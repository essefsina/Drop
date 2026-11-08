"""v2.7.98 placement correction round (supersedes the v2.7.97 above-Send placement) (Nov 2, 2026) -- parent brief items
from Essef's feedback on v2.7.96.

1. Devices Connected pill placement -- STILL the standing rule
   (Nov 2, 9:33 AM, confirmed): the pill sits ABOVE the Send
   card, CENTRED over the Send card -- NOT in the top bar, NOT
   over the Texts card, NOT in a row under the top bar. v2.7.96
   placed it above Send but ALSO shrank the Send card by the
   pill height (the "- 58px" height reduction), and Essef
   rejected that ("the send card not shriked or anything else
   resized"). v2.7.97 REMOVES the reduction: the pill lives in
   its own row directly above Send, Send keeps its EXACT
   pre-pill dimensions, and the board grows / page scrolls
   instead of compressing anything.

2. Toasts behind Set Up Your Addresses -- NEW item. The global
   toast was z-index:120, BELOW the Set Up dialog backdrop
   (.lockwrap, 300) and BELOW the Set Password popup
   (.lockpwpop, 130), so toasts fired from inside those dialogs
   rendered behind them and could not be seen. v2.7.97 raises
   the toast to 5000: above both dialogs and their backdrops,
   above the Set Password popup, and above every other overlay
   except the transient context menu (9999, pointer-driven).

Covers:
  (a) Devices pill directly above Send, centred on Send's width,
      no pill in the top bar (menu left, Address pill centred,
      Find right, Find icon = menu icon size).
  (b) Send card dimensions/content byte-identical to the
      pre-pill version: no height/width change on Send, no
      other card resized, no "- 58px" reduction anywhere in
      the served CSS (desktop or mobile).
  (c) A toast is above the Set Up dialog in stacking order
      (and above the Set Password popup, QR popup, AI modal
      and tooltip); the mobile toast rule sets no z-index of
      its own, so the one desktop rule covers mobile too.
      All toast/message containers were audited: #toast is
      the ONLY global toast container; .lkerr / .lockerr /
      .lockpwerr are inline errors INSIDE their dialogs and
      .gloginmsg / .gloginerr are inline on the guest login
      page, so none of them can render behind a dialog.
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


def _style(html):
    m = re.search(r"<style>(.*?)</style>", html, re.S)
    assert m, "no <style> block in served page"
    return m.group(1)


def _style_no_comments(html):
    return re.sub(r"/\*.*?\*/", "", _style(html), flags=re.S)


def _zindex(html, selector):
    # .toast has TWO rules (mobile bottom-offset first, desktop
    # stacking second): take the one that actually sets z-index.
    rules = re.findall(re.escape(selector) + r" \{([^}]*)\}", html)
    assert rules, f"no CSS rule for {selector}"
    for rule in rules:
        m = re.search(r"z-index:(\d+)", rule)
        if m:
            return int(m.group(1))
    raise AssertionError(f"no z-index in any {selector} rule: {rules!r}")


# ------------------------------------------------------------------ (a)
def test_devices_pill_top_left_in_topbar(server):
    # v2.7.98 SUPERSEDES (a): the pill is in the TOP BAR,
    # TOP LEFT, immediately right of the menu button, on the
    # same row as the centred Address pill and Find -- not
    # above Send, not over Texts, not in a row under the
    # top bar, and with no blank white rectangle anywhere.
    client, base, proc, port, home = server
    assert D.VERSION == "2.7.98"
    _setlink(client, "homebase")
    html = _page(port, client)
    top = _topbar(html)
    assert 'id="menubtn"' in top
    assert 'id="toplink"' in top
    assert 'id="askbtn"' in top
    assert top.index('id="menubtn"') < top.index('id="statusdiv"') < top.index('id="toplink"')
    assert "top:50%" in _rule(html, ".connectwrap")
    # Find icon = menu icon size, icon-only with AI sparkle.
    ask = _rule(html, "#askbtn")
    assert "width:36px" in ask and "height:36px" in ask
    assert "width:16px" in _rule(html, "#askbtn .findglass")
    assert 'class="findspark"' in html
    # No pill row anywhere near the board: no wrapper, no
    # status row, no statusdiv inside the board at all.
    assert 'class="sendwrap"' not in html
    assert 'class="sendstatus"' not in html
    assert 'class="statusrow"' not in html
    board = html[html.index('<div class="board">'):]
    assert 'id="statusdiv"' not in board
    # Top bar row height is unchanged: the pill fits the
    # existing 52px top-bar row at 48px (44px narrow).
    # (.topbar has several rules; the min-height lives in
    # a later one, so search all of them, not the first.)
    topbar_rules = " ".join(re.findall(
        r"\.topbar \{([^}]*)\}", html))
    assert "min-height:52px" in topbar_rules
    pill_rule = _rule(html, ".topstatus .status")
    assert "height:48px" in pill_rule
    assert "width:auto" in pill_rule
    # The board's first card is Send, directly -- nothing
    # between the board open and the Send card but the card.
    assert board.index('data-col="send"') < board.index('data-col="notes"')


# ------------------------------------------------------------------ (b)
def test_cards_unresized_unmoved_no_page_growth(server):
    # v2.7.98 SUPERSEDES (b): with the pill in the top bar,
    # there is no pill row to absorb at all -- no page
    # growth, no footer drop, no card shrink or shift.
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    css = _style_no_comments(html)
    # No pill-height reduction or addition anywhere: the
    # v2.7.96 "- 58px" shrink and the v2.7.97 "+58px" growth
    # are both gone from the served CSS.
    assert "- 58px" not in css
    assert "-58px" not in css
    assert "+58px" not in css
    # (The unrelated #lockwrap inset:58px for the Set Up
    # dialog backdrop is not a pill-height rule and stays.)
    # Standalone .col rule = the pre-pill card dimensions,
    # unchanged: 340px wide, calc(100vh - 210px) tall, and
    # it is the ONLY desktop card-size rule -- Send, Texts
    # and Files all share it, so they start and end aligned.
    col = re.search(r"\n  \.col \{([^}]*)\}", html)
    assert col, "standalone .col rule missing"
    assert "width:340px" in col.group(1)
    assert "height:calc(100vh - 210px)" in col.group(1)
    assert "height:calc(100dvh - 210px)" in col.group(1)
    assert "min-height:240px" in col.group(1)
    assert ".col[data-col=\"notes\"] {" not in css
    assert ".col[data-col=\"files\"] {" not in css
    assert ".col[data-col=\"send\"] {" not in css
    # Mobile: the Send-tab card height is EXACTLY the other
    # tabs' height (calc(100dvh - 205px)), not a reduced one,
    # and there is no wrapper rule left to hide/show it.
    assert ".board .sendwrap" not in css
    m_tabs = re.search(
        r"body\[data-mtab=\"send\"\] \.board \.col,\s*"
        r"body\[data-mtab=\"notes\"\] \.board \.col,\s*"
        r"body\[data-mtab=\"files\"\] \.board \.col,\s*"
        r"body\[data-mtab=\"ask\"\] \.board \.col \{([^}]*)\}",
        html)
    assert m_tabs, "mobile generic tab rule missing"
    assert "height:calc(100dvh - 205px)" in m_tabs.group(1)
    # Board order and content intact: Send, then Texts, then
    # Files, each a direct board child in that order.
    board = html[html.index('<div class="board">'):]
    assert board.index('data-col="send"') < board.index('data-col="notes"') < board.index('data-col="files"')
    send_seg = html[html.index('data-col="send"'):
                    html.index('data-col="notes"')]
    for marker in ("Send Files", "Drop Your Files Here", "Send Text",
                   'id="snippet"', 'id="sendsnippet"', 'id="drop"'):
        assert marker in send_seg, marker
    # Footer spacing unchanged (no ~58px drop): the footer
    # rule keeps its pre-pill margin.
    assert "margin-top:26px" in _rule(html, "footer")


# ------------------------------------------------------------------ (c)
def test_toast_above_setup_dialog_and_set_password_popup(server):
    client, base, proc, port, home = server
    _setlink(client, "homebase")
    html = _page(port, client)
    toast_z = _zindex(html, ".toast")
    setup_z = _zindex(html, ".lockwrap")
    pwpop_z = _zindex(html, ".lockpwpop")
    # The bug: toast was 120, below .lockwrap (300) and below
    # .lockpwpop (130). Now it must beat both, and their
    # backdrops (the wrappers ARE the backdrops: fixed inset-0).
    assert toast_z > setup_z, (toast_z, setup_z)
    assert toast_z > pwpop_z, (toast_z, pwpop_z)
    assert setup_z == 300 and pwpop_z == 130
    # Above every other overlay a toast could hide behind.
    assert toast_z > _zindex(html, ".qrpop")       # 300
    assert toast_z > _zindex(html, ".aimodalwrap")  # 1001
    assert toast_z > _zindex(html, ".aipop")       # 1000
    assert toast_z > _zindex(html, "#hovertip")    # 2000
    assert toast_z > _zindex(html, ".mdlg")        # 110
    assert toast_z > _zindex(html, ".viewer")      # 100
    # Toast stays non-blocking even at the top of the stack
    # (checked on the stacking rule, not the mobile offset rule).
    toast_rules = re.findall(r"\.toast \{([^}]*)\}", html)
    assert any("pointer-events:none" in r and "z-index:5000" in r
               for r in toast_rules)
    # Mobile: the media-query .toast rule moves only the bottom
    # offset and sets NO z-index, so the desktop rule above
    # governs mobile too -- exactly one .toast rule carries a
    # z-index, and it is the 5000 one.
    z_rules = [r for r in toast_rules if "z-index" in r]
    assert len(z_rules) == 1, toast_rules
    assert "z-index:5000" in z_rules[0]
    # The toast element itself: a single global container, a
    # direct body child, driven by toast().
    assert html.count('class="toast"') == 1
    assert '<div class="toast" id="toast"></div>' in html
    script = html[html.index("<script>"):]
    assert 'function toast(msg)' in script
    assert '$("#toast")' in script
    # Audit of every other message container: the inline
    # errors live INSIDE their dialogs (same stacking context,
    # so they cannot render behind them), and the guest login
    # messages live on the login page, not under any dialog.
    setup_seg = html[html.index('id="lkwrap"'):
                     html.index('id="lockpwpop"')]
    assert 'id="lkerr"' in setup_seg
    pw_seg = html[html.index('id="lockpwpop"'):]
    assert 'id="lockpwerr"' in pw_seg
    assert 'id="gloginerr"' in html and 'id="gloginmsg"' in html
