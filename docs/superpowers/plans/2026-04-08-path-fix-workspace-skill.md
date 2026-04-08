# Path Fix + workspace-context Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Standardize launch path to project root, add `once_per_session` auto_context support, and create a `workspace-context` skill that injects CWD/path context at session start.

**Architecture:** Move `main.py` to project root so CWD is always the project root. Add `once_per_session` tracking to `SimpleAgent` and `collect_auto_context_messages()`. Create a new `workspace_context` skill with `execution_mode: default` + `once_per_session: true` so the AI gets reliable path context once per session and can re-query on demand.

**Tech Stack:** Python 3.10+, pathlib, existing auto_context / SimpleAgent infrastructure, pytest

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `main.py` | Create | Root-level entrypoint |
| `agent/main.py` | Modify | Backward-compat shim |
| `agent/skill/auto_context.py` | Modify | Add `once_per_session` to normalize + collect |
| `agent/core/agent.py` | Modify | Add `_session_auto_context_executed` |
| `agent/SKILLs/workspace_context/scripts/workspace_tool.py` | Create | `info` action tool |
| `agent/SKILLs/workspace_context/SKILL.md` | Create | Prompt instructions |
| `agent/SKILLs/workspace_context/examples.md` | Create | Usage examples |
| `agent/SKILLs/workspace_context/skills_config.json` | Create | Runtime registration |
| `tests/skill/test_auto_context_session.py` | Create | Tests for once_per_session |
| `tests/skill/__init__.py` | Create | Package marker |
| `tests/skills/test_workspace_tool.py` | Create | Tests for workspace_tool |
| `tests/skills/__init__.py` | Create | Package marker |

---

### Task 1: once_per_session — failing tests

**Files:**
- Create: `tests/skill/__init__.py`
- Create: `tests/skill/test_auto_context_session.py`
- Read: `agent/skill/auto_context.py` (understand normalize_auto_context, collect_auto_context_messages)

- [ ] **Step 1: Create test package marker**

Create `tests/skill/__init__.py` as an empty file.

- [ ] **Step 2: Write failing tests for normalize_auto_context**

Create `tests/skill/test_auto_context_session.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agent.skill.auto_context import normalize_auto_context, collect_auto_context_messages


def test_normalize_once_per_session_true():
    config = {
        "action": "info",
        "args": {},
        "trigger": {"mode": "always"},
        "once_per_session": True,
        "once_per_turn": False,
        "success_prompt": "ok",
        "error_prompt": "err",
    }
    result = normalize_auto_context(config)
    assert result is not None
    assert result["once_per_session"] is True


def test_normalize_once_per_session_default_false():
    config = {
        "action": "info",
        "args": {},
        "trigger": {"mode": "always"},
        "success_prompt": "ok",
        "error_prompt": "err",
    }
    result = normalize_auto_context(config)
    assert result is not None
    assert result["once_per_session"] is False


def _make_fake_skill(name: str, once_per_session: bool = False, once_per_turn: bool = True):
    """Build a minimal skill dict with a no-op tool."""
    return {
        "name": name,
        "execution_mode": "default",
        "path": "",
        "auto_context": {
            "action": "noop",
            "args": {},
            "trigger_mode": "always",
            "contains_any": [],
            "regex_any": [],
            "once_per_session": once_per_session,
            "once_per_turn": once_per_turn,
            "success_prompt": "ctx: {result_json}",
            "error_prompt": "err: {result_json}",
        },
        "tool": {},
        "enabled": True,
        "metadata": {"command-tool": "noop"},
    }


def test_collect_skips_when_in_session_executed():
    """A once_per_session skill already in session_executed should not run."""
    skill = _make_fake_skill("ws", once_per_session=True)
    session_executed = {"ws"}

    messages, updated_turn, updated_session = collect_auto_context_messages(
        [skill],
        user_input="hello",
        session_executed_skills=session_executed,
    )
    assert messages == []
    assert "ws" in updated_session


def test_collect_runs_when_not_in_session_executed(monkeypatch):
    """A once_per_session skill NOT in session_executed should run."""
    import agent.skill.auto_context as ac_mod

    def fake_execute(runtime, *, skill_name, auto_context):
        return {"status": "ok", "skill": skill_name, "action": "noop", "result": {"data": {}}}

    monkeypatch.setattr(ac_mod, "_execute_auto_context_skill", fake_execute)

    skill = _make_fake_skill("ws", once_per_session=True)
    session_executed: set[str] = set()

    messages, updated_turn, updated_session = collect_auto_context_messages(
        [skill],
        user_input="hello",
        session_executed_skills=session_executed,
    )
    assert len(messages) == 1
    assert "ws" in updated_session
```

