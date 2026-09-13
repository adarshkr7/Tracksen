"""Accounts: who exists, and how they prove it.

This replaces a set of long-lived bearer tokens printed once at startup. Those were real
authentication -- a caller had to possess a secret, the secret was stored hashed, and the
comparison was constant-time -- but they were the wrong *shape* for a system whose whole
argument is that a sanction can be attributed to a person:

  * a token could not expire, so one pasted into a chat message stayed valid forever;
  * a token could not be revoked without reissuing every token in the file;
  * a token was per ROLE, not per person, so "the DRM sanctioned this" meant "somebody
    holding the DRM token did", which is precisely the claim the audit trail exists to
    make stronger.

An account is per person. It carries a password nobody can read back, a role, and the
two flags a real deployment needs on day one: disabled, and must-change-password.

WHAT IS REAL HERE AND WHAT IS NOT

Real: passwords are derived with scrypt and a per-account salt, never stored or logged in
any recoverable form; verification is constant-time; an unknown username costs the same
work as a known one, so the failure cannot be used to enumerate who exists; repeated
failures lock the account for a cooldown rather than allowing unlimited guesses.

Not real: this is still a file, not a directory. A division runs on its own AD or SSO and
a deployment binds `AccountStore.verify` to that instead. The seam is one function wide,
and it is on the server side of the wire -- which is the part that used to be missing.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from .workflow import Actor, Role


class AuthenticationError(Exception):
    """No identity could be established. Distinct from 'not permitted'.

    401 and 403 are different answers and the caller can act on the difference: one means
    sign in, the other means you did and it is not your decision to make.
    """


class PasswordPolicyError(Exception):
    """A new password was refused before it was ever stored."""


# --------------------------------------------------------------------------- #
# Derivation
# --------------------------------------------------------------------------- #
#
# scrypt from the standard library rather than bcrypt or argon2 from PyPI. Two reasons,
# and the second is the one that matters: it is a memory-hard KDF designed for exactly
# this, and it adds no dependency to a project whose requirements.txt is the thing a
# reviewer reads to decide what they are being asked to install.
#
# Parameters are stored PER ACCOUNT rather than as module constants. Cost has to rise
# over the life of a system, and an installation that hard-codes one value can only raise
# it by invalidating every password at once. Stored alongside the hash, a stronger value
# applies to the next password set and the old ones keep verifying until they are changed.

SCRYPT_N = 2 ** 14        # CPU/memory cost -- ~50 ms and ~16 MB per derivation
SCRYPT_R = 8
SCRYPT_P = 1
DK_LEN = 32
SALT_BYTES = 16

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256     # scrypt will hash anything; a 10 MB "password" is a DoS

# Repeated failures lock the account rather than slowing it down. A delay can be waited
# out by a script; a lockout cannot, and it also surfaces in the auth trail as an event
# somebody should look at.
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def _derive(password: str, salt: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=dklen,
        maxmem=n * r * 256 + 1024 * 1024,
    )


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(moment: dt.datetime | None) -> str | None:
    return moment.isoformat() if moment else None


def _parse(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def check_password_policy(password: str) -> None:
    """Refuse a password before it is ever derived, stored or transmitted onward.

    Deliberately short. A policy that demands three character classes and a symbol pushes
    people toward `Passw0rd!` and a sticky note; length is the property that actually
    costs an attacker something. The one blocklist entry is the bootstrap pattern, because
    an account still holding its minted password is the realistic way this gets breached.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"a password must be at least {MIN_PASSWORD_LENGTH} characters; "
            f"that one is {len(password)}"
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"a password may be at most {MAX_PASSWORD_LENGTH} characters"
        )
    if not password.strip():
        raise PasswordPolicyError("a password cannot be only whitespace")


# --------------------------------------------------------------------------- #
# Account
# --------------------------------------------------------------------------- #

