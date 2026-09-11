"""One place that turns a solved plan into the payload the UI reads.

Both `scripts/run_pipeline.py` (which writes plan.json) and the re-solve API return
this exact shape. Keeping it in one function is the point: the web client parses both,
and two builders would drift the moment either side gained a field.
"""

from __future__ import annotations

from typing import Any

from .domain import Line, MaintenanceTask, Plan
from .evaluate import PlanMetrics
from .network import SECTIONS, STATIONS
from .optimizer.cpsat import (
    MACHINE_POSITIONING_MIN,
    OptimiserWeights,
    SolveReport,
)

SECTION_INDEX = {s.id: i for i, s in enumerate(SECTIONS)}
CLASS_INDEX = {"PREMIER": 0, "MAIL_EXP": 1, "PASSENGER": 2, "GOODS": 3}

# Mirrored to the client so it prices windows exactly as the solver did.
DETENTION_WEIGHTS = [4.0, 2.5, 1.5, 1.0]
REGULATION_OVERHEAD_MIN = 10


def dump_blocks(plan: Plan) -> list[dict[str, Any]]:
    return [
        {
            "id": b.id,
            "sec": SECTION_INDEX[b.section_id],
            "line": b.line.value,
            "day": b.day,
            "s": b.start_min,
            "e": b.end_min,
            "tasks": b.task_ids,
            "depts": [d.value for d in b.departments],
            "types": [t.value for t in b.block_types],
            "corridor": b.inside_corridor,
            "traffic": round(b.traffic_cost, 1),
            "crit": b.criticality_retired,
            "why": b.reasons,
        }
        for b in plan.blocks
    ]


def dump_tasks(tasks: list[MaintenanceTask], breakdowns: dict) -> list[dict[str, Any]]:
    out = []
    for t in tasks:
        bd = breakdowns.get(t.id)
        out.append({
            "id": t.id,
            "dept": t.department.value,
            "type": t.task_type,
            "section": t.section_id,
            "line": t.line.value,
            "km": t.chainage_km,
            "severity": t.defect_severity,
            "due_day": t.due_day,
            "criticality": t.criticality,
            "p50": t.p50_duration_min,
            "p90": t.p90_duration_min,
            "demanded": t.demanded_duration_min,
            "cancellation_risk": t.cancellation_risk,
            "attribution": t.attribution,
            "machine": t.machine.value,
            "night_work_allowed": t.night_work_allowed,
            "e_days": round(bd.expected_days_to_failure, 2) if bd else None,
            "p_fail": round(bd.p_failure, 4) if bd else None,
        })
    return out


def plan_payload(
    *,
    plan: Plan,
    baseline: Plan,
    tasks: list[MaintenanceTask],
    breakdowns: dict,
    paths: list,
    corridors: list,
    metrics: dict[str, PlanMetrics],
    weights: OptimiserWeights,
    report: SolveReport,
    model_checks: dict,
    horizon_days: int,
    seed: int,
    pinned: list[dict] | None = None,
    monthly: Any = None,
    validation: dict | None = None,
) -> dict[str, Any]:
    return {
        "meta": {
            "horizon_days": horizon_days,
            "tasks": len(tasks),
            "seed": seed,
            "weights": weights.__dict__,
            "solver": report.__dict__,
            "pinned": pinned or [],
        },
        "model_checks": model_checks,
        "validation": validation,
        "metrics": {k: v.__dict__ for k, v in metrics.items()},
        "stations": [{"code": s.code, "name": s.name, "km": s.km} for s in STATIONS],
        "sections": [
            {"id": s.id, "a": s.from_station, "b": s.to_station,
             "km0": s.km_start, "km1": s.km_end}
            for s in SECTIONS
        ],
        "corridors": [
            [SECTION_INDEX[c.section_id], c.day, c.start_min, c.end_min] for c in corridors
        ],
        "trainClasses": list(CLASS_INDEX),
        "detentionWeights": DETENTION_WEIGHTS,
        "regulationOverheadMin": REGULATION_OVERHEAD_MIN,
        "maxBlocksPerDeptPerDay": weights.max_blocks_per_dept_per_day,
        "machinePositioningMin": MACHINE_POSITIONING_MIN,
        # Compact: [section, line(0=UP,1=DN), class, enter, exit, probability]
        "paths": [
            [SECTION_INDEX[p.section_id], 0 if p.line is Line.UP else 1,
             CLASS_INDEX[p.train_class.value], p.enter_min, p.exit_min,
             round(p.probability, 2)]
            for p in paths
        ],
        "blocks": dump_blocks(plan),
        "baselineBlocks": dump_blocks(baseline),
        "tasks": dump_tasks(tasks, breakdowns),
        "monthly": dump_monthly(monthly) if monthly is not None else None,
    }


def dump_monthly(r: Any) -> dict[str, Any]:
    """The long-horizon view: corridor slots allocated across the month."""
    return {
        "days": len(r.backlog_by_day),
        "corridorMinutes": r.corridor_minutes,
        "slotsTotal": r.slots_total,
        "slotsUsed": r.slots_used,
        "blocks": dump_blocks(r.plan),
        "metrics": r.metrics.__dict__,
        "extendedTasks": r.extended_tasks,
        "backlogByDay": r.backlog_by_day,
        "solver": r.report.__dict__,
    }
