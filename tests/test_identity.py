"""Accounts, passwords and sessions.

This file replaced a suite that tested a bearer token printed at startup. That scheme was
real authentication and the wrong shape: a token per role, permanent, and impossible to
withdraw. What is tested here is the three properties it lacked — a credential belongs to
a person, it expires, and it can be taken away — plus the handful of ways a login system
fails without raising anything.

The failures worth guarding are the quiet ones. A password compared with `==` still lets
everybody in and out correctly. An expiry that is written down but never checked produces
a session that works forever and a field that says it should not. A "wrong password"
message that differs from "no such user" hands an attacker a list of your DRMs. None of
those throw.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from samanvay.governance.accounts import (
    MAX_FAILED_ATTEMPTS,
    MIN_PASSWORD_LENGTH,
    AccountStore,
    AuthenticationError,
    PasswordPolicyError,
    bootstrap,
    load_or_bootstrap,
    new_account,
)
from samanvay.governance.identity import AuthService
from samanvay.governance.sessions import (
    ABSOLUTE_LIFETIME_HOURS,
    IDLE_TIMEOUT_MINUTES,
    SessionStore,
    hash_token,
)
from samanvay.governance.workflow import Role

GOOD_PASSWORD = "a-perfectly-adequate-password"


@pytest.fixture
def store(tmp_path):
    accounts, passwords = bootstrap(tmp_path / "accounts.json")
    return accounts, passwords, tmp_path


@pytest.fixture
def service(tmp_path):
    return AuthService(tmp_path / "accounts.json", tmp_path / "sessions.json",
                       tmp_path / "auth.jsonl")


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #

def test_a_minted_password_signs_its_account_in(store):
    accounts, passwords, _ = store
    account = accounts.verify("drm", passwords["drm"])
    assert account.role is Role.DRM


def test_every_role_gets_a_working_account(store):
    """The bootstrap set has to walk the whole route, or the gates go untested."""
    accounts, passwords, _ = store
    roles = {accounts.verify(u, p).role for u, p in passwords.items()}
    assert roles == set(Role), f"no bootstrap account for {set(Role) - roles}"


def test_a_wrong_password_is_refused(store):
    accounts, passwords, _ = store
    with pytest.raises(AuthenticationError):
        accounts.verify("drm", passwords["drm"] + "x")


def test_an_unknown_user_and_a_wrong_password_are_indistinguishable(store):
    """Otherwise the login form is a directory of who can sanction."""
    accounts, passwords, _ = store
    with pytest.raises(AuthenticationError) as wrong:
        accounts.verify("drm", "definitely-not-it")
    with pytest.raises(AuthenticationError) as unknown:
        accounts.verify("no-such-person", "definitely-not-it")
    assert str(wrong.value) == str(unknown.value)


def test_the_accounts_file_holds_no_recoverable_password(store):
    accounts, passwords, tmp = store
    raw = (tmp / "accounts.json").read_text(encoding="utf-8")
    for password in passwords.values():
        assert password not in raw, "a password was written to the accounts file"
    doc = json.loads(raw)
    for entry in doc["accounts"]:
        assert entry["password_hash"] and entry["salt"]
        assert entry["kdf"]["name"] == "scrypt"


def test_each_account_has_its_own_salt(store):
    """Shared salts make one precomputation serve every account."""
    accounts, _, _ = store
    salts = {a.salt for a in accounts.accounts}
    assert len(salts) == len(accounts.accounts)


def test_the_same_password_on_two_accounts_derives_differently(tmp_path):
    a = new_account("one", "One", Role.JE, GOOD_PASSWORD)
    b = new_account("two", "Two", Role.DRM, GOOD_PASSWORD)
    assert a.password_hash != b.password_hash


@pytest.mark.parametrize("bad", ["", "short", "x" * (MIN_PASSWORD_LENGTH - 1), "   "])
def test_a_weak_password_is_refused_before_it_is_stored(bad):
    with pytest.raises(PasswordPolicyError):
        new_account("u", "U", Role.JE, bad)


def test_bootstrap_accounts_must_change_their_password(store):
    """A minted credential printed to a terminal is already in somebody's scrollback."""
    accounts, _, _ = store
    assert all(a.must_change_password for a in accounts.accounts)


def test_changing_a_password_clears_the_flag_and_invalidates_the_old_one(store):
    accounts, passwords, _ = store
    accounts.set_password("drm", GOOD_PASSWORD)
    account = accounts.get("drm")
    assert not account.must_change_password
    assert accounts.verify("drm", GOOD_PASSWORD).username == "drm"
    with pytest.raises(AuthenticationError):
        accounts.verify("drm", passwords["drm"])


def test_repeated_failures_lock_the_account(store):
    accounts, passwords, _ = store
    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(AuthenticationError):
            accounts.verify("drm", "wrong")

    # The right password no longer works either -- that is what a lockout is.
    with pytest.raises(AuthenticationError) as exc:
        accounts.verify("drm", passwords["drm"])
    assert "locked" in str(exc.value)


