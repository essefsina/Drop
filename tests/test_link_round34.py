"""v2.8.18 fix round (Essef Nov 5) -- web/desktop only.

(1) Address dropdown INSIDE the address/link box, like the APK:
    chevron inside the field; the separate "Previously used
    addresses" card below the box is gone.
(2) Web Upload tab must NOT scroll -- except when a failed-file
    retry button is present, or the Send Text box is focused
    (keyboard open). The Send column clips otherwise.
(3) No device connected -> the exact message "No devices
    connected to this address" (pill + devices dropdown empty
    rows), never "No Devices Connected" or any variant.
(4) Web login screen fits without scrolling.
(5) Open-address GREEN note under the password field on the web
    login: "No password set for this address, click Connect."
(6) Web login matches the APK login layout: logo large on top,
    "Drop" below it, slogan, Address label + field centred,
    Password label + field centred, green open-address note,
    Connect, "Disconnected — ..." line, then the Saved button,
    theme toggle below the card. Saved button is GREEN with a
    CLASSIC phone icon (not the mobile-phone emoji).
(7) "Saved on this device" back arrow is a CLASSIC CURVED arrow,
    centred with the "Back" text, fitted, not wide.
(8) "Your address" shows in the web menu (read-only row, visible
    to host AND guest; Set Up controls stay host-only).
(11) "Show in folder" on the PC: bridge path end-to-end -- the
    click is traced (window.__revealTrace), no step fails
    silently any more, Api.reveal_file records last_reveal and
    logs failures; the Explorer call stays the two-item list.
"""
import ast
import json
import os
import re
import socket
import subprocess
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
from test_link_round2 import server, _raw  # noqa: F401,E402
from test_link_round3 import _flip_role  # noqa: E402
from test_link_folders import Client  # noqa: E402

PAGE = D.PAGE
SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py"),
           encoding="utf-8").read()

NO_DEV = "No devices connected to this address"
OPEN_NOTE = "No password set for this address, click Connect."
DISC_LINE = "Disconnected — enter the address and password to connect again"


def _css_rule(page, selector):
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", page)
    assert m, selector + " rule missing"
    return m.group(1)


def test_version_is_2_8_18():
    assert D.VERSION == "2.8.18"


