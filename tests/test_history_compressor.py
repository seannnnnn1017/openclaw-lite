"""
Tests for agent/core/history_compressor.py — covers L1, L2, and L3.
"""

from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.core.history_compressor import (
    HistoryCompressor,
    _strip_tool_jsonl,
    _compact_jsonl_entry,
    _history_to_readable_text,
    L1_PROTECT_LAST_N,
    L2_TOKEN_THRESHOLD,
    L3_USAGE_RATIO,
)
from agent.core.schemas import Message
from agent.core.token_estimator import estimate_text_tokens


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_msg(role: str, text: str) -> Message:
    return Message(role=role, content=text)


def make_assistant_with_tool(response_text: str, tool_lines: list[str]) -> Message:
    """Build an assistant message that contains a TOOL HISTORY JSONL block."""
    jsonl = "\n".join(tool_lines)
    content = (
        f"[TOOL HISTORY JSONL]\n{jsonl}\n\n[ASSISTANT RESPONSE]\n{response_text}"
    )
    return Message(role="assistant", content=content)


def make_tool_result_line(skill: str, action: str, status: str = "ok", payload_size: int = 0) -> str:
    """Create a JSONL event line; pad payload to reach a desired token size."""
    payload: dict = {
        "status": status,
        "skill": skill,
        "action": action,
        "result": {"data": {"content": "x" * payload_size}},
    }
    return json.dumps(
        {"type": "tool_result", "step": 1, "payload": payload},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def compressor(context_window: int = 50_000, client=None, model: str = "") -> HistoryCompressor:
    return HistoryCompressor(context_window=context_window, client=client, model=model)


# ── _strip_tool_jsonl ──────────────────────────────────────────────────────────

class TestStripToolJsonl:
    def test_strips_jsonl_block(self):
        content = "[TOOL HISTORY JSONL]\n{}\n\n[ASSISTANT RESPONSE]\nHello."
        assert _strip_tool_jsonl(content) == "Hello."

    def test_returns_unchanged_when_no_block(self):
        content = "Just a plain assistant reply."
        assert _strip_tool_jsonl(content) == content

    def test_multiline_jsonl(self):
        content = (
            "[TOOL HISTORY JSONL]\n"
            '{"type":"tool_call"}\n'
            '{"type":"tool_result"}\n'
            "\n[ASSISTANT RESPONSE]\nDone."
        )
        assert _strip_tool_jsonl(content) == "Done."


# ── L1: Snip ───────────────────────────────────────────────────────────────────

class TestL1Snip:
    def _make_history(self, n_turns: int) -> list[Message]:
        msgs: list[Message] = []
        for i in range(n_turns):
            msgs.append(make_msg("user", f"Question {i}"))
            msgs.append(
                make_assistant_with_tool(
                    f"Answer {i}",
                    [make_tool_result_line("file-control", "read")],
                )
            )
        return msgs

    def test_no_change_when_within_protect_limit(self):
        # L1_PROTECT_LAST_N = 8; 4 turns = 8 messages — nothing to strip
        history = self._make_history(4)
        c = compressor()
        result = c.apply_l1(history)
        # All assistant messages should still have JSONL
        for msg in result:
            if msg.role == "assistant":
                assert "[TOOL HISTORY JSONL]" in str(msg.content)

    def test_strips_oldest_beyond_protect_window(self):
        # 6 turns = 12 messages; L1_PROTECT_LAST_N=8 → first 4 are candidates
        history = self._make_history(6)
        c = compressor()
        result = c.apply_l1(history)

        # Messages 0-3 are outside the protection window
        for i, msg in enumerate(result):
            if msg.role == "assistant" and i < len(result) - L1_PROTECT_LAST_N:
                assert "[TOOL HISTORY JSONL]" not in str(msg.content), (
                    f"Message at index {i} should have had JSONL stripped"
                )
                assert "[ASSISTANT RESPONSE]" not in str(msg.content), (
                    f"Message at index {i} should only contain the bare response text"
                )

    def test_protected_messages_retain_jsonl(self):
        history = self._make_history(6)
        c = compressor()
        result = c.apply_l1(history)

        protected = result[-L1_PROTECT_LAST_N:]
        for msg in protected:
            if msg.role == "assistant":
                assert "[TOOL HISTORY JSONL]" in str(msg.content)

    def test_user_messages_never_touched(self):
        history = self._make_history(6)
        c = compressor()
        result = c.apply_l1(history)
        for msg in result:
            if msg.role == "user":
                assert "[TOOL HISTORY JSONL]" not in str(msg.content)


# ── L2: Microcompact ───────────────────────────────────────────────────────────

class TestL2Microcompact:
    def test_compact_jsonl_entry_large_payload(self):
        # Create a line that is much larger than L2_TOKEN_THRESHOLD
        big_line = make_tool_result_line("file-control", "read", payload_size=8000)
        assert estimate_text_tokens(big_line) > L2_TOKEN_THRESHOLD

        compacted = _compact_jsonl_entry(big_line)
        assert estimate_text_tokens(compacted) <= L2_TOKEN_THRESHOLD + 50  # small slack
        # Must still be valid JSON
        parsed = json.loads(compacted)
        assert parsed["payload"]["_compacted"] is True
        assert parsed["payload"]["skill"] == "file-control"
        assert parsed["payload"]["action"] == "read"

    def test_compact_jsonl_entry_small_payload_unchanged(self):
        small_line = make_tool_result_line("time-query", "now", payload_size=10)
        assert estimate_text_tokens(small_line) <= L2_TOKEN_THRESHOLD
        # _compact_jsonl_entry is called regardless; result must remain valid JSON
        result = _compact_jsonl_entry(small_line)
        json.loads(result)  # should not raise

    def test_apply_l2_compacts_large_entries(self):
        big_tool_line = make_tool_result_line("file-control", "read", payload_size=8000)
        history = [
            make_msg("user", "read a big file"),
            make_assistant_with_tool("Here is the content.", [big_tool_line]),
        ]
        c = compressor()
        result = c.apply_l2(history)

        assistant_content = result[1].content
        assert "[TOOL HISTORY JSONL]" in assistant_content
        assert "[ASSISTANT RESPONSE]" in assistant_content
        assert "_compacted" in assistant_content

    def test_apply_l2_leaves_small_entries_intact(self):
        small_line = make_tool_result_line("time-query", "now", payload_size=5)
        original_content = make_assistant_with_tool("Done.", [small_line]).content
        history = [
            make_msg("user", "what time is it"),
            make_assistant_with_tool("Done.", [small_line]),
        ]
        c = compressor()
        result = c.apply_l2(history)
        assert result[1].content == original_content  # unchanged

    def test_apply_l2_ignores_user_messages(self):
        history = [make_msg("user", "some big text " * 500)]
        c = compressor()
        result = c.apply_l2(history)
        assert result[0].content == history[0].content


# ── L3: Collapse ───────────────────────────────────────────────────────────────

class TestL3Collapse:
    def test_check_l3_not_needed_below_threshold(self):
        c = compressor(context_window=50_000)
        assert not c.check_l3_needed(total_tokens=20_000)  # 40 % < 60 %

    def test_check_l3_needed_at_threshold(self):
        c = compressor(context_window=50_000)
        threshold = int(50_000 * L3_USAGE_RATIO)
        assert c.check_l3_needed(total_tokens=threshold)

    def test_check_l3_not_triggered_when_context_window_zero(self):
        c = compressor(context_window=0)
        assert not c.check_l3_needed(total_tokens=999_999)

    def test_apply_l3_skipped_without_client(self):
        history = [make_msg("user", f"msg {i}") for i in range(8)]
        c = compressor(client=None)
        result = c.apply_l3(history)
        assert result is history  # unchanged reference

    def test_apply_l3_skipped_when_too_short(self):
        from agent.core.history_compressor import L3_PROTECT_LAST_N
        history = [make_msg("user", "hi")]
        c = compressor()
        result = c.apply_l3(history)
        assert result is history


class FakeLLMClient:
    """Minimal stub that returns a fixed summary."""

    def __init__(self, summary: str = "FACTS:\n- user asked things\n\nDECISIONS:\n- none\n\nANCHORS: none"):
        self.summary = summary
        self.called = False

    def chat(self, request):
        self.called = True
        return self.summary


class TestL3WithFakeClient:
    def _make_long_history(self, n_turns: int = 5) -> list[Message]:
        msgs: list[Message] = []
        for i in range(n_turns):
            msgs.append(make_msg("user", f"Turn {i} question"))
            msgs.append(make_msg("assistant", f"Turn {i} answer"))
        return msgs

    def test_l3_calls_llm_and_collapses(self):
        from agent.core.history_compressor import L3_PROTECT_LAST_N
        fake = FakeLLMClient()
        c = HistoryCompressor(
            context_window=50_000,
            client=fake,
            model="test-model",
        )
        history = self._make_long_history(5)  # 10 messages
        result = c.apply_l3(history)

        assert fake.called
        # Result: 1 summary message + last L3_PROTECT_LAST_N messages
        assert len(result) == 1 + L3_PROTECT_LAST_N
        assert result[0].role == "user"
        assert "CONVERSATION SUMMARY" in result[0].content
        assert fake.summary in result[0].content

    def test_l3_protected_messages_are_verbatim(self):
        from agent.core.history_compressor import L3_PROTECT_LAST_N
        fake = FakeLLMClient()
        c = HistoryCompressor(context_window=50_000, client=fake, model="m")
        history = self._make_long_history(5)
        protected_originals = history[-L3_PROTECT_LAST_N:]

        result = c.apply_l3(history)
        for orig, res in zip(protected_originals, result[1:]):
            assert orig.role == res.role
            assert orig.content == res.content

    def test_run_pipeline_triggers_l3_when_over_budget(self):
        fake = FakeLLMClient()
        c = HistoryCompressor(context_window=100, client=fake, model="m")
        history = self._make_long_history(5)
        # total_tokens >> 60 % of 100
        result, l3_triggered = c.run_pipeline(history, total_tokens=80)
        assert l3_triggered
        assert fake.called

    def test_run_pipeline_skips_l3_when_under_budget(self):
        fake = FakeLLMClient()
        c = HistoryCompressor(context_window=50_000, client=fake, model="m")
        history = self._make_long_history(3)
        result, l3_triggered = c.run_pipeline(history, total_tokens=1_000)
        assert not l3_triggered
        assert not fake.called


# ── _history_to_readable_text ─────────────────────────────────────────────────

class TestHistoryToReadableText:
    def test_strips_jsonl_for_readability(self):
        history = [
            make_msg("user", "what files?"),
            make_assistant_with_tool("Here are the files.", [make_tool_result_line("file-control", "list")]),
        ]
        text = _history_to_readable_text(history)
        assert "[USER]" in text
        assert "[ASSISTANT]" in text
        assert "Here are the files." in text
        assert "[TOOL HISTORY JSONL]" not in text

    def test_plain_messages_preserved(self):
        history = [
            make_msg("user", "hello"),
            make_msg("assistant", "world"),
        ]
        text = _history_to_readable_text(history)
        assert "hello" in text
        assert "world" in text
