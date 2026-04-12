# notion-schedule Skill — Design Spec

**Date:** 2026-04-12  
**Branch:** refactor/agent-modular-structure

---

## Goal

Replace `notion-basic` (a general-purpose Notion skill) with `notion-schedule`, a focused skill that only handles CRUD operations on a Notion schedule/calendar database. Remove `notion-workflow` entirely. The agent retains all schedule creation, querying, editing, and deletion capabilities through Notion.

---

## What Changes

| Item | Action |
|------|--------|
| `agent/SKILLs/notion_basic/` | Already deleted from disk — stage the deletion |
| `sandbox_for_claude/SKILL/notion_basic/` | Stage deletion of remaining files |
| `sandbox_for_claude/SKILL/notion_workflow/` | Stage deletion |
| `notion_skill_agent/` | Delete (untracked, rm -rf) |
| `agent/SKILLs/notion_schedule/` | Create new skill here |
| `agent/prompts/system_rules.md` | Replace notion-basic rules with notion-schedule rules |

---

## New Skill: `notion-schedule`

**Location:** `agent/SKILLs/notion_schedule/`

### Files

- `SKILL.md` — skill routing prompt, schedule-only scope
- `scripts/notion_mcp_tool.py` — MCP bridge, delegate_task removed
- `skills_config.json` — skill name: `notion-schedule`, tool: `notion_mcp_tool`
- `examples.md` — schedule CRUD examples only

---

## SKILL.md Scope

The SKILL.md describes only these operations:

- **Query events** — filter by date range, title, or other properties
- **Create event** — title, date/datetime, optional time range
- **Update event** — change properties of an existing schedule entry
- **Delete event** — archive or delete a schedule page

Removed from scope (not mentioned, not guided):
- Page operations outside a schedule database
- Comments
- Workspace search
- Page move
- Data source templates
- Bulk import / folder sync

The SKILL.md retains:
- MCP connection guidance (`tools/list` → `tools/call` pattern)
- Date/time handling rules (preserve datetimes, not date-only)
- Write rules (use exact schema property names, correct `parent` shape)
- Failure recovery rules

---

## notion_mcp_tool.py Changes

**Remove:** `delegate_task`, `delegate`, `task` action branches and all supporting internal-LLM logic (prompt building, iterative tool-call loop, token counting for delegate).

**Keep:**
- MCP process lifecycle (start, health-check, shutdown)
- `tools/list` / `list_tools` action
- `tools/call` / `call_tool` action
- `ok()` / `err()` response helpers
- Error handling and structured error return

Result: the tool becomes a thin MCP bridge. The agent itself decides which MCP calls to make based on the SKILL.md guidance.

---

## skills_config.json

```json
{
  "name": "notion-schedule",
  "tool": "notion_mcp_tool",
  "description": "CRUD operations on a Notion schedule/calendar database via MCP"
}
```

---

## system_rules.md Changes

Remove rules specific to notion-basic's delegate pattern and general Notion rules that are no longer needed. Keep only:
- Date/datetime rules relevant to schedule entries
- `tools/list` → `tools/call` usage pattern
- Rule about `?v=` being view_id not database_id (still relevant for schedule DB URLs)

---

## What Is NOT Changing

- `agent/SKILLs/schedule_task/` — agent-native scheduler, untouched
- `agent/SKILLs/time_query/` — time query, untouched
- `agent/SKILLs/file_control/` — file control, untouched
- MCP server itself (runs separately, unchanged)
- `cfg/secrets.py` Notion token handling — unchanged
