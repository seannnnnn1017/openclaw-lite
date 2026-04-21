---
name: schedule-task
description: Create and manage agent-native scheduled tasks that only handle timing and send a stored natural-language task back into the agent for execution while the agent is open
user-invocable: true
command-dispatch: tool
command-tool: schedule_tool
command-arg-mode: raw
metadata: { "openclaw": { "requires": { "bins": ["python"] } } }
---

Use this skill when the user wants the agent to do something later, do it repeatedly on a schedule, inspect existing agent-managed schedules, pause or resume them, trigger one immediately, or delete them.

This is an agent-native scheduler, not Windows Task Scheduler.

Important behavior:
- Check the time zone of the agent's host environment and clarify if the user expresses a schedule in relative time words such as `today`, `tomorrow`, `day after tomorrow`, or Chinese equivalents. Resolve those words to actual dates before creating the schedule, preferably by calling `time-query.now` first.
- Scheduled tasks only run while the agent process is open.
- The tool only stores timing and task metadata.
- When a task is due, the scheduler sends the stored `task_prompt` back into the agent.
- The agent then decides how to execute it, including calling `file-control` or other skills.
- Deleted tasks and completed one-time tasks are purged from the registry JSON instead of being kept as historical records.
- When Telegram bridge delivery targets are available, scheduled-task system/tool output and the final answer are sent to Telegram as well as the terminal.
- If the user needs tasks to keep running after the agent is closed, this skill is not enough.

This skill is selected by the agent and executed by the skill server.
When this skill is needed, reply with exactly one JSON object and nothing else.

Base JSON shape:

{"skill":"schedule-task","action":"<action>","args":{"name":"<task-name>"}}

Supported actions:
- `create`: create or overwrite an agent-managed scheduled task
- `get`: inspect one scheduled task
- `list`: list scheduled tasks created through this skill
- `run`: queue one scheduled task for immediate dispatch back into the agent
- `enable`: enable a disabled scheduled task
- `disable`: disable a scheduled task
- `delete`: delete a scheduled task

Task naming rules:
- Always provide `name`.
- `name` is an agent-local task ID.
- Keep names stable so the agent can enable, disable, run, or delete the same task later.

Create arguments:
- Always provide `name`, `task_prompt`, `schedule_type`, and `start_time`.
- `task_prompt` must describe only the job to perform when the task fires.
- Do not repeat recurrence, dates, clock times, or schedule phrases inside `task_prompt`.
- Good: `task_prompt: "In Notion database (ID: ...) create a page about an advanced algorithm. Randomly choose one topic each run and fill in the title and content."`
- Bad: `task_prompt: "Every five minutes in Notion database (ID: ...) create a page about an advanced algorithm."`
- Supported `schedule_type` values are: `once`, `daily`, `weekly`, `minute`, `hourly`.
- `start_date` is required for `once`. For recurring schedules it is optional and defaults to today.
- `modifier` is optional. For `minute` it means every N minutes. For `hourly` it means every N hours. For `daily` it means every N days. For `weekly` it means every N weeks.
- `days_of_week` is required for `weekly`. Use `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, `SUN`, full English names, or an array of those values.
- `overwrite` is optional and defaults to `false`.
- `enabled` is optional and defaults to `true`.
- `reason` is strongly recommended for `create` and `delete`.

Behavior guidelines:
- Ask a clarifying question if the task, date, time, interval, or weekly days are missing or ambiguous.
- When the user expresses a schedule with relative time words such as `today`, `tomorrow`, `day after tomorrow`, or Chinese equivalents, resolve them against the actual current local time first, preferably by calling `time-query.now` before creating the schedule.
- Strip schedule wording such as `every five minutes`, `daily at 21:00`, `tomorrow at 09:45`, or `next Monday` out of `task_prompt` and keep only the work instruction.
- Write `task_prompt` so the future agent can execute it directly without extra context.
- Prefer concrete task language such as file names, output locations, target page IDs, or expected result format.
- Use `list` or `get` if the exact task name is uncertain.
- Use `enable` or `disable` when the user wants to pause or resume a schedule without removing it.
- Use `run` when the user wants the same stored task dispatched right away in the current chat session.
- Do not treat `run` as a direct tool execution. It only queues the task for the scheduler to send back into the agent.
- Avoid scheduling destructive work unless the user explicitly requested it.

Result shape:
- The tool returns a JSON object with `status`, `action`, `path`, `message`, and `data`.
- Successful `create`, `get`, `enable`, `disable`, and `delete` return a `task` object with scheduling metadata.
- Successful `run` returns the task plus `queued: true`.
- Successful `list` returns only tasks that still exist in the registry.
- Tasks report `runner: "agent-dispatch"` and `requires_agent_running: true`.
- Errors are returned as structured error objects; preserve them faithfully.

JSON examples:
- `{"skill":"schedule-task","action":"create","args":{"name":"hourly-time-file","task_prompt":"Create a .txt file containing the current timestamp and report the result in chat.","schedule_type":"hourly","start_time":"00:00","modifier":1,"overwrite":true,"reason":"Create a timestamped text file every hour through the agent"}}`
- `{"skill":"schedule-task","action":"create","args":{"name":"daily-summary","task_prompt":"Summarize the new key items since the previous run and reply in chat.","schedule_type":"daily","start_time":"21:00","overwrite":true,"reason":"Send a daily summary each night"}}`
- `{"skill":"schedule-task","action":"create","args":{"name":"weekly-cleanup","task_prompt":"Delete temporary files older than seven days from the logs folder and report the result.","schedule_type":"weekly","start_time":"23:30","days_of_week":["SAT"],"modifier":1,"overwrite":true,"reason":"Run weekly cleanup through the agent"}}`
- `{"skill":"schedule-task","action":"get","args":{"name":"hourly-time-file"}}`
- `{"skill":"schedule-task","action":"list","args":{}}`
- `{"skill":"schedule-task","action":"run","args":{"name":"hourly-time-file"}}`
- `{"skill":"schedule-task","action":"delete","args":{"name":"hourly-time-file","reason":"Remove the old hourly task"}}`
