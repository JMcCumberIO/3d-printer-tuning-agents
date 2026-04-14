# 3D Printer Tuning Agents — Plan 1: Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete tools and infrastructure layer — HA client, OrcaSlicer profile R/W, calibration database, gcode extractor, HA history bootstrap, and CLI skeleton — fully tested and ready for agents to build on.

**Architecture:** Tools layer is a set of pure Python modules with no agent dependencies. Each module has one responsibility and is tested in isolation with mocked external calls. The CLI skeleton wires them together and proves the integration works end-to-end.

**Tech Stack:** Python 3.11+ · `httpx` · `click` · `python-dotenv` · `PyYAML` · `watchdog` · `pytest` · `respx` (HTTP mocking) · `anthropic` (installed for Plan 2)

---

## File Map

| File | Responsibility |
|---|---|
| `pyproject.toml` | Project metadata + dependency pinning |
| `config.yaml` | Tunable constants (tier thresholds, speed step, quality threshold) |
| `.env.example` | Secret template (committed) |
| `tools/__init__.py` | Empty |
| `tools/config.py` | Load `.env` + `config.yaml`, return typed config dict |
| `tools/ha_client.py` | HA REST wrapper: URL fallback, unit conversions, state reads, service calls, camera snapshot, history query |
| `tools/orca_profiles.py` | Read/write/backup OrcaSlicer JSON profiles in `~/.config/OrcaSlicer/user/default/` |
| `tools/calibration_db.py` | CRUD on `calibration_db.json`: entries, run history, confidence scoring, tier calculation, Pareto points |
| `tools/gcode_extractor.py` | Extract gcode + PNG thumbnail from `.3mf` (ZIP archive) |
| `tools/ha_history_bootstrap.py` | Query HA history for completed print sessions, extract stable params, return bootstrap dict |
| `tune.py` | CLI entry point: `status`, `list-filaments` commands |
| `tests/test_config.py` | Config loader tests |
| `tests/test_ha_client.py` | HA client tests with `respx` HTTP mocking |
| `tests/test_orca_profiles.py` | Profile R/W tests with `tmp_path` |
| `tests/test_calibration_db.py` | Calibration DB tests with `tmp_path` |
| `tests/test_gcode_extractor.py` | Extractor tests with synthetic `.3mf` fixture |
| `tests/test_ha_history_bootstrap.py` | Bootstrap tests with mocked HA history responses |
| `tests/test_cli.py` | CLI tests with `click.testing.CliRunner` |

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `config.yaml`
- Create: `.env.example`
- Create: `tools/__init__.py`
- Create: `tests/__init__.py`
- Create: `agents/__init__.py`
- Create: `dashboard/__init__.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "tune3d"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.40.0",
    "httpx>=0.27.0",
    "click>=8.1.0",
    "python-dotenv>=1.0.0",
    "PyYAML>=6.0.0",
    "watchdog>=5.0.0",
    "fastapi>=0.115.0",
    "uvicorn>=0.32.0",
    "pillow>=10.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "respx>=0.21.0",
]

[project.scripts]
tune = "tune:cli"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Create `config.yaml`**

```yaml
calibration:
  tier2_min_runs: 4
  tier3_min_runs: 11
  tier2_auto_proceed_variance: 0.05   # 5% from last known-good
  speed_step_percent: 10
  speed_quality_threshold: 0.80

vision:
  quality_dimensions:
    - stringing
    - layer_adhesion
    - warping
    - surface_finish
    - overall

dashboard:
  port: 8000
  ha_poll_interval_seconds: 5

ha:
  snapshot_entity: "camera.flashforge_adventurer_5m_pro_camera"
  status_entity: "sensor.flashforge_status"
  printing_entity: "binary_sensor.flashforge_printing"
  progress_entity: "sensor.flashforge_print_progress"
  eta_entity: "sensor.flashforge_estimated_time_remaining"
  nozzle_temp_entity: "sensor.flashforge_right_nozzle_temperature"
  bed_temp_entity: "sensor.flashforge_platform_temperature"
  print_speed_entity: "sensor.flashforge_current_print_speed"

orca:
  conf_path: "~/.config/OrcaSlicer/OrcaSlicer.conf"
  cache_dir: "~/.config/OrcaSlicer/cache"
```

- [ ] **Step 3: Create `.env.example`**

```env
# Home Assistant — copy to .env and fill in values
HA_URL_PRIMARY=https://192.168.1.191:8123
HA_URL_FALLBACK=https://hayjo.ddns.net:8123
HA_URL_CLOUD=https://YOUR_NABU_CASA_ID.ui.nabu.casa
HA_TOKEN=your-long-lived-access-token-here
HA_VERIFY_SSL=false

# OrcaSlicer
ORCA_PROFILE_DIR=~/.config/OrcaSlicer/user/default

