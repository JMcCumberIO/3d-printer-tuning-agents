# Dashboard + OrcaSlicerWatcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a FastAPI web dashboard with live HA state via SSE, 1fps camera relay (multi-viewer safe), OrcaSlicer file-watcher events, and a `tune serve` CLI command.

**Architecture:** A fully async FastAPI app (`server/`) with an SSEBroker fanout (one asyncio.Queue per connected client), a background HA poller, a multipart MJPEG camera relay, and a watchdog-based OrcaSlicerWatcher bridged into the asyncio event loop via `call_soon_threadsafe`. The dashboard is vanilla HTML/CSS/JS (no build toolchain), served as static files.

**Tech Stack:** FastAPI, uvicorn[standard], httpx (already used throughout), watchdog (already installed), pytest-asyncio (asyncio_mode=auto already configured), respx (already used for httpx mocking). All dependencies are already in `pyproject.toml` and the venv.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `tools/ha_client.py` | Modify | Add 4 graceful-degradation sensor methods + async snapshot |
| `server/__init__.py` | Create | Package init |
| `server/sse.py` | Create | SSEBroker: asyncio queue fanout |
| `server/ha_poller.py` | Create | Background asyncio.Task: polls HA every N seconds |
| `server/camera_relay.py` | Create | Async generator: HA snapshot to multipart MJPEG |
| `server/orca_watcher.py` | Create | Watchdog to asyncio bridge |
| `server/app.py` | Create | FastAPI app, routes, lifespan |
| `server/static/index.html` | Create | Dashboard shell (Option C layout) |
| `server/static/style.css` | Create | Responsive CSS Grid (desktop + mobile) |
| `server/static/app.js` | Create | SSE client, DOM updates, capture button |
| `tune.py` | Modify | Add `tune serve` command |
| `pyproject.toml` | Modify | Add `server*` to packages.find.include |
| `tests/test_ha_client.py` | Modify | Add 4 tests for new methods |
| `tests/test_sse.py` | Create | SSEBroker unit tests |
| `tests/test_ha_poller.py` | Create | Poller event shape + null handling |
| `tests/test_camera_relay.py` | Create | Frame format + error retry |
| `tests/test_orca_watcher.py` | Create | Event handler unit tests |
| `tests/test_server.py` | Create | Route tests via httpx.AsyncClient + ASGITransport |
| `tests/test_cli.py` | Modify | Add `tune serve` test |

---

## Task 1: HAClient — graceful-degradation sensor methods + async snapshot

**Context:** `tools/ha_client.py` already has typed accessors for existing sensors. The HA integration is missing `current_layer`, `total_layers`, `current_print_file`, and `print_speed_adjustment` sensors. We add methods for all four that return `None` when the entity is absent or in state `"unavailable"/"unknown"`. We also add `get_camera_snapshot_async()` — the async version used by the camera relay.

**Files:**
- Modify: `tools/ha_client.py`
- Modify: `tests/test_ha_client.py`

- [ ] **Step 1: Write four failing tests**

Append to `tests/test_ha_client.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/jonathan/projects/3d-printer-tuning-agents
source .venv/bin/activate
pytest tests/test_ha_client.py::test_get_current_layer_returns_none_when_entity_missing \
       tests/test_ha_client.py::test_get_current_layer_returns_int_when_sensor_available \
       tests/test_ha_client.py::test_get_camera_snapshot_async_returns_bytes -v
```
Expected: FAIL with `AttributeError: 'HAClient' object has no attribute 'get_current_layer'`

- [ ] **Step 3: Add entity constants and new methods to `tools/ha_client.py`**

After the existing entity constants block (after line `CAMERA_ENTITY = ...`), add:
```python
    LAYER_ENTITY = "sensor.flashforge_current_layer"
    TOTAL_LAYERS_ENTITY = "sensor.flashforge_total_layers"
    CURRENT_FILE_ENTITY = "sensor.flashforge_current_print_file"
    SPEED_PCT_ENTITY = "sensor.flashforge_print_speed_adjustment"
```

After `get_print_speed_mms`, add:
```python
    def _get_optional_state(self, entity_id: str) -> Optional[str]:
        """Return entity state string, or None if missing/unavailable/unknown."""
        try:
            state = self.get_state(entity_id)
            if state["state"] in ("unavailable", "unknown", ""):
                return None
            return state["state"]
        except Exception:
            return None

    def get_current_layer(self) -> Optional[int]:
        val = self._get_optional_state(self.LAYER_ENTITY)
        return int(float(val)) if val is not None else None

    def get_total_layers(self) -> Optional[int]:
        val = self._get_optional_state(self.TOTAL_LAYERS_ENTITY)
        return int(float(val)) if val is not None else None

    def get_current_file(self) -> Optional[str]:
        return self._get_optional_state(self.CURRENT_FILE_ENTITY)

    def get_speed_pct(self) -> Optional[int]:
        val = self._get_optional_state(self.SPEED_PCT_ENTITY)
        return int(float(val)) if val is not None else None

    async def get_camera_snapshot_async(
        self, entity_id: str = CAMERA_ENTITY
    ) -> bytes:
        """Async version of get_camera_snapshot() using httpx.AsyncClient."""
        async with httpx.AsyncClient(verify=self.verify_ssl) as client:
            r = await client.get(
                f"{self.base_url}/api/camera_proxy/{entity_id}",
                headers=self._headers,
                timeout=15.0,
            )
            r.raise_for_status()
            return r.content
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_ha_client.py -v
```
Expected: all 15 tests PASS (11 existing + 4 new)

- [ ] **Step 5: Commit**

