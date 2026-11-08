"""v2.8.37 round (Essef Nov 7) -- WEB/DESKTOP track only, local
test build only. EIGHT items, nothing else:

  (1) SAVE PASSWORD IN SET PASSWORD POPUP: the popup gains a
      "Save password" checkbox, DISABLED while the password
      field is empty and ENABLED live as soon as any character
      is typed (input event). Checked + password -> locked +
      saved; unchecked + password -> still locked, hash only.
      The Set Up window's Save Password follows the same live
      rule (disabled while the field is empty AND the address
      is open; typing re-enables it even when the current
      address is open -- the 2.8.36 image-73 "UNABLE TO SAVE"
      bug). 2.8.36 lock semantics are otherwise unchanged.
  (2) DOWNLOAD -> OPEN SYNCED IN REAL TIME + PROMPT Z-INDEX
      (web): one shared downloaded-state store + one repaint
      (repaintDownloadButtons, called from markDownloaded) flips
      the file-row button AND the preview button together; the
      preview also opens from the shared state (an already
      downloaded file reads Open at once). The download confirm
      dialog (#cfdlg) renders ABOVE the preview (z 2000 > 1001)
      and is hit-testable while the preview is open.
  (3) SAVED ON THIS DEVICE BACK BUTTON STAYS BLUE: solid blue
      background + white text/icon, in BOTH themes.
  (4) REMOVE THE REFRESH BUTTON on mobile web: no refresh
      control exists anywhere in the 2.8.36 page (verified by
      DOM scan); a mobile-width CSS guard hides any
      refresh-titled control outright. Desktop untouched.
  (5) DUPLICATE CHECKBOX ON LOGIN SCREEN (PC WEB ONLY): when
      the guest Connect modal opens over the login page, the
      login page is hidden, so exactly ONE Save Password
      checkbox is live (the modal's); closing the modal brings
      the login page back if still unauthed. The plain login
      screen already shows exactly one checkbox at every width
      in Chromium (390-1920px, both themes); the duplicate
      reproduced at DOM level (two live Save Password
      checkboxes) whenever the modal was open over it.
  (6) EYE ALIGNMENT + "DEVICE" WORDING (web): the eye toggle
      is INSIDE the "Password For This Address" field on the
      Connect dialog, vertically centred on the input (it sat
      ~30px low, straddling the field's bottom edge, because it
      was positioned at 50% of the tall wrapped row); the web
      connect header reads "Connect To A Device".
  (7) TEXTS DISAPPEARING ON DESKTOP WHEN SWITCHING ADDRESSES:
      root causes fixed -- (a) paintAddressAll only filled
      #mpchost when empty, so after a switch it kept showing
      the PREVIOUS address (reproduced: on addrB, mpchost still
      read addrA); it now always refills, and the folder label
      is always refilled too (em dash when none). (b) A failed
      loadNotes/loadFiles wiped the list ("Could not load
      shared texts." / "...file list.") WITHOUT resetting the
      signature, so the next same-signature fetch returned
      early and the wiped message STUCK (reproduced: after a
      stale-address 401 + restore, texts stayed wiped). Failed
      reloads now keep the last good list on screen.
  (8) MENU REDESIGN FROM HIS HTML: dark navy (#090D16 outer,
      #0F172A cards, #1E293B borders), 28px outer radius,
      16px cards, logo tile + "Drop" + version header, amber
      status dot, 36px lock/pencil squares, cyan toggles,
      full-width blue-gradient Open Folder + purple-gradient
      Change Folder (folder-open / pen icons), SHOW + THEME
      cards. The menu COVERS THE TOP BAR on the frameless PC
      app (top:0, z 1600 above the title bar -- supersedes the
      2.8.35 "menu below the title bar" rule) and its border
      runs to the bottom, ending rounded. Contents and
      functionality are identical -- only the look changed.
"""
import ast
import json
import os
import re
import subprocess
import sys
import time

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

PROOF = "/home/hatch/workspace/dropit-proof-round52"
os.makedirs(PROOF, exist_ok=True)


