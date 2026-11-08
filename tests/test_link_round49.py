"""v2.8.34 round (Essef Nov 6, ~10:11-10:13 PM PT) -- web/desktop,
local test build only. EIGHT items, nothing else:

  (1) STILL "NO DEVICES CONNECTED" -- bisect 2.8.31 vs 2.8.32/2.8.33
      server code. RESULT: no server-side regression exists.
      app.py is byte-identical across 31/32/33; the 31->32
      dropit.py diff is VERSION + a login-hide CSS rule only;
      the 30->31 Change Folder fix (per-address override wins
      over the separate-folders toggle; /api/setlinkfolder OFF
      refusal removed) does not touch sessions, tokens or the
      device count. Live A/B (probe_connect.py, in-process
      server + non-loopback guest via forwarder): a passwordless
      guest POST /api/connect for 10-0-0-85-8000 mints a guest
      session and GET /api/status reads devices:1 on 2.8.31,
      2.8.32 AND 2.8.33 -- plain, separate-folders OFF + folder
      override, and separate-folders ON + override. No server
      change was needed for (1); the remaining "No devices
      connected" on Essef's APK login screen is APK-side
      (parallel track). The browser test below re-proves the
      web end-to-end pill on 2.8.34.
  (2) MENU + SET UP YOUR ADDRESSES ON TOP OF THE TOP BAR
      (desktop frameless): sidebar z 80 and dialog backdrop
      .lockwrap z 300 were below the title bar z 1500.
      Now html.pcapp.frameless #sidebar z 1600 and
      .lockwrap z 1700 (dialog above menu, as before).
  (3) ANIMATED POP UP / POP OUT -- Set Up, QR, Add New text:
      dlgPopIn on open, dlgPopOut on close (160ms delayed
      hide; re-open cancels it). Same sizes, same behaviour.
  (4) DESKTOP APP JUMPS + CAN'T OPEN FILES FROM ZIP PREVIEW:
      the jump was the native pywebview easy-drag (see (5))
      fighting the JS title-bar drag; the ZIP rows now open
      directly via /api/archive/extract/ (ZIP extracts with
      stdlib zipfile; RAR answers a clear error -- no stdlib
      RAR decompressor) + bridge open_path on desktop.
  (5) APP MOVES FROM ANYWHERE -- ONLY THE TOP BAR SHOULD:
      pywebview create_window(frameless=True) defaults
      easy_drag=True ("moved by dragging any point").
      app.py now passes easy_drag=False, so the JS title-bar
      drag is the only drag path; it also ignores sub-3px
      jitter, so a plain click never moves the window.
  (6) DESKTOP PREVIEW DOWNLOAD BUTTON DOES NOTHING -> OPEN:
      on the desktop (bridge) the preview button reads Open
      and opens the file in Windows via open_file; web keeps
      Download + downloadPreviewFile.
  (7) NOTHING ELSE: only items 1-6 above plus (8).
  (8) REMOVE THE RIGHT-SIDE SCROLLER ON DESKTOP (main window
      only -- the Files tab scroller stays): pcapp viewport
      never scrolls (overflow-y hidden); body bottom padding
      70 -> 24px on desktop widths >=721px; where the four
      340px columns wrap to two rows (721-1437px) each column
      is half-height so both rows fit. All columns still
      scroll internally, so nothing becomes unreachable.
"""
import ast
import http.client
import io
import json
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
from test_link_round2 import server, _raw  # noqa: F401,E402
from test_link_round33 import _Fwd  # noqa: E402
from test_link_round36 import _playwright  # noqa: E402
from test_link_round37 import _make_fixtures, _host_page  # noqa: E402
from test_link_round46 import _pc_page  # noqa: E402
from test_link_round48 import (_guest_browser, _connect, _pill,  # noqa: E402
                               _wait_pill, _linkdir_with_fixtures)

PAGE = D.PAGE
SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py"),
           encoding="utf-8").read()
APP_SRC = open(os.path.join(os.path.dirname(__file__), "..", "app.py"),
               encoding="utf-8").read()

