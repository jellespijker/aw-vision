"""Unit tests for the timeline compression and formatting logic."""

from datetime import datetime, timedelta

import pytest

from aw_vision.timeline import compress_timeline_records, format_time_range


def test_format_time_range():
    # Base datetime: Mon Jul 6 09:00:00 2026
    base_dt = datetime(2026, 7, 6, 9, 0, 0)
    base_ts = base_dt.timestamp()

    # Same day, single snapshot, multi_day=False
    assert format_time_range(base_ts, base_ts, multi_day=False) == "09:00"

    # Same day, single snapshot, multi_day=True
    assert format_time_range(base_ts, base_ts, multi_day=True) == "Mon 09:00"

    # Same day range, multi_day=False
    assert format_time_range(base_ts, base_ts + 900, multi_day=False) == "09:00-09:15"

    # Same day range, multi_day=True
    assert format_time_range(base_ts, base_ts + 900, multi_day=True) == "Mon 09:00-09:15"

    # Cross-day range (e.g. crossing midnight from Mon 23:50 to Tue 00:10)
    mon_late = datetime(2026, 7, 6, 23, 50, 0).timestamp()
    tue_early = datetime(2026, 7, 7, 0, 10, 0).timestamp()
    assert format_time_range(mon_late, tue_early, multi_day=False) == "Mon 23:50-Tue 00:10"


def test_compress_timeline_records_empty():
    assert compress_timeline_records([], 60.0) == []


def test_compress_timeline_records_grouping():
    # base timestamps for testing
    t0 = datetime(2026, 7, 6, 9, 0, 0).timestamp()
    t1 = t0 + 60  # 9:01
    t2 = t0 + 120  # 9:02
    t3 = t0 + 900  # 9:15 (gap > 10m)
    t4 = t0 + 960  # 9:16

    records = [
        # Consecutive group 1 (9:00 - 9:02)
        {
            "timestamp": t0,
            "app_name": "Firefox",
            "description": "reading python docs",
            "project_number": "PRJ-2026-042",
        },
        {
            "timestamp": t1,
            "app_name": "Firefox",
            "description": "reading python docs",
            "project_number": "PRJ-2026-042",
        },
        {
            "timestamp": t2,
            "app_name": "Firefox",
            "description": "reading python docs",
            "project_number": "PRJ-2026-042",
        },
        # Interruption (9:15)
        {
            "timestamp": t3,
            "app_name": "Terminal",
            "description": "running pytest",
            "project_number": "PRJ-2026-042",
        },
        # Group 1 repeated (9:16) - should be grouped with group 1 but as distinct range
        {
            "timestamp": t4,
            "app_name": "Firefox",
            "description": "reading python docs",
            "project_number": "PRJ-2026-042",
        },
    ]

    compressed = compress_timeline_records(records, 60.0)

    assert len(compressed) == 2

    # Verify Firefox group (first seen at 9:00)
    firefox_group = next(c for c in compressed if c["app_name"] == "Firefox")
    assert firefox_group["description"] == "reading python docs"
    assert firefox_group["project_number"] == "PRJ-2026-042"
    # Should list both ranges: 09:00-09:02 and 09:16
    assert firefox_group["ranges_str"] == "09:00-09:02, 09:16"

    # Verify Terminal group (first seen at 9:15)
    terminal_group = next(c for c in compressed if c["app_name"] == "Terminal")
    assert terminal_group["description"] == "running pytest"
    assert terminal_group["project_number"] == "PRJ-2026-042"
    assert terminal_group["ranges_str"] == "09:15"

    # Verify sort order (Firefox first seen at t0, Terminal first seen at t3)
    assert compressed[0]["app_name"] == "Firefox"
    assert compressed[1]["app_name"] == "Terminal"


def test_divide_and_conquer_compress(monkeypatch):
    from unittest.mock import patch
    from aw_vision.tool_summary import divide_and_conquer_compress
    from aw_vision.settings import settings_store

    # Mock settings to return a small chunk limit of 50 characters
    monkeypatch.setattr(settings_store, "get_int", lambda key: 50 if key == "max_summarize_chunk_chars" else 8192)

    # 1. Short input: below max chunk limit, should be returned directly
    short_input = "Line 1\nLine 2"
    assert divide_and_conquer_compress("test_tool", short_input) == short_input

    # 2. Long input: split into multiple chunks and summarized
    long_input = (
        "Line A is a very long line that exceeds fifty characters\n"
        "Line B is another long line that also exceeds fifty characters\n"
        "Line C is also long"
    )

    mock_calls = []

    def mock_summarize_chunk(tool_name, chunk_content):
        mock_calls.append(chunk_content)
        return f"Summary: {chunk_content[:15]}..."

    with patch("aw_vision.tool_summary._summarize_chunk", side_effect=mock_summarize_chunk):
        result = divide_and_conquer_compress("test_tool", long_input)
        assert len(mock_calls) >= 2
        assert "Summary:" in result

    # 3. Single extremely long line: no newlines, should hard character split
    long_single_line = "A" * 150
    mock_calls.clear()
    with patch("aw_vision.tool_summary._summarize_chunk", side_effect=mock_summarize_chunk):
        result = divide_and_conquer_compress("test_tool", long_single_line)
        # Should split 150 chars into ~3 chunks of 50 chars each
        assert len(mock_calls) >= 3
        assert all(len(c) <= 50 for c in mock_calls)
        assert "Summary:" in result

    # 4. Recursion depth limit safety: if depth >= 2, fall back to programmatic compression
    # We simulate this by returning a large string from summarize chunk so it remains > 50
    def mock_oversized_summary(tool_name, chunk_content):
        return "B" * 100

    with patch("aw_vision.tool_summary._summarize_chunk", side_effect=mock_oversized_summary):
        result = divide_and_conquer_compress("test_tool", long_input)
        # Should not recurse infinitely, but fall back to programmatic compression
        assert "[Truncated" in result or "B" in result or "..." in result


