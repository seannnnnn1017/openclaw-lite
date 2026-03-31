# Ink Terminal UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `TerminalDisplay` with an Ink (React for CLI) UI that Python spawns as a subprocess, communicating via TCP (Python→Ink display events) and stdout pipe (Ink→Python user input), while keeping `python main.py` as the sole entry point.

**Architecture:** Python's `InkDisplay` class opens a TCP server, spawns `node agent/ui/index.js`, and sends NDJSON display events over the socket. Ink renders to `process.stderr` (real TTY), reads keyboard via `process.stdin` (real TTY), and writes user input as NDJSON to `process.stdout` (pipe to Python). If Node.js or `node_modules` is absent, `application.py` falls back to the existing `TerminalDisplay`.

**Tech Stack:** Python 3 (socket, subprocess, threading), Node.js 24, Ink 5 (React 18), ink-text-input 6, pytest 8

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `agent/ui/package.json` | Ink dependencies |
| Create | `agent/ui/index.js` | Ink React app (renders UI, IPC reader, sends user input) |
| Create | `agent/utils/ink_display.py` | InkDisplay Python class |
| Create | `tests/conftest.py` | sys.path setup for pytest |
| Create | `tests/utils/test_ink_display.py` | Unit tests for InkDisplay |
| Modify | `agent/app/application.py` | Use InkDisplay with fallback |

---

## Task 1: Ink UI — package.json + index.js

**Files:**
- Create: `agent/ui/package.json`
- Create: `agent/ui/index.js`

> **Note:** Ink renders to `process.stderr` (real TTY visible to user). User input goes to `process.stdout` (piped to Python). Keyboard input comes from `process.stdin` (real TTY, inherited).

- [ ] **Step 1: Create `agent/ui/package.json`**

```json
{
  "name": "openclaw-ui",
  "version": "1.0.0",
  "type": "module",
  "dependencies": {
    "ink": "^5.2.0",
    "react": "^18.3.1",
    "ink-text-input": "^6.0.0"
  }
}
```

- [ ] **Step 2: Create `agent/ui/index.js`**

```js
import React, { useState, useEffect } from 'react';
import { render, Box, Text, useApp } from 'ink';
import TextInput from 'ink-text-input';
import net from 'net';

const STYLES = {
  think:     { icon: '~', label: 'think    ', color: 'gray' },
  tool_call: { icon: '|', label: 'tool     ', color: 'yellow' },
  tool_note: { icon: '|', label: 'tool     ', color: 'yellow' },
  tool_res:  { icon: '|', label: 'tool     ', color: 'yellow' },
  memory:    { icon: '*', label: 'memory   ', color: 'magenta' },
  system:    { icon: '#', label: 'system   ', color: 'cyan' },
  command:   { icon: '>', label: 'command  ', color: 'green' },
  assistant: { icon: ':', label: 'assistant', color: 'white' },
  error:     { icon: '!', label: 'error    ', color: 'red' },
};

function App() {
  const [messages, setMessages] = useState([]);
  const [waiting, setWaiting] = useState('');
  const [inputValue, setInputValue] = useState('');
  const { exit } = useApp();

  useEffect(() => {
    const port = parseInt(process.env.OPENCLAW_IPC_PORT, 10);
    const client = net.createConnection(port, '127.0.0.1');
    let buffer = '';

    client.on('data', (chunk) => {
      buffer += chunk.toString();
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const event = JSON.parse(line);
          if (event.type === 'message') {
            setMessages(prev => [...prev, event]);
          } else if (event.type === 'set_waiting') {
            setWaiting(event.text);
          } else if (event.type === 'clear_waiting') {
            setWaiting('');
          } else if (event.type === 'exit') {
            exit();
          }
        } catch (_) {}
      }
    });

    client.on('error', () => exit());
    client.on('close', () => exit());

    return () => client.destroy();
  }, []);

  const handleSubmit = (value) => {
    process.stdout.write(JSON.stringify({ type: 'input', text: value }) + '\n');
    setInputValue('');
  };

  const cols = process.stderr.columns || 80;
  const divider = '═'.repeat(cols);

  return (
    <Box flexDirection="column">
      <Box flexDirection="column">
        {messages.map((msg, i) => {
          const s = STYLES[msg.style] || STYLES.assistant;
          return (
            <Box key={i}>
              <Text color={s.color}>{s.icon} {s.label} </Text>
              <Text>{msg.text}</Text>
            </Box>
          );
        })}
      </Box>
      {waiting ? (
        <Box marginTop={1}>
          <Text color="cyan">[/] {waiting}</Text>
        </Box>
      ) : null}
      <Text>{divider}</Text>
      <Box>
        <Text color="green" bold>{'> '}</Text>
        <TextInput
          value={inputValue}
          onChange={setInputValue}
          onSubmit={handleSubmit}
        />
      </Box>
    </Box>
  );
}

// Render to stderr so process.stdout stays clean for Python IPC
render(<App />, { stdout: process.stderr });
```

