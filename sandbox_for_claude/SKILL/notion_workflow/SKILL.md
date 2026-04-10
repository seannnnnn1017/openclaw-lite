---
name: notion-workflow
description: High-level Notion import workflows — copy local folders and files to Notion pages in one call
user-invocable: true
command-dispatch: tool
command-tool: notion_workflow_tool
command-arg-mode: raw
metadata: { "openclaw": { "requires": { "bins": ["python"] } } }
---

Use this skill when the user wants to bulk-import local files into Notion, sync a folder to Notion pages, or create multiple Notion pages from local content in one operation.

This skill handles the full pipeline internally: reading files, creating the parent page, creating sub-pages, and writing block content. You do not need to call file-control or notion-basic separately for bulk operations.

Base JSON shape:

{"skill":"notion-workflow","action":"<action>","args":{...}}

Supported actions:
- `import_folder` — read all matching files from a local folder and create a parent page with sub-pages
- `import_files` — same as import_folder but with an explicit list of file paths
- `batch_create_pages` — create multiple Notion pages from a list of {title, content, parent_id} objects
- `append_content` — append Markdown text to an existing Notion page (auto-chunks at 90 blocks)
- `sync_folder` — like import_folder but skips files whose title already exists as a child page

import_folder shape:
{"skill":"notion-workflow","action":"import_folder","args":{"folder":"<local_folder_path>","parent_page_id":"<notion_page_id>","parent_title":"<new_parent_page_title>","pattern":"*.md"}}

import_files shape:
{"skill":"notion-workflow","action":"import_files","args":{"paths":["<path1>","<path2>"],"parent_page_id":"<notion_page_id>","parent_title":"<new_parent_page_title>"}}

batch_create_pages shape:
{"skill":"notion-workflow","action":"batch_create_pages","args":{"pages":[{"title":"<title>","content":"<markdown_text>","parent_id":"<page_id>"}]}}

append_content shape:
{"skill":"notion-workflow","action":"append_content","args":{"page_id":"<notion_page_id>","content":"<markdown_text>"}}

sync_folder shape:
{"skill":"notion-workflow","action":"sync_folder","args":{"folder":"<local_folder_path>","parent_page_id":"<notion_page_id>","parent_title":"<new_parent_page_title>","pattern":"*.md"}}

Result shape:
All actions return {"status":"ok","action":"<action>","data":{...},"message":"<summary>"} on success.
On partial failures (some pages fail), status is still "ok" but data.error_count > 0 and data.pages contains per-page status.
On total failure (e.g. bad parent_page_id), status is "error" with a message.

Rules:
- Do not call notion-basic or file-control separately for bulk imports — use this skill directly.
- parent_page_id is the Notion page where the new parent page (or pages) will be created as children.
- pattern defaults to "*.md" for folder actions.
- Non-matching files (e.g. .json, .png) are silently skipped and counted in data.skipped_count.
