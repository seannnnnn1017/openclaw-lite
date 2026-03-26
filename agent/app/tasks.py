from __future__ import annotations

from datetime import datetime

try:
    from schedule_runtime import create_task
except ModuleNotFoundError:
    from agent.schedule_runtime import create_task


EDITABLE_TASK_FIELDS = {"start_time", "start_date", "task_prompt"}


def normalize_task_name(value: str) -> str:
    normalized = str(value or "").strip().replace("\\", "/")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return normalized.strip("/")


def resolve_task_identifier(tasks: list[dict], identifier: str) -> dict | None:
    cleaned = str(identifier or "").strip()
    if not cleaned:
        return None

    upper_identifier = cleaned.upper()
    normalized_identifier = normalize_task_name(cleaned)

    for task in tasks:
        if str(task.get("id", "")).upper() == upper_identifier:
            return task

    for task in tasks:
        if normalize_task_name(task.get("task_name", "")) == normalized_identifier:
            return task

    short_name_matches = [
        task
        for task in tasks
        if normalize_task_name(task.get("short_name", "")) == normalized_identifier
    ]
    if len(short_name_matches) == 1:
        return short_name_matches[0]

    return None


def format_task_datetime(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    try:
        return datetime.fromisoformat(text).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text


def format_task_status(task: dict) -> str:
    if task.get("deleted"):
        return "deleted"
    if task.get("completed"):
        return "completed"
    if task.get("pending_now"):
        return "queued"
    if task.get("enabled"):
        return "enabled"
    return "disabled"


def format_task_list(tasks: list[dict]) -> str:
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
                    format_task_status(task),
                    f"next={format_task_datetime(task.get('next_run_at', ''))}",
                ]
            )
        )
    return "\n".join(lines)


def format_task_days(task: dict) -> str:
    days = [str(day).strip() for day in (task.get("days_of_week") or []) if str(day).strip()]
    return ",".join(days) if days else "-"


def format_task_summary(task: dict) -> str:
    return "\n".join(
        [
            f"id: {str(task.get('id', '')).strip() or '-'}",
            f"name: {str(task.get('task_name', '')).strip() or '-'}",
            f"schedule: {str(task.get('schedule_type', '')).strip() or '-'}",
            f"date: {str(task.get('start_date', '')).strip() or '-'}",
            f"time: {str(task.get('start_time', '')).strip() or '-'}",
            f"modifier: {task.get('modifier') if task.get('modifier') is not None else '-'}",
            f"days: {format_task_days(task)}",
            f"status: {format_task_status(task)}",
            f"next: {format_task_datetime(task.get('next_run_at', ''))}",
            "",
            f"prompt: {str(task.get('task_prompt', '')).strip() or '-'}",
        ]
    )


def task_action_reply_markup(task_id: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {
                    "text": "Edit",
                    "callback_data": f"task:edit:{task_id}",
                },
                {
                    "text": "Delete",
                    "callback_data": f"task:delete:{task_id}",
                },
            ]
        ]
    }


def task_edit_reply_markup(task_id: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {
                    "text": "Time",
                    "callback_data": f"task:field:start_time:{task_id}",
                },
                {
                    "text": "Date",
                    "callback_data": f"task:field:start_date:{task_id}",
                },
            ],
            [
                {
                    "text": "Prompt",
                    "callback_data": f"task:field:task_prompt:{task_id}",
                },
                {
                    "text": "Cancel",
                    "callback_data": f"task:cancel:{task_id}",
                },
            ],
        ]
    }


def task_edit_instruction(task: dict, field: str) -> str:
    field_prompts = {
        "start_time": "Send the new execution time in `HH:MM` format, for example `18:30`.",
        "start_date": "Send the new execution date in `YYYY-MM-DD` format, for example `2026-03-25`.",
        "task_prompt": "Send the new task prompt text.",
    }
    instruction = field_prompts.get(field, "Send the new field value.")
    return "\n".join(
        [
            "Task edit pending.",
            instruction,
            "Send `/cancel` to stop editing.",
            "",
            format_task_summary(task),
        ]
    )


def apply_task_edit(task: dict, *, field: str, raw_value: str, actor: str) -> dict:
    value = str(raw_value or "").strip()
    if not value:
        raise ValueError("New value cannot be empty.")

    if field not in EDITABLE_TASK_FIELDS:
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
