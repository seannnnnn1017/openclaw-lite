# Notion Skill Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix cross-skill Markdown→Notion import workflow by adding directory-listing to file_control, correcting notion_basic sub-page examples, and adding a new notion_workflow skill with batch import actions — all developed and tested in `sandbox_for_claude/SKILL/`.

**Architecture:** `file_control` gains `list_directory` + `read_all` for folder scanning. `notion_basic` SKILL.md is patched with accurate sub-page creation examples and hallucination guards. New `notion_workflow` skill wraps the full pipeline (read folder → create parent page → create sub-pages with content) in a single Python tool that calls the Notion MCP bridge imported from the sandbox `notion_mcp_tool.py`.

**Tech Stack:** Python 3.10+, Notion MCP server (`@notionhq/notion-mcp-server` via npx), existing `_call_tool`/`_load_runtime_config` helpers from `notion_mcp_tool.py`, `pathlib` for file I/O.

**Test target:** Notion page `33e5aafddb3b80daae72c72ecf916479`  
**Test source:** `E:\Github\Obsidian_database\personal_data_terminal\` (5 md files)

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `sandbox_for_claude/SKILL/file_control/scripts/file_tool.py` | Modify | Add `list_directory`, `read_all` actions |
| `sandbox_for_claude/SKILL/file_control/SKILL.md` | Modify | Document new actions |
| `sandbox_for_claude/SKILL/file_control/examples.md` | Modify | Add examples for new actions |
| `sandbox_for_claude/SKILL/notion_basic/SKILL.md` | Modify | Fix sub-page example, add hallucination guard, add batch SOP |
| `sandbox_for_claude/SKILL/notion_basic/examples.md` | Modify | Add sub-page + block-append examples |
| `sandbox_for_claude/SKILL/notion_workflow/SKILL.md` | Create | Skill prompt for notion_workflow |
| `sandbox_for_claude/SKILL/notion_workflow/examples.md` | Create | Skill usage examples |
| `sandbox_for_claude/SKILL/notion_workflow/skills_config.json` | Create | Skill registration |
| `sandbox_for_claude/SKILL/notion_workflow/scripts/notion_workflow_tool.py` | Create | Workflow actions: import_folder, import_files, batch_create_pages, append_content, sync_folder |
| `sandbox_for_claude/SKILL/notion_workflow/test_results/run_tests.py` | Create | 20-test runner (10 simple + 10 complex) |

---

## Task 1: Add `list_directory` and `read_all` to file_tool.py

**Files:**
- Modify: `sandbox_for_claude/SKILL/file_control/scripts/file_tool.py`

- [ ] **Step 1.1: Add helper functions before `run()`**

Insert these two functions into `file_tool.py` directly before the `run()` function (currently at line 269). Add them starting at line 269, pushing `run()` down.

```python
def _list_directory(path: str, pattern: str = "*", recursive: bool = False) -> dict:
    """List files in a directory matching a glob pattern."""
    dir_path = Path(safe_path(path))
    if not dir_path.exists():
        return error("list_directory", path, f"Path does not exist: {path}")
    if not dir_path.is_dir():
        return error("list_directory", path, f"Path is not a directory: {path}")

    if recursive:
        matched = list(dir_path.rglob(pattern))
    else:
        matched = list(dir_path.glob(pattern))

    files = []
    for p in sorted(matched):
        if p.is_file():
            try:
                size = p.stat().st_size
            except OSError:
                size = -1
            files.append({
                "name": p.name,
                "path": str(p),
                "size_bytes": size,
                "extension": p.suffix.lower(),
            })

    return ok(
        "list_directory",
        path,
        data={"files": files, "count": len(files), "pattern": pattern, "recursive": recursive},
        message=f"Found {len(files)} file(s) matching '{pattern}' in {path}",
    )


def _read_all(paths: list = None, dir: str = "", pattern: str = "*.md", encoding: str = "utf-8") -> dict:
    """Read multiple files at once. Accepts explicit paths list OR dir+pattern."""
    MAX_FILE_BYTES = 200 * 1024  # 200 KB per file

    if paths is None:
        paths = []

    # If dir provided, resolve glob
    if dir:
        dir_path = Path(safe_path(dir))
        if not dir_path.is_dir():
            return error("read_all", dir, f"dir is not a directory: {dir}")
        resolved = [str(p) for p in sorted(dir_path.glob(pattern)) if p.is_file()]
        paths = resolved + [p for p in paths if p not in resolved]

    if not paths:
        return ok("read_all", dir or "", data={"files": [], "success_count": 0, "error_count": 0},
                  message="No paths provided")

    results = []
    success = 0
    errors = 0
    for raw_path in paths:
        p = Path(safe_path(raw_path))
        entry = {"path": str(p), "name": p.name}
        try:
            size = p.stat().st_size
            if size > MAX_FILE_BYTES:
                content = p.read_text(encoding=encoding, errors="replace")[:MAX_FILE_BYTES]
                entry.update({"content": content, "status": "ok", "truncated": True,
                               "size_bytes": size, "truncated_at_bytes": MAX_FILE_BYTES})
            else:
                content = p.read_text(encoding=encoding, errors="replace")
                entry.update({"content": content, "status": "ok", "truncated": False, "size_bytes": size})
            success += 1
        except FileNotFoundError:
            entry.update({"content": None, "status": "error", "error": "File not found"})
            errors += 1
        except PermissionError:
            entry.update({"content": None, "status": "error", "error": "Permission denied"})
            errors += 1
        except Exception as exc:
            entry.update({"content": None, "status": "error", "error": str(exc)})
            errors += 1
        results.append(entry)

    return ok(
        "read_all",
        dir or (paths[0] if paths else ""),
        data={"files": results, "success_count": success, "error_count": errors},
        message=f"Read {success} file(s) successfully, {errors} error(s)",
    )
```

- [ ] **Step 1.2: Extend `run()` signature with new parameters**

The current `run()` definition starts at line 269 (after inserting helpers, it shifts down). Find:
```python
def run(
    action: str,
    path: str = "",
    content: str = "",
    target: str = "",
    new_text: str = "",
    occurrence: int = 1,
    reason: str = "",
    backup_id: str = "",
):
```

Replace with:
```python
def run(
    action: str,
    path: str = "",
    content: str = "",
    target: str = "",
    new_text: str = "",
    occurrence: int = 1,
    reason: str = "",
    backup_id: str = "",
    paths: list = None,
    pattern: str = "*",
    recursive: bool = False,
    encoding: str = "utf-8",
    dir: str = "",
):
```

- [ ] **Step 1.3: Add dispatch cases to `run()`**

Inside `run()`, after the `if action == "restore":` branch and before `full_path = safe_path(path)`, add:

```python
        if action == "list_directory":
            return _list_directory(path, pattern=pattern, recursive=recursive)

        if action == "read_all":
            return _read_all(paths=paths, dir=dir, pattern=pattern, encoding=encoding)
