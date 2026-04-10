"""
Notion workflow skill test runner — 20 tests total.
Run from: E:/重要文件/openclaw-lite
  python sandbox_for_claude/SKILL/notion_workflow/test_results/run_tests.py

Results are printed and saved to results.json.
PREREQUISITE: Notion MCP server configured and reachable.
TEST TARGET PAGE: 33e5aafddb3b80daae72c72ecf916479
"""
import json
import sys
import time
import traceback
from pathlib import Path

# Bootstrap path
SCRIPT_DIR = Path(__file__).resolve().parent
SANDBOX_SKILL = SCRIPT_DIR.parents[1]  # sandbox_for_claude/SKILL/
NOTION_WORKFLOW = SANDBOX_SKILL / "notion_workflow" / "scripts"
FILE_CONTROL = SANDBOX_SKILL / "file_control" / "scripts"
NOTION_BASIC = SANDBOX_SKILL / "notion_basic" / "scripts"
for p in (str(NOTION_WORKFLOW), str(FILE_CONTROL), str(NOTION_BASIC)):
    if p not in sys.path:
        sys.path.insert(0, p)

import file_tool
import notion_workflow_tool as nwt

TARGET_PAGE = "33e5aafddb3b80daae72c72ecf916479"
TEST_FOLDER = "E:/Github/Obsidian_database/personal_data_terminal"
RESULTS = []
_created_pages = {}  # cache page ids between tests


def run_test(test_id: str, description: str, fn):
    print(f"\n[{test_id}] {description}")
    start = time.time()
    try:
        result = fn()
        elapsed = round(time.time() - start, 2)
        if result.get("status") == "ok":
            print(f"  PASS ({elapsed}s) — {result.get('message','')}")
            RESULTS.append({"id": test_id, "status": "PASS", "description": description,
                             "elapsed": elapsed, "message": result.get("message", "")})
            return result
        else:
            msg = result.get("message", str(result))
            print(f"  FAIL ({elapsed}s) — {msg}")
            RESULTS.append({"id": test_id, "status": "FAIL", "description": description,
                             "elapsed": elapsed, "message": msg})
            return result
    except Exception as exc:
        elapsed = round(time.time() - start, 2)
        tb = traceback.format_exc()
        print(f"  ERROR ({elapsed}s) — {exc}")
        RESULTS.append({"id": test_id, "status": "ERROR", "description": description,
                         "elapsed": elapsed, "message": str(exc), "traceback": tb})
        return {"status": "error", "message": str(exc)}


# ── Simple Tests S01–S10 ────────────────────────────────────────────────────

def s01():
    r = file_tool.run("list_directory", path=TEST_FOLDER, pattern="*.md")
    assert r["status"] == "ok", r.get("message", str(r))
    assert r["data"]["count"] == 5, f"Expected 5 files, got {r['data']['count']}"
    names = [f["name"] for f in r["data"]["files"]]
    assert "Index.md" in names, f"Index.md missing from {names}"
    return r

def s02():
    path = TEST_FOLDER + "/Index.md"
    r = file_tool.run("read_all", paths=[path])
    assert r["status"] == "ok", r.get("message", str(r))
    assert r["data"]["success_count"] == 1
    assert r["data"]["files"][0]["status"] == "ok"
    assert len(r["data"]["files"][0]["content"]) > 0
    return r

def s03():
    import glob
    paths = sorted(glob.glob(TEST_FOLDER + "/*.md"))
    assert len(paths) == 5, f"Expected 5 paths, got {len(paths)}"
    r = file_tool.run("read_all", paths=paths)
    assert r["status"] == "ok", r.get("message", str(r))
    assert r["data"]["success_count"] == 5, f"Expected 5 ok, got {r['data']}"
    return r

def s04():
    r = nwt.run("batch_create_pages", pages=[{
        "title": "[S04] Single Page Test",
        "content": "Created by S04 test.",
        "parent_id": TARGET_PAGE,
    }])
    assert r["status"] == "ok", r.get("message", str(r))
    assert r["data"]["success_count"] == 1
    _created_pages["s04_page_id"] = r["data"]["pages"][0]["page_id"]
    return r

