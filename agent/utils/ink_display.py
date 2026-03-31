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
            stdin=None,              # inherit: real TTY for keyboard
            stdout=subprocess.PIPE,  # pipe: Python reads user input
            stderr=None,             # inherit: Ink renders UI here
            env={**os.environ, "OPENCLAW_IPC_PORT": str(port), "FORCE_COLOR": "3"},
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

    # ------------------------------------------------------------------
    # Style → category mapping
    # ------------------------------------------------------------------

    _STYLE_CATEGORY: dict[str, str] = {
        "think": "think",
        "tool_call": "tool",
        "tool_note": "tool",
        "tool_res": "tool",
        "memory": "memory",
        "system": "system",
    }

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
    # Internal emit
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # User input
    # ------------------------------------------------------------------

    def read_input(self) -> str:
        line = self._proc.stdout.readline()
        if not line:
            raise EOFError("Ink process closed stdout")
        return json.loads(line.decode("utf-8").strip())["text"]
