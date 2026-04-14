import json
import os
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

    def _atomic_write(self, path: Path, data: dict) -> None:
        """Back up existing file then write atomically via temp+rename."""
        if path.exists():
            shutil.copy2(path, path.with_suffix(".json.bak"))
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, path)

    def read_filament(self, name: str) -> dict:
        path = self._filament_path(name)
        if not path.exists():
            raise FileNotFoundError(f"Filament profile not found: {path}")
        return json.loads(path.read_text())

    def write_filament(self, name: str, data: dict) -> None:
        self._atomic_write(self._filament_path(name), data)

    def rollback_filament(self, name: str) -> None:
        path = self._filament_path(name)
        bak = path.with_suffix(".json.bak")
        if not bak.exists():
            raise FileNotFoundError(f"No backup found for filament profile: {name}")
        os.replace(bak, path)

    def list_filament_profiles(self) -> list[str]:
        return sorted(
            p.stem
            for p in self.filament_dir.glob("*.json")
            if not p.name.endswith(".bak")
        )

    def read_process(self, name: str) -> dict:
        path = self._process_path(name)
        if not path.exists():
            raise FileNotFoundError(f"Process profile not found: {path}")
        return json.loads(path.read_text())

    def write_process(self, name: str, data: dict) -> None:
        self._atomic_write(self._process_path(name), data)

    def rollback_process(self, name: str) -> None:
        path = self._process_path(name)
        bak = path.with_suffix(".json.bak")
        if not bak.exists():
            raise FileNotFoundError(f"No backup found for process profile: {name}")
        os.replace(bak, path)

    def list_process_profiles(self) -> list[str]:
        return sorted(
            p.stem
            for p in self.process_dir.glob("*.json")
            if not p.name.endswith(".bak")
        )

    def profile_diff(self, original: dict, updated: dict) -> dict[str, tuple]:
        """Return {key: (old_value, new_value)} for any changed, added, or removed keys."""
        all_keys = original.keys() | updated.keys()
        return {
            k: (original.get(k), updated.get(k))
            for k in all_keys
            if original.get(k) != updated.get(k)
        }
