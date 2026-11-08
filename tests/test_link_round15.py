"""v2.7.99 desktop/web round (Nov 2, 2026) -- shared permissions
contract + Essef's Nov 2 evening items, as redirected.

PLACEMENT REDIRECTION (overrides the original brief's top-left
instruction and the v2.7.98 top-bar placement): the "Devices
Connected" text (borderless, small elegant arrow beside it) sits
CENTRED on the Send card, as an OVERLAY on the Send card's top
edge (absolutely positioned, straddling the top border) -- NOT a
separate row above Send (v2.7.97's page-growth shape) and NOT in
the top bar. The top bar no longer carries the Devices pill. The
overlay takes no flow space, so the page does not grow and no
card is resized; the three cards stay aligned.

The dropdown opens two ways (same window): hovering the arrow,
and clicking the Devices Connected text. Host-only; guests never
see its controls. Disconnect All lives in the dropdown (bottom,
red), NOT in Set Up any more. Set Up's Devices section is
replaced by the Permissions grid.

Covers:
  1. Pill: Send-card overlay, borderless, fitted, small arrow
     with a few-pixels gap, vertically centred, pointer cursor;
     no pill in the top bar; no page growth / card resize.
  2. Devices-list root cause: an authed LAN guest on connect
     (open address, no token yet) now gets a session and
     appears in /api/sessions; reuse does not duplicate; host
     sessions stay excluded.
  3. Set Up alignment: eye/delete icons exactly the password
     field's height and aligned; New Address + Open/Change
     Folder on one line, sizes unchanged; Save aligned with
     the password field, size unchanged; open-address notice
     centred with a tight border, not a full-width bar.
  4. Find window: visible border, animated drop-down from the
     magnifier, two distinct gentle chimes (results vs no
     results), renamed title, Find icon still 36x36.
  5. Set Password popup: exactly one eye, outside the box
     (native in-field reveal hidden), animation kept.
  7. Devices dropdown: animated, sizes to content, thin
     scroller absent when few, per-device Disconnect, red
     Disconnect All at bottom, exact disconnect messages,
     theme-correct message background, Title Case except
     device names.
  8. Permissions contract: per-address persisted, enforced
     per endpoint, guest greyed + no-permission message when
     off and working when on, old delete toggles gone.
"""

import io
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
from test_link_round2 import server, _raw  # noqa: F401,E402
from test_link_round3 import _flip_role, _guest_client  # noqa: E402
from test_link_round5 import _H, _write_cfg  # noqa: E402
from test_link_round6 import _page  # noqa: E402
from test_link_round8 import _main_script  # noqa: E402
from test_link_round12 import _rule, _setlink, _topbar, _setup  # noqa: E402
from test_link_folders import Client  # noqa: E402

PERMS_DEFAULT = {"download_files": True, "upload_files": True,
                 "delete_files": False, "add_notes": True,
                 "delete_notes": False, "star_notes": True}
MSG = {"download_files": "No permission to download files from this device",
       "upload_files": "No permission to upload files to this device",
       "delete_files": "No permission to delete files from this device",
       "delete_notes": "No permission to delete notes from this device",
       "add_notes": "No permission to add notes on this device",
       "star_notes": "No permission to star notes on this device"}


def _all_rules(html, selector):
    return " ".join(re.findall(re.escape(selector) + r" \{([^}]*)\}", html))


def _devpill(html):
    i = html.index('id="devpill"')
    j = html.index('<div class="colhead">', i)
    return html[i:j]


def _open_guest(port, address):
    """A guest client holding a token for an OPEN address: via
    explicit /api/connect (the guest login page's own path),
    then role-flipped to 'guest' like a real LAN phone."""
    guest = Client(port)
    status, j = guest.j("POST", "/api/connect", {"link": address})
    assert status == 200 and j.get("authed"), j
    guest.cookies["drop_sess"] = j["token"]
    return guest