```bash
git add tools/ha_client.py tests/test_ha_client.py
git commit -m "feat(ha_client): add graceful-degradation sensor methods and async snapshot"
```

---

## Task 2: SSEBroker

**Context:** The SSEBroker is a singleton that maintains a list of `asyncio.Queue` objects — one per connected SSE client. The HA poller and OrcaSlicerWatcher publish once; the broker fans out to every subscribed queue. Slow clients drop frames rather than blocking. The `asynccontextmanager` on `subscribe()` ensures queue cleanup on client disconnect.

**Files:**
- Create: `server/__init__.py`
- Create: `server/sse.py`
- Modify: `pyproject.toml` (add `server*` to packages.find.include)
- Create: `tests/test_sse.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_sse.py`:

```python
import asyncio
import pytest
from server.sse import SSEBroker


async def test_publish_delivers_event_to_subscriber():
    broker = SSEBroker()
    async with broker.subscribe() as q:
        await broker.publish({"type": "test"})
        event = q.get_nowait()
    assert event == {"type": "test"}


async def test_publish_delivers_to_all_subscribers():
    broker = SSEBroker()
    async with broker.subscribe() as q1:
        async with broker.subscribe() as q2:
            await broker.publish({"type": "multi"})
            assert q1.get_nowait() == {"type": "multi"}
            assert q2.get_nowait() == {"type": "multi"}


async def test_publish_drops_frame_when_queue_full():
    broker = SSEBroker()
    async with broker.subscribe() as q:
        for i in range(10):
            await broker.publish({"n": i})
        # 11th publish must not raise or block
        await broker.publish({"n": 10})
        assert q.qsize() == 10  # still 10; 11th was dropped


async def test_subscribe_cleanup_removes_queue_on_exit():
    broker = SSEBroker()
    async with broker.subscribe():
        assert broker.subscriber_count() == 1
    assert broker.subscriber_count() == 0


async def test_publish_with_no_subscribers_is_noop():
    broker = SSEBroker()
    await broker.publish({"type": "empty"})  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_sse.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'server'`

- [ ] **Step 3: Create `server/__init__.py` and `server/sse.py`**

Create `server/__init__.py` (empty file — just a newline):
```
```

Create `server/sse.py`:
```python
import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator


class SSEBroker:
    def __init__(self) -> None:
        self._queues: list[asyncio.Queue] = []

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue]:
        q: asyncio.Queue = asyncio.Queue(maxsize=10)
        self._queues.append(q)
        try:
            yield q
        finally:
            self._queues.remove(q)

    async def publish(self, event: dict) -> None:
        for q in self._queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # slow client — drop frame, never block

    def subscriber_count(self) -> int:
        return len(self._queues)
```

- [ ] **Step 4: Update `pyproject.toml`**

Change:
```toml
[tool.setuptools.packages.find]
include = ["tools*", "agents*", "dashboard*"]
```
to:
```toml
[tool.setuptools.packages.find]
include = ["tools*", "agents*", "dashboard*", "server*"]
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_sse.py -v
```
Expected: 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add server/__init__.py server/sse.py pyproject.toml tests/test_sse.py
git commit -m "feat(server): add SSEBroker asyncio queue fanout"
```

---

## Task 3: HA Poller

**Context:** `poll_ha()` is a long-running coroutine started as an `asyncio.Task` in the FastAPI lifespan. It calls existing synchronous HAClient methods and publishes a typed dict to the SSEBroker. The `_safe()` helper catches per-sensor exceptions and returns `None`, enabling graceful degradation without crashing the poll cycle.

**Files:**
- Create: `server/ha_poller.py`
- Create: `tests/test_ha_poller.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_ha_poller.py`:

```python
import asyncio
import pytest
from unittest.mock import MagicMock
from server.ha_poller import poll_ha
from server.sse import SSEBroker


async def _one_event(broker, client, interval=0):
    async with broker.subscribe() as q:
        task = asyncio.create_task(poll_ha(broker, client, interval=interval))
        try:
            return await asyncio.wait_for(q.get(), timeout=1.0)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


async def test_poll_publishes_ha_state_event():
    broker = SSEBroker()
    client = MagicMock()
    client.get_print_status.return_value = "printing"
    client.get_nozzle_temp_c.return_value = 225.0
    client.get_bed_temp_c.return_value = 60.0
    client.get_print_progress.return_value = 42.0
    client.get_current_layer.return_value = None
    client.get_total_layers.return_value = None
    client.get_current_file.return_value = None
    client.get_speed_pct.return_value = None

    event = await _one_event(broker, client)

    assert event["type"] == "ha_state"
    assert event["print_status"] == "printing"
    assert event["nozzle_temp"] == 225.0
    assert event["current_layer"] is None


async def test_poll_returns_none_for_sensor_that_raises():
    broker = SSEBroker()
    client = MagicMock()
    client.get_print_status.side_effect = Exception("timeout")
    client.get_nozzle_temp_c.return_value = 225.0
    client.get_bed_temp_c.return_value = 60.0
    client.get_print_progress.return_value = 0.0
    client.get_current_layer.return_value = None
    client.get_total_layers.return_value = None
    client.get_current_file.return_value = None
    client.get_speed_pct.return_value = None

    event = await _one_event(broker, client)

    assert event["print_status"] is None
    assert event["nozzle_temp"] == 225.0


