"""Baseline probe for round38: measure + screenshot the CURRENT (2.8.22)
xlsx / picture / video previews with REAL media, before any fix.

Real photo: ~/workspace/user/files/0799a122-f661-4026-a953-7a325bba6869_8_ft2q.jpg (2048x1536)
Real video: ~/workspace/user/files/61234_7_kkgj.mp4 (478x850 portrait)
Writes measurements to /tmp/r38_baseline.json and screenshots to
~/workspace/dropit-proof-round38/baseline_*.
Run: cd ~/workspace/dropit && python3 tests/probe_round38.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from test_link_round2 import _free_port, Client  # noqa: E402
from test_link_round36 import _playwright, _guest_page  # noqa: E402
from test_link_round37 import _host_page, _open_preview, _preview_geom, _close_preview, _make_fixtures, _measure_send_tab  # noqa: E402

PROOF = "/home/hatch/workspace/dropit-proof-round38"
os.makedirs(PROOF, exist_ok=True)

REAL_PHOTO = "/home/hatch/workspace/user/files/0799a122-f661-4026-a953-7a325bba6869_8_ft2q.jpg"
REAL_PHOTO2 = "/home/hatch/workspace/user/files/60992_8_lhdt.jpg"
REAL_VIDEO = "/home/hatch/workspace/user/files/61234_7_kkgj.mp4"


def _xlsx_geom(pg):
    return pg.evaluate("""() => {
      const box = document.querySelector('.previewbox');
      const body = document.querySelector('#previewbody');
      const tbl = body.querySelector('.xlsxview table');
      const br = box.getBoundingClientRect();
      const tr = tbl ? tbl.getBoundingClientRect() : null;
      return {boxW: Math.round(br.width), boxH: Math.round(br.height),
        tblW: tr ? Math.round(tr.width) : null,
        tblH: tr ? Math.round(tr.height) : null,
        bodyScrollW: body.scrollWidth, bodyClientW: body.clientWidth,
        rows: tbl ? tbl.rows.length : 0};
    }""")


def _video_geom(pg):
    return pg.evaluate("""() => {
      const box = document.querySelector('.previewbox');
      const body = document.querySelector('#previewbody');
      const v = body.querySelector('video');
      const br = box.getBoundingClientRect();
      const vr = v ? v.getBoundingClientRect() : null;
      return {boxW: Math.round(br.width), boxH: Math.round(br.height),
        vidW: vr ? Math.round(vr.width) : null,
        vidH: vr ? Math.round(vr.height) : null,
        vidNatW: v ? v.videoWidth : null, vidNatH: v ? v.videoHeight : null,
        ready: v ? v.readyState : null, t: v ? v.currentTime : null};
    }""")


def main():
    # Standalone server (same shape as the pytest `server` fixture in
    # test_link_round2, which cannot be called directly).
    tmp = tempfile.mkdtemp(prefix="r38probe_")
    home = os.path.join(tmp, "home")
    base = os.path.join(tmp, "base")
    os.makedirs(os.path.join(home, ".config", "DropIt"))
    os.makedirs(base)
    port = _free_port()
    env = dict(os.environ, HOME=home)
    proc = subprocess.Popen(
        [sys.executable, "dropit.py", "--port", str(port),
         "--dir", base],
        cwd=os.path.join(os.path.dirname(__file__), ".."),
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client = Client(port)
    out = {}
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                status, _ = client.j("GET", "/api/authstate")
                if status == 200:
                    break
            except OSError:
                pass
            time.sleep(0.2)
        else:
            raise RuntimeError("server did not come up")
        client.j("POST", "/api/setlink", {"name": "r38base"})
        linkdir = os.path.join(base, "r38base")
        _make_fixtures(linkdir)
        shutil.copy(REAL_PHOTO, os.path.join(linkdir, "realphoto.jpg"))
        shutil.copy(REAL_PHOTO2, os.path.join(linkdir, "realportrait.jpg"))
        shutil.copy(REAL_VIDEO, os.path.join(linkdir, "realvideo.mp4"))
        pw = _playwright()
        try:
            # --- xlsx at 1280x800 ---
            browser, pg = _host_page(pw, port)
            try:
                _open_preview(pg, "sheet.xlsx")
                pg.wait_for_timeout(500)
                out["xlsx_1280"] = _xlsx_geom(pg)
                pg.screenshot(path=os.path.join(PROOF, "baseline_xlsx_1280.png"))
                _close_preview(pg)
                # --- real landscape photo 1280x800 ---
                _open_preview(pg, "realphoto.jpg")
                pg.wait_for_timeout(800)
                out["photo_land_1280"] = _preview_geom(pg)
                pg.screenshot(path=os.path.join(PROOF, "baseline_photo_land_1280.png"))
                _close_preview(pg)
                # --- real portrait photo 1280x800 ---
                _open_preview(pg, "realportrait.jpg")
                pg.wait_for_timeout(800)
                out["photo_port_1280"] = _preview_geom(pg)
                pg.screenshot(path=os.path.join(PROOF, "baseline_photo_port_1280.png"))
                _close_preview(pg)
                # --- real video 1280x800 ---
                _open_preview(pg, "realvideo.mp4")
                pg.wait_for_timeout(500)
                pg.evaluate("""() => { const v = document.querySelector('#previewbody video');
                  if (v) { v.currentTime = 5; } }""")
                pg.wait_for_timeout(1200)
                out["video_1280"] = _video_geom(pg)
                pg.screenshot(path=os.path.join(PROOF, "baseline_video_1280.png"))
                _close_preview(pg)
            finally:
                browser.close()
            # --- same at 1920x1080 (bigger desktop) ---
            browser, pg = _host_page(pw, port, width=1920, height=1080)
            try:
                _open_preview(pg, "sheet.xlsx")
                pg.wait_for_timeout(500)
                out["xlsx_1920"] = _xlsx_geom(pg)
                pg.screenshot(path=os.path.join(PROOF, "baseline_xlsx_1920.png"))
                _close_preview(pg)
                _open_preview(pg, "realphoto.jpg")
                pg.wait_for_timeout(800)
                out["photo_land_1920"] = _preview_geom(pg)
                pg.screenshot(path=os.path.join(PROOF, "baseline_photo_land_1920.png"))
                _close_preview(pg)
                _open_preview(pg, "realvideo.mp4")
                pg.wait_for_timeout(500)
                pg.evaluate("""() => { const v = document.querySelector('#previewbody video');
                  if (v) { v.currentTime = 5; } }""")
                pg.wait_for_timeout(1200)
                out["video_1920"] = _video_geom(pg)
                pg.screenshot(path=os.path.join(PROOF, "baseline_video_1920.png"))
                _close_preview(pg)
            finally:
                browser.close()
            # --- mobile-web Upload tab at 390x844 (item 4 baseline) ---
            browser, ctx, pg, fwd = _guest_page(pw, port, 390, 844, light=False)
            try:
                m = _measure_send_tab(pg)
                btns = pg.evaluate("""() => {
                  const g = (id) => { const el = document.querySelector(id);
                    if (!el) return null;
                    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
                    return {w: Math.round(r.width), h: Math.round(r.height),
                      bg: cs.backgroundColor, radius: cs.borderRadius,
                      fs: cs.fontSize, fw: cs.fontWeight,
                      pad: cs.padding, label: el.textContent.trim(),
                      svg: (el.querySelector('svg')||{}).outerHTML ? el.querySelector('svg').getAttribute('viewBox') : null}; };
                  return {files: g('#msendfiles'), text: g('#msendsnippet'),
                    hostSend: g('#sendsnippet')};
                }""")
                out["mobile_upload_390"] = dict(m, **btns)
                pg.screenshot(path=os.path.join(PROOF, "baseline_mobile_upload_390.png"))
            finally:
                ctx.close()
                browser.close()
                fwd.close()
        finally:
            pw.stop()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    with open("/tmp/r38_baseline.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
