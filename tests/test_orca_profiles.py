import json
import pytest
from pathlib import Path
from tools.orca_profiles import OrcaProfiles


@pytest.fixture
def profile_dir(tmp_path):
    filament_dir = tmp_path / "filament"
    process_dir = tmp_path / "process"
    filament_dir.mkdir()
    process_dir.mkdir()

    filament_profile = {
        "name": "ELEGOO PLA+ High Speed",
        "nozzle_temperature": ["225"],
        "hot_plate_temp": ["60"],
        "from": "User",
        "inherits": "Generic PLA High Speed @System",
    }
    (filament_dir / "ELEGOO PLA+ High Speed.json").write_text(json.dumps(filament_profile))

    process_profile = {
        "name": "0.20mm Standard @Flashforge AD5M Pro 0.4 Nozzle",
        "wall_loops": "5",
        "sparse_infill_pattern": "gyroid",
        "from": "User",
    }
    (process_dir / "0.20mm Standard @Flashforge AD5M Pro 0.4 Nozzle.json").write_text(
        json.dumps(process_profile)
    )
    return tmp_path


def test_read_filament_profile(profile_dir):
    op = OrcaProfiles(profile_dir)
    profile = op.read_filament("ELEGOO PLA+ High Speed")
    assert profile["nozzle_temperature"] == ["225"]
    assert profile["hot_plate_temp"] == ["60"]


def test_read_nonexistent_profile_raises(profile_dir):
    op = OrcaProfiles(profile_dir)
    with pytest.raises(FileNotFoundError, match="Filament profile not found"):
        op.read_filament("Nonexistent Filament")


def test_write_filament_profile_creates_backup(profile_dir):
    op = OrcaProfiles(profile_dir)
    original = op.read_filament("ELEGOO PLA+ High Speed")
    original["nozzle_temperature"] = ["227"]
    op.write_filament("ELEGOO PLA+ High Speed", original)

    # Backup must exist
    bak = profile_dir / "filament" / "ELEGOO PLA+ High Speed.json.bak"
    assert bak.exists()

    # Original backup has old value
    bak_data = json.loads(bak.read_text())
    assert bak_data["nozzle_temperature"] == ["225"]

    # New file has updated value
    updated = op.read_filament("ELEGOO PLA+ High Speed")
    assert updated["nozzle_temperature"] == ["227"]


def test_rollback_restores_backup(profile_dir):
    op = OrcaProfiles(profile_dir)
    original = op.read_filament("ELEGOO PLA+ High Speed")
    original["nozzle_temperature"] = ["230"]
    op.write_filament("ELEGOO PLA+ High Speed", original)

    op.rollback_filament("ELEGOO PLA+ High Speed")
    restored = op.read_filament("ELEGOO PLA+ High Speed")
    assert restored["nozzle_temperature"] == ["225"]


def test_rollback_raises_when_no_backup(profile_dir):
    op = OrcaProfiles(profile_dir)
    with pytest.raises(FileNotFoundError, match="No backup found"):
        op.rollback_filament("ELEGOO PLA+ High Speed")


def test_list_filament_profiles(profile_dir):
    op = OrcaProfiles(profile_dir)
    profiles = op.list_filament_profiles()
    assert "ELEGOO PLA+ High Speed" in profiles


def test_read_process_profile(profile_dir):
    op = OrcaProfiles(profile_dir)
    profile = op.read_process("0.20mm Standard @Flashforge AD5M Pro 0.4 Nozzle")
    assert profile["wall_loops"] == "5"
    assert profile["sparse_infill_pattern"] == "gyroid"


def test_write_process_profile_creates_backup(profile_dir):
    op = OrcaProfiles(profile_dir)
    original = op.read_process("0.20mm Standard @Flashforge AD5M Pro 0.4 Nozzle")
    original["wall_loops"] = "4"
    op.write_process("0.20mm Standard @Flashforge AD5M Pro 0.4 Nozzle", original)

    bak = profile_dir / "process" / "0.20mm Standard @Flashforge AD5M Pro 0.4 Nozzle.json.bak"
    assert bak.exists()
    bak_data = json.loads(bak.read_text())
    assert bak_data["wall_loops"] == "5"
