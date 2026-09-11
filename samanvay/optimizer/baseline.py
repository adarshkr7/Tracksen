"""First-come-first-served baseline -- current practice, reproduced honestly.

Three departments raise demands into BDMS independently, in the order the work came
up, and each demand gets its own block. Nobody sees the other two queues, so nothing
is ever combined. Blocks land in the corridor when the corridor is free and wherever
else they fit when it is not.

The baseline obeys exactly the same *physical* constraints as the optimiser -- line
exclusivity, plant positioning, staff limits, night-work rules. Only the policy is
different. That is what makes the comparison fair: any gap between the two is
attributable to coordination and prioritisation, not to the baseline being handicapped.
"""

from __future__ import annotations

from ..domain import (
    MINUTES_PER_DAY,
    Department,
    Line,
    MachineType,
    MaintenanceTask,
    Plan,
    ScheduledBlock,
    overlaps,
)
from ..models.traffic import TrafficModel
from .cpsat import MACHINE_POSITIONING_MIN, Candidate, OptimiserWeights, _eligible


def schedule_fcfs(
    tasks: list[MaintenanceTask],
    candidates: list[Candidate],
    traffic: TrafficModel,
    horizon_days: int,
    weights: OptimiserWeights | None = None,
) -> Plan:
    w = weights or OptimiserWeights()

    # Arrival order. This is the whole policy: whoever asked first, gets first.
    queue = sorted(tasks, key=lambda t: (t.raised_day, t.id))

    # Candidates indexed by the line they sit on, earliest first, corridor preferred --
    # a department will take the mandated corridor if it is free.
    by_line: dict[tuple[str, Line], list[Candidate]] = {}
    for c in candidates:
        by_line.setdefault((c.section_id, c.line), []).append(c)
    for group in by_line.values():
        group.sort(key=lambda c: (c.start_min, not c.inside_corridor, c.capacity_min))

    occupied: dict[tuple[str, Line], list[tuple[int, int]]] = {}
    machine_busy: dict[MachineType, list[tuple[int, int]]] = {}
    dept_day_count: dict[tuple[Department, int], int] = {}

    blocks: list[ScheduledBlock] = []
    unscheduled: list[str] = []

    for task in queue:
        placed = False
        for c in by_line.get((task.section_id, task.line), ()):
            if not _eligible(task, c):
                continue

            used_min = task.p90_duration_min or task.demanded_duration_min
            start, end = c.start_min, c.start_min + used_min

            # Line exclusivity.
            key = (c.section_id, c.line)
            if any(overlaps(start, end, s, e) for s, e in occupied.get(key, ())):
                continue

            # Plant positioning, network-wide.
            if task.machine is not MachineType.NONE:
                m_end = end + MACHINE_POSITIONING_MIN
                if any(overlaps(start, m_end, s, e)
                       for s, e in machine_busy.get(task.machine, ())):
                    continue

            # Staff: a department can only mount so many blocks in a day.
            dkey = (task.department, c.day)
            if dept_day_count.get(dkey, 0) >= w.max_blocks_per_dept_per_day:
                continue

            occupied.setdefault(key, []).append((start, end))
            if task.machine is not MachineType.NONE:
                machine_busy.setdefault(task.machine, []).append(
                    (start, end + MACHINE_POSITIONING_MIN)
                )
            dept_day_count[dkey] = dept_day_count.get(dkey, 0) + 1

            cost = traffic.cost_of_block(c.section_id, c.line, start, end)
            blocks.append(
                ScheduledBlock(
                    id=f"F{c.id}-{task.id}",
                    section_id=c.section_id,
                    line=c.line,
                    day=c.day,
                    start_min=start,
                    end_min=end,
                    task_ids=[task.id],
                    departments=[task.department],
                    block_types=[task.block_type],
                    inside_corridor=c.inside_corridor,
                    traffic_cost=cost,
                    criticality_retired=round(task.criticality or 0.0, 2),
                    reasons=["first-come-first-served: one demand, one block"],
                )
            )
            placed = True
            break

        if not placed:
            unscheduled.append(task.id)

    return Plan(
        blocks=sorted(blocks, key=lambda b: (b.start_min, b.section_id)),
        unscheduled_task_ids=unscheduled,
        horizon_days=horizon_days,
        label="Baseline (FCFS, uncoordinated)",
    )
