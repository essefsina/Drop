"""Link-system round-2 regression tests (v2.7.85).

Covers the Nov 1, 2026 user report against v2.7.84:
  - dot (or other unsupported char) in a link name is REJECTED with a
    message, never silently rewritten to a hyphen;
  - an already-sanitised link keeps working unchanged;
  - a client declaring a stale link (X-Drop-Link) gets 401 on file
    endpoints after the link changes, even when the new link is
    unlocked -- the v2.7.84 hole was the tokenless unlocked fallback;
  - a client declaring the current link keeps connecting;
  - the saved password is retrievable (eye icon) only to an authed
    caller, never as bare plaintext in config.json;
  - authstate reports the server's actual runtime port.
Reuses the subprocess-server harness from test_link_folders.
"""
import http.client
import json
import os
import socket
import subprocess
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import dropit  # noqa: E402
from test_link_folders import Client, _free_port  # noqa: E402


@pytest.fixture()
def server(tmp_path):
    home = tmp_path / "home"
    base = tmp_path / "base"
    base.mkdir()
    data = home / ".config" / "DropIt"
    data.mkdir(parents=True)
    port = _free_port()
    env = dict(os.environ, HOME=str(home))
    proc = subprocess.Popen(
        [sys.executable, "dropit.py", "--port", str(port),
         "--dir", str(base)],
        cwd=os.path.join(os.path.dirname(__file__), ".."),
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client = Client(port)
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
        yield client, base, proc, port, home
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _raw(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    hdrs = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    conn.request(method, path, body=data, headers=hdrs)
    resp = conn.getresponse()
    raw = resp.read()
    status = resp.status
    conn.close()
    try:
        return status, json.loads(raw.decode() or "{}")
    except ValueError:
        return status, {}


def test_dot_name_rejected_not_rewritten(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "first"})
    assert status == 200 and j["ok"]
    for bad in ("my.link", "a.b", "has space", "UP!", "x" * 33, "-lead"):
        status, j = client.j("POST", "/api/setlink", {"name": bad})
        assert status == 400, (bad, status, j)
        assert j["ok"] is False
        assert j.get("code") == "invalid_link_name"
        assert "ot" in j["error"] or "etters" in j["error"]
    status, st = client.j("GET", "/api/authstate")
    assert st["link_name"] == "first"  # unchanged, nothing rewritten
    assert not (base / "my-link").exists()
    assert not (base / "my").exists()


def test_display_name_preserved_folder_key_lowercase(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "Essef-Home"})
    assert status == 200 and j["ok"], j
    assert j["display_link"] == "Essef-Home"
    assert j["link"] == "essef-home"
    assert j["folder"] == str(base / "essef-home")
    status, st = client.j("GET", "/api/authstate")
    assert st["link_name"] == "Essef-Home"
    assert st["link_key"] == "essef-home"
    assert "essef-home.local" in st["url"]


def test_stale_link_header_401_after_change_unlocked(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "oldlink"})
    assert status == 200 and j["ok"]
    status, _ = client.upload("oldfile.txt", b"old")
    assert status == 200
    # Old-link client, unlocked link, no token at all: v2.7.84 served
    # it (tokenless unlocked fallback). v2.7.85: declaring the old
    # link after the change must 401.
    status, j = client.j("POST", "/api/setlink", {"name": "newlink"})
    assert status == 200 and j["ok"]
    status, _ = _raw(port, "GET", "/api/files",
                     headers={"X-Drop-Link": "oldlink"})
    assert status == 401, status
    status, files = _raw(port, "GET", "/api/files",
                         headers={"X-Drop-Link": "newlink"})
    assert status == 200, status
    assert files == []  # new link's folder, not oldlink's
    # No-link legacy callers keep the old unlocked behaviour.
    status, files = _raw(port, "GET", "/api/files")
    assert status == 200


def test_empty_save_removes_password_and_eye_retrieval(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "locklink", "password": "s3cret!"})
    assert status == 200 and j["ok"] and j["locked"] is True
    # Guest retrieval is refused with the host-only 403 (v2.7.89:
    # the old drop_locked-cookie proxy for a remote caller is
    # ignored now, so guest-ness is simulated by flipping a
    # login token's role to "guest" in config.json).
    status, j = client.j("POST", "/api/login", {"password": "s3cret!"})
    assert status == 200 and j["ok"], j
    guest_tok = client.cookies["drop_sess"]
    cfg_path = home / ".config" / "DropIt" / "config.json"
    cfg = json.loads(cfg_path.read_text())
    cfg["sessions"][guest_tok]["role"] = "guest"
    cfg_path.write_text(json.dumps(cfg))
    guest = Client(port)
    guest.cookies["drop_sess"] = guest_tok
    status, j = guest.j("GET", "/api/linkpassword")
    assert status == 403 and j.get("code") == "host_only", (status, j)
    # Host re-logs in (fresh host token) for the steps below.
    status, j = client.j("POST", "/api/login", {"password": "s3cret!"})
    assert status == 200 and j["ok"], j
    # Authed (host) retrieval returns the saved password.
    status, j = client.j("GET", "/api/linkpassword")
    assert status == 200 and j["password"] == "s3cret!", j
    # Config must not contain the bare password anywhere.
    cfg_text = (home / ".config" / "DropIt" / "config.json").read_text()
    assert "s3cret!" not in cfg_text
    assert "link_pass_enc" in cfg_text
    # Saving with an empty password removes it.
    status, j = client.j("POST", "/api/setlink",
                         {"name": "locklink", "password": ""})
    assert status == 200 and j["ok"] and j["locked"] is False
    status, st = client.j("GET", "/api/authstate")
    assert st["locked"] is False


def test_authstate_reports_runtime_port(server):
    client, base, proc, port, home = server
    status, st = client.j("GET", "/api/authstate")
    assert status == 200
    assert st["port"] == port
    assert ":%d" % port in st["url"]