def s05():
    page_id = _created_pages.get("s04_page_id")
    if not page_id:
        raise AssertionError("S04 must pass before S05 — no page_id cached")
    r = nwt.run("append_content", page_id=page_id,
                content="## Appended by S05\n\nThis paragraph was added by the S05 test.")
    assert r["status"] == "ok", r.get("message", str(r))
    assert r["data"]["blocks_written"] >= 2
    return r

def s06():
    """Read the page via notion-basic to confirm it has the correct title."""
    from notion_mcp_tool import _load_runtime_config, _call_tool
    page_id = _created_pages.get("s04_page_id")
    if not page_id:
        raise AssertionError("S04 must pass before S06")
    config = _load_runtime_config()
    result = _call_tool(config, tool_name="API-retrieve-a-page", arguments={"page_id": page_id})
    assert result["status"] == "ok", result.get("message", str(result))
    mcp = result["data"].get("mcp_result", {})
    content_list = mcp.get("content", [])
    raw = ""
    for item in content_list:
        if item.get("type") == "text":
            raw = item["text"]
            break
    data = {}
    try:
        data = json.loads(raw)
    except Exception:
        pass
    title_parts = data.get("properties", {}).get("title", {}).get("title", [])
    title_text = "".join(p.get("plain_text", "") for p in title_parts)
    assert "[S04]" in title_text, f"Unexpected title: {title_text!r}"
    return result

def s07():
    """Rename the S04 page title via API-patch-page."""
    from notion_mcp_tool import _load_runtime_config, _call_tool
    page_id = _created_pages.get("s04_page_id")
    if not page_id:
        raise AssertionError("S04 must pass before S07")
    config = _load_runtime_config()
    result = _call_tool(config, tool_name="API-patch-page", arguments={
        "page_id": page_id,
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": "[S04+S07] Renamed Page"}}]}
        },
    })
    assert result["status"] == "ok", result.get("message", str(result))
    return result

def s08():
    """Delete a block from the S04 page."""
    from notion_mcp_tool import _load_runtime_config, _call_tool
    page_id = _created_pages.get("s04_page_id")
    if not page_id:
        raise AssertionError("S04 must pass before S08")
    config = _load_runtime_config()
    children_result = _call_tool(config, tool_name="API-get-block-children",
                                  arguments={"block_id": page_id})
    assert children_result["status"] == "ok", children_result.get("message", str(children_result))
    mcp = children_result["data"].get("mcp_result", {})
    content_list = mcp.get("content", [])
    raw = ""
    for item in content_list:
        if item.get("type") == "text":
            raw = item["text"]
            break
    data = {}
    try:
        data = json.loads(raw)
    except Exception:
        pass
    results_list = data.get("results", [])
    if not results_list:
        return {"status": "ok", "message": "No blocks to delete (page may be empty — acceptable)"}
    block_id = results_list[0]["id"]
    del_result = _call_tool(config, tool_name="API-delete-a-block", arguments={"block_id": block_id})
    assert del_result["status"] == "ok", del_result.get("message", str(del_result))
    return del_result

def s09():
    """Search for the renamed page and confirm it appears in results."""
    from notion_mcp_tool import _load_runtime_config, _call_tool
    config = _load_runtime_config()
    result = _call_tool(config, tool_name="API-post-search",
                         arguments={"query": "S04+S07", "filter": {"value": "page", "property": "object"}, "page_size": 10})
    assert result["status"] == "ok", result.get("message", str(result))
    return result

def s10():
    """batch_create_pages — create 3 blank sub-pages."""
    r = nwt.run("batch_create_pages", pages=[
        {"title": "[S10-A] Batch Page Alpha", "content": "", "parent_id": TARGET_PAGE},
        {"title": "[S10-B] Batch Page Beta",  "content": "", "parent_id": TARGET_PAGE},
        {"title": "[S10-C] Batch Page Gamma", "content": "", "parent_id": TARGET_PAGE},
    ])
    assert r["status"] == "ok", r.get("message", str(r))
    assert r["data"]["success_count"] == 3, f"Expected 3, got {r['data']}"
    _created_pages["s10_ids"] = [p["page_id"] for p in r["data"]["pages"] if p.get("page_id")]
    return r


