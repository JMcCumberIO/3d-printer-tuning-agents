# tests/test_filament_research_agent.py
import json
import pytest
from unittest.mock import MagicMock
from agents.filament_research_agent import FilamentResearchAgent


def _mock_client(text_response: str):
    """Build an Anthropic client mock that returns a single text block."""
    client = MagicMock()
    block = MagicMock()
    block.text = text_response
    response = MagicMock()
    response.content = [block]
    client.messages.create.return_value = response
    return client


_GOOD_RESPONSE = json.dumps({
    "source": "manufacturer + community",
    "retrieved": "2026-04-14",
    "nozzle_temp": {"recommended": 225, "range": [215, 235], "source_count": 12},
    "bed_temp":    {"recommended": 60,  "range": [55, 65],   "source_count": 10},
    "flow_rate":   {"recommended": 1.0, "range": [0.95, 1.05], "source_count": 6},
    "max_speed":   {"recommended": 200, "range": [150, 300], "source_count": 8},
    "cooling_fan": {"recommended": 100, "range": [80, 100],  "source_count": 9},
})


def test_research_returns_structured_baseline():
    agent = FilamentResearchAgent(_mock_client(_GOOD_RESPONSE))
    result = agent.research("ELEGOO PLA+ High Speed", "0.4mm")
    assert result["nozzle_temp"]["recommended"] == 225
    assert result["bed_temp"]["recommended"] == 60
    assert result["source"] == "manufacturer + community"


def test_research_passes_filament_name_in_prompt():
    client = _mock_client(_GOOD_RESPONSE)
    agent = FilamentResearchAgent(client)
    agent.research("Mika3D Silk PLA", "0.6mm")
    call_kwargs = client.messages.create.call_args
    prompt_text = call_kwargs[1]["messages"][0]["content"]
    assert "Mika3D Silk PLA" in prompt_text
    assert "0.6mm" in prompt_text


def test_research_calls_correct_model():
    client = _mock_client(_GOOD_RESPONSE)
    agent = FilamentResearchAgent(client)
    agent.research("Test PLA", "0.4mm")
    call_kwargs = client.messages.create.call_args
    assert call_kwargs[1]["model"] == "claude-sonnet-4-6"


def test_research_raises_on_unparseable_response():
    client = _mock_client("I could not find any data about this filament.")
    agent = FilamentResearchAgent(client)
    with pytest.raises(ValueError, match="No valid JSON"):
        agent.research("Unknown Brand Filament", "0.4mm")


def test_research_parses_json_embedded_in_prose():
    prose_response = "Here are the settings for your filament:\n\n" + _GOOD_RESPONSE + "\n\nLet me know if you need more details."
    agent = FilamentResearchAgent(_mock_client(prose_response))
    result = agent.research("ELEGOO PLA+", "0.4mm")
    assert result["nozzle_temp"]["recommended"] == 225
