import json
import threading
from pathlib import Path
from urllib import error, request


class TelegramBridge:
    def __init__(
        self,
        *,
        bot_token: str,
        handle_message,
        handle_callback_query=None,
        display,
        state_path: str,
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

        if not text:
            self.send_text(int(chat_id), "Only text messages are supported right now.")
            return

        event = {
            "chat_id": int(chat_id),
            "chat_type": str(chat.get("type", "")),
            "username": username,
            "user_id": user.get("id"),
            "display_name": str(user.get("first_name") or chat.get("title") or chat_id),
            "text": text,
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
