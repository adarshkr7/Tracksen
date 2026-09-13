"""The two returns the circular already requires, built from a plan TRACKSEN produced.

Railway Board's joint circular of 28.12.2016, para 3.0, does not leave the reporting to
anyone's discretion:

    "All cases of cancellation/deviation from agreed block, productivity of blocks given
     and overdue maintenance details, etc. shall be put up weekly to DRM by Sr. DEN/Co-ord.
     and monthly to GM by PCE."

Every quantity in that sentence is already computed here. Risk retired per block-hour is
productivity of blocks given; `overdue_task_days` is overdue maintenance details; the
cancellation model is the only estimate of deviation available until an execution feed is
connected. What was missing was the shape: a division adopting TRACKSEN should not have to
invent a new process to use its output, because the process exists and someone is already
signing it every Monday.

Built from the serialised payload rather than from live objects, so the same function
serves `plan.json` on disk and an API response, and so a return can be reproduced from an
artefact that was archived months ago. The alternative -- re-solving to print a report --
would mean the return could disagree with the plan it claims to describe.

Nothing here is a sanction. These are returns about a *recommended* plan, and the header
of each says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DIVISION = "Danapur (East Central Railway)"

# Who signs, per para 3.0. Carried in the header because a return addressed to nobody in
# particular is a spreadsheet, not a return.
WEEKLY_AUTHORITY = "Sr.DEN/Co-ord to DRM"
MONTHLY_AUTHORITY = "PCE to GM"

PROVENANCE_NOTE = (
    "Synthetic operational data over a real network topology. Not an Indian Railways "
    "product and not connected to any live railway system."
)


@dataclass
class Part:
    """One lettered part of a return: a heading, some rows, and any caveats."""

    heading: str
    rows: list[tuple[str, str]] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class Return:
    title: str
    authority: str
    period: str
    parts: list[Part]
    notes: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        out = [f"# {self.title}", ""]
        out.append(f"**{DIVISION}** | {self.period} | **{self.authority}**")
        out.append("")
        out.append("Recommended plan. Sanction rests with the competent authority.")
        out.append("")
        for i, part in enumerate(self.parts):
            out.append(f"## {chr(ord('A') + i)}. {part.heading}")
            out.append("")
            if part.rows:
                out.append("| | |")
                out.append("|---|---|")
                out.extend(f"| {k} | {v} |" for k, v in part.rows)
                out.append("")
            for line in part.lines:
                out.append(f"- {line}")
            if part.lines:
                out.append("")
            if part.note:
                out.append(f"*{part.note}*")
                out.append("")
        if self.notes:
            out.append("---")
            out.append("")
            out.extend(f"{n}" for n in self.notes)
            out.append("")
        return "\n".join(out)

    def to_text(self) -> str:
        out = [self.title, "=" * len(self.title), ""]
        out.append(f"{DIVISION}   {self.period}   {self.authority}")
        out.append("Recommended plan. Sanction rests with the competent authority.")
        for i, part in enumerate(self.parts):
            out.append("")
            out.append(f"{chr(ord('A') + i)}. {part.heading}")
            out.append("-" * 74)
            for k, v in part.rows:
                out.append(f"  {k:<54}{v:>22}")
            for line in part.lines:
                out.append(f"  - {line}")
            if part.note:
                out.append(f"  ({part.note})")
        if self.notes:
            out.append("")
            out.extend(f"  {n}" for n in self.notes)
        return "\n".join(out)


# --------------------------------------------------------------------------- #
# Shared parts
# --------------------------------------------------------------------------- #

def _section_names(payload: dict) -> list[str]:
    return [s["id"] for s in payload["sections"]]


def _productivity(metrics: dict) -> Part:
    """Para 3.0's "productivity of blocks given"."""
    burst = metrics.get("blocks_written_to_burst", 0)
    blocks = metrics.get("blocks_used", 0) or 0
    burst_share = f" ({burst / blocks:.0%})" if blocks else ""
    return Part(
        heading="Productivity of blocks given",
        rows=[
            ("Blocks programmed", f"{blocks}"),
            ("Block hours", f"{metrics.get('block_hours', 0):.1f}"),
            ("Risk retired per block-hour", f"{metrics.get('risk_retired_per_block_hour', 0):.1f}"),
            ("Block utilisation", f"{metrics.get('block_utilisation', 0):.0%}"),
            ("Integrated blocks (2+ departments)", f"{metrics.get('clubbed_blocks', 0)}"),
            ("Departments per block", f"{metrics.get('clubbing_ratio', 0):.2f}"),
            ("Line closures avoided by integration", f"{metrics.get('line_closures_saved', 0)}"),
            ("Corridor adherence", f"{metrics.get('corridor_adherence', 0):.0%}"),
            ("Blocks written to burst", f"{burst}{burst_share}"),
            ("Burst minutes carried", f"{metrics.get('burst_minutes', 0):,}"),
        ],
        note=(
            "Blocks written to burst is measured against the duration model, not against "
            "execution. It says how many of these windows are too short for the work, "
            "not how many over-ran on the ground."
        ),
    )


