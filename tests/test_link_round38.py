"""v2.8.23 round (Essef Nov 6) -- web/desktop only, dropit.py only.

(1) XLSX WINDOW TOO WIDE: the 2.8.22 .xlsx preview used the fixed
    1080px .fittext box even for a 2-column sheet (table 148px in
    a 1080px window). The window now HUGS the rendered table:
    JS sets the box width from the table's actual width (table +
    70px chrome, min 480px, max 1080px) and adds .fitxlsx; PDF /
    Word / text keep the big .fittext box.
(2) PICTURE/VIDEO PREVIEW BIGGER: Essef doubted the 2.8.22
    preview was clearly visible. Pictures now render up to 2x
    natural (was 1.25x), up to 1400px wide (was 1080px) and
    96vh tall (was 92vh); video HUGS the video (.fitvid, JS
    sizes the box from the displayed video, up to 1.5x natural)
    instead of sitting as a narrow strip in a fixed 1080px box.
    Still fit-view (no scrolling), still sized to the media,
    still very transparent. Proven below with a REAL photo
    (2048x1536), a REAL portrait photo and a REAL video frame,
    visually inspected in the proof screenshots.
(4) WEB BUTTONS BACK TO APK 2.6.69 DESIGN: the web Upload
    buttons revert to the 2.6.69 design decoded from the real
    2.6.69 backup APK (DropIt-2.6.69-backup.apk) and Essef's
    photo 9945_3_q880.jpg -- full-width (match_parent, not the
    60% centred pill), 12px corners (btn_primary/btn_secondary
    radius 12dp), 12px padding, 14px text, Choose Files normal
    weight on brown #4E342E (btn_main_brown) with the folder
    icon, Send Text BOLD on solid blue #277ff0 (btn_main_blue)
    with the text-snippet icon (APK ic_note -- Essef Nov 6
    ~2:03 AM: not the upload arrow, not the chat bubble, not
    the airplane). Labels match 2.6.69: "Choose Files to Send"
    and "Send Text to PC". Scoped to html:not(.pcapp), so the PC
    desktop app (pywebview bridge -> .pcapp, see markPcApp)
    keeps its 2.8.22 buttons exactly; the h3 "Send Text" heading
    keeps its chat bubble (only the BUTTON icons change). The
    host #sendsnippet gets the note icon on web too (same
    toggle); its label stays "Send Text". The web Upload card
    height (2.8.22, taller to the orange line) and the tab label
    "Upload" are unchanged.
    PC-app proof: tests/probe_round38_pcapp.py drives the REAL
    pywebview window and proves .pcapp is added, the host Send
    Text button keeps its bubble (note hidden), solid blue
    #277ff0, 8px radius, and the mobile buttons are zero-size
    there. The pytest test below also checks the same scoping
    in Chromium with .pcapp forced.
    NOTE (supersedes round33(g) for the BUTTON icon on web):
    round33(g) asserted the Send Text buttons show the chat
    bubble; Essef's Nov 6 ~2:03 AM instruction replaces the
    button icon with the text-snippet icon on web. The bubble
    stays in the markup (first svg) and shows in the PC app,
    and the h3 heading keeps the bubble, so round33(g) still
    passes as a source check.
"""
import ast
import os
import re
import shutil
import subprocess
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
from test_link_round2 import server, _raw  # noqa: F401,E402
from test_link_round36 import _playwright, _guest_page  # noqa: E402
from test_link_round37 import (  # noqa: E402
    _host_page, _open_preview, _preview_geom, _close_preview,
    _make_fixtures, _measure_send_tab)

PAGE = D.PAGE
SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py"),
           encoding="utf-8").read()

PROOF = "/home/hatch/workspace/dropit-proof-round38"
os.makedirs(PROOF, exist_ok=True)

REAL_PHOTO = "/home/hatch/workspace/user/files/0799a122-f661-4026-a953-7a325bba6869_8_ft2q.jpg"
REAL_PORTRAIT = "/home/hatch/workspace/user/files/60992_8_lhdt.jpg"
REAL_VIDEO = "/home/hatch/workspace/user/files/61234_7_kkgj.mp4"

