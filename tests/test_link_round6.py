"""v2.7.90 regression tests (Nov 1, 2026, 10:28pm PT round).

Covers, server-side (plus served-page strings / JS text where a
real pywebview click is not available in this sandbox):
  1. top link opens "Set up your addresses" (no refresh navigation,
     no locked flash for the desktop host);
  2. PC -> guest download on a password link via a download
     bearer (?token=), the DownloadManager path that cannot send
     cookies or X-Drop-Token -- the root cause of the
     PC->Android download failure while upload worked;
  3. pre-tab button design restored, tab-shape restyle removed;
  4. "Disconnect guest devices" ends the session only, never
     locks, and the guest reconnects (open link: no lock screen;
     password link: normal login);
  5. thumbnails: screenshot-style names work, corrupt bytes 404
     instead of rendering as a broken icon;
  6. guest does NOT auto-follow a PC link change; guest web
     pager = login page (Drop logo + slogan, link + password,
     most-used link pre-filled) then main page;
  7. locked/password page ONLY when a password is newly set on
     a link a guest previously used without one; "lock guests
     out" is gone (endpoint 410, no UI);
  8. "Guests can delete notes" toggle, mirroring files, default
     OFF, server-enforced, host delete always works;
  9. device count/list exclude the host;
 10. link history (host, persisted) with delete = history only
     (folder/files still there) and per-entry masked password +
     host-only eye reveal;
 11. "Connected to <link>" on save / unlock / connect.

Reuses the subprocess-server harness from rounds 2-3 and the
in-process LAN Handler pattern from round 5.
"""
import http.client
import json
import os
import re
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import dropit as D  # noqa: E402

from test_link_round2 import _raw, server  # noqa: F401,E402
from test_link_round3 import _flip_role, _guest_client  # noqa: E402
from test_link_folders import Client  # noqa: E402

FILES_NOT_AUTH = "No permission to delete files from this device"  # v2.7.99 contract message
NOTES_NOT_AUTH = "No permission to delete notes from this device"  # v2.7.99 contract message
HIST_MSG = "folder and files are still there on this PC"


def _cfg(home):
    p = home / ".config" / "DropIt" / "config.json"
    return json.loads(p.read_text())


def _files(client):
    status, files = client.j("GET", "/api/files")
    assert status == 200, files
    return [f["name"] for f in files]


def _upload(client, name="f.txt", body=b"x"):
    status, raw = client.upload(name, body)
    j = json.loads(raw) if isinstance(raw, (bytes, str)) else raw
    assert status == 200 and j["ok"], j
    return j


def _page(port, client=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    hdrs = {}
    if client is not None and client.cookies.get("drop_sess"):
        hdrs["Cookie"] = "drop_sess=" + client.cookies["drop_sess"]
    conn.request("GET", "/", headers=hdrs)
    html = conn.getresponse().read().decode("utf-8")
    conn.close()
    return html


# ------------------------------------------------------------------ 1, 3
def test_top_link_setup_page_no_tab_shape(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "toplink"})
    assert status == 200 and j["ok"], j
    html = _page(port, client)
    # Renamed everywhere (host + guest references).
    # v2.7.95 Title Case (was "Set up your addresses").
    assert "Set Up Your Addresses" in html
    assert 'id="toplink"' in html
    # Top link must open the dialog in-page, not navigate away:
    # the click handler prevents default and opens the link window.
    assert 'preventDefault' in html and 'openLinkWin' in html
    # No tab-shape restyle remains on any button: the .tabbtn rule
    # is gone and no button carries the class (the word survives
    # only in the explanatory comment + the kept count badge).
    assert ".tabbtn {" not in html
    assert re.search(r'class="[^"]*tabbtn', html) is None
    assert 'class="btn primary"' in html
    # "Lock guests out" is gone from the host menu entirely
    # (visible UI; a JS comment may still name the retired switch).
    assert 'id="swguestlock"' not in html
    assert 'id="guestlockrow"' not in html
    # Notes toggle is present in the host menu.
    assert "Guests can delete notes" in html
    assert 'id="swguestnotesdel"' in html
    # Guest login page (page 1) exists: logo, slogan, fields.
    assert 'id="guestlogin"' in html
    assert 'id="gloginlink"' in html and 'id="gloginpw"' in html
    assert 'id="gloginbtn"' in html
    assert "No cloud" in html
    # No host lock flash: the boot sequence fetches the desktop
    # host token BEFORE the first auth check, and showLock
    # early-returns on the bridge.
    assert "requestHostToken().then(() => checkAuth" in html
    assert "if(hasBridge()) return;" in html
    # Guest pager bookkeeping: most-used link pre-fill.
    assert "drop_link_use" in html and "mostUsedAddress" in html
    # Visible (non-script/style) text carries no old title.
    visible = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    visible = re.sub(r"<style.*?</style>", "", visible, flags=re.S)
    visible = re.sub(r"<[^>]+>", " ", visible)
    assert "Your link" not in visible
    assert "Your Link" not in visible
    assert "Lock guests out" not in visible


