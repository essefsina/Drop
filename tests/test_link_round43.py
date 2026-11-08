"""v2.8.28 round (Essef Nov 6, ~3:38 PM) -- web/desktop + APK.

UPLOADING PILL REFINEMENTS, ONLY:
1. Pill slightly LESS WIDE: the SAME WIDTH as the Devices
   Connected pill (#statusdiv), WITH the cancel X included --
   _upShow copies the Devices pill's live width onto the pill,
   so it matches in every state (the Devices pill's width
   follows its text). At 1280px with "No devices connected"
   that is 192px (was a fixed 272px).
2. Position slightly HIGHER -- LINED WITH the search button:
   when the pill's vertical band is near the search button's,
   its centre is snapped to the button's centre (52px at
   1280px, was 58px). It stays centred on the files column
   (centred and aligned with the Devices pill: same width,
   same 36px height).
3. Unchanged: 36px tall, same padding/font/ring, X still
   cancels, >= 8px clear of the search button (2.8.27), long
   names still ellipsise inside the fixed width.
"""
import ast
import importlib.util
import os
import re
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
from test_link_round2 import server, _raw  # noqa: F401,E402
from test_link_round36 import _playwright  # noqa: E402
from test_link_round37 import _host_page, _make_fixtures  # noqa: E402
from test_link_round40 import _held_upload  # noqa: E402

PAGE = D.PAGE
SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py"),
           encoding="utf-8").read()

PROOF = "/home/hatch/workspace/dropit-proof-round43"
os.makedirs(PROOF, exist_ok=True)


