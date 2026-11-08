"""v2.8.36 round (Essef Nov 7, ~1:32-1:35 AM PT) -- WEB/DESKTOP
track only, local test build only. TEN items, nothing else:

  (1) MENU ALL 4 CORNERS ROUNDED: frameless PC menu
      border-radius 18px on every corner (2.8.35 rounded only
      the two right corners). No resize.
  (2) SAVE PASSWORD -- CORRECT LOCK SEMANTICS (server + web):
      unchecked + typed password sends the password with
      save_password:false -- hash only, STILL LOCKED. Checked +
      password -> locked + saved. Unchecked + no password ->
      open. Typing no longer auto-checks the box. History shows
      dots / "Locked - No Saved Password" / "No password"; eye
      only when saved. Checkbox sync = retrievable copy exists.
  (3) OPEN ADDRESSES -- SAVE PASSWORD DISABLED (web): open
      address -> Save Password checkbox disabled/greyed on the
      host Set Up dialog AND the guest Connect card.
  (4) GUEST CONNECT DROPDOWN: saved-address rows show the
      server password state -- "••••••" saved, "No Password
      Saved" locked-not-saved, "No password" open.
  (5) REMOVE "Password set for this address." text (PC Your
      Address window). Locked pill + unauth text stay.
  (6) REMOVE ADDRESS dialog Delete button gains the trash icon.
  (7) WEB PREVIEW: Download button ANIMATES to Open only on a
      successful download (discard/reject/failure stays
      Download). Desktop bridge preview untouched.
  (8) SAVED ON THIS DEVICE: new Delete button (trash icon +
      "Delete", same size as Back), Back icon BLUE, selection
      mode (Select All / Cancel / Delete, "Select files") --
      same text in the web Files tab bar too.
  (9) CONNECTED POPUP MERGED: one smaller popup -- green icon
      + "Connected to <address>" centred inside; no separate
      toast alongside showConnPop("connected"). Failed state
      unchanged.
 (10) REMOVE the two unwanted texts on Saved on this device:
      "Files you downloaded through Drop on this device. Works
      without a connection ..." and "Files are also in this
      phone's Downloads folder."
"""
import ast
import json
import os
import re
import socket
import subprocess
import sys
import time
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
from test_link_round2 import server  # noqa: F401,E402
from test_link_round2 import Client  # noqa: E402
from test_link_round34 import _Fwd  # noqa: E402
from test_link_round46 import _pc_page  # noqa: E402

PAGE = D.PAGE
SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py"),
           encoding="utf-8").read()

PROOF = "/home/hatch/workspace/dropit-proof-round51"
os.makedirs(PROOF, exist_ok=True)

LEGACY_ZIP = "/home/hatch/workspace/dropit-desktop-v2.8.35.zip"