# Active filament (set before running calibrate/advise/speed)
ACTIVE_FILAMENT=ELEGOO PLA+ High Speed
ACTIVE_NOZZLE=0.4mm

# Anthropic
ANTHROPIC_API_KEY=your-api-key-here
```

- [ ] **Step 4: Create empty `__init__.py` files**

```bash
touch tools/__init__.py tests/__init__.py agents/__init__.py dashboard/__init__.py
mkdir -p print_log dashboard/static dashboard/templates
```

- [ ] **Step 5: Install dependencies**

```bash
pip install -e ".[dev]"
```

Expected: Successfully installed tune3d and all dependencies.

- [ ] **Step 6: Copy `.env.example` to `.env` and fill in real values**

```bash
cp .env.example .env
# Edit .env and set:
# HA_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
# ANTHROPIC_API_KEY=sk-ant-...
```

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml config.yaml .env.example tools/__init__.py tests/__init__.py agents/__init__.py dashboard/__init__.py
git commit -m "feat: project scaffolding, dependencies, config template"
```

---

## Task 2: Config Loader

**Files:**
- Create: `tools/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_config.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tools.config'`

- [ ] **Step 3: Write `tools/config.py`**

```python
import os
from pathlib import Path
import yaml
from dotenv import load_dotenv

load_dotenv()

_config_path = Path(__file__).parent.parent / "config.yaml"


def get_config() -> dict:
    with open(_config_path) as f:
        config = yaml.safe_load(f)

    urls = [
        os.getenv("HA_URL_PRIMARY", "https://192.168.1.191:8123"),
        os.getenv("HA_URL_FALLBACK", "https://hayjo.ddns.net:8123"),
        os.getenv("HA_URL_CLOUD", ""),
    ]
    config["ha"]["urls"] = [u for u in urls if u]
    config["ha"]["token"] = os.getenv("HA_TOKEN", "")
    config["ha"]["verify_ssl"] = os.getenv("HA_VERIFY_SSL", "false").lower() == "true"

    config["orca_profile_dir"] = os.path.expanduser(
        os.getenv("ORCA_PROFILE_DIR", "~/.config/OrcaSlicer/user/default")
    )
    config["active_filament"] = os.getenv("ACTIVE_FILAMENT", "")
    config["active_nozzle"] = os.getenv("ACTIVE_NOZZLE", "0.4mm")
    return config
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/config.py tests/test_config.py
git commit -m "feat: config loader with .env + yaml merging"
```

---

## Task 3: HA Client

**Files:**
- Create: `tools/ha_client.py`
- Create: `tests/test_ha_client.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ha_client.py
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
    respx.post("https://primary.test:8123/api/services/flashforge/start_print").mock(
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


def test_unit_conversion_fahrenheit_to_celsius():
    assert abs(HAClient.fahrenheit_to_celsius(212.0) - 100.0) < 0.01
    assert abs(HAClient.fahrenheit_to_celsius(32.0) - 0.0) < 0.01
    assert abs(HAClient.fahrenheit_to_celsius(437.0) - 225.0) < 0.1


def test_unit_conversion_inches_per_sec_to_mm_per_sec():
    assert abs(HAClient.inches_per_sec_to_mms(1.0) - 25.4) < 0.01
    assert abs(HAClient.inches_per_sec_to_mms(5.905511811) - 150.0) < 0.5
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_ha_client.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tools.ha_client'`

- [ ] **Step 3: Write `tools/ha_client.py`**