def _deviation(payload: dict, metrics: dict) -> Part:
    """Para 3.0's "cancellation/deviation from agreed block".

    There is no execution feed, so there is nothing to report and the return says so.
    Filling this part with the cancellation model's output as though it were a record of
    what happened would be the single most misleading thing this document could do: the
    DRM reads this part to find out which blocks were agreed and not given.
    """
    expected = metrics.get("expected_cancellations", 0.0)
    return Part(
        heading="Cancellation and deviation from agreed block",
        rows=[
            ("Blocks agreed and not given", "no execution feed connected"),
            ("Blocks given and not utilised", "no execution feed connected"),
            ("Expected cancellations (model prior)", f"{expected:.1f}"),
        ],
        note=(
            "The first two rows are the ones para 3.0 actually asks for and they cannot "
            "be answered yet: nothing ingests what happened. The third is a forward-looking "
            "estimate from the cancellation model and must not be read as a record. See "
            "AUDIT.md and ROADMAP.md item 6."
        ),
    )


def _overdue(payload: dict, metrics: dict, blocks: list, horizon: int,
             worst: int = 8) -> Part:
    """Para 3.0's "overdue maintenance details".

    `blocks` and `horizon` are passed in rather than read off the payload because the
    monthly return describes a different plan over a different horizon from the weekly
    one. Reading the weekly blocks while reporting monthly totals would produce a return
    that is internally consistent, plausible, and about no plan that exists.
    """
    scheduled_day: dict[str, int] = {}
    for b in blocks:
        for tid in b["tasks"]:
            scheduled_day[tid] = b["day"]

    by_dept: dict[str, int] = {}
    rows: list[tuple[int, str]] = []
    for t in payload.get("tasks", []):
        day = scheduled_day.get(t["id"])
        # Never placed inside the horizon: late by the whole horizon, which is how the
        # plan metrics count it too.
        late = (horizon if day is None else day) - t["due_day"]
        if late <= 0:
            continue
        by_dept[t["dept"]] = by_dept.get(t["dept"], 0) + late
        state = "deferred beyond horizon" if day is None else f"programmed day {day}"
        rows.append((late, f"{t['id']} {t['dept']} {t['type']} at {t['section']} "
                           f"km {t['km']:.1f} -- {late} task-days late, {state}"))

    rows.sort(reverse=True)
    return Part(
        heading="Overdue maintenance",
        rows=[("Overdue task-days, total", f"{metrics.get('overdue_task_days', 0):,}")]
             + [(f"Overdue task-days, {d}", f"{v:,}") for d, v in sorted(by_dept.items())],
        lines=[text for _, text in rows[:worst]],
        note=(
            f"Worst {min(worst, len(rows))} of {len(rows)} tasks past their statutory date. "
            "The optimiser ranks by criticality rather than by age, so a long-overdue "
            "low-consequence job will be passed over; raise the overdue weight to buy that "
            "back, at a cost in risk retired per block-hour."
        ),
    )


# --------------------------------------------------------------------------- #
# The returns
# --------------------------------------------------------------------------- #

