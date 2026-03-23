---
name: file-control
description: Read, create, write, append, and delete files through the external skill server
user-invocable: true
command-dispatch: tool
command-tool: file_tool
command-arg-mode: raw
metadata: { "openclaw": { "requires": { "bins": ["python"] } } }
---

Use this skill when the user wants to inspect or modify files.

This skill is selected by the agent and executed by the skill server.
Do not answer with slash commands.
When this skill is needed, output a single JSON object in this form:

{"skill":"file-control","action":"<action>","args":{"path":"<target_path>"}}

Supported actions:
- `read`: read a file and return its content
- `create`: create an empty file if it does not exist
- `write`: overwrite a file with new content
- `append`: append content to the end of a file
- `delete`: remove a file

Argument rules:
- Always provide `path` inside `args`.
- Provide `content` inside `args` for `write` and `append`.
- Do not place `action` inside `args`.
- Keep the JSON minimal and include only required arguments.

Behavior guidelines:
- If the user asks to inspect a file, choose `read`.
- If the user asks to create an empty file, choose `create`.
- If the user asks to replace the full content of a file, choose `write`.
- If the user asks to add text without replacing existing content, choose `append`.
- If the user clearly asks to remove a file, choose `delete`.
- If the path or content is missing, ask a clarifying question instead of guessing.

Result guidelines:
- The skill server will execute the JSON instruction and return structured output.
- After tool results are available, use them faithfully in the final user-facing answer.
- Do not invent file contents or success states.

JSON examples:
- `{"skill":"file-control","action":"read","args":{"path":"worplace/test.py"}}`
- `{"skill":"file-control","action":"create","args":{"path":"notes/todo.txt"}}`
- `{"skill":"file-control","action":"write","args":{"path":"notes/todo.txt","content":"hello world"}}`
- `{"skill":"file-control","action":"append","args":{"path":"notes/todo.txt","content":"\nmore text"}}`
- `{"skill":"file-control","action":"delete","args":{"path":"notes/todo.txt"}}`
