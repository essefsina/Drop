"""Real-pywebview end-to-end bridge probe, round37 item (9).

Extends tests/probe_round34_bridge.py for the 2.8.22 "Show in folder"
re-check (Essef Nov 6: still dead on the real PC). Drives the REAL
page in a REAL pywebview window (Qt/WebEngine offscreen) and proves:

  (a) the per-file button renders "Show in folder" and the click
      reaches the real Api.reveal_file (bridge present);
  (b) the spawn is invoked with the right argv AND with DEVNULL
      stdio + close_fds (the 2.8.20 fix) -- Popen args AND kwargs
      are captured, not just args;
  (c) a failure surfaces VISIBLY: with the spawn forced to raise,
      the click ends in a toast naming the recorded error
      ("OSError: boom") and window.__revealTrace records the
      bridge-detail step with that error (no silent death);
  (d) a missing file also surfaces: bridge says no, last_reveal
      records "file not found", the folder-open fallback runs and
      the toast names the reason.

No stubs except Popen itself (recorded, never launched) and the
display (Qt offscreen). Run with the pywebview venv:
  HOME=/tmp/r37b_home QT_QPA_PLATFORM=offscreen \\
    QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu" \\
    /home/hatch/.r36-pwv-venv/bin/python tests/probe_round37_bridge.py
Result JSON is written to /tmp/r37_bridge_result.json; the process
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

RESULT = {"ok": False, "checks": {}, "captured": [], "trace": [],
          "toast_missing": "", "toast_boom": ""}


def main():
    import tempfile
    home = tempfile.mkdtemp(prefix="r37bw_home_")
    base = tempfile.mkdtemp(prefix="r37bw_base_")
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
    boom = {"on": False}

    def fake_popen(args, **kw):
        captured.append({"argv": list(args),
                         "stdin": kw.get("stdin"),
                         "stdout": kw.get("stdout"),
                         "stderr": kw.get("stderr"),
                         "close_fds": kw.get("close_fds")})
        if boom["on"]:
            raise OSError("boom")
        return _FakeProc()

    appmod.subprocess.Popen = fake_popen
    real_spawn = appmod._spawn

    def boom_spawn(argv):
        raise OSError("boom")

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

            # ---- (a)+(b): click the real button -------------------
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
            folder = os.path.join(base, "probeaddr")
            reveal_calls = [c for c in captured
                            if c["argv"] == ["xdg-open", folder]]
            RESULT["checks"]["reveal_argv_seen"] = bool(reveal_calls)
            devnull = appmod.subprocess.DEVNULL
            RESULT["checks"]["reveal_devnull_stdio"] = bool(
                reveal_calls and all(
                    c["stdin"] == devnull and c["stdout"] == devnull
                    and c["stderr"] == devnull
                    and c["close_fds"] is True for c in reveal_calls))
            RESULT["checks"]["server_last_reveal"] = getattr(
                server, "last_reveal", None)

            # ---- (d): missing file surfaces visibly ---------------
            window.evaluate_js(
                "window.__revealTrace = [];"
                "revealFile('no-such-file.txt'); 'called'")
            deadline = time.time() + 15
            toast_missing = ""
            trace2 = []
            while time.time() < deadline:
                try:
                    raw = window.evaluate_js(
                        "JSON.stringify(window.__revealTrace || [])")
                    trace2 = json.loads(raw) if raw else []
                    toast_missing = window.evaluate_js(
                        "document.querySelector('#toast').textContent")
                except Exception:  # noqa: BLE001
                    pass
                if any(s.get("step") == "fallback-folder"
                       for s in trace2):
                    break
                time.sleep(0.3)
            time.sleep(0.3)
            toast_missing = window.evaluate_js(
                "document.querySelector('#toast').textContent")
            RESULT["toast_missing"] = toast_missing
            RESULT["checks"]["missing_trace"] = trace2
            RESULT["checks"]["missing_last_reveal"] = getattr(
                api, "last_reveal", None)

            # ---- (c): forced spawn failure surfaces visibly -------
            boom["on"] = True
            appmod._spawn = boom_spawn
            window.evaluate_js(
                "window.__revealTrace = [];"
                "revealFile('photo test 2.txt'); 'called'")
            deadline = time.time() + 20
            toast_boom = ""
            trace3 = []
            while time.time() < deadline:
                try:
                    raw = window.evaluate_js(
                        "JSON.stringify(window.__revealTrace || [])")
                    trace3 = json.loads(raw) if raw else []
                    toast_boom = window.evaluate_js(
                        "document.querySelector('#toast').textContent")
                except Exception:  # noqa: BLE001
                    pass
                if "boom" in (toast_boom or ""):
                    break
                time.sleep(0.3)
            time.sleep(0.3)
            toast_boom = window.evaluate_js(
                "document.querySelector('#toast').textContent")
            RESULT["toast_boom"] = toast_boom
            RESULT["checks"]["boom_trace"] = trace3
            RESULT["checks"]["boom_last_reveal"] = getattr(
                api, "last_reveal", None)

            RESULT["ok"] = bool(
                title == "Show in folder"
                and RESULT["checks"]["bridge_type"] == "function"
                and RESULT["checks"]["has_bridge"] is True
                and RESULT["checks"]["reveal_argv_seen"]
                and RESULT["checks"]["reveal_devnull_stdio"]
                and any(s.get("step") == "bridge" and s.get("ok") is True
                        for s in trace)
                and (RESULT["checks"]["last_reveal"] or {}).get("ok") is True
                and "file not found" in (toast_missing or "")
                and any(s.get("step") == "bridge-detail"
                        and "file not found" in (s.get("error") or "")
                        for s in trace2)
                and "boom" in (toast_boom or "")
                and "Could not show that file in its folder" in
                (toast_boom or "")
                and any(s.get("step") == "bridge-detail"
                        and "boom" in (s.get("error") or "")
                        for s in trace3))
        except Exception as e:  # noqa: BLE001
            RESULT["error"] = "%s: %s" % (type(e).__name__, e)
        finally:
            with open("/tmp/r37_bridge_result.json", "w",
                      encoding="utf-8") as fh:
                json.dump(RESULT, fh, indent=2)
            appmod.subprocess.Popen = real_popen
            appmod._spawn = real_spawn
            print(json.dumps(RESULT, indent=2))
            sys.stdout.flush()
            os._exit(0 if RESULT["ok"] else 1)

    threading.Thread(target=drive, daemon=True).start()
    webview.start()
    os._exit(1)


if __name__ == "__main__":
    main()
