"""v2.7.98 placement correction round (Nov 2, 2026) -- Essef
clarified three times in one evening, and this round is the
one that counts.

THE ONLY PLACEMENT THAT COUNTS: Devices Connected goes in
the TOP BAR, TOP LEFT, immediately to the right of the menu
button, on the same top-bar row as the centred Address pill
and the Find button -- exactly as in his screenshot/mockup,
where the pill sits left of the Address pill. Ignore the
white blank rectangle below the Address pill in that
screenshot; that is NOT the target and must not reappear.

WHAT v2.7.98 UNDOES: the v2.7.96/v2.7.97 pill row above the
Send card is removed entirely, and with it the page-growth
workaround (the board/page growing by the pill's height,
the footer sitting ~58px lower). The top-bar row is already
tall enough for the pill, so the pill fits inside the
existing top-bar height with no extra row, no extra vertical
space, and no other element resized or repositioned.

CARD ALIGNMENT (Essef's added clarification for this round):
in his screenshot Send, Shared Texts and Shared Files all
start and end aligned, with NO height extended on any card.
The top-left pill move must preserve that exact alignment:
no card taller, shorter, or shifted because of the pill,
and no board height extension at all.

Covers:
  (a) Pill in the top bar, first element after the menu
      button, on the same row as the Address pill; Address
      pill stays centred, Find stays right, icon-only,
      36x36, same size as the menu icon.
  (b) NO pill row above Send; NO blank row under the top
      bar; Send is a direct board child again.
  (c) Cards stay aligned: Send, Texts and Files are direct
      board children in that order, governed by the single
      shared .col rule (same width, same height calc, no
      per-card desktop size rule), in a stretch-aligned
      flex board -- so they start and end aligned.
  (d) No board/page height extension for the pill: no
      pill-height addition or reduction in the served CSS,
      top-bar height unchanged, footer spacing unchanged.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
from test_link_round2 import server  # noqa: F401,E402
from test_link_round6 import _page  # noqa: E402
from test_link_round12 import _rule, _setlink, _topbar  # noqa: E402
from test_link_round13 import _style_no_comments  # noqa: E402


def _all_rules(html, selector):
    # _rule() returns only the FIRST rule for a selector, but
    # .topbar and .topbar-left each have several rules (base,
    # min-height, media-query margin). Join them all so a
    # property living in a later rule is still found.
    return " ".join(re.findall(re.escape(selector) + r" \{([^}]*)\}", html))


# ------------------------------------------------------------------ (a)
def test_pill_top_left_beside_menu_same_row_as_address(server):
    client, base, proc, port, home = server
    assert D.VERSION == "2.7.98"
    _setlink(client, "homebase")
    html = _page(port, client)
    top = _topbar(html)
    # Order inside the top bar: menu, then pill, then the
    # centred Address pill, then Find -- the pill is the
    # FIRST element after the menu button.
    assert top.index('id="menubtn"') < top.index('id="statusdiv"')
    assert top.index('id="statusdiv"') < top.index('id="toplink"')
    assert top.index('id="toplink"') < top.index('id="askbtn"')
    # The pill and the menu share one left cluster, and the
    # top bar itself is one flex row (not a wrapped stack).
    assert 'class="topbar-left"' in top
    assert 'class="topstatus"' in top
    assert "display:flex" in _all_rules(html, ".topbar")
    assert "display:flex" in _all_rules(html, ".topbar-left")
    # Address pill stays centred on the single-row top bar.
    assert "top:50%" in _rule(html, ".connectwrap")
    # Find stays right, icon-only, 36x36 = menu icon size.
    ask = _rule(html, "#askbtn")
    assert "width:36px" in ask and "height:36px" in ask
    assert "width:16px" in _rule(html, "#askbtn .findglass")
    assert 'class="findspark"' in html
    # Pill fits the EXISTING top-bar row: 48px pill inside a
    # 52px-min-height top bar (44px at narrower widths).
    assert "min-height:52px" in _all_rules(html, ".topbar")
    pill = _rule(html, ".topstatus .status")
    assert "height:48px" in pill
    assert "width:auto" in pill
    assert "border-radius:999px" in pill
    assert "background:#12172a" in pill
    assert "border:1px solid #2a3560" in pill
    light = _rule(html, "html.light .topstatus .status")
    assert "background:#ffffff" in light
    assert "border-color:#c3cfde" in light


# ------------------------------------------------------------------ (b)
def test_no_pill_row_above_send_no_blank_row_under_topbar(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    # Every previous pill-row shape is gone, not just moved.
    assert 'class="statusrow"' not in html
    assert 'class="statusbar"' not in html
    assert 'class="sendwrap"' not in html
    assert 'class="sendstatus"' not in html
    # The pill is nowhere in the board, and there is no row
    # element between the top bar and the board except the
    # hidden QR popup and the hidden guest-login page.
    board = html[html.index('<div class="board">'):]
    assert 'id="statusdiv"' not in board
    between = html[html.index('</div>', html.index('<div class="topbar">')):
                   html.index('<div class="board">')]
    assert 'class="statusrow"' not in between
    assert 'class="sendwrap"' not in between
    assert 'class="sendstatus"' not in between
    # The board's first card is Send, directly: nothing
    # between the board open and the Send card's own tag.
    assert board.index('data-col="send"') < board.index('data-col="notes"')
    board_head = board[:board.index('<div class="col" data-col="send"')]
    assert board_head.count('<div') == 1  # only the board div itself


# ------------------------------------------------------------- (c) + (d)
def test_three_cards_aligned_no_height_extension(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    css = _style_no_comments(html)
    board = html[html.index('<div class="board">'):]
    # (c) Alignment: Send, Texts, Files are direct board
    # children in that order, and the board stretches them
    # to the same row height (align-items:stretch).
    assert board.index('data-col="send"') \
        < board.index('data-col="notes"') \
        < board.index('data-col="files"')
    board_rule = _rule(html, ".board")
    assert "display:flex" in board_rule
    assert "align-items:stretch" in board_rule
    # One shared .col rule governs all three cards: same
    # width, same height calc, same min-height -- so they
    # start and end aligned. No per-card desktop size rule
    # makes any one card taller, shorter, or shifted.
    col = re.search(r"\n  \.col \{([^}]*)\}", html)
    assert col, "standalone .col rule missing"
    assert "width:340px" in col.group(1)
    assert "height:calc(100vh - 210px)" in col.group(1)
    assert "height:calc(100dvh - 210px)" in col.group(1)
    assert "min-height:240px" in col.group(1)
    assert '.col[data-col="send"] {' not in css
    assert '.col[data-col="notes"] {' not in css
    assert '.col[data-col="files"] {' not in css
    # Board segment balance: the Send card closes inside
    # the board (board still open at the Notes card), so no
    # orphan closing tag from the removed wrapper shifts
    # the later cards out of the board.
    # (Segment stops BEFORE the Notes card's opening tag, so
    # the only unmatched open at that point is the board.)
    seg = html[html.index('<div class="board">'):
               html.index('<div class="col" data-col="notes"')]
    opens = len(re.findall(r"<div\b", seg))
    closes = len(re.findall(r"</div>", seg))
    assert opens == closes + 1, (opens, closes)
    # (d) No height extension for the pill anywhere in the
    # served CSS: neither the v2.7.96 shrink nor the
    # v2.7.97 growth survives, and the top bar and footer
    # keep their pre-pill spacing.
    assert "- 58px" not in css
    assert "-58px" not in css
    assert "+58px" not in css
    assert "margin-bottom:10px" in _rule(html, ".topbar")
    assert "margin-top:26px" in _rule(html, "footer")
    # Mobile: Send shares exactly the other tabs' height.
    m_tabs = re.search(
        r"body\[data-mtab=\"send\"\] \.board \.col,\s*"
        r"body\[data-mtab=\"notes\"\] \.board \.col,\s*"
        r"body\[data-mtab=\"files\"\] \.board \.col,\s*"
        r"body\[data-mtab=\"ask\"\] \.board \.col \{([^}]*)\}",
        html)
    assert m_tabs, "mobile generic tab rule missing"
    assert "height:calc(100dvh - 205px)" in m_tabs.group(1)
    assert ".board .sendwrap" not in css
