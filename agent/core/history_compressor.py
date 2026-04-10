"""
Session history compression pipeline.

L1 – Snip         : Strip [TOOL HISTORY JSONL] from messages older than L1_PROTECT_LAST_N.
L2 – Microcompact : Truncate individual JSONL entries exceeding L2_TOKEN_THRESHOLD tokens.
L3 – Collapse     : LLM-based summarization when total context exceeds L3_USAGE_RATIO.
"""

from __future__ import annotations

import json
import re

try:
    from core.schemas import Message, ChatRequest
    from core.token_estimator import estimate_text_tokens
except ImportError:
    from agent.core.schemas import Message, ChatRequest
    from agent.core.token_estimator import estimate_text_tokens


# ── Tunables ───────────────────────────────────────────────────────────────────

L1_PROTECT_LAST_N = 8   # protect the last N messages from L1 stripping
L2_TOKEN_THRESHOLD = 2000  # per-JSONL-entry token limit
L3_USAGE_RATIO = 0.60   # trigger L3 when estimated_tokens / context_window >= this
L3_PROTECT_LAST_N = 4   # protect last N messages from L3 collapse (= 2 turn pairs)
L3_SUMMARY_MAX_TOKENS = 1024  # max tokens for the L3 LLM summary call

_TOOL_HISTORY_RE = re.compile(
    r"^\[TOOL HISTORY JSONL\]\n(.*?)\n\n\[ASSISTANT RESPONSE\]\n",
    re.DOTALL,
)


# ── Public class ───────────────────────────────────────────────────────────────

class HistoryCompressor:
    """
    Encapsulates L1/L2/L3 compression logic.

    Parameters
    ----------
    context_window : int
        Model context window in tokens (used for L3 threshold).
    client : LMStudioClient | None
        LLM client used for L3 summarisation.  If *None*, L3 is skipped.
    model : str
        Model name forwarded to the LLM for L3 calls.
    temperature : float
        Sampling temperature for the L3 summarisation call.
    """

    def __init__(
        self,
        *,
        context_window: int,
        client=None,
        model: str = "",
        temperature: float = 0.1,
    ) -> None:
        self.context_window = context_window
        self.client = client
        self.model = model
        self.temperature = temperature

    # ── L1: Snip ──────────────────────────────────────────────────────────────

    def apply_l1(self, history: list[Message]) -> list[Message]:
        """Remove [TOOL HISTORY JSONL] blocks from messages older than L1_PROTECT_LAST_N."""
        if len(history) <= L1_PROTECT_LAST_N:
            return history

        cutoff = len(history) - L1_PROTECT_LAST_N
        result: list[Message] = []
        for i, msg in enumerate(history):
            if i < cutoff and msg.role == "assistant" and isinstance(msg.content, str):
                stripped = _strip_tool_jsonl(msg.content)
                if stripped != msg.content:
                    msg = Message(role=msg.role, content=stripped)
            result.append(msg)
        return result

    # ── L2: Microcompact ──────────────────────────────────────────────────────

    def apply_l2(self, history: list[Message]) -> list[Message]:
        """Compact large JSONL entries inside assistant messages in-place."""
        result: list[Message] = []
        for msg in history:
            if msg.role == "assistant" and isinstance(msg.content, str):
                compacted = _compact_tool_jsonl(msg.content)
                if compacted != msg.content:
                    msg = Message(role=msg.role, content=compacted)
            result.append(msg)
        return result

    # ── L3: Collapse ──────────────────────────────────────────────────────────

    def check_l3_needed(self, *, total_tokens: int) -> bool:
        """Return True when total_tokens has crossed the L3 trigger threshold."""
        if self.context_window <= 0:
            return False
        return total_tokens >= int(self.context_window * L3_USAGE_RATIO)

    def apply_l3(self, history: list[Message]) -> list[Message]:
        """
        Collapse old turns into a single summary message via an LLM call.

        The last L3_PROTECT_LAST_N messages are always preserved verbatim.
        """
        if not self.client or not self.model:
            return history
        if len(history) <= L3_PROTECT_LAST_N:
            return history

        compressible = history[:-L3_PROTECT_LAST_N]
        protected = history[-L3_PROTECT_LAST_N:]

        turns_text = _history_to_readable_text(compressible)
        if not turns_text.strip():
            return history

        summary = self._call_l3_summarize(turns_text)
        if not summary:
            return history

        summary_msg = Message(
            role="user",
            content=(
                "[CONVERSATION SUMMARY — earlier turns collapsed by history compressor]\n"
                + summary
            ),
        )
        return [summary_msg] + list(protected)

    def _call_l3_summarize(self, turns_text: str) -> str:
        system_prompt = (
            "You are a concise conversation summarizer. "
            "Summarize the following conversation history. "
            "Preserve all key facts, decisions, file paths, function names, variable names, "
            "version numbers, and any concrete values that might be referenced later. "
            "Output format:\n"
            "FACTS:\n- <fact>\n\n"
            "DECISIONS:\n- <decision label>: <what was decided and why>\n\n"
            "ANCHORS: <comma-separated list of file paths, names, IDs>"
        )
        try:
            request = ChatRequest(
                model=self.model,
                messages=[
                    Message(role="system", content=system_prompt),
                    Message(
                        role="user",
                        content=f"Conversation history to summarize:\n\n{turns_text}",
                    ),
                ],
                temperature=self.temperature,
                max_tokens=L3_SUMMARY_MAX_TOKENS,
                stream=False,
            )
            return self.client.chat(request)
        except Exception:
            return ""

    # ── Full pipeline ─────────────────────────────────────────────────────────

    def run_pipeline(
        self,
        history: list[Message],
        *,
        total_tokens: int,
    ) -> tuple[list[Message], bool]:
        """
        Execute L1 → L2, then L3 if the token budget demands it.

        Returns
        -------
        history : list[Message]
            Compressed history.
        l3_triggered : bool
            True if L3 summarisation was actually invoked.
        """
        history = self.apply_l1(history)
        history = self.apply_l2(history)
        l3_triggered = False
        if self.check_l3_needed(total_tokens=total_tokens):
            compressed = self.apply_l3(history)
            l3_triggered = compressed is not history or compressed != history
            history = compressed
        return history, l3_triggered


