"""Mapping a published stop sequence onto this division's routes.

Shared by every timetable importer, because the hard part is the same whatever the
source: a published schedule is a list of station calls, and this network is a main line
with eight branches meeting it at junctions. Turning one into the other is where the
mistakes live, so it lives in one place and is tested once.

Importers differ only in how they read their own file. What a stop sequence MEANS is
here.
"""

from __future__ import annotations

import re
from collections import defaultdict

from .network import (BRANCH_JUNCTION, MAIN, ROUTE_BY_ID, ROUTES, SPEED_KMPH,
                      junction_km)

# Markers mapped onto the running priority order. Anything unrecognised falls to
# MAIL_EXP, which is the common case and the safe one: calling a stopping train an
# express overstates its detention weight slightly, whereas calling an express a
# passenger train would understate it -- and understating is the direction that makes a
# block look cheaper than it is.
#
# Deliberately short, because published names are truncated. The data.gov.in dataset caps
# them at twelve characters, so 12309 arrives as "PATNA RAJDHA" and 12301 as
# "KOLKATA RAJD" -- matching on "rajdhani" finds neither, and an import that silently
# contains no premier traffic at all leaves the premier fence untested against a live
# plan while appearing to work.
PREMIER_MARKERS = ("rajd", "shatab", "duront", "vande", "tejas", "gatim")

# Jan Shatabdi is not Shatabdi. It is a chair-car intercity and sits with the expresses;
# "shatab" would otherwise sweep it into the protected class and fence off windows that
# a division would in fact be given.
NOT_PREMIER = ("jan shatabdi", "janshatabdi", "jan shatab", "janshatab")

PASSENGER_MARKERS = ("memu", "demu", "passenger", "ordinary", "suburban", "emu", "pass")


def classify(name: str, ttype: str = "", number: str = "") -> str:
    """Running priority for one service, from its name, type and number.

    The number is the most reliable of the three. Indian Railways' five-digit scheme is
    systematic where names are abbreviated inconsistently: the 5xxxx series is
    conventional passenger, 6xxxx is MEMU/EMU and 7xxxx is DMU, all of which are stopping
    traffic whatever the name happens to say. Names carry the premier tiers, which the
    numbering does not separate from ordinary superfasts.
    """
    blob = f"{name} {ttype}".lower()

    if any(m in blob for m in PREMIER_MARKERS) and not any(m in blob for m in NOT_PREMIER):
        return "PREMIER"

    n = (number or "").strip()
    if len(n) == 5 and n[0] in "567":
        return "PASSENGER"

    if any(m in blob for m in PASSENGER_MARKERS):
        return "PASSENGER"
    return "MAIL_EXP"


# --------------------------------------------------------------------------- #
# Resolving a published station name to a code
# --------------------------------------------------------------------------- #
#
# Some sources give codes, some give names, and the names are not spelled the way this
# repository spells them. Matching on a normalised form gets 36 of the 41 modelled
# stations; the rest are listed here explicitly rather than matched by fuzzy distance,
# because a near-miss does not fail loudly -- it puts a train on the wrong road.
#
# Deliberately absent: Simariya, on the Barauni branch. The candidates in the published
# data ("Simariatal", "Simariya Kajanwada") are elsewhere in the country, and guessing
# would move traffic onto a road it never touches. It is an intermediate station on a
# 28 km branch whose ends both resolve, so losing it costs nothing.
STATION_ALIASES: dict[str, str] = {
    "daniyawan": "DNWN",          # Daniawan, on the Islampur branch
    "daniyawanbazar": "DNWN",
    "ekangarsarai": "EKD",
    "ekangarsaraif": "EKD",
    "makhdumpurgaya": "MDR",      # distinguishes it from Makhdumpur elsewhere
    "mokameh": "MKA",             # Mokama is spelled Mokameh in most published data
    "fatwa": "FUT",               # Fatuha
    "warisaleganj": "WRS",        # Warisaliganj
    "sheikpura": "SHK",           # Sheikhpura
    "nawadah": "NWD",             # Nawada. NOT "Nawadih", which is in Jharkhand.
}


