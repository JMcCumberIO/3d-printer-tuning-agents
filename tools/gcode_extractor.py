import zipfile
from pathlib import Path
from typing import Optional


class GcodeExtractor:
    THUMBNAIL_PATHS = ["Metadata/thumbnail.png", "Thumbnails/thumbnail.png"]
    GCODE_EXTENSIONS = (".gcode",)

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def list_contents(self) -> list[str]:
        with zipfile.ZipFile(self.path) as zf:
            return zf.namelist()

    def extract_gcode(self) -> bytes:
        with zipfile.ZipFile(self.path) as zf:
            for name in zf.namelist():
                if any(name.endswith(ext) for ext in self.GCODE_EXTENSIONS):
                    return zf.read(name)
        raise FileNotFoundError(f"No gcode found in {self.path}")

    def extract_gcode_to_file(self, dest: str | Path) -> Path:
        dest = Path(dest)
        dest.write_bytes(self.extract_gcode())
        return dest

    def extract_thumbnail(self) -> Optional[bytes]:
        with zipfile.ZipFile(self.path) as zf:
            names = zf.namelist()
            for candidate in self.THUMBNAIL_PATHS:
                if candidate in names:
                    return zf.read(candidate)
        return None

    def gcode_path_in_archive(self) -> Optional[str]:
        with zipfile.ZipFile(self.path) as zf:
            for name in zf.namelist():
                if any(name.endswith(ext) for ext in self.GCODE_EXTENSIONS):
                    return name
        return None
