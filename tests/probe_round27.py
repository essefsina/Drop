"""One-off render probe for the 2.8.12 round + password-notice fix:
measures the menu buttons, sidebar card order, logo, Set Up dialog
notices in locked/unlocked/removed states, the Remove Address modal
stacking + X, and the preview Download greying, in a real Chromium
DOM. Saves proof screenshots. Not part of the shipped test suite."""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from test_link_folders import Client, _free_port  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/dropit-probe-2812"
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
results = {}


def check(name, ok, detail=""):
    results[name] = {"ok": bool(ok), "detail": detail}
    print(("PASS " if ok else "FAIL ") + name + (" -- " + str(detail) if detail else ""))


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
    # Locked + password-protected to start (password-notice state A).
    status, j = client.j("POST", "/api/setlink",
                         {"name": "probe", "password": "pw123"})
    assert status == 200 and j["ok"], j
    status, _ = client.upload("hello.txt", b"hello preview")
    assert status == 200, status

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(f"http://127.0.0.1:{port}/")
        page.wait_for_timeout(1200)

        # ---- menu: buttons centred + full labels, card order, logo
        page.click("#menubtn")
        page.wait_for_timeout(600)
        menu = page.evaluate("""() => {
          const q = s => document.querySelector(s);
          const r = el => { if(!el) return null;
            const b = el.getBoundingClientRect();
            const cs = getComputedStyle(el);
            return {text: el.textContent.trim(), x: b.x, y: b.y, w: b.width, h: b.height,
              display: cs.display, fontSize: cs.fontSize}; };
          const cards = [...document.querySelectorAll('#sidebar .sbcard')].map(c => {
            const b = c.getBoundingClientRect();
            return {y: b.y, h: b.height,
              hasSbedit: !!c.querySelector('#sbedit'),
              hasSwsep: !!c.querySelector('#swsep'),
              hasSbopen: !!c.querySelector('#sbopen')}; });
          const card = q('#sbopen').closest('.sbcard').getBoundingClientRect();
          const logo = q('.sblogo');
          const title = q('.sbtitle');
          const lb = logo ? logo.getBoundingClientRect() : null;
          const tb = title ? title.getBoundingClientRect() : null;
          return {card: {x: card.x, w: card.width},
                  sbopen: r(q('#sbopen')), sbchange: r(q('#sbchange')),
                  cards,
                  logo: lb ? {x: lb.x, w: lb.width, naturalW: logo.naturalWidth} : null,
                  title: tb ? {x: tb.x} : null,
                  h4margin: (() => { const h = q('.lockpwbox h4');
                    return h ? getComputedStyle(h).marginTop : null; })()};
        }""")
        print(json.dumps(menu, indent=2))
        card = menu["card"]
        for key in ("sbopen", "sbchange"):
            b = menu[key]
            cx = b["x"] + b["w"] / 2
            ccx = card["x"] + card["w"] / 2
            check("menu %s centred" % key, abs(cx - ccx) < 3,
                  "btn_cx=%.1f card_cx=%.1f" % (cx, ccx))
        check("menu Change Folder full label",
              menu["sbchange"]["text"] == "Change Folder",
              menu["sbchange"]["text"])
        check("menu Open Folder label",
              menu["sbopen"]["text"] == "Open Folder", menu["sbopen"]["text"])
        ys = {("addr" if c["hasSbedit"] else
               "swsep" if c["hasSwsep"] else
               "main" if c["hasSbopen"] else "?"): c["y"]
              for c in menu["cards"]}
        check("swsep card below address card, above Main Folder",
              ys.get("addr", 1e9) < ys.get("swsep", -1) < ys.get("main", 1e9),
              ys)
        check("logo before Drop text",
              menu["logo"] and menu["title"]
              and menu["logo"]["x"] < menu["title"]["x"]
              and menu["logo"]["naturalW"] > 0,
              menu["logo"])
        page.screenshot(path=os.path.join(OUT, "menu.png"))

        def open_setup():
            page.evaluate("""() => {
              const sb = document.querySelector('#sidebar');
              if (sb && !sb.classList.contains('open'))
                document.querySelector('#menubtn').click(); }""")
            page.wait_for_timeout(400)
            page.click("#sbedit")
            page.wait_for_timeout(700)

        def read_notices():
            return page.evaluate("""() => {
              const vis = id => { const e = document.querySelector(id);
                return e ? e.classList.contains('show') : null; };
              const txt = id => { const e = document.querySelector(id);
                return e ? e.textContent.trim() : null; };
              return {lockedShow: vis('#lklockedwarn'),
                      lockedText: txt('#lklockedtext'),
                      openShow: vis('#lkopenwarn'),
                      stateText: txt('#lkstate'),
                      h4margin: (() => { const h = document.querySelector('.lockpwbox h4');
                        return h ? getComputedStyle(h).marginTop + '/' + getComputedStyle(h).fontSize : null; })(),
                      dialogHasPasswordSet: (document.querySelector('#lockwrap') || {textContent: ''}).textContent.includes('Password set for this address')};
            }""")

        # ---- state A: locked + password
        open_setup()
        n = read_notices()
        print("NOTICES locked:", json.dumps(n))
        check("locked: locked notice shown, open hidden",
              n["lockedShow"] is True and n["openShow"] is False, n)
        check("locked: notice text is Locked address",
              n["lockedText"] == "Locked address — password required",
              n["lockedText"])
        check("Set Password h4 shifted 8px, size intact",
              n["h4margin"] == "8px/20px", n["h4margin"])
        page.screenshot(path=os.path.join(OUT, "setup_locked.png"))
        page.click("#lkcloseX")
        page.wait_for_timeout(400)

        # ---- state B: unlocked, password still stored (Essef's bug)
        s, j = client.j("POST", "/api/addresslock", {"locked": False})
        assert s == 200 and j["ok"], j
        page.reload()
        page.wait_for_timeout(1000)
        open_setup()
        n = read_notices()
        print("NOTICES unlocked:", json.dumps(n))
        check("unlocked: open notice shown, locked hidden",
              n["openShow"] is True and n["lockedShow"] is False, n)
        check("unlocked: NO 'Password set' text in dialog",
              n["dialogHasPasswordSet"] is False, n["stateText"])
        page.screenshot(path=os.path.join(OUT, "setup_unlocked.png"))

        # ---- Remove Address modal: stacking + X (from state B dialog)
        page.click("#lkcurview")
        page.wait_for_timeout(400)
        page.click("#lkddlist .dddel[data-delhist]")
        page.wait_for_timeout(500)
        modal = page.evaluate("""() => {
          const pop = document.querySelector('#addrrempop');
          const box = document.querySelector('.addrrembox');
          const x = document.querySelector('#addrremcloseX');
          const bb = box.getBoundingClientRect();
          const xb = x.getBoundingClientRect();
          const cs = getComputedStyle(x);
          const cx = bb.x + bb.width / 2, cy = bb.y + bb.height / 2;
          const hit = document.elementFromPoint(cx, cy);
          return {popOpen: pop.classList.contains('open'),
                  popZ: getComputedStyle(pop).zIndex,
                  hitInModal: !!(hit && hit.closest('#addrrempop')),
                  hitTag: hit ? hit.tagName + '.' + hit.className : null,
                  xRect: {x: xb.x, y: xb.y, w: xb.width, h: xb.height},
                  boxRight: bb.x + bb.width, boxTop: bb.y,
                  xBg: cs.backgroundImage, xBorder: cs.border,
                  xColor: cs.color, xFont: cs.fontSize};
        }""")
        print("MODAL:", json.dumps(modal, indent=2))
        check("modal open + z-index 4000 (above Set Up)",
              modal["popOpen"] and modal["popZ"] == "4000", modal["popZ"])
        check("modal centre hit-tests inside the modal (on top)",
              modal["hitInModal"] is True, modal["hitTag"])
        check("modal X top-right, 32px",
              abs((modal["xRect"]["x"] + modal["xRect"]["w"])
                  - modal["boxRight"]) <= 14
              and abs(modal["xRect"]["y"] - modal["boxTop"]) <= 12
              and modal["xRect"]["w"] == 32, modal["xRect"])
        check("modal X coloured + bordered",
              "239, 68, 68" in modal["xBg"] and "239, 68, 68" in modal["xBorder"],
              modal["xBg"][:80] + " | " + modal["xBorder"])
        page.screenshot(path=os.path.join(OUT, "modal.png"))
        page.click("#addrremcancel")
        page.wait_for_timeout(400)
        page.click("#lkcloseX")
        page.wait_for_timeout(400)

        # ---- preview without download permission (GUEST view: the
        # host bypass always allows downloads, so only a guest
        # session shows the greyed Download button)
        s, j = client.j("POST", "/api/permissions",
                        {"permissions": {"download_files": False,
                                         "upload_files": True,
                                         "delete_files": False,
                                         "add_notes": True,
                                         "delete_notes": False,
                                         "star_notes": True}})
        assert s == 200 and j["ok"], j
        # Mint a real guest-stamped session (login + flip role, as
        # the test suite does): a plain loopback browser is treated
        # as host, so without this the preview Download never greys.
        from test_link_round16 import _guest as _guest_client
        guest = _guest_client(port, home, "pw123")
        token = guest.cookies["drop_sess"]
        gctx = browser.new_context(viewport={"width": 1440, "height": 900})
        gctx.add_cookies([
            {"name": "drop_sess", "value": token,
             "domain": "127.0.0.1", "path": "/"},
            {"name": "drop_locked", "value": "1",
             "domain": "127.0.0.1", "path": "/"}])
        gpage = gctx.new_page()
        # Sandbox limit: a loopback browser is host by design
        # (authstate "host" is _is_host(), i.e. loopback), so a
        # guest-stamped session on loopback still sees
        # AUTH.host=true and the preview fetches the plain URL
        # (403 for the guest role). A real phone gets host=false.
        # Rewrite just that flag in the authstate response to
        # simulate the phone's view; everything else (session
        # role, permissions, preview fetch, render) is real.
        def _authstate_as_guest(route):
            resp = route.fetch()
            j = resp.json()
            j["host"] = False
            route.fulfill(response=resp, json=j)
        gpage.route("**/api/authstate", _authstate_as_guest)
        gpage.goto(f"http://127.0.0.1:{port}/")
        gpage.wait_for_timeout(1500)
        try:
            gpage.locator("text=hello.txt").first.click(timeout=5000)
            gpage.wait_for_timeout(800)
        except Exception as e:
            print("file-row click failed:", e)
        pv = gpage.evaluate("""() => {
          const v = document.querySelector('#previewpop');
          const dl = document.querySelector('#previewdl');
          const body = document.querySelector('#previewbody');
          return {viewerOpen: v ? v.classList.contains('open') : null,
                  viewerText: body ? body.innerText.slice(0, 120) : null,
                  dlGreyed: dl ? dl.classList.contains('deloff') : null,
                  dlText: dl ? dl.textContent.trim() : null};
        }""")
        print("PREVIEW:", json.dumps(pv, indent=2))
        check("preview opens without download permission",
              pv["viewerOpen"] is True
              and "hello preview" in (pv["viewerText"] or ""), pv)
        check("preview Download button greyed",
              pv["dlGreyed"] is True, pv)
        gpage.screenshot(path=os.path.join(OUT, "preview.png"))
        gctx.close()

        # ---- state C: password removed
        s, j = client.j("POST", "/api/setlinkpassword", {"password": ""})
        assert s == 200 and j["ok"], j
        page.reload()
        page.wait_for_timeout(1000)
        open_setup()
        n = read_notices()
        print("NOTICES removed:", json.dumps(n))
        check("removed: open notice only, no password-set text",
              n["openShow"] is True and n["lockedShow"] is False
              and n["dialogHasPasswordSet"] is False, n)
        page.screenshot(path=os.path.join(OUT, "setup_removed.png"))
        page.click("#lkcloseX")
        page.wait_for_timeout(400)
        browser.close()
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

print("RESULTS:", json.dumps(results, indent=2))
fails = [k for k, v in results.items() if not v["ok"]]
print("FAILURES:", fails if fails else "none")
print("OUT:", OUT)