# IRCTC's export carries a booking-quota marker in FRONT of the station name -- "RL
# Patna Jn" for Remote Location, "PQ New Delhi" for Pooled Quota, "RS" for roadside.
# It is not part of the name and it is not rare: 7,722 of the stop entries in
# IRCTC_cleaned.csv carry one, and with the marker left in place every one of those
# calls failed to resolve. 12273 Howrah-New Delhi Duronto touches this division at
# exactly one station -- "RL Patna Jn" -- so it resolved to nothing at all.
_QUOTA_PREFIX = re.compile(r"^(?:RL|PQ|RS)\s+(?=\S)")


def normalise_station(name: str) -> str:
    """Published station name -> a form two sources can be compared on."""
    s = re.sub(r"[^a-z0-9]", "", _QUOTA_PREFIX.sub("", (name or "").strip()).lower())
    # "Junction" and "Halt" are decoration. A bare trailing "h" is NOT: stripping it
    # turned "Mokameh" into "mokame" and stopped it matching anything at all.
    for suffix in ("junction", "jn", "halt"):
        if s.endswith(suffix) and len(s) > len(suffix) + 2:
            s = s[: -len(suffix)]
    return s


def _build_name_index() -> dict[str, str]:
    index = dict(STATION_ALIASES)
    for route in ROUTES:
        for st in route.stations:
            index.setdefault(normalise_station(st.name), st.code)
    return index


NAME_TO_CODE: dict[str, str] = _build_name_index()


def code_for_name(name: str) -> str | None:
    """The modelled station this published name refers to, or None."""
    return NAME_TO_CODE.get(normalise_station(name))


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


def unambiguous_route(code: str) -> str | None:
    """The route a station can only be on. None for a junction, which is on several."""
    routes = STATION_ROUTES[code]
    return routes[0] if len(routes) == 1 else None


def shared_route(codes: list[str]) -> str | None:
    """The one road every stop lies on, for a run whose stops are all junctions.

    Needed because "unambiguous" is the wrong test when a service calls only at
    junctions. 12309/12310 Rajendra Nagar-New Delhi touches this division at Patna Jn
    and Danapur and nowhere else; both are junction throats, so no stop was unambiguous
    and the service was thrown away as route-indeterminate. Patna and Danapur are the
    two busiest stations here, and the trains that call only there are exactly the
    long-distance premier ones -- the fence was protecting a timetable that contained no
    Rajdhani at all.

    Intersecting settles it without guessing. Patna Jn is on the main line and the Gaya
    branch, Danapur on the main line and the Hajipur branch; the main line is the only
    road carrying both.

    Where the intersection still holds more than one road the main line wins, because
    every branch meets the main line at exactly one junction -- so two DIFFERENT
    junctions can only be joined along the main line. Where it holds no main line, this
    returns None rather than picking a branch: that would be a guess, and a guess here
    puts a train on a road it never touches.
    """
    sets = [r for r in (set(STATION_ROUTES[c]) for c in codes) if r]
    if len(sets) < 2:
        return None
    shared = set.intersection(*sets)
    return MAIN if MAIN in shared else None


