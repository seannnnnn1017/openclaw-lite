# Three-Tier Memory System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the existing JSON-based long-term memory system with a Hot/Warm/Cold three-tier architecture.

**Architecture:** Hot layer always injects MEMORY.md index into system prompt; Warm layer uses a small LLM call to select up to 5 topic `.md` files per turn; Cold layer appends every turn to a per-session `.jsonl` for grep search. Writing is triggered inline by the main model via `{"memory":"write",...}` commands — background extraction LLM calls are removed entirely.

**Tech Stack:** Python 3.11+, pathlib, threading, json, pytest, existing LMStudioClient + ChatRequest/Message schemas

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `agent/storage/memory_hot.py` | Read + truncate MEMORY.md, return string for injection |
| Create | `agent/storage/memory_cold.py` | Session `.jsonl` creation + async append per turn |
| Create | `agent/storage/memory_writer.py` | Handle `memory.write` and `memory.search` commands |
| Create | `agent/storage/memory_warm.py` | Small-model topic file selector + loader |
| Modify | `agent/storage/memory.py` | Replace body with `MemoryCoordinator` facade; remove extraction classes |
| Modify | `agent/core/agent.py` | Wire coordinator, add memory-command detection, replace remember_turn |
| Modify | `agent/app/application.py` | Call `coordinator.start_session()` at terminal startup |
| Create | `tests/storage/__init__.py` | Empty init |
| Create | `tests/storage/test_memory_hot.py` | MemoryHotLayer tests |
| Create | `tests/storage/test_memory_cold.py` | MemoryColdWriter tests |
| Create | `tests/storage/test_memory_writer.py` | MemoryWriter tests |
| Create | `agent/data/memories/MEMORY.md` | Initial hot-layer index (migration) |
| Create | `agent/data/memories/topics/notification-workflow.md` | Migrated memory (migration) |

---

## Task 1: MemoryHotLayer

**Files:**
- Create: `agent/storage/memory_hot.py`
- Create: `tests/storage/__init__.py`
- Create: `tests/storage/test_memory_hot.py`

- [ ] **Step 1: Create test file**

```python
# tests/storage/__init__.py
# (empty)
```

