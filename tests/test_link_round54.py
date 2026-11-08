"""v2.8.39 round (Essef Nov 7, ~3:38 PM + 3:58 PM + 4:00 PM) --
WEB/DESKTOP track only, local test build only. EIGHT items:

  (1) SAVE PASSWORD ON MB + PC WEB MENU DISCONNECT: the MB
      Set Up Your Addresses card had no Save Password option
      (the login page has one, but MB users connect from this
      card). It now has #mpcsavechk; the choice carries into
      the login page on a locked address, and follows the
      address (disabled on open addresses, checked = a copy is
      saved here). Returning to the login page auto-fills the
      saved password for the prefilled address (edit flow:
      focus empties, blur restores); an unchecked session saved
      nothing, so nothing fills. PC web menu gains Disconnect
      (#sbdisconnect, web only -- hidden on the desktop app),
      ending the session and returning to login.
  (2) LOGIN ALWAYS OPENS UPLOAD (MB): the boot code restored
      the last-used tab from localStorage, so a login after a
      Files-tab session landed on Files. showGuestMain now
      resets to Upload on a login transition only (later polls
      never yank the tab).
  (3) REMOVE Open / Change Folder from the Files tab on WEB PC
      only (no bridge): hidden via html:not(.pcapp); D keeps
      them, menu / Set Up untouched.
  (4) SAVED ON THIS DEVICE -- OPEN FROM DEVICE STORAGE: Open
      in the Saved views handed the blob to the in-app viewer
      (another preview). It now triggers a real browser
      download of the saved blob, so the OS opens it in the
      default app (MB + PC web). A ledger entry whose blob is
      gone from device storage says "file has been removed"
      (offline) instead of offering a dead Open; while
      connected Open re-downloads. PC web Saved header matches
      MB: red Delete on the RIGHT, title in the MIDDLE.
  (5a) SAVED PASSWORDS IN THE WEB ADDRESS LIST: the mobile Set
      Up dropdown (#mddlist) rendered names only -- no
      password state at all. Rows now show dots / "Locked - No
      Saved Password" / "No password" (host-history path from
      /api/linkhistory; local fallback refined per row via
      /api/addressinfo), with eye reveal for local copies.
  (5b) MB FITS ALL CARDS WITHOUT SCROLLING: the send tab had a
      12px document overflow at every width, and ~144px of
      column overflow at 700px tall. Body bottom padding
      104 -> 86px, Send column offset 170 -> 164px, tighter
      send-stack spacing, and a short-screen (<=760px tall)
      compression (smaller Share Text box, hidden footer
      slogan + hint). Measured scrollHeight vs clientHeight
      at 360/390/414/430px x 844 and x 700, all three tabs.
  (6) STARRED TOGGLE + GREYED STARS (UI only): the Starred
      filter's on/off differed by only an inset shadow, dark
      and light alike. OFF is now a neutral button, ON a solid
      amber fill with dark text, filled dark star and amber
      ring, both themes (+ aria-pressed). A starred note whose
      star permission is removed still shows as starred while
      greyed out (filled grey star at readable opacity);
      unstarred notes stay plain greyed.
  (7) WEB DROP ZONE -- "OR CLICK TO BROWSE": the guest-served
      page stripped the whole #landline, so web guests saw no
      browse line (photo image-78). Only the host-only
      destination span is stripped now; "or click to browse"
      shows on web, same .small style as D. Clicking the zone
      opens the file picker.
  (8) PC WEB SHARED FILES -- ADD NEW BUTTON: after removing
      Open / Change (3), the Files tab gains "+ Add New" --
      the Shared Texts button's design copied exactly (btn
      primary + the same plus icon). Web PC only (hidden on
      the desktop app). It opens the file picker and uploads
      like the Upload tab's chooser. Shared Files on web PC
      has TWO buttons: Delete and + Add New.
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
from test_link_round2 import server  # noqa: F401,E402
from test_link_round2 import Client  # noqa: E402
from test_link_round34 import _Fwd  # noqa: F401,E402
from test_link_round46 import _pc_page  # noqa: E402
from test_link_folders import _free_port  # noqa: E402

PAGE = D.PAGE
SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py"),
           encoding="utf-8").read()

PROOF = "/home/hatch/workspace/dropit-proof-round54"
os.makedirs(PROOF, exist_ok=True)


def test_version_is_2_8_39():
    assert D.VERSION == "2.8.39", D.VERSION


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
    assert len(scripts) == 2, len(scripts)
    for i, s in enumerate(scripts):
        p = os.path.join(PROOF, "r54_script%d.js" % i)
        open(p, "w", encoding="utf-8").write(s)
        r = subprocess.run(["node", "--check", p],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


# --- markers ---

def test_markers_item1_mb_savepw():
    """(1) MB card Save Password checkbox + sync + carry-over,
    login-page auto-fill on return, menu Disconnect."""
    assert '<label class="permchk mpcsave" id="mpcsavelabel"' in PAGE
    assert '<input type="checkbox" id="mpcsavechk" checked>' in PAGE
    assert "async function syncMpSavePw(){" in PAGE
    assert "const _mpc = $(\"#mpcsavechk\"); if(_mpc && sc) sc.checked = _mpc.checked;" in PAGE
    assert "if(!mp2.value || (st.address_name || \"\") !== (window.__mpLastAddr || \"\")) mp2.value = st.address_name || \"\";" in PAGE
    assert "if(_sv0){ _pw0.value = _sv0; _glPwSt.saved = _sv0; _glPwSt.shown = true; }" in PAGE
    assert '<button class="sbbtn" id="sbdisconnect" style="display:none">Disconnect</button>' in PAGE
    assert "const _sdc = $(\"#sbdisconnect\"); if(_sdc) _sdc.style.display = (!hasBridge() && st.authed) ? \"\" : \"none\";" in PAGE
    assert "if(_sbd) _sbd.onclick = () => { openSidebar(false); window._userDisconnected = true; doLogout(); toast(\"Disconnected\"); };" in PAGE


def test_markers_item2_login_upload():
    """(2) showGuestMain resets to Upload on a login transition
    only; the boot restore is untouched."""
    assert "const _wasLogin = !!(gl0 && (gl0.classList.contains(\"open\") || gl0.dataset.lkHidden));" in PAGE
    assert "if(_wasLogin && typeof setTab === \"function\") setTab(\"send\");" in PAGE
    assert "try { setTab(localStorage.getItem(\"dropit_tab\") || \"send\"); } catch(e){ setTab(\"send\"); }" in PAGE


def test_markers_item3_no_folder_btns_web():
    """(3) Open / Change hidden on web PC (no .pcapp); the
    server still renders them for the desktop app."""
    assert "html:not(.pcapp) .fbtnrow #openfolder, html:not(.pcapp) .fbtnrow #changefolder { display:none; }" in PAGE
    assert "<button class=\"btn openf\" id=\"openfolder\"" in SRC
    assert "<button class=\"btn changef\" id=\"changefolder\"" in SRC


def test_markers_item4_saved_open_os():
    """(4) Saved Open hands the blob to the OS (real download),
    gone rows say so, PC web header matches MB."""
    assert "async function openSavedFileOS(name){" in PAGE
    assert "a.href = url; a.download = name;" in PAGE
    assert "b.onclick = () => openSavedFileOS(sfiles[+b.dataset.sopen].name));" in PAGE
    assert "row.classList.add(\"gsaved-gone\");" in PAGE
    assert "file has been removed" in PAGE
    assert "async function openSavedFile(name){\n  // v2.8.39 (4): Open hands the file to the OS default app" in PAGE
    _i = PAGE.index("async function openSavedFile(name){")
    _body = PAGE[_i:_i + 400]
    assert "openSavedFileOS(name)" in _body, _body
    assert "openBlob" not in _body, _body
    assert ".gsavedhead { position:relative; }" in PAGE
    assert ".gsavedhead b { position:absolute; left:50%; top:50%; transform:translate(-50%,-50%); font-size:15px; }" in PAGE
    assert ".gsavedhead #gsaveddel { order:2; margin-left:auto; background:#ef4444; color:#ffffff; border:none; }" in PAGE
    assert "@media (max-width:720px){\n    .gsavedhead { position:relative; }" not in PAGE


def test_markers_item5a_mddlist_pw():
    """(5a) The mobile address list shows the password state."""
    assert "const pwState = (n) => {" in PAGE
    assert "(e.password_saved ? \"••••••\" : (e.locked ? \"Locked - No Saved Password\" : \"No password\"))" in PAGE
    assert "sp.textContent = jj.needs_password ? \"Locked - No Saved Password\" : \"No password\";" in PAGE
    assert "data-meye=" in PAGE
    # The guest fallback refines via /api/addressinfo, which
    # used to answer known:false for every non-current address
    # -- the server now answers for known history addresses too.
    assert "_entry_locked(cfg, _wk)" in SRC


def test_markers_item5b_fit():
    """(5b) Fit CSS: body padding, column offset, short-screen
    compression."""
    assert "body { padding:16px 12px 86px; display:block; height:auto; }" in PAGE
    assert "body[data-mtab=\"send\"] .board .col[data-col=\"send\"] { height:calc(100dvh - 164px); }" in PAGE
    assert "@media (max-width:720px) and (max-height:760px){" in PAGE
    assert ".msend #msendtext { height:78px; min-height:0; }" in PAGE
    assert ".board .col[data-col=\"send\"] .msendfoot { display:none; }" in PAGE
    assert ".msend .mhint { display:none; }" in PAGE


def test_markers_item6_starred():
    """(6) Starred filter off/on + greyed starred notes."""
    assert ".board #starfilter { background:var(--card2); color:var(--muted); border:1px solid var(--line); }" in PAGE
    assert ".board #starfilter.on { background:linear-gradient(135deg,#fbbf24,#f59e0b); color:#231303; border:1px solid #b45309; box-shadow:0 0 0 2px rgba(245,158,11,.5); }" in PAGE
    assert "html.light .board #starfilter { background:#ffffff; color:#64748b; border-color:#cbd5e1; }" in PAGE
    assert ".starbtn.starred.deloff { opacity:.6 !important; }" in PAGE
    assert ".starbtn.starred.deloff svg { fill:#9ca3af; }" in PAGE
    assert "starfilter.setAttribute(\"aria-pressed\", String(starredOnly));" in PAGE


def test_markers_item7_dropzone():
    """(7) Only the host-only destination span is stripped;
    the browse line stays for web guests."""
    assert '<span id="landline-dir"> &mdash; they land in:' in PAGE
    assert "r'<span id=\"landline-dir\">.*?</span></span>'" in SRC
    assert "const ld = $(\"#landline-dir\"); if(ld) ld.style.display = st.host ? \"\" : \"none\";" in PAGE
    assert "r'<div class=\"small\" id=\"landline\">.*?</div>'" not in SRC


def test_markers_item8_files_addnew():
    """(8) Files-tab Add New: server HTML, pcapp hide, blue
    design shared with #maddnote, picker wiring."""
    assert "'<button class=\"btn primary\" id=\"fileaddbtn\" data-tip=\"Add files from this PC\">" in SRC
    assert "html.pcapp .fbtnrow #fileaddbtn { display:none; }" in PAGE
    assert ".board #sendsnippet, .board #maddnote, .board #fileaddbtn," in PAGE
    assert "if(_fab) _fab.onclick = () => { if(AUTH && !AUTH.host && AUTH.authed && !canUploadUI()){ toast(\"No permission to upload files to this device\"); return; } picker.click(); };" in PAGE
    assert "const fab = $(\"#fileaddbtn\"); if(fab) fab.classList.toggle(\"deloff\", upBlocked);" in PAGE