```python
import httpx
from typing import Optional


class HAClient:
    NOZZLE_TEMP_ENTITY = "sensor.flashforge_right_nozzle_temperature"
    BED_TEMP_ENTITY = "sensor.flashforge_platform_temperature"
    STATUS_ENTITY = "sensor.flashforge_status"
    PRINTING_ENTITY = "binary_sensor.flashforge_printing"
    PROGRESS_ENTITY = "sensor.flashforge_print_progress"
    SPEED_ENTITY = "sensor.flashforge_current_print_speed"
    CAMERA_ENTITY = "camera.flashforge_adventurer_5m_pro_camera"

    def __init__(self, urls: list[str], token: str, verify_ssl: bool = False):
        self.urls = [u for u in urls if u]
        self.token = token
        self.verify_ssl = verify_ssl
        self.base_url: Optional[str] = None
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def connect(self) -> str:
        for url in self.urls:
            try:
                r = httpx.get(
                    f"{url}/api/",
                    headers=self._headers,
                    verify=self.verify_ssl,
                    timeout=5.0,
                )
                if r.status_code == 200:
                    self.base_url = url
                    return url
            except (httpx.ConnectError, httpx.TimeoutException):
                continue
        raise ConnectionError(f"Could not connect to HA at any of: {self.urls}")

    def _get(self, path: str) -> httpx.Response:
        r = httpx.get(
            f"{self.base_url}{path}",
            headers=self._headers,
            verify=self.verify_ssl,
            timeout=10.0,
        )
        r.raise_for_status()
        return r

    def _post(self, path: str, data: dict) -> httpx.Response:
        r = httpx.post(
            f"{self.base_url}{path}",
            headers=self._headers,
            json=data,
            verify=self.verify_ssl,
            timeout=10.0,
        )
        r.raise_for_status()
        return r

    def get_state(self, entity_id: str) -> dict:
        return self._get(f"/api/states/{entity_id}").json()

    def get_all_states(self) -> list[dict]:
        return self._get("/api/states").json()

    def call_service(self, domain: str, service: str, data: dict) -> list:
        return self._post(f"/api/services/{domain}/{service}", data).json()

    def get_camera_snapshot(self, entity_id: str = CAMERA_ENTITY) -> bytes:
        r = httpx.get(
            f"{self.base_url}/api/camera_proxy/{entity_id}",
            headers=self._headers,
            verify=self.verify_ssl,
            timeout=15.0,
        )
        r.raise_for_status()
        return r.content

    def get_history(self, entity_ids: list[str], start_time: str) -> list:
        r = httpx.get(
            f"{self.base_url}/api/history/period/{start_time}Z",
            headers=self._headers,
            params={
                "filter_entity_id": ",".join(entity_ids),
                "minimal_response": "true",
                "no_attributes": "true",
            },
            verify=self.verify_ssl,
            timeout=30.0,
        )
        r.raise_for_status()
        return r.json()

    # --- Unit conversions ---

    @staticmethod
    def fahrenheit_to_celsius(f: float) -> float:
        return (f - 32) * 5 / 9

    @staticmethod
    def inches_per_sec_to_mms(v: float) -> float:
        return v * 25.4

    # --- Typed state accessors ---

    def get_nozzle_temp_c(self) -> float:
        state = self.get_state(self.NOZZLE_TEMP_ENTITY)
        return self.fahrenheit_to_celsius(float(state["state"]))

    def get_bed_temp_c(self) -> float:
        state = self.get_state(self.BED_TEMP_ENTITY)
        return self.fahrenheit_to_celsius(float(state["state"]))

    def get_print_status(self) -> str:
        return self.get_state(self.STATUS_ENTITY)["state"]

    def get_print_progress(self) -> float:
        return float(self.get_state(self.PROGRESS_ENTITY)["state"])

    def is_printing(self) -> bool:
        return self.get_state(self.PRINTING_ENTITY)["state"] == "on"

    def get_print_speed_mms(self) -> float:
        state = self.get_state(self.SPEED_ENTITY)
        return self.inches_per_sec_to_mms(float(state["state"]))

    # --- Service calls ---

    def start_print(self, file_path: str) -> list:
        return self.call_service("flashforge", "start_print", {"file_path": file_path})

    def pause_print(self) -> list:
        return self.call_service("flashforge", "pause_print", {})

    def cancel_print(self) -> list:
        return self.call_service("flashforge", "cancel_print", {})

    def ha_snapshot(self) -> dict[str, str]:
        """Return all HA entity states as a flat dict for logging."""
        states = self.get_all_states()
        return {s["entity_id"]: s["state"] for s in states}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_ha_client.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/ha_client.py tests/test_ha_client.py
git commit -m "feat: HA client with URL fallback, unit conversions, service calls"
```

---

## Task 4: OrcaSlicer Profile Tools

