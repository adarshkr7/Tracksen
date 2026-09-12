"""Build the coaching timetable from published schedule data.

Reads any of the three sources this project has been pointed at, and merges two of them
when both are available. The importer is one script because the hard part -- mapping a
published stop sequence onto this division's roads -- is shared, and lives in
`samanvay.timetable_import`.

    # best available: coverage from IRCTC, running days from a live NTES crawl
    python scripts/import_opendata.py --file data/IRCTC_cleaned.csv         --ntes ../railpull/data/out -o data/timetable_danapur.imported.csv

    python scripts/import_opendata.py --file data/IRCTC_cleaned.csv --dry-run

SOURCES, and what each is actually good for

    IRCTC_cleaned.csv        Best coverage by a distance -- 543 services over this
    (--file)                 division against ~320 from the others. Full train names,
                             complete stop lists including passing points, which is what
                             lets a non-stop express be placed on this road at all.
                             Its days_of_week column is NOT trustworthy: it only ever
                             says all-seven or exactly-one, which is a flattened field.

    Train_details (data.gov.in)  Open Government Data Licence, so redistributable.
    (--file)                 Commercial halts only, names capped at twelve characters,
                             dated December 2017, and no running days at all.

    schedules.json (Kaggle)  December 2020. Full names and passing points, no running
    (--file)                 days.

    NTES via railpull        Current, and the ONLY source whose running days are
    (--ntes)                 genuinely per-train. Thin on its own -- it needs a crawl,
                             and a partial one covers a fraction of the division. Merged
                             in rather than used alone.

WHAT THE MERGE DOES
    Stops and times from the published file, running days from NTES, and any service NTES
    has that the published extract predates is added whole. Neither source wins outright
    because neither is better at everything.

Provenance is written as `opendata` so the UI says where each service came from rather
than implying they are all equally current.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from samanvay.network import ROUTE_BY_ID, WEEKDAYS  # noqa: E402
from samanvay.timetable_import import (  # noqa: E402
    MODELLED,
    classify,
    code_for_name,
    to_service,
)

DAY_CODE = {"mon": "Mo", "tue": "Tu", "wed": "We", "thu": "Th",
            "fri": "Fr", "sat": "Sa", "sun": "Su"}


def hhmm(value: str) -> str:
    """"10:25:00" -> "10:25". Blank and the dataset's "--" placeholder become empty."""
    v = str(value or "").strip()
    if not v or v.startswith("-") or v.lower() == "none":
        return ""
    parts = v.split(":")
    if len(parts) < 2 or not parts[0].isdigit():
        return ""
    return f"{int(parts[0]):02d}:{int(parts[1]):02d}"


def read_railpull(export_dir: Path) -> dict[str, dict]:
    """A railpull/NTES export, in the same shape as the published readers.

    Current where the published datasets are of their vintage, and the only source whose
    running days are genuinely per-train.
    """
    trains_csv, stops_csv = export_dir / "trains.csv", export_dir / "stops.csv"
    if not (trains_csv.exists() and stops_csv.exists()):
        print(f"no railpull export at {export_dir} -- nothing to merge", file=sys.stderr)
        return {}

    meta: dict[str, dict] = {}
    with trains_csv.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            no = (row.get("number") or "").strip()
            if no:
                meta[no] = row

    by_train: dict[str, dict] = {}
    with stops_csv.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            code = (row.get("station_code") or "").strip().upper()
            if code not in MODELLED:
                continue
            no = (row.get("train_number") or "").strip()
            if not no:
                continue
            m = meta.get(no, {})
            rec = by_train.setdefault(no, {
                "name": (m.get("name") or f"Train {no}").strip(),
                "stops": [],
                "runs": parse_days_of_week(m.get("runs_days")),
            })
            try:
                seq = int(row.get("seq") or 0)
            except ValueError:
                continue
            rec["stops"].append({
                "code": code, "seq": seq,
                "time": hhmm(row.get("departure")) or hhmm(row.get("arrival")),
            })
    return by_train