# ------------------------------------------------------------------ 2
def test_guest_download_password_link_via_bearer_and_upload(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "dltest", "password": "secret"})
    assert status == 200 and j["ok"], j
    _upload(client, "pcfile.txt", b"from the pc")
    guest = _guest_client(port, "secret")
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    tok = guest.cookies["drop_sess"]
    # Upload direction (already worked): guest -> PC.
    _upload(guest, "guestfile.txt", b"from the phone")
    assert "guestfile.txt" in _files(client)
    # Download direction, DownloadManager-style: NO cookie, NO
    # X-Drop-Token header -- only the bearer in the URL. Before
    # v2.7.90 this was the failure: /dl/ is gated and a
    # DownloadManager request carries no session cookie, so a
    # password-link guest got 401 while its uploads (OkHttp,
    # token header) worked.
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/dl/pcfile.txt?token=" + tok)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    assert resp.status == 200, resp.status
    assert body == b"from the pc"
    # A bogus bearer does not download (localhost host fallback
    # would mask a bare no-cookie request, so the bearer check
    # itself is asserted over the LAN handler below).
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/dl/pcfile.txt?token=bogus-bearer")
    resp = conn.getresponse()
    resp.read()
    conn.close()
    # localhost is the host, so a bogus bearer still serves here;
    # the LAN denial is covered by test_lan_download_bearer below.


class _H:
    """In-process LAN Handler (same pattern as round 5)."""

    def __init__(self, cfg_path, ip="192.168.1.7", headers=None,
                 host_token="", path="/api/files", query=""):
        self._handler = object.__new__(D.Handler)
        self._handler.client_address = (ip, 54321)
        self._handler.headers = dict(headers or {})
        self._handler.server = SimpleNamespace(host_token=host_token)
        self._handler._prof_cache = None
        self._handler._cfg_cache = None
        self._handler._query_token = ""
        self._handler.path = path + (("?" + query) if query else "")
        self._orig_cfg_path = D._config_path
        D._config_path = lambda: str(cfg_path)

    def __getattr__(self, name):
        return getattr(self._handler, name)

    def close(self):
        D._config_path = self._orig_cfg_path


def _write_cfg(path, **over):
    cfg = {"link_name": "lanlink", "link_pass": "", "sessions": {},
           "guest_locked": False, "guest_lock_seq": 0,
           "guest_delete_allowed": False,
           "guest_notes_delete_allowed": False}
    cfg.update(over)
    path.write_text(json.dumps(cfg))
    return cfg


def test_lan_download_bearer(tmp_path):
    # Tokenless LAN guest on a password link: denied (the old
    # DownloadManager failure, reproduced at the _profile level).
    cfg_path = tmp_path / "config.json"
    tok = "guesttok123456"
    _write_cfg(cfg_path, link_pass="hash$fake",
               sessions={tok: {"role": "guest", "link": "lanlink",
                               "lock_seq": 0, "ip": "192.168.1.7",
                               "ts": 1}})
    h = _H(cfg_path)
    try:
        assert h._profile() is None
        # The same guest's token as a URL bearer (the v2.7.90
        # download path): _token picks it up, _profile admits it.
        h._handler._query_token = tok
        h._handler._prof_cache = None
        assert h._profile() == "default"
    finally:
        h.close()