- [ ] **Step 3: Install dependencies**

```bash
cd agent/ui
npm install
```

Expected: `node_modules/` directory created, no errors.

- [ ] **Step 4: Smoke-test the Ink app manually**

In one terminal:
```bash
# Start a simple TCP echo server on port 9999
python -c "
import socket, time
s = socket.socket(); s.bind(('127.0.0.1', 9999)); s.listen(1)
conn, _ = s.accept()
time.sleep(0.5)
conn.sendall(b'{\"type\":\"message\",\"style\":\"system\",\"text\":\"Hello from Python\"}\n')
time.sleep(0.5)
conn.sendall(b'{\"type\":\"set_waiting\",\"text\":\"thinking...\"}\n')
time.sleep(2)
conn.sendall(b'{\"type\":\"clear_waiting\"}\n')
time.sleep(60)
"
```

In a second terminal:
```bash
cd agent/ui
OPENCLAW_IPC_PORT=9999 node index.js
```

Expected: Ink UI renders, shows system message, spinner appears then disappears. Typing in the input box and pressing Enter should print `{"type":"input","text":"..."}` to stdout (visible in the terminal since stdout isn't piped here).

- [ ] **Step 5: Commit**

```bash
git add agent/ui/package.json agent/ui/index.js agent/ui/package-lock.json
git commit -m "feat: add Ink terminal UI (Node.js)"
```

---

## Task 2: InkDisplay — core structure + `is_available` tests

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/utils/__init__.py`
- Create: `tests/utils/test_ink_display.py` (partial — `is_available` only)
- Create: `agent/utils/ink_display.py` (partial — `is_available` + `__init__` + `_send` + `close`)

- [ ] **Step 1: Create `tests/conftest.py`**

```python
import sys
from pathlib import Path

# Add project root to sys.path so "from agent.utils.ink_display import ..." works
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
```

- [ ] **Step 2: Create `tests/utils/__init__.py`**

Empty file:
```python
```

- [ ] **Step 3: Write failing tests for `is_available()`**

Create `tests/utils/test_ink_display.py`:

```python
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
```

- [ ] **Step 4: Run tests — expect ImportError (module doesn't exist yet)**

```bash
cd E:\重要文件\openclaw-lite
python -m pytest tests/utils/test_ink_display.py::test_is_available_false_when_no_node -v
```

Expected: `ModuleNotFoundError: No module named 'agent.utils.ink_display'`

- [ ] **Step 5: Create `agent/utils/ink_display.py`**

```python
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path


class InkDisplay:
    _UI_DIR: Path = Path(__file__).resolve().parent.parent / "ui"

    # ------------------------------------------------------------------
    # Availability check
    # ------------------------------------------------------------------

    @staticmethod
    def is_available() -> bool:
        if shutil.which("node") is None:
            return False
        return (InkDisplay._UI_DIR / "node_modules").is_dir()

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------

    def __init__(self):
        self._lock = threading.Lock()
        self._capture_lock = threading.Lock()
        self._captures: dict[int, list[dict]] = {}
        self._enabled: dict[str, bool] = {
            "think": True,
            "tool": True,
            "memory": True,
            "system": True,
        }

        # TCP server: Python → Ink
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        port = self._server.getsockname()[1]

        # Spawn Ink subprocess
        ui_script = self._UI_DIR / "index.js"
        self._proc = subprocess.Popen(
            ["node", str(ui_script)],
            stdin=None,           # inherit: real TTY for keyboard
            stdout=subprocess.PIPE,  # pipe: Python reads user input
            stderr=None,          # inherit: Ink renders UI here
            env={**os.environ, "OPENCLAW_IPC_PORT": str(port)},
        )

        # Accept Ink's connection (5s timeout)
        self._server.settimeout(5.0)
        try:
            self._conn, _ = self._server.accept()
        except socket.timeout:
            self._proc.terminate()
            raise RuntimeError("Ink UI did not connect within 5 seconds")
        self._conn.settimeout(None)
        self._conn_file = self._conn.makefile("w", encoding="utf-8")

    # ------------------------------------------------------------------
    # IPC: send event to Ink
    # ------------------------------------------------------------------

    def _send(self, event: dict) -> None:
        try:
            line = json.dumps(event, ensure_ascii=False) + "\n"
            with self._lock:
                self._conn_file.write(line)
                self._conn_file.flush()
        except Exception:
            pass  # silent drop — agent must not crash on UI failure

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._send({"type": "exit"})
        try:
            self._conn.close()
        except Exception:
            pass
        try:
            self._server.close()
        except Exception:
            pass
        if self._proc is not None:
            self._proc.terminate()
            self._proc = None
```

- [ ] **Step 6: Run tests — expect PASS**

```bash
python -m pytest tests/utils/test_ink_display.py::test_is_available_false_when_no_node tests/utils/test_ink_display.py::test_is_available_false_when_no_node_modules tests/utils/test_ink_display.py::test_is_available_true -v
```

Expected: `3 passed`

- [ ] **Step 7: Commit**

```bash
git add agent/utils/ink_display.py tests/conftest.py tests/utils/__init__.py tests/utils/test_ink_display.py
git commit -m "feat: add InkDisplay core and is_available tests"
```

---

## Task 3: InkDisplay — display methods + category filtering

**Files:**
- Modify: `agent/utils/ink_display.py` (add `_emit`, `_category_for_style`, all display methods, `set_enabled`, `is_enabled`, `states`, `prompt`)
- Modify: `tests/utils/test_ink_display.py` (add tests for display methods)

- [ ] **Step 1: Write failing tests for display methods**

Append to `tests/utils/test_ink_display.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect failures**

```bash
python -m pytest tests/utils/test_ink_display.py -v -k "not is_available"
```

Expected: Multiple `AttributeError` / `AssertionError` failures (methods not yet implemented).

- [ ] **Step 3: Add display methods to `agent/utils/ink_display.py`**

Append after `close()`:

```python
    # ------------------------------------------------------------------
    # Category helpers
    # ------------------------------------------------------------------

    _STYLE_CATEGORY: dict[str, str] = {
        "think": "think",
        "tool_call": "tool",
        "tool_note": "tool",
        "tool_res": "tool",
        "memory": "memory",
        "system": "system",
    }

    def _emit(self, style: str, text: str, *, notify: bool = True) -> None:
        category = self._STYLE_CATEGORY.get(style)
        if category and not self.is_enabled(category):
            return
        if notify and category:
            self._record_event(style=style, text=str(text), category=category)
        self._send({"type": "message", "style": style, "text": str(text)})

    # ------------------------------------------------------------------
    # Display methods (same API as TerminalDisplay)
    # ------------------------------------------------------------------

    def agent(self, text: str) -> None:
        self._emit("assistant", text)

    def system(self, text: str, *, notify: bool = True) -> None:
        self._emit("system", text, notify=notify)

    def system_block(self, text: str, *, notify: bool = True) -> None:
        self._emit("system", text, notify=notify)

    def command(self, text: str) -> None:
        self._emit("command", text)

    def error(self, text: str) -> None:
        self._emit("error", text)

    def think(self, step: int, text: str) -> None:
        self._emit("think", f"step {step}: {text}")

    def tool_call(self, step: int, text: str) -> None:
        self._emit("tool_call", f"step={step} call: {text}")

    def tool_note(self, step: int, text: str) -> None:
        self._emit("tool_note", f"step={step} note: {text}")

    def tool_result(self, step: int, text: str) -> None:
        self._emit("tool_res", f"step={step} result: {text}")

    def memory(self, text: str) -> None:
        self._emit("memory", text)

    def set_waiting(self, text: str) -> None:
        self._send({"type": "set_waiting", "text": str(text or "")})

    def clear_waiting(self) -> None:
        self._send({"type": "clear_waiting"})

    def prompt(self) -> None:
        pass  # no-op: Ink always shows the input box

    # ------------------------------------------------------------------
    # Category enable/disable
    # ------------------------------------------------------------------

    def set_enabled(self, category: str, enabled: bool) -> None:
        self._enabled[category] = bool(enabled)

    def is_enabled(self, category: str) -> bool:
        return self._enabled.get(category, True)

    def states(self) -> dict[str, bool]:
        return dict(self._enabled)
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
python -m pytest tests/utils/test_ink_display.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add agent/utils/ink_display.py tests/utils/test_ink_display.py
git commit -m "feat: add InkDisplay display methods and category filtering"
```

---

## Task 4: InkDisplay — `capture_events` + `read_input`

**Files:**
- Modify: `agent/utils/ink_display.py` (add `_record_event`, `capture_events`, `read_input`)
- Modify: `tests/utils/test_ink_display.py` (add tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/utils/test_ink_display.py`:

```python
# ---------------------------------------------------------------------------
# capture_events
# ---------------------------------------------------------------------------

def test_capture_events_records_tool_events():
    d, _ = _make_display()
    with d.capture_events(categories={"tool"}) as events:
        d.tool_call(1, "search_files")
        d.agent("Hello")  # not a tool event — should not be captured
    assert len(events) == 1
    assert events[0]["category"] == "tool"
    assert "search_files" in events[0]["text"]


def test_capture_events_records_all_when_no_filter():
    d, _ = _make_display()
    with d.capture_events() as events:
        d.think(1, "pondering")
        d.tool_call(1, "search")
        d.memory("something remembered")
    assert len(events) == 3


def test_capture_events_on_event_callback():
    d, _ = _make_display()
    received = []
    with d.capture_events(categories={"tool"}, on_event=received.append):
        d.tool_call(1, "x")
    assert len(received) == 1
    assert received[0]["category"] == "tool"


def test_capture_events_disabled_category_not_captured():
    d, _ = _make_display()
    d.set_enabled("think", False)
    with d.capture_events(categories={"think"}) as events:
        d.think(1, "suppressed thought")
    # disabled → _emit returns early → no event recorded
    assert events == []


def test_capture_events_context_manager_cleans_up():
    d, _ = _make_display()
    with d.capture_events() as events:
        pass
    tid = threading.get_ident()
    # After context exits, captures dict should not contain this thread
    assert tid not in d._captures


# ---------------------------------------------------------------------------
# read_input
# ---------------------------------------------------------------------------

def test_read_input_returns_text_from_json():
    d, _ = _make_display()
    line = json.dumps({"type": "input", "text": "hello world"}).encode() + b"\n"
    d._proc.stdout.readline.return_value = line
    result = d.read_input()
    assert result == "hello world"


def test_read_input_raises_eof_when_process_closes():
    d, _ = _make_display()
    d._proc.stdout.readline.return_value = b""
    with pytest.raises(EOFError):
        d.read_input()
```

- [ ] **Step 2: Run tests — expect failures**

```bash
python -m pytest tests/utils/test_ink_display.py -v -k "capture or read_input"
```

Expected: `AttributeError: 'InkDisplay' object has no attribute '_record_event'` and similar.

- [ ] **Step 3: Add `_record_event`, `capture_events`, `read_input` to `agent/utils/ink_display.py`**

Append after `states()`:

```python
    # ------------------------------------------------------------------
    # Event capture (used by Telegram runtime)
    # ------------------------------------------------------------------

    def _record_event(self, *, style: str, text: str, category: str) -> None:
        tid = threading.get_ident()
        with self._capture_lock:
            captures = list(self._captures.get(tid, []))
        if not captures:
            return
        event = {"prefix": style, "text": text, "rendered": text, "category": category}
        listeners = []
        for cap in captures:
            cats = cap["categories"]
            if cats and category not in cats:
                continue
            cap["events"].append(dict(event))
            if cap.get("on_event"):
                listeners.append(cap["on_event"])
        for fn in listeners:
            try:
                fn(dict(event))
            except Exception:
                pass

    @contextmanager
    def capture_events(self, *, categories=None, on_event=None):
        capture = {
            "categories": set(categories or []),
            "events": [],
            "on_event": on_event,
        }
        tid = threading.get_ident()
        with self._capture_lock:
            self._captures.setdefault(tid, []).append(capture)
        try:
            yield capture["events"]
        finally:
            with self._capture_lock:
                caps = self._captures.get(tid, [])
                if capture in caps:
                    caps.remove(capture)
                if not caps:
                    self._captures.pop(tid, None)

    # ------------------------------------------------------------------
    # User input
    # ------------------------------------------------------------------

    def read_input(self) -> str:
        import json as _json
        line = self._proc.stdout.readline()
        if not line:
            raise EOFError("Ink process closed stdout")
        return _json.loads(line.decode("utf-8").strip())["text"]
```

- [ ] **Step 4: Run all tests — expect PASS**

```bash
python -m pytest tests/utils/test_ink_display.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add agent/utils/ink_display.py tests/utils/test_ink_display.py
git commit -m "feat: add InkDisplay capture_events and read_input"
```

---

## Task 5: Wire InkDisplay into application.py + smoke test

**Files:**
- Modify: `agent/app/application.py` (replace `TerminalDisplay()` with InkDisplay fallback)

- [ ] **Step 1: Read current `application.py` imports section**

Open `agent/app/application.py` and locate the import block (lines 1–28) and the `__init__` method (line 37–69). Confirm `self.display = TerminalDisplay()` is on line 46.

- [ ] **Step 2: Add `ink_display` import to `application.py`**

In `agent/app/application.py`, add the import after the existing try/except import block (after line 28):

```python
try:
    from utils.ink_display import InkDisplay
except ImportError:
    from agent.utils.ink_display import InkDisplay
```

- [ ] **Step 3: Replace `TerminalDisplay()` with InkDisplay fallback**

Find this line in `__init__` (around line 46):
```python
        self.display = TerminalDisplay()
```

Replace with:
```python
        if InkDisplay.is_available():
            try:
                self.display = InkDisplay()
            except Exception as exc:
                print(f"[system] Ink UI failed to start ({exc}). Using terminal fallback.")
                self.display = TerminalDisplay()
        else:
            if not (InkDisplay._UI_DIR / "node_modules").is_dir():
                print("[system] Ink UI not available (run: cd agent/ui && npm install). Using terminal fallback.")
            self.display = TerminalDisplay()
```

- [ ] **Step 4: Run all unit tests to confirm nothing is broken**

```bash
python -m pytest tests/ -v
```

Expected: All tests pass.

- [ ] **Step 5: Smoke test — run the agent**

```bash
python agent/main.py
```

Expected:
- Ink UI renders in the terminal (system messages appear, input box at bottom)
- Typing a message and pressing Enter sends it to the agent and gets a response
- `/help` command shows help text
- `/exit` exits cleanly

If `node_modules` is not installed, expected fallback message:
```
[system] Ink UI not available (run: cd agent/ui && npm install). Using terminal fallback.
```

- [ ] **Step 6: Commit**

```bash
git add agent/app/application.py
git commit -m "feat: wire InkDisplay into AgentApplication with TerminalDisplay fallback"
```

---

## Self-Review

**Spec coverage:**
- [x] `python main.py` entry point unchanged
- [x] TCP socket Python→Ink
- [x] stdout pipe Ink→Python
- [x] Ink keyboard via inherited stdin (TTY)
- [x] Ink renders to stderr (real TTY)
- [x] NDJSON protocol (all event types)
- [x] Same public API as TerminalDisplay
- [x] `is_available()` fallback conditions
- [x] Fallback to TerminalDisplay when Node.js absent
- [x] Fallback when node_modules absent with setup hint
- [x] `capture_events` for Telegram
- [x] `prompt()` is no-op
- [x] Style mapping (all 7 styles)
- [x] `close()` sends exit event

**Gaps:** None.
