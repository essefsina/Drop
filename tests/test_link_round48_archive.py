"""v2.8.33 round -- (8) ZIP + RAR ARCHIVE VIEWING (listing only).

A .zip or .rar clicked in Drop shows its contents (names, sizes,
folders) in-app, web + PC app. ZIP via stdlib zipfile; RAR via the
bundled pure-stdlib header parsers in dropit.py (RAR4 + RAR5) --
no rarfile / unrar / 7z binary on the machine, so the reader is
bundled and the installer stays zero-setup. LISTING ONLY:
opening / extracting a single file from inside is a later step.
Corrupt / unsupported archives show a clear error, never crash.

Server endpoint (also the one the APK track calls):
    GET /api/archive/?file=<url-encoded file name>
    -> {"ok": true, "entries": [{"name": ..., "size": ..., "is_dir": false}]}
    -> {"ok": false, "error": ...}  (400 bad extension / corrupt,
       404 missing, 401 unauthed)
Guest token may travel as ?token= (same bearer rule as /dl/) or
via the X-Drop-Token header / drop_sess cookie. Listing is a
view-only preview (like /api/docx/ and /api/xlsx/): an authed
guest may list even without download_files -- the preview's
Download button still enforces that permission.

Caveat: the RAR fixtures below are hand-built per the RAR 4.x /
5.0 header specs (no WinRAR-produced file exists on this machine
and no unrar/7z binary is available to cross-check), so the RAR
parsers are validated against spec-conformant bytes, not a
WinRAR-produced archive.
"""
import ast
import json
import os
import re
import struct
import subprocess
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
from test_link_round2 import server, _raw  # noqa: F401,E402
from test_link_round16 import _guest, _set_perms, ALL_ON  # noqa: E402
from test_link_round34 import _Fwd  # noqa: E402
from test_link_round36 import _playwright  # noqa: E402
from test_link_round37 import _host_page, _open_preview, _close_preview  # noqa: E402

SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py"),
           encoding="utf-8").read()
PAGE = D.PAGE

PROOF = "/home/hatch/workspace/dropit-proof-round48"
os.makedirs(PROOF, exist_ok=True)

PW = "Essef2026!"


# ---- fixtures: hand-built spec-conformant archives --------------------

def _build_zip_bytes():
    buf = zipfile.ZipFile.__new__(zipfile.ZipFile)
    import io
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as z:
        z.writestr("docs/", "")
        z.writestr("docs/readme.txt", "hello")
        z.writestr("photo.jpg", b"\x00" * 1234)
        z.writestr("café.txt", "x")
    return bio.getvalue()


def _rar4_bytes(main=True, entries=True):
    out = bytearray(b"Rar!\x1a\x07\x00")

    def block(htype, flags, body, data=b""):
        # HEAD_SIZE counts the header only (7-byte prefix + body);
        # the data is skipped by PACK_SIZE, not by HEAD_SIZE.
        size = 7 + len(body)
        out.extend(struct.pack("<HBHH", 0, htype, flags, size))
        out.extend(body)
        out.extend(data)

    if main:
        block(0x73, 0, struct.pack("<HH", 0, 0))
    if entries:
        def fentry(name, data, attr=0x20, flags=0):
            nb = name.encode("utf-8")
            body = struct.pack("<IIBIIBBHI", len(data), len(data), 3, 0, 0,
                               20, 0x30, len(nb), attr)
            assert len(body) == 25
            block(0x74, flags, body + nb, data)
        fentry("docs", b"", attr=0x10)
        fentry("docs/readme.txt", b"hello")
        fentry("café.txt", b"xx", flags=0x0200)
        fentry("big.bin", b"\x00" * 5000)
    return bytes(out)