async def test_poll_continues_after_full_cycle_exception():
    broker = SSEBroker()
    client = MagicMock()
    call_count = 0

    def status():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("HA offline")
        return "idle"

    client.get_print_status.side_effect = status
    for attr in (
        "get_nozzle_temp_c", "get_bed_temp_c", "get_print_progress",
        "get_current_layer", "get_total_layers", "get_current_file", "get_speed_pct",
    ):
        getattr(client, attr).return_value = None

    async with broker.subscribe() as q:
        task = asyncio.create_task(poll_ha(broker, client, interval=0))
        try:
            e1 = await asyncio.wait_for(q.get(), timeout=1.0)
            e2 = await asyncio.wait_for(q.get(), timeout=1.0)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    assert e1["print_status"] is None
    assert e2["print_status"] == "idle"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_ha_poller.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'server.ha_poller'`

- [ ] **Step 3: Create `server/ha_poller.py`**

```python
import asyncio
import logging
from tools.ha_client import HAClient
from server.sse import SSEBroker

logger = logging.getLogger(__name__)


def _safe(fn):
    """Call fn(), return None on any exception."""
    try:
        return fn()
    except Exception:
        return None


async def poll_ha(
    broker: SSEBroker,
    client: HAClient,
    interval: float = 1.0,
) -> None:
    """Background coroutine: poll HA every `interval` seconds, publish to broker."""
    while True:
        try:
            event = {
                "type": "ha_state",
                "print_status": _safe(client.get_print_status),
                "nozzle_temp": _safe(client.get_nozzle_temp_c),
                "bed_temp": _safe(client.get_bed_temp_c),
                "progress": _safe(client.get_print_progress),
                "current_layer": _safe(client.get_current_layer),
                "total_layers": _safe(client.get_total_layers),
                "current_file": _safe(client.get_current_file),
                "speed_pct": _safe(client.get_speed_pct),
            }
            await broker.publish(event)
        except Exception as e:
            logger.warning("HA poll cycle error: %s", e)
        await asyncio.sleep(interval)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_ha_poller.py -v
```
Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add server/ha_poller.py tests/test_ha_poller.py
git commit -m "feat(server): add async HA poller with graceful null handling"
```

---

## Task 4: Camera Relay

**Context:** `camera_frames()` is an async generator that polls HA's snapshot endpoint once per second and yields multipart MJPEG frames. All dashboard clients connect to the same `/stream/camera` route; the server makes exactly one HA call per tick regardless of viewer count. On error it skips the frame and retries next tick.

**Files:**
- Create: `server/camera_relay.py`
- Create: `tests/test_camera_relay.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_camera_relay.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from server.camera_relay import camera_frames


async def test_camera_frames_yields_multipart_mjpeg_frame():
    client = MagicMock()
    client.get_camera_snapshot_async = AsyncMock(return_value=b"FAKEJPEG")

    gen = camera_frames(client, interval=0)
    frame = await anext(gen)
    await gen.aclose()

    assert b"--frame" in frame
    assert b"Content-Type: image/jpeg" in frame
    assert b"FAKEJPEG" in frame


async def test_camera_frames_retries_after_snapshot_error():
    client = MagicMock()
    call_count = 0

    async def snapshot(_entity_id=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("camera offline")
        return b"RECOVERED"

    client.get_camera_snapshot_async = snapshot

    gen = camera_frames(client, interval=0)
    frame = await anext(gen)
    await gen.aclose()

    assert b"RECOVERED" in frame
    assert call_count == 2


async def test_camera_frames_yields_consecutive_frames():
    client = MagicMock()
    payloads = [b"FRAME_A", b"FRAME_B"]
    idx = 0

    async def snapshot(_entity_id=None):
        nonlocal idx
        data = payloads[idx % len(payloads)]
        idx += 1
        return data

    client.get_camera_snapshot_async = snapshot

    gen = camera_frames(client, interval=0)
    f1 = await anext(gen)
    f2 = await anext(gen)
    await gen.aclose()

    assert b"FRAME_A" in f1
    assert b"FRAME_B" in f2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_camera_relay.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'server.camera_relay'`

- [ ] **Step 3: Create `server/camera_relay.py`**

```python
import asyncio
from typing import AsyncIterator
from tools.ha_client import HAClient


async def camera_frames(
    client: HAClient,
    interval: float = 1.0,
) -> AsyncIterator[bytes]:
    """
    Async generator yielding multipart MJPEG frames.
    Polls HA camera snapshot once per `interval` seconds.
    On error, skips the frame and retries next tick.
    """
    while True:
        try:
            frame = await client.get_camera_snapshot_async()
        except Exception:
            await asyncio.sleep(interval)
            continue
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + frame
            + b"\r\n"
        )
        await asyncio.sleep(interval)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_camera_relay.py -v
```
Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add server/camera_relay.py tests/test_camera_relay.py
git commit -m "feat(server): add async camera relay (multipart MJPEG, single upstream connection)"
```

---

## Task 5: OrcaSlicerWatcher

**Context:** Watchdog is thread-based; FastAPI runs an asyncio event loop. `_OrcaEventHandler` bridges the two via `loop.call_soon_threadsafe(queue.put_nowait, payload)`. The handler emits `model_opened` on `last_opened` changes in `OrcaSlicer.conf`, and `slice_complete` on new `.gcode` file creation. `OrcaSlicerWatcher` wraps Observer lifecycle.

**Files:**
- Create: `server/orca_watcher.py`
- Create: `tests/test_orca_watcher.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_orca_watcher.py`:

```python
import asyncio
import pytest
from pathlib import Path
from watchdog.events import FileCreatedEvent, FileModifiedEvent
from server.orca_watcher import _OrcaEventHandler


async def test_model_opened_emitted_on_first_read(tmp_path):
    conf = tmp_path / "OrcaSlicer.conf"
    conf.write_text("last_opened = /path/to/model.3mf\n")
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    handler = _OrcaEventHandler(conf, loop, queue)

    handler._check_model_opened()

    event = queue.get_nowait()
    assert event["type"] == "orca_event"
    assert event["event"] == "model_opened"
    assert event["file"] == "/path/to/model.3mf"


