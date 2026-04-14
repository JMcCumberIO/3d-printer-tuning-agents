# tests/test_orchestrator.py
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from agents.orchestrator import Orchestrator
from tools.calibration_db import CalibrationDB
from tools.orca_profiles import OrcaProfiles


@pytest.fixture
def db(tmp_path):
    db = CalibrationDB(tmp_path / "calibration_db.json")
    db.set_baseline("ELEGOO PLA+", "0.4mm",
                    nozzle_temp=225, bed_temp=60, flow_rate=0.98,
                    pressure_advance=0.042, max_speed=150, cooling_fan=100)
    for _ in range(5):
        db.add_run("ELEGOO PLA+", "0.4mm", {"overall": 0.91, "passed": True, "phase": "calibrate"})
    return db


@pytest.fixture
def profile_dir(tmp_path):
    d = tmp_path / "profiles"
    (d / "filament").mkdir(parents=True)
    (d / "process").mkdir(parents=True)
    profile = {"name": "ELEGOO PLA+", "nozzle_temperature": ["225"]}
    (d / "filament" / "ELEGOO PLA+.json").write_text(json.dumps(profile))
    return d


def test_rollback_restores_profile(db, profile_dir, tmp_path):
    """rollback() calls OrcaProfiles.rollback_filament after writing a backup."""
    profiles = OrcaProfiles(profile_dir)
    original = profiles.read_filament("ELEGOO PLA+")
    original["nozzle_temperature"] = ["228"]
    profiles.write_filament("ELEGOO PLA+", original)  # creates .bak

    orch = Orchestrator(
        db=db, profiles=profiles, ha=MagicMock(),
        filament_research_agent=MagicMock(), calibration_agent=MagicMock(),
        profile_advisor=MagicMock(), speed_optimizer=MagicMock(),
        confirm_fn=lambda msg: True, ask_fn=lambda p: "",
    )
    orch.rollback("ELEGOO PLA+", "0.4mm")
    restored = profiles.read_filament("ELEGOO PLA+")
    assert restored["nozzle_temperature"] == ["225"]


def test_add_filament_calls_research_agent(db, tmp_path):
    mock_research = MagicMock()
    mock_research.research.return_value = {
        "source": "manufacturer + community",
        "retrieved": "2026-04-14",
        "nozzle_temp": {"recommended": 225, "range": [215, 235], "source_count": 5},
        "bed_temp": {"recommended": 60, "range": [55, 65], "source_count": 5},
        "flow_rate": {"recommended": 1.0, "range": [0.95, 1.05], "source_count": 3},
        "max_speed": {"recommended": 200, "range": [150, 300], "source_count": 4},
        "cooling_fan": {"recommended": 100, "range": [80, 100], "source_count": 4},
    }
    mock_bootstrap = MagicMock()
    mock_bootstrap.run.return_value = {"nozzle_temp": None, "bed_temp": None, "print_speed": None}

    orch = Orchestrator(
        db=db, profiles=MagicMock(), ha=MagicMock(),
        filament_research_agent=mock_research,
        calibration_agent=MagicMock(), profile_advisor=MagicMock(),
        speed_optimizer=MagicMock(), ha_bootstrap=mock_bootstrap,
        confirm_fn=lambda msg: True, ask_fn=lambda p: "",
    )
    orch.add_filament("New PLA", "0.4mm")
    mock_research.research.assert_called_once_with("New PLA", "0.4mm")


def test_add_filament_saves_research_to_db(db, tmp_path):
    research_data = {
        "source": "manufacturer + community",
        "retrieved": "2026-04-14",
        "nozzle_temp": {"recommended": 215, "range": [210, 220], "source_count": 3},
        "bed_temp": {"recommended": 55, "range": [50, 60], "source_count": 3},
        "flow_rate": {"recommended": 0.98, "range": [0.95, 1.0], "source_count": 2},
        "max_speed": {"recommended": 150, "range": [100, 200], "source_count": 2},
        "cooling_fan": {"recommended": 100, "range": [80, 100], "source_count": 2},
    }
    mock_research = MagicMock()
    mock_research.research.return_value = research_data
    mock_bootstrap = MagicMock()
    mock_bootstrap.run.return_value = {"nozzle_temp": None, "bed_temp": None, "print_speed": None}

    orch = Orchestrator(
        db=db, profiles=MagicMock(), ha=MagicMock(),
        filament_research_agent=mock_research,
        calibration_agent=MagicMock(), profile_advisor=MagicMock(),
        speed_optimizer=MagicMock(), ha_bootstrap=mock_bootstrap,
        confirm_fn=lambda msg: True, ask_fn=lambda p: "",
    )
    orch.add_filament("PETG Tough", "0.4mm")
    entry = db.get_or_create("PETG Tough", "0.4mm")
    assert entry["research_baseline"]["nozzle_temp"]["recommended"] == 215


def test_calibrate_delegates_to_calibration_agent(db, tmp_path):
    mock_cal = MagicMock()
    mock_cal.run.return_value = {"tested": [], "skipped": [], "skipped_count": 6,
                                  "declined_count": 0, "results": [], "tier": 2, "filament": "ELEGOO PLA+", "nozzle": "0.4mm"}
    orch = Orchestrator(
        db=db, profiles=MagicMock(), ha=MagicMock(),
        filament_research_agent=MagicMock(),
        calibration_agent=mock_cal, profile_advisor=MagicMock(),
        speed_optimizer=MagicMock(),
        confirm_fn=lambda msg: True, ask_fn=lambda p: "",
    )
    orch.calibrate("ELEGOO PLA+", "0.4mm")
    mock_cal.run.assert_called_once_with("ELEGOO PLA+", "0.4mm")
