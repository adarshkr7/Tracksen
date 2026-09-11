"""Local proposal service. Run one worker: python scripts/serve.py.

Schedules and approval states are persisted as atomic audit events. Identities remain
an explicit demo stand-in; bind _actor to authenticated identity before deployment.
"""
from __future__ import annotations

import hashlib
import json
import sys
import uuid
import warnings
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from samanvay.domain import Department
from samanvay.governance import Actor, ApprovalWorkflow, AuditLog, AuthorityError, Role, WorkflowError
from samanvay.optimizer.cpsat import OptimiserWeights, SolveReport
from samanvay.session import Pin, PlanningSession
from samanvay.serialize import plan_payload, dump_monthly
from samanvay.evaluate import evaluate

AUDIT_PATH = Path(__file__).resolve().parents[1] / "out" / "audit.jsonl"
audit = AuditLog(AUDIT_PATH)
workflow = ApprovalWorkflow(audit)
app = FastAPI(title="SAMANVAY proposals", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                   allow_methods=["GET", "POST"], allow_headers=["*"])
_session: PlanningSession | None = None
_last_plan = None


def _actor(name: str, role: str) -> Actor:
    try:
        return Actor(name, Role(role))
    except ValueError:
        raise HTTPException(400, detail=f"unknown role {role!r}")


def session() -> PlanningSession:
    global _session
    with workflow.lock:
        if _session is None:
            _session = PlanningSession(horizon_days=7, n_tasks=200, seed=42)
        return _session


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PinIn(Input):
    block_id: str
    start_min: int
    task_ids: list[str]


class Weights(Input):
    criticality: float = Field(1, ge=0, le=1000)
    clubbing: float = Field(25, ge=0, le=1000)
    traffic: float = Field(0.05, ge=0, le=1000)
    overdue: float = Field(1.5, ge=0, le=1000)
    corridor: float = Field(40, ge=0, le=1000)
    stability: float = Field(10, ge=0, le=1000)
    cancellation: float = Field(10, ge=0, le=1000)


class ActorIn(Input):
    actor: str = Field(min_length=1)
    role: str
    revision: int = Field(ge=1)
    content_hash: str = Field(min_length=64, max_length=64)
    remarks: str = ""


class ResolveRequest(ActorIn):
    plan_id: str
    pins: list[PinIn] = Field(default_factory=list)
    weights: Weights | None = None
    time_limit_s: float = Field(20, ge=2, le=120)
    warm_start: bool = True


class ConcurIn(ActorIn):
    department: Department
    granted: bool = True


def _handle(fn):
    try:
        return fn()
    except AuthorityError as exc:
        raise HTTPException(403, detail=str(exc))
    except WorkflowError as exc:
        raise HTTPException(409, detail=str(exc))
    except (OSError, RuntimeError) as exc:
        raise HTTPException(503, detail=f"proposal state could not be persisted: {exc}")


def _context(s):
    # Prevent restoring a proposal against a different task population/model output.
    body = json.dumps([asdict(t) for t in s.tasks], sort_keys=True)
    return {"seed": s.seed, "horizon_days": s.horizon_days,
            "estate_hash": hashlib.sha256(body.encode()).hexdigest()}


def _check_result(result):
    status = result.payload["meta"]["solver"]["status"]
    if result.rejected or status in ("INFEASIBLE", "MODEL_INVALID"):
        raise HTTPException(422, detail={"message": "No feasible proposal with these constraints",
                            "status": status, "rejected": result.rejected})
    if status not in ("OPTIMAL", "FEASIBLE"):
        raise HTTPException(503, detail={"message": "Solver returned no feasible incumbent; retry or allow more time",
                                        "status": status})
    if not result.plan.blocks:
        raise HTTPException(422, detail={"message": "No work can be placed in this proposal"})


def _bind(payload, approval):
    payload["meta"].update(plan_id=approval.plan_id, revision=approval.revision,
                            content_hash=approval.content_hash, state=approval.state.value)
    return payload


