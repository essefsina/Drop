"""v2.7.92 server/web round (Nov 2, 2026).

Covers, per the parent brief:
  * link -> address rename in user-visible served text (visible
    text carries no standalone "link" word; "optional for open
    links" and the eye-explanation paragraph are gone);
  * dropdowns drop from the address field itself (host Set up
    page + guest login page), each entry with its own animated
    eye (open / crossed-out, hashing / unhashing) and the main
    screens' delete icon (SVG.del, not an emoji);
  * disconnect-all revokes EVERY guest session on password AND
    open addresses, including the stale-declared-header host
    case that used to 401;
  * password remove / change / save messages carry the address
    name; disconnect-all confirms with a count;
  * real-time open-address detection: /api/addressinfo answers
    without authenticating and without leaking a password, and
    the served page greys the password field with the exact
    "No password set for this address, click Connect." note;
  * address colours: deterministic across renders and identical
    between the Python server function and the page's JS;
  * lock popup cycle (clarified Nov 2): first lock asks for a
    password only; unlock keeps the password; re-lock reuses it
    with no popup and no re-entry; only an explicit removal
    clears it; the password stays eye-revealable after unlock;
  * desktop files delete control is labelled "Delete files";
    Devices Connected sits in its own left row with a background;
    the menu icon is smaller; toasts align with light mode;
    the web Saved view shows a message on use.

Reuses the subprocess-server harness from rounds 2-3/6 and the
in-process _H helper from round 5 for the config migration.
"""
import json
import os
import re
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import dropit as D  # noqa: E402

from test_link_round2 import server, _raw  # noqa: F401,E402
from test_link_round3 import _flip_role, _guest_client  # noqa: E402
from test_link_round5 import _H, _write_cfg  # noqa: E402
from test_link_round6 import _page  # noqa: E402


def _visible(html):
    vis = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    vis = re.sub(r"<style.*?</style>", "", vis, flags=re.S)
    vis = re.sub(r"<[^>]+>", " ", vis)
    return re.sub(r"\s+", " ", vis)


def _main_script(html):
    blocks = re.findall(r"<script>(.*?)</script>", html, flags=re.S)
    return max(blocks, key=len)


def _guest_with_token(port, home, password=None, address=None):
    """A guest client holding a guest-stamped token for the current
    address: via login (password address) or connect (open)."""
    guest = _guest_client(port, password) if password else None
    if guest is None:
        from test_link_folders import Client
        guest = Client(port)
        status, j = guest.j("POST", "/api/connect",
                            {"link": address})
        assert status == 200 and j.get("authed"), j
        guest.cookies["drop_sess"] = j["token"]
        guest.cookies["drop_locked"] = "1"
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    return guest


# ------------------------------------------------------------------ rename
def test_rename_visible_text_and_no_stale_phrases(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "homebase", "password": "pw123"})
    assert status == 200 and j["ok"], j
    html = _page(port, client)
    vis = _visible(html)
    # v2.7.95 Title Case (was "Set up your addresses").
    assert "Set Up Your Addresses" in vis
    assert "Set up your links" not in html
    assert re.search(r"\blink\b", vis, re.I) is None, vis
    # Literal banned phrases, anywhere in the served page.
    assert "optional for open links" not in html
    assert "the eye shows the saved password too" not in html
    assert "eye shows only typed text" not in html
    assert "the eye then reveals" not in html
    # New API fields alongside the legacy ones (APK compat).
    status, st = client.j("GET", "/api/authstate")
    assert st["address_name"] == "homebase" and st["link_name"] == "homebase"
    assert st["address_key"] == "homebase" and st["link_key"] == "homebase"
    assert j["display_address"] == "homebase" and j["display_link"] == "homebase"
    assert j["address"] == "homebase" and j["link"] == "homebase"


def test_config_migration_old_keys_still_load_and_dual_write(tmp_path):
    cfg_path = tmp_path / "config.json"
    # Old spelling only, as written by pre-2.7.92 builds.
    cfg_path.write_text(json.dumps({
        "link_name": "lanlink", "link_pass": "hash$fake",
        "sessions": {}, "guest_locked": False, "guest_lock_seq": 0,
        "guest_delete_allowed": False}))
    h = _H(cfg_path)
    try:
        assert D._current_address(h._cfg()) == "lanlink"
        assert D._address_locked(h._cfg()) is True
        assert h._cfg().get("address_name") == "lanlink"
    finally:
        h.close()
    # A fresh write stores BOTH spellings.
    cfg = {"address_name": "newlink", "address_pass": "",
           "sessions": {}}
    old = D._config_path
    D._config_path = lambda: str(cfg_path)
    try:
        D._save_config(cfg)
    finally:
        D._config_path = old
    saved = json.loads(cfg_path.read_text())
    assert saved["address_name"] == "newlink"
    assert saved["link_name"] == "newlink"


