import io
import zipfile
import pytest
from pathlib import Path
from tools.gcode_extractor import GcodeExtractor


@pytest.fixture
def fake_3mf(tmp_path) -> Path:
    """Build a minimal .3mf ZIP with gcode and thumbnail."""
    path = tmp_path / "test_model.3mf"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Metadata/thumbnail.png", b"FAKEPNG")
        zf.writestr("Metadata/plate_1.gcode", b"; gcode start\nG28\nG1 X10 Y10\n")
        zf.writestr("3D/3dmodel.model", b"<model/>")
    return path


@pytest.fixture
def fake_3mf_no_gcode(tmp_path) -> Path:
    path = tmp_path / "no_gcode.3mf"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("3D/3dmodel.model", b"<model/>")
    return path


def test_extract_gcode_returns_bytes(fake_3mf):
    ex = GcodeExtractor(fake_3mf)
    gcode = ex.extract_gcode()
    assert b"G28" in gcode


def test_extract_thumbnail_returns_bytes(fake_3mf):
    ex = GcodeExtractor(fake_3mf)
    thumb = ex.extract_thumbnail()
    assert thumb == b"FAKEPNG"


def test_extract_gcode_raises_when_missing(fake_3mf_no_gcode):
    ex = GcodeExtractor(fake_3mf_no_gcode)
    with pytest.raises(FileNotFoundError, match="No gcode found"):
        ex.extract_gcode()


def test_extract_thumbnail_returns_none_when_missing(fake_3mf_no_gcode):
    ex = GcodeExtractor(fake_3mf_no_gcode)
    assert ex.extract_thumbnail() is None


def test_list_contents(fake_3mf):
    ex = GcodeExtractor(fake_3mf)
    contents = ex.list_contents()
    assert "Metadata/plate_1.gcode" in contents
    assert "Metadata/thumbnail.png" in contents


def test_extract_gcode_to_file(fake_3mf, tmp_path):
    ex = GcodeExtractor(fake_3mf)
    out = tmp_path / "output.gcode"
    ex.extract_gcode_to_file(out)
    assert out.exists()
    assert b"G28" in out.read_bytes()
