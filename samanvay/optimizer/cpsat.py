"""The block scheduler: a CP-SAT model over candidate windows.

The formulation deliberately enumerates *candidate blocks* -- (section, line, day,
start, capacity) -- rather than giving the solver free-floating intervals. Two reasons:

  1. Traffic cost depends on exactly which paths a window intersects. With the start
     and length fixed per candidate, that cost is a constant the objective can carry
     linearly, instead of a non-linear function of a decision variable.
  2. Real block demands are not placed at arbitrary minutes. They are placed in the
     corridor, or in one of a handful of defensible alternatives.

Objective:

    max  sum_t  Criticality(t) . Completed(t)
       + beta  . sum_b ClubbingBonus(b)
       - lambda. sum_b TrafficCost(b)
       - mu    . sum_t OverdueBreach(t)

Clubbing is encoded through one constraint that does most of the work: **at most one
task per department per block**. A department fields one gang per block, so a block
holding two tasks necessarily holds two departments -- and the bonus then rewards
exactly the coordination the problem statement is about. Work inside a block runs in
parallel across departments, which is what clubbing means operationally.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from ..domain import (
    MINUTES_PER_DAY,
    SLOT_MIN,
    BlockType,
    CorridorWindow,
    Department,
    Line,
    MachineType,
    MaintenanceTask,
    Plan,
    ScheduledBlock,
)
from ..models.traffic import TrafficModel

# Capacities a block may be granted for. Real demands are round; so are these.
CAPACITY_OPTIONS_MIN = [60, 120, 180, 240, 300]

# Plant has to be positioned. Two blocks needing the same machine must be separated by
# at least this much, network-wide.
MACHINE_POSITIONING_MIN = 90

# Daylight, for work types that cannot be done under lights.
DAY_START_MIN, DAY_END_MIN = 6 * 60, 18 * 60


@dataclass
class OptimiserWeights:
    """Exposed to the planner as sliders, not buried as constants.

    Divisions weigh freight path loss against maintenance backlog differently. A
    system that hides this trade-off inside a hard-coded constant will be trusted less
    than one that surfaces it.
    """

    criticality: float = 1.0
    clubbing: float = 25.0       # per extra department sharing a block
    traffic: float = 0.05        # per weighted detention minute
    overdue: float = 1.5         # per task-day late against the statutory date
    corridor: float = 40.0       # per block placed inside the mandated corridor
    stability: float = 10.0     # per previously placed task moved or dropped
    cancellation: float = 10.0  # per expected cancelled task

    max_tasks_per_block: int = 3
    max_blocks_per_dept_per_day: int = 6


@dataclass
class Candidate:
    """One placement the solver may or may not use."""

    id: int
    section_id: str
    line: Line
    day: int
    start_min: int
    capacity_min: int
    traffic_cost: float
    inside_corridor: bool
    trains_affected: int

    @property
    def end_min(self) -> int:
        return self.start_min + self.capacity_min


@dataclass
class SolveReport:
    status: str
    objective: float
    wall_time_s: float
    candidates: int
    assign_vars: int
    scheduled: int
    unscheduled: int
    conflicts: int = 0
    branches: int = 0
    best_bound: float = 0.0
    gap_pct: float = 0.0
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Candidate enumeration
# --------------------------------------------------------------------------- #

def build_candidates(
    section_ids: list[str],
    horizon_days: int,
    traffic: TrafficModel,
    corridors: list[CorridorWindow],
    alternatives_per_day: int = 2,
) -> list[Candidate]:
    """Enumerate placements: the mandated corridor, plus the cheapest alternatives.

    Every section-day gets its corridor window. We add a small number of non-corridor
    starts drawn from the cheapest hours so the solver has somewhere to go when the
    corridor is full -- priced at what those hours actually cost.
    """
    corridor_by_key = {(c.section_id, c.day): c for c in corridors}
    out: list[Candidate] = []
    cid = 0

    for sid in section_ids:
        for line in (Line.UP, Line.DN):
            for day in range(horizon_days):
                starts: list[tuple[int, bool]] = []

                corr = corridor_by_key.get((sid, day))
                if corr is not None:
                    starts.append((corr.start_min, True))

                cheap = traffic.cheapest_hours(sid, line, day, k=alternatives_per_day + 3)
                base = day * MINUTES_PER_DAY
                added = 0
                for hour in cheap:
                    if added >= alternatives_per_day:
                        break
                    start = base + hour * 60
                    if corr is not None and corr.start_min <= start < corr.end_min:
                        continue           # already covered by the corridor candidate
                    starts.append((start, False))
                    added += 1

                for start, inside in starts:
                    for cap in CAPACITY_OPTIONS_MIN:
                        if inside and corr is not None and start + cap > corr.end_min:
                            continue       # a corridor block cannot outrun the corridor
                        if start + cap > horizon_days * MINUTES_PER_DAY:
                            continue
                        cid += 1
                        out.append(
                            Candidate(
                                id=cid,
                                section_id=sid,
                                line=line,
                                day=day,
                                start_min=start,
                                capacity_min=cap,
                                traffic_cost=traffic.cost_of_block(sid, line, start, start + cap),
                                inside_corridor=inside,
                                trains_affected=traffic.trains_affected(
                                    sid, line, start, start + cap
                                ),
                            )
                        )
    return out


def build_monthly_candidates(
    section_ids: list[str],
    horizon_days: int,
    traffic: TrafficModel,
    corridors: list[CorridorWindow],
) -> tuple[list[Candidate], list[str]]:
    """Corridor-slot granularity: one candidate per section, line and day.

    A monthly plan answers a different question from a weekly one. Nobody commits a
    tamping machine to 11:15 on the 24th four weeks out; they commit it to *a corridor
    on the 24th*. So the monthly model drops the fine time grid entirely and allocates
    the mandated corridor itself -- which is the unit a division actually plans plant,
    material and staff against.

    Returns the candidates and the ids of sections with no corridor, so a caller can
    report the gap rather than silently planning nothing there.
    """
    by_key = {(c.section_id, c.day): c for c in corridors}
    out: list[Candidate] = []
    missing: list[str] = []
    cid = 0

    for sid in section_ids:
        for day in range(horizon_days):
            corr = by_key.get((sid, day))
            if corr is None:
                missing.append(f"{sid} day {day}")
                continue
            capacity = corr.end_min - corr.start_min
            for line in (Line.UP, Line.DN):
                cid += 1
                out.append(
                    Candidate(
                        id=cid,
                        section_id=sid,
                        line=line,
                        day=day,
                        start_min=corr.start_min,
                        capacity_min=capacity,
                        traffic_cost=traffic.cost_of_block(
                            sid, line, corr.start_min, corr.end_min
                        ),
                        inside_corridor=True,
                        trains_affected=traffic.trains_affected(
                            sid, line, corr.start_min, corr.end_min
                        ),
                    )
                )
    return out, missing


def needs_extended_block(task: MaintenanceTask, corridor_min: int) -> bool:
    """Work too long for the mandated corridor.

    Deep screening and rail renewal routinely outrun a three-hour corridor. On the
    real railway these go up as a separate extended or mega block negotiated with
    operations. The monthly plan cannot absorb them, so it names them instead of
    quietly leaving them unscheduled.
    """
    return (task.p90_duration_min or task.demanded_duration_min) > corridor_min


def _eligible(task: MaintenanceTask, cand: Candidate) -> bool:
    """Can this task go in this window at all? Hard rules only."""
    if task.section_id != cand.section_id or task.line != cand.line:
        return False
    if (task.p90_duration_min or task.demanded_duration_min) > cand.capacity_min:
        return False
    if not task.night_work_allowed:
        mod = cand.start_min % MINUTES_PER_DAY
        if mod < DAY_START_MIN or mod + cand.capacity_min > DAY_END_MIN:
            return False
    return True


# --------------------------------------------------------------------------- #
# The model
# --------------------------------------------------------------------------- #

class BlockOptimiser:
    def __init__(self, weights: OptimiserWeights | None = None,
                 time_limit_s: float = 30.0, workers: int = 8):
        self.w = weights or OptimiserWeights()
        self.time_limit_s = time_limit_s
        self.workers = workers
        self.report: SolveReport | None = None

    def solve(
        self,
        tasks: list[MaintenanceTask],
        candidates: list[Candidate],
        traffic: TrafficModel,
        horizon_days: int,
        warm_start: Plan | None = None,
        forced: dict[str, int] | None = None,
        cancellation=None,
    ) -> Plan:
        m = cp_model.CpModel()
        w = self.w

        cand_by_id = {c.id: c for c in candidates}
        task_by_id = {t.id: t for t in tasks}

        # ---- variables ------------------------------------------------- #
        use: dict[int, cp_model.IntVar] = {
            c.id: m.NewBoolVar(f"use_{c.id}") for c in candidates
        }
        assign: dict[tuple[str, int], cp_model.IntVar] = {}
        cands_for_task: dict[str, list[int]] = {t.id: [] for t in tasks}
        tasks_for_cand: dict[int, list[str]] = {c.id: [] for c in candidates}

        for t in tasks:
            for c in candidates:
                if _eligible(t, c):
                    v = m.NewBoolVar(f"x_{t.id}_{c.id}")
                    assign[(t.id, c.id)] = v
                    cands_for_task[t.id].append(c.id)
                    tasks_for_cand[c.id].append(t.id)

        # ---- a task is scheduled at most once -------------------------- #
        for t in tasks:
            ids = cands_for_task[t.id]
            if ids:
                m.AddAtMostOne(assign[(t.id, cid)] for cid in ids)

        # ---- a block is "used" iff something is in it ------------------ #
        for c in candidates:
            members = [assign[(tid, c.id)] for tid in tasks_for_cand[c.id]]
            if not members:
                m.Add(use[c.id] == 0)
                continue
            for v in members:
                m.AddImplication(v, use[c.id])
            m.Add(sum(members) >= 1).OnlyEnforceIf(use[c.id])
            m.Add(sum(members) <= w.max_tasks_per_block)

        # ---- one gang per department per block ------------------------- #
        # This single constraint is what makes "clubbing" mean what it should:
        # a block with two tasks is a block serving two departments.
        dept_present: dict[tuple[int, Department], cp_model.IntVar] = {}
        for c in candidates:
            for dept in Department:
                members = [
                    assign[(tid, c.id)]
                    for tid in tasks_for_cand[c.id]
                    if task_by_id[tid].department is dept
                ]
                if not members:
                    continue
                m.AddAtMostOne(members)
                d = m.NewBoolVar(f"dept_{c.id}_{dept.value}")
                dept_present[(c.id, dept)] = d
                m.Add(d <= sum(members))
                for v in members:
                    m.AddImplication(v, d)

        # ---- clubbing indicator ---------------------------------------- #
        # extra_depts[b] counts departments beyond the first, so a three-department
        # block is worth twice a two-department one.
        extra_depts: dict[int, cp_model.IntVar] = {}
        for c in candidates:
            ds = [dept_present[(c.id, d)] for d in Department if (c.id, d) in dept_present]
            if len(ds) < 2:
                continue
            e = m.NewIntVar(0, len(ds) - 1, f"club_{c.id}")
            # Departments beyond the first. Guarded on `use`: an unused block holds
            # no departments, and an unguarded `e <= sum - 1` would then demand
            # e <= -1 against a domain floor of zero -- infeasible for the whole model.
            m.Add(e <= sum(ds) - 1).OnlyEnforceIf(use[c.id])
            m.Add(e == 0).OnlyEnforceIf(use[c.id].Not())
            extra_depts[c.id] = e

        # ---- line exclusivity ------------------------------------------ #
        # One occupant per block section and line at a time, enforced structurally.
        by_line: dict[tuple[str, Line], list[Candidate]] = {}
        for c in candidates:
            by_line.setdefault((c.section_id, c.line), []).append(c)

        for (_sid, _line), group in by_line.items():
            intervals = [
                m.NewOptionalFixedSizeIntervalVar(
                    c.start_min, c.capacity_min, use[c.id], f"iv_{c.id}"
                )
                for c in group
            ]
            m.AddNoOverlap(intervals)

        # ---- plant cannot be in two places at once ---------------------- #
        machine_here: dict[tuple[int, MachineType], cp_model.IntVar] = {}
        for c in candidates:
            for mach in MachineType:
                if mach is MachineType.NONE:
                    continue
                members = [
                    assign[(tid, c.id)]
                    for tid in tasks_for_cand[c.id]
                    if task_by_id[tid].machine is mach
                ]
                if not members:
                    continue
                # One unit of each machine type is available in this prototype.
                # Departments run in parallel, including inside one clubbed block.
                m.AddAtMostOne(members)
                v = m.NewBoolVar(f"mach_{c.id}_{mach.value}")
                machine_here[(c.id, mach)] = v
                m.Add(v <= sum(members))
                for x in members:
                    m.AddImplication(x, v)

        for mach in MachineType:
            if mach is MachineType.NONE:
                continue
            ivs = [
                m.NewOptionalFixedSizeIntervalVar(
                    cand_by_id[cid].start_min,
                    cand_by_id[cid].capacity_min + MACHINE_POSITIONING_MIN,
                    v,
                    f"miv_{cid}_{mach.value}",
                )
                for (cid, mm), v in machine_here.items() if mm is mach
            ]
            if len(ivs) > 1:
                m.AddNoOverlap(ivs)

        # ---- staff: a department can only run so many blocks a day ------ #
        for dept in Department:
            for day in range(horizon_days):
                ds = [
                    dept_present[(c.id, dept)]
                    for c in candidates
                    if c.day == day and (c.id, dept) in dept_present
                ]
                if ds:
                    m.Add(sum(ds) <= w.max_blocks_per_dept_per_day)

        # ---- objective --------------------------------------------------- #
        S = 100  # integer scaling; CP-SAT objectives must be integral
        terms = []
        previous = {tid: (b.section_id, b.line, b.start_min)
                    for b in (warm_start.blocks if warm_start else []) for tid in b.task_ids}
        risks = cancellation.candidate_risks(tasks, candidates) if cancellation else {}

        for t in tasks:
            crit = t.criticality if t.criticality is not None else 0.0
            for cid in cands_for_task[t.id]:
                c = cand_by_id[cid]
                lateness = max(0, c.day - t.due_day)
                # Relative to leaving the task overdue through horizon end. The omitted
                # baseline is constant, so this is equivalent to penalising all work.
                avoided_lateness = max(0, horizon_days - t.due_day) - lateness
                value = w.criticality * crit + w.overdue * avoided_lateness
                value -= w.cancellation * risks.get((t.id, cid), 0.0)
                # Reward retaining a placement; dropping and moving both forfeit it.
                if previous.get(t.id) == (c.section_id, c.line, c.start_min):
                    value += w.stability
                terms.append(int(round(value * S)) * assign[(t.id, cid)])

        for cid, e in extra_depts.items():
            terms.append(int(round(w.clubbing * S)) * e)

        for c in candidates:
            placement = -w.traffic * c.traffic_cost
            if c.inside_corridor:
                placement += w.corridor
            terms.append(int(round(placement * S)) * use[c.id])

        m.Maximize(sum(terms))

        # ---- pinned placements ------------------------------------------ #
        # A planner has dragged these and asked for everything else to be redone
        # around them. They are facts, not preferences.
        if forced:
            forced_candidates = set(forced.values())
            for (tid, cid), variable in assign.items():
                if cid in forced_candidates and forced.get(tid) != cid:
                    m.Add(variable == 0)
            for tid, cid in forced.items():
                key = (tid, cid)
                if key not in assign:
                    raise ValueError(f"cannot force {tid} onto ineligible candidate {cid}")
                m.Add(assign[key] == 1)

        # ---- plan stability --------------------------------------------- #
        # Warm-starting from the sanctioned plan keeps the schedule recognisable
        # night to night. A scheduler that reshuffles the whole week every run is
        # technically optimal and operationally useless.
        if warm_start is not None:
            hinted: set[tuple[str, int]] = set()
            for blk in warm_start.blocks:
                for tid in blk.task_ids:
                    for c in candidates:
                        key = (tid, c.id)
                        if (c.section_id, c.line, c.start_min) != (blk.section_id, blk.line, blk.start_min):
                            continue
                        if key in assign and key not in hinted:
                            m.AddHint(assign[key], 1)
                            hinted.add(key)
                            break

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.time_limit_s
        solver.parameters.num_search_workers = self.workers
        status = solver.Solve(m)

        plan = self._extract(
            solver, status, tasks, candidates, cand_by_id, assign,
            cands_for_task, use, traffic, horizon_days
        )

        if cancellation:
            cancellation.score_plan(plan, tasks)

        self.report = SolveReport(
            status=solver.StatusName(status),
            objective=solver.ObjectiveValue() / S if status in
            (cp_model.OPTIMAL, cp_model.FEASIBLE) else 0.0,
            wall_time_s=round(solver.WallTime(), 2),
            candidates=len(candidates),
            assign_vars=len(assign),
            scheduled=sum(len(b.task_ids) for b in plan.blocks),
            unscheduled=len(plan.unscheduled_task_ids),
            conflicts=solver.NumConflicts(),
            branches=solver.NumBranches(),
            best_bound=(solver.BestObjectiveBound() / S) if status in
            (cp_model.OPTIMAL, cp_model.FEASIBLE) else 0.0,
        )
        if self.report.objective:
            self.report.gap_pct = round(
                abs(self.report.best_bound - self.report.objective)
                / abs(self.report.objective) * 100.0, 2
            )
        return plan

    # ------------------------------------------------------------------ #

    def _extract(self, solver, status, tasks, candidates, cand_by_id, assign,
                 cands_for_task, use, traffic, horizon_days) -> Plan:
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return Plan([], [t.id for t in tasks], horizon_days, label=f"optimised ({solver.StatusName(status).lower()})")

        task_by_id = {t.id: t for t in tasks}
        members: dict[int, list[str]] = {}
        for (tid, cid), v in assign.items():
            if solver.Value(v):
                members.setdefault(cid, []).append(tid)

        blocks: list[ScheduledBlock] = []
        for cid, tids in sorted(members.items()):
            c = cand_by_id[cid]
            ts = [task_by_id[t] for t in tids]
            depts = sorted({t.department for t in ts}, key=lambda d: d.value)
            btypes = sorted({t.block_type for t in ts}, key=lambda b: b.value)

            # The block only needs to be as long as its longest member; the rest of
            # the reserved capacity is handed back rather than held against traffic.
            used_min = max(
                (t.p90_duration_min or t.demanded_duration_min) for t in ts
            )
            actual_cost = traffic.cost_of_block(
                c.section_id, c.line, c.start_min, c.start_min + used_min
            )

            reasons = []
            if len(depts) > 1:
                reasons.append(
                    f"clubbed: {', '.join(d.value for d in depts)} share one closure"
                )
            if c.inside_corridor:
                reasons.append("inside mandated corridor")
            else:
                reasons.append(f"outside corridor -- {actual_cost:.0f} wtd detention min")
            top = max(ts, key=lambda t: t.criticality or 0)
            if top.criticality:
                reasons.append(f"driven by {top.id} (criticality {top.criticality:.0f})")

            blocks.append(
                ScheduledBlock(
                    id=str(cid),
                    section_id=c.section_id,
                    line=c.line,
                    day=c.day,
                    start_min=c.start_min,
                    end_min=c.start_min + used_min,
                    task_ids=sorted(tids),
                    departments=depts,
                    block_types=btypes,
                    inside_corridor=c.inside_corridor,
                    traffic_cost=actual_cost,
                    criticality_retired=round(sum(t.criticality or 0 for t in ts), 2),
                    reasons=reasons,
                )
            )

        done = {tid for tids in members.values() for tid in tids}
        return Plan(
            blocks=sorted(blocks, key=lambda b: (b.start_min, b.section_id)),
            unscheduled_task_ids=[t.id for t in tasks if t.id not in done],
            horizon_days=horizon_days,
            label="SAMANVAY (CP-SAT)",
        )