async def test_model_opened_emitted_when_file_changes(tmp_path):
    conf = tmp_path / "OrcaSlicer.conf"
    conf.write_text("last_opened = /old/model.3mf\n")
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    handler = _OrcaEventHandler(conf, loop, queue)

    handler._check_model_opened()  # establishes baseline, emits /old/model.3mf
    queue.get_nowait()              # consume initial event

    conf.write_text("last_opened = /new/model.3mf\n")
    handler._check_model_opened()

    event = queue.get_nowait()
    assert event["event"] == "model_opened"
    assert event["file"] == "/new/model.3mf"


async def test_model_opened_not_emitted_when_last_opened_unchanged(tmp_path):
    conf = tmp_path / "OrcaSlicer.conf"
    conf.write_text("last_opened = /same/model.3mf\n")
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    handler = _OrcaEventHandler(conf, loop, queue)

    handler._check_model_opened()  # emits initial event
    queue.get_nowait()              # consume it

    handler._check_model_opened()  # same value — no event
    assert queue.empty()


async def test_slice_complete_emitted_on_gcode_creation(tmp_path):
    conf = tmp_path / "OrcaSlicer.conf"
    conf.write_text("")
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    handler = _OrcaEventHandler(conf, loop, queue)

    handler.on_created(FileCreatedEvent(str(tmp_path / "output.gcode")))

    event = queue.get_nowait()
    assert event["type"] == "orca_event"
    assert event["event"] == "slice_complete"
    assert "output.gcode" in event["file"]


async def test_non_gcode_file_creation_is_ignored(tmp_path):
    conf = tmp_path / "OrcaSlicer.conf"
    conf.write_text("")
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    handler = _OrcaEventHandler(conf, loop, queue)

    handler.on_created(FileCreatedEvent(str(tmp_path / "model.3mf")))
    assert queue.empty()


async def test_missing_conf_file_does_not_raise(tmp_path):
    conf = tmp_path / "nonexistent.conf"
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    handler = _OrcaEventHandler(conf, loop, queue)

    handler._check_model_opened()  # must not raise
    assert queue.empty()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_orca_watcher.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'server.orca_watcher'`

- [ ] **Step 3: Create `server/orca_watcher.py`**

```python
import asyncio
import logging
from pathlib import Path
from typing import Optional

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


class _OrcaEventHandler(FileSystemEventHandler):
    def __init__(
        self,
        conf_path: Path,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue,
    ) -> None:
        self._conf_path = conf_path.resolve()
        self._loop = loop
        self._queue = queue
        self._last_opened: Optional[str] = None

    def on_modified(self, event: FileSystemEvent) -> None:
        src = Path(str(event.src_path)).resolve()
        if src == self._conf_path:
            self._check_model_opened()
        elif Path(str(event.src_path)).suffix == ".gcode" and not event.is_directory:
            self._emit({"type": "orca_event", "event": "slice_complete",
                        "file": str(event.src_path)})

    def on_created(self, event: FileSystemEvent) -> None:
        if Path(str(event.src_path)).suffix == ".gcode" and not event.is_directory:
            self._emit({"type": "orca_event", "event": "slice_complete",
                        "file": str(event.src_path)})

    def _check_model_opened(self) -> None:
        try:
            text = self._conf_path.read_text(errors="replace")
            for line in text.splitlines():
                if line.strip().startswith("last_opened"):
                    value = line.split("=", 1)[-1].strip()
                    if value != self._last_opened:
                        self._last_opened = value
                        self._emit({"type": "orca_event", "event": "model_opened",
                                    "file": value})
                    break
        except OSError:
            pass

    def _emit(self, payload: dict) -> None:
        self._loop.call_soon_threadsafe(self._queue.put_nowait, payload)


class OrcaSlicerWatcher:
    def __init__(
        self,
        conf_path: str,
        watch_dir: str,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue,
    ) -> None:
        self._conf_path = Path(conf_path).expanduser()
        self._watch_dir = Path(watch_dir).expanduser()
        self._loop = loop
        self._queue = queue
        self._observer: Optional[Observer] = None

    def start(self) -> None:
        handler = _OrcaEventHandler(self._conf_path, self._loop, self._queue)
        self._observer = Observer()
        self._observer.schedule(handler, str(self._watch_dir), recursive=True)
        self._observer.start()
        logger.info("OrcaSlicerWatcher started on %s", self._watch_dir)

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_orca_watcher.py -v
```
Expected: 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add server/orca_watcher.py tests/test_orca_watcher.py
git commit -m "feat(server): add OrcaSlicerWatcher with asyncio bridge"
```

---

## Task 6: FastAPI App

**Context:** `server/app.py` wires everything together. The `lifespan` context manager starts the HA poller and OrcaSlicerWatcher as background tasks and cancels them on shutdown. Routes: `GET /` serves the static HTML, `/api/status` returns one-shot HA state, `/api/filament` returns calibration DB data for the active filament, `/stream/events` is SSE, `/stream/camera` is multipart MJPEG, `POST /api/capture` triggers VisionAgent. A minimal placeholder `server/static/index.html` is created here so tests pass — it is replaced by the real dashboard in Task 7.

**Files:**
- Create: `server/app.py`
- Create: `server/static/index.html` (placeholder)
- Create: `tests/test_server.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_server.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_server.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'server.app'`

- [ ] **Step 3: Create the placeholder `server/static/index.html`**

```bash
mkdir -p server/static
```

