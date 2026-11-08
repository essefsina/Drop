"""Link-system round-4 regression tests (v2.7.87).

Covers the Nov 1, 2026 round-4 report against v2.7.86:

  - LOGIN STAMP BUG: after a host logout (drop_locked cookie set),
    the next login used to be stamped "guest" because the browser
    still sent the old cookie, so every admin endpoint 403d forever
    (Save / sessions / reveal dead while files still worked). A
    successful localhost login must now stamp "host" -- the login
    IS the unlock that clears the cookie.
  - LOCK ENFORCEMENT: a locked link gives a tokenless guest 401,
    rejects a wrong password, and admits the correct password.
  - GUEST DELETE: a guest setlinkpassword "" gets 403 host-only and
    the password is unchanged.
  - HOST SAVE KEEP: saving the same link with the password key
    OMITTED (prefilled password untouched) or with the same password
    value keeps the password AND does not disconnect guests
    (v2.7.86 cleared guest sessions unconditionally).
  - HOST SAVE NEW PASSWORD: sets the password, locks the link, and
    the old guest token stops working.
  - CONNECT MINTS A SESSION: a connect without a valid token mints
    one, so a connect-only guest shows up in the host's device list
    (v2.7.86: connect left no session, so "2 Devices Connected" in
    the top bar coexisted with an empty device list). Disconnecting
    that session revokes it.
  - SERVED PAGE: eye-explanation paragraph gone; New Link label +
    placeholder, never prefilled with the current name; guest screen
    hides the delete-password control; top-field copy is an icon
    (no "Copy" text in the top bar); QR button sits inside the
    narrowed centred field; QR popup is a small fixed centred
    popup with a close button; in-scope buttons use solid colours.

Reuses the subprocess-server harness from test_link_round2. The
sandbox cannot make a real LAN-IP connection, so LAN guests are
simulated exactly as in round 3: a login token whose role is flipped
to "guest" in config.json, plus the drop_locked cookie (which blocks
the localhost host bypass so a revoked token really reads as
unauthenticated).
"""
import http.client
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_link_folders import Client  # noqa: E402
from test_link_round2 import _raw, server  # noqa: E402,F401
from test_link_round3 import _flip_role, _guest_client  # noqa: E402

HOST_ONLY = "Only the host can change this - change it on the desktop"


def _page(port):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/")
    resp = conn.getresponse()
    html = resp.read().decode("utf-8")
    conn.close()
    assert resp.status == 200
    return html


def test_login_after_lockout_stamps_host_not_guest(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "lockloop", "password": "pw123"})
    assert status == 200 and j["ok"], j
    # Lock this device, then unlock: the login request still carries
    # the drop_locked cookie set by logout.
    status, j = client.j("POST", "/api/logout", {})
    assert status == 200 and j["ok"], j
    assert client.cookies.get("drop_locked") == "1"
    status, j = client.j("POST", "/api/login", {"password": "pw123"})
    assert status == 200 and j["ok"], j
    assert "drop_locked" not in client.cookies  # cleared by login
    # The host must be an admin again immediately -- not 403 forever.
    status, j = client.j("POST", "/api/setlink",
                         {"name": "lockloop", "password": "pw123"})
    assert status == 200 and j["ok"], j
    status, j = client.j("GET", "/api/sessions")
    assert status == 200 and j["ok"], j
    status, j = client.j("GET", "/api/linkpassword")
    assert status == 200 and j["password"] == "pw123", j


def test_lock_enforcement_guest_401_wrong_then_correct(server):
    # v2.7.89: a tokenless localhost caller is the host, so a
    # tokenless-guest 401 cannot be shown over localhost TCP (the
    # old drop_locked-cookie proxy is ignored now); that case is
    # covered by the in-process LAN-address tests in
    # test_link_round5.py. This TCP test keeps the password-gate
    # flow for a guest token: wrong password rejected, correct
    # password admits.
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "locked1", "password": "secret9"})
    assert status == 200 and j["ok"], j
    anon = Client(port)
    status, j = anon.j("POST", "/api/login", {"password": "wrong"})
    assert j["ok"] is False, j
    status, j = anon.j("POST", "/api/login", {"password": "secret9"})
    assert status == 200 and j["ok"], j
    _flip_role(home, anon.cookies["drop_sess"], "guest")
    status, files = anon.j("GET", "/api/files")
    assert status == 200, files


