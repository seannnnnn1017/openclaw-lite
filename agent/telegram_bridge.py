import json
import mimetypes
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, parse, request


IMAGE_FILE_EXTENSIONS = {
    ".bmp",
    ".gif",
    ".heic",
    ".heif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}


class TelegramBridge:
    def __init__(
        self,
        *,
        bot_token: str,
        handle_message,
        handle_callback_query=None,
        display,
        state_path: str,
        image_storage_path: str | None = None,
        poll_timeout_seconds: int = 20,
        retry_delay_seconds: float = 5.0,
        allowed_chat_ids=None,
        allowed_usernames=None,
        skip_pending_updates_on_start: bool = True,
    ):
        self.bot_token = (bot_token or "").strip()
        self.handle_message = handle_message
        self.handle_callback_query = handle_callback_query
        self.display = display
        self.state_path = Path(state_path).expanduser().resolve()
        self.image_storage_path = (
            Path(image_storage_path).expanduser().resolve()
            if image_storage_path
            else (self.state_path.parent.parent / "telegram_media").resolve()
        )
        self.poll_timeout_seconds = max(int(poll_timeout_seconds or 20), 1)
        self.retry_delay_seconds = max(float(retry_delay_seconds or 5.0), 0.5)
        self.allowed_chat_ids = {int(item) for item in (allowed_chat_ids or [])}
        self.allowed_usernames = {
            str(item).lstrip("@").casefold()
            for item in (allowed_usernames or [])
            if str(item).strip()
        }
        self.skip_pending_updates_on_start = bool(skip_pending_updates_on_start)
        self._stop_event = threading.Event()
        self._thread = None
        self._offset = None
        self._state_lock = threading.Lock()
        self._known_chats: dict[int, str] = {}

    def enabled(self) -> bool:
        return bool(self.bot_token)

    def start(self):
        if not self.enabled():
            return
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._load_state()
        if not self.allowed_chat_ids and not self.allowed_usernames:
            self.display.system("Telegram bridge warning: no allowlist configured.")
        if self.skip_pending_updates_on_start and self._offset is None:
            self._skip_pending_updates()

        self._thread = threading.Thread(
            target=self._loop,
            name="telegram-bridge",
            daemon=True,
        )
        self._thread.start()
        self.display.system("Telegram bridge started.")

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _api_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.bot_token}/{method}"

    def _file_url(self, file_path: str) -> str:
        cleaned = parse.quote(str(file_path or "").lstrip("/"), safe="/")
        return f"https://api.telegram.org/file/bot{self.bot_token}/{cleaned}"

    def _api_call(self, method: str, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            url=self._api_url(method),
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self.poll_timeout_seconds + 10) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Telegram HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Telegram unavailable: {exc.reason}") from exc

        if not data.get("ok"):
            raise RuntimeError(data.get("description") or f"Telegram API error on {method}")

        return data.get("result")

    def _download_binary(self, url: str) -> bytes:
        req = request.Request(url=url, method="GET")

        try:
            with request.urlopen(req, timeout=self.poll_timeout_seconds + 10) as response:
                return response.read()
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Telegram HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Telegram unavailable: {exc.reason}") from exc

    def _load_state(self):
        with self._state_lock:
            if not self.state_path.exists():
                self._offset = None
                self._known_chats = {}
                return

            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._offset = None
                self._known_chats = {}
                return

            offset = data.get("offset")
            self._offset = int(offset) if isinstance(offset, int) else None
            known_chats = {}
            raw_known_chats = data.get("known_chats", [])
            if isinstance(raw_known_chats, list):
                for item in raw_known_chats:
                    if not isinstance(item, dict):
                        continue
                    chat_id = item.get("chat_id")
                    username = str(item.get("username", "")).strip()
                    if not isinstance(chat_id, int):
                        continue
                    known_chats[int(chat_id)] = username
            self._known_chats = known_chats

    def _save_state(self):
        with self._state_lock:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            known_chats = [
                {
                    "chat_id": chat_id,
                    "username": username,
                }
                for chat_id, username in sorted(self._known_chats.items())
            ]
            self.state_path.write_text(
                json.dumps(
                    {
                        "offset": self._offset,
                        "known_chats": known_chats,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

    def _skip_pending_updates(self):
        updates = self._api_call(
            "getUpdates",
            {
                "timeout": 0,
                "allowed_updates": ["message", "callback_query"],
            },
        )
        if updates:
            self._offset = max(int(update.get("update_id", 0)) for update in updates) + 1
            self._save_state()
            self.display.system(f"Telegram bridge skipped {len(updates)} pending update(s).")

    def _is_allowed(self, chat_id, username: str) -> bool:
        if not self.allowed_chat_ids and not self.allowed_usernames:
            return True
        if chat_id is not None and int(chat_id) in self.allowed_chat_ids:
            return True
        return str(username or "").lstrip("@").casefold() in self.allowed_usernames

    def _remember_chat(self, chat_id: int, username: str):
        normalized_username = str(username or "").strip()
        with self._state_lock:
            changed = self._known_chats.get(int(chat_id)) != normalized_username
            if changed:
                self._known_chats[int(chat_id)] = normalized_username
        if changed:
            self._save_state()

    def _is_image_document(self, document: dict) -> bool:
        mime_type = str(document.get("mime_type", "")).strip().lower()
        if mime_type.startswith("image/"):
            return True

        file_name = str(document.get("file_name", "")).strip()
        return Path(file_name).suffix.lower() in IMAGE_FILE_EXTENSIONS

    def _guess_image_extension(
        self,
        *,
        original_name: str = "",
        telegram_file_path: str = "",
        mime_type: str = "",
        default_extension: str = ".jpg",
    ) -> str:
        for candidate in (original_name, telegram_file_path):
            suffix = Path(str(candidate or "").strip()).suffix.lower()
            if suffix:
                return ".jpg" if suffix == ".jpe" else suffix

        normalized_mime = str(mime_type or "").split(";", 1)[0].strip().lower()
        if normalized_mime:
            guessed = mimetypes.guess_extension(normalized_mime)
            if guessed:
                return ".jpg" if guessed == ".jpe" else guessed.lower()

        return default_extension

    def _build_saved_image_path(
        self,
        *,
        chat_id: int,
        message_id,
        update_id: int,
        message_date,
        extension: str,
    ) -> Path:
        timestamp = datetime.now().astimezone()
        if isinstance(message_date, int):
            timestamp = datetime.fromtimestamp(message_date, tz=timezone.utc).astimezone()

        safe_extension = str(extension or ".jpg").strip().lower() or ".jpg"
        if not safe_extension.startswith("."):
            safe_extension = f".{safe_extension}"

        target_dir = self.image_storage_path / timestamp.strftime("%Y-%m-%d") / f"chat_{int(chat_id)}"
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / (
            f"telegram_{timestamp.strftime('%Y%m%d_%H%M%S')}"
            f"_u{int(update_id)}_m{int(message_id or 0)}{safe_extension}"
        )

    def _download_image_asset(
        self,
        *,
        kind: str,
        file_id: str,
        chat_id: int,
        message_id,
        update_id: int,
        message_date,
        original_name: str = "",
        mime_type: str = "",
        width=None,
        height=None,
        file_size=None,
    ) -> dict:
        file_info = self._api_call("getFile", {"file_id": str(file_id)})
        telegram_file_path = str(file_info.get("file_path", "")).strip()
        if not telegram_file_path:
            raise RuntimeError("Telegram getFile returned no file_path.")

        extension = self._guess_image_extension(
            original_name=original_name,
            telegram_file_path=telegram_file_path,
            mime_type=mime_type,
            default_extension=".jpg" if kind == "photo" else ".img",
        )
        saved_path = self._build_saved_image_path(
            chat_id=chat_id,
            message_id=message_id,
            update_id=update_id,
            message_date=message_date,
            extension=extension,
        )
        payload = self._download_binary(self._file_url(telegram_file_path))
        saved_path.write_bytes(payload)

        asset = {
            "kind": kind,
            "file_id": str(file_id),
            "saved_path": str(saved_path),
            "saved_name": saved_path.name,
            "telegram_file_path": telegram_file_path,
            "mime_type": str(mime_type or "").strip(),
            "original_name": str(original_name or "").strip(),
            "bytes": len(payload),
        }
        if width is not None:
            asset["width"] = width
        if height is not None:
            asset["height"] = height
        if file_size is not None:
            asset["telegram_file_size"] = file_size
        return asset

    def _extract_message_images(self, message: dict, update_id: int) -> list[dict]:
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            return []

        message_id = message.get("message_id")
        message_date = message.get("date")
        images = []

        photo_sizes = message.get("photo") or []
        if isinstance(photo_sizes, list):
            photo_candidates = [
                item
                for item in photo_sizes
                if isinstance(item, dict) and str(item.get("file_id", "")).strip()
            ]
            if photo_candidates:
                selected_photo = max(
                    photo_candidates,
                    key=lambda item: (
                        int(item.get("file_size") or 0),
                        int(item.get("width") or 0) * int(item.get("height") or 0),
                    ),
                )
                images.append(
                    self._download_image_asset(
                        kind="photo",
                        file_id=str(selected_photo.get("file_id", "")).strip(),
                        chat_id=int(chat_id),
                        message_id=message_id,
                        update_id=update_id,
                        message_date=message_date,
                        mime_type="image/jpeg",
                        width=selected_photo.get("width"),
                        height=selected_photo.get("height"),
                        file_size=selected_photo.get("file_size"),
                    )
                )

        document = message.get("document") or {}
        if (
            isinstance(document, dict)
            and str(document.get("file_id", "")).strip()
            and self._is_image_document(document)
        ):
            images.append(
                self._download_image_asset(
                    kind="document",
                    file_id=str(document.get("file_id", "")).strip(),
                    chat_id=int(chat_id),
                    message_id=message_id,
                    update_id=update_id,
                    message_date=message_date,
                    original_name=str(document.get("file_name", "")).strip(),
                    mime_type=str(document.get("mime_type", "")).strip(),
                    file_size=document.get("file_size"),
                )
            )

        return images

    def delivery_chat_ids(self) -> list[int]:
        targets = set(self.allowed_chat_ids)
        with self._state_lock:
            known_chats = dict(self._known_chats)

        for chat_id, username in known_chats.items():
            if self._is_allowed(chat_id, username):
                targets.add(int(chat_id))

        return sorted(targets)

    def _split_text(self, text: str, *, limit: int = 3500) -> list[str]:
        cleaned = str(text or "").strip()
        if not cleaned:
            return []

        chunks = []
        remaining = cleaned
        while len(remaining) > limit:
            split_at = remaining.rfind("\n", 0, limit)
            if split_at < limit // 2:
                split_at = remaining.rfind(" ", 0, limit)
            if split_at < limit // 2:
                split_at = limit
            chunks.append(remaining[:split_at].rstrip())
            remaining = remaining[split_at:].lstrip()
        if remaining:
            chunks.append(remaining)
        return chunks

    def send_text(self, chat_id: int, text: str, *, reply_markup: dict | None = None):
        chunks = self._split_text(text)
        results = []
        for index, chunk in enumerate(chunks):
            payload = {
                "chat_id": int(chat_id),
                "text": chunk,
            }
            if index == 0 and reply_markup is not None:
                payload["reply_markup"] = reply_markup
            result = self._api_call(
                "sendMessage",
                payload,
            )
            if isinstance(result, dict):
                results.append(result)
        return results

    def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        reply_markup: dict | None = None,
    ):
        payload = {
            "chat_id": int(chat_id),
            "message_id": int(message_id),
            "text": str(text or ""),
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        self._api_call("editMessageText", payload)

    def answer_callback_query(
        self,
        callback_query_id: str,
        *,
        text: str = "",
        show_alert: bool = False,
    ):
        payload = {"callback_query_id": str(callback_query_id)}
        if text:
            payload["text"] = str(text)
        if show_alert:
            payload["show_alert"] = True
        self._api_call("answerCallbackQuery", payload)

    def broadcast_text(self, text: str, *, chat_ids=None, reply_markup: dict | None = None) -> dict:
        targets = sorted({int(chat_id) for chat_id in (chat_ids or self.delivery_chat_ids())})
        sent_chat_ids = []
        errors = []
        deliveries = []

        for chat_id in targets:
            try:
                messages = self.send_text(chat_id, text, reply_markup=reply_markup)
                sent_chat_ids.append(chat_id)
                message_ids = [
                    int(item.get("message_id"))
                    for item in messages
                    if isinstance(item, dict) and item.get("message_id") is not None
                ]
                deliveries.append(
                    {
                        "chat_id": chat_id,
                        "message_id": message_ids[0] if message_ids else None,
                        "message_ids": message_ids,
                    }
                )
            except Exception as exc:
                errors.append({"chat_id": chat_id, "error": str(exc)})

        return {
            "target_count": len(targets),
            "sent_chat_ids": sent_chat_ids,
            "deliveries": deliveries,
            "errors": errors,
        }

    def _process_update(self, update: dict):
        update_id = int(update.get("update_id", 0))
        callback_query = update.get("callback_query") or {}
        callback_message = callback_query.get("message") or {}
        callback_chat = callback_message.get("chat") or {}
        callback_user = callback_query.get("from") or {}
        callback_chat_id = callback_chat.get("id")
        callback_username = str(callback_user.get("username", "")).strip()
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        user = message.get("from") or {}
        chat_id = chat.get("id")
        text = message.get("text", "")
        caption = str(message.get("caption", ""))
        username = str(user.get("username", "")).strip()

        self._offset = update_id + 1
        self._save_state()

        if callback_query:
            if callback_chat_id is None:
                return

            if not self._is_allowed(callback_chat_id, callback_username):
                self.display.system(
                    "Telegram bridge rejected unauthorized callback "
                    f"chat {callback_chat_id} username={callback_username or '-'}."
                )
                return

            self._remember_chat(int(callback_chat_id), callback_username)

            if self.handle_callback_query:
                self.handle_callback_query(
                    {
                        "chat_id": int(callback_chat_id),
                        "chat_type": str(callback_chat.get("type", "")),
                        "message_id": callback_message.get("message_id"),
                        "message_text": str(callback_message.get("text", "")),
                        "callback_query_id": str(callback_query.get("id", "")),
                        "data": str(callback_query.get("data", "")),
                        "username": callback_username,
                        "user_id": callback_user.get("id"),
                        "display_name": str(
                            callback_user.get("first_name")
                            or callback_chat.get("title")
                            or callback_chat_id
                        ),
                    }
                )
            return

        if chat_id is None:
            return

        if not self._is_allowed(chat_id, username):
            self.display.system(
                f"Telegram bridge rejected unauthorized chat {chat_id} username={username or '-'}."
            )
            return

        self._remember_chat(int(chat_id), username)

        try:
            images = self._extract_message_images(message, update_id)
        except Exception as exc:
            self.display.system(
                f"Telegram bridge image download error chat={chat_id}: {exc}"
            )
            self.send_text(int(chat_id), f"Failed to save Telegram image: {exc}")
            return

        if not text and not caption and not images:
            self.send_text(int(chat_id), "Only text and image messages are supported right now.")
            return

        event = {
            "chat_id": int(chat_id),
            "chat_type": str(chat.get("type", "")),
            "username": username,
            "user_id": user.get("id"),
            "display_name": str(user.get("first_name") or chat.get("title") or chat_id),
            "text": text,
            "caption": caption,
            "images": images,
            "message_id": message.get("message_id"),
        }
        reply = self.handle_message(event)
        if reply:
            self.send_text(int(chat_id), reply)

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                payload = {
                    "timeout": self.poll_timeout_seconds,
                    "allowed_updates": ["message", "callback_query"],
                }
                if self._offset is not None:
                    payload["offset"] = self._offset

                updates = self._api_call("getUpdates", payload) or []
                for update in updates:
                    if self._stop_event.is_set():
                        break
                    self._process_update(update)
            except Exception as exc:
                self.display.system(f"Telegram bridge error: {exc}")
                self._stop_event.wait(self.retry_delay_seconds)
