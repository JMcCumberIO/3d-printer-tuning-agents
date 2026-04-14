import json
import pytest
from pathlib import Path
from datetime import datetime
from tools.calibration_db import CalibrationDB, ParameterStats


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "calibration_db.json"


def test_get_or_create_returns_new_entry(db_path):
    db = CalibrationDB(db_path)
    entry = db.get_or_create("ELEGOO PLA+", "0.4mm")
    assert entry["confidence_tier"] == 1
    assert entry["baseline"]["nozzle_temp"] is None
    assert entry["run_history"] == []


def test_get_or_create_returns_existing_entry(db_path):
    db = CalibrationDB(db_path)
    db.get_or_create("ELEGOO PLA+", "0.4mm")
    db.save()
    db2 = CalibrationDB(db_path)
    entry = db2.get_or_create("ELEGOO PLA+", "0.4mm")
    assert entry["confidence_tier"] == 1


def test_key_format(db_path):
    db = CalibrationDB(db_path)
    assert db._key("ELEGOO PLA+", "0.4mm") == "ELEGOO PLA+ | 0.4mm"


def test_set_baseline_updates_entry(db_path):
    db = CalibrationDB(db_path)
    db.get_or_create("Test PLA", "0.4mm")
    db.set_baseline("Test PLA", "0.4mm", nozzle_temp=225, bed_temp=60, flow_rate=0.98)
    entry = db.get_or_create("Test PLA", "0.4mm")
    assert entry["baseline"]["nozzle_temp"] == 225
    assert entry["baseline"]["bed_temp"] == 60
    assert entry["baseline"]["flow_rate"] == 0.98


def test_add_run_appends_to_history(db_path):
    db = CalibrationDB(db_path)
    db.get_or_create("Test PLA", "0.4mm")
    db.add_run("Test PLA", "0.4mm", {
        "nozzle_temp": 225,
        "quality_score": 0.9,
        "passed": True,
        "phase": "calibrate",
    })
    entry = db.get_or_create("Test PLA", "0.4mm")
    assert len(entry["run_history"]) == 1
    assert entry["run_history"][0]["nozzle_temp"] == 225
    assert "timestamp" in entry["run_history"][0]


def test_confidence_tier_cold_start(db_path):
    db = CalibrationDB(db_path)
    db.get_or_create("Test PLA", "0.4mm")
    assert db.get_confidence_tier("Test PLA", "0.4mm") == 1


def test_confidence_tier_warming(db_path):
    db = CalibrationDB(db_path)
    db.get_or_create("Test PLA", "0.4mm")
    for _ in range(5):
        db.add_run("Test PLA", "0.4mm", {"quality_score": 0.9, "passed": True, "phase": "calibrate"})
    assert db.get_confidence_tier("Test PLA", "0.4mm") == 2


def test_confidence_tier_confident(db_path):
    db = CalibrationDB(db_path)
    db.get_or_create("Test PLA", "0.4mm")
    for _ in range(12):
        db.add_run("Test PLA", "0.4mm", {"quality_score": 0.9, "passed": True, "phase": "calibrate"})
    assert db.get_confidence_tier("Test PLA", "0.4mm") == 3


def test_add_speed_pareto_point(db_path):
    db = CalibrationDB(db_path)
    db.get_or_create("Test PLA", "0.4mm")
    db.add_speed_pareto("Test PLA", "0.4mm", speed_mms=150, quality_score=0.91)
    db.add_speed_pareto("Test PLA", "0.4mm", speed_mms=165, quality_score=0.84)
    entry = db.get_or_create("Test PLA", "0.4mm")
    assert len(entry["speed_pareto"]) == 2
    assert entry["speed_pareto"][0]["speed"] == 150


def test_list_filaments(db_path):
    db = CalibrationDB(db_path)
    db.get_or_create("ELEGOO PLA+", "0.4mm")
    db.get_or_create("Mika Silk PLA", "0.4mm")
    db.save()
    filaments = db.list_filaments()
    assert "ELEGOO PLA+ | 0.4mm" in filaments
    assert "Mika Silk PLA | 0.4mm" in filaments


def test_set_research_baseline(db_path):
    db = CalibrationDB(db_path)
    db.get_or_create("New PLA", "0.4mm")
    research = {
        "source": "manufacturer + community",
        "retrieved": "2026-04-14",
        "nozzle_temp": {"recommended": 220, "range": [210, 230], "source_count": 8},
        "bed_temp": {"recommended": 60, "range": [55, 65], "source_count": 8},
    }
    db.set_research_baseline("New PLA", "0.4mm", research)
    entry = db.get_or_create("New PLA", "0.4mm")
    assert entry["research_baseline"]["nozzle_temp"]["recommended"] == 220
