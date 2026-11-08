"""v2.8.38 round (Essef Nov 7, ~1:48 PM) -- WEB/DESKTOP track only,
local test build only. SEVEN items, nothing else:

  (1) WEB PREVIEW OPEN OPENS THE FILE: on web/MB the preview's
      Open button called only close() (2.8.37) -- the file never
      opened. Now it closes the preview and opens the saved
      blob in the viewer (openBlob -- the same viewer the file
      row's Open uses), in previewFile (already-downloaded and
      fresh-download paths) and in repaintDownloadButtons. D
      (bridge) is untouched: its preview Open still calls
      openFile through the bridge.
  (2) SAVE PASSWORD -- SIMPLIFIED EDIT FLOW (web + MB): on the
      password fields that show a saved password (#lkpw in Set
      Up / Connect, #gloginpw on the login screen) focus empties
      the field (click in -> empty, type from scratch); blur
      with nothing typed brings the saved password back as dots;
      blur with something typed keeps what was typed and never
      brings the saved password back. Empty = open address;
      typed + Save Password checked = saved hashed and shown in
      the links lists. 2.8.36 semantics stay: unchecked +
      password -> still locked, NOT saved, history reads
      "Locked - No Saved Password".
  (3) LISTS FOLLOW THE THEME (MB + web): the address-history /
      links lists (.ddlist/.ddopt) were hard-coded white, so
      they glowed white in dark theme. They now use the theme
      vars (dark list in dark, light list in light); the light
      rules keep the exact old light look.
  (6) MENU LIGHT THEME (D + web + MB): the 2.8.37 menu was
      dark-only (navy in both themes). Light theme now gets
      light colours, same layout; dark theme untouched.
  (7) DUPLICATE CHECKBOX STILL THERE ON LOGIN (web + MB):
      image-76 -- an empty outline box PLUS a grey square
      overlapping "Save password". REAL root cause, reproduced
      live: the login checkbox is DISABLED + unchecked whenever
      an open address is typed (checkOpenAddress), and then
      `.gloginbox input:disabled { opacity:.55 }` (0,2,1) beat
      `.permchk input { opacity:0 }` (0,1,1), so the native
      390px-wide checkbox (`.gloginbox input { width:100% }`
      beat `.permchk input { width:auto }`) showed through at
      55% opacity. Fix: the .gloginbox input rules now exclude
      checkboxes (`:not([type=checkbox])`) and an explicit
      `.gloginbox .permchk input` rule pins opacity:0.
      Exactly one Save Password checkbox on the login screen,
      web and MB, in both the enabled and the disabled states.
  (8) "SAVE ON THIS PHONE" -> "SAVE ON THIS DEVICE": the
      download confirm button (#cfyes) read "Save on phone"
      with a gradient fill and dark text; it now reads "Save on
      this device", solid blue #277ff0 with white text, both
      themes. "Save on this phone" / "Save on phone" occur
      nowhere in the served page any more.
  (9) MB SAVED HEADER: title centred, red Delete on the RIGHT,
      Back on the left (solid blue, per 2.8.37). Phone widths
      only; desktop/web keep the old row.
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
from test_link_round34 import _Fwd  # noqa: F401,E402
from test_link_round46 import _pc_page  # noqa: E402

PAGE = D.PAGE
SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py"),
           encoding="utf-8").read()

PROOF = "/home/hatch/workspace/dropit-proof-round53"
os.makedirs(PROOF, exist_ok=True)


def test_version_is_2_8_38():
    assert D.VERSION == "2.8.38", D.VERSION


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
        p = os.path.join(PROOF, "r53_script%d.js" % i)
        open(p, "w", encoding="utf-8").write(s)
        r = subprocess.run(["node", "--check", p],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_markers_item1_preview_open():
    """(1) Preview Open opens the file (openBlob) in all three
    web paths; the old close-only assignments are gone."""
    assert "dl.onclick = () => { const cx = $(\"#previewclose2\"); if(cx) cx.click(); openBlob({name: name, size: size}); };" in PAGE
    assert "dl.onclick = () => { close(); openBlob({name: name, size: size}); };" in PAGE
    assert "dl.onclick = () => close();" not in PAGE
    assert "if(label === \"Open\") dl.onclick = () => { const cx = $(\"#previewclose2\"); if(cx) cx.click(); };" not in PAGE


def test_markers_item2_pw_flow():
    """(2) The edit-flow state machine, its listeners, and every
    fill site that arms it."""
    assert "function _savedPwFocus(field, st){" in PAGE
    assert "function _savedPwBlur(field, st){" in PAGE
    assert "_lkpwF38.addEventListener(\"focus\"" in PAGE
    assert "_glpwF38.addEventListener(\"blur\"" in PAGE
    assert "_lkpwF38.addEventListener(\"click\"" in PAGE
    assert "_glpwF38.addEventListener(\"click\"" in PAGE
    assert "pwf.value = \"\"; _lkPwSt.saved = \"\"; _lkPwSt.shown = false;" in PAGE
    assert "_lkPwSt.saved = j.password; _lkPwSt.shown = true; }" in PAGE
    assert "_lkPwSt.saved = jj.password; _lkPwSt.shown = true; }" in PAGE
    assert "_glPwSt.saved = saved[name]; _glPwSt.shown = true; }" in PAGE
    assert "if(p){ _glPwSt.keepFocus = true; p.focus(); }" in PAGE
    assert "_lkPwSt.keepFocus = true; pwf.focus(); paintEyeBtn(btn, true); }" in PAGE


def test_markers_item3_lists_theme():
    """(3) Lists use theme vars; light keeps the exact old look."""
    assert ".ddlist { display:none; position:absolute; top:calc(100% + 4px); left:0; right:0; background:var(--card); border:1px solid var(--line);" in PAGE
    assert ".ddopt { display:flex; align-items:center; gap:8px; padding:10px 12px; background:var(--card); color:var(--txt);" in PAGE
    assert ".ddopt:hover, .ddopt.ddhover { background:var(--card2); }" in PAGE
    assert ".ddopt .ddpw { color:var(--muted);" in PAGE
    assert "html.light .ddopt { background:#ffffff; color:#111827; }" in PAGE
    assert "background:#ffffff; color:#111827;" in PAGE
    assert ".ddopt { display:flex; align-items:center; gap:8px; padding:10px 12px; background:#ffffff; color:#111827;" not in PAGE


def test_markers_item6_menu_light():
    """(6) Light menu rules exist; the dark navy rules are
    untouched."""
    assert "html.light #sidebar { background-color:#ffffff;" in PAGE
    assert "html.light #sidebar .sbtitle { color:#0f172a; }" in PAGE
    assert "html.light #sidebar .sbcard { background:#f1f5f9; border-color:#c3cfde; }" in PAGE
    assert "html.light #sidebar .sbrow { color:#0f172a; }" in PAGE
    assert "html.light #sidebar .sbsw.on { background:#38bdf8; }" in PAGE
    assert "#sidebar { background-color:#090D16;" in PAGE
    assert "#sidebar .sbcard { background:#0F172A; border:1px solid #1E293B; border-radius:16px;" in PAGE


def test_markers_item7_checkbox():
    """(7) The .gloginbox input rules exclude checkboxes; the
    permchk input is pinned invisible even when disabled."""
    assert ".gloginbox input:not([type=checkbox]) { width:100%;" in PAGE
    assert ".gloginbox input:not([type=checkbox]):disabled { opacity:.55; }" in PAGE
    assert ".gloginbox .permchk input, .gloginbox .permchk input:disabled { opacity:0; width:auto; height:auto; }" in PAGE
    assert "  .gloginbox input { width:100%;" not in PAGE


def test_markers_item8_save_device():
    """(8) No "Save on this phone" / "Save on phone" anywhere in
    the served page; the button reads "Save on this device"
    and is solid blue + white in both themes."""
    assert PAGE.count("Save on this phone") == 0
    assert PAGE.count("Save on phone") == 0
    assert PAGE.count("Saved on this phone") == 0
    assert '<button class="btn primary" id="cfyes">Save on this device</button>' in PAGE
    assert "#cfdlg #cfyes, html.light #cfdlg #cfyes { background:#277ff0; color:#ffffff; border:none; }" in PAGE


def test_markers_item9_saved_head():
    """(9) MB media query: centred title, red Delete on the
    right, Back left."""
    assert "@media (max-width:720px){" in PAGE
    assert ".gsavedhead b { position:absolute; left:50%; top:50%; transform:translate(-50%,-50%); font-size:15px; }" in PAGE
    assert ".gsavedhead #gsaveddel { order:2; margin-left:auto; background:#ef4444; color:#ffffff; border:none; }" in PAGE


# --- Playwright helpers (same shapes as round52) ---

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
    """Occlusion-aware count of visible Save-password labels."""
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


def _native_chk_state(pg):
    """The native login checkbox: computed opacity + width, and
    whether it is disabled/checked."""
    return pg.evaluate("""() => { const i = document.querySelector('#gloginsavechk');
      const cs = getComputedStyle(i); const r = i.getBoundingClientRect();
      return {opacity: cs.opacity, width: cs.width,
              rectW: Math.round(r.width), rectH: Math.round(r.height),
              disabled: i.disabled, checked: i.checked}; }""")


def _grey_pixels_in_label_row(pg):
    """Screenshot the Save-password label row and count mid-grey
    pixels (the image-76 phantom box renders as a ~13px grey
    square over the text). The fixed row has only text
    antialiasing noise (6 px on this clip); the buggy 2.8.37
    disabled row scores 23. The callers assert <= 12, which
    separates the two with margin on both sides."""
    from PIL import Image
    import io
    r = pg.evaluate("""() => { const l = document.querySelector('#gloginsavelabel').getBoundingClientRect();
      return {x: l.x, y: l.y, width: l.width, height: l.height}; }""")
    shot = pg.screenshot(clip={"x": max(0, r["x"] - 10), "y": max(0, r["y"] - 8),
                               "width": r["width"] + 20, "height": r["height"] + 16})
    im = Image.open(io.BytesIO(shot)).convert("RGB")
    px = im.load()
    n = 0
    for y in range(im.height):
        for x in range(im.width):
            rr, gg, bb = px[x, y]
            if 70 <= rr <= 170 and abs(rr - gg) < 12 and abs(gg - bb) < 12:
                n += 1
    return n


# --- (1) Preview Open opens the file, web + MB; D unchanged ---

def _preview_open_flow(pg, label):
    """Open a text preview, Download it (confirm Save), then
    click the preview's Open: the preview must close AND the
    viewer must open showing the file text."""
    # Mobile widths show the board as tabs -- the Files column
    # is hidden until its tab is picked.
    pg.evaluate("() => { if (window.innerWidth < 721) setTab('files'); }")
    pg.wait_for_timeout(400)
    pg.wait_for_selector(".frow .fname", timeout=10000)
    pg.click(".frow .fname >> nth=0")
    pg.wait_for_selector("#previewdl", timeout=5000)
    pg.wait_for_timeout(400)
    assert pg.evaluate(
        "() => document.querySelector('#previewdl').textContent") == "Download"
    pg.click("#previewdl")
    pg.wait_for_selector("#cfdlg.open", timeout=5000)
    pg.wait_for_timeout(300)
    cf = pg.evaluate("""() => { const b = document.querySelector('#cfyes');
      const cs = getComputedStyle(b);
      return {text: b.textContent, bg: cs.backgroundColor, color: cs.color}; }""")
    assert cf["text"] == "Save on this device", cf
    assert cf["bg"] == "rgb(39, 127, 240)", cf
    assert cf["color"] == "rgb(255, 255, 255)", cf
    pg.evaluate("() => document.querySelector('#cfyes').click()")
    pg.wait_for_function(
        "() => document.querySelector('#previewdl').textContent === 'Open'",
        timeout=5000)
    pg.click("#previewdl")
    pg.wait_for_function(
        "() => document.querySelector('#viewer').classList.contains('open')",
        timeout=5000)
    pg.wait_for_timeout(400)
    st = pg.evaluate("""() => ({previewOpen: document.querySelector('#previewpop').classList.contains('open'),
      viewerText: document.querySelector('#vcontent').innerText.slice(0, 60)})""")
    assert st["previewOpen"] is False, st
    assert "hello preview" in st["viewerText"], st
    print("PREVIEW OPEN %s: viewer shows %r" % (label, st["viewerText"]))
    return st


def test_preview_open_opens_file_web_and_mb(server):
    """(1) Web (1280) + MB (390, mobile web): preview Download
    -> confirm -> Open opens the file in the viewer. Reopening
    the preview of the saved file reads Open at once and its
    Open opens the file too."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink", {"name": "prevx"})
    assert s == 200 and j["ok"], j
    open(os.path.join(j["folder"], "hello.txt"), "w").write("hello preview\n")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        for label, w, h in [("web", 1280, 800), ("mb", 390, 844)]:
            browser, pg = _host_web_page(pw, port, w, h)
            try:
                _preview_open_flow(pg, label)
                pg.screenshot(path="%s/r53_preview_open_%s.png" % (PROOF, label))
                # Close the viewer, reopen the preview: Open at once.
                pg.click("#vclose")
                pg.wait_for_timeout(500)
                pg.click(".frow .fname >> nth=0")
                pg.wait_for_selector("#previewdl", timeout=5000)
                pg.wait_for_timeout(400)
                assert pg.evaluate(
                    "() => document.querySelector('#previewdl').textContent") == "Open"
                pg.click("#previewdl")
                pg.wait_for_function(
                    "() => document.querySelector('#viewer').classList.contains('open')",
                    timeout=5000)
                pg.wait_for_timeout(300)
                assert "hello preview" in pg.evaluate(
                    "() => document.querySelector('#vcontent').innerText"), label
                print("PREVIEW REOPEN %s: saved file reads Open, Open opens it" % label)
            finally:
                browser.close()


