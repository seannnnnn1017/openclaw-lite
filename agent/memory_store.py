from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path

try:
    from schemas import ChatRequest, Message
except ModuleNotFoundError:
    from agent.schemas import ChatRequest, Message


_MEMORY_LOCK = threading.RLock()
_ALLOWED_KINDS = {
    "habit",
    "preference",
    "identity",
    "project",
    "constraint",
    "workflow",
    "reference",
    "fact",
}
_IMPORTANCE_RANK = {
    "low": 0,
    "medium": 1,
    "high": 2,
}
_PLACEHOLDER_TEXTS = {
    "",
    "[]",
}


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _strip_think_blocks(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", str(text or ""), flags=re.DOTALL).strip()


def _extract_json_object(text: str):
    cleaned = _strip_think_blocks(text).strip()
    if not cleaned:
        return None

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed

    depth = 0
    start = -1
    in_string = False
    escape = False
    for index, char in enumerate(cleaned):
        if in_string:
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                snippet = cleaned[start : index + 1]
                try:
                    parsed = json.loads(snippet)
                except json.JSONDecodeError:
                    return None
                if isinstance(parsed, dict):
                    return parsed
                return None

    return None


def _flatten_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                parts.append(str(item))
                continue
            item_type = str(item.get("type", "")).strip()
            if item_type == "text":
                parts.append(str(item.get("text") or item.get("content") or ""))
                continue
            if "text" in item:
                parts.append(str(item.get("text") or ""))
                continue
            if "content" in item:
                parts.append(str(item.get("content") or ""))
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            if str(key).strip().casefold() in {"image_url", "url"}:
                continue
            parts.append(_flatten_text(item))
        return "\n".join(part for part in parts if part)
    return str(value)


def _normalize_whitespace(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def _normalize_tags(tags) -> list[str]:
    if isinstance(tags, str):
        raw_tags = [part.strip() for part in tags.split(",")]
    elif isinstance(tags, (list, tuple, set)):
        raw_tags = [str(item).strip() for item in tags]
    else:
        raw_tags = []

    normalized = []
    seen = set()
    for tag in raw_tags:
        if not tag:
            continue
        cleaned = re.sub(r"[^0-9a-zA-Z_\-\u3400-\u9fff]+", "-", tag.casefold()).strip("-")
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized[:8]


def _tokenize(text: str) -> set[str]:
    raw_tokens = re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", str(text or "").casefold())
    tokens = set()
    for token in raw_tokens:
        cleaned = token.strip()
        if not cleaned:
            continue
        if cleaned.isascii() and len(cleaned) < 2:
            continue
        tokens.add(cleaned)
    return tokens


def _slugify(text: str) -> str:
    lowered = str(text or "").casefold()
    cleaned = re.sub(r"[^0-9a-zA-Z\u3400-\u9fff]+", "-", lowered)
    return cleaned.strip("-")[:80] or "memory"


def _default_store() -> dict:
    return {
        "version": 1,
        "next_id": 1,
        "updated_at": _now_iso(),
        "memories": [],
    }


class LongTermMemoryStore:
    def __init__(self, path: str | Path, *, max_entries: int = 200):
        self.path = Path(path).expanduser().resolve()
        self.max_entries = max(10, int(max_entries))

    def _log(self, debug_logger, kind: str, **payload):
        if not debug_logger:
            return
        try:
            debug_logger.log_event(kind, **payload)
        except Exception:
            return

    def _save(self, data: dict):
        with _MEMORY_LOCK:
            payload = dict(data)
            payload["updated_at"] = _now_iso()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    def _coerce_store(self, raw):
        if isinstance(raw, dict) and isinstance(raw.get("memories"), list):
            data = dict(raw)
            data["version"] = int(data.get("version", 1) or 1)
            try:
                data["next_id"] = max(1, int(data.get("next_id", 1) or 1))
            except (TypeError, ValueError):
                data["next_id"] = 1
            data["updated_at"] = str(data.get("updated_at") or _now_iso())
            data["memories"] = [
                normalized
                for normalized in (self._normalize_memory_record(item) for item in data.get("memories", []))
                if normalized is not None
            ]
            if not data["memories"]:
                data["next_id"] = max(1, data["next_id"])
            else:
                max_seen = 0
                for record in data["memories"]:
                    match = re.search(r"(\d+)$", str(record.get("id", "")))
                    if match:
                        max_seen = max(max_seen, int(match.group(1)))
                data["next_id"] = max(data["next_id"], max_seen + 1)
            return data
        if isinstance(raw, list):
            return self._coerce_store({"memories": raw})
        return _default_store()

    def _load(self, *, debug_logger=None) -> dict:
        with _MEMORY_LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                data = _default_store()
                self._save(data)
                return data

            raw_text = self.path.read_text(encoding="utf-8").strip()
            if raw_text in _PLACEHOLDER_TEXTS:
                data = _default_store()
                self._save(data)
                return data

            try:
                raw = json.loads(raw_text)
            except json.JSONDecodeError:
                migrated = self._migrate_legacy_text(raw_text)
                self._save(migrated)
                self._log(
                    debug_logger,
                    "memory_store_migrated",
                    path=str(self.path),
                    imported_count=len(migrated.get("memories", [])),
                )
                return migrated

            normalized = self._coerce_store(raw)
            if normalized != raw:
                self._save(normalized)
            return normalized

    def _migrate_legacy_text(self, raw_text: str) -> dict:
        cleaned = raw_text.strip()
        data = _default_store()
        if not cleaned or cleaned in _PLACEHOLDER_TEXTS:
            return data

        memory = self._normalize_memory_record(
            {
                "merge_key": "legacy.imported-note",
                "kind": "reference",
                "title": "Imported legacy note",
                "summary": cleaned[:160],
                "details": cleaned[:1000],
                "tags": ["legacy-import"],
                "importance": "low",
                "always_include": False,
                "source": {"type": "migration"},
            }
        )
        if memory is not None:
            memory["id"] = "mem-000001"
            data["memories"] = [memory]
            data["next_id"] = 2
        return data

    def _normalize_memory_record(self, raw) -> dict | None:
        if not isinstance(raw, dict):
            return None

        kind = str(raw.get("kind", "")).strip().casefold()
        if kind not in _ALLOWED_KINDS:
            kind = "reference"

        title = _normalize_whitespace(raw.get("title", ""))
        summary = _normalize_whitespace(raw.get("summary", ""))
        details = _normalize_whitespace(raw.get("details", ""))
        merge_key = _normalize_whitespace(raw.get("merge_key", "")).casefold()
        if not title and summary:
            title = summary[:80]
        if not summary and details:
            summary = details[:180]
        if not title or not summary:
            return None

        if not merge_key:
            merge_key = f"{kind}.{_slugify(title)}"

        importance = str(raw.get("importance", "medium")).strip().casefold()
        if importance not in _IMPORTANCE_RANK:
            importance = "medium"

        normalized = {
            "id": str(raw.get("id", "")).strip(),
            "merge_key": merge_key[:120],
            "kind": kind,
            "title": title[:120],
            "summary": summary[:220],
            "details": details[:500],
            "tags": _normalize_tags(raw.get("tags", [])),
            "importance": importance,
            "always_include": bool(raw.get("always_include", False)),
            "created_at": str(raw.get("created_at") or _now_iso()),
            "updated_at": str(raw.get("updated_at") or _now_iso()),
            "last_recalled_at": str(raw.get("last_recalled_at") or ""),
            "source": raw.get("source", {}) if isinstance(raw.get("source"), dict) else {},
        }
        return normalized

    def _next_memory_id(self, data: dict) -> str:
        next_id = max(1, int(data.get("next_id", 1) or 1))
        data["next_id"] = next_id + 1
        return f"mem-{next_id:06d}"

    def _sort_key(self, record: dict) -> tuple:
        return (
            1 if record.get("always_include") else 0,
            _IMPORTANCE_RANK.get(str(record.get("importance", "")).casefold(), 0),
            str(record.get("updated_at", "")),
            str(record.get("created_at", "")),
        )

    def _prune(self, data: dict):
        memories = list(data.get("memories", []))
        if len(memories) <= self.max_entries:
            return
        memories.sort(key=self._sort_key, reverse=True)
        data["memories"] = memories[: self.max_entries]

    def stats(self) -> dict:
        data = self._load()
        memories = data.get("memories", [])
        return {
            "count": len(memories),
            "always_include": sum(1 for item in memories if item.get("always_include")),
            "path": str(self.path),
        }

    def memory_index(self, *, limit: int = 40) -> list[dict]:
        data = self._load()
        memories = list(data.get("memories", []))
        memories.sort(key=self._sort_key, reverse=True)
        return memories[: max(1, limit)]

    def build_context_note(self, query_text: str, *, retrieve_limit: int = 6, always_include_limit: int = 3) -> str:
        with _MEMORY_LOCK:
            data = self._load()
            memories = list(data.get("memories", []))
            if not memories:
                return ""

            query = _normalize_whitespace(_flatten_text(query_text))
            query_tokens = _tokenize(query)

            selected = []
            seen_ids = set()

            pinned = [item for item in memories if item.get("always_include")]
            pinned.sort(key=self._sort_key, reverse=True)
            for item in pinned[: max(0, always_include_limit)]:
                item_id = str(item.get("id", "")).strip()
                if item_id in seen_ids:
                    continue
                selected.append(item)
                seen_ids.add(item_id)

            scored = []
            for item in memories:
                item_id = str(item.get("id", "")).strip()
                if item_id in seen_ids:
                    continue

                searchable = " ".join(
                    [
                        str(item.get("merge_key", "")),
                        str(item.get("title", "")),
                        str(item.get("summary", "")),
                        str(item.get("details", "")),
                        " ".join(item.get("tags", [])),
                    ]
                )
                score = 0
                if not query_tokens:
                    continue
                memory_tokens = _tokenize(searchable)
                overlap = len(query_tokens & memory_tokens)
                if overlap <= 0:
                    continue
                score += overlap * 10
                if query.casefold() and query.casefold() in searchable.casefold():
                    score += 5
                score += _IMPORTANCE_RANK.get(str(item.get("importance", "")).casefold(), 0)
                if item.get("always_include"):
                    score += 5
                scored.append((score, item))

            scored.sort(key=lambda entry: (entry[0], *self._sort_key(entry[1])), reverse=True)
            for _, item in scored[: max(0, retrieve_limit)]:
                item_id = str(item.get("id", "")).strip()
                if item_id in seen_ids:
                    continue
                selected.append(item)
                seen_ids.add(item_id)

            if not selected:
                return ""

            changed = False
            now_value = _now_iso()
            by_id = {str(item.get("id", "")): item for item in data.get("memories", [])}
            for item in selected:
                item_id = str(item.get("id", "")).strip()
                existing = by_id.get(item_id)
                if not existing:
                    continue
                if existing.get("last_recalled_at") == now_value:
                    continue
                existing["last_recalled_at"] = now_value
                changed = True
            if changed:
                self._save(data)

            lines = [
                "Relevant long-term memory:",
                "Use these notes only when they are relevant and still consistent with the current conversation.",
                "If the current user request conflicts with a stored memory, follow the current request.",
            ]
            for item in selected:
                markers = [str(item.get("kind", "")), str(item.get("importance", ""))]
                if item.get("always_include"):
                    markers.append("pinned")
                line = f"- [{' / '.join(marker for marker in markers if marker)}] {item.get('title', '')}: {item.get('summary', '')}"
                details = str(item.get("details", "")).strip()
                if details and details != item.get("summary"):
                    line += f" | {details}"
                if item.get("tags"):
                    line += f" | tags={', '.join(item['tags'])}"
                lines.append(line)
            return "\n".join(lines)

    def upsert_many(self, candidates: list[dict], *, source: dict | None = None, debug_logger=None) -> dict:
        normalized_candidates = []
        for candidate in candidates:
            normalized = self._normalize_memory_record(candidate)
            if normalized is None:
                continue
            normalized_candidates.append(normalized)

        if not normalized_candidates:
            return {
                "created": 0,
                "updated": 0,
                "total": self.stats()["count"],
                "titles": [],
            }

        with _MEMORY_LOCK:
            data = self._load(debug_logger=debug_logger)
            memories = list(data.get("memories", []))
            index_by_key = {
                str(item.get("merge_key", "")).casefold(): idx
                for idx, item in enumerate(memories)
                if str(item.get("merge_key", "")).strip()
            }
            created = 0
            updated = 0

            for candidate in normalized_candidates:
                key = str(candidate.get("merge_key", "")).casefold()
                now_value = _now_iso()
                if key in index_by_key:
                    existing = memories[index_by_key[key]]
                    existing["title"] = candidate["title"]
                    existing["summary"] = candidate["summary"]
                    existing["details"] = candidate["details"]
                    existing["tags"] = sorted(
                        set(existing.get("tags", [])) | set(candidate.get("tags", []))
                    )[:8]
                    existing["importance"] = candidate["importance"]
                    existing["always_include"] = candidate["always_include"]
                    existing["updated_at"] = now_value
                    if source:
                        existing["source"] = dict(source)
                    updated += 1
                    continue

                candidate["id"] = self._next_memory_id(data)
                candidate["created_at"] = now_value
                candidate["updated_at"] = now_value
                if source:
                    candidate["source"] = dict(source)
                memories.append(candidate)
                index_by_key[key] = len(memories) - 1
                created += 1

            data["memories"] = memories
            self._prune(data)
            self._save(data)
            self._log(
                debug_logger,
                "memory_store_updated",
                path=str(self.path),
                created=created,
                updated=updated,
                total=len(data.get("memories", [])),
                merge_keys=[item.get("merge_key", "") for item in normalized_candidates],
            )
            return {
                "created": created,
                "updated": updated,
                "total": len(data.get("memories", [])),
                "titles": [str(item.get("title", "")).strip() for item in normalized_candidates],
            }


class LongTermMemoryManager:
    def __init__(self, *, config, client, display=None, debug_logger=None):
        self.config = config
        self.client = client
        self.display = display
        self.debug_logger = debug_logger
        self.enabled = bool(getattr(config, "memory_enabled", True))
        self.extract_after_turn = bool(getattr(config, "memory_extract_after_turn", True))
        self.retrieve_limit = max(0, int(getattr(config, "memory_retrieve_limit", 6)))
        self.always_include_limit = max(0, int(getattr(config, "memory_always_include_limit", 3)))
        self.extractor_max_tokens = max(128, int(getattr(config, "memory_extractor_max_tokens", 600)))
        self.extractor_model = (
            str(getattr(config, "memory_extractor_model", "")).strip()
            or str(getattr(config, "model", "")).strip()
        )
        self.extractor_no_think = bool(getattr(config, "memory_extractor_no_think", False))
        self.store = LongTermMemoryStore(
            getattr(config, "memory_store_path", ""),
            max_entries=int(getattr(config, "memory_max_entries", 200)),
        )

    def _log(self, kind: str, **payload):
        if not self.debug_logger:
            return
        try:
            self.debug_logger.log_event(kind, **payload)
        except Exception:
            return

    def _emit_memory_update(self, *, created: int, updated: int, titles: list[str]):
        if not self.display:
            return

        unique_titles = []
        seen = set()
        for title in titles:
            cleaned = _normalize_whitespace(title)
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            unique_titles.append(cleaned)

        summary = f"long-term memory updated (created={created}, updated={updated})"
        if unique_titles:
            preview = "; ".join(unique_titles[:3])
            if len(unique_titles) > 3:
                preview += f"; +{len(unique_titles) - 3} more"
            summary += f": {preview}"

        try:
            self.display.memory(summary)
        except Exception:
            return

    def stats(self) -> dict:
        if not self.enabled:
            return {
                "enabled": False,
                "count": 0,
                "always_include": 0,
                "path": str(self.store.path),
            }
        data = self.store.stats()
        data["enabled"] = True
        return data

    def build_memory_message(self, user_input) -> str:
        if not self.enabled:
            return ""
        query_text = _flatten_text(user_input)
        note = self.store.build_context_note(
            query_text,
            retrieve_limit=self.retrieve_limit,
            always_include_limit=self.always_include_limit,
        )
        if note:
            self._log(
                "memory_context_injected",
                query_text=query_text[:400],
                note=note,
            )
        return note

    def remember_turn(self, *, user_input, assistant_response: str, debug_context: dict | None = None):
        if not (self.enabled and self.extract_after_turn):
            return
        if not self._should_extract(user_input=user_input, assistant_response=assistant_response, debug_context=debug_context):
            return

        user_text = _normalize_whitespace(_flatten_text(user_input))
        assistant_text = _normalize_whitespace(assistant_response)
        if not user_text or not assistant_text:
            return

        general_payload = self._extract_memory_payload(user_text=user_text, assistant_text=assistant_text)
        explicit_payload = self._extract_explicit_memory_payload(
            user_text=user_text,
            assistant_text=assistant_text,
        )

        general_upserts = general_payload.get("upserts", []) if isinstance(general_payload, dict) else []
        explicit_upserts = explicit_payload.get("upserts", []) if isinstance(explicit_payload, dict) else []
        if not isinstance(general_upserts, list):
            general_upserts = []
        if not isinstance(explicit_upserts, list):
            explicit_upserts = []

        upserts = list(general_upserts) + self._normalize_explicit_upserts(explicit_upserts)
        if not upserts:
            return

        source = {
            "type": "conversation",
            "channel": str((debug_context or {}).get("source") or "unknown"),
            "captured_at": _now_iso(),
            "user_excerpt": user_text[:240],
            "explicit_memory_pass": bool(explicit_upserts),
        }
        result = self.store.upsert_many(
            upserts,
            source=source,
            debug_logger=self.debug_logger,
        )
        if result["created"] or result["updated"]:
            self._emit_memory_update(
                created=result["created"],
                updated=result["updated"],
                titles=result.get("titles", []),
            )
            self._log(
                "memory_turn_captured",
                source=source,
                created=result["created"],
                updated=result["updated"],
                total=result["total"],
                explicit_candidates=len(explicit_upserts),
            )

    def _should_extract(self, *, user_input, assistant_response: str, debug_context: dict | None) -> bool:
        source = str((debug_context or {}).get("source") or "").strip().casefold()
        if source and source not in {"terminal", "telegram"}:
            return False
        user_text = _normalize_whitespace(_flatten_text(user_input))
        if not user_text:
            return False
        if user_text.startswith("/"):
            return False
        if str(assistant_response or "").strip().startswith("[ERROR]"):
            return False
        return True

    def _build_extraction_prompt(self, *, user_text: str, assistant_text: str) -> list:
        memory_index = self.store.memory_index(limit=40)
        memory_lines = []
        for item in memory_index:
            memory_lines.append(
                f"- merge_key={item.get('merge_key', '')} | kind={item.get('kind', '')} | title={item.get('title', '')} | summary={item.get('summary', '')}"
            )
        existing_memories = "\n".join(memory_lines) if memory_lines else "(none)"

        system_prompt = (
            "You maintain a long-term memory store for a coding assistant.\n"
            "Extract only durable information likely to matter in future sessions.\n"
            "Good candidates: stable user preferences, identity facts, ongoing projects, recurring constraints, durable workflow choices.\n"
            "If the user explicitly states an ongoing habit or default they want remembered, it is a good candidate.\n"
            "Do not store one-off requests, transient troubleshooting state, temporary timestamps, or tool noise.\n"
            "If the current turn revises an existing memory, reuse the exact existing `merge_key`.\n"
            "Return exactly one JSON object with this schema:\n"
            '{'
            '"upserts":['
            '{'
            '"merge_key":"snake.case.key",'
            '"kind":"habit|preference|identity|project|constraint|workflow|reference|fact",'
            '"title":"short title",'
            '"summary":"one-sentence durable summary",'
            '"details":"optional concise details",'
            '"tags":["tag-one","tag-two"],'
            '"importance":"low|medium|high",'
            '"always_include":true'
            '}'
            ']'
            '}\n'
            "Rules:\n"
            "- Return at most 3 upserts.\n"
            "- Use `always_include=true` only for strong persistent preferences or constraints.\n"
            "- Prefer updating an existing memory instead of creating a duplicate.\n"
            "- If nothing should be stored, return {\"upserts\":[]}."
        )
        user_prompt = (
            "Existing memory index:\n"
            f"{existing_memories}\n\n"
            "Current user turn:\n"
            f"{user_text}\n\n"
            "Assistant reply:\n"
            f"{assistant_text}"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _build_explicit_memory_prompt(self, *, user_text: str, assistant_text: str) -> list:
        memory_index = self.store.memory_index(limit=40)
        memory_lines = []
        for item in memory_index:
            memory_lines.append(
                f"- merge_key={item.get('merge_key', '')} | kind={item.get('kind', '')} | title={item.get('title', '')} | summary={item.get('summary', '')}"
            )
        existing_memories = "\n".join(memory_lines) if memory_lines else "(none)"

        system_prompt = (
            "You maintain a dedicated long-term memory pass for user-expected habits and future-facing defaults.\n"
            "Decide whether the user is expressing something they expect the assistant to remember and follow in future interactions.\n"
            "Good candidates: 'from now on', 'next time', 'please remember', standing formatting rules, ongoing tone preferences, recurring workflow habits, default behaviors.\n"
            "Do not store one-off task instructions, temporary troubleshooting details, or context that only matters for this single turn.\n"
            "If the current turn revises an existing memory, reuse the exact existing `merge_key`.\n"
            "Return exactly one JSON object with this schema:\n"
            '{'
            '"upserts":['
            '{'
            '"merge_key":"snake.case.key",'
            '"kind":"habit|preference|constraint|workflow|identity|project|reference|fact",'
            '"title":"short title",'
            '"summary":"one-sentence durable summary",'
            '"details":"optional concise details",'
            '"tags":["tag-one","tag-two"],'
            '"importance":"low|medium|high",'
            '"always_include":true'
            '}'
            ']'
            '}\n'
            "Rules:\n"
            "- Return at most 2 upserts.\n"
            "- If there is no explicit future-facing memory to keep, return {\"upserts\":[]}.\n"
            "- Only store habits or defaults the user would reasonably expect to persist across future conversations.\n"
            "- Prefer `habit`, `preference`, `workflow`, or `constraint` when they fit.\n"
        )
        user_prompt = (
            "Existing memory index:\n"
            f"{existing_memories}\n\n"
            "Current user turn:\n"
            f"{user_text}\n\n"
            "Assistant reply:\n"
            f"{assistant_text}"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _extract_payload(self, messages: list, *, user_text: str, log_prefix: str):
        prepared_messages = list(messages)
        if self.extractor_no_think and prepared_messages:
            first = dict(prepared_messages[0])
            content = str(first.get("content", "")).strip()
            if content and not content.startswith("/no_think"):
                first["content"] = f"/no_think\n{content}"
            prepared_messages[0] = first

        request = ChatRequest(
            model=self.extractor_model,
            messages=[Message(role=message["role"], content=message["content"]) for message in prepared_messages],
            temperature=0.1,
            max_tokens=self.extractor_max_tokens,
            stream=False,
        )
        try:
            response = self.client.chat(request)
        except Exception as exc:
            self._log(
                f"{log_prefix}_error",
                error=str(exc),
                user_text=user_text[:240],
                model=self.extractor_model,
                no_think=self.extractor_no_think,
            )
            return None

        payload = _extract_json_object(response)
        if not isinstance(payload, dict):
            self._log(
                f"{log_prefix}_invalid_payload",
                response=response,
                user_text=user_text[:240],
                model=self.extractor_model,
                no_think=self.extractor_no_think,
            )
            return None

        self._log(
            f"{log_prefix}_result",
            user_text=user_text[:240],
            payload=payload,
            model=self.extractor_model,
            no_think=self.extractor_no_think,
        )
        return payload

    def _extract_memory_payload(self, *, user_text: str, assistant_text: str):
        messages = self._build_extraction_prompt(user_text=user_text, assistant_text=assistant_text)
        return self._extract_payload(
            messages,
            user_text=user_text,
            log_prefix="memory_extraction",
        )

    def _extract_explicit_memory_payload(self, *, user_text: str, assistant_text: str):
        messages = self._build_explicit_memory_prompt(
            user_text=user_text,
            assistant_text=assistant_text,
        )
        return self._extract_payload(
            messages,
            user_text=user_text,
            log_prefix="explicit_memory_extraction",
        )

    def _normalize_explicit_upserts(self, upserts: list[dict]) -> list[dict]:
        normalized = []
        for candidate in upserts:
            if not isinstance(candidate, dict):
                continue
            prepared = dict(candidate)
            prepared["always_include"] = bool(prepared.get("always_include", True))
            importance = str(prepared.get("importance", "")).strip().casefold()
            if importance not in {"medium", "high"}:
                prepared["importance"] = "high"
            tags = prepared.get("tags", [])
            if isinstance(tags, str):
                tag_values = [part.strip() for part in tags.split(",") if part.strip()]
            elif isinstance(tags, (list, tuple, set)):
                tag_values = [str(part).strip() for part in tags if str(part).strip()]
            else:
                tag_values = []
            if "explicit-memory" not in {item.casefold() for item in tag_values}:
                tag_values.append("explicit-memory")
            prepared["tags"] = tag_values
            normalized.append(prepared)
        return normalized
