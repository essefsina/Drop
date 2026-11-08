"""Link-system regression tests (v2.7.84).

Covers the Oct 31, 2026 user report against v2.7.83:
  - a link typed on the link screen actually sets the link and its
    folder (base/<link>/), and the folder switches with the link;
  - switching links never moves/deletes another link's files;
  - changing a link kills every old session token (old clients can
    no longer connect) and the new link's stored password applies;
  - a per-link password is remembered when switching back;
  - Change folder moves where that link's files are saved;
  - a restart never auto-changes the link;
  - lock -> unlock returns the same notes/files for the same link.

Runs a real dropit.py server in a subprocess with an isolated HOME
so the real config/notes paths are exercised, not mocked.
"""
import http.client
import json
import os
import socket
import subprocess
import sys
import time
import urllib.parse

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import dropit  # noqa: E402


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Client:
    def __init__(self, port):
        self.port = port
        self.host = "127.0.0.1"
        self.cookies = {}

    def _call(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=10)
        hdrs = dict(headers or {})
        if self.cookies:
            hdrs["Cookie"] = "; ".join(
                "%s=%s" % kv for kv in self.cookies.items())
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        raw = resp.read()
        for part in (resp.getheader("Set-Cookie") or "").split("\n"):
            pass
        # http.client gives one header per call; collect via getheaders
        conn.close()
        return resp.status, raw

    def call(self, method, path, body=None):
        # Re-issue with cookie capture through a fresh connection that
        # reads all Set-Cookie headers.
        conn = http.client.HTTPConnection(self.host, self.port, timeout=10)
        hdrs = {}
        if self.cookies:
            hdrs["Cookie"] = "; ".join(
                "%s=%s" % kv for kv in self.cookies.items())
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        raw = resp.read()
        for k, v in resp.getheaders():
            if k.lower() == "set-cookie":
                name, _, rest = v.partition("=")
                val = rest.split(";")[0]
                if "Max-Age=0" in v:
                    self.cookies.pop(name, None)
                elif val:
                    self.cookies[name] = val
        status = resp.status
        conn.close()
        return status, raw

    def j(self, method, path, body=None):
        status, raw = self.call(method, path, body)
        try:
            return status, json.loads(raw.decode() or "{}")
        except ValueError:
            return status, {}

    def upload(self, name, content):
        boundary = "----testboundary"
        body = (
            ("--%s\r\nContent-Disposition: form-data; name=\"file\"; "
             "filename=\"%s\"\r\nContent-Type: text/plain\r\n\r\n")
            % (boundary, name)).encode() + content + \
            ("\r\n--%s--\r\n" % boundary).encode()
        conn = http.client.HTTPConnection(self.host, self.port, timeout=10)
        hdrs = {"Content-Type": "multipart/form-data; boundary=%s" % boundary}
        if self.cookies:
            hdrs["Cookie"] = "; ".join(
                "%s=%s" % kv for kv in self.cookies.items())
        conn.request("POST", "/api/upload", body=body, headers=hdrs)
        resp = conn.getresponse()
        raw = resp.read()
        status = resp.status
        conn.close()
        return status, raw


@pytest.fixture()
def server(tmp_path):
    home = tmp_path / "home"
    base = tmp_path / "base"
    base.mkdir()
    data = home / ".config" / "DropIt"
    data.mkdir(parents=True)
    # Pre-v2.7.84 single-folder data: one legacy file + one legacy note.
    (base / "legacy.txt").write_text("legacy file")
    (data / "notes.json").write_text(json.dumps(
        [{"id": "n1", "text": "keep me", "created": 1}]))
    port = _free_port()
    env = dict(os.environ, HOME=str(home))
    proc = subprocess.Popen(
        [sys.executable, "dropit.py", "--port", str(port),
         "--dir", str(base)],
        cwd=os.path.join(os.path.dirname(__file__), ".."),
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client = Client(port)
    # "remote" is a second localhost client. The sandbox blocks
    # non-localhost TCP, so a real LAN-IP client cannot connect
    # here; tests that need a guest flip the remote token's role
    # to "guest" in config.json (see _flip_role) -- v2.7.89, the
    # drop_locked cookie is ignored for host identity and no
    # longer simulates a remote caller.
    remote = Client(port)
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
        yield client, base, proc, port, home, remote
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _flip_role(home, token, role):
    """Flip a session token's role in config.json (LAN-guest
    simulation: the sandbox blocks non-localhost TCP, so a real
    LAN client cannot connect here; the role stamp is exactly
    what the server checks for guest vs host)."""
    cfg_path = os.path.join(str(home), ".config", "DropIt", "config.json")
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    assert token in cfg.get("sessions", {}), "token not in sessions"
    cfg["sessions"][token]["role"] = role
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)


