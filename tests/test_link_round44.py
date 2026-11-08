"""v2.8.29 round (Essef Nov 6, ~4:25-4:32 PM) -- web/desktop only.

Five items, nothing else:
1. REMOVE THE ZOOM OPTIONS: no "- 100% + Fit" controls in the
   preview, on web or the PC app -- no zoom buttons, no
   click-to-zoom, no wheel zoom. Fit view stays (whole picture
   visible, no scrolling); the window stays fixed-size and
   Close / Download stay where they are.
3. COPIED ADDRESS DOESN'T OPEN THE WEB VERSION -- QR DOES: the
   copy buttons copied the .local form
   (http://<name>.local:<port>/), which most phone browsers
   cannot resolve. All three copy buttons (#copy top pill,
   #mcopy address field, #lkcopy Set Up) now copy the SAME
   full working URL the QR encodes (http://<LAN IP>:<port>/,
   AUTH.connect_url from /api/authstate); the displayed
   address stays the .local form. The desktop tray "Copy phone
   link" copies it too. Live check: the copied value is pasted
   into a browser and the Drop page must load.
   SANDBOX NOTE: this VM intercepts ALL non-loopback TCP from
   agent processes (raw socket to the LAN IP returns the
   sandbox guard text, even to a closed port; loopback is
   unguarded), so a literal in-sandbox navigation to the LAN-IP
   URL cannot reach the server -- Chromium gets the guard's
   non-HTTP payload (ERR_INVALID_HTTP_RESPONSE). The test
   therefore proves the live chain that CAN run here and
   records the guard interception explicitly: copied ==
   connect_url == the exact bytes /qr.png encodes, the server
   binds 0.0.0.0 and serves the Drop page on that exact port
   (loopback navigation loads), and the navigation attempt to
   the copied string fails ONLY with the guard payload. The
   final leg -- a real phone on Essef's WiFi opening the
   pasted URL -- still needs a real device.
4. SAVE TEXT CENTRED, ONE SPACE FROM THE FLOPPY (refines the
   earlier "nudge left" item): icon + text are one centred
   unit, with exactly ONE space between floppy and "SAVE".
   Measured live: the " SAVE" text node's leading space is
   trimmed by the flex layout, so the flex gap IS the whole
   icon-to-text distance; gap 8px -> 4px (= one space at the
   15-16px button font). Applies to #lkset, #lockpwsave,
   #msave (no icon on #msave: gap rule shared, text centred).
5. DUPLICATE EYE ICON IN THE PASSWORD BOX: the Set Up
   password field (#lkpw) showed Edge/WebView2's native
   reveal eye INSIDE the box plus the custom #lkpweye toggle
   outside it -- #lkpw never got the ::-ms-reveal hide that
   2.8.9 gave #lockpwin. Now hidden the same way; exactly
   ONE eye toggle remains, the outside one.
8. DESKTOP SHARED FILES DELETE ICON -- BRING IT BACK: the
   2.8.25 text-only revert is superseded; the desktop Delete
   button (#delallbtn, server-rendered when desktop=True)
   shows the trash icon + "Delete" again, as 2.8.5 had it.
   Open / Change untouched.
"""
import ast
import os
import re
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

PAGE = D.PAGE
SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py"),
           encoding="utf-8").read()
APP = open(os.path.join(os.path.dirname(__file__), "..", "app.py"),
           encoding="utf-8").read()

PROOF = "/home/hatch/workspace/dropit-proof-round44"
os.makedirs(PROOF, exist_ok=True)

ADDR = "10-0-0-85-8000"  # Essef's actual address form (LAN IP:port dashed)


