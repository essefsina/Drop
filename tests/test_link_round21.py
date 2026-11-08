"""v2.8.6 Set Up fit + rectangular buttons + pill higher + Host Only into
the info icon (Essef Nov 4, 6:39 PM PT). Checks the INTERPRETED PAGE,
not raw source, following the round16-20 pattern."""

import ast

SRC = open(__file__.replace("tests/test_link_round21.py", "dropit.py")).read()
PAGE = None
for _n in ast.walk(ast.parse(SRC)):
    if isinstance(_n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "PAGE" for t in _n.targets
    ):
        PAGE = _n.value.value
        break
assert PAGE is not None


def test_version_286():
    assert 'VERSION = "2.8.6"' in SRC


def test_dialog_compact_fit():
    # Host dialog: 52px fields (was 65px), tighter padding/margins.
    assert ".lkbox:not(.guestcard) { max-height:calc(100dvh - 32px); padding:20px 32px 16px; }" in PAGE
    assert ".lkbox:not(.guestcard) .lkfield, .lkbox:not(.guestcard) .lkview { height:52px; font-size:17px; padding:0 18px; border-radius:12px; }" in PAGE
    assert ".lkbox:not(.guestcard) .lkfolderrow .btn { height:52px; min-height:52px; font-size:17px; border-radius:8px; }" in PAGE
    assert ".lkbox:not(.guestcard) .lkpwrow .lkiconbtn { width:64px; height:52px; border-radius:12px; }" in PAGE
    assert ".lkbox:not(.guestcard) .lksavewrap .btn.primary { width:150px; height:48px; min-height:48px; font-size:18px; border-radius:8px; }" in PAGE
    assert ".lkbox:not(.guestcard) .permbox { width:26px; height:26px; border-radius:7px; }" in PAGE


def test_rectangular_buttons():
    # 8px corners on main-page + Set Up buttons; Files row not shrunk to 11px.
    assert ".board .nbtnrow .btn, .board .fbtnrow .btn, .board #sendsnippet," in PAGE
    assert "border-radius:8px; }" in PAGE
    assert ".board .fbtnrow { flex-wrap:wrap; }" in PAGE
    assert ".board .fbtnrow .btn { padding:12px 6px; font-size:13px; gap:6px; white-space:normal; overflow:visible; text-overflow:clip; line-height:1.25; }" in PAGE
    # Fills per action unchanged from 2.8.5.
    assert "background:#2dd4bf; color:#052e33;" in PAGE
    assert ".board #starfilter { background:#fbbf24; color:#231303;" in PAGE
    assert "background:#f87171; color:#ffffff;" in PAGE
    assert ".board .fbtnrow #changefolder { background:#a78bfa; color:#ffffff;" in PAGE


def test_pill_slightly_higher_no_resize():
    # top:-54px (was -44px), status height unchanged at 36px, no other
    # pill/card/page size change in the 2.8.6 block.
    assert ".devpill { top:-54px; }" in PAGE
    assert "height:36px;" in PAGE


def test_host_only_moved_into_info_icon():
    # No visible Host Only line under the checkboxes any more.
    assert "Host Only — Applies To This Address</p>" not in PAGE
    assert "<p class=\"lkpermnote\">" not in PAGE
    # Both texts now in the info icon title (and its toast).
    assert "Permissions are saved for this address only. Change a box and tap Save, and guests using this address get exactly those permissions. Host only — applies to this address." in PAGE


def test_six_checkboxes_no_ai_kept():
    assert PAGE.count('data-perm=') >= 6
    assert "Add / Edit Notes" in PAGE
    assert "Use AI Features" not in PAGE
