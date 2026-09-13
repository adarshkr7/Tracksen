"""Block bursting, measured on a plan.

A block that is worked beyond its sanctioned time has *burst*. It is not a modelling
abstraction: the CAG counted 1,905 cases across six divisions on the Delhi-Howrah route
in 2018-19, delaying 4,659 trains, and "block bursting" is a named cause of punctuality
loss in ICMS. The reason a scheduler cares is that a burst block detains trains that were
promised a clear road at a specific minute, so the cost lands on traffic and not on the
department that over-ran.

The arithmetic that matters here is that the possession has to hold the *withdrawal* as
well as the work. A disconnection that takes 20 minutes to make and 15 to restore leaves
35 fewer minutes for the job, and a burst check that forgets this reports a block as
comfortable when the gang will still be on the track when the block expires.
"""

from __future__ import annotations

from samanvay.domain import (
    AssetClass,
    BlockType,
    Department,
    Line,
    MachineType,
    MaintenanceTask,
    Plan,
    ScheduledBlock,
)
from samanvay.evaluate import evaluate
from samanvay.optimizer.cpsat import withdrawal_overhead


def _task(tid: str, true_min: int, block_type: BlockType) -> MaintenanceTask:
    return MaintenanceTask(
        id=tid,
        source_system="TMS",
        department=Department.ENGINEERING,
        asset_id="A1",
        asset_class=AssetClass.RAIL,
        section_id="PNBE-DNR",
        line=Line.UP,
        chainage_km=10.0,
        task_type="through packing",
        block_type=block_type,
        defect_severity=3,
        is_defect=True,
        raised_day=0,
        due_day=3,
        demanded_duration_min=120,
        gang_size=8,
        machine=MachineType.NONE,
        quantity=100.0,
        night_work_allowed=True,
        true_duration_min=true_min,
    )


def _plan(block_minutes: int, tasks: list[MaintenanceTask]) -> Plan:
    block = ScheduledBlock(
        id="1",
        section_id="PNBE-DNR",
        line=Line.UP,
        day=0,
        start_min=600,
        end_min=600 + block_minutes,
        task_ids=[t.id for t in tasks],
        departments=[t.department for t in tasks],
        block_types=[t.block_type for t in tasks],
        inside_corridor=True,
        traffic_cost=0.0,
        criticality_retired=10.0,
    )
    return Plan(blocks=[block], unscheduled_task_ids=[], horizon_days=1, label="test")


def test_a_block_that_fits_does_not_burst():
    tasks = [_task("T1", true_min=60, block_type=BlockType.TRAFFIC)]
    overhead = withdrawal_overhead({BlockType.TRAFFIC})
    m = evaluate(_plan(60 + overhead + 15, tasks), tasks)

    assert m.blocks_written_to_burst == 0
    assert m.burst_minutes == 0
    assert m.burst_rate == 0.0


def test_a_block_that_over_runs_is_counted_with_its_minutes():
    tasks = [_task("T1", true_min=200, block_type=BlockType.TRAFFIC)]
    overhead = withdrawal_overhead({BlockType.TRAFFIC})
    m = evaluate(_plan(180, tasks), tasks)

    assert m.blocks_written_to_burst == 1
    assert m.burst_rate == 1.0
    assert m.burst_minutes == 200 + overhead - 180


def test_the_withdrawal_counts_against_the_window():
    """The failure that does not throw.

    Work of 170 minutes in a 180-minute possession looks comfortable and is not: making
    and restoring the disconnection is part of the block. Measuring the work alone would
    report a clean plan that bursts on the ground.
    """
    tasks = [_task("T1", true_min=170, block_type=BlockType.DISCONNECTION)]
    overhead = withdrawal_overhead({BlockType.DISCONNECTION})
    assert overhead > 0, "a disconnection is not free to make and restore"

    m = evaluate(_plan(180, tasks), tasks)
    assert m.blocks_written_to_burst == 1
    assert m.burst_minutes == 170 + overhead - 180


def test_departments_in_a_clubbed_block_work_in_parallel():
    """Two gangs in one possession finish when the LONGER one finishes, not the sum.

    Adding them would report bursting on every clubbed block -- which would make the
    coordination this project exists to find look like a safety problem.
    """
    tasks = [
        _task("T1", true_min=90, block_type=BlockType.TRAFFIC),
        _task("T2", true_min=80, block_type=BlockType.TRAFFIC),
    ]
    tasks[1].department = Department.SIGNAL
    overhead = withdrawal_overhead({BlockType.TRAFFIC})

    m = evaluate(_plan(90 + overhead, tasks), tasks)
    assert m.blocks_written_to_burst == 0


def test_burst_rate_agrees_with_the_count_on_a_real_plan(plan, session):
    m = evaluate(plan, session.tasks)
    if m.blocks_used:
        assert m.burst_rate == round(m.blocks_written_to_burst / m.blocks_used, 4)
    assert (m.burst_minutes > 0) == (m.blocks_written_to_burst > 0)
