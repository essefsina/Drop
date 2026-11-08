"""Desktop-app host proof via the pywebview JS bridge (v2.7.88).

Bug (Nov 1, 2026, user-confirmed): on the DESKTOP APP on his PC,
the "Your link" screen showed the GUEST connect-only screen
("Link to connect to") instead of the full host screen, even
though the desktop window runs on the host PC. Loopback origin
alone was the only host proof, so any desktop-window load that did
not arrive as 127.0.0.1/::1 (LAN IP / .local navigation, mapped
loopback, proxy) was stamped guest.

Fix: the server generates a random host token held ONLY in server
memory and hands it to the pywebview window ONLY via its local JS
bridge (Api.host_token). The page sends it as X-Drop-Host. LAN
guests have no bridge and can never obtain it; a forged host claim
without it is still a guest.

These tests run the server in-process (so the test can read
server.host_token, exactly as the desktop app's bridge would) and
prove, over real HTTP:
  - a guest-stamped session + locked cookie (the LAN-guest
    stand-in) gets 403 host-only on admin endpoints WITHOUT the
    bridge token, and the password is unchanged;
  - the SAME guest-stamped session WITH the correct bridge token
    is recognised as host and admin succeeds;
  - a WRONG bridge token does not upgrade anyone;
  - the bridge token never appears in any API response, page
    HTML, or config file.
"""

import http.client
import json
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import dropit  # noqa: E402
from test_link_folders import Client, _free_port  # noqa: E402
from test_link_round3 import _flip_role, _guest_client  # noqa: E402

HOST_ONLY = "Only the host can change this - change it on the desktop"


@pytest.fixture()
def bridge_server(tmp_path, monkeypatch):
    home = tmp_path / "home"
    base = tmp_path / "base"
    base.mkdir()
    (home / ".config" / "DropIt").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    port = _free_port()
    server = dropit.make_server(port, str(base), desktop=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
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
        yield client, base, server, port, home
    finally:
        server.shutdown()
        server.server_close()


def _raw(port, method, path, body=None, headers=None, cookies=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    hdrs = dict(headers or {})
    if cookies:
        hdrs["Cookie"] = "; ".join("%s=%s" % kv for kv in cookies.items())
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


def test_bridge_token_upgrades_guest_stamped_session_to_host(bridge_server):
    client, base, server, port, home = bridge_server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "bridge1", "password": "pw123"})
    assert status == 200 and j["ok"], j
    # LAN-guest stand-in: guest-stamped token. Note the bridge token
    # must NOT bypass a lock, so the locked cookie that
    # _guest_client sets is removed here: this session is authed
    # but guest-stamped and unlocked, exactly the desktop window
    # wrongly stamped guest in v2.7.87.
    guest = _guest_client(port, "pw123")
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    guest.cookies.pop("drop_locked", None)
    # Without the bridge token: host-only 403, as in round 3/4.
    status, j = guest.j("POST", "/api/setlinkpassword",
                        {"password": "hacked"})
    assert status == 403 and j.get("code") == "host_only", j
    # With a WRONG bridge token: still 403.
    status, j = _raw(port, "POST", "/api/setlinkpassword",
                     {"password": "hacked"},
                     headers={"X-Drop-Host": "wrong-token"},
                     cookies=guest.cookies)
    assert status == 403 and j.get("code") == "host_only", j
    # With the CORRECT bridge token (only the desktop bridge can
    # hand this out): the same session is host, admin succeeds.
    status, j = _raw(port, "POST", "/api/setlinkpassword",
                     {"password": "newpw"},
                     headers={"X-Drop-Host": server.host_token},
                     cookies=guest.cookies)
    assert status == 200 and j["ok"], j
    # And the password really changed (host login proves it).
    status, j = client.j("POST", "/api/login", {"password": "newpw"})
    assert status == 200 and j["ok"], j


def test_bridge_token_never_leaked(bridge_server):
    client, base, server, port, home = bridge_server
    assert server.host_token and len(server.host_token) >= 32
    status, j = client.j("POST", "/api/setlink", {"name": "leak1"})
    assert status == 200 and j["ok"], j
    status, st = client.j("GET", "/api/authstate")
    assert status == 200
    assert server.host_token not in json.dumps(st)
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/")
    html = conn.getresponse().read().decode("utf-8")
    conn.close()
    assert server.host_token not in html
    cfg_path = os.path.join(str(home), ".config", "DropIt", "config.json")
    with open(cfg_path, encoding="utf-8") as f:
        assert server.host_token not in f.read()
    # app.py bridge exposes it only to the desktop window.
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    import app as drop_app  # noqa: E402
    api = drop_app.Api(server)
    assert api.host_token() == server.host_token
