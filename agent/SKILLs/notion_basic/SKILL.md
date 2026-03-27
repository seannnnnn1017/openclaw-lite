---
name: notion-basic
description: Use the external Notion MCP server for full Notion tool access
user-invocable: true
command-dispatch: tool
command-tool: notion_mcp_tool
command-arg-mode: raw
metadata: { "openclaw": { "requires": { "bins": ["python"] } } }
---

Use this skill when the user wants to read, search, create, move, update, or comment on Notion pages, databases, data sources, views, users, or workspace content through the live Notion MCP server.

Built-in schedule database for calendar-style tasks:
- `database_id`: `dca9bd99-bf81-412b-9978-6996c72c5a37`
- `data_source_id`: `f199688f-e08a-48b5-a0db-f1e4b683dae4`
- In a Notion URL for this database, `?v=` is the `view_id`, not the `database_id`.

This skill is selected by the agent and executed by the skill server.
When this skill is needed, reply with exactly one JSON object and nothing else.

This skill is MCP-only.

Base JSON shape:

{"skill":"notion-basic","action":"<action>","args":{...}}

Supported actions:
- `tools/list`
- `tools/call`
- `list_tools`
- `call_tool`

Preferred actions:
- Use `tools/list` to ask the bridge for the current live MCP tool catalog.
- Use `tools/call` to call one live Notion MCP tool by exact name.
- Prefer `tools/list` and `tools/call`.
- Compatibility aliases `list_tools` and `call_tool` still work, but do not choose them unless the caller already requested them.

Preferred `tools/call` shape:

{"skill":"notion-basic","action":"tools/call","args":{"name":"<live-notion-mcp-tool-name>","arguments":{...}}}

Core execution logic:
- `tools/list` is a skill action, not a live Notion tool name.
- Never call `tools/list` through `tools/call`.
- Never call `tools/call` with `name` equal to `tools/list`, `list_tools`, `tools/call`, or `call_tool`.
- Use `tools/list` only when the exact live tool name is genuinely unknown or the user explicitly asked to see the available tools.
- In one task, call `tools/list` at most once unless the user explicitly asks to refresh the live catalog.
- If a successful `tools/list` already happened in the current task, reuse that catalog and do not list again.
- If the task can already be completed with the known tool names in this file and examples, skip `tools/list`.
- For the built-in schedule database, both `database_id` and `data_source_id` are already known. Do not search the workspace or retrieve the database only to rediscover those IDs.
- Retrieve the data source schema when you need current property names, option names, or property types before reading or writing rows.
- After schema is known for the current task, move forward to the write or query call. Do not restart the workflow from `tools/list`.

Known current live tools for common work:
- `API-post-search`
- `API-retrieve-a-database`
- `API-retrieve-a-data-source`
- `API-query-data-source`
- `API-post-page`
- `API-patch-page`
- `API-move-page`
- `API-create-a-comment`
- `API-list-data-source-templates`
- `API-get-self`

Use those names directly when they match the task. Do not re-list tools just to confirm a tool name that is already known here unless a prior result proved the catalog changed.

Routing and ID rules:
- Use `database_id` only where the live tool schema expects a database identifier.
- Use `data_source_id` only where the live tool schema expects a data source identifier.
- Never reuse a `database_id` as a `data_source_id`.
- If you only have a database URL or `database_id` and you need schema or row queries, call `API-retrieve-a-database` first, read `data_sources[].id`, then call the data-source tool with that `data_source_id`.
- For the built-in schedule database, you may skip that discovery step because both IDs are already known above.

Write rules:
- `tools/call` args must contain only `name` and `arguments`.
- Never place routing or conversation scaffolding such as `context`, `message`, `task`, or `delegation_args` inside MCP `arguments`.
- Preserve raw Notion argument shapes instead of inventing shorthand.
- For `API-post-page`, put the row parent under `parent.database_id`.
- Do not use a top-level `database_id` field for `API-post-page` unless a future live schema explicitly requires it.
- Build properties using native Notion shapes such as `title`, `rich_text`, `select`, `multi_select`, and `date`.
- Do not flatten title or rich-text properties into plain strings unless the live tool schema explicitly supports that shorthand.
- Use exact property names and select option names returned by the current schema.

Date and time rules:
- When the user specified a time, keep minute precision in the stored value.
- For a Notion date property, prefer an ISO datetime string in `date.start`, for example `2026-03-28T10:00:00+08:00`, unless the live tool result proves that only date-only input is accepted.
- If the user gave a time range and the destination property supports it, preserve both `start` and `end`.
- If the user gave only an hour, normalize it to `HH:00`.
- Downgrade to date-only only after the live schema or tool result makes that necessary.
- If you must downgrade because the destination truly cannot store time, keep the date in the property, put the missing time detail into another compatible field such as notes, and mention the limitation in the final answer.

Failure recovery rules:
- If a tool result returns an error, inspect that error and change the next payload accordingly.
- Do not repeat the same failing payload shape without a real change.
- Do not go back to `tools/list` unless the actual problem is that you do not know the live tool name.
- Do not invent tool names.
- After a successful `tools/list`, call only tool names that appeared in the live catalog or are explicitly documented as known current live tools above.
- Do not emit MCP session-management methods such as `initialize` or `notifications/initialized`; the bridge handles them automatically.

Result shape:
- `tools/list` returns the live MCP tool catalog under `data.tools` and server metadata under `data.server_info`.
- `tools/call` returns the raw MCP tool result under `data.mcp_result`.
- Errors are returned as structured error objects. Preserve them faithfully and react to the actual error message.

Recommended workflows:

Show the live catalog:
1. `tools/list`
2. Answer the user or choose a live tool name from that result.

Read schema from a database id:
1. `tools/call` -> `API-retrieve-a-database`
2. Read `data_sources[].id`
3. `tools/call` -> `API-retrieve-a-data-source`

Create one row in the built-in schedule database:
1. If the current property schema is not already known in this task, call `API-retrieve-a-data-source` with `f199688f-e08a-48b5-a0db-f1e4b683dae4`
2. Build `API-post-page`
3. Put row parent under `parent.database_id`
4. Use exact schema property names
5. If the user gave a time, store it with minute precision in the date property if the live tool accepts it

Minimal calendar-task rule:
- For calendar-style tasks targeting the built-in schedule database, the normal path is not `tools/list -> search -> search -> search`.
- The normal path is `API-retrieve-a-data-source` once if needed, then `API-post-page`.
