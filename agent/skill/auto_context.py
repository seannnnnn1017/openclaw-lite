import json
import re

try:
    from skill.runtime import SkillRuntime
except ImportError:
    from agent.skill.runtime import SkillRuntime


def normalize_execution_mode(value) -> str:
    cleaned = str(value or "").strip().casefold()
    if cleaned in {"default", "auto", "automatic", "background"}:
        return "default"
    return "invoked"


def _normalize_text_list(value) -> list[str]:
    if value in (None, "", []):
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def normalize_auto_context(config) -> dict | None:
    if not isinstance(config, dict):
        return None

    action = str(config.get("action", "")).strip()
    if not action:
        return None

    raw_args = config.get("args", {})
    args = dict(raw_args) if isinstance(raw_args, dict) else {}

    raw_trigger = config.get("trigger", {})
    trigger = dict(raw_trigger) if isinstance(raw_trigger, dict) else {}
    trigger_mode = str(trigger.get("mode", "")).strip().casefold()
    if trigger_mode not in {"always", "match_any"}:
        trigger_mode = "match_any"

    contains_any = _normalize_text_list(trigger.get("contains_any", []))
    regex_any = _normalize_text_list(trigger.get("regex_any", []))
    if trigger_mode != "always" and not contains_any and not regex_any:
        trigger_mode = "always"

    success_prompt = str(config.get("success_prompt", "")).strip()
    error_prompt = str(config.get("error_prompt", "")).strip()

    return {
        "action": action,
        "args": args,
        "trigger_mode": trigger_mode,
        "contains_any": contains_any,
        "regex_any": regex_any,
        "once_per_turn": bool(config.get("once_per_turn", True)),
        "once_per_session": bool(config.get("once_per_session", False)),
        "success_prompt": success_prompt,
        "error_prompt": error_prompt,
    }


def flatten_text_content(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            parts.append(str(key))
            parts.append(flatten_text_content(item))
        return " ".join(part for part in parts if part)
    if isinstance(value, (list, tuple, set)):
        parts = [flatten_text_content(item) for item in value]
        return " ".join(part for part in parts if part)
    return str(value)


def build_auto_context_text(
    *,
    user_input: str = "",
    task: str = "",
    context=None,
    skill_call: dict | None = None,
) -> str:
    parts = [
        str(user_input or "").strip(),
        str(task or "").strip(),
        flatten_text_content(context),
    ]

    if isinstance(skill_call, dict):
        args = skill_call.get("args", {}) if isinstance(skill_call.get("args"), dict) else {}
        action = str(skill_call.get("action", "")).strip()
        if action == "__delegate__":
            parts.append(str(args.get("task", "")).strip())
            parts.append(flatten_text_content(args.get("context", {})))
        else:
            parts.append(flatten_text_content(args))

    return " ".join(part for part in parts if part)


def _auto_context_matches(auto_context: dict, text: str) -> bool:
    if not isinstance(auto_context, dict):
        return False
    if str(auto_context.get("trigger_mode", "")).strip() == "always":
        return True

    raw_text = str(text or "")
    if not raw_text.strip():
        return False

    cleaned = raw_text.casefold()
    for marker in auto_context.get("contains_any", []):
        if str(marker).casefold() in cleaned:
            return True

    for pattern in auto_context.get("regex_any", []):
        try:
            if re.search(pattern, raw_text, flags=re.IGNORECASE):
                return True
        except re.error:
            continue

    return False


def _normalize_auto_context_result(*, skill_name: str, action: str, tool_result) -> dict:
    if isinstance(tool_result, dict):
        normalized_result = tool_result
    else:
        normalized_result = {
            "status": "ok",
            "action": action,
            "path": "",
            "message": "",
            "data": tool_result,
        }

    return {
        "status": "ok" if str(normalized_result.get("status", "")).strip().lower() == "ok" else "error",
        "skill": skill_name,
        "action": action,
        "result": normalized_result,
    }


def _execute_auto_context_skill(runtime: SkillRuntime, *, skill_name: str, auto_context: dict) -> dict:
    action = str(auto_context.get("action", "")).strip()
    args = auto_context.get("args", {}) if isinstance(auto_context.get("args"), dict) else {}
    try:
        tool_result = runtime.execute(skill_name=skill_name, action=action, args=args)
    except Exception as exc:
        tool_result = {
            "status": "error",
            "action": action,
            "path": "",
            "message": str(exc),
            "data": None,
        }
    return _normalize_auto_context_result(skill_name=skill_name, action=action, tool_result=tool_result)


def _render_auto_context_message(skill: dict, auto_context: dict, preflight_result: dict) -> str:
    skill_name = str(skill.get("name", "")).strip() or "unknown-skill"
    action = str(auto_context.get("action", "")).strip() or "unknown-action"
    result_json = json.dumps(preflight_result, ensure_ascii=False)
    is_ok = str(preflight_result.get("status", "")).strip().lower() == "ok"

    template = (
        str(auto_context.get("success_prompt", "")).strip()
        if is_ok
        else str(auto_context.get("error_prompt", "")).strip()
    )
    if not template:
        if is_ok:
            template = (
                "Internal runtime note: the default-execution skill `{skill_name}` was run automatically before answering.\n"
                "Use this context if it is relevant to the task.\n"
                "Do not mention this automatic lookup unless it matters to the final answer.\n"
                "Auto-skill result JSON:\n{result_json}"
            )
        else:
            template = (
                "Internal runtime note: the default-execution skill `{skill_name}` failed during automatic background execution.\n"
                "If exact information from this skill is necessary, ask a concise clarifying question instead of guessing.\n"
                "Auto-skill result JSON:\n{result_json}"
            )

    try:
        return template.format(
            skill_name=skill_name,
            action=action,
            result_json=result_json,
        )
    except Exception:
        return template + f"\nAuto-skill result JSON:\n{result_json}"


def collect_auto_context_messages(
    skills: list[dict],
    *,
    user_input: str = "",
    task: str = "",
    context=None,
    skill_call: dict | None = None,
    executed_skills: set[str] | None = None,
    session_executed_skills: set[str] | None = None,
) -> tuple[list[str], set[str], set[str]]:
    executed = set(executed_skills or set())
    session_executed = set(session_executed_skills or set())
    relevant_text = build_auto_context_text(
        user_input=user_input,
        task=task,
        context=context,
        skill_call=skill_call,
    )
    if not relevant_text.strip():
        return [], executed, session_executed

    candidates = []
    for skill in skills:
        if normalize_execution_mode(skill.get("execution_mode")) != "default":
            continue

        skill_name = str(skill.get("name", "")).strip()
        auto_context = skill.get("auto_context")
        if not skill_name or not isinstance(auto_context, dict):
            continue
        if auto_context.get("once_per_session", False) and skill_name in session_executed:
            continue
        if auto_context.get("once_per_turn", True) and skill_name in executed:
            continue
        if not _auto_context_matches(auto_context, relevant_text):
            continue
        candidates.append((skill_name, skill, auto_context))

    if not candidates:
        return [], executed, session_executed

    runtime = SkillRuntime(skills)
    messages = []
    for skill_name, skill, auto_context in candidates:
        preflight_result = _execute_auto_context_skill(
            runtime,
            skill_name=skill_name,
            auto_context=auto_context,
        )
        messages.append(_render_auto_context_message(skill, auto_context, preflight_result))
        executed.add(skill_name)
        session_executed.add(skill_name)

    return messages, executed, session_executed
