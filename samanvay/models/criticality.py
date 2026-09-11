"""The Criticality Index: how much it matters that this task happens soon.

    Criticality = P(failure within H) x Urgency(E[time to failure]) x Consequence

Two models sit behind the first term, because "will it fail" and "when will it fail"
are different questions and scheduling needs both:

  * a gradient-boosted classifier for P(failure within H days), and
  * a Cox proportional-hazards model for expected time-to-failure.

The training data is right-censored -- most defects are attended *before* they fail, so
we never observe their failure time. The classifier handles this by complete-case
selection within the horizon (see `_label_within_horizon`); Cox handles it natively,
which is the reason it is here rather than a plain regression on observed days.

Every score carries a SHAP attribution. That is not decoration: the system asks a
divisional officer to defer one department's work in favour of another's, and a score
he cannot interrogate is a score he will not use.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import lightgbm as lgb
import numpy as np
import pandas as pd
import shap
from lifelines import CoxPHFitter

from ..domain import MaintenanceTask
from ..generator import DUE_INTERVAL_DAYS, HistoricalDefect
from .traffic import TrafficModel

# How far ahead "before the next realistic opportunity" reaches, in days. A block for
# routine work is rarely available sooner than this on a dense corridor.
DEFAULT_RISK_HORIZON_DAYS = 30

NUMERIC_FEATURES = [
    "defect_severity",
    "age_years",
    "gmt",
    "curvature_deg",
    "gradient_permille",
    "repeat_failures",
    "days_overdue",
    "is_defect",
]
CATEGORICAL_FEATURES = ["asset_class", "task_type"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

# Plain-language names for the attribution chips shown against each task.
FEATURE_LABEL = {
    "defect_severity": "defect severity",
    "age_years": "asset age",
    "gmt": "traffic tonnage (GMT)",
    "curvature_deg": "curvature",
    "gradient_permille": "gradient",
    "repeat_failures": "repeat failures at this km",
    "days_overdue": "days overdue",
    "is_defect": "reactive defect",
    "asset_class": "asset class",
    "task_type": "work type",
}


@dataclass
class CriticalityBreakdown:
    """What went into one task's score, in a form a planner can argue with."""

    task_id: str
    criticality: float
    p_failure: float
    expected_days_to_failure: float
    consequence: float
    top_reasons: list[tuple[str, float]]

    def reason_text(self, limit: int = 3) -> str:
        parts = []
        for name, contrib in self.top_reasons[:limit]:
            sign = "+" if contrib >= 0 else "-"
            parts.append(f"{sign}{abs(contrib):.2f} {name}")
        return ", ".join(parts)


def _history_frame(history: list[HistoricalDefect]) -> pd.DataFrame:
    rows = [
        {
            "defect_severity": h.defect_severity,
            "age_years": h.age_years,
            "gmt": h.gmt,
            "curvature_deg": h.curvature_deg,
            "gradient_permille": h.gradient_permille,
            "repeat_failures": h.repeat_failures,
            "days_overdue": h.days_overdue_at_attention,
            "is_defect": int(h.is_defect),
            "asset_class": h.asset_class.value,
            "task_type": h.task_type,
            "observed_days": h.observed_days,
            "event": int(not h.censored),
        }
        for h in history
    ]
    df = pd.DataFrame(rows)
    for c in CATEGORICAL_FEATURES:
        df[c] = df[c].astype("category")
    return df


def _label_within_horizon(df: pd.DataFrame, horizon_days: int) -> pd.DataFrame:
    """Complete-case labelling for "failed within H days".

    An observation is usable only when the outcome at H is actually known:

      * it failed at or before H                  -> 1
      * it was still intact beyond H              -> 0  (censored or not)
      * it was censored *before* H                -> unknown, dropped

    Dropping the third group biases the sample towards assets that were left alone
    longer. We accept that and state it rather than silently labelling them zero,
    which would train the model to under-predict risk on exactly the tasks that get
    attended promptly today.
    """
    failed_within = (df["event"] == 1) & (df["observed_days"] <= horizon_days)
    survived_past = df["observed_days"] > horizon_days
    usable = failed_within | survived_past

    out = df.loc[usable].copy()
    out["label"] = failed_within.loc[usable].astype(int)
    return out


