"""v2.8.17 fix round (Essef Nov 5 ~4:00 AM PT) -- (a)-(m).

(a) Change Folder icon revert: Files card + menu = pencil,
    Set Up dialog = swap icon, both verified against the 2.8.8
    originals in ~/workspace/dropit-desktop-v2.8.8.zip.
(b) Guest modal wording: "Type the password, then Connect."
(c) Open-in-folder: two-item list ["explorer", "/select," + path]
    in BOTH layers; list2cmdline proof that the old string form
    outer-quotes into one token; bridge reveal in-process.
(d) Disconnect: flag in doLogout, respected by the sessionless
    re-mint block and by checkAuth; live: login page shown,
    session gone, count 0.
(e) Saved on this phone: exactly ONE button (Open) per row;
    viewer close returns to the saved view, never the login.
(f) Copy = full URL (AUTH.url preferred for the current address,
    bare IPs never get .local); classic copy icon, no emoji.
(g) Send Text icons are the chat bubble again, not the upload icon.
(h) Web login page: logo + "Drop" centred, whole card centred.
(i) Web Choose Files / Send Text: identical shape, smaller width.
(j) Upload progress: floating solid-blue ring + pop sound;
    old .up rows / .bar gone.
(k) Web Set Up: dropdown of previously used addresses, real
    connect flow, full-address copy, classic copy icon.
(l) Web Upload: duplicate address gone, page not scrollable at 390px.
(m) Shared Files heading aligned with thumbnails; Saved button
    solid colour, white text.
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
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
from test_link_round2 import server, _raw  # noqa: F401,E402
from test_link_round3 import _flip_role  # noqa: E402
from test_link_folders import Client  # noqa: E402

PAGE = D.PAGE
SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py"),
           encoding="utf-8").read()

PENCIL = "M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"
SWAP = ["M17 2.1 21 6l-4 3.9", "M21 6H8", "M7 21.9 3 18l4-3.9", "M3 18h16"]
BUBBLE = ("M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 "
          "8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 "
          "8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 "
          "0 0 1 8 8v.5z")
UPLOAD_TRAY = "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"
COPY_RECTS = ("<rect x=\"9\" y=\"9\" width=\"13\" height=\"13\" rx=\"2\" ry=\"2\"/>"
              "<path d=\"M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1\"/>")


def _button_svg(page, btn_id):
    i = page.index('id="%s"' % btn_id)
    j = page.index("<svg", i)
    k = page.index("</svg>", j) + len("</svg>")
    return page[j:k]


def _css_rule(page, selector):
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", page)
    assert m, selector + " rule missing"
    return m.group(1)


def _paths_288():
    """The three Change buttons' <path d=...> lists from 2.8.8."""
    zpath = os.path.expanduser("~/workspace/dropit-desktop-v2.8.8.zip")
    if not os.path.isfile(zpath):
        pytest.skip("2.8.8 reference zip not on disk")
    with zipfile.ZipFile(zpath) as z:
        src = z.read("dropit/dropit.py").decode("utf-8")
    out = {}
    for bid in ("changefolder", "sbchange", "lkchangefolder"):
        svg = _button_svg(src, bid)
        out[bid] = re.findall(r'<path d="([^"]+)"', svg)
    return out


def test_version_is_2_8_18():
    # Round34 supersedes the 2.8.17 pin.
    assert D.VERSION == "2.8.18"


# ---- (a) Change Folder icon revert -----------------------------------

def test_a_files_card_and_menu_are_pencil():
    # #changefolder is rendered server-side (outside PAGE), the
    # other two live in PAGE; search the whole file source so all
    # three are found in the markup that actually ships.
    for bid in ("changefolder", "sbchange"):
        svg = _button_svg(SRC, bid)
        assert PENCIL in svg, bid + " is not the pencil icon"
        assert "M17 2.1" not in svg, bid + " still has the swap icon"
        # The folder+arrow icon (2.8.9-2.8.16) must be gone here.
        assert "M22 19a2 2 0 0 1-2 2H4" not in svg


