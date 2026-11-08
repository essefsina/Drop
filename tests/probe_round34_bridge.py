"""Real-pywebview end-to-end bridge probe (round34 item 11).

Runs the ACTUAL desktop shell path -- webview.create_window with
js_api=Api(server), exactly like app.py main() -- under Xvfb, and
drives the REAL page in the REAL window:
  * window.pywebview.api.reveal_file exists in the window,
  * the per-file button renders "Show in folder" (hasBridge true),
  * clicking it reaches the real Api.reveal_file (Popen captured),
  * window.__revealTrace records the click -> bridge steps.

No stubs: the only fakes are Popen itself (recorded, never
launched) and the display (Xvfb). Run with the pywebview venv:
  xvfb-run -a ~/workspace/.pwv-venv/bin/python tests/probe_round34_bridge.py
Result JSON is written to /tmp/r34_bridge_result.json; the process
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

RESULT = {"ok": False, "checks": {}, "captured": [], "trace": []}


def main():
    import tempfile
    home = tempfile.mkdtemp(prefix="r34bw_home_")
    base = tempfile.mkdtemp(prefix="r34bw_base_")
    os.environ["HOME"] = home
    os.makedirs(os.path.join(home, ".config", "DropIt"), exist_ok=True)
    port = _free_port()
    server = dropit.make_server(port, base, desktop=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = Client(port)
    st, j = client.j("POST", "/api/setlink", {"name": "probeaddr"})
    assert st == 200 and j["ok"], j
    client.upload("photo-test.txt", b"photo test content")
    client.upload("photo test 2.txt", b"photo test 2 content")

    captured = []

    class _FakeProc:
        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    real_popen = appmod.subprocess.Popen

    def fake_popen(args, **kw):
        captured.append(list(args))
        return _FakeProc()

    appmod.subprocess.Popen = fake_popen

    import webview
    api = appmod.Api(server)
    window = webview.create_window(
        "Drop", "http://127.0.0.1:%d/" % port,
        width=1280, height=800, js_api=api)

    def drive():
        try:
            deadline = time.time() + 40
            title = None
            while time.time() < deadline:
                try:
                    title = window.evaluate_js(
                        "document.querySelector('[data-dl]') ? "
                        "document.querySelector('[data-dl]')."
                        "getAttribute('title') : 'NO-BUTTON'")
                except Exception as e:  # noqa: BLE001
                    title = "ERR:" + str(e)
                if title == "Show in folder":
                    break
                time.sleep(0.5)
            RESULT["checks"]["button_title"] = title
            RESULT["checks"]["bridge_type"] = window.evaluate_js(
                "typeof window.pywebview !== 'undefined' && "
                "typeof window.pywebview.api.reveal_file")
            RESULT["checks"]["has_bridge"] = window.evaluate_js(
                "typeof hasBridge === 'function' ? hasBridge() : 'no-fn'")
            window.evaluate_js(
                "window.__revealTrace = [];"
                "document.querySelector('[data-dl]').click(); 'clicked'")
            deadline = time.time() + 15
            trace = []
            while time.time() < deadline:
                try:
                    raw = window.evaluate_js(
                        "JSON.stringify(window.__revealTrace || [])")
                    trace = json.loads(raw) if raw else []
                except Exception:  # noqa: BLE001
                    trace = []
                if any(s.get("step") == "bridge" for s in trace):
                    break
                time.sleep(0.3)
            RESULT["trace"] = trace
            RESULT["captured"] = captured
            RESULT["checks"]["last_reveal"] = getattr(
                api, "last_reveal", None)
            expect = os.path.abspath(os.path.join(
                os.path.join(base, "probeaddr"), "photo-test.txt"))
            # The newest file sorts first; the click hit [data-dl]
            # #0, which is the most recently uploaded file.
            newest = os.path.abspath(os.path.join(
                os.path.join(base, "probeaddr"), "photo test 2.txt"))
            RESULT["checks"]["expect_argv"] = ["xdg-open",
                                               os.path.join(base, "probeaddr")]
            RESULT["ok"] = bool(
                title == "Show in folder"
                and RESULT["checks"]["bridge_type"] == "function"
                and RESULT["checks"]["has_bridge"] is True
                # (captured also holds the server's own startup
                # Popen calls -- `ip link`, `ifconfig` for LAN
                # detection -- so match the reveal call anywhere.)
                and any(c == ["xdg-open",
                              os.path.join(base, "probeaddr")]
                        for c in captured)
                and any(s.get("step") == "bridge" and s.get("ok") is True
                        for s in trace)
                and getattr(api, "last_reveal", {}).get("ok") is True)
        except Exception as e:  # noqa: BLE001
            RESULT["error"] = "%s: %s" % (type(e).__name__, e)
        finally:
            with open("/tmp/r34_bridge_result.json", "w",
                      encoding="utf-8") as fh:
                json.dump(RESULT, fh, indent=2)
            appmod.subprocess.Popen = real_popen
            print(json.dumps(RESULT, indent=2))
            sys.stdout.flush()
            os._exit(0 if RESULT["ok"] else 1)

    threading.Thread(target=drive, daemon=True).start()
    webview.start()
    os._exit(1)


if __name__ == "__main__":
    main()
