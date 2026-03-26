import json
import mimetypes
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
DEFAULT_REAL_ALL_MAX_DEPTH = 3
MAX_NOTION_SINGLE_PART_UPLOAD_BYTES = 20 * 1024 * 1024
NOTION_DOWNLOAD_DIR = AGENT_ROOT / "data" / "notion_downloads"
UUID_PATTERN = re.compile(
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|[0-9a-fA-F]{32})"
)
MARKDOWN_CHILD_PATTERN = re.compile(r"<(page|database)\s+url=\"([^\"]+)\"", re.IGNORECASE)
KNOWN_IMAGE_MIME_TYPES = {
    ".avif": "image/avif",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
}
FILENAME_SAFE_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")
NOTION_PROPERTY_VALUE_TYPES = {
    "title",
    "rich_text",
    "number",
    "select",
    "multi_select",
    "status",
    "date",
    "people",
    "files",
    "checkbox",
    "url",
    "email",
    "phone_number",
    "relation",
}


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


def _mark_result_architecture_stale(result: dict, *, reason: str = "") -> dict:
    return result


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

    parsed_url = parse.urlparse(text)
    path_matches = UUID_PATTERN.findall(parsed_url.path or "")
    if path_matches:
        return _normalize_uuid(path_matches[-1])

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


def _safe_local_path(path: str) -> str:
    normalized = Path(path).expanduser()
    if not normalized.is_absolute():
        normalized = Path.cwd() / normalized
    return str(normalized.resolve())


def _resolve_local_file(path: str, *, field_name: str) -> Path:
    cleaned = str(path or "").strip()
    if not cleaned:
        raise ValueError(f"{field_name} is required")

    resolved = Path(_safe_local_path(cleaned))
    if not resolved.exists():
        raise FileNotFoundError(f"{field_name} not found: {resolved}")
    if not resolved.is_file():
        raise ValueError(f"{field_name} must be a file: {resolved}")
    return resolved