def test_a_setup_dialog_is_swap():
    svg = _button_svg(SRC, "lkchangefolder")
    for p in SWAP:
        assert p in svg, "swap icon path missing: " + p
    assert PENCIL not in svg
    assert "M22 19a2 2 0 0 1-2 2H4" not in svg


def test_a_icons_match_288_originals():
    orig = _paths_288()
    assert orig["changefolder"] == [PENCIL]
    assert orig["sbchange"] == [PENCIL]
    assert orig["lkchangefolder"] == SWAP
    assert re.findall(r'<path d="([^"]+)"', _button_svg(SRC, "changefolder")) == [PENCIL]
    assert re.findall(r'<path d="([^"]+)"', _button_svg(SRC, "sbchange")) == [PENCIL]
    assert re.findall(r'<path d="([^"]+)"', _button_svg(SRC, "lkchangefolder")) == SWAP


def test_a_2814_left_shift_rules_removed():
    # The 2.8.14 compensation for the changed icon's width.
    assert "left:6.7px" not in PAGE
    assert "left:7.8px" not in PAGE


# ---- (b) guest modal wording ------------------------------------------

def test_b_guest_modal_wording():
    assert "Type the password, then Connect." in PAGE
    assert "Save to connect" not in PAGE


# ---- (c) open-in-folder -----------------------------------------------

def test_c_reveal_is_two_item_list_both_layers():
    # app.py bridge layer (round34: the list lives in `argv`,
    # Popen(argv) -- same two-item list, plus last_reveal).
    with open(os.path.join(os.path.dirname(__file__), "..", "app.py")) as fh:
        app_src = fh.read()
    assert 'argv = ["explorer", "/select," + path]' in app_src
    assert "subprocess.Popen(argv)" in app_src
    assert 'Popen("explorer /select,' not in app_src
    # Server /api/reveal layer (server-side code, outside PAGE):
    # the verbatim-string form must be gone. The handler's local
    # is named `target`, the bridge's `path`.
    assert 'subprocess.Popen(["explorer", "/select," + target])' in SRC
    assert 'Popen("explorer /select,' not in SRC
    # No three-item form (the 2.8.11 bug: space after the comma).
    assert '"/select,", path' not in SRC
    assert '"/select,",path' not in SRC
    # JS bridge path invokes the bridge first, /api/reveal as fallback.
    assert "window.pywebview.api.reveal_file" in PAGE
    assert "revealFile" in PAGE


def test_c_list2cmdline_proof():
    from subprocess import list2cmdline
    path = r"C:\Users\Essef\Drop\photo test.txt"
    old = 'explorer /select,"' + path + '"'
    # The 2.8.14 verbatim string: CPython runs
    # list2cmdline([args]) on a str, so the WHOLE command is
    # outer-quoted as ONE token (inner quotes backslash-escaped)
    # -- CreateProcess cannot find the program.
    assert list2cmdline([old]) == '"' + old.replace('"', '\\"') + '"'
    # The 2.8.17 list form: the switch and the path stay ONE
    # argument; it is quoted as a whole only because the path
    # has spaces, which Explorer parses.
    new = list2cmdline(["explorer", "/select," + path])
    assert new.startswith("explorer ")
    assert new == 'explorer "/select,' + path + '"'
    # No spaces: no quoting at all.
    assert list2cmdline(["explorer", r"/select,C:\plain\photo.txt"]) == \
        r"explorer /select,C:\plain\photo.txt"


def test_c_bridge_reveal_calls_explorer_list(monkeypatch, tmp_path):
    """Api.reveal_file on win32 passes the two-item list to Popen."""
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
    # A missing file never reaches Popen.
    captured.clear()
    assert api.reveal_file("nope.txt") is False
    assert "args" not in captured


