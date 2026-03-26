from __future__ import annotations

import base64
import mimetypes
import re
import time
from pathlib import Path


TELEGRAM_STREAM_REFRESH_SECONDS = 0.3
TELEGRAM_STREAM_PREVIEW_LIMIT = 3500


def format_scheduled_trigger(event: dict) -> str:
    name = event.get("short_name") or event.get("task_name") or "scheduled-task"
    trigger = event.get("trigger", "scheduled")
    parts = [f"Scheduled task triggered: {name}", f"trigger={trigger}"]
    task_id = str(event.get("task_id", "")).strip()
    if task_id:
        parts.append(f"id={task_id}")
    scheduled_for = str(event.get("scheduled_for", "")).strip()
    if scheduled_for:
        parts.append(f"scheduled_for={scheduled_for}")
    next_run_at = str(event.get("next_run_at", "")).strip()
    if next_run_at:
        parts.append(f"next_run_at={next_run_at}")
    return "\n".join(parts)


def format_telegram_delivery_errors(label: str, errors: list[dict]) -> str:
    lines = [f"Telegram {label} delivery error(s):"]
    for item in errors:
        lines.append(f"chat={item.get('chat_id')} error={item.get('error')}")
    return "\n".join(lines)


def format_saved_telegram_images(images: list[dict]) -> str:
    if not images:
        return ""

    noun = "image" if len(images) == 1 else "images"
    lines = [f"Saved Telegram {noun} locally:"]
    for index, image in enumerate(images, start=1):
        path = str(image.get("saved_path", "")).strip() or "-"
        parts = [f"{index}. {path}"]
        width = image.get("width")
        height = image.get("height")
        if width and height:
            parts.append(f"{width}x{height}")
        mime_type = str(image.get("mime_type", "")).strip()
        if mime_type:
            parts.append(mime_type)
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def looks_like_tool_payload(text: str) -> bool:
    stripped = str(text or "").lstrip()
    if not stripped:
        return False

    head = stripped[:1000]
    if stripped.startswith("{") and "skill" in head and "action" in head:
        return True

    if stripped.startswith("```"):
        fence_body = stripped[3:].lstrip()
        if "skill" in fence_body[:1000] and "action" in fence_body[:1000]:
            return True

    return bool(
        re.search(r"\{\s*['\"]?skill['\"]?\s*:", head)
        and ("action" in head or "args" in head)
    )


class TelegramRollingReply:
    def __init__(
        self,
        telegram_bridge,
        *,
        chat_id: int,
        refresh_seconds: float = TELEGRAM_STREAM_REFRESH_SECONDS,
        preview_limit: int = TELEGRAM_STREAM_PREVIEW_LIMIT,
    ):
        self.telegram_bridge = telegram_bridge
        self.chat_id = int(chat_id)
        self.refresh_seconds = float(refresh_seconds)
        self.preview_limit = int(preview_limit)
        self.message_id = None
        self.last_sent_text = ""
        self.last_sent_at = 0.0
        self.pending_text = ""
        self.finalized = False

    def _preview_text(self, text: str) -> str:
        cleaned = str(text or "").strip()
        if len(cleaned) <= self.preview_limit:
            return cleaned
        return cleaned[: max(1, self.preview_limit - 3)].rstrip() + "..."

    def _send_or_edit(self, text: str) -> bool:
        cleaned = str(text or "").strip()
        if not cleaned:
            return False

        try:
            if self.message_id is None:
                results = self.telegram_bridge.send_text(self.chat_id, cleaned)
                first_result = results[0] if results else {}
                message_id = first_result.get("message_id") if isinstance(first_result, dict) else None
                if message_id is not None:
                    self.message_id = int(message_id)
            else:
                self.telegram_bridge.edit_message_text(
                    self.chat_id,
                    int(self.message_id),
                    cleaned,
                )
        except Exception:
            return False

        self.last_sent_text = cleaned
        self.last_sent_at = time.monotonic()
        self.pending_text = ""
        return True

    def push_preview(self, text: str):
        if self.finalized:
            return

        cleaned = str(text or "").strip()
        if not cleaned or looks_like_tool_payload(cleaned):
            return

        preview = self._preview_text(cleaned)
        if not preview or preview == self.last_sent_text:
            return

        now = time.monotonic()
        if self.message_id is not None and (now - self.last_sent_at) < self.refresh_seconds:
            self.pending_text = preview
            return

        self._send_or_edit(preview)

    def finalize(self, text: str) -> bool:
        if self.finalized:
            return True
        self.finalized = True

        final_text = str(text or "").strip()
        if not final_text:
            return False

        chunks = self.telegram_bridge._split_text(final_text, limit=self.preview_limit)
        if not chunks:
            return False

        try:
            if self.message_id is None:
                self.telegram_bridge.send_text(self.chat_id, final_text)
                return True

            if chunks[0] != self.last_sent_text:
                self.telegram_bridge.edit_message_text(
                    self.chat_id,
                    int(self.message_id),
                    chunks[0],
                )
            for chunk in chunks[1:]:
                self.telegram_bridge.send_text(self.chat_id, chunk)
            return True
        except Exception:
            try:
                self.telegram_bridge.send_text(self.chat_id, final_text)
                return True
            except Exception:
                return False


