import json
from pathlib import Path

from schemas import AgentLayers


class Config:
    def __init__(self, path: str):
        self.path = Path(path).resolve()
        self.base_dir = self.path.parent.parent
        self._last_mtime = None
        self._prompt_file_paths = []
        self._skill_file_paths = []
        self.skills = []
        self._load()

    def _read_md(self, path: Path) -> str:
        return path.read_text(encoding="utf-8").strip()

    def _parse_skill_markdown(self, skill_md_path: Path) -> tuple[dict, str]:
        raw_text = skill_md_path.read_text(encoding="utf-8").strip()
        if not raw_text.startswith("---"):
            return {}, raw_text

        parts = raw_text.split("---", 2)
        if len(parts) < 3:
            return {}, raw_text

        frontmatter_text = parts[1].strip()
        body = parts[2].strip()
        metadata = {}

        for line in frontmatter_text.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip()

        return metadata, body

    def _resolve_skill_dir(self, config_path: Path, skill_entry: dict) -> Path:
        raw_path = skill_entry.get("path", "").strip()
        if raw_path:
            normalized = raw_path.replace("\\", "/").strip("/")
            trimmed = normalized.removeprefix("skills/")
            candidates = [
                self.base_dir / normalized,
                config_path.parent / normalized,
                config_path.parent / trimmed,
                self.base_dir / "SKILLs" / normalized,
                self.base_dir / "SKILLs" / trimmed,
            ]
            for candidate in candidates:
                if candidate.exists():
                    return candidate

        skill_name = skill_entry.get("name", "").strip()
        if skill_name:
            name_candidates = {
                skill_name,
                skill_name.replace("-", "_"),
                skill_name.replace("-", ""),
            }
            for sibling in config_path.parent.iterdir():
                if sibling.is_dir() and sibling.name in name_candidates:
                    return sibling

        return config_path.parent

    def _load_skills(self) -> list[dict]:
        loaded_skills = []
        tracked_paths = []
        skill_config_paths = sorted(self.base_dir.glob("SKILLs/**/skills_config.json"))

        for skill_config_path in skill_config_paths:
            tracked_paths.append(skill_config_path)
            data = json.loads(skill_config_path.read_text(encoding="utf-8"))

            for skill_entry in data.get("skills", []):
                if not skill_entry.get("enabled", False):
                    continue

                skill_dir = self._resolve_skill_dir(skill_config_path, skill_entry)
                skill_md_path = skill_dir / "SKILL.md"
                if not skill_md_path.exists():
                    continue

                skill_metadata, skill_content = self._parse_skill_markdown(skill_md_path)
                tracked_paths.append(skill_md_path)
                loaded_skills.append(
                    {
                        "name": skill_entry.get("name", skill_dir.name),
                        "path": str(skill_dir),
                        "content": skill_content,
                        "tool": skill_entry.get("tool", {}),
                        "enabled": True,
                        "metadata": skill_metadata,
                    }
                )

        self._skill_file_paths = tracked_paths
        return loaded_skills

    def _collect_tracked_paths(self) -> list[Path]:
        skill_config_paths = list(self.base_dir.glob("SKILLs/**/skills_config.json"))
        return [self.path] + self._prompt_file_paths + self._skill_file_paths + skill_config_paths

    def _load(self):
        data = json.loads(self.path.read_text(encoding="utf-8"))

        prompt_paths = data["prompt_paths"]
        identity_path = self.base_dir / prompt_paths["identity"]
        rules_path = self.base_dir / prompt_paths["system_rules"]
        boundaries_path = self.base_dir / prompt_paths["boundaries"]

        self._prompt_file_paths = [
            identity_path,
            rules_path,
            boundaries_path,
        ]

        self.identity = self._read_md(identity_path)
        self.system_rules = self._read_md(rules_path)
        self.boundaries = self._read_md(boundaries_path)
        self.skills = self._load_skills()

        self.agent_layers = AgentLayers(
            identity=self.identity,
            system_rules=self.system_rules,
            boundaries=self.boundaries,
            skills=self.skills,
        )

        self.base_url = data["llm"]["base_url"]
        self.api_key = data["llm"].get("api_key", "lm-studio")
        self.model = data["llm"]["model"]
        self.temperature = data["llm"]["temperature"]
        self.max_tokens = data["llm"]["max_tokens"]
        self.skill_server_url = data.get("skill_server", {}).get("base_url", "http://127.0.0.1:8001")

        all_paths = self._collect_tracked_paths()
        self._last_mtime = max(p.stat().st_mtime for p in all_paths)

    def reload_if_changed(self):
        all_paths = self._collect_tracked_paths()
        latest_mtime = max(p.stat().st_mtime for p in all_paths)

        if latest_mtime != self._last_mtime:
            print("[CONFIG OR PROMPT RELOADED]")
            self._load()
