import asyncio
import logging
import re
import zipfile
from pathlib import Path
from typing import Optional

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)

# OrcaSlicer writes live session state here regardless of how a model is loaded.
_DEFAULT_TMP_DIR = Path("/tmp/orcaslicer_model")


def _model_name_from_tmp_3mf(path: Path) -> Optional[str]:
    """Extract the first object name from an OrcaSlicer temp .3mf zip file."""
    try:
        with zipfile.ZipFile(path) as zf:
            if "Metadata/model_settings.config" not in zf.namelist():
                return None
            xml = zf.read("Metadata/model_settings.config").decode(errors="replace")
            names = re.findall(r'<metadata key="name" value="([^"]+)"', xml)
            # Deduplicate while preserving order; take first unique name.
            seen: set[str] = set()
            for name in names:
                if name not in seen:
                    seen.add(name)
                    return name
    except Exception:
        pass
    return None


class _OrcaEventHandler(FileSystemEventHandler):
    def __init__(
        self,
        conf_path: Path,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue[dict],
        tmp_dir: Optional[Path] = None,
    ) -> None:
        self._conf_path = conf_path.resolve()
        self._loop = loop
        self._queue = queue
        self._tmp_dir = tmp_dir
        self._last_opened: Optional[str] = None

    def on_modified(self, event: FileSystemEvent) -> None:
        src = Path(str(event.src_path)).resolve()
        if src == self._conf_path:
            self._check_model_opened()
        elif src.suffix == ".gcode" and not event.is_directory:
            self._emit({"type": "orca_event", "event": "slice_complete",
                        "file": str(event.src_path)})

    def on_created(self, event: FileSystemEvent) -> None:
        p = Path(str(event.src_path))
        if event.is_directory:
            return
        if p.name == ".3mf":
            # New OrcaSlicer session temp file — extract and emit model name.
            self._check_tmp_3mf(p)
        elif p.suffix == ".gcode":
            self._emit({"type": "orca_event", "event": "slice_complete",
                        "file": str(event.src_path)})

    def _check_model_opened(self, always_emit: bool = False) -> None:
        # OrcaSlicer.conf is JSON; recent_projects["01"] is the last *saved* project.
        # Only fires reliably for File > Open on a .3mf — not for unsaved sessions.
        try:
            import json
            data = json.loads(self._conf_path.read_text(errors="replace"))
            value = data.get("recent_projects", {}).get("01")
            if value and (always_emit or value != self._last_opened):
                self._last_opened = value
                self._emit({"type": "orca_event", "event": "model_opened",
                            "file": value})
        except (OSError, json.JSONDecodeError):
            pass

    def _check_tmp_3mf(self, path: Path, always_emit: bool = False) -> None:
        """Emit model_opened from an OrcaSlicer temp session .3mf file."""
        name = _model_name_from_tmp_3mf(path)
        if name and (always_emit or name != self._last_opened):
            self._last_opened = name
            self._emit({"type": "orca_event", "event": "model_opened", "file": name})

    def scan_existing_tmp_session(self) -> None:
        """Called at startup to detect a model already open in a running OrcaSlicer."""
        if not self._tmp_dir or not self._tmp_dir.exists():
            return
        tmp_3mfs = sorted(
            self._tmp_dir.rglob(".3mf"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if tmp_3mfs:
            logger.info("OrcaSlicerWatcher found existing session: %s", tmp_3mfs[0])
            self._check_tmp_3mf(tmp_3mfs[0], always_emit=True)
        else:
            # Fall back to conf file for last saved project.
            self._check_model_opened(always_emit=True)

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
        tmp_dir: Optional[str] = None,
    ) -> None:
        self._conf_path = Path(conf_path).expanduser()
        self._watch_dir = Path(watch_dir).expanduser()
        self._gcode_output_dir = Path(gcode_output_dir).expanduser() if gcode_output_dir else None
        self._tmp_dir = Path(tmp_dir) if tmp_dir else _DEFAULT_TMP_DIR
        self._loop = loop
        self._queue = queue
        self._observer: Optional[Observer] = None

    def start(self) -> None:
        handler = _OrcaEventHandler(
            self._conf_path, self._loop, self._queue, tmp_dir=self._tmp_dir
        )

        # Detect whatever is already open in OrcaSlicer (tmp session takes priority).
        handler.scan_existing_tmp_session()

        self._observer = Observer()

        # Watch OrcaSlicer config dir for conf changes (File > Open saved projects).
        self._observer.schedule(handler, str(self._watch_dir), recursive=False)

        # Watch the tmp session dir for new model loads and in-progress gcode.
        if self._tmp_dir.exists():
            self._observer.schedule(handler, str(self._tmp_dir), recursive=True)
            logger.info("OrcaSlicerWatcher watching tmp sessions: %s", self._tmp_dir)
        else:
            logger.info("OrcaSlicer tmp dir not yet present, will miss live session events: %s", self._tmp_dir)

        # Watch gcode export dir if configured and different from conf dir.
        if self._gcode_output_dir and self._gcode_output_dir.resolve() != self._watch_dir.resolve():
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
