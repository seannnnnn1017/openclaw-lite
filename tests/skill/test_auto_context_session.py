import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agent.skill.auto_context import normalize_auto_context, collect_auto_context_messages


def test_normalize_once_per_session_true():
    config = {
        "action": "info",
        "args": {},
        "trigger": {"mode": "always"},
        "once_per_session": True,
        "once_per_turn": False,
        "success_prompt": "ok",
        "error_prompt": "err",
    }
    result = normalize_auto_context(config)
    assert result is not None
    assert result["once_per_session"] is True


def test_normalize_once_per_session_default_false():
    config = {
        "action": "info",
        "args": {},
        "trigger": {"mode": "always"},
        "success_prompt": "ok",
        "error_prompt": "err",
    }
    result = normalize_auto_context(config)
    assert result is not None
    assert result["once_per_session"] is False


def _make_fake_skill(name: str, once_per_session: bool = False, once_per_turn: bool = True):
    """Build a minimal skill dict with a no-op tool."""
    return {
        "name": name,
        "execution_mode": "default",
        "path": "",
        "auto_context": {
            "action": "noop",
            "args": {},
            "trigger_mode": "always",
            "contains_any": [],
            "regex_any": [],
            "once_per_session": once_per_session,
            "once_per_turn": once_per_turn,
            "success_prompt": "ctx: {result_json}",
            "error_prompt": "err: {result_json}",
        },
        "tool": {},
        "enabled": True,
        "metadata": {"command-tool": "noop"},
    }


def test_collect_skips_when_in_session_executed():
    """A once_per_session skill already in session_executed should not run."""
    skill = _make_fake_skill("ws", once_per_session=True)
    session_executed = {"ws"}

    messages, updated_turn, updated_session = collect_auto_context_messages(
        [skill],
        user_input="hello",
        session_executed_skills=session_executed,
    )
    assert messages == []
    assert "ws" in updated_session


def test_collect_runs_when_not_in_session_executed(monkeypatch):
    """A once_per_session skill NOT in session_executed should run."""
    import agent.skill.auto_context as ac_mod

    def fake_execute(runtime, *, skill_name, auto_context):
        return {"status": "ok", "skill": skill_name, "action": "noop", "result": {"data": {}}}

    monkeypatch.setattr(ac_mod, "_execute_auto_context_skill", fake_execute)

    skill = _make_fake_skill("ws", once_per_session=True)
    session_executed: set[str] = set()

    messages, updated_turn, updated_session = collect_auto_context_messages(
        [skill],
        user_input="hello",
        session_executed_skills=session_executed,
    )
    assert len(messages) == 1
    assert "ws" in updated_session