# --- Playwright helpers ---

def _host_web_page(pw, port, width, height):
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    ctx = browser.new_context(viewport={"width": width, "height": height})
    pg = ctx.new_page()
    pg.goto("http://127.0.0.1:%d/" % port)
    pg.wait_for_function(
        "() => typeof AUTH !== 'undefined' && AUTH.host", timeout=10000)
    pg.wait_for_timeout(900)
    return browser, pg


def _guest_page(pw, port, width, height, init_script=None, light=False,
                accept_downloads=False):
    fwd = _Fwd(port)
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    ctx = browser.new_context(viewport={"width": width, "height": height},
                              accept_downloads=accept_downloads)
    if init_script:
        ctx.add_init_script(init_script)
    pg = ctx.new_page()
    pg.goto("http://127.0.0.3:%d/" % fwd.port)
    pg.wait_for_selector("#gloginbtn", state="attached", timeout=10000)
    pg.wait_for_timeout(900)
    if light:
        pg.evaluate("() => document.documentElement.classList.add('light')")
        pg.wait_for_timeout(300)
    return browser, ctx, pg, fwd


def _wait_authed(pg):
    """Wait until the page reports an authenticated session (an
    open address authenticates sessionlessly on load)."""
    pg.wait_for_function(
        "() => typeof AUTH !== 'undefined' && AUTH.authed", timeout=10000)
    pg.wait_for_timeout(600)


