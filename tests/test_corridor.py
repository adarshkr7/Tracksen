"""The corridor regime, against what the circular actually says.

Railway Board's joint circular of 28.12.2016 carries two different numbers and they are
easy to conflate: para 2.0 sets the norm the working time table is built around (one
block of four hours, or two of two and a half), para 3.0 sets a three-hour floor for the
joint monthly programme. This project used to hard-code the floor, which made every
"cannot fit a corridor" figure downstream an artefact of the weaker rule.

The tests that matter here are the ones that do not throw: a two-spell regime whose
spells silently overlap, or a `needs_extended_block` that adds two spells together, both
produce a plausible-looking plan that no division could work.
"""

from __future__ import annotations

import pytest

from samanvay.domain import MINUTES_PER_DAY
from samanvay.network import (
    CORRIDOR_REGIMES,
    DEFAULT_CORRIDOR_REGIME,
    audit_corridors,
    corridor_lookup,
    generate_corridors,
    generate_timetable,
    lines_for_section,
    planned_sections,
    resolve_regime,
)
from samanvay.optimizer.cpsat import DAY_END_MIN, DAY_START_MIN, build_candidates

DAYS = 3


def test_the_default_is_the_norm_not_the_floor():
    """240 minutes is para 2.0. 180 is the minimum a section may not fall below."""
    assert resolve_regime(None).name == DEFAULT_CORRIDOR_REGIME
    assert resolve_regime(None).longest_spell_min == 240
    assert CORRIDOR_REGIMES["min-180"].longest_spell_min == 180


def test_both_limbs_of_para_2_are_offered():
    assert CORRIDOR_REGIMES["single-240"].spells == ((0, 240),)
    lengths = [m for _, m in CORRIDOR_REGIMES["split-150x2"].spells]
    assert lengths == [150, 150]


def test_an_unknown_regime_is_refused_by_name():
    with pytest.raises(ValueError) as exc:
        resolve_regime("four-hours-ish")
    assert "four-hours-ish" in str(exc.value)
    assert "single-240" in str(exc.value)


@pytest.mark.parametrize("name", sorted(CORRIDOR_REGIMES))
def test_every_regime_places_spells_inside_the_day_work_window(name):
    """A corridor outside 06:00-18:00 excludes night-restricted work from the corridor.

    That would be a self-inflicted wound: the section has its mandated possession and
    half the queue still cannot be placed in it, for a reason that never surfaces.
    """
    for c in generate_corridors(DAYS, name):
        start = c.start_min % MINUTES_PER_DAY
        end = start + (c.end_min - c.start_min)
        assert DAY_START_MIN <= start, f"{name}: corridor starts before the working day"
        assert end <= DAY_END_MIN, f"{name}: corridor runs past the working day"


@pytest.mark.parametrize("name", sorted(CORRIDOR_REGIMES))
def test_spells_on_a_section_day_never_overlap(name):
    """Two corridors are two possessions. Overlapping them would double-count capacity."""
    for windows in corridor_lookup(generate_corridors(DAYS, name)).values():
        for earlier, later in zip(windows, windows[1:]):
            assert earlier.end_min <= later.start_min, name


def test_the_split_limb_yields_two_windows_per_section_day():
    single = corridor_lookup(generate_corridors(DAYS, "single-240"))
    split = corridor_lookup(generate_corridors(DAYS, "split-150x2"))

    assert single.keys() == split.keys()
    assert all(len(w) == 1 for w in single.values())
    assert all(len(w) == 2 for w in split.values())
    assert len(split) == DAYS * len(planned_sections())


def test_the_corridors_own_length_is_always_a_capacity_option(traffic):
    """Otherwise a 150-minute corridor can only be granted for 120.

    Thirty minutes of a mandated possession would go unused on every section every day,
    and nothing in the output would say why.
    """
    section_ids = [s.id for s in planned_sections()]
    corridors = generate_corridors(DAYS, "split-150x2")
    cands = build_candidates(section_ids, DAYS, traffic, corridors)

    inside = [c for c in cands if c.inside_corridor]
    assert inside, "no corridor placements were enumerated at all"
    assert any(c.capacity_min == 150 for c in inside)


@pytest.mark.parametrize("name", sorted(CORRIDOR_REGIMES))
def test_no_corridor_placement_outruns_its_own_window(traffic, name):
    section_ids = [s.id for s in planned_sections()]
    corridors = generate_corridors(DAYS, name)
    windows = corridor_lookup(corridors)
    cands = build_candidates(section_ids, DAYS, traffic, corridors)

    for c in cands:
        if not c.inside_corridor:
            continue
        holding = [
            w for w in windows.get((c.section_id, c.day), [])
            if w.start_min == c.start_min
        ]
        assert holding, f"{name}: corridor placement with no matching window"
        assert c.start_min + c.capacity_min <= holding[0].end_min


def test_placing_against_traffic_beats_the_fixed_stagger(traffic):
    """A corridor goes where the road is quietest, which is Sr.DOM's actual job.

    The Rolling Block Programme puts it in one sentence: Sr.DOM indicates the corridor
    "taking into consideration the integrated maintenance corridor block provided in the
    working timetable, historical data and operational patterns".
    """
    staggered = generate_corridors(DAYS, "single-240")
    placed = generate_corridors(DAYS, "single-240", traffic)
    assert len(staggered) == len(placed)

    def total(windows):
        return sum(
            traffic.cost_of_block(c.section_id, line, c.start_min, c.end_min)
            for c in windows
            for line in lines_for_section(c.section_id)
        )

    assert total(placed) < total(staggered)


def test_a_placed_corridor_avoids_protected_paths(traffic):
    """A section is not handed over in a window a Rajdhani is due to run.

    Fouling premier traffic makes the corridor unusable rather than expensive, so the
    placement treats it as a fence. Some section-day may genuinely have no clean window;
    what must not happen is fouling one that could have been avoided for free.
    """
    placed = generate_corridors(DAYS, "single-240", traffic)
    fouls = [
        c for c in placed
        for line in lines_for_section(c.section_id)
        if traffic.fouls_premier(c.section_id, line, c.start_min, c.end_min)
    ]
    staggered_fouls = [
        c for c in generate_corridors(DAYS, "single-240")
        for line in lines_for_section(c.section_id)
        if traffic.fouls_premier(c.section_id, line, c.start_min, c.end_min)
    ]
    assert len(fouls) <= len(staggered_fouls)


def test_the_audit_reports_what_the_chart_runs_through_the_corridor(traffic):
    """The CAG's second finding, checked against this division's own timetable.

    On a road carrying 543 services there may be no clean four-hour window anywhere, and
    that is the point: para 2.0 then requires trains to be rescheduled to create one. The
    audit has to say so rather than let a block be marked "inside mandated corridor" as
    though the window had been cleared.
    """
    corridors = generate_corridors(DAYS, "single-240", traffic)
    paths = generate_timetable(DAYS)
    findings = audit_corridors(paths, corridors)

    for f in findings:
        assert f.booked > 0 or f.forecast >= 1.0
        assert f.premier <= f.booked
        assert len(f.examples) <= min(4, f.booked)
        assert f.end_min > f.start_min


def test_two_spells_are_not_one_long_one():
    """The split limb gives more corridor minutes per day and a SHORTER longest spell.

    This is the trade the circular leaves to the division, and it has to survive into
    the model: five hours in two halves will not hold a job that needs four.
    """
    split = CORRIDOR_REGIMES["split-150x2"]
    single = CORRIDOR_REGIMES["single-240"]

    assert split.daily_minutes > single.daily_minutes
    assert split.longest_spell_min < single.longest_spell_min
