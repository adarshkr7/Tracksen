"""Held-out validation for the four models.

Every diagnostic the models report from `fit()` is in-sample, and in-sample numbers on
gradient-boosted trees are close to meaningless — a model with enough leaves can memorise
its training set and report an AUC of 0.99 while generalising badly. This module refits
each model on k-1 folds and scores it on the fold it never saw.

Two of these matter more than the rest:

  * **P90 coverage on held-out data.** The scheduler reserves the line against the P90
    prediction. If out-of-sample coverage is materially below 0.90, the plan is writing
    over-runs into the timetable and the central duration claim is wrong.
  * **Cox concordance out-of-sample.** The criticality index folds in the Cox expectation
    as its urgency term, so if that ordering does not generalise, neither does the queue.

One thing already out-of-sample and worth saying so: the Spearman check of criticality
against true time-to-failure runs on the *pending* tasks, which are a different population
from the historical defects the model trained on. That number was never in-sample.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold

from .generator import (
    HistoricalBlock,
    HistoricalDefect,
    cancellation_probability,
)
from .models import cancellation as cx
from .models import criticality as crit
from .models import duration as dur

DEFAULT_FOLDS = 5
DEFAULT_SEED = 0


@dataclass
class FoldScores:
    """Per-fold values for one metric, reported as mean ± std."""

    name: str
    values: list[float] = field(default_factory=list)
    note: str = ""

    @property
    def mean(self) -> float:
        return float(np.mean(self.values)) if self.values else float("nan")

    @property
    def std(self) -> float:
        return float(np.std(self.values)) if self.values else float("nan")

    def as_dict(self) -> dict:
        return {
            "metric": self.name,
            "mean": round(self.mean, 4),
            "std": round(self.std, 4),
            "folds": [round(v, 4) for v in self.values],
            "note": self.note,
        }


def _folds(n: int, k: int, seed: int):
    return KFold(n_splits=k, shuffle=True, random_state=seed).split(np.arange(n))


# --------------------------------------------------------------------------- #
# Criticality
# --------------------------------------------------------------------------- #

def validate_criticality(
    history: list[HistoricalDefect],
    horizon_days: int = crit.DEFAULT_RISK_HORIZON_DAYS,
    k: int = DEFAULT_FOLDS,
    seed: int = DEFAULT_SEED,
) -> list[FoldScores]:
    """Out-of-sample AUC and Brier for the risk classifier; concordance for Cox."""
    from lifelines import CoxPHFitter
    from lifelines.utils import concordance_index
    from sklearn.metrics import brier_score_loss, roc_auc_score

    import lightgbm as lgb

    df = crit._history_frame(history)
    labelled = crit._label_within_horizon(df, horizon_days).reset_index(drop=True)

    auc = FoldScores("classifier AUC (held-out)")
    brier = FoldScores("classifier Brier (held-out)",
                       note="lower is better; 0.25 is a coin flip at a 50% base rate")
    base = FoldScores("majority-class accuracy", note="the bar the classifier must clear")
    conc = FoldScores("Cox concordance (held-out)")

    for tr, te in _folds(len(labelled), k, seed):
        train, test = labelled.iloc[tr], labelled.iloc[te]
        if test["label"].nunique() < 2:
            continue

        model = lgb.LGBMClassifier(
            n_estimators=260, learning_rate=0.05, num_leaves=24,
            min_child_samples=25, subsample=0.9, colsample_bytree=0.9,
            random_state=seed, verbose=-1,
        )
        model.fit(train[crit.FEATURES], train["label"],
                  categorical_feature=crit.CATEGORICAL_FEATURES)
        p = model.predict_proba(test[crit.FEATURES])[:, 1]

        auc.values.append(roc_auc_score(test["label"], p))
        brier.values.append(brier_score_loss(test["label"], p))
        base.values.append(max(test["label"].mean(), 1 - test["label"].mean()))

    # Cox on the full censored sample -- its own folds, since it uses rows the
    # classifier drops as ambiguous.
    cox_cols = [c for c in crit.NUMERIC_FEATURES if df[c].nunique() > 1]
    cox_df = df[cox_cols + ["observed_days", "event"]].copy()
    cox_df["observed_days"] = cox_df["observed_days"].clip(lower=0.5)
    cox_df = cox_df.reset_index(drop=True)

    for tr, te in _folds(len(cox_df), k, seed):
        train, test = cox_df.iloc[tr], cox_df.iloc[te]
        if test["event"].sum() < 2:
            continue
        fitter = CoxPHFitter(penalizer=0.1)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fitter.fit(train, duration_col="observed_days", event_col="event")
            risk = fitter.predict_partial_hazard(test[cox_cols])
        conc.values.append(
            concordance_index(test["observed_days"], -risk, test["event"])
        )

    return [auc, brier, base, conc]


# --------------------------------------------------------------------------- #
# Duration
# --------------------------------------------------------------------------- #

def validate_duration(
    history: list[HistoricalBlock],
    k: int = DEFAULT_FOLDS,
    seed: int = DEFAULT_SEED,
) -> list[FoldScores]:
    """The one that matters: does the conformalised P90 reservation hold on unseen blocks?

    Fits the shipped `DurationModel` -- conformal calibration and all -- on k-1 folds and
    scores the fold it never saw. Before calibration this sat at 0.81 against a 0.90
    target, which meant roughly one block in five would over-run its reservation.
    """
    from .models.duration import DurationModel

    blocks = [h for h in history if not h.was_cancelled]

    cov90 = FoldScores("P90 coverage (held-out, conformalised)",
                       note="target 0.90 -- the share of blocks whose true duration "
                            "fits inside the window we reserve")
    cov50 = FoldScores("P50 coverage (held-out)", note="target 0.50")
    mae = FoldScores("P50 absolute error, minutes (held-out)")
    naive = FoldScores("naive median-baseline MAE, minutes",
                       note="predicting the training median for every block")
    offset = FoldScores("conformal offset applied, minutes")

    for tr, te in _folds(len(blocks), k, seed):
        train = [blocks[i] for i in tr]
        test = [blocks[i] for i in te]

        model = DurationModel(random_state=seed).fit(train)
        test_df = dur._history_frame(test)
        pred50, pred90 = model.predict_arrays(test_df[dur.FEATURES])
        y = test_df["actual_duration_min"].to_numpy()

        cov50.values.append(float(np.mean(y <= pred50)))
        cov90.values.append(float(np.mean(y <= pred90)))
        mae.values.append(float(np.mean(np.abs(y - pred50))))
        train_median = float(pd.DataFrame(
            {"d": [b.actual_duration_min for b in train]})["d"].median())
        naive.values.append(float(np.mean(np.abs(y - train_median))))
        offset.values.append(model.p90_offset)

    return [cov90, cov50, mae, naive, offset]


# --------------------------------------------------------------------------- #
# Cancellation
# --------------------------------------------------------------------------- #

def validate_cancellation(
    history: list[HistoricalBlock],
    k: int = DEFAULT_FOLDS,
    seed: int = DEFAULT_SEED,
) -> list[FoldScores]:
    """Fits the shipped logistic model, and reports the ceiling it is measured against.

    The oracle row scores the data generator's own cancellation probabilities. When the
    model sits within a whisker of it, the remaining error is irreducible and reaching
    for a bigger model would only buy overfitting -- which is exactly what the boosted
    version was doing before this check existed.
    """
    from sklearn.metrics import brier_score_loss, roc_auc_score

    from .models.cancellation import CancellationModel

    df = cx._frame(history).reset_index(drop=True)

    auc = FoldScores("cancellation AUC (held-out)")
    brier = FoldScores("cancellation Brier (held-out)", note="lower is better")
    oracle = FoldScores("ORACLE AUC (generator's true probability)",
                        note="the information ceiling -- no model can beat this")
    rate = FoldScores("base cancellation rate")

    for tr, te in _folds(len(history), k, seed):
        train = [history[i] for i in tr]
        test = [history[i] for i in te]
        y = np.array([int(h.was_cancelled) for h in test])
        if len(set(y.tolist())) < 2:
            continue

        model = CancellationModel(random_state=seed).fit(train)
        X = cx._frame(test)[cx.FEATURES]
        p = model.model.predict_proba(X)[:, 1]

        auc.values.append(roc_auc_score(y, p))
        brier.values.append(brier_score_loss(y, p))
        oracle.values.append(roc_auc_score(
            y, [cancellation_probability(h.inside_corridor, h.night_work,
                                          h.monsoon, h.machine.value != "NONE")
                for h in test]))
        rate.values.append(float(y.mean()))

    return [auc, oracle, brier, rate]


# --------------------------------------------------------------------------- #

def validate_all(dataset, k: int = DEFAULT_FOLDS, seed: int = DEFAULT_SEED) -> dict:
    """Run every model's held-out check and return a serialisable report."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        report = {
            "folds": k,
            "seed": seed,
            "criticality": [s.as_dict() for s in
                            validate_criticality(dataset.history_defects, k=k, seed=seed)],
            "duration": [s.as_dict() for s in
                         validate_duration(dataset.history_blocks, k=k, seed=seed)],
            "cancellation": [s.as_dict() for s in
                             validate_cancellation(dataset.history_blocks, k=k, seed=seed)],
        }
    return report


def format_report(report: dict) -> str:
    lines = [f"{report['folds']}-fold cross-validation (seed {report['seed']})", ""]
    for section in ("criticality", "duration", "cancellation"):
        lines.append(section.upper())
        for row in report[section]:
            lines.append(f"  {row['metric']:<44} {row['mean']:.3f} ± {row['std']:.3f}")
            if row["note"]:
                lines.append(f"      {row['note']}")
        lines.append("")
    return "\n".join(lines)
