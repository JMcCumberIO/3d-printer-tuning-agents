# Dashboard + OrcaSlicerWatcher Design Spec (Plan 3A)

## Scope

Plan 3A covers three of five originally scoped items:

- **A** — FastAPI server + static dashboard shell
- **B** — OrcaSlicerWatcher (inotify/watchdog monitoring OrcaSlicer config)
- **C** — SSE live updates (HA state → asyncio queue fanout → dashboard)

Deferred to Plan 3B:
- **D** — gcode-preview 3D viewer panel
- **E** — pending approvals queue

---

## Architecture

Three new modules live under `server/`, alongside existing `agents/` and `tools/`:

```
server/
  __init__.py
  app.py            — FastAPI app, routes, lifespan context manager
  sse.py            — SSEBroker: asyncio queue fanout (one queue per connected client)
  ha_poller.py      — background asyncio.Task: polls HA every 1s, publishes to broker
  camera_relay.py   — async generator: polls HA camera_proxy snapshot, serves multipart MJPEG
  orca_watcher.py   — watchdog FileSystemEventHandler → asyncio bridge → broker
  static/
    index.html      — dashboard shell (Option C layout)
    style.css       — responsive CSS (grid desktop, single column ≤768px)
    app.js          — SSE client, DOM updates, camera <img> src, capture button
```

**Stack:** FastAPI + uvicorn[standard], httpx (async HA calls), watchdog (filesystem events). No frontend build toolchain — vanilla HTML/CSS/JS only.

---

## Routes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Serve `index.html` |
| GET | `/stream/events` | SSE — HA state + OrcaSlicer events |
| GET | `/stream/camera` | Multipart MJPEG — 1fps camera relay |
| GET | `/api/status` | One-shot HA snapshot for initial page load |
| POST | `/api/capture` | Trigger VisionAgent snapshot + analysis |

---

## SSE Broker (`server/sse.py`)

Singleton shared across all routes. Each client subscribes and gets its own `asyncio.Queue`. The poller publishes once; every queue gets a copy. Slow clients drop frames (queue full) rather than blocking the poller.

```python
class SSEBroker:
    def __init__(self):
        self._queues: list[asyncio.Queue] = []

    @asynccontextmanager  # from contextlib — not @contextmanager
    async def subscribe(self):
        q = asyncio.Queue(maxsize=10)
        self._queues.append(q)
        try:
            yield q
        finally:
            self._queues.remove(q)

    async def publish(self, event: dict):
        for q in self._queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # slow client — drop frame, never block
```

---

## HA Poller (`server/ha_poller.py`)

Long-lived `asyncio.Task` started in the FastAPI lifespan. Calls existing `HAClient` methods every second and publishes a typed event dict. New `HAClient` methods are added for currently-missing sensors (`current_layer`, `total_layers`, `current_file`, `speed_pct`) — each catches 404 / `"unavailable"` state and returns `None`.

**Event shape:**
```json
{
  "type": "ha_state",
  "print_status": "printing",
  "nozzle_temp": 225.0,
  "bed_temp": 60.0,
  "progress": 42,
  "current_layer": null,
  "total_layers": null,
  "current_file": null,
  "speed_pct": null
}
```

`null` values mean the sensor is missing or unavailable. When the HA integration fix lands and a sensor starts reporting, the poller picks it up on the next tick automatically — no restart or code change needed.

---

## Camera Relay (`server/camera_relay.py`)

Async generator polling HA's `/api/camera_proxy/{entity}` (single-frame snapshot) once per second and serving it as a multipart MJPEG response. All dashboard clients — including multiple browser tabs — connect to `/stream/camera`; the server makes exactly one HA request per second regardless of viewer count.

**Note:** Plan 3 adds `get_camera_snapshot_async()` to `HAClient` — an async wrapper around the existing sync `get_camera_snapshot()` using `httpx.AsyncClient`.

```python
async def camera_frames(ha_client: HAClient):
    while True:
        frame = await ha_client.get_camera_snapshot_async()
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
        await asyncio.sleep(1.0)
```

The dashboard camera panel uses a plain `<img src="/stream/camera">` — browsers handle multipart MJPEG natively.

---

## OrcaSlicerWatcher (`server/orca_watcher.py`)

