"""The coaching timetable is read, not invented — so the reader has to be strict.

A traffic model built on a silently-dropped train prices a block hour too cheaply, and
nothing downstream would notice. These tests exist so that a malformed row stops the run
instead.
"""

from __future__ import annotations

import pytest

from samanvay.domain import Line, TrainClass
from samanvay.timetable_import import (
    BOUNDARIES,
    GATEWAYS,
    code_for_name,
    normalise_station,
    shared_route,
    to_service,
)
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
# Reading a published stop sequence
#
# Both of these were live defects, and both cost the division its premier traffic:
# the imported book held 543 services and not one Rajdhani or Duronto.
# --------------------------------------------------------------------------- #

def test_a_booking_quota_marker_is_not_part_of_the_station_name():
    # IRCTC's export writes "RL Patna Jn" for Remote Location and "PQ ..." for Pooled
    # Quota. 7,722 stop entries in IRCTC_cleaned.csv carry one, and none of them
    # resolved. 12273 Howrah-New Delhi Duronto touches this division at exactly one
    # station, and it is spelled "RL Patna Jn".
    assert code_for_name("RL Patna Jn") == code_for_name("Patna Jn") == "PNBE"
    assert code_for_name("RS Barh") == code_for_name("Barh")


def test_a_quota_marker_is_only_stripped_when_it_is_a_separate_word():
    # A name that merely starts with those letters keeps them.
    assert normalise_station("Rlxyz Junction") == "rlxyz"


def test_a_run_calling_only_at_junctions_resolves_to_the_road_they_share():
    # 12309/12310 Rajendra Nagar-New Delhi: Patna Jn and Danapur and nothing else on
    # this road. Both are junction throats, so no stop is unambiguous -- but Patna is
    # on the main line and the Gaya branch, Danapur on the main line and the Hajipur
    # branch, and only the main line carries both.
    row, why = to_service("12309", "RJPB TEJAS RAJ", "", "daily", [
        {"code": "PNBE", "time": "19:23"},
        {"code": "DNR", "time": "19:43"},
    ])
    assert row is not None, why
    assert row["route"] == MAIN
    assert (row["enter_at"], row["leave_at"]) == ("PNBE", "DNR")


def test_one_junction_stop_is_still_indeterminate():
    # Sharing a road takes two stops. One junction settles nothing, and guessing here
    # would put a train on a road it never touches.
    row, why = to_service("12273", "NDLS DURONTO", "", "daily", [
        {"code": "PNBE", "time": "16:03"},
    ])
    assert row is None
    assert "indeterminate" in why


def test_the_shared_road_is_never_guessed_to_be_a_branch():
    # Every branch meets the main line at exactly one junction, so two different
    # junctions can only be joined along the main line. shared_route says so rather
    # than picking whichever branch happens to sort first.
    assert shared_route(["PNBE", "DNR"]) == MAIN
    assert shared_route(["KIUL"]) is None


# --------------------------------------------------------------------------- #
# Gateways: where a service leaves the modelled network
#
# A leg ran from the first modelled STOP to the last, which equals the first to the last
# modelled KILOMETRE only for a train that happens to halt at the boundary. It does not
# for the premier traffic, which is exactly the traffic the fence exists for.
# --------------------------------------------------------------------------- #

def test_every_gateway_points_at_a_boundary():
    # A boundary is where the network STOPS -- the two ends of the main line and the far
    # end of each branch. A station leading into the MIDDLE of a road is not a gateway:
    # the train's own call there already says where it joined. Listing Chhapra, which
    # leads into Sonpur, made 11033 Pune-Darbhanga enter and leave at Hajipur.
    for name, boundaries in GATEWAYS.items():
        for b in boundaries:
            assert b in BOUNDARIES, f"{name} -> {b} is not a boundary"


