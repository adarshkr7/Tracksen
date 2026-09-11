"""Model behaviour, including the leakage guard.

The generator carries two ground-truth fields -- `true_duration_min` and
`true_days_to_failure` -- that exist only so evaluation can ask whether the plan got
there before the asset failed. If either ever reaches a feature set, every number in
the README becomes meaningless while still looking excellent. That is the one failure
mode worth an explicit test.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.stats import spearmanr

from samanvay.models import cancellation as cx
from samanvay.models import criticality as crit
from samanvay.models import duration as dur

GROUND_TRUTH_FIELDS = {"true_duration_min", "true_days_to_failure", "observed_days",
                       "actual_duration_min", "cancelled", "event", "label"}


# --------------------------------------------------------------------------- #
# Leakage
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("features,name", [
    (crit.FEATURES, "criticality"),
    (dur.FEATURES, "duration"),
    (cx.FEATURES, "cancellation"),
])
def test_no_ground_truth_in_any_feature_set(features, name):
    leaked = GROUND_TRUTH_FIELDS & set(features)
    assert not leaked, f"{name} model would train on ground truth: {leaked}"


def test_task_frames_never_expose_ground_truth(session):
    """The frames actually handed to the models at prediction time."""
    frame = session.duration._task_frame(session.tasks[:10])
    assert not (GROUND_TRUTH_FIELDS & set(frame.columns))


# --------------------------------------------------------------------------- #
# Criticality
# --------------------------------------------------------------------------- #

def test_criticality_is_bounded(session):
    values = [t.criticality for t in session.tasks]
    assert all(v is not None for v in values)
    assert min(values) >= 0.0
    assert max(values) <= 100.0


def test_criticality_has_real_spread(session):
    """It once saturated: the top fourteen rows all read exactly 100 and ranked nothing."""
    values = np.array([t.criticality for t in session.tasks])
    tied_at_top = int((values >= values.max() - 0.5).sum())
    assert tied_at_top <= max(3, len(values) // 20), (
        f"{tied_at_top} tasks tied at the maximum -- the index has saturated"
    )
    assert len(set(np.round(values, 1))) > len(values) * 0.5


def test_criticality_ranks_by_real_urgency(session):
    """Against simulator ground truth the model never saw. Not decoration."""
    crit_values = np.array([t.criticality for t in session.tasks])
    ttf = np.array([t.true_days_to_failure for t in session.tasks])
    rho, p = spearmanr(crit_values, -ttf)
    assert rho > 0.35, f"criticality barely tracks true urgency (rho={rho:.3f})"
    assert p < 0.01


# --------------------------------------------------------------------------- #
# Duration
# --------------------------------------------------------------------------- #

def test_p90_never_below_p50(session):
    for t in session.tasks:
        assert t.p90_duration_min >= t.p50_duration_min


def test_p90_is_reserved_in_whole_slots(session):
    from samanvay.domain import SLOT_MIN

    for t in session.tasks:
        assert t.p90_duration_min % SLOT_MIN == 0, (
            f"{t.id} reserves {t.p90_duration_min} min, not a whole slot"
        )


def test_conformal_offset_is_applied(session):
    """Without it, held-out P90 coverage sat at 0.81 against a 0.90 target."""
    assert session.duration.p90_offset >= 0.0
    report = session.duration.training_report
    assert "p90_conformal_offset_min" in report
    assert report["calibrated_p90_coverage_on_calibration_set"] >= 0.85


def test_p90_actually_covers_true_durations(session):
    """The operational claim: the window we reserve is the window the work fits in."""
    result = session.duration.evaluate_against_truth(session.tasks)
    assert result["p90_coverage"] >= 0.85, (
        f"P90 covers only {result['p90_coverage']:.2f} of true durations"
    )


def test_p90_beats_the_demanded_figure(session):
    """The headline duration finding. If this inverts, the argument is gone."""
    result = session.duration.evaluate_against_truth(session.tasks)
    assert result["p90_coverage"] > result["demanded_coverage"] + 0.3


# --------------------------------------------------------------------------- #
# Cancellation
# --------------------------------------------------------------------------- #

def test_cancellation_risk_is_a_probability(session):
    for t in session.tasks:
        assert 0.0 <= t.cancellation_risk <= 1.0


def test_leaving_the_corridor_raises_cancellation_risk(session):
    delta = session.cancellation.risk_delta_outside_corridor(session.tasks)
    assert delta > 0.0, "placing work outside the corridor should not look safer"


def test_cancellation_model_is_interpretable(session):
    """It is a logistic regression on purpose; the coefficients are part of the point."""
    coefs = session.cancellation.coefficients()
    assert coefs, "no readable coefficients"
    assert coefs["inside the corridor"] < 0, (
        "being inside the corridor should reduce cancellation risk"
    )


# --------------------------------------------------------------------------- #
# Traffic
# --------------------------------------------------------------------------- #

def test_traffic_cost_rises_with_window_length(session, sections):
    from samanvay.domain import Line

    sec = sections[0].id
    short = session.traffic.cost_of_block(sec, Line.UP, 8 * 60, 9 * 60)
    long = session.traffic.cost_of_block(sec, Line.UP, 8 * 60, 12 * 60)
    assert long >= short


def test_consequence_is_normalised(session, sections):
    from samanvay.domain import Line

    for s in sections:
        for line in (Line.UP, Line.DN):
            assert 0.0 <= session.traffic.consequence(s.id, line) <= 1.0
