"""v2.8.14 / APK 2.6.88 round (Essef Nov 5, 12:33 AM + follow-ups).

  1. Web Save -> Connect / Disconnect like the APK (mobile Set Up card).
  2. APK QR encodes the reachable LAN-IP URL, not .local.
  3. Web bottom tabs redesigned like the APK (pill + coloured icons).
  4. Word (.doc/.docx) preview on web + APK.
  5. PDF preview on web (always ?preview=1).
  6. Guestcard X moved to the top-right corner, clear of all text.
  7. Guestcard Save text centred with the floppy icon.
  8. Login Connect button narrower (60%), centred, solid blue.
  9. Open-in-folder (reveal) on the PC app: verbatim Explorer command.
 10. Change Folder icon shifted right to align with Open Folder icon.
 11. Theme switch works in real time on all platforms (APK: recreate
      + ui_theme_restore fast path; web: class toggle, no reload).
"""
import ast
import os
import re
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
from test_link_round2 import server  # noqa: F401,E402
from test_link_folders import Client, _free_port  # noqa: E402

APK = os.path.join(os.path.dirname(__file__), "..", "..", "dropit-android")
APK_MAIN = os.path.join(
    APK, "app/src/main/java/com/dropit/app/MainActivity.kt")
APK_MANIFEST = open(os.path.join(
    APK, "app/src/main/AndroidManifest.xml")).read()
APK_GRADLE = open(os.path.join(APK, "app/build.gradle")).read()
APK_PREVIEW_XML = open(os.path.join(
    APK, "app/src/main/res/layout/dialog_preview.xml")).read()
MAIN_SRC = open(APK_MAIN).read()
PAGE = D.PAGE
FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def test_version_is_2_8_14():
    assert D.VERSION == "2.8.14"


def test_apk_version_2_6_88():
    assert "versionCode 108" in APK_GRADLE
    assert 'versionName "2.6.88"' in APK_GRADLE
    assert 'android:versionCode="108"' in APK_MANIFEST
    assert 'android:versionName="2.6.88"' in APK_MANIFEST


# ---- 4. Word preview: server-side extraction ---------------------------

def test_doc_to_text_simple():
    assert D.doc_to_text(os.path.join(FIX, "test.doc")) == (
        "Hello docx world\nSecond paragraph 123")


def test_doc_to_text_rich():
    text = D.doc_to_text(os.path.join(FIX, "rich.doc"))
    assert text is not None
    assert "Quarterly Report" in text
    assert "Café" in text
    assert "Cell A1" in text and "Cell B2" in text
    assert "Final line." in text


def test_doc_to_text_rejects_non_doc():
    assert D.doc_to_text(os.path.join(FIX, "test.docx")) is None
    assert D.doc_to_text(os.path.join(FIX, "nope.doc")) is None
    assert D.doc_to_text(__file__) is None


def test_docx_endpoint_serves_docx_and_doc(server):
    import shutil
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "probe"})
    assert status == 200 and j["ok"]
    folder = base / "probe"
    for name in ("test.docx", "test.doc", "rich.doc"):
        shutil.copy(os.path.join(FIX, name), folder / name)
    c = Client(port)
    status, raw = c.call("GET", "/api/docx/?name=test.docx")
    assert status == 200
    assert b"Hello docx world" in raw
    assert b"<p>" in raw
    status, raw = c.call("GET", "/api/docx/?name=test.doc")
    assert status == 200
    assert b"Hello docx world" in raw
    assert b"Second paragraph 123" in raw
    assert b"<pre>" in raw
    status, raw = c.call("GET", "/api/docx/?name=rich.doc")
    assert status == 200
    assert "Café".encode("utf-8") in raw
    assert b"Cell A1" in raw


def test_docx_endpoint_rejects_other_types(server):
    client, base, proc, port, home = server
    c = Client(port)
    status, _ = c.call("GET", "/api/docx/?name=notes.txt")
    assert status == 404
    status, _ = c.call("GET", "/api/docx/?name=missing.docx")
    assert status == 404


# ---- 5. PDF preview: preview fetch is always inline ---------------------

def test_preview_url_always_preview_param():
    assert ('const url = "/dl/" + encodeURIComponent(name) + "?preview=1";'
            in PAGE)


def test_preview_has_word_branch():
    # PAGE is the INTERPRETED page: one backslash in the JS regex.
    assert r"if(/\.docx?$/.test(name)){" in PAGE
    assert 'fetch("/api/docx/?name=" + encodeURIComponent(name))' in PAGE
    assert '<div class="docxview">' in PAGE


