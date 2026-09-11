"""Counterexamples from the review: behavior, failure atomicity and restored state."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import json
import pytest
from fastapi.testclient import TestClient

from samanvay.domain import (MaintenanceTask, Department, AssetClass, BlockType, Line,
    MachineType, Plan, ScheduledBlock, TrainPath, TrainClass)
from samanvay.network import SECTIONS
from samanvay.models.traffic import TrafficModel
from samanvay.optimizer.cpsat import BlockOptimiser, Candidate, OptimiserWeights
from samanvay.session import PlanningSession, Pin
from samanvay.governance import Actor, ApprovalWorkflow, AuditLog, Role, WorkflowError, AuthorityError

SID = SECTIONS[0].id
JE, DEN, DOM, DRM = (Actor("je", Role.JE), Actor("den", Role.SR_DEN),
                     Actor("dom", Role.SR_DOM), Actor("drm", Role.DRM))

@pytest.fixture
def task():
    return MaintenanceTask("A", "TMS", Department.ENGINEERING, "asset", AssetClass.RAIL,
        SID, Line.UP, SECTIONS[0].km_start + 1, "test", BlockType.TRAFFIC, 3, True,
        -20, -10, 60, 5, MachineType.NONE, 1, True, criticality=10, p90_duration_min=60)

@pytest.fixture
def candidate():
    return Candidate(1, SID, Line.UP, 0, 600, 60, 0, False, 0)


def optimize(tasks, candidates, **kwargs):
    weights = kwargs.pop("weights", OptimiserWeights(overdue=0, corridor=0, traffic=1))
    opt = BlockOptimiser(weights, time_limit_s=2, workers=1)
    return opt.solve(tasks, candidates, TrafficModel([], 2), 2, **kwargs), opt.report


def proposal():
    return Plan([ScheduledBlock("1", SID, Line.UP, 0, 600, 660, ["A"],
        [Department.ENGINEERING], [BlockType.TRAFFIC], False, 0, 10)], [], 2)


def cleared(log=None):
    w = ApprovalWorkflow(log if log is not None else AuditLog())
    w.create("P", proposal(), JE)
    w.concur("P", DEN, Department.ENGINEERING)
    w.clear_operations("P", DOM)
    return w


@pytest.mark.parametrize("transition", ["clear", "sanction", "return", "cancel", "supersede"])
def test_terminal_states_cannot_be_reopened(transition):
    w = cleared()
    w.sanction("P", DRM)
    w.cancel("P", DRM, "cancelled")
    w.create("NEXT", proposal(), JE)
    operations = {"clear": lambda: w.clear_operations("P", DOM),
        "sanction": lambda: w.sanction("P", DRM),
        "return": lambda: w.return_for_revision("P", DEN, "revise"),
        "cancel": lambda: w.cancel("P", DRM, "again"),
        "supersede": lambda: w.supersede("P", "NEXT", DRM)}
    with pytest.raises(WorkflowError):
        operations[transition]()
    assert w.status("P")["state"] == "CANCELLED"


def test_sanctioned_clearance_cannot_unlock_edits():
    w = cleared(); w.sanction("P", DRM)
    with pytest.raises(WorkflowError): w.clear_operations("P", DOM)
    with pytest.raises(WorkflowError): w.modify("P", JE)
    assert w.status("P")["state"] == "SANCTIONED"


def test_return_requires_revision_and_fresh_approvals():
    w = cleared(); w.return_for_revision("P", DEN, "revise")
    with pytest.raises(WorkflowError): w.sanction("P", DRM)
    with pytest.raises(WorkflowError): w.concur("P", DEN, Department.ENGINEERING)
    w.modify("P", JE, plan=proposal())
    with pytest.raises(WorkflowError): w.sanction("P", DRM)
    w.concur("P", DEN, Department.ENGINEERING); w.clear_operations("P", DOM)
    assert w.sanction("P", DRM).revision == 2


def test_changed_concurrence_invalidates_clearance():
    w = cleared(); w.concur("P", DEN, Department.ENGINEERING, granted=False)
    w.concur("P", DEN, Department.ENGINEERING)
    with pytest.raises(WorkflowError): w.sanction("P", DRM)


def test_overdue_weight_cannot_reward_dropping_work(task, candidate):
    for mu in (0, 2, 100):
        p, _ = optimize([task], [candidate], weights=OptimiserWeights(overdue=mu, corridor=0))
        assert p.blocks[0].task_ids == [task.id]


def test_same_machine_cannot_be_shared_by_parallel_members(task, candidate):
    a = replace(task, machine=MachineType.UTV)
    b = replace(a, id="B", department=Department.SIGNAL)
    p, _ = optimize([a, b], [candidate])
    assert sum(len(b.task_ids) for b in p.blocks) == 1


def test_stability_can_retain_or_release_an_old_placement(task, candidate):
    old, _ = optimize([task], [candidate])
    alternatives = [replace(candidate, traffic_cost=0.01), replace(candidate, id=2, start_min=720)]
    retained, _ = optimize([task], alternatives, warm_start=old)
    moved, _ = optimize([task], alternatives, warm_start=old,
        weights=OptimiserWeights(overdue=0, corridor=0, traffic=1, stability=0))
    assert retained.blocks[0].start_min == 600
    assert moved.blocks[0].start_min == 720


def test_midnight_traffic_is_counted_once():
    t = TrainPath("N", TrainClass.GOODS, SID, Line.UP, 0, 1435, 1450)
    tm = TrafficModel([t], 2)
    assert tm.cost_of_block(SID, Line.UP, 1440, 1460) == 20
    assert tm.cost_of_block(SID, Line.UP, 1430, 1460) == 25
    assert tm.trains_affected(SID, Line.UP, 1430, 1460) == 1
    assert tm._raw_consequence(SID, Line.UP) == 0.5


class NoCancellation:
    def candidate_risks(self, tasks, candidates): return {}
    def score_plan(self, plan, tasks): pass


@pytest.fixture
def tiny(task, candidate):
    s = PlanningSession.__new__(PlanningSession)
    s.horizon_days = s.monthly_days = 2
    s.tasks = [task, replace(task, id="B", department=Department.SIGNAL)]
    s.task_by_id = {t.id: t for t in s.tasks}
    s.base_candidates = [candidate, replace(candidate, id=2, start_min=720)]
    s.traffic = TrafficModel([], 2); s.corridors = []; s._baseline = None
    s.breakdowns = {}; s.paths = []; s.model_checks = {}; s.seed = 0
    s._monthly_ctx = ([], s.traffic, [], s.base_candidates, [])
    s.cancellation = NoCancellation()
    return s


@pytest.mark.parametrize("pins", [
    [Pin("1", 600, ["A"]), Pin("2", 720, ["A"])],
    [Pin("1", 600, ["A"]), Pin("1", 720, ["B"])],
    [Pin("1", 600, ["A", "MISSING"])], [Pin("1", 600, ["A", "A"])],
])
def test_duplicate_and_unknown_pin_members_are_refused(tiny, pins):
    extra, accepted, rejected = tiny._pin_candidates(pins)
    assert rejected and not accepted and not extra


def test_jointly_infeasible_pins_have_names(tiny):
    r = tiny.solve(pins=[Pin("1", 600, ["A"]), Pin("2", 600, ["B"])], time_limit_s=2)
    assert r.payload["meta"]["solver"]["status"] == "INFEASIBLE"
    assert all(any(p in reason for reason in r.rejected) for p in ("1", "2"))


def test_pinned_membership_stays_exact(tiny):
    r = tiny.solve(pins=[Pin("1", 600, ["A"])], time_limit_s=2)
    pinned = next(b for b in r.plan.blocks if b.start_min == 600)
    assert pinned.task_ids == ["A"]


def test_monthly_accounts_for_extended_tasks(tiny, candidate):
    tiny.tasks[1].p90_duration_min = 240
    tiny.monthly_context = lambda: ([], tiny.traffic, [], [replace(candidate, capacity_min=180)], [])
    r = tiny.solve_monthly(time_limit_s=2)
    assert r.metrics.tasks_scheduled + r.metrics.tasks_unscheduled == len(tiny.tasks)
    assert "B" in r.plan.unscheduled_task_ids and r.extended_tasks == ["B"]
    assert r.report.unscheduled == r.metrics.tasks_unscheduled


def test_audit_checks_disk_without_restart(tmp_path):
    path = tmp_path / "audit.jsonl"; log = AuditLog(path)
    log.append(actor="a", role="JE", action="CREATE", plan_id="P")
    row = json.loads(path.read_text()); row["actor"] = "changed"
    path.write_text(json.dumps(row) + "\n")
    assert not log.verify().intact
    with pytest.raises(RuntimeError): log.append(actor="a", role="JE", action="MODIFY", plan_id="P")


def test_audit_detects_truncation(tmp_path):
    path = tmp_path / "audit.jsonl"; log = AuditLog(path)
    log.append(actor="a", role="JE", action="CREATE", plan_id="P")
    path.write_text("")
    assert not log.verify().intact


def test_audit_serializes_concurrent_appends(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: log.append(actor=str(i), role="JE", action="CREATE", plan_id=str(i)), range(20)))
    assert len(log) == 20 and log.verify().intact and AuditLog(log.path).verify().intact


def test_workflow_replays_snapshot_and_authority(tmp_path):
    w = cleared(AuditLog(tmp_path / "audit.jsonl")); w.sanction("P", DRM)
    restored = ApprovalWorkflow(AuditLog(w.log.path))
    assert restored.status("P") == w.status("P")
    assert restored.plans["P"].plan() == proposal()
    with pytest.raises(WorkflowError): restored.modify("P", JE)


def test_audit_failure_does_not_publish_approval_mutation(monkeypatch):
    w = cleared(); before = w.status("P"); count = len(w.log)
    def broken(entry): raise OSError("disk full")
    monkeypatch.setattr(w.log, "_persist", broken)
    with pytest.raises(OSError): w.sanction("P", DRM)
    assert w.status("P") == before and len(w.log) == count


def test_snapshot_is_detached_and_hash_changes_on_edit():
    original = proposal(); w = ApprovalWorkflow(AuditLog()); w.create("P", original, JE)
    old = w.status("P"); original.blocks[0].start_min += 5
    assert w.plans["P"].plan().blocks[0].start_min == 600
    w.modify("P", JE, plan=original)
    assert w.status("P")["content_hash"] != old["content_hash"]
    with pytest.raises(WorkflowError): w.check_revision("P", old["revision"], old["content_hash"])


@pytest.fixture
def api(tiny, monkeypatch):
    from scripts import serve
    wf = ApprovalWorkflow(AuditLog())
    source = proposal()
    source.blocks.append(replace(source.blocks[0], id="2", start_min=720, end_min=780,
                                 task_ids=["B"], departments=[Department.SIGNAL]))
    wf.create("P", source, JE, context=serve._context(tiny))
    monkeypatch.setattr(serve, "workflow", wf); monkeypatch.setattr(serve, "audit", wf.log)
    monkeypatch.setattr(serve, "_session", tiny); monkeypatch.setattr(serve, "_last_plan", source)
    return serve, TestClient(serve.app), source


def body(serve, **extra):
    a = serve.workflow.status("P")
    return {"plan_id": "P", "actor": "je", "role": "JE", "revision": a["revision"],
            "content_hash": a["content_hash"], "time_limit_s": 2, **extra}


def test_api_conflict_preserves_plan_and_revision(api):
    serve, client, original = api; before = serve.workflow.status("P")
    response = client.post("/api/resolve", json=body(serve, pins=[
        {"block_id": "1", "start_min": 600, "task_ids": ["A"]},
        {"block_id": "2", "start_min": 600, "task_ids": ["B"]}]))
    assert response.status_code == 422 and response.json()["detail"]["rejected"]
    assert serve._last_plan is original and serve.workflow.status("P") == before


def test_api_sanctioned_edit_does_not_even_solve(api, monkeypatch):
    serve, client, original = api
    serve.workflow.concur("P", DEN, Department.ENGINEERING)
    serve.workflow.concur("P", Actor("signal", Role.SR_DSTE), Department.SIGNAL)
    serve.workflow.clear_operations("P", DOM); serve.workflow.sanction("P", DRM)
    monkeypatch.setattr(serve._session, "solve", lambda **kw: pytest.fail("solver must not run"))
    assert client.post("/api/resolve", json=body(serve)).status_code == 409
    assert serve._last_plan is original


def test_api_requires_bound_revision_and_prevents_invented_scope(api):
    serve, client, _ = api
    assert client.post("/api/resolve", json={"pins": []}).status_code == 422
    b = body(serve); b["content_hash"] = "0" * 64
    assert client.post("/api/resolve", json=b).status_code == 409
    b = body(serve); b.pop("plan_id"); b.pop("time_limit_s"); b["departments"] = []
    assert client.post("/api/plans/P/submit", json=b).status_code == 422


def test_api_success_returns_new_bound_revision(api):
    serve, client, _ = api; old = body(serve)
    response = client.post("/api/resolve", json=old)
    assert response.status_code == 200
    assert response.json()["meta"]["revision"] == old["revision"] + 1
    assert client.post("/api/resolve", json=old).status_code == 409
    restored = client.get("/api/plan", params={"plan_id": "P"})
    assert restored.status_code == 200
    assert restored.json()["blocks"] == response.json()["blocks"]


def test_api_no_incumbent_is_not_reported_as_infeasible(api, monkeypatch):
    serve, client, original = api
    result = serve._session.solve(time_limit_s=2)
    result.payload["meta"]["solver"]["status"] = "UNKNOWN"
    monkeypatch.setattr(serve._session, "solve", lambda **kw: result)
    assert client.post("/api/resolve", json=body(serve)).status_code == 503
    assert serve._last_plan is original


def test_cancellation_uses_placement_not_night_permission(session):
    t = replace(session.tasks[0], night_work_allowed=True)
    cx = session.cancellation
    daylight = cx.probabilities([t], 600, 660, True)[0]
    without_permission = cx.probabilities([replace(t, night_work_allowed=False)], 600, 660, True)[0]
    night = cx.probabilities([t], 60, 120, True)[0]
    outside = cx.probabilities([t], 600, 660, False)[0]
    assert daylight == without_permission and night > daylight and outside > daylight


def test_cancellation_cost_influences_placement(task, candidate):
    class Risk:
        def candidate_risks(self, tasks, candidates): return {("A", 1): 0.9, ("A", 2): 0.1}
        def score_plan(self, plan, tasks): pass
    p, _ = optimize([task], [candidate, replace(candidate, id=2, start_min=720)], cancellation=Risk())
    assert p.blocks[0].start_min == 720


def test_standby_replaces_only_released_work_and_keeps_other_blocks(tiny):
    original = proposal()
    original.unscheduled_task_ids = ["B"]
    r = tiny.standby(original, "1", ["B"], time_limit_s=2)
    assert len(r.plan.blocks) == 1 and r.plan.blocks[0].task_ids == ["B"]
    assert (r.plan.blocks[0].start_min, r.plan.blocks[0].end_min) == (600, 660)
    assert "A" in r.plan.unscheduled_task_ids
    assert original.blocks[0].task_ids == ["A"]


def test_standby_rejects_tasks_not_declared_unscheduled(tiny):
    with pytest.raises(ValueError): tiny.standby(proposal(), "1", ["A"], time_limit_s=2)


def test_standby_api_creates_new_draft_without_changing_source(api):
    serve, client, source = api
    s = serve._session
    c = replace(s.tasks[0], id="C")
    s.tasks.append(c); s.task_by_id[c.id] = c
    source.unscheduled_task_ids.append(c.id)
    serve.workflow.modify("P", JE, plan=source, context=serve._context(s))
    before = serve.workflow.status("P")
    b = body(serve); b.pop("plan_id")
    b.update(released_block_id="1", ready_task_ids=["C"])
    response = client.post("/api/plans/P/standby", json=b)
    assert response.status_code == 200
    result = response.json()
    assert result["meta"]["plan_id"] != "P" and result["meta"]["state"] == "DRAFT"
    assert serve.workflow.status("P") == before
    by_tasks = {tuple(block["tasks"]): block for block in result["blocks"]}
    assert by_tasks[("C",)]["s"] == 600 and by_tasks[("B",)]["s"] == 720


def test_standby_checks_machine_positioning_against_unaffected_work(tiny):
    tiny.tasks[1].machine = MachineType.UTV
    c = replace(tiny.tasks[0], id="C", machine=MachineType.UTV)
    tiny.tasks.append(c); tiny.task_by_id[c.id] = c
    source = proposal()
    source.blocks.append(replace(source.blocks[0], id="2", start_min=720, end_min=780,
        task_ids=["B"], departments=[Department.SIGNAL]))
    source.unscheduled_task_ids.append("C")
    r = tiny.standby(source, "1", ["C"], time_limit_s=2)
    assert all("C" not in b.task_ids for b in r.plan.blocks)
    assert any(b.task_ids == ["B"] and b.start_min == 720 for b in r.plan.blocks)