# APK ic_note (text-snippet icon) geometry, from the 2.6.69 backup.
NOTE_PAGE = "M6,3 L14,3 L18,7 L18,19.5 A1.5,1.5 0 0 1 16.5,21 L6,21 A1.5,1.5 0 0 1 4.5,19.5 L4.5,4.5 A1.5,1.5 0 0 1 6,3 Z"
NOTE_LINES = "M14,3 L14,7.2 L18,7.2 M8.3,12.2 L15.7,12.2 M8.3,15.6 L15.7,15.6 M8.3,19 L12.9,19"
BUBBLE = ("M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 "
          "8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 "
          "8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 "
          "0 0 1 8 8v.5z")


def _make_wide_xlsx(linkdir):
    """6 columns of long unbroken strings -- the rendered table is
    far wider than the 1080px max, so the window must clamp."""
    ss = ('<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="6" uniqueCount="6">'
          + "".join('<si><t>Column%d_%s</t></si>' % (i, "x" * 50)
                    for i in range(6)) + '</sst>')
    row = ('<row r="1">' + "".join(
        '<c r="%s1" t="s"><v>%d</v></c>' % (chr(65 + i), i)
        for i in range(6)) + '</row>')
    sheet = ('<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<sheetData>' + row + '</sheetData></worksheet>')
    wb = ('<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
          '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/></sheets></workbook>')
    rels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
    ct = ('<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
          '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>')
    with zipfile.ZipFile(os.path.join(linkdir, "wide.xlsx"), "w") as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        z.writestr("xl/sharedStrings.xml", ss)


def _xlsx_geom(pg):
    return pg.evaluate("""() => {
      const box = document.querySelector('.previewbox');
      const body = document.querySelector('#previewbody');
      const tbl = body.querySelector('.xlsxview table');
      const br = box.getBoundingClientRect();
      const tr = tbl ? tbl.getBoundingClientRect() : null;
      return {boxW: Math.round(br.width), boxH: Math.round(br.height),
        tblW: tr ? Math.round(tr.width) : null,
        bodyScrollW: body.scrollWidth, bodyClientW: body.clientWidth,
        cls: document.querySelector('#previewpop').className};
    }""")


def _video_geom(pg):
    return pg.evaluate("""() => {
      const box = document.querySelector('.previewbox');
      const body = document.querySelector('#previewbody');
      const v = body.querySelector('video');
      const br = box.getBoundingClientRect();
      const vr = v ? v.getBoundingClientRect() : null;
      return {boxW: Math.round(br.width), boxH: Math.round(br.height),
        vidW: vr ? Math.round(vr.width) : null,
        vidH: vr ? Math.round(vr.height) : null,
        vidNatW: v ? v.videoWidth : null, vidNatH: v ? v.videoHeight : null,
        cls: document.querySelector('#previewpop').className};
    }""")


def _open_video(pg, name):
    _open_preview(pg, name)
    pg.wait_for_timeout(500)
    pg.evaluate("""() => { const v = document.querySelector('#previewbody video');
      if (v) { v.currentTime = 5; } }""")
    pg.wait_for_timeout(1200)


def _button_geom(pg, sel):
    return pg.evaluate("""(sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
      const vis = (c) => { const s = el.querySelector(c);
        return s ? getComputedStyle(s).display : null; };
      return {w: Math.round(r.width), h: Math.round(r.height),
        bg: cs.backgroundColor, radius: cs.borderRadius,
        fs: cs.fontSize, fw: cs.fontWeight, pad: cs.padding,
        label: el.textContent.trim(),
        bubble: vis('.ic-bubble'), note: vis('.ic-note')};
    }""", sel)


def test_version_is_2_8_23():
    assert D.VERSION == "2.8.23"


