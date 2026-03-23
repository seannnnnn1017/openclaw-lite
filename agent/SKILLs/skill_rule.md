# SKILL Rule Specification

This document defines how SKILLs work in this project.
It describes the required folder structure, config files, prompt behavior, server execution flow, and the current runtime logic used by the agent.

## 1. Purpose

SKILL is the project-level tool abstraction used by the agent.

A SKILL has two roles:
- It teaches the model when and how to use a capability.
- It provides a real executable tool that the FastAPI skill server can call.

In this project:
- The agent decides whether a SKILL is needed.
- The agent emits a JSON tool call.
- The skill server executes the tool.
- The result is returned to the agent.
- The agent may continue reasoning across multiple tool steps until it gives a final answer.

## 2. Root Location

All SKILL definitions live under:

`agent/SKILLs/`

Current files in this area include:
- `agent/SKILLs/skill_rule.md`
- `agent/SKILLs/file_control/`
- `agent/SKILLs/schedule_task/`

## 3. Required SKILL Folder Structure

Each SKILL should use a structure like this:

```text
agent/SKILLs/<skill_folder>/
  SKILL.md
  examples.md
  skills_config.json
  scripts/
    <tool_script>.py
```

Optional extra folders may exist, for example:

```text
agent/SKILLs/<skill_folder>/scripts/temporary_data/
agent/SKILLs/<skill_folder>/assets/
agent/SKILLs/<skill_folder>/references/
```

## 4. Current Examples

The current implemented SKILLs are:

`agent/SKILLs/file_control/`
`agent/SKILLs/schedule_task/`

Important files for `file_control`:
- `agent/SKILLs/file_control/SKILL.md`: prompt-facing skill description
- `agent/SKILLs/file_control/examples.md`: usage examples for the model
- `agent/SKILLs/file_control/skills_config.json`: runtime registration
- `agent/SKILLs/file_control/scripts/file_tool.py`: actual tool implementation
- `agent/SKILLs/file_control/scripts/temporary_data/file_ID.json`: backup index
- `agent/SKILLs/file_control/scripts/temporary_data/backups/`: backup payloads

Important files for `schedule_task`:
- `agent/SKILLs/schedule_task/SKILL.md`: prompt-facing skill description
- `agent/SKILLs/schedule_task/examples.md`: usage examples for the model
- `agent/SKILLs/schedule_task/skills_config.json`: runtime registration
- `agent/SKILLs/schedule_task/scripts/schedule_tool.py`: skill wrapper entrypoint
- `agent/schedule_runtime.py`: shared schedule registry and agent-dispatch runtime
- `agent/SKILLs/schedule_task/scripts/temporary_data/task_registry.json`: managed task registry

## 5. skills_config.json Rules

Each SKILL must be registered in a `skills_config.json` file.

Current pattern:

```json
{
  "skills": [
    {
      "name": "file-control",
      "enabled": true,
      "path": "file_control",
      "tool": {
        "type": "python_function",
        "module": "agent.SKILLs.file_control.scripts.file_tool",
        "function": "run"
      }
    }
  ]
}
```

Field rules:
- `name`: public skill name used by the agent in tool JSON
- `enabled`: only enabled skills are loaded
- `path`: folder path used to resolve the SKILL directory
- `tool.type`: current project uses `python_function`
- `tool.module`: import path for the tool module
- `tool.function`: callable entrypoint, usually `run`

Current loading behavior:
- The loader scans `agent/SKILLs/**/skills_config.json`
- Only `enabled: true` entries are added to the runtime registry

## 6. SKILL.md Rules

Each SKILL must provide a `SKILL.md`.

This file serves two functions:
- It contains frontmatter metadata
- It contains the prompt instructions shown to the model

Expected frontmatter pattern:

```md
---
name: file-control
description: ...
user-invocable: true
command-dispatch: tool
command-tool: file_tool
command-arg-mode: raw
metadata: { "openclaw": { "requires": { "bins": ["python"] } } }
---
```

Important metadata fields:
- `name`: SKILL name
- `description`: short human-readable summary
- `user-invocable`: whether the skill is intended for real user-facing tasks
- `command-dispatch`: current project expects `tool`
- `command-tool`: fallback script name under `scripts/`
- `command-arg-mode`: current project uses `raw`

