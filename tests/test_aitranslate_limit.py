"""Tests for the /api/aitranslate per-IP rate limiter (dropit._ait_allowed).

Translation is the heaviest endpoint (model inference, plus a ~110 MB
pack download on first use), so each client IP gets 10 translations per
sliding 60-second window; the 11th is refused and the server answers
{"ok": False, "message": "rate_limited"} with HTTP 429.
"""
from __future__ import annotations

import time

import pytest

import dropit


@pytest.fixture(autouse=True)
def _clean():
    dropit._ait_hits.clear()
    yield
    dropit._ait_hits.clear()


def test_ten_allowed_eleventh_denied():
    ip = "192.168.1.50"
    assert all(dropit._ait_allowed(ip) for _ in range(10))
    assert not dropit._ait_allowed(ip)


def test_window_slides(monkeypatch):
    ip = "192.168.1.51"
    now = [1000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    for _ in range(10):
        assert dropit._ait_allowed(ip)
    assert not dropit._ait_allowed(ip)
    now[0] += 61  # window slides past the old hits
    assert dropit._ait_allowed(ip)


def test_ips_are_independent():
    assert all(dropit._ait_allowed("10.0.0.1") for _ in range(10))
    assert not dropit._ait_allowed("10.0.0.1")
    assert dropit._ait_allowed("10.0.0.2")


def test_loopback_never_limited():
    assert all(dropit._ait_allowed("127.0.0.1") for _ in range(50))
