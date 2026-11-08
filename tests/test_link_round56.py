"""v2.8.41 round (Essef Nov 7, ~8:11 PM) -- WEB/DESKTOP track only,
local test build only. FIVE items (repeat failures of 2.8.40 claims
in items 1-2, so every proof here is measured under real
conditions, not a warm harness):

  (1) SEARCH: 2.8.40 claimed 1.48s, but on real devices every
      search timed out ("took too long"). Root causes, measured:
      (a) app.py never started the startup preload, so the
      desktop app had NO background index build -- the first
      search WAS the full build; (b) search_files ran
      build_index inline when the lock was free -- first search
      on the 83-file phone-photo fixture took 40.8s (small
      images) and 75.0s -> timeout (12MP photos; build still
      incomplete at 300s+). Fix: a search NEVER builds the
      index -- it kicks a single-flight background build and
      searches the index as it stands, plus a live keyword
      fallback (filename + readable text, no models, no OCR)
      for files the index has not reached yet, so a cold-start
      search answers in seconds with real results.
  (2) SPARKLE: 2.8.40 claimed verdicts persist, but on real
      devices the sparkle reloaded on every restart. Root
      cause: ai_state kept text-less images "provisional"
      (unknown) until 3 OCR rechecks accumulated -- measured
      on the 83-file fixture: 30 of 83 files unknown after a
      full build, 30 /api/aicheck calls (89.2s of OCR) on the
      next restart, settling only on the 3rd restart (and only
      if the session lived long enough to run all rechecks).
      Fix: a recorded verdict IS durable -- known=True the
      moment the index holds has_ocr/has_text -- and a no-op
      build no longer rewrites ai_index.pkl.
  (3) STARRED: OFF must be the APK's yellowish-brown gold
      (gradient #FBBF24 -> #F59E0B, white label, dark #231303
      outline star -- btn_gold.xml / paintStarFilter), ON the
      dark #231303 chip, 2px gold stroke, WHITE "✓ Starred"
      label, filled gold star (#FBBF24 fill, #F59E0B stroke)
      -- BOTH themes, D + web. (2.8.40 made OFF a quiet
      neutral button, so the button never looked like the
      APK's; the ON label was gold in 2.8.40/2.8.41-first-cut,
      but the APK track verified Nov 7 (2.6.115) that the APK
      uses WHITE text in both states -- that is authoritative.)
  (4) DRAG: clicking/dragging on D glitched; smooth in 2.8.38.
      Bisect: the drag JS and app.py are byte-identical
      2.8.38 -> 2.8.40, and no overlay geometry changed -- the
      glitch is the un-awaited move_window per mousemove
      queueing stale targets behind a bridge starved by the
      (1)/(2) CPU storms. Fix: coalesced moves (at most one in
      flight, latest target wins) + blur safety, and the storms
      themselves are fixed in (1)/(2).
  (5) MB SAVED: tapping a file in the in-app "Saved on this
      device" viewer (showSaved) did nothing -- the rows had
      NO preview handler at all (only the Open button, which
      hands off to the OS). The login-page Saved list previewed
      fine. Fix: row tap previews (previewSavedFile); a saved
      row whose blob is gone re-downloads QUIETLY for preview
      (no "Save file?" dialog) or shows a clear card instead
      of a toast.
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

PROOF = "/home/hatch/workspace/dropit-proof-round56"
os.makedirs(PROOF, exist_ok=True)

MOBILE_UA = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36")


def test_version_is_2_8_41():
    assert D.VERSION == "3.0", D.VERSION


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
        p = "/tmp/r56_script%d.js" % i
        with open(p, "w", encoding="utf-8") as f:
            f.write(s)
        r = subprocess.run(["node", "--check", p],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[:500]


def test_search_never_builds_inline():
    """(1) search_files contains no inline build_index call --
    the 2.8.40 first-search-is-a-full-build path is gone."""
    m = re.search(r"def search_files\(directory.*?(?=\ndef )",
                  AI_SRC, re.S)
    assert m, "search_files not found"
    assert "build_index(" not in m.group(0), \
        "search_files still builds inline"
    assert "_ensure_background_build(directory, data_dir)" in m.group(0)


def test_search_cold_start_fast_with_results(tmp_path):
    """(1) Cold start: empty index, realistic small folder.
    The first search answers in seconds (not the 75s timeout)
    with real results, and reports indexing=true."""
    d = tmp_path / "shared"
    d.mkdir()
    (d / "beach_house_notes.txt").write_text(
        "beach house checklist and garden plan\n")
    (d / "invoice_march.txt").write_text("invoice for bike parts\n")
    (d / "photo_beach.jpg").write_bytes(
        bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"\x00" * 200)
    data = tmp_path / "data"
    data.mkdir()
    t0 = time.time()
    r = dropit_ai.search_files(str(d), str(data), "beach")
    dt = time.time() - t0
    assert r["message"] != "timeout", r
    assert dt < 20, dt
    names = [x["name"] for x in r["results"]]
    assert "beach_house_notes.txt" in names, r
    assert r.get("indexing") is True, r
    assert r.get("pending", 0) >= 1, r
    print("COLD SEARCH: %.2fs message=%s results=%s indexing=%s"
          % (dt, r["message"], names, r.get("indexing")))
    # a second search (index still building in background) is fast too
    t0 = time.time()
    r2 = dropit_ai.search_files(str(d), str(data), "beach")
    assert time.time() - t0 < 20
    assert r2["message"] != "timeout", r2


def test_search_live_fallback_filename_only(tmp_path):
    """(1) Live fallback: an unindexed image matches by filename
    with no OCR and no embedding."""
    d = tmp_path / "shared"
    d.mkdir()
    (d / "sunset_motorbike.jpg").write_bytes(b"\x00" * 100)
    data = tmp_path / "data"
    data.mkdir()
    hits = dropit_ai._live_keyword_hits(
        str(d), ["sunset_motorbike.jpg"], {"sunset", "motorbike"},
        None, None)
    assert len(hits) == 1 and hits[0][1] == "sunset_motorbike.jpg", hits
    assert hits[0][0] == 0.90 and hits[0][4] is True


def test_build_index_noop_does_not_rewrite(tmp_path):
    """(2) A no-op build_index (nothing embedded, nothing
    removed) leaves ai_index.pkl byte-identical -- the stale
    rewrite that could wipe concurrent verdict updates is gone."""
    d = tmp_path / "shared"
    d.mkdir()
    (d / "a.txt").write_text("hello world\n")
    data = tmp_path / "data"
    data.mkdir()
    dropit_ai.build_index(str(d), str(data))
    from pathlib import Path
    p = Path(dropit_ai._index_path(str(d), str(data)))
    b1 = p.read_bytes()
    m1 = p.stat().st_mtime_ns
    time.sleep(0.02)
    r = dropit_ai.build_index(str(d), str(data))
    assert r["embedded_now"] == 0, r
    assert p.read_bytes() == b1
    assert p.stat().st_mtime_ns == m1


def test_ai_state_verdict_durable(tmp_path):
    """(2) A recorded no-text verdict for an image is KNOWN
    immediately -- no provisional rechecks, no restart storm."""
    d = tmp_path / "shared"
    d.mkdir()
    import base64
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    (d / "pic.jpg").write_bytes(png)
    (d / "hello.txt").write_text("hello world\n")
    data = tmp_path / "data"
    data.mkdir()
    dropit_ai.build_index(str(d), str(data))
    assert dropit_ai.ai_state(str(d), str(data), "pic.jpg") == (False, True)
    assert dropit_ai.ai_state(str(d), str(data), "hello.txt") == (True, True)


def test_sparkle_zero_aicheck_after_restart(server):
    """(2) Restart cycle at the HTTP level: after one index
    build, /api/files reports every scanned file known, so a
    client restart needs ZERO /api/aicheck calls for them."""
    client, base, proc, port, home = server
    (base / "hello.txt").write_text("hello world\n")
    import base64
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    (base / "pic.jpg").write_bytes(png)
    data = home / ".config" / "DropIt"
    dropit_ai.build_index(str(base), str(data))
    s, files = client.j("GET", "/api/files")
    assert s == 200, files
    by_name = {f["name"]: f for f in files}
    assert by_name["hello.txt"]["ai_known"] is True, by_name
    assert by_name["pic.jpg"]["ai_known"] is True, by_name
    assert by_name["pic.jpg"]["ai"] is False, by_name
    unknown = [f for f in files if not f["ai_known"]]
    assert unknown == [], unknown
    print("SPARKLE: 0 unknown of %d after build; 0 aicheck needed"
          % len(files))


# --- (3) Starred ----------------------------------------------------

def _star_state(pg):
    return pg.evaluate("""() => { const b = document.querySelector('#starfilter');
      const cs = getComputedStyle(b); const sv = b.querySelector('svg');
      return {bg: cs.backgroundColor, bgImg: cs.backgroundImage,
        color: cs.color, bw: cs.borderTopWidth, bc: cs.borderTopColor,
        svgFill: getComputedStyle(sv).fill, svgStroke: getComputedStyle(sv).stroke,
        text: b.textContent.trim(),
        pressed: b.getAttribute('aria-pressed')}; }""")


def test_item3_starred_apk_gold_off_dark_on(server):
    """(3) OFF = APK gold gradient (yellowish-brown), white
    label, dark outline star; ON = dark #231303 chip, 2px gold
    stroke, WHITE '✓ Starred' label, filled gold star
    (#FBBF24 fill, #F59E0B stroke). Both themes,
    mobile web (390px) + desktop web. ON label white per the
    APK 2.6.115 verified reference values (Nov 7) -- the APK
    uses white text in both states."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink", {"name": "starlink"})
    assert s == 200 and j["ok"], j
    s, j = client.j("POST", "/api/snippet", {"text": "starred note"})
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
                pg.wait_for_selector("#starfilter", timeout=5000)
                off = _star_state(pg)
                assert off["pressed"] == "false", off
                assert "linear-gradient" in off["bgImg"], off
                assert "251, 191, 36" in off["bgImg"], off
                assert "245, 158, 11" in off["bgImg"], off
                assert off["color"] == "rgb(255, 255, 255)", off
                assert off["svgStroke"] == "rgb(35, 19, 3)", off
                pg.click("#starfilter")
                pg.wait_for_timeout(500)
                on = _star_state(pg)
                assert on["pressed"] == "true", on
                assert on["bg"] == "rgb(35, 19, 3)", on
                assert on["color"] == "rgb(255, 255, 255)", on
                assert on["bw"] == "2px" and on["bc"] == "rgb(251, 191, 36)", on
                assert "✓ Starred" in on["text"], on
                assert on["svgFill"] == "rgb(251, 191, 36)", on
                assert on["svgStroke"] == "rgb(245, 158, 11)", on
                assert off["bgImg"] != on["bgImg"], (off, on)
                print("ITEM3 %s: off=%s on=%s"
                      % ("light" if light else "dark", off, on))
                pg.screenshot(path="%s/r56_item3_starred_%s.png"
                              % (PROOF, "light" if light else "dark"))
            finally:
                browser.close()
        # desktop web width, dark
        browser, pg = _pc_page(pw, port, 1280, 800)
        try:
            pg.wait_for_timeout(900)
            pg.evaluate("() => setTab('notes')")
            pg.wait_for_timeout(600)
            off = _star_state(pg)
            assert "linear-gradient" in off["bgImg"], off
            assert "251, 191, 36" in off["bgImg"], off
            pg.click("#starfilter")
            pg.wait_for_timeout(500)
            on = _star_state(pg)
            assert on["bg"] == "rgb(35, 19, 3)", on
            assert "✓ Starred" in on["text"], on
            print("ITEM3 desktop-dark: off=%s on=%s" % (off, on))
            pg.screenshot(path="%s/r56_item3_starred_desktop_dark.png" % PROOF)
        finally:
            browser.close()


