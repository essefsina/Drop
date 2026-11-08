"""v2.7.89 regression tests: guest-only locking + guest-delete toggle.

TCP tests run against the real subprocess server (same harness as
rounds 2-4). The sandbox blocks non-localhost TCP, so a real LAN
guest cannot connect here: a tokenless/revoked-token localhost
caller is correctly treated as the PC host, so TCP assertions use
role-flipped tokens and the host session list for "token died"
facts, and the true LAN 401s are covered by the in-process
LAN-address unit tests at the bottom of this file (a Handler built
via object.__new__ with client_address set to a LAN IP).
"""
import json
import os
import re
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import dropit as D  # noqa: E402

from test_link_round2 import server, _raw  # noqa: F401,E402
from test_link_round3 import _flip_role, _guest_client  # noqa: E402
from test_link_folders import Client, _free_port  # noqa: E402

GUEST_NOT_AUTH = "No permission to delete files from this device"  # v2.7.99 contract message
# Server-verbatim messages (dropit.py _ADDRESS_DOT_MSG /
# _ADDRESS_RULES_MSG); web validateAddressName and APK validateAddressName
# must carry these exact strings.
DOT_MSG = ("Dots are not allowed in address names: your address name "
           "becomes a folder name on the PC and part of the .local "
           "address, so a dot would break both. Use letters, "
           "numbers, hyphen (-) or underscore (_) instead (up to "
           "32 characters).")
RULES_MSG = ("Address names can only use letters, numbers, hyphen (-) "
             "and underscore (_), must start with a letter or "
             "number, and be at most 32 characters. Dots are not "
             "allowed: your address name becomes a folder name on the "
             "PC and part of the .local address, so a dot would "
             "break both.")


def _guest_tokens(client, port):
    status, j = client.j("GET", "/api/sessions")
    assert status == 200 and j["ok"], j
    return [s for s in j["sessions"] if s["role"] == "guest"]


def _upload(client, port, name="victim.txt", body=b"keep me"):
    # Client.upload posts multipart, as the real upload endpoint
    # requires (see test_link_folders.Client.upload); it returns
    # (status, raw bytes), so the JSON is parsed here.
    status, raw = client.upload(name, body)
    j = json.loads(raw) if isinstance(raw, (bytes, str)) else raw
    assert status == 200 and j["ok"], j
    return j


def _files(client):
    status, files = client.j("GET", "/api/files")
    assert status == 200, files
    return [f["name"] for f in files]


# ------------------------------------------------------------ guest-only lock

def test_guest_only_lock_host_never_blocked(server):
    # v2.7.90 SUPERSEDES v2.7.89 guest-lock: "lock guests out" is
    # retired. The endpoint answers 410, authstate reports
    # guest_locked False, and the guest keeps working.
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "locktest", "password": "secret"})
    assert status == 200 and j["ok"], j
    _upload(client, port, "hostfile.txt")
    guest = _guest_client(port, "secret")
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    assert _files(guest) == ["hostfile.txt"]
    client.cookies["drop_locked"] = "1"
    status, j = client.j("POST", "/api/guestlock", {"locked": True})
    assert status == 410 and j.get("code") == "guest_lock_removed", j
    assert _files(client) == ["hostfile.txt"]  # host, no prompt
    status, st = client.j("GET", "/api/authstate")
    assert st["authed"] is True and st["host"] is True, st
    assert st["guest_locked"] is False
    status, j = client.j("GET", "/api/linkpassword")
    assert status == 200 and j["password"] == "secret", j  # host admin
    assert _files(guest) == ["hostfile.txt"]  # guest unaffected


def test_guest_lock_seq_gate_surviving_pre_lock_token(server):
    # v2.7.90 SUPERSEDES: the lock sequence no longer gates
    # anything (guest-lock retired). A guest token bound to the
    # current link works regardless of its lock_seq stamp, and a
    # legacy guest_locked flag in config is ignored.
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "seqtest", "password": "secret"})
    assert status == 200 and j["ok"], j
    guest = _guest_client(port, "secret")
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    old_tok = guest.cookies["drop_sess"]
    cfg_path = home / ".config" / "DropIt" / "config.json"
    cfg = json.loads(cfg_path.read_text())
    cfg["guest_locked"] = True
    cfg["guest_lock_seq"] = 1
    cfg["sessions"][old_tok] = {"role": "guest", "link": "seqtest",
                                "lock_seq": 0, "ip": "127.0.0.1",
                                "ts": 1}
    cfg_path.write_text(json.dumps(cfg))
    status, files = guest.j("GET", "/api/files")
    assert status == 200, files  # retired gate: still admitted
    status, j = guest.j("POST", "/api/login", {"password": "secret"})
    assert status == 200 and j["ok"], j
    status, files = guest.j("GET", "/api/files")
    assert status == 200, files