def merge_sources(published: dict[str, dict], ntes: dict[str, dict]) -> tuple[dict, dict]:
    """Union of the two, field by field, with a tally of where each part came from.

    Neither source dominates, so neither is simply preferred:

      stops and times   published. It carries far more calls per train, which is what
                        lets a through express be placed on this road at all.
      running days      NTES. The published column is flattened -- all-seven or
                        exactly-one and nothing between -- and days that coarse price
                        every block near a tri-weekly train wrongly.
      trains            both. NTES is current, so it holds services introduced since the
                        published extract was taken; those are added whole.
    """
    merged = {no: dict(rec) for no, rec in published.items()}
    tally = {"published": len(published), "days_from_ntes": 0, "added_from_ntes": 0}

    for no, rec in ntes.items():
        if no in merged:
            if rec.get("runs"):
                merged[no]["runs"] = rec["runs"]
                tally["days_from_ntes"] += 1
        elif rec.get("stops"):
            merged[no] = dict(rec)
            tally["added_from_ntes"] += 1
    return merged, tally


def _read_irctc(path: Path) -> dict[str, dict]:
    """The IRCTC_cleaned export: one row per train, stops packed into one field.

    The best of the published sources, and the only one that carries RUNNING DAYS. Both
    the others have to borrow those from an NTES crawl or assume daily, and assuming
    daily puts a tri-weekly express on the road four extra days a week.

    Stops arrive as
        "Patna Jn (arr=22:05,dep=22:15) | Ara Jn (arr=22:58,dep=23:00) | ..."
    with NAMES rather than codes, which is why `code_for_name` exists: the spellings are
    not this repository's and a near-miss would put a train on the wrong road.
    """
    csv.field_size_limit(10 ** 7)          # one row holds an entire stop list
    stop_re = re.compile(r"^(?P<name>.*?)\s*\((?P<times>.*)\)\s*$")
    by_train: dict[str, dict] = {}

    with path.open(encoding="utf-8", errors="replace", newline="") as fh:
        for row in csv.DictReader(fh):
            no = (row.get("train_no") or "").strip()
            if not no:
                continue
            stops, outside = [], []
            for seq, chunk in enumerate((row.get("intermediate_stops") or "").split("|")):
                m = stop_re.match(chunk.strip())
                if not m:
                    continue
                times = dict(
                    kv.split("=", 1) for kv in m.group("times").split(",") if "=" in kv
                )
                # "First"/"Last" mark the originating and terminating calls, which have
                # no departure and no arrival respectively.
                dep, arr = times.get("dep", ""), times.get("arr", "")
                when = hhmm(dep if dep not in ("", "Last") else arr)
                code = code_for_name(m.group("name"))
                if code not in MODELLED:
                    # Kept, not dropped. Where a train goes after its last modelled stop
                    # is what says whether the leg ends there or runs on to the boundary.
                    outside.append({"name": m.group("name"), "seq": seq, "time": when})
                    continue
                stops.append({"code": code, "seq": seq, "time": when})
            if not stops:
                continue
            by_train[no] = {
                "name": (row.get("train_name") or "").strip(),
                "stops": stops,
                "outside": outside,
                "runs": parse_days_of_week(row.get("days_of_week")),
            }
    return by_train


def parse_days_of_week(value: str) -> str | None:
    """"MON,TUE,WED,..." -> our day codes. None when the field says nothing."""
    raw = (value or "").strip()
    if not raw:
        return None
    codes = []
    for part in raw.replace(";", ",").split(","):
        key = part.strip()[:3].lower()
        if key in DAY_CODE and DAY_CODE[key] not in codes:
            codes.append(DAY_CODE[key])
    if not codes:
        return None
    if len(codes) == 7:
        return "daily"
    return "".join(c for c in WEEKDAYS if c in codes)


