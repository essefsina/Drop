"""v2.8.5 main-page button language (reference: Shared Texts / Shared Files
card buttons, Essef Nov 3, 2:37 AM PT) + Set Up follow-ups (Nov 3, 2:39 and
2:40 AM PT). Checks the INTERPRETED PAGE, not raw source."""

import ast
import re

SRC = open(__file__.replace("tests/test_link_round20.py", "dropit.py")).read()
PAGE = None
for _n in ast.walk(ast.parse(SRC)):
    if isinstance(_n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "PAGE" for t in _n.targets
    ):
        PAGE = _n.value.value
        break
assert PAGE is not None


def test_version_285():
    assert 'VERSION = "2.8.5"' in SRC


def test_main_button_fills_and_radius():
    # Teal primary/add/open, gold starred, red delete, purple change/edit.
    assert ".board #sendsnippet, .board #maddnote," in PAGE
    assert "background:#2dd4bf; color:#052e33;" in PAGE
    assert ".board #starfilter { background:#fbbf24; color:#231303;" in PAGE
    assert ".board #delallnotesbtn, .board #delallbtn" in PAGE
    assert "background:#f87171; color:#ffffff;" in PAGE
    assert ".board .fbtnrow #changefolder { background:#a78bfa; color:#ffffff;" in PAGE
    assert "border-radius:18px;" in PAGE


def test_main_buttons_have_icons_before_text():
    assert re.search(r'id="sendsnippet"><svg[^>]*>.*?</svg>Send Text', PAGE)
    assert re.search(r'id="maddnote"[^>]*><svg[^>]*>.*?</svg> Add New', PAGE)
    assert re.search(r'id="msendfiles"><svg[^>]*fill="#052e33"', PAGE)
    assert "Open Folder</button>" in SRC  # server Files row, icon added
    assert "Change Folder</button>" in SRC


def test_setup_dialog_buttons_unchanged():
    # The 2.8.4 dark-outline Set Up folder buttons must survive this round.
    assert re.search(
        r"\.lkbox:not\(\.guestcard\) \.btn\.openf \{ background:#092a48; border:2px solid #00c9f5; color:#65e4ff;",
        PAGE,
    )
    assert re.search(
        r"\.lkbox:not\(\.guestcard\) \.btn\.changef \{ background:#261448; border:2px solid #b638f5; color:#ffffff;",
        PAGE,
    )


def test_password_eye_shifted_right():
    # Eye left edge aligned with the Set Up Open Folder button's left edge:
    # a 20px left offset on the eye button (measured: eye x == Open Folder x).
    assert ".lkbox:not(.guestcard) .lkpwrow #lkpweye { margin-left:20px; }" in PAGE
    # Same size, still immediately right of (outside) the password box.
    assert ".lkbox:not(.guestcard) .lkpwrow .lkiconbtn { width:80px; height:65px;" in PAGE


def test_save_icon_is_outline_svg_not_floppy_emoji():
    assert "💾 Save" not in PAGE
    assert re.search(
        r'id="lkset"[^>]*><svg width="20" height="20"[^>]*><path d="M19 21H5a2',
        PAGE,
    )
    assert ".lkbox #lkset svg { width:20px; height:20px; flex:none; }" in PAGE


def test_files_row_buttons_fit_their_card():
    # 3-column card: Files buttons use a smaller font so labels are not
    # clipped (scrollWidth == clientWidth in the proof render).
    assert ".board .fbtnrow .btn { padding:16px 2px; font-size:11px; gap:3px; }" in PAGE
