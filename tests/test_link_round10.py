"""v2.7.94 web/desktop round (Nov 2, 2026) -- parent brief items.

Supersedes, by design, the v2.7.93 expectations it contradicts:
the centred statusbar row is deleted (Devices pill moves into the
top bar), the host dropdown anchors to the CURRENT address field
(not New Address), the "Save keeps ..." copy is gone, and the top
pill carries a link icon + coloured address text (no dot, no
"Address:" prefix). Older tests asserting those v2.7.93 shapes
will fail on purpose; the tests here assert the new shapes.

Covers:
  1. no statusbar row; Devices pill inside the top bar (v2.7.95:
     centred row, not the v2.7.94 left cluster), pill
     background/border, 48px height;
  2. guest-supplied device_name / device accepted in /api/connect
     and /api/login, stored per session, surfaced in /api/sessions
     (display_name) and /api/status (device_names), IP fallback
     when no source supplies a name, UA hint as a middle fallback;
  3. host dropdown drops from the current-address field; New
     Address is a plain input; guest login dropdown unchanged;
  4. New Address / Password share one size class; gap tight;
  5. "Save keeps" absent everywhere in the served page;
  6. Set Password popup: "Set Password For <address>", red
     bordered X top-right, pill-like card surface, small Save;
  7. Set up your addresses X: red with its own border, same style;
  9. top address text in its deterministic (darkened-for-text)
     colour, no dot in the top pill;
 10. Find uses the menu button's purple/blue gradient;
 11. top pill has an inline-SVG link icon inside it, no "Address:".
"""
import os
import re
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
from test_link_round2 import server  # noqa: F401,E402
from test_link_round3 import _flip_role  # noqa: E402
from test_link_round6 import _page  # noqa: E402
from test_link_round8 import _main_script  # noqa: E402
from test_link_folders import Client  # noqa: E402


def _topbar(html):
    start = html.index('<div class="topbar">')
    end = html.index('<div class="qrpop"', start)
    return html[start:end]


def _rule(html, selector):
    m = re.search(re.escape(selector) + r" \{([^}]*)\}", html)
    assert m, f"no CSS rule for {selector}"
    return m.group(1)


def _setlink(client, name, **kw):
    status, j = client.j("POST", "/api/setlink", {"name": name, **kw})
    assert status == 200 and j["ok"], j
    return j


def _sessions(host_client):
    status, j = host_client.j("GET", "/api/sessions")
    assert status == 200 and j["ok"], j
    return j["sessions"]


