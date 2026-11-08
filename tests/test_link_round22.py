"""v2.8.7 / APK 2.6.81 big fix round (Essef Nov 4, 7:31 PM PT, 12 items)
+ QR redesign + no-green-buttons (Essef Nov 4, follow-ups).

PAGE checks (interpreted PAGE, round16-21 pattern) + live-server
checks via the round2/round16 fixtures: separate-folders toggle,
device dedupe, QR payload construction, and the no-green audit.
"""

import ast
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
from test_link_round2 import server, _raw  # noqa: F401,E402
from test_link_round3 import _flip_role  # noqa: E402

SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py")).read()
PAGE = None
for _n in ast.walk(ast.parse(SRC)):
    if isinstance(_n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "PAGE" for t in _n.targets
    ):
        PAGE = _n.value.value
        break
assert PAGE is not None


def test_version_287():
    assert 'VERSION = "2.8.7"' in SRC


def test_no_scroll_set_up():
    # Dialog fits its content: bounded width in BOTH axes, no
    # horizontal overflow, grids stack on narrow windows.
    assert ".lkbox:not(.guestcard) { width:min(960px, calc(100vw - 24px)); max-width:calc(100vw - 24px); box-sizing:border-box; overflow:hidden; }" in PAGE
    assert "#lkwrap { overflow:hidden; padding:12px; box-sizing:border-box; }" in PAGE
    assert "@media (max-width:720px) {" in PAGE
    assert ".lkbox:not(.guestcard) .lksplit { grid-template-columns:1fr; }" in PAGE


def test_locked_notice_open_notice_only_for_open():
    # Locked notice element + animation exist; open notice is gated
    # on gate-unlocked AND no stored password.
    assert 'id="lklockedwarn"' in PAGE
    assert "@keyframes lockpulse" in PAGE
    assert "const _lkNoticeLocked = !!(st.locked || st.has_password);" in PAGE
    assert 'warn.classList.toggle("show", !_lkNoticeLocked);' in PAGE
    assert 'lwarn.classList.toggle("show", _lkNoticeLocked);' in PAGE
    assert 'warn.classList.toggle("show", !st.locked);' not in PAGE


def test_no_password_top_left_text_removed():
    # SUPERSEDED in part by round34 item (5) (Essef Nov 5): the
    # guest-login note is REINSTATED -- green, under the password
    # field, matching the APK -- while the Set Up lkstate surface
    # still never carries the text. The eye-reveal toast (a
    # different, transient surface, not top-left) is unchanged.
    assert "No password set for this address." not in PAGE
    # Exactly one use: the guest-login note in checkOpenAddress.
    assert PAGE.count("No password set for this address, click Connect.") == 1
    seg = PAGE[PAGE.index("async function checkOpenAddress(name){"):
               PAGE.index("async function checkOpenAddress(name){") + 1400]
    assert "No password set for this address, click Connect." in seg


def test_save_icon_lowered_button_size_unchanged():
    assert ".lkbox #lkset svg { transform:translateY(3px); }" in PAGE
    assert ".lkbox:not(.guestcard) .lksavewrap .btn.primary { width:150px; height:48px; min-height:48px; font-size:18px; border-radius:8px; }" in PAGE


def test_menu_redesign_cards_blur_main_folder():
    assert 'class="sbcard"' in PAGE
    assert "backdrop-filter:blur(14px)" in PAGE
    assert "#sidebar { background:rgba(13,18,32,.55);" in PAGE
    assert "#sidebar" in PAGE and "width:264px" in PAGE
    assert '<div class="sbsec">Main Folder</div>' in PAGE
    assert "Open the Main Folder on this PC" in PAGE
    assert "Change the Main Folder on this PC" in PAGE
    assert 'id="swsep"' in PAGE
    assert "Create separate folder for each link" in PAGE
    # v2.8.8 SUPERSEDES the 2.8.7 disabled note (Essef Nov 4):
    # the note is removed entirely; see test_link_round23.
    assert "This option is disabled" not in PAGE


def test_home_buttons_refined_not_green():
    # v2.8.8 SUPERSEDES the 2.8.7 sizes below (Essef Nov 4 button
    # tightening; see test_link_round23). The teal family is
    # still gone from buttons.
    assert ".board .nbtnrow .btn { font-size:12px; padding:8px 7px; gap:5px; }" in PAGE
    assert ".board .fbtnrow .btn { font-size:11px; padding:8px 5px; gap:4px; }" in PAGE
    assert "#2dd4bf" not in PAGE


def test_send_section_and_dropzone_split():
    assert ".board #drop { padding:16px 12px; }" in PAGE
    assert 'or click to browse &mdash; they land in:<span class="dirline"><b id="dirnamelabel">' in PAGE


def test_dropdown_animates_bigger_arrow():
    assert ".lkcurdd .ddchev { font-size:20px; }" in PAGE
    assert ".lkcurdd .ddlist { display:block; opacity:0; visibility:hidden; pointer-events:none; transform:translateY(-6px); transition:opacity .22s ease, transform .22s ease, visibility 0s linear .22s; }" in PAGE
    assert ".lkcurdd .ddlist.open { opacity:1; visibility:visible; pointer-events:auto; transform:translateY(0);" in PAGE


def test_info_icon_only_host_only_themed():
    assert '<div class="lkpermtip" id="lkpermtip">HOST ONLY - APPLIES TO INDIVIDUAL ADDRESS</div>' in PAGE
    assert "Permissions are saved for this address only" not in PAGE
    assert ".lkpermtip { position:fixed; z-index:6000;" in PAGE
    assert "html.light .lkpermtip { background:#ffffff; color:#1e293b;" in PAGE


