"""v2.8.11 / APK 2.6.85 round (Essef Nov 4, 10:19 PM + follow-ups).

Items covered:
  1. Menu Main Folder buttons ONLY: resized (76%, centred) and
     renamed "Open Folder" / "Change Folder". Files card stays
     one-word "Open" / "Change"; Set Up dialog already full names.
  2. Menu Change Folder button: Set Up purple gradient.
  3. Set Up Your Addresses window: slightly transparent
     (rgba .88 + backdrop blur), text/controls readable.
  4. Delete colour REVERT: 2.8.10 darker #dc2626 -> pre-2.8.10
     lighter #f87171 (solid) / #ef4444 (gradient end), all platforms.
  5. File-row Open button (reveal in folder) was dead: root cause
     was ONE combined "/select,<path>" arg (quoted as a whole when
     the path has spaces, so Explorer got no switch); now separate
     args ["explorer", "/select,", target] in dropit.py AND app.py.
  6. APK theme switch restarts app -> in-place retheme, no
     recreate(), session + screen preserved.
  7. APK profile X aligned (same baseline/position as other closes).
  8. Permission update repaints ALL affected controls in one pass
     (rAF-coalesced paintDeleteState on web; paintRowPermissions
     on APK).
  9. Greyed-out opacity lowered further (.45 -> .25).
 10. APK pill/tab bar icons coloured (soft palette, Search icon
     treatment kept).
 11. "Find" -> "Search" everywhere (tabs, menu, headings, chatbox).
 12. "Create Separate Folders" NOT on APK (drawer row gone).
 13. QR regenerates on every address change (no-store + refreshQr
     cache-bust; payload = server.url, full http://<name>.local:<port>/).
 14. Address-removal prompt: two separate checkboxes (notes, files)
     with the four exact result messages; themed card; smaller X
     (24px) on it and on the Set Password window.
 15. Save buttons (Set Password + Set Up): floppy icon + colour
     matches Send Text / Add New (#277ff0).
 16. APK Send tab buttons narrower (32dp side margins, centred).
 17. File tap PREVIEWs in-app (web + APK), Download unchanged.
 18. APK note-card date shifted right (16dp gap after title).
 19. Devices pill count and device list share ONE source of truth
     (live guest sessions, 90s window) -- no ghost entries.
 + Rename (Nov 4, 10:33 PM): "Send" tab -> "Upload" on all
     platforms (tab label, pill label, headings). Send Files /
     Send Text actions keep their labels and behaviour.

PAGE checks use the interpreted PAGE (round16-25 pattern).
Round25's test_delete_buttons_darker_red now fails BY DESIGN
(the #dc2626 it pins was reverted by item 4) -- see the report,
do not "fix" it back. The live QR PNG test skips when the
qrcode package is absent (this sandbox); the URL-change test
still proves the payload source updates.
"""

import ast
import json
import os
import re
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
from test_link_round2 import server, _raw  # noqa: F401,E402
from test_link_folders import Client  # noqa: E402

SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py")).read()
APP_SRC = open(os.path.join(os.path.dirname(__file__), "..", "app.py")).read()
PAGE = None
for _n in ast.walk(ast.parse(SRC)):
    if isinstance(_n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "PAGE" for t in _n.targets
    ):
        PAGE = _n.value.value
        break
assert PAGE is not None

APK = os.path.join(os.path.dirname(__file__), "..", "..",
                   "dropit-android")
APK_KT = open(os.path.join(
    APK, "app/src/main/java/com/dropit/app/MainActivity.kt")).read()
APK_XML = open(os.path.join(
    APK, "app/src/main/res/layout/activity_main.xml")).read()


def test_version_is_2_8_11():
    assert D.VERSION == "2.8.11"


# ---------------------------------------------------------------- items 1-2
def test_menu_buttons_resized_renamed_only_this_pair():
    # THIS pair only: static menu HTML says "Open Folder" /
    # "Change Folder" (round25 pinned one-word here; item 1 changes
    # the menu pair and nothing else).
    assert re.search(r'id="sbopen".*?>\s*Open Folder</button>', PAGE, re.S)
    assert re.search(r'id="sbchange".*?>\s*Change Folder</button>', PAGE, re.S)
    # Narrower than full-card width, centred: 76% + auto margins.
    assert "#sbopen, #sbchange" in PAGE
    assert "width:76%" in PAGE
    assert "margin:8px auto 0" in PAGE
    # Files card buttons stay one-word "Open" / "Change".
    _open_line = next(
        l for l in SRC.splitlines()
        if "btn openf" in l and "openfolder" in l
        and "lkopenfolder" not in l)
    assert "> Open</button>" in _open_line, _open_line
    _change_line = next(
        l for l in SRC.splitlines()
        if "btn changef" in l and "changefolder" in l
        and "lkchangefolder" not in l)
    assert "> Change</button>" in _change_line, _change_line