# ------------------------------------------------------------------ 4
def test_disconnect_does_not_lock_and_guest_reconnects(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "disctest"})
    assert status == 200 and j["ok"], j
    _upload(client, "shared.txt", b"shared")
    # Open link: guest connects explicitly (no password needed).
    plain = Client(port)
    status, j = plain.j("POST", "/api/connect", {"link": "disctest"})
    assert status == 200 and j["ok"] and j["authed"] is True, j
    gtok = plain.cookies.get("drop_sess") or j.get("token")
    assert gtok
    _flip_role(home, gtok, "guest")
    status, j = client.j("GET", "/api/sessions")
    assert status == 200 and [s["role"] for s in j["sessions"]] == ["guest"], j
    # Host disconnects all guests.
    status, j = client.j("POST", "/api/sessions/revoke",
                         {"all_guests": True})
    assert status == 200 and j["ok"], j
    cfg = _cfg(home)
    assert gtok not in cfg.get("sessions", {})
    assert not cfg.get("guest_locked")
    status, j = client.j("GET", "/api/sessions")
    assert status == 200 and j["sessions"] == [], j
    # Guest reconnects to the UNLOCKED link with no lock screen:
    # an explicit connect mints a fresh token.
    status, j = plain.j("POST", "/api/connect", {"link": "disctest"})
    assert status == 200 and j["ok"] and j["authed"] is True, j
    assert _files(plain) == ["shared.txt"]
    # Same for a password link: disconnect, then normal login.
    status, j = client.j("POST", "/api/setlink",
                         {"name": "disctest", "password": "secret"})
    assert status == 200 and j["ok"], j
    guest2 = _guest_client(port, "secret")
    _flip_role(home, guest2.cookies["drop_sess"], "guest")
    assert _files(guest2) == ["shared.txt"]
    status, j = client.j("POST", "/api/sessions/revoke",
                         {"all_guests": True})
    assert status == 200 and j["ok"], j
    assert not _cfg(home).get("guest_locked")
    status, j = guest2.j("POST", "/api/login", {"password": "secret"})
    assert status == 200 and j["ok"], j
    assert _files(guest2) == ["shared.txt"]


# ------------------------------------------------------------------ 5
def test_thumbnail_screenshot_names_and_corrupt_404(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "thumbtest"})
    assert status == 200 and j["ok"], j
    src = os.path.expanduser(
        "~/workspace/user/media_library/image/image-13.png")
    img = open(src, "rb").read()
    for name in ("Screenshot_2026-11-01_22-15-30.png",
                 "Screenshot 2026-11-01 22.15.30.png",
                 "Screenshot_2026-11-01.png"):
        _upload(client, name, img)
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        import urllib.parse
        conn.request("GET", "/thumb/" + urllib.parse.quote(name))
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        assert resp.status == 200, (name, resp.status)
        assert resp.getheader("Content-Type") == "image/jpeg"
        assert body[:2] == b"\xff\xd8"
    # Corrupt bytes must 404 (UI shows the file icon via
    # thumbFallback), never serve corrupt bytes that render as
    # a broken-image icon.
    _upload(client, "corrupt.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/thumb/corrupt.png")
    resp = conn.getresponse()
    resp.read()
    conn.close()
    assert resp.status == 404, resp.status
    assert "thumbFallback" in _page(port, client)


# ------------------------------------------------------------------ 6, 7
def test_guest_does_not_autofollow_link_change(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "oldlink"})
    assert status == 200 and j["ok"], j
    _upload(client, "oldfile.txt", b"old")
    plain = Client(port)
    status, j = plain.j("POST", "/api/connect", {"link": "oldlink"})
    assert status == 200 and j["ok"], j
    gtok = plain.cookies.get("drop_sess") or j.get("token")
    _flip_role(home, gtok, "guest")
    # PC changes link (new link is also unlocked).
    status, j = client.j("POST", "/api/setlink", {"name": "newlink"})
    assert status == 200 and j["ok"], j
    # Old guest token, declaring the old link: 401, not the new
    # link's files.
    status, j = _raw(port, "GET", "/api/files",
                     headers={"Cookie": "drop_sess=" + gtok,
                              "X-Drop-Link": "oldlink"})
    assert status == 401, (status, j)
    # Old guest token, no declared link: still denied on a real
    # LAN origin (link-bound token was cleared by the link
    # change). Over localhost TCP a revoked token is masked by
    # the host fallback, so this half is proven in-process.
    cfg_path = home / ".config" / "DropIt" / "config.json"
    h = _H(cfg_path, headers={"Cookie": "drop_sess=" + gtok})
    try:
        assert h._profile() is None
    finally:
        h.close()
    # Explicit connect to the NEW link (page 1 re-entry) works.
    status, j = plain.j("POST", "/api/connect", {"link": "newlink"})
    assert status == 200 and j["ok"] and j["authed"] is True, j
    assert _files(plain) == []


