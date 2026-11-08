"""Live DOM click-tests for 2.8.35 items 4 + 6 (Remove dialog +
Save Password) -- runs against the CURRENT on-disk dropit.py.
Companion to test_link_round50.py; the round50 live tests cover
the server contracts, this file drives the actual dialog in a
real Chromium DOM: every checkbox combination, Cancel, and the
Save Password list behaviour (hashed vs "No password").
"""
import os

import pytest

from test_link_round2 import server  # noqa: F401,E402
from test_link_round46 import _pc_page  # noqa: E402

PROOF = "/home/hatch/workspace/dropit-proof-round50"


def _toast_text(pg):
    return pg.evaluate(
        "() => (document.querySelector('#toast') || {}).textContent || ''")


def _open_setup(pg):
    pg.evaluate("() => openLinkWin()")
    pg.wait_for_function(
        "() => getComputedStyle(document.querySelector('#lkwrap'))"
        ".display === 'flex'", timeout=10000)
    pg.wait_for_timeout(700)


def _open_history(pg):
    pg.click("#lkddchevbtn")
    pg.wait_for_function(
        "() => document.querySelector('#lkddlist')"
        ".classList.contains('open')", timeout=5000)
    pg.wait_for_timeout(300)


def _refresh_auth(pg, name):
    """The page's AUTH is a snapshot from load time; after an API
    setlink the page must re-fetch it or SAVE sees an empty
    current address and shakes instead of saving."""
    pg.evaluate("() => checkAuth()")
    pg.wait_for_function(
        "() => (typeof AUTH !== 'undefined') && AUTH.address_name === %s"
        % repr(name), timeout=5000)


def _make_addr(client, base, name, note=True, afile=True):
    assert client.j("POST", "/api/setlink", {"name": name})[0] == 200
    if note:
        st, j = client.j("POST", "/api/snippet", {"text": "note-" + name})
        assert st == 200 and j.get("ok"), j
    if afile:
        d = base / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "file.txt").write_text("f-" + name)
    st, j = client.j("GET", "/api/notes")
    assert st == 200, j
    return j


def _notes_for(client, name, home=None):
    """Notes live in notes-link-<addr>.json under the server HOME
    data dir -- read the file directly. GET /api/notes only
    returns the CURRENT address's notes, which is wrong after a
    remove switches the current address away."""
    import json as _json
    if home is None:
        return []
    p = home / ".config" / "DropIt" / ("notes-link-%s.json" % name)
    try:
        data = _json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [n for n in data if ("note-" + name) in (n.get("text") or "")]


def _hist_keys(client):
    st, j = client.j("GET", "/api/linkhistory")
    assert st == 200 and j["ok"], j
    return [e["key"] for e in j["entries"]]


def test_setup_window_screenshots(server):
    """Set Up window (dark + light): moved Create Separate
    Folders sits under the folder field with its "i", Save
    Password checkbox sits in the password row, aligned and
    centred with the field."""
    client, base, proc, port, home = server
    assert client.j("POST", "/api/setlink", {"name": "r50s"})[0] == 200
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        for theme in ("dark", "light"):
            browser, pg = _pc_page(pw, port, 1280, 800, frameless=True)
            try:
                if theme == "light":
                    pg.evaluate("() => document.documentElement"
                                ".classList.add('light')")
                _open_setup(pg)
                m = pg.evaluate("""() => {
                  const sep = document.querySelector('#lkseplabel');
                  const info = document.querySelector('#lksepinfo');
                  const save = document.querySelector('#lksavepwchk');
                  const pw = document.querySelector('#lkpw');
                  const folder = document.querySelector('#lkfolderview');
                  const r = e => { const b = e.getBoundingClientRect();
                    return {top: Math.round(b.top), h: Math.round(b.height),
                            vis: getComputedStyle(e).visibility,
                            disp: getComputedStyle(e).display}; };
                  return {sep: sep ? r(sep) : null,
                    infoTitle: info ? info.getAttribute('title') : null,
                    infoVis: info ? r(info) : null,
                    save: save ? {checked: save.checked, ...r(save)} : null,
                    pwTop: pw ? Math.round(pw.getBoundingClientRect().top) : null,
                    folderTop: folder ? Math.round(folder.getBoundingClientRect().top) : null,
                    saveCenterY: save ? Math.round(save.getBoundingClientRect().top
                      + save.getBoundingClientRect().height / 2) : null,
                    pwCenterY: pw ? Math.round(pw.getBoundingClientRect().top
                      + pw.getBoundingClientRect().height / 2) : null};
                }""")
                assert m["sep"] and m["sep"]["disp"] != "none", m
                # Separate-folders row sits under the folder field.
                assert m["folderTop"] < m["sep"]["top"], m
                assert m["infoTitle"] and "folder" in m["infoTitle"].lower(), m
                assert m["save"] and m["save"]["disp"] != "none", m
                # Save Password checkbox vertically centred on the
                # password field (within 6px).
                assert abs(m["saveCenterY"] - m["pwCenterY"]) <= 6, m
                pg.screenshot(path="%s/r50_setup_%s.png" % (PROOF, theme))
                print("SETUP %s: %s" % (theme, m))
            finally:
                browser.close()


