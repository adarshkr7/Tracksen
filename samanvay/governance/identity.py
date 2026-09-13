"""The login service: accounts, sessions and the trail of who signed in.

`accounts.py` knows how to prove somebody is who they say. `sessions.py` knows how to
carry that proof for the next few hours and how to take it away. This is the one object
that puts them together, so that the service has a single seam to a real directory rather
than three, and so that every path that grants or withdraws access records that it did.

    auth = AuthService(ACCOUNTS_PATH, SESSIONS_PATH, AUTH_LOG_PATH)
    result = auth.login("drm", password, user_agent="...")   -> token
    account, session = auth.resolve(token)                   -> who is calling
    auth.logout(token)

WHY THE SIGN-IN TRAIL IS HASH-CHAINED TOO

The plan audit log answers "who sanctioned this, and on whose authority". It is only as
strong as the claim that the person named is the person who acted. A sign-in record that
could be quietly edited afterwards -- to remove the failed attempts that preceded a
sanction, say -- would undercut the log it is supposed to support. It is the same
`AuditLog` machinery, in its own file, so the two trails verify independently and a plan's
history is not cluttered with sessions.

A password is never written to it, obviously. Neither is a session token: the trail names
people and events, never secrets.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .accounts import (
    Account,
    AccountStore,
    AuthenticationError,
    PasswordPolicyError,
    check_password_policy,
)
from .audit import AuditLog
from .sessions import Session, SessionStore
from .workflow import Actor

# Actions in the auth trail. Strings rather than the plan `Action` enum, which is
# documented as "everything that can happen to a plan" and should stay that way.
SIGN_IN = "SIGN_IN"
SIGN_IN_DENIED = "SIGN_IN_DENIED"
SIGN_OUT = "SIGN_OUT"
PASSWORD_CHANGED = "PASSWORD_CHANGED"
SESSIONS_REVOKED = "SESSIONS_REVOKED"

# The auth trail is not about plans, and inventing a plan id for it would make the field
# lie. This is the explicit absence.
NO_PLAN = "-"


@dataclass(frozen=True)
class LoginResult:
    """What a successful sign-in hands back. The token appears here and nowhere else."""

    token: str
    account: Account
    session: Session

    @property
    def actor(self) -> Actor:
        return self.account.actor

    def to_dict(self) -> dict:
        return {
            "token": self.token,
            "name": self.account.display_name,
            "username": self.account.username,
            "role": self.account.role.value,
            "expires_at": self.session.expires_at,
            "must_change_password": self.account.must_change_password,
        }


class AuthService:
    """Sign in, stay signed in, stop being signed in."""

    def __init__(self, accounts_path: Path, sessions_path: Path,
                 auth_log_path: Path | None = None):
        from .accounts import load_or_bootstrap

        self.accounts, self.minted = load_or_bootstrap(Path(accounts_path))
        self.sessions = SessionStore.load(Path(sessions_path))
        self.trail = AuditLog(Path(auth_log_path)) if auth_log_path else None

    # ------------------------------------------------------------------ #

    def _record(self, action: str, *, actor: str, role: str, detail: dict) -> None:
        if self.trail is None:
            return
        self.trail.append(actor=actor, role=role, action=action,
                          plan_id=NO_PLAN, detail=detail)

    # ------------------------------------------------------------------ #

    def login(self, username: str, password: str, user_agent: str = "") -> LoginResult:
        """Verify a password and issue a session, or refuse and record the refusal.

        A refused attempt is recorded against the username that was TRIED, which may not
        name anybody. That is the point: five failures against `drm` from one afternoon is
        the signal, and it does not exist if only successful sign-ins are written down.
        """
        attempted = (username or "").strip().lower()
        try:
            account = self.accounts.verify(attempted, password)
        except AuthenticationError as exc:
            self._record(SIGN_IN_DENIED, actor=attempted or "(blank)", role="-",
                         detail={"reason": str(exc), "user_agent": user_agent[:200]})
            raise

        token, session = self.sessions.issue(account, user_agent=user_agent)
        self._record(SIGN_IN, actor=account.display_name, role=account.role.value,
                     detail={"username": account.username,
                             "expires_at": session.expires_at,
                             "must_change_password": account.must_change_password})
        return LoginResult(token=token, account=account, session=session)

    def resolve(self, token: str | None) -> tuple[Account, Session]:
        """Who is calling. Raises `AuthenticationError` with a reason the client can use."""
        return self.sessions.resolve(token, self.accounts)

    def actor(self, token: str | None) -> Actor:
        account, _ = self.resolve(token)
        return account.actor

    def logout(self, token: str) -> bool:
        """End one session. Idempotent: signing out twice is not an error worth raising."""
        try:
            account, _ = self.resolve(token)
            who, role = account.display_name, account.role.value
        except AuthenticationError:
            who, role = "(unknown)", "-"
        ended = self.sessions.revoke(token)
        if ended:
            self._record(SIGN_OUT, actor=who, role=role, detail={})
        return ended

    def change_password(self, token: str, current_password: str,
                        new_password: str) -> Account:
        """Change your own password, then sign out everywhere else.

        The current password is required even though the caller already holds a valid
        session. A session proves the screen was signed in at some point, not that the
        person at it now is the same one -- which is the exact situation an idle timeout
        is for, and an unlocked terminal is how it goes wrong.

        Every other session for the account is revoked. A password change that left the
        old ones alive is the most dangerous kind of half-measure: the person doing it
        believes they have just locked somebody out, and they have not.
        """
        account, _ = self.resolve(token)

        if not current_password or not account.matches(current_password):
            self._record(SIGN_IN_DENIED, actor=account.display_name,
                         role=account.role.value,
                         detail={"reason": "wrong current password on change"})
            raise AuthenticationError("current password is not correct")

        check_password_policy(new_password)
        if account.matches(new_password):
            raise PasswordPolicyError("the new password must differ from the current one")

        self.accounts.set_password(account.username, new_password)
        ended = self.sessions.revoke_all_for(account.username, except_token=token)
        self._record(PASSWORD_CHANGED, actor=account.display_name,
                     role=account.role.value,
                     detail={"other_sessions_ended": ended})
        return account

    def revoke_all_for(self, username: str, by: Actor | None = None) -> int:
        """Sign an account out everywhere. The administrative half of revocation."""
        ended = self.sessions.revoke_all_for(username)
        if ended:
            self._record(SESSIONS_REVOKED,
                         actor=by.name if by else "system",
                         role=by.role.value if by else "-",
                         detail={"username": username, "sessions_ended": ended})
        return ended


__all__ = [
    "Account", "AccountStore", "AuthService", "AuthenticationError", "LoginResult",
    "PasswordPolicyError", "Session", "SessionStore",
    "SIGN_IN", "SIGN_IN_DENIED", "SIGN_OUT", "PASSWORD_CHANGED", "SESSIONS_REVOKED",
]
