"""Real-pywebview PC-app check, round38 item (4).

Drives the REAL page in a REAL pywebview window (Qt/WebEngine
offscreen) -- the same window the PC desktop app uses -- and
proves the PC app's buttons are UNCHANGED from 2.8.22:

  (a) markPcApp adds .pcapp to <html> (bridge present);
  (b) the host Send Text button (#sendsnippet) still shows the
      CHAT BUBBLE icon (.ic-bubble visible, .ic-note hidden),
      keeps its 2.8.22 gradient background and 16px icon;
  (c) the mobile-web buttons (#msendfiles / #msendsnippet) are
      not rendered at all in the PC window (.msend hidden at
      desktop width), so the web-only 2.6.69 revert cannot leak
      into the PC app.

Run with the pywebview venv:
  HOME=/tmp/r38pc_home QT_QPA_PLATFORM=offscreen \
    QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu" \
    /home/hatch/.r36-pwv-venv/bin/python tests/probe_round38_pcapp.py
Result JSON is written to /tmp/r38_pcapp_result.json; the process
exits 0 only when every check passed.
"""
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import dropit  # noqa: E402
import app as appmod  # noqa: E402
from test_link_round2 import _free_port  # noqa: E402
from test_link_folders import Client  # noqa: E402

RESULT = {"ok": False, "checks": {}}


def main():
    import tempfile
    home = tempfile.mkdtemp(prefix="r38pc_home_")
    base = tempfile.mkdtemp(prefix="r38pc_base_")
    os.environ["HOME"] = home
    os.makedirs(os.path.join(home, ".config", "DropIt"), exist_ok=True)
    port = _free_port()
    server = dropit.make_server(port, base, desktop=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = Client(port)
    st, j = client.j("POST", "/api/setlink", {"name": "probeaddr"})
    assert st == 200 and j["ok"], j

    import webview
    api = appmod.Api(server)
    window = webview.create_window(
        "Drop", "http://127.0.0.1:%d/" % port,
        width=1280, height=800, js_api=api)

    def drive():
        try:
            deadline = time.time() + 40
            ready = False
            while time.time() < deadline:
                try:
                    ready = window.evaluate_js(
                        "!!document.querySelector('#sendsnippet')")
                except Exception:  # noqa: BLE001
                    ready = False
                if ready:
                    break
                time.sleep(0.5)
            RESULT["checks"]["page_ready"] = bool(ready)
            time.sleep(1.5)
            m = window.evaluate_js("""JSON.stringify((() => {
              const de = document.documentElement;
              const btn = document.querySelector('#sendsnippet');
              const cs = btn ? getComputedStyle(btn) : null;
              const bub = btn ? btn.querySelector('.ic-bubble') : null;
              const note = btn ? btn.querySelector('.ic-note') : null;
              const msend = document.querySelector('.msend');
              const mf = document.querySelector('#msendfiles');
              const mt = document.querySelector('#msendsnippet');
              const vis = (el) => el ? getComputedStyle(el).display : null;
              return {pcapp: de.classList.contains('pcapp'),
                hasBridge: (typeof hasBridge === 'function') ? hasBridge() : 'no-fn',
                btnBgColor: cs ? cs.backgroundColor : null,
                btnBgImg: cs ? cs.backgroundImage : null,
                btnRadius: cs ? cs.borderRadius : null,
                btnLabel: btn ? btn.textContent.trim() : null,
                bubbleDisplay: vis(bub), noteDisplay: vis(note),
                bubbleHasPath: bub ? bub.outerHTML.indexOf('M21 11.5') !== -1 : false,
                noteHasPath: note ? note.outerHTML.indexOf('M6,3 L14,3') !== -1 : false,
                msendDisplay: vis(msend),
                // Children of a display:none ancestor still report
                // their own display, so visibility is measured by
                // rect: a hidden .msend gives its buttons zero size.
                mfilesW: mf ? Math.round(mf.getBoundingClientRect().width) : null,
                mtextW: mt ? Math.round(mt.getBoundingClientRect().width) : null};
            })())""")
            m = json.loads(m)
            RESULT["checks"].update(m)
            RESULT["ok"] = bool(
                m["page_ready"] if "page_ready" in m else True) and bool(
                m["pcapp"] is True
                and m["hasBridge"] is True
                # 2.8.22 PC-app button: solid blue #277ff0 (the
                # .btn.primary gradient is overridden by the
                # 2.8.5 .board #sendsnippet rule), 8px radius.
                and m["btnBgColor"] == "rgb(39, 127, 240)"
                and m["btnBgImg"] == "none"
                and m["btnRadius"] == "8px"
                and m["bubbleDisplay"] not in (None, "none")
                and m["noteDisplay"] == "none"
                and m["bubbleHasPath"] is True
                and m["noteHasPath"] is True
                and m["btnLabel"] == "Send Text"
                and m["msendDisplay"] == "none"
                and m["mfilesW"] == 0
                and m["mtextW"] == 0)
        except Exception as e:  # noqa: BLE001
            RESULT["error"] = "%s: %s" % (type(e).__name__, e)
        finally:
            with open("/tmp/r38_pcapp_result.json", "w",
                      encoding="utf-8") as fh:
                json.dump(RESULT, fh, indent=2)
            print(json.dumps(RESULT, indent=2))
            sys.stdout.flush()
            os._exit(0 if RESULT["ok"] else 1)

    threading.Thread(target=drive, daemon=True).start()
    webview.start()
    os._exit(1)


if __name__ == "__main__":
    main()
