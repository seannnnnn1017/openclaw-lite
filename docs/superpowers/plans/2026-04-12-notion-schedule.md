# notion-schedule Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the general-purpose `notion-basic` skill with `notion-schedule`, a focused skill for CRUD operations on a Notion schedule/calendar database, while removing `notion-workflow` entirely.

**Architecture:** Create `agent/SKILLs/notion_schedule/` with a simplified MCP bridge (`notion_mcp_tool.py`) that strips out the internal `delegate_task` LLM loop, keeping only `tools/list` and `tools/call`. The agent now decides what MCP calls to make directly, guided by the new SKILL.md.

**Tech Stack:** Python 3.10+, Notion MCP server (`@notionhq/notion-mcp-server` via npx), stdlib only (urllib, subprocess, threading, json).

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `agent/SKILLs/notion_schedule/skills_config.json` | Create | Skill registration for notion-schedule |
| `agent/SKILLs/notion_schedule/scripts/notion_mcp_tool.py` | Create | Simplified MCP bridge (no delegate_task) |
| `agent/SKILLs/notion_schedule/SKILL.md` | Create | Agent routing prompt, schedule CRUD only |
| `agent/SKILLs/notion_schedule/examples.md` | Create | Schedule CRUD examples |
| `agent/prompts/system_rules.md` | Modify | Replace notion-basic rules with notion-schedule rules |
| `agent/SKILLs/notion_basic/` | Stage delete | Already deleted from disk — `git rm` to stage |
| `sandbox_for_claude/SKILL/notion_basic/` | Stage delete | Remaining files need `git rm` |
| `sandbox_for_claude/SKILL/notion_workflow/` | Stage delete | Fully removed |
| `notion_skill_agent/` | Delete | Untracked directory, `rm -rf` |

---

## Task 1: Create skill directory and skills_config.json

**Files:**
- Create: `agent/SKILLs/notion_schedule/scripts/__init__.py` (empty)
- Create: `agent/SKILLs/notion_schedule/skills_config.json`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p "agent/SKILLs/notion_schedule/scripts"
touch "agent/SKILLs/notion_schedule/scripts/__init__.py"
```

- [ ] **Step 2: Write skills_config.json**

Create `agent/SKILLs/notion_schedule/skills_config.json`:

```json
{
  "skills": [
    {
      "name": "notion-schedule",
      "enabled": true,
      "execution_mode": "invoked",
      "path": "notion_schedule",
      "tool": {
        "type": "python_function",
        "module": "agent.SKILLs.notion_schedule.scripts.notion_mcp_tool",
        "function": "run"
      }
    }
  ]
}
```

- [ ] **Step 3: Commit**

```bash
git add agent/SKILLs/notion_schedule/skills_config.json agent/SKILLs/notion_schedule/scripts/__init__.py
git commit -m "feat(notion-schedule): scaffold skill directory and config"
```

---

## Task 2: Create simplified notion_mcp_tool.py

**Files:**
- Create: `agent/SKILLs/notion_schedule/scripts/notion_mcp_tool.py`

The source of truth is `git show HEAD:agent/SKILLs/notion_basic/scripts/notion_mcp_tool.py` (1070 lines). Copy that file into the new location and apply the following deletions/edits.

- [ ] **Step 1: Copy the original file**

```bash
git show HEAD:agent/SKILLs/notion_basic/scripts/notion_mcp_tool.py \
  > agent/SKILLs/notion_schedule/scripts/notion_mcp_tool.py
```

- [ ] **Step 2: Remove delegate-only constants**

Delete these two lines near the top of the file (lines ~32-33):

```python
DEFAULT_DELEGATE_MAX_STEPS = 20
DEFAULT_DELEGATE_MAX_TOKENS = 4096
```

- [ ] **Step 3: Remove all delegate helper functions**

Delete the following functions entirely (they are only used by `_delegate_task`):

- `_load_delegate_runtime_config()` (~lines 174–230)
- `_load_delegate_llm_dependencies()` (~lines 233–251)
- `_strip_think_blocks()` (~lines 254–258)
- `_try_parse_json_object()` (~lines 260–283)
- `_normalize_delegate_decision()` (~lines 286–332)
- `_build_delegate_system_prompt()` (~lines 335–363)
- `_extract_live_tool_names()` (~lines 366–373)
- `_build_delegate_task_packet()` (~lines 376–386)
- `_build_delegate_repair_message()` (~lines 389–398)
- `_build_unknown_tool_message()` (~lines 401–407)
- `_build_delegate_tool_result_message()` (~lines 410–419)
- `_delegate_chat()` (~lines 422–430)
- `_delegate_task()` (~lines 433–605)

- [ ] **Step 4: Remove delegate branch from run()**

In the `run()` function, delete the entire `delegate_task`/`delegate`/`task` action block:

```python
# DELETE this entire block:
if cleaned_action in {"delegate_task", "delegate", "task"}:
    raw_task = kwargs.pop("task", "")
    raw_context = kwargs.pop("context", {})
    raw_max_steps = kwargs.pop("max_steps", None)
    if kwargs:
        ...
    return _delegate_task(...)
