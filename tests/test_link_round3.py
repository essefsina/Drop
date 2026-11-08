"""Link-system round-3 regression tests (v2.7.86).

Covers the Nov 1, 2026 host-only admin decision, which reverses the
v2.7.85 opening (any authed viewer could redefine the link):

  - a guest token (stamped "guest" at login) gets 403 + the host-only
    message on EVERY privileged endpoint -- setlink, setlinkpassword,
    setlinkfolder, linkpassword reveal, sessions list/revoke -- even
    when authenticated, while guest USE (files, upload) still works;
  - a host token presented with the drop_locked cookie (the harness's
    stand-in for a non-host origin) is also denied;
  - the host still gets 200 on all of the above;
  - POST /api/connect (guest connect-to) verifies a clean link name
    like "10-30-99" without changing anything on the host, and
    refuses a wrong link with 409;
  - changing the password clears GUEST sessions but keeps host ones;
  - the saved password is revealable by the host only, and never
    appears as bare plaintext in config.json;
  - the served page carries the open-link warning, a single "Save"
    button (no "Connect / Save link", no "Done", no "Save Link"),
    Open/Change folder side by side under the folder field in the
    Shared-Files-tab colours, and no user-visible ".local" address.
Reuses the subprocess-server harness from test_link_round2.
"""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_link_folders import Client  # noqa: E402
from test_link_round2 import _raw, server  # noqa: E402,F401

HOST_ONLY = "Only the host can change this - change it on the desktop"


def _guest_client(port, password):
    """A client holding a login token stamped 'guest' (as a real LAN
    phone's token would be). The sandbox cannot make a real LAN-IP
    connection, so the stamp is flipped in config.json after a
    localhost login -- the stamp is exactly what the server checks."""
    guest = Client(port)
    status, j = guest.j("POST", "/api/login", {"password": password})
    assert status == 200 and j["ok"], j
    # Stand-in for a non-host origin (as in test_link_folders): the
    # drop_locked cookie disables the localhost host bypass, so a
    # revoked/expired token really reads as unauthenticated instead
    # of falling through to the PC-host bypass.
    guest.cookies["drop_locked"] = "1"
    return guest


def _flip_role(home, token, role):
    cfg_path = os.path.join(str(home), ".config", "DropIt", "config.json")
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    assert token in cfg.get("sessions", {}), "token not in sessions"
    cfg["sessions"][token]["role"] = role
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)


def test_guest_admin_403_host_200_and_guest_use_ok(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "10-30-99", "password": "pw123"})
    assert status == 200 and j["ok"], j
    status, _ = client.upload("hostfile.txt", b"host")
    assert status == 200
    guest = _guest_client(port, "pw123")
    _flip_role(home, guest.cookies["drop_sess"], "guest")

    # Every privileged endpoint: guest 403, host-only message.
    for method, path, body in [
            ("POST", "/api/setlink", {"name": "other-link"}),
            ("POST", "/api/setlinkpassword", {"password": "hacked"}),
            ("POST", "/api/setlinkfolder", {"folder": str(base)}),
            ("GET", "/api/linkpassword", None),
            ("GET", "/api/sessions", None),
            ("POST", "/api/sessions/revoke", {"all_guests": True})]:
        status, j = guest.j(method, path, body)
        assert status == 403, (method, path, status, j)
        assert j.get("code") == "host_only"
        assert j["error"] == HOST_ONLY
    # Nothing changed.
    status, st = client.j("GET", "/api/authstate")
    assert st["link_name"] == "10-30-99" and st["locked"] is True

    # Guest USE still works: files + upload.
    status, files = guest.j("GET", "/api/files")
    assert status == 200 and "hostfile.txt" in [f["name"] for f in files]
    status, _ = guest.upload("guestfile.txt", b"guest")
    assert status == 200

    # Host: sessions list works, revoke disconnects the guest.
    status, j = client.j("GET", "/api/sessions")
    assert status == 200 and j["ok"], j
    guests = [s for s in j["sessions"] if s["role"] == "guest"]
    assert len(guests) == 1
    assert guests[0]["id"] != guest.cookies["drop_sess"]  # prefix only
    assert guest.cookies["drop_sess"].startswith(guests[0]["id"])
    status, j = client.j("POST", "/api/sessions/revoke",
                         {"id": guests[0]["id"]})
    assert status == 200 and j["revoked"] == 1, j
    # v2.7.89: the revoked token is gone from the host list. Its
    # 401 over a real LAN connection cannot be shown over
    # localhost TCP (a tokenless localhost caller hits the PC
    # host fallback), so the LAN 401 is covered by the
    # in-process LAN-address tests in test_link_round5.py.
    status, j = client.j("GET", "/api/sessions")
    assert status == 200 and j["ok"], j
    assert [s for s in j["sessions"] if s["role"] == "guest"] == []


