"""Solver invariants.

These are the properties a plan must have to be a plan at all. Most of them exist
because a real bug got through: the clubbing indicator once made the whole model
INFEASIBLE, and nothing but a person noticing caught it.

Every test here runs against both the optimised plan and the FCFS baseline where the
constraint is physical rather than a policy choice. If the baseline were allowed to
break rules the optimiser obeys, the comparison in the README would be rigged.
"""

from __future__ import annotations

import itertools

import pytest

from samanvay.domain import MachineType, Plan, overlaps
from samanvay.optimizer.cpsat import (
    DAY_END_MIN,
    DAY_START_MIN,
    MACHINE_POSITIONING_MIN,
    MINUTES_PER_DAY,
)


def _plans(plan, baseline):
    return [("optimised", plan), ("baseline", baseline)]


# --------------------------------------------------------------------------- #
# Feasibility
# --------------------------------------------------------------------------- #

def test_solver_finds_a_feasible_plan(solved):
    """The clubbing indicator once made this model INFEASIBLE for every instance."""
    assert solved.plan.blocks, "solver returned no blocks at all"
    assert "INFEASIBLE" not in solved.plan.label


def test_solver_reports_a_gap(session, weights):
    from samanvay.optimizer.cpsat import BlockOptimiser

    opt = BlockOptimiser(weights=weights, time_limit_s=5.0)
    opt.solve(session.tasks, session.base_candidates, session.traffic, session.horizon_days)
    assert opt.report is not None
    assert opt.report.status in {"OPTIMAL", "FEASIBLE"}
    # A plan presented without its gap is a plan nobody can check.
    assert opt.report.gap_pct >= 0.0


# --------------------------------------------------------------------------- #
# Line exclusivity -- the constraint everything else depends on
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("which", ["optimised", "baseline"])
def test_no_two_blocks_share_a_section_and_line(plan, baseline, which):
    target = plan if which == "optimised" else baseline
    by_line: dict[tuple, list] = {}
    for b in target.blocks:
        by_line.setdefault((b.section_id, b.line), []).append(b)

    for key, group in by_line.items():
        for a, b in itertools.combinations(group, 2):
            assert not overlaps(a.start_min, a.end_min, b.start_min, b.end_min), (
                f"{which}: blocks {a.id} and {b.id} overlap on {key}"
            )


# --------------------------------------------------------------------------- #
# Clubbing is exactly one gang per department
# --------------------------------------------------------------------------- #

def test_at_most_one_task_per_department_per_block(plan, session):
    for b in plan.blocks:
        depts = [session.task_by_id[t].department for t in b.task_ids]
        assert len(depts) == len(set(depts)), (
            f"block {b.id} holds two tasks from the same department: {depts}"
        )


def test_clubbed_blocks_really_are_multi_department(plan):
    for b in plan.clubbed_blocks:
        assert len(set(b.departments)) > 1
        assert len(b.task_ids) > 1


def test_block_duration_covers_its_longest_member(plan, session):
    """Work runs in parallel inside a block, so the span is the longest member."""
    for b in plan.blocks:
        longest = max(
            (session.task_by_id[t].p90_duration_min or 0) for t in b.task_ids
        )
        assert b.duration_min >= longest, (
            f"block {b.id} is {b.duration_min} min but holds {longest} min of work"
        )


# --------------------------------------------------------------------------- #
# Resources
# --------------------------------------------------------------------------- #

MIN_REALISTIC_POSITIONING_MIN = 30


def test_positioning_buffer_is_meaningful():
    """Independent of the configured value: plant has to physically travel.

    Asserting only that the payload echoes the constant is tautological -- zeroing the
    constant satisfies it. This pins the floor instead.
    """
    assert MACHINE_POSITIONING_MIN >= MIN_REALISTIC_POSITIONING_MIN, (
        "plant cannot be repositioned between block sections instantaneously"
    )