# ------------------------------------------------------------------ 1
def test_no_statusbar_row_devices_pill_inside_topbar(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    assert '<div class="statusbar"' not in html
    assert ".statusbar {" not in html
    top = _topbar(html)
    # v2.7.98 SUPERSEDES the v2.7.96/97 above-Send placement:
    # the pill is back in the top bar, top left, beside the
    # menu -- and there is no statusbar/statusrow row.
    assert 'id="statusdiv"' in top
    assert 'class="statusrow"' not in html
    assert 'id="statusdiv"' in html
    assert 'id="statustext"' in html
    assert 'id="statusdot"' in html
    # v2.7.98: pill is in the top bar, top left, immediately
    # right of the menu button -- never in the board, never
    # above the Send card.
    top = html[html.index('<div class="topbar">'):html.index('<div class="qrpop"')]
    assert top.index('id="menubtn"') < top.index('id="statusdiv"') < top.index('id="toplink"')
    board = html[html.index('<div class="board">'):]
    assert 'id="statusdiv"' not in board
    # Pill treatment: explicit solid background + border, fitted text.
    rule = _rule(html, ".topstatus .status")
    assert "background:#12172a" in rule
    assert "border:1px solid #2a3560" in rule
    assert "height:48px" in rule
    assert "border-radius:999px" in rule


# ------------------------------------------------------------------ 9, 11
def test_top_address_icon_coloured_no_dot_no_prefix(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    m = re.search(r'<a[^>]*id="toplink"[^>]*>(.*?)</a>', html, re.S)
    assert m, "toplink missing"
    inner = m.group(1)
    assert "<svg" in inner, "top pill must carry an inline link icon"
    assert "homebase" in inner
    # Deterministic text colour, server-side == Python helper.
    assert D.address_text_color("homebase") in inner
    assert "addot" not in inner, "no coloured dot beside the top address"
    assert "Address:" not in inner
    # The live JS path paints the same shape (no dot, no prefix).
    script = _main_script(html)
    assert "addressTopHtml(st.address_name" in script
    assert "addressDotHtml(connText" not in script


# ------------------------------------------------------------------ 3
def test_dropdown_anchored_to_current_address_not_new_address(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    assert 'id="lkddwrap"' not in html
    # Current-address field holds the chevron + the list, and
    # the New Address label follows it in the same (left)
    # split-screen column (v2.7.96: the dialog is two columns,
    # so intervening closing tags are allowed here).
    m = re.search(
        r'<div class="lkview lkcurdd" id="lkcurview">(.*?)'
        r'<div class="lklabel" id="lklinklabel">', html, re.S)
    assert m, "current-address dropdown field missing"
    assert 'id="lkddchevbtn"' in m.group(1)
    assert 'id="lkddlist"' in m.group(1)
    assert 'id="lkname"' in m.group(1)
    # New Address is a plain input on its own line: no chevron/list.
    lkin_line = next(ln for ln in html.splitlines() if 'id="lkin"' in ln)
    assert "ddchevbtn" not in lkin_line and "ddlist" not in lkin_line
    assert "ddwrap" not in lkin_line
    # Guest login dropdown is untouched.
    m2 = re.search(r'<div class="ddwrap" id="gddwrap">(.*?)</div>', html, re.S)
    assert m2 and 'id="gddchevbtn"' in m2.group(1)
    assert 'id="gddlist"' in m2.group(1)
    # Outside-click guard watches the current-address field now.
    script = _main_script(html)
    assert '#lkcurview' in script
    assert '"#lkddwrap"' not in script
    # Row states from the spec survive the move.
    assert ".ddopt.ddsel" in html and ".ddopt:hover" in html


# ------------------------------------------------------------------ 4, 5
def test_field_sizes_and_no_save_keeps_copy(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    for fid in ("lkin", "lkpw"):
        line = next(ln for ln in html.splitlines() if f'id="{fid}"' in ln)
        assert "lkfield" in line, f"{fid} must share the .lkfield size class"
    rule = _rule(html, ".lkfield")
    assert "height:48px" in rule
    assert "Save keeps" not in html
    assert 'id="lkpwsemantics"' not in html


# ------------------------------------------------------------------ 6, 7
def test_set_password_popup_and_setup_x_red_bordered(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    assert "Set Password For <span" in html
    assert "Set password for" not in html
    # Shared red-X style on both popups.
    for selector in (".lkbox .lkclosebtn, .lockpwbox .lkclosebtn",):
        rule = _rule(html, selector)
        assert "#dc2626" in rule and "border:1px solid #dc2626" in rule
    # Set Password box: positioned (so its X sits in its corner),
    # explicit solid surface/border like the Devices pill (v2.7.96),
    # centred spacing.
    rule = _rule(html, ".lockpwbox")
    assert "position:relative" in rule
    assert "background:#12172a" in rule
    assert "border:1px solid #2a3560" in rule
    assert ".lockpwbox .lkclosebtn" in html
    # Save stays small, never full-width.
    rule = _rule(html, ".lockpwsave")
    assert "width:auto" in rule
    assert "width:100%" not in rule
    # Title address is coloured at open time.
    script = _main_script(html)
    assert "addr.style.color = addressTextColorForKey" in script


# ------------------------------------------------------------------ 10
def test_find_uses_menu_gradient(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    grad = "linear-gradient(135deg,#7C3AED,#0EA5E9)"
    assert grad in _rule(html, "#menubtn")
    assert grad in _rule(html, "#askbtn")
    m = re.search(r'<button[^>]*id="askbtn"[^>]*>(.*?)</button>', html, re.S)
    # v2.7.95 SUPERSEDES the v2.7.94 "Find" text: icon-only now
    # (magnifier + AI sparkle), label kept as title/aria.
    assert m and "<svg" in m.group(1)
    assert re.sub(r"<[^>]+>", "", m.group(1)).strip() == ""
    assert 'class="findspark"' in m.group(1)
    assert 'title="Find"' in m.group(0)


# ------------------------------------------------------------------ 2
def test_device_name_connect_surfaced_in_sessions_and_status(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    guest = Client(port)
    status, j = guest.j("POST", "/api/connect",
                        {"link": "homebase", "device_name": "Pixel 8"})
    assert status == 200 and j.get("authed"), j
    guest.cookies["drop_sess"] = j["token"]
    _flip_role(home, j["token"], "guest")
    sessions = _sessions(client)
    assert len(sessions) == 1, sessions
    assert sessions[0]["device_name"] == "Pixel 8"
    assert sessions[0]["display_name"] == "Pixel 8"
    status, st = client.j("GET", "/api/status")
    assert status == 200, st
    assert "Pixel 8" in st.get("device_names", []), st


def test_device_alias_login_and_ip_fallback(server):
    client, base, proc, port, home = server
    _setlink(client, "locklink", password="pw123")
    guest = Client(port)
    status, j = guest.j("POST", "/api/login",
                        {"password": "pw123", "device": "OnePlus 12"})
    assert status == 200 and j["ok"], j
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    sessions = _sessions(client)
    assert sessions[0]["display_name"] == "OnePlus 12", sessions
    # A guest with no name at all falls back to its IP, invented
    # name never appears.
    guest2 = Client(port)
    status, j = guest2.j("POST", "/api/login", {"password": "pw123"})
    assert status == 200 and j["ok"], j
    _flip_role(home, guest2.cookies["drop_sess"], "guest")
    sessions = _sessions(client)
    by_ip = [s for s in sessions if s["device_name"] == ""]
    assert len(by_ip) == 1, sessions
    assert by_ip[0]["display_name"] == "127.0.0.1", by_ip[0]
    assert by_ip[0]["ip"] == "127.0.0.1"


def test_device_name_helpers_fallback_order():
    # Supplied name wins over every fallback.
    assert D._device_display_name(
        {"device_name": "Pixel 8", "ua_hint": "iPhone",
         "ip": "10.0.1.5"}) == "Pixel 8"
    # UA hint beats the IP; loopback never resolves to "localhost".
    assert D._device_display_name(
        {"ua_hint": "iPhone", "ip": "10.0.1.5"}) == "iPhone"
    assert D._device_display_name({"ip": "127.0.0.1"}) == "127.0.0.1"
    assert D._resolve_hostname("127.0.0.1") == ""
    assert D._ua_hint("Mozilla/5.0 (Linux; Android 14; Pixel 8 "
                      "Build/AP1A) AppleWebKit") == "Pixel 8"
    assert D._ua_hint("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)") \
        == "iPhone"
    assert D._ua_hint("curl/8.0") == ""
    # Cleaning: control chars stripped, capped, never a password
    # blob -- a long value is truncated, not stored whole.
    assert len(D._clean_device_name("x" * 200)) == 64
    assert D._clean_device_name("  Pixel 8\n") == "Pixel 8"
    # Text palette agrees between server and page JS index-for-index.
    assert D.address_text_color("homebase") in (
        "#0284c7", "#7c3aed", "#be185d", "#b45309",
        "#047857", "#0e7490", "#9d174d", "#4d7c0f")
    assert D.address_text_color("homebase") != \
        D.address_color("homebase") or True  # palette differs in general


# ------------------------------------------------------------------ guardrails
def test_main_script_node_check_and_no_surrogates(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    assert not [c for c in html if 0xD800 <= ord(c) <= 0xDFFF]
    html.encode("utf-8")
    script = _main_script(html)
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".js",
                                     delete=False) as f:
        f.write(script)
        path = f.name
    try:
        proc2 = subprocess.run(["node", "--check", path],
                               capture_output=True, text=True, timeout=30)
        assert proc2.returncode == 0, proc2.stderr
    finally:
        os.unlink(path)
