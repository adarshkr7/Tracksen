"""Adapters: three ways in, one model out.

Parts of the legacy estate expose a REST endpoint. Parts expose only a database. Parts
will give you nothing but a nightly file. A design that presumes an API cannot be
commissioned, so each source is tried in descending order of fidelity and falls back:

    REST  ->  read-only DB view  ->  scheduled CSV drop

Two rules the whole layer is built on.

**Nothing is ever written to a source system.** The SQLite adapter opens the database
with `mode=ro` and refuses to run against anything but a view; if it is pointed at a
base table it raises rather than reading, because a system of record is not ours to
touch and an adapter that can read a table today can be edited to write one tomorrow.

**A record that cannot be mapped is rejected by name, with a reason.** Silently dropping
malformed rows is how a division discovers six months later that its worst defects were
never scheduled because a date format changed.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import sqlite3
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..domain import (
    AssetClass,
    BlockType,
    Department,
    Line,
    MachineType,
    MaintenanceTask,
)
from .sources import SMMS_PRIORITY, TMS_SEVERITY, SourceSpec, date_to_day


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #

@dataclass
class Rejection:
    system: str
    record_id: str
    reason: str

    def __str__(self) -> str:
        return f"{self.system}/{self.record_id}: {self.reason}"


@dataclass
class SourceReport:
    system: str
    mode: str                    # rest | db_view | csv | unavailable
    attempted: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)   # mode -> why not used
    fetched: int = 0
    accepted: int = 0
    rejected: list[Rejection] = field(default_factory=list)
    duplicates: int = 0
    error: str | None = None

    @property
    def degraded(self) -> bool:
        return self.mode != "rest"


@dataclass
class IngestionResult:
    tasks: list[MaintenanceTask]
    reports: list[SourceReport]

    @property
    def rejected(self) -> list[Rejection]:
        return [r for rep in self.reports for r in rep.rejected]

    def summary(self) -> str:
        lines = []
        for r in self.reports:
            path = " -> ".join(r.attempted) if r.attempted else "-"
            lines.append(
                f"  {r.system:<6} via {r.mode:<9} ({path})  "
                f"fetched {r.fetched:>3}  accepted {r.accepted:>3}  "
                f"rejected {len(r.rejected):>2}  duplicates {r.duplicates}"
                + (f"  ERROR {r.error}" if r.error else "")
            )
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Adapters
# --------------------------------------------------------------------------- #

class SourceAdapter(ABC):
    mode: str = "unknown"
    last_error: str | None = None

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def fetch(self) -> list[dict]: ...


class RestAdapter(SourceAdapter):
    """Preferred. Reads JSON from an endpoint; `items` or a bare list."""

    mode = "rest"

    def __init__(self, url: str | None, timeout: float = 5.0,
                 opener: Callable[[str], bytes] | None = None):
        self.url = url
        self.timeout = timeout
        self._opener = opener

    def _read(self) -> bytes:
        if self._opener is not None:          # injected for tests -- no network
            return self._opener(self.url or "")
        with urllib.request.urlopen(self.url, timeout=self.timeout) as r:  # noqa: S310
            return r.read()

    def available(self) -> bool:
        if not self.url:
            self.last_error = "no endpoint configured"
            return False
        try:
            self._read()
            return True
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False

    def fetch(self) -> list[dict]:
        payload = json.loads(self._read().decode("utf-8"))
        if isinstance(payload, list):
            return payload
        return payload.get("items", [])


class SqliteViewAdapter(SourceAdapter):
    """Read-only, and only ever against a view.

    Pointing this at a base table raises. The restriction is the point: a departmental
    DBA grants a view, not a table, and the code should make the weaker grant sufficient.
    """

    mode = "db_view"

    def __init__(self, db_path: str | None, view: str | None):
        self.db_path = db_path
        self.view = view

    def _connect(self) -> sqlite3.Connection:
        uri = f"file:{Path(self.db_path).as_posix()}?mode=ro"
        con = sqlite3.connect(uri, uri=True)
        con.row_factory = sqlite3.Row
        return con

    def available(self) -> bool:
        if not self.db_path or not self.view:
            self.last_error = "no database or view configured"
            return False
        if not Path(self.db_path).exists():
            self.last_error = f"database not found at {self.db_path}"
            return False
        try:
            with self._connect() as con:
                row = con.execute(
                    "SELECT type FROM sqlite_master WHERE name = ?", (self.view,)
                ).fetchone()
            if row is None:
                self.last_error = f"{self.view} does not exist"
                return False
            if row["type"] != "view":
                self.last_error = f"{self.view} is a {row['type']}, not a view"
                return False
            return True
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False

    def fetch(self) -> list[dict]:
        with self._connect() as con:
            kind = con.execute(
                "SELECT type FROM sqlite_master WHERE name = ?", (self.view,)
            ).fetchone()
            if kind is None:
                raise ValueError(f"{self.view} does not exist")
            if kind["type"] != "view":
                raise PermissionError(
                    f"{self.view} is a {kind['type']}, not a view -- "
                    "this adapter reads views only"
                )
            return [dict(r) for r in con.execute(f"SELECT * FROM {self.view}")]


class CsvAdapter(SourceAdapter):
    """The floor. A nightly drop is always possible, so this must always work."""

    mode = "csv"

    def __init__(self, path: str | None):
        self.path = path

    def available(self) -> bool:
        if not self.path:
            self.last_error = "no file configured"
            return False
        if not Path(self.path).exists():
            self.last_error = f"file not found at {self.path}"
            return False
        return True

    def fetch(self) -> list[dict]:
        with Path(self.path).open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))


# --------------------------------------------------------------------------- #
# Normalisation into the Unified Task Model
# --------------------------------------------------------------------------- #

def _parse_date_to_day(value: str, fmts: tuple[str, ...]) -> int:
    text = str(value).strip().replace("Z", "")
    for fmt in fmts:
        try:
            return date_to_day(dt.datetime.strptime(text, fmt).date())
        except ValueError:
            continue
    # ISO-8601 with a time component, as TDMS emits.
    try:
        return date_to_day(dt.datetime.fromisoformat(text).date())
    except ValueError as exc:
        raise ValueError(f"unparseable date {value!r}") from exc


def _block_type_for(dept: Department) -> BlockType:
    return {
        Department.ENGINEERING: BlockType.TRAFFIC,
        Department.SIGNAL: BlockType.DISCONNECTION,
        Department.TRACTION: BlockType.POWER,
    }[dept]


def _build(*, task_id, dept, asset_id, asset_class, section, line, km, task_type,
           severity, is_defect, raised_day, due_day, demanded, gang, machine,
           quantity, night) -> MaintenanceTask:
    return MaintenanceTask(
        id=task_id,
        source_system=dept.source_system,
        department=dept,
        asset_id=asset_id,
        asset_class=AssetClass(asset_class),
        section_id=section,
        line=Line(line),
        chainage_km=float(km),
        task_type=task_type,
        block_type=_block_type_for(dept),
        defect_severity=int(severity),
        is_defect=bool(is_defect),
        raised_day=int(raised_day),
        due_day=int(due_day),
        demanded_duration_min=int(demanded),
        gang_size=int(gang),
        machine=MachineType(machine),
        quantity=float(quantity),
        night_work_allowed=bool(night),
    )


def normalise_tms(raw: dict) -> MaintenanceTask:
    return _build(
        task_id=raw["DEFECT_ID"], dept=Department.ENGINEERING,
        asset_id=raw["ASSET_NO"], asset_class=raw["ASSET_TYP"],
        section=raw["SECTION_CD"], line=raw["LINE_CD"], km=raw["KM"],
        task_type=raw["WORK_DESC"],
        severity=TMS_SEVERITY[raw["SEVERITY_CD"]],
        is_defect=str(raw["IS_DEFECT"]).upper() == "Y",
        raised_day=_parse_date_to_day(raw["RAISED_DT"], ("%d-%m-%Y",)),
        due_day=_parse_date_to_day(raw["TARGET_DT"], ("%d-%m-%Y",)),
        demanded=raw["BLK_DEMAND_MIN"], gang=raw["GANG_STRENGTH"],
        machine=raw["MACHINE_CD"], quantity=raw["QTY"],
        night=str(raw["NIGHT_PERMITTED"]).upper() == "Y",
    )


def normalise_smms(raw: dict) -> MaintenanceTask:
    priority = raw["priority"]
    if priority not in SMMS_PRIORITY:
        raise ValueError(f"unknown priority code {priority!r}")
    return _build(
        task_id=raw["fault_ref"], dept=Department.SIGNAL,
        asset_id=raw["equipment_id"], asset_class=raw["equipment_class"],
        section=raw["section"], line=raw["line"],
        # Metres to kilometres. Miss this and every S&T job lands 1000x down the road.
        km=float(raw["chainage_m"]) / 1000.0,
        task_type=raw["activity"],
        # P1 is the MOST urgent in SMMS, the opposite of the TMS convention.
        severity=SMMS_PRIORITY[priority],
        is_defect=bool(int(raw["is_fault"])),
        raised_day=_parse_date_to_day(raw["reported_on"], ("%Y-%m-%d",)),
        due_day=_parse_date_to_day(raw["due_on"], ("%Y-%m-%d",)),
        demanded=raw["disconnection_minutes"], gang=raw["staff_count"],
        machine=raw["machine"], quantity=raw["qty"],
        night=bool(int(raw["night_ok"])),
    )


def normalise_tdms(raw: dict) -> MaintenanceTask:
    loc = raw.get("location") or {}
    if not loc:
        raise ValueError("missing location block")
    return _build(
        task_id=raw["ohEid"], dept=Department.TRACTION,
        asset_id=raw["assetRef"], asset_class=raw["assetKind"],
        section=loc["section"], line=loc["line"], km=loc["km"],
        task_type=raw["job"], severity=raw["criticality"],
        is_defect=bool(raw["reactive"]),
        raised_day=_parse_date_to_day(raw["raisedIso"], ()),
        due_day=_parse_date_to_day(raw["dueIso"], ()),
        demanded=raw["powerBlockMins"], gang=raw["crew"],
        machine=raw["plant"], quantity=raw["quantity"],
        night=bool(raw["nightAllowed"]),
    )


NORMALISERS = {
    "TMS": normalise_tms,
    "SMMS": normalise_smms,
    "TDMS": normalise_tdms,
}

ID_FIELDS = {"TMS": "DEFECT_ID", "SMMS": "fault_ref", "TDMS": "ohEid"}


# --------------------------------------------------------------------------- #
# The degradation ladder
# --------------------------------------------------------------------------- #

def build_ladder(spec: SourceSpec,
                 rest_opener: Callable[[str], bytes] | None = None
                 ) -> list[SourceAdapter]:
    return [
        RestAdapter(spec.rest_url, opener=rest_opener),
        SqliteViewAdapter(spec.db_path, spec.db_view),
        CsvAdapter(spec.csv_path),
    ]


def ingest_source(spec: SourceSpec,
                  rest_opener: Callable[[str], bytes] | None = None
                  ) -> tuple[list[MaintenanceTask], SourceReport]:
    """Try each mode in turn; normalise whatever the first working one returns."""
    report = SourceReport(system=spec.system, mode="unavailable")
    normaliser = NORMALISERS[spec.system]
    id_field = ID_FIELDS[spec.system]

    raw: list[dict] | None = None
    for adapter in build_ladder(spec, rest_opener):
        report.attempted.append(adapter.mode)
        if not adapter.available():
            report.skipped[adapter.mode] = adapter.last_error or "unavailable"
            continue
        try:
            raw = adapter.fetch()
            report.mode = adapter.mode
            break
        except Exception as exc:            # a mode that errors is a mode we fall past
            report.skipped[adapter.mode] = f"{type(exc).__name__}: {exc}"
            report.error = f"{adapter.mode}: {exc}"
            continue

    if raw is None:
        report.error = report.error or "no mode available"
        return [], report

    report.fetched = len(raw)
    tasks: list[MaintenanceTask] = []
    seen: set[str] = set()

    for record in raw:
        rid = str(record.get(id_field, "<no id>"))
        try:
            task = normaliser(record)
        except Exception as exc:
            report.rejected.append(Rejection(spec.system, rid, str(exc)))
            continue
        if task.id in seen:
            report.duplicates += 1
            continue
        seen.add(task.id)
        tasks.append(task)

    report.accepted = len(tasks)
    return tasks, report


def ingest(specs: dict[str, SourceSpec] | list[SourceSpec],
           rest_opener: Callable[[str], bytes] | None = None) -> IngestionResult:
    """Pull every source into one Unified Task Model."""
    items = list(specs.values()) if isinstance(specs, dict) else list(specs)
    all_tasks: list[MaintenanceTask] = []
    reports: list[SourceReport] = []

    for spec in items:
        tasks, report = ingest_source(spec, rest_opener)
        all_tasks.extend(tasks)
        reports.append(report)

    return IngestionResult(tasks=all_tasks, reports=reports)
