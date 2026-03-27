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
        ],
        "notion-basic": [
            "Page targets can fall back to the configured default Notion page.",
            "`sync_architecture` is live and capped at depth 3 per call.",
            "Delete actions move content to trash rather than permanently deleting it.",
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
    return skill_name not in {"time-query"}


def build_skill_manifest(skill: dict) -> dict:
    skill_name = str(skill.get("name", "")).strip() or "unknown-skill"
    metadata = skill.get("metadata", {}) or {}
    skill_content = str(skill.get("content", "")).strip()

    description = _normalize_whitespace(metadata.get("description", ""))
    use_when = extract_intro_paragraph(skill_content)
    actions = extract_supported_actions(skill_content)
    notes = skill_manifest_notes(skill_name)
    prefer_delegate = delegation_preferred(skill_name)

    lines = [f"[SKILL MANIFEST: {skill_name}]"]
    if description:
        lines.append(f"Description: {description}")
    if use_when and use_when != description:
        lines.append(f"Use when: {use_when}")
    if actions:
        lines.append(f"Supported actions: {', '.join(actions)}")
    if notes:
        lines.append(f"Notes: {'; '.join(notes)}")
    lines.append(
        "Delegation: prefer `__delegate__` so a single-skill specialist can plan concrete actions."
        if prefer_delegate
        else "Delegation: direct actions are acceptable when the required arguments are obvious."
    )

    return {
        "name": skill_name,
        "description": description,
        "use_when": use_when,
        "supported_actions": actions,
        "notes": notes,
        "delegation_preferred": prefer_delegate,
        "text": "\n".join(lines),
    }