Body rules:
- Describe what the SKILL is for
- Define supported actions
- Define required arguments
- Explain behavior and safety constraints
- Explain expected result shape
- Include accurate JSON examples

The body of `SKILL.md` is injected into the system prompt.

## 7. examples.md Rules

Each SKILL should provide `examples.md`.

This file is not executed directly.
Its purpose is to teach the model how to emit correct tool JSON.

Good examples should include:
- a natural user request
- the matching SKILL JSON
- multi-step examples if the task needs more than one tool call
- examples that reflect the current tool implementation exactly

If the tool changes, `examples.md` must be updated together with `SKILL.md`.

## 8. How SKILLs Are Loaded

The SKILL loading logic currently lives in:

`agent/config_loader.py`

Current load flow:
1. Read `agent/config/config.json`
2. Resolve prompt files
3. Scan `agent/SKILLs/**/skills_config.json`
4. For each enabled entry:
   - resolve its folder
   - load `SKILL.md`
   - parse frontmatter
   - store metadata, prompt content, and tool config
5. Inject enabled SKILL content into the system prompt

Important current behavior:
- SKILLs hot reload when config or tracked prompt/skill files change
- Only enabled SKILLs are included in `config.skills`

## 9. How SKILL Content Enters the Prompt

System prompt construction lives in:

`agent/schemas.py`

The final system prompt is built from:
- `[IDENTITY]`
- `[SYSTEM RULES]`
- `[BOUNDARIES]`
- `[AVAILABLE SKILLS]`

For each loaded SKILL, the body of `SKILL.md` is appended like:

```text
[SKILL: <skill-name>]
<skill prompt body>
```

This means SKILL prompt quality directly affects tool selection quality.

## 10. Agent-Side Tool Call Contract

The agent does not execute tools directly.
It emits JSON and sends it to the skill server.

Current base schema:

```json
{"skill":"<skill-name>","action":"<action>","args":{"key":"value"}}
```

Current extended schema:

```json
{"message":"<short note>","skill":"<skill-name>","action":"<action>","args":{"key":"value"}}
```

Field rules:
- `message`: optional terminal-facing note for the human operator
- `skill`: must match a registered enabled SKILL
- `action`: action name understood by the tool
- `args`: tool arguments only

The agent may emit multiple tool calls in sequence.

## 11. Agent Runtime Logic

The main runtime loop is in:

`agent/agent.py`

Current behavior:
1. Build system prompt from prompts + SKILL docs
2. Send messages to the LLM
3. Parse the reply
4. If it is normal text, return it to the user
5. If it is SKILL JSON:
   - show optional `[TOOL NOTE]`
   - show `[TOOL CALL]`
   - call the skill server
   - show `[TOOL RESULT]`
   - feed the result back into the model
   - continue until no more tool call appears or max steps are reached

Additional current behavior:
- `<think>...</think>` blocks are extracted and shown as `[THINK]`
- the agent currently limits tool steps with `max_tool_steps`

## 12. Skill Server Logic

The skill server is implemented in:

`agent/skill_server.py`

Framework:
- FastAPI

Current endpoints:
- `GET /skills`
- `POST /skills/execute`

Current execute request schema:

```json
{
  "skill": "file-control",
  "action": "read",
  "args": {
    "path": "some/file.txt"
  }
}
```

Current execute response shape:

```json
{
  "status": "ok",
  "skill": "file-control",
  "action": "read",
  "result": {
    "...": "tool return payload"
  }
}
```

Server responsibilities:
- receive the JSON request
- reload config if changed
- build a fresh runtime registry
- validate the requested SKILL exists
- load the tool
- call the tool function
- return structured JSON
- log full request and full response

## 13. Skill Runtime Logic

The execution registry lives in:

`agent/skill_runtime.py`

Current responsibilities:
- build a registry keyed by skill name
- expose `list_skills()`
- expose `execute(skill_name, action, args)`
- load the tool function

Tool loading behavior:
1. Try `tool.module` + `tool.function`
2. If import fails, fall back to:
   `SKILL_DIR/scripts/<command-tool>.py`

This means a SKILL can still work even if the module import path is unavailable, as long as the script file exists and the frontmatter has a valid `command-tool`.

## 14. Tool Script Rules

Each tool script should expose a callable entrypoint.

