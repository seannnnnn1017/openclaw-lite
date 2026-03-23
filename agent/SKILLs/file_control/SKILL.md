---
name: file-control
description: Read files and make full-file or targeted text edits through the external skill server
user-invocable: true
command-dispatch: tool
command-tool: file_tool
command-arg-mode: raw
metadata: { "openclaw": { "requires": { "bins": ["python"] } } }
---

Use this skill when the user wants to inspect a file, create a file, remove a file, overwrite full content, append content, or edit a specific text region inside an existing file.

This skill is selected by the agent and executed by the skill server.
When this skill is needed, reply with exactly one JSON object and nothing else.

Base JSON shape:

{"skill":"file-control","action":"<action>","args":{"path":"<target_path>"}}

Supported actions:
- `read`: return the full file content
- `create`: create an empty file if it does not exist
- `write`: overwrite the full file content
- `append`: append content to the end of the file
- `delete`: delete a file
- `replace_text`: replace matching text inside an existing file
- `insert_after`: insert text immediately after a matching text fragment
- `insert_before`: insert text immediately before a matching text fragment

Action arguments:
- Always provide `path`.
- For `write` and `append`, provide `content`.
- For `replace_text`, provide `target` and `new_text`.
- For `insert_after` and `insert_before`, provide `target` and `new_text`.
- `occurrence` is optional for text-targeted edits.

Occurrence rules:
- `occurrence` defaults to `1`.
- For `replace_text`, `occurrence: 0` means replace all matches.
- For `replace_text`, `insert_after`, and `insert_before`, any positive `occurrence` selects the nth match.
- If `occurrence` is outside the number of matches, the tool returns an error.

Behavior guidelines:
- Prefer `read` before targeted edits if the exact file content is uncertain.
- Prefer `replace_text`, `insert_after`, or `insert_before` over full `write` when the user asks for a localized change.
- Use `write` when the user clearly wants to replace the whole file.
- Use `append` only when the new content should be added to the end without modifying existing content.
- Use `delete` only when the user clearly asked to remove the file.
- If the required path, target text, or replacement text is missing, ask a clarifying question instead of guessing.

Matching rules:
- Text-targeted edits use exact substring matching.
- Matching is case-sensitive because it relies on direct string matching.
- If the target text is not found, the tool returns an error.

Path rules:
- `path` may be relative or absolute.
- If path resolution could be ambiguous, prefer an explicit path.

Result shape:
- The tool returns a JSON object with `status`, `action`, `path`, `message`, and `data`.
- Successful `read` returns file content in `data.content`.
- Successful text-edit actions return summary information such as match counts.
- Errors are returned as structured error objects; preserve them faithfully.

JSON examples:
- `{"skill":"file-control","action":"read","args":{"path":"worplace/test.py"}}`
- `{"skill":"file-control","action":"write","args":{"path":"notes/todo.txt","content":"hello world"}}`
- `{"skill":"file-control","action":"replace_text","args":{"path":"notes/todo.txt","target":"old","new_text":"new"}}`
- `{"skill":"file-control","action":"replace_text","args":{"path":"notes/todo.txt","target":"old","new_text":"new","occurrence":0}}`
- `{"skill":"file-control","action":"insert_after","args":{"path":"notes/todo.txt","target":"Title","new_text":"\n- item"}}`
- `{"skill":"file-control","action":"insert_before","args":{"path":"notes/todo.txt","target":"Footer","new_text":"Summary\n"}}`
