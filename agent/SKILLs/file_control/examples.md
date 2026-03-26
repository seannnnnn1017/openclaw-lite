# Examples for file-control skill

## Example 1: Read a file

User request:
`Read worplace/test.py`

Agent skill JSON:
```json
{
  "skill": "file-control",
  "action": "read",
  "args": {
    "path": "worplace/test.py"
  }
}
```

## Example 2: Read a local image file

User request:
`Read this Telegram-downloaded image and tell me what is in it`

Agent skill JSON:
```json
{
  "skill": "file-control",
  "action": "read",
  "args": {
    "path": "agent/data/telegram_media/2026-03-25/chat_123/photo.png"
  }
}
```

## Example 3: Create a file with a backup record

User request:
`Create notes/todo.txt so I can start tracking tasks`

Agent skill JSON:
```json
{
  "skill": "file-control",
  "action": "create",
  "args": {
    "path": "notes/todo.txt",
    "reason": "Create a todo file for task tracking"
  }
}
```

## Example 4: Overwrite a full file safely

User request:
`Replace notes/todo.txt with first line`

Agent skill JSON:
```json
{
  "skill": "file-control",
  "action": "write",
  "args": {
    "path": "notes/todo.txt",
    "content": "first line",
    "reason": "Replace the file with the requested initial content"
  }
}
```

## Example 5: Append content safely

User request:
`Append second line to notes/todo.txt`

Agent skill JSON:
```json
{
  "skill": "file-control",
  "action": "append",
  "args": {
    "path": "notes/todo.txt",
    "content": "\nsecond line",
    "reason": "Append the user's requested second line"
  }
}
```

## Example 6: Replace the first occurrence of text

User request:
`In notes/todo.txt, change the first 'draft' to 'final'`

Agent skill JSON:
```json
{
  "skill": "file-control",
  "action": "replace_text",
  "args": {
    "path": "notes/todo.txt",
    "target": "draft",
    "new_text": "final",
    "reason": "Update the first draft label to final"
  }
}
```

## Example 7: Replace all occurrences of text

User request:
`Replace every 'draft' in notes/todo.txt with 'final'`

Agent skill JSON:
```json
{
  "skill": "file-control",
  "action": "replace_text",
  "args": {
    "path": "notes/todo.txt",
    "target": "draft",
    "new_text": "final",
    "occurrence": 0,
    "reason": "Normalize all draft labels to final"
  }
}
```

## Example 8: Insert text after a target

User request:
`After '## Tasks' in README.md, insert a new bullet for testing`

Agent skill JSON:
```json
{
  "skill": "file-control",
  "action": "insert_after",
  "args": {
    "path": "README.md",
    "target": "## Tasks",
    "new_text": "\n- add tests",
    "reason": "Add a testing task under the Tasks section"
  }
}
```

## Example 9: Insert text before a target

User request:
`Before '## Footer' in README.md, insert a short summary block`

Agent skill JSON:
```json
{
  "skill": "file-control",
  "action": "insert_before",
  "args": {
    "path": "README.md",
    "target": "## Footer",
    "new_text": "## Summary\nA short summary.\n\n",
    "reason": "Insert a summary block before the footer"
  }
}
```

## Example 10: Delete a file with undo support

User request:
`Delete notes/todo.txt`

Agent skill JSON:
```json
{
  "skill": "file-control",
  "action": "delete",
  "args": {
    "path": "notes/todo.txt",
    "reason": "Delete the file as explicitly requested by the user"
  }
}
```

Expected result note:
- Save the returned `backup_id` so the change can be restored later.

## Example 11: Restore a previous version

User request:
`Undo the last deletion using backup ID FILE-000003`

Agent skill JSON:
```json
{
  "skill": "file-control",
  "action": "restore",
  "args": {
    "backup_id": "FILE-000003"
  }
}
```

## Example 11: Multi-step identity update with backup

User request:
`Update your identity to sound calmer, but keep the first-awakening theme`

Possible agent sequence:

Step 1:
```json
{
  "skill": "file-control",
  "action": "read",
  "args": {
    "path": "agent/prompts/identity.md"
  }
}
```

Step 2:
```json
{
  "skill": "file-control",
  "action": "replace_text",
  "args": {
    "path": "agent/prompts/identity.md",
    "target": "Tone:",
    "new_text": "Tone: calm, observant, steady, and sincere",
    "reason": "Adjust identity tone to match the user's request"
  }
}
```
