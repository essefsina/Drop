"""v2.8.26 round (Essef Nov 6, ~4:51 AM) -- web/desktop only.

(1) UPLOADING PILL MOVED SLIGHTLY HIGHER: the pill (.upfloat)
    sat at the top of the Shared Files card with a 4px clear gap
    (bottom edge 4px above the card's top edge, _upShow:
    r.top - ph - 4). Essef: move it slightly higher up, resize
    nothing else. Now 12px clear gap (r.top - ph - 12; fallback
    top 96px -> 88px). Pill stays 36px tall, same padding/font/
    ring/X.
(2) PILL SIZE MUST NOT GROW WITH A BIGGER FILE NAME: the name
    span was capped at max-width:180px, so the pill still grew
    with the name (short name = narrow pill, long name = wide
    pill, up to ~268px). Now the pill is a FIXED WIDTH (272px,
    box-sizing:border-box) and the name flexes inside it with
    an ellipsis, so short and 80+ char names measure identical.

Superseded round40 assertions (Essef's new instructions
replace them, NOT regressions):
- round40 test_2_pill_source: the .upfloat CSS line (top 96px,
  no fixed width) and the .upfloat-name max-width:180px rule.
- round40 test_2_live_pill_matches_devices_dark/light: they
  assert the pill bottom touches the card top (abs(bottom -
  filesTop) <= 6); the gap is now 12px, and the pill width is
  now fixed at 272px regardless of name length.
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

PROOF = "/home/hatch/workspace/dropit-proof-round41"
os.makedirs(PROOF, exist_ok=True)


def test_version_is_2_8_26():
    assert D.VERSION == "2.8.26"


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
        with open("/tmp/r41_script_%d.js" % i, "w",
                  encoding="utf-8") as fh:
            fh.write(js)
        out = subprocess.run(["node", "--check",
                              "/tmp/r41_script_%d.js" % i],
                             capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr


# ---- (1)+(2) pill higher + fixed width ---------------------------------
def test_pill_higher_and_fixed_width_source():
    # Fallback top 96px -> 88px, and the fixed width is in the
    # .upfloat rule itself.
    assert "top:88px; z-index:300;" in PAGE
    assert "top:96px; z-index:300;" not in PAGE
    assert "width:272px; box-sizing:border-box;" in PAGE
    # _upShow gap 4px -> 12px above the files card.
    assert 'f.style.top = Math.max(8, Math.round(r.top - ph - 12)) + "px";' in PAGE
    assert 'f.style.top = Math.max(8, Math.round(r.top - ph - 4)) + "px";' not in PAGE
    assert 'f.style.top = "88px";' in PAGE
    # Name flexes inside the fixed width; the old 180px cap is gone.
    assert ".upfloat-name { flex:1 1 auto; min-width:0; overflow:hidden; text-overflow:ellipsis;" in PAGE
    assert ".upfloat-name { max-width:180px;" not in PAGE
    # Everything else about the pill is untouched: 36px tall,
    # same padding/gap, ring 28px, X 20px.
    assert "border-radius:999px; height:36px; width:272px; box-sizing:border-box; padding:0 14px;" in PAGE
    assert ".upring { width:28px; height:28px;" in PAGE
    assert ".upcancel { flex:none; width:20px; height:20px;" in PAGE


def _name_geom(pg):
    return pg.evaluate("""() => {
      const n = document.querySelector('#upfloatname');
      const r = n.getBoundingClientRect();
      return {text: n.textContent, w: Math.round(r.width),
              scrollW: n.scrollWidth, clientW: n.clientWidth};
    }""")


def test_live_pill_higher_and_fixed_width(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r41pill"})
    _make_fixtures(os.path.join(str(base), "r41pill"))
    pw = _playwright()
    try:
        browser, pg = _host_page(pw, port)
        try:
            pg.route("**/api/upload", lambda route: None)
            # Short name first.
            pg.set_input_files("#picker", _held_upload("short.bin"))
            pg.wait_for_timeout(1200)
            m1 = _pill_measure(pg)
            assert m1["show"] is True, m1
            assert m1["up"]["h"] == 36, m1
            assert m1["up"]["w"] == 272, m1
            # 12px clear gap above the files card (was 4px).
            assert m1["filesTop"] - m1["up"]["bottom"] == 12, m1
            g1 = _name_geom(pg)
            assert g1["text"] == "r40_upload_short.bin", g1
            pg.screenshot(path=os.path.join(PROOF, "r41_pill_short.png"))
            pg.click("#upcancel")
            pg.wait_for_timeout(1800)
            assert pg.evaluate(
                "() => !document.querySelector('#upfloat').classList.contains('show')")
            # 80+ char name: pill dimensions must be identical.
            long_name = "a" * 80 + "_very_long_file_name_that_keeps_going.bin"
            assert len(long_name) > 80
            pg.set_input_files("#picker", _held_upload(long_name))
            pg.wait_for_timeout(1200)
            m2 = _pill_measure(pg)
            assert m2["show"] is True, m2
            assert m2["up"]["h"] == 36, m2
            assert m2["up"]["w"] == 272, m2
            assert m2["up"]["w"] == m1["up"]["w"], (m1, m2)
            assert m2["up"]["h"] == m1["up"]["h"], (m1, m2)
            assert m2["filesTop"] - m2["up"]["bottom"] == 12, m2
            g2 = _name_geom(pg)
            assert g2["text"] == "r40_upload_" + long_name, g2
            # Name is ellipsised inside the fixed pill: its
            # scroll width exceeds its visible width.
            assert g2["scrollW"] > g2["clientW"], g2
            assert g2["w"] == g1["w"], (g1, g2)
            pg.screenshot(path=os.path.join(PROOF, "r41_pill_long.png"))
            pg.click("#upcancel")
            pg.wait_for_timeout(1800)
            assert pg.evaluate(
                "() => !document.querySelector('#upfloat').classList.contains('show')")
            pg.unroute("**/api/upload")
        finally:
            browser.close()
    finally:
        pw.stop()