def _guess_image_content_type(file_path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(str(file_path))
    if mime_type and mime_type.startswith("image/"):
        return mime_type

    fallback = KNOWN_IMAGE_MIME_TYPES.get(file_path.suffix.lower(), "")
    if fallback:
        return fallback

    raise ValueError(
        f"Unsupported image file type for Notion upload: {file_path.name}. "
        "Use a standard image extension such as .png, .jpg, .jpeg, .gif, .webp, or .svg."
    )


def _guess_extension_from_content_type(content_type: str) -> str:
    guessed = mimetypes.guess_extension(str(content_type or "").strip())
    if not guessed:
        return ""
    return ".jpg" if guessed == ".jpe" else guessed


def _sanitize_filename(filename: str, *, fallback: str) -> str:
    cleaned = FILENAME_SAFE_PATTERN.sub("_", str(filename or "").strip()).strip("._")
    return cleaned or fallback


def _default_notion_download_dir() -> Path:
    target_dir = NOTION_DOWNLOAD_DIR / datetime.now().astimezone().strftime("%Y-%m-%d")
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def _download_binary_from_url(url: str) -> tuple[bytes, object]:
    cleaned = str(url or "").strip()
    if not cleaned:
        raise ValueError("download URL is missing")

    req = request.Request(url=cleaned, method="GET")
    try:
        with request.urlopen(req, timeout=60) as response:
            return response.read(), response.info()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Download failed with HTTP {exc.code}: {detail or exc.reason}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Download failed: {exc.reason}") from exc


def _save_downloaded_bytes(
    *,
    payload: bytes,
    source_url: str,
    filename: str = "",
    save_path: str = "",
    save_dir: str = "",
    content_type: str = "",
    fallback_stem: str,
) -> Path:
    explicit_save_path = str(save_path or "").strip()
    if explicit_save_path:
        resolved = Path(_safe_local_path(explicit_save_path))
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_bytes(payload)
        return resolved

    target_dir = Path(_safe_local_path(save_dir)) if str(save_dir or "").strip() else _default_notion_download_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    parsed_url = parse.urlparse(str(source_url or "").strip())
    url_name = Path(parsed_url.path).name
    candidate_name = str(filename or "").strip() or url_name
    extension = Path(candidate_name).suffix.lower()
    if not extension:
        extension = Path(url_name).suffix.lower()
    if not extension:
        extension = _guess_extension_from_content_type(content_type)
    if not extension:
        extension = ".img"

    stem = Path(candidate_name).stem if candidate_name else ""
    safe_name = _sanitize_filename(f"{stem}{extension}", fallback=f"{fallback_stem}{extension}")
    output_path = target_dir / safe_name
    output_path.write_bytes(payload)
    return output_path


def _multipart_request_json(
    runtime_config: dict,
    *,
    method: str,
    path: str,
    form_fields: list[tuple[str, str]] | None = None,
    files: list[dict] | None = None,
):
    api_key = runtime_config.get("api_key", "").strip()
    if not api_key:
        raise ValueError(
            f"Notion API key is not configured. Set OPENCLAW_NOTION_API_KEY or create {SECRET_CONFIG_PATH}."
        )

    boundary = f"----OpenClawNotionBoundary{os.urandom(12).hex()}"
    body_chunks = []

    for field_name, field_value in form_fields or []:
        body_chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{field_name}"\r\n\r\n'.encode("utf-8"),
                str(field_value).encode("utf-8"),
                b"\r\n",
            ]
        )

    for item in files or []:
        filename = str(item.get("filename", "upload.bin"))
        content_type = str(item.get("content_type", "application/octet-stream"))
        payload = item.get("content", b"")
        if not isinstance(payload, (bytes, bytearray)):
            raise ValueError("multipart file content must be bytes")

        body_chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                (
                    f'Content-Disposition: form-data; name="{item.get("field_name", "file")}"; '
                    f'filename="{filename}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
                bytes(payload),
                b"\r\n",
            ]
        )

    body_chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    payload = b"".join(body_chunks)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": runtime_config.get("notion_version", DEFAULT_NOTION_VERSION),
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    req = request.Request(
        url=f"{NOTION_API_BASE}{path}",
        data=payload,
        headers=headers,
        method=method.upper(),
    )
    try:
        with request.urlopen(req, timeout=60) as response:
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


def _looks_like_property_payload(value, expected_type: str = "") -> bool:
    if not isinstance(value, dict):
        return False
    if expected_type and expected_type in value:
        return True
    return any(key in NOTION_PROPERTY_VALUE_TYPES for key in value.keys())


def _normalize_date_property_value(value):
    if value is None:
        return {"date": None}

    if isinstance(value, str):
        cleaned = str(value).strip()
        if not cleaned:
            return {"date": None}
        return {"date": {"start": cleaned}}

    if isinstance(value, (list, tuple)):
        items = [str(item).strip() for item in value if str(item).strip()]
        if not items:
            return {"date": None}
        if len(items) == 1:
            return {"date": {"start": items[0]}}
        if len(items) == 2:
            return {"date": {"start": items[0], "end": items[1]}}
        raise ValueError("date property arrays must contain at most two values: start and optional end")

    if not isinstance(value, dict):
        raise ValueError("date properties must be a string, object, array, or null")

    if "date" in value:
        date_payload = value.get("date")
        if date_payload is None:
            return {"date": None}
        if not isinstance(date_payload, dict):
            raise ValueError("date.date must be an object or null")
        return {"date": dict(date_payload)}

    aliases = {
        "start": "start",
        "end": "end",
        "time_zone": "time_zone",
        "timezone": "time_zone",
        "tz": "time_zone",
        "from": "start",
        "to": "end",
        "value": "start",
    }
    date_payload = {}
    for raw_key, normalized_key in aliases.items():
        raw_value = value.get(raw_key)
        if raw_value not in (None, ""):
            date_payload[normalized_key] = str(raw_value).strip()

    if not date_payload:
        raise ValueError(
            "date property objects must use `date`, `start`/`end`, `from`/`to`, or `time_zone` keys"
        )

    return {"date": date_payload}


