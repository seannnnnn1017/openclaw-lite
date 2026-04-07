import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest
from agent.storage.memory_hot import MemoryHotLayer

MAX_LINES = 200
MAX_BYTES = 25_000
WARNING = "[WARNING: memory index truncated, some entries not loaded]"


def test_missing_file_returns_empty(tmp_path):
    layer = MemoryHotLayer(tmp_path)
    assert layer.load() == ""


def test_empty_file_returns_empty(tmp_path):
    (tmp_path / "MEMORY.md").write_text("   \n", encoding="utf-8")
    layer = MemoryHotLayer(tmp_path)
    assert layer.load() == ""


def test_normal_content_returned_as_is(tmp_path):
    content = "- [file.md] skill:null | updated:2026-01-01 | desc\n"
    (tmp_path / "MEMORY.md").write_text(content, encoding="utf-8")
    layer = MemoryHotLayer(tmp_path)
    assert layer.load() == content


def test_truncates_at_200_lines(tmp_path):
    lines = [f"- [f{i}.md] skill:null | updated:2026-01-01 | desc {i}\n" for i in range(210)]
    (tmp_path / "MEMORY.md").write_text("".join(lines), encoding="utf-8")
    layer = MemoryHotLayer(tmp_path)
    result = layer.load()
    assert result.count("\n") <= MAX_LINES + 2  # content lines + WARNING line
    assert WARNING in result
    assert "desc 200" not in result  # line 201+ truncated


def test_truncates_at_25kb(tmp_path):
    # ~200 chars per line × 130 lines ≈ 26KB
    lines = [f"- [f{i}.md] skill:null | updated:2026-01-01 | {'x' * 160}\n" for i in range(130)]
    (tmp_path / "MEMORY.md").write_text("".join(lines), encoding="utf-8")
    layer = MemoryHotLayer(tmp_path)
    result = layer.load()
    assert len(result.encode("utf-8")) <= MAX_BYTES + 300  # allow for WARNING text
    assert WARNING in result


def test_truncation_does_not_cut_mid_line(tmp_path):
    lines = [f"- [f{i}.md] skill:null | updated:2026-01-01 | {'x' * 160}\n" for i in range(130)]
    (tmp_path / "MEMORY.md").write_text("".join(lines), encoding="utf-8")
    layer = MemoryHotLayer(tmp_path)
    result = layer.load()
    # Every line before WARNING must start with "- ["
    content_lines = result.split(WARNING)[0].splitlines()
    for line in content_lines:
        stripped = line.strip()
        if stripped:
            assert stripped.startswith("- ["), f"Mid-line cut detected: {stripped[:60]}"