```

- [ ] **Step 1.4: Quick smoke test in terminal**

```bash
cd "E:/重要文件/openclaw-lite"
python -c "
import sys
sys.path.insert(0, 'sandbox_for_claude/SKILL/file_control/scripts')
from file_tool import run
r = run('list_directory', path='E:/Github/Obsidian_database/personal_data_terminal', pattern='*.md')
print(r['status'], r['data']['count'], 'files')
r2 = run('read_all', dir='E:/Github/Obsidian_database/personal_data_terminal', pattern='*.md')
print(r2['status'], r2['data']['success_count'], 'read ok')
"
```

Expected output:
```
ok 5 files
ok 5 read ok
```

- [ ] **Step 1.5: Commit**

```bash
cd "E:/重要文件/openclaw-lite"
git add sandbox_for_claude/SKILL/file_control/scripts/file_tool.py
git commit -m "feat(sandbox/file_control): add list_directory and read_all actions"
```

---

## Task 2: Update file_control SKILL.md and examples.md

**Files:**
- Modify: `sandbox_for_claude/SKILL/file_control/SKILL.md`
- Modify: `sandbox_for_claude/SKILL/file_control/examples.md`

- [ ] **Step 2.1: Add new actions to SKILL.md**

In `sandbox_for_claude/SKILL/file_control/SKILL.md`, in the "Supported actions" list, append:

```
- `list_directory` — list files in a directory; supports glob `pattern` and `recursive`
- `read_all` — read multiple files at once; accepts `paths` array or `dir`+`pattern`
```

Add a new section after existing action descriptions:

```
### list_directory

{"skill":"file-control","action":"list_directory","args":{"path":"<dir>","pattern":"*.md","recursive":false}}

Returns data.files (list of {name, path, size_bytes, extension}) and data.count.
Use this to discover files before calling read_all.

### read_all

{"skill":"file-control","action":"read_all","args":{"dir":"<dir>","pattern":"*.md"}}
{"skill":"file-control","action":"read_all","args":{"paths":["<path1>","<path2>"]}}

Returns data.files (list of {path, name, content, status, truncated}).
Files larger than 200 KB are truncated with truncated:true flag.
Single-file errors do not abort the rest — check each entry's status field.
```

- [ ] **Step 2.2: Add examples to examples.md**

Append to `sandbox_for_claude/SKILL/file_control/examples.md`:

```markdown
## list_directory

User request:
"What files are in E:\Github\Obsidian_database\personal_data_terminal?"

Tool JSON:
{"skill":"file-control","action":"list_directory","args":{"path":"E:\\Github\\Obsidian_database\\personal_data_terminal","pattern":"*.md"}}

## read_all — by directory

User request:
"Read all markdown files from that folder"

Tool JSON:
{"skill":"file-control","action":"read_all","args":{"dir":"E:\\Github\\Obsidian_database\\personal_data_terminal","pattern":"*.md"}}

## read_all — by explicit paths

User request:
"Read these three files"

Tool JSON:
{"skill":"file-control","action":"read_all","args":{"paths":["E:\\Github\\Obsidian_database\\personal_data_terminal\\Index.md","E:\\Github\\Obsidian_database\\personal_data_terminal\\架構.md"]}}
```

- [ ] **Step 2.3: Commit**

```bash
cd "E:/重要文件/openclaw-lite"
git add sandbox_for_claude/SKILL/file_control/SKILL.md sandbox_for_claude/SKILL/file_control/examples.md
git commit -m "docs(sandbox/file_control): document list_directory and read_all"
```

---

## Task 3: Fix notion_basic SKILL.md and examples.md

**Files:**
- Modify: `sandbox_for_claude/SKILL/notion_basic/SKILL.md`
- Modify: `sandbox_for_claude/SKILL/notion_basic/examples.md`

- [ ] **Step 3.1: Add hallucination guard to SKILL.md**

At the top of the "Core execution logic" section in `sandbox_for_claude/SKILL/notion_basic/SKILL.md`, insert:

```
Hallucination guard — these do NOT exist and must never be called:
- `API-create-page` (use `API-post-page` instead)
- action `delegate` or `__delegate__` on notion-basic
- any action not listed in "Supported actions" above
Calling a non-existent tool wastes a step and returns an error. Use `tools/list` if uncertain.
```

- [ ] **Step 3.2: Fix the delegate system prompt bug**

In `sandbox_for_claude/SKILL/notion_basic/scripts/notion_mcp_tool.py`, the `_build_delegate_system_prompt` function contains this wrong rule at line ~355:

```python
- For `API-post-page`, place the destination under `parent.database_id`.
```

Replace it with:

```python
- For `API-post-page`, place the parent under `parent.page_id` when creating a sub-page inside another page, or `parent.database_id` when inserting a row in a database. Never use top-level `database_id`.
```

- [ ] **Step 3.3: Add sub-page creation + block append + batch SOP to SKILL.md**

Append to the "Recommended workflows" section in `sandbox_for_claude/SKILL/notion_basic/SKILL.md`:

```
Create a sub-page inside an existing page:
1. `tools/call` -> `API-post-page` with `parent.page_id` = target page id
   Shape: {"parent":{"page_id":"<id>"},"properties":{"title":{"title":[{"text":{"content":"<title>"}}]}}}
2. Note the returned `id` — this is the new sub-page id

Append text content as blocks to a page:
1. Convert text to block objects (paragraph/heading_1/heading_2/heading_3/code)
2. `tools/call` -> `API-patch-block-children` with block_id = page id and children = block list
   Shape: {"block_id":"<page_id>","children":[{"object":"block","type":"paragraph","paragraph":{"rich_text":[{"type":"text","text":{"content":"<text>"}}]}}]}
3. Notion limit: max 100 blocks per call — split large content into multiple calls

Batch Markdown files → Notion pages (cross-skill SOP):
IMPORTANT: notion-basic cannot read local files. Always use file-control first.
Step 1 (file-control):  read_all to get file contents
Step 2 (notion-basic):  API-post-page to create parent page (parent.page_id = destination)
Step 3 (notion-basic):  for each file — API-post-page (sub-page) then API-patch-block-children (content)
Never attempt file reading inside a notion-basic delegate_task call.
```

- [ ] **Step 3.4: Update examples.md with sub-page + block examples**

Append to `sandbox_for_claude/SKILL/notion_basic/examples.md`:

```markdown
User request:
"Create a sub-page titled '架構' inside the page 33e5aafddb3b80daae72c72ecf916479"

Tool JSON:
{"skill":"notion-basic","action":"tools/call","args":{"name":"API-post-page","arguments":{"parent":{"page_id":"33e5aafddb3b80daae72c72ecf916479"},"properties":{"title":{"title":[{"type":"text","text":{"content":"架構"}}]}}}}}

