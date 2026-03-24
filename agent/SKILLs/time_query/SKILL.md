---
name: time-query
description: Query the current date and time for the local system or a specified timezone, compare current times across multiple timezones, and convert explicit datetime values between timezones through the external skill server
user-invocable: true
command-dispatch: tool
command-tool: time_tool
command-arg-mode: raw
metadata: { "openclaw": { "requires": { "bins": ["python"] } } }
---

Use this skill when the user asks what time it is now, what date it is today, what time it is in another timezone or city, wants multiple current times compared, or wants a provided datetime converted between timezones.

This skill is selected by the agent and executed by the skill server.
When this skill is needed, reply with exactly one JSON object and nothing else.

Base JSON shape:

{"skill":"time-query","action":"<action>","args":{}}

Supported actions:
- `now`: return the current date and time for one or more timezones
- `convert`: convert a provided datetime from one timezone to another

`now` arguments:
- `timezone` is optional for a single timezone query
- `timezones` is optional for a multi-timezone query and may be an array or comma-separated string
- If both are omitted, default to the local system timezone

`convert` arguments:
- Always provide `datetime_text`
- Always provide `to_timezone`
- Provide `from_timezone` when `datetime_text` does not already include a timezone offset

Timezone rules:
- Prefer canonical IANA timezone names such as `Asia/Taipei`, `Asia/Tokyo`, `America/New_York`, or `Europe/London`
- `local`, `system`, and `here` all mean the local system timezone
- `UTC` and explicit offsets such as `+08:00` are supported
- Common city aliases such as `Taipei`, `Tokyo`, and `New York` are also supported

Behavior guidelines:
- Use `now` for "what time is it" and "today's date" style questions
- Use `now` with `timezones` when the user asks to compare several cities or timezones at once
- Use `convert` only when the user supplied a specific datetime that needs conversion
- Ask a clarifying question if the source timezone is missing for a naive datetime such as `2026-03-24 09:00`
- Ask a clarifying question if the location name is ambiguous
- Prefer exact timezone names over guessing when the user names a broad region

Result shape:
- The tool returns a JSON object with `status`, `action`, `message`, and `data`
- Successful `now` returns `data.results`, each with timezone, ISO datetime, date, time, weekday, and UTC offset
- Successful single-timezone `now` also mirrors the first result at the top level of `data`
- Successful `convert` returns both the source and converted datetime values, including timezone and UTC offset details
- Errors are returned as structured error objects; preserve them faithfully

JSON examples:
- `{"skill":"time-query","action":"now","args":{"timezone":"local"}}`
- `{"skill":"time-query","action":"now","args":{"timezone":"Asia/Taipei"}}`
- `{"skill":"time-query","action":"now","args":{"timezones":["Asia/Taipei","Asia/Tokyo","UTC"]}}`
- `{"skill":"time-query","action":"convert","args":{"datetime_text":"2026-03-24 14:30","from_timezone":"Asia/Taipei","to_timezone":"UTC"}}`
- `{"skill":"time-query","action":"convert","args":{"datetime_text":"2026-03-24T14:30:00+08:00","to_timezone":"America/New_York"}}`
