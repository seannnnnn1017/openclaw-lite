# workspace-context Examples

## Example 1: check path before file operation

User: 幫我讀一下記憶檔案

Agent first confirms path context:
{"skill":"workspace-context","action":"info","args":{}}

Result:
{"status":"ok","action":"info","data":{"cwd":"/project","agent_dir":"/project/agent","memories_dir":"/project/agent/data/memories",...}}

Agent then reads the correct path:
{"skill":"file-control","action":"read","args":{"path":"agent/data/memories/MEMORY.md"}}

## Example 2: explicit path query

User: 你現在的執行目錄是哪裡？

{"skill":"workspace-context","action":"info","args":{}}
