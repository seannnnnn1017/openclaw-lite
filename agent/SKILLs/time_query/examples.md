# Examples for time-query skill

## Example 1: Ask for the local current time

User request:
`現在幾點`

Agent skill JSON:
```json
{
  "skill": "time-query",
  "action": "now",
  "args": {
    "timezone": "local"
  }
}
```

## Example 2: Ask for the current time in Taipei

User request:
`台北現在幾點`

Agent skill JSON:
```json
{
  "skill": "time-query",
  "action": "now",
  "args": {
    "timezone": "Asia/Taipei"
  }
}
```

## Example 3: Compare multiple current times

User request:
`幫我看一下台北、東京、紐約現在時間`

Agent skill JSON:
```json
{
  "skill": "time-query",
  "action": "now",
  "args": {
    "timezones": [
      "Asia/Taipei",
      "Asia/Tokyo",
      "America/New_York"
    ]
  }
}
```

## Example 4: Convert a naive datetime between timezones

User request:
`把 2026-03-24 14:30 的台北時間換成 UTC`

Agent skill JSON:
```json
{
  "skill": "time-query",
  "action": "convert",
  "args": {
    "datetime_text": "2026-03-24 14:30",
    "from_timezone": "Asia/Taipei",
    "to_timezone": "UTC"
  }
}
```

## Example 5: Convert a datetime that already includes an offset

User request:
`把 2026-03-24T14:30:00+08:00 轉成紐約時間`

Agent skill JSON:
```json
{
  "skill": "time-query",
  "action": "convert",
  "args": {
    "datetime_text": "2026-03-24T14:30:00+08:00",
    "to_timezone": "America/New_York"
  }
}
```
