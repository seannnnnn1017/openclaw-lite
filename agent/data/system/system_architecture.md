# System Architecture

This file is auto-generated when the agent starts.

Generated at: 2026-03-24T00:10:37+08:00

Project root: E:\重要文件\openclaw-lite

Agent root: E:\重要文件\openclaw-lite\agent

## Core Runtime Files
- agent/main.py: terminal entrypoint that starts the agent loop
- agent/agent.py: main reasoning loop, tool-call parsing, and multi-step tool execution
- agent/chat_scheduler.py: background scheduler that claims due tasks and dispatches them back into the agent
- agent/config_loader.py: loads config, prompts, and skills
- agent/lmstudio_client.py: sends chat requests to the configured LLM endpoint
- agent/skill_client.py: sends tool execution JSON to the skill server
- agent/skill_server.py: FastAPI server that executes skills
- agent/skill_runtime.py: skill registry and tool loader
- agent/schedule_runtime.py: shared agent-native schedule registry, timing logic, and dispatch metadata
- agent/schemas.py: shared message and prompt schemas
- agent/config/config.json: model, prompt, and skill-server configuration

## Data Files
- agent/data/system/system_architecture.md: startup-generated overview of the system
- agent/data/memories/: persistent memory directory
- agent/data/memories/*.json: important memories stored as JSON files that the agent may inspect or edit when appropriate

## Prompt Files
- agent/prompts/identity.md: active identity file used in the system prompt
- agent/prompts/identity.original.md: blank identity template and update guidance
- agent/prompts/system_rules.md: hard behavior and tool-usage rules
- agent/prompts/boundaries.md: final output and tool-loop boundaries

## Enabled Skills
- file-control: directory=agent/SKILLs/file_control, tool=agent.SKILLs.file_control.scripts.file_tool:run
- schedule-task: directory=agent/SKILLs/schedule_task, tool=agent.SKILLs.schedule_task.scripts.schedule_tool:run

## Execution Flow
- User input enters agent/main.py.
- Config loads prompts and enabled skills.
- SimpleAgent builds the system prompt from identity, system rules, boundaries, and SKILL docs.
- The model may answer directly or emit one tool-call JSON object.
- Tool-call JSON is sent to the FastAPI skill server.
- The skill server executes the tool and returns structured JSON.
- The agent may continue reasoning across multiple tool steps until it produces a final answer.

## How To Use This File
- If you need to locate a system file, read this file first before searching the repository.
- If you need prompt paths, start with the Prompt Files section.
- If you need runtime behavior, start with Core Runtime Files and Execution Flow.
- If you need a tool path, start with Enabled Skills.
