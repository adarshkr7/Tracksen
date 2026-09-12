"""Section topology and the traffic that runs over it.

Block planning is done **division-wise**, under one DRM, so the demonstration covers one
division: **Danapur (ECR)**. The main line runs Buxar (BXR) through Patna to Jhajha
(JAJ), roughly 280 km of Howrah--Delhi trunk route, chainage measured from the Buxar end.
It stops at Jhajha because that is where Danapur ends and Asansol division of Eastern
Railway begins -- Jasidih is not this DRM's to sanction, so planning it here would be
planning someone else's road.

Every line that comes onto that main line is modelled as a real route, not drawn as
decoration. Each has its own chainage, its own block sections and its own traffic, and
each meets the main line at a junction throat they have to share:

    Ara -- Sasaram                ARA    single line, via Piro
    Patna -- Gaya                 PNBE   via Taregna and Jehanabad
    Danapur -- Sonpur -- Hajipur  DNR    over the Digha bridge -- all of North Bihar
    Fatuha -- Islampur            FUT    single line, via Ekangarsarai
    Bakhtiyarpur -- Rajgir        BKP    single line, via Bihar Sharif
    Hathidah -- Barauni           HTZ    over Rajendra Setu, across the Ganga
    Kiul -- Gaya                  KIUL   single line, via Sheikhpura and Nawada
    Kiul -- Jamalpur              KIUL   Sahibganj loop

**Blocks are planned on the main line only** -- see `PLANNED_ROUTES`. The branches are
here for what they do TO the main line: the Bhagalpur expresses off Jamalpur, the North
Bihar traffic off Hajipur, the Barauni goods over Rajendra Setu. Those movements occupy
a branch, a junction throat and then a main-line section in one run, which is precisely
why an hour on the main line at Danapur or Kiul is not worth the same as an hour at
Bihiya. Coordinating against converging traffic is harder than sequencing along one road,
and Kiul is hardest -- four legs meet there.

Branches that continue past the divisional boundary are modelled to their named terminus;
what the division actually sanctions is its own end of them.

Station sequences and approximate inter-station distances are real so that section
lengths, run times and traffic densities are plausible rather than arbitrary.

Traffic comes from two different places, because on a real railway it does:

  * **Coaching is booked**, so it is read, not invented. `data/timetable_danapur.csv`
    holds real services -- Poorva, Vikramshila, Shramjeevi, the Rajdhanis, the MEMU
    stopping traffic -- with the road each works over. Read that file's header before
    quoting it: the numbers, names and routes are real, the times are approximate, and
    the extract is thinner than the real book. On deployment it is replaced by the
    division's own WTT extract and nothing in this module changes.
  * **Goods is not booked.** There is no published path to read, so it is forecast, and
    every goods path carries the probability that it runs at all. That is the whole
    reason the traffic cost of a block hour is an expectation rather than a count.

The asset population and the defect history are simulated. No live railway data is used
anywhere in this repository.
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from pathlib import Path

from .domain import (
    MINUTES_PER_DAY,
    BlockSection,
    CorridorWindow,
    Line,
    Station,
    TrainClass,
    TrainPath,
)

# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

MAIN = "MAIN"
BRANCH = "BRN"        # kept for callers that named the Barauni branch directly


@dataclass(frozen=True)
class Route:
    id: str
    name: str
    stations: list[Station]
    # Single-line branches work one road in both directions. Modelling that halves the
    # placements the solver has to consider on those routes and is what actually
    # constrains them: on a single line, a block stops traffic both ways.
    double: bool = True

    @property
    def length_km(self) -> float:
        return self.stations[-1].km

    @property
    def lines(self) -> list[Line]:
        return [Line.UP, Line.DN] if self.double else [Line.UP]


# Patna -- Jasidih via Kiul, in running order. Chainage from Patna Jn.
MAIN_STATIONS: list[Station] = [
    Station("BXR", "Buxar", 0.0),          # western end of the division
    Station("DURE", "Dumraon", 13.0),
    Station("BEA", "Bihiya", 54.0),
    Station("ARA", "Ara Jn", 70.0),
    Station("BTA", "Bihta", 98.0),
    Station("DNR", "Danapur", 116.0),
    Station("PNBE", "Patna Jn", 126.0),
    Station("PNC", "Patna Saheb", 136.0),
    Station("FUT", "Fatuha", 151.0),
    Station("KIQ", "Khusropur", 159.0),
    Station("BKP", "Bakhtiyarpur Jn", 171.0),
    Station("BARH", "Barh", 186.0),
    Station("MKA", "Mokama Jn", 216.0),
    Station("HTZ", "Hathidah Jn", 226.0),
    Station("KIUL", "Kiul Jn", 236.0),
    Station("JAJ", "Jhajha", 281.0),       # divisional limit: Danapur / Asansol
]

# ---- branches off the main line, each with its own chainage origin ---- #

# Ara -- Sasaram, via Piro. Single line.
SASARAM_STATIONS: list[Station] = [
    Station("ARA", "Ara Jn", 0.0),
    Station("PIRO", "Piro", 22.0),
    Station("BKRG", "Bikramganj", 48.0),
    Station("SSM", "Sasaram Jn", 97.0),
]

# Danapur -- Patliputra -- Sonpur -- Hajipur, over the Digha--Sonpur rail bridge. This is
# how North Bihar reaches the main line: Muzaffarpur, Samastipur and Darbhanga traffic
# comes down it and turns onto the Delhi road at Danapur, in the middle of the division's
# busiest ten kilometres.
HAJIPUR_STATIONS: list[Station] = [
    Station("DNR", "Danapur", 0.0),
    Station("PPTA", "Patliputra Jn", 6.0),
    Station("SEE", "Sonpur Jn", 19.0),
    Station("HJP", "Hajipur Jn", 25.0),
]

# Patna -- Gaya, via Taregna and Jehanabad. This one leaves the main line at Patna Jn
# itself -- the busiest point on the division -- so a block anywhere near the Patna
# throat is contending with South Bihar traffic as well as the Delhi road.
PATNA_GAYA_STATIONS: list[Station] = [
    Station("PNBE", "Patna Jn", 0.0),
    Station("TEA", "Taregna", 28.0),
    Station("JHD", "Jehanabad", 51.0),
    Station("MDR", "Makhdumpur", 68.0),
    Station("GAYA", "Gaya Jn", 92.0),
]

# Fatuha -- Islampur, via Daniawan and Ekangarsarai. Single line, and the junction sits
# on the busiest stretch of the whole division, ten minutes out of Patna.
ISLAMPUR_STATIONS: list[Station] = [
    Station("FUT", "Fatuha", 0.0),
    Station("DNWN", "Daniawan", 21.0),
    Station("EKD", "Ekangarsarai", 38.0),
    Station("IPR", "Islampur", 52.0),
]

# Bakhtiyarpur -- Rajgir, via Bihar Sharif. Single line.
RAJGIR_STATIONS: list[Station] = [
    Station("BKP", "Bakhtiyarpur Jn", 0.0),
    Station("HRN", "Harnaut", 18.0),
    Station("BEHS", "Bihar Sharif", 38.0),
    Station("NLD", "Nalanda", 47.0),
    Station("RGD", "Rajgir", 53.0),
]

# Hathidah -- Barauni, over Rajendra Setu across the Ganga. Heavy goods road.
BRANCH_STATIONS: list[Station] = [
    Station("HTZ", "Hathidah Jn", 0.0),
    Station("RJPL", "Rajendra Pul", 4.0),
    Station("SMRA", "Simariya", 11.0),
    Station("BJU", "Barauni Jn", 28.0),
]

# Kiul -- Gaya, via Sheikhpura and Nawada. Single line.
GAYA_STATIONS: list[Station] = [
    Station("KIUL", "Kiul Jn", 0.0),
    Station("LKR", "Luckeesarai Jn", 3.0),
    Station("SHK", "Sheikhpura", 30.0),
    Station("WRS", "Warisaliganj", 62.0),
    Station("NWD", "Nawada", 78.0),
    Station("GAYA", "Gaya Jn", 124.0),
]

# Kiul -- Jamalpur, on the Sahibganj loop.
JAMALPUR_STATIONS: list[Station] = [
    Station("KIUL", "Kiul Jn", 0.0),
    Station("DRH", "Dharhara", 22.0),
    Station("JMP", "Jamalpur Jn", 48.0),
]

ROUTES: list[Route] = [
    Route(MAIN, "Buxar – Patna – Jhajha", MAIN_STATIONS, double=True),
    Route("SSM", "Ara – Sasaram", SASARAM_STATIONS, double=False),
    Route("HJP", "Danapur – Sonpur – Hajipur (over the Digha bridge)",
          HAJIPUR_STATIONS, double=True),
    Route("PTG", "Patna – Gaya (via Jehanabad)", PATNA_GAYA_STATIONS, double=True),
    Route("IPR", "Fatuha – Islampur", ISLAMPUR_STATIONS, double=False),
    Route("RGD", "Bakhtiyarpur – Rajgir", RAJGIR_STATIONS, double=False),
    Route(BRANCH, "Hathidah – Barauni (over Rajendra Setu)", BRANCH_STATIONS, double=True),
    Route("GAYA", "Kiul – Gaya", GAYA_STATIONS, double=False),
    Route("JMP", "Kiul – Jamalpur", JAMALPUR_STATIONS, double=True),
]
ROUTE_BY_ID: dict[str, Route] = {r.id: r for r in ROUTES}

# Where each branch meets the main line.
BRANCH_JUNCTION: dict[str, str] = {
    "SSM": "ARA", "HJP": "DNR", "PTG": "PNBE", "IPR": "FUT", "RGD": "BKP",
    BRANCH: "HTZ", "GAYA": "KIUL", "JMP": "KIUL",
}
JUNCTION_STATION = "HTZ"      # the busiest one, kept for callers that name it

JUNCTIONS: dict[str, str] = {
    "ARA": "Sasaram branch (modelled)",
    "DNR": "Hajipur line over the Digha bridge (modelled)",
    "PNBE": "Gaya line via Jehanabad (modelled)",
    "FUT": "Islampur branch (modelled)",
    "BKP": "Rajgir branch (modelled)",
    "MKA": "Mokama yard — goods reception and stabling",
    "HTZ": "Barauni line over Rajendra Setu (modelled)",
    "KIUL": "Gaya and Jamalpur branches (both modelled)",
}


def build_sections() -> list[BlockSection]:
    """One block section between each adjacent pair of stations, on every route."""
    out: list[BlockSection] = []
    for route in ROUTES:
        for a, b in zip(route.stations, route.stations[1:]):
            out.append(
                BlockSection(
                    id=f"{a.code}-{b.code}",
                    from_station=a.code,
                    to_station=b.code,
                    km_start=a.km,
                    km_end=b.km,
                    route=route.id,
                )
            )
    return out


SECTIONS: list[BlockSection] = build_sections()
SECTION_BY_ID: dict[str, BlockSection] = {s.id: s for s in SECTIONS}
STATIONS: list[Station] = MAIN_STATIONS     # the main line, for the corridor schematic



# Routes this division actually plans blocks on.
#
# The demonstration is scoped to the main line. The branches are modelled in full --
# their own chainage, their own block sections, their own traffic -- but they are
# *traffic and constraint*, not workload. What makes the main line hard to plan is not
# work on the Gaya branch; it is the Barauni goods and the Bhagalpur expresses working
# off the branches onto it, and the junction throats they have to share on the way.
#
# Widening the demonstration to a branch takes one entry here: the asset population, the
# corridor windows and everything downstream of them read this list.
PLANNED_ROUTES: list[str] = [MAIN]


def sections_of(route_id: str) -> list[BlockSection]:
    return [s for s in SECTIONS if s.route == route_id]


def planned_sections() -> list[BlockSection]:
    """The sections blocks may be planned on. Branch sections carry traffic only."""
    return [s for s in SECTIONS if s.route in PLANNED_ROUTES]


def lines_of(route_id: str) -> list[Line]:
    """Which running lines a route has. Single-line branches have one."""
    return ROUTE_BY_ID[route_id].lines


def lines_for_section(section_id: str) -> list[Line]:
    return lines_of(SECTION_BY_ID[section_id].route)


def station_index(code: str, route_id: str = MAIN) -> int:
    for i, st in enumerate(ROUTE_BY_ID[route_id].stations):
        if st.code == code:
            return i
    raise KeyError(f"{code} not on {route_id}")


def junction_km(code: str, route_id: str = MAIN) -> float:
    return ROUTE_BY_ID[route_id].stations[station_index(code, route_id)].km


def section_for_chainage(km: float, route_id: str = MAIN) -> BlockSection:
    for s in sections_of(route_id):
        if s.contains(km):
            return s
    return sections_of(route_id)[-1]


def junction_groups() -> dict[str, list[str]]:
    """Sections meeting at each junction.

    Work in the throat of one leg conflicts with work in the throat of another, however
    many legs converge, because the throat is a single interlocked area.
    """
    out: dict[str, list[str]] = {}
    for s in SECTIONS:
        for end in (s.from_station, s.to_station):
            if end in JUNCTIONS:
                out.setdefault(end, []).append(s.id)
    return {k: v for k, v in out.items() if len(v) > 1}


JUNCTION_GROUPS: dict[str, list[str]] = junction_groups()

# How close to the junction station work has to be to interact with the throat. Beyond
# this it is plain line and the converging legs are independent of each other.
JUNCTION_THROAT_KM = 3.0


@dataclass(frozen=True)
class Branch:
    """A line joining the corridor, for the schematic."""

    junction: str
    name: str
    side: str           # "N" or "S" of the formation, as drawn
    note: str = ""
    modelled: bool = False


BRANCHES: list[Branch] = [
    Branch("ARA", "Sasaram", "S", "via Piro", modelled=True),
    Branch("DNR", "Hajipur", "N", "via Patliputra and Sonpur", modelled=True),
    Branch("PNBE", "Gaya", "S", "via Jehanabad", modelled=True),
    Branch("FUT", "Islampur", "S", "via Ekangarsarai", modelled=True),
    Branch("BKP", "Rajgir", "S", "via Bihar Sharif", modelled=True),
    Branch("HTZ", "Barauni", "N", "over Rajendra Setu", modelled=True),
    Branch("KIUL", "Gaya", "S", "via Sheikhpura and Nawada", modelled=True),
    Branch("KIUL", "Jamalpur", "N", "Sahibganj loop", modelled=True),
]


# --------------------------------------------------------------------------- #
# Timetable
# --------------------------------------------------------------------------- #

SPEED_KMPH = {
    TrainClass.PREMIER: 110.0,
    TrainClass.MAIL_EXP: 85.0,
    TrainClass.PASSENGER: 55.0,
    TrainClass.GOODS: 42.0,
}

# Minutes a through movement stands at the junction while the road is set for it.
JUNCTION_RECEPTION_MIN = 8


# --------------------------------------------------------------------------- #
# Coaching services, read from the timetable file
# --------------------------------------------------------------------------- #
#
# Coaching paths are booked, so they are read rather than sampled.
#
# Two files can supply them, and which one is in use is not a detail to keep quiet about:
#
#   timetable_danapur.imported.csv   Written by scripts/import_railpull.py from a local
#                                    railpull crawl of NTES. Real booked times, real
#                                    running days. Preferred whenever it exists.
#   timetable_danapur.csv            Ships with the repository. Real train numbers, names
#                                    and routes; APPROXIMATE times and running days.
#
# The imported file wins, so running the crawl is the only step needed to move the whole
# system onto published data -- no code change, no configuration. It is absent by default
# because railpull's README asks that NTES data not be redistributed, so it cannot be
# committed here; the repository has to be runnable without a multi-hour crawl, and the
# approximate file is what makes that true.
#
# On a real deployment both are replaced by the division's own WTT extract. Nothing below
# this point changes either way: the columns are the contract.

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SHIPPED_TIMETABLE = DATA_DIR / "timetable_danapur.csv"
IMPORTED_TIMETABLE = DATA_DIR / "timetable_danapur.imported.csv"


def resolve_timetable() -> Path:
    """The timetable in force. Imported data beats the approximate file that ships."""
    return IMPORTED_TIMETABLE if IMPORTED_TIMETABLE.exists() else SHIPPED_TIMETABLE


TIMETABLE_FILE = resolve_timetable()

# True when the times and running days in force are published rather than estimated.
# Surfaced all the way to the UI: a screen showing approximate times must say so.
TIMETABLE_IS_IMPORTED = TIMETABLE_FILE == IMPORTED_TIMETABLE

# Day 0 of the planning horizon is a Monday.
#
# The horizon is integer days, but running days are not: a tri-weekly express is on the
# road three times a week and absent the rest, so the cheapest hour on a Tuesday is not
# the cheapest hour on a Sunday. Without an anchor there is no weekday to compare a
# booking against, and every day of the plan would look identical.
HORIZON_START_WEEKDAY = 0
WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
ALL_DAYS = frozenset(range(7))


@dataclass(frozen=True)
class BookedService:
    """One coaching service, as booked over this division."""

    train_no: str
    name: str
    train_class: TrainClass
    route_id: str
    enter_at: str
    leave_at: str
    # For a branch service that works through onto the main line, the main-line station
    # it runs to or comes from. None if it terminates at the junction, or is main line.
    main_leg: str | None
    enter_min: int          # minutes past midnight at enter_at
    runs: frozenset[int]    # weekdays it works, 0 = Monday
    provenance: str         # "named" or "representative" -- see the file header

    def runs_on(self, day: int) -> bool:
        """Whether this service is on the road on the given horizon day."""
        return (HORIZON_START_WEEKDAY + day) % 7 in self.runs

    @property
    def days_per_week(self) -> int:
        return len(self.runs)


def _parse_hhmm(value: str) -> int:
    hh, mm = value.strip().split(":")
    return int(hh) * 60 + int(mm)


def _parse_runs(value: str) -> frozenset[int]:
    """"daily", or day codes run together: MoWeFr, TuSa, Su."""
    raw = value.strip()
    if raw.lower() == "daily":
        return ALL_DAYS
    if not raw or len(raw) % 2:
        raise ValueError(f"cannot read running days from {value!r}")
    days = set()
    for i in range(0, len(raw), 2):
        code = raw[i:i + 2]
        if code not in WEEKDAYS:
            raise ValueError(f"unknown day code {code!r} in {value!r}")
        days.add(WEEKDAYS.index(code))
    if not days:
        raise ValueError(f"a service that runs no days is not a service: {value!r}")
    return frozenset(days)


def load_booked_services(path: Path | str = TIMETABLE_FILE) -> list[BookedService]:
    """Read the coaching timetable.

    Every station reference is checked against the topology as it is read. A typo in the
    file should stop the run, not quietly delete a train from the traffic model and make
    an hour look cheaper than it is.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"coaching timetable not found at {path}. It ships with the repository; "
            "on deployment point TIMETABLE_FILE at the division's WTT extract."
        )

    out: list[BookedService] = []
    with path.open(encoding="utf-8", newline="") as fh:
        rows = csv.DictReader(line for line in fh if not line.lstrip().startswith("#"))
        for n, row in enumerate(rows, start=2):
            route_id = row["route"].strip()
            if route_id not in ROUTE_BY_ID:
                raise ValueError(f"{path}:{n}: unknown route {route_id!r}")

            enter_at, leave_at = row["enter_at"].strip(), row["leave_at"].strip()
            main_leg = (row.get("main_leg") or "").strip() or None
            for code in (enter_at, leave_at):
                station_index(code, route_id)       # raises if not on this route
            if enter_at == leave_at:
                raise ValueError(f"{path}:{n}: {row['train_no']} starts where it ends")

            if main_leg is not None:
                if route_id == MAIN:
                    raise ValueError(
                        f"{path}:{n}: main_leg is for branch services only"
                    )
                jn = BRANCH_JUNCTION[route_id]
                if jn not in (enter_at, leave_at):
                    raise ValueError(
                        f"{path}:{n}: {row['train_no']} carries a main leg but neither "
                        f"end is the junction {jn}"
                    )
                station_index(main_leg, MAIN)
                if main_leg == jn:
                    raise ValueError(f"{path}:{n}: main leg is the junction itself")

            out.append(
                BookedService(
                    train_no=row["train_no"].strip(),
                    name=row["name"].strip(),
                    train_class=TrainClass(row["class"].strip()),
                    route_id=route_id,
                    enter_at=enter_at,
                    leave_at=leave_at,
                    main_leg=main_leg,
                    enter_min=_parse_hhmm(row["enter_time"]),
                    runs=_parse_runs(row["runs"]),
                    provenance=row["provenance"].strip(),
                )
            )
    return out