def _guest_tokens(home):
    cfg_path = os.path.join(str(home), ".config", "DropIt", "config.json")
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    return [t for t, s in (cfg.get("sessions") or {}).items()
            if isinstance(s, dict) and s.get("role") == "guest"]


def test_sanitise_link():
    assert dropit._sanitise_address("My Link!") == "my-link"
    assert dropit._sanitise_address("  ESSEF--home ") == "essef-home"
    assert dropit._sanitise_address("!!!") == ""
    assert dropit._sanitise_address("a") == "a"


def test_link_switch_folders_tokens_passwords(server):
    client, base, proc, port, home, remote = server

    # 1. First link: valid name, folder created, legacy file adopted.
    # (v2.7.85: setlink accepts a valid name as typed; "My Link!"
    # would now be rejected -- see test_link_round2 dot/invalid tests.)
    status, j = client.j("POST", "/api/setlink", {"name": "my-link"})
    assert status == 200 and j["ok"], j
    assert j["link"] == "my-link"
    assert j["folder"] == str(base / "my-link")
    assert (base / "my-link" / "legacy.txt").read_text() == "legacy file"
    assert not (base / "legacy.txt").exists()
    # Legacy note adopted into this link's notes.
    status, notes = client.j("GET", "/api/notes")
    assert status == 200
    assert [n["text"] for n in notes] == ["keep me"]

    # 2. A file saved under link A.
    status, _ = client.upload("afile.txt", b"aaa")
    assert status == 200, status
    assert (base / "my-link" / "afile.txt").exists()

    # 3. Password for link A, then a login token for it.
    status, j = client.j("POST", "/api/setlinkpassword",
                         {"password": "pw123"})
    assert status == 200 and j["ok"], j
    status, j = client.j("POST", "/api/login", {"password": "pw123"})
    assert status == 200 and j["ok"], j
    assert client.cookies.get("drop_sess")
    status, files = client.j("GET", "/api/files")
    assert status == 200
    assert "afile.txt" in [f["name"] for f in files]

    # 4. Change the link to a PASSWORD-PROTECTED new link, using a
    #    remote (non-host) client holding link A's token: that token
    #    must die, and link A's folder must be left untouched.
    #    v2.7.89: the remote client is a guest by ROLE (flipped in
    #    config) -- the old drop_locked-cookie proxy is ignored for
    #    host identity now, so the cookie alone no longer makes a
    #    localhost caller a guest. A cleared guest token cannot
    #    401 over localhost TCP (the PC host fallback applies to
    #    tokenless localhost callers), so "token died" is asserted
    #    on the host's session list here; the LAN 401 itself is
    #    covered by the in-process LAN-address tests in
    #    test_link_round5.py.
    status, j = remote.j("POST", "/api/login", {"password": "pw123"})
    assert status == 200 and j["ok"], j
    _flip_role(home, remote.cookies["drop_sess"], "guest")
    status, j = client.j("POST", "/api/setlink",
                         {"name": "second", "password": "secondpw"})
    assert status == 200 and j["ok"], j
    assert j["folder"] == str(base / "second")
    assert (base / "second").is_dir()
    assert (base / "my-link" / "afile.txt").exists()
    assert _guest_tokens(home) == []  # old guest token died
    status, st = remote.j("GET", "/api/authstate")
    assert st["link_name"] == "second" and st["locked"] is True
    status, j = remote.j("POST", "/api/login", {"password": "nope"})
    assert status == 200 and j["ok"] is False
    status, j = remote.j("POST", "/api/login", {"password": "secondpw"})
    assert status == 200 and j["ok"], j
    _flip_role(home, remote.cookies["drop_sess"], "guest")
    status, files = remote.j("GET", "/api/files")
    assert status == 200 and files == []  # new link's folder, not A's

    # 5. Switch back to link A. v2.7.86: a guest/remote caller may
    #    NOT redefine the host's link any more -- it gets 403 with
    #    the host-only message even when authenticated, and the link
    #    is unchanged. The HOST switches back (no password key: a
    #    known link keeps its stored password). Link B's folder stays
    #    intact, and link A's own password (pw123) applies again.
    status, _ = remote.upload("bfile.txt", b"bbb")
    assert status == 200
    assert (base / "second" / "bfile.txt").exists()
    status, j = remote.j("POST", "/api/setlink", {"name": "my-link"})
    assert status == 403 and j["ok"] is False, j
    assert j.get("code") == "host_only"
    assert "Only the host can change this" in j["error"]
    status, st = client.j("GET", "/api/authstate")
    assert st["link_name"] == "second"  # unchanged by the guest call
    status, j = client.j("POST", "/api/setlink", {"name": "my-link"})
    assert status == 200 and j["ok"], j
    assert j["folder"] == str(base / "my-link")
    assert (base / "second" / "bfile.txt").exists()  # B untouched
    assert _guest_tokens(home) == []  # token died with the link change
    status, st = remote.j("GET", "/api/authstate")
    assert st["locked"] is True
    status, j = remote.j("POST", "/api/login", {"password": "nope"})
    assert status == 200 and j["ok"] is False
    status, j = remote.j("POST", "/api/login", {"password": "pw123"})
    assert status == 200 and j["ok"], j
    status, files = remote.j("GET", "/api/files")
    assert "afile.txt" in [f["name"] for f in files]
    status, notes = remote.j("GET", "/api/notes")
    assert [n["text"] for n in notes] == ["keep me"]

    # 6. Change folder for the current link: saves move there.
    custom = base / "custom"
    status, j = client.j("POST", "/api/setlinkfolder",
                         {"folder": str(custom)})
    assert status == 200 and j["ok"] and j["folder"] == str(custom), j
    status, _ = client.upload("cfile.txt", b"ccc")
    assert status == 200
    assert (custom / "cfile.txt").exists()
    status, st = client.j("GET", "/api/authstate")
    assert st["folder"] == str(custom)

    # 7. Lock -> unlock returns the same notes/files for this link.
    #    v2.7.89 GUEST-ONLY LOCK: a host logout no longer locks the
    #    host out of its own link (the drop_locked cookie is
    #    ignored), so the host's files still read 200 after logout
    #    -- the guest 401 on logout is covered by the LAN-address
    #    unit tests in test_link_round5.py, not by localhost TCP.
    status, j = remote.j("POST", "/api/logout", {})
    assert status == 200
    status, _ = remote.j("GET", "/api/files")
    assert status == 200
    status, j = remote.j("POST", "/api/login", {"password": "pw123"})
    assert status == 200 and j["ok"]
    status, files = remote.j("GET", "/api/files")
    assert "cfile.txt" in [f["name"] for f in files]
    status, notes = remote.j("GET", "/api/notes")
    assert [n["text"] for n in notes] == ["keep me"]


def test_restart_keeps_link(server):
    client, base, proc, port, home, remote = server
    status, j = client.j("POST", "/api/setlink", {"name": "essef"})
    assert status == 200 and j["ok"]
    status, j = client.j("POST", "/api/setlinkfolder",
                         {"folder": str(base / "essef-custom")})
    assert status == 200 and j["ok"]
    proc.terminate()
    proc.wait(timeout=5)
    port2 = _free_port()
    env = dict(os.environ, HOME=str(home))
    proc2 = subprocess.Popen(
        [sys.executable, "dropit.py", "--port", str(port2),
         "--dir", str(base)],
        cwd=os.path.join(os.path.dirname(__file__), ".."),
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        client2 = Client(port2)
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                status, st = client2.j("GET", "/api/authstate")
                if status == 200:
                    break
            except OSError:
                pass
            time.sleep(0.2)
        assert st["link_name"] == "essef"
        assert st["folder"] == str(base / "essef-custom")
        assert "essef.local" in st["url"]
    finally:
        proc2.terminate()
        try:
            proc2.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc2.kill()