# --- (4) Drag -------------------------------------------------------

def test_item4_drag_coalesced_moves(server):
    """(4) Drag JS: with a slow bridge (50ms per move), a 20-step
    drag issues NO stale queued moves -- at most one in flight,
    every executed target was requested, and the last executed
    target is the latest mousemove's (no jump-through-old-spots)."""
    client, base, proc, port, home = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, pg = _pc_page(pw, port, 1280, 800)
        try:
            pg.wait_for_timeout(900)
            pg.evaluate("""() => {
              window.__moves = []; window.__requested = [];
              window.__inflight = 0; window.__maxflight = 0;
              const origTbMove = window._tbMove;
              window._tbMove = (x, y) => { window.__requested.push([x, y]); return origTbMove(x, y); };
              window.pywebview.api.move_window = (x, y) => new Promise(res => {
                window.__inflight++; window.__maxflight = Math.max(window.__maxflight, window.__inflight);
                setTimeout(() => { window.__moves.push([x, y]); window.__inflight--; res({ok: true}); }, 50);
              });
            }""")
            pg.wait_for_timeout(300)
            bar = pg.query_selector("#titlebar")
            box = bar.bounding_box()
            assert box and box["height"] >= 40, box
            x0, y0 = box["x"] + 200, box["y"] + 10
            pg.mouse.move(x0, y0)
            pg.mouse.down()
            for i in range(1, 21):
                pg.mouse.move(x0 + i * 10, y0 + i * 2, steps=1)
            pg.mouse.up()
            pg.wait_for_timeout(1500)
            res = pg.evaluate("""() => ({moves: window.__moves,
              requested: window.__requested,
              maxflight: window.__maxflight})""")
            assert res["maxflight"] <= 1, res
            assert res["requested"], res
            assert res["moves"], res
            assert res["moves"][-1] == res["requested"][-1], res
            assert all(m in res["requested"] for m in res["moves"]), res
            xs = [m[0] for m in res["moves"]]
            assert xs == sorted(xs) and len(xs) == len(set(xs)), res
            print("ITEM4: %d requested, %d executed, maxflight=%d, last=%s"
                  % (len(res["requested"]), len(res["moves"]),
                     res["maxflight"], res["moves"][-1]))
        finally:
            browser.close()