def test_version_is_2_8_37():
    assert D.VERSION == "2.8.37", D.VERSION


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
        p = os.path.join(PROOF, "r52_script%d.js" % i)
        open(p, "w", encoding="utf-8").write(s)
        r = subprocess.run(["node", "--check", p],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_markers_item1_popup_checkbox():
    """(1) Popup checkbox exists (disabled in HTML), the live
    input rule, the reset on open, and save_password on Save;
    the Set Up live rule helper + its wiring."""
    assert 'id="lockpwsavechk" disabled' in PAGE
    assert 'class="permchk lockpwsavechk"' in PAGE
    assert "_lpsc0.checked = false; _lpsc0.disabled = true;" in PAGE
    assert "cb.disabled = !_lpin.value; if(!_lpin.value) cb.checked = false;" in PAGE
    assert "save_password: !!(_lpscb && _lpscb.checked)" in PAGE
    assert "function syncLkSavePw(){" in PAGE
    assert "box.disabled = !pwf.value && openAddr;" in PAGE
    assert "_savePwBox.disabled = !!_openAddr;" in PAGE
    assert 'syncLkSavePw(); });' in PAGE


def test_markers_item2_download_sync_zindex():
    """(2) Confirm dialog above the preview; the shared repaint;
    the preview opens from the shared downloaded state."""
    assert "#cfdlg { z-index:2000; }" in PAGE
    assert "function repaintDownloadButtons(name, size){" in PAGE
    assert "repaintDownloadButtons(f.name, f.size);" in PAGE
    assert "if(isDownloaded({name: name, size: size})){" in PAGE
    assert ".previewpop { display:none; position:fixed; inset:0; z-index:1001;" in PAGE


def test_markers_item3_saved_back_blue():
    """(3) Solid blue background + white text/icon, both themes;
    the old blue-text-only rules are gone."""
    assert "#gsavedback, html.light #gsavedback { background:#277ff0; color:#ffffff; border:none; }" in PAGE
    assert "#gsavedback { color:#3b82f6; }" not in PAGE
    assert "html.light #gsavedback { color:#1e6ad8; }" not in PAGE


def test_markers_item4_no_refresh():
    """(4) No refresh control exists in the page; the mobile
    guard hides any refresh-titled control outright."""
    assert 'id="refreshbtn"' not in PAGE
    assert 'title="Refresh"' not in PAGE
    assert 'aria-label="Refresh"' not in PAGE
    assert 'button[title*="Refresh" i]' in PAGE


def test_markers_item5_one_checkbox():
    """(5) The login page hides while the Connect modal is open
    (and comes back on close if still unauthed)."""
    assert '_gl0.dataset.lkHidden = "1";' in PAGE
    assert 'if(!(AUTH && AUTH.authed)) _gl1.classList.add("open");' in PAGE
    assert 'gl.dataset.lkHidden = "1";' in PAGE


def test_markers_item6_eye_and_device():
    """(6) Eye pinned to the input's centre; header wording."""
    assert "<b>Connect To A Device</b>" in PAGE
    assert "<b>Connect To A PC</b>" not in PAGE
    assert ".lkbox.guestcard .lkpwrow input { height:48px; }" in PAGE
    assert "top:24px; transform:translateY(-50%); width:36px; height:36px;" in PAGE


def test_markers_item7_no_wipe():
    """(7) Unconditional refills; failed reloads keep the lists."""
    assert 'window.__mpLastAddr' in PAGE
    assert 'if(!mp2.value || (st.address_name || "") !== (window.__mpLastAddr || "")) mp2.value = st.address_name || "";' in PAGE
    assert 'if(dl2) dl2.textContent = st.folder || "—";' in PAGE
    assert "Could not load shared texts." not in PAGE
    assert "Could not load file list." not in PAGE
    assert "if(mp2 && !mp2.value && st.address_name)" not in PAGE


def test_markers_item8_menu():
    """(8) Navy tokens, 28px outer / 16px cards, logo tile,
    36px square buttons, cyan toggles, gradient folder
    buttons, menu over the title bar (frameless)."""
    assert "#sidebar { background-color:#090D16;" in PAGE
    assert "border:1px solid #1E293B; border-radius:28px;" in PAGE
    assert "#sidebar .sbcard { background:#0F172A; border:1px solid #1E293B; border-radius:16px;" in PAGE
    assert "sblogotile" in PAGE
    assert "#sidebar .sblockbtn { flex:none; width:36px; height:36px; border-radius:12px;" in PAGE
    assert "#sidebar .sbsw { width:48px; height:24px;" in PAGE
    assert "#sidebar .sbsw.on { background:#38bdf8; }" in PAGE
    assert "background:linear-gradient(90deg,#2563EB,#3B82F6);" in PAGE
    assert "background:linear-gradient(90deg,#9333EA,#4F46E5);" in PAGE
    assert "#sidebar #sbopen, #sidebar #sbchange { display:flex; align-items:center; justify-content:center; width:100%;" in PAGE
    assert "html.pcapp.frameless #sidebar { top:0; z-index:1600; border-radius:28px; }" in PAGE
    assert "#sidebar .addot { background:#f59e0b !important;" in PAGE


# --- Playwright helpers (same shapes as round51) ---

def _host_web_page(pw, port, width, height):
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    ctx = browser.new_context(viewport={"width": width, "height": height})
    pg = ctx.new_page()
    pg.goto("http://127.0.0.1:%d/" % port)
    pg.wait_for_function(
        "() => typeof AUTH !== 'undefined' && AUTH.host", timeout=10000)
    pg.wait_for_timeout(900)
    return browser, pg


def _guest_page(pw, port, width, height, init_script=None, light=False):
    fwd = _Fwd(port)
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    ctx = browser.new_context(viewport={"width": width, "height": height})
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


def _auth(client):
    status, j = client.j("GET", "/api/authstate")
    assert status == 200 and j["ok"], j
    return j


def _hit_checkbox_count(pg):
    """Occlusion-aware count of visible Save-password labels:
    a label counts only if its centre hit-tests to itself."""
    return pg.evaluate("""() => {
      const isVis = el => { let n = el; while (n) { const cs = getComputedStyle(n);
        if (cs.display === 'none' || cs.visibility === 'hidden') return false;
        n = n.parentElement; } const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0; };
      let n = 0; const ids = [];
      [...document.querySelectorAll('label.permchk')].filter(isVis).forEach(l => {
        if (!/save password/i.test(l.textContent)) return;
        const r = l.getBoundingClientRect();
        const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
        if (hit && hit.closest('label') === l) { n++; ids.push((l.querySelector('input') || {}).id); }
      });
      return {n, ids};
    }""")


# --- (1) Set Password popup, live ---

def test_popup_save_password_live(server):
    """(1) Popup checkbox: disabled + unchecked on empty; typing
    enables it live; clearing disables + unchecks again.
    Unchecked + password -> locked, hash only. Checked +
    password -> locked + saved (second address)."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink", {"name": "popA"})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, pg = _pc_page(pw, port, 1280, 800, frameless=True)
        try:
            pg.evaluate("() => openLockPopup()")
            pg.wait_for_timeout(500)
            st = pg.evaluate("""() => ({dis: document.querySelector('#lockpwsavechk').disabled,
              chk: document.querySelector('#lockpwsavechk').checked,
              open: document.querySelector('#lockpwpop').classList.contains('open')})""")
            assert st == {"dis": True, "chk": False, "open": True}, st
            pg.fill("#lockpwin", "p")
            pg.wait_for_timeout(200)
            assert pg.evaluate(
                "() => document.querySelector('#lockpwsavechk').disabled") is False
            pg.fill("#lockpwin", "pw-pop-a")
            pg.wait_for_timeout(200)
            assert pg.evaluate(
                "() => document.querySelector('#lockpwsavechk').disabled") is False
            pg.fill("#lockpwin", "")
            pg.wait_for_timeout(200)
            st = pg.evaluate("""() => ({dis: document.querySelector('#lockpwsavechk').disabled,
              chk: document.querySelector('#lockpwsavechk').checked})""")
            assert st == {"dis": True, "chk": False}, st
            # Unchecked + password -> locked, hash only.
            pg.fill("#lockpwin", "pw-pop-a")
            pg.wait_for_timeout(200)
            pg.click("#lockpwsave")
            pg.wait_for_timeout(900)
            au = _auth(client)
            assert au["locked"] is True and au["password_saved"] is False, au
            s2, j2 = client.j("GET", "/api/linkpassword?link=popa")
            # Either error means the same thing: no retrievable
            # password (not_retrievable = hash-only entry,
            # not_found = entry has no stored password at all).
            assert j2.get("error") in ("not_retrievable", "not_found"), j2
            assert "password" not in j2, j2
            pg.screenshot(path="%s/r52_popup_unchecked.png" % PROOF)
            # Checked + password -> locked + saved (new address).
            s, j = client.j("POST", "/api/setlink", {"name": "popB"})
            assert s == 200 and j["ok"], j
            pg.evaluate("async () => { await checkAuth(); openLockPopup(); }")
            pg.wait_for_timeout(500)
            pg.fill("#lockpwin", "pw-pop-b")
            pg.wait_for_timeout(200)
            pg.evaluate("() => document.querySelector('#lockpwsavechk').click()")
            pg.wait_for_timeout(200)
            assert pg.evaluate(
                "() => document.querySelector('#lockpwsavechk').checked") is True
            pg.click("#lockpwsave")
            pg.wait_for_timeout(900)
            au = _auth(client)
            assert au["locked"] is True and au["password_saved"] is True, au
            s2, j2 = client.j("GET", "/api/linkpassword?link=popb")
            assert s2 == 200 and j2.get("password") == "pw-pop-b", j2
            pg.screenshot(path="%s/r52_popup_checked.png" % PROOF)
            print("POPUP: unchecked -> locked hash-only; checked -> locked+saved")
        finally:
            browser.close()


def test_setup_save_pw_live_rule(server):
    """(1) Set Up window: open address -> box disabled while the
    password field is empty; typing enables it live (the
    image-73 case: a NEW address + typed password must be
    saveable even though the current address is open); clearing
    disables again; saving the new address checked locks+saves."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink", {"name": "openy"})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, pg = _pc_page(pw, port, 1280, 800, frameless=True)
        try:
            pg.evaluate("() => openLinkWin()")
            pg.wait_for_timeout(700)
            assert pg.evaluate(
                "() => document.querySelector('#lksavepwchk').disabled") is True
            pg.fill("#lkpw", "x")
            pg.wait_for_timeout(200)
            assert pg.evaluate(
                "() => document.querySelector('#lksavepwchk').disabled") is False
            pg.fill("#lkpw", "")
            pg.wait_for_timeout(200)
            assert pg.evaluate(
                "() => document.querySelector('#lksavepwchk').disabled") is True
            # Image-73 flow: new address + typed password.
            pg.fill("#lkin", "newy")
            pg.fill("#lkpw", "pw-newy")
            pg.wait_for_timeout(200)
            assert pg.evaluate(
                "() => document.querySelector('#lksavepwchk').disabled") is False
            pg.evaluate("() => document.querySelector('#lksavepwchk').click()")
            pg.wait_for_timeout(200)
            pg.click("#lkset")
            pg.wait_for_timeout(900)
            au = _auth(client)
            assert au["locked"] is True and au["password_saved"] is True, au
            assert au["address_name"] == "newy", au
            pg.screenshot(path="%s/r52_setup_live.png" % PROOF)
            print("SETUP LIVE: open+empty disabled, typed enabled, save locks+saves")
        finally:
            browser.close()


