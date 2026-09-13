"""Ingest from the three departmental systems and plan from what comes back.

    python scripts/ingest.py

Writes mock TMS / SMMS / TDMS in their native formats, pulls them through the adapter
ladder into one Unified Task Model, then scores and schedules the result. The point is
that nothing above the adapter layer knows or cares where the tasks came from: the same
models and the same solver run on ingested records as on generated ones.
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from samanvay.evaluate import evaluate  # noqa: E402
from samanvay.generator import generate_dataset  # noqa: E402
from samanvay.ingestion import export_all, ingest  # noqa: E402
from samanvay.models.cancellation import CancellationModel  # noqa: E402
from samanvay.models.criticality import CriticalityModel  # noqa: E402
from samanvay.models.duration import DurationModel  # noqa: E402
from samanvay.models.traffic import TrafficModel  # noqa: E402
from samanvay.network import SECTIONS, generate_corridors, generate_timetable  # noqa: E402
from samanvay.optimizer.cpsat import BlockOptimiser, build_candidates  # noqa: E402


def rule(title: str) -> None:
    print(f"\n{title}\n" + "-" * 78)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--tasks", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--time-limit", type=float, default=20.0)
    ap.add_argument("--sources", type=str, default="out/sources")
    args = ap.parse_args()

    rule("1  EXPORT  --  write mock TMS / SMMS / TDMS in their native formats")
    ds = generate_dataset(n_pending=args.tasks, seed=args.seed)
    specs = export_all(ds.pending, args.sources)
    for name, spec in specs.items():
        where = spec.rest_url or spec.db_path or spec.csv_path
        print(f"  {name:<5} {Path(str(where)).name}")

    rule("2  INGEST  --  REST -> read-only DB view -> CSV drop")
    result = ingest(specs)
    print(result.summary())
    print(f"\n  unified task model: {len(result.tasks)} tasks "
          f"from {len(result.reports)} systems")
    if result.rejected:
        print(f"  rejected {len(result.rejected)}:")
        for r in result.rejected[:5]:
            print(f"    {r}")

    degraded = [r.system for r in result.reports if r.degraded]
    if degraded:
        print(f"  running degraded for: {', '.join(degraded)} "
              "(fell back from REST -- still fully functional)")

    rule("3  SCORE  --  the same models, on ingested records")
    tasks = result.tasks
    assets_by_id = {a.id: a for a in ds.assets}
    traffic = TrafficModel(generate_timetable(args.days), args.days)

    cm = CriticalityModel().fit(ds.history_defects)
    cm.score(tasks, assets_by_id, traffic, ds.repeat_failures)
    dm = DurationModel().fit(ds.history_blocks)
    dm.predict(tasks)
    cx = CancellationModel().fit(ds.history_blocks)
    cx.predict(tasks)

    crits = [t.criticality for t in tasks]
    print(f"  criticality  min {min(crits):.1f}  median "
          f"{sorted(crits)[len(crits)//2]:.1f}  max {max(crits):.1f}")
    print(f"  P90 reserved against, median "
          f"{sorted(t.p90_duration_min for t in tasks)[len(tasks)//2]} min")

    rule("4  OPTIMISE  --  the same solver")
    corridors = generate_corridors(args.days, traffic=traffic)
    candidates = build_candidates([s.id for s in SECTIONS], args.days, traffic, corridors)
    opt = BlockOptimiser(time_limit_s=args.time_limit)
    plan = opt.solve(tasks, candidates, traffic, args.days)
    m = evaluate(plan, tasks)

    print(f"  status {opt.report.status}  gap {opt.report.gap_pct:.1f}%  "
          f"wall {opt.report.wall_time_s}s")
    print(f"  blocks {m.blocks_used}  scheduled {m.tasks_scheduled}  "
          f"clubbing {m.clubbing_ratio:.2f}  closures saved {m.line_closures_saved}")
    print(f"  corridor adherence {m.corridor_adherence:.0%}  "
          f"traffic cost {m.traffic_cost:,.0f}")

    print("\n" + "=" * 78)
    print("  Planned entirely from records ingested out of three native schemas.")
    print("  Note: failure-based KPIs are omitted -- real ingested data carries no")
    print("  ground truth, so 'unplanned failures' is only measurable in simulation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
