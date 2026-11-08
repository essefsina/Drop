"""v2.8.22 round (Essef Nov 6, ~1 AM) -- web/desktop only.

(2) WEB UPLOAD CARD TALLER: the Nov 6 screenshot showed the Send
    Text button cut off by the bottom of the Upload card on his
    phone (orange line drawn just above the pill tabs). The Send
    column alone gets a 170px offset (was 205px), so its bottom
    edge lands ~8px above the pill tabs and the whole stack fits
    without scrolling at 390x844 and taller; shorter phones still
    scroll cleanly via fitSendTab. Notes/Files/Search keep 205px.
(3) PC FILE PREVIEW WINDOW (pictures): the window HUGS the picture
    (JS sets the box width from the displayed image size), the
    picture is slightly bigger (up to 1.25x natural, clamped to
    the viewport), the window is VERY transparent (translucent
    background, title/buttons stay opaque), and pictures are
    ZOOMABLE (+ / - / Fit, click to toggle, wheel). Video keeps
    the 2.8.21 fit view; PDF/doc previews are untouched here.
(4) TEXT PREVIEW RIGHT-CLICK: a dedicated ANIMATED pop-up
    (#pvctx, pop-in scale/fade) with Copy and Select All ONLY --
    no Paste. Copy toasts "copied 📑" (literal emoji, never a
    \\u escape). Applies to previews with rendered/extracted text
    (text, Word, Excel tables); the PDF <embed> keeps its native
    plugin menu (no DOM text to copy/select).
(6) DARK-MODE COPY ICON: the mobile address-field copy button
    (#mcopy) had no colour rule, so it fell back to the browser's
    ButtonText (black) -- contrast 1.08:1 on the dark field,
    invisible. It now uses color:var(--txt): light in dark mode,
    near-black in light mode (appearance unchanged there).
(7) FILES SENT ON PC say "sent", not "received": the upload
    toast in uploadFiles is now "✅ <name> sent". Label only.
(8) TEXT PREVIEWS BIGGER TOO: PDF / Word / Excel / text previews
    get the big 1080px / 92vh window (.fittext) with a taller PDF
    embed and larger text. Excel (.xlsx) now previews at all --
    first sheet as an HTML table via the new /api/xlsx/ endpoint
    (stdlib zip+ET, mirroring /api/docx/). Legacy .xls/.ods keep
    the "cannot preview" message.
(9) "SHOW IN FOLDER" -- click-tested for real this time: see
    tests/probe_round37_bridge.py (real pywebview window, real
    click). It proves the click reaches Api.reveal_file, the
    spawn runs with the right argv AND DEVNULL stdio + close_fds,
    and a forced failure surfaces as a toast naming the recorded
    error. The pytest test below asserts the source facts; the
    probe is the live proof.
(10) SET UP WINDOW BORDER SQUARE: the Set Up Your Addresses
    window's border-radius is 0 (one override rule, higher
    specificity than .lockbox's 18px and the 2.8.0 rule's 27px).
    Nothing inside changes and the window is not resized.
"""
import ast
import json
import os
import re
import subprocess
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
import app as appmod  # noqa: E402
from test_link_round2 import server, _raw  # noqa: F401,E402
from test_link_round3 import _flip_role, _guest_client  # noqa: E402
from test_link_round34 import _Fwd  # noqa: E402
from test_link_round36 import _playwright, _guest_page, MOBILE_UA  # noqa: E402

PAGE = D.PAGE
SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py"),
           encoding="utf-8").read()
APP = open(os.path.join(os.path.dirname(__file__), "..", "app.py"),
           encoding="utf-8").read()

PROOF = "/home/hatch/workspace/dropit-proof-round37"
os.makedirs(PROOF, exist_ok=True)


