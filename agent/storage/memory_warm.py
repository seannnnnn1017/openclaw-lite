from __future__ import annotations

import json
from pathlib import Path

try:
    from core.schemas import ChatRequest, Message
except ImportError:
    from agent.core.schemas import ChatRequest, Message

_SELECTOR_SYSTEM = """\
You are selecting memory files to load for an AI agent.
Return a JSON array of up to 5 filenames that are most relevant to the user message.

Rules:
- If a skill is listed as active, skip its general API/usage documentation files.
- Always select files that contain warnings, traps, or known issues (gotchas).
- Prefer files whose `skill:` field matches an active skill.
- Return ONLY a valid JSON array of filename strings, nothing else.
"""


class MemoryWarmSelector:
    def __init__(self, memories_dir: str | Path, client, config):
        self._topics_dir = Path(memories_dir) / "topics"
        self._index_path = Path(memories_dir) / "MEMORY.md"
        self._client = client
        self._config = config
        self.max_files = 5

    def select_and_load(self, user_input: str, active_skills: list[str]) -> str:
        if not self._index_path.exists() or not self._topics_dir.exists():
            return ""
        index_content = self._index_path.read_text(encoding="utf-8").strip()
        if not index_content:
            return ""
        available = [f.name for f in self._topics_dir.glob("*.md")]
        if not available:
            return ""

        selected = self._call_selector(index_content, user_input, active_skills, available)
        if not selected:
            return ""

        parts: list[str] = []
        for filename in selected:
            path = self._topics_dir / filename
            if path.exists():
                parts.append(path.read_text(encoding="utf-8").strip())
        return "\n\n---\n\n".join(parts) if parts else ""

    def _call_selector(
        self,
        index: str,
        user_input: str,
        active_skills: list[str],
        available: list[str],
    ) -> list[str]:
        skills_str = ", ".join(active_skills) if active_skills else "none"
        user_prompt = (
            f"Currently active skills: {skills_str}\n"
            f"Available files: {json.dumps(available)}\n\n"
            f"Memory index:\n{index}\n\n"
            f"User message: {str(user_input or '')[:400]}"
        )
        request = ChatRequest(
            model=self._config.model,
            messages=[
                Message(role="system", content=_SELECTOR_SYSTEM),
                Message(role="user", content=user_prompt),
            ],
            temperature=0.0,
            max_tokens=200,
            stream=False,
        )
        try:
            response = self._client.chat(request)
            parsed = json.loads(response.strip())
            if isinstance(parsed, list):
                return [str(f) for f in parsed if isinstance(f, str) and f in available][: self.max_files]
        except Exception:
            pass
        return []
