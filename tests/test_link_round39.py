"""v2.8.24 round (Essef Nov 6, ~3:18 AM) -- web/desktop only.

(1) PREVIEW ZOOM -- WINDOW FIXED, PICTURE ONLY ZOOMS: the 2.8.22 /
    2.8.23 zoom resized the whole window from the zoomed image
    size, so zooming out shrank the window and pushed the
    buttons out of it (measured on 2.8.23: box 833px -> 452px
    at 50%). Now _pvApply sizes ONLY the <img>; the box width is
    set once on image load from the fit size and never again, so
    the window and its buttons never move at any zoom level (the
    body scrolls past the fit size instead). ALSO: the window is
    LESS transparent -- box alpha .85 dark / .92 light (was .5 /
    .55). ALSO: the preview Download button in LIGHT mode was
    white text on a white button (contrast 1.0:1 -- the light
    .btn rule out-specificed .pvdl); it is now a solid darker
    blue #1e6ad8 fill, white text, >= 4.5:1.
(2) OPEN BUTTON OPENS DIRECTLY: on the desktop the file-row
    button (title "Open", open icon) used to reveal the file in
    its folder (revealFile); now it calls fileTap, which opens
    the file directly (bridge open_file on the desktop, Download
    then Open elsewhere). Clicking the file NAME / thumbnail
    still previews in-page. "Show in folder" survives on the
    file-row right-click menu (desktop only).
(3) CIRCULAR PROGRESS RING MOVED: off the footer (it overlapped
    the footer / slogan at bottom:84px) to the TOP of the Shared
    Files card -- the pill's bottom edge touches the card's top
    edge, just below the top pill, centred on the card
    (positioned by _upShow from the files column's rect; falls
    back to top-centre when the files column is hidden). It is
    SOLID now (themed card background + border, theme-coloured
    number/name, never transparent) and has an X button that
    CANCELS the in-flight upload (aborts every live XHR; the
    queue empties quietly, no "sent" toast, ring hides, the file
    is never saved).
(4) TEXT PREVIEW SELECTION: text-based previews (text, Word,
    Excel) get cursor:text + user-select:text, so text is
    individually selectable to copy (proven by double-clicking a
    word, copying it, and reading the clipboard).
(5) STARRED BUTTON TEXT WHITE + SAVE BUTTON: the "Starred"
    button text (and star icon) is WHITE on its amber fill (was
    near-black #231303). The three dialog Save buttons (#lkset,
    #lockpwsave, #msave) are centred flex rows -- icon + text
    share one centre line (the host Save's text sat ~4px below
    the button centre, measured) -- and read "SAVE" (all caps).
    The note-editor save and "Save on phone" are untouched.
(6) SEND TEXT NOTE BUTTON (web): the icon is wrapped with the
    text in one .msend-in span, so icon + text are a single
    centred unit (gap 6px) that no rule can split again --
    Essef's phone screenshot showed the icon pinned at the
    button's left padding with the text centred on its own
    (measured from his screenshot: icon 41 device-px from the
    button edge, text centred independently). Renamed to
    "Send Text Note" (was "Send Text to PC"). Solid blue #277ff0
    and the text-snippet icon stay; PC-app styling untouched.
(7) TAB SLIDE TRANSITIONS (web): changing tabs slides the new
    column in -- very fast (.18s ease-out), direction following
    tab order (--tabdx).
(8) SAVE SLIDE-IN (web): clicking a Save button slides the board
    in with the same fast slide (.boardslide, re-triggered by
    slideInBoard on every dialog Save success).

Superseded round38/37 assertions (Essef's new instructions
replace them, NOT regressions -- see the notes above):
- round38 test_2: preview box bg is now rgba(18,23,42,.85),
  not .5; test_2 source assertion on "rgba(18,23,42,.5)".
- round38 test_4: the web Send Text button is now labelled
  "Send Text Note", not "Send Text to PC".
- round37 test_9: the row button no longer calls revealFile;
  revealFile + the bridge + the probe still exist, and "Show in
  folder" is on the file-row right-click menu instead.
"""
import ast
import os
import re
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
from test_link_round2 import server, _raw  # noqa: F401,E402
from test_link_round36 import _playwright, _guest_page  # noqa: E402
from test_link_round37 import (  # noqa: E402
    _host_page, _open_preview, _preview_geom, _close_preview,
    _make_fixtures, _measure_send_tab)

PAGE = D.PAGE
SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py"),
           encoding="utf-8").read()

PROOF = "/home/hatch/workspace/dropit-proof-round39"
os.makedirs(PROOF, exist_ok=True)


def _contrast_rgb(fg, bg):
    def lum(rgb):
        def f(c):
            c /= 255.0
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        r, g, b = rgb
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
    l1, l2 = lum(fg), lum(bg)
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)