Create `server/static/index.html`:
```html
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>3D Tuner</title></head>
<body><p>Dashboard loading...</p></body>
</html>
```

- [ ] **Step 4: Create `server/app.py`**

```python
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import anthropic
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from agents.vision_agent import VisionAgent
from server.camera_relay import camera_frames
from server.ha_poller import poll_ha
from server.orca_watcher import OrcaSlicerWatcher
from server.sse import SSEBroker
from tools.calibration_db import CalibrationDB
from tools.config import get_config
from tools.ha_client import HAClient

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
DB_PATH = Path("calibration_db.json")

broker = SSEBroker()
_ha_client: HAClient | None = None
_poller_task: asyncio.Task | None = None
_orca_task: asyncio.Task | None = None
_orca_watcher: OrcaSlicerWatcher | None = None
_orca_queue: asyncio.Queue = asyncio.Queue()


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ha_client, _poller_task, _orca_task, _orca_watcher

    config = get_config()
    _ha_client = HAClient(
        urls=config["ha"]["urls"],
        token=config["ha"]["token"],
        verify_ssl=config["ha"]["verify_ssl"],
    )
    try:
        _ha_client.connect()
    except ConnectionError as e:
        logger.warning("HA not reachable at startup: %s", e)

    interval = config.get("dashboard", {}).get("ha_poll_interval_seconds", 1)
    _poller_task = asyncio.create_task(poll_ha(broker, _ha_client, interval=interval))

    orca_conf = config.get("orca", {}).get("conf_path", "~/.config/OrcaSlicer/OrcaSlicer.conf")
    orca_dir = str(Path(orca_conf).expanduser().parent)
    loop = asyncio.get_running_loop()
    _orca_watcher = OrcaSlicerWatcher(orca_conf, orca_dir, loop, _orca_queue)
    try:
        _orca_watcher.start()
    except Exception as e:
        logger.warning("OrcaSlicerWatcher failed to start: %s", e)

    async def _forward_orca():
        while True:
            evt = await _orca_queue.get()
            await broker.publish(evt)

    _orca_task = asyncio.create_task(_forward_orca())

    yield

    _poller_task.cancel()
    _orca_task.cancel()
    try:
        await asyncio.gather(_poller_task, _orca_task, return_exceptions=True)
    except Exception:
        pass
    if _orca_watcher:
        _orca_watcher.stop()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    return (STATIC_DIR / "index.html").read_text()


@app.get("/api/status")
async def api_status():
    if _ha_client is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    return {
        "print_status": _safe(_ha_client.get_print_status),
        "nozzle_temp": _safe(_ha_client.get_nozzle_temp_c),
        "bed_temp": _safe(_ha_client.get_bed_temp_c),
        "progress": _safe(_ha_client.get_print_progress),
        "current_layer": _safe(_ha_client.get_current_layer),
        "total_layers": _safe(_ha_client.get_total_layers),
        "current_file": _safe(_ha_client.get_current_file),
        "speed_pct": _safe(_ha_client.get_speed_pct),
    }


@app.get("/api/filament")
async def api_filament():
    config = get_config()
    filament = config.get("active_filament", "")
    nozzle = config.get("active_nozzle", "0.4mm")
    db = CalibrationDB(DB_PATH)
    key = CalibrationDB._key(filament, nozzle)
    entry = db._data.get(key, {})
    return {
        "filament": filament,
        "nozzle": nozzle,
        "tier": entry.get("confidence_tier", 0),
        "baseline": entry.get("baseline", {}),
        "research_baseline": entry.get("research_baseline"),
        "speed_pareto": entry.get("speed_pareto", []),
        "recent_runs": entry.get("run_history", [])[-5:],
    }


@app.get("/stream/events")
async def stream_events():
    async def generate():
        async with broker.subscribe() as q:
            while True:
                event = await q.get()
                yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/stream/camera")
async def stream_camera():
    if _ha_client is None:
        return JSONResponse({"error": "not connected"}, status_code=503)

    async def generate():
        async for frame in camera_frames(_ha_client):
            yield frame

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.post("/api/capture")
async def api_capture():
    if _ha_client is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    claude = anthropic.Anthropic()
    agent = VisionAgent(claude, _ha_client)
    scores = agent.score()
    return scores
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_server.py -v
```
Expected: 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add server/app.py server/static/index.html tests/test_server.py
git commit -m "feat(server): add FastAPI app with SSE, camera relay, and filament API"
```

---

## Task 7: Dashboard Static Files

**Context:** Replace the placeholder `index.html` with the full Option C layout. Layout: full-width status bar, OrcaSlicer banner (hidden until event), left column with camera feed + capture button + scores overlay, right column with baseline table + pareto chart, bottom row with print log + future 3D viewer slot. Responsive: collapses to single column at 768px. All user data inserted via `escHtml()` to prevent XSS.

**Files:**
- Modify: `server/static/index.html`
- Create: `server/static/style.css`
- Create: `server/static/app.js`

No automated tests — verify manually using the checklist at the end.

- [ ] **Step 1: Write `server/static/style.css`**

```css
:root {
  --bg: #0f1117;
  --surface: #1a1d26;
  --surface2: #242736;
  --border: #2e3347;
  --accent: #6c8ebf;
  --accent2: #4caf80;
  --text: #e2e4ed;
  --text2: #8b91a8;
  --warn: #e8a835;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); font-family: system-ui, -apple-system, sans-serif; font-size: 14px; }
.panel { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
#status-bar {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 16px; border-radius: 0;
  border-left: none; border-right: none; border-top: none; font-size: 13px;
}
#print-status { font-weight: 700; color: var(--accent2); text-transform: uppercase; }
.sep { color: var(--border); }
.temp-label { color: var(--text2); font-size: 11px; }
#progress-bar-wrap { flex: 1; height: 4px; background: var(--surface2); border-radius: 2px; min-width: 60px; }
#progress-bar { height: 100%; background: var(--accent2); border-radius: 2px; width: 0%; transition: width 0.5s; }
#orca-banner {
  background: #2a2a1a; border-color: #4a4820; color: var(--warn);
  font-size: 12px; border-radius: 0; border-left: none; border-right: none;
  padding: 6px 16px; display: flex; align-items: center; gap: 8px;
}
#orca-banner.hidden { display: none; }
.main-grid { display: grid; grid-template-columns: 1.2fr 1fr; gap: 12px; padding: 12px; }
.left-col { display: flex; flex-direction: column; gap: 12px; }
.right-col { display: flex; flex-direction: column; gap: 12px; }
.camera-panel { display: flex; flex-direction: column; gap: 8px; }
#camera-feed { width: 100%; border-radius: 4px; background: #000; display: block; }
.btn {
  background: var(--accent); color: #fff; border: none;
  border-radius: 4px; padding: 7px 14px; font-size: 13px;
  cursor: pointer; font-weight: 600;
}
.btn:hover { background: #5a7daf; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
#scores { margin-top: 6px; }
#scores.hidden { display: none; }
.score-row { display: flex; justify-content: space-between; padding: 3px 0; border-bottom: 1px solid var(--border); font-size: 12px; }
.score-row:last-child { border-bottom: none; }
.score-val { font-weight: 700; color: var(--accent2); }
.panel h2 { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text2); margin-bottom: 10px; }
.baseline-row { display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid var(--border); font-size: 13px; }
.baseline-row:last-child { border-bottom: none; }
.baseline-key { color: var(--text2); }
.baseline-val { font-weight: 600; }
.tier-badge { display: inline-block; background: var(--accent); color: #fff; border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: 700; margin-bottom: 8px; }
.pareto-row { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 12px; }
.pareto-bar-wrap { flex: 1; height: 6px; background: var(--surface2); border-radius: 3px; }
.pareto-bar { height: 100%; border-radius: 3px; background: var(--accent); }
.pareto-label { width: 72px; color: var(--text2); font-size: 11px; }
.log-row { padding: 4px 0; border-bottom: 1px solid var(--border); font-size: 12px; color: var(--text2); }
.log-row:last-child { border-bottom: none; }
.bottom-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 0 12px 12px; }
.future-panel { display: flex; align-items: center; justify-content: center; color: var(--text2); font-size: 12px; font-style: italic; border-style: dashed; }
@media (max-width: 768px) {
  .main-grid { grid-template-columns: 1fr; }
  .bottom-grid { grid-template-columns: 1fr; }
}
```

- [ ] **Step 2: Write `server/static/app.js`**

Note: `escHtml` is used for all user-supplied string values before insertion into the DOM.

```javascript
// Escape user data before inserting into the DOM.
function escHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function fmt(v, suffix) {
  return v != null ? escHtml(String(v)) + escHtml(suffix) : "&#x2014;";
}

