# Ink Terminal UI — Design Spec

**Date:** 2026-03-31  
**Branch:** refactor/agent-modular-structure  
**Status:** Approved

## Overview

Replace the current `TerminalDisplay` (Python + ANSI + prompt_toolkit) with an Ink (React for CLI) based UI, while keeping `python main.py` as the sole entry point and maintaining backward compatibility via automatic fallback.

---

## Architecture

### IPC: Two independent channels

```
python main.py
  └─ InkDisplay
       ├─ TCP socket (127.0.0.1:random) ──────▶  node agent/ui/index.js
       │    Python → Ink: display events (NDJSON)      │
       │                                               │ stdin = real TTY (keyboard)
       └─ subprocess stdout pipe  ◀─────────────────── ┘
            Ink → Python: user input (NDJSON)
```

- **Python → Ink**: `InkDisplay` opens a TCP server on `127.0.0.1:0` (OS-assigned port). Ink connects on startup using `OPENCLAW_IPC_PORT` env var. Display events are sent as newline-delimited JSON.
- **Ink → Python**: Ink writes user input to its stdout as NDJSON. Python reads via subprocess stdout pipe.
- **Keyboard input**: Ink's `stdin` is inherited from the parent process (real TTY), so Ink handles keyboard normally.

### NDJSON Protocol

**Python → Ink (TCP socket):**
```json
{"type": "message", "style": "assistant", "text": "Hello!"}
{"type": "message", "style": "system", "text": "Skill server ready"}
{"type": "message", "style": "think", "text": "step 1: considering query"}
{"type": "message", "style": "tool_call", "text": "step=1 call: search_files"}
{"type": "message", "style": "tool_res", "text": "step=1 result: found 3 files"}
{"type": "message", "style": "memory", "text": "recalled: user prefers brief answers"}
{"type": "message", "style": "command", "text": "Cleared history (5 messages)"}
{"type": "message", "style": "error", "text": "Connection refused"}
{"type": "set_waiting", "text": "thinking..."}
{"type": "clear_waiting"}
{"type": "exit"}
```

**Ink → Python (stdout pipe):**
```json
{"type": "input", "text": "user typed this and pressed Enter"}
```

---

## File Structure

```
agent/
  ui/
    package.json          # dependencies: ink, react, ink-text-input
    index.js              # Ink React app
  utils/
    terminal_display.py   # unchanged — used as fallback
    ink_display.py        # NEW: InkDisplay class
  app/
    application.py        # MODIFIED: one-line change to use InkDisplay with fallback
```

---

## InkDisplay (Python)

Lives in `agent/utils/ink_display.py`. Exposes the exact same public API as `TerminalDisplay`:

| Method | Action |
|--------|--------|
| `agent(text)` | Sends `message` with style `assistant` |
| `system(text)` | Sends `message` with style `system` |
| `system_block(text)` | Same as `system` (leading/trailing blank handled by Ink) |
| `command(text)` | Sends `message` with style `command` |
| `error(text)` | Sends `message` with style `error` |
| `think(step, text)` | Sends `message` with style `think` |
| `tool_call(step, text)` | Sends `message` with style `tool_call` |
| `tool_note(step, text)` | Sends `message` with style `tool_note` |
| `tool_result(step, text)` | Sends `message` with style `tool_res` |
| `memory(text)` | Sends `message` with style `memory` |
| `set_waiting(text)` | Sends `set_waiting` |
| `clear_waiting()` | Sends `clear_waiting` |
| `read_input() -> str` | Blocks until Ink writes a line to stdout; parses JSON; returns `text` |
| `prompt()` | No-op (Ink always shows input box) |
| `set_enabled(cat, bool)` | Stores locally; filters outgoing messages |
| `is_enabled(cat) -> bool` | Returns stored state |
| `states() -> dict` | Returns all category states |
| `capture_events(...)` | In-memory capture (same logic as TerminalDisplay — used by Telegram) |

### Startup

```python
@staticmethod
def is_available() -> bool:
    # 1. Check node is on PATH
    # 2. Check agent/ui/node_modules exists
    ...

def __init__(self):
    # 1. Create TCP server on 127.0.0.1:0
    # 2. Spawn: node agent/ui/index.js
    #    - env: OPENCLAW_IPC_PORT=<port>
    #    - stdin: None (inherit TTY)
    #    - stdout: PIPE
    #    - stderr: None (inherit, so Node errors show in terminal)
    # 3. accept() with 5s timeout
    # 4. Store connection socket
    ...
```

### `application.py` change

```python
# Before:
self.display = TerminalDisplay()

# After:
from .ink_display import InkDisplay
self.display = InkDisplay() if InkDisplay.is_available() else TerminalDisplay()
```

---

## Ink UI (Node.js)

### Layout

```
  ~ think     step 1: considering the query
  | tool      step=1 call: search_files
  | tool      step=1 result: found 3 files
  : assistant Hello! Here are the results...
  # system    Skill server ready

  [/] thinking...          ← spinner (visible only when waiting)
════════════════════════════════════════
> _                        ← ink-text-input
```

### Components

- **`MessageList`**: Array of messages in React state; renders each with icon + label + text in appropriate color.
- **`Spinner`**: Shown when `set_waiting` received; hidden on `clear_waiting`.
- **`InputBox`**: `ink-text-input` at the bottom; on submit writes `{"type":"input","text":"..."}` to stdout and clears field.
- **IPC reader**: `net.createConnection` to TCP server; reads NDJSON lines; dispatches to React state.

### Style mapping

| Style | Icon | Label | Color |
|-------|------|-------|-------|
| `think` | `~` | `think` | gray italic |
| `tool_call` / `tool_note` / `tool_res` | `\|` | `tool` | yellow |
| `memory` | `*` | `memory` | magenta |
| `system` | `#` | `system` | cyan |
| `command` | `>` | `command` | green bold |
| `assistant` | `:` | `assistant` | white |
| `error` | `!` | `error` | red |

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| `node` not on PATH | `is_available()` → False → use `TerminalDisplay` |
| `node_modules` missing | Same fallback; print setup hint |
| Ink fails to connect within 5s | Warn + fallback to `TerminalDisplay` |
| Ink process exits unexpectedly | `read_input()` raises `EOFError` → run loop exits cleanly |
| TCP send fails | Silent drop (agent continues running) |

---

## Setup (first time)

```bash
cd agent/ui
npm install
```

No changes to how the agent is started. If `npm install` has not been run, the agent falls back to `TerminalDisplay` and prints:

```
[system] Ink UI not available (run: cd agent/ui && npm install). Using terminal fallback.
```

---

## Out of Scope

- Scrollback history persistence
- Mouse support
- Theming / color customization
- Telegram-side UI changes