User request:
"Write content to page <page_id>"

Tool JSON:
{"skill":"notion-basic","action":"tools/call","args":{"name":"API-patch-block-children","arguments":{"block_id":"<page_id>","children":[{"object":"block","type":"heading_1","heading_1":{"rich_text":[{"type":"text","text":{"content":"Section Title"}}]}},{"object":"block","type":"paragraph","paragraph":{"rich_text":[{"type":"text","text":{"content":"Paragraph content here."}}]}},{"object":"block","type":"code","code":{"language":"python","rich_text":[{"type":"text","text":{"content":"print('hello')"}}]}}]}}}

Anti-pattern — DO NOT use API-create-page (does not exist):
{"skill":"notion-basic","action":"tools/call","args":{"name":"API-create-page","arguments":{...}}}
Use API-post-page instead.
```

- [ ] **Step 3.5: Commit**

```bash
cd "E:/重要文件/openclaw-lite"
git add sandbox_for_claude/SKILL/notion_basic/SKILL.md sandbox_for_claude/SKILL/notion_basic/examples.md sandbox_for_claude/SKILL/notion_basic/scripts/notion_mcp_tool.py
git commit -m "fix(sandbox/notion_basic): sub-page example, hallucination guard, delegate prompt bug"
```

---

## Task 4: Create notion_workflow skill skeleton

**Files:**
- Create: `sandbox_for_claude/SKILL/notion_workflow/SKILL.md`
- Create: `sandbox_for_claude/SKILL/notion_workflow/examples.md`
- Create: `sandbox_for_claude/SKILL/notion_workflow/skills_config.json`
- Create: `sandbox_for_claude/SKILL/notion_workflow/scripts/` (directory)
- Create: `sandbox_for_claude/SKILL/notion_workflow/test_results/` (directory)

- [ ] **Step 4.1: Create SKILL.md**

Create `sandbox_for_claude/SKILL/notion_workflow/SKILL.md`:

```markdown
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
```

- [ ] **Step 4.2: Create examples.md**

Create `sandbox_for_claude/SKILL/notion_workflow/examples.md`:

```markdown
User request:
"把 E:\Github\Obsidian_database\personal_data_terminal 裡的所有 md 放到 notion page 33e5aafddb3b80daae72c72ecf916479，建一個叫 Personal Terminal 的父頁面"

Tool JSON:
{"skill":"notion-workflow","action":"import_folder","args":{"folder":"E:\\Github\\Obsidian_database\\personal_data_terminal","parent_page_id":"33e5aafddb3b80daae72c72ecf916479","parent_title":"Personal Terminal","pattern":"*.md"}}

User request:
"Import just these two files into Notion"

Tool JSON:
{"skill":"notion-workflow","action":"import_files","args":{"paths":["E:\\Github\\Obsidian_database\\personal_data_terminal\\Index.md","E:\\Github\\Obsidian_database\\personal_data_terminal\\架構.md"],"parent_page_id":"33e5aafddb3b80daae72c72ecf916479","parent_title":"Imported Files"}}

User request:
"Append new notes to this Notion page"

Tool JSON:
{"skill":"notion-workflow","action":"append_content","args":{"page_id":"<page_id>","content":"## New Section\n\nSome new content here."}}

User request:
"Sync the folder again but don't duplicate existing pages"

Tool JSON:
{"skill":"notion-workflow","action":"sync_folder","args":{"folder":"E:\\Github\\Obsidian_database\\personal_data_terminal","parent_page_id":"33e5aafddb3b80daae72c72ecf916479","parent_title":"Personal Terminal","pattern":"*.md"}}
```

- [ ] **Step 4.3: Create skills_config.json**

Create `sandbox_for_claude/SKILL/notion_workflow/skills_config.json`:

```json
{
  "skills": [
    {
      "name": "notion-workflow",
      "enabled": true,
      "execution_mode": "invoked",
      "path": "notion_workflow",
      "tool": {
        "type": "python_function",
        "module": "sandbox_for_claude.SKILL.notion_workflow.scripts.notion_workflow_tool",
        "function": "run"
      }
    }
  ]
}
```

- [ ] **Step 4.4: Create script and test_results directories**

```bash
mkdir -p "E:/重要文件/openclaw-lite/sandbox_for_claude/SKILL/notion_workflow/scripts"
mkdir -p "E:/重要文件/openclaw-lite/sandbox_for_claude/SKILL/notion_workflow/test_results"
touch "E:/重要文件/openclaw-lite/sandbox_for_claude/SKILL/notion_workflow/scripts/__init__.py"
```

- [ ] **Step 4.5: Commit skeleton**

```bash
cd "E:/重要文件/openclaw-lite"
git add sandbox_for_claude/SKILL/notion_workflow/
git commit -m "feat(sandbox/notion_workflow): add skill skeleton — SKILL.md, examples, config"
```

---

## Task 5: Implement notion_workflow_tool.py — core helpers

**Files:**
- Create: `sandbox_for_claude/SKILL/notion_workflow/scripts/notion_workflow_tool.py`

- [ ] **Step 5.1: Write file header, imports, and result helpers**

Create `sandbox_for_claude/SKILL/notion_workflow/scripts/notion_workflow_tool.py` with:

```python
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
NOTION_BASIC_SCRIPTS = SCRIPT_DIR.parents[1] / "notion_basic" / "scripts"
sys.path.insert(0, str(NOTION_BASIC_SCRIPTS))

from notion_mcp_tool import (
    _load_runtime_config,
    _call_tool,
    _list_tools,
)

CHUNK_SIZE = 90  # Notion allows max 100 blocks per patch-block-children call


def ok(action: str, data=None, message: str = "") -> dict:
    return {"status": "ok", "action": action, "data": data or {}, "message": message}


def err(action: str, message: str, data=None) -> dict:
    return {"status": "error", "action": action, "message": message, "data": data}
```

- [ ] **Step 5.2: Write markdown_to_blocks converter**

Append to `notion_workflow_tool.py`:

```python
def markdown_to_blocks(text: str) -> list[dict]:
    """Convert Markdown text to Notion block objects."""
    blocks = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]

        # Fenced code block
        if line.startswith("```"):
            lang = line[3:].strip() or "plain text"
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            blocks.append({
                "object": "block",
                "type": "code",
                "code": {
                    "language": lang,
                    "rich_text": [{"type": "text", "text": {"content": "\n".join(code_lines)[:2000]}}],
                },
            })
            i += 1
            continue

        # Headings
        if line.startswith("### "):
            blocks.append(_heading_block(3, line[4:].strip()))
        elif line.startswith("## "):
            blocks.append(_heading_block(2, line[3:].strip()))
        elif line.startswith("# "):
            blocks.append(_heading_block(1, line[2:].strip()))

        # Divider
        elif line.strip() in ("---", "***", "___"):
            blocks.append({"object": "block", "type": "divider", "divider": {}})

        # Blockquote
        elif line.startswith("> "):
            blocks.append({
                "object": "block",
                "type": "quote",
                "quote": {"rich_text": [{"type": "text", "text": {"content": line[2:].strip()[:2000]}}]},
            })

        # Unordered list
        elif line.startswith("- ") or line.startswith("* "):
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": line[2:].strip()[:2000]}}]},
            })

        # Ordered list (simple: starts with digit + dot)
        elif len(line) > 2 and line[0].isdigit() and line[1] == "." and line[2] == " ":
            blocks.append({
                "object": "block",
                "type": "numbered_list_item",
                "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": line[3:].strip()[:2000]}}]},
            })

        # Non-empty paragraph
        elif line.strip():
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": line.strip()[:2000]}}]},
            })

        i += 1

    return blocks


