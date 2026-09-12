"""Turn a railpull export into the TRACKSEN coaching timetable.

`data/timetable_danapur.csv` ships with approximate times, because a Working Time Table
is not something this repository can invent. railpull (https://github.com/shwetankg07/railpull,
MIT) pulls the current timetable out of NTES and flattens it into `trains.csv` and
`stops.csv`. This script reads those two files and writes the timetable in the schema
`samanvay/network.py` already expects -- real numbers, real times, real running days,
marked `provenance=imported` so the UI stops describing them as approximate.

    python scripts/import_railpull.py --railpull ../railpull/data --dry-run
    python scripts/import_railpull.py --railpull ../railpull/data -o data/timetable_danapur.csv

ON RUNNING THE CRAWLER. This script does not fetch anything. railpull's own README asks
that the crawl be run once and cached, at its default request rate, and warns that bulk
REDISTRIBUTION of NTES data may run against the operator's terms of use. So: run the
crawl yourself, keep the output out of version control, and treat what this script writes
as a local working file rather than something to commit or publish.

WHAT IS AND IS NOT IMPORTED. Only services that touch the modelled Danapur road are kept.
A service is written out when its run over that road is one leg on one route, or one
branch leg working through a junction onto the main line -- which is what the timetable
schema can express. Anything else (a train that crosses the division twice, or works
branch-to-branch through Kiul) is reported and skipped rather than guessed at; --dry-run
prints the tally so you can see exactly how much was left behind.

Goods is not imported and cannot be: goods paths are not booked and not published.
TRACKSEN forecasts them, which is unchanged by any of this.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from samanvay.network import (  # noqa: E402
    BRANCH_JUNCTION,
    MAIN,
    ROUTES,
    ROUTE_BY_ID,
    WEEKDAYS,
)

# railpull writes weekday names; the timetable schema wants two-letter codes with no
# separator, because the file is comma-delimited and "Mon,Wed,Fri" would split a row.
DAY_CODE = {
    "mon": "Mo", "tue": "Tu", "wed": "We", "thu": "Th",
    "fri": "Fr", "sat": "Sa", "sun": "Su",
}

# NTES train types, lowercased, mapped onto the running priority order. Anything
# unrecognised falls to MAIL_EXP, which is the common case and the safe one: calling a
# stopping train an express overstates its detention weight slightly, whereas calling an
# express a passenger train would understate it.
PREMIER_MARKERS = ("rajdhani", "vande bharat", "vandebharat", "shatabdi", "duronto",
                   "tejas", "gatimaan")
PASSENGER_MARKERS = ("memu", "demu", "passenger", "ordinary", "suburban", "emu")


def classify(name: str, ttype: str) -> str:
    blob = f"{name} {ttype}".lower()
    if any(m in blob for m in PREMIER_MARKERS):
        return "PREMIER"
    if any(m in blob for m in PASSENGER_MARKERS):
        return "PASSENGER"
    return "MAIL_EXP"


def parse_runs(value: str) -> str | None:
    """railpull's runs_days -> our day codes, or None when it does not know.

    railpull writes "Daily", a "Mon,Wed,Fri" list, or the literal "Unknown" when NTES
    gave it no run-date list. Treating "Unknown" as daily would put a train on the road
    four extra days a week and quietly inflate the cost of every block near it, so it is
    returned as None and counted, not guessed at.
    """
    raw = (value or "").strip()
    if not raw or raw.lower() == "unknown":
        return None
    if raw.lower() in ("daily", "all", "everyday"):
        return "daily"
    codes = []
    for part in raw.replace(";", ",").split(","):
        key = part.strip()[:3].lower()
        if key in DAY_CODE and DAY_CODE[key] not in codes:
            codes.append(DAY_CODE[key])
    if not codes:
        return None
    # Canonical order, so two trains with the same days spell them the same way.
    return "".join(c for c in WEEKDAYS if c in codes)


def pick(row: dict, *names: str) -> str:
    """First column present under any of these names. railpull's headers have moved."""
    for n in names:
        for key in (n, n.lower(), n.upper()):
            if key in row and row[key] not in (None, ""):
                return str(row[key]).strip()
    return ""


