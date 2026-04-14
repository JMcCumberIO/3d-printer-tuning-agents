import json
import shutil
from pathlib import Path


class OrcaProfiles:
    def __init__(self, profile_dir: str | Path):
        self.profile_dir = Path(profile_dir)
        self.filament_dir = self.profile_dir / "filament"
        self.process_dir = self.profile_dir / "process"

    def _filament_path(self, name: str) -> Path:
        return self.filament_dir / f"{name}.json"

    def _process_path(self, name: str) -> Path:
        return self.process_dir / f"{name}.json"

    def read_filament(self, name: str) -> dict:
        path = self._filament_path(name)
        if not path.exists():
            raise FileNotFoundError(f"Filament profile not found: {path}")
        return json.loads(path.read_text())

    def write_filament(self, name: str, data: dict) -> None:
        path = self._filament_path(name)
        if path.exists():
            shutil.copy2(path, path.with_suffix(".json.bak"))
        path.write_text(json.dumps(data, indent=2))

    def rollback_filament(self, name: str) -> None:
        bak = self._filament_path(name).with_suffix(".json.bak")
        if not bak.exists():
            raise FileNotFoundError(f"No backup found for filament profile: {name}")
        shutil.copy2(bak, self._filament_path(name))

    def list_filament_profiles(self) -> list[str]:
        return [
            p.stem
            for p in self.filament_dir.glob("*.json")
            if not p.name.endswith(".bak")
        ]

    def read_process(self, name: str) -> dict:
        path = self._process_path(name)
        if not path.exists():
            raise FileNotFoundError(f"Process profile not found: {path}")
        return json.loads(path.read_text())

    def write_process(self, name: str, data: dict) -> None:
        path = self._process_path(name)
        if path.exists():
            shutil.copy2(path, path.with_suffix(".json.bak"))
        path.write_text(json.dumps(data, indent=2))

    def rollback_process(self, name: str) -> None:
        bak = self._process_path(name).with_suffix(".json.bak")
        if not bak.exists():
            raise FileNotFoundError(f"No backup found for process profile: {name}")
        shutil.copy2(bak, self._process_path(name))

    def list_process_profiles(self) -> list[str]:
        return [
            p.stem
            for p in self.process_dir.glob("*.json")
            if not p.name.endswith(".bak")
        ]

    def profile_diff(self, original: dict, updated: dict) -> dict[str, tuple]:
        """Return {key: (old_value, new_value)} for changed keys."""
        return {
            k: (original.get(k), updated[k])
            for k in updated
            if updated[k] != original.get(k)
        }
