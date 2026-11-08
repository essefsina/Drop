"""v2.8.10 / APK 2.6.84 round (Essef Nov 4, 9:14 PM, 3 items).

1. Set Up Your Addresses buttons use the FULL names again --
   "Open Folder" / "Change Folder", as on the Files card and
   menu (2.8.9 one-word rename reverted for the Set Up dialog
   ONLY). Files card buttons stay one-word "Open" / "Change"
   (final clarification: the two surfaces intentionally differ).
   Menu buttons also stay "Open" / "Change".
2. Set Password popup title is ALL CAPS:
   "SET PASSWORD FOR ADDRESS: <address>".
3. Delete buttons unified to the DARKER red #dc2626 -- the dark
   end of the X close icon / dangergrad gradient (was the
   lighter #f87171 solid and #ef4444 gradient end); white
   text/icons. Web + APK drawables.

PAGE checks use the interpreted PAGE (round16-24 pattern).
The old round20/round24 assertions encoding the one-word
Set Up labels ("Open</button>" for #lkopenfolder, "Change"
for #lkchangefolder) and the lighter #f87171 delete fills now
fail BY DESIGN -- see the report, do not "fix" them back.
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


def test_version_is_2_8_10():
    assert D.VERSION == "2.8.10"


def test_setup_buttons_full_names():
    # Static Set Up dialog HTML (ids are unique to Set Up).
    assert 'id="lkopenfolder"' in PAGE
    assert "> Open Folder</button>" in PAGE
    assert "> Change Folder</button>" in PAGE
    # The JS label painter must keep the full name too, so a
    # later paintSeparateFolders() call never shrinks it back.
    assert '_setChangeLabel(lcf, "Change Folder")' in PAGE


def test_files_card_and_menu_stay_one_word():
    # Files tab buttons are JS-built strings (line ~6484):
    # they must still say exactly "Open" / "Change". Match by
    # the button's class + id on its own source line (the file
    # bytes carry \" escapes, so match the plain label text).
    _open_line = next(
        l for l in SRC.splitlines()
        if "btn openf" in l and "openfolder" in l
        and "lkopenfolder" not in l)
    assert "> Open</button>" in _open_line, _open_line
    _change_line = next(
        l for l in SRC.splitlines()
        if "btn changef" in l and "changefolder" in l
        and "lkchangefolder" not in l)
    assert "> Change</button>" in _change_line, _change_line
    # Menu buttons (static HTML) also stay one-word.
    assert re.search(r'id="sbopen".*?>\s*Open</button>', PAGE, re.S)
    assert re.search(r'id="sbchange".*?>\s*Change</button>', PAGE, re.S)
    # And the painters for Files/menu still use "Change".
    assert '_setChangeLabel(cf, "Change")' in PAGE
    assert '_setChangeLabel(scf, "Change")' in PAGE


def test_setup_buttons_fit_rule():
    # Full labels must fit cleanly: 14px + nowrap on the Set Up
    # folder-row buttons (2.8.10 scoped rule).
    assert ".lkbox:not(.guestcard) .lkfolderrow .btn" in PAGE
    assert "white-space:nowrap" in PAGE


def test_set_password_title_all_caps():
    assert (
        "SET PASSWORD FOR ADDRESS: <span id=\"lockpwaddr\"></span>"
        in PAGE
    )
    # The h4 itself must not carry the old mixed-case title.
    m = re.search(r"<h4>(.*?)</h4>", PAGE, re.S)
    assert m and m.group(1).startswith("SET PASSWORD FOR ADDRESS:"), m


def test_delete_buttons_darker_red():
    # All delete-button fills are the darker red #dc2626 now.
    assert ".btn.dangergrad { background:#dc2626" in PAGE
    assert ".fact button.del { background:#dc2626; color:#fff; }" in PAGE
    assert ".delbar .confirmdel { background:#dc2626; color:#fff; }" in PAGE
    assert ".svbar .confirmdel { background:#dc2626; color:#fff; }" in PAGE
    assert "background:#dc2626; color:#ffffff; border:none; }" in PAGE
    # Per-note delete button (gradient vars) is darker red too.
    assert "--c1:#dc2626;--c2:#dc2626" in PAGE
    # X close buttons keep their shared gradient rule (round12
    # pins it): its DARK end #dc2626 is the reference shade the
    # delete buttons now match.
    assert (
        ".lkbox .lkclosebtn, .lockpwbox .lkclosebtn "
        "{ background:linear-gradient(135deg,#f87171,#dc2626); "
        "border:1px solid #dc2626;" in PAGE
    )
    # The light-to-dark gradient survives ONLY where it belongs:
    # the X close buttons (reference shade) and the picked
    # selection checkbox -- never as a delete-button fill.
    assert PAGE.count("linear-gradient(135deg,#f87171,#dc2626)") == 2
    assert "#f87171,#ef4444" not in PAGE


def test_main_page_buttons_aligned_one_line():
    # Alignment audit (Essef Nov 4, 9:19 PM): the 2.8.9 uniform
    # rule (13px / 10px 12px) let "Add New" wrap in its ~95px
    # flex share when the sidebar is open, stretching the Texts
    # row to 53px. Main-page row buttons now share one fit --
    # 12px, 10px 8px, 5px gap, 14px icons, nowrap -- so every
    # row is exactly 40px tall. Rendered harness (headless
    # Chromium, 1280x900, sidebar open) measured: Texts row and
    # Files row all 40px, same top, 12px/700, svg 14x14,
    # icon-centre minus text-centre +0.5px, zero clip; Send Text
    # 40px / 12px / svg 14 / dy 0; menu buttons 31px / 12px /
    # svg 15 / dy 0; Set Up folder buttons 44px / 14px / svg 18
    # / dy 0; eye/delete 44x56 / svg 19; file-row actions
    # 36x36; note-row actions 29px.
    assert (
        ".board .nbtnrow .btn, .board .fbtnrow .btn "
        "{ font-size:12px; padding:10px 8px; gap:5px; "
        "white-space:nowrap; }" in PAGE
    )
    assert (
        ".board .nbtnrow .btn svg, .board .fbtnrow .btn svg "
        "{ width:14px; height:14px; }" in PAGE
    )
    assert ".board #sendsnippet { font-size:12px; }" in PAGE
    assert ".board #sendsnippet svg { width:14px; height:14px; }" in PAGE


def test_served_page_has_new_labels_and_title(server):
    # Live server: the served page carries the Set Up full names
    # and the all-caps Set Password title. (_raw parses JSON and
    # returns {} for HTML, so fetch the page raw here.)
    import http.client

    client, base, proc, port, home = server
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/")
    resp = conn.getresponse()
    body = resp.read().decode()
    conn.close()
    assert resp.status == 200, body[:200]
    assert "Open Folder</button>" in body
    assert "Change Folder</button>" in body
    assert "SET PASSWORD FOR ADDRESS:" in body
    assert "background:#dc2626" in body
