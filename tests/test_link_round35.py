"""v2.8.19 fix round (Essef Nov 5) -- web/desktop only.

(1) LABEL REVERT: "No devices connected to this address" ->
    plain "No devices connected" everywhere in the web page
    (pill markup + all JS spots). The 2.8.18 "to this address"
    addition is dropped -- Essef never asked for it. The
    condition for showing it is unchanged.
(2) SHARED FILES THUMBNAILS, LIGHT MODE: file-type icons were
    emoji, which render as solid BLACK glyphs in environments
    without a colour-emoji font (the desktop pywebview window),
    so thumbnails were unreadable black blobs on the light
    tile. iconFor/badgeFor/thumbFallback now return classic
    inline SVG icons (feather-style strokes, one colour per
    type) that render identically in both themes; light-mode
    tile stays #eef2f7 with a coloured icon on it.
(3) DARK MODE: the file-type text labels on thumbnails
    (PDF / DOCX / CTFB / SIG ...) are WHITE.
(4) SAVED BUTTON ICON, CLASSIC: the login "Saved on this
    phone" button and the Shared Files "Saved" button use a
    classic download-arrow SVG -- no phone emoji/icon anywhere
    on those buttons (the Files one was U+1F4F2, the login one
    a phone-outline SVG).
(5) THEME TOGGLE ON LOGIN MUST NOT LOG IN: the login theme
    toggle is a <button type="button"> whose handler only
    switches the theme (preventDefault + stopPropagation);
    there is no <form> on the page and no Connect path from
    the button. Live-verified: tapping it on the login screen
    leaves the guest on the login screen, theme switched, no
    /api/connect issued (open + locked address, mouse + touch).
(6) SHARE TEXT BOX RESTORED: #msendtext min-height back to
    its pre-2.8.18 52px (2.8.18 shrank it to 46px); nothing
    else about the box changes.
"""
import ast
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
from test_link_round34 import _Fwd  # noqa: E402

PAGE = D.PAGE
SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py"),
           encoding="utf-8").read()

NO_DEV = "No devices connected"
OLD_NO_DEV = "No devices connected to this address"

# Classic download-arrow SVG shared by both Saved buttons
# (feather "download": tray + down arrow).
DL_PATH = "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"


def _css_rule(page, selector):
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", page)
    assert m, selector + " rule missing"
    return m.group(1)