def read_schedule(path: Path) -> dict[str, dict]:
    """Stops on the modelled road, per train, in running order.

    Two published shapes are accepted, because the two datasets worth using are shaped
    differently and neither is worth a separate importer:

      .csv   data.gov.in "Train details" -- Train No / Train Name / SEQ / Station Code /
             Arrival time / Departure Time. Commercial halts only, names capped at
             twelve characters.
      .json  the Kaggle schedules dump -- train_number / train_name / station_code /
             arrival / departure / id. Full names, and it carries PASSING points as well
             as halts, so a non-stop express still has several calls on this division
             instead of the single one that makes its run impossible to place.

    Only stops on this road are kept, but the ORDER comes from the train's own full
    sequence, so a train that calls elsewhere in between still runs these in this order.
    """
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8", errors="replace", newline="") as probe:
            header = probe.readline()
        if "intermediate_stops" in header:
            return _read_irctc(path)

    by_train: dict[str, dict] = {}

    if path.suffix.lower() == ".json":
        for row in json.loads(path.read_text(encoding="utf-8")):
            code = (row.get("station_code") or "").strip().upper()
            if code not in MODELLED:
                continue
            no = str(row.get("train_number") or "").strip()
            if not no:
                continue
            rec = by_train.setdefault(
                no, {"name": (row.get("train_name") or "").strip(), "stops": []}
            )
            rec["stops"].append({
                "code": code,
                "seq": int(row.get("id") or 0),   # monotonic within a train
                "time": hhmm(row.get("departure")) or hhmm(row.get("arrival")),
            })
        return by_train

    with path.open(encoding="utf-8", errors="replace", newline="") as fh:
        for row in csv.DictReader(fh):
            code = (row.get("Station Code") or "").strip().upper()
            if code not in MODELLED:
                continue
            no = (row.get("Train No") or "").strip()
            if not no:
                continue
            rec = by_train.setdefault(
                no, {"name": (row.get("Train Name") or "").strip(), "stops": []}
            )
            try:
                seq = int(row.get("SEQ") or 0)
            except ValueError:
                continue
            # Departure puts a train on the section; a terminating call has none, and it
            # is the last stop anyway, so arrival stands in.
            rec["stops"].append({
                "code": code, "seq": seq,
                "time": hhmm(row.get("Departure Time")) or hhmm(row.get("Arrival time")),
            })
    return by_train


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path,
                    default=Path("data/schedules.json"),
                    help="a published schedule: data.gov.in CSV or Kaggle schedules JSON")
    ap.add_argument("--ntes", "--runs-from", dest="ntes", type=Path, default=None,
                    help="railpull/NTES export dir, merged in: real running days, plus "
                         "any current service the published extract predates")
    ap.add_argument("-o", "--out", type=Path,
                    default=Path("data/timetable_danapur.imported.csv"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.file.exists():
        print(f"not found: {args.file}\n"
              "Download 'Train details' from data.gov.in and point --file at it.",
              file=sys.stderr)
        return 2


    by_train = read_schedule(args.file)
    tally = {"published": len(by_train), "days_from_ntes": 0, "added_from_ntes": 0}
    if args.ntes:
        by_train, tally = merge_sources(by_train, read_railpull(args.ntes))

    written: list[dict] = []
    skipped: dict[str, int] = defaultdict(int)
    assumed_daily = 0

    for number, rec in sorted(by_train.items()):
        stops = sorted(rec["stops"], key=lambda s: s["seq"])
        stops = [s for i, s in enumerate(stops)
                 if i == 0 or s["code"] != stops[i - 1]["code"]]
        outside = sorted(rec.get("outside") or [], key=lambda o: o["seq"])
        before = [o for o in outside if o["seq"] < stops[0]["seq"]]
        after = [o for o in outside if o["seq"] > stops[-1]["seq"]]

        # One halt used to be fatal. It is not, when the stops either side of it say
        # which boundary the train came in at and which it left by: 12305 Howrah-New
        # Delhi Rajdhani halts only at Patna and runs the full 281 km.
        if len(stops) < 2 and not (before and after):
            skipped["only touches one modelled station"] += 1
            continue
        if not all(s["time"] for s in stops):
            skipped["missing a booked time"] += 1
            continue

        name = rec["name"] or f"Train {number}"
        runs = rec.get("runs")
        known_runs = runs is not None

        tclass = classify(name, number=number)
        row, why = to_service(number, name, tclass, runs or "daily", stops,
                              before=before, after=after)
        if row is None:
            skipped[why] += 1
            continue
        # Counted only for rows that are actually written. Counting every train read gave
        # a tally larger than the output and a negative "known" figure.
        if not known_runs:
            assumed_daily += 1
            runs = "daily"

        written.append({
            "train_no": number,
            "name": name.replace(",", " "),
            "class": tclass,
            **row,
            "runs": runs,
            "provenance": "opendata",
        })

    # ---- one movement per path -------------------------------------------------
    #
    # The source carries a service under both its current and its former number, with
    # every booked time identical: 12327 and 13035 are both the Upasana Express out of
    # Howrah, calling at Jhajha 17:55/18:00 and Buxar 22:32/22:34 in both rows. Written
    # out twice, one train occupies the road twice and every block over it is priced as
    # though it delayed two.
    #
    # Identity here is the MOVEMENT -- same road, same ends, same minute, same days --
    # not the name, because the pair rarely share one. Two different trains cannot hold
    # the same section at the same minute anyway, so a collision is a duplicate rather
    # than a coincidence.
    seen: dict[tuple, str] = {}
    unique: list[dict] = []
    duplicates = 0
    for svc in written:
        key = (svc["route"], svc["enter_at"], svc["leave_at"], svc["main_leg"],
               svc["enter_time"], svc["runs"])
        if key in seen:
            duplicates += 1
            continue
        seen[key] = svc["train_no"]
        unique.append(svc)
    written = unique

    print(f"source          : {args.file.name}")
    if args.ntes:
        print(f"merged with     : {args.ntes} (NTES)")
        print(f"                  {tally['days_from_ntes']} running days replaced, "
              f"{tally['added_from_ntes']} services added")
    print(f"touching the road: {len(by_train)} trains")
    print(f"importable      : {len(written)}")
    if duplicates:
        print(f"  deduped {duplicates:>4}  same movement under a second train number")
    for why, n in sorted(skipped.items(), key=lambda kv: -kv[1]):
        print(f"  skipped {n:>4}  {why}")

    per_route: dict[str, int] = defaultdict(int)
    per_class: dict[str, int] = defaultdict(int)
    for r in written:
        per_route[r["route"]] += 1
        per_class[r["class"]] += 1
    print("by route        :", dict(sorted(per_route.items())))
    print("by class        :", dict(sorted(per_class.items())))

    # A running-days column that only ever says 7 or 1 has been flattened somewhere
    # upstream. Worth saying so: it looks like data and prices blocks as though it were.
    spread = {len(r["runs"]) // 2 if r["runs"] != "daily" else 7 for r in written}
    if written and spread <= {1, 7}:
        print("NOTE            : this source's running days are only ever daily or "
              "one-day-a-week.")
        print("                  That is a flattened column, not a timetable. Overlay a "
              "crawl with --runs-from")
        print("                  for per-train days, or treat the frequencies as "
              "indicative only.")

    known = len(written) - assumed_daily
    if assumed_daily == 0:
        print(f"running days    : all {known} published -- none assumed")
    elif known:
        print(f"running days    : {known} published, {assumed_daily} assumed daily")
    else:
        print(f"running days    : ALL {assumed_daily} assumed daily -- this source "
              "carries none")
        print("                  pass --runs-from <railpull export> to supply them")

    missing = set(ROUTE_BY_ID) - set(per_route)
    if missing:
        print(f"WARNING: no traffic on {sorted(missing)} -- a block there prices as free")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    fields = ["train_no", "name", "class", "route", "enter_at", "leave_at",
              "main_leg", "enter_time", "runs", "provenance"]
    header = [
        "# Coaching timetable - Danapur division.",
        "#",
        f"# Stops and booked times : {args.file.name}",
    ]
    if args.ntes:
        header += [
            f"# Running days          : NTES crawl, for {tally['days_from_ntes']} of them",
            f"# Added from NTES       : {tally['added_from_ntes']} services the published"
            " extract predates",
        ]
    else:
        header.append("# Running days          : from the source file, unverified")
    header += [
        "#",
        "# provenance=opendata: number, name, stop sequence and times are as published.",
        "# A published extract is of its own vintage: services introduced after it was",
        "# taken are absent, and some it contains have since been retimed or rerouted.",
        f"# {assumed_daily} services are assumed daily. A tri-weekly express modelled as",
        "# daily puts it on the road four extra days a week and prices every block near",
        "# it as dearer than it is.",
        "#",
        "# Goods is absent by design - goods paths are not booked, so TRACKSEN forecasts",
        "# them.",
        "#",
        "# ATTRIBUTION. This is a derived extract, not a redistribution of any source:",
        "# 543 rows covering one division, reduced to the columns this model needs.",
        "#   Stops and times  : the published schedule named above.",
        "#   Running days     : NTES, via railpull (github.com/shwetankg07/railpull, MIT).",
        "#                      railpull asks that NTES data not be bulk-redistributed;",
        "#                      what is here is the running-day field for a few dozen",
        "#                      trains on one division, not a copy of the book.",
        "# Regenerate rather than copy onward. One command, printed by the importer.",
        "#",
    ]

    # Written to a temporary file and moved into place. Writing straight to the target
    # meant a crash mid-write left a truncated timetable behind -- and the loader PREFERS
    # the imported file over the shipped one, so the next run planned against nothing at
    # all rather than falling back. That is exactly how this was found.
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(args.out.suffix + ".partial")
    try:
        with tmp.open("w", encoding="utf-8", newline="") as fh:
            fh.write("\n".join(header) + "\n")
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(written)
        os.replace(tmp, args.out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

    print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
