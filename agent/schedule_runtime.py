from __future__ import annotations

import json
import math
import os
import re
import shutil
import threading
from datetime import date, datetime, time, timedelta
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent / "SKILLs" / "schedule_task" / "scripts"
TEMP_DIR = SCRIPT_DIR / "temporary_data"
DEFAULT_REGISTRY_FILE = TEMP_DIR / "task_registry.json"
REGISTRY_ENV_VAR = "OPENCLAW_SCHEDULE_REGISTRY"
REGISTRY_LOCK = threading.RLock()
WEEKDAY_ALIASES = {
    "MON": 0,
    "MONDAY": 0,
    "TUE": 1,
    "TUESDAY": 1,
    "WED": 2,
    "WEDNESDAY": 2,
    "THU": 3,
    "THURSDAY": 3,
    "FRI": 4,
    "FRIDAY": 4,
    "SAT": 5,
    "SATURDAY": 5,
    "SUN": 6,
    "SUNDAY": 6,
}
WEEKDAY_NAMES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def _now() -> datetime:
    return datetime.now().astimezone()


def _iso(dt: datetime | None) -> str:
    if not dt:
        return ""
    return dt.astimezone().isoformat(timespec="seconds")


def _registry_path(registry_path: str | Path | None = None) -> Path:
    candidate = registry_path or os.getenv(REGISTRY_ENV_VAR, "")
    if candidate:
        return Path(candidate).expanduser().resolve()
    return DEFAULT_REGISTRY_FILE


def _default_registry() -> dict:
    return {"next_id": 1, "tasks": []}


