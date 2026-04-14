import json
import pytest
from pathlib import Path
from click.testing import CliRunner
from unittest.mock import patch, MagicMock
from tune import cli


@pytest.fixture
def runner():
    return CliRunner()


def test_status_shows_connected_when_ha_reachable(runner):
    mock_client = MagicMock()
    mock_client.connect.return_value = "https://192.168.1.191:8123"
    mock_client.get_print_status.return_value = "idle"
    mock_client.get_nozzle_temp_c.return_value = 28.5
    mock_client.get_bed_temp_c.return_value = 27.0
    mock_client.is_printing.return_value = False

    with patch("tune.build_ha_client", return_value=mock_client):
        result = runner.invoke(cli, ["status"])

    assert result.exit_code == 0
    assert "192.168.1.191" in result.output
    assert "idle" in result.output.lower()


def test_status_shows_error_when_ha_unreachable(runner):
    mock_client = MagicMock()
    mock_client.connect.side_effect = ConnectionError("Could not connect")

    with patch("tune.build_ha_client", return_value=mock_client):
        result = runner.invoke(cli, ["status"])

    assert result.exit_code == 1
    assert "could not connect" in result.output.lower()


def test_list_filaments_shows_db_entries(runner, tmp_path):
    db_file = tmp_path / "calibration_db.json"
    db_file.write_text(json.dumps({
        "ELEGOO PLA+ | 0.4mm": {"confidence_tier": 2, "run_history": [{}] * 5},
        "Mika Silk PLA | 0.4mm": {"confidence_tier": 1, "run_history": []},
    }))

    with patch("tune.DB_PATH", db_file):
        result = runner.invoke(cli, ["list-filaments"])

    assert result.exit_code == 0
    assert "ELEGOO PLA+" in result.output
    assert "Mika Silk PLA" in result.output
    assert "Tier 2" in result.output
    assert "Tier 1" in result.output


def test_list_filaments_empty_db(runner, tmp_path):
    db_file = tmp_path / "calibration_db.json"

    with patch("tune.DB_PATH", db_file):
        result = runner.invoke(cli, ["list-filaments"])

    assert result.exit_code == 0
    assert "no filaments" in result.output.lower()


def test_add_filament_calls_orchestrator(runner):
    mock_orch = MagicMock()
    mock_orch.add_filament.return_value = {
        "filament": "Test PLA", "nozzle": "0.4mm",
        "research": {"nozzle_temp": {"recommended": 225}},
        "ha_bootstrap": None,
    }
    with patch("tune.Orchestrator") as MockOrch:
        MockOrch.from_config.return_value = mock_orch
        result = runner.invoke(cli, ["add-filament", "--filament", "Test PLA", "--nozzle", "0.4mm"])
    assert result.exit_code == 0
    mock_orch.add_filament.assert_called_once_with("Test PLA", "0.4mm")


def test_calibrate_calls_orchestrator(runner):
    mock_orch = MagicMock()
    mock_orch.calibrate.return_value = {
        "filament": "Test PLA", "nozzle": "0.4mm", "tier": 1,
        "tested": ["nozzle_temp"], "skipped": [], "skipped_count": 0,
        "declined_count": 0, "results": [],
    }
    with patch("tune.Orchestrator") as MockOrch:
        MockOrch.from_config.return_value = mock_orch
        result = runner.invoke(cli, ["calibrate", "--filament", "Test PLA", "--nozzle", "0.4mm"])
    assert result.exit_code == 0
    mock_orch.calibrate.assert_called_once_with("Test PLA", "0.4mm")


def test_advise_calls_orchestrator(runner, tmp_path):
    fake_3mf = tmp_path / "model.3mf"
    fake_3mf.write_bytes(b"PK")  # minimal placeholder
    mock_orch = MagicMock()
    mock_orch.advise.return_value = {
        "recommendations": [], "summary": "No changes needed."
    }
    with patch("tune.Orchestrator") as MockOrch:
        MockOrch.from_config.return_value = mock_orch
        result = runner.invoke(cli, ["advise", str(fake_3mf), "--filament", "Test PLA", "--nozzle", "0.4mm"])
    assert result.exit_code == 0
    mock_orch.advise.assert_called_once()


def test_speed_calls_orchestrator(runner):
    mock_orch = MagicMock()
    mock_orch.speed_push.return_value = {
        "filament": "Test PLA", "nozzle": "0.4mm",
        "final_speed": 165.0, "stopped_reason": "quality_below_threshold",
        "pareto_points": [{"speed": 165, "quality": 0.91}],
    }
    with patch("tune.Orchestrator") as MockOrch:
        MockOrch.from_config.return_value = mock_orch
        result = runner.invoke(cli, ["speed", "--filament", "Test PLA", "--nozzle", "0.4mm"])
    assert result.exit_code == 0
    mock_orch.speed_push.assert_called_once()


def test_rollback_calls_orchestrator(runner):
    mock_orch = MagicMock()
    with patch("tune.Orchestrator") as MockOrch:
        MockOrch.from_config.return_value = mock_orch
        result = runner.invoke(cli, ["rollback", "--filament", "Test PLA", "--nozzle", "0.4mm"])
    assert result.exit_code == 0
    mock_orch.rollback.assert_called_once_with("Test PLA", "0.4mm")
