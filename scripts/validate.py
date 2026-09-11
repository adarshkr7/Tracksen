"""Held-out validation for all four models.

    python scripts/validate.py --folds 5

Writes out/validation.json and prints the report. Every number here is scored on data
the model did not see during fitting.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from samanvay.generator import generate_dataset  # noqa: E402
from samanvay.validation import format_report, validate_all  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42, help="dataset seed")
    ap.add_argument("--cv-seed", type=int, default=0, help="fold-assignment seed")
    ap.add_argument("--tasks", type=int, default=200)
    ap.add_argument("--out", type=str, default="out/validation.json")
    args = ap.parse_args()

    ds = generate_dataset(n_pending=args.tasks, seed=args.seed)
    report = validate_all(ds, k=args.folds, seed=args.cv_seed)
    report["dataset_seed"] = args.seed
    report["history_sizes"] = {
        "defects": len(ds.history_defects),
        "blocks": len(ds.history_blocks),
    }

    print(format_report(report))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
