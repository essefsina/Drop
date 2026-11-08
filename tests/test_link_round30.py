"""v2.8.15 guestcard folder-button hotfix (Essef Nov 5, 1:45 AM).

The Open/Change Folder buttons in the mobile web "Connect To A PC"
(guestcard) modal rendered as GIANT squares with enormous folder
icons, overlapping the New Address field, "Change" cut off.
Root cause: every .lkfolderrow .btn svg size rule was scoped
:not(.guestcard) (host dialog only), so in the guest card the SVGs
had NO size at all and rendered at their huge default size -- the
same class of bug as the 2.8.8 mobile Choose-files folder icon.
Fix: pin the icons unscoped (18px, width/height attributes + CSS),
pin the guest buttons to 44px with overflow hidden, stack the guest
top line under 480px, and pin the guest password eye to 20px in its
normal text colour (the guest remove-password button is hidden).
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


def test_folder_svg_attrs_pinned_18():
    # Both folder SVGs in the Set Up dialog carry explicit 18x18 attrs.
    assert PAGE.count('id="lkopenfolder"') == 1
    assert PAGE.count('id="lkchangefolder"') == 1
    m = re.search(r'id="lkopenfolder".*?<svg[^>]*>', PAGE, re.S)
    assert m and 'width="18"' in m.group(0) and 'height="18"' in m.group(0)
    m = re.search(r'id="lkchangefolder".*?<svg[^>]*>', PAGE, re.S)
    assert m and 'width="18"' in m.group(0) and 'height="18"' in m.group(0)


def test_folder_svg_css_pinned_unscoped():
    # Unscoped rule: covers the guest card too (host rules are
    # :not(.guestcard)-scoped and still win for the host).
    assert re.search(
        r"\.lkbox\s+\.lkfolderrow\s+\.btn\s+svg\s*\{[^}]*width:18px;[^}]*height:18px;",
        PAGE)


def test_guestcard_folder_buttons_pinned_44():
    assert re.search(
        r"\.lkbox\.guestcard\s+\.lkfolderrow\s+\.btn\s*\{[^}]*height:44px;[^}]*min-height:44px;",
        PAGE)
    assert re.search(
        r"\.lkbox\.guestcard\s+\.lkfolderrow\s+\.btn\s*\{[^}]*overflow:hidden;",
        PAGE)


def test_guestcard_topline_stacks_under_480():
    assert re.search(
        r"@media\s*\(max-width:480px\)\s*\{.*?\.lkbox\.guestcard\s+\.lktopline\s*\{[^}]*flex-direction:column;",
        PAGE, re.S)


def test_guestcard_eye_pinned_20_normal_colour():
    assert re.search(
        r"\.lkbox\.guestcard\s+\.lkpwrow\s+#lkpweye\s+svg\s*\{[^}]*width:20px;[^}]*height:20px;",
        PAGE)
    assert re.search(
        r"\.lkbox\.guestcard\s+\.lkpwrow\s+#lkpweye\s*\{[^}]*color:var\(--txt\);",
        PAGE)


def test_guestcard_remove_pw_button_hidden():
    assert re.search(
        r"\.lkbox\.guestcard\s+\.lkpwrow\s+#lkremovepwbtn\s*\{[^}]*display:none;",
        PAGE)


def test_host_folder_svg_still_pinned():
    # Host dialog keeps its own (later, higher-specificity) 18px rule.
    assert ".lkbox:not(.guestcard) .lkfolderrow .btn svg { width:18px; height:18px; }" in PAGE


def test_no_unpinned_folder_svg_in_lkbox():
    # Every <svg> inside the lkfolderrow buttons now carries width/height.
    row = re.search(r'id="lkfolderrow".*?</div>\s*</div>', PAGE, re.S)
    assert row
    svgs = re.findall(r"<svg[^>]*>", row.group(0))
    assert len(svgs) == 2
    for svg in svgs:
        assert 'width="18"' in svg and 'height="18"' in svg


def test_page_still_valid():
    src = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py")).read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "PAGE":
            page = node.value.value
            break
    assert not [c for c in page if 0xD800 <= ord(c) <= 0xDFFF]
    page.encode("utf-8")
