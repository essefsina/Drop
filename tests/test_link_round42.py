"""v2.8.27 round (Essef Nov 6, ~2:28 PM) -- web/desktop + APK.

UPLOADING PILL MUST NOT TOUCH THE SEARCH BUTTON: the pill
(.upfloat) sits at the top of the Shared Files card, centred
on the files column, 12px above the card top (v2.8.26). The
search button (#askbtn, magnifier, top-right of the topbar)
is nearby, so the rendered edge-to-edge gap between the pill
and the search button is measured live at 1280px, 1024px,
390px and 360px widths, dark + light. The gap must be >= 8px
at every width. The pill itself is unchanged: 36px tall,
272px wide, 12px gap above the files card.
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
from test_link_round40 import _pill_measure, _held_upload  # noqa: E402

PAGE = D.PAGE
SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py"),
           encoding="utf-8").read()

PROOF = "/home/hatch/workspace/dropit-proof-round42"
os.makedirs(PROOF, exist_ok=True)


def test_version_is_2_8_27():
    assert D.VERSION == "2.8.27"


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
        with open("/tmp/r42_script_%d.js" % i, "w",
                  encoding="utf-8") as fh:
            fh.write(js)
        out = subprocess.run(["node", "--check",
                              "/tmp/r42_script_%d.js" % i],
                             capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr


def _pill_vs_search_gap(pg):
    """Edge-to-edge gap (px) between #upfloat and #askbtn.

    Positive = clear of each other; 0 = touching; negative =
    overlapping (by that many px). Also returns both rects and
    the pill-vs-files-card gap, so a failure says exactly
    where the pill sits.
    """
    return pg.evaluate("""() => {
      const f = document.querySelector('#upfloat');
      const s = document.querySelector('#askbtn');
      const fr = f.getBoundingClientRect();
      const sr = s.getBoundingClientRect();
      const col = document.querySelector('.col[data-col="files"]');
      const cr = col.getBoundingClientRect();
      const ox = Math.min(fr.right, sr.right) - Math.max(fr.left, sr.left);
      const oy = Math.min(fr.bottom, sr.bottom) - Math.max(fr.top, sr.top);
      let gap;
      if (ox > 0 && oy > 0) {
        gap = -Math.min(ox, oy);  // overlapping
      } else {
        const dx = ox < 0 ? -ox : 0;
        const dy = oy < 0 ? -oy : 0;
        gap = Math.round(Math.hypot(dx, dy));
      }
      const r = x => ({left: Math.round(x.left), top: Math.round(x.top),
                       right: Math.round(x.right), bottom: Math.round(x.bottom),
                       w: Math.round(x.width), h: Math.round(x.height)});
      return {gap: gap, pill: r(fr), search: r(sr),
              filesTop: Math.round(cr.top),
              cardGap: Math.round(cr.top - fr.bottom),
              pillVisible: f.classList.contains('show'),
              searchVisible: sr.width > 0 && sr.height > 0};
    }""")


def test_live_pill_clear_of_search_button(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r42pill"})
    _make_fixtures(os.path.join(str(base), "r42pill"))
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
                        "#picker", _held_upload("r42_upload_gap.bin"))
                    pg.wait_for_timeout(1200)
                    m = _pill_vs_search_gap(pg)
                    key = "%dx%d_%s" % (width, height,
                                        "light" if light else "dark")
                    results[key] = m
                    print("GAP %s: %s" % (key, m))
                    assert m["pillVisible"] is True, m
                    # Pill itself unchanged: 36px tall, 272px wide.
                    assert m["pill"]["h"] == 36, m
                    assert m["pill"]["w"] == 272, m
                    if m["searchVisible"]:
                        # 12px clear gap above the files card
                        # (only measurable when the files column
                        # is laid out, i.e. desktop widths).
                        assert m["cardGap"] == 12, m
                        # The point of this round: at least 8px
                        # clear of the search button at every
                        # width/theme where it is rendered.
                        assert m["gap"] >= 8, m
                    else:
                        # Mobile widths: the topbar (and its
                        # search button) is not rendered at all
                        # -- there is nothing for the pill to
                        # touch. The pill falls back to
                        # top-centre (top 88px), as designed.
                        assert m["pill"]["top"] == 88, m
                    if width in (1280, 1024) and not light:
                        pg.screenshot(path=os.path.join(
                            PROOF, "r42_pill_search_%d.png" % width))
                    pg.click("#upcancel")
                    pg.wait_for_timeout(1200)
                    pg.unroute("**/api/upload")
                finally:
                    browser.close()
    finally:
        pw.stop()
    print("ALL GAPS: " + ", ".join(
        "%s=%dpx" % (k, v["gap"]) for k, v in results.items()))