def _drive_connect(cfg_path, ip, body, cookie=None):
    """Drive Handler.do_POST /api/connect in-process (the sandbox
    blocks non-loopback TCP, so a real LAN guest cannot connect
    here -- same pattern as round5's in-process LAN tests)."""
    raw = json.dumps(body).encode()
    headers = {"Content-Type": "application/json",
               "Content-Length": str(len(raw)),
               "User-Agent": ("Mozilla/5.0 (Linux; Android 14; "
                              "Pixel 8 Build/UP1A) AppleWebKit")}
    if cookie:
        headers["Cookie"] = "drop_sess=" + cookie
    h = _H(cfg_path, ip=ip, headers=headers, host_token="")
    try:
        hh = h._handler
        hh.path = "/api/connect"
        hh.rfile = io.BytesIO(raw)
        hh.wfile = io.BytesIO()
        hh.request_version = "HTTP/1.1"
        hh.requestline = "POST /api/connect HTTP/1.1"
        hh.log_request = lambda *a: None
        hh._headers_buffer = []
        hh.command = "POST"
        hh.do_POST()
        out = hh.wfile.getvalue()
        _, _, payload = out.partition(b"\r\n\r\n")
        return json.loads(payload.decode() or "{}")
    finally:
        h.close()


def _read_cfg(cfg_path):
    with open(str(cfg_path), encoding="utf-8") as f:
        return json.load(f)


def _sessions_of(cfg_path):
    """Host-view session list for a cfg file, via a fresh handler."""
    h = _H(cfg_path, ip="127.0.0.1", headers={}, host_token="")
    try:
        return h._handler._sessions_list()
    finally:
        h.close()


# ------------------------------------------------------------------ 0
def test_version_299():
    assert D.VERSION == "2.7.99"