- [ ] **Step 3: Run tests to verify they fail**

```
cd E:/重要文件/openclaw-lite
pytest tests/skill/test_auto_context_session.py -v
```

Expected: FAIL — `once_per_session` key missing from normalize result; `collect_auto_context_messages` does not accept `session_executed_skills`.

---

### Task 2: once_per_session — implementation

**Files:**
- Modify: `agent/skill/auto_context.py`

- [ ] **Step 1: Add `once_per_session` to `normalize_auto_context`**

In `normalize_auto_context()`, after the existing `once_per_turn` line, add:

```python
    return {
        "action": action,
        "args": args,
        "trigger_mode": trigger_mode,
        "contains_any": contains_any,
        "regex_any": regex_any,
        "once_per_turn": bool(config.get("once_per_turn", True)),
        "once_per_session": bool(config.get("once_per_session", False)),   # ← add this
        "success_prompt": success_prompt,
        "error_prompt": error_prompt,
    }
```

- [ ] **Step 2: Update `collect_auto_context_messages` signature and logic**

Replace the function signature and internals. The full updated function:

```python
def collect_auto_context_messages(
    skills: list[dict],
    *,
    user_input: str = "",
    task: str = "",
    context=None,
    skill_call: dict | None = None,
    executed_skills: set[str] | None = None,
    session_executed_skills: set[str] | None = None,
) -> tuple[list[str], set[str], set[str]]:
    executed = set(executed_skills or set())
    session_executed = set(session_executed_skills or set())
    relevant_text = build_auto_context_text(
        user_input=user_input,
        task=task,
        context=context,
        skill_call=skill_call,
    )
    if not relevant_text.strip():
        return [], executed, session_executed

    candidates = []
    for skill in skills:
        if normalize_execution_mode(skill.get("execution_mode")) != "default":
            continue

        skill_name = str(skill.get("name", "")).strip()
        auto_context = skill.get("auto_context")
        if not skill_name or not isinstance(auto_context, dict):
            continue
        if auto_context.get("once_per_session", False) and skill_name in session_executed:
            continue
        if auto_context.get("once_per_turn", True) and skill_name in executed:
            continue
        if not _auto_context_matches(auto_context, relevant_text):
            continue
        candidates.append((skill_name, skill, auto_context))

    if not candidates:
        return [], executed, session_executed

    runtime = SkillRuntime(skills)
    messages = []
    for skill_name, skill, auto_context in candidates:
        preflight_result = _execute_auto_context_skill(
            runtime,
            skill_name=skill_name,
            auto_context=auto_context,
        )
        messages.append(_render_auto_context_message(skill, auto_context, preflight_result))
        executed.add(skill_name)
        session_executed.add(skill_name)

    return messages, executed, session_executed
```

- [ ] **Step 3: Run tests to verify they pass**

```
cd E:/重要文件/openclaw-lite
pytest tests/skill/test_auto_context_session.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 4: Commit**

```bash
cd E:/重要文件/openclaw-lite
git add agent/skill/auto_context.py tests/skill/__init__.py tests/skill/test_auto_context_session.py
git commit -m "feat: add once_per_session support to auto_context collect"
```

---

### Task 3: Wire once_per_session into SimpleAgent

**Files:**
- Modify: `agent/core/agent.py`

The current `collect_auto_context_messages` returns `(list[str], set[str])`. After Task 2 it returns `(list[str], set[str], set[str])`. We need to update every call site in `agent.py`.

- [ ] **Step 1: Add session set to `__init__`**

In `SimpleAgent.__init__`, after `self.max_tool_steps = 20`, add:

```python
        self._session_auto_context_executed: set[str] = set()