def _normalize_property_value_by_type(value, *, property_name: str, property_type: str):
    if _looks_like_property_payload(value, property_type):
        return value

    if property_type == "title":
        if isinstance(value, str):
            return _build_title_property(value)
        raise ValueError(f"title property `{property_name}` must be a string or a raw title payload")

    if property_type == "rich_text":
        if isinstance(value, str):
            return {"rich_text": _to_rich_text_array(value, property_name)}
        raise ValueError(
            f"rich_text property `{property_name}` must be a string or a raw rich_text payload"
        )

    if property_type == "date":
        return _normalize_date_property_value(value)

    if property_type == "select":
        if isinstance(value, str):
            return {"select": {"name": value}}
        if isinstance(value, dict) and "name" in value:
            return {"select": dict(value)}
        raise ValueError(f"select property `{property_name}` must be a string or a select payload")

    if property_type == "status":
        if isinstance(value, str):
            return {"status": {"name": value}}
        if isinstance(value, dict) and "name" in value:
            return {"status": dict(value)}
        raise ValueError(f"status property `{property_name}` must be a string or a status payload")

    if property_type == "multi_select":
        if isinstance(value, str):
            cleaned = str(value).strip()
            return {"multi_select": [{"name": cleaned}]} if cleaned else {"multi_select": []}
        if isinstance(value, (list, tuple)):
            items = []
            for item in value:
                if isinstance(item, str):
                    cleaned = str(item).strip()
                    if cleaned:
                        items.append({"name": cleaned})
                elif isinstance(item, dict):
                    items.append(dict(item))
                else:
                    raise ValueError(
                        f"multi_select property `{property_name}` items must be strings or objects"
                    )
            return {"multi_select": items}
        raise ValueError(
            f"multi_select property `{property_name}` must be a string, array, or a raw multi_select payload"
        )

    if property_type == "checkbox":
        if isinstance(value, bool):
            return {"checkbox": value}
        raise ValueError(f"checkbox property `{property_name}` must be true/false or a raw checkbox payload")

    if property_type == "number":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return {"number": value}
        raise ValueError(f"number property `{property_name}` must be numeric or a raw number payload")

    if property_type in {"url", "email", "phone_number"}:
        if isinstance(value, str):
            return {property_type: value}
        raise ValueError(f"{property_type} property `{property_name}` must be a string or a raw payload")

    return value


def _normalize_properties_for_schema(properties: dict, *, schema_properties: dict) -> dict:
    if not properties:
        return {}

    normalized = {}
    schema_by_name = {}
    schema_by_id = {}
    for property_name, property_value in (schema_properties or {}).items():
        if not isinstance(property_value, dict):
            continue
        schema_by_name[str(property_name)] = property_value
        property_id = str(property_value.get("id", "")).strip()
        if property_id:
            schema_by_id[property_id] = property_value

    available_names = sorted(schema_by_name.keys())

    for raw_key, raw_value in properties.items():
        property_key = str(raw_key)
        schema_property = schema_by_name.get(property_key) or schema_by_id.get(property_key)
        if not schema_property:
            raise ValueError(
                f"Unknown property `{property_key}`. Available properties: {', '.join(available_names)}"
            )

        property_type = str(schema_property.get("type", "")).strip()
        property_name = str(schema_property.get("name", property_key)).strip() or property_key
        normalized[property_key] = _normalize_property_value_by_type(
            raw_value,
            property_name=property_name,
            property_type=property_type,
        )

    return normalized


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


def _file_upload_summary(file_upload_obj: dict) -> dict:
    return {
        "id": file_upload_obj.get("id", ""),
        "status": file_upload_obj.get("status", ""),
        "filename": file_upload_obj.get("filename", ""),
        "content_type": file_upload_obj.get("content_type", ""),
        "content_length": file_upload_obj.get("content_length"),
        "expiry_time": file_upload_obj.get("expiry_time", ""),
        "upload_url": file_upload_obj.get("upload_url", ""),
        "complete_url": file_upload_obj.get("complete_url", ""),
        "in_trash": bool(
            file_upload_obj.get("in_trash", file_upload_obj.get("archived", False))
        ),
    }


