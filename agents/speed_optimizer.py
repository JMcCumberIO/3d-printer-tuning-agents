# agents/speed_optimizer.py
import time
from typing import Callable

from agents.vision_agent import VisionAgent
from tools.calibration_db import CalibrationDB
from tools.ha_client import HAClient
from tools.print_logger import PrintLogger


class SpeedOptimizerAgent:
    """
    Starting from the calibrated baseline max_speed, proposes speed increases
    in step_percent increments. Runs test prints, scores via VisionAgent, and
    tracks a Pareto frontier. Stops when quality drops below quality_threshold.
    Prerequisite: calibrated baseline must exist (max_speed not None).
    """

    def __init__(
        self,
        db: CalibrationDB,
        ha: HAClient,
        vision: VisionAgent,
        logger: PrintLogger,
        quality_threshold: float = 0.80,
        step_percent: int = 10,
        confirm_fn: Callable[[str], bool] = lambda msg: True,
        ask_fn: Callable[[str], str] = input,
        poll_interval_seconds: int = 15,
    ):
        self.db = db
        self.ha = ha
        self.vision = vision
        self.logger = logger
        self.quality_threshold = quality_threshold
        self.step_percent = step_percent
        self.confirm_fn = confirm_fn
        self.ask_fn = ask_fn
        self.poll_interval = poll_interval_seconds

    def run(self, filament: str, nozzle: str) -> dict:
        """
        Run speed optimization loop. Returns summary dict with final_speed and stopped_reason.
        """
        entry = self.db.get_or_create(filament, nozzle)
        baseline_speed = entry["baseline"].get("max_speed")
        if baseline_speed is None:
            raise ValueError(
                f"Calibrated baseline required for '{filament} | {nozzle}'. "
                "Run 'tune calibrate' first."
            )

        current_speed = baseline_speed
        last_passing_speed = current_speed
        stopped_reason = "max_iterations"
        pareto_points = []

        for iteration in range(20):  # safety cap
            next_speed = round(current_speed * (1 + self.step_percent / 100))
            msg = (
                f"Speed test {iteration + 1}: {current_speed} → {next_speed} mm/s\n"
                f"Please slice a test print at max_speed={next_speed} mm/s."
            )
            if not self.confirm_fn(msg):
                stopped_reason = "user_declined"
                break

            gcode_path = self.ask_fn(
                f"Enter gcode file path for speed={next_speed}mm/s test: "
            )
            if not gcode_path:
                stopped_reason = "user_declined"
                break

            settings = {
                "filament": filament, "nozzle": nozzle, "phase": "speed",
                "tested_speed": next_speed, "baseline_speed": baseline_speed,
            }
            run_dir = self.logger.start_run(settings)

            try:
                ha_snapshot = self.ha.ha_snapshot()
                self.logger.log_ha_snapshot(run_dir, ha_snapshot)
            except Exception:
                pass

            self.ha.start_print(gcode_path)
            self._wait_for_print()

            try:
                image = self.ha.get_camera_snapshot()
                self.logger.log_camera_snapshot(run_dir, image)
                scores = self.vision.score(image_bytes=image)
            except Exception:
                scores = {"overall": 0.0}
            self.logger.log_vision_score(run_dir, scores)

            overall = scores.get("overall", 0.0)
            self.db.add_speed_pareto(filament, nozzle, speed_mms=next_speed, quality_score=overall)
            pareto_points.append({"speed": next_speed, "quality": overall})

            self.db.add_run(filament, nozzle, {
                "phase": "speed", "speed": next_speed, "overall": overall,
            })

            if overall >= self.quality_threshold:
                last_passing_speed = next_speed
                current_speed = next_speed
            else:
                stopped_reason = "quality_below_threshold"
                break

        # Save best passing speed to baseline
        self.db.set_baseline(filament, nozzle, max_speed=last_passing_speed)

        return {
            "filament": filament,
            "nozzle": nozzle,
            "final_speed": last_passing_speed,
            "stopped_reason": stopped_reason,
            "pareto_points": pareto_points,
        }

    def _wait_for_print(self, timeout_min: int = 120) -> str:
        deadline = time.monotonic() + timeout_min * 60
        while time.monotonic() < deadline:
            if not self.ha.is_printing():
                return self.ha.get_print_status()
            time.sleep(self.poll_interval)
        raise TimeoutError(f"Print did not complete within {timeout_min} minutes")
