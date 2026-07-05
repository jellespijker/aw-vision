"""Timeline compression and formatting for desktop activity records.

Provides clean utility functions to group consecutive/similar activities
and format them into compact time range strings, avoiding context bloat.
"""

from datetime import datetime
from typing import Any, Dict, List, Tuple


def format_time_range(start_ts: float, end_ts: float, multi_day: bool) -> str:
    """Format a start/end timestamp pair into a clean time range string.

    Examples:
      - Same day, multi_day=False: '09:00-09:15'
      - Same day, multi_day=True: 'Mon 09:00-09:15'
      - Cross-day range: 'Sun 23:45-Mon 00:15'
    """
    dt_start = datetime.fromtimestamp(start_ts)
    dt_end = datetime.fromtimestamp(end_ts)
    fmt = "%a %H:%M" if multi_day else "%H:%M"

    if end_ts - start_ts < 60.0:  # single snapshot
        return dt_start.strftime(fmt)

    if dt_start.date() != dt_end.date():
        return f"{dt_start.strftime('%a %H:%M')}-{dt_end.strftime('%a %H:%M')}"

    return f"{dt_start.strftime(fmt)}-{dt_end.strftime('%H:%M')}"


def compress_timeline_records(records: List[Dict[str, Any]], interval_seconds: float) -> List[Dict[str, Any]]:
    """Group and merge chronological records into a compact timeline.

    Merges consecutive identical activity events into time ranges,
    and then groups identical activities across the whole timeline.
    """
    if not records:
        return []

    # 1. Parse and extract clean fields from records
    parsed_events = []
    for r in records:
        app = r.get("app_name") or "Unknown"
        desc = (r.get("description") or "").strip()
        if not desc:
            desc = (r.get("window_title") or "N/A").strip()
        proj = r.get("project_number") or "Unclassified"
        ts = r.get("timestamp", 0.0)
        parsed_events.append({"app_name": app, "description": desc, "project_number": proj, "timestamp": ts})

    # Sort chronologically by timestamp
    parsed_events.sort(key=lambda x: x["timestamp"])

    # 2. Merge consecutive identical events into ranges
    max_gap = max(interval_seconds * 2.5, 600.0)  # at least 10 minutes

    raw_ranges = []
    current_event = None

    for ev in parsed_events:
        key = (ev["app_name"], ev["description"], ev["project_number"])
        ts = ev["timestamp"]

        if current_event is None:
            current_event = {"key": key, "start_ts": ts, "end_ts": ts}
        elif current_event["key"] == key and (ts - current_event["end_ts"]) <= max_gap:
            current_event["end_ts"] = ts
        else:
            raw_ranges.append(current_event)
            current_event = {"key": key, "start_ts": ts, "end_ts": ts}

    if current_event:
        raw_ranges.append(current_event)

    # 3. Group identical activities across the entire timeline
    grouped = {}
    first_seen = {}

    for r_range in raw_ranges:
        key = r_range["key"]
        r_tuple = (r_range["start_ts"], r_range["end_ts"])

        if key not in grouped:
            grouped[key] = []
            first_seen[key] = r_range["start_ts"]

        grouped[key].append(r_tuple)

    # 4. Format and sort by first_seen timestamp
    sorted_keys = sorted(grouped.keys(), key=lambda k: first_seen[k])

    # Check if total timeframe is multi-day (span > 24 hours)
    total_span = 0.0
    if parsed_events:
        total_span = parsed_events[-1]["timestamp"] - parsed_events[0]["timestamp"]
    multi_day = total_span > 86400.0

    result = []
    for key in sorted_keys:
        app, desc, proj = key
        ranges = grouped[key]

        # Merge overlapping/touching ranges in the list of ranges for this activity
        ranges.sort(key=lambda x: x[0])
        merged_ranges = []
        for r_start, r_end in ranges:
            if not merged_ranges:
                merged_ranges.append((r_start, r_end))
            else:
                last_start, last_end = merged_ranges[-1]
                if r_start <= last_end + max_gap:
                    merged_ranges[-1] = (last_start, max(last_end, r_end))
                else:
                    merged_ranges.append((r_start, r_end))

        # Format the time ranges
        range_strings = []
        for r_start, r_end in merged_ranges:
            range_strings.append(format_time_range(r_start, r_end, multi_day))

        ranges_str = ", ".join(range_strings)

        result.append(
            {
                "app_name": app,
                "description": desc,
                "project_number": proj,
                "ranges_str": ranges_str,
                "first_seen": first_seen[key],
            }
        )

    return result
