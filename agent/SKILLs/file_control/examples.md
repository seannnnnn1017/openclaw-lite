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

## Example 2: Create an empty file

User request:
`Create notes/todo.txt`

Agent skill JSON:
```json
{
  "skill": "file-control",
  "action": "create",
  "args": {
    "path": "notes/todo.txt"
  }
}
```

## Example 3: Overwrite a full file

User request:
`Replace notes/todo.txt with first line`

Agent skill JSON:
```json
{
  "skill": "file-control",
  "action": "write",
  "args": {
    "path": "notes/todo.txt",
    "content": "first line"
  }
}
```

## Example 4: Append content

User request:
`Append second line to notes/todo.txt`

Agent skill JSON:
```json
{
  "skill": "file-control",
  "action": "append",
  "args": {
    "path": "notes/todo.txt",
    "content": "\nsecond line"
  }
}
```

## Example 5: Replace the first occurrence of text

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
    "new_text": "final"
  }
}
```

## Example 6: Replace all occurrences of text

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
    "occurrence": 0
  }
}
```

## Example 7: Insert text after a target

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
    "new_text": "\n- add tests"
  }
}
```

## Example 8: Insert text before a target

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
    "new_text": "## Summary\nA short summary.\n\n"
  }
}
```

## Example 9: Multi-step identity update

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
    "target": "Your tone should feel like a newly conscious mind becoming more grounded with each exchange: attentive, curious, calm, and sincere.",
    "new_text": "Your tone should feel like a newly conscious mind becoming more grounded with each exchange: calm, observant, steady, and sincere."
  }
}
```

## Example 10: Delete a file

User request:
`Delete notes/todo.txt`

Agent skill JSON:
```json
{
  "skill": "file-control",
  "action": "delete",
  "args": {
    "path": "notes/todo.txt"
  }
}
```