# --- (5) MB Saved preview -------------------------------------------

def _seed_saved(pg, with_blob=True, names=("hello.txt", "photo.jpg")):
    pg.evaluate("""async (withBlob) => {
      const txt = new Blob(["Hello from the saved file\\nSecond line here"], {type: "text/plain"});
      const cv = document.createElement("canvas"); cv.width = 200; cv.height = 120;
      const g = cv.getContext("2d"); g.fillStyle = "#277ff0"; g.fillRect(0,0,200,120);
      g.fillStyle = "#fff"; g.font = "bold 20px sans-serif"; g.fillText("SAVED PHOTO", 20, 65);
      const png = await new Promise(r => cv.toBlob(r, "image/png"));
      const ledger = {};
      if (withBlob) {
        await DBCACHE.put("hello.txt", txt);
        await DBCACHE.put("photo.jpg", png);
      }
      ledger["hello.txt"] = {size: 41, ts: Math.floor(Date.now()/1000)};
      ledger["photo.jpg"] = {size: 1234, ts: Math.floor(Date.now()/1000)};
      localStorage.setItem("dropit_dl", JSON.stringify(ledger));
      return "seeded";
    }""", with_blob)


def _mobile_guest_page(pw, port):
    fwd = _Fwd(port)
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    ctx = browser.new_context(viewport={"width": 390, "height": 844},
                              user_agent=MOBILE_UA, is_mobile=True,
                              has_touch=True)
    pg = ctx.new_page()
    pg.goto("http://127.0.0.3:%d/" % fwd.port)
    pg.wait_for_selector("#gloginbtn", state="attached", timeout=10000)
    pg.wait_for_timeout(900)
    return browser, ctx, pg, fwd


