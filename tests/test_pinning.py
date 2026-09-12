"""Pinned placements: honoured exactly, or refused by name.

The one behaviour that must never occur is a pin quietly disappearing. A planner who
drags a block, presses re-solve, and gets a plan that silently ignored them has been
told a lie about who is in control of the schedule.
"""

from __future__ import annotations

from samanvay.domain import MINUTES_PER_DAY, overlaps
from samanvay.session import Pin

SOLVE = 8.0


def _pin_capacity(session, block) -> int:
    """The window `_pin_candidates` would mint for this block."""
    tasks = [session.task_by_id[t] for t in block.task_ids]
    return max((t.p90_duration_min or t.demanded_duration_min) for t in tasks)


def _clear_start(session, block, *offsets: int) -> int:
    """The first offered shift this block can legally take.

    A fixed offset is not safe to assume any more: premier paths are fenced off, so
    "move it two hours" can land on a Rajdhani and be refused for a reason that has
    nothing to do with what the test is checking.
    """
    cap = _pin_capacity(session, block)
    for off in offsets:
        start = block.start_min + off
        if start < 0 or start + cap > session.horizon_days * MINUTES_PER_DAY:
            continue
        if session.traffic.fouls_premier(block.section_id, block.line, start, start + cap):
            continue
        return start
    raise AssertionError(f"no premier-free shift for block {block.id} among {offsets}")


# Shifts to try, in preference order: a couple of hours either way, then further out.
SHIFTS = (120, 60, 180, -60, -120, 240, 300, -180, 360, 420, -240, 480)


def _placement(plan, task_id: str) -> int | None:
    for b in plan.blocks:
        if task_id in b.task_ids:
            return b.start_min
    return None


def test_a_pin_is_honoured_exactly(session, plan, weights):
    source = plan.blocks[0]
    target_start = _clear_start(session, source, *SHIFTS)
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
        pins=[Pin(source.id, _clear_start(session, source, *SHIFTS), source.task_ids)],
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
        pins=[Pin(source.id, _clear_start(session, source, *SHIFTS), source.task_ids)],
        time_limit_s=SOLVE,
    )
    scheduled = {t for b in result.plan.blocks for t in b.task_ids}
    assert scheduled | set(result.plan.unscheduled_task_ids) == {
        t.id for t in session.tasks
    }


def test_pinning_is_reported_in_the_payload(session, plan, weights):
    source = plan.blocks[0]
    start = _clear_start(session, source, *SHIFTS)
    result = session.solve(
        weights=weights, pins=[Pin(source.id, start, source.task_ids)], time_limit_s=SOLVE
    )
    pinned = result.payload["meta"]["pinned"]
    assert pinned == [{"block_id": source.id, "start_min": start}]
    assert result.payload["meta"]["rejectedPins"] == []


def test_pinned_day_matches_the_requested_day(session, plan, weights):
    source = plan.blocks[0]
    day_shifts = tuple(MINUTES_PER_DAY + o for o in (0, 60, 120, -60, 180, -120, 240))
    try:
        start = _clear_start(session, source, *day_shifts)
    except AssertionError:
        return  # no clear window a day out in this fixture

    result = session.solve(
        weights=weights, pins=[Pin(source.id, start, source.task_ids)], time_limit_s=SOLVE
    )
    if result.rejected:
        return
    for b in result.plan.blocks:
        if set(b.task_ids) & set(source.task_ids):
            assert b.day == start // MINUTES_PER_DAY


def test_a_pin_cannot_be_dragged_across_a_premier_path(session):
    """The one rule the solver may not trade away has to hold for hand placements too.

    Pins never go through build_candidates, so the fence there does not cover them. A
    planner dragging a block on the what-if chart would otherwise walk straight past it.
    """
    from samanvay.domain import Line, TrainClass
    from samanvay.session import Pin

    # Find a premier path on a section that actually carries pending work.
    sections_with_work = {(t.section_id, t.line) for t in session.tasks}
    target = None
    for day in range(session.horizon_days):
        for (sid, line) in sections_with_work:
            base = day * 24 * 60
            hits = session.traffic.premier_in_window(sid, line, base, base + 24 * 60)
            if hits:
                target = (sid, line, hits[0])
                break
        if target:
            break
    assert target, "no premier path over any section with work -- fence untestable here"

    sid, line, path = target
    task = next(t for t in session.tasks if t.section_id == sid and t.line == line)

    # Start the block squarely on top of the train.
    pin = Pin("B-PREMIER", max(0, path.enter_min - 5), [task.id])
    extra, pin_cid, rejected = session._pin_candidates([pin])

    assert not extra, "a pin fouling a premier path was turned into a candidate"
    assert "B-PREMIER" not in pin_cid
    assert any(path.train_no in r for r in rejected), (
        f"the refusal should name the train it would detain; got {rejected}"
    )


def test_the_baseline_is_rebuilt_when_the_weights_change(session):
    """Cached once, it would be measured under limits the new plan never obeyed."""
    from samanvay.optimizer.cpsat import OptimiserWeights

    tight = session.baseline(OptimiserWeights(max_blocks_per_dept_per_day=2))
    loose = session.baseline(OptimiserWeights(max_blocks_per_dept_per_day=12))

    assert len(tight.blocks) != len(loose.blocks), (
        "the baseline ignored a change to the operational limits -- every percentage "
        "on the comparison screen would be measured off the wrong datum"
    )
