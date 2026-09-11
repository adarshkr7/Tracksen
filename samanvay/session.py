"""A planning session: the estate, the fitted models, and a solver you can re-run.

Fitting the models and generating the estate takes a few seconds. Re-solving does not.
So the session does the expensive work once at construction and then answers any number
of solve requests — which is what makes "re-solve holding my changes" fast enough to be
an interaction rather than a batch job.

Pinning is the whole point of the re-solve. A planner drags two blocks, says "keep those
where I put them and redo the rest", and the solver treats those placements as hard
facts and re-optimises everything else around them. That is a different question from
the one the original solve answered, and it is the one a human actually asks.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

from .domain import MaintenanceTask, Plan
from .evaluate import PlanMetrics, evaluate
from .generator import generate_dataset
from .models.cancellation import CancellationModel
from .models.criticality import CriticalityModel
from .models.duration import DurationModel
from .models.traffic import TrafficModel
from .network import SECTIONS, generate_corridors, generate_timetable
from .optimizer.baseline import schedule_fcfs
from .optimizer.cpsat import (
    BlockOptimiser,
    Candidate,
    OptimiserWeights,
    _eligible,
    build_candidates,
    build_monthly_candidates,
    needs_extended_block,
)
from .serialize import plan_payload

# Pinned placements get ids well clear of the enumerated ones, so adding a pin never
# renumbers the base candidates and a warm start stays meaningful.
PIN_ID_BASE = 1_000_000


@dataclass
class Pin:
    """A placement the planner has fixed. `block_id` identifies it in the UI only."""

    block_id: str
    start_min: int
    task_ids: list[str]


@dataclass
class MonthlyResult:
    plan: Plan
    metrics: PlanMetrics
    report: object
    extended_tasks: list[str]
    corridor_minutes: int
    slots_total: int
    slots_used: int
    backlog_by_day: list[int]
    missing_corridors: list[str]


@dataclass
class SolveResult:
    plan: Plan
    baseline: Plan
    metrics: dict[str, PlanMetrics]
    payload: dict
    rejected: list[str] = field(default_factory=list)


class PlanningSession:
    """Holds everything expensive; solves cheaply and repeatedly."""

    def __init__(self, horizon_days: int = 7, n_tasks: int = 200, seed: int = 42,
                 monthly_days: int = 30):
        self.horizon_days = horizon_days
        self.monthly_days = monthly_days
        self.seed = seed

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.ds = generate_dataset(n_pending=n_tasks, seed=seed)
            self.assets_by_id = {a.id: a for a in self.ds.assets}
            self.paths = generate_timetable(horizon_days)
            self.traffic = TrafficModel(self.paths, horizon_days)
            self.corridors = generate_corridors(horizon_days)

            self.criticality = CriticalityModel().fit(self.ds.history_defects)
            breakdowns = self.criticality.score(
                self.ds.pending, self.assets_by_id, self.traffic, self.ds.repeat_failures
            )
            self.breakdowns = {b.task_id: b for b in breakdowns}

            self.duration = DurationModel().fit(self.ds.history_blocks)
            self.duration.predict(self.ds.pending)

            self.cancellation = CancellationModel().fit(self.ds.history_blocks)
            self.cancellation.predict(self.ds.pending)

        self.tasks: list[MaintenanceTask] = self.ds.pending
        self.task_by_id = {t.id: t for t in self.tasks}
        self.base_candidates = build_candidates(
            [s.id for s in SECTIONS], horizon_days, self.traffic, self.corridors
        )

        self.model_checks = {
            "criticality": {
                **self.criticality.training_report,
                **self.criticality.evaluate_against_truth(self.tasks),
            },
            "duration": {
                **self.duration.training_report,
                **self.duration.evaluate_against_truth(self.tasks),
            },
            "cancellation": self.cancellation.training_report,
        }

        self._baseline: Plan | None = None
        self._monthly_ctx: tuple | None = None

    # ------------------------------------------------------------------ #

    def baseline(self, weights: OptimiserWeights) -> Plan:
        if self._baseline is None:
            self._baseline = schedule_fcfs(
                self.tasks, self.base_candidates, self.traffic, self.horizon_days, weights
            )
        self.cancellation.score_plan(self._baseline, self.tasks)
        return self._baseline

    def _pin_candidates(
        self, pins: list[Pin]
    ) -> tuple[list[Candidate], dict[str, int], list[str]]:
        """Turn each pin into a candidate the solver can be forced onto.

        A pinned start rarely coincides with an enumerated candidate -- the planner
        dragged it somewhere of their own choosing -- so we mint one. Capacity is the
        longest P90 among the pinned tasks, which is exactly what that block needs.
        Anything a pin cannot legally satisfy is rejected by name rather than silently
        dropped, because a pin that quietly vanishes is worse than one that is refused.
        """
        extra: list[Candidate] = []
        pin_cid: dict[str, int] = {}
        rejected: list[str] = []

        from collections import Counter
        block_counts = Counter(p.block_id for p in pins)
        task_counts = Counter(tid for p in pins for tid in p.task_ids)
        for i, pin in enumerate(pins):
            unknown = sorted(set(pin.task_ids) - self.task_by_id.keys())
            repeated = sorted({tid for tid in pin.task_ids if task_counts[tid] > 1})
            if block_counts[pin.block_id] > 1 or repeated or unknown:
                rejected.append(f"{pin.block_id}: duplicate block/task references or unknown tasks "
                                f"(repeated={repeated}, unknown={unknown})")
                continue
            tasks = [self.task_by_id[t] for t in pin.task_ids if t in self.task_by_id]
            if not tasks:
                rejected.append(f"{pin.block_id}: no known tasks")
                continue

            same_section = {(t.section_id, t.line) for t in tasks}
            if len(same_section) != 1:
                rejected.append(f"{pin.block_id}: tasks span more than one section/line")
                continue
            section_id, line = next(iter(same_section))

            capacity = max(
                (t.p90_duration_min or t.demanded_duration_min) for t in tasks
            )
            end = pin.start_min + capacity
            if pin.start_min < 0 or end > self.horizon_days * 24 * 60:
                rejected.append(f"{pin.block_id}: falls outside the horizon")
                continue

            day = pin.start_min // (24 * 60)
            inside = any(
                c.section_id == section_id and c.day == day
                and c.start_min <= pin.start_min and end <= c.end_min
                for c in self.corridors
            )

            cand = Candidate(
                id=PIN_ID_BASE + i,
                section_id=section_id,
                line=line,
                day=day,
                start_min=pin.start_min,
                capacity_min=capacity,
                traffic_cost=self.traffic.cost_of_block(section_id, line, pin.start_min, end),
                inside_corridor=inside,
                trains_affected=self.traffic.trains_affected(
                    section_id, line, pin.start_min, end
                ),
            )

            bad = [t.id for t in tasks if not _eligible(t, cand)]
            if bad:
                rejected.append(
                    f"{pin.block_id}: {', '.join(bad)} cannot be worked in that window"
                )
                continue

            extra.append(cand)
            pin_cid[pin.block_id] = cand.id

        return extra, pin_cid, rejected

    # ------------------------------------------------------------------ #


    # ------------------------------------------------------------------ #
    # Monthly horizon
    # ------------------------------------------------------------------ #

    def monthly_context(self):
        """Traffic, corridors and corridor-slot candidates over the long horizon.

        Built on first use: thirty days of timetable is an order of magnitude more
        paths than seven, and most sessions never ask for it.
        """
        if self._monthly_ctx is None:
            days = self.monthly_days
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                paths = generate_timetable(days)
                traffic = TrafficModel(paths, days)
                corridors = generate_corridors(days)
                cands, missing = build_monthly_candidates(
                    [s.id for s in SECTIONS], days, traffic, corridors
                )
            self._monthly_ctx = (paths, traffic, corridors, cands, missing)
        return self._monthly_ctx

    def solve_monthly(
        self,
        weights: OptimiserWeights | None = None,
        time_limit_s: float = 30.0,
    ) -> "MonthlyResult":
        """Allocate mandated corridor slots across the month.

        Deliberately coarser than the weekly solve: the decision is which department's
        work occupies which section-day corridor, not which quarter-hour. Work that
        cannot fit inside a corridor is named rather than silently dropped -- it needs
        an extended block negotiated with operations, which is a different conversation.
        """
        weights = weights or OptimiserWeights()
        paths, traffic, corridors, candidates, missing = self.monthly_context()

        corridor_min = candidates[0].capacity_min if candidates else 0
        extended = [t for t in self.tasks if needs_extended_block(t, corridor_min)]
        fits = [t for t in self.tasks if not needs_extended_block(t, corridor_min)]

        opt = BlockOptimiser(weights=weights, time_limit_s=time_limit_s)
        plan = opt.solve(fits, candidates, traffic, self.monthly_days,
                         cancellation=self.cancellation)
        plan.unscheduled_task_ids.extend(t.id for t in extended)
        plan.label = "SAMANVAY monthly (corridor-slot)"
        opt.report.unscheduled = len(plan.unscheduled_task_ids)

        metrics = evaluate(plan, self.tasks)

        # How fast the backlog actually clears, day by day.
        burn: list[int] = []
        remaining = len(self.tasks)
        done_by_day: dict[int, int] = {}
        for b in plan.blocks:
            done_by_day[b.day] = done_by_day.get(b.day, 0) + len(b.task_ids)
        for d in range(self.monthly_days):
            remaining -= done_by_day.get(d, 0)
            burn.append(remaining)

        return MonthlyResult(
            plan=plan,
            metrics=metrics,
            report=opt.report,
            extended_tasks=[t.id for t in extended],
            corridor_minutes=corridor_min,
            slots_total=len(candidates),
            slots_used=len(plan.blocks),
            backlog_by_day=burn,
            missing_corridors=missing,
        )

    def solve(
        self,
        weights: OptimiserWeights | None = None,
        pins: list[Pin] | None = None,
        time_limit_s: float = 20.0,
        warm_start: Plan | None = None,
    ) -> SolveResult:
        weights = weights or OptimiserWeights()
        pins = pins or []

        extra, pin_cid, rejected = self._pin_candidates(pins)
        candidates = self.base_candidates + extra
        if warm_start:
            prior_pins = [Pin(b.id, b.start_min, b.task_ids) for b in warm_start.blocks]
            retained, _, _ = self._pin_candidates(prior_pins)
            positions = {(c.section_id, c.line, c.start_min, c.capacity_min) for c in candidates}
            for i, c in enumerate(retained):
                key = (c.section_id, c.line, c.start_min, c.capacity_min)
                if key not in positions:
                    c.id = PIN_ID_BASE * 2 + i
                    candidates.append(c)
                    positions.add(key)

        forced: dict[str, int] = {}
        for pin in pins:
            cid = pin_cid.get(pin.block_id)
            if cid is None:
                continue
            for tid in pin.task_ids:
                if tid in self.task_by_id:
                    forced[tid] = cid

        opt = BlockOptimiser(weights=weights, time_limit_s=time_limit_s)
        plan = opt.solve(
            self.tasks, candidates, self.traffic, self.horizon_days,
            warm_start=warm_start, forced=forced, cancellation=self.cancellation,
        )

        if opt.report.status == "INFEASIBLE" and pins:
            rejected.extend(f"{p.block_id}: pinned placements cannot be satisfied together"
                            for p in pins if p.block_id in pin_cid)
        base = self.baseline(weights)
        metrics = {
            "baseline": evaluate(base, self.tasks),
            "optimised": evaluate(plan, self.tasks),
        }

        payload = plan_payload(
            plan=plan,
            baseline=base,
            tasks=self.tasks,
            breakdowns=self.breakdowns,
            paths=self.paths,
            corridors=self.corridors,
            metrics=metrics,
            weights=weights,
            report=opt.report,
            model_checks=self.model_checks,
            horizon_days=self.horizon_days,
            seed=self.seed,
            pinned=[{"block_id": p.block_id, "start_min": p.start_min} for p in pins],
        )
        payload["meta"]["rejectedPins"] = rejected

        return SolveResult(
            plan=plan, baseline=base, metrics=metrics, payload=payload, rejected=rejected
        )

    def standby(self, original: Plan, released_block_id: str, ready_task_ids: list[str],
                weights: OptimiserWeights | None = None, time_limit_s: float = 20.0) -> SolveResult:
        """Recommend replacements in one released slot, keeping all other work fixed.

        Readiness must be supplied by the planner. This creates a proposal only; it
        neither releases a sanctioned block nor carries approvals into the new plan.
        """
        weights = weights or OptimiserWeights()
        released = next((b for b in original.blocks if b.id == released_block_id), None)
        if released is None:
            raise ValueError(f"unknown released block {released_block_id}")
        if len(ready_task_ids) != len(set(ready_task_ids)):
            raise ValueError("duplicate ready task ids")
        if set(ready_task_ids) - set(original.unscheduled_task_ids):
            raise ValueError("standby readiness must name unscheduled tasks in the proposal")
        if set(ready_task_ids) - self.task_by_id.keys():
            raise ValueError("unknown ready tasks")
        remaining = [b for b in original.blocks if b.id != released_block_id]
        pins = [Pin(b.id, b.start_min, b.task_ids) for b in remaining]
        candidates, mapping, rejected = self._pin_candidates(pins)
        if rejected:
            raise ValueError("existing placements are invalid: " + "; ".join(rejected))
        forced = {tid: mapping[p.block_id] for p in pins for tid in p.task_ids}
        slot = Candidate(PIN_ID_BASE * 3, released.section_id, released.line, released.day,
            released.start_min, released.duration_min, released.traffic_cost,
            released.inside_corridor, self.traffic.trains_affected(released.section_id,
            released.line, released.start_min, released.end_min))
        candidates.append(slot)
        tids = set(forced) | set(ready_task_ids)
        tasks = [t for t in self.tasks if t.id in tids]
        opt = BlockOptimiser(weights, time_limit_s=time_limit_s)
        plan = opt.solve(tasks, candidates, self.traffic, self.horizon_days,
                         forced=forced, cancellation=self.cancellation)
        scheduled = {tid for b in plan.blocks for tid in b.task_ids}
        plan.unscheduled_task_ids = [t.id for t in self.tasks if t.id not in scheduled]
        opt.report.unscheduled = len(plan.unscheduled_task_ids)
        base = self.baseline(weights)
        metrics = {"baseline": evaluate(base, self.tasks), "optimised": evaluate(plan, self.tasks)}
        payload = plan_payload(plan=plan, baseline=base, tasks=self.tasks, breakdowns=self.breakdowns,
            paths=self.paths, corridors=self.corridors, metrics=metrics, weights=weights,
            report=opt.report, model_checks=self.model_checks, horizon_days=self.horizon_days, seed=self.seed)
        payload["standbyQueue"] = sorted(
            [t.id for t in tasks if t.id in ready_task_ids and _eligible(t, slot)],
            key=lambda tid: -(self.task_by_id[tid].criticality or 0))
        payload["releasedBlock"] = released_block_id
        payload["meta"]["rejectedPins"] = []
        return SolveResult(plan, base, metrics, payload)

    def monthly_cached(self, weights: OptimiserWeights) -> MonthlyResult:
        """Monthly allocations are independent of weekly moves; cache by all weights."""
        key = tuple(sorted(weights.__dict__.items()))
        cache = getattr(self, "_monthly_results", None)
        if cache is None:
            self._monthly_results = cache = {}
        if key not in cache:
            result = self.solve_monthly(weights, time_limit_s=10)
            if result.report.status in ("OPTIMAL", "FEASIBLE"):
                cache[key] = result
            return result
        return cache[key]
