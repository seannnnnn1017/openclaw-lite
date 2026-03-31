import io
import json
import socket
import subprocess
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.utils.ink_display import InkDisplay


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_display():
    """Create InkDisplay with all I/O mocked out. Returns (display, written_lines)."""
    written_lines = []

    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.stdout = MagicMock()
    mock_proc.stdout.readline.return_value = b""

    mock_server = MagicMock(spec=socket.socket)
    mock_conn = MagicMock(spec=socket.socket)
    mock_server.getsockname.return_value = ("127.0.0.1", 12345)
    mock_server.accept.return_value = (mock_conn, ("127.0.0.1", 99999))

    mock_conn_file = MagicMock()
    mock_conn_file.write.side_effect = written_lines.append
    mock_conn.makefile.return_value = mock_conn_file

    with patch("agent.utils.ink_display.subprocess.Popen", return_value=mock_proc), \
         patch("agent.utils.ink_display.socket.socket", return_value=mock_server):
        d = InkDisplay()

    return d, written_lines


# ---------------------------------------------------------------------------
# is_available()
# ---------------------------------------------------------------------------

def test_is_available_false_when_no_node(tmp_path, monkeypatch):
    monkeypatch.setattr("agent.utils.ink_display.shutil.which", lambda _: None)
    monkeypatch.setattr(InkDisplay, "_UI_DIR", tmp_path)
    assert InkDisplay.is_available() is False


def test_is_available_false_when_no_node_modules(tmp_path, monkeypatch):
    monkeypatch.setattr("agent.utils.ink_display.shutil.which", lambda _: "/usr/bin/node")
    monkeypatch.setattr(InkDisplay, "_UI_DIR", tmp_path)
    # node_modules does NOT exist in tmp_path
    assert InkDisplay.is_available() is False


def test_is_available_true(tmp_path, monkeypatch):
    monkeypatch.setattr("agent.utils.ink_display.shutil.which", lambda _: "/usr/bin/node")
    (tmp_path / "node_modules").mkdir()
    monkeypatch.setattr(InkDisplay, "_UI_DIR", tmp_path)
    assert InkDisplay.is_available() is True


# ---------------------------------------------------------------------------
# _send serialization
# ---------------------------------------------------------------------------

def test_send_writes_ndjson():
    d, written = _make_display()
    d._send({"type": "message", "style": "assistant", "text": "hi"})
    assert len(written) == 1
    parsed = json.loads(written[0].rstrip("\n"))
    assert parsed == {"type": "message", "style": "assistant", "text": "hi"}


# ---------------------------------------------------------------------------
# Display methods
# ---------------------------------------------------------------------------

def test_agent_sends_assistant_message():
    d, written = _make_display()
    d.agent("Hello!")
    assert len(written) == 1
    msg = json.loads(written[0])
    assert msg["type"] == "message"
    assert msg["style"] == "assistant"
    assert msg["text"] == "Hello!"


def test_system_sends_system_message():
    d, written = _make_display()
    d.system("Skill server ready")
    msg = json.loads(written[0])
    assert msg["style"] == "system"
    assert msg["text"] == "Skill server ready"


def test_system_block_sends_system_message():
    d, written = _make_display()
    d.system_block("Block message")
    msg = json.loads(written[0])
    assert msg["style"] == "system"


def test_command_sends_command_message():
    d, written = _make_display()
    d.command("Cleared history")
    msg = json.loads(written[0])
    assert msg["style"] == "command"


def test_error_sends_error_message():
    d, written = _make_display()
    d.error("Something broke")
    msg = json.loads(written[0])
    assert msg["style"] == "error"


def test_think_formats_step():
    d, written = _make_display()
    d.think(2, "evaluating options")
    msg = json.loads(written[0])
    assert msg["style"] == "think"
    assert "step 2" in msg["text"]
    assert "evaluating options" in msg["text"]


def test_tool_call_formats_step():
    d, written = _make_display()
    d.tool_call(1, "search_files")
    msg = json.loads(written[0])
    assert msg["style"] == "tool_call"
    assert "step=1" in msg["text"]
    assert "search_files" in msg["text"]


def test_tool_result_formats_step():
    d, written = _make_display()
    d.tool_result(1, "found 3 files")
    msg = json.loads(written[0])
    assert msg["style"] == "tool_res"
    assert "step=1" in msg["text"]
    assert "found 3 files" in msg["text"]


def test_memory_sends_memory_message():
    d, written = _make_display()
    d.memory("user prefers brief answers")
    msg = json.loads(written[0])
    assert msg["style"] == "memory"


def test_set_waiting_sends_set_waiting():
    d, written = _make_display()
    d.set_waiting("thinking...")
    msg = json.loads(written[0])
    assert msg["type"] == "set_waiting"
    assert msg["text"] == "thinking..."


def test_clear_waiting_sends_clear_waiting():
    d, written = _make_display()
    d.clear_waiting()
    msg = json.loads(written[0])
    assert msg["type"] == "clear_waiting"


def test_prompt_is_noop():
    d, written = _make_display()
    d.prompt()
    assert written == []


# ---------------------------------------------------------------------------
# Category filtering
# ---------------------------------------------------------------------------

def test_disabled_think_category_blocks_think_message():
    d, written = _make_display()
    d.set_enabled("think", False)
    d.think(1, "some thought")
    assert written == []


def test_disabled_tool_category_blocks_tool_call():
    d, written = _make_display()
    d.set_enabled("tool", False)
    d.tool_call(1, "search")
    assert written == []


def test_disabled_category_does_not_block_other_styles():
    d, written = _make_display()
    d.set_enabled("think", False)
    d.agent("Hello")  # assistant style — no category filter
    assert len(written) == 1


def test_is_enabled_default_true():
    d, _ = _make_display()
    assert d.is_enabled("think") is True
    assert d.is_enabled("tool") is True
    assert d.is_enabled("memory") is True
    assert d.is_enabled("system") is True


def test_states_returns_all_categories():
    d, _ = _make_display()
    d.set_enabled("think", False)
    s = d.states()
    assert s["think"] is False
    assert s["tool"] is True
