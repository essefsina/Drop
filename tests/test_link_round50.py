"""v2.8.35 round (Essef Nov 6, ~11:22 PM - 11:42 PM PT) -- desktop
only, local test build only. SEVEN items, nothing else:

  (1) CARDS DO NOT FILL THE WINDOW HEIGHT (Essef: "WTF is this").
      ROOT CAUSE: the 2.8.34 item-8 half-height rule assumed FOUR
      340px columns wrapping to two rows at 721-1437px, but the
      Ask column is display:none on desktop, so only THREE
      columns ever show and they fit in ONE row from 1084px up
      (3x340 + 2x14 gap = 1048px). At 1084-1437px the cards were
      half-height (280px in an 800px window) with ~350px of empty
      black below them and the footer stranded at the bottom.
      FIX: the half-height rule now applies ONLY where the three
      columns really wrap to two rows (721-1083px: 2 + 1); from
      1084px up the base .col height calc(100dvh - 210px) fills
      the window again (cards end ~37px above the footer at
      every height). Files tab scroller untouched.
  (2) MENU BORDER ROUNDED TOP AND BOTTOM LIKE BEFORE: the
      sidebar menu's outer border is rounded at its top and
      bottom (top-right and bottom-right corners, 18px) on the
      frameless PC app. No resize, move, recolour or
      functionality change to the menu.
  (3) MENU MUST NOT COVER THE TOP BAR (reverses the menu half
      of 2.8.34 item 2): the sidebar sits BELOW the 44px title
      bar (top:44px, z-index back below the bar) so the bar
      (Drop logo + name, minimise / maximise / close) always
      stays visible and clickable above the open menu. The Set
      Up Your Addresses window stays ABOVE the bar (z 1700),
      as originally asked -- only the menu changes here.
  (4) REMOVE ADDRESS DIALOG: the Remove/Delete button was
      invisible in LIGHT mode (white-on-white: the light .btn
      rule beat the red .addrremsave rule) and the "Delete all
      files" checkbox was disabled whenever separate folders
      was OFF. FIX: the light rule now excludes .addrremsave;
      the checkbox is always checkable and, with separate
      folders OFF, deletes the shared Main Folder's files (the
      dialog says they are shared).
  (5) REMOVING AN ADDRESS (host only) disconnects from it and
      switches to the previous one (most-recent remaining
      history entry); removing the only address leaves no
      address selected.
  (6) SAVE PASSWORD checkbox + CREATE SEPARATE FOLDERS moved:
      separate-folders now sits under Folder For This Address
      with a small "i" ("Each address gets its own folder for
      its files."); its old spot in the password row is Save
      Password, which decides per address whether the password
      is stored -- saved shows hashed (dots) in the
      previous-addresses list, unsaved shows "no password".
      Web + APK login screens have the same checkbox.
  (7) CONNECTING POPUP: connecting shows a separate popup with
      a loading circle; success shows "Connected" + checkmark;
      failure shows "Unable to Connect — Check Device Address /
      Wi-Fi Name / Password" + warning icon. Replaces the inline
      connecting/disconnected status text on the login/connect
      screen; the Devices pill is untouched.
"""
import ast
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
from test_link_round2 import server  # noqa: F401,E402
from test_link_round46 import _pc_page  # noqa: E402

PAGE = D.PAGE
SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py"),
           encoding="utf-8").read()

PROOF = "/home/hatch/workspace/dropit-proof-round50"
os.makedirs(PROOF, exist_ok=True)

MEASURE = """() => {
  const cols = [...document.querySelectorAll('.board .col')]
    .filter(c => getComputedStyle(c).display !== 'none')
    .map(c => { const r = c.getBoundingClientRect();
      return {col: c.dataset.col, top: Math.round(r.top),
              bottom: Math.round(r.bottom), h: Math.round(r.height)}; });
  const f = document.querySelector('footer').getBoundingClientRect();
  return {cols, footerTop: Math.round(f.top),
    vh: window.innerHeight,
    docH: document.documentElement.scrollHeight,
    scrollH: document.documentElement.scrollHeight > window.innerHeight,
    scrollW: document.documentElement.scrollWidth > window.innerWidth};
}"""

MENU = """() => {
  const sb = document.querySelector('#sidebar');
  const cs = getComputedStyle(sb);
  const r = sb.getBoundingClientRect();
  const bar = document.querySelector('#titlebar').getBoundingClientRect();
  const btns = [...document.querySelectorAll('#titlebar .tb-btn')]
    .map(b => { const br = b.getBoundingClientRect();
      const el = document.elementFromPoint(br.x + br.width / 2,
                                           br.y + br.height / 2);
      return el === b || b.contains(el); });
  const mid = document.elementFromPoint(r.x + r.width / 2, 22);
  return {sbTop: Math.round(r.top), barBottom: Math.round(bar.bottom),
    radiusTR: cs.borderTopRightRadius,
    radiusBR: cs.borderBottomRightRadius,
    zIndex: cs.zIndex,
    barZ: getComputedStyle(document.querySelector('#titlebar')).zIndex,
    titlebarHitAt22: mid ? (mid.id || mid.className || mid.tagName) : null,
    btns};
}"""


