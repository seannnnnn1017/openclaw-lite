from __future__ import annotations

import shlex
import shutil
from collections.abc import Callable
from pathlib import Path

try:
    from scheduling.runtime import delete_task, list_tasks
except ModuleNotFoundError:
    from agent.scheduling.runtime import delete_task, list_tasks

from .tasks import format_task_list, resolve_task_identifier


HELP_TEXT = """Available commands:
/help                      Show this help message
/exit | /quit              Exit the agent
/model [name]              Show the current model or switch it for this session
  reset                    Reset the active model to the config default
  save <name>              Save a new default model to config and use it immediately
/stream [on|off]           Show LLM streaming status or toggle it for this session
  reset                    Reset LLM streaming to the config default
  save <on|off>            Save a new default LLM streaming setting to config
/clear <history|cache>     Clear in-memory history or cache directories
  history                  Clear in-memory chat history for this session
  cache                    Delete .codex-temp cache directories only
/task                      Show task subcommands
  list                     List scheduled tasks
  remove <id|name>         Remove one scheduled task by ID or task name
  remove -all              Remove all scheduled tasks
/think [on|off]            Show current [THINK] status or toggle it
/compact [on|off]          Show or toggle history compression (L1/L2/L3 pipeline)
/reload                    Reload config, prompts, skills, and runtime clients
/status                    Show the current model, history size, estimated prompt/history tokens, display categories, and endpoint URLs"""

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

COMPACT_HELP_TEXT = """Compact commands:
/compact [on|off]          Show current history compression status or toggle it
  on                       Enable L1/L2/L3 history compression
  off                      Disable history compression (useful for debugging)"""

STREAM_HELP_TEXT = """Stream commands:
/stream [on|off]           Show the current LLM streaming setting or toggle it
  on                       Enable LLM streaming for this session
  off                      Disable LLM streaming for this session
  reset                    Reset LLM streaming to the config default
  save <on|off>            Save a new default streaming setting to config"""


def _response(message: str = "", *, handled: bool = True, exit_requested: bool = False) -> dict:
    return {
        "handled": handled,
        "exit_requested": exit_requested,
        "message": message,
    }


def describe_model(config) -> str:
    if config.has_runtime_model_override():
        return f"{config.model} (session override, config default: {config.default_model})"
    return f"{config.model} (config default)"


def describe_stream(config) -> str:
    current = "on" if getattr(config, "stream", False) else "off"
    default = "on" if getattr(config, "default_stream", False) else "off"
    if config.has_runtime_stream_override():
        return f"{current} (session override, config default: {default})"
    return f"{current} (config default)"


def parse_stream_value(raw_value: str):
    value = str(raw_value or "").strip().casefold()
    if value in {"on", "true", "1", "yes"}:
        return True
    if value in {"off", "false", "0", "no"}:
        return False
    return None