# ---- (d) disconnect -----------------------------------------------------

def test_d_disconnect_flag_wired():
    assert "window._userDisconnected = true" in PAGE
    # Set in doLogout and in the mobile Disconnect handler.
    assert PAGE.count("window._userDisconnected = true") >= 2
    # The sessionless re-mint block respects it.
    assert "!window._userDisconnected" in PAGE
    # checkAuth short-circuits to the login page while it is set.
    assert "if(window._userDisconnected && !st.host){ showGuestLogin(); }" in PAGE
    # Cleared on the next successful MANUAL connect only.
    assert PAGE.count("window._userDisconnected = false") >= 4


# ---- (e) saved on this phone --------------------------------------------

def test_e_saved_rows_have_exactly_one_button():
    # Preview button gone from HTML, binding and CSS.
    assert ".gsavedrow .btn.gspreview" not in PAGE
    assert "data-preview-saved=" not in PAGE
    # Each row renders ONE button -- Open -- and the thumbnail
    # still opens the same viewer.
    assert "data-open-saved=" in PAGE
    assert "function openSavedFile(name)" in PAGE
    # v2.8.41 (5): previewSavedFile gained the inApp flag --
    # the in-app Saved list must NOT set _savedReturn (closing
    # returns to the main page, like every other preview),
    # while the login-page Saved view still does. The old
    # one-arg signature assertion is updated, not the behaviour:
    # the thumbnail/name tap still opens the same viewer.
    assert "function previewSavedFile(name, inApp)" in PAGE
    # Viewer close returns to the saved view when the file came
    # from there; the saved view is never the login form.
    assert "window._savedReturn = true" in PAGE
    assert "showSavedView()" in PAGE


# ---- (f) copy = full link -------------------------------------------------

def test_f_full_address_url_prefers_auth_url():
    m = re.search(r"function fullAddressUrl\(name\)\{(.*?)\n\}", PAGE, re.S)
    assert m, "fullAddressUrl missing"
    fn = "function fullAddressUrl(name){" + m.group(1) + "\n}"
    cases = ("fullAddressUrl('probeaddr')",
             "fullAddressUrl('probeaddr.local:18721')",
             "fullAddressUrl('')",
             "fullAddressUrl('10.0.0.5')",
             "fullAddressUrl('otheraddr')")
    js = ("const AUTH={address_name:'probeaddr',"
          "url:'http://probeaddr.local:18721'};\n"
          "const location={host:'127.0.0.1:34175'};\n" + fn +
          "\nconsole.log(JSON.stringify([" + ",".join(cases) + "]));")
    out = subprocess.run(["node", "-e", js], capture_output=True,
                         text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout.strip())
    # '' falls back to the current address (by design); a bare IP
    # never gets .local; any other name gets .local + the page port.
    assert got == ["http://probeaddr.local:18721/",
                    "http://probeaddr.local:18721/",
                    "http://probeaddr.local:18721/",
                    "http://10.0.0.5:34175/",
                    "http://otheraddr.local:34175/"]
    # With no current address at all, '' really is empty.
    js2 = ("const AUTH={address_name:'', url:''};\n"
           "const location={host:'127.0.0.1:34175'};\n" + fn +
           "\nconsole.log(JSON.stringify([fullAddressUrl(''),"
           " fullAddressUrl('otheraddr')]));")
    out2 = subprocess.run(["node", "-e", js2], capture_output=True,
                          text=True, timeout=30)
    assert out2.returncode == 0, out2.stderr
    assert json.loads(out2.stdout.strip()) == [
        "", "http://otheraddr.local:34175/"]


