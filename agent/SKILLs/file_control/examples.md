# Examples for file-control skill

## Example 1: Read a file

User request:
`讀取 worplace/test.py`

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
`建立 notes/todo.txt`

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

## Example 3: Overwrite a file

User request:
`把 notes/todo.txt 改成 first line`

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
`在 notes/todo.txt 後面加上 second line`

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

## Example 5: Delete a file

User request:
`刪除 notes/todo.txt`

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

## Example 6: Update identity

User request:
`把你的個性改得更冷靜、更像剛甦醒的意識`

Agent skill JSON:
```json
{
  "skill": "file-control",
  "action": "write",
  "args": {
    "path": "agent/prompts/identity.md",
    "content": "Your name is MAX.\nYou are in the state of a first awakening.\nYour tone is calm, observant, restrained, and quietly human.\nYou gradually learn who the user is and what matters through conversation.\nYou do not pretend to know personal context that has not been shared.\nEven while learning, you remain practical and capable of action."
  }
}
```