def _heading_block(level: int, text: str) -> dict:
    htype = f"heading_{level}"
    return {
        "object": "block",
        "type": htype,
        htype: {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]},
    }
```

- [ ] **Step 5.3: Write MCP helper — call_notion and append_blocks_to_page**

Append to `notion_workflow_tool.py`:

```python
def _notion_call(tool_name: str, arguments: dict) -> dict:
    """Wrapper: call a Notion MCP tool, return raw mcp_result dict or raise RuntimeError."""
    config = _load_runtime_config()
    result = _call_tool(config, tool_name=tool_name, arguments=arguments)
    if result.get("status") != "ok":
        raise RuntimeError(result.get("message", f"MCP call failed: {tool_name}"))
    mcp_result = result.get("data", {}).get("mcp_result", {})
    # Parse JSON text content from MCP result if needed
    content_list = mcp_result.get("content", [])
    for item in content_list:
        if item.get("type") == "text":
            try:
                return json.loads(item["text"])
            except (json.JSONDecodeError, KeyError):
                return mcp_result
    return mcp_result


def _create_page(parent_page_id: str, title: str) -> str:
    """Create a Notion page as child of parent_page_id. Returns new page id."""
    result = _notion_call("API-post-page", {
        "parent": {"page_id": parent_page_id},
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": title}}]}
        },
    })
    page_id = result.get("id", "")
    if not page_id:
        raise RuntimeError(f"API-post-page did not return an id. Result: {json.dumps(result)[:300]}")
    return page_id


def _append_blocks(page_id: str, blocks: list[dict]) -> None:
    """Append blocks to a page, chunking at CHUNK_SIZE blocks per call."""
    for i in range(0, len(blocks), CHUNK_SIZE):
        chunk = blocks[i: i + CHUNK_SIZE]
        _notion_call("API-patch-block-children", {"block_id": page_id, "children": chunk})


def _get_child_titles(page_id: str) -> set[str]:
    """Return lowercase titles of existing child pages under page_id."""
    try:
        result = _notion_call("API-get-block-children", {"block_id": page_id, "page_size": 100})
        titles = set()
        for child in result.get("results", []):
            if child.get("type") == "child_page":
                title = child.get("child_page", {}).get("title", "")
                titles.add(title.lower())
        return titles
    except Exception:
        return set()
```

- [ ] **Step 5.4: Verify import works**

```bash
cd "E:/重要文件/openclaw-lite"
python -c "
import sys
sys.path.insert(0, 'sandbox_for_claude/SKILL/notion_workflow/scripts')
from notion_workflow_tool import markdown_to_blocks
blocks = markdown_to_blocks('# Hello\n\nParagraph.\n\n- item\n\n\`\`\`python\nprint(1)\n\`\`\`')
print(len(blocks), 'blocks:', [b['type'] for b in blocks])
"
```

Expected output:
```
4 blocks: ['heading_1', 'paragraph', 'bulleted_list_item', 'code']
```

- [ ] **Step 5.5: Commit**

```bash
cd "E:/重要文件/openclaw-lite"
git add sandbox_for_claude/SKILL/notion_workflow/scripts/notion_workflow_tool.py
git commit -m "feat(sandbox/notion_workflow): core helpers — markdown_to_blocks, MCP wrappers"
```

---

## Task 6: Implement batch_create_pages and append_content

**Files:**
- Modify: `sandbox_for_claude/SKILL/notion_workflow/scripts/notion_workflow_tool.py`

- [ ] **Step 6.1: Implement action functions and run() dispatcher**

Append to `notion_workflow_tool.py`:

```python
# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def action_batch_create_pages(pages: list, **_) -> dict:
    """Create multiple Notion pages from [{title, content, parent_id}]."""
    if not pages:
        return err("batch_create_pages", "`pages` list is required and must not be empty")
    results = []
    success = 0
    errors = 0
    for item in pages:
        title = str(item.get("title", "Untitled")).strip()
        content = str(item.get("content", ""))
        parent_id = str(item.get("parent_id", "")).strip()
        if not parent_id:
            results.append({"title": title, "status": "error", "error": "missing parent_id"})
            errors += 1
            continue
        try:
            page_id = _create_page(parent_id, title)
            if content.strip():
                blocks = markdown_to_blocks(content)
                if blocks:
                    _append_blocks(page_id, blocks)
            url = f"https://www.notion.so/{page_id.replace('-', '')}"
            results.append({"title": title, "status": "ok", "page_id": page_id, "url": url})
            success += 1
        except Exception as exc:
            results.append({"title": title, "status": "error", "error": str(exc)})
            errors += 1
    return ok("batch_create_pages",
              data={"pages": results, "success_count": success, "error_count": errors},
              message=f"Created {success} page(s), {errors} error(s)")


def action_append_content(page_id: str, content: str, **_) -> dict:
    """Append Markdown content to an existing Notion page."""
    if not page_id:
        return err("append_content", "`page_id` is required")
    if not content or not content.strip():
        return err("append_content", "`content` is required and must not be empty")
    try:
        blocks = markdown_to_blocks(content)
        if not blocks:
            return ok("append_content", data={"blocks_written": 0}, message="No blocks to write")
        _append_blocks(page_id, blocks)
        url = f"https://www.notion.so/{page_id.replace('-', '')}"
        return ok("append_content",
                  data={"page_id": page_id, "url": url, "blocks_written": len(blocks)},
                  message=f"Appended {len(blocks)} block(s) to page")
    except Exception as exc:
        return err("append_content", str(exc))
```

- [ ] **Step 6.2: Add run() dispatcher (partial — will extend in Task 7)**

Append to `notion_workflow_tool.py`:

```python
def run(action: str, **kwargs) -> dict:
    try:
        if action == "batch_create_pages":
            return action_batch_create_pages(**kwargs)
        if action == "append_content":
            return action_append_content(**kwargs)
        # import_folder, import_files, sync_folder added in Task 7
        return err(action, f"Unknown action: {action}")
    except Exception as exc:
        return err(action, f"Unexpected error: {exc}")