def test_a_lockout_survives_a_restart(store):
    """Held in the file, not in memory. Otherwise the attack is: guess, restart, guess."""
    accounts, passwords, tmp = store
    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(AuthenticationError):
            accounts.verify("drm", "wrong")

    reloaded = AccountStore.load(tmp / "accounts.json")
    with pytest.raises(AuthenticationError) as exc:
        reloaded.verify("drm", passwords["drm"])
    assert "locked" in str(exc.value)


def test_a_successful_sign_in_clears_the_failure_count(store):
    accounts, passwords, _ = store
    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        with pytest.raises(AuthenticationError):
            accounts.verify("drm", "wrong")
    accounts.verify("drm", passwords["drm"])
    assert accounts.get("drm").failed_attempts == 0


def test_a_disabled_account_cannot_sign_in(store):
    accounts, passwords, _ = store
    accounts.set_disabled("drm", True)
    with pytest.raises(AuthenticationError):
        accounts.verify("drm", passwords["drm"])


def test_a_forged_hash_does_not_grant_access(tmp_path):
    """Writing a hash you chose into the file gets you in only if you know its input."""
    accounts, _ = bootstrap(tmp_path / "accounts.json")
    victim = accounts.get("drm")
    other = new_account("tmp", "Tmp", Role.DRM, GOOD_PASSWORD)
    victim.password_hash = other.password_hash        # stolen hash, wrong salt
    with pytest.raises(AuthenticationError):
        accounts.verify("drm", GOOD_PASSWORD)