def test_interpreted_page_valid_js_no_surrogates():
    # PAGE is a non-raw Python string: check the INTERPRETED page.
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
        with open("/tmp/r34_script_%d.js" % i, "w",
                  encoding="utf-8") as fh:
            fh.write(js)
        out = subprocess.run(["node", "--check",
                              "/tmp/r34_script_%d.js" % i],
                             capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr


# ---- (1) dropdown inside the address box ------------------------------

def test_1_dropdown_inside_address_box():
    assert 'id="mddtoggle"' in PAGE
    assert 'id="mddlist"' in PAGE
    assert 'id="mddchev"' in PAGE
    # The toggle + list live INSIDE .maddrwrap (the address box),
    # after the input and before the wrapper closes.
    i = PAGE.index('class="maddrwrap"')
    j = PAGE.index("</div>", PAGE.index('id="mddlist"'))
    seg = PAGE[i:j]
    assert 'id="mpchost"' in seg
    assert 'id="mddtoggle"' in seg
    assert 'id="mddlist"' in seg
    assert 'id="mcopy"' in seg
    # The separate card is gone: no wrapper, no long label
    # button. (The phrase survives in a CSS comment only.)
    assert 'class="mddwrap"' not in PAGE
    assert "Previously used addresses <span" not in PAGE
    # Chevron is positioned inside the field; the input leaves
    # room for chevron + copy button.
    rule = _css_rule(PAGE, ".maddrwrap .mddtoggle")
    assert "position:absolute" in rule
    assert "right:38px" in rule
    assert ".mqrrow .maddrwrap .mtext" in PAGE
    assert "padding-right:68px" in PAGE
    # The outside-click closer now guards .maddrwrap, not the
    # deleted .mddwrap.
    assert 'closest(".maddrwrap")' in PAGE
    assert 'closest(".mddwrap")' not in PAGE
    # The (k) history painter + real connect flow are untouched.
    assert "function paintMobileAddressHistory()" in PAGE
    assert "/api/linkhistory" in PAGE
    # The sessionless auto-connect also remembers the use, so a
    # guest who only ever auto-connected still has history.
    assert "bumpAddressUse(st.address_name)" in PAGE


# ---- (2) Upload tab must not scroll ------------------------------------

def test_2_upload_tab_no_scroll_rules():
    assert ('body[data-mtab="send"] .col[data-col="send"] .colbody'
            ' { overflow:hidden; }') in PAGE
    assert ('body.send-may-scroll[data-mtab="send"]'
            ' .col[data-col="send"] .colbody { overflow-y:auto; }') in PAGE
    assert "function fitSendTab()" in PAGE
    assert 'document.querySelector("#msendtext")' in PAGE
    assert 'addEventListener("focus", fitSendTab)' in PAGE
    assert 'addEventListener("blur", fitSendTab)' in PAGE
    # The two allowed scroll cases are the only ones named.
    seg = PAGE[PAGE.index("function fitSendTab()"):
               PAGE.index("function fitSendTab()") + 600]
    assert "[data-retry]" in seg
    assert ".upretry" in seg


# ---- (3) exact no-devices message --------------------------------------

def test_3_exact_no_devices_message():
    assert NO_DEV in PAGE
    assert PAGE.count(NO_DEV) >= 7  # pill markup + 6 JS spots
    assert "No Devices Connected" not in PAGE
    assert "that's not the PC's address" not in PAGE


# ---- (4)+(6) login fits, APK-style layout ------------------------------

def test_4_6_login_layout_apk_style():
    # Tighter login chrome so it fits without scrolling.
    rule = _css_rule(PAGE, ".guestlogin")
    assert "padding:12px 12px 16px" in rule
    assert "flex-direction:column" in rule
    # Logo LARGE on top, "Drop" below it (separate line).
    assert '<span class="gdrop">Drop</span>' in PAGE
    assert "height:64px" in _css_rule(PAGE, ".glogo img")
    assert "flex-direction:column" in _css_rule(PAGE, ".glogo")
    # Order: logo, slogan, Address, Password, note, Connect,
    # disconnected line, Saved, theme toggle below the card.
    # (id=/class= prefixes: bare names also match CSS/JS.)
    order = ['class="glogo"', 'class="gslogan"', 'id="gloginlink"',
             'id="gloginpw"', 'id="gloginpwstate"', 'id="gloginbtn"',
             'id="gloginmsg"', 'id="gsavedbtn"', 'id="themeswLogin"']
    idx = [PAGE.index(x) for x in order]
    assert idx == sorted(idx), list(zip(order, idx))
    # Labels centred.
    assert "text-align:center" in _css_rule(PAGE, ".gloginbox .lklabel")
    # Disconnected line is the login message's default text.
    assert DISC_LINE in PAGE
    # Theme toggle below the card (inside .guestlogin, after the
    # login box closes).
    assert 'id="themeswLogin"' in PAGE
    assert "themeswLogin" in PAGE
    assert 'const themeswLogin = $("#themeswLogin");' in PAGE
    # Saved button: GREEN, classic phone icon, no emoji.
    rule = _css_rule(PAGE, ".gloginbox #gsavedbtn")
    assert "background:#22c55e" in rule
    assert "color:#ffffff" in rule
    assert "border:none" in rule
    i = PAGE.index('id="gsavedbtn"')
    seg = PAGE[i:i + 400]
    assert "<svg" in seg
    assert '<rect x="7" y="2" width="10" height="20"' in seg
    assert "&#128241;" not in PAGE
    # The only green button fill on the page is the Saved button
    # (the other #22c55e background is the permission checkbox
    # check state, not a button).
    assert PAGE.count("background:#22c55e") == 2
    assert ".permchk input:checked + .permbox" in PAGE


# ---- (5) green open-address note ---------------------------------------

def test_5_green_open_address_note():
    seg = PAGE[PAGE.index("async function checkOpenAddress(name){"):
               PAGE.index("async function checkOpenAddress(name){") + 1400]
    assert ('note.textContent = "%s";' % OPEN_NOTE) in seg
    rule = _css_rule(PAGE, ".gloginpwstate")
    assert "color:#22c55e" in rule
    assert "font-weight:600" in rule
    # The note sits under the password field in the markup.
    assert PAGE.index('id="gloginpw"') < PAGE.index('id="gloginpwstate"') \
        < PAGE.index('id="gloginbtn"')


# ---- (7) curved back arrow ---------------------------------------------

def test_7_curved_back_arrow():
    assert "&larr; Back" not in PAGE
    i = PAGE.index('id="gsavedback"')
    seg = PAGE[i:i + 500]
    assert "<svg" in seg
    # Classic curved (undo-style) arrow.
    assert "M9 14 4 9l5-5" in seg
    assert "M4 9h10.5a5.5 5.5 0 0 1 0 11H11" in seg
    assert "> Back</button>" in seg
    rule = _css_rule(PAGE, ".gsavedhead .btn")
    assert "display:inline-flex" in rule
    assert "align-items:center" in rule
    assert "width:auto" in rule
    assert ".gsavedhead .btn svg" in PAGE


# ---- (8) "Your address" in the web menu --------------------------------

def test_8_your_address_in_menu():
    assert 'id="sbaddrcard"' in PAGE
    assert "Your address" in PAGE
    i = PAGE.index('id="sbaddrcard"')
    seg = PAGE[i:i + 200]
    assert 'id="sbaddr"' in seg
    # Painted for host AND guest: both painters set it, and the
    # card is NOT in the host-only hide list.
    assert 'const _sa = $("#sbaddr");' in PAGE
    assert 'const sa = $("#sbaddr");' in PAGE
    hide = PAGE[PAGE.index('["#sbsetupcard"'):
                PAGE.index('["#sbsetupcard"') + 200]
    assert "#sbsetupcard" in hide and "#sbaddrcard" not in hide


# ---- guest Set Up removal still holds ----------------------------------

def test_guest_setup_still_hidden():
    assert ".lkbox.guestcard h3," in PAGE
    assert "display:none !important" in PAGE
    assert '"#sbsetupcard", "#sbsepcard", "#sbfoldercard"' in PAGE


# ---- (11) reveal: trace, loud failure, bridge record -------------------

def test_11_reveal_trace_and_loud_failure():
    assert "window.__revealTrace = [];" in PAGE
    assert "function revealFile(name)" in PAGE
    seg = PAGE[PAGE.index("async function revealFile(name){"):
               PAGE.index("async function revealFile(name){") + 3200]
    assert '_rt("click"' in seg
    assert '_rt("bridge"' in seg
    assert '_rt("fallback-api"' in seg
    assert '_rt("fallback-folder"' in seg
    # A failed folder fallback is reported, never swallowed.
    assert "Opened the folder — the file could not be highlighted" in seg
    assert 'if(opened){ toast(' in seg
    # app.py: last_reveal record + failure logging, list form kept.
    with open(os.path.join(os.path.dirname(__file__), "..",
                           "app.py")) as fh:
        app_src = fh.read()
    assert "self.last_reveal" in app_src
    assert 'argv = ["explorer", "/select," + path]' in app_src
    assert "subprocess.Popen(argv)" in app_src
    assert 'subprocess.Popen(["explorer", "/select," + target])' in SRC
    assert 'Popen("explorer /select,' not in app_src
    assert 'Popen("explorer /select,' not in SRC


def test_11_list2cmdline_proof():
    from subprocess import list2cmdline
    path = r"C:\Users\Essef\Drop\photo test.txt"
    new = list2cmdline(["explorer", "/select," + path])
    assert new == 'explorer "/select,' + path + '"'
    assert list2cmdline(["explorer", r"/select,C:\plain\photo.txt"]) == \
        r"explorer /select,C:\plain\photo.txt"


def test_11_bridge_reveal_records_last_reveal(monkeypatch, tmp_path):
    """Api.reveal_file on win32 passes the two-item list to Popen
    AND records it on last_reveal; a missing file records the
    failure instead of dying silently."""
    import app as appmod
    captured = {}

    def fake_popen(args, **kw):
        captured["args"] = args
        return None

    monkeypatch.setattr(appmod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(sys, "platform", "win32")
    (tmp_path / "photo-test.txt").write_text("hello")
    api = appmod.Api(type("S", (), {"directory": str(tmp_path)})())
    monkeypatch.setattr(api, "_link_dir", lambda: str(tmp_path))
    assert api.reveal_file("photo-test.txt") is True
    expect = os.path.abspath(os.path.join(str(tmp_path), "photo-test.txt"))
    assert captured["args"] == ["explorer", "/select," + expect]
    assert api.last_reveal["ok"] is True
    assert api.last_reveal["argv"] == ["explorer", "/select," + expect]
    assert api.last_reveal["path"] == expect
    captured.clear()
    assert api.reveal_file("nope.txt") is False
    assert "args" not in captured
    assert api.last_reveal["ok"] is False
    assert "file not found" in api.last_reveal["error"]


# ---- live probes --------------------------------------------------------

AC_SPY = """
window.__clip = null;
(function(){
  if(navigator.clipboard && navigator.clipboard.writeText){
    const _w = navigator.clipboard.writeText.bind(navigator.clipboard);
    navigator.clipboard.writeText = (t) => { window.__clip = t; return _w(t).catch(()=>{}); };
  }
})();
"""

BRIDGE_STUB = """
window.__revealed = null;
window.pywebview = { api: {
  reveal_file: async (n) => { window.__revealed = n; return true; },
  open_file: async (n) => true,
  open_folder: async () => true,
  host_token: async () => ""
} };
"""


class _Fwd:
    """127.0.0.3:<port> -> 127.0.0.1:<target>, source 127.0.0.2,
    so the server sees a non-loopback (guest) source IP."""

    def __init__(self, target_port):
        self.target_port = target_port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.3", 0))
        self.sock.listen(50)
        self.port = self.sock.getsockname()[1]
        self.stop = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while not self.stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._pump, args=(conn,), daemon=True).start()

    def _pump(self, conn):
        up = None
        try:
            up = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            up.bind(("127.0.0.2", 0))
            up.connect(("127.0.0.1", self.target_port))
            up.settimeout(30)
            conn.settimeout(30)

            def copy(src, dst):
                try:
                    while True:
                        b = src.recv(65536)
                        if not b:
                            break
                        dst.sendall(b)
                except OSError:
                    pass
                finally:
                    try:
                        dst.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass

            t1 = threading.Thread(target=copy, args=(conn, up), daemon=True)
            t2 = threading.Thread(target=copy, args=(up, conn), daemon=True)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        except OSError:
            pass
        finally:
            for s in (conn, up):
                if s:
                    try:
                        s.close()
                    except OSError:
                        pass

    def close(self):
        self.stop.set()
        try:
            self.sock.close()
        except OSError:
            pass


def _pw():
    from playwright.sync_api import sync_playwright
    return sync_playwright().start()


def test_live_login_apk_style_390(server):
    """(4)(5)(6)(7) live on a 390px guest login page."""
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "probeaddr"})
    fwd = _Fwd(port)
    guest_url = "http://127.0.0.3:%d/" % fwd.port
    pw = _pw()
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    try:
        ctx = browser.new_context(viewport={"width": 390, "height": 844},
                                  permissions=["clipboard-read",
                                               "clipboard-write"])
        pg = ctx.new_page()
        pg.goto(guest_url)
        # An open address auto-connects a fresh guest (sessionless
        # open), so the login page is reached via Disconnect --
        # the same way a user returns to it.
        pg.wait_for_function(
            "() => !document.querySelector('#guestlogin').classList.contains('open')",
            timeout=10000)
        pg.wait_for_timeout(800)
        pg.click("#mpcdisconnect")
        pg.wait_for_function(
            "document.querySelector('#guestlogin').classList.contains('open')",
            timeout=10000)
        pg.wait_for_timeout(1000)
        # (4) the login page fits without scrolling.
        m = pg.evaluate("() => ({docSH: document.documentElement.scrollHeight,"
                        " bodySH: document.body.scrollHeight,"
                        " ih: window.innerHeight})")
        assert m["docSH"] <= m["ih"], m
        assert m["bodySH"] <= m["ih"], m
        # (6) APK-style order, measured, not just in source.
        m = pg.evaluate("""() => {
          const y = s => { const el = document.querySelector(s);
                           return el ? el.getBoundingClientRect().top : -1; };
          const cx = s => { const el = document.querySelector(s);
                            const r = el.getBoundingClientRect();
                            return r.x + r.width / 2; };
          return { logo: y('.glogo img'), drop: y('.glogo .gdrop'),
                   slogan: y('.gslogan'), addr: y('#gloginlink'),
                   pw: y('#gloginpw'), note: y('#gloginpwstate'),
                   connect: y('#gloginbtn'), msg: y('#gloginmsg'),
                   saved: y('#gsavedbtn'), theme: y('#themeswLogin'),
                   addrCX: cx('#gloginlink'), pwCX: cx('#gloginpw'),
                   vpCX: window.innerWidth / 2 };
        }""")
        assert 0 < m["logo"] < m["drop"] < m["slogan"] < m["addr"] < m["pw"], m
        assert m["pw"] < m["connect"] < m["msg"] < m["saved"] < m["theme"], m
        assert abs(m["addrCX"] - m["vpCX"]) <= 1, m
        assert abs(m["pwCX"] - m["vpCX"]) <= 1, m
        # (6) the disconnected line + green Saved button + classic icon.
        assert pg.inner_text("#gloginmsg") == DISC_LINE
        m = pg.evaluate("""() => {
          const b = document.querySelector('#gsavedbtn');
          const cs = getComputedStyle(b);
          return { bg: cs.backgroundColor, hasSvg: !!b.querySelector('svg'),
                   hasEmoji: b.textContent.includes('\\uD83D') };
        }""")
        assert m["bg"] == "rgb(34, 197, 94)", m
        assert m["hasSvg"] is True and m["hasEmoji"] is False, m
        # Theme toggle below the card actually switches the theme.
        pg.click("#themeswLogin")
        pg.wait_for_timeout(300)
        assert pg.evaluate(
            "() => document.documentElement.classList.contains('light')")
        pg.click("#themeswLogin")
        pg.wait_for_timeout(300)
        assert not pg.evaluate(
            "() => document.documentElement.classList.contains('light')")
        # (5) open address: type it, the green note appears under
        # the password field and the password greys out.
        pg.fill("#gloginlink", "probeaddr")
        pg.wait_for_function(
            "() => document.querySelector('#gloginpwstate').textContent === %s"
            % json.dumps(OPEN_NOTE), timeout=10000)
        m = pg.evaluate("""() => {
          const n = document.querySelector('#gloginpwstate');
          const cs = getComputedStyle(n);
          return { color: cs.color,
                   disabled: document.querySelector('#gloginpw').disabled,
                   noteTop: n.getBoundingClientRect().top,
                   pwBottom: document.querySelector('#gloginpw').getBoundingClientRect().bottom,
                   btnTop: document.querySelector('#gloginbtn').getBoundingClientRect().top };
        }""")
        assert m["color"] == "rgb(34, 197, 94)", m
        assert m["disabled"] is True
        assert m["pwBottom"] <= m["noteTop"] < m["btnTop"], m
        # (7) Saved view: curved back arrow, centred with Back,
        # fitted (narrow), not a wide button.
        pg.evaluate("""async () => {
          localStorage.setItem('dropit_dl',
            JSON.stringify({'hello.txt': {size: 5, ts: 1700000000}}));
          await DBCACHE.put('hello.txt', new Blob(['hello'], {type: 'text/plain'}));
        }""")
        pg.click("#gsavedbtn")
        pg.wait_for_selector(".gsavedrow", timeout=5000)
        m = pg.evaluate("""() => {
          const b = document.querySelector('#gsavedback');
          const r = b.getBoundingClientRect();
          const svg = b.querySelector('svg').getBoundingClientRect();
          return { w: r.width, text: b.textContent.trim(),
                   svgCX: svg.y + svg.height / 2,
                   btnCX: r.y + r.height / 2,
                   svgD: b.querySelector('svg').innerHTML };
        }""")
        assert m["text"] == "Back", m
        assert m["w"] <= 140, m
        assert abs(m["svgCX"] - m["btnCX"]) <= 1.5, m
        assert "M9 14 4 9l5-5" in m["svgD"], m
        assert "M4 9h10.5a5.5 5.5" in m["svgD"], m
        ctx.close()
    finally:
        browser.close()
        pw.stop()
        fwd.close()