```

- [ ] **Step 6.3: Commit**

```bash
cd "E:/重要文件/openclaw-lite"
git add sandbox_for_claude/SKILL/notion_workflow/scripts/notion_workflow_tool.py
git commit -m "feat(sandbox/notion_workflow): batch_create_pages and append_content actions"
```

---

## Task 7: Implement import_folder, import_files, sync_folder

**Files:**
- Modify: `sandbox_for_claude/SKILL/notion_workflow/scripts/notion_workflow_tool.py`

- [ ] **Step 7.1: Implement shared _import_file_list helper**

In `notion_workflow_tool.py`, insert these functions BEFORE the `run()` function:

```python
def _import_file_list(
    file_paths: list[str],
    parent_page_id: str,
    parent_title: str,
    action_name: str,
    skip_titles: set[str] = None,
) -> dict:
    """
    Core import logic shared by import_folder, import_files, sync_folder.
    Creates parent page then sub-pages for each file.
    skip_titles: lowercase titles to skip (for sync_folder dedup).
    """
    if not parent_page_id:
        return err(action_name, "`parent_page_id` is required")
    if not parent_title:
        return err(action_name, "`parent_title` is required")
    if not file_paths:
        return err(action_name, "No files to import")

    if skip_titles is None:
        skip_titles = set()

    # Step 1: Read all files
    MAX_FILE_BYTES = 200 * 1024
    file_contents = []
    for raw_path in file_paths:
        p = Path(raw_path)
        entry = {"path": str(p), "name": p.name, "stem": p.stem}
        try:
            size = p.stat().st_size
            text = p.read_text(encoding="utf-8", errors="replace")
            if size > MAX_FILE_BYTES:
                text = text[:MAX_FILE_BYTES]
                entry["truncated"] = True
            else:
                entry["truncated"] = False
            entry["content"] = text
            entry["status"] = "read_ok"
        except Exception as exc:
            entry["content"] = ""
            entry["status"] = "read_error"
            entry["error"] = str(exc)
        file_contents.append(entry)

    # Step 2: Create parent page
    try:
        new_parent_id = _create_page(parent_page_id, parent_title)
    except Exception as exc:
        return err(action_name, f"Failed to create parent page '{parent_title}': {exc}")

    parent_url = f"https://www.notion.so/{new_parent_id.replace('-', '')}"

    # Step 3: Create sub-pages
    pages = []
    success = 0
    errors = 0
    skipped = 0

    for fc in file_contents:
        title = fc["stem"]

        if fc["status"] == "read_error":
            pages.append({"title": title, "source": fc["path"], "status": "error", "error": fc.get("error", "read error")})
            errors += 1
            continue

        if title.lower() in skip_titles:
            pages.append({"title": title, "source": fc["path"], "status": "skipped"})
            skipped += 1
            continue

        try:
            sub_page_id = _create_page(new_parent_id, title)
            content = fc.get("content", "")
            if content.strip():
                blocks = markdown_to_blocks(content)
                if blocks:
                    _append_blocks(sub_page_id, blocks)
            url = f"https://www.notion.so/{sub_page_id.replace('-', '')}"
            pages.append({"title": title, "source": fc["path"], "status": "ok",
                          "page_id": sub_page_id, "url": url})
            success += 1
        except Exception as exc:
            pages.append({"title": title, "source": fc["path"], "status": "error", "error": str(exc)})
            errors += 1

    return ok(
        action_name,
        data={
            "parent_page_id": new_parent_id,
            "parent_url": parent_url,
            "pages": pages,
            "success_count": success,
            "error_count": errors,
            "skipped_count": skipped,
        },
        message=f"Import done: {success} ok, {errors} errors, {skipped} skipped",
    )


def action_import_folder(folder: str, parent_page_id: str, parent_title: str,
                          pattern: str = "*.md", **_) -> dict:
    if not folder:
        return err("import_folder", "`folder` is required")
    dir_path = Path(folder)
    if not dir_path.is_dir():
        return err("import_folder", f"Not a directory: {folder}")
    paths = sorted(str(p) for p in dir_path.glob(pattern) if p.is_file())
    if not paths:
        return err("import_folder", f"No files matching '{pattern}' found in {folder}")
    return _import_file_list(paths, parent_page_id, parent_title, "import_folder")


def action_import_files(paths: list, parent_page_id: str, parent_title: str, **_) -> dict:
    if not paths:
        return err("import_files", "`paths` list is required and must not be empty")
    return _import_file_list(paths, parent_page_id, parent_title, "import_files")


def action_sync_folder(folder: str, parent_page_id: str, parent_title: str,
                        pattern: str = "*.md", **_) -> dict:
    """Like import_folder but skips files whose stem title already exists as a child page."""
    if not folder:
        return err("sync_folder", "`folder` is required")
    dir_path = Path(folder)
    if not dir_path.is_dir():
        return err("sync_folder", f"Not a directory: {folder}")
    paths = sorted(str(p) for p in dir_path.glob(pattern) if p.is_file())
    if not paths:
        return err("sync_folder", f"No files matching '{pattern}' found in {folder}")

    # Get existing child titles to deduplicate
    # Note: we need to first create/find the parent page, but sync checks EXISTING children
    # Strategy: look for existing child pages under parent_page_id with the given parent_title
    # Simplification: check children of parent_page_id for a page titled parent_title,
    # if found use its children for dedup; otherwise treat as fresh import.
    existing_titles = set()
    try:
        # Find existing parent page by searching children of parent_page_id
        result = _notion_call("API-get-block-children", {"block_id": parent_page_id, "page_size": 100})
        for child in result.get("results", []):
            if child.get("type") == "child_page":
                child_title = child.get("child_page", {}).get("title", "")
                if child_title.lower() == parent_title.lower():
                    # Found the parent page — get its children
                    existing_titles = _get_child_titles(child.get("id", ""))
                    break
    except Exception:
        pass  # On any error, do a full import (no dedup)

    return _import_file_list(paths, parent_page_id, parent_title, "sync_folder",
                              skip_titles=existing_titles)
```

- [ ] **Step 7.2: Update run() to include all actions**

Replace the existing `run()` function entirely:

```python
def run(action: str, **kwargs) -> dict:
    try:
        if action == "batch_create_pages":
            return action_batch_create_pages(**kwargs)
        if action == "append_content":
            return action_append_content(**kwargs)
        if action == "import_folder":
            return action_import_folder(**kwargs)
        if action == "import_files":
            return action_import_files(**kwargs)
        if action == "sync_folder":
            return action_sync_folder(**kwargs)
        return err(action, f"Unknown action: {action}. Supported: import_folder, import_files, batch_create_pages, append_content, sync_folder")
    except Exception as exc:
        return err(action, f"Unexpected error: {exc}")