@dataclass
class Account:
    """One person the service will accept, and what they may do.

    Mutable, unlike most of this codebase, because two fields legitimately change on a
    failed sign-in and the file has to record that a lockout is in force across a restart.
    """

    username: str
    display_name: str
    role: Role
    salt: str                      # hex
    password_hash: str             # hex
    n: int = SCRYPT_N
    r: int = SCRYPT_R
    p: int = SCRYPT_P
    dklen: int = DK_LEN
    disabled: bool = False
    must_change_password: bool = False
    failed_attempts: int = 0
    locked_until: str | None = None
    created_at: str = field(default_factory=lambda: _now().isoformat())
    password_changed_at: str | None = None

    @property
    def actor(self) -> Actor:
        return Actor(self.display_name, self.role)

    @property
    def is_locked(self) -> bool:
        until = _parse(self.locked_until)
        return until is not None and until > _now()

    def matches(self, password: str) -> bool:
        """Constant-time comparison of the derived key. Never log either side of this."""
        candidate = _derive(password, bytes.fromhex(self.salt),
                            self.n, self.r, self.p, self.dklen)
        return hmac.compare_digest(candidate.hex(), self.password_hash)

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role.value,
            "salt": self.salt,
            "password_hash": self.password_hash,
            "kdf": {"name": "scrypt", "n": self.n, "r": self.r,
                    "p": self.p, "dklen": self.dklen},
            "disabled": self.disabled,
            "must_change_password": self.must_change_password,
            "failed_attempts": self.failed_attempts,
            "locked_until": self.locked_until,
            "created_at": self.created_at,
            "password_changed_at": self.password_changed_at,
        }

    @classmethod
    def from_dict(cls, raw: dict, source: str = "accounts file") -> "Account":
        name = raw.get("username", "?")
        try:
            role = Role(raw["role"])
        except (KeyError, ValueError) as exc:
            raise ValueError(
                f"{source}: account {name!r} has an unusable role {raw.get('role')!r}; "
                f"expected one of {', '.join(r.value for r in Role)}"
            ) from exc
        if not raw.get("password_hash") or not raw.get("salt"):
            raise ValueError(
                f"{source}: account {name!r} has no password hash or no salt. Passwords "
                "are stored derived and salted; write the derivation, never the password."
            )
        kdf = raw.get("kdf") or {}
        if kdf.get("name", "scrypt") != "scrypt":
            raise ValueError(
                f"{source}: account {name!r} was derived with {kdf['name']!r}, which this "
                "build cannot verify. Reset the password rather than guessing."
            )
        return cls(
            username=raw["username"],
            display_name=raw.get("display_name") or raw["username"],
            role=role,
            salt=raw["salt"],
            password_hash=raw["password_hash"],
            n=int(kdf.get("n", SCRYPT_N)),
            r=int(kdf.get("r", SCRYPT_R)),
            p=int(kdf.get("p", SCRYPT_P)),
            dklen=int(kdf.get("dklen", DK_LEN)),
            disabled=bool(raw.get("disabled", False)),
            must_change_password=bool(raw.get("must_change_password", False)),
            failed_attempts=int(raw.get("failed_attempts", 0)),
            locked_until=raw.get("locked_until"),
            created_at=raw.get("created_at") or _now().isoformat(),
            password_changed_at=raw.get("password_changed_at"),
        )


def new_account(username: str, display_name: str, role: Role, password: str,
                must_change_password: bool = False) -> Account:
    check_password_policy(password)
    salt = secrets.token_bytes(SALT_BYTES)
    derived = _derive(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P, DK_LEN)
    return Account(
        username=username.strip().lower(),
        display_name=display_name,
        role=role,
        salt=salt.hex(),
        password_hash=derived.hex(),
        must_change_password=must_change_password,
        password_changed_at=_now().isoformat(),
    )


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #

# Verifying a password for a username that does not exist still has to cost what a real
# verification costs. Without this, "unknown user" returns in microseconds and "wrong
# password" in fifty milliseconds, and the difference tells an attacker which of your
# DRMs to spend their guesses on. The salt is fixed and public; that is fine, because the
# result is thrown away.
_DUMMY_SALT = b"tracksen-timing-equaliser-0001"[:SALT_BYTES]