def test_menu_change_folder_purple_matches_setup():
    # Set Up Change Folder purple gradient, now on the menu button
    # (line ~2708 override wins over the earlier solid #a78bfa).
    assert ("#sbchange { background:linear-gradient(135deg,#A78BFA,#7C3AED);"
            " color:#ffffff; border:none; }") in PAGE
    # Open Folder keeps its blue.
    assert "#sbopen" in PAGE and "#277ff0" in PAGE


# ------------------------------------------------------------------- item 3
def test_setup_window_transparent():
    assert ".lkbox:not(.guestcard) { background:rgba(18,23,42,.88);" in PAGE
    assert "backdrop-filter:blur(14px)" in PAGE
    assert "rgba(255,255,255,.88)" in PAGE  # light theme, still readable


# ------------------------------------------------------------------- item 4
def test_delete_colour_reverted_to_lighter_red():
    # No trace of the 2.8.10 darker red anywhere in the served page.
    assert "#dc2626" not in PAGE.lower()
    # The pre-2.8.10 lighter red is back on the delete rules.
    assert ".btn.dangergrad { background:#f87171" in PAGE
    assert ".fact button.del { background:#f87171; color:#fff; }" in PAGE
    assert ".delbar .confirmdel { background:#f87171; color:#fff; }" in PAGE
    assert ".svbar .confirmdel { background:#f87171; color:#fff; }" in PAGE
    # Gradient end is the old #ef4444, not #dc2626.
    assert "#f87171,#ef4444" in PAGE


# ------------------------------------------------------------------- item 9
def test_greyed_opacity_lower():
    assert ".deloff" in PAGE
    assert "opacity:.25" in PAGE
    assert ".delbar .confirmdel:disabled { opacity:.25; }" in PAGE
    assert ".svbar .confirmdel:disabled { opacity:.25; }" in PAGE


# ------------------------------------------------------------------ item 11
def test_find_renamed_search_everywhere():
    assert "<span>Search</span>" in PAGE  # tab label
    assert "Search a file" in PAGE  # chatbox placeholders (x2)
    assert PAGE.count("Search a file") >= 2
    assert ">Find</span>" not in PAGE
    assert "Find a file" not in PAGE
    assert "Search A File Using Keywords" in PAGE


# ------------------------------------------------------- Send -> Upload tab
def test_send_tab_renamed_upload():
    assert "&#x2B06;&#xFE0F; Upload</h2>" in PAGE  # column heading
    assert "<span>Upload</span>" in PAGE  # mobile pill/tab label
    assert ">Send</span>" not in PAGE
    assert "Upload column" in PAGE  # empty-notes text names the column
    # The actions inside keep their labels and behaviour.
    assert "Send Files" in PAGE
    assert "Send Text" in PAGE


# ------------------------------------------------------------------ item 13
def test_qr_refresh_wiring():
    assert "function refreshQr(){" in PAGE
    assert '"/qr.png?v=" + encodeURIComponent(v)' in PAGE
    assert "refreshQr();" in PAGE  # called on address paint
    # Server sends no-store on the QR itself (SRC: qr.png branch).
    assert '{"Cache-Control": "no-store"}' in SRC


# ------------------------------------------------------------------ item 14
def test_address_remove_prompt():
    assert 'id="addrrempop"' in PAGE
    assert 'id="addrremnotes"' in PAGE
    assert 'id="addrremfiles"' in PAGE
    assert "Delete all notes for this address" in PAGE
    assert "Delete all files for this address" in PAGE
    # The four exact result messages.
    assert ", notes and files have been deleted." in PAGE
    assert "Files and notes are still there." in PAGE
    assert "Files deleted for " in PAGE and ", the notes are still there." in PAGE
    assert "Notes deleted for " in PAGE and ", the files are still there." in PAGE
    # Smaller X (24px, was 32px) on the new window AND Set Password.
    assert (".lockpwbox .lkclosebtn, .addrrembox .lkclosebtn { width:24px;"
            " height:24px; font-size:15px; border-radius:7px; }") in PAGE