**Files:**
- Create: `tools/orca_profiles.py`
- Create: `tests/test_orca_profiles.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_orca_profiles.py
import json
import pytest
from pathlib import Path
from tools.orca_profiles import OrcaProfiles


@pytest.fixture
def profile_dir(tmp_path):
    filament_dir = tmp_path / "filament"
    process_dir = tmp_path / "process"
    filament_dir.mkdir()
    process_dir.mkdir()

    filament_profile = {
        "name": "ELEGOO PLA+ High Speed",
        "nozzle_temperature": ["225"],
        "hot_plate_temp": ["60"],
        "from": "User",
        "inherits": "Generic PLA High Speed @System",
    }
    (filament_dir / "ELEGOO PLA+ High Speed.json").write_text(json.dumps(filament_profile))

    process_profile = {
        "name": "0.20mm Standard @Flashforge AD5M Pro 0.4 Nozzle",
        "wall_loops": "5",
        "sparse_infill_pattern": "gyroid",
        "from": "User",
    }
    (process_dir / "0.20mm Standard @Flashforge AD5M Pro 0.4 Nozzle.json").write_text(
        json.dumps(process_profile)
    )
    return tmp_path


def test_read_filament_profile(profile_dir):
    op = OrcaProfiles(profile_dir)
    profile = op.read_filament("ELEGOO PLA+ High Speed")
    assert profile["nozzle_temperature"] == ["225"]
    assert profile["hot_plate_temp"] == ["60"]


def test_read_nonexistent_profile_raises(profile_dir):
    op = OrcaProfiles(profile_dir)
    with pytest.raises(FileNotFoundError, match="Filament profile not found"):
        op.read_filament("Nonexistent Filament")


def test_write_filament_profile_creates_backup(profile_dir):
    op = OrcaProfiles(profile_dir)
    original = op.read_filament("ELEGOO PLA+ High Speed")
    original["nozzle_temperature"] = ["227"]
    op.write_filament("ELEGOO PLA+ High Speed", original)

    # Backup must exist
    bak = profile_dir / "filament" / "ELEGOO PLA+ High Speed.json.bak"
    assert bak.exists()

    # Original backup has old value
    bak_data = json.loads(bak.read_text())
    assert bak_data["nozzle_temperature"] == ["225"]

    # New file has updated value
    updated = op.read_filament("ELEGOO PLA+ High Speed")
    assert updated["nozzle_temperature"] == ["227"]


def test_rollback_restores_backup(profile_dir):
    op = OrcaProfiles(profile_dir)
    original = op.read_filament("ELEGOO PLA+ High Speed")
    original["nozzle_temperature"] = ["230"]
    op.write_filament("ELEGOO PLA+ High Speed", original)

    op.rollback_filament("ELEGOO PLA+ High Speed")
    restored = op.read_filament("ELEGOO PLA+ High Speed")
    assert restored["nozzle_temperature"] == ["225"]


def test_rollback_raises_when_no_backup(profile_dir):
    op = OrcaProfiles(profile_dir)
    with pytest.raises(FileNotFoundError, match="No backup found"):
        op.rollback_filament("ELEGOO PLA+ High Speed")


def test_list_filament_profiles(profile_dir):
    op = OrcaProfiles(profile_dir)
    profiles = op.list_filament_profiles()
    assert "ELEGOO PLA+ High Speed" in profiles


def test_read_process_profile(profile_dir):
    op = OrcaProfiles(profile_dir)
    profile = op.read_process("0.20mm Standard @Flashforge AD5M Pro 0.4 Nozzle")
    assert profile["wall_loops"] == "5"
    assert profile["sparse_infill_pattern"] == "gyroid"


def test_write_process_profile_creates_backup(profile_dir):
    op = OrcaProfiles(profile_dir)
    original = op.read_process("0.20mm Standard @Flashforge AD5M Pro 0.4 Nozzle")
    original["wall_loops"] = "4"
    op.write_process("0.20mm Standard @Flashforge AD5M Pro 0.4 Nozzle", original)

    bak = profile_dir / "process" / "0.20mm Standard @Flashforge AD5M Pro 0.4 Nozzle.json.bak"
    assert bak.exists()
    bak_data = json.loads(bak.read_text())
    assert bak_data["wall_loops"] == "5"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_orca_profiles.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tools.orca_profiles'`

- [ ] **Step 3: Write `tools/orca_profiles.py`**

```python
import json
import shutil
from pathlib import Path


class OrcaProfiles:
    def __init__(self, profile_dir: str | Path):
        self.profile_dir = Path(profile_dir)
        self.filament_dir = self.profile_dir / "filament"
        self.process_dir = self.profile_dir / "process"

    def _filament_path(self, name: str) -> Path:
        return self.filament_dir / f"{name}.json"

    def _process_path(self, name: str) -> Path:
        return self.process_dir / f"{name}.json"

    def read_filament(self, name: str) -> dict:
        path = self._filament_path(name)
        if not path.exists():
            raise FileNotFoundError(f"Filament profile not found: {path}")
        return json.loads(path.read_text())

    def write_filament(self, name: str, data: dict) -> None:
        path = self._filament_path(name)
        if path.exists():
            shutil.copy2(path, path.with_suffix(".json.bak"))
        path.write_text(json.dumps(data, indent=2))

    def rollback_filament(self, name: str) -> None:
        bak = self._filament_path(name).with_suffix(".json.bak")
        if not bak.exists():
            raise FileNotFoundError(f"No backup found for filament profile: {name}")
        shutil.copy2(bak, self._filament_path(name))

    def list_filament_profiles(self) -> list[str]:
        return [
            p.stem
            for p in self.filament_dir.glob("*.json")
            if not p.name.endswith(".bak")
        ]

    def read_process(self, name: str) -> dict:
        path = self._process_path(name)
        if not path.exists():
            raise FileNotFoundError(f"Process profile not found: {path}")
        return json.loads(path.read_text())

    def write_process(self, name: str, data: dict) -> None:
        path = self._process_path(name)
        if path.exists():
            shutil.copy2(path, path.with_suffix(".json.bak"))
        path.write_text(json.dumps(data, indent=2))

    def rollback_process(self, name: str) -> None:
        bak = self._process_path(name).with_suffix(".json.bak")
        if not bak.exists():
            raise FileNotFoundError(f"No backup found for process profile: {name}")
        shutil.copy2(bak, self._process_path(name))

    def list_process_profiles(self) -> list[str]:
        return [
            p.stem
            for p in self.process_dir.glob("*.json")
            if not p.name.endswith(".bak")
        ]

    def profile_diff(self, original: dict, updated: dict) -> dict[str, tuple]:
        """Return {key: (old_value, new_value)} for changed keys."""
        return {
            k: (original.get(k), updated[k])
            for k in updated
            if updated[k] != original.get(k)
        }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_orca_profiles.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/orca_profiles.py tests/test_orca_profiles.py
git commit -m "feat: OrcaSlicer profile R/W with atomic backup + rollback"
```

