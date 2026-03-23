import shlex
import shutil
from pathlib import Path

from config_loader import Config
from lmstudio_client import LMStudioClient
from agent import SimpleAgent
from chat_scheduler import ChatScheduler
from schedule_runtime import clear_schedule_cache, record_task_result
from system_doc_generator import generate_system_architecture


HELP_TEXT = """Available commands:
/help                Show this help message
/exit                Exit the agent
/quit                Exit the agent
/model               Show the current model
/model <name>        Switch the active model for this session only
/model reset         Reset the active model to the config default
/model save <name>   Save a new default model to config and use it immediately
/clear               Show clear subcommands
/clear history       Clear in-memory chat history for this session
/clear cache         Delete .codex-temp and reset schedule-task temporary data (wipes scheduled tasks)
/think               Show think subcommands and current status
/think on            Show [THINK n] output
/think off           Hide [THINK n] output
/reload              Reload config, prompts, skills, and runtime clients
/status              Show the current model, history size, and endpoint URLs"""

CLEAR_HELP_TEXT = """Clear commands:
/clear history       Clear in-memory chat history for this session
/clear cache         Delete .codex-temp and reset schedule-task temporary data (wipes scheduled tasks)"""

THINK_HELP_TEXT = """Think commands:
/think               Show the current [THINK] setting
/think on            Show [THINK n] output
/think off           Hide [THINK n] output"""


def format_scheduled_trigger(event: dict) -> str:
    name = event.get("short_name") or event.get("task_name") or "scheduled-task"
    trigger = event.get("trigger", "scheduled")
    parts = [f"[Scheduled Task Triggered] {name} trigger={trigger}"]
    scheduled_for = str(event.get("scheduled_for", "")).strip()
    if scheduled_for:
        parts.append(f"scheduled_for={scheduled_for}")
    next_run_at = str(event.get("next_run_at", "")).strip()
    if next_run_at:
        parts.append(f"next_run_at={next_run_at}")
    return "\n".join(parts)


def describe_model(config: Config) -> str:
    if config.has_runtime_model_override():
        return f"{config.model} (session override, config default: {config.default_model})"
    return f"{config.model} (config default)"


def format_status(config: Config, agent: SimpleAgent) -> str:
    return "\n".join(
        [
            f"Model: {describe_model(config)}",
            f"History messages: {agent.history_size()}",
            f"Show [THINK]: {'on' if agent.think_enabled() else 'off'}",
            f"Skill server: {config.skill_server_url}",
            f"LLM base URL: {config.base_url}",
        ]
    )


def clear_project_cache(project_root: Path, *, schedule_registry_path: Path | None = None) -> dict:
    codex_temp_dir = project_root / ".codex-temp"
    codex_temp_removed = codex_temp_dir.exists()
    if codex_temp_removed:
        shutil.rmtree(codex_temp_dir)

    resolved_schedule_registry = schedule_registry_path or (
        project_root
        / "agent"
        / "SKILLs"
        / "schedule_task"
        / "scripts"
        / "temporary_data"
        / "task_registry.json"
    )
    schedule_result = clear_schedule_cache(
        registry_path=resolved_schedule_registry,
    )
    return {
        "codex_temp_dir": str(codex_temp_dir),
        "codex_temp_removed": codex_temp_removed,
        "schedule": schedule_result,
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
            schedule_info = cleared["schedule"]
            codex_temp_status = "deleted" if cleared["codex_temp_removed"] else "already empty"
            return {
                "handled": True,
                "exit_requested": False,
                "message": (
                    "Cleared disk cache.\n"
                    f".codex-temp: {codex_temp_status} ({cleared['codex_temp_dir']})\n"
                    f"schedule temp reset: {schedule_info['registry_path']}\n"
                    f"scheduled task records removed: {schedule_info['tasks_cleared']}"
                ),
            }

        return {
            "handled": True,
            "exit_requested": False,
            "message": f'Unknown /clear subcommand: {" ".join(args)}\n\n{CLEAR_HELP_TEXT}',
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
    architecture_path = generate_system_architecture(config)
    print(f"[SYSTEM DOC GENERATED] {architecture_path}")
    client = LMStudioClient(base_url=config.base_url, api_key=config.api_key)
    agent = SimpleAgent(config=config, client=client)

    def on_scheduled_event(event: dict):
        if event.get("status") == "error" and not event.get("dispatch_prompt"):
            error_text = str(event.get("error", "")).strip() or "Unknown scheduler error"
            print(f"\nAgent: [Scheduled Task Error] {error_text}\n")
            print("You: ", end="", flush=True)
            return

        text = format_scheduled_trigger(event)
        print(f"\nAgent: {text}\n")

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
            print(f"\nAgent: {reply}\n")
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
            print(f"\nAgent: [Scheduled Task Error] {error_text}\n")

        print("You: ", end="", flush=True)

    scheduler = ChatScheduler(on_event=on_scheduled_event)
    scheduler.start()

    try:
        while True:
            user_input = input("You: ").strip()
            if user_input.lower() in {"exit", "quit"}:
                break

            command_result = handle_cli_command(user_input, config=config, agent=agent)
            if command_result["handled"]:
                message = command_result["message"].strip()
                if message:
                    print(f"\n[COMMAND] {message}\n")
                if command_result["exit_requested"]:
                    break
                continue

            try:
                reply = agent.run(user_input)
                print(f"\nAgent: {reply}\n")
            except Exception as e:
                print(f"\n[ERROR] {e}\n")
    finally:
        scheduler.stop()


if __name__ == "__main__":
    main()
