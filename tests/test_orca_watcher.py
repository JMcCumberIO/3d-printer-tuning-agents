import asyncio
import json
import pytest
from pathlib import Path
from watchdog.events import FileCreatedEvent, FileModifiedEvent
from server.orca_watcher import _OrcaEventHandler


def _orca_conf(path: Path, recent_project: str = "") -> None:
    """Write a minimal OrcaSlicer.conf JSON with the given recent_projects[01] value."""
    data: dict = {}
    if recent_project:
        data["recent_projects"] = {"01": recent_project}
    path.write_text(json.dumps(data))


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


async def test_non_gcode_file_creation_is_ignored(tmp_path):
    conf = tmp_path / "OrcaSlicer.conf"
    _orca_conf(conf)
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