# --- (2) Download sync + prompt z-index ---

def test_download_sync_and_prompt_zindex(server):
    """(2) Web preview: Download opens the confirm dialog ABOVE
    the preview (hit-testable); Save flips the preview button
    AND the file-row button to Open together; reopening the
    preview of the saved file reads Open at once; Discard
    leaves both on Download."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink", {"name": "dlsy"})
    assert s == 200 and j["ok"], j
    folder = j["folder"]
    open(os.path.join(folder, "hello.txt"), "w").write("hello preview\n")
    open(os.path.join(folder, "second.txt"), "w").write("second file\n")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, pg = _host_web_page(pw, port, 1280, 800)
        try:
            pg.wait_for_selector(".frow .fname", timeout=10000)
            pg.click(".frow .fname >> nth=0")
            pg.wait_for_selector("#previewdl", timeout=5000)
            pg.wait_for_timeout(400)
            assert pg.evaluate(
                "() => document.querySelector('#previewdl').textContent") == "Download"
            first = pg.evaluate("() => document.querySelector('#previewtitle').textContent")
            pg.click("#previewdl")
            pg.wait_for_selector("#cfdlg.open", timeout=5000)
            pg.wait_for_timeout(300)
            hit = pg.evaluate("""() => {
              const z = {cf: getComputedStyle(document.querySelector('#cfdlg')).zIndex,
                         pv: getComputedStyle(document.querySelector('#previewpop')).zIndex};
              const b = document.querySelector('#cfyes').getBoundingClientRect();
              const el = document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2);
              return {z, hit: el ? (el.id || el.tagName) : null,
                      hitInCf: !!(el && el.closest('#cfdlg'))};
            }""")
            assert int(hit["z"]["cf"]) > int(hit["z"]["pv"]), hit
            assert hit["hitInCf"] is True, hit
            pg.screenshot(path="%s/r52_prompt_above_preview.png" % PROOF)
            pg.evaluate("() => document.querySelector('#cfyes').click()")
            pg.wait_for_function(
                "() => document.querySelector('#previewdl').textContent === 'Open'",
                timeout=5000)
            both = pg.evaluate("""() => {
              const row = document.querySelector('#files [data-dl][data-name="%s"]');
              return {preview: document.querySelector('#previewdl').textContent,
                      rowTitle: row ? row.title : null,
                      rowIsOpen: row ? row.innerHTML.includes('M18 13v6') : null};
            }""" % first)
            assert both["preview"] == "Open", both
            assert both["rowTitle"] == "Open", both
            assert both["rowIsOpen"] is True, both
            pg.screenshot(path="%s/r52_preview_row_open.png" % PROOF)
            # Reopen the preview: it must read Open at once.
            pg.click("#previewclose2")
            pg.wait_for_timeout(400)
            pg.click(".frow .fname >> nth=0")
            pg.wait_for_selector("#previewdl", timeout=5000)
            pg.wait_for_timeout(400)
            assert pg.evaluate(
                "() => document.querySelector('#previewdl').textContent") == "Open"
            pg.click("#previewclose2")
            pg.wait_for_timeout(400)
            # Discard path on the second file: both stay Download.
            pg.click(".frow .fname >> nth=1")
            pg.wait_for_selector("#previewdl", timeout=5000)
            pg.wait_for_timeout(400)
            assert pg.evaluate(
                "() => document.querySelector('#previewdl').textContent") == "Download"
            second = pg.evaluate("() => document.querySelector('#previewtitle').textContent")
            pg.click("#previewdl")
            pg.wait_for_selector("#cfdlg.open", timeout=5000)
            pg.evaluate("() => document.querySelector('#cfno').click()")
            pg.wait_for_timeout(600)
            stay = pg.evaluate("""() => {
              const row = document.querySelector('#files [data-dl][data-name="%s"]');
              return {preview: document.querySelector('#previewdl').textContent,
                      rowTitle: row ? row.title : null};
            }""" % second)
            assert stay == {"preview": "Download", "rowTitle": "Download"}, stay
            print("DOWNLOAD SYNC: prompt above preview (z %s>%s), both flip to Open, discard stays Download" % (hit["z"]["cf"], hit["z"]["pv"]))
        finally:
            browser.close()


# --- (3) Saved Back button blue, both themes ---

def test_saved_back_blue_both_themes(server):
    """(3) Back button: solid blue background + white text in
    dark AND light themes."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink",
                    {"name": "savey", "password": "pw-savey",
                     "save_password": True})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    seed = ("localStorage.setItem('dropit_dl', JSON.stringify("
            "{'a.txt': {size: 10, ts: 1700000000}}));")
    with sync_playwright() as pw:
        for light in (False, True):
            browser, ctx, pg, fwd = _guest_page(
                pw, port, 390, 844, init_script=seed, light=light)
            try:
                pg.click("#gsavedbtn")
                pg.wait_for_timeout(600)
                st = pg.evaluate("""() => { const b = document.querySelector('#gsavedback');
                  const cs = getComputedStyle(b);
                  return {bg: cs.backgroundColor, color: cs.color,
                          svgStroke: getComputedStyle(b.querySelector('svg')).stroke || cs.color}; }""")
                assert st["bg"] == "rgb(39, 127, 240)", st
                assert st["color"] == "rgb(255, 255, 255)", st
                pg.screenshot(path="%s/r52_saved_back_%s.png" % (
                    PROOF, "light" if light else "dark"))
                print("SAVED BACK %s: %s" % ("light" if light else "dark", st))
            finally:
                browser.close()


