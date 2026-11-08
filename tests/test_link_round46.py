"""v2.8.31 round (Essef Nov 6) -- web/desktop only.

Five items, nothing else:
1. "SAVED ON THIS PHONE" -> "SAVED ON THIS DEVICE" everywhere
   (web/desktop): every "on this phone" in the served page is now
   "on this device". Zero remaining, checked on the interpreted
   PAGE and on the rendered guest login button.
2. CHANGE FOLDER: root causes were (a) app.py set_directory called
   dropit._link_entry / _sanitise_link, which DO NOT EXIST -- every
   desktop Change Folder with an address active died with
   "unexpected error"; (b) /api/setlinkfolder refused while
   separate folders was OFF; (c) _address_folder ignored an
   explicit override while OFF; (d) the JS Change handlers
   retargeted to the Main Folder while OFF. All four fixed: a
   folder can now be chosen for an address regardless of the
   toggle, and "they land in <path>" shows the new folder.
3. WEB UPLOADING PILL slightly UP (6px), centred/aligned with the
   card, WEB ONLY (html:not(.pcapp) equivalent: the shift runs
   only when the page is NOT the PC app). PC pill byte-identical.
4. PILL FADES OUT after the last file -- no "0" state, no empty
   pill: _upRender never writes "0", _upHide animates opacity.
5. CUSTOM THEMED TITLE BAR, PC app ONLY, Design 1 (picked by
   Essef): dark navy bar (#12172a), 44px, thin blue underline
   (#277ff0), Drop logo + "Drop" left, minimise / maximise /
   close as full-height 46px strips right, close hovers red.
   Bridge methods in app.py (minimize/maximize/close/move +
   is_frameless/is_maximized); drag to move, double-click to
   maximise; the maximise button shows the restore-down
   overlapping-squares icon while maximised and the single
   square while normal (synced at boot, after every toggle,
   and on resize). Content shifts 44px below the bar. Framed
   fallback (frameless creation fails) keeps the native bar
   and hides the custom one.
"""
import ast
import json
import os
import re
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
import app as appmod  # noqa: E402
from test_link_folders import Client, _free_port  # noqa: E402
from test_link_round2 import server, _raw  # noqa: F401,E402
from test_link_round36 import _playwright, _host_page  # noqa: E402
from test_link_round37 import _host_page as _host_page37  # noqa: E402
from test_link_round44 import desktop_server, _desktop_page  # noqa: E402,F401

PAGE = D.PAGE
SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py"),
           encoding="utf-8").read()

PROOF = "/home/hatch/workspace/dropit-proof-round46"
os.makedirs(PROOF, exist_ok=True)

ADDR = "10-0-0-85-8000"  # Essef's actual address form (LAN IP:port dashed)