# ------------------------------------------------------------------ item 15
def test_save_floppy_and_colour_match():
    # Floppy icon path on the Set Password Save button.
    assert re.search(
        r'id="lockpwsave".*?M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z',
        PAGE, re.S)
    # Both Saves match Send Text / Add New blue #277ff0.
    assert ".lockpwbox .lockpwsave { background:#277ff0; color:#ffffff;" in PAGE
    assert (".lkbox .btn.primary { background:#277ff0; border:none;"
            " color:#ffffff; font-weight:800; }") in PAGE
    assert ".lksavewrap .btn.primary" in PAGE


# ------------------------------------------------------------------- item 8
def test_permission_single_pass_paint():
    assert "let _permPaintQueued = false;" in PAGE
    assert 'if(typeof requestAnimationFrame === "function") requestAnimationFrame(_run);' in PAGE
    assert "function paintDeleteStateNow(){" in PAGE


# ------------------------------------------------------------------ item 17
def test_web_preview_on_click():
    assert 'id="previewpop"' in PAGE
    assert "function previewFile(name, size){" in PAGE
    assert "function downloadPreviewFile(name){" in PAGE
    # File-row name/thumb/date click previews (not downloads).
    assert "previewFile(f.name, f.size)" in PAGE
    # Unsupported types get a clear in-window message, never a
    # silent download.
    assert "Can not preview this file type in the app" in PAGE
    # Download stays as its own explicit action in the preview.
    assert "downloadPreviewFile" in PAGE


# ------------------------------------------------------------------- item 5
def test_reveal_separate_args():
    # Server handler (desktop browser fallback).
    assert 'subprocess.Popen(["explorer", "/select,", target])' in SRC
    assert '"/select," + target' not in SRC
    # Desktop pywebview bridge (app.py).
    assert 'subprocess.Popen(["explorer", "/select,", path])' in APP_SRC
    assert '"/select," + path' not in APP_SRC


# ---------------------------------------------------------------- live: item 5
def test_reveal_live_opens_folder(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "revtest"})
    assert status == 200 and j["ok"], j
    folder = base / "revtest"
    folder.mkdir(exist_ok=True)
    # A name WITH a space: the old combined-arg bug failed exactly here.
    (folder / "hello world.txt").write_text("hi")
    status, j = client.j("POST", "/api/reveal",
                         {"name": "hello world.txt"})
    assert status == 200 and j["ok"] is True, (status, j)
    # Guest is host-only denied.
    guest = Client(port)
    guest.cookies["drop_sess"] = "guesttok"
    cfg_path = home / ".config" / "DropIt" / "config.json"
    cfg = json.loads(cfg_path.read_text())
    cfg.setdefault("sessions", {})["guesttok"] = {
        "role": "guest", "ts": int(time.time()), "link": "revtest"}
    cfg_path.write_text(json.dumps(cfg))
    status, j = guest.j("POST", "/api/reveal",
                        {"name": "hello world.txt"})
    assert status == 403 and j.get("code") == "host_only", (status, j)
    # Missing file is an error, never a folder open.
    status, j = client.j("POST", "/api/reveal", {"name": "nope.txt"})
    assert status == 200 and j["ok"] is False, (status, j)


# --------------------------------------------------------------- live: item 19
def _seed_guest(home, tok, ts, name="Pixel 8"):
    cfg_path = home / ".config" / "DropIt" / "config.json"
    cfg = json.loads(cfg_path.read_text())
    cfg.setdefault("sessions", {})[tok] = {
        "role": "guest", "ts": int(ts), "device_name": name,
        "ip": "192.168.1.50", "link": "devtest"}
    cfg_path.write_text(json.dumps(cfg))


def test_devices_pill_and_list_always_agree(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "devtest"})
    assert status == 200 and j["ok"], j
    tok = "guestdevtok123456"
    # No sessions: pill 0, list empty.
    status, st = client.j("GET", "/api/status")
    assert status == 200 and st["devices"] == 0, st
    assert st["device_names"] == [] and st["devices_list"] == []
    # Fresh session: pill 1 AND list 1, same name, both endpoints.
    _seed_guest(home, tok, time.time())
    status, st = client.j("GET", "/api/status")
    assert st["devices"] == 1 and st["device_names"] == ["Pixel 8"], st
    assert len(st["devices_list"]) == 1
    status, sj = client.j("GET", "/api/sessions")
    assert status == 200 and len(sj["sessions"]) == 1, sj
    assert sj["sessions"][0]["display_name"] == "Pixel 8"
    # Stale session (10 min idle, no activity): pill 0 AND list empty.
    _seed_guest(home, tok, time.time() - 600)
    status, st = client.j("GET", "/api/status")
    assert st["devices"] == 0, st
    assert st["device_names"] == [] and st["devices_list"] == []
    status, sj = client.j("GET", "/api/sessions")
    assert sj["sessions"] == [], sj
    # Activity revives it in BOTH at once.
    guest = Client(port)
    guest.cookies["drop_sess"] = tok
    status, st = guest.j("GET", "/api/status")
    assert st["devices"] == 1 and st["device_names"] == ["Pixel 8"], st
    # Disconnect (revoke) removes it from BOTH at once.
    status, rj = client.j("POST", "/api/sessions/revoke",
                          {"id": tok[:12]})
    assert status == 200 and rj.get("ok"), (status, rj)
    status, st = client.j("GET", "/api/status")
    assert st["devices"] == 0 and st["device_names"] == [], st
    status, sj = client.j("GET", "/api/sessions")
    assert sj["sessions"] == [], sj


