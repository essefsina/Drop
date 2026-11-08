"""Post-fix render probe for the 2.8.14 round: measures every visual
item in a real Chromium DOM against a live server (desktop=True so
the Files-card folder buttons render), and screenshots the proofs.
Not part of the shipped test suite."""
import json
import os
import shutil
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from test_link_folders import Client, _free_port  # noqa: E402

OUT = "/tmp/dropit-probe-2814"
os.makedirs(OUT, exist_ok=True)
home = os.path.join(OUT, "home")
base = os.path.join(OUT, "base")
os.makedirs(os.path.join(home, ".config", "DropIt"), exist_ok=True)
os.makedirs(base, exist_ok=True)
FIX = os.path.join(os.path.dirname(__file__), "fixtures")

# Minimal valid PDF (one page, "Hello PDF") for the preview check.
PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
       b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
       b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/"
       b"Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
       b"4 0 obj<</Length 44>>stream\nBT /F1 18 Tf 20 180 Td "
       b"(Hello PDF) Tj ET\nendstream endobj\n"
       b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
       b"trailer<</Root 1 0 R>>\n%%EOF\n")

results = {}


def check(name, ok, detail=""):
    results[name] = {"ok": bool(ok), "detail": detail}
    print(("PASS " if ok else "FAIL ") + name + (" -- " + str(detail) if detail else ""))


