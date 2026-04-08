from agent.integrations.lmstudio import LMStudioClient
from agent.integrations.lmstudio_model_manager import LMStudioModelManager


def test_ensure_model_skips_when_context_window_disabled():
    manager = LMStudioModelManager(base_url="http://localhost:1234/v1", api_key="")

    result = manager.ensure_model(model_name="qwen/test", context_window=0)

    assert result["status"] == "skipped"
    assert "disabled" in result["message"]


def test_ensure_model_accepts_already_loaded_matching_instance(monkeypatch):
    manager = LMStudioModelManager(base_url="http://localhost:1234/v1", api_key="")

    monkeypatch.setattr(
        manager,
        "list_models",
        lambda: [
            {
                "key": "qwen/test",
                "max_context_length": 32768,
                "loaded_instances": [
                    {
                        "id": "qwen/test",
                        "config": {"context_length": 16384},
                    }
                ],
            }
        ],
    )

    result = manager.ensure_model(model_name="qwen/test", context_window=16384)

    assert result["status"] == "ok"
    assert result["changed"] is False
    assert result["instance_id"] == "qwen/test"


def test_ensure_model_reloads_when_context_differs(monkeypatch):
    manager = LMStudioModelManager(base_url="http://localhost:1234/v1", api_key="")
    unloads = []
    loads = []

    monkeypatch.setattr(
        manager,
        "list_models",
        lambda: [
            {
                "key": "qwen/test",
                "max_context_length": 32768,
                "loaded_instances": [
                    {
                        "id": "qwen/test",
                        "config": {"context_length": 8192},
                    }
                ],
            }
        ],
    )
    monkeypatch.setattr(
        manager,
        "unload_instance",
        lambda instance_id: unloads.append(instance_id) or {"instance_id": instance_id},
    )
    monkeypatch.setattr(
        manager,
        "load_model",
        lambda *, model_key, context_window: loads.append((model_key, context_window)) or {
            "instance_id": model_key,
            "load_config": {"context_length": context_window},
        },
    )

    result = manager.ensure_model(model_name="qwen/test", context_window=16384)

    assert unloads == ["qwen/test"]
    assert loads == [("qwen/test", 16384)]
    assert result["status"] == "ok"
    assert result["changed"] is True
    assert result["context_window"] == 16384


def test_ensure_model_rejects_context_beyond_model_limit(monkeypatch):
    manager = LMStudioModelManager(base_url="http://localhost:1234/v1", api_key="")

    monkeypatch.setattr(
        manager,
        "list_models",
        lambda: [
            {
                "key": "qwen/test",
                "max_context_length": 8192,
                "loaded_instances": [],
            }
        ],
    )

    result = manager.ensure_model(model_name="qwen/test", context_window=16384)

    assert result["status"] == "error"
    assert result["max_context_length"] == 8192


def test_lmstudio_client_ensures_model_before_chat(monkeypatch):
    client = LMStudioClient(
        base_url="http://localhost:1234/v1",
        api_key="",
        context_window=4096,
        ensure_model_loaded=True,
    )
    ensured = []
    create_calls = []

    monkeypatch.setattr(
        client.model_manager,
        "ensure_model",
        lambda **kwargs: ensured.append(kwargs) or {"status": "ok", "changed": False},
    )

    class _FakeMessage:
        content = "hello"

    class _FakeChoice:
        message = _FakeMessage()

    class _FakeResponse:
        choices = [_FakeChoice()]

    monkeypatch.setattr(
        client.client.chat.completions,
        "create",
        lambda **kwargs: create_calls.append(kwargs) or _FakeResponse(),
    )

    class _Request:
        model = "qwen/test"
        temperature = 0.1
        max_tokens = 128
        stream = False

        def to_dict(self):
            return {"messages": [{"role": "user", "content": "hi"}]}

    result = client.chat(_Request())

    assert result == "hello"
    assert ensured == [
        {
            "model_name": "qwen/test",
            "context_window": 4096,
            "load_model_key": "qwen/test",
        }
    ]
    assert create_calls and create_calls[0]["model"] == "qwen/test"
