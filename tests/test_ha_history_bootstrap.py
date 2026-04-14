import pytest
from unittest.mock import MagicMock
from tools.ha_history_bootstrap import HAHistoryBootstrap


@pytest.fixture
def mock_ha():
    """HA client mock with canned history data matching real sensor format."""
    client = MagicMock()
    # Nozzle temp: 437°F = 225°C (active print temps)
    client.get_history.return_value = [
        [
            {"entity_id": "sensor.flashforge_right_nozzle_temperature",
             "state": "unavailable", "last_changed": "2026-04-13T03:50:00"},
            {"state": "437.0", "last_changed": "2026-04-13T03:57:37"},
            {"state": "436.8", "last_changed": "2026-04-13T04:00:00"},
            {"state": "437.2", "last_changed": "2026-04-13T05:00:00"},
            {"state": "437.0", "last_changed": "2026-04-13T06:00:00"},
            {"state": "437.1", "last_changed": "2026-04-13T07:00:00"},
            {"state": "105.0", "last_changed": "2026-04-13T08:30:00"},  # cooling
        ],
        [
            {"entity_id": "sensor.flashforge_platform_temperature",
             "state": "unavailable", "last_changed": "2026-04-13T03:50:00"},
            {"state": "140.0", "last_changed": "2026-04-13T03:57:37"},
            {"state": "140.2", "last_changed": "2026-04-13T05:00:00"},
            {"state": "139.8", "last_changed": "2026-04-13T07:00:00"},
        ],
        [
            {"entity_id": "sensor.flashforge_current_print_speed",
             "state": "5.905511811", "last_changed": "2026-04-13T04:00:00"},  # 150mm/s
            {"state": "8.858267716", "last_changed": "2026-04-13T05:00:00"},  # 225mm/s
        ],
    ]
    client.get_print_status.return_value = "completed"
    client.fahrenheit_to_celsius = MagicMock(side_effect=lambda f: (f - 32) * 5 / 9)
    client.inches_per_sec_to_mms = MagicMock(side_effect=lambda v: v * 25.4)
    return client


def test_extract_nozzle_temp_from_history(mock_ha):
    bootstrap = HAHistoryBootstrap(mock_ha)
    result = bootstrap.run(start_date="2026-04-13")
    assert result["nozzle_temp"]["median_c"] == pytest.approx(225.0, abs=1.0)
    assert result["nozzle_temp"]["sample_count"] >= 4


def test_extract_bed_temp_from_history(mock_ha):
    bootstrap = HAHistoryBootstrap(mock_ha)
    result = bootstrap.run(start_date="2026-04-13")
    assert result["bed_temp"]["median_c"] == pytest.approx(60.0, abs=1.0)


def test_extract_speed_from_history(mock_ha):
    bootstrap = HAHistoryBootstrap(mock_ha)
    result = bootstrap.run(start_date="2026-04-13")
    assert result["print_speed"]["max_mms"] > 100


def test_returns_empty_when_no_hot_readings(mock_ha):
    """When all readings are idle/cold, returns None for temps."""
    mock_ha.get_history.return_value = [
        [
            {"entity_id": "sensor.flashforge_right_nozzle_temperature",
             "state": "82.0", "last_changed": "2026-04-13T09:00:00"},
        ],
        [], [],
    ]
    bootstrap = HAHistoryBootstrap(mock_ha)
    result = bootstrap.run(start_date="2026-04-13")
    assert result["nozzle_temp"] is None
