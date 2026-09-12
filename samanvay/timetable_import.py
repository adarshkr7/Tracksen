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

from .network import BRANCH_JUNCTION, MAIN, ROUTES

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


def to_service(number: str, name: str, tclass: str, runs: str,
               stops: list[dict]) -> tuple[dict | None, str]:
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

    if not branches:                                  # main line throughout
        leg = span(MAIN)
        if len(leg) < 2:
            return None, "fewer than two stops on the main line"
        return {
            "route": MAIN, "enter_at": leg[0]["code"], "leave_at": leg[-1]["code"],
            "main_leg": "", "enter_time": leg[0]["time"],
        }, ""

    branch = branches.pop()
    jn = BRANCH_JUNCTION[branch]

    if MAIN not in certain:                           # branch only
        leg = span(branch)
        if len(leg) < 2:
            return None, f"fewer than two stops on {branch}"
        return {
            "route": branch, "enter_at": leg[0]["code"], "leave_at": leg[-1]["code"],
            "main_leg": "", "enter_time": leg[0]["time"],
        }, ""

    # Works through: branch, junction throat, main line. Split at the junction, using the
    # last stop that can only be on the branch and the last that can only be on the main.
    branch_stops = [s for s in stops if unambiguous_route(s["code"]) == branch]
    main_stops = [s for s in stops if unambiguous_route(s["code"]) == MAIN]
    if not branch_stops or not main_stops:
        return None, "through service with no identifiable leg"

    if codes.index(branch_stops[0]["code"]) < codes.index(main_stops[0]["code"]):
        # Off the branch onto the main line.
        return {
            "route": branch, "enter_at": branch_stops[0]["code"], "leave_at": jn,
            "main_leg": main_stops[-1]["code"], "enter_time": branch_stops[0]["time"],
        }, ""
    # Off the main line onto the branch.
    return {
        "route": branch, "enter_at": jn, "leave_at": branch_stops[-1]["code"],
        "main_leg": main_stops[0]["code"], "enter_time": main_stops[0]["time"],
    }, ""
