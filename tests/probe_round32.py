"""Post-fix render probe for the 2.8.16 round: measures every visual
item in a real Chromium DOM against a live server at mobile width
(390px), and screenshots the proofs. Not part of the shipped suite.
"""
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from test_link_folders import Client, _free_port  # noqa: E402

OUT = "/tmp/dropit-probe-2816"
os.makedirs(OUT, exist_ok=True)
home = os.path.join(OUT, "home")
base = os.path.join(OUT, "base")
os.makedirs(os.path.join(home, ".config", "DropIt"), exist_ok=True)
os.makedirs(base, exist_ok=True)

PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
       b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
       b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/"
       b"Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
       b"4 0 obj<</Length 44>>stream\nBT /F1 18 Tf 20 180 Td "
       b"(Hello PDF) Tj ET\nendstream endobj\n"
       b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
       b"trailer<</Root 1 0 R>>\n%%EOF\n")

PNG_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
           "Xw8AAwMCAO+ip1sAAAAASUVORK5CYII=")

results = {}


def check(name, ok, detail=""):
    results[name] = {"ok": bool(ok), "detail": detail}
    print(("PASS " if ok else "FAIL ") + name + (" -- " + str(detail) if detail else ""))


def stored_docx_b64():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("word/document.xml",
                   '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Hello docx saved</w:t></w:r></w:p><w:p><w:r><w:t>Second paragraph 123</w:t></w:r></w:p></w:body></w:document>')
    return base64.b64encode(buf.getvalue()).decode()


