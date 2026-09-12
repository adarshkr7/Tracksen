"""Who is calling, decided by the server.

The workflow rules were always real -- only the DRM may sanction, a head may concur only
for their own department, a refusal is recorded. What was not real was the identity they
were enforced against: the caller sent `{"actor": "...", "role": "DRM"}` and was believed.
Every rule in `workflow.py` was one JSON field away from being nothing at all.

This module is the other half. A caller presents a bearer token; the token resolves to a
name and a role held here; and the role in the request body is ignored entirely -- not
validated, not preferred, ignored, because a field that is sometimes trusted eventually
is.

WHAT THIS IS AND IS NOT

It is real authentication: a caller must possess a secret to act, secrets are stored as
hashes so the identity file is not a password list, and comparison is constant-time.

It is not a directory. A division runs on its own AD or SSO, and a deployment binds
`IdentityStore.resolve` to that instead. The seam is one function wide on purpose. What
matters is that the seam is on the server side of the wire, which is the part that was
missing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from pathlib import Path

from .workflow import Actor, Role

# Long enough that guessing is not a strategy, short enough to paste.
TOKEN_BYTES = 24


class AuthenticationError(Exception):
    """No identity could be established. Distinct from 'not permitted'.

    401 and 403 are different answers and the caller can act on the difference: one means
    sign in, the other means you did and it is not your decision to make.
    """


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Identity:
    """One person the service will accept, and what they may do."""

    name: str
    role: Role
    token_hash: str

    @property
    def actor(self) -> Actor:
        return Actor(self.name, self.role)

    def to_dict(self) -> dict:
        return {"name": self.name, "role": self.role.value,
                "token_hash": self.token_hash}


class IdentityStore:
    """Bearer token -> Actor, backed by a file of hashed tokens.

    The file holds no plaintext token. Losing it therefore leaks who may act and in what
    capacity -- worth protecting -- but not the ability to act as them.
    """

    def __init__(self, identities: list[Identity]):
        self._by_hash = {i.token_hash: i for i in identities}
        self.identities = list(identities)

    # ------------------------------------------------------------------ #

    @classmethod
    def load(cls, path: Path) -> "IdentityStore":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        out = []
        for entry in raw.get("identities", []):
            try:
                role = Role(entry["role"])
            except (KeyError, ValueError) as exc:
                raise ValueError(
                    f"{path}: identity {entry.get('name', '?')!r} has an unusable role "
                    f"{entry.get('role')!r}; expected one of "
                    f"{', '.join(r.value for r in Role)}"
                ) from exc
            if not entry.get("token_hash"):
                raise ValueError(
                    f"{path}: identity {entry.get('name', '?')!r} has no token_hash. "
                    "Tokens are stored hashed; write the hash, never the token."
                )
            out.append(Identity(entry["name"], role, entry["token_hash"]))
        if not out:
            raise ValueError(f"{path}: no identities. A service nobody can act on is "
                             "not a safe default, it is a broken one.")
        return cls(out)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "_comment": (
                "Bearer tokens for the TRACKSEN approval route. Tokens are stored as "
                "SHA-256 hashes: this file cannot be used to obtain one. Keep it out of "
                "version control anyway -- it names who may sanction."
            ),
            "identities": [i.to_dict() for i in self.identities],
        }
        tmp = path.with_suffix(path.suffix + ".partial")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)

    # ------------------------------------------------------------------ #

    def resolve(self, token: str | None) -> Actor:
        """The actor this token belongs to, or refuse.

        Compared in constant time against every known hash. A dictionary lookup on the
        hash would be faster and would also leak, through timing, whether a prefix was
        right -- and the whole point of this module is that the answer to "who are you"
        is not negotiable from the client side.
        """
        if not token:
            raise AuthenticationError("no bearer token supplied")

        candidate = hash_token(token)
        found: Identity | None = None
        for identity in self.identities:
            if hmac.compare_digest(candidate, identity.token_hash):
                found = identity
        if found is None:
            raise AuthenticationError("token not recognised")
        return found.actor

    def __len__(self) -> int:
        return len(self.identities)


# --------------------------------------------------------------------------- #
# First run
# --------------------------------------------------------------------------- #

# One identity per role, so the whole approval route can be walked end to end. A real
# deployment has one per person and several people per role; this is the smallest set
# that exercises every gate.
BOOTSTRAP_ROLES: list[tuple[str, Role]] = [
    ("JE (demo)", Role.JE),
    ("Sr.DEN (demo)", Role.SR_DEN),
    ("Sr.DSTE (demo)", Role.SR_DSTE),
    ("Sr.DEE/TrD (demo)", Role.SR_DEE),
    ("Sr.DOM (demo)", Role.SR_DOM),
    ("DRM (demo)", Role.DRM),
    ("Viewer (demo)", Role.VIEWER),
]


def bootstrap(path: Path) -> tuple["IdentityStore", dict[str, str]]:
    """Create an identity file with fresh random tokens. Returns the tokens ONCE.

    Deliberately not a bypass. A service that fell back to "trust the caller" when no
    identity file was present would have an authentication system and a hole beside it,
    and the hole is what would get used. Instead the first run mints real secrets, prints
    them once, and never stores them.
    """
    tokens: dict[str, str] = {}
    identities: list[Identity] = []
    for name, role in BOOTSTRAP_ROLES:
        token = secrets.token_urlsafe(TOKEN_BYTES)
        tokens[role.value] = token
        identities.append(Identity(name, role, hash_token(token)))

    store = IdentityStore(identities)
    store.save(path)
    return store, tokens


def load_or_bootstrap(path: Path) -> tuple["IdentityStore", dict[str, str] | None]:
    """Load the identity file, creating one on first run. Tokens returned only if minted."""
    path = Path(path)
    if path.exists():
        return IdentityStore.load(path), None
    return bootstrap(path)
