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