BOOKED_SERVICES: list[BookedService] = load_booked_services()


# --------------------------------------------------------------------------- #
# Goods, forecast rather than booked
# --------------------------------------------------------------------------- #

# Goods trains per direction per day on the main line.
GOODS_PER_DAY_MAIN = 28

# Goods trains per direction per day working between each branch and the main line
# through its junction. Barauni dominates -- it is why Mokama--Hathidah is contended at
# hours when the main line alone would be quiet.
GOODS_PER_DAY_BRANCH: dict[str, int] = {
    "SSM": 3, "HJP": 9, "PTG": 7, "IPR": 2, "RGD": 2, BRANCH: 16, "GAYA": 6, "JMP": 8,
}

_GOODS_HOUR_WEIGHT = [
    6, 6, 6, 5, 4, 3, 2, 2, 3, 4, 5, 5,
    5, 5, 5, 5, 4, 3, 3, 3, 4, 5, 6, 6,
]


def _sample_departure_minute(rng: random.Random, weights: list[int]) -> int:
    hour = rng.choices(range(24), weights=weights, k=1)[0]
    return hour * 60 + rng.randrange(60)


def _sample_goods_route(rng: random.Random) -> tuple[int, int]:
    """Which span of main-line sections a goods train covers, as [first, last]."""
    n = len(sections_of(MAIN))
    start = rng.randrange(0, max(1, n - 2))
    end = min(n - 1, start + rng.randrange(2, n))
    return (start, end)


