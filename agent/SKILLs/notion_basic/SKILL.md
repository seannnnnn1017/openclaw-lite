---
name: notion-basic
description: Read and modify Notion pages, databases, data sources, and database rows through the external skill server using the Notion REST API
user-invocable: true
command-dispatch: tool
command-tool: notion_tool
command-arg-mode: raw
metadata: { "openclaw": { "requires": { "bins": ["python"] } } }
---

Use this skill when the user wants to work with Notion pages or databases, including title search, reading content, creating child pages, querying database rows, syncing live structure, uploading or downloading images, updating data source schemas, and trashing or restoring pages or rows.

This skill is selected by the agent and executed by the skill server.
When this skill is needed, reply with exactly one JSON object and nothing else.
When the user does not specify a page target, prefer the default page configured in `agent/data/system/secrets.local.json` instead of inventing a Notion URL.

Base JSON shape:

{"skill":"notion-basic","action":"<action>","args":{...}}

Supported actions:
- `search`: search shared Notion pages or data sources by title metadata through the official Notion search API
- `read_page`: read page metadata and full content as enhanced markdown
- `create_page`: create a new child page under a parent page
- `write_page`: replace the full markdown content of a page and optionally update its title
- `append_page`: append markdown content to the end of a page or after a matched range
- `upload_image`: upload a local image file to Notion and append it to a page as an image block
- `download_image`: download an image block from a Notion page or image block to a local file
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
- `sync_architecture`: recursively read a page, database, or data source from Notion and return the live JSON snapshot

Target rules:
- Page targets may be provided as `page_id` or `page_url`.
- Block targets for `download_image` may be provided as `block_id` or `block_url`.
- Parent page targets may be provided as `parent_page_id` or `parent_page_url`.
- Database targets may be provided as `database_id` or `database_url`.
- Parent database targets may be provided as `parent_database_id` or `parent_database_url`.
- Data source targets may be provided as `data_source_id` or `data_source_url`.
- Row targets may be provided as `row_page_id` or `row_page_url`. `page_id` and `page_url` also work for row update, trash, and restore actions.
- `read_page` may omit the target and fall back to the default page configured in `agent/data/system/secrets.local.json` under `notion.default_parent_page_id` or `notion.default_parent_page_url`.
- `create_page` and `create_database` may omit the parent target and fall back to the same configured default parent page from `agent/data/system/secrets.local.json`.
- `query_database` and `create_row` may accept `database_id` instead of `data_source_id`, but automatic resolution only works when the database has a single data source.
- `sync_architecture` may target a page, database, or data source. If no target is given, it falls back to the same default page from `agent/data/system/secrets.local.json`.

Core arguments:
- `query_text` or `search_query`: keyword text for the official Notion `search` action; prefer these over `query` for title search
- `title`: convenience title for page creation, database creation, data source creation, or row title injection
- `description`: convenience database or data source description; may be a string or raw rich-text payload
- `content`: Notion-flavored markdown used for page content or row page content
- `image_path`: local filesystem path for `upload_image`; relative paths resolve from the current working directory
- `local_image_path` and `file_path`: accepted aliases for `image_path` when the image already exists on disk
- `caption`: optional rich-text caption for `upload_image`; may be a string, object, or array
- `image_index`: 1-based index for `download_image` when a page contains multiple image blocks; defaults to `1`
- `save_path`: optional explicit local file path for `download_image`
- `save_dir`: optional local output directory for `download_image`; if omitted, files are saved under `agent/data/notion_downloads/<date>/`
- `filename`: optional output filename override for `download_image`
- `recursive`: when true, `download_image` searches nested child blocks under the target page; defaults to `true`
- `properties`: raw Notion property payload used for `create_data_source`, `update_data_source`, `create_row`, and `update_row`
- `initial_data_source`: raw Notion `initial_data_source` payload for `create_database`
- `query`: raw query body for `query_database`, `query_data_source`, or `sync_architecture`
- `body`: raw Notion request body for advanced `create_*`, `update_*`, or `query_*` cases
- `filter`, `sorts`, `page_size`, `start_cursor`: convenience query fields merged into `query`
- `max_depth`: maximum nested page depth to traverse for `sync_architecture`; defaults to `3` and cannot exceed `3`
- `include_markdown`: when true, `sync_architecture` includes page markdown in the stored snapshot; defaults to `false`