def test_guest_delete_password_403_and_password_kept(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "keeppw", "password": "donttouch"})
    assert status == 200 and j["ok"], j
    guest = _guest_client(port, "donttouch")
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    # A guest "delete" must never reach the host password endpoint.
    status, j = guest.j("POST", "/api/setlinkpassword", {"password": ""})
    assert status == 403 and j.get("code") == "host_only", j
    assert j["error"] == HOST_ONLY
    status, st = client.j("GET", "/api/authstate")
    assert st["locked"] is True
    status, j = client.j("GET", "/api/linkpassword")
    assert status == 200 and j["password"] == "donttouch", j


def test_host_save_prefilled_unchanged_keeps_password_and_guests(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "keepme", "password": "stayput"})
    assert status == 200 and j["ok"], j
    guest = _guest_client(port, "stayput")
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    status, _ = guest.j("GET", "/api/files")
    assert status == 200
    # Host Save with the password key OMITTED (prefilled untouched).
    status, j = client.j("POST", "/api/setlink", {"name": "keepme"})
    assert status == 200 and j["ok"], j
    assert j["sessions_cleared"] is False, j
    status, j = client.j("GET", "/api/linkpassword")
    assert status == 200 and j["password"] == "stayput", j
    status, _ = guest.j("GET", "/api/files")
    assert status == 200  # guest NOT disconnected by an unchanged Save
    # Same again with the same password value supplied explicitly.
    status, j = client.j("POST", "/api/setlink",
                         {"name": "keepme", "password": "stayput"})
    assert status == 200 and j["ok"], j
    assert j["sessions_cleared"] is False, j
    status, _ = guest.j("GET", "/api/files")
    assert status == 200


def test_host_save_new_password_sets_locks_and_logs_guests_out(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "newpw"})
    assert status == 200 and j["ok"], j
    # Unlocked link: guest connects (mints a session), then the host
    # sets a password -- the guest must be logged out.
    plain = Client(port)
    status, j = plain.j("POST", "/api/connect", {"link": "newpw"})
    assert status == 200 and j["ok"] and j.get("token"), j
    _flip_role(home, j["token"], "guest")  # LAN stand-in
    plain.cookies["drop_locked"] = "1"  # block localhost bypass
    status, _ = plain.j("GET", "/api/files")
    assert status == 200
    status, j = client.j("POST", "/api/setlink",
                         {"name": "newpw", "password": "brandnew"})
    assert status == 200 and j["ok"] and j["locked"] is True, j
    assert j["sessions_cleared"] is True, j
    status, j = client.j("GET", "/api/linkpassword")
    assert status == 200 and j["password"] == "brandnew", j
    # v2.7.89: old connect token dead on new password -- asserted
    # on the host session list (its LAN 401 cannot be shown over
    # localhost TCP; see test_link_round5.py).
    status, j = client.j("GET", "/api/sessions")
    assert status == 200 and j["ok"], j
    assert [s for s in j["sessions"] if s["role"] == "guest"] == []
    status, j = plain.j("POST", "/api/login", {"password": "brandnew"})
    assert status == 200 and j["ok"], j  # guest re-authenticates