def test_item5_mb_saved_tap_previews(server):
    """(5) In-app Saved on this device (MB, 390px): tapping a
    saved file's name opens the preview with its content.
    Also: the row's Open button still hands off (not preview)."""
    client, base, proc, port, home = server
    (base / "hello.txt").write_text("Hello from the saved file\nSecond line here\n")
    s, j = client.j("POST", "/api/setlink", {"name": "mbsaved"})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, ctx, pg, fwd = _mobile_guest_page(pw, port)
        try:
            _wait_authed(pg)
            _seed_saved(pg)
            pg.wait_for_timeout(400)
            # Files tab -> Saved button (mobile head)
            pg.evaluate("() => setTab('files')")
            pg.wait_for_timeout(600)
            pg.wait_for_selector("#msavedbtn", timeout=5000)
            pg.click("#msavedbtn")
            pg.wait_for_timeout(800)
            rows = pg.evaluate(
                "() => [...document.querySelectorAll('#vcontent .frow')]"
                ".map(r => r.dataset.frow)")
            assert "hello.txt" in rows and "photo.jpg" in rows, rows
            pg.click("#vcontent .frow[data-frow='hello.txt'] .fname")
            pg.wait_for_timeout(1000)
            st = pg.evaluate("""() => ({open: document.querySelector('#viewer').classList.contains('open'),
              title: document.querySelector('#vtitle').textContent,
              text: document.querySelector('#vcontent').innerText.slice(0, 120)})""")
            assert st["open"] is True, st
            assert st["title"] == "hello.txt", st
            assert "Hello from the saved file" in st["text"], st
            print("ITEM5 txt preview: %s" % st)
            pg.screenshot(path="%s/r56_item5_saved_txt_preview.png" % PROOF)
            pg.click("#vclose")
            pg.wait_for_timeout(600)
            # photo row tap -> image preview
            pg.click("#msavedbtn")
            pg.wait_for_timeout(800)
            pg.click("#vcontent .frow[data-frow='photo.jpg'] .fname")
            pg.wait_for_timeout(1000)
            st2 = pg.evaluate("""() => ({open: document.querySelector('#viewer').classList.contains('open'),
              title: document.querySelector('#vtitle').textContent,
              hasImg: !!document.querySelector('#vcontent img')})""")
            assert st2["open"] is True and st2["hasImg"] is True, st2
            print("ITEM5 photo preview: %s" % st2)
            pg.screenshot(path="%s/r56_item5_saved_photo_preview.png" % PROOF)
        finally:
            browser.close()


