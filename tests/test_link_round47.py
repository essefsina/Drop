"""v2.8.32 round (Essef Nov 6) -- web/desktop + APK.

ONE item, nothing else:
  "why is the pill on login screen?" -- the bottom pill tabs
  (Upload / Notes / Files / Search) and the top bar (hamburger)
  were visible on the guest LOGIN screen (page 1), Essef's photo
  image-56.png. The login page must show ONLY the login form
  (logo, slogan, address + optional password, Connect, Saved on
  this device, theme toggle); the pill tabs belong to page 2 and
  must appear only after a successful connect.

Root cause (plain words): the login page hid the tabs, top bar
and board ONLY with one-shot inline styles set inside
showGuestLogin(). The tabs are visible by default in the mobile
CSS, so the hide held only as long as that one call's inline
style stuck -- any path that displayed the login form without
that hide having taken effect left the pill tabs (and the
hamburger) sitting on the login screen, exactly as photographed.
The JS hide was verified working in the four guest flows the
sandbox can run (fresh load, connect, logout, reload, locked +
open addresses), so the exact trigger on Essef's phone could not
be reproduced here -- but the structural weakness is real.

Fix (web/desktop, dropit.py PAGE): the rule is now structural
CSS -- body:has(.guestlogin.open) hides .mtabs, .topbar, .board
and footer with display:none !important. The moment the login
page is open the tabs cannot render, whatever JS ran before;
they return the moment it closes. The old JS hides stay as well
(defence in depth, not a replacement).

Fix (APK 2.6.106): the bottom tab bar container gets the id
tabBar; showLoginPage hides it explicitly (it already hid its
parent mainPage) and goToMainPage + the two other page-2 entry
points (offline-Saved restore, offline Saved from the login
button) show it again. No behaviour change on any traced path --
hardening of the same invariant.
"""
import ast
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
from test_link_round2 import server, _raw  # noqa: F401,E402
from test_link_round36 import _playwright  # noqa: E402
from test_link_round44 import desktop_server, _desktop_page  # noqa: E402,F401

PAGE = D.PAGE
SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py"),
           encoding="utf-8").read()

PROOF = "/home/hatch/workspace/dropit-proof-round47"
os.makedirs(PROOF, exist_ok=True)

ADDR = "10-0-0-85-8000"  # Essef's actual address form (LAN IP:port dashed)

GUEST_AUTH = {
    "ok": True, "host": False, "authed": False, "locked": True,
    "guest_locked": False, "address_name": ADDR, "link_name": ADDR,
    "sessionless_open": False,
    "permissions": {"download_files": True, "upload_files": True,
                    "delete_files": False, "add_notes": True,
                    "delete_notes": False, "star_notes": True},
}

VIS = """() => {
  const q = (s) => { const e = document.querySelector(s);
    if (!e) return {display: 'missing', box: null};
    const r = e.getBoundingClientRect();
    return {display: getComputedStyle(e).display,
            box: [Math.round(r.x), Math.round(r.y),
                  Math.round(r.width), Math.round(r.height)]}; };
  return {loginOpen: document.querySelector('#guestlogin')
              .classList.contains('open'),
          mtabs: q('.mtabs'), topbar: q('.topbar'), board: q('.board')};
}"""


def test_version_is_2_8_32():
    assert D.VERSION == "2.8.32"


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


def test_login_hides_tabs_rule_in_page():
    # The structural rule itself must be in the served page.
    assert "body:has(.guestlogin.open) .mtabs" in PAGE
    assert "body:has(.guestlogin.open) .topbar" in PAGE
    assert "body:has(.guestlogin.open) .board" in PAGE
    assert "display:none !important" in PAGE


def _guest_page(pw, port, width, height):
    """Mobile guest page: /api/authstate intercepted to report a
    locked-address guest (host False, authed False), so the real
    boot routing opens the login page exactly as on Essef's phone."""
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    ctx = browser.new_context(viewport={"width": width, "height": height},
                              is_mobile=True, has_touch=True)
    pg = ctx.new_page()

    def _auth(route):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(GUEST_AUTH))

    pg.route("**/api/authstate", _auth)
    pg.goto("http://127.0.0.1:%d/" % port)
    pg.wait_for_function(
        "() => document.querySelector('#guestlogin')"
        ".classList.contains('open')", timeout=10000)
    pg.wait_for_timeout(400)
    return browser, ctx, pg