def _ensure_storage(registry_path: str | Path | None = None) -> Path:
    path = _registry_path(registry_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            json.dumps(_default_registry(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return path


def _save_registry(registry: dict, registry_path: str | Path | None = None):
    path = _ensure_storage(registry_path)
    path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def clear_schedule_cache(*, registry_path: str | Path | None = None) -> dict:
    path = _registry_path(registry_path)
    temp_dir = path.parent

    with REGISTRY_LOCK:
        tasks_cleared = 0
        next_id_before = 1
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    tasks = raw.get("tasks", [])
                    if isinstance(tasks, list):
                        tasks_cleared = len(tasks)
                    next_id_before = raw.get("next_id", 1)
            except Exception:
                pass

        if temp_dir.exists():
            shutil.rmtree(temp_dir)

        temp_dir.mkdir(parents=True, exist_ok=True)
        reset_registry = _default_registry()
        path.write_text(
            json.dumps(reset_registry, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return {
            "temp_dir": str(temp_dir),
            "registry_path": str(path),
            "tasks_cleared": tasks_cleared,
            "next_id_before": next_id_before,
            "next_id_after": reset_registry["next_id"],
        }


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _clean_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_name(value: str) -> str:
    text = _clean_text(value).replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    return text.strip("/")


def _short_name(name: str) -> str:
    normalized = _normalize_name(name)
    return normalized.split("/")[-1] if normalized else ""


def _normalize_time(value: str, *, default: str = "") -> str:
    text = _clean_text(value)
    if not text:
        return default

    candidates = [text, f"{text}:00" if text.count(":") == 1 else text]
    for candidate in candidates:
        for fmt in ("%H:%M", "%H:%M:%S"):
            try:
                parsed = datetime.strptime(candidate, fmt)
                return parsed.strftime("%H:%M")
            except ValueError:
                continue

    raise ValueError(f"Invalid time format: {value}")


def _normalize_date(value: str, *, default: str = "") -> str:
    text = _clean_text(value)
    if not text:
        return default

    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"Invalid date format: {value}") from exc
    return parsed.strftime("%Y-%m-%d")


def _normalize_schedule_type(value: str) -> str:
    text = _clean_text(value).lower().replace("_", "-")
    aliases = {
        "once": "once",
        "one-time": "once",
        "one time": "once",
        "daily": "daily",
        "day": "daily",
        "weekly": "weekly",
        "week": "weekly",
        "minute": "minute",
        "minutes": "minute",
        "hourly": "hourly",
        "hour": "hourly",
        "hours": "hourly",
    }
    normalized = aliases.get(text)
    if not normalized:
        raise ValueError(f"Unsupported schedule_type: {value}")
    return normalized


def _normalize_modifier(value, schedule_type: str):
    if schedule_type == "once":
        return None

    if value in (None, ""):
        return 1

    try:
        modifier = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid modifier: {value}") from exc

    if modifier < 1:
        raise ValueError("modifier must be >= 1")

    return modifier


def _normalize_days_of_week(value) -> list[str]:
    if value in (None, "", []):
        return []

    if isinstance(value, str):
        tokens = [part for part in value.replace(",", " ").split() if part]
    elif isinstance(value, (list, tuple, set)):
        tokens = [str(part).strip() for part in value if str(part).strip()]
    else:
        raise ValueError("days_of_week must be a string or array")

    normalized = []
    seen = set()
    for token in tokens:
        weekday_index = WEEKDAY_ALIASES.get(token.strip().upper())
        if weekday_index is None:
            raise ValueError(f"Unsupported weekday: {token}")
        weekday_name = WEEKDAY_NAMES[weekday_index]
        if weekday_name not in seen:
            seen.add(weekday_name)
            normalized.append(weekday_name)

    return normalized


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_time(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


def _parse_dt(value: str) -> datetime | None:
    text = _clean_text(value)
    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=_now().tzinfo)
    return parsed.astimezone()


def _combine_local(date_value: str, time_value: str) -> datetime:
    return datetime.combine(
        _parse_date(date_value),
        _parse_time(time_value),
    ).replace(tzinfo=_now().tzinfo)


def _resolve_task_prompt(
    task_prompt: str = "",
    task: str = "",
    prompt: str = "",
    command: str = "",
    arguments: str = "",
) -> str:
    for candidate in (task_prompt, task, prompt):
        cleaned = _clean_text(candidate)
        if cleaned:
            return cleaned

    combined = " ".join(
        part for part in [_clean_text(command), _clean_text(arguments)] if part
    ).strip()
    if combined:
        return f"Run this legacy command and report the result in chat: {combined}"

    return ""


def _sanitize_task_prompt(task_prompt: str) -> str:
    cleaned = _clean_text(task_prompt)
    if not cleaned:
        return ""

    text = cleaned
    chinese_number = r"(?:\d+|[零〇一二兩三四五六七八九十百千]+)"
    clock_time = (
        r"(?:"
        r"(?:(?:[01]?\d|2[0-3]):[0-5]\d(?:\:[0-5]\d)?)"
        r"|(?:(?:[1-9]|1[0-2])\s*(?:am|pm))"
        r")"
    )
    zh_time_of_day = r"(?:凌晨|清晨|早上|上午|中午|下午|傍晚|晚上|夜裡|夜間)"
    en_time_of_day = (
        r"(?:early\s+morning|morning|afternoon|evening|tonight|"
        r"in\s+the\s+morning|in\s+the\s+afternoon|in\s+the\s+evening)"
    )
    zh_recurring = (
        rf"(?:每(?:隔)?\s*{chinese_number}\s*(?:分鐘|分|小時|個小時|鐘頭|個鐘頭|天|日|週|周|星期|個星期|月|個月)"
        r"|每(?:天|日|週|周|星期|月|小時|鐘頭|分鐘)"
        r"|每(?:週|周|星期)\s*[一二三四五六日天]"
        r"|每個(?:小時|鐘頭|星期|月))"
    )
    en_recurring = (
        r"(?:every\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|an?|couple\s+of)\s+"
        r"(?:minute|minutes|hour|hours|day|days|week|weeks|month|months)"
        r"|every\s+(?:minute|hour|day|week|month)"
        r"|every\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
        r"|hourly|daily|weekly|monthly)"
    )
    zh_relative = (
        r"(?:今天|今晚|今早|今天早上|今天上午|今天下午|今天晚上|"
        r"明天|明晚|明早|明天早上|明天上午|明天下午|明天晚上|"
        r"後天|後天早上|後天下午|後天晚上|"
        r"本週|本周|這週|這周|這星期|下週|下周|下星期|"
        r"下(?:週|周|星期)\s*[一二三四五六日天]|"
        r"這(?:週|周|星期)\s*[一二三四五六日天]|"
        r"本(?:週|周)\s*[一二三四五六日天]|"
        r"下個月|這個月|本月)"
    )
    en_relative = (
        r"(?:today|tomorrow|tonight|day\s+after\s+tomorrow|"
        r"this\s+(?:morning|afternoon|evening|week|month)|"
        r"next\s+(?:week|month|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
        r"tomorrow\s+(?:morning|afternoon|evening))"
    )
    relative_phrase = (
        rf"(?:{zh_relative}|{en_relative})"
        rf"(?:\s*(?:{zh_time_of_day}|{en_time_of_day}))?"
        rf"(?:\s*{clock_time})?"
    )
    time_only_phrase = rf"(?:(?:{zh_time_of_day}|{en_time_of_day})\s*)?(?:{clock_time})"
    prefix_patterns = [
        r"^(?:please|please\s+help(?:\s+me)?|help(?:\s+me)?|kindly|can\s+you|could\s+you|would\s+you)\s+",
        r"^(?:請(?:幫我|你|協助)?|麻煩(?:你)?|幫我|幫忙|請替我)\s*",
        rf"^(?:{zh_recurring}|{en_recurring})\s*",
        rf"^(?:(?:在|於|on|at|in|by|around|about)\s+)?{relative_phrase}\s*",
        rf"^(?:(?:在|於|at|around|about)\s+)?{time_only_phrase}\s*",
    ]

    changed = True
    while changed and text:
        changed = False
        for pattern in prefix_patterns:
            updated = re.sub(pattern, "", text, count=1, flags=re.IGNORECASE).strip()
            if updated != text:
                text = updated
                changed = True
        updated = re.sub(r"^[,，、:：;；\-\(\)\[\]\s]+", "", text).strip()
        if updated != text:
            text = updated
            changed = True

    if not text:
        return cleaned
    return text


def _scheduled_start(record: dict) -> datetime:
    return _combine_local(record["start_date"], record["start_time"])


def _compute_interval_next(
    start_dt: datetime,
    interval: timedelta,
    reference_dt: datetime,
    *,
    inclusive: bool,
) -> datetime:
    if reference_dt < start_dt:
        return start_dt
    if inclusive and reference_dt == start_dt:
        return start_dt

    elapsed = (reference_dt - start_dt).total_seconds()
    interval_seconds = interval.total_seconds()
    steps = math.floor(elapsed / interval_seconds)
    candidate = start_dt + (interval * steps)
    if candidate < reference_dt or (candidate == reference_dt and not inclusive):
        candidate += interval
    return candidate


def _compute_weekly_next(record: dict, reference_dt: datetime, *, inclusive: bool) -> datetime | None:
    start_dt = _scheduled_start(record)
    modifier = int(record.get("modifier") or 1)
    allowed_weekdays = [
        WEEKDAY_ALIASES[weekday]
        for weekday in _normalize_days_of_week(record.get("days_of_week", []))
    ]
    if not allowed_weekdays:
        return None

    anchor_week_start = start_dt.date() - timedelta(days=start_dt.weekday())
    reference_date = reference_dt.date()
    starting_week = max(0, (reference_date - anchor_week_start).days // 7 - 1)

    for week_offset in range(starting_week, starting_week + 520):
        if week_offset % modifier != 0:
            continue

        week_start = anchor_week_start + timedelta(weeks=week_offset)
        for weekday_index in sorted(allowed_weekdays):
            candidate_date = week_start + timedelta(days=weekday_index)
            candidate = datetime.combine(candidate_date, start_dt.time()).replace(
                tzinfo=start_dt.tzinfo
            )
            if candidate < start_dt:
                continue
            if candidate < reference_dt:
                continue
            if candidate == reference_dt and not inclusive:
                continue
            return candidate

    return None


def _compute_next_occurrence(record: dict, reference_dt: datetime, *, inclusive: bool) -> datetime | None:
    schedule_type = record["schedule_type"]
    start_dt = _scheduled_start(record)

    if schedule_type == "once":
        if inclusive:
            return start_dt
        return None
    if schedule_type == "minute":
        return _compute_interval_next(
            start_dt,
            timedelta(minutes=int(record.get("modifier") or 1)),
            reference_dt,
            inclusive=inclusive,
        )
    if schedule_type == "hourly":
        return _compute_interval_next(
            start_dt,
            timedelta(hours=int(record.get("modifier") or 1)),
            reference_dt,
            inclusive=inclusive,
        )
    if schedule_type == "daily":
        return _compute_interval_next(
            start_dt,
            timedelta(days=int(record.get("modifier") or 1)),
            reference_dt,
            inclusive=inclusive,
        )
    if schedule_type == "weekly":
        return _compute_weekly_next(record, reference_dt, inclusive=inclusive)

    return None


def _normalize_record(record: dict) -> tuple[dict, bool]:
    if not isinstance(record, dict):
        record = {}

    original = json.dumps(record, ensure_ascii=False, sort_keys=True)
    now = _now()
    normalized = dict(record)

    task_name = _normalize_name(
        normalized.get("task_name")
        or normalized.get("name")
        or normalized.get("short_name")
        or normalized.get("id")
        or ""
    )
    normalized["task_name"] = task_name
    normalized["name"] = task_name
    normalized["short_name"] = _short_name(task_name)

    schedule_type = _normalize_schedule_type(normalized.get("schedule_type") or "daily")
    normalized["schedule_type"] = schedule_type

    default_date = normalized.get("start_date") or now.strftime("%Y-%m-%d")
    normalized["start_date"] = _normalize_date(default_date, default=now.strftime("%Y-%m-%d"))
    normalized["start_time"] = _normalize_time(
        normalized.get("start_time") or "00:00",
        default="00:00",
    )
    normalized["modifier"] = _normalize_modifier(normalized.get("modifier"), schedule_type)

    if schedule_type == "weekly":
        normalized["days_of_week"] = _normalize_days_of_week(normalized.get("days_of_week"))
        if not normalized["days_of_week"]:
            normalized["days_of_week"] = [WEEKDAY_NAMES[_scheduled_start(normalized).weekday()]]
    else:
        normalized["days_of_week"] = _normalize_days_of_week(normalized.get("days_of_week"))

    if schedule_type == "once":
        normalized["days_of_week"] = []

    normalized["task_prompt"] = _resolve_task_prompt(
        task_prompt=normalized.get("task_prompt", ""),
        task=normalized.get("task", ""),
        prompt=normalized.get("prompt", ""),
        command=normalized.get("command", ""),
        arguments=normalized.get("arguments", ""),
    )

    normalized["enabled"] = _bool(normalized.get("enabled", True))
    normalized["completed"] = _bool(normalized.get("completed", False))
    normalized["deleted"] = _bool(normalized.get("deleted", False))
    normalized["pending_now"] = _bool(normalized.get("pending_now", False))
    normalized["reason"] = _clean_text(normalized.get("reason"))
    normalized["deleted_at"] = _clean_text(normalized.get("deleted_at"))
    normalized["pending_requested_at"] = _iso(_parse_dt(normalized.get("pending_requested_at", "")))
    normalized["last_run_at"] = _iso(_parse_dt(normalized.get("last_run_at", "")))
    normalized["last_status"] = _clean_text(normalized.get("last_status"))
    normalized["last_response"] = _clean_text(normalized.get("last_response"))
    normalized["last_error"] = _clean_text(normalized.get("last_error"))
    normalized["last_trigger"] = _clean_text(normalized.get("last_trigger"))
    normalized["last_scheduled_for"] = _iso(_parse_dt(normalized.get("last_scheduled_for", "")))
    normalized["last_dispatch_at"] = _iso(_parse_dt(normalized.get("last_dispatch_at", "")))
    normalized["created_at"] = _iso(_parse_dt(normalized.get("created_at", ""))) or _iso(now)
    normalized["updated_at"] = _iso(_parse_dt(normalized.get("updated_at", ""))) or normalized["created_at"]
    normalized["next_run_at"] = _iso(_parse_dt(normalized.get("next_run_at", "")))

    if schedule_type == "once" and normalized["completed"]:
        normalized["next_run_at"] = ""

    if (
        not normalized["deleted"]
        and not normalized["completed"]
        and normalized["enabled"]
        and not normalized["next_run_at"]
    ):
        next_run = _compute_next_occurrence(normalized, now, inclusive=True)
        normalized["next_run_at"] = _iso(next_run)

    mutated = json.dumps(normalized, ensure_ascii=False, sort_keys=True) != original
    return normalized, mutated


def _should_purge_record(record: dict) -> bool:
    if _bool(record.get("deleted", False)):
        return True
    if _bool(record.get("completed", False)):
        return True
    return False


def _load_registry(registry_path: str | Path | None = None) -> dict:
    path = _ensure_storage(registry_path)
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return _default_registry()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _default_registry()

    if not isinstance(data, dict):
        return _default_registry()

    tasks = data.get("tasks", [])
    next_id = data.get("next_id", 1)
    if not isinstance(tasks, list):
        tasks = []
    if not isinstance(next_id, int) or next_id < 1:
        next_id = 1

    normalized_tasks = []
    changed = False
    for record in tasks:
        normalized, mutated = _normalize_record(record)
        if _should_purge_record(normalized):
            changed = True
            continue
        normalized_tasks.append(normalized)
        changed = changed or mutated

    registry = {
        "next_id": next_id,
        "tasks": normalized_tasks,
    }

    if changed:
        _save_registry(registry, path)

    return registry


def _present_task(record: dict) -> dict:
    task = {
        "id": record.get("id", ""),
        "name": record.get("task_name", ""),
        "short_name": record.get("short_name", ""),
        "task_prompt": record.get("task_prompt", ""),
        "schedule_type": record.get("schedule_type", ""),
        "start_date": record.get("start_date", ""),
        "start_time": record.get("start_time", ""),
        "modifier": record.get("modifier"),
        "days_of_week": list(record.get("days_of_week", [])),
        "enabled": _bool(record.get("enabled", False)),
        "completed": _bool(record.get("completed", False)),
        "deleted": _bool(record.get("deleted", False)),
        "reason": record.get("reason", ""),
        "next_run_at": record.get("next_run_at", ""),
        "pending_now": _bool(record.get("pending_now", False)),
        "pending_requested_at": record.get("pending_requested_at", ""),
        "last_run_at": record.get("last_run_at", ""),
        "last_status": record.get("last_status", ""),
        "last_response": record.get("last_response", ""),
        "last_error": record.get("last_error", ""),
        "last_trigger": record.get("last_trigger", ""),
        "last_scheduled_for": record.get("last_scheduled_for", ""),
        "last_dispatch_at": record.get("last_dispatch_at", ""),
        "runner": "agent-dispatch",
        "requires_agent_running": True,
    }

    legacy_command = " ".join(
        part
        for part in [
            _clean_text(record.get("command")),
            _clean_text(record.get("arguments")),
        ]
        if part
    ).strip()
    if legacy_command:
        task["legacy_command"] = legacy_command

    return task


def _ok(action: str, message: str, data=None, registry_path: str | Path | None = None) -> dict:
    return {
        "status": "ok",
        "action": action,
        "path": str(_registry_path(registry_path)),
        "message": message,
        "data": data,
    }


def _error(action: str, message: str, registry_path: str | Path | None = None) -> dict:
    return {
        "status": "error",
        "action": action,
        "path": str(_registry_path(registry_path)),
        "message": message,
        "data": None,
    }


def _find_task_index(tasks: list[dict], name: str, *, include_deleted: bool = True) -> int | None:
    normalized_name = _normalize_name(name)
    for index in range(len(tasks) - 1, -1, -1):
        record = tasks[index]
        if _normalize_name(record.get("task_name", "")) != normalized_name:
            continue
        if not include_deleted and _bool(record.get("deleted", False)):
            continue
        return index
    return None


def create_task(
    *,
    name: str,
    task_prompt: str,
    schedule_type: str,
    start_time: str,
    start_date: str = "",
    modifier=None,
    days_of_week=None,
    overwrite: bool = False,
    enabled: bool = True,
    reason: str = "",
    registry_path: str | Path | None = None,
    **legacy_fields,
) -> dict:
    now = _now()
    task_name = _normalize_name(name)
    if not task_name:
        raise ValueError("Missing name")

    resolved_prompt = _resolve_task_prompt(
        task_prompt=task_prompt,
        task=legacy_fields.get("task", ""),
        prompt=legacy_fields.get("prompt", ""),
        command=legacy_fields.get("command", ""),
        arguments=legacy_fields.get("arguments", ""),
    )
    if not resolved_prompt:
        raise ValueError("Missing task_prompt")
    resolved_prompt = _sanitize_task_prompt(resolved_prompt)

    normalized_schedule_type = _normalize_schedule_type(schedule_type)
    normalized_start_time = _normalize_time(start_time)
    default_date = now.strftime("%Y-%m-%d") if normalized_schedule_type != "once" else ""
    normalized_start_date = _normalize_date(start_date, default=default_date)
    if normalized_schedule_type == "once" and not normalized_start_date:
        raise ValueError("start_date is required for once schedules")

    normalized_modifier = _normalize_modifier(modifier, normalized_schedule_type)
    normalized_days = _normalize_days_of_week(days_of_week)
    if normalized_schedule_type == "weekly" and not normalized_days:
        raise ValueError("days_of_week is required for weekly schedules")

    with REGISTRY_LOCK:
        registry = _load_registry(registry_path)
        tasks = registry["tasks"]
        any_index = _find_task_index(tasks, task_name, include_deleted=True)
        active_index = _find_task_index(tasks, task_name, include_deleted=False)

        if active_index is not None and not overwrite:
            raise ValueError(f"Task already exists: {task_name}")

        target_index = None
        record = {}
        if active_index is not None and overwrite:
            target_index = active_index
            record = dict(tasks[active_index])
        elif active_index is None and any_index is not None:
            target_index = any_index
            record = dict(tasks[any_index])
        else:
            record["id"] = f"TASK-{registry['next_id']:06d}"
            registry["next_id"] += 1

        record.update(
            {
                "task_name": task_name,
                "name": task_name,
                "short_name": _short_name(task_name),
                "task_prompt": resolved_prompt,
                "task": "",
                "prompt": "",
                "command": "",
                "arguments": "",
                "task_run": "",
                "schedule_type": normalized_schedule_type,
                "start_date": normalized_start_date,
                "start_time": normalized_start_time,
                "modifier": normalized_modifier,
                "days_of_week": normalized_days,
                "enabled": bool(enabled),
                "completed": False,
                "deleted": False,
                "deleted_at": "",
                "next_run_at": "",
                "pending_now": False,
                "pending_requested_at": "",
                "reason": _clean_text(reason),
                "last_status": "",
                "last_response": "",
                "last_error": "",
                "last_trigger": "",
                "last_scheduled_for": "",
                "last_dispatch_at": "",
                "last_run_at": "",
                "created_at": record.get("created_at") or _iso(now),
                "updated_at": _iso(now),
            }
        )

        if "timeout_seconds" in legacy_fields:
            record["timeout_seconds"] = legacy_fields.get("timeout_seconds")

        normalized_record, _ = _normalize_record(record)
        if normalized_record["enabled"]:
            normalized_record["next_run_at"] = _iso(
                _compute_next_occurrence(normalized_record, now, inclusive=True)
            )

        if target_index is None:
            tasks.append(normalized_record)
        else:
            tasks[target_index] = normalized_record

        _save_registry(registry, registry_path)
        return normalized_record


def get_task(name: str, *, include_deleted: bool = False, registry_path: str | Path | None = None) -> dict:
    with REGISTRY_LOCK:
        registry = _load_registry(registry_path)
        index = _find_task_index(registry["tasks"], name, include_deleted=include_deleted)
        if index is None:
            raise ValueError(f"Task not found: {name}")
        return dict(registry["tasks"][index])


def list_tasks(*, include_deleted: bool = False, registry_path: str | Path | None = None) -> list[dict]:
    with REGISTRY_LOCK:
        registry = _load_registry(registry_path)
        tasks = []
        for record in registry["tasks"]:
            if not include_deleted and _bool(record.get("deleted", False)):
                continue
            tasks.append(dict(record))
        tasks.sort(key=lambda item: (item.get("task_name", ""), item.get("created_at", "")))
        return tasks


def set_enabled(
    name: str,
    *,
    enabled: bool,
    registry_path: str | Path | None = None,
) -> dict:
    with REGISTRY_LOCK:
        now = _now()
        registry = _load_registry(registry_path)
        index = _find_task_index(registry["tasks"], name, include_deleted=False)
        if index is None:
            raise ValueError(f"Task not found: {name}")

        record = dict(registry["tasks"][index])
        record["enabled"] = bool(enabled)
        if enabled:
            if record.get("schedule_type") == "once" and _bool(record.get("completed", False)):
                record["completed"] = False
            record["next_run_at"] = _iso(_compute_next_occurrence(record, now, inclusive=True))
        else:
            record["pending_now"] = False
            record["pending_requested_at"] = ""
        record["updated_at"] = _iso(now)

        normalized_record, _ = _normalize_record(record)
        registry["tasks"][index] = normalized_record
        _save_registry(registry, registry_path)
        return normalized_record


def delete_task(name: str, *, reason: str = "", registry_path: str | Path | None = None) -> dict:
    with REGISTRY_LOCK:
        now = _now()
        registry = _load_registry(registry_path)
        index = _find_task_index(registry["tasks"], name, include_deleted=False)
        if index is None:
            raise ValueError(f"Task not found: {name}")

        record = dict(registry["tasks"][index])
        record["enabled"] = False
        record["deleted"] = True
        record["completed"] = False
        record["pending_now"] = False
        record["pending_requested_at"] = ""
        record["deleted_at"] = _iso(now)
        record["updated_at"] = _iso(now)
        record["reason"] = _clean_text(reason) or record.get("reason", "")
        record["last_trigger"] = "delete"
        record["next_run_at"] = ""

        normalized_record, _ = _normalize_record(record)
        registry["tasks"].pop(index)
        _save_registry(registry, registry_path)
        return normalized_record


def queue_task_now(name: str, *, registry_path: str | Path | None = None) -> dict:
    with REGISTRY_LOCK:
        now = _now()
        registry = _load_registry(registry_path)
        index = _find_task_index(registry["tasks"], name, include_deleted=False)
        if index is None:
            raise ValueError(f"Task not found: {name}")

        record = dict(registry["tasks"][index])
        record["pending_now"] = True
        record["pending_requested_at"] = _iso(now)
        record["updated_at"] = _iso(now)

        normalized_record, _ = _normalize_record(record)
        registry["tasks"][index] = normalized_record
        _save_registry(registry, registry_path)
        return normalized_record


def build_dispatch_prompt(record: dict, *, trigger: str, scheduled_for: str = "") -> str:
    now = _now()
    lines = [
        "This is an internal scheduled-task trigger from the agent.",
        f"Task name: {record.get('task_name', '')}",
        f"Trigger type: {trigger}",
    ]
    if scheduled_for:
        lines.append(f"Scheduled for: {scheduled_for}")
    lines.extend(
        [
            f"Current local time: {_iso(now)}",
            "",
            "Execute the following task now. Use available skills if needed.",
            "Treat the stored task prompt as the work to perform once right now, not as instructions to create another schedule.",
            "Do not create or modify schedules unless the task instruction explicitly asks for scheduler management.",
            "Carry out the task instead of only describing a plan.",
            "",
            f"Task instruction: {record.get('task_prompt', '')}",
        ]
    )

    legacy_command = " ".join(
        part
        for part in [
            _clean_text(record.get("command")),
            _clean_text(record.get("arguments")),
        ]
        if part
    ).strip()
    if legacy_command:
        lines.extend(
            [
                "",
                f"Legacy command context: {legacy_command}",
            ]
        )

    lines.extend(
        [
            "",
            "After finishing, reply with a concise status update suitable for the chat.",
        ]
    )
    return "\n".join(lines).strip()


def claim_due_tasks(
    *,
    limit: int = 5,
    registry_path: str | Path | None = None,
) -> list[dict]:
    with REGISTRY_LOCK:
        now = _now()
        registry = _load_registry(registry_path)
        tasks = registry["tasks"]
        candidates = []

        for index, record in enumerate(tasks):
            if _bool(record.get("deleted", False)):
                continue

            if _bool(record.get("pending_now", False)):
                requested_at = _parse_dt(record.get("pending_requested_at", "")) or now
                candidates.append(("manual-request", requested_at, index))
                continue

            if _bool(record.get("completed", False)) or not _bool(record.get("enabled", False)):
                continue

            next_run = _parse_dt(record.get("next_run_at", ""))
            if next_run and next_run <= now:
                candidates.append(("scheduled", next_run, index))

        candidates.sort(key=lambda item: (0 if item[0] == "manual-request" else 1, item[1], item[2]))

        events = []
        claimed = False
        for trigger, scheduled_dt, index in candidates[: max(limit, 1)]:
            record = dict(tasks[index])
            record["pending_now"] = False
            record["pending_requested_at"] = ""
            record["last_dispatch_at"] = _iso(now)
            record["updated_at"] = _iso(now)

            if trigger == "scheduled":
                if record.get("schedule_type") == "once":
                    record["completed"] = True
                    record["enabled"] = False
                    record["next_run_at"] = ""
                else:
                    record["next_run_at"] = _iso(
                        _compute_next_occurrence(record, now, inclusive=False)
                    )

            normalized_record, _ = _normalize_record(record)
            tasks[index] = normalized_record
            claimed = True
            scheduled_for = _iso(scheduled_dt)
            events.append(
                {
                    "task_id": normalized_record.get("id", ""),
                    "task_name": normalized_record.get("task_name", ""),
                    "short_name": normalized_record.get("short_name", ""),
                    "trigger": trigger,
                    "scheduled_for": scheduled_for,
                    "task_prompt": normalized_record.get("task_prompt", ""),
                    "next_run_at": normalized_record.get("next_run_at", ""),
                    "dispatch_prompt": build_dispatch_prompt(
                        normalized_record,
                        trigger=trigger,
                        scheduled_for=scheduled_for,
                    ),
                }
            )

        if claimed:
            _save_registry(registry, registry_path)

        return events


def record_task_result(
    task_name: str,
    *,
    status: str,
    response_text: str = "",
    error_text: str = "",
    trigger: str = "",
    scheduled_for: str = "",
    registry_path: str | Path | None = None,
) -> dict | None:
    with REGISTRY_LOCK:
        now = _now()
        registry = _load_registry(registry_path)
        index = _find_task_index(registry["tasks"], task_name, include_deleted=True)
        if index is None:
            return None

        record = dict(registry["tasks"][index])
        record["last_run_at"] = _iso(now)
        record["last_status"] = _clean_text(status)
        record["last_response"] = response_text or ""
        record["last_error"] = error_text or ""
        record["last_trigger"] = trigger or ""
        record["last_scheduled_for"] = scheduled_for or ""
        record["updated_at"] = _iso(now)

        normalized_record, _ = _normalize_record(record)
        if _should_purge_record(normalized_record):
            registry["tasks"].pop(index)
        else:
            registry["tasks"][index] = normalized_record
        _save_registry(registry, registry_path)
        if _should_purge_record(normalized_record):
            return None
        return normalized_record


def run_schedule_skill(
    action: str,
    name: str = "",
    task_prompt: str = "",
    task: str = "",
    prompt: str = "",
    command: str = "",
    arguments: str = "",
    schedule_type: str = "",
    start_time: str = "",
    start_date: str = "",
    modifier=None,
    days_of_week=None,
    overwrite: bool = False,
    enabled: bool = True,
    include_deleted: bool = False,
    reason: str = "",
    registry_path: str | Path | None = None,
    **kwargs,
):
    normalized_action = _clean_text(action).lower()

    try:
        if normalized_action == "create":
            record = create_task(
                name=name,
                task_prompt=task_prompt,
                task=task,
                prompt=prompt,
                command=command,
                arguments=arguments,
                schedule_type=schedule_type,
                start_time=start_time,
                start_date=start_date,
                modifier=modifier,
                days_of_week=days_of_week,
                overwrite=overwrite,
                enabled=enabled,
                reason=reason,
                registry_path=registry_path,
                **kwargs,
            )
            return _ok(
                "create",
                "Scheduled task created",
                {"task": _present_task(record)},
                registry_path=registry_path,
            )

        if normalized_action == "get":
            record = get_task(name, include_deleted=include_deleted, registry_path=registry_path)
            return _ok(
                "get",
                "Scheduled task loaded",
                {"task": _present_task(record)},
                registry_path=registry_path,
            )

        if normalized_action == "list":
            tasks = list_tasks(include_deleted=include_deleted, registry_path=registry_path)
            return _ok(
                "list",
                f"Loaded {len(tasks)} managed task(s)",
                {"tasks": [_present_task(task) for task in tasks]},
                registry_path=registry_path,
            )

        if normalized_action == "run":
            record = queue_task_now(name, registry_path=registry_path)
            return _ok(
                "run",
                "Scheduled task queued for immediate dispatch",
                {
                    "task": _present_task(record),
                    "queued": True,
                },
                registry_path=registry_path,
            )

        if normalized_action == "enable":
            record = set_enabled(name, enabled=True, registry_path=registry_path)
            return _ok(
                "enable",
                "Scheduled task enabled",
                {"task": _present_task(record)},
                registry_path=registry_path,
            )

        if normalized_action == "disable":
            record = set_enabled(name, enabled=False, registry_path=registry_path)
            return _ok(
                "disable",
                "Scheduled task disabled",
                {"task": _present_task(record)},
                registry_path=registry_path,
            )

        if normalized_action == "delete":
            record = delete_task(name, reason=reason, registry_path=registry_path)
            return _ok(
                "delete",
                "Scheduled task deleted",
                {"task": _present_task(record)},
                registry_path=registry_path,
            )

        return _error(normalized_action or action, f"Unknown action: {action}", registry_path=registry_path)
    except Exception as exc:
        return _error(normalized_action or action, str(exc), registry_path=registry_path)
