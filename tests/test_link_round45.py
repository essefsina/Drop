"""v2.8.30 round (Essef Nov 6, ~5:24 PM) -- web/desktop only.

Three items, nothing else:
1. CANCELLED UPLOADS MUST NEVER APPEAR IN SHARED FILES (web +
   PC app side). The 2.8.24 pill X already aborts the XHR, but
   the server still wrote the truncated body as a file:
   rfile.read(length) returns SHORT on abort, and
   parse_multipart still yields the truncated part (header +
   partial content, no closing boundary), which the old code
   wrote and answered 200 for. Now /api/upload discards any
   body that is short of Content-Length or lacks the closing
   "--boundary--" marker -- nothing is written, no AI index
   starts -- and the write path only runs on a fully-received
   body. Verified two ways: a raw-socket partial POST (server
   level, deterministic) and a live Playwright upload
   cancelled mid-flight under CDP upload throttling (list
   before/after, /api/files + shared-folder contents).
   A pre-existing complete file of the same name is never
   touched by a discarded upload.
3. SET PASSWORD FOR ADDRESS WINDOW: SAVE was 110px LEFT of
   centre on 2.8.29 (measured) because the #lkset/#lockpwsave/
   #msave ID rule makes it inline-flex, so margin:auto
   computed to 0. #lockpwpop #lockpwsave restores block flex
   + auto margins, so SAVE is truly centred (icon + text one
   centred unit, one-space floppy gap kept); the PASSWORD
   label is centred too, with the label-to-field gap grown
   6px -> 16px and the field-to-SAVE gap grown (margin-top
   16px -> 24px) -- the "space under password" from Essef's
   annotated photo. The box is SLIGHTLY TRANSPARENT
   (rgba .93 both modes + backdrop blur; the h4's solid
   background goes transparent so no opaque strip shows)
   and ANIMATES: lockpwpopin (.22s) on open, lockpwpopout
   (.18s) on close, the close held under .closing until the
   out-animation finishes. Title, field, eye, red X
   unchanged.
4. WEB DOWNLOAD -> OPEN IS BACK (web file rows only). The
   2.8.25 always-Open icon is reverted for web: a row shows
   the download arrow + "Download" until the file is saved
   on this phone (dlLabel: Open only when hasBridge() or
   isDownloaded(f)); after a completed download it
   re-renders as Open; a discarded / failed download never
   marks it, so it stays Download. The PC app is untouched
   (hasBridge() -> always "Open", direct open_file bridge).
   Preview on file-name click stays on both.
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
import app as appmod  # noqa: E402
from test_link_folders import Client, _free_port  # noqa: E402
from test_link_round2 import server, _raw  # noqa: F401,E402
from test_link_round36 import _playwright  # noqa: E402
from test_link_round37 import _host_page, _make_fixtures, _open_preview  # noqa: E402
from test_link_round44 import _save_gap, desktop_server  # noqa: E402,F401

PAGE = D.PAGE
SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py"),
           encoding="utf-8").read()

PROOF = "/home/hatch/workspace/dropit-proof-round45"
os.makedirs(PROOF, exist_ok=True)

ADDR = "10-0-0-85-8000"  # Essef's actual address form (LAN IP:port dashed)


def test_version_is_2_8_30():
    assert D.VERSION == "2.8.30"


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
        p = os.path.join(PROOF, "r45_script_%d.js" % i)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(js)
        out = subprocess.run(["node", "--check", p],
                             capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr


# ---- (1) cancelled upload: server level -------------------------------
# Deterministic: a raw socket POST that sends only part of the
# declared multipart body, then closes -- exactly what an
# aborted XHR looks like to the server.

def _partial_post(port, fname, total_bytes, send_bytes, boundary="----r45b"):
    """Send a multipart upload header + `send_bytes` of a
    `total_bytes` file body, then close the socket abruptly.
    Returns the folder listing + /api/files names afterwards."""
    head = ("--%s\r\nContent-Disposition: form-data; name=\"file\"; "
            "filename=\"%s\"\r\nContent-Type: application/octet-stream\r\n\r\n"
            % (boundary, fname)).encode()
    tail = ("\r\n--%s--\r\n" % boundary).encode()
    total = len(head) + total_bytes + len(tail)
    s = socket.create_connection(("127.0.0.1", port), timeout=10)
    s.sendall(("POST /api/upload HTTP/1.1\r\nHost: x\r\n"
               "Content-Type: multipart/form-data; boundary=%s\r\n"
               "Content-Length: %d\r\n\r\n" % (boundary, total)).encode())
    s.sendall(head)
    s.sendall(b"A" * send_bytes)
    s.close()
    time.sleep(2.0)


def _files_via_api(client):
    st, files = client.j("GET", "/api/files")
    assert st == 200, files
    return [f["name"] for f in files]


def test_server_partial_upload_leaves_no_file(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": ADDR})
    linkdir = os.path.join(str(base), ADDR)
    os.makedirs(linkdir, exist_ok=True)
    # Positive control: a complete upload lands in Shared Files.
    st, _ = client.upload("keepme.txt", b"complete and fine\n")
    assert st == 200, st
    assert _files_via_api(client) == ["keepme.txt"]
    assert os.listdir(linkdir) == ["keepme.txt"]
    # (a) abort halfway through a 5MB body: nothing appears.
    _partial_post(port, "cancelled-big.bin", 5 * 1024 * 1024, 100 * 1024)
    assert "cancelled-big.bin" not in _files_via_api(client)
    assert "cancelled-big.bin" not in os.listdir(linkdir)
    assert os.listdir(linkdir) == ["keepme.txt"]
    # (b) abort at 99.9% -- body missing only the closing
    # boundary: still discarded (the marker is the proof of a
    # complete body, not the byte count alone).
    _partial_post(port, "almost-done.bin", 200 * 1024, 200 * 1024 - 50)
    assert "almost-done.bin" not in _files_via_api(client)
    assert "almost-done.bin" not in os.listdir(linkdir)
    # (c) abort an upload whose name already exists complete:
    # the original file is untouched (same bytes, same size).
    _partial_post(port, "keepme.txt", 1024 * 1024, 10 * 1024)
    assert _files_via_api(client) == ["keepme.txt"]
    with open(os.path.join(linkdir, "keepme.txt"), "rb") as fh:
        assert fh.read() == b"complete and fine\n"
    # (d) a complete upload still works after the discards.
    st, _ = client.upload("after.txt", b"still works\n")
    assert st == 200, st
    assert sorted(_files_via_api(client)) == ["after.txt", "keepme.txt"]
    print("SERVER-PARTIAL: cancelled uploads left no file; "
          "complete uploads still land (keepme.txt + after.txt)")


# ---- (1b) cancelled upload: live browser cancel ------------------------
# A real upload through the page, throttled so it is still in
# flight when the pill X is hit, then list before/after.

def test_live_cancel_mid_upload_leaves_no_file(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": ADDR})
    linkdir = os.path.join(str(base), ADDR)
    os.makedirs(linkdir, exist_ok=True)
    # A 3MB file + 40KB/s upload throttle = ~75s of flight.
    big = os.path.join(str(base), "big-cancel.bin")
    with open(big, "wb") as fh:
        fh.write(os.urandom(3 * 1024 * 1024))
    pw = _playwright()
    try:
        browser, pg = _host_page(pw, port, 1280, 800)
        try:
            cdp = pg.context.new_cdp_session(pg)
            cdp.send("Network.enable")
            cdp.send("Network.emulateNetworkConditions", {
                "offline": False, "latency": 50,
                "downloadThroughput": -1,
                "uploadThroughput": 40 * 1024})
            before = pg.evaluate(
                "() => fetch('/api/files').then(r => r.json())")
            assert before == [], before
            pg.set_input_files("#picker", big)
            # Wait until the ring is actually progressing.
            deadline = time.time() + 20
            prog = None
            while time.time() < deadline:
                prog = pg.evaluate("""() => ({
                  ring: document.querySelector('#upfloat').classList.contains('show'),
                  num: document.querySelector('#upringnum').textContent,
                  name: document.querySelector('#upfloatname').textContent})""")
                if prog["ring"] and prog["num"] not in ("0", ""):
                    break
                pg.wait_for_timeout(500)
            print("UPLOAD IN FLIGHT: %s" % prog)
            assert prog["ring"] is True, prog
            assert prog["name"] == "big-cancel.bin", prog
            # Cancel from the pill X, exactly as Essef does.
            pg.click("#upcancel")
            pg.wait_for_timeout(2500)
            toast = pg.evaluate(
                "() => document.querySelector('#toast') ? "
                "document.querySelector('#toast').textContent : "
                "document.body.innerText.includes('Upload cancelled')")
            print("AFTER CANCEL toast check: %r" % toast)
            after = pg.evaluate(
                "() => fetch('/api/files').then(r => r.json())")
            on_disk = os.listdir(linkdir)
            print("AFTER CANCEL api/files=%r disk=%r" % (after, on_disk))
            assert after == [], after
            assert on_disk == [], on_disk
            pg.screenshot(path=os.path.join(
                PROOF, "r45_cancel_no_file.png"))
        finally:
            browser.close()
    finally:
        pw.stop()


# ---- (3) Set Password popup --------------------------------------------

def _lockpw_geom(pg):
    return pg.evaluate("""() => {
      const pop = document.querySelector('#lockpwpop');
      const box = document.querySelector('.lockpwbox');
      const save = document.querySelector('#lockpwsave');
      const cap = document.querySelector('.lockpwcap');
      const field = document.querySelector('.lockpwfield');
      const err = document.querySelector('#lockpwerr');
      const h4 = document.querySelector('.lockpwbox h4');
      const br = box.getBoundingClientRect(), sr = save.getBoundingClientRect();
      const cr = cap.getBoundingClientRect(), fr = field.getBoundingClientRect();
      const cs = getComputedStyle(box), ccs = getComputedStyle(cap);
      const scs = getComputedStyle(save), hcs = getComputedStyle(h4);
      return {popOpen: pop.classList.contains('open'),
        popClosing: pop.classList.contains('closing'),
        box: {w: Math.round(br.width), cx: +(br.x + br.width/2).toFixed(1),
              bg: cs.backgroundColor, opacity: cs.opacity},
        h4bg: hcs.backgroundColor,
        save: {w: Math.round(sr.width), cx: +(sr.x + sr.width/2).toFixed(1),
               off: +((sr.x + sr.width/2) - (br.x + br.width/2)).toFixed(1),
               display: scs.display, marginLeft: scs.marginLeft,
               marginRight: scs.marginRight, marginTop: scs.marginTop,
               gapCss: scs.gap},
        cap: {cx: +(cr.x + cr.width/2).toFixed(1),
              off: +((cr.x + cr.width/2) - (br.x + br.width/2)).toFixed(1),
              align: ccs.textAlign, marginBottom: ccs.marginBottom,
              gapToField: +(fr.top - cr.bottom).toFixed(1)},
        fieldBottomToSave: +(sr.top - fr.bottom).toFixed(1),
        errH: Math.round(err.getBoundingClientRect().height),
        xVisible: (() => { const x = document.querySelector('#lockpwcloseX');
          const r = x.getBoundingClientRect(); return r.width > 0; })(),
        anims: [...box.getAnimations()].map(a => a.animationName)};
    }""")


def test_live_lockpw_centred_spaced_transparent_animated(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": ADDR})
    _make_fixtures(os.path.join(str(base), ADDR))
    pw = _playwright()
    try:
        for light in (False, True):
            browser, pg = _host_page(pw, port, 1280, 800, light=light)
            try:
                # Pop-IN: sample the animation while it runs.
                pg.evaluate("() => openLockPopup()")
                pg.wait_for_timeout(60)
                during = pg.evaluate("""() => {
                  const box = document.querySelector('.lockpwbox');
                  const cs = getComputedStyle(box);
                  return {anims: [...box.getAnimations()].map(a => a.animationName),
                          opacity: +cs.opacity,
                          transform: cs.transform}; }""")
                print("LOCKPW POP-IN %s: %s"
                      % ("light" if light else "dark", during))
                assert "lockpwpopin" in during["anims"], during
                assert during["opacity"] < 1 or during["transform"] != "none", during
                pg.wait_for_timeout(500)  # let the .22s pop-in finish
                m = _lockpw_geom(pg)
                print("LOCKPW %s: %s" % ("light" if light else "dark", m))
                assert m["popOpen"] is True, m
                # SAVE centred in the window (was -110px on 2.8.29).
                assert m["save"]["display"] == "flex", m
                assert abs(m["save"]["off"]) <= 2, m
                assert m["save"]["marginLeft"] != "0px", m
                # PASSWORD label centred, with space under it.
                assert m["cap"]["align"] == "center", m
                assert abs(m["cap"]["off"]) <= 2, m
                assert m["cap"]["marginBottom"] == "16px", m
                assert m["cap"]["gapToField"] >= 14, m
                # Space under the password field before SAVE too.
                assert m["fieldBottomToSave"] >= 48, m
                # SLIGHTLY TRANSPARENT: rgba .93, title strip not opaque.
                assert m["box"]["bg"].startswith("rgba("), m
                assert abs(float(m["box"]["bg"].split(",")[-1].rstrip(")")) - 0.93) < 0.01, m
                assert m["h4bg"] in ("rgba(0, 0, 0, 0)", "transparent"), m
                # Red X still there; SAVE one-space floppy gap kept.
                assert m["xVisible"] is True, m
                g = _save_gap(pg, "#lockpwsave")
                print("LOCKPW SAVE gap %s: %s" % ("light" if light else "dark", g))
                assert g["gapCss"] == "4px", g
                assert abs(g["gap"] - g["spaceW"]) <= 1.5, g
                assert abs(g["unitOff"]) <= 2, g
                pg.screenshot(path=os.path.join(
                    PROOF, "r45_lockpw_%s.png" % ("light" if light else "dark")))
                # Pop-OUT: close, sample the out-animation mid-flight.
                pg.evaluate("() => closeLockPopup()")
                pg.wait_for_timeout(60)
                out = pg.evaluate("""() => {
                  const pop = document.querySelector('#lockpwpop');
                  const box = document.querySelector('.lockpwbox');
                  return {open: pop.classList.contains('open'),
                          closing: pop.classList.contains('closing'),
                          anims: [...box.getAnimations()].map(a => a.animationName),
                          opacity: +getComputedStyle(box).opacity}; }""")
                print("LOCKPW POP-OUT %s: %s" % ("light" if light else "dark", out))
                assert out["open"] is True and out["closing"] is True, out
                assert "lockpwpopout" in out["anims"], out
                pg.wait_for_timeout(400)  # past the .18s pop-out
                gone = pg.evaluate("""() => {
                  const pop = document.querySelector('#lockpwpop');
                  return {open: pop.classList.contains('open'),
                          closing: pop.classList.contains('closing'),
                          display: getComputedStyle(pop).display}; }""")
                print("LOCKPW CLOSED %s: %s" % ("light" if light else "dark", gone))
                assert gone["open"] is False and gone["closing"] is False, gone
                assert gone["display"] == "none", gone
                # Reopen works after a close (no stuck .closing).
                pg.evaluate("() => openLockPopup()")
                pg.wait_for_timeout(500)
                assert pg.evaluate(
                    "() => document.querySelector('#lockpwpop')"
                    ".classList.contains('open')") is True
                pg.evaluate("() => closeLockPopup()")
                pg.wait_for_timeout(400)
            finally:
                browser.close()
    finally:
        pw.stop()


# ---- (4) web Download -> Open -------------------------------------------
# Live, all three states, on the plain web page (no pywebview
# bridge): Download first, Open after a completed download,
# Download again after a discarded download. The confirm
# dialog (#cfdlg) is the Save/Discard step: #cfyes keeps it,
# #cfno discards it.

def _row_btn(pg, name):
    return pg.evaluate("""(name) => {
      const row = [...document.querySelectorAll('#files .frow')]
        .find(r => r.dataset.frow === name);
      if (!row) return null;
      const b = row.querySelector('[data-dl]');
      if (!b) return null;
      return {title: b.title,
              isDl: b.innerHTML.includes('M21 15v4'),
              isOpen: b.innerHTML.includes('M18 13v6a2 2 0 01-2 2H5')};
    }""", name)


def _click_row_btn(pg, name):
    pg.evaluate("""(name) => {
      const row = [...document.querySelectorAll('#files .frow')]
        .find(r => r.dataset.frow === name);
      row.querySelector('[data-dl]').click();
    }""", name)


def test_live_web_download_open_states(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": ADDR})
    _make_fixtures(os.path.join(str(base), ADDR))
    pw = _playwright()
    try:
        browser, pg = _host_page(pw, port, 1280, 800)
        try:
            assert pg.evaluate("() => !!(window.pywebview && window.pywebview.api)") is False
            pg.wait_for_selector("#files .frow", timeout=10000)
            # (a) DOWNLOAD shown initially, for both files.
            b0 = _row_btn(pg, "pic.png")
            b1 = _row_btn(pg, "notes.txt")
            print("ROW INITIAL pic=%s notes=%s" % (b0, b1))
            assert b0 == {"title": "Download", "isDl": True, "isOpen": False}, b0
            assert b1 == {"title": "Download", "isDl": True, "isOpen": False}, b1
            assert pg.evaluate(
                "() => localStorage.getItem('dropit_dl')") in (None, "{}")
            pg.screenshot(path=os.path.join(PROOF, "r45_dl_initial.png"))
            # Preview on file-name click still works (untouched).
            _open_preview(pg, "pic.png")
            assert pg.evaluate(
                "() => document.querySelector('#previewpop')"
                ".classList.contains('open')") is True
            pg.evaluate("() => document.querySelector('#previewclose2').click()")
            pg.wait_for_timeout(400)
            # (b) COMPLETED download -> OPEN.
            _click_row_btn(pg, "pic.png")
            pg.wait_for_selector("#cfdlg.open", timeout=10000)
            dlg = pg.evaluate("""() => ({
              title: document.querySelector('#cftitle').textContent,
              msg: document.querySelector('#cfmsg').textContent})""")
            print("DL DIALOG: %s" % dlg)
            assert "Download complete" in dlg["title"], dlg
            assert "pic.png" in dlg["msg"], dlg
            pg.click("#cfyes")
            pg.wait_for_timeout(1500)
            b0b = _row_btn(pg, "pic.png")
            print("ROW AFTER SAVE pic=%s" % b0b)
            assert b0b == {"title": "Open", "isDl": False, "isOpen": True}, b0b
            dlstate = json.loads(pg.evaluate(
                "() => localStorage.getItem('dropit_dl')"))
            assert "pic.png" in dlstate, dlstate
            pg.screenshot(path=os.path.join(PROOF, "r45_dl_after_save.png"))
            # Tapping Open opens the saved file (viewer), no re-download.
            _click_row_btn(pg, "pic.png")
            pg.wait_for_timeout(1200)
            view = pg.evaluate("""() => ({
              open: document.querySelector('#viewer').classList.contains('open'),
              title: document.querySelector('#vtitle').textContent,
              hasImg: !!document.querySelector('#vcontent img')})""")
            print("VIEWER AFTER OPEN: %s" % view)
            assert view["open"] is True and view["title"] == "pic.png", view
            assert view["hasImg"] is True, view
            pg.evaluate("() => document.querySelector('#vclose').click()")
            pg.wait_for_timeout(400)
            # (c) DISCARDED download -> stays DOWNLOAD.
            _click_row_btn(pg, "notes.txt")
            pg.wait_for_selector("#cfdlg.open", timeout=10000)
            pg.click("#cfno")
            pg.wait_for_timeout(1200)
            b1b = _row_btn(pg, "notes.txt")
            print("ROW AFTER DISCARD notes=%s" % b1b)
            assert b1b == {"title": "Download", "isDl": True, "isOpen": False}, b1b
            dlstate = json.loads(pg.evaluate(
                "() => localStorage.getItem('dropit_dl')"))
            assert "notes.txt" not in dlstate, dlstate
            assert "pic.png" in dlstate, dlstate
            pg.screenshot(path=os.path.join(PROOF, "r45_dl_after_discard.png"))
        finally:
            browser.close()
    finally:
        pw.stop()


def test_live_pc_app_row_stays_open(desktop_server):
    """Desktop (pywebview bridge present): the row button is
    still Open from the first paint and taps the bridge --
    the web Download -> Open change must not touch it."""
    client, base, port, srv, exe = desktop_server
    assert exe, "no headless-shell executable found under real HOME"
    client.j("POST", "/api/setlink", {"name": "r45desk"})
    _make_fixtures(os.path.join(str(base), "r45desk"))
    pw = _playwright()
    try:
        browser = pw.chromium.launch(
            executable_path=exe, args=["--no-proxy-server"])
        pg = browser.new_page(viewport={"width": 1280, "height": 800})
        # Fake the pywebview bridge before the page loads.
        # (A bare script, not a function expression -- an
        # uncalled "() => {...}" would never run.)
        pg.add_init_script(
            "window.pywebview = {api: {open_file: "
            "(n) => { window.__opened = n; return Promise.resolve(true); }}};")
        pg.goto("http://127.0.0.1:%d/" % port)
        pg.wait_for_timeout(1800)
        try:
            pg.wait_for_selector("#files .frow", timeout=10000)
            b = _row_btn(pg, "pic.png")
            print("PC ROW: %s" % b)
            assert b == {"title": "Open", "isDl": False, "isOpen": True}, b
            _click_row_btn(pg, "pic.png")
            pg.wait_for_timeout(800)
            opened = pg.evaluate("() => window.__opened")
            print("PC BRIDGE open_file called with: %r" % opened)
            assert opened == "pic.png", opened
            # No download dialog on the PC path.
            assert pg.evaluate(
                "() => !document.querySelector('#cfdlg.open')") is True
            pg.screenshot(path=os.path.join(
                PROOF, "r45_pc_row_open.png"))
        finally:
            browser.close()
    finally:
        pw.stop()
