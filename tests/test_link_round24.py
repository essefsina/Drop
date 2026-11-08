"""v2.8.9 / APK 2.6.83 round (Essef Nov 4, 8:54 PM, 10 items).

1. Separate-folders toggle MOVED from above Permissions into the
   password row, vertically centred with the eye/delete buttons,
   to their right.
2. Toggle OFF no longer renames the button (label only): the
   button stays "Change" in both states (2.8.8 "Change Main
   Folder" label reverted; server OFF routing to the Main Folder
   is unchanged).
3. Shorter label "Create Separate Folders" on Set Up + menu
   (+ APK drawer).
4. Permissions "i": ONE method only -- hover tooltip (title).
   The click popup that duplicated the message is gone.
5. Main-page buttons unified to one size (Shared Texts /
   Shared Files cards + other main-page buttons).
6. One-word buttons: "Open Folder" -> "Open", "Change Folder" ->
   "Change", with distinct icons (Open = folder; Change =
   folder + arrow, not a pencil).
7. DESKTOP PAGE ONLY: file rows hyperlink-like (pointer cursor);
   the per-file Open button reveals the file in its folder;
   name / thumbnail / date open the file directly. AI icon
   untouched. APK / mobile web unchanged.
8. Current Address dropdown root cause fixed (overflow:hidden
   on the field clipped the list + no positioning context),
   arrow bigger (28px), 2.8.7 open animation kept.
9. Locked notice GREEN translucent (checkbox-tick green);
   open notice stays yellow. Small-pill size kept.
10. Set Password popup refined: "Set Password For Address:
    <address>", captioned field, eye INSIDE the field, clean
    Save (blue/purple gradient, no green), red X close.

PAGE checks use the interpreted PAGE (round16-22 pattern).
NOTE: several round22/23 assertions encode the OLD strings
these items intentionally replace ("Create separate folder
for each link", "Change Main Folder", the 20px chevron,
the lkpermtip popup, "Open Folder</button>"); those old
tests now fail BY DESIGN -- see the report, do not "fix"
them back.
"""

import ast
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
from test_link_round2 import server, _raw  # noqa: F401,E402

SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py")).read()
PAGE = None
for _n in ast.walk(ast.parse(SRC)):
    if isinstance(_n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "PAGE" for t in _n.targets
    ):
        PAGE = _n.value.value
        break
assert PAGE is not None


def test_version_289():
    assert 'VERSION = "2.8.9"' in SRC
    assert 'VERSION = "2.8.8"' not in SRC


def test_toggle_moved_to_password_row():
    # Old home above Permissions is gone entirely.
    assert "lkseprow" not in PAGE
    assert "Create separate folder for each link" not in PAGE
    # New short label in BOTH places: sidebar menu + Set Up.
    assert PAGE.count("Create Separate Folders") == 2
    # The checkbox lives inside the password row, after the
    # delete button -- i.e. between the lkpwrow start and the
    # lkpwsection close, to the right of eye/delete.
    m = re.search(r'<div class="lkpwrow">(.*?)</div>', PAGE, re.S)
    assert m, "lkpwrow not found"
    assert 'id="lksepchk"' in m.group(1)
    assert 'id="lkremovepwbtn"' in m.group(1)
    assert m.group(1).index("lkremovepwbtn") < m.group(1).index("lksepchk")
    assert m.group(1).index("lkpweye") < m.group(1).index("lksepchk")
    # Guest card never shows it (host-only setting).
    assert ".lkbox.guestcard .lksepinline { display:none; }" in PAGE
    # JS still wires the same checkbox id.
    assert 'const _lksep = $("#lksepchk");' in PAGE


def test_toggle_off_no_longer_renames_button():
    # All three buttons keep the one-word label in BOTH states.
    assert '_setChangeLabel(cf, "Change")' in PAGE
    assert '_setChangeLabel(lcf, "Change")' in PAGE
    assert '_setChangeLabel(scf, "Change")' in PAGE
    assert '_setChangeLabel(cf, sep ? "Change Folder" : "Change Main Folder")' not in PAGE
    assert '_setChangeLabel(lcf, sep ? "Change Folder" : "Change Main Folder")' not in PAGE
    assert '_setChangeLabel(scf, sep ? "Change folder" : "Change Main Folder")' not in PAGE
    # No button is ever labelled with the old 2.8.8 text.
    assert "Change Main Folder</button>" not in PAGE
    # Still never disabled, and the OFF route still retargets.
    assert "cf.disabled = false;" in PAGE
    assert "if(_sepOff()){ await changeRootFolder(); loadFiles(); return; }" in PAGE
    assert "if(_sepOff()){ await changeRootFolder(); await checkAuth(); openLinkWin(); loadFiles(); return; }" in PAGE


