# tools/print_logger.py
import json
from datetime import datetime, timezone
from pathlib import Path


class PrintLogger:
    """
    Creates structured print_log/{timestamp}/ directories for each print run.
    Stores settings, HA state snapshot, camera image, vision scores, and user feedback.
    """

    def __init__(self, log_dir: Path = Path("print_log")):
        self.log_dir = Path(log_dir)

    def start_run(self, settings: dict) -> Path:
        """Create a new timestamped run directory and write settings.json. Returns the run dir."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")
        run_dir = self.log_dir / ts
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "settings.json").write_text(json.dumps(settings, indent=2))
        return run_dir

    def log_ha_snapshot(self, run_dir: Path, snapshot: dict) -> None:
        """Write full HA entity state dict to ha_snapshot.json."""
        (run_dir / "ha_snapshot.json").write_text(json.dumps(snapshot, indent=2))

    def log_camera_snapshot(self, run_dir: Path, image_bytes: bytes) -> None:
        """Write camera image bytes to camera_snapshot.jpg."""
        (run_dir / "camera_snapshot.jpg").write_bytes(image_bytes)

    def log_vision_score(self, run_dir: Path, scores: dict) -> None:
        """Write VisionAgent score dict to vision_score.json."""
        (run_dir / "vision_score.json").write_text(json.dumps(scores, indent=2))

    def log_feedback(self, run_dir: Path, feedback: str) -> None:
        """Write user pass/fail note to feedback.txt."""
        (run_dir / "feedback.txt").write_text(feedback)
