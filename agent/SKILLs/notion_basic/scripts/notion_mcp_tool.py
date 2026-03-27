from __future__ import annotations

import hashlib
import itertools
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib import error, request

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

DEFAULT_MCP_BASE_URL = "http://127.0.0.1:3000/mcp"
DEFAULT_PROTOCOL_VERSION = "2024-11-05"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 45
DEFAULT_STARTUP_TIMEOUT_SECONDS = 60
DEFAULT_PACKAGE_NAME = "@notionhq/notion-mcp-server"
LOCAL_MCP_LOG_PATH = AGENT_ROOT / ".codex-temp" / "notion_mcp_server.log"
REMOVED_LEGACY_ACTIONS = {
    "search",
    "read_page",
    "create_page",
    "write_page",
    "append_page",
    "upload_image",
    "download_image",
    "replace_text",
    "delete_page",
    "restore_page",
    "read_database",
    "read_data_source",
    "query_database",
    "query_data_source",
    "create_database",
    "create_data_source",
    "update_data_source",
    "create_row",
    "update_row",
    "delete_row",
    "restore_row",
    "sync_architecture",
}
META_MCP_ACTION_NAMES = {
    "tools/list",
    "list_tools",
    "tools/call",
    "call_tool",
}
_REQUEST_IDS = itertools.count(1)
_PROCESS_LOCK = threading.RLock()
_MCP_PROCESS: subprocess.Popen | None = None
_MCP_PROCESS_BASE_URL = ""


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