@app.get("/api/health")
def health():
    return {"ok": True, "ready": _session is not None}


@app.get("/api/plan")
def plan(plan_id: str | None = None, time_limit_s: float = Query(20, ge=2, le=120)):
    """Create a bound proposal, or reload an existing immutable revision snapshot."""
    global _last_plan
    with workflow.lock:
        s = session()
        if plan_id is None:
            result = s.solve(time_limit_s=time_limit_s)
            _check_result(result)
            result.payload["monthly"] = dump_monthly(s.monthly_cached(OptimiserWeights()))
            approval = _handle(lambda: workflow.create(f"PLAN-{uuid.uuid4().hex}", result.plan,
                                Actor("Demo planner", Role.JE), context={**_context(s), "weights": result.payload["meta"]["weights"]}))
            _last_plan = result.plan
            return _bind(result.payload, approval)
        approval = _handle(lambda: workflow._require(plan_id))
        if any(approval.context.get(k) != v for k, v in _context(s).items()):
            raise HTTPException(409, detail="proposal belongs to a different estate; cannot reinterpret it")
        saved = approval.plan()
        weights = OptimiserWeights(**approval.context.get("weights", {}))
        base = s.baseline(weights)
        report = SolveReport("RESTORED", 0, 0, 0, 0,
                             sum(len(b.task_ids) for b in saved.blocks), len(saved.unscheduled_task_ids))
        payload = plan_payload(plan=saved, baseline=base, tasks=s.tasks, breakdowns=s.breakdowns,
            paths=s.paths, corridors=s.corridors,
            metrics={"baseline": evaluate(base, s.tasks), "optimised": evaluate(saved, s.tasks)},
            weights=weights, report=report, model_checks=s.model_checks,
            horizon_days=s.horizon_days, seed=s.seed)
        payload["monthly"] = dump_monthly(s.monthly_cached(weights))
        return _bind(payload, approval)


@app.post("/api/resolve")
def resolve(req: ResolveRequest):
    global _last_plan
    with workflow.lock:
        actor = _actor(req.actor, req.role)
        approval = _handle(lambda: workflow.check_revision(req.plan_id, req.revision, req.content_hash))
        _handle(lambda: workflow.check_editable(req.plan_id, actor))
        s = session()
        if any(approval.context.get(k) != v for k, v in _context(s).items()):
            raise HTTPException(409, detail="proposal belongs to a different estate")
        pins = [Pin(p.block_id, p.start_min, p.task_ids) for p in req.pins]
        # A pin references the actual displayed block membership, not caller-invented tasks.
        source = {b.id: b for b in approval.plan().blocks}
        bad = [p.block_id for p in pins if p.block_id not in source or
               sorted(p.task_ids) != sorted(source[p.block_id].task_ids)]
        if bad:
            raise HTTPException(422, detail={"message": "Pins do not match the stored proposal",
                                            "rejected": bad})
        _, _, rejected = s._pin_candidates(pins)
        if rejected:
            raise HTTPException(422, detail={"message": "Invalid pins", "rejected": rejected})
        weights = (OptimiserWeights(**req.weights.model_dump()) if req.weights else
                   OptimiserWeights(**approval.context.get("weights", {})))
        result = s.solve(weights=weights, pins=pins, time_limit_s=req.time_limit_s,
                         warm_start=approval.plan() if req.warm_start else None)
        _check_result(result)
        result.payload["monthly"] = dump_monthly(s.monthly_cached(weights))
        updated = _handle(lambda: workflow.modify(req.plan_id, actor, plan=result.plan,
                         context={**_context(s), "weights": result.payload["meta"]["weights"]}, note=req.remarks or "re-solved pinned placements"))
        _last_plan = result.plan
        return _bind(result.payload, updated)


class StandbyRequest(ActorIn):
    released_block_id: str
    ready_task_ids: list[str]
    time_limit_s: float = Field(20, ge=2, le=120)


