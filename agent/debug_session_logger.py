import json
import os
import threading
from datetime import datetime
from pathlib import Path


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _normalize_value(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        head = value[:128]
        if head.startswith("data:") and ";base64," in head:
            return f"<data-url omitted chars={len(value)}>"
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _normalize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_normalize_value(item) for item in value]
    return str(value)


class DebugSessionLogger:
    def __init__(self, root_dir: str | Path):
        self.root_dir = Path(root_dir).expanduser().resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        self.path = self.root_dir / f"session_{timestamp}_{os.getpid()}.jsonl"
        self._lock = threading.Lock()
        self._sequence = 0

    def log_event(self, kind: str, **payload):
        entry = {
            "seq": 0,
            "ts": _now_iso(),
            "kind": str(kind or "").strip() or "unknown",
            "payload": _normalize_value(payload),
        }
        with self._lock:
            self._sequence += 1
            entry["seq"] = self._sequence
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
