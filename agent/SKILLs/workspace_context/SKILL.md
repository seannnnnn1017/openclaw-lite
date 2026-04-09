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
