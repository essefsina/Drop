"""v2.8.13 / APK 2.6.87 round — logo correction ONLY (Essef Nov 4, 11:52 PM).

Essef sent the correct logo (~/workspace/user/media_library/image/icon.png):
blue droplet with WHITE WIFI ARCS above a white document (4 blue lines,
folded top-right corner) — NOT the sparkle version. The sparkle droplet
(md5 3a8a5df47d24cf9605b30918f21b5948) was the wrong file in 2.8.12 and
must not be bundled as the logo anywhere.

Changes in this round, behaviour untouched:
  - ~/workspace/dropit/logo.png replaced by a byte copy of icon.png
    (served as /logo.png: menu header + guest-login wordmark).
  - ~/workspace/dropit-android/app/src/main/res/drawable/app_logo.png
    replaced by a byte copy of icon.png (APK drawer header + login).
  - Launcher mipmap ic_launcher.png files were ALREADY the WiFi
    version — left untouched.
  - ~/workspace/dropit/icon.png was already the correct file — left
    untouched (favicon / manifest / pywebview icon).
  - VERSION 2.8.12 -> 2.8.13; APK 2.6.86 (code 106) -> 2.6.87 (code 107).
"""

import hashlib
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
from test_link_round2 import server  # noqa: F401,E402

CORRECT_MD5 = "11592bea1e152e761b1f1d36ec9f3389"  # icon.png, WiFi arcs
SPARKLE_MD5 = "3a8a5df47d24cf9605b30918f21b5948"  # wrong file, must be gone

APK = os.path.join(os.path.dirname(__file__), "..", "..", "dropit-android")
APK_MANIFEST = open(os.path.join(
    APK, "app/src/main/AndroidManifest.xml")).read()
APK_GRADLE = open(os.path.join(APK, "app/build.gradle")).read()


def _md5(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()


def test_version_is_2_8_13():
    assert D.VERSION == "2.8.13"


def test_desktop_logo_is_wifi_version():
    p = os.path.join(os.path.dirname(__file__), "..", "logo.png")
    assert _md5(p) == CORRECT_MD5
    assert _md5(p) != SPARKLE_MD5


def test_apk_logo_is_wifi_version():
    p = os.path.join(
        APK, "app/src/main/res/drawable/app_logo.png")
    assert _md5(p) == CORRECT_MD5
    assert _md5(p) != SPARKLE_MD5


def test_logo_matches_icon_png_source():
    src = os.path.join(os.path.dirname(__file__), "..", "..",
                       "user/media_library/image/icon.png")
    assert _md5(src) == CORRECT_MD5
    assert open(os.path.join(os.path.dirname(__file__), "..",
                             "logo.png"), "rb").read() == open(src, "rb").read()


def test_logo_transparent_corners():
    from PIL import Image
    p = os.path.join(os.path.dirname(__file__), "..", "logo.png")
    im = Image.open(p)
    assert im.mode == "RGBA"
    assert im.size == (512, 512)
    for xy in [(0, 0), (511, 0), (0, 511), (511, 511)]:
        assert im.getpixel(xy)[3] == 0, xy


def test_logo_png_served_is_wifi_version(server):
    client, base, proc, port, home = server
    status, raw = client.call("GET", "/logo.png")
    assert status == 200, status
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    assert hashlib.md5(raw).hexdigest() == CORRECT_MD5


def test_apk_version_2_6_87():
    assert "versionCode 107" in APK_GRADLE
    assert 'versionName "2.6.87"' in APK_GRADLE
    assert 'android:versionCode="107"' in APK_MANIFEST
    assert 'android:versionName="2.6.87"' in APK_MANIFEST


# --- v2.6.87 follow-ups (Essef Nov 4, 11:57 PM) -----------------------
def _apk_xml(name):
    return open(os.path.join(
        APK, "app/src/main/res/layout", name)).read()


def test_apk_setup_x_inside_purple_header():
    """Set Up modal X must sit INSIDE the purple header banner,
    at its top-right, vertically centred with the title — not in
    a separate row above the header (the 2.6.86 bug: it floated
    detached above/outside the banner)."""
    xml = _apk_xml("dialog_link.xml")
    # Exactly one lkClose, and it must appear AFTER the header's
    # title view and BEFORE the header's closing tag region — i.e.
    # inside the btn_save_violet_solid header row, not above it.
    assert xml.count('android:id="@+id/lkClose"') == 1
    i_title = xml.find('android:id="@+id/lkTitle"')
    i_close = xml.find('android:id="@+id/lkClose"')
    i_header_bg = xml.find("btn_save_violet_solid")
    assert 0 < i_header_bg < i_title < i_close
    # The title column is weight-1 so the X is pushed to the
    # header's right edge; the X is 32dp, centred vertically.
    assert 'android:layout_weight="1"' in xml
    assert 'android:layout_width="32dp"' in xml[i_close:i_close + 400]
    assert 'android:layout_gravity="center_vertical"' in xml[i_close:i_close + 400]
    assert "@drawable/close_btn_bg" in xml[i_close:i_close + 400]
    # No separate X row above the header any more.
    assert xml.find('android:id="@+id/lkClose"') > xml.find("btn_save_violet_solid")


def test_apk_choose_files_button_dark_brown():
    """Choose Files to Send (Upload tab) is DARK BROWN on the APK
    only (Essef's explicit choice; supersedes blue/teal)."""
    xml = _apk_xml("activity_main.xml")
    i_btn = xml.find('android:id="@+id/sendBtn"')
    assert i_btn > 0
    seg = xml[i_btn:i_btn + 900]
    assert "@drawable/btn_main_brown" in seg
    assert 'android:textColor="#FFFFFF"' in seg
    brown = open(os.path.join(
        APK, "app/src/main/res/drawable/btn_main_brown.xml")).read()
    assert "#4E342E" in brown
    # Desktop/web Choose Files button is untouched (still blue).
    import re as _re
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "dropit.py")).read()
    assert "btn_main_brown" not in src