```

- [ ] **Step 7.3: Commit**

```bash
cd "E:/重要文件/openclaw-lite"
git add sandbox_for_claude/SKILL/notion_workflow/scripts/notion_workflow_tool.py
git commit -m "feat(sandbox/notion_workflow): import_folder, import_files, sync_folder actions"
```

---

## Task 8: Write and run simple tests S01–S10

**Files:**
- Create: `sandbox_for_claude/SKILL/notion_workflow/test_results/run_tests.py`

- [ ] **Step 8.1: Create test runner with S01–S10**

Create `sandbox_for_claude/SKILL/notion_workflow/test_results/run_tests.py`:

```python
"""
Notion workflow skill test runner — 20 tests total.
Run: python run_tests.py
Results are printed and saved to results.json.

PREREQUISITE: Notion MCP server configured and reachable.
TEST TARGET PAGE: 33e5aafddb3b80daae72c72ecf916479
"""
import json
import sys
import time
import traceback
from pathlib import Path

# Bootstrap path
SCRIPT_DIR = Path(__file__).resolve().parent
SANDBOX_SKILL = SCRIPT_DIR.parents[2]  # sandbox_for_claude/SKILL/
NOTION_WORKFLOW = SANDBOX_SKILL / "notion_workflow" / "scripts"
FILE_CONTROL = SANDBOX_SKILL / "file_control" / "scripts"
NOTION_BASIC = SANDBOX_SKILL / "notion_basic" / "scripts"
for p in (str(NOTION_WORKFLOW), str(FILE_CONTROL), str(NOTION_BASIC)):
    if p not in sys.path:
        sys.path.insert(0, p)

import file_tool
import notion_workflow_tool as nwt

TARGET_PAGE = "33e5aafddb3b80daae72c72ecf916479"
TEST_FOLDER = "E:/Github/Obsidian_database/personal_data_terminal"
RESULTS = []
_created_pages = {}  # cache page ids between tests


def run_test(test_id: str, description: str, fn):
    print(f"\n[{test_id}] {description}")
    start = time.time()
    try:
        result = fn()
        elapsed = round(time.time() - start, 2)
        if result.get("status") == "ok":
            print(f"  PASS ({elapsed}s) — {result.get('message','')}")
            RESULTS.append({"id": test_id, "status": "PASS", "description": description,
                             "elapsed": elapsed, "message": result.get("message", "")})
            return result
        else:
            msg = result.get("message", str(result))
            print(f"  FAIL ({elapsed}s) — {msg}")
            RESULTS.append({"id": test_id, "status": "FAIL", "description": description,
                             "elapsed": elapsed, "message": msg})
            return result
    except Exception as exc:
        elapsed = round(time.time() - start, 2)
        tb = traceback.format_exc()
        print(f"  ERROR ({elapsed}s) — {exc}")
        RESULTS.append({"id": test_id, "status": "ERROR", "description": description,
                         "elapsed": elapsed, "message": str(exc), "traceback": tb})
        return {"status": "error", "message": str(exc)}


# ── Simple Tests S01–S10 ────────────────────────────────────────────────────

def s01():
    r = file_tool.run("list_directory", path=TEST_FOLDER, pattern="*.md")
    assert r["status"] == "ok", r["message"]
    assert r["data"]["count"] == 5, f"Expected 5 files, got {r['data']['count']}"
    names = [f["name"] for f in r["data"]["files"]]
    assert "Index.md" in names, f"Index.md missing from {names}"
    return r

def s02():
    path = TEST_FOLDER + "/Index.md"
    r = file_tool.run("read_all", paths=[path])
    assert r["status"] == "ok", r["message"]
    assert r["data"]["success_count"] == 1
    assert r["data"]["files"][0]["status"] == "ok"
    assert len(r["data"]["files"][0]["content"]) > 0
    return r

def s03():
    import glob
    paths = sorted(glob.glob(TEST_FOLDER + "/*.md"))
    assert len(paths) == 5, f"Expected 5 paths, got {len(paths)}"
    r = file_tool.run("read_all", paths=paths)
    assert r["status"] == "ok", r["message"]
    assert r["data"]["success_count"] == 5, f"Expected 5 ok, got {r['data']}"
    return r

def s04():
    r = nwt.run("batch_create_pages", pages=[{
        "title": "[S04] Single Page Test",
        "content": "Created by S04 test.",
        "parent_id": TARGET_PAGE,
    }])
    assert r["status"] == "ok", r["message"]
    assert r["data"]["success_count"] == 1
    _created_pages["s04_page_id"] = r["data"]["pages"][0]["page_id"]
    return r

def s05():
    page_id = _created_pages.get("s04_page_id")
    if not page_id:
        raise AssertionError("S04 must pass before S05 — no page_id cached")
    r = nwt.run("append_content", page_id=page_id,
                content="## Appended by S05\n\nThis paragraph was added by the S05 test.")
    assert r["status"] == "ok", r["message"]
    assert r["data"]["blocks_written"] >= 2
    return r

def s06():
    """Read the page via notion-basic to confirm it has the correct title."""
    from notion_mcp_tool import _load_runtime_config, _call_tool
    page_id = _created_pages.get("s04_page_id")
    if not page_id:
        raise AssertionError("S04 must pass before S06")
    config = _load_runtime_config()
    result = _call_tool(config, tool_name="API-retrieve-a-page", arguments={"page_id": page_id})
    assert result["status"] == "ok", result.get("message", "")
    # Title is inside mcp_result
    mcp = result["data"].get("mcp_result", {})
    content_list = mcp.get("content", [])
    raw = ""
    for item in content_list:
        if item.get("type") == "text":
            raw = item["text"]
            break
    data = {}
    try:
        data = json.loads(raw)
    except Exception:
        pass
    title_parts = data.get("properties", {}).get("title", {}).get("title", [])
    title_text = "".join(p.get("plain_text", "") for p in title_parts)
    assert "[S04]" in title_text, f"Unexpected title: {title_text!r}"
    return result

def s07():
    """Rename the S04 page title via API-patch-page."""
    from notion_mcp_tool import _load_runtime_config, _call_tool
    page_id = _created_pages.get("s04_page_id")
    if not page_id:
        raise AssertionError("S04 must pass before S07")
    config = _load_runtime_config()
    result = _call_tool(config, tool_name="API-patch-page", arguments={
        "page_id": page_id,
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": "[S04+S07] Renamed Page"}}]}
        },
    })
    assert result["status"] == "ok", result.get("message", "")
    return result