def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _rar5_bytes():
    out = bytearray(b"Rar!\x1a\x07\x01\x00")

    def block(htype, fields):
        out.extend(b"\x00\x00\x00\x00")
        out.extend(_varint(len(fields)))
        out.extend(fields)

    block(1, _varint(1) + _varint(0) + _varint(0))  # main header

    def fentry(name, data, attr=0x20, flags=0x01):
        nb = name.encode("utf-8")
        fields = (_varint(2) + _varint(flags) + _varint(len(data))
                  + _varint(attr) + _varint(0) + _varint(3)
                  + _varint(len(nb)) + nb + _varint(0))
        if flags & 0x01:
            fields += _varint(len(data))
        block(2, fields)
        out.extend(data)

    def service(name, data):
        nb = name.encode("utf-8")
        fields = (_varint(3) + _varint(0x01) + _varint(len(data))
                  + _varint(0) + _varint(0) + _varint(3)
                  + _varint(len(nb)) + nb + _varint(0)
                  + _varint(len(data)))
        block(3, fields)
        out.extend(data)

    fentry("docs", b"", attr=0x10, flags=0x00)
    fentry("docs/readme.txt", b"hello")
    fentry("café.txt", b"xx")
    service("comment", b"hello")  # service header: skipped, not listed
    fentry("big.bin", b"\x00" * 5000)
    block(5, _varint(5) + _varint(0) + _varint(0))  # end of archive
    return bytes(out)


def _write_archive_fixtures(linkdir):
    with open(os.path.join(linkdir, "test.zip"), "wb") as fh:
        fh.write(_build_zip_bytes())
    with open(os.path.join(linkdir, "test.rar"), "wb") as fh:
        fh.write(_rar4_bytes())
    with open(os.path.join(linkdir, "test5.rar"), "wb") as fh:
        fh.write(_rar5_bytes())
    with open(os.path.join(linkdir, "bad.zip"), "wb") as fh:
        fh.write(b"not a zip at all")
    with open(os.path.join(linkdir, "bad.rar"), "wb") as fh:
        fh.write(b"Rar!\x1a\x07\x00" + b"\x00" * 50)
    with open(os.path.join(linkdir, "cut.rar"), "wb") as fh:
        # Cut mid-file-header (last file's data + end header +
        # 4 bytes of its header) -- a cut that only chops data
        # still lists fine (names come from headers), so the
        # error case has to land inside a header.
        data = _rar5_bytes()
        fh.write(data[:len(data) - 5000 - 8 - 4])


# ---- source facts ------------------------------------------------------

def test_version_is_2_8_33():
    assert D.VERSION == "2.8.33"


