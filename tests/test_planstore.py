"""What was approved, kept where it can be read back and checked.

The audit chain proves a plan was sanctioned. The content hash proves which plan. Neither
stores the plan, so until this existed a restarted service could verify a sanction and be
unable to show anybody what had been sanctioned.
"""

from __future__ import annotations

import json

import pytest

from samanvay.domain import Line, Plan, ScheduledBlock, plan_content_hash
from samanvay.governance import PlanStore, PlanStoreError, StoredPlan


def block(bid: str, section: str, start: int, tasks: list[str],
          line: Line = Line.UP) -> ScheduledBlock:
    from samanvay.domain import BlockType, Department

    return ScheduledBlock(
        id=bid, section_id=section, line=line, day=start // 1440,
        start_min=start, end_min=start + 120, task_ids=tasks,
        departments=[Department.ENGINEERING], block_types=[BlockType.TRAFFIC],
        inside_corridor=True, traffic_cost=12.5, criticality_retired=40.0,
        reasons=["inside mandated corridor"],
    )


@pytest.fixture
def a_plan() -> Plan:
    return Plan(
        blocks=[block("1", "BXR-DURE", 600, ["T1", "T2"]),
                block("2", "ARA-BTA", 900, ["T3"], Line.DN)],
        unscheduled_task_ids=["T9"],
        horizon_days=7,
        label="TRACKSEN (CP-SAT)",
    )


@pytest.fixture
def store(tmp_path) -> PlanStore:
    return PlanStore(tmp_path / "plans")


# --------------------------------------------------------------------------- #
# Round trip
# --------------------------------------------------------------------------- #

def test_a_saved_plan_comes_back_intact(store, a_plan):
    store.save("PLAN-0001", 1, a_plan)
    back = store.load("PLAN-0001", 1)

    assert back is not None
    assert back.content_hash == a_plan.content_hash()
    assert back.intact, "a freshly written revision failed its own hash check"
    assert len(back.blocks) == 2
    assert back.unscheduled_task_ids == ["T9"]


def test_the_stored_hash_is_the_domain_hash(store, a_plan):
    """Two implementations of "what a plan is" would drift. There is only one."""
    store.save("P", 1, a_plan)
    back = store.load("P", 1)
    assert back.recomputed_hash() == a_plan.content_hash()


def test_loading_without_a_revision_gives_the_latest(store, a_plan):
    store.save("P", 1, a_plan)
    moved = Plan(blocks=[block("1", "BXR-DURE", 660, ["T1", "T2"])],
                 unscheduled_task_ids=[], horizon_days=7, label="x")
    store.save("P", 2, moved)

    assert store.load("P").revision == 2
    assert store.revisions("P") == [1, 2]


def test_an_unstored_plan_is_absent_not_an_error(store):
    assert store.load("NEVER-SAVED") is None
    assert store.revisions("NEVER-SAVED") == []


# --------------------------------------------------------------------------- #
# Which revision was signed
# --------------------------------------------------------------------------- #

def test_find_by_hash_returns_the_revision_that_was_signed(store, a_plan):
    """A plan is re-solved several times before anyone approves it.

    "The latest revision" and "the revision the DRM sanctioned" are different questions,
    and the audit entry carries the hash that answers the second.
    """
    store.save("P", 1, a_plan)
    signed_hash = a_plan.content_hash()

    later = Plan(blocks=[block("1", "BXR-DURE", 1200, ["T1"])],
                 unscheduled_task_ids=[], horizon_days=7, label="x")
    store.save("P", 2, later)

    found = store.find_by_hash("P", signed_hash)
    assert found is not None and found.revision == 1
    assert store.load("P").revision == 2, "the latest is still the latest"


def test_matches_is_false_for_a_different_plan(store, a_plan):
    store.save("P", 1, a_plan)
    back = store.load("P", 1)
    assert back.matches(a_plan.content_hash())
    assert not back.matches("0" * 64)
    assert not back.matches(None)


# --------------------------------------------------------------------------- #
# Tampering
# --------------------------------------------------------------------------- #

def test_editing_a_stored_plan_is_detected(store, a_plan):
    """The hash is only worth recording if it can be used as a test afterwards."""
    store.save("P", 1, a_plan)
    path = next((store.root / "P").glob("r*.json"))

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["blocks"][0]["start_min"] = 60          # move the block two hours earlier
    path.write_text(json.dumps(raw), encoding="utf-8")

    back = store.load("P", 1)
    assert not back.intact, "a block was moved on disk and the store did not notice"
    assert not back.matches(a_plan.content_hash())


def test_commentary_is_not_content(store, a_plan):
    """Re-scoring an unchanged plan must not read as a modification."""
    store.save("P", 1, a_plan)
    path = next((store.root / "P").glob("r*.json"))

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["blocks"][0]["reasons"] = ["rewritten"]
    raw["blocks"][0]["criticality_retired"] = 0.0
    raw["label"] = "renamed"
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert store.load("P", 1).intact


# --------------------------------------------------------------------------- #
# Plan ids become filenames
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("bad", [
    "../../etc/passwd", "..", "/abs/path", "a/b", "", "with space",
    "x" * 65, ".hidden",
])
def test_a_plan_id_that_would_escape_the_store_is_refused(store, a_plan, bad):
    """Plan ids arrive in a JSON body and become path segments."""
    with pytest.raises(PlanStoreError):
        store.save(bad, 1, a_plan)
    with pytest.raises(PlanStoreError):
        store.load(bad)


def test_ordinary_plan_ids_are_accepted(store, a_plan):
    for good in ("PLAN-0001", "WEEKLY-CURRENT", "p.1_2", "A"):
        store.save(good, 1, a_plan)
        assert store.load(good) is not None


# --------------------------------------------------------------------------- #
# Survives a restart
# --------------------------------------------------------------------------- #

def test_a_new_store_over_the_same_directory_sees_everything(tmp_path, a_plan):
    root = tmp_path / "plans"
    PlanStore(root).save("P", 1, a_plan)

    restarted = PlanStore(root)
    assert restarted.plan_ids() == ["P"]
    assert restarted.load("P", 1).intact


def test_a_partial_write_does_not_replace_a_good_revision(store, a_plan, monkeypatch):
    """A crash mid-write must not leave a truncated revision reading as a tampered one."""
    store.save("P", 1, a_plan)
    good = store.load("P", 1).content_hash

    import samanvay.governance.planstore as mod

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(mod.os, "replace", boom)
    with pytest.raises(OSError):
        store.save("P", 1, a_plan)

    assert store.load("P", 1).content_hash == good
    assert not list((store.root / "P").glob("*.partial")), "left a partial file behind"
