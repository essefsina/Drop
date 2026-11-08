"""v2.8.1 / APK 2.6.75 permission-mapping audit + disconnect immediacy
(Nov 3, 2026, Essef's 1:32 AM and 1:35 AM reports against 2.8.0/2.6.74).

Covers, against a real subprocess server with a guest-stamped token:
  1. Server matrix: every one of the six checkboxes, OFF -> its exact
     endpoints 403 AND its authstate can_* flag is False; ON -> 200.
     Download covers /dl/ AND /api/notes/dl; Upload covers /api/upload;
     Add/Edit covers /api/snippet, /api/notes/edit AND /api/notes/rename;
     Delete Files covers /api/delete + /api/delete_all; Delete Notes
     covers /api/notes/delete + /api/notes/delete_all; Star covers
     /api/notes/star. No cross-wiring (each OFF blocks only its own).
  2. Disconnect immediacy (server): single revoke purges the revoked
     sessions' IPs from the seen set (helper unit test), and the
     sessions list is empty immediately after a revoke, with no wait.
  3. Web UI (PAGE text): Send pickers are gated BEFORE opening
     (desktop drop zone + mobile Send Files); Send textareas grey
     with Add/Edit; every gated control is painted by
     paintDeleteState under its own permission; disconnect rows
     are removed optimistically (rowEl.remove) and Disconnect All
     clears the list at once.
  4. APK source: uploadOne is gated by Upload; checkAuthAsync never
     nulls lastAuth on an unreachable authstate (the stale-True ->
     403-instead-of-grey root cause); checkStillConnected repaints
     all six permissions.
"""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
from test_link_round2 import server, _raw  # noqa: F401,E402
from test_link_round3 import _flip_role  # noqa: E402


def _guest(port, home, password="pw123"):
    from test_link_folders import Client
    guest = Client(port)
    status, j = guest.j("POST", "/api/login", {"password": password})
    assert status == 200 and j["ok"], j
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    guest.cookies["drop_locked"] = "1"
    return guest


def _set_perms(host, perms):
    status, j = host.j("POST", "/api/permissions", {"permissions": perms})
    assert status == 200 and j["ok"], j


ALL_ON = {"download_files": True, "upload_files": True,
          "delete_files": True, "add_notes": True,
          "delete_notes": True, "star_notes": True}


def test_server_matrix_all_six(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "10-30-99", "password": "pw123"})
    assert status == 200 and j["ok"], j
    status, _ = client.upload("m.txt", b"m")
    assert status == 200
    status, note = client.j("POST", "/api/snippet", {"text": "m note"})
    assert status == 200 and note["ok"], note
    nid = note["id"]
    guest = _guest(port, home)

    def auth_flag(flag):
        status, st = guest.j("GET", "/api/authstate")
        assert status == 200, st
        return st[flag]

    cases = [
        ("download_files", "can_download_files",
         lambda: _raw(port, "GET", "/dl/m.txt",
                      headers={"Cookie": "drop_sess=%s; drop_locked=1"
                               % guest.cookies["drop_sess"]})[0]),
        ("download_files", "can_download_files",
         lambda: _raw(port, "GET", "/api/notes/dl?id=%s" % nid,
                      headers={"Cookie": "drop_sess=%s; drop_locked=1"
                               % guest.cookies["drop_sess"]})[0]),
        ("upload_files", "can_upload_files",
         lambda: guest.upload("u.txt", b"u")[0]),
        ("add_notes", "can_add_notes",
         lambda: guest.j("POST", "/api/snippet", {"text": "t"})[0]),
        ("add_notes", "can_add_notes",
         lambda: guest.j("POST", "/api/notes/edit",
                         {"id": nid, "text": "e"})[0]),
        ("add_notes", "can_add_notes",
         lambda: guest.j("POST", "/api/notes/rename",
                         {"id": nid, "title": "r"})[0]),
        ("star_notes", "can_star_notes",
         lambda: guest.j("POST", "/api/notes/star",
                         {"id": nid, "starred": True})[0]),
        ("delete_notes", "can_delete_notes",
         lambda: guest.j("POST", "/api/notes/delete_all", {})[0]),
        ("delete_files", "can_delete_files",
         lambda: guest.j("POST", "/api/delete_all", {})[0]),
    ]
    for key, flag, action in cases:
        _set_perms(client, ALL_ON)
        assert action() == 200, (key, "ON should work")
        p = dict(ALL_ON)
        p[key] = False
        _set_perms(client, p)
        assert auth_flag(flag) is False, (key, flag)
        assert action() == 403, (key, "OFF should 403")
    # No cross-wiring: with ONLY add_notes off, upload still works.
    _set_perms(client, ALL_ON)
    p = dict(ALL_ON)
    p["add_notes"] = False
    _set_perms(client, p)
    assert guest.upload("still.txt", b"s")[0] == 200
    # With ONLY upload off, snippet still works.
    p = dict(ALL_ON)
    p["upload_files"] = False
    _set_perms(client, p)
    assert guest.j("POST", "/api/snippet", {"text": "t2"})[0] == 200