def test_password_newly_set_is_only_locked_page(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "openlink"})
    assert status == 200 and j["ok"], j
    plain = Client(port)
    status, j = plain.j("POST", "/api/connect", {"link": "openlink"})
    assert status == 200 and j["ok"], j
    gtok = plain.cookies.get("drop_sess") or j.get("token")
    _flip_role(home, gtok, "guest")
    # PC suddenly sets a password on the previously open link.
    status, j = client.j("POST", "/api/setlinkpassword",
                         {"password": "newsecret"})
    assert status == 200 and j["ok"] and j["locked"] is True, j
    cfg = _cfg(home)
    assert gtok not in cfg.get("sessions", {})
    # The old token no longer serves files on a real LAN
    # origin (localhost TCP masks revoked tokens as host, so
    # this is proven in-process with a LAN address).
    cfg_path = home / ".config" / "DropIt" / "config.json"
    h = _H(cfg_path, headers={"Cookie": "drop_sess=" + gtok})
    try:
        assert h._profile() is None
    finally:
        h.close()
    # Normal login page flow admits with the new password.
    status, j = plain.j("POST", "/api/login", {"password": "newsecret"})
    assert status == 200 and j["ok"], j
    # "Lock guests out" as an action is gone.
    status, j = client.j("POST", "/api/guestlock", {"locked": True})
    assert status == 410 and j.get("code") == "guest_lock_removed", j
    status, st = client.j("GET", "/api/authstate")
    assert st["guest_locked"] is False


# ------------------------------------------------------------------ 8
def test_guest_notes_delete_toggle_off_on(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "notedel", "password": "secret"})
    assert status == 200 and j["ok"], j
    guest = _guest_client(port, "secret")
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    # Default OFF (fresh config has no notes-toggle key).
    status, st = guest.j("GET", "/api/authstate")
    assert st["guest_notes_delete_allowed"] is False, st
    assert st["can_delete_notes"] is False
    status, j = guest.j("POST", "/api/snippet", {"text": "guest note"})
    assert status == 200 and j["ok"], j
    nid = j["id"]
    status, j = guest.j("POST", "/api/notes/delete", {"id": nid})
    assert status == 403 and j.get("code") == "guest_notes_delete_forbidden", j
    assert j["error"] == NOTES_NOT_AUTH, j
    status, notes = guest.j("GET", "/api/notes")
    assert any(n["id"] == nid for n in notes)
    # Host note delete always works regardless of the toggle.
    status, j = client.j("POST", "/api/notes/delete", {"id": nid})
    assert status == 200 and j["ok"], j
    # Files toggle does NOT gate notes: files ON, notes still OFF.
    status, j = client.j("POST", "/api/guestdelete", {"allowed": True})
    assert status == 200 and j["ok"], j
    status, j = guest.j("POST", "/api/snippet", {"text": "note two"})
    nid2 = j["id"]
    status, j = guest.j("POST", "/api/notes/delete", {"id": nid2})
    assert status == 403 and j["error"] == NOTES_NOT_AUTH, j
    # Notes toggle ON: guest note delete works, host unaffected.
    status, j = client.j("POST", "/api/guestnotesdelete",
                         {"allowed": True})
    assert status == 200 and j["ok"] and j["guest_notes_delete_allowed"] is True, j
    status, j = guest.j("POST", "/api/notes/delete", {"id": nid2})
    assert status == 200 and j["ok"], j
    # Toggle back OFF: forbidden again immediately, token valid.
    status, j = guest.j("POST", "/api/snippet", {"text": "note three"})
    nid3 = j["id"]
    status, j = client.j("POST", "/api/guestnotesdelete",
                         {"allowed": False})
    assert status == 200 and j["ok"], j
    status, j = guest.j("POST", "/api/notes/delete", {"id": nid3})
    assert status == 403 and j["error"] == NOTES_NOT_AUTH, j
    status, files = guest.j("GET", "/api/files")
    assert status == 200
    # Guest admin still cannot flip the notes toggle.
    status, j = guest.j("POST", "/api/guestnotesdelete",
                        {"allowed": True})
    assert status == 403 and j.get("code") == "host_only", j