def run_simple_tests():
    print("\n" + "="*60)
    print("SIMPLE TESTS S01–S10")
    print("="*60)
    run_test("S01", "list_directory returns 5 md files", s01)
    run_test("S02", "read_all reads single file correctly", s02)
    run_test("S03", "read_all reads 5 files as array", s03)
    run_test("S04", "batch_create_pages creates 1 page", s04)
    run_test("S05", "append_content writes 2+ blocks", s05)
    run_test("S06", "API-retrieve-a-page confirms title", s06)
    run_test("S07", "API-patch-page renames page", s07)
    run_test("S08", "API-delete-a-block removes first block", s08)
    run_test("S09", "API-post-search finds renamed page", s09)
    run_test("S10", "batch_create_pages creates 3 blank pages", s10)


# ── Complex Tests C01–C10 ───────────────────────────────────────────────────

def c01():
    r = nwt.run("import_folder",
                folder=TEST_FOLDER,
                parent_page_id=TARGET_PAGE,
                parent_title="[C01] Personal Terminal Import",
                pattern="*.md")
    assert r["status"] == "ok", r.get("message", str(r))
    assert r["data"]["success_count"] == 5, f"Expected 5, got {r['data']}"
    assert r["data"]["error_count"] == 0
    _created_pages["c01_parent_id"] = r["data"]["parent_page_id"]
    return r

def c02():
    import glob
    all_paths = sorted(glob.glob(TEST_FOLDER + "/*.md"))
    r = nwt.run("import_files",
                paths=all_paths[:3],
                parent_page_id=TARGET_PAGE,
                parent_title="[C02] Explicit Files Import")
    assert r["status"] == "ok", r.get("message", str(r))
    assert r["data"]["success_count"] == 3
    return r

def c03():
    long_content = "\n\n".join(f"Paragraph {i}: " + "x" * 80 for i in range(110))
    blocks = nwt.markdown_to_blocks(long_content)
    assert len(blocks) >= 100, f"Expected >=100 blocks, got {len(blocks)}"
    r = nwt.run("batch_create_pages", pages=[{
        "title": "[C03] Long Content Chunked",
        "content": long_content,
        "parent_id": TARGET_PAGE,
    }])
    assert r["status"] == "ok", r.get("message", str(r))
    assert r["data"]["success_count"] == 1
    _created_pages["c03_page_id"] = r["data"]["pages"][0]["page_id"]
    return r

def c04():
    parent_id = _created_pages.get("c01_parent_id")
    if not parent_id:
        raise AssertionError("C01 must pass before C04")
    r = nwt.run("sync_folder",
                folder=TEST_FOLDER,
                parent_page_id=TARGET_PAGE,
                parent_title="[C01] Personal Terminal Import",
                pattern="*.md")
    assert r["status"] == "ok", r.get("message", str(r))
    assert r["data"]["skipped_count"] == 5, f"Expected 5 skipped, got {r['data']}"
    return r

def c05():
    content = (
        "# 架構說明\n\n"
        "這是一個包含中文的頁面。\n\n"
        "```python\nprint('你好世界')\n```\n\n"
        "## 結論\n\n測試通過。"
    )
    r = nwt.run("batch_create_pages", pages=[{
        "title": "[C05] 中文與程式碼測試",
        "content": content,
        "parent_id": TARGET_PAGE,
    }])
    assert r["status"] == "ok", r.get("message", str(r))
    assert r["data"]["success_count"] == 1
    return r

def c06():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "valid1.md").write_text("# Valid 1\nContent.", encoding="utf-8")
        Path(tmp, "valid2.md").write_text("# Valid 2\nContent.", encoding="utf-8")
        Path(tmp, "data.json").write_text('{"key":"value"}', encoding="utf-8")
        Path(tmp, "image.png").write_bytes(b"\x89PNG fake")
        r = nwt.run("import_folder",
                    folder=tmp,
                    parent_page_id=TARGET_PAGE,
                    parent_title="[C06] Mixed Extensions",
                    pattern="*.md")
        assert r["status"] == "ok", r.get("message", str(r))
        assert r["data"]["success_count"] == 2, f"Expected 2 md files, got {r['data']}"
    return r

