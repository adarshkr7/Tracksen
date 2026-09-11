"""Cancellation risk: will this block, if sanctioned, actually run?

A block that is sanctioned and then cancelled has consumed planning capacity and
returned nothing -- the paths were kept clear, the gang was booked, and no risk was
retired. Two uses:

  * avoid placing the most critical work into the most fragile slots, and
  * keep a standby queue, so a block released at short notice is filled, not lost.

**This is a logistic regression, not a gradient-boosted model, and that is deliberate.**
Held-out validation showed the boosted version scoring 0.92 AUC in-sample and 0.57 out
of sample -- it was memorising noise. Logistic regression reaches 0.66 held-out, and an
oracle scored on the data generator's own cancellation probabilities reaches 0.664. In
other words the simple model is within 0.002 of the information ceiling: whether a
particular block gets cancelled is mostly irreducible, and no amount of model capacity
will recover it.

Treat the output as a weak prior, not a prediction. It is good enough to rank fragile
slots against robust ones and no better, which is all the scheduler asks of it.

Note that `inside_corridor` is a feature, and it is a *decision*, not an observation.
The same task therefore carries a different cancellation risk depending on where the
optimiser puts it -- which is the coupling we want to expose to the planner.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ..domain import MaintenanceTask
from ..generator import HistoricalBlock, _is_monsoon

FEATURES = ["night_work", "monsoon", "inside_corridor", "has_machine",
            "demanded_duration_min", "gang_size"]

FEATURE_LABEL = {
    "night_work": "night working",
    "monsoon": "monsoon season",
    "inside_corridor": "inside the corridor",
    "has_machine": "needs plant",
    "demanded_duration_min": "demanded duration",
    "gang_size": "gang size",
}


def _row(night: bool, monsoon: bool, inside: bool, machine: str,
         demanded: int, gang: int) -> dict:
    return {
        "night_work": int(night),
        "monsoon": int(monsoon),
        "inside_corridor": int(inside),
        "has_machine": int(machine != "NONE"),
        "demanded_duration_min": demanded,
        "gang_size": gang,
    }


def _frame(history: list[HistoricalBlock]) -> pd.DataFrame:
    rows = []
    for h in history:
        r = _row(h.night_work, h.monsoon, h.inside_corridor, h.machine.value,
                 h.demanded_duration_min, h.gang_size)
        r["cancelled"] = int(h.was_cancelled)
        rows.append(r)
    return pd.DataFrame(rows)


class CancellationModel:
    def __init__(self, random_state: int = 0):
        self.random_state = random_state
        self.model: Pipeline | None = None
        self.training_report: dict[str, float] = {}

    def fit(self, history: list[HistoricalBlock]) -> "CancellationModel":
        df = _frame(history)
        X, y = df[FEATURES], df["cancelled"]

        self.model = Pipeline([
            ("scale", StandardScaler()),
            ("lr", LogisticRegression(max_iter=1000, random_state=self.random_state)),
        ])
        self.model.fit(X, y)

        from sklearn.metrics import roc_auc_score
        self.training_report = {
            "blocks_trained_on": float(len(df)),
            "base_cancellation_rate": float(y.mean()),
            "in_sample_auc": float(roc_auc_score(y, self.model.predict_proba(X)[:, 1])),
        }
        return self

    def coefficients(self) -> dict[str, float]:
        """Readable drivers, which is half the reason for choosing this model."""
        if self.model is None:
            return {}
        lr: LogisticRegression = self.model.named_steps["lr"]
        return {
            FEATURE_LABEL.get(f, f): round(float(c), 3)
            for f, c in zip(FEATURES, lr.coef_[0])
        }

    def predict(self, tasks: list[MaintenanceTask], inside_corridor: bool = True) -> None:
        """Write a daytime/day-zero prior. Solved blocks carry actual placement scores."""
        if self.model is None:
            raise RuntimeError("CancellationModel.fit must be called before predict")

        X = pd.DataFrame([
            _row(False, _is_monsoon(0),
                 inside_corridor, t.machine.value, t.demanded_duration_min, t.gang_size)
            for t in tasks
        ])[FEATURES]

        p = self.model.predict_proba(X)[:, 1]
        for i, t in enumerate(tasks):
            t.cancellation_risk = round(float(p[i]), 4)

    def risk_delta_outside_corridor(self, tasks: list[MaintenanceTask]) -> float:
        """Mean increase in cancellation risk from placing work outside the corridor.

        Reported to the planner as the operational cost of leaving the corridor,
        separately from the traffic cost of the paths themselves.
        """
        if self.model is None:
            return 0.0
        self.predict(tasks, inside_corridor=True)
        inside = np.array([t.cancellation_risk or 0.0 for t in tasks])
        self.predict(tasks, inside_corridor=False)
        outside = np.array([t.cancellation_risk or 0.0 for t in tasks])
        # Leave the tasks carrying the in-corridor figure, which is the default plan.
        self.predict(tasks, inside_corridor=True)
        return float(np.mean(outside - inside))

    def probabilities(self, tasks: list[MaintenanceTask], start_min: int,
                      end_min: int, inside_corridor: bool) -> list[float]:
        """Score the actual window, not the task's permission to work at night."""
        if self.model is None:
            raise RuntimeError("CancellationModel.fit must be called first")
        if not tasks:
            return []
        day = start_min // 1440
        night = (start_min % 1440 < 360 or end_min > day * 1440 + 1080)
        X = pd.DataFrame([
            _row(night, _is_monsoon(day), inside_corridor, t.machine.value,
                 t.demanded_duration_min, t.gang_size) for t in tasks
        ])[FEATURES]
        return self.model.predict_proba(X)[:, 1].tolist()

    def candidate_risks(self, tasks, candidates) -> dict[tuple[str, int], float]:
        """Batch inference across eligible task/window pairs for the objective."""
        from ..optimizer.cpsat import _eligible
        pairs, rows = [], []
        for c in candidates:
            night = c.start_min % 1440 < 360 or c.end_min > c.day * 1440 + 1080
            for t in tasks:
                if _eligible(t, c):
                    pairs.append((t.id, c.id))
                    rows.append(_row(night, _is_monsoon(c.day), c.inside_corridor,
                                     t.machine.value, t.demanded_duration_min, t.gang_size))
        if not rows:
            return {}
        values = self.model.predict_proba(pd.DataFrame(rows)[FEATURES])[:, 1]
        return dict(zip(pairs, map(float, values)))

    def score_plan(self, plan, tasks) -> None:
        """Keep scores with the plan so baseline and optimized results cannot overwrite each other."""
        by_id = {t.id: t for t in tasks}
        for b in plan.blocks:
            values = self.probabilities([by_id[tid] for tid in b.task_ids],
                                        b.start_min, b.end_min, b.inside_corridor)
            b.cancellation_risk = max(values, default=0.0)
