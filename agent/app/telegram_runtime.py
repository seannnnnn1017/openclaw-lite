from __future__ import annotations

import threading
from collections.abc import Callable

try:
    from scheduling.runtime import delete_task, list_tasks
    from telegram.bridge import TelegramBridge
except ModuleNotFoundError:
    from agent.scheduling.runtime import delete_task, list_tasks
    from agent.telegram.bridge import TelegramBridge

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
    format_telegram_memory_event,
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

    def _tool_step_label(self, tool_event: dict) -> str:
        skill = str(tool_event.get("skill", "")).strip()
        action = str(tool_event.get("action", "")).strip()
        step = str(tool_event.get("step", "")).strip()
        if skill and action:
            label = f"{skill}.{action}"
        else:
            label = "tool"
        if step:
            return f"step {step}: {label}"
        return label

    def _truncate_telegram_text(self, text: str, *, limit: int = 3800) -> str:
        cleaned = str(text or "").strip()
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: max(1, limit - 24)].rstrip() + "\n\n[truncated for Telegram]"

    def _render_tool_progress(self, aggregate: dict) -> tuple[str, str]:
        active_steps = aggregate.get("active_steps", {})
        completed_steps = aggregate.get("completed_steps", {})
        call_order = aggregate.get("call_order", [])
        completed_order = aggregate.get("completed_order", [])

        total_started = len(call_order)
        total_completed = len(completed_order)
        running_count = len(active_steps)
        latest_label = str(aggregate.get("latest_label", "")).strip()
        latest_status = str(aggregate.get("latest_status", "")).strip()

        summary_parts = [f"[TOOLS] {total_completed}/{total_started} done"]
        if running_count > 0:
            summary_parts.append(f"{running_count} running")
        if latest_label:
            if latest_status:
                summary_parts.append(f"latest: {latest_label} -> {latest_status}")
            else:
                summary_parts.append(f"latest: {latest_label}")
        elif total_started > 0 and running_count == 0:
            summary_parts.append("all steps finished")
        summary = " | ".join(summary_parts)

        detail_lines = [summary, "", "Steps:"]
        for step_key in call_order:
            entry = completed_steps.get(step_key) or active_steps.get(step_key)
            if not entry:
                continue
            status = str(entry.get("status", "")).strip()
            label = str(entry.get("label", "")).strip() or f"step {step_key}"
            detail_line = f"- {label}"
            if status:
                detail_line += f" -> {status}"
            detail_lines.append(detail_line)
            details = str(entry.get("details", "")).strip()
            if details:
                detail_lines.append(details)
                detail_lines.append("")

        details_text = "\n".join(line for line in detail_lines if line is not None).strip()
        details_text = self._truncate_telegram_text(details_text)
        return summary, details_text or summary

    def build_tool_streamer(self, *, chat_ids, memory_sink: Callable[[str], None] | None = None) -> Callable[[dict], None]:
        targets = sorted({int(chat_id) for chat_id in (chat_ids or [])})
        aggregate = {
            "event_id": "",
            "message_ids_by_chat": {},
            "call_order": [],
            "active_steps": {},
            "completed_steps": {},
            "completed_order": [],
            "latest_label": "",
            "latest_status": "",
        }

        def handle_event(event: dict):
            if not self.bridge or not targets:
                return

            memory_text = format_telegram_memory_event(event)
            if memory_text:
                if memory_sink:
                    memory_sink(memory_text)
                else:
                    self.broadcast_text(memory_text, label="memory", chat_ids=targets)
                return

            tool_event = format_telegram_tool_event(event)
            if not tool_event:
                return

            step_key = str(tool_event.get("step", "")).strip() or str(tool_event.get("key", "")).strip()
            if not step_key:
                return

            label = self._tool_step_label(tool_event)
            if tool_event.get("kind") == "call":
                if step_key not in aggregate["call_order"]:
                    aggregate["call_order"].append(step_key)
                aggregate["active_steps"][step_key] = {
                    "label": label,
                    "status": "running",
                    "details": str(tool_event.get("details", "")).strip(),
                }
                aggregate["latest_label"] = label
                aggregate["latest_status"] = "running"
            elif tool_event.get("kind") == "result":
                existing = aggregate["active_steps"].pop(step_key, None) or {}
                status = str(tool_event.get("status", "")).strip() or "done"
                entry = {
                    "label": str(existing.get("label", "")).strip() or label,
                    "status": status,
                    "details": "\n".join(
                        part
                        for part in [
                            str(existing.get("details", "")).strip(),
                            str(tool_event.get("details", "")).strip(),
                        ]
                        if part
                    ).strip(),
                }
                aggregate["completed_steps"][step_key] = entry
                if step_key not in aggregate["completed_order"]:
                    aggregate["completed_order"].append(step_key)
                aggregate["latest_label"] = entry["label"]
                aggregate["latest_status"] = status
            else:
                return

            combined_summary, combined_details = self._render_tool_progress(aggregate)
            if not aggregate["event_id"]:
                aggregate["event_id"] = self._remember_tool_event(combined_summary, combined_details)
                result = self.broadcast_text(
                    combined_summary,
                    label="tool-progress",
                    reply_markup=tool_event_reply_markup(aggregate["event_id"], expanded=False),
                    chat_ids=targets,
                )
                message_ids_by_chat = {}
                for delivery in result.get("deliveries", []):
                    chat_id = delivery.get("chat_id")
                    message_id = delivery.get("message_id")
                    if chat_id is None or message_id is None:
                        continue
                    message_ids_by_chat[int(chat_id)] = int(message_id)
                aggregate["message_ids_by_chat"] = message_ids_by_chat
                return

            with self._telegram_tool_lock:
                self._telegram_tool_events[aggregate["event_id"]] = {
                    "summary": combined_summary,
                    "details": combined_details,
                }

            for target_chat_id in targets:
                message_id = aggregate["message_ids_by_chat"].get(int(target_chat_id))
                if message_id is None:
                    result = self.broadcast_text(
                        combined_summary,
                        label="tool-progress",
                        reply_markup=tool_event_reply_markup(aggregate["event_id"], expanded=False),
                        chat_ids=[int(target_chat_id)],
                    )
                    for delivery in result.get("deliveries", []):
                        chat_id = delivery.get("chat_id")
                        delivered_message_id = delivery.get("message_id")
                        if chat_id is None or delivered_message_id is None:
                            continue
                        aggregate["message_ids_by_chat"][int(chat_id)] = int(delivered_message_id)
                    continue

                try:
                    self.bridge.edit_message_text(
                        int(target_chat_id),
                        int(message_id),
                        combined_summary,
                        reply_markup=tool_event_reply_markup(aggregate["event_id"], expanded=False),
                    )
                except Exception:
                    result = self.broadcast_text(
                        combined_summary,
                        label="tool-progress",
                        reply_markup=tool_event_reply_markup(aggregate["event_id"], expanded=False),
                        chat_ids=[int(target_chat_id)],
                    )
                    for delivery in result.get("deliveries", []):
                        chat_id = delivery.get("chat_id")
                        delivered_message_id = delivery.get("message_id")
                        if chat_id is None or delivered_message_id is None:
                            continue
                        aggregate["message_ids_by_chat"][int(chat_id)] = int(delivered_message_id)

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
            try:
                typing_session = self.bridge.start_typing_session(chat_id)
            except Exception:
                typing_session = None

            def response_stream_callback(stream_text: str, *, final: bool = False):
                if final:
                    return
                rolling_reply.push_preview(stream_text)
        else:
            typing_session = None

        try:
            pending_memory_messages: list[str] = []
            with self.display.capture_events(
                categories={"tool", "memory"},
                on_event=self.build_tool_streamer(
                    chat_ids=[chat_id],
                    memory_sink=pending_memory_messages.append,
                ),
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
                        debug_context={
                            "source": "telegram",
                            "chat_id": chat_id,
                            "user_id": user_id,
                            "username": event.get("username"),
                            "display_name": event.get("display_name"),
                            "images": len(images),
                            "caption": caption,
                        },
                    )
                elif text.startswith("/"):
                    reply = self.handle_remote_command(text, session_agent)
                else:
                    reply = session_agent.run(
                        text,
                        response_stream_callback=response_stream_callback,
                        debug_context={
                            "source": "telegram",
                            "chat_id": chat_id,
                            "user_id": user_id,
                            "username": event.get("username"),
                            "display_name": event.get("display_name"),
                            "images": 0,
                        },
                    )
            if images:
                reply_parts = [format_saved_telegram_images(images), str(reply or "").strip()]
                if caption and not str(reply or "").strip():
                    reply_parts.append(f"Caption: {caption}")
                final_reply = "\n\n".join(part for part in reply_parts if part)
                if rolling_reply and rolling_reply.finalize(final_reply):
                    for memory_text in pending_memory_messages:
                        self.broadcast_text(memory_text, label="memory", chat_ids=[chat_id])
                    return ""
                for memory_text in pending_memory_messages:
                    self.broadcast_text(memory_text, label="memory", chat_ids=[chat_id])
                return final_reply

            if rolling_reply and rolling_reply.finalize(reply):
                for memory_text in pending_memory_messages:
                    self.broadcast_text(memory_text, label="memory", chat_ids=[chat_id])
                return ""

            for memory_text in pending_memory_messages:
                self.broadcast_text(memory_text, label="memory", chat_ids=[chat_id])
            return reply
        finally:
            if typing_session:
                typing_session.stop()
