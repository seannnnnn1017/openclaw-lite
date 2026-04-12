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

{"skill":"notion-schedule","action":"tools/list","args":{}}

### tools/call

{
  "skill": "notion-schedule",
  "action": "tools/call",
  "args": {
    "name": "<live-notion-mcp-tool-name>",
    "arguments": {}
  }
}

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