port = _free_port()
env = dict(os.environ, HOME=home)
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

    seeds = {
        "photo.png": PNG_B64,
        "notes.txt": base64.b64encode(b"hello saved text file").decode(),
        "doc.pdf": base64.b64encode(PDF).decode(),
        "word.docx": stored_docx_b64(),
        "legacy.doc": base64.b64encode(b"\xd0\xcf\x11\xe0" + b"Hello saved doc world second line 123" + b"\x00" * 20).decode(),
        "song.mp3": base64.b64encode(b"ID3" + b"\x00" * 64).decode(),
        "clip.mp4": base64.b64encode(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64).decode(),
        "archive.zip": base64.b64encode(b"PK\x05\x06" + b"\x00" * 18).decode(),
    }
    ledger = {n: {"size": len(base64.b64decode(v)), "ts": 1793000000} for n, v in seeds.items()}

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        mp = browser.new_page(viewport={"width": 390, "height": 844})
        mp.goto(f"http://127.0.0.1:{port}/")
        mp.wait_for_timeout(1200)
        mp.evaluate("showGuestLogin()")
        mp.wait_for_timeout(400)

        # (1)(2)(3)(5) login-page layout
        m = mp.evaluate("""() => {
          const box = document.querySelector('.gloginbox');
          const br = box.getBoundingClientRect();
          const saved = document.querySelector('#gsavedbtn');
          const conn = document.querySelector('#gloginbtn');
          const inp = document.querySelector('#gloginlink');
          const chev = document.querySelector('#gddchevbtn');
          const sr = saved.getBoundingClientRect(), cr = conn.getBoundingClientRect();
          const ir = inp.getBoundingClientRect(), hr = chev.getBoundingClientRect();
          const cs = getComputedStyle(conn);
          const contentW = box.clientWidth - 48; // 24px padding each side
          return {
            savedRatio: +(sr.width / contentW).toFixed(2),
            savedVsConn: Math.round(sr.width - cr.width),
            savedCentred: Math.abs((sr.left - br.left) - (br.right - sr.right)) <= 2,
            connColor: cs.color, connTop: Math.round(cr.top),
            connMarginTop: getComputedStyle(conn).marginTop,
            pwBottom: Math.round(document.querySelector('#gloginpw').getBoundingClientRect().bottom),
            chevDelta: +(((hr.top + hr.height / 2) - (ir.top + ir.height / 2)).toFixed(1)),
            noteGone: !document.body.innerText.includes('Your recent addresses are saved only on this device'),
            connText: conn.textContent.trim(), savedText: saved.textContent.trim(),
          }; }""")
        check("Saved button is 60% of the card content width, centred, same width as Connect",
              0.58 <= m["savedRatio"] <= 0.62 and m["savedCentred"] and abs(m["savedVsConn"]) <= 2, m)
        check("Connect text is white",
              m["connColor"] == "rgb(255, 255, 255)", m["connColor"])
        check("Connect moved slightly up (margin-top -4px)",
              m["connMarginTop"] == "-4px" and 28 <= (m["connTop"] - m["pwBottom"]) <= 38, m)
        check("Address chevron sits a bit higher than field centre",
              -6 <= m["chevDelta"] <= -1, m)
        check("'Your recent addresses' note is gone from the web login",
              m["noteGone"], m)
        mp.screenshot(path=os.path.join(OUT, "login-2816.png"))

        # Seed the saved files (ledger + IndexedDB blobs), then open the view.
        mp.evaluate("""async (args) => {
          localStorage.setItem('dropit_dl', JSON.stringify(args.ledger));
          for (const [name, b64] of Object.entries(args.seeds)) {
            const bin = atob(b64); const bytes = new Uint8Array(bin.length);
            for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
            await DBCACHE.put(name, new Blob([bytes]));
          }
          return true; }""", {"seeds": seeds, "ledger": ledger})
        mp.evaluate("document.querySelector('#gsavedbtn').click()")
        mp.wait_for_timeout(900)
        rows = mp.evaluate("""() => {
          const rs = [...document.querySelectorAll('.gsavedrow')];
          return rs.map(r => ({
            name: r.querySelector('.gsname').textContent,
            thumb: r.querySelector('.gsthumbwrap img') ? 'img'
              : r.querySelector('.gsthumbwrap video') ? 'video'
              : r.querySelector('.gsthumbwrap .fic') ? 'icon' : 'none',
            hasPreview: !!r.querySelector('[data-preview-saved]'),
            hasOpen: !!r.querySelector('[data-open-saved]'),
          })); }""")
        check("saved view lists all 8 seeded files with thumbnail + Preview + Open",
              len(rows) == 8 and all(r["thumb"] != "none" and r["hasPreview"] and r["hasOpen"] for r in rows), rows)
        check("image row got a real <img> thumbnail, video row a <video> thumbnail",
              any(r["name"] == "photo.png" and r["thumb"] == "img" for r in rows)
              and any(r["name"] == "clip.mp4" and r["thumb"] == "video" for r in rows), rows)
        mp.screenshot(path=os.path.join(OUT, "saved-2816.png"))

        # (4) Preview every type in the viewer.
        def preview(name):
            mp.evaluate("""(n) => {
              const rows = document.querySelectorAll('.gsavedrow');
              for (const row of rows) {
                if (row.querySelector('.gsname').textContent === n) {
                  row.querySelector('[data-preview-saved]').click(); break; }
              } }""", name)
            mp.wait_for_timeout(1200)
            v = mp.evaluate("""() => {
              const v = document.querySelector('#vcontent');
              return { open: document.querySelector('#viewer').classList.contains('open'),
                       text: v ? v.innerText.slice(0, 120) : null,
                       hasImg: !!v.querySelector('img'), hasIframe: !!v.querySelector('iframe'),
                       hasVideo: !!v.querySelector('video'), hasAudio: !!v.querySelector('audio'),
                       hasPre: !!v.querySelector('pre'), hasOpenBtn: !!v.querySelector('#votheropen') }; }""")
            mp.evaluate("document.querySelector('#vclose').click()")
            mp.wait_for_timeout(300)
            return v

        v = preview("photo.png")
        check("Preview: image renders <img> in viewer", v["open"] and v["hasImg"], v)
        v = preview("notes.txt")
        check("Preview: text renders with content", v["open"] and v["hasPre"] and "hello saved text" in (v["text"] or ""), v)
        v = preview("doc.pdf")
        check("Preview: PDF renders in-app <iframe> (no new tab)", v["open"] and v["hasIframe"], v)
        mp.screenshot(path=os.path.join(OUT, "preview-pdf-2816.png"))
        v = preview("word.docx")
        check("Preview: .docx renders offline-extracted text", v["open"] and "Hello docx saved" in (v["text"] or ""), v)
        v = preview("legacy.doc")
        check("Preview: .doc renders extracted text", v["open"] and "Hello saved doc world" in (v["text"] or ""), v)
        v = preview("song.mp3")
        check("Preview: audio renders <audio> in viewer", v["open"] and v["hasAudio"], v)
        v = preview("clip.mp4")
        check("Preview: video renders <video> in viewer", v["open"] and v["hasVideo"], v)
        v = preview("archive.zip")
        check("Preview: other type shows a preview card with Open (never blank)",
              v["open"] and v["hasOpenBtn"] and "No in-app preview" in (v["text"] or ""), v)

        # (6) guest Connect To A PC modal: label + space below it
        mp.evaluate("document.querySelector('#gsavedback').click()")
        mp.wait_for_timeout(300)
        # The probe browser holds the host session (no password on
        # the probe address), so force the guest view, exactly as
        # a guest phone sees it, before opening the modal.
        mp.evaluate("AUTH.host = false; AUTH.authed = false; openLinkWin()")
        mp.wait_for_timeout(600)
        g = mp.evaluate("""() => {
          const l = document.querySelector('#lklinklabel');
          const f = document.querySelector('#lkin');
          const lr = l.getBoundingClientRect(), fr = f.getBoundingClientRect();
          return { label: l.textContent.trim(),
                   marginBottom: getComputedStyle(l).marginBottom,
                   gap: Math.round(fr.top - lr.bottom),
                   placeholder: f.getAttribute('placeholder') }; }""")
        check("guest modal label is 'Address To Connect' with space below it",
              g["label"] == "Address To Connect" and g["placeholder"] == "Address To Connect"
              and g["marginBottom"] == "14px" and g["gap"] >= 12, g)
        mp.screenshot(path=os.path.join(OUT, "guestcard-2816.png"))
        mp.close()
        browser.close()

    print(json.dumps(results, indent=2, default=str))
    failed = [k for k, v in results.items() if not v["ok"]]
    print("FAILED:", failed if failed else "none")
    sys.exit(1 if failed else 0)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