```

- [ ] **Step 5: Update error messages that reference notion-basic**

In `_validate_known_call_shapes()`, change:

```python
# OLD:
f"`{cleaned_tool_name}` is a notion-basic action, not a live Notion MCP tool name. "
"Use the skill action directly instead of passing it through `tools/call`.",
```

```python
# NEW:
f"`{cleaned_tool_name}` is a notion-schedule action, not a live Notion MCP tool name. "
"Use the skill action directly instead of passing it through `tools/call`.",
```

In the `run()` function's `tools/call` branch, change:

```python
# OLD:
"For notion-basic `tools/call`, args must use only `name` and `arguments`."
```

```python
# NEW:
"For notion-schedule `tools/call`, args must use only `name` and `arguments`."
```

In the final fallback error at the bottom of `run()`, change:

```python
# OLD:
"Unsupported notion-basic action. Use `delegate_task` for normal work, or `tools/list` / `tools/call` for low-level MCP access.",
```

```python
# NEW:
"Unsupported notion-schedule action. Use `tools/list` to discover the live catalog, then `tools/call` to call a Notion MCP tool.",
```

- [ ] **Step 6: Verify the file has no syntax errors**

```bash
python -m py_compile agent/SKILLs/notion_schedule/scripts/notion_mcp_tool.py && echo "OK"
```

Expected output: `OK`

- [ ] **Step 7: Commit**

```bash
git add agent/SKILLs/notion_schedule/scripts/notion_mcp_tool.py
git commit -m "feat(notion-schedule): add simplified MCP bridge without delegate_task"
```

---

## Task 3: Write SKILL.md

**Files:**
- Create: `agent/SKILLs/notion_schedule/SKILL.md`

- [ ] **Step 1: Write SKILL.md**

Create `agent/SKILLs/notion_schedule/SKILL.md` with the following content:

```markdown
---
name: notion-schedule
description: CRUD operations on a Notion schedule/calendar database via MCP
user-invocable: true
command-dispatch: tool
command-tool: notion_mcp_tool
command-arg-mode: raw
metadata: { "openclaw": { "requires": { "bins": ["python"] } } }
---

Use this skill when the user wants to view, add, edit, or delete entries in their Notion schedule or calendar database.

This skill is selected by the agent and executed by the skill server.
When this skill is needed, reply with exactly one JSON object and nothing else.

This skill provides direct MCP access via two actions:
- `tools/list` — retrieve the live Notion MCP tool catalog
- `tools/call` — call one live Notion MCP tool by name

Base JSON shape:

{"skill":"notion-schedule","action":"<action>","args":{...}}

Supported actions:
- `tools/list` / `list_tools` — list available Notion MCP tools
- `tools/call` / `call_tool` — call a specific Notion MCP tool

---

## Typical workflow for schedule CRUD

**Always follow this order:**

1. If the property schema for the schedule database is not already known in this session, call `API-retrieve-a-data-source` with the `data_source_id` from the user's memory topic or context.
2. Build the correct MCP call using exact schema property names.
3. Call the MCP tool via `tools/call`.

---

## Scope

Only use this skill for operations on the user's schedule/calendar database:
- Query schedule entries (by date, title, or other filter)
- Create a new schedule entry
- Update an existing schedule entry's properties
- Delete (archive) a schedule entry

Do NOT use this skill for: general Notion page creation, workspace search, comments, page moves, bulk import, or any operation outside the schedule database.

---

## Action shapes

### tools/list

```json
{"skill":"notion-schedule","action":"tools/list","args":{}}
```

### tools/call

```json
{
  "skill": "notion-schedule",
  "action": "tools/call",
  "args": {
    "name": "<live-notion-mcp-tool-name>",
    "arguments": {}
  }
}
```

`args` must contain only `name` and `arguments`. Do not add extra keys.

---

## Key rules

