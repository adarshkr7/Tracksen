"""Block duration: what the work will actually take, not what was demanded.

Departments demand blocks in round figures -- two hours, three hours. Actual occupancy
is driven by quantity, gang strength, plant, and whether the job falls at night or in
the monsoon, and its distribution has a long right tail. A block that over-runs costs
paths; a block that under-runs wastes a withdrawn line.

So we fit two quantile models rather than one mean regressor:

    P50 -- the honest typical case, which is what the plan reports
    P90 -- the tail the line must actually be reserved against

Scheduling against P50 would guarantee that roughly half of all blocks over-run.
"""

from __future__ import annotations

import lightgbm as lgb
import numpy as np
import pandas as pd

from ..domain import MachineType, MaintenanceTask
from ..generator import HistoricalBlock, _is_monsoon

NUMERIC = ["quantity", "gang_size", "demanded_duration_min", "defect_severity",
           "night_work", "monsoon"]
CATEGORICAL = ["task_type", "asset_class", "machine"]
FEATURES = NUMERIC + CATEGORICAL


def _history_frame(history: list[HistoricalBlock]) -> pd.DataFrame:
    rows = [
        {
            "quantity": h.quantity,
            "gang_size": h.gang_size,
            "demanded_duration_min": h.demanded_duration_min,
            "defect_severity": h.defect_severity,
            "night_work": int(h.night_work),
            "monsoon": int(h.monsoon),
            "task_type": h.task_type,
            "asset_class": h.asset_class.value,
            "machine": h.machine.value,
            "actual_duration_min": h.actual_duration_min,
        }
        # A cancelled block never ran, so it carries no duration to learn from.
        for h in history if not h.was_cancelled
    ]
    df = pd.DataFrame(rows)
    for c in CATEGORICAL:
        df[c] = df[c].astype("category")
    return df


class DurationModel:
    def __init__(self, random_state: int = 0):
        self.random_state = random_state
        self.p50: lgb.LGBMRegressor | None = None
        self.p90: lgb.LGBMRegressor | None = None
        self._categories: dict[str, pd.Index] = {}
        self.training_report: dict[str, float] = {}

    def _make(self, alpha: float) -> lgb.LGBMRegressor:
        return lgb.LGBMRegressor(
            objective="quantile",
            alpha=alpha,
            n_estimators=320,
            learning_rate=0.05,
            num_leaves=24,
            min_child_samples=20,
            random_state=self.random_state,
            verbose=-1,
        )

    def fit(self, history: list[HistoricalBlock]) -> "DurationModel":
        df = _history_frame(history)
        for c in CATEGORICAL:
            self._categories[c] = df[c].cat.categories

        X, y = df[FEATURES], df["actual_duration_min"]
        self.p50 = self._make(0.5).fit(X, y, categorical_feature=CATEGORICAL)
        self.p90 = self._make(0.9).fit(X, y, categorical_feature=CATEGORICAL)

        pred50 = self.p50.predict(X)
        pred90 = self.p90.predict(X)
        self.training_report = {
            "blocks_trained_on": float(len(df)),
            "in_sample_p50_coverage": float((y <= pred50).mean()),
            "in_sample_p90_coverage": float((y <= pred90).mean()),
            "median_actual_min": float(y.median()),
        }
        return self

    def _task_frame(self, tasks: list[MaintenanceTask]) -> pd.DataFrame:
        rows = [
            {
                "quantity": t.quantity,
                "gang_size": t.gang_size,
                "demanded_duration_min": t.demanded_duration_min,
                "defect_severity": t.defect_severity,
                "night_work": int(t.night_work_allowed),
                "monsoon": int(_is_monsoon(max(0, t.raised_day))),
                "task_type": t.task_type,
                "asset_class": t.asset_class.value,
                "machine": t.machine.value,
            }
            for t in tasks
        ]
        df = pd.DataFrame(rows)
        for c in CATEGORICAL:
            df[c] = pd.Categorical(df[c], categories=self._categories[c])
        return df

    def predict(self, tasks: list[MaintenanceTask], slot_min: int = 15) -> None:
        """Write P50 and P90 onto each task, rounded up to whole planning slots."""
        if self.p50 is None or self.p90 is None:
            raise RuntimeError("DurationModel.fit must be called before predict")

        X = self._task_frame(tasks)
        p50 = np.maximum(20.0, self.p50.predict(X))
        p90 = np.maximum(p50 + 5.0, self.p90.predict(X))

        for i, t in enumerate(tasks):
            t.p50_duration_min = int(round(p50[i]))
            # Reserve whole slots: a block cannot be granted for 47 minutes.
            t.p90_duration_min = int(np.ceil(p90[i] / slot_min) * slot_min)

    def evaluate_against_truth(self, tasks: list[MaintenanceTask]) -> dict[str, float]:
        """Would the reservation actually have held?

        `p90_coverage` is the number that matters operationally: the share of tasks
        whose true duration fits inside the window we reserved. It should sit near
        0.90 -- materially below means we are still writing over-runs into the plan.
        """
        scored = [t for t in tasks if t.p90_duration_min is not None]
        if not scored:
            return {}
        true = np.array([t.true_duration_min for t in scored], dtype=float)
        p50 = np.array([t.p50_duration_min for t in scored], dtype=float)
        p90 = np.array([t.p90_duration_min for t in scored], dtype=float)
        demanded = np.array([t.demanded_duration_min for t in scored], dtype=float)

        return {
            "p50_mae_min": float(np.mean(np.abs(true - p50))),
            "p90_coverage": float(np.mean(true <= p90)),
            "demanded_coverage": float(np.mean(true <= demanded)),
            "median_p90_minus_demanded_min": float(np.median(p90 - demanded)),
        }
