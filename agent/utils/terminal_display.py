import sys
import threading
from contextlib import contextmanager
from datetime import datetime
from shutil import get_terminal_size

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.formatted_text import ANSI
    from prompt_toolkit.patch_stdout import patch_stdout
except ImportError:
    PromptSession = None
    ANSI = None
    patch_stdout = None

# ANSI codes
_R = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_ITALIC = "\033[3m"

_RED = "\033[31m"
_YELLOW = "\033[33m"
_BLUE = "\033[34m"
_MAGENTA = "\033[35m"
_CYAN = "\033[36m"

_GRAY = "\033[90m"
_BWHITE = "\033[97m"
_BGREEN = "\033[92m"


def _enable_windows_ansi() -> bool:
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        k32.GetConsoleMode(h, ctypes.byref(mode))
        k32.SetConsoleMode(h, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        return True
    except Exception:
        return False


_VT_OK = _enable_windows_ansi()


def _color_supported() -> bool:
    import os

    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return _VT_OK and hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


_STYLES: dict[str, tuple[str, str, str, str]] = {
    "think": ("~", "thinking", _GRAY, _DIM + _ITALIC),
    "tool_call": ("|", "tool", _YELLOW, ""),
    "tool_note": ("|", "tool", _YELLOW, _DIM),
    "tool_res": ("|", "tool", _YELLOW, _DIM),
    "memory": ("*", "memory", _MAGENTA, ""),
    "system": ("#", "system", _CYAN, ""),
    "compact": ("%", "compact", _BLUE, _DIM),
    "command": (">", "command", _BGREEN, _BOLD),
    "assistant": (":", "assistant", "", _BWHITE),
    "error": ("!", "error", _RED, _RED),
}

_LABEL_WIDTH = 9
_INDENT = "  "
_PREFIX_LEN = len(_INDENT) + 1 + 1 + _LABEL_WIDTH + 1
_CONTINUATION = " " * _PREFIX_LEN
_RULE_CHAR = "="


class TerminalDisplay:
    def __init__(self, color: bool | None = None):
        self._lock = threading.Lock()
        self._capture_lock = threading.Lock()
        self._captures: dict[int, list[dict]] = {}
        self._color = _color_supported() if color is None else bool(color)
        self._enabled = {
            "think": True,
            "tool": True,
            "memory": True,
            "system": True,
        }
        self._prompt_active = False
        self._status_footer_text = ""
        self._status_footer_visible = False
        self._waiting_base_text = ""
        self._spinner_frames = ("-", "\\", "|", "/")
        self._spinner_index = 0
        self._spinner_interval = 0.12
        self._spinner_stop_event: threading.Event | None = None
        self._spinner_thread: threading.Thread | None = None
        self._hud_model: str = ""
        self._hud_token_used: int | None = None
        self._hud_context_window: int = 0
        self._prompt_session = PromptSession() if self._supports_prompt_toolkit() else None

    def set_hud(self, model: str = "", token_used: int | None = None, context_window: int = 0):
        with self._lock:
            self._hud_model = str(model or "").strip()
            self._hud_token_used = token_used
            self._hud_context_window = max(0, int(context_window or 0))

    def _format_hud(self) -> str:
        parts = []
        if self._hud_model:
            model = self._hud_model
            if len(model) > 24:
                model = model[:21] + "..."
            parts.append(model)
        if self._hud_token_used is not None and self._hud_context_window > 0:
            used = self._hud_token_used
            limit = self._hud_context_window
            ratio = min(1.0, used / limit)
            bar_width = 8
            filled = round(ratio * bar_width)
            bar = "\u2588" * filled + "\u2591" * (bar_width - filled)
            def _k(n: int) -> str:
                return f"{n / 1000:.1f}K" if n >= 1000 else str(n)
            parts.append(f"{bar} {_k(used)}/{_k(limit)}")
        parts.append(datetime.now().strftime("%H:%M:%S"))
        return "  \u2502  ".join(parts)

    def _rule_with_hud(self) -> str:
        hud = self._format_hud()
        width = self._terminal_columns()
        if not hud:
            if self._color:
                return f"{self._c(_GRAY, _DIM)}{_RULE_CHAR * width}{self._c(_R)}"
            return _RULE_CHAR * width
        hud_block = f"[ {hud} ]"
        hud_len = len(hud_block)
        rule_len = max(0, width - hud_len)
        rule = _RULE_CHAR * rule_len
        if self._color:
            return (
                f"{self._c(_GRAY, _DIM)}{rule}{self._c(_R)}"
                f"{self._c(_CYAN)}{hud_block}{self._c(_R)}"
            )
        return rule + hud_block

    def _c(self, *codes: str) -> str:
        return "".join(codes) if self._color else ""

    def _supports_tty(self) -> bool:
        return (
            hasattr(sys.stdout, "isatty")
            and hasattr(sys.stdin, "isatty")
            and sys.stdout.isatty()
            and sys.stdin.isatty()
        )

    def _supports_framed_prompt(self) -> bool:
        return self._supports_tty() and _VT_OK

    def _supports_prompt_toolkit(self) -> bool:
        return (
            PromptSession is not None
            and ANSI is not None
            and patch_stdout is not None
            and self._supports_tty()
        )

    def _terminal_columns(self) -> int:
        return max(20, get_terminal_size(fallback=(80, 20)).columns)

    def _rule_text(self) -> str:
        return _RULE_CHAR * self._terminal_columns()

    def _ansi_rule(self) -> str:
        if self._color:
            return f"{self._c(_GRAY, _DIM)}{self._rule_text()}{self._c(_R)}"
        return self._rule_text()

    def _prompt_pt_text(self):
        if not self._supports_prompt_toolkit():
            return "> "
        rule = self._rule_with_hud()
        if self._color:
            return ANSI(
                f"{rule}\n"
                f"{self._c(_BGREEN, _BOLD)}>{self._c(_R)} "
            )
        return f"{self._rule_text()}\n> "

    def _prompt_pt_toolbar(self):
        hud = self._format_hud()
        if not hud:
            return ""
        if self._color:
            return ANSI(f"{self._c(_GRAY, _DIM)}  {hud}{self._c(_R)}")
        return f"  {hud}"

    def _fit_status_line(self, text: str, *, reserve: int = 0) -> str:
        width = self._terminal_columns()
        cleaned = str(text or "").replace("\r", " ").replace("\n", " ").strip()
        available = max(1, width - reserve)
        if len(cleaned) <= available:
            return cleaned
        if available <= 3:
            return cleaned[:available]
        return cleaned[: available - 3] + "..."

    def _clear_status_footer_locked(self):
        if not self._status_footer_visible or not self._supports_framed_prompt():
            return
        for _ in range(2):
            sys.stdout.write("\033[1A\r\033[2K")
        sys.stdout.write("\r")
        sys.stdout.flush()
        self._status_footer_visible = False

    def _render_status_footer_locked(self):
        if (
            not self._status_footer_text
            or not self._supports_framed_prompt()
            or self._prompt_active
        ):
            return

        prompt_prefix = f"{self._c(_BGREEN, _BOLD)}>{self._c(_R)} "
        status_text = self._fit_status_line(self._status_footer_text, reserve=2)
        if self._color:
            status_text = f"{self._c(_CYAN, _BOLD)}{status_text}{self._c(_R)}"
        sys.stdout.write(
            f"{self._rule_with_hud()}\n"
            f"{prompt_prefix}{status_text}\n"
        )
        sys.stdout.flush()
        self._status_footer_visible = True

    def _refresh_waiting_frame_locked(self):
        if not self._waiting_base_text:
            self._status_footer_text = ""
            return
        frame = self._spinner_frames[self._spinner_index % len(self._spinner_frames)]
        self._spinner_index += 1
        self._status_footer_text = f"[{frame}] {self._waiting_base_text}"

    def _ensure_spinner_locked(self):
        if self._spinner_thread and self._spinner_thread.is_alive():
            return

        stop_event = threading.Event()
        self._spinner_stop_event = stop_event

        def _run_spinner():
            while not stop_event.wait(self._spinner_interval):
                with self._lock:
                    if stop_event.is_set() or not self._waiting_base_text:
                        break
                    self._clear_status_footer_locked()
                    self._refresh_waiting_frame_locked()
                    self._render_status_footer_locked()

        self._spinner_thread = threading.Thread(
            target=_run_spinner,
            name="terminal-waiting-spinner",
            daemon=True,
        )
        self._spinner_thread.start()

    def set_waiting(self, text: str):
        with self._lock:
            waiting_text = str(text or "").strip()
            if not waiting_text or waiting_text.lower().startswith("ai "):
                waiting_text = "thinking"
            self._waiting_base_text = waiting_text
            self._spinner_index = 0
            self._clear_status_footer_locked()
            self._refresh_waiting_frame_locked()
            self._render_status_footer_locked()
            self._ensure_spinner_locked()

    def clear_waiting(self):
        spinner_thread = None
        with self._lock:
            if self._spinner_stop_event is not None:
                self._spinner_stop_event.set()
            spinner_thread = self._spinner_thread
            self._spinner_stop_event = None
            self._spinner_thread = None
            self._waiting_base_text = ""
            self._spinner_index = 0
            self._clear_status_footer_locked()
            self._status_footer_text = ""
        if (
            spinner_thread
            and spinner_thread.is_alive()
            and spinner_thread is not threading.current_thread()
        ):
            spinner_thread.join(timeout=0.2)

    def set_enabled(self, category: str, enabled: bool):
        self._enabled[category] = bool(enabled)

    def is_enabled(self, category: str) -> bool:
        return self._enabled.get(category, True)

    def states(self) -> dict[str, bool]:
        return dict(self._enabled)

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

    def _record_event(self, *, prefix: str, text: str, rendered: str, category: str | None):
        if not category:
            return
        tid = threading.get_ident()
        with self._capture_lock:
            captures = list(self._captures.get(tid, []))
        if not captures:
            return
        event = {"prefix": prefix, "text": text, "rendered": rendered, "category": category}
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

    def _emit(
        self,
        style_key: str,
        text: str,
        *,
        category: str | None = None,
        leading_blank: bool = False,
        trailing_blank: bool = False,
        notify: bool = True,
    ):
        if category and not self.is_enabled(category):
            return

        icon, label, label_ansi, text_ansi = _STYLES[style_key]
        R = self._c(_R)

        styled_label = (
            self._c(label_ansi, _BOLD)
            + f"{icon} {label.ljust(_LABEL_WIDTH)}"
            + R
        )

        lines = str(text).splitlines() or [""]
        rendered_lines = []
        plain_lines = []
        for i, line in enumerate(lines):
            prefix = f"{_INDENT}{styled_label} " if i == 0 else _CONTINUATION
            plain_prefix = f"{_INDENT}{icon} {label.ljust(_LABEL_WIDTH)} " if i == 0 else _CONTINUATION
            color_on = self._c(text_ansi) if text_ansi else ""
            color_off = R if text_ansi else ""
            rendered_lines.append(f"{prefix}{color_on}{line}{color_off}")
            plain_lines.append(f"{plain_prefix}{line}")

        rendered = "\n".join(rendered_lines)
        plain_rendered = "\n".join(plain_lines)

        if notify:
            self._record_event(prefix=label, text=str(text), rendered=plain_rendered, category=category)

        with self._lock:
            self._clear_status_footer_locked()
            if leading_blank:
                print()
            print(rendered)
            if trailing_blank:
                print()
            self._render_status_footer_locked()

    def think(self, step: int, text: str):
        self._emit("think", f"step {step}: {text}", category="think")

    def tool_note(self, step: int, text: str):
        self._emit("tool_note", f"step={step} note: {text}", category="tool")

    def tool_call(self, step: int, text: str):
        self._emit("tool_call", f"step={step} call: {text}", category="tool")

    def tool_result(self, step: int, text: str):
        self._emit("tool_res", f"step={step} result: {text}", category="tool")

    def compact(self, text: str):
        self._emit("compact", text)

    def memory(self, text: str):
        self._emit("memory", text, category="memory")

    def system(self, text: str, *, notify: bool = True):
        self._emit("system", text, category="system", notify=notify)

    def system_block(self, text: str, *, notify: bool = True):
        self._emit("system", text, category="system", leading_blank=True, trailing_blank=True, notify=notify)

    def command(self, text: str):
        self._emit("command", text, leading_blank=True, trailing_blank=True)

    def agent(self, text: str):
        self._emit("assistant", text, leading_blank=True, trailing_blank=True)

    def error(self, text: str):
        self._emit("error", text, leading_blank=True, trailing_blank=True)

    def prompt(self):
        if self._supports_prompt_toolkit():
            return

        with self._lock:
            prompt_prefix = f"{self._c(_BGREEN, _BOLD)}>{self._c(_R)} "
            if not self._supports_framed_prompt():
                print(prompt_prefix, end="", flush=True)
                return

            border = self._rule_with_hud()
            sys.stdout.write(f"{border}\n{prompt_prefix}")
            sys.stdout.flush()

    def try_read_input(self, timeout: float) -> str | None:
        """TerminalDisplay does not support non-blocking input reads."""
        return None

    def read_input(self) -> str:
        if self._supports_prompt_toolkit():
            with self._lock:
                self._clear_status_footer_locked()
                self._prompt_active = True
            try:
                with patch_stdout():
                    return self._prompt_session.prompt(
                        self._prompt_pt_text,
                        bottom_toolbar=self._prompt_pt_toolbar,
                    )
            finally:
                with self._lock:
                    self._prompt_active = False
                    self._render_status_footer_locked()

        self.prompt()
        try:
            return input()
        finally:
            if self._supports_framed_prompt():
                with self._lock:
                    print()
                    self._render_status_footer_locked()
