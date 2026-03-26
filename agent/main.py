import base64
import mimetypes
import shlex
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

from config_loader import Config
from lmstudio_client import LMStudioClient
from agent import SimpleAgent
from chat_scheduler import ChatScheduler
from schedule_runtime import create_task, delete_task, list_tasks, record_task_result
from system_doc_generator import generate_system_architecture
from terminal_display import TerminalDisplay
from telegram_bridge import TelegramBridge


HELP_TEXT = """Available commands:
/help                      Show this help message
/exit | /quit              Exit the agent
/model [name]              Show the current model or switch it for this session
  reset                    Reset the active model to the config default
  save <name>              Save a new default model to config and use it immediately
/clear <history|cache>     Clear in-memory history or cache directories
  history                  Clear in-memory chat history for this session
  cache                    Delete .codex-temp cache directories only
/task                      Show task subcommands
  list                     List scheduled tasks
  remove <id|name>         Remove one scheduled task by ID or task name
  remove -all              Remove all scheduled tasks
/think [on|off]            Show current [THINK] status or toggle it
/reload                    Reload config, prompts, skills, and runtime clients
/status                    Show the current model, history size, display categories, and endpoint URLs"""

CLEAR_HELP_TEXT = """Clear commands:
/clear <history|cache>     Clear in-memory history or cache directories
  history                  Clear in-memory chat history for this session
  cache                    Delete .codex-temp cache directories only"""

TASK_HELP_TEXT = """Task commands:
/task list                  List scheduled tasks
/task remove <id|name|-all> Remove one or all scheduled tasks"""

THINK_HELP_TEXT = """Think commands:
/think [on|off]            Show the current [THINK] setting or toggle it
  on                       Show [THINK n] output
  off                      Hide [THINK n] output"""

TELEGRAM_STREAM_REFRESH_SECONDS = 0.3
TELEGRAM_STREAM_PREVIEW_LIMIT = 3500


def format_scheduled_trigger(event: dict) -> str:
    name = event.get("short_name") or event.get("task_name") or "scheduled-task"
    trigger = event.get("trigger", "scheduled")
    parts = [f"Scheduled task triggered: {name}", f"trigger={trigger}"]
    task_id = str(event.get("task_id", "")).strip()
    if task_id:
        parts.append(f"id={task_id}")
    scheduled_for = str(event.get("scheduled_for", "")).strip()
    if scheduled_for:
        parts.append(f"scheduled_for={scheduled_for}")
    next_run_at = str(event.get("next_run_at", "")).strip()
    if next_run_at:
        parts.append(f"next_run_at={next_run_at}")
    return "\n".join(parts)


def format_telegram_trace_reply(reply: str, events: list[dict]) -> str:
    parts = []
    for event in events:
        rendered = str(event.get("rendered", "")).strip()
        if rendered:
            parts.append(rendered)

    final_reply = str(reply or "").strip()
    if final_reply:
        parts.append(final_reply)

    return "\n\n".join(parts)


def _format_telegram_delivery_errors(label: str, errors: list[dict]) -> str:
    lines = [f"Telegram {label} delivery error(s):"]
    for item in errors:
        lines.append(f"chat={item.get('chat_id')} error={item.get('error')}")
    return "\n".join(lines)


def _format_saved_telegram_images(images: list[dict]) -> str:
    if not images:
        return ""

    noun = "image" if len(images) == 1 else "images"
    lines = [f"Saved Telegram {noun} locally:"]
    for index, image in enumerate(images, start=1):
        path = str(image.get("saved_path", "")).strip() or "-"
        parts = [f"{index}. {path}"]
        width = image.get("width")
        height = image.get("height")
        if width and height:
            parts.append(f"{width}x{height}")
        mime_type = str(image.get("mime_type", "")).strip()
        if mime_type:
            parts.append(mime_type)
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def _looks_like_tool_payload(text: str) -> bool:
    stripped = str(text or "").lstrip()
    if not stripped:
        return False
    if stripped.startswith("{"):
        return True
    if stripped.startswith("```"):
        fence_body = stripped[3:].lstrip()
        if fence_body.lower().startswith("json") or fence_body.startswith("{"):
            return True
    head = stripped[:200]
    return '"skill"' in head and '"action"' in head


