"""The approval endpoints, exercised over HTTP.

The unit tests in test_identity.py prove the store refuses a bad token. These prove the
service actually asks it -- which is a different claim, and the one that was false before.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

fastapi_testclient = pytest.importorskip("fastapi.testclient")


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    """The service, with its audit log, accounts and sessions in a temp directory.

    Imported with the paths redirected so a test run never writes into out/ or, worse,
    authenticates against whatever accounts happen to be on the developer's machine.

    The tokens handed back are real session tokens, obtained by signing each bootstrap
    account in with its minted password -- the same path a browser takes. Keying them by
    role rather than by username keeps these tests about the approval route, which is
    what they are for; who holds the DRM account is test_identity.py's business.
    """
    tmp = tmp_path_factory.mktemp("api")
    from samanvay.domain import BlockType, Department, Line, Plan, ScheduledBlock
    from samanvay.governance import AuthService, PlanStore

    serve = importlib.import_module("serve")
    serve.audit.__init__(tmp / "audit.jsonl")                  # fresh chain
    serve.workflow.log = serve.audit
    serve.workflow.plans.clear()
    serve.plans = PlanStore(tmp / "plans")                     # never touch out/

    serve.auth = AuthService(tmp / "accounts.json", tmp / "sessions.json",
                             tmp / "auth.jsonl")
    tokens = {}
    for username, password in serve.auth.minted.items():
        result = serve.auth.login(username, password)
        tokens[result.account.role.value] = result.token

    # A plan to submit. Solving a real one here would fit four models for the sake of
    # testing an HTTP surface; what these tests need is something with a content hash.
    serve._last_plan = Plan(
        blocks=[ScheduledBlock(
            id="1", section_id="BXR-DURE", line=Line.UP, day=0,
            start_min=600, end_min=780, task_ids=["T1", "T2"],
            departments=[Department.ENGINEERING], block_types=[BlockType.TRAFFIC],
            inside_corridor=True, traffic_cost=12.5, criticality_retired=40.0,
            reasons=["inside mandated corridor"],
        )],
        unscheduled_task_ids=["T9"], horizon_days=7, label="test",
    )

    client = fastapi_testclient.TestClient(serve.app)
    return client, tokens, serve


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def who(serve, role: str) -> str:
    """The display name the service holds for a role, rather than a literal in a test.

    The bootstrap names are demo dressing and have changed once already. What these tests
    are actually asserting is that the trail carries the name the SERVICE resolved, so
    that is what they should read it from.
    """
    for account in serve.auth.accounts.accounts:
        if account.role.value == role:
            return account.display_name
    raise AssertionError(f"no bootstrap account for {role}")


# --------------------------------------------------------------------------- #
# Unauthenticated
# --------------------------------------------------------------------------- #

ACTIONS = [
    ("submit", {"plan_id": "P-AUTH", "departments": ["ENGG"]}),
    ("concur", {"department": "ENGG"}),
    ("clear", {}),
    ("sanction", {}),
    ("return", {}),
]


@pytest.mark.parametrize("action,body", ACTIONS)
def test_every_approval_action_refuses_an_unauthenticated_caller(api, action, body):
    client, _, _ = api
    r = client.post(f"/api/plans/P-AUTH/{action}", json=body)
    assert r.status_code == 401, (
        f"{action} accepted a request with no token -- the approval route is open"
    )
    assert "bearer" in r.headers.get("www-authenticate", "").lower()


@pytest.mark.parametrize("action,body", ACTIONS)
def test_every_approval_action_refuses_a_bad_token(api, action, body):
    client, _, _ = api
    r = client.post(f"/api/plans/P-AUTH/{action}", json=body, headers=auth("wrong"))
    assert r.status_code == 401


def test_a_role_in_the_body_grants_nothing(api):
    """The attack the old design permitted, asserted as impossible.

    A caller holding only a Viewer token, claiming DRM in the body, must not sanction.
    The body field no longer exists; FastAPI ignores the extra key, and the token decides.
    """
    client, tokens, _ = api
    client.post("/api/plans/P-CLAIM/submit",
                json={"plan_id": "P-CLAIM", "departments": ["ENGG"]},
                headers=auth(tokens["JE"]))

    r = client.post("/api/plans/P-CLAIM/sanction",
                    json={"remarks": "mine now", "role": "DRM", "actor": "Somebody"},
                    headers=auth(tokens["Viewer"]))
    assert r.status_code == 403, (
        "a Viewer token sanctioned a plan by claiming DRM in the request body"
    )


# --------------------------------------------------------------------------- #
# Authenticated
# --------------------------------------------------------------------------- #

def test_me_reports_the_token_holder(api):
    client, tokens, _ = api
    r = client.get("/api/me", headers=auth(tokens["Sr.DOM"]))
    assert r.status_code == 200
    assert r.json()["role"] == "Sr.DOM"


def test_me_refuses_without_a_token(api):
    client, _, _ = api
    assert client.get("/api/me").status_code == 401


def test_the_full_route_works_with_the_right_tokens(api):
    """Authentication must not have broken the thing it protects."""
    client, tokens, serve = api
    pid = "P-ROUTE"

    assert client.post(f"/api/plans/{pid}/submit",
                       json={"plan_id": pid, "departments": ["ENGG"]},
                       headers=auth(tokens["JE"])).status_code == 200
    assert client.post(f"/api/plans/{pid}/concur", json={"department": "ENGG"},
                       headers=auth(tokens["Sr.DEN"])).status_code == 200
    assert client.post(f"/api/plans/{pid}/clear", json={},
                       headers=auth(tokens["Sr.DOM"])).status_code == 200

    r = client.post(f"/api/plans/{pid}/sanction", json={}, headers=auth(tokens["DRM"]))
    assert r.status_code == 200
    assert r.json()["state"] == "SANCTIONED"
    assert r.json()["sanctioned_by"] == who(serve, "DRM")


def test_the_wrong_head_cannot_concur_for_another_department(api):
    client, tokens, _ = api
    pid = "P-DEPT"
    client.post(f"/api/plans/{pid}/submit",
                json={"plan_id": pid, "departments": ["ENGG"]},
                headers=auth(tokens["JE"]))
    r = client.post(f"/api/plans/{pid}/concur", json={"department": "ENGG"},
                    headers=auth(tokens["Sr.DSTE"]))
    assert r.status_code == 403


def test_the_audit_records_the_authenticated_name_not_a_claimed_one(api):
    """The trail is only worth keeping if the name in it was established, not asserted."""
    client, tokens, serve = api
    pid = "P-TRAIL"
    client.post(f"/api/plans/{pid}/submit",
                json={"plan_id": pid, "departments": ["ENGG"], "actor": "Impostor"},
                headers=auth(tokens["JE"]))

    entries = [e for e in serve.audit if e.plan_id == pid]
    assert entries, "nothing was recorded"
    expected = who(serve, "JE")
    assert all(e.actor == expected for e in entries), (
        f"the audit trusted a name from the body: {[e.actor for e in entries]}"
    )
    assert all(e.actor != "Impostor" for e in entries)
    assert all(e.role == "JE" for e in entries)


# --------------------------------------------------------------------------- #
# What was approved, retrievable afterwards
# --------------------------------------------------------------------------- #

def test_a_submitted_plan_is_stored_and_retrievable(api):
    client, tokens, serve = api
    pid = "P-STORED"
    client.post(f"/api/plans/{pid}/submit",
                json={"plan_id": pid, "departments": ["ENGG"]},
                headers=auth(tokens["JE"]))

    r = client.get(f"/api/plans/{pid}/plan")
    assert r.status_code == 200
    body = r.json()
    assert body["blocks"], "the plan was approved but its content was not stored"
    assert body["intact"], "the stored plan does not match its own hash"
    assert body["revisions"] == [body["revision"]]


def test_the_stored_plan_is_the_one_the_drm_signed(api):
    """The claim the content hash exists to support, asserted end to end."""
    client, tokens, _ = api
    pid = "P-SIGNED"
    client.post(f"/api/plans/{pid}/submit",
                json={"plan_id": pid, "departments": ["ENGG"]},
                headers=auth(tokens["JE"]))
    client.post(f"/api/plans/{pid}/concur", json={"department": "ENGG"},
                headers=auth(tokens["Sr.DEN"]))
    client.post(f"/api/plans/{pid}/clear", json={}, headers=auth(tokens["Sr.DOM"]))
    client.post(f"/api/plans/{pid}/sanction", json={}, headers=auth(tokens["DRM"]))

    body = client.get(f"/api/plans/{pid}/plan").json()
    assert body["matches_sanctioned"], (
        "the stored plan is not the one recorded as sanctioned"
    )
    assert body["sanctioned_hash"] == body["content_hash"]


def test_an_unstored_plan_is_404_not_an_empty_plan(api):
    client, _, _ = api
    r = client.get("/api/plans/NEVER-EXISTED/plan")
    assert r.status_code == 404


def test_a_plan_id_that_would_escape_the_store_is_refused_over_http(api):
    """The id reaches the store from a URL path, so it is checked there too."""
    client, _, _ = api
    r = client.get("/api/plans/..%2F..%2Fetc/plan")
    assert r.status_code in (404, 422), f"got {r.status_code}: path traversal reached disk"


def test_submitting_before_anything_is_solved_is_refused(api):
    """Storing nothing and calling it approved would be the worst of both."""
    client, tokens, serve = api
    held, serve._last_plan = serve._last_plan, None
    try:
        r = client.post("/api/plans/P-NOTHING/submit",
                        json={"plan_id": "P-NOTHING", "departments": ["ENGG"]},
                        headers=auth(tokens["JE"]))
        assert r.status_code == 409
    finally:
        serve._last_plan = held


# --------------------------------------------------------------------------- #
# Signing in over HTTP
# --------------------------------------------------------------------------- #
#
# These use an account of their own. Changing a password revokes every other session for
# that account, so exercising it against one of the bootstrap logins would sign the rest
# of this file out halfway through and the failures would look like authorisation bugs.

TEST_PASSWORD = "a-perfectly-adequate-password"
NEW_PASSWORD = "an-entirely-different-password"


@pytest.fixture
def tester(api):
    """A throwaway account, recreated per test so password changes cannot leak across."""
    _, _, serve = api
    from samanvay.governance import Role, new_account

    account = new_account("tester", "T. Tester", Role.VIEWER, TEST_PASSWORD)
    store = serve.auth.accounts
    store._by_username["tester"] = account
    store.accounts = [a for a in store.accounts if a.username != "tester"] + [account]
    serve.auth.sessions.revoke_all_for("tester")
    return account


def test_signing_in_returns_a_session(api, tester):
    client, _, _ = api
    r = client.post("/api/login",
                    json={"username": "tester", "password": TEST_PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["token"] and body["role"] == "Viewer"
    assert body["expires_at"], "a session with no expiry is the thing this replaced"
    assert client.get("/api/me", headers=auth(body["token"])).status_code == 200


def test_a_wrong_password_is_refused_the_same_way_as_an_unknown_user(api, tester):
    client, _, _ = api
    wrong = client.post("/api/login",
                        json={"username": "tester", "password": "nope-not-this"})
    unknown = client.post("/api/login",
                          json={"username": "no-such-person", "password": "nope-not-this"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"], (
        "the login form tells an attacker which usernames are real"
    )


def test_the_login_response_never_carries_the_password_back(api, tester):
    client, _, _ = api
    body = client.post("/api/login",
                       json={"username": "tester", "password": TEST_PASSWORD}).text
    assert TEST_PASSWORD not in body


def test_signing_out_makes_the_token_useless(api, tester):
    client, _, _ = api
    token = client.post("/api/login",
                        json={"username": "tester", "password": TEST_PASSWORD}
                        ).json()["token"]
    assert client.post("/api/logout", headers=auth(token)).status_code == 200
    assert client.get("/api/me", headers=auth(token)).status_code == 401


def test_a_weak_new_password_is_refused_without_signing_the_caller_out(api, tester):
    client, _, _ = api
    token = client.post("/api/login",
                        json={"username": "tester", "password": TEST_PASSWORD}
                        ).json()["token"]
    r = client.post("/api/password", headers=auth(token),
                    json={"current_password": TEST_PASSWORD, "new_password": "short"})
    assert r.status_code == 422, (
        "a rejected password sent the caller back to the sign-in screen; the problem is "
        "the new password, not their identity"
    )
    assert client.get("/api/me", headers=auth(token)).status_code == 200


def test_changing_the_password_ends_other_sessions_over_http(api, tester):
    client, _, _ = api
    elsewhere = client.post("/api/login",
                            json={"username": "tester", "password": TEST_PASSWORD}
                            ).json()["token"]
    here = client.post("/api/login",
                       json={"username": "tester", "password": TEST_PASSWORD}
                       ).json()["token"]

    r = client.post("/api/password", headers=auth(here),
                    json={"current_password": TEST_PASSWORD,
                          "new_password": NEW_PASSWORD})
    assert r.status_code == 200
    assert client.get("/api/me", headers=auth(elsewhere)).status_code == 401
    assert client.get("/api/me", headers=auth(here)).status_code == 200


def test_the_sessions_endpoint_names_the_current_one(api, tester):
    client, _, _ = api
    token = client.post("/api/login",
                        json={"username": "tester", "password": TEST_PASSWORD}
                        ).json()["token"]
    client.post("/api/login", json={"username": "tester", "password": TEST_PASSWORD})

    body = client.get("/api/sessions", headers=auth(token)).json()
    assert len(body["sessions"]) == 2
    assert sum(1 for s in body["sessions"] if s["current"]) == 1

    assert client.post("/api/sessions/revoke-others",
                       headers=auth(token)).json()["ended"] == 1
    assert client.get("/api/me", headers=auth(token)).status_code == 200


def test_the_verifier_checks_the_sign_in_trail_too(api, tester):
    client, _, _ = api
    client.post("/api/login", json={"username": "tester", "password": TEST_PASSWORD})
    body = client.get("/api/audit/verify").json()
    assert body["auth"] is not None
    assert body["auth"]["intact"]
    assert body["auth"]["entries"] > 0
