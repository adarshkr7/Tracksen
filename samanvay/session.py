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
from dataclasses import astuple, dataclass, field

from .domain import MaintenanceTask, Plan
from .evaluate import PlanMetrics, evaluate
from .generator import generate_dataset
from .models.cancellation import CancellationModel
from .models.criticality import CriticalityModel
from .models.duration import DurationModel
from .models.traffic import TrafficModel
from .network import (
    SECTIONS,
    audit_corridors,
    generate_corridors,
    generate_timetable,
    resolve_regime,
)
from .optimizer.baseline import schedule_fcfs
from .optimizer.cpsat import (
    BlockOptimiser,
    Candidate,
    OptimiserWeights,
    _eligible,
    build_candidates,
    build_monthly_candidates,
    needs_extended_block,
    withdrawal_overhead,
    withdrawals_for,
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
                 monthly_days: int = 30, corridor_regime: str | None = None):
        self.horizon_days = horizon_days
        self.monthly_days = monthly_days
        self.seed = seed
        self.corridor_regime = resolve_regime(corridor_regime)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.ds = generate_dataset(n_pending=n_tasks, seed=seed)
            self.assets_by_id = {a.id: a for a in self.ds.assets}
            self.paths = generate_timetable(horizon_days)
            self.traffic = TrafficModel(self.paths, horizon_days)
            self.corridors = generate_corridors(
                horizon_days, self.corridor_regime, self.traffic)

            self.criticality = CriticalityModel().fit(self.ds.history_defects)
            breakdowns = self.criticality.score(
                self.ds.pending, self.assets_by_id, self.traffic, self.ds.repeat_failures
            )
            self.breakdowns = {b.task_id: b for b in breakdowns}

            self.duration = DurationModel().fit(self.ds.history_blocks)
            self.duration.predict(self.ds.pending)

            self.cancellation = CancellationModel().fit(self.ds.history_blocks)
            self.cancellation.predict(self.ds.pending)

        # Computed once: which mandated corridors the chart itself runs trains
        # through. It depends on the timetable and the regime, neither of which
        # changes between solves.
        self.corridor_audit = audit_corridors(self.paths, self.corridors)

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

        self._baselines: dict[tuple, Plan] = {}
        self._monthly_ctx: tuple | None = None

    # ------------------------------------------------------------------ #

    def baseline(self, weights: OptimiserWeights) -> Plan:
        """The FCFS comparison, cached per set of weights.

        Keyed by the weights, not computed once: the baseline obeys the same operational
        limits as the optimised plan -- how many blocks a department may field in a day,
        how many tasks fit in one -- so a planner who moves those sliders and re-solves
        would otherwise be shown a new plan against a baseline built under the old ones,
        and every percentage on the comparison screen would be measured off the wrong
        datum.
        """
        key = astuple(weights)
        cached = self._baselines.get(key)
        if cached is None:
            cached = schedule_fcfs(
                self.tasks, self.base_candidates, self.traffic, self.horizon_days, weights
            )
            self._baselines[key] = cached
        return cached

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

        for i, pin in enumerate(pins):
            tasks = [self.task_by_id[t] for t in pin.task_ids if t in self.task_by_id]
            if not tasks:
                rejected.append(f"{pin.block_id}: no known tasks")
                continue

            same_section = {(t.section_id, t.line) for t in tasks}
            if len(same_section) != 1:
                rejected.append(f"{pin.block_id}: tasks span more than one section/line")
                continue
            section_id, line = next(iter(same_section))

            # The possession has to hold the work AND the withdrawal it needs: a pinned
            # disconnection is disconnect, work, reconnect and test. Sizing it to the
            # work alone would hand the gang a window that cannot contain the job, and
            # `_eligible` would then refuse the planner's own pin for a reason that
            # looks like a bug rather than like arithmetic.
            capacity = max(
                (t.p90_duration_min or t.demanded_duration_min) for t in tasks
            ) + withdrawal_overhead(
                {bt for t in tasks for bt in withdrawals_for(t)}
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

            # A pin is a placement the planner chose by hand, so it never went through
            # build_candidates and never met the premier fence there. Without this check
            # the one rule the solver is not allowed to trade away could be walked
            # straight past by dragging a block on the what-if chart.
            fouled = self.traffic.premier_in_window(section_id, line, pin.start_min, end)
            if fouled:
                first = min(fouled, key=lambda p: p.enter_min)
                who = f"{first.train_no} {first.train_name}".strip()
                rejected.append(
                    f"{pin.block_id}: would stand in front of {who} at "
                    f"{first.enter_min % (24 * 60) // 60:02d}:"
                    f"{first.enter_min % 60:02d} -- premier paths are not blocked"
                )
                continue

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
                corridors = generate_corridors(days, self.corridor_regime, traffic)
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

        # The longest single spell, not the first and not the day's total: a task has to
        # fit one possession end to end.
        corridor_min = max((c.capacity_min for c in candidates), default=0)
        extended = [t for t in self.tasks if needs_extended_block(t, corridor_min)]
        fits = [t for t in self.tasks if not needs_extended_block(t, corridor_min)]

        opt = BlockOptimiser(weights=weights, time_limit_s=time_limit_s)
        plan = opt.solve(fits, candidates, traffic, self.monthly_days)
        plan.label = "TRACKSEN monthly (corridor-slot)"

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
            warm_start=warm_start, forced=forced,
        )

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
            corridor_regime=self.corridor_regime,
            corridor_audit=self.corridor_audit,
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