```

- [ ] **Step 2: Update `_append_auto_context_messages`**

Replace the existing method:

```python
    def _append_auto_context_messages(
        self,
        messages: list[Message],
        *,
        user_input: str = "",
        skill_call: dict | None = None,
        executed_skills: set[str],
        debug_context: dict | None = None,
    ) -> set[str]:
        auto_messages, updated_executed, updated_session = collect_auto_context_messages(
            self.config.skills,
            user_input=user_input,
            skill_call=skill_call,
            executed_skills=executed_skills,
            session_executed_skills=self._session_auto_context_executed,
        )
        self._session_auto_context_executed = updated_session
        for index, content in enumerate(auto_messages, start=1):
            messages.append(Message(role="user", content=content))
            self._log_debug(
                "auto_context",
                debug_context=dict(debug_context or {}),
                ordinal=index,
                content=content,
                skill_call=skill_call,
            )
        return updated_executed
```

- [ ] **Step 3: Run existing tests to confirm no regressions**

```
cd E:/重要文件/openclaw-lite
pytest tests/ -v
```

Expected: All previously passing tests still PASS.

- [ ] **Step 4: Commit**

```bash
cd E:/重要文件/openclaw-lite
git add agent/core/agent.py
git commit -m "feat: wire once_per_session session tracking into SimpleAgent"
```

---

### Task 4: workspace_tool.py — failing tests

**Files:**
- Create: `tests/skills/__init__.py`
- Create: `tests/skills/test_workspace_tool.py`

- [ ] **Step 1: Create test package marker**

Create `tests/skills/__init__.py` as an empty file.

- [ ] **Step 2: Write failing tests**

Create `tests/skills/test_workspace_tool.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def test_info_returns_ok():
    from agent.SKILLs.workspace_context.scripts.workspace_tool import run
    result = run(action="info")
    assert result["status"] == "ok"
    assert result["action"] == "info"


def test_info_cwd_is_absolute():
    from agent.SKILLs.workspace_context.scripts.workspace_tool import run
    result = run(action="info")
    cwd = result["data"]["cwd"]
    assert Path(cwd).is_absolute()


def test_info_includes_expected_keys():
    from agent.SKILLs.workspace_context.scripts.workspace_tool import run
    result = run(action="info")
    data = result["data"]
    assert "cwd" in data
    assert "project_root" in data
    assert "agent_dir" in data
    assert "memories_dir" in data
    assert "skills_dir" in data


def test_unknown_action_returns_error():
    from agent.SKILLs.workspace_context.scripts.workspace_tool import run
    result = run(action="unknown_action")
    assert result["status"] == "error"
    assert "unknown_action" in result["message"]
```

- [ ] **Step 3: Run tests to verify they fail**

```
cd E:/重要文件/openclaw-lite
pytest tests/skills/test_workspace_tool.py -v
```

Expected: FAIL — `agent/SKILLs/workspace_context/` does not exist yet.

---

### Task 5: workspace_tool.py — implementation

**Files:**
- Create: `agent/SKILLs/workspace_context/scripts/workspace_tool.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p "E:/重要文件/openclaw-lite/agent/SKILLs/workspace_context/scripts"
```

- [ ] **Step 2: Write workspace_tool.py**

Create `agent/SKILLs/workspace_context/scripts/workspace_tool.py`:

```python
from pathlib import Path


def run(action: str, **kwargs):
    if action == "info":
        cwd = Path.cwd().resolve()
        return {
            "status": "ok",
            "action": "info",
            "message": "Workspace path context resolved.",
            "data": {
                "cwd": str(cwd),
                "project_root": str(cwd),
                "agent_dir": str(cwd / "agent"),
                "memories_dir": str(cwd / "agent" / "data" / "memories"),
                "skills_dir": str(cwd / "agent" / "SKILLs"),
            },
        }

    return {
        "status": "error",
        "action": action,
        "message": f"Unknown action: {action!r}. Supported actions: info",
        "data": None,
    }
```

- [ ] **Step 3: Run tests to verify they pass**

```
cd E:/重要文件/openclaw-lite
pytest tests/skills/test_workspace_tool.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 4: Commit**