# --- v2.6.87 follow-ups 2 (Essef Nov 5, 12:00 AM) ---------------------
def _apk_layout(name):
    return open(os.path.join(
        APK, "app/src/main/res/layout", name)).read()


def test_apk_menu_empty_folder_card_removed():
    """The empty white box under the YOUR ADDRESS card was the
    Main Folder card with every child hidden for guests (folder
    label/text GONE for host-path hide, separate-folders row
    gone) — an empty padded card. The whole card is now hidden,
    so the Theme card sits directly below the address card.
    The 'This address is not locked' status line is kept."""
    xml = _apk_layout("drawer_panel.xml")
    assert 'android:id="@+id/drawerFolderCard"' in xml
    assert 'android:id="@+id/drawerLockText"' in xml
    assert "This address is not locked" in xml
    kt = open(os.path.join(
        APK, "app/src/main/java/com/dropit/app/MainActivity.kt")).read()
    i = kt.find("drawerFolderCard")
    assert i > 0
    assert "View.GONE" in kt[i:i + 200]


def test_change_button_purple_darkened():
    """Files card Change button (folder+arrow) is slightly darker
    purple, same hue, white text/icon, same size/shape — on every
    surface that purple Change button appears (Files card,
    Set Up dialog, menu). Old light #A78BFA must not remain on
    any Change button rule."""
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "dropit.py")).read()
    assert ".board .fbtnrow #changefolder { background:#8B5CF6;" in src
    assert ".btn.changef { background:linear-gradient(135deg,#8B5CF6,#6D28D9);" in src
    assert ".lkbox .btn.changef { background:#6D28D9;" in src
    assert "linear-gradient(135deg,#8B5CF6,#6D28D9)" in src  # menu #sbchange
    assert "#changefolder { background:#a78bfa" not in src
    assert ".btn.changef { background:linear-gradient(135deg,#A78BFA,#7C3AED)" not in src


def test_web_choose_files_dark_brown_pill():
    """Web/mobile-web 'Choose files to send' (#msendfiles) is
    DARK BROWN (#4E342E, same as the APK button) and a PILL
    (fully rounded), white text + white folder icon. No other
    button's colour or shape changes."""
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "dropit.py")).read()
    assert ".msend #msendfiles { background:#4E342E; color:#FFFFFF; border-radius:999px; }" in src
    assert ".msend #msendfiles svg { fill:#FFFFFF; }" in src
    # Other buttons unchanged: Send Text stays blue, rectangular.
    assert ".msend .mbtn-primary, .msend #msendfiles {\n    background:#277ff0;" in src
    assert ".msend .mbtn-primary, .msend .mbtn-secondary,\n  .lkbox .btn, .mbox .btn" in src


