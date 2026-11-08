"""v2.7.95 web/desktop round (Nov 2, 2026) -- parent brief items
from Essef's feedback on v2.7.94 screenshots.

Supersedes, by design, the v2.7.94 expectations it contradicts
(those assertions were updated in place in the older files and
are listed in the round-11 report):
  - the Devices pill sat left next to the menu icon; it is now
    CENTRED. It cannot share row 1 with the Address pill, which
    is absolutely centred in row 1, so it sits centred on its
    own line INSIDE .topbar (.statusrow) -- capped at the Shared
    Texts card width (340px), text centred, pill styling kept.
  - the Find button carried the text "Find"; it is now icon-only
    (magnifier + AI sparkle), tooltip/aria label still "Find".
  - the disconnect section sat below Save (below the fold); it
    now sits at the TOP of Set Up Your Addresses.
  - several dialog labels were sentence-case; both windows are
    now Title Case (the address value itself is never re-cased).

Covers:
  1. Devices pill: centred .statusrow inside .topbar, max-width
     340px == Shared Texts (.col) width, centred text, pill
     background/border from theme vars, Address pill still
     anchored to row 1 (top:24px, not the whole bar's centre).
  2. Find button: no visible "Find" text, magnifier icon with
     AI gradient + .findspark accent, label "Find" kept.
  3. Disconnect options: present at the top of the dialog,
     dialog scrollable, per-device Disconnect + Disconnect All
     Guests work end to end on open AND password addresses,
     host-only (guest attempts are refused).
  4. Title Case in Set Up Your Addresses and the Set Password
     popup; the address value is inserted verbatim.
  5. Set Password popup background/border match the Devices
     pill (same theme vars); popup centred, small Save, red
     bordered X, animated eye, lock-cycle logic untouched.
"""
import os
import re
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


def _guest_open(port, home, name):
    guest = Client(port)
    status, j = guest.j("POST", "/api/connect",
                        {"link": "homebase", "device_name": name})
    assert status == 200 and j.get("authed"), j
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    return guest


def _guest_locked(port, home, password, name):
    guest = Client(port)
    status, j = guest.j("POST", "/api/login",
                        {"password": password, "device_name": name})
    assert status == 200 and j["ok"], j
    guest.cookies["drop_locked"] = "1"
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    return guest


# ------------------------------------------------------------------ 1
def test_devices_pill_centred_capped_in_topbar(server):
    # v2.7.96 SUPERSEDES the v2.7.95 top-bar row: the pill now
    # sits ABOVE THE SEND CARD, centred on it, and is gone from
    # the top bar. Full assertions live in test_link_round12.
    client, base, proc, port, home = server
    assert D.VERSION == "2.7.98"
    _setlink(client, "homebase")
    html = _page(port, client)
    assert '<div class="statusbar"' not in html
    top = _topbar(html)
    # v2.7.98: pill is back in the top bar, top left,
    # immediately right of the menu button, left of the
    # centred Address pill -- never above the Send card.
    assert top.index('id="menubtn"') < top.index('id="statusdiv"') < top.index('id="toplink"')
    assert 'class="statusrow"' not in html
    assert 'class="sendwrap"' not in html
    board = html[html.index('<div class="board">'):]
    assert 'id="statusdiv"' not in board
    # Cards keep the standalone .col width (340px).
    _col = re.search(r"\n  \.col \{([^}]*)\}", html)
    assert _col and "width:340px" in _col.group(1)
    rule = _rule(html, ".topstatus .status")
    assert "background:#12172a" in rule
    assert "border:1px solid #2a3560" in rule
    assert "border-radius:999px" in rule
    assert "height:48px" in rule
    # Address pill is centred on the single-row top bar again.
    assert "top:50%" in _rule(html, ".connectwrap")


