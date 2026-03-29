import json
from pathlib import Path


AGENT_ROOT = Path(__file__).resolve().parent.parent
SYSTEM_DIR = AGENT_ROOT / "data" / "system"
SECRET_CONFIG_PATH = SYSTEM_DIR / "secrets.local.json"
SECRET_EXAMPLE_PATH = SYSTEM_DIR / "secrets.example.json"


def load_secret_config() -> dict:
    if not SECRET_CONFIG_PATH.exists():
        return {}

    try:
        data = json.loads(SECRET_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    return data if isinstance(data, dict) else {}
