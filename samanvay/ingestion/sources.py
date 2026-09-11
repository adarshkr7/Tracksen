"""The three departmental systems, in their own native shapes.

TMS, SMMS and TDMS were built at different times by different teams. They do not agree
on field names, on units, on date formats, or on what a severity code means. That
disagreement is the entire reason an ingestion layer exists, so the mock systems here
reproduce it faithfully rather than emitting three copies of one convenient schema:

    TMS    CSV drop     UPPER_SNAKE   km as decimal      dates DD-MM-YYYY   severity S1..S5
    SMMS   SQLite view  lower_snake   chainage in METRES dates ISO          priority P1..P5,
                                                                           where P1 is worst
    TDMS   REST/JSON    camelCase     nested location    dates ISO-8601 Z   criticality 1..5

The severity inversion is deliberate: TMS severity S5 is the most urgent, SMMS priority
P1 is the most urgent. An adapter that maps both straight onto an integer without
reversing one of them produces a plan that attends the least urgent signalling faults
first, and nothing downstream would ever notice.

`export_all()` writes these as real files and a real database so the adapters can be
exercised end to end against something that is not a Python object.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..domain import Department, MaintenanceTask

EPOCH = dt.date(2026, 9, 1)   # day 0 of the planning horizon, for date round-tripping


def day_to_date(day: int) -> dt.date:
    return EPOCH + dt.timedelta(days=day)


def date_to_day(d: dt.date) -> int:
    return (d - EPOCH).days


# --------------------------------------------------------------------------- #
# Severity / priority code systems
# --------------------------------------------------------------------------- #

# TMS: S1 least urgent .. S5 most urgent  (same direction as our 1..5)
TMS_SEVERITY = {f"S{i}": i for i in range(1, 6)}

# SMMS: P1 MOST urgent .. P5 least urgent  (inverted)
SMMS_PRIORITY = {f"P{i}": 6 - i for i in range(1, 6)}
SMMS_PRIORITY_REVERSE = {v: k for k, v in SMMS_PRIORITY.items()}

# TDMS: plain integer, same direction.


@dataclass(frozen=True)
class SourceSpec:
    """What a departmental system is and where its data can be found."""

    system: str                 # TMS | SMMS | TDMS
    department: Department
    rest_url: str | None = None
    db_path: str | None = None
    db_view: str | None = None
    csv_path: str | None = None


# --------------------------------------------------------------------------- #
# Export: write the mock systems
# --------------------------------------------------------------------------- #

TMS_COLUMNS = [
    "DEFECT_ID", "SECTION_CD", "LINE_CD", "KM", "ASSET_NO", "ASSET_TYP",
    "WORK_DESC", "SEVERITY_CD", "IS_DEFECT", "RAISED_DT", "TARGET_DT",
    "BLK_DEMAND_MIN", "GANG_STRENGTH", "MACHINE_CD", "QTY", "NIGHT_PERMITTED",
]


def _tms_row(t: MaintenanceTask) -> dict:
    return {
        "DEFECT_ID": t.id,
        "SECTION_CD": t.section_id,
        "LINE_CD": t.line.value,
        "KM": f"{t.chainage_km:.3f}",
        "ASSET_NO": t.asset_id,
        "ASSET_TYP": t.asset_class.value,
        "WORK_DESC": t.task_type,
        "SEVERITY_CD": f"S{t.defect_severity}",
        "IS_DEFECT": "Y" if t.is_defect else "N",
        "RAISED_DT": day_to_date(t.raised_day).strftime("%d-%m-%Y"),
        "TARGET_DT": day_to_date(t.due_day).strftime("%d-%m-%Y"),
        "BLK_DEMAND_MIN": t.demanded_duration_min,
        "GANG_STRENGTH": t.gang_size,
        "MACHINE_CD": t.machine.value,
        "QTY": f"{t.quantity:.1f}",
        "NIGHT_PERMITTED": "Y" if t.night_work_allowed else "N",
    }


def _smms_row(t: MaintenanceTask) -> dict:
    return {
        "fault_ref": t.id,
        "section": t.section_id,
        "line": t.line.value,
        # Metres, not kilometres. The classic unit mismatch.
        "chainage_m": int(round(t.chainage_km * 1000)),
        "equipment_id": t.asset_id,
        "equipment_class": t.asset_class.value,
        "activity": t.task_type,
        "priority": SMMS_PRIORITY_REVERSE[t.defect_severity],
        "is_fault": 1 if t.is_defect else 0,
        "reported_on": day_to_date(t.raised_day).isoformat(),
        "due_on": day_to_date(t.due_day).isoformat(),
        "disconnection_minutes": t.demanded_duration_min,
        "staff_count": t.gang_size,
        "machine": t.machine.value,
        "qty": t.quantity,
        "night_ok": 1 if t.night_work_allowed else 0,
    }


def _tdms_record(t: MaintenanceTask) -> dict:
    return {
        "ohEid": t.id,
        "location": {
            "section": t.section_id,
            "line": t.line.value,
            "km": t.chainage_km,
        },
        "assetRef": t.asset_id,
        "assetKind": t.asset_class.value,
        "job": t.task_type,
        "criticality": t.defect_severity,
        "reactive": t.is_defect,
        "raisedIso": dt.datetime.combine(
            day_to_date(t.raised_day), dt.time()).isoformat() + "Z",
        "dueIso": dt.datetime.combine(
            day_to_date(t.due_day), dt.time()).isoformat() + "Z",
        "powerBlockMins": t.demanded_duration_min,
        "crew": t.gang_size,
        "plant": t.machine.value,
        "quantity": t.quantity,
        "nightAllowed": t.night_work_allowed,
    }


def export_all(tasks: list[MaintenanceTask], out_dir: str | Path) -> dict[str, SourceSpec]:
    """Write the three mock systems to disk in their native formats."""
    # Resolve before building URIs: a file:// URL made from a relative path points at
    # a location that does not exist, and the adapter can only report "unavailable".
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    by_dept: dict[Department, list[MaintenanceTask]] = {}
    for t in tasks:
        by_dept.setdefault(t.department, []).append(t)

    # ---- TMS: a CSV drop, the floor of the degradation ladder ----
    tms_path = out / "tms_defects.csv"
    with tms_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=TMS_COLUMNS)
        w.writeheader()
        for t in by_dept.get(Department.ENGINEERING, []):
            w.writerow(_tms_row(t))

    # ---- SMMS: a read-only view over a departmental database ----
    db_path = out / "smms.sqlite"
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    con.execute("""
        CREATE TABLE smms_faults (
            fault_ref TEXT PRIMARY KEY, section TEXT, line TEXT, chainage_m INTEGER,
            equipment_id TEXT, equipment_class TEXT, activity TEXT, priority TEXT,
            is_fault INTEGER, reported_on TEXT, due_on TEXT,
            disconnection_minutes INTEGER, staff_count INTEGER, machine TEXT,
            qty REAL, night_ok INTEGER, closed INTEGER DEFAULT 0
        )""")
    rows = [_smms_row(t) for t in by_dept.get(Department.SIGNAL, [])]
    if rows:
        cols = list(rows[0])
        con.executemany(
            f"INSERT INTO smms_faults ({','.join(cols)}) "
            f"VALUES ({','.join('?' * len(cols))})",
            [tuple(r[c] for c in cols) for r in rows],
        )
    # The adapter is only ever pointed at a view, never the base table.
    con.execute("CREATE VIEW v_open_faults AS "
                "SELECT * FROM smms_faults WHERE closed = 0")
    con.commit()
    con.close()

    # ---- TDMS: JSON, as a REST endpoint would return it ----
    tdms_path = out / "tdms_jobs.json"
    tdms_path.write_text(
        json.dumps(
            {"count": len(by_dept.get(Department.TRACTION, [])),
             "items": [_tdms_record(t) for t in by_dept.get(Department.TRACTION, [])]},
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "TMS": SourceSpec("TMS", Department.ENGINEERING, csv_path=str(tms_path)),
        "SMMS": SourceSpec("SMMS", Department.SIGNAL,
                           db_path=str(db_path), db_view="v_open_faults"),
        "TDMS": SourceSpec("TDMS", Department.TRACTION,
                           rest_url=tdms_path.as_uri(),
                           csv_path=None),
    }
