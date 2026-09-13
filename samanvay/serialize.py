"""One place that turns a solved plan into the payload the UI reads.

Both `scripts/run_pipeline.py` (which writes plan.json) and the re-solve API return
this exact shape. Keeping it in one function is the point: the web client parses both,
and two builders would drift the moment either side gained a field.
"""

from __future__ import annotations

from typing import Any

from .domain import Line, MaintenanceTask, Plan, TrainClass
from .evaluate import PlanMetrics
from .network import (
    BOOKED_SERVICES,
    TIMETABLE_FILE,
    TIMETABLE_IS_IMPORTED,
    BRANCHES,
    JUNCTIONS,
    PLANNED_ROUTES,
    ROUTES,
    SECTIONS,
    STATIONS,
    resolve_regime,
)
from .optimizer.cpsat import (
    MACHINE_POSITIONING_MIN,
    OptimiserWeights,
    SolveReport,
)

SECTION_INDEX = {s.id: i for i, s in enumerate(SECTIONS)}
CLASS_INDEX = {"PREMIER": 0, "MAIL_EXP": 1, "PASSENGER": 2, "GOODS": 3}

# How each train in the payload came to be there. The UI shows this on the path tooltip
# so nobody reads a forecast goods path as a booked one, or a stand-in MEMU number as a
# verified one. See data/timetable_danapur.csv for what the two coaching values mean.
PROVENANCE_INDEX = {
    "named": 0,          # authored here: real train, approximate time
    "representative": 1, # authored here: stands in for stopping traffic
    "forecast": 2,       # goods -- not booked anywhere, so modelled
    "imported": 3,       # from NTES via railpull: current, booked
    "opendata": 4,       # from a published open dataset: booked, but of its vintage
}
SERVICE_PROVENANCE = {s.train_no: s.provenance for s in BOOKED_SERVICES}


def _provenance_code(train_no: str) -> int:
    """Provenance index for a train, refusing to guess at one it does not recognise.

    Defaulting an unknown value to "named" would put a made-up time behind a label that
    says it is real, which is the one direction this field must never fail in. A new
    importer that writes a provenance nobody registered should stop the build.
    """
    value = SERVICE_PROVENANCE.get(train_no, "forecast")
    try:
        return PROVENANCE_INDEX[value]
    except KeyError:
        raise KeyError(
            f"train {train_no} carries provenance {value!r}, which is not in "
            f"PROVENANCE_INDEX ({', '.join(PROVENANCE_INDEX)}). Register it there and in "
            "web/app/lib/plan.ts PROVENANCE so the UI can say where it came from."
        ) from None


def dump_trains(paths: list) -> tuple[list[list], dict[str, int]]:
    """The roster behind the path array.

    A path is one section occupation; a train has dozens of them. Carrying the number and
    name on every path would be most of plan.json, so identity is interned here and each
    path keeps an index into this list.
    """
    index: dict[str, int] = {}
    roster: list[list] = []
    for p in paths:
        if p.train_no in index:
            continue
        index[p.train_no] = len(roster)
        roster.append([
            p.train_no,
            p.train_name,
            _provenance_code(p.train_no),
        ])
    return roster, index

# Mirrored to the client so it prices windows exactly as the solver did. Derived from
# the enum rather than written out: this list was once a hand-kept copy, and it silently
# went stale the moment the premier weight changed, leaving what-if pricing the client
# showed disagreeing with what the solver had actually optimised.
DETENTION_WEIGHTS = [TrainClass(c).detention_weight for c in CLASS_INDEX]
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
    corridor_regime: Any = None,
    corridor_audit: list | None = None,
) -> dict[str, Any]:
    train_roster, train_index = dump_trains(paths)
    regime = resolve_regime(corridor_regime)
    return {
        "meta": {
            "horizon_days": horizon_days,
            "tasks": len(tasks),
            "seed": seed,
            "weights": weights.__dict__,
            "solver": report.__dict__,
            "pinned": pinned or [],
            # Which limb of the 28.12.2016 joint circular this plan was built under.
            # The UI must not describe a 180-minute corridor as the mandated norm.
            "corridorRegime": {
                "name": regime.name,
                "spells": [m for _, m in regime.spells],
                "longestSpellMin": regime.longest_spell_min,
                "dailyMinutes": regime.daily_minutes,
            },
        },
        "model_checks": model_checks,
        "validation": validation,
        "metrics": {k: v.__dict__ for k, v in metrics.items()},
        "stations": [
            {"code": s.code, "name": s.name, "km": s.km,
             "junction": JUNCTIONS.get(s.code)}
            for s in STATIONS
        ],
        "branches": [
            {"junction": b.junction, "name": b.name, "side": b.side, "note": b.note,
             "modelled": b.modelled}
            for b in BRANCHES
        ],
        # Routes blocks are planned on. The rest are modelled for the traffic they put
        # onto the planned road and the junction throats they share with it.
        "plannedRoutes": list(PLANNED_ROUTES),
        # Where the coaching timetable came from. The UI must not describe imported
        # times as approximate, nor approximate times as booked.
        "timetable": {
            "file": TIMETABLE_FILE.name,
            "imported": TIMETABLE_IS_IMPORTED,
            "services": len(BOOKED_SERVICES),
        },
        "routes": [
            {
                "id": r.id, "name": r.name, "lengthKm": r.length_km,
                "planned": r.id in PLANNED_ROUTES,
                "stations": [
                    {"code": st.code, "name": st.name, "km": st.km,
                     "junction": JUNCTIONS.get(st.code)}
                    for st in r.stations
                ],
            }
            for r in ROUTES
        ],
        "sections": [
            {"id": s.id, "a": s.from_station, "b": s.to_station,
             "km0": s.km_start, "km1": s.km_end, "route": s.route}
            for s in SECTIONS
        ],
        "corridors": [
            [SECTION_INDEX[c.section_id], c.day, c.start_min, c.end_min] for c in corridors
        ],
        # Corridors the working timetable itself runs trains through. A block marked
        # "inside mandated corridor" in one of these is inside a promise the chart does
        # not keep, and the UI has to be able to say so.
        "corridorAudit": [
            {
                "section": SECTION_INDEX[f.section_id],
                "line": 0 if f.line.value == "UP" else 1,
                "day": f.day,
                "start": f.start_min,
                "end": f.end_min,
                "booked": f.booked,
                "forecast": f.forecast,
                "premier": f.premier,
                "examples": list(f.examples),
            }
            for f in (corridor_audit or [])
        ],
        "trainClasses": list(CLASS_INDEX),
        "detentionWeights": DETENTION_WEIGHTS,
        "regulationOverheadMin": REGULATION_OVERHEAD_MIN,
        "maxBlocksPerDeptPerDay": weights.max_blocks_per_dept_per_day,
        "machinePositioningMin": MACHINE_POSITIONING_MIN,
        # [train_no, name, provenance(0=named,1=representative,2=forecast)]
        "trains": train_roster,
        # Compact: [section, line(0=UP,1=DN), class, enter, exit, probability, train]
        "paths": [
            [SECTION_INDEX[p.section_id], 0 if p.line is Line.UP else 1,
             CLASS_INDEX[p.train_class.value], p.enter_min, p.exit_min,
             round(p.probability, 2), train_index[p.train_no]]
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
