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


def _get_ha_client() -> HAClient | None:
    """Return existing HA client or lazily create one from config."""
    global _ha_client
    if _ha_client is not None:
        return _ha_client
    try:
        config = get_config()
        client = HAClient(
            urls=config["ha"]["urls"],
            token=config["ha"]["token"],
            verify_ssl=config["ha"]["verify_ssl"],
        )
        try:
            client.connect()
        except ConnectionError as e:
            logger.warning("HA not reachable: %s", e)
        _ha_client = client
        return _ha_client
    except Exception as e:
        logger.warning("Could not create HAClient: %s", e)
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ha_client, _poller_task, _orca_task, _orca_watcher

    _ha_client = _get_ha_client()

    interval = 1
    try:
        config = get_config()
        interval = config.get("dashboard", {}).get("ha_poll_interval_seconds", 1)
    except Exception:
        pass

    if _ha_client is not None:
        _poller_task = asyncio.create_task(poll_ha(broker, _ha_client, interval=interval))

    try:
        config = get_config()
        orca_conf = config.get("orca", {}).get("conf_path", "~/.config/OrcaSlicer/OrcaSlicer.conf")
        orca_dir = str(Path(orca_conf).expanduser().parent)
        loop = asyncio.get_running_loop()
        _orca_watcher = OrcaSlicerWatcher(orca_conf, orca_dir, loop, _orca_queue)
        try:
            _orca_watcher.start()
        except Exception as e:
            logger.warning("OrcaSlicerWatcher failed to start: %s", e)
    except Exception as e:
        logger.warning("Could not set up OrcaSlicerWatcher: %s", e)

    async def _forward_orca():
        while True:
            evt = await _orca_queue.get()
            await broker.publish(evt)

    _orca_task = asyncio.create_task(_forward_orca())

    yield

    if _poller_task:
        _poller_task.cancel()
    _orca_task.cancel()
    try:
        tasks = [t for t in [_poller_task, _orca_task] if t is not None]
        await asyncio.gather(*tasks, return_exceptions=True)
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
    ha = _get_ha_client()
    if ha is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    return {
        "print_status": _safe(ha.get_print_status),
        "nozzle_temp": _safe(ha.get_nozzle_temp_c),
        "bed_temp": _safe(ha.get_bed_temp_c),
        "progress": _safe(ha.get_print_progress),
        "current_layer": _safe(ha.get_current_layer),
        "total_layers": _safe(ha.get_total_layers),
        "current_file": _safe(ha.get_current_file),
        "speed_pct": _safe(ha.get_speed_pct),
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
    ha = _get_ha_client()
    if ha is None:
        return JSONResponse({"error": "not connected"}, status_code=503)

    async def generate():
        async for frame in camera_frames(ha):
            yield frame

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.post("/api/capture")
async def api_capture():
    ha = _get_ha_client()
    if ha is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    claude = anthropic.Anthropic()
    agent = VisionAgent(claude, ha)
    scores = agent.score()
    return scores