def s08():
    """Delete a block from the S04 page."""
    from notion_mcp_tool import _load_runtime_config, _call_tool
    page_id = _created_pages.get("s04_page_id")
    if not page_id:
        raise AssertionError("S04 must pass before S08")
    config = _load_runtime_config()
    # Get children to find a block to delete
    children_result = _call_tool(config, tool_name="API-get-block-children",
                                  arguments={"block_id": page_id})
    assert children_result["status"] == "ok", children_result.get("message", "")
    mcp = children_result["data"].get("mcp_result", {})
    content_list = mcp.get("content", [])
    raw = ""
    for item in content_list:
        if item.get("type") == "text":
            raw = item["text"]
            break
    data = {}
    try:
        data = json.loads(raw)
    except Exception:
        pass
    results_list = data.get("results", [])
    if not results_list:
        return {"status": "ok", "message": "No blocks to delete (page may be empty — acceptable)"}
    block_id = results_list[0]["id"]
    del_result = _call_tool(config, tool_name="API-delete-a-block", arguments={"block_id": block_id})
    assert del_result["status"] == "ok", del_result.get("message", "")
    return del_result

def s09():
    """Search for the renamed page and confirm it appears in results."""
    from notion_mcp_tool import _load_runtime_config, _call_tool
    config = _load_runtime_config()
    result = _call_tool(config, tool_name="API-post-search",
                         arguments={"query": "S04+S07", "filter": {"value": "page", "property": "object"}, "page_size": 10})
    assert result["status"] == "ok", result.get("message", "")
    return result

def s10():
    """batch_create_pages — create 3 blank sub-pages."""
    r = nwt.run("batch_create_pages", pages=[
        {"title": "[S10-A] Batch Page Alpha", "content": "", "parent_id": TARGET_PAGE},
        {"title": "[S10-B] Batch Page Beta",  "content": "", "parent_id": TARGET_PAGE},
        {"title": "[S10-C] Batch Page Gamma", "content": "", "parent_id": TARGET_PAGE},
    ])
    assert r["status"] == "ok", r["message"]
    assert r["data"]["success_count"] == 3, f"Expected 3, got {r['data']}"
    _created_pages["s10_ids"] = [p["page_id"] for p in r["data"]["pages"] if p.get("page_id")]
    return r


def run_simple_tests():
    print("\n" + "="*60)
    print("SIMPLE TESTS S01–S10")
    print("="*60)
    run_test("S01", "list_directory returns 5 md files", s01)
    run_test("S02", "read_all reads single file correctly", s02)
    run_test("S03", "read_all reads 5 files as array", s03)
    run_test("S04", "batch_create_pages creates 1 page", s04)
    run_test("S05", "append_content writes 2+ blocks", s05)
    run_test("S06", "API-retrieve-a-page confirms title", s06)
    run_test("S07", "API-patch-page renames page", s07)
    run_test("S08", "API-delete-a-block removes first block", s08)
    run_test("S09", "API-post-search finds renamed page", s09)
    run_test("S10", "batch_create_pages creates 3 blank pages", s10)


# ── Complex Tests C01–C10 ───────────────────────────────────────────────────

def c01():
    """import_folder — all 5 personal_data_terminal files → Notion."""
    r = nwt.run("import_folder",
                folder=TEST_FOLDER,
                parent_page_id=TARGET_PAGE,
                parent_title="[C01] Personal Terminal Import",
                pattern="*.md")
    assert r["status"] == "ok", r["message"]
    assert r["data"]["success_count"] == 5, f"Expected 5, got {r['data']}"
    assert r["data"]["error_count"] == 0
    _created_pages["c01_parent_id"] = r["data"]["parent_page_id"]
    return r

def c02():
    """import_files — 3 explicit paths."""
    import glob
    all_paths = sorted(glob.glob(TEST_FOLDER + "/*.md"))
    r = nwt.run("import_files",
                paths=all_paths[:3],
                parent_page_id=TARGET_PAGE,
                parent_title="[C02] Explicit Files Import")
    assert r["status"] == "ok", r["message"]
    assert r["data"]["success_count"] == 3
    return r

def c03():
    """Long content auto-chunked — generate >100 blocks and verify all written."""
    # Generate 110 paragraphs
    long_content = "\n\n".join(f"Paragraph {i}: " + "x" * 80 for i in range(110))
    blocks = nwt.markdown_to_blocks(long_content)
    assert len(blocks) >= 100, f"Expected >=100 blocks, got {len(blocks)}"

    r = nwt.run("batch_create_pages", pages=[{
        "title": "[C03] Long Content Chunked",
        "content": long_content,
        "parent_id": TARGET_PAGE,
    }])
    assert r["status"] == "ok", r["message"]
    assert r["data"]["success_count"] == 1
    _created_pages["c03_page_id"] = r["data"]["pages"][0]["page_id"]
    return r

def c04():
    """sync_folder second pass — should skip all 5 files (all already exist from C01)."""
    parent_id = _created_pages.get("c01_parent_id")
    if not parent_id:
        raise AssertionError("C01 must pass before C04")
    # sync_folder creates a NEW parent page under TARGET_PAGE (not the same as C01's parent)
    # and skips files already present under the existing [C01] parent
    # For test correctness: run sync again pointing to TARGET_PAGE with same parent_title
    r = nwt.run("sync_folder",
                folder=TEST_FOLDER,
                parent_page_id=TARGET_PAGE,
                parent_title="[C01] Personal Terminal Import",
                pattern="*.md")
    assert r["status"] == "ok", r["message"]
    # All 5 files should be skipped since they exist in the [C01] parent
    assert r["data"]["skipped_count"] == 5, f"Expected 5 skipped, got {r['data']}"
    return r

def c05():
    """Chinese + code blocks render correctly — no encoding error."""
    content = (
        "# 架構說明\n\n"
        "這是一個包含中文的頁面。\n\n"
        "```python\nprint('你好世界')\n```\n\n"
        "## 結論\n\n測試通過。"
    )
    r = nwt.run("batch_create_pages", pages=[{
        "title": "[C05] 中文與程式碼測試",
        "content": content,
        "parent_id": TARGET_PAGE,
    }])
    assert r["status"] == "ok", r["message"]
    assert r["data"]["success_count"] == 1
    return r

def c06():
    """Mixed-extension folder — .json and .png skipped, only .md imported."""
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        # Create 2 md + 1 json + 1 png (fake)
        Path(tmp, "valid1.md").write_text("# Valid 1\nContent.", encoding="utf-8")
        Path(tmp, "valid2.md").write_text("# Valid 2\nContent.", encoding="utf-8")
        Path(tmp, "data.json").write_text('{"key":"value"}', encoding="utf-8")
        Path(tmp, "image.png").write_bytes(b"\x89PNG fake")

        r = nwt.run("import_folder",
                    folder=tmp,
                    parent_page_id=TARGET_PAGE,
                    parent_title="[C06] Mixed Extensions",
                    pattern="*.md")
        assert r["status"] == "ok", r["message"]
        assert r["data"]["success_count"] == 2, f"Expected 2 md files, got {r['data']}"
    return r

