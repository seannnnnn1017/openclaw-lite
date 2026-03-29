import sys
import threading
from contextlib import contextmanager

# ── ANSI codes ────────────────────────────────────────────────────────────────
_R       = "\033[0m"   # reset
_BOLD    = "\033[1m"
_DIM     = "\033[2m"
_ITALIC  = "\033[3m"

_RED     = "\033[31m"
_GREEN   = "\033[32m"
_YELLOW  = "\033[33m"
_MAGENTA = "\033[35m"
_CYAN    = "\033[36m"

_GRAY    = "\033[90m"  # bright-black
_BWHITE  = "\033[97m"  # bright-white
_BGREEN  = "\033[92m"  # bright-green


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


# ── label / icon config ───────────────────────────────────────────────────────
#  Each entry: (icon, label, label_ansi, text_ansi)
_STYLES: dict[str, tuple[str, str, str, str]] = {
    "think":     ("◌", "thinking",  _GRAY,    _DIM + _ITALIC),
    "tool_call": ("⎿", "tool",      _YELLOW,  ""),
    "tool_note": ("⎿", "tool",      _YELLOW,  _DIM),
    "tool_res":  ("⎿", "tool",      _YELLOW,  _DIM),
    "memory":    ("◈", "memory",    _MAGENTA, ""),
    "system":    ("◆", "system",    _CYAN,    ""),
    "command":   (">", "command",   _BGREEN,  _BOLD),
    "assistant": ("◇", "assistant", "",       _BWHITE),
    "error":     ("✗", "error",     _RED,     _RED),
}

_LABEL_WIDTH = 9   # characters reserved for the label text
_INDENT      = "  "
# visual prefix length:  indent(2) + icon(1) + space(1) + label_width(9) + space(1) = 14
_PREFIX_LEN  = len(_INDENT) + 1 + 1 + _LABEL_WIDTH + 1
_CONTINUATION = " " * _PREFIX_LEN


class TerminalDisplay:
    def __init__(self, color: bool | None = None):
        self._lock = threading.Lock()
        self._capture_lock = threading.Lock()
        self._captures: dict[int, list[dict]] = {}
        self._color = _color_supported() if color is None else bool(color)
        self._enabled = {
            "think":  True,
            "tool":   True,
            "memory": True,
            "system": True,
        }

    # ── color helper ──────────────────────────────────────────────────────────

    def _c(self, *codes: str) -> str:
        return "".join(codes) if self._color else ""

    # ── public toggles ────────────────────────────────────────────────────────

    def set_enabled(self, category: str, enabled: bool):
        self._enabled[category] = bool(enabled)

    def is_enabled(self, category: str) -> bool:
        return self._enabled.get(category, True)

    def states(self) -> dict[str, bool]:
        return dict(self._enabled)

    # ── capture context manager ───────────────────────────────────────────────

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

    # ── core renderer ─────────────────────────────────────────────────────────

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
            color_on  = self._c(text_ansi) if text_ansi else ""
            color_off = R if text_ansi else ""
            rendered_lines.append(f"{prefix}{color_on}{line}{color_off}")
            plain_lines.append(f"{plain_prefix}{line}")

        rendered = "\n".join(rendered_lines)
        plain_rendered = "\n".join(plain_lines)

        if notify:
            self._record_event(prefix=label, text=str(text), rendered=plain_rendered, category=category)

        with self._lock:
            if leading_blank:
                print()
            print(rendered)
            if trailing_blank:
                print()

    # ── public display methods ────────────────────────────────────────────────

    def think(self, step: int, text: str):
        self._emit("think", f"step {step}: {text}", category="think")

    def tool_note(self, step: int, text: str):
        self._emit("tool_note", f"step={step} note: {text}", category="tool")

    def tool_call(self, step: int, text: str):
        self._emit("tool_call", f"step={step} call: {text}", category="tool")

    def tool_result(self, step: int, text: str):
        self._emit("tool_res", f"step={step} result: {text}", category="tool")

    def memory(self, text: str):
        self._emit("memory", text, category="memory")

    def system(self, text: str, *, notify: bool = True):
        self._emit("system", text, category="system", notify=notify)

    def system_block(self, text: str, *, notify: bool = True):
        self._emit("system", text, category="system",
                   leading_blank=True, trailing_blank=True, notify=notify)

    def command(self, text: str):
        self._emit("command", text, leading_blank=True, trailing_blank=True)

    def agent(self, text: str):
        self._emit("assistant", text, leading_blank=True, trailing_blank=True)

    def error(self, text: str):
        self._emit("error", text, leading_blank=True, trailing_blank=True)

    def prompt(self):
        with self._lock:
            print(f"{self._c(_BGREEN, _BOLD)}>{self._c(_R)} ", end="", flush=True)
