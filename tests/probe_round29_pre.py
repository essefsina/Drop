"""Pre-fix measurement probe for the 2.8.14 round (run BEFORE editing):
measures the Change Folder icon offset (menu + Set Up + Files card),
the guestcard X vs header text, the guestcard Save icon/text centres,
and the login Connect button width. Prints numbers only; no edits."""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from test_link_folders import Client, _free_port  # noqa: E402

OUT = "/tmp/dropit-probe-2814-pre"
os.makedirs(OUT, exist_ok=True)
home = os.path.join(OUT, "home")
base = os.path.join(OUT, "base")
os.makedirs(os.path.join(home, ".config", "DropIt"), exist_ok=True)
os.makedirs(base, exist_ok=True)
port = _free_port()
env = dict(os.environ, HOME=home)
proc = subprocess.Popen(
    [sys.executable, "dropit.py", "--port", str(port), "--dir", base],
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

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        # ---- desktop 1280x900: menu + Set Up + Files card icon offsets ----
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"http://127.0.0.1:{port}/")
        page.wait_for_timeout(1200)
        page.evaluate("openSidebar(true)")
        page.wait_for_timeout(400)
        m = page.evaluate("""() => {
          const r = s => { const el = document.querySelector(s); if(!el) return null;
            const b = el.getBoundingClientRect(); return {left: b.left, w: b.width}; };
          return {
            menuOpen: r('#sbopen svg'), menuChange: r('#sbchange svg'),
            menuOpenBtn: r('#sbopen'), menuChangeBtn: r('#sbchange'),
          }; }""")
        print("MENU open icon:", m["menuOpen"], "change icon:", m["menuChange"],
              "delta(change-open):",
              (m["menuChange"]["left"] - m["menuOpen"]["left"]) if m["menuOpen"] and m["menuChange"] else None)
        page.evaluate("openSidebar(false); openLinkWin()")
        page.wait_for_timeout(600)
        s = page.evaluate("""() => {
          const r = s => { const el = document.querySelector(s); if(!el) return null;
            const b = el.getBoundingClientRect(); return {left: b.left, w: b.width}; };
          const off = (btn, ic) => { const a = r(btn), b = r(ic);
            return (a && b) ? (b.left - a.left) : null; };
          return { setupOpenOff: off('#lkopenfolder', '#lkopenfolder svg'),
                   setupChangeOff: off('#lkchangefolder', '#lkchangefolder svg'),
                   filesOpenOff: off('#openfolder', '#openfolder svg'),
                   filesChangeOff: off('#changefolder', '#changefolder svg'),
                   filesOpen: r('#openfolder svg'), filesChange: r('#changefolder svg') }; }""")
        print("SETUP in-button offset open:", s["setupOpenOff"], "change:", s["setupChangeOff"])
        print("FILES in-button offset open:", s["filesOpenOff"], "change:", s["filesChangeOff"],
              "raw:", s["filesOpen"], s["filesChange"])
        page.evaluate("closeLinkWin()")
        page.close()
        # ---- mobile 390x844: guest login + guestcard modal ----
        mp = browser.new_page(viewport={"width": 390, "height": 844})
        mp.goto(f"http://127.0.0.1:{port}/")
        mp.wait_for_timeout(1200)
        mp.evaluate("showGuestLogin('')")
        mp.wait_for_timeout(400)
        g = mp.evaluate("""() => {
          const b = document.querySelector('#gloginbtn');
          const r = b ? b.getBoundingClientRect() : null;
          const box = document.querySelector('.gloginbox').getBoundingClientRect();
          return { btnW: r ? r.width : null, btnLeft: r ? r.left : null,
                   boxW: box.width, boxLeft: box.left,
                   bg: b ? getComputedStyle(b).backgroundImage + ' / ' + getComputedStyle(b).backgroundColor : null }; }""")
        print("LOGIN connect btn:", g)
        # force guestcard modal layout for measurement
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
            const b = el.getBoundingClientRect(); return {l: b.left, t: b.top, r: b.right, b: b.bottom, w: b.width, h: b.height}; };
          const sv = document.querySelector('#lkset svg');
          const btn = document.querySelector('#lkset');
          const br = btn ? btn.getBoundingClientRect() : null;
          const sr = sv ? sv.getBoundingClientRect() : null;
          return { xBtn: r('#lkcloseX'), headTxt: r('.guestcardtxt'), head: r('.guestcardhead'),
                   saveBtn: br ? {t: br.top, b: br.bottom, cy: (br.top+br.bottom)/2} : null,
                   saveSvg: sr ? {t: sr.top, b: sr.bottom, cy: (sr.top+sr.bottom)/2} : null }; }""")
        print("GUESTCARD X:", x["xBtn"], "header txt:", x["headTxt"], "header:", x["head"])
        print("SAVE btn centre-y:", x["saveBtn"], "svg centre-y:", x["saveSvg"],
              "svg-btn dy:", (x["saveSvg"]["cy"] - x["saveBtn"]["cy"]) if x["saveBtn"] and x["saveSvg"] else None)
        mp.screenshot(path=os.path.join(OUT, "guestcard-pre.png"))
        mp.close()
        browser.close()
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
print("done")