def test_guestlock_guestdelete_guest_calls_403(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "admin403", "password": "secret"})
    assert status == 200 and j["ok"], j
    guest = _guest_client(port, "secret")
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    for allowed in (False, True):
        status, j = client.j("POST", "/api/guestdelete",
                             {"allowed": allowed})
        assert status == 200 and j["ok"], j
        for ep, body in (("/api/guestdelete", {"allowed": True}),
                         ("/api/setlink", {"name": "nope"}),
                         ("/api/setlinkpassword", {"password": "x"}),
                         ("/api/setlinkfolder", {"folder": str(base)}),
                         ("/api/sessions/revoke", {"id": "abcd"})):
            status, j = guest.j("POST", ep, body)
            assert status == 403 and j.get("code") == "host_only", (ep, status, j)
        status, j = guest.j("GET", "/api/linkpassword")
        assert status == 403 and j.get("code") == "host_only", j
    status, j = client.j("POST", "/api/guestdelete", {"allowed": False})
    assert status == 200 and j["ok"], j


# --------------------------------------------------------- guest-delete toggle

def test_guest_delete_toggle_off_on_immediate_and_persistent(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "deltest", "password": "secret"})
    assert status == 200 and j["ok"], j
    _upload(client, port, "victim.txt")
    guest = _guest_client(port, "secret")
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    # Default OFF (fresh config has no guest_delete_allowed key).
    status, st = guest.j("GET", "/api/authstate")
    assert st["guest_delete_allowed"] is False, st
    assert st["can_delete_files"] is False
    # Guest delete -> exact 403, file survives.
    status, j = guest.j("POST", "/api/delete", {"name": "victim.txt"})
    assert status == 403 and j.get("code") == "guest_delete_forbidden", j
    assert j["error"] == GUEST_NOT_AUTH, j
    status, j = guest.j("POST", "/api/delete_all", {})
    assert status == 403 and j.get("code") == "guest_delete_forbidden", j
    assert _files(guest) == ["victim.txt"]
    # Host delete always works regardless of the toggle.
    status, j = client.j("POST", "/api/delete", {"name": "victim.txt"})
    assert status == 200 and j["ok"], j
    assert _files(client) == []
    # Toggle ON: the guest's PRE-EXISTING token stays valid for
    # non-delete use, and delete now works -- no relink.
    _upload(client, port, "victim2.txt")
    status, j = client.j("POST", "/api/guestdelete", {"allowed": True})
    assert status == 200 and j["ok"] and j["guest_delete_allowed"] is True, j
    assert _files(guest) == ["victim2.txt"]  # same token, still valid
    status, j = guest.j("POST", "/api/delete", {"name": "victim2.txt"})
    assert status == 200 and j["ok"], j
    # Toggle back OFF: delete is forbidden again immediately, and
    # the token is still valid for files.
    _upload(client, port, "victim3.txt")
    status, j = client.j("POST", "/api/guestdelete", {"allowed": False})
    assert status == 200 and j["ok"] and j["guest_delete_allowed"] is False, j
    assert _files(guest) == ["victim3.txt"]
    status, j = guest.j("POST", "/api/delete", {"name": "victim3.txt"})
    assert status == 403 and j["error"] == GUEST_NOT_AUTH, j
    assert _files(guest) == ["victim3.txt"]
    # Toggle state persists across a server restart.
    status, j = client.j("POST", "/api/guestdelete", {"allowed": True})
    assert status == 200 and j["ok"], j
    proc.terminate()
    proc.wait(timeout=10)
    port2 = _free_port()
    env = dict(os.environ)
    env["HOME"] = str(home)
    proc2 = subprocess.Popen(
        [sys.executable, str(__import__("pathlib").Path(
            os.path.dirname(os.path.dirname(__file__))) / "dropit.py"),
         "--port", str(port2)],
        cwd=base, env=env, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
    try:
        host2 = Client(port2)
        for _ in range(50):
            try:
                status, st = host2.j("GET", "/api/authstate")
                if status == 200:
                    break
            except OSError:
                time.sleep(0.2)
        assert status == 200 and st["guest_delete_allowed"] is True, st
    finally:
        proc2.terminate()
        proc2.wait(timeout=10)


def test_guest_delete_scope_files_only_not_notes(server):
    # v2.7.90 SUPERSEDES: notes deletion is now gated by its OWN
    # toggle ("Guests can delete notes", default OFF) -- the files
    # toggle still does not gate notes, and vice versa. Full
    # OFF/ON coverage lives in test_link_round6.
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "scopetest", "password": "secret"})
    assert status == 200 and j["ok"], j
    guest = _guest_client(port, "secret")
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    status, j = guest.j("POST", "/api/snippet", {"text": "guest note"})
    assert status == 200 and j["ok"], j
    nid = j["id"]
    status, j = guest.j("POST", "/api/notes/delete", {"id": nid})
    assert status == 403 and j["error"] == (
        "No permission to delete notes from this device"), j