def test_version_is_2_8_21():
    # Version pin follows the current build (2.8.21; was 2.8.19
    # when this round was written).
    assert D.VERSION == "2.8.21"


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
        with open("/tmp/r35_script_%d.js" % i, "w",
                  encoding="utf-8") as fh:
            fh.write(js)
        out = subprocess.run(["node", "--check",
                              "/tmp/r35_script_%d.js" % i],
                             capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr


# ---- (1) label revert ------------------------------------------------

def test_1_no_devices_label_reverted():
    assert OLD_NO_DEV not in PAGE
    assert NO_DEV in PAGE
    # pill markup + 6 JS spots (same count as 2.8.18's test_3).
    assert PAGE.count(NO_DEV) >= 7
    assert "No Devices Connected" not in PAGE


# ---- (2) light-mode thumbnails: SVG icons, never emoji ---------------

def test_2_file_icons_are_svg_not_emoji():
    # Scope the ban to the icon code itself: emoji still appear
    # elsewhere in the page for unrelated UI (e.g. the
    # translate "🌐 English" button), so check the three
    # functions that draw file thumbnails, not the whole PAGE.
    icon_seg = SRC[SRC.index("function _ficSvg("):
                   SRC.index("function thumbFor(")]
    for emo in ("🖼️", "🎬", "🎵", "📦", "📕", "📘", "📗", "📙",
                "🌐", "💻", "📝", "📄"):
        assert emo not in icon_seg, emo
    # iconFor returns an SVG per type; thumbFallback reuses it.
    assert "function iconFor(n)" in PAGE
    assert "_ficSvg(" in PAGE
    assert 's.innerHTML = iconFor(' in PAGE
    # Per-type colours (readable on the dark tile #090c15 and
    # the light tile #eef2f7 alike).
    for colour in ("#ef4444", "#3b82f6", "#16a34a", "#ea580c",
                   "#0284c7", "#8b5cf6", "#db2777", "#d97706",
                   "#0891b2", "#7c3aed", "#64748b"):
        assert colour in PAGE, colour
    # Light-mode tile background unchanged.
    assert "#eef2f7" in _css_rule(PAGE, "html.light .thwrap .fic")
    # Badges for image/video/audio are small SVGs, not emoji.
    assert "function _badgeSvg(" in PAGE
    assert PAGE.count("_badgeSvg(_FIC_") == 3


# ---- (3) dark-mode file-type text is white ---------------------------

def test_3_dark_mode_badge_label_white():
    rule = _css_rule(PAGE, ".tbadge.tlabel")
    assert "color:#ffffff" in rule.replace(" ", ""), rule
    # Light mode keeps its dark-blue label on the light badge.
    # (Two light rules exist; the later one wins the cascade.)
    light_rules = re.findall(
        r"html\.light \.tbadge\.tlabel\s*\{([^}]*)\}", PAGE)
    assert light_rules, "no light tbadge.tlabel rule"
    assert "#0369a1" in light_rules[-1], light_rules


# ---- (4) classic Saved icon, no phone --------------------------------

def test_4_saved_buttons_classic_download_icon():
    assert "1F4F2" not in PAGE  # U+1F4F2 mobile-phone emoji
    assert "📲" not in PAGE and "📱" not in PAGE
    # Login "Saved on this phone": download-arrow SVG, no phone
    # outline (rect x=7 y=2 w=10 h=20).
    m = re.search(r'id="gsavedbtn"[^>]*>(.*?)</button>', PAGE, re.S)
    assert m, "gsavedbtn missing"
    assert DL_PATH in m.group(1), m.group(1)[:200]
    assert "M21 15v4" in m.group(1)
    assert '<rect x="7" y="2" width="10" height="20"' not in m.group(1)
    # Shared Files "Saved" button (server-rendered, mobile web).
    m2 = re.search(r'id="msavedbtn"[^>]*>(.*?)</button>', SRC, re.S)
    assert m2, "msavedbtn missing"
    assert DL_PATH in m2.group(1), m2.group(1)[:200]
    assert "1F4F2" not in m2.group(1)


# ---- (5) login theme toggle never logs in ----------------------------

def test_5_login_theme_toggle_is_inert_button():
    # type="button" on all three theme switches (never a submit).
    for tid in ("themeswLogin", "themesw", "themesw2"):
        m = re.search(r'<button[^>]*id="%s"[^>]*>' % tid, PAGE)
        assert m, tid + " missing"
        assert 'type="button"' in m.group(0), m.group(0)
    # The login toggle's only handler: stop the tap dead, then
    # applyTheme. No doGuestLogin / checkAuth / /api/connect in
    # its neighbourhood.
    i = PAGE.index('const themeswLogin = $("#themeswLogin");')
    seg = PAGE[i:i + 500]
    assert 'addEventListener("click"' in seg, seg
    assert "preventDefault" in seg and "stopPropagation" in seg
    assert "applyTheme(" in seg
    assert "doGuestLogin" not in seg and "checkAuth" not in seg
    assert "/api/connect" not in seg
    # No <form> element anywhere on the page, so no implicit
    # submit (a comment may mention the word; match a real tag).
    assert not re.search(r"<form[\s>]", PAGE)


def test_5_live_login_toggle_does_not_connect(server):
    """Guest on the login page taps the theme toggle (touch):
    stays on login, theme switches, no /api/connect issued."""
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r35addr"})
    fwd = _Fwd(port)
    guest_url = "http://127.0.0.3:%d/" % fwd.port
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    try:
        ctx = browser.new_context(
            viewport={"width": 390, "height": 844}, has_touch=True,
            is_mobile=True,
            user_agent="Mozilla/5.0 (Linux; Android 14; Pixel 8) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0 Mobile Safari/537.36")
        pg = ctx.new_page()
        seen = []
        pg.on("request", lambda r: seen.append(r.url)
              if "/api/connect" in r.url else None)
        pg.goto(guest_url)
        pg.wait_for_function(
            "() => !document.querySelector('#guestlogin')"
            ".classList.contains('open')", timeout=10000)
        pg.wait_for_timeout(800)
        pg.click("#mpcdisconnect")
        pg.wait_for_function(
            "document.querySelector('#guestlogin')"
            ".classList.contains('open')", timeout=10000)
        pg.wait_for_timeout(800)
        # The boot auto-connect on an open address legitimately
        # calls /api/connect once (designed sessionless-open
        # mint); only calls AFTER this point count against the
        # toggle.
        seen.clear()
        before = pg.evaluate(
            "() => document.documentElement.classList.contains"
            "('light') ? 'light' : 'dark'")
        assert before == "dark"
        box = pg.locator("#themeswLogin").bounding_box()
        pg.touchscreen.tap(box["x"] + box["width"] / 2,
                           box["y"] + box["height"] / 2)
        pg.wait_for_timeout(1000)
        st = pg.evaluate(
            "() => ({loginOpen: document.querySelector('#guestlogin')"
            ".classList.contains('open'), theme: document."
            "documentElement.classList.contains('light') "
            "? 'light' : 'dark'})")
        assert st["loginOpen"] is True, st
        assert st["theme"] == "light", st
        pg.wait_for_timeout(7000)  # past one 5s poll
        st = pg.evaluate(
            "() => ({loginOpen: document.querySelector('#guestlogin')"
            ".classList.contains('open'), theme: document."
            "documentElement.classList.contains('light') "
            "? 'light' : 'dark'})")
        assert st["loginOpen"] is True, st
        assert st["theme"] == "light", st
        assert not [u for u in seen if "/api/connect" in u], seen
    finally:
        browser.close()
        pw.stop()
        fwd.close()


# ---- (6) Share Text box size ---------------------------------------
# 2.8.20 item 7 superseded the 2.8.19 52px restoration: the box is
# now BIGGER (min-height 110px, rows 5) with its own scroller --
# see round36 test_7. This keeps the "no shrinkage" guard, just
# at the new intentional size.

def test_6_send_text_box_restored_to_52px():
    rule = _css_rule(PAGE, "#msendtext")
    assert "min-height:110px" in rule.replace(" ", ""), rule
    assert "min-height:52px" not in rule.replace(" ", "")
    assert '<textarea id="msendtext" rows="5"' in PAGE


def test_live_files_light_svg_icons_and_white_dark_labels(server):
    """Shared Files tab: SVG icons in light mode, white badge
    text in dark mode, classic Saved icon -- measured live."""
    client, base, proc, port, home = server
    sj = client.j("POST", "/api/setlink", {"name": "r35files"})[1]
    folder = sj["folder"]
    assert os.path.isdir(folder), sj
    for name, data in (("test.pdf", b"%PDF-1.4 fake\n"),
                       ("report.docx", b"PK fake\n"),
                       ("notes.txt", b"hello\n"),
                       ("data.ctfb", b"ctfb\n"),
                       ("file.sig", b"sig\n")):
        open(os.path.join(folder, name), "wb").write(data)
    fwd = _Fwd(port)
    guest_url = "http://127.0.0.3:%d/" % fwd.port
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    try:
        ctx = browser.new_context(viewport={"width": 390, "height": 844})
        pg = ctx.new_page()
        pg.goto(guest_url)
        pg.wait_for_function(
            "() => !document.querySelector('#guestlogin')"
            ".classList.contains('open')", timeout=10000)
        pg.wait_for_timeout(1200)
        pg.click('.mtab[data-tab="files"]')
        pg.wait_for_timeout(1000)
        rows = pg.evaluate(
            "() => [...document.querySelectorAll('.frow')].map(r => ({"
            "name: r.querySelector('.fname')?.textContent, "
            "svg: !!r.querySelector('.thwrap .fic svg'), "
            "stroke: r.querySelector('.thwrap .fic svg')"
            "?.getAttribute('stroke')}))")
        assert len(rows) == 5, rows
        by_name = {r["name"]: r for r in rows}
        assert by_name["test.pdf"] == {"name": "test.pdf", "svg": True,
                                       "stroke": "#ef4444"}, rows
        assert by_name["report.docx"]["stroke"] == "#3b82f6", rows
        assert by_name["notes.txt"]["stroke"] == "#64748b", rows
        # Dark mode: badge text white.
        dark = pg.evaluate(
            "() => [...document.querySelectorAll('.tbadge.tlabel')]"
            ".map(el => getComputedStyle(el).color)")
        assert dark and all(c == "rgb(255, 255, 255)" for c in dark), dark
        # Light mode: coloured SVG on the light tile, never black.
        pg.evaluate("() => document.documentElement.classList"
                    ".add('light')")
        pg.wait_for_timeout(400)
        light = pg.evaluate(
            "() => [...document.querySelectorAll('.thwrap .fic')].map("
            "el => ({bg: getComputedStyle(el).backgroundColor, "
            "stroke: el.querySelector('svg')"
            "?.getAttribute('stroke')}))")
        assert all(x["bg"] == "rgb(238, 242, 247)" and
                   x["stroke"] not in (None, "#000000", "#090c15")
                   for x in light), light
        # Classic Saved icon on the Files tab button.
        sb = pg.evaluate(
            "() => ({svg: !!document.querySelector('#msavedbtn svg'), "
            "phone: /1F4F2|📲|📱/.test(document.querySelector"
            "('#msavedbtn').innerHTML)})")
        assert sb == {"svg": True, "phone": False}, sb
        # Pill label is the plain reverted text.
        assert pg.evaluate(
            "() => document.querySelector('#statustext')"
            ".textContent") == "No devices connected"
    finally:
        browser.close()
        pw.stop()
        fwd.close()
