"""Cancellation risk: will this block, if sanctioned, actually run?

A block that is sanctioned and then cancelled has consumed planning capacity and
returned nothing -- the paths were kept clear, the gang was booked, and no risk was
retired. Two uses:

  * avoid placing the most critical work into the most fragile slots, and
  * keep a standby queue, so a block released at short notice is filled, not lost.

Note that `inside_corridor` is a feature, and it is a *decision*, not an observation.
That means the same task carries a different cancellation risk depending on where the
optimiser puts it -- which is exactly the coupling we want to expose to the planner.
"""

from __future__ import annotations

import lightgbm as lgb
import pandas as pd

from ..domain import MaintenanceTask
from ..generator import HistoricalBlock, _is_monsoon

NUMERIC = ["night_work", "monsoon", "inside_corridor", "demanded_duration_min",
           "gang_size"]
CATEGORICAL = ["task_type", "machine"]
FEATURES = NUMERIC + CATEGORICAL


def _frame(history: list[HistoricalBlock]) -> pd.DataFrame:
    rows = [
        {
            "night_work": int(h.night_work),
            "monsoon": int(h.monsoon),
            "inside_corridor": int(h.inside_corridor),
            "demanded_duration_min": h.demanded_duration_min,
            "gang_size": h.gang_size,
            "task_type": h.task_type,
            "machine": h.machine.value,
            "cancelled": int(h.was_cancelled),
        }
        for h in history
    ]
    df = pd.DataFrame(rows)
    for c in CATEGORICAL:
        df[c] = df[c].astype("category")
    return df


class CancellationModel:
    def __init__(self, random_state: int = 0):
        self.random_state = random_state
        self.model: lgb.LGBMClassifier | None = None
        self._categories: dict[str, pd.Index] = {}
        self.training_report: dict[str, float] = {}

    def fit(self, history: list[HistoricalBlock]) -> "CancellationModel":
        df = _frame(history)
        for c in CATEGORICAL:
            self._categories[c] = df[c].cat.categories

        X, y = df[FEATURES], df["cancelled"]
        self.model = lgb.LGBMClassifier(
            n_estimators=220,
            learning_rate=0.05,
            num_leaves=16,
            min_child_samples=30,
            random_state=self.random_state,
            verbose=-1,
        )
        self.model.fit(X, y, categorical_feature=CATEGORICAL)

        from sklearn.metrics import roc_auc_score
        self.training_report = {
            "blocks_trained_on": float(len(df)),
            "base_cancellation_rate": float(y.mean()),
            "in_sample_auc": float(roc_auc_score(y, self.model.predict_proba(X)[:, 1])),
        }
        return self

    def predict(self, tasks: list[MaintenanceTask], inside_corridor: bool = True) -> None:
        """Write cancellation risk onto each task for a given placement assumption."""
        if self.model is None:
            raise RuntimeError("CancellationModel.fit must be called before predict")

        rows = [
            {
                "night_work": int(t.night_work_allowed),
                "monsoon": int(_is_monsoon(max(0, t.raised_day))),
                "inside_corridor": int(inside_corridor),
                "demanded_duration_min": t.demanded_duration_min,
                "gang_size": t.gang_size,
                "task_type": t.task_type,
                "machine": t.machine.value,
            }
            for t in tasks
        ]
        X = pd.DataFrame(rows)
        for c in CATEGORICAL:
            X[c] = pd.Categorical(X[c], categories=self._categories[c])

        p = self.model.predict_proba(X[FEATURES])[:, 1]
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
        inside = [t.cancellation_risk or 0.0 for t in tasks]
        self.predict(tasks, inside_corridor=False)
        outside = [t.cancellation_risk or 0.0 for t in tasks]
        # Leave the tasks carrying the in-corridor figure, which is the default plan.
        self.predict(tasks, inside_corridor=True)
        return float(sum(o - i for o, i in zip(outside, inside)) / max(1, len(tasks)))