def _list_block_children(runtime_config: dict, *, parent_block_id: str) -> list[dict]:
    items = []
    next_cursor = ""

    while True:
        query = {"page_size": 100}
        if str(next_cursor).strip():
            query["start_cursor"] = next_cursor
        response = _request_json(
            runtime_config,
            method="GET",
            path=f"/blocks/{parent_block_id}/children",
            query=query,
        )
        batch = response.get("results") or []
        items.extend(item for item in batch if isinstance(item, dict))
        next_cursor = response.get("next_cursor") or ""
        if not response.get("has_more") or not next_cursor:
            break

    return items


def _block_file_download_info(block_obj: dict) -> dict | None:
    block_type = str(block_obj.get("type", "")).strip()
    if block_type != "image":
        return None

    payload = block_obj.get(block_type) or {}
    if not isinstance(payload, dict):
        return None

    file_kind = str(payload.get("type", "")).strip()
    info = {
        "block_id": block_obj.get("id", ""),
        "block_type": block_type,
        "caption": _plain_text_from_rich_text(payload.get("caption", [])),
        "file_kind": file_kind,
        "has_download_url": False,
    }

    if file_kind == "file":
        file_obj = payload.get("file") or {}
        info["download_url"] = str(file_obj.get("url", "")).strip()
        info["expiry_time"] = str(file_obj.get("expiry_time", "")).strip()
        info["has_download_url"] = bool(info["download_url"])
        return info

    if file_kind == "external":
        file_obj = payload.get("external") or {}
        info["download_url"] = str(file_obj.get("url", "")).strip()
        info["has_download_url"] = bool(info["download_url"])
        return info

    if file_kind == "file_upload":
        file_obj = payload.get("file_upload") or {}
        info["file_upload_id"] = str(file_obj.get("id", "")).strip()
        return info

    return None


def _collect_page_image_blocks(
    runtime_config: dict,
    *,
    parent_block_id: str,
    recursive: bool = True,
) -> list[dict]:
    found = []
    queue = [str(parent_block_id).strip()]
    visited = set()

    while queue:
        current_id = queue.pop(0)
        if not current_id or current_id in visited:
            continue
        visited.add(current_id)

        for child in _list_block_children(runtime_config, parent_block_id=current_id):
            image_info = _block_file_download_info(child)
            if image_info:
                found.append(image_info)

            if recursive and bool(child.get("has_children")):
                child_id = str(child.get("id", "")).strip()
                if child_id and child_id not in visited:
                    queue.append(child_id)

    return found