def test_remove_dialog_click_live(server):
    """Light mode, real DOM: the Delete (Remove) button is
    visible, both checkboxes check, every combination works,
    Cancel leaves everything untouched."""
    client, base, proc, port, home = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, pg = _pc_page(pw, port, 1280, 800, frameless=True)
        try:
            pg.evaluate("() => document.documentElement"
                        ".classList.add('light')")
            combos = [
                # (notes, files, expected toast fragment)
                (True, False, "Notes deleted for r50r"),
                (False, True, "Files deleted for r50r"),
                (True, True, "notes and files have been deleted"),
                (False, False, "Files and notes are still there"),
            ]
            for i, (notes, files, frag) in enumerate(combos):
                name = "r50r"
                _make_addr(client, base, name)
                _refresh_auth(pg, name)
                assert name in _hist_keys(client)
                _open_setup(pg)
                _open_history(pg)
                pg.click('[data-delhist="%s"]' % name)
                pg.wait_for_function(
                    "() => document.querySelector('#addrrempop')"
                    ".classList.contains('open')", timeout=5000)
                pg.wait_for_timeout(300)
                vis = pg.evaluate("""() => {
                  const b = document.querySelector('#addrremconfirm');
                  const cs = getComputedStyle(b);
                  const r = b.getBoundingClientRect();
                  return {w: Math.round(r.width), h: Math.round(r.height),
                    bg: cs.backgroundColor, color: cs.color,
                    text: b.textContent.trim(),
                    notesChk: document.querySelector('#addrremnotes').checked,
                    filesChk: document.querySelector('#addrremfiles').checked,
                    filesDisabled: document.querySelector('#addrremfiles').disabled};
                }""")
                assert vis["w"] > 0 and vis["h"] > 0, vis
                assert vis["text"] == "Delete", vis
                # Light mode: red button (#ef4444), white text --
                # not white-on-white.
                assert vis["bg"] == "rgb(239, 68, 68)", vis
                assert vis["color"] == "rgb(255, 255, 255)", vis
                assert vis["filesDisabled"] is False, vis
                if i == 0:
                    pg.screenshot(
                        path="%s/r50_remove_dialog_light.png" % PROOF)
                if notes:
                    pg.evaluate("() => document.querySelector"
                                "('#addrremnotes').click()")
                if files:
                    pg.evaluate("() => document.querySelector"
                                "('#addrremfiles').click()")
                chk = pg.evaluate("""() => ({
                  n: document.querySelector('#addrremnotes').checked,
                  f: document.querySelector('#addrremfiles').checked})""")
                assert chk["n"] is notes and chk["f"] is files, chk
                pg.click("#addrremconfirm")
                pg.wait_for_function(
                    "() => (document.querySelector('#toast') || {})"
                    ".textContent.includes(%s)" % repr(frag),
                    timeout=5000)
                assert frag in _toast_text(pg), _toast_text(pg)
                assert name not in _hist_keys(client)
                # Notes/files state on disk matches the combo.
                has_note = bool(_notes_for(client, name, home))
                has_file = (base / name / "file.txt").exists()
                assert has_note is (not notes), (name, has_note)
                assert has_file is (not files), (name, has_file)
                print("REMOVE combo %s: toast ok, note=%s file=%s"
                      % (chk, has_note, has_file))
                pg.wait_for_timeout(400)
            # Cancel: everything untouched.
            _make_addr(client, base, "r50r")
            _refresh_auth(pg, "r50r")
            _open_setup(pg)
            _open_history(pg)
            pg.click('[data-delhist="r50r"]')
            pg.wait_for_function(
                "() => document.querySelector('#addrrempop')"
                ".classList.contains('open')", timeout=5000)
            pg.click("#addrremcancel")
            pg.wait_for_timeout(400)
            assert "r50r" in _hist_keys(client)
            assert _notes_for(client, "r50r", home)
            assert (base / "r50r" / "file.txt").exists()
            print("REMOVE cancel: address, note and file all kept")
        finally:
            browser.close()


def test_save_password_dom_live(server):
    """DOM: check Save Password + set a password -> history
    list shows hashed dots; uncheck + save -> "No password"."""
    client, base, proc, port, home = server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, pg = _pc_page(pw, port, 1280, 800, frameless=True)
        try:
            assert client.j("POST", "/api/setlink",
                            {"name": "r50d"})[0] == 200
            _refresh_auth(pg, "r50d")
            _open_setup(pg)
            # Save Password checked + password -> hashed.
            pg.evaluate("() => { const c = document.querySelector"
                        "('#lksavepwchk'); if(!c.checked) c.click(); }")
            pg.fill("#lkpw", "dompw123")
            pg.click("#lkset")
            pg.wait_for_timeout(600)
            _open_setup(pg)
            _open_history(pg)
            row = pg.evaluate("""() => {
              const rows = [...document.querySelectorAll('#lkddlist .ddopt')];
              const row = rows.find(r => r.textContent.includes('r50d'));
              return row ? row.querySelector('.ddpw').textContent : null;
            }""")
            assert row == "••••••", row
            print("SAVE-PW checked: list shows %r" % row)
            # Uncheck Save Password + save -> "No password".
            # NOTE: typing in the password field auto-checks the
            # box (input handler), so the uncheck must come AFTER
            # the fill -- that is the real user flow too.
            pg.fill("#lkpw", "dompw123")
            pg.evaluate("() => { const c = document.querySelector"
                        "('#lksavepwchk'); if(c.checked) c.click(); }")
            pg.click("#lkset")
            pg.wait_for_timeout(600)
            _open_setup(pg)
            _open_history(pg)
            row = pg.evaluate("""() => {
              const rows = [...document.querySelectorAll('#lkddlist .ddopt')];
              const row = rows.find(r => r.textContent.includes('r50d'));
              return row ? row.querySelector('.ddpw').textContent : null;
            }""")
            assert row == "No password", row
            print("SAVE-PW unchecked: list shows %r" % row)
        finally:
            browser.close()
