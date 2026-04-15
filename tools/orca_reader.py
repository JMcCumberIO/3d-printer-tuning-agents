"""
tools/orca_reader.py

Reads live OrcaSlicer session state from the temp directory and detects
new gcode exports. Used by CalibrationAgent to show current vs target
settings and auto-detect sliced files instead of asking the user.
"""
import json
import time
from pathlib import Path
from typing import Optional

# Keys in _temp_1.config that correspond to calibration parameters.
# Values are lists in the JSON (per-extruder), so we take [0].
_PARAM_TO_ORCA_KEY: dict[str, str] = {
    "nozzle_temp": "nozzle_temperature",
    "bed_temp": "hot_plate_temp",
    "flow_rate": "filament_flow_ratio",
    "cooling_fan": "slow_down_min_speed",   # closest available; actual fan is in gcode
    "max_speed": "outer_wall_speed",
    "pressure_advance": "pressure_advance",
}

# Keys that are stored as lists (per-extruder) — take first element.
_LIST_KEYS = {
    "nozzle_temperature", "nozzle_temperature_initial_layer",
    "hot_plate_temp", "hot_plate_temp_initial_layer",
    "filament_flow_ratio",
}

# Gcode header comment keys for the same parameters.
_PARAM_TO_GCODE_KEY: dict[str, str] = {
    "nozzle_temp": "nozzle_temperature",
    "bed_temp": "hot_plate_temp",
    "flow_rate": "filament_flow_ratio",
    "max_speed": "outer_wall_speed",
    "pressure_advance": "pressure_advance",
}

_DEFAULT_TMP_DIR = Path("/tmp/orcaslicer_model")


def _latest_session_dir(tmp_dir: Path) -> Optional[Path]:
    """Return the most recently modified OrcaSlicer temp session directory."""
    candidates = sorted(
        (p for p in tmp_dir.rglob("_temp_1.config") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0].parent if candidates else None


def read_current_settings(tmp_dir: Path = _DEFAULT_TMP_DIR) -> dict[str, float | None]:
    """
    Return a dict of calibration param → current value from the live OrcaSlicer session.
    Returns empty dict if no session is found.
    """
    session = _latest_session_dir(tmp_dir)
    if not session:
        return {}
    config_file = session / "_temp_1.config"
    try:
        data = json.loads(config_file.read_text(errors="replace"))
    except Exception:
        return {}

    result: dict[str, float | None] = {}
    for param, key in _PARAM_TO_ORCA_KEY.items():
        raw = data.get(key)
        if raw is None:
            result[param] = None
            continue
        # List values (per-extruder) — take first element.
        val = raw[0] if isinstance(raw, list) else raw
        try:
            result[param] = float(val)
        except (TypeError, ValueError):
            result[param] = None
    return result


def read_gcode_setting(gcode_path: Path, param: str) -> Optional[float]:
    """
    Read a parameter value from an OrcaSlicer gcode header comment.
    Returns None if the key is not found or can't be parsed.
    """
    key = _PARAM_TO_GCODE_KEY.get(param)
    if not key:
        return None
    prefix = f"; {key} = "
    try:
        with gcode_path.open(errors="replace") as f:
            for line in f:
                if not line.startswith(";"):
                    # OrcaSlicer puts settings before the first non-comment line.
                    break
                if line.startswith(prefix):
                    try:
                        return float(line[len(prefix):].strip())
                    except ValueError:
                        return None
    except OSError:
        pass
    return None


def wait_for_new_gcode(
    export_dir: Path,
    timeout_seconds: int = 600,
    poll_interval: float = 1.0,
) -> Optional[Path]:
    """
    Block until a new (or freshly modified) .gcode file appears in export_dir.
    Returns the path of the detected file, or None on timeout.

    "New" means any .gcode whose mtime is newer than when this function was called.
    """
    start = time.monotonic()
    baseline_mtimes: dict[Path, float] = {
        p: p.stat().st_mtime
        for p in export_dir.glob("*.gcode")
        if p.is_file()
    }

    while time.monotonic() - start < timeout_seconds:
        for p in export_dir.glob("*.gcode"):
            if not p.is_file():
                continue
            mtime = p.stat().st_mtime
            if p not in baseline_mtimes or mtime > baseline_mtimes[p]:
                return p
        time.sleep(poll_interval)
    return None