# ------------------------------------------------------------- folder hiding

def test_guest_authstate_connect_and_page_hide_host_folder(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "folderhide", "password": "secret"})
    assert status == 200 and j["ok"], j
    guest = _guest_client(port, "secret")
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    status, st = guest.j("GET", "/api/authstate")
    assert "folder" not in st, st
    status, st = client.j("GET", "/api/authstate")
    assert "folder" in st and str(base) in st["folder"], st
    status, j = guest.j("POST", "/api/connect", {"link": "folderhide"})
    assert status == 200 and j["ok"], j
    assert "folder" not in j, j
    status, j = client.j("POST", "/api/connect", {"link": "folderhide"})
    assert status == 200 and j["ok"] and "folder" in j, j
    # Served page for a guest carries no host absolute path.
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/", headers={
        "Cookie": "drop_sess=" + guest.cookies["drop_sess"]})
    resp = conn.getresponse()
    html = resp.read().decode("utf-8")
    conn.close()
    assert resp.status == 200
    assert str(base) not in html
    # The save-destination line div itself is stripped for guests
    # (server-side), not merely hidden -- and carries no path.
    assert 'id="landline"' not in html
    assert "they land in" not in html


# ----------------------------------------------------------- password logic

def test_password_optional_open_link_required_password_link(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "openlink"})
    assert status == 200 and j["ok"], j
    # Open link + blank password: connect succeeds, no login needed.
    plain = Client(port)
    status, j = plain.j("POST", "/api/connect",
                        {"link": "openlink", "password": ""})
    assert status == 200 and j["ok"] and j["authed"] is True, j
    # Password link + blank password: login is a clear rejection,
    # not a client-side "required" block. (A blank CONNECT from a
    # tokenless localhost caller correctly reports authed True --
    # localhost IS the host -- so the tokenless-guest connect
    # refusal is covered by the LAN unit test below, where
    # _profile() is None for a LAN caller on a password link and
    # /api/connect's "authed" field is exactly that result.)
    status, j = client.j("POST", "/api/setlink",
                         {"name": "pwlink", "password": "secret"})
    assert status == 200 and j["ok"], j
    blank = Client(port)
    status, j = blank.j("POST", "/api/login", {"password": ""})
    assert status == 200 and j["ok"] is False, j
    status, j = blank.j("POST", "/api/login", {"password": "wrong"})
    assert status == 200 and j["ok"] is False, j
    # Correct password admits.
    status, j = blank.j("POST", "/api/login", {"password": "secret"})
    assert status == 200 and j["ok"], j
    status, files = blank.j("GET", "/api/files")
    assert status == 200, files


def test_empty_link_connect_rejected_400(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "keeplink"})
    assert status == 200 and j["ok"], j
    status, j = client.j("POST", "/api/connect", {"link": ""})
    assert status == 400 and j.get("code") == "invalid_link_name", j
    status, st = client.j("GET", "/api/authstate")
    assert st["link_name"] == "keeplink", st


# ------------------------------------------------------- validation identical

def test_connect_validation_identical_server_and_clients(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "validlink"})
    assert status == 200 and j["ok"], j
    for bad in ("my.link", "has space", "UP!", "x" * 33, "-lead"):
        status, j = client.j("POST", "/api/connect", {"link": bad})
        assert status == 400 and j.get("code") == "invalid_link_name", (bad, j)
        status, st = client.j("GET", "/api/authstate")
        assert st["link_name"] == "validlink", (bad, st)
    # Valid names that are simply NOT the current link are 409
    # wrong_link, not 400: the server regex permits a trailing
    # hyphen and an underscore after the first character
    # (^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$), so "trail-" and
    # "under_score" are valid-format, wrong-link names.
    for valid_wrong in ("otherlink", "trail-", "under_score"):
        status, j = client.j("POST", "/api/connect",
                             {"link": valid_wrong})
        assert status == 409 and j.get("code") == "wrong_link", (valid_wrong, j)
    # Web validateLinkName uses the server-verbatim messages.
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/")
    html = conn.getresponse().read().decode("utf-8")
    conn.close()
    assert DOT_MSG in html
    assert RULES_MSG in html
    assert "shakeAddressField" in html
    # APK validateLinkName uses the same verbatim messages and
    # shakes the field on failure (code-path, no emulator here).
    apk = __import__("pathlib").Path.home() / "workspace" / "dropit-android" \
        / "app" / "src" / "main" / "java" / "com" / "dropit" / "app" \
        / "MainActivity.kt"
    src = apk.read_text(encoding="utf-8")
    assert DOT_MSG in src
    assert RULES_MSG in src
    assert src.count("shakeView") >= 3
    assert "Enter an address first" in src


