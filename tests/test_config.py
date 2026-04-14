import os
import pytest
from unittest.mock import patch

def test_get_config_loads_ha_urls_from_env():
    with patch.dict(os.environ, {
        "HA_URL_PRIMARY": "https://test.local:8123",
        "HA_URL_FALLBACK": "https://fallback.test:8123",
        "HA_URL_CLOUD": "",
        "HA_TOKEN": "test-token",
        "HA_VERIFY_SSL": "false",
        "ORCA_PROFILE_DIR": "/tmp/orca",
        "ACTIVE_FILAMENT": "Test PLA",
        "ACTIVE_NOZZLE": "0.4mm",
    }):
        from tools.config import get_config
        config = get_config()
        assert config["ha"]["urls"] == ["https://test.local:8123", "https://fallback.test:8123"]
        assert config["ha"]["token"] == "test-token"
        assert config["ha"]["verify_ssl"] is False
        assert config["active_filament"] == "Test PLA"
        assert config["active_nozzle"] == "0.4mm"

def test_get_config_loads_yaml_calibration_values():
    from tools.config import get_config
    config = get_config()
    assert config["calibration"]["tier2_min_runs"] == 4
    assert config["calibration"]["tier3_min_runs"] == 11
    assert config["calibration"]["speed_step_percent"] == 10
    assert config["calibration"]["speed_quality_threshold"] == 0.80

def test_get_config_filters_empty_urls():
    with patch.dict(os.environ, {"HA_URL_CLOUD": "", "HA_URL_PRIMARY": "https://primary.test:8123", "HA_URL_FALLBACK": "", "HA_TOKEN": "tok"}):
        from tools.config import get_config
        config = get_config()
        assert "" not in config["ha"]["urls"]
