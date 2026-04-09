˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙˙Use these examples as canonical payload shapes for the current `notion-basic` bridge.

Important notes:
- `tools/list` is the source of truth for the live MCP API.
- The examples below are representative, not exhaustive.
- If a tool appears in `tools/list`, `tools/call` may use it even if that tool does not appear below.

Current live catalog snapshot observed on 2026-03-30:
- `API-get-user`
- `API-get-users`
- `API-get-self`
- `API-post-search`
- `API-get-block-children`
- `API-patch-block-children`
- `API-retrieve-a-block`
- `API-update-a-block`
- `API-delete-a-block`
- `API-retrieve-a-page`
- `API-patch-page`
- `API-post-page`
- `API-retrieve-a-page-property`
- `API-retrieve-a-comment`
- `API-create-a-comment`
- `API-query-data-source`
- `API-retrieve-a-data-source`
- `API-update-a-data-source`
- `API-create-a-data-source`
- `API-list-data-source-templates`
- `API-retrieve-a-database`
- `API-move-page`

Preferred high-level route for normal work:

User request:
"Create a Notion schedule entry for tomorrow at 10:00 titled 台北看房"

Tool JSON:
```json
{"skill":"notion-basic","action":"delegate_task","args":{"task":"Create one schedule entry in Notion for tomorrow at 10:00 with the title 台北看房.","context":{"database_id":"<preferred_schedule_database_id>","data_source_id":"<preferred_schedule_data_source_id>","timezone":"Asia/Taipei","user_intent":"calendar entry creation"}}}
```

User request:
"Search Notion for pages related to roadmap and summarize the result"

Tool JSON:
```json
{"skill":"notion-basic","action":"delegate_task","args":{"task":"Search Notion for pages whose title or content matches roadmap, then summarize the relevant results for the user.","context":{"query":"roadmap","object":"page","output":"brief summary"}}}
```

Low-level MCP route for explicit tool work:

User request:
"Show me the live Notion MCP tools"

Tool JSON:
```json
{"skill":"notion-basic","action":"tools/list","args":{}}
```

User request:
"Search Notion for pages named roadmap"

Tool JSON:
```json
{"skill":"notion-basic","action":"tools/call","args":{"name":"API-post-search","arguments":{"query":"roadmap","filter":{"property":"object","value":"page"},"page_size":10}}}
```

User request:
"Read this page"

Tool JSON:
```json
{"skill":"notion-basic","action":"tools/call","args":{"name":"API-retrieve-a-page","arguments":{"page_id":"<page_id>"}}}
```

User request:
"Read the child blocks of this block"

Tool JSON:
```json
{"skill":"notion-basic","action":"tools/call","args":{"name":"API-get-block-children","arguments":{"block_id":"<block_id>"}}}
```

User request:
"Read the schema for this data source"

Tool JSON:
```json
{"skill":"notion-basic","action":"tools/call","args":{"name":"API-retrieve-a-data-source","arguments":{"data_source_id":"<data_source_id>"}}}
```

User request:
"Query the first 20 rows from this data source"

Tool JSON:
```json
{"skill":"notion-basic","action":"tools/call","args":{"name":"API-query-data-source","arguments":{"data_source_id":"<data_source_id>","page_size":20}}}
```

User request:
"Create one schedule row for tomorrow at 10:00 in the built-in calendar"

Step 1 Tool JSON:
```json
{"skill":"notion-basic","action":"tools/call","args":{"name":"API-retrieve-a-data-source","arguments":{"data_source_id":"<preferred_schedule_data_source_id>"}}}
```

Step 2 Tool JSON:
```json
{"skill":"notion-basic","action":"tools/call","args":{"name":"API-post-page","arguments":{"parent":{"database_id":"<preferred_schedule_database_id>"},"properties":{"標題":{"title":[{"type":"text","text":{"content":"台北看房"}}]},"日期":{"date":{"start":"2026-03-31T10:00:00+08:00"}},"狀態":{"select":{"name":"未開始"}},"備註":{"rich_text":[{"type":"text","text":{"content":"明天上午十點看房"}}]}}}}}
```

User request:
"Mark this page as complete"

Tool JSON:
```json
{"skill":"notion-basic","action":"tools/call","args":{"name":"API-patch-page","arguments":{"page_id":"<page_id>","properties":{"狀態":{"select":{"name":"完成"}}}}}}
```

User request:
"Add a comment to this page"

Tool JSON:
```json
{"skill":"notion-basic","action":"tools/call","args":{"name":"API-create-a-comment","arguments":{"parent":{"page_id":"<page_id>"},"rich_text":[{"type":"text","text":{"content":"Hello MCP"}}]}}}
```

User request:
"Show workspace users"

Tool JSON:
```json
{"skill":"notion-basic","action":"tools/call","args":{"name":"API-get-users","arguments":{}}}
```

Anti-patterns to avoid:
- Do not do this:
```json
{"skill":"notion-basic","action":"tools/call","args":{"name":"tools/list","arguments":{}}}
```
Reason: `tools/list` is a skill action, not a live tool name.

- Do not do this:
```json
{"skill":"notion-basic","action":"tools/call","args":{"name":"API-post-page","arguments":{"database_id":"<database_id>","properties":{}}}}
```
Reason: `API-post-page` must place the parent under `parent.database_id`.

- Do not do this:
```json
{"skill":"notion-basic","action":"tools/call","args":{"name":"API-post-page","arguments":{"parent":{"database_id":"<database_id>"},"properties":{"標題":"台北看房"}}}}
```
Reason: use raw Notion property objects such as `title`, `date`, `select`, and `rich_text`.
