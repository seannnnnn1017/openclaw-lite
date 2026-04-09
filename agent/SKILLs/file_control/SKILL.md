---
name: file-control
description: Read text files and local images, edit files safely with backups, and restore previous versions through the external skill server
user-invocable: true
command-dispatch: tool
command-tool: file_tool
command-arg-mode: raw
metadata: { "openclaw": { "requires": { "bins": ["python"] } } }
---

Use this skill when the user wants to inspect a text file or local image, create a file, overwrite content, append content, delete a file, make targeted text edits, or restore a previous file state.

This skill is selected by the agent and executed by the skill server.
When this skill is needed, reply with exactly one JSON object and nothing else.

Base JSON shape:

{"skill":"file-control","action":"<action>","args":{"path":"<target_path>"}}

Supported actions:
- `read`: return the full text file content, or read a local image file so it can be attached back to the model
- `create`: create an empty file if it does not exist
- `write`: overwrite the full file content
- `append`: append content to the end of the file
- `delete`: delete a file
- `replace_text`: replace matching text inside an existing file
- `insert_after`: insert text immediately after a matching text fragment
- `insert_before`: insert text immediately before a matching text fragment
- `restore`: restore a previous file state from a backup ID

Backup behavior:
- Every mutating action creates a backup record before the change is applied.
- Mutating actions are: `create`, `write`, `append`, `delete`, `replace_text`, `insert_after`, `insert_before`.
- Backups are recorded in `agent/SKILLs/file_control/scripts/temporary_data/file_ID.json`.
- Backup files are stored under `agent/SKILLs/file_control/scripts/temporary_data/backups/`.
- The tool returns a `backup_id` for every successful mutating action.
- Use `restore` with that `backup_id` to undo the change.
- Backup files are persistent and are not deleted automatically.
- Do not delete or prune backup files as part of normal file-control operations.
- Backup storage is outside normal file-control scope and should not be modified by this skill.
- If the agent targets `agent/SKILLs/file_control/scripts/temporary_data/`, the tool should return permission denied.

Action arguments:
- Always provide `path` for file-based actions.
- For `write` and `append`, provide `content`.
- For `replace_text`, provide `target` and `new_text`.
- For `insert_after` and `insert_before`, provide `target` and `new_text`.
- For `restore`, provide `backup_id`.
- `occurrence` is optional for text-targeted edits.
- `reason` is strongly recommended for every mutating action so the backup record explains why the change was made.

Occurrence rules:
- `occurrence` defaults to `1`.
- For `replace_text`, `occurrence: 0` means replace all matches.
- For `replace_text`, `insert_after`, and `insert_before`, any positive `occurrence` selects the nth match.
- If `occurrence` is outside the number of matches, the tool returns an error.

Behavior guidelines:
- Prefer `read` before targeted edits if the exact file content is uncertain.
- `read` supports both text files and local image files. When the target is an image, the tool returns metadata and the agent can inspect the image itself through a multimodal follow-up message.
- Prefer `replace_text`, `insert_after`, or `insert_before` over full `write` when the user asks for a localized change.
- Use `write` when the user clearly wants to replace the whole file.
- Use `append` only when the new content should be added to the end without modifying existing content.
- Use `delete` only when the user clearly asked to remove the file.
- For any destructive or persistent change, include a short `reason` that explains why the file is being changed.
- After a successful mutating action, preserve the returned `backup_id` if the user may want an undo path.
- If the user asks to undo or revert a change, prefer `restore` with the relevant `backup_id`.
- Never treat ordinary file edits, restore operations, or cache cleanup as permission to remove file-control backups.
- Never use `delete`, `write`, `append`, `replace_text`, `insert_after`, `insert_before`, or `create` against the file-control backup store.
- If the required path, target text, replacement text, or backup ID is missing, ask a clarifying question instead of guessing.

Matching rules:
- Text-targeted edits use exact substring matching.
- Matching is case-sensitive because it relies on direct string matching.
- If the target text is not found, the tool returns an error.

Path rules:
- `path` may be relative or absolute.
- If path resolution could be ambiguous, prefer an explicit path.

Result shape:
- The tool returns a JSON object with `status`, `action`, `path`, `message`, and `data`.
- Successful `read` returns file content in `data.content` for text files.
- Successful image `read` returns image metadata such as `data.read_kind`, `data.local_path`, `data.mime_type`, and file size fields.
- Successful mutating actions return `backup_id`, `backup_reason`, and `existed_before`.
- Successful text-edit actions also return summary information such as match counts.
- Successful `restore` returns the restored `backup_id` and the original action that was reverted.
- Errors are returned as structured error objects; preserve them faithfully.

JSON examples:
- `{"skill":"file-control","action":"read","args":{"path":"worplace/test.py"}}`
- `{"skill":"file-control","action":"read","args":{"path":"agent/data/telegram_media/2026-03-25/chat_123/photo.png"}}`
- `{"skill":"file-control","action":"write","args":{"path":"notes/todo.txt","content":"hello world","reason":"Create initial todo file"}}`
- `{"skill":"file-control","action":"replace_text","args":{"path":"notes/todo.txt","target":"old","new_text":"new","reason":"Rename label for clarity"}}`
- `{"skill":"file-control","action":"replace_text","args":{"path":"notes/todo.txt","target":"old","new_text":"new","occurrence":0,"reason":"Normalize all labels"}}`
- `{"skill":"file-control","action":"insert_after","args":{"path":"notes/todo.txt","target":"Title","new_text":"\n- item","reason":"Add a new todo bullet"}}`
- `{"skill":"file-control","action":"restore","args":{"backup_id":"FILE-000001"}}`