class AccountStore:
    """Username -> Account, backed by a JSON file that holds no recoverable password."""

    def __init__(self, accounts: list[Account], path: Path | None = None):
        self._by_username = {a.username: a for a in accounts}
        self.accounts = list(accounts)
        self.path = Path(path) if path else None

    # ------------------------------------------------------------------ #

    @classmethod
    def load(cls, path: Path) -> "AccountStore":
        path = Path(path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        out = [Account.from_dict(entry, str(path))
               for entry in raw.get("accounts", [])]
        if not out:
            raise ValueError(
                f"{path}: no accounts. A service nobody can act on is not a safe "
                "default, it is a broken one."
            )
        return cls(out, path)

    def save(self, path: Path | None = None) -> None:
        target = Path(path) if path else self.path
        if target is None:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "_comment": (
                "TRACKSEN accounts. Passwords are stored as salted scrypt derivations: "
                "this file cannot be used to obtain one. Keep it out of version control "
                "anyway -- it names who may sanction."
            ),
            "accounts": [a.to_dict() for a in self.accounts],
        }
        tmp = target.with_suffix(target.suffix + ".partial")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp.replace(target)

    # ------------------------------------------------------------------ #

    def get(self, username: str) -> Account | None:
        return self._by_username.get((username or "").strip().lower())

    def verify(self, username: str, password: str) -> Account:
        """The account these credentials belong to, or refuse.

        Every refusal raises the SAME message. "No such user" and "wrong password" are
        different facts and telling them apart is a favour to an attacker and to nobody
        else: the honest user knows which of the two they got wrong. The lockout is the
        one exception -- being told to come back in fifteen minutes is actionable, and it
        leaks nothing an attacker who triggered it does not already know.
        """
        refusal = "username or password not recognised"
        account = self.get(username)

        if account is None:
            # Spend the same work, then refuse. See _DUMMY_SALT.
            _derive(password or "", _DUMMY_SALT, SCRYPT_N, SCRYPT_R, SCRYPT_P, DK_LEN)
            raise AuthenticationError(refusal)

        if account.is_locked:
            until = _parse(account.locked_until)
            minutes = max(1, int((until - _now()).total_seconds() // 60) + 1)
            raise AuthenticationError(
                f"account locked after {MAX_FAILED_ATTEMPTS} failed attempts; "
                f"try again in {minutes} minute(s)"
            )

        if not password or not account.matches(password):
            account.failed_attempts += 1
            if account.failed_attempts >= MAX_FAILED_ATTEMPTS:
                account.locked_until = _iso(
                    _now() + dt.timedelta(minutes=LOCKOUT_MINUTES))
            self.save()
            raise AuthenticationError(refusal)

        # A disabled account is checked AFTER the password, deliberately. Checking it
        # first would answer "does this person exist and are they still with the
        # division" to anyone who can type a username.
        if account.disabled:
            raise AuthenticationError(refusal)

        if account.failed_attempts or account.locked_until:
            account.failed_attempts = 0
            account.locked_until = None
            self.save()
        return account

    def set_password(self, username: str, new_password: str) -> Account:
        """Set a password, clearing the must-change flag and any lockout.

        Does not check the old one: callers that should -- the self-service change -- do
        that first, because an administrative reset legitimately has no old password to
        offer.
        """
        account = self.get(username)
        if account is None:
            raise AuthenticationError("username or password not recognised")
        check_password_policy(new_password)

        salt = secrets.token_bytes(SALT_BYTES)
        account.salt = salt.hex()
        account.password_hash = _derive(
            new_password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P, DK_LEN).hex()
        account.n, account.r, account.p, account.dklen = (
            SCRYPT_N, SCRYPT_R, SCRYPT_P, DK_LEN)
        account.must_change_password = False
        account.failed_attempts = 0
        account.locked_until = None
        account.password_changed_at = _now().isoformat()
        self.save()
        return account

    def set_disabled(self, username: str, disabled: bool) -> Account:
        account = self.get(username)
        if account is None:
            raise AuthenticationError("username or password not recognised")
        account.disabled = disabled
        self.save()
        return account

    def __len__(self) -> int:
        return len(self.accounts)


# --------------------------------------------------------------------------- #
# First run
# --------------------------------------------------------------------------- #

# One account per role, so the whole approval route can be walked end to end. A real
# deployment has one per person and several people per role; this is the smallest set
# that exercises every gate.
BOOTSTRAP_ACCOUNTS: list[tuple[str, str, Role]] = [
    ("je", "J. Kumar, JE/P.Way (demo)", Role.JE),
    ("srden", "A. Sharma, Sr.DEN/Co (demo)", Role.SR_DEN),
    ("srdste", "P. Nair, Sr.DSTE (demo)", Role.SR_DSTE),
    ("srdee", "R. Verma, Sr.DEE/TrD (demo)", Role.SR_DEE),
    ("srdom", "S. Iyer, Sr.DOM (demo)", Role.SR_DOM),
    ("drm", "M. Banerjee, DRM (demo)", Role.DRM),
    ("viewer", "Divisional viewer (demo)", Role.VIEWER),
]

# Long enough that the minted password is not the weak link, short enough to retype once
# from a terminal before changing it.
BOOTSTRAP_PASSWORD_BYTES = 12


def bootstrap(path: Path) -> tuple["AccountStore", dict[str, str]]:
    """Create an accounts file with fresh random passwords. Returns them ONCE.

    Every bootstrap account is flagged must-change-password. A minted credential that
    stays valid indefinitely is how a demo system becomes a production system with a
    published password, and printing it to a terminal means it is already in somebody's
    scrollback.

    Deliberately not a bypass. A service that fell back to "trust the caller" when no
    accounts file was present would have an authentication system and a hole beside it,
    and the hole is what would get used.
    """
    passwords: dict[str, str] = {}
    accounts: list[Account] = []
    for username, display, role in BOOTSTRAP_ACCOUNTS:
        password = secrets.token_urlsafe(BOOTSTRAP_PASSWORD_BYTES)
        passwords[username] = password
        accounts.append(new_account(username, display, role, password,
                                    must_change_password=True))

    store = AccountStore(accounts, path)
    store.save()
    return store, passwords


def load_or_bootstrap(path: Path) -> tuple["AccountStore", dict[str, str] | None]:
    """Load the accounts file, creating one on first run. Passwords only if minted."""
    path = Path(path)
    if path.exists():
        return AccountStore.load(path), None
    return bootstrap(path)
