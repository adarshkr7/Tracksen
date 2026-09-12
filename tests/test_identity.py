"""Authentication: the server decides who is calling.

Until this existed the caller sent `{"role": "DRM"}` and was believed, so every rule in
`workflow.py` was one JSON field away from being nothing. These tests are about that
field being gone, not merely validated.
"""

from __future__ import annotations

import json

import pytest

from samanvay.governance import (
    Actor,
    AuthenticationError,
    Identity,
    IdentityStore,
    Role,
    bootstrap,
    hash_token,
    load_or_bootstrap,
)


@pytest.fixture
def store(tmp_path):
    s, tokens = bootstrap(tmp_path / "identities.json")
    return s, tokens, tmp_path / "identities.json"


# --------------------------------------------------------------------------- #
# Resolving
# --------------------------------------------------------------------------- #

def test_a_valid_token_resolves_to_its_role(store):
    s, tokens, _ = store
    actor = s.resolve(tokens["DRM"])
    assert actor.role is Role.DRM
    assert isinstance(actor, Actor)


def test_every_role_gets_a_working_token(store):
    """The bootstrap set has to walk the whole route, or the gates go untested."""
    s, tokens, _ = store
    for role in Role:
        assert role.value in tokens, f"no bootstrap identity for {role.value}"
        assert s.resolve(tokens[role.value]).role is role


def test_an_unknown_token_is_refused(store):
    s, _, _ = store
    with pytest.raises(AuthenticationError):
        s.resolve("not-a-real-token")


def test_no_token_is_refused(store):
    s, _, _ = store
    for empty in (None, "", "   "):
        with pytest.raises(AuthenticationError):
            s.resolve(empty)


def test_a_token_prefix_does_not_resolve(store):
    """Guards against any lookup that would accept a partial match."""
    s, tokens, _ = store
    real = tokens["DRM"]
    for truncated in (real[:-1], real[:8], real + "x"):
        with pytest.raises(AuthenticationError):
            s.resolve(truncated)


# --------------------------------------------------------------------------- #
# What is stored
# --------------------------------------------------------------------------- #

def test_the_identity_file_holds_no_plaintext_token(store):
    """Losing the file must not hand over the ability to act as anyone."""
    _, tokens, path = store
    raw = path.read_text(encoding="utf-8")
    for role, token in tokens.items():
        assert token not in raw, f"the {role} token is sitting in the identity file"


def test_stored_hashes_match_the_minted_tokens(store):
    _, tokens, path = store
    stored = {i["role"]: i["token_hash"]
              for i in json.loads(path.read_text(encoding="utf-8"))["identities"]}
    for role, token in tokens.items():
        assert stored[role] == hash_token(token)


def test_tokens_are_unique_and_not_guessable(store):
    _, tokens, _ = store
    assert len(set(tokens.values())) == len(tokens), "two identities share a token"
    for token in tokens.values():
        assert len(token) >= 24, "a short token is a guessable one"


def test_a_second_start_reuses_the_file_and_mints_nothing(store):
    """Re-minting on every start would invalidate everyone's token on a restart."""
    _, tokens, path = store
    again, minted = load_or_bootstrap(path)
    assert minted is None, "restarting the service minted a fresh set of tokens"
    assert again.resolve(tokens["DRM"]).role is Role.DRM


# --------------------------------------------------------------------------- #
# Refusing a broken file rather than falling back
# --------------------------------------------------------------------------- #

def test_an_empty_identity_file_is_refused(tmp_path):
    """An empty file must not mean "let everybody in"."""
    p = tmp_path / "identities.json"
    p.write_text(json.dumps({"identities": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="no identities"):
        IdentityStore.load(p)


def test_an_identity_with_no_token_hash_is_refused(tmp_path):
    p = tmp_path / "identities.json"
    p.write_text(json.dumps({"identities": [{"name": "X", "role": "DRM"}]}),
                 encoding="utf-8")
    with pytest.raises(ValueError, match="no token_hash"):
        IdentityStore.load(p)


def test_an_unknown_role_is_refused(tmp_path):
    p = tmp_path / "identities.json"
    p.write_text(json.dumps({"identities": [
        {"name": "X", "role": "Emperor", "token_hash": "a" * 64}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="unusable role"):
        IdentityStore.load(p)


def test_a_forged_hash_does_not_grant_access(tmp_path):
    """Writing a hash into the file is not the same as knowing the token.

    Someone who can edit the identity file can of course add their own identity -- that
    is what file permissions are for. What they cannot do is take an existing entry and
    work back to a token, which is the property that makes storing hashes worth anything.
    """
    s = IdentityStore([Identity("Forged", Role.DRM, hash_token("secret"))])
    with pytest.raises(AuthenticationError):
        s.resolve(hash_token("secret"))      # presenting the hash is not the token
    assert s.resolve("secret").role is Role.DRM
