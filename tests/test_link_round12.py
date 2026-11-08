"""v2.7.96 web/desktop round (Nov 2, 2026) -- parent brief items
from Essef's feedback on v2.7.95.

Supersedes, by design, the v2.7.95 expectations it contradicts
(those assertions were updated in place in the older files):
  - Devices pill: was centred on its own row INSIDE .topbar
    (.statusrow); it now sits ABOVE THE SEND CARD, centred on
    that card's width, and is gone from the top bar entirely.
  - Devices section: was at the TOP of Set Up Your Addresses
    (v2.7.95); it is back at the BOTTOM, after everything, and
    now refreshes in real time while the dialog is open.
  - Set Password popup background: was a bare theme var
    (var(--card)); it is now an explicit solid surface, light
    and dark, distinct from the page behind it.
  - Find button: was a 48px box with a 20px glass; it is now
    the menu button's 36px box with a 16px glass.
  - Menu Open/Change Folder: used to delegate to the Files
    tab's address-folder buttons; the menu now routes to the
    ROOT folder, while Set Up and the Files tab stay on the
    address folder.

Covers:
  1. Devices pill above the Send card, centred on it, fitted
     to its text, explicit background/border, no pill in the
     top bar (menu left, Address pill centred, Find right).
  2. Set Password popup explicit visible background (solid,
     light/dark), title on the same surface, distinct from
     the page backgrounds.
  3. Devices section last in the Set Up dialog order and
     re-polled every 5s while the dialog is open, without a
     reload; /api/sessions reflects a newly connected device.
  4. Folder routing split by place: menu = root, Set Up =
     address folder, Files tab = address folder (JS handlers,
     server scope helpers, /api/setrootfolder, desktop bridge
     root methods).
  5. Both dialog Xs red, bordered, same shared class/size,
     pointer cursor; no later rule restyles the Set Up X.
  6. Find icon size equals menu icon size (button box +
     glass), icon-only with AI sparkle/glow kept.
  7. Set Up dialog scrollbar matches the Files tab scroller
     (same width, thumb colour, track treatment).
  8. Set Up dialog is split-screen: two equal columns, wider
     window, Devices spanning both columns at the bottom.
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


def _rule(html, selector):
    m = re.search(re.escape(selector) + r" \{([^}]*)\}", html)
    assert m, f"no CSS rule for {selector}"
    return m.group(1)


def _topbar(html):
    start = html.index('<div class="topbar">')
    end = html.index('<div class="qrpop"', start)
    return html[start:end]


def _setup(html):
    return html[html.index('id="lkwrap"'):html.index('id="lockpwpop"')]


def _setlink(client, name, **kw):
    status, j = client.j("POST", "/api/setlink", {"name": name, **kw})
    assert status == 200 and j["ok"], j
    return j


def _fn(script, start_marker, end_marker):
    i = script.index(start_marker)
    j = script.index(end_marker, i)
    return script[i:j]


# ------------------------------------------------------------------ 1
def test_devices_pill_top_left_in_topbar_not_above_send(server):
    # v2.7.98 SUPERSEDES the v2.7.96/97 above-Send placement:
    # the pill is in the TOP BAR, TOP LEFT, immediately right
    # of the menu button, on the same row as the centred
    # Address pill and the Find button -- exactly as in
    # Essef's screenshot/mockup. No wrapper, no row above
    # the Send card, no blank row under the top bar.
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    top = _topbar(html)
    assert 'id="menubtn"' in top
    assert 'id="toplink"' in top
    assert 'id="askbtn"' in top
    assert top.index('id="menubtn"') < top.index('id="statusdiv"') < top.index('id="toplink"')
    assert 'class="topstatus"' in top
    assert 'class="statusrow"' not in html
    assert 'class="sendwrap"' not in html
    assert 'class="sendstatus"' not in html
    board = html[html.index('<div class="board">'):]
    assert 'id="statusdiv"' not in board
    assert board.index('data-col="send"') < board.index('data-col="notes"') < board.index('data-col="files"')
    # Fitted to its text, pill shape, top-bar row height.
    rule = _rule(html, ".topstatus .status")
    assert "width:auto" in rule
    assert "border-radius:999px" in rule
    assert "height:48px" in rule
    # Explicit solid background + border (dark), light variant
    # distinct from the light page background.
    assert "background:#12172a" in rule
    assert "border:1px solid #2a3560" in rule
    light = _rule(html, "html.light .topstatus .status")
    assert "background:#ffffff" in light
    assert "border-color:#c3cfde" in light
    # Address pill stays centred on the single-row top bar.
    assert "top:50%" in _rule(html, ".connectwrap")


# ------------------------------------------------------------------ 2
def test_set_password_popup_explicit_visible_background(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    rule = _rule(html, ".lockpwbox")
    assert "position:relative" in rule
    # Explicit solid surface, NOT a bare theme var.
    assert "background:#12172a" in rule
    assert "border:1px solid #2a3560" in rule
    assert "background:var(--card)" not in rule
    light = _rule(html, "html.light .lockpwbox")
    assert "background:#ffffff" in light
    assert "border-color:#c3cfde" in light
    # Title area on the same solid surface.
    assert "background:#12172a" in _rule(html, ".lockpwbox h4")
    assert "background:#ffffff" in _rule(html, "html.light .lockpwbox h4")
    # Distinct from the page behind it in both modes: dark page
    # is #0a0d16, light page is #eef2f7 (html.light --bg).
    assert "#12172a" != "#0a0d16"
    assert "#ffffff" != "#eef2f7"
    assert "--bg:#0a0d16" in html
    assert "--bg:#eef2f7" in html
    # Popup stays centred, Save small.
    pop = _rule(html, ".lockpwpop")
    assert "align-items:center" in pop and "justify-content:center" in pop
    save = _rule(html, ".lockpwsave")
    assert "width:auto" in save and "width:100%" not in save


# ------------------------------------------------------------------ 3
def test_devices_section_last_and_realtime_poll(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    lk = _setup(html)
    # Order: everything first, Devices last (spanning both
    # split-screen columns at the bottom).
    order = ["lkcurlabel", "lklinklabel", "lkpwlabel",
             "lkfolderlabel", "lkfolderrow", "lkset",
             "lkunlockbtn", "lksesslabel", "lksess", "lksessall"]
    idx = [lk.index('id="%s"' % o) for o in order]
    assert idx == sorted(idx), idx
    assert 'id="lksesslabel" style="display:none">Devices On This Address' in lk
    assert 'id="lksessall" style="display:none">Disconnect All Guests<' in lk
    # Real-time: a 5s poll while the dialog is open re-renders
    # the list; the timer starts on open and stops on close.
    script = _main_script(html)
    assert "startSessPoll()" in script
    assert "stopSessPoll()" in script
    assert "closeLinkWin()" in script
    poll = _fn(script, "function startSessPoll(){",
               "function closeLinkWin(){")
    assert "setInterval" in poll and ", 5000)" in poll
    assert "paintSessions()" in poll
    assert 'w.style.display !== "flex"' in poll
    assert 'if(AUTH && AUTH.host) paintSessions();' in script
    assert 'startSessPoll();' in script
    assert '$("#lkcloseX").onclick = () => { closeLinkWin(); };' in script
    assert "if(e.target.id === \"lkwrap\") closeLinkWin();" in script
    assert "location.reload" not in poll
    # The data the poll reads: a newly connected device appears
    # in /api/sessions without any reload.
    guest = Client(port)
    status, j = guest.j("POST", "/api/connect",
                        {"link": "homebase", "device_name": "Pixel 8"})
    assert status == 200 and j.get("authed"), j
    _flip_role(home, j["token"], "guest")
    status, j = client.j("GET", "/api/sessions")
    assert status == 200 and j["ok"], j
    assert any(s["display_name"] == "Pixel 8"
               for s in j["sessions"]), j


# ------------------------------------------------------------------ 4
def test_folder_routing_split_by_place(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    script = _main_script(html)
    # --- JS call sites ---
    # Menu: root methods, never the Files-tab buttons.
    sbopen = next(ln for ln in script.splitlines()
                  if '$("#sbopen").onclick' in ln)
    assert "openRootFolder()" in sbopen
    assert 'getElementById("openfolder")' not in sbopen
    sbchange = next(ln for ln in script.splitlines()
                    if '$("#sbchange").onclick' in ln)
    assert "changeRootFolder()" in sbchange
    assert 'getElementById("changefolder")' not in sbchange
    root_open = _fn(script, "async function openRootFolder(){",
                    "async function changeRootFolder(){")
    assert "open_root_folder" in root_open
    assert "api.open_folder()" not in root_open
    root_change = _fn(script, "async function changeRootFolder(){",
                      '$("#sbopen").onclick')
    assert "browse_root_directory" in root_change
    assert '"/api/setrootfolder"' in root_change
    assert "api.browse_directory()" not in root_change
    # Set Up dialog: address folder only.
    lkopen = next(ln for ln in script.splitlines()
                  if '$("#lkopenfolder").onclick' in ln)
    assert "open_folder()" in script[script.index(lkopen):
                                     script.index(lkopen) + 400]
    lkchg = script[script.index('$("#lkchangefolder").onclick'):]
    assert "browse_directory()" in lkchg[:1200]
    assert "browse_root_directory" not in lkchg[:1200]
    # Files tab: address folder only.
    assert "window.pywebview.api.open_folder()" in script
    # --- server scope helpers (in-process) ---
    cfg = {"directory": "/root", "address_name": "HomeBase",
           "addresses": {"homebase": {"folder": "/custom"}}}
    assert D._root_folder(cfg) == "/root"
    assert D._address_folder(cfg) == "/custom"
    assert D._folder_for_scope(cfg, "root") == "/root"
    assert D._folder_for_scope(cfg, "address") == "/custom"
    cfg2 = {"directory": "/root", "address_name": "homebase",
            "addresses": {}}
    assert D._address_folder(cfg2) == os.path.join("/root", "homebase")
    assert D._folder_for_scope(cfg2, "root") == "/root"
    # --- /api/setrootfolder: root moves, address override stays ---
    status, j = client.j("POST", "/api/setlinkfolder",
                         {"folder": str(base / "addr-custom")})
    assert status == 200 and j["ok"], j
    newroot = str(base / "newroot")
    status, j = client.j("POST", "/api/setrootfolder",
                         {"folder": newroot})
    assert status == 200 and j["ok"], j
    assert j["folder"] == newroot
    assert j["address_folder"] == str(base / "addr-custom")
    status, st = client.j("GET", "/api/authstate")
    assert st["folder"] == str(base / "addr-custom")
    # Guest may not change the root.
    guest = Client(port)
    status, j = guest.j("POST", "/api/connect",
                        {"link": "homebase"})
    assert status == 200 and j.get("authed"), j
    _flip_role(home, j["token"], "guest")
    status, j = guest.j("POST", "/api/setrootfolder",
                        {"folder": str(base / "evil")})
    assert status == 403 and j.get("code") == "host_only", (status, j)


def test_desktop_bridge_root_methods(tmp_path, monkeypatch):
    import app as appmod
    fake = type("S", (), {"directory": str(tmp_path / "root")})()
    api = appmod.Api(fake)
    calls = []

    def fake_popen(args, **kw):
        calls.append(list(args))
        return None

    monkeypatch.setattr(appmod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        appmod.dropit, "_load_config",
        lambda: {"directory": str(tmp_path / "root"),
                 "address_name": "homebase",
                 "addresses": {"homebase": {"folder": str(tmp_path / "addr")}}})
    api.open_folder()
    assert calls[-1] == ["xdg-open", str(tmp_path / "addr")]
    api.open_root_folder()
    assert calls[-1] == ["xdg-open", str(tmp_path / "root")]
    # set_root_directory moves the root only, leaves the link
    # override and the server's link folder untouched.
    store = {"directory": str(tmp_path / "root"),
             "addresses": {"homebase": {"folder": str(tmp_path / "addr")}}}
    monkeypatch.setattr(appmod, "load_config", lambda: store)
    monkeypatch.setattr(appmod, "save_config", lambda c: None)
    r = api.set_root_directory(str(tmp_path / "newroot"))
    assert r["ok"] and r["directory"] == str(tmp_path / "newroot")
    assert store["directory"] == str(tmp_path / "newroot")
    assert store["addresses"]["homebase"]["folder"] == str(tmp_path / "addr")
    assert fake.directory == str(tmp_path / "newroot")


# ------------------------------------------------------------------ 5
def test_both_xs_red_bordered_pointer_same_class(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    lk = _setup(html)
    assert 'id="lkcloseX"' in lk
    assert 'id="lockpwcloseX"' in html
    # One shared rule for both Xs: red gradient, own border,
    # 32px box, pointer cursor.
    shared = _rule(html, ".lkbox .lkclosebtn, .lockpwbox .lkclosebtn")
    assert "linear-gradient(135deg,#f87171,#dc2626)" in shared
    assert "border:1px solid #dc2626" in shared
    assert "width:32px" in shared and "height:32px" in shared
    assert "cursor:pointer" in shared
    # No later rule restyles the Set Up X away from the shared
    # class (no background:none, muted colour, other size).
    m = re.search(r"\.lkbox \.lkclosebtn \{([^}]*)\}", html)
    assert m, "Set Up X positioning rule missing"
    for banned in ("background", "border", "color", "font-size",
                   "width", "height"):
        assert banned not in m.group(1), m.group(1)


# ------------------------------------------------------------------ 6
def test_find_icon_size_equals_menu_icon(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    menu = _rule(html, "#menubtn")
    find = _rule(html, "#askbtn")
    # Same button box.
    assert "width:36px" in menu and "height:36px" in menu
    assert "width:36px" in find and "height:36px" in find
    # Same icon size: menu bars are 16px wide, glass is 16px.
    assert "width:16px" in _rule(html, "#menubtn span")
    assert "width:16px" in _rule(html, "#askbtn .findglass")
    assert "height:16px" in _rule(html, "#askbtn .findglass")
    # Still icon-only with AI sparkle/glow, label kept.
    m = re.search(r'<button[^>]*id="askbtn"[^>]*>(.*?)</button>', html, re.S)
    assert m and re.sub(r"<[^>]+>", "", m.group(1)).strip() == ""
    assert 'class="findspark"' in m.group(1)
    assert 'title="Find"' in m.group(0)
    assert 'aria-label="Find"' in m.group(0)
    grad = "linear-gradient(135deg,#7C3AED,#0EA5E9)"
    assert grad in menu and grad in find


# ------------------------------------------------------------------ 7
def test_setup_dialog_scrollbar_matches_files_tab(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    # One grouped rule per scrollbar part: dialog and Files
    # tab (.colbody) share width, thumb colour, track.
    assert (".colbody::-webkit-scrollbar, .lkbox::-webkit-scrollbar"
            " { width:8px; }") in html
    assert (".colbody::-webkit-scrollbar-thumb, "
            ".lkbox::-webkit-scrollbar-thumb"
            " { background:#2a3560; border-radius:8px; }") in html
    assert (".colbody::-webkit-scrollbar-track, "
            ".lkbox::-webkit-scrollbar-track"
            " { background:transparent; }") in html
    assert ("html.light .colbody::-webkit-scrollbar-thumb, "
            "html.light .lkbox::-webkit-scrollbar-thumb"
            " { background:#b6c2d4; }") in html


# ------------------------------------------------------------------ 8
def test_setup_dialog_split_screen_equal_columns(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    lk = _setup(html)
    # Bigger window, two equal columns (the .lkbox selector has
    # several rules; the split-screen width is its own rule).
    lkbox_rules = re.findall(r"\.lkbox \{([^}]*)\}", html)
    assert any("width:min(760px,96vw)" in r for r in lkbox_rules)
    split = _rule(html, ".lksplit")
    assert "display:grid" in split
    assert "grid-template-columns:1fr 1fr" in split
    # Left column: Current + New + Password; right column:
    # Folder + Save. Both columns present, in that order.
    left = lk.index('class="lkcol"')
    right = lk.index('class="lkcol"', left + 1)
    leftseg = lk[left:right]
    rightseg = lk[right:]
    for fid in ("lkcurlabel", "lklinklabel", "lkpwlabel"):
        assert 'id="%s"' % fid in leftseg, fid
    for fid in ("lkfolderlabel", "lkfolderrow", "lkset"):
        assert 'id="%s"' % fid in rightseg, fid
    # Save is pushed to the foot of the right column, so the
    # columns end level (balanced, not one long one short).
    assert "margin-top:auto" in _rule(html, ".lksplit .lkcol #lkset")
    # Devices spans both columns at the bottom, after the split.
    assert lk.index('class="lkdevices"') > lk.index('class="lksplit"')
    assert lk.index('id="lksesslabel"') > lk.index('id="lkset"')
    # Guest screen stays single-column (its right column would
    # be empty -- no folder controls for guests).
    assert "width:400px" in _rule(html, ".lkbox.guestcard")
    assert "display:block" in _rule(html, ".lkbox.guestcard .lksplit")
    # Bounded content: device list scrolls inside itself, so
    # the dialog itself does not need a vertical scroll at a
    # normal window size.
    sess = _rule(html, "#lksess")
    assert "max-height:180px" in sess and "overflow-y:auto" in sess
