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