def test_preview_open_desktop_bridge_unchanged(server):
    """(1) D (fake pywebview bridge): the preview's Open still
    goes through the bridge open_file -- the desktop behaviour
    is exactly as before."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink", {"name": "prevd"})
    assert s == 200 and j["ok"], j
    open(os.path.join(j["folder"], "hello.txt"), "w").write("hello preview\n")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, pg = _pc_page(pw, port, 1280, 800, frameless=True)
        try:
            pg.evaluate("""() => { window.__openFileCalls = [];
              window.pywebview.api.open_file = (n) => { window.__openFileCalls.push(n); return Promise.resolve(true); }; }""")
            pg.wait_for_selector(".frow .fname", timeout=10000)
            pg.click(".frow .fname >> nth=0")
            pg.wait_for_selector("#previewdl", timeout=5000)
            pg.wait_for_timeout(400)
            assert pg.evaluate(
                "() => document.querySelector('#previewdl').textContent") == "Open"
            pg.click("#previewdl")
            pg.wait_for_timeout(600)
            calls = pg.evaluate("() => window.__openFileCalls")
            assert calls == ["hello.txt"], calls
            assert pg.evaluate(
                "() => document.querySelector('#previewpop').classList.contains('open')") is False
            print("PREVIEW D: bridge open_file called with %s, preview closed" % calls)
        finally:
            browser.close()


# --- (2) Password focus/blur matrix ---

def test_pw_flow_setup_window(server):
    """(2) Set Up window (#lkpw): prefilled saved password ->
    click in empties it; click out empty restores it hashed;
    click in, type a new password, click out keeps the typed
    one; Save with Save Password checked saves it hashed and
    the history list shows dots for the address. Then:
    unchecked + password -> locked, NOT saved, history reads
    "Locked - No Saved Password"; empty password -> open."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink",
                    {"name": "seta", "password": "pw-seta",
                     "save_password": True})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, pg = _pc_page(pw, port, 1280, 800, frameless=True)
        try:
            pg.evaluate("() => openLinkWin()")
            pg.wait_for_function(
                "() => document.querySelector('#lkpw').value === 'pw-seta'",
                timeout=5000)
            assert pg.evaluate("() => document.querySelector('#lkpw').type") == "password"
            assert pg.evaluate(
                "() => document.querySelector('#lksavepwchk').checked") is True
            # Click in -> EMPTY (caret in an empty field).
            pg.click("#lkpw")
            pg.wait_for_timeout(300)
            assert pg.evaluate("() => document.querySelector('#lkpw').value") == ""
            assert pg.evaluate(
                "() => document.activeElement.id") == "lkpw"
            # Click out empty -> saved password reappears hashed.
            pg.click("#lkin")
            pg.wait_for_timeout(300)
            assert pg.evaluate("() => document.querySelector('#lkpw').value") == "pw-seta"
            assert pg.evaluate("() => document.querySelector('#lkpw').type") == "password"
            # Click in again, type a NEW password, click out ->
            # the typed password is kept, saved one NOT restored.
            pg.click("#lkpw")
            pg.wait_for_timeout(300)
            assert pg.evaluate("() => document.querySelector('#lkpw').value") == ""
            pg.fill("#lkpw", "pw-new2")
            pg.wait_for_timeout(200)
            pg.click("#lkin")
            pg.wait_for_timeout(300)
            assert pg.evaluate("() => document.querySelector('#lkpw').value") == "pw-new2"
            assert pg.evaluate(
                "() => document.querySelector('#lksavepwchk').checked") is True
            pg.screenshot(path="%s/r53_pw_setup_typed.png" % PROOF)
            # Save: typed + checked -> locked + saved hashed.
            pg.click("#lkset")
            pg.wait_for_timeout(900)
            au = _auth(client)
            assert au["locked"] is True and au["password_saved"] is True, au
            s2, j2 = client.j("GET", "/api/linkpassword?link=seta")
            assert s2 == 200 and j2.get("password") == "pw-new2", j2
            # History list shows dots for the current address.
            pg.evaluate("() => openLinkWin()")
            pg.wait_for_timeout(800)
            pg.click("#lkcurview")
            pg.wait_for_selector("#lkddlist.open", timeout=5000)
            pg.wait_for_timeout(400)
            row = pg.evaluate("""() => { const rows = [...document.querySelectorAll('#lkddlist .ddopt')];
              const r = rows.find(o => o.dataset.name === 'seta');
              return r ? r.querySelector('.ddpw').textContent : null; }""")
            assert row == "••••••", row
            pg.screenshot(path="%s/r53_pw_history_dots.png" % PROOF)
            print("PW SETUP: click-in empties, blur-empty restores, typed kept, saved+listed as dots")
            # Unchecked + password -> locked, hash only.
            pg.evaluate("() => { document.querySelector('#lkin').value = ''; }")
            pg.fill("#lkin", "hashy")
            pg.click("#lkpw")
            pg.wait_for_timeout(200)
            pg.fill("#lkpw", "pw-hashy")
            pg.wait_for_timeout(200)
            assert pg.evaluate(
                "() => document.querySelector('#lksavepwchk').disabled") is False
            assert pg.evaluate(
                "() => document.querySelector('#lksavepwchk').checked") is True
            # Uncheck it: unchecked + password -> locked, hash only.
            pg.evaluate("() => document.querySelector('#lksavepwchk').click()")
            pg.wait_for_timeout(200)
            assert pg.evaluate(
                "() => document.querySelector('#lksavepwchk').checked") is False
            pg.click("#lkset")
            pg.wait_for_timeout(900)
            au = _auth(client)
            assert au["locked"] is True and au["password_saved"] is False, au
            assert au["address_name"] == "hashy", au
            s2, j2 = client.j("GET", "/api/linkpassword?link=hashy")
            assert j2.get("error") in ("not_retrievable", "not_found"), j2
            pg.evaluate("() => openLinkWin()")
            pg.wait_for_timeout(800)
            pg.click("#lkcurview")
            pg.wait_for_selector("#lkddlist.open", timeout=5000)
            pg.wait_for_timeout(400)
            row = pg.evaluate("""() => { const rows = [...document.querySelectorAll('#lkddlist .ddopt')];
              const r = rows.find(o => o.dataset.name === 'hashy');
              return r ? r.querySelector('.ddpw').textContent : null; }""")
            assert row == "Locked - No Saved Password", row
            print("PW SETUP: unchecked + password -> locked hash-only, history 'Locked - No Saved Password'")
            # Empty password -> open address.
            pg.evaluate("() => { document.querySelector('#lkin').value = ''; }")
            pg.fill("#lkin", "openz")
            pg.click("#lkpw")
            pg.wait_for_timeout(200)
            pg.fill("#lkpw", "")
            pg.wait_for_timeout(200)
            pg.click("#lkset")
            pg.wait_for_timeout(900)
            au = _auth(client)
            assert au["locked"] is False and au["password_saved"] is False, au
            assert au["address_name"] == "openz", au
            print("PW SETUP: no password -> open address")
        finally:
            browser.close()


