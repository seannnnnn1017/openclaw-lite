Use these examples as canonical payload shapes for `notion-schedule`.

Important notes:
- `tools/list` is the source of truth for the live MCP API.
- Always use exact property names from the live schema.
- `data_source_id` and `database_id` come from the user's memory topics — not from this file.

---

## List live tools

{"skill":"notion-schedule","action":"tools/list","args":{}}

---

## Get schedule database schema

{
  "skill": "notion-schedule",
  "action": "tools/call",
  "args": {
    "name": "API-retrieve-a-database",
    "arguments": {
      "database_id": "<schedule_database_id>"
    }
  }
}

Then read `data_sources[].id` from the result to get `data_source_id`.

---

## Query schedule entries (by date range)

{
  "skill": "notion-schedule",
  "action": "tools/call",
  "args": {
    "name": "API-query-data-source",
    "arguments": {
      "data_source_id": "<schedule_data_source_id>",
      "filter": {
        "property": "日期",
        "date": {
          "on_or_after": "2026-04-12",
          "on_or_before": "2026-04-19"
        }
      }
    }
  }
}

---

## Create a schedule entry

{
  "skill": "notion-schedule",
  "action": "tools/call",
  "args": {
    "name": "API-post-page",
    "arguments": {
      "parent": {
        "database_id": "<schedule_database_id>"
      },
      "properties": {
        "名稱": {
          "title": [{ "text": { "content": "台北看房" } }]
        },
        "日期": {
          "date": {
            "start": "2026-04-13T10:00:00+08:00",
            "end": "2026-04-13T11:00:00+08:00"
          }
        }
      }
    }
  }
}

---

## Update a schedule entry

{
  "skill": "notion-schedule",
  "action": "tools/call",
  "args": {
    "name": "API-patch-page",
    "arguments": {
      "page_id": "<page_id_of_entry>",
      "properties": {
        "日期": {
          "date": {
            "start": "2026-04-14T14:00:00+08:00"
          }
        }
      }
    }
  }
}

---

## Delete (archive) a schedule entry

{
  "skill": "notion-schedule",
  "action": "tools/call",
  "args": {
    "name": "API-patch-page",
    "arguments": {
      "page_id": "<page_id_of_entry>",
      "archived": true
    }
  }
}
