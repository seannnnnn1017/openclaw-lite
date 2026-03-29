import importlib
import importlib.util
from pathlib import Path


class SkillRuntime:
    def __init__(self, skills: list[dict]):
        self.registry = {}
        for skill in skills:
            skill_name = skill.get("name")
            if skill_name:
                self.registry[skill_name] = skill

    def list_skills(self) -> list[dict]:
        result = []
        for skill_name, skill in sorted(self.registry.items()):
            result.append(
                {
                    "name": skill_name,
                    "description": skill.get("metadata", {}).get("description", ""),
                    "tool": skill.get("tool", {}),
                }
            )
        return result

    def execute(self, skill_name: str, action: str, args: dict | None = None):
        skill = self.registry.get(skill_name)
        if not skill:
            raise ValueError(f"Unknown skill: {skill_name}")

        tool_spec = skill.get("tool") or {}
        if not tool_spec:
            raise ValueError(f"Skill '{skill_name}' has no tool configuration")

        tool_fn = self._load_tool(skill, tool_spec)
        kwargs = {"action": action, **(args or {})}
        return tool_fn(**kwargs)

    def _load_tool(self, skill: dict, tool_spec: dict):
        module_name = tool_spec.get("module")
        function_name = tool_spec.get("function", "run")

        if module_name:
            try:
                module = importlib.import_module(module_name)
                return getattr(module, function_name)
            except ModuleNotFoundError:
                pass

        skill_path = Path(skill["path"])
        tool_name = skill.get("metadata", {}).get("command-tool", "tool")
        script_path = skill_path / "scripts" / f"{tool_name}.py"
        if not script_path.exists():
            raise FileNotFoundError(f"Tool script not found: {script_path}")

        spec = importlib.util.spec_from_file_location(
            f"skill_{skill.get('name', 'tool').replace('-', '_')}_{tool_name}",
            script_path,
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load tool from {script_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return getattr(module, function_name)