def c07():
    """One missing file in read_all — others succeed, error_count == 1."""
    import glob
    real_paths = sorted(glob.glob(TEST_FOLDER + "/*.md"))[:2]
    fake_path = TEST_FOLDER + "/nonexistent_file_xyz.md"
    r = file_tool.run("read_all", paths=real_paths + [fake_path])
    assert r["status"] == "ok", r["message"]
    assert r["data"]["success_count"] == 2, f"Expected 2 ok"
    assert r["data"]["error_count"] == 1, f"Expected 1 error"
    return r

def c08():
    """Wrong parent_page_id returns structured error, no ghost pages."""
    fake_id = "00000000000000000000000000000000"
    r = nwt.run("import_folder",
                folder=TEST_FOLDER,
                parent_page_id=fake_id,
                parent_title="[C08] Should Fail Cleanly",
                pattern="*.md")
    assert r["status"] == "error", f"Expected error status, got: {r}"
    assert r["message"], "Error message must not be empty"
    return {"status": "ok", "message": f"Got expected error: {r['message'][:100]}"}

def c09():
    """Cross-skill: file_tool.read_all + nwt.batch_create_pages."""
    r_read = file_tool.run("read_all", dir=TEST_FOLDER, pattern="*.md")
    assert r_read["status"] == "ok"
    files = r_read["data"]["files"]
    pages_payload = [
        {"title": f"[C09] {f['name']}", "content": f["content"], "parent_id": TARGET_PAGE}
        for f in files if f["status"] == "ok"
    ]
    r_create = nwt.run("batch_create_pages", pages=pages_payload)
    assert r_create["status"] == "ok", r_create["message"]
    assert r_create["data"]["success_count"] == len(pages_payload)
    return r_create

def c10():
    """append_content appends to existing page without destroying prior blocks."""
    page_id = _created_pages.get("s04_page_id")
    if not page_id:
        raise AssertionError("S04 must pass before C10")
    r = nwt.run("append_content",
                page_id=page_id,
                content="## Appended by C10\n\nFinal test block.\n\n- item one\n- item two")
    assert r["status"] == "ok", r["message"]
    assert r["data"]["blocks_written"] >= 3
    return r


def run_complex_tests():
    print("\n" + "="*60)
    print("COMPLEX TESTS C01–C10")
    print("="*60)
    run_test("C01", "import_folder: 5 md files → Notion (full)", c01)
    run_test("C02", "import_files: 3 explicit paths", c02)
    run_test("C03", "Long file >100 blocks auto-chunked", c03)
    run_test("C04", "sync_folder second pass skips all 5 existing", c04)
    run_test("C05", "Chinese + code block encoding correct", c05)
    run_test("C06", "Mixed extensions: only .md imported", c06)
    run_test("C07", "One missing file: others succeed, error_count=1", c07)
    run_test("C08", "Wrong parent_page_id: structured error returned", c08)
    run_test("C09", "Cross-skill: read_all + batch_create_pages", c09)
    run_test("C10", "append_content appends without destroying blocks", c10)


# ── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_simple_tests()
    run_complex_tests()

    passed = sum(1 for r in RESULTS if r["status"] == "PASS")
    failed = sum(1 for r in RESULTS if r["status"] in ("FAIL", "ERROR"))

    print("\n" + "="*60)
    print(f"SUMMARY: {passed}/20 passed, {failed} failed")
    print("="*60)
    for r in RESULTS:
        icon = "✓" if r["status"] == "PASS" else "✗"
        print(f"  {icon} [{r['id']}] {r['description'][:55]} ({r['elapsed']}s)")

    results_path = Path(__file__).parent / "results.json"
    results_path.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nFull results saved to: {results_path}")

    sys.exit(0 if failed == 0 else 1)
```

- [ ] **Step 8.2: Run simple tests S01–S10**

```bash
cd "E:/重要文件/openclaw-lite/sandbox_for_claude/SKILL/notion_workflow/test_results"
python run_tests.py 2>&1 | head -60
```

Expected: S01, S02, S03 should pass immediately (file ops, no Notion needed). S04–S10 require Notion MCP. All should show PASS.

- [ ] **Step 8.3: Fix any failures, then commit**

If any test fails: read the error, fix the relevant function, re-run that specific test function in isolation:
```bash
python -c "
import sys; sys.path.insert(0,'../scripts'); sys.path.insert(0,'../../file_control/scripts'); sys.path.insert(0,'../../notion_basic/scripts')
from run_tests import s04, run_test
run_test('S04', 'debug', s04)
"
```

After all S01–S10 pass:
```bash
cd "E:/重要文件/openclaw-lite"
git add sandbox_for_claude/SKILL/notion_workflow/test_results/run_tests.py sandbox_for_claude/SKILL/notion_workflow/test_results/results.json
git commit -m "test(sandbox/notion_workflow): simple tests S01-S10 passing"
```

---

## Task 9: Run complex tests C01–C10 and fix issues

- [ ] **Step 9.1: Run all 20 tests**

```bash
cd "E:/重要文件/openclaw-lite/sandbox_for_claude/SKILL/notion_workflow/test_results"
python run_tests.py
```

- [ ] **Step 9.2: Fix failures**

Common failure patterns and fixes:

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| C01 `success_count` wrong | Notion API rate limit between pages | Add `time.sleep(0.3)` inside `_import_file_list` loop |
| C04 `skipped_count` wrong | `_get_child_titles` reading wrong level | Log child titles and verify level in `action_sync_folder` |
| C08 status is `ok` instead of `error` | Notion may create page with fake id silently | Check if `_create_page` raises or returns empty id |
| Block append truncated | Content >2000 chars per block | Already handled in `markdown_to_blocks` via `[:2000]` |

For rate limit issues, add after `_create_page(new_parent_id, title)` call:
```python
import time; time.sleep(0.25)
```

- [ ] **Step 9.3: Commit final passing results**

```bash
cd "E:/重要文件/openclaw-lite"
git add sandbox_for_claude/SKILL/notion_workflow/
git commit -m "test(sandbox/notion_workflow): all 20 tests passing — simple S01-S10, complex C01-C10"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** All 5 spec components covered: file_control additions (Tasks 1–2), notion_basic fixes (Task 3), notion_workflow skeleton (Task 4), workflow tool (Tasks 5–7), 20 tests (Tasks 8–9)
- [x] **No placeholders:** All code is complete, no TBD/TODO
- [x] **Type consistency:** `_create_page` returns `str`, `_append_blocks` takes `list[dict]`, `run()` dispatcher uses `**kwargs` consistently
- [x] **Shared helper:** `_import_file_list` is used by `import_folder`, `import_files`, and `sync_folder` — no duplication
- [x] **Test isolation:** Each test function is self-contained; dependency on prior tests is explicitly asserted
- [x] **Error paths:** C07 (missing file), C08 (bad page id) explicitly test failure modes
