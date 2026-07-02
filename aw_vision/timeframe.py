"""Natural-language timeframe parsing for the memory agent.

The local agent LLM is small and unreliable at computing epoch timestamps for phrases
like "yesterday" or "this morning", which made date-filtered questions return the wrong
records. This module resolves such phrases to a concrete ``(start_epoch, end_epoch, label)``
window *deterministically in Python* so the agent never has to do date math itself.
"""

import re
from datetime import datetime, time, timedelta
from typing import Optional, Tuple

# Parts of the day, expressed as (start_hour, end_hour) on a 24h clock.
DAY_PARTS = {
    "morning": (5, 12),
    "afternoon": (12, 17),
    "evening": (17, 22),
    "night": (22, 24),
}

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def _day_bounds(day: datetime) -> Tuple[float, float]:
    """Return (start, end) epoch seconds spanning the full calendar day of ``day``."""
    start = datetime.combine(day.date(), time.min)
    end = datetime.combine(day.date(), time.max)
    return start.timestamp(), end.timestamp()


def _part_bounds(day: datetime, part: str) -> Tuple[float, float]:
    """Return epoch bounds for a part-of-day (e.g. morning) on ``day``."""
    start_h, end_h = DAY_PARTS[part]
    start = datetime.combine(day.date(), time(hour=start_h))
    if end_h >= 24:
        end = datetime.combine(day.date(), time.max)
    else:
        end = datetime.combine(day.date(), time(hour=end_h))
    return start.timestamp(), end.timestamp()


def parse_timeframe(text: str, now: Optional[datetime] = None) -> Optional[Tuple[float, float, str]]:
    """Resolve a natural-language timeframe to ``(start_epoch, end_epoch, label)``.

    Returns ``None`` when nothing date-like is recognised, so the caller can decide on a
    fallback. ``now`` is injectable to keep the logic testable.
    """
    if not text:
        return None
    now = now or datetime.now()
    t = text.strip().lower()

    # --- Explicit ISO date or date range: 2026-06-28 [to 2026-06-29] ---
    iso_dates = re.findall(r"\d{4}-\d{2}-\d{2}", t)
    if iso_dates:
        try:
            first = datetime.strptime(iso_dates[0], "%Y-%m-%d")
            last = datetime.strptime(iso_dates[-1], "%Y-%m-%d")
            start, _ = _day_bounds(first)
            _, end = _day_bounds(last)
            if len(iso_dates) > 1:
                return start, end, f"{iso_dates[0]} to {iso_dates[-1]}"
            return start, end, iso_dates[0]
        except ValueError:
            pass

    # --- Relative day anchor (today / yesterday) optionally + part-of-day ---
    anchor_day = None
    anchor_label = None
    if "yesterday" in t:
        anchor_day = now - timedelta(days=1)
        anchor_label = "yesterday"
    elif "today" in t or "this day" in t:
        anchor_day = now
        anchor_label = "today"

    part = next((p for p in DAY_PARTS if p in t), None)
    if anchor_day is not None:
        if part:
            start, end = _part_bounds(anchor_day, part)
            return start, end, f"{anchor_label} {part}"
        start, end = _day_bounds(anchor_day)
        return start, end, anchor_label

    # "this morning" / "this afternoon" etc. without an explicit day -> today
    if part and ("this" in t or part in t):
        start, end = _part_bounds(now, part)
        # If the part hasn't started yet today, fall back to yesterday's part.
        if start > now.timestamp():
            start, end = _part_bounds(now - timedelta(days=1), part)
            return start, end, f"yesterday {part}"
        return start, end, f"this {part}"

    # --- Rolling windows: "last/past N hours|days|weeks" ---
    m = re.search(r"(?:last|past|previous)\s+(\d+)\s+(hour|day|week|month)s?", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        delta = {
            "hour": timedelta(hours=n),
            "day": timedelta(days=n),
            "week": timedelta(weeks=n),
            "month": timedelta(days=30 * n),
        }[unit]
        start = (now - delta).timestamp()
        return start, now.timestamp(), f"last {n} {unit}{'s' if n != 1 else ''}"

    # "last hour" / "past hour" (no number)
    if re.search(r"(?:last|past|previous)\s+hour", t):
        return (now - timedelta(hours=1)).timestamp(), now.timestamp(), "last hour"

    # --- Week / month windows ---
    if "this week" in t:
        monday = now - timedelta(days=now.weekday())
        start, _ = _day_bounds(monday)
        return start, now.timestamp(), "this week"
    if "last week" in t or "previous week" in t:
        this_monday = now - timedelta(days=now.weekday())
        last_monday = this_monday - timedelta(days=7)
        start, _ = _day_bounds(last_monday)
        _, end = _day_bounds(last_monday + timedelta(days=6))
        return start, end, "last week"
    if "this month" in t:
        first = now.replace(day=1)
        start, _ = _day_bounds(first)
        return start, now.timestamp(), "this month"

    # --- Named weekday: "monday" / "last friday" (most recent past occurrence) ---
    for name, idx in WEEKDAYS.items():
        if name in t:
            days_back = (now.weekday() - idx) % 7
            if days_back == 0:
                days_back = 0 if "this" in t else 7 if ("last" in t or "previous" in t) else 0
            elif "last" in t or "previous" in t:
                # already the most recent past occurrence; keep days_back
                pass
            target = now - timedelta(days=days_back)
            start, end = _day_bounds(target)
            return start, end, target.strftime("%A %Y-%m-%d")

    return None
