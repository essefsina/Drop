"""v2.8.15 guest-modal Set Up removal + "Saved on this phone" (Essef Nov 5).

Essef's rule behind the giant-button screenshot: the mobile browser
and the APK must NOT show "Set Up Your Addresses" at all. The guest
"Connect To A PC" modal shows only address + password + Connect.
The host Set Up dialog on desktop/web stays exactly as it is.

Web (dropit.py):
- .lkbox.guestcard hard-hides h3, .lksplit, .lkfolderrow, .lkperms,
  .lkpermlabel, .lkdivider, .lksepinline, #lkremovepwbtn with
  !important, so no JS path or auth-state quirk can ever leak the
  host sections onto a guest screen again (the real-phone screenshot
  showed them even though openLinkWin hides them for guests).
- openLinkWin also hides #lksplit / #lkperms / #lkpermlabel for
  guests in JS, and the guest action button now reads "Connect".
- The drawer hides its host Set Up cards (#sbsetupcard,
  #sbsepcard, #sbfoldercard) for guests in paintSidebar.
- "Saved on this phone" button on the guest login page opens a
  saved-files view listing this browser's Drop downloads
  (localStorage dropit_dl ledger + IndexedDB blob cache), each
  with an Open action that opens the saved copy offline, and a
  Back button to the login. The menu still never appears on the
  login page.

APK (dialog_link.xml + MainActivity.kt) is covered by the render
probe and the build; its assertions live in the probe script.
"""
import ast
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402

PAGE = D.PAGE


def test_version_is_2_8_15():
    assert D.VERSION == "2.8.15"


def test_guestcard_hard_hides_setup_sections():
    # The !important block must cover every host Set Up element.
    m = re.search(
        r"\.lkbox\.guestcard h3,\s*\.lkbox\.guestcard \.lksplit,\s*\.lkbox\.guestcard \.lkfolderrow,\s*\.lkbox\.guestcard \.lkperms,\s*\.lkbox\.guestcard \.lkpermlabel,\s*\.lkbox\.guestcard \.lkdivider,\s*\.lkbox\.guestcard \.lksepinline,\s*\.lkbox\.guestcard #lkremovepwbtn \{ display:none !important; \}",
        PAGE,
    )
    assert m, "guestcard !important hard-hide block missing or incomplete"


def test_guestcard_hard_hide_is_scoped_to_guestcard():
    # The hard-hide must not touch the host dialog: every selector
    # in that block starts with .lkbox.guestcard.
    block = re.search(
        r"(\.lkbox\.guestcard [^{]+\{ display:none !important; \})", PAGE
    )
    assert block
    assert ".lkbox:not(.guestcard)" not in block.group(1)


def test_openlinkwin_hides_setup_sections_for_guests():
    assert 'show("#lksplit", host);' in PAGE
    assert 'show("#lkperms", host);' in PAGE
    assert 'show("#lkpermlabel", host);' in PAGE
    assert 'show("#lkfolderrow", host);' in PAGE


def test_guest_action_button_reads_connect():
    assert '_setBtn.lastChild.textContent = host ? " Save" : " Connect";' in PAGE


def test_lksplit_and_permlabel_have_ids():
    assert '<div class="lksplit" id="lksplit">' in PAGE
    assert '<div class="lkpermlabel" id="lkpermlabel">' in PAGE


def test_drawer_setup_cards_hidden_for_guests():
    assert 'id="sbsetupcard"' in PAGE
    assert 'id="sbsepcard"' in PAGE
    assert 'id="sbfoldercard"' in PAGE
    assert '"#sbsetupcard", "#sbsepcard", "#sbfoldercard"' in PAGE


def test_host_setup_sections_still_present():
    # The host dialog itself is untouched: all six permission
    # checkboxes, the folder buttons and the Save button remain.
    for perm in ("download_files", "upload_files", "delete_files",
                 "add_notes", "delete_notes", "star_notes"):
        assert f'data-perm="{perm}"' in PAGE
    assert 'id="lkopenfolder"' in PAGE
    assert 'id="lkchangefolder"' in PAGE
    assert 'id="lkset"' in PAGE


def test_login_page_has_saved_on_this_phone_button():
    assert 'id="gsavedbtn"' in PAGE
    assert "Saved on this phone" in PAGE
    # The button lives inside the login form, on the login page
    # itself -- not in a menu.
    assert PAGE.index('id="gsavedbtn"') > PAGE.index('id="gloginform"')
    assert PAGE.index('id="gsavedbtn"') < PAGE.index('id="gsavedview"')


def test_saved_view_markup_present():
    assert 'id="gsavedview"' in PAGE
    assert 'id="gsavedlist"' in PAGE
    assert 'id="gsavedempty"' in PAGE
    assert 'id="gsavedback"' in PAGE
    assert "Back" in PAGE


def test_saved_view_reads_local_download_ledger():
    assert "dropit_dl" in PAGE
    assert "function getSavedFiles()" in PAGE
    assert "function paintSavedFiles()" in PAGE
    assert "function openSavedFile(name)" in PAGE
    assert "function showSavedView()" in PAGE
    assert "function showLoginForm()" in PAGE


def test_saved_open_uses_offline_blob_cache():
    # Open goes through the IndexedDB blob cache, not a fetch, so
    # it works with no PC connection.
    assert "DBCACHE.get(name)" in PAGE
    assert "await openBlob(f)" in PAGE


def test_login_bounce_resets_to_login_form():
    assert 'if(typeof showLoginForm === "function") showLoginForm();' in PAGE


def test_page_parses_and_has_no_lone_surrogates():
    tree = ast.parse(open(os.path.join(os.path.dirname(__file__), "..", "dropit.py")).read())
    page = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "PAGE":
            page = node.value.value
    assert page is not None
    assert not [c for c in page if 0xD800 <= ord(c) <= 0xDFFF]
    page.encode("utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
    assert len(scripts) == 2


def test_apk_dialog_has_no_setup_section():
    base = os.path.join(os.path.dirname(__file__), "..", "..", "dropit-android")
    xml = open(os.path.join(base, "app", "src", "main", "res", "layout", "dialog_link.xml")).read()
    markup = re.sub(r"<!--.*?-->", "", xml, flags=re.S)
    assert "Connect To A PC" in markup
    assert "Set Up Your Addresses" not in markup
    assert "Folder For This Address" not in markup
    assert "lkFolder" not in markup
    assert "Address To Connect To" in xml
    assert 'android:text="Connect"' in xml
    kt = open(os.path.join(base, "app", "src", "main", "java", "com", "dropit", "app", "MainActivity.kt")).read()
    assert 'view.findViewById<TextView>(R.id.lkTitle)?.text = "Connect To A PC"' in kt
    assert "R.id.lkFolder" not in kt
    assert "folderTxt" not in kt
