# tests/test_speed_optimizer.py
import json
import pytest
from unittest.mock import MagicMock
from agents.speed_optimizer import SpeedOptimizerAgent
from tools.calibration_db import CalibrationDB
from tools.print_logger import PrintLogger


@pytest.fixture
def db(tmp_path):
    db = CalibrationDB(tmp_path / "calibration_db.json")
    db.set_baseline("Test PLA", "0.4mm",
                    nozzle_temp=225, bed_temp=60, flow_rate=0.98,
                    pressure_advance=0.042, max_speed=150, cooling_fan=100)
    for _ in range(5):
        db.add_run("Test PLA", "0.4mm", {"overall": 0.91, "passed": True, "phase": "calibrate"})
    return db


def _make_agent(db, tmp_path, vision_scores, quality_threshold=0.80, steps=3):
    mock_ha = MagicMock()
    mock_ha.is_printing.side_effect = [True, False] * steps
    mock_ha.get_print_status.return_value = "completed"
    mock_ha.get_camera_snapshot.return_value = b"FAKEJPEG"
    mock_ha.ha_snapshot.return_value = {}

    mock_vision = MagicMock()
    mock_vision.score.side_effect = [
        {"stringing": 0.9, "layer_adhesion": 0.85, "warping": 0.95,
         "surface_finish": 0.88, "overall": s}
        for s in vision_scores
    ]

    logger = PrintLogger(tmp_path / "print_log")

    return SpeedOptimizerAgent(
        db=db, ha=mock_ha, vision=mock_vision, logger=logger,
        quality_threshold=quality_threshold,
        step_percent=10,
        confirm_fn=lambda msg: True,
        ask_fn=lambda prompt: "/user/models/speed_test.gcode",
        poll_interval_seconds=0,
    ), mock_ha


def test_optimizer_starts_from_baseline_max_speed(db, tmp_path):
    agent, mock_ha = _make_agent(db, tmp_path, vision_scores=[0.91, 0.88, 0.75])
    result = agent.run("Test PLA", "0.4mm")
    # First print should be at 150 * 1.10 = 165 mm/s
    first_call = mock_ha.start_print.call_args_list[0]
    assert first_call is not None


def test_optimizer_stops_when_quality_drops(db, tmp_path):
    # First speed: 0.91 (pass), second: 0.72 (fail below 0.80 threshold)
    agent, _ = _make_agent(db, tmp_path, vision_scores=[0.91, 0.72], steps=2)
    result = agent.run("Test PLA", "0.4mm")
    assert result["final_speed"] == pytest.approx(150 * 1.10)  # stays at first passing speed
    assert result["stopped_reason"] == "quality_below_threshold"


def test_optimizer_records_pareto_points(db, tmp_path):
    agent, _ = _make_agent(db, tmp_path, vision_scores=[0.91, 0.88, 0.72], steps=3)
    agent.run("Test PLA", "0.4mm")
    pareto = db.get_speed_pareto("Test PLA", "0.4mm")
    assert len(pareto) >= 2  # at least the passing points


def test_optimizer_updates_baseline_max_speed(db, tmp_path):
    agent, _ = _make_agent(db, tmp_path, vision_scores=[0.91, 0.72], steps=2)
    agent.run("Test PLA", "0.4mm")
    entry = db.get_or_create("Test PLA", "0.4mm")
    assert entry["baseline"]["max_speed"] == pytest.approx(150 * 1.10)


def test_optimizer_requires_tier2_baseline(tmp_path):
    db = CalibrationDB(tmp_path / "db.json")
    db.get_or_create("Fresh PLA", "0.4mm")  # no runs, no baseline
    logger = PrintLogger(tmp_path / "print_log")
    agent = SpeedOptimizerAgent(
        db=db, ha=MagicMock(), vision=MagicMock(), logger=logger,
        quality_threshold=0.80, step_percent=10,
        confirm_fn=lambda msg: True, ask_fn=lambda p: "/tmp/test.gcode",
        poll_interval_seconds=0,
    )
    with pytest.raises(ValueError, match="Calibrated baseline required"):
        agent.run("Fresh PLA", "0.4mm")