def test_programmatic_compress_records():
    from aw_vision.tool_summary import programmatic_compress_records

    # 1. Unstructured text - Verify head-tail truncation
    long_unstructured = "A" * 4000
    compressed_unstructured = programmatic_compress_records(long_unstructured)
    assert "[Truncated" in compressed_unstructured
    assert len(compressed_unstructured) < 3200
    assert compressed_unstructured.startswith("A" * 1500)
    assert compressed_unstructured.endswith("A" * 1500)

    # 2. Structured records - Verify progressive resolution thinning
    # 6 records (limit: max_full=2, max_total=4)
    structured_input = (
        "- [09:00] Firefox | Reading docs\n"
        "  Desc: Firefox reading python docs\n"
        "  OCR: hello world text\n"
        "  Tags: web | Proj: PRJ-1\n"
        "- [09:01] Firefox | Reading more docs\n"
        "  Desc: Firefox reading more python docs\n"
        "  OCR: hello universe text\n"
        "  Tags: web | Proj: PRJ-1\n"
        "- [09:02] VS Code | Coding\n"
        "  Desc: VS Code editing timeline.py\n"
        "  OCR: def compress_timeline_records\n"
        "  Tags: code | Proj: PRJ-1\n"
        "- [09:03] VS Code | Debugging\n"
        "  Desc: VS Code running pytest\n"
        "  OCR: collected 4 items\n"
        "  Tags: code | Proj: PRJ-1\n"
        "- [09:04] Slack | Chatting\n"
        "  Desc: Slack talking to team\n"
        "  OCR: status updates\n"
        "  Tags: chat | Proj: PRJ-2\n"
        "- [09:05] Spotify | Listening to music\n"
        "  Desc: Spotify playing lofi\n"
        "  OCR: N/A\n"
        "  Tags: music | Proj: PRJ-3"
    )

    # With max_full=2 and max_total=4 (max_headers_limit is 50, so up to 50 kept as header-only)
    compressed_structured = programmatic_compress_records(structured_input, max_full_records=2, max_total_records=4)

    # Record 1 (full detail)
    assert "- [09:00] Firefox | Reading docs" in compressed_structured
    assert "  Desc: Firefox reading python docs" in compressed_structured
    assert "  OCR: hello world text" in compressed_structured

    # Record 3 (max_full < index <= max_total: header + desc only)
    assert "- [09:02] VS Code | Coding" in compressed_structured
    assert "  Desc: VS Code editing timeline.py" in compressed_structured
    assert "  OCR: def compress_timeline_records" not in compressed_structured

    # Record 5 (index > max_total: header only)
    assert "- [09:04] Slack | Chatting" in compressed_structured
    assert "  Desc: Slack talking to team" not in compressed_structured
    assert "  OCR: status updates" not in compressed_structured


def test_summarize_ocr_text_progressive_thinning():
    from aw_vision.processor.ocr import OcrMixin
    mixin = OcrMixin()

    # 1. Fits within character limit
    ocr_text = "Line 1\nLine 2\nLine 3"
    assert mixin.summarize_ocr_text(ocr_text, max_chars=100) == "Line 1 | Line 2 | Line 3"

    # 2. Exceeds limit, should apply head-tail thinning
    ocr_long = "Heading\nFile Edit\nrepetitive line\nanother repet\nFooter Status"
    res = mixin.summarize_ocr_text(ocr_long, max_chars=60)
    assert "omitted" in res
    assert "Heading" in res
    assert "Status" in res

    # 3. Very tight limit, should only fit head + omitted
    res_tight = mixin.summarize_ocr_text(ocr_long, max_chars=35)
    assert "omitted" in res_tight
    assert "Heading" in res
    assert "Status" not in res_tight


def test_build_similar_snapshots_context_thinning(monkeypatch):
    from unittest.mock import MagicMock
    from aw_vision.processor.history_context import build_similar_snapshots_context
    from aw_vision.db import db
    import json

    mock_record = {
        "app_name": "Terminal",
        "window_title": "Running tests",
        "description": "Executed pytest successfully",
        "project_number": "PRJ-2026-042",
        "human_labeled": True,
        # Heavy fields to be thinned out:
        "ocr_text": "A" * 1000,
        "project_reasoning": "Matching keywords present...",
        "vector": [0.1] * 384,
    }

    monkeypatch.setattr(db, "get_similar_labeled_snapshots_by_metadata", MagicMock(return_value=[mock_record]))

    result_json = build_similar_snapshots_context("Terminal", "Running tests")
    result_data = json.loads(result_json)

    assert len(result_data) == 1
    item = result_data[0]
    assert item["app_name"] == "Terminal"
    assert item["window_title"] == "Running tests"
    assert item["description"] == "Executed pytest successfully"
    assert item["project_number"] == "PRJ-2026-042"
    assert item["human_labeled"] is True

    # Assert heavy fields were successfully thinned out
    assert "ocr_text" not in item
    assert "project_reasoning" not in item
    assert "vector" not in item