Uses `watchdog` to monitor two paths (configurable via `config.yaml`, defaulting to `~/.config/OrcaSlicer`):

1. **`OrcaSlicer.conf`** — on every write, reads file and compares `last_opened` field to previous value. If changed → publishes `model_opened` event.
2. **`user/default/` directory** — watches for new `.gcode` files. New file → publishes `slice_complete` event.

**Asyncio bridge** (watchdog runs in a thread; FastAPI lives in an asyncio event loop):
```python
def on_modified(self, event):
    payload = self._build_payload(event)
    self._loop.call_soon_threadsafe(self._queue.put_nowait, payload)
```

**OrcaSlicer event shape:**
```json
{ "type": "orca_event", "event": "model_opened", "file": "/path/to/model.3mf" }
{ "type": "orca_event", "event": "slice_complete", "file": "/path/to/output.gcode" }
```

Both event types flow through the same SSEBroker so the dashboard receives a unified event stream.

---

## Dashboard Layout (`server/static/`)

**Option C — camera-first, mobile-responsive.**

### Desktop (≥768px) — CSS Grid:
```
┌─────────────────────────────────────────┐
│ STATUS BAR — temps · state · progress   │  full width
├────────────────────┬────────────────────┤
│ ORCA BANNER        │                    │
│ (when printing)    │  BASELINE TABLE    │
├────────────────────┤  params · tier     │
│ CAMERA FEED        ├────────────────────┤
│  1fps relay        │  PARETO CHART      │
│  [Capture+Analyze] │  speed vs quality  │
├────────────────────┴────────────────────┤
│ PRINT LOG (last 5) │ FUTURE: 3D VIEWER  │
└────────────────────┴────────────────────┘
```

### Mobile (<768px) — single column, in order:
1. Status bar
2. Orca banner (hidden when not printing)
3. Camera feed
4. Baseline table
5. Pareto chart
6. Print log

**SSE client (`app.js`):**
```javascript
const es = new EventSource("/stream/events");
es.onmessage = (e) => {
  const data = JSON.parse(e.data);
  if (data.type === "ha_state")   updateStatus(data);
  if (data.type === "orca_event") handleOrcaEvent(data);
};
```

Missing / null sensor values render as `—`. The `[Capture + Analyze]` button POSTs to `/api/capture` and shows the VisionAgent score overlay on the camera panel when the response returns.

---

## CLI Integration

New command added to `tune.py`:

```python
@cli.command()
@click.option("--port", default=8765, show_default=True)
@click.option("--daemon", is_flag=True, default=False)
@click.option("--stop", is_flag=True, default=False)
def serve(port, daemon, stop):
    """Start (or stop) the dashboard server."""
    ...
```

- **Foreground (default):** logs stream to terminal, Ctrl+C to stop.
- **`--daemon`:** detaches, writes PID to `~/.local/share/3d-tuner/server.pid`, prints the URL, returns to shell.
- **`--stop`:** reads PID file and kills the process.

---

## Testing

| File | Coverage |
|------|----------|
| `tests/test_sse.py` | SSEBroker: subscribe, publish, drop on full queue, cleanup on disconnect |
| `tests/test_ha_poller.py` | Mock HAClient → verify event dict shape, null handling for missing sensors |
| `tests/test_orca_watcher.py` | Inject mock filesystem events → verify asyncio queue receives correct payloads |
| `tests/test_server.py` | `httpx.AsyncClient` + `pytest-asyncio`: GET `/api/status`, GET `/stream/events` (read 1 event), POST `/api/capture` |
| `tests/test_camera_relay.py` | Mock HAClient snapshot → verify multipart MJPEG frame format |

**Manual test checklist:**
- [ ] Open dashboard in two browser tabs simultaneously — camera relay serves both without conflict
- [ ] Disconnect HA — all sensors show `—`, page does not crash
- [ ] Reconnect HA — values restore within 2 seconds
- [ ] Open a model in OrcaSlicer — Orca banner updates
- [ ] Slice a model — slice_complete event appears in browser console
- [ ] Resize browser to 375px wide — layout collapses to single column correctly
- [ ] `tune serve --daemon` — process detaches, PID file written, `tune serve --stop` kills it

---

## Dependencies Added

```
fastapi
uvicorn[standard]
httpx
watchdog
pytest-asyncio
```
