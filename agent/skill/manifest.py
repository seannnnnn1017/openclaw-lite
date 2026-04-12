import re


def _normalize_whitespace(text: str) -> str:
    return " ".join(str(text or "").split())


def extract_supported_actions(skill_content: str) -> list[str]:
    lines = str(skill_content or "").splitlines()
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


def extract_intro_paragraph(skill_content: str) -> str:
    paragraph_lines = []

    for raw_line in str(skill_content or "").splitlines():
        line = raw_line.strip()
        if not line:
            if paragraph_lines:
                break
            continue
        paragraph_lines.append(line)

    return _normalize_whitespace(" ".join(paragraph_lines))


def skill_manifest_notes(skill_name: str) -> list[str]:
    notes_by_skill = {
        "file-control": [
            "Mutating actions create backups before changes.",
            "Localized edits are preferred over full rewrites when possible.",
            "For tasks that move local content into another system, use this skill only for the local file stage and hand the prepared content to the destination skill afterward.",
        ],
        "notion-basic": [
            "Primary access now goes through the configured Notion MCP server over HTTP.",
            "Prefer `delegate_task` for normal user-facing work; use `tools/list` and `tools/call` for explicit low-level MCP work.",
            "Treat the live `tools/list` result as the source of truth for the full Notion MCP API; compatibility aliases remain available.",
            "Use explicit MCP tool arguments rather than old convenience aliases or hidden defaults.",
            "The bridge handles MCP session setup automatically; do not emit `initialize` or notification methods.",
            "Notion specialists do not read local files directly; for file or folder imports, gather the source content first and pass the prepared payload into Notion work.",
            "Batch page creation is valid when the caller already supplied the page titles, hierarchy, and exact content to write.",
        ],
        "schedule-task": [
            "Scheduled tasks only run while the agent process is open.",
            "The scheduler stores `task_prompt` metadata and dispatches it back into the main agent later.",
            "Store only the underlying work in `task_prompt`; strip timing phrases like `every five minutes` or `tomorrow at 9:45`.",
            "Resolve relative dates like today or tomorrow against `time-query.now` before creating the schedule.",
        ],
        "time-query": [
            "Supports local time, explicit UTC offsets, cities, and IANA timezone names.",
        ],
    }
    return notes_by_skill.get(skill_name, [])


def delegation_preferred(skill_name: str) -> bool:
    return delegation_mode(skill_name) != "direct_ok"


def delegation_mode(skill_name: str) -> str:
    if skill_name == "notion-basic":
        return "specialist_only"
    if skill_name == "time-query":
        return "direct_ok"
    return "prefer"


def build_skill_manifest(skill: dict) -> dict:
    skill_name = str(skill.get("name", "")).strip() or "unknown-skill"
    metadata = skill.get("metadata", {}) or {}
    skill_content = str(skill.get("content", "")).strip()
    execution_mode = str(skill.get("execution_mode", "invoked")).strip() or "invoked"
    auto_context = skill.get("auto_context") if isinstance(skill.get("auto_context"), dict) else None

    description = _normalize_whitespace(metadata.get("description", ""))
    use_when = extract_intro_paragraph(skill_content)
    actions = extract_supported_actions(skill_content)
    notes = skill_manifest_notes(skill_name)
    prefer_delegate = delegation_preferred(skill_name)
    delegate_mode = delegation_mode(skill_name)

    lines = [f"[SKILL MANIFEST: {skill_name}]"]
    if description:
        lines.append(f"Description: {description}")
    if use_when and use_when != description:
        lines.append(f"Use when: {use_when}")
    if actions:
        lines.append(f"Supported actions: {', '.join(actions)}")
    if notes:
        lines.append(f"Notes: {'; '.join(notes)}")
    if execution_mode == "default":
        auto_action = str(auto_context.get("action", "")).strip() if auto_context else ""
        lines.append(
            "Execution mode: default"
            + (f"; automatic background action `{auto_action}` may run before answering." if auto_action else "; automatic background execution is enabled.")
        )
    else:
        lines.append("Execution mode: invoked; run this skill only when the task needs it.")
    if delegate_mode == "specialist_only":
        lines.append(
            "Delegation: route this skill through a single-skill specialist before tool execution;"
            " do not rely on the main agent to guess live tool names or payload schemas."
        )
    elif prefer_delegate:
        lines.append("Delegation: prefer `__delegate__` so a single-skill specialist can plan concrete actions.")
    else:
        lines.append("Delegation: direct actions are acceptable when the required arguments are obvious.")

    return {
        "name": skill_name,
        "description": description,
        "use_when": use_when,
        "supported_actions": actions,
        "notes": notes,
        "delegation_preferred": prefer_delegate,
        "delegation_mode": delegate_mode,
        "execution_mode": execution_mode,
        "auto_context": auto_context,
        "text": "\n".join(lines),
    }