# --------------------------------------------------------------------------- #
# Where a service leaves the modelled network
# --------------------------------------------------------------------------- #
#
# A leg ran from the first modelled STOP to the last, which is the same thing as the
# first modelled kilometre to the last only for a train that happens to halt at the
# boundary. 12309 Rajendra Nagar-New Delhi halts at Patna and Danapur and then runs
# non-stop through Bihta, Ara, Dumraon and Buxar to DDU -- the whole western half of the
# division -- and the leg stopped at Danapur, ten kilometres in. Understating occupation
# is the direction that makes a block look cheaper than it is.
#
# These are the stations just outside the network and the boundary each lies beyond.
# Derived from the data rather than from memory: for every off-network station appearing
# next to a modelled stop in IRCTC_cleaned.csv, the modelled station it actually abuts.
# Each of the twenty candidates resolved to exactly one boundary.
#
# Rajendra Nagar Terminal is the entry that matters by its ABSENCE. It sits next to Patna
# 106 times and it is INSIDE the division, so 12310 -- which terminates there -- must not
# be extended east to Jhajha. Any rule reading "the destination is not a modelled
# station, so the train must be leaving" gets that train exactly wrong.
# A gateway can lie beyond MORE THAN ONE boundary, which is the trap. Mughalsarai is
# beyond Buxar on the Patna road AND beyond Sasaram on the Grand Chord; Samastipur is
# beyond Barauni and also beyond Muzaffarpur. Reading the adjacency counts as if each
# had a single answer put the Ranchi-Varanasi Vande Bharat -- a Grand Chord train, Gaya
# to Sasaram to Mughalsarai, which never touches this network -- up the Ara-Sasaram
# branch and out along our main line to Buxar. So each gateway lists every boundary it
# can sit beyond, and one is chosen only when the REAL stops already place the train on
# that road.
GATEWAYS: dict[str, tuple[str, ...]] = {
    # West of Buxar on the Patna road -- and west of Sasaram on the Grand Chord
    "ddupadhyaya": ("BXR", "SSM"), "ptdeendayalupadhyaya": ("BXR", "SSM"),
    "mughalsarai": ("BXR", "SSM"),
    "dildarnagar": ("BXR",), "chausa": ("BXR",), "gahmar": ("BXR",),
    "pawanikumarpur": ("BXR",),
    # East, beyond Jhajha. Everything from Deoghar, Asansol, Jamtara, Durgapur and
    # Howrah reaches this division through Jasidih, so it needs no entry of its own.
    "jasidih": ("JAJ",), "simultala": ("JAJ",), "rajla": ("JAJ",), "madhupur": ("JAJ",),
    "narganjo": ("JAJ",),
    # Beyond Sasaram on the Grand Chord. NOT beyond Buxar: Bhabua Road is on the other
    # road entirely, and the adjacency count says so -- 58 against Sasaram.
    "bhabuaroad": ("SSM",), "kudra": ("SSM",), "kumahu": ("SSM",),
    "dehrionsone": ("SSM",), "dehrionson": ("SSM",),
    # Beyond Gaya, shared by the Patna-Gaya and Kiul-Gaya roads
    "koderma": ("GAYA",), "dhanbad": ("GAYA",), "tankuppa": ("GAYA",),
    "paharpur": ("GAYA",), "guraru": ("GAYA",), "kastha": ("GAYA",),
    # Beyond Hajipur. Chhapra and Dighwara are deliberately NOT here: they lead into
    # SONPUR, which is in the middle of this branch rather than at the end of it, so a
    # train off the Chhapra road is already described by its Sonpur call. Listing them
    # made 11033 Pune-Darbhanga enter and leave at Hajipur -- a leg that starts where it
    # ends -- and took 45 Hajipur services with it.
    "muzaffarpur": ("HJP",), "bhagwanpur": ("HJP",), "ghoshawar": ("HJP",),
    # Beyond Barauni over Rajendra Setu -- Samastipur also sits beyond Muzaffarpur
    "begusarai": ("BJU",), "barauni": ("BJU",), "newbarauni": ("BJU",),
    "baraunif": ("BJU",), "dalsinghsarai": ("BJU",), "teghra": ("BJU",),
    "bihat": ("BJU",), "khagaria": ("BJU",), "katihar": ("BJU",),
    "samastipur": ("BJU", "HJP"),
    # Beyond Jamalpur, towards Bhagalpur and on to Banka, Hansdiha, Dumka and Godda.
    # Abhaipur is deliberately absent: it sits BETWEEN Jamalpur and Kiul, inside this
    # branch rather than past the end of it, and a mid-road station is not a gateway.
    "bariarpur": ("JMP",), "sultanganj": ("JMP",), "ratanpur": ("JMP",),
    "bhagalpur": ("JMP",), "barahat": ("JMP",), "mandarhill": ("JMP",), "patam": ("JMP",),
    "banka": ("JMP",), "hansdiha": ("JMP",), "dumka": ("JMP",), "godda": ("JMP",),
}

