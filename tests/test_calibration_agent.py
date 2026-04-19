# tests/test_calibration_agent.py
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call
from agents.calibration_agent import CalibrationAgent
from tools.calibration_db import CalibrationDB
from tools.print_logger import PrintLogger


@pytest.fixture
def db(tmp_path):
    return CalibrationDB(tmp_path / "calibration_db.json")


@pytest.fixture
def mock_ha():
    ha = MagicMock()
    ha.is_printing.side_effect = [True, False]
    ha.get_print_status.return_value = "completed"
    ha.ha_snapshot.return_value = {"sensor.test": "42"}
    ha.get_camera_snapshot.return_value = b"FAKEJPEG"
    return ha


@pytest.fixture
def mock_vision():
    vision = MagicMock()
    vision.score.return_value = {
        "stringing": 0.9, "layer_adhesion": 0.85,
        "warping": 0.95, "surface_finish": 0.88, "overall": 0.91,
    }
    return vision


def _mock_client_suggesting(value: float, rationale: str = "good starting point"):
    client = MagicMock()
    block = MagicMock()
    block.text = json.dumps({"value": value, "rationale": rationale})
    resp = MagicMock()
    resp.content = [block]
    client.messages.create.return_value = resp
    return client


def test_run_skips_calibrated_parameters(db, mock_ha, mock_vision, tmp_path):
    """Parameters that already have a baseline value are skipped."""
    db.set_baseline("Test PLA", "0.4mm", nozzle_temp=225, bed_temp=60,
                    flow_rate=0.98, pressure_advance=0.042, max_speed=150, cooling_fan=100)
    logger = PrintLogger(tmp_path / "print_log")
    agent = CalibrationAgent(
        client=_mock_client_suggesting(225),
        db=db, ha=mock_ha, vision=mock_vision, logger=logger,
        confirm_fn=lambda msg: True,
        ask_fn=lambda prompt: "/user/models/test.gcode",
        poll_interval_seconds=0,
    )
    result = agent.run("Test PLA", "0.4mm")
    assert result["skipped_count"] == 6  # all already set
    mock_ha.start_print.assert_not_called()


def test_run_proposes_and_starts_print_for_untested_param(db, mock_ha, mock_vision, tmp_path):
    """An untested parameter triggers a print job."""
    # Pre-calibrate 5 of 6 params, leave nozzle_temp unset
    db.set_baseline("Test PLA", "0.4mm", bed_temp=60, flow_rate=0.98,
                    pressure_advance=0.042, max_speed=150, cooling_fan=100)
    logger = PrintLogger(tmp_path / "print_log")
    agent = CalibrationAgent(
        client=_mock_client_suggesting(225.0, "standard for PLA"),
        db=db, ha=mock_ha, vision=mock_vision, logger=logger,
        confirm_fn=lambda msg: True,
        ask_fn=lambda prompt: "/user/models/test.gcode",
        poll_interval_seconds=0,
    )
    result = agent.run("Test PLA", "0.4mm")
    # start_print is called with the printer path returned by upload_gcode
    mock_ha.upload_gcode.assert_called_once_with("/user/models/test.gcode")
    mock_ha.start_print.assert_called_once_with(mock_ha.upload_gcode.return_value)


def test_run_updates_db_after_print(db, mock_ha, mock_vision, tmp_path):
    """After a successful print, run_history grows and baseline is updated."""
    # Pre-calibrate 5 of 6 params, leave nozzle_temp unset
    db.set_baseline("Test PLA", "0.4mm", bed_temp=60, flow_rate=0.98,
                    pressure_advance=0.042, max_speed=150, cooling_fan=100)
    logger = PrintLogger(tmp_path / "print_log")
    agent = CalibrationAgent(
        client=_mock_client_suggesting(225.0),
        db=db, ha=mock_ha, vision=mock_vision, logger=logger,
        confirm_fn=lambda msg: True,
        ask_fn=lambda prompt: "/user/models/test.gcode",
        poll_interval_seconds=0,
    )
    agent.run("Test PLA", "0.4mm")
    entry = db.get_or_create("Test PLA", "0.4mm")
    assert len(entry["run_history"]) >= 1
    assert entry["run_history"][0]["overall"] == pytest.approx(0.91)


def test_run_skips_when_user_declines(db, mock_ha, mock_vision, tmp_path):
    """If user declines confirmation, no print is started."""
    db.get_or_create("Test PLA", "0.4mm")
    logger = PrintLogger(tmp_path / "print_log")
    agent = CalibrationAgent(
        client=_mock_client_suggesting(225.0),
        db=db, ha=mock_ha, vision=mock_vision, logger=logger,
        confirm_fn=lambda msg: False,
        ask_fn=lambda prompt: "",
        poll_interval_seconds=0,
    )
    result = agent.run("Test PLA", "0.4mm")
    mock_ha.start_print.assert_not_called()
    assert result["declined_count"] >= 1


def test_wait_for_print_polls_until_not_printing(db, mock_ha, mock_vision, tmp_path):
    """_wait_for_print returns when is_printing becomes False."""
    mock_ha.is_printing.side_effect = [True, True, False]
    mock_ha.get_print_status.return_value = "completed"
    logger = PrintLogger(tmp_path / "print_log")
    agent = CalibrationAgent(
        client=MagicMock(), db=db, ha=mock_ha, vision=mock_vision, logger=logger,
        confirm_fn=lambda msg: True, ask_fn=lambda p: "/tmp/x.gcode",
        poll_interval_seconds=0,
    )
    status = agent._wait_for_print(timeout_min=1)
    assert status == "completed"
    assert mock_ha.is_printing.call_count == 3