class CriticalityModel:
    """Fits the risk models once, then scores any number of pending tasks."""

    def __init__(self, risk_horizon_days: int = DEFAULT_RISK_HORIZON_DAYS,
                 random_state: int = 0):
        self.risk_horizon_days = risk_horizon_days
        self.random_state = random_state
        self.classifier: lgb.LGBMClassifier | None = None
        self.cox: CoxPHFitter | None = None
        self._explainer: shap.TreeExplainer | None = None
        self._categories: dict[str, pd.Index] = {}
        self._cox_columns: list[str] = []
        self.training_report: dict[str, float] = {}

    # ------------------------------------------------------------------ #
    # Fitting
    # ------------------------------------------------------------------ #

    def fit(self, history: list[HistoricalDefect]) -> "CriticalityModel":
        df = _history_frame(history)
        for c in CATEGORICAL_FEATURES:
            self._categories[c] = df[c].cat.categories

        labelled = _label_within_horizon(df, self.risk_horizon_days)
        X = labelled[FEATURES]
        y = labelled["label"]

        self.classifier = lgb.LGBMClassifier(
            n_estimators=260,
            learning_rate=0.05,
            num_leaves=24,
            min_child_samples=25,
            subsample=0.9,
            colsample_bytree=0.9,
            random_state=self.random_state,
            verbose=-1,
        )
        self.classifier.fit(X, y, categorical_feature=CATEGORICAL_FEATURES)
        self._explainer = shap.TreeExplainer(self.classifier)

        # Cox uses the full sample, censoring included -- that is the point of it.
        cox_cols = [c for c in NUMERIC_FEATURES]
        cox_df = df[cox_cols + ["observed_days", "event"]].copy()
        cox_df["observed_days"] = cox_df["observed_days"].clip(lower=0.5)
        # Drop zero-variance columns; Cox will not invert a singular design matrix.
        keep = [c for c in cox_cols if cox_df[c].nunique() > 1]
        self._cox_columns = keep

        self.cox = CoxPHFitter(penalizer=0.1)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.cox.fit(
                cox_df[keep + ["observed_days", "event"]],
                duration_col="observed_days",
                event_col="event",
            )

        self.training_report = {
            "defect_records": float(len(df)),
            "usable_for_classifier": float(len(labelled)),
            "dropped_as_censored_early": float(len(df) - len(labelled)),
            "positive_rate": float(y.mean()),
            "cox_concordance": float(self.cox.concordance_index_),
        }
        return self

    # ------------------------------------------------------------------ #
    # Scoring
    # ------------------------------------------------------------------ #

    def _task_frame(self, tasks: list[MaintenanceTask], assets_by_id: dict,
                    repeat_failures: dict[tuple[str, int], int],
                    today: int) -> pd.DataFrame:
        rows = []
        for t in tasks:
            a = assets_by_id[t.asset_id]
            rows.append({
                "defect_severity": t.defect_severity,
                "age_years": a.age_years,
                "gmt": a.gmt,
                "curvature_deg": a.curvature_deg,
                "gradient_permille": a.gradient_permille,
                "repeat_failures": repeat_failures.get(
                    (t.section_id, int(t.chainage_km)), 0
                ),
                "days_overdue": t.days_overdue(today),
                "is_defect": int(t.is_defect),
                "asset_class": t.asset_class.value,
                "task_type": t.task_type,
            })
        df = pd.DataFrame(rows)
        for c in CATEGORICAL_FEATURES:
            df[c] = pd.Categorical(df[c], categories=self._categories[c])
        return df

    def score(
        self,
        tasks: list[MaintenanceTask],
        assets_by_id: dict,
        traffic: TrafficModel,
        repeat_failures: dict[tuple[str, int], int] | None = None,
        today: int = 0,
    ) -> list[CriticalityBreakdown]:
        """Score every task, write `criticality` onto it, and return the breakdowns."""
        if self.classifier is None or self.cox is None:
            raise RuntimeError("CriticalityModel.fit must be called before score")

        repeat_failures = repeat_failures or {}
        X = self._task_frame(tasks, assets_by_id, repeat_failures, today)

        p_fail = self.classifier.predict_proba(X[FEATURES])[:, 1]

        cox_X = X[self._cox_columns].astype(float)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            expected_days = self.cox.predict_expectation(cox_X).to_numpy()

        shap_values = self._explainer.shap_values(X[FEATURES])
        if isinstance(shap_values, list):          # older shap returns one array per class
            shap_values = shap_values[1]
        if shap_values.ndim == 3:                  # (n, features, classes)
            shap_values = shap_values[:, :, 1]

        out: list[CriticalityBreakdown] = []
        for i, t in enumerate(tasks):
            consequence = traffic.consequence(t.section_id, t.line)

            # Probability alone saturates: on a backlog of genuine defects most tasks
            # carry p_fail near 1.0, and a queue where the top forty rows all read 100
            # ranks nothing. The Cox expectation supplies the missing dimension --
            # *when* -- so a rail flaw due to go in eight days outranks one due in sixty
            # even though both are certain to fail eventually.
            horizon = float(self.risk_horizon_days)
            urgency = horizon / (horizon + max(0.0, float(expected_days[i])))

            # Consequence never zeroes a score -- a defect on a quiet line still has
            # to be attended. It scales it between a floor and full weight.
            score = 100.0 * float(p_fail[i]) * urgency * (0.35 + 0.65 * consequence)
            t.criticality = round(float(score), 2)

            contribs = sorted(
                zip(FEATURES, shap_values[i]),
                key=lambda kv: abs(kv[1]),
                reverse=True,
            )
            reasons = [(FEATURE_LABEL.get(k, k), float(v)) for k, v in contribs[:5]]
            t.attribution = {FEATURE_LABEL.get(k, k): float(v) for k, v in contribs[:5]}

            out.append(
                CriticalityBreakdown(
                    task_id=t.id,
                    criticality=t.criticality,
                    p_failure=float(p_fail[i]),
                    expected_days_to_failure=float(expected_days[i]),
                    consequence=consequence,
                    top_reasons=reasons,
                )
            )
        return out

    # ------------------------------------------------------------------ #
    # Honesty check
    # ------------------------------------------------------------------ #

    def evaluate_against_truth(self, tasks: list[MaintenanceTask]) -> dict[str, float]:
        """Does the score actually rank by true time-to-failure?

        The generator knows each asset's true days-to-failure; the model never sees it.
        Spearman correlation between criticality and -true_days_to_failure tells us
        whether the ranking is real or decorative.
        """
        from scipy.stats import spearmanr

        scored = [t for t in tasks if t.criticality is not None]
        if len(scored) < 3:
            return {}
        crit = np.array([t.criticality for t in scored])
        ttf = np.array([t.true_days_to_failure for t in scored])
        rho, p = spearmanr(crit, -ttf)
        return {"spearman_rho_vs_true_urgency": float(rho), "p_value": float(p)}


def urgency_deadline_day(task: MaintenanceTask, horizon_days: int) -> int:
    """The day by which this task should be done, for the overdue penalty.

    Statutory due date, clipped into the horizon. Already-overdue work lands on day 0
    and drags the penalty from the first day of the plan.
    """
    interval = DUE_INTERVAL_DAYS.get(task.task_type, 30)
    due = task.due_day if task.due_day is not None else interval
    return int(min(max(due, 0), horizon_days - 1))