def weekly_drm_return(payload: dict[str, Any]) -> Return:
    """The weekly return to the DRM, per para 3.0.

    "Sr.DOM & Sr.DEN should make weekly programme" -- so this describes the week that was
    programmed, in the terms the circular asks for.
    """
    metrics = payload["metrics"]["optimised"]
    horizon = payload["meta"]["horizon_days"]
    regime = payload["meta"].get("corridorRegime", {})
    sections = _section_names(payload)

    by_dept: dict[str, int] = {}
    by_section: dict[str, int] = {}
    for b in payload.get("blocks", []):
        for d in set(b["depts"]):
            by_dept[d] = by_dept.get(d, 0) + 1
        name = sections[b["sec"]]
        by_section[name] = by_section.get(name, 0) + 1

    fouled = payload.get("corridorAudit", [])
    programmed = Part(
        heading="Blocks programmed",
        rows=[("Blocks", f"{metrics.get('blocks_used', 0)}"),
              ("Tasks placed", f"{metrics.get('tasks_scheduled', 0)}"),
              ("Tasks not placed in this week", f"{metrics.get('tasks_unscheduled', 0)}")]
             + [(f"Blocks holding {d} work", f"{v}") for d, v in sorted(by_dept.items())],
        lines=[
            f"{name}: {n} block(s)"
            for name, n in sorted(by_section.items(), key=lambda kv: -kv[1])[:8]
        ],
        note="A block holding two departments is counted once under each.",
    )

    corridor = Part(
        heading="Corridor",
        rows=[
            ("Regime", f"{regime.get('name', 'unknown')} "
                       f"({'+'.join(str(s) for s in regime.get('spells', []))} min)"),
            ("Longest single spell", f"{regime.get('longestSpellMin', 0)} min"),
            ("Corridor windows crossed by charted paths", f"{len(fouled)}"),
            ("Services to be regulated or rescheduled to clear them",
             f"{sum(f['booked'] for f in fouled):,}"),
        ],
        note=(
            "Para 2.0: where margins are inadequate the corridor is to be provided by "
            "rescheduling trains within the zone. The count is that demand on the working "
            "time table, not a defect in the plan."
        ),
    )

    return Return(
        title="Weekly return on traffic blocks",
        authority=WEEKLY_AUTHORITY,
        period=f"{horizon}-day programme",
        parts=[programmed, corridor, _productivity(metrics),
               _deviation(payload, metrics),
               _overdue(payload, metrics, payload.get("blocks", []), horizon)],
        notes=[
            "Rendered from the plan TRACKSEN recommended, in the form required by Railway "
            "Board's joint circular No. 2015/Track-III/TK/15 of 28.12.2016, para 3.0.",
            PROVENANCE_NOTE,
        ],
    )


def monthly_gm_return(payload: dict[str, Any]) -> Return:
    """The monthly return to the GM, per para 3.0.

    The month is the horizon on which the circular's joint programme is issued -- "at
    least one month in advance" -- so this return is about corridor slots and the demand
    that will not fit in one, which is the division's extended-block requirement.
    """
    monthly = payload.get("monthly")
    if not monthly:
        raise ValueError(
            "no monthly horizon in this plan; re-run the pipeline with --monthly"
        )

    metrics = monthly["metrics"]
    slots_total = monthly["slotsTotal"] or 0
    slots_used = monthly["slotsUsed"] or 0
    backlog = monthly.get("backlogByDay") or [0]
    extended = monthly.get("extendedTasks") or []

    task_by_id = {t["id"]: t for t in payload.get("tasks", [])}
    ext_by_dept: dict[str, int] = {}
    for tid in extended:
        t = task_by_id.get(tid)
        if t:
            ext_by_dept[t["dept"]] = ext_by_dept.get(t["dept"], 0) + 1

    allocation = Part(
        heading="Corridor slots allocated",
        rows=[
            ("Days", f"{monthly['days']}"),
            ("Corridor length", f"{monthly['corridorMinutes']} min"),
            ("Slots available", f"{slots_total:,}"),
            ("Slots allocated",
             f"{slots_used:,} ({slots_used / slots_total:.0%})" if slots_total
             else f"{slots_used:,}"),
            ("Tasks placed", f"{metrics.get('tasks_scheduled', 0)}"),
            ("Backlog at start", f"{backlog[0]:,}"),
            ("Backlog at end", f"{backlog[-1]:,}"),
        ],
    )

    extended_part = Part(
        heading="Extended and mega block demand",
        rows=[("Tasks that cannot fit one corridor", f"{len(extended)}")]
             + [(f"of which {d}", f"{v}") for d, v in sorted(ext_by_dept.items())],
        note=(
            "These need a block longer than the corridor provides and go up separately, "
            "negotiated with operations. Naming them is the point: this list IS the "
            "division's extended-block demand for the month."
        ),
    )

    return Return(
        title="Monthly return on traffic blocks",
        authority=MONTHLY_AUTHORITY,
        period=f"{monthly['days']}-day programme",
        parts=[allocation, extended_part, _productivity(metrics),
               _deviation(payload, metrics),
               _overdue(payload, metrics, monthly.get("blocks", []), monthly["days"])],
        notes=[
            "Rendered from the plan TRACKSEN recommended, in the form required by Railway "
            "Board's joint circular No. 2015/Track-III/TK/15 of 28.12.2016, para 3.0.",
            PROVENANCE_NOTE,
        ],
    )


RETURNS = {"weekly": weekly_drm_return, "monthly": monthly_gm_return}
