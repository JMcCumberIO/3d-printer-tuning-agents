# agents/vision_agent.py
import base64
import json
from typing import Optional

import anthropic

from tools.ha_client import HAClient


class VisionAgent:
    """
    Captures a camera snapshot from HA and scores print quality using Claude vision.
    Returns scores 0.0–1.0 for: stringing, layer_adhesion, warping, surface_finish, overall.
    """

    RUBRIC = """Score this 3D print quality on a scale of 0.0 to 1.0 for each dimension.
Return ONLY valid JSON, no other text:
{"stringing": <0-1>, "layer_adhesion": <0-1>, "warping": <0-1>, "surface_finish": <0-1>, "overall": <0-1>}

Scoring guide (1.0 = perfect, 0.0 = completely failed):
- stringing: 1.0 = no stringing, 0.0 = severe stringing everywhere
- layer_adhesion: 1.0 = perfect layer bonding, 0.0 = delaminating
- warping: 1.0 = no warping/lifting, 0.0 = severe warping
- surface_finish: 1.0 = smooth finish, 0.0 = rough/blobby
- overall: your holistic quality assessment"""

    def __init__(self, client: anthropic.Anthropic, ha: HAClient):
        self.client = client
        self.ha = ha

    def score(self, image_bytes: Optional[bytes] = None) -> dict:
        """
        Score print quality from an image.
        Captures from HA camera if image_bytes is not provided.
        Returns dict with five quality dimension scores.
        """
        if image_bytes is None:
            image_bytes = self.ha.get_camera_snapshot()

        b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": self.RUBRIC},
                ],
            }],
        )
        return self._parse_scores(response)

    def _parse_scores(self, response) -> dict:
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
        raise ValueError("No valid JSON scores in vision response")
