import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def test_info_returns_ok():
    from agent.SKILLs.workspace_context.scripts.workspace_tool import run
    result = run(action="info")
    assert result["status"] == "ok"
    assert result["action"] == "info"


def test_info_cwd_is_absolute():
    from agent.SKILLs.workspace_context.scripts.workspace_tool import run
    result = run(action="info")
    cwd = result["data"]["cwd"]
    assert Path(cwd).is_absolute()


def test_info_includes_expected_keys():
    from agent.SKILLs.workspace_context.scripts.workspace_tool import run
    result = run(action="info")
    data = result["data"]
    assert "cwd" in data
    assert "project_root" in data
    assert "agent_dir" in data
    assert "memories_dir" in data
    assert "skills_dir" in data


def test_unknown_action_returns_error():
    from agent.SKILLs.workspace_context.scripts.workspace_tool import run
    result = run(action="unknown_action")
    assert result["status"] == "error"
    assert "unknown_action" in result["message"]
