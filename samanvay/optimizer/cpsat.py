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

import os

from dataclasses import dataclass, field
from typing import Iterable

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
from ..network import (
    JUNCTION_GROUPS,
    JUNCTION_THROAT_KM,
    SECTION_BY_ID,
    junction_km,
    lines_for_section,
)

# Capacities a block may be granted for. Real demands are round; so are these.
CAPACITY_OPTIONS_MIN = [60, 120, 180, 240, 300]

# Plant has to be positioned. Two blocks needing the same machine must be separated by
# at least this much, network-wide.
MACHINE_POSITIONING_MIN = 90

# What each kind of withdrawal costs before and after the work itself.
#
# These are not the same event. A traffic block hands the line over and takes it back; a
# disconnection additionally takes signalling out of service and has to be reconnected
# and tested before the line can be given back; a power block additionally isolates and
# earths the OHE and has to restore it. Those minutes are inside the possession and are
# not available for work, which is why a 180-minute corridor does not give a TRD gang
# 180 minutes of working time.
#
# Keyed by BlockType so the value is read off the withdrawal the task actually needs
# rather than assumed from the department: an S&T job at a location already isolated is
# a different event from one that is not.
SETUP_MIN: dict[BlockType, int] = {
    BlockType.TRAFFIC: 0,          # the hand-over itself, already priced as regulation
    BlockType.DISCONNECTION: 15,   # disconnect signalling and prove it
    BlockType.POWER: 20,           # isolate and earth the OHE
}
RESTORE_MIN: dict[BlockType, int] = {
    BlockType.TRAFFIC: 0,
    BlockType.DISCONNECTION: 20,   # reconnect, test, and take off the disconnection
    BlockType.POWER: 15,           # remove earths and recharge
}


def withdrawals_for(task: MaintenanceTask) -> set[BlockType]:
    """Every withdrawal a task actually needs, which is not only the one it is filed as.

    A task carries a nominal `block_type` -- the withdrawal its own department raised the
    demand under. That is not the whole picture. Work on or beside OHE needs the traction
    current off whoever asked for the block: a P.Way gang changing a sleeper under live
    contact wire is not made safe by the demand saying "traffic block". `MaintenanceTask`
    already knows this (`requires_power_block` folds in the asset class), and this is
    where that knowledge is spent.
    """
    out = {task.block_type}
    if task.requires_power_block:
        out.add(BlockType.POWER)
    if task.requires_disconnection:
        out.add(BlockType.DISCONNECTION)
    return out


