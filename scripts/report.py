"""Render the returns Railway Board's joint circular already requires.

    python scripts/report.py                       # weekly return to the DRM, on screen
    python scripts/report.py --which monthly       # monthly return to the GM
    python scripts/report.py --which both --markdown -o out/

Reads a plan produced by `scripts/run_pipeline.py`. It does not solve anything: a return
that re-solved could disagree with the plan it claims to describe.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from samanvay.reports import RETURNS  # noqa: E402

FILENAME = {"weekly": "weekly-drm-return", "monthly": "monthly-gm-return"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", type=str, default="out/plan.json",
                    help="a plan written by scripts/run_pipeline.py")
    ap.add_argument("--which", choices=["weekly", "monthly", "both"], default="weekly")
    ap.add_argument("--markdown", action="store_true",
                    help="render Markdown rather than plain text")
    ap.add_argument("-o", "--out", type=str, default="",
                    help="directory to write to; prints to stdout when omitted")
    args = ap.parse_args()

    path = Path(args.plan)
    if not path.exists():
        print(f"no plan at {path}. Run scripts/run_pipeline.py first.", file=sys.stderr)
        return 1
    payload = json.loads(path.read_text(encoding="utf-8"))

    wanted = ["weekly", "monthly"] if args.which == "both" else [args.which]
    written: list[str] = []

    for name in wanted:
        try:
            ret = RETURNS[name](payload)
        except ValueError as exc:
            # A missing monthly horizon is a reason, not a crash: --which both on a plan
            # solved without --monthly should still print the weekly return.
            print(f"{name}: {exc}", file=sys.stderr)
            if args.which != "both":
                return 1
            continue

        body = ret.to_markdown() if args.markdown else ret.to_text()
        if args.out:
            out_dir = Path(args.out)
            out_dir.mkdir(parents=True, exist_ok=True)
            suffix = "md" if args.markdown else "txt"
            dest = out_dir / f"{FILENAME[name]}.{suffix}"
            dest.write_text(body, encoding="utf-8")
            written.append(str(dest))
        else:
            print(body)
            print()

    for dest in written:
        print(f"written  {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