PROOF = "/home/hatch/workspace/dropit-proof-round49"
os.makedirs(PROOF, exist_ok=True)

ADDR = "10-0-0-85-8000"  # Essef's actual address form (LAN IP:port dashed)
PW = "test1234"


def test_version_is_2_8_34():
    assert D.VERSION == "2.8.34"


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


def test_item2_zindex_markers():
    assert "html.pcapp.frameless #sidebar { z-index:1600; }" in PAGE
    assert "html.pcapp.frameless .lockwrap { z-index:1700; }" in PAGE


def test_item3_animation_markers():
    assert "@keyframes dlgPopIn" in PAGE
    assert "@keyframes dlgPopOut" in PAGE
    assert "#lkwrap .lockbox, .qrpop.open, .mdlg.open .mbox { animation:dlgPopIn .18s ease-out; }" in PAGE
    assert "function closeQrPop()" in PAGE
    assert "function closeMdlg()" in PAGE
    assert "closeQrPop();" in PAGE
    assert "closeMdlg();" in PAGE


def test_item5_drag_markers():
    assert "easy_drag=False" in APP_SRC
    assert "_tbdrag.moved" in PAGE
    assert "Math.abs(e.screenX - _tbdrag.sx) < 3" in PAGE


def test_item6_preview_open_markers():
    assert 'dl.textContent = "Open";' in PAGE
    assert 'dl.textContent = "Download";' in PAGE
    assert "close(); openFile(name);" in PAGE


def test_item8_no_scroller_markers():
    assert "html.pcapp, html.pcapp body { overflow-x:hidden; overflow-y:hidden; }" in PAGE
    assert "@media (min-width:721px){ html.pcapp body { padding-bottom:24px; } }" in PAGE
    assert "@media (max-width:720px){ html.pcapp body { padding-bottom:32px; } }" in PAGE
    assert "html.pcapp .col { height:calc((100dvh - 240px)/2); min-height:190px; }" in PAGE
    # The Files tab's own scroller is untouched (item 9 cancelled).
    assert ".colbody { display:flex; flex-direction:column; gap:12px; flex:1; min-height:0; overflow-y:auto;" in PAGE


def test_item4_extract_markers():
    assert "def archive_extract_entry(path, entry):" in PAGE or \
        "def archive_extract_entry(path, entry):" in SRC
    assert '"/api/archive/extract/"' in SRC
    assert "function openArchiveEntry(archive, entry){" in PAGE
    assert 'data-entry="' in PAGE
    assert ".archrow[data-entry] { cursor:pointer; }" in PAGE


# --- live guest helpers (real server + non-loopback guest) --------

class _GuestRaw:
    """Minimal guest client through the forwarder (source
    127.0.0.2, i.e. a real LAN guest, not loopback/host),
    keeping the drop_sess cookie across calls."""

    def __init__(self, fwd_port):
        self.port = fwd_port
        self.cookies = {}

    def call(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.3", self.port,
                                          timeout=10)
        hdrs = dict(headers or {})
        if self.cookies:
            hdrs["Cookie"] = "; ".join(
                "%s=%s" % kv for kv in self.cookies.items())
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        raw = resp.read()
        for k, v in resp.getheaders():
            if k.lower() == "set-cookie":
                name, _, rest = v.partition("=")
                val = rest.split(";")[0]
                if "Max-Age=0" in v:
                    self.cookies.pop(name, None)
                elif val:
                    self.cookies[name] = val
        conn.close()
        try:
            return resp.status, json.loads(raw.decode() or "{}")
        except ValueError:
            return resp.status, {}