class TelegramRollingReply:
    def __init__(
        self,
        telegram_bridge: TelegramBridge,
        *,
        chat_id: int,
        refresh_seconds: float = TELEGRAM_STREAM_REFRESH_SECONDS,
        preview_limit: int = TELEGRAM_STREAM_PREVIEW_LIMIT,
    ):
        self.telegram_bridge = telegram_bridge
        self.chat_id = int(chat_id)
        self.refresh_seconds = float(refresh_seconds)
        self.preview_limit = int(preview_limit)
        self.message_id = None
        self.last_sent_text = ""
        self.last_sent_at = 0.0
        self.pending_text = ""
        self.finalized = False

    def _preview_text(self, text: str) -> str:
        cleaned = str(text or "").strip()
        if len(cleaned) <= self.preview_limit:
            return cleaned
        return cleaned[: max(1, self.preview_limit - 1)].rstrip() + "…"

    def _send_or_edit(self, text: str) -> bool:
        cleaned = str(text or "").strip()
        if not cleaned:
            return False

        try:
            if self.message_id is None:
                results = self.telegram_bridge.send_text(self.chat_id, cleaned)
                first_result = results[0] if results else {}
                message_id = first_result.get("message_id") if isinstance(first_result, dict) else None
                if message_id is not None:
                    self.message_id = int(message_id)
            else:
                self.telegram_bridge.edit_message_text(
                    self.chat_id,
                    int(self.message_id),
                    cleaned,
                )
        except Exception:
            return False

        self.last_sent_text = cleaned
        self.last_sent_at = time.monotonic()
        self.pending_text = ""
        return True

    def push_preview(self, text: str):
        if self.finalized:
            return

        cleaned = str(text or "").strip()
        if not cleaned or _looks_like_tool_payload(cleaned):
            return

        preview = self._preview_text(cleaned)
        if not preview or preview == self.last_sent_text:
            return

        now = time.monotonic()
        if self.message_id is not None and (now - self.last_sent_at) < self.refresh_seconds:
            self.pending_text = preview
            return

        self._send_or_edit(preview)

    def finalize(self, text: str) -> bool:
        if self.finalized:
            return True
        self.finalized = True

        final_text = str(text or "").strip()
        if not final_text:
            return False

        chunks = self.telegram_bridge._split_text(final_text, limit=self.preview_limit)
        if not chunks:
            return False

        try:
            if self.message_id is None:
                self.telegram_bridge.send_text(self.chat_id, final_text)
                return True

            if chunks[0] != self.last_sent_text:
                self.telegram_bridge.edit_message_text(
                    self.chat_id,
                    int(self.message_id),
                    chunks[0],
                )
            for chunk in chunks[1:]:
                self.telegram_bridge.send_text(self.chat_id, chunk)
            return True
        except Exception:
            try:
                self.telegram_bridge.send_text(self.chat_id, final_text)
                return True
            except Exception:
                return False


def image_file_to_data_url(image_path: Path) -> str:
    resolved_path = Path(image_path).expanduser().resolve()
    if not resolved_path.is_file():
        raise FileNotFoundError(f"Image not found: {resolved_path}")

    mime_type, _ = mimetypes.guess_type(str(resolved_path))
    if not mime_type:
        mime_type = "application/octet-stream"

    encoded = base64.b64encode(resolved_path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def _build_telegram_image_prompt(event: dict) -> str:
    images = [item for item in (event.get("images") or []) if isinstance(item, dict)]
    lines = [
        "A Telegram user sent image attachment(s).",
        "The saved local file paths are listed below.",
        "Use the attached image(s) together with the caption/request.",
    ]

    caption = str(event.get("caption", "")).strip()
    text = str(event.get("text", "")).strip()
    if caption:
        lines.extend(["Caption:", caption])
    elif text:
        lines.extend(["Message text:", text])
    else:
        lines.append("No caption was provided.")

    lines.append("Saved image files:")
    for index, image in enumerate(images, start=1):
        saved_path = str(image.get("saved_path", "")).strip() or "-"
        details = [f"{index}. path={saved_path}"]
        original_name = str(image.get("original_name", "")).strip()
        if original_name:
            details.append(f"original_name={original_name}")
        mime_type = str(image.get("mime_type", "")).strip()
        if mime_type:
            details.append(f"mime_type={mime_type}")
        width = image.get("width")
        height = image.get("height")
        if width and height:
            details.append(f"size={width}x{height}")
        byte_count = image.get("bytes")
        if byte_count is not None:
            details.append(f"bytes={byte_count}")
        lines.append(", ".join(details))

    lines.append(
        "Respond based on the user's caption/request and mention the saved local path(s) when useful."
    )
    return "\n".join(lines)


def _build_telegram_image_user_input(event: dict):
    images = [item for item in (event.get("images") or []) if isinstance(item, dict)]
    content = [{"type": "text", "text": _build_telegram_image_prompt(event)}]
    for image in images:
        saved_path = str(image.get("saved_path", "")).strip()
        if not saved_path:
            continue
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": image_file_to_data_url(Path(saved_path)),
                },
            }
        )
    return content


def describe_model(config: Config) -> str:
    if config.has_runtime_model_override():
        return f"{config.model} (session override, config default: {config.default_model})"
    return f"{config.model} (config default)"


def format_status(config: Config, agent: SimpleAgent) -> str:
    display_states = [
        f"think={'on' if agent.display_category_enabled('think') else 'off'}",
        f"tool={'on' if agent.display_category_enabled('tool') else 'off'}",
        f"system={'on' if agent.display_category_enabled('system') else 'off'}",
    ]
    return "\n".join(
        [
            f"Model: {describe_model(config)}",
            f"History messages: {agent.history_size()}",
            f"LLM streaming: {'enabled' if getattr(config, 'stream', False) else 'disabled'}",
            f"Display categories: {', '.join(display_states)}",
            f"Skill server: {config.skill_server_url}",
            f"LLM base URL: {config.base_url}",
            f"Telegram bridge: {'enabled' if config.telegram_enabled and config.telegram_bot_token else 'disabled'}",
        ]
    )