# ---- 1. Mobile Connect / Disconnect like the APK ------------------------

def test_mobile_connect_disconnect_buttons():
    assert 'id="mpcconnect"' in PAGE
    assert 'id="mpcdisconnect"' in PAGE
    assert "> Connect</button>" in PAGE
    assert "> Disconnect</button>" in PAGE
    # APK colours/icons: Connect solid violet #7C3AED with the APK
    # right-arrow path; Disconnect solid red #EF4444 with </>.
    assert ".mpc-connect { background:#7C3AED; }" in PAGE
    assert ".mpc-disconnect { background:#EF4444; }" in PAGE
    assert "M3,12h17M14.5,5.5L21,12l-6.5,6.5" in PAGE
    assert "M7,7l-3,3 3,3M17,7l3,3 -3,3M13,4l-2,16" in PAGE
    assert ".mpc-connect.connected svg { stroke:#22C55E; }" in PAGE
    # The old purple-gradient Save is gone from this card.
    assert 'id="mpcconnect" data-tip="Connect to this address"' in PAGE
    assert "&#x1F4BE;&nbsp; Save</button>" not in PAGE


def test_mobile_disconnect_calls_logout():
    assert 'if(mpcd) mpcd.onclick = () => { doLogout(); toast("Disconnected"); };' in PAGE


# ---- 3. Web tabs: pill + coloured icons ---------------------------------

def test_web_tabs_pill_container():
    assert "border-radius:999px;" in PAGE
    assert "left:50%; transform:translateX(-50%); bottom:12px;" in PAGE
    assert "width:min(480px, calc(100vw - 24px));" in PAGE


def test_web_tabs_coloured_icons():
    assert 'stroke="#22C55E"' in PAGE  # Upload green
    assert 'stroke="#D9A441"' in PAGE  # Notes amber
    assert 'stroke="#3B82F6"' in PAGE  # Files blue
    assert 'stroke="#A78BFA"' in PAGE  # Search violet sparkle
    # No emoji tab icons remain inside the bottom tab nav itself
    # (the desktop Upload column heading still uses the arrow glyph).
    nav = re.search(r'<nav class="mtabs">.*?</nav>', PAGE, re.S).group(0)
    assert "&#x2B06;&#xFE0F;" not in nav
    assert "&#x1F4AC;" not in nav
    assert "&#x1F4C1;" not in nav


# ---- 6/7/8. Guestcard X, Save alignment, login Connect ------------------

def test_guestcard_x_top_right_corner():
    assert ".lkbox.guestcard .lkclosebtn { top:10px; right:12px; }" in PAGE
    assert ".lkbox.guestcard .guestcardhead { margin-top:20px; }" in PAGE
    assert ".lkbox.guestcard .lkclosebtn { top:50px; right:40px; }" not in PAGE


def test_guestcard_save_text_centred_with_floppy():
    assert (".lkbox.guestcard #lkset { display:inline-flex; "
            "align-items:center; justify-content:center; gap:8px; "
            "line-height:1; }" in PAGE)
    assert ".lkbox.guestcard #lkset svg { transform:none; }" in PAGE


def test_login_connect_narrow_centred_solid_blue():
    assert (".gloginbox #gloginbtn { width:60%; margin-left:auto; "
            "margin-right:auto; display:block; background:#277ff0; "
            "border:none; }" in PAGE)


# ---- 10. Change Folder icon alignment ------------------------------------

def test_change_folder_icon_shifted_right():
    assert "#sidebar #sbchange svg { position:relative; left:6.7px; }" in PAGE
    assert "#lkchangefolder svg { position:relative; left:7.8px; }" in PAGE
    assert "#changefolder svg { position:relative; left:6.7px; }" in PAGE


# ---- 9. Reveal: verbatim Explorer command --------------------------------

def test_reveal_uses_verbatim_explorer_command():
    app_src = open(os.path.join(
        os.path.dirname(__file__), "..", "app.py")).read()
    dropit_src = open(os.path.join(
        os.path.dirname(__file__), "..", "dropit.py")).read()
    assert 'subprocess.Popen(\'explorer /select,"\' + path + \'"\')' in app_src
    assert 'subprocess.Popen(\'explorer /select,"\' + target + \'"\')' in dropit_src
    assert '["explorer", "/select,", path]' not in app_src
    assert '["explorer", "/select,", target]' not in dropit_src