---

## Task 5: Calibration Database

**Files:**
- Create: `tools/calibration_db.py`
- Create: `tests/test_calibration_db.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_calibration_db.py
import json
import pytest
from pathlib import Path
from datetime import datetime
from tools.calibration_db import CalibrationDB, ParameterStats


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "calibration_db.json"


def test_get_or_create_returns_new_entry(db_path):
    db = CalibrationDB(db_path)
    entry = db.get_or_create("ELEGOO PLA+", "0.4mm")
    assert entry["confidence_tier"] == 1
    assert entry["baseline"]["nozzle_temp"] is None
    assert entry["run_history"] == []


def test_get_or_create_returns_existing_entry(db_path):
    db = CalibrationDB(db_path)
    db.get_or_create("ELEGOO PLA+", "0.4mm")
    db.save()
    db2 = CalibrationDB(db_path)
    entry = db2.get_or_create("ELEGOO PLA+", "0.4mm")
    assert entry["confidence_tier"] == 1


def test_key_format(db_path):
    db = CalibrationDB(db_path)
    assert db._key("ELEGOO PLA+", "0.4mm") == "ELEGOO PLA+ | 0.4mm"


def test_set_baseline_updates_entry(db_path):
    db = CalibrationDB(db_path)
    db.get_or_create("Test PLA", "0.4mm")
    db.set_baseline("Test PLA", "0.4mm", nozzle_temp=225, bed_temp=60, flow_rate=0.98)
    entry = db.get_or_create("Test PLA", "0.4mm")
    assert entry["baseline"]["nozzle_temp"] == 225
    assert entry["baseline"]["bed_temp"] == 60
    assert entry["baseline"]["flow_rate"] == 0.98


def test_add_run_appends_to_history(db_path):
    db = CalibrationDB(db_path)
    db.get_or_create("Test PLA", "0.4mm")
    db.add_run("Test PLA", "0.4mm", {
        "nozzle_temp": 225,
        "quality_score": 0.9,
        "passed": True,
        "phase": "calibrate",
    })
    entry = db.get_or_create("Test PLA", "0.4mm")
    assert len(entry["run_history"]) == 1
    assert entry["run_history"][0]["nozzle_temp"] == 225
    assert "timestamp" in entry["run_history"][0]


def test_confidence_tier_cold_start(db_path):
    db = CalibrationDB(db_path)
    db.get_or_create("Test PLA", "0.4mm")
    assert db.get_confidence_tier("Test PLA", "0.4mm") == 1


def test_confidence_tier_warming(db_path):
    db = CalibrationDB(db_path)
    db.get_or_create("Test PLA", "0.4mm")
    for _ in range(5):
        db.add_run("Test PLA", "0.4mm", {"quality_score": 0.9, "passed": True, "phase": "calibrate"})
    assert db.get_confidence_tier("Test PLA", "0.4mm") == 2


def test_confidence_tier_confident(db_path):
    db = CalibrationDB(db_path)
    db.get_or_create("Test PLA", "0.4mm")
    for _ in range(12):
        db.add_run("Test PLA", "0.4mm", {"quality_score": 0.9, "passed": True, "phase": "calibrate"})
    assert db.get_confidence_tier("Test PLA", "0.4mm") == 3


def test_add_speed_pareto_point(db_path):
    db = CalibrationDB(db_path)
    db.get_or_create("Test PLA", "0.4mm")
    db.add_speed_pareto("Test PLA", "0.4mm", speed_mms=150, quality_score=0.91)
    db.add_speed_pareto("Test PLA", "0.4mm", speed_mms=165, quality_score=0.84)
    entry = db.get_or_create("Test PLA", "0.4mm")
    assert len(entry["speed_pareto"]) == 2
    assert entry["speed_pareto"][0]["speed"] == 150


def test_list_filaments(db_path):
    db = CalibrationDB(db_path)
    db.get_or_create("ELEGOO PLA+", "0.4mm")
    db.get_or_create("Mika Silk PLA", "0.4mm")
    db.save()
    filaments = db.list_filaments()
    assert "ELEGOO PLA+ | 0.4mm" in filaments
    assert "Mika Silk PLA | 0.4mm" in filaments


def test_set_research_baseline(db_path):
    db = CalibrationDB(db_path)
    db.get_or_create("New PLA", "0.4mm")
    research = {
        "source": "manufacturer + community",
        "retrieved": "2026-04-14",
        "nozzle_temp": {"recommended": 220, "range": [210, 230], "source_count": 8},
        "bed_temp": {"recommended": 60, "range": [55, 65], "source_count": 8},
    }
    db.set_research_baseline("New PLA", "0.4mm", research)
    entry = db.get_or_create("New PLA", "0.4mm")
    assert entry["research_baseline"]["nozzle_temp"]["recommended"] == 220
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_calibration_db.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tools.calibration_db'`

