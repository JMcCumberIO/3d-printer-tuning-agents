import httpx
import pytest
import respx
from tools.ha_client import HAClient

URLS = ["https://primary.test:8123", "https://fallback.test:8123"]
TOKEN = "test-token"


@respx.mock
def test_connect_uses_primary_url():
    respx.get("https://primary.test:8123/api/").mock(
        return_value=httpx.Response(200, json={"message": "API running."})
    )
    client = HAClient(urls=URLS, token=TOKEN)
    url = client.connect()
    assert url == "https://primary.test:8123"
    assert client.base_url == "https://primary.test:8123"


@respx.mock
def test_connect_falls_back_to_secondary():
    respx.get("https://primary.test:8123/api/").mock(
        side_effect=httpx.ConnectError("")
    )
    respx.get("https://fallback.test:8123/api/").mock(
        return_value=httpx.Response(200, json={"message": "API running."})
    )
    client = HAClient(urls=URLS, token=TOKEN)
    url = client.connect()
    assert url == "https://fallback.test:8123"


@respx.mock
def test_connect_raises_when_all_urls_fail():
    respx.get("https://primary.test:8123/api/").mock(side_effect=httpx.ConnectError(""))
    respx.get("https://fallback.test:8123/api/").mock(side_effect=httpx.ConnectError(""))
    client = HAClient(urls=URLS, token=TOKEN)
    with pytest.raises(ConnectionError, match="Could not connect"):
        client.connect()


@respx.mock
def test_get_state_returns_entity_dict():
    respx.get("https://primary.test:8123/api/").mock(
        return_value=httpx.Response(200, json={"message": "API running."})
    )
    respx.get("https://primary.test:8123/api/states/sensor.test").mock(
        return_value=httpx.Response(200, json={"entity_id": "sensor.test", "state": "42"})
    )
    client = HAClient(urls=URLS, token=TOKEN)
    client.connect()
    state = client.get_state("sensor.test")
    assert state["state"] == "42"


@respx.mock
def test_get_nozzle_temp_converts_fahrenheit_to_celsius():
    respx.get("https://primary.test:8123/api/").mock(
        return_value=httpx.Response(200, json={"message": "API running."})
    )
    respx.get("https://primary.test:8123/api/states/sensor.flashforge_right_nozzle_temperature").mock(
        return_value=httpx.Response(200, json={"state": "437.0"})  # 437°F = 225°C
    )
    client = HAClient(urls=URLS, token=TOKEN)
    client.connect()
    temp = client.get_nozzle_temp_c()
    assert abs(temp - 225.0) < 0.1


@respx.mock
def test_get_print_speed_converts_inches_to_mm():
    respx.get("https://primary.test:8123/api/").mock(
        return_value=httpx.Response(200, json={"message": "API running."})
    )
    respx.get("https://primary.test:8123/api/states/sensor.flashforge_current_print_speed").mock(
        return_value=httpx.Response(200, json={"state": "5.905511811"})  # 5.9 in/s ≈ 150 mm/s
    )
    client = HAClient(urls=URLS, token=TOKEN)
    client.connect()
    speed = client.get_print_speed_mms()
    assert abs(speed - 150.0) < 1.0


@respx.mock
def test_call_service_posts_to_correct_endpoint():
    respx.get("https://primary.test:8123/api/").mock(
        return_value=httpx.Response(200, json={"message": "API running."})
    )
    respx.post("https://primary.test:8123/api/services/flashforge_adventurer5m/start_print").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = HAClient(urls=URLS, token=TOKEN)
    client.connect()
    result = client.start_print("/user/models/test.gcode")
    assert result == []


@respx.mock
def test_get_camera_snapshot_returns_bytes():
    respx.get("https://primary.test:8123/api/").mock(
        return_value=httpx.Response(200, json={"message": "API running."})
    )
    respx.get("https://primary.test:8123/api/camera_proxy/camera.flashforge_adventurer_5m_pro_camera").mock(
        return_value=httpx.Response(200, content=b"FAKEJPEG")
    )
    client = HAClient(urls=URLS, token=TOKEN)
    client.connect()
    data = client.get_camera_snapshot()
    assert data == b"FAKEJPEG"


@respx.mock
def test_get_history_queries_correct_url():
    respx.get("https://primary.test:8123/api/").mock(
        return_value=httpx.Response(200, json={"message": "API running."})
    )
    respx.get("https://primary.test:8123/api/history/period/2026-04-13T00:00:00Z").mock(
        return_value=httpx.Response(200, json=[[{"state": "437.0"}], [], []])
    )
    client = HAClient(urls=URLS, token=TOKEN)
    client.connect()
    result = client.get_history(["sensor.flashforge_right_nozzle_temperature"], "2026-04-13T00:00:00")
    assert result[0][0]["state"] == "437.0"


def test_unit_conversion_fahrenheit_to_celsius():
    assert abs(HAClient.fahrenheit_to_celsius(212.0) - 100.0) < 0.01
    assert abs(HAClient.fahrenheit_to_celsius(32.0) - 0.0) < 0.01
    assert abs(HAClient.fahrenheit_to_celsius(437.0) - 225.0) < 0.1


def test_unit_conversion_inches_per_sec_to_mm_per_sec():
    assert abs(HAClient.inches_per_sec_to_mms(1.0) - 25.4) < 0.01
    assert abs(HAClient.inches_per_sec_to_mms(5.905511811) - 150.0) < 0.5


