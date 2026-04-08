from __future__ import annotations

import json


def is_cjk_like_char(char: str) -> bool:
    code = ord(char)
    return any(
        start <= code <= end
        for start, end in (
            (0x3400, 0x4DBF),
            (0x4E00, 0x9FFF),
            (0x3040, 0x30FF),
            (0x31F0, 0x31FF),
            (0xAC00, 0xD7AF),
        )
    )


def estimate_text_tokens(text: str) -> int:
    cleaned = str(text or "")
    if not cleaned:
        return 0

    total = 0
    index = 0
    length = len(cleaned)
    ascii_token_chars = "_-./:\\"

    while index < length:
        char = cleaned[index]
        if char.isspace():
            index += 1
            continue

        if is_cjk_like_char(char):
            total += 1
            index += 1
            continue

        if char.isascii() and (char.isalnum() or char in ascii_token_chars):
            next_index = index + 1
            while next_index < length:
                next_char = cleaned[next_index]
                if not (next_char.isascii() and (next_char.isalnum() or next_char in ascii_token_chars)):
                    break
                next_index += 1
            span = next_index - index
            total += max(1, (span + 3) // 4)
            index = next_index
            continue

        total += 1
        index += 1

    return total


def estimate_content_tokens(content) -> int:
    if content is None:
        return 0
    if isinstance(content, str):
        return estimate_text_tokens(content)
    if isinstance(content, list):
        total = 0
        for item in content:
            if isinstance(item, str):
                total += estimate_text_tokens(item)
                continue
            if isinstance(item, dict):
                item_type = str(item.get("type", "")).strip()
                if item_type == "text":
                    total += estimate_text_tokens(item.get("text") or item.get("content") or "")
                elif item_type == "image_url":
                    total += 85
                else:
                    total += estimate_text_tokens(json.dumps(item, ensure_ascii=False))
                continue
            total += estimate_text_tokens(str(item))
        return total
    if isinstance(content, dict):
        return estimate_text_tokens(json.dumps(content, ensure_ascii=False))
    return estimate_text_tokens(str(content))


def estimate_message_tokens(*, role: str, content) -> int:
    return 4 + estimate_text_tokens(role) + estimate_content_tokens(content)


def summarize_prompt_and_history(system_prompt: str, history_snapshot) -> dict:
    system_prompt_tokens = estimate_message_tokens(role="system", content=system_prompt)
    history_tokens = sum(
        estimate_message_tokens(
            role=str(getattr(message, "role", "")),
            content=getattr(message, "content", None),
        )
        for message in history_snapshot
    )
    return {
        "system_prompt_tokens": system_prompt_tokens,
        "history_tokens": history_tokens,
        "base_total_tokens": system_prompt_tokens + history_tokens,
        "history_messages": len(history_snapshot),
        "method": "estimated",
    }


def summarize_with_breakdown(
    base_text: str,
    skills_text: str,
    mem_tokens: int,
    history_snapshot,
) -> dict:
    """Token summary with sys/skl/mem/history breakdown."""
    sys_tokens = estimate_message_tokens(role="system", content=base_text)
    skl_tokens = estimate_message_tokens(role="system", content=skills_text) if skills_text else 0
    history_tokens = sum(
        estimate_message_tokens(
            role=str(getattr(m, "role", "")),
            content=getattr(m, "content", None),
        )
        for m in history_snapshot
    )
    total = sys_tokens + skl_tokens + mem_tokens + history_tokens
    return {
        "sys_tokens": sys_tokens,
        "skl_tokens": skl_tokens,
        "mem_tokens": mem_tokens,
        "history_tokens": history_tokens,
        "base_total_tokens": total,
        "history_messages": len(history_snapshot),
        "method": "estimated",
    }
