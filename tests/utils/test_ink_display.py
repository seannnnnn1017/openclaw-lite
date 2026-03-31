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
