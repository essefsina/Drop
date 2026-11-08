"""v2.8.12 / APK 2.6.86 round (Essef Nov 4, 11:14 PM, 3 screenshots).

Desktop items covered:
  1. Menu Main Folder buttons CENTRED + full "Change Folder".
     Root causes (both fixed): paintSeparateFolders() rewrote the
     2.8.11 HTML rename back to "Change" on every paint, AND
     #sidebar .sbbtn (display:inline-flex, 1,1,0) beat the 2.8.11
     #sbopen rule (1,0,0) on display, so auto margins could not
     centre the inline-level buttons (measured x=27, left-aligned
     in the rendered 2.8.11 sidebar).
  2. Remove Address modal ON TOP (z-index 4000, above the Set Up
     backdrop at 300) + its X top-right, coloured + bordered (32px).
  3. "Set Password For Address" line one step down (margin-top 8px
     on .lockpwbox h4 only -- nothing else resized).
  4. Delete/disconnect redder: in-between red #ef4444 solid /
     gradient #ef4444 -> #e11d48 (redder than the reverted #f87171,
     still short of the rejected 2.8.10 #dc2626, which stays out
     of live code).
  7. APK "Choose Files to Send": NO colour change in the 2.6.85
     ship (2.6.83 and 2.6.85 APKs both btn_main_blue #277FF0 --
     verified by aapt2 dump); only the narrower width (32dp side
     margins) is the 2.8.11 change, and it stays. The last colour
     change was teal #2DD4BF -> blue in 2.6.81, per Essef's
     no-green-buttons rule -- reverting to teal would break it,
     so the blue stands (see the report).
  8. QR encodes the LAN IP URL (http://<lan_ip>:<port>/), not the
     .local name: most phone browsers never resolve .local, so
     scanning gave "this site can't be reached". Address-name
     display is untouched (server.url stays .local; setlink still
     returns it). NOTE: this sandbox blocks non-loopback TCP, so
     opening the LAN-IP URL from a client cannot be exercised
     here -- the test proves the encoded payload byte-for-byte
     instead, and real-LAN/phone verification stays open.
 11. "Create Separate Folders" moved out of the Main Folder card
     into its own menu card BELOW the address card.
 12. Drop logo (Essef's fixed artwork, byte-identical) on the
     LEFT before the "Drop" text: menu header + guest-login
     wordmark, served as /logo.png.
 13. Preview stays available WITHOUT download_files (view-only
     /dl/?preview=1, served inline); only the Download button
     inside the preview window greys. Plain /dl/ still 403s.

APK items covered (source checks; the APK is built by build.sh):
  5. Upload icon GREEN (#22C55E), Files icon BLUE (#3B82F6).
  6. "Send" texts nudged left in the Send-tab buttons
     (drawablePadding 8dp -> 4dp + paddingEnd 20dp).
  9. Share Text keyboard: adjustResize + scroll-to-bottom on
     focus/tap, back closes the keyboard first.
 10. Saved-mode tap opens with the app chooser (Open), never
     re-downloads; the preview's button is Open for local files.
 13. (APK parity) preview without download_files via ?preview=1,
     Download button greyed in the preview window.

BY-DESIGN failures in older rounds after this change (do not
"fix" back):
  - round26 test_delete_colour_reverted_to_lighter_red (#f87171).
  - round26 test_qr_png_no_store: QR bytes NO LONGER change with
    the address -- the payload is the LAN IP URL, stable across
    address changes (that is the fix, item 8).
  - round26 test_apk_version_2_6_85, test_apk_delete_colour_reverted
    and test_apk_pill_icon_colours (2.6.85 pins, superseded here).
  - round25 test_delete_buttons_darker_red (#dc2626, already
    failing by design since round26).
"""

import ast
import hashlib
import http.client
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
from test_link_round2 import server, _raw  # noqa: F401,E402
from test_link_round16 import _guest, _set_perms, ALL_ON  # noqa: E402
from test_link_folders import Client  # noqa: E402

SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py")).read()
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
APK_MANIFEST = open(os.path.join(
    APK, "app/src/main/AndroidManifest.xml")).read()

LOGO_MD5 = "11592bea1e152e761b1f1d36ec9f3389"  # Essef's correct logo: WiFi arcs (2.8.13 supersedes the sparkle file 3a8a5df4...)


def _strip_css_comments(text):
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def test_version_is_2_8_12():
    assert D.VERSION == "2.8.12"


# ------------------------------------------------------------------- item 1
def test_menu_buttons_centred_full_labels():
    # Static HTML still says the full names.
    assert re.search(r'id="sbopen".*?>\s*Open Folder</button>', PAGE, re.S)
    assert re.search(r'id="sbchange".*?>\s*Change Folder</button>', PAGE, re.S)
    # The JS repaint no longer rewrites the menu label to "Change".
    assert '_setChangeLabel(scf, "Change Folder")' in PAGE
    assert '_setChangeLabel(scf, "Change")' not in PAGE
    # Files card stays one-word "Change" (only the menu pair changed).
    assert '_setChangeLabel(cf, "Change")' in PAGE
    # Centring: #sidebar #sbopen/#sbchange (2,0,0) beats
    # #sidebar .sbbtn inline-flex (1,1,0) on display, so the
    # 76% width + auto margins actually centre the buttons.
    m = re.search(
        r"#sidebar #sbopen, #sidebar #sbchange \{([^}]*)\}", PAGE)
    assert m, "centring override missing"
    body = m.group(1)
    assert "display:flex" in body
    assert "width:76%" in body
    assert "margin:8px auto 0" in body
    assert "white-space:nowrap" in body


# ------------------------------------------------------------------- item 2
def test_remove_address_modal_on_top_and_x_top_right():
    rules = re.findall(r"\.addrrempop \{([^}]*)\}", PAGE)
    assert rules, "addrrempop rule missing"
    # The v2.8.12 override comes last in the cascade and wins.
    assert "z-index:4000" in rules[-1], rules[-1]
    # Above the Set Up backdrop (.lockwrap, z-index 300).
    assert ".lockwrap" in PAGE and "z-index:300" in PAGE
    m = re.search(r"\.addrrembox \.lkclosebtn \{([^}]*)\}", PAGE)
    assert m, "addrrem X rule missing"
    body = m.group(1)
    assert "position:absolute" in body
    assert "top:10px" in body
    assert "right:12px" in body
    assert "width:32px" in body
    assert "border:1px solid #ef4444" in body
    assert "linear-gradient(135deg,#ef4444,#e11d48)" in body
    # The 2.8.11 small-X rule no longer shrinks the addrrem X.
    assert ".lockpwbox .lkclosebtn, .addrrembox .lkclosebtn" not in PAGE


# ------------------------------------------------------------------- item 3
def test_set_password_line_down_slightly_nothing_resized():
    assert ".lockpwbox h4 { margin-top:8px; }" in PAGE
    # The h4 sizes are untouched (16px base, 20px themed).
    assert ".lockpwbox h4 { font-size:16px;" in PAGE
    assert ".lockpwbox h4 { font-size:20px;" in PAGE


# ------------------------------------------------------------------- item 4
def test_delete_disconnect_redder_in_between():
    stripped = _strip_css_comments(PAGE)
    assert "#f87171" not in stripped, "old lighter red still live"
    assert "#dc2626" not in stripped, "rejected 2.8.10 red is live"
    assert "#ef4444" in stripped
    assert "linear-gradient(135deg,#ef4444,#e11d48)" in stripped
    # The delete fills + Disconnect All use the new solid.
    assert ".btn.dangergrad { background:#ef4444;" in stripped
    assert ".fact button.del { background:#ef4444;" in stripped
    assert ".devdropfoot .devdropall { width:100%; background:#ef4444;" in stripped
    assert ".addrrembox .addrremsave { background:#ef4444;" in stripped