def test_interpreted_page_valid_js_no_surrogates():
    for n in ast.walk(ast.parse(SRC)):
        if isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "PAGE" for t in n.targets):
            page = n.value.value
            break
    assert not [c for c in page if 0xD800 <= ord(c) <= 0xDFFF]
    page.encode("utf-8")
    for js in re.findall(r"<script>(.*?)</script>", page, re.S):
        p = "/tmp/r48_arch_check.js"
        open(p, "w", encoding="utf-8").write(js)
        out = subprocess.run(["node", "--check", p],
                             capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr
    assert "/api/archive/?file=" in PAGE
    assert ".archrow" in PAGE


# ---- unit: archive_to_entries -----------------------------------------

def test_zip_lists_entries(tmp_path):
    p = tmp_path / "a.zip"
    p.write_bytes(_build_zip_bytes())
    got = D.archive_to_entries(str(p))
    assert got == [
        {"name": "docs/", "size": 0, "is_dir": True},
        {"name": "docs/readme.txt", "size": 5, "is_dir": False},
        {"name": "photo.jpg", "size": 1234, "is_dir": False},
        {"name": "café.txt", "size": 1, "is_dir": False},
    ]


def test_rar4_lists_entries(tmp_path):
    p = tmp_path / "a.rar"
    p.write_bytes(_rar4_bytes())
    got = D.archive_to_entries(str(p))
    assert got == [
        {"name": "docs", "size": 0, "is_dir": True},
        {"name": "docs/readme.txt", "size": 5, "is_dir": False},
        {"name": "café.txt", "size": 2, "is_dir": False},
        {"name": "big.bin", "size": 5000, "is_dir": False},
    ]


def test_rar5_lists_entries_and_skips_service(tmp_path):
    p = tmp_path / "a.rar"
    p.write_bytes(_rar5_bytes())
    got = D.archive_to_entries(str(p))
    assert got == [
        {"name": "docs", "size": 0, "is_dir": True},
        {"name": "docs/readme.txt", "size": 5, "is_dir": False},
        {"name": "café.txt", "size": 2, "is_dir": False},
        {"name": "big.bin", "size": 5000, "is_dir": False},
    ]
    assert all(e["name"] != "comment" for e in got)


def test_archive_errors(tmp_path):
    p = tmp_path / "bad.zip"
    p.write_bytes(b"not a zip at all")
    with pytest.raises(ValueError):
        D.archive_to_entries(str(p))
    p = tmp_path / "bad.rar"
    p.write_bytes(b"Rar!\x1a\x07\x00" + b"\x00" * 50)
    with pytest.raises(ValueError):
        D.archive_to_entries(str(p))
    p = tmp_path / "empty.rar"
    p.write_bytes(b"")
    with pytest.raises(ValueError):
        D.archive_to_entries(str(p))
    p = tmp_path / "cut.rar"
    data = _rar5_bytes()
    p.write_bytes(data[:len(data) - 5000 - 8 - 4])  # mid-file-header
    with pytest.raises(ValueError):
        D.archive_to_entries(str(p))
    # No main header at all (header-encrypted style): unreadable.
    p = tmp_path / "nomain.rar"
    p.write_bytes(_rar4_bytes(main=False))
    with pytest.raises(ValueError):
        D.archive_to_entries(str(p))
    p = tmp_path / "a.7z"
    p.write_bytes(b"7z" + b"\x00" * 20)
    with pytest.raises(ValueError):
        D.archive_to_entries(str(p))


# ---- HTTP: /api/archive/ ----------------------------------------------

def _get_json(port, path, headers=None):
    # _raw returns (status, parsed-json-or-{}).
    return _raw(port, "GET", path, headers=headers or {})


def test_archive_endpoint_zip_and_rar(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "r48arch"})
    assert status == 200 and j["ok"], j
    _write_archive_fixtures(os.path.join(str(base), "r48arch"))
    status, j = _get_json(port, "/api/archive/?file=test.zip")
    assert status == 200 and j["ok"], j
    assert [e["name"] for e in j["entries"]] == [
        "docs/", "docs/readme.txt", "photo.jpg", "café.txt"]
    assert j["entries"][2] == {"name": "photo.jpg", "size": 1234,
                               "is_dir": False}
    assert j["entries"][0]["is_dir"] is True
    # name= alias works too.
    status, j = _get_json(port, "/api/archive/?name=test.rar")
    assert status == 200 and j["ok"], j
    assert [e["name"] for e in j["entries"]] == [
        "docs", "docs/readme.txt", "café.txt", "big.bin"]
    status, j = _get_json(port, "/api/archive/?file=test5.rar")
    assert status == 200 and j["ok"], j
    assert [e["name"] for e in j["entries"]] == [
        "docs", "docs/readme.txt", "café.txt", "big.bin"]


def test_archive_endpoint_errors(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "r48arch2"})
    assert status == 200 and j["ok"], j
    _write_archive_fixtures(os.path.join(str(base), "r48arch2"))
    status, j = _get_json(port, "/api/archive/?file=missing.zip")
    assert status == 404 and j["ok"] is False, j
    status, j = _get_json(port, "/api/archive/?file=notes.txt")
    assert status == 400 and j["ok"] is False and "only" in j["error"], j
    status, j = _get_json(port, "/api/archive/?file=bad.zip")
    assert status == 400 and j["ok"] is False and j["error"], j
    status, j = _get_json(port, "/api/archive/?file=bad.rar")
    assert status == 400 and j["ok"] is False and j["error"], j
    status, j = _get_json(port, "/api/archive/?file=cut.rar")
    assert status == 400 and j["ok"] is False and j["error"], j


