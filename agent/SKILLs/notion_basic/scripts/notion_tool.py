import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, parse, request

SCRIPT_DIR = Path(__file__).resolve().parent
AGENT_ROOT = SCRIPT_DIR.parents[2]
PROJECT_ROOT = AGENT_ROOT.parent

for candidate in (str(PROJECT_ROOT), str(AGENT_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

try:
    from agent.secret_store import SECRET_CONFIG_PATH, load_secret_config
except ModuleNotFoundError:
    from secret_store import SECRET_CONFIG_PATH, load_secret_config


NOTION_API_BASE = "https://api.notion.com/v1"
DEFAULT_NOTION_VERSION = "2026-03-11"
DEFAULT_REAL_ALL_PAGE_SIZE = 100
DEFAULT_REAL_ALL_MAX_DEPTH = 5
TEMP_DIR = SCRIPT_DIR / "temporary_data"
ARCHITECTURE_CACHE_FILE = TEMP_DIR / "notion_architecture.json"
UUID_PATTERN = re.compile(
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|[0-9a-fA-F]{32})"
)
MARKDOWN_CHILD_PATTERN = re.compile(r"<(page|database)\s+url=\"([^\"]+)\"", re.IGNORECASE)


def ok(action: str, path: str, data=None, message: str = ""):
    return {
        "status": "ok",
        "action": action,
        "path": path,
        "message": message,
        "data": data or {},
    }


def error_result(action: str, path: str, message: str, data=None):
    return {
        "status": "error",
        "action": action,
        "path": path,
        "message": message,
        "data": data,
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _empty_architecture_cache() -> dict:
    return {
        "updated_at": "",
        "sync_status": "fresh",
        "stale_marked_at": "",
        "stale_reason": "",
        "last_mutation": {},
        "snapshots": {},
    }


def _normalize_architecture_cache(data) -> dict:
    normalized = _empty_architecture_cache()
    if not isinstance(data, dict):
        return normalized

    normalized["updated_at"] = str(data.get("updated_at", "")).strip()

    sync_status = str(data.get("sync_status", "")).strip().lower()
    normalized["sync_status"] = "stale" if sync_status == "stale" else "fresh"

    if normalized["sync_status"] == "stale":
        normalized["stale_marked_at"] = str(data.get("stale_marked_at", "")).strip()
        normalized["stale_reason"] = str(data.get("stale_reason", "")).strip()

    last_mutation = data.get("last_mutation", {})
    if isinstance(last_mutation, dict):
        normalized["last_mutation"] = last_mutation

    snapshots = data.get("snapshots", {})
    if isinstance(snapshots, dict):
        normalized["snapshots"] = snapshots

    return normalized


def _architecture_cache_status_payload(cache: dict) -> dict:
    normalized = _normalize_architecture_cache(cache)
    return {
        "cache_path": str(ARCHITECTURE_CACHE_FILE),
        "updated_at": normalized.get("updated_at", ""),
        "sync_status": normalized.get("sync_status", "fresh"),
        "is_stale": normalized.get("sync_status") == "stale",
        "stale_marked_at": normalized.get("stale_marked_at", ""),
        "stale_reason": normalized.get("stale_reason", ""),
        "last_mutation": normalized.get("last_mutation", {}),
    }


def _ensure_architecture_storage():
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    if not ARCHITECTURE_CACHE_FILE.exists():
        ARCHITECTURE_CACHE_FILE.write_text(
            json.dumps(_empty_architecture_cache(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _load_architecture_cache() -> dict:
    _ensure_architecture_storage()
    raw = ARCHITECTURE_CACHE_FILE.read_text(encoding="utf-8").strip()
    if not raw:
        return _empty_architecture_cache()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _empty_architecture_cache()

    return _normalize_architecture_cache(data)


def _save_architecture_cache(data: dict):
    _ensure_architecture_storage()
    ARCHITECTURE_CACHE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _save_architecture_snapshot(snapshot: dict) -> str:
    cache = _load_architecture_cache()
    root = snapshot.get("root") or {}
    root_key = f"{root.get('type', 'unknown')}:{root.get('id', 'unknown')}"
    cache["updated_at"] = _utc_now_iso()
    cache["sync_status"] = "fresh"
    cache["stale_marked_at"] = ""
    cache["stale_reason"] = ""
    cache["snapshots"][root_key] = snapshot
    _save_architecture_cache(cache)
    return str(ARCHITECTURE_CACHE_FILE)


def _mark_architecture_stale(
    *,
    action: str,
    path: str,
    reason: str = "",
    update_last_mutation: bool = True,
) -> dict:
    cache = _load_architecture_cache()
    marked_at = _utc_now_iso()
    stale_reason = str(reason or "").strip() or f"Successful Notion mutation via {action}"
    cache["sync_status"] = "stale"
    cache["stale_marked_at"] = marked_at
    cache["stale_reason"] = stale_reason
    if update_last_mutation:
        cache["last_mutation"] = {
            "action": str(action or "").strip(),
            "path": str(path or "").strip(),
            "marked_at": marked_at,
            "reason": stale_reason,
        }
    _save_architecture_cache(cache)
    return _architecture_cache_status_payload(cache)


def mark_architecture_cache_stale_on_agent_startup() -> dict:
    return _mark_architecture_stale(
        action="agent_startup",
        path=str(ARCHITECTURE_CACHE_FILE),
        reason=(
            "Agent restarted; refresh Notion architecture before relying on cached structure."
        ),
        update_last_mutation=False,
    )


def _mark_result_architecture_stale(result: dict, *, reason: str = "") -> dict:
    if not isinstance(result, dict) or result.get("status") != "ok":
        return result

    cache_status = _mark_architecture_stale(
        action=str(result.get("action", "")).strip(),
        path=str(result.get("path", "")).strip(),
        reason=reason,
    )

    existing_data = result.get("data")
    if not isinstance(existing_data, dict):
        existing_data = {"value": existing_data}
        result["data"] = existing_data

    existing_data["architecture_cache"] = cache_status
    message = str(result.get("message", "")).strip() or "Success"
    result["message"] = (
        f"{message} Architecture cache marked stale; run sync_architecture before relying on cached structure."
    )
    return result


def _normalize_object_type(value: str) -> str:
    normalized = str(value or "").strip().lower()
    aliases = {
        "page": "page",
        "pages": "page",
        "database": "database",
        "databases": "database",
        "data_source": "data_source",
        "data-source": "data_source",
        "data_sources": "data_source",
        "data-sources": "data_source",
        "row": "row",
        "rows": "row",
    }
    return aliases.get(normalized, normalized)


def _normalize_uuid(raw_value: str) -> str:
    cleaned = re.sub(r"[^0-9a-fA-F]", "", str(raw_value or ""))
    if len(cleaned) != 32:
        raise ValueError(f"Invalid Notion page identifier: {raw_value}")
    return (
        f"{cleaned[0:8]}-{cleaned[8:12]}-{cleaned[12:16]}-"
        f"{cleaned[16:20]}-{cleaned[20:32]}"
    ).lower()


def _extract_notion_id(raw_value: str) -> str:
    text = str(raw_value or "").strip()
    if not text:
        return ""

    matches = UUID_PATTERN.findall(text)
    if not matches:
        raise ValueError(f"Could not find a Notion page ID in: {raw_value}")
    return _normalize_uuid(matches[-1])


def _load_runtime_config() -> dict:
    all_secrets = load_secret_config()
    stored = all_secrets.get("notion", {}) if isinstance(all_secrets.get("notion"), dict) else {}
    api_key = str(os.getenv("OPENCLAW_NOTION_API_KEY") or stored.get("api_key") or "").strip()
    notion_version = str(
        os.getenv("OPENCLAW_NOTION_VERSION") or stored.get("notion_version") or DEFAULT_NOTION_VERSION
    ).strip() or DEFAULT_NOTION_VERSION
    default_parent_raw = (
        os.getenv("OPENCLAW_NOTION_PARENT_PAGE_ID")
        or os.getenv("OPENCLAW_NOTION_PARENT_PAGE_URL")
        or stored.get("default_parent_page_id")
        or stored.get("default_parent_page_url")
        or ""
    )
    default_parent_page_id = _extract_notion_id(default_parent_raw) if str(default_parent_raw).strip() else ""

    return {
        "api_key": api_key,
        "notion_version": notion_version,
        "default_parent_page_id": default_parent_page_id,
        "default_parent_page_url": str(stored.get("default_parent_page_url", "")).strip(),
        "config_path": str(SECRET_CONFIG_PATH),
    }


def _request_json(
    runtime_config: dict,
    *,
    method: str,
    path: str,
    body: dict | None = None,
    query: dict | None = None,
):
    api_key = runtime_config.get("api_key", "").strip()
    if not api_key:
        raise ValueError(
            f"Notion API key is not configured. Set OPENCLAW_NOTION_API_KEY or create {SECRET_CONFIG_PATH}."
        )

    url = f"{NOTION_API_BASE}{path}"
    if query:
        query_string = parse.urlencode({k: v for k, v in query.items() if v not in (None, "")})
        if query_string:
            url = f"{url}?{query_string}"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": runtime_config.get("notion_version", DEFAULT_NOTION_VERSION),
    }
    payload = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")

    req = request.Request(url=url, data=payload, headers=headers, method=method.upper())
    try:
        with request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raw_detail = exc.read().decode("utf-8", errors="replace")
        detail = {"raw": raw_detail}
        try:
            detail = json.loads(raw_detail)
        except json.JSONDecodeError:
            pass
        message = detail.get("message") if isinstance(detail, dict) else raw_detail
        code = detail.get("code") if isinstance(detail, dict) else ""
        raise RuntimeError(
            f"Notion HTTP {exc.code}: {code or 'request_failed'}: {message or raw_detail}"
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(f"Notion unavailable: {exc.reason}") from exc


def _resolve_page_id(
    *,
    page_id: str = "",
    page_url: str = "",
    default_page_id: str = "",
    require_explicit: bool = False,
    label: str = "page",
) -> str:
    for raw_value in (page_id, page_url):
        if str(raw_value).strip():
            return _extract_notion_id(raw_value)

    if not require_explicit and str(default_page_id).strip():
        return _extract_notion_id(default_page_id)

    raise ValueError(f"Missing {label}_id or {label}_url")


def _find_title_property_name(page_obj: dict) -> str:
    properties = page_obj.get("properties") or {}
    for property_name, property_value in properties.items():
        if isinstance(property_value, dict) and property_value.get("type") == "title":
            return property_name
    return "title"


def _plain_text_from_rich_text(items) -> str:
    text_parts = []
    for item in items or []:
        if isinstance(item, dict):
            text_parts.append(str(item.get("plain_text") or item.get("text", {}).get("content") or ""))
    return "".join(text_parts).strip()


def _extract_page_title(page_obj: dict) -> str:
    properties = page_obj.get("properties") or {}
    for property_value in properties.values():
        if isinstance(property_value, dict) and property_value.get("type") == "title":
            return _plain_text_from_rich_text(property_value.get("title", []))
    return ""


def _page_summary(page_obj: dict) -> dict:
    parent = page_obj.get("parent") or {}
    return {
        "object": page_obj.get("object", ""),
        "page_id": page_obj.get("id", ""),
        "url": page_obj.get("url", ""),
        "title": _extract_page_title(page_obj),
        "parent": parent,
        "parent_type": parent.get("type", "") if isinstance(parent, dict) else "",
        "parent_page_id": parent.get("page_id", "") if isinstance(parent, dict) else "",
        "parent_database_id": parent.get("database_id", "") if isinstance(parent, dict) else "",
        "parent_data_source_id": parent.get("data_source_id", "") if isinstance(parent, dict) else "",
        "properties": page_obj.get("properties", {}) if isinstance(page_obj.get("properties"), dict) else {},
        "in_trash": bool(page_obj.get("in_trash", False)),
        "is_archived": bool(page_obj.get("is_archived", False)),
        "last_edited_time": page_obj.get("last_edited_time", ""),
    }


def _markdown_summary(markdown_obj: dict) -> dict:
    return {
        "markdown": markdown_obj.get("markdown", ""),
        "truncated": bool(markdown_obj.get("truncated", False)),
        "unknown_block_ids": markdown_obj.get("unknown_block_ids", []),
    }


def _normalize_mapping(value, field_name: str) -> dict:
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return dict(value)
    raise ValueError(f"{field_name} must be an object")


def _to_rich_text_array(value, field_name: str) -> list:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    if isinstance(value, str):
        return [
            {
                "type": "text",
                "text": {
                    "content": value,
                },
            }
        ]
    raise ValueError(f"{field_name} must be a string, object, or array")


def _property_type_map(properties: dict) -> dict:
    type_map = {}
    for property_name, property_value in (properties or {}).items():
        if isinstance(property_value, dict):
            type_map[property_name] = property_value.get("type", "")
        else:
            type_map[property_name] = type(property_value).__name__
    return type_map


def _database_summary(database_obj: dict) -> dict:
    parent = database_obj.get("parent") or {}
    data_sources = []
    for data_source in database_obj.get("data_sources") or []:
        if isinstance(data_source, dict):
            data_sources.append(
                {
                    "id": data_source.get("id", ""),
                    "name": data_source.get("name", ""),
                    "url": data_source.get("url", ""),
                }
            )
    return {
        "object": database_obj.get("object", ""),
        "database_id": database_obj.get("id", ""),
        "url": database_obj.get("url", ""),
        "title": _plain_text_from_rich_text(database_obj.get("title", [])),
        "description": _plain_text_from_rich_text(database_obj.get("description", [])),
        "parent": parent,
        "parent_type": parent.get("type", "") if isinstance(parent, dict) else "",
        "parent_page_id": parent.get("page_id", "") if isinstance(parent, dict) else "",
        "is_inline": bool(database_obj.get("is_inline", False)),
        "in_trash": bool(database_obj.get("in_trash", False)),
        "is_archived": bool(database_obj.get("is_archived", False)),
        "last_edited_time": database_obj.get("last_edited_time", ""),
        "data_sources": data_sources,
    }


def _data_source_summary(data_source_obj: dict) -> dict:
    parent = data_source_obj.get("parent") or {}
    properties = data_source_obj.get("properties") or {}
    return {
        "object": data_source_obj.get("object", ""),
        "data_source_id": data_source_obj.get("id", ""),
        "url": data_source_obj.get("url", ""),
        "title": _plain_text_from_rich_text(data_source_obj.get("title", [])),
        "description": _plain_text_from_rich_text(data_source_obj.get("description", [])),
        "parent": parent,
        "parent_type": parent.get("type", "") if isinstance(parent, dict) else "",
        "parent_database_id": parent.get("database_id", "") if isinstance(parent, dict) else "",
        "properties": properties,
        "property_names": list(properties.keys()),
        "property_types": _property_type_map(properties),
        "in_trash": bool(data_source_obj.get("in_trash", False)),
        "is_archived": bool(data_source_obj.get("is_archived", False)),
        "last_edited_time": data_source_obj.get("last_edited_time", ""),
    }


def _query_item_summary(item: dict) -> dict:
    object_type = item.get("object", "")
    if object_type == "page":
        return _page_summary(item)
    if object_type == "data_source":
        return _data_source_summary(item)
    return {
        "object": object_type,
        "id": item.get("id", ""),
        "url": item.get("url", ""),
    }


def _query_result_summary(query_obj: dict) -> dict:
    results = query_obj.get("results") or []
    return {
        "object": query_obj.get("object", ""),
        "type": query_obj.get("type", ""),
        "results": results,
        "items": [_query_item_summary(item) for item in results if isinstance(item, dict)],
        "next_cursor": query_obj.get("next_cursor"),
        "has_more": bool(query_obj.get("has_more", False)),
    }


def _extract_markdown_children(markdown: str) -> dict:
    page_refs = {}
    database_refs = {}
    for object_type, raw_url in MARKDOWN_CHILD_PATTERN.findall(str(markdown or "")):
        target_id = _extract_notion_id(raw_url)
        ref = {
            "id": target_id,
            "url": raw_url,
        }
        if str(object_type).lower() == "page":
            page_refs[target_id] = ref
        else:
            database_refs[target_id] = ref
    return {
        "pages": list(page_refs.values()),
        "databases": list(database_refs.values()),
    }


def _build_title_property(title: str) -> dict:
    return {
        "title": [
            {
                "type": "text",
                "text": {
                    "content": title,
                },
            }
        ]
    }


def _extract_h1_title(markdown: str) -> str:
    for line in str(markdown or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


def _pick_single_data_source(database_obj: dict) -> str:
    candidates = [
        data_source
        for data_source in (database_obj.get("data_sources") or [])
        if isinstance(data_source, dict) and str(data_source.get("id", "")).strip()
    ]
    if len(candidates) == 1:
        return candidates[0]["id"]
    if not candidates:
        raise ValueError("Database has no data sources")

    names = []
    for data_source in candidates[:5]:
        names.append(str(data_source.get("name") or data_source.get("id")))
    raise ValueError(
        "Database has multiple data sources; specify data_source_id or data_source_url explicitly. "
        f"Available data sources: {', '.join(names)}"
    )


def _resolve_database_id(
    *,
    database_id: str = "",
    database_url: str = "",
    require_explicit: bool = True,
) -> str:
    return _resolve_page_id(
        page_id=database_id,
        page_url=database_url,
        require_explicit=require_explicit,
        label="database",
    )


def _resolve_data_source_id(
    runtime_config: dict,
    *,
    data_source_id: str = "",
    data_source_url: str = "",
    database_id: str = "",
    database_url: str = "",
    require_explicit: bool = True,
) -> str:
    for raw_value in (data_source_id, data_source_url):
        if str(raw_value).strip():
            return _extract_notion_id(raw_value)

    database_target_id = ""
    for raw_value in (database_id, database_url):
        if str(raw_value).strip():
            database_target_id = _extract_notion_id(raw_value)
            break

    if database_target_id:
        database_obj = _request_json(runtime_config, method="GET", path=f"/databases/{database_target_id}")
        return _pick_single_data_source(database_obj)

    if require_explicit:
        raise ValueError("Missing data_source_id or data_source_url")
    return ""


def _merge_row_title(properties: dict, title_property_name: str, title: str) -> dict:
    merged = dict(properties or {})
    cleaned_title = str(title or "").strip()
    if cleaned_title:
        merged[title_property_name] = _build_title_property(cleaned_title)
    return merged


def _new_architecture_snapshot(root_type: str, root_id: str, options: dict | None = None) -> dict:
    return {
        "generated_at": _utc_now_iso(),
        "root": {
            "type": root_type,
            "id": root_id,
        },
        "options": options or {},
        "pages": {},
        "databases": {},
        "data_sources": {},
        "rows": {},
        "counts": {},
    }


def _query_all_data_source(runtime_config: dict, *, target_data_source_id: str, query_body: dict | None = None) -> dict:
    base_query = dict(query_body or {})
    page_size = int(base_query.pop("page_size", DEFAULT_REAL_ALL_PAGE_SIZE) or DEFAULT_REAL_ALL_PAGE_SIZE)
    start_cursor = str(base_query.pop("start_cursor", "") or "").strip()
    all_results = []
    next_cursor = start_cursor
    page_count = 0

    while True:
        body = dict(base_query)
        body["page_size"] = page_size
        if next_cursor:
            body["start_cursor"] = next_cursor

        query_obj = _request_json(
            runtime_config,
            method="POST",
            path=f"/data_sources/{target_data_source_id}/query",
            body=body,
        )
        page_count += 1
        all_results.extend(query_obj.get("results") or [])

        if not query_obj.get("has_more") or not query_obj.get("next_cursor"):
            return {
                "object": query_obj.get("object", ""),
                "type": query_obj.get("type", ""),
                "results": all_results,
                "next_cursor": query_obj.get("next_cursor"),
                "has_more": bool(query_obj.get("has_more", False)),
                "page_count": page_count,
            }

        next_cursor = str(query_obj.get("next_cursor") or "")


def _collect_data_source_tree(
    runtime_config: dict,
    snapshot: dict,
    *,
    target_data_source_id: str,
    query_body: dict | None = None,
):
    if target_data_source_id in snapshot["data_sources"]:
        return

    data_source_obj = _request_json(runtime_config, method="GET", path=f"/data_sources/{target_data_source_id}")
    query_obj = _query_all_data_source(
        runtime_config,
        target_data_source_id=target_data_source_id,
        query_body=query_body,
    )

    row_ids = []
    for item in query_obj.get("results") or []:
        if isinstance(item, dict) and item.get("object") == "page":
            page_id = str(item.get("id", "")).strip()
            if not page_id:
                continue
            row_ids.append(page_id)
            snapshot["rows"][page_id] = _page_summary(item)

    data = _data_source_summary(data_source_obj)
    data["row_page_ids"] = row_ids
    data["row_count"] = len(row_ids)
    data["query_page_count"] = int(query_obj.get("page_count", 0))
    snapshot["data_sources"][target_data_source_id] = data


def _collect_database_tree(
    runtime_config: dict,
    snapshot: dict,
    *,
    target_database_id: str,
    query_body: dict | None = None,
):
    if target_database_id in snapshot["databases"]:
        return

    database_obj = _request_json(runtime_config, method="GET", path=f"/databases/{target_database_id}")
    data = _database_summary(database_obj)
    snapshot["databases"][target_database_id] = data

    for data_source in data.get("data_sources", []):
        target_data_source_id = str(data_source.get("id", "")).strip()
        if not target_data_source_id:
            continue
        _collect_data_source_tree(
            runtime_config,
            snapshot,
            target_data_source_id=target_data_source_id,
            query_body=query_body,
        )


def _collect_page_tree(
    runtime_config: dict,
    snapshot: dict,
    *,
    target_page_id: str,
    include_markdown: bool,
    current_depth: int,
    max_depth: int,
    query_body: dict | None = None,
):
    if target_page_id in snapshot["pages"]:
        return

    page_obj = _request_json(runtime_config, method="GET", path=f"/pages/{target_page_id}")
    markdown_obj = _request_json(runtime_config, method="GET", path=f"/pages/{target_page_id}/markdown")
    data = _page_summary(page_obj)
    data.update(_markdown_summary(markdown_obj))

    children = _extract_markdown_children(markdown_obj.get("markdown", ""))
    data["child_pages"] = children["pages"]
    data["child_databases"] = children["databases"]
    data["child_page_ids"] = [item["id"] for item in children["pages"]]
    data["child_database_ids"] = [item["id"] for item in children["databases"]]
    data["depth"] = current_depth
    if not include_markdown:
        data.pop("markdown", None)
    snapshot["pages"][target_page_id] = data

    if current_depth >= max_depth:
        return

    for page_ref in children["pages"]:
        _collect_page_tree(
            runtime_config,
            snapshot,
            target_page_id=page_ref["id"],
            include_markdown=include_markdown,
            current_depth=current_depth + 1,
            max_depth=max_depth,
            query_body=query_body,
        )

    for database_ref in children["databases"]:
        _collect_database_tree(
            runtime_config,
            snapshot,
            target_database_id=database_ref["id"],
            query_body=query_body,
        )


def _finalize_architecture_snapshot(snapshot: dict) -> dict:
    snapshot["counts"] = {
        "page_count": len(snapshot.get("pages", {})),
        "database_count": len(snapshot.get("databases", {})),
        "data_source_count": len(snapshot.get("data_sources", {})),
        "row_count": len(snapshot.get("rows", {})),
    }
    return snapshot


def _sync_architecture(
    runtime_config: dict,
    *,
    action_name: str,
    root_page_id: str = "",
    root_database_id: str = "",
    root_data_source_id: str = "",
    include_markdown: bool = False,
    max_depth: int = DEFAULT_REAL_ALL_MAX_DEPTH,
    query_body: dict | None = None,
) -> dict:
    root_type = ""
    root_id = ""

    if str(root_data_source_id).strip():
        root_type = "data_source"
        root_id = root_data_source_id
    elif str(root_database_id).strip():
        root_type = "database"
        root_id = root_database_id
    else:
        root_type = "page"
        root_id = root_page_id

    if not root_id:
        raise ValueError("sync_architecture requires a page, database, or data source target")

    snapshot = _new_architecture_snapshot(
        root_type,
        root_id,
        options={
            "include_markdown": bool(include_markdown),
            "max_depth": int(max_depth),
            "query": dict(query_body or {}),
        },
    )

    if root_type == "page":
        _collect_page_tree(
            runtime_config,
            snapshot,
            target_page_id=root_id,
            include_markdown=bool(include_markdown),
            current_depth=0,
            max_depth=max(0, int(max_depth)),
            query_body=query_body,
        )
    elif root_type == "database":
        _collect_database_tree(
            runtime_config,
            snapshot,
            target_database_id=root_id,
            query_body=query_body,
        )
    else:
        _collect_data_source_tree(
            runtime_config,
            snapshot,
            target_data_source_id=root_id,
            query_body=query_body,
        )

    snapshot = _finalize_architecture_snapshot(snapshot)
    cache_path = _save_architecture_snapshot(snapshot)
    return ok(
        action=action_name,
        path=root_id,
        message="Notion architecture synced successfully",
        data={
            "cache_path": cache_path,
            "snapshot": snapshot,
        },
    )


def _read_architecture_cache(
    *,
    lookup_id: str = "",
    lookup_url: str = "",
    lookup_title: str = "",
    object_type: str = "",
    include_snapshot: bool = False,
) -> dict:
    cache = _load_architecture_cache()
    cache_status = _architecture_cache_status_payload(cache)
    had_lookup = bool(
        str(lookup_id or "").strip()
        or str(lookup_url or "").strip()
        or str(lookup_title or "").strip()
        or str(object_type or "").strip()
    )
    normalized_lookup_id = ""
    if str(lookup_id or lookup_url).strip():
        normalized_lookup_id = _extract_notion_id(lookup_url or lookup_id)

    normalized_title = str(lookup_title or "").strip().lower()
    normalized_object_type = _normalize_object_type(object_type)
    snapshot_summaries = []
    matches = []

    bucket_types = (
        ("pages", "page"),
        ("databases", "database"),
        ("data_sources", "data_source"),
        ("rows", "row"),
    )

    for snapshot_key, snapshot in (cache.get("snapshots") or {}).items():
        if not isinstance(snapshot, dict):
            continue

        root = snapshot.get("root") or {}
        counts = snapshot.get("counts") or {}
        snapshot_summaries.append(
            {
                "snapshot_key": snapshot_key,
                "generated_at": snapshot.get("generated_at", ""),
                "root": root,
                "counts": counts,
            }
        )

        for bucket_name, bucket_type in bucket_types:
            if normalized_object_type and normalized_object_type != bucket_type:
                continue

            for item_id, item in (snapshot.get(bucket_name) or {}).items():
                if not isinstance(item, dict):
                    continue

                if normalized_lookup_id and str(item_id) != normalized_lookup_id:
                    continue

                title_value = str(item.get("title") or "").strip()
                if normalized_title and normalized_title not in title_value.lower():
                    continue

                matches.append(
                    {
                        "snapshot_key": snapshot_key,
                        "bucket": bucket_name,
                        "object_type": bucket_type,
                        "id": item_id,
                        "title": title_value,
                        "url": item.get("url", ""),
                        "parent_type": item.get("parent_type", ""),
                        "parent_page_id": item.get("parent_page_id", ""),
                        "parent_database_id": item.get("parent_database_id", ""),
                        "parent_data_source_id": item.get("parent_data_source_id", ""),
                        "root": root,
                    }
                )

    data = {
        "cache_path": str(ARCHITECTURE_CACHE_FILE),
        "updated_at": cache.get("updated_at", ""),
        "architecture_cache": cache_status,
        "snapshot_count": len(snapshot_summaries),
        "snapshots": snapshot_summaries,
        "matches": matches,
        "match_count": len(matches),
        "lookup": {
            "lookup_id": normalized_lookup_id,
            "lookup_title": str(lookup_title or "").strip(),
            "object_type": normalized_object_type,
        },
    }
    cache_miss = bool(had_lookup and not matches)
    cache_is_stale = bool(cache_status.get("is_stale"))
    data["cache_miss"] = cache_miss
    data["should_sync_architecture"] = cache_miss or cache_is_stale
    if data["should_sync_architecture"]:
        data["recommended_next_action"] = "sync_architecture"
    if include_snapshot or (not normalized_lookup_id and not normalized_title and not normalized_object_type):
        data["cache"] = cache

    message = "Architecture cache read successfully"
    if cache_is_stale and cache_miss:
        message = (
            "Architecture cache is marked stale and no cached match was found. "
            "Run sync_architecture before concluding the item is missing."
        )
    elif cache_is_stale:
        message = (
            "Architecture cache is marked stale. "
            "Run sync_architecture before relying on cached structure."
        )
    elif cache_miss:
        message = "No cached match found. Run sync_architecture before concluding the item is missing."

    return ok(
        action="read_architecture_cache",
        path=str(ARCHITECTURE_CACHE_FILE),
        message=message,
        data=data,
    )


def _read_page(runtime_config: dict, *, target_page_id: str) -> dict:
    page_obj = _request_json(runtime_config, method="GET", path=f"/pages/{target_page_id}")
    markdown_obj = _request_json(runtime_config, method="GET", path=f"/pages/{target_page_id}/markdown")
    data = _page_summary(page_obj)
    data.update(_markdown_summary(markdown_obj))
    return ok(
        action="read_page",
        path=target_page_id,
        message="Page read successfully",
        data=data,
    )


def _create_page(
    runtime_config: dict,
    *,
    parent_page_id: str,
    title: str,
    content: str,
) -> dict:
    body = {
        "parent": {"page_id": parent_page_id},
    }

    title = str(title or "").strip()
    content = str(content or "")
    if title:
        body["properties"] = {"title": _build_title_property(title)}
    elif content.strip():
        inferred_title = _extract_h1_title(content)
        if inferred_title:
            title = inferred_title

    if not title and not content.strip():
        raise ValueError("create_page requires a title or markdown content with a top-level # heading")

    if content.strip():
        body["markdown"] = content

    page_obj = _request_json(runtime_config, method="POST", path="/pages", body=body)
    data = _page_summary(page_obj)
    data["created_with_markdown"] = bool(content.strip())
    return ok(
        action="create_page",
        path=data.get("page_id", ""),
        message="Page created successfully",
        data=data,
    )


def _update_page_title(runtime_config: dict, *, target_page_id: str, title: str) -> dict | None:
    cleaned_title = str(title or "").strip()
    if not cleaned_title:
        return None

    page_obj = _request_json(runtime_config, method="GET", path=f"/pages/{target_page_id}")
    title_property_name = _find_title_property_name(page_obj)
    updated_page = _request_json(
        runtime_config,
        method="PATCH",
        path=f"/pages/{target_page_id}",
        body={
            "properties": {
                title_property_name: _build_title_property(cleaned_title),
            }
        },
    )
    return updated_page


def _write_page(
    runtime_config: dict,
    *,
    target_page_id: str,
    content: str,
    title: str = "",
    allow_deleting_content: bool = False,
) -> dict:
    _update_page_title(runtime_config, target_page_id=target_page_id, title=title)
    replace_content = {"new_str": str(content or "")}
    if allow_deleting_content:
        replace_content["allow_deleting_content"] = True
    markdown_obj = _request_json(
        runtime_config,
        method="PATCH",
        path=f"/pages/{target_page_id}/markdown",
        body={
            "type": "replace_content",
            "replace_content": replace_content,
        },
    )
    page_obj = _request_json(runtime_config, method="GET", path=f"/pages/{target_page_id}")
    data = _page_summary(page_obj)
    data.update(_markdown_summary(markdown_obj))
    return ok(
        action="write_page",
        path=target_page_id,
        message="Page content replaced successfully",
        data=data,
    )


def _append_page(
    runtime_config: dict,
    *,
    target_page_id: str,
    content: str,
    after: str = "",
) -> dict:
    if not str(content or "").strip():
        raise ValueError("append_page requires content")

    insert_content = {"content": str(content)}
    if str(after or "").strip():
        insert_content["after"] = str(after)

    markdown_obj = _request_json(
        runtime_config,
        method="PATCH",
        path=f"/pages/{target_page_id}/markdown",
        body={
            "type": "insert_content",
            "insert_content": insert_content,
        },
    )
    page_obj = _request_json(runtime_config, method="GET", path=f"/pages/{target_page_id}")
    data = _page_summary(page_obj)
    data.update(_markdown_summary(markdown_obj))
    return ok(
        action="append_page",
        path=target_page_id,
        message="Page content appended successfully",
        data=data,
    )


def _replace_text(
    runtime_config: dict,
    *,
    target_page_id: str,
    target: str,
    new_text: str,
    replace_all_matches: bool = False,
    allow_deleting_content: bool = False,
) -> dict:
    if not str(target or ""):
        raise ValueError("replace_text requires target")

    content_update = {
        "old_str": str(target),
        "new_str": str(new_text or ""),
    }
    if replace_all_matches:
        content_update["replace_all_matches"] = True

    update_content = {"content_updates": [content_update]}
    if allow_deleting_content:
        update_content["allow_deleting_content"] = True

    markdown_obj = _request_json(
        runtime_config,
        method="PATCH",
        path=f"/pages/{target_page_id}/markdown",
        body={
            "type": "update_content",
            "update_content": update_content,
        },
    )
    page_obj = _request_json(runtime_config, method="GET", path=f"/pages/{target_page_id}")
    data = _page_summary(page_obj)
    data.update(_markdown_summary(markdown_obj))
    return ok(
        action="replace_text",
        path=target_page_id,
        message="Page text updated successfully",
        data=data,
    )


def _set_page_trash_state(runtime_config: dict, *, target_page_id: str, in_trash: bool, action: str) -> dict:
    page_obj = _request_json(
        runtime_config,
        method="PATCH",
        path=f"/pages/{target_page_id}",
        body={"in_trash": bool(in_trash)},
    )
    data = _page_summary(page_obj)
    return ok(
        action=action,
        path=target_page_id,
        message="Page moved to trash" if in_trash else "Page restored from trash",
        data=data,
    )


def _read_database(runtime_config: dict, *, target_database_id: str) -> dict:
    database_obj = _request_json(runtime_config, method="GET", path=f"/databases/{target_database_id}")
    return ok(
        action="read_database",
        path=target_database_id,
        message="Database read successfully",
        data=_database_summary(database_obj),
    )


def _read_data_source(runtime_config: dict, *, target_data_source_id: str) -> dict:
    data_source_obj = _request_json(runtime_config, method="GET", path=f"/data_sources/{target_data_source_id}")
    return ok(
        action="read_data_source",
        path=target_data_source_id,
        message="Data source read successfully",
        data=_data_source_summary(data_source_obj),
    )


def _query_data_source(runtime_config: dict, *, target_data_source_id: str, query_body: dict | None = None) -> dict:
    query_obj = _request_json(
        runtime_config,
        method="POST",
        path=f"/data_sources/{target_data_source_id}/query",
        body=query_body or {},
    )
    data = _query_result_summary(query_obj)
    data["data_source_id"] = target_data_source_id
    return ok(
        action="query_data_source",
        path=target_data_source_id,
        message="Data source queried successfully",
        data=data,
    )


def _create_database(
    runtime_config: dict,
    *,
    parent_page_id: str,
    title,
    description,
    is_inline,
    properties: dict,
    initial_data_source: dict,
    body: dict,
) -> dict:
    request_body = dict(body or {})
    if parent_page_id:
        request_body["parent"] = {"type": "page_id", "page_id": parent_page_id}
    elif not isinstance(request_body.get("parent"), dict):
        raise ValueError("create_database requires parent_page_id, parent_page_url, or body.parent")

    title_payload = _to_rich_text_array(title, "title")
    if title_payload:
        request_body["title"] = title_payload

    description_payload = _to_rich_text_array(description, "description")
    if description_payload:
        request_body["description"] = description_payload

    if is_inline is not None:
        request_body["is_inline"] = bool(is_inline)

    if initial_data_source or properties:
        merged_initial_data_source = dict(initial_data_source or {})
        if properties:
            merged_initial_data_source["properties"] = properties
        request_body["initial_data_source"] = merged_initial_data_source

    database_obj = _request_json(runtime_config, method="POST", path="/databases", body=request_body)
    data = _database_summary(database_obj)
    return ok(
        action="create_database",
        path=data.get("database_id", ""),
        message="Database created successfully",
        data=data,
    )


def _create_data_source(
    runtime_config: dict,
    *,
    parent_database_id: str,
    title,
    description,
    properties: dict,
    body: dict,
) -> dict:
    request_body = dict(body or {})
    if parent_database_id:
        request_body["parent"] = {"database_id": parent_database_id}
    elif not isinstance(request_body.get("parent"), dict):
        raise ValueError("create_data_source requires parent_database_id, parent_database_url, database_id, database_url, or body.parent")

    title_payload = _to_rich_text_array(title, "title")
    if title_payload:
        request_body["title"] = title_payload

    description_payload = _to_rich_text_array(description, "description")
    if description_payload:
        request_body["description"] = description_payload

    if properties:
        request_body["properties"] = properties

    data_source_obj = _request_json(runtime_config, method="POST", path="/data_sources", body=request_body)
    data = _data_source_summary(data_source_obj)
    return ok(
        action="create_data_source",
        path=data.get("data_source_id", ""),
        message="Data source created successfully",
        data=data,
    )


def _update_data_source(
    runtime_config: dict,
    *,
    target_data_source_id: str,
    title,
    description,
    properties: dict,
    in_trash,
    body: dict,
) -> dict:
    request_body = dict(body or {})

    title_payload = _to_rich_text_array(title, "title")
    if title_payload:
        request_body["title"] = title_payload

    description_payload = _to_rich_text_array(description, "description")
    if description_payload:
        request_body["description"] = description_payload

    if properties:
        request_body["properties"] = properties

    if in_trash is not None:
        request_body["in_trash"] = bool(in_trash)

    if not request_body:
        raise ValueError("update_data_source requires at least one change")

    data_source_obj = _request_json(
        runtime_config,
        method="PATCH",
        path=f"/data_sources/{target_data_source_id}",
        body=request_body,
    )
    data = _data_source_summary(data_source_obj)
    return ok(
        action="update_data_source",
        path=target_data_source_id,
        message="Data source updated successfully",
        data=data,
    )


def _create_row(
    runtime_config: dict,
    *,
    target_data_source_id: str,
    properties: dict,
    title: str,
    content: str,
    body: dict,
) -> dict:
    request_body = dict(body or {})
    effective_data_source_id = str(target_data_source_id or "").strip()
    if target_data_source_id:
        request_body["parent"] = {"data_source_id": target_data_source_id}
    elif not isinstance(request_body.get("parent"), dict):
        raise ValueError("create_row requires data_source_id, data_source_url, database_id, database_url, or body.parent")
    else:
        raw_parent_data_source_id = request_body.get("parent", {}).get("data_source_id", "")
        if str(raw_parent_data_source_id).strip():
            effective_data_source_id = _extract_notion_id(raw_parent_data_source_id)

    merged_properties = dict(properties or {})
    if str(title or "").strip():
        if not effective_data_source_id:
            raise ValueError("create_row title injection requires a data_source_id")
        data_source_obj = _request_json(runtime_config, method="GET", path=f"/data_sources/{effective_data_source_id}")
        title_property_name = _find_title_property_name(data_source_obj)
        merged_properties = _merge_row_title(merged_properties, title_property_name, title)

    if merged_properties:
        request_body["properties"] = merged_properties

    if str(content or "").strip():
        request_body["markdown"] = str(content)

    page_obj = _request_json(runtime_config, method="POST", path="/pages", body=request_body)
    data = _page_summary(page_obj)
    data["data_source_id"] = effective_data_source_id
    data["created_with_markdown"] = bool(str(content or "").strip())
    return ok(
        action="create_row",
        path=data.get("page_id", ""),
        message="Row created successfully",
        data=data,
    )


def _update_row(
    runtime_config: dict,
    *,
    target_row_page_id: str,
    properties: dict,
    title: str,
    body: dict,
) -> dict:
    request_body = dict(body or {})
    merged_properties = dict(properties or {})

    if str(title or "").strip():
        existing_page = _request_json(runtime_config, method="GET", path=f"/pages/{target_row_page_id}")
        title_property_name = _find_title_property_name(existing_page)
        merged_properties = _merge_row_title(merged_properties, title_property_name, title)

    if merged_properties:
        request_body["properties"] = merged_properties

    if not request_body:
        raise ValueError("update_row requires at least one change")

    page_obj = _request_json(
        runtime_config,
        method="PATCH",
        path=f"/pages/{target_row_page_id}",
        body=request_body,
    )
    data = _page_summary(page_obj)
    return ok(
        action="update_row",
        path=target_row_page_id,
        message="Row updated successfully",
        data=data,
    )


def run(
    action: str,
    page_id: str = "",
    page_url: str = "",
    parent_page_id: str = "",
    parent_page_url: str = "",
    database_id: str = "",
    database_url: str = "",
    parent_database_id: str = "",
    parent_database_url: str = "",
    data_source_id: str = "",
    data_source_url: str = "",
    row_page_id: str = "",
    row_page_url: str = "",
    title="",
    description="",
    content: str = "",
    properties=None,
    initial_data_source=None,
    query=None,
    body=None,
    filter=None,
    sorts=None,
    page_size=None,
    start_cursor: str = "",
    max_depth=None,
    include_markdown=False,
    include_snapshot=False,
    is_inline=None,
    in_trash=None,
    lookup_id: str = "",
    lookup_url: str = "",
    lookup_title: str = "",
    object_type: str = "",
    target: str = "",
    new_text: str = "",
    after: str = "",
    replace_all_matches: bool = False,
    allow_deleting_content: bool = False,
    **kwargs,
):
    runtime_config = _load_runtime_config()
    path_hint = (
        row_page_id
        or row_page_url
        or data_source_id
        or data_source_url
        or database_id
        or database_url
        or page_id
        or page_url
        or parent_database_id
        or parent_database_url
        or parent_page_id
        or parent_page_url
    )

    try:
        request_body = _normalize_mapping(body, "body")
        row_properties = _normalize_mapping(properties, "properties")
        initial_data_source_body = _normalize_mapping(initial_data_source, "initial_data_source")
        query_body = _normalize_mapping(query, "query")

        if filter not in (None, ""):
            if not isinstance(filter, dict):
                raise ValueError("filter must be an object")
            query_body["filter"] = filter

        if sorts not in (None, ""):
            if not isinstance(sorts, list):
                raise ValueError("sorts must be an array")
            query_body["sorts"] = sorts

        if page_size not in (None, ""):
            query_body["page_size"] = int(page_size)

        if str(start_cursor or "").strip():
            query_body["start_cursor"] = str(start_cursor)

        if action == "read_architecture_cache":
            effective_lookup_id = str(lookup_id or "").strip()
            effective_lookup_url = str(lookup_url or "").strip()
            effective_object_type = str(object_type or "").strip()

            if not effective_lookup_id and not effective_lookup_url:
                if str(row_page_id or row_page_url).strip():
                    effective_lookup_id = row_page_id
                    effective_lookup_url = row_page_url
                    effective_object_type = effective_object_type or "row"
                elif str(data_source_id or data_source_url).strip():
                    effective_lookup_id = data_source_id
                    effective_lookup_url = data_source_url
                    effective_object_type = effective_object_type or "data_source"
                elif str(database_id or database_url).strip():
                    effective_lookup_id = database_id
                    effective_lookup_url = database_url
                    effective_object_type = effective_object_type or "database"
                elif str(page_id or page_url).strip():
                    effective_lookup_id = page_id
                    effective_lookup_url = page_url
                    effective_object_type = effective_object_type or "page"

            return _read_architecture_cache(
                lookup_id=effective_lookup_id,
                lookup_url=effective_lookup_url,
                lookup_title=lookup_title,
                object_type=effective_object_type,
                include_snapshot=bool(include_snapshot),
            )

        if action in {"sync_architecture", "real_all", "read_all"}:
            root_page_id = ""
            root_database_id = ""
            root_data_source_id = ""

            if str(data_source_id or data_source_url).strip():
                root_data_source_id = _resolve_data_source_id(
                    runtime_config,
                    data_source_id=data_source_id,
                    data_source_url=data_source_url,
                    database_id=database_id,
                    database_url=database_url,
                    require_explicit=True,
                )
            elif str(database_id or database_url).strip():
                root_database_id = _resolve_database_id(
                    database_id=database_id,
                    database_url=database_url,
                    require_explicit=True,
                )
            else:
                root_page_id = _resolve_page_id(
                    page_id=page_id,
                    page_url=page_url,
                    default_page_id=runtime_config.get("default_parent_page_id", ""),
                    require_explicit=False,
                    label="page",
                )

            effective_query_body = query_body or request_body
            effective_max_depth = DEFAULT_REAL_ALL_MAX_DEPTH if max_depth in (None, "") else int(max_depth)
            return _sync_architecture(
                runtime_config,
                action_name="sync_architecture",
                root_page_id=root_page_id,
                root_database_id=root_database_id,
                root_data_source_id=root_data_source_id,
                include_markdown=bool(include_markdown),
                max_depth=effective_max_depth,
                query_body=effective_query_body,
            )

        if action == "read_page":
            target_page_id = _resolve_page_id(
                page_id=page_id,
                page_url=page_url,
                default_page_id=runtime_config.get("default_parent_page_id", ""),
                require_explicit=False,
                label="page",
            )
            return _read_page(runtime_config, target_page_id=target_page_id)

        if action == "create_page":
            parent_id = _resolve_page_id(
                page_id=parent_page_id,
                page_url=parent_page_url,
                default_page_id=runtime_config.get("default_parent_page_id", ""),
                require_explicit=False,
                label="parent_page",
            )
            return _mark_result_architecture_stale(
                _create_page(
                    runtime_config,
                    parent_page_id=parent_id,
                    title=title,
                    content=content,
                )
            )

        if action == "write_page":
            target_page_id = _resolve_page_id(
                page_id=page_id,
                page_url=page_url,
                require_explicit=True,
                label="page",
            )
            return _mark_result_architecture_stale(
                _write_page(
                    runtime_config,
                    target_page_id=target_page_id,
                    content=content,
                    title=title,
                    allow_deleting_content=bool(allow_deleting_content),
                )
            )

        if action == "append_page":
            target_page_id = _resolve_page_id(
                page_id=page_id,
                page_url=page_url,
                require_explicit=True,
                label="page",
            )
            return _mark_result_architecture_stale(
                _append_page(
                    runtime_config,
                    target_page_id=target_page_id,
                    content=content,
                    after=after,
                )
            )

        if action == "replace_text":
            target_page_id = _resolve_page_id(
                page_id=page_id,
                page_url=page_url,
                require_explicit=True,
                label="page",
            )
            return _mark_result_architecture_stale(
                _replace_text(
                    runtime_config,
                    target_page_id=target_page_id,
                    target=target,
                    new_text=new_text,
                    replace_all_matches=bool(replace_all_matches),
                    allow_deleting_content=bool(allow_deleting_content),
                )
            )

        if action == "delete_page":
            target_page_id = _resolve_page_id(
                page_id=page_id,
                page_url=page_url,
                require_explicit=True,
                label="page",
            )
            return _mark_result_architecture_stale(
                _set_page_trash_state(
                    runtime_config,
                    target_page_id=target_page_id,
                    in_trash=True,
                    action="delete_page",
                )
            )

        if action == "restore_page":
            target_page_id = _resolve_page_id(
                page_id=page_id,
                page_url=page_url,
                require_explicit=True,
                label="page",
            )
            return _mark_result_architecture_stale(
                _set_page_trash_state(
                    runtime_config,
                    target_page_id=target_page_id,
                    in_trash=False,
                    action="restore_page",
                )
            )

        if action == "read_database":
            target_database_id = _resolve_database_id(
                database_id=database_id,
                database_url=database_url,
                require_explicit=True,
            )
            return _read_database(runtime_config, target_database_id=target_database_id)

        if action == "read_data_source":
            target_data_source_id = _resolve_data_source_id(
                runtime_config,
                data_source_id=data_source_id,
                data_source_url=data_source_url,
                database_id=database_id,
                database_url=database_url,
                require_explicit=True,
            )
            return _read_data_source(runtime_config, target_data_source_id=target_data_source_id)

        if action == "query_database":
            effective_query_body = query_body or request_body
            target_data_source_id = _resolve_data_source_id(
                runtime_config,
                data_source_id=data_source_id,
                data_source_url=data_source_url,
                database_id=database_id,
                database_url=database_url,
                require_explicit=True,
            )
            result = _query_data_source(
                runtime_config,
                target_data_source_id=target_data_source_id,
                query_body=effective_query_body,
            )
            result["action"] = "query_database"
            if str(database_id or database_url).strip():
                result["path"] = _resolve_database_id(
                    database_id=database_id,
                    database_url=database_url,
                    require_explicit=True,
                )
                result["data"]["database_id"] = result["path"]
            return result

        if action == "query_data_source":
            effective_query_body = query_body or request_body
            target_data_source_id = _resolve_data_source_id(
                runtime_config,
                data_source_id=data_source_id,
                data_source_url=data_source_url,
                database_id=database_id,
                database_url=database_url,
                require_explicit=True,
            )
            return _query_data_source(
                runtime_config,
                target_data_source_id=target_data_source_id,
                query_body=effective_query_body,
            )

        if action == "create_database":
            parent_id = ""
            if str(parent_page_id or parent_page_url).strip() or not isinstance(request_body.get("parent"), dict):
                parent_id = _resolve_page_id(
                    page_id=parent_page_id,
                    page_url=parent_page_url,
                    default_page_id=runtime_config.get("default_parent_page_id", ""),
                    require_explicit=False,
                    label="parent_page",
                )
            return _mark_result_architecture_stale(
                _create_database(
                    runtime_config,
                    parent_page_id=parent_id,
                    title=title,
                    description=description,
                    is_inline=is_inline,
                    properties=row_properties,
                    initial_data_source=initial_data_source_body,
                    body=request_body,
                )
            )

        if action == "create_data_source":
            parent_db_id = ""
            if (
                str(parent_database_id or parent_database_url).strip()
                or str(database_id or database_url).strip()
                or not isinstance(request_body.get("parent"), dict)
            ):
                parent_db_id = _resolve_database_id(
                    database_id=parent_database_id or database_id,
                    database_url=parent_database_url or database_url,
                    require_explicit=False,
                )
            return _mark_result_architecture_stale(
                _create_data_source(
                    runtime_config,
                    parent_database_id=parent_db_id,
                    title=title,
                    description=description,
                    properties=row_properties,
                    body=request_body,
                )
            )

        if action == "update_data_source":
            target_data_source_id = _resolve_data_source_id(
                runtime_config,
                data_source_id=data_source_id,
                data_source_url=data_source_url,
                database_id=database_id,
                database_url=database_url,
                require_explicit=True,
            )
            return _mark_result_architecture_stale(
                _update_data_source(
                    runtime_config,
                    target_data_source_id=target_data_source_id,
                    title=title,
                    description=description,
                    properties=row_properties,
                    in_trash=in_trash,
                    body=request_body,
                )
            )

        if action == "create_row":
            target_data_source_id = ""
            if (
                str(data_source_id or data_source_url).strip()
                or str(database_id or database_url).strip()
                or not isinstance(request_body.get("parent"), dict)
            ):
                target_data_source_id = _resolve_data_source_id(
                    runtime_config,
                    data_source_id=data_source_id,
                    data_source_url=data_source_url,
                    database_id=database_id,
                    database_url=database_url,
                    require_explicit=False,
                )
            return _mark_result_architecture_stale(
                _create_row(
                    runtime_config,
                    target_data_source_id=target_data_source_id,
                    properties=row_properties,
                    title=str(title or ""),
                    content=content,
                    body=request_body,
                )
            )

        if action == "update_row":
            target_row_page_id = _resolve_page_id(
                page_id=row_page_id or page_id,
                page_url=row_page_url or page_url,
                require_explicit=True,
                label="row_page",
            )
            return _mark_result_architecture_stale(
                _update_row(
                    runtime_config,
                    target_row_page_id=target_row_page_id,
                    properties=row_properties,
                    title=str(title or ""),
                    body=request_body,
                )
            )

        if action == "delete_row":
            target_row_page_id = _resolve_page_id(
                page_id=row_page_id or page_id,
                page_url=row_page_url or page_url,
                require_explicit=True,
                label="row_page",
            )
            return _mark_result_architecture_stale(
                _set_page_trash_state(
                    runtime_config,
                    target_page_id=target_row_page_id,
                    in_trash=True,
                    action="delete_row",
                )
            )

        if action == "restore_row":
            target_row_page_id = _resolve_page_id(
                page_id=row_page_id or page_id,
                page_url=row_page_url or page_url,
                require_explicit=True,
                label="row_page",
            )
            return _mark_result_architecture_stale(
                _set_page_trash_state(
                    runtime_config,
                    target_page_id=target_row_page_id,
                    in_trash=False,
                    action="restore_row",
                )
            )

        return error_result(action, path_hint, f"Unsupported action: {action}")
    except Exception as exc:
        return error_result(action, path_hint, str(exc))
