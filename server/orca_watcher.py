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
        queue: asyncio.Queue[dict],
    ) -> None:
        self._conf_path = conf_path.resolve()
        self._loop = loop
        self._queue = queue
        self._last_opened: Optional[str] = None

    def on_modified(self, event: FileSystemEvent) -> None:
        src = Path(str(event.src_path)).resolve()
        if src == self._conf_path:
            self._check_model_opened()
        elif src.suffix == ".gcode" and not event.is_directory:
            self._emit({"type": "orca_event", "event": "slice_complete",
                        "file": str(event.src_path)})

    def on_created(self, event: FileSystemEvent) -> None:
        if Path(str(event.src_path)).suffix == ".gcode" and not event.is_directory:
            self._emit({"type": "orca_event", "event": "slice_complete",
                        "file": str(event.src_path)})

    def _check_model_opened(self) -> None:
        # OrcaSlicer.conf is JSON. The most recently opened project is at
        # recent_projects["01"]; it updates every time a project is opened.
        try:
            import json
            data = json.loads(self._conf_path.read_text(errors="replace"))
            value = data.get("recent_projects", {}).get("01")
            if value and value != self._last_opened:
                self._last_opened = value
                self._emit({"type": "orca_event", "event": "model_opened",
                            "file": value})
        except (OSError, json.JSONDecodeError):
            pass

    def _emit(self, payload: dict) -> None:
        self._loop.call_soon_threadsafe(self._queue.put_nowait, payload)


class OrcaSlicerWatcher:
    def __init__(
        self,
        conf_path: str,
        watch_dir: str,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue[dict],
        gcode_output_dir: Optional[str] = None,
    ) -> None:
        self._conf_path = Path(conf_path).expanduser()
        self._watch_dir = Path(watch_dir).expanduser()
        self._gcode_output_dir = Path(gcode_output_dir).expanduser() if gcode_output_dir else None
        self._loop = loop
        self._queue = queue
        self._observer: Optional[Observer] = None

    def start(self) -> None:
        handler = _OrcaEventHandler(self._conf_path, self._loop, self._queue)
        self._observer = Observer()
        # Watch OrcaSlicer config dir for conf changes (model_opened)
        self._observer.schedule(handler, str(self._watch_dir), recursive=False)
        # Watch gcode output dir if configured and different from conf dir
        if self._gcode_output_dir and self._gcode_output_dir != self._watch_dir:
            if self._gcode_output_dir.exists():
                self._observer.schedule(handler, str(self._gcode_output_dir), recursive=True)
                logger.info("OrcaSlicerWatcher watching gcode output: %s", self._gcode_output_dir)
            else:
                logger.warning("gcode_output_dir does not exist, skipping: %s", self._gcode_output_dir)
        self._observer.start()
        logger.info("OrcaSlicerWatcher started on %s", self._watch_dir)

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join()
