"""Section topology and the traffic that runs over it.

The demonstration is anchored to a real double-line electrified corridor -- the
Ahmedabad (ADI) -- Vadodara (BRC) stretch of Western Railway, roughly 100 km with
eight stations. Station sequence and approximate inter-station distances are real so
that section lengths, run times and traffic densities are plausible rather than
arbitrary. Everything else -- the individual paths, the asset population, the defect
history -- is simulated. No live railway data is used anywhere in this repository.
"""

from __future__ import annotations

import random

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
# Topology
# --------------------------------------------------------------------------- #

STATIONS: list[Station] = [
    Station("ADI", "Ahmedabad Jn", 0.0),
    Station("MAN", "Maninagar", 4.0),
    Station("VTA", "Vatva", 9.0),
    Station("MHD", "Mahemdavad Kheda Road", 34.0),
    Station("ND", "Nadiad Jn", 46.0),
    Station("ANND", "Anand Jn", 64.0),
    Station("BVI", "Bhalej", 78.0),
    Station("BRC", "Vadodara Jn", 100.0),
]


def build_sections() -> list[BlockSection]:
    """One block section between each adjacent pair of stations."""
    out: list[BlockSection] = []
    for a, b in zip(STATIONS, STATIONS[1:]):
        out.append(
            BlockSection(
                id=f"{a.code}-{b.code}",
                from_station=a.code,
                to_station=b.code,
                km_start=a.km,
                km_end=b.km,
            )
        )
    return out


SECTIONS: list[BlockSection] = build_sections()
SECTION_BY_ID: dict[str, BlockSection] = {s.id: s for s in SECTIONS}


def section_for_chainage(km: float) -> BlockSection:
    for s in SECTIONS:
        if s.contains(km):
            return s
    return SECTIONS[-1]


# --------------------------------------------------------------------------- #
# Timetable
# --------------------------------------------------------------------------- #

# Sectional running speeds (km/h) -- what each class actually makes over this road.
SPEED_KMPH = {
    TrainClass.PREMIER: 110.0,
    TrainClass.MAIL_EXP: 85.0,
    TrainClass.PASSENGER: 55.0,
    TrainClass.GOODS: 42.0,
}

# Trains per direction per day. A dense trunk corridor: goods dominates by count,
# premier traffic dominates by consequence.
DAILY_COUNT = {
    TrainClass.PREMIER: 5,
    TrainClass.MAIL_EXP: 22,
    TrainClass.PASSENGER: 12,
    TrainClass.GOODS: 28,
}

# Departure-hour weights. Coaching traffic clusters early morning and late evening;
# the mid-morning trough is precisely why the maintenance corridor sits where it does.
_COACHING_HOUR_WEIGHT = [
    3, 3, 2, 2, 3, 6, 8, 9, 7, 4, 2, 2,     # 00..11
    2, 2, 3, 4, 5, 7, 8, 9, 8, 6, 5, 4,     # 12..23
]
_GOODS_HOUR_WEIGHT = [
    6, 6, 6, 5, 4, 3, 2, 2, 3, 4, 5, 5,
    5, 5, 5, 5, 4, 3, 3, 3, 4, 5, 6, 6,
]


def _sample_departure_minute(rng: random.Random, weights: list[int]) -> int:
    hour = rng.choices(range(24), weights=weights, k=1)[0]
    return hour * 60 + rng.randrange(60)


