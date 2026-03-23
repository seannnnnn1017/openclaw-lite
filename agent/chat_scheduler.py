import threading
from collections.abc import Callable

from schedule_runtime import claim_due_tasks


class ChatScheduler:
    def __init__(self, on_event: Callable[[dict], None], poll_interval_seconds: float = 1.0):
        self.on_event = on_event
        self.poll_interval_seconds = poll_interval_seconds
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="chat-scheduler", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                events = claim_due_tasks()
                for event in events:
                    self.on_event(event)
            except Exception as exc:
                self.on_event(
                    {
                        "task_name": "scheduler",
                        "short_name": "scheduler",
                        "trigger": "internal",
                        "status": "error",
                        "scheduled_for": "",
                        "task_prompt": "",
                        "dispatch_prompt": "",
                        "error": str(exc),
                        "next_run_at": "",
                    }
                )
            self._stop_event.wait(self.poll_interval_seconds)