def test_connect_mints_session_shown_and_disconnectable(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "connlink"})
    assert status == 200 and j["ok"], j
    # Two live connect-only sessions (each mints its own token).
    c1 = Client(port)
    status, j1 = c1.j("POST", "/api/connect", {"link": "connlink"})
    assert status == 200 and j1["ok"] and j1.get("token"), j1
    c2 = Client(port)
    status, j2 = c2.j("POST", "/api/connect", {"link": "connlink"})
    assert status == 200 and j2["ok"] and j2.get("token"), j2
    assert j1["token"] != j2["token"]
    # Same client reconnecting reuses its token (no duplicates).
    status, j1b = c1.j("POST", "/api/connect", {"link": "connlink"})
    assert status == 200 and j1b["ok"] and "token" not in j1b, j1b
    # Flip both to guest (LAN stand-in) and check the host list.
    _flip_role(home, j1["token"], "guest")
    _flip_role(home, j2["token"], "guest")
    status, j = client.j("GET", "/api/sessions")
    assert status == 200 and j["ok"], j
    guests = [s for s in j["sessions"] if s["role"] == "guest"]
    assert len(guests) == 2, j["sessions"]
    # Disconnect one: its files go 401 (drop_locked blocks bypass).
    c1.cookies["drop_locked"] = "1"
    status, _ = c1.j("GET", "/api/files")
    assert status == 200
    victim = [s for s in guests
              if j1["token"].startswith(s["id"])][0]
    status, j = client.j("POST", "/api/sessions/revoke",
                         {"id": victim["id"]})
    assert status == 200 and j["revoked"] == 1, j
    # The revoked session is gone from the host list; the other
    # guest is untouched. (On an unlocked link, file USE stays open
    # to tokenless callers by design -- revocation removes the
    # session, it does not lock an unlocked link.)
    status, j = client.j("GET", "/api/sessions")
    assert status == 200 and j["ok"], j
    guests = [s for s in j["sessions"] if s["role"] == "guest"]
    assert len(guests) == 1, j["sessions"]
    assert guests[0]["id"] == j2["token"][:12], guests


def test_served_page_round4(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "10-30-99"})
    assert status == 200 and j["ok"], j
    html = _page(port)
    # 5. Eye-explanation paragraph entirely gone.
    assert "the eye shows the saved password too" not in html
    assert "id=\"lkpwnote\"" not in html
    # Host Save keep semantics: omit-key, not always-send.
    assert "if(lkPwTouched) body.password = pw" in html
    assert '{"name, password: pw}' not in html
    # 2. New Link label + placeholder, never prefilled.
    # v2.7.95 Title Case (was "New address").
    assert 'id="lklinklabel">New Address<' in html
    assert 'id="lkin" placeholder="New Address"' in html
    assert "inp.value = st.address_name" not in html
    # Guest screen hides the delete-password control.
    assert 'show("#lkremovepwbtn", host)' in html
    assert 'show("#lkfolderrow", host)' in html
    # Password-to-New-Link gap tightened (was 16px label margin).
    assert "margin:10px 0 6px" in html
    # 7. Eye/delete buttons stretch to exactly the field height.
    assert ".lkpwrow { display:flex; gap:8px; align-items:stretch; }" in html
    assert "height:auto" in html
    # 8 + copy-icon follow-up: top field narrowed + centred, QR
    # inside it, copy is an icon, QR popup small + centred + close.
    assert "width:clamp(280px, 24vw, 420px)" in html
    assert 'id="qrpopclose"' in html
    assert ".qrpop { display:none; position:fixed; inset:0;" in html
    assert ".qrpop .qr img { width:220px; height:220px; }" in html
    topbar = html[html.index('<div class="topbar">'):
                  html.index('<div class="qrpop"')]
    assert ">Copy<" not in topbar  # no "Copy" text button in top field
    m = re.search(r'id="copy"[^>]*>(.*?)</button>', topbar, re.S)
    assert m and "<svg" in m.group(1), topbar
    assert topbar.index('id="qrtoggle"') < topbar.index('id="copy"')
    assert topbar.index('id="qrtoggle"') > topbar.index('class="connectbar"')
    # Solid-colour in-scope buttons (no blended fill via the class).
    assert ".lkbox .btn.primary { background:#22d3ee;" in html
    assert ".lkbox .btn.openf { background:#0ea5e9;" in html
    assert ".lkbox .btn.changef { background:#7c3aed;" in html
    # Keep-vs-remove copy is explicitly REMOVED (v2.7.94).
    assert "Save keeps the current password unless you type a new one" not in html
    # No user-visible technical address (round-3 rule, kept).
    visible = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    visible = re.sub(r"<style.*?</style>", "", visible, flags=re.S)
    visible = re.sub(r"<[^>]+>", "", visible)
    assert ".local" not in visible