# ------------------------------------------------------------------ 1
def test_pill_sendcard_overlay_not_topbar_no_growth(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    top = _topbar(html)
    # No pill in the top bar any more: menu, Address pill, Find
    # only -- the v2.7.98 top-left placement is superseded.
    assert 'id="statusdiv"' not in top
    assert 'class="topstatus"' not in html
    assert 'id="menubtn"' in top and 'id="toplink"' in top
    assert 'id="askbtn"' in top
    # The pill lives on the Send card, before its heading, as an
    # overlay wrapper (absolute, centred, straddling the edge).
    assert 'id="devpill"' in html
    board = html[html.index('<div class="board">'):]
    send_i = board.index('id="devpill"')
    col_i = board.index('data-col="send"')
    assert col_i < send_i < col_i + 400
    send = _devpill(html)
    assert 'id="statusdiv"' in send
    assert 'id="statustext"' in send
    assert send.index('id="statustext"') < send.index('devarrow')
    assert board.index('data-col="send"') < board.index('data-col="notes"') < board.index('data-col="files"')
    # Overlay, not a row: absolute + centred straddle, taking no
    # flow space (no v2.7.97 row shapes anywhere).
    wrap = _rule(html, ".devpill")
    assert "position:absolute" in wrap
    assert "left:50%" in wrap
    assert "translate(-50%,-50%)" in wrap
    assert 'class="statusrow"' not in html
    assert 'class="sendwrap"' not in html
    assert 'class="devpill"' in html
    # Borderless pill, fitted, pointer cursor; only the Send
    # column may show overflow (so the straddle is not clipped).
    pill = _rule(html, ".devpill .status")
    assert "border:none" in pill
    assert "cursor:pointer" in pill
    assert "width:auto" in pill
    assert "background:#12172a" in pill
    light = _rule(html, "html.light .devpill .status")
    assert "background:#ffffff" in light
    assert "overflow:visible" in _rule(html, ".col")
    # No per-card rule for Send (round13 constraint): the shared
    # .col rule carries the overflow, so all cards stay governed
    # by the single shared rule.
    assert '.col[data-col="send"] {' not in html
    # No page growth, no card resize: board/col rules unchanged.
    assert "display:flex" in _rule(html, ".board")
    assert "gap:14px" in _rule(html, ".board")
    col = _rule(html, ".col")
    assert "height:calc(100vh - 210px)" in col
    assert "width:340px" in col
    assert "min-height:52px" in _all_rules(html, ".topbar")


def test_pill_arrow_small_few_px_gap_centred(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    send = _devpill(html)
    # One small elegant chevron beside the text, text first.
    assert 'class="devarrow"' in send
    assert "<svg" in send
    pill = _rule(html, ".devpill .status")
    # A few pixels' gap, not a wide separation; same vertical
    # centre line; fitted width (no stretched gap).
    assert "gap:6px" in pill
    assert "align-items:center" in pill
    arrow = _rule(html, ".devpill .devarrow")
    assert "width:10px" in arrow and "height:10px" in arrow
    assert "width:10px" in _rule(html, ".devpill .devarrow svg")
    # Both triggers wire to the same dropdown: hover on the
    # pill wrapper (the arrow sits inside it) and click on the
    # pill text itself.
    script = _main_script(html)
    assert "function openDevDrop(" in script
    assert "function toggleDevDrop()" in script
    assert 'addEventListener("mouseenter"' in script
    assert "_pill.onclick = () => toggleDevDrop();" in script
    assert 'id="devdrop"' in html


# ------------------------------------------------------------------ 2
def test_open_guest_connect_mints_session_in_list(tmp_path):
    cfg_path = tmp_path / "config.json"
    _write_cfg(cfg_path, link_name="homebase", sessions={})
    # Tokenless LAN guest, open address: authed via the
    # passwordless fallback but holding no token -- the exact
    # case the old `if ... _is_host()` mint gate missed.
    out = _drive_connect(cfg_path, "192.168.1.7",
                         {"link": "homebase",
                          "device_name": "Essefs Phone"})
    assert out.get("ok") and out.get("authed"), out
    assert out.get("token"), out
    tok = out["token"]
    cfg = _read_cfg(cfg_path)
    sess = cfg["sessions"][tok]
    assert sess["role"] == "guest"
    assert sess["link"] == "homebase"
    assert sess["ip"] == "192.168.1.7"
    assert sess["device_name"] == "Essefs Phone"
    assert sess["ua_hint"] == "Pixel 8"
    listed = _sessions_of(cfg_path)
    assert any(s["display_name"] == "Essefs Phone" and
               s["ua_hint"] == "Pixel 8" for s in listed), listed
    # Reuse: a second connect with the token mints nothing new.
    out2 = _drive_connect(cfg_path, "192.168.1.7",
                          {"link": "homebase"}, cookie=tok)
    assert out2.get("authed") and not out2.get("token"), out2
    assert len(_read_cfg(cfg_path)["sessions"]) == 1
    # Host sessions stay excluded from the list.
    out3 = _drive_connect(cfg_path, "127.0.0.1",
                          {"link": "homebase"})
    assert out3.get("authed") and out3.get("token"), out3
    listed = _sessions_of(cfg_path)
    assert all(s["role"] != "host" for s in listed)
    assert len(listed) == 1


# ------------------------------------------------------------------ 3
def test_setup_alignment(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    lk = _setup(html)
    # (a) Eye + delete icons exactly the password field's height.
    assert "height:48px" in _rule(html, ".lkfield")
    assert "height:48px" in _rule(html, ".lkpwrow .lkiconbtn")
    assert "align-items:stretch" in _rule(html, ".lkpwrow")
    # (b) New Address, Open Folder, Change Folder on ONE line:
    # one shared .lktopline row holding the field + both buttons.
    top_i = lk.index('class="lktopline"')
    top_j = lk.index('id="lkerr"', top_i)
    top = lk[top_i:top_j]
    assert 'id="lklinklabel"' in top
    assert 'id="lkin"' in top
    assert 'id="lkopenfolder"' in top
    assert 'id="lkchangefolder"' in top
    assert 'class="btn openf" id="lkopenfolder"' in top
    assert 'class="btn changef" id="lkchangefolder"' in top
    assert 'class="lkfield" id="lkin"' in top
    # (c) Save aligned with the password field: same left column
    # as the password row, after it, left edge = field's edge,
    # size unchanged (same classes, same min-width/padding).
    assert lk.index('id="lkpw"') < lk.index('id="lkset"')
    assert 'class="btn primary lkclose" id="lkset"' in lk
    assert "margin-left:0" in _all_rules(html, ".lksplit .lkcol #lkset")
    assert "margin-top:auto" in _all_rules(html, ".lksplit .lkcol #lkset")
    assert "min-width:150px" in _rule(html, ".lkclose")
    # (d) Open-address notice centred with a tight border only
    # around the text, not a wide flat full-width bar.
    warn = _rule(html, ".lkopenwarn.show")
    assert "display:table" in warn
    assert "margin-left:auto" in warn and "margin-right:auto" in warn
    assert "border:1px solid #f59e0b" in _rule(html, ".lkopenwarn")


# ------------------------------------------------------------------ 4
def test_find_window(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    # (a) Visible full border on the Find window.
    pop = _rule(html, ".askpop")
    assert "border:1px solid" in pop
    assert "border-radius:18px" in pop
    # (b) Drops down from the magnifier, animated: fixed under
    # the top bar at the right, slide + fade from the icon.
    assert "top:76px" in pop and "right:18px" in pop
    assert "translateY(-14px)" in pop
    assert "transition:opacity .25s ease, transform .25s ease" in pop
    open_pop = _rule(html, ".askpop.open")
    assert "opacity:1" in open_pop and "translateY(0)" in open_pop
    assert "visibility:visible" in open_pop
    # Not the old full-height side panel any more.
    assert "top:0; right:0; bottom:0" not in pop
    # (c) Two distinct gentle WebAudio chimes, low volume,
    # silent fallback; results vs no-results wired in render.
    script = _main_script(html)
    assert "function playFindResultsSound()" in script
    assert "function playFindEmptySound()" in script
    res = script[script.index("function playFindResultsSound()"):
                 script.index("function playFindEmptySound()")]
    emp = script[script.index("function playFindEmptySound()"):
                 script.index("/* Ask Drop")]
    assert "660" in res and "880" in res
    assert "587" in emp and "392" in emp
    assert res != emp
    assert "AudioContext" in res and "AudioContext" in emp
    assert "0.07" in res and "0.06" in emp
    assert "playFindResultsSound();" in script
    assert "playFindEmptySound();" in script
    # (d) Renamed title, Title Case as written, in the Find
    # window's head (not the tab label).
    ask = html[html.index('id="askpop"'):html.index('id="asklist2"')]
    assert "Find A File Using Keywords / Objects / Texts" in ask
    # Find icon stays icon-only 36x36 (menu size).
    assert "width:36px" in _rule(html, "#askbtn")
    assert "height:36px" in _rule(html, "#askbtn")
    assert "width:16px" in _rule(html, "#askbtn .findglass")


# ------------------------------------------------------------------ 5
def test_set_password_single_eye_outside_box(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    pop = html[html.index('id="lockpwpop"'):html.index('id="lockpwpop"') + 2000]
    # Exactly ONE eye icon in the popup, OUTSIDE the field box:
    # the row holds the input followed by the eye button (the
    # button is a sibling, never inside the input element).
    assert pop.count('id="lockpweye"') == 1
    row = pop[pop.index('class="lockpwrow"'):]
    assert row.index('id="lockpwin"') < row.index('id="lockpweye"')
    # The native in-field reveal eye (Edge/WebView2) is hidden,
    # so the popup never shows a duplicate inside the box.
    assert "#lockpwin::-ms-reveal { display:none; }" in html
    # Its animation is kept.
    script = _main_script(html)
    assert "paintEyeBtn" in script and "eyesnap" in script


# ------------------------------------------------------------------ 7
def test_devices_dropdown(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    send = _devpill(html)
    # Window lives inside the pill wrapper, after the pill.
    assert 'id="devdrop"' in send
    assert send.index('id="statusdiv"') < send.index('id="devdrop"')
    assert "Devices Connected" in send
    # Rows container comes before the Disconnect All footer.
    assert send.index('id="devdroprows"') < send.index('id="devdropall"')
    assert ">Disconnect All<" in send
    # Animated drop-down, sized to content, thin scroller that
    # only appears on overflow (overflow-y:auto).
    dd = _rule(html, ".devdrop")
    assert "transition:opacity .22s ease, transform .22s ease" in dd
    assert "translateY(-8px)" in dd
    assert "width:max-content" in dd
    assert "min-width:240px" in dd
    assert "max-width:min(320px" in dd
    ddopen = _rule(html, ".devdrop.open")
    assert "opacity:1" in ddopen and "translateY(0)" in ddopen
    assert "overflow-y:auto" in _rule(html, ".devdroprows")
    assert "width:8px" in _rule(html, ".devdroprows::-webkit-scrollbar")
    # Disconnect All at the BOTTOM, RED.
    assert "background:#dc2626" in _rule(html, ".devdropfoot .devdropall")
    # JS: per-device Disconnect + Disconnect All via the
    # host-only revoke endpoint; exact messages; host-only guard.
    script = _main_script(html)
    ddjs = script[script.index("async function paintDevDrop()"):
                  script.index('const _devdropall')]
    assert "/api/sessions" in ddjs
    assert 'class="devdisc"' in ddjs
    assert "/api/sessions/revoke" in ddjs
    assert '+ " disconnected"' in script
    assert '+ " device(s) disconnected"' in script
    assert "All devices disconnected" not in script
    assert "All guests disconnected" not in script
    assert "Only the host can change this" in script
    # Title Case labels; device names as-is (no case transform
    # applied to a device name in the dropdown render).
    assert "Disconnect" in ddjs and "Devices Connected" in ddjs
    assert "toUpperCase" not in ddjs and "toLowerCase" not in ddjs
    # Theme-correct message background: toast light + dark.
    assert "z-index:5000" in _all_rules(html, ".toast")
    assert "background:#ffffff" in _rule(html, "html.light .toast")


# ------------------------------------------------------------------ 8
def test_permissions_contract_tcp(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    # Defaults, via both authstate and GET /api/permissions.
    status, st = client.j("GET", "/api/authstate")
    assert status == 200 and st["permissions"] == PERMS_DEFAULT, st
    # Host always True for every can_* (contract), whatever the set.
    for k in PERMS_DEFAULT:
        assert st["can_" + k] is True, (k, st)
    status, j = client.j("GET", "/api/permissions")
    assert status == 200 and j["permissions"] == PERMS_DEFAULT, j
    # POST merges a subset; other keys unchanged.
    status, j = client.j("POST", "/api/permissions",
                         {"permissions": {"delete_files": True}})
    assert status == 200 and j["permissions"]["delete_files"] is True, j
    assert j["permissions"]["download_files"] is True
    status, j = client.j("GET", "/api/permissions")
    assert j["permissions"]["delete_files"] is True
    # Per-address persisted: switch away and back, still set.
    _setlink(client, "otherbase")
    status, j = client.j("GET", "/api/permissions")
    assert j["permissions"] == PERMS_DEFAULT, j
    _setlink(client, "homebase")
    status, j = client.j("GET", "/api/permissions")
    assert j["permissions"]["delete_files"] is True, j
    # Legacy seed: on a fresh address the legacy global toggles
    # seed the delete keys before any entry exists.
    status, j = client.j("POST", "/api/guestdelete", {"allowed": True})
    assert status == 200 and j["ok"]
    _setlink(client, "seedbase")
    status, j = client.j("GET", "/api/permissions")
    assert j["permissions"]["delete_files"] is True, j
    _setlink(client, "homebase")
    # Guest: GET works, POST is host-only 403.
    guest = _open_guest(port, "homebase")
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    status, j = guest.j("GET", "/api/permissions")
    assert status == 200 and j["ok"], j
    status, j = guest.j("POST", "/api/permissions",
                        {"permissions": {"delete_files": True}})
    assert status == 403 and j.get("code") == "host_only", j


def test_permissions_enforced_per_endpoint(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    status, _ = client.upload("pcfile.txt", b"from the pc")
    assert status == 200
    status, j = client.j("POST", "/api/snippet", {"text": "hello note"})
    assert status == 200 and j["ok"], j
    nid = j["id"]
    guest = _open_guest(port, "homebase")
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    # All six off for this address: every gate 403s with the
    # exact contract message.
    status, j = client.j("POST", "/api/permissions",
                         {"permissions": {k: False for k in PERMS_DEFAULT}})
    assert status == 200
    # Guest authstate mirrors the set (all False here).
    status, st = guest.j("GET", "/api/authstate")
    assert status == 200, st
    for k in PERMS_DEFAULT:
        assert st["can_" + k] is False, (k, st)
    status, j = guest.j("GET", "/dl/pcfile.txt")
    assert status == 403 and j.get("error") == MSG["download_files"], j
    status, j = guest.j("GET", "/api/notes/dl?id=" + nid)
    assert status == 403 and j.get("error") == MSG["download_files"], j
    status, _ = guest.upload("guestfile.txt", b"guest")
    # upload() returns raw bytes; decode the JSON error.
    status, raw = guest.upload("guestfile2.txt", b"guest")
    assert status == 403, status
    assert json.loads(raw.decode())["error"] == MSG["upload_files"]
    status, j = guest.j("POST", "/api/snippet", {"text": "nope"})
    assert status == 403 and j.get("error") == MSG["add_notes"], j
    status, j = guest.j("POST", "/api/notes/star",
                        {"id": nid, "starred": True})
    assert status == 403 and j.get("error") == MSG["star_notes"], j
    status, j = guest.j("POST", "/api/delete", {"name": "pcfile.txt"})
    assert status == 403 and j.get("error") == MSG["delete_files"], j
    status, j = guest.j("POST", "/api/notes/delete", {"id": nid})
    assert status == 403 and j.get("error") == MSG["delete_notes"], j
    # All six on: the same calls work (delete removes the file).
    status, j = client.j("POST", "/api/permissions",
                         {"permissions": {k: True for k in PERMS_DEFAULT}})
    assert status == 200
    status, j = guest.j("GET", "/dl/pcfile.txt")
    assert status == 200, (status, j)
    status, _ = guest.upload("guestfile3.txt", b"guest")
    assert status == 200
    status, j = guest.j("POST", "/api/snippet", {"text": "allowed"})
    assert status == 200 and j["ok"], j
    status, j = guest.j("POST", "/api/notes/star",
                        {"id": nid, "starred": True})
    assert status == 200 and j["ok"], j
    status, j = guest.j("POST", "/api/delete", {"name": "pcfile.txt"})
    assert status == 200 and j["ok"], j
    status, j = guest.j("POST", "/api/notes/delete", {"id": nid})
    assert status == 200 and j["ok"], j


def test_permissions_grid_and_old_toggles_gone(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    lk = _setup(html)
    # The old Devices section is gone from Set Up...
    assert 'id="lksesslabel"' not in html
    assert 'id="lksessall"' not in html
    assert 'id="lksess"' not in html
    # ...and the old separate guest-delete toggles are gone
    # (superseded by Delete Files / Delete Notes) -- not just
    # hidden: no such controls, no such endpoint calls in PAGE.
    assert 'id="swguestdel"' not in html
    assert 'id="swguestnotesdel"' not in html
    assert 'id="guestdelrow"' not in html
    assert 'id="guestnotesdelrow"' not in html
    assert "/api/guestdelete" not in html
    assert "/api/guestnotesdelete" not in html
    # ...replaced by the Permissions grid in Set Up.
    assert 'id="lkperms"' in lk
    assert 'id="lkpermgrid"' in lk
    for key, label in (("download_files", "Download Files"),
                       ("upload_files", "Upload Files"),
                       ("delete_files", "Delete Files"),
                       ("add_notes", "Add Notes"),
                       ("delete_notes", "Delete Notes"),
                       ("star_notes", "Star Notes")):
        assert 'data-perm="%s"' % key in lk
        assert label in lk
    # Compact grid, 3 per row -- NOT a vertical list -- so the
    # window does not extend vertically.
    grid = _rule(html, ".lkpermgrid")
    assert "display:grid" in grid
    assert "repeat(3, 1fr)" in grid
    # Classic-futuristic animated checkbox with a GREEN tick.
    assert "background:#22c55e" in _rule(
        html, ".permchk input:checked + .permbox")
    assert "scale(1)" in _rule(
        html, ".permchk input:checked + .permbox::after")
    # Host-only to change, per-address persisted via the new
    # endpoint (JS wiring, not just markup).
    script = _main_script(html)
    assert "function paintPermissions()" in script
    assert "/api/permissions" in script
    assert 'postHostJ("/api/permissions"' in script
    # Guest grey + no-permission message for every control, and
    # working normally when on (the grey class + gate helpers).
    for key in PERMS_DEFAULT:
        assert MSG[key] in script, key
    assert "[data-dl]" in script and "[data-star]" in script
    assert 'getElementById("maddnote")' in script or '#maddnote' in script
