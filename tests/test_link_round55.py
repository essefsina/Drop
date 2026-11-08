"""v2.8.40 round (Essef Nov 7, ~5:45-6:17 PM) -- WEB/DESKTOP track
only, local test build only. SEVEN items (the 6:17 PM voice-call
confirmation list -- all already in the brief):

  (1) LAG: everything laggy, thumbnails refreshing constantly,
      web lagging, search taking forever. Root causes, measured
      against 2.8.38/2.8.39: (a) loadFiles rebuilt #files on
      every 5s poll while ANY AI scan was pending (the early
      return was defeated by `!pendingAi.size`, and every
      checkPendingAi resolution did lastFilesSig=null +
      loadFiles() -- a rebuild per file), so <video> thumbs
      re-created and flashed black; (b) /api/files conflated
      "has text" with "not yet scanned", so every text-less file
      re-entered pendingAi on every restart / address switch;
      (c) scan state was keyed by file NAME only, so switching
      addresses re-scanned (or, worse, never scanned the new
      address's same-name files -- 2.8.39 B-side same.jpg never
      got a sparkle); (d) search_files called build_index
      first, and build_index held _index_lock across its whole
      OCR+embedding pass -- searches blocked up to the 75s
      timeout. Fixes: per-address scan keys (aiKey/aiPrefix),
      in-place paintAiCell (no rebuild per verdict), ai_known
      from ai_state (scanned files never re-enter pending),
      search skips a running build (non-blocking lock take)
      and searches the current index, atomic _save_index.
  (2) DISCONNECT BUTTON SIZE (MB + web PC): same size as the
      Change Folder button on the D menu (216x40 PC web;
      40px tall on MB, width the row's half-share).
  (3) STARRED LIGHT MODE + APK TOGGLE: ON is the APK chip --
      inverted solid dark #231303, 2px gold stroke, "✓ Starred",
      filled YELLOW star -- in BOTH themes (the first 2.8.40
      attempt lost to the light OFF rule on specificity).
      Starred notes keep a filled yellow star both themes.
  (4) SAVE PASSWORD CHECKBOX: removed from the MB Set Up Your
      Addresses card ONLY (the Nov 7 5:50 PM correction -- the
      login-page checkbox STAYS, as do APK and PC web).
  (5) MB SAVED OPEN: system open-with chooser
      (navigator.share({files}) -- Android ACTION_VIEW style),
      never another download. PC WEB SAVED OPEN: POST
      /api/openlocal -- the server opens the file from PC
      storage in the default app (host-only). A download is
      never presented as an open.
  (6) = (5) PC web half (listed separately in the 6:17 PM
      confirmation).
  (7) SPARKLE: re-loading on every address switch and every
      app restart, glitching the app while loading, and
      glitching even with all sparkles loaded -- fixed by the
      per-address scan cache + ai_known (see (1)); the
      switch probe (lagtest/sw240v.json vs sw39v.json) is the
      live proof: 2.8.39 18 rebuilds + B never scanned, 2.8.40
      7 rebuilds (1 per folder render, 0 idle) + correct
      per-address verdicts + 0 re-scans on revisit.
"""
import ast
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
import dropit_ai  # noqa: E402
from test_link_round2 import server  # noqa: F401,E402
from test_link_round2 import Client  # noqa: E402
from test_link_round2 import _raw  # noqa: E402
from test_link_round34 import _Fwd  # noqa: F401,E402
from test_link_round46 import _pc_page  # noqa: E402
from test_link_round54 import _guest_page, _wait_authed  # noqa: E402

PAGE = D.PAGE
SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py"),
           encoding="utf-8").read()
AI_SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit_ai.py"),
              encoding="utf-8").read()

PROOF = "/home/hatch/workspace/dropit-proof-round55"
os.makedirs(PROOF, exist_ok=True)


def test_version_is_2_8_40():
    assert D.VERSION == "2.8.40", D.VERSION


