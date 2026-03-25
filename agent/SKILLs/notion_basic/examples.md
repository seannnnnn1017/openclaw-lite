User request:
"Where is the Notion item named hello?"

Tool JSON:
```json
{"skill":"notion-basic","action":"read_architecture_cache","args":{"lookup_title":"hello","object_type":"row"}}
```

User request:
"Sync the full Notion structure into local JSON"

Tool JSON:
```json
{"skill":"notion-basic","action":"sync_architecture","args":{"page_url":"https://www.notion.so/Claw-lite-32e5aafddb3b80a5a0ebc5d49ec41b5f","max_depth":4}}
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
"Mark this row as Done"

Tool JSON:
```json
{"skill":"notion-basic","action":"update_row","args":{"row_page_id":"32e5aafd-db3b-80a5-a0eb-c5d49ec41b5f","properties":{"Status":{"select":{"name":"Done"}}}}}
```

User request:
"Move this row to trash"

Tool JSON:
```json
{"skill":"notion-basic","action":"delete_row","args":{"row_page_id":"32e5aafd-db3b-80a5-a0eb-c5d49ec41b5f"}}
```
