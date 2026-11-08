"""v2.8.16 login-page fixes (Essef Nov 5, login screenshot).

1. "Saved on this phone" button is 60% wide, centred (his red
   lines) -- the same width as the Connect button, not full-width.
2. The chevron/arrow at the right end of the Address field sits a
   bit higher up (3px above the field's vertical centre).
3. Login Connect button is slightly up (margin pulled in 4px) and
   its text is WHITE (the .btn.primary dark ink was showing on
   the blue).
4. The saved-files view has a THUMBNAIL per row (image/video
   frame from the on-phone blob, file-type icon otherwise) and a
   Preview button; preview covers ALL types in the viewer --
   image / video / audio / text / PDF (in-app iframe, not a new
   tab) / .docx (server HTML, offline text extraction fallback)
   / .doc (client-side text extraction) / any other type (a
   preview card with name, size and an Open button, never blank).
5. The "Your recent addresses are saved only on this device --
   never sent to the PC." note is REMOVED from the web login page.
6. Connect To A PC window: the label is "Address To Connect"
   (the word "to" removed, label + placeholder, web and APK),
   with extra space below the label (14px web, 10dp APK field
   margin).
"""
import ast
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402

PAGE = D.PAGE


def test_version_is_2_8_16():
    assert D.VERSION == "2.8.16"


def test_saved_button_is_60_percent_centred():
    m = re.search(r"\.gloginbox #gsavedbtn \{([^}]*)\}", PAGE)
    assert m, "#gsavedbtn rule missing"
    rule = m.group(1)
    assert "width:60%" in rule
    assert "margin:14px auto 0" in rule
    assert "display:block" in rule


def test_connect_button_white_text_and_moved_up():
    m = re.search(r"\.gloginbox #gloginbtn \{([^}]*)\}", PAGE)
    assert m, "#gloginbtn rule missing"
    rule = m.group(1)
    assert "width:60%" in rule
    assert "color:#ffffff" in rule
    assert "margin:-4px auto 0" in rule


def test_address_chevron_moved_higher():
    # 50% - 8px, not -3px: the wrapper is 10px taller than the
    # input (the input's bottom margin), so 50% of the wrapper
    # is 5px below the input's centre; -8px lands the chevron
    # 3px above the field's centre (probe-measured -3.0px).
    assert "#gddwrap .ddchevbtn { top:calc(50% - 8px); }" in PAGE


def test_recent_addresses_note_removed_from_web_login():
    assert "Your recent addresses are saved only on this device" not in PAGE
    # The dynamic message slot stays (showGuestLogin writes into it).
    assert 'id="gloginmsg"' in PAGE


def test_saved_rows_have_thumbnail_and_preview_button():
    assert "data-thumb=" in PAGE
    assert "data-preview-saved=" in PAGE
    assert "function previewSavedFile(name)" in PAGE
    assert ".gsavedrow .gsthumb" in PAGE
    assert ".gsavedrow .gsthumbwrap" in PAGE
    assert ".gsavedrow .btn.gspreview" in PAGE
    # Thumbnails fill from the on-phone blob cache (image frame /
    # video frame); a missing blob keeps the file-type icon.
    assert "MEMBLOBS[f.name] || await DBCACHE.get(f.name)" in PAGE
    assert "preload=\"metadata\" muted playsinline" in PAGE


def test_saved_preview_covers_all_types():
    # PDF previews inside the viewer, not a new tab.
    assert "showViewer(n, `<iframe src=\"${url}\"></iframe>`, url);" in PAGE
    assert 'window.open(url, "_blank")' not in PAGE
    # .docx: offline text extraction fallback when the PC fetch fails.
    assert "function docxTextFromBlob(blob)" in PAGE
    assert "word/document.xml" in PAGE
    assert "const _off = await docxTextFromBlob(blob);" in PAGE
    # .doc: client-side text extraction from the saved blob.
    assert "function docTextFromBlob(blob)" in PAGE
    assert "await docTextFromBlob(blob)" in PAGE
    # Any other type: a preview card with an Open button, never blank.
    assert 'id="votheropen"' in PAGE
    assert "No in-app preview for this file type" in PAGE


def test_connect_to_pc_label_is_address_to_connect():
    assert '"Address To Connect"' in PAGE
    assert '"Address To Connect To"' not in PAGE
    # Extra space below the label in the guest modal.
    assert ".lkbox.guestcard #lklinklabel { margin-bottom:14px; }" in PAGE


def test_apk_connect_label_and_spacing():
    base = os.path.join(os.path.dirname(__file__), "..", "..", "dropit-android")
    xml = open(os.path.join(base, "app", "src", "main", "res", "layout", "dialog_link.xml")).read()
    markup = re.sub(r"<!--.*?-->", "", xml, flags=re.S)
    assert "Address To Connect" in markup
    assert "Address To Connect To" not in markup
    # The field sits 10dp below the label (was 4dp).
    m = re.search(r'android:id="@\+id/lkName".*?android:layout_marginTop="(\d+)dp"',
                  xml, re.S)
    assert m and m.group(1) == "10", m
    assert "2.6.90" in open(os.path.join(base, "app", "build.gradle")).read()
    assert "2.6.90" in open(os.path.join(base, "app", "src", "main", "AndroidManifest.xml")).read()


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
