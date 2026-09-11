"""Who may do what to a block plan, and in what order.

The route a real block demand travels, and the one modelled here:

    JE / SSE raises
        -> Sr.DEN / Sr.DSTE / Sr.DEE concur, each for their own department only
            -> Sr.DOM clears the traffic impact
                -> DRM sanctions

SAMANVAY produces the plan. It does not sanction it, and this module is where that
stops being a sentence in a README and becomes a rule the code enforces:

  * **Only the DRM can sanction.** Every other role attempting it raises.
  * **A department head concurs for their own department and no other.** Sr.DSTE cannot
    sign off Engineering's work; that is someone else's accountability.
  * **Sanction requires every department present in the plan to have concurred, and
    operations to have cleared.** The order cannot be skipped, and a withheld concurrence
    blocks it outright.
  * **A sanctioned plan cannot be edited.** Changing sanctioned work means superseding it
    with a new plan that travels the route again, because the thing that was approved must
    remain the thing that was approved.

Every transition is written to the hash-chained audit log before it takes effect.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field
from copy import deepcopy
import hashlib
import json
from threading import RLock
from enum import Enum

from ..domain import Department, Plan, ScheduledBlock, Line, BlockType
from .audit import Action, AuditLog


class Role(str, Enum):
    JE = "JE"                  # Junior/Section Engineer -- raises and revises
    SR_DEN = "Sr.DEN"          # Engineering
    SR_DSTE = "Sr.DSTE"        # Signal & Telecom
    SR_DEE = "Sr.DEE/TrD"      # Traction Distribution
    SR_DOM = "Sr.DOM"          # Operations -- traffic clearance
    DRM = "DRM"                # Divisional Railway Manager -- sanction
    VIEWER = "Viewer"          # read-only


# Which department each head may concur for. Nobody signs for another's work.
CONCURRENCE_AUTHORITY: dict[Role, Department] = {
    Role.SR_DEN: Department.ENGINEERING,
    Role.SR_DSTE: Department.SIGNAL,
    Role.SR_DEE: Department.TRACTION,
}

DEPARTMENT_HEAD: dict[Department, Role] = {v: k for k, v in CONCURRENCE_AUTHORITY.items()}


class PlanState(str, Enum):
    DRAFT = "DRAFT"
    UNDER_CONCURRENCE = "UNDER_CONCURRENCE"
    OPERATIONS_REVIEW = "OPERATIONS_REVIEW"
    SANCTIONED = "SANCTIONED"
    RETURNED = "RETURNED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in (PlanState.SUPERSEDED, PlanState.CANCELLED)


class AuthorityError(PermissionError):
    """Raised when someone attempts something their role does not permit."""


class WorkflowError(RuntimeError):
    """Raised when an action is legal for the role but wrong for the current state."""


@dataclass
class Concurrence:
    department: Department
    granted: bool
    actor: str
    role: str
    timestamp: str
    remarks: str = ""


@dataclass
class Actor:
    name: str
    role: Role

    def may_concur_for(self, dept: Department) -> bool:
        return CONCURRENCE_AUTHORITY.get(self.role) is dept


@dataclass
class PlanApproval:
    """The workflow state of one plan, and the gate in front of sanction."""

    plan_id: str
    departments: set[Department]
    state: PlanState = PlanState.DRAFT
    concurrences: dict[Department, Concurrence] = field(default_factory=dict)
    operations_cleared_by: str | None = None
    sanctioned_by: str | None = None
    sanctioned_at: str | None = None
    superseded_by: str | None = None
    revision: int = 1
    snapshot_json: str = ""

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.snapshot_json.encode()).hexdigest()

    def plan(self) -> Plan:
        data = json.loads(self.snapshot_json)["plan"]
        blocks = []
        for row in data.pop("blocks"):
            row["line"] = Line(row["line"])
            row["departments"] = [Department(d) for d in row["departments"]]
            row["block_types"] = [BlockType(b) for b in row["block_types"]]
            blocks.append(ScheduledBlock(**row))
        return Plan(blocks=blocks, **data)

    @property
    def context(self) -> dict:
        return json.loads(self.snapshot_json)["context"]

    # ------------------------------------------------------------------ #
    # Gate conditions
    # ------------------------------------------------------------------ #

    @property
    def pending_departments(self) -> set[Department]:
        return {d for d in self.departments if d not in self.concurrences}

    @property
    def withheld(self) -> list[Concurrence]:
        return [c for c in self.concurrences.values() if not c.granted]

    @property
    def fully_concurred(self) -> bool:
        return not self.pending_departments and not self.withheld

    @property
    def ready_for_sanction(self) -> bool:
        return (self.state is PlanState.OPERATIONS_REVIEW and bool(self.snapshot_json)
                and self.fully_concurred and self.operations_cleared_by is not None)

    def blockers(self) -> list[str]:
        """Why this plan cannot be sanctioned right now, in plain language."""
        out: list[str] = []
        if self.state is PlanState.SANCTIONED:
            out.append("already sanctioned")
        if self.state.is_terminal:
            out.append(f"plan is {self.state.value.lower()}")
        if self.state is PlanState.RETURNED:
            out.append("plan was returned and must be revised")
        for d in sorted(self.pending_departments, key=lambda x: x.value):
            out.append(f"{DEPARTMENT_HEAD[d].value} has not concurred for {d.value}")
        for c in self.withheld:
            out.append(
                f"{c.role} withheld concurrence for {c.department.value}"
                + (f": {c.remarks}" if c.remarks else "")
            )
        if self.operations_cleared_by is None:
            out.append(f"{Role.SR_DOM.value} has not cleared the traffic impact")
        return out


class ApprovalWorkflow:
    """Single-writer workflow; durable audit events are also its replayable state store.

    A transition is computed on a copy and published only after the audit append has
    completed. Serve one process; the lock also guards revision checks and re-solves.
    """

    def __init__(self, log: AuditLog):
        self.log = log
        self.lock = RLock()
        self.plans: dict[str, PlanApproval] = {}
        if not log.verify().intact:
            raise WorkflowError("audit log is corrupt; refusing to restore approvals")
        for entry in log:
            row = entry.detail.get("approval")
            if row is None:  # Legacy metadata-only events cannot restore approval authority.
                continue
            row = deepcopy(row)
            row["departments"] = {Department(d) for d in row["departments"]}
            row["state"] = PlanState(row["state"])
            row["concurrences"] = {
                Department(d): Concurrence(**{**c, "department": Department(c["department"])})
                for d, c in row["concurrences"].items()
            }
            approval = PlanApproval(**row)
            self.plans[approval.plan_id] = approval

    def _require(self, plan_id: str) -> PlanApproval:
        if plan_id not in self.plans:
            raise WorkflowError(f"unknown plan {plan_id}")
        return deepcopy(self.plans[plan_id])

    def _deny(self, actor, attempted, plan_id, reason, error=AuthorityError):
        self.log.append(actor=actor.name, role=actor.role.value, action=Action.DENIED,
                        plan_id=plan_id, detail={"attempted": attempted.value, "reason": reason})
        raise error(reason)

    def _commit(self, a, actor, action, **detail):
        row = asdict(a)
        row["departments"] = sorted(d.value for d in a.departments)
        row["concurrences"] = {d.value: asdict(c) for d, c in a.concurrences.items()}
        self.log.append(actor=actor.name, role=actor.role.value, action=action,
                        plan_id=a.plan_id, detail={**detail, "revision": a.revision,
                        "content_hash": a.content_hash, "approval": row})
        self.plans[a.plan_id] = a
        return deepcopy(a)

    @staticmethod
    def _snapshot(plan: Plan, context: dict | None = None) -> str:
        if not plan.blocks or not all(b.task_ids and b.departments for b in plan.blocks):
            raise WorkflowError("cannot approve an empty or unbound schedule")
        return json.dumps({"plan": asdict(plan), "context": context or {}},
                          sort_keys=True, separators=(",", ":"), allow_nan=False)

    def create(self, plan_id: str, plan: Plan, actor: Actor, *, context=None, **detail):
        with self.lock:
            if actor.role is not Role.JE:
                self._deny(actor, Action.CREATE, plan_id, "only JE may raise a proposal")
            if plan_id in self.plans:
                raise WorkflowError(f"plan {plan_id} already exists")
            snapshot = self._snapshot(plan, context)
            a = PlanApproval(plan_id, {d for b in plan.blocks for d in b.departments},
                             snapshot_json=snapshot)
            return self._commit(a, actor, Action.CREATE, **detail)

    def check_revision(self, plan_id: str, revision: int, content_hash: str):
        a = self._require(plan_id)
        if a.revision != revision or a.content_hash != content_hash:
            raise WorkflowError("stale plan revision; reload the proposal before acting")
        return a

    def check_editable(self, plan_id, actor):
        a = self._require(plan_id)
        if actor.role is not Role.JE:
            self._deny(actor, Action.MODIFY, plan_id, "only JE may revise a proposal")
        if a.state is PlanState.SANCTIONED:
            self._deny(actor, Action.MODIFY, plan_id,
                       "a sanctioned plan cannot be modified -- supersede it with a new plan",
                       WorkflowError)
        if a.state.is_terminal:
            self._deny(actor, Action.MODIFY, plan_id, f"plan is {a.state.value.lower()}", WorkflowError)
        return a

    def modify(self, plan_id, actor, *, plan=None, context=None, note="", **detail):
        with self.lock:
            a = self.check_editable(plan_id, actor)
            invalidated = sorted(d.value for d in a.concurrences)
            if plan is not None:
                a.snapshot_json = self._snapshot(plan, context if context is not None else a.context)
                a.departments = {d for b in plan.blocks for d in b.departments}
            a.concurrences.clear()
            a.operations_cleared_by = None
            a.state = PlanState.DRAFT
            a.revision += 1
            return self._commit(a, actor, Action.MODIFY, note=note,
                                invalidated_concurrences=invalidated, **detail)

    def _review_state(self, a, actor, action):
        if a.state not in (PlanState.DRAFT, PlanState.UNDER_CONCURRENCE,
                           PlanState.OPERATIONS_REVIEW):
            self._deny(actor, action, a.plan_id, f"plan is {a.state.value.lower()}", WorkflowError)

    def concur(self, plan_id, actor, department, granted=True, remarks=""):
        with self.lock:
            a = self._require(plan_id)
            if not actor.may_concur_for(department):
                self._deny(actor, Action.CONCUR, plan_id,
                           f"{actor.role.value} cannot concur for {department.value} -- "
                           f"that is {DEPARTMENT_HEAD[department].value}'s accountability")
            self._review_state(a, actor, Action.CONCUR)
            if department not in a.departments:
                raise WorkflowError(f"plan {plan_id} contains no {department.value} work")
            a.operations_cleared_by = None
            a.concurrences[department] = Concurrence(department, granted, actor.name,
                actor.role.value, dt.datetime.now(dt.timezone.utc).isoformat(), remarks)
            a.state = PlanState.OPERATIONS_REVIEW if a.fully_concurred else PlanState.UNDER_CONCURRENCE
            return self._commit(a, actor, Action.CONCUR if granted else Action.WITHHOLD,
                                department=department.value, remarks=remarks)

    def clear_operations(self, plan_id, actor, remarks=""):
        with self.lock:
            a = self._require(plan_id)
            if actor.role is not Role.SR_DOM:
                self._deny(actor, Action.CLEAR, plan_id, "only Sr.DOM may clear traffic impact")
            self._review_state(a, actor, Action.CLEAR)
            if not a.fully_concurred:
                raise WorkflowError("operations clearance comes after departmental concurrence: "
                                    + "; ".join(a.blockers()))
            a.operations_cleared_by = actor.name
            a.state = PlanState.OPERATIONS_REVIEW
            return self._commit(a, actor, Action.CLEAR, remarks=remarks)

    def sanction(self, plan_id, actor, remarks=""):
        with self.lock:
            a = self._require(plan_id)
            if actor.role is not Role.DRM:
                self._deny(actor, Action.SANCTION, plan_id, "only the DRM can sanction a block plan")
            if not a.ready_for_sanction:
                self._deny(actor, Action.SANCTION, plan_id,
                           "cannot sanction: " + "; ".join(a.blockers()), WorkflowError)
            a.state = PlanState.SANCTIONED
            a.sanctioned_by = actor.name
            a.sanctioned_at = dt.datetime.now(dt.timezone.utc).isoformat()
            return self._commit(a, actor, Action.SANCTION, remarks=remarks)

    def return_for_revision(self, plan_id, actor, remarks):
        with self.lock:
            a = self._require(plan_id)
            if actor.role in (Role.VIEWER, Role.JE):
                self._deny(actor, Action.RETURN, plan_id, "role cannot return a plan for revision")
            self._review_state(a, actor, Action.RETURN)
            a.state = PlanState.RETURNED
            a.concurrences.clear()
            a.operations_cleared_by = None
            return self._commit(a, actor, Action.RETURN, remarks=remarks)

    def supersede(self, plan_id, successor_id, actor, remarks=""):
        with self.lock:
            a = self._require(plan_id)
            if actor.role is not Role.DRM:
                self._deny(actor, Action.SUPERSEDE, plan_id, "only DRM may supersede a plan")
            if a.state is not PlanState.SANCTIONED:
                raise WorkflowError("only a sanctioned plan can be superseded")
            successor = self._require(successor_id)
            if successor_id == plan_id or successor.state.is_terminal:
                raise WorkflowError("invalid successor proposal")
            a.state = PlanState.SUPERSEDED
            a.superseded_by = successor_id
            return self._commit(a, actor, Action.SUPERSEDE, superseded_by=successor_id, remarks=remarks)

    def cancel(self, plan_id, actor, remarks):
        with self.lock:
            a = self._require(plan_id)
            if actor.role not in (Role.DRM, Role.SR_DOM):
                self._deny(actor, Action.CANCEL, plan_id, "role cannot cancel a sanctioned plan")
            if a.state is not PlanState.SANCTIONED:
                raise WorkflowError("only a sanctioned plan can be cancelled")
            a.state = PlanState.CANCELLED
            return self._commit(a, actor, Action.CANCEL, remarks=remarks)

    def status(self, plan_id):
        with self.lock:
            a = self._require(plan_id)
            return {"plan_id": a.plan_id, "state": a.state.value, "revision": a.revision,
                    "content_hash": a.content_hash,
                    "departments": sorted(d.value for d in a.departments),
                    "concurrences": {d.value: {"granted": c.granted, "by": c.actor,
                        "role": c.role, "at": c.timestamp, "remarks": c.remarks}
                        for d, c in a.concurrences.items()},
                    "operations_cleared_by": a.operations_cleared_by,
                    "sanctioned_by": a.sanctioned_by, "sanctioned_at": a.sanctioned_at,
                    "ready_for_sanction": a.ready_for_sanction, "blockers": a.blockers()}
