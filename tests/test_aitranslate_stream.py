"""Tests for POST /api/aitranslate/stream (NDJSON per-chunk translation).

The real dropit HTTP server runs on an ephemeral port with the MT backend
stubbed out — no model download, no inference. Covers the endpoint's
NDJSON framing plus dropit_mt.iter_chunk_translations' pre-flight and
chunk protocol.
"""
import json
import os
import sys
import threading
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import dropit
import dropit_mt


def _fake_chunks():
    yield {"ok": True, "index": 0, "total": 2, "src": "es", "text": "hola "}
    yield {"ok": True, "index": 1, "total": 2, "src": "es", "text": "mundo"}
    yield {"ok": True, "done": True, "src": "es", "text": "hola mundo"}


@pytest.fixture()
def live_server(tmp_path, monkeypatch):
    monkeypatch.setattr(
        dropit_mt, "iter_chunk_translations",
        lambda text, data_dir=None: _fake_chunks())
    monkeypatch.setattr(dropit, "_data_dir", lambda: str(tmp_path))
    srv = dropit.make_server(0, str(tmp_path))
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % port
    srv.shutdown()
    srv.server_close()


def _post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        return urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        return e


def test_stream_yields_ndjson_chunks(live_server):
    resp = _post(live_server + "/api/aitranslate/stream", {"text": "x" * 2500})
    assert resp.status == 200
    assert resp.headers.get_content_type() == "application/x-ndjson"
    lines = [json.loads(ln) for ln in
             resp.read().decode("utf-8").splitlines() if ln.strip()]
    chunks = [m for m in lines if not m.get("done")]
    assert [m["index"] for m in chunks] == [0, 1]
    assert all(m["total"] == 2 and m["src"] == "es" for m in chunks)
    done = lines[-1]
    assert done["done"] is True
    assert done["text"] == "hola mundo"


def test_stream_rejects_too_long(live_server):
    resp = _post(live_server + "/api/aitranslate/stream",
                 {"text": "x" * 20_001})
    assert resp.status == 400
    assert json.loads(resp.read().decode())["message"] == "too_long"


def test_stream_rejects_empty(live_server):
    resp = _post(live_server + "/api/aitranslate/stream", {"text": "   "})
    assert resp.status == 400
    assert json.loads(resp.read().decode())["message"] == "empty"


# --- iter_chunk_translations unit tests (no model needed) ------------------


def test_iter_empty_text():
    assert list(dropit_mt.iter_chunk_translations("   ")) == [
        {"ok": False, "message": "empty"}]


def test_iter_already_english_short_circuits():
    text = "Hello world, this is a plain English sentence for testing."
    assert list(dropit_mt.iter_chunk_translations(text)) == [
        {"ok": True, "done": True, "src": "en",
         "message": "already_english", "text": text}]


def test_iter_no_pair_when_download_fails(monkeypatch):
    def _boom(pair, data_dir):
        raise RuntimeError("no network")
    monkeypatch.setattr(dropit_mt, "_get_pair_mt", _boom)
    text = "Bonjour le monde, ceci est une phrase en francais pour tester."
    assert list(dropit_mt.iter_chunk_translations(text)) == [
        {"ok": False, "message": "no_pair"}]


class _FakeMT:
    def _split(self, text):
        return ["chunk one", "chunk two"]

    def _translate_chunk(self, ch):
        return "TRANS:" + ch


class _FlakyMT(_FakeMT):
    def _translate_chunk(self, ch):
        if ch == "chunk two":
            raise RuntimeError("inference blew up")
        return "TRANS:" + ch


def test_iter_yields_chunks_then_done(monkeypatch):
    monkeypatch.setattr(dropit_mt, "_get_pair_mt",
                        lambda pair, data_dir: _FakeMT())
    out = list(dropit_mt.iter_chunk_translations("du texte francais " * 60))
    chunks = [m for m in out if not m.get("done")]
    assert [m["index"] for m in chunks] == [0, 1]
    assert all(m["total"] == 2 and m["ok"] for m in chunks)
    assert out[-1] == {"ok": True, "done": True, "src": "fr",
                       "text": "TRANS:chunk one TRANS:chunk two"}


def test_iter_mid_stream_failure_yields_error_line(monkeypatch):
    monkeypatch.setattr(dropit_mt, "_get_pair_mt",
                        lambda pair, data_dir: _FlakyMT())
    out = list(dropit_mt.iter_chunk_translations("du texte francais " * 60))
    assert out[0]["ok"] is True and out[0]["index"] == 0
    assert out[1] == {"ok": False, "message": "error",
                      "index": 1, "total": 2}


def test_translate_still_joins_chunks():
    # The _translate_chunk refactor must not change translate()'s output:
    # run the real translate() with stubbed internals.
    mt = dropit_mt._PairMT.__new__(dropit_mt._PairMT)
    mt._split = lambda text: ["chunk one", "chunk two"]
    mt._translate_chunk = lambda ch: "TRANS:" + ch
    assert mt.translate("n'importe quoi") == "TRANS:chunk one TRANS:chunk two"