def test_version_is_2_8_36():
    assert D.VERSION == "2.8.36", D.VERSION


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
        p = os.path.join(PROOF, "r51_script%d.js" % i)
        open(p, "w", encoding="utf-8").write(s)
        r = subprocess.run(["node", "--check", p],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_markers_menu_radius():
    """(1) All four corners rounded on the frameless PC menu;
    the 2.8.35 two-corner rule is gone."""
    assert ("html.pcapp.frameless #sidebar { top:44px; z-index:80;"
            " border-radius:18px; }" in PAGE)
    assert "border-radius:0 18px 18px 0" not in PAGE


def test_markers_no_password_set_text():
    """(5) The locked-branch text is gone (the comment naming it
    stays); the pill + unauth strings stay."""
    assert '? "Password set for this address." : ""' not in PAGE
    assert "Locked address" in PAGE
    assert "This address is locked. Unlock with the current password" in PAGE


def test_markers_select_files():
    """(8) "Select files" everywhere; the old wording is gone."""
    assert "Select the files to delete" not in PAGE
    assert "Select files to delete" not in PAGE
    assert '<span class="delcount" id="delcount">Select files</span>' in PAGE
    assert '<span class="delcount" id="svcount">Select files</span>' in PAGE
    assert '<span class="delcount" id="gsvcount">Select files</span>' in PAGE


def test_markers_saved_texts_removed():
    """(10) Both unwanted Saved-view texts gone, CSS included."""
    assert "Files you downloaded through Drop on this device" not in PAGE
    assert "Files are also in this phone's Downloads folder" not in PAGE
    assert "gsavedhint" not in PAGE
    assert "gsavedtip" not in PAGE


def test_markers_conn_popup():
    """(9) showConnPop takes the address; small-box CSS exists;
    the three connect-path toasts are gone (doLogin, lock-set,
    host Save, unlock and password-removal toasts stay)."""
    assert "function showConnPop(state, address)" in PAGE
    assert 'tx.textContent = address ? ("Connected to " + address)' in PAGE
    assert ".connpop.small .connbox { width:min(280px,88vw);" in PAGE
    assert PAGE.count('showConnPop("connected", cj.display_address') == 3
    assert 'toast("Connected to " + (cj.display_address || name));' not in PAGE
    assert 'toast("Connected to " + (cj.display_address || bareM));' not in PAGE
    assert "Unable to Connect" in PAGE


def test_markers_remove_dialog_icon():
    """(6) Trash SVG inside the Remove Address Delete button."""
    assert 'id="addrremconfirm"><svg viewBox="0 0 24 24"' in PAGE
    assert ".addrrembox .addrremrow .btn svg { width:16px;" in PAGE


def test_markers_preview_animation():
    """(7) Web preview Download animates to Open via the
    fetch-based downloadFile path (success only)."""
    assert "@keyframes pvdlflip" in PAGE
    assert ".previewbox .pvdl.pvdlswap { animation:pvdlflip .38s ease; }" in PAGE
    assert "downloadFile({name: name, size: size}, dl, true)" in PAGE
    assert 'dl.textContent = "Open"; }, 170);' in PAGE


def test_markers_save_password_client():
    """(2)(3)(4) Client-side markers: history states, no
    auto-check, disabled-on-open, guest dropdown strings."""
    assert '"Locked - No Saved Password"' in PAGE
    assert '"No Password Saved"' in PAGE
    assert "async function renderGuestRecent(){" in PAGE
    assert '$("#lkpw").addEventListener("input", () => { lkPwTouched = true; });' in PAGE
    assert "body.save_password = savePw" in PAGE
    assert "body.save_password = false" in PAGE
    assert "_savePwBox.disabled = !!_openAddr;" in PAGE
    assert "_sc2.disabled = true; _sc2.checked = false;" in PAGE


# --- (2) server: Save Password lock semantics ---

def _auth(client):
    status, j = client.j("GET", "/api/authstate")
    assert status == 200 and j["ok"], j
    return j


def _hist(client):
    status, j = client.j("GET", "/api/linkhistory")
    assert status == 200 and j["ok"], j
    return {e["key"]: e for e in j["entries"]}


def _linkpw(client, key):
    return client.j("GET", "/api/linkpassword?link=" + key)


def test_save_password_matrix_server(server):
    """(2) (a) checked+pw -> locked+saved; (b) unchecked+pw ->
    STILL LOCKED but hash-only; (c) unchecked+no pw -> open;
    default (no flag) preserves old behaviour; same password +
    save:false drops the saved copy but keeps the lock."""
    client, base, proc, port, home = server
    # (a) checked + password
    s, j = client.j("POST", "/api/setlink",
                    {"name": "alpha", "password": "pw-one",
                     "save_password": True})
    assert s == 200 and j["ok"], j
    st = _auth(client)
    assert st["locked"] is True and st["password_saved"] is True, st
    assert st["has_password"] is True, st
    h = _hist(client)["alpha"]
    assert h == {"name": "alpha", "key": "alpha", "has_password": True,
                 "locked": True, "password_saved": True}, h
    s, j = _linkpw(client, "alpha")
    assert s == 200 and j["ok"] and j["password"] == "pw-one", j
    # (b) unchecked + password -> locked, hash only
    s, j = client.j("POST", "/api/setlink",
                    {"name": "beta", "password": "pw-two",
                     "save_password": False})
    assert s == 200 and j["ok"], j
    st = _auth(client)
    assert st["locked"] is True and st["password_saved"] is False, st
    assert st["has_password"] is True, st
    h = _hist(client)["beta"]
    assert h["locked"] is True and h["password_saved"] is False, h
    assert h["has_password"] is True, h
    s, j = _linkpw(client, "beta")
    assert j.get("error") == "not_retrievable", j
    # (c) unchecked + no password -> open
    s, j = client.j("POST", "/api/setlink",
                    {"name": "gamma", "password": "",
                     "save_password": False})
    assert s == 200 and j["ok"], j
    st = _auth(client)
    assert st["locked"] is False and st["password_saved"] is False, st
    assert st["has_password"] is False, st
    h = _hist(client)["gamma"]
    assert h["locked"] is False and h["password_saved"] is False, h
    # default (flag absent) == old behaviour: saved
    s, j = client.j("POST", "/api/setlink",
                    {"name": "delta", "password": "pw-four"})
    assert s == 200 and j["ok"], j
    assert _auth(client)["password_saved"] is True
    # same password + save:false drops the copy, keeps the lock
    s, j = client.j("POST", "/api/setlink",
                    {"name": "delta", "password": "pw-four",
                     "save_password": False})
    assert s == 200 and j["ok"], j
    st = _auth(client)
    assert st["locked"] is True and st["password_saved"] is False, st
    assert st["has_password"] is True, st
    s, j = _linkpw(client, "delta")
    assert j.get("error") == "not_retrievable", j
    # setlinkpassword honours the flag too
    s, j = client.j("POST", "/api/setlinkpassword",
                    {"password": "pw-five", "save_password": False})
    assert s == 200 and j["ok"], j
    st = _auth(client)
    assert st["locked"] is True and st["password_saved"] is False, st
    print("MATRIX: alpha saved+locked, beta hash-only+locked,"
          " gamma open, delta dropped-copy+locked")


def test_set_address_password_unit():
    """(2) Core helper, in-process: save=False stores the hash
    only, clears the encrypted copy, locks; empty clears all."""
    cfg = {"address_name": "unit", "addresses": {}}
    D._set_address_password(cfg, "unit", "secret", save=False)
    ent = cfg["addresses"]["unit"]
    assert ent["pass"] and D._check_pw("secret", ent["pass"])
    assert ent["pass_enc"] == ""
    assert ent["locked"] is True
    assert cfg["address_pass_enc"] == ""
    D._set_address_password(cfg, "unit", "secret", save=True)
    ent = cfg["addresses"]["unit"]
    assert ent["pass_enc"] and D._decrypt_pw(ent["pass_enc"]) == "secret"
    assert D._password_saved_for(cfg, "unit") is True
    D._set_address_password(cfg, "unit", "", save=True)
    assert cfg["addresses"]["unit"]["pass"] == ""
    assert cfg["addresses"]["unit"]["locked"] is False

# --- Playwright helpers ---

def _host_web_page(pw, port, width, height):
    """Host page over plain HTTP with NO pywebview bridge stub
    -- the real web path (the stub makes hasBridge() true, so
    previews read Open instead of Download)."""
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    ctx = browser.new_context(viewport={"width": width, "height": height})
    pg = ctx.new_page()
    pg.goto("http://127.0.0.1:%d/" % port)
    pg.wait_for_function(
        "() => typeof AUTH !== 'undefined' && AUTH.host", timeout=10000)
    pg.wait_for_timeout(900)
    return browser, pg


def _guest_page(pw, port, width, height, init_script=None, light=False):
    """Guest page: traffic forwarded so the server sees a
    non-loopback (guest) source IP, no bridge stub."""
    fwd = _Fwd(port)
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    ctx = browser.new_context(viewport={"width": width, "height": height})
    if init_script:
        ctx.add_init_script(init_script)
    pg = ctx.new_page()
    pg.goto("http://127.0.0.3:%d/" % fwd.port)
    # Attached, not visible: an open current address
    # auto-connects first, so the login button starts hidden
    # until the test logs out to reach the login form.
    pg.wait_for_selector("#gloginbtn", state="attached", timeout=10000)
    pg.wait_for_timeout(900)
    if light:
        pg.evaluate("() => document.documentElement.classList.add('light')")
        pg.wait_for_timeout(300)
    return browser, ctx, pg, fwd


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _legacy_server(tmp_path):
    """2.8.35 server from the shipped zip, for the menu
    no-size-change comparison."""
    dest = tmp_path / "legacy35"
    with zipfile.ZipFile(LEGACY_ZIP) as z:
        z.extractall(dest)
    root = dest / "dropit"
    home = tmp_path / "legacy-home"
    base = tmp_path / "legacy-base"
    base.mkdir()
    (home / ".config" / "DropIt").mkdir(parents=True)
    port = _free_port()
    env = dict(os.environ, HOME=str(home))
    proc = subprocess.Popen(
        [sys.executable, "dropit.py", "--port", str(port),
         "--dir", str(base)],
        cwd=str(root), env=env,
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
            raise RuntimeError("legacy server did not come up")
        yield client, base, proc, port, home
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


MENU_MEASURE = """() => {
  const sb = document.querySelector('#sidebar');
  const cs = getComputedStyle(sb);
  const r = sb.getBoundingClientRect();
  return {top: Math.round(r.top), w: Math.round(r.width),
    h: Math.round(r.height), tl: cs.borderTopLeftRadius,
    tr: cs.borderTopRightRadius, br: cs.borderBottomRightRadius,
    bl: cs.borderBottomLeftRadius};
}"""


def test_menu_all_corners_rounded_no_resize(server, tmp_path):
    """(1) All four corners 18px on the frameless PC menu, and
    the menu box is exactly the 2.8.35 size (width/height/top)."""
    client, base, proc, port, home = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, pg = _pc_page(pw, port, 1280, 800, frameless=True)
        try:
            pg.click("#menubtn")
            pg.wait_for_timeout(600)
            m = pg.evaluate(MENU_MEASURE)
            assert m["tl"] == "18px" and m["tr"] == "18px", m
            assert m["br"] == "18px" and m["bl"] == "18px", m
            assert m["top"] == 44, m
            pg.screenshot(path="%s/r51_menu_dark.png" % PROOF)
            print("MENU 2.8.36: %s" % m)
        finally:
            browser.close()
        # Same measurement against the shipped 2.8.35 build.
        for c2, b2, p2, po2, h2 in _legacy_server(tmp_path):
            browser2, pg2 = _pc_page(pw, po2, 1280, 800, frameless=True)
            try:
                pg2.click("#menubtn")
                pg2.wait_for_timeout(600)
                m2 = pg2.evaluate(MENU_MEASURE)
                assert m2["tr"] == "18px" and m2["br"] == "18px", m2
                assert m2["tl"] == "0px" and m2["bl"] == "0px", m2
                assert (m2["w"], m2["h"], m2["top"]) == (m["w"], m["h"], m["top"]), (m, m2)
                print("MENU 2.8.35: %s (same box as 2.8.36)" % m2)
            finally:
                browser2.close()


def _lk_state(pg):
    return pg.evaluate(
        "() => ({lkstate: document.querySelector('#lkstate').textContent,"
        " pill: document.querySelector('#lklockedwarn').classList.contains('show'),"
        " saveChecked: document.querySelector('#lksavepwchk').checked,"
        " saveDisabled: document.querySelector('#lksavepwchk').disabled,"
        " pwVal: document.querySelector('#lkpw').value})")


def _hist_rows(pg):
    pg.evaluate("() => document.querySelector('#lkcurview').click()")
    pg.wait_for_timeout(500)
    return pg.evaluate(
        "() => [...document.querySelectorAll('#lkddlist .ddopt')]"
        ".map(o => o.textContent.replace(/\\s+/g, ' ').trim())")


def test_host_save_password_matrix_ui(server):
    """(2)(5) Live host Set Up flow: (a) locked+saved shows
    dots, pill on, lkstate empty, box checked; typing never
    auto-checks; (b) unchecked+typed pw SAVES LOCKED but
    hash-only ("Locked - No Saved Password", no reveal);
    (c) unchecked+empty -> open ("No password")."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink",
                    {"name": "alpha", "password": "pw-one",
                     "save_password": True})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, pg = _pc_page(pw, port, 1280, 800, frameless=True)
        try:
            pg.evaluate("() => openLinkWin()")
            pg.wait_for_timeout(700)
            st = _lk_state(pg)
            assert st["lkstate"] == "", st
            assert st["pill"] is True, st
            assert st["saveChecked"] is True, st
            assert st["saveDisabled"] is False, st
            assert st["pwVal"] == "pw-one", st
            rows = _hist_rows(pg)
            assert any("alpha" in r and "••••••" in r for r in rows), rows
            pg.screenshot(path="%s/r51_setup_alpha.png" % PROOF)
            # (b) uncheck, type a password: box must STAY unchecked.
            # Close the history dropdown first (it covers the
            # password row), and click the checkbox via JS -- the
            # input itself is visually hidden behind .permbox.
            pg.evaluate("() => document.querySelector('#lkpw').click()")
            pg.wait_for_timeout(200)
            pg.evaluate("() => document.querySelector('#lksavepwchk').click()")
            pg.wait_for_timeout(200)
            assert pg.evaluate(
                "() => document.querySelector('#lksavepwchk').checked") is False
            pg.fill("#lkpw", "pw-two")
            pg.wait_for_timeout(200)
            assert pg.evaluate(
                "() => document.querySelector('#lksavepwchk').checked") is False
            pg.fill("#lkin", "beta")
            pg.click("#lkset")
            pg.wait_for_timeout(900)
            st = _auth(client)
            assert st["locked"] is True and st["password_saved"] is False, st
            s2, j2 = client.j("GET", "/api/linkpassword?link=beta")
            assert j2.get("error") == "not_retrievable", j2
            st2 = _lk_state(pg)
            assert st2["lkstate"] == "" and st2["pill"] is True, st2
            assert st2["saveChecked"] is False, st2
            rows = _hist_rows(pg)
            assert any("beta" in r and "Locked - No Saved Password" in r
                       for r in rows), rows
            assert not any("beta" in r and "••••••" in r for r in rows), rows
            pg.screenshot(path="%s/r51_setup_beta.png" % PROOF)
            # (c) unchecked + empty password -> open.
            pg.fill("#lkin", "gamma")
            pg.fill("#lkpw", "")
            pg.click("#lkset")
            pg.wait_for_timeout(900)
            st = _auth(client)
            assert st["locked"] is False and st["has_password"] is False, st
            rows = _hist_rows(pg)
            assert any("gamma" in r and "No password" in r for r in rows), rows
            print("UI MATRIX: alpha dots, beta locked-not-saved,"
                  " gamma open; lkstate empty throughout")
        finally:
            browser.close()


def test_open_address_save_pw_disabled_host(server):
    """(3) Host Set Up: open address -> Save Password disabled
    + unchecked; locked address -> enabled again."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink", {"name": "openy"})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, pg = _pc_page(pw, port, 1280, 800, frameless=True)
        try:
            pg.evaluate("() => openLinkWin()")
            pg.wait_for_timeout(600)
            assert pg.evaluate(
                "() => document.querySelector('#lksavepwchk').disabled") is True
            assert pg.evaluate(
                "() => document.querySelector('#lksavepwchk').checked") is False
            pg.evaluate("() => closeLinkWin()")
            s, j = client.j("POST", "/api/setlink",
                            {"name": "locky", "password": "pw-locky",
                             "save_password": True})
            assert s == 200 and j["ok"], j
            # Refresh the page's cached AUTH first (the dialog
            # reads it; the API switch happened out-of-band).
            pg.evaluate("async () => { await checkAuth(); openLinkWin(); }")
            pg.wait_for_timeout(600)
            assert pg.evaluate(
                "() => document.querySelector('#lksavepwchk').disabled") is False
            print("HOST DISABLE: open -> disabled, locked -> enabled")
        finally:
            browser.close()


def test_guest_dropdown_conn_popup(server):
    """(3)(4)(9) Guest Connect card: the open current address
    auto-connects, so the test logs out to reach the login
    form; typing the open address greys out Save password (+
    the password field); the locked address re-enables both;
    the saved-addresses dropdown shows "No Password Saved"
    (locked, nothing saved here) vs "No password" (open);
    connecting shows ONE small popup with "Connected to locky"
    inside and no duplicate toast."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink",
                    {"name": "locky", "password": "pw-locky",
                     "save_password": True})
    assert s == 200 and j["ok"], j
    s, j = client.j("POST", "/api/setlink", {"name": "openy"})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    # NB: a bare "() => {...}" init string is never invoked --
    # seed with plain statements.
    seed = ("localStorage.setItem('drop_link_use',"
            " JSON.stringify({locky: 5, openy: 3}));")
    with sync_playwright() as pw:
        browser, ctx, pg, fwd = _guest_page(pw, port, 390, 844,
                                            init_script=seed)
        try:
            # Open current address auto-connects; log out to
            # reach the login form.
            pg.wait_for_timeout(1500)
            pg.evaluate("() => doLogout()")
            pg.wait_for_selector("#gloginbtn:visible", timeout=5000)
            # (3) open address -> both fields greyed out.
            pg.fill("#gloginlink", "openy")
            pg.wait_for_timeout(800)
            assert pg.evaluate(
                "() => document.querySelector('#gloginpw').disabled") is True
            assert pg.evaluate(
                "() => document.querySelector('#gloginsavechk').disabled") is True
            # locked address -> both back.
            pg.fill("#gloginlink", "locky")
            pg.wait_for_timeout(800)
            assert pg.evaluate(
                "() => document.querySelector('#gloginpw').disabled") is False
            assert pg.evaluate(
                "() => document.querySelector('#gloginsavechk').disabled") is False
            # (4) dropdown rows.
            pg.click("#gddchevbtn")
            pg.wait_for_timeout(1200)
            rows = pg.evaluate(
                "() => [...document.querySelectorAll('#gddlist .ddopt')]"
                ".map(o => o.textContent.replace(/\\s+/g, ' ').trim())")
            assert any("locky" in r and "No Password Saved" in r
                       for r in rows), rows
            assert any("openy" in r and "No password" in r
                       for r in rows), rows
            pg.screenshot(path="%s/r51_guest_dropdown.png" % PROOF)
            # (9) connect to locky: a guest can only connect to
            # the PC's CURRENT address, so switch it to locky
            # first (doGuestLogin refreshes the name itself).
            s, j = client.j("POST", "/api/setlink",
                            {"name": "locky", "password": "pw-locky",
                             "save_password": True})
            assert s == 200 and j["ok"], j
            pg.click("#gddchevbtn")  # close the dropdown first
            pg.wait_for_timeout(300)
            pg.fill("#gloginlink", "locky")
            pg.wait_for_timeout(400)
            pg.fill("#gloginpw", "pw-locky")
            pg.click("#gloginbtn")
            pg.wait_for_selector("#connpop.open", timeout=5000)
            pg.wait_for_function(
                "() => document.querySelector('#conntext').textContent"
                ".startsWith('Connected to')", timeout=5000)
            pop = pg.evaluate(
                "() => { const pop = document.querySelector('#connpop');"
                " const box = document.querySelector('.connbox')"
                ".getBoundingClientRect(); return {small: pop.classList"
                ".contains('small'), text: document.querySelector"
                "('#conntext').textContent, w: Math.round(box.width),"
                " toast: document.querySelector('#toast').classList"
                ".contains('show')}; }")
            assert pop["small"] is True, pop
            assert pop["text"] == "Connected to locky", pop
            assert pop["w"] <= 290, pop
            assert pop["toast"] is False, pop
            pg.wait_for_timeout(300)
            pg.screenshot(path="%s/r51_connpop.png" % PROOF)
            print("GUEST: dropdown + one small popup %s" % pop)
        finally:
            browser.close()


def test_saved_view_delete_blue_back(server):
    """(8)(10) Saved on this device (guest page): the two
    unwanted texts are gone; Delete is the same size as Back;
    Back is blue; Delete opens selection mode (Select All /
    Cancel / Delete, "Select files"); deleting removes the
    picked file from this device only."""
    client, base, proc, port, home = server
    # Locked current address, so the guest login form shows on
    # load (an open address would auto-connect to the board).
    s, j = client.j("POST", "/api/setlink",
                    {"name": "savey", "password": "pw-savey",
                     "save_password": True})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    seed = ("localStorage.setItem('dropit_dl', JSON.stringify("
            "{'a.txt': {size: 10, ts: 1700000000},"
            " 'b.png': {size: 20, ts: 1700000001}}));")
    with sync_playwright() as pw:
        browser, ctx, pg, fwd = _guest_page(pw, port, 390, 844,
                                            init_script=seed)
        try:
            pg.click("#gsavedbtn")
            pg.wait_for_timeout(600)
            assert pg.evaluate(
                "() => document.querySelector('.gsavedhint')") is None
            assert pg.evaluate(
                "() => document.querySelector('.gsavedtip')") is None
            txt = pg.evaluate("() => document.body.innerText")
            assert "Files you downloaded through Drop" not in txt
            assert "Files are also in this phone's Downloads folder" not in txt
            sizes = pg.evaluate(
                "() => { const b = document.querySelector('#gsavedback')"
                ".getBoundingClientRect(), d = document.querySelector"
                "('#gsaveddel').getBoundingClientRect(); return {bh:"
                " Math.round(b.height), dh: Math.round(d.height),"
                " bw: Math.round(b.width), dw: Math.round(d.width),"
                " color: getComputedStyle(document.querySelector"
                "('#gsavedback')).color}; }")
            assert sizes["bh"] == sizes["dh"], sizes
            assert sizes["color"] == "rgb(59, 130, 246)", sizes
            assert pg.evaluate(
                "() => document.querySelector('#gsaveddel').disabled") is False
            pg.screenshot(path="%s/r51_saved_view.png" % PROOF)
            # Selection mode.
            pg.click("#gsaveddel")
            pg.wait_for_timeout(400)
            assert pg.evaluate(
                "() => document.querySelector('#gsvbar').classList"
                ".contains('show')") is True
            assert pg.evaluate(
                "() => document.querySelector('#gsvcount').textContent") == "Select files"
            assert pg.evaluate(
                "() => [...document.querySelectorAll('#gsvbar button')]"
                ".map(b => b.textContent.trim())") == ["Cancel", "All", "Delete"]
            pg.click(".gsavedrow >> nth=0")
            pg.wait_for_timeout(300)
            assert pg.evaluate(
                "() => document.querySelector('#gsvcount').textContent") == "1 selected"
            pg.click("#gsvall")
            pg.wait_for_timeout(300)
            assert pg.evaluate(
                "() => document.querySelector('#gsvcount').textContent") == "2 selected"
            pg.click("#gsvcancel")
            pg.wait_for_timeout(300)
            assert pg.evaluate(
                "() => document.querySelector('#gsvbar').classList"
                ".contains('show')") is False
            # Delete one (b.png is first: newest ts first).
            pg.on("dialog", lambda d: d.accept())
            pg.click("#gsaveddel")
            pg.wait_for_timeout(300)
            pg.click(".gsavedrow >> nth=0")
            pg.wait_for_timeout(200)
            pg.click("#gsvconfirm")
            pg.wait_for_timeout(600)
            left = pg.evaluate(
                "() => ({rows: document.querySelectorAll('.gsavedrow').length,"
                " dl: JSON.parse(localStorage.getItem('dropit_dl') || '{}')})")
            assert left["rows"] == 1, left
            assert list(left["dl"].keys()) == ["a.txt"], left
            pg.screenshot(path="%s/r51_saved_delete.png" % PROOF)
            print("SAVED VIEW: %s" % sizes)
        finally:
            browser.close()


def test_preview_download_animates_to_open(server):
    """(7) Web preview: Download animates to Open on a saved
    download; a discarded download stays Download."""
    client, base, proc, port, home = server
    (base / "hello.txt").write_text("hello preview\n", encoding="utf-8")
    s, j = client.j("POST", "/api/setlink", {"name": "pvy"})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        # Plain web page (no bridge stub): the preview button
        # must read Download here, not the desktop Open.
        browser, pg = _host_web_page(pw, port, 1280, 800)
        try:
            pg.wait_for_selector(".frow .fname", timeout=10000)
            pg.click(".frow .fname")
            pg.wait_for_selector("#previewdl", timeout=5000)
            pg.wait_for_timeout(400)
            assert pg.evaluate(
                "() => document.querySelector('#previewdl').textContent") == "Download"
            # Save path -> animates to Open. (JS clicks: the
            # confirm dialog's button never reports stable to
            # Playwright while its pop-in runs.)
            pg.click("#previewdl")
            pg.wait_for_selector("#cfdlg.open", timeout=5000)
            pg.evaluate("() => document.querySelector('#cfyes').click()")
            pg.wait_for_timeout(1000)
            assert pg.evaluate(
                "() => document.querySelector('#previewdl').textContent") == "Open"
            pg.screenshot(path="%s/r51_preview_open.png" % PROOF)
            # Discard path -> stays Download.
            pg.click("#previewclose2")
            pg.wait_for_timeout(400)
            pg.click(".frow .fname")
            pg.wait_for_selector("#previewdl", timeout=5000)
            pg.wait_for_timeout(400)
            pg.click("#previewdl")
            pg.wait_for_selector("#cfdlg.open", timeout=5000)
            pg.evaluate("() => document.querySelector('#cfno').click()")
            pg.wait_for_timeout(600)
            assert pg.evaluate(
                "() => document.querySelector('#previewdl').textContent") == "Download"
            print("PREVIEW: save -> Open, discard -> Download")
        finally:
            browser.close()


def test_remove_dialog_delete_icon(server):
    """(6) Remove Address dialog Delete button carries the
    trash icon (same SVG as the other Delete buttons)."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink",
                    {"name": "rem1", "password": "pw-rem",
                     "save_password": True})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, pg = _pc_page(pw, port, 1280, 800, frameless=True)
        try:
            pg.evaluate("() => openLinkWin()")
            pg.wait_for_timeout(600)
            pg.evaluate("() => document.querySelector('#lkcurview').click()")
            pg.wait_for_timeout(500)
            pg.click('[data-delhist="rem1"]')
            pg.wait_for_timeout(500)
            has = pg.evaluate(
                "() => { const b = document.querySelector('#addrremconfirm');"
                " return {svg: !!b.querySelector('svg'),"
                " trash: b.innerHTML.includes('M19 6v14a2'),"
                " text: b.textContent.trim()}; }")
            assert has["svg"] is True and has["trash"] is True, has
            assert has["text"] == "Delete", has
            pg.screenshot(path="%s/r51_remove_dialog.png" % PROOF)
            pg.click("#addrremcancel")
            print("REMOVE DIALOG: %s" % has)
        finally:
            browser.close()