def test_archive_endpoint_locked_unauth_401(server):
    # Loopback callers get the host bypass, so an unauthenticated
    # 401 can only be observed through _Fwd (server sees 127.0.0.2).
    import http.client
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "r48arch3", "password": PW})
    assert status == 200 and j["ok"], j
    _write_archive_fixtures(os.path.join(str(base), "r48arch3"))
    fwd = _Fwd(port)
    try:
        conn = http.client.HTTPConnection("127.0.0.3", fwd.port, timeout=10)
        conn.request("GET", "/api/archive/?file=test.zip")
        resp = conn.getresponse()
        body = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 401, resp.status
        assert body["need_auth"] is True
        conn.close()
    finally:
        fwd.close()


def test_archive_endpoint_guest_token_and_no_download_perm(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "r48arch4", "password": PW})
    assert status == 200 and j["ok"], j
    _write_archive_fixtures(os.path.join(str(base), "r48arch4"))
    guest = _guest(port, home, PW)
    # Guest may list even with download_files OFF (view-only
    # preview rule, like docx/xlsx); the real download still 403s.
    _set_perms(client, {**ALL_ON, "download_files": False})
    status, j = _get_json(
        port, "/api/archive/?file=test.zip",
        headers={"X-Drop-Token": guest.cookies["drop_sess"]})
    assert status == 200 and j["ok"], j
    assert len(j["entries"]) == 4
    # Same token in the URL (?token=) -- the APK calling convention.
    status, j = _get_json(
        port, "/api/archive/?file=test.rar&token="
              + guest.cookies["drop_sess"])
    assert status == 200 and j["ok"], j
    assert [e["name"] for e in j["entries"]][0] == "docs"
    status, _j = _raw(
        port, "GET", "/dl/test.zip",
        headers={"Cookie": "drop_sess=" + guest.cookies["drop_sess"]})
    assert status == 403, status


# ---- UI: click a .zip / .rar row, see the contents --------------------

def _archive_rows(pg):
    return pg.evaluate("""() => {
      const pop = document.querySelector('#previewpop');
      const rows = [...document.querySelectorAll('.archrow')].map(r => r.textContent.trim());
      return {open: pop && pop.classList.contains('open'), rows};
    }""")


def test_archive_preview_zip_ui(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r48archui"})
    _write_archive_fixtures(os.path.join(str(base), "r48archui"))
    pw = _playwright()
    try:
        browser, pg = _host_page(pw, port)
        try:
            _open_preview(pg, "test.zip")
            pg.wait_for_timeout(1500)
            m = _archive_rows(pg)
            assert m["open"] is True, m
            assert len(m["rows"]) == 4, m
            assert any("docs/readme.txt" in r for r in m["rows"]), m
            assert any("photo.jpg" in r and "1.2 KB" in r for r in m["rows"]), m
            pg.screenshot(path=os.path.join(PROOF, "r48_archive_zip.png"))
        finally:
            browser.close()
    finally:
        pw.stop()


def test_archive_preview_rar_ui(server):
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "r48archui2"})
    _write_archive_fixtures(os.path.join(str(base), "r48archui2"))
    pw = _playwright()
    try:
        browser, pg = _host_page(pw, port)
        try:
            _open_preview(pg, "test.rar")
            pg.wait_for_timeout(1500)
            m = _archive_rows(pg)
            assert m["open"] is True, m
            assert len(m["rows"]) == 4, m
            assert any("café.txt" in r for r in m["rows"]), m
            pg.screenshot(path=os.path.join(PROOF, "r48_archive_rar.png"))
            # Corrupt zip: clear error in the preview, no crash.
            _close_preview(pg)
            _open_preview(pg, "bad.zip")
            pg.wait_for_timeout(1500)
            msg = pg.evaluate(
                "() => document.querySelector('#previewbody').textContent")
            assert "Could not list" in msg or "ZIP" in msg, msg
            assert "use Download to open it" in msg, msg
            pg.screenshot(path=os.path.join(PROOF, "r48_archive_bad.png"))
        finally:
            browser.close()
    finally:
        pw.stop()