def clear_project_cache(project_root: Path) -> dict:
    cache_dirs = [
        project_root / ".codex-temp",
        project_root / "agent" / ".codex-temp",
    ]
    cleared_dirs = []
    for cache_dir in cache_dirs:
        existed = cache_dir.exists()
        if existed:
            shutil.rmtree(cache_dir)
        cleared_dirs.append(
            {
                "path": str(cache_dir),
                "removed": existed,
            }
        )

    return {
        "cache_dirs": cleared_dirs,
    }


def _normalize_task_name(value: str) -> str:
    normalized = str(value or "").strip().replace("\\", "/")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return normalized.strip("/")


def _resolve_task_identifier(tasks: list[dict], identifier: str) -> dict | None:
    cleaned = str(identifier or "").strip()
    if not cleaned:
        return None

    upper_identifier = cleaned.upper()
    normalized_identifier = _normalize_task_name(cleaned)

    for task in tasks:
        if str(task.get("id", "")).upper() == upper_identifier:
            return task

    for task in tasks:
        if _normalize_task_name(task.get("task_name", "")) == normalized_identifier:
            return task

    short_name_matches = [
        task
        for task in tasks
        if _normalize_task_name(task.get("short_name", "")) == normalized_identifier
    ]
    if len(short_name_matches) == 1:
        return short_name_matches[0]

    return None


def _format_task_datetime(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    try:
        return datetime.fromisoformat(text).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text


def _format_task_status(task: dict) -> str:
    if task.get("deleted"):
        return "deleted"
    if task.get("completed"):
        return "completed"
    if task.get("pending_now"):
        return "queued"
    if task.get("enabled"):
        return "enabled"
    return "disabled"


def _format_task_list(tasks: list[dict]) -> str:
    if not tasks:
        return "No scheduled tasks."

    lines = [f"Scheduled tasks ({len(tasks)}):"]
    for task in tasks:
        lines.append(
            " - ".join(
                [
                    str(task.get("id", "")).strip() or "-",
                    str(task.get("task_name", "")).strip() or "-",
                    str(task.get("schedule_type", "")).strip() or "-",
                    _format_task_status(task),
                    f"next={_format_task_datetime(task.get('next_run_at', ''))}",
                ]
            )
        )
    return "\n".join(lines)


def _format_task_days(task: dict) -> str:
    days = [str(day).strip() for day in (task.get("days_of_week") or []) if str(day).strip()]
    return ",".join(days) if days else "-"


def _format_task_summary(task: dict) -> str:
    return "\n".join(
        [
            f"id: {str(task.get('id', '')).strip() or '-'}",
            f"name: {str(task.get('task_name', '')).strip() or '-'}",
            f"schedule: {str(task.get('schedule_type', '')).strip() or '-'}",
            f"date: {str(task.get('start_date', '')).strip() or '-'}",
            f"time: {str(task.get('start_time', '')).strip() or '-'}",
            f"modifier: {task.get('modifier') if task.get('modifier') is not None else '-'}",
            f"days: {_format_task_days(task)}",
            f"status: {_format_task_status(task)}",
            f"next: {_format_task_datetime(task.get('next_run_at', ''))}",
            "",
            f"prompt: {str(task.get('task_prompt', '')).strip() or '-'}",
        ]
    )


def _task_action_reply_markup(task_id: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {
                    "text": "編輯",
                    "callback_data": f"task:edit:{task_id}",
                },
                {
                    "text": "刪除",
                    "callback_data": f"task:delete:{task_id}",
                },
            ]
        ]
    }


def _task_edit_reply_markup(task_id: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {
                    "text": "改時間",
                    "callback_data": f"task:field:start_time:{task_id}",
                },
                {
                    "text": "改日期",
                    "callback_data": f"task:field:start_date:{task_id}",
                },
            ],
            [
                {
                    "text": "改內容",
                    "callback_data": f"task:field:task_prompt:{task_id}",
                },
                {
                    "text": "取消",
                    "callback_data": f"task:cancel:{task_id}",
                },
            ],
        ]
    }


def _task_edit_instruction(task: dict, field: str) -> str:
    field_prompts = {
        "start_time": "請直接回覆新的時間，格式 `HH:MM`，例如 `18:30`。",
        "start_date": "請直接回覆新的日期，格式 `YYYY-MM-DD`，例如 `2026-03-25`。",
        "task_prompt": "請直接回覆新的任務內容。",
    }
    instruction = field_prompts.get(field, "請直接回覆新的值。")
    return "\n".join(
        [
            "Task edit pending.",
            instruction,
            "輸入 `/cancel` 可以取消這次編輯。",
            "",
            _format_task_summary(task),
        ]
    )