def withdrawal_overhead(block_types: Iterable[BlockType]) -> int:
    """Setup and restoration minutes a block loses to its withdrawals.

    The MAXIMUM across the withdrawals present, never the sum. One isolation covers
    every TRD gang working under it, and the disconnection is taken once for the block,
    not once per job -- which is a real part of why clubbing is worth doing and would be
    thrown away by adding these up. Different withdrawal types do overlap in practice
    (the OHE is isolated while signalling is being disconnected), so the block loses the
    longest of them, not the total.
    """
    types = list(block_types) or [BlockType.TRAFFIC]
    return max(SETUP_MIN[t] for t in types) + max(RESTORE_MIN[t] for t in types)

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

    max_tasks_per_block: int = 3
    # Calibrated for a division, not a single corridor: Danapur works five routes and
    # thirty-odd block sections, so a department fielding six gangs a day across all of
    # it would be a staffing figure no division would recognise.
    max_blocks_per_dept_per_day: int = 12


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
        # A single-line branch has one road; enumerating a DN line it does not have
        # would invent capacity the division cannot use.
        for line in lines_for_section(sid):
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
                        # A block is not granted across a Rajdhani or a Vande Bharat.
                        # Withheld rather than priced, so no saving elsewhere can buy
                        # it: the solver never sees the option.
                        if traffic.fouls_premier(sid, line, start, start + cap):
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

    Returns the candidates and the unavailable section-day slots, so a caller can
    report a missing or unsafe corridor rather than silently planning nothing there.
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
            for line in lines_for_section(sid):
                # Monthly candidates are built directly from corridor slots rather
                # than through build_candidates, so the premier-path fence must be
                # repeated here. A malformed master chart must result in an explicit
                # unavailable slot, never in a block over a protected train.
                if traffic.fouls_premier(sid, line, corr.start_min, corr.end_min):
                    missing.append(f"{sid} {line.value} day {day}: corridor fouls premier path")
                    continue
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

    The withdrawal counts. A 170-minute disconnection does not fit a 180-minute corridor:
    disconnecting and reconnecting the signalling costs 35 of those minutes, so the job
    needs 205. Comparing bare P90 against the corridor handed such tasks to the solver as
    though they fitted, where they could never be placed -- they came out as "deferred"
    rather than "needs an extended block", which is the wrong answer operationally, and
    their criticality inflated the objective's upper bound with work no plan could do.
    """
    need = task.p90_duration_min or task.demanded_duration_min
    return need + withdrawal_overhead(withdrawals_for(task)) > corridor_min


def working_minutes(cand: Candidate, block_types: Iterable[BlockType]) -> int:
    """Minutes inside the possession actually available for work."""
    return cand.capacity_min - withdrawal_overhead(block_types)


def _eligible(task: MaintenanceTask, cand: Candidate) -> bool:
    """Can this task go in this window at all? Hard rules only."""
    if task.section_id != cand.section_id or task.line != cand.line:
        return False
    # The withdrawal this task needs eats into the window before work can start. A
    # 60-minute possession is not 60 minutes of OHE work: twenty of them are isolation
    # and fifteen are restoration.
    need = task.p90_duration_min or task.demanded_duration_min
    if need > working_minutes(cand, withdrawals_for(task)):
        return False
    if not task.night_work_allowed:
        mod = cand.start_min % MINUTES_PER_DAY
        if mod < DAY_START_MIN or mod + cand.capacity_min > DAY_END_MIN:
            return False
    return True


# --------------------------------------------------------------------------- #
# The model
# --------------------------------------------------------------------------- #

def default_workers() -> int:
    """One search worker per core.

    CP-SAT runs a PORTFOLIO: each worker explores with a different strategy and they
    share bounds, so the count is not a throughput dial -- it is how many different ways
    the problem is attacked at once. The fixed 8 this used to carry left half of a
    sixteen-core machine idle, and measured at 180 seconds that alone was the difference
    between a 73.1% gap and 18.2%: same plan, far better bound.
    """
    return max(1, os.cpu_count() or 8)


class BlockOptimiser:
    def __init__(self, weights: OptimiserWeights | None = None,
                 time_limit_s: float = 30.0, workers: int | None = None):
        self.w = weights or OptimiserWeights()
        self.time_limit_s = time_limit_s
        self.workers = workers or default_workers()
        self.report: SolveReport | None = None

    def solve(
        self,
        tasks: list[MaintenanceTask],
        candidates: list[Candidate],
        traffic: TrafficModel,
        horizon_days: int,
        warm_start: Plan | None = None,
        forced: dict[str, int] | None = None,
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

        # ---- the withdrawal has to fit inside the possession ----------- #
        # `_eligible` already checks a task against its own withdrawal, but clubbing
        # changes the answer: an hour of track work fits an hour-long block on its own,
        # and stops fitting the moment a power block is clubbed into it, because the
        # first twenty minutes are now OHE isolation and the last fifteen are recharging.
        # Without this the plan would promise gangs working time the possession does not
        # contain, and the overrun would surface on the ground rather than on the chart.
        #
        # setup and restore take the MAXIMUM over the withdrawals present, not the sum.
        # Only lower bounds are needed: both appear solely on the left of a <= capacity
        # constraint, so the solver already wants them small and the bounds force them up
        # exactly as far as the clubbed withdrawals require.
        max_setup = max(SETUP_MIN.values())
        max_restore = max(RESTORE_MIN.values())
        for c in candidates:
            member_ids = tasks_for_cand[c.id]
            if not member_ids:
                continue
            setup = m.NewIntVar(0, max_setup, f"setup_{c.id}")
            restore = m.NewIntVar(0, max_restore, f"restore_{c.id}")
            for tid in member_ids:
                v = assign[(tid, c.id)]
                needed = withdrawals_for(task_by_id[tid])
                m.Add(setup >= max(SETUP_MIN[bt] for bt in needed)).OnlyEnforceIf(v)
                m.Add(restore >= max(RESTORE_MIN[bt] for bt in needed)).OnlyEnforceIf(v)
                need = (task_by_id[tid].p90_duration_min
                        or task_by_id[tid].demanded_duration_min)
                m.Add(need + setup + restore <= c.capacity_min).OnlyEnforceIf(v)

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

        # A redundant AddAtMostOne over the candidates sharing a section, a line and a
        # start -- the five capacity variants -- was tried here and removed. The theory
        # was that NoOverlap reasons through an interval propagator the linear relaxation
        # cannot see, so stating the same thing linearly would tighten the bound the gap
        # was stuck on. Measured at 600s and 16 workers, the bound moved from 8,807 to
        # 8,809: two units in eight thousand, which is nothing. The 8.0% -> 6.5% that
        # came with it was a luckier incumbent, and at 180s the same cut measured 39.6%
        # against 18.2% without it. A constraint whose stated mechanism does not happen
        # is not worth the presolve.

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

        # ---- junction throats ------------------------------------------- #
        # Where routes converge, the throat is one interlocked area. Work in the throat
        # of one leg cannot proceed while the throat of another is occupied, so a block
        # on the Barauni branch at Hathidah has to be planned against the main line --
        # which is precisely the coordination a single-corridor scheduler never has to
        # do. Only work actually *in* the throat interacts; plain line further out on
        # either leg is independent.
        for jn, section_ids in JUNCTION_GROUPS.items():
            throat_ivs = []
            for c in candidates:
                if c.section_id not in section_ids:
                    continue
                route = SECTION_BY_ID[c.section_id].route
                try:
                    jkm = junction_km(jn, route)
                except KeyError:
                    continue
                in_throat = [
                    assign[(tid, c.id)]
                    for tid in tasks_for_cand[c.id]
                    if abs(task_by_id[tid].chainage_km - jkm) <= JUNCTION_THROAT_KM
                ]
                if not in_throat:
                    continue
                v = m.NewBoolVar(f"throat_{jn}_{c.id}")
                m.Add(v <= sum(in_throat))
                for x in in_throat:
                    m.AddImplication(x, v)
                throat_ivs.append(
                    m.NewOptionalFixedSizeIntervalVar(
                        c.start_min, c.capacity_min, v, f"tiv_{jn}_{c.id}"
                    )
                )
            if len(throat_ivs) > 1:
                m.AddNoOverlap(throat_ivs)

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

        for t in tasks:
            crit = t.criticality if t.criticality is not None else 0.0
            for cid in cands_for_task[t.id]:
                c = cand_by_id[cid]
                lateness = max(0, c.day - t.due_day)
                value = w.criticality * crit - w.overdue * lateness
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
            for tid, cid in forced.items():
                key = (tid, cid)
                if key in assign:
                    m.Add(assign[key] == 1)

        # ---- plan stability --------------------------------------------- #
        # Warm-starting from the sanctioned plan keeps the schedule recognisable
        # night to night. A scheduler that reshuffles the whole week every run is
        # technically optimal and operationally useless.
        if warm_start is not None:
            hinted: set[tuple[str, int]] = set()
            for blk in warm_start.blocks:
                try:
                    cid = int(blk.id)
                except (TypeError, ValueError):
                    continue          # baseline blocks carry composite ids
                for tid in blk.task_ids:
                    key = (tid, cid)
                    if key in assign and key not in hinted:
                        m.AddHint(assign[key], 1)
                        hinted.add(key)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.time_limit_s
        solver.parameters.num_search_workers = self.workers
        # linearization_level is deliberately left alone. Raising it to 2 builds a
        # stronger LP relaxation, which is what the bound is computed from, so it looked
        # like the obvious lever -- and measured at 180 seconds it made the gap WORSE,
        # 18.2% to 25.1%. The stronger relaxation costs more per node than the portfolio
        # recovers. symmetry_level=2 was neutral. Measured, not assumed.
        status = solver.Solve(m)

        plan = self._extract(
            solver, status, tasks, candidates, cand_by_id, assign,
            cands_for_task, use, traffic, horizon_days
        )

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
            return Plan([], [t.id for t in tasks], horizon_days, label="optimised (infeasible)")

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

            # `capacity_min` is the possession that the solver reserved.  It must be
            # the interval shown to operations and used for the reported traffic cost:
            # shortening it here used to make the displayed plan overlap-safe while
            # the optimisation had priced and excluded a longer, different plan.
            # Releasing unused minutes is a later, explicit re-planning operation;
            # it cannot be inferred after CP-SAT has made its decisions.
            reserved_min = c.capacity_min
            reserved_cost = c.traffic_cost

            reasons = []
            if len(depts) > 1:
                reasons.append(
                    f"clubbed: {', '.join(d.value for d in depts)} share one closure"
                )
            if c.inside_corridor:
                reasons.append("inside mandated corridor")
            else:
                reasons.append(f"outside corridor -- {reserved_cost:.0f} wtd detention min")
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
                    end_min=c.start_min + reserved_min,
                    task_ids=sorted(tids),
                    departments=depts,
                    block_types=btypes,
                    inside_corridor=c.inside_corridor,
                    traffic_cost=reserved_cost,
                    criticality_retired=round(sum(t.criticality or 0 for t in ts), 2),
                    reasons=reasons,
                )
            )

        done = {tid for tids in members.values() for tid in tids}
        return Plan(
            blocks=sorted(blocks, key=lambda b: (b.start_min, b.section_id)),
            unscheduled_task_ids=[t.id for t in tasks if t.id not in done],
            horizon_days=horizon_days,
            label="TRACKSEN (CP-SAT)",
        )