# ------------------------------------------------- guest design + send state

def test_served_page_round5_guest_design_send_state_tabs_hover(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "round5page", "password": "secret"})
    assert status == 200 and j["ok"], j
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/")
    html = conn.getresponse().read().decode("utf-8")
    conn.close()
    # Final toggle label, verbatim -- and NOT the superseded ones.
    assert "Guests can delete files" in html
    assert "Devices can delete files" not in html
    assert "Allow connected devices to delete files on this pc" not in html
    assert "Allow guest devices to delete files" not in html
    assert 'id="swguestdel"' in html and 'id="swguestnotesdel"' in html
    assert 'id="swguestlock"' not in html  # v2.7.90: lock switch gone
    # Guest link-page design cards.
    assert 'id="guestcardhead"' in html
    assert 'id="guestlinkcard"' in html
    # v2.7.95 Title Case (was "Connect to a PC").
    assert "Connect To A PC" in html
    # Send-tab connection state, server-rendered.
    visible = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    visible = re.sub(r"<style.*?</style>", "", visible, flags=re.S)
    visible = re.sub(r"<[^>]+>", " ", visible)
    assert "round5page" in visible
    assert "Address: round5page" not in visible  # v2.7.94: top pill is icon + coloured name, no "Address:" text
    assert "Not connected" in html  # fallback text for no-link state
    # Greyed-out delete + exact toast, web code paths.
    assert GUEST_NOT_AUTH in html
    assert "deloff" in html
    # v2.7.90 SUPERSEDES the tab-style redesign: pre-tab button
    # design restored, no tab-shape class or rule remains (the
    # count badge .tabbadge is kept -- it is a badge, not a shape).
    assert "tabbadge" in html
    assert ".tabbtn {" not in html
    assert re.search(r'class="[^"]*tabbtn', html) is None
    assert "tabState" not in html and "activeTab" not in html
    # Hover popups on all in-scope buttons.
    for tip in ("Open the save folder on this PC",
                "Change the save folder for this address",
                "Save this address", "Show or hide the password",
                "Remove the address password", "Copy the address name",
                "Show the large QR code", "Delete files",
                "Add a new shared text"):
        assert f'data-tip="{tip}"' in html, tip
    # The hovertip element is created by JS at runtime (not static
    # HTML), so assert its JS creation + show/hide functions.
    assert "hovertip" in html and "showHovertip" in html
    # Guest password label/placeholder never imply "required".
    # v2.7.95 Title Case (was "Password (optional)" /
    # "Password for this address").
    assert "Password (Optional)" in html
    assert "Password For This Address" in html
    # Empty guest Save is blocked before any connect call.
    assert "Enter an address first" in html
    # APK guest link-page design + send state (code/layout paths).
    apk_base = __import__("pathlib").Path.home() / "workspace" \
        / "dropit-android" / "app" / "src" / "main"
    link_layout = (apk_base / "res" / "layout" / "dialog_link.xml") \
        .read_text(encoding="utf-8")
    assert "Set up your addresses" in link_layout
    assert "lkConnState" in link_layout
    main_src = (apk_base / "java" / "com" / "dropit" / "app"
                / "MainActivity.kt").read_text(encoding="utf-8")
    assert '"Address: "' in main_src or "Address: $" in main_src
    assert '"Not connected"' in main_src
    assert "Press back again to close the app" in main_src
    assert "2000" in main_src
    assert "finish()" in main_src
    assert "longTip" in main_src
    # v2.7.90 SUPERSEDES tab shapes: tab_btn.xml was deliberately
    # deleted in the button restoration, so it must NOT exist.
    assert not (apk_base / "res" / "drawable" / "tab_btn.xml").exists()


# ------------------------------------------------- in-process LAN unit tests

