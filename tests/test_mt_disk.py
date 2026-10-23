"""Tests for the translation-pack disk-space guard (dropit_mt).

Before downloading a ~110 MB language pair, _download logs the pack size
and checks that the destination disk can fit it, raising
InsufficientDiskSpace otherwise. translate_to_english surfaces that as
{"ok": False, "message": "no_space"} so the UI can show a clear message
instead of a mysterious mid-download failure.
"""
from __future__ import annotations

import os
import urllib.request

import pytest

import dropit_mt


class _FakeUsage:
    def __init__(self, free):
        self.free = free


def test_check_space_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(dropit_mt.shutil, "disk_usage",
                        lambda p: _FakeUsage(10 * 1024 ** 3))
    dropit_mt._check_space(str(tmp_path / "x.onnx"), 110 * 1024 ** 2)  # no raise


def test_check_space_short(tmp_path, monkeypatch):
    monkeypatch.setattr(dropit_mt.shutil, "disk_usage",
                        lambda p: _FakeUsage(1024))
    with pytest.raises(dropit_mt.InsufficientDiskSpace):
        dropit_mt._check_space(str(tmp_path / "x.onnx"), 110 * 1024 ** 2)


def test_check_space_unknown_fs_skips(tmp_path, monkeypatch):
    def boom(p):
        raise OSError("cannot statfs")
    monkeypatch.setattr(dropit_mt.shutil, "disk_usage", boom)
    # Can't determine free space - let the download try anyway.
    dropit_mt._check_space(str(tmp_path / "x.onnx"), 10 ** 12)  # no raise


class _FakeResp:
    status = 200

    def __init__(self, payload):
        self._payload = payload
        self.headers = {"Content-Length": str(len(payload))}

    def read(self, n=-1):
        chunk, self._payload = self._payload[:n], self._payload[n:]
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_download_refuses_before_writing(tmp_path, monkeypatch):
    payload = b"x" * 4096
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResp(payload))
    monkeypatch.setattr(dropit_mt.shutil, "disk_usage",
                        lambda p: _FakeUsage(100))
    dest = str(tmp_path / "pair.onnx")
    with pytest.raises(dropit_mt.InsufficientDiskSpace):
        dropit_mt._download("http://example.com/pair.onnx", dest)
    # Nothing was fetched and no partial file was left behind.
    assert not os.path.exists(dest)
    assert not os.path.exists(dest + ".part")


def test_download_proceeds_with_space(tmp_path, monkeypatch, capsys):
    payload = b"y" * 4096
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResp(payload))
    monkeypatch.setattr(dropit_mt.shutil, "disk_usage",
                        lambda p: _FakeUsage(10 * 1024 ** 3))
    dest = str(tmp_path / "pair.onnx")
    dropit_mt._download("http://example.com/pair.onnx", dest)
    assert os.path.getsize(dest) == len(payload)
    assert "downloading pair.onnx" in capsys.readouterr().out


def test_translate_maps_no_space(monkeypatch):
    def boom(pair, data_dir):
        raise dropit_mt.InsufficientDiskSpace("disk full")

    monkeypatch.setattr(dropit_mt, "_get_pair_mt", boom)
    r = dropit_mt.translate_to_english(
        "Bonjour le monde, comment allez-vous aujourd'hui ?")
    assert r == {"ok": False, "message": "no_space"}
