import json
import re
from datetime import datetime
from pathlib import Path


CLI_COMMANDS = [
    "/help: show command help",
    "/exit | /quit: stop the terminal agent process",
    "/model [name]: show the active model or switch it for the current session",
    "/model reset: reset the session model override back to config default",
    "/model save <name>: persist a new default model to config and use it immediately",
    "/clear history: clear in-memory chat history for the current session",
    "/clear cache: delete only `/.codex-temp` and `/agent/.codex-temp`",
    "/task list: list scheduled tasks directly from the schedule registry",
    "/task remove <id|name>: remove one scheduled task without using the LLM",
    "/task remove -all: remove all scheduled tasks without using the LLM",
    "/think [on|off]: show or toggle `[THINK]` output for the current session",
    "/reload: reload config, prompts, skills, runtime clients, and regenerate this file",
    "/status: show model, history size, display categories, and endpoint URLs",
]

CORE_COMPONENTS = [
    "agent/main.py: primary terminal entrypoint; starts the terminal loop, scheduler, Telegram bridge, and regeneration of this file",
    "agent/agent.py: `SimpleAgent` implementation; builds prompts, runs the chat loop, parses tool JSON, executes multi-step tool use, and stores per-session history",
    "agent/config_loader.py: loads `config.json`, prompt files, and enabled skills; also supports live reload and runtime model override",
    "agent/lmstudio_client.py: OpenAI-compatible chat client used by each agent session",
    "agent/skill_client.py: HTTP client that sends tool execution JSON to the skill server",
    "agent/skill_server.py: FastAPI process that receives skill execution requests and dispatches them to Python tool functions",
    "agent/skill_runtime.py: skill loader and registry used by the skill server",
    "agent/schedule_runtime.py: schedule registry, task normalization, next-run calculation, due-task claiming, and result recording",
    "agent/chat_scheduler.py: background polling thread that claims due scheduled tasks every second",
    "agent/telegram_bridge.py: Telegram Bot API long-poll bridge, allowlist enforcement, chat-state tracking, and message delivery",
    "agent/terminal_display.py: shared formatter for `[THINK]`, `[TOOL]`, `[SYSTEM]`, `Agent:`, and `[COMMAND]`; also captures tool/system events for Telegram replies",
    "agent/schemas.py: shared pydantic message and request schemas",
    "agent/system_doc_generator.py: produces `agent/data/system/system_architecture.md` from the current config and enabled skill set",
]

EDIT_MAP = [
    "Change slash commands or interactive routing in `agent/main.py`.",
    "Change the main reasoning loop, tool-step limits, or history behavior in `agent/agent.py`.",
    "Change config loading, prompt loading, or runtime model persistence in `agent/config_loader.py`.",
    "Change Telegram polling, allowlist logic, known-chat persistence, or outbound delivery in `agent/telegram_bridge.py`.",
    "Change scheduler timing, task claiming, or schedule registry logic in `agent/schedule_runtime.py` and `agent/chat_scheduler.py`.",
    "Change display formatting or Telegram trace capture in `agent/terminal_display.py`.",
    "Change tool loading or skill server behavior in `agent/skill_runtime.py` and `agent/skill_server.py`.",
    "Change cross-skill rules in `agent/SKILLs/skill_rule.md` and per-skill behavior in each skill's `SKILL.md`.",
]


def _relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _bullet_section(title: str, lines: list[str]) -> str:
    body = "\n".join(f"- {line}" for line in lines) if lines else "- None"
    return f"## {title}\n{body}"


def _normalize_whitespace(text: str) -> str:
    return " ".join(str(text or "").split())


def _extract_supported_actions(skill_content: str) -> list[str]:
    lines = skill_content.splitlines()
    actions = []
    in_actions = False

    for raw_line in lines:
        line = raw_line.strip()
        if not in_actions:
            if line.lower() == "supported actions:":
                in_actions = True
            continue

        if not line:
            if actions:
                break
            continue

        if not line.startswith("- "):
            if actions:
                break
            continue

        match = re.search(r"`([^`]+)`", line)
        if match:
            actions.append(match.group(1))

    return actions


def _tool_module_file(tool_module: str, project_root: Path) -> Path | None:
    cleaned = str(tool_module or "").strip()
    if not cleaned:
        return None
    candidate = project_root / (cleaned.replace(".", "/") + ".py")
    return candidate if candidate.exists() else None