# --- (4) No refresh button on mobile web ---

def test_no_refresh_button_mobile(server):
    """(4) Mobile web (390px): no refresh control anywhere --
    not in the top area, not in the whole document."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink", {"name": "openy"})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, pg = _host_web_page(pw, port, 390, 844)
        try:
            found = pg.evaluate("""() => {
              const all = [...document.querySelectorAll('button, a, [role=button]')];
              const bad = all.filter(el => /refresh|reload/i.test(
                (el.title || '') + ' ' + (el.getAttribute('aria-label') || '') +
                ' ' + el.textContent + ' ' + (el.id || '') + ' ' + (el.className || '')));
              const top = all.filter(el => el.getBoundingClientRect().top < 120)
                .map(el => ({id: el.id, title: el.title || '', txt: el.textContent.trim().slice(0, 20)}));
              return {bad: bad.map(b => b.id || b.textContent.trim()), top};
            }""")
            assert found["bad"] == [], found
            pg.screenshot(path="%s/r52_mobile_top.png" % PROOF)
            print("NO REFRESH: top-area buttons %s" % found["top"])
        finally:
            browser.close()


# --- (5) One checkbox on the login screen ---

def test_one_checkbox_login_pc_and_mobile(server):
    """(5) Locked current address, logged out: the login screen
    shows exactly ONE hit-testable Save password checkbox on
    PC web AND on mobile web; opening the Connect modal over
    it still leaves exactly one (the modal's)."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink",
                    {"name": "locky", "password": "pw-locky",
                     "save_password": True})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        for label, w, h in [("pc", 1280, 800), ("mobile", 390, 844)]:
            browser, ctx, pg, fwd = _guest_page(pw, port, w, h)
            try:
                pg.wait_for_timeout(1200)
                pg.evaluate("() => doLogout()")
                pg.wait_for_timeout(800)
                c1 = _hit_checkbox_count(pg)
                assert c1 == {"n": 1, "ids": ["gloginsavechk"]}, (label, c1)
                pg.screenshot(path="%s/r52_login_one_%s.png" % (PROOF, label))
                pg.evaluate("() => openLinkWin()")
                pg.wait_for_timeout(700)
                c2 = _hit_checkbox_count(pg)
                assert c2 == {"n": 1, "ids": ["lksavepwchk"]}, (label, c2)
                pg.screenshot(path="%s/r52_login_modal_one_%s.png" % (PROOF, label))
                # Closing the modal brings the login page back.
                pg.evaluate("() => closeLinkWin()")
                pg.wait_for_timeout(500)
                c3 = _hit_checkbox_count(pg)
                assert c3 == {"n": 1, "ids": ["gloginsavechk"]}, (label, c3)
                print("ONE CHECKBOX %s: login 1, modal 1, after close 1" % label)
            finally:
                browser.close()