def test_one_word_buttons_distinct_icons():
    # "Open Folder" / "Change Folder" as button labels are gone.
    assert "Open Folder</button>" not in PAGE
    assert "Change Folder</button>" not in PAGE
    assert "Open Folder</button>" not in SRC
    assert "Change Folder</button>" not in SRC
    # One-word labels present in Set Up + menu + Files tab.
    assert "</svg> Open</button>" in PAGE
    assert "</svg> Change</button>" in PAGE
    assert "</svg> Open</button>" in SRC
    assert "</svg> Change</button>" in SRC
    # Change icon is folder + arrow (M9 13h6 / M13 10l3 3-3 3),
    # in the Set Up button, the menu button, and the Files tab.
    assert PAGE.count("M9 13h6") == 2
    assert SRC.count("M9 13h6") == 3
    # Open keeps the plain folder icon.
    assert "M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" in PAGE


def test_info_icon_hover_only():
    # No click popup anywhere: no element, no CSS, no handler.
    # (A v2.8.9 comment names the removed popup; that is not
    # a live element, rule, or handler.)
    assert 'id="lkpermtip"' not in PAGE
    assert ".lkpermtip {" not in PAGE
    assert "_lkpi" not in PAGE
    assert 'lkpi.onclick' not in PAGE
    # The hover method survives: native title tooltip, same text.
    assert 'id="lkperminfo" title="HOST ONLY - APPLIES TO INDIVIDUAL ADDRESS"' in PAGE


def test_delete_buttons_one_word_for_uniform_size():
    # Item 5 forces this: at the unified 13px / 12px padding, a
    # ~97px-wide row button cannot fit a two-word label on one
    # line ("Delete files" wraps -> 53px row, breaking the
    # uniform height). So the two card-level delete buttons are
    # one-word "Delete" too (item 6's direction); their
    # data-tips and confirm dialogs keep the full wording.
    assert "> Delete</button>" in PAGE  # notes card
    assert "Delete All</button>" not in PAGE
    assert "> Delete</button>" in SRC  # files card (server)
    assert "Delete files</button>" not in SRC
    assert 'data-tip="Delete files"' in SRC
    assert 'data-tip="Delete all shared texts"' in PAGE


def test_buttons_uniform_size():
    assert ".board .nbtnrow .btn, .board .fbtnrow .btn, .board #sendsnippet,\n  .msend .mbtn-primary, .msend .mbtn-secondary {\n    font-size:13px; padding:10px 12px; min-height:40px; gap:6px; }" in PAGE
    assert ".board .nbtnrow .btn svg, .board .fbtnrow .btn svg,\n  .board #sendsnippet svg { width:16px; height:16px; }" in PAGE


def test_file_rows_desktop_only_hyperlink_and_reveal():
    # Desktop-only class + pointer cursor + name underline.
    assert "#files.desktoplink .frow { cursor:pointer; }" in PAGE
    assert '#files.desktoplink .frow:hover .fname { text-decoration:underline; }' in PAGE
    assert 'box.classList.toggle("desktoplink", hasBridge());' in PAGE
    # Open button reveals (bridge first, /api/reveal fallback).
    assert "async function revealFile(name){" in PAGE
    assert "window.pywebview.api.reveal_file(name)" in PAGE
    assert 'postHostJ("/api/reveal", {name})' in PAGE
    assert 'if(hasBridge()) revealFile(f.name); else fileTap(f, b);' in PAGE
    assert 'title="${hasBridge() ? "Show in folder" : (isDownloaded(f) ? "Open" : "Download")}"' in PAGE
    # Name / thumbnail / date open the file directly, desktop only.
    assert 'if(hasBridge() && e.target.closest(".fname,.thwrap,.ftime")){' in PAGE
    # AI icon untouched: same markup + same popup call.
    assert 'openAiPopup(files[+b.dataset.ai].name, b)' in PAGE
    assert '<span class="em">✨</span>' in PAGE
    # Server endpoint exists (host-only, jailed, real file only).
    assert 'elif path == "/api/reveal":' in SRC
    assert 'subprocess.Popen(["explorer", "/select," + target])' in SRC
    assert 'subprocess.Popen(["open", "-R", target])' in SRC
    # Desktop bridge exposes the same reveal.
    app = open(os.path.join(os.path.dirname(__file__), "..", "app.py")).read()
    assert "def reveal_file(self, name: str) -> bool:" in app
    assert 'subprocess.Popen(["explorer", "/select," + path])' in app


def test_dropdown_root_cause_fixed_bigger_arrow():
    # The field is its own positioning context with visible
    # overflow -- the 2.8.7 overflow:hidden clip is undone for
    # this field only (other .lkview fields keep it).
    assert ".lkbox:not(.guestcard) .lkview.lkcurdd { overflow:visible; position:relative; }" in PAGE
    # Arrow clearly bigger than the old 20px: the 28px rule
    # comes AFTER the 2.8.7 20px rule, so it wins the cascade
    # (this file's append-override convention).
    assert ".lkcurdd .ddchev { font-size:28px; }" in PAGE
    assert PAGE.index(".lkcurdd .ddchev { font-size:28px; }") > \
        PAGE.index(".lkcurdd .ddchev { font-size:20px; }")
    # The 2.8.7 open animation is untouched.
    assert ".lkcurdd .ddlist { display:block; opacity:0; visibility:hidden; pointer-events:none; transform:translateY(-6px); transition:opacity .22s ease, transform .22s ease, visibility 0s linear .22s; }" in PAGE
    assert ".lkcurdd .ddlist.open { opacity:1; visibility:visible; pointer-events:auto; transform:translateY(0);" in PAGE