```python
# tests/storage/test_memory_hot.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest
from agent.storage.memory_hot import MemoryHotLayer

MAX_LINES = 200
MAX_BYTES = 25_000
WARNING = "[WARNING: memory index truncated, some entries not loaded]"


def test_missing_file_returns_empty(tmp_path):
    layer = MemoryHotLayer(tmp_path)
    assert layer.load() == ""


def test_empty_file_returns_empty(tmp_path):
    (tmp_path / "MEMORY.md").write_text("   \n", encoding="utf-8")
    layer = MemoryHotLayer(tmp_path)
    assert layer.load() == ""


def test_normal_content_returned_as_is(tmp_path):
    content = "- [file.md] skill:null | updated:2026-01-01 | desc\n"
    (tmp_path / "MEMORY.md").write_text(content, encoding="utf-8")
    layer = MemoryHotLayer(tmp_path)
    assert layer.load() == content


def test_truncates_at_200_lines(tmp_path):
    lines = [f"- [f{i}.md] skill:null | updated:2026-01-01 | desc {i}\n" for i in range(210)]
    (tmp_path / "MEMORY.md").write_text("".join(lines), encoding="utf-8")
    layer = MemoryHotLayer(tmp_path)
    result = layer.load()
    assert result.count("\n") <= MAX_LINES + 2  # content lines + WARNING line
    assert WARNING in result
    assert "desc 200" not in result  # line 201+ truncated


def test_truncates_at_25kb(tmp_path):
    # ~200 chars per line × 130 lines ≈ 26KB
    lines = [f"- [f{i}.md] skill:null | updated:2026-01-01 | {'x' * 160}\n" for i in range(130)]
    (tmp_path / "MEMORY.md").write_text("".join(lines), encoding="utf-8")
    layer = MemoryHotLayer(tmp_path)
    result = layer.load()
    assert len(result.encode("utf-8")) <= MAX_BYTES + 300  # allow for WARNING text
    assert WARNING in result


def test_truncation_does_not_cut_mid_line(tmp_path):
    lines = [f"- [f{i}.md] skill:null | updated:2026-01-01 | {'x' * 160}\n" for i in range(130)]
    (tmp_path / "MEMORY.md").write_text("".join(lines), encoding="utf-8")
    layer = MemoryHotLayer(tmp_path)
    result = layer.load()
    # Every line before WARNING must start with "- ["
    content_lines = result.split(WARNING)[0].splitlines()
    for line in content_lines:
        stripped = line.strip()
        if stripped:
            assert stripped.startswith("- ["), f"Mid-line cut detected: {stripped[:60]}"
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd E:/重要文件/openclaw-lite
python -m pytest tests/storage/test_memory_hot.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` (file doesn't exist yet)

- [ ] **Step 3: Create `agent/storage/memory_hot.py`**

```python
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
        if cut <= 0:
            cut = MAX_BYTES
        result = encoded[: cut + 1].decode("utf-8", errors="replace")
        truncated = True

    if truncated:
        result = result.rstrip("\n") + "\n" + _WARNING
    return result
```

- [ ] **Step 4: Run tests to confirm they pass**

```
python -m pytest tests/storage/test_memory_hot.py -v
```

Expected: all 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agent/storage/memory_hot.py tests/storage/__init__.py tests/storage/test_memory_hot.py
git commit -m "feat: add MemoryHotLayer with 200-line/25KB truncation"
```

---

## Task 2: MemoryColdWriter

**Files:**
- Create: `agent/storage/memory_cold.py`
- Create: `tests/storage/test_memory_cold.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/storage/test_memory_cold.py
import sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest
from agent.storage.memory_cold import MemoryColdWriter


def test_start_session_creates_file(tmp_path):
    writer = MemoryColdWriter(tmp_path)
    writer.start_session()
    transcripts = list((tmp_path / "transcripts").glob("session-*.jsonl"))
    assert len(transcripts) == 1
    assert transcripts[0].stat().st_size == 0  # empty on creation


def test_append_turn_writes_two_lines(tmp_path):
    writer = MemoryColdWriter(tmp_path)
    writer.start_session()
    writer.append_turn("hello", "hi there")
    time.sleep(0.1)  # allow async write
    files = list((tmp_path / "transcripts").glob("session-*.jsonl"))
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    user_entry = json.loads(lines[0])
    assistant_entry = json.loads(lines[1])
    assert user_entry["role"] == "user"
    assert user_entry["content"] == "hello"
    assert assistant_entry["role"] == "assistant"
    assert assistant_entry["content"] == "hi there"
    assert "ts" in user_entry


def test_multiple_appends_go_to_same_file(tmp_path):
    writer = MemoryColdWriter(tmp_path)
    writer.start_session()
    writer.append_turn("msg1", "reply1")
    writer.append_turn("msg2", "reply2")
    time.sleep(0.2)
    files = list((tmp_path / "transcripts").glob("session-*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 4


def test_append_without_start_session_is_noop(tmp_path):
    writer = MemoryColdWriter(tmp_path)
    writer.append_turn("hello", "hi")  # no start_session called
    time.sleep(0.1)
    assert not (tmp_path / "transcripts").exists()
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/storage/test_memory_cold.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `agent/storage/memory_cold.py`**

```python
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
```

- [ ] **Step 4: Run tests to confirm they pass**

```
python -m pytest tests/storage/test_memory_cold.py -v
```

Expected: all 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agent/storage/memory_cold.py tests/storage/test_memory_cold.py
git commit -m "feat: add MemoryColdWriter for per-session transcript append"
```

---

## Task 3: MemoryWriter (write + search)

**Files:**
- Create: `agent/storage/memory_writer.py`
- Create: `tests/storage/test_memory_writer.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/storage/test_memory_writer.py
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest
from agent.storage.memory_writer import MemoryWriter


def test_write_creates_new_topic_file(tmp_path):
    writer = MemoryWriter(tmp_path)
    result = writer.write({
        "memory": "write",
        "file": "schedule-gotchas.md",
        "skill": "schedule-task",
        "title": "排程陷阱",
        "tags": ["scheduler", "gotcha"],
        "content": "## 相對時間\n需先呼叫 time-query.now",
    })
    assert result["status"] == "ok"
    topic = (tmp_path / "topics" / "schedule-gotchas.md")
    assert topic.exists()
    text = topic.read_text(encoding="utf-8")
    assert "skill: schedule-task" in text
    assert "排程陷阱" in text
    assert "相對時間" in text


def test_write_creates_index_entry(tmp_path):
    writer = MemoryWriter(tmp_path)
    writer.write({
        "memory": "write",
        "file": "prefs.md",
        "skill": "null",
        "title": "User prefs",
        "tags": [],
        "content": "繁體中文",
    })
    index = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "[prefs.md]" in index
    assert "skill:null" in index
    assert "User prefs" in index


def test_write_updates_existing_entry(tmp_path):
    writer = MemoryWriter(tmp_path)
    writer.write({"memory": "write", "file": "prefs.md", "skill": "null", "title": "Old title", "tags": [], "content": "v1"})
    writer.write({"memory": "write", "file": "prefs.md", "skill": "null", "title": "New title", "tags": [], "content": "v2"})
    index = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert index.count("[prefs.md]") == 1  # no duplicate
    assert "New title" in index
    assert "Old title" not in index


def test_write_missing_required_fields_returns_error(tmp_path):
    writer = MemoryWriter(tmp_path)
    result = writer.write({"memory": "write", "file": "", "content": ""})
    assert result["status"] == "error"


def test_search_finds_matching_lines(tmp_path):
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    session = transcripts / "session-20260407-120000.jsonl"
    entries = [
        {"ts": "2026-04-07T12:00:00+08:00", "role": "user", "content": "notion webhook 問題"},
        {"ts": "2026-04-07T12:00:01+08:00", "role": "assistant", "content": "根本原因是 polling 延遲"},
    ]
    session.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")

    writer = MemoryWriter(tmp_path)
    result = writer.search({"memory": "search", "query": "notion webhook", "limit": 10})
    assert "notion webhook" in result
    assert "session-20260407-120000.jsonl" in result


def test_search_no_match_returns_message(tmp_path):
    (tmp_path / "transcripts").mkdir()
    writer = MemoryWriter(tmp_path)
    result = writer.search({"memory": "search", "query": "nonexistent_xyz", "limit": 5})
    assert "No matches" in result


def test_search_no_transcripts_dir(tmp_path):
    writer = MemoryWriter(tmp_path)
    result = writer.search({"memory": "search", "query": "anything", "limit": 5})
    assert "No transcripts" in result
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/storage/test_memory_writer.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `agent/storage/memory_writer.py`**

```python
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
        limit = max(1, int(command.get("limit", 20)))

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
```

- [ ] **Step 4: Run tests to confirm they pass**

```
python -m pytest tests/storage/test_memory_writer.py -v
```

Expected: all 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agent/storage/memory_writer.py tests/storage/test_memory_writer.py
git commit -m "feat: add MemoryWriter for topic file writes and transcript search"
```

---

## Task 4: MemoryWarmSelector

**Files:**
- Create: `agent/storage/memory_warm.py`

No unit tests for the LLM call path (requires live client). The selector is tested end-to-end in integration. We test the fallback path (no topics dir, empty index).

- [ ] **Step 1: Create `agent/storage/memory_warm.py`**

```python
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
```

- [ ] **Step 2: Verify import works**

```
python -c "from agent.storage.memory_warm import MemoryWarmSelector; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add agent/storage/memory_warm.py
git commit -m "feat: add MemoryWarmSelector for small-model topic file selection"
```

---

## Task 5: MemoryCoordinator Facade

Replace `agent/storage/memory.py` body with a `MemoryCoordinator` that wires all four components. The old `LongTermMemoryManager` and `LongTermMemoryStore` classes are removed.

**Files:**
- Modify: `agent/storage/memory.py`

- [ ] **Step 1: Rewrite `agent/storage/memory.py`**

Keep the file path the same so existing imports (`from agent.storage.memory import LongTermMemoryManager`) still resolve (we'll update call sites next task — for now we rename the class).

```python
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
        memories_dir = Path(getattr(config, "memory_store_path", "")).parent
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

    def build_warm_message(self, user_input: str, active_skills: list[str]) -> str:
        if not self.enabled:
            return ""
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
```

- [ ] **Step 2: Verify import**

```
python -c "from agent.storage.memory import MemoryCoordinator; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add agent/storage/memory.py
git commit -m "refactor: replace LongTermMemoryManager with MemoryCoordinator facade"
```

---

## Task 6: Integrate into `agent/core/agent.py`

**Files:**
- Modify: `agent/core/agent.py`

Four changes:
1. Import `MemoryCoordinator` instead of `LongTermMemoryManager`
2. `__init__`: replace `memory_manager` with `memory_coordinator`, call `start_session()`
3. `_build_base_messages`: inject hot + warm layers
4. `run()`: add memory command detection before skill-call check; replace `remember_turn` with `append_turn`

- [ ] **Step 1: Update import at top of `agent/core/agent.py`**

Find (line ~16-26):
```python
    from core.token_estimator import summarize_prompt_and_history
    from storage.memory import LongTermMemoryManager
except ImportError:
    from agent.skill.auto_context import collect_auto_context_messages
    from agent.skill.delegated_executor import DelegatedSkillExecutor
    from agent.integrations.lmstudio import LMStudioClient
    from agent.core.schemas import Message, ChatRequest
    from agent.skill.client import SkillClient
    from agent.utils.terminal_display import TerminalDisplay
    from agent.core.token_estimator import summarize_prompt_and_history
    from agent.storage.memory import LongTermMemoryManager
```

Replace both `LongTermMemoryManager` import lines:
```python
    from core.token_estimator import summarize_prompt_and_history
    from storage.memory import MemoryCoordinator
except ImportError:
    from agent.skill.auto_context import collect_auto_context_messages
    from agent.skill.delegated_executor import DelegatedSkillExecutor
    from agent.integrations.lmstudio import LMStudioClient
    from agent.core.schemas import Message, ChatRequest
    from agent.skill.client import SkillClient
    from agent.utils.terminal_display import TerminalDisplay
    from agent.core.token_estimator import summarize_prompt_and_history
    from agent.storage.memory import MemoryCoordinator
```

- [ ] **Step 2: Update `__init__` in `SimpleAgent`**

Find (lines ~38-44):
```python
        self.memory_manager = LongTermMemoryManager(
            config=config,
            client=client,
            display=self.display,
            debug_logger=debug_logger,
        )
```

Replace with:
```python
        self.memory_coordinator = MemoryCoordinator(
            config=config,
            client=client,
            display=self.display,
            debug_logger=debug_logger,
        )
        self.memory_coordinator.start_session()
```

- [ ] **Step 3: Update `long_term_memory_summary` method**

Find (line ~212):
```python
    def long_term_memory_summary(self) -> dict:
        return self.memory_manager.stats()
```

Replace with:
```python
    def long_term_memory_summary(self) -> dict:
        return self.memory_coordinator.stats()
```

- [ ] **Step 4: Update `refresh_runtime_clients` method**

Find (lines ~224-235):
```python
        self.memory_manager = LongTermMemoryManager(
            config=self.config,
            client=self.client,
            display=self.display,
            debug_logger=self.debug_logger,
        )
```

Replace with:
```python
        self.memory_coordinator = MemoryCoordinator(
            config=self.config,
            client=self.client,
            display=self.display,
            debug_logger=self.debug_logger,
        )
        self.memory_coordinator.start_session()
```

- [ ] **Step 5: Update `_build_base_messages` to inject hot + warm layers**

Find (lines ~387-401):
```python
    def _build_base_messages(self, user_input):
        with self.history_lock:
            history_snapshot = list(self.history)
        messages = [
            Message(
                role="system",
                content=self.config.agent_layers.build_system_prompt(),
            ),
        ]
        memory_message = self.memory_manager.build_memory_message(user_input)
        if memory_message:
            messages.append(Message(role="system", content=memory_message))
        messages.extend(history_snapshot)
        messages.append(Message(role="user", content=user_input))
        return messages
```

Replace with:
```python
    def _build_base_messages(self, user_input):
        with self.history_lock:
            history_snapshot = list(self.history)
        messages = [
            Message(
                role="system",
                content=self.config.agent_layers.build_system_prompt(),
            ),
        ]
        hot_content = self.memory_coordinator.build_hot_message()
        if hot_content:
            messages.append(Message(role="system", content=hot_content))
        active_skills = [str(s.get("name", "")) for s in getattr(self.config, "skills", [])]
        warm_content = self.memory_coordinator.build_warm_message(user_input, active_skills)
        if warm_content:
            messages.append(Message(role="system", content=warm_content))
        messages.extend(history_snapshot)
        messages.append(Message(role="user", content=user_input))
        return messages
```

- [ ] **Step 6: Add `_parse_memory_command` method**

Add after `_parse_skill_call` method (around line 557):

```python
    def _parse_memory_command(self, text: str) -> dict | None:
        if not text:
            return None
        candidate = str(text).strip()
        if candidate.startswith("```") and candidate.endswith("```"):
            lines = candidate.splitlines()
            candidate = "\n".join(lines[1:-1]).strip()
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        if isinstance(payload, dict) and isinstance(payload.get("memory"), str):
            return payload
        return None
```

- [ ] **Step 7: Wire memory command detection into the run loop**

In the `run()` method, find the section right after `cleaned_response, think_blocks = self._extract_think_blocks(response)` and the think block printing, and just before `skill_call = self._parse_skill_call(...)` (around line 695).

Insert memory command check:
```python
                memory_command = self._parse_memory_command(cleaned_response or response)
                if memory_command:
                    mem_result = self.memory_coordinator.handle_memory_command(memory_command)
                    messages.append(Message(role="assistant", content=json.dumps(memory_command, ensure_ascii=False)))
                    messages.append(Message(role="user", content=f"Memory operation result:\n{mem_result}\n\nContinue answering the user."))
                    continue
```

So the block becomes:
```python
                visible_response = cleaned_response.strip()
                if not visible_response and think_blocks:
                    visible_response = "[ERROR] Model returned thoughts without a final answer"
                elif not visible_response:
                    visible_response = response.strip()
                last_response = visible_response

                memory_command = self._parse_memory_command(cleaned_response or response)
                if memory_command:
                    mem_result = self.memory_coordinator.handle_memory_command(memory_command)
                    messages.append(Message(role="assistant", content=json.dumps(memory_command, ensure_ascii=False)))
                    messages.append(Message(role="user", content=f"Memory operation result:\n{mem_result}\n\nContinue answering the user."))
                    continue

                skill_call = self._parse_skill_call(cleaned_response or response)
```

- [ ] **Step 8: Replace `remember_turn` with `append_turn`**

Find the two `self.memory_manager.remember_turn(...)` calls (around lines 738-742 and 876-880):

```python
                    self.memory_manager.remember_turn(
                        user_input=persisted_user_input,
                        assistant_response=visible_response,
                        debug_context=normalized_debug_context,
                    )
```

Replace both occurrences with:
```python
                    self.memory_coordinator.append_turn(
                        user_input=str(persisted_user_input or ""),
                        assistant_response=visible_response,
                    )
```

- [ ] **Step 9: Smoke-test the agent starts without errors**

```
python -c "
import sys; sys.path.insert(0, '.')
from agent.cfg.loader import Config
from agent.integrations.lmstudio import LMStudioClient
from agent.core.agent import SimpleAgent
print('imports ok')
"
```

Expected: `imports ok`

- [ ] **Step 10: Commit**

```bash
git add agent/core/agent.py
git commit -m "feat: integrate MemoryCoordinator into SimpleAgent, add memory command detection"
```

---

## Task 7: Start Session in `application.py`

The terminal `SimpleAgent` now calls `start_session()` in `__init__`, so the cold writer is already set up. Telegram per-chat agents do the same. No change needed in `application.py` unless it creates the agent after startup in a way that skips `__init__`.

- [ ] **Step 1: Verify no orphaned `memory_manager` references remain**

```
grep -rn "memory_manager" agent/
```

Expected: zero matches (all replaced with `memory_coordinator`)

- [ ] **Step 2: If any remain, replace them**

For each remaining `memory_manager` reference, apply the same pattern as Task 6 Steps 3-4.

- [ ] **Step 3: Commit if any fixes were needed**

```bash
git add -p
git commit -m "fix: remove remaining memory_manager references"
```

---

## Task 8: Data Migration

Create initial `MEMORY.md` and migrate the two existing `skill-memory.json` entries.

**Files:**
- Create: `agent/data/memories/MEMORY.md`
- Create: `agent/data/memories/topics/notification-workflow.md`

- [ ] **Step 1: Create `agent/data/memories/topics/notification-workflow.md`**

```markdown
---
title: 通知排程偏好設定
tags: [notification, scheduler, workflow, explicit-memory]
skill: null
updated: 2026-04-07
---

## 規則

所有「傳訊息給我」、「叫醒提醒」等個人通知任務，一律使用系統排程器（schedule-task skill）處理。

**不要**使用 Notion 行程頁面來設定通知類任務。

此設定適用於所有後續的個人通知需求，包括訊息傳送與提醒功能。
```

- [ ] **Step 2: Create `agent/data/memories/MEMORY.md`**

```markdown
- [notification-workflow.md] skill:null | updated:2026-04-07 | 通知排程偏好設定：用 scheduler 不用 Notion
```

- [ ] **Step 3: Verify hot layer loads the index**

```
python -c "
import sys; sys.path.insert(0, '.')
from agent.storage.memory_hot import MemoryHotLayer
from pathlib import Path
layer = MemoryHotLayer(Path('agent/data/memories'))
print(repr(layer.load()))
"
```

Expected: prints the index line

- [ ] **Step 4: Commit**

```bash
git add agent/data/memories/MEMORY.md agent/data/memories/topics/notification-workflow.md
git commit -m "chore: migrate skill-memory.json to three-tier memory files"
```

---

## Task 9: Remove Old Extraction Code

The `LongTermMemoryStore`, old `LongTermMemoryManager` extraction methods, and related helpers in the original `memory.py` are now dead code (the file was fully replaced in Task 5). Verify nothing else imports the removed symbols.

- [ ] **Step 1: Check for imports of removed symbols**

```
grep -rn "LongTermMemoryStore\|_extract_memory_payload\|_extract_explicit_memory_payload\|build_memory_message\|remember_turn" agent/
```

Expected: zero matches

- [ ] **Step 2: Remove backup JSON if desired (optional)**

The `skill-memory.json` file is kept as backup. No deletion required.

- [ ] **Step 3: Run all tests**

```
python -m pytest tests/ -v
```

Expected: all existing tests + new storage tests PASS

- [ ] **Step 4: Final commit**

```bash
git add -p
git commit -m "chore: confirm removal of old memory extraction code"
```

---

## Summary of Changes

| Component | Before | After |
|-----------|--------|-------|
| Hot context | Token-overlap scored retrieval | MEMORY.md index, always injected |
| Warm context | None | Small model selects ≤5 topic files |
| Cold storage | None | Per-session `.jsonl`, grep search |
| Write trigger | 2× background LLM calls per turn | Main model inline `{"memory":"write"}` |
| Storage format | `skill-memory.json` (flat) | `topics/*.md` + `MEMORY.md` index |