def test_web_upload_icon_replaces_paper_plane():
    """Every paper-plane icon in the web page is replaced by the
    upload icon (up-arrow over a tray, same geometry as the APK
    Upload tab icon ic_send.xml) — Send Files heading, Send Text
    button, mobile Send Text button. Sizes/alignment/colours of
    each icon are unchanged; the chat-bubble Send Text heading
    icon and the AI sparkle are untouched."""
    import ast as _ast
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "dropit.py")).read()
    page = None
    for _n in _ast.walk(_ast.parse(src)):
        if isinstance(_n, _ast.Assign) and any(
                isinstance(t, _ast.Name) and t.id == "PAGE"
                for t in _n.targets):
            page = _n.value.value
            break
    assert page is not None
    assert "M22 2" not in page  # feather paper-plane paths, gone
    assert "&#x2708" not in page  # airplane emoji, gone
    assert page.count("M12 15.5V4.2M6.9 8.8L12 3.7 17.1 8.8") == 3
    assert page.count("M4.5 14.8V18.2A1.8 1.8 0 0 0 6.3 20H17.7A1.8 1.8 0 0 0 19.5 18.2V14.8") == 3
    # The Send Text heading keeps its chat-bubble icon.
    assert "M21 11.5a8.38 8.38 0 0 1-.9 3.8" in page


def test_login_page_hides_menu():
    """The hamburger/menu must NOT appear on the web login page:
    showGuestLogin hides the top bar and closes the drawer, and
    showGuestMain restores it; openSidebar refuses to open while
    the login page is open. (Root cause: showGuestLogin hid
    .board/.mtabs but left .topbar visible.)"""
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "dropit.py")).read()
    i = src.find("function showGuestLogin(msg){")
    assert i > 0
    seg = src[i:i + 900]
    assert 'document.querySelector(".topbar")' in seg
    assert 'tb.style.display = "none"' in seg
    assert "openSidebar(false)" in seg
    j = src.find("function showGuestMain(){")
    assert j > 0
    assert 'tb.style.display = ""' in src[j:j + 300]
    k = src.find("function openSidebar(o){")
    assert k > 0
    assert 'classList.contains("open")' in src[k:k + 400]
    assert "#guestlogin" in src[k:k + 400]


def test_save_buttons_solid_blue_smaller():
    """Set Up / Connect Save is SOLID BLUE (#277ff0 — the guest
    Connect Save was purple #7c3aed) and a bit smaller; the Set
    Password Save was already solid blue and only shrinks."""
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "dropit.py")).read()
    assert ".lkbox.guestcard .btn.primary { background:#277ff0; }" in src
    assert ".lkbox:not(.guestcard) .lksavewrap .btn.primary { width:126px; height:38px;" in src
    assert ".lkbox.guestcard .lksavewrap .btn.primary { width:136px; min-height:40px;" in src
    assert ".lockpwbox .lockpwsave { min-width:146px; padding:10px 24px; }" in src
    assert ".lockpwbox .lockpwsave { background:#277ff0;" in src


def test_logo_fallback_and_build_bundles_logo():
    """The broken-logo root cause: frozen builds never bundled
    logo.png (build.bat only added icon.png), so /logo.png 404'd.
    The handler now falls back to icon.png (same WiFi artwork,
    byte-identical), and all three build commands bundle logo.png."""
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "dropit.py")).read()
    i = src.find('elif path == "/logo.png":')
    assert i > 0
    seg = src[i:i + 1100]
    assert 'p = asset_path("logo.png")' in seg
    assert 'p = asset_path("icon.png")' in seg
    here = os.path.join(os.path.dirname(__file__), "..")
    assert '"logo.png;."' in open(os.path.join(here, "build.bat")).read()
    assert '"logo.png;."' in open(os.path.join(here, "app.py")).read()
    assert '"logo.png:."' in open(os.path.join(here, "build-mac.sh")).read()
