User request:
"把 E:\Github\Obsidian_database\personal_data_terminal 裡的所有 md 放到 notion page 33e5aafddb3b80daae72c72ecf916479，建一個叫 Personal Terminal 的父頁面"

Tool JSON:
{"skill":"notion-workflow","action":"import_folder","args":{"folder":"E:\\Github\\Obsidian_database\\personal_data_terminal","parent_page_id":"33e5aafddb3b80daae72c72ecf916479","parent_title":"Personal Terminal","pattern":"*.md"}}

User request:
"Import just these two files into Notion"

Tool JSON:
{"skill":"notion-workflow","action":"import_files","args":{"paths":["E:\\Github\\Obsidian_database\\personal_data_terminal\\Index.md","E:\\Github\\Obsidian_database\\personal_data_terminal\\架構.md"],"parent_page_id":"33e5aafddb3b80daae72c72ecf916479","parent_title":"Imported Files"}}

User request:
"Append new notes to this Notion page"

Tool JSON:
{"skill":"notion-workflow","action":"append_content","args":{"page_id":"<page_id>","content":"## New Section\n\nSome new content here."}}

User request:
"Sync the folder again but don't duplicate existing pages"

Tool JSON:
{"skill":"notion-workflow","action":"sync_folder","args":{"folder":"E:\\Github\\Obsidian_database\\personal_data_terminal","parent_page_id":"33e5aafddb3b80daae72c72ecf916479","parent_title":"Personal Terminal","pattern":"*.md"}}
