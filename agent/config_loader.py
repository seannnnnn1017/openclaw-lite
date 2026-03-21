import json
from pathlib import Path
from schemas import AgentLayers


class Config:
    def __init__(self, path: str):
        self.path = Path(path).resolve()   # config.json 絕對路徑
        self.base_dir = self.path.parent.parent  # 指到 agent/
        self._last_mtime = None
        self._prompt_file_paths = []
        self._load()

    def _read_md(self, path: Path) -> str:
        return path.read_text(encoding="utf-8").strip()

    def _load(self):
        data = json.loads(self.path.read_text(encoding="utf-8"))

        prompt_paths = data["prompt_paths"]

        # ✅ 相對於 agent/
        identity_path = self.base_dir / prompt_paths["identity"]
        rules_path = self.base_dir / prompt_paths["system_rules"]
        boundaries_path = self.base_dir / prompt_paths["boundaries"]

        # 存路徑（給 reload 用）
        self._prompt_file_paths = [
            identity_path,
            rules_path,
            boundaries_path,
        ]

        # 讀內容
        self.identity = self._read_md(identity_path)
        self.system_rules = self._read_md(rules_path)
        self.boundaries = self._read_md(boundaries_path)

        self.agent_layers = AgentLayers(
            identity=self.identity,
            system_rules=self.system_rules,
            boundaries=self.boundaries,
        )

        # LLM 設定
        self.base_url = data["llm"]["base_url"]
        self.model = data["llm"]["model"]
        self.temperature = data["llm"]["temperature"]
        self.max_tokens = data["llm"]["max_tokens"]

        # 記錄時間
        all_paths = [self.path] + self._prompt_file_paths
        self._last_mtime = max(p.stat().st_mtime for p in all_paths)

    def reload_if_changed(self):
        all_paths = [self.path] + self._prompt_file_paths
        latest_mtime = max(p.stat().st_mtime for p in all_paths)

        if latest_mtime != self._last_mtime:
            print("[CONFIG OR PROMPT RELOADED]")
            self._load()