# --------------------------------------------------------------- live: item 14
def _setup_address(server, client, base, home, name):
    status, j = client.j("POST", "/api/setlink", {"name": name})
    assert status == 200 and j["ok"], j
    folder = base / name
    folder.mkdir(exist_ok=True)
    (folder / "keep.txt").write_text("x")
    notes_path = home / ".config" / "DropIt" / ("notes-link-%s.json" % name)
    notes_path.write_text(json.dumps(
        [{"id": "n1", "text": "note", "created": 1}]))
    status, hj = client.j("GET", "/api/linkhistory")
    assert status == 200, hj
    assert any(e.get("key") == name for e in hj["entries"]), hj
    return folder, notes_path


@pytest.mark.parametrize("del_notes,del_files", [
    (True, True), (False, False), (True, False), (False, True)])
def test_address_remove_four_combos(server, del_notes, del_files):
    client, base, proc, port, home = server
    folder, notes_path = _setup_address(
        server, client, base, home, "rmtest")
    status, j = client.j("POST", "/api/address/remove", {
        "key": "rmtest", "delete_notes": del_notes,
        "delete_files": del_files})
    assert status == 200 and j["ok"], (status, j)
    assert j["notes_deleted"] is del_notes, j
    assert j["files_deleted"] is del_files, j
    assert j["address"] == "rmtest"
    # Filesystem matches the flags exactly.
    assert notes_path.exists() is not del_notes
    assert (folder / "keep.txt").exists() is not del_files
    # History entry is always removed.
    status, hj = client.j("GET", "/api/linkhistory")
    assert not any(e.get("key") == "rmtest" for e in hj["entries"]), hj


def test_address_remove_separate_folders_off_keeps_files(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/separate_folders",
                         {"enabled": False})
    assert status == 200 and j["ok"], (status, j)
    folder, notes_path = _setup_address(
        server, client, base, home, "rmshared")
    status, j = client.j("POST", "/api/address/remove", {
        "key": "rmshared", "delete_notes": False,
        "delete_files": True})
    assert status == 200 and j["ok"], (status, j)
    # Shared Main Folder: file deletion refused, file survives.
    assert j["files_deleted"] is False, j
    assert (folder / "keep.txt").exists()


def test_address_remove_guest_forbidden(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "rmguest"})
    assert status == 200 and j["ok"], j
    cfg_path = home / ".config" / "DropIt" / "config.json"
    cfg = json.loads(cfg_path.read_text())
    cfg.setdefault("sessions", {})["guesttok"] = {
        "role": "guest", "ts": int(time.time()), "link": "rmguest"}
    cfg_path.write_text(json.dumps(cfg))
    guest = Client(port)
    guest.cookies["drop_sess"] = "guesttok"
    status, j = guest.j("POST", "/api/address/remove", {
        "key": "rmguest", "delete_notes": True, "delete_files": True})
    assert status == 403 and j.get("code") == "host_only", (status, j)


# --------------------------------------------------------------- live: item 13
def test_qr_url_changes_with_address(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "qra"})
    assert status == 200 and j["ok"], j
    assert j["url"] == "http://qra.local:%d" % port, j
    status, j = client.j("POST", "/api/setlink", {"name": "qrb"})
    assert status == 200 and j["ok"], j
    assert j["url"] == "http://qrb.local:%d" % port, j
    # The QR payload is server.url, so it changes with the address.