def test_an_empty_accounts_file_is_refused(tmp_path):
    p = tmp_path / "accounts.json"
    p.write_text(json.dumps({"accounts": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="no accounts"):
        AccountStore.load(p)


def test_an_account_with_no_hash_is_refused(tmp_path):
    p = tmp_path / "accounts.json"
    p.write_text(json.dumps({"accounts": [
        {"username": "x", "role": "DRM", "salt": "aa"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="no password hash"):
        AccountStore.load(p)


def test_an_unknown_role_is_refused(tmp_path):
    p = tmp_path / "accounts.json"
    p.write_text(json.dumps({"accounts": [
        {"username": "x", "role": "Emperor", "salt": "aa", "password_hash": "bb"}]}),
        encoding="utf-8")
    with pytest.raises(ValueError, match="unusable role"):
        AccountStore.load(p)


def test_a_second_start_reuses_the_file_and_mints_nothing(store):
    accounts, passwords, tmp = store
    again, minted = load_or_bootstrap(tmp / "accounts.json")
    assert minted is None, "a restart minted a second set of passwords"
    assert again.verify("drm", passwords["drm"]).role is Role.DRM


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #

def test_signing_in_issues_a_session_that_resolves(service):
    result = service.login("drm", service.minted["drm"])
    account, session = service.resolve(result.token)
    assert account.username == "drm"
    assert session.expiry_reason() is None


def test_the_session_file_holds_no_usable_token(service, tmp_path):
    result = service.login("drm", service.minted["drm"])
    raw = (tmp_path / "sessions.json").read_text(encoding="utf-8")
    assert result.token not in raw
    assert hash_token(result.token) in raw


def test_an_unknown_token_is_refused(service):
    service.login("drm", service.minted["drm"])
    with pytest.raises(AuthenticationError):
        service.resolve("not-a-real-token")


@pytest.mark.parametrize("empty", ["", None])
def test_no_token_is_refused(service, empty):
    with pytest.raises(AuthenticationError):
        service.resolve(empty)


def test_a_token_prefix_does_not_resolve(service):
    result = service.login("drm", service.minted["drm"])
    for cut in (4, len(result.token) // 2, len(result.token) - 1):
        with pytest.raises(AuthenticationError):
            service.resolve(result.token[:cut])


def test_two_sign_ins_get_different_tokens(service):
    a = service.login("drm", service.minted["drm"])
    b = service.login("drm", service.minted["drm"])
    assert a.token != b.token
    assert service.resolve(a.token)[0].username == "drm"
    assert service.resolve(b.token)[0].username == "drm"


def test_signing_out_ends_that_session_and_no_other(service):
    a = service.login("drm", service.minted["drm"])
    b = service.login("drm", service.minted["drm"])
    service.logout(a.token)

    with pytest.raises(AuthenticationError):
        service.resolve(a.token)
    assert service.resolve(b.token)[0].username == "drm"


def test_an_expired_session_is_refused(service):
    """The absolute clock. A field that is written and never read is not an expiry."""
    result = service.login("drm", service.minted["drm"])
    session = service.sessions._by_hash[hash_token(result.token)]
    session.expires_at = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)).isoformat()

    with pytest.raises(AuthenticationError, match="expired"):
        service.resolve(result.token)


def test_an_idle_session_is_refused(service):
    """The second clock, for the screen somebody walked away from."""
    result = service.login("drm", service.minted["drm"])
    session = service.sessions._by_hash[hash_token(result.token)]
    session.last_seen = (
        dt.datetime.now(dt.timezone.utc)
        - dt.timedelta(minutes=IDLE_TIMEOUT_MINUTES + 1)).isoformat()

    with pytest.raises(AuthenticationError, match="idle"):
        service.resolve(result.token)


def test_use_moves_the_idle_clock_but_not_the_absolute_one(service):
    result = service.login("drm", service.minted["drm"])
    session = service.sessions._by_hash[hash_token(result.token)]
    expiry_before = session.expires_at

    session.last_seen = (
        dt.datetime.now(dt.timezone.utc)
        - dt.timedelta(minutes=IDLE_TIMEOUT_MINUTES - 1)).isoformat()
    service.resolve(result.token)

    assert session.expires_at == expiry_before, (
        "using a session extended its absolute lifetime -- it can now live forever"
    )
    assert session.expiry_reason() is None


def test_the_absolute_lifetime_is_bounded(service):
    result = service.login("drm", service.minted["drm"])
    issued = dt.datetime.fromisoformat(result.session.issued_at)
    expires = dt.datetime.fromisoformat(result.session.expires_at)
    assert expires - issued <= dt.timedelta(hours=ABSOLUTE_LIFETIME_HOURS)


def test_a_session_survives_a_restart(tmp_path):
    """A service that signed everyone out on restart would be unusable here."""
    first = AuthService(tmp_path / "a.json", tmp_path / "s.json", tmp_path / "l.jsonl")
    result = first.login("drm", first.minted["drm"])

    second = AuthService(tmp_path / "a.json", tmp_path / "s.json", tmp_path / "l.jsonl")
    assert second.resolve(result.token)[0].username == "drm"


def test_changing_the_password_ends_every_other_session(service):
    """The half-measure that matters: the person doing this believes it locks others out."""
    elsewhere = service.login("drm", service.minted["drm"])
    here = service.login("drm", service.minted["drm"])

    service.change_password(here.token, service.minted["drm"], GOOD_PASSWORD)

    with pytest.raises(AuthenticationError):
        service.resolve(elsewhere.token)
    assert service.resolve(here.token)[0].username == "drm", (
        "changing your own password signed you out of the session you did it from"
    )


def test_changing_a_password_needs_the_current_one(service):
    """A live session proves the screen was signed in, not who is at it now."""
    result = service.login("drm", service.minted["drm"])
    with pytest.raises(AuthenticationError):
        service.change_password(result.token, "not-the-current-one", GOOD_PASSWORD)


def test_the_new_password_must_differ(service):
    result = service.login("drm", service.minted["drm"])
    with pytest.raises(PasswordPolicyError):
        service.change_password(result.token, service.minted["drm"],
                                service.minted["drm"])


def test_disabling_an_account_ends_its_live_sessions(service):
    result = service.login("drm", service.minted["drm"])
    service.accounts.set_disabled("drm", True)
    with pytest.raises(AuthenticationError):
        service.resolve(result.token)


def test_revoking_everything_for_an_account_leaves_others_alone(service):
    drm = service.login("drm", service.minted["drm"])
    je = service.login("je", service.minted["je"])

    ended = service.revoke_all_for("drm")
    assert ended == 1
    with pytest.raises(AuthenticationError):
        service.resolve(drm.token)
    assert service.resolve(je.token)[0].username == "je"


def test_a_corrupt_session_file_signs_everyone_out_without_stopping_the_service(tmp_path):
    (tmp_path / "s.json").write_text("{not json", encoding="utf-8")
    store = SessionStore.load(tmp_path / "s.json")
    assert len(store) == 0


# --------------------------------------------------------------------------- #
# The sign-in trail
# --------------------------------------------------------------------------- #

def test_sign_ins_and_refusals_are_both_recorded(service):
    """Five failures against `drm` is the signal, and only exists if refusals are kept."""
    service.login("drm", service.minted["drm"])
    with pytest.raises(AuthenticationError):
        service.login("drm", "wrong")

    actions = [e.action for e in service.trail]
    assert "SIGN_IN" in actions
    assert "SIGN_IN_DENIED" in actions


def test_the_trail_never_records_a_password_or_a_token(service):
    result = service.login("drm", service.minted["drm"])
    with pytest.raises(AuthenticationError):
        service.login("drm", "hunter2-the-wrong-one")
    service.change_password(result.token, service.minted["drm"], GOOD_PASSWORD)

    body = json.dumps([e.to_dict() for e in service.trail])
    for secret in (result.token, service.minted["drm"], GOOD_PASSWORD,
                   "hunter2-the-wrong-one"):
        assert secret not in body, "a secret reached the auth trail"


def test_the_trail_is_hash_chained(service):
    service.login("drm", service.minted["drm"])
    with pytest.raises(AuthenticationError):
        service.login("drm", "wrong")
    assert service.trail.verify().intact

    # Soften a refusal after the fact, as somebody covering their tracks would.
    service.trail._entries[-1].detail["reason"] = "nothing to see"
    assert not service.trail.verify().intact


def test_a_refusal_is_recorded_against_the_username_that_was_tried(service):
    with pytest.raises(AuthenticationError):
        service.login("drm", "wrong")
    denied = [e for e in service.trail if e.action == "SIGN_IN_DENIED"]
    assert denied and denied[-1].actor == "drm"
