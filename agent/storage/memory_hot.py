from __future__ import annotations

from pathlib import Path

MAX_LINES = 200
MAX_BYTES = 25_000
_WARNING = "[WARNING: memory index truncated, some entries not loaded]\n"


class MemoryHotLayer:
    def __init__(self, memories_dir: str | Path):
        self.index_path = Path(memories_dir) / "MEMORY.md"

    def load(self) -> str:
        if not self.index_path.exists():
            return ""
        text = self.index_path.read_text(encoding="utf-8")
        if not text.strip():
            return ""
        return _truncate(text)


def _truncate(text: str) -> str:
    lines = text.splitlines(keepends=True)
    truncated = False

    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES]
        truncated = True

    result = "".join(lines)
    encoded = result.encode("utf-8")
    if len(encoded) > MAX_BYTES:
        cut = encoded[:MAX_BYTES].rfind(b"\n")
        if cut < 0:
            cut = MAX_BYTES
        result = encoded[: cut + 1].decode("utf-8", errors="replace")
        truncated = True

    if truncated:
        result = result.rstrip("\n") + "\n" + _WARNING
    return result