# --------------------------------------------------------------------------- #
# Running trains over the topology
# --------------------------------------------------------------------------- #


def _walk(number: str, tclass: TrainClass, line: Line, span: list[BlockSection],
          start_min: int, probability: float = 1.0,
          name: str = "") -> tuple[list[TrainPath], int]:
    """Run a train across a list of sections, in the order given."""
    speed = SPEED_KMPH[tclass]
    t = start_min
    out: list[TrainPath] = []
    for sec in span:
        run_min = max(2, int(round(sec.length_km / speed * 60)))
        out.append(
            TrainPath(
                train_no=number, train_class=tclass, section_id=sec.id, line=line,
                day=(t // MINUTES_PER_DAY), enter_min=t, exit_min=t + run_min,
                probability=probability, train_name=name,
            )
        )
        t += run_min
        if tclass is TrainClass.GOODS:
            t += 6
    return out, t


def _span(route_id: str, a: str, b: str) -> tuple[list[BlockSection], Line]:
    """The sections between two stations on one route, in running order.

    Increasing chainage is taken as UP on every route. A single-line branch works one
    road in both directions, so both directions are booked on it.
    """
    ia, ib = station_index(a, route_id), station_index(b, route_id)
    secs = sections_of(route_id)
    if ia < ib:
        span, line = secs[ia:ib], Line.UP
    else:
        span, line = list(reversed(secs[ib:ia])), Line.DN
    if not ROUTE_BY_ID[route_id].double:
        line = Line.UP
    return span, line


def run_service(svc: BookedService, day: int) -> list[TrainPath]:
    """A booked coaching service, run over the topology on one day.

    A branch service with a main leg occupies the branch, the junction and the main line
    in one movement. That is what makes a throat contended rather than merely busy, and
    is why a block on one leg has to be planned against the others.
    """
    jn = BRANCH_JUNCTION.get(svc.route_id)
    own = _span(svc.route_id, svc.enter_at, svc.leave_at)

    if svc.main_leg is None:
        legs = [own]
    elif svc.leave_at == jn:                    # branch first, then out along the main
        legs = [own, _span(MAIN, jn, svc.main_leg)]
    else:                                       # in along the main, then the branch
        legs = [_span(MAIN, svc.main_leg, jn), own]

    paths: list[TrainPath] = []
    t = day * MINUTES_PER_DAY + svc.enter_min
    for i, (span, line) in enumerate(legs):
        if i:
            t += JUNCTION_RECEPTION_MIN
        more, t = _walk(svc.train_no, svc.train_class, line, span, t, name=svc.name)
        paths.extend(more)
    return paths


def _run_goods_main(number: str, line: Line, day: int, depart_min: int,
                    probability: float, route: tuple[int, int]) -> list[TrainPath]:
    main = sections_of(MAIN)
    first, last = route
    span = main[first:last + 1]
    ordered = span if line is Line.UP else list(reversed(span))
    paths, _ = _walk(number, TrainClass.GOODS, line, ordered,
                     day * MINUTES_PER_DAY + depart_min, probability)
    return paths


def _run_goods_branch(number: str, line: Line, day: int, depart_min: int, route_id: str,
                      toward_patna: bool, probability: float) -> list[TrainPath]:
    """A goods train working between a branch and the main line through its junction."""
    branch = sections_of(route_id)
    main = sections_of(MAIN)
    jn = BRANCH_JUNCTION[route_id]
    j = station_index(jn, MAIN)          # main sections before j are Patna-side

    patna_side = list(reversed(main[:j]))
    far_side = main[j:]
    # A junction at either end of the main line only has one way onward.
    if not patna_side:
        toward_patna = False
    if not far_side:
        toward_patna = True

    branch_line = line if ROUTE_BY_ID[route_id].double else Line.UP

    if line is Line.UP:                       # off the branch, onto the main line
        span_a, line_a = list(reversed(branch)), branch_line
        span_b, line_b = (patna_side if toward_patna else far_side), line
    else:                                     # off the main line, onto the branch
        span_a, line_a = (main[:j] if toward_patna else list(reversed(far_side))), line
        span_b, line_b = branch, branch_line

    start = day * MINUTES_PER_DAY + depart_min
    paths, t = _walk(number, TrainClass.GOODS, line_a, span_a, start, probability)
    more, _ = _walk(number, TrainClass.GOODS, line_b, span_b,
                    t + JUNCTION_RECEPTION_MIN, probability)
    return paths + more


def generate_timetable(days: int, seed: int = 7) -> list[TrainPath]:
    """Booked coaching services from the timetable file, plus forecast goods.

    Coaching is deterministic: it comes off the book, at the booked time, on the days
    that service actually works. A tri-weekly express is not on the road four days a
    week, and pretending it is would make every day of the horizon look alike -- which
    would hide the one thing a planner is looking for, the day this section is quiet.

    Goods is resampled every day and each path carries the probability it runs at all.
    """
    rng = random.Random(seed)
    paths: list[TrainPath] = []

    for day in range(days):
        for svc in BOOKED_SERVICES:
            if not svc.runs_on(day):
                continue
            paths.extend(run_service(svc, day))

        for line in (Line.UP, Line.DN):
            for _ in range(GOODS_PER_DAY_MAIN):
                number = f"G{rng.randrange(10000, 99999)}"
                depart = _sample_departure_minute(rng, _GOODS_HOUR_WEIGHT)
                paths.extend(_run_goods_main(
                    number, line, day, depart,
                    probability=rng.uniform(0.55, 0.95),
                    route=_sample_goods_route(rng),
                ))

            for route_id, per_day in GOODS_PER_DAY_BRANCH.items():
                for _ in range(per_day):
                    number = f"G{rng.randrange(10000, 99999)}"
                    depart = _sample_departure_minute(rng, _GOODS_HOUR_WEIGHT)
                    paths.extend(_run_goods_branch(
                        number, line, day, depart, route_id,
                        toward_patna=rng.random() < 0.62,
                        probability=rng.uniform(0.6, 0.95),
                    ))

    return paths


# --------------------------------------------------------------------------- #
# Corridor
# --------------------------------------------------------------------------- #

CORRIDOR_HOURS = 3


def generate_corridors(days: int) -> list[CorridorWindow]:
    """The mandated maintenance corridor, staggered along the planned road.

    Only sections that carry work get a corridor. A corridor on a section nobody plans
    on would inflate the slot count the monthly view reports as available.
    """
    out: list[CorridorWindow] = []
    for day in range(days):
        for idx, sec in enumerate(planned_sections()):
            start_hour = 10 + (idx % 3)
            base = day * MINUTES_PER_DAY
            out.append(
                CorridorWindow(
                    section_id=sec.id, day=day,
                    start_min=base + start_hour * 60,
                    end_min=base + (start_hour + CORRIDOR_HOURS) * 60,
                )
            )
    return out


def corridor_lookup(corridors: list[CorridorWindow]) -> dict[tuple[str, int], CorridorWindow]:
    return {(c.section_id, c.day): c for c in corridors}