def _parse_bool(value, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_int(value, *, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _load_runtime_config() -> dict:
    all_secrets = load_secret_config()
    stored = all_secrets.get("notion", {}) if isinstance(all_secrets.get("notion"), dict) else {}
    api_key = str(os.getenv("OPENCLAW_NOTION_API_KEY") or stored.get("api_key") or "").strip()
    base_url = (
        str(os.getenv("OPENCLAW_NOTION_MCP_BASE_URL") or stored.get("mcp_base_url") or DEFAULT_MCP_BASE_URL)
        .strip()
        .rstrip("/")
    )
    auth_token = str(os.getenv("OPENCLAW_NOTION_MCP_AUTH_TOKEN") or stored.get("mcp_auth_token") or "").strip()
    auto_start = _parse_bool(
        os.getenv("OPENCLAW_NOTION_MCP_AUTO_START", stored.get("mcp_auto_start")),
        default=True,
    )
    request_timeout_seconds = _parse_int(
        os.getenv("OPENCLAW_NOTION_MCP_TIMEOUT_SECONDS") or stored.get("mcp_timeout_seconds"),
        default=DEFAULT_REQUEST_TIMEOUT_SECONDS,
    )
    startup_timeout_seconds = _parse_int(
        os.getenv("OPENCLAW_NOTION_MCP_STARTUP_TIMEOUT_SECONDS") or stored.get("mcp_startup_timeout_seconds"),
        default=DEFAULT_STARTUP_TIMEOUT_SECONDS,
    )
    npx_path = str(
        os.getenv("OPENCLAW_NOTION_MCP_NPX")
        or stored.get("mcp_npx_path")
        or shutil.which("npx.cmd")
        or shutil.which("npx")
        or ""
    ).strip()
    package_name = str(
        os.getenv("OPENCLAW_NOTION_MCP_PACKAGE") or stored.get("mcp_package") or DEFAULT_PACKAGE_NAME
    ).strip() or DEFAULT_PACKAGE_NAME
    derived_auth_token = auth_token
    if auto_start and not derived_auth_token and api_key:
        digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
        derived_auth_token = f"openclaw-notion-{digest[:32]}"

    return {
        "api_key": api_key,
        "base_url": base_url or DEFAULT_MCP_BASE_URL,
        "auth_token": derived_auth_token,
        "auto_start": auto_start,
        "request_timeout_seconds": request_timeout_seconds,
        "startup_timeout_seconds": startup_timeout_seconds,
        "npx_path": npx_path,
        "package_name": package_name,
        "config_path": str(SECRET_CONFIG_PATH),
    }


def _build_headers(runtime_config: dict, *, session_id: str = "", include_json: bool = True) -> dict:
    headers = {"Accept": "application/json, text/event-stream"}
    if include_json:
        headers["Content-Type"] = "application/json"
    auth_token = str(runtime_config.get("auth_token", "")).strip()
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    return headers


def _parse_sse_payload(raw_body: str) -> dict:
    events = []
    current_data_lines = []

    for raw_line in str(raw_body or "").splitlines():
        line = raw_line.strip()
        if not line:
            if current_data_lines:
                payload = "\n".join(current_data_lines).strip()
                if payload:
                    events.append(payload)
                current_data_lines = []
            continue
        if line.startswith("data:"):
            current_data_lines.append(line[5:].strip())

    if current_data_lines:
        payload = "\n".join(current_data_lines).strip()
        if payload:
            events.append(payload)

    for payload in reversed(events):
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            continue
    raise json.JSONDecodeError("No JSON payload found in SSE body", raw_body, 0)


def _http_post_json(runtime_config: dict, *, payload: dict, session_id: str = "") -> tuple[dict, str]:
    raw_payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url=runtime_config["base_url"],
        data=raw_payload,
        headers=_build_headers(runtime_config, session_id=session_id),
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=runtime_config["request_timeout_seconds"]) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
            content_type = str(response.headers.get("Content-Type", "")).lower()
            if not raw_body:
                response_payload = {}
            elif "text/event-stream" in content_type:
                response_payload = _parse_sse_payload(raw_body)
            else:
                response_payload = json.loads(raw_body)
            response_session_id = (
                response.headers.get("Mcp-Session-Id")
                or response.headers.get("mcp-session-id")
                or session_id
            )
            return response_payload, response_session_id
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Notion MCP HTTP {exc.code}: {body or exc.reason}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Notion MCP unavailable: {exc.reason}") from exc


def _json_rpc(runtime_config: dict, *, method: str, params: dict | None = None, session_id: str = ""):
    payload = {
        "jsonrpc": "2.0",
        "method": method,
    }
    if params is not None:
        payload["params"] = params
    if not method.startswith("notifications/"):
        payload["id"] = next(_REQUEST_IDS)

    response_payload, response_session_id = _http_post_json(
        runtime_config,
        payload=payload,
        session_id=session_id,
    )
    if method.startswith("notifications/"):
        return {}, response_session_id
    if "error" in response_payload:
        error_payload = response_payload.get("error") or {}
        raise RuntimeError(
            f"MCP {method} failed: {error_payload.get('message') or response_payload['error']}"
        )
    return response_payload.get("result", {}), response_session_id


def _initialize_session(runtime_config: dict) -> tuple[str, dict]:
    initialize_result, session_id = _json_rpc(
        runtime_config,
        method="initialize",
        params={
            "protocolVersion": DEFAULT_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {
                "name": "openclaw-notion-skill",
                "version": "1.0.0",
            },
        },
    )
    _json_rpc(
        runtime_config,
        method="notifications/initialized",
        params={},
        session_id=session_id,
    )
    return session_id, initialize_result


def _is_local_http_endpoint(base_url: str) -> bool:
    normalized = str(base_url or "").lower()
    return normalized.startswith("http://127.0.0.1:") or normalized.startswith("http://localhost:")


def _ensure_local_server(runtime_config: dict):
    global _MCP_PROCESS, _MCP_PROCESS_BASE_URL

    if not runtime_config.get("auto_start"):
        return
    if not _is_local_http_endpoint(runtime_config.get("base_url", "")):
        return

    with _PROCESS_LOCK:
        if _MCP_PROCESS and _MCP_PROCESS.poll() is None and _MCP_PROCESS_BASE_URL == runtime_config["base_url"]:
            return

        npx_path = str(runtime_config.get("npx_path", "")).strip()
        if not npx_path:
            raise RuntimeError(
                "Notion MCP auto-start is enabled but npx was not found. "
                "Set OPENCLAW_NOTION_MCP_NPX or notion.mcp_npx_path."
            )
        api_key = str(runtime_config.get("api_key", "")).strip()
        if not api_key:
            raise RuntimeError(
                "Notion MCP auto-start is enabled but no Notion token is configured. "
                f"Set OPENCLAW_NOTION_API_KEY or update {runtime_config['config_path']}."
            )

        port = 3000
        try:
            port = int(str(runtime_config["base_url"]).rsplit(":", 1)[-1].split("/", 1)[0])
        except (TypeError, ValueError):
            pass

        LOCAL_MCP_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        log_handle = LOCAL_MCP_LOG_PATH.open("a", encoding="utf-8")
        command_args = [
            npx_path,
            "-y",
            runtime_config["package_name"],
            "--transport",
            "http",
            "--port",
            str(port),
        ]
        auth_token = str(runtime_config.get("auth_token", "")).strip()
        if auth_token:
            command_args.extend(["--auth-token", auth_token])

        use_shell = False
        if os.name == "nt" and npx_path.lower().endswith((".cmd", ".bat")):
            arg_text = subprocess.list2cmdline(command_args[1:])
            command = f'call "{npx_path}" {arg_text}'.strip()
            use_shell = True
        else:
            command = command_args

        env = os.environ.copy()
        env["NOTION_TOKEN"] = api_key
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        _MCP_PROCESS = subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            shell=use_shell,
        )
        _MCP_PROCESS_BASE_URL = runtime_config["base_url"]

        deadline = time.time() + runtime_config["startup_timeout_seconds"]
        last_error = "Notion MCP did not finish startup"
        while time.time() < deadline:
            if _MCP_PROCESS.poll() is not None:
                raise RuntimeError(
                    "Notion MCP server exited during startup. "
                    f"Check {LOCAL_MCP_LOG_PATH} for details."
                )
            try:
                _initialize_session(runtime_config)
                return
            except RuntimeError as exc:
                last_error = str(exc)
                time.sleep(0.5)

        raise RuntimeError(
            f"Timed out waiting for Notion MCP server at {runtime_config['base_url']}: {last_error}. "
            f"Check {LOCAL_MCP_LOG_PATH} for details."
        )


