"""v2.8.21 round (Essef Nov 5, ~10:30 PM voice call) -- web/desktop only.

(A) PICTURE + VIDEO PREVIEW FIT VIEW: the Files-tab preview
    (.previewpop) for a tall picture or a portrait video needed
    scrolling (2.8.20 probe: tall 500x2000 image showed 505 of
    2000px, portrait 720x1280 video 505 of 1081px). Image/video
    previews now get .fitmedia on the pop: a bigger box
    (min(1080px,96vw), 92vh), a non-scrolling flex body, and the
    media clamped by vh-unit max-height so the whole picture /
    video is visible at once -- not a zoomed-out immersive view.
    The saved-file viewer (#viewer) gets the same fit for its
    img/video; PDF (embed 52vh) and Word/text keep their
    scrolling preview untouched.
(B) NO SIDE-TO-SIDE SCROLLER ON THE PC APP: the pywebview
    desktop page gets .pcapp on <html> (markPcApp at boot + on
    pywebviewready) and html.pcapp / html.pcapp body get
    overflow-x:hidden. Plain browsers / phones never get the
    class. Verified live: no element extends past the right
    viewport edge at desktop widths, host + sidebar open +
    Set Up open.
(C) SET UP LIGHT-MODE LABELS ONLY: in light mode the host
    dialog labels were the pale #aab9ed on a white card.
    html.light .lkbox:not(.guestcard) .lklabel and .lkpermlabel
    are now #1e293b -- the five labels only ("Current Address",
    "Folder For This Address", "New Address", "Password
    (Optional)", "Permissions"). Dark mode keeps #aab9ed; the
    live test proves the labels' geometry is identical in both
    modes, so nothing was resized or moved.

Plus re-verification of the 2.8.20 items 3, 4, 5, 8, which the
first round36 file only covered by inspection:
(3) Saved button solid blue (#277ff0, theme text via .btn);
(4) saved-file viewer close returns to the Saved view
(_savedReturn) and the viewer pushes one history entry so
back closes it; (5) file-type badge is the bordered chip,
white text in dark mode, dark-blue (#0369a1) in light mode;
(8) real circular upload ring: solid blue, dashoffset from
real xhr.upload.onprogress, count decrements per finished file.

v2.8.20 fix round (Essef Nov 5, 9:53 PM) -- web/desktop only.

(1) SMALL-SCREEN CARD OVERLAP: on a smaller phone (360px wide /
    short height, light mode) the Upload tab's Share Text card was
    clipped by its column (stack 550px, column 366px at 360x640)
    and the Send Text button ended up UNDER the pill tabs
    (button bottom 642, tabs top 556). fitSendTab now also enables
    scrolling when the Send column's content overflows, so
    scrolled-to-bottom the button sits fully inside its card with
    space below, clear of the pill tabs. The bigger Share Text box
    (item 7, +44px) is paid for by ~36px of spacing trims on the
    mobile Send tab only, so 390x844 still fits WITHOUT scrolling
    (the 2.8.18 no-scroll fit holds on Essef's phone). No extra
    bottom padding is added: it would count toward scrollHeight
    and latch the scroll class on once the keyboard opened.
(2) DUPLICATE "YOUR ADDRESS" IN PC MENU: the host already sees
    the address in the "Set Up Your Addresses" card (#sblink), so
    the 2.8.18 "Your address" row (#sbaddrcard) duplicated it in
    the PC menu. paintSidebar hides #sbaddrcard for the host;
    guests keep it -- it is their only address row in the web
    menu (their Set Up cards are hidden).
(6) NARROWER UPLOAD BUTTONS (web): "Send Text" and "Choose Files
    to Send" go from 70% to 60% width, centred -- the APK / login
    "Saved on this phone" width.
(7) TEXT BOX -- OWN SCROLLER, SCROLL ONCE, BACK CLOSES KEYBOARD
    (web/mobile web): #msendtext is bigger (min-height 110px like
    desktop #snippet, rows 5) with its own scroller (max-height
    190px, overflow-y:auto, overscroll-behavior:contain). On
    focus it scrolls into view ONCE per focus session; typing
    after that scrolls only inside the box, never the page. Back
    while the box is focused closes the keyboard (blur) and stays
    on the screen: focus pushes ONE history entry, a back-press
    consumes it and blurs; a blur without a back-press removes
    the entry again.
(9) OPEN IN FOLDER ON PC STILL DEAD: root cause -- reveal_file
    is the ONLY Windows path in the app that spawns via
    subprocess.Popen; open_folder/open_file/open_root_folder all
    use os.startfile on Windows (and they work). In the frozen
    --windowed build the process has no console and no valid std
    handles, so Popen's inherited stdio fails the spawn with
    [WinError 6] "The handle is invalid" -- caught, recorded,
    returned False: a dead click with nothing visible happening.
    The 2.8.18 probe could never see this (it faked Popen, on
    Linux). The spawn now goes through _spawn() (DEVNULL stdio +
    close_fds) in app.py and in the server /api/reveal handler,
    and the record is readable again: Api.get_last_reveal() for
    the bridge path (revealFile names the recorded error in its
    toast) and GET /api/reveal/last for the server path.
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
from test_link_round2 import server, _raw  # noqa: F401,E402
from test_link_round3 import _flip_role, _guest_client  # noqa: E402
from test_link_round34 import _Fwd  # noqa: E402

PAGE = D.PAGE
SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py"),
           encoding="utf-8").read()
APP = open(os.path.join(os.path.dirname(__file__), "..", "app.py"),
           encoding="utf-8").read()

MOBILE_UA = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) "
             "AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/124.0 Mobile Safari/537.36")
PROOF = "/home/hatch/workspace/dropit-proof-round36"
os.makedirs(PROOF, exist_ok=True)


def _css_rule(page, selector):
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", page)
    assert m, selector + " rule missing"
    return m.group(1)


def test_version_is_2_8_21():
    assert D.VERSION == "2.8.21"


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
        with open("/tmp/r36_script_%d.js" % i, "w",
                  encoding="utf-8") as fh:
            fh.write(js)
        out = subprocess.run(["node", "--check",
                              "/tmp/r36_script_%d.js" % i],
                             capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr


# ---- (1) small-screen card overlap -----------------------------------

def test_1_fitsendtab_scrolls_on_overflow():
    assert "colbody.scrollHeight > colbody.clientHeight" in PAGE
    assert "send-may-scroll" in PAGE
    # No bottom-clearance padding on .msend: it would count
    # toward scrollHeight and latch the scroll class on (once
    # on -- e.g. keyboard focus -- it could never turn off).
    # The clearance at max scroll comes from the colbody's own
    # bottom edge, which already clears the pill tabs.
    assert "padding-bottom:100px" not in PAGE
    # The bigger Share Text box (+44px) is paid for by ~36px
    # of spacing trims on the mobile Send tab only, so 390x844
    # still fits without scrolling (see the live test below).
    assert ".board .col[data-col=\"send\"] .msend .minicard" in PAGE
    assert "padding:10px 12px" in PAGE
    assert "margin-top:6px" in PAGE


# ---- (2) duplicate address in PC menu --------------------------------

def test_2_host_hides_sbaddrcard_guest_keeps_it():
    i = SRC.index("function paintSidebar(){")
    seg = SRC[i:i + 2200]
    assert '#sbaddrcard' in seg
    assert 'st.host ? "none" : ""' in seg, seg
    # The guest row itself is still painted (guests need it).
    assert 'const _sa = $("#sbaddr")' in seg
    # The host setup card is untouched by this change.
    assert '"#sbsetupcard"' in seg


# ---- (6) narrower Upload buttons -------------------------------------

def test_6_upload_buttons_60_percent():
    m = re.search(
        r"\.msend #msendfiles, \.msend #msendsnippet \{([^}]*)\}", PAGE)
    assert m, "upload button width rule missing"
    assert "width:60%" in m.group(1).replace(" ", ""), m.group(1)
    assert "width:70%" not in m.group(1)


# ---- (7) text box -----------------------------------------------------

def test_7_textbox_bigger_own_scroller():
    rule = _css_rule(PAGE, "#msendtext")
    flat = rule.replace(" ", "")
    assert "min-height:110px" in flat, rule
    assert "min-height:52px" not in flat
    assert "max-height:190px" in flat, rule
    assert "overflow-y:auto" in flat, rule
    assert "overscroll-behavior:contain" in flat, rule
    assert '<textarea id="msendtext" rows="5"' in PAGE


def test_7_scroll_once_and_back_closes_keyboard_source():
    # Scroll into view once per focus session (flag-guarded).
    assert "_mstKbScrolled" in PAGE
    assert "_mst.scrollIntoView" in PAGE
    # Back closes keyboard: one pushed entry per focus session.
    assert "history.pushState({dropKb:1}" in PAGE
    assert "_mstKbPushed" in PAGE
    assert "history.back()" in PAGE
    # The popstate handler blurs instead of leaving.
    assert "document.activeElement === _mst" in PAGE
    assert "_mst.blur()" in PAGE


# ---- (9) reveal root cause + diagnostics ------------------------------

def test_9_spawn_devnull_stdio_and_last_reveal():
    assert "def _spawn(argv):" in APP
    assert "stdin=subprocess.DEVNULL" in APP
    assert "stdout=subprocess.DEVNULL" in APP
    assert "stderr=subprocess.DEVNULL" in APP
    assert "close_fds=True" in APP
    # reveal_file is the only Windows Popen site left using it.
    assert "def reveal_file(self, name: str) -> bool:" in APP
    assert "def get_last_reveal(self) -> dict:" in APP
    assert "_spawn(argv)" in APP
    # No bare Popen left in app.py's reveal/open paths.
    assert "subprocess.Popen([" not in APP
    # The page asks the bridge WHY it said no.
    assert "window.pywebview.api.get_last_reveal()" in PAGE
    assert "__revealDetail" in PAGE
    # Server fallback: same DEVNULL spawn + record + endpoint.
    assert "elif path == \"/api/reveal/last\":" in SRC
    assert "self.server.last_reveal = rec" in SRC
    assert 'path == "/api/reveal"' in SRC


def _playwright():
    from playwright.sync_api import sync_playwright
    return sync_playwright().start()


def _guest_page(pw, port, width, height, light=True):
    fwd = _Fwd(port)
    guest_url = "http://127.0.0.3:%d/" % fwd.port
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    ctx = browser.new_context(
        viewport={"width": width, "height": height}, has_touch=True,
        is_mobile=True, user_agent=MOBILE_UA)
    pg = ctx.new_page()
    pg.goto(guest_url)
    pg.wait_for_function(
        "() => !document.querySelector('#guestlogin')"
        ".classList.contains('open')", timeout=10000)
    pg.wait_for_timeout(900)
    if light:
        pg.evaluate("() => document.documentElement.classList"
                    ".add('light')")
        pg.wait_for_timeout(300)
    return browser, ctx, pg, fwd


def _measure_send_tab(pg):
    return pg.evaluate("""() => {
      const btn = document.querySelector('#msendsnippet');
      const card = btn.closest('.minicard');
      const tabs = document.querySelector('.mtabs');
      const colbody = document.querySelector('.col[data-col="send"] .colbody');
      const b = btn.getBoundingClientRect(), c = card.getBoundingClientRect(),
            t = tabs.getBoundingClientRect();
      return {mayScroll: document.body.classList.contains('send-may-scroll'),
        btnBottom: b.bottom, btnTop: b.top, btnW: b.width,
        cardBottom: c.bottom, cardTop: c.top,
        tabsTop: t.top, gapBtnToTabs: t.top - b.bottom,
        gapCardBottomToBtn: c.bottom - b.bottom,
        colbodyScrollH: colbody.scrollHeight, colbodyClientH: colbody.clientHeight,
        colbodyScrollTop: colbody.scrollTop,
        filesBtnW: document.querySelector('#msendfiles').getBoundingClientRect().width,
        cardContentW: c.width - 20};
    }""")


def test_1_live_small_phone_send_text_clear_of_tabs(server):
    """360x640 light mode (the reported phone): scrolled to the
    bottom, the Send Text button sits fully inside its card with
    space below, clear of the pill tabs. 360x740 and 390x844 too."""
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r36send"})
    pw = _playwright()
    try:
        for (w, h) in [(360, 640), (360, 740), (390, 844)]:
            browser, ctx, pg, fwd = _guest_page(pw, port, w, h)
            try:
                m0 = _measure_send_tab(pg)
                # The short phone overflows -> scrolling is on.
                if (w, h) == (360, 640):
                    assert m0["mayScroll"] is True, m0
                    assert m0["colbodyScrollH"] > m0["colbodyClientH"], m0
                # 390x844 still fits WITHOUT scrolling (the bigger
                # box is paid for by the spacing trims).
                if (w, h) == (390, 844):
                    assert m0["mayScroll"] is False, m0
                    assert m0["colbodyScrollH"] <= m0["colbodyClientH"], m0
                # Scroll to the bottom of the Send column.
                pg.evaluate(
                    "() => { const c = document.querySelector('.col"
                    "[data-col=\"send\"] .colbody'); c.scrollTop = "
                    "c.scrollHeight; }")
                pg.wait_for_timeout(300)
                m = _measure_send_tab(pg)
                assert m["gapCardBottomToBtn"] >= 8, m
                assert m["gapBtnToTabs"] >= 8, m
                assert m["btnBottom"] <= m["cardBottom"] - 8, m
                assert m["btnBottom"] <= m["tabsTop"] - 8, m
                pg.screenshot(path=os.path.join(
                    PROOF, "r36_send_%dx%d.png" % (w, h)))
            finally:
                ctx.close()
                browser.close()
                fwd.close()
    finally:
        pw.stop()


def test_2_live_host_menu_one_address_guest_menu_one_address(server):
    """Host sidebar: the address appears exactly ONCE (setup card
    only, #sbaddrcard hidden). Guest sidebar: exactly ONCE too
    (the #sbaddrcard row, setup card hidden)."""
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r36addr"})
    pw = _playwright()
    try:
        # Host: loopback page (host bypass), desktop-ish viewport.
        browser = pw.chromium.launch(args=["--no-proxy-server"])
        try:
            pg = browser.new_page(viewport={"width": 1280,
                                            "height": 800})
            pg.goto("http://127.0.0.1:%d/" % port)
            pg.wait_for_timeout(1500)
            pg.click("#menubtn")
            pg.wait_for_timeout(600)
            host = pg.evaluate("""() => {
              const vis = sel => { const el = document.querySelector(sel);
                return !!el && getComputedStyle(el).display !== 'none'
                  && el.getBoundingClientRect().height > 0; };
              const txt = sel => (document.querySelector(sel)?.textContent || '');
              return {setupVisible: vis('#sbsetupcard'),
                addrRowVisible: vis('#sbaddrcard'),
                setupText: txt('#sblink'), addrText: txt('#sbaddr'),
                addrRows: [...document.querySelectorAll('#sidebar .sbcard')]
                  .filter(c => getComputedStyle(c).display !== 'none'
                    && /r36addr/.test(c.textContent)).length};
            }""")
            assert host["setupVisible"] is True, host
            assert host["addrRowVisible"] is False, host
            assert host["addrRows"] == 1, host
            assert "r36addr" in host["setupText"], host
            pg.screenshot(path=os.path.join(PROOF, "r36_menu_host.png"))
        finally:
            browser.close()
        # Guest: forwarded (non-loopback) page, mobile viewport.
        browser, ctx, pg, fwd = _guest_page(pw, port, 390, 844)
        try:
            pg.click("#menubtn")
            pg.wait_for_timeout(600)
            guest = pg.evaluate("""() => {
              const vis = sel => { const el = document.querySelector(sel);
                return !!el && getComputedStyle(el).display !== 'none'
                  && el.getBoundingClientRect().height > 0; };
              return {setupVisible: vis('#sbsetupcard'),
                addrRowVisible: vis('#sbaddrcard'),
                addrRows: [...document.querySelectorAll('#sidebar .sbcard')]
                  .filter(c => getComputedStyle(c).display !== 'none'
                    && /r36addr/.test(c.textContent)).length};
            }""")
            assert guest["setupVisible"] is False, guest
            assert guest["addrRowVisible"] is True, guest
            assert guest["addrRows"] == 1, guest
            pg.screenshot(path=os.path.join(PROOF, "r36_menu_guest.png"))
        finally:
            ctx.close()
            browser.close()
            fwd.close()
    finally:
        pw.stop()


def test_6_live_upload_buttons_60_percent(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r36btns"})
    pw = _playwright()
    try:
        browser, ctx, pg, fwd = _guest_page(pw, port, 390, 844)
        try:
            m = pg.evaluate("""() => {
              const card = document.querySelector('#msendsnippet')
                .closest('.minicard').getBoundingClientRect();
              const s = document.querySelector('#msendsnippet')
                .getBoundingClientRect();
              const f = document.querySelector('#msendfiles')
                .getBoundingClientRect();
              const inner = card.width - 20;  // minicard padding
              return {sendW: s.width, filesW: f.width,
                sendPct: s.width / inner, filesPct: f.width / inner,
                sendX: s.left, cardX: card.left,
                sendCentred: Math.abs((s.left + s.width / 2)
                  - (card.left + card.width / 2))};
            }""")
            assert 0.55 <= m["sendPct"] <= 0.65, m
            assert 0.55 <= m["filesPct"] <= 0.65, m
            assert abs(m["sendW"] - m["filesW"]) <= 2, m
            assert m["sendCentred"] <= 2, m
        finally:
            ctx.close()
            browser.close()
            fwd.close()
    finally:
        pw.stop()


def test_7_live_textbox_scroller_scroll_once_back_closes(server):
    """Bigger box with its own scroller; typing scrolls the box,
    not the page; Back (history) while focused blurs and stays
    on the screen; one history entry per focus session."""
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r36text"})
    pw = _playwright()
    try:
        browser, ctx, pg, fwd = _guest_page(pw, port, 360, 640)
        try:
            box = pg.evaluate("""() => {
              const b = document.querySelector('#msendtext');
              const cs = getComputedStyle(b);
              return {h: b.getBoundingClientRect().height,
                minH: cs.minHeight, maxH: cs.maxHeight,
                overflowY: cs.overflowY,
                overscroll: cs.overscrollBehaviorY || cs.overscrollBehavior,
                rows: b.getAttribute('rows')};
            }""")
            assert box["minH"] == "110px", box
            assert box["maxH"] == "190px", box
            assert box["overflowY"] == "auto", box
            assert "contain" in (box["overscroll"] or ""), box
            assert box["rows"] == "5", box
            assert box["h"] >= 110, box
            h0 = pg.evaluate("() => history.length")
            pg.click("#msendtext")
            pg.wait_for_timeout(600)  # past the 350ms scroll-once
            h1 = pg.evaluate("() => history.length")
            assert h1 == h0 + 1, (h0, h1)
            assert pg.evaluate("() => history.state") == {"dropKb": 1}
            # Type long text in three chunks; after the one-time
            # focus scroll, the page column must not scroll again
            # while typing (chunk 1 may settle the caret once;
            # chunks 1-3 must then be identical).
            tops = []
            for chunk in range(3):
                pg.keyboard.type(
                    "Line %d: the quick brown fox jumps over the lazy "
                    "dog and keeps going. " % chunk * 6, delay=5)
                pg.wait_for_timeout(250)
                tops.append(pg.evaluate("""() => ({
                  col: document.querySelector('.col[data-col="send"] .colbody').scrollTop,
                  box: document.querySelector('#msendtext').scrollTop,
                  boxH: document.querySelector('#msendtext').scrollHeight,
                  boxClient: document.querySelector('#msendtext')
                    .clientHeight})"""))
            # The box itself scrolls (own scroller active)...
            assert tops[-1]["boxH"] > tops[-1]["boxClient"], tops
            assert tops[-1]["box"] > 0, tops
            # ...while the page column does not move between chunks.
            assert tops[0]["col"] == tops[1]["col"] == tops[2]["col"], tops
            # Back while focused: closes the keyboard (blur), stays.
            # (history.length never shrinks on a back-press -- the
            # entry stays in the stack, we just move off it -- so
            # the check is the current entry's state + the blur.)
            url_before = pg.url
            pg.evaluate("() => history.back()")
            pg.wait_for_timeout(500)
            st = pg.evaluate("""() => ({
              active: document.activeElement
                ? document.activeElement.id : '',
              url: location.href, hlen: history.length,
              state: history.state})""")
            assert st["active"] != "msendtext", st
            assert st["url"] == url_before, st
            assert st["hlen"] == h1, st
            assert st["state"] != {"dropKb": 1}, st
            # A second focus pushes exactly one entry again (the
            # consumed forward entry is discarded, one appended),
            # and a plain blur (tap Send Text) removes it without
            # leaving.
            pg.click("#msendtext")
            pg.wait_for_timeout(600)
            assert pg.evaluate("() => history.length") == h1
            assert pg.evaluate("() => history.state") == {"dropKb": 1}
            pg.evaluate("() => document.querySelector"
                        "('#msendsnippet').focus()")
            pg.wait_for_timeout(500)
            st2 = pg.evaluate("""() => ({
              active: document.activeElement
                ? document.activeElement.id : '',
              url: location.href, hlen: history.length,
              state: history.state})""")
            assert st2["hlen"] == h1, st2
            assert st2["url"] == url_before, st2
            assert st2["state"] != {"dropKb": 1}, st2
            pg.screenshot(path=os.path.join(PROOF, "r36_textbox.png"))
        finally:
            ctx.close()
            browser.close()
            fwd.close()
    finally:
        pw.stop()


# ---- (9) reveal: bridge path + diagnostics, in-process -------------

def _make_api(tmp_path):
    home = tmp_path / "home"
    base = tmp_path / "base"
    base.mkdir(exist_ok=True)
    (home / ".config" / "DropIt").mkdir(parents=True, exist_ok=True)
    port = _free_port()
    server = D.make_server(port, str(base), desktop=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, home, base, port


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_9_reveal_windows_branch_spawn_and_trace(tmp_path, monkeypatch):
    """The Windows branch, in-process: argv is the two-item list
    and the spawn carries DEVNULL stdio (the 2.8.20 fix); the
    record is readable via get_last_reveal(). sys.platform is
    patched because this box is Linux -- the branch itself is
    what is under test, and real Windows Explorer is still
    unverified (see the report)."""
    server, home, base, port = _make_api(tmp_path)
    try:
        old_home = os.environ.get("HOME")
        old_appdata = os.environ.get("APPDATA")
        # _data_dir() is platform-dependent: Linux reads
        # $HOME/.config/DropIt, win32 reads %APPDATA%/DropIt.
        # Point both at the tmp home BEFORE patching the
        # platform, so the setlink write and the reveal read
        # see the same config.
        os.environ["HOME"] = str(home)
        os.environ["APPDATA"] = str(home)
        try:
            from test_link_folders import Client
            monkeypatch.setattr(sys, "platform", "win32")
            client = Client(port)
            st, j = client.j("POST", "/api/setlink",
                             {"name": "r36reveal"})
            assert st == 200 and j["ok"], j
            folder = j["folder"]
            open(os.path.join(folder, "photo test.txt"),
                 "w").write("x")
            captured = []

            class _FakeProc:
                def poll(self):
                    return 0

            def fake_popen(args, **kw):
                captured.append((list(args), kw))
                return _FakeProc()

            monkeypatch.setattr(appmod.subprocess, "Popen", fake_popen)
            api = appmod.Api(server)
            ok = api.reveal_file("photo test.txt")
            assert ok is True
            assert len(captured) == 1, captured
            argv, kw = captured[0]
            expect = os.path.join(folder, "photo test.txt")
            assert argv == ["explorer", "/select," + expect], argv
            assert kw.get("stdin") is subprocess.DEVNULL, kw
            assert kw.get("stdout") is subprocess.DEVNULL, kw
            assert kw.get("stderr") is subprocess.DEVNULL, kw
            assert kw.get("close_fds") is True, kw
            rec = api.get_last_reveal()
            assert rec["ok"] is True, rec
            assert rec["argv"] == argv, rec
            assert rec["path"] == expect, rec
            # Missing file: False + recorded reason, no spawn.
            captured.clear()
            assert api.reveal_file("nope.txt") is False
            assert captured == []
            rec = api.get_last_reveal()
            assert rec["ok"] is False and "file not found" in rec["error"], rec
            # Spawn failure (the old WinError 6 mode): False, and
            # the record names the error for the toast to show.
            def boom(args, **kw):
                raise OSError(6, "The handle is invalid")

            monkeypatch.setattr(appmod.subprocess, "Popen", boom)
            assert api.reveal_file("photo test.txt") is False
            rec = api.get_last_reveal()
            assert rec["ok"] is False, rec
            assert "WinError 6" in rec["error"] or "handle is invalid" in rec["error"], rec
            assert api.get_last_reveal()["error"] == rec["error"]
        finally:
            if old_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = old_home
            if old_appdata is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = old_appdata
    finally:
        server.shutdown()


def test_9_reveal_last_endpoint_live(server):
    """GET /api/reveal/last: host reads the record; guest 403s.
    The live call also exercises the server /api/reveal spawn
    (Linux xdg-open branch) with DEVNULL stdio."""
    client, base, proc, port, home = server
    st, j = client.j("POST", "/api/setlink",
                     {"name": "r36last", "password": "pw123"})
    assert st == 200 and j["ok"], j
    folder = j["folder"]
    open(os.path.join(folder, "a.txt"), "w").write("a")
    st, j = client.j("POST", "/api/reveal", {"name": "a.txt"})
    assert st == 200 and j["ok"], j
    st, j = client.j("GET", "/api/reveal/last")
    assert st == 200 and j["ok"], j
    rec = j["last_reveal"]
    assert rec and rec["ok"] is True, rec
    assert rec["name"] == "a.txt", rec
    assert rec["argv"] and rec["argv"][0] in ("xdg-open", "open",
                                              "explorer"), rec
    guest = _guest_client(port, "pw123")
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    st, j = guest.j("GET", "/api/reveal/last")
    assert st == 403, (st, j)
    st, j = guest.j("POST", "/api/reveal", {"name": "a.txt"})
    assert st == 403, (st, j)

# ---- 2.8.20 re-verification: items 3, 4, 5, 8 ------------------------
# (the first round36 file verified 1, 2, 6, 7, 9 only)

def test_3_saved_button_solid_blue():
    # The per-file Open button in the Saved view is solid blue;
    # its text comes from .btn (var(--txt)): theme-appropriate.
    rule = _css_rule(PAGE, ".gsavedrow .btn")
    flat = rule.replace(" ", "")
    assert "background:#277ff0" in flat, rule
    assert "border:none" in flat, rule
    # The login "Saved on this phone" button stays GREEN (2.8.18
    # (6), explicitly allowed) -- it is not this item's button.
    rule2 = _css_rule(PAGE, ".gloginbox #gsavedbtn")
    assert "background:#22c55e" in rule2.replace(" ", ""), rule2


def test_4_saved_return_viewer_close():
    # Opening a saved file sets _savedReturn; a bounce back to
    # the login page consumes it and re-opens the Saved view,
    # not the login form.
    assert "window._savedReturn = true" in PAGE
    assert ("if(window._savedReturn){ window._savedReturn = false; "
            "if(typeof showSavedView" in PAGE)
    # The viewer pushes ONE history entry, so a back-press closes
    # the viewer instead of leaving the page (ovOpened).
    assert "history.pushState({dov:1}" in PAGE
    # The Saved view's own Back button returns to the login form.
    assert ('const _gsbk = $("#gsavedback"); '
            "if(_gsbk) _gsbk.onclick = showLoginForm;") in PAGE


def test_5_badge_bordered_chip():
    rule = _css_rule(PAGE, ".tbadge")
    flat = rule.replace(" ", "")
    assert "border:1pxsolidvar(--line)" in flat, rule
    assert "border-radius:7px" in flat, rule
    label = _css_rule(PAGE, ".tbadge.tlabel")
    assert "color:#ffffff" in label.replace(" ", ""), label
    # Light mode: dark-blue text.
    assert "html.light .tbadge.tlabel { color:#0369a1; }" in PAGE


def test_8_progress_ring_real():
    # Solid blue ring, driven by real xhr progress -- not a spinner.
    assert ".upring-prog { fill:none; stroke:#277ff0;" in PAGE
    assert "stroke-dasharray:163.36" in PAGE
    assert "xhr.upload.onprogress" in PAGE
    assert "_upQ.loaded += (ev.loaded - prev)" in PAGE
    assert "p.style.strokeDashoffset = String(c * (1 - frac))" in PAGE
    # The number is the files still queued and DECREMENTS per finish.
    assert "const left = _upQ.pending.length;" in PAGE
    assert "_upQ.pending.splice(ix, 1)" in PAGE
    assert 'id="upringprog"' in PAGE and 'id="upringnum"' in PAGE
    assert "animation" not in _css_rule(PAGE, ".upring")


# ---- 2.8.21 (A) picture + video fit view ------------------------------

def test_A_fitmedia_css():
    m = re.search(r"\.previewpop\.fitmedia \.previewbox \{([^}]*)\}",
                  PAGE)
    assert m, "fitmedia box rule missing"
    flat = m.group(1).replace(" ", "")
    assert "width:min(1080px,96vw)" in flat, m.group(1)
    assert "max-height:92vh" in flat, m.group(1)
    body = re.search(
        r"\.previewpop\.fitmedia \.previewbox \.pvbody \{([^}]*)\}",
        PAGE)
    assert body, "fitmedia body rule missing"
    assert "overflow:hidden" in body.group(1).replace(" ", ""), body.group(1)
    media = re.search(
        r"\.previewpop\.fitmedia \.previewbox \.pvbody img, "
        r"\.previewpop\.fitmedia \.previewbox \.pvbody video "
        r"\{([^}]*)\}", PAGE)
    assert media, "fitmedia media rule missing"
    mflat = media.group(1).replace(" ", "")
    assert "max-height:calc(92vh-196px)" in mflat, media.group(1)
    assert "max-width:100%" in mflat, media.group(1)
    # PDF / doc preview untouched: embed still 52vh, viewer iframe 70vh.
    assert (".previewbox .pvbody embed, .previewbox .pvbody iframe "
            "{ width:100%; height:52vh;") in PAGE
    assert "#vcontent iframe { width:100%; height:70vh;" in PAGE
    # Saved-file viewer img/video also fit.
    assert "#vcontent img { max-width:100%; border-radius:10px; " \
        "display:block; margin:0 auto; " \
        "max-height:calc(88vh - 100px);" in PAGE
    assert "max-height:calc(88dvh - 100px)" in PAGE


def test_A_previewfile_adds_fitmedia_only_for_media():
    i = SRC.index("function previewFile(name, size){")
    seg = SRC[i:i + 4200]
    # Reset on every open and on close, so PDF/Word/text never
    # inherit the fit box.
    assert 'pop.classList.remove("fitmedia");' in seg
    assert ('const close = () => { pop.classList.remove("open"); '
            'pop.classList.remove("fitmedia");') in seg
    # Images and videos add it; audio does not.
    assert 'if(_PV_IMG.test(name)){ pop.classList.add("fitmedia");' in seg
    assert 'if(isVid) pop.classList.add("fitmedia");' in seg
    assert seg.count('classList.add("fitmedia")') == 2, seg


# ---- 2.8.21 (B) no side-to-side scroller on the PC app ----------------

def test_B_pcapp_css_and_js():
    assert "html.pcapp, html.pcapp body { overflow-x:hidden; }" in PAGE
    # Scoped to the PC app only: no blanket overflow-x rule on
    # plain html/body (phones keep their own behaviour).
    assert "html, body { overflow-x:hidden" not in PAGE
    assert "function markPcApp()" in PAGE
    assert ('document.documentElement.classList.add("pcapp")') in PAGE
    i = PAGE.index('window.addEventListener("pywebviewready"')
    assert "markPcApp();" in PAGE[i:i + 300]
    # markPcApp is also called at boot (bridge already present).
    assert PAGE.index("markPcApp();") < PAGE.index("let bridgeSeen")


# ---- 2.8.21 (C) Set Up light-mode labels only ------------------------

def test_C_light_labels_dark_only():
    m = re.search(
        r"html\.light \.lkbox:not\(\.guestcard\) \.lklabel,\s*"
        r"html\.light \.lkbox:not\(\.guestcard\) \.lkpermlabel "
        r"\{([^}]*)\}", PAGE)
    assert m, "light-mode label rule missing"
    assert "color:#1e293b" in m.group(1).replace(" ", ""), m.group(1)
    # Dark mode keeps the pale periwinkle; sizes untouched.
    assert (".lkbox:not(.guestcard) .lklabel { font-size:16px; "
            "letter-spacing:1px; color:#aab9ed; margin-bottom:10px; }") \
        in PAGE
    assert (".lkpermlabel { font-size:16px; letter-spacing:1px; "
            "color:#aab9ed;") in PAGE


# ---- 2.8.21 live tests (desktop host page, 127.0.0.1 = host) ----------

def _host_page(pw, port, width, height, bridge=False):
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    ctx = browser.new_context(viewport={"width": width, "height": height})
    if bridge:
        # Fake the pywebview bridge (open_file present, so
        # hasBridge() is true) -- the real bridge is injected
        # before page scripts run, same as add_init_script.
        ctx.add_init_script(
            "window.pywebview = {api: {open_file: "
            "() => Promise.resolve(true)}};")
    pg = ctx.new_page()
    pg.goto("http://127.0.0.1:%d/" % port)
    pg.wait_for_function(
        "() => !document.querySelector('#guestlogin')"
        ".classList.contains('open')", timeout=10000)
    pg.wait_for_function("() => typeof AUTH !== 'undefined' && AUTH.host",
                         timeout=10000)
    pg.wait_for_timeout(900)
    return browser, ctx, pg


def _preview_measure(pg, sel):
    return pg.evaluate(
        """() => {
      const b = document.querySelector('#previewbody');
      const m = b.querySelector('%s');
      const r = m ? m.getBoundingClientRect() : null;
      const br = b.getBoundingClientRect();
      return {fit: document.querySelector('#previewpop')
                .classList.contains('fitmedia'),
        boxW: Math.round(document.querySelector('.previewbox')
                .getBoundingClientRect().width),
        scrollH: b.scrollHeight, clientH: b.clientHeight,
        mediaH: r ? Math.round(r.height) : null,
        mediaVisible: r ? Math.round(Math.min(r.bottom, br.bottom)
                - Math.max(r.top, br.top)) : null};
    }""" % sel)


def test_A_live_fit_view(server):
    """Tall picture + portrait video: whole media visible, no
    vertical scroll; PDF preview unchanged (embed 52vh)."""
    client, base, proc, port, home = server
    sj = client.j("POST", "/api/setlink", {"name": "r36fit"})[1]
    folder = sj["folder"]
    from PIL import Image
    Image.new("RGB", (500, 2000), (40, 90, 180)).save(
        os.path.join(folder, "tall.png"))
    Image.new("RGB", (1200, 800), (180, 60, 40)).save(
        os.path.join(folder, "wide.jpg"))
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "testsrc=size=720x1280:rate=10:duration=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    os.path.join(folder, "portrait.mp4")], check=True)
    open(os.path.join(folder, "doc.pdf"), "wb").write(b"%PDF-1.4 fake\n")
    pw = _playwright()
    try:
        browser, ctx, pg = _host_page(pw, port, 1280, 800)
        try:
            pg.wait_for_selector(".frow", timeout=10000)
            # Tall picture (2.8.20: 505 of 2000px visible).
            pg.evaluate("() => previewFile('tall.png', 1000)")
            pg.wait_for_timeout(1200)
            m = _preview_measure(pg, "img")
            assert m["fit"] and m["boxW"] > 900, m
            assert m["scrollH"] <= m["clientH"], m
            assert m["mediaVisible"] == m["mediaH"], m
            pg.screenshot(path=os.path.join(PROOF, "r36_fit_tall.png"))
            pg.evaluate("() => document.querySelector('#previewclose')"
                        ".click()")
            pg.wait_for_timeout(400)
            assert not pg.evaluate(
                "() => document.querySelector('#previewpop')"
                ".classList.contains('fitmedia')")
            # Portrait video (2.8.20: 505 of 1081px visible).
            pg.evaluate("() => previewFile('portrait.mp4', 1000)")
            pg.wait_for_timeout(1500)
            m = _preview_measure(pg, "video")
            assert m["fit"] and m["boxW"] > 900, m
            assert m["scrollH"] <= m["clientH"], m
            assert m["mediaVisible"] == m["mediaH"], m
            pg.screenshot(path=os.path.join(PROOF, "r36_fit_video.png"))
            pg.evaluate("() => document.querySelector('#previewclose')"
                        ".click()")
            pg.wait_for_timeout(400)
            # Wide landscape picture also fits (sanity).
            pg.evaluate("() => previewFile('wide.jpg', 1000)")
            pg.wait_for_timeout(1000)
            m = _preview_measure(pg, "img")
            assert m["fit"] and m["scrollH"] <= m["clientH"], m
            assert m["mediaVisible"] == m["mediaH"], m
            pg.evaluate("() => document.querySelector('#previewclose')"
                        ".click()")
            pg.wait_for_timeout(400)
            # PDF UNCHANGED: no fitmedia, embed still 52vh.
            pg.evaluate("() => previewFile('doc.pdf', 100)")
            pg.wait_for_timeout(800)
            m3 = pg.evaluate("""() => {
              const e = document.querySelector('#previewbody embed');
              return {fit: document.querySelector('#previewpop')
                        .classList.contains('fitmedia'),
                embedH: e ? e.getBoundingClientRect().height : null,
                vh: window.innerHeight};
            }""")
            assert m3["fit"] is False, m3
            assert abs(m3["embedH"] / m3["vh"] - 0.52) < 0.02, m3
            pg.screenshot(path=os.path.join(PROOF, "r36_fit_pdf.png"))
            pg.evaluate("() => document.querySelector('#previewclose')"
                        ".click()")
            pg.wait_for_timeout(400)
            # Saved-file viewer: same fit for its img.
            pg.evaluate("() => showViewer('tall.png', "
                        "'<img src=\"/dl/tall.png?preview=1\">')")
            pg.wait_for_timeout(1200)
            mv = pg.evaluate("""() => {
              const box = document.querySelector('.vbox');
              const img = document.querySelector('#vcontent img');
              const r = img.getBoundingClientRect();
              const vr = document.querySelector('#vcontent')
                .getBoundingClientRect();
              return {scrollH: box.scrollHeight, clientH: box.clientHeight,
                imgH: Math.round(r.height),
                imgVisible: Math.round(Math.min(r.bottom, vr.bottom)
                  - Math.max(r.top, vr.top))};
            }""")
            assert mv["scrollH"] <= mv["clientH"], mv
            assert mv["imgVisible"] == mv["imgH"], mv
            pg.screenshot(path=os.path.join(PROOF, "r36_fit_viewer.png"))
        finally:
            browser.close()
    finally:
        pw.stop()


def _right_overflow(pg):
    return pg.evaluate("""() => {
      const W = window.innerWidth;
      const bad = [];
      document.querySelectorAll('body *').forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.right > W + 1) {
          const c = el.className;
          bad.push({tag: el.tagName,
            cls: String(c && c.baseVal !== undefined ? c.baseVal : c || '')
              .slice(0, 40),
            id: el.id || '', right: Math.round(r.right)});
        }
      });
      return {W: W, docScrollW: document.documentElement.scrollWidth,
        bodyScrollW: document.body.scrollWidth,
        bad: bad.slice(0, 10), badCount: bad.length};
    }""")


def test_B_live_no_horizontal_scroll_pc(server):
    """PC app (bridge faked): .pcapp set, overflow-x hidden, no
    element past the right edge -- host, sidebar open, Set Up open,
    at 1280x800 and 1024x768. Plain browser gets no .pcapp."""
    client, base, proc, port, home = server
    sj = client.j("POST", "/api/setlink", {"name": "r36pc"})[1]
    open(os.path.join(sj["folder"], "a.txt"), "wb").write(b"hi\n")
    pw = _playwright()
    try:
        for width, height in ((1280, 800), (1024, 768)):
            browser, ctx, pg = _host_page(pw, port, width, height,
                                          bridge=True)
            try:
                assert pg.evaluate(
                    "() => document.documentElement.classList"
                    ".contains('pcapp')")
                assert pg.evaluate(
                    "() => getComputedStyle(document.documentElement)"
                    ".overflowX") == "hidden"
                pg.wait_for_selector(".frow", timeout=10000)
                m = _right_overflow(pg)
                assert m["docScrollW"] <= m["W"] and m["badCount"] == 0, m
                pg.evaluate("() => openSidebar(true)")
                pg.wait_for_timeout(600)
                m = _right_overflow(pg)
                assert m["docScrollW"] <= m["W"] and m["badCount"] == 0, m
                pg.evaluate("() => openLinkWin()")
                pg.wait_for_timeout(600)
                m = _right_overflow(pg)
                assert m["docScrollW"] <= m["W"] and m["badCount"] == 0, m
                if width == 1280:
                    pg.screenshot(path=os.path.join(
                        PROOF, "r36_pc_setup_1280.png"))
            finally:
                browser.close()
        # Plain browser (no bridge): no .pcapp class.
        browser, ctx, pg = _host_page(pw, port, 1280, 800, bridge=False)
        try:
            assert not pg.evaluate(
                "() => document.documentElement.classList"
                ".contains('pcapp')")
        finally:
            browser.close()
    finally:
        pw.stop()


def _setup_labels(pg):
    return pg.evaluate("""() => {
      const out = {};
      for (const id of ['lkcurlabel', 'lkfolderlabel', 'lklinklabel',
                        'lkpwlabel', 'lkpermlabel']) {
        const el = document.getElementById(id);
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        out[id] = {text: el.textContent.trim(), color: cs.color,
          fontSize: cs.fontSize, marginBottom: cs.marginBottom,
          top: Math.round(r.top), left: Math.round(r.left),
          w: Math.round(r.width), h: Math.round(r.height)};
      }
      return out;
    }""")


def test_C_live_light_labels_dark_geometry_same(server):
    """Light mode: the five Set Up labels are dark (#1e293b);
    dark mode: still pale #aab9ed; every label's position/size
    is identical in both modes -- colour change only."""
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r36labels"})
    pw = _playwright()
    try:
        browser, ctx, pg = _host_page(pw, port, 1280, 800)
        try:
            pg.evaluate("() => openLinkWin()")
            pg.wait_for_timeout(600)
            pg.evaluate("() => document.documentElement.classList"
                        ".add('light')")
            pg.wait_for_timeout(400)
            light = _setup_labels(pg)
            pg.screenshot(path=os.path.join(PROOF, "r36_setup_light.png"))
            for lid, v in light.items():
                assert v["color"] == "rgb(30, 41, 59)", (lid, v)
            pg.evaluate("() => document.documentElement.classList"
                        ".remove('light')")
            pg.wait_for_timeout(400)
            dark = _setup_labels(pg)
            pg.screenshot(path=os.path.join(PROOF, "r36_setup_dark.png"))
            for lid, v in dark.items():
                assert v["color"] == "rgb(170, 185, 237)", (lid, v)
                for k in ("fontSize", "marginBottom", "top", "left",
                          "w", "h"):
                    assert light[lid][k] == dark[lid][k], \
                        (lid, k, light[lid], dark[lid])
            assert [light[i]["text"] for i in
                    ("lkcurlabel", "lkfolderlabel", "lklinklabel",
                     "lkpwlabel", "lkpermlabel")] == [
                "Current Address", "Folder For This Address",
                "New Address", "Password (Optional)", "Permissions"]
        finally:
            browser.close()
    finally:
        pw.stop()
