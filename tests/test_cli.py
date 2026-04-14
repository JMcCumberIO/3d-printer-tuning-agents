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

    assert result.exit_code != 0 or "error" in result.output.lower() or "could not connect" in result.output.lower()


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