def test_locked_cookie_no_longer_blocks_host(server):
    # v2.7.89 SUPERSEDES the old cookie-as-origin rule: the host
    # must NEVER be blocked by the drop_locked cookie for its own
    # use/admin. A localhost caller WITH the cookie still passes
    # host admin; what denies a guest now is its guest role stamp,
    # not the cookie.
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "origin"})
    assert status == 200 and j["ok"], j
    locked = Client(port)
    status, j = locked.j("POST", "/api/setlink", {"name": "origin2"})
    assert status == 200 and j["ok"], j  # unlocked host, no cookie yet
    locked.cookies["drop_locked"] = "1"
    status, j = locked.j("POST", "/api/setlink",
                         {"name": "origin3", "password": "pw123"})
    assert status == 200 and j["ok"], j  # cookie ignored for host
    # And a guest-stamped token WITH the cookie is still denied.
    guest = _guest_client(port, "pw123")
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    status, j = guest.j("POST", "/api/setlink", {"name": "origin4"})
    assert status == 403 and j.get("code") == "host_only", j


def test_connect_clean_name_verifies_without_changing(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "10-30-99"})
    assert status == 200 and j["ok"], j
    status, _ = client.upload("linkfile.txt", b"data")
    assert status == 200
    # Clean name, no token, no auth: connects to that link's files.
    status, j = _raw(port, "POST", "/api/connect", {"link": "10-30-99"})
    assert status == 200 and j["ok"], j
    assert j["display_link"] == "10-30-99" and j["locked"] is False
    status, files = _raw(port, "GET", "/api/files",
                         headers={"X-Drop-Link": "10-30-99"})
    assert status == 200 and [f["name"] for f in files] == ["linkfile.txt"]
    # Wrong link: refused, nothing changed.
    status, j = _raw(port, "POST", "/api/connect", {"link": "other"})
    assert status == 409 and j.get("code") == "wrong_link", j
    status, st = client.j("GET", "/api/authstate")
    assert st["link_name"] == "10-30-99"


def test_password_change_clears_guest_keeps_host(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink",
                         {"name": "keephost", "password": "oldpw"})
    assert status == 200 and j["ok"], j
    status, j = client.j("POST", "/api/login", {"password": "oldpw"})
    assert status == 200 and j["ok"], j  # host token (localhost)
    guest = _guest_client(port, "oldpw")
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    status, _ = guest.j("GET", "/api/files")
    assert status == 200
    status, j = client.j("POST", "/api/setlinkpassword",
                         {"password": "newpw"})
    assert status == 200 and j["ok"], j
    # v2.7.89: the guest token is cleared by the password change
    # (asserted on the host session list; its LAN 401 cannot be
    # shown over localhost TCP -- see test_link_round5.py).
    status, j = client.j("GET", "/api/sessions")
    assert status == 200 and j["ok"], j
    assert [s for s in j["sessions"] if s["role"] == "guest"] == []
    status, files = client.j("GET", "/api/files")
    assert status == 200  # host session survives
    # The guest re-authenticates with the new password.
    status, j = guest.j("POST", "/api/login", {"password": "newpw"})
    assert status == 200 and j["ok"], j


def test_saved_password_host_only_and_never_plaintext(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "prefill"})
    assert status == 200 and j["ok"], j
    status, j = client.j("POST", "/api/setlinkpassword",
                         {"password": "secret1"})
    assert status == 200 and j["ok"], j
    cfg_path = os.path.join(str(home), ".config", "DropIt", "config.json")
    with open(cfg_path, encoding="utf-8") as f:
        raw_cfg = f.read()
    assert "secret1" not in raw_cfg  # hash + encrypted blob only
    status, j = client.j("GET", "/api/linkpassword")
    assert status == 200 and j["password"] == "secret1", j
    guest = _guest_client(port, "secret1")
    _flip_role(home, guest.cookies["drop_sess"], "guest")
    status, j = guest.j("GET", "/api/linkpassword")
    assert status == 403 and j.get("code") == "host_only", j


