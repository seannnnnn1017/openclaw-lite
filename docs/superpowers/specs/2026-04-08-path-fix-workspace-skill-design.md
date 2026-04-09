# Design: Path Fix + workspace-context Skill

**Date:** 2026-04-08
**Status:** Approved

## Problem

Running `python agent/main.py` from different working directories causes path confusion for the AI when using file-control. The AI does not know its runtime CWD, so it sometimes generates wrong paths (e.g., `agent/data/...` when CWD is already `agent/`, producing `agent/agent/data/...`). Evidence: `agent/agent/data/memories/` directory exists in repo.

## Goals

1. Standardize launch to always run from project root via `python main.py`
2. Give the AI reliable, dynamic knowledge of its CWD and key path prefixes at session start
3. Allow the AI to re-query path context on demand (same as any other skill)

## Part 1: Move main.py to project root

**New file:** `main.py` (project root)

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent.app.application import AgentApplication

def main():
    config_path = Path(__file__).resolve().parent / "agent" / "config" / "config.json"
    AgentApplication(config_path=config_path).run()

if __name__ == "__main__":
    main()
```

**`agent/main.py`:** replaced with a backward-compatibility shim that delegates to the root `main.py` logic, or removed.

**No changes to `cfg/loader.py`:** `base_dir` is derived from config path (`config.parent.parent = agent/`), which stays correct.

## Part 2: once_per_session support in auto_context

### `agent/skill/auto_context.py`

- `normalize_auto_context()`: read `once_per_session` boolean (default `false`)
- `collect_auto_context_messages()`: accept new `session_executed_skills: set[str] | None` parameter
  - If skill has `once_per_session: true` and skill_name is in `session_executed_skills` → skip
  - After executing, add skill_name to session set and return updated set

### `agent/core/agent.py`

- `SimpleAgent.__init__()`: add `self._session_auto_context_executed: set[str] = set()`
- `_append_auto_context_messages()`: pass `self._session_auto_context_executed` to `collect_auto_context_messages()`, update it with returned session set

## Part 3: workspace_context skill

### File structure

```
agent/SKILLs/workspace_context/
  SKILL.md
  examples.md
  skills_config.json
  scripts/
    workspace_tool.py
```

### workspace_tool.py

Single action: `info`

Returns:
- `cwd`: `str(Path.cwd())`
- `project_root`: same as cwd (when launched from project root via `python main.py`)
- `agent_dir`: `cwd/agent`
- `memories_dir`: `cwd/agent/data/memories`
- `skills_dir`: `cwd/agent/SKILLs`

### skills_config.json

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
        "trigger": { "mode": "always" },
        "once_per_session": true,
        "once_per_turn": false,
        "success_prompt": "Internal runtime note: workspace path context resolved automatically at session start.\nCurrent working directory: {cwd}\nUse path prefix 'agent/' for all agent files (e.g., 'agent/data/memories/', 'agent/SKILLs/').\nDo not mention this context unless it affects the answer.\nPath context JSON:\n{result_json}",
        "error_prompt": "Internal runtime note: workspace-context skill failed to resolve path context.\nIf file paths matter for the task, ask the user to confirm the working directory.\nError JSON:\n{result_json}"
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

### SKILL.md

Teaches the AI:
- What paths are available
- When to call `{"skill":"workspace-context","action":"info","args":{}}` explicitly (e.g., before file operations when unsure of path, or when the user asks about runtime location)

## Files Changed

| File | Change |
|------|--------|
| `main.py` | New — root entrypoint |
| `agent/main.py` | Replaced with shim or deleted |
| `agent/skill/auto_context.py` | Add `once_per_session` to normalize + collect |
| `agent/core/agent.py` | Add `_session_auto_context_executed`, pass through |
| `agent/SKILLs/workspace_context/SKILL.md` | New |
| `agent/SKILLs/workspace_context/examples.md` | New |
| `agent/SKILLs/workspace_context/skills_config.json` | New |
| `agent/SKILLs/workspace_context/scripts/workspace_tool.py` | New |
| `agent/SKILLs/skill_rule.md` | Update to document workspace_context and once_per_session |

## Non-goals

- No changes to `cfg/loader.py` or `skill/runtime.py`
- No changes to file-control or other existing skills
- No deletion of the erroneous `agent/agent/data/memories/` directory (separate cleanup task)