Behavior guidelines:
- `search` uses the official Notion search API. It can search shared pages and data sources by title metadata, but it is not full-text page-content search and it cannot directly search attachment contents.
- Treat `content` as Notion-flavored markdown.
- `upload_image` currently supports single-part Notion uploads for local image files up to 20 MB and appends the uploaded image as a page block.
- `download_image` downloads an existing Notion image block to a local file. If `block_id` or `block_url` is not given, it searches the target page for image blocks and picks `image_index`.
- For `upload_image`, the image itself must come from a local filesystem path such as `image_path`, `local_image_path`, or `file_path`. Do not invent or require a hosted image URL for the uploaded file.
- `page_url` or `page_id` identifies the target Notion page. It does not replace the local image file path.
- `upload_image` may reuse `after` to insert the image after an existing block ID or URL; omit `after` to append at the end of the page.
- Prefer `read_page` before `replace_text` if the exact page content is uncertain.
- Prefer `replace_text` for localized edits and `write_page` only when the user wants to replace the whole page.
- `write_page` and `replace_text` use Notion's markdown update API and protect child pages and child databases by default.
- Only set `allow_deleting_content: true` when the user explicitly wants destructive content replacement.
- `query_database` is a convenience alias over `query_data_source`; if a database has multiple data sources, provide `data_source_id` explicitly.
- `create_row` and `update_row` accept raw Notion property payloads. Use `title` only as a convenience shortcut for the title property.
- When the user does not provide `page_id` or `page_url`, do not ask for one first if the configured default page in `agent/data/system/secrets.local.json` is sufficient for the task.
- When the user asks where a Notion page, database, data source, or row is located, use `sync_architecture` directly against the relevant root target instead of relying on a local cache.
- `sync_architecture` is live and stateless. It does not read or write a local architecture cache file.
- `sync_architecture` is capped at depth `3` per call. If the user needs deeper structure, call `sync_architecture` again from a deeper page, database, or data source target.
- `sync_architecture` follows child `<page ...>` and `<database ...>` references from page markdown, retrieves database data sources, and continues data source pagination until all rows are collected.
- `delete_page` and `delete_row` are trash/archive operations. The Notion API does not permanently delete pages.
- Credentials and default parent settings are loaded from `agent/data/system/secrets.local.json` or the corresponding `OPENCLAW_NOTION_*` environment variables. The default page comes from `notion.default_parent_page_id` and `notion.default_parent_page_url`.
- If the user gives a Notion URL, pass it directly as `*_url` instead of manually rewriting it.

Result shape:
- The tool returns a JSON object with `status`, `action`, `path`, `message`, and `data`.
- `search` returns `data.results` and summarized `data.items`; search matches shared pages and data sources by title metadata only.
- `read_page` returns metadata plus `data.markdown`.
- Database and data source reads return summarized metadata plus schema-oriented fields.
- Query actions return raw `results` and summarized `items`.
- Row actions return row page metadata including `properties`.
- `upload_image` returns page metadata plus `data.file_upload`, `data.local_image_path`, and `data.appended_blocks`.
- `download_image` returns the local file path, block metadata, download URL, content type, and byte size.
- `sync_architecture` returns `data.snapshot` with `pages`, `databases`, `data_sources`, `rows`, and `counts`, plus depth-limit metadata.
- Errors are returned as structured error objects; preserve them faithfully.

JSON examples:
- `{"skill":"notion-basic","action":"search","args":{"search_query":"Dinner","object_type":"page","page_size":10}}`
- `{"skill":"notion-basic","action":"sync_architecture","args":{"page_url":"https://www.notion.so/Claw-lite-32e5aafddb3b80a5a0ebc5d49ec41b5f","include_markdown":false,"max_depth":3}}`
- `{"skill":"notion-basic","action":"read_page","args":{}}`
- `{"skill":"notion-basic","action":"sync_architecture","args":{"max_depth":3}}`
- `{"skill":"notion-basic","action":"upload_image","args":{"page_url":"https://www.notion.so/Claw-lite-32e5aafddb3b80a5a0ebc5d49ec41b5f","image_path":"assets/screenshot.png","caption":"Latest UI screenshot"}}`
- `{"skill":"notion-basic","action":"download_image","args":{"page_id":"32e5aafd-db3b-80a5-a0eb-c5d49ec41b5f","image_index":1}}`
- `{"skill":"notion-basic","action":"upload_image","args":{"page_id":"32e5aafd-db3b-80a5-a0eb-c5d49ec41b5f","local_image_path":"agent/data/telegram_media/2026-03-25/chat_123/photo.png","caption":"User-provided local photo"}}`
- `{"skill":"notion-basic","action":"read_database","args":{"database_url":"https://www.notion.so/32e5aafddb3b807ab2e5c4c05c04b172"}}`
- `{"skill":"notion-basic","action":"query_database","args":{"database_id":"32e5aafd-db3b-807a-b2e5-c4c05c04b172","page_size":10}}`
- `{"skill":"notion-basic","action":"create_database","args":{"title":"Tasks","initial_data_source":{"properties":{"Name":{"title":{}},"Status":{"select":{"options":[{"name":"Todo","color":"gray"},{"name":"Doing","color":"blue"},{"name":"Done","color":"green"}]}}}}}}`
- `{"skill":"notion-basic","action":"create_data_source","args":{"database_id":"32e5aafd-db3b-807a-b2e5-c4c05c04b172","title":"Bugs","properties":{"Name":{"title":{}},"Severity":{"select":{"options":[{"name":"High","color":"red"},{"name":"Low","color":"yellow"}]}}}}}`
- `{"skill":"notion-basic","action":"update_data_source","args":{"data_source_id":"32e5aafd-db3b-807a-b2e5-c4c05c04b172","description":"Main task schema","properties":{"Priority":{"select":{"options":[{"name":"P0","color":"red"},{"name":"P1","color":"orange"},{"name":"P2","color":"yellow"}]}}}}}`
- `{"skill":"notion-basic","action":"create_row","args":{"data_source_id":"32e5aafd-db3b-807a-b2e5-c4c05c04b172","title":"Fix Telegram reconnect","properties":{"Status":{"select":{"name":"Doing"}},"Owner":{"people":[]}}}}`
- `{"skill":"notion-basic","action":"update_row","args":{"row_page_id":"32e5aafd-db3b-80a5-a0eb-c5d49ec41b5f","properties":{"Status":{"select":{"name":"Done"}}}}}`