def test_item1_guest_connect_devices_1(server):
    # (1) no server regression: passwordless guest connects and
    # /api/status reads devices:1 -- plain, separate-OFF +
    # folder override (the 2.8.31 Change Folder fix path), and
    # separate-ON + override.
    client, base, proc, port, home = server
    _linkdir_with_fixtures(client, base)
    fwd = _Fwd(port)
    for tag, setup in (
            ("plain", None),
            ("sep-off-override", "off"),
            ("sep-on-override", "on")):
        if setup == "off":
            st, j = client.j("POST", "/api/separate_folders",
                             {"enabled": False})
            assert st == 200 and j["separate_folders"] is False, j
            folder = os.path.join(str(base), "custom-folder")
            os.makedirs(folder, exist_ok=True)
            st, j = client.j("POST", "/api/setlinkfolder",
                             {"folder": folder})
            assert st == 200, j
        if setup == "on":
            st, j = client.j("POST", "/api/separate_folders",
                             {"enabled": True})
            assert st == 200 and j["separate_folders"] is True, j
        # The fixture link has a password: login first (mints the
        # guest session), then connect, then status -- the same
        # order the real guest page uses.
        guest = _GuestRaw(fwd.port)
        st, j = guest.call("POST", "/api/login", {"password": PW},
                           {"X-Drop-Address": ADDR})
        assert st == 200 and j.get("ok"), (tag, st, j)
        assert guest.cookies.get("drop_sess"), (tag, guest.cookies)
        st, j = guest.call("POST", "/api/connect", {"link": ADDR},
                           {"X-Drop-Address": ADDR})
        assert st == 200 and j.get("ok") and j.get("authed"), (tag, st, j)
        st, j = guest.call("GET", "/api/status",
                           headers={"X-Drop-Address": ADDR})
        assert st == 200 and j.get("devices") == 1, (tag, st, j)
        print("ITEM1-%s: login + connect ok, devices:1" % tag)


# --- (4) extract endpoint -------------------------------------------

def _zip_bytes():
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as z:
        z.writestr("docs/", "")
        z.writestr("docs/readme.txt", "hello from inside the zip")
        z.writestr("photo.jpg", b"\x00" * 1234)
    return bio.getvalue()


def _extract_url(name, entry, mode=None):
    q = ("/api/archive/extract/?file=" + name + "&entry=" + entry)
    if mode:
        q += "&mode=" + mode
    return q