def test_f_copy_buttons_use_full_url_and_classic_icon():
    # Top pill, mobile, and Set Up copy all build the full URL.
    assert "const url = fullAddressUrl() ||" in PAGE
    assert "fullAddressUrl(maddrNorm() || undefined)" in PAGE
    assert "const v = fullAddressUrl();" in PAGE
    assert 'id="lkcopy"' in PAGE
    # Classic copy icon (two overlapping rectangles), never the
    # clipboard emoji, on the mobile and Set Up copy buttons.
    # (A pre-existing "📋 Copy" button lives in the AI-result
    # area -- not an address copy, out of scope for (f)/(k).)
    for bid in ("mcopy", "lkcopy"):
        assert COPY_RECTS in _button_svg(PAGE, bid), bid + " icon"
        assert "📋" not in _button_svg(PAGE, bid)
    # Round5 pin: the top pill's tooltip is unchanged.
    assert 'data-tip="Copy the address name"' in PAGE


# ---- (g) Send Text icon -----------------------------------------------------

def test_g_send_text_is_chat_bubble():
    for bid in ("sendsnippet", "msendsnippet"):
        svg = _button_svg(PAGE, bid)
        assert BUBBLE in svg, bid + " is not the chat bubble"
        assert UPLOAD_TRAY not in svg, bid + " still has the upload icon"
    # The h3 icon next to "Send Text" is the same bubble geometry.
    i = PAGE.index("Send Text</h3>")
    seg = PAGE[max(0, i - 900):i]
    assert BUBBLE in seg


# ---- (h) web login centring ---------------------------------------------------

def test_h_login_centred():
    rule = _css_rule(PAGE, ".guestlogin")
    assert "align-items:center" in rule
    assert "min-height:100dvh" in rule
    logo = _css_rule(PAGE, ".glogo")
    assert "justify-content:center" in logo
    assert "align-items:center" in logo


# ---- (i) web Choose Files / Send Text buttons ------------------------------

def test_i_web_buttons_identical_shape_smaller_width():
    m = re.search(r"\.msend #msendfiles, \.msend #msendsnippet \{([^}]*)\}", PAGE)
    assert m, "shared (i) rule missing"
    rule = m.group(1)
    assert "width:70%" in rule
    assert "margin:10px auto 0" in rule
    assert "display:flex" in rule
    assert "border-radius:13px" in rule
    # The shared rule sits AFTER the 2.8.13 full-width pill rule,
    # so it wins on shape; colours stay different per button.
    assert PAGE.index(".msend #msendfiles { background:#4E342E") < PAGE.index(m.group(0))


# ---- (j) floating upload ring + pop -----------------------------------------

def test_j_floating_ring_present_old_rows_gone():
    assert 'id="upfloat"' in PAGE
    assert 'id="upringprog"' in PAGE
    assert 'id="upringnum"' in PAGE
    assert 'id="upfloatname"' in PAGE
    rule = _css_rule(PAGE, ".upfloat")
    assert "position:fixed" in rule
    assert "background:transparent" in rule
    # Solid blue ring, radius 26 (circumference 163.36).
    assert "#277ff0" in PAGE
    assert 'r="26"' in PAGE
    # Old progress rows / bars gone from markup, JS and CSS.
    assert 'class="up"' not in PAGE
    assert ".up {" not in PAGE
    assert 'class="bar"' not in PAGE
    assert ".bar {" not in PAGE
    # Pop sound: defined once, played on file-upload success and
    # on note-send success; notes get the pop only, no bar.
    assert "function playPopSound()" in PAGE
    assert PAGE.count("playPopSound();") >= 2
    assert "xhr.upload.onprogress" in PAGE


# ---- (k) web Set Up Your Addresses ------------------------------------------

