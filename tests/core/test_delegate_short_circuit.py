import json

from agent.core.agent import SimpleAgent


class _FakeLayers:
    def build_system_prompt(self) -> str:
        return "system"


class _FakeConfig:
    def __init__(self):
        self.skill_server_url = "http://127.0.0.1:8001"
        self.base_url = "http://localhost:1234/v1"
        self.api_key = "lm-studio"
        self.model = "qwen/test"
        self.temperature = 0.1
        self.max_tokens = 256
        self.stream = False
        self.memory_enabled = False
        self.memory_store_path = "."
        self.agent_layers = _FakeLayers()
        self.skills = []
        self.ensure_model_loaded = False
        self.context_window = 0
        self.model_load_key = ""
        self.model_load_timeout_seconds = 30.0


class _FakeDisplay:
    def tool_call(self, *args, **kwargs):
        return None

    def tool_note(self, *args, **kwargs):
        return None

    def tool_result(self, *args, **kwargs):
        return None

    def think(self, *args, **kwargs):
        return None

    def system(self, *args, **kwargs):
        return None

    def set_waiting(self, *args, **kwargs):
        return None

    def clear_waiting(self, *args, **kwargs):
        return None


class _FakeMemoryCoordinator:
    def __init__(self, *args, **kwargs):
        self.turns = []

    def start_session(self):
        return None

    def build_hot_message(self):
        return ""

    def build_warm_message(self, user_input, active_skills):
        return ""

    def append_turn(self, user_input: str, assistant_response: str):
        self.turns.append((user_input, assistant_response))

    def handle_memory_command(self, command: dict) -> str:
        return "{}"

    def stats(self) -> dict:
        return {"enabled": False}


class _FakeSkillClient:
    def __init__(self, *args, **kwargs):
        return None


def test_run_short_circuits_successful_delegate(monkeypatch):
    import agent.core.agent as agent_mod

    monkeypatch.setattr(agent_mod, "MemoryCoordinator", _FakeMemoryCoordinator)
    monkeypatch.setattr(agent_mod, "SkillClient", _FakeSkillClient)

    agent = SimpleAgent(
        config=_FakeConfig(),
        client=object(),
        display=_FakeDisplay(),
        debug_logger=None,
    )

    chat_calls = []

    def fake_chat(messages, *, response_stream_callback=None):
        chat_calls.append(messages)
        return json.dumps(
            {
                "skill": "notion-basic",
                "action": "__delegate__",
                "args": {"task": "查詢明天行程", "context": {}},
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(agent, "_chat", fake_chat)
    monkeypatch.setattr(agent, "_append_auto_context_messages", lambda messages, **kwargs: kwargs["executed_skills"])
    monkeypatch.setattr(
        agent,
        "_execute_delegated_skill",
        lambda *args, **kwargs: {
            "status": "ok",
            "skill": "notion-basic",
            "action": "__delegate__",
            "result": {
                "status": "ok",
                "action": "__delegate__",
                "path": "notion-basic",
                "message": "Delegated skill session completed",
                "data": {
                    "final_response": "明天有 1 個行程。",
                    "tool_calls": 2,
                    "last_tool_result": {},
                },
            },
        },
    )

    reply = agent.run("幫我看看明天有什麼行程")

    assert reply == "明天有 1 個行程。"
    assert len(chat_calls) == 1