def _apply_task_edit(task: dict, *, field: str, raw_value: str, actor: str) -> dict:
    value = str(raw_value or "").strip()
    if not value:
        raise ValueError("New value cannot be empty.")

    if field not in {"start_time", "start_date", "task_prompt"}:
        raise ValueError(f"Unsupported edit field: {field}")

    enabled = bool(task.get("enabled"))
    if field in {"start_time", "start_date"} and (
        bool(task.get("completed")) or not bool(task.get("enabled"))
    ):
        enabled = True

    return create_task(
        name=str(task.get("task_name", "")).strip(),
        task_prompt=value if field == "task_prompt" else str(task.get("task_prompt", "")).strip(),
        schedule_type=str(task.get("schedule_type", "")).strip(),
        start_time=value if field == "start_time" else str(task.get("start_time", "")).strip(),
        start_date=value if field == "start_date" else str(task.get("start_date", "")).strip(),
        modifier=task.get("modifier"),
        days_of_week=list(task.get("days_of_week", []) or []),
        overwrite=True,
        enabled=enabled,
        reason=f"Edited via Telegram inline action by {actor or 'telegram'}",
    )


def _extract_tool_field(text: str, key: str) -> str:
    marker = f"{key}="
    start = text.find(marker)
    if start < 0:
        return ""
    start += len(marker)
    end = text.find(" ", start)
    if end < 0:
        end = len(text)
    return text[start:end].strip().strip('"')


def _extract_tool_step(text: str) -> str:
    if not str(text).startswith("step="):
        return ""
    start = len("step=")
    end = str(text).find(" ", start)
    if end < 0:
        end = len(str(text))
    return str(text)[start:end].strip()


def _format_telegram_tool_event(event: dict) -> dict | None:
    text = str(event.get("text", "")).strip()
    rendered = str(event.get("rendered", "")).strip()
    if not text.startswith("step="):
        return None

    kind = ""
    if " call: " in text:
        kind = "call"
    elif " result: " in text:
        kind = "result"
    else:
        return None

    skill = _extract_tool_field(text, "skill")
    action = _extract_tool_field(text, "action")
    status = _extract_tool_field(text, "status")
    step = _extract_tool_step(text)

    if skill and action:
        if kind == "call":
            summary = f"[TOOL] {skill}.{action}"
        else:
            suffix = f" {status}" if status else ""
            summary = f"[TOOL RESULT] {skill}.{action}{suffix}"
    else:
        summary = "[TOOL]" if kind == "call" else "[TOOL RESULT]"

    return {
        "summary": summary,
        "details": rendered or text or summary,
        "kind": kind,
        "status": status,
        "key": "|".join([step or "-", skill or "-", action or "-"]),
    }


def _tool_event_reply_markup(event_id: str, *, expanded: bool) -> dict:
    return {
        "inline_keyboard": [
            [
                {
                    "text": "收合" if expanded else "展開",
                    "callback_data": f"tool:{'hide' if expanded else 'show'}:{event_id}",
                }
            ]
        ]
    }