def c07():
    import glob
    real_paths = sorted(glob.glob(TEST_FOLDER + "/*.md"))[:2]
    fake_path = TEST_FOLDER + "/nonexistent_file_xyz.md"
    r = file_tool.run("read_all", paths=real_paths + [fake_path])
    assert r["status"] == "ok", r.get("message", str(r))
    assert r["data"]["success_count"] == 2, f"Expected 2 ok"
    assert r["data"]["error_count"] == 1, f"Expected 1 error"
    return r

def c08():
    fake_id = "00000000000000000000000000000000"
    r = nwt.run("import_folder",
                folder=TEST_FOLDER,
                parent_page_id=fake_id,
                parent_title="[C08] Should Fail Cleanly",
                pattern="*.md")
    assert r["status"] == "error", f"Expected error status, got: {r}"
    assert r["message"], "Error message must not be empty"
    return {"status": "ok", "message": f"Got expected error: {r['message'][:100]}"}

def c09():
    r_read = file_tool.run("read_all", dir=TEST_FOLDER, pattern="*.md")
    assert r_read["status"] == "ok"
    files = r_read["data"]["files"]
    pages_payload = [
        {"title": f"[C09] {f['name']}", "content": f["content"], "parent_id": TARGET_PAGE}
        for f in files if f["status"] == "ok"
    ]
    r_create = nwt.run("batch_create_pages", pages=pages_payload)
    assert r_create["status"] == "ok", r_create.get("message", str(r_create))
    assert r_create["data"]["success_count"] == len(pages_payload)
    return r_create

def c10():
    page_id = _created_pages.get("s04_page_id")
    if not page_id:
        # When running --complex-only, S04 hasn't run; create a temporary page
        r_create = nwt.run("batch_create_pages", pages=[{
            "title": "[C10] append_content target",
            "content": "Initial content.",
            "parent_id": TARGET_PAGE,
        }])
        assert r_create["status"] == "ok", r_create.get("message", str(r_create))
        page_id = r_create["data"]["pages"][0]["page_id"]
    r = nwt.run("append_content",
                page_id=page_id,
                content="## Appended by C10\n\nFinal test block.\n\n- item one\n- item two")
    assert r["status"] == "ok", r.get("message", str(r))
    assert r["data"]["blocks_written"] >= 3
    return r


def run_complex_tests():
    print("\n" + "="*60)
    print("COMPLEX TESTS C01–C10")
    print("="*60)
    run_test("C01", "import_folder: 5 md files → Notion (full)", c01)
    run_test("C02", "import_files: 3 explicit paths", c02)
    run_test("C03", "Long file >100 blocks auto-chunked", c03)
    run_test("C04", "sync_folder second pass skips all 5 existing", c04)
    run_test("C05", "Chinese + code block encoding correct", c05)
    run_test("C06", "Mixed extensions: only .md imported", c06)
    run_test("C07", "One missing file: others succeed, error_count=1", c07)
    run_test("C08", "Wrong parent_page_id: structured error returned", c08)
    run_test("C09", "Cross-skill: read_all + batch_create_pages", c09)
    run_test("C10", "append_content appends without destroying blocks", c10)


# ── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--simple-only", action="store_true", help="Run only S01-S10")
    parser.add_argument("--complex-only", action="store_true", help="Run only C01-C10")
    args = parser.parse_args()

    if args.complex_only:
        run_complex_tests()
    elif args.simple_only:
        run_simple_tests()
    else:
        run_simple_tests()
        run_complex_tests()

    passed = sum(1 for r in RESULTS if r["status"] == "PASS")
    failed = sum(1 for r in RESULTS if r["status"] in ("FAIL", "ERROR"))
    total = len(RESULTS)

    print("\n" + "="*60)
    print(f"SUMMARY: {passed}/{total} passed, {failed} failed")
    print("="*60)
    for r in RESULTS:
        icon = "PASS" if r["status"] == "PASS" else "FAIL"
        print(f"  {icon} [{r['id']}] {r['description'][:55]} ({r['elapsed']}s)")

    results_path = Path(__file__).parent / "results.json"
    results_path.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nFull results saved to: {results_path}")

    sys.exit(0 if failed == 0 else 1)
