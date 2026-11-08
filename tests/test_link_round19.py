"""v2.8.4 Set Up polish: zoomed folder-button reference + annotated proof
(Nov 3, 2:30 AM PT). Checks the INTERPRETED PAGE, not raw source.
Note: the 3rd picture in that message was our own 2.8.3 proof, not a new
reference — only the zoomed buttons and the annotated screenshot count."""
import ast
import re

SRC = open(__file__.replace("tests/test_link_round19.py", "dropit.py")).read()
PAGE = None
for _n in ast.walk(ast.parse(SRC)):
    if isinstance(_n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "PAGE" for t in _n.targets
    ):
        PAGE = _n.value.value
        break
assert PAGE is not None


def test_version_284():
    assert 'VERSION = "2.8.4"' in SRC


def test_folder_button_dark_colours_scoped_to_host_dialog():
    # Dark navy fill + thin cyan border + cyan text; dark purple fill +
    # thin purple border + white text; scoped to the host dialog only so
    # the Files-tab buttons keep their colours.
    assert re.search(
        r"\.lkbox:not\(\.guestcard\) \.btn\.openf \{ background:#092a48; border:2px solid #00c9f5; color:#65e4ff;",
        PAGE,
    )
    assert re.search(
        r"\.lkbox:not\(\.guestcard\) \.btn\.changef \{ background:#261448; border:2px solid #b638f5; color:#ffffff;",
        PAGE,
    )


def test_folder_buttons_use_outline_svg_not_emoji():
    # The Set Up folder buttons must not carry the old emoji icons.
    assert "📁 Open Folder" not in PAGE
    assert "⇄ Change Folder" not in PAGE
    assert re.search(r'id="lkopenfolder"[^>]*><svg[^>]*><path d="M22 19a2', PAGE)
    assert re.search(r'id="lkchangefolder"[^>]*><svg[^>]*><path d="M17 2\.1', PAGE)


def test_folder_buttons_span_new_address_field():
    # Folder row is end-aligned at 65px and the New Address field's
    # bottom margin is zeroed, so the buttons' top/bottom equal the
    # field's top/bottom (the annotated red lines) instead of sitting
    # 10px low on the field's bottom margin.
    assert ".lkbox:not(.guestcard) .lkfolderrow { align-self:end; height:65px;" in PAGE
    assert ".lkbox:not(.guestcard) .lknewcol .lkfield { margin-bottom:0; }" in PAGE


def test_permissions_heading_above_box_and_refined_info_icon():
    # Heading lives above/outside the box (yellow-line position), not
    # inside .lkperms; the ugly ⓘ is gone, replaced by an SVG circled-i.
    assert "ⓘ" not in PAGE
    assert '<div class="lkpermlabel">Permissions' in PAGE
    assert re.search(
        r'class="lkpermlabel">Permissions <button[^>]*id="lkperminfo"[^>]*><svg[^>]*><circle cx="12" cy="12" r="9"/>',
        PAGE,
    )
    assert (
        "Permissions are saved for this address only. Change a box and tap Save, "
        "and guests using this address get exactly those permissions." in PAGE
    )


def test_notice_icon_is_visibly_unlocked_svg():
    # No locked-padlock emoji; an SVG padlock whose shackle path ends
    # open (9.8,-1.6) instead of connecting back to the body.
    assert "🔓" not in PAGE
    assert re.search(
        r'id="lkopenwarn"><svg[^>]*><path d="M7 11V7a5 5 0 0 1 9\.8-1\.6"/>',
        PAGE,
    )
    assert "Open address &mdash; anyone on your Wi-Fi can use it" in PAGE


def test_kept_283_rules():
    # Password still ends at the New Address right edge; exactly six
    # checkboxes, no AI; ChatGPT font; Save icon; pill still outside.
    assert "flex:0 0 calc((100% - 30px) / 2)" in PAGE
    assert "💾 Save" in PAGE
    assert '"Segoe UI", Arial, sans-serif' in PAGE
    assert "top:-44px" in PAGE
    assert len(re.findall(r'data-perm="', PAGE)) == 6
    assert "ai_features" not in PAGE.lower().replace("use ai features", "")