def generate_timetable(days: int, seed: int = 7) -> list[TrainPath]:
    """Build a working timetable plus a forecast goods pattern over the horizon.

    Coaching paths repeat daily at the same time (they are booked paths). Goods paths
    are redrawn each day and carry a probability below one -- they are a forecast, not
    a booking, which is the whole reason the traffic cost of an hour is an expectation.
    """
    rng = random.Random(seed)
    paths: list[TrainPath] = []

    # Coaching: fix the pattern once, then repeat it every day of the horizon.
    booked: list[tuple[str, TrainClass, Line, int, tuple[int, int]]] = []
    for tclass in (TrainClass.PREMIER, TrainClass.MAIL_EXP, TrainClass.PASSENGER):
        for line in (Line.UP, Line.DN):
            for i in range(DAILY_COUNT[tclass]):
                number = f"{_class_prefix(tclass)}{rng.randrange(1000, 9999)}"
                depart = _sample_departure_minute(rng, _COACHING_HOUR_WEIGHT)
                booked.append((number, tclass, line, depart, _sample_route(rng, tclass)))

    for day in range(days):
        for number, tclass, line, depart, route in booked:
            paths.extend(_run_train(number, tclass, line, day, depart, route=route))

        # Goods: resampled daily, and only probably going to run.
        for line in (Line.UP, Line.DN):
            for _ in range(DAILY_COUNT[TrainClass.GOODS]):
                number = f"G{rng.randrange(10000, 99999)}"
                depart = _sample_departure_minute(rng, _GOODS_HOUR_WEIGHT)
                prob = rng.uniform(0.55, 0.95)
                paths.extend(
                    _run_train(number, TrainClass.GOODS, line, day, depart,
                               probability=prob, route=_sample_route(rng, TrainClass.GOODS))
                )

    return paths


def _class_prefix(tclass: TrainClass) -> str:
    return {"PREMIER": "P", "MAIL_EXP": "E", "PASSENGER": "S", "GOODS": "G"}[tclass.value]


def _sample_route(rng: random.Random, tclass: TrainClass) -> tuple[int, int]:
    """Which span of sections this train actually covers, as [first, last] indices.

    Premier and mail traffic runs the length of the road. Passenger services are
    largely suburban and turn back short. Goods are stabled at intermediate yards.
    The result is that sections near the origin carry materially more traffic than
    the far end -- so `consequence` differentiates instead of saturating at 1.0.
    """
    n = len(SECTIONS)
    if tclass in (TrainClass.PREMIER, TrainClass.MAIL_EXP):
        return (0, n - 1)
    if tclass is TrainClass.PASSENGER:
        # Two thirds terminate short; suburban traffic concentrates at the ADI end.
        if rng.random() < 0.66:
            return (0, rng.randrange(1, n - 1))
        return (0, n - 1)
    # Goods: any contiguous span, biased towards long runs.
    start = rng.randrange(0, max(1, n - 2))
    end = min(n - 1, start + rng.randrange(2, n))
    return (start, end)


def _run_train(
    number: str,
    tclass: TrainClass,
    line: Line,
    day: int,
    depart_min: int,
    probability: float = 1.0,
    route: tuple[int, int] | None = None,
) -> list[TrainPath]:
    """Walk a train across its route, producing one occupation per section."""
    speed = SPEED_KMPH[tclass]
    first, last = route if route is not None else (0, len(SECTIONS) - 1)
    span = SECTIONS[first:last + 1]
    ordered = span if line is Line.UP else list(reversed(span))
    t = day * MINUTES_PER_DAY + depart_min
    out: list[TrainPath] = []

    for sec in ordered:
        run_min = max(2, int(round(sec.length_km / speed * 60)))
        out.append(
            TrainPath(
                train_no=number,
                train_class=tclass,
                section_id=sec.id,
                line=line,
                day=(t // MINUTES_PER_DAY),
                enter_min=t,
                exit_min=t + run_min,
                probability=probability,
            )
        )
        t += run_min
        # Goods get looped and regulated; coaching runs through.
        if tclass is TrainClass.GOODS:
            t += 6

    return out


# --------------------------------------------------------------------------- #
# Corridor
# --------------------------------------------------------------------------- #

# Railway Board policy mandates a pre-defined maintenance corridor in the master
# chart. We model three hours per section per day, staggered along the road so that
# consecutive sections are not all shut in the same window.
CORRIDOR_HOURS = 3


def generate_corridors(days: int) -> list[CorridorWindow]:
    out: list[CorridorWindow] = []
    for day in range(days):
        for idx, sec in enumerate(SECTIONS):
            start_hour = 10 + (idx % 3)  # 10:00, 11:00 or 12:00
            base = day * MINUTES_PER_DAY
            out.append(
                CorridorWindow(
                    section_id=sec.id,
                    day=day,
                    start_min=base + start_hour * 60,
                    end_min=base + (start_hour + CORRIDOR_HOURS) * 60,
                )
            )
    return out


def corridor_lookup(corridors: list[CorridorWindow]) -> dict[tuple[str, int], CorridorWindow]:
    return {(c.section_id, c.day): c for c in corridors}