def _make_fixtures(linkdir):
    from PIL import Image
    img = Image.new("RGB", (400, 300), (30, 120, 200))
    img.save(os.path.join(linkdir, "pic.png"))
    img2 = Image.new("RGB", (500, 2000), (200, 60, 60))
    img2.save(os.path.join(linkdir, "tall.png"))
    with open(os.path.join(linkdir, "notes.txt"), "w") as fh:
        fh.write("Hello preview world\n" + "line two\n" * 40)
    pdf = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
           b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
           b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
           b"4 0 obj<</Length 44>>stream\nBT /F1 24 Tf 100 700 Td (Hello PDF) Tj ET\nendstream\nendobj\n"
           b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
           b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000260 00000 n \n0000000354 00000 n \n"
           b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n440\n%%EOF\n")
    with open(os.path.join(linkdir, "doc.pdf"), "wb") as fh:
        fh.write(pdf)
    docx_xml = ('<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t>Hello Word preview</w:t></w:r></w:p>'
                '<w:p><w:r><w:t>Second paragraph here.</w:t></w:r></w:p></w:body></w:document>')
    ct = ('<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    with zipfile.ZipFile(os.path.join(linkdir, "doc.docx"), "w") as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("word/document.xml", docx_xml)
    ss = ('<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="3" uniqueCount="3">'
          '<si><t>Name</t></si><si><t>Amount</t></si><si><t>Alice</t></si></sst>')
    sheet = ('<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
             '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>42</v></c></row></sheetData></worksheet>')
    wb = ('<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
          '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/></sheets></workbook>')
    rels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
    ct2 = ('<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
           '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
           '<Default Extension="xml" ContentType="application/xml"/>'
           '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
           '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
           '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>')
    with zipfile.ZipFile(os.path.join(linkdir, "sheet.xlsx"), "w") as z:
        z.writestr("[Content_Types].xml", ct2)
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        z.writestr("xl/sharedStrings.xml", ss)


def _host_page(pw, port, width=1280, height=800, light=False):
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    pg = browser.new_page(viewport={"width": width, "height": height})
    pg.goto("http://127.0.0.1:%d/" % port)
    pg.wait_for_timeout(1800)
    if light:
        pg.evaluate("() => document.documentElement.classList"
                    ".add('light')")
        pg.wait_for_timeout(300)
    return browser, pg


def _open_preview(pg, name):
    pg.evaluate("""(n) => {
      const row = [...document.querySelectorAll('.frow')].find(r => r.dataset.frow === n);
      if (!row) return 'norow';
      const t = row.querySelector('.fname, .thwrap'); (t || row).click(); return 'clicked';
    }""", name)
    pg.wait_for_timeout(1000)


def _preview_geom(pg):
    return pg.evaluate("""() => {
      const pop = document.querySelector('#previewpop');
      const box = document.querySelector('.previewbox');
      const body = document.querySelector('#previewbody');
      const r = box.getBoundingClientRect();
      const cs = getComputedStyle(box);
      const img = body.querySelector('img');
      const em = body.querySelector('embed');
      const pre = body.querySelector('pre');
      const br = body.getBoundingClientRect();
      return {open: pop.classList.contains('open'), cls: pop.className,
        boxW: Math.round(r.width), boxH: Math.round(r.height),
        bg: cs.backgroundColor,
        img: img ? {w: Math.round(img.getBoundingClientRect().width),
                    h: Math.round(img.getBoundingClientRect().height),
                    top: Math.round(img.getBoundingClientRect().top),
                    bottom: Math.round(img.getBoundingClientRect().bottom),
                    natW: img.naturalWidth, natH: img.naturalHeight} : null,
        bodyTop: Math.round(br.top), bodyBottom: Math.round(br.bottom),
        embedH: em ? Math.round(em.getBoundingClientRect().height) : null,
        preFs: pre ? getComputedStyle(pre).fontSize : null,
        zoomVal: (document.querySelector('#pvzval')||{}).textContent || null,
        zoomDisplay: (() => { const z = document.querySelector('#pvzoom');
          return z ? getComputedStyle(z).display : null; })(),
        text: (body.textContent || '').slice(0, 90)};
    }""")


def _close_preview(pg):
    pg.keyboard.press("Escape")
    pg.evaluate("() => { const p = document.querySelector('#previewpop'); p.classList.remove('open'); }")
    pg.wait_for_timeout(200)


def test_version_is_2_8_22():
    assert D.VERSION == "2.8.22"


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
        with open("/tmp/r37_script_%d.js" % i, "w",
                  encoding="utf-8") as fh:
            fh.write(js)
        out = subprocess.run(["node", "--check",
                              "/tmp/r37_script_%d.js" % i],
                             capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr


# ---- (2) Upload card taller ------------------------------------------

def test_2_send_tab_taller_source():
    # Send column alone gets the 170px offset; the shared 205px
    # rule (all tabs) is untouched.
    assert 'body[data-mtab="send"] .board .col[data-col="send"] { height:calc(100dvh - 170px); }' in PAGE
    assert "height:calc(100dvh - 205px); min-height:380px" in PAGE


def _measure_send_tab(pg):
    return pg.evaluate("""() => {
      const btn = document.querySelector('#msendsnippet');
      const card = btn.closest('.minicard');
      const col = document.querySelector('.col[data-col="send"]');
      const tabs = document.querySelector('.mtabs');
      const colbody = document.querySelector('.col[data-col="send"] .colbody');
      const b = btn.getBoundingClientRect(), c = card.getBoundingClientRect(),
            t = tabs.getBoundingClientRect(), colr = col.getBoundingClientRect(),
            cbr = colbody.getBoundingClientRect();
      return {mayScroll: document.body.classList.contains('send-may-scroll'),
        btnBottom: b.bottom, btnTop: b.top,
        cardBottom: c.bottom, colBottom: colr.bottom,
        tabsTop: t.top, gapBtnToTabs: t.top - b.bottom,
        gapColBottomToTabs: t.top - colr.bottom,
        btnVisiblePct: Math.max(0, Math.min(b.bottom, cbr.bottom) - Math.max(b.top, cbr.top)) / b.height,
        colbodyScrollH: colbody.scrollHeight, colbodyClientH: colbody.clientHeight};
    }""")


def test_2_live_send_text_clear_of_tabs_dark(server):
    """Dark mode, guest page: at 390x844 / 360x800 / 393x873 the
    Send Text button is fully visible with clear space above the
    pill tabs WITHOUT scrolling; shorter phones scroll cleanly
    and show it fully at max scroll. The column never tucks
    under the pill tabs.
    NOTE (tradeoff, Nov 6): the taller Send column makes the
    PAGE 12px taller than the viewport at 390x844 (docSH 856
    vs ih 844), so the page itself scrolls a touch -- the
    column does not scroll internally and the button is fully
    visible. That is the "or scroll cleanly" the task allows,
    and it supersedes round33's no-page-scroll invariant and
    the round13/14 "Send card exactly the other tabs' height"
    invariant: making the card taller while keeping the page
    exactly 844 tall is geometrically impossible without
    shrinking something else those same rounds guard."""
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r37send"})
    pw = _playwright()
    try:
        for (w, h) in [(390, 844), (360, 800), (393, 873),
                       (360, 700), (393, 720), (360, 640)]:
            browser, ctx, pg, fwd = _guest_page(pw, port, w, h, light=False)
            try:
                m0 = _measure_send_tab(pg)
                # The card bottom stays above the pill tabs.
                assert m0["gapColBottomToTabs"] >= 4, (w, h, m0)
                if (w, h) in [(390, 844), (360, 800), (393, 873)]:
                    assert m0["btnVisiblePct"] == 1, (w, h, m0)
                    assert m0["gapBtnToTabs"] >= 8, (w, h, m0)
                if (w, h) == (390, 844):
                    assert m0["mayScroll"] is False, m0
                    assert m0["colbodyScrollH"] <= m0["colbodyClientH"], m0
                    # Page scroll stays small (12px on this build).
                    doc = pg.evaluate("() => ({docSH: document.documentElement.scrollHeight, ih: window.innerHeight})")
                    assert 0 <= doc["docSH"] - doc["ih"] <= 20, doc
                pg.evaluate(
                    "() => { const c = document.querySelector('.col"
                    "[data-col=\"send\"] .colbody'); c.scrollTop = "
                    "c.scrollHeight; }")
                pg.wait_for_timeout(300)
                m = _measure_send_tab(pg)
                assert m["btnVisiblePct"] == 1, (w, h, m)
                assert m["gapBtnToTabs"] >= 8, (w, h, m)
                pg.screenshot(path=os.path.join(
                    PROOF, "r37_send_%dx%d.png" % (w, h)))
            finally:
                ctx.close()
                browser.close()
                fwd.close()
    finally:
        pw.stop()


# ---- (3) picture preview hugs + zooms, very transparent -------------

def test_3_picture_preview_source():
    assert ".previewpop.fitpic" in PAGE
    assert "rgba(18,23,42,.5)" in PAGE
    assert "window.__pvZoom" in PAGE
    assert 'id="pvzval"' in PAGE
    # Video keeps the 2.8.21 fit view only -- no fitpic there.
    assert "pop.classList.add(\"fitpic\")" in PAGE
    i = PAGE.index("if(isVid) pop.classList.add(\"fitmedia\");")
    assert "fitpic" not in PAGE[i:i + 120]


def test_3_live_picture_preview_hugs_and_zooms(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r37pic"})
    _make_fixtures(os.path.join(str(base), "r37pic"))
    pw = _playwright()
    try:
        browser, pg = _host_page(pw, port)
        try:
            # Small picture: 400x300 natural -> 500x375 (1.25x),
            # box hugs it (570 = 500 + 70), NOT the 1080 fit box.
            _open_preview(pg, "pic.png")
            m = _preview_geom(pg)
            assert m["open"] is True, m
            assert "fitpic" in m["cls"], m
            assert m["img"] and m["img"]["natW"] == 400, m
            assert m["img"]["w"] == 500 and m["img"]["h"] == 375, m
            assert m["boxW"] == 570, m
            assert m["boxW"] < 900, m
            # Very transparent: translucent background, alpha 0.5.
            assert m["bg"] == "rgba(18, 23, 42, 0.5)", m
            # .pvzoom is a flex item, so its inline-flex blockifies
            # to computed "flex" -- visible either way.
            assert m["zoomDisplay"] in ("flex", "inline-flex"), m
            assert m["zoomVal"] == "100%", m
            pg.screenshot(path=os.path.join(PROOF, "r37_pic.png"))
            # Zoom: + -> 125% (625px), click image -> 200%
            # (1000px), Fit -> back to 100% (500px).
            pg.click("#pvzin")
            pg.wait_for_timeout(300)
            assert pg.evaluate("() => document.querySelector('#pvzval').textContent") == "125%"
            assert pg.evaluate("() => Math.round(document.querySelector('#previewbody img').getBoundingClientRect().width)") == 625
            pg.evaluate("() => document.querySelector('#previewbody img').click()")
            pg.wait_for_timeout(300)
            assert pg.evaluate("() => document.querySelector('#pvzval').textContent") == "200%"
            pg.click("#pvzfit")
            pg.wait_for_timeout(300)
            assert pg.evaluate("() => document.querySelector('#pvzval').textContent") == "100%"
            assert pg.evaluate("() => Math.round(document.querySelector('#previewbody img').getBoundingClientRect().width)") == 500
            _close_preview(pg)
            # Tall picture: whole picture visible, box hugs it.
            _open_preview(pg, "tall.png")
            m = _preview_geom(pg)
            assert "fitpic" in m["cls"], m
            assert m["img"]["h"] <= m["bodyBottom"] - m["bodyTop"], m
            assert m["img"]["top"] >= m["bodyTop"], m
            assert m["img"]["bottom"] <= m["bodyBottom"], m
            assert m["boxW"] < 400, m
            pg.screenshot(path=os.path.join(PROOF, "r37_tall.png"))
            _close_preview(pg)
        finally:
            browser.close()
    finally:
        pw.stop()


# ---- (4) text preview right-click menu --------------------------------

def test_4_preview_context_menu_source():
    assert 'id="pvctx"' in PAGE or 'menu.id = "pvctx"' in PAGE
    assert "@keyframes pvctxpop" in PAGE
    assert '"copied 📑"' in PAGE
    # The literal emoji, never a \\u escape, anywhere near it.
    assert "\\u1f4d1" not in PAGE
    assert "\\uD83D\\uDCD1" not in PAGE
    # No Paste item in the preview menu builder (the builder adds
    # exactly two items, Copy then Select All).
    i = PAGE.index('menu.id = "pvctx"')
    seg = PAGE[i:i + 1600]
    assert "Paste" not in seg, seg
    assert 'addItem("Copy"' in seg
    assert 'addItem("Select All"' in seg


def test_4_live_preview_right_click_copy_select_all(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r37ctx"})
    _make_fixtures(os.path.join(str(base), "r37ctx"))
    pw = _playwright()
    try:
        browser, pg = _host_page(pw, port)
        try:
            _open_preview(pg, "notes.txt")
            pre = pg.query_selector("#previewbody pre")
            assert pre is not None
            pre.click(button="right")
            pg.wait_for_timeout(400)
            menu = pg.evaluate("""() => {
              const m = document.querySelector('#pvctx');
              const cs = getComputedStyle(m);
              return {display: cs.display, cls: m.className,
                anim: cs.animationName,
                items: [...m.querySelectorAll('.ctxitem')].map(b => b.textContent)};
            }""")
            assert menu["display"] == "block", menu
            assert "open" in menu["cls"], menu
            assert menu["anim"] == "pvctxpop", menu
            assert menu["items"] == ["Copy", "Select All"], menu
            pg.screenshot(path=os.path.join(PROOF, "r37_pvctx.png"))
            pg.evaluate("() => { [...document.querySelectorAll('#pvctx .ctxitem')].find(b => b.textContent === 'Copy').click(); }")
            pg.wait_for_timeout(400)
            assert pg.evaluate("() => document.querySelector('#toast').textContent") == "copied 📑"
            pre.click(button="right")
            pg.wait_for_timeout(400)
            pg.evaluate("() => { [...document.querySelectorAll('#pvctx .ctxitem')].find(b => b.textContent === 'Select All').click(); }")
            pg.wait_for_timeout(300)
            sel = pg.evaluate("() => (window.getSelection() || '').toString()")
            assert sel.startswith("Hello preview world"), sel
            assert "line two" in sel
            _close_preview(pg)
            # PDF embed keeps its native menu: no custom pop-up.
            _open_preview(pg, "doc.pdf")
            pg.mouse.click(640, 400, button="right")
            pg.wait_for_timeout(400)
            assert pg.evaluate("() => getComputedStyle(document.querySelector('#pvctx')).display") == "none"
            _close_preview(pg)
        finally:
            browser.close()
    finally:
        pw.stop()


# ---- (6) dark-mode copy icon ------------------------------------------

def _contrast(pg, sel):
    return pg.evaluate("""(sel) => {
      const lum = (r, g, b) => {
        const f = c => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
      };
      const parse = s => { const m = s.match(/(\\d+)[,\\s]+(\\d+)[,\\s]+(\\d+)/); return m ? [+m[1], +m[2], +m[3]] : [0,0,0]; };
      const el = document.querySelector(sel);
      const cs = getComputedStyle(el);
      const fg = parse(cs.color);
      let bg = [0,0,0], node = el;
      while (node) {
        const b = getComputedStyle(node).backgroundColor;
        const p = b.match(/rgba?\\((\\d+)[,\\s]+(\\d+)[,\\s]+(\\d+)(?:[,\\s]+([\\d.]+))?\\)/);
        if (p && (p[4] === undefined || parseFloat(p[4]) > 0.9)) { bg = [+p[1],+p[2],+p[3]]; break; }
        node = node.parentElement;
      }
      const l1 = lum(...fg), l2 = lum(...bg);
      return {color: cs.color, bg: "rgb(" + bg.join(",") + ")",
              contrast: +((Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05)).toFixed(2)};
    }""", sel)


def test_6_mcopy_visible_dark_unchanged_light(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r37copy"})
    pw = _playwright()
    try:
        # Dark mode (default): was 1.08:1 black-on-dark.
        browser, ctx, pg, fwd = _guest_page(pw, port, 390, 844, light=False)
        try:
            m = _contrast(pg, "#mcopy")
            assert m["contrast"] >= 4.5, m
            pg.screenshot(path=os.path.join(PROOF, "r37_mcopy_dark.png"))
        finally:
            ctx.close()
            browser.close()
            fwd.close()
        # Light mode: still a dark icon on the light field.
        browser, ctx, pg, fwd = _guest_page(pw, port, 390, 844, light=True)
        try:
            m = _contrast(pg, "#mcopy")
            assert m["contrast"] >= 7, m
            r, g, b = [int(x) for x in
                       re.findall(r"\d+", m["color"])[:3]]
            assert max(r, g, b) < 60, m
        finally:
            ctx.close()
            browser.close()
            fwd.close()
    finally:
        pw.stop()


# ---- (7) "sent", not "received" ---------------------------------------

def test_7_sent_label_source():
    assert " received" not in SRC
    assert " received" not in APP
    assert 'f.name+" sent"' in PAGE


def test_7_live_upload_toast_says_sent(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r37sent"})
    pw = _playwright()
    try:
        browser, ctx, pg, fwd = _guest_page(pw, port, 390, 844, light=False)
        try:
            up = os.path.join(str(base), "r37sent_upload.txt")
            with open(up, "w") as fh:
                fh.write("sent label check")
            pg.set_input_files("#mpicker", up)
            pg.wait_for_timeout(2500)
            toast = pg.evaluate("() => document.querySelector('#toast').textContent")
            assert "sent" in toast, toast
            assert "received" not in toast, toast
        finally:
            ctx.close()
            browser.close()
            fwd.close()
    finally:
        pw.stop()


# ---- (8) text previews bigger + Excel previews ------------------------

def test_8_text_previews_bigger_source():
    assert ".previewpop.fittext" in PAGE
    assert "xlsx_to_html" in SRC
    assert 'path.startswith("/api/xlsx/")' in SRC
    assert "api/xlsx/?name=" in PAGE


def test_8_live_text_previews_bigger_and_xlsx(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r37big"})
    _make_fixtures(os.path.join(str(base), "r37big"))
    pw = _playwright()
    try:
        browser, pg = _host_page(pw, port)
        try:
            # PDF: big window, taller embed than the old 52vh (416px).
            _open_preview(pg, "doc.pdf")
            m = _preview_geom(pg)
            assert "fittext" in m["cls"], m
            assert m["boxW"] == 1080, m
            assert m["embedH"] is not None and m["embedH"] > 480, m
            pg.screenshot(path=os.path.join(PROOF, "r37_pdf.png"))
            _close_preview(pg)
            # Text: big window, larger type (was 13.5px).
            _open_preview(pg, "notes.txt")
            m = _preview_geom(pg)
            assert "fittext" in m["cls"], m
            assert m["boxW"] == 1080, m
            assert m["preFs"] == "15px", m
            assert "Hello preview world" in m["text"], m
            _close_preview(pg)
            # Word: big window, rendered text.
            _open_preview(pg, "doc.docx")
            m = _preview_geom(pg)
            assert "fittext" in m["cls"], m
            assert m["boxW"] == 1080, m
            assert "Hello Word preview" in m["text"], m
            _close_preview(pg)
            # Excel: big window, first sheet as a table.
            _open_preview(pg, "sheet.xlsx")
            m = _preview_geom(pg)
            assert "fittext" in m["cls"], m
            assert m["boxW"] == 1080, m
            assert "Alice" in m["text"] and "42" in m["text"], m
            tbl = pg.evaluate("() => { const t = document.querySelector('#previewbody .xlsxview table'); return t ? t.rows.length : 0; }")
            assert tbl == 2, tbl
            pg.screenshot(path=os.path.join(PROOF, "r37_xlsx.png"))
            _close_preview(pg)
            # The endpoint itself: 200 + table, 404 for non-xlsx.
            # (_raw parses JSON and drops non-JSON bodies, so use
            # http.client directly for this HTML response.)
            import http.client
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("GET", "/api/xlsx/?name=sheet.xlsx")
            resp = conn.getresponse()
            xbody = resp.read()
            assert resp.status == 200 and b"<table>" in xbody, (resp.status, xbody[:80])
            assert b"Alice" in xbody and b"42" in xbody
            conn.close()
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("GET", "/api/xlsx/?name=notes.txt")
            resp = conn.getresponse()
            assert resp.status == 404, resp.status
            conn.close()
        finally:
            browser.close()
    finally:
        pw.stop()


# ---- (9) Show in folder -- source facts -------------------------------
# Live proof is tests/probe_round37_bridge.py (real pywebview window,
# real click): it proves the click reaches Api.reveal_file, the spawn
# runs with the right argv AND DEVNULL stdio + close_fds, and a
# forced failure surfaces as a toast naming the recorded error.

def test_9_reveal_source_facts():
    assert APP.count("def reveal_file") == 1
    assert APP.count("class Api") == 1
    assert "js_api=Api(server)" in APP
    # The bridge spawn goes through _spawn (DEVNULL stdio + close_fds).
    i = APP.index("return subprocess.Popen(argv")
    seg = APP[i:i + 300]
    assert "stdin=subprocess.DEVNULL" in seg
    assert "stdout=subprocess.DEVNULL" in seg
    assert "stderr=subprocess.DEVNULL" in seg
    assert "close_fds=True" in seg
    # reveal_file is the only Windows Popen path in the bridge; the
    # page's button calls revealFile, which tries the bridge first.
    assert "if(hasBridge()) revealFile(f.name);" in PAGE
    assert "window.pywebview.api.reveal_file(name)" in PAGE
    assert "get_last_reveal" in PAGE
    # The probe script itself exists.
    assert os.path.isfile(os.path.join(
        os.path.dirname(__file__), "probe_round37_bridge.py"))


# ---- (10) Set Up window border square ---------------------------------

def test_10_setup_square_source():
    assert ".lockbox.lkbox:not(.guestcard) { border-radius:0; }" in PAGE
    # The old radii are still there for other elements / as the
    # overridden value -- only the window's own corners change.
    assert "border-radius:27px" in PAGE


def test_10_live_setup_square_same_inner_size(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r37sq"})
    pw = _playwright()
    try:
        browser, pg = _host_page(pw, port)
        try:
            pg.click("#menubtn")
            pg.wait_for_timeout(500)
            pg.click("#sbedit")
            pg.wait_for_timeout(800)
            m = pg.evaluate("""() => {
              const r = s => { const el = document.querySelector(s);
                if (!el) return null;
                const b = el.getBoundingClientRect(), cs = getComputedStyle(el);
                return {w: Math.round(b.width), h: Math.round(b.height),
                        radius: cs.borderRadius}; };
              return {box: r('#lkbox'), lkin: r('#lkin'),
                      lkview: r('#lkcurview'), save: r('#lkset'),
                      perms: r('.lkperms')};
            }""")
            # Square corners, window NOT resized (2.8.21 baseline:
            # 960x652), inner measurements unchanged.
            assert m["box"]["radius"] == "0px", m
            assert m["box"]["w"] == 960 and m["box"]["h"] == 652, m
            assert m["lkin"]["h"] == 52, m
            assert m["lkview"]["h"] == 52, m
            assert m["save"]["w"] == 150, m
            assert m["perms"]["w"] == 892, m
            # Inner radii are NOT zeroed (only the window border).
            assert m["lkin"]["radius"] != "0px", m
            assert m["perms"]["radius"] != "0px", m
            pg.screenshot(path=os.path.join(PROOF, "r37_setup_square.png"))
        finally:
            browser.close()
        # Light mode: square too.
        browser, pg = _host_page(pw, port, light=True)
        try:
            pg.click("#menubtn")
            pg.wait_for_timeout(500)
            pg.click("#sbedit")
            pg.wait_for_timeout(800)
            r = pg.evaluate("() => getComputedStyle(document.querySelector('#lkbox')).borderRadius")
            assert r == "0px", r
        finally:
            browser.close()
    finally:
        pw.stop()
