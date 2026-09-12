"""The coaching timetable is read, not invented — so the reader has to be strict.

A traffic model built on a silently-dropped train prices a block hour too cheaply, and
nothing downstream would notice. These tests exist so that a malformed row stops the run
instead.
"""

from __future__ import annotations

import pytest

from samanvay.domain import Line, TrainClass
from samanvay.network import (
    BOOKED_SERVICES,
    SHIPPED_TIMETABLE,
    BRANCH_JUNCTION,
    MAIN,
    ROUTE_BY_ID,
    TIMETABLE_FILE,
    generate_timetable,
    load_booked_services,
    run_service,
    sections_of,
    station_index,
)


def write_table(tmp_path, *rows: str):
    header = ("train_no,name,class,route,enter_at,leave_at,main_leg,enter_time,"
              "runs,provenance")
    path = tmp_path / "tt.csv"
    path.write_text("\n".join(["# comment", header, *rows]), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# The shipped file
# --------------------------------------------------------------------------- #

def test_shipped_timetable_loads():
    assert TIMETABLE_FILE.exists()
    assert len(BOOKED_SERVICES) > 40


def test_every_service_declares_its_provenance():
    """The UI shows this. A blank or invented value would be a claim we cannot back."""
    for s in BOOKED_SERVICES:
        from samanvay.serialize import PROVENANCE_INDEX

        # Derived, not listed: a new importer adding a provenance must register it in one
        # place, and this test then accepts it without being edited into agreement.
        assert s.provenance in PROVENANCE_INDEX, (
            f"{s.train_no} carries unregistered provenance {s.provenance!r}"
        )
        assert s.provenance != "forecast", "coaching traffic is booked, not forecast"


def test_train_numbers_are_unique():
    numbers = [s.train_no for s in BOOKED_SERVICES]
    assert len(numbers) == len(set(numbers))


def test_no_goods_in_the_book():
    """Goods paths are not booked. If one appears here it is being faked as booked."""
    for s in BOOKED_SERVICES:
        assert s.train_class is not TrainClass.GOODS, s.train_no


def test_the_shipped_book_carries_traffic_on_every_route():
    """A modelled route with no traffic prices as free, and its junction as uncontended.

    Asserted against the SHIPPED file specifically, because that one is ours to author.
    An NTES import is a reading of the real railway and may legitimately have gaps -- the
    weaker invariant that must hold whatever is loaded is the next test.
    """
    shipped = load_booked_services(SHIPPED_TIMETABLE)
    assert {s.route_id for s in shipped} == set(ROUTE_BY_ID)


def test_whatever_is_loaded_carries_main_line_traffic():
    """The planned road must never price as empty, whichever timetable is in force."""
    worked = {s.route_id for s in BOOKED_SERVICES}
    assert MAIN in worked, "no coaching traffic on the main line -- every block is free"


# --------------------------------------------------------------------------- #
# Running a service over the topology
# --------------------------------------------------------------------------- #

def test_a_service_occupies_contiguous_sections():
    svc = next(s for s in BOOKED_SERVICES if s.route_id == MAIN)
    paths = run_service(svc, day=0)
    assert paths
    for a, b in zip(paths, paths[1:]):
        assert b.enter_min >= a.exit_min, "a train is in two places at once"


def test_a_through_service_occupies_branch_and_main():
    """The point of the junction throat: one movement takes both legs."""
    svc = next(s for s in BOOKED_SERVICES if s.main_leg is not None)
    branch = {s.id for s in sections_of(svc.route_id)}
    main = {s.id for s in sections_of(MAIN)}

    hit = {p.section_id for p in run_service(svc, day=0)}
    assert hit & branch, f"{svc.train_no} never runs its own branch"
    assert hit & main, f"{svc.train_no} never reaches the main line"


def test_through_service_reaches_its_declared_main_leg():
    for svc in BOOKED_SERVICES:
        if svc.main_leg is None:
            continue
        jn = BRANCH_JUNCTION[svc.route_id]
        lo, hi = sorted((station_index(jn, MAIN), station_index(svc.main_leg, MAIN)))
        expected = {s.id for s in sections_of(MAIN)[lo:hi]}
        hit = {p.section_id for p in run_service(svc, day=0)}
        assert expected <= hit, f"{svc.train_no} stops short of {svc.main_leg}"


def test_single_line_branches_are_worked_as_one_road():
    """A block on a single line stops traffic both ways. Both directions book UP."""
    for svc in BOOKED_SERVICES:
        route = ROUTE_BY_ID[svc.route_id]
        if route.double:
            continue
        for p in run_service(svc, day=0):
            if p.section_id in {s.id for s in sections_of(svc.route_id)}:
                assert p.line is Line.UP, f"{svc.train_no} booked DN on a single line"


def test_services_repeat_daily_at_the_same_clock_time():
    svc = BOOKED_SERVICES[0]
    d0 = run_service(svc, day=0)
    d2 = run_service(svc, day=2)
    assert len(d0) == len(d2)
    for a, b in zip(d0, d2):
        assert b.enter_min - a.enter_min == 2 * 24 * 60


def test_coaching_paths_are_certain_and_goods_are_not():
    paths = generate_timetable(1)
    coaching = [p for p in paths if p.train_class is not TrainClass.GOODS]
    goods = [p for p in paths if p.train_class is TrainClass.GOODS]

    assert coaching and goods
    assert all(p.probability == 1.0 for p in coaching), "a booked path was discounted"
    assert all(p.probability < 1.0 for p in goods), "a forecast path was made certain"
    assert all(p.train_name for p in coaching), "a booked path lost its service name"


# --------------------------------------------------------------------------- #
# Malformed rows must stop the run
# --------------------------------------------------------------------------- #

def test_unknown_route_is_rejected(tmp_path):
    p = write_table(tmp_path, "12345,Test,MAIL_EXP,NOPE,BXR,JAJ,,06:00,daily,named")
    with pytest.raises(ValueError, match="unknown route"):
        load_booked_services(p)


def test_station_not_on_the_route_is_rejected(tmp_path):
    # Sasaram is real, but it is not on the main line.
    p = write_table(tmp_path, "12345,Test,MAIL_EXP,MAIN,BXR,SSM,,06:00,daily,named")
    with pytest.raises(KeyError):
        load_booked_services(p)


def test_main_leg_without_a_junction_end_is_rejected(tmp_path):
    p = write_table(tmp_path, "12345,Test,MAIL_EXP,GAYA,SHK,NWD,PNBE,06:00,daily,named")
    with pytest.raises(ValueError, match="neither end is the junction"):
        load_booked_services(p)


def test_main_leg_on_a_main_line_service_is_rejected(tmp_path):
    p = write_table(tmp_path, "12345,Test,MAIL_EXP,MAIN,BXR,JAJ,PNBE,06:00,daily,named")
    with pytest.raises(ValueError, match="branch services only"):
        load_booked_services(p)


def test_a_service_that_goes_nowhere_is_rejected(tmp_path):
    p = write_table(tmp_path, "12345,Test,MAIL_EXP,MAIN,PNBE,PNBE,,06:00,daily,named")
    with pytest.raises(ValueError, match="starts where it ends"):
        load_booked_services(p)


def test_a_missing_file_is_reported_not_silently_empty(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_booked_services(tmp_path / "absent.csv")


# --------------------------------------------------------------------------- #
# Premier priority
# --------------------------------------------------------------------------- #

def test_premier_outranks_everything_else_by_a_wide_margin():
    """Detaining a Rajdhani is a different kind of event, not a worse one."""
    from samanvay.domain import TrainClass

    premier = TrainClass.PREMIER.detention_weight
    nxt = TrainClass.MAIL_EXP.detention_weight
    assert premier >= 4 * nxt, (
        f"premier weight {premier} is only {premier / nxt:.1f}x mail/express -- close "
        "enough that the solver can buy a premier detention with savings elsewhere"
    )


def test_the_book_carries_premier_traffic():
    """Protected paths must exist, or the premier fence is never exercised."""
    premier = [s for s in BOOKED_SERVICES if s.train_class is TrainClass.PREMIER]
    assert premier, "no protected paths in the timetable -- the fence would be untested"


def test_the_shipped_book_names_the_premier_services_it_claims():
    """The shipped file is authored, so its premier traffic is ours to get right.

    Matched case-insensitively: an NTES import spells them "VANDE BHARAT EXP", and a
    test that only accepted title case would fail on real data while passing on ours --
    exactly backwards.
    """
    shipped = load_booked_services(SHIPPED_TIMETABLE)
    names = " ".join(s.name.lower() for s in shipped
                     if s.train_class is TrainClass.PREMIER)
    assert "vande bharat" in names
    assert "rajdhani" in names


def test_no_candidate_window_fouls_a_premier_path(candidates, traffic):
    """The fence is in candidate generation, so the solver never sees the option."""
    for c in candidates:
        assert not traffic.fouls_premier(
            c.section_id, c.line, c.start_min, c.start_min + c.capacity_min
        ), f"candidate {c.id} on {c.section_id} stands in front of a premier path"


def test_no_planned_block_fouls_a_premier_path(plan, traffic):
    for b in plan.blocks:
        assert not traffic.fouls_premier(
            b.section_id, b.line, b.start_min, b.end_min
        ), f"block {b.id} on {b.section_id} would detain premier traffic"


def test_a_valid_row_round_trips(tmp_path):
    """Guards the helper above: if it drifts from the real header, the rejection
    tests below start passing for the wrong reason."""
    p = write_table(tmp_path, "12345,Test,MAIL_EXP,MAIN,BXR,JAJ,,06:00,MoWeFr,named")
    svc = load_booked_services(p)[0]
    assert svc.train_no == "12345"
    assert svc.runs == frozenset({0, 2, 4})
    assert svc.runs_on(0) and not svc.runs_on(1) and svc.runs_on(2)


def test_an_unreadable_running_day_is_rejected(tmp_path):
    p = write_table(tmp_path, "12345,Test,MAIL_EXP,MAIN,BXR,JAJ,,06:00,MoXx,named")
    with pytest.raises(ValueError, match="unknown day code"):
        load_booked_services(p)


def test_a_service_running_no_days_is_rejected(tmp_path):
    p = write_table(tmp_path, "12345,Test,MAIL_EXP,MAIN,BXR,JAJ,,06:00,,named")
    with pytest.raises(ValueError, match="running days"):
        load_booked_services(p)


def test_imported_timetable_wins_when_present(monkeypatch, tmp_path):
    """Running the crawl is meant to be the only step. If resolution preferred the
    shipped file, an import would sit on disk doing nothing and the UI would keep
    calling published times approximate."""
    from samanvay import network

    shipped = tmp_path / "shipped.csv"
    imported = tmp_path / "imported.csv"
    shipped.write_text("x", encoding="utf-8")

    monkeypatch.setattr(network, "SHIPPED_TIMETABLE", shipped)
    monkeypatch.setattr(network, "IMPORTED_TIMETABLE", imported)
    assert network.resolve_timetable() == shipped

    imported.write_text("x", encoding="utf-8")
    assert network.resolve_timetable() == imported
