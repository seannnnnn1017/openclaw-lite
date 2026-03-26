User request:
"Search Notion for dinner-related pages"

Tool JSON:
```json
{"skill":"notion-basic","action":"search","args":{"search_query":"Dinner","object_type":"page","page_size":10}}
```

User request:
"Read the configured default Notion page"

Tool JSON:
```json
{"skill":"notion-basic","action":"read_page","args":{}}
```

User request:
"Sync the configured default Notion page structure"

Tool JSON:
```json
{"skill":"notion-basic","action":"sync_architecture","args":{"max_depth":3}}
```

User request:
"Sync the full Notion structure live from Notion"

Tool JSON:
```json
{"skill":"notion-basic","action":"sync_architecture","args":{"page_url":"https://www.notion.so/Claw-lite-32e5aafddb3b80a5a0ebc5d49ec41b5f","max_depth":3}}
```

User request:
"Read the Claw-lite Notion page"

Tool JSON:
```json
{"skill":"notion-basic","action":"read_page","args":{"page_url":"https://www.notion.so/Claw-lite-32e5aafddb3b80a5a0ebc5d49ec41b5f"}}
```

User request:
"Create a Daily Summary page under the default parent page"

Tool JSON:
```json
{"skill":"notion-basic","action":"create_page","args":{"title":"Daily Summary","content":"# Daily Summary\n\n## Highlights\n\n- Item 1\n- Item 2"}}
```

User request:
"Upload this local screenshot into the Claw-lite Notion page"

Tool JSON:
```json
{"skill":"notion-basic","action":"upload_image","args":{"page_url":"https://www.notion.so/Claw-lite-32e5aafddb3b80a5a0ebc5d49ec41b5f","image_path":"assets/screenshot.png","caption":"Latest UI screenshot"}}
```

User request:
"Download the first image from this Notion page to local disk"

Tool JSON:
```json
{"skill":"notion-basic","action":"download_image","args":{"page_id":"32e5aafd-db3b-80a5-a0eb-c5d49ec41b5f","image_index":1}}
```

User request:
"Upload the Telegram-downloaded local photo into this Notion page"

Tool JSON:
```json
{"skill":"notion-basic","action":"upload_image","args":{"page_id":"32e5aafd-db3b-80a5-a0eb-c5d49ec41b5f","local_image_path":"agent/data/telegram_media/2026-03-25/chat_123/photo.png","caption":"User-provided local photo"}}
```

User request:
"Read this database schema"

Tool JSON:
```json
{"skill":"notion-basic","action":"read_database","args":{"database_id":"32e5aafd-db3b-807a-b2e5-c4c05c04b172"}}
```

User request:
"Query the first 20 rows from the Tasks database"

Tool JSON:
```json
{"skill":"notion-basic","action":"query_database","args":{"database_id":"32e5aafd-db3b-807a-b2e5-c4c05c04b172","page_size":20}}
```

User request:
"Create a Bugs data source under this database"

Tool JSON:
```json
{"skill":"notion-basic","action":"create_data_source","args":{"database_id":"32e5aafd-db3b-807a-b2e5-c4c05c04b172","title":"Bugs","properties":{"Name":{"title":{}},"Severity":{"select":{"options":[{"name":"High","color":"red"},{"name":"Medium","color":"orange"},{"name":"Low","color":"yellow"}]}}}}}
```

User request:
"Add a Priority field to this data source"

Tool JSON:
```json
{"skill":"notion-basic","action":"update_data_source","args":{"data_source_id":"32e5aafd-db3b-807a-b2e5-c4c05c04b172","properties":{"Priority":{"select":{"options":[{"name":"P0","color":"red"},{"name":"P1","color":"orange"},{"name":"P2","color":"yellow"}]}}}}}
```

User request:
"Create a task row named Fix Telegram reconnect"

Tool JSON:
```json
{"skill":"notion-basic","action":"create_row","args":{"data_source_id":"32e5aafd-db3b-807a-b2e5-c4c05c04b172","title":"Fix Telegram reconnect","properties":{"Status":{"select":{"name":"Doing"}}}}}
```

User request:
"Create a calendar row for a client call from 2026-03-26 14:30 to 15:00 Taipei time"

Tool JSON:
```json
{"skill":"notion-basic","action":"create_row","args":{"data_source_id":"32e5aafd-db3b-807a-b2e5-c4c05c04b172","title":"Client call","properties":{"Date":{"date":{"start":"2026-03-26T14:30:00+08:00","end":"2026-03-26T15:00:00+08:00"}}}}}
```

User request:
"Create a calendar row using the simpler date shorthand"

Tool JSON:
```json
{"skill":"notion-basic","action":"create_row","args":{"data_source_id":"32e5aafd-db3b-807a-b2e5-c4c05c04b172","title":"Client call","properties":{"Date":{"start":"2026-03-26T14:30:00+08:00","end":"2026-03-26T15:00:00+08:00"},"Status":"Doing"}}}
```

User request:
"Mark this row as Done"

Tool JSON:
```json
{"skill":"notion-basic","action":"update_row","args":{"row_page_id":"32e5aafd-db3b-80a5-a0eb-c5d49ec41b5f","properties":{"Status":{"select":{"name":"Done"}}}}}
```

User request:
"Update this row's Date field to a single start time at 2026-03-26 16:45 in Asia/Taipei"

Tool JSON:
```json
{"skill":"notion-basic","action":"update_row","args":{"row_page_id":"32e5aafd-db3b-80a5-a0eb-c5d49ec41b5f","properties":{"Date":{"date":{"start":"2026-03-26T16:45:00","time_zone":"Asia/Taipei"}}}}}
```

User request:
"Update this row's Date field using a date array shorthand"

Tool JSON:
```json
{"skill":"notion-basic","action":"update_row","args":{"row_page_id":"32e5aafd-db3b-80a5-a0eb-c5d49ec41b5f","properties":{"Date":["2026-03-26T16:45:00+08:00","2026-03-26T18:00:00+08:00"]}}}
```

User request:
"Move this row to trash"

Tool JSON:
```json
{"skill":"notion-basic","action":"delete_row","args":{"row_page_id":"32e5aafd-db3b-80a5-a0eb-c5d49ec41b5f"}}
```
