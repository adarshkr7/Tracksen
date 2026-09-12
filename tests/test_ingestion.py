"""Adapter behaviour.

Two of these guard failures that would corrupt a plan without anything visibly breaking:

  * SMMS publishes chainage in **metres**. Read it as kilometres and every signalling
    job lands a thousand times further down the road, on the wrong section entirely.
  * SMMS priority **P1 is the most urgent**, the reverse of the TMS severity scale. Map
    both straight onto an integer and the plan attends the least urgent signalling
    faults first, in a way no downstream metric would flag.

Neither throws. Both are caught here.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from samanvay.domain import AssetClass, Department, Line, MachineType
from samanvay.ingestion import (
    CsvAdapter,
    RestAdapter,
    SourceSpec,
    SqliteViewAdapter,
    export_all,
    ingest,
    ingest_source,
)
from samanvay.ingestion.adapters import normalise_smms, normalise_tms
from samanvay.ingestion.sources import SMMS_PRIORITY, TMS_SEVERITY, day_to_date
from samanvay.network import SECTIONS

# Derived, not hardcoded: these fixtures must not care which corridor is the sample.
A_SECTION = SECTIONS[0].id


@pytest.fixture(scope="module")
def exported(dataset, tmp_path_factory):
    out = tmp_path_factory.mktemp("sources")
    specs = export_all(dataset.pending, out)
    return specs, out, dataset


# --------------------------------------------------------------------------- #
# Round trip
# --------------------------------------------------------------------------- #

def test_every_task_survives_the_round_trip(exported):
    specs, _, dataset = exported
    result = ingest(specs)
    assert len(result.tasks) == len(dataset.pending)
    assert not result.rejected


def test_all_fields_survive_the_round_trip(exported):
    specs, _, dataset = exported
    result = ingest(specs)
    original = {t.id: t for t in dataset.pending}

    compared = [
        "department", "asset_id", "asset_class", "section_id", "line", "task_type",
        "block_type", "defect_severity", "is_defect", "raised_day", "due_day",
        "demanded_duration_min", "gang_size", "machine", "night_work_allowed",
    ]
    for t in result.tasks:
        o = original[t.id]
        for f in compared:
            assert getattr(t, f) == getattr(o, f), f"{t.id}.{f} changed in transit"
        assert abs(t.chainage_km - o.chainage_km) < 0.001
        assert abs(t.quantity - o.quantity) < 0.05


def test_each_system_is_read_through_a_different_mode(exported):
    """The ladder is real: one source per mode in this fixture."""
    specs, _, _ = exported
    result = ingest(specs)
    modes = {r.system: r.mode for r in result.reports}
    assert modes["TDMS"] == "rest"
    assert modes["SMMS"] == "db_view"
    assert modes["TMS"] == "csv"


# --------------------------------------------------------------------------- #
# The two silent corruptions
# --------------------------------------------------------------------------- #

def test_smms_chainage_is_converted_from_metres():
    raw = {
        "fault_ref": "X1", "section": A_SECTION, "line": "UP", "chainage_m": 3500,
        "equipment_id": "A1", "equipment_class": "POINT_MACHINE",
        "activity": "Point machine overhaul", "priority": "P3", "is_fault": 1,
        "reported_on": day_to_date(0).isoformat(), "due_on": day_to_date(10).isoformat(),
        "disconnection_minutes": 120, "staff_count": 4, "machine": "NONE",
        "qty": 2.0, "night_ok": 1,
    }
    task = normalise_smms(raw)
    assert task.chainage_km == pytest.approx(3.5), (
        "metres were not converted -- this job would land 3500 km down the road"
    )


def test_smms_priority_scale_is_inverted_relative_to_tms():
    """P1 is the worst in SMMS; S5 is the worst in TMS. Both must reach severity 5."""
    assert SMMS_PRIORITY["P1"] == 5
    assert SMMS_PRIORITY["P5"] == 1
    assert TMS_SEVERITY["S5"] == 5
    assert TMS_SEVERITY["S1"] == 1


def test_the_most_urgent_record_from_each_system_maps_to_the_same_severity():
    base_smms = {
        "fault_ref": "X1", "section": A_SECTION, "line": "UP", "chainage_m": 1000,
        "equipment_id": "A1", "equipment_class": "POINT_MACHINE",
        "activity": "Point machine overhaul", "priority": "P1", "is_fault": 1,
        "reported_on": day_to_date(0).isoformat(), "due_on": day_to_date(5).isoformat(),
        "disconnection_minutes": 90, "staff_count": 3, "machine": "NONE",
        "qty": 1.0, "night_ok": 0,
    }
    base_tms = {
        "DEFECT_ID": "Y1", "SECTION_CD": A_SECTION, "LINE_CD": "UP", "KM": "1.000",
        "ASSET_NO": "A2", "ASSET_TYP": "RAIL", "WORK_DESC": "Rail flaw attention (USFD)",
        "SEVERITY_CD": "S5", "IS_DEFECT": "Y",
        "RAISED_DT": day_to_date(0).strftime("%d-%m-%Y"),
        "TARGET_DT": day_to_date(5).strftime("%d-%m-%Y"),
        "BLK_DEMAND_MIN": 60, "GANG_STRENGTH": 8, "MACHINE_CD": "NONE",
        "QTY": "2.0", "NIGHT_PERMITTED": "Y",
    }
    assert normalise_smms(base_smms).defect_severity == 5
    assert normalise_tms(base_tms).defect_severity == 5


# --------------------------------------------------------------------------- #
# Degradation
# --------------------------------------------------------------------------- #

def test_falls_back_when_rest_is_unavailable(exported):
    specs, out, _ = exported
    tdms = specs["TDMS"]
    # Same data, but the endpoint is gone and only a CSV-less DB remains unavailable too.
    broken = SourceSpec("TDMS", Department.TRACTION,
                        rest_url="http://127.0.0.1:9/never", csv_path=None)
    tasks, report = ingest_source(broken)
    assert tasks == []
    assert report.mode == "unavailable"
    assert "rest" in report.skipped, "the report must say why REST was skipped"


def test_degradation_is_reported_not_hidden(exported):
    specs, _, _ = exported
    result = ingest(specs)
    tms = next(r for r in result.reports if r.system == "TMS")
    assert tms.degraded
    assert tms.attempted == ["rest", "db_view", "csv"]
    assert "rest" in tms.skipped and "db_view" in tms.skipped


def test_csv_is_always_a_viable_floor(exported, dataset, tmp_path):
    """A nightly drop must always work -- it is the mode that needs no cooperation."""
    out = tmp_path / "csvonly"
    specs = export_all(dataset.pending, out)
    csv_only = SourceSpec("TMS", Department.ENGINEERING, csv_path=specs["TMS"].csv_path)
    tasks, report = ingest_source(csv_only)
    assert report.mode == "csv"
    assert tasks


# --------------------------------------------------------------------------- #
# Read-only discipline
# --------------------------------------------------------------------------- #

def test_db_adapter_refuses_a_base_table(exported):
    """A DBA grants a view. Reading the table directly is not ours to do."""
    specs, _, _ = exported
    adapter = SqliteViewAdapter(specs["SMMS"].db_path, "smms_faults")
    assert not adapter.available()
    assert "not a view" in (adapter.last_error or "")
    with pytest.raises(PermissionError):
        adapter.fetch()


def test_db_adapter_cannot_write(exported):
    specs, _, _ = exported
    adapter = SqliteViewAdapter(specs["SMMS"].db_path, specs["SMMS"].db_view)
    con = adapter._connect()
    with pytest.raises(sqlite3.OperationalError):
        con.execute("DELETE FROM smms_faults")
    con.close()


def test_ingestion_does_not_modify_the_sources(exported):
    specs, out, _ = exported
    before = {p.name: (p.stat().st_size, p.read_bytes()[:64])
              for p in Path(out).iterdir() if p.is_file()}
    ingest(specs)
    after = {p.name: (p.stat().st_size, p.read_bytes()[:64])
             for p in Path(out).iterdir() if p.is_file()}
    assert before == after, "a source system was modified during ingestion"


# --------------------------------------------------------------------------- #
# Bad records
# --------------------------------------------------------------------------- #

def test_a_malformed_record_is_rejected_by_name(tmp_path):
    """Silently dropping rows is how a division loses its worst defects for a year."""
    bad = [{
        "ohEid": "BROKEN-1",
        "location": {"section": A_SECTION, "line": "UP", "km": 2.0},
        "assetRef": "A9", "assetKind": "OHE_MAST", "job": "OHE mast / bracket attention",
        "criticality": 3, "reactive": True,
        "raisedIso": "not-a-date", "dueIso": "2026-09-10T00:00:00Z",
        "powerBlockMins": 120, "crew": 5, "plant": "TOWER_WAGON",
        "quantity": 2.0, "nightAllowed": True,
    }]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"items": bad}), encoding="utf-8")

    spec = SourceSpec("TDMS", Department.TRACTION, rest_url=path.as_uri())
    tasks, report = ingest_source(spec)

    assert tasks == []
    assert len(report.rejected) == 1
    assert report.rejected[0].record_id == "BROKEN-1"
    assert "date" in report.rejected[0].reason.lower()


def test_duplicates_are_counted_not_silently_merged(tmp_path, dataset):
    sample = next(t for t in dataset.pending if t.department is Department.TRACTION)
    from samanvay.ingestion.sources import _tdms_record

    rec = _tdms_record(sample)
    path = tmp_path / "dupes.json"
    path.write_text(json.dumps({"items": [rec, rec, rec]}), encoding="utf-8")

    spec = SourceSpec("TDMS", Department.TRACTION, rest_url=path.as_uri())
    tasks, report = ingest_source(spec)
    assert len(tasks) == 1
    assert report.duplicates == 2


def test_unknown_priority_code_is_rejected():
    raw = {
        "fault_ref": "X9", "section": A_SECTION, "line": "UP", "chainage_m": 1000,
        "equipment_id": "A1", "equipment_class": "POINT_MACHINE",
        "activity": "Point machine overhaul", "priority": "URGENT", "is_fault": 1,
        "reported_on": day_to_date(0).isoformat(), "due_on": day_to_date(5).isoformat(),
        "disconnection_minutes": 90, "staff_count": 3, "machine": "NONE",
        "qty": 1.0, "night_ok": 0,
    }
    with pytest.raises(ValueError, match="priority"):
        normalise_smms(raw)


# --------------------------------------------------------------------------- #
# The result is the same model everything else consumes
# --------------------------------------------------------------------------- #

def test_ingested_tasks_are_ordinary_maintenance_tasks(exported):
    specs, _, _ = exported
    result = ingest(specs)
    for t in result.tasks[:20]:
        assert isinstance(t.asset_class, AssetClass)
        assert isinstance(t.line, Line)
        assert isinstance(t.machine, MachineType)
        assert isinstance(t.department, Department)
        assert t.source_system == t.department.source_system
        assert t.block_type.value in {"TRAFFIC", "DISCONN", "POWER"}


def test_ingested_tasks_carry_no_ground_truth(exported):
    """Real data has no oracle. The defaults must make that obvious, not fake it."""
    specs, _, _ = exported
    result = ingest(specs)
    for t in result.tasks:
        assert t.true_duration_min == 0
        assert t.true_days_to_failure == 9_999.0
