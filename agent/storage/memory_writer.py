from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class MemoryWriter:
    def __init__(self, memories_dir: str | Path):
        self._memories_dir = Path(memories_dir)
        self._topics_dir = self._memories_dir / "topics"
        self._index_path = self._memories_dir / "MEMORY.md"

    def write(self, command: dict) -> dict:
        filename = str(command.get("file", "")).strip()
        skill = str(command.get("skill") or "null").strip()
        title = str(command.get("title", "")).strip()
        tags = command.get("tags", [])
        content = str(command.get("content", "")).strip()

        if not filename or not content:
            return {"status": "error", "error": "file and content are required"}

        # Strip any directory prefix — file must be a plain filename inside topics/
        filename = Path(filename).name

        self._topics_dir.mkdir(parents=True, exist_ok=True)
        topic_path = self._topics_dir / filename
        today = datetime.now().strftime("%Y-%m-%d")
        tag_str = ", ".join(str(t) for t in (tags if isinstance(tags, list) else []))
        frontmatter = (
            "---\n"
            f"title: {title}\n"
            f"tags: [{tag_str}]\n"
            f"skill: {skill}\n"
            f"updated: {today}\n"
            "---\n\n"
        )
        topic_path.write_text(frontmatter + content + "\n", encoding="utf-8")
        self._update_index(filename=filename, skill=skill, title=title, updated=today)
        return {"status": "ok", "file": filename}

    def search(self, command: dict) -> str:
        query = str(command.get("query", "")).strip()
        try:
            limit = max(1, int(command.get("limit", 20)))
        except (TypeError, ValueError):
            limit = 20

        if not query:
            return "No query provided."

        transcripts_dir = self._memories_dir / "transcripts"
        if not transcripts_dir.exists():
            return "No transcripts found."

        results: list[str] = []
        for jsonl_file in sorted(transcripts_dir.glob("*.jsonl")):
            lines = jsonl_file.read_text(encoding="utf-8").splitlines()
            for i, line in enumerate(lines):
                if query.casefold() not in line.casefold():
                    continue
                start = max(0, i - 2)
                end = min(len(lines), i + 3)
                formatted = []
                for ctx in lines[start:end]:
                    try:
                        entry = json.loads(ctx)
                        formatted.append(f"{entry['role']}: {entry['content'][:200]}")
                    except Exception:
                        formatted.append(ctx[:200])
                results.append(f"[{jsonl_file.name} | line {i + 1}]\n" + "\n".join(formatted))
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break

        if not results:
            return f"No matches found for '{query}'."
        return "\n\n".join(results)

    def _update_index(self, *, filename: str, skill: str, title: str, updated: str) -> None:
        existing: list[str] = []
        if self._index_path.exists():
            existing = self._index_path.read_text(encoding="utf-8").splitlines(keepends=True)

        new_line = f"- [{filename}] skill:{skill} | updated:{updated} | {title}\n"
        updated_lines: list[str] = []
        found = False
        for line in existing:
            if f"[{filename}]" in line:
                updated_lines.append(new_line)
                found = True
            else:
                updated_lines.append(line)
        if not found:
            updated_lines.append(new_line)

        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        self._index_path.write_text("".join(updated_lines), encoding="utf-8")