def test_locked_notice_green_open_stays_yellow():
    # Locked: tick-green #22c55e, translucent.
    assert ".lklockedwarn { border:2px solid rgba(34,197,94,.55); color:#4ade80; background:rgba(34,197,94,.14); }" in PAGE
    assert 'stroke="#4ade80"' in PAGE
    # Open notice keeps its yellow treatment.
    assert ".lkopenwarn { display:none; border:1px solid #f59e0b; color:#fbbf24; background:rgba(245,158,11,.10);" in PAGE
    # Small-pill size from 2.8.8 kept for both.
    assert ".lkbox:not(.guestcard) .lklockedwarn.show { padding:10px 20px; font-size:16px; margin-bottom:10px; }" in PAGE
    assert ".lkbox:not(.guestcard) .lkopenwarn.show { padding:10px 20px; font-size:16px; margin-bottom:10px; }" in PAGE


def test_set_password_popup_refined():
    # Title with the address highlighted.
    assert "<h4>Set Password For Address: <span id=\"lockpwaddr\"></span></h4>" in PAGE
    # Captioned single field, eye INSIDE the field (no .lockpwrow).
    assert "lockpwrow" not in PAGE
    assert '<label class="lockpwcap" for="lockpwin">Password</label>' in PAGE
    assert '<div class="lockpwfield">' in PAGE
    assert '<button class="lockpweye" id="lockpweye"' in PAGE
    assert ".lockpweye { position:absolute; right:6px; top:50%; transform:translateY(-50%);" in PAGE
    # Blue/purple gradient Save, never green.
    assert ".lockpwbox .lockpwsave { background:linear-gradient(135deg,#277ff0,#7c3aed);" in PAGE
    assert ".lockpwbox { width:min(420px,92vw); border-radius:18px;" in PAGE
    # Behaviour hooks unchanged: same ids, same save path.
    assert 'id="lockpwcloseX"' in PAGE
    assert 'id="lockpwsave"' in PAGE
    assert 'postHostJ("/api/setlinkpassword", {password: pw})' in PAGE
    assert "function openLockPopup(){" in PAGE


def test_apk_drawer_label_and_version():
    apk_dir = os.path.join(os.path.dirname(__file__), "..", "..",
                           "dropit-android")
    drawer = open(os.path.join(apk_dir, "app/src/main/res/layout/drawer_panel.xml")).read()
    assert "Create Separate Folders" in drawer
    assert "Create separate folder for each link" not in drawer
    gradle = open(os.path.join(apk_dir, "app/build.gradle")).read()
    assert "versionCode 103" in gradle
    assert 'versionName "2.6.83"' in gradle
    mani = open(os.path.join(apk_dir, "app/src/main/AndroidManifest.xml")).read()
    assert 'android:versionCode="103"' in mani
    assert 'android:versionName="2.6.83"' in mani


def test_reveal_endpoint_validation_live(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "reveal-test", "password": "pw123"})
    assert status == 200 and j["ok"], j
    # Missing name / missing file: error, never a folder open.
    status, j = client.j("POST", "/api/reveal", {})
    assert status == 200 and j["ok"] is False, j
    status, j = client.j("POST", "/api/reveal", {"name": "nope.txt"})
    assert status == 200 and j["ok"] is False, j
    # Path escape is jailed, not revealed.
    status, j = client.j("POST", "/api/reveal", {"name": "../dropit.py"})
    assert status == 200 and j["ok"] is False, j
    # A real file in the address folder: endpoint answers ok
    # (on this Linux sandbox that opens the folder itself --
    # no /select verb exists here; Windows/macOS select it).
    folder = base / "reveal-test"
    (folder / "hello.txt").write_text("hi")
    status, j = client.j("POST", "/api/reveal", {"name": "hello.txt"})
    assert status == 200 and j["ok"] is True, j
    # Guest (non-host role) is denied: a guest client whose
    # session role is flipped to guest gets the host-only 403.
    from test_link_round3 import _flip_role, _guest_client  # noqa: E402
    guest = _guest_client(port, "pw123")
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    status, j = guest.j("POST", "/api/reveal", {"name": "hello.txt"})
    assert status == 403 and j.get("code") == "host_only", (status, j)


def test_sep_off_still_routes_to_main_folder_live(server):
    # Item 2 is label-only: the 2.8.8 server behaviour (OFF =
    # all files to the Main Folder) must still hold.
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "sep-off-289", "password": "pw123"})
    assert status == 200 and j["ok"], j
    status, j = client.j("POST", "/api/separate_folders", {"enabled": False})
    assert status == 200 and j["ok"] and j["separate_folders"] is False
    status, auth = client.j("GET", "/api/authstate")
    assert auth["separate_folders"] is False
    assert auth["folder"] == auth["main_folder"]
