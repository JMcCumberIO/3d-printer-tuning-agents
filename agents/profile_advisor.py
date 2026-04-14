# agents/profile_advisor.py
import json
from pathlib import Path

import anthropic

from tools.calibration_db import CalibrationDB
from tools.gcode_extractor import GcodeExtractor


class ProfileAdvisorAgent:
    """
    Analyzes a .3mf model's geometry (via gcode stats) against the calibrated baseline
    for the active filament × nozzle, and recommends profile adjustments.
    Advisory only — does not write profiles itself; caller applies diffs after user approval.
    """

    def __init__(self, client: anthropic.Anthropic, db: CalibrationDB):
        self.client = client
        self.db = db

    def advise(self, model_path: Path, filament: str, nozzle: str) -> dict:
        """
        Produce profile adjustment recommendations for model_path given the calibrated baseline.
        Returns {"recommendations": [...], "summary": "..."}
        where each recommendation is {"param": str, "current": val, "suggested": val, "reason": str}
        Raises ValueError if no calibration entry exists for the filament/nozzle.
        """
        model_path = Path(model_path)
        entry = self.db.get_or_create(filament, nozzle)
        if entry["baseline"].get("nozzle_temp") is None:
            key = CalibrationDB._key(filament, nozzle)
            raise ValueError(
                f"No calibration data for '{key}'. Run 'tune calibrate' first."
            )

        gcode_stats = self._extract_gcode_stats(model_path)
        baseline = entry["baseline"]

        prompt = self._build_prompt(filament, nozzle, baseline, gcode_stats)
        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        return self._parse_response(response)

    def _extract_gcode_stats(self, model_path: Path) -> dict:
        """Extract key stats from the gcode in a .3mf file."""
        ex = GcodeExtractor(model_path)
        try:
            gcode_bytes = ex.extract_gcode()
        except FileNotFoundError:
            return {"error": "No gcode found in .3mf"}

        gcode_text = gcode_bytes.decode("utf-8", errors="replace")
        stats: dict = {}

        for line in gcode_text.splitlines():
            line = line.strip()
            if not line.startswith(";"):
                continue
            # Parse "; key = value" header lines from OrcaSlicer gcode
            if " = " in line:
                key_part, _, val_part = line[1:].partition(" = ")
                stats[key_part.strip()] = val_part.strip()

        return stats

    def _build_prompt(self, filament: str, nozzle: str, baseline: dict, gcode_stats: dict) -> str:
        return f"""You are advising on OrcaSlicer profile settings for a 3D print.

Filament: {filament}
Nozzle: {nozzle}
Calibrated baseline: {json.dumps(baseline, indent=2)}

Model gcode statistics:
{json.dumps(gcode_stats, indent=2)}

Based on the model geometry (layer count, support requirements, wall structure) and the calibrated baseline settings, what OrcaSlicer profile adjustments do you recommend for this specific print?

Return ONLY JSON with this structure:
{{
  "recommendations": [
    {{"param": "<orca_profile_key>", "current": <value>, "suggested": <value>, "reason": "<one sentence>"}}
  ],
  "summary": "<2-3 sentence overall recommendation>"
}}

If no changes are needed, return an empty recommendations list."""

    def _parse_response(self, response) -> dict:
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
        return {"recommendations": [], "summary": "Could not parse advisor response."}