def _skill_specific_notes(skill_name: str) -> list[str]:
    if skill_name == "file-control":
        return [
            "Mutating actions create backups before changing files.",
            "Backup storage is protected from ordinary skill edits and returns permission denied if targeted.",
            "Backup cleanup is not part of normal file-control operations.",
        ]
    if skill_name == "notion-basic":
        return [
            "Uses the Notion REST API and reads credentials from env vars or `agent/data/system/secrets.local.json`.",
            "Page content operations use Notion's markdown endpoints for full-page replace, append, and targeted search-and-replace.",
            "Delete is implemented as moving a page to trash; the Notion API does not permanently delete pages.",
        ]
    if skill_name == "schedule-task":
        return [
            "The scheduler stores timing plus `task_prompt`; it does not run raw shell commands directly.",
            "Due tasks are dispatched back into the main terminal `SimpleAgent` instance, not into a Telegram per-chat session.",
            "When Telegram delivery targets are known, scheduled task output is broadcast to Telegram as well as printed in the terminal.",
        ]
    if skill_name == "time-query":
        return [
            "Supports local time, named timezones, common city aliases, and explicit UTC offsets.",
            "Use `now` for current-time questions and `convert` for explicit datetime conversion.",
        ]
    return []


def _skill_state_paths(skill_name: str, project_root: Path) -> list[str]:
    if skill_name == "file-control":
        return [
            f"`{_relative_path(project_root / 'agent/SKILLs/file_control/scripts/temporary_data/file_ID.json', project_root)}`: backup index",
            f"`{_relative_path(project_root / 'agent/SKILLs/file_control/scripts/temporary_data/backups', project_root)}/`: backup payloads",
        ]
    if skill_name == "notion-basic":
        return [
            f"`{_relative_path(project_root / 'agent/data/system/secrets.example.json', project_root)}`: example shared secret configuration",
            f"`{_relative_path(project_root / 'agent/data/system/secrets.local.json', project_root)}`: ignored local shared secrets for LLM, Telegram, and Notion",
        ]
    if skill_name == "schedule-task":
        return [
            f"`{_relative_path(project_root / 'agent/SKILLs/schedule_task/scripts/temporary_data/task_registry.json', project_root)}`: schedule registry",
        ]
    return []


def _skill_block(skill: dict, project_root: Path) -> str:
    skill_name = skill.get("name", "").strip() or "unknown-skill"
    skill_dir = Path(skill["path"]).resolve()
    skill_rel = _relative_path(skill_dir, project_root)
    tool = skill.get("tool", {})
    tool_module = tool.get("module", "")
    tool_function = tool.get("function", "run")
    tool_file = _tool_module_file(tool_module, project_root)
    tool_file_rel = _relative_path(tool_file, project_root) if tool_file else "(tool file not found)"
    metadata = skill.get("metadata", {})
    description = _normalize_whitespace(metadata.get("description", "")) or "No description provided."
    actions = _extract_supported_actions(skill.get("content", ""))
    examples_path = skill_dir / "examples.md"
    skill_md_path = skill_dir / "SKILL.md"
    skill_config_path = skill_dir / "skills_config.json"

    lines = [
        f"### {skill_name}",
        f"- Description: {description}",
        f"- Directory: `{skill_rel}`",
        f"- Tool entrypoint: `{tool_module}:{tool_function}`",
        f"- Tool source file: `{tool_file_rel}`",
        f"- Supported actions: {', '.join(f'`{action}`' for action in actions) if actions else 'None detected'}",
        f"- Key files: `{_relative_path(skill_md_path, project_root)}`, `{_relative_path(skill_config_path, project_root)}`"
        + (f", `{_relative_path(examples_path, project_root)}`" if examples_path.exists() else ""),
    ]

    state_paths = _skill_state_paths(skill_name, project_root)
    if state_paths:
        lines.append(f"- State and storage: {'; '.join(state_paths)}")

    notes = _skill_specific_notes(skill_name)
    if notes:
        lines.append(f"- Runtime notes: {' '.join(notes)}")

    return "\n".join(lines)