def test_version_is_2_8_28():
    assert D.VERSION == "2.8.28"


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
        with open("/tmp/r43_script_%d.js" % i, "w",
                  encoding="utf-8") as fh:
            fh.write(js)
        out = subprocess.run(["node", "--check",
                              "/tmp/r43_script_%d.js" % i],
                             capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr


def _pill_geometry(pg):
    """Live rects: pill, Devices pill, search button, files col."""
    return pg.evaluate("""() => {
      const r = e => { if(!e) return null; const b = e.getBoundingClientRect();
        return {left: Math.round(b.left), top: Math.round(b.top),
                right: Math.round(b.right), bottom: Math.round(b.bottom),
                w: Math.round(b.width), h: Math.round(b.height),
                cx: Math.round(b.left + b.width/2),
                cy: Math.round(b.top + b.height/2)}; };
      const f = document.querySelector('#upfloat');
      const s = document.querySelector('#askbtn');
      const fr = f.getBoundingClientRect();
      const sr = s.getBoundingClientRect();
      const ox = Math.min(fr.right, sr.right) - Math.max(fr.left, sr.left);
      const oy = Math.min(fr.bottom, sr.bottom) - Math.max(fr.top, sr.top);
      let gap;
      if (ox > 0 && oy > 0) { gap = -Math.min(ox, oy); }
      else { gap = Math.round(Math.hypot(ox < 0 ? -ox : 0, oy < 0 ? -oy : 0)); }
      const nm = document.querySelector('#upfloatname');
      return {gap: gap, pill: r(f), dev: r(document.querySelector('#statusdiv')),
              search: r(s), files: r(document.querySelector('.col[data-col="files"]')),
              searchVisible: sr.width > 0 && sr.height > 0,
              pillVisible: f.classList.contains('show'),
              nameEllipsised: nm.scrollWidth > nm.clientWidth,
              nameText: nm.textContent,
              devText: document.querySelector('#statustext').textContent};
    }""")


def test_live_pill_matches_devices_and_lines_with_search(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r43pill"})
    _make_fixtures(os.path.join(str(base), "r43pill"))
    pw = _playwright()
    results = {}
    try:
        for width, height in [(1280, 800), (1024, 768),
                              (390, 844), (360, 640)]:
            for light in (False, True):
                browser, pg = _host_page(pw, port, width, height,
                                         light=light)
                try:
                    pg.route("**/api/upload", lambda route: None)
                    pg.set_input_files(
                        "#picker", _held_upload("r43_upload_short.bin"))
                    pg.wait_for_timeout(1200)
                    m = _pill_geometry(pg)
                    key = "%dx%d_%s" % (width, height,
                                        "light" if light else "dark")
                    results[key] = m
                    print("GEOM %s: %s" % (key, m))
                    assert m["pillVisible"] is True, m
                    # Still 36px tall, same height as Devices pill.
                    assert m["pill"]["h"] == 36, m
                    assert m["dev"]["h"] == 36, m
                    # (1) SAME WIDTH as Devices Connected pill,
                    # X included -- measured live.
                    assert m["pill"]["w"] == m["dev"]["w"], m
                    assert m["pill"]["w"] < 272, m  # slightly less wide
                    if m["searchVisible"]:
                        # (2) Centred on the files column, at
                        # every width where the column is laid out.
                        assert m["pill"]["cx"] == m["files"]["cx"], m
                        # (3) Still >= 8px clear of the search
                        # button (2.8.27 clearance holds).
                        assert m["gap"] >= 8, m
                        if m["files"]["top"] < 200:
                            # Desktop top-row layout: the pill sits
                            # just under the topbar, so it lines up
                            # with the search button.
                            # (2) LINED WITH the search button:
                            # same vertical centre.
                            assert m["pill"]["cy"] == m["search"]["cy"], m
                            # Card gap grew 12px -> 18px with the
                            # 6px upward snap (files top 88, pill
                            # bottom 70).
                            assert m["files"]["top"] - m["pill"]["bottom"] == 18, m
                        else:
                            # Stacked layout (e.g. 1024px): the
                            # files column is far down the page, so
                            # lining the pill up with the topbar
                            # search button would detach it from
                            # its card. It keeps its card-relative
                            # position (12px above the card top).
                            assert m["files"]["top"] - m["pill"]["bottom"] == 12, m
                    else:
                        # Mobile: no search button, fallback
                        # top-centre position, unchanged.
                        assert m["pill"]["top"] == 88, m
                    if width == 1280 and not light:
                        pg.screenshot(path=os.path.join(
                            PROOF, "r43_pill_1280.png"))
                    pg.click("#upcancel")
                    pg.wait_for_timeout(1200)
                    pg.unroute("**/api/upload")
                finally:
                    browser.close()
    finally:
        pw.stop()
    print("ALL: " + ", ".join(
        "%s pill=%dx%d dev=%d cy=%d/%d gap=%d" % (
            k, v["pill"]["w"], v["pill"]["h"], v["dev"]["w"],
            v["pill"]["cy"], v["search"]["cy"], v["gap"])
        for k, v in results.items()))


def test_live_long_name_never_grows_pill(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r43pill"})
    _make_fixtures(os.path.join(str(base), "r43pill"))
    pw = _playwright()
    try:
        browser, pg = _host_page(pw, port, 1280, 800)
        try:
            pg.route("**/api/upload", lambda route: None)
            long_name = ("a" * 70 +
                         "_very_long_file_name_that_keeps_going.bin")
            assert len(long_name) >= 100
            pg.set_input_files("#picker", _held_upload(long_name))
            pg.wait_for_timeout(1200)
            m = _pill_geometry(pg)
            print("LONG-NAME GEOM: %s" % m)
            assert m["pillVisible"] is True, m
            # Same width as Devices pill, identical to the
            # short-name run -- the long name ellipsises
            # inside instead of stretching the pill.
            assert m["pill"]["w"] == m["dev"]["w"], m
            assert m["pill"]["h"] == 36, m
            assert m["nameEllipsised"] is True, m
            assert m["pill"]["cy"] == m["search"]["cy"], m
            assert m["gap"] >= 8, m
            pg.screenshot(path=os.path.join(PROOF, "r43_pill_long.png"))
            pg.click("#upcancel")
            pg.wait_for_timeout(1200)
            pg.unroute("**/api/upload")
        finally:
            browser.close()
    finally:
        pw.stop()