```bash
cd E:/重要文件/openclaw-lite
git add agent/SKILLs/workspace_context/scripts/workspace_tool.py tests/skills/__init__.py tests/skills/test_workspace_tool.py
git commit -m "feat: add workspace_context skill tool (info action)"
```

---

### Task 6: workspace_context skill registration files

**Files:**
- Create: `agent/SKILLs/workspace_context/SKILL.md`
- Create: `agent/SKILLs/workspace_context/examples.md`
- Create: `agent/SKILLs/workspace_context/skills_config.json`

- [ ] **Step 1: Create SKILL.md**

Create `agent/SKILLs/workspace_context/SKILL.md`:

```markdown
---
name: workspace-context
description: Returns the current working directory and key project path prefixes so the agent can resolve file paths correctly
user-invocable: true
command-dispatch: tool
command-tool: workspace_tool
command-arg-mode: raw
metadata: { "openclaw": { "requires": { "bins": ["python"] } } }
---

Use this skill when you need to confirm the runtime working directory or resolve correct path prefixes before file operations.

This skill runs automatically once per session. You may also call it explicitly at any time if you are unsure which directory prefix to use for a file path.

When this skill is needed, reply with exactly one JSON object and nothing else.

Base JSON shape:

{"skill":"workspace-context","action":"info","args":{}}

Supported actions:
- `info`: return the current working directory and derived project path prefixes

Result shape:
- `status`: "ok" or "error"
- `action`: "info"
- `message`: human-readable summary
- `data.cwd`: absolute path of the current working directory
- `data.project_root`: same as cwd (the project root when launched via `python main.py`)
- `data.agent_dir`: `<cwd>/agent` — all agent source lives here
- `data.memories_dir`: `<cwd>/agent/data/memories` — long-term memory files
- `data.skills_dir`: `<cwd>/agent/SKILLs` — SKILL folders

Path usage rules:
- When using file-control with a relative path, prefix it relative to `data.cwd`
- Agent source files are under `agent/` (e.g., `agent/SKILLs/`, `agent/data/`)
- Long-term memory is at `agent/data/memories/`
- Do NOT use `agent/agent/...` — that is an invalid double-prefix path

JSON examples:
- `{"skill":"workspace-context","action":"info","args":{}}`
```

- [ ] **Step 2: Create examples.md**

Create `agent/SKILLs/workspace_context/examples.md`:

```markdown
# workspace-context Examples

## Example 1: check path before file operation

User: 幫我讀一下記憶檔案

Agent first confirms path context:
{"skill":"workspace-context","action":"info","args":{}}

Result:
{"status":"ok","action":"info","data":{"cwd":"/project","agent_dir":"/project/agent","memories_dir":"/project/agent/data/memories",...}}

Agent then reads the correct path:
{"skill":"file-control","action":"read","args":{"path":"agent/data/memories/MEMORY.md"}}

## Example 2: explicit path query

User: 你現在的執行目錄是哪裡？

{"skill":"workspace-context","action":"info","args":{}}
```

- [ ] **Step 3: Create skills_config.json**

Create `agent/SKILLs/workspace_context/skills_config.json`:

```json
{
  "skills": [
    {
      "name": "workspace-context",
      "enabled": true,
      "execution_mode": "default",
      "path": "workspace_context",
      "auto_context": {
        "action": "info",
        "args": {},
        "trigger": {
          "mode": "always"
        },
        "once_per_session": true,
        "once_per_turn": false,
        "success_prompt": "Internal runtime note: workspace path context was resolved automatically at session start by skill `{skill_name}`.\nUse the paths below to construct correct file paths with file-control.\nDo NOT use double-prefix paths like 'agent/agent/...'.\nDo not mention this lookup unless it affects the answer.\nPath context JSON:\n{result_json}",
        "error_prompt": "Internal runtime note: skill `{skill_name}` failed to resolve workspace path context.\nIf a file path is needed, call this skill explicitly before using file-control.\nError JSON:\n{result_json}"
      },
      "tool": {
        "type": "python_function",
        "module": "agent.SKILLs.workspace_context.scripts.workspace_tool",
        "function": "run"
      }
    }
  ]
}
```

- [ ] **Step 4: Run full test suite**