def _download_image(
    runtime_config: dict,
    *,
    target_page_id: str = "",
    target_block_id: str = "",
    image_index: int = 1,
    save_path: str = "",
    save_dir: str = "",
    filename: str = "",
    recursive: bool = True,
) -> dict:
    if str(target_block_id or "").strip():
        block_obj = _request_json(runtime_config, method="GET", path=f"/blocks/{target_block_id}")
        candidate_images = []
        image_info = _block_file_download_info(block_obj)
        if image_info:
            candidate_images.append(image_info)
    else:
        if not str(target_page_id or "").strip():
            raise ValueError("download_image requires page_id, page_url, block_id, or block_url")
        candidate_images = _collect_page_image_blocks(
            runtime_config,
            parent_block_id=target_page_id,
            recursive=bool(recursive),
        )

    available_images = [item for item in candidate_images if item.get("has_download_url")]
    if not available_images:
        if candidate_images and any(item.get("file_kind") == "file_upload" for item in candidate_images):
            raise RuntimeError(
                "Found image blocks, but Notion has not exposed a downloadable file URL yet. "
                "Try again later after the file upload finishes processing."
            )
        raise RuntimeError("No downloadable image block was found on the target page or block.")

    effective_index = max(1, int(image_index)) - 1
    if effective_index >= len(available_images):
        raise ValueError(
            f"image_index {image_index} is out of range; found {len(available_images)} downloadable image(s)."
        )

    selected = available_images[effective_index]
    download_url = str(selected.get("download_url", "")).strip()
    payload, response_info = _download_binary_from_url(download_url)
    content_type = str(getattr(response_info, "get_content_type", lambda: "")() or "").strip()
    saved_path = _save_downloaded_bytes(
        payload=payload,
        source_url=download_url,
        filename=filename,
        save_path=save_path,
        save_dir=save_dir,
        content_type=content_type,
        fallback_stem=f"notion_image_{selected.get('block_id', '')[:8] or 'download'}",
    )

    path_hint = str(target_block_id or target_page_id)
    data = {
        "page_id": target_page_id,
        "block_id": selected.get("block_id", ""),
        "image_index": effective_index + 1,
        "candidate_count": len(available_images),
        "local_path": str(saved_path),
        "filename": saved_path.name,
        "size_bytes": len(payload),
        "download_url": download_url,
        "file_kind": selected.get("file_kind", ""),
        "block_type": selected.get("block_type", ""),
        "caption": selected.get("caption", ""),
        "content_type": content_type,
    }
    expiry_time = str(selected.get("expiry_time", "")).strip()
    if expiry_time:
        data["expiry_time"] = expiry_time

    return ok(
        action="download_image",
        path=path_hint,
        message="Image downloaded from Notion successfully",
        data=data,
    )