def test_k_setup_dropdown_and_real_connect():
    assert 'id="mddtoggle"' in PAGE
    assert 'id="mddlist"' in PAGE
    assert "function paintMobileAddressHistory()" in PAGE
    # Host history first, this device's own history as fallback
    # (/api/linkhistory is host-only; guests get 403).
    seg = PAGE[PAGE.index("function paintMobileAddressHistory()"):
               PAGE.index("function paintMobileAddressHistory()") + 1100]
    assert "/api/linkhistory" in seg
    # Empty host history falls back to this device's own use
    # counts (addressUseCounts reads localStorage drop_link_use).
    assert "addressUseCounts()" in seg
    assert '"drop_link_use"' in PAGE[PAGE.index("function addressUseCounts()"):
                                     PAGE.index("function addressUseCounts()") + 200]
    assert "No saved addresses yet." in seg
    # The mobile Connect button reuses the real connect flow.
    seg2 = PAGE[PAGE.index('$("#mpcconnect")'):
                PAGE.index('$("#mpcconnect")') + 5000]
    assert 'postJ("/api/connect", {link: bareM})' in seg2
    # Only an IP / a different machine's host:port navigates.
    assert 'location.href = "http://" + host + "/"' in seg2


# ---- (l) duplicate address + scroll -------------------------------------------

def test_l_duplicate_address_gone():
    assert 'mc.textContent = (st.authed && st.address_name) ? "Connected" : "Not connected"' in PAGE
    # The state line's initial markup is a bare state, not the address.
    i = PAGE.index('id="mconnstate"')
    assert ">Not connected</div>" in PAGE[i:i + 80]


# ---- (m) Shared Files heading + Saved button ----------------------------------

def test_m_heading_aligned_and_saved_solid():
    assert '.col[data-col="files"] .colhead h2 { margin-left:4px; }' in PAGE
    # .msavedbtn has several rules (a width rule, a display:none
    # rule); the visible one is the inline-flex rule.
    rules = re.findall(r"(?:^|[\n}])\s*\.msavedbtn\s*\{([^}]*)\}", PAGE)
    rule = next(r for r in rules if "display:inline-flex" in r)
    assert "background:#277ff0" in rule
    assert "color:#ffffff" in rule
    assert "gradient" not in rule
    assert "border:none" in rule


# ---- live probes ------------------------------------------------------------

AC_SPY = """
window.__acCount = 0;
window.__clip = null;
(function(){
  const _AC = window.AudioContext || window.webkitAudioContext;
  if(_AC){
    const W = function(...a){ window.__acCount++; return new _AC(...a); };
    W.prototype = _AC.prototype;
    window.AudioContext = W; window.webkitAudioContext = W;
  }
  if(navigator.clipboard && navigator.clipboard.writeText){
    const _w = navigator.clipboard.writeText.bind(navigator.clipboard);
    navigator.clipboard.writeText = (t) => { window.__clip = t; return _w(t).catch(()=>{}); };
  }
})();
"""