# ------------------------------------------------------------------ dropdowns
def test_dropdowns_drop_from_address_field(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "homebase"})
    assert status == 200 and j["ok"], j
    html = _page(port, client)
    # Host (v2.7.94): the dropdown drops from the CURRENT address
    # field, not from New Address (which is now a plain input).
    assert 'id="lkddwrap"' not in html
    m = re.search(r'<div class="lkview lkcurdd" id="lkcurview">(.*?)</div>', html)
    assert m, "host current-address dropdown missing"
    assert 'id="lkddlist"' in m.group(1) and 'id="lkddchevbtn"' in m.group(1)
    assert 'id="lkin"' in html and 'id="lkhistbox"' not in html and 'id="lkhistlabel"' not in html
    # Guest: the login address field wraps input + chevron + list.
    m = re.search(r'<div class="ddwrap" id="gddwrap">(.*?)</div>', html)
    assert m, "guest field dropdown wrapper missing"
    assert 'id="gloginlink"' in m.group(1) and 'id="gddlist"' in m.group(1)
    assert 'id="gddchevbtn"' in m.group(1)
    assert 'id="gloginrecent"' not in html
    # Shared helpers + per-entry eye/delete wiring present.
    for needle in ("function paintAddressHistory(){",
                   "function renderGuestRecent(){",
                   "function eyeSVG(open){",
                   "eyesnap",
                   "data-delhist",
                   "data-gddel"):
        assert needle in html, needle
    # Dropdown rows use the main-screen delete SVG, not an emoji.
    assert "🗑" not in html
    assert "👁" not in html


def _jsdom_run(html, prelude, script):
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".js",
                                     delete=False) as f:
        f.write(prelude + "\n" + script)
        path = f.name
    env = dict(os.environ,
               NODE_PATH=os.path.expanduser("~/workspace/aitest3/dom/node_modules"))
    proc = subprocess.run(["node", path], capture_output=True,
                          text=True, timeout=30, env=env)
    os.unlink(path)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    return proc.stdout


def _extract_fn(script, start_marker, end_marker=None):
    start = script.index(start_marker)
    if end_marker is None:
        # Single-line function: up to the first newline.
        end = script.index("\n", start)
    else:
        end = script.index(end_marker, start)
    return script[start:end]