- Use `tools/list` before using a tool you have not seen in this session.
- Only use tool names returned by the live `tools/list` result.
- For `API-post-page`, place the destination database under `parent.database_id` (not top-level).
- For `API-patch-page`, use the page's own ID (not the database ID).
- A Notion `date` property stores datetimes in `date.start` and `date.end`. Do not downgrade to date-only if the user specified a time.
- Preserve minute precision when the user specifies a time (e.g., `"10:30"` → `"2026-04-13T10:30:00+08:00"`).
- If you only have a `database_id`, call `API-retrieve-a-database` first to read `data_sources[].id`, then use `API-retrieve-a-data-source` to get the property schema.
- Never reuse a `database_id` as a `data_source_id`.
- For schedule database URLs, the `?v=` query parameter is the `view_id`, not the `database_id`.

---

## Result shape

- `tools/list` returns the live MCP catalog under `data.tools`.
- `tools/call` returns the raw MCP result under `data.mcp_result` and the extracted text message under `message`.
- Errors are returned as structured error objects with `status: "error"`.
```

- [ ] **Step 2: Commit**

```bash
git add agent/SKILLs/notion_schedule/SKILL.md
git commit -m "feat(notion-schedule): add schedule-focused SKILL.md"
```

---

## Task 4: Write examples.md

**Files:**
- Create: `agent/SKILLs/notion_schedule/examples.md`

- [ ] **Step 1: Write examples.md**

Create `agent/SKILLs/notion_schedule/examples.md`:

```markdown
Use these examples as canonical payload shapes for `notion-schedule`.

Important notes:
- `tools/list` is the source of truth for the live MCP API.
- Always use exact property names from the live schema.
- `data_source_id` and `database_id` come from the user's memory topics — not from this file.

---

## List live tools

```json
{"skill":"notion-schedule","action":"tools/list","args":{}}
```

---

## Get schedule database schema

```json
{
  "skill": "notion-schedule",
  "action": "tools/call",
  "args": {
    "name": "API-retrieve-a-database",
    "arguments": {
      "database_id": "<schedule_database_id>"
    }
  }
}
```

Then read `data_sources[].id` from the result to get `data_source_id`.

---

## Query schedule entries (by date range)

```json
{
  "skill": "notion-schedule",
  "action": "tools/call",
  "args": {
    "name": "API-query-data-source",
    "arguments": {
      "data_source_id": "<schedule_data_source_id>",
      "filter": {
        "property": "日期",
        "date": {
          "on_or_after": "2026-04-12",
          "on_or_before": "2026-04-19"
        }
      }
    }
  }
}
```

---

## Create a schedule entry

```json
{
  "skill": "notion-schedule",
  "action": "tools/call",
  "args": {
    "name": "API-post-page",
    "arguments": {
      "parent": {
        "database_id": "<schedule_database_id>"
      },
      "properties": {
        "名稱": {
          "title": [{ "text": { "content": "台北看房" } }]
        },
        "日期": {
          "date": {
            "start": "2026-04-13T10:00:00+08:00",
            "end": "2026-04-13T11:00:00+08:00"
          }
        }
      }
    }
  }
}
```

---

## Update a schedule entry

```json
{
  "skill": "notion-schedule",
  "action": "tools/call",
  "args": {
    "name": "API-patch-page",
    "arguments": {
      "page_id": "<page_id_of_entry>",
      "properties": {
        "日期": {
          "date": {
            "start": "2026-04-14T14:00:00+08:00"
          }
        }
      }
    }
  }
}
```

---

## Delete (archive) a schedule entry

```json
{
  "skill": "notion-schedule",
  "action": "tools/call",
  "args": {
    "name": "API-patch-page",
    "arguments": {
      "page_id": "<page_id_of_entry>",
      "archived": true
    }
  }
}
```
```

- [ ] **Step 2: Commit**

```bash
git add agent/SKILLs/notion_schedule/examples.md
git commit -m "feat(notion-schedule): add schedule CRUD examples"
```

---

## Task 5: Stage deletions and clean up

**Files:**
- Stage delete: `agent/SKILLs/notion_basic/` (already deleted from disk)
- Stage delete: `sandbox_for_claude/SKILL/notion_basic/` remaining files
- Stage delete: `sandbox_for_claude/SKILL/notion_workflow/`
- Delete untracked: `notion_skill_agent/`

- [ ] **Step 1: Stage deletions of tracked files**

```bash
cd /e/重要文件/openclaw-lite

# Stage already-deleted notion_basic files in agent/
git rm --cached agent/SKILLs/notion_basic/SKILL.md \
  agent/SKILLs/notion_basic/examples.md \
  agent/SKILLs/notion_basic/scripts/notion_mcp_tool.py \
  agent/SKILLs/notion_basic/skills_config.json 2>/dev/null || true

