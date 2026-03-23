from datetime import datetime
from pathlib import Path


def _relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _section(title: str, lines: list[str]) -> str:
    body = "\n".join(f"- {line}" for line in lines) if lines else "- None"
    return f"## {title}\n{body}"


def generate_system_architecture(config) -> Path:
    agent_root = config.base_dir
    project_root = agent_root.parent
    system_dir = agent_root / "data" / "system"
    system_dir.mkdir(parents=True, exist_ok=True)
    output_path = system_dir / "system_architecture.md"

    prompt_paths = [
        project_root / "agent" / "prompts" / "identity.md",
        project_root / "agent" / "prompts" / "identity.original.md",
        project_root / "agent" / "prompts" / "system_rules.md",
        project_root / "agent" / "prompts" / "boundaries.md",
    ]

    core_runtime = [
        "agent/main.py: terminal entrypoint that starts the agent loop",
        "agent/agent.py: main reasoning loop, tool-call parsing, and multi-step tool execution",
        "agent/chat_scheduler.py: background scheduler that claims due tasks and dispatches them back into the agent",
        "agent/config_loader.py: loads config, prompts, and skills",
        "agent/lmstudio_client.py: sends chat requests to the configured LLM endpoint",
        "agent/skill_client.py: sends tool execution JSON to the skill server",
        "agent/skill_server.py: FastAPI server that executes skills",
        "agent/skill_runtime.py: skill registry and tool loader",
        "agent/schedule_runtime.py: shared agent-native schedule registry, timing logic, and dispatch metadata",
        "agent/schemas.py: shared message and prompt schemas",
        "agent/config/config.json: model, prompt, and skill-server configuration",
    ]

    data_lines = [
        "agent/data/system/system_architecture.md: startup-generated overview of the system",
        "agent/data/memories/: persistent memory directory",
        "agent/data/memories/*.json: important memories stored as JSON files that the agent may inspect or edit when appropriate",
    ]

    prompt_lines = []
    for path in prompt_paths:
        rel = _relative_path(path, project_root)
        if path.name == "identity.md":
            prompt_lines.append(f"{rel}: active identity file used in the system prompt")
        elif path.name == "identity.original.md":
            prompt_lines.append(f"{rel}: blank identity template and update guidance")
        elif path.name == "system_rules.md":
            prompt_lines.append(f"{rel}: hard behavior and tool-usage rules")
        elif path.name == "boundaries.md":
            prompt_lines.append(f"{rel}: final output and tool-loop boundaries")

    skill_lines = []
    for skill in sorted(config.skills, key=lambda item: item.get("name", "")):
        skill_path = Path(skill["path"])
        rel_skill_path = _relative_path(skill_path, project_root)
        tool = skill.get("tool", {})
        tool_module = tool.get("module", "")
        tool_function = tool.get("function", "run")
        skill_lines.append(
            f"{skill['name']}: directory={rel_skill_path}, tool={tool_module}:{tool_function}"
        )

    flow_lines = [
        "User input enters agent/main.py.",
        "Config loads prompts and enabled skills.",
        "SimpleAgent builds the system prompt from identity, system rules, boundaries, and SKILL docs.",
        "The model may answer directly or emit one tool-call JSON object.",
        "Tool-call JSON is sent to the FastAPI skill server.",
        "The skill server executes the tool and returns structured JSON.",
        "The agent may continue reasoning across multiple tool steps until it produces a final answer.",
    ]

    lookup_rules = [
        "If you need to locate a system file, read this file first before searching the repository.",
        "If you need prompt paths, start with the Prompt Files section.",
        "If you need runtime behavior, start with Core Runtime Files and Execution Flow.",
        "If you need a tool path, start with Enabled Skills.",
    ]

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    content = "\n\n".join(
        [
            "# System Architecture",
            "This file is auto-generated when the agent starts.",
            f"Generated at: {generated_at}",
            f"Project root: {project_root}",
            f"Agent root: {agent_root}",
            _section("Core Runtime Files", core_runtime),
            _section("Data Files", data_lines),
            _section("Prompt Files", prompt_lines),
            _section("Enabled Skills", skill_lines),
            _section("Execution Flow", flow_lines),
            _section("How To Use This File", lookup_rules),
        ]
    ).strip() + "\n"

    output_path.write_text(content, encoding="utf-8")
    return output_path