def test_guest_dropdown_eye_and_delete_jsdom(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "homebase"})
    assert status == 200 and j["ok"], j
    html = _page(port, client)
    script = _main_script(html)
    esc = _extract_fn(script, "const esc =")
    svg = script[script.index("const SVG = {"):script.index("};", script.index("const SVG = {")) + 2]
    helpers = script[script.index("const ADDRESS_PALETTE"):script.index("// v2.7.92 lock/unlock click sound")]
    funcs = "\n".join([
        _extract_fn(script, "function addressUseCounts(){"),
        _extract_fn(script, "function guestSavedAddressPw(){"),
        _extract_fn(script, "function removeGuestSavedAddressPw(link){"),
    ])
    render = script[script.index("function renderGuestRecent(){"):script.index("function showGuestMain(){", script.index("function renderGuestRecent(){"))]
    prelude = (
        "const { JSDOM } = require('jsdom');\n"
        "const dom = new JSDOM('<input id=\"gloginlink\" value=\"homebase\">"
        "<div class=\"ddwrap\" id=\"gddwrap\"><button id=\"gddchevbtn\">x</button>"
        "<div class=\"ddlist\" id=\"gddlist\"></div></div>"
        "<input type=\"password\" id=\"gloginpw\">', {url: 'http://x/'});\n"
        "global.window = dom.window; global.document = dom.window.document;\n"
        "global.localStorage = dom.window.localStorage;\n"
        "localStorage.setItem('drop_link_use', JSON.stringify({homebase: 3, work: 1}));\n"
        "localStorage.setItem('drop_guest_pw', JSON.stringify({homebase: 'secret1'}));\n"
        "const $ = s => document.querySelector(s);\n"
        "let __toast = '';\n"
        "function toast(m){ __toast = m; }\n"
        "function checkOpenAddress(n){ globalThis.__checked = n; }\n"
        + esc + "\n" + svg + "\n" + helpers + "\n" + funcs + "\n")
    out = _jsdom_run(html, prelude, render + """
renderGuestRecent();
const rows = document.querySelectorAll('#gddlist .ddopt');
if (rows.length !== 2) throw new Error('rows=' + rows.length);
const home = document.querySelector('#gddlist .ddopt.ddsel');
if (!home) throw new Error('selected row missing');
const eye = home.querySelector('[data-gdeye]');
if (!eye || !eye.innerHTML.includes('<svg')) throw new Error('eye is not an SVG');
if (eye.innerHTML.includes('x1="4"') === false) throw new Error('hidden preview must show the crossed eye');
const del = home.querySelector('[data-gddel]');
if (!del || !del.innerHTML.includes('polyline')) throw new Error('delete is not the main-screen SVG');
eye.click();
const pwSpan = home.querySelector('.ddpw');
if (pwSpan.textContent !== 'secret1') throw new Error('eye did not reveal: ' + pwSpan.textContent);
if (eye.innerHTML.includes('x1="4"')) throw new Error('revealed preview must show the open eye');
eye.click();
if (pwSpan.textContent !== '••••••') throw new Error('eye did not re-hash');
const workDel = document.querySelector('[data-gddel="work"]') || [...document.querySelectorAll('[data-gddel]')].find(b => b.closest('.ddopt').dataset.name === 'work');
if (!workDel) throw new Error('work delete missing');
workDel.click();
if (!__toast.includes('files remain on the PC')) throw new Error('delete toast wrong: ' + __toast);
if (document.querySelector('#gddlist').innerHTML.includes('work')) throw new Error('deleted row still listed');
console.log('guest-dropdown-ok');
""")
    assert "guest-dropdown-ok" in out


def test_host_dropdown_eye_and_delete_jsdom(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "homebase"})
    assert status == 200 and j["ok"], j
    html = _page(port, client)
    script = _main_script(html)
    esc = _extract_fn(script, "const esc =")
    svg = script[script.index("const SVG = {"):script.index("};", script.index("const SVG = {")) + 2]
    helpers = script[script.index("const ADDRESS_PALETTE"):script.index("// v2.7.92 lock/unlock click sound")]
    paint = script[script.index("async function paintAddressHistory(){"):script.index("// v2.7.87: ONE button for the whole link flow", script.index("async function paintAddressHistory(){"))]
    prelude = (
        "const { JSDOM } = require('jsdom');\n"
        "const dom = new JSDOM('<input id=\"lkin\"><input type=\"password\" id=\"lkpw\">"
        "<button id=\"lkset\"></button><button id=\"lkddchevbtn\">x</button>"
        "<div class=\"ddlist\" id=\"lkddlist\"></div>', {url: 'http://x/'});\n"
        "global.window = dom.window; global.document = dom.window.document;\n"
        "const $ = s => document.querySelector(s);\n"
        "let AUTH = {address_name: 'homebase', address_key: 'homebase'};\n"
        "let lkPwTouched = false;\n"
        "let __toast = ''; let __postJ = null;\n"
        "function toast(m){ __toast = m; }\n"
        "function validateAddressName(n){ return ''; }\n"
        "function shakeAddressField(m){}\n"
        "const _origFetch = async (url) => ({json: async () => {\n"
        "  if (String(url).includes('/api/linkhistory')) return {ok: true, entries: [{name: 'homebase', key: 'homebase', has_password: true}, {name: 'work', key: 'work', has_password: false}]};\n"
        "  if (String(url).includes('/api/linkpassword')) return {ok: true, password: 'pw123'};\n"
        "  return {ok: false};\n"
        "}});\n"
        "async function postJ(path, data){ __postJ = {path, data}; return {ok: true}; }\n"
        + esc + "\n" + svg + "\n" + helpers + "\n")
    out = _jsdom_run(html, prelude, paint + """
(async () => {
  await paintAddressHistory();
  const rows = document.querySelectorAll('#lkddlist .ddopt');
  if (rows.length !== 2) throw new Error('rows=' + rows.length);
  const home = document.querySelector('#lkddlist .ddopt.ddsel');
  if (!home) throw new Error('selected row missing');
  const dot = home.querySelector('.addot');
  if (!dot) throw new Error('address colour dot missing');
  const eye = home.querySelector('[data-eye]');
  if (!eye || !eye.innerHTML.includes('<svg')) throw new Error('eye is not an SVG');
  eye.click();
  await new Promise(r => setTimeout(r, 50));
  const pwSpan = home.querySelector('.ddpw');
  if (pwSpan.textContent !== 'pw123') throw new Error('eye did not reveal: ' + pwSpan.textContent);
  if (eye.innerHTML.includes('x1="4"')) throw new Error('revealed preview must show the open eye');
  const workRow = [...document.querySelectorAll('#lkddlist .ddopt')].find(r => r.dataset.name === 'work');
  const workDel = workRow.querySelector('[data-delhist]');
  if (!workDel || !workDel.innerHTML.includes('polyline')) throw new Error('delete is not the main-screen SVG');
  workDel.click();
  await new Promise(r => setTimeout(r, 50));
  if (!__postJ || __postJ.path !== '/api/linkhistory/delete') throw new Error('delete did not call history delete');
  if (!__toast.includes('folder and files are still there on this PC')) throw new Error('delete toast wrong: ' + __toast);
  if (document.getElementById('lkin').value !== '') throw new Error('delete must not select');
  console.log('host-dropdown-ok');
})();
""")
    assert "host-dropdown-ok" in out


