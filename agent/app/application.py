from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    from core.agent import SimpleAgent
    from scheduling.scheduler import ChatScheduler
    from cfg.loader import Config
    from utils.debug_logger import DebugSessionLogger
    from integrations.lmstudio import LMStudioClient
    from scheduling.runtime import record_task_result
    from utils.doc_generator import generate_system_architecture
    from utils.terminal_display import TerminalDisplay
    from utils.ink_display import InkDisplay
except ImportError:
    from agent.core.agent import SimpleAgent
    from agent.scheduling.scheduler import ChatScheduler
    from agent.cfg.loader import Config
    from agent.utils.debug_logger import DebugSessionLogger
    from agent.integrations.lmstudio import LMStudioClient
    from agent.scheduling.runtime import record_task_result
    from agent.utils.doc_generator import generate_system_architecture
    from agent.utils.terminal_display import TerminalDisplay
    from agent.utils.ink_display import InkDisplay

from .cli import handle_cli_command
from .tasks import task_action_reply_markup
from .telegram_runtime import TelegramRuntime
from .telegram_support import format_scheduled_trigger


class AgentApplication:
    def __init__(self, *, config_path: str | Path | None = None):
        self.agent_root = Path(__file__).resolve().parent.parent
        self.project_root = self.agent_root.parent
        resolved_config_path = (
            Path(config_path).expanduser().resolve()
            if config_path is not None
            else self.agent_root / "config" / "config.json"
        )
        self.config = Config(str(resolved_config_path))
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
        self.debug_logger = DebugSessionLogger(self.agent_root / ".codex-temp" / "debug_sessions")
        self._skill_server_proc: subprocess.Popen | None = None
        self._ensure_skill_server()
        self.main_agent = self._build_agent_session()
        self.scheduler = ChatScheduler(on_event=self.on_scheduled_event)
        self.telegram_runtime = TelegramRuntime(
            config=self.config,
            display=self.display,
            build_agent_session=self._build_agent_session,
            handle_remote_command=self.handle_remote_command,
        )
        architecture_path = generate_system_architecture(self.config)
        self.display.system(f"System doc generated: {architecture_path}")
        self.display.system(f"Debug session log: {self.debug_logger.path}")
        self.debug_logger.log_event(
            "session_start",
            pid=os.getpid(),
            config_path=str(resolved_config_path),
            model=self.config.model,
            skill_count=len(self.config.skills),
            telegram_enabled=self.config.telegram_enabled,
            log_path=str(self.debug_logger.path),
        )

    def _ensure_skill_server(self, timeout: float = 15.0):
        """Start the skill server as a subprocess if it is not already running."""
        url = self.config.skill_server_url.rstrip("/") + "/skills"

        def _is_up() -> bool:
            try:
                urllib.request.urlopen(url, timeout=1)
                return True
            except Exception:
                return False

        if _is_up():
            self.display.system("Skill server already running.")
            return

        server_script = self.agent_root / "skill" / "server.py"
        log_path = self.agent_root / ".codex-temp" / "skill_server.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.display.system(f"Starting skill server: {server_script}")

        # Redirect stdout+stderr to a log file so the pipe buffer never fills up.
        log_file = open(log_path, "w", encoding="utf-8")
        self._skill_server_proc = subprocess.Popen(
            [sys.executable, "-u", str(server_script)],
            cwd=str(self.agent_root),
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=log_file,
            env={**os.environ, "PYTHONPATH": str(self.agent_root)},
        )
        log_file.close()  # parent doesn't need to hold it; child keeps its own fd

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            # Process died — surface the log for diagnosis.
            if self._skill_server_proc.poll() is not None:
                log_tail = ""
                try:
                    log_tail = log_path.read_text(encoding="utf-8", errors="replace").strip()[-2000:]
                except Exception:
                    pass
                self.display.error(
                    f"Skill server process exited (code {self._skill_server_proc.returncode})."
                    + (f"\n{log_tail}" if log_tail else "")
                )
                self._skill_server_proc = None
                return
            if _is_up():
                self.display.system(
                    f"Skill server ready (pid={self._skill_server_proc.pid}). "
                    f"Log: {log_path}"
                )
                return
            time.sleep(0.3)

        log_tail = ""
        try:
            log_tail = log_path.read_text(encoding="utf-8", errors="replace").strip()[-2000:]
        except Exception:
            pass
        self.display.error(
            "Skill server did not become ready in time — skill calls may fail."
            + (f"\n{log_tail}" if log_tail else "")
        )

    def _build_agent_session(self) -> SimpleAgent:
        return SimpleAgent(
            config=self.config,
            client=LMStudioClient(base_url=self.config.base_url, api_key=self.config.api_key),
            display=self.display,
            debug_logger=self.debug_logger,
        )

    def reload_runtime(self) -> Path:
        self.config.reload_now()
        self.main_agent.refresh_runtime_clients()
        self.telegram_runtime.refresh_runtime_clients()
        self.debug_logger.log_event(
            "manual_reload",
            model=self.config.model,
            skill_count=len(self.config.skills),
        )
        return generate_system_architecture(self.config)

    def _handle_cli_command(self, command_line: str, *, agent: SimpleAgent) -> dict:
        return handle_cli_command(
            command_line,
            config=self.config,
            agent=agent,
            project_root=self.project_root,
            on_reload=self.reload_runtime,
        )

    def handle_remote_command(self, command_text: str, session_agent: SimpleAgent) -> str:
        command_result = self._handle_cli_command(command_text, agent=session_agent)
        if not command_result["handled"]:
            return ""
        if command_result["exit_requested"]:
            return "This command is only available in the terminal session."
        return command_result["message"].strip() or "Done."

    def on_scheduled_event(self, event: dict):
        live_chat_ids = self.telegram_runtime.delivery_chat_ids()
        with self.display.capture_events(
            categories={"tool"},
            on_event=self.telegram_runtime.build_tool_streamer(chat_ids=live_chat_ids),
        ):
            reply = ""

            if event.get("status") == "error" and not event.get("dispatch_prompt"):
                error_text = str(event.get("error", "")).strip() or "Unknown scheduler error"
                self.display.system_block(f"Scheduled task error: {error_text}")
                self.telegram_runtime.broadcast_text(
                    f"Scheduled task error: {error_text}",
                    label="scheduled-task",
                )
                self.display.prompt()
                return

            text = format_scheduled_trigger(event)
            self.display.system_block(text)

            try:
                reply = self.main_agent.run(
                    event["dispatch_prompt"],
                    debug_context={
                        "source": "scheduler",
                        "task_id": event.get("task_id"),
                        "task_name": event.get("task_name"),
                        "trigger": event.get("trigger"),
                        "scheduled_for": event.get("scheduled_for"),
                    },
                )
                status = "error" if reply.strip().startswith("[ERROR]") else "ok"
                updated_task = record_task_result(
                    event.get("task_name", ""),
                    status=status,
                    response_text="" if status == "error" else reply,
                    error_text=reply if status == "error" else "",
                    trigger=event.get("trigger", ""),
                    scheduled_for=event.get("scheduled_for", ""),
                )
                self.display.agent(reply)
            except Exception as exc:
                error_text = str(exc)
                reply = f"[ERROR] {error_text}"
                updated_task = record_task_result(
                    event.get("task_name", ""),
                    status="error",
                    response_text="",
                    error_text=error_text,
                    trigger=event.get("trigger", ""),
                    scheduled_for=event.get("scheduled_for", ""),
                )
                self.display.system_block(f"Scheduled task error: {error_text}")

        reply_markup = None
        task_id = str(event.get("task_id", "")).strip()
        if updated_task and task_id:
            reply_markup = task_action_reply_markup(task_id)

        final_parts = [format_scheduled_trigger(event)]
        if str(reply or "").strip():
            final_parts.append(str(reply).strip())
        self.telegram_runtime.broadcast_text(
            "\n\n".join(final_parts),
            label="scheduled-task",
            reply_markup=reply_markup,
        )

        self.display.prompt()

    def run(self):
        self.scheduler.start()
        self.telegram_runtime.start()

        try:
            while True:
                user_input = self.display.read_input().strip()
                if user_input.lower() in {"exit", "quit"}:
                    break

                command_result = self._handle_cli_command(user_input, agent=self.main_agent)
                if command_result["handled"]:
                    message = command_result["message"].strip()
                    if message:
                        self.display.command(message)
                    if command_result["exit_requested"]:
                        break
                    continue

                try:
                    try:
                        reply = self.main_agent.run(
                            user_input,
                            debug_context={
                                "source": "terminal",
                                "session": "main",
                            },
                        )
                    finally:
                        self.display.clear_waiting()
                    self.display.agent(reply)
                except Exception as exc:
                    self.display.error(str(exc))
        finally:
            self.debug_logger.log_event("session_stop")
            self.telegram_runtime.stop()
            self.scheduler.stop()
            if self._skill_server_proc is not None:
                self._skill_server_proc.terminate()
                self._skill_server_proc = None
