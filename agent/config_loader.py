import json
import os
from pathlib import Path

from schemas import AgentLayers

try:
    from secret_store import SECRET_CONFIG_PATH, load_secret_config
except ModuleNotFoundError:
    from agent.secret_store import SECRET_CONFIG_PATH, load_secret_config


class Config:
    def __init__(self, path: str):
        self.path = Path(path).resolve()
        self.base_dir = self.path.parent.parent
        self._last_mtime = None
        self._prompt_file_paths = []
        self._skill_file_paths = []
        self._secret_file_paths = []
        self._model_override = None
        self.default_model = ""
        self.skills = []
        self._load()

    def _read_md(self, path: Path) -> str:
        return path.read_text(encoding="utf-8").strip()

    def _parse_int_list(self, value) -> list[int]:
        if value in (None, "", []):
            return []
        if isinstance(value, str):
            tokens = [part.strip() for part in value.replace(",", " ").split() if part.strip()]
        elif isinstance(value, (list, tuple, set)):
            tokens = [str(part).strip() for part in value if str(part).strip()]
        else:
            return []

        parsed = []
        for token in tokens:
            try:
                parsed.append(int(token))
            except ValueError:
                continue
        return parsed

    def _parse_string_list(self, value) -> list[str]:
        if value in (None, "", []):
            return []
        if isinstance(value, str):
            items = [part.strip() for part in value.replace(",", " ").split() if part.strip()]
        elif isinstance(value, (list, tuple, set)):
            items = [str(part).strip() for part in value if str(part).strip()]
        else:
            return []

        normalized = []
        seen = set()
        for item in items:
            key = item.lstrip("@").casefold()
            if key and key not in seen:
                seen.add(key)
                normalized.append(item.lstrip("@"))
        return normalized

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
        return (
            [self.path]
            + self._prompt_file_paths
            + self._skill_file_paths
            + self._secret_file_paths
            + skill_config_paths
        )

    def _load(self):
        data = json.loads(self.path.read_text(encoding="utf-8"))
        secrets = load_secret_config()
        llm_secrets = secrets.get("llm", {}) if isinstance(secrets.get("llm"), dict) else {}
        telegram_secrets = (
            secrets.get("telegram", {}) if isinstance(secrets.get("telegram"), dict) else {}
        )
        self._secret_file_paths = [SECRET_CONFIG_PATH] if SECRET_CONFIG_PATH.exists() else []

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
        self.api_key = (
            os.getenv("OPENCLAW_LLM_API_KEY")
            or llm_secrets.get("api_key")
            or data["llm"].get("api_key", "lm-studio")
        )
        self.default_model = data["llm"]["model"]
        self.model = self._model_override or self.default_model
        self.temperature = data["llm"]["temperature"]
        self.max_tokens = data["llm"]["max_tokens"]
        self.stream = bool(data["llm"].get("stream", False))
        self.skill_server_url = data.get("skill_server", {}).get("base_url", "http://127.0.0.1:8001")

        telegram = data.get("telegram", {})
        self.telegram_enabled = bool(telegram.get("enabled", False))
        self.telegram_bot_token = (
            os.getenv("OPENCLAW_TELEGRAM_BOT_TOKEN")
            or telegram_secrets.get("bot_token")
            or telegram.get("bot_token", "")
        )
        self.telegram_poll_timeout_seconds = int(telegram.get("poll_timeout_seconds", 20))
        self.telegram_retry_delay_seconds = float(telegram.get("retry_delay_seconds", 5))
        self.telegram_skip_pending_updates_on_start = bool(
            telegram.get("skip_pending_updates_on_start", True)
        )
        self.telegram_allowed_chat_ids = self._parse_int_list(telegram.get("allowed_chat_ids", []))
        self.telegram_allowed_usernames = self._parse_string_list(
            telegram.get("allowed_usernames", [])
        )
        telegram_state_path = telegram.get("state_path", "").strip()
        self.telegram_state_path = (
            str((self.base_dir / telegram_state_path).resolve())
            if telegram_state_path
            else str((self.base_dir / "data" / "system" / "telegram_bridge_state.json").resolve())
        )
        telegram_image_storage_path = telegram.get("image_storage_path", "").strip()
        self.telegram_image_storage_path = (
            str((self.base_dir / telegram_image_storage_path).resolve())
            if telegram_image_storage_path
            else str((self.base_dir / "data" / "telegram_media").resolve())
        )

        all_paths = self._collect_tracked_paths()
        self._last_mtime = max(p.stat().st_mtime for p in all_paths)

    def reload_if_changed(self):
        all_paths = self._collect_tracked_paths()
        latest_mtime = max(p.stat().st_mtime for p in all_paths)

        if latest_mtime != self._last_mtime:
            self._load()
            return True
        return False

    def reload_now(self):
        self._load()

    def set_runtime_model(self, model_name: str):
        cleaned = model_name.strip()
        if not cleaned:
            raise ValueError("Model name cannot be empty")
        self._model_override = cleaned
        self.model = cleaned

    def reset_runtime_model(self):
        self._model_override = None
        self.model = self.default_model

    def has_runtime_model_override(self) -> bool:
        return bool(self._model_override)

    def save_model(self, model_name: str):
        cleaned = model_name.strip()
        if not cleaned:
            raise ValueError("Model name cannot be empty")

        data = json.loads(self.path.read_text(encoding="utf-8"))
        data["llm"]["model"] = cleaned
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._model_override = None
        self._load()