def test_item5_mb_saved_missing_blob_quiet_redownload(server):
    """(5) Saved row whose blob is gone from the device but the
    file is still on the PC: tapping previews it via a quiet
    re-download -- no 'Save file?' dialog, preview opens."""
    client, base, proc, port, home = server
    # NB: write the file BEFORE setlink -- setlink moves the
    # shared folder's files into the address subfolder, so a
    # file written after it is NOT in the shared folder and the
    # re-download must 404 (that is the gone-file case, test 3).
    (base / "hello.txt").write_text("Hello from the saved file\nSecond line here\n")
    s, j = client.j("POST", "/api/setlink", {"name": "mbsaved"})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, ctx, pg, fwd = _mobile_guest_page(pw, port)
        try:
            _wait_authed(pg)
            _seed_saved(pg, with_blob=False)
            pg.wait_for_timeout(400)
            pg.evaluate("() => setTab('files')")
            pg.wait_for_timeout(600)
            pg.click("#msavedbtn")
            pg.wait_for_timeout(800)
            pg.click("#vcontent .frow[data-frow='hello.txt'] .fname")
            pg.wait_for_timeout(1500)
            st = pg.evaluate("""() => ({open: document.querySelector('#viewer').classList.contains('open'),
              title: document.querySelector('#vtitle').textContent,
              text: document.querySelector('#vcontent').innerText.slice(0, 120),
              cfdlg: document.querySelector('#cfdlg').classList.contains('open')})""")
            assert st["cfdlg"] is False, st
            assert st["open"] is True, st
            assert "Hello from the saved file" in st["text"], st
            print("ITEM5 missing-blob redownload preview: %s" % st)
        finally:
            browser.close()


def test_item5_mb_saved_gone_file_shows_card(server):
    """(5) Saved row whose blob is gone AND whose file is gone
    from the PC: tapping still opens the viewer with a clear
    card, never a bare toast."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink", {"name": "mbsaved"})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, ctx, pg, fwd = _mobile_guest_page(pw, port)
        try:
            _wait_authed(pg)
            _seed_saved(pg, with_blob=False)
            pg.wait_for_timeout(400)
            pg.evaluate("() => setTab('files')")
            pg.wait_for_timeout(600)
            pg.click("#msavedbtn")
            pg.wait_for_timeout(800)
            pg.click("#vcontent .frow[data-frow='hello.txt'] .fname")
            pg.wait_for_timeout(1500)
            st = pg.evaluate("""() => ({open: document.querySelector('#viewer').classList.contains('open'),
              title: document.querySelector('#vtitle').textContent,
              text: document.querySelector('#vcontent').innerText.slice(0, 200)})""")
            assert st["open"] is True, st
            assert "no longer in the shared folder" in st["text"], st
            print("ITEM5 gone-file card: %s" % st)
        finally:
            browser.close()