def test_live_upload_tab_and_dropdown_390(server):
    """(1)(2)(3)(8) live on a 390px guest Upload tab."""
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "probeaddr"})
    client.upload("photo-test.txt", b"photo test content")
    fwd = _Fwd(port)
    guest_url = "http://127.0.0.3:%d/" % fwd.port
    pw = _pw()
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    try:
        ctx = browser.new_context(viewport={"width": 390, "height": 844},
                                  permissions=["clipboard-read",
                                               "clipboard-write"])
        pg = ctx.new_page()
        pg.goto(guest_url)
        # An open address auto-connects a fresh guest, so the
        # Upload tab is already showing; make the connect
        # explicit once so the address lands in this device's
        # used-address history for the dropdown check below.
        pg.wait_for_function(
            "() => !document.querySelector('#guestlogin').classList.contains('open')",
            timeout=10000)
        pg.wait_for_timeout(800)
        pg.click("#mpcconnect")
        pg.wait_for_timeout(800)
        # (2) the Upload tab fits: no page scroll, no column scroll.
        m = pg.evaluate("""() => {
          const col = document.querySelector('.col[data-col="send"] .colbody');
          return { docSH: document.documentElement.scrollHeight,
                   ih: window.innerHeight,
                   colSH: col.scrollHeight, colCH: col.clientHeight };
        }""")
        assert m["docSH"] <= m["ih"], m
        assert m["colSH"] <= m["colCH"], m
        # (2) keyboard exception: focusing Send Text allows scroll.
        pg.click("#msendtext")
        pg.wait_for_timeout(300)
        assert pg.evaluate(
            "() => document.body.classList.contains('send-may-scroll')")
        pg.evaluate("() => document.querySelector('#msendtext').blur()")
        pg.wait_for_timeout(300)
        assert not pg.evaluate(
            "() => document.body.classList.contains('send-may-scroll')")
        # (1) the dropdown lives INSIDE the address box: the
        # chevron sits inside the input's box, the list is a
        # child of the address wrapper, and no separate card
        # exists anywhere on the page.
        m = pg.evaluate("""() => {
          const inp = document.querySelector('#mpchost').getBoundingClientRect();
          const ch = document.querySelector('#mddtoggle').getBoundingClientRect();
          const list = document.querySelector('#mddlist');
          return { chevInside: ch.left >= inp.left && ch.right <= inp.right
                     && ch.top >= inp.top && ch.bottom <= inp.bottom,
                   listParent: list.parentElement.className,
                   separateCard: !!document.querySelector('.mddwrap') };
        }""")
        assert m["chevInside"] is True, m
        assert "maddrwrap" in m["listParent"], m
        assert m["separateCard"] is False, m
        pg.click("#mddtoggle")
        pg.wait_for_timeout(500)
        assert "probeaddr" in pg.inner_text("#mddlist")
        pg.click("#mddlist .ddopt")
        pg.wait_for_timeout(300)
        assert pg.input_value("#mpchost") == "probeaddr"
        # (8) the menu shows "Your address" for a guest, while
        # the host Set Up card stays hidden.
        pg.click("#menubtn")
        pg.wait_for_timeout(500)
        m = pg.evaluate("""() => {
          const card = document.querySelector('#sbaddrcard');
          const setup = document.querySelector('#sbsetupcard');
          return { addrCard: !!card, addrText: card ? card.innerText : '',
                   sbaddr: document.querySelector('#sbaddr').innerText,
                   setupDisplay: getComputedStyle(setup).display,
                   sidebarOpen: document.querySelector('#sidebar').classList.contains('open') };
        }""")
        assert m["sidebarOpen"] is True, m
        # (.sbsec renders uppercase, like every menu header.)
        assert "your address" in m["addrText"].lower() and "probeaddr" in m["sbaddr"], m
        assert m["setupDisplay"] == "none", m
        ctx.close()
    finally:
        browser.close()
        pw.stop()
        fwd.close()


