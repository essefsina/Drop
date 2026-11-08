"""v2.8.8 / APK 2.6.82 hotfix round (Essef Nov 4, evening, 3 items).

1. Locked-address notice: the 2.8.7 rule set NO svg size, so
   Chromium rendered the padlock at its huge default and the
   pill ballooned (~256-315px tall, dialog overflowing). Fixed
   to a small pill in the open notice's style (20px icon).
2. Separate-folder toggle OFF: Change Folder is NEVER greyed
   any more -- it stays enabled and retargets to the Main
   Folder ("Change Main Folder") in the menu, Set Up, and the
   Files tab; the "This option is disabled" note is gone
   everywhere (desktop + APK drawer). ON restores per-link.
3. Buttons smaller overall (text may drop to fit; icons
   scaled + aligned to the reduced text), fills/actions/
   greying/8px corners unchanged.

PAGE checks (interpreted PAGE, round16-22 pattern) + live
server checks via the round2/round16 fixtures.
"""

import ast
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
from test_link_round2 import server, _raw  # noqa: F401,E402
from test_link_round3 import _flip_role  # noqa: F401,E402

SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py")).read()
PAGE = None
for _n in ast.walk(ast.parse(SRC)):
    if isinstance(_n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "PAGE" for t in _n.targets
    ):
        PAGE = _n.value.value
        break
assert PAGE is not None


def test_version_288():
    assert 'VERSION = "2.8.8"' in SRC
    assert 'VERSION = "2.8.7"' not in SRC


def test_locked_pill_small_not_giant():
    # Root cause fixed: the locked svg is sized like the open
    # notice's (20px), in CSS and as element attributes, so it
    # can never fall back to the browser's huge default again.
    assert ".lklockedwarn svg { width:20px; height:20px; vertical-align:-4px; margin-right:8px; flex:none; }" in PAGE
    assert 'id="lklockedwarn"><svg width="20" height="20"' in PAGE
    # Host parity with the open notice: same pill padding/font.
    assert ".lkbox:not(.guestcard) .lklockedwarn.show { padding:10px 20px; font-size:16px; margin-bottom:10px; }" in PAGE
    # Animation + selection logic unchanged.
    assert "@keyframes lockpulse" in PAGE
    assert "const _lkNoticeLocked = !!(st.locked || st.has_password);" in PAGE
    assert 'warn.classList.toggle("show", !_lkNoticeLocked);' in PAGE
    assert 'lwarn.classList.toggle("show", _lkNoticeLocked);' in PAGE
    assert '_lt.textContent = st.locked ? "Locked address — password required" : "Password set for this address"' in PAGE


def test_disabled_note_gone_everywhere():
    assert "This option is disabled" not in PAGE
    assert 'id="sbsepnote"' not in PAGE
    assert 'id="lksepnote"' not in PAGE
    assert ".sbsepnote" not in PAGE


def test_sep_off_never_disables_retargets():
    # paintSeparateFolders: enabled always, label retargets.
    assert "function _sepOff(){ return !!(AUTH && AUTH.separate_folders === false); }" in PAGE
    assert 'cf.disabled = false; _setChangeLabel(cf, sep ? "Change Folder" : "Change Main Folder")' in PAGE
    assert 'lcf.disabled = false; _setChangeLabel(lcf, sep ? "Change Folder" : "Change Main Folder")' in PAGE
    assert 'scf.disabled = false; _setChangeLabel(scf, sep ? "Change folder" : "Change Main Folder")' in PAGE
    assert "cf.disabled = !sep" not in PAGE
    assert "lcf.disabled = !sep" not in PAGE
    assert "scf.disabled = !sep" not in PAGE
    # Handlers: OFF branches route to the Main Folder route.
    assert "if(_sepOff()){ await changeRootFolder(); loadFiles(); return; }" in PAGE
    assert "if(_sepOff()){ await changeRootFolder(); await checkAuth(); openLinkWin(); loadFiles(); return; }" in PAGE
    # Menu route itself unchanged (always Main Folder).
    assert 'async function changeRootFolder(){' in PAGE
    # Server guard kept: direct per-link changes still refuse
    # while OFF (the UI retargets, the API enforces).
    assert '"error": "separate folders are disabled — "' in SRC


