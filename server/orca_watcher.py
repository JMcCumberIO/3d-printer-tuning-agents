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
        queue: asyncio.Queue[dict],
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