def test_live_host_desktop_no_devices_and_reveal(server):
    """(3)(8)(11) live on a 1280px host desktop page."""
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "probeaddr"})
    client.upload("photo-test.txt", b"photo test content")
    pw = _pw()
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    try:
        ctx = browser.new_context(viewport={"width": 1280, "height": 800},
                                  permissions=["clipboard-read",
                                               "clipboard-write"])
        ctx.add_init_script(BRIDGE_STUB)
        pg = ctx.new_page()
        pg.goto("http://127.0.0.1:%d/" % port)
        pg.wait_for_timeout(1500)
        # (3) no guests connected: the pill shows the exact message.
        pg.wait_for_function(
            "() => document.querySelector('#statustext').textContent === %s"
            % json.dumps(NO_DEV), timeout=10000)
        assert pg.inner_text("#statustext") == NO_DEV
        # ... and so does the devices dropdown's empty row.
        # (Hover opens it; a click would toggle it shut again.)
        pg.hover("#statusdiv")
        pg.wait_for_function(
            "() => document.querySelector('#devdrop').classList.contains('open')",
            timeout=10000)
        pg.wait_for_function(
            "() => document.querySelector('#devdroprows').innerText.includes(%s)"
            % json.dumps(NO_DEV), timeout=10000)
        assert NO_DEV in pg.inner_text("#devdroprows")
        # (11) the per-file button is "Show in folder" and the
        # click reaches the bridge -- traced, step by step.
        pg.wait_for_selector("[data-dl]", timeout=10000)
        m = pg.evaluate(
            "() => document.querySelector('[data-dl]').getAttribute('title')")
        assert m == "Show in folder", m
        pg.evaluate("() => { window.__revealTrace = []; }")
        pg.click("[data-dl]")
        pg.wait_for_function(
            "() => window.__revealTrace.some(s => s.step === 'bridge')",
            timeout=10000)
        trace = pg.evaluate("() => window.__revealTrace")
        assert trace[0]["step"] == "click" and trace[0]["bridge"] is True
        assert any(s["step"] == "bridge" and s["ok"] is True
                   for s in trace), trace
        assert pg.evaluate("() => window.__revealed") == "photo-test.txt"
        # (8) the menu shows "Your address" for the host too.
        pg.click("#menubtn")
        pg.wait_for_timeout(500)
        m = pg.evaluate("""() => ({
          addr: document.querySelector('#sbaddr').innerText,
          setupDisplay: getComputedStyle(
            document.querySelector('#sbsetupcard')).display })""")
        assert "probeaddr" in m["addr"], m
        assert m["setupDisplay"] != "none", m
        ctx.close()
    finally:
        browser.close()
        pw.stop()
