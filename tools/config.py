import os
from pathlib import Path
import yaml
from dotenv import load_dotenv

load_dotenv()

_config_path = Path(__file__).parent.parent / "config.yaml"


def get_config() -> dict:
    with open(_config_path) as f:
        config = yaml.safe_load(f)

    urls = [
        os.getenv("HA_URL_PRIMARY", ""),
        os.getenv("HA_URL_FALLBACK", ""),
        os.getenv("HA_URL_CLOUD", ""),
    ]
    config["ha"]["urls"] = [u for u in urls if u]
    config["ha"]["token"] = os.getenv("HA_TOKEN", "")
    config["ha"]["verify_ssl"] = os.getenv("HA_VERIFY_SSL", "false").lower() == "true"

    config["orca_profile_dir"] = os.path.expanduser(
        os.getenv("ORCA_PROFILE_DIR", "~/.config/OrcaSlicer/user/default")
    )
    config["active_filament"] = os.getenv("ACTIVE_FILAMENT", "")
    config["active_nozzle"] = os.getenv("ACTIVE_NOZZLE", "0.4mm")
    return config