# ------------------------------------------------------------------ 2
def test_find_button_icon_only_ai_sparkle(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    m = re.search(r'<button[^>]*id="askbtn"[^>]*>(.*?)</button>', html, re.S)
    assert m, "askbtn missing"
    inner = m.group(1)
    visible = re.sub(r"<[^>]+>", "", inner).strip()
    assert visible == "", f"Find button must be icon-only, got {visible!r}"
    assert "Find" not in visible
    assert 'class="findglass"' in inner and "<svg" in inner
    assert 'class="findspark"' in inner, "AI sparkle accent missing"
    assert 'title="Find"' in m.group(0)
    assert 'aria-label="Find"' in m.group(0)
    # Menu gradient + glow, icon-only square sizing.
    grad = "linear-gradient(135deg,#7C3AED,#0EA5E9)"
    assert grad in _rule(html, "#menubtn")
    assert grad in _rule(html, "#askbtn")
    # v2.7.96: same box as the menu button (36px), not 48px.
    assert "width:36px" in _rule(html, "#askbtn")
    assert "height:36px" in _rule(html, "#askbtn")
    assert "width:16px" in _rule(html, "#askbtn .findglass")
    # The other Find labels (tab, column head) are untouched:
    # only the top-bar button went icon-only.
    assert 'data-tab="ask"' in html


# ------------------------------------------------------------------ 3
def test_disconnect_section_at_top_of_setup_dialog(server):
    # v2.7.96 SUPERSEDES the v2.7.95 top placement: Devices is
    # back at the BOTTOM, after everything (full assertions in
    # test_link_round12).
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    lk = html[html.index('id="lkwrap"'):html.index('id="lockpwpop"')]
    # Devices section sits below Current Address AND below Save.
    assert lk.index('id="lksesslabel"') > lk.index('id="lkcurlabel"')
    assert lk.index('id="lksess"') < lk.index('id="lksessall"')
    assert lk.index('id="lksessall"') > lk.index('id="lkcurlabel"')
    assert lk.index('id="lksessall"') > lk.index('id="lkset"')
    assert 'id="lksesslabel" style="display:none">Devices On This Address' in lk
    assert 'id="lksessall" style="display:none">Disconnect All Guests<' in lk
    # Dialog scrolls; a long device list scrolls inside it.
    lockbox = _rule(html, ".lockbox")
    assert "max-height:92vh" in lockbox and "overflow:auto" in lockbox
    sess_rule = _rule(html, "#lksess")
    assert "max-height:180px" in sess_rule
    assert "overflow-y:auto" in sess_rule
    # JS wiring: host-only section, per-device Disconnect rows,
    # Disconnect All Guests posts all_guests.
    script = _main_script(html)
    assert "paintSessions()" in script
    assert 'data-sess="' in script
    assert ">Disconnect</button>" in script
    assert '"/api/sessions/revoke", {all_guests: true}' in script


def test_disconnect_end_to_end_open_address(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    _guest_open(port, home, "Pixel 8")
    _guest_open(port, home, "iPhone")
    sessions = _sessions(client)
    guests = [s for s in sessions if s["role"] == "guest"]
    assert len(guests) == 2, sessions
    assert {s["display_name"] for s in guests} == {"Pixel 8", "iPhone"}
    # Per-device disconnect removes exactly that device.
    first = next(s for s in guests if s["display_name"] == "Pixel 8")
    status, j = client.j("POST", "/api/sessions/revoke",
                         {"id": first["id"]})
    assert status == 200 and j["revoked"] == 1, j
    rest = [s for s in _sessions(client) if s["role"] == "guest"]
    assert [s["display_name"] for s in rest] == ["iPhone"]
    # Disconnect-all clears the rest, on an open address.
    status, j = client.j("POST", "/api/sessions/revoke",
                         {"all_guests": True})
    assert status == 200 and j["ok"], j
    assert "All guests disconnected" in j["message"]
    assert [s for s in _sessions(client) if s["role"] == "guest"] == []


def test_disconnect_end_to_end_password_address_host_only(server):
    client, base, proc, port, home = server
    _setlink(client, "locklink", password="pw123")
    guest_a = _guest_locked(port, home, "pw123", "Pixel 8")
    _guest_locked(port, home, "pw123", "iPhone")
    sessions = _sessions(client)
    guests = [s for s in sessions if s["role"] == "guest"]
    assert len(guests) == 2, sessions
    # A guest may not disconnect anyone (host-only, 403).
    status, j = guest_a.j("POST", "/api/sessions/revoke",
                          {"all_guests": True})
    assert status == 403 and j.get("code") == "host_only", (status, j)
    status, j = guest_a.j("GET", "/api/sessions")
    assert status == 403, (status, j)
    assert len([s for s in _sessions(client)
                if s["role"] == "guest"]) == 2
    # Host per-device, then disconnect-all, on a password address.
    first = guests[0]
    status, j = client.j("POST", "/api/sessions/revoke",
                         {"id": first["id"]})
    assert status == 200 and j["revoked"] == 1, j
    assert len([s for s in _sessions(client)
                if s["role"] == "guest"]) == 1
    status, j = client.j("POST", "/api/sessions/revoke",
                         {"all_guests": True})
    assert status == 200 and j["ok"], j
    assert [s for s in _sessions(client) if s["role"] == "guest"] == []


# ------------------------------------------------------------------ 4
def test_title_case_both_windows_address_value_verbatim(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    lk = html[html.index('id="lkwrap"'):html.index('id="lockpwpop"')]
    for label in ("Set Up Your Addresses", "Current Address",
                  "New Address", "Password (Optional)",
                  "Folder For This Address", "Open Folder",
                  "Change Folder", "Devices On This Address",
                  "Disconnect All Guests",
                  "Unlock With This Password"):
        assert label in lk, label
    for old in (">Current address<", ">New address<",
                "Password (optional)", "Folder for this address",
                ">Open folder<", ">Change folder<",
                "Devices on this address", "Disconnect all guests",
                "Set up your addresses"):
        assert old not in lk, old
    # NB: the first <script> in the page is the <head> theme
    # bootstrap, which sits BEFORE the popup -- search forward.
    lp = html[html.index('id="lockpwpop"'):
              html.index("<script>", html.index('id="lockpwpop"'))]
    assert "Set Password For <span" in lp
    assert 'placeholder="Password For This Address"' in lp
    assert "Password for this address" not in lp
    assert "Set password for" not in lp
    # JS-set labels/placeholders (host + guest modes) match.
    script = _main_script(html)
    for s in ('"New Address"', '"Address To Connect To"',
              '"Password (Optional)"', '"Set A Password (Optional)"',
              '"Password For This Address"'):
        assert s in script, s
    for s in ('"New address"', '"Address to connect to"',
              '"Password (optional)"', '"Set a password (optional)"',
              '"Password for this address"'):
        assert s not in script, s
    # The address VALUE is inserted verbatim -- no re-casing.
    assert 'addr.textContent = AUTH.address_name || ""' in script
    assert "toUpperCase" not in script.split("function openLockPopup")[1] \
        .split("function ")[0]


# ------------------------------------------------------------------ 5
def test_set_password_popup_matches_devices_pill(server):
    # v2.7.96: both use the same EXPLICIT solid surface/border
    # (dark #12172a / #2a3560), not a bare theme var.
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    pill = _rule(html, ".topstatus .status")
    popup = _rule(html, ".lockpwbox")
    for token in ("background:#12172a", "border:1px solid #2a3560"):
        assert token in pill, token
        assert token in popup, token
    assert "position:relative" in popup
    # Popup stays centred, Save small, red bordered X.
    pop = _rule(html, ".lockpwpop")
    assert "align-items:center" in pop and "justify-content:center" in pop
    save = _rule(html, ".lockpwsave")
    assert "width:auto" in save and "width:100%" not in save
    xrule = _rule(html, ".lkbox .lkclosebtn, .lockpwbox .lkclosebtn")
    assert "#dc2626" in xrule and "border:1px solid #dc2626" in xrule
    # Animated eye + lock-cycle logic untouched.
    script = _main_script(html)
    assert "lockpweye" in script and "paintEyeBtn" in script
    assert "eyesnap" in html
    # Lock cycle untouched: lock icon posts /api/addresslock;
    # first lock with no stored password opens the popup
    # (server refuses that lock with error no_password).
    assert "/api/addresslock" in script
    assert "openLockPopup" in script
    assert "if(AUTH.has_password)" in script
    import pathlib
    assert '"no_password"' in pathlib.Path(D.__file__).read_text()
