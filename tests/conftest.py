"""Shared fixtures.

Fitting models and generating the estate costs a few seconds, and solving costs more,
so the expensive objects are session-scoped and built once. Individual tests assert
against them rather than rebuilding.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from samanvay.network import SECTIONS, generate_corridors, generate_timetable  # noqa: E402
from samanvay.optimizer.cpsat import OptimiserWeights, build_candidates  # noqa: E402
from samanvay.session import PlanningSession  # noqa: E402

# Small enough to keep the suite quick, large enough that the constraints actually bind.
TEST_DAYS = 5
TEST_TASKS = 90
TEST_SEED = 7
SOLVE_SECONDS = 8.0


@pytest.fixture(scope="session")
def session() -> PlanningSession:
    return PlanningSession(horizon_days=TEST_DAYS, n_tasks=TEST_TASKS, seed=TEST_SEED)


@pytest.fixture(scope="session")
def dataset(session):
    return session.ds


@pytest.fixture(scope="session")
def weights() -> OptimiserWeights:
    return OptimiserWeights()


@pytest.fixture(scope="session")
def solved(session, weights):
    """One optimised solve, reused by every invariant test."""
    return session.solve(weights=weights, time_limit_s=SOLVE_SECONDS)


@pytest.fixture(scope="session")
def plan(solved):
    return solved.plan


@pytest.fixture(scope="session")
def baseline(session, weights):
    return session.baseline(weights)


@pytest.fixture(scope="session")
def candidates(session):
    return session.base_candidates


@pytest.fixture(scope="session")
def traffic(session):
    return session.traffic


@pytest.fixture(scope="session")
def corridors(session):
    """The session's own corridors.

    Not a fresh `generate_corridors(TEST_DAYS)`: corridors are now placed against the
    traffic model, so a second set built without one would sit at different hours from
    the ones the candidates were enumerated from, and every test comparing the two would
    be quietly asserting against a plan nobody solved.
    """
    return session.corridors


@pytest.fixture(scope="session")
def timetable():
    return generate_timetable(TEST_DAYS)


@pytest.fixture(scope="session")
def sections():
    return SECTIONS
