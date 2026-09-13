"""Sessions: staying signed in, and being able to stop.

A password proves who you are once. A session is what carries that proof across the next
few hours of requests, and it is the half of a login system that decides whether "revoke
this person's access" is a button or a rebuild.

The wire format is unchanged from the token scheme this replaces -- `Authorization:
Bearer <token>` -- so `caller()`, the approval workflow and the audit trail never learn
that anything happened. What changed is everything behind the token:

  * it is issued by proving a password, not printed at startup;
  * it belongs to a PERSON, not to a role, so "the DRM sanctioned this" names somebody;
  * it expires, twice over -- an absolute lifetime and an idle timeout;
  * it can be revoked, individually or for a whole account, without touching anyone else.

Opaque server-side sessions rather than JWTs, and that is the whole reason. A signed token
that carries its own claims cannot be withdrawn before it expires without building the
revocation list you were trying to avoid -- and for a system whose point is that authority
is checked, "we cannot actually stop them until Tuesday" is the wrong answer.

Only the SHA-256 of a token is stored. The file therefore says who is signed in and until
when, which is worth protecting, but cannot be used to sign in as them.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from pathlib import Path

from .accounts import Account, AccountStore, AuthenticationError

# 32 bytes of urandom. Guessing is not a strategy against this and never becomes one.
SESSION_TOKEN_BYTES = 32

# Two clocks, because they fail differently. The absolute lifetime bounds the damage from
# a token that leaks and is used quietly; the idle timeout covers the control-room case
# this is actually built for -- somebody signs in, walks away, and the next person sits
# down at a screen that is still authenticated as a DRM.
ABSOLUTE_LIFETIME_HOURS = 12
IDLE_TIMEOUT_MINUTES = 60

# How stale `last_seen` may get on disk before a request rewrites the file. Well under
# the idle timeout, so a restart can never resurrect a session that should have lapsed,
# and coarse enough that a burst of requests is not a burst of writes.
LAST_SEEN_WRITE_SECONDS = 60


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(moment: dt.datetime) -> str:
    return moment.isoformat()


def _parse(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class Session:
    """One signed-in person, until they sign out or one of the two clocks runs down."""

    token_hash: str
    username: str
    issued_at: str
    expires_at: str            # absolute -- never extended
    last_seen: str             # moved forward on every accepted request
    revoked_at: str | None = None
    user_agent: str = ""       # trimmed; for the trail, not for any decision

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def expiry_reason(self, at: dt.datetime | None = None) -> str | None:
        """Why this session is no longer usable, or None if it still is.

        A reason rather than a bool because the client can act on the difference: an idle
        timeout means sign in again, and a revoked session may mean somebody else ended
        it deliberately.
        """
        moment = at or _now()
        if self.is_revoked:
            # Signed out, password changed, or access withdrawn -- the client is told it
            # has to sign in again, not which of the three happened to it.
            return "session was ended"
        absolute = _parse(self.expires_at)
        if absolute is None or moment >= absolute:
            return "session expired"
        seen = _parse(self.last_seen)
        if seen is None or moment - seen > dt.timedelta(minutes=IDLE_TIMEOUT_MINUTES):
            return f"session idle for more than {IDLE_TIMEOUT_MINUTES} minutes"
        return None

    def to_dict(self) -> dict:
        return {
            "token_hash": self.token_hash,
            "username": self.username,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "last_seen": self.last_seen,
            "revoked_at": self.revoked_at,
            "user_agent": self.user_agent,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Session":
        return cls(
            token_hash=raw["token_hash"],
            username=raw["username"],
            issued_at=raw["issued_at"],
            expires_at=raw["expires_at"],
            last_seen=raw.get("last_seen") or raw["issued_at"],
            revoked_at=raw.get("revoked_at"),
            user_agent=raw.get("user_agent", ""),
        )


class SessionStore:
    """Live sessions, persisted so a restart does not sign everybody out.

    Persistence is a deliberate choice and it cuts both ways: a service that forgot its
    sessions on restart would be safer by accident and unusable in practice, because this
    one restarts whenever a plan is re-solved from the command line. Expiry and revocation
    are what make it safe on purpose instead.
    """

    def __init__(self, sessions: list[Session] | None = None, path: Path | None = None):
        self._by_hash: dict[str, Session] = {s.token_hash: s for s in (sessions or [])}
        self.path = Path(path) if path else None

    # ------------------------------------------------------------------ #

    @classmethod
    def load(cls, path: Path) -> "SessionStore":
        path = Path(path)
        if not path.exists():
            return cls([], path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A corrupt session file signs everyone out; it does not stop the service.
            # The alternative -- refusing to start -- turns a recoverable annoyance into
            # an outage, and there is nothing here that cannot be recreated by signing in.
            return cls([], path)
        store = cls([Session.from_dict(s) for s in raw.get("sessions", [])], path)
        store.purge()
        return store

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "_comment": (
                "Live TRACKSEN sessions. Tokens are stored as SHA-256 hashes: this file "
                "says who is signed in and until when, and cannot be used to sign in."
            ),
            "sessions": [s.to_dict() for s in self._by_hash.values()],
        }
        tmp = self.path.with_suffix(self.path.suffix + ".partial")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    # ------------------------------------------------------------------ #

    def issue(self, account: Account, user_agent: str = "") -> tuple[str, Session]:
        """Mint a session for an account. The token is returned once and never stored."""
        token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
        now = _now()
        session = Session(
            token_hash=hash_token(token),
            username=account.username,
            issued_at=_iso(now),
            expires_at=_iso(now + dt.timedelta(hours=ABSOLUTE_LIFETIME_HOURS)),
            last_seen=_iso(now),
            user_agent=(user_agent or "")[:200],
        )
        self._by_hash[session.token_hash] = session
        self.purge()
        self.save()
        return token, session

    def resolve(self, token: str | None, accounts: AccountStore) -> tuple[Account, Session]:
        """The account this session belongs to, or refuse with a reason.

        Compared in constant time against every live session. A dictionary lookup on the
        hash would be faster and would also leak, through timing, whether a prefix was
        right -- and the whole point of this layer is that the answer to "who are you" is
        not negotiable from the client side.

        `last_seen` moves forward on success, which is what makes the idle timeout an
        idle timeout rather than a second absolute one.
        """
        if not token:
            raise AuthenticationError("no session token supplied")

        candidate = hash_token(token)
        found: Session | None = None
        for session in self._by_hash.values():
            if hmac.compare_digest(candidate, session.token_hash):
                found = session
        if found is None:
            raise AuthenticationError("session not recognised")

        reason = found.expiry_reason()
        if reason:
            raise AuthenticationError(reason)

        account = accounts.get(found.username)
        if account is None:
            # The account was removed while a session was live. The session is worthless
            # and should not survive the discovery.
            self.revoke(token)
            raise AuthenticationError("account no longer exists")
        if account.disabled:
            self.revoke_all_for(account.username)
            raise AuthenticationError("account is disabled")

        # Persisted only when it has actually moved, not on every request. The idle
        # timeout works off this field, so it has to advance -- but rewriting the whole
        # file on each authenticated call is disk churn for a value nothing reads at that
        # resolution.
        now = _now()
        previous = _parse(found.last_seen)
        found.last_seen = _iso(now)
        if previous is None or (now - previous) > dt.timedelta(seconds=LAST_SEEN_WRITE_SECONDS):
            self.save()
        return account, found

    def revoke(self, token: str) -> bool:
        session = self._by_hash.get(hash_token(token))
        if session is None or session.is_revoked:
            return False
        session.revoked_at = _iso(_now())
        self.save()
        return True

    def revoke_all_for(self, username: str, except_token: str | None = None) -> int:
        """Sign an account out everywhere. Used on password change and on disable.

        A password change that left old sessions alive would be the most dangerous kind
        of half-measure: the person doing it believes they have just locked somebody out,
        and they have not.
        """
        keep = hash_token(except_token) if except_token else None
        n = 0
        for session in self._by_hash.values():
            if session.username != username or session.is_revoked:
                continue
            if keep and hmac.compare_digest(session.token_hash, keep):
                continue
            session.revoked_at = _iso(_now())
            n += 1
        if n:
            self.save()
        return n

    def sessions_for(self, username: str) -> list[Session]:
        return [s for s in self._by_hash.values()
                if s.username == username and s.expiry_reason() is None]

    def purge(self) -> int:
        """Drop sessions nobody can use any more, so the file does not grow forever."""
        dead = [h for h, s in self._by_hash.items() if s.expiry_reason() is not None]
        for h in dead:
            del self._by_hash[h]
        return len(dead)

    def __len__(self) -> int:
        return len(self._by_hash)
