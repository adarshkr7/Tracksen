"""What was actually approved, kept where it can be read back.

The audit log proves that PLAN-0007 was concurred with and sanctioned, and the content
hash in those entries proves *which* plan that was. Neither of them stores the plan. So a
restarted service could verify a sanction and be unable to show anybody what had been
sanctioned -- the trail was sound and the thing it referred to was gone.

This keeps every revision of every plan on disk, and checks what it reads back against
the hash the audit recorded. That turns the hash from a claim into a test: presented with
a plan and an audit entry, you can say whether they are the same plan, which is the whole
reason the hash was worth recording.

Files, not a database, for the same reason the audit log is a file: the deployment story
is a divisional Postgres and the seam is `PlanStore`, but a file-backed store has no
setup, survives a restart, and is inspectable with `cat` when something has gone wrong at
two in the morning.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..domain import Plan, plan_content_hash

# Plan ids reach this from the API. They become path segments, so they are checked
# rather than trusted: "../../etc" is a plan id as far as a JSON body is concerned.
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class PlanStoreError(Exception):
    """The store could not do what was asked, for a reason worth naming."""


def _check_id(plan_id: str) -> str:
    if not SAFE_ID.match(plan_id or ""):
        raise PlanStoreError(
            f"unusable plan id {plan_id!r}: letters, digits, dot, dash and underscore "
            "only, up to 64 characters. Plan ids become filenames."
        )
    return plan_id


@dataclass
class StoredPlan:
    """One revision of one plan, as it was when somebody was asked to approve it."""

    plan_id: str
    revision: int
    content_hash: str
    saved_at: str
    horizon_days: int
    label: str
    blocks: list[dict[str, Any]]
    unscheduled_task_ids: list[str] = field(default_factory=list)
    metrics: dict[str, Any] | None = None

    # ------------------------------------------------------------------ #

    def recomputed_hash(self) -> str:
        """Hash the blocks as stored, through the same function the domain uses."""
        return plan_content_hash(
            (b["section_id"], b["line"], int(b["start_min"]), int(b["end_min"]),
             b.get("task_ids", []))
            for b in self.blocks
        )

    @property
    def intact(self) -> bool:
        """Whether the stored content still matches the hash saved beside it.

        False means the file was edited after the fact. It does not mean the plan was
        never approved -- the audit chain answers that -- it means what is on disk is no
        longer the thing that was.
        """
        return self.recomputed_hash() == self.content_hash

    def matches(self, expected_hash: str | None) -> bool:
        """Whether this is the plan a given audit entry was about."""
        return bool(expected_hash) and self.content_hash == expected_hash and self.intact

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "revision": self.revision,
            "content_hash": self.content_hash,
            "saved_at": self.saved_at,
            "horizon_days": self.horizon_days,
            "label": self.label,
            "blocks": self.blocks,
            "unscheduled_task_ids": self.unscheduled_task_ids,
            "metrics": self.metrics,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StoredPlan":
        return cls(
            plan_id=raw["plan_id"],
            revision=int(raw["revision"]),
            content_hash=raw["content_hash"],
            saved_at=raw.get("saved_at", ""),
            horizon_days=int(raw.get("horizon_days", 0)),
            label=raw.get("label", "plan"),
            blocks=raw.get("blocks", []),
            unscheduled_task_ids=raw.get("unscheduled_task_ids", []),
            metrics=raw.get("metrics"),
        )


class PlanStore:
    """Every revision of every plan, addressed by (plan_id, revision)."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def _dir(self, plan_id: str) -> Path:
        return self.root / _check_id(plan_id)

    def _path(self, plan_id: str, revision: int) -> Path:
        return self._dir(plan_id) / f"r{int(revision):04d}.json"

    # ------------------------------------------------------------------ #

    def save(self, plan_id: str, revision: int, plan: Plan,
             metrics: dict[str, Any] | None = None) -> StoredPlan:
        """Write a revision. Only the operative content, not the whole payload.

        Train paths, the asset estate and the task list are regenerable and would multiply
        the size of every revision by twenty. What cannot be regenerated is the decision:
        which work went into which possession, where, and for how long.
        """
        stored = StoredPlan(
            plan_id=_check_id(plan_id),
            revision=int(revision),
            content_hash=plan.content_hash(),
            saved_at=dt.datetime.now(dt.timezone.utc).isoformat(),
            horizon_days=plan.horizon_days,
            label=plan.label,
            blocks=[{
                "id": b.id,
                "section_id": b.section_id,
                "line": b.line.value,
                "day": b.day,
                "start_min": b.start_min,
                "end_min": b.end_min,
                "task_ids": list(b.task_ids),
                "departments": [d.value for d in b.departments],
                "block_types": [t.value for t in b.block_types],
                "inside_corridor": b.inside_corridor,
                "traffic_cost": b.traffic_cost,
                "criticality_retired": b.criticality_retired,
                "reasons": list(b.reasons),
            } for b in plan.blocks],
            unscheduled_task_ids=list(plan.unscheduled_task_ids),
            metrics=metrics,
        )

        path = self._path(plan_id, revision)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Written aside and moved into place: a crash mid-write would otherwise leave a
        # truncated revision that reads as a tampered one, which is a far more alarming
        # thing to find than a missing file.
        tmp = path.with_suffix(".partial")
        try:
            tmp.write_text(json.dumps(stored.to_dict(), indent=1), encoding="utf-8")
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return stored

    def load(self, plan_id: str, revision: int | None = None) -> StoredPlan | None:
        """One revision, or the latest. None if it was never stored."""
        if revision is None:
            revs = self.revisions(plan_id)
            if not revs:
                return None
            revision = revs[-1]
        path = self._path(plan_id, revision)
        if not path.exists():
            return None
        return StoredPlan.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def revisions(self, plan_id: str) -> list[int]:
        d = self._dir(plan_id)
        if not d.is_dir():
            return []
        out = []
        for f in d.glob("r*.json"):
            try:
                out.append(int(f.stem[1:]))
            except ValueError:
                continue
        return sorted(out)

    def plan_ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(d.name for d in self.root.iterdir() if d.is_dir())

    def find_by_hash(self, plan_id: str, content_hash: str) -> StoredPlan | None:
        """The revision whose content matches this hash -- what the DRM actually signed.

        A plan can be re-solved several times before anyone approves it, so "the latest
        revision" and "the revision that was sanctioned" are different questions. The
        audit entry carries the hash; this answers the second one with it.
        """
        for revision in reversed(self.revisions(plan_id)):
            stored = self.load(plan_id, revision)
            if stored and stored.content_hash == content_hash:
                return stored
        return None