- [ ] **Step 3: Write `tools/calibration_db.py`**

```python
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class ParameterStats:
    sample_count: int = 0
    confidence: float = 0.0
    proven_range: list[float] = field(default_factory=list)
    pass_rate: float = 0.0


_EMPTY_ENTRY = {
    "confidence_tier": 1,
    "baseline": {
        "nozzle_temp": None,
        "bed_temp": None,
        "flow_rate": None,
        "pressure_advance": None,
        "max_speed": None,
        "cooling_fan": None,
    },
    "parameters": {},
    "research_baseline": None,
    "speed_pareto": [],
    "run_history": [],
}


class CalibrationDB:
    def __init__(self, db_path: str | Path, tier2_min: int = 4, tier3_min: int = 11):
        self.db_path = Path(db_path)
        self.tier2_min = tier2_min
        self.tier3_min = tier3_min
        self._data: dict = {}
        if self.db_path.exists():
            self._data = json.loads(self.db_path.read_text())

    @staticmethod
    def _key(filament: str, nozzle: str) -> str:
        return f"{filament} | {nozzle}"

    def get_or_create(self, filament: str, nozzle: str) -> dict:
        key = self._key(filament, nozzle)
        if key not in self._data:
            import copy
            self._data[key] = copy.deepcopy(_EMPTY_ENTRY)
        return self._data[key]

    def save(self) -> None:
        self.db_path.write_text(json.dumps(self._data, indent=2))

    def set_baseline(self, filament: str, nozzle: str, **kwargs) -> None:
        entry = self.get_or_create(filament, nozzle)
        for k, v in kwargs.items():
            entry["baseline"][k] = v
        self.save()

    def set_research_baseline(self, filament: str, nozzle: str, research: dict) -> None:
        entry = self.get_or_create(filament, nozzle)
        entry["research_baseline"] = research
        self.save()

    def add_run(self, filament: str, nozzle: str, run_data: dict) -> None:
        entry = self.get_or_create(filament, nozzle)
        run = {**run_data, "timestamp": datetime.now(timezone.utc).isoformat()}
        entry["run_history"].append(run)
        entry["confidence_tier"] = self.get_confidence_tier(filament, nozzle)
        self.save()

    def add_speed_pareto(self, filament: str, nozzle: str, speed_mms: float, quality_score: float) -> None:
        entry = self.get_or_create(filament, nozzle)
        entry["speed_pareto"].append({
            "speed": speed_mms,
            "quality_score": quality_score,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self.save()

    def get_confidence_tier(self, filament: str, nozzle: str) -> int:
        entry = self.get_or_create(filament, nozzle)
        n = len(entry["run_history"])
        if n >= self.tier3_min:
            return 3
        if n >= self.tier2_min:
            return 2
        return 1

    def list_filaments(self) -> list[str]:
        return list(self._data.keys())

    def get_speed_pareto(self, filament: str, nozzle: str) -> list[dict]:
        return self.get_or_create(filament, nozzle)["speed_pareto"]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_calibration_db.py -v
```

Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/calibration_db.py tests/test_calibration_db.py
git commit -m "feat: calibration DB with run history, confidence tiers, Pareto storage"
```

---

## Task 6: GCode Extractor

**Files:**
- Create: `tools/gcode_extractor.py`
- Create: `tests/test_gcode_extractor.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_gcode_extractor.py
import io
import zipfile
import pytest
from pathlib import Path
from tools.gcode_extractor import GcodeExtractor


@pytest.fixture
def fake_3mf(tmp_path) -> Path:
    """Build a minimal .3mf ZIP with gcode and thumbnail."""
    path = tmp_path / "test_model.3mf"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Metadata/thumbnail.png", b"FAKEPNG")
        zf.writestr("Metadata/plate_1.gcode", b"; gcode start\nG28\nG1 X10 Y10\n")
        zf.writestr("3D/3dmodel.model", b"<model/>")
    return path


@pytest.fixture
def fake_3mf_no_gcode(tmp_path) -> Path:
    path = tmp_path / "no_gcode.3mf"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("3D/3dmodel.model", b"<model/>")
    return path