def test_version_is_2_8_35():
    assert D.VERSION == "2.8.35", D.VERSION


def test_page_valid():
    """Interpreted PAGE: both scripts node --check clean, zero lone
    surrogates, UTF-8 clean (pre-existing SyntaxWarning at line
    1226 left alone)."""
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
    import re
    scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
    assert len(scripts) == 2, len(scripts)
    for i, s in enumerate(scripts):
        p = os.path.join(PROOF, "r50_script%d.js" % i)
        open(p, "w", encoding="utf-8").write(s)
        r = subprocess.run(["node", "--check", p],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_height_markers():
    """Half-height only where the three columns really wrap
    (721-1083px); base full height everywhere else."""
    assert ("@media (min-width:721px) and (max-width:1083px){\n"
            "    html.pcapp .col { height:calc((100dvh - 240px)/2);"
            " min-height:190px; }" in PAGE)
    assert "@media (min-width:721px) and (max-width:1437px)" not in PAGE
    assert ("height:calc(100vh - 210px); height:calc(100dvh - 210px);"
            in PAGE)


def test_menu_markers():
    assert ("html.pcapp.frameless #sidebar { top:44px; z-index:80;"
            " border-radius:0 18px 18px 0; }" in PAGE)
    assert "html.pcapp.frameless .lockwrap { z-index:1700; }" in PAGE


def _sizes():
    # (width, height, expect_single_row)
    return [(1280, 800, True), (1280, 1000, True), (1440, 900, True),
            (1600, 900, True), (1920, 1080, True), (1000, 800, False)]


def test_cards_fill_window(server):
    client, base, proc, port, home = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        for w, h, single in _sizes():
            browser, pg = _pc_page(pw, port, w, h, frameless=True)
            try:
                pg.wait_for_timeout(400)
                m = pg.evaluate(MEASURE)
                assert m["cols"], (w, h, m)
                assert not m["scrollH"], (w, h, m)
                assert not m["scrollW"], (w, h, m)
                tops = {c["top"] for c in m["cols"]}
                if single:
                    # One row: all three tops equal, bottoms near footer.
                    assert len(tops) == 1, (w, h, m)
                    gap = m["footerTop"] - max(c["bottom"]
                                               for c in m["cols"])
                    assert 20 <= gap <= 60, (w, h, m)
                else:
                    # 1000x800 wraps 2+1: two rows, last row near footer.
                    assert len(tops) == 2, (w, h, m)
                    gap = m["footerTop"] - max(c["bottom"]
                                               for c in m["cols"])
                    assert 20 <= gap <= 60, (w, h, m)
                pg.screenshot(path="%s/r50_fill_%dx%d.png" % (PROOF, w, h))
                print("FILL %dx%d: heights=%s gap=%d" % (
                    w, h, [c["h"] for c in m["cols"]], gap))
            finally:
                browser.close()


def test_menu_below_bar_rounded(server):
    client, base, proc, port, home = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        for theme in ("dark", "light"):
            browser, pg = _pc_page(pw, port, 1280, 800, frameless=True)
            try:
                if theme == "light":
                    pg.evaluate("() => document.documentElement"
                                ".classList.add('light')")
                pg.click("#menubtn")
                pg.wait_for_timeout(600)
                mm = pg.evaluate(MENU)
                # Menu starts exactly where the title bar ends.
                assert mm["sbTop"] == 44, mm
                assert mm["barBottom"] == 44, mm
                # Menu below the bar in stacking order.
                assert int(mm["zIndex"]) < int(mm["barZ"]), mm
                # Rounded top and bottom of the menu border.
                assert mm["radiusTR"] == "18px", mm
                assert mm["radiusBR"] == "18px", mm
                # Title bar is what a pointer hits above the menu,
                # and all three window buttons are clickable.
                assert mm["titlebarHitAt22"] in ("tbdrag", "titlebar",
                                                 "tb-btn"), mm
                assert mm["btns"] == [True, True, True], mm
                pg.screenshot(path="%s/r50_menu_%s.png" % (PROOF, theme))
                print("MENU %s: %s" % (theme, mm))
            finally:
                browser.close()


# --- v2.8.35 items 4-7 ---

APK_DIR = "/home/hatch/workspace/dropit-android"
KOTLIN = open(os.path.join(
    APK_DIR, "app/src/main/java/com/dropit/app/MainActivity.kt"),
    encoding="utf-8").read()
LOGIN_XML = open(os.path.join(
    APK_DIR, "app/src/main/res/layout/page_login.xml"),
    encoding="utf-8").read()


def test_remove_dialog_markers():
    """(4) Light-mode rule excludes .addrremsave (no more
    white-on-white Delete button); the files checkbox is never
    disabled; the hint no longer claims the files stay."""
    assert (":not(.addrremsave)" in PAGE)
    assert "html.light .btn:not(.primary):not(.dangergrad):not(.openf)" \
        ":not(.changef):not(.pvdl):not(.addrremsave)" in PAGE
    assert "ff.disabled = false" in PAGE
    assert "ff.disabled = shared" not in PAGE
    assert ("Files live in the Main Folder shared by all addresses."
            in PAGE)
    assert "so they stay" not in PAGE
    # Server: separate-folders OFF deletes the shared Main
    # Folder's files instead of refusing.
    assert "separate folders OFF -- files are" in SRC


def test_remove_switches_to_previous(server):
    """(4)+(5) Live: remove current B with files ticked -> B's
    folder files gone, host switched to previous A; remove the
    only address -> none selected; separate-folders OFF -> the
    shared Main Folder's files are deleted."""
    client, base, proc, port, home = server
    assert client.j("POST", "/api/setlink", {"name": "r50a"})[0] == 200
    assert client.j("POST", "/api/setlink", {"name": "r50b"})[0] == 200
    st, j = client.j("GET", "/api/authstate")
    assert j["address_name"] == "r50b", j
    bfolder = base / "r50b"
    assert bfolder.is_dir(), list(base.iterdir())
    (bfolder / "bfile.txt").write_text("b")
    st, j = client.j("POST", "/api/address/remove",
                     {"key": "r50b", "delete_notes": False,
                      "delete_files": True})
    assert st == 200 and j["ok"], j
    assert j["files_deleted"] is True, j
    assert not (bfolder / "bfile.txt").exists()
    assert j["switched_to"] == "r50a", j
    st, j = client.j("GET", "/api/authstate")
    assert j["address_name"] == "r50a", j
    st, j = client.j("POST", "/api/address/remove",
                     {"key": "r50a", "delete_notes": False,
                      "delete_files": False})
    assert st == 200 and j["ok"], j
    assert j["switched_to"] == "", j
    st, j = client.j("GET", "/api/authstate")
    assert not j["address_name"], j
    # Separate folders OFF: ticked files box deletes the shared
    # Main Folder's files.
    assert client.j("POST", "/api/separate_folders",
                    {"enabled": False})[0] == 200
    assert client.j("POST", "/api/setlink", {"name": "r50c"})[0] == 200
    (base / "shared.txt").write_text("s")
    st, j = client.j("POST", "/api/address/remove",
                     {"key": "r50c", "delete_notes": False,
                      "delete_files": True})
    assert st == 200 and j["ok"] and j["files_deleted"] is True, j
    assert not (base / "shared.txt").exists()


def test_save_password_markers():
    """(6) Save Password checkbox in the password row (host Set
    Up + guest Connect card), Create Separate Folders moved
    under the folder field with its "i", login-page checkbox,
    and the SAVE/login gating that makes the checkbox decide
    whether the password is stored."""
    # Set Up: Save Password lives in the password row; the
    # separate-folders row moved out of it, under the folder
    # field (HTML order: folder col, then password row, then
    # Permissions -- the ids below are unique to the HTML).
    assert 'id="lksavepwchk"' in PAGE
    assert 'id="lksavepwlabel"' in PAGE
    assert PAGE.index('id="lkseplabel"') < PAGE.index('id="lkpw"')
    assert PAGE.index('id="lksepinfo"') > PAGE.index('id="lkseplabel"')
    assert PAGE.index('id="lksepinfo"') < PAGE.index('id="lkpw"')
    assert PAGE.index('id="lksavepwchk"') > PAGE.index('id="lkpw"')
    assert PAGE.index('id="lksavepwchk"') < PAGE.index('id="lkpermlabel"')
    assert "Each address gets its own folder for its files." in PAGE
    # Host SAVE: unchecked clears the stored password.
    assert "if(!savePw) body.password" in PAGE
    # Guest login page checkbox + gating on connect.
    assert 'id="gloginsavechk"' in PAGE
    assert "const _savePw = " in PAGE
    assert "if(_savePw) saveGuestAddressPw" in PAGE
    assert "removeGuestSavedAddressPw(cj.display_address" in PAGE
    # The list already shows hashed / "no password" from
    # has_password -- unchanged, driven by the checkbox now.
    assert '(e.has_password ? "••••••" : "No password")' in PAGE
    # APK: login checkbox + gating + popup helper.
    assert "loginSavePassword" in KOTLIN
    assert "savePassword" in KOTLIN
    assert "Save password" in LOGIN_XML
    assert "loginSavePassword" in LOGIN_XML


def test_save_password_server(server):
    """(6) Live server contract the checkbox drives: a stored
    password shows hashed in the list; an empty-password save
    (unchecked Save Password) clears it; per-address
    independence holds."""
    client, base, proc, port, home = server

    def has_pw(key):
        st, j = client.j("GET", "/api/linkhistory")
        assert st == 200 and j["ok"], j
        ent = {e["key"]: e for e in j["entries"]}
        assert key in ent, j
        return ent[key]["has_password"]

    assert client.j("POST", "/api/setlink",
                    {"name": "r50pw", "password": "pw123"})[0] == 200
    assert has_pw("r50pw") is True
    assert client.j("POST", "/api/setlink",
                    {"name": "r50pw", "password": ""})[0] == 200
    assert has_pw("r50pw") is False
    assert client.j("POST", "/api/setlink",
                    {"name": "r50pw2", "password": "pw456"})[0] == 200
    assert has_pw("r50pw2") is True
    assert has_pw("r50pw") is False


def test_conn_popup_markers():
    """(7) Popup HTML + the three states + wiring on every
    connect path (login page, guest Connect card, mobile
    Connect button); APK helper + failure text."""
    assert 'id="connpop"' in PAGE
    assert 'id="conntext"' in PAGE
    assert "Unable to Connect — Check Device Address / Wi-Fi Name / Password" in PAGE
    assert 'showConnPop("connecting")' in PAGE
    assert 'showConnPop("connected")' in PAGE
    assert 'showConnPop("failed")' in PAGE
    assert ".connspin" in PAGE
    assert "function showConnPop(state)" in PAGE
    assert "function hideConnPop()" in PAGE
    # APK: same three states on the login page.
    assert "showConnDialog" in KOTLIN
    assert "Unable to Connect — Check Device Address" in KOTLIN
    assert os.path.isfile(os.path.join(
        APK_DIR, "app/src/main/res/drawable/ic_warning.xml"))


CONN = """() => {
  const pop = document.querySelector('#connpop');
  return {open: pop ? pop.classList.contains('open') : false,
    text: (document.querySelector('#conntext') || {}).textContent || ''};
}"""


def _guest_login_page(pw, port, width, height):
    """Guest page for a LOCKED address: same _Fwd trick as
    test_link_round36 (server sees a non-loopback guest), but
    waits for the login page to OPEN instead of staying shut."""
    from test_link_round34 import _Fwd
    fwd = _Fwd(port)
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    ctx = browser.new_context(viewport={"width": width, "height": height})
    pg = ctx.new_page()
    pg.goto("http://127.0.0.3:%d/" % fwd.port)
    pg.wait_for_function(
        "() => document.querySelector('#guestlogin')"
        ".classList.contains('open')", timeout=15000)
    pg.wait_for_timeout(500)
    return browser, ctx, pg, fwd


def test_conn_popup_live(server):
    """(7) Live: wrong password -> failure popup with the exact
    message; right password -> "Connected" popup."""
    client, base, proc, port, home = server
    assert client.j("POST", "/api/setlink",
                    {"name": "r50conn", "password": "rightpw"})[0] == 200
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, ctx, pg, fwd = _guest_login_page(pw, port, 1280, 800)
        try:
            pg.fill("#gloginlink", "r50conn")
            pg.fill("#gloginpw", "wrongpw")
            pg.click("#gloginbtn")
            pg.wait_for_function(
                "() => document.querySelector('#connpop')"
                ".classList.contains('open')", timeout=10000)
            pg.wait_for_timeout(300)
            m = pg.evaluate(CONN)
            assert m["open"] and "Unable to Connect" in m["text"], m
            assert "Check Device Address" in m["text"], m
            pg.screenshot(path="%s/r50_conn_failed.png" % PROOF)
            print("CONN FAILED: %s" % m)
            pg.click("#connclose")
            pg.wait_for_timeout(300)
            pg.fill("#gloginpw", "rightpw")
            pg.click("#gloginbtn")
            pg.wait_for_function(
                "() => (document.querySelector('#conntext') || {})"
                ".textContent === 'Connected'", timeout=10000)
            m = pg.evaluate(CONN)
            assert m["open"] and m["text"] == "Connected", m
            pg.screenshot(path="%s/r50_conn_ok.png" % PROOF)
            print("CONN OK: %s" % m)
        finally:
            browser.close()
            fwd.close()