# --------------------------------------------------------------------------- #
# Where a station sits on the modelled network
# --------------------------------------------------------------------------- #

STATION_ROUTES: dict[str, list[str]] = defaultdict(list)
for _r in ROUTES:
    for _st in _r.stations:
        STATION_ROUTES[_st.code].append(_r.id)

MODELLED = set(STATION_ROUTES)


def routes_spanning(a: str, b: str) -> list[str]:
    """Routes carrying both stations. MAIN first, so a shared pair resolves to it."""
    shared = [r for r in STATION_ROUTES[a] if r in STATION_ROUTES[b]]
    return sorted(shared, key=lambda r: (r != MAIN, r))


def segment(stops: list[dict]) -> list[tuple[str, list[dict]]]:
    """Split a run over the modelled road into consecutive same-route legs.

    Junction stations sit on two routes at once, so a stop cannot be assigned a route on
    its own -- Kiul is on the main line, the Gaya branch and the Jamalpur branch. What
    fixes it is the pair: the route a train is on between two adjacent stops is the one
    that carries both of them.
    """
    legs: list[tuple[str, list[dict]]] = []
    for prev, cur in zip(stops, stops[1:]):
        shared = routes_spanning(prev["code"], cur["code"])
        if not shared:
            return []                     # not a move this network can represent
        route = shared[0]
        if legs and legs[-1][0] == route:
            legs[-1][1].append(cur)
        else:
            legs.append((route, [prev, cur]))
    return legs


def to_service(number: str, name: str, tclass: str, runs: str,
               stops: list[dict]) -> tuple[dict | None, str]:
    """One timetable row, or a reason it could not be written."""
    legs = segment(stops)
    if not legs:
        return None, "no modelled leg"

    if len(legs) == 1:
        route, leg = legs[0]
        return {
            "route": route, "enter_at": leg[0]["code"], "leave_at": leg[-1]["code"],
            "main_leg": "", "enter_time": leg[0]["time"],
        }, ""

    if len(legs) == 2:
        (ra, la), (rb, lb) = legs
        # Exactly one of the two must be the main line for the schema to hold it.
        if ra == MAIN and rb != MAIN and BRANCH_JUNCTION.get(rb) == lb[0]["code"]:
            return {
                "route": rb, "enter_at": lb[0]["code"], "leave_at": lb[-1]["code"],
                "main_leg": la[0]["code"], "enter_time": lb[0]["time"],
            }, ""
        if rb == MAIN and ra != MAIN and BRANCH_JUNCTION.get(ra) == la[-1]["code"]:
            return {
                "route": ra, "enter_at": la[0]["code"], "leave_at": la[-1]["code"],
                "main_leg": lb[-1]["code"], "enter_time": la[0]["time"],
            }, ""
        return None, f"two legs, neither shape the schema holds ({ra}+{rb})"

    return None, f"{len(legs)} legs over the division"


# --------------------------------------------------------------------------- #

