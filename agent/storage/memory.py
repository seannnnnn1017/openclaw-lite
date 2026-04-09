from __future__ import annotations

import json
from pathlib import Path

try:
    from storage.memory_hot import MemoryHotLayer
    from storage.memory_cold import MemoryColdWriter
    from storage.memory_warm import MemoryWarmSelector
    from storage.memory_writer import MemoryWriter
except ImportError:
    from agent.storage.memory_hot import MemoryHotLayer
    from agent.storage.memory_cold import MemoryColdWriter
    from agent.storage.memory_warm import MemoryWarmSelector
    from agent.storage.memory_writer import MemoryWriter


class MemoryCoordinator:
    """Three-tier memory coordinator: Hot (MEMORY.md) / Warm (topic files) / Cold (.jsonl transcripts)."""

    def __init__(self, *, config, client, display=None, debug_logger=None):
        memories_dir = Path(getattr(config, "memory_store_path", "agent/data/memories"))
        self.enabled = bool(getattr(config, "memory_enabled", True))
        self._hot = MemoryHotLayer(memories_dir)
        self._warm = MemoryWarmSelector(memories_dir, client, config)
        self._cold = MemoryColdWriter(memories_dir)
        self._writer = MemoryWriter(memories_dir)
        self._display = display
        self._debug_logger = debug_logger

    def start_session(self) -> None:
        if self.enabled:
            self._cold.start_session()

    def build_hot_message(self) -> str:
        if not self.enabled:
            return ""
        return self._hot.load()

    def build_warm_message(self, user_input: str, active_skills: list[str]) -> tuple[str, list[str]]:
        if not self.enabled:
            return "", []
        return self._warm.select_and_load(user_input, active_skills)

    def append_turn(self, user_input: str, assistant_response: str) -> None:
        if self.enabled:
            self._cold.append_turn(user_input, assistant_response)

    def handle_memory_command(self, command: dict) -> str:
        op = str(command.get("memory", "")).strip()
        if op == "write":
            result = self._writer.write(command)
            if self._display and result.get("status") == "ok":
                try:
                    self._display.memory(f"wrote {result.get('file', '')}")
                except Exception:
                    pass
            return json.dumps(result, ensure_ascii=False)
        if op == "search":
            return self._writer.search(command)
        return json.dumps({"status": "error", "error": f"unknown memory op: {op}"}, ensure_ascii=False)

    def stats(self) -> dict:
        return {"enabled": self.enabled}


# ---------------------------------------------------------------------------
# Backwards-compat alias so existing imports don't break during migration
# ---------------------------------------------------------------------------
LongTermMemoryManager = MemoryCoordinator
