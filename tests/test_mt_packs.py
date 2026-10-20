"""Tests for translation-pack maintenance (dropit_mt.pack_info/clear_packs).

Cached packs live under <data_dir>/mt_models/<pair>/. pack_info reports
what is cached and how big it is; clear_packs deletes the packs and drops
the loaded sessions so the next translation re-downloads on demand.
"""
from __future__ import annotations

import os

import dropit_mt


def _make_pack(data_dir, pair, sizes):
    d = os.path.join(data_dir, "mt_models", pair)
    os.makedirs(d)
    for name, size in sizes.items():
        with open(os.path.join(d, name), "wb") as f:
            f.write(b"z" * size)


def test_pack_info_lists_pairs_with_bytes(tmp_path):
    _make_pack(str(tmp_path), "es",
               {"encoder.onnx": 1000, "decoder.onnx": 2000})
    _make_pack(str(tmp_path), "fr", {"encoder.onnx": 500})
    assert dropit_mt.pack_info(str(tmp_path)) == [
        {"pair": "es", "bytes": 3000},
        {"pair": "fr", "bytes": 500},
    ]


def test_pack_info_empty(tmp_path):
    assert dropit_mt.pack_info(str(tmp_path)) == []
    os.makedirs(str(tmp_path / "mt_models"))
    assert dropit_mt.pack_info(str(tmp_path)) == []


def test_clear_packs_removes_and_reports(tmp_path):
    _make_pack(str(tmp_path), "es", {"encoder.onnx": 1000})
    _make_pack(str(tmp_path), "fr", {"decoder.onnx": 2000})
    dropit_mt._sessions["es"] = object()  # pretend a session is loaded
    try:
        r = dropit_mt.clear_packs(str(tmp_path))
    finally:
        dropit_mt._sessions.clear()
    assert r == {"pairs": ["es", "fr"], "bytes": 3000}
    assert not os.path.exists(str(tmp_path / "mt_models"))


def test_clear_packs_empty_dir(tmp_path):
    assert dropit_mt.clear_packs(str(tmp_path)) == {"pairs": [], "bytes": 0}
