"""v3.0 round (Essef Nov 7, ~10:30 PM) -- WEB/DESKTOP track only,
local test build only. TWO items, both traced to ONE root cause
the round-56 harness never exercised: it never set an address.

ROOT CAUSE (measured on 2.8.41, address set, 83-file fixture with
30x 12MP photos, desktop-style startup):
  * The AI index was ONE global ai_index.pkl keyed by bare filename,
    while build_index() purges every record whose name is not a file
    in the folder it was given.
  * Startup _preload_ai built server.directory -- the BASE root, which
    holds no files (only the address subfolder) -- so on EVERY restart
    it deleted every verdict for the current address folder and saved
    an empty index. Unit proof: build A (2 files), build empty B,
    load A -> 0 files.
  * The address-folder background build then took ~114s and saved
    ONLY at the very end, so a restart inside that window lost it all.
  * /api/aicheck never persisted its verdict either, so the client's
    own OCR work evaporated too.
  * The web/desktop client keeps verdicts only in memory, so it
    depends entirely on the server index -> re-scans every restart.
    The APK persists verdicts in SharedPreferences -> immune. That
    is exactly the reported asymmetry (APK good, D/PC-web bad).
  * Search: same empty index -> semantic / photo-content queries
    returned 0 results + indexing=True ("still indexing try again
    later"); only filename / document-word queries answered, via the
    live fallback. Measured 2.8.41 with address: 'bicycle' 0.4s,
    0 results, indexing=True -- after a full build AND after restart.

FIX (v3.0):
  * One index file PER shared folder (ai_index_<sha256(folder)>.pkl):
    a build for folder A can never purge folder B's verdicts.
  * _preload_ai targets the CURRENT address folder (_ai_folder).
  * build_index saves after EVERY file: a kill loses at most the
    file in flight, and the next build resumes from saved progress.
  * file_has_text (/api/aicheck) records its verdict in the folder's
    index, so a client scan is durable; ai_state ignores a verdict
    whose mtime/size no longer matches the file (rewritten file).
  * Background-build failures now print a traceback instead of
    dying silently with an empty index forever.
"""
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
import dropit_ai  # noqa: E402
from test_link_round2 import server  # noqa: F401,E402
from test_link_round2 import Client  # noqa: E402
from test_link_round2 import _raw  # noqa: E402

PAGE = D.PAGE
SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py"),
           encoding="utf-8").read()
AI_SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit_ai.py"),
              encoding="utf-8").read()

PROOF = "/home/hatch/workspace/dropit-proof-round57"
os.makedirs(PROOF, exist_ok=True)
REAL83 = "/home/hatch/workspace/dropit-proof-round56/real83"


def test_version_is_3_0():
    assert D.VERSION == "3.0", D.VERSION