def test_a_non_stop_run_to_the_boundary_is_not_clipped_at_the_last_halt():
    # 12309 halts at Patna and Danapur, then runs non-stop through Bihta, Ara, Dumraon
    # and Buxar to Mughalsarai. The leg used to end at Danapur, ten km in.
    row, why = to_service("12309", "RJPB TEJAS RAJ", "PREMIER", "daily",
        [{"code": "PNBE", "time": "19:30"}, {"code": "DNR", "time": "19:45"}],
        before=[{"name": "Rajendranagar T", "time": "19:10"}],
        after=[{"name": "Dd Upadhyaya Jn", "time": "22:10"}])
    assert row is not None, why
    assert (row["enter_at"], row["leave_at"]) == ("PNBE", "BXR")


def test_a_service_terminating_inside_the_division_is_not_dragged_to_the_boundary():
    # The mirror image, and the one a naive rule gets wrong. 12310 TERMINATES at Rajendra
    # Nagar Terminal, which is in Patna and is not modelled. "The destination is not a
    # modelled station, so the train must be leaving" would send it to Jhajha.
    row, why = to_service("12310", "RJPB TEJAS RAJ", "PREMIER", "daily",
        [{"code": "DNR", "time": "04:17"}, {"code": "PNBE", "time": "04:45"}],
        before=[{"name": "RL Dd Upadhyaya Jn", "time": "02:00"}],
        after=[{"name": "Rajendranagar T", "time": "05:15"}])
    assert row is not None, why
    assert (row["enter_at"], row["leave_at"]) == ("BXR", "PNBE")


def test_a_boundary_time_is_backed_off_from_the_first_booked_stop():
    # Not taken from the gateway's own clock. 12310 leaves Mughalsarai at 02:00 and is
    # 200 km short of Danapur there, which is nothing like the 116 km from Buxar; using
    # 02:00 would drag the whole path an hour early.
    row, _ = to_service("12310", "RJPB TEJAS RAJ", "PREMIER", "daily",
        [{"code": "DNR", "time": "04:17"}],
        before=[{"name": "RL Dd Upadhyaya Jn", "time": "02:00"}],
        after=[{"name": "Rajendranagar T", "time": "05:15"}])
    assert row is None or row["enter_time"] != "02:00"


def test_one_halt_plus_two_gateways_is_a_full_traversal():
    # 12305 Howrah-New Delhi Rajdhani halts once on this division, at Patna, and runs the
    # whole 281 km. One modelled stop used to be fatal.
    row, why = to_service("12305", "RAJDHANI EXPRESS", "PREMIER", "Su",
        [{"code": "PNBE", "time": "21:35"}],
        before=[{"name": "RL Jasidih Jn", "time": "17:33"}],
        after=[{"name": "RL Dd Upadhyaya Jn", "time": "00:50"}])
    assert row is not None, why
    assert (row["route"], row["enter_at"], row["leave_at"]) == (MAIN, "JAJ", "BXR")


def test_a_gateway_does_not_drag_a_train_onto_a_road_it_never_used():
    # 20887 Ranchi-Varanasi Vande Bharat runs the GRAND CHORD: Koderma, Gaya, Sasaram,
    # Mughalsarai. Mughalsarai is beyond Buxar AND beyond Sasaram, and reading it as
    # Buxar put this train up the Ara-Sasaram branch and out along our main line. It
    # touches two branch ends and no through road, so it belongs to neither.
    row, why = to_service("20887", "VANDE BHARAT EXP", "PREMIER", "daily",
        [{"code": "GAYA", "time": "09:55"}, {"code": "SSM", "time": "10:57"}],
        before=[{"name": "Koderma", "time": "08:42"}],
        after=[{"name": "Dd Upadhyaya Jn", "time": "12:15"}])
    assert row is None or row["route"] != MAIN, row


def test_a_leg_that_starts_where_it_ends_is_refused_at_import():
    # 11033 Pune-Darbhanga calls Chhapra, Sonpur, Hajipur, Muzaffarpur. Reading both
    # outer calls as the Hajipur boundary made the leg HJP -> HJP, which the loader
    # rejects by raising -- taking the whole timetable down rather than one row.
    row, why = to_service("11033", "DARBHANGA EXP", "MAIL_EXP", "daily",
        [{"code": "HJP", "time": "10:00"}],
        before=[{"name": "Muzaffarpur Jn", "time": "09:00"}],
        after=[{"name": "Muzaffarpur Jn", "time": "11:00"}])
    assert row is None, row


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