def _parse_rgb(s):
    m = re.match(r"rgba?\((\d+)[,\s]+(\d+)[,\s]+(\d+)(?:[,\s]+([\d.]+))?\)", s)
    assert m, s
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)),
            float(m.group(4)) if m.group(4) is not None else 1.0)


def _sample_transform(pg, sel, ms=200, step=25):
    """Sample an element's translateX over `ms`; returns the list
    of tx values seen (0 when no transform) and the final state."""
    vals = []
    for _ in range(int(ms / step)):
        vals.append(pg.evaluate("""(sel) => {
          const el = document.querySelector(sel);
          if (!el) return null;
          const t = getComputedStyle(el).transform;
          if (t === 'none') return 0;
          const m = t.match(/matrix\\(([^)]+)\\)/);
          return m ? parseFloat(m[1].split(',')[4]) : 0;
        }""", sel))
        pg.wait_for_timeout(step)
    return vals


def test_version_is_2_8_24():
    assert D.VERSION == "2.8.24"


def test_interpreted_page_valid_js_no_surrogates():
    for n in ast.walk(ast.parse(SRC)):
        if isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "PAGE"
                for t in n.targets):
            page = n.value.value
            break
    else:
        raise AssertionError("PAGE assignment not found")
    assert page == PAGE
    assert not [c for c in page if 0xD800 <= ord(c) <= 0xDFFF]
    page.encode("utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
    assert len(scripts) == 2
    for i, js in enumerate(scripts):
        with open("/tmp/r39_script_%d.js" % i, "w",
                  encoding="utf-8") as fh:
            fh.write(js)
        out = subprocess.run(["node", "--check",
                              "/tmp/r39_script_%d.js" % i],
                             capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr


# ---- (1) preview zoom: fixed window, less transparent, Download -----
def test_1_preview_fixed_window_source():
    # Box alpha .85 dark / .92 light; the 2.8.23 .5 is gone.
    assert "rgba(18,23,42,.85)" in PAGE
    assert "rgba(255,255,255,.92)" in PAGE
    assert "rgba(18,23,42,.5)" not in PAGE
    # _pvApply sizes only the image now; the box width is set
    # once, on image load, from the fit size. (The video
    # _vidSize still sizes its own box -- that is the 2.8.23
    # video hugging, not the picture zoom.)
    m = re.search(r"const _pvApply = \(\) => \{(.*?)\n    \};", PAGE, re.S)
    assert m, "_pvApply not found"
    assert "box.style.width" not in m.group(1), m.group(1)
    assert "box.style.width = Math.min(_pvBaseW + 70" in PAGE
    # Download button: light rule no longer paints it white, and
    # the light fill is the darker blue.
    assert ":not(.pvdl)" in PAGE
    assert "html.light .previewbox .pvdl { background:#1e6ad8; color:#fff; }" in PAGE


def _preview_box_row(pg):
    return pg.evaluate("""() => {
      const box = document.querySelector('.previewbox');
      const row = document.querySelector('.pvrow');
      const img = document.querySelector('#previewbody img');
      const b = box.getBoundingClientRect(), r = row.getBoundingClientRect();
      const i = img ? img.getBoundingClientRect() : null;
      return {box: {x: Math.round(b.x), y: Math.round(b.y),
                    w: Math.round(b.width), h: Math.round(b.height)},
              row: {y: Math.round(r.y), bottom: Math.round(r.bottom)},
              imgW: i ? Math.round(i.width) : null,
              zoom: document.querySelector('#pvzval').textContent,
              boxBg: getComputedStyle(box).backgroundColor,
              dlBg: getComputedStyle(document.querySelector('#previewdl')).backgroundColor,
              dlColor: getComputedStyle(document.querySelector('#previewdl')).color};
    }""")


def test_1_live_zoom_window_fixed_opaque_and_download(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r39zoom"})
    _make_fixtures(os.path.join(str(base), "r39zoom"))
    pw = _playwright()
    try:
        # Dark mode: window + buttons identical at every zoom.
        browser, pg = _host_page(pw, port)
        try:
            _open_preview(pg, "pic.png")
            pg.wait_for_timeout(600)
            m0 = _preview_box_row(pg)
            assert m0["box"]["w"] == 833 and m0["box"]["h"] == 745, m0
            assert m0["zoom"] == "100%", m0
            # More opaque than 2.8.23's 0.5.
            assert _parse_rgb(m0["boxBg"])[3] == 0.85, m0
            assert _parse_rgb(m0["boxBg"])[:3] == (18, 23, 42), m0
            for action, want_zoom, want_img in [
                    ("#pvzin", "125%", 954),
                    ("#pvzin", "150%", 1145),
                    ("#pvzout", "125%", 954),
                    ("#pvzout", "100%", 763),
                    ("#pvzout", "75%", 572),
                    ("#pvzout", "50%", 382)]:
                pg.click(action)
                pg.wait_for_timeout(300)
                m = _preview_box_row(pg)
                assert m["zoom"] == want_zoom, (action, m)
                assert m["imgW"] == want_img, (action, m)
                # The WINDOW and the button row never move.
                assert m["box"] == m0["box"], (action, m0, m)
                assert m["row"] == m0["row"], (action, m0, m)
            pg.screenshot(path=os.path.join(PROOF, "r39_zoom_out_50.png"))
            # Click the image: 200% -- the picture zooms inside
            # the same fixed window (body scrolls, box stays).
            pg.evaluate("() => document.querySelector('#previewbody img').click()")
            pg.wait_for_timeout(300)
            m = _preview_box_row(pg)
            assert m["zoom"] == "200%" and m["imgW"] == 1526, m
            assert m["box"] == m0["box"], m
            assert m["row"] == m0["row"], m
            pg.screenshot(path=os.path.join(PROOF, "r39_zoom_in_200.png"))
            # Wheel zoom out to 100% via the API, then Fit.
            pg.evaluate("() => window.__pvZoom.set(1)")
            pg.wait_for_timeout(300)
            m = _preview_box_row(pg)
            assert m["zoom"] == "100%" and m["imgW"] == 763, m
            assert m["box"] == m0["box"], m
            _close_preview(pg)
        finally:
            browser.close()
        # Light mode: the window is .92 opaque and the Download
        # button is dark blue fill + white text, >= 4.5:1.
        browser, pg = _host_page(pw, port, light=True)
        try:
            _open_preview(pg, "pic.png")
            pg.wait_for_timeout(600)
            m = _preview_box_row(pg)
            assert _parse_rgb(m["boxBg"])[3] == 0.92, m
            assert _parse_rgb(m["boxBg"])[:3] == (255, 255, 255), m
            assert m["dlBg"] == "rgb(30, 106, 216)", m
            assert m["dlColor"] == "rgb(255, 255, 255)", m
            fg = _parse_rgb(m["dlColor"])[:3]
            bg = _parse_rgb(m["dlBg"])[:3]
            c = _contrast_rgb(fg, bg)
            assert c >= 4.5, (c, m)
            pg.screenshot(path=os.path.join(PROOF, "r39_preview_light.png"))
            _close_preview(pg)
        finally:
            browser.close()
        # Dark mode Download: still solid blue #277ff0, white text.
        browser, pg = _host_page(pw, port)
        try:
            _open_preview(pg, "pic.png")
            pg.wait_for_timeout(600)
            m = _preview_box_row(pg)
            assert m["dlBg"] == "rgb(39, 127, 240)", m
            assert m["dlColor"] == "rgb(255, 255, 255)", m
            _close_preview(pg)
        finally:
            browser.close()
    finally:
        pw.stop()


# ---- (2) Open button opens directly -----------------------------------
def test_2_open_button_source():
    assert 'fileTap(f, b); });' in PAGE
    assert 'if(hasBridge()) revealFile(f.name); else fileTap(f, b);' not in PAGE
    assert 'title="${(hasBridge() || isDownloaded(f)) ? "Open" : "Download"}"' in PAGE
    # "Show in folder" survives on the file-row right-click menu.
    assert 'addItem("Show in folder", () => revealFile(frowEl.dataset.frow));' in PAGE
    assert "function revealFile(name){" in PAGE
    assert "window.pywebview.api.open_file(name)" in PAGE


def test_2_live_open_direct_and_ctx_show_in_folder(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r39open"})
    _make_fixtures(os.path.join(str(base), "r39open"))
    pw = _playwright()
    try:
        browser, pg = _host_page(pw, port)
        try:
            # Fake the desktop bridge: open_file / reveal_file
            # record their calls; every other bridge method is a
            # harmless async no-op.
            pg.evaluate("""() => {
              window.__bridgeCalls = [];
              window.pywebview = {api: new Proxy({}, {get: (t, k) => {
                if (k === 'open_file') return async (n) => {
                  window.__bridgeCalls.push(['open_file', n]); return true; };
                if (k === 'reveal_file') return async (n) => {
                  window.__bridgeCalls.push(['reveal_file', n]); return true; };
                return async () => null;
              }})};
              markPcApp();
              lastFilesSig = null; loadFiles();
            }""")
            pg.wait_for_timeout(800)
            # The row button now says Open on the desktop.
            title = pg.evaluate("""() => {
              const b = document.querySelector('.frow[data-frow="pic.png"] [data-dl]');
              return b ? b.title : null; }""")
            assert title == "Open", title
            # Click the row Open button: the file opens directly
            # via the bridge -- no preview, no reveal.
            pg.click('.frow[data-frow="pic.png"] [data-dl]')
            pg.wait_for_timeout(600)
            calls = pg.evaluate("() => window.__bridgeCalls")
            assert calls == [["open_file", "pic.png"]], calls
            assert pg.evaluate(
                "() => document.querySelector('#previewpop').classList.contains('open')"
            ) is False
            # Clicking the file NAME still previews in-page.
            pg.evaluate("""() => {
              const row = [...document.querySelectorAll('.frow')].find(r => r.dataset.frow === 'pic.png');
              row.querySelector('.fname').click(); }""")
            pg.wait_for_timeout(800)
            assert pg.evaluate(
                "() => document.querySelector('#previewpop').classList.contains('open')"
            ) is True
            assert pg.evaluate(
                "() => document.querySelector('#previewtitle').textContent") == "pic.png"
            pg.screenshot(path=os.path.join(PROOF, "r39_open_preview.png"))
            _close_preview(pg)
            # Right-click the row: "Show in folder" is on the menu
            # and still reaches the bridge.
            row = pg.query_selector('.frow[data-frow="pic.png"]')
            box = row.bounding_box()
            pg.mouse.click(box["x"] + 40, box["y"] + 20, button="right")
            pg.wait_for_timeout(500)
            menu = pg.evaluate("""() => {
              const m = document.querySelector('#ctxmenu');
              return {display: getComputedStyle(m).display,
                items: [...m.querySelectorAll('.ctxitem')].map(b => b.textContent)}; }""")
            assert menu["display"] == "block", menu
            assert menu["items"] == ["Show in folder"], menu
            pg.screenshot(path=os.path.join(PROOF, "r39_ctx_show_in_folder.png"))
            pg.evaluate("""() => { [...document.querySelectorAll('#ctxmenu .ctxitem')]
              .find(b => b.textContent === 'Show in folder').click(); }""")
            pg.wait_for_timeout(600)
            calls = pg.evaluate("() => window.__bridgeCalls")
            assert calls[-1] == ["reveal_file", "pic.png"], calls
        finally:
            browser.close()
    finally:
        pw.stop()


# ---- (3) ring: top of Shared Files, solid, X cancels ------------------
def test_3_ring_source():
    assert "bottom:84px" not in PAGE
    assert ".upfloat { display:none; position:fixed; left:50%; transform:translateX(-50%); top:96px;" in PAGE
    assert "background:var(--card); border:1px solid var(--line); border-radius:999px;" in PAGE
    assert ".upcancel" in PAGE
    assert 'id="upcancel"' in PAGE
    assert "xhr.onabort = () => { finish(false, true); };" in PAGE
    assert 'toast("Upload cancelled");' in PAGE
    assert "f.style.top = Math.max(8, Math.round(r.top - ph - 4))" in PAGE
    assert ".upring-num { fill:var(--txt);" in PAGE


def _ring_geom(pg):
    return pg.evaluate("""() => {
      const f = document.querySelector('#upfloat');
      const r = f.getBoundingClientRect();
      const col = document.querySelector('.col[data-col="files"]');
      const cr = col.getBoundingClientRect();
      const foot = document.querySelector('footer').getBoundingClientRect();
      const x = document.querySelector('#upcancel');
      const xr = x.getBoundingClientRect();
      const num = document.querySelector('#upringnum');
      return {show: f.classList.contains('show'),
        ring: {x: Math.round(r.x), y: Math.round(r.y),
               w: Math.round(r.width), h: Math.round(r.height),
               bottom: Math.round(r.bottom),
               cx: Math.round(r.x + r.width / 2)},
        bg: getComputedStyle(f).backgroundColor,
        border: getComputedStyle(f).borderTopColor,
        numFill: getComputedStyle(num).fill,
        nameColor: getComputedStyle(document.querySelector('#upfloatname')).color,
        xBtn: {w: Math.round(xr.width), h: Math.round(xr.height),
               bg: getComputedStyle(x).backgroundColor,
               color: getComputedStyle(x).color},
        files: {top: Math.round(cr.top), left: Math.round(cr.left),
                w: Math.round(cr.width),
                cx: Math.round(cr.left + cr.width / 2)},
        footerTop: Math.round(foot.top), vh: window.innerHeight};
    }""")


def _held_upload(pg, fname, size_mb=5):
    """Start an upload whose /api/upload request is held by a
    route handler, so the XHR stays in-flight for the test."""
    path = "/tmp/r39_upload_%s" % fname
    with open(path, "wb") as fh:
        fh.write(os.urandom(size_mb * 1024 * 1024))
    return path


def test_3_live_ring_top_and_cancel(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r39ring"})
    _make_fixtures(os.path.join(str(base), "r39ring"))
    pw = _playwright()
    try:
        for light in (False, True):
            browser, pg = _host_page(pw, port, light=light)
            try:
                pg.route("**/api/upload", lambda route: None)
                up = _held_upload(pg, "big_%s.bin" % ("light" if light else "dark"))
                pg.set_input_files("#picker", up)
                pg.wait_for_timeout(1200)
                m = _ring_geom(pg)
                assert m["show"] is True, m
                # Top of the Shared Files card: the pill's bottom
                # edge touches the card's top edge, centred on it.
                assert abs(m["ring"]["bottom"] - m["files"]["top"]) <= 6, m
                assert abs(m["ring"]["cx"] - m["files"]["cx"]) <= 15, m
                # Nowhere near the footer / slogan.
                assert m["ring"]["bottom"] < m["footerTop"] - 100, m
                assert m["ring"]["y"] < 130, m
                # SOLID: opaque themed background, theme number.
                assert _parse_rgb(m["bg"])[3] == 1.0, m
                if light:
                    assert m["bg"] == "rgb(255, 255, 255)", m
                    assert m["numFill"] == "rgb(15, 23, 42)", m
                    assert m["nameColor"] == "rgb(15, 23, 42)", m
                else:
                    assert m["bg"] == "rgb(18, 23, 42)", m
                    assert m["numFill"] == "rgb(238, 241, 248)", m
                    assert m["nameColor"] == "rgb(238, 241, 248)", m
                # The X button: 28x28, solid red, white x.
                assert m["xBtn"]["w"] == 28 and m["xBtn"]["h"] == 28, m
                assert m["xBtn"]["bg"] == "rgb(239, 68, 68)", m
                assert m["xBtn"]["color"] == "rgb(255, 255, 255)", m
                pg.screenshot(path=os.path.join(
                    PROOF, "r39_ring_%s.png" % ("light" if light else "dark")))
                # Cancel: toast, ring hides, queue empties, the
                # file is never saved, no "sent" toast.
                pg.click("#upcancel")
                pg.wait_for_timeout(400)
                assert pg.evaluate(
                    "() => document.querySelector('#toast').textContent") == "Upload cancelled"
                pg.wait_for_timeout(1600)
                m2 = _ring_geom(pg)
                assert m2["show"] is False, m2
                st = pg.evaluate("() => ({pending: window.__upQ.pending.length, cancelled: window.__upQ.cancelled})")
                assert st == {"pending": 0, "cancelled": True}, st
                names = pg.evaluate("() => fetch('/api/files').then(r => r.json()).then(fs => fs.map(f => f.name))")
                assert not any(n.startswith("big_") for n in names), names
                pg.unroute("**/api/upload")
            finally:
                browser.close()
    finally:
        pw.stop()


def test_3_live_ring_fallback_top_centre_guest(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r39ringg"})
    pw = _playwright()
    try:
        browser, ctx, pg, fwd = _guest_page(pw, port, 390, 844, light=False)
        try:
            # On the Send tab the files column is hidden, so the
            # ring falls back to top-centre.
            pg.route("**/api/upload", lambda route: None)
            up = _held_upload(pg, "guest.bin")
            pg.set_input_files("#mpicker", up)
            pg.wait_for_timeout(1200)
            m = pg.evaluate("""() => {
              const f = document.querySelector('#upfloat');
              const r = f.getBoundingClientRect();
              return {show: f.classList.contains('show'),
                top: Math.round(r.y), cx: Math.round(r.x + r.width / 2),
                vw: window.innerWidth}; }""")
            assert m["show"] is True, m
            assert m["top"] == 96, m
            assert abs(m["cx"] - m["vw"] / 2) <= 2, m
            pg.click("#upcancel")
            pg.wait_for_timeout(1800)
            assert pg.evaluate(
                "() => !document.querySelector('#upfloat').classList.contains('show')")
            pg.unroute("**/api/upload")
        finally:
            ctx.close()
            browser.close()
            fwd.close()
    finally:
        pw.stop()


# ---- (4) text preview selection ---------------------------------------
def _host_page_perms(pw, port, light=False):
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    ctx = browser.new_context(
        viewport={"width": 1280, "height": 800},
        permissions=["clipboard-read", "clipboard-write"])
    pg = ctx.new_page()
    pg.goto("http://127.0.0.1:%d/" % port)
    pg.wait_for_timeout(1800)
    if light:
        pg.evaluate("() => document.documentElement.classList.add('light')")
        pg.wait_for_timeout(300)
    return browser, ctx, pg


def test_4_text_preview_selectable(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r39sel"})
    _make_fixtures(os.path.join(str(base), "r39sel"))
    pw = _playwright()
    try:
        browser, ctx, pg = _host_page_perms(pw, port)
        try:
            # Text file: I-beam cursor, selectable, copyable.
            _open_preview(pg, "notes.txt")
            pg.wait_for_timeout(600)
            cur = pg.evaluate("""() => {
              const pre = document.querySelector('#previewbody pre');
              const cs = getComputedStyle(pre);
              return {cursor: cs.cursor, select: cs.userSelect}; }""")
            assert cur == {"cursor": "text", "select": "text"}, cur
            word = pg.evaluate("""() => {
              const pre = document.querySelector('#previewbody pre');
              const tn = pre.firstChild;
              const rng = document.createRange();
              rng.setStart(tn, 0); rng.setEnd(tn, 5);
              const r = rng.getBoundingClientRect();
              return {x: r.x + r.width / 2, y: r.y + r.height / 2}; }""")
            pg.mouse.dblclick(word["x"], word["y"])
            pg.wait_for_timeout(300)
            assert pg.evaluate(
                "() => window.getSelection().toString()") == "Hello"
            pg.keyboard.press("Control+c")
            pg.wait_for_timeout(400)
            assert pg.evaluate(
                "() => navigator.clipboard.readText()") == "Hello"
            pg.screenshot(path=os.path.join(PROOF, "r39_text_select.png"))
            _close_preview(pg)
            # Word: I-beam + selectable too.
            _open_preview(pg, "doc.docx")
            pg.wait_for_timeout(800)
            cur = pg.evaluate("""() => {
              const el = document.querySelector('#previewbody .docxview');
              const cs = getComputedStyle(el);
              return {cursor: cs.cursor, select: cs.userSelect}; }""")
            assert cur == {"cursor": "text", "select": "text"}, cur
            sel = pg.evaluate("""() => {
              const el = document.querySelector('#previewbody .docxview');
              const rng = document.createRange();
              rng.selectNodeContents(el);
              const s = window.getSelection();
              s.removeAllRanges(); s.addRange(rng);
              return s.toString(); }""")
            assert "Hello Word preview" in sel, sel
            _close_preview(pg)
            # Excel: I-beam over the table.
            _open_preview(pg, "sheet.xlsx")
            pg.wait_for_timeout(800)
            cur = pg.evaluate("""() => {
              const el = document.querySelector('#previewbody .xlsxview');
              const cs = getComputedStyle(el);
              return {cursor: cs.cursor, select: cs.userSelect}; }""")
            assert cur == {"cursor": "text", "select": "text"}, cur
            _close_preview(pg)
        finally:
            ctx.close()
            browser.close()
    finally:
        pw.stop()


# ---- (5) Starred white + Save centred + SAVE --------------------------
def _save_btn_geom(pg, sel):
    return pg.evaluate("""(sel) => {
      const b = document.querySelector(sel);
      const br = b.getBoundingClientRect();
      const svg = b.querySelector('svg');
      const sr = svg ? svg.getBoundingClientRect() : null;
      const tn = [...b.childNodes].find(n => n.nodeType === 3 && n.textContent.trim());
      let tr = null;
      if (tn) {
        const rng = document.createRange();
        rng.setStart(tn, tn.textContent.indexOf('S'));
        rng.setEnd(tn, tn.textContent.length);
        tr = rng.getBoundingClientRect();
      }
      return {label: b.textContent.trim(),
        display: getComputedStyle(b).display,
        btnCy: Math.round(br.y + br.height / 2),
        iconCy: sr ? Math.round(sr.y + sr.height / 2) : null,
        textCy: tr ? Math.round(tr.y + tr.height / 2) : null};
    }""", sel)


def test_5_starred_white_and_save_centred(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r39star"})
    client.j("POST", "/api/snippet", {"text": "Starred test note"})
    _make_fixtures(os.path.join(str(base), "r39star"))
    pw = _playwright()
    try:
        browser, pg = _host_page(pw, port)
        try:
            pg.wait_for_timeout(1500)
            # Starred: white text + white star on amber.
            m = pg.evaluate("""() => {
              const s = document.querySelector('#starfilter');
              const cs = getComputedStyle(s);
              const svg = s.querySelector('svg');
              return {display: cs.display, color: cs.color,
                bg: cs.backgroundColor,
                svgFill: getComputedStyle(svg).fill,
                label: s.textContent.trim()}; }""")
            assert m["display"] != "none", m
            assert m["color"] == "rgb(255, 255, 255)", m
            assert m["svgFill"] == "rgb(255, 255, 255)", m
            assert m["label"] == "Starred", m
            # Still white in the active (.on) state.
            pg.click("#starfilter")
            pg.wait_for_timeout(400)
            m2 = pg.evaluate("""() => {
              const s = document.querySelector('#starfilter');
              return {on: s.classList.contains('on'),
                color: getComputedStyle(s).color,
                svgFill: getComputedStyle(s.querySelector('svg')).fill}; }""")
            assert m2["on"] is True and m2["color"] == "rgb(255, 255, 255)", m2
            assert m2["svgFill"] == "rgb(255, 255, 255)", m2
            pg.click("#starfilter")
            pg.wait_for_timeout(300)
            pg.screenshot(path=os.path.join(PROOF, "r39_starred.png"))
            # Set Up Save: "SAVE", icon + text on the button centre.
            pg.click("#menubtn")
            pg.wait_for_timeout(500)
            pg.click("#sbedit")
            pg.wait_for_timeout(800)
            g = _save_btn_geom(pg, "#lkset")
            assert g["label"] == "SAVE", g
            assert g["display"] in ("flex", "inline-flex"), g
            assert abs(g["iconCy"] - g["btnCy"]) <= 2, g
            assert abs(g["textCy"] - g["btnCy"]) <= 2, g
            pg.screenshot(path=os.path.join(PROOF, "r39_save_setup.png"))
            pg.click("#lkcloseX")
            pg.wait_for_timeout(400)
            # Set Password Save: same treatment.
            pg.evaluate("() => openLockPopup()")
            pg.wait_for_timeout(500)
            g = _save_btn_geom(pg, "#lockpwsave")
            assert g["label"] == "SAVE", g
            assert g["display"] in ("flex", "inline-flex"), g
            assert abs(g["iconCy"] - g["btnCy"]) <= 2, g
            assert abs(g["textCy"] - g["btnCy"]) <= 2, g
            pg.evaluate("() => closeLockPopup()")
            # New Shared Text Save: same treatment.
            pg.click("#maddnote")
            pg.wait_for_timeout(500)
            g = _save_btn_geom(pg, "#msave")
            assert g["label"] == "SAVE", g
            assert g["display"] in ("flex", "inline-flex"), g
            assert abs(g["textCy"] - g["btnCy"]) <= 2, g
            pg.click("#mcancel")
            pg.wait_for_timeout(300)
        finally:
            browser.close()
    finally:
        pw.stop()


# ---- (6) Send Text Note: one centred unit -----------------------------
def test_6_send_text_note_centred(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r39send"})
    pw = _playwright()
    try:
        for (w, h) in [(390, 844), (360, 792)]:
            browser, ctx, pg, fwd = _guest_page(pw, port, w, h, light=False)
            try:
                m = pg.evaluate("""() => {
                  const b = document.querySelector('#msendsnippet');
                  const br = b.getBoundingClientRect();
                  const span = b.querySelector('.msend-in');
                  const sr = span.getBoundingClientRect();
                  const note = b.querySelector('.ic-note');
                  const nr = note.getBoundingClientRect();
                  const rng = document.createRange();
                  const tn = [...span.childNodes].find(n => n.nodeType === 3 && n.textContent.trim());
                  rng.selectNodeContents(tn);
                  const tr = rng.getBoundingClientRect();
                  const cs = getComputedStyle(b);
                  return {label: b.textContent.trim(),
                    btnCx: Math.round(br.x + br.width / 2),
                    spanCx: Math.round(sr.x + sr.width / 2),
                    spanL: Math.round(sr.x), btnL: Math.round(br.x),
                    gap: Math.round(tr.x - nr.right),
                    bg: cs.backgroundColor,
                    note: getComputedStyle(note).display,
                    bubble: getComputedStyle(b.querySelector('.ic-bubble')).display,
                    spanDisplay: getComputedStyle(span).display,
                    spanGap: getComputedStyle(span).gap};
                }""")
                assert m["label"] == "Send Text Note", m
                # Icon + text are ONE centred unit: the span's
                # centre is the button's centre, and the span
                # starts well clear of the button's left edge
                # (the 2.8.23 phone split put the icon at the
                # padding, ~14px from the edge).
                assert abs(m["spanCx"] - m["btnCx"]) <= 2, m
                assert m["spanL"] - m["btnL"] > 40, m
                assert 4 <= m["gap"] <= 10, m
                assert m["bg"] == "rgb(39, 127, 240)", m
                assert m["note"] not in (None, "none"), m
                assert m["bubble"] == "none", m
                # inline-flex blockifies to computed "flex" as a
                # flex item -- either value proves the span rule.
                assert m["spanDisplay"] in ("flex", "inline-flex"), m
                assert m["spanGap"] == "6px", m
                # The 2.8.22 fit still holds at 390x844.
                if (w, h) == (390, 844):
                    s = _measure_send_tab(pg)
                    assert s["mayScroll"] is False, s
                    assert s["btnVisiblePct"] == 1, s
                    assert s["gapBtnToTabs"] >= 8, s
                pg.screenshot(path=os.path.join(
                    PROOF, "r39_sendtext_%dx%d.png" % (w, h)))
            finally:
                ctx.close()
                browser.close()
                fwd.close()
        # .pcapp forced: same label + span, bubble back, note hidden.
        browser, ctx, pg, fwd = _guest_page(pw, port, 390, 844, light=False)
        try:
            pg.evaluate("() => document.documentElement.classList.add('pcapp')")
            pg.wait_for_timeout(300)
            m = pg.evaluate("""() => {
              const b = document.querySelector('#msendsnippet');
              return {label: b.textContent.trim(),
                bubble: getComputedStyle(b.querySelector('.ic-bubble')).display,
                note: getComputedStyle(b.querySelector('.ic-note')).display,
                span: !!b.querySelector('.msend-in')}; }""")
            assert m["label"] == "Send Text Note", m
            assert m["bubble"] not in (None, "none"), m
            assert m["note"] == "none", m
            assert m["span"] is True, m
        finally:
            ctx.close()
            browser.close()
            fwd.close()
    finally:
        pw.stop()


# ---- (7) tab slide transitions ----------------------------------------
def test_7_tab_slide(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r39tab"})
    pw = _playwright()
    try:
        browser, ctx, pg, fwd = _guest_page(pw, port, 390, 844, light=False)
        try:
            assert pg.evaluate(
                "() => getComputedStyle(document.querySelector('.board .col.active')).animationName"
            ) == "tabslidein"
            assert pg.evaluate(
                "() => getComputedStyle(document.querySelector('.board .col.active')).animationDuration"
            ) == "0.18s"
            # Forward: send -> notes slides in from the right.
            pg.click('.mtab[data-tab="notes"]')
            vals = _sample_transform(pg, '.col[data-col="notes"]')
            assert max(vals) > 2, vals
            assert pg.evaluate(
                "() => getComputedStyle(document.body).getPropertyValue('--tabdx')"
            ).strip() == "24px"
            pg.wait_for_timeout(200)
            assert pg.evaluate(
                "() => getComputedStyle(document.querySelector('.col[data-col=\"notes\"]')).transform"
            ) == "none"
            pg.screenshot(path=os.path.join(PROOF, "r39_tab_notes.png"))
            # Back: notes -> send slides in from the left.
            pg.click('.mtab[data-tab="send"]')
            vals = _sample_transform(pg, '.col[data-col="send"]')
            assert min(vals) < -2, vals
            assert pg.evaluate(
                "() => getComputedStyle(document.body).getPropertyValue('--tabdx')"
            ).strip() == "-24px"
            pg.wait_for_timeout(200)
            assert pg.evaluate(
                "() => getComputedStyle(document.querySelector('.col[data-col=\"send\"]')).transform"
            ) == "none"
            # Mid-slide proof shot: catch Files sliding in.
            pg.click('.mtab[data-tab="files"]')
            pg.wait_for_timeout(80)
            pg.screenshot(path=os.path.join(PROOF, "r39_tab_slide_mid.png"))
            pg.wait_for_timeout(300)
            assert pg.evaluate(
                "() => document.querySelector('.col[data-col=\"files\"]').classList.contains('active')"
            ) is True
        finally:
            ctx.close()
            browser.close()
            fwd.close()
    finally:
        pw.stop()


# ---- (8) Save slide-in -------------------------------------------------
def test_8_save_slide_in(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r39save"})
    _make_fixtures(os.path.join(str(base), "r39save"))
    pw = _playwright()
    try:
        browser, pg = _host_page(pw, port)
        try:
            # New Shared Text Save: the board slides in.
            pg.click("#maddnote")
            pg.wait_for_timeout(400)
            pg.fill("#mnote", "slide-in check")
            pg.click("#msave")
            vals = _sample_transform(pg, ".board")
            assert pg.evaluate(
                "() => document.querySelector('.board').classList.contains('boardslide')"
            ) is True
            assert pg.evaluate(
                "() => getComputedStyle(document.querySelector('.board')).animationName"
            ) == "boardslidein"
            assert pg.evaluate(
                "() => getComputedStyle(document.querySelector('.board')).animationDuration"
            ) == "0.18s"
            assert max(vals) > 2, vals
            pg.wait_for_timeout(200)
            assert pg.evaluate(
                "() => getComputedStyle(document.querySelector('.board')).transform"
            ) == "none"
            assert pg.evaluate(
                "() => document.querySelector('#toast').textContent"
            ) == "✅ Shared Text Added"
            # Set Up Save (host, keep current address): the board
            # slides in too.
            pg.click("#menubtn")
            pg.wait_for_timeout(500)
            pg.click("#sbedit")
            pg.wait_for_timeout(800)
            pg.click("#lkset")
            vals = _sample_transform(pg, ".board")
            assert pg.evaluate(
                "() => document.querySelector('.board').classList.contains('boardslide')"
            ) is True
            assert max(vals) > 2, vals
            pg.wait_for_timeout(300)
            toast = pg.evaluate(
                "() => document.querySelector('#toast').textContent")
            assert "Connected to r39save" in toast, toast
            pg.screenshot(path=os.path.join(PROOF, "r39_save_slide.png"))
        finally:
            browser.close()
    finally:
        pw.stop()