# ------------------------------------------------------------------ disconnect
def _sessions(client):
    status, j = client.j("GET", "/api/sessions")
    assert status == 200 and j["ok"], j
    return j["sessions"]


def test_disconnect_all_password_and_open_addresses(server):
    client, base, proc, port, home = server
    # Password address: two guests.
    status, j = client.j("POST", "/api/setlink",
                         {"name": "pwaddr", "password": "pw123"})
    assert status == 200 and j["ok"], j
    g1 = _guest_with_token(port, home, password="pw123")
    g2 = _guest_with_token(port, home, password="pw123")
    assert len(_sessions(client)) == 2
    tok1, tok2 = g1.cookies["drop_sess"], g2.cookies["drop_sess"]
    status, j = client.j("POST", "/api/sessions/revoke",
                         {"all_guests": True})
    assert status == 200 and j["ok"] and j["revoked"] == 2, j
    assert "All guests disconnected" in j["message"]
    assert _sessions(client) == []
    # The tokens are gone from config: that is the "token died"
    # fact provable over TCP (a localhost caller is the PC host
    # by loopback bypass, so its own 401 cannot be observed here;
    # the LAN-caller 401 for a removed token is covered in-process
    # by test_revoked_token_dead_for_lan_caller below).
    cfg_path = home / ".config" / "DropIt" / "config.json"
    sessions = json.loads(cfg_path.read_text()).get("sessions", {})
    assert tok1 not in sessions and tok2 not in sessions
    # Open address: two guests via explicit connect.
    status, j = client.j("POST", "/api/setlink", {"name": "openaddr"})
    assert status == 200 and j["ok"], j
    g3 = _guest_with_token(port, home, address="openaddr")
    g4 = _guest_with_token(port, home, address="openaddr")
    assert len(_sessions(client)) == 2
    tok3, tok4 = g3.cookies["drop_sess"], g4.cookies["drop_sess"]
    status, j = client.j("POST", "/api/sessions/revoke",
                         {"all_guests": True})
    assert status == 200 and j["ok"] and j["revoked"] == 2, j
    assert _sessions(client) == []
    sessions = json.loads(cfg_path.read_text()).get("sessions", {})
    assert tok3 not in sessions and tok4 not in sessions


def test_disconnect_all_stale_declared_header_host(server):
    # The pre-2.7.92 failure: the host page's declared address was
    # stale after an address change, so _profile 401d the revoke
    # while the (header-free) sessions list still showed guests.
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "firstaddr", "password": "pw123"})
    assert status == 200 and j["ok"], j
    # Host holds a host-stamped token (localhost login).
    status, j = client.j("POST", "/api/login", {"password": "pw123"})
    assert status == 200 and j["ok"], j
    host_tok = client.cookies["drop_sess"]
    # Host page still declares the OLD address after a change.
    status, j = client.j("POST", "/api/setlink",
                         {"name": "secondaddr", "password": "pw123"})
    assert status == 200 and j["ok"], j
    guest = _guest_with_token(port, home, password="pw123")
    assert len(_sessions(client)) == 1
    status, j = _raw(port, "POST", "/api/sessions/revoke",
                     {"all_guests": True},
                     headers={"X-Drop-Link": "firstaddr",
                              "Cookie": "drop_sess=" + host_tok})
    assert status == 200 and j["ok"], (status, j)
    assert _sessions(client) == []


