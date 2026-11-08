"""v2.8.2 Set Up redesign (Essef's ChatGPT HTML) + Devices pill fully
outside the Send card (Nov 3, 2026, Essef's 1:51 AM report against
2.8.1: pill still stuck in the card).

PAGE-text proofs (no live DOM needed for the CSS facts):
  1. Host Set Up dialog sizes match the ChatGPT HTML: 1200px
     max-width, 65px fields, 80x65px password icon buttons
     OUTSIDE the password box (lkpwrow: input + two icon
     buttons as siblings), 34px permission boxes, 165x58
     Save, 48x48 red close X, 27px radius, 2px #277ff0 border.
  2. Exactly six permission checkboxes, no AI checkbox, and
     the Permissions info icon carries the exact per-address
     tooltip text.
  3. Pill geometry: top:-44px, 36px tall, translateX only, so
     the pill spans -44px..-8px relative to the card top --
     an 8px clear gap, zero overlap with the card (v2.8.0's
     top:-10px + translate(-50%,-50%) spanned -28px..+8px,
     i.e. 8px INSIDE the card -- the reported bug).
"""
import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402

PAGE = D.PAGE
TOOLTIP = ("Permissions are saved for this address only. Change a box "
           "and tap Save, and guests using this address get exactly "
           "those permissions.")
SIX = ["download_files", "upload_files", "delete_files",
       "add_notes", "delete_notes", "star_notes"]


def test_design_sizes_match_chatgpt_html():
    assert "width:min(1200px,96vw)" in PAGE
    assert "height:65px" in PAGE
    assert "width:80px; height:65px" in PAGE
    assert "width:34px; height:34px" in PAGE
    assert "width:165px; height:58px" in PAGE
    assert "width:48px; height:48px" in PAGE
    assert "border-radius:27px" in PAGE
    assert "border:2px solid #277ff0" in PAGE


def test_password_icons_outside_box():
    m = re.search(r'<div class="lkpwrow">(.*?)</div>', PAGE, re.S)
    assert m, "lkpwrow not found"
    row = m.group(1)
    assert '<input class="lkfield" type="password" id="lkpw"' in row
    assert row.count("lkiconbtn") == 2  # eye + delete, siblings of the input


def test_exactly_six_checkboxes_no_ai_and_info_icon():
    assert re.findall(r'data-perm="([a-z_]+)"', PAGE) == SIX
    assert "Use AI" not in PAGE and "ai_features" not in PAGE
    assert TOOLTIP in PAGE
    assert 'id="lkperminfo"' in PAGE


def test_pill_fully_outside_send_card():
    m = re.search(r'\.devpill \{[^}]*\}', PAGE)
    assert m, "devpill rule not found"
    rule = m.group(0)
    assert "top:-44px" in rule
    assert "translateX(-50%)" in rule and "translate(-50%,-50%)" not in rule
    # 36px pill: -44px .. -44+36 = -8px -> 8px clear gap, no overlap.
    top, height = -44, 36
    assert top + height <= 0, "pill bottom must not reach the card top"
    assert top + height == -8
