"""v2.8.25 round (Essef Nov 6, ~3:59 AM) -- web/desktop only.

(1) FILE-ROW BUTTON -- OPEN ICON ALWAYS: the per-file button
    showed the download arrow whenever there was no desktop
    bridge or the file was not yet downloaded on the phone --
    including on the desktop before the bridge arrived after
    first paint (the pywebviewready re-render was the only
    thing flipping it to Open). Essef circled it on
    image-47.png: the button's job is Open. It now ALWAYS
    shows the previous open / external-link icon (SVG.open --
    the box + NE arrow) with title "Open", on every surface.
    The click is unchanged (fileTap: bridge open_file on the
    desktop, Download then Open elsewhere -- never the in-app
    preview, which stays on the file NAME / thumbnail click).
    No new buttons; the note-download toggle and the preview
    window's Download button are untouched.
(2) UPLOADING PILL -- SAME SIZE AS DEVICES CONNECTED: the
    uploading pill (.upfloat, 64px ring -> ~76px tall) was too
    big. It is now exactly the Devices Connected pill's size
    (.devpill .status): height 36px, padding 0 14px, gap 6px,
    name font 13px. Ring 28px (number font 27 in viewBox units
    so it still reads), X 20px. Ring + count + name + X still
    fit and work; X still cancels the upload; the pill still
    sits at the top of the Shared Files card with its bottom
    edge touching the card's top edge.

Superseded round39 assertions (Essef's new instructions
replace them, NOT regressions -- see the notes above):
- round39 test_2_open_button_source: the title conditional
  '(hasBridge() || isDownloaded(f)) ? "Open" : "Download"'
  is gone -- the title is always "Open".
- round39 test_3_live_ring_top_and_cancel: the X button is
  now 20x20 (was 28x28) and the pill is 36px tall (was
  ~76px). Position (bottom edge touching the card top),
  solidity, colours and the cancel flow are unchanged.
- round8 test_desktop_files_delete_label and round9
  test_desktop_delete_files_text_only still fail, but only
  on their LABEL half now: they want the inner text
  "Delete files", while item 3 below keeps the current
  short label "Delete" (Essef: label must not change).
  Their NO-ICON half passes again with item 3.

(3) DESKTOP DELETE BUTTON -- TRASH ICON REVERTED: the
    trash icon on the desktop Shared Files Delete button
    was ADDED in 2.8.5 ("icons before text", Essef Nov 3)
    -- before that the button was TEXT-ONLY (v2.7.93 round9:
    text only, "Delete files", no trash icon), and the
    trash-2 SVG itself never changed in any version from
    2.7.50 to 2.8.24 (byte-identical in every shipped zip),
    so the icon's addition WAS the change. 2.8.25 reverts
    it: the desktop Delete button is text-only "Delete"
    again -- icon removed, label / colour / size / position
    untouched. Open and Change keep their icons byte-
    identical to 2.8.24. The mobile icon-only header button
    keeps _SVG_TRASH (it has no label; removing its icon
    would leave a blank red square).
"""
import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
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

PROOF = "/home/hatch/workspace/dropit-proof-round40"
os.makedirs(PROOF, exist_ok=True)

# SVG.open (external-link: box + NE arrow) vs SVG.dl (download
# arrow) -- the two path fingerprints that tell them apart.
OPEN_PATH = "15 3 21 3 21 9"
DL_PATH = "7 10 12 15 17 10"


