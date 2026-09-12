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


def test_reported_blocks_match_the_possessions_the_solver_reserved(plan, candidates):
    """The published plan and the CP-SAT objective must describe the same window."""
    by_id = {str(c.id): c for c in candidates}
    for b in plan.blocks:
        candidate = by_id[b.id]
        assert b.start_min == candidate.start_min
        assert b.end_min == candidate.end_min
        assert b.traffic_cost == candidate.traffic_cost


def test_monthly_candidates_respect_the_premier_path_fence():
    """A faulty master corridor must not bypass the weekly candidate safety rule."""
    from samanvay.domain import CorridorWindow, TrainClass, TrainPath
    from samanvay.models.traffic import TrafficModel
    from samanvay.network import SECTIONS, lines_for_section
    from samanvay.optimizer.cpsat import build_monthly_candidates

    section = SECTIONS[0]
    line = lines_for_section(section.id)[0]
    corridor = CorridorWindow(section.id, 0, 600, 720)
    traffic = TrafficModel([
        TrainPath("P-1", TrainClass.PREMIER, section.id, line, 0, 630, 660),
    ], horizon_days=1)

    candidates, unavailable = build_monthly_candidates(
        [section.id], 1, traffic, [corridor]
    )

    assert not [c for c in candidates if c.line is line]
    assert any("fouls premier" in message for message in unavailable)


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


# --------------------------------------------------------------------------- #
# What a withdrawal costs inside the possession
# --------------------------------------------------------------------------- #

def test_clubbing_pays_the_longest_withdrawal_not_the_sum():
    """One isolation covers every gang under it. Summing would delete the reason to club."""
    from samanvay.domain import BlockType
    from samanvay.optimizer.cpsat import RESTORE_MIN, SETUP_MIN, withdrawal_overhead

    both = withdrawal_overhead([BlockType.DISCONNECTION, BlockType.POWER])
    apart = (withdrawal_overhead([BlockType.DISCONNECTION])
             + withdrawal_overhead([BlockType.POWER]))

    assert both < apart, "clubbed withdrawals were added up rather than overlapped"
    assert both == (max(SETUP_MIN[BlockType.DISCONNECTION], SETUP_MIN[BlockType.POWER])
                    + max(RESTORE_MIN[BlockType.DISCONNECTION],
                          RESTORE_MIN[BlockType.POWER]))


def test_a_plain_traffic_block_loses_nothing_to_setup():
    from samanvay.domain import BlockType
    from samanvay.optimizer.cpsat import withdrawal_overhead

    assert withdrawal_overhead([BlockType.TRAFFIC]) == 0


def test_every_block_leaves_room_for_its_own_withdrawal(plan, session):
    """The promise a block makes to the gang: this much time, actually workable.

    Before withdrawal overheads were modelled a block could be granted exactly the P90
    of its longest job, leaving nothing for isolation or disconnection -- so the plan
    promised working time the possession did not contain, and the overrun appeared on
    the ground rather than on the chart.
    """
    from samanvay.optimizer.cpsat import withdrawal_overhead

    for b in plan.blocks:
        tasks = [session.task_by_id[t] for t in b.task_ids]
        longest = max((t.p90_duration_min or t.demanded_duration_min) for t in tasks)
        overhead = withdrawal_overhead({t.block_type for t in tasks})
        possession = b.end_min - b.start_min
        assert longest + overhead <= possession, (
            f"block {b.id} on {b.section_id}: {possession} min possession cannot hold "
            f"{longest} min of work plus {overhead} min of withdrawal"
        )


def test_ohe_work_pays_for_isolation_whatever_it_was_filed_as():
    """A P.Way gang under live contact wire is not made safe by the demand's wording.

    `requires_power_block` folds in the asset class, so a task on an OHE mast needs the
    traction current off even when its department raised it as a plain traffic block.
    These two properties sat unreferenced for most of the project's life — a safety rule
    that looked implemented and was not.
    """
    from samanvay.domain import AssetClass, BlockType, Department, Line, MachineType, MaintenanceTask
    from samanvay.optimizer.cpsat import withdrawal_overhead, withdrawals_for

    def task(asset_class, block_type):
        return MaintenanceTask(
            id="T1", department=Department.ENGINEERING, task_type="x",
            block_type=block_type, asset_id="A1", asset_class=asset_class,
            section_id="BXR-DURE", line=Line.UP, chainage_km=1.0,
            defect_severity=3, due_day=3, demanded_duration_min=60,
            machine=MachineType.NONE, source_system="TMS", is_defect=True,
            raised_day=0, gang_size=6, quantity=100.0, night_work_allowed=True,
        )

    plain = task(AssetClass.RAIL, BlockType.TRAFFIC)
    ohe = task(AssetClass.OHE_MAST, BlockType.TRAFFIC)

    assert withdrawals_for(plain) == {BlockType.TRAFFIC}
    assert BlockType.POWER in withdrawals_for(ohe), (
        "an OHE-mast job filed as a traffic block would be worked under live wire"
    )
    assert withdrawal_overhead(withdrawals_for(ohe)) > 0
    assert withdrawal_overhead(withdrawals_for(plain)) == 0