# ------------------------------------------------------------------- item 8
def test_qr_encodes_lan_ip_url(server):
    if not D.HAS_QR:
        pytest.skip("qrcode/Pillow not installed in this sandbox")
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "qrtest"})
    assert status == 200 and j["ok"], j
    # Address-name display / API contract unchanged: .local still.
    assert j["url"] == "http://qrtest.local:%d" % port, j
    assert D._qr_connect_url  # helper exists
    status, b1, h1 = _raw_png(port, "/qr.png")
    assert status == 200 and b1[:8] == b"\x89PNG\r\n\x1a\n", status
    assert h1.get("Cache-Control") == "no-store", h1
    lan = D.lan_ip()
    assert lan not in ("127.0.0.1", ""), lan
    expected = D.qr_png("http://%s:%d/" % (lan, port))
    assert b1 == expected, "QR payload is not the LAN-IP URL"
    assert b1 != D.qr_png("http://qrtest.local:%d/" % port)
    # The payload is stable across address changes (it no longer
    # encodes the address at all -- that is the fix).
    status, j = client.j("POST", "/api/setlink", {"name": "qrtest2"})
    assert status == 200 and j["ok"], j
    status, b2, _ = _raw_png(port, "/qr.png")
    assert status == 200 and b2 == b1


def _raw_png(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", path)
    resp = conn.getresponse()
    raw = resp.read()
    headers = {k: v for k, v in resp.getheaders()}
    conn.close()
    return resp.status, raw, headers


# ------------------------------------------------------------------ item 11
def test_create_separate_folders_below_address_card():
    # Order in the sidebar HTML: address card, then the separate
    # folders card, then the Main Folder card.
    i_addr = PAGE.find("Set Up Your Addresses")
    i_sep = PAGE.find('id="swsep"')
    i_main = PAGE.find(">Main Folder<")
    assert 0 < i_addr < i_sep < i_main, (i_addr, i_sep, i_main)
    # The Main Folder card holds only the two folder buttons now.
    main_card = PAGE[i_main:i_main + 2000]
    assert "swsep" not in main_card
    assert 'id="sbopen"' in main_card and 'id="sbchange"' in main_card
    # The switch still exists once, and the Set Up dialog checkbox
    # (a different control for the same setting) is untouched.
    assert PAGE.count('id="swsep"') == 1
    assert 'id="lksepchk"' in PAGE


# ------------------------------------------------------------------ item 12
def test_logo_before_drop_text_desktop():
    assert '<img class="sblogo" src="/logo.png" alt="Drop logo">' in PAGE
    assert PAGE.find('class="sblogo"') < PAGE.find('class="sbtitle"')
    # Round34 (6): the login logo is stacked now -- the image on
    # top, "Drop" below it as its own line (APK style). The
    # logo still comes before the "Drop" text.
    assert '<div class="glogo"><img src="/logo.png" alt="Drop logo"><span class="gdrop">Drop</span></div>' in PAGE
    assert PAGE.find('/logo.png') < PAGE.find('class="gdrop"')
    # The bundled file is Essef's fixed artwork, byte-identical.
    p = os.path.join(os.path.dirname(__file__), "..", "logo.png")
    data = open(p, "rb").read()
    assert hashlib.md5(data).hexdigest() == LOGO_MD5


def test_logo_png_served(server):
    client, base, proc, port, home = server
    status, raw = client.call("GET", "/logo.png")
    assert status == 200, status
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    p = os.path.join(os.path.dirname(__file__), "..", "logo.png")
    assert raw == open(p, "rb").read()


# ------------------------------------------------------------------ item 13
def _raw_guest(guest, port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    hdrs = {}
    if guest.cookies:
        hdrs["Cookie"] = "; ".join(
            "%s=%s" % kv for kv in guest.cookies.items())
    conn.request("GET", path, headers=hdrs)
    resp = conn.getresponse()
    raw = resp.read()
    headers = {k: v for k, v in resp.getheaders()}
    conn.close()
    return resp.status, raw, headers


def test_preview_without_download_permission(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "previewtest", "password": "Essef2026!"})
    assert status == 200 and j["ok"], j
    status, _ = client.upload("hello.txt", b"hello preview")
    assert status == 200, status
    guest = _guest(port, home, "Essef2026!")
    _set_perms(client, {**ALL_ON, "download_files": False})
    # Plain download still 403s.
    s, _, _ = _raw_guest(guest, port, "/dl/hello.txt")
    assert s == 403, s
    # Preview fetch works, inline (no attachment disposition).
    s, raw, h = _raw_guest(guest, port, "/dl/hello.txt?preview=1")
    assert s == 200, s
    assert raw == b"hello preview"
    assert "attachment" not in h.get("Content-Disposition", ""), h
    # And with the permission back on, the plain download works.
    _set_perms(client, {**ALL_ON, "download_files": True})
    s, raw, _ = _raw_guest(guest, port, "/dl/hello.txt")
    assert s == 200 and raw == b"hello preview"


def test_preview_window_greys_download_only():
    # The old early-return (preview replaced by a no-permission
    # message) is gone; the Download button greys via .deloff
    # and toasts instead.
    assert ("body.innerHTML = '<p class=\"pvmsg\">No permission to "
            "download files from this device</p>'") not in PAGE
    assert '"?preview=1"' in PAGE or "?preview=1" in PAGE
    assert 'dl.classList.toggle("deloff", _noDl)' in PAGE
    assert "downloadPreviewFile(name);" in PAGE
    # downloadPreviewFile itself refuses without the permission.
    m = re.search(r"function downloadPreviewFile\(name\)\{(.*?)\n\}",
                  PAGE, re.S)
    assert m and "canDownloadUI()" in m.group(1)


# ---------------------------------------------------------------- APK: meta
def test_apk_version_2_6_86():
    gradle = open(os.path.join(APK, "app/build.gradle")).read()
    assert "versionCode 106" in gradle
    assert 'versionName "2.6.86"' in gradle
    assert 'android:versionCode="106"' in APK_MANIFEST
    assert 'android:versionName="2.6.86"' in APK_MANIFEST


# ------------------------------------------------------------- APK: item 5
def test_apk_pill_icon_colours_green_blue():
    assert "0xFF22C55E" in APK_KT  # Upload: GREEN
    assert "0xFF3B82F6" in APK_KT  # Files: BLUE
    assert "0xFFD9A441" in APK_KT  # Notes: amber, unchanged
    assert "0xFF7FB3E8" not in APK_KT  # old soft sky-blue Upload
    m = re.search(
        r"val tabIconColors = mapOf\((.*?)\)\)", APK_KT, re.S)
    assert m, "tabIconColors map missing"
    body = m.group(1)
    assert "R.id.tabIconSend to 0xFF22C55E" in body
    assert "R.id.tabIconFiles to 0xFF3B82F6" in body
    assert "0xFFA78BFA" not in body  # old soft violet Files


# ---------------------------------------------------------- APK: items 6+7
def test_apk_send_text_nudged_left_and_choose_files_colour():
    # Both Send-tab buttons: smaller icon gap + extra end padding
    # (the ~6dp left nudge), colour UNCHANGED (btn_main_blue).
    for btn_id in ('android:id="@+id/sendBtn"',
                   'android:id="@+id/sendTextBtn"'):
        i = APK_XML.find(btn_id)
        assert i != -1, btn_id
        block = APK_XML[i:i + 900]
        assert 'android:drawablePadding="4dp"' in block, btn_id
        assert 'android:paddingEnd="20dp"' in block, btn_id
        assert 'android:background="@drawable/btn_main_blue"' in block, btn_id
    # Narrower width from 2.6.85 kept (32dp side margins).
    assert APK_XML.count('android:layout_marginStart="32dp"') >= 2
    assert APK_XML.count('android:layout_marginEnd="32dp"') >= 2
    # The blue itself never changed: #277FF0 in the drawable.
    blue = open(os.path.join(
        APK, "app/src/main/res/drawable/btn_main_blue.xml")).read()
    assert "#277FF0" in blue or "#277ff0" in blue


# ------------------------------------------------------------- APK: item 4
def test_apk_delete_disconnect_redder():
    for f, want in (
            ("app/src/main/res/drawable/btn_main_red.xml", "#EF4444"),
            ("app/src/main/res/drawable/btn_danger.xml", "#EF4444"),
            ("app/src/main/res/drawable/ic_delete.xml", "#EF4444")):
        txt = open(os.path.join(APK, f)).read()
        assert want in txt, f
        assert "#F87171" not in re.sub(r"<!--.*?-->", "", txt, flags=re.S), f
    disc = open(os.path.join(
        APK, "app/src/main/res/drawable/btn_disconnect_red.xml")).read()
    assert '#EF4444' in disc and '#E11D48' in disc
    assert "0xFFEF4444" in APK_KT  # delete-icon tint in code
    assert "0xFFF87171" not in APK_KT
    assert "#DC2626" not in APK_KT


# ------------------------------------------------------------- APK: item 9
def test_apk_share_text_keyboard_scroll_and_back():
    assert 'android:windowSoftInputMode="stateHidden|adjustResize"' \
        in APK_MANIFEST
    assert "fun scrollSendToBottom()" in APK_KT
    assert "fullScroll(View.FOCUS_DOWN)" in APK_KT
    assert "snippetInput.setOnFocusChangeListener" in APK_KT
    # Back closes the keyboard first when a text field has focus.
    m = re.search(r"override fun onBackPressed\(\) \{(.*?)\n        if \(onLoginPage\)",
                  APK_KT, re.S)
    assert m, "onBackPressed keyboard-first block missing"
    body = m.group(1)
    assert "currentFocus" in body and "EditText" in body
    assert "hideSoftInputFromWindow" in body
    assert "clearFocus()" in body


# ------------------------------------------------------------ APK: item 10
def test_apk_saved_tap_opens_with_chooser():
    # savedRow tap -> openDownloaded (app chooser), never preview.
    m = re.search(
        r"private fun savedRow\(name: String, size: Long, savedAt: Long\)"
        r"(.*?)setupAiButton\(this, name, false\)", APK_KT, re.S)
    assert m, "savedRow body missing"
    body = m.group(1)
    assert "openDownloaded(name)" in body
    assert "previewFile(name, size, localUriFor(name))" not in body
    # The preview window's button is Open for a local file.
    assert 'pvDl.text = "Open"' in APK_KT
    assert "pvDl.setOnClickListener { close(); openDownloaded(name) }" \
        in APK_KT


# --------------------------------------------------------- APK: item 13
def test_apk_preview_without_download_permission():
    # No early return gating preview on download_files.
    assert "if (localUri == null && !guestCanDownloadFiles())" \
        not in APK_KT
    assert '"?preview=1"' in APK_KT
    assert "pvDl.alpha = 0.45f" in APK_KT
    assert "pvDl.setOnClickListener { toast(MSG_NO_DOWNLOAD) }" in APK_KT


# ------------------------------------------------------------ APK: item 12
def test_apk_logo_before_drop_text():
    drawer = open(os.path.join(
        APK, "app/src/main/res/layout/drawer_panel.xml")).read()
    i_logo = drawer.find("@drawable/app_logo")
    i_drop = drawer.find('android:text="Drop"')
    assert 0 < i_logo < i_drop, (i_logo, i_drop)
    # The bundled artwork is Essef's fixed logo, byte-identical.
    p = os.path.join(APK, "app/src/main/res/drawable/app_logo.png")
    data = open(p, "rb").read()
    assert hashlib.md5(data).hexdigest() == LOGO_MD5
    # Login page logo untouched (already logo-above-Drop there).
    login = open(os.path.join(
        APK, "app/src/main/res/layout/page_login.xml")).read()
    assert '@drawable/app_logo' in login


# ------------------------------------------------- password notice (v2.8.12)
# Essef Nov 4 (follow-up, same build): "PASSWORD SET FOR THIS
# ADDRESS" is shown even when the link is unlocked. Rule: the
# notice appears ONLY when the address is password-protected AND
# locked right now; an unlocked address shows the open-address
# notice only. A removed/cleared password must fully clear the
# stored-password state (registry entry + address_pass/link_pass
# mirrors + encrypted copies), so a password set once in the past
# does not keep the notice showing after it was removed/unlocked.
# (Unlocking alone keeps the stored password for re-lock -- that
# is intended; only the NOTICE must go away while unlocked.)

def test_password_notice_logic_is_locked_and_password():
    # AND, not OR: the old v2.8.7 rule (locked OR password stored)
    # is what kept the notice up after an unlock.
    assert ("const _lkNoticeLocked = !!(st.locked && "
            "st.has_password !== false);") in PAGE
    assert ("const _lkNoticeLocked = !!(st.locked || st.has_password);"
            ) not in PAGE
    # The locked notice text is always the locked wording now --
    # the "Password set for this address" branch for an unlocked
    # address is gone from the notice itself.
    assert '_lt.textContent = "Locked address — password required";' \
        in PAGE
    assert '_lt.textContent = st.locked ? "Locked address' not in PAGE
    # The dialog state line is gated on the same boolean.
    assert '(_lkNoticeLocked ? "Password set for this address." : "")' \
        in PAGE


def test_password_notice_states_live(server):
    client, base, proc, port, home = server
    cfg_path = os.path.join(str(home), ".config", "DropIt",
                            "config.json")

    def cfg():
        with open(cfg_path, encoding="utf-8") as f:
            return json.load(f)

    def authstate():
        s, j = client.j("GET", "/api/authstate")
        assert s == 200, j
        return j

    # 1. No password yet: open, no stored password.
    st = authstate()
    assert st["locked"] is False and st.get("has_password") is False
    # 2. Set a password: locked + password-protected.
    s, j = client.j("POST", "/api/setlink",
                    {"name": "noticetest", "password": "pw123"})
    assert s == 200 and j["ok"], j
    st = authstate()
    assert st["locked"] is True and st["has_password"] is True
    c = cfg()
    assert c["addresses"]["noticetest"]["pass"] != ""
    assert c["address_pass"] != "" and c["link_pass"] != ""
    # 3. UNLOCK (the Essef scenario): gate opens, password stays
    # stored for re-lock -- notice must be OFF (locked is False).
    s, j = client.j("POST", "/api/addresslock", {"locked": False})
    assert s == 200 and j["ok"], j
    st = authstate()
    assert st["locked"] is False, st
    assert st["has_password"] is True, st  # kept for re-lock
    # Re-lock reuses the stored password without retyping.
    s, j = client.j("POST", "/api/addresslock", {"locked": True})
    assert s == 200 and j["ok"], j
    assert authstate()["locked"] is True
    # 4. Remove the password: stored state fully clears everywhere.
    s, j = client.j("POST", "/api/setlinkpassword", {"password": ""})
    assert s == 200 and j["ok"], j
    st = authstate()
    assert st["locked"] is False and st["has_password"] is False, st
    c = cfg()
    ent = c["addresses"]["noticetest"]
    assert ent.get("pass") == "" and ent.get("pass_enc") == ""
    assert c.get("address_pass") == "" and c.get("link_pass") == ""
    assert c.get("address_pass_enc") == "" \
        and c.get("link_pass_enc") == ""
    s, j = client.j("GET", "/api/linkhistory")
    assert s == 200 and j["ok"], j
    ent_j = [e for e in j["entries"] if e.get("key") == "noticetest"]
    assert ent_j and ent_j[0]["has_password"] is False, j
    # 5. The other clear path (setlink with an explicit empty
    # password) also fully clears.
    s, j = client.j("POST", "/api/setlink",
                    {"name": "noticetest", "password": "pw123"})
    assert s == 200 and j["ok"] and authstate()["has_password"] is True
    s, j = client.j("POST", "/api/setlink",
                    {"name": "noticetest", "password": ""})
    assert s == 200 and j["ok"], j
    st = authstate()
    assert st["locked"] is False and st["has_password"] is False, st
    assert cfg()["addresses"]["noticetest"].get("pass") == ""
