---
name: notion-basic
description: Use the configured Notion MCP server for full Notion tool access
user-invocable: true
command-dispatch: tool
command-tool: notion_mcp_tool
command-arg-mode: raw
metadata: { "openclaw": { "requires": { "bins": ["python"] } } }
---

Use this skill when the user wants to read, search, create, update, move, or comment on Notion content through the live Notion MCP server.

Workspace-specific Notion target IDs are personal preferences, not skill rules.
Store those defaults in `agent/data/memories/topics/*.md` and pass them through `context` when relevant.
For Notion URLs, `?v=` is the `view_id`, not the `database_id`.

This skill is selected by the agent and executed by the skill server.
When this skill is needed, reply with exactly one JSON object and nothing else.

This skill has two layers:
- High-level delegation through `delegate_task`
- Low-level MCP access through `tools/list` and `tools/call`

Base JSON shape:

{"skill":"notion-basic","action":"<action>","args":{...}}

Supported actions:
- `delegate_task`
- `delegate`
- `task`
- `tools/list`
- `tools/call`
- `list_tools`
- `call_tool`

Preferred actions:
- Use `delegate_task` for normal user-facing Notion work.
- Use `tools/list` and `tools/call` for explicit low-level MCP work, debugging, or when the caller already knows the exact tool call to make.
- Compatibility aliases `list_tools` and `call_tool` still work, but do not choose them unless the caller already requested them.

Preferred `delegate_task` shape:

{"skill":"notion-basic","action":"delegate_task","args":{"task":"<complete Notion objective>","context":{"key":"value"}}}

Preferred `tools/call` shape:

{"skill":"notion-basic","action":"tools/call","args":{"name":"<live-notion-mcp-tool-name>","arguments":{...}}}

Core execution logic:
- `delegate_task` is the normal route for user-facing Notion work.
- When using `delegate_task`, put the complete objective in `task` and put concrete ids, urls, dates, constraints, and user text in `context`.
- Do not put MCP transport notes or chain-of-thought style instructions in `context`.
- `tools/list` is a skill action, not a live Notion MCP tool name.
- Never call `tools/list` through `tools/call`.
- Never call `tools/call` with `name` equal to `tools/list`, `list_tools`, `tools/call`, or `call_tool`.
- The live `tools/list` result is the source of truth for the available MCP API.
- If a tool appears in the live catalog, it is allowed to use it.
- The examples in this skill are representative, not exhaustive.
- Do not assume the tool catalog is limited to the examples in this file.
- Workspace-specific `database_id` / `data_source_id` values should come from caller-provided `context` or memory topics, not from hardcoded IDs in this skill file.
- If you need exact property names or select options, retrieve the data source schema once and continue to the write or query step.

Current live catalog snapshot observed from this environment on 2026-03-30:
- `API-get-user`
- `API-get-users`
- `API-get-self`
- `API-post-search`
- `API-get-block-children`
- `API-patch-block-children`
- `API-retrieve-a-block`
- `API-update-a-block`
- `API-delete-a-block`
- `API-retrieve-a-page`
- `API-patch-page`
- `API-post-page`
- `API-retrieve-a-page-property`
- `API-retrieve-a-comment`
- `API-create-a-comment`
- `API-query-data-source`
- `API-retrieve-a-data-source`
- `API-update-a-data-source`
- `API-create-a-data-source`
- `API-list-data-source-templates`
- `API-retrieve-a-database`
- `API-move-page`

Catalog rules:
- Treat the live `tools/list` result as newer than this snapshot if they ever differ.
- The official local server migrated to data-source-first tools. Old database-query style tools are not the current interface.
- If you only have a `database_id` and need row schema or row queries, call `API-retrieve-a-database`, read `data_sources[].id`, then use the data-source tool with that `data_source_id`.

Write rules:
- `tools/call` args must contain only `name` and `arguments`.
- Never place routing scaffolding such as `context`, `task`, `message`, or `delegation_args` inside MCP `arguments`.
- Preserve raw Notion argument shapes instead of inventing shorthand.
- For `API-post-page`, put the destination under `parent.database_id` or `parent.page_id`, depending on the target parent type.
- Do not use a top-level `database_id` field for `API-post-page`.
- Build properties using native Notion shapes such as `title`, `rich_text`, `select`, `multi_select`, and `date`.
- Use exact property names and select option names returned by the current schema.

Date and time rules:
- When the user specified a time, keep minute precision in the stored value.
- A Notion `date` property can still store datetimes in `date.start` and `date.end`.
- Prefer ISO datetimes in `date.start` and `date.end` unless the live tool result proves that only date-only input is accepted.
- If the user gave a time range and the destination property supports it, preserve both `start` and `end`.
- Do not downgrade to date-only just because the schema says `type: date`.

Failure recovery rules:
- If a tool result returns an error, inspect that error and change the next payload accordingly.
- Do not repeat the same failing payload shape without a real change.
- Do not invent tool names.
- Do not emit MCP session-management methods such as `initialize` or `notifications/initialized`; the bridge handles them automatically.

Result shape:
- `tools/list` returns the live MCP tool catalog under `data.tools` and server metadata under `data.server_info`.
- `tools/call` returns the raw MCP tool result under `data.mcp_result`.
- Errors are returned as structured error objects. Preserve them faithfully and react to the actual error message.

Recommended workflows:

Normal user-facing Notion task:
1. `delegate_task`
2. Let the internal Notion specialist use the live catalog plus the task context to decide the next MCP call
3. Return the final user-facing result

Show the live catalog:
1. `tools/list`
2. Read `data.tools`

Read schema from a database id:
1. `tools/call` -> `API-retrieve-a-database`
2. Read `data_sources[].id`
3. `tools/call` -> `API-retrieve-a-data-source`

Create one row in the preferred schedule database:
1. Use the preferred `database_id` / `data_source_id` already present in `context` or loaded from personal memory topics
2. If the current property schema is not already known in this task, call `API-retrieve-a-data-source` with that `data_source_id`
3. Build `API-post-page`
4. Put the row parent under `parent.database_id`
5. Use exact schema property names
6. Preserve time and time ranges in `date.start` and `date.end` whenever the live tool accepts them
