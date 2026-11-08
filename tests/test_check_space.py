"""Unit tests for dropit_mt._mb and _check_space.

_check_space guards translation-pack downloads: it raises
InsufficientDiskSpace before the first byte is written when the
destination disk can't fit the pack, and stays silent when free
space can't be determined (the download itself surfaces real
filesystem errors). No network or real downloads involved.
"""
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import dropit_mt  # noqa: E402
from dropit_mt import InsufficientDiskSpace, _check_space, _mb  # noqa: E402

ONE_MB = 1048576


def _fake_usage(monkeypatch, free_bytes):
    usage = SimpleNamespace(total=10 * ONE_MB, used=0, free=free_bytes)
    monkeypatch.setattr(dropit_mt.shutil, "disk_usage",
                        lambda path: usage)


def test_mb_formats_whole_megabytes():
    assert _mb(0) == "0 MB"
    assert _mb(ONE_MB) == "1 MB"
    assert _mb(10 * ONE_MB) == "10 MB"


def test_mb_truncates_fractional_megabytes():
    # %d truncates: 1.5 MB reports as "1 MB", never "1.5 MB".
    assert _mb(int(1.5 * ONE_MB)) == "1 MB"


def test_check_space_passes_when_disk_fits(tmp_path, monkeypatch):
    _fake_usage(monkeypatch, free_bytes=500 * ONE_MB)
    _check_space(str(tmp_path / "pack.bin"), 100 * ONE_MB)


def test_check_space_passes_on_exact_fit(tmp_path, monkeypatch):
    _fake_usage(monkeypatch, free_bytes=100 * ONE_MB)
    _check_space(str(tmp_path / "pack.bin"), 100 * ONE_MB)


def test_check_space_raises_when_disk_too_small(tmp_path, monkeypatch):
    _fake_usage(monkeypatch, free_bytes=50 * ONE_MB)
    with pytest.raises(InsufficientDiskSpace) as excinfo:
        _check_space(str(tmp_path / "pack.bin"), 100 * ONE_MB)
    assert "100 MB" in str(excinfo.value)
    assert "50 MB" in str(excinfo.value)


def test_insufficient_disk_space_is_an_os_error(tmp_path, monkeypatch):
    # Callers catching OSError (e.g. the download path) must see it too.
    _fake_usage(monkeypatch, free_bytes=0)
    with pytest.raises(OSError):
        _check_space(str(tmp_path / "pack.bin"), ONE_MB)


def test_check_space_silent_when_free_space_unknown(tmp_path, monkeypatch):
    def _boom(path):
        raise OSError("cannot stat filesystem")

    monkeypatch.setattr(dropit_mt.shutil, "disk_usage", _boom)
    _check_space(str(tmp_path / "pack.bin"), 100 * ONE_MB)
