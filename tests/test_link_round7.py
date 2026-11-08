"""v2.7.91 real-time delete-state sync tests (Nov 1, 2026, late round).

Proves, for files AND notes, web AND (by code shape) APK:
  (a) a guest's /api/authstate flips can_delete_files /
      can_delete_notes the moment the host toggles -- no reload,
      no relink, same guest token (this is exactly what the
      5s refreshDeleteState() poll reads);
  (b) the served page wires that poll into the 5s interval and
      re-paints freshly rendered note rows, and refreshDeleteState
      does NOT route/bounce (it only updates delete fields);
  (c) a jsdom check of the real served paintDeleteState() code:
      with both toggles OFF the file delete-all, note delete-all
      and per-note delete buttons all gain .deloff; with both ON
      they all lose it;
  (d) the v2.7.90 PC -> guest locked-link download bearer still
      works, and a tokenless LAN guest on a password link still
      401s (download auth is NOT weakened by this round).

Reuses the subprocess-server harness from rounds 2-3/6.
"""
import http.client
import json
import os
import re
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import dropit as D  # noqa: E402

from test_link_round2 import server  # noqa: F401,E402
from test_link_round3 import _flip_role, _guest_client  # noqa: E402
from test_link_round6 import _page, _upload  # noqa: E402


def _authstate(client):
    status, st = client.j("GET", "/api/authstate")
    assert status == 200, st
    return st


def test_authstate_flips_without_reload_or_relink(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "rtdelete", "password": "secret"})
    assert status == 200 and j["ok"], j
    guest = _guest_client(port, "secret")
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    tok = guest.cookies["drop_sess"]
    # Both toggles OFF by default: the poll's first read.
    st = _authstate(guest)
    assert st["can_delete_files"] is False and st["can_delete_notes"] is False, st
    # Host flips files ON only: same token, no reload, no relink.
    status, j = client.j("POST", "/api/guestdelete", {"allowed": True})
    assert status == 200 and j["ok"], j
    st = _authstate(guest)
    assert st["can_delete_files"] is True and st["can_delete_notes"] is False, st
    # Host flips notes ON: both now true.
    status, j = client.j("POST", "/api/guestnotesdelete", {"allowed": True})
    assert status == 200 and j["ok"], j
    st = _authstate(guest)
    assert st["can_delete_files"] is True and st["can_delete_notes"] is True, st
    # Host flips both OFF again: both false immediately, and the
    # token is still valid for non-delete use (files list works).
    status, j = client.j("POST", "/api/guestdelete", {"allowed": False})
    assert status == 200 and j["ok"], j
    status, j = client.j("POST", "/api/guestnotesdelete", {"allowed": False})
    assert status == 200 and j["ok"], j
    st = _authstate(guest)
    assert st["can_delete_files"] is False and st["can_delete_notes"] is False, st
    status, files = guest.j("GET", "/api/files")
    assert status == 200
    # The token itself never changed across the flips.
    assert guest.cookies["drop_sess"] == tok


def test_served_page_wires_realtime_delete_poll(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "rtpage"})
    assert status == 200 and j["ok"], j
    html = _page(port, client)
    # The 5s interval now also runs the delete-state refresh.
    assert "refreshDeleteState();" in html
    # Round34 (2): the interval also re-fits the Upload tab
    # (fitSendTab toggles the scroll-allowed class).
    assert re.search(r"setInterval\(\(\) => \{ loadFiles\(\); loadNotes\(\); loadStatus\(\); refreshDeleteState\(\); if\(typeof fitSendTab === \"function\"\) fitSendTab\(\); \}, 5000\)", html)
    # refreshDeleteState reads authstate via _origFetch (never the
    # wrapped fetch, so no stale X-Drop-Link header), updates
    # ONLY the delete fields, then re-paints. It must not call
    # the routing checkAuth/showGuestLogin/showGuestMain paths.
    m = re.search(r"async function refreshDeleteState\(\)\{(.*?)\n\}", html, re.S)
    assert m, "refreshDeleteState missing from served page"
    body = m.group(1)
    assert "_origFetch(\"/api/authstate\"" in body
    assert "AUTH.can_delete_files" in body and "AUTH.can_delete_notes" in body
    assert "paintDeleteState()" in body
    assert "checkAuth()" not in body
    assert "showGuestLogin" not in body and "showGuestMain" not in body
    # loadNotes re-paints after rendering fresh note rows.
    notes_fn = html.split("async function loadNotes()", 1)[1]
    notes_fn = notes_fn.split("const delallbtn", 1)[0]
    assert notes_fn.count("paintDeleteState()") >= 2
    # loadFiles already painted; keep that invariant.
    assert "paintDeleteState()" in html.split("async function loadFiles()", 1)[1].split("async function loadNotes()", 1)[0]


def test_jsdom_paint_delete_state_greys_files_and_notes(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "rtdom"})
    assert status == 200 and j["ok"], j
    html = _page(port, client)
    # Extract the real canDelete*/paintDeleteState block from the
    # served page (it sits between canDeleteUI and checkAuth).
    start = html.index("function canDeleteUI(){")
    end = html.index("async function checkAuth(){", start)
    funcs = html[start:end]
    assert "function paintDeleteState(){" in funcs
    script = (
        "const { JSDOM } = require('jsdom');\n"
        "const dom = new JSDOM('<button id=\"delallbtn\"></button>'\n"
        "  + '<button id=\"delallnotesbtn\"></button>'\n"
        "  + '<button data-del=\"a\"></button><button data-del=\"b\"></button>');\n"
        "global.document = dom.window.document;\n"
        "global.$ = (s) => dom.window.document.querySelector(s);\n"
        "global.AUTH = { host: false, authed: true, can_delete_files: false, can_delete_notes: false };\n"
        + funcs + "\n"
        "paintDeleteState();\n"
        "const off = ['delallbtn', 'delallnotesbtn'].every(id => document.getElementById(id).classList.contains('deloff'))\n"
        "  && [...document.querySelectorAll('[data-del]')].every(b => b.classList.contains('deloff'));\n"
        "if (!off) { console.log('OFF-FAIL'); process.exit(1); }\n"
        "AUTH.can_delete_files = true; AUTH.can_delete_notes = true;\n"
        "paintDeleteState();\n"
        "const on = ['delallbtn', 'delallnotesbtn'].every(id => !document.getElementById(id).classList.contains('deloff'))\n"
        "  && [...document.querySelectorAll('[data-del]')].every(b => !b.classList.contains('deloff'));\n"
        "if (!on) { console.log('ON-FAIL'); process.exit(1); }\n"
        "console.log('PAINT-OK');\n"
    )
    r = subprocess.run(
        ["node", "-e", script],
        cwd=os.path.expanduser("~/workspace/aitest3/dom"),
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "PAINT-OK" in r.stdout, (r.stdout, r.stderr)


def test_locked_link_download_bearer_still_works(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "rtdl", "password": "secret"})
    assert status == 200 and j["ok"], j
    _upload(client, "pcfile.txt", b"from the pc")
    guest = _guest_client(port, "secret")
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    tok = guest.cookies["drop_sess"]
    # DownloadManager-style: no cookie, no header, bearer in URL.
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/dl/pcfile.txt?token=" + tok)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    assert resp.status == 200 and body == b"from the pc", resp.status
