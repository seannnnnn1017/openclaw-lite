from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path


class MemoryColdWriter:
    def __init__(self, memories_dir: str | Path):
        self._transcripts_dir = Path(memories_dir) / "transcripts"
        self._session_file: Path | None = None
        self._lock = threading.Lock()

    def start_session(self) -> None:
        self._transcripts_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        self._session_file = self._transcripts_dir / f"session-{ts}.jsonl"
        self._session_file.touch()

    def append_turn(self, user_input: str, assistant_response: str) -> None:
        if not self._session_file:
            return
        path = self._session_file
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        lines = (
            json.dumps({"ts": ts, "role": "user", "content": str(user_input or "")}, ensure_ascii=False)
            + "\n"
            + json.dumps({"ts": ts, "role": "assistant", "content": str(assistant_response or "")}, ensure_ascii=False)
            + "\n"
        )

        def _write() -> None:
            with self._lock:
                with path.open("a", encoding="utf-8") as f:
                    f.write(lines)

        threading.Thread(target=_write, daemon=True).start()