port = _free_port()
env = dict(os.environ, HOME=home)
# Server runs in its own process (desktop=True so the Files-card
# folder buttons render) with an isolated HOME; the probe process
# keeps the real HOME so Playwright finds its Chromium build.
proc = subprocess.Popen(
    [sys.executable, "-c",
     "import sys, dropit; dropit.make_server(%d, %r, desktop=True).serve_forever()"
     % (port, base)],
    cwd=os.path.join(os.path.dirname(__file__), ".."),
    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    client = Client(port)
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            status, _ = client.j("GET", "/api/authstate")
            if status == 200:
                break
        except OSError:
            pass
        time.sleep(0.2)
    status, j = client.j("POST", "/api/setlink", {"name": "probe", "password": ""})
    assert status == 200 and j["ok"], j
    for name in ("test.docx", "test.doc"):
        shutil.copy(os.path.join(FIX, name), os.path.join(base, "probe", name))
    with open(os.path.join(base, "probe", "hello.pdf"), "wb") as f:
        f.write(PDF)
    with open(os.path.join(base, "probe", "hello world.txt"), "w") as f:
        f.write("hello preview")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        # ---------- desktop 1280x900 ----------
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"http://127.0.0.1:{port}/")
        page.wait_for_timeout(1200)
        # (10) Change Folder icon alignment: menu + Set Up + Files card
        page.evaluate("openSidebar(true)")
        page.wait_for_timeout(400)
        m = page.evaluate("""() => {
          const r = s => { const el = document.querySelector(s); if(!el) return null;
            const b = el.getBoundingClientRect(); return {left: b.left}; };
          const off = (btn, ic) => { const a = r(btn), b = r(ic);
            return (a && b) ? +(b.left - a.left).toFixed(2) : null; };
          return { menuDelta: (r('#sbchange svg').left - r('#sbopen svg').left).toFixed(2),
                   filesDelta: (off('#changefolder', '#changefolder svg') - off('#openfolder', '#openfolder svg')).toFixed(2) }; }""")
        check("menu change icon aligns with open icon",
              abs(float(m["menuDelta"])) <= 1, m)
        check("files-card change icon aligns with open icon",
              abs(float(m["filesDelta"])) <= 1, m)
        page.evaluate("openSidebar(false); openLinkWin()")
        page.wait_for_timeout(600)
        s = page.evaluate("""() => {
          const r = s => { const el = document.querySelector(s); if(!el) return null;
            const b = el.getBoundingClientRect(); return {left: b.left}; };
          const off = (btn, ic) => { const a = r(btn), b = r(ic);
            return (a && b) ? +(b.left - a.left).toFixed(2) : null; };
          return { open: off('#lkopenfolder', '#lkopenfolder svg'),
                   change: off('#lkchangefolder', '#lkchangefolder svg') }; }""")
        check("setup change icon aligns with open icon",
              s["open"] is not None and s["change"] is not None and abs(s["change"] - s["open"]) <= 1, s)
        page.screenshot(path=os.path.join(OUT, "setup-2814.png"))
        page.evaluate("closeLinkWin()")
        # (4/5) Word + PDF preview on web: click the file name
        page.evaluate("""() => {
          const rows = document.querySelectorAll('.frow');
          for (const row of rows) {
            if (row.dataset.frow === 'test.docx') { row.querySelector('.fname').click(); break; }
          } }""")
        page.wait_for_timeout(1200)
        w = page.evaluate("""() => {
          const b = document.querySelector('#previewbody');
          return { text: b ? b.innerText.slice(0, 80) : null,
                   hasDocx: !!document.querySelector('#previewbody .docxview') }; }""")
        check("web .docx preview renders text", w["hasDocx"] and "Hello docx world" in (w["text"] or ""), w)
        page.keyboard.press("Escape")
        page.evaluate("document.querySelector('#previewclose').click()")
        page.wait_for_timeout(300)
        page.evaluate("""() => {
          const rows = document.querySelectorAll('.frow');
          for (const row of rows) {
            if (row.dataset.frow === 'test.doc') { row.querySelector('.fname').click(); break; }
          } }""")
        page.wait_for_timeout(1200)
        w2 = page.evaluate("""() => {
          const b = document.querySelector('#previewbody');
          return { text: b ? b.innerText.slice(0, 80) : null }; }""")
        check("web .doc preview renders extracted text",
              "Hello docx world" in (w2["text"] or ""), w2)
        page.evaluate("document.querySelector('#previewclose').click()")
        page.wait_for_timeout(300)
        page.evaluate("""() => {
          const rows = document.querySelectorAll('.frow');
          for (const row of rows) {
            if (row.dataset.frow === 'hello.pdf') { row.querySelector('.fname').click(); break; }
          } }""")
        page.wait_for_timeout(1200)
        p = page.evaluate("""() => {
          const e = document.querySelector('#previewbody embed');
          return { hasEmbed: !!e, src: e ? e.getAttribute('src') : null }; }""")
        check("web PDF preview embeds with ?preview=1",
              p["hasEmbed"] and p["src"] is not None and "?preview=1" in p["src"], p)
        page.screenshot(path=os.path.join(OUT, "preview-pdf-2814.png"))
        page.evaluate("document.querySelector('#previewclose').click()")
        # (11) web theme switch: no reload, all surfaces repaint
        before = page.evaluate("""() => ({
          light: document.documentElement.classList.contains('light'),
          card: getComputedStyle(document.querySelector('.minicard')).backgroundColor,
          url: location.href })""")
        page.evaluate("openSidebar(true)")
        page.wait_for_timeout(300)
        page.evaluate("document.querySelector('#themesw2').click()")
        page.wait_for_timeout(400)
        after = page.evaluate("""() => ({
          light: document.documentElement.classList.contains('light'),
          card: getComputedStyle(document.querySelector('.minicard')).backgroundColor,
          stored: localStorage.getItem('drop_theme'),
          url: location.href })""")
        check("web theme toggles without reload and repaints cards",
              before["light"] != after["light"] and before["card"] != after["card"]
              and before["url"] == after["url"], {"before": before, "after": after})
        page.evaluate("document.querySelector('#themesw2').click()")
        page.wait_for_timeout(400)
        back = page.evaluate("document.documentElement.classList.contains('light')")
        check("web theme toggles back (both directions)", back == before["light"], back)
        page.evaluate("openSidebar(false)")
        page.close()
        # ---------- mobile 390x844 ----------
        mp = browser.new_page(viewport={"width": 390, "height": 844})
        mp.goto(f"http://127.0.0.1:{port}/")
        mp.wait_for_timeout(1200)
        # (1) mobile Connect / Disconnect
        c = mp.evaluate("""() => {
          const cs = (s) => { const el = document.querySelector(s); if(!el) return null;
            const c = getComputedStyle(el); const r = el.getBoundingClientRect();
            return { w: Math.round(r.width), bg: c.backgroundColor, txt: el.textContent.trim() }; };
          const arrow = document.querySelector('#mpcconnect svg');
          return { connect: cs('#mpcconnect'), disconnect: cs('#mpcdisconnect'),
                   arrowStroke: arrow ? arrow.getAttribute('stroke') || getComputedStyle(arrow).stroke : null,
                   row: (() => { const el = document.querySelector('.mpcbtnrow');
                     return el ? getComputedStyle(el).display : null; })() }; }""")
        check("mobile Connect is violet + Disconnect is red, side by side",
              c["connect"] and "124, 58, 237" in c["connect"]["bg"]
              and c["disconnect"] and "239, 68, 68" in c["disconnect"]["bg"]
              and c["row"] == "flex", c)
        # Disconnect fires a real /api/logout request
        logout_calls = []
        mp.on("request", lambda req: logout_calls.append(req.url) if "/api/logout" in req.url else None)
        mp.evaluate("document.querySelector('#mpcdisconnect').click()")
        mp.wait_for_timeout(800)
        check("mobile Disconnect posts /api/logout",
              any("/api/logout" in u for u in logout_calls), logout_calls)
        # (3) pill tabs with coloured icons
        t = mp.evaluate("""() => {
          const bar = document.querySelector('.mtabs');
          const cs = getComputedStyle(bar);
          const r = bar.getBoundingClientRect();
          const cols = {};
          document.querySelectorAll('.mtab .mi svg').forEach((svg, i) => {
            cols[i] = svg.getAttribute('stroke'); });
          return { radius: cs.borderRadius, left: Math.round(r.left), w: Math.round(r.width),
                   vw: window.innerWidth, cols }; }""")
        check("mobile tabs are a centred pill with coloured icons",
              t["radius"] == "999px" and abs((t["left"] + t["w"] / 2) - t["vw"] / 2) <= 2
              and t["cols"].get("0") == "#22C55E" and t["cols"].get("1") == "#D9A441"
              and t["cols"].get("2") == "#3B82F6" and t["cols"].get("3") == "#A78BFA", t)
        mp.screenshot(path=os.path.join(OUT, "mobile-tabs-2814.png"))
        # (8) login Connect button
        mp.evaluate("showGuestLogin('')")
        mp.wait_for_timeout(400)
        g = mp.evaluate("""() => {
          const b = document.querySelector('#gloginbtn');
          const r = b.getBoundingClientRect();
          const box = document.querySelector('.gloginbox').getBoundingClientRect();
          const cs = getComputedStyle(b);
          const contentW = box.width - 48;
          return { w: Math.round(r.width), ratio: +(r.width / contentW).toFixed(2),
                   centred: Math.abs((r.left - box.left - 24) - (box.right - r.right - 24)) <= 2,
                   bg: cs.backgroundColor, bgImg: cs.backgroundImage }; }""")
        check("login Connect is ~60% wide, centred, solid blue",
              0.55 <= g["ratio"] <= 0.65 and g["centred"] and "39, 127, 240" in g["bg"]
              and g["bgImg"] == "none", g)
        # (6/7) guestcard X + Save alignment
        mp.evaluate("""() => {
          const lk = document.querySelector('#lkbox');
          lk.classList.add('guestcard');
          document.querySelector('#guestcardhead').style.display = '';
          document.querySelector('#lkwrap').classList.add('open');
          document.querySelector('#lkwrap').style.display = '';
          document.querySelector('#lkbox h3').style.display = 'none';
        }""")
        mp.wait_for_timeout(400)
        x = mp.evaluate("""() => {
          const r = s => { const el = document.querySelector(s); if(!el) return null;
            const b = el.getBoundingClientRect(); return {l: b.left, t: b.top, r: b.right, b: b.bottom}; };
          const xb = r('#lkcloseX'), ht = r('.guestcardtxt'), hd = r('.guestcardhead');
          const overlap = !(xb.r <= ht.l || xb.l >= ht.r || xb.b <= ht.t || xb.t >= ht.b);
          const btn = document.querySelector('#lkset').getBoundingClientRect();
          const svg = document.querySelector('#lkset svg').getBoundingClientRect();
          return { xInCorner: xb.t < hd.t && Math.abs(xb.r - hd.r) <= 28,
                   overlapWithText: overlap, xRect: xb, headRect: hd,
                   saveDy: +(((svg.top + svg.bottom) / 2 - (btn.top + btn.bottom) / 2).toFixed(2)) }; }""")
        check("guestcard X sits in its own top-right corner, clear of text",
              x["xInCorner"] and not x["overlapWithText"], x)
        check("guestcard Save icon and text share one centre line",
              abs(x["saveDy"]) <= 1, x)
        mp.screenshot(path=os.path.join(OUT, "guestcard-2814.png"))
        mp.close()
        browser.close()
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
print(json.dumps(results, indent=1))
print("FAILURES:", [k for k, v in results.items() if not v["ok"]] or "none")