def test_version_is_2_8_29():
    assert D.VERSION == "2.8.29"


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
        p = os.path.join(PROOF, "r44_script_%d.js" % i)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(js)
        out = subprocess.run(["node", "--check", p],
                             capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr


# ---- (1) no zoom ------------------------------------------------------

def _preview_state(pg):
    return pg.evaluate("""() => {
      const img = document.querySelector('#previewbody img');
      const box = document.querySelector('.previewbox');
      const body = document.querySelector('#previewbody');
      const row = document.querySelector('.pvrow');
      const ir = img ? img.getBoundingClientRect() : null;
      const br = box ? box.getBoundingClientRect() : null;
      const bdr = body ? body.getBoundingClientRect() : null;
      return {open: document.querySelector('#previewpop').classList.contains('open'),
        zoomEls: ['#pvzoom','#pvzin','#pvzout','#pvzfit','#pvzval'].map(s => !!document.querySelector(s)),
        pvZoomApi: typeof window.__pvZoom,
        rowText: row ? row.innerText : null,
        img: ir ? {w: Math.round(ir.width), h: Math.round(ir.height)} : null,
        box: br ? {w: Math.round(br.width), h: Math.round(br.height)} : null,
        imgFits: !!(ir && bdr && ir.top >= bdr.top - 1 && ir.bottom <= bdr.bottom + 1),
        bodyScroll: body ? (body.scrollHeight > body.clientHeight + 1 || body.scrollWidth > body.clientWidth + 1) : null,
        closeVisible: (() => { const b = document.querySelector('#previewclose2'); if(!b) return false; const r = b.getBoundingClientRect(); return r.width > 0; })(),
        dlVisible: (() => { const b = document.querySelector('#previewdl'); if(!b) return false; const r = b.getBoundingClientRect(); return r.width > 0; })()};
    }""")


def test_live_preview_has_no_zoom(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": ADDR})
    _make_fixtures(os.path.join(str(base), ADDR))
    # Static: no zoom markup / API / behaviour left in the page.
    for dead in ('id="pvzoom"', 'id="pvzin"', 'id="pvzout"',
                 'id="pvzfit"', 'id="pvzval"', "window.__pvZoom",
                 "cursor:zoom-in", "cursor:zoom-out"):
        assert dead not in PAGE, dead
    assert "pvzoom" not in PAGE or PAGE.count("pvzoom") == 1  # only the removal note
    pw = _playwright()
    try:
        for light in (False, True):
            browser, pg = _host_page(pw, port, 1280, 800, light=light)
            try:
                _open_preview(pg, "pic.png")
                m0 = _preview_state(pg)
                print("PREVIEW %s: %s" % ("light" if light else "dark", m0))
                assert m0["open"] is True, m0
                assert m0["zoomEls"] == [False] * 5, m0
                assert m0["pvZoomApi"] == "undefined", m0
                assert "100%" not in (m0["rowText"] or ""), m0
                assert "Fit" not in (m0["rowText"] or ""), m0
                # Fit view kept: whole picture visible, no scroll.
                assert m0["imgFits"] is True, m0
                assert m0["bodyScroll"] is False, m0
                assert m0["closeVisible"] and m0["dlVisible"], m0
                # Click the picture: no zoom.
                pg.evaluate("() => document.querySelector('#previewbody img').click()")
                pg.wait_for_timeout(300)
                # Wheel over the picture: no zoom.
                box = pg.evaluate("() => { const r = document.querySelector('#previewbody img').getBoundingClientRect(); return {x: r.left + r.width/2, y: r.top + r.height/2}; }")
                pg.mouse.move(box["x"], box["y"])
                pg.mouse.wheel(0, -480)
                pg.wait_for_timeout(300)
                pg.mouse.wheel(0, 480)
                pg.wait_for_timeout(300)
                m1 = _preview_state(pg)
                print("PREVIEW after click+wheel %s: %s" % ("light" if light else "dark", m1))
                assert m1["img"] == m0["img"], (m0, m1)
                assert m1["box"] == m0["box"], (m0, m1)
                assert m1["zoomEls"] == [False] * 5, m1
                if not light:
                    pg.screenshot(path=os.path.join(
                        PROOF, "r44_preview_nozoom_1280.png"))
                else:
                    pg.screenshot(path=os.path.join(
                        PROOF, "r44_preview_nozoom_light.png"))
            finally:
                browser.close()
    finally:
        pw.stop()


# ---- (3) copied address opens the web version -------------------------

def _clip_hook(pg):
    pg.evaluate("""() => {
      window.__clip = null;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        const _w = navigator.clipboard.writeText.bind(navigator.clipboard);
        navigator.clipboard.writeText = (t) => { window.__clip = t; return _w(t).catch(()=>{}); };
      }
    }""")


def test_live_copy_is_qr_url_and_loads(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": ADDR})
    _make_fixtures(os.path.join(str(base), ADDR))
    lan = D.lan_ip()
    expected = "http://%s:%d/" % (lan, port)
    # Server side: authstate carries the QR URL, and /qr.png
    # encodes exactly it.
    st, auth = client.j("GET", "/api/authstate")
    assert st == 200, auth
    print("AUTHSTATE url=%r connect_url=%r" % (auth.get("url"),
                                               auth.get("connect_url")))
    assert auth.get("connect_url") == expected, auth
    assert auth.get("url") == "http://%s.local:%d" % (ADDR, port), auth
    # NOTE: /qr.png bytes are checked in
    # test_qr_png_encodes_copied_url below (in-process server):
    # the subprocess fixture's tmp HOME hides user
    # site-packages, so its qrcode import fails (HAS_QR False)
    # and /qr.png 404s there -- a pre-existing sandbox
    # artifact, not a 2.8.29 change (round26's qr test fails
    # the same way on pristine 2.8.28).
    # Static: the tray copies the QR URL too, not a bare name.
    assert "dropit._qr_connect_url(server)" in APP, APP
    assert 'copy_text(name or server.link_name)' not in APP

    pw = _playwright()
    try:
        browser, pg = _host_page(pw, port, 1280, 800)
        try:
            _clip_hook(pg)
            pg.wait_for_timeout(400)
            # Top pill copy.
            pg.click("#copy")
            pg.wait_for_timeout(400)
            top_copy = pg.evaluate("() => window.__clip")
            print("COPY #copy -> %r (want %r)" % (top_copy, expected))
            assert top_copy == expected, top_copy
            # Set Up copy.
            pg.click("#toplink")
            pg.wait_for_timeout(800)
            pg.evaluate("() => { window.__clip = null; }")
            pg.evaluate("() => document.querySelector('#lkcopy').click()")
            pg.wait_for_timeout(400)
            setup_copy = pg.evaluate("() => window.__clip")
            print("COPY #lkcopy -> %r" % setup_copy)
            assert setup_copy == expected, setup_copy
            # Address-field copy.
            pg.evaluate("() => { window.__clip = null; }")
            pg.evaluate("() => document.querySelector('#mcopy').click()")
            pg.wait_for_timeout(400)
            m_copy = pg.evaluate("() => window.__clip")
            print("COPY #mcopy -> %r" % m_copy)
            assert m_copy == expected, m_copy
            # Displayed address is STILL the .local form.
            disp = pg.evaluate("""() => ({
              href: document.querySelector('#toplink').href,
              text: document.querySelector('#toplink').textContent})""")
            print("DISPLAY toplink: %s" % disp)
            assert disp["href"] == "http://%s.local:%d/" % (ADDR, port), disp
            assert ADDR in disp["text"], disp

            # LIVE CHECK 1 -- control: the server serves the Drop
            # page on this exact port (loopback navigation loads).
            pg2 = browser.new_page(viewport={"width": 1280, "height": 800})
            try:
                pg2.goto("http://127.0.0.1:%d/" % port, timeout=10000)
                pg2.wait_for_timeout(1500)
                assert pg2.evaluate(
                    "() => !!document.querySelector('#toplink')"), "no toplink on loopback load"
                print("NAV loopback -> Drop page loaded")
            finally:
                pg2.close()
            # LIVE CHECK 2 -- paste the copied value into a
            # browser address bar. In this sandbox the VM
            # intercepts non-loopback TCP (see module docstring),
            # so record exactly what happens instead of
            # pretending the load worked.
            pg3 = browser.new_page(viewport={"width": 1280, "height": 800})
            try:
                try:
                    pg3.goto(top_copy, timeout=10000)
                    pg3.wait_for_timeout(1500)
                    loaded = pg3.evaluate(
                        "() => !!document.querySelector('#toplink')")
                    print("NAV copied %r -> loaded=%s title=%r"
                          % (top_copy, loaded, pg3.title()))
                    assert loaded is True, "copied URL did not load Drop"
                    pg3.screenshot(path=os.path.join(
                        PROOF, "r44_copied_loads.png"))
                except Exception as e:  # noqa: BLE001 - sandbox guard
                    # Prove the failure is the sandbox guard, not
                    # the URL or the server: a raw socket to the
                    # copied host:port returns the guard text,
                    # while loopback (LIVE CHECK 1) loads fine.
                    import socket as _s
                    try:
                        s = _s.create_connection((lan, port), timeout=5)
                        s.sendall(b"GET / HTTP/1.0\r\n\r\n")
                        payload = s.recv(120)
                        s.close()
                    except Exception as e2:  # noqa: BLE001
                        payload = ("socket error: %s" % e2).encode()
                    print("NAV copied %r -> blocked in sandbox: %s | raw payload: %r"
                          % (top_copy, e, payload[:100]))
                    assert b"Other TCP connections is turned off" in payload, payload
                    print("SANDBOX-GUARD confirmed: navigation to the "
                          "LAN-IP URL is intercepted before reaching "
                          "the server; real-LAN check still needs a "
                          "real device (see report).")
            finally:
                pg3.close()
            # Negative control: the OLD .local value still fails.
            pg4 = browser.new_page(viewport={"width": 1280, "height": 800})
            try:
                old = "http://%s.local:%d/" % (ADDR, port)
                try:
                    pg4.goto(old, timeout=8000)
                    pg4.wait_for_timeout(1000)
                    old_loaded = pg4.evaluate(
                        "() => !!document.querySelector('#toplink')")
                except Exception:  # noqa: BLE001
                    old_loaded = False
                print("NAV old .local %r -> loaded=%s" % (old, old_loaded))
                assert old_loaded is False, old
            finally:
                pg4.close()
        finally:
            browser.close()
    finally:
        pw.stop()


# ---- (3b) /qr.png encodes exactly the copied URL ----------------------
# In-process server: its qrcode import already happened under the
# real HOME, so /qr.png works here (see the note in the test above).

def test_qr_png_encodes_copied_url(desktop_server):
    client, base, port, srv, exe = desktop_server
    assert D.HAS_QR, "qrcode/Pillow missing in this process"
    lan = D.lan_ip()
    expected = "http://%s:%d/" % (lan, port)
    client.j("POST", "/api/setlink", {"name": ADDR})
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/qr.png")
    resp = conn.getresponse()
    qr_bytes = resp.read()
    headers = {k: v for k, v in resp.getheaders()}
    conn.close()
    print("QR /qr.png -> %s, %d bytes, cache=%r"
          % (resp.status, len(qr_bytes), headers.get("Cache-Control")))
    assert resp.status == 200 and qr_bytes, resp.status
    assert qr_bytes[:8] == b"\x89PNG\r\n\x1a\n", qr_bytes[:8]
    assert headers.get("Cache-Control") == "no-store", headers
    assert qr_bytes == D.qr_png(expected), (
        "QR bytes differ from qr_png(copied URL): %d vs %d"
        % (len(qr_bytes), len(D.qr_png(expected))))
    assert qr_bytes != D.qr_png("http://qrtest.local:%d/" % port)
    print("QR encodes exactly the copied URL: %r" % expected)


# ---- (4) SAVE: one space, centred --------------------------------------

def _save_gap(pg, sel):
    return pg.evaluate("""(sel) => {
      const cv = document.createElement('canvas').getContext('2d');
      const b = document.querySelector(sel); if (!b) return null;
      const cs = getComputedStyle(b);
      cv.font = cs.fontStyle + ' ' + cs.fontWeight + ' ' + cs.fontSize + ' ' + cs.fontFamily;
      const spaceW = cv.measureText(' ').width;
      const svg = b.querySelector('svg');
      const br = b.getBoundingClientRect();
      if (!svg) {
        const tr = b.getBoundingClientRect();
        const range = document.createRange();
        range.selectNodeContents(b);
        const rr = range.getBoundingClientRect();
        return {sel, hasIcon: false, gapCss: cs.gap, spaceW: +spaceW.toFixed(2),
                unitOff: +(((rr.left + rr.right)/2) - (br.left + br.width/2)).toFixed(2),
                textDy: +((rr.top + rr.height/2) - (br.top + br.height/2)).toFixed(2),
                text: b.textContent.trim()};
      }
      const tn = [...b.childNodes].find(n => n.nodeType === 3 && n.textContent.trim());
      const sr = svg.getBoundingClientRect();
      const range = document.createRange();
      range.setStart(tn, 1); range.setEnd(tn, tn.textContent.length);
      const tr = range.getBoundingClientRect();
      return {sel, hasIcon: true, gap: +(tr.left - sr.right).toFixed(2),
              spaceW: +spaceW.toFixed(2), gapCss: cs.gap,
              unitOff: +(((sr.left + tr.right)/2) - (br.left + br.width/2)).toFixed(2),
              textDy: +((tr.top + tr.height/2) - (br.top + br.height/2)).toFixed(2),
              text: JSON.stringify(tn.textContent)};
    }""", sel)


def test_live_save_one_space_centred(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": ADDR})
    _make_fixtures(os.path.join(str(base), ADDR))
    pw = _playwright()
    try:
        browser, pg = _host_page(pw, port, 1280, 800)
        try:
            # Set Up SAVE (#lkset) -- openLinkWin rewrites its
            # label to " SAVE" on open; the spacing must survive.
            pg.click("#toplink")
            pg.wait_for_timeout(800)
            m = _save_gap(pg, "#lkset")
            print("SAVE #lkset: %s" % m)
            assert m["hasIcon"] is True, m
            assert m["gapCss"] == "4px", m
            assert abs(m["gap"] - m["spaceW"]) <= 1.5, m  # one space
            assert 2.5 <= m["gap"] < 8, m  # clear gap, closer than 2.8.28
            assert abs(m["unitOff"]) <= 2, m  # icon+text centred
            assert abs(m["textDy"]) <= 2, m  # text vertically centred
            assert m["text"] == '" SAVE"', m
            pg.screenshot(path=os.path.join(PROOF, "r44_save_setup.png"))
            # Set Password SAVE (#lockpwsave).
            pg.evaluate("() => openLockPopup()")
            pg.wait_for_timeout(600)
            m2 = _save_gap(pg, "#lockpwsave")
            print("SAVE #lockpwsave: %s" % m2)
            assert m2["hasIcon"] is True, m2
            assert m2["gapCss"] == "4px", m2
            assert abs(m2["gap"] - m2["spaceW"]) <= 1.5, m2
            assert 2.5 <= m2["gap"] < 8, m2
            assert abs(m2["unitOff"]) <= 2, m2
            assert abs(m2["textDy"]) <= 2, m2
            pg.screenshot(path=os.path.join(PROOF, "r44_save_lockpw.png"))
            pg.evaluate("() => closeLockPopup()")
            pg.wait_for_timeout(300)
            # Note SAVE (#msave) -- no floppy icon; its text must
            # still be centred, and the shared gap rule is 4px.
            pg.evaluate("() => document.querySelector('#maddnote').click()")
            pg.wait_for_timeout(600)
            m3 = _save_gap(pg, "#msave")
            print("SAVE #msave: %s" % m3)
            assert m3["hasIcon"] is False, m3
            assert m3["gapCss"] == "4px", m3
            assert abs(m3["unitOff"]) <= 2, m3
            assert abs(m3["textDy"]) <= 2, m3
            pg.screenshot(path=os.path.join(PROOF, "r44_save_msave.png"))
        finally:
            browser.close()
    finally:
        pw.stop()


# ---- (5) one eye in the Set Up password box -----------------------------

def test_live_setup_password_single_eye(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": ADDR})
    _make_fixtures(os.path.join(str(base), ADDR))
    # Static: the native Edge/WebView2 reveal eye is hidden for
    # the Set Up field exactly as 2.8.9 hid it for #lockpwin;
    # the guest login field (no outside eye) is untouched.
    norm = re.sub(r"\s+", "", PAGE)
    assert "#lkpw::-ms-reveal{display:none;}" in norm, "lkpw reveal hide missing"
    assert "#lkpw::-ms-clear{display:none;}" in norm, "lkpw clear hide missing"
    assert "#lockpwin::-ms-reveal{display:none;}" in norm
    assert "#gloginpw::-ms-reveal" not in PAGE
    pw = _playwright()
    try:
        browser, pg = _host_page(pw, port, 1280, 800)
        try:
            pg.click("#toplink")
            pg.wait_for_timeout(800)
            m = pg.evaluate("""() => {
              const inp = document.querySelector('#lkpw');
              const row = inp.closest('.lkpwrow');
              const ir = inp.getBoundingClientRect();
              const eye = document.querySelector('#lkpweye').getBoundingClientRect();
              return {buttons: [...row.querySelectorAll('button')].map(b => b.id),
                      field: {left: Math.round(ir.left), right: Math.round(ir.right)},
                      eye: {left: Math.round(eye.left), right: Math.round(eye.right),
                            w: Math.round(eye.width)},
                      eyeInsideField: eye.left >= ir.left && eye.right <= ir.right};
            }""")
            print("SETUP-PW-ROW: %s" % m)
            # Exactly two buttons in the row: eye toggle + delete.
            # The eye is the ONLY eye, and it sits OUTSIDE the field.
            assert m["buttons"] == ["lkpweye", "lkremovepwbtn"], m
            assert m["eyeInsideField"] is False, m
            assert m["eye"]["left"] > m["field"]["right"], m
            assert m["eye"]["w"] > 0, m
            pg.screenshot(path=os.path.join(
                PROOF, "r44_setup_one_eye.png"))
        finally:
            browser.close()
    finally:
        pw.stop()


# ---- (8) desktop Delete icon back ----------------------------------------

@pytest.fixture()
def desktop_server(tmp_path):
    """In-process server with desktop=True (what app.py runs)."""
    import glob
    home = tmp_path / "home"
    base = tmp_path / "base"
    base.mkdir()
    (home / ".config" / "DropIt").mkdir(parents=True)
    port = _free_port()
    old_home = os.environ.get("HOME")
    # Playwright resolves its browser under $HOME/.cache -- the
    # tmp HOME below hides it, so resolve the real executable
    # BEFORE overriding HOME and pass it to the launcher.
    exe = None
    if old_home:
        cands = sorted(glob.glob(os.path.join(
            old_home, ".cache", "ms-playwright",
            "chromium_headless_shell-*",
            "chrome-headless-shell-linux64",
            "chrome-headless-shell")))
        exe = cands[0] if cands else None
    os.environ["HOME"] = str(home)
    try:
        srv = D.make_server(port, str(base), desktop=True)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        client = Client(port)
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
        yield client, base, port, srv, exe
    finally:
        try:
            srv.shutdown()
            srv.server_close()
        except Exception:  # noqa: BLE001
            pass
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home


def _desktop_page(pw, port, exe, width=1280, height=800):
    """_host_page, but with an explicit browser executable (the
    desktop_server fixture's tmp HOME hides Playwright's cache)."""
    browser = pw.chromium.launch(
        executable_path=exe, args=["--no-proxy-server"])
    pg = browser.new_page(viewport={"width": width, "height": height})
    pg.goto("http://127.0.0.1:%d/" % port)
    pg.wait_for_timeout(1800)
    return browser, pg


def test_live_desktop_delete_icon(desktop_server):
    client, base, port, srv, exe = desktop_server
    assert srv.server_address[1] == port
    assert exe, "no headless-shell executable found under real HOME"
    client.j("POST", "/api/setlink", {"name": "r44desk"})
    _make_fixtures(os.path.join(str(base), "r44desk"))
    # Static: the desktop branch renders the trash icon again.
    assert "_SVG_TRASH + ' Delete</button>'" in SRC, "desktop Delete icon missing in source"
    pw = _playwright()
    try:
        browser, pg = _desktop_page(pw, port, exe, 1280, 800)
        try:
            pg.wait_for_selector("#delallbtn:visible", timeout=10000)
            m = pg.evaluate("""() => {
              const d = document.querySelector('#delallbtn');
              const o = document.querySelector('#openfolder');
              const c = document.querySelector('#changefolder');
              const svg = d.querySelector('svg');
              const sr = svg ? svg.getBoundingClientRect() : null;
              const tn = [...d.childNodes].find(n => n.nodeType === 3 && n.textContent.trim());
              let tr = null;
              if (tn) { const r = document.createRange(); r.setStart(tn, 1); r.setEnd(tn, tn.textContent.length); tr = r.getBoundingClientRect(); }
              return {delHasSvg: !!svg,
                      delSvgTrash: svg ? svg.innerHTML.includes('M19 6v14a2 2 0 01-2 2H7') : false,
                      delText: d.textContent.trim(),
                      iconVisible: sr ? sr.width > 0 : false,
                      iconLeftOfText: (sr && tr) ? sr.right <= tr.left : null,
                      openText: o ? o.textContent.trim() : null,
                      openHasSvg: !!(o && o.querySelector('svg')),
                      changeText: c ? c.textContent.trim() : null,
                      changeHasSvg: !!(c && c.querySelector('svg'))};
            }""")
            print("DESKTOP DELETE: %s" % m)
            assert m["delHasSvg"] is True, m
            assert m["delSvgTrash"] is True, m
            assert m["delText"] == "Delete", m
            assert m["iconVisible"] is True, m
            assert m["iconLeftOfText"] is True, m
            # Open / Change untouched.
            assert m["openText"] == "Open" and m["openHasSvg"] is True, m
            assert m["changeText"] == "Change" and m["changeHasSvg"] is True, m
            pg.screenshot(path=os.path.join(
                PROOF, "r44_desktop_delete_icon.png"))
        finally:
            browser.close()
    finally:
        pw.stop()