@respx.mock
def test_get_current_layer_returns_none_when_entity_missing():
    respx.get("https://primary.test:8123/api/").mock(
        return_value=httpx.Response(200, json={"message": "API running."})
    )
    respx.get(
        "https://primary.test:8123/api/states/sensor.flashforge_current_layer"
    ).mock(return_value=httpx.Response(404))
    client = HAClient(urls=URLS, token=TOKEN)
    client.connect()
    assert client.get_current_layer() is None


@respx.mock
def test_get_current_layer_returns_none_for_unavailable_state():
    respx.get("https://primary.test:8123/api/").mock(
        return_value=httpx.Response(200, json={"message": "API running."})
    )
    respx.get(
        "https://primary.test:8123/api/states/sensor.flashforge_current_layer"
    ).mock(return_value=httpx.Response(200, json={"state": "unavailable"}))
    client = HAClient(urls=URLS, token=TOKEN)
    client.connect()
    assert client.get_current_layer() is None


@respx.mock
def test_get_current_layer_returns_int_when_sensor_available():
    respx.get("https://primary.test:8123/api/").mock(
        return_value=httpx.Response(200, json={"message": "API running."})
    )
    respx.get(
        "https://primary.test:8123/api/states/sensor.flashforge_current_layer"
    ).mock(return_value=httpx.Response(200, json={"state": "42"}))
    client = HAClient(urls=URLS, token=TOKEN)
    client.connect()
    assert client.get_current_layer() == 42


@respx.mock
async def test_get_camera_snapshot_async_returns_bytes():
    respx.get("https://primary.test:8123/api/").mock(
        return_value=httpx.Response(200, json={"message": "API running."})
    )
    respx.get(
        "https://primary.test:8123/api/camera_proxy/"
        "camera.flashforge_adventurer_5m_pro_camera"
    ).mock(return_value=httpx.Response(200, content=b"ASYNCJPEG"))
    client = HAClient(urls=URLS, token=TOKEN)
    client.connect()
    data = await client.get_camera_snapshot_async()
    assert data == b"ASYNCJPEG"


@respx.mock
def test_get_total_layers_returns_int_when_sensor_available():
    respx.get("https://primary.test:8123/api/").mock(
        return_value=httpx.Response(200, json={"message": "API running."})
    )
    respx.get(
        "https://primary.test:8123/api/states/sensor.flashforge_total_layers"
    ).mock(return_value=httpx.Response(200, json={"state": "120"}))
    client = HAClient(urls=URLS, token=TOKEN)
    client.connect()
    assert client.get_total_layers() == 120


@respx.mock
def test_get_current_file_returns_string():
    respx.get("https://primary.test:8123/api/").mock(
        return_value=httpx.Response(200, json={"message": "API running."})
    )
    respx.get(
        "https://primary.test:8123/api/states/sensor.flashforge_current_print_file"
    ).mock(return_value=httpx.Response(200, json={"state": "benchy.gcode"}))
    client = HAClient(urls=URLS, token=TOKEN)
    client.connect()
    assert client.get_current_file() == "benchy.gcode"


@respx.mock
def test_get_speed_pct_returns_int():
    respx.get("https://primary.test:8123/api/").mock(
        return_value=httpx.Response(200, json={"message": "API running."})
    )
    respx.get(
        "https://primary.test:8123/api/states/sensor.flashforge_print_speed_adjustment"
    ).mock(return_value=httpx.Response(200, json={"state": "110"}))
    client = HAClient(urls=URLS, token=TOKEN)
    client.connect()
    assert client.get_speed_pct() == 110


@respx.mock
def test_get_speed_pct_scales_raw_10000_to_100():
    """FlashForge reports 10000 to mean 100%; verify normalization."""
    respx.get("https://primary.test:8123/api/").mock(
        return_value=httpx.Response(200, json={"message": "API running."})
    )
    respx.get(
        "https://primary.test:8123/api/states/sensor.flashforge_print_speed_adjustment"
    ).mock(return_value=httpx.Response(200, json={"state": "10000"}))
    client = HAClient(urls=URLS, token=TOKEN)
    client.connect()
    assert client.get_speed_pct() == 100


@respx.mock
def test_get_speed_pct_scales_boundary_1000():
    """Value of exactly 1000 (= 10.00%) should be scaled, not passed through."""
    respx.get("https://primary.test:8123/api/").mock(
        return_value=httpx.Response(200, json={"message": "API running."})
    )
    respx.get(
        "https://primary.test:8123/api/states/sensor.flashforge_print_speed_adjustment"
    ).mock(return_value=httpx.Response(200, json={"state": "1000"}))
    client = HAClient(urls=URLS, token=TOKEN)
    client.connect()
    assert client.get_speed_pct() == 10


def _mock_api(urls=None):
    respx.get("https://primary.test:8123/api/").mock(
        return_value=httpx.Response(200, json={"message": "API running."})
    )


@respx.mock
def test_is_printing_true_when_binary_sensor_on():
    _mock_api()
    respx.get(
        "https://primary.test:8123/api/states/binary_sensor.flashforge_printing"
    ).mock(return_value=httpx.Response(200, json={"state": "on"}))
    client = HAClient(urls=URLS, token=TOKEN)
    client.connect()
    assert client.is_printing() is True


@respx.mock
def test_is_printing_false_when_binary_sensor_off():
    _mock_api()
    respx.get(
        "https://primary.test:8123/api/states/binary_sensor.flashforge_printing"
    ).mock(return_value=httpx.Response(200, json={"state": "off"}))
    client = HAClient(urls=URLS, token=TOKEN)
    client.connect()
    assert client.is_printing() is False
