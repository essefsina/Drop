"""Tests for translation-pack download progress reporting (dropit_mt).

No network: urlopen is faked. Verifies the (done, total) callback contract
of _download and that download_progress() only reports in-flight downloads.
"""
import io
import os
import tempfile
import urllib.request

import dropit_mt as mt


class _FakeResp:
    def __init__(self, n, length=True):
        self._buf = io.BytesIO(b"x" * n)
        self.headers = {"Content-Length": str(n)} if length else {}

    def read(self, n=-1):
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen(n, length=True):
    return lambda req, timeout=None: _FakeResp(n, length)


def _patch(monkeypatch, n, length=True):
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen(n, length))


def test_download_reports_progress(monkeypatch, tmp_path):
    _patch(monkeypatch, 1024 * 1024)
    seen = []
    mt._download("http://example/x", str(tmp_path / "f.bin"),
                 progress=lambda d, t: seen.append((d, t)))
    assert seen[0] == (0, 1024 * 1024)
    assert seen[-1] == (1024 * 1024, 1024 * 1024)
    dones = [d for d, _ in seen]
    assert dones == sorted(dones), "progress must be monotonic"


def test_download_without_content_length(monkeypatch, tmp_path):
    _patch(monkeypatch, 100, length=False)
    seen = []
    mt._download("http://example/x", str(tmp_path / "f.bin"),
                 progress=lambda d, t: seen.append((d, t)))
    assert seen[0] == (0, None)
    assert seen[-1] == (100, None)


def test_download_progress_idle():
    assert mt.download_progress() == {}


def test_ensure_pair_clears_progress(monkeypatch):
    _patch(monkeypatch, 512)
    data_dir = tempfile.mkdtemp()
    d = mt._ensure_pair("xx-progress-test", data_dir)
    assert mt.download_progress() == {}, \
        "stale progress must not linger after a download finishes"
    assert sorted(os.listdir(d)) == [
        "config.json", "decoder.onnx", "encoder.onnx",
        "generation_config.json", "tokenizer.json",
    ]


def test_progress_visible_mid_download(monkeypatch):
    """A slow pair download must be visible via download_progress() mid-flight."""
    import threading
    import time

    class _Slow(_FakeResp):
        def read(self, n=-1):
            time.sleep(0.02)
            return super().read(n)

    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout=None: _Slow(1024 * 256))
    data_dir = tempfile.mkdtemp()

    t = threading.Thread(
        target=mt._ensure_pair, args=("xx-slow-test", data_dir))
    t.start()
    try:
        deadline = time.time() + 10
        seen = {}
        while time.time() < deadline:
            seen = mt.download_progress()
            if seen:
                break
            time.sleep(0.05)
        assert seen, "no in-flight download was ever visible"
        pair, st = next(iter(seen.items()))
        assert pair == "xx-slow-test"
        assert st["done"] >= 0 and st["total"] == 1024 * 256
        assert st["file"].endswith(".onnx")
    finally:
        t.join(timeout=30)
    assert mt.download_progress() == {}
