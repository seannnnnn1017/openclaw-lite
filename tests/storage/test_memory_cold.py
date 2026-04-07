import sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest
from agent.storage.memory_cold import MemoryColdWriter


def test_start_session_creates_file(tmp_path):
    writer = MemoryColdWriter(tmp_path)
    writer.start_session()
    transcripts = list((tmp_path / "transcripts").glob("session-*.jsonl"))
    assert len(transcripts) == 1
    assert transcripts[0].stat().st_size == 0  # empty on creation


def test_append_turn_writes_two_lines(tmp_path):
    writer = MemoryColdWriter(tmp_path)
    writer.start_session()
    writer.append_turn("hello", "hi there")
    time.sleep(0.1)  # allow async write
    files = list((tmp_path / "transcripts").glob("session-*.jsonl"))
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    user_entry = json.loads(lines[0])
    assistant_entry = json.loads(lines[1])
    assert user_entry["role"] == "user"
    assert user_entry["content"] == "hello"
    assert assistant_entry["role"] == "assistant"
    assert assistant_entry["content"] == "hi there"
    assert "ts" in user_entry


def test_multiple_appends_go_to_same_file(tmp_path):
    writer = MemoryColdWriter(tmp_path)
    writer.start_session()
    writer.append_turn("msg1", "reply1")
    writer.append_turn("msg2", "reply2")
    time.sleep(0.2)
    files = list((tmp_path / "transcripts").glob("session-*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 4


def test_append_without_start_session_is_noop(tmp_path):
    writer = MemoryColdWriter(tmp_path)
    writer.append_turn("hello", "hi")  # no start_session called
    time.sleep(0.1)
    assert not (tmp_path / "transcripts").exists()
