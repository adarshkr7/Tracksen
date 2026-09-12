"""Approval workflow and audit trail.

The claim TRACKSEN makes everywhere -- "the system recommends, the competent authority
sanctions" -- is only worth anything if the code refuses when someone reaches past their
authority. These tests are that refusal, written down.

The tamper tests matter most. An audit trail nobody can verify is decoration; one that
can be edited without detection is worse than none, because it lends false confidence to
whatever it happens to say.
"""

from __future__ import annotations

import json

import pytest

from samanvay.domain import Department
from samanvay.governance import (
    Action,
    Actor,
    ApprovalWorkflow,
    AuditLog,
    AuthorityError,
    PlanState,
    Role,
    WorkflowError,
)

ALL_DEPTS = {Department.ENGINEERING, Department.SIGNAL, Department.TRACTION}

JE = Actor("A. Sharma", Role.JE)
DEN = Actor("R. Iyer", Role.SR_DEN)
DSTE = Actor("P. Nair", Role.SR_DSTE)
DEE = Actor("S. Rao", Role.SR_DEE)
DOM = Actor("K. Menon", Role.SR_DOM)
DRM = Actor("V. Kulkarni", Role.DRM)
VIEWER = Actor("Visitor", Role.VIEWER)


@pytest.fixture
def wf():
    flow = ApprovalWorkflow(AuditLog())
    flow.create("P1", ALL_DEPTS, JE, note="weekly plan")
    return flow


def _full_route(flow, plan_id="P1"):
    flow.concur(plan_id, DEN, Department.ENGINEERING)
    flow.concur(plan_id, DSTE, Department.SIGNAL)
    flow.concur(plan_id, DEE, Department.TRACTION)
    flow.clear_operations(plan_id, DOM)
    return flow.sanction(plan_id, DRM)


# --------------------------------------------------------------------------- #
# Authority
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("actor", [JE, DEN, DSTE, DEE, DOM, VIEWER])
def test_only_the_drm_can_sanction(wf, actor):
    wf.concur("P1", DEN, Department.ENGINEERING)
    wf.concur("P1", DSTE, Department.SIGNAL)
    wf.concur("P1", DEE, Department.TRACTION)
    wf.clear_operations("P1", DOM)
    with pytest.raises(AuthorityError, match="only the DRM"):
        wf.sanction("P1", actor)


@pytest.mark.parametrize("actor,dept", [
    (DSTE, Department.ENGINEERING),
    (DEN, Department.SIGNAL),
    (DEE, Department.ENGINEERING),
    (DRM, Department.SIGNAL),
    (JE, Department.TRACTION),
])
def test_a_head_cannot_concur_for_another_department(wf, actor, dept):
    with pytest.raises(AuthorityError, match="cannot concur"):
        wf.concur("P1", actor, dept)


def test_each_head_can_concur_for_their_own(wf):
    wf.concur("P1", DEN, Department.ENGINEERING)
    wf.concur("P1", DSTE, Department.SIGNAL)
    wf.concur("P1", DEE, Department.TRACTION)
    assert wf.plans["P1"].fully_concurred


def test_only_operations_clears_traffic(wf):
    wf.concur("P1", DEN, Department.ENGINEERING)
    wf.concur("P1", DSTE, Department.SIGNAL)
    wf.concur("P1", DEE, Department.TRACTION)
    with pytest.raises(AuthorityError, match="Sr.DOM"):
        wf.clear_operations("P1", DRM)


# --------------------------------------------------------------------------- #
# The gate
# --------------------------------------------------------------------------- #

def test_sanction_is_refused_before_concurrence(wf):
    with pytest.raises(WorkflowError, match="cannot sanction"):
        wf.sanction("P1", DRM)


def test_sanction_is_refused_with_one_department_outstanding(wf):
    wf.concur("P1", DEN, Department.ENGINEERING)
    wf.concur("P1", DSTE, Department.SIGNAL)
    with pytest.raises(WorkflowError):
        wf.clear_operations("P1", DOM)
    with pytest.raises(WorkflowError):
        wf.sanction("P1", DRM)


def test_a_withheld_concurrence_blocks_sanction(wf):
    wf.concur("P1", DEN, Department.ENGINEERING)
    wf.concur("P1", DSTE, Department.SIGNAL, granted=False,
              remarks="cable work not ready")
    wf.concur("P1", DEE, Department.TRACTION)
    assert not wf.plans["P1"].fully_concurred
    with pytest.raises(WorkflowError):
        wf.sanction("P1", DRM)
    assert any("withheld" in b for b in wf.plans["P1"].blockers())


