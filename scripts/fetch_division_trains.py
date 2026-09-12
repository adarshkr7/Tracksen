"""Fetch NTES schedules for only the trains this division actually models.

railpull's own crawler discovers and fetches every train on Indian Railways -- around
10,500 of them, deliberately throttled, so roughly five hours. That is the right tool for
building a national dataset and the wrong one for this: TRACKSEN models one division and
needs a couple of hundred specific services. Worse, the crawler works in sorted numeric
order, so the 12xxx and 13xxx expresses that actually run over Danapur do not arrive until
most of the way through the run.

This fetches exactly the numbers already named in the shipped timetable and nothing else
-- a few minutes instead of a few hours, and a proportionate amount of load on a public
enquiry service. It writes into railpull's own schedules directory in railpull's own
format, so `transform/export.py` and `scripts/import_railpull.py` then work unchanged.

    python scripts/fetch_division_trains.py --railpull ../railpull
    cd ../railpull && python transform/export.py
    cd ../SIH && python scripts/import_railpull.py \
        --railpull ../railpull/data/out -o data/timetable_danapur.imported.csv

Already-cached schedules are skipped, so this is resume-safe and can be re-run. It does
not lower railpull's request pause, and it should not be run in a loop: a timetable is
not a live feed.
"""

from __future__ import annotations

import argparse
import csv
import functools
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from samanvay.network import SHIPPED_TIMETABLE  # noqa: E402

# railpull's floor, not lowered. It is a public enquiry service.
PAUSE_S = 1.2


def wanted_numbers(timetable: Path) -> list[str]:
    """Train numbers named in the shipped timetable."""
    with timetable.open(encoding="utf-8", newline="") as fh:
        rows = csv.DictReader(line for line in fh if not line.lstrip().startswith("#"))
        return sorted({r["train_no"].strip() for r in rows if r.get("train_no")})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--railpull", type=Path, default=Path("../railpull"),
                    help="path to a railpull checkout (for its NTES client and cache)")
    ap.add_argument("--pause", type=float, default=PAUSE_S,
                    help="seconds between requests; the 1.2 s floor is not negotiable")
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after this many fetches (0 = all); useful for a smoke test")
    args = ap.parse_args()

    railpull = args.railpull.resolve()
    if not (railpull / "ntes").is_dir():
        print(f"no railpull checkout at {railpull}\n"
              "  git clone https://github.com/shwetankg07/railpull", file=sys.stderr)
        return 2

    try:
        # The distribution is named ntes-client; the module it installs is `ntes`.
        from ntes import NTESClient
    except ImportError:
        print("the NTES client is not installed.\n"
              f"  pip install -r {railpull / 'requirements.txt'}", file=sys.stderr)
        return 2

    sched_dir = railpull / "data" / "raw" / "schedules"
    sched_dir.mkdir(parents=True, exist_ok=True)

    numbers = wanted_numbers(SHIPPED_TIMETABLE)
    todo = [n for n in numbers if not (sched_dir / f"{n}.json").exists()]
    cached = len(numbers) - len(todo)
    if args.limit:
        todo = todo[:args.limit]

    pause = max(PAUSE_S, args.pause)
    print(f"timetable names {len(numbers)} trains | {cached} already cached | "
          f"{len(todo)} to fetch")
    if not todo:
        print("nothing to do - run railpull's transform/export.py next")
        return 0
    # Console output stays plain ASCII. This runs on a Windows terminal whose default
    # codec is cp1252, where a stray "approximately" sign crashes the run before it has
    # fetched anything -- which is precisely the failure this script exists to route past.
    print(f"~{len(todo) * (pause + 0.5) / 60:.0f} min at a {pause:.1f}s pause\n")

    client = NTESClient()
    # The enquiry server sometimes accepts a connection and then goes silent. Without a
    # read timeout one dead socket hangs the whole run -- railpull hit this too.
    client.session.request = functools.partial(client.session.request, timeout=(10, 30))

    ok = missing = failed = 0
    for i, no in enumerate(todo, 1):
        try:
            r = client.schedule(no)
        except Exception as exc:                      # noqa: BLE001 - network, anything
            failed += 1
            print(f"  {no}  error: {type(exc).__name__}")
            r = None
        else:
            if r and r.get("stations"):
                # encoding is explicit: train names carry non-ASCII, and on Windows the
                # default locale codec cannot encode them. This is what broke railpull's
                # own crawler on the first train it fetched.
                (sched_dir / f"{no}.json").write_text(
                    json.dumps(r, ensure_ascii=False), encoding="utf-8"
                )
                ok += 1
            else:
                missing += 1
                print(f"  {no}  not in NTES (renumbered, or not currently running)")

        if i % 25 == 0 or i == len(todo):
            print(f"  {i}/{len(todo)}  ok={ok} missing={missing} failed={failed}",
                  flush=True)
        # Jittered so a long run does not become a metronome against one host.
        time.sleep(pause + random.uniform(0, 0.4))

    print(f"\nfetched {ok}, {missing} not found, {failed} errored")
    print(f"schedules now cached: {len(list(sched_dir.glob('*.json')))}")
    print("\nnext:")
    print(f"  cd {railpull} && python transform/export.py")
    print("  python scripts/import_railpull.py --railpull "
          f"{railpull / 'data' / 'out'} -o data/timetable_danapur.imported.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
