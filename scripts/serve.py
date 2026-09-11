"""Re-solve service.

    python scripts/serve.py            # http://127.0.0.1:8000

The web UI works perfectly well without this running -- it reads a static plan.json and
the what-if simulator prices moves client-side. What the service adds is the other half
of the loop: take the planner's moves as fixed and re-optimise everything else around
them. So the button appears only when /api/health answers, and the page degrades to
explore-only when it does not. That matters when you are demonstrating on a laptop that
is not yours.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from samanvay.domain import Department  # noqa: E402
from samanvay.governance import (  # noqa: E402
    Actor,
    ApprovalWorkflow,
    AuditLog,
    AuthorityError,
    Role,
    WorkflowError,
)
from samanvay.optimizer.cpsat import OptimiserWeights  # noqa: E402
from samanvay.session import Pin, PlanningSession  # noqa: E402

# Persisted so the trail survives a restart -- an audit log that evaporates with the
# process is not an audit log.
AUDIT_PATH = Path(__file__).resolve().parents[1] / "out" / "audit.jsonl"
audit = AuditLog(AUDIT_PATH)
workflow = ApprovalWorkflow(audit)

app = FastAPI(title="SAMANVAY re-solve", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_session: PlanningSession | None = None
_last_plan = None
_plan_counter = 0


def _actor(name: str | None, role: str | None) -> Actor:
    """Stand-in for real authentication.

    A production deployment binds this to the divisional directory; the workflow rules
    are the same either way, and keeping the seam explicit is better than pretending
    there is an identity system here when there is not.
    """
    try:
        parsed = Role(role) if role else Role.VIEWER
    except ValueError:
        raise HTTPException(status_code=400, detail=f"unknown role {role!r}")
    return Actor(name or "unknown", parsed)


def session() -> PlanningSession:
    """Built once, on first use. Model fitting is the slow part; solving is not."""
    global _session
    if _session is None:
        _session = PlanningSession(horizon_days=7, n_tasks=200, seed=42)
    return _session


class PinIn(BaseModel):
    block_id: str
    start_min: int
    task_ids: list[str]


class Weights(BaseModel):
    criticality: float = 1.0
    clubbing: float = 25.0
    traffic: float = 0.05
    overdue: float = 1.5
    corridor: float = 40.0


class ResolveRequest(BaseModel):
    plan_id: str | None = None
    actor: str | None = None
    role: str | None = None
    pins: list[PinIn] = Field(default_factory=list)
    weights: Weights | None = None
    time_limit_s: float = Field(default=20.0, ge=2.0, le=120.0)
    warm_start: bool = True


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "ready": _session is not None}


@app.get("/api/plan")
def plan(time_limit_s: float = 20.0) -> dict:
    """The unpinned plan. Same shape as plan.json."""
    global _last_plan
    result = session().solve(time_limit_s=time_limit_s)
    _last_plan = result.plan
    return result.payload


@app.post("/api/resolve")
def resolve(req: ResolveRequest) -> dict:
    """Re-optimise with the planner's moves held fixed."""
    global _last_plan
    s = session()

    weights = (
        OptimiserWeights(**req.weights.model_dump()) if req.weights else OptimiserWeights()
    )
    pins = [Pin(p.block_id, p.start_min, p.task_ids) for p in req.pins]

    result = s.solve(
        weights=weights,
        pins=pins,
        time_limit_s=req.time_limit_s,
        warm_start=_last_plan if req.warm_start else None,
    )

    if not result.plan.blocks and result.rejected:
        raise HTTPException(
            status_code=422,
            detail={"message": "No feasible plan with those pins", "rejected": result.rejected},
        )

    _last_plan = result.plan

    # A re-solve is a human changing the plan. It is recorded as such, and it resets
    # any concurrence already given -- those were granted to a different plan.
    global _plan_counter
    plan_id = req.plan_id or f"PLAN-{_plan_counter:04d}"
    if plan_id in workflow.plans:
        try:
            workflow.modify(plan_id, _actor(req.actor, req.role),
                            note=f"re-solved around {len(pins)} pinned block(s)",
                            pinned=[p.block_id for p in pins])
        except WorkflowError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    return result.payload


# --------------------------------------------------------------------------- #
# Approval workflow
# --------------------------------------------------------------------------- #

class ActorIn(BaseModel):
    actor: str
    role: str
    remarks: str = ""


class CreateIn(ActorIn):
    plan_id: str
    departments: list[str] = Field(default_factory=lambda: ["ENGG", "S&T", "TRD"])


class ConcurIn(ActorIn):
    department: str
    granted: bool = True


def _handle(fn):
    try:
        return fn()
    except AuthorityError as exc:
        # 403: the role is not permitted. The refusal is already in the audit log.
        raise HTTPException(status_code=403, detail=str(exc))
    except WorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/api/plans/{plan_id}/submit")
def submit(plan_id: str, body: CreateIn) -> dict:
    """Put a plan into the approval route."""
    depts = {Department(d) for d in body.departments}
    _handle(lambda: workflow.create(
        plan_id, depts, _actor(body.actor, body.role), note=body.remarks))
    return workflow.status(plan_id)


@app.post("/api/plans/{plan_id}/concur")
def concur(plan_id: str, body: ConcurIn) -> dict:
    dept = Department(body.department)
    _handle(lambda: workflow.concur(plan_id, _actor(body.actor, body.role), dept,
                                    granted=body.granted, remarks=body.remarks))
    return workflow.status(plan_id)


@app.post("/api/plans/{plan_id}/clear")
def clear(plan_id: str, body: ActorIn) -> dict:
    _handle(lambda: workflow.clear_operations(
        plan_id, _actor(body.actor, body.role), remarks=body.remarks))
    return workflow.status(plan_id)


@app.post("/api/plans/{plan_id}/sanction")
def sanction(plan_id: str, body: ActorIn) -> dict:
    """The only endpoint that makes a plan operative. DRM only."""
    _handle(lambda: workflow.sanction(
        plan_id, _actor(body.actor, body.role), remarks=body.remarks))
    return workflow.status(plan_id)


@app.post("/api/plans/{plan_id}/return")
def return_plan(plan_id: str, body: ActorIn) -> dict:
    _handle(lambda: workflow.return_for_revision(
        plan_id, _actor(body.actor, body.role), remarks=body.remarks))
    return workflow.status(plan_id)


@app.get("/api/plans/{plan_id}/status")
def plan_status(plan_id: str) -> dict:
    return _handle(lambda: workflow.status(plan_id))


@app.get("/api/plans/{plan_id}/audit")
def plan_audit(plan_id: str) -> dict:
    chain = audit.verify()
    return {
        "plan_id": plan_id,
        "entries": [e.to_dict() for e in audit.for_plan(plan_id)],
        "chain": {"intact": chain.intact, "entries": chain.entries,
                  "broken_at": chain.broken_at, "reason": chain.reason},
    }


@app.get("/api/audit/verify")
def audit_verify() -> dict:
    """Anyone may check the trail has not been rewritten."""
    chain = audit.verify()
    return {"intact": chain.intact, "entries": chain.entries,
            "broken_at": chain.broken_at, "reason": chain.reason,
            "head": audit.head_hash}


if __name__ == "__main__":
    import uvicorn

    print("Warming the planning session (generating estate, fitting models)...")
    session()
    print("Ready. POST /api/resolve to re-solve with pinned blocks.")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