def _guest_login(pg, address, password=None, save=None):
    """Fill the login form and connect. save=True/False forces the
    Save password checkbox; None leaves it alone. If the page is
    already authed (open address: sessionless), there is no login
    form -- this is a no-op."""
    pg.wait_for_function(
        "() => typeof AUTH !== 'undefined' && (AUTH.authed || document.querySelector('#guestlogin').classList.contains('open'))",
        timeout=10000)
    pg.wait_for_timeout(400)
    if not pg.evaluate("() => document.querySelector('#guestlogin').classList.contains('open')"):
        return
    pg.fill("#gloginlink", address)
    pg.wait_for_timeout(400)
    if password is not None:
        pg.fill("#gloginpw", password)
    if save is not None:
        cur = pg.evaluate("() => document.querySelector('#gloginsavechk').checked")
        if cur != save:
            pg.click("#gloginsavelabel")
            pg.wait_for_timeout(200)
    pg.click("#gloginbtn")
    pg.wait_for_function(
        "() => !document.querySelector('#guestlogin').classList.contains('open')",
        timeout=10000)
    pg.wait_for_timeout(900)


def _guest_logout(pg):
    """End the guest session. Mobile: the Upload tab's
    Disconnect; PC web: the menu Disconnect (item 1c)."""
    if pg.evaluate("() => window.innerWidth >= 721"):
        pg.click("#menubtn")
        pg.wait_for_function(
            "() => document.querySelector('#sidebar').classList.contains('open')",
            timeout=5000)
        pg.wait_for_timeout(300)
        pg.click("#sbdisconnect")
    else:
        pg.evaluate("() => setTab('send')")
        pg.wait_for_timeout(300)
        pg.click("#mpcdisconnect")
    pg.wait_for_function(
        "() => document.querySelector('#guestlogin').classList.contains('open')",
        timeout=10000)
    pg.wait_for_timeout(800)


def _auth(client):
    status, j = client.j("GET", "/api/authstate")
    assert status == 200 and j["ok"], j
    return j


@pytest.fixture()
def dserver(tmp_path):
    """A desktop=True server (the app.py shape): renders the
    Files-tab Open / Change / Delete row, like the real PC app
    server. The stock `server` fixture runs desktop=False."""
    home = tmp_path / "home"
    base = tmp_path / "base"
    base.mkdir()
    data = home / ".config" / "DropIt"
    data.mkdir(parents=True)
    port = _free_port()
    env = dict(os.environ, HOME=str(home))
    root = os.path.join(os.path.dirname(__file__), "..")
    code = ("import sys; sys.path.insert(0, %r); import dropit; "
            "s = dropit.make_server(%d, %r, desktop=True); "
            "s.serve_forever()" % (root, port, str(base)))
    proc = subprocess.Popen(
        [sys.executable, "-c", code], cwd=root, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client = Client(port)
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                status, _ = client.j("GET", "/api/authstate")
                if status == 200:
                    break
            except OSError:
                pass
            time.sleep(0.2)
        else:
            raise RuntimeError("desktop server did not come up")
        yield client, base, proc, port, home
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _vis(pg, sel):
    return pg.evaluate("""(sel) => { const el = document.querySelector(sel);
      if (!el) return {exists: false};
      const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
      return {exists: true, visible: cs.display !== 'none' && r.width > 0 && r.height > 0,
              display: cs.display, w: Math.round(r.width), h: Math.round(r.height)}; }""", sel)


def _delete_idb_blob(pg, name):
    """Remove one file's blob from the on-device cache (IndexedDB)
    while keeping the localStorage ledger -- the 'file removed
    from the device folder' simulation."""
    pg.evaluate("""(name) => new Promise((res) => {
      const rq = indexedDB.open('dropit-cache', 1);
      rq.onsuccess = () => { const db = rq.result;
        const tx = db.transaction('files', 'readwrite');
        tx.objectStore('files').delete(name);
        tx.oncomplete = () => res(true); tx.onerror = () => res(false); };
      rq.onerror = () => res(false); })""", name)
    pg.wait_for_timeout(400)


# --- (1) MB Save Password: login page flow ---

def test_item1_mb_savepw_checked_saves_and_autofills(server):
    """(1) MB login, checked -> password saved (hashed, in the
    local list) and auto-filled on return; then unchecked ->
    NOT saved and no auto-fill after disconnect."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink",
                    {"name": "svpw", "password": "secret1",
                     "save_password": True})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, ctx, pg, fwd = _guest_page(pw, port, 390, 844)
        try:
            assert _vis(pg, "#gloginsavelabel")["visible"], "Save password missing on MB login"
            _guest_login(pg, "svpw", "secret1", save=True)
            saved = pg.evaluate("() => JSON.parse(localStorage.getItem('drop_guest_pw') || '{}')")
            assert saved.get("svpw") == "secret1", saved
            # The address dropdown shows the saved password as dots.
            pg.evaluate("() => { if (window.innerWidth < 721) setTab('send'); }")
            pg.wait_for_timeout(300)
            _guest_logout(pg)
            # Returning auto-fills the saved password (dots).
            pg.wait_for_function(
                "() => document.querySelector('#gloginpw').value === 'secret1'",
                timeout=5000)
            assert pg.evaluate("() => document.querySelector('#gloginpw').type") == "password"
            assert pg.evaluate("() => document.querySelector('#gloginsavechk').checked") is True
            pg.screenshot(path="%s/r54_item1_autofill.png" % PROOF)
            print("ITEM1 CHECKED: saved + auto-filled on return")
            # Now log in with Save Password UNCHECKED: the saved
            # copy must be dropped, and the next return must NOT
            # auto-fill.
            pg.click("#gloginsavelabel")
            pg.wait_for_timeout(200)
            assert pg.evaluate("() => document.querySelector('#gloginsavechk').checked") is False
            pg.click("#gloginbtn")
            pg.wait_for_function(
                "() => !document.querySelector('#guestlogin').classList.contains('open')",
                timeout=10000)
            pg.wait_for_timeout(800)
            saved2 = pg.evaluate("() => JSON.parse(localStorage.getItem('drop_guest_pw') || '{}')")
            assert "svpw" not in saved2, saved2
            _guest_logout(pg)
            pg.wait_for_timeout(600)
            assert pg.evaluate("() => document.querySelector('#gloginpw').value") == "", \
                "unchecked session auto-filled the password"
            assert pg.evaluate("() => document.querySelector('#gloginsavechk').checked") is False
            print("ITEM1 UNCHECKED: not saved, no auto-fill after disconnect")
        finally:
            browser.close()
            fwd.stop.set()


def test_item1_mb_msend_savepw_and_carryover(server):
    """(1) The MB Set Up card has the Save Password checkbox;
    its choice carries into the login page on a locked address;
    it greys out on an open address."""
    client, base, proc, port, home = server
    for name, pw in [("svpw", "secret1"), ("svpw2", "secret2")]:
        s, j = client.j("POST", "/api/setlink",
                        {"name": name, "password": pw,
                         "save_password": True})
        assert s == 200 and j["ok"], j
    s, j = client.j("POST", "/api/setlink", {"name": "fitlink"})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, ctx, pg, fwd = _guest_page(pw, port, 390, 844)
        try:
            # fitlink is the current address and open, so the
            # guest is already authed; the card is the subject.
            _wait_authed(pg)
            pg.evaluate("() => setTab('send')")
            pg.wait_for_timeout(500)
            assert _vis(pg, "#mpcsavelabel")["visible"], "MB card has no Save password"
            # Open address -> the card's box greys out.
            pg.fill("#mpchost", "fitlink")
            pg.wait_for_function(
                "() => document.querySelector('#mpcsavechk').disabled === true",
                timeout=5000)
            # Locked address, box CHECKED -> Connect routes to the
            # login page with its box checked too (carried over).
            # The locked address must be the PC's CURRENT address
            # (/api/connect only answers for it, by design), so
            # the host switches to a fresh locked address and the
            # guest taps Connect at once -- before the next 5s
            # poll bounces the stale session to the login page.
            s, j = client.j("POST", "/api/setlink",
                            {"name": "svpw3", "password": "secret3",
                             "save_password": True})
            assert s == 200 and j["ok"], j
            pg.evaluate("""() => {
              document.querySelector('#mpchost').value = 'svpw3';
              document.querySelector('#mpcsavechk').checked = true;
              document.querySelector('#mpcconnect').click(); }""")
            pg.wait_for_function(
                "() => document.querySelector('#guestlogin').classList.contains('open')",
                timeout=10000)
            pg.wait_for_timeout(600)
            assert pg.evaluate("() => document.querySelector('#gloginlink').value") == "svpw3"
            assert pg.evaluate("() => document.querySelector('#gloginsavechk').checked") is True, \
                "MB card choice did not carry to the login page"
            pg.screenshot(path="%s/r54_item1_carryover.png" % PROOF)
            # Complete the login: the carried choice saves it.
            pg.fill("#gloginpw", "secret3")
            pg.click("#gloginbtn")
            pg.wait_for_function(
                "() => !document.querySelector('#guestlogin').classList.contains('open')",
                timeout=10000)
            pg.wait_for_timeout(800)
            saved = pg.evaluate("() => JSON.parse(localStorage.getItem('drop_guest_pw') || '{}')")
            assert saved.get("svpw3") == "secret3", saved
            print("ITEM1 MB CARD: checkbox present, open greys out, locked choice carries + saves")
        finally:
            browser.close()
            fwd.stop.set()


def test_item1_menu_disconnect_pc_web(server):
    """(1) PC web menu has Disconnect: a guest ends the session
    and lands on the login page. The desktop app hides it."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink",
                    {"name": "menulink", "password": "pw123",
                     "save_password": True})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        # Guest on PC web (1280, no bridge).
        browser, ctx, pg, fwd = _guest_page(pw, port, 1280, 800)
        try:
            _guest_login(pg, "menulink", "pw123")
            pg.click("#menubtn")
            pg.wait_for_function(
                "() => document.querySelector('#sidebar').classList.contains('open')",
                timeout=5000)
            pg.wait_for_timeout(400)
            assert _vis(pg, "#sbdisconnect")["visible"], "menu Disconnect missing on PC web"
            st = pg.evaluate("""() => { const b = document.querySelector('#sbdisconnect');
              const cs = getComputedStyle(b);
              return {text: b.textContent.trim(), bg: cs.backgroundColor}; }""")
            assert st["text"] == "Disconnect" and st["bg"] == "rgb(239, 68, 68)", st
            pg.screenshot(path="%s/r54_item1_menu_disconnect.png" % PROOF)
            pg.click("#sbdisconnect")
            pg.wait_for_function(
                "() => document.querySelector('#guestlogin').classList.contains('open')",
                timeout=10000)
            print("ITEM1 MENU: Disconnect ends the session, back on login")
        finally:
            browser.close()
            fwd.stop.set()
        # Desktop app (fake bridge): no Disconnect in the menu.
        browser, pg = _pc_page(pw, port, 1280, 800, frameless=True)
        try:
            pg.click("#menubtn")
            pg.wait_for_function(
                "() => document.querySelector('#sidebar').classList.contains('open')",
                timeout=5000)
            pg.wait_for_timeout(400)
            assert _vis(pg, "#sbdisconnect")["visible"] is False, \
                "Disconnect must stay hidden on the desktop app"
            print("ITEM1 MENU: hidden on D, as required")
        finally:
            browser.close()


