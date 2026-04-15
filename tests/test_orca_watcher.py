import asyncio
import json
import zipfile
import pytest
from pathlib import Path
from watchdog.events import FileCreatedEvent, FileModifiedEvent
from server.orca_watcher import _OrcaEventHandler, _model_name_from_tmp_3mf


def _orca_conf(path: Path, recent_project: str = "") -> None:
    """Write a minimal OrcaSlicer.conf JSON with the given recent_projects[01] value."""
    data: dict = {}
    if recent_project:
        data["recent_projects"] = {"01": recent_project}
    path.write_text(json.dumps(data))


def _tmp_3mf(path: Path, model_name: str) -> None:
    """Write a minimal OrcaSlicer temp .3mf zip with the given model name."""
    model_settings = f"""<?xml version="1.0" encoding="UTF-8"?>
<config>
  <object id="1">
    <metadata key="name" value="{model_name}"/>
  </object>
</config>"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Metadata/model_settings.config", model_settings)


# ── conf-file (saved projects) tests ────────────────────────────────────────

async def test_model_opened_emitted_on_first_read(tmp_path):
    conf = tmp_path / "OrcaSlicer.conf"
    _orca_conf(conf, "/path/to/model.3mf")
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    handler = _OrcaEventHandler(conf, loop, queue)

    handler._check_model_opened()
    await asyncio.sleep(0)  # yield so call_soon_threadsafe callback fires

    event = queue.get_nowait()
    assert event["type"] == "orca_event"
    assert event["event"] == "model_opened"
    assert event["file"] == "/path/to/model.3mf"


async def test_model_opened_emitted_when_file_changes(tmp_path):
    conf = tmp_path / "OrcaSlicer.conf"
    _orca_conf(conf, "/old/model.3mf")
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    handler = _OrcaEventHandler(conf, loop, queue)

    handler._check_model_opened()  # establishes baseline, emits /old/model.3mf
    await asyncio.sleep(0)
    queue.get_nowait()              # consume initial event

    _orca_conf(conf, "/new/model.3mf")
    handler._check_model_opened()
    await asyncio.sleep(0)

    event = queue.get_nowait()
    assert event["event"] == "model_opened"
    assert event["file"] == "/new/model.3mf"


async def test_model_opened_not_emitted_when_last_opened_unchanged(tmp_path):
    conf = tmp_path / "OrcaSlicer.conf"
    _orca_conf(conf, "/same/model.3mf")
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    handler = _OrcaEventHandler(conf, loop, queue)

    handler._check_model_opened()  # emits initial event
    await asyncio.sleep(0)
    queue.get_nowait()              # consume it

    handler._check_model_opened()  # same value — no event
    await asyncio.sleep(0)
    assert queue.empty()


async def test_missing_conf_file_does_not_raise(tmp_path):
    conf = tmp_path / "nonexistent.conf"
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    handler = _OrcaEventHandler(conf, loop, queue)

    handler._check_model_opened()  # must not raise
    assert queue.empty()


async def test_invalid_json_conf_does_not_raise(tmp_path):
    conf = tmp_path / "OrcaSlicer.conf"
    conf.write_text("this is not json {{{")
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    handler = _OrcaEventHandler(conf, loop, queue)

    handler._check_model_opened()  # must not raise
    assert queue.empty()


async def test_conf_without_recent_projects_does_not_emit(tmp_path):
    conf = tmp_path / "OrcaSlicer.conf"
    _orca_conf(conf)  # no recent_project arg → no recent_projects key
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    handler = _OrcaEventHandler(conf, loop, queue)

    handler._check_model_opened()
    assert queue.empty()


async def test_always_emit_fires_on_startup_even_if_unchanged(tmp_path):
    conf = tmp_path / "OrcaSlicer.conf"
    _orca_conf(conf, "/startup/model.3mf")
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    handler = _OrcaEventHandler(conf, loop, queue)

    handler._check_model_opened(always_emit=True)
    await asyncio.sleep(0)
    event = queue.get_nowait()
    assert event["event"] == "model_opened"
    assert event["file"] == "/startup/model.3mf"

    # calling again without always_emit should NOT re-emit (same value)
    handler._check_model_opened()
    await asyncio.sleep(0)
    assert queue.empty()


# ── tmp session (.3mf zip) tests ─────────────────────────────────────────────

def test_model_name_from_tmp_3mf_extracts_name(tmp_path):
    p = tmp_path / ".3mf"
    _tmp_3mf(p, "3DBenchy.stl")
    assert _model_name_from_tmp_3mf(p) == "3DBenchy.stl"


def test_model_name_from_tmp_3mf_returns_none_for_missing_file(tmp_path):
    assert _model_name_from_tmp_3mf(tmp_path / "no_such.3mf") is None


def test_model_name_from_tmp_3mf_returns_none_for_corrupt_zip(tmp_path):
    p = tmp_path / ".3mf"
    p.write_bytes(b"not a zip")
    assert _model_name_from_tmp_3mf(p) is None


async def test_on_created_tmp_3mf_emits_model_opened(tmp_path):
    conf = tmp_path / "OrcaSlicer.conf"
    _orca_conf(conf)
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    tmp_3mf = session_dir / ".3mf"
    _tmp_3mf(tmp_3mf, "3DBenchy.stl")

    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    handler = _OrcaEventHandler(conf, loop, queue)

    handler.on_created(FileCreatedEvent(str(tmp_3mf)))
    await asyncio.sleep(0)

    event = queue.get_nowait()
    assert event["type"] == "orca_event"
    assert event["event"] == "model_opened"
    assert event["file"] == "3DBenchy.stl"


async def test_scan_existing_tmp_session_detects_live_model(tmp_path):
    conf = tmp_path / "OrcaSlicer.conf"
    _orca_conf(conf)
    tmp_dir = tmp_path / "orcaslicer_model"
    session = tmp_dir / "Wed_Apr_15" / "00_13_18#1234#50"
    session.mkdir(parents=True)
    _tmp_3mf(session / ".3mf", "3DBenchy.stl")

    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    handler = _OrcaEventHandler(conf, loop, queue, tmp_dir=tmp_dir)

    handler.scan_existing_tmp_session()
    await asyncio.sleep(0)

    event = queue.get_nowait()
    assert event["event"] == "model_opened"
    assert event["file"] == "3DBenchy.stl"


async def test_scan_existing_tmp_session_falls_back_to_conf(tmp_path):
    conf = tmp_path / "OrcaSlicer.conf"
    _orca_conf(conf, "/saved/model.3mf")
    empty_tmp = tmp_path / "empty_tmp"
    empty_tmp.mkdir()

    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    handler = _OrcaEventHandler(conf, loop, queue, tmp_dir=empty_tmp)

    handler.scan_existing_tmp_session()
    await asyncio.sleep(0)

    event = queue.get_nowait()
    assert event["file"] == "/saved/model.3mf"


# ── gcode / other events ─────────────────────────────────────────────────────

async def test_slice_complete_emitted_on_gcode_creation(tmp_path):
    conf = tmp_path / "OrcaSlicer.conf"
    _orca_conf(conf)
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    handler = _OrcaEventHandler(conf, loop, queue)

    handler.on_created(FileCreatedEvent(str(tmp_path / "output.gcode")))
    await asyncio.sleep(0)

    event = queue.get_nowait()
    assert event["type"] == "orca_event"
    assert event["event"] == "slice_complete"
    assert "output.gcode" in event["file"]


async def test_non_gcode_non_3mf_file_creation_is_ignored(tmp_path):
    conf = tmp_path / "OrcaSlicer.conf"
    _orca_conf(conf)
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    handler = _OrcaEventHandler(conf, loop, queue)

    # Named model.3mf (not .3mf alone) — should be ignored
    handler.on_created(FileCreatedEvent(str(tmp_path / "model.3mf")))
    assert queue.empty()