# --- (6) Eye inside field + "Connect To A Device" ---

def test_eye_inside_and_device_header(server):
    """(6) Guest Connect dialog: header reads "Connect To A
    Device"; the eye toggle's box sits fully inside the
    password field's box, vertically centred, at mobile and
    PC widths."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink", {"name": "openy"})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        for label, w, h in [("mobile", 390, 844), ("pc", 1280, 800)]:
            browser, ctx, pg, fwd = _guest_page(pw, port, w, h)
            try:
                pg.evaluate("() => openLinkWin()")
                pg.wait_for_timeout(700)
                m = pg.evaluate("""() => {
                  const pw = document.querySelector('#lkpw');
                  const eye = document.querySelector('#lkpweye');
                  const pr = pw.getBoundingClientRect(), er = eye.getBoundingClientRect();
                  const head = document.querySelector('#guestcardhead b').textContent;
                  return {head,
                    pw: {x: Math.round(pr.x), y: Math.round(pr.y), w: Math.round(pr.width), h: Math.round(pr.height)},
                    eye: {x: Math.round(er.x), y: Math.round(er.y), w: Math.round(er.width), h: Math.round(er.height)},
                    inside: er.x >= pr.x && er.right <= pr.right && er.y >= pr.y && er.bottom <= pr.bottom,
                    centred: Math.abs((er.y + er.height / 2) - (pr.y + pr.height / 2))};
                }""")
                assert m["head"] == "Connect To A Device", m
                assert m["inside"] is True, m
                assert m["centred"] <= 1, m
                pg.screenshot(path="%s/r52_eye_%s.png" % (PROOF, label))
                print("EYE %s: inside=%s centred off by %spx, header=%r" % (
                    label, m["inside"], m["centred"], m["head"]))
            finally:
                browser.close()


# --- (7) Address-switch round trip keeps every text ---

def _send_text(pg, text):
    pg.fill("#snippet", text)
    pg.click("#sendsnippet")
    pg.wait_for_function(
        "() => document.querySelector('#snips').innerText.includes(%s)"
        % json.dumps(text), timeout=8000)


def _read_all(pg):
    return pg.evaluate("""() => ({
      auth: AUTH.address_name,
      mpchost: document.querySelector('#mpchost').value,
      dirlabel: document.querySelector('#dirnamelabel').textContent,
      connectbar: document.querySelector('.connectbar a').textContent,
      mconn: document.querySelector('#mconnstate').textContent,
      sblink: document.querySelector('#sblink').textContent,
      sbaddr: document.querySelector('#sbaddr').textContent,
      snips: document.querySelector('#snips').innerText.slice(0, 200),
      files: [...document.querySelectorAll('#files .fname')].map(e => e.textContent),
      filecount: document.querySelector('#filecount').textContent,
      snipcount: document.querySelector('#snipcount').textContent
    })""")


def _switch_to(pg, name):
    pg.evaluate("() => openLinkWin()")
    pg.wait_for_timeout(500)
    pg.fill("#lkin", name)
    pg.click("#lkset")
    pg.wait_for_timeout(1500)
    pg.evaluate("() => closeLinkWin()")
    pg.wait_for_timeout(400)


def test_address_switch_keeps_texts(server):
    """(7) Host page: two addresses with distinct texts + files.
    Switching A->B->A->B keeps every field present and correct
    (address, folder, lock state, counts, texts, files) -- in
    particular #mpchost follows the switch. Then a stale-address
    401 mid-poll must NOT wipe the texts, and they must still
    be there after the next good reload."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink", {"name": "addrA"})
    assert s == 200 and j["ok"], j
    folderA = j["folder"]
    s, j = client.j("POST", "/api/setlink", {"name": "addrB"})
    assert s == 200 and j["ok"], j
    folderB = j["folder"]
    open(os.path.join(folderA, "a.txt"), "w").write("aaa\n")
    open(os.path.join(folderB, "b.txt"), "w").write("bbb\n")
    s, j = client.j("POST", "/api/setlink", {"name": "addrA"})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, pg = _pc_page(pw, port, 1280, 800, frameless=True)
        try:
            pg.wait_for_timeout(1200)
            _send_text(pg, "Alpha shared text")
            pg.wait_for_timeout(600)
            beta_sent = False
            for name, note, fname, folder in [
                    ("addrB", "Beta shared text", "b.txt", folderB),
                    ("addrA", "Alpha shared text", "a.txt", folderA),
                    ("addrB", "Beta shared text", "b.txt", folderB)]:
                _switch_to(pg, name)
                if name == "addrB" and not beta_sent:
                    _send_text(pg, "Beta shared text")
                    beta_sent = True
                st = _read_all(pg)
                assert st["auth"] == name, st
                assert st["mpchost"] == name, st
                assert st["dirlabel"] == folder, st
                assert st["connectbar"] == name, st
                assert st["mconn"] == "Connected", st
                assert st["sblink"] == name, st
                assert note in st["snips"], st
                assert st["files"] == [fname], st
                assert st["snipcount"] == "1", st
                assert st["filecount"] == "1", st
            pg.screenshot(path="%s/r52_switch_final.png" % PROOF)
            # Stale-address 401 must not wipe the texts now.
            pg.evaluate("""async () => {
              window.__savedAuth = AUTH.address_name;
              AUTH.address_name = 'zzz-no-such';
              await loadNotes(); await loadFiles();
              AUTH.address_name = window.__savedAuth;
              await loadNotes(); await loadFiles();
            }""")
            pg.wait_for_timeout(800)
            st = _read_all(pg)
            assert "Could not load" not in st["snips"], st
            assert "Beta shared text" in st["snips"], st
            assert st["files"] == ["b.txt"], st
            print("SWITCH: A->B->A->B all fields correct; stale 401 kept texts+files")
        finally:
            browser.close()