def _search(
    runtime_config: dict,
    *,
    query_text: str = "",
    object_type: str = "",
    page_size: int | None = None,
    start_cursor: str = "",
    sort_timestamp: str = "",
    sort_direction: str = "",
    body: dict | None = None,
) -> dict:
    request_body = dict(body or {})
    cleaned_query = str(query_text or "").strip()
    if cleaned_query:
        request_body["query"] = cleaned_query

    cleaned_object_type = str(object_type or "").strip().lower()
    if cleaned_object_type:
        if cleaned_object_type not in {"page", "data_source"}:
            raise ValueError("search object_type must be `page` or `data_source`")
        request_body["filter"] = {"property": "object", "value": cleaned_object_type}

    if page_size not in (None, ""):
        request_body["page_size"] = int(page_size)
    if str(start_cursor or "").strip():
        request_body["start_cursor"] = str(start_cursor)

    cleaned_sort_timestamp = str(sort_timestamp or "").strip()
    cleaned_sort_direction = str(sort_direction or "").strip()
    if cleaned_sort_timestamp or cleaned_sort_direction:
        request_body["sort"] = {
            "timestamp": cleaned_sort_timestamp or "last_edited_time",
            "direction": cleaned_sort_direction or "descending",
        }

    search_obj = _request_json(runtime_config, method="POST", path="/search", body=request_body)
    data = _query_result_summary(search_obj)
    data["query_text"] = cleaned_query
    data["object_type"] = cleaned_object_type
    data["official_limit_note"] = (
        "Notion search matches shared pages and data sources by title metadata. "
        "It does not provide full-text search over page content or attachment contents."
    )
    return ok(
        action="search",
        path=cleaned_query,
        message="Notion search completed successfully",
        data=data,
    )


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
    if int(max_depth) > DEFAULT_REAL_ALL_MAX_DEPTH:
        raise ValueError(
            f"sync_architecture max_depth cannot exceed {DEFAULT_REAL_ALL_MAX_DEPTH}. "
            "If you need to go deeper, call sync_architecture again from a deeper page, database, or data source target."
        )

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
    return ok(
        action=action_name,
        path=root_id,
        message="Notion architecture synced successfully",
        data={
            "snapshot": snapshot,
            "max_depth_limit": DEFAULT_REAL_ALL_MAX_DEPTH,
            "call_again_for_deeper_traversal": True,
        },
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


def _create_notion_file_upload(runtime_config: dict, *, file_path: Path, content_type: str) -> dict:
    return _request_json(
        runtime_config,
        method="POST",
        path="/file_uploads",
        body={
            "mode": "single_part",
            "filename": file_path.name,
            "content_type": content_type,
        },
    )


def _send_notion_file_upload(runtime_config: dict, *, file_upload_id: str, file_path: Path, content_type: str) -> dict:
    file_bytes = file_path.read_bytes()
    if len(file_bytes) > MAX_NOTION_SINGLE_PART_UPLOAD_BYTES:
        raise ValueError(
            "upload_image currently supports single-part Notion uploads up to "
            f"{MAX_NOTION_SINGLE_PART_UPLOAD_BYTES} bytes; got {len(file_bytes)} bytes."
        )

    return _multipart_request_json(
        runtime_config,
        method="POST",
        path=f"/file_uploads/{file_upload_id}/send",
        files=[
            {
                "field_name": "file",
                "filename": file_path.name,
                "content_type": content_type,
                "content": file_bytes,
            }
        ],
    )


def _append_block_children(
    runtime_config: dict,
    *,
    target_block_id: str,
    children: list[dict],
    after_block_id: str = "",
) -> dict:
    request_body = {
        "children": children,
    }
    if str(after_block_id or "").strip():
        request_body["position"] = {
            "type": "after_block",
            "after_block": {
                "id": _extract_notion_id(after_block_id),
            },
        }
    return _request_json(
        runtime_config,
        method="PATCH",
        path=f"/blocks/{target_block_id}/children",
        body=request_body,
    )


def _upload_image(
    runtime_config: dict,
    *,
    target_page_id: str,
    image_path: str,
    caption="",
    after: str = "",
) -> dict:
    local_image_path = _resolve_local_file(image_path, field_name="image_path")
    content_type = _guess_image_content_type(local_image_path)
    created_upload = _create_notion_file_upload(
        runtime_config,
        file_path=local_image_path,
        content_type=content_type,
    )
    file_upload_id = str(created_upload.get("id", "")).strip()
    if not file_upload_id:
        raise RuntimeError("Notion file upload creation did not return an upload ID.")

    sent_upload = _send_notion_file_upload(
        runtime_config,
        file_upload_id=file_upload_id,
        file_path=local_image_path,
        content_type=content_type,
    )
    if str(sent_upload.get("status", "")).strip().lower() != "uploaded":
        raise RuntimeError(
            "Notion file upload did not reach uploaded status. "
            f"Current status: {sent_upload.get('status', '') or '-'}"
        )
    caption_payload = _to_rich_text_array(caption, "caption")
    append_result = _append_block_children(
        runtime_config,
        target_block_id=target_page_id,
        after_block_id=after,
        children=[
            {
                "object": "block",
                "type": "image",
                "image": {
                    "type": "file_upload",
                    "file_upload": {
                        "id": file_upload_id,
                    },
                    "caption": caption_payload,
                },
            }
        ],
    )
    page_obj = _request_json(runtime_config, method="GET", path=f"/pages/{target_page_id}")
    markdown_obj = _request_json(runtime_config, method="GET", path=f"/pages/{target_page_id}/markdown")
    data = _page_summary(page_obj)
    data.update(_markdown_summary(markdown_obj))
    data["local_image_path"] = str(local_image_path)
    data["image_file_size"] = local_image_path.stat().st_size
    data["image_content_type"] = content_type
    data["caption"] = caption_payload
    data["file_upload"] = _file_upload_summary(sent_upload if isinstance(sent_upload, dict) else created_upload)
    append_results = append_result.get("results") or []
    data["appended_blocks"] = [
        {
            "id": item.get("id", ""),
            "type": item.get("type", ""),
            "has_children": bool(item.get("has_children", False)),
        }
        for item in append_results
        if isinstance(item, dict)
    ]
    return ok(
        action="upload_image",
        path=target_page_id,
        message="Image uploaded to Notion and appended to the page successfully",
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
    data_source_obj = {}
    if target_data_source_id:
        request_body["parent"] = {"data_source_id": target_data_source_id}
    elif not isinstance(request_body.get("parent"), dict):
        raise ValueError("create_row requires data_source_id, data_source_url, database_id, database_url, or body.parent")
    else:
        raw_parent_data_source_id = request_body.get("parent", {}).get("data_source_id", "")
        if str(raw_parent_data_source_id).strip():
            effective_data_source_id = _extract_notion_id(raw_parent_data_source_id)

    merged_properties = dict(properties or {})
    if effective_data_source_id and (merged_properties or str(title or "").strip()):
        data_source_obj = _request_json(runtime_config, method="GET", path=f"/data_sources/{effective_data_source_id}")

    if merged_properties:
        if not data_source_obj:
            raise ValueError("create_row property normalization requires a data_source_id")
        merged_properties = _normalize_properties_for_schema(
            merged_properties,
            schema_properties=data_source_obj.get("properties") or {},
        )

    if str(title or "").strip():
        if not effective_data_source_id:
            raise ValueError("create_row title injection requires a data_source_id")
        if not data_source_obj:
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
    existing_page = {}

    if merged_properties or str(title or "").strip():
        existing_page = _request_json(runtime_config, method="GET", path=f"/pages/{target_row_page_id}")

    if merged_properties:
        merged_properties = _normalize_properties_for_schema(
            merged_properties,
            schema_properties=existing_page.get("properties") or {},
        )

    if str(title or "").strip():
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
    block_id: str = "",
    block_url: str = "",
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
    image_path: str = "",
    local_image_path: str = "",
    file_path: str = "",
    caption="",
    properties=None,
    initial_data_source=None,
    query=None,
    query_text: str = "",
    search_query: str = "",
    body=None,
    filter=None,
    sorts=None,
    page_size=None,
    start_cursor: str = "",
    sort_timestamp: str = "",
    sort_direction: str = "",
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
    image_index: int = 1,
    save_path: str = "",
    save_dir: str = "",
    filename: str = "",
    recursive: bool = True,
    replace_all_matches: bool = False,
    allow_deleting_content: bool = False,
    **kwargs,
):
    runtime_config = _load_runtime_config()
    effective_image_path = (
        str(image_path or "").strip()
        or str(local_image_path or "").strip()
        or str(file_path or "").strip()
    )
    path_hint = (
        row_page_id
        or row_page_url
        or data_source_id
        or data_source_url
        or database_id
        or database_url
        or block_id
        or block_url
        or page_id
        or page_url
        or parent_database_id
        or parent_database_url
        or parent_page_id
        or parent_page_url
        or effective_image_path
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

        if action == "sync_architecture":
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

        if action == "search":
            effective_query_text = str(search_query or "").strip() or str(query_text or "").strip()
            return _search(
                runtime_config,
                query_text=effective_query_text,
                object_type=object_type,
                page_size=page_size,
                start_cursor=start_cursor,
                sort_timestamp=sort_timestamp,
                sort_direction=sort_direction,
                body=request_body,
            )

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

        if action == "upload_image":
            target_page_id = _resolve_page_id(
                page_id=page_id,
                page_url=page_url,
                require_explicit=True,
                label="page",
            )
            return _mark_result_architecture_stale(
                _upload_image(
                    runtime_config,
                    target_page_id=target_page_id,
                    image_path=effective_image_path,
                    caption=caption,
                    after=after,
                )
            )

        if action == "download_image":
            target_block_id = ""
            if str(block_id or block_url).strip():
                target_block_id = _extract_notion_id(block_id or block_url)

            target_page_id = ""
            if not target_block_id:
                target_page_id = _resolve_page_id(
                    page_id=page_id,
                    page_url=page_url,
                    default_page_id=runtime_config.get("default_parent_page_id", ""),
                    require_explicit=False,
                    label="page",
                )

            return _download_image(
                runtime_config,
                target_page_id=target_page_id,
                target_block_id=target_block_id,
                image_index=image_index,
                save_path=save_path,
                save_dir=save_dir,
                filename=filename,
                recursive=bool(recursive),
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