SPEED_FOR = {c.name: v for c, v in SPEED_KMPH.items()}

# A gateway names the boundary it lies beyond, and a boundary is where the modelled
# network STOPS: the two ends of the main line, and the far end of each branch. A station
# leading into the middle of a road is not a gateway -- the train's own call there
# already says where it joined.
BOUNDARIES: frozenset[str] = frozenset(
    [ROUTE_BY_ID[MAIN].stations[0].code, ROUTE_BY_ID[MAIN].stations[-1].code]
    + [r.stations[-1].code for r in ROUTES if r.id != MAIN]
)

_stray = {b for bs in GATEWAYS.values() for b in bs} - BOUNDARIES
if _stray:                                          # pragma: no cover - import-time guard
    raise ValueError(f"gateway points at a non-boundary: {sorted(_stray)}")


def gateway_boundaries(name: str) -> tuple[str, ...]:
    """Modelled boundaries this off-network station can lie beyond."""
    return GATEWAYS.get(normalise_station(name), ())


def _turn_off(boundary: str, on_roads: set[str]) -> bool:
    """Is this boundary on a branch leaving a road the train is already using?

    The case is a train that runs the main line and turns up a branch without calling
    anywhere on it: 22234 Patna-New Jalpaiguri halts at Patna and Patna Sahib, then runs
    to Hathidah and over Rajendra Setu to Barauni with no other booked stop here.
    """
    return any(
        on_roads & set(STATION_ROUTES[BRANCH_JUNCTION[r]])
        for r in STATION_ROUTES[boundary]
        if r in BRANCH_JUNCTION and BRANCH_JUNCTION[r] in STATION_ROUTES
    )


def _nearest_gateway(neighbours: list[dict], on_roads: set[str]) -> dict | None:
    """First usable gateway, scanning outward from the modelled span.

    A station can sit beyond more than one boundary -- Mughalsarai is beyond Buxar on the
    Patna road and beyond Sasaram on the Grand Chord -- so the two readings are ranked
    rather than pooled:

      1. a boundary on a road the train has actually called on. This is what keeps
         20887 Ranchi-Varanasi, a Grand Chord train calling at Gaya and Sasaram, off our
         main line: Mughalsarai reads as Sasaram, the road it has been on, not Buxar.

      2. failing that, a boundary up a branch leaving a road it has called on -- and only
         when the VERY NEXT call evidences it. "Somewhere down its route it reaches
         Barauni" says nothing about where it left the main line; "the next place it
         stops is Begusarai" does. Without that restriction every branch end is reachable
         from the main line and thirty-one main-line services turned into branch
         movements.

    The two ends of the main line keep the outward scan under rule 1, because a train
    leaving the division carries on in one direction and may not call for 200 km.
    """
    for i, stop in enumerate(neighbours):
        candidates = gateway_boundaries(stop.get("name", ""))
        on_road = [b for b in candidates if on_roads & set(STATION_ROUTES[b])]
        if len(on_road) == 1:
            return {"code": on_road[0], "time": stop.get("time", ""), "gateway": True}
        if on_road:
            continue                      # genuinely ambiguous; do not guess
        if i:
            continue                      # a turn-off needs the adjacent call
        turn = [b for b in candidates if _turn_off(b, on_roads)]
        if len(turn) == 1:
            return {"code": turn[0], "time": stop.get("time", ""), "gateway": True}
    return None


