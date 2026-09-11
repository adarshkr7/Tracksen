"""Plan evaluation.

Every measure here is computed identically for the optimised plan and the
first-come-first-served baseline. Reported figures are the difference between two runs
of the same simulator on the same task population -- not a claim about Indian Railways.

Two of these use simulator ground truth (`true_days_to_failure`, `true_duration_min`).
That is legitimate *here* because it is evaluation, not a feature: no model and no
solver ever saw either quantity. It is what lets us ask the question that actually
matters -- did the plan get there before the asset failed?
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .domain import MaintenanceTask, Plan


@dataclass
class PlanMetrics:
    label: str

    # Headline
    risk_retired_per_block_hour: float = 0.0

    # Throughput
    tasks_scheduled: int = 0
    tasks_unscheduled: int = 0
    blocks_used: int = 0
    block_hours: float = 0.0
    criticality_retired: float = 0.0

    # Coordination
    clubbing_ratio: float = 0.0
    clubbed_blocks: int = 0
    line_closures_saved: int = 0

    # Traffic
    traffic_cost: float = 0.0
    traffic_cost_per_task: float = 0.0
    corridor_adherence: float = 0.0

    # Schedule health
    block_utilisation: float = 0.0
    overdue_task_days: int = 0
    expected_cancellations: float = 0.0

    # Outcome against ground truth
    unplanned_failures: int = 0
    critical_unplanned_failures: int = 0

    notes: list[str] = field(default_factory=list)

    def as_rows(self) -> list[tuple[str, str]]:
        return [
            ("Risk retired / block-hour", f"{self.risk_retired_per_block_hour:.1f}"),
            ("Tasks scheduled", f"{self.tasks_scheduled}"),
            ("Tasks unscheduled", f"{self.tasks_unscheduled}"),
            ("Blocks used", f"{self.blocks_used}"),
            ("Block hours consumed", f"{self.block_hours:.1f}"),
            ("Criticality retired", f"{self.criticality_retired:.0f}"),
            ("Clubbing ratio (depts/block)", f"{self.clubbing_ratio:.2f}"),
            ("Clubbed blocks", f"{self.clubbed_blocks}"),
            ("Line closures saved", f"{self.line_closures_saved}"),
            ("Traffic cost (wtd detention min)", f"{self.traffic_cost:,.0f}"),
            ("Traffic cost per task", f"{self.traffic_cost_per_task:.0f}"),
            ("Corridor adherence", f"{self.corridor_adherence:.0%}"),
            ("Block utilisation", f"{self.block_utilisation:.0%}"),
            ("Overdue task-days", f"{self.overdue_task_days}"),
            ("Expected cancellations", f"{self.expected_cancellations:.1f}"),
            ("Unplanned failures", f"{self.unplanned_failures}"),
            ("  of which high-criticality", f"{self.critical_unplanned_failures}"),
        ]


def evaluate(plan: Plan, tasks: list[MaintenanceTask]) -> PlanMetrics:
    by_id = {t.id: t for t in tasks}
    m = PlanMetrics(label=plan.label)

    m.blocks_used = len(plan.blocks)
    m.tasks_unscheduled = len(plan.unscheduled_task_ids)
    m.tasks_scheduled = sum(len(b.task_ids) for b in plan.blocks)

    total_minutes = 0
    worked_minutes = 0
    dept_slots = 0
    corridor_blocks = 0
    cancel_expectation = 0.0

    for b in plan.blocks:
        total_minutes += b.duration_min
        m.criticality_retired += b.criticality_retired
        m.traffic_cost += b.traffic_cost
        dept_slots += len(set(b.departments))
        if b.inside_corridor:
            corridor_blocks += 1

        members = [by_id[t] for t in b.task_ids if t in by_id]
        if members:
            # Departments work in parallel inside a clubbed block, so the productive
            # span is the longest member, not the sum.
            worked_minutes += min(b.duration_min,
                                  max(t.true_duration_min for t in members))
            cancel_expectation += (b.cancellation_risk if b.cancellation_risk is not None
                                   else max((t.cancellation_risk or 0.0) for t in members))

    m.block_hours = round(total_minutes / 60.0, 2)
    m.clubbed_blocks = len(plan.clubbed_blocks)
    m.clubbing_ratio = round(dept_slots / m.blocks_used, 3) if m.blocks_used else 0.0

    # Every department beyond the first in a block is one line closure that did not
    # have to happen. This is the quantity the problem statement is really about.
    m.line_closures_saved = dept_slots - m.blocks_used if m.blocks_used else 0

    m.traffic_cost = round(m.traffic_cost, 1)
    m.traffic_cost_per_task = round(
        m.traffic_cost / m.tasks_scheduled, 1) if m.tasks_scheduled else 0.0
    m.corridor_adherence = round(
        corridor_blocks / m.blocks_used, 4) if m.blocks_used else 0.0
    m.block_utilisation = round(
        worked_minutes / total_minutes, 4) if total_minutes else 0.0
    m.expected_cancellations = round(cancel_expectation, 2)

    m.risk_retired_per_block_hour = round(
        m.criticality_retired / m.block_hours, 2) if m.block_hours else 0.0

    # ---- outcome against ground truth ---------------------------------- #
    scheduled_day: dict[str, int] = {}
    for b in plan.blocks:
        for tid in b.task_ids:
            scheduled_day[tid] = b.day

    overdue_days = 0
    for t in tasks:
        day = scheduled_day.get(t.id)
        if day is None:
            # Never scheduled inside the horizon: it is late by the whole horizon,
            # and it fails if it was going to fail within it.
            overdue_days += max(0, plan.horizon_days - t.due_day)
            failed = t.true_days_to_failure <= plan.horizon_days
        else:
            overdue_days += max(0, day - t.due_day)
            failed = t.true_days_to_failure <= day

        if failed:
            m.unplanned_failures += 1
            if (t.criticality or 0) >= 60:
                m.critical_unplanned_failures += 1

    m.overdue_task_days = overdue_days
    return m


def compare(baseline: PlanMetrics, optimised: PlanMetrics) -> list[tuple[str, str, str, str]]:
    """Side-by-side rows: (measure, baseline, optimised, delta)."""
    rows = []
    b_rows = dict(baseline.as_rows())
    o_rows = dict(optimised.as_rows())

    # Measures where a bigger number is better.
    higher_better = {
        "Risk retired / block-hour", "Tasks scheduled", "Criticality retired",
        "Clubbing ratio (depts/block)", "Clubbed blocks", "Line closures saved",
        "Corridor adherence", "Block utilisation",
    }

    for name, b_val in b_rows.items():
        o_val = o_rows.get(name, "-")
        delta = _delta(name, b_val, o_val, name.strip() in higher_better)
        rows.append((name, b_val, o_val, delta))
    return rows


def _delta(name: str, b: str, o: str, higher_better: bool) -> str:
    def num(s: str) -> float | None:
        s = s.replace(",", "").replace("%", "").strip()
        try:
            return float(s)
        except ValueError:
            return None

    bv, ov = num(b), num(o)
    if bv is None or ov is None:
        return ""
    if bv == 0:
        return "+new" if ov > 0 else "="

    pct = (ov - bv) / abs(bv) * 100.0
    if abs(pct) < 0.5:
        return "="
    arrow = "better" if ((pct > 0) == higher_better) else "worse"
    return f"{pct:+.0f}%  {arrow}"
