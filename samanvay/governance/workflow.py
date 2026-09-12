"""Who may do what to a block plan, and in what order.

The route a real block demand travels, and the one modelled here:

    JE / SSE raises
        -> Sr.DEN / Sr.DSTE / Sr.DEE concur, each for their own department only
            -> Sr.DOM clears the traffic impact
                -> DRM sanctions

TRACKSEN produces the plan. It does not sanction it, and this module is where that
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
from dataclasses import dataclass, field
from enum import Enum

from ..domain import Department
from .audit import Action, AuditEntry, AuditLog


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
    # Fingerprint of the plan content this approval refers to. Set on create, replaced on
    # every modify, and recorded again at sanction -- so what was signed is recoverable.
    plan_hash: str | None = None
    sanctioned_hash: str | None = None
    sanctioned_by: str | None = None
    sanctioned_at: str | None = None
    superseded_by: str | None = None
    revision: int = 1

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
        return self.fully_concurred and self.operations_cleared_by is not None

    def blockers(self) -> list[str]:
        """Why this plan cannot be sanctioned right now, in plain language."""
        out: list[str] = []
        if self.state is PlanState.SANCTIONED:
            out.append("already sanctioned")
        if self.state.is_terminal:
            out.append(f"plan is {self.state.value.lower()}")
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
    """Drives plans through the route, writing every step to the audit log first."""

    def __init__(self, log: AuditLog):
        self.log = log
        self.plans: dict[str, PlanApproval] = {}
        self._restore_from_audit()

    def _restore_from_audit(self) -> None:
        """Rebuild the current workflow state from the durable audit history.

        The audit log already survives a service restart, but until this replay existed
        the in-memory approval state did not.  A restarted service could therefore
        verify a sanction while refusing to find the sanctioned plan it described.
        Replay is deliberately side-effect free: it never calls transition methods and
        never appends a second copy of a historic event.
        """
        chain = self.log.verify()
        if not chain.intact:
            raise WorkflowError(f"cannot restore workflow: {chain}")

        for entry in self.log:
            self._apply_audit_entry(entry)

    def _restore_plan(self, entry: AuditEntry) -> PlanApproval:
        try:
            return self.plans[entry.plan_id]
        except KeyError as exc:
            raise WorkflowError(
                f"cannot restore audit entry {entry.seq}: unknown plan {entry.plan_id}"
            ) from exc

    def _apply_audit_entry(self, entry: AuditEntry) -> None:
        """Apply one previously verified entry without performing authorization checks."""
        try:
            action = Action(entry.action)
        except ValueError as exc:
            raise WorkflowError(
                f"cannot restore audit entry {entry.seq}: unknown action {entry.action!r}"
            ) from exc

        # Denied attempts are important evidence, but never changed plan state.
        if action is Action.DENIED:
            return

        if action is Action.CREATE:
            if entry.plan_id in self.plans:
                raise WorkflowError(
                    f"cannot restore audit entry {entry.seq}: duplicate plan {entry.plan_id}"
                )
            try:
                departments = {Department(d) for d in entry.detail["departments"]}
            except (KeyError, TypeError, ValueError) as exc:
                raise WorkflowError(
                    f"cannot restore audit entry {entry.seq}: invalid CREATE departments"
                ) from exc
            self.plans[entry.plan_id] = PlanApproval(
                plan_id=entry.plan_id, departments=departments,
                plan_hash=entry.detail.get("plan_hash") or None,
            )
            return

        plan = self._restore_plan(entry)

        if action is Action.MODIFY:
            plan.concurrences.clear()
            plan.operations_cleared_by = None
            plan.state = PlanState.DRAFT
            plan.revision = int(entry.detail.get("revision", plan.revision + 1))
            if entry.detail.get("plan_hash"):
                plan.plan_hash = entry.detail["plan_hash"]
            return

        if action in (Action.CONCUR, Action.WITHHOLD):
            try:
                department = Department(entry.detail["department"])
            except (KeyError, ValueError) as exc:
                raise WorkflowError(
                    f"cannot restore audit entry {entry.seq}: invalid concurrence department"
                ) from exc
            granted = action is Action.CONCUR
            plan.concurrences[department] = Concurrence(
                department=department,
                granted=granted,
                actor=entry.actor,
                role=entry.role,
                timestamp=entry.timestamp,
                remarks=str(entry.detail.get("remarks", "")),
            )
            plan.state = (
                PlanState.OPERATIONS_REVIEW if plan.fully_concurred
                else PlanState.UNDER_CONCURRENCE
            )
            return

        if action is Action.CLEAR:
            plan.operations_cleared_by = entry.actor
            plan.state = PlanState.OPERATIONS_REVIEW
            return

        if action is Action.SANCTION:
            plan.state = PlanState.SANCTIONED
            plan.sanctioned_by = entry.actor
            plan.sanctioned_at = entry.timestamp
            plan.revision = int(entry.detail.get("revision", plan.revision))
            plan.sanctioned_hash = entry.detail.get("plan_hash") or plan.plan_hash
            return

        if action is Action.RETURN:
            plan.state = PlanState.RETURNED
            return

        if action is Action.SUPERSEDE:
            plan.state = PlanState.SUPERSEDED
            plan.superseded_by = str(entry.detail.get("superseded_by", "")) or None
            return

        if action is Action.CANCEL:
            plan.state = PlanState.CANCELLED
            return

        # RESOLVE is a valid historical marker, but the present service currently
        # records re-solves as MODIFY. It carries no state of its own.
        if action is Action.RESOLVE:
            return

    # ------------------------------------------------------------------ #

    def _require(self, plan_id: str) -> PlanApproval:
        if plan_id not in self.plans:
            raise WorkflowError(f"unknown plan {plan_id}")
        return self.plans[plan_id]

    def _record(self, actor: Actor, action: Action, plan_id: str, **detail) -> None:
        self.log.append(actor=actor.name, role=actor.role.value, action=action,
                        plan_id=plan_id, detail=detail)

    def _deny(self, actor: Actor, attempted: Action, plan_id: str, reason: str,
              error: type[Exception] = AuthorityError):
        """Record the refusal, then raise.

        A refused attempt is exactly the event an audit trail exists to capture. Someone
        reaching above their authority -- or trying to sanction a plan two departments
        have not seen -- should leave a mark, not vanish because the code said no.
        """
        self.log.append(actor=actor.name, role=actor.role.value, action=Action.DENIED,
                        plan_id=plan_id,
                        detail={"attempted": attempted.value, "reason": reason})
        raise error(reason)

    # ------------------------------------------------------------------ #

    def create(self, plan_id: str, departments: set[Department], actor: Actor,
               plan_hash: str | None = None, **detail) -> PlanApproval:
        if plan_id in self.plans:
            raise WorkflowError(f"plan {plan_id} already exists")
        approval = PlanApproval(plan_id=plan_id, departments=set(departments),
                                plan_hash=plan_hash)
        self.plans[plan_id] = approval
        self._record(actor, Action.CREATE, plan_id,
                     departments=sorted(d.value for d in departments),
                     plan_hash=plan_hash, **detail)
        return approval

    def modify(self, plan_id: str, actor: Actor, *, note: str = "",
               plan_hash: str | None = None, **detail) -> PlanApproval:
        """A human changed the plan. Illegal once sanctioned -- supersede instead."""
        a = self._require(plan_id)
        if a.state is PlanState.SANCTIONED:
            self._deny(actor, Action.MODIFY, plan_id,
                       "a sanctioned plan cannot be modified -- supersede it with a "
                       "new plan", WorkflowError)
        if a.state.is_terminal:
            raise WorkflowError(f"plan is {a.state.value.lower()}")

        # Any change invalidates concurrences already given: they were given to a
        # different plan, and treating them as still valid would launder the change
        # through approvals nobody granted for it.
        invalidated = sorted(d.value for d in a.concurrences)
        a.concurrences.clear()
        a.operations_cleared_by = None
        a.state = PlanState.DRAFT
        a.revision += 1
        if plan_hash is not None:
            a.plan_hash = plan_hash

        self._record(actor, Action.MODIFY, plan_id, note=note, plan_hash=a.plan_hash,
                     revision=a.revision, invalidated_concurrences=invalidated, **detail)
        return a

    def concur(self, plan_id: str, actor: Actor, department: Department,
               granted: bool = True, remarks: str = "") -> PlanApproval:
        a = self._require(plan_id)
        if not actor.may_concur_for(department):
            self._deny(actor, Action.CONCUR, plan_id,
                       f"{actor.role.value} cannot concur for {department.value} -- "
                       f"that is {DEPARTMENT_HEAD[department].value}'s accountability")
        if department not in a.departments:
            raise WorkflowError(f"plan {plan_id} contains no {department.value} work")
        if a.state is PlanState.SANCTIONED or a.state.is_terminal:
            raise WorkflowError(f"plan is {a.state.value.lower()}")

        a.concurrences[department] = Concurrence(
            department=department, granted=granted, actor=actor.name,
            role=actor.role.value,
            timestamp=dt.datetime.now(dt.timezone.utc).isoformat(), remarks=remarks,
        )
        a.state = (
            PlanState.OPERATIONS_REVIEW if a.fully_concurred
            else PlanState.UNDER_CONCURRENCE
        )
        self._record(actor, Action.CONCUR if granted else Action.WITHHOLD, plan_id,
                     department=department.value, remarks=remarks)
        return a

    def clear_operations(self, plan_id: str, actor: Actor, remarks: str = "") -> PlanApproval:
        a = self._require(plan_id)
        if actor.role is not Role.SR_DOM:
            self._deny(actor, Action.CLEAR, plan_id,
                       f"{actor.role.value} cannot clear traffic impact -- that is Sr.DOM's")
        if not a.fully_concurred:
            raise WorkflowError(
                "operations clearance comes after departmental concurrence: "
                + "; ".join(a.blockers())
            )
        a.operations_cleared_by = actor.name
        a.state = PlanState.OPERATIONS_REVIEW
        self._record(actor, Action.CLEAR, plan_id, remarks=remarks)
        return a

    def sanction(self, plan_id: str, actor: Actor, remarks: str = "") -> PlanApproval:
        """The only place a plan becomes operative. DRM only, gate fully satisfied."""
        a = self._require(plan_id)
        if actor.role is not Role.DRM:
            self._deny(actor, Action.SANCTION, plan_id,
                       f"{actor.role.value} cannot sanction a block plan -- only the DRM can")
        if not a.ready_for_sanction:
            self._deny(actor, Action.SANCTION, plan_id,
                       "cannot sanction: " + "; ".join(a.blockers()), WorkflowError)

        a.state = PlanState.SANCTIONED
        a.sanctioned_by = actor.name
        a.sanctioned_at = dt.datetime.now(dt.timezone.utc).isoformat()
        # The hash goes into the sanction entry itself, not just the plan's state: this
        # is the line of the trail that says what the DRM actually put their name to.
        a.sanctioned_hash = a.plan_hash
        self._record(actor, Action.SANCTION, plan_id, remarks=remarks,
                     revision=a.revision, plan_hash=a.plan_hash)
        return a

    def return_for_revision(self, plan_id: str, actor: Actor, remarks: str) -> PlanApproval:
        a = self._require(plan_id)
        if actor.role in (Role.VIEWER, Role.JE):
            self._deny(actor, Action.RETURN, plan_id,
                       f"{actor.role.value} cannot return a plan for revision")
        if a.state is PlanState.SANCTIONED:
            raise WorkflowError("a sanctioned plan is returned by cancelling it")
        a.state = PlanState.RETURNED
        self._record(actor, Action.RETURN, plan_id, remarks=remarks)
        return a

    def supersede(self, plan_id: str, successor_id: str, actor: Actor,
                  remarks: str = "") -> PlanApproval:
        a = self._require(plan_id)
        a.state = PlanState.SUPERSEDED
        a.superseded_by = successor_id
        self._record(actor, Action.SUPERSEDE, plan_id,
                     superseded_by=successor_id, remarks=remarks)
        return a

    def cancel(self, plan_id: str, actor: Actor, remarks: str) -> PlanApproval:
        a = self._require(plan_id)
        if actor.role not in (Role.DRM, Role.SR_DOM):
            self._deny(actor, Action.CANCEL, plan_id,
                       f"{actor.role.value} cannot cancel a sanctioned plan")
        a.state = PlanState.CANCELLED
        self._record(actor, Action.CANCEL, plan_id, remarks=remarks)
        return a

    # ------------------------------------------------------------------ #

    def status(self, plan_id: str) -> dict:
        a = self._require(plan_id)
        return {
            "plan_id": a.plan_id,
            "state": a.state.value,
            "revision": a.revision,
            "departments": sorted(d.value for d in a.departments),
            "concurrences": {
                d.value: {
                    "granted": c.granted, "by": c.actor, "role": c.role,
                    "at": c.timestamp, "remarks": c.remarks,
                }
                for d, c in a.concurrences.items()
            },
            "operations_cleared_by": a.operations_cleared_by,
            "plan_hash": a.plan_hash,
            "sanctioned_hash": a.sanctioned_hash,
            "sanctioned_by": a.sanctioned_by,
            "sanctioned_at": a.sanctioned_at,
            "ready_for_sanction": a.ready_for_sanction,
            "blockers": a.blockers(),
        }