// SSE connection
const es = new EventSource("/stream/events");
es.onmessage = (e) => {
  const data = JSON.parse(e.data);
  if (data.type === "ha_state")   updateStatus(data);
  if (data.type === "orca_event") handleOrcaEvent(data);
};
es.onerror = () => {
  document.getElementById("print-status").textContent = "disconnected";
};

function updateStatus(d) {
  document.getElementById("print-status").textContent = d.print_status ?? "\u2014";
  document.getElementById("nozzle-temp").textContent =
    d.nozzle_temp != null ? d.nozzle_temp.toFixed(1) + "\u00b0C" : "\u2014";
  document.getElementById("bed-temp").textContent =
    d.bed_temp != null ? d.bed_temp.toFixed(1) + "\u00b0C" : "\u2014";

  const pct = d.progress ?? 0;
  document.getElementById("progress-bar").style.width = pct + "%";
  document.getElementById("progress-pct").textContent =
    d.progress != null ? Math.round(d.progress) + "%" : "\u2014";

  const layerEl = document.getElementById("layer-info");
  layerEl.textContent = (d.current_layer != null && d.total_layers != null)
    ? "Layer " + d.current_layer + " / " + d.total_layers : "";

  document.getElementById("print-status").style.color =
    d.print_status === "printing" ? "var(--accent2)" : "var(--text2)";
}

function handleOrcaEvent(d) {
  const banner = document.getElementById("orca-banner");
  const fileEl = document.getElementById("orca-file");
  const base = (d.file || "").split("/").pop() || d.file || "\u2014";
  if (d.event === "model_opened") {
    fileEl.textContent = "Opened: " + base;
    banner.classList.remove("hidden");
  }
  if (d.event === "slice_complete") {
    fileEl.textContent = "Sliced: " + base;
    banner.classList.remove("hidden");
  }
}

