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
class SolveResult:
    plan: Plan
    baseline: Plan
    metrics: dict[str, PlanMetrics]
    payload: dict
    rejected: list[str] = field(default_factory=list)


class PlanningSession:
    """Holds everything expensive; solves cheaply and repeatedly."""

    def __init__(self, horizon_days: int = 7, n_tasks: int = 200, seed: int = 42):
        self.horizon_days = horizon_days
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

    # ------------------------------------------------------------------ #

    def baseline(self, weights: OptimiserWeights) -> Plan:
        if self._baseline is None:
            self._baseline = schedule_fcfs(
                self.tasks, self.base_candidates, self.traffic, self.horizon_days, weights
            )
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