class _H:
    """A Handler built without __init__: client_address is a LAN
    IP, headers a plain mapping, server a stub with a bridge token.
    _config_path is monkeypatched to the test tmp config. Methods
    are delegated to the real Handler class via __getattr__."""

    def __init__(self, cfg_path, ip="192.168.1.7", headers=None,
                 host_token=""):
        self._handler = object.__new__(D.Handler)
        self._handler.client_address = (ip, 54321)
        self._handler.headers = dict(headers or {})
        self._handler.server = SimpleNamespace(host_token=host_token)
        self._handler._prof_cache = None
        self._handler._cfg_cache = None
        self._orig_cfg_path = D._config_path
        D._config_path = lambda: str(cfg_path)

    def __getattr__(self, name):
        return getattr(self._handler, name)

    def close(self):
        D._config_path = self._orig_cfg_path


def _write_cfg(path, **over):
    cfg = {"link_name": "lanlink", "link_pass": "", "sessions": {},
           "guest_locked": False, "guest_lock_seq": 0,
           "guest_delete_allowed": False}
    cfg.update(over)
    path.write_text(json.dumps(cfg))
    return cfg


def test_lan_profile_tokenless_and_locked(tmp_path):
    # v2.7.90 SUPERSEDES: a legacy guest_locked flag is IGNORED
    # (guest-lock retired) -- tokenless LAN access on a
    # passwordless link is authed with or without the flag.
    cfg_path = tmp_path / "config.json"
    _write_cfg(cfg_path)
    h = _H(cfg_path)
    try:
        assert h._profile() == "default"
    finally:
        h.close()
    _write_cfg(cfg_path, guest_locked=True, guest_lock_seq=1)
    h = _H(cfg_path)
    try:
        assert h._profile() == "default"
    finally:
        h.close()
    _write_cfg(cfg_path, guest_locked=False, guest_lock_seq=1)
    h = _H(cfg_path)
    try:
        assert h._profile() == "default"
    finally:
        h.close()


def test_lan_profile_password_link_and_forged_host(tmp_path):
    cfg_path = tmp_path / "config.json"
    _write_cfg(cfg_path, link_pass="hash$fake")
    # Tokenless LAN guest on a password link -> unauthed.
    h = _H(cfg_path)
    try:
        assert h._profile() is None
        # A forged host claim (wrong bridge token, or a stale
        # drop_locked cookie) does NOT make a LAN caller the host.
        h2 = _H(cfg_path, headers={"X-Drop-Host": "forged",
                                   "Cookie": "drop_locked=1"})
        try:
            assert h2._profile() is None
            assert h2._require_host() is False
        finally:
            h2.close()
        # A REAL bridge token from the LAN origin DOES prove host
        # (the desktop window loaded via a LAN IP).
        h3 = _H(cfg_path, headers={"X-Drop-Host": "bridge123"},
                host_token="bridge123")
        try:
            assert h3._profile() == "default"
            assert h3._require_host() is True
        finally:
            h3.close()
    finally:
        h.close()


def test_lan_profile_guest_lock_seq_and_delete_toggle(tmp_path):
    # v2.7.90 SUPERSEDES: lock_seq / guest_locked no longer gate
    # (retired); the delete toggle behaviour is unchanged.
    cfg_path = tmp_path / "config.json"
    tok = "guesttok123456"
    _write_cfg(cfg_path, link_pass="hash$fake", guest_locked=True,
               guest_lock_seq=1,
               sessions={tok: {"role": "guest", "link": "lanlink",
                               "lock_seq": 0, "ip": "192.168.1.7",
                               "ts": 1}})
    h = _H(cfg_path, headers={"Cookie": "drop_sess=" + tok})
    try:
        assert h._profile() == "default"
        assert h._can_delete_files() is False  # toggle OFF
    finally:
        h.close()
    _write_cfg(cfg_path, link_pass="hash$fake", guest_locked=True,
               guest_lock_seq=1, guest_delete_allowed=True,
               sessions={tok: {"role": "guest", "link": "lanlink",
                               "lock_seq": 1, "ip": "192.168.1.7",
                               "ts": 1}})
    h = _H(cfg_path, headers={"Cookie": "drop_sess=" + tok})
    try:
        assert h._can_delete_files() is True
    finally:
        h.close()
    _write_cfg(cfg_path, link_pass="hash$fake", guest_locked=True,
               guest_lock_seq=1, guest_delete_allowed=False,
               sessions={})
    h = _H(cfg_path, ip="127.0.0.1")
    try:
        assert h._can_delete_files() is True
        assert h._require_host() is True
    finally:
        h.close()