def test_pw_flow_login_screen(server):
    """(2) Login screen (#gloginpw): picking a saved address
    fills the password (dots, no clearing on the programmatic
    focus); click in empties it; click out empty restores it;
    click in + type keeps the typed one; connecting with the
    restored saved password still logs in."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink",
                    {"name": "locky", "password": "pw-locky",
                     "save_password": True})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    seed = ("localStorage.setItem('drop_guest_pw', JSON.stringify({locky: 'pw-locky'}));"
            "localStorage.setItem('drop_link_use', JSON.stringify({locky: 3}));")
    with sync_playwright() as pw:
        browser, ctx, pg, fwd = _guest_page(pw, port, 390, 844, init_script=seed)
        try:
            pg.wait_for_timeout(1200)
            pg.evaluate("() => doLogout()")
            pg.wait_for_timeout(800)
            pg.click("#gddchevbtn")
            pg.wait_for_selector("#gddlist.open", timeout=5000)
            pg.wait_for_timeout(400)
            pg.click("#gddlist .ddopt >> nth=0")
            pg.wait_for_timeout(600)
            # Filled with the saved password, NOT cleared by the
            # programmatic focus the row click performs.
            assert pg.evaluate("() => document.querySelector('#gloginpw').value") == "pw-locky"
            assert pg.evaluate(
                "() => document.querySelector('#gloginpw').type") == "password"
            # Click in -> EMPTY.
            pg.click("#gloginpw")
            pg.wait_for_timeout(300)
            assert pg.evaluate("() => document.querySelector('#gloginpw').value") == ""
            # Click out empty -> saved password reappears hashed.
            pg.click("#gloginlink")
            pg.wait_for_timeout(300)
            assert pg.evaluate("() => document.querySelector('#gloginpw').value") == "pw-locky"
            # Click in, type a different password, click out ->
            # the typed one is kept.
            pg.click("#gloginpw")
            pg.wait_for_timeout(300)
            pg.fill("#gloginpw", "pw-other")
            pg.wait_for_timeout(200)
            pg.click("#gloginlink")
            pg.wait_for_timeout(300)
            assert pg.evaluate("() => document.querySelector('#gloginpw').value") == "pw-other"
            pg.screenshot(path="%s/r53_pw_login_typed.png" % PROOF)
            # Clicking into the field holding TYPED text does NOT
            # clear it (it is the user's text, not a saved one).
            pg.click("#gloginpw")
            pg.wait_for_timeout(300)
            assert pg.evaluate("() => document.querySelector('#gloginpw').value") == "pw-other"
            # Delete everything, click out empty -> the saved
            # password reappears, and Connect logs in with it.
            pg.fill("#gloginpw", "")
            pg.wait_for_timeout(200)
            pg.click("#gloginlink")
            pg.wait_for_timeout(300)
            assert pg.evaluate("() => document.querySelector('#gloginpw').value") == "pw-locky"
            pg.click("#gloginbtn")
            pg.wait_for_function(
                "() => typeof AUTH !== 'undefined' && AUTH.authed",
                timeout=8000)
            pg.wait_for_timeout(600)
            assert pg.evaluate(
                "() => !document.querySelector('#guestlogin').classList.contains('open')")
            print("PW LOGIN: row fill kept, click-in empties, blur-empty restores, typed kept, restored pw logs in")
        finally:
            browser.close()


# --- (3) Lists follow the theme ---

def test_lists_theme_colours(server):
    """(3) Address-history / links lists: dark theme -> dark
    list, light theme -> light list, on MB guest + web guest +
    host Set Up. Measured computed colours."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink", {"name": "othera"})
    assert s == 200 and j["ok"], j
    s, j = client.j("POST", "/api/setlink",
                    {"name": "locky", "password": "pw-locky",
                     "save_password": True})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    seed = ("localStorage.setItem('drop_guest_pw', JSON.stringify({locky: 'pw-locky'}));"
            "localStorage.setItem('drop_link_use', JSON.stringify({locky: 3, other: 1}));")
    with sync_playwright() as pw:
        for label, w, h in [("mb", 390, 844), ("web", 1280, 800)]:
            for light in (False, True):
                browser, ctx, pg, fwd = _guest_page(
                    pw, port, w, h, init_script=seed, light=light)
                try:
                    pg.wait_for_timeout(1200)
                    pg.evaluate("() => doLogout()")
                    pg.wait_for_timeout(600)
                    pg.click("#gddchevbtn")
                    pg.wait_for_selector("#gddlist.open", timeout=5000)
                    pg.wait_for_timeout(400)
                    m = pg.evaluate("""() => { const l = document.querySelector('#gddlist');
                      const o = document.querySelector('#gddlist .ddopt:not(.ddsel)') || document.querySelector('#gddlist .ddopt');
                      const pw = document.querySelector('#gddlist .ddopt') ? document.querySelector('#gddlist .ddopt').querySelector('.ddpw') : null;
                      return {listBg: getComputedStyle(l).backgroundColor,
                        optBg: o ? getComputedStyle(o).backgroundColor : null,
                        optColor: o ? getComputedStyle(o).color : null,
                        pwText: pw ? pw.textContent : null}; }""")
                    if light:
                        assert m["listBg"] == "rgb(255, 255, 255)", (label, m)
                        assert m["optBg"] == "rgb(255, 255, 255)", (label, m)
                        assert m["optColor"] == "rgb(17, 24, 39)", (label, m)
                    else:
                        assert m["listBg"] == "rgb(18, 23, 42)", (label, m)
                        assert m["optBg"] == "rgb(18, 23, 42)", (label, m)
                        assert m["optColor"] == "rgb(238, 241, 248)", (label, m)
                    assert m["pwText"] == "••••••", (label, m)
                    pg.screenshot(path="%s/r53_list_guest_%s_%s.png" % (
                        PROOF, label, "light" if light else "dark"))
                    print("LIST GUEST %s %s: %s" % (label, "light" if light else "dark", m))
                finally:
                    browser.close()
        # Host Set Up list, web 1280, both themes.
        browser, pg = _pc_page(pw, port, 1280, 800, frameless=True)
        try:
            for light in (False, True):
                pg.evaluate("() => openLinkWin()")
                pg.wait_for_timeout(800)
                pg.click("#lkcurview")
                pg.wait_for_selector("#lkddlist.open", timeout=5000)
                pg.wait_for_timeout(400)
                m = pg.evaluate("""() => { const l = document.querySelector('#lkddlist');
                  const o = document.querySelector('#lkddlist .ddopt:not(.ddsel)') || document.querySelector('#lkddlist .ddopt');
                  return {listBg: getComputedStyle(l).backgroundColor,
                    optBg: o ? getComputedStyle(o).backgroundColor : null,
                    optColor: o ? getComputedStyle(o).color : null}; }""")
                if light:
                    pg.evaluate("() => document.documentElement.classList.add('light')")
                    pg.wait_for_timeout(300)
                    m = pg.evaluate("""() => { const l = document.querySelector('#lkddlist');
                      const o = document.querySelector('#lkddlist .ddopt:not(.ddsel)') || document.querySelector('#lkddlist .ddopt');
                      return {listBg: getComputedStyle(l).backgroundColor,
                        optBg: o ? getComputedStyle(o).backgroundColor : null,
                        optColor: o ? getComputedStyle(o).color : null}; }""")
                    assert m["listBg"] == "rgb(255, 255, 255)", m
                    assert m["optColor"] == "rgb(17, 24, 39)", m
                else:
                    assert m["listBg"] == "rgb(18, 23, 42)", m
                    assert m["optColor"] == "rgb(238, 241, 248)", m
                pg.screenshot(path="%s/r53_list_host_%s.png" % (
                    PROOF, "light" if light else "dark"))
                print("LIST HOST %s: %s" % ("light" if light else "dark", m))
                pg.evaluate("() => { document.querySelector('#lkcurview').click(); closeLinkWin(); }")
                pg.wait_for_timeout(400)
        finally:
            browser.close()


