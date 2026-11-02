"""Unit tests for dropit_ai._save_index / _load_index — the on-disk
embedding index (ai_index.pkl).

The loader must never raise and never serve a stale index: a missing
file, a corrupt file, or an index written by an older version all come
back as a fresh empty index, so the files simply get re-embedded.
"""
import os

from dropit_ai import _index_path, _index_version, _load_index, _save_index


def _empty():
    return {"v": _index_version(), "files": {}, "order": []}


def test_round_trip_preserves_files_and_order(tmp_path):
    data_dir = str(tmp_path)
    index = {
        "v": _index_version(),
        "files": {
            "a.txt": {"has_text": True},
            "b.jpg": {"has_ocr": False, "has_text": False},
        },
        "order": ["a.txt", "b.jpg"],
    }
    _save_index(data_dir, index)
    assert os.path.isfile(_index_path(data_dir))
    assert _load_index(data_dir) == index


def test_missing_file_returns_empty_index(tmp_path):
    assert _load_index(str(tmp_path)) == _empty()


def test_missing_data_dir_returns_empty_index(tmp_path):
    assert _load_index(str(tmp_path / "no-such-dir")) == _empty()


def test_corrupt_file_returns_empty_index(tmp_path):
    data_dir = str(tmp_path)
    with open(_index_path(data_dir), "wb") as f:
        f.write(b"this is not a pickle")
    assert _load_index(data_dir) == _empty()


def test_stale_version_is_discarded(tmp_path):
    data_dir = str(tmp_path)
    stale = {
        "v": _index_version() + 1000,
        "files": {"old.txt": {"has_text": True}},
        "order": ["old.txt"],
    }
    _save_index(data_dir, stale)
    assert _load_index(data_dir) == _empty()


def test_save_creates_data_dir(tmp_path):
    data_dir = str(tmp_path / "nested" / "data")
    _save_index(data_dir, _empty())
    assert _load_index(data_dir) == _empty()
