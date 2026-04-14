# tests/test_vision_agent.py
import json
import pytest
from unittest.mock import MagicMock
from agents.vision_agent import VisionAgent


def _mock_client(text_response: str):
    client = MagicMock()
    block = MagicMock()
    block.text = text_response
    response = MagicMock()
    response.content = [block]
    client.messages.create.return_value = response
    return client


_GOOD_SCORES = json.dumps({
    "stringing": 0.9,
    "layer_adhesion": 0.85,
    "warping": 0.95,
    "surface_finish": 0.88,
    "overall": 0.90,
})


def test_score_returns_five_dimensions():
    agent = VisionAgent(_mock_client(_GOOD_SCORES), ha=MagicMock())
    scores = agent.score(image_bytes=b"FAKEJPEG")
    assert set(scores.keys()) == {"stringing", "layer_adhesion", "warping", "surface_finish", "overall"}
    assert scores["overall"] == pytest.approx(0.90)


def test_score_uses_provided_image_not_ha():
    mock_ha = MagicMock()
    agent = VisionAgent(_mock_client(_GOOD_SCORES), ha=mock_ha)
    agent.score(image_bytes=b"FAKEJPEG")
    mock_ha.get_camera_snapshot.assert_not_called()


def test_score_captures_from_ha_when_no_image():
    mock_ha = MagicMock()
    mock_ha.get_camera_snapshot.return_value = b"HAJPEG"
    agent = VisionAgent(_mock_client(_GOOD_SCORES), ha=mock_ha)
    agent.score()
    mock_ha.get_camera_snapshot.assert_called_once()


def test_score_raises_on_bad_response():
    agent = VisionAgent(_mock_client("I cannot assess this image."), ha=MagicMock())
    with pytest.raises(ValueError, match="No valid JSON"):
        agent.score(image_bytes=b"FAKEJPEG")


def test_score_sends_image_as_base64():
    client = _mock_client(_GOOD_SCORES)
    agent = VisionAgent(client, ha=MagicMock())
    agent.score(image_bytes=b"FAKEJPEG")
    call_kwargs = client.messages.create.call_args[1]
    content = call_kwargs["messages"][0]["content"]
    image_block = next(c for c in content if c.get("type") == "image")
    assert image_block["source"]["type"] == "base64"
    assert image_block["source"]["media_type"] == "image/jpeg"