def test_page_valid():
    """Interpreted PAGE: both scripts node --check clean, zero lone
    surrogates, UTF-8 clean."""
    tree = ast.parse(SRC)
    page = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "PAGE"
                for t in node.targets):
            page = ast.literal_eval(node.value)
    assert page is not None
    assert not [c for c in page if 0xD800 <= ord(c) <= 0xDFFF]
    page.encode("utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
    assert scripts, "no <script> in PAGE"
    for i, s in enumerate(scripts):
        p = "/tmp/r57_script%d.js" % i
        with open(p, "w", encoding="utf-8") as f:
            f.write(s)
        r = subprocess.run(["node", "--check", p],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[:500]


def test_per_folder_index_isolation(tmp_path):
    """(root cause, unit proof) A build for folder B must never purge
    folder A's index. 2.8.41: build A (2 files), build empty B, load
    A -> 0 files. v3.0: A stays at 2, B stays at 0."""
    a = tmp_path / "A"
    b = tmp_path / "B"
    a.mkdir()
    b.mkdir()
    (a / "hello.txt").write_text("hello world\n")
    (a / "pic.jpg").write_bytes(
        bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"\x00" * 200)
    data = tmp_path / "data"
    data.mkdir()
    assert dropit_ai.build_index(str(a), str(data))["indexed"] == 2
    assert dropit_ai.build_index(str(b), str(data))["indexed"] == 0
    assert len(dropit_ai._load_index(str(a), str(data))["files"]) == 2
    assert len(dropit_ai._load_index(str(b), str(data))["files"]) == 0
    assert dropit_ai._index_path(str(a), str(data)) != \
        dropit_ai._index_path(str(b), str(data))
    assert dropit_ai.ai_state(str(a), str(data), "pic.jpg") == (False, True)
    print("ISOLATION: A=2 after B build; per-folder paths differ")


def test_build_index_noop_does_not_rewrite(tmp_path):
    """(2.8.41 rule, kept) A no-op build leaves the per-folder index
    file byte-identical."""
    d = tmp_path / "shared"
    d.mkdir()
    (d / "a.txt").write_text("hello world\n")
    data = tmp_path / "data"
    data.mkdir()
    dropit_ai.build_index(str(d), str(data))
    p = dropit_ai._index_path(str(d), str(data))
    b1 = open(p, "rb").read()
    m1 = os.stat(p).st_mtime_ns
    time.sleep(0.02)
    r = dropit_ai.build_index(str(d), str(data))
    assert r["embedded_now"] == 0, r
    assert open(p, "rb").read() == b1
    assert os.stat(p).st_mtime_ns == m1


def test_aicheck_verdict_persists(tmp_path):
    """(2) A live /api/aicheck verdict (file_has_text) is recorded in
    the folder's index: an unindexed image reports unknown, then
    known after ONE check, with no background build involved."""
    d = tmp_path / "shared"
    d.mkdir()
    import base64
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    (d / "pic.jpg").write_bytes(png)
    data = tmp_path / "data"
    data.mkdir()
    assert dropit_ai.ai_state(str(d), str(data), "pic.jpg") == (False, False)
    assert dropit_ai.file_has_text(str(d), str(data), "pic.jpg") is False
    assert dropit_ai.ai_state(str(d), str(data), "pic.jpg") == (False, True)
    # a rewritten file invalidates the verdict (mtime/size guard)
    time.sleep(0.02)
    (d / "pic.jpg").write_bytes(png + b"\x00" * 50)
    assert dropit_ai.ai_state(str(d), str(data), "pic.jpg") == (False, False)
    print("AICHECK-PERSIST: unknown -> known after 1 check; rewrite -> unknown")


def test_preload_targets_address_folder(tmp_path, monkeypatch):
    """(1) _preload_ai builds the CURRENT address folder, not the base
    root. With address 'myhome' in config, the address folder's index
    gains the files while the base root's index stays empty."""
    home = tmp_path / "home"
    base = tmp_path / "base"
    addr = base / "myhome"
    addr.mkdir(parents=True)
    (addr / "hello.txt").write_text("hello world\n")
    (addr / "bike_notes.txt").write_text("bike repair checklist\n")
    data = home / ".config" / "DropIt"
    data.mkdir(parents=True)
    (data / "config.json").write_text(json.dumps(
        {"address_name": "myhome", "directory": str(base)}))
    monkeypatch.setenv("HOME", str(home))
    assert D._ai_folder(str(base)) == str(addr)
    D._preload_ai(str(base))
    n_addr = len(dropit_ai._load_index(
        str(addr), str(data))["files"])
    n_base = len(dropit_ai._load_index(
        str(base), str(data))["files"])
    assert n_addr == 2, (n_addr, n_base)
    assert n_base == 0, (n_addr, n_base)
    print("PRELOAD: address folder indexed=%d base=%d" % (n_addr, n_base))


def _restart_server(proc, port, home):
    """Full process restart of the fixture server (same HOME/base)."""
    proc.terminate()
    proc.wait(timeout=10)
    env = dict(os.environ, HOME=str(home))
    p2 = subprocess.Popen(
        [sys.executable, "dropit.py", "--port", str(port),
         "--dir", str(_restart_server.base)],
        cwd=os.path.join(os.path.dirname(__file__), ".."),
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client = Client(port)
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            status, _ = client.j("GET", "/api/authstate")
            if status == 200:
                return p2, client
        except OSError:
            pass
        time.sleep(0.2)
    p2.terminate()
    raise RuntimeError("restarted server did not come up")


def test_sparkle_zero_aicheck_after_restart_with_address(server):
    """(1) End to end, WITH an address set (the 2.8.41 repro never did
    this): after one full build of the address folder, a FULL server
    restart reports every file known in /api/files -- zero
    /api/aicheck calls needed for already-scanned files -- and
    /api/aistatus still shows the full index (2.8.41: indexed=0)."""
    client, base, proc, port, home = server
    _restart_server.base = str(base)
    (base / "hello.txt").write_text("hello world\n")
    (base / "bike_notes.txt").write_text("bike repair checklist\n")
    import base64
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    (base / "pic.jpg").write_bytes(png)
    s, j = client.j("POST", "/api/setlink", {"name": "myhome"})
    assert s == 200 and j["ok"], j
    addr = base / "myhome"
    assert sorted(os.listdir(addr)) == ["bike_notes.txt", "hello.txt", "pic.jpg"]
    data = home / ".config" / "DropIt"
    dropit_ai.build_index(str(addr), str(data))
    s, files = client.j("GET", "/api/files")
    assert s == 200, files
    by_name = {f["name"]: f for f in files}
    assert by_name["hello.txt"]["ai_known"] is True, by_name
    assert by_name["pic.jpg"]["ai_known"] is True, by_name
    proc2, client2 = _restart_server(proc, port, home)
    try:
        s, files = client2.j("GET", "/api/files")
        assert s == 200, files
        unknown = [f for f in files if not f["ai_known"]]
        assert unknown == [], unknown
        s, st = client2.j("GET", "/api/aistatus")
        assert st["indexed"] == 3 and st["pending"] == 0, st
        print("SPARKLE+ADDRESS: restart UNKNOWN 0/3, aistatus indexed=3/3")
    finally:
        proc2.terminate()
        proc2.wait(timeout=10)


def test_search_cold_start_with_address(server):
    """(2) Cold start WITH an address set: the first search answers in
    seconds with real results (live fallback for document words);
    a semantic query ('bicycle' vs 'bike' files) answers once the
    index lands; and after a FULL restart it still answers at once
    with indexing=False -- never stuck on 'still indexing'."""
    client, base, proc, port, home = server
    _restart_server.base = str(base)
    (base / "bike_repair.txt").write_text("bike repair checklist and parts\n")
    (base / "beach_house_notes.txt").write_text(
        "beach house checklist and garden plan\n")
    s, j = client.j("POST", "/api/setlink", {"name": "myhome"})
    assert s == 200 and j["ok"], j
    addr = base / "myhome"
    data = home / ".config" / "DropIt"
    t0 = time.time()
    s, r = client.j("GET", "/api/aisearch?q=beach")
    dt = time.time() - t0
    assert s == 200, r
    assert dt < 20, dt
    names = [x["name"] for x in r["results"]]
    assert "beach_house_notes.txt" in names, r
    print("SEARCH COLD 'beach': %.2fs results=%s indexing=%s"
          % (dt, names, r.get("indexing")))
    # semantic query needs the embedding index: build it (what the
    # background build does), then it must answer
    dropit_ai.build_index(str(addr), str(data))
    t0 = time.time()
    s, r = client.j("GET", "/api/aisearch?q=bicycle")
    dt = time.time() - t0
    assert s == 200, r
    names = [x["name"] for x in r["results"]]
    assert "bike_repair.txt" in names, r
    assert dt < 20, dt
    print("SEARCH 'bicycle' after build: %.2fs results=%s indexing=%s"
          % (dt, names, r.get("indexing")))
    proc2, client2 = _restart_server(proc, port, home)
    try:
        # the restarted server's startup preload holds the build lock
        # for a moment even when the index is already complete; poll
        # briefly for the steady state instead of racing it
        r = None
        dt = 0.0
        deadline = time.time() + 10
        while time.time() < deadline:
            t0 = time.time()
            s, r = client2.j("GET", "/api/aisearch?q=bicycle")
            dt = time.time() - t0
            assert s == 200, r
            if r.get("indexing") is False:
                break
            time.sleep(0.5)
        names = [x["name"] for x in r["results"]]
        assert "bike_repair.txt" in names, r
        assert r.get("indexing") is False, r
        assert dt < 20, dt
        print("SEARCH 'bicycle' after RESTART: %.2fs results=%s indexing=%s"
              % (dt, names, r.get("indexing")))
    finally:
        proc2.terminate()
        proc2.wait(timeout=10)


def test_midkill_build_progress_persists(server):
    """(durability) Kill the server mid-build over a real photo
    folder: the per-folder index must already hold files (2.8.41:
    nothing on disk until the very end), and the restart must resume
    from that progress instead of starting over or wiping it."""
    client, base, proc, port, home = server
    _restart_server.base = str(base)
    s, j = client.j("POST", "/api/setlink", {"name": "myhome"})
    assert s == 200 and j["ok"], j
    addr = base / "myhome"
    # 12 real 12MP photos + a few text files (build ~1 min here)
    for n in sorted(os.listdir(REAL83)):
        if n.startswith("photo_") and n.endswith(".jpg"):
            shutil.copy(os.path.join(REAL83, n), addr / n)
        if len([x for x in os.listdir(addr) if x.endswith(".jpg")]) >= 12:
            break
    for n in ("bike_repair_03.txt", "beach_house_notes.txt"):
        src = os.path.join(REAL83, n)
        if os.path.isfile(src):
            shutil.copy(src, addr / n)
    nfiles = len(os.listdir(addr))
    assert nfiles >= 13, os.listdir(addr)
    data = home / ".config" / "DropIt"
    # trigger the background build exactly as a page load does
    s, files = client.j("GET", "/api/files")
    assert s == 200, files
    time.sleep(45)  # mid-build kill (full build takes ~60s+ here)
    idx = dropit_ai._load_index(str(addr), str(data))
    n_saved = len(idx.get("files", {}))
    print("MIDKILL: %d/%d files persisted at kill time" % (n_saved, nfiles))
    assert n_saved > 0, "no progress persisted mid-build"
    proc2, client2 = _restart_server(proc, port, home)
    try:
        s, st = client2.j("GET", "/api/aistatus")
        assert st["indexed"] == n_saved, st
        assert st["pending"] == nfiles - n_saved, st
        print("MIDKILL RESTART: indexed=%d pending=%d (resumed, not wiped)"
              % (st["indexed"], st["pending"]))
        # let the resumed build finish, then the restart must be clean
        deadline = time.time() + 240
        while time.time() < deadline:
            s, st = client2.j("GET", "/api/aistatus")
            if st.get("pending") == 0 and st.get("indexed") == nfiles:
                break
            time.sleep(10)
        assert st.get("pending") == 0 and st.get("indexed") == nfiles, st
        s, files = client2.j("GET", "/api/files")
        unknown = [f for f in files if not f["ai_known"]]
        assert unknown == [], unknown
        print("MIDKILL DONE: build finished after resume; UNKNOWN 0/%d" % nfiles)
    finally:
        proc2.terminate()
        proc2.wait(timeout=10)