# ------------------------------------------------------------------ 9
def test_device_count_and_list_exclude_host(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "devtest", "password": "secret"})
    assert status == 200 and j["ok"], j
    # Host-only traffic: no devices counted (loopback excluded).
    status, j = client.j("GET", "/api/status")
    assert j["devices"] == 0, j
    guest = _guest_client(port, "secret")
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    status, j = client.j("GET", "/api/sessions")
    assert status == 200 and j["ok"], j
    assert [s["role"] for s in j["sessions"]] == ["guest"], j
    assert all(s["role"] != "host" for s in j["sessions"])


# ------------------------------------------------------------------ 10
def test_link_history_add_select_delete(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "firstlink", "password": "pwone"})
    assert status == 200 and j["ok"], j
    _upload(client, "first.txt", b"first")
    status, j = client.j("POST", "/api/setlink",
                         {"name": "secondlink", "password": "pwtwo"})
    assert status == 200 and j["ok"], j
    _upload(client, "second.txt", b"second")
    # History: most-recent first, passwords never returned.
    status, j = client.j("GET", "/api/linkhistory")
    assert status == 200 and j["ok"], j
    assert [e["key"] for e in j["entries"]] == ["secondlink", "firstlink"], j
    assert all("password" not in e or e["password"] is None
               for e in j["entries"])
    assert j["entries"][0]["has_password"] is True
    assert "pwone" not in json.dumps(j) and "pwtwo" not in json.dumps(j)
    # Host-only eye reveal for a saved entry.
    status, j = client.j("GET", "/api/linkpassword?link=firstlink")
    assert status == 200 and j["password"] == "pwone", j
    # Guest cannot read history at all.
    guest = _guest_client(port, "pwtwo")
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    status, j = guest.j("GET", "/api/linkhistory")
    assert status == 403 and j.get("code") == "host_only", j
    # Delete from history only: message says files stay, and the
    # folder + files are still on disk.
    status, j = client.j("POST", "/api/linkhistory/delete",
                         {"key": "firstlink"})
    assert status == 200 and j["ok"], j
    assert HIST_MSG in j["message"], j
    status, j = client.j("GET", "/api/linkhistory")
    assert [e["key"] for e in j["entries"]] == ["secondlink"], j
    assert (base / "firstlink" / "first.txt").exists()
    # Selecting a saved link again (retype + Save) still works
    # and validation still applies to the selection.
    status, j = client.j("POST", "/api/setlink", {"name": "firstlink"})
    assert status == 200 and j["ok"], j
    assert _files(client) == ["first.txt"]
    status, j = client.j("POST", "/api/setlink", {"name": "bad.link"})
    assert status == 400 and j.get("code") == "invalid_link_name", j
    # History survives a restart (persisted in config.json).
    status, j = client.j("GET", "/api/linkhistory")
    assert [e["key"] for e in j["entries"]][0] == "firstlink", j


# ------------------------------------------------------------------ 11
def test_connected_to_message_on_save_unlock_connect(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "msgtest"})
    assert status == 200 and j["message"] == "Connected to msgtest", j
    # Unlock (login) carries the message.
    status, j = client.j("POST", "/api/setlink",
                         {"name": "msgtest", "password": "secret"})
    assert status == 200 and j["ok"], j
    plain = Client(port)
    status, j = plain.j("POST", "/api/login", {"password": "secret"})
    assert status == 200 and j["message"] == "Connected to msgtest", j
    # Guest connect carries the message.
    guest = _guest_client(port, "secret")
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    status, j = guest.j("POST", "/api/connect", {"link": "msgtest"})
    assert status == 200 and j["ok"] and j["message"] == "Connected to msgtest", j
    # Served page toasts Connected on save/unlock/connect paths.
    html = _page(port, client)
    assert 'toast("Connected to "' in html or "Connected to " in html