// Capture + Analyze button
document.getElementById("capture-btn").addEventListener("click", async () => {
  const btn = document.getElementById("capture-btn");
  const scoresEl = document.getElementById("scores");
  btn.disabled = true;
  btn.textContent = "Analyzing\u2026";
  scoresEl.classList.add("hidden");

  // Remove existing child nodes safely
  while (scoresEl.firstChild) { scoresEl.removeChild(scoresEl.firstChild); }

  try {
    const resp = await fetch("/api/capture", { method: "POST" });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const data = await resp.json();
    ["stringing", "layer_adhesion", "warping", "surface_finish", "overall"].forEach((k) => {
      const row = document.createElement("div");
      row.className = "score-row";

      const labelSpan = document.createElement("span");
      labelSpan.textContent = k.replace(/_/g, " ");

      const valSpan = document.createElement("span");
      valSpan.className = "score-val";
      valSpan.textContent = data[k] != null
        ? Math.round(data[k] * 100) + "%" : "\u2014";

      row.appendChild(labelSpan);
      row.appendChild(valSpan);
      scoresEl.appendChild(row);
    });
    scoresEl.classList.remove("hidden");
  } catch (err) {
    const errSpan = document.createElement("span");
    errSpan.style.color = "var(--warn)";
    errSpan.textContent = "Error: " + err.message;
    scoresEl.appendChild(errSpan);
    scoresEl.classList.remove("hidden");
  } finally {
    btn.disabled = false;
    btn.textContent = "Capture + Analyze";
  }
});

// Load filament data on page load
async function loadFilament() {
  try {
    const resp = await fetch("/api/filament");
    if (!resp.ok) return;
    const d = await resp.json();
    document.getElementById("filament-name").textContent =
      (d.filament || "\u2014") + " \u00b7 " + (d.nozzle || "");
    renderBaseline(d);
    renderPareto(d.speed_pareto || []);
    renderLog(d.recent_runs || []);
  } catch (_) {}
}

function renderBaseline(d) {
  const el = document.getElementById("baseline-content");
  const bl = d.baseline || {};
  const rb = (d.research_baseline) || {};

  // Clear children
  while (el.firstChild) { el.removeChild(el.firstChild); }

  const badge = document.createElement("div");
  badge.className = "tier-badge";
  badge.textContent = "Tier " + (d.tier != null ? d.tier : "\u2014");
  el.appendChild(badge);

  ["nozzle_temp", "bed_temp", "flow_rate", "max_speed", "cooling_fan"].forEach((p) => {
    const v = bl[p] ?? rb[p]?.recommended ?? null;
    const row = document.createElement("div");
    row.className = "baseline-row";

    const key = document.createElement("span");
    key.className = "baseline-key";
    key.textContent = p.replace(/_/g, " ");

    const val = document.createElement("span");
    val.className = "baseline-val";
    val.textContent = v != null ? String(v) : "\u2014";

    row.appendChild(key);
    row.appendChild(val);
    el.appendChild(row);
  });
}

function renderPareto(points) {
  const el = document.getElementById("pareto-content");
  while (el.firstChild) { el.removeChild(el.firstChild); }

  if (!points.length) {
    const msg = document.createElement("span");
    msg.style.cssText = "color:var(--text2);font-size:12px";
    msg.textContent = "No speed data yet";
    el.appendChild(msg);
    return;
  }

  const maxQ = Math.max(...points.map((p) => p.quality_score || 0)) || 1;
  points.slice(-8).forEach((p) => {
    const pct = ((p.quality_score / maxQ) * 100).toFixed(0);

    const row = document.createElement("div");
    row.className = "pareto-row";

    const label = document.createElement("span");
    label.className = "pareto-label";
    label.textContent = (p.speed || 0) + " mm/s";

    const barWrap = document.createElement("div");
    barWrap.className = "pareto-bar-wrap";
    const bar = document.createElement("div");
    bar.className = "pareto-bar";
    bar.style.width = pct + "%";
    barWrap.appendChild(bar);

    const scoreSpan = document.createElement("span");
    scoreSpan.textContent = Math.round((p.quality_score || 0) * 100) + "%";

    row.appendChild(label);
    row.appendChild(barWrap);
    row.appendChild(scoreSpan);
    el.appendChild(row);
  });
}

function renderLog(runs) {
  const el = document.getElementById("log-content");
  while (el.firstChild) { el.removeChild(el.firstChild); }

  if (!runs.length) {
    const msg = document.createElement("span");
    msg.style.cssText = "color:var(--text2);font-size:12px";
    msg.textContent = "No runs yet";
    el.appendChild(msg);
    return;
  }

  runs.slice(-5).reverse().forEach((r) => {
    const ts = r.timestamp ? r.timestamp.slice(0, 16).replace("T", " ") : "\u2014";
    const row = document.createElement("div");
    row.className = "log-row";
    row.textContent = ts + " \u00b7 " + (r.param || "\u2014") + " = " + (r.value ?? "\u2014");
    el.appendChild(row);
  });
}

loadFilament();
```

- [ ] **Step 3: Write `server/static/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>3D Tuner Dashboard</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>

  <div id="status-bar" class="panel">
    <span id="print-status">&#x2014;</span>
    <span class="sep">&middot;</span>
    <span class="temp-label">nozzle</span>
    <span id="nozzle-temp">&#x2014;</span>
    <span class="sep">&middot;</span>
    <span class="temp-label">bed</span>
    <span id="bed-temp">&#x2014;</span>
    <span class="sep">&middot;</span>
    <div id="progress-bar-wrap"><div id="progress-bar"></div></div>
    <span id="progress-pct">&#x2014;</span>
    <span id="layer-info" style="color:var(--text2);font-size:12px"></span>
  </div>

  <div id="orca-banner" class="panel hidden">
    <span style="font-size:10px;text-transform:uppercase;letter-spacing:0.06em">OrcaSlicer</span>
    <span id="orca-file">&#x2014;</span>
  </div>

  <div class="main-grid">
    <div class="left-col">
      <div class="panel camera-panel">
        <img id="camera-feed" src="/stream/camera" alt="Camera feed">
        <button id="capture-btn" class="btn">Capture + Analyze</button>
        <div id="scores" class="hidden"></div>
      </div>
    </div>
    <div class="right-col">
      <div class="panel baseline-panel">
        <h2>Baseline &mdash; <span id="filament-name" style="text-transform:none;font-weight:400">loading&hellip;</span></h2>
        <div id="baseline-content">&#x2014;</div>
      </div>
      <div class="panel pareto-panel">
        <h2>Speed vs Quality</h2>
        <div id="pareto-content">&#x2014;</div>
      </div>
    </div>
  </div>

  <div class="bottom-grid">
    <div class="panel log-panel">
      <h2>Print Log</h2>
      <div id="log-content">&#x2014;</div>
    </div>
    <div class="panel future-panel">3D Viewer &mdash; Plan 3B</div>
  </div>

  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 4: Verify server tests still pass**

