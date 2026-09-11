"""Domain primitives and generator sanity.

The generator tests exist because a calibration error hid here for several commits:
per-unit work rates were an order of magnitude too slow, so a single "task" came out as
a multi-shift campaign. Nothing crashed, nothing looked wrong, and every downstream
number was quietly distorted.
"""

from __future__ import annotations

import datetime as dt

import pytest

from samanvay.domain import (
    MINUTES_PER_DAY,
    AssetClass,
    BlockType,
    Department,
    Horizon,
    TrainClass,
    overlaps,
)
from samanvay.generator import DUE_INTERVAL_DAYS, WORK_CATALOGUE, cancellation_probability


# --------------------------------------------------------------------------- #
# Intervals
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("a,b,expected", [
    ((0, 10), (5, 15), True),
    ((0, 10), (10, 20), False),   # half-open: touching is not overlapping
    ((10, 20), (0, 10), False),
    ((0, 100), (10, 20), True),
    ((0, 10), (20, 30), False),
])
def test_overlap_is_half_open(a, b, expected):
    assert overlaps(a[0], a[1], b[0], b[1]) is expected


def test_horizon_round_trips():
    h = Horizon(dt.date(2026, 9, 14), days=7)
    assert h.total_minutes == 7 * MINUTES_PER_DAY
    assert h.day_of(MINUTES_PER_DAY + 30) == 1
    assert h.minute_of_day(MINUTES_PER_DAY + 90) == 90
    assert h.hhmm(MINUTES_PER_DAY + 9 * 60 + 5) == "09:05"


# --------------------------------------------------------------------------- #
# Departmental wiring
# --------------------------------------------------------------------------- #

def test_every_asset_class_belongs_to_one_department():
    for cls in AssetClass:
        assert isinstance(cls.department, Department)


def test_source_systems_map_correctly():
    assert Department.ENGINEERING.source_system == "TMS"
    assert Department.SIGNAL.source_system == "SMMS"
    assert Department.TRACTION.source_system == "TDMS"


def test_block_types_match_the_department_that_raises_them():
    """S&T takes disconnections, TRD takes power blocks. Mixing them is a domain error."""
    for spec in WORK_CATALOGUE:
        dept = spec.asset_class.department
        if dept is Department.SIGNAL:
            assert spec.block_type is BlockType.DISCONNECTION
        elif dept is Department.TRACTION:
            assert spec.block_type is BlockType.POWER
        else:
            assert spec.block_type is BlockType.TRAFFIC


def test_premier_traffic_costs_most_to_detain():
    weights = [c.detention_weight for c in TrainClass]
    assert TrainClass.PREMIER.detention_weight == max(weights)
    assert TrainClass.GOODS.detention_weight == min(weights)


def test_every_work_type_has_a_due_interval():
    for spec in WORK_CATALOGUE:
        assert spec.task_type in DUE_INTERVAL_DAYS


# --------------------------------------------------------------------------- #
# Generator calibration
# --------------------------------------------------------------------------- #

def test_task_durations_are_one_block_of_work(dataset):
    """A task is one block's work, not a campaign.

    Rates were once an order of magnitude too slow: median tamping P90 came out at
    1050 minutes -- seventeen hours, which is not a block, it is a fortnight's campaign.
    """
    durations = sorted(t.true_duration_min for t in dataset.pending)
    median = durations[len(durations) // 2]
    assert 45 <= median <= 300, f"median true duration is {median} min"
    assert max(durations) <= 12 * 60, (
        f"longest task is {max(durations)} min -- that is a campaign, not a block"
    )


def test_demanded_durations_are_round_figures(dataset):
    """Departments demand round numbers. Recovering the difference is the model's job."""
    for t in dataset.pending:
        assert t.demanded_duration_min % 30 == 0


def test_demands_are_systematically_optimistic(dataset):
    """The premise of the whole duration argument."""
    under = sum(1 for t in dataset.pending if t.demanded_duration_min < t.true_duration_min)
    assert under / len(dataset.pending) > 0.5, (
        "demands are not optimistic, so the P90 argument has no basis"
    )


def test_backlog_contains_genuinely_overdue_work(dataset):
    overdue = [t for t in dataset.pending if t.days_overdue() > 0]
    assert overdue, "no overdue work -- there is nothing to prioritise"


def test_all_three_departments_are_represented(dataset):
    depts = {t.department for t in dataset.pending}
    assert depts == set(Department)


def test_cancellation_probability_is_monotone():
    """Leaving the corridor, working at night and needing plant all raise the risk."""
    base = cancellation_probability(True, False, False, False)
    assert cancellation_probability(False, False, False, False) > base
    assert cancellation_probability(True, True, False, False) > base
    assert cancellation_probability(True, False, True, False) > base
    assert cancellation_probability(True, False, False, True) > base
    assert 0.0 <= cancellation_probability(False, True, True, True) <= 0.6


def test_history_is_large_enough_to_fit_on(dataset):
    assert len(dataset.history_defects) >= 500
    assert len(dataset.history_blocks) >= 300
