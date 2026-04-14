import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
from httpx import AsyncClient, ASGITransport

TEST_CONFIG = {
    "ha": {
        "urls": ["https://ha.test:8123"],
        "token": "test-token",
        "verify_ssl": False,
    },
    "dashboard": {"ha_poll_interval_seconds": 999},
    "orca": {"conf_path": "/tmp/tune3d-test-orca.conf"},
    "calibration": {
        "tier2_min_runs": 4,
        "tier3_min_runs": 11,
        "speed_quality_threshold": 0.80,
        "speed_step_percent": 10,
    },
    "active_filament": "Test PLA",
    "active_nozzle": "0.4mm",
    "orca_profile_dir": "/tmp",
}


def _mock_ha():
    m = MagicMock()
    m.get_print_status.return_value = "idle"
    m.get_nozzle_temp_c.return_value = 25.0
    m.get_bed_temp_c.return_value = 24.0
    m.get_print_progress.return_value = 0.0
    m.get_current_layer.return_value = None
    m.get_total_layers.return_value = None
    m.get_current_file.return_value = None
    m.get_speed_pct.return_value = None
    return m


@pytest.fixture
async def client():
    from server.app import app
    mock_ha = _mock_ha()
    with (
        patch("server.app.get_config", return_value=TEST_CONFIG),
        patch("server.app.HAClient", return_value=mock_ha),
        patch("server.app.OrcaSlicerWatcher") as MockWatcher,
    ):
        MockWatcher.return_value.start.return_value = None
        MockWatcher.return_value.stop.return_value = None
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac


async def test_index_returns_html(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


async def test_api_status_returns_ha_state(client):
    resp = await client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["print_status"] == "idle"
    assert data["nozzle_temp"] == 25.0
    assert data["current_layer"] is None


async def test_api_filament_returns_active_filament_data(client, tmp_path):
    db_file = tmp_path / "calibration_db.json"
    db_file.write_text(json.dumps({
        "Test PLA | 0.4mm": {
            "confidence_tier": 2,
            "baseline": {"nozzle_temp": 215, "bed_temp": 60},
            "research_baseline": None,
            "speed_pareto": [{"speed": 150, "quality_score": 0.9}],
            "run_history": [{"param": "nozzle_temp"}] * 5,
            "parameters": {},
        }
    }))
    with patch("server.app.DB_PATH", db_file):
        resp = await client.get("/api/filament")
    assert resp.status_code == 200
    data = resp.json()
    assert data["filament"] == "Test PLA"
    assert data["tier"] == 2
    assert data["speed_pareto"][0]["speed"] == 150


async def test_api_capture_returns_vision_scores(client):
    mock_scores = {
        "stringing": 0.9, "layer_adhesion": 0.85,
        "warping": 0.95, "surface_finish": 0.88, "overall": 0.89,
    }
    with patch("server.app.VisionAgent") as MockVision:
        MockVision.return_value.score.return_value = mock_scores
        resp = await client.post("/api/capture")
    assert resp.status_code == 200
    assert resp.json()["overall"] == 0.89
