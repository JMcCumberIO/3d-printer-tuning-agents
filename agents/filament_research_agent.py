# agents/filament_research_agent.py
import json
from datetime import datetime, timezone

import anthropic


class FilamentResearchAgent:
    """
    Researches manufacturer and community settings for a filament × nozzle pair.
    Uses Claude's training knowledge (supplemented by web search when available).
    """

    def __init__(self, client: anthropic.Anthropic):
        self.client = client

    def research(self, filament: str, nozzle: str) -> dict:
        """
        Research optimal print settings for filament on a Flashforge AD5M Pro.
        Returns a research_baseline dict suitable for CalibrationDB.set_research_baseline().
        """
        prompt = self._build_prompt(filament, nozzle)
        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        return self._parse_response(response)

    def _build_prompt(self, filament: str, nozzle: str) -> str:
        today = datetime.now(timezone.utc).date().isoformat()
        return f"""You are helping calibrate a Flashforge Adventurer 5M Pro (CoreXY, direct drive) with a {nozzle} nozzle.

Research optimal print settings for this filament: "{filament}"

Provide community-consensus settings based on:
- Manufacturer's official specifications
- Reddit r/FlashForge, r/3Dprinting, r/FixMyPrint reports
- Printables and MakerWorld community profiles for this filament
- OrcaSlicer filament profile repositories

Return ONLY a JSON object with this exact structure (no other text):
{{
  "source": "manufacturer + community",
  "retrieved": "{today}",
  "nozzle_temp": {{"recommended": <int°C>, "range": [<min>, <max>], "source_count": <int>}},
  "bed_temp":    {{"recommended": <int°C>, "range": [<min>, <max>], "source_count": <int>}},
  "flow_rate":   {{"recommended": <float>,  "range": [<min>, <max>], "source_count": <int>}},
  "max_speed":   {{"recommended": <int mm/s>, "range": [<min>, <max>], "source_count": <int>}},
  "cooling_fan": {{"recommended": <int%>,   "range": [<min>, <max>], "source_count": <int>}}
}}"""

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
        raise ValueError("No valid JSON found in research response")
