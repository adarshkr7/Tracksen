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

from samanvay.optimizer.cpsat import OptimiserWeights  # noqa: E402
from samanvay.session import Pin, PlanningSession  # noqa: E402

app = FastAPI(title="SAMANVAY re-solve", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_session: PlanningSession | None = None
_last_plan = None


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
    return result.payload


if __name__ == "__main__":
    import uvicorn

    print("Warming the planning session (generating estate, fitting models)...")
    session()
    print("Ready. POST /api/resolve to re-solve with pinned blocks.")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