# --- (6) Menu light theme ---

def test_menu_light_theme(server):
    """(6) Menu: dark theme stays navy; light theme is light
    with readable dark text/icons, same layout -- on D
    (frameless), web, and MB widths."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink", {"name": "menuy"})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        # D (frameless PC app).
        browser, pg = _pc_page(pw, port, 1280, 800, frameless=True)
        try:
            pg.click("#menubtn")
            pg.wait_for_timeout(600)
            dark = pg.evaluate("""() => { const sb = document.querySelector('#sidebar');
              const card = document.querySelector('#sbsetupcard');
              return {bg: getComputedStyle(sb).backgroundColor,
                cardBg: getComputedStyle(card).backgroundColor,
                title: getComputedStyle(document.querySelector('.sbtitle')).color,
                row: getComputedStyle(document.querySelector('#sidebar .sbrow')).color,
                radius: getComputedStyle(sb).borderRadius,
                top: Math.round(sb.getBoundingClientRect().top)}; }""")
            assert dark == {"bg": "rgb(9, 13, 22)", "cardBg": "rgb(15, 23, 42)",
                            "title": "rgb(255, 255, 255)", "row": "rgb(241, 245, 249)",
                            "radius": "28px", "top": 0}, dark
            pg.screenshot(path="%s/r53_menu_d_dark.png" % PROOF)
            pg.evaluate("() => document.documentElement.classList.add('light')")
            pg.wait_for_timeout(400)
            light = pg.evaluate("""() => { const sb = document.querySelector('#sidebar');
              const card = document.querySelector('#sbsetupcard');
              const sw = document.querySelector('#swsep');
              return {bg: getComputedStyle(sb).backgroundColor,
                cardBg: getComputedStyle(card).backgroundColor,
                title: getComputedStyle(document.querySelector('.sbtitle')).color,
                row: getComputedStyle(document.querySelector('#sidebar .sbrow')).color,
                sec: getComputedStyle(document.querySelector('#sidebar .sbsec')).color,
                radius: getComputedStyle(sb).borderRadius,
                swOn: getComputedStyle(sw).backgroundColor}; }""")
            assert light["bg"] == "rgb(255, 255, 255)", light
            assert light["cardBg"] == "rgb(241, 245, 249)", light
            assert light["title"] == "rgb(15, 23, 42)", light
            assert light["row"] == "rgb(15, 23, 42)", light
            assert light["radius"] == "28px", light
            pg.screenshot(path="%s/r53_menu_d_light.png" % PROOF)
            print("MENU D: dark %s light %s" % (dark, light))
        finally:
            browser.close()
        # Web + MB host pages.
        for label, w, h in [("web", 1280, 800), ("mb", 390, 844)]:
            browser, pg = _host_web_page(pw, port, w, h)
            try:
                pg.click("#menubtn")
                pg.wait_for_timeout(600)
                pg.evaluate("() => document.documentElement.classList.add('light')")
                pg.wait_for_timeout(400)
                m = pg.evaluate("""() => { const sb = document.querySelector('#sidebar');
                  const card = document.querySelector('#sbsetupcard');
                  return {bg: getComputedStyle(sb).backgroundColor,
                    cardBg: getComputedStyle(card).backgroundColor,
                    title: getComputedStyle(document.querySelector('.sbtitle')).color,
                    row: getComputedStyle(document.querySelector('#sidebar .sbrow')).color}; }""")
                assert m["bg"] == "rgb(255, 255, 255)", (label, m)
                assert m["cardBg"] == "rgb(241, 245, 249)", (label, m)
                assert m["title"] == "rgb(15, 23, 42)", (label, m)
                assert m["row"] == "rgb(15, 23, 42)", (label, m)
                pg.screenshot(path="%s/r53_menu_%s_light.png" % (PROOF, label))
                print("MENU %s light: %s" % (label, m))
            finally:
                browser.close()


# --- (7) Exactly one Save Password checkbox on login ---

def test_one_checkbox_login_both_states(server):
    """(7) Locked address logged out, web + MB: exactly ONE
    hit-testable Save Password checkbox; the native input stays
    opacity:0 and intrinsic-width in BOTH states -- the enabled
    state AND the disabled state (open address typed, the
    image-76 state: disabled + unchecked, where the native box
    used to show through as a grey square). Screenshots + a
    grey-pixel scan of the label row prove no phantom box."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink",
                    {"name": "locky", "password": "pw-locky",
                     "save_password": True})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        for label, w, h in [("web", 1280, 800), ("mb", 390, 844)]:
            # State A: locked address is current, enabled + checked.
            browser, ctx, pg, fwd = _guest_page(pw, port, w, h)
            try:
                pg.wait_for_timeout(1200)
                pg.evaluate("() => doLogout()")
                pg.wait_for_timeout(800)
                c = _hit_checkbox_count(pg)
                assert c == {"n": 1, "ids": ["gloginsavechk"]}, (label, c)
                st = _native_chk_state(pg)
                assert st["opacity"] == "0", (label, st)
                assert st["rectW"] <= 20, (label, st)
                assert st["checked"] is True and st["disabled"] is False, (label, st)
                grey = _grey_pixels_in_label_row(pg)
                assert grey <= 12, (label, grey)
                pg.screenshot(path="%s/r53_login_one_%s_enabled.png" % (PROOF, label))
                print("ONE CHECKBOX %s enabled: %s grey px %d" % (label, st, grey))
            finally:
                browser.close()
            # State B: an OPEN address is current and typed -- the
            # image-76 state (disabled + unchecked). checkOpenAddress
            # only reports a typed address as open when it IS the
            # current address, so the server switches first.
            s, j = client.j("POST", "/api/setlink", {"name": "openaddr"})
            assert s == 200 and j["ok"], j
            browser, ctx, pg, fwd = _guest_page(pw, port, w, h)
            try:
                pg.wait_for_timeout(1200)
                pg.evaluate("() => doLogout()")
                pg.wait_for_timeout(800)
                pg.fill("#gloginlink", "openaddr")
                pg.wait_for_function(
                    "() => document.querySelector('#gloginsavechk').disabled",
                    timeout=5000)
                pg.wait_for_timeout(300)
                c = _hit_checkbox_count(pg)
                assert c == {"n": 1, "ids": ["gloginsavechk"]}, (label, c)
                st = _native_chk_state(pg)
                assert st["opacity"] == "0", (label, st)
                assert st["rectW"] <= 20, (label, st)
                assert st["checked"] is False and st["disabled"] is True, (label, st)
                grey = _grey_pixels_in_label_row(pg)
                assert grey <= 12, (label, grey)
                pg.screenshot(path="%s/r53_login_one_%s_disabled.png" % (PROOF, label))
                print("ONE CHECKBOX %s disabled(image-76): %s grey px %d" % (label, st, grey))
            finally:
                browser.close()
            # Back to the locked address for the next width.
            s, j = client.j("POST", "/api/setlink",
                            {"name": "locky", "password": "pw-locky",
                             "save_password": True})
            assert s == 200 and j["ok"], j