@app.post("/api/plans/{plan_id}/standby")
def standby(plan_id: str, req: StandbyRequest):
    with workflow.lock:
        actor = _actor(req.actor, req.role)
        if actor.role is not Role.JE:
            raise HTTPException(403, detail="only JE may propose standby replacements")
        a = _handle(lambda: workflow.check_revision(plan_id, req.revision, req.content_hash))
        if a.state.is_terminal:
            raise HTTPException(409, detail="cannot replace work from a terminal proposal")
        s = session()
        if any(a.context.get(k) != v for k, v in _context(s).items()):
            raise HTTPException(409, detail="proposal belongs to a different estate")
        try:
            result = s.standby(a.plan(), req.released_block_id, req.ready_task_ids,
                weights=OptimiserWeights(**a.context.get("weights", {})), time_limit_s=req.time_limit_s)
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc))
        _check_result(result)
        if not any(set(b.task_ids) & set(req.ready_task_ids) for b in result.plan.blocks):
            raise HTTPException(422, detail="no ready task fits the released slot and resource constraints")
        replacement = _handle(lambda: workflow.create(f"PLAN-{uuid.uuid4().hex}", result.plan, actor,
            context={**_context(s), "weights": result.payload["meta"]["weights"]},
            note=f"standby proposal replacing {req.released_block_id} in {plan_id}"))
        return _bind(result.payload, replacement)


def _transition(plan_id, body, fn):
    with workflow.lock:
        _handle(lambda: workflow.check_revision(plan_id, body.revision, body.content_hash))
        _handle(lambda: fn(_actor(body.actor, body.role)))
        return workflow.status(plan_id)


@app.post("/api/plans/{plan_id}/submit")
def submit(plan_id: str, body: ActorIn):
    # Generation already creates the draft and derives its departments from the snapshot.
    # Submission records the planner's review without accepting replacement scope metadata.
    def action(actor):
        a = workflow.check_editable(plan_id, actor)
        if a.state.value != "DRAFT":
            raise WorkflowError("only a draft can be submitted")
        from samanvay.governance import Action, PlanState
        a.state = PlanState.UNDER_CONCURRENCE
        workflow._commit(a, actor, Action.SUBMIT, remarks=body.remarks)
    return _transition(plan_id, body, action)


@app.post("/api/plans/{plan_id}/concur")
def concur(plan_id: str, body: ConcurIn):
    return _transition(plan_id, body, lambda actor: workflow.concur(plan_id, actor, body.department,
                           granted=body.granted, remarks=body.remarks))


@app.post("/api/plans/{plan_id}/clear")
def clear(plan_id: str, body: ActorIn):
    return _transition(plan_id, body, lambda actor: workflow.clear_operations(plan_id, actor, body.remarks))


@app.post("/api/plans/{plan_id}/sanction")
def sanction(plan_id: str, body: ActorIn):
    return _transition(plan_id, body, lambda actor: workflow.sanction(plan_id, actor, body.remarks))


@app.post("/api/plans/{plan_id}/return")
def return_plan(plan_id: str, body: ActorIn):
    return _transition(plan_id, body, lambda actor: workflow.return_for_revision(plan_id, actor, body.remarks))


@app.post("/api/plans/{plan_id}/cancel")
def cancel(plan_id: str, body: ActorIn):
    return _transition(plan_id, body, lambda actor: workflow.cancel(plan_id, actor, body.remarks))


@app.get("/api/plans/{plan_id}/status")
def plan_status(plan_id: str):
    return _handle(lambda: workflow.status(plan_id))


@app.get("/api/plans/{plan_id}/audit")
def plan_audit(plan_id: str):
    with workflow.lock:
        chain = audit.verify()
        return {"plan_id": plan_id, "entries": [e.to_dict() for e in audit.for_plan(plan_id)],
                "chain": asdict(chain)}


@app.get("/api/audit/verify")
def audit_verify():
    return {**asdict(audit.verify()), "head": audit.head_hash}


if __name__ == "__main__":
    import uvicorn
    session()
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