def _extract_text(result: dict) -> str:
    parts = []
    for item in result.get("content", []) or []:
        if isinstance(item, dict) and item.get("type") == "text" and str(item.get("text", "")).strip():
            parts.append(str(item["text"]).strip())
    return "\n\n".join(parts).strip()


def _extract_embedded_error_payload(text_message: str) -> dict | None:
    cleaned = str(text_message or "").strip()
    if not cleaned:
        return None
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    status = payload.get("status")
    if isinstance(status, int) and status >= 400:
        return payload
    if str(payload.get("object", "")).strip().lower() == "error":
        return payload
    return None


def _list_tools(runtime_config: dict, *, action_name: str = "list_tools") -> dict:
    _ensure_local_server(runtime_config)
    session_id, initialize_result = _initialize_session(runtime_config)
    list_result, _ = _json_rpc(
        runtime_config,
        method="tools/list",
        params={},
        session_id=session_id,
    )
    tools = list_result.get("tools", []) if isinstance(list_result, dict) else []
    server_info = initialize_result.get("serverInfo", {}) if isinstance(initialize_result, dict) else {}
    return ok(
        action_name,
        runtime_config["base_url"],
        data={
            "tools": tools,
            "server_info": server_info,
        },
        message=f"Loaded {len(tools)} Notion MCP tools",
    )


def _call_tool(
    runtime_config: dict,
    *,
    tool_name: str,
    arguments: dict,
    action_name: str = "call_tool",
) -> dict:
    cleaned_tool_name = str(tool_name or "").strip()
    if not cleaned_tool_name:
        raise ValueError("tool_name is required")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")

    _ensure_local_server(runtime_config)
    session_id, initialize_result = _initialize_session(runtime_config)
    call_result, _ = _json_rpc(
        runtime_config,
        method="tools/call",
        params={
            "name": cleaned_tool_name,
            "arguments": arguments,
        },
        session_id=session_id,
    )
    text_message = _extract_text(call_result) if isinstance(call_result, dict) else ""
    server_info = initialize_result.get("serverInfo", {}) if isinstance(initialize_result, dict) else {}
    embedded_error = _extract_embedded_error_payload(text_message)
    if embedded_error is not None:
        return error_result(
            action_name,
            runtime_config["base_url"],
            text_message or f"Notion MCP tool returned an embedded error payload: {cleaned_tool_name}",
            data={
                "tool_name": cleaned_tool_name,
                "arguments": arguments,
                "mcp_result": call_result,
                "server_info": server_info,
                "embedded_error": embedded_error,
            },
        )
    if isinstance(call_result, dict) and call_result.get("isError"):
        return error_result(
            action_name,
            runtime_config["base_url"],
            text_message or f"Notion MCP tool returned an error: {cleaned_tool_name}",
            data={
                "tool_name": cleaned_tool_name,
                "arguments": arguments,
                "mcp_result": call_result,
                "server_info": server_info,
            },
        )
    return ok(
        action_name,
        runtime_config["base_url"],
        data={
            "tool_name": cleaned_tool_name,
            "arguments": arguments,
            "mcp_result": call_result,
            "server_info": server_info,
        },
        message=text_message or f"Called Notion MCP tool: {cleaned_tool_name}",
    )