def generate_system_architecture(config) -> Path:
    agent_root = config.base_dir
    project_root = agent_root.parent
    system_dir = agent_root / "data" / "system"
    system_dir.mkdir(parents=True, exist_ok=True)
    output_path = system_dir / "system_architecture.md"

    raw_config = json.loads(config.path.read_text(encoding="utf-8"))
    prompt_config = raw_config.get("prompt_paths", {})

    identity_path = (agent_root / prompt_config.get("identity", "prompts/identity.md")).resolve()
    system_rules_path = (agent_root / prompt_config.get("system_rules", "prompts/system_rules.md")).resolve()
    boundaries_path = (agent_root / prompt_config.get("boundaries", "prompts/boundaries.md")).resolve()
    identity_original_path = agent_root / "prompts" / "identity.original.md"
    skill_rule_path = agent_root / "SKILLs" / "skill_rule.md"
    readme_path = project_root / "README.md"

    telegram_allowlist_parts = [
        f"allowed usernames={len(config.telegram_allowed_usernames)}",
        f"allowed chat IDs={len(config.telegram_allowed_chat_ids)}",
    ]
    telegram_state_rel = _relative_path(Path(config.telegram_state_path), project_root)
    enabled_skill_names = [skill.get("name", "") for skill in config.skills]

    snapshot_lines = [
        f"Generated at: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Repository root marker: `{project_root.name}/`",
        "Project root path in this document is expressed with repository-relative paths.",
        "Agent root: `agent/`",
        f"Active model: `{config.model}`",
        f"Config default model: `{config.default_model}`",
        f"LLM base URL: `{config.base_url}`",
        f"Skill server URL: `{config.skill_server_url}`",
        f"Temperature: `{config.temperature}`",
        f"Max tokens: `{config.max_tokens}`",
        f"Telegram bridge enabled: {'yes' if config.telegram_enabled else 'no'}",
        f"Telegram bot token configured: {'yes (redacted)' if bool(config.telegram_bot_token) else 'no'}",
        f"Telegram polling: timeout={config.telegram_poll_timeout_seconds}s, retry_delay={config.telegram_retry_delay_seconds}s, skip_pending_on_start={'yes' if config.telegram_skip_pending_updates_on_start else 'no'}",
        f"Telegram allowlist summary: {', '.join(telegram_allowlist_parts)}",
        f"Enabled skills ({len(enabled_skill_names)}): {', '.join(f'`{name}`' for name in enabled_skill_names)}",
        f"This file is regenerated on startup and `/reload`: `{_relative_path(output_path, project_root)}`",
    ]

    session_model_lines = [
        "Terminal session: `main.py` creates one shared `SimpleAgent` instance named `agent` for terminal input and scheduled-task execution.",
        "Telegram sessions: `main.py` keeps `telegram_agents[chat_id]`, creating one `SimpleAgent` per Telegram chat ID.",
        "Session history is in-memory only. Terminal history and each Telegram chat history are separate.",
        "Per-session history is capped to the most recent 10 messages in `SimpleAgent._append_history`.",
        "The tool loop allows up to 6 tool steps per turn (`SimpleAgent.max_tool_steps = 6`).",
        "Scheduled tasks run through the main terminal `agent` instance, then optionally broadcast results to Telegram delivery targets.",
    ]

    prompt_lines = [
        "Prompt composition order: `identity -> system_rules -> boundaries -> enabled SKILL.md bodies`.",
        f"Active identity prompt: `{_relative_path(identity_path, project_root)}`",
        f"Active system rules prompt: `{_relative_path(system_rules_path, project_root)}`",
        f"Active boundaries prompt: `{_relative_path(boundaries_path, project_root)}`",
        f"Identity template and editing guidance: `{_relative_path(identity_original_path, project_root)}`" if identity_original_path.exists() else "Identity template and editing guidance: not present",
        f"Cross-skill rules and project conventions: `{_relative_path(skill_rule_path, project_root)}`" if skill_rule_path.exists() else "Cross-skill rules file: not present",
    ]

    state_lines = [
        f"`{_relative_path(config.path, project_root)}`: persisted non-secret configuration for model selection, endpoints, Telegram settings, and prompt paths",
        f"`{_relative_path(agent_root / 'data/system/secrets.example.json', project_root)}`: example shared secret layout",
        f"`{_relative_path(agent_root / 'data/system/secrets.local.json', project_root)}`: ignored local shared secrets for LLM, Telegram, and Notion",
        f"`{telegram_state_rel}`: Telegram bridge state (`offset` plus remembered delivery chats)",
        f"`{_relative_path(agent_root / 'SKILLs/schedule_task/scripts/temporary_data/task_registry.json', project_root)}`: scheduled task registry and last-run metadata",
        f"`{_relative_path(agent_root / 'SKILLs/file_control/scripts/temporary_data/file_ID.json', project_root)}`: file-control backup index",
        f"`{_relative_path(agent_root / 'SKILLs/file_control/scripts/temporary_data/backups', project_root)}/`: file-control backup payloads",
        f"`{_relative_path(agent_root / 'data/memories', project_root)}/`: persistent memory store",
        f"`{_relative_path(project_root / '.codex-temp', project_root)}/`: root-level cache and scratch space cleared by `/clear cache`",
        f"`{_relative_path(agent_root / '.codex-temp', project_root)}/`: agent-local cache and test scratch space also cleared by `/clear cache`",
        f"`{_relative_path(output_path, project_root)}`: auto-generated system map used as a first-stop index",
    ]

    telegram_lines = [
        "Inbound flow: `telegram_bridge.py` long-polls `getUpdates`, filters by allowlist, remembers known chats, and forwards text to `handle_message` in `main.py`.",
        "Per-chat sessioning: each allowed `chat_id` gets its own `SimpleAgent` instance and isolated in-memory history.",
        "Reply format: Telegram replies include captured `[SYSTEM]` and `[TOOL]` lines plus the final answer.",
        "Command handling: Telegram slash commands reuse the same command handler as terminal commands, except `/exit` is blocked remotely.",
        "Scheduled task delivery: scheduled-task output is broadcast to remembered allowed chats and any explicit `allowed_chat_ids`.",
        "Push limitation: if only usernames are allowlisted, the bot must first receive a message from that chat before scheduled-task output can be pushed there.",
        "Transport limitation: Telegram bridge is text-only; non-text messages receive a fallback reply.",
    ]

    flow_lines = [
        "Terminal request flow: terminal input -> `handle_cli_command` for `/...` or `SimpleAgent.run(...)` for normal input -> optional tool loop -> terminal display.",
        "Telegram request flow: Telegram update -> allowlist check -> per-chat `SimpleAgent` -> capture system/tool events -> send combined trace and answer back through `sendMessage`.",
        "Skill execution flow: model emits one JSON tool call -> `skill_client.py` posts to the skill server -> `skill_runtime.py` loads the configured Python function -> result JSON is returned to the agent as a follow-up message.",
        "Scheduled task flow: `schedule-task` stores `task_prompt` and timing -> `chat_scheduler.py` claims due tasks -> `main.py` dispatches the prompt through the main terminal agent -> result is recorded in the schedule registry -> output is shown in terminal and broadcast to Telegram when possible.",
        "Reload flow: `/reload` or file-change detection reloads config/prompts/skills, refreshes runtime clients, and regenerates this architecture file.",
    ]

    operational_notes = [
        "`/task ...` commands manipulate the schedule registry directly and do not require the LLM.",
        "`/clear cache` deletes only `.codex-temp` directories; it does not delete scheduled tasks or file-control backups.",
        "`file-control` protects its own backup store and returns permission denied if the agent targets `agent/SKILLs/file_control/scripts/temporary_data/`.",
        "`schedule-task` is agent-native, not OS-native. Tasks stop running when the agent process is not running.",
        "Secrets should live in `agent/data/system/secrets.local.json` or environment variables, not in tracked config files.",
        "This file is safe to use as a repository map, but it is derived from the current config and enabled skills, so disabling a skill changes future output.",
    ]

    lookup_guide = [
        "Need terminal or Telegram routing behavior: start with `agent/main.py` and `agent/telegram_bridge.py`.",
        "Need prompt composition or live reload behavior: start with `agent/config_loader.py` and the Prompt Stack section above.",
        "Need tool execution or skill registration: start with `agent/skill_server.py`, `agent/skill_runtime.py`, and the Enabled Skills section below.",
        "Need scheduler behavior or task persistence: start with `agent/schedule_runtime.py`, `agent/chat_scheduler.py`, and the schedule-task skill section.",
        f"Need broader usage examples or setup instructions: read `{_relative_path(readme_path, project_root)}`.",
    ]

    sections = [
        "# System Architecture",
        "This file is auto-generated by `agent/system_doc_generator.py` when the agent starts and when `/reload` runs.",
        _bullet_section("Current Runtime Snapshot", snapshot_lines),
        _bullet_section("Entrypoints And Core Components", CORE_COMPONENTS),
        _bullet_section("Session Model", session_model_lines),
        _bullet_section("Prompt Stack", prompt_lines),
        _bullet_section("Command Surface", CLI_COMMANDS),
    ]

    skill_sections = ["## Enabled Skills"]
    for skill in sorted(config.skills, key=lambda item: item.get("name", "")):
        skill_sections.append(_skill_block(skill, project_root))
    sections.append("\n\n".join(skill_sections))

    sections.extend(
        [
            _bullet_section("State And Storage", state_lines),
            _bullet_section("Telegram Integration", telegram_lines),
            _bullet_section("Execution Flows", flow_lines),
            _bullet_section("Operational Notes", operational_notes),
            _bullet_section("Edit Map", EDIT_MAP),
            _bullet_section("How To Use This File", lookup_guide),
        ]
    )

    content = "\n\n".join(sections).strip() + "\n"
    output_path.write_text(content, encoding="utf-8")
    return output_path
