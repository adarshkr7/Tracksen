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
    """The service, with its audit log and identity file in a temp directory.

    Imported with the paths redirected so a test run never writes into out/ or, worse,
    authenticates against whatever tokens happen to be on the developer's machine.
    """
    tmp = tmp_path_factory.mktemp("api")
    import samanvay.governance.identity as identity_mod

    serve = importlib.import_module("serve")
    serve.audit.__init__(tmp / "audit.jsonl")                  # fresh chain
    serve.workflow.log = serve.audit
    serve.workflow.plans.clear()

    store, tokens = identity_mod.bootstrap(tmp / "identities.json")
    serve.identities = store

    client = fastapi_testclient.TestClient(serve.app)
    return client, tokens, serve


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


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
    assert r.json()["sanctioned_by"] == "DRM (demo)"


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
    assert all(e.actor == "JE (demo)" for e in entries), (
        f"the audit trusted a name from the body: {[e.actor for e in entries]}"
    )
    assert all(e.role == "JE" for e in entries)