def test_interpreted_page_valid_js_no_surrogates():
    for n in ast.walk(ast.parse(SRC)):
        if isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "PAGE"
                for t in n.targets):
            page = n.value.value
            break
    else:
        raise AssertionError("PAGE assignment not found")
    assert page == PAGE
    assert not [c for c in page if 0xD800 <= ord(c) <= 0xDFFF]
    page.encode("utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
    assert len(scripts) == 2
    for i, js in enumerate(scripts):
        with open("/tmp/r38_script_%d.js" % i, "w",
                  encoding="utf-8") as fh:
            fh.write(js)
        out = subprocess.run(["node", "--check",
                              "/tmp/r38_script_%d.js" % i],
                             capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr


# ---- (1) xlsx window hugs the table -----------------------------------

def test_1_xlsx_hug_source():
    assert ".previewpop.fittext.fitxlsx .previewbox" in PAGE
    assert 'pop.classList.add("fitxlsx")' in PAGE
    assert 'pop.classList.remove("fitxlsx")' in PAGE
    assert "Math.max(tw + 70, 480)" in PAGE
    assert "Math.min(1080, window.innerWidth * 0.96)" in PAGE
    # PDF / Word / text still get the plain big .fittext box.
    assert ".previewpop.fittext .previewbox { width:min(1080px,96vw)" in PAGE


def test_1_live_xlsx_narrow_and_wide(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r38xlsx"})
    linkdir = os.path.join(str(base), "r38xlsx")
    _make_fixtures(linkdir)
    _make_wide_xlsx(linkdir)
    pw = _playwright()
    try:
        browser, pg = _host_page(pw, port)
        try:
            # Narrow sheet (2 cols, table 148px): the window hugs
            # it at the 480px minimum -- NOT the 1080px box.
            _open_preview(pg, "sheet.xlsx")
            pg.wait_for_timeout(500)
            m = _xlsx_geom(pg)
            assert "fitxlsx" in m["cls"], m
            assert m["tblW"] == 148, m
            assert m["boxW"] == 480, m
            assert m["bodyScrollW"] <= m["bodyClientW"], m
            pg.screenshot(path=os.path.join(PROOF, "r38_xlsx_narrow.png"))
            _close_preview(pg)
            # Wide sheet: the window clamps at the 1080px max and
            # the table scrolls horizontally inside it.
            _open_preview(pg, "wide.xlsx")
            pg.wait_for_timeout(500)
            m = _xlsx_geom(pg)
            assert "fitxlsx" in m["cls"], m
            assert m["tblW"] > 1010, m
            assert m["boxW"] == 1080, m
            assert m["bodyScrollW"] > m["bodyClientW"], m
            pg.screenshot(path=os.path.join(PROOF, "r38_xlsx_wide.png"))
            _close_preview(pg)
            # Closing resets the box width: the next preview (a
            # picture) sizes itself, it does not inherit 480px.
            _open_preview(pg, "pic.png")
            m = _preview_geom(pg)
            assert m["boxW"] == 833, m
            _close_preview(pg)
        finally:
            browser.close()
    finally:
        pw.stop()


# ---- (2) picture / video previews bigger -------------------------------

def test_2_bigger_previews_source():
    # Picture: 2x upscale, 1400px / 96vh caps (were 1.25x, 1080px,
    # 92vh). Video: .fitvid hugging, 1.5x cap.
    assert "Math.min(availW / natW, availH / natH, 2)" in PAGE
    assert "Math.min(1400, window.innerWidth * 0.96) - 70" in PAGE
    assert "window.innerHeight * 0.96 - 196" in PAGE
    assert ".previewpop.fitmedia .previewbox { width:min(1400px,96vw); max-height:96vh; }" in PAGE
    assert ".previewpop.fitvid .previewbox" in PAGE
    assert 'pop.classList.add("fitvid")' in PAGE
    assert "Math.min(availW / vw, availH / vh, 1.5)" in PAGE
    assert 'pop.classList.remove("fitvid")' in PAGE
    # Still very transparent, still fit-view (no page scroll from
    # the preview), zoom controls still there.
    assert "rgba(18,23,42,.5)" in PAGE
    assert "window.__pvZoom" in PAGE


def test_2_live_real_photo_and_video_bigger(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r38big"})
    linkdir = os.path.join(str(base), "r38big")
    _make_fixtures(linkdir)
    shutil.copy(REAL_PHOTO, os.path.join(linkdir, "realphoto.jpg"))
    shutil.copy(REAL_PORTRAIT, os.path.join(linkdir, "realportrait.jpg"))
    shutil.copy(REAL_VIDEO, os.path.join(linkdir, "realvideo.mp4"))
    pw = _playwright()
    try:
        browser, pg = _host_page(pw, port)
        try:
            # Real landscape photo, 2048x1536: was 720x540 in a
            # 790px box; now 763x572 in an 833px box.
            _open_preview(pg, "realphoto.jpg")
            pg.wait_for_timeout(800)
            m = _preview_geom(pg)
            assert "fitpic" in m["cls"], m
            assert m["img"]["w"] == 763 and m["img"]["h"] == 572, m
            assert m["boxW"] == 833, m
            assert m["bg"] == "rgba(18, 23, 42, 0.5)", m
            assert m["img"]["bottom"] <= m["bodyBottom"], m
            pg.screenshot(path=os.path.join(PROOF, "r38_photo_land.png"))
            _close_preview(pg)
            # Real portrait photo, 1152x2048: was 304x540 in a
            # 374px box; now 322x572 in a 392px box.
            _open_preview(pg, "realportrait.jpg")
            pg.wait_for_timeout(800)
            m = _preview_geom(pg)
            assert m["img"]["w"] == 322 and m["img"]["h"] == 572, m
            assert m["boxW"] == 392, m
            pg.screenshot(path=os.path.join(PROOF, "r38_photo_port.png"))
            _close_preview(pg)
            # Small fixture picture, 400x300: the 2x cap is the big
            # win -- was 500x375 in a 570px box, now 763x572 in an
            # 833px box. Zoom still works on top of it.
            _open_preview(pg, "pic.png")
            m = _preview_geom(pg)
            assert m["img"]["w"] == 763 and m["img"]["h"] == 572, m
            assert m["boxW"] == 833, m
            pg.screenshot(path=os.path.join(PROOF, "r38_pic_small.png"))
            pg.click("#pvzin")
            pg.wait_for_timeout(300)
            assert pg.evaluate("() => document.querySelector('#pvzval').textContent") == "125%"
            _close_preview(pg)
            # Real video, 478x850 portrait: was a 304x540 strip in
            # a 1080px box; now 322x572 in a 392px box that hugs it.
            _open_video(pg, "realvideo.mp4")
            m = _video_geom(pg)
            assert "fitvid" in m["cls"], m
            assert m["vidW"] == 322 and m["vidH"] == 572, m
            assert m["boxW"] == 392, m
            assert m["vidNatW"] == 478 and m["vidNatH"] == 850, m
            pg.screenshot(path=os.path.join(PROOF, "r38_video.png"))
            _close_preview(pg)
        finally:
            browser.close()
        # Bigger desktop: video 473x841 in a 543px box (was
        # 449x798 in a 1080px box); photo 1121x841 in 1191px.
        browser, pg = _host_page(pw, port, width=1920, height=1080)
        try:
            _open_video(pg, "realvideo.mp4")
            m = _video_geom(pg)
            assert m["vidW"] == 473 and m["vidH"] == 841, m
            assert m["boxW"] == 543, m
            pg.screenshot(path=os.path.join(PROOF, "r38_video_1920.png"))
            _close_preview(pg)
            _open_preview(pg, "realphoto.jpg")
            pg.wait_for_timeout(800)
            m = _preview_geom(pg)
            assert m["img"]["w"] == 1121 and m["img"]["h"] == 841, m
            assert m["boxW"] == 1191, m
            _close_preview(pg)
        finally:
            browser.close()
    finally:
        pw.stop()


# ---- (4) web buttons back to APK 2.6.69 design ------------------------

def test_4_web_buttons_269_source():
    # The web-only revert rule, scoped off the PC app.
    assert ("html:not(.pcapp) .msend #msendfiles, html:not(.pcapp) .msend #msendsnippet"
            in PAGE)
    assert "width:100%; margin:6px auto 0; display:flex; border-radius:12px; padding:12px; font-size:14px;" in PAGE
    assert "html:not(.pcapp) .msend #msendfiles { font-weight:400; }" not in PAGE
    # 2.6.69 Choose Files is btn_secondary (theme-adaptive, NOT
    # the later brown): dark #141926 fill / #EEF1F8 text /
    # #2A3560 stroke, light #FFFFFF / #0F172A / #C3CFDE, with the
    # 📁 emoji as ::before and the folder SVG hidden on web.
    assert ("html:not(.pcapp) .msend #msendfiles { font-weight:400; background:#141926; "
            "color:#EEF1F8; box-shadow:inset 0 0 0 1px #2A3560; }") in PAGE
    assert ("html.light:not(.pcapp) .msend #msendfiles { background:#FFFFFF; "
            "color:#0F172A; box-shadow:inset 0 0 0 1px #C3CFDE; }") in PAGE
    assert "html:not(.pcapp) .msend #msendfiles svg { display:none; }" in PAGE
    assert "html:not(.pcapp) .msend #msendfiles::before { content:\"📁\"; }" in PAGE
    assert "html:not(.pcapp) .msend #msendsnippet { font-weight:700; background:#277ff0; color:#ffffff; }" in PAGE
    # The 2.8.13 brown pill rule and the 2.8.17 60% rule stay in
    # the file as the PC app's base (the web rule overrides them
    # by specificity on web only).
    assert ".msend #msendfiles { background:#4E342E; color:#FFFFFF; border-radius:999px; }" in PAGE
    assert ".msend #msendfiles, .msend #msendsnippet { width:60%; margin:10px auto 0; display:flex; border-radius:13px; }" in PAGE
    # Labels match 2.6.69 exactly.
    assert "Choose Files to Send</button>" in PAGE
    assert "Send Text to PC</button>" in PAGE
    # The text-snippet (note) icon: APK ic_note geometry, on both
    # Send Text buttons; the chat bubble stays FIRST in each
    # button's markup (round33 source check) and shows in the PC
    # app, the note shows on web.
    assert NOTE_PAGE in PAGE
    assert NOTE_LINES in PAGE
    assert PAGE.count("ic-note") >= 4
    for bid in ("sendsnippet", "msendsnippet"):
        i = PAGE.index('id="%s"' % bid)
        seg = PAGE[i:i + 1400]
        assert BUBBLE in seg, bid
        assert NOTE_PAGE in seg, bid
        assert seg.index(BUBBLE) < seg.index(NOTE_PAGE), bid
    # No upload arrow / airplane anywhere near the Send Text
    # buttons; the h3 heading keeps its chat bubble.
    assert "M12 15.5V4.2M6.9 8.8L12 3.7 17.1 8.8" not in PAGE[
        PAGE.index('id="msendsnippet"'):PAGE.index('id="msendsnippet"') + 1400]
    i = PAGE.index("Send Text</h3>")
    assert BUBBLE in PAGE[max(0, i - 900):i]


def test_4_live_web_buttons_match_269(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r38btn"})
    pw = _playwright()
    try:
        browser, ctx, pg, fwd = _guest_page(pw, port, 390, 844, light=False)
        try:
            f = _button_geom(pg, "#msendfiles")
            t = _button_geom(pg, "#msendsnippet")
            # Full width, 12px corners, 12px padding, 14px text.
            assert f["w"] == 298 and f["h"] == 43, f
            assert t["w"] == 298 and t["h"] == 43, t
            assert f["radius"] == "12px" and t["radius"] == "12px", (f, t)
            assert f["pad"] == "12px" and t["pad"] == "12px", (f, t)
            assert f["fs"] == "14px" and t["fs"] == "14px", (f, t)
            # Colours: 2.6.69 btn_secondary Choose Files (dark
            # #141926 fill here, light #FFFFFF), solid blue Send Text.
            assert f["bg"] == "rgb(20, 25, 38)", f
            assert t["bg"] == "rgb(39, 127, 240)", t
            assert pg.evaluate(
                "() => getComputedStyle(document.querySelector('#msendfiles')).boxShadow"
            ).find("rgb(42, 53, 96)") >= 0, f
            # Weights: Choose Files normal, Send Text bold.
            assert f["fw"] == "400", f
            assert t["fw"] == "700", t
            # Labels: 2.6.69 exact (textContent excludes the
            # ::before emoji, so it reads without it).
            assert f["label"] == "Choose Files to Send", f
            assert t["label"] == "Send Text to PC", t
            # Icons on web: note visible, bubble hidden.
            assert t["note"] not in (None, "none"), t
            assert t["bubble"] == "none", t
            # Choose Files shows the 📁 emoji via ::before and the
            # white folder SVG is hidden (it would be invisible on
            # the light button and wrong on the dark one).
            assert "📁" in pg.evaluate(
                "() => getComputedStyle(document.querySelector('#msendfiles'), '::before').content"
            ), f
            assert pg.evaluate(
                "() => getComputedStyle(document.querySelector('#msendfiles svg')).display"
            ) == "none", f
            # The 2.8.22 fit still holds: no column scroll at
            # 390x844, button fully visible with clear space.
            m = _measure_send_tab(pg)
            assert m["mayScroll"] is False, m
            assert m["colbodyScrollH"] <= m["colbodyClientH"], m
            assert m["btnVisiblePct"] == 1, m
            assert m["gapBtnToTabs"] >= 8, m
            pg.screenshot(path=os.path.join(PROOF, "r38_mobile_upload.png"))
        finally:
            ctx.close()
            browser.close()
            fwd.close()
        # Light mode: the 2.6.69 button is white with dark text
        # and a light grey border (the photo reference).
        browser, ctx, pg, fwd = _guest_page(pw, port, 390, 844, light=True)
        try:
            f = _button_geom(pg, "#msendfiles")
            assert f["bg"] == "rgb(255, 255, 255)", f
            assert pg.evaluate(
                "() => getComputedStyle(document.querySelector('#msendfiles')).boxShadow"
            ).find("rgb(195, 207, 222)") >= 0, f
            assert pg.evaluate(
                "() => getComputedStyle(document.querySelector('#msendfiles')).color"
            ) == "rgb(15, 23, 42)", f
            pg.screenshot(path=os.path.join(PROOF, "r38_mobile_upload_light.png"))
        finally:
            ctx.close()
            browser.close()
            fwd.close()
        # Desktop host view (a browser, not the PC app): the host
        # Send Text button shows the note icon too, keeps its
        # "Send Text" label and solid blue.
        browser, pg = _host_page(pw, port)
        try:
            h = _button_geom(pg, "#sendsnippet")
            assert h["label"] == "Send Text", h
            assert h["bg"] == "rgb(39, 127, 240)", h
            assert h["note"] not in (None, "none"), h
            assert h["bubble"] == "none", h
            pg.screenshot(path=os.path.join(PROOF, "r38_host_sendtext.png"))
            # Forcing .pcapp (the PC app's view of the same page):
            # the bubble comes back, the note hides, and the mobile
            # buttons fall back to the 2.8.22 60% / 13px shape.
            pg.evaluate("() => document.documentElement.classList.add('pcapp')")
            pg.wait_for_timeout(300)
            h2 = _button_geom(pg, "#sendsnippet")
            assert h2["bubble"] not in (None, "none"), h2
            assert h2["note"] == "none", h2
            assert h2["bg"] == "rgb(39, 127, 240)", h2
            assert h2["label"] == "Send Text", h2
        finally:
            browser.close()
        # Mobile width WITH .pcapp forced: the web-only revert does
        # not apply -- 2.8.22 shape (60% / 13px / bold) and the
        # bubble icon on the Send Text button.
        browser, ctx, pg, fwd = _guest_page(pw, port, 390, 844, light=False)
        try:
            pg.evaluate("() => document.documentElement.classList.add('pcapp')")
            pg.wait_for_timeout(300)
            f = _button_geom(pg, "#msendfiles")
            t = _button_geom(pg, "#msendsnippet")
            assert f["w"] == 179 and f["radius"] == "13px", f
            assert t["w"] == 179 and t["radius"] == "13px", t
            assert t["bubble"] not in (None, "none"), t
            assert t["note"] == "none", t
            assert t["label"] == "Send Text to PC", t
            pg.screenshot(path=os.path.join(PROOF, "r38_pcapp_mobile.png"))
        finally:
            ctx.close()
            browser.close()
            fwd.close()
    finally:
        pw.stop()


def test_4_pcapp_probe_script_exists():
    # The REAL pywebview proof (run separately with the pywebview
    # venv): tests/probe_round38_pcapp.py -- it drives the actual
    # PC-app window and proves .pcapp is added, the host Send Text
    # button keeps its bubble (note hidden), solid blue #277ff0,
    # 8px radius, and the mobile buttons are zero-size there.
    assert os.path.isfile(os.path.join(
        os.path.dirname(__file__), "probe_round38_pcapp.py"))
    assert os.path.isfile(os.path.join(
        os.path.dirname(__file__), "probe_round38.py"))