# --- (2) Login always opens Upload ---

def test_item2_login_always_upload(server):
    """(2) Three logins in a row, each with the last tab seeded
    to Files: every one lands on Upload."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink",
                    {"name": "tablink", "password": "pw123",
                     "save_password": True})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, ctx, pg, fwd = _guest_page(pw, port, 390, 844)
        try:
            for i in range(3):
                pg.evaluate("() => localStorage.setItem('dropit_tab', 'files')")
                _guest_login(pg, "tablink", "pw123")
                tab = pg.evaluate("() => document.body.dataset.mtab")
                assert tab == "send", "login %d landed on %s" % (i + 1, tab)
                assert pg.evaluate(
                    "() => document.querySelector('.col[data-col=\"send\"]').classList.contains('active')") is True
                print("ITEM2 login %d: landed on Upload (was Files)" % (i + 1))
                if i < 2:
                    _guest_logout(pg)
            pg.screenshot(path="%s/r54_item2_upload.png" % PROOF)
        finally:
            browser.close()
            fwd.stop.set()


# --- (3) Files tab: no Open / Change on web PC; D keeps them ---

def test_item3_files_tab_folder_buttons(dserver):
    """(3) Desktop server, web PC (no bridge): the Files tab has
    NO Open / Change Folder buttons; the desktop app keeps them."""
    client, base, proc, port, home = dserver
    s, j = client.j("POST", "/api/setlink", {"name": "fblink"})
    assert s == 200 and j["ok"], j
    open(os.path.join(j["folder"], "hello.txt"), "w").write("hello\n")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        # Web PC: plain browser, 1280.
        browser, pg = _host_web_page(pw, port, 1280, 800)
        try:
            pg.evaluate("() => { if (window.innerWidth < 721) setTab('files'); }")
            pg.wait_for_selector(".frow .fname", timeout=10000)
            assert _vis(pg, "#openfolder")["visible"] is False, "web PC still shows Open Folder"
            assert _vis(pg, "#changefolder")["visible"] is False, "web PC still shows Change Folder"
            assert _vis(pg, "#delallbtn")["exists"] is True, "Delete button gone from web PC"
            pg.screenshot(path="%s/r54_item3_webpc.png" % PROOF)
            print("ITEM3 WEB PC: no Open / Change Folder buttons; Delete present")
        finally:
            browser.close()
        # Desktop app (fake bridge): Open / Change stay visible.
        browser, pg = _pc_page(pw, port, 1280, 800, frameless=True)
        try:
            pg.wait_for_selector(".frow .fname", timeout=10000)
            assert _vis(pg, "#openfolder")["visible"] is True, "D lost Open Folder"
            assert _vis(pg, "#changefolder")["visible"] is True, "D lost Change Folder"
            assert pg.evaluate("() => document.documentElement.classList.contains('pcapp')") is True
            print("ITEM3 D: Open / Change Folder kept")
        finally:
            browser.close()


# --- (4) Saved on this device: OS open + removed tracking + header ---

def _download_one_file(pg, name="hello.txt"):
    """On the Files tab, preview a file, Download it and confirm
    Save on this device, so it lands in the device ledger."""
    pg.evaluate("() => { if (window.innerWidth < 721) setTab('files'); }")
    pg.wait_for_timeout(400)
    pg.wait_for_selector(".frow .fname", timeout=10000)
    pg.click(".frow .fname >> nth=0")
    pg.wait_for_selector("#previewdl", timeout=5000)
    pg.wait_for_timeout(400)
    assert pg.evaluate("() => document.querySelector('#previewdl').textContent") == "Download"
    pg.click("#previewdl")
    pg.wait_for_selector("#cfdlg.open", timeout=5000)
    pg.wait_for_timeout(300)
    pg.evaluate("() => document.querySelector('#cfyes').click()")
    pg.wait_for_function(
        "() => document.querySelector('#previewdl').textContent === 'Open'",
        timeout=5000)
    pg.click("#previewclose2")
    pg.wait_for_timeout(400)


def test_item4_saved_open_hands_to_os_mb(server):
    """(4) MB Saved view: Open triggers a REAL browser download
    (the OS handler), not another in-app preview."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink", {"name": "svdl"})
    assert s == 200 and j["ok"], j
    open(os.path.join(j["folder"], "hello.txt"), "w").write("hello saved\n")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, ctx, pg, fwd = _guest_page(pw, port, 390, 844,
                                            accept_downloads=True)
        try:
            _wait_authed(pg)
            _download_one_file(pg)
            _guest_logout(pg)
            pg.click("#gsavedbtn")
            pg.wait_for_selector(".gsavedrow", timeout=5000)
            pg.wait_for_timeout(500)
            assert pg.evaluate(
                "() => [...document.querySelectorAll('.gsavedrow')].some(r => r.textContent.includes('hello.txt'))")
            with pg.expect_download(timeout=10000) as dl_info:
                pg.click("[data-open-saved]")
            dl = dl_info.value
            assert dl.suggested_filename == "hello.txt", dl.suggested_filename
            pg.wait_for_timeout(600)
            assert pg.evaluate(
                "() => document.querySelector('#viewer').classList.contains('open')") is False, \
                "Open showed another in-app preview instead of the OS handler"
            pg.screenshot(path="%s/r54_item4_saved_open_mb.png" % PROOF)
            print("ITEM4 MB: Open downloaded hello.txt to the OS; no preview opened")
        finally:
            browser.close()
            fwd.stop.set()