def test_revoked_token_dead_for_lan_caller(tmp_path):
    # A token that is no longer in sessions must not authenticate
    # a LAN caller -- on a password address, and (the subtle one)
    # on an open address, where a tokenless caller WOULD be authed
    # but a revoked-token caller must not be silently re-authed.
    cfg_path = tmp_path / "config.json"
    _write_cfg(cfg_path, link_pass="hash$fake")
    h = _H(cfg_path, headers={"Cookie": "drop_sess=deadbeeftoken"})
    try:
        assert h._profile() is None
    finally:
        h.close()
    _write_cfg(cfg_path)
    h = _H(cfg_path, headers={"Cookie": "drop_sess=deadbeeftoken"})
    try:
        assert h._profile() is None
    finally:
        h.close()


# ------------------------------------------------------------------ messages
def test_password_messages_carry_address_name(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "msgaddr"})
    assert j["message"] == "Connected to msgaddr", j
    status, j = client.j("POST", "/api/setlink",
                         {"name": "msgaddr", "password": "secret"})
    assert status == 200 and j["ok"] and "msgaddr" in j["message"], j
    status, j = client.j("POST", "/api/setlinkpassword", {"password": ""})
    assert status == 200 and j["ok"] and "msgaddr" in j["message"], j
    status, j = client.j("POST", "/api/setlink",
                         {"name": "msgaddr", "password": "newpass"})
    assert status == 200 and j["ok"] and "msgaddr" in j["message"], j


# ------------------------------------------------------------------ detection
def test_open_address_detection_endpoint_and_page(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "detaddr", "password": "pw123"})
    assert status == 200 and j["ok"], j
    # No auth at all (a fresh guest page has no token).
    from test_link_folders import Client
    anon = Client(port)
    status, j = anon.j("GET", "/api/addressinfo?address=detaddr")
    assert status == 200 and j["ok"] and j["known"] is True, j
    assert j["needs_password"] is True and j["has_password"] is True
    assert "pw123" not in json.dumps(j)
    status, j = anon.j("GET", "/api/addressinfo?address=wrongaddr")
    assert status == 200 and j["known"] is False, j
    # Password removed on the PC: detection flips, no stale state.
    status, j = client.j("POST", "/api/setlinkpassword", {"password": ""})
    assert status == 200 and j["ok"], j
    status, j = anon.j("GET", "/api/addressinfo?address=detaddr")
    assert j["known"] is True and j["needs_password"] is False, j
    assert j["has_password"] is False
    html = _page(port, client)
    assert "No password set for this address, click Connect." in html
    assert "checkOpenAddress" in html and "debounceOpenAddress" in html
    assert "/api/addressinfo" in html


# ------------------------------------------------------------------ colours
def test_address_colour_stable_and_js_matches_python(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "homebase"})
    assert status == 200 and j["ok"], j
    html = _page(port, client)
    script = _main_script(html)
    helpers = script[script.index("const ADDRESS_PALETTE"):script.index("function addressDotHtml")]
    colour_fn = script[script.index("function addressColorForKey"):script.index("function addressDotHtml")]
    key_fn = script[script.index("function addressKeyOf"):script.index("function addressColorForKey")]
    out = _jsdom_run(html, helpers + "\n" + key_fn + "\n" + colour_fn, """
for (const k of ['homebase', 'work-2', 'esse f']) {
  console.log(k + '=' + addressColorForKey(addressKeyOf(k)));
}
console.log('again=' + addressColorForKey(addressKeyOf('homebase')));
""")
    js_colours = {}
    for line in out.strip().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            js_colours[k] = v
    assert js_colours["homebase"] == js_colours["again"]
    for key in ("homebase", "work-2", "esse f"):
        assert js_colours[key] == D.address_color(D._sanitise_address(key)), key
        assert js_colours[key] in D._ADDRESS_PALETTE
    # Same address, two renders: same colour (deterministic).
    assert D.address_color("homebase") == D.address_color("homebase")
    assert "function addressColorForKey" in html