def test_version_is_2_8_25():
    assert D.VERSION == "2.8.25"


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
        with open("/tmp/r40_script_%d.js" % i, "w",
                  encoding="utf-8") as fh:
            fh.write(js)
        out = subprocess.run(["node", "--check",
                              "/tmp/r40_script_%d.js" % i],
                             capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr


# ---- (1) file-row button: open icon always -----------------------------
def test_1_open_icon_source():
    # The file-row button is unconditional now: always the
    # external-link icon, always titled "Open".
    assert 'title="Open" style="--c1:#7dd3fc;--c2:#4f46e5">${SVG.open}' in PAGE
    assert '(hasBridge() || isDownloaded(f)) ? SVG.open : SVG.dl' not in PAGE
    assert 'title="${(hasBridge() || isDownloaded(f)) ? "Open" : "Download"}"' not in PAGE
    # SVG.open is the previous external-link icon (box + NE
    # arrow), unchanged.
    m = re.search(r"open: '(<svg[^>]*>.*?)',", PAGE)
    assert m, "SVG.open not found"
    assert OPEN_PATH in m.group(1), m.group(1)
    assert "M18 13v6a2 2 0 01-2 2H5" in m.group(1), m.group(1)
    # The click still goes through fileTap (direct open), and
    # the bridge + reveal paths still exist for it / the
    # right-click menu.
    assert "fileTap(f, b); });" in PAGE
    assert "function revealFile(name){" in PAGE
    assert "window.pywebview.api.open_file(name)" in PAGE
    assert 'addItem("Show in folder", () => revealFile(frowEl.dataset.frow));' in PAGE
    # Untouched neighbours: the note-download toggle still
    # switches open/download, the preview keeps its Download.
    assert "btn.innerHTML = opened ? SVG.open : SVG.dl;" in PAGE
    assert 'id="previewdl"' in PAGE


def _row_buttons(pg):
    return pg.evaluate("""() => [...document.querySelectorAll('.frow [data-dl]')].map(b => ({
      name: b.dataset.name, title: b.title,
      html: b.innerHTML }))""")


def test_1_live_open_icon_everywhere(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r40open"})
    _make_fixtures(os.path.join(str(base), "r40open"))
    pw = _playwright()
    try:
        # Plain host page: NO bridge, NOTHING downloaded -- the
        # state that used to show the download arrow on every
        # row. Now every row shows the open icon, titled Open.
        browser, pg = _host_page(pw, port)
        try:
            pg.wait_for_timeout(1500)
            rows = _row_buttons(pg)
            assert len(rows) == 6, rows
            for r in rows:
                assert r["title"] == "Open", r
                assert OPEN_PATH in r["html"], r
                assert DL_PATH not in r["html"], r
            # The sheet.xlsx row in particular (Essef's circled
            # row): open icon, not the download arrow.
            sheet = [r for r in rows if r["name"] == "sheet.xlsx"]
            assert len(sheet) == 1 and sheet[0]["title"] == "Open", rows
            pg.screenshot(path=os.path.join(PROOF, "r40_rows_open_icon.png"))
            # No bridge, not downloaded: clicking the row button
            # starts the Download-then-Open flow (the download
            # confirm dialog), NOT the in-app preview.
            pg.click('.frow[data-frow="notes.txt"] [data-dl]')
            pg.wait_for_timeout(1500)
            assert pg.evaluate(
                "() => document.querySelector('#cfdlg').classList.contains('open')"
            ) is True
            assert pg.evaluate(
                "() => document.querySelector('#previewpop').classList.contains('open')"
            ) is False
            pg.click("#cfno")
            pg.wait_for_timeout(400)
            # Clicking the file NAME still previews in-page.
            pg.evaluate("""() => {
              const row = [...document.querySelectorAll('.frow')].find(r => r.dataset.frow === 'pic.png');
              row.querySelector('.fname').click(); }""")
            pg.wait_for_timeout(800)
            assert pg.evaluate(
                "() => document.querySelector('#previewpop').classList.contains('open')"
            ) is True
            _close_preview(pg)
        finally:
            browser.close()
        # Desktop (bridge faked): the same open icon, and the
        # click opens directly via bridge open_file -- no
        # preview, no reveal.
        browser, pg = _host_page(pw, port)
        try:
            pg.evaluate("""() => {
              window.__bridgeCalls = [];
              window.pywebview = {api: new Proxy({}, {get: (t, k) => {
                if (k === 'open_file') return async (n) => {
                  window.__bridgeCalls.push(['open_file', n]); return true; };
                if (k === 'reveal_file') return async (n) => {
                  window.__bridgeCalls.push(['reveal_file', n]); return true; };
                return async () => null;
              }})};
              markPcApp();
              lastFilesSig = null; loadFiles();
            }""")
            pg.wait_for_timeout(800)
            rows = _row_buttons(pg)
            assert len(rows) == 6, rows
            for r in rows:
                assert r["title"] == "Open", r
                assert OPEN_PATH in r["html"], r
                assert DL_PATH not in r["html"], r
            pg.click('.frow[data-frow="sheet.xlsx"] [data-dl]')
            pg.wait_for_timeout(600)
            calls = pg.evaluate("() => window.__bridgeCalls")
            assert calls == [["open_file", "sheet.xlsx"]], calls
            assert pg.evaluate(
                "() => document.querySelector('#previewpop').classList.contains('open')"
            ) is False
            # Right-click menu still offers "Show in folder".
            row = pg.query_selector('.frow[data-frow="sheet.xlsx"]')
            box = row.bounding_box()
            pg.mouse.click(box["x"] + 40, box["y"] + 20, button="right")
            pg.wait_for_timeout(500)
            menu = pg.evaluate("""() => {
              const m = document.querySelector('#ctxmenu');
              return {display: getComputedStyle(m).display,
                items: [...m.querySelectorAll('.ctxitem')].map(b => b.textContent)}; }""")
            assert menu["display"] == "block", menu
            assert menu["items"] == ["Show in folder"], menu
        finally:
            browser.close()
    finally:
        pw.stop()


# ---- (2) uploading pill: Devices Connected size ------------------------
def test_2_pill_source():
    # .upfloat matches .devpill .status exactly: 36px tall,
    # 0 14px padding, 6px gap; name still 13px.
    assert ".upfloat { display:none; position:fixed; left:50%; transform:translateX(-50%); top:96px; z-index:300; align-items:center; gap:6px;" in PAGE
    assert "border-radius:999px; height:36px; padding:0 14px;" in PAGE
    assert ".devpill .status { background:#12172a; border:none; border-radius:999px; padding:0 14px; height:36px; display:flex; align-items:center; gap:6px;" in PAGE
    # Ring 28px (was 64px), X 20px (was 28px), number font
    # bumped in viewBox units so it still reads at 28px.
    assert ".upring { width:28px; height:28px;" in PAGE
    assert ".upring { width:64px; height:64px;" not in PAGE
    assert ".upring-num { fill:var(--txt); font-size:27px;" in PAGE
    assert ".upcancel { flex:none; width:20px; height:20px;" in PAGE
    assert ".upcancel { flex:none; width:28px; height:28px;" not in PAGE
    assert '.upfloat-name { max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:13px;' in PAGE
    # The ring math is untouched (same viewBox, same dasharray).
    assert "stroke-dasharray:163.36" in PAGE
    assert "const c = 163.36;" in PAGE
    assert 'id="upringnum" x="32" y="41"' in PAGE
    # _upShow's fallback height follows the new size.
    assert "const ph = f.offsetHeight || 36;" in PAGE


def _pill_measure(pg):
    return pg.evaluate("""() => {
      const f = document.querySelector('#upfloat');
      const r = f.getBoundingClientRect();
      const cs = getComputedStyle(f);
      const ring = document.querySelector('.upring').getBoundingClientRect();
      const x = document.querySelector('#upcancel');
      const xr = x.getBoundingClientRect();
      const name = document.querySelector('#upfloatname');
      const dev = document.querySelector('#statusdiv');
      const dr = dev.getBoundingClientRect();
      const ds = getComputedStyle(dev);
      const col = document.querySelector('.col[data-col="files"]');
      const cr = col.getBoundingClientRect();
      const foot = document.querySelector('footer').getBoundingClientRect();
      return {show: f.classList.contains('show'),
        up: {h: Math.round(r.height), w: Math.round(r.width),
             padL: cs.paddingLeft, padR: cs.paddingRight,
             padT: cs.paddingTop, padB: cs.paddingBottom,
             gap: cs.gap, bottom: Math.round(r.bottom),
             name: name.textContent,
             nameFont: getComputedStyle(name).fontSize,
             bg: cs.backgroundColor},
        ring: {w: Math.round(ring.width), h: Math.round(ring.height)},
        xBtn: {w: Math.round(xr.width), h: Math.round(xr.height),
               bg: getComputedStyle(x).backgroundColor,
               color: getComputedStyle(x).color},
        dev: {h: Math.round(dr.height),
              padL: ds.paddingLeft, padR: ds.paddingRight,
              gap: ds.gap, font: getComputedStyle(document.querySelector('#statustext')).fontSize,
              text: document.querySelector('#statustext').textContent},
        filesTop: Math.round(cr.top), footerTop: Math.round(foot.top)};
    }""")


def _held_upload(fname, size_mb=5):
    path = "/tmp/r40_upload_%s" % fname
    with open(path, "wb") as fh:
        fh.write(os.urandom(size_mb * 1024 * 1024))
    return path


def test_2_live_pill_matches_devices_dark(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r40pill"})
    _make_fixtures(os.path.join(str(base), "r40pill"))
    pw = _playwright()
    try:
        browser, pg = _host_page(pw, port)
        try:
            pg.route("**/api/upload", lambda route: None)
            up = _held_upload("big_dark.bin")
            pg.set_input_files("#picker", up)
            pg.wait_for_timeout(1200)
            m = _pill_measure(pg)
            assert m["show"] is True, m
            # SAME SIZE as Devices Connected, measured live.
            assert m["up"]["h"] == 36, m
            assert m["dev"]["h"] == 36, m
            assert m["up"]["h"] == m["dev"]["h"], m
            assert m["up"]["padL"] == m["dev"]["padL"] == "14px", m
            assert m["up"]["padR"] == m["dev"]["padR"] == "14px", m
            assert m["up"]["padT"] == "0px" and m["up"]["padB"] == "0px", m
            assert m["up"]["gap"] == m["dev"]["gap"] == "6px", m
            assert m["up"]["nameFont"] == m["dev"]["font"] == "13px", m
            # The shrunk contents still fit and read.
            assert m["ring"] == {"w": 28, "h": 28}, m
            assert m["xBtn"]["w"] == 20 and m["xBtn"]["h"] == 20, m
            assert m["xBtn"]["bg"] == "rgb(239, 68, 68)", m
            assert m["xBtn"]["color"] == "rgb(255, 255, 255)", m
            assert m["up"]["name"] == "r40_upload_big_dark.bin", m
            assert m["up"]["bg"] == "rgb(18, 23, 42)", m
            # Still at the top of the Shared Files card, bottom
            # edge touching the card's top edge, clear of the
            # footer (2.8.24 positioning, unchanged).
            assert abs(m["up"]["bottom"] - m["filesTop"]) <= 6, m
            assert m["up"]["bottom"] < m["footerTop"] - 100, m
            pg.screenshot(path=os.path.join(PROOF, "r40_pill_dark.png"))
            # Cancel still works: toast, ring hides, queue
            # empties, the file is never saved.
            pg.click("#upcancel")
            pg.wait_for_timeout(400)
            assert pg.evaluate(
                "() => document.querySelector('#toast').textContent") == "Upload cancelled"
            pg.wait_for_timeout(1600)
            assert pg.evaluate(
                "() => !document.querySelector('#upfloat').classList.contains('show')")
            st = pg.evaluate("() => ({pending: window.__upQ.pending.length, cancelled: window.__upQ.cancelled})")
            assert st == {"pending": 0, "cancelled": True}, st
            names = pg.evaluate("() => fetch('/api/files').then(r => r.json()).then(fs => fs.map(f => f.name))")
            assert not any(n.startswith("r40_upload_big_") for n in names), names
            pg.unroute("**/api/upload")
        finally:
            browser.close()
    finally:
        pw.stop()


def test_2_live_pill_matches_devices_light(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r40pilll"})
    _make_fixtures(os.path.join(str(base), "r40pilll"))
    pw = _playwright()
    try:
        browser, pg = _host_page(pw, port, light=True)
        try:
            pg.route("**/api/upload", lambda route: None)
            up = _held_upload("big_light.bin")
            pg.set_input_files("#picker", up)
            pg.wait_for_timeout(1200)
            m = _pill_measure(pg)
            assert m["show"] is True, m
            assert m["up"]["h"] == 36 and m["dev"]["h"] == 36, m
            assert m["up"]["padL"] == m["dev"]["padL"] == "14px", m
            assert m["up"]["padR"] == m["dev"]["padR"] == "14px", m
            assert m["up"]["gap"] == m["dev"]["gap"] == "6px", m
            assert m["up"]["nameFont"] == m["dev"]["font"] == "13px", m
            assert m["ring"] == {"w": 28, "h": 28}, m
            assert m["xBtn"]["w"] == 20 and m["xBtn"]["h"] == 20, m
            assert m["up"]["name"] == "r40_upload_big_light.bin", m
            assert m["up"]["bg"] == "rgb(255, 255, 255)", m
            assert abs(m["up"]["bottom"] - m["filesTop"]) <= 6, m
            pg.screenshot(path=os.path.join(PROOF, "r40_pill_light.png"))
            pg.click("#upcancel")
            pg.wait_for_timeout(1800)
            assert pg.evaluate(
                "() => !document.querySelector('#upfloat').classList.contains('show')")
            pg.unroute("**/api/upload")
        finally:
            browser.close()
    finally:
        pw.stop()


# ---- (3) desktop Delete button: trash icon reverted --------------------
_V24_ZIP = "/home/hatch/workspace/dropit-desktop-v2.8.24.zip"


def _v24_src():
    with zipfile.ZipFile(_V24_ZIP) as zf:
        return zf.read("dropit/dropit.py").decode("utf-8")


def test_3_delete_icon_source():
    v24 = _v24_src()
    # The history, established from the shipped zips: the
    # trash-2 SVG is byte-identical in every version from
    # 2.7.50 to 2.8.24, and the desktop Delete button was
    # text-only ("Delete files", no icon) through 2.8.4 --
    # the icon was ADDED in 2.8.5.
    t24 = re.search(r"_SVG_TRASH = '([^']*)'", v24).group(1)
    t25 = re.search(r"_SVG_TRASH = '([^']*)'", SRC).group(1)
    assert t24 == t25
    assert "M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" in t25
    # Desktop branch: Delete is text-only again -- no <svg>.
    desk = re.search(r"if desktop and not _mobile:\n(.*?)else:", SRC, re.S)
    assert desk, "desktop branch not found"
    dm = re.search(r'id="delallbtn"[^>]*>(.*?)</button>', desk.group(1))
    assert dm, "desktop delallbtn missing"
    assert dm.group(1) == "Delete", dm.group(1)
    assert "<svg" not in dm.group(1) and "polyline" not in dm.group(1)
    # Same button otherwise: class, style, data-tip untouched.
    assert 'class="btn dangergrad" id="delallbtn" style="display:none" data-tip="Delete files"' in desk.group(1)
    # Open / Change byte-identical to 2.8.24 (whole button).
    for bid in ("openfolder", "changefolder"):
        m24 = re.search(r'id="%s"[^>]*>.*?</button>' % bid, v24)
        m25 = re.search(r'id="%s"[^>]*>.*?</button>' % bid, SRC)
        assert m24 and m25, bid
        assert m24.group(0) == m25.group(0), bid
    # Mobile header button keeps its trash icon (icon-only by
    # design -- removing it would leave a blank button).
    mob = SRC[desk.end():]
    mm = re.search(r'id="delallbtn"[^>]*>(.*?)</button>', mob)
    assert mm and "_SVG_TRASH" in mm.group(1), mm
    # Shared Texts Delete keeps its trash icon too.
    nm = re.search(r'id="delallnotesbtn"[^>]*>(.*?)</button>', PAGE)
    assert nm and "polyline" in nm.group(1), nm
    # The 2.8.24 desktop Delete HAD the icon (this is what
    # 2.8.25 reverts).
    dm24 = re.search(r'id="delallbtn"[^>]*>(.*?)</button>', v24)
    assert dm24 and "<svg" in dm24.group(1) and "polyline" in dm24.group(1)


def _load_v24_module():
    dest = "/tmp/r40-2824/dropit/dropit.py"
    if not os.path.exists(dest):
        os.makedirs("/tmp/r40-2824/dropit", exist_ok=True)
        with zipfile.ZipFile(_V24_ZIP) as zf:
            zf.extract("dropit/dropit.py", "/tmp/r40-2824")
    if "/tmp/r40-2824/dropit" not in sys.path:
        sys.path.insert(0, "/tmp/r40-2824/dropit")
    spec = importlib.util.spec_from_file_location("dropit24", dest)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _serve_desktop(mod, base, port, name):
    import http.client
    srv = mod.make_server(port, base, desktop=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("POST", "/api/setlink", body=json.dumps({"name": name}),
              headers={"Content-Type": "application/json"})
    assert c.getresponse().status == 200
    c.close()
    return srv


def _fbtnrow_measure(pg):
    return pg.evaluate("""() => {
      const g = (sel) => { const el = document.querySelector(sel);
        if (!el) return null;
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        return {html: el.outerHTML, inner: el.innerHTML,
          x: Math.round(r.x), y: Math.round(r.y),
          w: Math.round(r.width), h: Math.round(r.height),
          bg: cs.backgroundColor, color: cs.color,
          fontSize: cs.fontSize, padding: cs.padding,
          label: el.textContent.trim(),
          visible: cs.display !== 'none' && r.width > 0}; };
      const row = document.querySelector('.fbtnrow');
      const rr = row.getBoundingClientRect();
      return {open: g('#openfolder'), change: g('#changefolder'),
        del: g('#delallbtn'),
        row: {x: Math.round(rr.x), y: Math.round(rr.y),
              w: Math.round(rr.width), h: Math.round(rr.height)}};
    }""")


def test_3_live_desktop_row_matches_2824_except_delete_icon(tmp_path):
    from test_link_folders import _free_port
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/home/hatch/.cache/ms-playwright"
    real_home = os.environ.get("HOME", "/home/hatch")
    v24mod = _load_v24_module()
    pw = _playwright()
    results = {}
    try:
        for tag, mod, link in (("24", v24mod, "r40del24"), ("25", D, "r40del25")):
            home = str(tmp_path / ("home" + tag))
            base = str(tmp_path / ("base" + tag))
            os.makedirs(os.path.join(home, ".config", "DropIt"), exist_ok=True)
            os.makedirs(base, exist_ok=True)
            os.environ["HOME"] = home
            os.makedirs(os.path.join(base, link), exist_ok=True)
            _make_fixtures(os.path.join(base, link))
            port = _free_port()
            srv = _serve_desktop(mod, base, port, link)
            try:
                browser = pw.chromium.launch(args=["--no-proxy-server"])
                try:
                    pg = browser.new_page(viewport={"width": 1280, "height": 800})
                    pg.goto("http://127.0.0.1:%d/" % port)
                    pg.wait_for_timeout(2200)
                    assert pg.evaluate(
                        "() => !!document.querySelector('.fbtnrow')")
                    results[tag] = _fbtnrow_measure(pg)
                    pg.screenshot(path=os.path.join(
                        PROOF, "r40_fbtnrow_2.8.%s.png" % tag))
                    if tag == "25":
                        # Delete still works: opens selection mode.
                        pg.click("#delallbtn")
                        pg.wait_for_timeout(600)
                        assert pg.evaluate(
                            "() => document.querySelector('#files').classList.contains('selmode')"
                        ) is True
                        assert pg.evaluate(
                            "() => document.querySelector('#delbar').classList.contains('show')"
                        ) is True
                        pg.screenshot(path=os.path.join(
                            PROOF, "r40_delete_selmode.png"))
                finally:
                    browser.close()
            finally:
                srv.shutdown()
                srv.server_close()
    finally:
        os.environ["HOME"] = real_home
        pw.stop()
    m24, m25 = results["24"], results["25"]
    # Open / Change: byte-identical HTML AND identical geometry.
    for key in ("open", "change"):
        assert m24[key]["html"] == m25[key]["html"], key
        for f in ("x", "y", "w", "h", "bg", "color", "fontSize", "padding"):
            assert m24[key][f] == m25[key][f], (key, f, m24[key], m25[key])
        assert m24[key]["visible"] is True and m25[key]["visible"] is True
    # The row itself is unmoved.
    assert m24["row"] == m25["row"], (m24["row"], m25["row"])
    # Delete: ONLY the icon differs -- same label, colours,
    # padding, position and size; inner is now text-only.
    assert m25["del"]["inner"] == "Delete", m25["del"]
    assert "<svg" not in m25["del"]["inner"]
    assert "<svg" in m24["del"]["inner"]
    assert m25["del"]["label"] == m24["del"]["label"] == "Delete"
    for f in ("x", "y", "w", "h", "bg", "color", "fontSize", "padding"):
        assert m24["del"][f] == m25["del"][f], (f, m24["del"], m25["del"])
    assert m24["del"]["visible"] is True and m25["del"]["visible"] is True