# ── Private helpers ────────────────────────────────────────────────────────────

def _strip_tool_jsonl(content: str) -> str:
    """Return only the [ASSISTANT RESPONSE] portion, discarding [TOOL HISTORY JSONL]."""
    match = _TOOL_HISTORY_RE.match(content)
    if not match:
        return content
    return content[match.end():]


def _compact_tool_jsonl(content: str) -> str:
    """Microcompact: truncate oversized JSONL lines within the tool-history block."""
    match = _TOOL_HISTORY_RE.match(content)
    if not match:
        return content

    jsonl_section = match.group(1)
    response_section = content[match.end():]

    compacted_lines: list[str] = []
    changed = False
    for raw_line in jsonl_section.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if estimate_text_tokens(line) > L2_TOKEN_THRESHOLD:
            line = _compact_jsonl_entry(line)
            changed = True
        compacted_lines.append(line)

    if not changed:
        return content

    if compacted_lines:
        return (
            "[TOOL HISTORY JSONL]\n"
            + "\n".join(compacted_lines)
            + "\n\n[ASSISTANT RESPONSE]\n"
            + response_section
        )
    return "[ASSISTANT RESPONSE]\n" + response_section


def _compact_jsonl_entry(line: str) -> str:
    """Reduce a single JSONL event line to its essential fields."""
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        # Fallback: hard-truncate raw text
        words = line.split()
        out = ""
        for word in words:
            if estimate_text_tokens(out + " " + word) > L2_TOKEN_THRESHOLD:
                break
            out = (out + " " + word).strip()
        return out + " …[truncated]"

    event_type = str(event.get("type", ""))
    payload = event.get("payload", {})

    if event_type == "tool_result" and isinstance(payload, dict):
        compact_payload: dict = {
            "status": payload.get("status", ""),
            "skill": payload.get("skill", ""),
            "action": payload.get("action", ""),
        }
        if "error" in payload:
            compact_payload["error"] = str(payload["error"])[:120]
        result = payload.get("result", {})
        if isinstance(result, dict):
            if "message" in result:
                compact_payload["message"] = str(result["message"])[:120]
            data = result.get("data", {})
            if isinstance(data, dict):
                for key in ("size", "written_chars", "path"):
                    if key in data:
                        compact_payload[key] = data[key]
        event = {
            "type": event_type,
            "step": event.get("step"),
            "payload": {"_compacted": True, **compact_payload},
        }

    return json.dumps(event, ensure_ascii=False, separators=(",", ":"))


def _history_to_readable_text(history: list[Message]) -> str:
    """Render history as human-readable text for the L3 summarisation prompt."""
    parts: list[str] = []
    for msg in history:
        role = str(msg.role or "").upper()
        content = str(msg.content or "")
        # Strip tool JSONL for readability; keep only the assistant response text.
        content = _strip_tool_jsonl(content)
        parts.append(f"[{role}]\n{content.strip()}")
    return "\n\n".join(parts)