def test_reveal_bridge_call_has_timeout_race():
    assert "Promise.race([window.pywebview.api.reveal_file(name)" in PAGE
    assert "setTimeout(() => r(false), 3000)" in PAGE


def test_api_reveal_file_command_string(tmp_path, monkeypatch):
    """Invoke the desktop bridge path in-process with a faked
    win32 platform and a captured Popen: the exact Explorer
    command line must be explorer /select,"<spaced path>"."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    import app as appmod
    calls = []

    class FakePopen:
        def __init__(self, *a, **k):
            calls.append(a[0] if a else k.get("args"))

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setattr(sys, "platform", "win32")
    folder = tmp_path / "DropItFiles" / "probe"
    folder.mkdir(parents=True)
    (folder / "hello world.txt").write_text("hi")
    api = appmod.Api.__new__(appmod.Api)
    monkeypatch.setattr(api, "_link_dir", lambda: str(folder))
    assert api.reveal_file("hello world.txt") is True
    assert len(calls) == 1
    assert calls[0] == 'explorer /select,"' + str(folder / "hello world.txt") + '"'
    assert api.reveal_file("missing.txt") is False
    assert api.reveal_file("../escape.txt") is False


def test_api_reveal_endpoint_wiring(server):
    import shutil
    client, base, proc, port, home = server
    c = Client(port)
    status, j = c.j("POST", "/api/setlink", {"name": "probe"})
    assert status == 200 and j["ok"]
    shutil.copy(os.path.join(FIX, "test.docx"), base / "probe" / "test.docx")
    status, j = c.j("POST", "/api/reveal", {"name": "test.docx"})
    assert status == 200 and j["ok"] is True
    status, j = c.j("POST", "/api/reveal", {"name": "missing.docx"})
    assert status == 200 and j["ok"] is False


# ---- 2. APK QR: resolved LAN-IP URL first --------------------------------

def test_apk_qr_prefers_resolved_server_url():
    fn = re.search(r"private fun qrAddress\(\).*?\n    \}", MAIN_SRC, re.S)
    assert fn, "qrAddress not found"
    body = fn.group(0)
    assert "val srv = server()" in body
    assert (body.index('return srv.trimEnd') <
            body.index('return "http://$name.local:$port/"'))
    assert "http://$name.local:$port/" in body  # fallback only


# ---- 4 (APK). Word preview in the dialog ---------------------------------

def test_apk_word_preview_webview():
    assert 'android:id="@+id/pvWeb"' in APK_PREVIEW_XML
    assert "<WebView" in APK_PREVIEW_XML
    assert 'ext == "docx" || ext == "doc"' in MAIN_SRC
    assert '"$srv/api/docx/?name=${Uri.encode(name)}"' in MAIN_SRC
    assert "loadDataWithBaseURL(null, docxWrap(html)" in MAIN_SRC
    assert "private fun docxWrap(inner: String)" in MAIN_SRC
    assert "javaScriptEnabled = false" in MAIN_SRC


# ---- 11. Theme switch ------------------------------------------------------

def test_apk_theme_switch_uses_recreate_with_restore():
    fn = re.search(r"private fun applyThemeInPlace\(toLight: Boolean\).*?\n    \}",
                   MAIN_SRC, re.S)
    assert fn, "applyThemeInPlace not found"
    body = fn.group(0)
    assert "recreate()" in body
    assert '.putBoolean("ui_theme_restore", true)' in body
    assert "setContentView(R.layout.activity_main)" not in body
    assert "setTheme(" not in body


def test_web_theme_is_class_toggle_no_reload():
    assert 'document.documentElement.classList.toggle("light", on);' in PAGE
    assert 'localStorage.getItem("drop_theme")==="light"' in PAGE


# ---- PAGE guardrails -------------------------------------------------------

def test_page_script_blocks_still_valid():
    src = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py")).read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') == 'PAGE':
            page = node.value.value
            assert not [c for c in page if 0xD800 <= ord(c) <= 0xDFFF]
            page.encode('utf-8')
            scripts = re.findall(r'<script>(.*?)</script>', page, re.S)
            assert len(scripts) == 2
            import tempfile
            for s in scripts:
                with tempfile.NamedTemporaryFile(
                        'w', suffix='.js', delete=False) as f:
                    f.write(s)
                    fn = f.name
                r = subprocess.run(['node', '--check', fn],
                                   capture_output=True, text=True)
                os.unlink(fn)
                assert r.returncode == 0, r.stderr
            return
    raise AssertionError("PAGE not found")