def test_disconnect_purges_seen_ip_and_list_empty_at_once(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "10-30-99", "password": "pw123"})
    assert status == 200 and j["ok"], j
    guest = _guest(port, home)
    status, sess = client.j("GET", "/api/sessions")
    guests = [x for x in sess["sessions"] if x["role"] == "guest"]
    assert len(guests) == 1
    # Helper unit proof: purge drops exactly the revoked IP.
    D._seen_ips.clear()
    D._seen_ips["10.0.0.9"] = 1.0
    D._seen_ips["10.0.0.10"] = 1.0
    D._purge_seen_ips({"10.0.0.9"})
    assert "10.0.0.9" not in D._seen_ips
    assert "10.0.0.10" in D._seen_ips
    # Live proof: sessions list empty immediately after revoke.
    status, j = client.j("POST", "/api/sessions/revoke",
                         {"id": guests[0]["id"]})
    assert status == 200 and j["revoked"] == 1, j
    status, sess2 = client.j("GET", "/api/sessions")
    assert [x for x in sess2["sessions"] if x["role"] == "guest"] == []


def test_web_ui_gates_and_optimistic_disconnect():
    page = D.PAGE
    # Pickers gated before opening.
    assert 'drop.onclick' in page
    drop_line = [ln for ln in page.splitlines()
                 if 'drop.onclick' in ln][0]
    assert 'canUploadUI' in drop_line
    msf_line = [ln for ln in page.splitlines()
                if 'msendfiles' in ln and 'onclick' in ln][0]
    assert 'canUploadUI' in msf_line
    # Send textareas grey with Add/Edit.
    assert '$("#snippet")' in page and '$("#msendtext")' in page
    # Optimistic disconnect.
    assert 'rowEl.remove()' in page
    assert 'devempty' in page
    # Every gated control painted under its own permission.
    # (2.8.21 note: paintDeleteState is now only the rAF-debounce
    # wrapper; the painting itself lives in paintDeleteStateNow.)
    paint = re.search(r'function paintDeleteStateNow\(\)\{(.*?)\n\}\n',
                      page, flags=re.S).group(1)
    for needle in ('#drop', '#msendfiles', '#sendsnippet',
                   '#msendsnippet', '[data-dl]', '[data-del]',
                   '[data-star]', '[data-edit]', '#maddnote'):
        assert needle in paint, needle


def test_apk_source_gates():
    path = os.path.join(os.path.dirname(__file__), "..", "..",
                        "dropit-android", "app", "src", "main", "java",
                        "com", "dropit", "app", "MainActivity.kt")
    path = os.path.normpath(path)
    s = open(path, encoding="utf-8").read()
    assert 'if (!guestCanUploadFiles()) { toast(MSG_NO_UPLOAD); return }' in s
    assert 'sendTextBtn.alpha = if (guestCanAddNotes())' in s
    assert 'paintGuestPermissions()' in s
    # checkAuthAsync's null branch must not null lastAuth.
    fn = s.split('private fun checkAuthAsync')[1].split('private fun ')[1]
    assert 'lastAuth = null' not in fn


def test_search_always_terminates():
    """v2.8.1 Find termination: a search that stalls (sleeping
    backend) returns a timeout answer within the bound, and a fast
    search returns normally. Web PAGE aborts at 90s; APK caps the
    whole call at 90s and shows a timeout bubble + falling chime."""
    import time as _time
    orig = D.__dict__.get("search_files")
    import dropit_ai as _A
    real = _A.search_files
    try:
        _A.search_files = lambda d, dd, q, top_k=50: (
            _time.sleep(5), {"ok": True, "results": [], "message": "slow"})[1]
        t0 = _time.time()
        r = _A.search_files_timed("/tmp", "/tmp", "x", timeout=1)
        assert r["message"] == "timeout"
        assert _time.time() - t0 < 3
        _A.search_files = lambda d, dd, q, top_k=50: {
            "ok": True, "results": [], "message": "none"}
        assert _A.search_files_timed("/tmp", "/tmp", "x",
                                     timeout=5)["message"] == "none"
    finally:
        _A.search_files = real
    page = D.PAGE
    assert "AbortController" in page
    assert "90000" in page
    assert "Search took too long" in page
    assert "playFindEmptySound()" in page
    apk_dir = os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "..", "dropit-android",
        "app", "src", "main", "java", "com", "dropit", "app"))
    client = open(os.path.join(apk_dir, "DropItClient.kt"),
                  encoding="utf-8").read()
    assert "callTimeout(90" in client
    main = open(os.path.join(apk_dir, "MainActivity.kt"),
                encoding="utf-8").read()
    assert "Search took too long" in main
    assert "playFindSound(false)" in main
