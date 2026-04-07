import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest
from agent.storage.memory_writer import MemoryWriter


def test_write_creates_new_topic_file(tmp_path):
    writer = MemoryWriter(tmp_path)
    result = writer.write({
        "memory": "write",
        "file": "schedule-gotchas.md",
        "skill": "schedule-task",
        "title": "排程陷阱",
        "tags": ["scheduler", "gotcha"],
        "content": "## 相對時間\n需先呼叫 time-query.now",
    })
    assert result["status"] == "ok"
    topic = (tmp_path / "topics" / "schedule-gotchas.md")
    assert topic.exists()
    text = topic.read_text(encoding="utf-8")
    assert "skill: schedule-task" in text
    assert "排程陷阱" in text
    assert "相對時間" in text


def test_write_creates_index_entry(tmp_path):
    writer = MemoryWriter(tmp_path)
    writer.write({
        "memory": "write",
        "file": "prefs.md",
        "skill": "null",
        "title": "User prefs",
        "tags": [],
        "content": "繁體中文",
    })
    index = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "[prefs.md]" in index
    assert "skill:null" in index
    assert "User prefs" in index


def test_write_updates_existing_entry(tmp_path):
    writer = MemoryWriter(tmp_path)
    writer.write({"memory": "write", "file": "prefs.md", "skill": "null", "title": "Old title", "tags": [], "content": "v1"})
    writer.write({"memory": "write", "file": "prefs.md", "skill": "null", "title": "New title", "tags": [], "content": "v2"})
    index = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert index.count("[prefs.md]") == 1  # no duplicate
    assert "New title" in index
    assert "Old title" not in index


def test_write_missing_required_fields_returns_error(tmp_path):
    writer = MemoryWriter(tmp_path)
    result = writer.write({"memory": "write", "file": "", "content": ""})
    assert result["status"] == "error"


def test_search_finds_matching_lines(tmp_path):
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    session = transcripts / "session-20260407-120000.jsonl"
    entries = [
        {"ts": "2026-04-07T12:00:00+08:00", "role": "user", "content": "notion webhook 問題"},
        {"ts": "2026-04-07T12:00:01+08:00", "role": "assistant", "content": "根本原因是 polling 延遲"},
    ]
    session.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")

    writer = MemoryWriter(tmp_path)
    result = writer.search({"memory": "search", "query": "notion webhook", "limit": 10})
    assert "notion webhook" in result
    assert "session-20260407-120000.jsonl" in result


def test_search_no_match_returns_message(tmp_path):
    (tmp_path / "transcripts").mkdir()
    writer = MemoryWriter(tmp_path)
    result = writer.search({"memory": "search", "query": "nonexistent_xyz", "limit": 5})
    assert "No matches" in result


def test_search_no_transcripts_dir(tmp_path):
    writer = MemoryWriter(tmp_path)
    result = writer.search({"memory": "search", "query": "anything", "limit": 5})
    assert "No transcripts" in result