def test_login_screen_has_no_pill_tabs_mobile(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": ADDR, "password": "test1234"})
    pw = _playwright()
    try:
        browser, ctx, pg = _guest_page(pw, port, 390, 844)
        st = pg.evaluate(VIS)
        assert st["loginOpen"] is True, st
        for key in ("mtabs", "topbar", "board"):
            assert st[key]["display"] == "none", (key, st)
            assert st[key]["box"][2] == 0 and st[key]["box"][3] == 0, \
                (key, st)
        pg.screenshot(path=os.path.join(PROOF, "r47_login_no_tabs.png"))
        # Tabs return the moment the login closes (connect path):
        # showGuestMain is the real function checkAuth calls.
        pg.evaluate("() => showGuestMain()")
        pg.wait_for_timeout(400)
        st2 = pg.evaluate(VIS)
        assert st2["loginOpen"] is False, st2
        assert st2["mtabs"]["display"] == "flex", st2
        assert st2["mtabs"]["box"][3] > 0, st2
        assert st2["topbar"]["display"] == "flex", st2
        # And back to login: hidden again.
        pg.evaluate("() => showGuestLogin()")
        pg.wait_for_timeout(400)
        st3 = pg.evaluate(VIS)
        assert st3["loginOpen"] is True, st3
        assert st3["mtabs"]["display"] == "none", st3
        assert st3["topbar"]["display"] == "none", st3
        print("LOGIN-TABS: hidden on login, shown on main, hidden again")
        browser.close()
    finally:
        pw.stop()


def test_login_screen_has_no_pill_tabs_desktop_width(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": ADDR, "password": "test1234"})
    pw = _playwright()
    try:
        browser, ctx, pg = _guest_page(pw, port, 1280, 800)
        st = pg.evaluate(VIS)
        assert st["loginOpen"] is True, st
        for key in ("mtabs", "topbar", "board"):
            assert st[key]["display"] == "none", (key, st)
            assert st[key]["box"][2] == 0 and st[key]["box"][3] == 0, \
                (key, st)
        pg.screenshot(path=os.path.join(PROOF, "r47_login_no_tabs_1280.png"))
        print("LOGIN-TABS-1280: hidden on login at desktop width")
        browser.close()
    finally:
        pw.stop()


def test_login_open_forced_has_no_pill_tabs(server):
    # Belt and braces: even if the login form is opened by any
    # other path (direct class add, as round46 did), the CSS rule
    # alone hides the tabs -- the JS hide is not load-bearing.
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": ADDR})
    pw = _playwright()
    try:
        browser = pw.chromium.launch(args=["--no-proxy-server"])
        ctx = browser.new_context(viewport={"width": 390, "height": 844},
                                  is_mobile=True, has_touch=True)
        pg = ctx.new_page()
        pg.goto("http://127.0.0.1:%d/" % port)
        pg.wait_for_timeout(1200)
        # Main page showing (loopback == host): force the login open
        # WITHOUT calling showGuestLogin, i.e. without its JS hide.
        pg.evaluate("() => document.querySelector('#guestlogin')"
                    ".classList.add('open')")
        pg.wait_for_timeout(300)
        st = pg.evaluate(VIS)
        assert st["loginOpen"] is True, st
        assert st["mtabs"]["display"] == "none", st
        assert st["topbar"]["display"] == "none", st
        assert st["board"]["display"] == "none", st
        print("LOGIN-TABS-FORCED: CSS alone hides tabs/topbar/board")
        browser.close()
    finally:
        pw.stop()


def test_pc_app_login_open_has_no_pill_tabs(desktop_server):
    # Same rule on the PC app surface (desktop=True server, what
    # app.py runs): force the login open without the JS hide and
    # the CSS must still hide tabs/topbar/board. The PC app never
    # shows the guest login in normal use (bridge == host), but
    # the rule must hold there too.
    client, base, port, srv, exe = desktop_server
    client.j("POST", "/api/setlink", {"name": ADDR})
    pw = _playwright()
    try:
        browser, pg = _desktop_page(pw, port, exe, 1280, 800)
        pg.evaluate("() => document.querySelector('#guestlogin')"
                    ".classList.add('open')")
        pg.wait_for_timeout(300)
        st = pg.evaluate(VIS)
        assert st["loginOpen"] is True, st
        assert st["mtabs"]["display"] == "none", st
        assert st["topbar"]["display"] == "none", st
        assert st["board"]["display"] == "none", st
        pg.screenshot(path=os.path.join(PROOF, "r47_pc_login_no_tabs.png"))
        print("LOGIN-TABS-PC: CSS hides tabs/topbar/board on PC app too")
        browser.close()
    finally:
        pw.stop()