# --- (8) Menu redesign ---

def test_menu_redesign(server):
    """(8) Menu matches his design: navy tokens, 28px outer /
    16px cards, logo tile + Drop + v2.8.37, amber dot, 36px
    square lock/pencil buttons, cyan toggles, full-width
    gradient folder buttons; frameless PC: menu covers the
    title bar (top 0, above it) and its border runs to the
    bottom, ending rounded. Screenshots dark + light."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink", {"name": "menuy"})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, pg = _pc_page(pw, port, 1280, 800, frameless=True)
        try:
            pg.click("#menubtn")
            pg.wait_for_timeout(600)
            m = pg.evaluate("""() => {
              const sb = document.querySelector('#sidebar');
              const cs = getComputedStyle(sb);
              const r = sb.getBoundingClientRect();
              const tb = document.querySelector('#titlebar');
              const tcs = getComputedStyle(tb);
              const card = document.querySelector('#sbsetupcard');
              const ccs = getComputedStyle(card);
              const lock = document.querySelector('#sblock');
              const lr = lock.getBoundingClientRect();
              const sw = document.querySelector('#swsep');
              const swcs = getComputedStyle(sw);
              const open = document.querySelector('#sbopen');
              const ocs = getComputedStyle(open);
              const orect = open.getBoundingClientRect();
              const cardRect = card.getBoundingClientRect();
              const dot = document.querySelector('#sbsetupcard .addot');
              const dcs = dot ? getComputedStyle(dot) : null;
              return {top: Math.round(r.top), bottom: Math.round(r.bottom),
                vh: window.innerHeight, bg: cs.backgroundColor,
                radius: cs.borderRadius, z: cs.zIndex,
                titlebarZ: tcs.zIndex, titlebarTop: Math.round(tb.getBoundingClientRect().top),
                cardBg: ccs.backgroundColor, cardRadius: ccs.borderTopLeftRadius,
                cardBorder: ccs.borderTopColor,
                lockW: Math.round(lr.width), lockH: Math.round(lr.height),
                lockRadius: getComputedStyle(lock).borderTopLeftRadius,
                swW: Math.round(sw.getBoundingClientRect().width),
                swOnBg: swcs.backgroundColor,
                openBg: ocs.backgroundImage, openColor: ocs.color,
                openW: Math.round(orect.width), cardW: Math.round(cardRect.width),
                dotBg: dcs ? dcs.backgroundColor : null,
                title: document.querySelector('.sbtitle').textContent,
                ver: document.querySelector('.sbver').textContent,
                logo: document.querySelector('.sblogo').getAttribute('src'),
                themeRow: [...document.querySelectorAll('#sidebar .sbcard')].pop().querySelector('.sbrow').textContent.trim()};
            }""")
            assert m["top"] == 0, m
            assert m["bottom"] == m["vh"], m
            assert m["bg"] == "rgb(9, 13, 22)", m
            assert m["radius"] == "28px", m
            assert int(m["z"]) > int(m["titlebarZ"]), m
            assert m["cardBg"] == "rgb(15, 23, 42)", m
            assert m["cardRadius"] == "16px", m
            assert m["cardBorder"] == "rgb(30, 41, 59)", m
            assert (m["lockW"], m["lockH"]) == (36, 36), m
            assert m["lockRadius"] == "12px", m
            assert m["swW"] == 48, m
            assert m["swOnBg"] == "rgb(56, 189, 248)", m
            assert "linear-gradient" in m["openBg"] and "rgb(37, 99, 235)" in m["openBg"], m
            assert m["openColor"] == "rgb(255, 255, 255)", m
            assert abs(m["openW"] - (m["cardW"] - 26)) <= 2, m  # full width inside the 12px PC card padding + 1px borders
            assert m["dotBg"] == "rgb(245, 158, 11)", m
            assert m["title"] == "Drop" and m["ver"] == "v2.8.37", m
            assert m["logo"] == "/logo.png", m
            assert "Dark / Light" in m["themeRow"], m
            pg.screenshot(path="%s/r52_menu_dark.png" % PROOF)
            pg.evaluate("() => document.documentElement.classList.add('light')")
            pg.wait_for_timeout(400)
            m2 = pg.evaluate("""() => { const sb = document.querySelector('#sidebar');
              const cs = getComputedStyle(sb);
              const back = document.querySelector('#gsavedback');
              return {bg: cs.backgroundColor, radius: cs.borderRadius}; }""")
            assert m2["bg"] == "rgb(9, 13, 22)", m2
            assert m2["radius"] == "28px", m2
            pg.screenshot(path="%s/r52_menu_light.png" % PROOF)
            print("MENU: %s" % m)
        finally:
            browser.close()
        # Web (non-frameless) host page: same navy + 28px, top 0.
        browser2, pg2 = _host_web_page(pw, port, 1280, 800)
        try:
            pg2.click("#menubtn")
            pg2.wait_for_timeout(600)
            w = pg2.evaluate("""() => { const sb = document.querySelector('#sidebar');
              const cs = getComputedStyle(sb); const r = sb.getBoundingClientRect();
              return {top: Math.round(r.top), bg: cs.backgroundColor,
                      radius: cs.borderRadius, w: Math.round(r.width)}; }""")
            assert w["top"] == 0 and w["bg"] == "rgb(9, 13, 22)", w
            assert w["radius"] == "28px", w
            pg2.screenshot(path="%s/r52_menu_web.png" % PROOF)
            print("MENU WEB: %s" % w)
        finally:
            browser2.close()