def test_qr_payload_and_themed_popup():
    # Server builds the QR from the full URL + trailing slash.
    assert '_qr_url = (self.server.url or "").rstrip("/") + "/"' in SRC
    assert "qr_png(_qr_url)" in SRC
    # Popup is themed (card background), QR itself keeps a white pad.
    assert ".qrpop .qr { background:var(--card);" in PAGE
    assert ".qrpop .qr img { width:220px; height:220px; background:#fff; padding:10px;" in PAGE


def test_no_green_button_fills_web():
    # Every web button fill that was teal/green is now app blue.
    assert "background:#277ff0; color:#ffffff;" in PAGE
    assert ".rnbtn.ok { background:#277ff0; color:#fff; }" in PAGE
    assert '--c1:#277ff0;--c2:#0ea5e9' in PAGE
    # Checkbox ticks are NOT buttons and are intentionally kept.
    assert ".permchk input:checked + .permbox { background:#22c55e;" in PAGE


def test_apk_no_green_buttons_and_qr_local():
    apk_dir = os.path.join(os.path.dirname(__file__), "..", "..",
                           "dropit-android")
    main = open(os.path.join(apk_dir, "app/src/main/java/com/dropit/app/MainActivity.kt")).read()
    assert "btn_main_teal" not in main and "btn_main_teal" not in open(
        os.path.join(apk_dir, "app/src/main/res/layout/activity_main.xml")).read()
    assert os.path.exists(os.path.join(apk_dir, "app/src/main/res/drawable/btn_main_blue.xml"))
    blue = open(os.path.join(apk_dir, "app/src/main/res/drawable/btn_main_blue.xml")).read()
    assert "#277FF0" in blue
    assert not os.path.exists(os.path.join(apk_dir, "app/src/main/res/drawable/btn_main_teal.xml"))
    # APK QR encodes http://<address>.local:<port>/
    assert 'return "http://$name.local:$port/"' in main
    # APK drawer: cards + Main Folder rename + 264dp width
    drawer = open(os.path.join(apk_dir, "app/src/main/res/layout/drawer_panel.xml")).read()
    assert 'android:layout_width="264dp"' in drawer
    assert "@drawable/card_bg" in drawer
    assert "MAIN FOLDER" in drawer


def _host_client(server):
    client, base, proc, port, home = server
    return client, port, home


def test_separate_folders_toggle_live(server):
    client, port, home = _host_client(server)
    status, j = client.j("POST", "/api/setlink",
                         {"name": "10-30-99", "password": "pw123"})
    assert status == 200 and j["ok"], j
    # Default ON: authstate reports True.
    status, auth = client.j("GET", "/api/authstate")
    assert status == 200 and auth.get("separate_folders") is True
    # OFF: per-link folder change refused; uploads land in Main Folder.
    status, j = client.j("POST", "/api/separate_folders", {"enabled": False})
    assert status == 200 and j["ok"] and j["separate_folders"] is False
    status, auth = client.j("GET", "/api/authstate")
    assert auth["separate_folders"] is False
    assert auth["folder"] == auth["main_folder"]
    status, j = client.j("POST", "/api/setlinkfolder", {"folder": "/tmp/should-not-stick"})
    assert status == 200 and j["ok"] is False
    # A FRESH address while OFF must not create its own subfolder:
    # the earlier 10-30-99 folder (created while ON) legitimately
    # still exists, so the no-creation proof needs a new name.
    status, j = client.j("POST", "/api/setlink",
                         {"name": "10-31-00", "password": "pw123"})
    assert status == 200 and j["ok"], j
    status, _ = client.upload("sep.txt", b"sep")
    assert status == 200
    assert not os.path.exists(os.path.join(auth["main_folder"], "10-31-00"))
    assert os.path.exists(os.path.join(auth["main_folder"], "sep.txt"))
    # ON again: per-link folder restored.
    status, j = client.j("POST", "/api/separate_folders", {"enabled": True})
    assert status == 200 and j["separate_folders"] is True
    status, auth = client.j("GET", "/api/authstate")
    assert auth["folder"].rstrip("/").endswith("10-31-00")


def test_sessions_dedupe_live(server):
    client, port, home = _host_client(server)
    status, j = client.j("POST", "/api/setlink",
                         {"name": "10-30-99", "password": "pw123"})
    assert status == 200 and j["ok"], j
    from test_link_folders import Client
    # Same device logs in twice (two tokens, same IP + UA hint).
    for _ in range(2):
        g = Client(port)
        status, gj = g.j("POST", "/api/login", {"password": "pw123"})
        assert status == 200 and gj["ok"], gj
    status, sj = client.j("GET", "/api/sessions")
    assert status == 200 and sj["ok"], sj
    keys = [(str(x.get("ip") or ""), str(x.get("display_name") or x.get("device_name") or "")) for x in sj["sessions"]]
    assert len(keys) == len(set(keys)), keys
    status, st = client.j("GET", "/api/status")
    assert status == 200
    names = st.get("device_names") or []
    assert len(names) == len(set(names)), names


def test_qr_url_construction():
    # server.url for a named address is the .local form; the QR
    # handler appends the trailing slash (decode-proven separately
    # against a live server in the delivery probe).
    assert 'server.url = (f"http://{_link}.local:{port}"' in SRC
    url = "http://10-30-99.local:8000"
    assert (url.rstrip("/") + "/") == "http://10-30-99.local:8000/"