def test_item4_saved_open_hands_to_os_pcweb(server):
    """(4) PC web Saved: Open triggers a real download in BOTH
    Saved surfaces -- the login-page Saved view and the in-app
    Saved viewer (showSaved) -- and no in-app preview opens."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink", {"name": "svdlpc"})
    assert s == 200 and j["ok"], j
    open(os.path.join(j["folder"], "hello.txt"), "w").write("hello saved\n")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-proxy-server"])
        ctx = browser.new_context(viewport={"width": 1280, "height": 800},
                                  accept_downloads=True)
        pg = ctx.new_page()
        fwd = _Fwd(port)
        pg.goto("http://127.0.0.3:%d/" % fwd.port)
        pg.wait_for_selector("#gloginbtn", state="attached", timeout=10000)
        pg.wait_for_timeout(900)
        try:
            _wait_authed(pg)
            _download_one_file(pg)
            # (a) In-app Saved viewer (showSaved): Open downloads.
            pg.evaluate("() => showSaved()")
            pg.wait_for_function(
                "() => document.querySelector('#viewer').classList.contains('open')",
                timeout=5000)
            pg.wait_for_timeout(500)
            assert pg.evaluate("() => document.querySelector('#vtitle').textContent") == "Saved on this device"
            with pg.expect_download(timeout=10000) as dl_info:
                pg.click("[data-sopen]")
            dl = dl_info.value
            assert dl.suggested_filename == "hello.txt", dl.suggested_filename
            pg.wait_for_timeout(600)
            assert pg.evaluate("() => document.querySelector('#vtitle').textContent") == "Saved on this device", \
                "Open replaced the Saved list with a preview"
            pg.click("#vclose")
            pg.wait_for_timeout(400)
            # (b) Login-page Saved view: Open downloads, no viewer.
            _guest_logout(pg)
            pg.click("#gsavedbtn")
            pg.wait_for_selector(".gsavedrow", timeout=5000)
            pg.wait_for_timeout(500)
            with pg.expect_download(timeout=10000) as dl_info2:
                pg.click("[data-open-saved]")
            dl2 = dl_info2.value
            assert dl2.suggested_filename == "hello.txt", dl2.suggested_filename
            pg.wait_for_timeout(600)
            assert pg.evaluate(
                "() => document.querySelector('#viewer').classList.contains('open')") is False
            pg.screenshot(path="%s/r54_item4_saved_open_pc.png" % PROOF)
            print("ITEM4 PC WEB: Open downloaded hello.txt in both Saved surfaces; no preview")
        finally:
            browser.close()
            fwd.stop.set()


def test_item4_removed_file_says_so(server):
    """(4) A ledger entry whose blob is gone from device storage
    says 'file has been removed' instead of offering a dead Open.
    The address is LOCKED and the guest logged out, so the PC
    cannot re-supply the file -- the offline case. (For an open
    address the PC stays reachable sessionlessly and Open
    re-downloads instead; that is the connected case.)"""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink",
                    {"name": "svgone", "password": "pw123",
                     "save_password": True})
    assert s == 200 and j["ok"], j
    open(os.path.join(j["folder"], "gone.txt"), "w").write("gone file\n")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, ctx, pg, fwd = _guest_page(pw, port, 390, 844)
        try:
            _guest_login(pg, "svgone", "pw123")
            _download_one_file(pg, "gone.txt")
            _guest_logout(pg)
            # Remove the blob from the device cache (ledger stays).
            _delete_idb_blob(pg, "gone.txt")
            pg.reload()
            pg.wait_for_selector("#gloginbtn", state="attached", timeout=10000)
            pg.wait_for_timeout(900)
            pg.click("#gsavedbtn")
            pg.wait_for_selector(".gsavedrow", timeout=5000)
            pg.wait_for_function(
                "() => [...document.querySelectorAll('.gsavedrow')].some(r => r.textContent.includes('file has been removed'))",
                timeout=5000)
            st = pg.evaluate("""() => { const r = [...document.querySelectorAll('.gsavedrow')].find(x => x.textContent.includes('gone.txt'));
              const b = r.querySelector('[data-open-saved]');
              return {gone: r.classList.contains('gsaved-gone'), openDisabled: b.disabled, openText: b.textContent}; }""")
            assert st["gone"] is True and st["openDisabled"] is True, st
            pg.screenshot(path="%s/r54_item4_removed.png" % PROOF)
            print("ITEM4 REMOVED: row says 'file has been removed', Open disabled: %s" % st)
        finally:
            browser.close()
            fwd.stop.set()


def test_item4_saved_header_pc_web(server):
    """(4) PC web Saved header: red Delete on the RIGHT, title
    in the MIDDLE (same as MB)."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink", {"name": "svhead"})
    assert s == 200 and j["ok"], j
    open(os.path.join(j["folder"], "hello.txt"), "w").write("hello\n")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, ctx, pg, fwd = _guest_page(pw, port, 1280, 800)
        try:
            _wait_authed(pg)
            _download_one_file(pg)
            _guest_logout(pg)
            pg.click("#gsavedbtn")
            pg.wait_for_selector(".gsavedrow", timeout=5000)
            pg.wait_for_timeout(400)
            m = pg.evaluate("""() => {
              const head = document.querySelector('.gsavedhead').getBoundingClientRect();
              const t = document.querySelector('.gsavedhead b').getBoundingClientRect();
              const d = document.querySelector('#gsaveddel').getBoundingClientRect();
              const b = document.querySelector('#gsavedback').getBoundingClientRect();
              const cs = getComputedStyle(document.querySelector('#gsaveddel'));
              return {headCx: head.x + head.width / 2, titleCx: t.x + t.width / 2,
                      delRight: d.right, headRight: head.right,
                      backLeft: b.left, headLeft: head.left,
                      delBg: cs.backgroundColor, title: document.querySelector('.gsavedhead b').textContent}; }""")
            assert abs(m["titleCx"] - m["headCx"]) <= 8, m
            assert abs(m["delRight"] - m["headRight"]) <= 8, m
            assert m["backLeft"] - m["headLeft"] <= 8, m
            assert m["delBg"] == "rgb(239, 68, 68)", m
            assert m["title"] == "Saved on this device", m
            pg.screenshot(path="%s/r54_item4_header_pc.png" % PROOF)
            print("ITEM4 HEADER PC: title centred, red Delete right: %s" % m)
        finally:
            browser.close()
            fwd.stop.set()


