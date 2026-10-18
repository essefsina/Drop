"""Tests for dropit_mt._download resume behaviour (HTTP Range).

An interrupted ~110 MB translation-pack download leaves a partial file
behind. _download must continue that file with a Range request instead
of restarting from zero - this is simulated against a local HTTP server.
"""
from __future__ import annotations

import functools
import http.server
import threading

import pytest

import dropit_mt

PAYLOAD = bytes(range(256)) * 4096  # 1 MiB of deterministic bytes


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # keep pytest output clean
        pass


class _NoRangeHandler(_QuietHandler):
    """Server that ignores Range requests (always answers 200, full body)."""

    def send_head(self):
        self.headers["Range"] = ""
        return super().send_head()


def _serve(handler_cls, directory):
    handler = functools.partial(handler_cls, directory=directory)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


@pytest.fixture()
def file_url(tmp_path):
    (tmp_path / "pack.bin").write_bytes(PAYLOAD)
    httpd = _serve(_QuietHandler, str(tmp_path))
    yield f"http://127.0.0.1:{httpd.server_port}/pack.bin"
    httpd.shutdown()


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def test_fresh_download_has_no_part_file_left(file_url, tmp_path):
    dest = str(tmp_path / "out.bin")
    calls = []
    dropit_mt._download(file_url, dest, progress=lambda d, t: calls.append((d, t)))
    assert _read(dest) == PAYLOAD
    assert calls[-1][0] == len(PAYLOAD)
    assert not (tmp_path / "out.bin.part").exists()


def test_resume_continues_from_partial_file(file_url, tmp_path):
    dest = str(tmp_path / "out.bin")
    # Simulate an interrupted download: the first 40% is already on disk.
    cut = len(PAYLOAD) * 2 // 5
    with open(dest + ".part", "wb") as f:
        f.write(PAYLOAD[:cut])
    totals = []
    dropit_mt._download(file_url, dest, progress=lambda d, t: totals.append(t))
    assert _read(dest) == PAYLOAD
    # The UI is told the full file size as the total, not just the remainder,
    # so the progress bar resumes at 40% instead of restarting at 0%.
    assert totals and all(t == len(PAYLOAD) for t in totals)
    assert not (tmp_path / "out.bin.part").exists()


def test_restart_when_server_ignores_range(tmp_path):
    (tmp_path / "pack.bin").write_bytes(PAYLOAD)
    httpd = _serve(_NoRangeHandler, str(tmp_path))
    try:
        url = f"http://127.0.0.1:{httpd.server_port}/pack.bin"
        dest = str(tmp_path / "out.bin")
        # A stale partial file from a Range-capable mirror - this server
        # answers 200 to the Range request, so the download restarts.
        with open(dest + ".part", "wb") as f:
            f.write(b"garbage-bytes-not-the-pack")
        dropit_mt._download(url, dest)
        assert _read(dest) == PAYLOAD
    finally:
        httpd.shutdown()


def test_already_complete_part_file_becomes_dest(file_url, tmp_path):
    # Server answers 416 (Range Not Satisfiable) when the partial file is
    # already the whole pack - the download is then just complete.
    dest = str(tmp_path / "out.bin")
    with open(dest + ".part", "wb") as f:
        f.write(PAYLOAD)
    dropit_mt._download(file_url, dest)
    assert _read(dest) == PAYLOAD