```bash
pytest tests/test_server.py -v
```
Expected: all 4 tests PASS

- [ ] **Step 5: Manual verification checklist**

Start the server (requires HA to be reachable or will show dashes):
```bash
source .venv/bin/activate
tune serve --port 8765
```

Open `http://localhost:8765` and verify:
- [ ] Option C layout: status bar top, camera left, baseline+pareto right, log+future bottom
- [ ] Resize to 375px wide — layout collapses to single column (status bar → orca banner → camera → baseline → pareto → log)
- [ ] Status bar shows `—` for all values when HA is unreachable — no JS error in console
- [ ] OrcaSlicer banner is hidden at startup

- [ ] **Step 6: Commit**

```bash
git add server/static/index.html server/static/style.css server/static/app.js
git commit -m "feat(dashboard): add Option C responsive dashboard (HTML/CSS/JS)"
```

---

## Task 8: CLI `tune serve`

**Context:** Adds `tune serve` to `tune.py`. Foreground (default): uvicorn runs in-process, Ctrl+C to stop. `--daemon`: forks via subprocess, writes PID to `~/.local/share/3d-tuner/server.pid`. `--stop`: reads PID file and sends SIGTERM.

**Files:**
- Modify: `tune.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_cli.py`:

```python
def test_serve_foreground_starts_uvicorn(runner):
    with patch("tune.uvicorn") as mock_uvicorn:
        mock_uvicorn.run.return_value = None
        result = runner.invoke(cli, ["serve", "--port", "9999"])
    assert result.exit_code == 0
    mock_uvicorn.run.assert_called_once()
    kwargs = mock_uvicorn.run.call_args
    # port may be positional arg[1] or keyword arg
    port_used = kwargs.kwargs.get("port") or (kwargs.args[1] if len(kwargs.args) > 1 else None)
    assert port_used == 9999
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_cli.py::test_serve_foreground_starts_uvicorn -v
```
Expected: FAIL with `Error: No such command 'serve'`

- [ ] **Step 3: Add imports and `serve` command to `tune.py`**

Add at the top of `tune.py` after the existing imports:
```python
import os
import signal
import subprocess

import uvicorn
```

Add the following just before `if __name__ == "__main__":` at the bottom of `tune.py`:

```python
_PID_DIR = Path.home() / ".local" / "share" / "3d-tuner"
_PID_FILE = _PID_DIR / "server.pid"


@cli.command()
@click.option("--port", default=8765, show_default=True, help="Port to listen on")
@click.option("--daemon", is_flag=True, default=False, help="Run in background")
@click.option("--stop", is_flag=True, default=False, help="Stop a running daemon")
def serve(port: int, daemon: bool, stop: bool):
    """Start (or stop) the dashboard server."""
    if stop:
        if not _PID_FILE.exists():
            click.echo("No running server found (no PID file).", err=True)
            sys.exit(1)
        pid = int(_PID_FILE.read_text().strip())
        try:
            os.kill(pid, signal.SIGTERM)
            _PID_FILE.unlink(missing_ok=True)
            click.echo(f"Stopped server (PID {pid})")
        except ProcessLookupError:
            click.echo(f"Process {pid} not found — stale PID file removed.")
            _PID_FILE.unlink(missing_ok=True)
            sys.exit(1)
        return

    if daemon:
        _PID_DIR.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server.app:app",
             "--host", "0.0.0.0", "--port", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _PID_FILE.write_text(str(proc.pid))
        click.echo(f"Dashboard running at http://localhost:{port}  (PID {proc.pid})")
        click.echo("Stop with: tune serve --stop")
        return

    click.echo(f"Dashboard at http://localhost:{port}  (Ctrl+C to stop)")
    uvicorn.run("server.app:app", host="0.0.0.0", port=port, reload=False)
```

- [ ] **Step 4: Run all CLI tests**

```bash
pytest tests/test_cli.py -v
```
Expected: all 8 tests PASS (7 existing + 1 new)

- [ ] **Step 5: Run full test suite**

```bash
pytest -v
```
Expected: all tests PASS (90 existing + 25 new = ~115 total)

- [ ] **Step 6: Commit and tag**

```bash
git add tune.py tests/test_cli.py
git commit -m "feat(cli): add tune serve command (foreground + daemon + stop)"
git tag plan3a-dashboard
```

---

## Post-Plan Manual Checklist

After all 8 tasks complete, verify end-to-end:

- [ ] `tune serve` starts, dashboard opens at `http://localhost:8765`
- [ ] Open two browser tabs — both show camera feed without conflict
- [ ] HA status bar updates live via SSE
- [ ] Disconnect HA — all values show `—`, no JS errors in console
- [ ] Reconnect HA — values restore within the poll interval
- [ ] Open a model in OrcaSlicer — banner appears within 1-2 seconds
- [ ] Slice a model — banner updates to show the gcode filename
- [ ] Dashboard collapses to single column at 375px wide
- [ ] `tune serve --daemon --port 8765` detaches; `tune serve --stop` kills it
