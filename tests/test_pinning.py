"""Pinned placements: honoured exactly, or refused by name.

The one behaviour that must never occur is a pin quietly disappearing. A planner who
drags a block, presses re-solve, and gets a plan that silently ignored them has been
told a lie about who is in control of the schedule.
"""

from __future__ import annotations

from samanvay.domain import MINUTES_PER_DAY, overlaps
from samanvay.session import Pin

SOLVE = 8.0


def _placement(plan, task_id: str) -> int | None:
    for b in plan.blocks:
        if task_id in b.task_ids:
            return b.start_min
    return None


def test_a_pin_is_honoured_exactly(session, plan, weights):
    source = plan.blocks[0]
    target_start = source.start_min + 120
    pin = Pin(source.id, target_start, source.task_ids)

    result = session.solve(weights=weights, pins=[pin], time_limit_s=SOLVE)
    assert not result.rejected, f"pin was refused: {result.rejected}"

    for tid in source.task_ids:
        assert _placement(result.plan, tid) == target_start, (
            f"{tid} was not placed at the pinned start"
        )


def test_an_impossible_pin_is_refused_by_name(session, plan, weights):
    source = plan.blocks[0]
    pin = Pin(source.id, 99_999_999, source.task_ids)

    result = session.solve(weights=weights, pins=[pin], time_limit_s=SOLVE)
    assert result.rejected, "an out-of-horizon pin was accepted"
    assert source.id in result.rejected[0]
    assert "horizon" in result.rejected[0].lower()


def test_a_pin_for_unknown_tasks_is_refused(session, weights):
    result = session.solve(
        weights=weights, pins=[Pin("ghost", 600, ["NOPE-1"])], time_limit_s=SOLVE
    )
    assert result.rejected
    assert "ghost" in result.rejected[0]


def test_pinned_plans_still_obey_line_exclusivity(session, plan, weights):
    """Pinning must not be a way to smuggle an illegal plan past the solver."""
    import itertools

    source = plan.blocks[0]
    result = session.solve(
        weights=weights,
        pins=[Pin(source.id, source.start_min + 60, source.task_ids)],
        time_limit_s=SOLVE,
    )

    by_line: dict[tuple, list] = {}
    for b in result.plan.blocks:
        by_line.setdefault((b.section_id, b.line), []).append(b)
    for group in by_line.values():
        for a, c in itertools.combinations(group, 2):
            assert not overlaps(a.start_min, a.end_min, c.start_min, c.end_min)


def test_pinning_does_not_lose_tasks(session, plan, weights):
    source = plan.blocks[0]
    result = session.solve(
        weights=weights,
        pins=[Pin(source.id, source.start_min + 60, source.task_ids)],
        time_limit_s=SOLVE,
    )
    scheduled = {t for b in result.plan.blocks for t in b.task_ids}
    assert scheduled | set(result.plan.unscheduled_task_ids) == {
        t.id for t in session.tasks
    }


def test_pinning_is_reported_in_the_payload(session, plan, weights):
    source = plan.blocks[0]
    start = source.start_min + 60
    result = session.solve(
        weights=weights, pins=[Pin(source.id, start, source.task_ids)], time_limit_s=SOLVE
    )
    pinned = result.payload["meta"]["pinned"]
    assert pinned == [{"block_id": source.id, "start_min": start}]
    assert result.payload["meta"]["rejectedPins"] == []


def test_pinned_day_matches_the_requested_day(session, plan, weights):
    source = plan.blocks[0]
    start = source.start_min + MINUTES_PER_DAY
    if start + (source.end_min - source.start_min) > session.horizon_days * MINUTES_PER_DAY:
        return  # not enough horizon left in this fixture to move a day forward

    result = session.solve(
        weights=weights, pins=[Pin(source.id, start, source.task_ids)], time_limit_s=SOLVE
    )
    if result.rejected:
        return
    for b in result.plan.blocks:
        if set(b.task_ids) & set(source.task_ids):
            assert b.day == start // MINUTES_PER_DAY
