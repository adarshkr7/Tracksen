"""Payload shape, and the guarantee that both producers emit the same one.

The web client parses `plan.json` from the pipeline *and* the response from
`/api/resolve`. They already drifted once -- `run_pipeline.py` carried its own copy of
the builder while `serialize.py` claimed to be the only one. These tests pin the shape
so the client cannot be broken silently from either side.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REQUIRED_TOP_LEVEL = {
    "meta", "model_checks", "metrics", "stations", "sections", "corridors",
    "trainClasses", "detentionWeights", "regulationOverheadMin",
    "maxBlocksPerDeptPerDay", "machinePositioningMin", "paths", "blocks",
    "baselineBlocks", "tasks",
}

REQUIRED_BLOCK_KEYS = {
    "id", "sec", "line", "day", "s", "e", "tasks", "depts", "types",
    "corridor", "traffic", "crit", "why",
}

REQUIRED_TASK_KEYS = {
    "id", "dept", "type", "section", "line", "km", "severity", "due_day",
    "criticality", "p50", "p90", "demanded", "cancellation_risk", "attribution",
    "machine", "night_work_allowed", "e_days", "p_fail",
}


@pytest.fixture(scope="module")
def payload(solved):
    return solved.payload


def test_top_level_keys_present(payload):
    missing = REQUIRED_TOP_LEVEL - set(payload)
    assert not missing, f"payload is missing {missing}"


def test_block_keys_present(payload):
    assert payload["blocks"], "no blocks to check"
    for b in payload["blocks"]:
        missing = REQUIRED_BLOCK_KEYS - set(b)
        assert not missing, f"block {b.get('id')} missing {missing}"


def test_task_keys_present(payload):
    for t in payload["tasks"]:
        missing = REQUIRED_TASK_KEYS - set(t)
        assert not missing, f"task {t.get('id')} missing {missing}"


def test_section_indices_resolve(payload):
    n = len(payload["sections"])
    for b in payload["blocks"] + payload["baselineBlocks"]:
        assert 0 <= b["sec"] < n, f"block {b['id']} points at section {b['sec']}"


def test_pricing_constants_match_the_solver(payload):
    """The client re-prices windows with these. If they drift, what-if lies."""
    from samanvay.models.traffic import REGULATION_OVERHEAD_MIN
    from samanvay.optimizer.cpsat import MACHINE_POSITIONING_MIN
    from samanvay.domain import TrainClass

    assert payload["regulationOverheadMin"] == REGULATION_OVERHEAD_MIN
    assert payload["machinePositioningMin"] == MACHINE_POSITIONING_MIN

    expected = [TrainClass(c).detention_weight for c in payload["trainClasses"]]
    assert payload["detentionWeights"] == expected


def test_path_rows_are_well_formed(payload):
    n_sections = len(payload["sections"])
    n_classes = len(payload["trainClasses"])
    n_trains = len(payload["trains"])
    for row in payload["paths"][:500]:
        assert len(row) == 7
        assert 0 <= row[0] < n_sections
        assert row[1] in (0, 1)
        assert 0 <= row[2] < n_classes
        assert row[3] < row[4], "a path exits before it enters"
        assert 0.0 < row[5] <= 1.0
        assert 0 <= row[6] < n_trains, "path points outside the train roster"


def test_train_roster_labels_provenance_honestly(payload):
    """The tooltip must not let a forecast goods path read as a booked service."""
    from samanvay.domain import TrainClass

    goods = payload["trainClasses"].index(TrainClass.GOODS.value)
    roster = payload["trains"]

    from samanvay.serialize import PROVENANCE_INDEX

    valid = set(PROVENANCE_INDEX.values())
    for row in roster:
        assert row[2] in valid, f"unknown provenance code {row[2]}"

    for row in payload["paths"]:
        number, name, provenance = roster[row[6]]
        if row[2] == goods:
            assert provenance == 2, f"goods train {number} claims a booked provenance"
            assert name == "", "a forecast goods path must not carry a service name"
        else:
            # Anything but forecast: coaching traffic is booked somewhere, whether
            # authored here or read from a published source.
            assert provenance != PROVENANCE_INDEX["forecast"], (
                f"coaching train {number} marked as forecast"
            )
            assert name, f"booked service {number} has no name"

    # Authored-real, or read from a published source. Any of them means the timetable
    # loaded; only "representative" and "forecast" are stand-ins.
    stand_in = {PROVENANCE_INDEX["representative"], PROVENANCE_INDEX["forecast"]}
    real = [r for r in roster if r[2] not in stand_in]
    assert real, "no real services in the roster -- the timetable file did not load"


def test_task_ids_in_blocks_exist(payload):
    known = {t["id"] for t in payload["tasks"]}
    for b in payload["blocks"]:
        for tid in b["tasks"]:
            assert tid in known, f"block {b['id']} references unknown task {tid}"


def test_metrics_carry_the_headline_measure(payload):
    for label in ("baseline", "optimised"):
        m = payload["metrics"][label]
        assert "risk_retired_per_block_hour" in m
        assert "clubbing_ratio" in m
        assert "line_closures_saved" in m


def test_pipeline_output_matches_the_builder(payload):
    """If out/plan.json exists, it must have the shape the session produces."""
    disk = Path(__file__).resolve().parents[1] / "out" / "plan.json"
    if not disk.exists():
        pytest.skip("no out/plan.json -- run scripts/run_pipeline.py first")

    written = json.loads(disk.read_text(encoding="utf-8"))
    # The pipeline may add optional sections the session did not build.
    assert REQUIRED_TOP_LEVEL <= set(written)
    assert REQUIRED_BLOCK_KEYS <= set(written["blocks"][0])
    assert REQUIRED_TASK_KEYS <= set(written["tasks"][0])
