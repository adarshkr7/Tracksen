"""End-to-end run: generate -> score -> optimise -> compare against the baseline.

    python scripts/run_pipeline.py --days 7 --tasks 200

Everything printed here comes from two runs of the same simulator over the same task
population. No live railway data is involved at any point.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from samanvay.domain import Line  # noqa: E402
from samanvay.evaluate import compare, evaluate  # noqa: E402
from samanvay.generator import generate_dataset  # noqa: E402
from samanvay.models.cancellation import CancellationModel  # noqa: E402
from samanvay.models.criticality import CriticalityModel  # noqa: E402
from samanvay.models.duration import DurationModel  # noqa: E402
from samanvay.models.traffic import TrafficModel  # noqa: E402
from samanvay.network import (  # noqa: E402
    SECTIONS,
    STATIONS,
    generate_corridors,
    generate_timetable,
)
from samanvay.optimizer.baseline import schedule_fcfs  # noqa: E402
from samanvay.serialize import plan_payload  # noqa: E402
from samanvay.optimizer.cpsat import (  # noqa: E402
    BlockOptimiser,
    OptimiserWeights,
    build_candidates,
)


def rule(title: str = "", width: int = 78) -> None:
    if title:
        print(f"\n{title}")
        print("-" * width)
    else:
        print("=" * width)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="planning horizon in days")
    ap.add_argument("--tasks", type=int, default=200, help="pending tasks to schedule")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--time-limit", type=float, default=30.0, help="solver seconds")
    ap.add_argument("--clubbing", type=float, default=25.0, help="beta: clubbing bonus")
    ap.add_argument("--traffic", type=float, default=0.05, help="lambda: traffic weight")
    ap.add_argument("--overdue", type=float, default=1.5, help="mu: overdue penalty")
    ap.add_argument("--corridor", type=float, default=40.0, help="corridor adherence bonus")
    ap.add_argument("--out", type=str, default="out/plan.json")
    ap.add_argument("--validate", action="store_true",
                    help="run k-fold held-out validation and include it in the output")
    ap.add_argument("--monthly", action="store_true",
                    help="also solve the 30-day corridor-slot horizon")
    ap.add_argument("--monthly-days", type=int, default=30)
    args = ap.parse_args()

    t_start = time.time()

    # ---- 1. ingest -------------------------------------------------------- #
    rule("1  INGEST  --  synthetic TMS / SMMS / TDMS feeds")
    ds = generate_dataset(n_pending=args.tasks, seed=args.seed)
    assets_by_id = {a.id: a for a in ds.assets}
    print(f"  assets {len(ds.assets)}  pending tasks {len(ds.pending)}  "
          f"history: {len(ds.history_blocks)} blocks / {len(ds.history_defects)} defects")
    print(f"  sections {len(SECTIONS)}  horizon {args.days} d")
    by_dept: dict[str, int] = {}
    for t in ds.pending:
        by_dept[t.department.value] = by_dept.get(t.department.value, 0) + 1
    print(f"  departmental split: " +
          "  ".join(f"{k}={v}" for k, v in sorted(by_dept.items())))
    print(f"  already overdue: {sum(1 for t in ds.pending if t.days_overdue() > 0)}")

    # ---- 2. traffic ------------------------------------------------------- #
    rule("2  TRAFFIC  --  working timetable + goods forecast from COA")
    paths = generate_timetable(args.days)
    traffic = TrafficModel(paths, args.days)
    corridors = generate_corridors(args.days)
    print(f"  path-occupations {len(paths):,}   corridor windows {len(corridors)}")
    print(f"  consequence by section (UP): " + "  ".join(
        f"{s.id}={traffic.consequence(s.id, Line.UP):.2f}" for s in SECTIONS[:4]))

    # ---- 3. score --------------------------------------------------------- #
    rule("3  SCORE  --  criticality, duration, cancellation risk")
    cm = CriticalityModel().fit(ds.history_defects)
    breakdowns = cm.score(ds.pending, assets_by_id, traffic, ds.repeat_failures)
    bd_by_task = {b.task_id: b for b in breakdowns}
    crit_check = cm.evaluate_against_truth(ds.pending)

    dm = DurationModel().fit(ds.history_blocks)
    dm.predict(ds.pending)
    dur_check = dm.evaluate_against_truth(ds.pending)

    cx = CancellationModel().fit(ds.history_blocks)
    cx.predict(ds.pending)

    print(f"  criticality: Cox concordance {cm.training_report['cox_concordance']:.3f}   "
          f"rank-vs-true-urgency rho {crit_check.get('spearman_rho_vs_true_urgency', 0):.3f}")
    print(f"  duration:    P90 covers {dur_check['p90_coverage']:.0%} of true durations; "
          f"the demanded figure covers only {dur_check['demanded_coverage']:.0%}")
    print(f"               median P90 - demanded = "
          f"{dur_check['median_p90_minus_demanded_min']:+.0f} min")
    print(f"  cancellation: in-sample AUC {cx.training_report['in_sample_auc']:.3f}, "
          f"base rate {cx.training_report['base_cancellation_rate']:.0%}")

    # ---- 4. candidates ---------------------------------------------------- #
    rule("4  CANDIDATES  --  corridor windows plus cheapest alternatives")
    candidates = build_candidates(
        [s.id for s in SECTIONS], args.days, traffic, corridors
    )
    inside = sum(1 for c in candidates if c.inside_corridor)
    print(f"  {len(candidates)} candidate placements  ({inside} in corridor, "
          f"{len(candidates) - inside} outside)")

    # ---- 5. solve --------------------------------------------------------- #
    rule("5  OPTIMISE  --  CP-SAT")
    weights = OptimiserWeights(
        clubbing=args.clubbing, traffic=args.traffic, overdue=args.overdue,
        corridor=args.corridor,
    )
    opt = BlockOptimiser(weights=weights, time_limit_s=args.time_limit)
    plan = opt.solve(ds.pending, candidates, traffic, args.days, cancellation=cx)
    r = opt.report
    print(f"  status {r.status}  objective {r.objective:,.0f}  "
          f"bound {r.best_bound:,.0f}  gap {r.gap_pct:.1f}%  wall {r.wall_time_s}s")
    print(f"  {r.assign_vars:,} assignment variables over {r.candidates:,} candidates")
    print(f"  scheduled {r.scheduled}  unscheduled {r.unscheduled}  "
          f"conflicts {r.conflicts:,}")

    # ---- 6. baseline ------------------------------------------------------ #
    rule("6  BASELINE  --  first-come-first-served, uncoordinated")
    base_plan = schedule_fcfs(ds.pending, candidates, traffic, args.days, weights)
    print(f"  scheduled {sum(len(b.task_ids) for b in base_plan.blocks)}  "
          f"unscheduled {len(base_plan.unscheduled_task_ids)}  "
          f"blocks {len(base_plan.blocks)}")

    # ---- 7. compare ------------------------------------------------------- #
    rule("7  COMPARISON")
    cx.score_plan(base_plan, ds.pending)
    bm = evaluate(base_plan, ds.pending)
    om = evaluate(plan, ds.pending)

    w1, w2, w3 = 34, 13, 13
    print(f"  {'Measure':<{w1}}{'Baseline':>{w2}}{'SAMANVAY':>{w3}}   Change")
    print("  " + "-" * (w1 + w2 + w3 + 18))
    for name, b, o, delta in compare(bm, om):
        print(f"  {name:<{w1}}{b:>{w2}}{o:>{w3}}   {delta}")

    # ---- 8. sample of the plan ------------------------------------------- #
    rule("8  SAMPLE  --  first clubbed blocks in the optimised plan")
    shown = 0
    for b in plan.blocks:
        if not b.is_clubbed:
            continue
        day_h = f"D{b.day} {b.start_min % 1440 // 60:02d}:{b.start_min % 60:02d}"
        print(f"  {day_h}  {b.section_id:10s} {b.line.value}  "
              f"{b.duration_min:3d}min  "
              f"{'+'.join(d.value for d in b.departments):14s} "
              f"crit={b.criticality_retired:6.1f}  traffic={b.traffic_cost:6.0f}")
        for reason in b.reasons[:2]:
            print(f"       - {reason}")
        shown += 1
        if shown >= 5:
            break
    if shown == 0:
        print("  (no clubbed blocks -- try raising --clubbing)")

    # ---- 8b. monthly horizon ---------------------------------------------- #
    monthly = None
    if args.monthly:
        rule("8b  MONTHLY HORIZON  --  corridor-slot granularity")
        from samanvay.session import PlanningSession  # noqa: E402

        msession = PlanningSession(
            horizon_days=args.days, n_tasks=args.tasks, seed=args.seed,
            monthly_days=args.monthly_days,
        )
        monthly = msession.solve_monthly(weights=weights, time_limit_s=args.time_limit)
        mm = monthly.metrics
        print(f"  corridor slots used {monthly.slots_used}/{monthly.slots_total} "
              f"({monthly.corridor_minutes} min each)  status {monthly.report.status} "
              f"gap {monthly.report.gap_pct:.1f}%")
        print(f"  scheduled {mm.tasks_scheduled}  deferred {mm.tasks_unscheduled}  "
              f"clubbing {mm.clubbing_ratio:.2f}  closures saved {mm.line_closures_saved}")
        print(f"  needs an extended block (P90 > corridor): "
              f"{len(monthly.extended_tasks)} tasks")
        burn = monthly.backlog_by_day
        print(f"  backlog {burn[0]} -> {burn[-1]} over {len(burn)} days "
              f"(day 7: {burn[6] if len(burn) > 6 else '-'})")

    # ---- 8c. held-out validation ------------------------------------------ #
    validation = None
    if args.validate:
        rule("8c  HELD-OUT VALIDATION  --  5-fold cross-validation")
        from samanvay.validation import validate_all  # noqa: E402

        validation = validate_all(ds, k=5, seed=0)
        for section in ("criticality", "duration", "cancellation"):
            for row in validation[section]:
                print(f"  {row['metric']:<46}{row['mean']:>7.3f} +/- {row['std']:.3f}")

    # ---- 9. persist ------------------------------------------------------- #
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = plan_payload(
        plan=plan,
        baseline=base_plan,
        tasks=ds.pending,
        breakdowns=bd_by_task,
        paths=paths,
        corridors=corridors,
        metrics={"baseline": bm, "optimised": om},
        weights=weights,
        report=r,
        model_checks={
            "criticality": {**cm.training_report, **crit_check},
            "duration": {**dm.training_report, **dur_check},
            "cancellation": cx.training_report,
        },
        horizon_days=args.days,
        seed=args.seed,
        monthly=monthly,
        validation=validation,
    )

    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    rule()
    print(f"  plan written to {out_path}   total {time.time() - t_start:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
