import re
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    ZoneInfo = None

    class ZoneInfoNotFoundError(Exception):
        pass


TIMEZONE_ALIASES = {
    "local": "local",
    "system": "local",
    "here": "local",
    "utc": "UTC",
    "gmt": "UTC",
    "z": "UTC",
    "taipei": "Asia/Taipei",
    "taiwan": "Asia/Taipei",
    "台北": "Asia/Taipei",
    "台灣": "Asia/Taipei",
    "tokyo": "Asia/Tokyo",
    "東京": "Asia/Tokyo",
    "japan": "Asia/Tokyo",
    "shanghai": "Asia/Shanghai",
    "beijing": "Asia/Shanghai",
    "上海": "Asia/Shanghai",
    "北京": "Asia/Shanghai",
    "singapore": "Asia/Singapore",
    "london": "Europe/London",
    "倫敦": "Europe/London",
    "paris": "Europe/Paris",
    "巴黎": "Europe/Paris",
    "new york": "America/New_York",
    "newyork": "America/New_York",
    "紐約": "America/New_York",
    "los angeles": "America/Los_Angeles",
    "losangeles": "America/Los_Angeles",
    "la": "America/Los_Angeles",
}

FIXED_TIMEZONE_FALLBACKS = {
    "Asia/Taipei": timezone(timedelta(hours=8), "Asia/Taipei"),
    "Asia/Tokyo": timezone(timedelta(hours=9), "Asia/Tokyo"),
    "Asia/Shanghai": timezone(timedelta(hours=8), "Asia/Shanghai"),
    "Asia/Singapore": timezone(timedelta(hours=8), "Asia/Singapore"),
    "UTC": timezone.utc,
}

COMMON_DATETIME_FORMATS = [
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
    "%Y/%m/%d",
]


def ok(action: str, message: str, data=None):
    return {
        "status": "ok",
        "action": action,
        "path": "",
        "message": message,
        "data": data or {},
    }


def error(action: str, message: str, data=None):
    return {
        "status": "error",
        "action": action,
        "path": "",
        "message": message,
        "data": data,
    }