def test_mdns_srv_advertises_port_for_clean_name_connect():
    """A phone with no stored port must still resolve a clean link
    name: SRV gives the port, A gives the IP. Pure-function check of
    the server's mDNS reply builder."""
    import dropit as dropit_mod

    def query(name, qtype):
        out = bytearray(b"\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        for label in name.split("."):
            out.append(len(label))
            out.extend(label.encode())
        out.append(0)
        out.extend(qtype.to_bytes(2, "big"))
        out.extend((1).to_bytes(2, "big"))
        return bytes(out)

    resp = dropit_mod._mdns_reply(query("10-30-99.local", 33),
                                  b"10-30-99.local", "192.168.1.7", 8123)
    assert resp is not None
    ancount = (resp[6] << 8) | resp[7]
    assert ancount == 1
    # SRV answer: pointer, type 33, then TTL, rdlen, priority, weight,
    # port, target pointer. Search after the question section (the
    # question itself also contains the qtype bytes).
    assert b"\x00\x21" in resp[32:]
    idx = resp.index(b"\x00\x21", 32)
    rdlen_off = idx + 2 + 2 + 4
    rdlen = (resp[rdlen_off] << 8) | resp[rdlen_off + 1]
    rdata = resp[rdlen_off + 2:rdlen_off + 2 + rdlen]
    port = (rdata[4] << 8) | rdata[5]
    assert port == 8123
    # A query still gets only the A record; ANY gets both.
    resp_a = dropit_mod._mdns_reply(query("10-30-99.local", 1),
                                    b"10-30-99.local", "192.168.1.7", 8123)
    assert resp_a is not None and ((resp_a[6] << 8) | resp_a[7]) == 1
    assert b"\x00\x21" not in resp_a
    resp_any = dropit_mod._mdns_reply(query("10-30-99.local", 255),
                                      b"10-30-99.local", "192.168.1.7", 8123)
    assert resp_any is not None and ((resp_any[6] << 8) | resp_any[7]) == 2
    # Wrong name: no reply at all.
    assert dropit_mod._mdns_reply(query("other.local", 33),
                                  b"10-30-99.local", "192.168.1.7",
                                  8123) is None


def test_served_page_single_save_open_warning_no_tech_address(server):
    client, base, proc, port, home = server
    status, j = client.j("POST", "/api/setlink", {"name": "10-30-99"})
    assert status == 200 and j["ok"], j
    status, page = _raw(port, "GET", "/")
    # _raw parses JSON; the page is HTML, so fetch it raw instead.
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/")
    resp = conn.getresponse()
    html = resp.read().decode("utf-8")
    conn.close()
    assert resp.status == 200
    # Single Save, no overlapping link-flow buttons (as buttons, not
    # as words in code comments).
    assert 'id="lkset" data-tip="Save this address">Save<' in html
    assert "Connect / Save link</button>" not in html
    assert ">Save Link<" not in html
    assert 'id="lkclose">Done' not in html
    # Folder row: Open/Change side by side under the folder field,
    # in the Shared-Files-tab openf/changef colours.
    assert 'class="lkfolderrow"' in html
    # v2.7.90 SUPERSEDES v2.7.89: tab-shape classes are removed;
    # the folder buttons are the plain pre-tab .btn shape again.
    # (tab-style redesign, visual only) and a hover data-tip.
    assert 'class="btn openf" id="lkopenfolder" data-tip="Open the save folder on this PC"' in html
    assert 'class="btn changef" id="lkchangefolder" data-tip="Change the save folder for this address"' in html
    # Open-link warning present on a passwordless link.
    assert "Open address" in html and "anyone on your Wi-Fi can use it" in html
    # Host saved-password prefill path: openLinkWin fetches the
    # saved password (host only) into the masked field.
    assert "pwf.value = j.password" in html
    # No user-visible technical address: strip scripts, styles and
    # tags (hrefs/JS internals are not displayed text), then check.
    visible = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    visible = re.sub(r"<style.*?</style>", "", visible, flags=re.S)
    visible = re.sub(r"<[^>]+>", "", visible)
    assert ".local" not in visible
    assert ":8000" not in visible
    # Icon buttons sized to the field height, not a fixed bigger box.
    assert "height:auto" in html