def test_button_tightening_sizes():
    # Main page.
    assert ".board .nbtnrow .btn { font-size:12px; padding:8px 7px; gap:5px; }" in PAGE
    assert ".board .fbtnrow .btn { font-size:11px; padding:8px 5px; gap:4px; }" in PAGE
    assert ".board .nbtnrow .btn svg, .board .fbtnrow .btn svg { width:14px; height:14px; }" in PAGE
    assert ".board #sendsnippet { font-size:13px; padding:9px 12px; }" in PAGE
    assert ".board #sendsnippet svg { width:16px; height:16px; }" in PAGE
    assert ".snipactions .btn { font-size:12px; padding:7px 4px; }" in PAGE
    assert ".snipactions .btn svg { width:13px; height:13px; }" in PAGE
    assert ".frow .btn { font-size:11px; padding:7px 8px; }" in PAGE
    # Menu.
    assert "#sidebar .sbbtn { padding:8px 9px; font-size:12px; border-radius:8px; gap:7px; }" in PAGE
    assert "#sidebar .sbbtn svg { width:15px; height:15px; }" in PAGE
    # Mobile Send card + guest login.
    assert ".msend .mbtn-primary, .msend .mbtn-secondary { font-size:14px; padding:9px; }" in PAGE
    assert ".msend #msendfiles svg { width:18px; height:18px; flex:none; }" in PAGE
    assert ".gloginbox .btn { font-size:14px; padding:10px; border-radius:8px; }" in PAGE
    # Set Up dialog (host).
    assert ".lkbox .btn { padding:10px; min-height:40px; font-size:13px; }" in PAGE
    assert ".lkbox:not(.guestcard) .lkfolderrow { gap:10px; height:44px; }" in PAGE
    assert ".lkbox:not(.guestcard) .lkfolderrow .btn { height:44px; min-height:44px; font-size:15px; gap:8px; }" in PAGE
    assert ".lkbox:not(.guestcard) .lkfolderrow .btn svg { width:18px; height:18px; }" in PAGE
    assert ".lkbox:not(.guestcard) .lkpwrow { align-items:center; }" in PAGE
    assert ".lkbox:not(.guestcard) .lkpwrow .lkiconbtn { width:56px; height:44px; border-radius:8px; }" in PAGE
    assert ".lkbox:not(.guestcard) .lkpwrow .lkiconbtn svg { width:19px; height:19px; }" in PAGE
    assert ".lkbox:not(.guestcard) .lksavewrap .btn.primary { width:138px; height:42px; min-height:42px; font-size:16px; }" in PAGE
    assert ".lkbox:not(.guestcard) #lkset svg { width:18px; height:18px; }" in PAGE
    assert ".lkbox:not(.guestcard) .lkclosebtn { width:38px; height:38px; font-size:21px; border-radius:8px; }" in PAGE
    # Greying + fills untouched.
    assert ".sbbtn:disabled, .btn:disabled { opacity:.45; cursor:not-allowed; }" in PAGE
    assert "background:#277ff0; color:#ffffff; }" in PAGE  # blue fills unchanged


def test_apk_282_note_gone_versions_bumped():
    apk_dir = os.path.join(os.path.dirname(__file__), "..", "..",
                           "dropit-android")
    gradle = open(os.path.join(apk_dir, "app/build.gradle")).read()
    manifest = open(os.path.join(apk_dir, "app/src/main/AndroidManifest.xml")).read()
    assert "versionCode 102" in gradle and 'versionName "2.6.82"' in gradle
    assert 'android:versionCode="102"' in manifest
    assert 'android:versionName="2.6.82"' in manifest
    assert 'applicationId "com.dropit.app"' in gradle
    main = open(os.path.join(apk_dir, "app/src/main/java/com/dropit/app/MainActivity.kt")).read()
    drawer = open(os.path.join(apk_dir, "app/src/main/res/layout/drawer_panel.xml")).read()
    dialog = open(os.path.join(apk_dir, "app/src/main/res/layout/dialog_link.xml")).read()
    assert "This option is disabled" not in drawer
    assert "This option is disabled" not in main
    assert "drawerSepNote" not in drawer
    assert "drawerSepNote" not in main
    # APK is a guest: no Change Folder control exists to retarget
    # (host-only, removed in round 4) -- state display only.
    assert 'android:id="@+id/drawerSepState"' in drawer
    # Set Up Save tightened, still fits "Save" cleanly.
    assert 'android:minWidth="128dp"' in dialog
    assert 'android:paddingTop="8dp"' in dialog


def test_sep_off_retargets_to_main_folder_live(server):
    client, _base, _proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "11-04-88", "password": "pw123"})
    assert status == 200 and j["ok"], j
    status, auth = client.j("GET", "/api/authstate")
    assert status == 200 and auth["separate_folders"] is True
    # OFF: everything resolves to the Main Folder.
    status, j = client.j("POST", "/api/separate_folders", {"enabled": False})
    assert status == 200 and j["separate_folders"] is False
    status, auth = client.j("GET", "/api/authstate")
    assert auth["folder"] == auth["main_folder"]
    # The OFF retarget path: changing the MAIN Folder works
    # while OFF (this is what the retargeted Change Folder
    # button now calls), and uploads follow it.
    import tempfile
    new_main = tempfile.mkdtemp(prefix="drop-main-")
    status, j = client.j("POST", "/api/setrootfolder", {"folder": new_main})
    assert status == 200 and j["ok"], j
    status, auth = client.j("GET", "/api/authstate")
    assert auth["main_folder"] == new_main and auth["folder"] == new_main
    status, _ = client.upload("mainfile.txt", b"main")
    assert status == 200
    assert os.path.exists(os.path.join(new_main, "mainfile.txt"))
    assert not os.path.exists(os.path.join(new_main, "11-04-88"))
    # Per-link changes still refuse while OFF (server guard).
    status, j = client.j("POST", "/api/setlinkfolder",
                         {"folder": "/tmp/should-not-stick"})
    assert status == 200 and j["ok"] is False
    # ON restores per-link behaviour.
    status, j = client.j("POST", "/api/separate_folders", {"enabled": True})
    assert status == 200 and j["separate_folders"] is True
    status, auth = client.j("GET", "/api/authstate")
    assert auth["folder"].rstrip("/").endswith("11-04-88")