def handle_cli_command(
    command_line: str,
    *,
    config: Config,
    agent: SimpleAgent,
) -> dict:
    stripped = command_line.strip()
    if not stripped.startswith("/"):
        return {"handled": False, "exit_requested": False, "message": ""}

    try:
        parts = shlex.split(stripped)
    except ValueError as exc:
        return {
            "handled": True,
            "exit_requested": False,
            "message": f"Command parse error: {exc}",
        }

    if not parts:
        return {"handled": True, "exit_requested": False, "message": ""}

    command = parts[0].lower()
    args = parts[1:]

    if command in {"/help", "/?", "/commands"}:
        return {"handled": True, "exit_requested": False, "message": HELP_TEXT}

    if command in {"/exit", "/quit"}:
        return {"handled": True, "exit_requested": True, "message": "Exiting agent."}

    if command == "/clear-history":
        return {
            "handled": True,
            "exit_requested": False,
            "message": 'Use "/clear history" instead.',
        }

    if command == "/clear-cache":
        return {
            "handled": True,
            "exit_requested": False,
            "message": 'Use "/clear cache" instead.',
        }

    if command == "/clear":
        if not args:
            return {
                "handled": True,
                "exit_requested": False,
                "message": CLEAR_HELP_TEXT,
            }

        subcommand = args[0].lower()
        if subcommand == "history" and len(args) == 1:
            cleared = agent.clear_history()
            return {
                "handled": True,
                "exit_requested": False,
                "message": f"Cleared in-memory chat history ({cleared} message(s)).",
            }

        if subcommand == "cache" and len(args) == 1:
            project_root = Path(__file__).resolve().parent.parent
            cleared = clear_project_cache(project_root)
            cache_lines = [
                f"{entry['path']}: {'deleted' if entry['removed'] else 'already empty'}"
                for entry in cleared["cache_dirs"]
            ]
            return {
                "handled": True,
                "exit_requested": False,
                "message": "Cleared cache directories.\n" + "\n".join(cache_lines),
            }

        return {
            "handled": True,
            "exit_requested": False,
            "message": f'Unknown /clear subcommand: {" ".join(args)}\n\n{CLEAR_HELP_TEXT}',
        }

    if command == "/task":
        if not args:
            return {
                "handled": True,
                "exit_requested": False,
                "message": TASK_HELP_TEXT,
            }

        subcommand = args[0].lower()
        if subcommand == "list" and len(args) == 1:
            tasks = list_tasks(include_deleted=False)
            return {
                "handled": True,
                "exit_requested": False,
                "message": _format_task_list(tasks),
            }

        if subcommand in {"remove", "delete"}:
            if len(args) == 2 and args[1].lower() == "-all":
                tasks = list_tasks(include_deleted=False)
                if not tasks:
                    return {
                        "handled": True,
                        "exit_requested": False,
                        "message": "No scheduled tasks to remove.",
                    }

                removed_names = []
                for task in tasks:
                    delete_task(
                        task.get("task_name", ""),
                        reason="Removed via /task remove -all",
                    )
                    removed_names.append(task.get("task_name", ""))

                return {
                    "handled": True,
                    "exit_requested": False,
                    "message": (
                        f"Removed {len(removed_names)} scheduled task(s).\n"
                        + "\n".join(f"- {name}" for name in removed_names)
                    ),
                }

            identifier = " ".join(args[1:]).strip()
            if not identifier:
                return {
                    "handled": True,
                    "exit_requested": False,
                    "message": f'Usage: /task remove <id|name|-all>\n\n{TASK_HELP_TEXT}',
                }

            tasks = list_tasks(include_deleted=False)
            task = _resolve_task_identifier(tasks, identifier)
            if not task:
                return {
                    "handled": True,
                    "exit_requested": False,
                    "message": f"Task not found: {identifier}",
                }

            delete_task(
                task.get("task_name", ""),
                reason=f"Removed via /task remove ({identifier})",
            )
            return {
                "handled": True,
                "exit_requested": False,
                "message": (
                    "Removed scheduled task.\n"
                    f"id: {task.get('id', '')}\n"
                    f"name: {task.get('task_name', '')}"
                ),
            }

        return {
            "handled": True,
            "exit_requested": False,
            "message": f'Unknown /task subcommand: {" ".join(args)}\n\n{TASK_HELP_TEXT}',
        }

    if command == "/think":
        if not args:
            return {
                "handled": True,
                "exit_requested": False,
                "message": (
                    f"Current [THINK] output: {'on' if agent.think_enabled() else 'off'}\n\n"
                    f"{THINK_HELP_TEXT}"
                ),
            }

        subcommand = args[0].lower()
        if subcommand == "on" and len(args) == 1:
            agent.set_show_think(True)
            return {
                "handled": True,
                "exit_requested": False,
                "message": "Enabled [THINK] output for this session.",
            }

        if subcommand == "off" and len(args) == 1:
            agent.set_show_think(False)
            return {
                "handled": True,
                "exit_requested": False,
                "message": "Disabled [THINK] output for this session.",
            }

        return {
            "handled": True,
            "exit_requested": False,
            "message": f'Unknown /think subcommand: {" ".join(args)}\n\n{THINK_HELP_TEXT}',
        }

    if command == "/status":
        if args:
            return {
                "handled": True,
                "exit_requested": False,
                "message": f"Unexpected arguments for {command}",
            }
        return {
            "handled": True,
            "exit_requested": False,
            "message": format_status(config, agent),
        }

    if command == "/reload":
        if args:
            return {
                "handled": True,
                "exit_requested": False,
                "message": f"Unexpected arguments for {command}",
            }
        config.reload_now()
        agent.refresh_runtime_clients()
        architecture_path = generate_system_architecture(config)
        return {
            "handled": True,
            "exit_requested": False,
            "message": (
                "Reloaded config, prompts, skills, and runtime clients.\n"
                f"Model: {describe_model(config)}\n"
                f"System doc: {architecture_path}"
            ),
        }

    if command == "/model":
        if not args:
            return {
                "handled": True,
                "exit_requested": False,
                "message": f"Current model: {describe_model(config)}",
            }

        subcommand = args[0].lower()
        if subcommand in {"reset", "default"} and len(args) == 1:
            config.reset_runtime_model()
            return {
                "handled": True,
                "exit_requested": False,
                "message": f"Model reset to config default: {config.model}",
            }

        if subcommand == "save":
            model_name = " ".join(args[1:]).strip()
            if not model_name:
                return {
                    "handled": True,
                    "exit_requested": False,
                    "message": "Usage: /model save <name>",
                }
            config.save_model(model_name)
            agent.refresh_runtime_clients()
            return {
                "handled": True,
                "exit_requested": False,
                "message": f"Saved and activated model: {describe_model(config)}",
            }

        model_name = " ".join(args).strip()
        if not model_name:
            return {
                "handled": True,
                "exit_requested": False,
                "message": "Usage: /model <name>",
            }
        config.set_runtime_model(model_name)
        return {
            "handled": True,
            "exit_requested": False,
            "message": f"Active model changed for this session: {describe_model(config)}",
        }

    return {
        "handled": True,
        "exit_requested": False,
        "message": f"Unknown command: {command}\n\n{HELP_TEXT}",
    }


