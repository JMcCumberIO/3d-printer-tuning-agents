import copy
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class ParameterStats:
    sample_count: int = 0
    confidence: float = 0.0
    proven_range: list[float] = field(default_factory=list)
    pass_rate: float = 0.0


_EMPTY_ENTRY = {
    "confidence_tier": 1,
    "baseline": {
        "nozzle_temp": None,
        "bed_temp": None,
        "flow_rate": None,
        "pressure_advance": None,
        "max_speed": None,
        "cooling_fan": None,
    },
    "parameters": {},
    "research_baseline": None,
    "speed_pareto": [],
    "run_history": [],
}


class CalibrationDB:
    def __init__(self, db_path: str | Path, tier2_min: int = 4, tier3_min: int = 11):
        self.db_path = Path(db_path)
        self.tier2_min = tier2_min
        self.tier3_min = tier3_min
        self._data: dict = {}
        if self.db_path.exists():
            self._data = json.loads(self.db_path.read_text())

    @staticmethod
    def _key(filament: str, nozzle: str) -> str:
        return f"{filament} | {nozzle}"

    def get_or_create(self, filament: str, nozzle: str) -> dict:
        key = self._key(filament, nozzle)
        if key not in self._data:
            self._data[key] = copy.deepcopy(_EMPTY_ENTRY)
        return self._data[key]

    def get_entry(self, filament: str, nozzle: str) -> dict:
        """Return the entry for a filament/nozzle pair, or {} if not found."""
        return self._data.get(self._key(filament, nozzle), {})

    def save(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path.write_text(json.dumps(self._data, indent=2))

    def set_baseline(self, filament: str, nozzle: str, **kwargs) -> None:
        entry = self.get_or_create(filament, nozzle)
        for k, v in kwargs.items():
            entry["baseline"][k] = v
        self.save()

    def set_research_baseline(self, filament: str, nozzle: str, research: dict) -> None:
        entry = self.get_or_create(filament, nozzle)
        entry["research_baseline"] = research
        self.save()

    def add_run(self, filament: str, nozzle: str, run_data: dict) -> None:
        entry = self.get_or_create(filament, nozzle)
        run = {**run_data, "timestamp": datetime.now(timezone.utc).isoformat()}
        entry["run_history"].append(run)
        entry["confidence_tier"] = self.get_confidence_tier(filament, nozzle)
        self.save()

    def add_speed_pareto(self, filament: str, nozzle: str, speed_mms: float, quality_score: float) -> None:
        entry = self.get_or_create(filament, nozzle)
        entry["speed_pareto"].append({
            "speed": speed_mms,
            "quality_score": quality_score,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self.save()

    def get_confidence_tier(self, filament: str, nozzle: str) -> int:
        entry = self.get_or_create(filament, nozzle)
        n = len(entry["run_history"])
        if n >= self.tier3_min:
            return 3
        if n >= self.tier2_min:
            return 2
        return 1

    def list_filaments(self) -> list[str]:
        return list(self._data.keys())

    def get_speed_pareto(self, filament: str, nozzle: str) -> list[dict]:
        return self.get_or_create(filament, nozzle)["speed_pareto"]