def _validate_known_call_shapes(action_name: str, base_url: str, tool_name: str, arguments: dict):
    cleaned_tool_name = str(tool_name or "").strip()
    if cleaned_tool_name in META_MCP_ACTION_NAMES:
        return error_result(
            action_name,
            base_url,
            f"`{cleaned_tool_name}` is a notion-basic action, not a live Notion MCP tool name. "
            "Use the skill action directly instead of passing it through `tools/call`.",
            data={
                "tool_name": cleaned_tool_name,
                "arguments": arguments,
                "expected_action": cleaned_tool_name,
            },
        )

    if cleaned_tool_name == "API-post-page":
        if "database_id" in arguments and "parent" not in arguments:
            return error_result(
                action_name,
                base_url,
                "For `API-post-page`, put the destination database under `parent.database_id`, "
                "not top-level `database_id`.",
                data={
                    "tool_name": cleaned_tool_name,
                    "arguments": arguments,
                    "expected_shape": {
                        "parent": {
                            "database_id": str(arguments.get("database_id", "")),
                        },
                        "properties": arguments.get("properties", {}),
                    },
                },
            )

    return None


def run(action: str, **kwargs):
    runtime_config = _load_runtime_config()
    cleaned_action = str(action or "").strip()
    if not cleaned_action:
        return error_result("unknown", runtime_config["base_url"], "Missing action")

    try:
        if cleaned_action in {"list_tools", "tools/list"}:
            if kwargs:
                unexpected_keys = ", ".join(sorted(str(key) for key in kwargs.keys()))
                return error_result(
                    cleaned_action,
                    runtime_config["base_url"],
                    f"`{cleaned_action}` does not accept arguments. Unexpected keys: {unexpected_keys}",
                    data={"unexpected_keys": sorted(str(key) for key in kwargs.keys())},
                )
            return _list_tools(runtime_config, action_name=cleaned_action)

        if cleaned_action in {"call_tool", "tools/call"}:
            raw_name = kwargs.pop("name", "")
            raw_tool_name = kwargs.pop("tool_name", "")
            if raw_name and raw_tool_name and str(raw_name).strip() != str(raw_tool_name).strip():
                return error_result(
                    cleaned_action,
                    runtime_config["base_url"],
                    "`name` and `tool_name` both appeared but did not match.",
                    data={
                        "name": str(raw_name),
                        "tool_name": str(raw_tool_name),
                    },
                )
            tool_name = str(raw_name or raw_tool_name or "").strip()
            explicit_arguments = kwargs.pop("arguments", None)
            if kwargs:
                unexpected_keys = sorted(str(key) for key in kwargs.keys())
                return error_result(
                    cleaned_action,
                    runtime_config["base_url"],
                    "For notion-basic `tools/call`, args must use only `name` and `arguments`."
                    f" Unexpected keys: {', '.join(unexpected_keys)}",
                    data={
                        "tool_name": tool_name,
                        "unexpected_keys": unexpected_keys,
                    },
                )
            if explicit_arguments is None:
                explicit_arguments = {}
            known_shape_error = _validate_known_call_shapes(
                cleaned_action,
                runtime_config["base_url"],
                tool_name,
                explicit_arguments,
            )
            if known_shape_error is not None:
                return known_shape_error
            return _call_tool(
                runtime_config,
                tool_name=tool_name,
                arguments=explicit_arguments,
                action_name=cleaned_action,
            )

        if cleaned_action in REMOVED_LEGACY_ACTIONS:
            return error_result(
                cleaned_action,
                runtime_config["base_url"],
                "Legacy Notion REST actions were removed. Use `tools/list` first, then call the live Notion MCP tool with `tools/call`.",
                data={"action": cleaned_action},
            )

        return error_result(
            cleaned_action,
            runtime_config["base_url"],
            "Unsupported notion-basic action. Use `tools/list` or `tools/call`.",
            data={"action": cleaned_action},
        )
    except Exception as exc:
        return error_result(cleaned_action or "unknown", runtime_config["base_url"], str(exc))