# --- (8) "Save on this device" button ---

def test_save_on_this_device_button(server):
    """(8) The download confirm button reads "Save on this
    device", solid blue #277ff0 with white text, dark AND
    light themes, web + MB."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink", {"name": "cfy"})
    assert s == 200 and j["ok"], j
    open(os.path.join(j["folder"], "hello.txt"), "w").write("hello preview\n")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        for label, w, h in [("web", 1280, 800), ("mb", 390, 844)]:
            browser, pg = _host_web_page(pw, port, w, h)
            try:
                pg.evaluate("() => { if (window.innerWidth < 721) setTab('files'); }")
                pg.wait_for_timeout(400)
                pg.wait_for_selector(".frow .fname", timeout=10000)
                pg.click(".frow .fname >> nth=0")
                pg.wait_for_selector("#previewdl", timeout=5000)
                pg.wait_for_timeout(400)
                pg.click("#previewdl")
                pg.wait_for_selector("#cfdlg.open", timeout=5000)
                pg.wait_for_timeout(300)
                for light in (False, True):
                    if light:
                        pg.evaluate("() => document.documentElement.classList.add('light')")
                        pg.wait_for_timeout(300)
                    m = pg.evaluate("""() => { const b = document.querySelector('#cfyes');
                      const cs = getComputedStyle(b);
                      return {text: b.textContent, bg: cs.backgroundColor,
                        color: cs.color, bgImage: cs.backgroundImage}; }""")
                    assert m["text"] == "Save on this device", (label, m)
                    assert m["bg"] == "rgb(39, 127, 240)", (label, m)
                    assert m["color"] == "rgb(255, 255, 255)", (label, m)
                    assert m["bgImage"] == "none", (label, m)
                    print("CFYES %s %s: %s" % (label, "light" if light else "dark", m))
                pg.screenshot(path="%s/r53_cfyes_%s.png" % (PROOF, label))
            finally:
                browser.close()


# --- (9) MB Saved header ---

def test_saved_header_mb(server):
    """(9) MB Saved view: title exactly centred, red Delete on
    the right, Back on the left (solid blue). Desktop web keeps
    the old row (Delete not red, title not centred)."""
    client, base, proc, port, home = server
    s, j = client.j("POST", "/api/setlink",
                    {"name": "savey", "password": "pw-savey",
                     "save_password": True})
    assert s == 200 and j["ok"], j
    from playwright.sync_api import sync_playwright
    seed = ("localStorage.setItem('dropit_dl', JSON.stringify("
            "{'a.txt': {size: 10, ts: 1700000000}}));")
    with sync_playwright() as pw:
        browser, ctx, pg, fwd = _guest_page(
            pw, port, 390, 844, init_script=seed)
        try:
            pg.click("#gsavedbtn")
            pg.wait_for_timeout(600)
            m = pg.evaluate("""() => { const head = document.querySelector('.gsavedhead');
              const b = head.querySelector('b'); const del = document.querySelector('#gsaveddel');
              const back = document.querySelector('#gsavedback');
              const hr = head.getBoundingClientRect(), br = b.getBoundingClientRect(),
                    dr = del.getBoundingClientRect(), kr = back.getBoundingClientRect();
              return {titleCx: Math.round(br.x + br.width / 2),
                headCx: Math.round(hr.x + hr.width / 2),
                titleLeft: Math.round(br.x), titleRight: Math.round(br.right),
                delLeft: Math.round(dr.x), delRight: Math.round(dr.right),
                backLeft: Math.round(kr.x), backRight: Math.round(kr.right),
                delBg: getComputedStyle(del).backgroundColor,
                delColor: getComputedStyle(del).color,
                backBg: getComputedStyle(back).backgroundColor,
                backColor: getComputedStyle(back).color,
                titlePos: getComputedStyle(b).position}; }""")
            assert abs(m["titleCx"] - m["headCx"]) <= 3, m
            assert m["delLeft"] >= m["titleRight"], m
            assert m["backRight"] <= m["titleLeft"], m
            assert m["delBg"] == "rgb(239, 68, 68)", m
            assert m["delColor"] == "rgb(255, 255, 255)", m
            assert m["backBg"] == "rgb(39, 127, 240)", m
            assert m["backColor"] == "rgb(255, 255, 255)", m
            pg.screenshot(path="%s/r53_saved_head_mb.png" % PROOF)
            print("SAVED HEAD MB: %s" % m)
        finally:
            browser.close()
        # Desktop web: old row preserved.
        browser, ctx, pg, fwd = _guest_page(
            pw, port, 1280, 800, init_script=seed)
        try:
            pg.click("#gsavedbtn")
            pg.wait_for_timeout(600)
            m = pg.evaluate("""() => { const b = document.querySelector('.gsavedhead b');
              const del = document.querySelector('#gsaveddel');
              return {titlePos: getComputedStyle(b).position,
                delBg: getComputedStyle(del).backgroundColor}; }""")
            assert m["titlePos"] == "static", m
            assert m["delBg"] != "rgb(239, 68, 68)", m
            print("SAVED HEAD DESKTOP unchanged: %s" % m)
        finally:
            browser.close()