def test_extract_gcode_returns_bytes(fake_3mf):
    ex = GcodeExtractor(fake_3mf)
    gcode = ex.extract_gcode()
    assert b"G28" in gcode


def test_extract_thumbnail_returns_bytes(fake_3mf):
    ex = GcodeExtractor(fake_3mf)
    thumb = ex.extract_thumbnail()
    assert thumb == b"FAKEPNG"


def test_extract_gcode_raises_when_missing(fake_3mf_no_gcode):
    ex = GcodeExtractor(fake_3mf_no_gcode)
    with pytest.raises(FileNotFoundError, match="No gcode found"):
        ex.extract_gcode()


def test_extract_thumbnail_returns_none_when_missing(fake_3mf_no_gcode):
    ex = GcodeExtractor(fake_3mf_no_gcode)
    assert ex.extract_thumbnail() is None


def test_list_contents(fake_3mf):
    ex = GcodeExtractor(fake_3mf)
    contents = ex.list_contents()
    assert "Metadata/plate_1.gcode" in contents
    assert "Metadata/thumbnail.png" in contents


def test_extract_gcode_to_file(fake_3mf, tmp_path):
    ex = GcodeExtractor(fake_3mf)
    out = tmp_path / "output.gcode"
    ex.extract_gcode_to_file(out)
    assert out.exists()
    assert b"G28" in out.read_bytes()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_gcode_extractor.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tools.gcode_extractor'`

- [ ] **Step 3: Write `tools/gcode_extractor.py`**

```python
import zipfile
from pathlib import Path
from typing import Optional


class GcodeExtractor:
    THUMBNAIL_PATHS = ["Metadata/thumbnail.png", "Thumbnails/thumbnail.png"]
    GCODE_EXTENSIONS = (".gcode",)

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def list_contents(self) -> list[str]:
        with zipfile.ZipFile(self.path) as zf:
            return zf.namelist()

    def extract_gcode(self) -> bytes:
        with zipfile.ZipFile(self.path) as zf:
            for name in zf.namelist():
                if any(name.endswith(ext) for ext in self.GCODE_EXTENSIONS):
                    return zf.read(name)
        raise FileNotFoundError(f"No gcode found in {self.path}")

    def extract_gcode_to_file(self, dest: str | Path) -> Path:
        dest = Path(dest)
        dest.write_bytes(self.extract_gcode())
        return dest

    def extract_thumbnail(self) -> Optional[bytes]:
        with zipfile.ZipFile(self.path) as zf:
            names = zf.namelist()
            for candidate in self.THUMBNAIL_PATHS:
                if candidate in names:
                    return zf.read(candidate)
        return None

    def gcode_path_in_archive(self) -> Optional[str]:
        with zipfile.ZipFile(self.path) as zf:
            for name in zf.namelist():
                if any(name.endswith(ext) for ext in self.GCODE_EXTENSIONS):
                    return name
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_gcode_extractor.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/gcode_extractor.py tests/test_gcode_extractor.py
git commit -m "feat: .3mf gcode + thumbnail extractor"
```

---

## Task 7: HA History Bootstrap

**Files:**
- Create: `tools/ha_history_bootstrap.py`
- Create: `tests/test_ha_history_bootstrap.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ha_history_bootstrap.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_ha_history_bootstrap.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tools.ha_history_bootstrap'`

- [ ] **Step 3: Write `tools/ha_history_bootstrap.py`**

```python
import statistics
from typing import Optional
from tools.ha_client import HAClient


class HAHistoryBootstrap:
    # Minimum °C to be considered "printing" (not idle/cooling)
    NOZZLE_PRINT_MIN_C = 150.0
    BED_PRINT_MIN_C = 45.0

    def __init__(self, ha_client: HAClient):
        self.ha = ha_client

    def run(self, start_date: str) -> dict:
        """
        Query HA history from start_date, extract print-time sensor values.
        Returns dict with bootstrapped parameter stats.
        """
        entity_ids = [
            HAClient.NOZZLE_TEMP_ENTITY,
            HAClient.BED_TEMP_ENTITY,
            HAClient.SPEED_ENTITY,
        ]
        history = self.ha.get_history(entity_ids, start_date + "T00:00:00")

        result = {
            "nozzle_temp": None,
            "bed_temp": None,
            "print_speed": None,
            "source": "ha_history",
            "start_date": start_date,
        }

        nozzle_c = []
        bed_c = []
        speed_mms = []

        for entity_data in history:
            if not entity_data:
                continue
            entity_id = entity_data[0].get("entity_id", "")

            for reading in entity_data:
                state = reading.get("state", "")
                try:
                    v = float(state)
                except (ValueError, TypeError):
                    continue

                if entity_id == HAClient.NOZZLE_TEMP_ENTITY:
                    c = HAClient.fahrenheit_to_celsius(v)
                    if c >= self.NOZZLE_PRINT_MIN_C:
                        nozzle_c.append(c)

                elif entity_id == HAClient.BED_TEMP_ENTITY:
                    c = HAClient.fahrenheit_to_celsius(v)
                    if c >= self.BED_PRINT_MIN_C:
                        bed_c.append(c)

                elif entity_id == HAClient.SPEED_ENTITY:
                    mms = HAClient.inches_per_sec_to_mms(v)
                    if mms > 5:
                        speed_mms.append(mms)

        if nozzle_c:
            result["nozzle_temp"] = {
                "median_c": statistics.median(nozzle_c),
                "mean_c": statistics.mean(nozzle_c),
                "min_c": min(nozzle_c),
                "max_c": max(nozzle_c),
                "sample_count": len(nozzle_c),
            }

        if bed_c:
            result["bed_temp"] = {
                "median_c": statistics.median(bed_c),
                "mean_c": statistics.mean(bed_c),
                "sample_count": len(bed_c),
            }

        if speed_mms:
            result["print_speed"] = {
                "median_mms": statistics.median(speed_mms),
                "max_mms": max(speed_mms),
                "sample_count": len(speed_mms),
            }

        return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_ha_history_bootstrap.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/ha_history_bootstrap.py tests/test_ha_history_bootstrap.py
git commit -m "feat: HA history bootstrap extracts print-time params from sensor history"
```

