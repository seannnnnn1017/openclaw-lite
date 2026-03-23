# Examples for schedule-task skill

## Example 1: Create an hourly task that lets the agent use file-control

User request:
`每小時新增一個當前時間的.txt`

Agent skill JSON:
```json
{
  "skill": "schedule-task",
  "action": "create",
  "args": {
    "name": "hourly-time-file",
    "task_prompt": "每小時新增一個當前時間的.txt，檔名使用目前本地時間，並在聊天室回報建立結果。",
    "schedule_type": "hourly",
    "start_time": "00:00",
    "modifier": 1,
    "overwrite": true,
    "reason": "Create a timestamped text file every hour through the agent"
  }
}
```

## Example 2: Create a per-minute prompt for chat output

User request:
`每分鐘生成一句立志英文短句，直接顯示在聊天室`

Agent skill JSON:
```json
{
  "skill": "schedule-task",
  "action": "create",
  "args": {
    "name": "minute-motivation",
    "task_prompt": "生成一句簡短的立志英文短句，直接回覆在聊天室。",
    "schedule_type": "minute",
    "start_time": "00:00",
    "modifier": 1,
    "overwrite": true,
    "reason": "Send a short motivational English line every minute"
  }
}
```

## Example 3: Create a weekly maintenance task

User request:
`每週六晚上 11:30 清理 logs 資料夾，完成後回報`

Agent skill JSON:
```json
{
  "skill": "schedule-task",
  "action": "create",
  "args": {
    "name": "weekly-log-cleanup",
    "task_prompt": "每週六清理 logs 資料夾中七天前的臨時檔，完成後回報結果。",
    "schedule_type": "weekly",
    "start_time": "23:30",
    "days_of_week": [
      "SAT"
    ],
    "modifier": 1,
    "overwrite": true,
    "reason": "Run weekly log cleanup through the agent"
  }
}
```

## Example 4: Create a one-time task

User request:
`明天晚上 9:45 幫我建立一次 reminder.txt`

Agent skill JSON:
```json
{
  "skill": "schedule-task",
  "action": "create",
  "args": {
    "name": "one-time-reminder-file",
    "task_prompt": "建立一個 reminder.txt，並在聊天室回報位置與結果。",
    "schedule_type": "once",
    "start_date": "2026-03-24",
    "start_time": "21:45",
    "reason": "Create the requested reminder file once"
  }
}
```

## Example 5: Inspect one task

User request:
`Show me the details for hourly-time-file`

Agent skill JSON:
```json
{
  "skill": "schedule-task",
  "action": "get",
  "args": {
    "name": "hourly-time-file"
  }
}
```

## Example 6: List managed tasks

User request:
`What scheduled agent tasks do you have right now?`

Agent skill JSON:
```json
{
  "skill": "schedule-task",
  "action": "list",
  "args": {}
}
```

## Example 7: Trigger one task right now

User request:
`現在先執行一次 hourly-time-file`

Agent skill JSON:
```json
{
  "skill": "schedule-task",
  "action": "run",
  "args": {
    "name": "hourly-time-file"
  }
}
```
``run`` queues the stored task for immediate dispatch. The actual work still happens when the scheduler sends that task back into the agent.

## Example 8: Disable a task

User request:
`先暫停 minute-motivation`

Agent skill JSON:
```json
{
  "skill": "schedule-task",
  "action": "disable",
  "args": {
    "name": "minute-motivation"
  }
}
```

## Example 9: Delete a task

User request:
`刪掉舊的 hourly-time-file`

Agent skill JSON:
```json
{
  "skill": "schedule-task",
  "action": "delete",
  "args": {
    "name": "hourly-time-file",
    "reason": "Remove the old hourly task"
  }
}
```