def _format_offset(offset: timedelta | None) -> str:
    if offset is None:
        return ""

    total_seconds = int(offset.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    total_seconds = abs(total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    return f"{sign}{hours:02d}:{minutes:02d}"


def _local_timezone():
    local_dt = datetime.now().astimezone()
    label = local_dt.tzname() or "local"
    return local_dt.tzinfo, label


def _parse_utc_offset(raw_value: str):
    match = re.fullmatch(r"([+-])(\d{1,2})(?::?(\d{2}))?", raw_value.strip())
    if not match:
        return None

    sign, hours_text, minutes_text = match.groups()
    hours = int(hours_text)
    minutes = int(minutes_text or "0")
    if hours > 23 or minutes > 59:
        raise ValueError(f"Invalid UTC offset: {raw_value}")

    delta = timedelta(hours=hours, minutes=minutes)
    if sign == "-":
        delta = -delta

    return timezone(delta, _format_offset(delta))


def _resolve_timezone(raw_value: str | None):
    cleaned = str(raw_value or "").strip()
    if not cleaned:
        return _local_timezone()

    normalized = TIMEZONE_ALIASES.get(cleaned.casefold(), cleaned)
    if normalized == "local":
        return _local_timezone()
    if normalized == "UTC":
        return timezone.utc, "UTC"

    explicit_offset = _parse_utc_offset(normalized)
    if explicit_offset is not None:
        return explicit_offset, explicit_offset.tzname(None) or cleaned

    if ZoneInfo is not None:
        try:
            return ZoneInfo(normalized), normalized
        except ZoneInfoNotFoundError:
            pass

    fallback = FIXED_TIMEZONE_FALLBACKS.get(normalized)
    if fallback is not None:
        return fallback, normalized

    raise ValueError(
        f"Unsupported timezone: {cleaned}. Use an IANA timezone such as Asia/Taipei or an explicit UTC offset."
    )


def _normalize_timezone_list(timezone_value: str = "", timezones=None) -> list[str]:
    values: list[str] = []

    if isinstance(timezones, str):
        values.extend(part.strip() for part in timezones.split(",") if part.strip())
    elif isinstance(timezones, list):
        for item in timezones:
            text = str(item).strip()
            if text:
                values.append(text)
    elif timezones not in (None, ""):
        raise ValueError("timezones must be a list, a comma-separated string, or omitted")

    if str(timezone_value or "").strip():
        values.insert(0, str(timezone_value).strip())

    deduped: list[str] = []
    seen = set()
    for item in values or ["local"]:
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def _serialize_datetime(dt: datetime, requested_timezone: str, resolved_timezone: str) -> dict:
    return {
        "requested_timezone": requested_timezone or resolved_timezone,
        "timezone": resolved_timezone,
        "timezone_name": dt.tzname() or resolved_timezone,
        "datetime": dt.isoformat(timespec="seconds"),
        "date": dt.date().isoformat(),
        "time": dt.strftime("%H:%M:%S"),
        "weekday": dt.strftime("%A"),
        "utc_offset": _format_offset(dt.utcoffset()),
    }


def _parse_datetime_text(datetime_text: str) -> datetime:
    cleaned = str(datetime_text or "").strip()
    if not cleaned:
        raise ValueError("Missing datetime_text")

    normalized = cleaned[:-1] + "+00:00" if cleaned.endswith("Z") else cleaned

    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        pass

    for fmt in COMMON_DATETIME_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue

    raise ValueError(
        "Unsupported datetime_text format. Use ISO-like values such as 2026-03-24 14:30 or 2026-03-24T14:30:00+08:00."
    )


def _current_time_payload(timezone_value: str = "", timezones=None):
    targets = _normalize_timezone_list(timezone_value=timezone_value, timezones=timezones)
    results = []
    for requested in targets:
        tzinfo, resolved = _resolve_timezone(requested)
        results.append(
            _serialize_datetime(
                datetime.now(tzinfo),
                requested_timezone=requested,
                resolved_timezone=resolved,
            )
        )

    payload = {
        "query_type": "now",
        "count": len(results),
        "results": results,
    }
    if results:
        payload.update(results[0])
    return payload


def _convert_time_payload(datetime_text: str, from_timezone: str = "", to_timezone: str = ""):
    if not to_timezone:
        raise ValueError("Missing to_timezone")

    parsed = _parse_datetime_text(datetime_text)
    target_tz, target_label = _resolve_timezone(to_timezone)

    if parsed.tzinfo is None:
        if not from_timezone:
            raise ValueError("Missing from_timezone for a datetime without timezone information")
        source_tz, source_label = _resolve_timezone(from_timezone)
        source_dt = parsed.replace(tzinfo=source_tz)
    else:
        source_dt = parsed
        source_label = from_timezone.strip() or (source_dt.tzname() or _format_offset(source_dt.utcoffset()))

    target_dt = source_dt.astimezone(target_tz)
    return {
        "query_type": "convert",
        "input": datetime_text,
        "from_timezone": source_label,
        "to_timezone": target_label,
        "source": _serialize_datetime(
            source_dt,
            requested_timezone=from_timezone or source_label,
            resolved_timezone=source_label,
        ),
        "target": _serialize_datetime(
            target_dt,
            requested_timezone=to_timezone,
            resolved_timezone=target_label,
        ),
        "source_datetime": source_dt.isoformat(timespec="seconds"),
        "target_datetime": target_dt.isoformat(timespec="seconds"),
    }


def run(
    action: str,
    timezone: str = "",
    timezones=None,
    datetime_text: str = "",
    from_timezone: str = "",
    to_timezone: str = "",
    **kwargs,
):
    try:
        if action == "now":
            payload = _current_time_payload(timezone_value=timezone, timezones=timezones)
            message = f"Returned current time for {payload['count']} timezone(s)"
            return ok(action=action, message=message, data=payload)

        if action == "convert":
            payload = _convert_time_payload(
                datetime_text=datetime_text,
                from_timezone=from_timezone,
                to_timezone=to_timezone,
            )
            message = f"Converted time from {payload['from_timezone']} to {payload['to_timezone']}"
            return ok(action=action, message=message, data=payload)

        return error(action=action, message=f"Unknown action: {action}")
    except Exception as exc:
        return error(action=action, message=str(exc))