# --- (7) Web drop zone: "or click to browse" ---

def test_item7_dropzone_browse_line(server):
    """(7) Web guests see 'or click to browse' under 'Drop Your
    Files Here' (same style as D); the host path stays hidden.
    Clicking the zone opens the file picker."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink", {"name": "dzlink"})
    assert s == 200 and j["ok"], j
    folder = j["folder"]
    # Guest-served HTML: browse line present, no host path.
    import http.client
    fwd = _Fwd(port)
    try:
        conn = http.client.HTTPConnection("127.0.0.3", fwd.port, timeout=10)
        conn.request("GET", "/")
        resp = conn.getresponse()
        html = resp.read().decode("utf-8")
        conn.close()
        assert resp.status == 200
        assert "or click to browse" in html, "browse line missing from guest page"
        assert 'id="landline"' in html
        assert 'id="landline-dir"' not in html, "host destination span leaked to guest"
        assert "they land in" not in html
        assert str(base) not in html, "host path leaked to guest page"
        print("ITEM7 HTML: guest page has the browse line, no host path")
    finally:
        fwd.stop.set()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        # Guest on PC web: the line shows; clicking opens the picker.
        browser, ctx, pg, fwd = _guest_page(pw, port, 1280, 800)
        try:
            _wait_authed(pg)
            pg.wait_for_timeout(500)
            txt = pg.evaluate("() => document.querySelector('#landline').innerText")
            assert txt.strip() == "or click to browse", repr(txt)
            assert pg.evaluate("() => !!document.querySelector('#landline-dir')") is False
            pg.screenshot(path="%s/r54_item7_dropzone_guest.png" % PROOF)
            up = os.path.join(str(base), "via-dropzone.txt")
            open(up, "w").write("via drop zone\n")
            with pg.expect_file_chooser(timeout=5000) as ch_info:
                pg.click("#drop")
            ch = ch_info.value
            ch.set_files(up)
            pg.wait_for_function(
                "() => [...document.querySelectorAll('#files .frow .fname')].some(e => e.textContent.includes('via-dropzone.txt'))",
                timeout=10000)
            print("ITEM7 GUEST: line shows, zone click opens picker, file uploaded")
        finally:
            browser.close()
            fwd.stop.set()
        # Host page: both lines, same style.
        browser, pg = _host_web_page(pw, port, 1280, 800)
        try:
            txt = pg.evaluate("() => document.querySelector('#landline').innerText")
            assert "or click to browse" in txt and "they land in" in txt, repr(txt)
            assert pg.evaluate("() => !!document.querySelector('#landline-dir')") is True
            pg.screenshot(path="%s/r54_item7_dropzone_host.png" % PROOF)
            print("ITEM7 HOST: both lines show: %r" % txt)
        finally:
            browser.close()


# --- (8) PC web Shared Files: + Add New ---

def test_item8_files_add_new(dserver):
    """(8) Web PC Files tab has TWO buttons: + Add New and
    Delete. Clicking Add New opens the picker and uploads.
    D has no Add New button."""
    client, base, proc, port, home = dserver
    s, j = client.j("POST", "/api/setlink", {"name": "addlink"})
    assert s == 200 and j["ok"], j
    open(os.path.join(j["folder"], "seed.txt"), "w").write("seed\n")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        # Web PC (no bridge).
        browser, pg = _host_web_page(pw, port, 1280, 800)
        try:
            pg.wait_for_selector(".frow .fname", timeout=10000)
            pg.wait_for_timeout(500)
            vis = pg.evaluate("""() => [...document.querySelectorAll('.fbtnrow .btn')]
              .filter(b => { const r = b.getBoundingClientRect(); const cs = getComputedStyle(b);
                return cs.display !== 'none' && r.width > 0; })
              .map(b => b.textContent.trim())""")
            assert vis == ["Add New", "Delete"], vis
            # Same design as the Shared Texts + Add New: same
            # background, text colour and label.
            same = pg.evaluate("""() => { const a = getComputedStyle(document.querySelector('#fileaddbtn'));
              const m = getComputedStyle(document.querySelector('#maddnote'));
              return {addBg: a.backgroundColor, maddBg: m.backgroundColor,
                      addColor: a.color, maddColor: m.color,
                      addLabel: document.querySelector('#fileaddbtn').textContent.trim(),
                      maddLabel: document.querySelector('#maddnote').textContent.trim()}; }""")
            assert same["addBg"] == same["maddBg"] == "rgb(39, 127, 240)", same
            assert same["addColor"] == same["maddColor"] == "rgb(255, 255, 255)", same
            assert same["addLabel"] == same["maddLabel"] == "Add New", same
            pg.screenshot(path="%s/r54_item8_files_addnew.png" % PROOF)
            up = os.path.join(str(base), "via-addnew.txt")
            open(up, "w").write("via add new\n")
            with pg.expect_file_chooser(timeout=5000) as ch_info:
                pg.click("#fileaddbtn")
            ch = ch_info.value
            ch.set_files(up)
            pg.wait_for_function(
                "() => [...document.querySelectorAll('#files .frow .fname')].some(e => e.textContent.includes('via-addnew.txt'))",
                timeout=10000)
            print("ITEM8 WEB PC: Add New + Delete only; same design as Texts; picker opens, file uploaded: %s" % same)
        finally:
            browser.close()
        # Desktop app: no Add New; Open / Change stay.
        browser, pg = _pc_page(pw, port, 1280, 800, frameless=True)
        try:
            pg.wait_for_selector(".frow .fname", timeout=10000)
            assert _vis(pg, "#fileaddbtn")["visible"] is False, "D must not show Add New"
            assert _vis(pg, "#openfolder")["visible"] is True
            assert _vis(pg, "#changefolder")["visible"] is True
            print("ITEM8 D: no Add New; Open / Change kept")
        finally:
            browser.close()


# --- (5a) Saved passwords visible in the web address list ---

def test_item5a_mddlist_pw_states(server):
    """(5a) The MB Set Up dropdown shows the password state per
    row: dots for a saved copy, 'Locked - No Saved Password'
    for locked-not-saved, 'No password' for open. Host path
    (from /api/linkhistory) and the guest local fallback."""
    client, base, proc, port, home = server
    # Locked + saved here (host save), locked + not saved, open.
    s, j = client.j("POST", "/api/setlink",
                    {"name": "pwlist1", "password": "secret1",
                     "save_password": True})
    assert s == 200 and j["ok"], j
    s, j = client.j("POST", "/api/setlink",
                    {"name": "pwlist2", "password": "secret2",
                     "save_password": False})
    assert s == 200 and j["ok"], j
    s, j = client.j("POST", "/api/setlink", {"name": "pwlist3"})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        # GUEST (local fallback): seed the local saved copy for
        # pwlist1 only, so the rows must read dots / locked-not-
        # saved / no password.
        browser, ctx, pg, fwd = _guest_page(pw, port, 390, 844)
        try:
            pg.evaluate("""() => localStorage.setItem('drop_guest_pw',
              JSON.stringify({pwlist1: 'secret1'}))""")
            _wait_authed(pg)
            pg.evaluate("() => setTab('send')")
            pg.wait_for_timeout(500)
            # Open the address dropdown (chevron toggle).
            # Seed the local use counts: a guest's list falls
            # back to the addresses this device has connected to
            # before (/api/linkhistory is host-only).
            pg.evaluate("""() => localStorage.setItem('drop_link_use',
              JSON.stringify({pwlist1: 5, pwlist2: 3, pwlist3: 1}))""")
            pg.click("#mddtoggle")
            pg.wait_for_function(
                "() => [...document.querySelectorAll('#mddlist .ddopt')].length >= 3",
                timeout=8000)
            pg.wait_for_timeout(1200)
            rows = pg.evaluate("""() => [...document.querySelectorAll('#mddlist .ddopt')]
              .map(r => r.innerText.replace(/\\n/g, ' | '))""")
            print("ITEM5A guest rows: %s" % rows)
            by_name = {}
            for r in rows:
                for n in ("pwlist1", "pwlist2", "pwlist3"):
                    if r.startswith(n):
                        by_name[n] = r
            assert "••••••" in by_name["pwlist1"], by_name
            assert "Locked - No Saved Password" in by_name["pwlist2"], by_name
            assert "No password" in by_name["pwlist3"], by_name
            pg.screenshot(path="%s/r54_item5a_mddlist.png" % PROOF)
            print("ITEM5A GUEST: dots / Locked - No Saved Password / No password all shown")
        finally:
            browser.close()
            fwd.stop.set()
        # HOST (linkhistory path): same three states from the
        # host's own saved passwords.
        browser, pg = _host_web_page(pw, port, 390, 844)
        try:
            pg.evaluate("() => setTab('send')")
            pg.wait_for_timeout(500)
            pg.click("#mddtoggle")
            pg.wait_for_function(
                "() => [...document.querySelectorAll('#mddlist .ddopt')].length >= 3",
                timeout=8000)
            pg.wait_for_timeout(1200)
            rows = pg.evaluate("""() => [...document.querySelectorAll('#mddlist .ddopt')]
              .map(r => r.innerText.replace(/\\n/g, ' | '))""")
            print("ITEM5A host rows: %s" % rows)
            by_name = {}
            for r in rows:
                for n in ("pwlist1", "pwlist2", "pwlist3"):
                    if r.startswith(n):
                        by_name[n] = r
            assert "••••••" in by_name["pwlist1"], by_name
            assert "Locked - No Saved Password" in by_name["pwlist2"], by_name
            assert "No password" in by_name["pwlist3"], by_name
            print("ITEM5A HOST: same three states from /api/linkhistory")
        finally:
            browser.close()


# --- (5b) MB fits all cards without scrolling ---

def _fit_measure(pg):
    return pg.evaluate("""() => {
      const de = document.documentElement;
      const tabs = document.querySelector('.mtabs');
      const sendCol = document.querySelector('.col[data-col="send"]');
      const msend = document.querySelector('.msend');
      const pillTop = tabs ? tabs.getBoundingClientRect().top : 0;
      const lastBottom = msend ? msend.getBoundingClientRect().bottom : 0;
      const open = document.querySelector('.col[data-col="send"] .open, .col[data-col="send"] .active');
      return {docSH: de.scrollHeight, docCH: de.clientHeight,
              colSH: sendCol ? sendCol.scrollHeight : -1,
              colCH: sendCol ? sendCol.clientHeight : -1,
              sendMayScroll: document.body.classList.contains('send-may-scroll'),
              slack: Math.round(pillTop - lastBottom),
              lastBottom: Math.round(lastBottom), pillTop: Math.round(pillTop)}; }""")


def test_item5b_fit_matrix(server):
    """(5b) MB: at 360/390/414/430px x 844 and x 700, on all
    three tabs, the document and the send column never scroll;
    the send stack ends with slack above the pill tabs."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink", {"name": "fitlink"})
    assert s == 200 and j["ok"], j
    folder = j["folder"]
    for i in range(2):
        s, j = client.j("POST", "/api/snippet", {"text": "fit note %d" % i})
        assert s == 200 and j["ok"], j
    open(os.path.join(folder, "fit.txt"), "w").write("fit\n")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        for width, height in [(360, 844), (390, 844), (414, 844),
                              (430, 844), (360, 700), (390, 700),
                              (430, 700)]:
            browser, ctx, pg, fwd = _guest_page(pw, port, width, height)
            try:
                _wait_authed(pg)
                for tab in ("send", "notes", "files"):
                    pg.evaluate("(t) => setTab(t)", tab)
                    pg.wait_for_timeout(600)
                    m = pg.evaluate("""() => { const de = document.documentElement;
                      const col = document.querySelector('.col[data-col="' + document.body.dataset.mtab + '"]');
                      return {docSH: de.scrollHeight, docCH: de.clientHeight,
                              colSH: col ? col.scrollHeight : -1, colCH: col ? col.clientHeight : -1,
                              mayScroll: document.body.classList.contains('send-may-scroll')}; }""")
                    assert m["docSH"] <= m["docCH"], \
                        "%dx%d %s: doc scrolls %s > %s" % (width, height, tab, m["docSH"], m["docCH"])
                    assert m["colSH"] <= m["colCH"], \
                        "%dx%d %s: column scrolls %s > %s" % (width, height, tab, m["colSH"], m["colCH"])
                    assert m["mayScroll"] is False, \
                        "%dx%d %s: send-may-scroll set" % (width, height, tab)
                    if tab == "send":
                        fm = _fit_measure(pg)
                        assert fm["slack"] >= 0, "%dx%d: send stack overlaps pill tabs: %s" % (width, height, fm)
                        print("ITEM5B %dx%d send: doc %d/%d col %d/%d slack %dpx" % (
                            width, height, fm["docSH"], fm["docCH"], fm["colSH"], fm["colCH"], fm["slack"]))
                if (width, height) in [(390, 844), (390, 700)]:
                    pg.evaluate("() => setTab('send')")
                    pg.wait_for_timeout(500)
                    pg.screenshot(path="%s/r54_item5b_fit_%dx%d.png" % (PROOF, width, height))
            finally:
                browser.close()
                fwd.stop.set()
    print("ITEM5B: all 7 sizes x 3 tabs fit without scrolling")


