"""Append-only, tamper-evident audit trail.

Every state change to a plan lands here: who did it, in what capacity, when, to which
plan, and why. Nothing is ever updated or deleted.

Each entry carries the SHA-256 of the entry before it, so the log is a hash chain. Edit
any historical record -- change a name, soften a remark, move a sanction time -- and every
subsequent hash stops matching. `verify()` finds it and names the first broken link.

That property is the point. A block plan is a safety document: when something goes wrong
on the ground, the question asked afterwards is what was recommended, what was changed,
by whom, and on whose authority. A log that can be quietly rewritten answers none of it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

GENESIS = "0" * 64


class Action(str, Enum):
    """Everything that can happen to a plan."""

    CREATE = "CREATE"              # a plan was generated
    MODIFY = "MODIFY"              # a human moved or pinned something
    RESOLVE = "RESOLVE"            # re-solved around pinned placements
    CONCUR = "CONCUR"              # departmental head agrees
    WITHHOLD = "WITHHOLD"          # departmental head does not agree
    CLEAR = "CLEAR"                # operations clears the traffic impact
    RETURN = "RETURN"              # sent back for revision
    SANCTION = "SANCTION"          # the competent authority sanctions
    SUPERSEDE = "SUPERSEDE"        # replaced by a later plan
    CANCEL = "CANCEL"              # withdrawn after sanction
    EXECUTE = "EXECUTE"            # the block actually ran
    DENIED = "DENIED"              # someone attempted something they may not do


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    timestamp: str
    actor: str
    role: str
    action: str
    plan_id: str
    detail: dict[str, Any]
    prev_hash: str
    entry_hash: str = ""

    def compute_hash(self) -> str:
        body = {
            "seq": self.seq,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "role": self.role,
            "action": self.action,
            "plan_id": self.plan_id,
            "detail": self.detail,
            "prev_hash": self.prev_hash,
        }
        return hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChainStatus:
    intact: bool
    entries: int
    broken_at: int | None = None
    reason: str | None = None

    def __str__(self) -> str:
        if self.intact:
            return f"chain intact over {self.entries} entries"
        return f"CHAIN BROKEN at entry {self.broken_at}: {self.reason}"


class AuditLog:
    """Append-only. There is deliberately no update or delete."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self._entries: list[AuditEntry] = []
        if self.path and self.path.exists():
            self._load()

    # ------------------------------------------------------------------ #

    def _load(self) -> None:
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    self._entries.append(AuditEntry(**json.loads(line)))

    def _persist(self, entry: AuditEntry) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry.to_dict(), default=str) + "\n")

    # ------------------------------------------------------------------ #

    @property
    def head_hash(self) -> str:
        return self._entries[-1].entry_hash if self._entries else GENESIS

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[AuditEntry]:
        return iter(self._entries)

    def append(self, *, actor: str, role: str, action: Action | str, plan_id: str,
               detail: dict[str, Any] | None = None,
               timestamp: dt.datetime | None = None) -> AuditEntry:
        ts = (timestamp or dt.datetime.now(dt.timezone.utc)).isoformat()
        draft = AuditEntry(
            seq=len(self._entries),
            timestamp=ts,
            actor=actor,
            role=role if isinstance(role, str) else role.value,
            action=action.value if isinstance(action, Action) else action,
            plan_id=plan_id,
            detail=detail or {},
            prev_hash=self.head_hash,
        )
        entry = AuditEntry(**{**draft.to_dict(), "entry_hash": draft.compute_hash()})
        self._entries.append(entry)
        self._persist(entry)
        return entry

    # ------------------------------------------------------------------ #

    def verify(self) -> ChainStatus:
        """Walk the chain. Any retroactive edit shows up here."""
        prev = GENESIS
        for i, e in enumerate(self._entries):
            if e.seq != i:
                return ChainStatus(False, len(self._entries), i,
                                   f"sequence is {e.seq}, expected {i}")
            if e.prev_hash != prev:
                return ChainStatus(False, len(self._entries), i,
                                   "prev_hash does not match the entry before it")
            if e.compute_hash() != e.entry_hash:
                return ChainStatus(False, len(self._entries), i,
                                   "contents do not match the recorded hash")
            prev = e.entry_hash
        return ChainStatus(True, len(self._entries))

    def for_plan(self, plan_id: str) -> list[AuditEntry]:
        return [e for e in self._entries if e.plan_id == plan_id]

    def by_action(self, action: Action) -> list[AuditEntry]:
        return [e for e in self._entries if e.action == action.value]

    def history(self, plan_id: str) -> str:
        """The trail as a person would read it."""
        lines = []
        for e in self.for_plan(plan_id):
            when = e.timestamp[:19].replace("T", " ")
            note = e.detail.get("remarks") or e.detail.get("note") or ""
            lines.append(
                f"  {when}  {e.action:<10} {e.actor} ({e.role})"
                + (f" -- {note}" if note else "")
            )
        return "\n".join(lines)