---

## Task 8: CLI Skeleton

**Files:**
- Create: `tune.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_cli.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tune'` or `cannot import name 'cli'`

- [ ] **Step 3: Write `tune.py`**

```python
import sys
from pathlib import Path
import click
from tools.config import get_config
from tools.ha_client import HAClient
from tools.calibration_db import CalibrationDB

DB_PATH = Path("calibration_db.json")


def build_ha_client() -> HAClient:
    config = get_config()
    return HAClient(
        urls=config["ha"]["urls"],
        token=config["ha"]["token"],
        verify_ssl=config["ha"]["verify_ssl"],
    )


@click.group()
def cli():
    """Tune3D — 3D printer calibration agent CLI."""
    pass


@cli.command()
def status():
    """Show printer and HA connection status."""
    client = build_ha_client()
    try:
        url = client.connect()
        click.echo(f"Connected to HA: {url}")
        status_val = client.get_print_status()
        nozzle = client.get_nozzle_temp_c()
        bed = client.get_bed_temp_c()
        printing = client.is_printing()
        click.echo(f"Printer status : {status_val}")
        click.echo(f"Nozzle temp    : {nozzle:.1f}°C")
        click.echo(f"Bed temp       : {bed:.1f}°C")
        click.echo(f"Printing       : {'yes' if printing else 'no'}")
    except ConnectionError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command(name="list-filaments")
def list_filaments():
    """List all filament × nozzle entries in the calibration database."""
    db = CalibrationDB(DB_PATH)
    filaments = db.list_filaments()
    if not filaments:
        click.echo("No filaments registered. Run: tune add-filament --filament <name> --nozzle <size>")
        return
    for key in filaments:
        entry = db._data[key]
        tier = entry.get("confidence_tier", 1)
        runs = len(entry.get("run_history", []))
        click.echo(f"  {key}  |  Tier {tier}  |  {runs} runs")


if __name__ == "__main__":
    cli()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_cli.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

```bash
pytest -v
```

Expected: All tests pass (total should be ~35+).

- [ ] **Step 6: Smoke-test the CLI against live HA**

```bash
python tune.py status
```

Expected output (approximate):
```
Connected to HA: https://192.168.1.191:8123
Printer status : completed
Nozzle temp    : 29.4°C
Bed temp       : 27.6°C
Printing       : no
```

```bash
python tune.py list-filaments
```

Expected: `No filaments registered. Run: tune add-filament ...`

- [ ] **Step 7: Commit**

```bash
git add tune.py tests/test_cli.py
git commit -m "feat: CLI skeleton with status and list-filaments commands"
```

---

## Final: Full Test Run + Plan 1 Tag

- [ ] **Step 1: Run all tests**

```bash
pytest -v --tb=short
```

Expected: All tests pass.

- [ ] **Step 2: Tag Plan 1 complete**

```bash
git tag plan1-foundation
git log --oneline -8
```

Expected output should show commits for: scaffolding, config, ha-client, orca-profiles, calibration-db, gcode-extractor, ha-history-bootstrap, cli.

---

## What's Next

- **Plan 2: Agents** — FilamentResearchAgent, VisionAgent, CalibrationAgent (all 3 tiers), ProfileAdvisorAgent, SpeedOptimizerAgent, Orchestrator, full CLI (`add-filament`, `calibrate`, `advise`, `speed`, `rollback`)
- **Plan 3: Dashboard + OrcaSlicerWatcher** — FastAPI server, SSE live updates, gcode-preview 3D viewer, OrcaSlicerWatcher via inotify, Live OrcaSlicer panel
