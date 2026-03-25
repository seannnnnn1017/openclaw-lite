import threading
from contextlib import contextmanager


class TerminalDisplay:
    def __init__(self):
        self._lock = threading.Lock()
        self._capture_lock = threading.Lock()
        self._captures: dict[int, list[dict]] = {}
        self._enabled = {
            "think": True,
            "tool": True,
            "system": True,
        }

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
        thread_id = threading.get_ident()
        with self._capture_lock:
            self._captures.setdefault(thread_id, []).append(capture)
        try:
            yield capture["events"]
        finally:
            with self._capture_lock:
                captures = self._captures.get(thread_id, [])
                if capture in captures:
                    captures.remove(capture)
                if not captures and thread_id in self._captures:
                    self._captures.pop(thread_id, None)

    def _record_event(self, *, prefix: str, text: str, rendered: str, category: str | None):
        if not category:
            return

        thread_id = threading.get_ident()
        with self._capture_lock:
            captures = list(self._captures.get(thread_id, []))

        if not captures:
            return

        event = {
            "prefix": prefix,
            "text": text,
            "rendered": rendered,
            "category": category,
        }
        listeners = []
        for capture in captures:
            categories = capture["categories"]
            if categories and category not in categories:
                continue
            capture["events"].append(dict(event))
            listener = capture.get("on_event")
            if listener:
                listeners.append(listener)

        for listener in listeners:
            try:
                listener(dict(event))
            except Exception:
                continue

    def _emit(
        self,
        prefix: str,
        text: str,
        *,
        category: str | None = None,
        leading_blank: bool = False,
        trailing_blank: bool = False,
        continuation_prefix: str | None = None,
        notify: bool = True,
    ):
        if category and not self.is_enabled(category):
            return

        lines = str(text).splitlines() or [""]
        first_prefix = f"{prefix} " if prefix else ""
        next_prefix = continuation_prefix if continuation_prefix is not None else first_prefix
        rendered_lines = []
        for index, line in enumerate(lines):
            active_prefix = first_prefix if index == 0 else next_prefix
            rendered_lines.append(f"{active_prefix}{line}" if line else "")
        rendered = "\n".join(rendered_lines)

        if notify:
            self._record_event(prefix=prefix, text=str(text), rendered=rendered, category=category)

        with self._lock:
            if leading_blank:
                print()
            print(rendered)
            if trailing_blank:
                print()

    def think(self, step: int, text: str):
        self._emit(f"[THINK {step}]", text, category="think")

    def tool_note(self, step: int, text: str):
        self._emit("[TOOL]", f"step={step} note: {text}", category="tool")

    def tool_call(self, step: int, text: str):
        self._emit("[TOOL]", f"step={step} call: {text}", category="tool", leading_blank=True)

    def tool_result(self, step: int, text: str):
        self._emit("[TOOL]", f"step={step} result: {text}", category="tool", trailing_blank=True)

    def system(self, text: str, *, notify: bool = True):
        self._emit("[SYSTEM]", text, category="system", notify=notify)

    def system_block(self, text: str, *, notify: bool = True):
        self._emit(
            "[SYSTEM]",
            text,
            category="system",
            leading_blank=True,
            trailing_blank=True,
            notify=notify,
        )

    def command(self, text: str):
        self._emit(
            "[COMMAND]",
            text,
            leading_blank=True,
            trailing_blank=True,
            continuation_prefix=" " * len("[COMMAND] "),
        )

    def agent(self, text: str):
        self._emit(
            "Agent:",
            text,
            leading_blank=True,
            trailing_blank=True,
            continuation_prefix=" " * len("Agent: "),
        )

    def error(self, text: str):
        self._emit("[ERROR]", text, leading_blank=True, trailing_blank=True)

    def prompt(self):
        with self._lock:
            print("You: ", end="", flush=True)