def test_operations_clearance_comes_after_concurrence(wf):
    with pytest.raises(WorkflowError, match="after departmental concurrence"):
        wf.clear_operations("P1", DOM)


def test_the_full_route_sanctions(wf):
    approval = _full_route(wf)
    assert approval.state is PlanState.SANCTIONED
    assert approval.sanctioned_by == DRM.name
    assert approval.sanctioned_at


def test_blockers_are_readable(wf):
    blockers = wf.plans["P1"].blockers()
    assert any("Sr.DEN" in b for b in blockers)
    assert any("Sr.DOM" in b for b in blockers)


# --------------------------------------------------------------------------- #
# A sanctioned plan is frozen
# --------------------------------------------------------------------------- #

def test_a_sanctioned_plan_cannot_be_modified(wf):
    _full_route(wf)
    with pytest.raises(WorkflowError, match="supersede"):
        wf.modify("P1", JE, note="move a block")


def test_modifying_a_draft_invalidates_prior_concurrences(wf):
    """Concurrence was given to a particular plan, not to a plan-shaped placeholder."""
    wf.concur("P1", DEN, Department.ENGINEERING)
    wf.concur("P1", DSTE, Department.SIGNAL)
    assert len(wf.plans["P1"].concurrences) == 2

    wf.modify("P1", JE, note="moved two blocks after the Sr.DOM call")
    assert wf.plans["P1"].concurrences == {}
    assert wf.plans["P1"].operations_cleared_by is None
    assert wf.plans["P1"].revision == 2
    assert wf.plans["P1"].state is PlanState.DRAFT


def test_supersession_is_how_a_sanctioned_plan_changes(wf):
    _full_route(wf)
    wf.create("P2", ALL_DEPTS, JE, note="revision")
    wf.supersede("P1", "P2", DRM, remarks="superseded by P2")
    assert wf.plans["P1"].state is PlanState.SUPERSEDED
    assert wf.plans["P1"].superseded_by == "P2"


# --------------------------------------------------------------------------- #
# Audit trail
# --------------------------------------------------------------------------- #

def test_every_step_is_recorded(wf):
    _full_route(wf)
    actions = [e.action for e in wf.log.for_plan("P1")]
    assert actions == ["CREATE", "CONCUR", "CONCUR", "CONCUR", "CLEAR", "SANCTION"]


def test_refused_attempts_are_recorded(wf):
    """Someone reaching above their authority should leave a mark, not vanish."""
    with pytest.raises(AuthorityError):
        wf.sanction("P1", DSTE)
    denials = wf.log.by_action(Action.DENIED)
    assert len(denials) == 1
    assert denials[0].actor == DSTE.name
    assert denials[0].detail["attempted"] == "SANCTION"
    assert "only the DRM" in denials[0].detail["reason"]


def test_the_trail_names_who_and_why(wf):
    wf.concur("P1", DEN, Department.ENGINEERING, remarks="tamping cleared")
    entry = wf.log.for_plan("P1")[-1]
    assert entry.actor == DEN.name
    assert entry.role == Role.SR_DEN.value
    assert entry.detail["remarks"] == "tamping cleared"


def test_chain_is_intact_after_a_full_route(wf):
    _full_route(wf)
    status = wf.log.verify()
    assert status.intact, str(status)
    assert status.entries == 6


# --------------------------------------------------------------------------- #
# Tamper evidence -- the reason the chain exists
# --------------------------------------------------------------------------- #

def test_editing_a_past_entry_breaks_the_chain(wf):
    _full_route(wf)
    log = wf.log
    assert log.verify().intact

    # Rewrite history: make it look like someone else sanctioned the plan.
    target = log._entries[-1]
    log._entries[-1] = type(target)(**{**target.to_dict(), "actor": "Someone Else"})

    status = log.verify()
    assert not status.intact
    assert status.broken_at == 5
    assert "hash" in status.reason


def test_removing_an_entry_breaks_the_chain(wf):
    _full_route(wf)
    del wf.log._entries[2]          # quietly drop a concurrence
    status = wf.log.verify()
    assert not status.intact


def test_reordering_entries_breaks_the_chain(wf):
    _full_route(wf)
    e = wf.log._entries
    e[1], e[2] = e[2], e[1]
    assert not wf.log.verify().intact


