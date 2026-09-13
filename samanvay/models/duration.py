"""Block duration: what the work will actually take, not what was demanded.

Departments demand blocks in round figures -- two hours, three hours. Actual occupancy
is driven by quantity, gang strength, plant, and whether the job falls at night or in
the monsoon, and its distribution has a long right tail. A block that over-runs costs
paths; a block that under-runs wastes a withdrawn line.

So we fit two quantile models rather than one mean regressor:

    P50 -- the honest typical case, which is what the plan reports
    P90 -- the tail the line must actually be reserved against

Scheduling against P50 would guarantee that roughly half of all blocks over-run.

A quantile model fitted at alpha=0.9 does *not* reliably cover 90% of unseen data --
held-out coverage on this estate came out at 0.81, because the fitted quantile is
optimised on the training sample and the tail is exactly where trees extrapolate worst.
So the P90 is conformalised: a calibration split the model never fits on supplies an
empirical offset that restores the guarantee. Without it the scheduler reserves windows
that fail roughly one time in five instead of one in ten, and the whole "reserve against
P90" argument collapses.
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
    def __init__(self, random_state: int = 0, calibration_frac: float = 0.25,
                 target_coverage: float = 0.90):
        self.random_state = random_state
        self.calibration_frac = calibration_frac
        self.target_coverage = target_coverage
        self.p50: lgb.LGBMRegressor | None = None
        self.p90: lgb.LGBMRegressor | None = None
        self.p90_offset: float = 0.0
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

        rng = np.random.default_rng(self.random_state)
        idx = rng.permutation(len(df))
        n_cal = max(30, int(len(df) * self.calibration_frac))
        cal_idx, fit_idx = idx[:n_cal], idx[n_cal:]
        fit_df, cal_df = df.iloc[fit_idx], df.iloc[cal_idx]

        X, y = fit_df[FEATURES], fit_df["actual_duration_min"]
        self.p50 = self._make(0.5).fit(X, y, categorical_feature=CATEGORICAL)
        self.p90 = self._make(0.9).fit(X, y, categorical_feature=CATEGORICAL)

        # One-sided split-conformal calibration. The offset is the
        # ceil((n+1)*target)-th smallest residual on data the quantile never saw, which
        # is what makes the coverage claim hold out of sample rather than in it.
        cal_y = cal_df["actual_duration_min"].to_numpy()
        cal_p90 = self.p90.predict(cal_df[FEATURES])
        residuals = np.sort(cal_y - cal_p90)
        rank = int(np.ceil((len(residuals) + 1) * self.target_coverage)) - 1
        rank = min(max(rank, 0), len(residuals) - 1)
        self.p90_offset = float(max(0.0, residuals[rank]))

        pred50 = self.p50.predict(fit_df[FEATURES])
        self.training_report = {
            "blocks_trained_on": float(len(fit_df)),
            "calibration_blocks": float(len(cal_df)),
            "p90_conformal_offset_min": round(self.p90_offset, 1),
            "in_sample_p50_coverage": float((y <= pred50).mean()),
            "calibrated_p90_coverage_on_calibration_set": float(
                (cal_y <= cal_p90 + self.p90_offset).mean()
            ),
            "median_actual_min": float(df["actual_duration_min"].median()),
        }
        return self

    def predict_arrays(self, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """P50 and conformalised P90 for a prepared feature frame.

        Shared with `validation.py` so the validated model is literally the shipped one.
        """
        if self.p50 is None or self.p90 is None:
            raise RuntimeError("DurationModel.fit must be called first")
        p50 = np.maximum(20.0, self.p50.predict(X))
        p90 = np.maximum(p50 + 5.0, self.p90.predict(X) + self.p90_offset)
        return p50, p90

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
        """Write P50 and conformalised P90 onto each task, rounded up to whole slots."""

        X = self._task_frame(tasks)
        p50, p90 = self.predict_arrays(X)

        for i, t in enumerate(tasks):
            t.p50_duration_min = int(round(p50[i]))
            # Reserve whole slots: a block cannot be granted for 47 minutes.
            t.p90_duration_min = int(np.ceil(p90[i] / slot_min) * slot_min)

    def evaluate_against_truth(self, tasks: list[MaintenanceTask]) -> dict[str, float]:
        """Would the reservation actually have held?

        `p90_coverage` is the number that matters operationally: the share of tasks
        whose true duration fits inside the window we reserved. It should sit near
        0.90 -- materially below means we are still writing over-runs into the plan.

        The same quantities are reported a second time as burst rates, because that is
        the word the railway uses. A block worked beyond its sanctioned time has *burst*,
        and bursting is a counted, audited event: the CAG found 1,905 cases on the
        Delhi-Howrah route in 2018-19 alone, delaying 4,659 trains, with the cause
        recorded as "lack of proper coordination between men, machine and materials".
        A coverage figure of 0.12 and a burst rate of 88% are the same measurement, and
        only one of them is in the vocabulary of the person who has to sign the block.
        """
        scored = [t for t in tasks if t.p90_duration_min is not None]
        if not scored:
            return {}
        true = np.array([t.true_duration_min for t in scored], dtype=float)
        p50 = np.array([t.p50_duration_min for t in scored], dtype=float)
        p90 = np.array([t.p90_duration_min for t in scored], dtype=float)
        demanded = np.array([t.demanded_duration_min for t in scored], dtype=float)

        over_demanded = true - demanded
        burst_as_demanded = over_demanded > 0

        return {
            "p50_mae_min": float(np.mean(np.abs(true - p50))),
            "p90_coverage": float(np.mean(true <= p90)),
            "demanded_coverage": float(np.mean(true <= demanded)),
            "median_p90_minus_demanded_min": float(np.median(p90 - demanded)),
            # The same two numbers, in the railway's own words.
            "burst_rate_as_demanded": float(np.mean(burst_as_demanded)),
            "burst_rate_at_p90": float(np.mean(true > p90)),
            # How far the ones that do burst run over, which is what the section
            # controller has to absorb. Reported only when something bursts.
            "median_burst_min_as_demanded": (
                float(np.median(over_demanded[burst_as_demanded]))
                if burst_as_demanded.any() else 0.0
            ),
        }