def image_file_to_data_url(image_path: Path) -> str:
    resolved_path = Path(image_path).expanduser().resolve()
    if not resolved_path.is_file():
        raise FileNotFoundError(f"Image not found: {resolved_path}")

    mime_type, _ = mimetypes.guess_type(str(resolved_path))
    if not mime_type:
        mime_type = "application/octet-stream"

    encoded = base64.b64encode(resolved_path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def build_telegram_image_prompt(event: dict) -> str:
    images = [item for item in (event.get("images") or []) if isinstance(item, dict)]
    lines = [
        "A Telegram user sent image attachment(s).",
        "The saved local file paths are listed below.",
        "Use the attached image(s) together with the caption/request.",
    ]

    caption = str(event.get("caption", "")).strip()
    text = str(event.get("text", "")).strip()
    if caption:
        lines.extend(["Caption:", caption])
    elif text:
        lines.extend(["Message text:", text])
    else:
        lines.append("No caption was provided.")

    lines.append("Saved image files:")
    for index, image in enumerate(images, start=1):
        saved_path = str(image.get("saved_path", "")).strip() or "-"
        details = [f"{index}. path={saved_path}"]
        original_name = str(image.get("original_name", "")).strip()
        if original_name:
            details.append(f"original_name={original_name}")
        mime_type = str(image.get("mime_type", "")).strip()
        if mime_type:
            details.append(f"mime_type={mime_type}")
        width = image.get("width")
        height = image.get("height")
        if width and height:
            details.append(f"size={width}x{height}")
        byte_count = image.get("bytes")
        if byte_count is not None:
            details.append(f"bytes={byte_count}")
        lines.append(", ".join(details))

    lines.append(
        "Respond based on the user's caption/request and mention the saved local path(s) when useful."
    )
    return "\n".join(lines)


def build_telegram_image_user_input(event: dict):
    images = [item for item in (event.get("images") or []) if isinstance(item, dict)]
    content = [{"type": "text", "text": build_telegram_image_prompt(event)}]
    for image in images:
        saved_path = str(image.get("saved_path", "")).strip()
        if not saved_path:
            continue
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": image_file_to_data_url(Path(saved_path)),
                },
            }
        )
    return content


def extract_tool_field(text: str, key: str) -> str:
    marker = f"{key}="
    start = text.find(marker)
    if start < 0:
        return ""
    start += len(marker)
    end = text.find(" ", start)
    if end < 0:
        end = len(text)
    return text[start:end].strip().strip('"')


def extract_tool_step(text: str) -> str:
    if not str(text).startswith("step="):
        return ""
    start = len("step=")
    end = str(text).find(" ", start)
    if end < 0:
        end = len(str(text))
    return str(text)[start:end].strip()


def format_telegram_tool_event(event: dict) -> dict | None:
    text = str(event.get("text", "")).strip()
    rendered = str(event.get("rendered", "")).strip()
    if not text.startswith("step="):
        return None

    if " call: " in text:
        kind = "call"
    elif " result: " in text:
        kind = "result"
    else:
        return None

    skill = extract_tool_field(text, "skill")
    action = extract_tool_field(text, "action")
    status = extract_tool_field(text, "status")
    step = extract_tool_step(text)

    if skill and action:
        if kind == "call":
            summary = f"[TOOL] {skill}.{action}"
        else:
            suffix = f" {status}" if status else ""
            summary = f"[TOOL RESULT] {skill}.{action}{suffix}"
    else:
        summary = "[TOOL]" if kind == "call" else "[TOOL RESULT]"

    return {
        "summary": summary,
        "details": rendered or text or summary,
        "kind": kind,
        "status": status,
        "key": "|".join([step or "-", skill or "-", action or "-"]),
    }


def tool_event_reply_markup(event_id: str, *, expanded: bool) -> dict:
    return {
        "inline_keyboard": [
            [
                {
                    "text": "Hide" if expanded else "Show",
                    "callback_data": f"tool:{'hide' if expanded else 'show'}:{event_id}",
                }
            ]
        ]
    }