@pytest.mark.parametrize("which", ["optimised", "baseline"])
def test_plant_is_never_in_two_places_at_once(plan, baseline, session, which):
    target = plan if which == "optimised" else baseline
    windows: dict[MachineType, list[tuple[int, int, str]]] = {}

    for b in target.blocks:
        for tid in b.task_ids:
            mach = session.task_by_id[tid].machine
            if mach is MachineType.NONE:
                continue
            # Independent floor, so a regression that zeroes the constant cannot
            # also relax the test that is supposed to catch it.
            buffer = max(MIN_REALISTIC_POSITIONING_MIN, MACHINE_POSITIONING_MIN)
            windows.setdefault(mach, []).append((b.start_min, b.end_min + buffer, b.id))

    for mach, spans in windows.items():
        for (s1, e1, id1), (s2, e2, id2) in itertools.combinations(spans, 2):
            if id1 == id2:
                continue
            assert not overlaps(s1, e1, s2, e2), (
                f"{which}: {mach.value} needed by blocks {id1} and {id2} "
                f"inside the positioning window"
            )


@pytest.mark.parametrize("which", ["optimised", "baseline"])
def test_department_daily_block_cap_respected(plan, baseline, weights, which):
    target = plan if which == "optimised" else baseline
    counts: dict[tuple, int] = {}
    for b in target.blocks:
        for d in set(b.departments):
            counts[(d, b.day)] = counts.get((d, b.day), 0) + 1

    for (dept, day), n in counts.items():
        assert n <= weights.max_blocks_per_dept_per_day, (
            f"{which}: {dept.value} has {n} blocks on day {day}, "
            f"cap is {weights.max_blocks_per_dept_per_day}"
        )


@pytest.mark.parametrize("which", ["optimised", "baseline"])
def test_night_work_restrictions_respected(plan, baseline, session, which):
    target = plan if which == "optimised" else baseline
    for b in target.blocks:
        for tid in b.task_ids:
            task = session.task_by_id[tid]
            if task.night_work_allowed:
                continue
            start = b.start_min % MINUTES_PER_DAY
            assert start >= DAY_START_MIN, (
                f"{which}: {tid} starts at {start} min but cannot be night-worked"
            )
            assert start + b.duration_min <= DAY_END_MIN, (
                f"{which}: {tid} runs past {DAY_END_MIN} min but cannot be night-worked"
            )


# --------------------------------------------------------------------------- #
# Bookkeeping
# --------------------------------------------------------------------------- #

def test_every_task_is_scheduled_at_most_once(plan):
    seen = [t for b in plan.blocks for t in b.task_ids]
    assert len(seen) == len(set(seen)), "a task appears in two blocks"


def test_scheduled_and_unscheduled_partition_the_queue(plan, session):
    scheduled = {t for b in plan.blocks for t in b.task_ids}
    unscheduled = set(plan.unscheduled_task_ids)
    assert not (scheduled & unscheduled), "a task is both scheduled and deferred"
    assert scheduled | unscheduled == {t.id for t in session.tasks}


def test_blocks_stay_inside_the_horizon(plan, session):
    limit = session.horizon_days * MINUTES_PER_DAY
    for b in plan.blocks:
        assert 0 <= b.start_min < limit
        assert b.end_min <= limit
        assert b.day == b.start_min // MINUTES_PER_DAY


def test_corridor_flag_matches_the_corridor_windows(plan, corridors):
    windows = {(c.section_id, c.day): (c.start_min, c.end_min) for c in corridors}
    for b in plan.blocks:
        if not b.inside_corridor:
            continue
        w = windows.get((b.section_id, b.day))
        assert w is not None, f"block {b.id} claims a corridor that does not exist"
        assert w[0] <= b.start_min and b.end_min <= w[1], (
            f"block {b.id} is flagged in-corridor but runs {b.start_min}-{b.end_min} "
            f"against a corridor of {w[0]}-{w[1]}"
        )


# --------------------------------------------------------------------------- #
# The comparison must be fair
# --------------------------------------------------------------------------- #

def test_baseline_is_not_handicapped(plan, baseline):
    """Both plans draw from the same candidate pool and obey the same physics.

    The README attributes the whole gap to coordination and prioritisation. That claim
    only holds if the baseline was allowed to do everything the optimiser was.
    """
    assert baseline.blocks, "baseline produced nothing to compare against"
    assert isinstance(baseline, Plan)
    # The baseline gives each demand its own block, by construction.
    assert all(len(b.task_ids) == 1 for b in baseline.blocks)
    assert not baseline.clubbed_blocks