def main():
    config_path = Path(__file__).resolve().parent / "config" / "config.json"
    config = Config(str(config_path))
    display = TerminalDisplay()
    architecture_path = generate_system_architecture(config)
    display.system(f"System doc generated: {architecture_path}")
    client = LMStudioClient(base_url=config.base_url, api_key=config.api_key)
    agent = SimpleAgent(config=config, client=client, display=display)
    telegram_agents = {}
    telegram_bridge = None
    telegram_task_edits = {}
    telegram_tool_events = {}
    telegram_tool_lock = threading.Lock()
    telegram_tool_counter = {"value": 0}

    def build_agent_session():
        return SimpleAgent(
            config=config,
            client=LMStudioClient(base_url=config.base_url, api_key=config.api_key),
            display=display,
        )

    def get_telegram_agent(chat_id: int) -> SimpleAgent:
        if chat_id not in telegram_agents:
            telegram_agents[chat_id] = build_agent_session()
        return telegram_agents[chat_id]

    def handle_remote_command(command_text: str, session_agent: SimpleAgent) -> str:
        command_result = handle_cli_command(command_text, config=config, agent=session_agent)
        if not command_result["handled"]:
            return ""
        if command_result["exit_requested"]:
            return "This command is only available in the terminal session."
        return command_result["message"].strip() or "Done."

    def broadcast_to_telegram(
        text: str,
        *,
        label: str,
        reply_markup: dict | None = None,
        chat_ids=None,
    ):
        cleaned = str(text or "").strip()
        if not cleaned or not telegram_bridge:
            return

        result = telegram_bridge.broadcast_text(
            cleaned,
            reply_markup=reply_markup,
            chat_ids=chat_ids,
        )
        errors = result.get("errors", [])
        if errors:
            display.system_block(_format_telegram_delivery_errors(label, errors), notify=False)
        return result

    def resolve_active_task(identifier: str) -> dict | None:
        tasks = list_tasks(include_deleted=False)
        return _resolve_task_identifier(tasks, identifier)

    def telegram_edit_key(chat_id: int, user_id) -> tuple[int, int]:
        return (int(chat_id), int(user_id or 0))

    def remember_tool_event(summary: str, details: str) -> str:
        with telegram_tool_lock:
            telegram_tool_counter["value"] += 1
            event_id = f"tool-{telegram_tool_counter['value']}"
            telegram_tool_events[event_id] = {
                "summary": str(summary or "").strip(),
                "details": str(details or "").strip(),
            }
            while len(telegram_tool_events) > 200:
                oldest_key = next(iter(telegram_tool_events))
                telegram_tool_events.pop(oldest_key, None)
        return event_id

    def build_tool_streamer(*, chat_ids) -> callable:
        targets = sorted({int(chat_id) for chat_id in (chat_ids or [])})
        pending_messages = {}

        def handle_event(event: dict):
            if not telegram_bridge or not targets:
                return

            tool_event = _format_telegram_tool_event(event)
            if not tool_event:
                return

            event_key = str(tool_event.get("key", "")).strip()
            if tool_event.get("kind") == "call":
                event_id = remember_tool_event(
                    tool_event["summary"],
                    tool_event["details"],
                )
                result = broadcast_to_telegram(
                    tool_event["summary"],
                    label="tool-progress",
                    reply_markup=_tool_event_reply_markup(event_id, expanded=False),
                    chat_ids=targets,
                )
                message_ids_by_chat = {}
                for delivery in result.get("deliveries", []):
                    chat_id = delivery.get("chat_id")
                    message_id = delivery.get("message_id")
                    if chat_id is None or message_id is None:
                        continue
                    message_ids_by_chat[int(chat_id)] = int(message_id)

                pending_messages[event_key] = {
                    "event_id": event_id,
                    "summary": tool_event["summary"],
                    "details": tool_event["details"],
                    "message_ids_by_chat": message_ids_by_chat,
                }
                return

            if tool_event.get("kind") == "result":
                pending = pending_messages.pop(event_key, None)
                if not pending:
                    event_id = remember_tool_event(
                        tool_event["summary"],
                        tool_event["details"],
                    )
                    broadcast_to_telegram(
                        tool_event["summary"],
                        label="tool-progress",
                        reply_markup=_tool_event_reply_markup(event_id, expanded=False),
                        chat_ids=targets,
                    )
                    return

                event_id = pending["event_id"]
                combined_summary = pending["summary"]
                status = str(tool_event.get("status", "")).strip()
                if status:
                    combined_summary = f"{combined_summary} -> {status}"
                else:
                    combined_summary = f"{combined_summary} -> done"

                combined_details = "\n".join(
                    part
                    for part in [
                        str(pending.get("details", "")).strip(),
                        str(tool_event.get("details", "")).strip(),
                    ]
                    if part
                )
                with telegram_tool_lock:
                    telegram_tool_events[event_id] = {
                        "summary": combined_summary,
                        "details": combined_details,
                    }

                for target_chat_id in targets:
                    message_id = pending["message_ids_by_chat"].get(int(target_chat_id))
                    if message_id is None:
                        broadcast_to_telegram(
                            combined_summary,
                            label="tool-progress",
                            reply_markup=_tool_event_reply_markup(event_id, expanded=False),
                            chat_ids=[int(target_chat_id)],
                        )
                        continue

                    try:
                        telegram_bridge.edit_message_text(
                            int(target_chat_id),
                            int(message_id),
                            combined_summary,
                            reply_markup=_tool_event_reply_markup(event_id, expanded=False),
                        )
                    except Exception:
                        broadcast_to_telegram(
                            combined_summary,
                            label="tool-progress",
                            reply_markup=_tool_event_reply_markup(event_id, expanded=False),
                            chat_ids=[int(target_chat_id)],
                        )

        return handle_event

    def on_telegram_callback(event: dict):
        if not telegram_bridge:
            return

        chat_id = int(event.get("chat_id"))
        user_id = event.get("user_id")
        key = telegram_edit_key(chat_id, user_id)
        callback_query_id = str(event.get("callback_query_id", "")).strip()
        data = str(event.get("data", "")).strip()
        message_id = event.get("message_id")
        actor = str(event.get("username") or event.get("display_name") or chat_id).strip()

        def answer(text: str = "", *, show_alert: bool = False):
            if callback_query_id:
                telegram_bridge.answer_callback_query(
                    callback_query_id,
                    text=text,
                    show_alert=show_alert,
                )

        if data.startswith("tool:show:") or data.startswith("tool:hide:"):
            parts = data.split(":", 2)
            if len(parts) != 3:
                answer("Invalid tool action.", show_alert=True)
                return

            mode = parts[1].strip()
            event_id = parts[2].strip()
            payload = telegram_tool_events.get(event_id)
            if not payload:
                answer("Tool details expired.", show_alert=True)
                return

            if message_id is None:
                answer()
                return

            expanded = mode == "show"
            telegram_bridge.edit_message_text(
                chat_id,
                int(message_id),
                payload["details"] if expanded else payload["summary"],
                reply_markup=_tool_event_reply_markup(event_id, expanded=expanded),
            )
            answer()
            return

        if data.startswith("task:delete:"):
            identifier = data.split(":", 2)[2].strip()
            task = resolve_active_task(identifier)
            if not task:
                answer("Task not found or already deleted.", show_alert=True)
                return

            delete_task(
                task.get("task_name", ""),
                reason=f"Removed via Telegram inline action by {actor}",
            )
            pending = telegram_task_edits.get(key)
            if pending and pending.get("task_id") == task.get("id", ""):
                telegram_task_edits.pop(key, None)

            answer("已刪除排程任務")
            if message_id is not None:
                telegram_bridge.edit_message_text(
                    chat_id,
                    int(message_id),
                    "\n".join(
                        [
                            "Scheduled task deleted.",
                            f"id: {task.get('id', '')}",
                            f"name: {task.get('task_name', '')}",
                        ]
                    ),
                )
            return

        if data.startswith("task:edit:"):
            identifier = data.split(":", 2)[2].strip()
            task = resolve_active_task(identifier)
            if not task:
                answer("Task not found or already deleted.", show_alert=True)
                return

            answer("選擇要編輯的欄位")
            telegram_bridge.send_text(
                chat_id,
                "\n".join(
                    [
                        "Choose what to edit for this scheduled task.",
                        "",
                        _format_task_summary(task),
                    ]
                ),
                reply_markup=_task_edit_reply_markup(str(task.get("id", "")).strip()),
            )
            return

        if data.startswith("task:field:"):
            parts = data.split(":", 3)
            if len(parts) != 4:
                answer("Invalid edit action.", show_alert=True)
                return

            field = parts[2].strip()
            identifier = parts[3].strip()
            task = resolve_active_task(identifier)
            if not task:
                answer("Task not found or already deleted.", show_alert=True)
                return

            telegram_task_edits[key] = {
                "task_id": str(task.get("id", "")).strip(),
                "field": field,
            }
            answer("請直接輸入新值")
            telegram_bridge.send_text(chat_id, _task_edit_instruction(task, field))
            return

        if data.startswith("task:cancel:"):
            telegram_task_edits.pop(key, None)
            answer("已取消編輯")
            if message_id is not None:
                telegram_bridge.edit_message_text(
                    chat_id,
                    int(message_id),
                    "Task edit cancelled.",
                )
            return

        answer()

    def on_scheduled_event(event: dict):
        live_chat_ids = telegram_bridge.delivery_chat_ids() if telegram_bridge else []
        with display.capture_events(
            categories={"tool"},
            on_event=build_tool_streamer(chat_ids=live_chat_ids),
        ):
            reply = ""

            if event.get("status") == "error" and not event.get("dispatch_prompt"):
                error_text = str(event.get("error", "")).strip() or "Unknown scheduler error"
                display.system_block(f"Scheduled task error: {error_text}")
                broadcast_to_telegram(
                    f"Scheduled task error: {error_text}",
                    label="scheduled-task",
                )
                display.prompt()
                return

            text = format_scheduled_trigger(event)
            display.system_block(text)

            try:
                reply = agent.run(event["dispatch_prompt"])
                status = "error" if reply.strip().startswith("[ERROR]") else "ok"
                record_task_result(
                    event.get("task_name", ""),
                    status=status,
                    response_text="" if status == "error" else reply,
                    error_text=reply if status == "error" else "",
                    trigger=event.get("trigger", ""),
                    scheduled_for=event.get("scheduled_for", ""),
                )
                display.agent(reply)
            except Exception as exc:
                error_text = str(exc)
                reply = f"[ERROR] {error_text}"
                record_task_result(
                    event.get("task_name", ""),
                    status="error",
                    response_text="",
                    error_text=error_text,
                    trigger=event.get("trigger", ""),
                    scheduled_for=event.get("scheduled_for", ""),
                )
                display.system_block(f"Scheduled task error: {error_text}")

        reply_markup = None
        task_id = str(event.get("task_id", "")).strip()
        if task_id:
            reply_markup = _task_action_reply_markup(task_id)

        final_parts = [format_scheduled_trigger(event)]
        if str(reply or "").strip():
            final_parts.append(str(reply).strip())
        broadcast_to_telegram(
            "\n\n".join(final_parts),
            label="scheduled-task",
            reply_markup=reply_markup,
        )

        display.prompt()

    scheduler = ChatScheduler(on_event=on_scheduled_event)
    scheduler.start()

    def on_telegram_message(event: dict) -> str:
        chat_id = int(event["chat_id"])
        user_id = event.get("user_id")
        text = str(event.get("text", "")).strip()
        caption = str(event.get("caption", "")).strip()
        images = [item for item in (event.get("images") or []) if isinstance(item, dict)]
        session_agent = get_telegram_agent(chat_id)
        rolling_reply = None
        response_stream_callback = None
        display.system(
            f"Telegram message chat={chat_id} user={event.get('username') or event.get('display_name') or '-'} images={len(images)}",
            notify=False,
        )

        pending_edit = telegram_task_edits.get(telegram_edit_key(chat_id, user_id))
        if pending_edit:
            if images:
                return "A task edit is pending. Send the new value as plain text only, or send /cancel."
            if text.lower() in {"/cancel", "cancel"}:
                telegram_task_edits.pop(telegram_edit_key(chat_id, user_id), None)
                return "Cancelled scheduled-task edit."

            if text.startswith("/"):
                return "A task edit is pending. Send the new value directly, or send /cancel."

            task = resolve_active_task(pending_edit.get("task_id", ""))
            if not task:
                telegram_task_edits.pop(telegram_edit_key(chat_id, user_id), None)
                return "Task not found. It may have been deleted already."

            try:
                updated_task = _apply_task_edit(
                    task,
                    field=str(pending_edit.get("field", "")).strip(),
                    raw_value=text,
                    actor=str(event.get("username") or event.get("display_name") or chat_id).strip(),
                )
            except Exception as exc:
                return (
                    f"Task edit failed: {exc}\n"
                    "Send the new value again, or send /cancel to stop editing."
                )

            telegram_task_edits.pop(telegram_edit_key(chat_id, user_id), None)
            return "Updated scheduled task.\n" + _format_task_summary(updated_task)

        if telegram_bridge and not text.startswith("/"):
            rolling_reply = TelegramRollingReply(telegram_bridge, chat_id=chat_id)

            def response_stream_callback(stream_text: str, *, final: bool = False):
                if final:
                    return
                rolling_reply.push_preview(stream_text)

        with display.capture_events(
            categories={"tool"},
            on_event=build_tool_streamer(chat_ids=[chat_id]),
        ):
            if images:
                history_user_input = _build_telegram_image_prompt(event)
                try:
                    user_input = _build_telegram_image_user_input(event)
                except Exception as exc:
                    display.system(
                        f"Telegram image prompt fallback chat={chat_id}: {exc}",
                        notify=False,
                    )
                    user_input = history_user_input
                reply = session_agent.run(
                    user_input,
                    history_user_input=history_user_input,
                    response_stream_callback=response_stream_callback,
                )
            elif text.startswith("/"):
                reply = handle_remote_command(text, session_agent)
            else:
                reply = session_agent.run(
                    text,
                    response_stream_callback=response_stream_callback,
                )

        if images:
            reply_parts = [_format_saved_telegram_images(images), str(reply or "").strip()]
            if caption and not str(reply or "").strip():
                reply_parts.append(f"Caption: {caption}")
            final_reply = "\n\n".join(part for part in reply_parts if part)
            if rolling_reply and rolling_reply.finalize(final_reply):
                return ""
            return final_reply

        if rolling_reply and rolling_reply.finalize(reply):
            return ""

        return reply

    if config.telegram_enabled and config.telegram_bot_token:
        telegram_bridge = TelegramBridge(
            bot_token=config.telegram_bot_token,
            handle_message=on_telegram_message,
            handle_callback_query=on_telegram_callback,
            display=display,
            state_path=config.telegram_state_path,
            image_storage_path=config.telegram_image_storage_path,
            poll_timeout_seconds=config.telegram_poll_timeout_seconds,
            retry_delay_seconds=config.telegram_retry_delay_seconds,
            allowed_chat_ids=config.telegram_allowed_chat_ids,
            allowed_usernames=config.telegram_allowed_usernames,
            skip_pending_updates_on_start=config.telegram_skip_pending_updates_on_start,
        )
        telegram_bridge.start()

    try:
        while True:
            display.prompt()
            user_input = input().strip()
            if user_input.lower() in {"exit", "quit"}:
                break

            command_result = handle_cli_command(user_input, config=config, agent=agent)
            if command_result["handled"]:
                message = command_result["message"].strip()
                if message:
                    display.command(message)
                if command_result["exit_requested"]:
                    break
                continue

            try:
                reply = agent.run(user_input)
                display.agent(reply)
            except Exception as e:
                display.error(str(e))
    finally:
        if telegram_bridge:
            telegram_bridge.stop()
        scheduler.stop()


if __name__ == "__main__":
    main()
