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
    "agent/main.py: terminal entrypoint, command handling, Telegram routing, scheduler integration",
    "agent/agent.py: `SimpleAgent` reasoning loop, tool JSON parsing, per-session history",
    "agent/config_loader.py: loads config, prompts, enabled skills, and runtime model overrides",
    "agent/skill_server.py + agent/skill_runtime.py: skill request dispatch and tool loading",
    "agent/schedule_runtime.py + agent/chat_scheduler.py: schedule registry, due-task polling, result recording",
    "agent/telegram_bridge.py: Telegram polling, allowlist checks, callback routing, message send/edit, image download/storage",
    "agent/terminal_display.py: terminal rendering plus Telegram tool-event capture",
    "agent/system_doc_generator.py: generates this file from current config and enabled skills",
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
            "The `read` action supports both text files and local image files; image reads can be attached back to the model for multimodal inspection.",
            "Backup storage is protected from ordinary skill edits and returns permission denied if targeted.",
            "Backup cleanup is not part of normal file-control operations.",
        ]
    if skill_name == "notion-basic":
        return [
            "Uses the Notion REST API and reads credentials from env vars or `agent/data/system/secrets.local.json`.",
            "When no Notion page target is provided, the skill falls back to the default page configured in `agent/data/system/secrets.local.json` via `notion.default_parent_page_id` or `notion.default_parent_page_url`.",
            "Page content operations use Notion's markdown endpoints for full-page replace, append, and targeted search-and-replace.",
            "Notion search uses the official `/search` API for shared page and data source title metadata only; it is not full-text attachment search.",
            "Downloaded Notion images are saved locally under `agent/data/notion_downloads/` unless an explicit path is provided.",
            "Structure discovery relies on live `sync_architecture` calls instead of a local architecture cache.",
            "Each `sync_architecture` call is capped at depth 3; to inspect deeper structure, call it again from a deeper page, database, or data source target.",
            "Delete is implemented as moving a page to trash; the Notion API does not permanently delete pages.",
        ]
    if skill_name == "schedule-task":
        return [
            "The scheduler stores timing plus `task_prompt`; it does not run raw shell commands directly.",
            "Due tasks are dispatched back into the main terminal `SimpleAgent` instance, not into a Telegram per-chat session.",
            "When Telegram delivery targets are known, scheduled task output is broadcast to Telegram with inline `編輯` and `刪除` actions, and edits are completed through follow-up chat messages.",
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
            f"`{_relative_path(project_root / 'agent/data/notion_downloads', project_root)}/`: local downloads created by `notion-basic.download_image`",
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
    telegram_allowlist_parts = [
        f"allowed usernames={len(config.telegram_allowed_usernames)}",
        f"allowed chat IDs={len(config.telegram_allowed_chat_ids)}",
    ]
    telegram_state_rel = _relative_path(Path(config.telegram_state_path), project_root)
    telegram_image_storage_rel = _relative_path(Path(config.telegram_image_storage_path), project_root)
    enabled_skill_names = [skill.get("name", "") for skill in config.skills]

    snapshot_lines = [
        f"Generated at: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Active model: `{config.model}`",
        f"LLM base URL: `{config.base_url}`",
        f"Skill server URL: `{config.skill_server_url}`",
        f"Telegram bridge enabled: {'yes' if config.telegram_enabled else 'no'}",
        f"Telegram polling: timeout={config.telegram_poll_timeout_seconds}s, retry_delay={config.telegram_retry_delay_seconds}s, skip_pending_on_start={'yes' if config.telegram_skip_pending_updates_on_start else 'no'}",
        f"Telegram image storage: `{telegram_image_storage_rel}`",
        f"Telegram allowlist summary: {', '.join(telegram_allowlist_parts)}",
        f"Enabled skills ({len(enabled_skill_names)}): {', '.join(f'`{name}`' for name in enabled_skill_names)}",
    ]

    session_model_lines = [
        "Terminal uses one shared `SimpleAgent` instance.",
        "Telegram keeps one `SimpleAgent` per `chat_id` in `telegram_agents`.",
        "History is in-memory and separated by session.",
        "Tool loop limit: `SimpleAgent.max_tool_steps = 6`.",
    ]

    prompt_lines = [
        f"Active identity prompt: `{_relative_path(identity_path, project_root)}`",
        f"Active system rules prompt: `{_relative_path(system_rules_path, project_root)}`",
        f"Active boundaries prompt: `{_relative_path(boundaries_path, project_root)}`",
        "Prompt order: `identity -> system_rules -> boundaries -> enabled SKILL.md bodies`.",
        f"Cross-skill rules and project conventions: `{_relative_path(skill_rule_path, project_root)}`" if skill_rule_path.exists() else "Cross-skill rules file: not present",
    ]

    state_lines = [
        f"`{_relative_path(config.path, project_root)}`: non-secret runtime config",
        f"`{_relative_path(agent_root / 'data/system/secrets.local.json', project_root)}`: local secrets for LLM, Telegram, Notion",
        f"`{telegram_state_rel}`: Telegram offset + known chats",
        f"`{telegram_image_storage_rel}/`: downloaded Telegram image files",
        f"`{_relative_path(agent_root / 'SKILLs/schedule_task/scripts/temporary_data/task_registry.json', project_root)}`: schedule registry",
        f"`{_relative_path(agent_root / 'data/memories', project_root)}/`: persistent memory store",
        f"`{_relative_path(output_path, project_root)}`: this generated system map",
    ]

    telegram_lines = [
        "Handles text messages, inbound image messages, plus `callback_query` inline actions.",
        "Telegram sessions are isolated per `chat_id`.",
        "Incoming Telegram photos and image documents are downloaded and stored locally before the event reaches the agent.",
        "For the current Telegram image turn, saved images are attached to the model request as OpenAI-compatible `image_url` content parts, while session history keeps a compact text record with the saved local paths.",
        "Direct Telegram chat replies use throttled rolling edits at roughly 300 ms intervals when streamed model text looks like a user-facing answer.",
        "Tool activity is streamed live as compact `[TOOL] skill.action` messages and edited in place with results.",
        "Inline controls: `展開` / `收合` for tool details, `編輯` / `刪除` for scheduled-task notifications.",
        "If only usernames are allowlisted, the bot must first receive a message from that chat before scheduled-task push works.",
    ]

    flow_lines = [
        "Terminal: input -> slash-command handler or `SimpleAgent.run(...)` -> optional tool loop -> terminal output.",
        "Telegram: update -> allowlist check -> per-chat `SimpleAgent` -> live tool messages -> final answer.",
        "Skills: model emits one JSON tool call -> skill server -> Python tool -> result returned to agent.",
        "Scheduled tasks: registry -> due-task claim -> main `agent` runs `task_prompt` -> result recorded and optionally pushed to Telegram.",
    ]

    operational_notes = [
        "`/task ...` commands manipulate the schedule registry directly and do not require the LLM.",
        "`/clear cache` only deletes `.codex-temp` directories.",
        "`schedule-task` is agent-native; tasks stop when the agent process stops.",
        "Notion structure inspection now uses live `sync_architecture` calls with a maximum depth of 3 per call.",
        "Secrets should stay in `agent/data/system/secrets.local.json` or environment variables.",
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
        ]
    )

    content = "\n\n".join(sections).strip() + "\n"
    output_path.write_text(content, encoding="utf-8")
    return output_path
