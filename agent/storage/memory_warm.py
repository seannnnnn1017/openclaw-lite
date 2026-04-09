from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

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

    def select_and_load(self, user_input: str, active_skills: list[str]) -> tuple[str, list[str]]:
        if not self._index_path.exists() or not self._topics_dir.exists():
            return "", []
        index_content = self._index_path.read_text(encoding="utf-8").strip()
        if not index_content:
            return "", []
        available = [f.name for f in self._topics_dir.glob("*.md")]
        if not available:
            return "", []

        selected = self._call_selector(index_content, user_input, active_skills, available)
        if not selected:
            return "", []

        parts: list[str] = []
        loaded: list[str] = []
        for filename in selected:
            path = self._topics_dir / filename
            if path.exists():
                parts.append(path.read_text(encoding="utf-8").strip())
                loaded.append(filename)
        content = "\n\n---\n\n".join(parts) if parts else ""
        return content, loaded

    def _native_chat_url(self) -> str:
        """Derive LM Studio native /api/v1/chat URL from the configured base_url."""
        base = str(getattr(self._config, "base_url", "http://localhost:1234/v1")).rstrip("/")
        # base_url is typically http://host:port/v1 — strip the /v1 suffix
        if base.endswith("/v1"):
            return base[:-3] + "/api/v1/chat"
        # Fallback: replace last /v1 occurrence
        return re.sub(r"/v1(/.*)?$", "/api/v1/chat", base)

    def _call_selector(
        self,
        index: str,
        user_input: str,
        active_skills: list[str],
        available: list[str],
    ) -> list[str]:
        skills_str = ", ".join(active_skills) if active_skills else "none"
        # Combine system + user into a single input string for the native endpoint
        combined_input = (
            f"{_SELECTOR_SYSTEM}\n\n"
            f"Currently active skills: {skills_str}\n"
            f"Available files: {json.dumps(available)}\n\n"
            f"Memory index:\n{index}\n\n"
            f"User message: {str(user_input or '')[:400]}"
        )
        extractor_model = (
            str(getattr(self._config, "memory_extractor_model", "") or "").strip()
            or self._config.model
        )
        payload = {
            "model": extractor_model,
            "input": combined_input,
            "temperature": 0.0,
            "max_output_tokens": 256,
            "reasoning": "off",
        }
        try:
            req = urllib.request.Request(
                self._native_chat_url(),
                data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                response = json.loads(resp.read().decode("utf-8"))

            # Extract text from output[].content (native LM Studio response format)
            raw = ""
            for item in response.get("output", []):
                if isinstance(item, dict) and item.get("type") == "message":
                    raw = str(item.get("content") or "").strip()
                    if raw:
                        break

            # Parse JSON array — no think-block stripping needed with reasoning=off
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                matches = list(re.finditer(r'\[.*?\]', raw, re.DOTALL))
                parsed = json.loads(matches[-1].group()) if matches else []

            if isinstance(parsed, list):
                return [str(f) for f in parsed if isinstance(f, str) and f in available][: self.max_files]
        except Exception:
            pass
        return []
