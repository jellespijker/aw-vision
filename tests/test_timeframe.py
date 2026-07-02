from datetime import datetime

from aw_vision.timeframe import parse_timeframe

# Fixed anchor: Monday 2026-06-29 14:30 local.
NOW = datetime(2026, 6, 29, 14, 30, 0)


def _span(label):
    res = parse_timeframe(label, now=NOW)
    assert res is not None, f"failed to parse {label!r}"
    start, end, _ = res
    return datetime.fromtimestamp(start), datetime.fromtimestamp(end)


def test_yesterday_is_full_previous_day():
    start, end = _span("What did I work on yesterday")
    assert start.date() == datetime(2026, 6, 28).date()
    assert end.date() == datetime(2026, 6, 28).date()
    assert (start.hour, start.minute) == (0, 0)
    assert end.hour == 23


def test_today_spans_today():
    start, end = _span("today")
    assert start.date() == NOW.date()
    assert (start.hour, start.minute) == (0, 0)


def test_this_morning_window():
    start, end = _span("what did I do this morning")
    assert (start.hour, end.hour) == (5, 12)
    assert start.date() == NOW.date()


def test_yesterday_afternoon():
    start, end = _span("yesterday afternoon")
    assert start.date() == datetime(2026, 6, 28).date()
    assert (start.hour, end.hour) == (12, 17)


def test_last_n_days():
    start, end = _span("last 3 days")
    assert abs((end - start).days - 3) <= 1


def test_last_hours():
    start, end = _span("last 2 hours")
    assert round((end - start).total_seconds() / 3600) == 2


def test_iso_date():
    start, end = _span("2026-06-15")
    assert start.date() == datetime(2026, 6, 15).date()
    assert end.date() == datetime(2026, 6, 15).date()


def test_iso_range():
    start, end = _span("2026-06-01 to 2026-06-07")
    assert start.date() == datetime(2026, 6, 1).date()
    assert end.date() == datetime(2026, 6, 7).date()


def test_last_week():
    start, end = _span("last week")
    # Anchor is Monday; last week is the prior Mon-Sun (2026-06-22 .. 2026-06-28).
    assert start.date() == datetime(2026, 6, 22).date()
    assert end.date() == datetime(2026, 6, 28).date()


def test_unrecognized_returns_none():
    assert parse_timeframe("tell me about purple sneakers", now=NOW) is None
