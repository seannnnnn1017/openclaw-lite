from __future__ import annotations

import threading
from collections.abc import Callable

try:
    from schedule_runtime import delete_task, list_tasks
    from telegram_bridge import TelegramBridge
except ModuleNotFoundError:
    from agent.schedule_runtime import delete_task, list_tasks
    from agent.telegram_bridge import TelegramBridge

from .tasks import (
    apply_task_edit,
    format_task_summary,
    resolve_task_identifier,
    task_edit_instruction,
    task_edit_reply_markup,
)
from .telegram_support import (
    TelegramRollingReply,
    build_telegram_image_prompt,
    build_telegram_image_user_input,
    format_saved_telegram_images,
    format_telegram_delivery_errors,
    format_telegram_tool_event,
    tool_event_reply_markup,
)


class TelegramRuntime:
    def __init__(
        self,
        *,
        config,
        display,
        build_agent_session: Callable[[], object],
        handle_remote_command: Callable[[str, object], str],
    ):
        self.config = config
        self.display = display
        self.build_agent_session = build_agent_session
        self.handle_remote_command = handle_remote_command
        self.bridge: TelegramBridge | None = None
        self._telegram_agents: dict[int, object] = {}
        self._telegram_task_edits: dict[tuple[int, int], dict] = {}
        self._telegram_tool_events: dict[str, dict[str, str]] = {}
        self._telegram_tool_lock = threading.Lock()
        self._telegram_tool_counter = 0

    def start(self):
        if not (self.config.telegram_enabled and self.config.telegram_bot_token):
            return
        if self.bridge is None:
            self.bridge = TelegramBridge(
                bot_token=self.config.telegram_bot_token,
                handle_message=self.on_message,
                handle_callback_query=self.on_callback,
                display=self.display,
                state_path=self.config.telegram_state_path,
                image_storage_path=self.config.telegram_image_storage_path,
                poll_timeout_seconds=self.config.telegram_poll_timeout_seconds,
                retry_delay_seconds=self.config.telegram_retry_delay_seconds,
                allowed_chat_ids=self.config.telegram_allowed_chat_ids,
                allowed_usernames=self.config.telegram_allowed_usernames,
                skip_pending_updates_on_start=self.config.telegram_skip_pending_updates_on_start,
            )
        self.bridge.start()

    def stop(self):
        if self.bridge:
            self.bridge.stop()
            self.bridge = None

    def refresh_runtime_clients(self):
        for session_agent in list(self._telegram_agents.values()):
            session_agent.refresh_runtime_clients()

    def get_session_agent(self, chat_id: int):
        if chat_id not in self._telegram_agents:
            self._telegram_agents[chat_id] = self.build_agent_session()
        return self._telegram_agents[chat_id]

    def delivery_chat_ids(self) -> list[int]:
        if not self.bridge:
            return []
        return self.bridge.delivery_chat_ids()

    def broadcast_text(
        self,
        text: str,
        *,
        label: str,
        reply_markup: dict | None = None,
        chat_ids=None,
    ) -> dict:
        cleaned = str(text or "").strip()
        if not cleaned or not self.bridge:
            return {"deliveries": [], "errors": []}

        result = self.bridge.broadcast_text(
            cleaned,
            reply_markup=reply_markup,
            chat_ids=chat_ids,
        )
        errors = result.get("errors", [])
        if errors:
            self.display.system_block(format_telegram_delivery_errors(label, errors), notify=False)
        return result

    def _edit_key(self, chat_id: int, user_id) -> tuple[int, int]:
        return (int(chat_id), int(user_id or 0))

    def _resolve_active_task(self, identifier: str) -> dict | None:
        tasks = list_tasks(include_deleted=False)
        return resolve_task_identifier(tasks, identifier)

    def _remember_tool_event(self, summary: str, details: str) -> str:
        with self._telegram_tool_lock:
            self._telegram_tool_counter += 1
            event_id = f"tool-{self._telegram_tool_counter}"
            self._telegram_tool_events[event_id] = {
                "summary": str(summary or "").strip(),
                "details": str(details or "").strip(),
            }
            while len(self._telegram_tool_events) > 200:
                oldest_key = next(iter(self._telegram_tool_events))
                self._telegram_tool_events.pop(oldest_key, None)
        return event_id

    def build_tool_streamer(self, *, chat_ids) -> Callable[[dict], None]:
        targets = sorted({int(chat_id) for chat_id in (chat_ids or [])})
        pending_messages = {}

        def handle_event(event: dict):
            if not self.bridge or not targets:
                return

            tool_event = format_telegram_tool_event(event)
            if not tool_event:
                return

            event_key = str(tool_event.get("key", "")).strip()
            if tool_event.get("kind") == "call":
                event_id = self._remember_tool_event(
                    tool_event["summary"],
                    tool_event["details"],
                )
                result = self.broadcast_text(
                    tool_event["summary"],
                    label="tool-progress",
                    reply_markup=tool_event_reply_markup(event_id, expanded=False),
                    chat_ids=targets,
                )
                message_ids_by_chat = {}
                for delivery in result.get("deliveries", []):
                    chat_id = delivery.get("chat_id")
                    message_id = delivery.get("message_id")
                    if chat_id is None or message_id is None:
                        continue
                    message_ids_by_chat[int(chat_id)] = int(message_id)

                pending_messages[event_key] = {
                    "event_id": event_id,
                    "summary": tool_event["summary"],
                    "details": tool_event["details"],
                    "message_ids_by_chat": message_ids_by_chat,
                }
                return

            if tool_event.get("kind") != "result":
                return

            pending = pending_messages.pop(event_key, None)
            if not pending:
                event_id = self._remember_tool_event(
                    tool_event["summary"],
                    tool_event["details"],
                )
                self.broadcast_text(
                    tool_event["summary"],
                    label="tool-progress",
                    reply_markup=tool_event_reply_markup(event_id, expanded=False),
                    chat_ids=targets,
                )
                return

            event_id = pending["event_id"]
            combined_summary = pending["summary"]
            status = str(tool_event.get("status", "")).strip()
            if status:
                combined_summary = f"{combined_summary} -> {status}"
            else:
                combined_summary = f"{combined_summary} -> done"

            combined_details = "\n".join(
                part
                for part in [
                    str(pending.get("details", "")).strip(),
                    str(tool_event.get("details", "")).strip(),
                ]
                if part
            )
            with self._telegram_tool_lock:
                self._telegram_tool_events[event_id] = {
                    "summary": combined_summary,
                    "details": combined_details,
                }

            for target_chat_id in targets:
                message_id = pending["message_ids_by_chat"].get(int(target_chat_id))
                if message_id is None:
                    self.broadcast_text(
                        combined_summary,
                        label="tool-progress",
                        reply_markup=tool_event_reply_markup(event_id, expanded=False),
                        chat_ids=[int(target_chat_id)],
                    )
                    continue

                try:
                    self.bridge.edit_message_text(
                        int(target_chat_id),
                        int(message_id),
                        combined_summary,
                        reply_markup=tool_event_reply_markup(event_id, expanded=False),
                    )
                except Exception:
                    self.broadcast_text(
                        combined_summary,
                        label="tool-progress",
                        reply_markup=tool_event_reply_markup(event_id, expanded=False),
                        chat_ids=[int(target_chat_id)],
                    )

        return handle_event

    def on_callback(self, event: dict):
        if not self.bridge:
            return

        chat_id = int(event.get("chat_id"))
        user_id = event.get("user_id")
        key = self._edit_key(chat_id, user_id)
        callback_query_id = str(event.get("callback_query_id", "")).strip()
        data = str(event.get("data", "")).strip()
        message_id = event.get("message_id")
        actor = str(event.get("username") or event.get("display_name") or chat_id).strip()

        def answer(text: str = "", *, show_alert: bool = False):
            if callback_query_id and self.bridge:
                self.bridge.answer_callback_query(
                    callback_query_id,
                    text=text,
                    show_alert=show_alert,
                )

        if data.startswith("tool:show:") or data.startswith("tool:hide:"):
            parts = data.split(":", 2)
            if len(parts) != 3:
                answer("Invalid tool action.", show_alert=True)
                return

            mode = parts[1].strip()
            event_id = parts[2].strip()
            with self._telegram_tool_lock:
                payload = dict(self._telegram_tool_events.get(event_id, {}))
            if not payload:
                answer("Tool details expired.", show_alert=True)
                return

            if message_id is None:
                answer()
                return

            expanded = mode == "show"
            self.bridge.edit_message_text(
                chat_id,
                int(message_id),
                payload["details"] if expanded else payload["summary"],
                reply_markup=tool_event_reply_markup(event_id, expanded=expanded),
            )
            answer()
            return

        if data.startswith("task:delete:"):
            identifier = data.split(":", 2)[2].strip()
            task = self._resolve_active_task(identifier)
            if not task:
                answer("Task not found or already deleted.", show_alert=True)
                return

            delete_task(
                task.get("task_name", ""),
                reason=f"Removed via Telegram inline action by {actor}",
            )
            pending = self._telegram_task_edits.get(key)
            if pending and pending.get("task_id") == task.get("id", ""):
                self._telegram_task_edits.pop(key, None)

            answer("Deleted.")
            if message_id is not None:
                self.bridge.edit_message_text(
                    chat_id,
                    int(message_id),
                    "\n".join(
                        [
                            "Scheduled task deleted.",
                            f"id: {task.get('id', '')}",
                            f"name: {task.get('task_name', '')}",
                        ]
                    ),
                )
            return

        if data.startswith("task:edit:"):
            identifier = data.split(":", 2)[2].strip()
            task = self._resolve_active_task(identifier)
            if not task:
                answer("Task not found or already deleted.", show_alert=True)
                return

            answer("Choose a field to edit.")
            self.bridge.send_text(
                chat_id,
                "\n".join(
                    [
                        "Choose what to edit for this scheduled task.",
                        "",
                        format_task_summary(task),
                    ]
                ),
                reply_markup=task_edit_reply_markup(str(task.get("id", "")).strip()),
            )
            return

        if data.startswith("task:field:"):
            parts = data.split(":", 3)
            if len(parts) != 4:
                answer("Invalid edit action.", show_alert=True)
                return

            field = parts[2].strip()
            identifier = parts[3].strip()
            task = self._resolve_active_task(identifier)
            if not task:
                answer("Task not found or already deleted.", show_alert=True)
                return

            self._telegram_task_edits[key] = {
                "task_id": str(task.get("id", "")).strip(),
                "field": field,
            }
            answer("Send the new value.")
            self.bridge.send_text(chat_id, task_edit_instruction(task, field))
            return

        if data.startswith("task:cancel:"):
            self._telegram_task_edits.pop(key, None)
            answer("Cancelled.")
            if message_id is not None:
                self.bridge.edit_message_text(
                    chat_id,
                    int(message_id),
                    "Task edit cancelled.",
                )
            return

        answer()

    def on_message(self, event: dict) -> str:
        chat_id = int(event["chat_id"])
        user_id = event.get("user_id")
        text = str(event.get("text", "")).strip()
        caption = str(event.get("caption", "")).strip()
        images = [item for item in (event.get("images") or []) if isinstance(item, dict)]
        session_agent = self.get_session_agent(chat_id)
        rolling_reply = None
        response_stream_callback = None
        self.display.system(
            f"Telegram message chat={chat_id} user={event.get('username') or event.get('display_name') or '-'} images={len(images)}",
            notify=False,
        )

        pending_edit = self._telegram_task_edits.get(self._edit_key(chat_id, user_id))
        if pending_edit:
            if images:
                return "A task edit is pending. Send the new value as plain text only, or send /cancel."
            if text.lower() in {"/cancel", "cancel"}:
                self._telegram_task_edits.pop(self._edit_key(chat_id, user_id), None)
                return "Cancelled scheduled-task edit."

            if text.startswith("/"):
                return "A task edit is pending. Send the new value directly, or send /cancel."

            task = self._resolve_active_task(pending_edit.get("task_id", ""))
            if not task:
                self._telegram_task_edits.pop(self._edit_key(chat_id, user_id), None)
                return "Task not found. It may have been deleted already."

            try:
                updated_task = apply_task_edit(
                    task,
                    field=str(pending_edit.get("field", "")).strip(),
                    raw_value=text,
                    actor=str(event.get("username") or event.get("display_name") or chat_id).strip(),
                )
            except Exception as exc:
                return (
                    f"Task edit failed: {exc}\n"
                    "Send the new value again, or send /cancel to stop editing."
                )

            self._telegram_task_edits.pop(self._edit_key(chat_id, user_id), None)
            return "Updated scheduled task.\n" + format_task_summary(updated_task)

        if self.bridge and not text.startswith("/"):
            rolling_reply = TelegramRollingReply(self.bridge, chat_id=chat_id)

            def response_stream_callback(stream_text: str, *, final: bool = False):
                if final:
                    return
                rolling_reply.push_preview(stream_text)

        with self.display.capture_events(
            categories={"tool"},
            on_event=self.build_tool_streamer(chat_ids=[chat_id]),
        ):
            if images:
                history_user_input = build_telegram_image_prompt(event)
                try:
                    user_input = build_telegram_image_user_input(event)
                except Exception as exc:
                    self.display.system(
                        f"Telegram image prompt fallback chat={chat_id}: {exc}",
                        notify=False,
                    )
                    user_input = history_user_input
                reply = session_agent.run(
                    user_input,
                    history_user_input=history_user_input,
                    response_stream_callback=response_stream_callback,
                )
            elif text.startswith("/"):
                reply = self.handle_remote_command(text, session_agent)
            else:
                reply = session_agent.run(
                    text,
                    response_stream_callback=response_stream_callback,
                )

        if images:
            reply_parts = [format_saved_telegram_images(images), str(reply or "").strip()]
            if caption and not str(reply or "").strip():
                reply_parts.append(f"Caption: {caption}")
            final_reply = "\n\n".join(part for part in reply_parts if part)
            if rolling_reply and rolling_reply.finalize(final_reply):
                return ""
            return final_reply

        if rolling_reply and rolling_reply.finalize(reply):
            return ""

        return reply
