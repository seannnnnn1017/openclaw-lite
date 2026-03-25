---
name: notion-basic
description: Read and modify Notion pages, databases, data sources, and database rows through the external skill server using the Notion REST API
user-invocable: true
command-dispatch: tool
command-tool: notion_tool
command-arg-mode: raw
metadata: { "openclaw": { "requires": { "bins": ["python"] } } }
---

Use this skill when the user wants to work with Notion pages or databases, including reading content, creating child pages, querying database rows, syncing structure to local JSON, updating data source schemas, and trashing or restoring pages or rows.

This skill is selected by the agent and executed by the skill server.
When this skill is needed, reply with exactly one JSON object and nothing else.

Base JSON shape:

{"skill":"notion-basic","action":"<action>","args":{...}}

Supported actions:
- `read_page`: read page metadata and full content as enhanced markdown
- `create_page`: create a new child page under a parent page
- `write_page`: replace the full markdown content of a page and optionally update its title
- `append_page`: append markdown content to the end of a page or after a matched range
- `replace_text`: perform exact search-and-replace inside a page's markdown content
- `delete_page`: move a page to trash
- `restore_page`: restore a trashed page
- `read_database`: retrieve database metadata and its child data source list
- `read_data_source`: retrieve a data source schema and metadata
- `query_database`: query rows through a database target; only works automatically when the database has exactly one data source unless `data_source_id` is also provided
- `query_data_source`: query rows directly from a specific data source
- `create_database`: create a new database under a page
- `create_data_source`: create a new data source under a database
- `update_data_source`: update a data source title, description, schema, or trash state
- `create_row`: create a new database row under a data source
- `update_row`: update a database row's properties
- `delete_row`: move a database row to trash
- `restore_row`: restore a trashed database row
- `read_architecture_cache`: read the local Notion architecture cache from `E:\重要文件\openclaw-lite\agent\SKILLs\notion_basic\scripts\temporary_data\notion_architecture.json` and optionally look up a cached page, database, data source, or row by ID or title
- `sync_architecture`: recursively read a page, database, or data source, continue pagination automatically, save the structure to local JSON, and return the JSON snapshot

Target rules:
- Page targets may be provided as `page_id` or `page_url`.
- Parent page targets may be provided as `parent_page_id` or `parent_page_url`.
- Database targets may be provided as `database_id` or `database_url`.
- Parent database targets may be provided as `parent_database_id` or `parent_database_url`.
- Data source targets may be provided as `data_source_id` or `data_source_url`.
- Row targets may be provided as `row_page_id` or `row_page_url`. `page_id` and `page_url` also work for row update, trash, and restore actions.
- `read_page` may omit the target and fall back to the configured default page.
- `create_page` and `create_database` may omit the parent target and fall back to the configured default parent page.
- `query_database` and `create_row` may accept `database_id` instead of `data_source_id`, but automatic resolution only works when the database has a single data source.
- `sync_architecture` may target a page, database, or data source. If no target is given, it falls back to the configured default page.
- `read_architecture_cache` may be called without arguments to inspect the full local cache, or with `lookup_id`, `lookup_url`, `lookup_title`, and optional `object_type` to narrow results.

Core arguments:
- `title`: convenience title for page creation, database creation, data source creation, or row title injection
- `description`: convenience database or data source description; may be a string or raw rich-text payload
- `content`: Notion-flavored markdown used for page content or row page content
- `properties`: raw Notion property payload used for `create_data_source`, `update_data_source`, `create_row`, and `update_row`
- `initial_data_source`: raw Notion `initial_data_source` payload for `create_database`
- `query`: raw query body for `query_database`, `query_data_source`, or `sync_architecture`
- `body`: raw Notion request body for advanced `create_*`, `update_*`, or `query_*` cases
- `filter`, `sorts`, `page_size`, `start_cursor`: convenience query fields merged into `query`
- `max_depth`: maximum nested page depth to traverse for `sync_architecture`; defaults to `5`
- `include_markdown`: when true, `sync_architecture` includes page markdown in the stored snapshot; defaults to `false`
- `lookup_id`, `lookup_url`, `lookup_title`, `object_type`: optional filters for `read_architecture_cache`
- `include_snapshot`: when true, `read_architecture_cache` also returns the full cached JSON even when filters are used

