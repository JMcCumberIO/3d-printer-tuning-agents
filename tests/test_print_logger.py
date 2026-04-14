# tests/test_print_logger.py
import json
import pytest
from pathlib import Path
from tools.print_logger import PrintLogger


@pytest.fixture
def logger(tmp_path):
    return PrintLogger(log_dir=tmp_path / "print_log")


def test_start_run_creates_timestamped_directory(logger):
    run_dir = logger.start_run({"nozzle_temp": 225, "filament": "ELEGOO PLA+"})
    assert run_dir.exists()
    assert run_dir.is_dir()
    # Directory name starts with a date-like timestamp
    assert run_dir.name[0:4].isdigit()


def test_start_run_writes_settings_json(logger):
    run_dir = logger.start_run({"nozzle_temp": 225})
    settings = json.loads((run_dir / "settings.json").read_text())
    assert settings["nozzle_temp"] == 225


def test_log_ha_snapshot(logger):
    run_dir = logger.start_run({})
    logger.log_ha_snapshot(run_dir, {"entity1": "state1", "entity2": "state2"})
    snap = json.loads((run_dir / "ha_snapshot.json").read_text())
    assert snap["entity1"] == "state1"


def test_log_camera_snapshot(logger):
    run_dir = logger.start_run({})
    logger.log_camera_snapshot(run_dir, b"FAKEJPEG")
    assert (run_dir / "camera_snapshot.jpg").read_bytes() == b"FAKEJPEG"


def test_log_vision_score(logger):
    run_dir = logger.start_run({})
    scores = {"overall": 0.91, "stringing": 0.88}
    logger.log_vision_score(run_dir, scores)
    saved = json.loads((run_dir / "vision_score.json").read_text())
    assert saved["overall"] == 0.91


def test_log_feedback(logger):
    run_dir = logger.start_run({})
    logger.log_feedback(run_dir, "Good first layer, some stringing on bridges")
    assert "stringing" in (run_dir / "feedback.txt").read_text()


def test_two_runs_get_different_directories(logger, monkeypatch):
    import time
    run1 = logger.start_run({"run": 1})
    time.sleep(0.01)
    run2 = logger.start_run({"run": 2})
    assert run1 != run2