Current project convention:

```python
def run(action: str, ...):
    ...
```

Rules for tool scripts:
- accept `action` as the primary dispatch argument
- accept additional keyword arguments as needed
- return structured JSON-like dictionaries
- avoid printing user-facing content directly
- encode success and error states clearly

Recommended return shape:

```json
{
  "status": "ok",
  "action": "<action>",
  "path": "<path>",
  "message": "<summary>",
  "data": {}
}
```

Recommended error shape:

```json
{
  "status": "error",
  "action": "<action>",
  "path": "<path>",
  "message": "<error>",
  "data": null
}
```

## 15. file-control Specific Rules

Current tool:

`agent/SKILLs/file_control/scripts/file_tool.py`

Current supported actions:
- `read`
- `create`
- `write`
- `append`
- `delete`
- `replace_text`
- `insert_after`
- `insert_before`
- `restore`

Current safety logic:
- all mutating actions create a backup record first
- backup records are indexed in `temporary_data/file_ID.json`
- backup files are stored in `temporary_data/backups/`
- `restore` can restore by `backup_id`

Current mutating actions that create backups:
- `create`
- `write`
- `append`
- `delete`
- `replace_text`
- `insert_after`
- `insert_before`

Recommended prompt behavior for file-control:
- use `read` before making localized edits when unsure
- include `reason` for any mutating action
- retain `backup_id` when the user may later want to undo

## 16. Logging Rules

Current terminal-side logs in the agent:
- `[THINK n]`
- `[TOOL NOTE n]`
- `[TOOL CALL n]`
- `[TOOL RESULT n]`

Current server-side logs:
- full `skill_request`
- full `skill_success`
- full `skill_failed`

Rule:
- human-facing terminal logs should be concise
- server logs may be verbose and preserve full payloads

## 17. Memory and System Data

Important project data locations:
- `agent/data/system/system_architecture.md`: generated system overview
- `agent/data/memories/`: persistent memory directory

Memory rules:
- important memories are stored as JSON under `agent/data/memories`
- the agent may inspect or edit those files using a configured skill when appropriate

## 18. Authoring a New SKILL

To add a new SKILL:
1. Create `agent/SKILLs/<skill_folder>/`
2. Add `SKILL.md`
3. Add `examples.md`
4. Add `skills_config.json`
5. Add `scripts/<tool_script>.py`
6. Set `enabled: true`
7. Restart or trigger config reload
8. Confirm the SKILL appears in `/skills`

Minimum checklist:
- the folder exists
- `SKILL.md` exists
- `skills_config.json` is valid JSON
- tool module path is correct
- tool function exists
- examples match the real tool behavior

## 19. Maintenance Rules

Whenever a SKILL tool changes:
- update `SKILL.md`
- update `examples.md`
- update any related safety or restore logic
- keep request/response shapes aligned with the implementation

Whenever server execution logic changes:
- update this document
- update system prompt rules if the JSON contract changes

Whenever prompt contract changes:
- update `agent/prompts/system_rules.md`
- update `agent/prompts/boundaries.md`
- update affected SKILL docs

## 20. Current Design Constraints

Current practical constraints in this project:
- the agent relies heavily on prompt quality to decide when to use tools
- the agent expects exactly one tool JSON object per tool step
- malformed JSON can cause missed tool execution
- some model/chat template combinations in LM Studio may fail on longer histories
- multi-step tool use works, but long accumulated history can still destabilize some models

## 21. Recommended Future Improvements

Possible future improvements:
- stronger JSON schema validation per SKILL
- explicit `input_schema` in `skills_config.json`
- backup listing and inspection endpoints
- richer restore history
- SKILL categories and permissions
- tool-specific safety approval flow
- automatic summarization of long tool traces before storing them in history

## 22. Source of Truth

If this document conflicts with the actual code, the code is the immediate runtime truth.
However, this file should be kept in sync with:
- `agent/config_loader.py`
- `agent/skill_runtime.py`
- `agent/skill_server.py`
- `agent/agent.py`
- the individual SKILL folder files

The goal is that a developer or the agent itself can read this document first and understand:
- where a SKILL lives
- how it is registered
- how it enters the prompt
- how it is executed by the server
- how tool JSON should be formed
- how safety, backup, and restore behavior currently work