def format_status(config, agent) -> str:
    display_states = [
        f"think={'on' if agent.display_category_enabled('think') else 'off'}",
        f"tool={'on' if agent.display_category_enabled('tool') else 'off'}",
        f"memory={'on' if agent.display_category_enabled('memory') else 'off'}",
        f"system={'on' if agent.display_category_enabled('system') else 'off'}",
        f"compact={'on' if agent.compression_enabled() else 'off'}",
    ]
    token_summary = agent.token_estimate_summary()
    memory_summary = agent.long_term_memory_summary()
    if memory_summary.get("enabled"):
        memory_line = (
            "Long-term memory: enabled "
            f"({memory_summary.get('count', 0)} stored, "
            f"{memory_summary.get('always_include', 0)} pinned)"
        )
    else:
        memory_line = "Long-term memory: disabled"
    return "\n".join(
        [
            f"Model: {describe_model(config)}",
            (
                "LM Studio context window: "
                + (str(config.context_window) if config.context_window > 0 else "disabled")
                + (
                    "; auto-manage=on"
                    if getattr(config, "ensure_model_loaded", False)
                    else "; auto-manage=off"
                )
            ),
            f"History messages: {agent.history_size()}",
            memory_line,
            f"System prompt tokens ({token_summary['method']}): {token_summary['system_prompt_tokens']}",
            f"History tokens ({token_summary['method']}): {token_summary['history_tokens']}",
            f"Base prompt total ({token_summary['method']}, no current user turn): {token_summary['base_total_tokens']}",
            f"LLM streaming: {describe_stream(config)}",
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


def handle_cli_command(
    command_line: str,
    *,
    config,
    agent,
    project_root: Path,
    on_reload: Callable[[], Path],
) -> dict:
    stripped = command_line.strip()
    if not stripped.startswith("/"):
        return _response(handled=False)

    try:
        parts = shlex.split(stripped)
    except ValueError as exc:
        return _response(f"Command parse error: {exc}")

    if not parts:
        return _response()

    command = parts[0].lower()
    args = parts[1:]

    if command in {"/help", "/?", "/commands"}:
        return _response(HELP_TEXT)

    if command in {"/exit", "/quit"}:
        return _response("Exiting agent.", exit_requested=True)

    if command == "/clear-history":
        return _response('Use "/clear history" instead.')

    if command == "/clear-cache":
        return _response('Use "/clear cache" instead.')

    if command == "/clear":
        if not args:
            return _response(CLEAR_HELP_TEXT)

        subcommand = args[0].lower()
        if subcommand == "history" and len(args) == 1:
            cleared = agent.clear_history()
            return _response(f"Cleared in-memory chat history ({cleared} message(s)).")

        if subcommand == "cache" and len(args) == 1:
            cleared = clear_project_cache(project_root)
            cache_lines = [
                f"{entry['path']}: {'deleted' if entry['removed'] else 'already empty'}"
                for entry in cleared["cache_dirs"]
            ]
            return _response("Cleared cache directories.\n" + "\n".join(cache_lines))

        return _response(f'Unknown /clear subcommand: {" ".join(args)}\n\n{CLEAR_HELP_TEXT}')

    if command == "/task":
        if not args:
            return _response(TASK_HELP_TEXT)

        subcommand = args[0].lower()
        if subcommand == "list" and len(args) == 1:
            tasks = list_tasks(include_deleted=False)
            return _response(format_task_list(tasks))

        if subcommand in {"remove", "delete"}:
            if len(args) == 2 and args[1].lower() == "-all":
                tasks = list_tasks(include_deleted=False)
                if not tasks:
                    return _response("No scheduled tasks to remove.")

                removed_names = []
                for task in tasks:
                    delete_task(
                        task.get("task_name", ""),
                        reason="Removed via /task remove -all",
                    )
                    removed_names.append(task.get("task_name", ""))

                return _response(
                    f"Removed {len(removed_names)} scheduled task(s).\n"
                    + "\n".join(f"- {name}" for name in removed_names)
                )

            identifier = " ".join(args[1:]).strip()
            if not identifier:
                return _response(f'Usage: /task remove <id|name|-all>\n\n{TASK_HELP_TEXT}')

            tasks = list_tasks(include_deleted=False)
            task = resolve_task_identifier(tasks, identifier)
            if not task:
                return _response(f"Task not found: {identifier}")

            delete_task(
                task.get("task_name", ""),
                reason=f"Removed via /task remove ({identifier})",
            )
            return _response(
                "Removed scheduled task.\n"
                f"id: {task.get('id', '')}\n"
                f"name: {task.get('task_name', '')}"
            )

        return _response(f'Unknown /task subcommand: {" ".join(args)}\n\n{TASK_HELP_TEXT}')

    if command == "/think":
        if not args:
            return _response(
                f"Current [THINK] output: {'on' if agent.think_enabled() else 'off'}\n\n"
                f"{THINK_HELP_TEXT}"
            )

        subcommand = args[0].lower()
        if subcommand == "on" and len(args) == 1:
            agent.set_show_think(True)
            return _response("Enabled [THINK] output for this session.")

        if subcommand == "off" and len(args) == 1:
            agent.set_show_think(False)
            return _response("Disabled [THINK] output for this session.")

        return _response(f'Unknown /think subcommand: {" ".join(args)}\n\n{THINK_HELP_TEXT}')

    if command == "/compact":
        if not args:
            status = "on" if agent.compression_enabled() else "off"
            return _response(
                f"History compression: {status}\n\n{COMPACT_HELP_TEXT}"
            )

        subcommand = args[0].lower()
        if subcommand == "on" and len(args) == 1:
            agent.set_compression_enabled(True)
            return _response("History compression enabled (L1/L2/L3 pipeline active).")

        if subcommand == "off" and len(args) == 1:
            agent.set_compression_enabled(False)
            return _response("History compression disabled.")

        return _response(f'Unknown /compact subcommand: {" ".join(args)}\n\n{COMPACT_HELP_TEXT}')

    if command == "/status":
        if args:
            return _response(f"Unexpected arguments for {command}")
        return _response(format_status(config, agent))

    if command == "/reload":
        if args:
            return _response(f"Unexpected arguments for {command}")
        architecture_path = on_reload()
        return _response(
            "Reloaded config, prompts, skills, and runtime clients.\n"
            f"Model: {describe_model(config)}\n"
            f"System doc: {architecture_path}"
        )

    if command == "/model":
        if not args:
            return _response(f"Current model: {describe_model(config)}")

        subcommand = args[0].lower()
        if subcommand in {"reset", "default"} and len(args) == 1:
            config.reset_runtime_model()
            return _response(f"Model reset to config default: {config.model}")

        if subcommand == "save":
            model_name = " ".join(args[1:]).strip()
            if not model_name:
                return _response("Usage: /model save <name>")
            config.save_model(model_name)
            agent.refresh_runtime_clients()
            return _response(f"Saved and activated model: {describe_model(config)}")

        model_name = " ".join(args).strip()
        if not model_name:
            return _response("Usage: /model <name>")
        config.set_runtime_model(model_name)
        return _response(f"Active model changed for this session: {describe_model(config)}")

    if command == "/stream":
        if not args:
            return _response(f"Current LLM streaming: {describe_stream(config)}")

        subcommand = args[0].lower()
        if subcommand in {"reset", "default"} and len(args) == 1:
            config.reset_runtime_stream()
            return _response(f"LLM streaming reset to config default: {describe_stream(config)}")

        if subcommand == "save":
            if len(args) != 2:
                return _response(f"Usage: /stream save <on|off>\n\n{STREAM_HELP_TEXT}")
            enabled = parse_stream_value(args[1])
            if enabled is None:
                return _response(f"Usage: /stream save <on|off>\n\n{STREAM_HELP_TEXT}")
            config.save_stream(enabled)
            agent.refresh_runtime_clients()
            return _response(f"Saved and activated LLM streaming: {describe_stream(config)}")

        if len(args) != 1:
            return _response(STREAM_HELP_TEXT)
        enabled = parse_stream_value(args[0])
        if enabled is None:
            return _response(STREAM_HELP_TEXT)
        config.set_runtime_stream(enabled)
        return _response(f"Active LLM streaming changed for this session: {describe_stream(config)}")

    return _response(f"Unknown command: {command}\n\n{HELP_TEXT}")