def test_page_valid():
    """Interpreted PAGE: both scripts node --check clean, zero lone
    surrogates, UTF-8 clean."""
    tree = ast.parse(SRC)
    page = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "PAGE"
                for t in node.targets):
            page = ast.literal_eval(node.value)
    assert page is not None
    assert not [c for c in page if 0xD800 <= ord(c) <= 0xDFFF]
    page.encode("utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
    assert scripts, "no <script> in PAGE"
    for i, s in enumerate(scripts):
        p = "/tmp/r55_script%d.js" % i
        with open(p, "w", encoding="utf-8") as f:
            f.write(s)
        r = subprocess.run(["node", "--check", p],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[:500]


# --- (1)/(7) lag: /api/files ai_known -------------------------------

def test_lag_files_ai_known(server):
    """(1) /api/files reports ai_known: a text file is KNOWN
    (has text, never re-scanned on restart/switch); a text-less
    image with no scan record is UNKNOWN (client scans it once,
    bounded) -- the old flag conflated the two, so every
    text-less file re-entered pendingAi on every load."""
    client, base, proc, port, home = server
    (base / "hello.txt").write_text("hello world\n")
    # 1x1 black PNG: no text, no index record yet.
    import base64
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    (base / "pic.jpg").write_bytes(png)
    s, files = client.j("GET", "/api/files")
    assert s == 200, files
    by_name = {f["name"]: f for f in files}
    txt = by_name["hello.txt"]
    assert txt["ai"] is True and txt["ai_known"] is True, txt
    img = by_name["pic.jpg"]
    assert "ai_known" in img, img
    assert img["ai"] is False and img["ai_known"] is False, img


def test_lag_search_skips_running_build(tmp_path):
    """(1) A search must not block behind a running index build:
    hold _index_lock (a startup/upload build) and search -- it
    answers from the current index instead of timing out.
    2.8.39 blocked the full 10s search_files_timed timeout."""
    if not dropit_ai.model_ready():
        pytest.skip("no MiniLM model files in repo")
    base = tmp_path / "base"
    data = tmp_path / "data"
    base.mkdir()
    data.mkdir()
    (base / "hello.txt").write_text("hello world motorbikes\n")
    # No warm build_index here: the point is the lock behaviour,
    # not the ranking. With the build lock held by another thread,
    # 2.8.39's search_files blocks inside build_index until the
    # 10s search_files_timed timeout; 2.8.40 skips the build and
    # answers (needs_setup here -- this env has no tokenizers --
    # but fast, from the current index) instead of timing out.
    held = threading.Event()

    def holder():
        with dropit_ai._index_lock:
            held.set()
            time.sleep(20)

    th = threading.Thread(target=holder, daemon=True)
    th.start()
    assert held.wait(5)
    t0 = time.time()
    res = dropit_ai.search_files_timed(str(base), str(data),
                                       "motorbike", timeout=10)
    dt = time.time() - t0
    assert dt < 5, dt
    assert res.get("message") != "timeout", res
    th.join(timeout=25)


def test_lag_no_per_file_rebuild_shape():
    """(1)/(7) The per-file rebuild trigger is gone from the
    client: no `lastFilesSig=null; loadFiles()` after a scan
    verdict, verdicts patch one row in place, and scan state is
    keyed per address (aiKey/aiPrefix/pendingHere)."""
    assert "lastFilesSig=null; loadFiles()" not in SRC
    assert "paintAiCell(name, true)" in SRC
    assert "function aiPrefix()" in SRC
    assert "function aiKey(name)" in SRC
    assert "function pendingHere()" in SRC
    assert "if(sig === lastFilesSig && !newOnes && !pendingAi.size)" not in SRC
    assert "if(sig===lastFilesSig &&!newOnes &&!pendingAi.size)" not in SRC


def test_lag_index_lock_and_atomic_save():
    """(1) Search takes the build lock non-blocking (RLock, so a
    same-thread re-take inside build_index is safe) and the
    index save is atomic (os.replace -- no torn pickle reads)."""
    assert "threading.RLock()" in AI_SRC
    assert "os.replace(" in AI_SRC
    assert "acquire(blocking=False)" in AI_SRC


# --- (2) Disconnect button size -------------------------------------

def _host_page(pw, port, width, height):
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    ctx = browser.new_context(viewport={"width": width, "height": height})
    pg = ctx.new_page()
    pg.goto("http://127.0.0.1:%d/" % port)
    pg.wait_for_function(
        "() => typeof AUTH !== 'undefined' && AUTH.host", timeout=10000)
    pg.wait_for_timeout(900)
    return browser, pg


def _rect(pg, sel):
    return pg.evaluate("""(s) => { const el = document.querySelector(s);
      if(!el) return null; const r = el.getBoundingClientRect();
      return {x: Math.round(r.x * 10) / 10, w: Math.round(r.width * 10) / 10,
              h: Math.round(r.height * 10) / 10}; }""", sel)


def test_item1_disconnect_size_pcweb(server):
    """(2) PC web Disconnect is the SAME SIZE as the D menu
    Change Folder button: 216x40, same x (card inset)."""
    client, base, proc, port, home = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, pg = _host_page(pw, port, 1280, 800)
        try:
            pg.click("#menubtn")
            pg.wait_for_timeout(500)
            ch = _rect(pg, "#sbchange")
            dc = _rect(pg, "#sbdisconnect")
            assert ch and dc, (ch, dc)
            assert (dc["w"], dc["h"]) == (ch["w"], ch["h"]) == (216, 40), (ch, dc)
            assert dc["x"] == ch["x"], (ch, dc)
            print("ITEM1 PCweb: change=%s disconnect=%s" % (ch, dc))
        finally:
            browser.close()


def test_item1_disconnect_size_mb(server):
    """(2) MB Disconnect is 40px tall like the D Change Folder
    button, and the Connect/Disconnect pair stays even."""
    client, base, proc, port, home = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, pg = _host_page(pw, port, 390, 844)
        try:
            pg.evaluate("() => setTab('send')")
            pg.wait_for_timeout(600)
            co = _rect(pg, "#mpcconnect")
            dc = _rect(pg, "#mpcdisconnect")
            assert co and dc, (co, dc)
            assert dc["h"] == 40, dc
            assert co["h"] == dc["h"] == 40, (co, dc)
            assert co["w"] == dc["w"], (co, dc)
            print("ITEM1 MB: connect=%s disconnect=%s" % (co, dc))
        finally:
            browser.close()


# --- (3) Starred APK toggle -----------------------------------------

def test_item2_starred_apk_toggle(server):
    """(3) Starred toggle = the APK chip in BOTH themes: ON is
    solid dark #231303, 2px gold stroke, WHITE "✓ Starred"
    label, filled YELLOW star. Starred notes keep a filled
    yellow star in both themes.
    v2.8.41 fix-up: ON label white -- the 2.8.40 web spec used
    a gold ON label, but the APK track verified Nov 7 (APK
    2.6.115) that the APK uses white text in both states, and
    that is authoritative for D/web too."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink", {"name": "starlink"})
    assert s == 200 and j["ok"], j
    ids = []
    for txt in ("starred note", "plain note"):
        s, j = client.j("POST", "/api/snippet", {"text": txt})
        assert s == 200 and j["ok"], j
        ids.append(j["id"])
    s, j = client.j("POST", "/api/notes/star",
                    {"id": ids[0], "starred": True})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        for light in (False, True):
            browser, ctx, pg, fwd = _guest_page(pw, port, 390, 844,
                                                light=light)
            try:
                _wait_authed(pg)
                pg.evaluate("() => setTab('notes')")
                pg.wait_for_timeout(600)
                pg.wait_for_selector("[data-star]", timeout=5000)
                off = pg.evaluate("""() => { const b = document.querySelector('#starfilter');
                  const cs = getComputedStyle(b); const sv = b.querySelector('svg');
                  return {bg: cs.backgroundColor, color: cs.color,
                    bw: cs.borderTopWidth, bc: cs.borderTopColor,
                    svgFill: getComputedStyle(sv).fill, text: b.textContent.trim(),
                    pressed: b.getAttribute('aria-pressed')}; }""")
                assert off["pressed"] == "false", off
                pg.click("#starfilter")
                pg.wait_for_timeout(500)
                on = pg.evaluate("""() => { const b = document.querySelector('#starfilter');
                  const cs = getComputedStyle(b); const sv = b.querySelector('svg');
                  return {bg: cs.backgroundColor, color: cs.color,
                    bw: cs.borderTopWidth, bc: cs.borderTopColor,
                    svgFill: getComputedStyle(sv).fill, text: b.textContent.trim(),
                    pressed: b.getAttribute('aria-pressed')}; }""")
                assert on["pressed"] == "true", on
                assert on["bg"] == "rgb(35, 19, 3)", on
                assert on["color"] == "rgb(255, 255, 255)", on
                assert on["bw"] == "2px" and on["bc"] == "rgb(251, 191, 36)", on
                assert "✓ Starred" in on["text"], on
                assert on["svgFill"] == "rgb(251, 191, 36)", on
                assert off["bg"] != on["bg"], (off, on)
                note_star = pg.evaluate("""() => { const el = document.querySelector('[data-star].starred svg, .starbtn.starred svg');
                  return el ? getComputedStyle(el).fill : null; }""")
                assert note_star == "rgb(251, 191, 36)", note_star
                print("ITEM2 %s: off=%s on=%s note_star=%s"
                      % ("light" if light else "dark", off, on, note_star))
                pg.screenshot(path="%s/r55_item2_starred_%s.png"
                              % (PROOF, "light" if light else "dark"))
            finally:
                browser.close()


# --- (4) Save Password checkbox: MB Set Up card only -----------------

def test_item3_mb_setup_no_savepw(server):
    """(4) The MB Set Up Your Addresses card has NO Save Password
    checkbox (the Nov 7 5:50 PM correction) -- while the LOGIN
    page checkbox stays (and APK / PC web are untouched)."""
    assert "mpcsavechk" not in SRC
    assert "mpcsave" not in SRC
    assert "gloginsavechk" in SRC
    client, base, proc, port, home = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, pg = _host_page(pw, port, 390, 844)
        try:
            pg.evaluate("() => setTab('send')")
            pg.wait_for_timeout(600)
            n = pg.evaluate(
                "() => document.querySelectorAll('#mpcsavechk').length")
            assert n == 0, n
            setup_has = pg.evaluate("""() => {
              const cards = [...document.querySelectorAll('.minicard')];
              const c = cards.find(x => /Set Up Your Addresses/i.test(x.textContent));
              return c ? /save password/i.test(c.textContent) : null; }""")
            assert setup_has is False, setup_has
            login_has = pg.evaluate(
                "() => document.querySelectorAll('#gloginsavechk').length")
            assert login_has >= 1, login_has
        finally:
            browser.close()


# --- (5)/(6) Saved Open ----------------------------------------------

def test_item5_openlocal_host(server):
    """(5)/(6) PC web Saved Open: /api/openlocal opens the file
    FROM PC STORAGE (host-only). A real file opens; a missing
    file and a traversal name are refused, never opened from
    outside the shared folder."""
    client, base, proc, port, home = server
    (base / "hello.txt").write_text("hello openlocal\n")
    s, j = client.j("POST", "/api/openlocal", {"name": "hello.txt"})
    assert s == 200 and j["ok"] is True, (s, j)
    s, j = client.j("POST", "/api/openlocal", {"name": "nope.txt"})
    assert s == 200 and j["ok"] is False, (s, j)
    s, j = client.j("POST", "/api/openlocal", {"name": "../dropit.py"})
    assert s == 200 and j["ok"] is False, (s, j)
    s, j = client.j("POST", "/api/openlocal", {"name": "dropit.py"})
    assert s == 200 and j["ok"] is False, (s, j)


def _raw_guest(port, method, path, body=None):
    import http.client
    conn = http.client.HTTPConnection("127.0.0.3", port, timeout=10)
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Content-Type": "application/json"} if data else {}
    conn.request(method, path, body=data, headers=hdrs)
    resp = conn.getresponse()
    raw = resp.read()
    status = resp.status
    conn.close()
    try:
        return status, json.loads(raw.decode() or "{}")
    except ValueError:
        return status, {}


def test_item5_openlocal_guest_denied(server):
    """(5)/(6) A LAN guest can never make the host PC open a
    file: /api/openlocal is host-only (403 host_only)."""
    client, base, proc, port, home = server
    (base / "hello.txt").write_text("hello openlocal\n")
    fwd = _Fwd(port)
    try:
        s, j = _raw_guest(fwd.port, "POST", "/api/openlocal",
                          {"name": "hello.txt"})
        assert s == 403, (s, j)
        assert j.get("code") == "host_only", j
    finally:
        fwd.close()


def test_item5_saved_open_uses_share_not_download():
    """(5) openSavedFileOS hands the file to the OS / an app:
    bridge open_file, host /api/openlocal, else the system
    share sheet (navigator.share({files}) -- Android open-with
    chooser). No anchor download anywhere in it."""
    m = re.search(r"async function openSavedFileOS\(name\)\{(.*?)\n\}\nasync function openSavedFile\(",
                  SRC, re.S)
    assert m, "openSavedFileOS not found"
    body = m.group(1)
    assert 'postHostJ("/api/openlocal"' in body, body[:500]
    assert "navigator.share({files: [file]})" in body
    assert "window.open(url" in body  # tab-view fallback only
    assert ".download" not in body
    assert "createElement(\"a\")" not in body
    assert "a.click()" not in body
