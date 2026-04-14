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
    await asyncio.sleep(0)  # yield to event loop

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
    await asyncio.sleep(0)  # yield to event loop
    queue.get_nowait()              # consume initial event

    conf.write_text("last_opened = /new/model.3mf\n")
    handler._check_model_opened()
    await asyncio.sleep(0)  # yield to event loop

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
    await asyncio.sleep(0)  # yield to event loop
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
    await asyncio.sleep(0)  # yield to event loop

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