def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--railpull", type=Path, required=True,
                    help="railpull's export directory -- normally <railpull>/data/out")
    ap.add_argument("-o", "--out", type=Path,
                    default=Path("data/timetable_danapur.imported.csv"),
                    help="where to write the timetable")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be imported without writing")
    args = ap.parse_args()

    trains_csv = args.railpull / "trains.csv"
    stops_csv = args.railpull / "stops.csv"
    missing = [f for f in (trains_csv, stops_csv) if not f.exists()]
    if missing:
        where = args.railpull
        print(f"No railpull export at {where}", file=sys.stderr)
        for f in missing:
            print(f"  missing: {f.name}", file=sys.stderr)
        if not where.exists():
            print(f"\nThat directory does not exist. --railpull must point at the "
                  f"folder holding railpull's exported trains.csv and stops.csv.",
                  file=sys.stderr)
        print(
            "\nTRACKSEN runs fine without this -- it falls back to the approximate\n"
            "timetable that ships in data/timetable_danapur.csv. Import only when you\n"
            "want published NTES times instead.\n"
            "\nTo produce an export:\n"
            "    git clone https://github.com/shwetankg07/railpull\n"
            "    cd railpull\n"
            "    python ntes/crawl.py        # hours: ~12,000 trains, throttled on purpose\n"
            "    python transform/export.py  # writes trains.csv and stops.csv\n"
            "\nLeave the crawler's pacing alone, and run it once rather than repeatedly:\n"
            "it is a public enquiry service and a timetable, not a live feed.\n"
            "Then point --railpull at wherever export.py put those two files.",
            file=sys.stderr,
        )
        return 2

    trains = {pick(r, "number", "train_no", "train"): r for r in load(trains_csv)}

    by_train: dict[str, list[dict]] = defaultdict(list)
    for row in load(stops_csv):
        code = pick(row, "station_code", "code", "station").upper()
        if code not in MODELLED:
            continue
        by_train[pick(row, "train_number", "train", "number", "train_no")].append({
            "code": code,
            "seq": int(pick(row, "seq", "sequence", "stop_no") or 0),
            # Departure is what puts a train on the section. A terminating stop has
            # none, and it is the last one anyway, so arrival stands in.
            "time": (pick(row, "departure", "dep", "departure_time")
                     or pick(row, "arrival", "arr", "arrival_time"))[:5],
        })

    written: list[dict] = []
    skipped: dict[str, int] = defaultdict(int)

    for number, stops in sorted(by_train.items()):
        stops.sort(key=lambda s: s["seq"])
        # Consecutive duplicates appear when a train is booked through a station twice.
        stops = [s for i, s in enumerate(stops) if i == 0 or s["code"] != stops[i - 1]["code"]]
        if len(stops) < 2:
            skipped["only touches one modelled station"] += 1
            continue
        if not all(s["time"] for s in stops):
            skipped["missing a booked time"] += 1
            continue

        meta = trains.get(number, {})
        name = pick(meta, "name", "train_name") or f"Train {number}"
        tclass = classify(name, pick(meta, "type_label", "type", "train_type"))
        runs = parse_runs(pick(meta, "runs_days", "days", "running_days"))
        if runs is None:
            skipped["NTES gave no running days"] += 1
            continue

        row, why = to_service(number, name, tclass, runs, stops)
        if row is None:
            skipped[why] += 1
            continue

        written.append({
            "train_no": number,
            "name": name.replace(",", " "),     # the file is comma-delimited
            "class": tclass,
            **row,
            "runs": runs,
            "provenance": "imported",
        })

    print(f"railpull export : {len(trains)} trains, "
          f"{len(by_train)} touching the modelled road")
    print(f"importable      : {len(written)}")
    for why, n in sorted(skipped.items(), key=lambda kv: -kv[1]):
        print(f"  skipped {n:>4}  {why}")

    per_route: dict[str, int] = defaultdict(int)
    per_class: dict[str, int] = defaultdict(int)
    for r in written:
        per_route[r["route"]] += 1
        per_class[r["class"]] += 1
    print("by route        :", dict(sorted(per_route.items())))
    print("by class        :", dict(sorted(per_class.items())))
    missing = set(ROUTE_BY_ID) - set(per_route)
    if missing:
        print(f"WARNING: no imported traffic on {sorted(missing)} -- those routes would "
              "price as empty, making a block there look free")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    fields = ["train_no", "name", "class", "route", "enter_at", "leave_at",
              "main_leg", "enter_time", "runs", "provenance"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as fh:
        fh.write(
            "# Coaching timetable — Danapur division, imported from a railpull export.\n"
            "#\n"
            "# provenance=imported: number, name, route, booked time and running days\n"
            "# all come from NTES via railpull. This is not the approximate file that\n"
            "# ships with the repository — do not describe these times as estimates.\n"
            "#\n"
            "# Local working file. railpull's README warns that bulk redistribution of\n"
            "# NTES data may run against the operator's terms of use: do not commit or\n"
            "# publish this, and re-crawl rather than passing it on.\n"
            "#\n"
            "# Goods is absent by design — goods paths are not booked, so TRACKSEN\n"
            "# forecasts them.\n"
            "#\n"
        )
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(written)

    print(f"\nwritten to {args.out}")
    print("Point samanvay.network.TIMETABLE_FILE at it, or copy it over "
          "data/timetable_danapur.csv, then re-run the pipeline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