Behavior guidelines:
- Treat `content` as Notion-flavored markdown.
- Prefer `read_page` before `replace_text` if the exact page content is uncertain.
- Prefer `replace_text` for localized edits and `write_page` only when the user wants to replace the whole page.
- `write_page` and `replace_text` use Notion's markdown update API and protect child pages and child databases by default.
- Only set `allow_deleting_content: true` when the user explicitly wants destructive content replacement.
- `query_database` is a convenience alias over `query_data_source`; if a database has multiple data sources, provide `data_source_id` explicitly.
- `create_row` and `update_row` accept raw Notion property payloads. Use `title` only as a convenience shortcut for the title property.
- When the user asks where a Notion file, page, database, data source, or row is located, prefer `read_architecture_cache` first and inspect `E:\重要文件\openclaw-lite\agent\SKILLs\notion_basic\scripts\temporary_data\notion_architecture.json` before making live API calls.
- Do not call `sync_architecture` by default for location questions. Use it only when the cache file is missing, the cached snapshot is clearly stale for the user task, or the user explicitly asks to refresh from Notion.
- If `read_architecture_cache` returns no match for a requested item, do not answer "not found" immediately. Run `sync_architecture` once to refresh the local structure, then check the cache or refreshed snapshot again before concluding the item is missing.
- `sync_architecture` follows child `<page ...>` and `<database ...>` references from page markdown, retrieves database data sources, and continues data source pagination until all rows are collected.
- `sync_architecture` writes the resulting snapshot to `agent/SKILLs/notion_basic/scripts/temporary_data/notion_architecture.json` and also returns the snapshot JSON in the tool result.
- Legacy aliases `real_all` and `read_all` are still accepted for backward compatibility, but new prompts should use `sync_architecture`.
- `delete_page` and `delete_row` are trash/archive operations. The Notion API does not permanently delete pages.
- Credentials and default parent settings are loaded from `agent/data/system/secrets.local.json` or the corresponding `OPENCLAW_NOTION_*` environment variables.
- If the user gives a Notion URL, pass it directly as `*_url` instead of manually rewriting it.

Result shape:
- The tool returns a JSON object with `status`, `action`, `path`, `message`, and `data`.
- `read_page` returns metadata plus `data.markdown`.
- Database and data source reads return summarized metadata plus schema-oriented fields.
- Query actions return raw `results` and summarized `items`.
- Row actions return row page metadata including `properties`.
- `read_architecture_cache` returns `data.cache_path`, snapshot summaries, optional `matches`, and `data.should_sync_architecture` when a lookup misses in cache.
- `sync_architecture` returns `data.cache_path` plus `data.snapshot` with `pages`, `databases`, `data_sources`, `rows`, and `counts`.
- Errors are returned as structured error objects; preserve them faithfully.

JSON examples:
- `{"skill":"notion-basic","action":"read_architecture_cache","args":{"lookup_title":"hello","object_type":"row"}}`
- `{"skill":"notion-basic","action":"sync_architecture","args":{"page_url":"https://www.notion.so/Claw-lite-32e5aafddb3b80a5a0ebc5d49ec41b5f","include_markdown":false,"max_depth":4}}`
- `{"skill":"notion-basic","action":"read_database","args":{"database_url":"https://www.notion.so/32e5aafddb3b807ab2e5c4c05c04b172"}}`
- `{"skill":"notion-basic","action":"query_database","args":{"database_id":"32e5aafd-db3b-807a-b2e5-c4c05c04b172","page_size":10}}`
- `{"skill":"notion-basic","action":"create_database","args":{"title":"Tasks","initial_data_source":{"properties":{"Name":{"title":{}},"Status":{"select":{"options":[{"name":"Todo","color":"gray"},{"name":"Doing","color":"blue"},{"name":"Done","color":"green"}]}}}}}}`
- `{"skill":"notion-basic","action":"create_data_source","args":{"database_id":"32e5aafd-db3b-807a-b2e5-c4c05c04b172","title":"Bugs","properties":{"Name":{"title":{}},"Severity":{"select":{"options":[{"name":"High","color":"red"},{"name":"Low","color":"yellow"}]}}}}}`
- `{"skill":"notion-basic","action":"update_data_source","args":{"data_source_id":"32e5aafd-db3b-807a-b2e5-c4c05c04b172","description":"Main task schema","properties":{"Priority":{"select":{"options":[{"name":"P0","color":"red"},{"name":"P1","color":"orange"},{"name":"P2","color":"yellow"}]}}}}}`
- `{"skill":"notion-basic","action":"create_row","args":{"data_source_id":"32e5aafd-db3b-807a-b2e5-c4c05c04b172","title":"Fix Telegram reconnect","properties":{"Status":{"select":{"name":"Doing"}},"Owner":{"people":[]}}}}`
- `{"skill":"notion-basic","action":"update_row","args":{"row_page_id":"32e5aafd-db3b-80a5-a0eb-c5d49ec41b5f","properties":{"Status":{"select":{"name":"Done"}}}}}`
