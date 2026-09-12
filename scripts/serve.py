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

from fastapi import Depends, FastAPI, Header, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from samanvay.domain import Department  # noqa: E402
from samanvay.governance import (  # noqa: E402
    Actor,
    AuthenticationError,
    PlanStore,
    PlanStoreError,
    load_or_bootstrap,
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

# Every revision of every plan, so a sanction can be shown and not merely asserted. The
# audit log says what was decided; this says what it was decided about.
PLAN_STORE_PATH = Path(__file__).resolve().parents[1] / "out" / "plans"
plans = PlanStore(PLAN_STORE_PATH)

# Who the service will accept. On first run this mints one token per role and prints
# them once; thereafter it reads the hashes. There is deliberately no "no identity file
# means trust the caller" path -- that would be an authentication system with a hole
# beside it, and the hole is what would get used.
IDENTITY_PATH = Path(__file__).resolve().parents[1] / "out" / "identities.json"
identities, _minted = load_or_bootstrap(IDENTITY_PATH)
if _minted:
    print()
    print("=" * 72)
    print("  FIRST RUN -- bearer tokens minted. Shown once here and never stored.")
    print(f"  Only their hashes go to {IDENTITY_PATH}")
    print("=" * 72)
    for role, token in _minted.items():
        print(f"  {role:12} {token}")
    print("=" * 72)
    print("  Use one as:  Authorization: Bearer <token>")
    print("  Lost a token? Delete the file above and restart to mint a fresh set.")
    print()
    # Flushed explicitly. stdout is block-buffered when it is a file or a pipe, and a
    # server does not exit -- so without this the one-time secrets sit in a buffer
    # forever and are unrecoverable, because only their hashes were stored. Found by
    # starting the service with its output redirected and getting an empty log.
    sys.stdout.flush()

app = FastAPI(title="TRACKSEN re-solve", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_session: PlanningSession | None = None
_last_plan = None
_plan_counter = 0


def caller(authorization: str = Header(default="")) -> Actor:
    """The authenticated caller, from the bearer token. FastAPI dependency.

    The request body has no say in this. It used to: `{"actor": "...", "role": "DRM"}`
    was taken at face value, which meant every rule in the approval route was one JSON
    field away from being nothing. The role now comes from the identity store and the
    body's copy is gone rather than ignored -- a field that is sometimes trusted
    eventually is.
    """
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=401,
            detail="an approval action needs a bearer token: Authorization: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return identities.resolve(token.strip())
    except AuthenticationError as exc:
        # 401, not 403. The caller has not established who they are; telling them they
        # lack permission would send them looking for the wrong problem.
        raise HTTPException(status_code=401, detail=str(exc),
                            headers={"WWW-Authenticate": "Bearer"})


def _next_plan_id() -> str:
    """Allocate an unused plan id.

    The counter lives in memory and the workflow's plans are replayed from the audit log
    on startup, so a restart used to hand the next caller PLAN-0001 again -- an id that
    already belonged to somebody. The re-solve path treats an existing id as "modify this
    plan", so that collision would have wiped a stranger's concurrences and written the
    change into the audit trail against their plan. Skipping ids already in use is the
    whole fix.
    """
    global _plan_counter
    while True:
        _plan_counter += 1
        plan_id = f"PLAN-{_plan_counter:04d}"
        if plan_id not in workflow.plans:
            return plan_id


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
    pins: list[PinIn] = Field(default_factory=list)
    weights: Weights | None = None
    time_limit_s: float = Field(default=20.0, ge=2.0, le=120.0)
    warm_start: bool = True


@app.get("/api/health")
def health() -> dict:
    """Health, plus the topology this process is actually holding.

    The planning session is built once and reused, so a service left running across a
    change to the network keeps serving the old one. Publishing the section fingerprint
    lets the client notice that rather than quietly adopting a different division.
    """
    from samanvay.network import ROUTES, SECTIONS, STATIONS

    return {
        "ok": True,
        "ready": _session is not None,
        "topology": {
            "from": STATIONS[0].code,
            "to": STATIONS[-1].code,
            "sections": len(SECTIONS),
            "routes": [r.id for r in ROUTES],
            "fingerprint": "|".join(s.id for s in SECTIONS),
        },
    }


def _store_plan(plan_id: str, revision: int, plan, metrics=None) -> None:
    """Persist a revision, without letting a storage fault lose the approval.

    The workflow transition has already happened and is already in the audit log by the
    time this runs. Raising here would fail the request after the fact was recorded,
    leaving the caller thinking their submission was refused when the trail says it was
    accepted -- a worse state than a plan that cannot be displayed.
    """
    try:
        plans.save(plan_id, revision, plan,
                   {k: v.__dict__ for k, v in (metrics or {}).items()} or None)
    except (PlanStoreError, OSError) as exc:
        print(f"WARNING: plan {plan_id} r{revision} was approved but not stored: {exc}",
              file=sys.stderr, flush=True)


@app.get("/api/me")
def me(actor: Actor = Depends(caller)) -> dict:
    """Who the presented token belongs to.

    The client shows the role this returns rather than one the user picked. A role
    selector on the client was always decoration; this is where the answer lives.
    """
    return {"name": actor.name, "role": actor.role.value}


@app.get("/api/plan")
def plan(time_limit_s: float = 20.0) -> dict:
    """The unpinned plan. Same shape as plan.json."""
    global _last_plan
    result = session().solve(time_limit_s=time_limit_s)
    _last_plan = result.plan
    return result.payload


@app.post("/api/resolve")
def resolve(req: ResolveRequest,
            authorization: str = Header(default="")) -> dict:
    """Re-optimise with the planner's moves held fixed.

    Authentication is required only when this touches a plan already in the approval
    route, because re-solving one invalidates every concurrence given to it. Exploring a
    fresh plan changes nothing anybody signed, and gating it would put a login in front
    of the thing a planner is meant to play with.
    """
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
    plan_id = req.plan_id or _next_plan_id()
    if plan_id in workflow.plans:
        actor = caller(authorization)      # 401 here rather than a silent no-op
        try:
            workflow.modify(plan_id, actor,
                            note=f"re-solved around {len(pins)} pinned block(s)",
                            plan_hash=result.plan.content_hash(),
                            pinned=[p.block_id for p in pins])
        except WorkflowError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        # A re-solve of a plan under approval is a new revision of it, and the old one
        # is what the concurrences it just invalidated were given to. Both are kept.
        _store_plan(plan_id, workflow.plans[plan_id].revision, result.plan,
                    result.metrics)

    return result.payload


# --------------------------------------------------------------------------- #
# Approval workflow
# --------------------------------------------------------------------------- #

class ActorIn(BaseModel):
    """Remarks only. Identity comes from the token, never from the body."""

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


def _department(value: str) -> Department:
    """Parse a department code, or refuse it as bad input rather than as a crash.

    `Department("ENG")` raises ValueError, which FastAPI turns into a 500 -- an error
    that reads as "the service is broken" when the truth is "you sent a code that does
    not exist". The client cannot tell those apart, so it is worth separating.
    """
    try:
        return Department(value)
    except ValueError:
        known = ", ".join(d.value for d in Department)
        raise HTTPException(
            status_code=422,
            detail=f"unknown department {value!r}; expected one of: {known}",
        )


@app.post("/api/plans/{plan_id}/submit")
def submit(plan_id: str, body: CreateIn, actor: Actor = Depends(caller)) -> dict:
    """Put a plan into the approval route."""
    if body.plan_id != plan_id:
        raise HTTPException(
            status_code=422,
            detail=("plan id in the request body must match the plan id in the URL "
                    f"({body.plan_id!r} != {plan_id!r})"),
        )
    depts = {_department(d) for d in body.departments}
    # The fingerprint of the plan being submitted. Without it the trail records that a
    # plan was approved but not which plan, and "PLAN-0007 was sanctioned" could later be
    # attached to any set of blocks at all.
    if _last_plan is None:
        raise HTTPException(
            status_code=409,
            detail=("no plan has been solved yet, so there is nothing to submit. "
                    "Call /api/plan or /api/resolve first."),
        )
    plan_hash = _last_plan.content_hash()
    _handle(lambda: workflow.create(
        plan_id, depts, actor, plan_hash=plan_hash, note=body.remarks))

    # Stored after the workflow accepted it, so a refused submission leaves nothing
    # behind claiming to be under approval.
    _store_plan(plan_id, workflow.plans[plan_id].revision, _last_plan)
    return workflow.status(plan_id)


@app.post("/api/plans/{plan_id}/concur")
def concur(plan_id: str, body: ConcurIn, actor: Actor = Depends(caller)) -> dict:
    dept = _department(body.department)
    _handle(lambda: workflow.concur(plan_id, actor, dept,
                                    granted=body.granted, remarks=body.remarks))
    return workflow.status(plan_id)


@app.post("/api/plans/{plan_id}/clear")
def clear(plan_id: str, body: ActorIn, actor: Actor = Depends(caller)) -> dict:
    _handle(lambda: workflow.clear_operations(
        plan_id, actor, remarks=body.remarks))
    return workflow.status(plan_id)


@app.post("/api/plans/{plan_id}/sanction")
def sanction(plan_id: str, body: ActorIn, actor: Actor = Depends(caller)) -> dict:
    """The only endpoint that makes a plan operative. DRM only."""
    _handle(lambda: workflow.sanction(
        plan_id, actor, remarks=body.remarks))
    return workflow.status(plan_id)


@app.post("/api/plans/{plan_id}/return")
def return_plan(plan_id: str, body: ActorIn, actor: Actor = Depends(caller)) -> dict:
    _handle(lambda: workflow.return_for_revision(
        plan_id, actor, remarks=body.remarks))
    return workflow.status(plan_id)


@app.get("/api/plans/{plan_id}/status")
def plan_status(plan_id: str) -> dict:
    return _handle(lambda: workflow.status(plan_id))


@app.get("/api/plans/{plan_id}/plan")
def stored_plan(plan_id: str, revision: int | None = None) -> dict:
    """The plan content behind a plan id: what was actually approved.

    Checked, not just returned. `intact` says the stored file still hashes to the value
    saved with it; `matches_sanctioned` says it is the revision the DRM signed, by
    comparing against the hash in the approval state. Returning the content without
    either would be an assertion, and an assertion is what this exists to replace.
    """
    try:
        stored = plans.load(plan_id, revision)
    except PlanStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if stored is None:
        raise HTTPException(
            status_code=404,
            detail=(f"no stored content for plan {plan_id}"
                    + (f" revision {revision}" if revision is not None else "")),
        )

    approval = workflow.plans.get(plan_id)
    sanctioned_hash = approval.sanctioned_hash if approval else None
    return {
        **stored.to_dict(),
        "revisions": plans.revisions(plan_id),
        "intact": stored.intact,
        "sanctioned_hash": sanctioned_hash,
        "matches_sanctioned": stored.matches(sanctioned_hash),
    }


@app.get("/api/plans/{plan_id}/audit")
def plan_audit(plan_id: str) -> dict:
    chain = audit.verify()
    return {
        "plan_id": plan_id,
        "entries": [e.to_dict() for e in audit.for_plan(plan_id)],
        "chain": {"intact": chain.intact, "entries": chain.entries,
                  "broken_at": chain.broken_at, "reason": chain.reason},
    }


@app.get("/api/sources")
def sources() -> dict:
    """Live adapter status for TMS / SMMS / TDMS.

    Runs the real ingestion ladder and reports which mode each source answered on and
    why the better ones were skipped. The feeds are the mock systems written by
    `export_all()`, so `demo` is true and the UI must say so -- reporting a synthetic
    feed as a live departmental connection would be the one dishonest thing this panel
    could do.
    """
    from samanvay.generator import generate_dataset
    from samanvay.ingestion import export_all, ingest

    out_dir = Path(__file__).resolve().parents[1] / "out" / "sources"
    ds = generate_dataset(n_pending=200, seed=42)
    specs = export_all(ds.pending, out_dir)
    result = ingest(specs)

    return {
        "demo": True,
        "note": "Synthetic feeds written by export_all(); not live departmental systems.",
        "sources": [
            {
                "system": r.system,
                "mode": r.mode,
                "connected": r.mode != "unavailable",
                "degraded": r.degraded,
                "attempted": r.attempted,
                "skipped": r.skipped,
                "fetched": r.fetched,
                "accepted": r.accepted,
                "rejected": [str(x) for x in r.rejected],
                "duplicates": r.duplicates,
                "error": r.error,
            }
            for r in result.reports
        ],
        "unified_tasks": len(result.tasks),
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