def test_a_persisted_log_survives_reload_and_verifies(wf, tmp_path):
    path = tmp_path / "audit.jsonl"
    flow = ApprovalWorkflow(AuditLog(path))
    flow.create("P9", ALL_DEPTS, JE)
    _full_route(flow, "P9")

    reloaded = AuditLog(path)
    assert len(reloaded) == 6
    assert reloaded.verify().intact
    assert [e.action for e in reloaded.for_plan("P9")][-1] == "SANCTION"


def test_a_workflow_is_restored_from_a_persisted_log(tmp_path):
    """A restart must preserve the sanction gate, not only its historic evidence."""
    path = tmp_path / "audit.jsonl"
    flow = ApprovalWorkflow(AuditLog(path))
    flow.create("P9", ALL_DEPTS, JE)
    _full_route(flow, "P9")

    restored = ApprovalWorkflow(AuditLog(path))
    status = restored.status("P9")
    assert status["state"] == PlanState.SANCTIONED.value
    assert status["sanctioned_by"] == DRM.name
    assert status["ready_for_sanction"]

    with pytest.raises(WorkflowError, match="supersede"):
        restored.modify("P9", JE, note="attempted post-restart edit")


def test_tampering_with_the_file_is_detected(wf, tmp_path):
    path = tmp_path / "audit.jsonl"
    flow = ApprovalWorkflow(AuditLog(path))
    flow.create("P9", ALL_DEPTS, JE)
    _full_route(flow, "P9")

    lines = path.read_text(encoding="utf-8").strip().split("\n")
    record = json.loads(lines[-1])
    record["detail"]["remarks"] = "sanctioned under protest"   # quietly reword it
    lines[-1] = json.dumps(record)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    status = AuditLog(path).verify()
    assert not status.intact, "a reworded remark went undetected"
    assert status.broken_at == 5


# --------------------------------------------------------------------------- #
# What was actually sanctioned
# --------------------------------------------------------------------------- #

def test_the_trail_records_which_plan_was_sanctioned_not_just_that_one_was(tmp_path):
    """"PLAN-0007 was sanctioned by the DRM" is unfalsifiable without a fingerprint.

    The chain proves the decision happened and was not edited afterwards. It could not,
    until now, prove *what* was decided — any set of blocks could be presented later as
    the sanctioned plan and nothing in the log would contradict it.
    """
    from samanvay.domain import Department
    from samanvay.governance import Action, Actor, ApprovalWorkflow, AuditLog, Role

    log = AuditLog(tmp_path / "audit.jsonl")
    wf = ApprovalWorkflow(log)
    depts = {Department.ENGINEERING}

    wf.create("P1", depts, Actor("JE Kumar", Role.JE), plan_hash="abc123")
    wf.concur("P1", Actor("Sr.DEN Rao", Role.SR_DEN), Department.ENGINEERING)
    wf.clear_operations("P1", Actor("Sr.DOM Iyer", Role.SR_DOM))
    wf.sanction("P1", Actor("DRM Sharma", Role.DRM))

    sanction = [e for e in log if e.action == Action.SANCTION.value][-1]
    assert sanction.detail.get("plan_hash") == "abc123", (
        "the sanction entry does not say which plan was signed"
    )
    assert wf.status("P1")["sanctioned_hash"] == "abc123"


def test_a_plan_hash_survives_a_restart(tmp_path):
    from samanvay.domain import Department
    from samanvay.governance import Actor, ApprovalWorkflow, AuditLog, Role

    path = tmp_path / "audit.jsonl"
    wf = ApprovalWorkflow(AuditLog(path))
    wf.create("P1", {Department.SIGNAL}, Actor("JE Kumar", Role.JE), plan_hash="deadbeef")

    restored = ApprovalWorkflow(AuditLog(path))
    assert restored.plans["P1"].plan_hash == "deadbeef"


def test_the_hash_tracks_what_the_plan_says_to_do(plan):
    """Rescoring an unchanged plan must not read as a change to it."""
    import copy

    same = copy.deepcopy(plan)
    assert same.content_hash() == plan.content_hash()

    # Commentary is not content.
    same.label = "renamed"
    for b in same.blocks:
        b.reasons = ["rewritten"]
        b.criticality_retired = 0.0
    assert same.content_hash() == plan.content_hash(), (
        "a hash that moves when only commentary changes would flag every re-score "
        "as a modification and make the signal useless"
    )

    # Moving a block is content.
    same.blocks[0].start_min += 15
    assert same.content_hash() != plan.content_hash(), "a moved block did not change the hash"
