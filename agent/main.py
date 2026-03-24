import shlex
import shutil
from datetime import datetime
from pathlib import Path

from config_loader import Config
from lmstudio_client import LMStudioClient
from agent import SimpleAgent
from chat_scheduler import ChatScheduler
from schedule_runtime import delete_task, list_tasks, record_task_result
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


def format_scheduled_trigger(event: dict) -> str:
    name = event.get("short_name") or event.get("task_name") or "scheduled-task"
    trigger = event.get("trigger", "scheduled")
    parts = [f"Scheduled task triggered: {name}", f"trigger={trigger}"]
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

    def broadcast_to_telegram(text: str, *, label: str):
        cleaned = str(text or "").strip()
        if not cleaned or not telegram_bridge:
            return

        result = telegram_bridge.broadcast_text(cleaned)
        errors = result.get("errors", [])
        if errors:
            display.system_block(_format_telegram_delivery_errors(label, errors), notify=False)

    def on_scheduled_event(event: dict):
        with display.capture_events(categories={"system", "tool"}) as trace_events:
            reply = ""

            if event.get("status") == "error" and not event.get("dispatch_prompt"):
                error_text = str(event.get("error", "")).strip() or "Unknown scheduler error"
                display.system_block(f"Scheduled task error: {error_text}")
                broadcast_to_telegram(
                    format_telegram_trace_reply("", trace_events),
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
                record_task_result(
                    event.get("task_name", ""),
                    status="error",
                    response_text="",
                    error_text=error_text,
                    trigger=event.get("trigger", ""),
                    scheduled_for=event.get("scheduled_for", ""),
                )
                display.system_block(f"Scheduled task error: {error_text}")

        broadcast_to_telegram(
            format_telegram_trace_reply(reply, trace_events),
            label="scheduled-task",
        )

        display.prompt()

    scheduler = ChatScheduler(on_event=on_scheduled_event)
    scheduler.start()

    def on_telegram_message(event: dict) -> str:
        chat_id = int(event["chat_id"])
        text = str(event.get("text", "")).strip()
        session_agent = get_telegram_agent(chat_id)
        display.system(
            f"Telegram message chat={chat_id} user={event.get('username') or event.get('display_name') or '-'}",
            notify=False,
        )

        with display.capture_events(categories={"system", "tool"}) as trace_events:
            if text.startswith("/"):
                reply = handle_remote_command(text, session_agent)
            else:
                reply = session_agent.run(text)

        return format_telegram_trace_reply(reply, trace_events)

    if config.telegram_enabled and config.telegram_bot_token:
        telegram_bridge = TelegramBridge(
            bot_token=config.telegram_bot_token,
            handle_message=on_telegram_message,
            display=display,
            state_path=config.telegram_state_path,
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