# --- (6) Starred filter + greyed stars ---

def test_item6_starred_toggle_and_greyed(server):
    """(6) The Starred filter's on/off states are clearly
    different in dark AND light mode (measured colours, fill,
    border, aria-pressed). A starred note whose star permission
    is removed still shows a filled GREY star; an unstarred one
    stays a plain greyed outline."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink", {"name": "starlink"})
    assert s == 200 and j["ok"], j
    ids = []
    for i, txt in enumerate(["starred note", "plain note"]):
        s, j = client.j("POST", "/api/snippet", {"text": txt})
        assert s == 200 and j["ok"], j
        ids.append(j["id"])
    s, j = client.j("POST", "/api/notes/star", {"id": ids[0], "starred": True})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        for light in (False, True):
            browser, ctx, pg, fwd = _guest_page(pw, port, 390, 844, light=light)
            try:
                _wait_authed(pg)
                pg.evaluate("() => setTab('notes')")
                pg.wait_for_timeout(600)
                pg.wait_for_selector("[data-star]", timeout=5000)
                off = pg.evaluate("""() => { const b = document.querySelector('#starfilter');
                  const cs = getComputedStyle(b); const sv = b.querySelector('svg');
                  return {bg: cs.backgroundColor, img: cs.backgroundImage, color: cs.color,
                          border: cs.borderColor, svgFill: getComputedStyle(sv).fill,
                          pressed: b.getAttribute('aria-pressed')}; }""")
                assert off["pressed"] == "false", off
                pg.click("#starfilter")
                pg.wait_for_timeout(500)
                on = pg.evaluate("""() => { const b = document.querySelector('#starfilter');
                  const cs = getComputedStyle(b); const sv = b.querySelector('svg');
                  return {bg: cs.backgroundColor, img: cs.backgroundImage, color: cs.color,
                          border: cs.borderColor, svgFill: getComputedStyle(sv).fill,
                          pressed: b.getAttribute('aria-pressed')}; }""")
                assert on["pressed"] == "true", on
                # On vs off must differ clearly, on both themes.
                assert on["img"] != off["img"] and "gradient" in on["img"], on
                assert on["color"] == "rgb(35, 19, 3)", on
                assert off["color"] != on["color"], (off, on)
                assert on["svgFill"] == "rgb(35, 19, 3)", on
                print("ITEM6 %s: off=%s on=%s" % ("light" if light else "dark", off, on))
                pg.click("#starfilter")  # back off
                pg.wait_for_timeout(400)
                pg.screenshot(path="%s/r54_item6_toggle_%s.png" % (
                    PROOF, "light" if light else "dark"))
                if not light:
                    # Greyed stars: host removes the star permission.
                    s, j = client.j("POST", "/api/permissions",
                                    {"permissions": {"star_notes": False}})
                    assert s == 200 and j["ok"], j
                    pg.wait_for_timeout(6000)  # next checkAuth poll
                    pg.wait_for_function(
                        "() => document.querySelectorAll('[data-star].deloff').length >= 2",
                        timeout=10000)
                    st = pg.evaluate("""() => [...document.querySelectorAll('[data-star]')].map(el => {
                      const cs = getComputedStyle(el);
                      return {starred: el.classList.contains('starred'),
                              deloff: el.classList.contains('deloff'),
                              op: parseFloat(cs.opacity),
                              fill: getComputedStyle(el.querySelector('svg')).fill,
                              text: el.closest('.snipcard').querySelector('.sniptext').textContent.trim()}; })""")
                    starred = [x for x in st if x["text"] == "starred note"][0]
                    plain = [x for x in st if x["text"] == "plain note"][0]
                    assert starred["starred"] and starred["deloff"], starred
                    assert plain["deloff"] and not plain["starred"], plain
                    assert abs(starred["op"] - 0.6) < 0.05, starred
                    assert abs(plain["op"] - 0.25) < 0.05, plain
                    assert starred["fill"] == "rgb(156, 163, 175)", starred
                    assert plain["fill"] not in ("rgb(251, 191, 36)", "rgb(156, 163, 175)"), plain
                    pg.screenshot(path="%s/r54_item6_greyed.png" % PROOF)
                    print("ITEM6 GREYED: starred=%s plain=%s" % (starred, plain))
                    # Restore the permission for other tests.
                    s, j = client.j("POST", "/api/permissions",
                                    {"permissions": {"star_notes": True}})
                    assert s == 200 and j["ok"], j
            finally:
                browser.close()
                fwd.stop.set()
    print("ITEM6: toggle clearly distinct dark + light; greyed starred stays visibly starred")