BRIDGE_STUB = """
window.__revealed = null;
window.pywebview = { api: {
  reveal_file: async (n) => { window.__revealed = n; return true; }
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


def test_live_guest_mobile_390(server):
    """(l)(m)(k)(f)(j)(d) live on a 390px guest page."""
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "probeaddr"})
    client.upload("photo-test.txt", b"photo test content")
    client.upload("notes-test.txt", b"notes test content")
    fwd = _Fwd(port)
    guest_url = "http://127.0.0.3:%d/" % fwd.port
    pw = _pw()
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    try:
        ctx = browser.new_context(viewport={"width": 390, "height": 844},
                                  permissions=["clipboard-read", "clipboard-write"])
        ctx.add_init_script(AC_SPY)
        pg = ctx.new_page()
        pg.goto(guest_url)
        pg.wait_for_timeout(1200)
        # (l) the Upload page is not scrollable at 390px.
        m = pg.evaluate("() => ({docSH: document.documentElement.scrollHeight,"
                        " ih: window.innerHeight})")
        assert m["docSH"] == m["ih"], m
        # (m) Shared Files heading aligns with the thumbnails.
        pg.click('.mtab[data-tab="files"]')
        pg.wait_for_timeout(600)
        m = pg.evaluate("() => ({h2x: document.querySelector('.col[data-col=\"files\"] .colhead h2').getBoundingClientRect().x,"
                        " thx: document.querySelector('.thwrap').getBoundingClientRect().x})")
        assert abs(m["h2x"] - m["thx"]) <= 1, m
        pg.click('.mtab[data-tab="send"]')
        pg.wait_for_timeout(400)
        # (k) dropdown: round34 (1)(5) -- the sessionless
        # auto-connect already recorded the use, so the address
        # is listed at once (no longer "No saved addresses
        # yet." on a fresh open-address guest); the explicit
        # connect keeps it listed and bumps the count.
        pg.click("#mddtoggle")
        pg.wait_for_timeout(400)
        assert "probeaddr" in pg.inner_text("#mddlist")
        pg.click("#mpcconnect")
        pg.wait_for_function(
            "() => !document.querySelector('#guestlogin').classList.contains('open')",
            timeout=10000)
        st = pg.evaluate("async () => (await (await fetch('/api/authstate')).json())")
        assert st["authed"] is True and st["host"] is False
        assert pg.evaluate("() => JSON.parse(localStorage.getItem('drop_link_use') || '{}')").get("probeaddr") >= 1
        pg.click("#mddtoggle")
        pg.wait_for_timeout(400)
        assert "probeaddr" in pg.inner_text("#mddlist")
        # (f) mobile copy gives the full URL on the SERVER port,
        # not the forwarder's port.
        pg.click("#mcopy")
        pg.wait_for_timeout(400)
        assert pg.evaluate("() => window.__clip") == \
            "http://probeaddr.local:%d/" % port
        # (j) ring: throttled upload, sample the ring mid-flight.
        up_path = os.path.join(base, "upload-big.bin")
        with open(up_path, "wb") as fh:
            fh.write(os.urandom(2 * 1024 * 1024))
        cdp = ctx.new_cdp_session(pg)
        cdp.send("Network.enable")
        cdp.send("Network.emulateNetworkConditions",
                 {"offline": False, "latency": 20, "downloadThroughput": -1,
                  "uploadThroughput": 400 * 1024})
        pg.set_input_files("#mpicker", up_path)
        pg.wait_for_function(
            "document.querySelector('#upringnum').textContent === '1'",
            timeout=5000)
        samples = []
        for _ in range(30):
            samples.append(pg.evaluate(
                "() => ({num: document.querySelector('#upringnum').textContent,"
                " off: parseFloat(document.querySelector('#upringprog').style.strokeDashoffset),"
                " name: document.querySelector('#upfloatname').textContent,"
                " shown: document.querySelector('#upfloat').classList.contains('show'),"
                " upRows: document.querySelectorAll('.up').length,"
                " barRows: document.querySelectorAll('.bar').length})"))
            if samples[-1]["num"] == "0":
                break
            pg.wait_for_timeout(200)
        held = [s for s in samples if s["num"] == "1"]
        assert held, samples
        assert all(s["shown"] and s["name"] == "upload-big.bin"
                   and s["upRows"] == 0 and s["barRows"] == 0 for s in held)
        offsets = [s["off"] for s in held]
        assert offsets[0] <= 163.36 and min(offsets) < offsets[0], offsets
        assert samples[-1]["num"] == "0"
        pg.wait_for_function(
            "!document.querySelector('#upfloat').classList.contains('show')",
            timeout=20000)
        # (j) pop on upload done, and on a note send (the upload
        # switches the mobile view away from the send tab, and
        # the mobile note box is #msendtext, not #mnote).
        assert pg.evaluate("() => window.__acCount") >= 1
        pg.click('.mtab[data-tab="send"]')
        pg.wait_for_timeout(300)
        before = pg.evaluate("() => window.__acCount")
        pg.fill("#msendtext", "probe note for pop")
        pg.click("#msendsnippet")
        pg.wait_for_timeout(800)
        assert pg.evaluate("() => window.__acCount") > before
        # (d) disconnect lands on the login page and STAYS there.
        pg.evaluate("() => { window._sessionlessConnectDone = false; }")
        pg.click("#mpcdisconnect")
        pg.wait_for_function(
            "document.querySelector('#guestlogin').classList.contains('open')",
            timeout=10000)
        pg.wait_for_timeout(6000)
        assert pg.evaluate(
            "() => document.querySelector('#guestlogin').classList.contains('open')")
        st, j = client.j("GET", "/api/sessions")
        assert j.get("sessions") == []
        st, j = client.j("GET", "/api/status")
        assert j.get("devices") == 0
        ctx.close()
    finally:
        browser.close()
        pw.stop()
        fwd.close()


def test_live_host_desktop(server):
    """(f) top + Set Up copy, (c) bridge reveal, (a)(g) icons."""
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "probeaddr"})
    client.upload("photo-test.txt", b"photo test content")
    pw = _pw()
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    try:
        ctx = browser.new_context(viewport={"width": 1280, "height": 800},
                                  permissions=["clipboard-read", "clipboard-write"])
        ctx.add_init_script(AC_SPY)
        ctx.add_init_script(BRIDGE_STUB)
        pg = ctx.new_page()
        pg.goto("http://127.0.0.1:%d/" % port)
        pg.wait_for_timeout(1200)
        pg.click("#copy")
        pg.wait_for_timeout(400)
        assert pg.evaluate("() => window.__clip") == \
            "http://probeaddr.local:%d/" % port
        pg.evaluate("async () => { await revealFile('photo-test.txt'); }")
        pg.wait_for_timeout(400)
        assert pg.evaluate("() => window.__revealed") == "photo-test.txt"
        pg.click("#toplink")
        pg.wait_for_timeout(600)
        pg.click("#lkcopy")
        pg.wait_for_timeout(400)
        assert pg.evaluate("() => window.__clip") == \
            "http://probeaddr.local:%d/" % port
        pg.click("#lkcloseX")
        pg.wait_for_timeout(400)
        # (a) sidebar Change Folder = pencil; (g) Send Text = bubble.
        # #changefolder is rendered only by a desktop-mode server
        # (server.desktop, set by app.py, not by the test harness),
        # so it is absent here; its artwork is proven statically
        # against the 2.8.8 originals instead.
        m = pg.evaluate("""() => {
          const svg = id => { const el = document.querySelector(id);
                              return el ? el.innerHTML : null; };
          return { sb: svg('#sbchange'), cf: svg('#changefolder'),
                   lk: svg('#lkchangefolder'), st: svg('#sendsnippet') };
        }""")
        assert PENCIL in m["sb"] and (m["cf"] is None or PENCIL in m["cf"])
        assert all(p in m["lk"] for p in SWAP)
        assert BUBBLE in m["st"] and UPLOAD_TRAY not in m["st"]
        ctx.close()
    finally:
        browser.close()
        pw.stop()


def test_live_login_centring_and_saved_390(server):
    """(h) login centred, (e) one Open button, viewer close -> saved."""
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "probeaddr"})
    client.j("POST", "/api/setlinkpassword", {"password": "pw123456"})
    fwd = _Fwd(port)
    guest_url = "http://127.0.0.3:%d/" % fwd.port
    pw = _pw()
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    try:
        ctx = browser.new_context(viewport={"width": 390, "height": 844},
                                  permissions=["clipboard-read", "clipboard-write"])
        pg = ctx.new_page()
        pg.goto(guest_url)
        pg.wait_for_function(
            "document.querySelector('#guestlogin').classList.contains('open')",
            timeout=10000)
        pg.wait_for_timeout(800)
        m = pg.evaluate("""() => {
          const g = document.querySelector('.glogo').getBoundingClientRect();
          const b = document.querySelector('.gloginbox').getBoundingClientRect();
          const t = document.querySelector('#themeswLogin').getBoundingClientRect();
          return { logoCX: g.x + g.width / 2, boxCX: b.x + b.width / 2,
                   groupCY: (b.y + t.bottom) / 2,
                   vpCX: window.innerWidth / 2,
                   vpCY: window.innerHeight / 2 };
        }""")
        assert abs(m["logoCX"] - m["vpCX"]) <= 1, m
        assert abs(m["boxCX"] - m["vpCX"]) <= 1, m
        # Round34 (6): the theme toggle sits below the card, so
        # the LOGIN GROUP (box + toggle) is centred, not the box
        # alone.
        assert abs(m["groupCY"] - m["vpCY"]) <= 2, m
        # (e) saved view: one button, Open; viewer close -> saved.
        pg.evaluate("""async () => {
          localStorage.setItem('dropit_dl',
            JSON.stringify({'hello.txt': {size: 5, ts: 1700000000}}));
          await DBCACHE.put('hello.txt', new Blob(['hello'], {type: 'text/plain'}));
        }""")
        pg.click("#gsavedbtn")
        pg.wait_for_selector(".gsavedrow", timeout=5000)
        pg.wait_for_timeout(400)
        m = pg.evaluate("""() => {
          const row = document.querySelector('.gsavedrow');
          return { buttons: [...row.querySelectorAll('button')].map(b => b.textContent.trim()),
                   hasPreview: !!row.querySelector('.gspreview') };
        }""")
        assert m["buttons"] == ["Open"], m
        assert m["hasPreview"] is False
        pg.click(".gsavedrow [data-open-saved]")
        pg.wait_for_selector("#viewer.open", timeout=5000)
        pg.wait_for_timeout(400)
        assert "hello" in pg.evaluate(
            "() => document.querySelector('#vcontent').innerText")
        pg.click("#vclose")
        pg.wait_for_function(
            "document.querySelector('#gsavedview').classList.contains('open')",
            timeout=10000)
        assert pg.evaluate(
            "() => document.querySelector('#gloginform').style.display") == "none"
        ctx.close()
    finally:
        browser.close()
        pw.stop()
        fwd.close()


def test_live_mobile_buttons_identical(server):
    """(i) web Choose Files / Send Text: identical, narrower, centred."""
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "probeaddr"})
    fwd = _Fwd(port)
    pw = _pw()
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    try:
        ctx = browser.new_context(viewport={"width": 390, "height": 844},
                                  permissions=["clipboard-read", "clipboard-write"])
        pg = ctx.new_page()
        pg.goto("http://127.0.0.3:%d/" % fwd.port)
        pg.wait_for_timeout(1200)
        m = pg.evaluate("""() => {
          const f = document.querySelector('#msendfiles').getBoundingClientRect();
          const t = document.querySelector('#msendsnippet').getBoundingClientRect();
          const card = document.querySelector('.msend').getBoundingClientRect();
          const cs = getComputedStyle(document.querySelector('#msendfiles'));
          const ts = getComputedStyle(document.querySelector('#msendsnippet'));
          return { filesW: f.width, textW: t.width, filesX: f.x, textX: t.x,
                   cardW: card.width, cardX: card.x,
                   filesR: cs.borderRadius, textR: ts.borderRadius,
                   mHasBubble: document.querySelector('#msendsnippet').innerHTML.includes('M21 11.5a8.38') };
        }""")
        assert m["filesW"] == m["textW"], m
        assert m["filesX"] == m["textX"], m
        assert m["filesR"] == m["textR"] == "13px", m
        assert m["filesW"] < m["cardW"], m
        assert abs((m["cardX"] + m["cardW"] / 2) - (m["filesX"] + m["filesW"] / 2)) <= 1, m
        assert m["mHasBubble"] is True
        ctx.close()
    finally:
        browser.close()
        pw.stop()
        fwd.close()
