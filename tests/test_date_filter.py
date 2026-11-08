"""Tests for dropit_ai._parse_date_filter — the date half of AI search.

Typing "oct 2" must list every file from that day, and a complex query
like "email screenshot from last week" must split into a date range plus
the keyword. These tests pin that parsing without needing any model or
index on disk.
"""

from __future__ import annotations

import calendar
import time

from dropit_ai import _parse_date_filter

DAY = 86400


def _ymd(ts: float):
    lt = time.localtime(ts)
    return lt.tm_year, lt.tm_mon, lt.tm_mday


def test_no_date_leaves_query_and_range_untouched():
    q, since, until = _parse_date_filter("email screenshot")
    assert q == "email screenshot"
    assert since is None
    assert until is None


def test_absolute_month_day_is_a_single_day():
    q, since, until = _parse_date_filter("oct 2")
    assert q == ""
    assert since is not None and until is not None
    assert until - since == DAY
    _, mon, day = _ymd(since)
    assert (mon, day) == (10, 2)


def test_full_month_name_and_trailing_keyword():
    q, since, until = _parse_date_filter("october 5 report")
    assert q == "report"
    assert until - since == DAY
    _, mon, day = _ymd(since)
    assert (mon, day) == (10, 5)


def test_numeric_month_day():
    q, since, until = _parse_date_filter("10/2 notes")
    assert q == "notes"
    assert until - since == DAY
    _, mon, day = _ymd(since)
    assert (mon, day) == (10, 2)


def test_future_date_rolls_back_a_year():
    # Dec 25 is still ahead when this suite runs in autumn, so the parser
    # must fall back to last year's Dec 25 rather than a future range.
    # Assert month/day only: the year follows whichever side of Dec 25
    # "now" falls on, and that is the parser's documented behaviour.
    q, since, until = _parse_date_filter("dec 25")
    assert q == ""
    assert until - since == DAY
    _, mon, day = _ymd(since)
    assert (mon, day) == (12, 25)
    assert since <= time.time()


def test_last_week_splits_off_keyword_and_seven_day_range():
    q, since, until = _parse_date_filter("email screenshot from last week")
    assert "email" in q and "screenshot" in q
    assert "last week" not in q
    assert until - since == 7 * DAY
    assert since <= time.time() <= until + 60


def test_yesterday_is_a_one_day_range_ending_now():
    q, since, until = _parse_date_filter("yesterday memo")
    assert q == "memo"
    assert until - since == DAY


def test_year_only_spans_that_calendar_year():
    q, since, until = _parse_date_filter("report 2024")
    assert q == "report"
    assert since == calendar.timegm((2024, 1, 1, 0, 0, 0))
    assert until == calendar.timegm((2025, 1, 1, 0, 0, 0))
