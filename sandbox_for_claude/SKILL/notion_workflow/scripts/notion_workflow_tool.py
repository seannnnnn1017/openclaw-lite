from __future__ import annotations

import json
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
NOTION_BASIC_SCRIPTS = SCRIPT_DIR.parents[1] / "notion_basic" / "scripts"
sys.path.insert(0, str(NOTION_BASIC_SCRIPTS))

from notion_mcp_tool import (
    _load_runtime_config,
    _call_tool,
)

CHUNK_SIZE = 90  # Notion allows max 100 blocks per patch-block-children call


def ok(action: str, data=None, message: str = "") -> dict:
    return {"status": "ok", "action": action, "data": data or {}, "message": message}


def err(action: str, message: str, data=None) -> dict:
    return {"status": "error", "action": action, "message": message, "data": data}


# ---------------------------------------------------------------------------
# Markdown → Notion blocks
# ---------------------------------------------------------------------------

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

        # Ordered list
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


# ---------------------------------------------------------------------------
# Notion MCP helpers
# ---------------------------------------------------------------------------

def _notion_call(tool_name: str, arguments: dict) -> dict:
    """Call a Notion MCP tool and return parsed result dict."""
    config = _load_runtime_config()
    result = _call_tool(config, tool_name=tool_name, arguments=arguments)
    if result.get("status") != "ok":
        raise RuntimeError(result.get("message", f"MCP call failed: {tool_name}"))
    mcp_result = result.get("data", {}).get("mcp_result", {})
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


def action_append_content(page_id: str = "", content: str = "", **_) -> dict:
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


def _import_file_list(
    file_paths: list[str],
    parent_page_id: str,
    parent_title: str,
    action_name: str,
    skip_titles: set[str] = None,
) -> dict:
    """Core import logic shared by import_folder, import_files, sync_folder."""
    if not parent_page_id:
        return err(action_name, "`parent_page_id` is required")
    if not parent_title:
        return err(action_name, "`parent_title` is required")
    if not file_paths:
        return err(action_name, "No files to import")

    if skip_titles is None:
        skip_titles = set()

    MAX_FILE_BYTES = 200 * 1024

    # Step 1: Read all files
    file_contents = []
    for raw_path in file_paths:
        p = Path(raw_path)
        entry = {"path": str(p), "name": p.name, "stem": p.stem}
        try:
            size = p.stat().st_size
            if size > MAX_FILE_BYTES:
                raw = p.read_bytes()[:MAX_FILE_BYTES]
                text = raw.decode("utf-8", errors="replace")
                entry["truncated"] = True
            else:
                text = p.read_text(encoding="utf-8", errors="replace")
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
            pages.append({"title": title, "source": fc["path"], "status": "error",
                          "error": fc.get("error", "read error")})
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
        time.sleep(0.25)  # Avoid Notion API rate limiting

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


def action_import_folder(folder: str = "", parent_page_id: str = "", parent_title: str = "",
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


def action_import_files(paths: list = None, parent_page_id: str = "", parent_title: str = "", **_) -> dict:
    if not paths:
        return err("import_files", "`paths` list is required and must not be empty")
    return _import_file_list(paths, parent_page_id, parent_title, "import_files")


def action_sync_folder(folder: str = "", parent_page_id: str = "", parent_title: str = "",
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

    # Find existing parent page to deduplicate
    existing_titles: set[str] = set()
    try:
        result = _notion_call("API-get-block-children", {"block_id": parent_page_id, "page_size": 100})
        for child in result.get("results", []):
            if child.get("type") == "child_page":
                child_title = child.get("child_page", {}).get("title", "")
                if child_title.lower() == parent_title.lower():
                    existing_titles = _get_child_titles(child.get("id", ""))
                    break
    except Exception:
        pass  # On any error, do a full import

    return _import_file_list(paths, parent_page_id, parent_title, "sync_folder",
                              skip_titles=existing_titles)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

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
