"""v2.8.3 Set Up remake: ChatGPT HTML faithfully, per Essef's annotated
2.8.2 proof (Nov 3, 2:13 AM PT). Checks the INTERPRETED PAGE, not raw source."""
import ast
import re

SRC = open(__file__.replace("tests/test_link_round18.py", "dropit.py")).read()
PAGE = None
for _n in ast.walk(ast.parse(SRC)):
    if isinstance(_n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "PAGE" for t in _n.targets
    ):
        PAGE = _n.value.value
        break
assert PAGE is not None


def test_version_283():
    assert 'VERSION = "2.8.3"' in SRC


def test_password_ends_at_new_address_width():
    # Left-column width: topline grids use a 30px gap, so the password
    # input's flex-basis must be (100% - 30px)/2, NOT flex:1 full width.
    assert re.search(
        r"\.lkpwrow input\.lkfield \{[^}]*flex:0 0 calc\(\(100% - 30px\) / 2\)",
        PAGE,
    ), "password input must be left-column width, not full width"


def test_chatgpt_icons_present():
    assert "🔓 Open address" in PAGE
    assert "📁 Open Folder" in PAGE
    assert "⇄ Change Folder" in PAGE
    assert "💾 Save" in PAGE
    # Folder icon inside the Folder For This Address view.
    assert re.search(r'id="lkfolderview">📁', PAGE)


def test_chatgpt_font_and_sizes():
    assert '"Segoe UI", Arial, sans-serif' in PAGE
    assert "width:min(1200px,96vw)" in PAGE
    assert ".lkpwrow .lkiconbtn { width:80px; height:65px" in PAGE
    assert ".lkbox:not(.guestcard) .lkfield" in PAGE and "height:65px" in PAGE
    assert "width:165px; height:58px" in PAGE
    assert "width:48px; height:48px" in PAGE
    assert "width:34px; height:34px" in PAGE


def test_open_address_notice_text():
    assert "Open address" in PAGE and "anyone on your Wi-Fi can use it" in PAGE
    # Notice is shown for open (unlocked) addresses.
    assert 'warn.classList.toggle("show", !st.locked)' in PAGE


def test_six_checkboxes_no_ai_and_pill_outside():
    perms = re.findall(r'data-perm="([a-z_]+)"', PAGE)
    assert perms == [
        "download_files",
        "upload_files",
        "delete_files",
        "add_notes",
        "delete_notes",
        "star_notes",
    ]
    assert "Use AI Features" not in PAGE
    assert "Add / Edit Notes" in PAGE
    assert 'id="lkperminfo"' in PAGE
    assert "top:-44px" in PAGE  # pill fully outside Send card, no straddle
    assert "translate(-50%,-50%)" not in PAGE.split(".devpill")[1].split("}")[0]


def test_no_lone_surrogates():
    assert not [c for c in PAGE if 0xD800 <= ord(c) <= 0xDFFF]
    PAGE.encode("utf-8")