def test_version_is_2_8_31():
    assert D.VERSION == "2.8.31"


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
        p = os.path.join(PROOF, "r46_script_%d.js" % i)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(js)
        out = subprocess.run(["node", "--check", p],
                             capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr


# ---- (1) device wording -------------------------------------------------

def test_item1_no_on_this_phone():
    assert PAGE.lower().count("on this phone") == 0, \
        [m.start() for m in re.finditer("on this phone", PAGE, re.I)]
    assert "Saved on this device" in PAGE
    assert "file(s) saved on this device" in PAGE
    assert "Nothing saved on this device yet" in PAGE
    print("ITEM1: 'on this phone' occurrences in PAGE: 0; "
          "'on this device': %d" % PAGE.count("on this device"))


# ---- (2) Change Folder --------------------------------------------------

def test_item2_address_folder_override_wins_when_off():
    root = "/tmp/r46root"
    custom = "/tmp/r46custom"
    cfg = {"directory": root, "address_name": "myaddr",
           "separate_folders": False,
           "addresses": {"myaddr": {"folder": custom}}}
    assert D._address_folder(cfg) == custom
    cfg["addresses"] = {}
    assert D._address_folder(cfg) == root
    cfg["separate_folders"] = True
    assert D._address_folder(cfg) == os.path.join(root, "myaddr")
    print("ITEM2-UNIT: override wins when OFF; default root when OFF "
          "and no override; base/<addr> when ON")


def test_item2_app_set_directory_link_active(tmp_path, monkeypatch):
    # 2.8.30: set_directory with an address active ALWAYS failed
    # with {"ok": False, "error": "unexpected error"} -- it called
    # dropit._link_entry / _sanitise_link, which do not exist.
    home = tmp_path / "home"
    cfg = {"directory": str(tmp_path), "address_name": "myaddr",
           "addresses": {}}
    monkeypatch.setattr(appmod, "load_config", lambda: cfg)
    monkeypatch.setattr(appmod, "save_config", lambda c: None)
    api = appmod.Api(SimpleNamespace(directory=str(tmp_path)))
    dest = str(tmp_path / "newdest")
    r = api.set_directory(dest)
    assert r.get("ok") is True, r
    assert r["directory"] == dest
    assert cfg["addresses"]["myaddr"]["folder"] == dest
    assert os.path.isdir(dest)
    print("ITEM2-APP: set_directory with address active -> ok, "
          "folder=%s" % dest)


def test_item2_setlinkfolder_works_when_separate_off(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": ADDR})
    st, j = client.j("POST", "/api/separate_folders", {"enabled": False})
    assert st == 200 and j["ok"], j
    dest = os.path.join(str(base), "off-dest")
    st, j = client.j("POST", "/api/setlinkfolder", {"folder": dest})
    assert st == 200 and j.get("ok") is True, j  # 2.8.30: refusal error
    assert j["folder"] == dest, j
    st, files = client.upload("off-file.txt", b"lands in off dest\n")
    assert st == 200, files
    assert os.path.isfile(os.path.join(dest, "off-file.txt"))
    st, j = client.j("POST", "/api/separate_folders", {"enabled": True})
    assert st == 200 and j["ok"], j
    print("ITEM2-OFF: setlinkfolder with separate OFF -> ok, folder=%s, "
          "upload landed there" % dest)


def test_item2_live_change_folder_on(desktop_server):
    # End-to-end with Create Separate Folders ON: click Change in
    # the Files tab (prompt stubbed to the new path), expect NO
    # error, "they land in <path>" showing the new path, and a
    # file actually landing there. Uses desktop_server (what
    # app.py runs) -- only then is the Files-tab #changefolder
    # button rendered at all.
    client, base, port, srv, exe = desktop_server
    client.j("POST", "/api/setlink", {"name": ADDR})
    st, j = client.j("POST", "/api/separate_folders", {"enabled": True})
    assert st == 200 and j["ok"], j
    dest = os.path.join(str(base), "on-dest")
    pw = _playwright()
    try:
        browser, pg = _desktop_page(pw, port, exe, 1280, 800)
        try:
            pg.evaluate(
                "() => { window.__newfolder = %s; "
                "window.prompt = () => window.__newfolder; }"
                % json.dumps(dest))
            pg.click("#changefolder")
            pg.wait_for_timeout(1200)
            toast = pg.evaluate(
                "() => document.querySelector('#toast').textContent")
            land = pg.evaluate(
                "() => document.querySelector('#dirnamelabel').textContent")
            print("ITEM2-LIVE-ON: toast=%r land-in=%r" % (toast, land))
            assert "Save folder changed" in toast, toast
            assert "error" not in toast.lower(), toast
            assert land == dest, land
            pg.screenshot(path=os.path.join(PROOF, "r46_land_in.png"))
            up = os.path.join(str(base), "landed.txt")
            with open(up, "wb") as fh:
                fh.write(b"lands in on dest\n")
            pg.set_input_files("#picker", up)
            deadline = time.time() + 15
            landed = False
            while time.time() < deadline:
                if os.path.isfile(os.path.join(dest, "landed.txt")):
                    landed = True
                    break
                pg.wait_for_timeout(300)
            assert landed, os.listdir(dest) if os.path.isdir(dest) else "no dir"
            print("ITEM2-LIVE-ON: file landed in %s" % dest)
        finally:
            browser.close()
    finally:
        pw.stop()


# ---- (3)+(4) uploading pill ---------------------------------------------

def _pill_geom(pg):
    return pg.evaluate("""() => {
      const f = document.querySelector('#upfloat');
      const col = document.querySelector('.col[data-col="files"]');
      const btn = document.querySelector('#askbtn');
      const fr = f.getBoundingClientRect(), cr = col.getBoundingClientRect();
      const br = btn.getBoundingClientRect();
      return {show: f.classList.contains('show'),
        fading: f.classList.contains('fading'),
        top: Math.round(fr.top), h: Math.round(fr.height),
        cy: +(fr.top + fr.height / 2).toFixed(1),
        colTop: Math.round(cr.top),
        colCx: +(cr.left + cr.width / 2).toFixed(1),
        pillCx: +(fr.left + fr.width / 2).toFixed(1),
        btnCy: +(br.top + br.height / 2).toFixed(1),
        num: document.querySelector('#upringnum').textContent,
        name: document.querySelector('#upfloatname').textContent};
    }""")


def _throttle(pg, bps):
    cdp = pg.context.new_cdp_session(pg)
    cdp.send("Network.enable")
    cdp.send("Network.emulateNetworkConditions", {
        "offline": False, "latency": 50,
        "downloadThroughput": -1, "uploadThroughput": bps})
    return cdp


def test_item3_pill_web_higher_pc_unchanged(server):
    # Same viewport, same page: web pill centre sits 6px above the
    # search-button centre; PC pill centre sits exactly ON it
    # (2.8.28 snap, unchanged). Card-relative: web gap is 6px
    # bigger than PC gap; both stay centred on the files column.
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": ADDR})
    big = os.path.join(str(base), "pill-1mb.bin")
    with open(big, "wb") as fh:
        fh.write(os.urandom(1024 * 1024))
    pw = _playwright()
    try:
        # --- WEB (no bridge) ---
        browser, pg = _host_page37(pw, port, 1280, 800)
        try:
            _throttle(pg, 40 * 1024)
            pg.set_input_files("#picker", big)
            g_web = None
            deadline = time.time() + 20
            while time.time() < deadline:
                g_web = _pill_geom(pg)
                if g_web["show"] and g_web["num"] not in ("0", ""):
                    break
                pg.wait_for_timeout(200)
            assert g_web and g_web["show"], g_web
            pg.screenshot(path=os.path.join(PROOF, "r46_pill_web.png"))
            print("ITEM3-WEB: %s" % g_web)
        finally:
            browser.close()
        # --- PC (stub bridge, frameless) ---
        browser, pg = _pc_page(pw, port, 1280, 800, frameless=True)
        try:
            _throttle(pg, 40 * 1024)
            pg.set_input_files("#picker", big)
            g_pc = None
            deadline = time.time() + 20
            while time.time() < deadline:
                g_pc = _pill_geom(pg)
                if g_pc["show"] and g_pc["num"] not in ("0", ""):
                    break
                pg.wait_for_timeout(200)
            assert g_pc and g_pc["show"], g_pc
            pg.screenshot(path=os.path.join(PROOF, "r46_pill_pc.png"))
            print("ITEM3-PC: %s" % g_pc)
        finally:
            browser.close()
        # Web pill centre 6px above the button centre; PC exactly on it.
        assert abs((g_web["cy"] - g_web["btnCy"]) - (-6)) <= 1.5, (g_web, g_pc)
        assert abs(g_pc["cy"] - g_pc["btnCy"]) <= 1.5, (g_web, g_pc)
        # Card-relative gap: web is 6px bigger; both centred on the column.
        assert abs((g_web["colTop"] - g_web["top"]) -
                   (g_pc["colTop"] - g_pc["top"]) - 6) <= 1.5, (g_web, g_pc)
        assert abs(g_web["pillCx"] - g_web["colCx"]) <= 2, g_web
        assert abs(g_pc["pillCx"] - g_pc["colCx"]) <= 2, g_pc
        print("ITEM3: web pill 6px higher than PC (card-relative), "
              "both centred on the files column; PC snap unchanged")
    finally:
        pw.stop()


def test_item4_pill_fades_no_zero(server):
    # Upload 2 files, poll the ring number: it must NEVER read "0";
    # after the last file the pill must fade (fading class) and then
    # disappear (.show removed), with no empty pill shown.
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": ADDR})
    f1 = os.path.join(str(base), "fade-a.txt")
    f2 = os.path.join(str(base), "fade-b.txt")
    open(f1, "wb").write(b"first\n")
    open(f2, "wb").write(b"second\n")
    pw = _playwright()
    try:
        browser, pg = _host_page37(pw, port, 1280, 800)
        try:
            pg.set_input_files("#picker", [f1, f2])
            seen_nums, saw_fading, saw_gone = set(), False, False
            deadline = time.time() + 10
            while time.time() < deadline:
                g = _pill_geom(pg)
                if g["num"]:
                    seen_nums.add(g["num"])
                if g["fading"]:
                    saw_fading = True
                if not g["show"] and seen_nums:
                    saw_gone = True
                    break
                pg.wait_for_timeout(40)
            pg.screenshot(path=os.path.join(
                PROOF, "r46_fade_after_upload.png"))
            print("ITEM4: numbers seen=%r fading=%s gone=%s"
                  % (sorted(seen_nums), saw_fading, saw_gone))
            assert "0" not in seen_nums, seen_nums
            assert seen_nums <= {"1", "2"}, seen_nums
            assert saw_fading, "pill never entered fading state"
            assert saw_gone, "pill never disappeared after fade"
        finally:
            browser.close()
    finally:
        pw.stop()

# ---- (5) custom title bar -------------------------------------------------

_TB_STUB = """
window.__tbframeless = %s;
window.__tbcalls = [];
window.__tbmax = false;
window.pywebview = {api: {
  open_file: () => Promise.resolve(true),
  host_token: () => Promise.resolve(""),
  is_frameless: () => Promise.resolve({ok:true, frameless: window.__tbframeless}),
  is_maximized: () => Promise.resolve({ok:true, maximized: window.__tbmax}),
  minimize_window: () => { window.__tbcalls.push("minimize"); return Promise.resolve({ok:true}); },
  toggle_maximize_window: () => { window.__tbmax = !window.__tbmax; window.__tbcalls.push("toggle_max"); return Promise.resolve({ok:true, maximized: window.__tbmax}); },
  close_window: () => { window.__tbcalls.push("close"); return Promise.resolve({ok:true}); },
  move_window: (x, y) => { window.__tbcalls.push("move:" + Math.round(x) + "," + Math.round(y)); return Promise.resolve({ok:true}); },
}};
"""


def _pc_page(pw, port, width, height, frameless=True):
    """Host page with a recording fake pywebview bridge, as the real
    PC app injects it before page scripts run."""
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    ctx = browser.new_context(viewport={"width": width, "height": height})
    ctx.add_init_script(_TB_STUB % ("true" if frameless else "false"))
    pg = ctx.new_page()
    pg.goto("http://127.0.0.1:%d/" % port)
    pg.wait_for_function(
        "() => !document.querySelector('#guestlogin')"
        ".classList.contains('open')", timeout=10000)
    pg.wait_for_function(
        "() => typeof AUTH !== 'undefined' && AUTH.host", timeout=10000)
    pg.wait_for_timeout(900)
    return browser, pg


def _tb_state(pg):
    return pg.evaluate("""() => {
      const b = document.querySelector('#titlebar');
      const r = b.getBoundingClientRect();
      const cs = getComputedStyle(b);
      const top = document.querySelector('.topbar').getBoundingClientRect();
      const disp = (s) => getComputedStyle(document.querySelector(s)).display;
      return {visible: cs.display !== 'none', h: Math.round(r.height),
        top: Math.round(r.top), bg: cs.backgroundColor,
        underline: cs.borderBottomColor,
        underlineW: cs.borderBottomWidth,
        logo: !!document.querySelector('#titlebar .tb-logo'),
        name: document.querySelector('#titlebar .tb-name').textContent,
        topbarTop: Math.round(top.top),
        maxed: b.classList.contains('maxed'),
        maxDisp: disp('#titlebar .tb-ic-max'),
        restoreDisp: disp('#titlebar .tb-ic-restore'),
        maxTitle: document.querySelector('#tbmax').title,
        calls: window.__tbcalls ? window.__tbcalls.slice() : null};
    }""")


def test_item5_titlebar_pc(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": ADDR})
    pw = _playwright()
    try:
        browser, pg = _pc_page(pw, port, 1280, 800, frameless=True)
        try:
            pg.wait_for_function(
                "() => document.documentElement.classList"
                ".contains('frameless')", timeout=5000)
            pg.wait_for_timeout(300)
            st = _tb_state(pg)
            print("ITEM5-BAR: %s" % st)
            assert st["visible"] and st["h"] == 44 and st["top"] == 0, st
            assert st["bg"] == "rgb(18, 23, 42)", st  # Design 1 #12172a
            assert st["underline"] == "rgb(39, 127, 240)", st  # #277ff0
            assert st["underlineW"] == "1px", st
            assert st["name"] == "Drop" and st["logo"], st
            assert st["topbarTop"] == 70, st  # content shifted below bar
            assert st["maxed"] is False and st["restoreDisp"] == "none", st
            pg.screenshot(path=os.path.join(PROOF, "r46_titlebar_dark.png"))
            # Minimise button fires the bridge call.
            pg.click("#tbmin")
            pg.wait_for_timeout(300)
            assert "minimize" in _tb_state(pg)["calls"], _tb_state(pg)
            # Maximise: icon flips to restore-down, title follows.
            pg.click("#tbmax")
            pg.wait_for_timeout(300)
            st = _tb_state(pg)
            assert st["maxed"] is True, st
            assert st["maxDisp"] == "none" and st["restoreDisp"] == "block", st
            assert st["maxTitle"] == "Restore Down", st
            assert "toggle_max" in st["calls"], st
            pg.screenshot(path=os.path.join(PROOF, "r46_titlebar_maxed.png"))
            # Restore: single square back.
            pg.click("#tbmax")
            pg.wait_for_timeout(300)
            st = _tb_state(pg)
            assert st["maxed"] is False, st
            assert st["maxDisp"] != "none" and st["restoreDisp"] == "none", st
            assert st["maxTitle"] == "Maximize", st
            # Resize re-sync: an EXTERNAL maximise (Win+Up / snap)
            # must flip the icon too, via the resize listener.
            pg.evaluate("() => { window.__tbmax = true; "
                        "window.dispatchEvent(new Event('resize')); }")
            pg.wait_for_timeout(400)
            st = _tb_state(pg)
            assert st["maxed"] is True and st["restoreDisp"] == "block", st
            pg.evaluate("() => { window.__tbmax = false; "
                        "window.dispatchEvent(new Event('resize')); }")
            pg.wait_for_timeout(400)
            assert _tb_state(pg)["maxed"] is False
            # Drag the bar: mousedown at (200,22), move to (260,62).
            pg.mouse.move(200, 22)
            pg.mouse.down()
            pg.mouse.move(260, 62, steps=5)
            pg.mouse.up()
            pg.wait_for_timeout(300)
            calls = _tb_state(pg)["calls"]
            moves = [c for c in calls if c.startswith("move:")]
            print("ITEM5-DRAG calls: %s" % calls)
            assert moves, calls
            assert moves[-1] == "move:60,40", moves
            # Double-click the bar toggles maximise.
            pg.dblclick("#tbdrag")
            pg.wait_for_timeout(300)
            assert _tb_state(pg)["maxed"] is True
            # Close button fires the bridge call.
            pg.click("#tbclose")
            pg.wait_for_timeout(300)
            assert "close" in _tb_state(pg)["calls"], _tb_state(pg)
            # Light mode: same design, light colours, blue line kept.
            pg.evaluate("() => document.documentElement.classList"
                        ".add('light')")
            pg.wait_for_timeout(300)
            st = _tb_state(pg)
            assert st["bg"] == "rgb(255, 255, 255)", st
            assert st["underline"] == "rgb(39, 127, 240)", st
            pg.screenshot(path=os.path.join(PROOF, "r46_titlebar_light.png"))
            print("ITEM5: dark + light bars shot; buttons/drag/dblclick/"
                  "icon-sync all fired via the bridge")
        finally:
            browser.close()
        # Framed fallback (is_frameless false): native bar, custom hidden.
        browser, pg = _pc_page(pw, port, 1280, 800, frameless=False)
        try:
            pg.wait_for_timeout(1200)
            st = _tb_state(pg)
            assert st["visible"] is False, st
            assert not pg.evaluate(
                "() => document.documentElement.classList"
                ".contains('frameless')")
            assert pg.evaluate(
                "() => document.documentElement.classList"
                ".contains('pcapp')")
            print("ITEM5-FALLBACK: framed window hides the custom bar")
        finally:
            browser.close()
        # Plain web (no bridge): no bar at all.
        browser, pg = _host_page37(pw, port, 1280, 800)
        try:
            st = pg.evaluate(
                "() => getComputedStyle(document.querySelector"
                "('#titlebar')).display")
            assert st == "none", st
            print("ITEM5-WEB: no bridge, title bar hidden")
        finally:
            browser.close()
    finally:
        pw.stop()


def test_item5_bridge_methods_unit(monkeypatch):
    # app.py Api delegates to the real window verbs. Fake webview
    # with a recording window; prove each method calls the right
    # verb (and the no-window path reports an error, never raises).
    import types
    calls = []

    class FakeWin:
        def minimize(self):
            calls.append("minimize")

        def maximize(self):
            calls.append("maximize")

        def restore(self):
            calls.append("restore")

        def destroy(self):
            calls.append("destroy")

        def move(self, x, y):
            calls.append(("move", x, y))

    fake = types.ModuleType("webview")
    fake.windows = [FakeWin()]
    monkeypatch.setitem(sys.modules, "webview", fake)
    api = appmod.Api(SimpleNamespace(directory="/tmp"))
    assert api.is_frameless() == {"ok": True, "frameless": False}
    api.frameless = True
    assert api.is_frameless()["frameless"] is True
    assert api.minimize_window() == {"ok": True} and calls == ["minimize"]
    r = api.toggle_maximize_window()
    assert r == {"ok": True, "maximized": True} and calls[-1] == "maximize"
    assert api.is_maximized() == {"ok": True, "maximized": True}
    r = api.toggle_maximize_window()
    assert r == {"ok": True, "maximized": False} and calls[-1] == "restore"
    assert api.move_window(60, 40) == {"ok": True}
    assert calls[-1] == ("move", 60, 40)
    assert api.close_window() == {"ok": True} and calls[-1] == "destroy"
    fake.windows = []
    assert api.minimize_window()["ok"] is False
    assert api.close_window()["ok"] is False
    assert api.move_window(0, 0)["ok"] is False
    print("ITEM5-UNIT: bridge methods delegate to window verbs; "
          "no-window path returns errors, never raises")


# ---- (1) rendered --------------------------------------------------------

def test_item1_saved_button_rendered(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": ADDR})
    pw = _playwright()
    try:
        browser = pw.chromium.launch(args=["--no-proxy-server"])
        ctx = browser.new_context(viewport={"width": 390, "height": 844})
        pg = ctx.new_page()
        pg.goto("http://127.0.0.1:%d/" % port)
        pg.wait_for_timeout(1500)
        pg.evaluate("() => { document.querySelector('#guestlogin')"
                    ".classList.add('open'); }")
        pg.wait_for_timeout(500)
        txt = pg.evaluate(
            "() => document.querySelector('#gsavedbtn').textContent.trim()")
        assert txt == "Saved on this device", txt
        pg.screenshot(path=os.path.join(PROOF, "r46_saved_device.png"))
        print("ITEM1-RENDERED: guest login button=%r" % txt)
        browser.close()
    finally:
        pw.stop()