# Stage deletions in sandbox_for_claude
git rm -f sandbox_for_claude/SKILL/notion_basic/SKILL.md \
  sandbox_for_claude/SKILL/notion_basic/examples.md \
  sandbox_for_claude/SKILL/notion_basic/scripts/notion_mcp_tool.py \
  2>/dev/null || true

git rm -f sandbox_for_claude/SKILL/notion_workflow/SKILL.md \
  sandbox_for_claude/SKILL/notion_workflow/examples.md \
  sandbox_for_claude/SKILL/notion_workflow/scripts/__init__.py \
  sandbox_for_claude/SKILL/notion_workflow/scripts/notion_workflow_tool.py \
  sandbox_for_claude/SKILL/notion_workflow/skills_config.json \
  sandbox_for_claude/SKILL/notion_workflow/test_results/results.json \
  sandbox_for_claude/SKILL/notion_workflow/test_results/run_tests.py \
  2>/dev/null || true
```

- [ ] **Step 2: Delete untracked directories**

```bash
rm -rf notion_skill_agent/
```

- [ ] **Step 3: Remove untracked skills_config.json files**

These untracked files should also be removed:

```bash
rm -f sandbox_for_claude/SKILL/notion_basic/skills_config.json
rm -f sandbox_for_claude/SKILL/notion_workflow/skills_config.json 2>/dev/null || true
```

- [ ] **Step 4: Verify git status is clean for notion files**

```bash
git status | grep notion
```

Expected: no output (or only the staged deletions about to be committed).

- [ ] **Step 5: Commit deletions**

```bash
git add -u
git commit -m "chore: remove notion-basic and notion-workflow skills"
```

---

## Task 6: Update system_rules.md

**Files:**
- Modify: `agent/prompts/system_rules.md`

The file currently has these notion-specific lines (lines 23 and 36–41):

```
- Do not ask one skill to perform another skill's job. Example: read local files with `file-control` first, then write to Notion with `notion-basic`.
- For Notion, a property whose schema `type` is `date` can still store datetimes in `date.start` and `date.end`; do not infer "date-only" from the schema label alone.
- Do not claim a Notion date field cannot store time unless a live tool result explicitly rejects a datetime payload.
- For Notion database URLs, the `?v=` query parameter is a `view_id`, not the `database_id`.
- Never reuse a Notion `database_id` as a `data_source_id`.
- If you need a Notion data source schema or rows and you only have a database URL or `database_id`, first retrieve the database and read `data_sources[].id`, then call the data-source tool with that ID.
- After a live `tools/list`, only call Notion MCP tool names that actually appeared in that list.
```

- [ ] **Step 1: Update line 23 (notion-basic reference)**

Change:

```
- Do not ask one skill to perform another skill's job. Example: read local files with `file-control` first, then write to Notion with `notion-basic`.
```

To:

```
- Do not ask one skill to perform another skill's job. Example: read local files with `file-control` first, then write to Notion with `notion-schedule`.
```

- [ ] **Step 2: Verify lines 36–41 are still accurate**

Read the current `agent/prompts/system_rules.md` lines 36–41. These rules about Notion date handling, `database_id` vs `data_source_id`, and `tools/list` are all still correct for `notion-schedule`. No change needed to those lines.

- [ ] **Step 3: Commit**

```bash
git add agent/prompts/system_rules.md
git commit -m "fix(system-rules): update notion-basic reference to notion-schedule"
```

---

## Task 7: Verify and final commit

- [ ] **Step 1: Check git status is clean**

```bash
git status
```

Expected: working tree clean (or only unrelated untracked files).

- [ ] **Step 2: Verify skill structure**

```bash
ls agent/SKILLs/notion_schedule/
```

Expected:
```
SKILL.md  examples.md  scripts/  skills_config.json
```

- [ ] **Step 3: Verify tool syntax**

```bash
python -m py_compile agent/SKILLs/notion_schedule/scripts/notion_mcp_tool.py && echo "syntax OK"
```

Expected: `syntax OK`

- [ ] **Step 4: Verify delegate_task is gone**

```bash
grep -n "delegate_task\|delegate_task\|_delegate_task" agent/SKILLs/notion_schedule/scripts/notion_mcp_tool.py
```

Expected: no output.

- [ ] **Step 5: Verify notion-basic is gone**

```bash
find agent/SKILLs/notion_basic -type f 2>/dev/null && echo "STILL EXISTS" || echo "Correctly removed"
find sandbox_for_claude/SKILL/notion_basic -type f 2>/dev/null && echo "STILL EXISTS" || echo "Correctly removed"
find sandbox_for_claude/SKILL/notion_workflow -type f 2>/dev/null && echo "STILL EXISTS" || echo "Correctly removed"
```

Expected: all three print `Correctly removed`.