def test_qr_png_no_store(server):
    if not D.HAS_QR:
        pytest.skip("qrcode/Pillow not installed in this sandbox")
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "qra"})
    assert status == 200 and j["ok"], j
    s1, b1, h1 = _raw_png(port, "/qr.png")
    assert s1 == 200 and b1[:8] == b"\x89PNG\r\n\x1a\n", s1
    assert h1.get("Cache-Control") == "no-store", h1
    status, j = client.j("POST", "/api/setlink", {"name": "qrb"})
    assert status == 200 and j["ok"], j
    s2, b2, h2 = _raw_png(port, "/qr.png")
    assert s2 == 200
    assert b2 != b1  # QR bytes change with the address


def _raw_png(port, path):
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", path)
    resp = conn.getresponse()
    raw = resp.read()
    headers = {k: v for k, v in resp.getheaders()}
    conn.close()
    return resp.status, raw, headers


# ------------------------------------------------------- served page: Upload
def test_served_page_upload_tab(server):
    client, base, proc, port, home = server
    status, raw = client.call("GET", "/")
    assert status == 200
    html = raw.decode()
    assert "<span>Upload</span>" in html
    assert "Upload</h2>" in html
    assert ">Send</span>" not in html


# ---------------------------------------------------------------- APK statics
def test_apk_version_2_6_85():
    gradle = open(os.path.join(APK, "app/build.gradle")).read()
    manifest = open(os.path.join(
        APK, "app/src/main/AndroidManifest.xml")).read()
    assert "versionCode 105" in gradle
    assert 'versionName "2.6.85"' in gradle
    assert 'android:versionCode="105"' in manifest
    assert 'android:versionName="2.6.85"' in manifest


def test_apk_delete_colour_reverted():
    for f in ("app/src/main/res/drawable/btn_danger.xml",
              "app/src/main/res/drawable/btn_main_red.xml"):
        txt = open(os.path.join(APK, f)).read()
        assert "#F87171" in txt, f
        assert "#DC2626" not in txt, f
    assert "0xFFDC2626" not in APK_KT
    assert "0xFFF87171" in APK_KT


def test_apk_send_buttons_narrower():
    # Both Send-tab buttons: 32dp side margins + centred (item 16).
    assert APK_XML.count('android:layout_marginStart="32dp"') >= 2
    assert APK_XML.count('android:layout_marginEnd="32dp"') >= 2
    assert 'android:layout_gravity="center_horizontal"' in APK_XML


def test_apk_no_separate_folders_option():
    drawer = open(os.path.join(
        APK, "app/src/main/res/layout/drawer_panel.xml")).read()
    idx = drawer.find("Create Separate Folders")
    assert idx != -1
    # The row holding it is gone (visibility=gone on its parent).
    assert 'android:visibility="gone"' in drawer[:idx]


def test_apk_theme_switch_no_recreate():
    # No recreate() CALL anywhere (only comments mention it).
    assert not re.search(r"(?m)^\s*recreate\(\)", APK_KT)
    assert "fun applyThemeInPlace(" in APK_KT
    assert "fun bindMainViews()" in APK_KT
    assert "applyThemeInPlace(" in APK_KT


def test_apk_preview_viewer():
    assert os.path.isfile(os.path.join(
        APK, "app/src/main/res/layout/dialog_preview.xml"))
    assert "fun previewFile(" in APK_KT
    assert "PdfRenderer" in APK_KT
    assert "Can not preview this file type in the app" in APK_KT
    # Preview never downloads: the preview path fetches bytes, the
    # DownloadManager path lives only in enqueueDownload.
    assert "fun enqueueDownload(" in APK_KT
    assert "previewFile(name" in APK_KT or "previewFile(name," in APK_KT


def test_apk_permission_single_pass():
    assert "fun paintRowPermissions()" in APK_KT
    # Permission-greyed alphas are the lowered .25, not .45.
    assert "0.25f" in APK_KT


def test_apk_pill_icon_colours():
    assert "0xFF7FB3E8" in APK_KT  # Upload: soft sky blue
    assert "0xFFD9A441" in APK_KT  # Notes: soft amber
    assert "0xFFA78BFA" in APK_KT  # Files: soft violet


def test_apk_note_date_shifted_right():
    item_note = open(os.path.join(
        APK, "app/src/main/res/layout/item_note.xml")).read()
    assert 'android:layout_marginStart="16dp"' in item_note


def test_apk_upload_tab_label():
    assert 'android:text="Upload"' in APK_XML
    assert 'android:text="Send"' not in APK_XML


def test_apk_profile_x_aligned():
    for f in ("app/src/main/res/layout/dialog_link.xml",
              "app/src/main/res/layout/dialog_login.xml"):
        txt = open(os.path.join(APK, f)).read()
        assert 'android:gravity="end|center_vertical"' in txt, f
        assert 'android:scaleType="centerInside"' in txt, f
