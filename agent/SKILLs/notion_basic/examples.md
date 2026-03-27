Use these examples as canonical raw payload shapes for the current `notion-basic` bridge.

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
"Read this database"

Tool JSON:
```json
{"skill":"notion-basic","action":"tools/call","args":{"name":"API-retrieve-a-database","arguments":{"database_id":"dca9bd99-bf81-412b-9978-6996c72c5a37"}}}
```

User request:
"Read the schema for this data source"

Tool JSON:
```json
{"skill":"notion-basic","action":"tools/call","args":{"name":"API-retrieve-a-data-source","arguments":{"data_source_id":"f199688f-e08a-48b5-a0db-f1e4b683dae4"}}}
```

User request:
"Query the first 20 rows from this data source"

Tool JSON:
```json
{"skill":"notion-basic","action":"tools/call","args":{"name":"API-query-data-source","arguments":{"data_source_id":"f199688f-e08a-48b5-a0db-f1e4b683dae4","page_size":20}}}
```

User request:
"Create one schedule row for tomorrow at 10:00 in the built-in calendar"

Step 1 Tool JSON:
```json
{"skill":"notion-basic","action":"tools/call","args":{"name":"API-retrieve-a-data-source","arguments":{"data_source_id":"f199688f-e08a-48b5-a0db-f1e4b683dae4"}}}
```

Step 2 Tool JSON:
```json
{"skill":"notion-basic","action":"tools/call","args":{"name":"API-post-page","arguments":{"parent":{"database_id":"dca9bd99-bf81-412b-9978-6996c72c5a37"},"properties":{"標題":{"title":[{"type":"text","text":{"content":"明天早上十點去台北看房"}}]},"日期":{"date":{"start":"2026-03-28T10:00:00+08:00"}},"狀態":{"select":{"name":"未開始"}},"備註":{"rich_text":[{"type":"text","text":{"content":"去台北看房"}}]}}}}}
```

User request:
"Create one all-day schedule row in the built-in calendar"

Tool JSON:
```json
{"skill":"notion-basic","action":"tools/call","args":{"name":"API-post-page","arguments":{"parent":{"database_id":"dca9bd99-bf81-412b-9978-6996c72c5a37"},"properties":{"標題":{"title":[{"type":"text","text":{"content":"週五請假"}}]},"日期":{"date":{"start":"2026-03-27"}},"狀態":{"select":{"name":"未開始"}}}}}}
```

User request:
"Update a page property"

Tool JSON:
```json
{"skill":"notion-basic","action":"tools/call","args":{"name":"API-patch-page","arguments":{"page_id":"3305aafd-db3b-8171-9287-cab75bcb8083","properties":{"狀態":{"select":{"name":"完成"}}}}}}
```

User request:
"Move this page under another parent"

Tool JSON:
```json
{"skill":"notion-basic","action":"tools/call","args":{"name":"API-move-page","arguments":{"page_id":"32e5aafd-db3b-80a5-a0eb-c5d49ec41b5f","parent":{"page_id":"32e5aafd-db3b-80a5-a0eb-c5d49ec41b5f"}}}}
```

Anti-patterns to avoid:
- Do not do this:
```json
{"skill":"notion-basic","action":"tools/call","args":{"name":"tools/list","arguments":{}}}
```
Reason: `tools/list` is a skill action, not a live tool name.

- Do not do this:
```json
{"skill":"notion-basic","action":"tools/call","args":{"name":"API-post-page","arguments":{"database_id":"dca9bd99-bf81-412b-9978-6996c72c5a37","properties":{}}}}
```
Reason: `API-post-page` must place the parent under `parent.database_id`.

- Do not do this:
```json
{"skill":"notion-basic","action":"tools/call","args":{"name":"API-post-page","arguments":{"parent":{"database_id":"dca9bd99-bf81-412b-9978-6996c72c5a37"},"properties":{"標題":"明天早上十點去台北看房"}}}}
```
Reason: use raw Notion property objects such as `title`, `date`, `select`, and `rich_text`.