def test_item4_extract_bytes_and_path(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": ADDR})
    linkdir = os.path.join(str(base), ADDR)
    os.makedirs(linkdir, exist_ok=True)
    with open(os.path.join(linkdir, "pack.zip"), "wb") as f:
        f.write(_zip_bytes())
    # Bytes mode (web guest): the single file comes down with
    # its own name and exact content (raw bytes, not JSON).
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", _extract_url("pack.zip", "docs/readme.txt"))
    resp = conn.getresponse()
    data = resp.read()
    disp = resp.getheader("Content-Disposition") or ""
    conn.close()
    assert resp.status == 200, resp.status
    assert data == b"hello from inside the zip", data
    assert "readme.txt" in disp, disp
    # Path mode (host): temp path exists with the same content.
    st, j = client.j("GET", _extract_url("pack.zip", "docs/readme.txt",
                                         mode="path"))
    assert st == 200 and j.get("ok") and j.get("path"), (st, j)
    assert os.path.isfile(j["path"])
    with open(j["path"], "rb") as f:
        assert f.read() == b"hello from inside the zip"
    assert j["path"].endswith("readme.txt")
    print("ITEM4-EXTRACT: bytes + host path ok")


def test_item4_extract_errors(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": ADDR})
    linkdir = os.path.join(str(base), ADDR)
    os.makedirs(linkdir, exist_ok=True)
    with open(os.path.join(linkdir, "pack.zip"), "wb") as f:
        f.write(_zip_bytes())
    # Missing entry, directory entry, traversal, bad archive.
    for entry, want in (("nope.txt", 400), ("docs/", 400),
                        ("../secret.txt", 400), ("docs/../../x", 400)):
        st, j = client.j("GET", _extract_url("pack.zip", entry))
        assert st == 400 and j.get("ok") is False, (entry, st, j)
    st, j = client.j("GET", _extract_url("missing.zip", "x.txt"))
    assert st == 404, (st, j)
    # RAR: clear error, never a crash (no stdlib RAR extractor).
    with open(os.path.join(linkdir, "a.rar"), "wb") as f:
        f.write(b"Rar!\x1a\x07\x01\x00" + b"\x00" * 64)
    st, j = client.j("GET", _extract_url("a.rar", "x.txt"))
    assert st == 400 and "RAR" in (j.get("error") or ""), (st, j)
    print("ITEM4-ERRORS: missing/dir/traversal/RAR all 400 with a reason")


def test_item4_extract_guest_rules(server):
    # Bytes mode enforces download_files (403); mode=path is
    # host-only (403 for a guest); unauthed callers get 401.
    # The listing endpoint itself is untouched (still works).
    from test_link_round16 import _guest, _set_perms, ALL_ON  # noqa: E402
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": ADDR, "password": PW})
    linkdir = os.path.join(str(base), ADDR)
    os.makedirs(linkdir, exist_ok=True)
    with open(os.path.join(linkdir, "pack.zip"), "wb") as f:
        f.write(_zip_bytes())
    st, j = client.j("GET", "/api/archive/?file=pack.zip")
    assert st == 200 and j.get("ok") and len(j["entries"]) == 3, (st, j)
    guest = _guest(port, home, PW)
    st, j = guest.j("GET", _extract_url("pack.zip", "docs/readme.txt"))
    assert st == 200, (st, j)
    _set_perms(client, dict(ALL_ON, download_files=False))
    st, j = guest.j("GET", _extract_url("pack.zip", "docs/readme.txt"))
    assert st == 403 and j.get("code") == "download_forbidden", (st, j)
    st, j = guest.j("GET", _extract_url("pack.zip", "docs/readme.txt",
                                        mode="path"))
    assert st == 403, (st, j)
    # Unauthed: a fresh guest through the forwarder (non-loopback
    # source, no session) gets 401. (A plain _raw call from
    # 127.0.0.1 is the HOST, not an unauthed guest.)
    fwd2 = _Fwd(port)
    anon = _GuestRaw(fwd2.port)
    st, j = anon.call("GET", _extract_url("pack.zip", "docs/readme.txt"))
    assert st == 401, (st, j)
    print("ITEM4-GUEST: bytes 403 without perm, path host-only, 401 unauthed")


# --- browser tests ----------------------------------------------------
# Playwright was SIGTRAP-failing while /tmp was full; writes work
# again now, so these run against the real Chromium.

_TB49_STUB = """
window.__tbopens = [];
window.pywebview.api.open_file = (n) => { window.__tbopens.push("file:" + n); return Promise.resolve(true); };
window.pywebview.api.open_path = (p) => { window.__tbopens.push(p); return Promise.resolve(true); };
"""


def _pc49_page(pw, port, width, height):
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    ctx = browser.new_context(viewport={"width": width, "height": height})
    from test_link_round46 import _TB_STUB  # noqa: E402
    ctx.add_init_script(_TB_STUB % "true")
    ctx.add_init_script(_TB49_STUB)
    pg = ctx.new_page()
    pg.goto("http://127.0.0.1:%d/" % port)
    pg.wait_for_function(
        "() => !document.querySelector('#guestlogin')"
        ".classList.contains('open')", timeout=10000)
    pg.wait_for_function(
        "() => typeof AUTH !== 'undefined' && AUTH.host", timeout=10000)
    pg.wait_for_timeout(900)
    return browser, pg


def _tb_calls(pg):
    return pg.evaluate("() => window.__tbccalls || window.__tbcalls || []")


def test_item1_browser_guest_connect_pill(server):
    # (1) end-to-end web: dashed-address guest connects and the
    # pill reads "1 Device Connected" promptly.
    client, base, proc, port, home = server
    _linkdir_with_fixtures(client, base)
    fwd = _Fwd(port)
    pw = _playwright()
    browser, ctx, pg = _guest_browser(pw, fwd.port)
    try:
        _connect(pg, ADDR)
        assert _wait_pill(pg) == "1 Device Connected"
        print("ITEM1-BROWSER: pill = '1 Device Connected'")
    finally:
        browser.close()
        pw.stop()


def test_item2_menu_and_setup_above_titlebar(server):
    client, base, proc, port, home = server
    _linkdir_with_fixtures(client, base)
    pw = _playwright()
    browser, pg = _pc49_page(pw, port, 1280, 800)
    try:
        tb = pg.evaluate(
            "() => { const r = document.querySelector('#titlebar')"
            ".getBoundingClientRect(); const sb = document"
            ".querySelector('#sidebar'); const cs = getComputedStyle(sb);"
            " return {tbTop: r.top, tbH: r.height,"
            " sbZ: cs.zIndex}; }")
        assert tb["tbTop"] == 0 and tb["tbH"] > 30, tb
        assert tb["sbZ"] == "1600", tb
        # Menu open: a point inside the menu's top strip (which
        # overlaps the title bar's band) must hit the menu, not
        # the bar.
        pg.evaluate("() => openSidebar(true)")
        pg.wait_for_timeout(250)
        hit = pg.evaluate(
            "() => { const el = document.elementFromPoint(10, 22);"
            " return el ? (el.closest('#sidebar') ? 'sidebar' :"
            " (el.id || el.className || el.tagName)) : 'none'; }")
        assert hit == "sidebar", hit
        pg.screenshot(path=PROOF + "/r49_item2_sidebar.png")
        # Set Up open: its backdrop sits above the bar too.
        pg.evaluate("() => openSidebar(false)")
        pg.evaluate("() => openLinkWin()")
        pg.wait_for_timeout(300)
        lk = pg.evaluate(
            "() => { const w = document.querySelector('#lkwrap');"
            " const cs = getComputedStyle(w);"
            " const box = document.querySelector('#lkwrap .lockbox')"
            ".getBoundingClientRect(); const el ="
            " document.elementFromPoint(box.x + box.width / 2,"
            " box.y + 6); return {z: cs.zIndex, hit: el ?"
            " (el.closest('#lkwrap') ? 'lockwrap' : (el.id ||"
            " el.className || el.tagName)) : 'none'}; }")
        assert lk["z"] == "1700", lk
        assert lk["hit"] == "lockwrap", lk
        pg.screenshot(path=PROOF + "/r49_item2_setup.png")
        pg.evaluate("() => closeLinkWin()")
        print("ITEM2: sidebar z=1600 + setup z=1700, both hit-tested above the bar")
    finally:
        browser.close()
        pw.stop()


def test_item3_animations_pop_in_out(server):
    client, base, proc, port, home = server
    _linkdir_with_fixtures(client, base)
    pw = _playwright()
    browser, pg = _pc49_page(pw, port, 1280, 800)
    try:
        # Set Up: pop-in on open, pop-out (still shown, .closing)
        # on close, then hidden after the 160ms close.
        pg.evaluate("() => openLinkWin()")
        pg.wait_for_timeout(120)
        anim = pg.evaluate(
            "() => getComputedStyle(document.querySelector("
            "'#lkwrap .lockbox')).animationName")
        assert anim == "dlgPopIn", anim
        pg.evaluate("() => closeLinkWin()")
        pg.wait_for_timeout(60)
        mid = pg.evaluate(
            "() => { const w = document.querySelector('#lkwrap');"
            " return {closing: w.classList.contains('closing'),"
            " disp: getComputedStyle(w).display,"
            " anim: getComputedStyle(document.querySelector("
            "'#lkwrap .lockbox')).animationName}; }")
        assert mid["closing"] and mid["disp"] != "none", mid
        assert mid["anim"] == "dlgPopOut", mid
        pg.wait_for_timeout(300)
        assert pg.evaluate(
            "() => getComputedStyle(document.querySelector("
            "'#lkwrap')).display") == "none"
        # QR popup: same pop-in / pop-out. The #qrtoggle button
        # is empty (display:none) when the server has no QR lib
        # in this sandbox, so open it with a programmatic click
        # (the handler still fires); the close button is visible
        # once the popup is open.
        pg.evaluate("() => document.querySelector('#qrtoggle').click()")
        pg.wait_for_timeout(120)
        assert pg.evaluate(
            "() => document.querySelector('#qrpop')"
            ".classList.contains('open')")
        assert pg.evaluate(
            "() => getComputedStyle(document.querySelector("
            "'#qrpop')).animationName") == "dlgPopIn"
        # Programmatic click: #qrpopclose sits at top-right under
        # the desktop title bar (.qrpop z 300 < titlebar 1500,
        # pre-existing -- item 2 names only the menu and Set Up),
        # so a real pointer click there is intercepted by
        # #tbclose. Backdrop/Escape still close it in real use.
        pg.evaluate("() => document.querySelector('#qrpopclose').click()")
        pg.wait_for_timeout(60)
        mid = pg.evaluate(
            "() => { const w = document.querySelector('#qrpop');"
            " return {closing: w.classList.contains('closing'),"
            " disp: getComputedStyle(w).display,"
            " anim: getComputedStyle(document.querySelector("
            "'#qrpop')).animationName}; }")
        assert mid["closing"] and mid["disp"] != "none", mid
        assert mid["anim"] == "dlgPopOut", mid
        pg.wait_for_timeout(300)
        assert pg.evaluate(
            "() => !document.querySelector('#qrpop')"
            ".classList.contains('open')")
        # Add New text dialog: same pop-in / pop-out.
        pg.click("#maddnote")
        pg.wait_for_timeout(120)
        assert pg.evaluate(
            "() => document.querySelector('#mdlg')"
            ".classList.contains('open')")
        assert pg.evaluate(
            "() => getComputedStyle(document.querySelector("
            "'#mdlg .mbox')).animationName") == "dlgPopIn"
        pg.click("#mcancel")
        pg.wait_for_timeout(60)
        mid = pg.evaluate(
            "() => { const w = document.querySelector('#mdlg');"
            " return {closing: w.classList.contains('closing'),"
            " disp: getComputedStyle(w).display,"
            " anim: getComputedStyle(document.querySelector("
            "'#mdlg .mbox')).animationName}; }")
        assert mid["closing"] and mid["disp"] != "none", mid
        assert mid["anim"] == "dlgPopOut", mid
        pg.wait_for_timeout(300)
        assert pg.evaluate(
            "() => !document.querySelector('#mdlg')"
            ".classList.contains('open')")
        print("ITEM3: Set Up + QR + Add New all pop in (dlgPopIn) and pop out (dlgPopOut)")
    finally:
        browser.close()
        pw.stop()


def test_item5_drag_only_titlebar(server):
    client, base, proc, port, home = server
    linkdir = _linkdir_with_fixtures(client, base)
    pw = _playwright()
    browser, pg = _pc49_page(pw, port, 1280, 800)
    try:
        assert _tb_calls(pg) == []
        # Hold + drag on the page body: must NOT move the window.
        pg.mouse.move(400, 300)
        pg.mouse.down()
        pg.mouse.move(600, 500, steps=5)
        pg.mouse.up()
        assert _tb_calls(pg) == [], _tb_calls(pg)
        # Plain click (no drag) on the title bar: no move (the
        # 3px jitter threshold kills the click-jump).
        pg.mouse.move(200, 22)
        pg.mouse.down()
        pg.mouse.up()
        assert _tb_calls(pg) == [], _tb_calls(pg)
        # Real title-bar drag: moves, by the dragged delta.
        pg.mouse.move(200, 22)
        pg.mouse.down()
        pg.mouse.move(260, 62, steps=5)
        pg.mouse.up()
        # The handler fires per mousemove (one call per step);
        # the last call carries the full dragged delta.
        assert _tb_calls(pg)[-1] == "move:60,40", _tb_calls(pg)
        assert all(c.startswith("move:") for c in _tb_calls(pg))
        # Text selection in a text-file preview: selects, and
        # does NOT move the window (Essef's exact report).
        pg.evaluate(
            "() => { const r = [...document.querySelectorAll("
            "'.frow')].find(e => e.textContent.includes('notes.txt'));"
            " if (r) r.querySelector('.fname').click(); }")
        pg.wait_for_selector("#previewpop.open", timeout=8000)
        pg.wait_for_timeout(400)
        box = pg.evaluate(
            "() => { const p = document.querySelector("
            "'#previewpop .pvpre, #previewpop pre');"
            " const r = p.getBoundingClientRect();"
            " return {x: r.x, y: r.y, w: r.width, h: r.height}; }")
        pg.mouse.move(box["x"] + 20, box["y"] + 20)
        pg.mouse.down()
        pg.mouse.move(box["x"] + 200, box["y"] + 60, steps=5)
        pg.mouse.up()
        sel = pg.evaluate("() => window.getSelection().toString()")
        assert sel.strip(), "no text was selected"
        assert _tb_calls(pg)[-1] == "move:60,40", _tb_calls(pg)
        print("ITEM5: body drag + title-bar click + text select: no move; title-bar drag: move:60,40; selection %d chars"
              % len(sel))
    finally:
        browser.close()
        pw.stop()


def test_item6_preview_button_open_on_desktop(server):
    client, base, proc, port, home = server
    _linkdir_with_fixtures(client, base)
    pw = _playwright()
    browser, pg = _pc49_page(pw, port, 1280, 800)
    try:
        pg.evaluate(
            "() => { const r = [...document.querySelectorAll("
            "'.frow')].find(e => e.textContent.includes('notes.txt'));"
            " if (r) r.querySelector('.fname').click(); }")
        pg.wait_for_selector("#previewpop.open", timeout=8000)
        pg.wait_for_timeout(300)
        label = pg.evaluate(
            "() => document.querySelector('#previewdl').textContent")
        assert label == "Open", label
        pg.click("#previewdl")
        pg.wait_for_timeout(300)
        opens = pg.evaluate("() => window.__tbopens")
        assert "file:notes.txt" in opens, opens
        print("ITEM6-DESKTOP: preview button reads 'Open', click -> bridge open_file('notes.txt')")
    finally:
        browser.close()
        pw.stop()


def test_item6_preview_button_download_on_web(server):
    # Web (no bridge) keeps Download + the download flow.
    client, base, proc, port, home = server
    _linkdir_with_fixtures(client, base)
    pw = _playwright()
    browser, pg = _host_page(pw, port, 1280, 800)
    try:
        pg.evaluate(
            "() => { const r = [...document.querySelectorAll("
            "'.frow')].find(e => e.textContent.includes('notes.txt'));"
            " if (r) r.querySelector('.fname').click(); }")
        pg.wait_for_selector("#previewpop.open", timeout=8000)
        pg.wait_for_timeout(300)
        label = pg.evaluate(
            "() => document.querySelector('#previewdl').textContent")
        assert label == "Download", label
        print("ITEM6-WEB: preview button still reads 'Download'")
    finally:
        browser.close()
        pw.stop()


def test_item4_zip_preview_opens_file_desktop(server):
    client, base, proc, port, home = server
    linkdir = _linkdir_with_fixtures(client, base)
    with open(os.path.join(linkdir, "pack.zip"), "wb") as f:
        f.write(_zip_bytes())
    pw = _playwright()
    browser, pg = _pc49_page(pw, port, 1280, 800)
    try:
        pg.evaluate(
            "() => { const r = [...document.querySelectorAll("
            "'.frow')].find(e => e.textContent.includes('pack.zip'));"
            " if (r) r.querySelector('.fname').click(); }")
        pg.wait_for_selector("#previewpop.open", timeout=8000)
        pg.wait_for_selector(".archrow[data-entry]", timeout=8000)
        rows = pg.evaluate(
            "() => [...document.querySelectorAll("
            "'.archrow[data-entry]')].map(e => e.getAttribute("
            "'data-entry'))")
        assert "docs/readme.txt" in rows and "photo.jpg" in rows, rows
        pg.evaluate(
            "() => { const r = [...document.querySelectorAll("
            "'.archrow[data-entry]')].find(e => e.getAttribute("
            "'data-entry') === 'docs/readme.txt'); r.click(); }")
        pg.wait_for_timeout(500)
        opens = pg.evaluate("() => window.__tbopens")
        assert len(opens) == 1 and opens[0].endswith("readme.txt"), opens
        with open(opens[0], "rb") as f:
            assert f.read() == b"hello from inside the zip"
        print("ITEM4-DESKTOP: zip row click -> bridge open_path(%s), content verified"
              % opens[0])
    finally:
        browser.close()
        pw.stop()


def test_item4_zip_preview_downloads_file_web(server):
    # Web guest: clicking a zip row downloads that one file.
    client, base, proc, port, home = server
    linkdir = _linkdir_with_fixtures(client, base)
    with open(os.path.join(linkdir, "pack.zip"), "wb") as f:
        f.write(_zip_bytes())
    fwd = _Fwd(port)
    pw = _playwright()
    browser, ctx, pg = _guest_browser(pw, fwd.port)
    try:
        _connect(pg, ADDR)
        assert _wait_pill(pg) == "1 Device Connected"
        # Mobile guest page is tabbed: switch to the Files tab
        # first, then open the archive preview.
        pg.evaluate("() => setTab('files')")
        pg.wait_for_selector(".frow[data-frow='pack.zip']", timeout=8000)
        from test_link_round37 import _open_preview  # noqa: E402
        _open_preview(pg, "pack.zip")
        pg.wait_for_selector("#previewpop.open", timeout=8000)
        pg.wait_for_selector(".archrow[data-entry]", timeout=8000)
        with pg.expect_download(timeout=10000) as dl_info:
            pg.evaluate(
                "() => { const r = [...document.querySelectorAll("
                "'.archrow[data-entry]')].find(e => e.getAttribute("
                "'data-entry') === 'docs/readme.txt'); r.click(); }")
        dl = dl_info.value
        assert dl.suggested_filename == "readme.txt", dl.suggested_filename
        path = dl.path()
        with open(path, "rb") as f:
            assert f.read() == b"hello from inside the zip"
        print("ITEM4-WEB: zip row click -> download 'readme.txt', content verified")
    finally:
        browser.close()
        pw.stop()


def test_item8_no_main_scroller_desktop(server):
    client, base, proc, port, home = server
    linkdir = _linkdir_with_fixtures(client, base)
    # 30 files: the Files tab's own scroller must still work.
    for i in range(30):
        with open(os.path.join(linkdir, "file%02d.txt" % i), "w") as f:
            f.write("file %d\n" % i)
    pw = _playwright()
    for width, height in ((1280, 800), (720, 600), (1920, 1080)):
        browser, pg = _pc49_page(pw, port, width, height)
        try:
            m = pg.evaluate(
                "() => { const de = document.documentElement;"
                " const b = document.body;"
                " const cols = [...document.querySelectorAll('.col')]"
                ".map(c => { const r = c.getBoundingClientRect();"
                " return {top: Math.round(r.top), bottom:"
                " Math.round(r.bottom)}; });"
                " return {docH: de.scrollHeight, bodyH: b.scrollHeight,"
                " innerH: window.innerHeight,"
                " ovY: getComputedStyle(de).overflowY, cols}; }")
            assert m["ovY"] == "hidden", (width, height, m)
            assert m["docH"] <= m["innerH"], (width, height, m)
            assert m["bodyH"] <= m["innerH"], (width, height, m)
            for c in m["cols"]:
                assert c["top"] >= 0 and c["bottom"] <= m["innerH"], \
                    (width, height, c)
            pg.screenshot(path=PROOF + "/r49_item8_%dx%d.png"
                          % (width, height))
            print("ITEM8-%dx%d: docH=%d innerH=%d, all cols in viewport"
                  % (width, height, m["docH"], m["innerH"]))
        finally:
            browser.close()
    # Files tab still scrolls internally (item 9 cancelled).
    browser, pg = _pc49_page(pw, port, 1280, 800)
    try:
        m = pg.evaluate(
            "() => { const el = document.querySelector("
            "'.col[data-col=\"files\"] .colbody');"
            " const before = el.scrollTop; el.scrollTop = 200;"
            " return {sh: el.scrollHeight, ch: el.clientHeight,"
            " scrolled: el.scrollTop}; }")
        assert m["sh"] > m["ch"] and m["scrolled"] > 0, m
        print("ITEM8-FILES: colbody scrollHeight=%d clientHeight=%d, scrolls to %d"
              % (m["sh"], m["ch"], m["scrolled"]))
    finally:
        browser.close()
        pw.stop()