```
cd E:/重要文件/openclaw-lite
pytest tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
cd E:/重要文件/openclaw-lite
git add agent/SKILLs/workspace_context/
git commit -m "feat: register workspace-context skill with once_per_session auto_context"
```

---

### Task 7: Move main.py to project root

**Files:**
- Create: `main.py` (project root)
- Modify: `agent/main.py` (shim)

- [ ] **Step 1: Create root main.py**

Create `main.py` at project root:

```python
import sys
from pathlib import Path

# Ensure project root is on sys.path so `from agent.X import Y` works
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent.app.application import AgentApplication


def main():
    config_path = Path(__file__).resolve().parent / "agent" / "config" / "config.json"
    AgentApplication(config_path=config_path).run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Replace agent/main.py with shim**

Replace `agent/main.py` with:

```python
"""Backward-compatibility shim. Run `python main.py` from the project root instead."""
import sys
from pathlib import Path

# Add project root (parent of agent/) to sys.path
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from agent.app.application import AgentApplication


def main():
    config_path = _project_root / "agent" / "config" / "config.json"
    AgentApplication(config_path=config_path).run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Verify both entrypoints resolve config correctly**

```bash
cd E:/重要文件/openclaw-lite
python -c "
import sys
from pathlib import Path
sys.path.insert(0, '.')
from agent.cfg.loader import Config
c = Config('agent/config/config.json')
print('base_dir:', c.base_dir)
print('memory_store_path:', c.memory_store_path)
print('OK')
"
```

Expected output:
```
base_dir: E:\重要文件\openclaw-lite\agent
memory_store_path: E:\重要文件\openclaw-lite\agent\data\memories\skill-memory.json
OK
```

- [ ] **Step 4: Run full test suite**

```
cd E:/重要文件/openclaw-lite
pytest tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
cd E:/重要文件/openclaw-lite
git add main.py agent/main.py
git commit -m "feat: move entrypoint to project root main.py, keep agent/main.py as shim"
```

---

### Task 8: Update skill_rule.md

**Files:**
- Modify: `agent/SKILLs/skill_rule.md`

- [ ] **Step 1: Add workspace_context to section 2 (Root Location)**

In the "Current files in this area include:" list, add:
```
- `agent/SKILLs/workspace_context/`
```

- [ ] **Step 2: Add workspace_context to section 4 (Current Examples)**

After the `time_query` block, add:

```
Important files for `workspace_context`:
- `agent/SKILLs/workspace_context/SKILL.md`: prompt-facing skill description
- `agent/SKILLs/workspace_context/examples.md`: usage examples for the model
- `agent/SKILLs/workspace_context/skills_config.json`: runtime registration (execution_mode: default, once_per_session: true)
- `agent/SKILLs/workspace_context/scripts/workspace_tool.py`: returns CWD and key project path prefixes
```

- [ ] **Step 3: Add once_per_session to section 5 (skills_config.json Rules)**

After the `once_per_turn` bullet, add:
```
- `once_per_session`: when true, the automatic action runs at most once per agent session instance (survives across turns, resets when the agent process restarts or `/clear` resets session state)
```

- [ ] **Step 4: Commit**

```bash
cd E:/重要文件/openclaw-lite
git add agent/SKILLs/skill_rule.md
git commit -m "docs: update skill_rule.md for workspace_context and once_per_session"
```

---

## Self-Review

**Spec coverage:**
- ✅ Move main.py to project root → Task 7
- ✅ once_per_session in auto_context → Tasks 1–3
- ✅ workspace_context skill with info action → Tasks 4–6
- ✅ AI can call skill explicitly on demand → SKILL.md documents this, skill is in prompt
- ✅ session start auto-run (once) → skills_config.json `once_per_session: true`
- ✅ skill_rule.md updated → Task 8

**Placeholder scan:** No TBD/TODO. All code blocks are complete. All file paths are exact.

**Type consistency:**
- `collect_auto_context_messages` returns `tuple[list[str], set[str], set[str]]` — checked in Task 2 signature and Task 3 usage.
- `run(action, **kwargs)` signature in workspace_tool matches SkillRuntime `execute()` call pattern (passes `action=` as kwarg).
- `_session_auto_context_executed` set initialized in `__init__`, mutated in `_append_auto_context_messages` — consistent across Tasks 3.
