"""Unit tests for dropit_mt._pair_dir — where one translation pair's
ONNX files live on disk.

The pair directory is created on demand under <data_dir>/mt_models/,
so the downloader never has to worry about missing parents, and
calling it twice for the same pair resolves to the same directory.
"""
import os

import dropit_mt as mt


def test_creates_pair_directory_under_data_dir(tmp_path):
    d = mt._pair_dir(str(tmp_path), "fr")
    assert d == os.path.join(str(tmp_path), "mt_models", "fr")
    assert os.path.isdir(d)


def test_idempotent_on_repeat_calls(tmp_path):
    first = mt._pair_dir(str(tmp_path), "es")
    second = mt._pair_dir(str(tmp_path), "es")
    assert first == second
    assert os.path.isdir(first)


def test_different_pairs_get_different_directories(tmp_path):
    fr = mt._pair_dir(str(tmp_path), "fr")
    de = mt._pair_dir(str(tmp_path), "de")
    assert fr != de
    assert os.path.isdir(fr)
    assert os.path.isdir(de)


def test_none_data_dir_resolves_under_current_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = mt._pair_dir(None, "mul")
    assert d == os.path.join(".", "mt_models", "mul")
    assert os.path.isdir(tmp_path / "mt_models" / "mul")


def test_existing_directory_is_left_alone(tmp_path):
    d = tmp_path / "mt_models" / "ja"
    d.mkdir(parents=True)
    marker = d / "keep.txt"
    marker.write_text("do not touch", encoding="utf-8")
    assert mt._pair_dir(str(tmp_path), "ja") == str(d)
    assert marker.read_text(encoding="utf-8") == "do not touch"