# ------------------------------------------------------------------ lock cycle
def test_lock_popup_cycle_first_lock_only(server):
    client, base, proc, port, home = server
    # No password stored yet: locking is refused (popup path).
    status, j = client.j("POST", "/api/setlink", {"name": "lockaddr"})
    assert status == 200 and j["ok"], j
    status, j = client.j("POST", "/api/addresslock", {"locked": True})
    assert status == 409 and j.get("code") == "no_password", j
    # First lock: password saved (what the popup's Save sends).
    status, j = client.j("POST", "/api/setlinkpassword",
                         {"password": "firstpw"})
    assert status == 200 and j["ok"], j
    status, st = client.j("GET", "/api/authstate")
    assert st["locked"] is True and st["has_password"] is True, st
    # Unlock: password stays stored and eye-revealable.
    status, j = client.j("POST", "/api/addresslock", {"locked": False})
    assert status == 200 and j["ok"] and "lockaddr" in j["message"], j
    status, st = client.j("GET", "/api/authstate")
    assert st["locked"] is False and st["has_password"] is True, st
    status, j = client.j("GET", "/api/linkpassword")
    assert status == 200 and j["password"] == "firstpw", j
    # Re-lock: no password supplied, same stored password reused.
    status, j = client.j("POST", "/api/addresslock", {"locked": True})
    assert status == 200 and j["ok"] and "lockaddr" in j["message"], j
    status, st = client.j("GET", "/api/authstate")
    assert st["locked"] is True, st
    status, j = client.j("GET", "/api/linkpassword")
    assert j["password"] == "firstpw", j
    # Only an explicit removal clears it.
    status, j = client.j("POST", "/api/setlinkpassword", {"password": ""})
    assert status == 200 and j["ok"], j
    status, st = client.j("GET", "/api/authstate")
    assert st["locked"] is False and st["has_password"] is False, st
    # Served page carries the popup (password only, small Save).
    html = _page(port, client)
    assert 'id="lockpwpop"' in html
    assert 'Set Password For <span id="lockpwaddr">' in html
    assert 'id="lockpwsave"' in html
    assert "openLockPopup" in html and "playLockSound" in html
    assert "lockwiggle" in html


# ------------------------------------------------------------------ layout bits
def test_layout_bits_desktop_delete_devices_menu_toast_saved(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "homebase"})
    assert status == 200 and j["ok"], j
    html = _page(port, client)
    # Devices Connected (v2.7.98 SUPERSEDES the v2.7.96/97
    # above-Send placement): top bar, top left, immediately
    # right of the menu button, explicit solid pill
    # background — no white row under the top bar.
    assert '<div class="statusbar">' not in html
    assert '<div class="statusrow">' not in html
    assert 'class="sendwrap"' not in html
    assert 'class="sendstatus"' not in html
    top = html[html.index('<div class="topbar">'):html.index('<div class="qrpop"')]
    assert top.index('id="menubtn"') < top.index('id="statusdiv"') < top.index('id="toplink"')
    assert ".topstatus .status { background:#12172a" in html
    # Menu icon smaller; no Set-up entry in the sidebar; edit icon
    # in the sidebar only (v2.7.93: no edit icon on the top field).
    assert "#menubtn { width:36px" in html
    assert 'id="sbsetup"' not in html
    assert 'id="addredit"' not in html and 'id="sbedit"' in html
    # Toast colours align with light mode; Save smaller + red
    # Disconnect-all the same size; Saved view shows a message.
    assert "html.light .toast" in html
    assert ".lkclose { display:block" in html
    assert "#lksessall" in html and "#dc2626" in html
    assert "file(s) saved on this phone" in html


def test_desktop_files_delete_label(tmp_path, monkeypatch):
    # The desktop branch (server.desktop=True, as app.py runs it)
    # never renders under the CLI test harness, so serve one
    # in-process and check the real served desktop button row.
    import http.client
    import threading

    from test_link_folders import _free_port
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    base = tmp_path / "base"
    base.mkdir()
    port = _free_port()
    server = D.make_server(port, str(base), desktop=True)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/")
        html = conn.getresponse().read().decode("utf-8")
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
    m = re.search(r'<button[^>]*id="delallbtn"[^>]*>(.*?)</button>', html)
    assert m, "desktop delete button missing"
    assert "Delete files" in m.group(1), m.group(0)
    assert 'class="btn dangergrad"' in m.group(0)
    assert "fbtnrow" in html