def _shift(hhmm_str: str, minutes: int) -> str:
    """Clock arithmetic, wrapping at midnight."""
    try:
        h, m = (int(x) for x in hhmm_str.split(":"))
    except (ValueError, AttributeError):
        return hhmm_str
    total = (h * 60 + m + minutes) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def _boundary_time(route: str, boundary: str, anchor: dict, tclass: str) -> str:
    """Clock time at a boundary the train passes without stopping.

    Backed off from the nearest BOOKED stop at the model's own line speed, so that
    running the service forward from the boundary puts it at that stop at the time the
    timetable actually publishes. Anchoring on the gateway station's own time instead
    would drag the whole path: 12310 leaves DDU at 02:00 and is 200 km short of Danapur,
    which is nothing like the 116 km from Buxar.
    """
    try:
        km = abs(junction_km(boundary, route) - junction_km(anchor["code"], route))
    except KeyError:
        return anchor.get("time", "")
    speed = SPEED_FOR.get(tclass, SPEED_FOR["MAIL_EXP"])
    return _shift(anchor.get("time", ""), -int(round(km / speed * 60)))


def to_service(number: str, name: str, tclass: str, runs: str,
               stops: list[dict], before: list[dict] | None = None,
               after: list[dict] | None = None) -> tuple[dict | None, str]:
    """One timetable row, or a reason it could not be written.

    Classified from the SET of roads the stops lie on, not from consecutive pairs.

    Pairing was the obvious approach and it was wrong: it assumed a train stops at every
    modelled station it passes. Expresses do not. The Vikramshila calls at Jamalpur and
    then at Patna, skipping Kiul -- so the two stops share no route, the pair test found
    no leg, and a train that plainly runs over this division was thrown away. It cost 44%
    of the traffic on the first real import, all of it in the direction that makes a block
    look cheaper than it is.

    Reading the set instead is robust to skipped stops, because the topology is a star:
    every branch meets the main line at exactly one junction, so "these stops are on the
    Jamalpur branch and on the main line" determines the run without needing the junction
    to appear in it.
    """
    # A gateway is evidence about the road in exactly the way a stop is, so it is folded
    # in as a pseudo-stop at the boundary and everything below -- route classification,
    # clamping, the through-service split -- sees it without knowing the difference.
    on_roads = {r for s in stops for r in STATION_ROUTES[s["code"]]}
    lead = _nearest_gateway(list(reversed(before or [])), on_roads)
    tail = _nearest_gateway(list(after or []), on_roads)
    stops = ([lead] if lead else []) + list(stops) + ([tail] if tail else [])

    codes = [s["code"] for s in stops]
    # Junctions belong to several routes and settle nothing; the stops that can only be
    # on one road are what identify the run.
    certain = {r for r in (unambiguous_route(c) for c in codes) if r}

    if not certain:
        # Every stop was a junction. No single stop distinguishes the road, but the road
        # they all share may still do it.
        shared = shared_route(codes)
        if shared is None:
            return None, "only junction stops -- route indeterminate"
        certain = {shared}

    # A branch service can reach the main line and have every call on it be a junction.
    # 13229 Godda-Rajendra Nagar calls Jamalpur, then Kiul, Hathidah and Bakhtiyarpur --
    # the last three all junction throats -- so nothing put it on the main line and
    # sixty-five kilometres of main-line running were thrown away. The road those calls
    # share settles it, exactly as it does for a run made only of junctions.
    if certain and MAIN not in certain and len(certain - {MAIN}) == 1:
        branch_only = certain.copy().pop()
        rest = [c for c in codes if branch_only not in STATION_ROUTES[c]]
        if shared_route(rest) == MAIN:
            certain = certain | {MAIN}

    branches = certain - {MAIN}
    if len(branches) > 1:
        return None, f"runs over {len(branches)} branches ({'+'.join(sorted(branches))})"

    def span(route: str) -> list[dict]:
        """Stops that actually lie on this route.

        The first and last stop of the run are not safe to use directly: a service can
        begin at a station that is on another road entirely, and naming it as the entry
        point of this one produces a row the loader rejects outright
        ("GAYA not on SSM"). Clamping to the stops that are genuinely on the route is
        what makes the row describe a movement this network can hold.
        """
        return [s for s in stops if route in STATION_ROUTES[s["code"]]]

    def traverses(leg: list[dict]) -> bool:
        """Does this leg cross any of the route, or merely touch one point of it?

        Two things are being caught. A gateway may EXTEND a leg but may not BE one:
        Sasaram is the far end of the Ara-Sasaram branch and also a station on the Grand
        Chord, which this network does not model, so a Grand Chord train calling there
        has one modelled stop and a gateway just beyond it, both resolving to Sasaram.
        Accepting that put 99 trains on a branch they never touch.

        And the ends have to differ. A service that leaves the road and comes back to the
        same station -- 11033 does -- has two distinct codes and still describes no
        movement this model can hold; the loader rejects it outright, which takes the
        whole timetable down rather than one row.
        """
        return len({s["code"] for s in leg}) >= 2 and leg[0]["code"] != leg[-1]["code"]

    if not branches:                                  # main line throughout
        leg = span(MAIN)
        if not traverses(leg):
            return None, "fewer than two stops on the main line"
        return {
            "route": MAIN, "enter_at": leg[0]["code"], "leave_at": leg[-1]["code"],
            "main_leg": "", "enter_time": _leg_start(MAIN, leg, tclass),
        }, ""

    branch = branches.pop()
    jn = BRANCH_JUNCTION[branch]

    if MAIN not in certain:                           # branch only
        leg = span(branch)
        if not traverses(leg):
            return None, f"fewer than two stops on {branch}"
        return {
            "route": branch, "enter_at": leg[0]["code"], "leave_at": leg[-1]["code"],
            "main_leg": "", "enter_time": _leg_start(branch, leg, tclass),
        }, ""

    # Works through: branch, junction throat, main line. Split at the junction, using the
    # last stop that can only be on the branch and the last that can only be on the main.
    branch_stops = [s for s in stops if unambiguous_route(s["code"]) == branch]
    main_stops = [s for s in stops if unambiguous_route(s["code"]) == MAIN]
    if not branch_stops or not main_stops:
        return None, "through service with no identifiable leg"

    # Order comes from the stops that can only be on one road; the ENDS come from the
    # full span, junctions included. Taking both from the unambiguous set dropped the
    # main-line portion back to the first non-junction station, which for a train out of
    # Patna Jn threw away the Patna-Patna Sahib section it plainly occupies.
    main_span, branch_span = span(MAIN), span(branch)
    if not main_span or not branch_span:
        return None, "through service with no identifiable leg"

    if codes.index(branch_stops[0]["code"]) < codes.index(main_stops[0]["code"]):
        # Off the branch onto the main line.
        row = {
            "route": branch, "enter_at": branch_span[0]["code"], "leave_at": jn,
            "main_leg": main_span[-1]["code"],
            "enter_time": _leg_start(branch, branch_span, tclass),
        }
    else:
        # Off the main line onto the branch.
        row = {
            "route": branch, "enter_at": jn, "leave_at": branch_span[-1]["code"],
            "main_leg": main_span[0]["code"],
            "enter_time": _leg_start(MAIN, main_span, tclass),
        }

    # `traverses` is the wrong test on this shape: one end of the branch leg is the
    # junction, supplied by the topology rather than by a stop, so a branch end reached
    # only through a gateway is a single entry and still a real movement. What must hold
    # is that neither leg starts where it ends.
    if row["enter_at"] == row["leave_at"] or row["main_leg"] == jn:
        return None, "through service with no identifiable leg"
    return row, ""


def _leg_start(route: str, leg: list[dict], tclass: str) -> str:
    """Clock time at the first point of a leg.

    A booked stop carries its own time. A boundary the train runs through without
    stopping does not, so it is backed off from the first booked stop on the leg.
    """
    head = leg[0]
    if not head.get("gateway"):
        return head.get("time", "")
    anchor = next((s for s in leg[1:] if not s.get("gateway")), None)
    if anchor is None:
        return head.get("time", "")
    return _boundary_time(route, head["code"], anchor, tclass)
