# agents/calibration_agent.py
import json
import time
from pathlib import Path
from typing import Callable, Optional

import anthropic

from agents.vision_agent import VisionAgent
from tools.calibration_db import CalibrationDB
from tools.ha_client import HAClient
from tools.orca_profiles import OrcaProfiles
from tools.orca_reader import read_current_settings, read_gcode_setting, wait_for_new_gcode
from tools.print_logger import PrintLogger


class CalibrationAgent:
    """
    Tier-aware calibration agent. For each uncalibrated parameter:
    1. Asks Claude what value to test
    2. Confirms with user (always in Tier 1, conditionally in Tier 2, auto in Tier 3)
    3. Asks user for the gcode file path (must pre-slice in OrcaSlicer)
    4. Starts the print via HA, monitors to completion
    5. Scores with VisionAgent, logs result, updates CalibrationDB
    """

    # Parameters tested in order
    CALIBRATION_SEQUENCE = [
        "nozzle_temp", "bed_temp", "flow_rate", "pressure_advance", "cooling_fan", "max_speed",
    ]

    def __init__(
        self,
        client: anthropic.Anthropic,
        db: CalibrationDB,
        ha: HAClient,
        vision: VisionAgent,
        logger: PrintLogger,
        confirm_fn: Callable[[str], bool] = lambda msg: True,
        ask_fn: Callable[[str], str] = input,
        poll_interval_seconds: int = 15,
        profiles: Optional[OrcaProfiles] = None,
        gcode_export_dir: Optional[str] = None,
    ):
        self.client = client
        self.db = db
        self.ha = ha
        self.vision = vision
        self.logger = logger
        self.confirm_fn = confirm_fn
        self.ask_fn = ask_fn
        self.poll_interval = poll_interval_seconds
        self.profiles = profiles  # optional, used for profile writes
        self.gcode_export_dir = Path(gcode_export_dir).expanduser() if gcode_export_dir else None

    def run(self, filament: str, nozzle: str) -> dict:
        """
        Run calibration for a filament/nozzle pair.
        Returns summary: {tested: [...], skipped: [...], skipped_count, declined_count, results}
        """
        entry = self.db.get_or_create(filament, nozzle)
        tier = self.db.get_confidence_tier(filament, nozzle)

        tested, skipped, declined, results = [], [], [], []

        for param in self.CALIBRATION_SEQUENCE:
            if entry["baseline"].get(param) is not None:
                skipped.append(param)
                continue

            suggestion = self._suggest_value(param, filament, nozzle, entry)
            value = suggestion["value"]
            rationale = suggestion.get("rationale", "")

            # Show current OrcaSlicer setting vs target so the user knows what to change.
            current = read_current_settings().get(param)
            if current is not None and current != value:
                change_hint = f"  OrcaSlicer currently has {param}={current} → change to {value}"
            elif current == value:
                change_hint = f"  OrcaSlicer already has {param}={value} ✓"
            else:
                change_hint = f"  Set {param}={value} in OrcaSlicer"

            msg = (
                f"[Tier {tier}] Test {param} = {value}  ({rationale})\n"
                f"{change_hint}\n"
                f"Slice in OrcaSlicer then export gcode to {self.gcode_export_dir or '~/projects/3D Printing'}."
            )

            if not self.confirm_fn(msg):
                declined.append(param)
                continue

            # Auto-detect gcode export instead of asking the user for a path.
            gcode_path: Optional[str] = None
            if self.gcode_export_dir and self.gcode_export_dir.exists():
                print(f"Waiting for gcode export to {self.gcode_export_dir} …")
                detected = wait_for_new_gcode(self.gcode_export_dir, timeout_seconds=600)
                if detected:
                    # Verify the setting is actually in the file.
                    actual = read_gcode_setting(detected, param)
                    if actual is not None and actual != value:
                        print(f"  Warning: gcode has {param}={actual}, expected {value}. Proceeding anyway.")
                    gcode_path = str(detected)
                    print(f"  Detected: {detected.name}")
                else:
                    print("  Timed out waiting for gcode. Falling back to manual entry.")

            if not gcode_path:
                gcode_path = self.ask_fn(
                    f"Enter the gcode file path on the printer for {param}={value} test: "
                )
            if not gcode_path:
                declined.append(param)
                continue

            settings = {
                "filament": filament, "nozzle": nozzle, "param": param,
                "value": value, "tier": tier,
            }
            run_dir = self.logger.start_run(settings)

            # Snapshot HA state at print start
            try:
                ha_snapshot = self.ha.ha_snapshot()
                self.logger.log_ha_snapshot(run_dir, ha_snapshot)
            except Exception:
                pass

            self.ha.start_print(gcode_path)
            final_status = self._wait_for_print()

            # Capture + score
            try:
                image = self.ha.get_camera_snapshot()
                self.logger.log_camera_snapshot(run_dir, image)
                scores = self.vision.score(image_bytes=image)
            except Exception:
                scores = {"overall": 0.0}
            self.logger.log_vision_score(run_dir, scores)

            # Collect user feedback
            feedback = self.ask_fn("Pass/fail note (optional, press Enter to skip): ")
            if feedback:
                self.logger.log_feedback(run_dir, feedback)

            run_data = {
                "param": param, "value": value, "final_status": final_status,
                **scores,
            }
            self.db.add_run(filament, nozzle, run_data)

            if scores.get("overall", 0) >= 0.7:
                self.db.set_baseline(filament, nozzle, **{param: value})

            tested.append(param)
            results.append(run_data)

        return {
            "filament": filament,
            "nozzle": nozzle,
            "tier": tier,
            "tested": tested,
            "skipped": skipped,
            "skipped_count": len(skipped),
            "declined_count": len(declined),
            "results": results,
        }

    def _suggest_value(self, param: str, filament: str, nozzle: str, entry: dict) -> dict:
        """Ask Claude what value to test for a parameter."""
        research = entry.get("research_baseline") or {}
        baseline = entry.get("baseline") or {}
        recent_runs = entry.get("run_history", [])[-5:]

        prompt = f"""Calibrating {param} for "{filament}" on a Flashforge AD5M Pro with {nozzle} nozzle.

Current baseline: {json.dumps(baseline)}
Research data: {json.dumps(research)}
Recent runs: {json.dumps(recent_runs)}

What single value should we test for {param} next?
Return ONLY JSON: {{"value": <number>, "rationale": "<one sentence>"}}"""

        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )

        decoder = json.JSONDecoder()
        for block in response.content:
            if hasattr(block, "text"):
                text = block.text
                for i, ch in enumerate(text):
                    if ch == '{':
                        try:
                            obj, _ = decoder.raw_decode(text, i)
                            return obj
                        except json.JSONDecodeError:
                            continue
        return {"value": 225, "rationale": "default fallback"}

    def _wait_for_print(self, timeout_min: int = 120) -> str:
        """Poll HA every poll_interval seconds until printing stops. Returns final status."""
        deadline = time.monotonic() + timeout_min * 60
        while time.monotonic() < deadline:
            if not self.ha.is_printing():
                return self.ha.get_print_status()
            time.sleep(self.poll_interval)
        raise TimeoutError(f"Print did not complete within {timeout_min} minutes")
