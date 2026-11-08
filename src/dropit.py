#!/usr/bin/env python3
"""Drop - beam files between your phone and PC over local WiFi.

No cloud, no USB cable, no accounts. Run it, open the shown address
(or scan the QR code) on your phone. Same WiFi required.

Usage:
    python dropit.py                 # serves on port 8000, saves to ~/DropIt
    python dropit.py --port 9000 --dir ./shared

Stdlib only for the core - no pip install needed. (QR codes appear
automatically if the `qrcode` package is installed.)
"""

import argparse
import hashlib
import hmac
import html
import json
import mimetypes
import os
import re
import secrets
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "2.8.41"

_SVG_TRASH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>'
_SVG_LINK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>'
_SVG_FOLDER_OPEN = '<svg viewBox="0 0 24 24"><path d="M2.5 6a2 2 0 0 1 2-2h4l2 2.5h9a2 2 0 0 1 2 2V9h-19V6z" fill="#fbbf24"/><path d="M2.5 9h19v9a2 2 0 0 1-2 2h-15a2 2 0 0 1-2-2V9z" fill="#ffedd5"/><path d="M2.5 12.5h19V18a2 2 0 0 1-2 2h-15a2 2 0 0 1-2-2v-5.5z" fill="#ffffff"/></svg>'
_SVG_FOLDER_EDIT = '<svg viewBox="0 0 24 24"><path d="M2.5 7a2 2 0 0 1 2-2h4l2 2.5h6a2 2 0 0 1 2 2V9h-16V7z" fill="#a78bfa"/><path d="M2.5 9h16v9a2 2 0 0 1-2 2h-12a2 2 0 0 1-2-2V9z" fill="#ddd6fe"/><g transform="rotate(45 14.5 13.5)"><rect x="13.1" y="7.5" width="2.8" height="8.5" rx="1.2" fill="#fbbf24"/><path d="M13.1 16h2.8l-1.4 2.4z" fill="#78350f"/></g></svg>'

try:
    import qrcode  # noqa: F401
    HAS_QR = True
except ImportError:
    HAS_QR = False


# ------------------------------------------------------------ text notes
# Shared texts live in the app's own data dir (notes.json) -- NOT as files
# in the shared folder. The folder stays 100% the user's files.
_notes_lock = threading.Lock()

# Recently seen remote clients (ip -> last-seen timestamp). The desktop's own
# loopback traffic is excluded so the count reflects real connected devices.
_seen_lock = threading.Lock()
_seen_ips = {}
_SEEN_WINDOW = 20  # seconds

def _note_seen(ip):
    if ip in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
        return
    with _seen_lock:
        _seen_ips[ip] = time.time()

def _purge_seen_ips(ips):
    """Drop exactly these IPs from the seen set (v2.8.1: single-
    device disconnect must not leave the pill count stale)."""
    with _seen_lock:
        for _ip in ips:
            if _ip:
                _seen_ips.pop(_ip, None)


# In-memory last-activity per session token. Single source of
# truth for "Devices Connected": a device counts (and is listed)
# only while its guest session has been active recently. The old
# pill count came from _seen_ips (any recent authed traffic, 20s
# TTL) while the list came from sessions (never expiring) -- so an
# idle phone showed "No Devices Connected" with its name still
# listed, and a revoked device showed a count with an empty list.
# Both now derive from the same live-session set, so they always
# agree; a disconnect removes the session, so it leaves both at
# once. Window covers the APK ~30s poll + jitter.
_session_seen = {}
_session_seen_lock = threading.Lock()
_DEVICE_LIVE_WINDOW = 90  # seconds

def _note_session_seen(tok):
    if not tok:
        return
    now = time.time()
    with _session_seen_lock:
        _session_seen[tok] = now
        for t in [t for t, ts in _session_seen.items()
                  if now - ts >= _DEVICE_LIVE_WINDOW]:
            _session_seen.pop(t, None)

def _live_guest_tokens(cfg):
    """Tokens of guest sessions active within the live window.
    A just-minted session counts via its mint timestamp until
    its first request lands."""
    now = time.time()
    live = set()
    with _session_seen_lock:
        seen = dict(_session_seen)
    for tok, s in (cfg.get("sessions") or {}).items():
        if not isinstance(s, dict):
            continue
        role = s.get("role")
        if role not in ("host", "guest"):
            role = "guest"
        if role == "host":
            continue
        last = max(seen.get(tok, 0), int(s.get("ts") or 0))
        if now - last < _DEVICE_LIVE_WINDOW:
            live.add(tok)
    return live

def _device_count(exclude=None):
    # v2.7.90: the host is NEVER a "connected device". Loopback
    # traffic is already excluded by _note_seen; callers pass the
    # IPs of host sessions too (the desktop window loaded via a
    # LAN IP would otherwise count as a device).
    now = time.time()
    excl = set(exclude or ())
    with _seen_lock:
        for ip in [ip for ip, ts in _seen_ips.items() if now - ts >= _SEEN_WINDOW]:
            del _seen_ips[ip]
        return len([ip for ip in _seen_ips if ip not in excl])


# --- /api/aitranslate rate limiting ---------------------------------------
# Translation is the heaviest endpoint (model inference, plus a ~110 MB
# pack download on first use), so each client IP gets a sliding window.
# Loopback is never limited - local testing and the desktop app itself
# shouldn't trip the guard.
_AIT_LIMIT = 10    # max translations ...
_AIT_WINDOW = 60.0  # ... per this many seconds
_ait_lock = threading.Lock()
_ait_hits = {}  # ip -> [timestamps of recent calls]


def _ait_allowed(ip):
    """Sliding-window rate limiter for /api/aitranslate.

    Returns True when this call may proceed, False when the IP has used
    up its window.
    """
    if ip in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
        return True
    now = time.time()
    with _ait_lock:
        hits = [t for t in _ait_hits.get(ip, []) if now - t < _AIT_WINDOW]
        if len(hits) >= _AIT_LIMIT:
            _ait_hits[ip] = hits
            return False
        hits.append(now)
        _ait_hits[ip] = hits
        if len(_ait_hits) > 512:  # don't let the table grow forever
            _ait_hits.pop(next(iter(_ait_hits)))
        return True

def _data_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        folder = os.path.join(base, "DropIt")
    else:
        folder = os.path.join(os.path.expanduser("~"), ".config", "DropIt")
    os.makedirs(folder, exist_ok=True)
    return folder

def _notes_path(pid="default"):
    if pid and pid != "default":
        return os.path.join(_data_dir(), "notes-%s.json" % pid)
    return os.path.join(_data_dir(), "notes.json")

def load_notes(pid="default"):
    try:
        with open(_notes_path(pid), encoding="utf-8") as f:
            data = json.load(f)
        notes = [n for n in data
                 if isinstance(n, dict) and n.get("id") and isinstance(n.get("text"), str)]
        notes.sort(key=lambda n: n.get("created", 0), reverse=True)
        return notes
    except (OSError, ValueError):
        return []

def save_notes(notes, pid="default"):
    tmp = _notes_path(pid) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(notes, f)
    os.replace(tmp, _notes_path(pid))

def _new_note_id(notes):
    taken = {n.get("id") for n in notes}
    nid = "n%d" % int(time.time() * 1000)
    while nid in taken:
        nid += "1"
    return nid

def add_note(text, pid="default"):
    notes = load_notes(pid)
    note = {"id": _new_note_id(notes), "text": text, "created": int(time.time())}
    notes.append(note)
    save_notes(notes, pid)
    return note

def delete_note(nid, pid="default"):
    notes = load_notes(pid)
    kept = [n for n in notes if n.get("id") != nid]
    if len(kept) == len(notes):
        return False
    save_notes(kept, pid)
    return True

def edit_note(nid, text, pid="default"):
    notes = load_notes(pid)
    for n in notes:
        if n.get("id") == nid:
            n["text"] = text
            save_notes(notes, pid)
            return True
    return False


def rename_note(nid, title, pid="default"):
    notes = load_notes(pid)
    for n in notes:
        if n.get("id") == nid:
            title = (title or "").strip()[:120]
            if title:
                n["title"] = title
            else:
                n.pop("title", None)
            save_notes(notes, pid)
            return True
    return False


def star_note(nid, starred, pid="default"):
    notes = load_notes(pid)
    for n in notes:
        if n.get("id") == nid:
            if starred:
                n["starred"] = True
            else:
                n.pop("starred", None)
            save_notes(notes, pid)
            return True
    return False


# ------------------------------------------------------- single-link lock/auth
def _config_path():
    return os.path.join(_data_dir(), "config.json")


# ------------------------------------------------- v2.7.92 address rename
# Config keys were renamed link_* -> address_* (and the registry
# "links" -> "addresses"). Old saved state MUST still load: every
# read normalises old keys into new ones, and every write stores
# BOTH spellings, so old readers/tests and new code agree. The new
# key is canonical whenever both are present.
_ADDRESS_KEY_PAIRS = (
    ("address_name", "link_name"),
    ("address_pass", "link_pass"),
    ("address_pass_enc", "link_pass_enc"),
    ("address_history", "link_history"),
    ("addresses", "links"),
)


def _sync_address_keys(cfg):
    for new, old in _ADDRESS_KEY_PAIRS:
        if new in cfg:
            cfg[old] = cfg[new]
        elif old in cfg:
            cfg[new] = cfg[old]
    return cfg


def _load_config():
    try:
        with open(_config_path(), encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            return {}
        return _sync_address_keys(d)
    except (OSError, ValueError):
        return {}


def _save_config(cfg):
    _sync_address_keys(cfg)
    tmp = _config_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    os.replace(tmp, _config_path())


# ------------------------------------------------- v2.7.92 address colours
# Deterministic colour per address, stable across restarts and
# identical in the web page and (for the APK worker) in any other
# client: FNV-1a 32-bit over the UTF-8 bytes of the sanitised
# lowercase address key, index = hash % 8 into _ADDRESS_PALETTE.
# The palette is badge/dot colours chosen to stay clearly visible
# with white text / as a solid dot on BOTH dark and light cards.
_ADDRESS_PALETTE = ("#0ea5e9", "#8b5cf6", "#ec4899", "#d97706",
                    "#059669", "#0891b2", "#db2777", "#65a30d")


def address_color(key):
    h = 2166136261
    for b in (key or "").encode("utf-8"):
        h ^= b
        h = (h * 16777619) & 0xFFFFFFFF
    return _ADDRESS_PALETTE[h % len(_ADDRESS_PALETTE)]


# v2.7.94 text colours: same FNV-1a index as address_color, but each
# palette entry darkened so coloured address TEXT stays readable on
# a light card as well as on dark. Family recognisable, same order.
_ADDRESS_TEXT_PALETTE = ("#0284c7", "#7c3aed", "#be185d", "#b45309",
                         "#047857", "#0e7490", "#9d174d", "#4d7c0f")


def address_text_color(key):
    h = 2166136261
    for b in (key or "").encode("utf-8"):
        h ^= b
        h = (h * 16777619) & 0xFFFFFFFF
    return _ADDRESS_TEXT_PALETTE[h % len(_ADDRESS_TEXT_PALETTE)]


def _clean_device_name(v):
    # Guest-supplied device name only: a model name, never a
    # password and never personal data beyond that. Stripped of
    # control characters and capped, so a hostile value cannot
    # inject markup or bloat the config.
    if v is None:
        return ""
    s = "".join(ch for ch in str(v).strip()
                if ord(ch) >= 32 and ord(ch) != 127)
    return s.strip()[:64]


def _ua_hint(ua):
    # Web-guest device hint from the User-Agent, best effort only:
    # an Android model ("...; <Model> Build/..."), iPhone/iPad, or
    # a generic desktop OS label. Returns "" when unrecognised --
    # the caller then falls back to the IP, never invents a name.
    if not ua:
        return ""
    m = re.search(r"Android[^;]*;\s*([^;\)]+?)\s+Build/", ua)
    if m:
        return _clean_device_name(m.group(1))
    if "iPhone" in ua:
        return "iPhone"
    if "iPad" in ua:
        return "iPad"
    if "Android" in ua:
        return "Android device"
    if "Windows" in ua:
        return "Windows PC"
    if "Macintosh" in ua or "Mac OS" in ua:
        return "Mac"
    if "Linux" in ua:
        return "Linux PC"
    return ""


_HOSTNAME_CACHE = {}


def _resolve_hostname(ip):
    # Reverse-DNS / hostname for one IP, best effort, never
    # blocking a request for long: a 0.5s join on a daemon thread.
    # Loopback is skipped (it would only ever say "localhost",
    # which is not a device name) and a hostname equal to the IP
    # itself, or "localhost", is treated as unresolvable.
    if not ip or ip in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
        return ""
    if ip in _HOSTNAME_CACHE:
        return _HOSTNAME_CACHE[ip]
    result = {}

    def _run():
        try:
            result["h"] = socket.gethostbyaddr(ip)[0]
        except Exception:  # noqa: BLE001 - any DNS failure = no name
            result["h"] = None

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(0.5)
    h = result.get("h") if not t.is_alive() else None
    out = ""
    if h and h != ip:
        first = h.rstrip(".").split(".")[0].strip()
        if first and first.lower() != "localhost":
            out = first
    if out:
        _HOSTNAME_CACHE[ip] = out
    return out


def _device_display_name(sess):
    # Display fallback order (v2.7.94): guest-supplied name >
    # reverse-DNS hostname > User-Agent hint > IP. Never invents.
    if not isinstance(sess, dict):
        return ""
    name = _clean_device_name(sess.get("device_name") or "")
    if name:
        return name
    ip = str(sess.get("ip") or "")
    host = _resolve_hostname(ip) if ip else ""
    if host:
        return host
    hint = _clean_device_name(sess.get("ua_hint") or
                              sess.get("device_hint") or "")
    if hint:
        return hint
    return ip


def _session_device_fields(handler, data):
    # Fields to stamp on a freshly minted session (or to update
    # on a reused token): the guest-supplied name, if any, plus
    # the UA-derived hint. The full User-Agent is never stored.
    out = {}
    if isinstance(data, dict):
        name = _clean_device_name(data.get("device_name") or
                                  data.get("device") or "")
        if name:
            out["device_name"] = name
    ua = ""
    try:
        ua = handler.headers.get("User-Agent") or ""
    except Exception:  # noqa: BLE001 - headers may be a plain mapping
        ua = ""
    hint = _ua_hint(ua)
    if hint:
        out["ua_hint"] = hint
    return out


def _hash_pw(pw):
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(pw.encode("utf-8"), salt=salt, n=16384, r=8, p=1,
                        dklen=32)
    return salt.hex() + "$" + dk.hex()


def _check_pw(pw, stored):
    try:
        salt_hex, dk_hex = stored.split("$", 1)
        dk = hashlib.scrypt(pw.encode("utf-8"),
                            salt=bytes.fromhex(salt_hex),
                            n=16384, r=8, p=1, dklen=32)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------- single-link lock (v2.7.83)
# Profiles are REMOVED (user verdict, Oct 31 2026): one link, one
# collection, one optional password. Locking/unlocking never switches
# collections, so notes and files for a link survive lock/unlock.
#   cfg["address_pass"] — scrypt hash of the link password ("" = unlocked).
#   cfg["sessions"]  — token -> {ts, link}; a token is valid only for
#     the link it was issued for (see _profile).
#   drop_locked cookie — set on logout so even the PC host (which is
#     normally auto-authed) must unlock with the password after locking.
# Legacy profiles data stays on disk untouched (never deleted here);
# their folders/notes are simply no longer served. A legacy space
# password still unlocks once: on a matching login it is adopted as
# the link password (see _legacy_passwords), so an existing password
# keeps working under the new model.
#
# ------------------------------------------------- links (v2.7.84)
# A "link" is the name the user types on the link screen. It is the
# connection identity AND the folder identity, in one:
#   * sanitised link name -> folder mapping (documented, stable):
#       base/<link>/   where <link> = _sanitise_address(name)
#     e.g. "My Link!" -> "my-link", so the folder is base/my-link/.
#     A per-link folder override set with Change folder replaces
#     base/<link>/ for that link only (stored in the registry).
#   * cfg["addresses"] — per-link registry:
#       {<link>: {"pass": scrypt hash or "", "folder": override or ""}}
#     cfg["address_name"] / cfg["address_pass"] mirror the CURRENT link
#     (back-compat for v2.7.83 readers). Switching links switches the
#     active folder automatically and NEVER moves or deletes another
#     link's folder. Changing a link clears every session token, so a
#     client holding an old link's token can no longer connect; it
#     must reconnect through the new link (and its password, if set).
#     A link NEVER changes on its own: make_server() reads link_name
#     verbatim from config and never generates or rewrites it.
#   * notes are per link too: notes-link-<link>.json. The pre-v2.7.84
#     single notes.json is adopted ONCE, into the first link that
#     needs it (flag: legacy_notes_adopted_by); the original file is
#     never deleted. Files from a pre-link shared folder are moved
#     ONCE into the first link's folder (flag: legacy_files_adopted);
#     switching between links afterwards moves nothing.
def _sanitise_address(name):
    """Typed link name -> filesystem-safe link name (also the folder
    name). Lowercase, runs of non [a-z0-9] become one dash, no leading
    or trailing dash, max 32 chars. "" when nothing usable remains."""
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower())
    s = re.sub(r"-+", "-", s).strip("-")[:32].strip("-")
    return s


# ------------------------------------------------- link names (v2.7.85)
# Round 2 changes the input rule, NOT the folder mapping. _sanitise_address
# still derives the folder/mDNS key (lowercase) from a name, but
# /api/setlink no longer silently rewrites what the user typed: a name
# is either accepted exactly as typed (stored as the display name in
# cfg["address_name"]) or rejected with a clear message. Dots (and every
# other non [A-Za-z0-9_-] character) are rejected, never turned into
# hyphens: the link name becomes a folder name on the PC and part of
# the .local address, so a dot would break both.
_ADDRESS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
_ADDRESS_RULES_MSG = (
    "Address names can only use letters, numbers, hyphen (-) and "
    "underscore (_), must start with a letter or number, and be at "
    "most 32 characters. Dots are not allowed: your address name becomes "
    "a folder name on the PC and part of the .local address, so a dot "
    "would break both.")
_ADDRESS_DOT_MSG = (
    "Dots are not allowed in address names: your address name becomes a "
    "folder name on the PC and part of the .local address, so a dot "
    "would break both. Use letters, numbers, hyphen (-) or underscore "
    "(_) instead (up to 32 characters).")


def _validate_address_name(name):
    """(ok, error). ``name`` is the raw typed name, already stripped."""
    if not name:
        return False, "Type an address name first"
    if "." in name:
        return False, _ADDRESS_DOT_MSG
    if not _ADDRESS_RE.match(name):
        return False, _ADDRESS_RULES_MSG
    return True, ""


def _current_address(cfg):
    return _sanitise_address(cfg.get("address_name") or "")


def _address_registry(cfg):
    raw = cfg.get("addresses")
    if not isinstance(raw, dict):
        raw = {}
        cfg["addresses"] = raw
    return raw


# ------------------------------------------------- password storage (v2.7.85)
# Round 2, user decision (Nov 1, 2026): the eye icon must reveal the
# SAVED password. Pure hashing cannot be reversed, so storage is now
# hash + local encryption, and the user explicitly accepted the
# trade-off: anyone with access to this host device (its config AND
# its key file) could retrieve the password.
#   cfg["address_pass"]      -- scrypt hash, used for verification.
#   cfg["address_pass_enc"]  -- the same password, symmetrically encrypted
#                            (never bare plaintext in config.json).
#   <data dir>/linkkey    -- random 32-byte key, created once, mode 0600
#                            where the platform supports it, stored
#                            SEPARATELY from config.json.
# Cipher: SHA-256 counter-mode stream (key || nonce || counter) XOR
# plaintext, with an HMAC-SHA256 tag so a tampered blob fails closed.
# Stdlib-only: dropit.py must run with no extra install on the PC.
def _address_key():
    path = os.path.join(_data_dir(), "linkkey")
    try:
        with open(path, "rb") as f:
            key = bytes.fromhex(f.read().decode("ascii").strip())
        if len(key) == 32:
            return key
    except (OSError, ValueError):
        pass
    key = secrets.token_bytes(32)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(key.hex())
    except OSError:
        pass
    return key


def _encrypt_pw(pw):
    if not pw:
        return ""
    key = _address_key()
    nonce = secrets.token_bytes(16)
    raw = pw.encode("utf-8")
    ct = bytearray()
    off = 0
    ctr = 0
    while off < len(raw):
        block = hashlib.sha256(
            key + nonce + ctr.to_bytes(4, "big")).digest()
        chunk = raw[off:off + len(block)]
        ct.extend(b ^ block[i] for i, b in enumerate(chunk))
        off += len(chunk)
        ctr += 1
    tag = hmac.new(key, nonce + bytes(ct), hashlib.sha256).digest()[:16]
    return "v1:%s:%s:%s" % (nonce.hex(), bytes(ct).hex(), tag.hex())


def _decrypt_pw(blob):
    """Saved password, or None when there is no retrievable copy
    (empty, legacy hash-only password, missing key, tampered blob)."""
    try:
        if not blob or not blob.startswith("v1:"):
            return None
        _, nonce_h, ct_h, tag_h = blob.split(":", 3)
        nonce, ct, tag = (bytes.fromhex(nonce_h), bytes.fromhex(ct_h),
                          bytes.fromhex(tag_h))
        key = _address_key()
        expect = hmac.new(key, nonce + ct, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(expect, tag):
            return None
        raw = bytearray()
        off = 0
        ctr = 0
        while off < len(ct):
            block = hashlib.sha256(
                key + nonce + ctr.to_bytes(4, "big")).digest()
            chunk = ct[off:off + len(block)]
            raw.extend(b ^ block[i] for i, b in enumerate(chunk))
            off += len(chunk)
            ctr += 1
        return bytes(raw).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def _set_address_password(cfg, link, pw, save=True):
    """Store the password for `link`, mirroring cfg when it is the
    current link. v2.8.36 lock semantics (Essef Nov 7): an empty pw
    clears hash + encrypted copy and unlocks (locked=False). A
    non-empty pw with save=True stores hash + encrypted copy and
    locks (locked=True). A non-empty pw with save=False stores the
    HASH ONLY (verification still works), CLEARS the encrypted
    copy, and still locks (locked=True) -- the gate is active but
    nobody can reveal or prefill the password."""
    hashed = _hash_pw(pw) if pw else ""
    enc = _encrypt_pw(pw) if (pw and save) else ""
    if link:
        entry = _address_entry(cfg, link)
        entry["pass"] = hashed
        entry["pass_enc"] = enc
        entry["locked"] = bool(pw)
    if link and link == _current_address(cfg):
        cfg["address_pass"] = hashed
        cfg["address_pass_enc"] = enc
    return hashed


def _entry_locked(cfg, key):
    """Lock gate for one registry entry: an explicit "locked"
    flag wins; entries written before v2.7.92 fall back to "a
    password is stored" (the pre-2.7.92 meaning of locked)."""
    entry = _address_registry(cfg).get(key)
    if isinstance(entry, dict):
        if "locked" in entry:
            return bool(entry["locked"])
        if entry.get("pass"):
            return True
    if key and key == _current_address(cfg):
        return bool(cfg.get("address_pass"))
    return False


def _password_saved_for(cfg, key):
    """True when a RETRIEVABLE encrypted copy of the password
    exists for `key` (decrypts with this PC's key). A hash-only
    password (v2.8.36 save=False) returns False."""
    entry = _address_registry(cfg).get(key)
    enc = ""
    if isinstance(entry, dict):
        enc = entry.get("pass_enc") or ""
    if not enc and key and key == _current_address(cfg):
        enc = cfg.get("address_pass_enc") or ""
    return _decrypt_pw(enc) is not None


def _address_entry(cfg, link):
    """Registry entry for `link`, created on demand. For the current
    link, a legacy cfg["address_pass"] with no registry entry yet is
    adopted into the entry (v2.7.83 -> v2.7.84 migration)."""
    reg = _address_registry(cfg)
    entry = reg.get(link)
    if not isinstance(entry, dict):
        entry = {}
        reg[link] = entry
    if link and link == _current_address(cfg) and "pass" not in entry \
            and cfg.get("address_pass"):
        entry["pass"] = str(cfg["address_pass"])
    if link and link == _current_address(cfg) and "pass_enc" not in entry \
            and cfg.get("address_pass_enc"):
        entry["pass_enc"] = str(cfg["address_pass_enc"])
    return entry


def _address_folder(cfg):
    """Folder for the CURRENT link: its Change-folder override if set,
    else base/<link>/, else the base root when no link is set.
    v2.8.31: an explicit per-address override wins regardless of
    the separate-folders toggle -- choosing a folder for an
    address must work whether the toggle is ON or OFF. The
    toggle only decides the DEFAULT (per-address subfolder vs
    the shared Main Folder) when no override is set."""
    root = str(cfg.get("directory") or "")
    link = _current_address(cfg)
    if not link:
        return root
    entry = _address_registry(cfg).get(link)
    if isinstance(entry, dict) and entry.get("folder"):
        return str(entry["folder"])
    if not _separate_folders_enabled(cfg):
        return root
    return os.path.join(root, link) if root else link


def _separate_folders_enabled(cfg):
    """v2.8.7: True (default) = one subfolder per link, as before.
    False = every link saves into the Main Folder (base root),
    with no per-link subfolder creation."""
    return cfg.get("separate_folders", True) is not False


def _root_folder(cfg):
    """The base ROOT folder (cfg["directory"]), the parent under
    which per-address folders live -- NOT any address's folder.
    v2.7.96: the MENU's Open/Change Folder route targets this;
    Set Up and the Files tab target _address_folder instead."""
    return str(cfg.get("directory") or "")


def _folder_for_scope(cfg, scope):
    """Folder routing, split by place (v2.7.96): "root" -> the
    base root, "address" (default) -> the current address's
    direct folder. Any other scope falls back to address."""
    if scope == "root":
        return _root_folder(cfg)
    return _address_folder(cfg)


def _address_notes_pid(cfg):
    link = _current_address(cfg)
    return ("link-" + link) if link else "default"


def _adopt_legacy_notes(cfg):
    """Copy the pre-v2.7.84 notes.json into the current link's notes
    file, once, if that link has no notes yet. Returns True when a
    copy happened (caller must save cfg to record the flag). The
    original notes.json is never deleted or modified."""
    link = _current_address(cfg)
    if not link or cfg.get("legacy_notes_adopted_by"):
        return False
    target = _notes_path("link-" + link)
    legacy = _notes_path("default")
    if os.path.exists(target) or not os.path.exists(legacy):
        return False
    try:
        import shutil
        shutil.copyfile(legacy, target)
    except OSError:
        return False
    cfg["legacy_notes_adopted_by"] = link
    return True


def _any_password(cfg=None):
    cfg = cfg if cfg is not None else _load_config()
    return bool(cfg.get("address_pass"))


def _address_locked(cfg):
    """v2.7.92 lock state, DISTINCT from password existence.

    Locking an address means its password gate is active; unlocking
    means guests may connect without a password, while the password
    itself stays stored for the next lock. The flag lives per
    address in its registry entry ("locked"); entries written
    before v2.7.92 have no flag and fall back to "a password is
    stored" (the pre-2.7.92 meaning of locked), so old state keeps
    working unchanged. Only an explicit password removal clears
    the stored password; locking/unlocking never touches it.
    """
    cur = _current_address(cfg)
    if not cur:
        return False
    entry = _address_registry(cfg).get(cur)
    if isinstance(entry, dict) and "locked" in entry:
        return bool(entry["locked"])
    if isinstance(entry, dict) and entry.get("pass"):
        return True
    return bool(cfg.get("address_pass"))


def _has_stored_password(cfg):
    """True when the current address has a stored password, whether
    or not its gate is currently locked (host-only signal)."""
    cur = _current_address(cfg)
    if not cur:
        return False
    entry = _address_registry(cfg).get(cur)
    if isinstance(entry, dict) and entry.get("pass"):
        return True
    return bool(cfg.get("address_pass"))


# ------------------------------------------------- guest-only lock
# + guest-delete toggle (v2.7.89, user decision Nov 1, 2026).
# v2.7.90 RETIRES the guest lock: "lock guests out" is gone as a
# host-initiated action. The only guest gate left is the PASSWORD
# gate (cfg["address_pass"] non-empty, "locked" in /api/authstate):
# a guest with no valid token must supply the password to get a
# token. Setting a password on a link a guest previously used
# WITHOUT one clears that guest's sessions, so the guest sees the
# password/login page -- that is the ONLY locked-page case left.
# Disconnecting a guest ends its session only and never blocks
# reconnection. The HOST is never gated: loopback origin OR the
# desktop bridge token bypasses the password gate for use and
# admin, and the legacy drop_locked cookie is IGNORED for host
# identity.
#   * GUEST DELETE (cfg["guest_delete_allowed"], default False):
#     host-only toggle "Guests can delete files". OFF: guest file
#     deletion is forbidden (server 403 on /api/delete and
#     /api/delete_all; guest delete UI is greyed out with the
#     no-permission toast). ON: guests may delete files. Host
#     deletion always works regardless of the toggle. Changing the
#     toggle takes effect immediately and does NOT touch sessions.
#   * GUEST NOTES DELETE (cfg["guest_notes_delete_allowed"],
#     default False, v2.7.90): the same shape for notes, on
#     /api/notes/delete and /api/notes/delete_all, with the
#     v2.7.99 message "No permission to delete notes from this
#     device" (the legacy toggles seed the per-address
#     Permissions set on first use -- see _address_permissions).
#     It does NOT gate file delete, and the files toggle does NOT
#     gate notes. Host note delete always works.
def _guest_locked(cfg=None):
    # v2.7.90 RETIRED: "lock guests out" as a host-initiated action
    # is gone (Nov 1, 2026). A legacy cfg may still carry the flag;
    # it is deliberately IGNORED here so an old locked flag can
    # never lock guests out again. The only guest gate left is the
    # link password (see _any_password): a guest with no valid
    # token on a password link must log in, and a guest whose link
    # newly gains a password is logged out with it (setlink /
    # setlinkpassword clear guest sessions). Disconnect never sets
    # any lock state either (see /api/sessions/revoke).
    return False


def _guest_lock_seq(cfg=None):
    cfg = cfg if cfg is not None else _load_config()
    try:
        return int(cfg.get("guest_lock_seq") or 0)
    except (TypeError, ValueError):
        return 0


def _guest_delete_allowed(cfg=None):
    cfg = cfg if cfg is not None else _load_config()
    return bool(cfg.get("guest_delete_allowed"))


def _guest_notes_delete_allowed(cfg=None):
    # v2.7.90, mirroring "Guests can delete files": host-only
    # toggle "Guests can delete notes", default OFF.
    cfg = cfg if cfg is not None else _load_config()
    return bool(cfg.get("guest_notes_delete_allowed"))


# ------------------------------------------------- per-address permissions (v2.7.99)
# Shared contract with the APK worker (field names are frozen):
# cfg["address_permissions"]: dict keyed by sanitised address key
# -> {download_files, upload_files, delete_files, add_notes,
#     delete_notes, star_notes}. Defaults: everything ON except
# the two deletes (OFF). On first use for an address with no
# entry, the delete keys are seeded from the legacy global
# guest_delete_allowed / guest_notes_delete_allowed values when
# present, else the defaults; the other four always default as
# above. Once an entry exists (written by POST /api/permissions)
# it is authoritative for that address and the legacy toggles no
# longer affect it -- per-address independence thereafter. The
# legacy /api/guestdelete and /api/guestnotesdelete endpoints
# keep working: they write the legacy key AND, when an entry
# already exists for the current address, that entry's key too,
# so old clients and the new Permissions grid never disagree.
_PERM_KEYS = ("download_files", "upload_files", "delete_files",
              "add_notes", "delete_notes", "star_notes")
_PERM_DEFAULTS = {"download_files": True, "upload_files": True,
                  "delete_files": False, "add_notes": True,
                  "delete_notes": False, "star_notes": True}
_PERM_MESSAGES = {
    "download_files": "No permission to download files from this device",
    "upload_files": "No permission to upload files to this device",
    "delete_files": "No permission to delete files from this device",
    "delete_notes": "No permission to delete notes from this device",
    "add_notes": "No permission to add notes on this device",
    "star_notes": "No permission to star notes on this device"}


def _address_permissions(cfg, key=None):
    """Effective six permissions for one address (never saved here;
    POST /api/permissions is the only writer of entries)."""
    cfg = cfg if cfg is not None else _load_config()
    key = key if key is not None else _current_address(cfg)
    out = dict(_PERM_DEFAULTS)
    stored = cfg.get("address_permissions")
    entry = stored.get(key) if isinstance(stored, dict) else None
    if isinstance(entry, dict):
        for k in _PERM_KEYS:
            if k in entry:
                out[k] = bool(entry[k])
    else:
        if "guest_delete_allowed" in cfg:
            out["delete_files"] = bool(cfg.get("guest_delete_allowed"))
        if "guest_notes_delete_allowed" in cfg:
            out["delete_notes"] = bool(
                cfg.get("guest_notes_delete_allowed"))
    return out


# ------------------------------------------------- link history (v2.7.90)
# cfg["address_history"]: most-recent-first list of
# {"name": display name as typed, "key": sanitised folder/mDNS key}.
# It is a HISTORY only: deleting an entry removes it from this
# list and nothing else -- the link's folder, files, registry
# password and folder override stay on this PC untouched, so
# retyping the same link later still finds its files. The
# per-link password itself lives in cfg["addresses"][key]["pass_enc"]
# (encrypted host copy) and is revealed to the host only, one
# entry at a time, via /api/linkpassword?link=<key>; the history
# endpoint itself never returns a password.
def _address_history(cfg):
    raw = cfg.get("address_history")
    if not isinstance(raw, list):
        raw = []
        cfg["address_history"] = raw
    out = []
    for e in raw:
        if isinstance(e, dict) and e.get("key"):
            out.append({"name": str(e.get("name") or e["key"]),
                        "key": str(e["key"])})
    return out


def _remember_address(cfg, display, key):
    if not key:
        return
    hist = [{"name": display or key, "key": key}]
    for e in _address_history(cfg):
        if e["key"] != key:
            hist.append(e)
    cfg["address_history"] = hist[:20]


def _legacy_passwords(cfg=None):
    """Hashes of pre-v2.7.83 profile/space passwords (login migration)."""
    cfg = cfg if cfg is not None else _load_config()
    out = []
    raw = cfg.get("profiles")
    if isinstance(raw, list):
        for p in raw:
            if isinstance(p, dict) and p.get("pass"):
                out.append(str(p["pass"]))
    return out


def _legacy_space_count(cfg=None):
    cfg = cfg if cfg is not None else _load_config()
    raw = cfg.get("profiles")
    if not isinstance(raw, list):
        return 0
    return sum(1 for p in raw
               if isinstance(p, dict) and p.get("auto"))


def _mdns_reply(data, our_name, ip, port=0):
    """Build an mDNS response if `data` asks for our_name.

    v2.7.86: answers A records (as before) AND SRV records. The SRV
    record is what lets a phone connect by clean link name alone on
    a FIRST pairing: mDNS A gives the IP, SRV gives the port, so the
    phone never needs a stored port and never hard-codes one (the
    desktop default 8000 is a server-side default only). A query for
    ANY (255) gets both records.
    """
    try:
        if len(data) < 12:
            return None
        qd = (data[4] << 8) | data[5]
        off = 12
        question_end = None
        want_a = False
        want_srv = False
        for _ in range(qd):
            labels = []
            while off < len(data) and data[off] != 0:
                ln = data[off]
                labels.append(data[off + 1:off + 1 + ln].decode("utf-8", "replace"))
                off += 1 + ln
            off += 1  # zero byte
            if off + 4 > len(data):
                return None
            qtype = (data[off] << 8) | data[off + 1]
            off += 4
            name = ".".join(labels).lower()
            if name == our_name.decode().lower():
                if qtype in (1, 255):
                    want_a = True
                if qtype in (33, 255):
                    want_srv = True
            if question_end is None:
                question_end = off
        answers = []
        if want_a:
            answers.append(
                b"\xc0\x0c" + b"\x00\x01" + b"\x80\x01" +
                (120).to_bytes(4, "big") + b"\x00\x04" +
                socket.inet_aton(ip))
        if want_srv and port:
            # SRV rdata: priority 0, weight 0, port, target (pointer
            # back to the question name, 0xC00C).
            srv_rdata = (0).to_bytes(2, "big") + (0).to_bytes(2, "big") + \
                int(port).to_bytes(2, "big") + b"\xc0\x0c"
            answers.append(
                b"\xc0\x0c" + b"\x00\x21" + b"\x80\x01" +
                (120).to_bytes(4, "big") +
                len(srv_rdata).to_bytes(2, "big") + srv_rdata)
        if not answers:
            return None
        hdr = (data[0:2] + b"\x84\x00" + data[4:6] +
               len(answers).to_bytes(2, "big") +
               b"\x00\x00\x00\x00")
        return hdr + data[12:question_end] + b"".join(answers)
    except Exception:  # noqa: BLE001
        return None


def _mdns_serve(server):
    """Advertise the custom link name (<name>.local) on the LAN."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                             socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", 5353))
        mreq = struct.pack("4sL", socket.inet_aton("224.0.0.251"),
                           socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    except Exception:  # noqa: BLE001 - port busy etc: link name is best-effort
        return
    while True:
        try:
            data, addr = sock.recvfrom(2048)
            name = (getattr(server, "address_name", "") or "").strip()
            if not name:
                continue
            resp = _mdns_reply(data, (name + ".local").encode(),
                               lan_ip(),
                               server.server_address[1])
            if resp:
                try:
                    sock.sendto(resp, addr)
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            time.sleep(0.2)


# ------------------------------------------------------------- note labels
_URL_RE = re.compile(r"(https?://[^\s<>]+|www\.[^\s<>]+)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _slug_name(slug):
    parts = [x for x in re.split(r"[-_.]", slug) if x]
    while parts and any(ch.isdigit() for ch in parts[-1]) and len(parts) > 1:
        parts.pop()
    if not parts or len(parts) < 2:
        return ""
    return " ".join(w.capitalize() for w in parts[:3])


def _url_label(url):
    try:
        u = url if "://" in url else "http://" + url
        pr = urllib.parse.urlparse(u)
        host = (pr.hostname or "").lower()
        segs = [x for x in pr.path.split("/") if x]
    except Exception:  # noqa: BLE001
        return "Link"
    if "linkedin.com" in host:
        if segs and segs[0] == "in" and len(segs) > 1:
            nm = _slug_name(segs[1])
            return ("LinkedIn \u00b7 " + nm) if nm else "LinkedIn Profile"
        if segs and segs[0] == "company":
            return "LinkedIn Page"
        return "LinkedIn"
    if "facebook.com" in host or "fb.com" in host:
        if segs and segs[0] == "groups":
            return "Facebook Group"
        if segs and segs[0] not in ("profile.php", "events", "watch",
                                   "marketplace", "pages", "sharer"):
            nm = _slug_name(segs[0]) if segs else ""
            return ("Facebook \u00b7 " + nm) if nm else "Facebook Profile"
        return "Facebook Profile"
    if "instagram.com" in host:
        if segs and segs[0] in ("p", "reel", "reels"):
            return "Instagram Post"
        return "Instagram Profile"
    if "github.com" in host:
        return "GitHub Repo" if len(segs) >= 2 else "GitHub Profile"
    if "youtube.com" in host or "youtu.be" in host:
        return "YouTube Video"
    if "zoom.us" in host:
        return "Zoom Meeting"
    if "meet.google" in host:
        return "Google Meet"
    if "x.com" in host or "twitter.com" in host:
        return "X Post" if "status" in segs else "X Profile"
    if "maps" in host or "goo.gl" in host:
        return "Location"
    if "amazon." in host:
        return "Amazon Product"
    if "reddit.com" in host:
        return "Reddit Post"
    if "t.me" in host or "telegram" in host:
        return "Telegram"
    dom = host[4:] if host.startswith("www.") else host
    return ("Link \u00b7 " + dom) if dom else "Link"


def _phone_label(text):
    for m in re.finditer(r"\+?[\d][\d\s\-\(\)]{8,}\d", text):
        digits = re.sub(r"\D", "", m.group(0))
        core = ""
        if len(digits) == 11 and digits.startswith("1"):
            core = digits[1:]
        elif len(digits) == 10:
            core = digits
        if len(core) == 10 and core[0] in "23456789" and core[3] in "23456789":
            return True
    return False


_LABEL_PROTOS = {
    "Address": "a home street mailing address with city state and zip code",
    "Code Snippet": "computer program source code with functions and variables",
    "Recipe": "a cooking recipe with ingredients and preparation steps",
    "Shopping List": "a grocery shopping list of food items to buy",
}
_label_proto_vecs = None
_label_cache = {}


def _fuzzy_label(text):
    global _label_proto_vecs
    try:
        import dropit_ai
        if not dropit_ai.model_ready():
            return None
        key = hash(text)
        if key in _label_cache:
            return _label_cache[key]
        if _label_proto_vecs is None:
            vecs = dropit_ai._encode(list(_LABEL_PROTOS.values()))
            _label_proto_vecs = {k: vecs[i] for i, k in
                                 enumerate(_LABEL_PROTOS)}
        qv = dropit_ai._encode([text[:600]])[0]
        import numpy as np
        scored = sorted(((float(np.dot(qv, v)), k)
                         for k, v in _label_proto_vecs.items()),
                        reverse=True)
        out = None
        if scored and scored[0][0] >= 0.32 and \
                (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.03):
            out = scored[0][1]
        _label_cache[key] = out
        return out
    except Exception:  # noqa: BLE001 - labels are best-effort
        return None


def note_label(text):
    """Best label for a shared text: patterns first, fuzzy embedding
    fallback, 'Shared Text' when nothing fits."""
    t = (text or "").strip()
    if not t:
        return "Shared Text"
    if _EMAIL_RE.search(t):
        return "Email Address"
    if re.search(r"(a\/c|acct|account)\s*(number|no\.?)?\s*[:#]?\s*\d{8,}", t,
                 re.I):
        return "Account Number"
    if _phone_label(t):
        return "Phone Number"
    urls = [u.strip("\"'") for u in _URL_RE.findall(t)]
    if urls and (len(t) < 220 or len(urls) > 1):
        return _url_label(urls[0])
    if re.search(r"(verification|security|one[- ]time|\botp\b|code is|"
                 r"pin\s*(number|no\.?)?\s*[:#])[^0-9]{0,24}\d{4,8}\b",
                 t, re.I):
        return "Verification Code"
    if re.search(r"\b\d{1,6}\s+[\w\s]{2,34}\b(st|street|ave|avenue|blvd|"
                 r"rd|road|dr|drive|ln|lane|ct|court|way|hwy)\b", t, re.I):
        return "Address"
    if re.search(r"wi-?fi", t, re.I) and re.search(r"pass|pwd|key", t, re.I):
        return "Wi-Fi Password"
    if urls:
        return _url_label(urls[0])
    return _fuzzy_label(t) or "Shared Text"


def migrate_snippets(directory):
    """One-time import of legacy snippet-*.txt files into the notes store."""
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return
    moved = []
    for name in names:
        ln = name.lower()
        if not (ln.startswith("snippet-") and ln.endswith(".txt")):
            continue
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read().strip()
            m = re.match(r"snippet-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})", name, re.I)
            if m:
                y, mo, d, h, mi, s = (int(g) for g in m.groups())
                created = int(time.mktime((y, mo, d, h, mi, s, 0, 0, -1)))
            else:
                created = int(os.path.getmtime(path))
            if text:
                moved.append((text, created))
            os.remove(path)
        except OSError:
            continue
    if moved:
        with _notes_lock:
            notes = load_notes()
            for text, created in moved:
                notes.append({"id": _new_note_id(notes), "text": text, "created": created})
            notes.sort(key=lambda n: n.get("created", 0), reverse=True)
            save_notes(notes)

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Drop">
<meta name="theme-color" content="#0a0e1a">
<link rel="manifest" href="/manifest.json">
<link rel="apple-touch-icon" href="/icon.png">
<title>Drop</title>
<script>try{if(localStorage.getItem("drop_theme")==="light")document.documentElement.classList.add("light")}catch(e){}</script>
<style>
  :root { --bg:#0a0d16; --card:#12172a; --card2:#1a2140; --line:#2a3560; --txt:#eef1f8;
          --muted:#8f99b8; --acc:#22d3ee; --acc2:#a78bfa; --good:#34d399; --bad:#fb7185; }
  * { box-sizing:border-box; margin:0; }
  body { background:radial-gradient(1100px 500px at 50% -10%, #16213d 0%, var(--bg) 55%) fixed, var(--bg);
         color:var(--txt); font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
         max-width:1320px; margin:0 auto; padding:26px 18px 70px;
         /* v2.7.98: the Devices pill lives INSIDE the top bar
            (top-left, beside the menu), so it adds NO row to
            the board and NO height to any card: the board,
            the cards and the footer keep their exact
            pre-pill positions. min-height only fills the
            viewport when the board is shorter. */
         min-height:100vh; min-height:100dvh; display:flex; flex-direction:column; }
  .topbar { display:flex; align-items:center; justify-content:space-between; margin-bottom:10px;
            flex-wrap:wrap; gap:10px; }
  @media (min-width:721px){
    .topbar { width:100%; margin:0 auto 10px; }
  }
  @media (min-width:721px) and (max-width:1083px){
    .topbar { max-width:694px; }
  }
  @media (min-width:1084px){
    .topbar { max-width:1048px; }
  }
  .brand { display:flex; align-items:center; gap:13px; }
  .logo { width:46px; height:46px; border-radius:14px; background:linear-gradient(135deg,var(--acc),var(--acc2));
          display:flex; align-items:center; justify-content:center; font-size:25px;
          box-shadow:0 8px 24px rgba(56,189,248,.35); }
  .logoimg { width:46px; height:46px; display:block; }
  h1 { font-size:25px; letter-spacing:-.02em; }
  .ver { font-size:11px; color:var(--muted); border:1px solid var(--line); padding:3px 9px; border-radius:20px; }
  .status { display:flex; align-items:center; gap:8px; font-size:13px; color:var(--muted); }
  /* v2.7.98: Devices Connected sits in the TOP BAR, TOP LEFT,
     immediately to the right of the menu button, on the same
     top-bar row as the centred Address pill and the Search
     button -- exactly as in Essef's screenshot/mockup. It is
     NOT above the Send card, NOT on top of the Texts card,
     and NOT in a row under the top bar (no blank white row).
     The top-bar row is already tall enough for the 48px
     pill, so it adds no row, no page growth and no card
     resize. The pill is fitted to its text (width:auto),
     with an explicit solid background + border that adapts
     to light / dark (dark #12172a / #2a3560, light #ffffff /
     #c3cfde), never a bare var that can render invisible. */
  .dot { width:9px; height:9px; border-radius:50%; background:var(--good); box-shadow:0 0 12px var(--good);
         animation:pulse 2.2s infinite; }
  .dot.idle { background:#5b6478; box-shadow:none; animation:none; }
  @keyframes pulse { 50% { opacity:.45; } }
  .copybtn { border:1px solid var(--line); background:var(--card2); color:var(--txt); border-radius:9px;
             padding:8px 14px; font-size:13px; cursor:pointer; white-space:nowrap; }
  .copybtn:hover { border-color:var(--acc); }
  .qr { text-align:center; }
  .qr img { width:136px; height:136px; border-radius:12px; background:#fff; padding:7px;
            border:1px solid var(--line); }
  .qr div { font-size:12px; color:var(--muted); margin-top:8px; }
  .hint { color:var(--muted); font-size:13px; margin-top:14px; line-height:1.55; }
  #drop { border:2px dashed var(--line); border-radius:14px; padding:10px 12px; text-align:center;
          cursor:pointer; transition:border-color .15s, background .15s; }
  #drop:hover { border-color:var(--acc2); }
  #drop.over { border-color:var(--acc); background:rgba(56,189,248,.07); transform:scale(1.005); }
  #drop .dropicon { width:30px; height:30px; margin:0 auto 6px; display:block;
          filter:drop-shadow(0 3px 10px rgba(129,140,248,.45)); }
  #drop .big { font-size:15px; font-weight:650; margin-bottom:4px; }
  #drop .small { color:var(--muted); font-size:12px; }
  #drop .small b { color:var(--txt); word-break:break-all; }
  #snippet { width:100%; background:#090c15; border:1px solid var(--line); border-radius:12px;
             color:var(--txt); padding:12px 14px; font-size:14px; font-family:inherit; resize:vertical;
             min-height:110px; }
             resize:vertical; line-height:1.5; }
  #snippet:focus { outline:none; border-color:var(--acc); }
  #snippet::placeholder { color:var(--muted); }
  .snipcard { background:#090c15; border:1px solid var(--line); border-radius:14px;
              padding:14px 16px 14px 19px; margin-bottom:12px; position:relative; overflow:hidden; }
  .snipcard::before { content:""; position:absolute; left:0; top:0; bottom:0; width:3px;
              background:linear-gradient(180deg,var(--nac,var(--acc)),var(--nac2,var(--acc2))); }
  .snipcard:last-child { margin-bottom:0; }
  .sniphead { display:flex; align-items:center; gap:7px; font-size:12.5px; color:var(--muted); margin-bottom:9px; }
  .sniphead .who { color:var(--nac,var(--acc)); font-weight:700; }
  .sniptext { font-size:14.5px; line-height:1.55; white-space:pre-wrap; word-break:break-word;
              display:-webkit-box; -webkit-line-clamp:5; -webkit-box-orient:vertical; overflow:hidden;
              user-select:text; -webkit-user-select:text; cursor:text; }
  .snipcard.expanded .sniptext { display:block; }
  .sniptext a { color:var(--acc); }
  .snipmore { background:none; border:none; color:var(--acc); font-size:13px; cursor:pointer;
              padding:5px 0 0; font-family:inherit; }
  #ctxmenu { position:fixed; z-index:9999; min-width:150px; background:#12172a;
             border:1px solid var(--line); border-radius:10px; padding:5px;
             box-shadow:0 10px 30px rgba(0,0,0,.5); }
  #ctxmenu .ctxitem { display:block; width:100%; text-align:left; background:none; border:none;
             color:#eef1f8; font-size:13.5px; font-family:inherit; padding:9px 12px;
             border-radius:7px; cursor:pointer; }
  #ctxmenu .ctxitem:hover { background:#1d2547; }
  #ctxmenu .ctxitem.off { color:#5a6378; cursor:default; }
  #ctxmenu .ctxitem.off:hover { background:none; }
  /* v2.8.22 (4): the text-preview right-click menu -- Copy +
     Select All only, no Paste. It POPS IN with a scale/fade
     animation on open (the .open class restarts the keyframes;
     the show path reflows between display and .open). Same
     theme as #ctxmenu, one z-step below the toast (5000). */
  #pvctx { position:fixed; z-index:6000; min-width:160px; background:#12172a;
           border:1px solid var(--line); border-radius:10px; padding:5px;
           box-shadow:0 10px 30px rgba(0,0,0,.5); }
  #pvctx .ctxitem { display:block; width:100%; text-align:left; background:none; border:none;
           color:#eef1f8; font-size:13.5px; font-family:inherit; padding:9px 12px;
           border-radius:7px; cursor:pointer; }
  #pvctx .ctxitem:hover { background:#1d2547; }
  #pvctx.open { animation:pvctxpop .16s ease; }
  @keyframes pvctxpop { from { opacity:0; transform:scale(.92) translateY(-4px); } to { opacity:1; transform:scale(1) translateY(0); } }
  .snipactions { display:flex; gap:8px; margin-top:11px; flex-wrap:nowrap; }
  .snipactions .btn { flex:1 1 0; min-width:0; padding:8px 4px; font-size:12.5px; white-space:nowrap; }
  .editbox { width:100%; box-sizing:border-box; background:#0b0e14; color:#eef1f8;
             border:1px solid var(--line); border-radius:9px; padding:10px;
             font-size:14px; font-family:inherit; resize:vertical; margin-bottom:8px; }
  #uploads { margin-top:14px; }
  /* v2.8.17 (j): ONE floating upload indicator. A CIRCULAR
     progress bar -- elegant, classic, SOLID BLUE (#277ff0) --
     showing upload progress in real time; the NUMBER inside
     the circle is the files still queued and decrements as
     each finishes, while the ring keeps filling. The file
     name is truncated with an ellipsis and never overflows
     the border.
     v2.8.24 (3): the ring moved OFF the footer -- it now sits
     at the TOP of the Shared Files card (top edge, just below
     the top pill; positioned by _upShow from the files
     column's rect, bottom of the pill touching the card's top
     edge), so it never overlaps the footer / slogan again.
     It is SOLID now (themed card background + border, never
     transparent), so it reads on any background, and it has
     an X button (.upcancel) that cancels the in-flight
     upload. Only the X takes pointer events; the rest of the
     pill lets clicks through to the card beneath it.
     v2.8.25 (2): the pill is the SAME SIZE as the "Devices
     Connected" pill (.devpill .status) -- height 36px,
     padding 0 14px, gap 6px, name 13px -- so the ring shrinks
     to 28px and the X to 20px; only the size changed.
     v2.8.26: the pill is a FIXED WIDTH (272px) and sits a
     little HIGHER (12px clear gap above the Shared Files
     card, was 4px). The name flexes inside the fixed width
     with an ellipsis, so a long file name can never stretch
     the pill wider or taller -- short and 80+ char names
     measure identical.
     v2.8.27: the pill must never TOUCH the search button
     (#askbtn, top-right). At desktop widths the board is
     centred with a max-width while the search button sits at
     the viewport's far right, so the pill (centred on the
     files column) overlapped the button by 2px at 1280px.
     _upKeepClearOfSearch shifts the pill left after every
     positioning so its right edge stays >= 8px clear of the
     button's left edge; size, height and the 12px card gap
     are untouched.
     v2.8.28: the pill is the SAME WIDTH as the "Devices
     Connected" pill (#statusdiv, X included) -- _upShow
     copies the Devices pill's live width onto the pill, so
     it matches in every state (the Devices pill's width
     follows its text). At 1280px with "No devices
     connected" that is 192px (was a fixed 272px). The pill
     also sits slightly HIGHER, LINED UP with the search
     button: when the pill's vertical band is near the
     button's, its centre is snapped to the button's centre
     (52px at 1280px, was 58px) -- a 6px move, and the gap
     above the Shared Files card grows 12px -> 18px. It
     stays centred on the files column, so it stays centred
     and aligned with the Devices pill (same width, same
     36px height, same padding/font). The name still
     ellipsises inside the fixed width. */
  .upfloat { display:none; position:fixed; left:50%; transform:translateX(-50%); top:88px; z-index:300; align-items:center; gap:6px; background:var(--card); border:1px solid var(--line); border-radius:999px; height:36px; width:272px; box-sizing:border-box; padding:0 14px; box-shadow:0 10px 30px rgba(0,0,0,.35); pointer-events:none; max-width:calc(100vw - 24px); transition:opacity .4s ease; }
  .upfloat.show { display:flex; }
  /* v2.8.31: the pill FADES OUT after the last file -- it never
     shows a "0" state. .fading animates opacity to 0, then
     _upHide removes .show. */
  .upfloat.fading { opacity:0; }
  .upring { width:28px; height:28px; flex:none; filter:drop-shadow(0 2px 8px rgba(0,0,0,.45)); }
  .upring-track { fill:none; stroke:rgba(127,140,180,.35); stroke-width:6; }
  html.light .upring-track { stroke:rgba(15,23,42,.25); }
  .upring-prog { fill:none; stroke:#277ff0; stroke-width:6; stroke-linecap:round; stroke-dasharray:163.36; stroke-dashoffset:163.36; transition:stroke-dashoffset .15s linear; }
  .upring-num { fill:var(--txt); font-size:27px; font-weight:800; text-anchor:middle; font-family:inherit; }
  .upfloat-name { flex:1 1 auto; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:13px; font-weight:700; color:var(--txt); }
  .upcancel { flex:none; width:20px; height:20px; border:none; border-radius:50%; background:#ef4444; color:#fff; font-size:13px; font-weight:700; line-height:1; cursor:pointer; pointer-events:auto; display:inline-flex; align-items:center; justify-content:center; padding:0; font-family:inherit; }
  .upcancel:hover { filter:brightness(1.12); }
  .frow { display:flex; align-items:center; gap:12px; padding:10px 8px; margin:0 -8px;
          border-top:1px solid var(--line); font-size:14px; border-radius:12px; transition:background .15s; }
  .frowtop { display:flex; align-items:center; gap:12px; flex:1 1 auto; min-width:0; }
  .frow:first-child { border-top:none; }
  .frow:hover { background:rgba(34,211,238,.05); }
  .thumb { width:54px; height:54px; object-fit:cover; border-radius:12px; flex:none;
          border:1px solid var(--line); background:#090c15; }
  .fic { font-size:20px; }
  .fic svg { display:block; }
  .thwrap { position:relative; width:54px; height:54px; flex:none; }
  .thwrap .fic { display:flex; align-items:center; justify-content:center;
          width:54px; height:54px; border:1px solid var(--line); border-radius:12px; background:#090c15; }
  .tbadge { position:absolute; right:-6px; bottom:-6px; font-size:12px; line-height:1;
          background:#141a30; border:1px solid var(--line); border-radius:7px; padding:2px 3px; }
  .tbadge svg { display:block; }
  /* v2.8.19: in DARK mode the file-type text labels on the
     thumbnails (PDF / DOCX / CTFB / SIG ...) are WHITE so they
     read against the dark badge background. */
  .tbadge.tlabel { font-size:9px; font-weight:800; letter-spacing:.5px; padding:3px 5px; color:#ffffff; }
  .fmeta { flex:1 1 auto; min-width:0; display:flex; flex-direction:column; gap:3px; }
  .fname { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:600; font-size:13.5px; }
  .fsize { color:var(--muted); font-size:11.5px; white-space:nowrap; }
  .ftime { color:var(--muted); font-size:11px; white-space:nowrap; opacity:.8; }
  .btn { border:1px solid var(--line); background:#090c15; color:var(--txt); border-radius:10px;
         padding:8px 14px; font-size:13px; cursor:pointer; text-decoration:none; white-space:nowrap;
         transition:border-color .15s, filter .15s; }
  .btn:hover { border-color:var(--acc); }
  .frow .btn { padding:8px 10px; font-size:12px; }
  .btn.primary { background:linear-gradient(135deg,var(--acc),var(--acc2)); border:none;
         color:#0a0f1e; font-weight:700; }
  .btn.primary:hover { filter:brightness(1.12); }
  .btn.danger:hover { border-color:var(--bad); color:var(--bad); }
  .btn.dangergrad { background:#ef4444; border:none; color:#fff; font-weight:700;
         display:inline-flex; align-items:center; justify-content:center; gap:6px; }
  .btn.dangergrad:hover { filter:brightness(1.12); border:none; }
  .btn.dangergrad svg { width:15px; height:15px; flex:none; }
  .fstack { display:inline-flex; flex-direction:column; gap:6px; align-items:stretch; }
  .fstack .btn, .fstack .msavedbtn { width:100%; margin:0; }
  /* inline file actions: compact, uncluttered */
  .fact { display:flex; gap:8px; margin-left:auto; flex:none; }
  .fact button { flex:none; width:36px; height:36px; box-sizing:border-box;
    display:inline-flex; align-items:center; justify-content:center; padding:0;
    background:rgba(20,25,38,.55); border:1px solid var(--line);
    border-radius:12px; cursor:pointer; color:var(--txt); }
  .fact button:active { filter:brightness(1.15); }
  .fact button svg { width:17px; height:17px; display:block; }
  .fact button .em { font-size:17px; line-height:1; }
  .fact button.del { background:#ef4444; color:#fff; }
  /* AI scanning spinner: shows while a new file is checked for text */
  .fact .aiload { width:36px; height:36px; box-sizing:border-box; flex:none;
    display:inline-flex; align-items:center; justify-content:center; }
  .fact .aiload::after { content:""; width:16px; height:16px; border-radius:50%;
    border:2px solid rgba(147,51,234,.25); border-top-color:#a855f7;
    animation:aispin 0.8s linear infinite; }
  @keyframes aispin { to { transform:rotate(360deg); } }
  /* busy state for the download/open button while a download runs */
  .fact button.busy { pointer-events:none; }
  .fact button.busy svg { display:none; }
  .fact button.busy::after { content:""; width:15px; height:15px; border-radius:50%;
    border:2px solid rgba(255,255,255,.25); border-top-color:#22d3ee; animation:aispin .8s linear infinite; }
  /* icon-only header buttons (e.g. the delete-mode trash) */
  .btn.iconbtn { padding:8px 12px; }
  /* delete-selection mode: checkboxes hidden until the trash icon is tapped */
  .fsel { flex:none; width:0; height:26px; margin-right:-12px; opacity:0; transform:scale(.3);
    border-radius:50%; border:2px solid var(--muted); box-sizing:border-box; overflow:hidden;
    display:inline-flex; align-items:center; justify-content:center; color:transparent;
    transition:width .25s ease, margin .25s ease, opacity .18s ease, transform .3s cubic-bezier(.34,1.56,.64,1), background .15s, border-color .15s; }
  .fsel svg { width:13px; height:13px; flex:none; }
  .selmode .fsel { width:26px; margin-right:0; opacity:1; transform:scale(1); }
  .selmode .frow { cursor:pointer; }
  .frow.picked { background:rgba(239,68,68,.08); border-radius:12px; }
  .frow.picked .fsel { background:linear-gradient(135deg,#ef4444,#e11d48); border-color:transparent; color:#fff; }
  /* floating confirm bar for delete-selection mode */
  .delbar { position:fixed; left:50%; bottom:88px; transform:translateX(-50%) translateY(24px);
    display:flex; gap:10px; align-items:center; background:rgba(17,24,39,.97); border:1px solid var(--line);
    border-radius:999px; padding:8px; z-index:130; opacity:0; pointer-events:none; transition:.25s;
    box-shadow:0 16px 40px rgba(0,0,0,.5); max-width:94vw; }
  .delbar.show { opacity:1; transform:translateX(-50%) translateY(0); pointer-events:auto; }
  .delbar .delcount { font-size:13px; color:var(--muted); padding:0 2px 0 10px; white-space:nowrap; }
  .delbar button { border:none; border-radius:999px; padding:10px 18px; font-size:14px; font-weight:700;
    cursor:pointer; font-family:inherit; white-space:nowrap; }
  .delbar .confirmdel { background:#ef4444; color:#fff; }
  .delbar .confirmdel:disabled { opacity:.25; }
  /* v2.7.89: guest delete when the host toggle is OFF -- the
     button stays VISIBLE but greyed out; tapping it toasts the
     not-authorized message instead of deleting. */
  .deloff { opacity:.25 !important; filter:grayscale(1); }
  /* v2.8.39 (6): a STARRED note stays visibly starred while its
     star is greyed out (star permission removed) -- the filled
     star renders greyed at readable opacity, so the host's
     starred notes are still visible. Unstarred notes keep the
     plain .25 grey above. */
  .starbtn.starred.deloff { opacity:.6 !important; }
  .starbtn.starred.deloff svg { fill:#9ca3af; }
  .delbar .canceldel, .delbar .selall { background:#1f2937; color:var(--txt); }
  /* Saved-viewer selection tools */
  .svtools { display:flex; justify-content:flex-end; margin-bottom:10px; }
  .svbar { display:none; gap:10px; align-items:center; margin:0 0 12px; flex-wrap:wrap; }
  .svbar.show { display:flex; }
  .svbar .delcount { font-size:13px; color:var(--muted); flex:1; }
  .svbar button { border:none; border-radius:999px; padding:9px 16px; font-size:13.5px; font-weight:700;
    cursor:pointer; font-family:inherit; white-space:nowrap; }
  .svbar .confirmdel { background:#ef4444; color:#fff; }
  .svbar .confirmdel:disabled { opacity:.25; }
  .svbar .canceldel, .svbar .selall { background:#1f2937; color:var(--txt); }
  /* AI popup menu */
  .aipop { position:fixed; z-index:1000; min-width:190px;
    background:rgba(17,24,39,.97); border:1px solid rgba(147,51,234,.4);
    border-radius:14px; padding:6px; box-shadow:0 12px 32px rgba(0,0,0,.5);
    backdrop-filter:blur(8px); }
  .aipop button { display:flex; align-items:center; gap:10px; width:100%;
    background:none; border:none; color:#e5e7eb; font-size:14px; padding:10px 12px;
    border-radius:10px; cursor:pointer; text-align:left; }
  .aipop button:hover:not(:disabled) { background:rgba(147,51,234,.18); }
  .aipop button:disabled { opacity:.38; cursor:not-allowed; }
  .aipop button .em { font-size:17px; }
  /* AI result modal */
  .aimodalwrap { position:fixed; inset:0; z-index:1001; display:flex;
    align-items:center; justify-content:center; padding:20px;
    background:rgba(0,0,0,.6); backdrop-filter:blur(4px); }
  .aimodal { max-width:560px; width:100%; max-height:80vh; display:flex; flex-direction:column;
    background:#111827; border:1px solid rgba(147,51,234,.35); border-radius:18px;
    box-shadow:0 24px 64px rgba(0,0,0,.6); overflow:hidden; }
  .aimodal header { display:flex; align-items:center; justify-content:space-between;
    padding:14px 18px; border-bottom:1px solid rgba(255,255,255,.08);
    font-weight:700; font-size:15px; }
  .aimodal header button { background:none; border:none; color:#9ca3af; font-size:20px;
    cursor:pointer; padding:0 4px; }
  .aimodal .abody { padding:18px; overflow-y:auto; white-space:pre-wrap;
    font-size:14px; line-height:1.6; color:#e5e7eb;
    user-select:text; -webkit-user-select:text; cursor:text; }
  .aimodal header .ahbtns { display:flex; flex-direction:column; gap:6px; align-items:stretch; flex:none; margin-left:12px; }
  .aimodal header .aclose { width:30px; height:30px; align-self:flex-end; display:inline-flex;
    align-items:center; justify-content:center; padding:0; cursor:pointer;
    background:#ef4444; border:none; border-radius:8px; color:#fff; }
  .aimodal header .aclose svg { width:14px; height:14px; display:block; }
  .aimodal header .aclose:active { filter:brightness(1.15); }
  .aimodal header .acopy { font-size:13px; font-weight:700; color:#0a0f1e; white-space:nowrap;
    background:linear-gradient(135deg,#22d3ee,#818cf8); border:none; border-radius:8px;
    padding:7px 14px; cursor:pointer; font-family:inherit; }
  .aimodal header .acopy:active { filter:brightness(1.15); }
  .aimodal header .apacks { font-size:13px; font-weight:700; color:#0a0f1e; white-space:nowrap;
    background:linear-gradient(135deg,#fbbf24,#f97316); border:none; border-radius:8px;
    padding:7px 14px; cursor:pointer; font-family:inherit; }
  .aimodal header .apacks:active { filter:brightness(1.15); }
  /* AI-style bouncing dots while transcribing / translating */
  .ailoading { display:inline-flex; gap:7px; align-items:center; padding:10px 2px; }
  .ailoading i { width:9px; height:9px; border-radius:50%; background:#a855f7;
    animation:ailbounce 1.2s infinite ease-in-out; }
  .ailoading i:nth-child(2) { animation-delay:.15s; }
  .ailoading i:nth-child(3) { animation-delay:.3s; }
  @keyframes ailbounce { 0%,60%,100% { transform:translateY(0); opacity:.35; } 30% { transform:translateY(-8px); opacity:1; } }
  .empty { color:var(--muted); font-size:14px; padding:10px 4px; }
  .connectbar { display:flex; align-items:center; justify-content:center; gap:8px; background:#090c15; border:1px solid var(--line);
         border-radius:999px; padding:6px 8px 6px 16px; }
  .connectbar a { color:var(--acc); font-weight:700; font-size:14px; text-decoration:none; word-break:break-all; }
  /* v2.7.87 desktop top bar: the link field is NARROW and CENTRED
     (clamp(280px, 24vw, 420px) -- 390px at a 1625px viewport, the
     screenshot spec -- never the old full-width pill), with the QR
     code INSIDE the field on the left, shrunk to fit the field
     height. The link name, lock icon and copy icon are flex items
     that cannot overlap: the name flexes with ellipsis, the icons
     are fixed-size. The devices indicator stays in its own
     non-overlapping slot (flex:none). No technical address is ever
     shown here. The QR popup is a SMALL centred in-window popup
     (fixed, backdrop, 220px QR), never fullscreen, dismissed by
     click-outside, the x button, or Escape. Palette (classic
     futuristic, SOLID colours only):
     dark field #090c15, cyan accent #22d3ee, amber lock #f59e0b. */
  .topbar { position:relative; min-height:52px; }
  /* With the field absolutely centred (wide screens only), the
     left cluster (menu + Devices pill) takes the free space on
     its right so Search clusters at the right edge instead of
     spreading under the field. At narrower widths the field is
     back in flow, so the auto margin must not apply there. */
  @media (min-width:1084px){
    .topbar-left { margin-right:auto; }
  }
  /* v2.7.96: the top bar is a single row again (Devices pill
     moved above the Send card), so the Address pill is centred
     on the whole bar (top:50%), not on a row-1 offset. */
  .connectwrap { position:absolute; left:50%; top:50%; transform:translate(-50%,-50%);
                 width:clamp(280px, 24vw, 420px); display:flex; align-items:center; min-width:0; }
  .connectbar { flex:1 1 auto; min-width:0; height:48px; box-sizing:border-box;
                display:flex; align-items:center; gap:8px; padding:5px 10px;
                background:#090c15; border:1px solid #22d3ee; border-radius:999px; }
  .connectbar a { flex:1 1 auto; min-width:0; white-space:nowrap; overflow:hidden;
                  text-overflow:ellipsis; text-align:center; }
  .connectbar .qrmini { flex:none; padding:2px; border-radius:8px; }
  .connectbar .qrmini img { width:30px; height:30px; }
  .connectbar .copybtn { flex:none; width:36px; height:36px; padding:0; border-radius:50%;
                         display:inline-flex; align-items:center; justify-content:center; }
  .connectbar .copybtn svg { width:17px; height:17px; display:block; }
  .connectbar #linklock.locked { color:#f59e0b; border-color:#f59e0b; }
  .status { flex:none; white-space:nowrap; }
  /* v2.7.99: the Devices pill NO LONGER lives in the top bar
     (v2.7.98's top-left placement is superseded -- see the
     .devpill rules: the pill is an overlay centred on the
     Send card's top edge). The top bar is menu + centred
     Address pill + Search again, with no Devices slot. */
  /* v2.7.99 Devices Connected: NO LONGER in the top bar (the
     v2.7.98 top-left placement is superseded by Essef's Nov 2
     redirection). It is an OVERLAY centred on the SEND card's
     top edge: absolutely positioned, straddling the card's top
     border, taking NO flow space -- so it adds no row, grows
     no page height and resizes no card (a v2.7.97-style row
     above Send is exactly what this must not be). The Send
     column alone gets overflow:visible so the straddling half
     and the dropdown below it are never clipped; every other
     column keeps overflow:hidden. The pill itself is
     BORDERLESS (border:none, solid theme background kept so
     the text reads on both themes), fitted to its content,
     pointer cursor, with a SMALL elegant chevron arrow beside
     the text: a 6px gap (a few pixels, not a wide separation),
     same vertical centre line (align-items:center). */
  .topbar-left { display:flex; align-items:center; gap:10px; flex:none; min-width:0; }
  /* v2.8.2: pill FULLY OUTSIDE the Send card. v2.8.0's
     top:-10px + translate(-50%,-50%) left the pill spanning
     -28px..+8px, i.e. its bottom 8px still overlapped the
     card -- that is why Essef still saw it "stuck in the
     card". Now top:-44px with translateX only, so the 36px
     pill spans -44px..-8px: an 8px clear gap above the card,
     zero overlap, no resize of card/page/column. The
     dropdown still hangs from the pill at top:100% (no gap
     between pill and dropdown, so the hover fix holds). */
  .devpill { position:absolute; left:50%; top:-54px; transform:translateX(-50%); z-index:60; width:max-content; max-width:calc(100% - 24px); }
  .devpill .status { background:#12172a; border:none; border-radius:999px; padding:0 14px; height:36px; display:flex; align-items:center; gap:6px; width:auto; max-width:100%; flex:none; white-space:nowrap; overflow:hidden; font-size:13px; color:#eef1f8; cursor:pointer; box-shadow:0 8px 24px rgba(0,0,0,.35); }
  /* v2.8.19: the no-device pill text is reverted to the plain
     "No devices connected" (2.8.18's "to this address" addition
     is dropped -- Essef never asked for it). The text may still
     wrap on a narrow pill instead of being cut off with an
     ellipsis. */
  .devpill .status #statustext { color:#eef1f8; min-width:0; white-space:normal; line-height:1.25; }
  .devpill .dot { flex:none; }
  .devpill .devarrow { flex:none; display:inline-flex; align-items:center; justify-content:center; width:10px; height:10px; }
  .devpill .devarrow svg { width:10px; height:10px; display:block; }
  html.light .devpill .status { background:#ffffff; color:#0f172a; box-shadow:0 8px 24px rgba(15,23,42,.20); }
  html.light .devpill .status #statustext { color:#0f172a; }
  /* v2.7.99 Devices dropdown: opens from the Send-card pill
     (hover on the arrow, or click on the text -- same window).
     Animated drop-down (slide + fade from the pill), sized to
     its content (width:max-content within a min/max band, so
     it grows/shrinks with the device count); the scroller is
     the thin Files-tab style and, with overflow-y:auto, is
     ABSENT when few devices need no scroll. Theme backgrounds
     match the pill (dark card / light white). Labels are
     Title Case; device names render as-is (no case transform
     anywhere in this window). Disconnect All sits at the
     BOTTOM, RED. Host-only: guests never see these controls
     (the pill click for a guest toasts the host-only message
     instead of opening this window). */
  /* v2.8.0 hover fix: the old 8px gap between pill and dropdown
     meant moving the mouse down onto the dropdown crossed
     open space, firing mouseleave and closing it before it
     could be reached. top:100% removes the gap entirely, so
     the pointer travels straight from pill into dropdown. */
  .devdrop { position:absolute; left:50%; top:100%; transform:translateX(-50%) translateY(0); width:max-content; min-width:240px; max-width:min(320px, calc(100vw - 32px)); max-height:300px; display:flex; flex-direction:column; background:#12172a; border:1px solid #2a3560; border-radius:14px; box-shadow:0 16px 40px rgba(0,0,0,.45); z-index:61; opacity:0; visibility:hidden; pointer-events:none; transition:opacity .22s ease, transform .22s ease, visibility 0s linear .22s; overflow:hidden; }
  .devdrop.open { opacity:1; visibility:visible; pointer-events:auto; transform:translateX(-50%) translateY(0); transition:opacity .22s ease, transform .22s ease; }
  html.light .devdrop { background:#ffffff; border-color:#c3cfde; box-shadow:0 16px 40px rgba(15,23,42,.25); }
  .devdroptitle { font-size:13px; font-weight:700; padding:12px 14px 8px; border-bottom:1px solid var(--line); }
  .devdroprows { overflow-y:auto; scrollbar-width:thin; scrollbar-color:#2a3560 transparent; }
  .devdroprows::-webkit-scrollbar { width:8px; }
  .devdroprows::-webkit-scrollbar-thumb { background:#2a3560; border-radius:8px; }
  .devdroprows::-webkit-scrollbar-track { background:transparent; }
  html.light .devdroprows::-webkit-scrollbar-thumb { background:#b6c2d4; }
  .devrow { display:flex; align-items:center; gap:10px; padding:10px 14px; border-bottom:1px solid var(--line); }
  .devrow:last-child { border-bottom:none; }
  .devrow .devmeta { flex:1 1 auto; min-width:0; display:flex; flex-direction:column; gap:2px; }
  .devrow .devname { font-size:14px; font-weight:700; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .devrow .devmodel { font-size:12px; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .devrow .devdisc { flex:none; border:1px solid var(--line); background:var(--card2); color:var(--txt); border-radius:9px; padding:7px 11px; font-size:12.5px; cursor:pointer; font-family:inherit; white-space:nowrap; }
  .devrow .devdisc:hover { border-color:var(--acc); }
  .devempty { font-size:13px; color:var(--muted); padding:12px 14px; }
  .devdropfoot { border-top:1px solid var(--line); padding:10px 12px; }
  .devdropfoot .devdropall { width:100%; background:#ef4444; border:1px solid #ef4444; color:#ffffff; border-radius:10px; padding:10px 12px; font-size:13.5px; font-weight:700; cursor:pointer; font-family:inherit; }
  .devdropfoot .devdropall:hover { filter:brightness(1.12); }
  /* v2.7.94 top pill: link icon inside the pill, before the
     coloured address text (no prefix, no dot). */
  #toplink svg { width:16px; height:16px; flex:none; vertical-align:-3px; margin-right:6px; }
  #toplink .addname { font-weight:700; }
  /* v2.7.94 Search matches the menu button's purple/blue gradient.
     v2.7.95: icon-only -- the "Find" text is gone, only the
     magnifying glass remains, with a small AI sparkle accent
     (.findspark) in the corner: same gradient + glow as the
     menu button, tooltip / aria label stays "Search".
     v2.7.96: Search is the SAME SIZE as the menu icon -- the
     button box is the menu button's 36x36 and the glass is
     16px, the menu bars' width -- icon-only with sparkle kept. */
  #askbtn { background:linear-gradient(135deg,#7C3AED,#0EA5E9); border:none; color:#fff; font-weight:700; box-shadow:0 4px 12px rgba(124,58,237,.35); width:36px; height:36px; padding:0; flex:none; display:inline-flex; align-items:center; justify-content:center; position:relative; }
  #askbtn:hover { filter:brightness(1.1); border:none; }
  #askbtn .findglass { width:16px; height:16px; display:block; }
  #askbtn .findspark { position:absolute; top:3px; right:3px; width:10px; height:10px; line-height:0; pointer-events:none; }
  #askbtn .findspark svg { width:10px; height:10px; display:block; filter:drop-shadow(0 0 4px rgba(251,191,36,.9)); }
  /* v2.7.94 popup X buttons (Set up your addresses + Set
     Password): RED with their own border, well inside the
     popup's top-right corner. Shared style for both popups.
     v2.7.96: both Xs use EXACTLY this shared class -- no later
     rule may restyle the Set Up X (no background:none, no
     muted colour, no different size), and both get the pointer
     cursor on hover. */
  .lkbox .lkclosebtn, .lockpwbox .lkclosebtn { background:linear-gradient(135deg,#ef4444,#e11d48); border:1px solid #ef4444; color:#fff; border-radius:9px; width:32px; height:32px; display:inline-flex; align-items:center; justify-content:center; font-size:20px; line-height:1; padding:0; box-shadow:0 2px 8px rgba(239,68,68,.35); cursor:pointer; }
  /* v2.7.94 Set up fields: New Address and Password share the
     .lkfield size (same height/width class); the gap between
     them is tight -- the error line under New Address keeps no
     reserved height and the Password label sits close above it. */
  .lkfield { width:100%; box-sizing:border-box; padding:13px 12px; font-size:15px; height:48px; }
  #lkpwlabel { margin-top:6px; }
  #lkerr { min-height:0; margin-top:2px; }
  /* v2.7.94 current-address dropdown trigger: the current
     address field itself (positioned, so its list drops below
     it); the chevron sits inside the field. */
  .lkcurdd { position:relative; cursor:pointer; }
  .lkcurdd .ddchev { flex:none; font-size:14px; color:var(--muted); }
  /* v2.8.17 (f): Set Up copy -- classic copy icon in the Current
     Address row; copies the FULL URL (see #lkcopy handler). */
  .lkview .lkcopybtn { flex:none; background:none; border:none; cursor:pointer; color:var(--txt); padding:6px; border-radius:8px; display:inline-flex; align-items:center; justify-content:center; }
  .lkview .lkcopybtn svg { width:17px; height:17px; display:block; }
  .lkview .lkcopybtn:hover { background:rgba(127,140,180,.15); }
  .lkcurdd .ddlist { z-index:60; }
  .techaddr { display:none; }
  .qrmini { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:4px;
            cursor:pointer; line-height:0; }
  .qrmini:empty { display:none; }
  .qrmini img { width:52px; height:52px; display:block; border-radius:6px; background:#fff; padding:2px; }
  .qrpop { display:none; position:fixed; inset:0; z-index:300; background:rgba(3,5,10,.72);
           flex-direction:column; align-items:center; justify-content:center; gap:12px; padding:20px; }
  .qrpop.open { display:flex; }
  .qrpop .qr { background:var(--card); border:1px solid var(--line); border-radius:20px; padding:22px; box-shadow:0 24px 60px rgba(0,0,0,.45); }
  .qrpop .qr img { width:220px; height:220px; background:#fff; padding:10px; border-radius:12px; }
  .qrpop .qr div { color:var(--muted); }
  .qrpop .hint { color:#dbe4f0; text-align:center; max-width:300px; margin-top:0; }
  .qrpopclose { position:absolute; top:18px; right:22px; width:38px; height:38px; border-radius:50%;
                border:1px solid var(--line); background:#10182b; color:var(--txt); font-size:22px;
                line-height:1; cursor:pointer; }
  .qrpopclose:hover { border-color:#22d3ee; }
  @media (max-width:1083px){
    .connectwrap { position:static; transform:none; flex:1 1 auto; width:auto; }
    .connectbar { height:44px; }
  }
  .board { display:flex; flex-wrap:wrap; gap:14px; justify-content:center; align-items:stretch;
           flex:1 1 auto; min-height:0; width:100%; }
  .col { background:linear-gradient(180deg,var(--card2),var(--card)); border:1px solid var(--line);
          border-radius:18px; padding:18px; box-shadow:0 12px 32px rgba(0,0,0,.35);
          position:relative; overflow:visible; width:340px; max-width:100%; flex:0 0 auto;
          height:calc(100vh - 210px); height:calc(100dvh - 210px); min-height:240px;
          display:flex; flex-direction:column; }
  .col::before { content:""; position:absolute; top:0; left:24px; right:24px; height:1px;
          background:linear-gradient(90deg,transparent,rgba(34,211,238,.55),rgba(167,139,250,.55),transparent); }
  .colhead { display:flex; align-items:center; gap:10px; margin-bottom:14px; flex-wrap:wrap; row-gap:8px; }
  .colhead h2 { font-size:12px; text-transform:uppercase; letter-spacing:.1em; color:var(--muted); }
  /* v2.8.17 (m): the Shared Files heading sits a little to the
     right so its text aligns with the file thumbnails below it
     (probe-measured: the heading started 4px left of the
     thumbnails at 390px and on desktop). */
  .col[data-col="files"] .colhead h2 { margin-left:4px; }
  .count { font-size:11px; color:var(--muted); border:1px solid var(--line); background:#090c15;
           padding:2px 9px; border-radius:12px; }
  .count:empty { display:none; }
  .colbody { display:flex; flex-direction:column; gap:12px; flex:1; min-height:0; overflow-y:auto;
             padding-right:4px; scrollbar-width:thin; scrollbar-color:#2a3560 transparent; }
  /* v2.7.96: the Set Up dialog's scroll area uses EXACTLY the
     Files tab scroller (same width, thumb colour, track) --
     the grouped rules below, not a chunkier default scrollbar. */
  .colbody::-webkit-scrollbar, .lkbox::-webkit-scrollbar { width:8px; }
  .colbody::-webkit-scrollbar-thumb, .lkbox::-webkit-scrollbar-thumb { background:#2a3560; border-radius:8px; }
  .colbody::-webkit-scrollbar-track, .lkbox::-webkit-scrollbar-track { background:transparent; }
  .lkbox { scrollbar-width:thin; scrollbar-color:#2a3560 transparent; }
  .minicard { background:#090c15; border:1px solid var(--line); border-radius:14px; padding:16px; }
  .minicard h3 { font-size:13.5px; font-weight:650; margin-bottom:12px; display:flex; align-items:center; gap:8px; }
  .hicon { width:20px; height:20px; flex:none; filter:drop-shadow(0 2px 6px rgba(129,140,248,.4)); }
  footer { text-align:center; color:var(--muted); font-size:12px; margin-top:26px; }
  .mtabs { display:none; }
  .nbtnrow, .fbtnrow { display:flex; gap:8px; margin:0 0 12px; }
  .nbtnrow .btn { flex:1 1 0; min-width:0; margin:0; padding:8px 6px; font-size:12px;
    border-radius:12px; display:inline-flex; align-items:center; justify-content:center; gap:6px;
    overflow:hidden; text-overflow:ellipsis; }
  .fbtnrow { gap:6px; }
  .fbtnrow .btn { flex:1 1 0; min-width:0; margin:0; padding:10px 4px; font-size:13px;
    border-radius:12px; display:inline-flex; align-items:center; justify-content:center; gap:5px;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .nbtnrow .btn svg, .fbtnrow .btn svg { width:15px; height:15px; flex:none; }
  .btn.openf { background:linear-gradient(135deg,#277ff0,#0ea5e9); border:none;
    color:#052e33; font-weight:700; }
  .btn.openf:hover { filter:brightness(1.12); border:none; }
  .btn.changef { background:linear-gradient(135deg,#8B5CF6,#6D28D9); border:none;
    color:#fff; font-weight:700; }
  .btn.changef:hover { filter:brightness(1.12); border:none; }
  .msavedbtn { display:none; }
  .mqrmini { display:none; }
  .msend { display:none; }
  .mlabel { font-size:11px; letter-spacing:.14em; text-transform:uppercase; color:var(--muted); font-weight:700; margin-bottom:10px; }
  .mbtn-primary { width:100%; margin-top:12px; padding:13px; border:none; border-radius:13px; font-size:15px;
           font-weight:800; font-family:inherit; color:#0a0f1e; cursor:pointer;
           background:linear-gradient(135deg,#818cf8,#22d3ee); }
  .mbtn-secondary { width:100%; padding:13px; border-radius:13px; font-size:15px; font-weight:700;
           font-family:inherit; color:var(--txt); background:#10182b; border:1px solid var(--line); cursor:pointer; }
  .mbtn-primary:active, .mbtn-secondary:active { filter:brightness(1.2); }
  #muploads { margin-top:10px; }
  .nact { display:flex; gap:8px; margin-top:11px; flex-wrap:wrap; }
  .nact button { flex:1 1 0; min-width:0; display:flex; align-items:center; justify-content:center;
          padding:7px 4px; background:linear-gradient(135deg,var(--c1,#22d3ee),var(--c2,#0ea5e9));
          border:none; border-radius:10px; cursor:pointer; color:#0a0f1e; }
  .nact button svg { width:15px; height:15px; display:block; }
  .nact button .em { font-size:15px; line-height:1; }
  .nact button:active { filter:brightness(1.15); }
  .mdlg { display:none; position:fixed; inset:0; z-index:110; background:rgba(4,6,12,.82);
          align-items:center; justify-content:center; padding:22px; }
  /* v2.8.37 (2): the download confirm dialog (#cfdlg) must
     render ABOVE the in-page preview (.previewpop, z 1001) --
     it was z 110, so the "Save on this device?" prompt sat BEHIND
     the preview and could not be clicked while a preview was
     open. 2000 sits above preview (1001) and viewer (100) but
     below the connect popup / toast (5000). The New Shared
     Text dialog (#mdlg) keeps z 110. */
  #cfdlg { z-index:2000; }
  /* v2.8.38 (8): the download confirm's Save button reads
     "Save on this device" and is SOLID BLUE with WHITE text
     in both themes (it was the gradient .btn.primary with dark
     text). The Discard button beside it is untouched. */
  #cfdlg #cfyes, html.light #cfdlg #cfyes { background:#277ff0; color:#ffffff; border:none; }
  #cfdlg #cfyes:hover, html.light #cfdlg #cfyes:hover { filter:brightness(1.12); }
  .mdlg.open { display:flex; }
  .mbox { width:100%; max-width:430px; background:var(--card2); border:1px solid var(--line);
          border-radius:16px; padding:18px; box-shadow:0 18px 50px rgba(0,0,0,.5); }
  .mbox h3 { font-size:16px; margin:0 0 12px; }
  .cfmsg { color:var(--muted); font-size:14px; line-height:1.55; margin:0 0 16px; word-break:break-word; }
  .mdlg .mrow { display:flex; gap:10px; }
  .mdlg .mrow .btn { flex:1; }
  .mbox textarea { width:100%; box-sizing:border-box; min-height:130px; background:#090c15;
          border:1px solid var(--line); border-radius:10px; color:var(--txt); padding:12px;
          font-size:14.5px; font-family:inherit; resize:vertical; }
  .mbox textarea:focus { outline:none; border-color:var(--acc); }
  .mbox .mrow { display:flex; gap:10px; margin-top:12px; }
  .mbox .mrow .btn { flex:1; padding:11px; font-size:14px; }
  .viewer { display:none; position:fixed; inset:0; z-index:100; background:rgba(4,6,12,.93);
            align-items:center; justify-content:center; padding:18px; }
  .viewer.open { display:flex; }
  .vbox { width:100%; max-width:640px; max-height:88vh; max-height:88dvh; overflow:auto;
          background:var(--card); border:1px solid var(--line); border-radius:16px; padding:14px; }
  .vhead { display:flex; justify-content:space-between; align-items:center; gap:10px; margin-bottom:10px; }
  #vtitle { font-size:13px; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .vclose { background:#1a2036; border:1px solid var(--line); color:var(--txt); border-radius:10px;
            width:34px; height:34px; font-size:15px; cursor:pointer; flex:0 0 auto; }
  #vcontent img { max-width:100%; border-radius:10px; display:block; margin:0 auto; max-height:calc(88vh - 100px); max-height:calc(88dvh - 100px); }
  #vcontent video { width:auto; max-width:100%; max-height:calc(88vh - 100px); max-height:calc(88dvh - 100px); border-radius:10px; background:#000; display:block; margin:0 auto; }
  #vcontent audio { width:100%; }
  #vcontent iframe { width:100%; height:70vh; border:none; border-radius:8px; background:#fff; }
  #vcontent pre { white-space:pre-wrap; word-break:break-word; font-size:13px; max-height:60vh;
                 overflow:auto; background:#090c15; border:1px solid var(--line);
                 border-radius:10px; padding:12px; }
  .docxview { text-align:left; line-height:1.65; font-size:15px; }
  .docxview h1,.docxview h2,.docxview h3,.docxview h4 { margin:.7em 0 .35em; line-height:1.3; }
  .docxview p { margin:.45em 0; }
  .docxview table.dx { border-collapse:collapse; margin:.7em 0; max-width:100%; }
  .docxview table.dx td { border:1px solid var(--line); padding:6px 9px; }
  .vrow { display:flex; align-items:center; gap:10px; padding:10px 4px; border-top:1px solid var(--line); }
  .vrow .fname { flex:1; }
  @media (max-width:720px){
    body { padding:16px 12px 86px; display:block; height:auto; }
    .board { display:block; flex:none; }
    .board .col { display:none; width:100%; margin:0;
             height:calc(100vh - 330px); height:calc(100dvh - 330px); min-height:340px; }
    /* v2.7.98 mobile: no Send wrapper any more -- the Devices
       pill lives in the top bar, so the Send card is a plain
       direct board child like every other tab, and the
       generic tab rule below gives it exactly the other
       tabs' height (calc(100dvh - 205px)), no shrink, no
       extra row. */
    body[data-mtab="send"] .board .col,
    body[data-mtab="notes"] .board .col,
    body[data-mtab="files"] .board .col,
    body[data-mtab="ask"] .board .col { height:calc(100dvh - 205px); min-height:380px; }
    /* v2.8.22 (2): the Upload card is TALLER -- the 205px offset
       left the Send Text button cut off by the column on
       Essef's phone (Nov 6 screenshot: the button half-hidden
       at the card's bottom edge, orange line drawn just above
       the pill tabs). The Send column alone gets a 164px
       offset (2.8.39 (5b): 170px -> 164px, buying the column
       6px of slack; 2.8.40 (3) removed the MB Save password
       row, so the slack is roomier still), so its
       bottom edge lands ~2px above the pill tabs and the whole
       stack (Send Text + card + footer) fits without scrolling
       at 390x844 and taller; shorter phones still scroll
       cleanly via fitSendTab. Notes / Files / Search keep the
       205px column exactly. */
    body[data-mtab="send"] .board .col[data-col="send"] { height:calc(100dvh - 164px); }
    #askbtn { display:none; }
    footer { display:none; }
    .col[data-col="files"] #openfolder, .col[data-col="files"] #changefolder { display:none; }
    .board .col.active { display:flex; }
    /* v2.8.24 (7): changing tabs SLIDES the new column in --
       very fast (.18s), direction from tab order (--tabdx).
       Mobile web only (this media query); the desktop
       three-column board is untouched. */
    .board .col.active { animation:tabslidein .18s ease-out; }
    .qrpop.open { max-width:100%; }
    .connectwrap { display:none; }
    .mqrmini { display:flex; align-items:center; flex:0 0 auto; }
    .mqrmini img { width:42px; height:42px; }
    .mqrrow { display:flex; gap:10px; align-items:center; }
    .mqrrow .maddrwrap { position:relative; display:flex; flex:1; min-width:0; width:0; }
    /* v2.8.18 (1): the previously-used-addresses dropdown lives
       INSIDE the address box, like the APK -- a chevron button
       inside the field, between the text and the copy button;
       the list floats below the field. The separate
       "Previously used addresses" card below the box is gone. */
    .maddrwrap .mddtoggle { position:absolute; right:38px; top:50%; transform:translateY(-50%); width:auto; background:none; border:none; color:var(--muted); font-size:14px; padding:6px; line-height:1; cursor:pointer; z-index:3; font-family:inherit; }
    .maddrwrap .mddlist { z-index:60; }
    .mqrrow .maddrwrap .mtext { flex:1; min-width:0; width:0; padding-right:68px; }
    /* v2.8.22 (6): the mobile copy button gets the theme text
       colour. It had NO colour rule, so it fell back to the
       browser's ButtonText (black, because the page declares
       no color-scheme) -- black on the dark address field in
       dark mode, contrast 1.08:1, effectively invisible. With
       color:var(--txt) it is light in dark mode and near-black
       (#0f172a) in light mode, i.e. its light-mode appearance
       is unchanged. */
    .mcopybtn { position:absolute; right:2px; top:50%; transform:translateY(-50%); background:none; border:none; font-size:17px; padding:8px 10px; cursor:pointer; color:var(--txt); }
    /* v2.8.17 (f/k): the mobile copy button is the classic copy
       icon (two overlapping rectangles), never the clipboard
       emoji -- size the inline SVG to the old emoji's size. */
    .mcopybtn svg { width:17px; height:17px; display:block; }
    /* v2.8.18 (1): the separate "Previously used addresses"
       card is gone -- the dropdown lives inside the address
       box now (see .maddrwrap .mddtoggle above). The old
       full-width toggle rules are deleted with it. */
    .mddlist { z-index:60; }
    /* v2.8.14 mobile Connect / Disconnect like the APK (Essef
       Nov 5, screenshot 1): the purple gradient Save is gone.
       Connect is solid violet #7C3AED with the APK's
       right-arrow icon (green while connected, muted grey
       while not -- the APK's paintSendConnectBtn rule);
       Disconnect is solid red #EF4444 with the APK's white
       </> icon. One row, equal widths, same as the APK's
       Send-tab pair. The address still saves on Connect,
       as on the APK. */
    .mpcbtnrow { display:flex; gap:12px; margin-top:12px; }
    .mpcbtn { flex:1 1 0; min-width:0; display:inline-flex; align-items:center; justify-content:center; gap:6px; padding:13px 8px; border:none; border-radius:13px; font-size:15px; font-weight:700; font-family:inherit; color:#ffffff; cursor:pointer; white-space:nowrap; }
    .mpcbtn svg { width:18px; height:18px; flex:none; }
    .mpc-connect { background:#7C3AED; }
    .mpc-connect svg { stroke:#9CA3AF; }
    .mpc-connect.connected svg { stroke:#22C55E; }
    .mpc-disconnect { background:#EF4444; }
    .mpc-disconnect svg { stroke:#ffffff; }
    /* v2.8.40 (1): the MB Disconnect is the same size as the D
       menu Change Folder button -- 40px tall, 14px font. An
       explicit height is used because the buttons' normal
       line-heights (19px at 14px, ~25px at 15px) can never add
       up to exactly 40px with integer padding. Its width stays
       the row's half-share (flex:1): a literal 208px would not
       fit beside Connect. Connect gets the same 40px height so
       the pair stays even. */
    #mpcdisconnect { height:40px; padding:10px 8px; font-size:14px; }
    #mpcconnect { height:40px; padding:7px 8px; }
    .msend .minicard { padding:10px 10px 11px; }
    .msend .minicard + .minicard { margin-top:8px; }
    .msend .mlabel { margin-bottom:6px; }
    .msend .mtext { padding:9px 10px; }
    .msend .mhint { font-size:12px; margin:6px 2px 0; }
    .msend .mbtn-primary, .msend .mbtn-secondary { padding:10px; margin-top:8px; }
    .msendfoot { text-align:center; color:var(--muted); font-size:11px; margin:6px 4px 0; white-space:nowrap; }
    /* v2.8.18 (2): the web Upload tab must NOT scroll -- the
       whole Send card fits inside its column, so the column
       body clips instead of scrolling. Scrolling is allowed
       again ONLY when the page says so: body.send-may-scroll
       (set by fitSendTab when a failed-file retry button is
       present, or while the Send Text box is focused and the
       keyboard is open). */
    body[data-mtab="send"] .col[data-col="send"] .colbody { overflow:hidden; }
    body.send-may-scroll[data-mtab="send"] .col[data-col="send"] .colbody { overflow-y:auto; }
    /* v2.8.20 (1): NO extra bottom clearance is added here on
       purpose. The colbody's own bottom edge already clears
       the pill tabs (at max scroll the last card sits ~80px
       above them), and any padding on .msend would count
       toward scrollHeight -- once the scroll class turned on
       (e.g. keyboard focus) the padding would keep it on
       forever, breaking the 390px no-scroll fit. The scroll
       itself is the fix; the clearance comes free. */
    /* v2.8.20 (1)+(7): the bigger Share Text box (+44px) would
       push the 390x844 stack 24px over the column, so the tab
       would scroll on Essef's own phone too. Recover ~36px of
       spacing on the mobile Send tab ONLY (desktop is
       untouched -- these selectors are .msend-scoped): card
       padding 14px -> 10px (24px), card gaps 8px -> 6px (4px),
       Upload buttons' top margin 8px -> 6px (4px), Connect
       buttons 11px -> 10px (2px), footer margin 6px -> 4px
       (2px). The 390x844 stack is then ~558px in a 570px
       column: it fits without scrolling, and smaller phones
       scroll via fitSendTab. */
    .board .col[data-col="send"] .msend .minicard { padding:9px 12px; }
    .board .col[data-col="send"] .msend .minicard + .minicard { margin-top:5px; }
    .board .col[data-col="send"] .msend .mbtn-primary, .board .col[data-col="send"] .msend .mbtn-secondary { margin-top:6px; }
    .board .col[data-col="send"] .msend .mpcbtn { padding:9px 8px; }
    .board .col[data-col="send"] .msendfoot { margin-top:2px; }
    /* v2.8.39 (5b): the MB Save password row (1) had added ~28px
       to the Set Up card, so the 390x844 stack lost its slack
       (605px of content in a 605px column). Recover ~15px of
       spacing on the mobile Send tab ONLY -- card padding,
       gaps, Connect buttons, footer margin, card labels -- so
       the stack fits with room again. Text sizes never change.
       2.8.40 (3) removed that row, so the slack is roomier
       still; the tighter spacing stays. */
    .board .col[data-col="send"] .msend .mlabel { margin-bottom:5px; }
    /* v2.8.18 (2): tighter Send-tab spacing so the card fits
       without scrolling (Connect/Disconnect a touch shorter).
       v2.8.19: the Send Text box is restored to its pre-2.8.18
       size (min-height 52px) -- the 2.8.18 shrink to 46px is
       reverted, nothing else about the box changes. */
    .mpcbtn { padding:11px 8px; }
    .mtext { width:100%; box-sizing:border-box; background:#090c15; border:1px solid var(--line);
             border-radius:10px; color:var(--txt); padding:12px; font-size:16px; font-family:inherit; }
    .mtext:focus { outline:none; border-color:var(--acc); }
    .mhint { color:var(--muted); font-size:12.5px; margin:10px 2px 0; line-height:1.5; }
    .msavedbtn { display:inline-flex; align-items:center; justify-content:center; gap:6px; border-radius:10px; padding:8px 14px;
             font-size:13px; font-weight:800; font-family:inherit; cursor:pointer; color:#ffffff;
             background:#277ff0; border:none; }
    .msavedbtn:active { filter:brightness(1.15); }
    /* v2.8.14 bottom tabs redesigned like the APK (Essef Nov 5):
       PILL container -- floating rounded pill, centred, instead
       of the full-width bottom bar -- with COLOURED icons per
       tab, same as the APK: Upload green, Notes amber, Files
       blue, Search violet sparkle (soft/muted tones). The icons
       are inline SVGs now (emoji could not be coloured). */
    .mtabs { display:flex; position:fixed; left:50%; transform:translateX(-50%); bottom:12px; z-index:60; gap:6px;
             width:min(480px, calc(100vw - 24px)); background:rgba(9,12,21,.97); border:1px solid var(--line); border-radius:999px;
             padding:8px 10px calc(8px + env(safe-area-inset-bottom)); box-shadow:0 8px 30px rgba(0,0,0,.45); }
    .mtab { flex:1; display:flex; flex-direction:column; align-items:center; gap:3px; position:relative;
            background:none; border:none; color:var(--muted); font-size:11px; font-family:inherit;
            padding:8px 4px; border-radius:999px; cursor:pointer; }
    .mtab .mi { font-size:20px; line-height:1; }
    .mtab .mi svg { width:20px; height:20px; display:block; }
    .mtab.sel { color:var(--txt); background:rgba(34,211,238,.1); }
    .mcount { position:absolute; top:2px; right:calc(50% - 28px); font-size:10px; background:var(--acc);
              color:#0a0f1e; font-weight:700; border-radius:10px; padding:1px 6px; }
    .mcount:empty { display:none; }
    .nbtnrow { margin:0 0 10px; }
    .nbtnrow .btn { padding:12px 8px; font-size:14px; border-radius:12px; }
    .col[data-col="send"] .colbody > .minicard { display:none; }
    .col[data-col="send"] .msend { display:block; }
    /* v2.8.20 (7): the Share Text box is BIGGER (min-height
       110px, like the desktop #snippet) and has ITS OWN small
       scroller -- max-height caps it, overflow-y:auto scrolls
       long text inside the box, and overscroll-behavior:contain
       stops that scroll chaining out to the page, so typing
       scrolls the box, never the column. The 2.8.19 52px size
       is superseded. */
    #msendtext { width:100%; box-sizing:border-box; min-height:110px; max-height:190px; overflow-y:auto; overscroll-behavior:contain; background:#090c15;
             border:1px solid var(--line); border-radius:12px; color:var(--txt); padding:12px;
             font-size:16px; font-family:inherit; resize:vertical; }
    #msendtext:focus { outline:none; border-color:var(--acc); }
    #msendtext::placeholder { color:var(--muted); }
    .nact { margin-top:10px; }
    .nact button { padding:8px 4px; }
    .nact button svg { width:18px; height:18px; }
    .toast { bottom:calc(112px + env(safe-area-inset-bottom)); }
  }
  /* v2.8.39 (5b): SHORT phones (<=760px tall) -- the three
     Upload cards must still fit without scrolling, so the
     stack compresses: the Share Text box drops to ~3 rows,
     the footer slogan and the Set Up hint hide, card
     padding/gaps tighten. Text sizes never change; only
     spacing and the box height do. At 700px tall the stack
     needs ~129px back; this recovers ~134px (the column
     itself already has 6px more room from the 164px offset
     above). */
  @media (max-width:720px) and (max-height:760px){
    .board .col[data-col="send"] .msend .minicard { padding:7px 12px; }
    .board .col[data-col="send"] .msend .minicard + .minicard { margin-top:4px; }
    .board .col[data-col="send"] .msendfoot { display:none; }
    .msend #msendtext { height:78px; min-height:0; }
    .msend .mhint { display:none; }
    .board .col[data-col="send"] .msend .mpcbtn { padding:8px; }
    .board .col[data-col="send"] .msend .mlabel { margin-bottom:4px; }
    .board .col[data-col="send"] .msend .mbtn-primary, .board .col[data-col="send"] .msend .mbtn-secondary { padding:8px 10px; }
  }
  .col[data-col="ask"] { display:none; }
  .col[data-col="ask"] .colbody { overflow:hidden; }
  .asklist { display:flex; flex-direction:column; gap:6px; flex:1; min-height:0; overflow-y:auto; padding:4px 2px; }
  .amsg { max-width:88%; padding:10px 13px; border-radius:14px; font-size:14px; line-height:1.5; margin:2px 0; overflow-wrap:break-word; }
  .amsg.bot { background:#151b31; border:1px solid var(--line); align-self:flex-start; border-bottom-left-radius:4px;
    user-select:text; -webkit-user-select:text; cursor:text; }
  .amsg.user { background:linear-gradient(135deg,#1d4ed8,#7c3aed); align-self:flex-end; border-bottom-right-radius:4px; }
  .amsg code { display:block; background:#090c15; border:1px solid var(--line); border-radius:8px; padding:8px 10px; margin:8px 0; font-size:12px; white-space:pre-wrap; word-break:break-all; font-family:ui-monospace,monospace; }
  .ares { display:flex; align-items:center; gap:10px; background:#090c15; border:1px solid var(--line); border-radius:12px; padding:10px 12px; }
  .afic { font-size:22px; flex:none; }
  .afic svg { display:block; width:24px; height:24px; }
  .athumb { width:46px; height:46px; object-fit:cover; border-radius:9px; flex:none; border:1px solid var(--line); }
  .afname { flex:1; min-width:0; font-weight:600; font-size:13.5px; word-break:break-all; }
  .afsize { color:var(--muted); font-size:12px; flex:none; }
  .abtn { flex:none; border:none; border-radius:9px; padding:8px 13px; font-size:13px; font-weight:700; cursor:pointer; color:#0a0f1e; background:linear-gradient(135deg,#22d3ee,#818cf8); font-family:inherit; }
  .abtn2 { padding:8px 10px; }
  .abtn:disabled { opacity:.45; }
  .abtn:active { filter:brightness(1.15); }
  .atyping { display:inline-flex; gap:4px; padding:6px 2px; }
  .atyping i { width:7px; height:7px; border-radius:50%; background:var(--muted); animation:ablink 1.2s infinite; }
  .atyping i:nth-child(2) { animation-delay:.2s; }
  .atyping i:nth-child(3) { animation-delay:.4s; }
  @keyframes ablink { 0%,60%,100% { opacity:.25; } 30% { opacity:1; } }
  .askinput { display:flex; gap:8px; padding-top:10px; flex:none; }
  .askinput input { flex:1; min-width:0; background:#090c15; border:1px solid var(--line); border-radius:12px; color:var(--txt); padding:11px 12px; font-size:15px; font-family:inherit; }
  .askinput input:focus { outline:none; border-color:var(--acc); }
  .askinput button { flex:none; width:46px; border-radius:12px; border:none; cursor:pointer; font-size:17px; color:#0a0f1e; background:linear-gradient(135deg,#22d3ee,#818cf8); }
  .askinput button:disabled { opacity:.4; }
  .askinput button:active { filter:brightness(1.15); }
  /* v2.7.99 Search window: it DROPS DOWN from the magnifying
     glass icon (fixed, just under the top bar at the right,
     where the icon sits), ANIMATED on click -- slide + fade
     down from the icon, not a tab jump and not a side panel
     slide-in. Closed state keeps display:block with
     visibility/opacity/transform so the transition actually
     runs. It carries a VISIBLE full border (not just a left
     edge), theme-adapted, and sizes to a capped height with
     its list scrolling inside. */
  .askpop { visibility:hidden; position:fixed; top:76px; right:18px; bottom:auto; width:410px; max-width:94vw; max-height:72vh; z-index:90; background:rgba(9,12,21,.98); border:1px solid var(--line); border-radius:18px; padding:18px; box-sizing:border-box; box-shadow:0 16px 40px rgba(0,0,0,.45); opacity:0; transform:translateY(-14px); transform-origin:top right; pointer-events:none; transition:opacity .25s ease, transform .25s ease, visibility 0s linear .25s; display:flex; flex-direction:column; }
  .askpop.open { visibility:visible; opacity:1; transform:translateY(0); pointer-events:auto; transition:opacity .25s ease, transform .25s ease; }
  .askbox { display:flex; flex-direction:column; min-height:0; flex:1; }
  .askhead { display:flex; align-items:center; justify-content:space-between; margin-bottom:12px; font-weight:700; font-size:15px; }
  /* v2.7.97: toast stacking -- the ONLY global toast/message
     container (#toast, class .toast, shown by toast()). It was
     z-index:120, BELOW the Set Up Your Addresses dialog
     backdrop (.lockwrap, z-index:300) and BELOW the Set
     Password popup (.lockpwpop, z-index:130), so every toast
     fired from inside those dialogs rendered BEHIND them and
     could not be seen. It is now 5000: above .lockwrap (300),
     .lockpwpop (130), .qrpop (300), .mdlg (110), .viewer
     (100), .aipop (1000), .aimodalwrap (1001) and #hovertip
     (2000). pointer-events:none is unchanged, so the raised
     toast can never block clicks. The mobile media query only
     moves its bottom offset and sets no z-index, so this one
     rule covers mobile too. No other global toast/message
     container exists: .lkerr / .lockerr / .lockpwerr are
     inline errors INSIDE their dialogs, and .gloginmsg /
     .gloginerr are inline on the guest login page. */
  .toast { position:fixed; bottom:26px; left:50%; transform:translateX(-50%) translateY(20px); background:var(--card2);
           border:1px solid var(--acc); color:var(--txt); padding:11px 20px; border-radius:12px; font-size:14px;
           opacity:0; transition:.25s; pointer-events:none; z-index:5000; max-width:92vw; text-align:center; }
  .toast.show { opacity:1; transform:translateX(-50%) translateY(0); }
  html.light .toast { background:#ffffff; border-color:var(--acc); box-shadow:0 10px 30px rgba(15,23,42,.20); }

  /* ---- light mode: same page, re-tuned palette (no blended text) ---- */
  html.light { --bg:#eef2f7; --card:#ffffff; --card2:#e7edf4; --line:#c3cfde; --txt:#0f172a;
               --muted:#4e6076; --acc:#0284c7; --acc2:#7c3aed; --good:#059669; --bad:#e11d48; }
  html.light body { background:radial-gradient(1100px 500px at 50% -10%, #d7e7fa 0%, var(--bg) 55%) fixed, var(--bg); }
  html.light .col { background:rgba(255,255,255,.55); }
  html.light .amsg.bot { background:var(--card2); }
  html.light .aimodal { background:#ffffff; box-shadow:0 24px 70px rgba(15,23,42,.28), 0 0 0 1px var(--line); }
  html.light .aimodal .abody { color:var(--txt); }
  html.light .aimodal header button { color:var(--muted); }
  html.light .aipop { background:rgba(255,255,255,.98); border-color:var(--line); box-shadow:0 18px 50px rgba(15,23,42,.22); }
  html.light .aipop button { color:var(--txt); }
  html.light .delbar { background:rgba(255,255,255,.97); box-shadow:0 14px 44px rgba(15,23,42,.22), 0 0 0 1px var(--line); }
  html.light .delbar .canceldel, html.light .delbar .selall,
  html.light .svbar .canceldel, html.light .svbar .selall { background:var(--card2); }
  html.light .askpop { background:rgba(255,255,255,.98); }
  html.light .mtabs { background:rgba(255,255,255,.97); box-shadow:0 8px 30px rgba(15,23,42,.18); }
  html.light #ctxmenu { background:var(--card); box-shadow:0 18px 50px rgba(15,23,42,.22); }
  html.light #ctxmenu .ctxitem:hover { background:var(--card2); }
  /* v2.7.83: light mode previously kept the dark-mode text colours on
     a white menu — enabled items (near-white #eef1f8) looked greyed
     out while disabled items (dark grey #5a6378) looked selectable,
     exactly inverted. Enabled items now use the light theme text
     colour; disabled items use a pale grey that reads as unavailable
     on white. Dark mode is untouched. */
  html.light #ctxmenu .ctxitem { color:var(--txt); }
  html.light #ctxmenu .ctxitem.off { color:#94a3b8; }
  html.light #ctxmenu .ctxitem.off:hover { background:none; }
  html.light #pvctx { background:var(--card); box-shadow:0 18px 50px rgba(15,23,42,.22); }
  html.light #pvctx .ctxitem { color:var(--txt); }
  html.light #pvctx .ctxitem:hover { background:var(--card2); }
  html.light #msendtext, html.light #snippet, html.light .editbox { background:#ffffff; }
  html.light #vcontent pre, html.light .amsg code { background:var(--card2); }
  html.light .vclose { background:var(--card2); }
  html.light .tbadge { background:var(--card2); }
  html.light .tbadge.tlabel { color:var(--acc); }
  html.light .fact button { background:#ffffff; }
  html.light .mbtn-secondary { background:var(--card2); }
  html.light .colbody::-webkit-scrollbar-thumb, html.light .lkbox::-webkit-scrollbar-thumb { background:#b6c2d4; }
  .aipop button .em svg { display:block; }
  html.light #snippet, html.light .snipcard, html.light .minicard,
  html.light .thumb, html.light .thwrap .fic, html.light .editbox, html.light .mtext,
  html.light .ares, html.light .askinput input, html.light .mbox textarea,
  html.light #vcontent pre { background:#ffffff; }
  html.light .count { background:var(--card2); }
  html.light .mbox .btn { background:#ffffff; }

  /* ---- v2.7.77: profiles, lock screen, rename, stars, theme switch ---- */
  .lockwrap { position:fixed; inset:0; background:rgba(3,5,10,.74); backdrop-filter:blur(3px);
    display:none; align-items:center; justify-content:center; z-index:300; padding:16px; }
  .lockwrap.open { display:flex; }
  /* v2.8.34 (3): animated pop up / pop out -- Set Up Your
     Addresses (#lkwrap .lockbox), the QR popup (.qrpop .qr)
     and the Add New text dialog (.mdlg .mbox). Same sizes,
     same behaviour; only the CARD animates (scale .96 <-> 1
     + a small rise + fade). Open: the animation runs when
     the dialog becomes displayed (display:none -> flex
     restarts it). Close: JS adds .closing, the pop-out
     plays, then the dialog hides after 160ms; a re-open
     cancels the pending hide. The .closing rules sit after
     the pop-in rules so they win the equal-specificity
     tie while both classes are present. */
  @keyframes dlgPopIn { from { opacity:0; transform:scale(.96) translateY(6px); } to { opacity:1; transform:scale(1) translateY(0); } }
  @keyframes dlgPopOut { from { opacity:1; transform:scale(1) translateY(0); } to { opacity:0; transform:scale(.96) translateY(6px); } }
  #lkwrap .lockbox, .qrpop.open, .mdlg.open .mbox { animation:dlgPopIn .18s ease-out; }
  #lkwrap.closing .lockbox, .qrpop.closing, .mdlg.closing .mbox { animation:dlgPopOut .16s ease-in forwards; }
  #lkwrap.closing, .qrpop.closing, .mdlg.closing { pointer-events:none; }
  .lockbox { background:var(--card); border:1px solid var(--line); border-radius:18px;
    padding:26px 24px; width:min(350px,94vw); text-align:center; max-height:92vh; overflow:auto; }
  .lockbox h3 { margin:0 0 6px; font-size:19px; }
  .lockic { color:var(--acc); margin-bottom:8px; }
  .locksub { color:var(--muted); font-size:13.5px; margin:0 0 14px; }
  .lockbox input { width:100%; box-sizing:border-box; background:var(--card2); color:var(--txt);
    border:1px solid var(--line); border-radius:10px; padding:10px 12px; font-size:14px; margin:0 0 10px; }
  .lockbox input:focus { outline:none; border-color:var(--acc); }
  .lockerr { color:#ef4444; font-size:13px; min-height:18px; margin:2px 0 6px; }
  .lockgo { width:100%; padding:11px; font-size:14px; }
  .pmbox { width:min(520px,96vw); text-align:left; }
  .pmhead { display:flex; align-items:center; justify-content:space-between; margin-bottom:8px; }
  .pmsec { font-size:12px; font-weight:800; letter-spacing:.6px; text-transform:uppercase;
    color:var(--muted); margin:18px 0 8px; }
  .pmrow { display:flex; align-items:center; gap:8px; padding:9px 10px; border:1px solid var(--line);
    border-radius:12px; margin-bottom:8px; }
  .pmrow .pmname { font-weight:700; flex:1 1 auto; min-width:0; overflow:hidden; text-overflow:ellipsis; }
  .pmrow .pmmeta { color:var(--muted); font-size:11.5px; display:block; font-weight:400;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:230px; }
  .pmrow .btn { padding:6px 10px; font-size:12px; }
  .pmcur { color:var(--acc); font-size:11px; font-weight:800; letter-spacing:.4px; }
  .pmedit { border:1px solid var(--line); border-radius:12px; padding:10px; margin:-2px 0 10px; display:none; }
  .pmedit.open { display:block; }
  .pmrow2 { display:flex; gap:8px; } .pmrow2 input { flex:1 1 auto; min-width:0; }
  .pmrow2 .btn { flex:none; }
  .pmhint { color:var(--muted); font-size:12.5px; margin:6px 0 0; min-height:16px; }
  .themewrap { display:flex; justify-content:center; padding:0 0 16px; }
  .themesw { position:relative; width:78px; height:34px; border-radius:999px; cursor:pointer;
    background:#090c15; border:1px solid var(--line); padding:0; }
  html.light .themesw { background:#ffffff; }
  .themesw .tsic { position:absolute; top:50%; transform:translateY(-50%); width:16px; height:16px; }
  .themesw .tsmoon { left:10px; color:#fbbf24; }
  .themesw .tssun { right:10px; color:#f59e0b; }
  .tsknob { position:absolute; top:3px; left:3px; width:26px; height:26px; border-radius:50%;
    border:2px solid var(--acc); background:rgba(56,189,248,.18); transition:left .28s ease; }
  html.light .tsknob { left:45px; }
  @keyframes popin { 0% { transform:scale(.3); } 60% { transform:scale(1.3); } 100% { transform:scale(1); } }
  .pop { animation:popin .28s ease; }
  .dying { overflow:hidden; transition:height .3s ease, opacity .26s ease, margin .3s ease, padding .3s ease; }
  .sniphead .wic { color:var(--nac,var(--acc)); display:inline-flex; }
  .sniphead .wic svg { width:15px; height:15px; }
  .rnedit { background:none; border:none; cursor:pointer; padding:2px; color:var(--nac,var(--acc));
    display:inline-flex; flex:none; }
  .rnedit svg { width:13px; height:13px; }
  .starbtn { background:none; border:none; cursor:pointer; padding:3px; margin-left:auto; flex:none;
    color:var(--muted); display:inline-flex; }
  .starbtn svg { width:16px; height:16px; }
  .starbtn.starred { color:#f59e0b; }
  .starbtn.starred svg { fill:#fbbf24; }
  .renamein { background:var(--card2); border:1px solid var(--acc); border-radius:7px; color:var(--txt);
    font:inherit; font-weight:700; padding:1px 7px; width:170px; max-width:46vw; }
  .rnbtn { border:none; border-radius:50%; width:20px; height:20px; flex:none; cursor:pointer;
    display:inline-flex; align-items:center; justify-content:center; padding:0; }
  .rnbtn svg { width:12px; height:12px; }
  .rnbtn.ok { background:#277ff0; color:#fff; }
  .rnbtn.xx { background:#374151; color:#e5e7eb; font-size:11px; }
  html.light .rnbtn.xx { background:#e2e8f0; color:#33475e; }
  #starfilter.on { border-color:#f59e0b; color:#f59e0b; }
  #starfilter.on svg { fill:#fbbf24; }
  html.light .connectbar { background:#ffffff; }
  html.light .btn:not(.primary):not(.dangergrad):not(.openf):not(.changef):not(.pvdl):not(.addrremsave) { background:#ffffff; }
  html.light .tbadge { background:#dbe7f3; color:#33475e; }
  html.light .tbadge.tlabel { color:#0369a1; }
  html.light .thwrap .fic { background:#eef2f7; }
  .pmchk { font-size:12.5px; color:var(--muted); display:flex; gap:6px; align-items:center; margin:0 0 10px; }
  .pmchk input { width:auto; margin:0; }

  /* ---- v2.7.78 fixes: note header room, rename row, buttons, toggle ---- */
  .sniphead { flex-wrap:nowrap; }
  .sniphead .who { flex:1 1 auto; min-width:0; white-space:nowrap; overflow:hidden;
    text-overflow:ellipsis; cursor:text; }
  .sniphead .ndate { flex:none; white-space:nowrap; font-size:11.5px; }
  .sniphead .who.editing { display:flex; align-items:center; gap:6px; overflow:visible; }
  .renamein { flex:1 1 auto; min-width:0; width:auto; }
  .rnbtn { width:22px; height:22px; }
  .nbtnrow { align-items:stretch; }
  .nbtnrow .btn { display:inline-flex; align-items:center; justify-content:center;
    padding:10px 4px; font-size:13px; box-sizing:border-box; }
  #maddnote { font-weight:700; }
  #starfilter { background:linear-gradient(135deg,#fbbf24,#f59e0b); border:none;
    color:#231303; font-weight:700; }
  #starfilter svg { color:#231303; }
  #starfilter.on { box-shadow:inset 0 0 0 2px rgba(35,19,3,.55); filter:brightness(1.06); color:#231303; }
  #starfilter.on svg { fill:#231303; }
  @keyframes cardin { from { opacity:0; transform:translateY(7px) scale(.98); }
    to { opacity:1; transform:none; } }
  #snips.flip .snipcard { animation:cardin .3s ease both; }
  #snips.flip .snipcard:nth-child(2) { animation-delay:.03s; }
  #snips.flip .snipcard:nth-child(3) { animation-delay:.06s; }
  #snips.flip .snipcard:nth-child(4) { animation-delay:.09s; }
  #snips.flip .snipcard:nth-child(5) { animation-delay:.12s; }
  #snips.flip .snipcard:nth-child(6) { animation-delay:.15s; }
  .themewrap { margin-top:18px; padding:0 0 30px; }

  /* ---- v2.7.79: sidebar, link window, lock screen ---- */
  #menubtn { width:36px; height:36px; flex:none; border:none; border-radius:11px; cursor:pointer;
    background:linear-gradient(135deg,#7C3AED,#0EA5E9); display:flex; flex-direction:column;
    align-items:center; justify-content:center; gap:4px; box-shadow:0 4px 12px rgba(124,58,237,.35);
    transition:transform .2s, filter .2s; }
  #menubtn:hover { filter:brightness(1.1); }
  #menubtn span { display:block; width:16px; height:2.2px; border-radius:2px; background:#fff;
    transition:transform .3s cubic-bezier(.6,0,.2,1), opacity .2s; }
  #menubtn.open span:nth-child(1) { transform:translateY(6.2px) rotate(45deg); }
  #menubtn.open span:nth-child(2) { opacity:0; }
  #menubtn.open span:nth-child(3) { transform:translateY(-6.2px) rotate(-45deg); }
  #scrim { position:fixed; inset:0; background:rgba(3,5,10,.5); opacity:0; pointer-events:none;
    transition:opacity .3s; z-index:79; }
  #scrim.on { opacity:1; pointer-events:auto; }
  #sidebar { position:fixed; top:0; left:0; bottom:0; width:292px; max-width:86vw; z-index:80;
    background:var(--card); border-right:1px solid var(--line); padding:20px 18px;
    transform:translateX(-106%); transition:transform .34s cubic-bezier(.6,0,.2,1);
    overflow-y:auto; box-sizing:border-box; }
  #sidebar.open { transform:none; box-shadow:24px 0 60px rgba(0,0,0,.35); }
  .sbhead { display:flex; align-items:baseline; gap:8px; margin-bottom:6px; }
  .sbtitle { font-size:21px; font-weight:800;
    background:linear-gradient(135deg,#a78bfa,#38bdf8); -webkit-background-clip:text;
    background-clip:text; color:transparent; }
  .sbver { font-size:11px; color:var(--muted); }
  .sbsec { font-size:11px; font-weight:700; letter-spacing:.09em; text-transform:uppercase;
    color:var(--muted); margin:20px 0 8px; }
  .sblinkrow { display:flex; align-items:center; gap:8px; background:var(--card2);
    border:1px solid var(--line); border-radius:12px; padding:9px 12px; }
  #sblink { flex:1 1 auto; min-width:0; font-size:13px; font-weight:600; white-space:nowrap;
    overflow:hidden; text-overflow:ellipsis; }
  .sblockbtn { flex:none; width:32px; height:32px; border-radius:9px; border:1px solid var(--line);
    background:transparent; color:var(--muted); cursor:pointer; display:flex; align-items:center;
    justify-content:center; }
  .sblockbtn.locked { color:#f59e0b; border-color:#f59e0b; background:rgba(245,158,11,.12); }
  #linklock { color:var(--muted); display:inline-flex; align-items:center; }
  #linklock.locked { color:#f59e0b; }
  .sbbtn { display:block; width:100%; text-align:left; margin-top:8px; padding:11px 12px;
    border-radius:12px; border:1px solid var(--line); background:var(--card2); color:var(--txt);
    font-size:13.5px; font-weight:600; cursor:pointer; }
  .sbbtn:hover { filter:brightness(1.12); }
  /* v2.8.39 (1): the menu Disconnect (PC web only, hidden on the
     desktop app -- see paintSidebar) reads as a disconnect at a
     glance: solid red like the mobile Disconnect button. */
  #sbdisconnect { background:#ef4444; color:#ffffff; border:none; }
  .sbrow { display:flex; align-items:center; justify-content:space-between; padding:7px 2px;
    font-size:13.5px; font-weight:600; }
  .sbsw { width:42px; height:24px; border-radius:999px; background:var(--line); position:relative;
    cursor:pointer; flex:none; transition:background .2s; }
  .sbsw .sbknob { position:absolute; top:3px; left:3px; width:18px; height:18px; border-radius:50%;
    background:#fff; transition:left .2s; box-shadow:0 1px 4px rgba(0,0,0,.35); }
  .sbsw.on { background:linear-gradient(135deg,#22d3ee,#0ea5e9); }
  .sbsw.on .sbknob { left:21px; }
  #sidebar .themesw { transform:scale(.92); }
  .lkbox { text-align:left; width:380px; }
  /* v2.7.96 SPLIT SCREEN: the host Set Up window is BIGGER
     (760px) and laid out as two EQUAL columns side by side,
     so it does not need to be scrolled down at a normal window
     size. v2.7.99 layout: a shared top line (New Address +
     Open/Change Folder), then Current Address + Folder, then
     Password + Save (Save in the Password column, left-aligned
     with the password field), then the Permissions grid
     spanning both columns at the bottom (it replaces the old
     Devices section -- devices now live in the Send-card
     dropdown). The guest connect screen stays single-column
     (400px): its right column would be empty (no folder
     controls). */
  .lkbox { width:min(760px,96vw); }
  .lkbox.guestcard { width:400px; }
  .lksplit { display:grid; grid-template-columns:1fr 1fr; gap:8px 20px; align-items:stretch; }
  .lkbox.guestcard .lksplit { display:block; }
  .lksplit .lkcol { display:flex; flex-direction:column; min-width:0; }
  .lksplit .lkcol #lkset { margin-top:auto; }
  .lksplit .lkcol #lkunlockbtn { margin-top:10px; }
  /* v2.7.86 Your-Link section: every field and button the same width,
     same padding, same rhythm -- no overlap, no clutter. The password
     icon buttons stretch to exactly the password field's height
     (align-items:stretch on the row, height:auto on the buttons), so
     they are never bigger than the field. Current-link and Folder
     rows use the same padding/font as the inputs, so all four fields
     measure the same height. Open/Change folder sit side by side
     directly under the Folder field in .lkfolderrow, reusing the
     Shared-Files-tab .openf/.changef colours, with the single Save
     button directly below them. */
  .lkbox input[type="text"], .lkbox input[type="password"] { width:100%; box-sizing:border-box; padding:13px 12px; font-size:15px; }
  .lkbox .btn { width:100%; box-sizing:border-box; margin-top:10px; padding:12px; min-height:46px; font-size:14px; }
  .lkbox .btn.primary { margin-top:16px; }
  /* v2.7.87 solid-colour buttons (classic futuristic, solid fills
     only in this dialog): the shared .btn.primary / .openf /
     .changef classes use blended fills, so the dialog overrides
     them with solid colours instead of inheriting a blended fill
     through the class.
     Palette: cyan #22d3ee primary Save (dark text #052e33),
     teal #0ea5e9 Open folder (dark text), violet #7c3aed Change
     folder (white text), amber #f59e0b lock accent. */
  .lkbox .btn.primary { background:#277ff0; border:none; color:#ffffff; font-weight:800; }
  .lkbox .btn.primary:hover { filter:brightness(1.12); border:none; }
  .lkbox .btn.openf { background:#0ea5e9; border:none; color:#052e33; font-weight:700; }
  .lkbox .btn.openf:hover { filter:brightness(1.12); border:none; }
  .lkbox .btn.changef { background:#6D28D9; border:none; color:#ffffff; font-weight:700; }
  .lkbox .btn.changef:hover { filter:brightness(1.12); border:none; }
  .lkbox .btn:not(.primary):not(.openf):not(.changef) { background:#10182b; }
  .lkpwrow { display:flex; gap:8px; align-items:stretch; }
  /* v2.7.99: the eye + delete icons beside the Password field
     are EXACTLY the field's height (the field is a fixed 48px
     .lkfield): an explicit 48px on the buttons, so stretch
     cannot render them a touch taller than the field, and
     both sit on the same 48px row, vertically aligned. */
  .lkpwrow .lkiconbtn { height:48px; }
  .lkpwrow input { flex:1 1 auto; min-width:0; }
  .lkiconbtn { flex:none; width:48px; height:auto; min-height:0; border-radius:11px; border:1px solid var(--line); background:var(--card2); color:var(--txt); cursor:pointer; display:flex; align-items:center; justify-content:center; }
  .lkiconbtn svg { width:19px; height:19px; }
  .lkiconbtn:hover { border-color:var(--acc); }
  .lkiconbtn.danger:hover { border-color:var(--bad); color:var(--bad); }
  .lkerr { color:var(--bad); font-size:13px; margin-top:4px; min-height:18px; }
  .lksemnote { color:var(--muted); font-size:12px; margin-top:7px; }
  .lkopenwarn { display:none; border:1px solid #f59e0b; color:#fbbf24; background:rgba(245,158,11,.10); border-radius:11px; padding:10px 12px; font-size:13px; margin-top:10px; }
  /* v2.7.99: the open-address notice is CENTRED with a SMALL
     tight border only around the text -- display:table
     shrink-wraps it to its text width and auto margins centre
     it, instead of the old wide flat full-width bar. */
  .lkopenwarn.show { display:table; margin-left:auto; margin-right:auto; }
  .lkfolderrow { display:flex; gap:8px; margin-top:10px; }
  .lkfolderrow .btn { flex:1 1 0; min-width:0; margin-top:0; }
  /* v2.7.99 Set Up top line: New Address, Open Folder and
     Change Folder share ONE line (repositioned only -- the
     field keeps its 48px .lkfield height, the buttons keep
     their padding/font/min-height; in the shared row their
     width follows their content instead of splitting a
     column). The label sits inline at the row's left. */
  .lktopline { display:flex; gap:8px; align-items:center; margin-top:4px; }
  .lktopline .lklabel { margin:0; flex:none; }
  .lktopline .lkeditrow { flex:1 1 auto; min-width:0; }
  .lktopline .lkfolderrow { margin-top:0; flex:none; }
  .lktopline .lkfolderrow .btn { flex:none; width:auto; }
  /* v2.7.99 Save alignment: Save sits in the Password column
     (left column of the second split), left-aligned with the
     password field's left edge -- margin-left:0 instead of
     the centred auto margins -- size unchanged (same
     min-width/padding), still pushed to the column foot. */
  .lksplit .lkcol #lkset { margin-left:0; }
  /* v2.7.99 Permissions (replaces the Devices section): a
     compact grid, 3 per row, so the window does not extend
     vertically -- no vertical list. Each checkbox is a
     classic-futuristic animated box with a GREEN tick when
     checked (border-drawn tick scaling in with a spring). */
  .lkperms { margin-top:14px; border-top:1px solid var(--line); padding-top:10px; }
  .lkpermgrid { display:grid; grid-template-columns:repeat(3, 1fr); gap:10px 14px; margin-top:2px; }
  .permchk { display:flex; align-items:center; gap:8px; cursor:pointer; font-size:13.5px; color:var(--txt); }
  .permchk input { position:absolute; opacity:0; pointer-events:none; width:auto; /* v2.8.21 (B): the broad .lockbox input width:100% made these invisible checkboxes ~956px wide, sticking past the viewport's right edge (clipped today only by #lkwrap overflow:hidden). Intrinsic width now; the inputs are opacity:0, so nothing visible changes. */ }
  .permbox { flex:none; width:20px; height:20px; border:1.5px solid var(--line); border-radius:6px; background:var(--card2); position:relative; transition:background .18s ease, border-color .18s ease, transform .18s ease; }
  .permchk input:checked + .permbox { background:#22c55e; border-color:#22c55e; }
  .permbox::after { content:""; position:absolute; left:6px; top:2px; width:5px; height:10px; border:solid #ffffff; border-width:0 2.5px 2.5px 0; transform:rotate(45deg) scale(0); transition:transform .18s cubic-bezier(.34,1.56,.64,1); }
  .permchk input:checked + .permbox::after { transform:rotate(45deg) scale(1); }
  .permchk input:disabled + .permbox { opacity:.45; }
  .permchk.disabled { opacity:.55; cursor:default; }
  .lkpermnote { color:var(--muted); font-size:12px; margin-top:8px; }
  /* v2.8.0 Set Up redesign (Essef's HTML + screenshot, wired to
     the real functions -- no alert placeholders): host dialog
     only (.guestcard keeps its own 400px card). Stacked, not
     split: Current+Folder grid, then New Address + folder
     buttons grid, then Password, then the Permissions box,
     then a CENTRED Save. All fields share one height (56px),
     the password eye/delete icons sit OUTSIDE the password
     box at exactly that height, and the dialog carries the
     screenshot's blue border and rounded corners. Exactly six
     permission checkboxes -- no AI checkbox. The info icon
     beside Permissions carries the per-address tooltip. */
  .lkbox:not(.guestcard) { width:min(960px,96vw); padding:32px 36px 24px; border:2px solid #277ff0; border-radius:27px; }
  .lkbox:not(.guestcard) h3 { text-align:center; font-size:26px; margin-bottom:16px; }
  .lkbox:not(.guestcard) .lkfield, .lkbox:not(.guestcard) .lkview { height:56px; }
  .lkbox:not(.guestcard) .lkview { display:flex; align-items:center; }
  .lkbox:not(.guestcard) .lktopline { display:grid; grid-template-columns:1fr 1fr; gap:20px; align-items:end; margin-top:16px; }
  .lkbox:not(.guestcard) .lktopline .lklabel { margin:0 0 8px; }
  .lkbox:not(.guestcard) .lkfolderrow { display:flex; gap:14px; margin-top:0; }
  .lkbox:not(.guestcard) .lkfolderrow .btn { flex:1 1 0; height:56px; min-height:56px; margin-top:0; }
  .lkbox:not(.guestcard) .lkpwsection { margin-top:16px; }
  .lkbox:not(.guestcard) .lkpwrow .lkiconbtn { height:56px; width:56px; }
  .lkbox:not(.guestcard) .lkperms { margin-top:20px; border:1.5px solid var(--line); border-radius:18px; padding:18px 22px; }
  .lkbox:not(.guestcard) .lkpermgrid { gap:14px 22px; }
  .lkbox:not(.guestcard) .permchk { font-size:15px; }
  .lkbox:not(.guestcard) .permbox { width:24px; height:24px; }
  .lkperminfo { display:inline-flex; align-items:center; justify-content:center; width:22px; height:22px; border-radius:50%; border:1.5px solid #38bdf8; background:transparent; color:#38bdf8; font-size:14px; font-weight:700; cursor:pointer; margin-left:6px; vertical-align:middle; }
  .lksavewrap { display:flex; flex-direction:column; align-items:center; gap:10px; margin-top:20px; }
  .lksavewrap .btn.primary { width:165px; min-height:56px; margin-top:0; font-size:17px; }
  .lksavewrap .btn:not(.primary) { width:280px; }
  /* v2.8.2 Set Up redesign (Essef's ChatGPT HTML, wired to
     the real functions -- no alert placeholders): the host
     dialog takes the HTML's exact sizes -- 1200px max-width,
     35/40/25px padding, 2px #277ff0 border, 27px radius,
     30px centred title, 65px fields, 30px grids, 65px
     folder buttons, 80x65px password icon buttons OUTSIDE
     the 65px password box, 34px permission boxes, 165x58
     cyan Save, 48x48 red close X, fit-content amber notice.
     Scoped :not(.guestcard) so the guest connect card is
     untouched. Exactly six checkboxes -- no AI checkbox --
     and the Permissions info icon already present is kept. */
  .lkbox:not(.guestcard) { width:min(1200px,96vw); padding:35px 40px 25px; box-shadow:0 0 20px rgba(0,153,255,.12); }
  .lkbox:not(.guestcard) h3 { font-size:30px; margin-bottom:22px; }
  .lkbox:not(.guestcard) .lklabel { font-size:16px; letter-spacing:1px; color:#aab9ed; margin-bottom:10px; }
  .lkbox:not(.guestcard) .lktopline .lklabel { margin-bottom:10px; }
  .lkbox:not(.guestcard) .lkfield, .lkbox:not(.guestcard) .lkview { height:65px; font-size:19px; padding:0 25px; border-radius:17px; }
  .lkbox:not(.guestcard) .lksplit { gap:30px; margin-bottom:25px; }
  .lkbox:not(.guestcard) .lktopline { gap:30px; margin-bottom:28px; }
  .lkbox:not(.guestcard) .lkfolderrow { gap:18px; }
  .lkbox:not(.guestcard) .lkfolderrow .btn { height:65px; min-height:65px; font-size:18px; border-radius:16px; }
  .lkbox:not(.guestcard) .lkpwsection { margin-bottom:30px; }
  .lkbox:not(.guestcard) .lkpwrow { gap:10px; }
  .lkbox:not(.guestcard) .lkpwrow .lkiconbtn { width:80px; height:65px; border-radius:17px; }
  .lkbox:not(.guestcard) .lkpwrow .lkiconbtn svg { width:26px; height:26px; }
  .lkbox:not(.guestcard) .lkperms { padding:20px 25px; margin-bottom:28px; border-color:#354777; }
  .lkbox:not(.guestcard) .lkpermgrid { gap:15px 25px; }
  .lkbox:not(.guestcard) .permchk { font-size:18px; gap:13px; }
  .lkbox:not(.guestcard) .permbox { width:34px; height:34px; border-radius:9px; }
  .lkbox:not(.guestcard) .permbox::after { left:11px; top:5px; width:8px; height:16px; border-width:0 3px 3px 0; }
  .lkbox:not(.guestcard) .lksavewrap .btn.primary { width:165px; height:58px; min-height:58px; font-size:20px; border-radius:17px; background:#277ff0; color:#ffffff; }
  .lkbox:not(.guestcard) .lkclosebtn { top:17px; right:17px; width:48px; height:48px; border-radius:13px; background:#f22635; border-color:#f22635; font-size:27px; }
  .lkbox:not(.guestcard) .lkopenwarn.show { padding:13px 25px; border:2px solid #ffb000; border-radius:20px; color:#ffb000; background:#211d20; font-size:18px; margin-bottom:15px; }
  /* v2.8.3 Set Up remake (Essef's annotated 2.8.2 proof + ChatGPT HTML, literally): ChatGPT font stack for the dialog; password box ends where the New Address field ends (left-column width = (content - 30px gap)/2, NOT full width), with the 80x65 eye/delete buttons immediately right of it (not stranded at the dialog far right); folder-view icon gap. The 2.8.2 65px/1200px/34px/165x58/48x48 sizes are kept — the proof's smaller look was the screenshot scale, verified by measurement below. */
  .lkbox:not(.guestcard) { font-family:"Segoe UI", Arial, sans-serif; }
  .lkbox:not(.guestcard) input, .lkbox:not(.guestcard) button { font-family:inherit; }
  .lkbox:not(.guestcard) .lkpwrow input.lkfield { flex:0 0 calc((100% - 30px) / 2); width:auto; min-width:0; }
  .lkbox:not(.guestcard) .lkview { gap:10px; }
  .lkdivider { border:none; border-top:1px solid #35446e; margin:20px 0 28px; }
  .lkbox.guestcard .lkdivider { display:none; }
  .lkbox .lkclosebtn { position:absolute; top:10px; right:12px; }
  .lkbox { position:relative; border-top:3px solid #22d3ee; }
  /* v2.8.4 Set Up polish (zoomed button reference + annotated proof): folder buttons dark fills with thin coloured borders + outline icons, scoped to the host dialog only so the Files-tab buttons keep their colours; folder buttons vertically span exactly the New Address field (same top, same bottom, same 65px height); Permissions heading moved above the box; refined circled-i info icon; visibly unlocked notice icon. */
  .lkbox:not(.guestcard) .lktopline { align-items:end; }
  .lkbox:not(.guestcard) .lknewcol { align-self:end; }
  .lkbox:not(.guestcard) .lkfolderrow { align-self:end; height:65px; margin-top:0; }
  .lkbox:not(.guestcard) .lknewcol .lkfield { margin-bottom:0; }
  .lkbox:not(.guestcard) .lkfolderrow .btn { height:65px; min-height:65px; margin-top:0; display:inline-flex; align-items:center; justify-content:center; gap:10px; }
  .lkbox:not(.guestcard) .lkfolderrow .btn svg { width:22px; height:22px; flex:none; }
  .lkbox:not(.guestcard) .btn.openf { background:#092a48; border:2px solid #00c9f5; color:#65e4ff; }
  .lkbox:not(.guestcard) .btn.openf:hover { filter:brightness(1.15); border:2px solid #00c9f5; }
  .lkbox:not(.guestcard) .btn.changef { background:#261448; border:2px solid #b638f5; color:#ffffff; }
  .lkbox:not(.guestcard) .btn.changef:hover { filter:brightness(1.15); border:2px solid #b638f5; }
  .lkbox:not(.guestcard) .lkperms { margin-top:0; }
  .lkpermlabel { font-size:16px; letter-spacing:1px; color:#aab9ed; font-weight:700; margin:0 0 10px; display:flex; align-items:center; font-family:"Segoe UI", Arial, sans-serif; }
  /* v2.8.21 (C): LIGHT mode only -- the Set Up label texts
     ("Current Address", "Folder For This Address", "New
     Address", "Password (Optional)", "Permissions") were the
     pale #aab9ed on a white card: unreadable. Darkened here
     ONLY; nothing else on this page is resized or moved. */
  html.light .lkbox:not(.guestcard) .lklabel,
  html.light .lkbox:not(.guestcard) .lkpermlabel { color:#1e293b; }
  .lkperminfo { width:24px; height:24px; border:1.5px solid #38bdf8; background:transparent; color:#38bdf8; border-radius:50%; display:inline-flex; align-items:center; justify-content:center; cursor:pointer; margin-left:8px; vertical-align:middle; padding:0; }
  .lkperminfo svg { width:20px; height:20px; display:block; }
  .lkopenwarn svg { width:20px; height:20px; vertical-align:-4px; margin-right:8px; }
  /* v2.7.89 GUEST link page design: a distinct, professional
     card, not a plain stacked form. Solid colours only (the
     classic-futuristic palette): a solid violet header card
     with a white icon chip, a violet-edged "Connected address"
     card, wider spacing, and a solid violet Save for guests
     (host Save stays cyan). The host dialog is unchanged. */
  .lkbox.guestcard { width:400px; border-top:3px solid #a78bfa; }
  .guestcardhead { display:flex; align-items:center; gap:12px; background:#7c3aed; border-radius:14px; padding:14px 16px; margin:4px 0 12px; box-shadow:0 8px 24px rgba(0,0,0,.35); }
  .guestcardic { flex:none; width:44px; height:44px; border-radius:12px; background:#ffffff; color:#7c3aed; display:flex; align-items:center; justify-content:center; font-size:22px; }
  .guestcardtxt { display:flex; flex-direction:column; gap:2px; }
  .guestcardtxt b { font-size:16px; color:#ffffff; }
  .guestcardtxt span { font-size:12px; color:#e9d5ff; }
  .guestlinkcard { display:flex; flex-direction:column; gap:2px; background:var(--card2); border:1px solid #a78bfa; border-left:4px solid #a78bfa; border-radius:12px; padding:12px 14px; margin:0 0 14px; }
  .glklabel { font-size:11px; font-weight:800; letter-spacing:.08em; color:var(--muted); text-transform:uppercase; }
  .glkname { font-size:15px; font-weight:800; color:var(--txt); }
  .lkbox.guestcard .lklabel { margin-top:14px; }
  /* v2.8.16 (Essef Nov 5): in the Connect To A PC window the
     "Address To Connect" label gets extra space BELOW it --
     14px between the label and the field under it. */
  .lkbox.guestcard #lklinklabel { margin-bottom:14px; }
  .lkbox.guestcard input[type="text"], .lkbox.guestcard input[type="password"] { padding:14px 12px; }
  .lkbox.guestcard .btn.primary { background:#7c3aed; color:#ffffff; }
  .mconnstate { font-size:12px; font-weight:700; color:var(--muted); margin:2px 0 8px; }
  /* v2.7.90 BUTTON DESIGN RESTORED: the pre-tab-style design
     used before the v2.7.89 tab-shape restyle. Buttons are the
     plain .btn shape again (10px radius, dark fill, 1px border;
     .primary / .dangergrad / .openf / .changef gradients, and
     the .lkbox solid overrides for the link dialog). The
     v2.7.89 tab-shape restyle (.tabbtn white tab with curved
     top, grey text, overlapping -10px margins, .tabfixed black
     underline bar, .tabdanger red text) is REMOVED everywhere,
     including the Set up your addresses page: no button carries a
     tabbtn/tabfixed/tabdanger classes any more, and no tab-shape
     CSS remains to restyle one. The count badge on Delete
     (.tabbadge, a small purple number) is kept -- it is a badge,
     not a button shape. */
  .tabbadge { display:inline-block; background:#7c3aed; color:#ffffff; font-size:11px; font-weight:800; border-radius:6px; padding:2px 6px; margin-left:6px; vertical-align:middle; }
  /* v2.7.90 GUEST LOGIN PAGE (page 1 of the guest web pager):
     clean, centred, Drop logo + slogan, link + password fields.
     Shown to guests instead of the old lock overlay; the main
     page (board + 4 tabs) is shown only once connected. */
  /* v2.8.18 (4): the login page hides the top bar, board, pill
     tabs and footer, so the body's padding (which leaves room
     for the pill tabs) only adds scroll on top of the login's
     own 100dvh -- while the login is open the body has no
     padding at all, so the login fits the viewport exactly. */
  body:has(.guestlogin.open) { padding:0; }
  /* v2.8.32: the pill tabs, top bar, board and footer must NEVER
     show while the login page is open. Until now the hide lived
     only in showGuestLogin()'s one-shot inline styles, so any
     path that displayed the login form without that hide having
     taken effect left the pill tabs (and the hamburger) visible
     on the login screen -- exactly what Essef photographed
     Nov 6. CSS enforces the rule structurally now: the moment
     .guestlogin.open is present the tabs cannot render, whatever
     JS ran before, and they return the moment it closes. */
  body:has(.guestlogin.open) .mtabs,
  body:has(.guestlogin.open) .topbar,
  body:has(.guestlogin.open) .board,
  body:has(.guestlogin.open) footer { display:none !important; }
  .guestlogin { display:none; align-items:center; justify-content:center; flex-direction:column; min-height:100vh; min-height:100dvh; padding:12px 12px 16px; }
  .guestlogin.open { display:flex; }
  .gloginbox { width:min(400px,94vw); background:var(--card); border:1px solid var(--line); border-radius:14px; padding:20px 24px 18px; box-shadow:0 8px 24px rgba(0,0,0,.22); }
  .glogo { display:flex; flex-direction:column; align-items:center; justify-content:center; gap:2px; font-size:30px; font-weight:800; letter-spacing:-.02em; text-align:center; color:var(--txt); }
  .glogo img { height:64px; width:auto; flex:none; }
  .glogo .gdrop { font-size:30px; font-weight:800; line-height:1.1; }
  .gslogan { text-align:center; color:var(--muted); font-size:13px; margin:6px 0 16px; }
  /* v2.8.18 (6): login labels are centred, like the APK. */
  .gloginbox .lklabel { text-align:center; }
  .gloginbox input:not([type=checkbox]) { width:100%; box-sizing:border-box; background:var(--card2); color:var(--txt); border:1px solid var(--line); border-radius:10px; padding:12px; font-size:15px; font-family:inherit; margin:0 0 10px; }
  .gloginbox input:not([type=checkbox]):focus { outline:none; border-color:var(--acc); }
  .gloginbox input:not([type=checkbox]):disabled { opacity:.55; }
  /* v2.8.38 (7): the Save-password checkbox MUST stay invisible
     as a native control -- the broad .gloginbox input rules
     above used to restyle it (width:100% made it 390px wide,
     and input:disabled opacity:.55 beat .permchk's opacity:0,
     so on an open address the native box showed through as a
     grey square overlapping "Save password" -- Essef's
     image-76; the custom .permbox is the only visible box). */
  .gloginbox .permchk input, .gloginbox .permchk input:disabled { opacity:0; width:auto; height:auto; }
  .gloginbox .btn { width:100%; padding:12px; font-size:15px; }
  /* v2.8.14 login Connect (Essef Nov 5, screenshot 3): NOT
     full-width and NOT the cyan->violet gradient -- 60% wide,
     centred, solid blue #277ff0 like the other buttons.
     v2.8.16 (Essef Nov 5, login screenshot): the text must be
     WHITE (the .btn.primary dark ink #0a0f1e was showing on the
     blue), and the button sits slightly UP -- the gap above it
     (error line + input margin) is pulled in 4px. */
  .gloginbox #gloginbtn { width:60%; margin:-4px auto 0; display:block; background:#277ff0; border:none; color:#ffffff; }
  /* v2.8.16 (Essef Nov 5, login screenshot, yellow mark): the
     chevron/arrow at the right end of the Address field sits a
     bit HIGHER up -- 3px above the field's vertical centre.
     The wrapper is 10px taller than the input (the input's
     bottom margin), so 50% of the wrapper is 5px below the
     input's centre: 50% - 8px lands the chevron 3px above it. */
  #gddwrap .ddchevbtn { top:calc(50% - 8px); }
  .gloginerr { color:var(--bad); font-size:13px; min-height:18px; margin:2px 0 8px; text-align:center; }
  .gloginmsg { color:var(--muted); font-size:13px; text-align:center; margin:10px 0 0; line-height:1.5; }
  /* v2.8.18 (5): the open-address note under the password field
     is GREEN, like the APK -- it is only ever set for an open
     address (see checkOpenAddress), never for a locked one. */
  .gloginpwstate { color:#22c55e; font-weight:600; font-size:13px; text-align:center; margin:0 0 10px; min-height:18px; }
  .gloginpwstate:empty { display:none; }
  /* v2.8.35: Save password on the login page, beside the
     Disconnected status line. The status text itself is
     untouched. */
  .gloginsave { justify-content:center; margin:10px 0 2px; }
  /* v2.7.92 PROPER DROPDOWN (shared host + guest): a closed
     bordered field with a chevron, opening a floating white
     list below it. Row states, exactly as Essef's screenshot:
     Enabled black on white; Hovered black on light grey;
     Selected purple text on white; Selected + Hovered purple
     text on light grey. This is NOT a rows list. */
  .ddrop { position:relative; width:100%; }
  .ddfield { display:flex; align-items:center; gap:8px; background:#ffffff; color:#111827; border:1px solid #d1d5db; border-radius:10px; padding:12px 12px; font-size:15px; cursor:pointer; box-sizing:border-box; width:100%; }
  .ddfield .ddtext { flex:1 1 auto; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:700; }
  .ddfield .ddchev { flex:none; font-size:14px; }
  /* v2.8.38 (3): the address-history / links lists follow the
     THEME -- they were hard-coded white (#ffffff / #111827),
     so in dark theme they glowed white. Base rules now use
     the theme vars (dark list in dark theme); the explicit
     html.light rules below keep the exact old light look. The
     selected row uses --acc2 so it stays readable on dark
     (#a78bfa) and keeps the old purple on light (#7c3aed). */
  .ddlist { display:none; position:absolute; top:calc(100% + 4px); left:0; right:0; background:var(--card); border:1px solid var(--line); border-radius:10px; box-shadow:0 12px 28px rgba(0,0,0,.30); z-index:50; overflow:hidden; max-height:260px; overflow-y:auto; }
  .ddlist.open { display:block; }
  .ddopt { display:flex; align-items:center; gap:8px; padding:10px 12px; background:var(--card); color:var(--txt); cursor:pointer; font-size:14px; }
  .ddopt:hover, .ddopt.ddhover { background:var(--card2); }
  .ddopt.ddsel { color:var(--acc2); }
  .ddopt.ddsel:hover, .ddopt.ddsel.ddhover { background:var(--card2); color:var(--acc2); }
  .ddopt .ddname { flex:1 1 auto; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:700; }
  .ddopt .ddpw { color:var(--muted); font-size:12.5px; flex:none; white-space:nowrap; }
  .ddopt button { flex:none; background:none; border:1px solid var(--line); border-radius:9px; width:32px; height:32px; cursor:pointer; font-size:14px; color:var(--txt); display:inline-flex; align-items:center; justify-content:center; }
  .ddopt button svg { width:16px; height:16px; display:block; }
  .ddopt.ddempty { cursor:default; color:var(--muted); }
  .ddopt.ddempty:hover { background:var(--card); }
  html.light .ddlist { background:#ffffff; border-color:#d1d5db; }
  html.light .ddopt { background:#ffffff; color:#111827; }
  html.light .ddopt:hover, html.light .ddopt.ddhover { background:#f3f4f6; }
  html.light .ddopt.ddsel:hover, html.light .ddopt.ddsel.ddhover { background:#f3f4f6; }
  html.light .ddopt .ddpw { color:#6b7280; }
  html.light .ddopt button { border-color:#d1d5db; color:#111827; }
  html.light .ddopt.ddempty { color:#6b7280; }
  html.light .ddopt.ddempty:hover { background:#ffffff; }
  /* v2.7.92: the dropdown drops from the address field itself
     (host Set up page + guest login page), not from a separate
     history section. The chevron sits inside the field; the list
     floats below it. */
  .ddwrap { position:relative; width:100%; }
  .ddwrap > input { padding-right:38px; }
  .ddchevbtn { position:absolute; right:8px; top:50%; transform:translateY(-50%); background:none; border:none; cursor:pointer; color:var(--muted); font-size:14px; padding:6px; line-height:1; z-index:3; }
  .ddwrap .ddlist { z-index:60; }
  /* Address colour dot: the deterministic per-address colour,
     shown wherever an address name appears (top field, sidebar,
     current-address view, dropdown rows). The name text itself
     keeps the theme colour, so it reads in both modes. */
  .addot { display:inline-block; width:10px; height:10px; border-radius:50%; flex:none; vertical-align:baseline; margin-right:7px; }
  .connectbar .addot { vertical-align:-1px; }
  @keyframes eyesnap { 0% { transform:scale(1); } 40% { transform:scale(1.3) rotate(-10deg); } 100% { transform:scale(1); } }
  .eyesnap svg { animation:eyesnap .35s ease; }
  @keyframes lockwiggle { 0% { transform:rotate(0) scale(1); } 30% { transform:rotate(-14deg) scale(1.15); } 60% { transform:rotate(10deg) scale(1.1); } 100% { transform:rotate(0) scale(1); } }
  .lockanim { animation:lockwiggle .45s ease; }
  /* v2.7.92: host saved-links history is a proper dropdown
     (see the shared .ddrop rules above), not a rows list. */
  /* v2.7.89 hover popup: small white tooltip above the button,
     never covering it; positioned by JS, hidden by default. */
  #hovertip { position:fixed; z-index:2000; display:none; background:#ffffff; color:#111827; font-size:12.5px; font-weight:600; border-radius:10px; padding:7px 10px; box-shadow:0 8px 24px rgba(0,0,0,.30); max-width:240px; text-align:center; pointer-events:none; }
  #hovertip.show { display:block; }
  html.light #hovertip { background:#111827; color:#ffffff; }
  @keyframes lkshake { 0%,100% { transform:translateX(0); } 20% { transform:translateX(-7px); } 40% { transform:translateX(7px); } 60% { transform:translateX(-5px); } 80% { transform:translateX(5px); } }
  .shake { animation:lkshake .45s ease; border-color:var(--bad) !important; }
  .lkbox h3 { text-align:center; }
  .lkview { display:flex; align-items:center; gap:9px; background:var(--card2);
    border:1px solid var(--line); border-radius:12px; padding:13px 12px; font-size:15px;
    box-sizing:border-box; width:100%; }
  #lkname { flex:1 1 auto; min-width:0; font-weight:700; white-space:nowrap; overflow:hidden;
    text-overflow:ellipsis; }
  #lkfolder { flex:1 1 auto; min-width:0; white-space:nowrap; overflow:hidden;
    text-overflow:ellipsis; }
  .lkeditrow { display:flex; align-items:center; gap:7px; }
  .lkeditrow input { flex:1 1 auto; min-width:0; }
  .lkdot { color:var(--muted); font-weight:700; }
  .lklabel { font-size:11px; font-weight:700; letter-spacing:.09em; text-transform:uppercase;
    color:var(--muted); margin:10px 0 6px; }
  .lkspace { display:flex; align-items:center; gap:8px; padding:8px 10px; border:1px solid var(--line);
    border-radius:11px; margin-bottom:7px; font-size:13px; }
  .lkspace .lkfolder { color:var(--muted); flex:1 1 auto; min-width:0; white-space:nowrap;
    overflow:hidden; text-overflow:ellipsis; }
  .lkaddpw { display:flex; gap:7px; }
  .lkaddpw input { flex:1 1 auto; min-width:0; }
  .lkclose { display:block; width:auto; min-width:150px; padding:11px 26px; margin:12px auto 0; }
  .lockpwpop { display:none; position:fixed; inset:0; z-index:130; align-items:center; justify-content:center; background:rgba(3,5,10,.5); padding:16px; }
  .lockpwpop.open { display:flex; }
  /* v2.7.94 Set Password popup: clean and centred, good
     spacing; background + border match the Devices Connected
     pill (same card surface / border treatment). Its X is
     positioned inside the popup corner (see the shared red-X
     rule above); Save stays small, never full-width.
     v2.7.96: the background is EXPLICIT and solid, not a bare
     theme var -- dark #12172a with a #2a3560 border, light
     #ffffff with a #c3cfde border -- so the popup box is
     visibly distinct from the page behind it in both modes,
     including dark mode. Its title area sits on the same solid
     card surface (no transparent title strip). */
  .lockpwbox { position:relative; width:min(360px,92vw); background:#12172a; border:1px solid #2a3560; border-radius:14px; padding:28px 22px 22px; box-shadow:0 16px 40px rgba(0,0,0,.35); }
  html.light .lockpwbox { background:#ffffff; border-color:#c3cfde; box-shadow:0 16px 40px rgba(15,23,42,.25); }
  .lockpwbox h4 { background:#12172a; }
  html.light .lockpwbox h4 { background:#ffffff; }
  .lockpwbox .lkclosebtn { position:absolute; top:10px; right:12px; }
  .lockpwbox h4 { font-size:16px; margin-bottom:16px; text-align:center; line-height:1.4; padding:0 24px; }
  /* v2.8.9: exactly ONE eye in "Set Password For Address:
     <address>" -- the custom button is now INSIDE the field
     box (see .lockpwfield / .lockpweye in the v2.8.9 block).
     Edge/WebView2 also paints its own native reveal eye INSIDE
     password fields -- that duplicate is hidden here, so the
     popup never shows two eyes. The custom button keeps its
     eyesnap animation (paintEyeBtn). */
  #lockpwin::-ms-reveal { display:none; }
  #lockpwin::-ms-clear { display:none; }
  /* v2.8.29 (5): exactly ONE eye in "Set Up Your Addresses"
     too (Essef Nov 6) -- Edge/WebView2 paints its own native
     reveal eye INSIDE password fields, and the Set Up field
     (#lkpw) never got the hide that 2.8.9 gave #lockpwin, so
     the desktop app showed the native eye inside the box PLUS
     the custom #lkpweye toggle outside it. Same hide here, so
     only the outside toggle remains. Scoped to #lkpw on
     purpose: the guest login field (#gloginpw) has no outside
     eye, so its native reveal stays its only one. */
  #lkpw::-ms-reveal { display:none; }
  #lkpw::-ms-clear { display:none; }
  .lockpwerr { color:var(--bad); font-size:13px; min-height:18px; text-align:center; margin-top:8px; }
  .lockpwsave { display:flex; align-items:center; justify-content:center; gap:4px; width:auto; min-width:130px; padding:10px 26px; margin:14px auto 0; }
  #lockwrap { inset:58px 0 0 0; }
  #lockwrap .lockbox { background:transparent; border:none; box-shadow:none; }
  #lockwrap .lockic { width:112px; height:112px; border-radius:50%; margin:0 auto 16px;
    display:flex; align-items:center; justify-content:center; color:#fff;
    background:linear-gradient(135deg,#f59e0b,#ef4444,#7C3AED);
    box-shadow:0 14px 34px rgba(0,0,0,.4); }
  #lockwrap .lockic svg { width:52px; height:52px; }
  #lockwrap h3 { font-size:21px; }

  /* v2.8.5 main-page button language (reference: Shared Texts / Shared Files
     card buttons, Essef Nov 3). Solid fills per action, icon before text,
     18px corners, generous padding. Scoped to .board / .msend ONLY -- the
     Set Up dialog (.lkbox) keeps its 2.8.4 dark-outline folder buttons. */
  .board .nbtnrow .btn, .board .fbtnrow .btn, .board #sendsnippet,
  .msend .mbtn-primary, .msend .mbtn-secondary {
    border:none; border-radius:18px; padding:14px 16px; font-size:15px;
    font-weight:700; display:inline-flex; align-items:center;
    justify-content:center; gap:8px; white-space:nowrap; }
  .board .nbtnrow .btn svg, .board .fbtnrow .btn svg, .board #sendsnippet svg {
    width:18px; height:18px; flex:none; }
  .board #sendsnippet, .board #maddnote, .board #fileaddbtn,
  .msend .mbtn-primary, .msend #msendfiles {
    background:#277ff0; color:#ffffff; }
  .board #sendsnippet:hover, .board #maddnote:hover, .board #fileaddbtn:hover,
  .msend .mbtn-primary:hover, .msend #msendfiles:hover { filter:brightness(1.08); border:none; }
  /* v2.8.13: web/mobile-web "Choose files to send" (#msendfiles)
     is DARK BROWN (#4E342E, same as the APK button) and a PILL
     (fully rounded, like the APK buttons) — white text + white
     folder icon. This ID rule only; every other button keeps its
     own colour and shape. */
  .msend #msendfiles { background:#4E342E; color:#FFFFFF; border-radius:999px; }
  .msend #msendfiles svg { fill:#FFFFFF; }
  /* v2.8.17 (i): "Choose Files to Send" (#msendfiles) and "Send
     Text" (#msendsnippet) on the web version share ONE shape
     and are NARROWER and centred, like the APK -- the same
     width, radius and display on both (their colours stay
     different). Sits after the 2.8.13 #msendfiles pill rule so
     it wins the cascade at the same specificity.
     v2.8.20 (6): 70% -> 60%, the APK / login "Saved on this
     phone" width -- Essef Nov 5, the web Upload buttons were
     still too wide. */
  .msend #msendfiles, .msend #msendsnippet { width:60%; margin:10px auto 0; display:flex; border-radius:13px; }
  /* v2.8.23 (4): the WEB Upload buttons go back to the APK
     2.6.69 design (decoded from the real 2.6.69 backup APK,
     DropIt-2.6.69-backup.apk, and Essef's photo 9945_3_q880.jpg):
     FULL-WIDTH buttons (match_parent in 2.6.69 -- the 60%
     centred width from 2.8.17/2.8.20 is reverted), 12px corners
     (btn_primary / btn_secondary radius 12dp), 12px padding,
     14px text. CORRECTION (coordinator, Nov 6): 2.6.69's
     "Choose Files to Send" is NOT the brown #4E342E button --
     that brown was a LATER choice (2.8.13, Essef Nov 4). The
     real 2.6.69 button is btn_secondary: theme-adaptive fill
     (white #FFFFFF in light mode, #141926 in dark), theme text
     (?cTxt: #0F172A light / #EEF1F8 dark), 1dp stroke (?cLine:
     #C3CFDE light / #2A3560 dark), and the folder is the 📁
     EMOJI inside the label -- no drawableStart. The APK
     2.6.97 track verified this against the real backup APK
     with aapt2; the first web pass wrongly kept the brown.
     Send Text is BOLD on solid blue #277ff0 (btn_main_blue,
     same as the APK) with the text-snippet icon (APK ic_note,
     per Essef Nov 6 ~2:03 AM -- not the upload arrow, not the
     chat bubble, not the airplane). Scoped to
     html:not(.pcapp): the PC desktop app (pywebview bridge ->
     .pcapp, see markPcApp) keeps its 2.8.22 buttons exactly --
     the 2.8.13 brown pill rule and the 2.8.17 60% rule above
     stay as its base. The h3 "Send Text" heading keeps its
     chat bubble; only the BUTTON icons change. Button top
     margin stays 6px (2.8.20): the taller 12px padding would
     otherwise push the 390x844 stack over the column and flip
     send-may-scroll on. */
  /* v2.8.39 (3): the Files tab's Open / Change Folder buttons do
     nothing on the web PC version (no bridge, no OS folder to
     open) -- they are hidden there. The desktop app (pywebview
     bridge -> .pcapp, see markPcApp) keeps them exactly; the
     menu and Set Up window buttons are untouched (different
     elements: #sbopen/#sbchange, #lkopenfolder/#lkchangefolder).
     Phone widths already hide them (mobile media query below). */
  html:not(.pcapp) .fbtnrow #openfolder, html:not(.pcapp) .fbtnrow #changefolder { display:none; }
  /* v2.8.39 (8): the Files-tab Add New button is web-PC only --
     the desktop app (pywebview bridge -> .pcapp) never shows
     it; its Open / Change / Delete row is untouched. */
  html.pcapp .fbtnrow #fileaddbtn { display:none; }
  html:not(.pcapp) .msend #msendfiles, html:not(.pcapp) .msend #msendsnippet { width:100%; margin:6px auto 0; display:flex; border-radius:12px; padding:12px; font-size:14px; }
  html:not(.pcapp) .msend #msendfiles { font-weight:400; background:#141926; color:#EEF1F8; box-shadow:inset 0 0 0 1px #2A3560; }
  html.light:not(.pcapp) .msend #msendfiles { background:#FFFFFF; color:#0F172A; box-shadow:inset 0 0 0 1px #C3CFDE; }
  html:not(.pcapp) .msend #msendfiles svg { display:none; }
  html:not(.pcapp) .msend #msendfiles::before { content:"📁"; }
  html:not(.pcapp) .msend #msendsnippet { font-weight:700; background:#277ff0; color:#ffffff; }
  /* Send Text button icon: the text-snippet (note) icon on web.
     The chat bubble stays in the markup FIRST (so the round33
     source check still sees it) and shows in the PC app; the
     note icon is hidden there and shown on web. The note svg
     matches the folder icon's 18px on the mobile button. */
  #sendsnippet .ic-note, #msendsnippet .ic-note { display:none; }
  html:not(.pcapp) #sendsnippet .ic-note, html:not(.pcapp) #msendsnippet .ic-note { display:inline; }
  html:not(.pcapp) #sendsnippet .ic-bubble, html:not(.pcapp) #msendsnippet .ic-bubble { display:none; }
  html:not(.pcapp) .msend #msendsnippet svg { width:18px; height:18px; flex:none; }
  .board #starfilter { background:#fbbf24; color:#231303; border:none; }
  .board #starfilter:hover { filter:brightness(1.08); border:none; }
  .board #starfilter svg, .board #starfilter svg path { fill:#231303; stroke:none; }
  .board #delallnotesbtn, .board #delallbtn, .delbar .confirmdel {
    background:#ef4444; color:#ffffff; border:none; }
  .board #delallnotesbtn:hover, .board #delallbtn:hover { filter:brightness(1.08); border:none; }
  .board .fbtnrow #openfolder { background:#277ff0; color:#ffffff; border:none; }
  .board .fbtnrow #changefolder { background:#8B5CF6; color:#ffffff; border:none; }
  .board .fbtnrow #openfolder:hover, .board .fbtnrow #changefolder:hover { filter:brightness(1.08); border:none; }
  .board .askinput button { background:#277ff0; color:#ffffff; border:none; }
  .board .askinput button:hover { filter:brightness(1.08); }
  #sbopen { background:#277ff0; color:#ffffff; border:none; }
  #sbchange { background:#8B5CF6; color:#ffffff; border:none; }
  /* v2.8.5 Set Up password eye/delete shift (Essef Nov 3, yellow lines):
     eye left edge aligned with the Set Up Open Folder button's left edge.
     On the 2.8.4 render the eye was 16px left of that edge, so the eye
     row gets a 16px left offset; delete follows (same gap, same size).
     Password box width, button sizes and everything else unchanged. */
  .lkbox:not(.guestcard) .lkpwrow #lkpweye { margin-left:20px; }
  .lkbox #lkset svg { width:20px; height:20px; flex:none; }
  /* v2.8.5 Files row: same fills/radius, smaller text so the three
     buttons fit a 3-column card without clipping their labels. */
  .board .fbtnrow .btn { padding:16px 2px; font-size:11px; gap:3px; }
  .board .fbtnrow .btn svg { width:12px; height:12px; }

  /* v2.8.6 (Essef Nov 4): (1) Set Up dialog FITS without scrolling at
     normal viewports: compact host-dialog sizes (fields 65px -> 52px,
     all fields still equal height, eye/delete at field height),
     tighter padding/margins/gaps; total dialog ~650px, fits 800px
     viewports (768px usable) with Save visible, no scrollbar.
     (2) RECTANGULAR buttons everywhere: main-page and Set Up
     buttons get 8px corners (not 18px pill-like), full-width
     proportions, icon before text; fills/colours per action
     unchanged. Files-row buttons are NOT shrunk to 11px any
     more: 13px text, wrapping allowed so labels are never
     clipped. (3) Devices pill slightly higher, no resize. */
  .lkbox:not(.guestcard) { max-height:calc(100dvh - 32px); padding:20px 32px 16px; }
  .lkbox:not(.guestcard) h3 { font-size:26px; margin-bottom:12px; }
  .lkbox:not(.guestcard) .lklabel { font-size:15px; margin-bottom:6px; }
  .lkbox:not(.guestcard) .lkfield, .lkbox:not(.guestcard) .lkview { height:52px; font-size:17px; padding:0 18px; border-radius:12px; }
  .lkbox:not(.guestcard) .lksplit { gap:20px; margin-bottom:16px; }
  .lkbox:not(.guestcard) .lktopline { gap:20px; margin-bottom:16px; }
  .lkbox:not(.guestcard) .lkfolderrow { gap:14px; height:52px; }
  .lkbox:not(.guestcard) .lkfolderrow .btn { height:52px; min-height:52px; font-size:17px; border-radius:8px; }
  .lkbox:not(.guestcard) .lkfolderrow .btn svg { width:20px; height:20px; }
  .lkbox:not(.guestcard) .lkpwsection { margin-bottom:16px; }
  .lkbox:not(.guestcard) .lkpwrow { gap:8px; }
  .lkbox:not(.guestcard) .lkpwrow .lkiconbtn { width:64px; height:52px; border-radius:12px; }
  .lkbox:not(.guestcard) .lkpwrow .lkiconbtn svg { width:22px; height:22px; }
  .lkbox:not(.guestcard) .lkperms { padding:14px 18px; margin-bottom:16px; }
  .lkbox:not(.guestcard) .lkpermgrid { gap:10px 18px; }
  .lkbox:not(.guestcard) .permchk { font-size:16px; gap:10px; }
  .lkbox:not(.guestcard) .permbox { width:26px; height:26px; border-radius:7px; }
  .lkbox:not(.guestcard) .permbox::after { left:8px; top:3px; width:6px; height:12px; border-width:0 3px 3px 0; }
  .lkbox:not(.guestcard) .lksavewrap { margin-top:14px; gap:8px; }
  .lkbox:not(.guestcard) .lksavewrap .btn.primary { width:150px; height:48px; min-height:48px; font-size:18px; border-radius:8px; }
  .lkbox:not(.guestcard) .lkclosebtn { top:14px; right:14px; width:44px; height:44px; font-size:24px; }
  .lkbox:not(.guestcard) .lkopenwarn.show { padding:10px 20px; font-size:16px; margin-bottom:10px; }
  .lkdivider { margin:12px 0 16px; }
  .lkpermlabel { margin-bottom:8px; }
  .devpill { top:-54px; }
  /* Rectangular buttons: main page + Set Up dialog + dialogs. */
  .board .nbtnrow .btn, .board .fbtnrow .btn, .board #sendsnippet,
  .msend .mbtn-primary, .msend .mbtn-secondary,
  .lkbox .btn, .mbox .btn, .delbar .confirmdel, .board .askinput button,
  #sbopen, #sbchange { border-radius:8px; }
  .board .nbtnrow .btn { font-size:14px; padding:12px 8px; white-space:normal; overflow:visible; text-overflow:clip; line-height:1.25; }
  .board .fbtnrow { flex-wrap:wrap; }
  .board .fbtnrow .btn { padding:12px 6px; font-size:13px; gap:6px; white-space:normal; overflow:visible; text-overflow:clip; line-height:1.25; }
  .board .fbtnrow .btn svg { width:16px; height:16px; }
  .lkbox:not(.guestcard) .lkfolderrow .btn { border-radius:8px; }
  /* v2.8.7 (Essef Nov 4): Set Up fits, no scroll in ANY direction;
     locked/open notices; rectangular refined buttons; menu cards;
     dropdown animation; Save icon lowered; Send refined. */
  #lkwrap { overflow:hidden; padding:12px; box-sizing:border-box; }
  #lkwrap .lockbox.lkbox { max-height:calc(100dvh - 24px); overflow:hidden; }
  .lkbox:not(.guestcard) { width:min(960px, calc(100vw - 24px)); max-width:calc(100vw - 24px); box-sizing:border-box; overflow:hidden; }
  /* v2.8.22 (10): the Set Up Your Addresses window border is
     SQUARE -- corners only. This one rule (higher specificity
     than .lockbox's 18px and the 2.8.0 rule's 27px, placed after
     both) zeroes the window's own border-radius in every
     viewport. Nothing inside the window changes: every inner
     field, button, checkbox and label keeps its own radius,
     and the window's width, padding and height are untouched. */
  .lockbox.lkbox:not(.guestcard) { border-radius:0; }
  .lkbox:not(.guestcard) .lksplit, .lkbox:not(.guestcard) .lktopline { min-width:0; }
  .lkbox:not(.guestcard) .lkcol, .lkbox:not(.guestcard) .lknewcol, .lkbox:not(.guestcard) .lkfield, .lkbox:not(.guestcard) .lkview { min-width:0; box-sizing:border-box; }
  .lkbox:not(.guestcard) .lkfield, .lkbox:not(.guestcard) .lkview { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  @media (max-width:720px) {
    .lkbox:not(.guestcard) .lksplit { grid-template-columns:1fr; }
    .lkbox:not(.guestcard) .lktopline { grid-template-columns:1fr; }
  }
  /* v2.8.8 (Essef Nov 4, 7:49 PM): the locked notice is a SMALL
     pill in the open notice's style. The 2.8.7 rule set NO svg
     size, so Chromium rendered the padlock at its 300x150
     default and the pill ballooned to ~170px tall, dominating
     the dialog. Sized svg (20px, same as the open notice) +
     host padding/font parity with the open notice; the subtle
     lockpulse animation is the only animation, no large card,
     no large icon, no layout domination. */
  .lklockedwarn { display:none; border:2px solid #f59e0b; color:#fbbf24; background:rgba(245,158,11,.12); border-radius:20px; padding:10px 20px; font-size:16px; margin:0 auto 10px; text-align:center; animation:lockpulse 1.6s ease-in-out infinite; }
  .lklockedwarn.show { display:table; margin-left:auto; margin-right:auto; }
  .lklockedwarn svg { width:20px; height:20px; vertical-align:-4px; margin-right:8px; flex:none; }
  .lkbox:not(.guestcard) .lklockedwarn.show { padding:10px 20px; font-size:16px; margin-bottom:10px; }
  @keyframes lockpulse { 0%,100% { box-shadow:0 0 0 0 rgba(245,158,11,.35); } 50% { box-shadow:0 0 0 6px rgba(245,158,11,0); } }
  /* v2.8.9: the Permissions "i" shows its message ONE way
     only -- the native hover tooltip from its title attribute.
     The click popup (.lkpermtip) that duplicated the same
     message is removed entirely. */
  /* Menu (sidebar) redesign: transparent + blur, card layout, smaller buttons. */
  #sidebar { background:rgba(13,18,32,.55); backdrop-filter:blur(14px) saturate(1.2); -webkit-backdrop-filter:blur(14px) saturate(1.2); width:264px; padding:16px 14px; }
  html.light #sidebar { background:rgba(255,255,255,.55); }
  /* v2.8.33 (4): the PC-app menu fits without scrolling -- NO
     scroller in the main menu (sidebar), PC app only. The menu
     content is ~675px tall in the host state (6 cards); at the
     PC window's 600px minimum height the 16px padding + 12px
     card gaps + 12px card padding overflowed by ~75px, so
     overflow-y:auto showed a scroller. Tighten the menu's own
     vertical spacing only -- 8px sidebar padding, 6px card
     gaps, 8px card padding, 4px head gap -- saving ~82px, so
     the menu fits at 600px with room to spare, and hide the
     vertical overflow outright -- there is nothing left to
     scroll to. Web keeps its scrolling drawer (the unscoped
     rule above is untouched). Contents, order and buttons are
     unchanged. */
  html.pcapp #sidebar { overflow-y:hidden; padding:8px 14px; }
  html.pcapp #sidebar .sbhead { margin-bottom:4px; }
  html.pcapp #sidebar .sbcard { margin-bottom:6px; padding-top:8px; padding-bottom:8px; }
  .sbcard { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:12px; margin-bottom:12px; }
  .sbcard .sbsec { margin:0 0 8px; }
  .sbcard .sblinkrow { border:none; background:transparent; padding:0; }
  #sidebar .sbbtn { padding:9px 10px; font-size:13px; border-radius:10px; margin-top:6px; display:inline-flex; align-items:center; gap:8px; }
  #sidebar .sbbtn svg { width:16px; height:16px; flex:none; }
  .sbbtn:disabled, .btn:disabled { opacity:.45; cursor:not-allowed; }
  /* Current Address dropdown: animated open + bigger chevron. */
  .lkcurdd .ddchev { font-size:20px; }
  .lkcurdd .ddlist { display:block; opacity:0; visibility:hidden; pointer-events:none; transform:translateY(-6px); transition:opacity .22s ease, transform .22s ease, visibility 0s linear .22s; }
  .lkcurdd .ddlist.open { opacity:1; visibility:visible; pointer-events:auto; transform:translateY(0); transition:opacity .22s ease, transform .22s ease; }
  .ddchevbtn { font-size:18px; }
  /* Home buttons refined: smaller, cleaner. */
  .board .nbtnrow .btn { font-size:13px; padding:10px 8px; gap:6px; }
  .board .fbtnrow .btn { font-size:12px; padding:10px 6px; gap:5px; }
  .board #sendsnippet { font-size:14px; padding:11px 14px; }
  .board .nbtnrow .btn svg, .board .fbtnrow .btn svg { width:15px; height:15px; }
  /* Send section refined: tighter, cleaner cards. */
  .board .minicard { padding:14px; }
  .board #drop { padding:16px 12px; }
  .board #drop .big { font-size:17px; }
  .board #snippet, .board #msendtext { padding:10px 12px; }
  /* Save icon lowered inside the (unchanged-size) Save button. */
  .lkbox #lkset svg { transform:translateY(3px); }
  /* Drop-zone directory on its own line (see HTML split below). */
  #landline .dirline { display:block; margin-top:2px; }
  /* v2.8.8 button tightening (Essef Nov 4: "buttons can be
     smaller and texts fitted cleanly"; clarification: text
     size MAY drop to fit, icons scaled + aligned to the
     reduced text, icon + text on one clean baseline). Size /
     fit ONLY: fills, actions, greying and 8px corners are
     unchanged, and every rule below sits last so it wins the
     cascade over the 2.8.7 sizes. Measured before/after in
     the round23 harness (offsetHeight, scroll overflow,
     icon-centre minus text-centre). */
  .btn { padding:7px 12px; font-size:12.5px; }
  .board .nbtnrow .btn { font-size:12px; padding:8px 7px; gap:5px; }
  .board .fbtnrow .btn { font-size:11px; padding:8px 5px; gap:4px; }
  .board .nbtnrow .btn svg, .board .fbtnrow .btn svg { width:14px; height:14px; }
  .board #sendsnippet { font-size:13px; padding:9px 12px; }
  .board #sendsnippet svg { width:16px; height:16px; }
  .snipactions .btn { font-size:12px; padding:7px 4px; }
  .snipactions .btn svg { width:13px; height:13px; }
  .frow .btn { font-size:11px; padding:7px 8px; }
  #sidebar .sbbtn { padding:8px 9px; font-size:12px; border-radius:8px; gap:7px; }
  #sidebar .sbbtn svg { width:15px; height:15px; }
  .msend .mbtn-primary, .msend .mbtn-secondary { font-size:14px; padding:9px; }
  /* The mobile "Choose files" folder svg had NO size rule, so
     it flexed to the leftover row width (72px in 2.8.7, 97px
     once padding shrank) -- pin it to the text scale. */
  .msend #msendfiles svg { width:18px; height:18px; flex:none; }
  .gloginbox .btn { font-size:14px; padding:10px; border-radius:8px; }
  .lkbox .btn { padding:10px; min-height:40px; font-size:13px; }
  .lkbox:not(.guestcard) .lkfolderrow { gap:10px; height:44px; }
  .lkbox:not(.guestcard) .lkfolderrow .btn { height:44px; min-height:44px; font-size:15px; gap:8px; }
  .lkbox:not(.guestcard) .lkfolderrow .btn svg { width:18px; height:18px; }
  .lkbox:not(.guestcard) .lkpwrow { align-items:center; }
  .lkbox:not(.guestcard) .lkpwrow .lkiconbtn { width:56px; height:44px; border-radius:8px; }
  .lkbox:not(.guestcard) .lkpwrow .lkiconbtn svg { width:19px; height:19px; }
  .lkbox:not(.guestcard) .lksavewrap .btn.primary { width:138px; height:42px; min-height:42px; font-size:16px; }
  .lkbox.guestcard .lksavewrap .btn.primary { width:150px; min-height:44px; font-size:15px; }
  .lkbox:not(.guestcard) #lkset svg { width:18px; height:18px; }
  .lkbox:not(.guestcard) .lkclosebtn { width:38px; height:38px; font-size:21px; border-radius:8px; }
  /* v2.8.9 (Essef Nov 4, 8:54 PM, 10 items). Every rule below
     sits last so it wins the cascade over the 2.8.8 sizes.
     (8) CURRENT-ADDRESS DROPDOWN ROOT CAUSE: the list lives
     INSIDE the .lkview field, and the 2.8.7 rule gave every host
     .lkview overflow:hidden -- so the absolutely-positioned
     list was clipped to the 52px field, and with no
     position:relative on the field it also anchored to the
     whole dialog (top:100% of .lkbox) instead of the field.
     Clicking only flipped the chevron; the menu never showed.
     Fix: the current-address field keeps its own positioning
     context and visible overflow, so the list drops from the
     field itself (the 2.8.7 open animation is untouched).
     The chevron grows 20px -> 28px, clearly visible. */
  .lkbox:not(.guestcard) .lkview.lkcurdd { overflow:visible; position:relative; }
  .lkcurdd .ddchev { font-size:28px; }
  /* (9) NOTICES SEPARATED: open stays yellow; locked is GREEN
     -- the checkbox-tick green #22c55e, translucent -- with
     readable light-green text (dark green on light theme).
     Small-pill size from 2.8.8 is unchanged. */
  .lklockedwarn { border:2px solid rgba(34,197,94,.55); color:#4ade80; background:rgba(34,197,94,.14); }
  html.light .lklockedwarn { color:#15803d; border-color:rgba(34,197,94,.6); background:rgba(34,197,94,.12); }
  @keyframes lockpulse { 0%,100% { box-shadow:0 0 0 0 rgba(34,197,94,.35); } 50% { box-shadow:0 0 0 6px rgba(34,197,94,0); } }
  /* (5) UNIFORM MAIN-PAGE BUTTONS: Shared Texts, Shared Files
     and the other main-page buttons share ONE size -- same
     height, same font, same padding -- instead of the 2.8.8
     spread (12px/11px/13px/14px). Set Up dialog buttons keep
     their own sizes (scoped .lkbox rules above). */
  .board .nbtnrow .btn, .board .fbtnrow .btn, .board #sendsnippet,
  .msend .mbtn-primary, .msend .mbtn-secondary {
    font-size:13px; padding:10px 12px; min-height:40px; gap:6px; }
  .board .nbtnrow .btn svg, .board .fbtnrow .btn svg,
  .board #sendsnippet svg { width:16px; height:16px; }
  /* (1) SEPARATE-FOLDERS TOGGLE beside the password eye/delete
     buttons (vertically centred on their row, to their right):
     an inline checkbox row, never above Permissions again.
     Guests never see it (host-only setting). */
  .lkbox:not(.guestcard) .lkpwrow .lksepinline { display:inline-flex; align-items:center; gap:8px; margin-left:14px; white-space:nowrap; font-size:15px; flex:none; }
  .lkbox.guestcard .lksepinline { display:none; }
  /* v2.8.35: Create Separate Folders MOVED under the Folder
     field (empty space above Open / Change Folder), with a
     small "i" saying what it does. Its old spot in the
     password row is now the Save Password checkbox, centred
     with the row. Guests see Save Password on their Connect
     card (wrapped below the password field) but never the
     separate-folders row. */
  .lkseprow { display:flex; align-items:center; gap:6px; margin-top:14px; }
  .lkseprow .lksepinline { display:inline-flex; align-items:center; gap:8px; white-space:nowrap; flex:none; }
  .lksepinfo { display:inline-flex; align-items:center; justify-content:center; width:22px; height:22px; border-radius:50%; border:1.5px solid #38bdf8; background:transparent; color:#38bdf8; cursor:pointer; padding:0; flex:none; }
  .lksepinfo svg { width:18px; height:18px; display:block; }
  .lkbox:not(.guestcard) .lkpwrow .lksavepwinline { display:inline-flex; align-items:center; gap:8px; margin-left:14px; white-space:nowrap; font-size:15px; flex:none; }
  .lkbox.guestcard .lkpwrow { flex-wrap:wrap; }
  .lkbox.guestcard .lksavepwinline { display:inline-flex; align-items:center; gap:8px; flex:0 0 100%; margin:10px 0 0; font-size:14px; white-space:nowrap; }
  .lkbox.guestcard .lkseprow { display:none !important; }
  /* (7) DESKTOP-ONLY file rows as hyperlinks: the .desktoplink
     class is added by JS only when the pywebview bridge is
     present (desktop app). Phone web / APK never get it, so
     their rows are untouched. Pointer cursor over a file, and
     the name underlines on hover like a link. */
  #files.desktoplink .frow { cursor:pointer; }
  #files.desktoplink .frow:hover .fname { text-decoration:underline; }
  /* v2.8.21 (B): the PC desktop app (pywebview bridge present)
     never scrolls sideways -- the page must fit the window
     width. .pcapp is added to <html> by JS only when the
     bridge is present (see markPcApp); plain browsers and
     phones never get it. */
  /* v2.8.35: the 2.8.34 half-height rule was WRONG about the
     board -- it assumed FOUR 340px columns wrapping to two
     rows at 721-1437px, but the Ask column is display:none
     on desktop, so only THREE columns ever show and they fit
     in ONE row from 1084px up (3x340 + 2x14 gap = 1048px).
     At 1084-1437px the half-height rule left the cards
     280px tall in an 800px window with ~350px of empty
     black below them and the footer stranded at the bottom
     (Essef's photo, Nov 6 ~11:22 PM PT). The half-height
     rule now applies ONLY where the three columns really
     wrap to two rows (721-1083px: 2 + 1); from 1084px up
     the base .col height calc(100dvh - 210px) fills the
     window again (cards end ~37px above the footer at every
     height). Nothing else changes: the Files tab keeps its
     own scroller, columns still scroll internally. */
  html.pcapp, html.pcapp body { overflow-x:hidden; overflow-y:hidden; }
  @media (min-width:721px){ html.pcapp body { padding-bottom:24px; } }
  /* v2.8.34 (8), <=720px (the desktop window's minimum size):
     the tabbed single column is calc(100dvh - 170px) (Send) /
     calc(100dvh - 205px) (other tabs) on top of a 60px top pad
     + 52px top bar + 10px gap + the mobile tab bar's 104px
     bottom pad, so the page ran a CONSTANT 56px (Send) / 21px
     (others) past the viewport at every height. The pill tabs
     are position:fixed and the column scrolls internally, so
     that bottom pad is dead space on the PC app -- 32px
     instead: Send fits with 16px spare at 720x600. */
  @media (max-width:720px){ html.pcapp body { padding-bottom:32px; } }
  @media (min-width:721px) and (max-width:1083px){
    html.pcapp .col { height:calc((100dvh - 240px)/2); min-height:190px; }
  }
  /* v2.8.37 (8): the menu now COVERS THE TOP BAR (Essef's
     latest word, superseding the 2.8.35 "menu below the title
     bar" rule and the 2.8.36 18px rule): top 0, z 1600 above
     the title bar (1500), 28px radius, navy. The full v2.8.37
     menu block lives with the other sidebar rules below. */
  html.pcapp.frameless #sidebar { top:0; z-index:1600; border-radius:28px; }
  html.pcapp.frameless .lockwrap { z-index:1700; }
  /* v2.8.33 (Essef Nov 6): CUSTOM THEMED TITLE BAR, PC app
     ONLY -- Design 4 (picked by Essef, supersedes Design 1):
     glossy, slightly see-through bar -- rgba(18,23,42,.85)
     + backdrop blur(8px), hairline rgba(255,255,255,.12)
     border instead of the blue underline, ROUND logo
     (border-radius:50% on the logo image), "Drop" in white,
     minimise / maximise-restore / close as full-height 46px
     strips right, close hovers red (#e81123, like Windows).
     The bar shows ONLY on the frameless PC app
     (html.pcapp.frameless, set by JS from the bridge's
     is_frameless) -- web, guests and the framed fallback keep
     the native bar and never see it. Fixed at the top (z 1500,
     above the sidebar drawer at z 80, so Close is always
     reachable); the body padding below shifts ALL app content
     down 44px so nothing is covered. Light mode keeps the same
     design in light colours (glassy white bar, dark text,
     hairline border). */
  #titlebar { display:none; }
  html.pcapp.frameless #titlebar { display:flex; position:fixed; top:0; left:0; right:0; height:44px; z-index:1500; align-items:center; background:rgba(18,23,42,.85); backdrop-filter:blur(8px); -webkit-backdrop-filter:blur(8px); border-bottom:1px solid rgba(255,255,255,.12); padding:0 0 0 14px; user-select:none; -webkit-user-select:none; }
  html.pcapp.frameless body { padding-top:70px; }
  @media (max-width:720px){ html.pcapp.frameless body { padding-top:60px; } }
  #titlebar .tb-drag { display:flex; align-items:center; gap:9px; flex:1 1 auto; min-width:0; height:100%; }
  #titlebar .tb-logo { width:22px; height:22px; display:block; border-radius:50%; }
  #titlebar .tb-name { font-size:14px; font-weight:600; letter-spacing:.3px; color:#ffffff; }
  #titlebar .tb-btns { display:flex; align-items:stretch; height:100%; flex:none; }
  #titlebar .tb-btn { width:46px; border:none; background:transparent; color:#cbd5e1; cursor:pointer; display:flex; align-items:center; justify-content:center; padding:0; }
  #titlebar .tb-btn:hover { background:rgba(255,255,255,.08); color:#fff; }
  #titlebar .tb-close:hover { background:#e81123; color:#fff; }
  #titlebar .tb-ic-restore { display:none; }
  #titlebar.maxed .tb-ic-max { display:none; }
  #titlebar.maxed .tb-ic-restore { display:block; }
  html.light.pcapp.frameless #titlebar { background:rgba(255,255,255,.85); backdrop-filter:blur(8px); -webkit-backdrop-filter:blur(8px); border-bottom:1px solid rgba(15,23,42,.12); }
  html.light #titlebar .tb-name { color:#0f172a; }
  html.light #titlebar .tb-btn { color:#475569; }
  html.light #titlebar .tb-btn:hover { background:rgba(15,23,42,.08); color:#0f172a; }
  html.light #titlebar .tb-close:hover { background:#e81123; color:#fff; }
  /* (10) SET PASSWORD POPUP, refined: wider clean card,
     prominent title (address highlighted by JS colour),
     captioned single field with the eye INSIDE the field,
     blue/purple gradient Save (never green). The red X close
     keeps the shared .lkclosebtn style. */
  .lockpwbox { width:min(420px,92vw); border-radius:18px; padding:30px 26px 24px; }
  .lockpwbox h4 { font-size:20px; margin-bottom:18px; }
  .lockpwbox h4 #lockpwaddr { font-weight:800; }
  .lockpwcap { display:block; font-size:12px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); margin:0 0 6px; text-align:left; }
  .lockpwfield { position:relative; }
  .lockpwfield input { width:100%; box-sizing:border-box; background:var(--card2); color:var(--txt); border:1px solid var(--line); border-radius:10px; padding:13px 48px 13px 14px; font-size:15px; font-family:inherit; }
  .lockpwfield input:focus { outline:none; border-color:var(--acc); }
  .lockpweye { position:absolute; right:6px; top:50%; transform:translateY(-50%); width:36px; height:36px; border:none; background:transparent; color:var(--muted); cursor:pointer; display:flex; align-items:center; justify-content:center; border-radius:8px; padding:0; }
  .lockpweye:hover { color:var(--txt); }
  .lockpweye svg { width:20px; height:20px; }
  .lockpwbox .lockpwsave { background:#277ff0; color:#ffffff; border:none; min-width:160px; padding:12px 28px; margin:16px auto 0; font-size:15px; font-weight:700; border-radius:10px; display:flex; align-items:center; justify-content:center; gap:4px; }
  .lockpwbox .lockpwsave svg { width:18px; height:18px; flex:none; }
  .lockpwbox .lockpwsave:hover { filter:brightness(1.12); border:none; }
  /* v2.8.30 (3): Set Password popup (Essef Nov 6, ~5:24 PM,
     photo 74452_2_cs3q.jpg) -- SAVE sat at the LEFT of the
     window and the PASSWORD label sat left with only a 6px
     gap to the field. (a) CENTRED: the SAVE button is
     inline-flex (see the #lkset/#lockpwsave/#msave rule
     below, ID specificity) so its margin:auto computed to
     0px -- measured 110px left of centre on 2.8.29. The
     #lockpwpop #lockpwsave selector (two IDs) beats that
     rule and restores block flex + auto margins, so the
     button is truly centred; the PASSWORD label centres
     too (its block spans the box). The one-space floppy
     gap (gap:4px, 2.8.29) and the red X are untouched.
     (b) SPACE under the password text: the label-to-field
     gap grows 6px -> 16px, and the field-to-SAVE gap grows
     (save margin-top 16px -> 24px), so the password area
     breathes before SAVE. (c) SLIGHTLY TRANSPARENT: the
     box background is rgba .93 in both modes (the h4's
     solid background goes transparent so no opaque strip
     shows through), plus a backdrop blur. (d) ANIMATED
     pop-in on open / pop-out on close (see closeLockPopup
     -- the .closing class holds the box visible for the
     .18s out-animation before .open is removed). */
  .lockpwbox { background:rgba(18,23,42,.93); backdrop-filter:blur(8px); -webkit-backdrop-filter:blur(8px); }
  html.light .lockpwbox { background:rgba(255,255,255,.93); }
  .lockpwbox h4, html.light .lockpwbox h4 { background:transparent; }
  .lockpwbox .lockpwcap { text-align:center; margin:0 0 16px; }
  #lockpwpop #lockpwsave { display:flex; margin:24px auto 0; }
  /* v2.8.37 (1): Save password checkbox in the Set Password
     popup -- centred under the field, above SAVE. DISABLED
     while the password field is empty; typing any character
     enables it live (input event, see openLockPopup). Checked
     + password -> locked + saved (hashed + retrievable copy);
     unchecked + password -> still locked, hash only
     ("Locked - No Saved Password" in history). */
  .lockpwbox .lockpwsavechk { display:flex; justify-content:center; margin:14px auto 0; font-size:14px; }
  .lockpwbox .lockpwsavechk input:disabled + .permbox { opacity:.45; }
  .lockpwbox .lockpwsavechk:has(input:disabled) { opacity:.55; cursor:default; }
  .lockpwpop.open .lockpwbox { animation:lockpwpopin .22s ease-out; }
  .lockpwpop.closing .lockpwbox { animation:lockpwpopout .18s ease-in forwards; }
  @keyframes lockpwpopin { from { opacity:0; transform:scale(.94) translateY(8px); } to { opacity:1; transform:scale(1) translateY(0); } }
  @keyframes lockpwpopout { from { opacity:1; transform:scale(1) translateY(0); } to { opacity:0; transform:scale(.94) translateY(8px); } }
  /* v2.8.10 (Essef Nov 4, 9:14 PM): (1) Set Up folder buttons use
     the FULL names again -- "Open Folder" / "Change Folder", as
     on the Files card and menu (2.8.9 one-word rename reverted
     for the Set Up dialog ONLY; Files tab + menu keep "Open" /
     "Change"). Full labels fit cleanly: 14px, nowrap, no clip.
     (2) Set Password title is ALL CAPS (HTML text). (3) Delete
     buttons unified to the darker red #f87171 -- the dark end
     of the X close icon / dangergrad gradient (was the lighter
     #f87171 solid / #ef4444 gradient end); white text/icons.
     The Set Up password-remove trash icon takes the same
     darker red so it reads as a delete action.
     v2.8.11 REVERTED this (Essef Nov 4, 10:19 PM): the darker
     red was worse; every darker-red value above is back to
     the lighter #f87171 (gradient end #ef4444).
     (gradient end #ef4444). */
  .lkbox:not(.guestcard) .lkfolderrow .btn { font-size:14px; padding:0 10px; white-space:nowrap; }
  .lkbox .lkiconbtn.danger { color:#ef4444; }
  /* v2.8.11 (Essef Nov 4, 10:19 PM):
     (1) MENU Main Folder buttons only: narrower than the card
     (76%, centred) -- the yellow-mark width in his screenshot;
     renamed "Open Folder" / "Change Folder" in the HTML above.
     Files card keeps "Open" / "Change"; Set Up already has the
     full names.
     (2) Menu Change Folder takes the Set Up dialog's purple
     gradient (#A78BFA -> #7C3AED); Open Folder keeps its blue.
     (3) Set Up Your Addresses window is slightly see-through:
     translucent background + backdrop blur; text and controls
     stay fully opaque and readable.
     (4) DELETE COLOUR REVERT: the 2.8.10 darker red #f87171 was
     worse -- all delete fills/icons are back to the pre-2.8.10
     lighter red #f87171 (gradient end #ef4444); see the global
     replacements below this block's rules.
     (9) Permission-greyed buttons are dimmer: .deloff .45 -> .25.
     (14) Smaller X on the Set Password window + the new
     address-removal window (24px, was 32px).
     (15) Both Save buttons match Send Text / Add New: solid
     app blue #277ff0, white text. */
  #sbopen, #sbchange { display:flex; align-items:center; justify-content:center; width:76%; margin:8px auto 0; }
  #sbopen svg, #sbchange svg { flex:none; width:17px; height:17px; margin-right:8px; }
  /* v2.8.17: the 2.8.14 left-shift rules for the Change Folder
     icons are REMOVED with the icon revert (a) -- they only
     compensated for the changed icon's width. */
  #sbchange { background:linear-gradient(135deg,#8B5CF6,#6D28D9); color:#ffffff; border:none; }
  .lkbox:not(.guestcard) { background:rgba(18,23,42,.88); backdrop-filter:blur(14px); -webkit-backdrop-filter:blur(14px); }
  html.light .lkbox:not(.guestcard) { background:rgba(255,255,255,.88); backdrop-filter:blur(14px); -webkit-backdrop-filter:blur(14px); }
  .lockpwbox .lkclosebtn { width:24px; height:24px; font-size:15px; border-radius:7px; }
  /* v2.8.11 in-page file preview (web + desktop pywebview):
     click a file row -> preview window; Download stays a
     separate explicit action. Same themed card as the Set
     Password window, dark + light. */
  .previewpop { display:none; position:fixed; inset:0; z-index:1001; align-items:center; justify-content:center; background:rgba(3,5,10,.6); padding:16px; }
  .previewpop.open { display:flex; }
  .previewbox { position:relative; width:min(680px,94vw); max-height:86vh; display:flex; flex-direction:column; background:#12172a; border:1px solid #2a3560; border-radius:18px; padding:20px 22px; box-shadow:0 24px 60px rgba(0,0,0,.5); }
  html.light .previewbox { background:#ffffff; border-color:#c3cfde; box-shadow:0 24px 60px rgba(15,23,42,.25); }
  .previewbox h4 { font-size:16px; margin:0 0 4px; padding-right:28px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .previewbox .pvsub { color:var(--muted); font-size:12.5px; margin-bottom:12px; }
  .previewbox .pvclose { position:absolute; top:10px; right:12px; width:24px; height:24px; font-size:15px; border-radius:7px; background:linear-gradient(135deg,#ef4444,#e11d48); border:1px solid #ef4444; color:#fff; display:inline-flex; align-items:center; justify-content:center; cursor:pointer; line-height:1; padding:0; }
  .previewbox .pvbody { overflow:auto; min-height:120px; max-height:calc(86vh - 170px); border:1px solid var(--line); border-radius:12px; padding:12px; background:var(--card2); }
  .previewbox .pvbody img { max-width:100%; display:block; margin:0 auto; border-radius:8px; }
  .previewbox .pvbody pre { white-space:pre-wrap; word-break:break-word; font-size:13.5px; line-height:1.55; margin:0; font-family:ui-monospace,Menlo,Consolas,monospace; }
  .previewbox .pvbody embed, .previewbox .pvbody iframe { width:100%; height:52vh; border:none; border-radius:8px; background:#fff; }
  .previewbox .pvbody video, .previewbox .pvbody audio { width:100%; }
  .previewbox .pvmsg { color:var(--muted); font-size:14px; line-height:1.6; text-align:center; padding:28px 12px; }
  .previewbox .pvrow { display:flex; gap:10px; margin-top:14px; justify-content:flex-end; }
  .previewbox .pvrow .btn { padding:10px 18px; }
  .previewbox .pvdl { background:#277ff0; color:#fff; border:none; }
  /* v2.8.36 (7): web preview Download button animates into
     Open on a successful download -- short fade/scale flip.
     Discard / reject / failure leaves it reading Download. */
  .previewbox .pvdl.pvdlswap { animation:pvdlflip .38s ease; }
  @keyframes pvdlflip { 0% { opacity:1; transform:scale(1); } 45% { opacity:0; transform:scale(.86); } 55% { opacity:0; transform:scale(1.06); } 100% { opacity:1; transform:scale(1); } }
  /* v2.8.24 (1): light mode -- white Download text on the
     #277ff0 fill is only 3.9:1, and the light .btn rule used
     to paint the whole button white (white on white). The
     darker #1e6ad8 fill reads ~5.1:1 against white text. */
  html.light .previewbox .pvdl { background:#1e6ad8; color:#fff; }
  /* v2.8.21 (A): picture/video FIT VIEW -- the whole picture or
     video is visible without scrolling, on a bigger box, not a
     zoomed-out immersive view. Only image/video previews get
     the .fitmedia class (see previewFile); PDF / Word / text
     keep their scrolling preview untouched. The media's
     max-height is in vh units (never a % of the auto-height
     body), so it always fits the box with its padding. */
  .previewpop.fitmedia .previewbox { width:min(1400px,96vw); max-height:96vh; }
  .previewpop.fitmedia .previewbox .pvbody { overflow:hidden; display:flex; align-items:center; justify-content:center; max-height:calc(96vh - 170px); }
  .previewpop.fitmedia .previewbox .pvbody img, .previewpop.fitmedia .previewbox .pvbody video { flex:none; width:auto; height:auto; max-width:100%; max-height:calc(96vh - 196px); object-fit:contain; }
  /* v2.8.22 (3): picture previews HUG the picture -- the 2.8.21
     fit box was a fixed 1080px wide for EVERY picture, so a
     small picture sat in a wide empty window. .fitpic (images
     only; video keeps .fitmedia) sizes the window to the
     picture (JS sets the box width from the displayed image
     size), shows the picture slightly bigger (up to 1.25x
     natural, clamped to the viewport), and makes the window
     translucent -- a translucent background, not element
     opacity, so the title and buttons stay
     fully opaque and readable. PDF / Word / text
     keep their own sizing below.
     v2.8.24 (1): LESS transparent than 2.8.23 -- the box is
     rgba(18,23,42,.85) dark / rgba(255,255,255,.92) light
     (was .5 / .55); the page behind it barely shows through.
     v2.8.29 (1): ZOOM IS GONE (Essef Nov 6) -- the "- 100% +
     Fit" controls, click-to-zoom and wheel zoom are removed
     from the preview on web and the PC app. The preview keeps
     its fit view (whole picture visible, no scrolling) in a
     FIXED window: the box size is set once on load from the
     fit size and never changes, so the buttons stay put. */
  .previewpop.fitpic { background:rgba(3,5,10,.35); }
  .previewpop.fitpic .previewbox { width:auto; max-width:min(1400px,96vw); background:rgba(18,23,42,.85); border-color:rgba(42,53,96,.6); }
  html.light .previewpop.fitpic .previewbox { background:rgba(255,255,255,.92); border-color:rgba(195,207,222,.7); }
  .previewpop.fitpic .previewbox .pvbody { overflow:hidden; display:flex; flex:1 1 auto; min-height:0; align-items:center; justify-content:center; max-height:calc(96vh - 170px); padding:4px; }
  .previewpop.fitpic .previewbox .pvbody img { flex:none; width:auto; height:auto; max-width:100%; max-height:calc(96vh - 180px); object-fit:contain; }
  /* v2.8.23 (2): video previews HUG the video too -- the 2.8.21
     fit box was a fixed 1080px for EVERY video, so a portrait
     video sat as a narrow strip in a wide empty window. .fitvid
     (video only; pictures keep .fitpic) sizes the window to the
     video -- JS sets the box width from the displayed video
     size, same as pictures -- and makes the window VERY
     transparent like .fitpic (title / controls stay opaque).
     The video is also bigger: up to 96vh tall (was 92vh) and
     up to 1.5x natural, clamped to the viewport, so it still
     fits with no scrolling. Audio keeps the plain player. */
  .previewpop.fitvid { background:rgba(3,5,10,.35); }
  .previewpop.fitvid .previewbox { width:auto; max-width:min(1400px,96vw); background:rgba(18,23,42,.85); border-color:rgba(42,53,96,.6); }
  html.light .previewpop.fitvid .previewbox { background:rgba(255,255,255,.92); border-color:rgba(195,207,222,.7); }
  .previewpop.fitvid .previewbox .pvbody { overflow:hidden; display:flex; align-items:center; justify-content:center; max-height:calc(96vh - 170px); padding:4px; }
  .previewpop.fitvid .previewbox .pvbody video { flex:none; width:auto; height:auto; max-width:100%; max-height:calc(96vh - 180px); object-fit:contain; }
  /* v2.8.29 (1): zoom controls removed (see above) -- no
     .pvzoom rules remain; the preview row is Close + Download
     only, and the picture never zooms (no buttons, no click,
     no wheel). */
  /* v2.8.22 (8): text-based previews are BIGGER too -- PDF,
     Word, Excel and text used the small 680px box while
     pictures got the 1080px fit box. .fittext gives them the
     same big window (1080px / 92vh) with a taller body, a
     taller PDF embed and larger text, so the contents are
     clearly visible. Behaviour is otherwise unchanged: PDF
     still embeds, Word still renders, text still scrolls. */
  .previewpop.fittext .previewbox { width:min(1080px,96vw); max-height:92vh; }
  .previewpop.fittext .previewbox .pvbody { max-height:calc(92vh - 170px); }
  .previewpop.fittext .previewbox .pvbody embed, .previewpop.fittext .previewbox .pvbody iframe { height:calc(92vh - 210px); }
  .previewpop.fittext .previewbox .pvbody pre { font-size:15px; line-height:1.6; }
  .previewpop.fittext .previewbox .docxview { font-size:16px; }
  .previewpop.fittext .previewbox .xlsxview { font-size:15px; line-height:1.5; }
  .previewpop.fittext .previewbox .xlsxview table { border-collapse:collapse; }
  .previewpop.fittext .previewbox .xlsxview td, .previewpop.fittext .previewbox .xlsxview th { border:1px solid var(--line); padding:7px 10px; text-align:left; }
  .previewpop.fittext .previewbox .xlsxview th { background:var(--card2); }
  /* v2.8.23 (1): the Excel window HUGS its table -- the 2.8.22
     .fittext window was a fixed 1080px even for a 2-column
     sheet, so a tiny table sat in a wide empty window. .fitxlsx
     (added by JS once the table renders) lifts the fixed 1080px
     width; JS sets the exact box width from the rendered table
     (table + 70px chrome, min 480px, max 1080px). PDF / Word /
     text keep the big .fittext box. */
  .previewpop.fittext.fitxlsx .previewbox { width:auto; max-width:min(1080px,96vw); }
  /* v2.8.33 (5): on the frameless PC app the preview must sit
     ENTIRELY below the 44px custom title bar -- never under it.
     The overlay covers the full viewport (inset:0) at z 1001,
     BELOW the bar's z 1500, so a tall centred preview box
     (96vh) started ~16px from the top and its top edge, its
     red X and its scrollbar track all ran up behind the bar
     (Essef's Nov 6 photo: the scroller disappears under the
     blue title-bar line). The overlay now starts at top:44px
     on frameless, and every vh-based cap in the preview loses
     the same 44px, so no part of the window -- box, title row,
     X, Close/Download row, or any scroll area (text / PDF /
     .xlsx / saved-file viewer) -- can reach above the bar.
     Web (no title bar) is untouched: these rules are all
     scoped html.pcapp.frameless. */
  html.pcapp.frameless .previewpop { top:44px; }
  html.pcapp.frameless .previewpop .previewbox { max-height:calc(86vh - 44px); }
  html.pcapp.frameless .previewpop .previewbox .pvbody { max-height:calc(86vh - 214px); }
  html.pcapp.frameless .previewpop.fitmedia .previewbox { max-height:calc(96vh - 44px); }
  html.pcapp.frameless .previewpop.fitmedia .previewbox .pvbody { max-height:calc(96vh - 214px); }
  html.pcapp.frameless .previewpop.fitmedia .previewbox .pvbody img,
  html.pcapp.frameless .previewpop.fitmedia .previewbox .pvbody video { max-height:calc(96vh - 224px); }
  html.pcapp.frameless .previewpop.fitpic .previewbox .pvbody img { max-height:calc(96vh - 224px); }
  html.pcapp.frameless .previewpop.fitvid .previewbox .pvbody video { max-height:calc(96vh - 224px); }
  html.pcapp.frameless .previewpop.fittext .previewbox { max-height:calc(92vh - 44px); }
  html.pcapp.frameless .previewpop.fittext .previewbox .pvbody { max-height:calc(92vh - 214px); }
  html.pcapp.frameless .previewpop.fittext .previewbox .pvbody embed,
  html.pcapp.frameless .previewpop.fittext .previewbox .pvbody iframe { height:calc(92vh - 254px); }
  html.pcapp.frameless .viewer { top:44px; }
  html.pcapp.frameless .viewer .vbox { max-height:calc(88vh - 44px); }
  html.pcapp.frameless .viewer #vcontent img,
  html.pcapp.frameless .viewer #vcontent video { max-height:calc(88vh - 144px); }
  /* v2.8.24 (4): text previews are SELECTABLE -- the cursor
     is the I-beam over rendered text (text files, Word,
     Excel tables) and the text can be selected + copied
     (the 2.8.22 right-click Copy / Select All menu still
     applies). The PDF <embed> keeps its native behaviour. */
  .previewpop.fittext .previewbox .pvbody pre, .previewpop.fittext .previewbox .docxview, .previewpop.fittext .previewbox .xlsxview { cursor:text; user-select:text; -webkit-user-select:text; }
  /* v2.8.33 (8): archive listing view -- .zip / .rar contents
     inside the preview window (see previewFile). Plain rows,
     folder icon + name left, size right; same text scale as the
     Excel table view. */
  .archview { font-size:14px; }
  .archrow { display:flex; gap:10px; padding:6px 4px; border-bottom:1px solid var(--line); align-items:baseline; }
  /* v2.8.34 (4): file rows inside an archive preview are
     clickable (they open that one file directly); folders
     are not (no data-entry, no pointer). */
  .archrow[data-entry] { cursor:pointer; }
  .archrow[data-entry]:hover .archname { text-decoration:underline; }
  .archrow:last-child { border-bottom:none; }
  .archname { flex:1 1 auto; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .archsize { flex:none; color:var(--muted); font-size:12.5px; white-space:nowrap; }
  /* v2.8.11 address-removal prompt: same themed card as the
     Set Password window (dark + light), two checkboxes. */
  .addrrempop { display:none; position:fixed; inset:0; z-index:130; align-items:center; justify-content:center; background:rgba(3,5,10,.5); padding:16px; }
  .addrrempop.open { display:flex; }
  .addrrembox { position:relative; width:min(420px,92vw); background:#12172a; border:1px solid #2a3560; border-radius:18px; padding:30px 26px 24px; box-shadow:0 16px 40px rgba(0,0,0,.35); }
  html.light .addrrembox { background:#ffffff; border-color:#c3cfde; box-shadow:0 16px 40px rgba(15,23,42,.25); }
  .addrrembox h4 { font-size:16px; margin-bottom:8px; text-align:center; line-height:1.4; padding:0 24px; }
  .addrrembox .addrremsub { color:var(--muted); font-size:13.5px; text-align:center; margin:0 0 16px; }
  .addrrembox .addrremchk { padding:10px 4px; }
  .addrrembox .addrremchk input:disabled + .permbox { opacity:.4; }
  .addrrembox .addrremhint { color:var(--muted); font-size:12.5px; margin:6px 4px 0; }
  .addrrembox .addrremrow { display:flex; gap:10px; margin-top:18px; }
  .addrrembox .addrremrow .btn { flex:1; padding:11px; display:inline-flex; align-items:center; justify-content:center; gap:6px; }
  /* v2.8.36 (6): the Delete button carries the same trash icon
     as the other Delete buttons (see SVG.del). */
  .addrrembox .addrremrow .btn svg { width:16px; height:16px; flex:none; }
  .addrrembox .addrremsave { background:#ef4444; color:#fff; border:none; }
  /* v2.8.10 ALIGNMENT AUDIT (Essef Nov 4, 9:19 PM): rendered
     measurement showed the Texts row growing to 53px when the
     sidebar is open: at 13px / 10px 12px padding, "Add New"
     (icon 16 + gap 6 + text ~56px + padding 24px = ~102px)
     wraps in its ~95px flex share, stretching the whole row.
     Main-page row buttons (Texts + Files) now share ONE fit:
     12px, 10px 8px padding, 5px gap, 14px icons, nowrap, so
     every label stays on one line and every row is exactly
     40px tall (min-height 40 from the 2.8.9 uniform rule).
     Send Text joins the same 12px / 15px-icon size so the
     main-page buttons align as one family. */
  .board .nbtnrow .btn, .board .fbtnrow .btn { font-size:12px; padding:10px 8px; gap:5px; white-space:nowrap; }
  .board .nbtnrow .btn svg, .board .fbtnrow .btn svg { width:14px; height:14px; }
  .board #sendsnippet { font-size:12px; }
  .board #sendsnippet svg { width:14px; height:14px; }
  /* v2.8.12 (Essef Nov 4, 11:14 PM):
     (1) MENU folder buttons CENTRED: #sidebar .sbbtn sets
     display:inline-flex, which beats the 2.8.11 #sbopen rule
     on display (1,1,0 > 1,0,0) -- inline-level boxes ignore
     auto margins, so the buttons sat left-aligned (x=27 in
     the rendered 2.8.11 sidebar, measured) instead of centred.
     #sidebar #sbopen/#sbchange (2,0,0) restores display:flex
     so width:76% + auto margins centre them; nowrap keeps the
     full "Change Folder" label on one line. The label itself
     is fixed in paintSeparateFolders (it rewrote the 2.8.11
     HTML rename back to "Change" on every paint).
     (2) Remove Address modal ON TOP: .addrrempop was z-index
     130, BELOW the Set Up backdrop (.lockwrap, 300), so it
     rendered behind Set Up. Now 4000 (above lockwrap 300,
     qrpop 300, aipop 1000, aimodalwrap 1001, hovertip 2000;
     toast stays 5000). Its X is now a visible coloured
     bordered button at the top-right (32px, new delete-red
     gradient + border), replacing the 2.8.11 24px plain X
     that sat in-flow at the top-left.
     (3) Set Password line one step down: .lockpwbox h4 gets
     margin-top:8px only -- nothing else resized.
     (4) Delete/disconnect redder: the in-between red #ef4444
     (solid) / gradient #ef4444 -> #e11d48 -- redder than the
     reverted lighter red, still short of the rejected 2.8.10
     darker red (which stays out of live code).
     (11) "Create Separate Folders" lives in its own menu
     card below the address card now (HTML move; the Main
     Folder card shrinks by that row, no CSS needed).
     (12) Drop logo before the "Drop" text: .sblogo in the
     menu header + the guest-login wordmark (.glogo img).
     The artwork is Essef's fixed logo, served as /logo.png
     (resize-and-fit only, never redrawn).
     (13) Preview Download greys via the shared .deloff
     class (see previewFile); no CSS of its own needed. */
  #sidebar #sbopen, #sidebar #sbchange { display:flex; align-items:center; justify-content:center; width:76%; margin:8px auto 0; white-space:nowrap; }
  /* v2.8.37 (8): MENU REDESIGN from Essef's HTML + target
     screenshot (Nov 7) -- dark navy throughout: outer #090D16,
     cards #0F172A, borders #1E293B; outer container rounded
     28px, cards rounded 16px. The menu COVERS THE TOP BAR on
     the frameless PC app (top:0, z 1600 above the title bar --
     supersedes the 2.8.35 "menu below the title bar" rule) and
     its border runs all the way to the bottom, ending rounded.
     Same navy in the dark theme; v2.8.38 (6) adds the light
     variant (html.light #sidebar rules below) -- same layout,
     light colours. Every menu text colour is set explicitly so
     light mode cannot wash it out. Contents, order and all
     buttons/switches are unchanged -- ONLY the look. */
  #sidebar { background-color:#090D16; background-image:radial-gradient(140px 140px at 90% -20px, rgba(37,99,235,.14), transparent 70%), radial-gradient(140px 140px at -20% 105%, rgba(139,92,246,.12), transparent 70%); border:1px solid #1E293B; border-radius:28px; padding:24px 20px; width:292px; }
  /* v2.8.38 (6): the menu now HAS a light theme -- same layout,
     light colours, readable text/icons. Dark theme untouched
     (the navy rules above still own it). */
  html.light #sidebar { background-color:#ffffff; background-image:radial-gradient(140px 140px at 90% -20px, rgba(37,99,235,.08), transparent 70%), radial-gradient(140px 140px at -20% 105%, rgba(139,92,246,.07), transparent 70%); border-color:#c3cfde; }
  html.light #sidebar .sbtitle { color:#0f172a; }
  html.light #sidebar .sbver { color:#64748b; }
  html.light #sidebar .sbcard { background:#f1f5f9; border-color:#c3cfde; }
  html.light #sidebar .sbcard .sbsec { color:#475569; }
  html.light #sidebar #sblink, html.light #sidebar #sbaddr { color:#0f172a; }
  html.light #sidebar .sblockbtn { border-color:rgba(100,116,139,.5); background:rgba(226,232,240,.7); color:#475569; }
  html.light #sidebar .sblockbtn:hover { background:rgba(203,213,225,.8); color:#0f172a; }
  html.light #sidebar .sblockbtn.locked { color:#b45309; border-color:#f59e0b; background:rgba(245,158,11,.14); }
  html.light #sidebar .sbrow { color:#0f172a; }
  html.light #sidebar .sbsw { background:#cbd5e1; }
  html.light #sidebar .sbsw.on { background:#38bdf8; }
  html.light #sidebar .sblogotile .sblogo { background:#ffffff; }
  html.light #sidebar .themesw { background:#f1f5f9; border-color:#cbd5e1; }
  #sidebar .sbhead { display:flex; align-items:center; gap:12px; margin-bottom:24px; }
  #sidebar .sblogotile { flex:none; width:48px; height:48px; border-radius:16px; background:linear-gradient(135deg,#2563EB,#22d3ee); padding:2px; display:flex; align-items:center; justify-content:center; box-shadow:0 8px 24px rgba(37,99,235,.35); }
  #sidebar .sblogotile .sblogo { width:100%; height:100%; object-fit:cover; border-radius:14px; background:#090D16; display:block; }
  #sidebar .sbtitle { font-size:24px; font-weight:800; color:#ffffff; background:none; -webkit-background-clip:initial; background-clip:initial; }
  #sidebar .sbver { font-size:12px; font-weight:600; color:#64748b; }
  #sidebar .sbcard { background:#0F172A; border:1px solid #1E293B; border-radius:16px; padding:16px; margin-bottom:16px; }
  #sidebar .sbcard .sbsec { font-size:11px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; color:#94a3b8; margin:0 0 12px; }
  #sidebar .sblinkrow { border:none; background:transparent; padding:0; }
  #sidebar #sblink, #sidebar #sbaddr { font-size:14px; font-weight:700; color:#f1f5f9; }
  #sidebar .addot { background:#f59e0b !important; width:12px; height:12px; animation:sbping 2s ease-out infinite; }
  @keyframes sbping { 0% { box-shadow:0 0 0 0 rgba(245,158,11,.45); } 70% { box-shadow:0 0 0 7px rgba(245,158,11,0); } 100% { box-shadow:0 0 0 0 rgba(245,158,11,0); } }
  #sidebar .sblockbtn { flex:none; width:36px; height:36px; border-radius:12px; border:1px solid rgba(51,65,85,.6); background:rgba(30,41,59,.4); color:#cbd5e1; cursor:pointer; display:flex; align-items:center; justify-content:center; }
  #sidebar .sblockbtn:hover { background:rgba(51,65,85,.5); color:#ffffff; }
  #sidebar .sblockbtn.locked { color:#f59e0b; border-color:#f59e0b; background:rgba(245,158,11,.12); }
  #sidebar .sblockbtn svg { width:12px; height:12px; }
  #sidebar .sbrow { display:flex; align-items:center; justify-content:space-between; padding:0; font-size:14px; font-weight:700; color:#f1f5f9; }
  #sidebar .sbrow + .sbrow { margin-top:16px; }
  #sidebar .sbsw { width:48px; height:24px; border-radius:999px; background:#1e293b; position:relative; cursor:pointer; flex:none; transition:background .25s; }
  #sidebar .sbsw .sbknob { position:absolute; top:2px; left:2px; width:20px; height:20px; border-radius:50%; background:#fff; transition:left .25s; box-shadow:0 1px 4px rgba(0,0,0,.35); }
  #sidebar .sbsw.on { background:#38bdf8; }
  #sidebar .sbsw.on .sbknob { left:26px; }
  #sidebar #sbopen, #sidebar #sbchange, #sidebar #sbdisconnect { display:flex; align-items:center; justify-content:center; width:100%; margin:10px 0 0; padding:12px; border-radius:12px; font-size:14px; font-weight:700; color:#ffffff; border:none; white-space:nowrap; }
  /* v2.8.40 (1): the menu Disconnect is the SAME SIZE as the D
     menu Change Folder button (216x40 on PC web). The button is
     a direct child of #sidebar -- NOT inside a card -- so the
     shared rule's width:100% would span the whole sidebar
     (250px). The card inset is 17px a side (16px card padding
     + 1px border), so the same 17px margins plus
     width:calc(100% - 34px) land it exactly on the card
     buttons' box. width:auto does NOT work here: a <button>
     shrink-to-fits on width:auto, which measured 99.5px. */
  #sidebar #sbdisconnect { width:calc(100% - 34px); margin:10px 17px 0; }
  #sidebar #sbopen { margin-top:0; background:linear-gradient(90deg,#2563EB,#3B82F6); box-shadow:0 4px 14px rgba(37,99,235,.30); }
  #sidebar #sbchange { background:linear-gradient(90deg,#9333EA,#4F46E5); box-shadow:0 4px 14px rgba(147,51,234,.30); }
  #sidebar #sbopen:hover, #sidebar #sbchange:hover { filter:brightness(1.12); }
  #sidebar #sbopen svg, #sidebar #sbchange svg { width:16px; height:16px; flex:none; }
  #sidebar .themesw { transform:none; width:76px; height:32px; background:#020617; border:1px solid #1e293b; }
  #sidebar .themesw .tsmoon { color:#22d3ee; }
  #sidebar .themesw .tssun { color:#f59e0b; }
  #sidebar .themesw .tsknob { border-color:#38bdf8; background:rgba(56,189,248,.18); }
  html.pcapp #sidebar { width:264px; overflow-y:hidden; padding:16px 14px; }
  html.pcapp #sidebar .sbhead { margin-bottom:16px; }
  html.pcapp #sidebar .sbcard { margin-bottom:10px; padding:12px; }
  html.pcapp.frameless #sidebar { top:0; z-index:1600; border-radius:28px; }
  .addrrempop { z-index:4000; }
  /* v2.8.35: connecting popup -- one small centred box for the
     three connect states (connecting / connected / failed).
     Replaces the inline connecting/disconnected status text on
     the login/connect screen; the main-screen Devices pill is
     untouched. */
  .connpop { display:none; position:fixed; inset:0; z-index:5000; align-items:center; justify-content:center; background:rgba(3,5,10,.45); padding:16px; }
  .connpop.open { display:flex; }
  .connbox { width:min(360px,92vw); background:#12172a; border:1px solid #2a3560; border-radius:18px; padding:28px 24px 22px; box-shadow:0 16px 40px rgba(0,0,0,.35); text-align:center; }
  /* v2.8.36 (9): the CONNECTED popup is ONE small box -- the
     green icon + "Connected to <address>" centred inside it,
     smaller than the connecting / failed box (unchanged). */
  .connpop.small .connbox { width:min(280px,88vw); padding:20px 18px 16px; }
  .connpop.small .connic { min-height:44px; margin-bottom:8px; }
  .connpop.small .connic svg { width:40px; height:40px; }
  .connpop.small .conntext { font-size:14px; }
  html.light .connbox { background:#ffffff; border-color:#c3cfde; box-shadow:0 16px 40px rgba(15,23,42,.25); }
  .connic { min-height:52px; display:flex; align-items:center; justify-content:center; margin-bottom:12px; }
  .connspin { width:44px; height:44px; border-radius:50%; border:4px solid rgba(39,127,240,.25); border-top-color:#277ff0; animation:connspin .8s linear infinite; }
  @keyframes connspin { to { transform:rotate(360deg); } }
  .conntext { font-size:15px; line-height:1.45; margin:0; }
  .connbox .btn { margin-top:16px; padding:9px 22px; }
  .addrrembox .lkclosebtn { position:absolute; top:10px; right:12px; width:32px; height:32px; font-size:20px; border-radius:9px; background:linear-gradient(135deg,#ef4444,#e11d48); border:1px solid #ef4444; color:#fff; display:inline-flex; align-items:center; justify-content:center; line-height:1; padding:0; box-shadow:0 2px 8px rgba(239,68,68,.35); cursor:pointer; }
  .lockpwbox h4 { margin-top:8px; }
  .sbhead { align-items:center; }
  .sblogo { height:28px; width:auto; flex:none; }
  .glogo { display:flex; align-items:center; justify-content:center; gap:10px; }
  .glogo img { height:38px; width:auto; flex:none; }
  /* v2.8.13 guest "Connect To A PC" modal alignment (Essef Nov 5,
     mobile web, light theme). All rules scoped .guestcard so the
     host Set Up dialog is untouched.
     (1) X IN THE TOP-RIGHT CORNER, NOT ON THE HEADER: the
     2.8.13 fix centred the X on the purple .guestcardhead
     (top:50px), but the header text spans the full header
     width, so the X sat ON the subtitle ("...Drop window"
     cut off behind it -- measured: X rect fully inside the
     header-text rect). Now the X sits in its own corner row
     at the card's top-right (top:10px right:12px, the base
     rule's spot) and the header is pushed down (margin-top
     4px -> 20px) so its top edge (26px card padding + 20px
     = 46px) clears the X's bottom edge (10+32=42px) with
     4px to spare -- the X overlaps no text at all.
     (2) PASSWORD FIELD WIDTH: the Address field was narrower
     than the Password row because .lknewcol (the Address field's
     column) had no flex-grow — it sized to content while the
     password row stretched full width. .lknewcol now grows, so
     the Address field spans the full width; and the eye button
     moves INSIDE the password field (like the Set Password
     popup), so the password input box itself ends at the same
     right edge as the Address field — same width, same edges.
     (3) PERMISSIONS REMOVED: paintPermissions() hides the grid
     for guests but never hid the "Permissions" label + i icon,
     leaving it orphaned in the guest modal. Hidden here.
     (4) General alignment: labels/fields/Save already share the
     card's 24px side padding once (1) and (2) land; nothing else
     moved. */
  .lkbox.guestcard .lkclosebtn { top:10px; right:12px; }
  .lkbox.guestcard .guestcardhead { margin-top:20px; }
  .lkbox.guestcard .lktopline .lknewcol { flex:1 1 auto; min-width:0; }
  .lkbox.guestcard .lkpwrow { position:relative; }
  .lkbox.guestcard .lkpwrow input { padding-right:48px; }
  .lkbox.guestcard .lkpwrow .lkiconbtn { position:absolute; right:8px; top:50%; transform:translateY(-50%); width:36px; height:36px; min-height:0; background:transparent; border:none; box-shadow:none; }
  .lkbox.guestcard .lkpermlabel { display:none; }
  /* v2.8.14 Save text alignment (guestcard ONLY): the floppy
     was translateY(3px), so its centre sat 1.5px below the
     button centre while the text sat on the centre line
     (measured). The guest Save is now a centred flex row
     with the icon transform removed, so icon and text share
     one clean centre line. The host Save keeps its
     3px-lower floppy -- this rule is guestcard-scoped. */
  .lkbox.guestcard #lkset { display:inline-flex; align-items:center; justify-content:center; gap:4px; line-height:1; }
  .lkbox.guestcard #lkset svg { transform:none; }
  /* v2.8.13 Save buttons: SOLID BLUE + a bit smaller. The guest
     Connect Save was PURPLE (#7c3aed) — now solid #277ff0 like
     the other buttons. Host Save was already solid blue; both
     shrink slightly. The Set Password Save was already solid
     blue #277ff0, so it only shrinks slightly too. */
  .lkbox.guestcard .btn.primary { background:#277ff0; }
  .lkbox:not(.guestcard) .lksavewrap .btn.primary { width:126px; height:38px; min-height:38px; font-size:15px; }
  .lkbox.guestcard .lksavewrap .btn.primary { width:136px; min-height:40px; font-size:14px; }
  .lockpwbox .lockpwsave { min-width:146px; padding:10px 24px; }
  /* v2.8.15 GUESTCARD FOLDER-BUTTON HOTFIX (Essef Nov 5, 1:45 AM,
     mobile web "Connect To A PC" modal): the Open/Change Folder
     buttons rendered as GIANT squares with enormous folder icons,
     overlapping the New Address field, "Change" cut off. ROOT
     CAUSE: every .lkfolderrow .btn svg size rule was scoped
     :not(.guestcard) (host dialog only, 18-22px), so in the
     guest card the SVGs had NO size at all and rendered at
     their huge default size, blowing the buttons up to ~200px
     tall -- the same class of bug as the 2.8.8 mobile
     Choose-files folder icon (72-97px). FIX: pin the icons
     unscoped (18px, so host + guest both get it; the host's
     later :not(.guestcard) rules still win for the host by
     specificity), pin the guest buttons to 44px with overflow
     hidden, and stack the guest top line vertically under
     480px so the buttons can never overlap the New Address
     field. The password eye in the same modal is pinned to
     20px in its normal text colour, and the guest's
     remove-password button (already hidden for guests by JS)
     is hidden in CSS too, so it can never stack on top of
     the eye and look red/broken. */
  .lkbox .lkfolderrow .btn svg { width:18px; height:18px; flex:none; }
  .lkbox.guestcard .lkfolderrow { height:44px; }
  .lkbox.guestcard .lkfolderrow .btn { height:44px; min-height:44px; display:inline-flex; align-items:center; justify-content:center; gap:8px; overflow:hidden; white-space:nowrap; font-size:14px; padding:0 12px; }
  /* v2.8.37 (6a): the eye sits INSIDE the password field,
     vertically centred on the INPUT -- the old top:50% was
     50% of the whole .lkpwrow, whose height includes the
     Save Password label wrapped below the field, so the eye
     landed ~30px low, straddling the field's bottom edge
     (Essef's photo). The input is pinned to 48px tall here,
     so top:24px is the input's exact centre at every width. */
  .lkbox.guestcard .lkpwrow input { height:48px; }
  .lkbox.guestcard .lkpwrow #lkpweye { position:absolute; right:8px; top:24px; transform:translateY(-50%); width:36px; height:36px; min-height:0; background:transparent; border:none; box-shadow:none; color:var(--txt); }
  .lkbox.guestcard .lkpwrow #lkpweye svg { width:20px; height:20px; }
  .lkbox.guestcard .lkpwrow #lkremovepwbtn { display:none; }
  @media (max-width:480px) {
    .lkbox.guestcard { width:min(400px,94vw); }
    .lkbox.guestcard .lktopline { flex-direction:column; align-items:stretch; }
    .lkbox.guestcard .lkfolderrow { width:100%; }
  }
  /* v2.8.15 (Essef Nov 5): the guest Connect modal must NEVER
     show the host Set Up section -- no "Set Up Your Addresses"
     heading, no Current Address, no Folder For This Address, no
     New Address row, no Open/Change Folder buttons, no
     Permissions. Hard-hidden with !important so no JS path, no
     auth-state quirk and no stale inline style can ever leak
     them onto a guest screen again (the real-phone screenshot
     showed them even though openLinkWin hides them for guests --
     the hide must not depend on JS state at all). A guest sees
     only: Connect To A PC header, connected-address card,
     open/locked notice, address field, password field, Connect.
     The host dialog is untouched -- every rule here is scoped
     .guestcard. The 2.8.15 shrink fix above stays as
     defence-in-depth for the host dialog. */
  .lkbox.guestcard h3,
  .lkbox.guestcard .lksplit,
  .lkbox.guestcard .lkfolderrow,
  .lkbox.guestcard .lkperms,
  .lkbox.guestcard .lkpermlabel,
  .lkbox.guestcard .lkdivider,
  .lkbox.guestcard .lksepinline,
  .lkbox.guestcard #lkremovepwbtn { display:none !important; }
  .lkbox.guestcard .lktopline { display:block; }
  /* v2.8.15 (Essef Nov 5): "Saved on this device" on the guest
     login page -- same offline saved mode as the APK. Button is
     on the login page itself (not in a menu, and the menu still
     never appears on the login page). The saved view lists the
     files this browser saved through Drop (localStorage
     dropit_dl + the IndexedDB blob cache), each with an Open
     action that opens the saved copy offline, and a Back button
     to the login. */
  /* v2.8.16 (Essef Nov 5, login screenshot, red marks): the
     "Saved on this device" button is NOT full-width -- it is the
     same 60% width as the Connect button above it, centred, so
     it ends at his red lines. */
  /* v2.8.18 (6): the "Saved on this device" button is GREEN
     (solid #22c55e, white text), like the APK's saved button
     -- the one green button fill on the login page. */
  .gloginbox #gsavedbtn { width:60%; margin:14px auto 0; display:block; background:#22c55e; border:none; color:#ffffff; }
  .gloginbox #gsavedbtn svg { vertical-align:-3px; margin-right:6px; }
  /* v2.8.18 (6): the theme toggle sits BELOW the login card,
     centred, like the APK login screen. */
  .glogintheme { display:flex; justify-content:center; margin-top:16px; }
  /* v2.8.16: saved rows carry a THUMBNAIL (image/video frame
     from the on-phone blob, or the file-type icon) plus a
     Preview button next to Open. */
  .gsavedrow .gsthumb { width:54px; height:54px; object-fit:cover; border-radius:12px; flex:none; border:1px solid var(--line); background:#090c15; }
  .gsavedrow .gsthumbwrap { display:flex; align-items:center; justify-content:center; width:54px; height:54px; flex:none; border:1px solid var(--line); border-radius:12px; background:#090c15; cursor:pointer; }
  .gsavedrow .gsthumbwrap .fic { font-size:20px; }
  .gsavedrow .gsnamewrap { flex:1 1 auto; min-width:0; display:flex; flex-direction:column; gap:2px; cursor:pointer; }
  .gsavedrow .gsnamewrap .gsname { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:700; font-size:14px; }
  .gsavedrow .gsnamewrap .gsmeta { color:var(--muted); font-size:12px; white-space:nowrap; }
  .gsavedview { display:none; }
  .gsavedview.open { display:block; }
  .gsavedhead { display:flex; align-items:center; gap:10px; margin-bottom:6px; }
  .gsavedhead b { font-size:17px; }
  /* v2.8.18 (7): the Back button is a small fitted button -- a
     classic curved arrow centred with the "Back" text, never
     a wide full-width button. */
  .gsavedhead .btn { display:inline-flex; align-items:center; justify-content:center; gap:6px; width:auto; padding:6px 10px; font-size:14px; }
  .gsavedhead .btn svg { width:16px; height:16px; flex:none; display:block; }
  /* v2.8.37 (3): the Back button is SOLID BLUE with WHITE
     text/icon, in BOTH themes -- theme switching must not
     change it. (2.8.36 made only the icon/text blue; the
     button itself was transparent, and the blue got lost.)
     The Delete button beside it is untouched. */
  #gsavedback, html.light #gsavedback { background:#277ff0; color:#ffffff; border:none; }
  #gsavedback:hover, html.light #gsavedback:hover { filter:brightness(1.12); }
  /* v2.8.39 (4): the Saved header is the MB layout on EVERY
     surface now -- the title sits exactly centred, the red
     Delete button sits on the RIGHT, Back stays on the left
     (solid blue, per 2.8.37). 2.8.38 did this for phone widths
     only; PC web keeps the old row no longer -- it matches MB. */
  .gsavedhead { position:relative; }
  .gsavedhead b { position:absolute; left:50%; top:50%; transform:translate(-50%,-50%); font-size:15px; }
  .gsavedhead #gsaveddel { order:2; margin-left:auto; background:#ef4444; color:#ffffff; border:none; }
  .gsavedhead #gsaveddel:hover { filter:brightness(1.12); }
  /* v2.8.36 (8): selection mode on saved rows -- same picked
     highlight as the Files tab. */
  .gsavedrow.picked { background:rgba(239,68,68,.08); border-radius:12px; }
  .gsavedrow.picked .fsel { background:linear-gradient(135deg,#ef4444,#e11d48); border-color:transparent; color:#fff; }
  .gsavedrow { display:flex; align-items:center; gap:10px; padding:10px 4px; border-top:1px solid var(--line); }
  .gsavedrow .gsname { flex:1 1 auto; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:700; font-size:14px; }
  .gsavedrow .gsmeta { flex:none; color:var(--muted); font-size:12px; white-space:nowrap; }
  .gsavedrow .btn { width:auto; flex:none; padding:7px 14px; font-size:13px; background:#277ff0; border:none; }
  .gsavedempty { color:var(--muted); font-size:13px; text-align:center; margin:16px 0 4px; line-height:1.5; }
  /* v2.8.39 (4): a saved row whose file is gone from this
     device's storage (blob cache empty, PC unreachable) says
     so instead of offering a dead Open -- the meta line reads
     "file has been removed" in red and Open is disabled. */
  .gsavedrow.gsaved-gone { opacity:.75; }
  .gsavedrow.gsaved-gone .gsmeta { color:#f87171; font-weight:700; }
  .gsavedrow.gsaved-gone .btn:disabled { opacity:.45; cursor:not-allowed; }
  /* v2.8.39 (4): the same gone state on the in-app Saved
     viewer's file rows (see showSaved). */
  #vcontent .frow.gsaved-gone { opacity:.75; }
  /* v2.8.37 (4): NO refresh button on mobile web -- the page
     has no refresh control of its own, and none may appear in
     the header/top area at phone widths. This guard hides any
     refresh-titled control outright (it matches nothing in
     2.8.37; it is a backstop so a future control cannot leak
     back onto the mobile header). Desktop is untouched. */
  @media (max-width:720px){
    [data-refresh], #refreshbtn, button[title*="Refresh" i], button[aria-label*="Refresh" i] { display:none !important; }
  }
  /* v2.8.24 (Essef Nov 6, ~3:18 AM) -- web/desktop only.
     (5) STARRED button text WHITE on its amber fill (was
     near-black #231303): label + star icon, on and off, both
     themes. The active (.on) state keeps an inset ring, now
     white so it still reads on amber.
     (5) SAVE buttons CENTRED: the three dialog Saves (#lkset
     Set Up, #lockpwsave Set Password, #msave New Shared Text)
     are centred flex rows with the icon transform removed, so
     icon + text share one centre line -- the host Save's icon
     sat 3px low (2.8.6 translateY) and its text sat ~4px below
     the button centre (measured). Labels become "SAVE" in the
     HTML below. The note-editor save and "Save on this device" are
     untouched.
     v2.8.29 (4): ONE SPACE between floppy and SAVE (Essef
     Nov 6) -- gap 8px -> 4px on all four Save gap rules
     (#lkset / #lockpwsave / #msave shared rule, .lockpwsave,
     .lockpwbox .lockpwsave, guest #lkset). 4px is one space
     at the 15-16px button font (measured live: the " SAVE"
     text node's leading space is trimmed by the flex layout,
     so the flex gap IS the whole icon-to-text distance).
     Icon + text stay one centred unit, text vertically
     centred; the " SAVE" / " Connect" label rewrite in
     openLinkWin is untouched, so the spacing survives it. */
     (6) SEND TEXT NOTE button (web): icon + text are ONE
     centred unit -- the .msend-in span wraps both svgs + the
     label, so no rule can ever split the icon to the button's
     left edge again (Essef's phone screenshot showed exactly
     that split: icon pinned at the left padding, text centred
     on its own). Gap 6px; label renamed in the HTML below.
     (7)/(8) SLIDE transitions: tab changes slide the new
     column in from the side (direction follows tab order,
     --tabdx set by setTab; the animation itself lives on
     .board .col.active in the mobile media query below), and
     Save clicks slide the board in (.boardslide, re-triggered
     by slideInBoard). Both are very fast (.18s ease-out). */
  .board #starfilter, .board #starfilter.on, #starfilter.on { color:#ffffff; }
  .board #starfilter svg, .board #starfilter svg path, #starfilter.on svg, #starfilter.on svg path { fill:#ffffff; color:#ffffff; }
  #starfilter.on { box-shadow:inset 0 0 0 2px rgba(255,255,255,.65); }
  /* v2.8.40 (2): the Starred filter matches the APK toggle
     exactly -- OFF stays a quiet neutral button (card fill,
     muted text, outline star); ON is the APK's inverted chip:
     solid dark #231303, a 2px gold stroke, gold "✓ Starred"
     label, and the star back to filled YELLOW (the 2.8.39 amber
     fill with a dark star washed the star out in light mode).
     One ON rule governs BOTH themes -- the dark chip reads on
     light and dark alike, so the light-mode amber override is
     gone. These rules sit after the 2.8.24 block above, so
     they win. Starred notes keep their filled yellow star in
     both themes (see .starbtn.starred); a starred note with
     the star permission removed keeps its filled GREY star
     (see .starbtn.starred.deloff). */
  .board #starfilter { background:var(--card2); color:var(--muted); border:1px solid var(--line); }
  .board #starfilter svg, .board #starfilter svg path { fill:none; stroke:currentColor; }
  .board #starfilter.on { background:#231303; color:#fbbf24; border:2px solid #fbbf24; box-shadow:none; }
  .board #starfilter.on svg, .board #starfilter.on svg path { fill:#fbbf24; stroke:#fbbf24; }
  html.light .board #starfilter { background:#ffffff; color:#64748b; border-color:#cbd5e1; }
  /* v2.8.40 (2) fix: the light OFF rule above is
     html.light .board #starfilter (1,2,1), which outranks the
     plain .board #starfilter.on rule (1,2,0) for background and
     color -- light ON measured white with grey text. This
     light-scoped ON rule (1,3,1) wins, so ON is the same dark
     #231303 chip in light mode as in dark. */
  html.light .board #starfilter.on { background:#231303; color:#fbbf24; border:2px solid #fbbf24; box-shadow:none; }
  html.light .board #starfilter.on svg, html.light .board #starfilter.on svg path { fill:#fbbf24; stroke:#fbbf24; }
  .board #starfilter:hover { filter:brightness(1.08); border:1px solid var(--line); }
  .board #starfilter.on:hover { border:2px solid #fbbf24; }
  #lkset, #lockpwsave, #msave { display:inline-flex; align-items:center; justify-content:center; gap:4px; line-height:1; }
  .lkbox #lkset svg { transform:none; }
  html:not(.pcapp) .msend #msendsnippet .msend-in { display:inline-flex; align-items:center; justify-content:center; gap:6px; }
  @keyframes tabslidein { from { opacity:0; transform:translateX(var(--tabdx,24px)); } to { opacity:1; transform:translateX(0); } }
  @keyframes boardslidein { from { opacity:0; transform:translateX(24px); } to { opacity:1; transform:translateX(0); } }
  .board.boardslide { animation:boardslidein .18s ease-out; }
  /* v2.8.41 (3): Starred filter -- ONE authoritative block,
     last in the stylesheet, so it wins over the five older
     competing #starfilter rule sets above (2.8.24 amber,
     2.8.39 solid gold, 2.8.40 neutral-OFF + dark-ON, and the
     white-text override). Colours are the APK's own, read
     from its source (btn_gold.xml / btn_gold_on.xml /
     MainActivity.paintStarFilter): OFF is the APK gold --
     yellowish-brown gradient #FBBF24 -> #F59E0B -- with a
     WHITE label and a dark #231303 outline star; ON is the
     inverted chip -- solid dark #231303, 2px gold #FBBF24
     stroke, WHITE "✓ Starred" label, filled gold star. The
     SAME colours in dark and light mode, on D and web (the
     2.8.40 build made OFF a quiet neutral button, so the
     button never looked yellowish-brown like the APK).
     v2.8.41 fix-up (APK 2.6.115 reference values, verified by
     the APK track Nov 7): the ON label is WHITE in both
     states -- the 2.8.40 web spec used a gold ON label, which
     is not the APK -- and the ON filled star is #FBBF24 fill
     with a #F59E0B stroke.
     Every property the old rules set is set here, so no
     stale value leaks through on any surface. Starred notes
     keep their filled yellow star (see .starbtn.starred). */
  html .board #starfilter, html #starfilter { background:linear-gradient(135deg,#fbbf24,#f59e0b); color:#ffffff; border:none; box-shadow:none; filter:none; }
  html .board #starfilter svg, html #starfilter svg, html .board #starfilter svg path, html #starfilter svg path { fill:none; stroke:#231303; }
  html .board #starfilter.on, html #starfilter.on { background:#231303; color:#ffffff; border:2px solid #fbbf24; box-shadow:none; filter:none; }
  html .board #starfilter.on svg, html #starfilter.on svg, html .board #starfilter.on svg path, html #starfilter.on svg path { fill:#fbbf24; stroke:#f59e0b; }
  html.light .board #starfilter, html.light #starfilter { background:linear-gradient(135deg,#fbbf24,#f59e0b); color:#ffffff; border:none; box-shadow:none; filter:none; }
  html.light .board #starfilter svg, html.light #starfilter svg, html.light .board #starfilter svg path, html.light #starfilter svg path { fill:none; stroke:#231303; }
  html.light .board #starfilter.on, html.light #starfilter.on { background:#231303; color:#ffffff; border:2px solid #fbbf24; box-shadow:none; filter:none; }
  html.light .board #starfilter.on svg, html.light #starfilter.on svg, html.light .board #starfilter.on svg path, html.light #starfilter.on svg path { fill:#fbbf24; stroke:#f59e0b; }
</style>
</head>
<body>

<!-- v2.8.31 (Essef Nov 6): CUSTOM THEMED TITLE BAR, PC app ONLY --
     Design 1 (picked by Essef): dark navy bar (#12172a) with a
     thin blue underline (#277ff0), Drop logo + "Drop" left,
     minimise / maximise-restore / close as full-height strips
     right, close hovers red. Shown only on the frameless PC
     app (html.pcapp.frameless, set by JS from the bridge) --
     web, guests and the framed fallback never see it. -->
<div id="titlebar"><div class="tb-drag" id="tbdrag"><img class="tb-logo" src="/logo.png" alt="Drop logo"><span class="tb-name">Drop</span></div><div class="tb-btns"><button class="tb-btn" id="tbmin" type="button" title="Minimize" aria-label="Minimize"><svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="5" y1="12" x2="19" y2="12"/></svg></button><button class="tb-btn" id="tbmax" type="button" title="Maximize" aria-label="Maximize"><svg class="tb-ic-max" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="6" width="12" height="12" rx="1"/></svg><svg class="tb-ic-restore" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><rect x="8" y="4" width="12" height="12" rx="1"/><path d="M4 16v2a2 2 0 0 0 2 2h10"/></svg></button><button class="tb-btn tb-close" id="tbclose" type="button" title="Close" aria-label="Close"><svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="5" y1="5" x2="19" y2="19"/><line x1="19" y1="5" x2="5" y2="19"/></svg></button></div></div>

<div class="topbar">
  <div class="topbar-left">
    <button id="menubtn" aria-label="Menu" title="Menu"><span></span><span></span><span></span></button>
  </div>
  <div class="connectwrap">
    <div class="connectbar">
      <button class="qrmini" id="qrtoggle" data-tip="Show the large QR code">__QRMINI__</button>
      <a href="__URL__" id="toplink">__ADDRESSNAME__</a>
      <button class="copybtn" id="linklock" title="Address lock"></button>
      <button class="copybtn" id="copy" data-tip="Copy the address name" aria-label="Copy address"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg></button>
    </div>
  </div>
  <button class="btn" id="askbtn" title="Search" aria-label="Search"><svg class="findglass" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round"><circle cx="10.5" cy="10.5" r="6.8"/><line x1="15.4" y1="15.4" x2="20.6" y2="20.6"/><path d="M10.5 7.4l.9 2.2 2.2.9-2.2.9-.9 2.2-.9-2.2-2.2-.9 2.2-.9z" fill="currentColor" stroke="none"/></svg><span class="findspark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="#fbbf24"><path d="M12 2l2.2 6.6L21 11l-6.8 2.4L12 20l-2.2-6.6L3 11l6.8-2.4z"/></svg></span></button>
</div>
<div class="qrpop" id="qrpop"><button class="qrpopclose" id="qrpopclose" title="Close" aria-label="Close">&times;</button>__QR__
  <p class="hint">Open the address on your phone &mdash; both devices need the same WiFi.<br>First run may ask for firewall permission &mdash; allow it.</p>
</div>

<div class="guestlogin" id="guestlogin"><div class="gloginbox">
  <div class="glogo"><img src="/logo.png" alt="Drop logo"><span class="gdrop">Drop</span></div>
  <p class="gslogan">Local only &middot; No cloud &middot; No accounts &middot; Just Drop</p>
  <div id="gloginform">
  <div class="lklabel">Address</div>
  <div class="ddwrap" id="gddwrap"><input id="gloginlink" placeholder="Address shown on the Drop window" autocomplete="off" autocapitalize="off" spellcheck="false"><button class="ddchevbtn" id="gddchevbtn" type="button" title="Show saved addresses" aria-label="Show saved addresses">▾</button><div class="ddlist" id="gddlist"></div></div>
  <div class="lklabel">Password</div>
  <input type="password" id="gloginpw" placeholder="Password For This Address" autocomplete="current-password">
  <p class="gloginpwstate" id="gloginpwstate"></p>
  <div class="gloginerr" id="gloginerr"></div>
  <button class="btn primary" id="gloginbtn">Connect</button>
  <label class="permchk gloginsave" id="gloginsavelabel" title="Save the password for this address on this device"><input type="checkbox" id="gloginsavechk" checked><span class="permbox"></span><span>Save password</span></label>
  <p class="gloginmsg" id="gloginmsg">Disconnected — enter the address and password to connect again</p>
  <button class="btn" id="gsavedbtn" type="button" title="Show files saved on this device"><svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> Saved on this device</button>
  </div>
  <div class="gsavedview" id="gsavedview">
  <div class="gsavedhead"><button class="btn" id="gsavedback" type="button"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/></svg> Back</button><button class="btn" id="gsaveddel" type="button"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg> Delete</button><b>Saved on this device</b></div>
  <div class="svbar" id="gsvbar"><span class="delcount" id="gsvcount">Select files</span><button class="canceldel" id="gsvcancel">Cancel</button><button class="selall" id="gsvall">All</button><button class="confirmdel" id="gsvconfirm" disabled>Delete</button></div>
  <div id="gsavedlist"></div>
  <p class="gsavedempty" id="gsavedempty">Nothing saved yet &mdash; download a file from a PC and it will show up here.</p>
  </div>
</div><div class="glogintheme"><button class="themesw" id="themeswLogin" type="button" title="Switch light / dark mode" aria-label="Switch light / dark mode"><svg class="tsic tsmoon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg><svg class="tsic tssun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg><span class="tsknob"></span></button></div></div>
<div class="connpop" id="connpop"><div class="connbox">
  <div class="connic" id="connic"></div>
  <p class="conntext" id="conntext">Connecting…</p>
  <button class="btn" id="connclose" style="display:none">Close</button>
</div></div>
<div class="board">
  <div class="col" data-col="send">
    <div class="devpill" id="devpill"><div class="status" id="statusdiv" role="button" tabindex="0" title="Devices connected"><span class="dot" id="statusdot"></span><span id="statustext">No devices connected</span><span class="devarrow" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg></span></div><div class="devdrop" id="devdrop"><div class="devdroptitle">Devices Connected</div><div class="devdroprows" id="devdroprows"></div><div class="devdropfoot"><button class="devdropall" id="devdropall">Disconnect All</button></div></div></div>
    <div class="colhead"><h2>&#x2B06;&#xFE0F; Upload</h2></div>
    <div class="colbody">
      <div class="minicard">
        <h3><svg class="hicon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <defs><linearGradient id="hg1" x1="0" y1="0" x2="24" y2="24" gradientUnits="userSpaceOnUse">
            <stop stop-color="#a78bfa"/><stop offset="1" stop-color="#38bdf8"/>
          </linearGradient></defs>
          <path d="M12 15.5V4.2M6.9 8.8L12 3.7 17.1 8.8" stroke="url(#hg1)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M4.5 14.8V18.2A1.8 1.8 0 0 0 6.3 20H17.7A1.8 1.8 0 0 0 19.5 18.2V14.8" stroke="url(#hg1)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>Send Files</h3>
        <div id="drop">
          <svg class="dropicon" viewBox="0 0 64 64" fill="none" aria-hidden="true">
            <defs><linearGradient id="dg" x1="0" y1="0" x2="64" y2="64" gradientUnits="userSpaceOnUse">
              <stop stop-color="#a78bfa"/><stop offset="1" stop-color="#38bdf8"/>
            </linearGradient></defs>
            <path d="M32 4C32 4 12 28 12 42a20 20 0 0 0 40 0C52 28 32 4 32 4Z" fill="url(#dg)"/>
            <path d="M22 42a10 10 0 0 0 10 10" stroke="#fff" stroke-opacity=".7" stroke-width="3.5"
                  stroke-linecap="round"/>
            <path d="M24 20c2-3 5-7 8-10 3 3 6 7 8 10" stroke="#fff" stroke-opacity=".9" stroke-width="3"
                  stroke-linecap="round"/>
          </svg>
          <div class="big">Drop Your Files Here</div>
          <div class="small" id="landline">or click to browse<span id="landline-dir"> &mdash; they land in:<span class="dirline"><b id="dirnamelabel">__DIRNAME__</b></span></span></div>
          <input type="file" id="picker" multiple style="display:none">
        </div>
        <div id="uploads"></div>
      </div>
      <div class="minicard">
        <h3><svg class="hicon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <defs><linearGradient id="hg2" x1="0" y1="0" x2="24" y2="24" gradientUnits="userSpaceOnUse">
            <stop stop-color="#a78bfa"/><stop offset="1" stop-color="#38bdf8"/>
          </linearGradient></defs>
          <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"
                stroke="url(#hg2)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>Send Text</h3>
        <textarea id="snippet" rows="3" placeholder="Paste a web address, email, phone number, or any text&#8230;"></textarea>
        <div style="display:flex;justify-content:flex-end;margin-top:10px;">
          <button class="btn primary" id="sendsnippet"><svg class="ic-bubble" viewBox="0 0 24 24" fill="none" stroke="#052e33" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg><svg class="ic-note" viewBox="0 0 24 24" fill="none" stroke="#052e33" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6,3 L14,3 L18,7 L18,19.5 A1.5,1.5 0 0 1 16.5,21 L6,21 A1.5,1.5 0 0 1 4.5,19.5 L4.5,4.5 A1.5,1.5 0 0 1 6,3 Z"/><path d="M14,3 L14,7.2 L18,7.2 M8.3,12.2 L15.7,12.2 M8.3,15.6 L15.7,15.6 M8.3,19 L12.9,19"/></svg>Send Text</button>
        </div>
      </div>
      <div class="msend">
        <div class="minicard">
          <div class="mlabel">Set Up Your Addresses</div>
          <div class="mconnstate" id="mconnstate">Not connected</div>
          <div class="mqrrow">
            <div class="maddrwrap">
              <input id="mpchost" class="mtext" spellcheck="false" autocomplete="off" autocapitalize="off">
              <button class="mddtoggle" id="mddtoggle" type="button" title="Show saved addresses" aria-label="Show saved addresses"><span id="mddchev">▾</span></button>
              <button class="mcopybtn" id="mcopy" data-tip="Copy the address name"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg></button>
              <div class="ddlist mddlist" id="mddlist"></div>
            </div>
            <button class="qrmini mqrmini" id="qrtoggleM" data-tip="Show the large QR code">__QRMINI__</button>
          </div>
          <p class="mhint">Shown on the Drop window on your PC &mdash; enter once, it&apos;s remembered.</p>
          <div class="mpcbtnrow"><button class="mpcbtn mpc-connect" id="mpcconnect" data-tip="Connect to this address"><svg viewBox="0 0 24 24" fill="none" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M3,12h17M14.5,5.5L21,12l-6.5,6.5"/></svg> Connect</button><button class="mpcbtn mpc-disconnect" id="mpcdisconnect" data-tip="Disconnect from this PC"><svg viewBox="0 0 24 24" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M7,7l-3,3 3,3M17,7l3,3 -3,3M13,4l-2,16"/></svg> Disconnect</button></div>
        </div>
        <div class="minicard">
          <div class="mlabel">Send Files</div>
          <button class="mbtn-secondary" id="msendfiles"><svg viewBox="0 0 24 24" fill="#052e33"><path d="M10 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8l-2-2z"/></svg>&nbsp; Choose Files to Send</button>
          <input type="file" id="mpicker" multiple style="display:none">
          <div id="muploads"></div>
        </div>
        <div class="minicard">
          <div class="mlabel">Share Text</div>
          <textarea id="msendtext" rows="5" placeholder="Paste a web address, email, phone number&#8230;"></textarea>
          <button class="mbtn-primary" id="msendsnippet"><span class="msend-in"><svg class="ic-bubble" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg><svg class="ic-note" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#FFFFFF" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6,3 L14,3 L18,7 L18,19.5 A1.5,1.5 0 0 1 16.5,21 L6,21 A1.5,1.5 0 0 1 4.5,19.5 L4.5,4.5 A1.5,1.5 0 0 1 6,3 Z"/><path d="M14,3 L14,7.2 L18,7.2 M8.3,12.2 L15.7,12.2 M8.3,15.6 L15.7,15.6 M8.3,19 L12.9,19"/></svg>Send Text Note</span></button>
        </div>
        <p class="msendfoot">Local only &middot; No cloud &middot; No accounts &middot; Just Drop</p>
      </div>
    </div>
  </div>
  <div class="col" data-col="notes">
    <div class="colhead"><h2><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/><path d="M8.5 10h7M8.5 13.5h4.5"/></svg> Shared Texts</h2><span class="count" id="snipcount"></span></div>
    <div class="nbtnrow"><button class="btn primary" id="maddnote" data-tip="Add a new shared text"><svg viewBox="0 0 24 24" fill="none" stroke="#052e33" stroke-width="2.5" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg> Add New</button><button class="btn" id="starfilter" style="display:none" title="Show starred only" aria-pressed="false"><svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px"><path d="M12 3.6l2.5 5.2 5.7.7-4.2 4 1.1 5.6L12 16.4l-5.1 2.7L8 13.5l-4.2-4 5.7-.7z"/></svg> Starred</button><button class="btn dangergrad" id="delallnotesbtn" style="display:none" data-tip="Delete all shared texts"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg> Delete</button></div>
    <div class="colbody"><div id="snips"><p class="empty">Loading&hellip;</p></div></div>
  </div>
  <div class="col" data-col="files">
    <div class="colhead"><h2>&#x1F4C1; Shared Files</h2><span class="count" id="filecount"></span>__FILEHEAD__</div>
    __FILEBTNS__
    <div class="colbody"><div id="files"><p class="empty">Loading&hellip;</p></div></div>
  </div>
  <div class="col" data-col="ask">
    <div class="colhead"><h2><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" style="vertical-align:-2px"><circle cx="10.5" cy="10.5" r="6.8"/><line x1="15.4" y1="15.4" x2="20.6" y2="20.6"/><path d="M10.5 7.4l.9 2.2 2.2.9-2.2.9-.9 2.2-.9-2.2-2.2-.9 2.2-.9z" fill="currentColor" stroke="none"/></svg> Search</h2></div>
    <div class="colbody">
      <div class="asklist" id="asklist"></div>
      <div class="askinput"><input id="asktext" placeholder="Search a file&hellip;" autocomplete="off"><button id="asksend" title="Send">&#x27A4;</button></div>
    </div>
  </div>
</div>

        <div class="upfloat" id="upfloat" aria-live="polite"><svg class="upring" viewBox="0 0 64 64" aria-hidden="true"><circle class="upring-track" cx="32" cy="32" r="26"/><circle class="upring-prog" id="upringprog" cx="32" cy="32" r="26" transform="rotate(-90 32 32)"/><text class="upring-num" id="upringnum" x="32" y="41">0</text></svg><span class="upfloat-name" id="upfloatname"></span><button class="upcancel" id="upcancel" type="button" title="Cancel upload" aria-label="Cancel upload">&times;</button></div>
<nav class="mtabs">
  <button class="mtab sel" data-tab="send"><span class="mi"><svg viewBox="0 0 24 24" fill="none" stroke="#22C55E" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15.5V4.2M6.9 8.8L12 3.7 17.1 8.8"/><path d="M4.5 14.8V18.2A1.8 1.8 0 0 0 6.3 20H17.7A1.8 1.8 0 0 0 19.5 18.2V14.8"/></svg></span><span>Upload</span></button>
  <button class="mtab" data-tab="notes"><span class="mi"><svg viewBox="0 0 24 24" fill="none" stroke="#D9A441" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/><path d="M8.5 10h7M8.5 13.5h4.5"/></svg></span><span>Notes</span><span class="mcount" id="mnotecount"></span></button>
  <button class="mtab" data-tab="files"><span class="mi"><svg viewBox="0 0 24 24" fill="none" stroke="#3B82F6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg></span><span>Files</span><span class="mcount" id="mfilecount"></span></button>
  <button class="mtab" data-tab="ask"><span class="mi"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="#A78BFA" stroke-width="2.1" stroke-linecap="round" style="vertical-align:-2px"><circle cx="10.5" cy="10.5" r="6.8"/><line x1="15.4" y1="15.4" x2="20.6" y2="20.6"/><path d="M10.5 7.4l.9 2.2 2.2.9-2.2.9-.9 2.2-.9-2.2-2.2-.9 2.2-.9z" fill="#A78BFA" stroke="none"/></svg></span><span>Search</span></button>
</nav>

<footer>Drop &middot; Local only &middot; No cloud &middot; No accounts &middot; Just Drop</footer>
<div class="themewrap" style="display:none"><button class="themesw" id="themesw" type="button" title="Switch light / dark mode" aria-label="Switch light / dark mode"><svg class="tsic tsmoon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg><svg class="tsic tssun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg><span class="tsknob"></span></button></div>
<div class="toast" id="toast"></div>
<div class="delbar" id="delbar"><span class="delcount" id="delcount">Select files</span><button class="canceldel" id="delcancel">Cancel</button><button class="selall" id="delselall">All</button><button class="confirmdel" id="delconfirm" disabled data-tip="Delete the selected files">Delete</button></div>
<div class="askpop" id="askpop"><div class="askbox">
  <div class="askhead"><span><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" style="vertical-align:-2px"><circle cx="10.5" cy="10.5" r="6.8"/><line x1="15.4" y1="15.4" x2="20.6" y2="20.6"/><path d="M10.5 7.4l.9 2.2 2.2.9-2.2.9-.9 2.2-.9-2.2-2.2-.9 2.2-.9z" fill="currentColor" stroke="none"/></svg> Search A File Using Keywords / Objects / Texts</span><button class="vclose" id="askclose">&#x2715;</button></div>
  <div class="asklist" id="asklist2"></div>
  <div class="askinput"><input id="asktext2" placeholder="Search a file&hellip;" autocomplete="off"><button id="asksend2" title="Send">&#x27A4;</button></div>
</div></div>
<div class="viewer" id="viewer"><div class="vbox">
  <div class="vhead"><span id="vtitle"></span><button class="vclose" id="vclose">&#x2715;</button></div>
  <div id="vcontent"></div>
</div></div>
<div class="mdlg" id="cfdlg"><div class="mbox">
  <h3 id="cftitle">Save file?</h3>
  <p class="cfmsg" id="cfmsg"></p>
  <div class="mrow"><button class="btn" id="cfno">Discard</button><button class="btn primary" id="cfyes">Save on this device</button></div>
</div></div>

<div class="mdlg" id="mdlg"><div class="mbox">
  <h3>New Shared Text</h3>
  <textarea id="mnote" placeholder="Write your shared text&hellip;"></textarea>
  <div class="mrow"><button class="btn" id="mcancel">Cancel</button><button class="btn primary" id="msave">SAVE</button></div>
</div></div>

<div class="lockwrap" id="lockwrap"><div class="lockbox">
  <div class="lockic"><svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg></div>
  <h3>Drop is locked</h3>
  <p class="locksub" id="locksub">Enter the password for your collection.</p>
  <input type="password" id="lockpw" placeholder="Password" autocomplete="current-password">
  <div class="lockerr" id="lockerr"></div>
  <button class="btn primary lockgo" id="lockgo">Unlock</button>
  <button class="btn lockgo" id="lockchange">Change address</button>
</div></div>
<div id="scrim"></div>
<aside id="sidebar">
  <div class="sbhead"><span class="sblogotile"><img class="sblogo" src="/logo.png" alt="Drop logo"></span><span class="sbtitle">Drop</span><span class="sbver">v__VERSION__</span></div>
  <div class="sbcard" id="sbsetupcard">
  <div class="sbsec">Set Up Your Addresses</div>
  <div class="sblinkrow"><span id="sblink">-</span><button id="sblock" class="sblockbtn" title="Address lock"><svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.5-2"/></svg></button><button id="sbedit" class="sblockbtn" title="Edit address" aria-label="Edit address"><svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.828 2.828 0 114 4L7.5 20.5 2 22l1.5-5.5L17 3z"/></svg></button></div>
  </div>
  <div class="sbcard" id="sbaddrcard">
  <div class="sbsec">Your address</div>
  <div class="sblinkrow"><span id="sbaddr">No address set yet</span></div>
  </div>
  <div class="sbcard" id="sbsepcard">
  <div class="sbrow"><span>Create Separate Folders</span><span class="sbsw" id="swsep"><span class="sbknob"></span></span></div>
  </div>
  <div class="sbcard" id="sbfoldercard">
  <div class="sbsec">Main Folder</div>
  <button class="sbbtn" id="sbopen" data-tip="Open the Main Folder on this PC"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M3 9.5h18"/></svg> Open Folder</button>
  <button class="sbbtn" id="sbchange" data-tip="Change the Main Folder on this PC"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/></svg> Change Folder</button>
  </div>
  <div class="sbcard">
  <div class="sbsec">Show</div>
  <div class="sbrow"><span>QR code</span><span class="sbsw" id="swqr"><span class="sbknob"></span></span></div>
  <div class="sbrow"><span>Devices connected</span><span class="sbsw" id="swdev"><span class="sbknob"></span></span></div>
  </div>
  <div class="sbcard">
  <div class="sbsec">Theme</div>
  <div class="sbrow"><span>Dark / Light</span><button class="themesw" id="themesw2" type="button" title="Switch light / dark mode" aria-label="Switch light / dark mode"><svg class="tsic tsmoon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg><svg class="tsic tssun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg><span class="tsknob"></span></button></div>
  </div>
  <button class="sbbtn" id="sbdisconnect" style="display:none">Disconnect</button>
  <button class="sbbtn" id="sblockdev" style="display:none">Lock this device</button>
</aside>
<div class="lockwrap" id="lkwrap" style="display:none"><div class="lockbox lkbox" id="lkbox">
  <button class="lkclosebtn" id="lkcloseX" title="Close" aria-label="Close">&times;</button>
  <h3>Set Up Your Addresses</h3>
  <div class="guestcardhead" id="guestcardhead" style="display:none"><span class="guestcardic">🔗</span><div class="guestcardtxt"><b>Connect To A Device</b><span>Enter the address shown on the Drop window</span></div></div>
  <div class="guestlinkcard" id="guestlinkcard" style="display:none"><span class="glklabel">Connected Address</span><span class="glkname" id="guestlinkname">Not connected</span></div>
  <p class="locksub" id="lkstate"></p>
  <div class="lklockedwarn" id="lklockedwarn"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#4ade80" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg><span id="lklockedtext">Locked address — password required</span></div>
  <div class="lkopenwarn" id="lkopenwarn"><svg viewBox="0 0 24 24" fill="none" stroke="#ffb000" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 11V7a5 5 0 0 1 9.8-1.6"/><rect x="4" y="11" width="16" height="10" rx="2"/><circle cx="12" cy="16" r="1.5" fill="#ffb000" stroke="none"/></svg>Open address &mdash; anyone on your Wi-Fi can use it</div>
  <hr class="lkdivider">
  <div class="lksplit" id="lksplit">
  <div class="lkcol">
  <div class="lklabel" id="lkcurlabel">Current Address</div>
  <div class="lkview lkcurdd" id="lkcurview"><span id="lkname">-</span><button class="lkcopybtn" id="lkcopy" type="button" title="Copy the full address link" aria-label="Copy the full address link"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg></button><span class="ddchev" id="lkddchevbtn" role="button" title="Show saved addresses" aria-label="Show saved addresses">▾</span><div class="ddlist" id="lkddlist"></div></div>
  </div>
  <div class="lkcol">
  <div class="lklabel" id="lkfolderlabel">Folder For This Address</div>
  <div class="lkview" id="lkfolderview">📁 <span id="lkfolder">-</span></div>
  <div class="lkseprow"><label class="permchk lksepinline" id="lkseplabel" title="Create a separate folder for each address"><input type="checkbox" id="lksepchk"><span class="permbox"></span><span>Create Separate Folders</span></label><button type="button" class="lksepinfo" id="lksepinfo" title="Each address gets its own folder for its files." aria-label="What does Create Separate Folders do?"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><line x1="12" y1="11" x2="12" y2="17"/><circle cx="12" cy="7.5" r="1" fill="currentColor" stroke="none"/></svg></button></div>
  </div>
  </div>
  <div class="lktopline"><div class="lknewcol"><div class="lklabel" id="lklinklabel">New Address</div><div class="lkeditrow"><input class="lkfield" id="lkin" placeholder="New Address" autocomplete="off" autocapitalize="off" spellcheck="false"></div></div><div class="lkfolderrow" id="lkfolderrow"><button class="btn openf" id="lkopenfolder" data-tip="Open the save folder on this PC"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg> Open Folder</button><button class="btn changef" id="lkchangefolder" data-tip="Change the save folder for this address"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 2.1 21 6l-4 3.9"/><path d="M21 6H8"/><path d="M7 21.9 3 18l4-3.9"/><path d="M3 18h16"/></svg> Change Folder</button></div></div>
  <div class="lkerr" id="lkerr"></div>
  <div class="lkpwsection">
  <div class="lklabel" id="lkpwlabel">Password (Optional)</div>
  <div class="lkpwrow"><input class="lkfield" type="password" id="lkpw" placeholder="Set A Password (Optional)" autocomplete="new-password"><button class="lkiconbtn" id="lkpweye" data-tip="Show or hide the password" aria-label="Show password"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg></button><button class="lkiconbtn danger" id="lkremovepwbtn" data-tip="Remove the address password" aria-label="Remove password"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg></button><label class="permchk lksavepwinline" id="lksavepwlabel" title="Save the password for this address"><input type="checkbox" id="lksavepwchk" checked><span class="permbox"></span><span>Save Password</span></label></div>
  </div>
  <hr class="lkdivider">
  <div class="lkpermlabel" id="lkpermlabel">Permissions <button type="button" class="lkperminfo" id="lkperminfo" title="HOST ONLY - APPLIES TO INDIVIDUAL ADDRESS" aria-label="About permissions"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><line x1="12" y1="11" x2="12" y2="17"/><circle cx="12" cy="7.5" r="1" fill="currentColor" stroke="none"/></svg></button></div>
  <div class="lkperms" id="lkperms">
  <div class="lkpermgrid" id="lkpermgrid">
  <label class="permchk"><input type="checkbox" data-perm="download_files"><span class="permbox"></span><span>Download Files</span></label>
  <label class="permchk"><input type="checkbox" data-perm="upload_files"><span class="permbox"></span><span>Upload Files</span></label>
  <label class="permchk"><input type="checkbox" data-perm="delete_files"><span class="permbox"></span><span>Delete Files</span></label>
  <label class="permchk"><input type="checkbox" data-perm="add_notes"><span class="permbox"></span><span>Add / Edit Notes</span></label>
  <label class="permchk"><input type="checkbox" data-perm="delete_notes"><span class="permbox"></span><span>Delete Notes</span></label>
  <label class="permchk"><input type="checkbox" data-perm="star_notes"><span class="permbox"></span><span>Star Notes</span></label>
  </div>
  </div>
  <div class="lksavewrap">
  <button class="btn primary lkclose" id="lkset" data-tip="Save this address"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><path d="M17 21v-8H7v8"/><path d="M7 3v5h8"/></svg> SAVE</button>
  <button class="btn" id="lkunlockbtn" style="display:none">Unlock With This Password</button>
  </div>
</div></div>
<div class="lockpwpop" id="lockpwpop"><div class="lockpwbox">
  <button class="lkclosebtn" id="lockpwcloseX" title="Close" aria-label="Close">&times;</button>
  <h4>SET PASSWORD FOR ADDRESS: <span id="lockpwaddr"></span></h4>
  <label class="lockpwcap" for="lockpwin">Password</label>
  <div class="lockpwfield"><input type="password" id="lockpwin" placeholder="Enter a password" autocomplete="new-password"><button class="lockpweye" id="lockpweye" data-tip="Show or hide the password" aria-label="Show password"></button></div>
  <div class="lockpwerr" id="lockpwerr"></div>
  <label class="permchk lockpwsavechk" id="lockpwsavechklabel" title="Save the password for this address"><input type="checkbox" id="lockpwsavechk" disabled><span class="permbox"></span><span>Save password</span></label>
  <button class="btn primary lockpwsave" id="lockpwsave"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><path d="M17 21v-8H7v8"/><path d="M7 3v5h8"/></svg> SAVE</button>
</div></div>

<div class="previewpop" id="previewpop"><div class="previewbox">
  <button class="pvclose" id="previewclose" title="Close" aria-label="Close">&times;</button>
  <h4 id="previewtitle">Preview</h4>
  <div class="pvsub" id="previewsub"></div>
  <div class="pvbody" id="previewbody"></div>
  <div class="pvrow"><button class="btn" id="previewclose2">Close</button><button class="btn pvdl" id="previewdl">Download</button></div>
</div></div>
<div class="addrrempop" id="addrrempop"><div class="addrrembox">
  <button class="lkclosebtn" id="addrremcloseX" title="Close" aria-label="Close">&times;</button>
  <h4>REMOVE ADDRESS: <span id="addrremaddr"></span></h4>
  <p class="addrremsub">Delete the data saved for this address?</p>
  <label class="permchk addrremchk"><input type="checkbox" id="addrremnotes"><span class="permbox"></span><span>Delete all notes for this address</span></label>
  <label class="permchk addrremchk"><input type="checkbox" id="addrremfiles"><span class="permbox"></span><span>Delete all files for this address</span></label>
  <p class="addrremhint" id="addrremhint" style="display:none">Files live in the Main Folder shared by all addresses.</p>
  <div class="addrremrow"><button class="btn" id="addrremcancel">Cancel</button><button class="btn addrremsave" id="addrremconfirm"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg> Delete</button></div>
</div></div>
<script>
const $ = s => document.querySelector(s);
const drop = $("#drop"), picker = $("#picker");
const esc = s => s.replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const SVG = {
  transcribe: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="#22d3ee" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3h8l4 4v13a1.5 1.5 0 0 1 -1.5 1.5h-10.5A1.5 1.5 0 0 1 4.5 20V4.5A1.5 1.5 0 0 1 6 3z"/><path d="M14 3v4.2h4.2"/><path d="M8.3 12.2h7.4M8.3 15.6h7.4M8.3 19h4.6"/></svg>',
  translate: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="#a78bfa" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9.2"/><path d="M2.8 12h18.4"/><path d="M12 2.8a4.6 9.2 0 1 1 0 18.4 4.6 9.2 0 1 1 0 -18.4"/></svg>',
  edit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.828 2.828 0 114 4L7.5 20.5 2 22l1.5-5.5L17 3z"/></svg>',
  copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>',
  dl: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>',
  share: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>',
  del: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>',
  open: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
  note: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/><path d="M8.5 10h7M8.5 13.5h4.5"/></svg>',
  star: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3.6l2.5 5.2 5.7.7-4.2 4 1.1 5.6L12 16.4l-5.1 2.7L8 13.5l-4.2-4 5.7-.7z"/></svg>',
};

/* ---- single-link lock (v2.7.83, profiles removed) ---- */
const _origFetch = window.fetch.bind(window);
let AUTH = { locked:false, guest_locked:false, guest_delete_allowed:false, guest_notes_delete_allowed:false, permissions:{download_files:true, upload_files:true, delete_files:false, add_notes:true, delete_notes:false, star_notes:true}, can_download_files:true, can_upload_files:true, can_add_notes:true, can_star_notes:true, can_delete_files:true, can_delete_notes:true, authed:true, host:false, address_name:"", url:"" };
let justUnlockedAt = 0;
// v2.7.85: every same-origin request declares the link this page
// thinks it is on (X-Drop-Link). The server refuses a declared link
// that is not its current link, so a page left open across a link
// change elsewhere stops connecting instead of silently showing the
// new link's files. checkAuth() itself uses _origFetch (no header)
// so it can always learn the current link.
// v2.7.88: desktop host proof. Set ONLY from the pywebview JS
// bridge (Api.host_token) in the desktop window itself -- LAN
// browsers have no such bridge, so they can never obtain it. Kept
// in JS memory only: never localStorage, never a URL, never shown.
let DROP_HOST_TOKEN = "";
async function requestHostToken(){
  try {
    if(!hasBridge() || !window.pywebview.api.host_token) return false;
    const t = await window.pywebview.api.host_token();
    if(typeof t === "string" && t){ DROP_HOST_TOKEN = t; return true; }
  } catch(e){}
  return false;
}
function addressHeaders(extra){
  const h = Object.assign({}, extra || {});
  if(AUTH && AUTH.address_name){ h["X-Drop-Address"] = AUTH.address_name; h["X-Drop-Link"] = AUTH.address_name; }
  if(DROP_HOST_TOKEN) h["X-Drop-Host"] = DROP_HOST_TOKEN;
  return h;
}
window.fetch = async (...a) => {
  const t0 = Date.now();
  let url = "", init = {};
  if(typeof a[0] === "string"){ url = a[0]; init = a[1] || {}; }
  if(url.startsWith("/")){
    init = Object.assign({}, init, {headers: addressHeaders(init.headers)});
    a = [url, init];
  }
  const r = await _origFetch(...a);
  // Stale 401s: a files/notes poll started BEFORE a successful login
  // must not pop the lock screen back up after unlocking.
  // v2.7.90: a 401 for a guest shows the guest LOGIN PAGE (page 1),
  // never the old lock overlay; for the desktop host window it
  // shows nothing at all (the host is never locked out -- see
  // showLock, which early-returns on the bridge).
  if(r.status === 401 && t0 >= justUnlockedAt){ try { const j = await r.clone().json(); if(j && j.need_auth){
    // v2.8.33 (1): a 401 while the guest LOGIN page is already
    // open is expected -- the 5s polls (files/notes/status)
    // run unauthed there and 401 by design. Bouncing through
    // showLock()/checkAuth() again would yank the Saved view
    // back to the login form every 5s (and, with checkAuth's
    // pill refresh, could spin: checkAuth -> loadStatus -> 401
    // -> here -> checkAuth ...). Only bounce when the user is
    // NOT already on the login page: a real session loss on
    // the main page still pops the login page, as before.
    const _gl = document.querySelector("#guestlogin");
    if(!(_gl && _gl.classList.contains("open"))){ showLock(); checkAuth(); }
  } } catch(e){} }
  return r;
};
async function postJ(path, data){
  try {
    const r = await _origFetch(path, {method:"POST", headers: addressHeaders({"Content-Type":"application/json"}), body: JSON.stringify(data || {})});
    return await r.json();
  } catch(e){ return {ok:false}; }
}
// v2.7.92 address colours (mirror of the server address_color):
// FNV-1a 32-bit over the UTF-8 bytes of the sanitised lowercase
// address key, index into the same 8-colour palette.
const ADDRESS_PALETTE = ["#0ea5e9", "#8b5cf6", "#ec4899", "#d97706", "#059669", "#0891b2", "#db2777", "#65a30d"];
// v2.7.94 text colours (mirror of the server address_text_color):
// same index, darkened so coloured address TEXT reads on light cards.
const ADDRESS_TEXT_PALETTE = ["#0284c7", "#7c3aed", "#be185d", "#b45309", "#047857", "#0e7490", "#9d174d", "#4d7c0f"];
function addressTextColorForKey(key){
  const bytes = (typeof TextEncoder !== "undefined") ? new TextEncoder().encode(key || "") : Array.from(key || "").map(c => c.charCodeAt(0));
  let h = 2166136261;
  for(const b of bytes){ h ^= b; h = Math.imul(h, 16777619) >>> 0; }
  return ADDRESS_TEXT_PALETTE[h % ADDRESS_TEXT_PALETTE.length];
}
const LINK_ICON = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>';
// v2.7.94 top pill: link icon inside the pill + the address name
// in its deterministic text colour. No dot, no prefix.
function addressTopHtml(name, key){
  const col = addressTextColorForKey(key || addressKeyOf(name));
  return LINK_ICON + '<span class="addname" style="color:' + col + '">' + esc(name) + '</span>';
}
function addressKeyOf(n){ return (n || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/-+/g, "-").replace(/^-|-$/g, "").slice(0, 32).replace(/^-|-$/g, ""); }
function addressColorForKey(key){
  const bytes = (typeof TextEncoder !== "undefined") ? new TextEncoder().encode(key || "") : Array.from(key || "").map(c => c.charCodeAt(0));
  let h = 2166136261;
  for(const b of bytes){ h ^= b; h = Math.imul(h, 16777619) >>> 0; }
  return ADDRESS_PALETTE[h % ADDRESS_PALETTE.length];
}
function addressDotHtml(name, key){
  const col = addressColorForKey(key || addressKeyOf(name));
  return '<span class="addot" style="background:' + col + '"></span>' + esc(name);
}
// v2.7.92 futuristic-classic eye: almond outline + iris; crossed
// while the preview is hashed (hidden), open once revealed.
function eyeSVG(open){
  const iris = open ? '<circle cx="12" cy="12" r="3" fill="currentColor" stroke="none"/><circle cx="13.2" cy="10.8" r="0.9" fill="#ffffff" stroke="none"/>' : '<circle cx="12" cy="12" r="3" fill="none" opacity=".45"/>';
  return '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/>' + iris + (open ? '' : '<line x1="4" y1="4" x2="20" y2="20"/>') + '</svg>';
}
function paintEyeBtn(btn, revealed){
  if(!btn) return;
  btn.innerHTML = eyeSVG(!!revealed);
  btn.classList.remove("eyesnap"); void btn.offsetWidth; btn.classList.add("eyesnap");
  setTimeout(() => btn.classList.remove("eyesnap"), 400);
}
// v2.7.92 lock/unlock click sound: a tiny WebAudio click, with a
// silent fallback when audio is unavailable. No file, no download.
function playLockSound(locked){
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if(!AC) return;
    const ctx = new AC();
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.connect(g); g.connect(ctx.destination);
    const t = ctx.currentTime;
    o.frequency.setValueAtTime(locked ? 880 : 520, t);
    o.frequency.exponentialRampToValueAtTime(locked ? 440 : 780, t + 0.09);
    g.gain.setValueAtTime(0.12, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.12);
    o.start(t); o.stop(t + 0.13);
    setTimeout(() => { try { ctx.close(); } catch(e){} }, 200);
  } catch(e){}
}
function animateLockIcon(){
  ["#linklock", "#sblock"].forEach(sel => {
    const el = $(sel); if(!el) return;
    el.classList.remove("lockanim"); void el.offsetWidth; el.classList.add("lockanim");
    setTimeout(() => el.classList.remove("lockanim"), 500);
  });
}
// v2.7.92 host admin POST without a declared-address header: the
// sessions list already travels header-free, and the revoke call
// now does too, so a stale page can never 401 a disconnect.
async function postHostJ(path, data){
  try {
    const hh = {"Content-Type": "application/json"};
    if(DROP_HOST_TOKEN) hh["X-Drop-Host"] = DROP_HOST_TOKEN;
    const r = await _origFetch(path, {method: "POST", headers: hh, body: JSON.stringify(data || {})});
    return await r.json();
  } catch(e){ return {ok: false}; }
}
// v2.7.92 real-time open-address detection (guest login page).
// Debounced on typing, never only on Connect: when the typed
// address is this PC's current address and needs no password,
// the password field greys out and the note below it says so.
// A stale locally saved password for an address the PC has
// since opened is dropped, so the dropdown never again claims
// that address needs one.
let _openAddrTimer = null;
async function checkOpenAddress(name){
  const pw = $("#gloginpw"), note = $("#gloginpwstate");
  if(!pw) return;
  // v2.8.36 (3): the guest Save password checkbox follows the
  // password field -- disabled (greyed out) on an open address,
  // re-enabled otherwise.
  const reset = () => { pw.disabled = false; if(note) note.textContent = ""; const _sc = $("#gloginsavechk"); if(_sc) _sc.disabled = false; };
  if(!name){ reset(); return; }
  try {
    const r = await _origFetch("/api/addressinfo?address=" + encodeURIComponent(name));
    const j = await r.json();
    if(!j.ok || !j.known){ reset(); return; }
    if(!j.needs_password){
      const disp = j.address || name;
      const key = addressKeyOf(disp);
      const saved = guestSavedAddressPw();
      let stale = false;
      for(const k in saved){ if(addressKeyOf(k) === key){ removeGuestSavedAddressPw(k); stale = true; } }
      if(stale) renderGuestRecent();
      pw.disabled = true; pw.value = "";
      // v2.8.38 (2): an open address has no saved password to
      // show -- the edit-flow state goes with the field.
      _glPwSt.saved = ""; _glPwSt.shown = false;
      // v2.8.36 (3): open address -- no password to save, so the
      // Save password checkbox is disabled and unchecked.
      const _sc2 = $("#gloginsavechk"); if(_sc2){ _sc2.disabled = true; _sc2.checked = false; }
      // v2.8.18 (5): the open-address note under the password
      // field, green like the APK: "No password set for this
      // address, click Connect." This reinstates the note the
      // 2.8.7 round removed (round22) -- Essef Nov 5 wants the
      // web login to match the APK here.
      if(note) note.textContent = "No password set for this address, click Connect.";
    } else reset();
  } catch(e){ reset(); }
}
function debounceOpenAddress(){
  if(_openAddrTimer) clearTimeout(_openAddrTimer);
  _openAddrTimer = setTimeout(() => {
    const f = $("#gloginlink"); if(f) checkOpenAddress(f.value.trim());
  }, 300);
}
// Shared link-name rules (mirror the server): letters, numbers,
// hyphen, underscore, start with letter/number, max 32. Dots are
// never silently rewritten -- they are rejected with a message.
function validateAddressName(name){
  if(!name) return "Type an address name first";
  if(name.indexOf(".") !== -1) return "Dots are not allowed in address names: your address name becomes a folder name on the PC and part of the .local address, so a dot would break both. Use letters, numbers, hyphen (-) or underscore (_) instead (up to 32 characters).";
  if(!/^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$/.test(name)) return "Address names can only use letters, numbers, hyphen (-) and underscore (_), must start with a letter or number, and be at most 32 characters. Dots are not allowed: your address name becomes a folder name on the PC and part of the .local address, so a dot would break both.";
  return "";
}
// A pasted desktop link ("http://essef.local:<port>/", "essef.local:<port>",
// "essef.local") -> its bare link name. Anything else -> null (it is a
// typed name, not a pasted address). Port/host come from the pasted
// text itself or the live page -- never a hard-coded default.
// v2.8.33: a dotted host is an IP / URL form, not a name. When it
// names THIS server -- the page's own host, or the LAN-IP host from
// /api/authstate connect_url (the URL the QR code and the copy
// buttons give out) -- it resolves to this PC's current address
// name, so typing the copied link http://10.0.0.85:8000/ (or the
// bare 10.0.0.85:8000) into the Address field connects instead of
// failing with the dots error. A dotted host for any OTHER machine
// is not a name at all (foreignPastedUrl handles navigating to it).
function _connectUrlHost(){
  try {
    if(AUTH && AUTH.connect_url){
      const u = String(AUTH.connect_url).replace(/^https?:\/\//i, "").split("/")[0];
      return {host: u.split(":")[0], port: u.split(":")[1] || ""};
    }
  } catch(e){}
  return {host: "", port: ""};
}
function _isThisServerHost(host, port){
  const h = (host || "").toLowerCase();
  const cu = _connectUrlHost();
  const thisPort = (location.port || "") || cu.port;
  if(h === (location.hostname || "").toLowerCase())
    return !port || port === thisPort;
  if(cu.host && h === cu.host.toLowerCase())
    return !port || port === cu.port || port === (location.port || "");
  // v2.8.33 (1)(B): the address the server calls itself -- the
  // dashed name from /api/authstate (e.g. 10-0-0-85-8000 for
  // 10.0.0.85:8000). This is the check that works however the
  // page was reached: a guest loaded through a forwarder (or
  // any URL whose host is not the LAN IP) has location.hostname
  // != the typed LAN IP, so the two checks above missed it and
  // a dotted address typed from the PC's copied link / QR URL
  // was wrongly treated as a FOREIGN machine -- the browser
  // navigated away to a dead URL instead of connecting (caught
  // by test_item1_dotted_ip_connect_succeeds). Dots become
  // dashes; with a typed port the full dashed name must match,
  // without one the host part of the name must match.
  if(AUTH && AUTH.address_name && /^\d+\.\d+\.\d+\.\d+$/.test(h)){
    const dashed = h.split(".").join("-");
    const name = (AUTH.address_name || "").toLowerCase();
    if(port){ if(dashed + "-" + port === name) return true; }
    else {
      if(dashed === name) return true;
      const m = name.match(/^(.*)-\d+$/);
      if(m && m[1] === dashed) return true;
    }
  }
  return false;
}
// v2.8.33: a pasted / typed IP-or-URL form naming a DIFFERENT
// machine (not this server -- see _isThisServerHost) is a
// navigation, not a name: the URL to open it at, else null.
function foreignPastedUrl(v){
  const t = (v || "").trim();
  if(!t) return null;
  let rest = t;
  const low = rest.toLowerCase();
  if(low.indexOf("http://") === 0) rest = rest.slice(7);
  else if(low.indexOf("https://") === 0) rest = rest.slice(8);
  else if(t.indexOf("/") === -1 && t.indexOf(":") === -1 && !/^\d+\.\d+\.\d+\.\d+$/.test(t)) return null;
  rest = rest.split("/")[0].trim();
  const parts = rest.split(":");
  const host = parts[0];
  const port = parts[1] || "";
  if(!host || host.indexOf(".") === -1) return null;
  if(host.toLowerCase().endsWith(".local")) return null;
  if(_isThisServerHost(host, port)) return null;
  return "http://" + host + (port ? ":" + port : "") + "/";
}
function parsePastedAddress(v){
  const t = (v || "").trim();
  if(!t) return null;
  let rest = t;
  const low = rest.toLowerCase();
  if(low.indexOf("http://") === 0) rest = rest.slice(7);
  else if(low.indexOf("https://") === 0) rest = rest.slice(8);
  else if(t.indexOf("/") === -1 && t.indexOf(".local") === -1 && t.indexOf(":") === -1
          && !/^\d+\.\d+\.\d+\.\d+$/.test(t)) return null;
  rest = rest.split("/")[0].trim();
  const parts = rest.split(":");
  let host = parts[0];
  const port = parts[1] || "";
  if(host.toLowerCase().endsWith(".local")) host = host.slice(0, -6);
  if(!host) return null;
  if(host.indexOf(".") !== -1){
    if(!_isThisServerHost(host, port)) return null;
    return (AUTH && AUTH.address_name) || null;
  }
  return host;
}
function shakeAddressField(msg){
  const inp = $("#lkin");
  const err = $("#lkerr");
  if(err) err.textContent = msg || "";
  if(inp){ inp.classList.remove("shake"); void inp.offsetWidth; inp.classList.add("shake"); inp.focus(); }
}
let lockHistoryPushed = false;
// v2.7.90 GUEST PAGER + NO HOST LOCK FLASH:
//  * The desktop host window (pywebview bridge present) NEVER
//    sees a lock screen, not even briefly: the bridge token may
//    still be loading when the first auth check runs, and the old
//    code flashed "Drop is locked" until the token arrived.
//    showLock() therefore early-returns on the bridge, and the
//    boot sequence fetches the host token BEFORE the first
//    checkAuth (see the bottom of the script).
//  * A guest NEVER sees the lock overlay either: showLock()
//    routes guests to the guest LOGIN PAGE (page 1), which is
//    also the only "locked page" left -- it appears only when
//    the PC suddenly sets a password on a link the guest
//    previously used without one (or when the guest is simply
//    not connected yet). Disconnect never routes here either:
//    a disconnected guest lands on the login page and can
//    reconnect to an unlocked link with no lock screen at all.
function showLock(){
  if(hasBridge()) return;
  if(!(AUTH && AUTH.host)){ showGuestLogin(); return; }
  const w = $("#lockwrap"); if(w && !w.classList.contains("open")){ w.classList.add("open"); const i = $("#lockpw"); if(i) setTimeout(() => i.focus(), 60); }
  if(!lockHistoryPushed){ try { history.pushState({dropLock:1}, ""); lockHistoryPushed = true; } catch(e){} } }
function hideLock(){ const w = $("#lockwrap"); if(w) w.classList.remove("open"); lockHistoryPushed = false; }
// ---- guest web pager (v2.7.90): page 1 = login, page 2 = main ----
// connectedLink: the link this guest last CONNECTED to (explicit
// login/connect), kept in localStorage. The guest page NEVER
// auto-follows a PC link change: if the server's current link
// differs from connectedLink, the guest is sent back to page 1
// and must enter the link (+ password, if set) again. Staying
// connected while the PC keeps the same link needs no action:
// the session token keeps working across polls.
function guestConnectedAddress(){ try { return localStorage.getItem("drop_connected_link") || ""; } catch(e){ return ""; } }
function setGuestConnectedAddress(v){ try { if(v) localStorage.setItem("drop_connected_link", v); else localStorage.removeItem("drop_connected_link"); } catch(e){} }
function addressUseCounts(){ try { return JSON.parse(localStorage.getItem("drop_link_use") || "{}"); } catch(e){ return {}; } }
function bumpAddressUse(link){ if(!link) return; try { const c = addressUseCounts(); c[link] = (c[link] || 0) + 1; localStorage.setItem("drop_link_use", JSON.stringify(c)); } catch(e){} }
function mostUsedAddress(){ const c = addressUseCounts(); let best = "", n = 0; for(const k in c){ if(c[k] > n){ n = c[k]; best = k; } } return best; }
function guestSavedAddressPw(){ try { return JSON.parse(localStorage.getItem("drop_guest_pw") || "{}"); } catch(e){ return {}; } }
function saveGuestAddressPw(link, pw){ if(!link || !pw) return; try { const m = guestSavedAddressPw(); m[link] = pw; localStorage.setItem("drop_guest_pw", JSON.stringify(m)); } catch(e){} }
function removeGuestSavedAddressPw(link){ try { const m = guestSavedAddressPw(); delete m[link]; localStorage.setItem("drop_guest_pw", JSON.stringify(m)); } catch(e){} }
// v2.7.92 GUEST SAVED-LINKS DROPDOWN: replaces the old pills.
// A closed field ("Saved addresses", or the link already typed)
// opens a floating list of this device's own previously used
// links (localStorage only -- never sent to the PC). Each row:
// name, masked password dots (from this device's own copy
// only) with eye reveal, delete icon. Delete removes the row
// from this device's history only and does NOT select it;
// selecting a row fills the link field (+ its saved password,
// masked by the password input) and does NOT connect by itself.
async function renderGuestRecent(){
  const list = $("#gddlist"); if(!list) return;
  const c = addressUseCounts();
  const names = Object.keys(c).sort((a, b) => c[b] - c[a]).slice(0, 20);
  const typed = ($("#gloginlink") && $("#gloginlink").value) || "";
  const selected = names.includes(typed) ? typed : "";
  const saved = guestSavedAddressPw();
  if(!names.length){
    list.innerHTML = '<div class="ddopt ddempty"><span class="ddname">No saved addresses yet.</span></div>';
    return;
  }
  // v2.8.36 (4): exact shared strings -- a saved copy on this
  // device shows dots; anything else reads "No Password Saved"
  // until the server state below corrects the current row.
  list.innerHTML = names.map(n => '<div class="ddopt' + (n === selected ? ' ddsel' : '') + '" data-name="' + esc(n) + '"><span class="ddname">' + addressDotHtml(n) + '</span><span class="ddpw">' + (saved[n] ? "••••••" : "No Password Saved") + '</span>' +
    (saved[n] ? '<button class="ddeye" data-gdeye="' + esc(n) + '" title="Show saved password">' + eyeSVG(false) + '</button>' : "") +
    '<button class="dddel" data-gddel="' + esc(n) + '" title="Remove from history">' + SVG.del + '</button></div>').join("");
  list.querySelectorAll(".ddopt").forEach(opt => {
    opt.addEventListener("mouseenter", () => opt.classList.add("ddhover"));
    opt.addEventListener("mouseleave", () => opt.classList.remove("ddhover"));
    opt.onclick = () => {
      const name = opt.dataset.name;
      const f = $("#gloginlink"); if(f) f.value = name;
      const p = $("#gloginpw"); if(p) p.value = saved[name] || "";
      // v2.8.38 (2): the row just filled the saved password --
      // the edit flow must know it is showing, and the focus
      // below is programmatic, so it must NOT clear it.
      if(saved[name]){ _glPwSt.saved = saved[name]; _glPwSt.shown = true; }
      else { _glPwSt.saved = ""; _glPwSt.shown = false; }
      const sc = $("#gloginsavechk"); if(sc) sc.checked = !!saved[name];
      const chev = $("#gddchevbtn"); list.classList.remove("open"); if(chev) chev.textContent = "▾";
      if(p){ _glPwSt.keepFocus = true; p.focus(); }
      checkOpenAddress(name);
    };
  });
  list.querySelectorAll("[data-gdeye]").forEach(b => { b.onclick = (ev) => {
    ev.stopPropagation();
    const row = b.closest(".ddopt");
    const pwSpan = row.querySelector(".ddpw");
    if(pwSpan.dataset.revealed){ pwSpan.textContent = "••••••"; delete pwSpan.dataset.revealed; paintEyeBtn(b, false); return; }
    const pw = guestSavedAddressPw()[b.dataset.gdeye];
    if(pw){ pwSpan.textContent = pw; pwSpan.dataset.revealed = "1"; paintEyeBtn(b, true); }
  }; });
  list.querySelectorAll("[data-gddel]").forEach(b => { b.onclick = (ev) => {
    ev.stopPropagation();
    const name = b.dataset.gddel;
    const c2 = addressUseCounts(); delete c2[name];
    try { localStorage.setItem("drop_link_use", JSON.stringify(c2)); } catch(e){}
    removeGuestSavedAddressPw(name);
    toast("Removed " + name + " from this device — the files remain on the PC.");
    renderGuestRecent();
  }; });
  // v2.8.36 (4): the CURRENT address's row shows the server's
  // password state, not just this device's copy -- a locked
  // address with nothing saved here reads "No Password Saved",
  // an open address reads "No password". Other rows are history
  // only (the server knows nothing about them), so they keep the
  // local "No Password Saved" when this device holds no copy.
  try {
    const curName = (typeof AUTH !== "undefined" && AUTH && AUTH.address_name) || "";
    if(curName && !saved[curName]){
      let row = null;
      list.querySelectorAll(".ddopt").forEach(o => { if(o.dataset.name === curName) row = o; });
      if(row){
        const rr = await _origFetch("/api/addressinfo?address=" + encodeURIComponent(curName));
        const jj = await rr.json();
        if(jj.ok && jj.known && row.isConnected){
          const sp = row.querySelector(".ddpw");
          if(sp && !sp.dataset.revealed) sp.textContent = jj.needs_password ? "No Password Saved" : "No password";
        }
      }
    }
  } catch(e){}
}
const _gddchev = $("#gddchevbtn");
// v2.8.36 (4): re-render on open, so the rows (and the
// current row's server password state) are fresh every time
// the dropdown is shown.
if(_gddchev) _gddchev.onclick = (ev) => { ev.stopPropagation(); const l = $("#gddlist"); if(!l) return; renderGuestRecent(); const open = l.classList.toggle("open"); _gddchev.textContent = open ? "▴" : "▾"; };
if(!window._gddDocBound){ window._gddDocBound = true; document.addEventListener("click", (e) => { const l = document.querySelector("#gddlist"); const c = document.querySelector("#gddchevbtn"); if(l && (!e.target.closest || !e.target.closest("#gddwrap"))){ l.classList.remove("open"); if(c) c.textContent = "▾"; } }); }
function showGuestMain(){
  // v2.8.39 (2): logging in ALWAYS opens the Upload tab on MB
  // (and web). The boot code restores the last-used tab from
  // localStorage ("dropit_tab"), so a guest whose previous
  // session ended on the Files tab (the Saved view) landed
  // there again after login. A login transition -- the login
  // page was showing, or the Connect modal was hiding it
  // (dataset.lkHidden) -- resets to Upload, exactly once:
  // later polls call showGuestMain while already authed and
  // must NOT yank the user off the tab they are using. The
  // lkHidden flag is consumed here so it cannot reset again.
  const gl0 = $("#guestlogin");
  const _wasLogin = !!(gl0 && (gl0.classList.contains("open") || gl0.dataset.lkHidden));
  if(gl0 && gl0.dataset.lkHidden) delete gl0.dataset.lkHidden;
  const tb = document.querySelector(".topbar"); if(tb) tb.style.display = "";
  const gl = $("#guestlogin"); if(gl) gl.classList.remove("open");
  const b = document.querySelector(".board"); if(b) b.style.display = "";
  const mt = document.querySelector(".mtabs"); if(mt) mt.style.display = "";
  if(_wasLogin && typeof setTab === "function") setTab("send");
}
function showGuestLogin(msg){
  const gl = $("#guestlogin"); if(!gl) return;
  // v2.8.13: the menu must NOT appear on the login page — the
  // top bar (hamburger) hid nothing here before: showGuestLogin
  // hid .board/.mtabs but left .topbar visible, so the drawer
  // could still be opened from the login page. Hide the top bar
  // and close the drawer; showGuestMain restores the top bar.
  const tb = document.querySelector(".topbar"); if(tb) tb.style.display = "none";
  try { openSidebar(false); } catch(e){}
  const b = document.querySelector(".board"); if(b) b.style.display = "none";
  const mt = document.querySelector(".mtabs"); if(mt) mt.style.display = "none";
  gl.classList.add("open");
  // v2.8.37 (5): if the guest Connect modal is already open,
  // it IS the login surface -- the page-1 form behind it must
  // not reappear with a second Save Password checkbox (a 401
  // bounce while the modal is up used to re-add .open here).
  const _lw0 = $("#lkwrap");
  if(_lw0 && _lw0.style.display === "flex" && $("#lkbox") && $("#lkbox").classList.contains("guestcard")){ gl.classList.remove("open"); gl.dataset.lkHidden = "1"; }
  // v2.8.33 (3): a bounce back to the login page always lands on the
  // login form, never on the saved-files view -- EXCEPT (v2.8.17)
  // when the guest just closed a saved file's viewer: the
  // viewer-close history.back() bounces through showLock ->
  // showGuestLogin while unauthed, and that must return to the
  // Saved view, not the login form. _savedReturn is set when a
  // saved file is opened into the viewer and consumed here.
  // v2.8.33: do NOT consume it while the viewer is still OPEN.
  // The 5s poll's 401s bounce through showLock/showGuestLogin
  // while the viewer is up, and consuming the flag there meant
  // a preview watched for more than a few seconds closed back
  // onto the login form instead of the Saved list. While the
  // viewer is open the flag stays set; the viewer close is
  // what consumes it.
  if(window._savedReturn){
    const _viewerOpen = document.querySelector("#viewer") && document.querySelector("#viewer").classList.contains("open");
    if(!_viewerOpen){ window._savedReturn = false; if(typeof showSavedView === "function"){ showSavedView(); } }
  }
  else if(typeof showLoginForm === "function") showLoginForm();
  const lk = $("#gloginlink");
  if(lk && !lk.value){ const mu = mostUsedAddress(); if(mu) lk.value = mu; }
  renderGuestRecent();
  if(lk && lk.value) checkOpenAddress(lk.value.trim());
  // v2.8.39 (1): returning to the login page auto-fills the
  // saved password for the prefilled address (dots, via the
  // 2.8.38 edit flow -- focus empties it, blur restores it),
  // so a saved session reconnects with one tap on Connect.
  // An unchecked session saved nothing, so nothing fills.
  // checkOpenAddress above clears the field again if the
  // address turns out to be open (and drops the stale copy),
  // so this only ever fills a locked address's saved copy.
  const _pw0 = $("#gloginpw");
  if(lk && _pw0 && lk.value && !_pw0.disabled && !_pw0.value){
    const _sv0 = guestSavedAddressPw()[lk.value.trim()];
    if(_sv0){ _pw0.value = _sv0; _glPwSt.saved = _sv0; _glPwSt.shown = true; }
  }
  const m = $("#gloginmsg");
  // v2.8.18 (6): with no specific message, the login page says
  // "Disconnected — enter the address and password to connect
  // again" under the Connect button, like the APK login.
  if(m) m.textContent = (msg !== undefined) ? (msg || "") : "Disconnected — enter the address and password to connect again";
  const err = $("#gloginerr"); if(err && msg === undefined) err.textContent = "";
  hideLockOverlayOnly();
}
// v2.8.15 (Essef Nov 5): "Saved on this device" on the guest login
// page -- the web version of the APK's offline saved mode. The
// list is the files this browser saved through Drop: the
// localStorage dropit_dl ledger (name -> {size, ts}) plus the
// IndexedDB blob cache (DBCACHE), so Open works offline with no
// PC connection and no fetch. No menu involved -- the menu still
// never appears on the login page.
function getSavedFiles(){
  let dl = {};
  try { dl = JSON.parse(localStorage.getItem("dropit_dl") || "{}"); } catch(e){}
  return Object.keys(dl).map(n => ({name: n, size: (dl[n] && dl[n].size) || (typeof dl[n] === "number" ? dl[n] : 0), ts: (dl[n] && dl[n].ts) || 0}))
    .sort((a, b) => (b.ts || 0) - (a.ts || 0));
}
function paintSavedFiles(){
  const list = $("#gsavedlist"); if(!list) return;
  const files = getSavedFiles();
  const empty = $("#gsavedempty"); if(empty) empty.style.display = files.length ? "none" : "";
  // v2.8.17 (Essef Nov 5): every saved row has a THUMBNAIL and
  // ONE button only -- Open. Tapping the thumbnail or Open
  // opens the file in PREVIEW MODE (openBlob viewer). Thumbnails
  // fill in async from the on-phone blob cache (image frame /
  // video frame); a file with no stored blob keeps its
  // file-type icon, so a row never shows a broken image.
  list.innerHTML = files.map(f => `<div class="gsavedrow" data-gsaved="${esc(f.name)}"><span class="fsel">${SVG.check}</span><span class="gsthumbwrap" data-thumb="${esc(f.name)}" title="Preview"><span class="fic">${iconFor(f.name)}</span></span><span class="gsnamewrap" data-savedname="${esc(f.name)}" title="Preview"><span class="gsname">${esc(f.name)}</span><span class="gsmeta">${f.size ? fmt(f.size) : ""}${f.ts ? " &middot; " + new Date(f.ts * 1000).toLocaleDateString() : ""}</span></span><button class="btn primary" type="button" data-open-saved="${esc(f.name)}">Open</button></div>`).join("");
  // v2.8.36 (8): in selection mode a tap toggles the row
  // instead of opening / previewing it -- the toggle lives
  // on the ROW (one toggle per tap, so the checkbox itself,
  // the thumbnail, the name and Open all toggle alike).
  list.querySelectorAll(".gsavedrow").forEach(r => r.addEventListener("click", () => { if(gsvSel) gsvToggle(r.dataset.gsaved); }));
  list.querySelectorAll("[data-open-saved]").forEach(b => b.onclick = () => { if(gsvSel) return; openSavedFile(b.getAttribute("data-open-saved")); });
  list.querySelectorAll("[data-thumb]").forEach(w => w.onclick = () => { if(gsvSel) return; previewSavedFile(w.getAttribute("data-thumb")); });
  // v2.8.33 (3): tapping the file NAME previews it too -- the
  // name is the row's main tap target, and until now it had no
  // handler at all, so tapping the file itself did nothing
  // (only the thumbnail and the Open button worked).
  list.querySelectorAll("[data-savedname]").forEach(w => w.onclick = () => { if(gsvSel) return; previewSavedFile(w.getAttribute("data-savedname")); });
  files.forEach(async f => {
    let blob = null;
    try { blob = MEMBLOBS[f.name] || await DBCACHE.get(f.name); } catch(e){}
    if(!blob){
      // v2.8.39 (4): the ledger lists the file but this device
      // no longer stores it -- while the PC is reachable Open
      // re-downloads it (see openSavedFileOS), so the row stays
      // normal; offline the row must say the file is gone.
      if(!(AUTH && AUTH.authed)){
        const row = list.querySelector(`[data-gsaved="${CSS.escape(f.name)}"]`);
        if(row && row.isConnected){
          row.classList.add("gsaved-gone");
          const _ob = row.querySelector("[data-open-saved]");
          if(_ob){ _ob.disabled = true; _ob.textContent = "Removed"; }
          const _meta = row.querySelector(".gsmeta");
          if(_meta) _meta.textContent = "file has been removed";
        }
      }
      return;
    }
    const wrap = list.querySelector(`[data-thumb="${CSS.escape(f.name)}"]`);
    if(!wrap || !wrap.isConnected) return;
    const url = URL.createObjectURL(blob);
    if(/\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(f.name)){
      wrap.innerHTML = `<img class="gsthumb" src="${url}" alt="">`;
    } else if(/\.(mp4|mov|m4v|webm|mkv|avi)$/i.test(f.name)){
      wrap.innerHTML = `<video class="gsthumb" preload="metadata" muted playsinline src="${url}#t=0.5"></video>`;
    }
  });
  // v2.8.36 (8): selection-mode state survives a repaint; the
  // Delete button is disabled when there is nothing to delete.
  list.classList.toggle("selmode", gsvSel);
  gsvPaint();
  const gd = $("#gsaveddel"); if(gd) gd.disabled = !files.length;
}
// v2.8.36 (8): file-selection mode on the guest "Saved on this
// device" screen -- same shape as the Files tab (Select All /
// Cancel / Delete, "Select files") and the in-app Saved viewer
// (sv*): the head Delete button enters the mode, rows toggle
// on tap, Delete removes the picked files from this device
// only (localStorage ledger + IndexedDB blob cache + memory).
let gsvSel = false;
const gsvPicked = new Set();
function gsvPaint(){
  const list = $("#gsavedlist"); if(!list) return;
  list.querySelectorAll(".gsavedrow").forEach(r => r.classList.toggle("picked", gsvPicked.has(r.dataset.gsaved)));
}
function gsvUpd(){
  const c = $("#gsvcount"), ok = $("#gsvconfirm"); if(!c || !ok) return;
  const n = gsvPicked.size;
  c.textContent = n ? n + " selected" : "Select files";
  ok.textContent = n ? "Delete (" + n + ")" : "Delete";
  ok.disabled = !n;
}
function gsvSet(on){
  gsvSel = on;
  const list = $("#gsavedlist"); if(list) list.classList.toggle("selmode", on);
  const b = $("#gsvbar"); if(b) b.classList.toggle("show", on);
  if(!on){ gsvPicked.clear(); gsvPaint(); }
  gsvUpd();
}
function gsvOpen(){
  // NB: NO ovOpened/ovClosed history push here, unlike the
  // Files tab -- this screen is used while UNAUTHENTICATED,
  // and a history.back() on exit would trip the popstate
  // listener that shows the lock screen for unauthed users.
  // The on-screen Back button exits selection mode instead.
  gsvSet(true);
}
function gsvExit(){
  gsvSet(false);
}
function gsvToggle(name){
  if(!name) return;
  if(gsvPicked.has(name)) gsvPicked.delete(name); else gsvPicked.add(name);
  gsvPaint(); gsvUpd();
}
const _gsvd = $("#gsaveddel"); if(_gsvd) _gsvd.onclick = () => { if(!getSavedFiles().length) return; if(gsvSel) gsvExit(); else gsvOpen(); };
const _gsvc = $("#gsvcancel"); if(_gsvc) _gsvc.onclick = () => gsvExit();
const _gsva = $("#gsvall"); if(_gsva) _gsva.onclick = () => {
  const names = getSavedFiles().map(f => f.name);
  if(!names.length) return;
  if(names.every(n => gsvPicked.has(n))) names.forEach(n => gsvPicked.delete(n));
  else names.forEach(n => gsvPicked.add(n));
  gsvPaint(); gsvUpd();
};
const _gsvo = $("#gsvconfirm"); if(_gsvo) _gsvo.onclick = async () => {
  const names = [...gsvPicked];
  if(!names.length) return;
  if(!confirm("Remove " + names.length + " file(s) from this phone?")) return;
  for(const n of names){
    delete DLSTATE[n];
    try{ await DBCACHE.del(n); }catch(e){}
    delete MEMBLOBS[n];
  }
  try{ localStorage.setItem("dropit_dl", JSON.stringify(DLSTATE)); }catch(e){}
  gsvExit(); paintSavedFiles();
};
// v2.8.16: Preview for a saved file -- the in-app viewer
// (openBlob), never a blank screen. Every type is covered:
// image / video / audio / text / PDF / Word render in the
// viewer; .doc and offline .docx get client-side text
// extraction (see openBlob); any other type shows a preview
// card with the file's name, size and an Open button instead
// of failing silently.
async function previewSavedFile(name, inApp){
  // v2.8.17: opened from the login-page Saved view -- closing
  // the viewer returns there, not to the login form (see
  // showGuestLogin). The in-app Saved list (inApp) returns to
  // the main page instead, like every other file preview, so
  // it must NOT set _savedReturn.
  if(!inApp) window._savedReturn = true;
  const files = getSavedFiles();
  const f = files.find(x => x.name === name) || {name: name, size: 0};
  let blob = null;
  try { blob = MEMBLOBS[name] || await DBCACHE.get(name); } catch(e){}
  // v2.8.41 (5): a tap must OPEN something visible, not just
  // toast. A listed file whose blob is gone from this device
  // (and no PC session to re-download it from) gets a clear
  // card in the viewer instead of a toast that leaves the
  // user staring at the list.
  if(!blob && !(AUTH && AUTH.authed)){
    showViewer(name, '<div style="text-align:center;padding:24px"><p style="font-weight:700;margin:0 0 8px">' + esc(name) + '</p><p style="opacity:.65;margin:0 0 16px">That file is no longer stored on this device &mdash; connect to the PC and download it again.</p></div>');
    return;
  }
  try { await openBlob(f); } catch(e){ toast("Couldn't preview that file on this device"); }
}
// v2.8.40 (5): Open means OPEN, never another download -- the
// 2.8.39 "real download" just downloaded the file again every
// time it was clicked, which is not opening it (Essef Nov 7).
// How a saved file opens depends on where this page runs:
//  - desktop app (bridge): open_file, as before -- the local
//    file opens in the PC's default app.
//  - PC web ON the PC itself (host session, localhost URL):
//    POST /api/openlocal -- the server runs on this PC, so it
//    opens the file from PC storage in the default app.
//  - phone / guest web (MB and PC-web guests): the file lives
//    in this browser's storage, so the system share sheet opens
//    it: navigator.share({files}) shows Android's open-with
//    chooser, exactly like the APK's ACTION_VIEW -- pick an app,
//    no file lands in Downloads. If the browser cannot share
//    files, the saved file opens in a new tab to view there.
//    A download is never presented as an open.
async function openSavedFileOS(name){
  try{
    if(window.pywebview && window.pywebview.api && window.pywebview.api.open_file){
      const ok = await window.pywebview.api.open_file(name);
      if(ok) return true;
    }
  }catch(e){}
  // PC web on the PC itself: open from PC storage, default app.
  if(AUTH && AUTH.host){
    try{
      const r = await postHostJ("/api/openlocal", {name: name});
      if(r && r.ok){ toast("Opening " + name); return true; }
    }catch(e){}
    // refused (e.g. a LAN-URL session the server cannot prove
    // is this PC): fall through to the share sheet below.
  }
  let blob = null;
  try { blob = MEMBLOBS[name] || await DBCACHE.get(name); } catch(e){}
  if(!blob){
    if(!(AUTH && AUTH.authed)){ toast("That file has been removed from this device — connect to the PC and download it again"); return false; }
    try {
      const r = await fetch("/dl/" + encodeURIComponent(name));
      if(!r.ok) throw 0;
      blob = await r.blob();
      MEMBLOBS[name] = blob;
      await DBCACHE.put(name, blob);
    } catch(e){ toast("Couldn't open that file on this device"); return false; }
  }
  // System open-with chooser (MB): share the saved file to an app.
  const file = new File([blob], name, {type: blob.type || ""});
  try{
    if(navigator.canShare && navigator.canShare({files: [file]})){
      await navigator.share({files: [file]});
      return true;
    }
  }catch(e){
    if(e && e.name === "AbortError") return false;  // sheet dismissed: stay quiet
    if(e && e.name === "NotAllowedError"){
      toast("This browser won't open the app chooser here — opening the file to view instead");
    }
    // any other share failure: fall through to the tab view below.
  }
  // No share sheet on this browser: view the saved file in a new tab.
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank");
  setTimeout(() => URL.revokeObjectURL(url), 60000);
  return true;
}
async function openSavedFile(name){
  // v2.8.40 (5): Open hands the file to the OS / an app --
  // never another in-app preview, never a download. No viewer,
  // no _savedReturn.
  await openSavedFileOS(name);
}
// v2.8.16: offline text out of a .docx blob, with no PC and no
// library -- scan the zip's local file headers, inflate
// word/document.xml (deflate-raw, or stored), and read the
// <w:t> runs as paragraphs. Returns "" when it cannot parse.
async function docxTextFromBlob(blob){
  try {
    const buf = await blob.arrayBuffer();
    const bytes = new Uint8Array(buf);
    const dec = new TextDecoder("utf-8");
    let off = 0;
    while(off + 30 <= bytes.length){
      if(bytes[off] !== 0x50 || bytes[off + 1] !== 0x4B || bytes[off + 2] !== 0x03 || bytes[off + 3] !== 0x04) break;
      const dv = new DataView(buf, off, 30);
      const method = dv.getUint16(8, true);
      const csize = dv.getUint32(18, true);
      const nlen = dv.getUint16(26, true);
      const elen = dv.getUint16(28, true);
      const name = dec.decode(bytes.subarray(off + 30, off + 30 + nlen));
      const start = off + 30 + nlen + elen;
      if(name === "word/document.xml"){
        const chunk = bytes.subarray(start, start + csize);
        let xml;
        if(method === 0) xml = dec.decode(chunk);
        else if(method === 8 && typeof DecompressionStream !== "undefined"){
          const ds = new DecompressionStream("deflate-raw");
          xml = dec.decode(await new Response(new Blob([chunk]).stream().pipeThrough(ds)).arrayBuffer());
        } else return "";
        const paras = xml.split(/<\/w:p>/i).map(p => {
          const runs = [...p.matchAll(/<w:t[^>]*>([^<]*)<\/w:t>/gi)].map(m => m[1]);
          return runs.join("").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&apos;/g, "'");
        }).filter(t => t.trim());
        return paras.join("\\n\\n");
      }
      off = start + csize;
    }
  } catch(e){}
  return "";
}
// v2.8.16: readable text out of a legacy .doc blob, with no PC
// -- .doc stores text as plain runs, so keep the printable
// runs and drop the binary noise. Returns "" when nothing
// readable is found.
async function docTextFromBlob(blob){
  try {
    const buf = await blob.arrayBuffer();
    const text = new TextDecoder("windows-1252").decode(buf);
    const runs = text.split(/[^\\x20-\\x7E\\x0A\\x0D\\u00A0-\\u00FF]+/).filter(r => r.trim().length >= 4);
    const out = runs.join(" ").replace(/\s+/g, " ").trim();
    return out.length > 20 ? out : "";
  } catch(e){}
  return "";
}
function showSavedView(){
  const form = $("#gloginform"); if(form) form.style.display = "none";
  const view = $("#gsavedview"); if(view) view.classList.add("open");
  if(typeof gsvSet === "function") gsvSet(false);
  paintSavedFiles();
}
function showLoginForm(){
  const view = $("#gsavedview"); if(view) view.classList.remove("open");
  const form = $("#gloginform"); if(form) form.style.display = "";
}
const _gsb = $("#gsavedbtn"); if(_gsb) _gsb.onclick = showSavedView;
// v2.8.36 (8): while selection mode is on, Back exits the mode
// first instead of leaving the screen.
const _gsbk = $("#gsavedback"); if(_gsbk) _gsbk.onclick = () => { if(gsvSel){ gsvExit(); return; } showLoginForm(); };
function hideLockOverlayOnly(){ const w = $("#lockwrap"); if(w) w.classList.remove("open"); }
window.addEventListener("popstate", () => {
  if(AUTH && !AUTH.authed){ showLock(); }
});
// v2.7.89: can this viewer delete files? Host always; a guest
// only when the host's "Guests can delete files" toggle is ON
// (server /api/authstate supplies can_delete_files, and the
// server 403s guest deletes as backstop when it is OFF).
function canDeleteUI(){
  if(AUTH && AUTH.host) return true;
  return !!(AUTH && AUTH.can_delete_files);
}
function canDeleteNotesUI(){
  if(AUTH && AUTH.host) return true;
  return !!(AUTH && AUTH.can_delete_notes);
}
// v2.7.99: the other four permissions, mirroring the delete
// helpers (host always; a guest only when the address's set
// allows it -- server /api/authstate supplies the can_* flags).
function canDownloadUI(){
  if(AUTH && AUTH.host) return true;
  return !!(AUTH && AUTH.can_download_files);
}
function canUploadUI(){
  if(AUTH && AUTH.host) return true;
  return !!(AUTH && AUTH.can_upload_files);
}
function canAddNotesUI(){
  if(AUTH && AUTH.host) return true;
  return !!(AUTH && AUTH.can_add_notes);
}
function canStarUI(){
  if(AUTH && AUTH.host) return true;
  return !!(AUTH && AUTH.can_star_notes);
}
// v2.8.11: one permission update repaints ALL affected
// controls in a SINGLE pass. paintDeleteState() used to run
// synchronously from every list render + the 5s poll, so a
// permission flip repainted the Notes controls, then the
// Files controls a beat later as each list re-rendered.
// Calls now coalesce into one requestAnimationFrame paint.
let _permPaintQueued = false;
function paintDeleteState(){
  if(_permPaintQueued) return;
  _permPaintQueued = true;
  const _run = () => { _permPaintQueued = false; paintDeleteStateNow(); };
  if(typeof requestAnimationFrame === "function") requestAnimationFrame(_run);
  else setTimeout(_run, 0);
}
function paintDeleteStateNow(){
  const blocked = !!(AUTH && !AUTH.host && AUTH.authed && !canDeleteUI());
  const dab = $("#delallbtn"); if(dab) dab.classList.toggle("deloff", blocked);
  const dc = $("#delconfirm"); if(dc) dc.classList.toggle("deloff", blocked);
  const nblocked = !!(AUTH && !AUTH.host && AUTH.authed && !canDeleteNotesUI());
  const danb = $("#delallnotesbtn"); if(danb) danb.classList.toggle("deloff", nblocked);
  document.querySelectorAll("[data-del]").forEach(b => b.classList.toggle("deloff", nblocked));
  // v2.7.99: the same grey treatment, generalised from the
  // delete-only poll to all six permissions. A control stays
  // VISIBLE but greyed, and tapping it toasts the exact
  // no-permission message instead of acting (each action
  // handler below checks its own gate first; the grey class
  // here is the visual half).
  const dlBlocked = !!(AUTH && !AUTH.host && AUTH.authed && !canDownloadUI());
  document.querySelectorAll("[data-dl]").forEach(b => b.classList.toggle("deloff", dlBlocked));
  const upBlocked = !!(AUTH && !AUTH.host && AUTH.authed && !canUploadUI());
  const dz = $("#drop"); if(dz) dz.classList.toggle("deloff", upBlocked);
  const msf = $("#msendfiles"); if(msf) msf.classList.toggle("deloff", upBlocked);
  // v2.8.39 (8): the Files-tab Add New greys with Upload too.
  const fab = $("#fileaddbtn"); if(fab) fab.classList.toggle("deloff", upBlocked);
  const addBlocked = !!(AUTH && !AUTH.host && AUTH.authed && !canAddNotesUI());
  // v2.8.0: edit/rename are Add / Edit Notes actions too, so
  // their controls grey with Add, not just the Add button.
  document.querySelectorAll("[data-edit]").forEach(b => b.classList.toggle("deloff", addBlocked));
  const man = $("#maddnote"); if(man) man.classList.toggle("deloff", addBlocked);
  const ss = $("#sendsnippet"); if(ss) ss.classList.toggle("deloff", addBlocked);
  const mss = $("#msendsnippet"); if(mss) mss.classList.toggle("deloff", addBlocked);
  // v2.8.1: the Send text areas themselves grey with Add / Edit
  // Notes too, so the whole Send Text card reads unavailable --
  // not just its button (the button tap still toasts the exact
  // no-permission message, as for every other greyed control).
  const sn = $("#snippet"); if(sn) sn.classList.toggle("deloff", addBlocked);
  const msn = $("#msendtext"); if(msn) msn.classList.toggle("deloff", addBlocked);
  const stBlocked = !!(AUTH && !AUTH.host && AUTH.authed && !canStarUI());
  document.querySelectorAll("[data-star]").forEach(b => b.classList.toggle("deloff", stBlocked));
}
// v2.7.91 real-time delete-state sync: the 5s poll refreshes ONLY
// the delete permissions from /api/authstate (via _origFetch, so
// no stale X-Drop-Link header can flip the result) and re-paints
// the grey delete controls. It deliberately does NOT run the
// checkAuth() routing logic: no page-1/page-2 bouncing and no
// lock-screen flips from this poll. Bouncing stays in
// checkAuth()/checkStillConnected-style paths only. A failed
// refresh is silent -- the last known state stays painted.
let _delStateBusy = false;
async function refreshDeleteState(){
  if(_delStateBusy) return;
  _delStateBusy = true;
  try {
    const hh = {};
    if(DROP_HOST_TOKEN) hh["X-Drop-Host"] = DROP_HOST_TOKEN;
    const r = await _origFetch("/api/authstate", {headers: hh});
    const st = await r.json();
    if(st && typeof st === "object"){
      if(typeof st.can_delete_files === "boolean") AUTH.can_delete_files = st.can_delete_files;
      if(typeof st.can_delete_notes === "boolean") AUTH.can_delete_notes = st.can_delete_notes;
      // v2.7.99: the poll now refreshes ALL six permissions,
      // not just the two deletes.
      if(typeof st.can_download_files === "boolean") AUTH.can_download_files = st.can_download_files;
      if(typeof st.can_upload_files === "boolean") AUTH.can_upload_files = st.can_upload_files;
      if(typeof st.can_add_notes === "boolean") AUTH.can_add_notes = st.can_add_notes;
      if(typeof st.can_star_notes === "boolean") AUTH.can_star_notes = st.can_star_notes;
      if(st.permissions && typeof st.permissions === "object") AUTH.permissions = st.permissions;
      if(typeof st.guest_delete_allowed === "boolean") AUTH.guest_delete_allowed = st.guest_delete_allowed;
      if(typeof st.guest_notes_delete_allowed === "boolean") AUTH.guest_notes_delete_allowed = st.guest_notes_delete_allowed;
      paintDeleteState();
    }
  } catch(e){}
  _delStateBusy = false;
}
// v2.8.33 (Essef Nov 6): re-read the server's CURRENT address
// (header-free, like checkAuth -- no X-Drop-Address, WITH the
// desktop bridge token when there is one) and adopt it into
// AUTH, with NO routing or other side effects. Connect entries
// must call this before posting /api/connect: a phone page
// loaded before the PC changed its address still declares the
// OLD address in X-Drop-Address, and the server refuses a
// declared address that is not current -- so the connect
// answered authed:false even after a correct login, and the
// guest stayed stuck on "Couldn't connect to this address".
// Refreshing first makes the declared header truthful again.
// A failed refresh is silent -- the connect proceeds with the
// last known address, exactly as before.
async function refreshAuthName(){
  try {
    const hh = {};
    if(DROP_HOST_TOKEN) hh["X-Drop-Host"] = DROP_HOST_TOKEN;
    const r = await _origFetch("/api/authstate", {headers: hh});
    const st = await r.json();
    if(st && typeof st === "object") AUTH = Object.assign(AUTH || {}, st);
  } catch(e){}
}
async function checkAuth(){
  try {
    // Authstate must NOT carry X-Drop-Link (a stale declared link
    // would make it report unauthed), but it SHOULD carry the
    // desktop bridge token when the page has one, so the desktop
    // window is recognised as host even if it was loaded via a
    // LAN IP / .local name instead of loopback.
    const hh = {};
    if(DROP_HOST_TOKEN) hh["X-Drop-Host"] = DROP_HOST_TOKEN;
    const r = await _origFetch("/api/authstate", {headers: hh}); const st = await r.json();
    AUTH = Object.assign(AUTH, st);
    // v2.8.0: tokenless open guest -- mint a session once, so
    // Devices shows a UA-hint name (not a bare IP) for open
    // guests, like it already does for password guests whose
    // login mints one. Once only per page load; a revoked
    // token never reaches here (authed is false for it).
    // v2.8.17: a user-initiated disconnect must NEVER re-mint.
    // doLogout sets window._userDisconnected, and this block
    // respects it: without the flag, a disconnect on an open
    // address re-minted a session here at once (the guard
    // passed because doLogout had just cleared
    // guestConnectedAddress), so Disconnect looked like it
    // did nothing. The flag clears on the next successful
    // MANUAL connect (doGuestLogin / doLogin / guest Save /
    // mobile Connect), never on its own.
    if(st.sessionless_open && st.address_name && !window._sessionlessConnectDone
       && !window._userDisconnected
       && (!guestConnectedAddress() || guestConnectedAddress() === st.address_name)){
      window._sessionlessConnectDone = true;
      // v2.8.18 (1)(5): remember the use, like the manual
      // connect paths do -- otherwise a guest who only ever
      // auto-connected has no local history: the login field
      // never prefills, the address dropdown stays empty, and
      // the green open-address note never shows after a
      // disconnect until the address is typed again.
      try { const _sj = await postJ("/api/connect", {link: st.address_name}); if(_sj && _sj.ok) bumpAddressUse(st.address_name); } catch(e){}
    }
    if(!AUTH.address_name && AUTH.link_name) AUTH.address_name = AUTH.link_name;
    if(!AUTH.address_key && AUTH.link_key) AUTH.address_key = AUTH.link_key;
    // v2.7.90 pager: host -> main page, never a lock flash.
    // Guest -> main ONLY when authed AND on the link it last
    // connected to; anything else (unauth, or the PC changed
    // its link) goes to page 1, the login page, and must enter
    // the link (+ password) again -- never auto-followed.
    // The one password-page case: the guest's own connected
    // link suddenly gained a password (server cleared its
    // sessions), so the login page says so explicitly.
    // v2.8.17 (d): a user-initiated disconnect lands on the login
    // page and STAYS there. The sessionless-mint block above is
    // only half of it: on an open address the server's
    // tokenless-open fallback still reports authed=true with no
    // session at all, so the authed branch below would send the
    // guest straight back to the main page (and re-record the
    // connection) even though no session was re-minted. This
    // branch short-circuits that: while _userDisconnected is
    // set, an open address shows the login page. The flag clears
    // on the next successful MANUAL connect, never on its own.
    if(window._userDisconnected && !st.host){ showGuestLogin(); }
    else if(st.host){ hideLock(); showGuestMain(); }
    else if(st.authed && st.address_name && (!guestConnectedAddress() || guestConnectedAddress() === st.address_name)){
      if(st.address_name) setGuestConnectedAddress(st.address_name);
      hideLock(); showGuestMain();
    } else if(!st.authed && st.locked && guestConnectedAddress() && guestConnectedAddress() === st.address_name){
      showGuestLogin("This address now needs a password — enter it to reconnect.");
    } else if(guestConnectedAddress() && st.address_name && guestConnectedAddress() !== st.address_name){
      showGuestLogin("The PC changed its address — enter the new address to connect again.");
    } else if(!st.authed){
      showGuestLogin();
    } else if(!st.address_name){
      showGuestLogin("No address set yet — enter the address shown on the PC.");
    } else {
      showGuestMain();
    }
    const ls = $("#locksub");
    if(ls) ls.textContent = "Enter the password for your collection.";
    paintLockBtns();
    paintSwitches();
    paintDeleteState();
    paintSeparateFolders();
    paintAddressAll();
    // v2.7.89 HOST-ONLY path: guests never get st.folder from the
    // server, so the save-destination span stays hidden for them
    // (the server also strips that span from guest-served pages
    // entirely). v2.8.39 (7): only #landline-dir is host-only --
    // the "or click to browse" line itself shows for everyone,
    // same as D.
    const ld = $("#landline-dir"); if(ld) ld.style.display = st.host ? "" : "none";
    if(st.folder){ const dl = $("#dirnamelabel"); if(dl) dl.textContent = st.folder; }
    else { const dl = $("#dirnamelabel"); if(dl && !st.host) dl.textContent = ""; }
    // v2.8.33 (1): refresh the Devices pill NOW, not at the next
    // 5s tick. A guest that just connected watched the pill say
    // "No devices connected" for up to 5 seconds even though the
    // server had already registered the session (devices:1 at
    // once) -- the connect paths never refreshed the pill, so
    // the first seconds after Connect looked like a failed
    // connect. loadStatus is a no-op while unauthed (401, caught).
    // ONLY when authed: /api/status 401s for an unauthed guest,
    // and the fetch wrapper answers a 401 with showLock() +
    // checkAuth() -- calling loadStatus() here while unauthed
    // spun that into a ~30/sec loop (caught by probe48e: 90
    // /api/status 401s in 3s on the login page, and the Saved
    // view could never open). When authed the pill refreshes
    // at once, which is the whole point of this call.
    if(st.authed && typeof loadStatus === "function") loadStatus();
    return st;
  } catch(e){ return null; }
}
$("#lockgo").onclick = doLogin;
$("#lockpw").addEventListener("keydown", e => { if(e.key === "Enter") doLogin(); });
$("#lockchange").onclick = () => { hideLock(); openLinkWin(); };
async function doLogin(){
  const err = $("#lockerr"); err.textContent = "";
  const j = await postJ("/api/login", {password: $("#lockpw").value});
  if(j.ok){
    window._userDisconnected = false;
    justUnlockedAt = Date.now();
    $("#lockpw").value = ""; hideLock(); paintAddressAll();
    lastNotesSig = null; lastFilesSig = null; loadNotes(); loadFiles(); await checkAuth();
    toast("Connected to " + (AUTH.address_name || j.display_address || ""));
  } else err.textContent = "Incorrect password";
}
// Guest login page (page 1) Connect button. Order matters:
// try the explicit connect FIRST (open links need no login);
// only when the server says the link is locked do we log in
// with the typed password and connect again. A wrong link
// (409) is an error, never a silent switch to another link.
// v2.8.35: connecting popup -- one small box for the three
// connect states. Connecting: loading circle + "Connecting…".
// Success: checkmark + "Connected" (auto-closes after ~1.2s).
// Failure: warning icon + "Unable to Connect — Check Device
// Address / Wi-Fi Name / Password" (stays until closed).
// Replaces the inline connecting/disconnected status text on
// the login/connect screen; the Devices pill is untouched.
let _connTimer = null;
// v2.8.36 (9): ONE popup on connect -- the green icon +
// "Connected to <address>" centred inside the small box
// (no separate "Connected to ..." toast alongside it). The
// failed state ("Unable to Connect — ...") is unchanged.
function showConnPop(state, address){
  const pop = $("#connpop"); if(!pop) return;
  const ic = $("#connic"), tx = $("#conntext"), cl = $("#connclose");
  clearTimeout(_connTimer); _connTimer = null;
  if(state === "connected"){
    ic.innerHTML = '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="8 12.5 11 15.5 16 9"/></svg>';
    if(tx) tx.textContent = address ? ("Connected to " + address) : "Connected";
    if(cl) cl.style.display = "none";
    pop.classList.add("small");
    _connTimer = setTimeout(hideConnPop, 1200);
  } else if(state === "failed"){
    pop.classList.remove("small");
    ic.innerHTML = '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><line x1="12" y1="9" x2="12" y2="13"/><circle cx="12" cy="17" r="1" fill="#f59e0b" stroke="none"/></svg>';
    if(tx) tx.textContent = "Unable to Connect — Check Device Address / Wi-Fi Name / Password";
    if(cl) cl.style.display = "";
  } else {
    pop.classList.remove("small");
    ic.innerHTML = '<div class="connspin"></div>';
    if(tx) tx.textContent = "Connecting…";
    if(cl) cl.style.display = "none";
  }
  pop.classList.add("open");
}
function hideConnPop(){ const pop = $("#connpop"); if(pop) pop.classList.remove("open"); if(_connTimer){ clearTimeout(_connTimer); _connTimer = null; } }
const _connClose = $("#connclose"); if(_connClose) _connClose.onclick = hideConnPop;
const _connPopEl = $("#connpop"); if(_connPopEl) _connPopEl.addEventListener("mousedown", e => { if(e.target.id === "connpop") hideConnPop(); });
async function doGuestLogin(){
  const err = $("#gloginerr"); if(err) err.textContent = "";
  const raw = ($("#gloginlink").value || "").trim();
  // v2.8.33: refresh the server's current address FIRST, so the
  // X-Drop-Address header on the connect below is truthful even
  // when this page was loaded before the PC changed its address
  // (a stale declared address made Connect fail after a correct
  // login -- see refreshAuthName). A pasted / typed IP-or-URL
  // naming a DIFFERENT machine navigates to that machine
  // instead of being validated as a name.
  await refreshAuthName();
  const foreign = foreignPastedUrl(raw);
  if(foreign){ location.href = foreign; return; }
  const pasted = parsePastedAddress(raw);
  const name = pasted || raw;
  if(!name){ if(err) err.textContent = "Enter an address first"; return; }
  const nameErr = validateAddressName(name);
  if(nameErr){ if(err) err.textContent = nameErr; shakeAddressField(nameErr); return; }
  const pw = $("#gloginpw").value;
  showConnPop("connecting");
  let cj = await postJ("/api/connect", {link: name});
  if(cj.ok && cj.authed === false && cj.locked){
    if(!pw){ hideConnPop(); if(err) err.textContent = "Enter the password for this address"; return; }
    const lj = await postJ("/api/login", {password: pw});
    if(!lj.ok){ showConnPop("failed"); if(err) err.textContent = "Incorrect password"; return; }
    justUnlockedAt = Date.now();
    // v2.8.33: re-read the current address after login, so the
    // second connect never declares a stale one either.
    await refreshAuthName();
    cj = await postJ("/api/connect", {link: name});
  }
  if(cj.ok && cj.authed !== false){
    window._userDisconnected = false;
    setGuestConnectedAddress(cj.display_address || name);
    bumpAddressUse(cj.display_address || name);
    // v2.8.35: Save password decides whether this device
    // remembers the password for this address.
    const _savePw = !$("#gloginsavechk") || $("#gloginsavechk").checked;
    if(_savePw) saveGuestAddressPw(cj.display_address || name, pw);
    else removeGuestSavedAddressPw(cj.display_address || name);
    showConnPop("connected", cj.display_address || name);
    await checkAuth(); paintAddressAll();
    lastNotesSig = null; lastFilesSig = null; loadNotes(); loadFiles();
  } else if(cj.code === "invalid_link_name"){ hideConnPop(); if(err) err.textContent = cj.error || "That address name is not allowed"; }
  else { showConnPop("failed"); if(err) err.textContent = cj.error || "Couldn't connect to this address"; }
}
const _glb = $("#gloginbtn"); if(_glb) _glb.onclick = doGuestLogin;
const _gll = $("#gloginlink"); if(_gll) _gll.addEventListener("keydown", e => { if(e.key === "Enter") doGuestLogin(); });
if(_gll) _gll.addEventListener("input", debounceOpenAddress);
const _glp = $("#gloginpw"); if(_glp) _glp.addEventListener("keydown", e => { if(e.key === "Enter") doGuestLogin(); });
async function doLogout(){
  window._userDisconnected = true;
  await postJ("/api/logout", {});
  setGuestConnectedAddress("");
  lastNotesSig = null;
  /* v2.8.39 (1): leaving a session must not leave the typed
     password sitting in the login form -- an unchecked session
     saved nothing, so the field must be empty on return
     (showGuestLogin refills it from the saved copy when one
     exists). */
  const _lp = $("#gloginpw"); if(_lp) _lp.value = "";
  _glPwSt.saved = ""; _glPwSt.shown = false;
  checkAuth();
}
// v2.7.92: the lock icon (top bar, sidebar) LOCKS and UNLOCKS the
// address itself, animated + with a sound. Guests never get this
// path: a guest lock tap still opens its connect screen. Host:
//  * locked -> unlock at once (password stays stored);
//  * unlocked + a password stored -> re-lock at once with that
//    stored password (no popup, no re-entry);
//  * unlocked + no password stored -> FIRST lock only: the small
//    password popup (password + nothing else).
// Unlocking never removes the password; only an explicit removal
// (the Remove-password button, or saving an emptied password
// field) clears it.
async function onLockIcon(){
  openSidebar(false);
  const st = AUTH || {};
  if(!st.host){ openLinkWin(); return; }
  await checkAuth();
  if(AUTH.locked){
    const j = await postHostJ("/api/addresslock", {locked: false});
    if(j.ok){ playLockSound(false); animateLockIcon(); await checkAuth(); paintAddressAll(); toast(j.message || ("Address unlocked — " + (AUTH.address_name || ""))); }
    else toast(j.error || "Could not unlock");
    return;
  }
  if(AUTH.has_password){
    const j = await postHostJ("/api/addresslock", {locked: true});
    if(j.ok){ playLockSound(true); animateLockIcon(); await checkAuth(); paintAddressAll(); toast(j.message || ("Address locked — " + (AUTH.address_name || ""))); }
    else toast(j.error || "Could not lock");
    return;
  }
  openLockPopup();
}
function openLockPopup(){
  const pop = $("#lockpwpop"); if(!pop) return;
  const addr = $("#lockpwaddr"); if(addr){ addr.textContent = AUTH.address_name || ""; addr.style.color = addressTextColorForKey((AUTH && AUTH.address_key) || addressKeyOf(AUTH.address_name || "")); }
  const inp = $("#lockpwin"); if(inp){ inp.value = ""; inp.type = "password"; }
  // v2.8.37 (1): the Save password box starts unchecked +
  // DISABLED (empty field); typing enables it live (the
  // input listener below). Reset on every open so a previous
  // choice never leaks into a new password.
  const _lpsc0 = $("#lockpwsavechk"); if(_lpsc0){ _lpsc0.checked = false; _lpsc0.disabled = true; }
  const eye = $("#lockpweye"); if(eye) eye.innerHTML = eyeSVG(false);
  const err = $("#lockpwerr"); if(err) err.textContent = "";
  // v2.8.30 (3): a reopen during the .18s pop-out cancels it
  // (clear the pending hide so it cannot yank .open away).
  clearTimeout(_lockpwCloseT); pop.classList.remove("closing");
  pop.classList.add("open");
  setTimeout(() => { if(inp) inp.focus(); }, 60);
}
let _lockpwCloseT = 0;
function closeLockPopup(){ const pop = $("#lockpwpop"); if(!pop || !pop.classList.contains("open")) return;
  // v2.8.30 (3): ANIMATED pop-out -- hold the box visible
  // under .closing for the .18s lockpwpopout animation, then
  // remove .open (display:none). A reopen clears the timer.
  pop.classList.add("closing");
  clearTimeout(_lockpwCloseT);
  _lockpwCloseT = setTimeout(() => { pop.classList.remove("open"); pop.classList.remove("closing"); }, 180); }
const _lpx = $("#lockpwcloseX"); if(_lpx) _lpx.onclick = closeLockPopup;
const _lpp = $("#lockpwpop"); if(_lpp) _lpp.addEventListener("click", (e) => { if(e.target === _lpp) closeLockPopup(); });
const _lpe = $("#lockpweye"); if(_lpe) _lpe.onclick = () => { const inp = $("#lockpwin"); if(!inp) return; if(inp.type === "text"){ inp.type = "password"; paintEyeBtn(_lpe, false); } else { inp.type = "text"; inp.focus(); paintEyeBtn(_lpe, true); } };
const _lpin = $("#lockpwin"); if(_lpin) _lpin.addEventListener("keydown", e => { if(e.key === "Enter") $("#lockpwsave").click(); });
// v2.8.37 (1): live Save-password rule -- disabled while the
// field is empty, enabled as soon as any character is typed
// (and disabled + unchecked again if the field is cleared).
if(_lpin) _lpin.addEventListener("input", () => { const cb = $("#lockpwsavechk"); if(!cb) return; cb.disabled = !_lpin.value; if(!_lpin.value) cb.checked = false; });
const _lps = $("#lockpwsave"); if(_lps) _lps.onclick = async () => {
  const inp = $("#lockpwin"); const err = $("#lockpwerr");
  const pw = inp ? inp.value : "";
  if(!pw){ if(err) err.textContent = "Type a password first"; return; }
  const _lpscb = $("#lockpwsavechk");
  // v2.8.37 (1): Save sends save_password -- checked + password
  // -> locked + saved; unchecked + password -> still locked,
  // hash only. The server (/api/setlinkpassword) honours it.
  const j = await postHostJ("/api/setlinkpassword", {password: pw, save_password: !!(_lpscb && _lpscb.checked)});
  if(j.ok){ closeLockPopup(); slideInBoard(); playLockSound(true); animateLockIcon(); await checkAuth(); paintAddressAll(); toast(j.message || ("Connected to " + (j.display_address || AUTH.address_name || ""))); }
  else if(err) err.textContent = j.error || "Could not save the password";
};
function fmt(n){ if(n<1024) return n+" B"; if(n<1048576) return (n/1024).toFixed(1)+" KB";
  if(n<1073741824) return (n/1048576).toFixed(1)+" MB"; return (n/1073741824).toFixed(2)+" GB"; }
// v2.8.19: file-type icons are inline SVG (classic
// feather-style strokes, one colour per type) -- never emoji.
// Emoji render as solid BLACK glyphs in environments without a
// colour-emoji font (notably the desktop pywebview window), so
// in LIGHT mode the Shared Files thumbnails were unreadable
// black blobs on a light tile. SVG strokes render identically
// everywhere, in both themes; the colours below read on the
// dark tile (#090c15) and the light tile (#eef2f7) alike.
function _ficSvg(color, inner){
  return '<svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="' + color + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + inner + '</svg>';
}
const _FIC_FILE = '<path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/>';
const _FIC_FILETEXT = _FIC_FILE + '<line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/>';
const _FIC_IMAGE = '<rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>';
const _FIC_FILM = '<rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="2" y1="7" x2="7" y2="7"/><line x1="2" y1="17" x2="7" y2="17"/><line x1="17" y1="17" x2="22" y2="17"/><line x1="17" y1="7" x2="22" y2="7"/>';
const _FIC_MUSIC = '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>';
const _FIC_BOX = '<path d="M16.5 9.4L7.55 4.24"/><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/>';
const _FIC_GLOBE = '<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>';
const _FIC_CODE = '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>';
function iconFor(n){ const e=n.split(".").pop().toLowerCase();
  if(["png","jpg","jpeg","gif","webp","svg","heic","bmp"].includes(e)) return _ficSvg("#0284c7", _FIC_IMAGE);
  if(["mp4","mov","mkv","webm","avi","m4v"].includes(e)) return _ficSvg("#8b5cf6", _FIC_FILM);
  if(["mp3","wav","flac","m4a","ogg","aac"].includes(e)) return _ficSvg("#db2777", _FIC_MUSIC);
  if(["zip","rar","7z","tar","gz"].includes(e)) return _ficSvg("#d97706", _FIC_BOX);
  if(["pdf"].includes(e)) return _ficSvg("#ef4444", _FIC_FILETEXT);
  if(["doc","docx","odt","rtf"].includes(e)) return _ficSvg("#3b82f6", _FIC_FILETEXT);
  if(["xls","xlsx","ods","csv"].includes(e)) return _ficSvg("#16a34a", _FIC_FILETEXT);
  if(["ppt","pptx","odp"].includes(e)) return _ficSvg("#ea580c", _FIC_FILETEXT);
  if(["html","htm","xml"].includes(e)) return _ficSvg("#0891b2", _FIC_GLOBE);
  if(["py","js","ts","css","java","c","cpp","json"].includes(e)) return _ficSvg("#7c3aed", _FIC_CODE);
  if(["txt","md","log"].includes(e)) return _ficSvg("#64748b", _FIC_FILETEXT);
  return _ficSvg("#64748b", _FIC_FILE); }
// v2.8.19: the image/video/audio badges are the same classic
// SVG icons at badge size (currentColor, so they follow the
// badge text colour in both themes) -- never emoji, for the
// same solid-black reason as iconFor above.
function _badgeSvg(inner){
  return '<span class="tbadge"><svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + inner + '</svg></span>';
}
function badgeFor(n){
  if(/\\.(png|jpe?g|gif|webp|bmp|heic|svg)$/i.test(n)) return _badgeSvg(_FIC_IMAGE);
  if(/\\.(mp4|mov|m4v|webm|mkv|avi)$/i.test(n)) return _badgeSvg(_FIC_FILM);
  if(/\\.(mp3|wav|flac|m4a|ogg|aac)$/i.test(n)) return _badgeSvg(_FIC_MUSIC);
  const p = n.split(".");
  const e = (p.length > 1 ? p.pop() : "file").toUpperCase().slice(0, 4);
  return '<span class="tbadge tlabel">' + esc(e) + '</span>';
}
// v2.7.90: a thumbnail that fails (401, 404 for an unreadable
// format, corrupt bytes) must never render as a broken-image
// icon: swap it for the plain file icon instead.
// v2.8.19: a failed thumbnail falls back to the same classic
// SVG file icon (never an emoji -- see iconFor).
function thumbFallback(el){ const s = document.createElement("span"); s.className = "fic"; const src = el.getAttribute("src") || ""; const nm = decodeURIComponent(src.split("/thumb/").pop() || ""); s.innerHTML = iconFor(nm || "x.png"); el.replaceWith(s); }
function thumbFor(n){
  if(/\\.(png|jpe?g|gif|webp|bmp|heic|svg)$/i.test(n))
    return `<img class="thumb" loading="lazy" src="/thumb/${encodeURIComponent(n)}" alt="" onerror="thumbFallback(this)">`;
  if(/\\.(mp4|mov|m4v|webm|mkv|avi)$/i.test(n))
    return `<video class="thumb" preload="metadata" muted playsinline disablepictureinpicture src="/dl/${encodeURIComponent(n)}#t=0.5"></video>`;
  return `<span class="fic">${iconFor(n)}</span>`;
}
async function openFile(name){
  try {
    if(window.pywebview && window.pywebview.api && window.pywebview.api.open_file){
      const ok = await window.pywebview.api.open_file(name);
      if(!ok) toast("Couldn't open that file");
      return;
    }
  } catch(e){}
  location.href = "/dl/" + encodeURIComponent(name);
}
function toast(msg){ const t=$("#toast"); t.textContent=msg; t.classList.add("show");
  clearTimeout(t._h); t._h=setTimeout(()=>t.classList.remove("show"),2200); }

// ---------- phone download cache: Download once, Open after ----------
function hasBridge(){ try{ return !!(window.pywebview && window.pywebview.api && window.pywebview.api.open_file); }catch(e){ return false; } }
const MEMBLOBS = {};
const DLSTATE = {};
try { Object.assign(DLSTATE, JSON.parse(localStorage.getItem("dropit_dl") || "{}")); } catch(e){}
function isDownloaded(f){ const v = DLSTATE[f.name]; return v === f.size || (!!v && v.size === f.size); }
function markDownloaded(f){ DLSTATE[f.name] = {size: f.size, ts: Math.floor(Date.now()/1000)};
  try{ localStorage.setItem("dropit_dl", JSON.stringify(DLSTATE)); }catch(e){} 
  // v2.8.37 (2): the shared downloaded-state store -- every
  // successful save repaints BOTH the file row and the preview
  // button together, in real time (see repaintDownloadButtons).
  repaintDownloadButtons(f.name, f.size); }
function dlLabel(f){ return (hasBridge() || isDownloaded(f)) ? "Open" : "Download"; }
// v2.8.37 (2): ONE repaint for every Download -> Open flip.
// The file-row button is an icon button (title + SVG), the
// preview button is text -- both read the same DLSTATE via
// dlLabel/isDownloaded, so a download started in either place
// flips the other at the same time, with no reload in between.
// Row buttons are matched by data-name (never by a selector
// built from the file name). The desktop bridge path is
// untouched: its buttons always read Open and the preview's
// Open still opens the file in Windows' selected apps.
function repaintDownloadButtons(name, size){
  const f = {name: name, size: size};
  const label = dlLabel(f);
  document.querySelectorAll("#files [data-dl][data-name]").forEach(b => {
    if(b.dataset.name !== name) return;
    b.title = label;
    b.innerHTML = label === "Open" ? SVG.open : SVG.dl;
  });
  if(hasBridge()) return;
  const pop = $("#previewpop");
  if(pop && pop.classList.contains("open")){
    const t = $("#previewtitle");
    if(t && t.textContent === name){
      const dl = $("#previewdl");
      if(dl){
        dl.textContent = label;
        // v2.8.38 (1): "Open" in the preview OPENS the file --
        // the same saved-blob viewer the file row's Open uses
        // (openBlob). It must NOT just close the preview (the
        // 2.8.37 behaviour Essef reported: Open closed the
        // window and the file never opened, web + MB). Close
        // the preview first, then open the file. Desktop
        // (bridge) returns above and is untouched.
        if(label === "Open") dl.onclick = () => { const cx = $("#previewclose2"); if(cx) cx.click(); openBlob({name: name, size: size}); };
      }
    }
  }
}

const DBCACHE = {
  db:null,
  open(){ return new Promise((res, rej) => {
    if(this.db) return res(this.db);
    try{
      const rq = indexedDB.open("dropit-cache", 1);
      rq.onupgradeneeded = () => rq.result.createObjectStore("files");
      rq.onsuccess = () => { this.db = rq.result; res(this.db); };
      rq.onerror = () => rej(rq.error);
    }catch(e){ rej(e); }
  });},
  async get(name){ try{ const db = await this.open();
      return await new Promise((res, rej) => { const t = db.transaction("files").objectStore("files").get(name);
        t.onsuccess = () => res(t.result || null); t.onerror = () => rej(t.error); });
    }catch(e){ return null; } },
  async put(name, blob){ try{ const db = await this.open();
      await new Promise((res, rej) => { const t = db.transaction("files","readwrite").objectStore("files").put(blob, name);
        t.onsuccess = () => res(); t.onerror = () => rej(t.error); });
    }catch(e){} },
  async del(name){ try{ const db = await this.open();
      await new Promise((res, rej) => { const t = db.transaction("files","readwrite").objectStore("files").delete(name);
        t.onsuccess = () => res(); t.onerror = () => rej(t.error); });
    }catch(e){} },
  async clear(){ try{ const db = await this.open();
      await new Promise((res, rej) => { const t = db.transaction("files","readwrite").objectStore("files").clear();
        t.onsuccess = () => res(); t.onerror = () => rej(t.error); });
    }catch(e){} }
};

async function ensureSpace(){
  try{
    const est = await navigator.storage.estimate();
    if(est.usage > 400*1024*1024){
      await DBCACHE.clear();
      for(const k in MEMBLOBS) delete MEMBLOBS[k];
      for(const k in DLSTATE) delete DLSTATE[k];
      try{ localStorage.setItem("dropit_dl", "{}"); }catch(e){}
    }
  }catch(e){}
}

let VURL = null;

// ---------- overlay back-button handling ----------
// The viewer and the download confirm dialog each push a history entry, so the
// phone's back button / swipe-back closes the top overlay instead of the browser.
// A user back-press already consumes that entry, so only a self-close (X / button)
// issues history.back() to remove it -- never both.
const ovStack = [];
let ovSkipPop = false;
function ovOpened(onClose){
  ovSkipPop = false;   // a stale skip must never swallow a future real back-press
  const top = ovStack[ovStack.length - 1];
  if(top && top._isViewer && onClose._isViewer){
    ovStack.pop();     // viewer replacing viewer keeps the single live entry
  } else if(window.history){
    try{ history.pushState({dov:1}, ""); }catch(e){}
  }
  ovStack.push(onClose);
}
function ovClosed(onClose, selfClose){
  const i = ovStack.lastIndexOf(onClose);
  if(i >= 0) ovStack.splice(i, 1);
  if(selfClose){
    ovSkipPop = true;
    try{ history.back(); }catch(e){ ovSkipPop = false; }
  }
}
window.addEventListener("popstate", () => {
  if(ovSkipPop){ ovSkipPop = false; return; }
  const top = ovStack.pop();
  if(top){ try{ top(false); }catch(e){} }
});

function _viewerHide(){
  $("#viewer").classList.remove("open");
  $("#vcontent").innerHTML = "";
  if(VURL){ URL.revokeObjectURL(VURL); VURL = null; }
}
function showViewer(title, html, url){
  _viewerHide();
  $("#vtitle").textContent = title;
  $("#vcontent").innerHTML = html;
  $("#viewer").classList.add("open");
  VURL = url || null;
  const closer = (self) => { _viewerHide(); ovClosed(closer, self !== false); };
  closer._isViewer = true;
  ovOpened(closer);
}
function closeViewer(byUser){
  const wasOpen = $("#viewer").classList.contains("open");
  _viewerHide();
  if(!wasOpen) return;
  let own = null;
  for(let i = ovStack.length - 1; i >= 0; i--){
    if(ovStack[i]._isViewer){ own = ovStack[i]; break; }
  }
  ovClosed(own, byUser !== false);
}
$("#vclose").onclick = () => closeViewer();
$("#viewer").onclick = e => { if(e.target.id === "viewer") closeViewer(); };

// ---------- download confirm dialog ----------
function askSaveDiscard(title, msg){
  return new Promise(res => {
    const d = $("#cfdlg");
    $("#cftitle").textContent = title;
    $("#cfmsg").textContent = msg;
    let settled = false;
    const dcloser = (self) => done(false, self);
    const done = (v, self) => {
      if(settled) return; settled = true;
      d.classList.remove("open");
      ovClosed(dcloser, self !== false);
      res(v);
    };
    $("#cfyes").onclick = () => done(true);
    $("#cfno").onclick = () => done(false);
    d.classList.add("open");
    ovOpened(dcloser);
  });
}

async function downloadFile(f, btn, quiet){
  if(btn){ if(btn.classList.contains("busy")) return null; btn.classList.add("busy"); }
  const resetBtn = () => { if(btn) btn.classList.remove("busy"); };
  try{
    toast("Downloading " + f.name);
    const r = await fetch("/dl/" + encodeURIComponent(f.name));
    if(r.status === 403){ toast("No permission to download files from this device"); resetBtn(); return null; }
    if(!r.ok) throw 0;
    const blob = await r.blob();
    const keep = await askSaveDiscard("Download complete",
      "Save " + f.name + " (" + fmt(f.size) + ") on this device?");
    if(!keep){ toast("File not saved on this device."); resetBtn(); return null; }
    await ensureSpace();
    MEMBLOBS[f.name] = blob;
    // v2.8.33 (3): AWAIT the cache write. Fire-and-forget left a
    // race: the ledger (localStorage, synchronous) could list the
    // file while its blob had not committed to IndexedDB yet, so
    // a later Saved preview found no blob to open even though the
    // file was listed as saved on this device.
    await DBCACHE.put(f.name, blob);
    markDownloaded(f);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = f.name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    lastFilesSig = null;
    await loadFiles();
    // v2.8.33 (3): return the blob, so a caller that re-downloads
    // in order to PREVIEW (openBlob's missing-blob fallback) can
    // open the viewer with it instead of only re-saving the file
    // and leaving the user staring at "tap Open to view it".
    // quiet: skip the "tap Open" toast when the viewer is about
    // to open anyway (the openBlob re-download path).
    if(!quiet) toast("Saved in Drop — tap Open to view it");
    resetBtn();
    return blob;
  }catch(e){ toast("Download failed"); resetBtn(); }
  resetBtn();
  return null;
}

async function openBlob(f){
  let blob = MEMBLOBS[f.name] || await DBCACHE.get(f.name);
  if(!blob){
    if(!(AUTH && AUTH.authed)){ toast("That file is no longer stored on this device"); return; }
    // v2.8.41 (5): a preview re-download is QUIET -- no "Save
    // file?" confirm dialog (downloadFile asks it) and no
    // anchor download. Fetch the bytes, cache them, preview.
    // A tap that ends at a dialog (or at "Download failed"
    // when the file is gone from the PC) is a preview that
    // never opens -- the 2.8.40 Saved complaint.
    try{
      const rr = await fetch("/dl/" + encodeURIComponent(f.name));
      if(rr.status === 403){ toast("No permission to download files from this device"); return; }
      if(!rr.ok) throw 0;
      blob = await rr.blob();
      MEMBLOBS[f.name] = blob;
      await DBCACHE.put(f.name, blob);
      markDownloaded(f);
    }catch(e){
      showViewer(f.name, '<div style="text-align:center;padding:24px"><p style="font-weight:700;margin:0 0 8px">' + esc(f.name) + '</p><p style="opacity:.65;margin:0 0 16px">This file is no longer in the shared folder on your PC.</p></div>');
      return;
    }
  }
  MEMBLOBS[f.name] = blob;
  const n = f.name;
  if(/\\.(txt|md|log|json|csv|xml|html|css|js)$/i.test(n)){
    showViewer(n, `<pre>${esc((await blob.text()).slice(0, 30000))}</pre>`);
    return;
  }
  if(/\\.docx$/i.test(n)){
    showViewer(n, '<div style="text-align:center;opacity:.6;padding:24px">Opening document\\u2026</div>');
    try{
      const r = await fetch("/api/docx/?name=" + encodeURIComponent(n));
      if(r.status === 404) throw "gone";
      if(!r.ok) throw "preview";
      showViewer(n, '<div class="docxview">' + (await r.text()) + "</div>");
    }catch(e){
      // v2.8.16: offline first -- the saved blob itself carries
      // the text (docxTextFromBlob inflates word/document.xml),
      // so a saved .docx previews with no PC connection.
      const _off = await docxTextFromBlob(blob);
      if(_off){ showViewer(n, `<pre>${esc(_off.slice(0, 30000))}</pre>`); return; }
      const why = e === "gone"
        ? "This file is no longer in the shared folder on your PC."
        : "No preview available for this Word file.";
      showViewer(n, '<div style="text-align:center;padding:24px"><p style="opacity:.65;margin:0 0 16px">' + why + '</p>' +
        '<button class="btn primary" id="vdocxopen">Open in Word app</button></div>');
      const vb = document.getElementById("vdocxopen");
      if(vb) vb.onclick = () => { closeViewer(); openWithApp(f); };
    }
    return;
  }
  // v2.8.16: legacy .doc preview -- readable text is pulled
  // straight out of the saved blob (docTextFromBlob), offline.
  if(/\.doc$/i.test(n)){
    const _dt = await docTextFromBlob(blob);
    if(_dt){ showViewer(n, `<pre>${esc(_dt.slice(0, 30000))}</pre>`); }
    else {
      showViewer(n, '<div style="text-align:center;padding:24px"><p style="opacity:.65;margin:0 0 16px">No preview available for this Word file.</p><button class="btn primary" id="vdocopen">Open in Word app</button></div>');
      const _db = document.getElementById("vdocopen");
      if(_db) _db.onclick = () => { closeViewer(); const _u = URL.createObjectURL(blob); openWithApp(n, blob, _u); };
    }
    return;
  }
  const url = URL.createObjectURL(blob);
  if(/\\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(n))
    showViewer(n, `<img src="${url}" alt="">`, url);
  else if(/\\.(mp4|mov|m4v|webm|mkv|avi)$/i.test(n))
    showViewer(n, `<video src="${url}" controls autoplay playsinline>`, url);
  else if(/\\.(mp3|wav|flac|m4a|ogg|aac)$/i.test(n))
    showViewer(n, `<audio src="${url}" controls autoplay style="width:100%">`, url);
  // v2.8.16: PDF previews IN the app (viewer iframe), not in
  // a new tab -- so Preview works the same offline as online.
  else if(/\\.pdf$/i.test(n)){
    showViewer(n, `<iframe src="${url}"></iframe>`, url);
  }
  // v2.8.16: every other type still gets a preview card --
  // name, size and an Open button -- never a blank screen or
  // a silent hand-off.
  else {
    showViewer(n, `<div style="text-align:center;padding:24px"><p style="font-weight:700;margin:0 0 8px">${esc(n)}</p><p style="opacity:.65;margin:0 0 16px">No in-app preview for this file type \u2014 open it with an app on this device.</p><button class="btn primary" id="votheropen">Open</button></div>`, url);
    const _ob = document.getElementById("votheropen");
    if(_ob) _ob.onclick = () => { closeViewer(); openWithApp(n, blob, url); };
  }
}

async function openWithApp(n, blob, url){
  const file = new File([blob], n, { type: blob.type || "application/octet-stream" });
  if(navigator.share){
    try { await navigator.share({ files:[file] }); URL.revokeObjectURL(url); return; }
    catch(e){}
  }
  URL.revokeObjectURL(url);
  toast("Saved in Downloads \\u2014 open it from your Files app");
}

function fileTap(f, btn){
  if(hasBridge()){ openFile(f.name); return; }
  if(isDownloaded(f)) openBlob(f);
  else {
    // v2.7.99: guests without download permission get the exact
    // no-permission message instead of downloading (server
    // 403s /dl/ as backstop).
    if(AUTH && !AUTH.host && AUTH.authed && !canDownloadUI()){ toast("No permission to download files from this device"); return; }
    downloadFile(f, btn);
  }
}

// v2.8.34 (4): open ONE file from inside an archive preview.
// Desktop (bridge): ask the server to extract just that entry
// (mode=path, host-only) and hand the temp path to the bridge
// open_path, so Windows opens it in its selected app -- the
// same bridge the file-row Open uses for whole files. Web:
// fetch the extracted bytes as a download (the server serves
// the single file as an attachment). A RAR entry answers a
// clear error from the server (no stdlib RAR decompressor);
// the toast names it instead of failing silently.
async function openArchiveEntry(archive, entry){
  if(!entry) return;
  try{
    if(hasBridge()){
      const r = await fetch("/api/archive/extract/?file=" + encodeURIComponent(archive) + "&entry=" + encodeURIComponent(entry) + "&mode=path");
      const j = await r.json().catch(() => null);
      if(!r.ok || !j || !j.ok) throw new Error((j && j.error) || "Could not open this file");
      const api = window.pywebview && window.pywebview.api;
      if(api && api.open_path){ const ok = await api.open_path(j.path); if(ok) return; }
      throw new Error("Could not open this file");
    }
    location.href = "/api/archive/extract/?file=" + encodeURIComponent(archive) + "&entry=" + encodeURIComponent(entry);
  }catch(e){ toast(e && e.message ? e.message : "Could not open this file"); }
}

// v2.8.11 in-page file preview (web + desktop pywebview):
// clicking a file row PREVIEWs it here; Download stays a
// separate explicit action (the per-file button + the
// Download button in this window). Nothing is saved by
// previewing: images/video/audio/PDF stream from /dl/ for
// display, text is fetched and shown. A type that cannot be
// previewed shows a clear message, never a silent download.
// v2.8.12: preview stays available WITHOUT download
// permission (view-only, via /dl/?preview=1, served inline
// by the server); only the Download button in this window
// greys, and the plain /dl/ download still 403s.
const _PV_IMG = /\.(png|jpe?g|gif|webp|bmp|svg|heic)$/i;
const _PV_TXT = /\.(txt|md|markdown|json|csv|log|py|js|ts|java|c|cpp|h|css|html|htm|xml|yml|yaml|ini|cfg|sh)$/i;
const _PV_AV = /\.(mp4|mov|m4v|webm|mkv|avi|mp3|wav|ogg|m4a|flac)$/i;
function previewFile(name, size){
  const pop = $("#previewpop"); if(!pop) return;
  const title = $("#previewtitle"), sub = $("#previewsub"), body = $("#previewbody");
  if(title) title.textContent = name;
  if(sub) sub.textContent = size ? fmt(size) : "";
  // v2.8.21 (A): fit view is per-preview -- a picture/video
  // preview adds it below; every other type (and every close)
  // clears it, so PDF/Word/text never inherit the fit box.
  // v2.8.22: the same per-preview clearing covers .fitpic
  // (pictures) and .fittext (text-based previews), and the
  // picture path's explicit box width is reset too.
  // v2.8.23: also clears .fitvid (video) and .fitxlsx (Excel).
  pop.classList.remove("fitmedia"); pop.classList.remove("fitpic"); pop.classList.remove("fittext"); pop.classList.remove("fitvid"); pop.classList.remove("fitxlsx");
  const _pvbox0 = pop.querySelector(".previewbox"); if(_pvbox0) _pvbox0.style.width = ""; if(_pvbox0) _pvbox0.style.height = "";
  const close = () => { pop.classList.remove("open"); pop.classList.remove("fitmedia"); pop.classList.remove("fitpic"); pop.classList.remove("fittext"); pop.classList.remove("fitvid"); pop.classList.remove("fitxlsx"); const _b = pop.querySelector(".previewbox"); if(_b) _b.style.width = ""; if(_b) _b.style.height = ""; if(body) body.innerHTML = ""; };
  const cx = $("#previewclose"), cx2 = $("#previewclose2");
  if(cx) cx.onclick = close;
  if(cx2) cx2.onclick = close;
  pop.onclick = (e) => { if(e.target === pop) close(); };
  const dl = $("#previewdl");
  // v2.8.12: removing Download Files must NOT disable preview
  // (preview is view-only). Only the Download button in this
  // window greys (shared .deloff: visible but dimmed, tapping
  // it toasts the no-permission message); the preview fetch
  // itself uses ?preview=1, which the server serves inline
  // without the download permission.
  // v2.8.14: preview ALWAYS uses ?preview=1, not only when the
  // download permission is off. Without it the server sent
  // Content-Disposition: attachment, so the PDF <embed> below
  // could never render -- that was the "PDF preview works on
  // the APK but not on web" bug (the APK fetches bytes itself,
  // the web page embeds the URL). Images/audio/video take the
  // same inline URL now, for consistency.
  const _noDl = !!(AUTH && !AUTH.host && AUTH.authed && !canDownloadUI());
  // v2.8.34 (6): on the DESKTOP the preview's Download button
  // did nothing (a browser download has no handler inside
  // pywebview), so it is an OPEN button there instead -- it
  // opens the file in Windows' selected apps through the
  // same open bridge as the file-row Open (openFile). The
  // label is set on every preview (the button element is
  // reused), so a desktop preview after a web one -- or the
  // reverse -- never shows the wrong word. Web keeps
  // Download + downloadPreviewFile exactly as before.
  if(dl){ dl.classList.toggle("deloff", _noDl);
    if(hasBridge()){
      dl.textContent = "Open";
      dl.onclick = () => { if(_noDl){ toast("No permission to download files from this device"); return; } close(); openFile(name); };
    } else {
      // v2.8.37 (2): the preview button opens from the SHARED
      // downloaded state -- a file saved earlier (from its row
      // or an earlier preview) already reads Open here.
      // v2.8.38 (1): its Open OPENS the file (openBlob, the
      // same viewer the file row's Open uses) instead of only
      // closing the preview -- close first, then open.
      if(isDownloaded({name: name, size: size})){
        dl.textContent = "Open";
        dl.onclick = () => { close(); openBlob({name: name, size: size}); };
      } else {
      dl.textContent = "Download";
      dl.onclick = async () => {
        if(_noDl){ toast("No permission to download files from this device"); return; }
        // v2.8.36 (7): fetch-based download, so success is
        // KNOWN: only a SAVED download animates the button to
        // Open (discard / reject / failure returns null and
        // the button stays Download). The preview stays open
        // so the animation is visible; Open opens the file.
        const blob = await downloadFile({name: name, size: size}, dl, true);
        if(!blob) return;
        dl.classList.add("pvdlswap");
        setTimeout(() => { dl.textContent = "Open"; }, 170);
        setTimeout(() => { dl.classList.remove("pvdlswap"); }, 420);
        dl.onclick = () => { close(); openBlob({name: name, size: size}); };
      };
      }
    } }
  pop.classList.add("open");
  if(!body) return;
  const url = "/dl/" + encodeURIComponent(name) + "?preview=1";
  // v2.8.22 (3): picture preview -- the window HUGS the picture
  // (no wide empty box), the picture is slightly bigger (up to
  // 1.25x natural, clamped to the viewport), and the window is
  // very transparent (.fitpic). The box width follows the
  // displayed image size.
  // v2.8.23 (2): BIGGER -- up to 2x natural (was 1.25x), up to
  // 1400px wide (was 1080px) and 96vh tall (was 92vh), so a real
  // photo is clearly, comfortably visible at a glance; small
  // pictures gain the most (a 400x300 photo now shows ~760px
  // wide instead of 500px). Still fit-view, still hugging.
  // v2.8.29 (1): NO ZOOM any more (Essef Nov 6) -- the "- 100%
  // + Fit" controls, click-to-zoom and wheel zoom are removed
  // on web and the PC app. The picture is sized ONCE on load
  // to its fit size and never changes; the WINDOW is FIXED
  // (set once here from the fit size), so the buttons stay put
  // and the window never moves. No __pvZoom API any more.
  if(_PV_IMG.test(name)){
    pop.classList.add("fitmedia"); pop.classList.add("fitpic");
    body.innerHTML = '<img src="' + esc(url) + '" alt="">';
    const img = body.querySelector("img");
    const _sizePic = () => {
      const natW = img.naturalWidth || 0, natH = img.naturalHeight || 0;
      if(!natW || !natH) return;
      // v2.8.33 (6)(7): the picture frame is thinner now (pvbody
      // padding 12px -> 4px), so the chrome allowance is 56px
      // wide (was 70) and 180px tall (was 196) -- the exact box
      // padding + borders + pvbody padding + borders, so the
      // sized picture can never overflow the body by a pixel and
      // show a scroller. On the frameless PC app the 44px title
      // bar sits above the preview, so the height allowance
      // loses another 44px there (the CSS caps do the same).
      const _tbOff = document.documentElement.classList.contains("frameless") ? 44 : 0;
      const availW = Math.min(1400, window.innerWidth * 0.96) - 56;
      const availH = window.innerHeight * 0.96 - 180 - _tbOff;
      const s = Math.min(availW / natW, availH / natH, 2);
      const fitW = Math.max(1, Math.round(natW * s)), fitH = Math.max(1, Math.round(natH * s));
      img.style.width = fitW + "px"; img.style.height = fitH + "px";
      // v2.8.24 (1): the WINDOW size is set ONCE here, from the
      // fit size, so the buttons stay put and the window never
      // shrinks or moves.
      const box = pop.querySelector(".previewbox");
      if(box) box.style.width = Math.min(fitW + 56, Math.min(1400, window.innerWidth * 0.96)) + "px";
      // v2.8.24 (1): the window HEIGHT is fixed too -- the
      // box is a flex column, so without this it hugs the
      // picture; the .fitpic .pvbody flex:1 above absorbs
      // the slack, so the row stays pinned at the bottom.
      if(box) box.style.height = Math.round(box.getBoundingClientRect().height) + "px";
    };
    img.addEventListener("load", _sizePic);
    // v2.8.33 (7): a cached image may already be complete before
    // the listener attaches -- its load event never fires again,
    // so the fit sizing never ran and the natural-size picture
    // overflowed the body with both scrollers. Size at once when
    // already complete (the video branch already does this with
    // readyState).
    if(img.complete && img.naturalWidth) _sizePic();
    return;
  }
  if(name.toLowerCase().endsWith(".pdf")){ pop.classList.add("fittext"); body.innerHTML = '<embed src="' + esc(url) + '" type="application/pdf">'; return; }
  // v2.8.14: Word preview (.docx renders as HTML, .doc as
  // extracted text -- both from the same /api/docx/ endpoint).
  // Download stays unchanged: this only fills the preview body.
  if(/\\.docx?$/.test(name)){
    pop.classList.add("fittext");
    body.innerHTML = '<p class="pvmsg">Loading…</p>';
    fetch("/api/docx/?name=" + encodeURIComponent(name)).then(r => { if(!r.ok) throw new Error("preview failed"); return r.text(); }).then(t => { body.innerHTML = '<div class="docxview">' + t + '</div>'; }).catch(() => { body.innerHTML = '<p class="pvmsg">Could not preview this Word file — use Download to open it.</p>'; });
    return;
  }
  // v2.8.22 (8): Excel preview -- .xlsx renders as a table from
  // /api/xlsx/ (same stdlib-only pattern as /api/docx/). Legacy
  // .xls / .ods keep the "cannot preview" message below.
  // v2.8.23 (1): the window HUGS the table -- once it renders,
  // the box width is set from the table's actual width (table
  // + 70px chrome, min 480px, max 1080px) instead of the fixed
  // 1080px .fittext box, so a narrow sheet gets a narrow window.
  if(/\\.xlsx$/i.test(name)){
    pop.classList.add("fittext");
    body.innerHTML = '<p class="pvmsg">Loading…</p>';
    fetch("/api/xlsx/?name=" + encodeURIComponent(name)).then(r => { if(!r.ok) throw new Error("preview failed"); return r.text(); }).then(t => { body.innerHTML = '<div class="xlsxview">' + t + '</div>'; const tbl = body.querySelector(".xlsxview table"); if(tbl){ pop.classList.add("fitxlsx"); const tw = Math.ceil(tbl.getBoundingClientRect().width); const box = pop.querySelector(".previewbox"); if(box) box.style.width = Math.min(Math.max(tw + 70, 480), Math.min(1080, window.innerWidth * 0.96)) + "px"; } }).catch(() => { body.innerHTML = '<p class="pvmsg">Could not preview this Excel file — use Download to open it.</p>'; });
    return;
  }
  if(_PV_AV.test(name)){
    const isVid = /\.(mp4|mov|m4v|webm|mkv|avi)$/i.test(name);
    if(isVid){
      // v2.8.23 (2): video HUGS the video (.fitvid) -- the 2.8.21
      // fit box was a fixed 1080px, so a portrait video sat as a
      // narrow strip in a wide empty window. The box width is set
      // from the displayed video size once its metadata loads
      // (up to 1.5x natural, clamped to the viewport, 96vh tall),
      // same hugging as pictures. Audio keeps the plain player.
      pop.classList.add("fitmedia"); pop.classList.add("fitvid");
      body.innerHTML = '<video controls src="' + esc(url) + '"></video>';
      const vid = body.querySelector("video");
      const _vidSize = () => {
        const vw = vid.videoWidth || 0, vh = vid.videoHeight || 0;
        if(!vw || !vh) return;
        // v2.8.33 (6)(7): same thinner-frame chrome as pictures
        // (56 wide / 180 tall, +44 on the frameless PC app).
        const _tbOff = document.documentElement.classList.contains("frameless") ? 44 : 0;
        const availW = Math.min(1400, window.innerWidth * 0.96) - 56;
        const availH = window.innerHeight * 0.96 - 180 - _tbOff;
        const s = Math.min(availW / vw, availH / vh, 1.5);
        const w = Math.max(1, Math.round(vw * s)), h = Math.max(1, Math.round(vh * s));
        vid.style.width = w + "px"; vid.style.height = h + "px";
        const box = pop.querySelector(".previewbox");
        if(box) box.style.width = Math.min(w + 56, Math.min(1400, window.innerWidth * 0.96)) + "px";
      };
      vid.addEventListener("loadedmetadata", _vidSize);
      if(vid.readyState >= 1) _vidSize();
      return;
    }
    body.innerHTML = '<audio controls src="' + esc(url) + '"></audio>';
    return;
  }
  if(_PV_TXT.test(name)){
    pop.classList.add("fittext");
    if(size && size > 1048576){ body.innerHTML = '<p class="pvmsg">This text file is too large to preview — use Download to open it.</p>'; return; }
    body.innerHTML = '<p class="pvmsg">Loading…</p>';
    fetch(url).then(r => { if(!r.ok) throw new Error("preview failed"); return r.text(); }).then(t => { body.innerHTML = "<pre>" + esc(t) + "</pre>"; }).catch(() => { body.innerHTML = '<p class="pvmsg">Could not preview this file — use Download to open it.</p>'; });
    return;
  }
  // v2.8.33 (8): ARCHIVE LISTING -- .zip / .rar show what is
  // inside (names, sizes, folders) from /api/archive/, web +
  // PC app. A corrupt or unsupported archive shows a clear
  // error, never a crash; listing is view-only like the Word
  // / Excel previews (no download_files check -- the
  // Download button below still enforces it, as for every
  // preview).
  // v2.8.34 (4): file rows OPEN directly -- tapping a file
  // extracts just that one entry and opens it
  // (openArchiveEntry: on the desktop the bridge opens it
  // in Windows' selected apps; on web the single file
  // downloads). Folders are not clickable (no expansion).
  if(/\.(zip|rar)$/i.test(name)){
    pop.classList.add("fittext");
    body.innerHTML = '<p class="pvmsg">Loading…</p>';
    fetch("/api/archive/?file=" + encodeURIComponent(name)).then(r => r.json().then(j => { if(!r.ok || !j || !j.ok) throw new Error((j && j.error) || "Could not list this archive"); return j; })).then(j => {
      const rows = (j.entries || []).map(e => '<div class="archrow"' + (e.is_dir ? "" : ' data-entry="' + esc(e.name) + '" title="Open this file"') + '><span class="archname">' + (e.is_dir ? "📁 " : "📄 ") + esc(e.name) + '</span><span class="archsize">' + (e.is_dir ? "" : fmt(e.size)) + '</span></div>').join("");
      body.innerHTML = '<div class="archview">' + (rows || '<p class="pvmsg">This archive is empty.</p>') + '</div>';
      body.querySelectorAll(".archrow[data-entry]").forEach(r => { r.onclick = () => openArchiveEntry(name, r.getAttribute("data-entry")); });
    }).catch(err => { body.innerHTML = '<p class="pvmsg">' + esc(err && err.message ? err.message : "Could not list this archive") + ' — open it from the button below.</p>'; });
    return;
  }
  body.innerHTML = '<p class="pvmsg">Can not preview this file type in the app — use Download to open it.</p>';
}
function downloadPreviewFile(name){
  // Explicit Download from the preview window: the same
  // browser download as the per-file Download button
  // (a plain /dl/ navigation -- nothing changes here).
  // v2.8.12 backstop: without download permission the plain
  // /dl/ 403s server-side, so refuse here with the message
  // instead of navigating to an error.
  if(AUTH && !AUTH.host && AUTH.authed && !canDownloadUI()){
    toast("No permission to download files from this device"); return;
  }
  const a = document.createElement("a");
  a.href = "/dl/" + encodeURIComponent(name);
  a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
}

/* v2.8.22 (4): right-click menu for TEXT previews -- Copy and
   Select All ONLY, never Paste. A dedicated ANIMATED pop-up
   (#pvctx, pop-in scale/fade on open), separate from the
   file-row #ctxmenu. Desktop/web only (pointer:fine or the
   pywebview bridge); phones keep their native long-press
   menu. It applies to previews with rendered / extracted
   text (text files, Word, Excel tables) -- the PDF <embed>
   keeps its native plugin menu, since it exposes no DOM text
   to copy or select. Copying toasts "copied 📑". */
(function(){
  const menu = document.createElement("div");
  menu.id = "pvctx"; menu.style.display = "none";
  document.body.appendChild(menu);
  const hide = () => { menu.classList.remove("open"); menu.style.display = "none"; };
  document.addEventListener("click", e => { if(!menu.contains(e.target)) hide(); });
  document.addEventListener("keydown", e => { if(e.key === "Escape") hide(); });
  window.addEventListener("blur", hide);
  const isDesktopPv = () => {
    try { if(window.matchMedia && matchMedia("(pointer:fine)").matches) return true; } catch(e){}
    try { if(typeof hasBridge === "function" && hasBridge()) return true; } catch(e){}
    return false;
  };
  const pvTextEl = () => {
    const body = $("#previewbody"); if(!body) return null;
    if(body.querySelector("pre, .docxview, .xlsxview")) return body;
    return null;
  };
  let lastPvMenuAt = 0;
  const showPvMenu = (x, y) => {
    const body = pvTextEl(); if(!body) return;
    hide();
    menu.innerHTML = "";
    const addItem = (label, fn) => {
      const b = document.createElement("button");
      b.className = "ctxitem"; b.type = "button"; b.textContent = label;
      b.onclick = () => { hide(); fn(); };
      menu.appendChild(b);
    };
    addItem("Copy", async () => {
      const sel = (window.getSelection() || "").toString();
      const text = sel || body.innerText || body.textContent || "";
      toast(await copyText(text) ? "copied 📑" : "Couldn't copy text");
    });
    addItem("Select All", () => {
      const r = document.createRange(); r.selectNodeContents(body);
      const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
    });
    const mx = Math.min(x, window.innerWidth - 180);
    const my = Math.min(y, window.innerHeight - 100);
    menu.style.left = Math.max(4, mx) + "px";
    menu.style.top = Math.max(4, my) + "px";
    menu.style.display = "block";
    void menu.offsetWidth;
    menu.classList.add("open");
  };
  const pvTarget = (e) => {
    const pop = $("#previewpop");
    if(!pop || !pop.classList.contains("open")) return false;
    const body = pvTextEl();
    return !!(body && body.contains(e.target));
  };
  document.addEventListener("contextmenu", e => {
    if(!pvTarget(e)) return;
    if(!isDesktopPv()) return;
    if(Date.now() - lastPvMenuAt < 600) return;
    e.preventDefault(); hide();
    lastPvMenuAt = Date.now();
    showPvMenu(e.clientX, e.clientY);
  });
  // Fallback trigger: some embedded webviews swallow contextmenu,
  // but the right mouse button press itself still fires.
  document.addEventListener("mousedown", e => {
    if(e.button !== 2 || !isDesktopPv()) return;
    if(!pvTarget(e)) return;
    if(Date.now() - lastPvMenuAt < 600) return;
    e.preventDefault();
    lastPvMenuAt = Date.now();
    showPvMenu(e.clientX, e.clientY);
  });
  const _pvClose = $("#previewclose"), _pvClose2 = $("#previewclose2");
  if(_pvClose) _pvClose.addEventListener("click", hide);
  if(_pvClose2) _pvClose2.addEventListener("click", hide);
})();

/* v2.8.18: every step of a reveal is recorded in
   window.__revealTrace (bridge present? bridge result?
   fallback result?) so a dead click can be proven to have
   reached (or not reached) each layer -- open the desktop
   window's devtools and read it. No step fails silently any
   more: a failed bridge + failed /api/reveal + failed folder
   fallback toasts the reason instead of returning quietly. */
window.__revealTrace = [];
window.__revealDetail = null;
async function revealFile(name){
  const _rt = (step, info) => { try { window.__revealTrace.push(Object.assign({step: step, name: name, t: Date.now()}, info || {})); } catch(e){} };
  window.__revealDetail = null;
  // v2.8.11: bridge first (pywebview Api.reveal_file); the
  // /api/reveal endpoint is the fallback for a desktop browser
  // without the bridge.
  // v2.8.17: BOTH Explorer layers now pass the two-item list
  // ["explorer", "/select," + path]. The 2.8.14 verbatim
  // string was EXACTLY the bug (CPython outer-quotes a str
  // arg as one token, so CreateProcess cannot find the
  // program); the 2.8.11 three-item form put a space after
  // the comma (empty path to select). The bridge call also
  // races a 3s timeout now: if the pywebview bridge ever hangs
  // instead of answering, the click falls through to
  // /api/reveal instead of dying silently. A failed reveal
  // falls back to opening the folder itself instead of
  // doing nothing.
  // v2.8.20 (9): when the bridge runs but says NO, ask it WHY
  // (Api.get_last_reveal) instead of guessing -- the bridge
  // records the resolved path, the argv it spawned and the
  // exact error, and that record is what the toast below
  // names. The 2.8.18 probe proved the bridge REACHES
  // Api.reveal_file, so a dead click on the real PC is the
  // Explorer spawn itself -- see _spawn() in app.py.
  _rt("click", {bridge: !!(window.pywebview && window.pywebview.api && window.pywebview.api.reveal_file)});
  if(window.pywebview && window.pywebview.api && window.pywebview.api.reveal_file){
    try {
      const ok = await Promise.race([window.pywebview.api.reveal_file(name), new Promise(r => setTimeout(() => r(false), 3000))]);
      _rt("bridge", {ok: !!ok});
      if(ok) return;
      try {
        const lr = await window.pywebview.api.get_last_reveal();
        if(lr && typeof lr === "object"){
          window.__revealDetail = lr;
          _rt("bridge-detail", {error: lr.error || "", argv: lr.argv || null, path: lr.path || ""});
        }
      } catch(e2){}
    } catch(e){ _rt("bridge-error", {error: String((e && e.message) || e)}); }
  }
  try {
    const j = await postHostJ("/api/reveal", {name});
    _rt("fallback-api", {ok: !!(j && j.ok), error: (j && j.error) || ""});
    if(j && j.ok) return;
    const why = (window.__revealDetail && window.__revealDetail.error) || (j && j.error) || "";
    if(window.pywebview && window.pywebview.api && window.pywebview.api.open_folder){
      try {
        const opened = await window.pywebview.api.open_folder();
        _rt("fallback-folder", {ok: !!opened});
        // v2.8.18: the old code returned here without checking
        // the result -- a failed open_folder died silently.
        // Opening the folder is only a partial success (the
        // file is not highlighted), so say so.
        if(opened){ toast("Opened the folder — the file could not be highlighted" + (why ? ": " + why : "")); return; }
      } catch(e){ _rt("fallback-folder-error", {error: String((e && e.message) || e)}); }
    }
    toast("Could not show that file in its folder" + (why ? ": " + why : ""));
  } catch(e){ _rt("fallback-error", {error: String((e && e.message) || e)}); toast("Could not show that file in its folder"); }
}

async function clearPhoneCache(){
  for(const k in MEMBLOBS) delete MEMBLOBS[k];
  for(const k in DLSTATE) delete DLSTATE[k];
  try{ localStorage.setItem("dropit_dl", "{}"); }catch(e){}
  await DBCACHE.clear();
}

function fileRowHtml(f, idx){
  const ft = fileTime(f.ts || f.mtime);
  return `<div class="frow" data-frow="${esc(f.name)}"><div class="frowtop"><span class="fsel" style="transition-delay:${Math.min((idx||0)*35,350)}ms">${SVG.check}</span><span class="thwrap">${thumbFor(f.name)}${badgeFor(f.name)}</span>` +
    `<span class="fmeta"><span class="fname" title="${esc(f.name)}">${esc(f.name)}</span>` +
    `<span class="fsize">${fmt(f.size)}</span>` +
    (ft ? `<span class="ftime">${ft}</span>` : "") + `</span></div>`;
}
let svSel = false;
const svPicked = new Set();
let svCloser = null;
let svFiles = [];
function svPaint(){
  const v = $("#vcontent"); if(!v) return;
  v.querySelectorAll(".frow").forEach(r => r.classList.toggle("picked", svPicked.has(r.dataset.frow)));
}
function svUpd(){
  const c = $("#svcount"), ok = $("#svconfirm"); if(!c || !ok) return;
  const n = svPicked.size;
  c.textContent = n ? n + " selected" : "Select files";
  ok.textContent = n ? "Delete (" + n + ")" : "Delete";
  ok.disabled = !n;
}
function svSet(on){
  svSel = on;
  const v = $("#vcontent"); if(v) v.classList.toggle("selmode", on);
  const b = $("#svbar"); if(b) b.classList.toggle("show", on);
  if(!on){ svPicked.clear(); svPaint(); }
  svUpd();
}
function svOpen(){
  svSet(true);
  svCloser = (self) => { svSet(false); ovClosed(svCloser, self !== false); };
  ovOpened(svCloser);
}
function svExit(){
  if(svCloser){ const c = svCloser; svCloser = null; c(true); }
  else svSet(false);
}
function showSaved(){
  // v2.8.41 (5): re-sync the in-memory ledger from localStorage
  // before rendering -- DLSTATE is loaded once at boot, so a
  // ledger changed outside this page load (another tab, a
  // restore, a download recorded while this page was closed)
  // would otherwise render an empty/stale list. localStorage
  // is the persisted truth; in-memory changes are always
  // persisted alongside, so a full re-sync is safe.
  try { const _dl = JSON.parse(localStorage.getItem("dropit_dl") || "{}");
    Object.keys(DLSTATE).forEach(k => { if(!(_dl && k in _dl)) delete DLSTATE[k]; });
    Object.assign(DLSTATE, _dl); } catch(e){}
  const sfiles = Object.keys(DLSTATE).map(n => {
    const v = DLSTATE[n];
    return (v && typeof v === "object") ? {name:n, size:v.size, ts:v.ts} : {name:n, size:v, ts:0};
  });
  svFiles = sfiles;
  svSel = false; svPicked.clear(); svCloser = null;
  let html;
  if(!sfiles.length) html = '<p class="empty">Nothing saved on this device yet \u2014 tap Download on any file.</p>';
  else html = `<div class="svtools"><button class="btn dangergrad iconbtn" id="svdel" title="Delete files">${SVG.del}</button></div>` +
    `<div class="svbar" id="svbar"><span class="delcount" id="svcount">Select files</span><button class="canceldel" id="svcancel">Cancel</button><button class="selall" id="svall">All</button><button class="confirmdel" id="svconfirm" disabled>Delete</button></div>` +
    sfiles.map((f,i) =>
      fileRowHtml(f, i) +
      `<span class="fact">` +
      `<button data-sopen="${i}" title="Open">${SVG.open}</button></span></div>`
    ).join("");
  toast(sfiles.length ? sfiles.length + " file(s) saved on this device" : "Nothing saved on this device yet");
  showViewer("Saved on this device", html);
  document.querySelectorAll("[data-sopen]").forEach(b =>
    // v2.8.40 (5): Open hands the file to the OS / an app
    // (share sheet or server-side local open), never another
    // in-app preview and never a download.
    b.onclick = () => openSavedFileOS(sfiles[+b.dataset.sopen].name));
  // v2.8.39 (4): rows whose blob is gone from this device say
  // so (offline) -- same rule as the login-page Saved list.
  // While connected Open re-downloads, so rows stay normal.
  sfiles.forEach(async (f) => {
    let blob = null;
    try { blob = MEMBLOBS[f.name] || await DBCACHE.get(f.name); } catch(e){}
    if(blob) return;
    if(AUTH && AUTH.authed) return;
    const row = document.querySelector(`#vcontent .frow[data-frow="${CSS.escape(f.name)}"]`);
    if(!row || !row.isConnected) return;
    row.classList.add("gsaved-gone");
    const btn = row.querySelector("[data-sopen]");
    if(btn) btn.disabled = true;
    const meta = row.querySelector(".fmeta");
    if(meta) meta.insertAdjacentHTML("beforeend", '<span class="fsize" style="color:#f87171;font-weight:700">file has been removed</span>');
  });
  const svd = $("#svdel");
  if(svd) svd.onclick = () => { if(svSel) svExit(); else svOpen(); };
  const svc = $("#svcancel");
  if(svc) svc.onclick = () => svExit();
  const sva = $("#svall");
  if(sva) sva.onclick = () => {
    const names = svFiles.map(f => f.name);
    if(!names.length) return;
    if(names.every(n => svPicked.has(n))) names.forEach(n => svPicked.delete(n));
    else names.forEach(n => svPicked.add(n));
    svPaint(); svUpd();
  };
  const svo = $("#svconfirm");
  if(svo) svo.onclick = async () => {
    const names = [...svPicked];
    if(!names.length) return;
    if(!confirm("Remove " + names.length + " file(s) from this phone?")) return;
    for(const n of names){
      delete DLSTATE[n];
      try{ await DBCACHE.del(n); }catch(e){}
      delete MEMBLOBS[n];
    }
    try{ localStorage.setItem("dropit_dl", JSON.stringify(DLSTATE)); }catch(e){}
    svExit();
    lastFilesSig = null; loadFiles(); showSaved(); toast("Removed " + names.length + " file(s)");
  };
  const vcont = $("#vcontent");
  if(vcont) vcont.querySelectorAll(".frow").forEach(r =>
    r.addEventListener("click", e => {
      if(e.target.closest("button")) return;
      const n = r.dataset.frow;
      if(svSel){
        if(svPicked.has(n)) svPicked.delete(n); else svPicked.add(n);
        svPaint(); svUpd();
        return;
      }
      // v2.8.41 (5): tapping a saved file PREVIEWS it. The rows
      // had no preview handler at all -- only the Open button,
      // which hands the file to the OS -- so a tap on the file
      // itself did nothing. Same preview as the login-page
      // Saved list (previewSavedFile); closing it returns to
      // the main page, like every other file preview.
      previewSavedFile(n, true);
    }));
}

  function applyTheme(on){
    document.documentElement.classList.toggle("light", on);
    try{ localStorage.setItem("drop_theme", on ? "light" : "dark"); }catch(e){}
  }
  const themesw = $("#themesw");
  if(themesw) themesw.onclick = () =>
    applyTheme(!document.documentElement.classList.contains("light"));
  // v2.8.19: the login page's own theme toggle, below the
  // login card -- same switch as the footer's. It ONLY
  // switches the theme and must NEVER trigger Connect or any
  // address action: it is a <button type="button"> (never a
  // submit -- there is no form element on the page at all), and
  // the handler stops the tap dead here (preventDefault +
  // stopPropagation) so it cannot bubble into any
  // document-level handler or activate anything else. Live
  // verified (round35): tapping it on the login screen
  // leaves the guest on the login screen, theme switched,
  // no /api/connect issued. No Connect path exists from
  // this button -- its only handler is the one below, and
  // the 5s poll never calls checkAuth/doGuestLogin.
  const themeswLogin = $("#themeswLogin");
  if(themeswLogin) themeswLogin.addEventListener("click", (e) => {
    e.preventDefault(); e.stopPropagation();
    applyTheme(!document.documentElement.classList.contains("light"));
  });
// v2.8.29 (3): copy actions copy the FULL WORKING URL --
// http://<LAN IP>:<port>/, the SAME URL the QR code encodes
// (AUTH.connect_url, from /api/authstate) -- so pasting it
// into a browser opens the web version. 2.8.17 copied the
// .local form (AUTH.url / http://<name>.local:<port>/), which
// most phone browsers cannot resolve: the copied address
// could not open the web version while the QR could. The
// DISPLAYED address stays the .local form; only the COPIED
// value changes. A value that already carries .local / a port
// is used as-is.
async function ensureConnectUrl(){
  // checkAuth normally fills AUTH.connect_url at page load;
  // if it has not (yet), fetch it once so a copy tap still
  // gets the working URL instead of the .local fallback.
  if(AUTH && AUTH.connect_url) return;
  try { const r = await _origFetch("/api/authstate"); const st = await r.json();
    if(st && st.connect_url) AUTH = Object.assign(AUTH || {}, st);
  } catch(e){}
}
function fullAddressUrl(name){
  let n = String(name || (AUTH && AUTH.address_name) || "").trim();
  if(!n) return "";
  n = n.replace(/^https?:\/\//i, "").split("/")[0].trim();
  if(!n) return "";
  if(/\.local(:\d+)?$/i.test(n) || /:\d+$/.test(n)) return "http://" + n + "/";
  let port = (location.host.split(":")[1] || "");
  if(!port && AUTH && AUTH.url){ const m = AUTH.url.match(/:(\d+)\/?$/); if(m) port = m[1]; }
  // A bare IP is a host, not a name -- never append .local.
  if(/^\d{1,3}(\.\d{1,3}){3}$/.test(n) || /^\[[0-9a-fA-F:]+\]$/.test(n))
    return "http://" + n + (port ? ":" + port : "") + "/";
  // The CURRENT address copies the QR URL: the LAN-IP URL a
  // phone browser can actually open. Falls back to the .local
  // form only when the server never supplied one, and to this
  // page's own host when this page was itself reached by IP.
  const cur = (AUTH && AUTH.address_name) || "";
  if(n.toLowerCase() === cur.toLowerCase()){
    if(AUTH && AUTH.connect_url) return AUTH.connect_url.endsWith("/") ? AUTH.connect_url : AUTH.connect_url + "/";
    if(/^\d{1,3}(\.\d{1,3}){3}$/.test(location.hostname)) return "http://" + location.host + "/";
    if(AUTH && AUTH.url) return AUTH.url.endsWith("/") ? AUTH.url : AUTH.url + "/";
  }
  return "http://" + n + ".local" + (port ? ":" + port : "") + "/";
}
$("#copy").onclick = async () => {
  // v2.8.29 (3): copy the FULL WORKING URL (see
  // fullAddressUrl above -- the QR URL, not the .local form),
  // never the plain address text.
  await ensureConnectUrl();
  const url = fullAddressUrl() || "__ADDRESSNAME_TEXT__";
  try { await navigator.clipboard.writeText(url); }
  catch(e){ const i=document.createElement("input"); i.value=url; document.body.appendChild(i);
    i.select(); document.execCommand("copy"); i.remove(); }
  toast("Address copied \\u2014 send it to your phone");
};

const qp = $("#qrpop");
// v2.8.34 (3): pop-out on close -- add .closing, drop .open
// after the 160ms pop-out finishes. A re-open cancels the
// pending hide. Every close path below goes through here;
// the toggle re-opens through the same cancel so a click
// during the pop-out never loses to the pending timeout.
let _qrCloseT = null;
function closeQrPop(){
  if(!qp || !qp.classList.contains("open")) return;
  clearTimeout(_qrCloseT);
  qp.classList.add("closing");
  _qrCloseT = setTimeout(() => { qp.classList.remove("open", "closing"); }, 160);
}
document.querySelectorAll(".qrmini").forEach(b => { b.onclick = () => { if(!qp) return; if(qp.classList.contains("open")) closeQrPop(); else { clearTimeout(_qrCloseT); qp.classList.remove("closing"); qp.classList.add("open"); } }; });
// v2.7.87: the QR popup is a small centred in-window popup, dismissed
// by the x button, by clicking the backdrop itself (not the card),
// or by Escape -- never fullscreen, nothing cropped.
const _qrclose = $("#qrpopclose");
if(_qrclose) _qrclose.onclick = () => { closeQrPop(); };
if(qp) qp.addEventListener("mousedown", e => { if(e.target.id === "qrpop") closeQrPop(); });
document.addEventListener("keydown", e => { if(e.key === "Escape" && qp) closeQrPop(); });

const mpch = $("#mpchost");
// v2.7.86: this field shows the CLEAN link name only, never
// location.host (the technical .local:port address). It is filled
// from the live link name by paintAddressAll once checkAuth returns.
function maddrNorm(){
  let v = (mpch.value || "").trim();
  const low = v.toLowerCase();
  if(low.indexOf("http://") === 0) v = v.slice(7);
  else if(low.indexOf("https://") === 0) v = v.slice(8);
  return v.split("/")[0].trim();
}
const mpcc = $("#mpcconnect");
if(mpcc) mpcc.onclick = async () => {
  let v = maddrNorm();
  if(!v){ toast("Enter your PC's address"); return; }
  // v2.7.89 IDENTICAL link-name rule as host/guest link screens
  // and the server: a bare name with a dot or forbidden character
  // is rejected with the allowed-format message, never navigated
  // to as a (silently different) address.
  const bareM = v.replace(/\.local$/, "").split(":")[0];
  const isIP = /^\d+\.\d+\.\d+\.\d+$/.test(bareM);
  if(bareM && !bareM.includes(":") && !isIP){
    const merr = validateAddressName(bareM);
    if(merr){ toast(merr); return; }
  }
  try{ localStorage.setItem("dropit_pchost", v); }catch(e){}
  // v2.8.17 (k): Connect uses the REAL connect flow -- POST
  // /api/connect and WAIT for the PC's answer -- instead of
  // blindly navigating to a guessed host. A bare address name
  // (or the same name with this page's port) connects to this
  // PC's address; a locked address routes to the login page
  // with the address prefilled so the password can be entered
  // there. Only an IP / host:port naming a DIFFERENT machine
  // still navigates, as before -- /api/connect only ever
  // answers for this PC's own address.
  const hasPort = v.includes(":");
  const thisPort = location.host.split(":")[1] || "";
  const portPart = hasPort ? v.split(":")[1] : "";
  const useRealFlow = !isIP && (!hasPort || portPart === thisPort);
  if(useRealFlow){
    // v2.8.33: refresh the current address first, so the connect
    // never declares a stale one (see refreshAuthName).
    await refreshAuthName();
    showConnPop("connecting");
    let cj = await postJ("/api/connect", {link: bareM});
    if(cj.ok && cj.authed === false && cj.locked){
      const f = $("#gloginlink"); if(f) f.value = bareM;
      const saved = guestSavedAddressPw()[bareM];
      const p = $("#gloginpw"); if(p && saved){ p.value = saved; _glPwSt.saved = saved; _glPwSt.shown = true; }
      const sc = $("#gloginsavechk"); if(sc) sc.checked = !!saved;
      hideConnPop();
      showGuestLogin("This address needs a password — enter it to connect.");
      return;
    }
    if(cj.ok && cj.authed !== false){
      window._userDisconnected = false;
      setGuestConnectedAddress(cj.display_address || bareM);
      bumpAddressUse(cj.display_address || bareM);
      showConnPop("connected", cj.display_address || bareM);
      await checkAuth(); paintAddressAll();
      lastNotesSig = null; lastFilesSig = null; loadNotes(); loadFiles();
    } else if(cj.code === "wrong_link"){
      showConnPop("failed");
      toast(cj.error || "That is not this PC's address — check the address on the PC");
    } else {
      showConnPop("failed");
      toast(cj.error || "Couldn't connect to this address");
    }
    return;
  }
  // IP or host:port for another machine: navigate, as before.
  let host = v;
  if(/^[a-z0-9-]+$/.test(host)){
    const port = location.host.split(":")[1] || "";
    host = host + ".local" + (port ? ":" + port : "");
  }
  if(host === location.host){ toast("Already connected to this PC"); return; }
  location.href = "http://" + host + "/";
};
// v2.8.40 (3): the MB Set Up card has NO Save password checkbox
// (removed -- it was put there incorrectly in 2.8.39). The login
// page keeps its own Save password checkbox, and the sync helper
// that followed this card's box (syncMpSavePw, with its
// /api/addressinfo fetch on every address paint) is gone with it.
// v2.8.17 (k): the mobile-web Set Up Your Addresses dropdown --
// the APK-style list of previously used addresses. Rows come
// from the host history (/api/linkhistory) when it answers; a
// guest phone gets a 403 there (host-only), so it falls back to
// this device's own used addresses (localStorage, like the login
// page dropdown). Empty either way, the toggle and its "No saved
// addresses yet." row are still shown. Selecting a row fills the
// address field; it never connects by itself.
async function paintMobileAddressHistory(){
  const list = $("#mddlist"); if(!list) return;
  let entries = null;
  let names = [];
  try {
    const r = await _origFetch("/api/linkhistory"); const j = await r.json();
    if(j.ok && j.entries){ entries = j.entries; names = j.entries.map(e => e.name); }
  } catch(e){}
  const saved = guestSavedAddressPw();
  if(!names.length){
    const c = addressUseCounts();
    names = Object.keys(c).sort((a, b) => c[b] - c[a]).slice(0, 20);
  }
  const typed = (mpch && mpch.value) || "";
  if(!names.length){
    list.innerHTML = '<div class="ddopt ddempty"><span class="ddname">No saved addresses yet.</span></div>';
    return;
  }
  // v2.8.39 (5a): every row shows its saved-password state,
  // like the Set Up history list -- dots when a copy is saved
  // (here or on the host), "Locked - No Saved Password" for a
  // locked address with nothing saved, "No password" for an
  // open one. The 2.8.38 rows showed the name only, which is
  // the photo's missing state. The host-history path carries
  // password_saved / locked per entry; the local fallback
  // knows only this device's own saved copies, so rows without
  // one start at "No Password Saved" and are refined by
  // /api/addressinfo below.
  const pwState = (n) => {
    if(saved[n]) return "••••••";
    if(entries){
      const e = entries.find(x => x.name === n);
      if(e) return e.password_saved ? "••••••" : (e.locked ? "Locked - No Saved Password" : "No password");
    }
    return "No Password Saved";
  };
  list.innerHTML = names.map(n => '<div class="ddopt' + (n === typed ? ' ddsel' : '') + '" data-name="' + esc(n) + '"><span class="ddname">' + addressDotHtml(n) + '</span><span class="ddpw">' + pwState(n) + '</span>' +
    (saved[n] ? '<button class="ddeye" data-meye="' + esc(n) + '" title="Show saved password">' + eyeSVG(false) + '</button>' : "") +
    '</div>').join("");
  list.querySelectorAll(".ddopt").forEach(opt => {
    opt.onclick = () => {
      const name = opt.dataset.name;
      if(mpch) mpch.value = name;
      list.classList.remove("open");
      const ch = $("#mddchev"); if(ch) ch.textContent = "▾";
    };
  });
  list.querySelectorAll("[data-meye]").forEach(b => { b.onclick = (ev) => {
    ev.stopPropagation();
    const row = b.closest(".ddopt");
    const pwSpan = row.querySelector(".ddpw");
    if(pwSpan.dataset.revealed){ pwSpan.textContent = "••••••"; delete pwSpan.dataset.revealed; paintEyeBtn(b, false); return; }
    const pw = guestSavedAddressPw()[b.dataset.meye];
    if(pw){ pwSpan.textContent = pw; pwSpan.dataset.revealed = "1"; paintEyeBtn(b, true); }
  }; });
  // v2.8.39 (5a): refine local-fallback rows with no saved copy
  // via the server's address state -- a locked address reads
  // "Locked - No Saved Password", an open one "No password".
  // Only while the list is still open and the row still listed.
  if(!entries){
    names.forEach(async n => {
      if(saved[n]) return;
      try {
        const rr = await _origFetch("/api/addressinfo?address=" + encodeURIComponent(n));
        const jj = await rr.json();
        if(!jj.ok || !jj.known) return;
        const row = list.querySelector('.ddopt[data-name="' + CSS.escape(n) + '"]');
        if(!row || !row.isConnected) return;
        const sp = row.querySelector(".ddpw");
        if(sp && !sp.dataset.revealed) sp.textContent = jj.needs_password ? "Locked - No Saved Password" : "No password";
      } catch(e){}
    });
  }
}
const _mddt = $("#mddtoggle");
if(_mddt) _mddt.onclick = async (ev) => {
  if(ev) ev.stopPropagation();
  const l = $("#mddlist"); if(!l) return;
  const willOpen = !l.classList.contains("open");
  if(willOpen) await paintMobileAddressHistory();
  l.classList.toggle("open", willOpen);
  const ch = $("#mddchev"); if(ch) ch.textContent = willOpen ? "▴" : "▾";
};
if(!window._mddDocBound){ window._mddDocBound = true; document.addEventListener("click", (e) => { const l = document.querySelector("#mddlist"); const c = document.querySelector("#mddchev"); if(l && (!e.target.closest || !e.target.closest(".maddrwrap"))){ l.classList.remove("open"); if(c) c.textContent = "▾"; } }); }
paintMobileAddressHistory();

const mpcd = $("#mpcdisconnect");
if(mpcd) mpcd.onclick = () => { window._userDisconnected = true; doLogout(); toast("Disconnected"); };
const mcp = $("#mcopy");
if(mcp) mcp.onclick = async () => {
  // v2.8.29 (3): copy the FULL WORKING URL (see
  // fullAddressUrl), never the plain address text.
  await ensureConnectUrl();
  const v = fullAddressUrl(maddrNorm() || undefined);
  if(!v){ toast("No address to copy"); return; }
  toast(await copyText(v) ? "Address copied" : "Couldn't copy address");
};
const msb = $("#msavedbtn");
if(msb) msb.onclick = () => showSaved();

const of = $("#openfolder");
if(of) of.onclick = () => {
  // Files tab: ADDRESS folder (this address's direct folder),
  // never the root -- see the menu handlers for root routing.
  if(hasBridge()){ try { window.pywebview.api.open_folder(); } catch(e){} return; }
  // Phone web has no OS folder to open: show this link's files instead.
  loadFiles();
  toast("This address's files are listed below");
};

const cf = $("#changefolder");
if(cf){
  // Files tab: ADDRESS folder (this address's direct folder),
  // never the root -- see the menu handlers for root routing.
  // v2.8.31: always the per-address route, ON or OFF -- the
  // old OFF retarget to the Main Folder blocked choosing a
  // folder for an address.
  // Desktop: native folder browser (Explorer/Finder) - clicks just work.
  // Other surfaces: type the PC path, saved via /api/setlinkfolder.
  cf.onclick = async () => {
    if(!hasBridge()){
      const cur = (AUTH && AUTH.folder) || "";
      const path = prompt("Folder on this PC for this address:", cur);
      if(!path) return;
      const j = await postJ("/api/setlinkfolder", {folder: path});
      if(j.ok){ await checkAuth(); toast("Save folder changed"); loadFiles(); }
      else toast(j.error || "Couldn't change the folder");
      return;
    }
    cf.disabled = true;
    try {
      const r = await window.pywebview.api.browse_directory();
      if(r && r.ok){
        const dl = $("#dirnamelabel");
        if(dl) dl.textContent = r.directory || r.dirname;
        // v2.8.31: re-read auth so the destination line
        // shows the new folder from the server, not just
        // the optimistic value above.
        await checkAuth();
        toast("Save folder changed");
        loadFiles();
      } else if(r && r.error && r.error !== "cancelled"){
        toast("Couldn't change the folder: " + r.error);
      }
    } catch(e){ toast("Couldn't open the folder picker"); }
    cf.disabled = false;
  };
}

drop.onclick = () => { if(AUTH && !AUTH.host && AUTH.authed && !canUploadUI()){ toast("No permission to upload files to this device"); return; } picker.click(); };
// v2.8.39 (8): Shared Files "+ Add New" (web PC only -- hidden
// on the desktop app by CSS). Same as the Upload tab's file
// chooser: opens the picker, and the picker's change handler
// uploads the chosen files. Guests without upload permission
// get the exact no-permission message, like the drop zone.
const _fab = $("#fileaddbtn");
if(_fab) _fab.onclick = () => { if(AUTH && !AUTH.host && AUTH.authed && !canUploadUI()){ toast("No permission to upload files to this device"); return; } picker.click(); };
["dragover","dragenter"].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.add("over"); }));
["dragleave","drop"].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", ev => uploadFiles(ev.dataTransfer.files));
picker.addEventListener("change", () => { uploadFiles(picker.files); picker.value=""; });

// v2.8.17 (j): ONE floating circular upload indicator replaces
// the old per-file .up rows + .bar progress bars (removed -- see
// the .upfloat CSS). The ring is solid blue and fills in real
// time from xhr.upload.onprogress across the whole queue; the
// NUMBER inside the circle is the files still queued and
// DECREMENTS as each file finishes, while the ring keeps
// filling. Transparent background; the file name is truncated
// with an ellipsis and never overflows its border. A pop sound
// plays per file sent (playPopSound); notes get the pop only,
// never a progress bar. boxSel is kept for the call sites --
// both the desktop #uploads and mobile #muploads share the one
// floating indicator.
const _upQ = { total: 0, loaded: 0, pending: [], xhrs: [], cancelled: false };
window.__upQ = _upQ;
function _upRender(){
  const left = _upQ.pending.length;
  // v2.8.31: the number NEVER shows "0" -- when the queue
  // empties the pill fades out instead (see _upHide), so the
  // last count stays on screen while it fades. The ring still
  // fills to full and the name clears below.
  const n = $("#upringnum"); if(n && left > 0) n.textContent = String(left);
  const nm = $("#upfloatname"); if(nm) nm.textContent = left ? (_upQ.pending[0].name || "") : "";
  const p = $("#upringprog");
  if(p){ const c = 163.36; const frac = _upQ.total ? Math.min(1, _upQ.loaded / _upQ.total) : 0; p.style.strokeDashoffset = String(c * (1 - frac)); }
}
function _upShow(){
  const f = $("#upfloat"); if(!f) return;
  // v2.8.31: a new upload cancels any in-progress fade-out.
  f.classList.remove("fading");
  // v2.8.28: width = the Devices Connected pill's live width
  // (#statusdiv, X included -- the upload pill has its own
  // cancel X inside the same total width). Set it first so
  // the centring and the search-button clearance below are
  // computed on the real width. Falls back to the CSS width
  // (272px) when the Devices pill is not measurable (e.g.
  // mobile, where the topbar is hidden).
  const dev = $("#statusdiv");
  if(dev && dev.offsetWidth > 0) f.style.width = dev.offsetWidth + "px";
  // v2.8.24 (3): the ring sits at the TOP of the Shared Files
  // card (top edge, just below the top pill) -- the pill's
  // bottom edge sits 12px above the card's top edge (v2.8.26:
  // moved slightly higher, was 4px), so the card header stays
  // fully visible and the footer is never covered. Falls back
  // to top-centre when the files column is hidden (e.g.
  // another mobile tab is active).
  const col = document.querySelector('.col[data-col="files"]');
  let placed = false;
  if(col){
    const r = col.getBoundingClientRect();
    if(r.width > 0 && r.height > 0){
      f.style.left = Math.round(r.left + r.width / 2) + "px";
      f.classList.add("show");
      const ph = f.offsetHeight || 36;
      f.style.top = Math.max(8, Math.round(r.top - ph - 12)) + "px";
      placed = true;
    }
  }
  if(!placed){ f.style.left = "50%"; f.style.top = "88px"; f.classList.add("show"); }
  // v2.8.28: line the pill up with the search button -- when
  // the pill's vertical band is near the button's (desktop
  // widths, where the pill sits just under the topbar), snap
  // the pill's centre to the button's centre. At 1280px that
  // moves the pill 6px up (centre 58 -> 52). At stacked
  // widths (e.g. 1024px) the pill is far down the page, so
  // the snap does not fire and the card-relative position
  // is kept.
  const s = document.querySelector("#askbtn");
  if(s && placed){
    const sr = s.getBoundingClientRect();
    if(sr.width > 0){
      const fr = f.getBoundingClientRect();
      const scy = sr.top + sr.height / 2;
      const fcy = fr.top + fr.height / 2;
      if(Math.abs(fcy - scy) <= 24){
        f.style.top = Math.round(scy - fr.height / 2) + "px";
      }
    }
  }
  _upKeepClearOfSearch(f);
  // v2.8.31 (Essef Nov 6): WEB ONLY -- the pill sits slightly
  // HIGHER (6px up), still centred/aligned with the card. The
  // PC app (html.pcapp, pywebview bridge) keeps its 2.8.30
  // position byte-identical: this runs only when the page is
  // NOT the PC app. _upShow recomputes top from scratch on
  // every call, so the shift never accumulates.
  if(!document.documentElement.classList.contains("pcapp")){
    const cur = parseInt(f.style.top || "0", 10);
    if(!isNaN(cur)) f.style.top = Math.max(8, cur - 6) + "px";
  }
}
// v2.8.27: the pill must NEVER touch the search button (#askbtn,
// magnifier, top-right of the topbar). At desktop widths the
// board is centred with a max-width, so the files column -- and
// the pill centred on it -- reaches almost to the viewport's
// right edge, where the search button sits; on 2.8.26 the pill
// overlapped the button by 2px at 1280px. After every
// positioning, shift the pill left just enough that its right
// edge stays at least 8px clear of the button's left edge
// (only when their vertical bands overlap). Size, height and
// the 12px gap above the card are untouched.
function _upKeepClearOfSearch(f){
  const s = document.querySelector("#askbtn"); if(!s || !f) return;
  const sr = s.getBoundingClientRect(); if(sr.width <= 0) return;
  const fr = f.getBoundingClientRect();
  const vOverlap = Math.min(fr.bottom, sr.bottom) - Math.max(fr.top, sr.top);
  if(vOverlap <= 0) return;
  const maxRight = sr.left - 8;
  if(fr.right <= maxRight) return;
  const shift = fr.right - maxRight;
  const cx = fr.left + fr.width / 2;
  const nl = Math.max(fr.width / 2 + 12, cx - shift);
  f.style.left = Math.round(nl) + "px";
}
function _upHide(){
  // v2.8.31: the pill ANIMATES away (opacity fade, .4s) after
  // the last file -- no "0" state, no empty pill. The .show
  // class is removed only once the fade has finished; a new
  // upload in between clears .fading in _upShow, which makes
  // the pending removal below a no-op.
  const f = $("#upfloat"); if(!f) return;
  if(!f.classList.contains("show") || f.classList.contains("fading")) return;
  f.classList.add("fading");
  setTimeout(() => { if(f.classList.contains("fading")) f.classList.remove("show", "fading"); }, 400);
}
// v2.8.24 (3): the X on the ring CANCELS the in-flight
// upload -- every live XHR is aborted, the queue empties
// without "sent" toasts, and the ring hides. Files that
// already finished stay sent; nothing new is uploaded.
const _upCancelBtn = $("#upcancel");
if(_upCancelBtn) _upCancelBtn.onclick = () => {
  if(!_upQ.pending.length || _upQ.cancelled) return;
  _upQ.cancelled = true;
  const live = _upQ.xhrs.slice(); _upQ.xhrs = [];
  live.forEach(x => { try { x.abort(); } catch(e){} });
  toast("Upload cancelled");
};
function uploadFiles(files, boxSel){
  // v2.7.99: guests without upload permission get the exact
  // no-permission message instead of uploading (the server
  // 403s as backstop).
  if(AUTH && !AUTH.host && AUTH.authed && !canUploadUI()){ toast("No permission to upload files to this device"); return; }
  const list = [...files];
  if(!list.length) return;
  _upQ.total = list.reduce((a, f) => a + (f.size || 0), 0);
  _upQ.loaded = 0;
  _upQ.pending = list.slice();
  _upQ.xhrs = []; _upQ.cancelled = false;
  _upRender(); _upShow();
  const perFile = new Map(list.map(f => [f, 0]));
  list.forEach(f => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload");
    _upQ.xhrs.push(xhr);
    xhr.upload.onprogress = ev => {
      if(ev.lengthComputable){
        const prev = perFile.get(f) || 0;
        perFile.set(f, ev.loaded);
        _upQ.loaded += (ev.loaded - prev);
        _upRender();
      }
    };
    const finish = (ok, cancelled) => {
      const prev = perFile.get(f) || 0;
      _upQ.loaded += ((f.size || 0) - prev); perFile.set(f, f.size || 0);
      const ix = _upQ.pending.indexOf(f); if(ix >= 0) _upQ.pending.splice(ix, 1);
      const xi = _upQ.xhrs.indexOf(xhr); if(xi >= 0) _upQ.xhrs.splice(xi, 1);
      // v2.8.24 (3): a cancelled upload finishes quietly -- no
      // "sent" toast, no failure toast, no list reload; the ring
      // just hides once the queue is empty.
      if(cancelled){ _upRender(); if(!_upQ.pending.length) setTimeout(_upHide, 1200); return; }
      if(ok){ playPopSound(); toast("\u2705 "+f.name+" sent"); loadFiles(); }
      _upRender();
      // v2.8.31: fade out promptly after the last file (was
      // 1200ms lingering on the finished pill).
      if(!_upQ.pending.length) setTimeout(_upHide, 400);
    };
    xhr.onload = () => {
      if(xhr.status === 200) finish(true);
      else if(xhr.status === 403){ finish(false); toast("No permission to upload files to this device"); }
      else { finish(false); toast("Upload failed: "+f.name); }
    };
    xhr.onerror = () => { finish(false); toast("Upload failed: "+f.name); };
    xhr.onabort = () => { finish(false, true); };
    const fd = new FormData(); fd.append("file", f);
    xhr.send(fd);
  });
}

async function sendSnippet(ta){
  const text = ta.value.trim();
  if(!text){ toast("Type something first"); return; }
  // v2.7.99: guests without add-notes permission get the exact
  // no-permission message instead of sharing (server 403s too).
  if(AUTH && !AUTH.host && AUTH.authed && !canAddNotesUI()){ toast("No permission to add notes on this device"); return; }
  try {
    const r = await fetch("/api/snippet", {method:"POST",
      headers:{"Content-Type":"application/json"}, body:JSON.stringify({text})});
    const j = await r.json();
    if(j.ok){ ta.value=""; playPopSound(); toast("\u2705 Text shared"); loadNotes(); }
    else toast((r.status === 403 && j.error) ? j.error : "Couldn't share that text");
  } catch(e){ toast("Couldn't share that text"); }
}
$("#sendsnippet").onclick = () => sendSnippet($("#snippet"));
$("#msendsnippet").onclick = () => sendSnippet($("#msendtext"));
$("#msendfiles").onclick = () => { if(AUTH && !AUTH.host && AUTH.authed && !canUploadUI()){ toast("No permission to upload files to this device"); return; } $("#mpicker").click(); };
$("#mpicker").addEventListener("change", () => { uploadFiles($("#mpicker").files, "#muploads"); $("#mpicker").value=""; });

const NOTES = {};
const NOTEOBJ = {};
let starredOnly = false;
const EXPANDED = new Set();  // note ids the user expanded - survives the 5s re-render
function noteTime(ts){
  return new Date(ts*1000).toLocaleString([], {month:"short", day:"numeric", hour:"numeric", minute:"2-digit"});
}
function fileTime(ts){ return ts ? noteTime(ts) : ""; }
// ---------- note download state: Download once, Open after ----------
const NOTEDL = {};
try { Object.assign(NOTEDL, JSON.parse(localStorage.getItem("dropit_notedl") || "{}")); } catch(e){}
function persistNotedl(){ try{ localStorage.setItem("dropit_notedl", JSON.stringify(NOTEDL)); }catch(e){} }
function paintNoteDlBtn(btn, id){
  const opened = !!NOTEDL[id];
  btn.innerHTML = opened ? SVG.open : SVG.dl;
  btn.title = opened ? "Open" : "Download";
}
function noteDlTap(btn){
  const id = btn.dataset.dl;
  if(NOTEDL[id]) openNote(id);
  else {
    // v2.7.99: guests without download permission get the exact
    // no-permission message instead of downloading the note
    // (server 403s /api/notes/dl as backstop).
    if(AUTH && !AUTH.host && AUTH.authed && !canDownloadUI()){ toast("No permission to download files from this device"); return; }
    dlNote(id, btn);
  }
}
async function copyText(t){
  try { await navigator.clipboard.writeText(t); return true; }
  catch(e){
    try {
      const ta = document.createElement("textarea");
      ta.value = t; ta.style.cssText = "position:fixed;opacity:0;top:0;left:0";
      document.body.appendChild(ta); ta.select();
      const ok = document.execCommand("copy"); ta.remove();
      return !!ok;
    } catch(e2){ return false; }
  }
}
async function copyNote(id){
  const t = NOTES[id] || "";
  if(!t){ toast("Nothing to copy"); return; }
  toast(await copyText(t) ? "Text copied" : "Couldn't copy text");
}
async function shareNote(id){
  const t = NOTES[id] || "";
  if(!t){ toast("Nothing to share"); return; }
  if(navigator.share){
    try { await navigator.share({text:t}); return; }
    catch(e){ if(e && e.name === "AbortError") return; }
  }
  toast(await copyText(t) ? "Share sheet unavailable \u2014 text copied" : "Couldn't copy text");
}
function startRename(card, note){
  if(!card || !note) return;
  // v2.8.0: renaming is editing -- Add / Edit Notes gates it.
  if(AUTH && !AUTH.host && AUTH.authed && !canAddNotesUI()){ toast("No permission to add notes on this device"); return; }
  const who = card.querySelector(".who");
  if(!who || who.querySelector("input")) return;
  let done = false, cancelled = false;
  who.innerHTML = "";
  who.classList.add("editing");
  const inp = document.createElement("input");
  inp.className = "renamein"; inp.value = note.title || "";
  inp.placeholder = note.label || "Shared Text";
  inp.setAttribute("aria-label", "Rename text");
  const ok = document.createElement("button");
  ok.className = "rnbtn ok pop"; ok.innerHTML = SVG.check; ok.title = "Save";
  const xx = document.createElement("button");
  xx.className = "rnbtn xx pop"; xx.textContent = "✕"; xx.title = "Cancel";
  who.appendChild(inp); who.appendChild(ok); who.appendChild(xx);
  inp.focus(); inp.select();
  const finish = async save => {
    if(done) return; done = true;
    const t = save ? inp.value.trim() : null;
    // Tear the editor down first: loadNotes() refuses to re-render while a
    // .renamein input exists, so leaving it in place deadlocks the card.
    who.textContent = (t !== null && t !== "") ? t : (note.title || note.label || "Shared Text");
    who.classList.remove("editing");
    if(t !== null && t !== (note.title || "")){
      let rr = null;
      try { rr = await fetch("/api/notes/rename", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({id: note.id, title: t})}); } catch(e){}
      if(rr && rr.status === 403) toast("No permission to add notes on this device");
    }
    lastNotesSig = null; loadNotes();
  };
  ok.onclick = () => finish(true);
  xx.onmousedown = e => { e.preventDefault(); cancelled = true; finish(false); };
  inp.onkeydown = e => { if(e.key === "Enter") finish(true); else if(e.key === "Escape"){ cancelled = true; finish(false); } };
  inp.onblur = () => { if(!cancelled) finish(true); };
}
async function toggleStar(id, btn){
  const note = NOTEOBJ[id]; if(!note) return;
  // v2.7.99: guests without star permission get the exact
  // no-permission message instead of starring (server 403s too).
  if(AUTH && !AUTH.host && AUTH.authed && !canStarUI()){ toast("No permission to star notes on this device"); return; }
  const next = !note.starred;
  let r = null;
  try { r = await fetch("/api/notes/star", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({id, starred: next})}); } catch(e){}
  if(r && r.status === 403){ toast("No permission to star notes on this device"); return; }
  if(btn){ btn.classList.toggle("starred", next); }
  lastNotesSig = null; loadNotes();
}
function collapseEl(el, done){
  if(!el){ if(done) done(); return; }
  el.style.height = el.offsetHeight + "px";
  el.classList.add("dying");
  requestAnimationFrame(() => {
    el.style.height = "0px"; el.style.opacity = "0";
    el.style.marginTop = "0"; el.style.marginBottom = "0";
    el.style.paddingTop = "0"; el.style.paddingBottom = "0"; el.style.borderWidth = "0";
  });
  setTimeout(() => { el.remove(); if(done) done(); }, 310);
}
async function delNote(id){
  // v2.7.90: the note-delete control stays VISIBLE but greyed
  // out for guests when "Guests can delete notes" is OFF, and
  // tapping it shows the not-authorized message (server 403
  // backstop) instead of deleting.
  if(AUTH && !AUTH.host && AUTH.authed && !canDeleteNotesUI()){ toast("No permission to delete notes from this device"); return; }
  if(!confirm("Delete this text note?")) return;
  const card = document.querySelector('.snipcard[data-nid="' + id + '"]');
  let r = null;
  try { r = await fetch("/api/notes/delete", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({id})}); } catch(e){}
  if(r && r.status === 403){ toast("No permission to delete notes from this device"); return; }
  collapseEl(card);
  setTimeout(() => { lastNotesSig = null; loadNotes(); }, 320);
  toast("Shared Text Deleted");
}
async function dlNote(id, btn){
  const t = NOTES[id] || "";
  if(!t){ toast("Nothing to download"); return; }
  try {
    if(window.pywebview && window.pywebview.api && window.pywebview.api.save_note){
      const r = await window.pywebview.api.save_note({id, text: t});
      if(r && r.ok){ NOTEDL[id] = r.path || true; persistNotedl(); if(btn) paintNoteDlBtn(btn, id); toast("Note saved"); }
      else toast("Download cancelled");
      return;
    }
  } catch(e){}
  location.href = "/api/notes/dl?id=" + encodeURIComponent(id);
  NOTEDL[id] = true; persistNotedl(); if(btn) paintNoteDlBtn(btn, id);
}
async function openNote(id){
  const t = NOTES[id] || "";
  const saved = NOTEDL[id];
  try {
    if(typeof saved === "string" && window.pywebview && window.pywebview.api && window.pywebview.api.open_path){
      if(await window.pywebview.api.open_path(saved)) return;
    }
  } catch(e){}
  if(!t){ toast("Nothing to open"); return; }
  showViewer("Shared Text", "<pre>" + esc(t) + "</pre>");
}
function editNote(id, card){
  // v2.8.0: editing is gated by Add / Edit Notes, like adding.
  if(AUTH && !AUTH.host && AUTH.authed && !canAddNotesUI()){ toast("No permission to add notes on this device"); return; }
  const box = card.querySelector(".sniptext");
  const cur = NOTES[id] || "";
  box.innerHTML = "";
  const ta = document.createElement("textarea");
  ta.value = cur; ta.rows = 5; ta.className = "editbox";
  const row = document.createElement("div"); row.className = "snipactions";
  const save = document.createElement("button"); save.className = "btn"; save.textContent = "Save";
  const cancel = document.createElement("button"); cancel.className = "btn"; cancel.textContent = "Cancel";
  row.appendChild(save); row.appendChild(cancel);
  box.appendChild(ta); box.appendChild(row);
  ta.focus();
  const closeEditor = () => { ta.remove(); row.remove(); };
  save.onclick = async () => {
    const text = ta.value.trim();
    if(!text){ toast("Shared Text Is Empty \u2014 Not Saved"); return; }
    let r = null;
    try { r = await fetch("/api/notes/edit", {method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({id, text})}); } catch(e){}
    if(r && r.status === 403){ toast("No permission to add notes on this device"); return; }
    closeEditor(); lastNotesSig = null; loadNotes(); toast("Shared Text Updated");
  };
  cancel.onclick = () => { closeEditor(); lastNotesSig = null; loadNotes(); };
}
function linkify(s){
  return s.replace(/(https?:\\/\\/[^\\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
}

let lastFilesSig = null;
// AI scan tracking: new files get a spinner until we know if they have text.
// v2.8.40: scan state is keyed PER ADDRESS (aiKey) -- switching
// addresses never re-scans files already scanned for that address,
// and a scan left running for another address never disturbs this
// list. The scan NEVER forces a list re-render (see loadFiles /
// paintAiCell): a resolved file patches only its own row, so
// thumbnails, video posters, scroll and selection stay put while
// scans run -- the 5s poll re-render storm is gone.
const seenFiles = new Set(), pendingAi = new Set(), aiReady = new Set();
function aiPrefix(){
  return ((AUTH && (AUTH.address_key || AUTH.address_name)) || "") + "\\n";
}
function aiKey(name){ return aiPrefix() + name; }
function pendingHere(){
  const p = aiPrefix(); let n = 0;
  pendingAi.forEach(k => { if(k.indexOf(p) === 0) n++; });
  return n;
}
// v2.8.40: patch ONE file row's AI control in place -- spinner to
// ✨ (has text) or to nothing (no text). Never rebuilds #files.
function paintAiCell(name, hasText){
  const row = document.querySelector('#files .frow[data-frow="' + CSS.escape(name) + '"]');
  if(!row) return;
  const cell = row.querySelector(".fact");
  if(!cell) return;
  const first = cell.firstElementChild;
  const isSpinner = !!(first && first.classList.contains("aiload"));
  const isSparkle = !!(first && first.querySelector && first.querySelector(".em"));
  if(hasText){
    if(isSparkle) return;
    const b = document.createElement("button");
    b.setAttribute("title", "AI tools");
    b.style.setProperty("--c1", "#a78bfa"); b.style.setProperty("--c2", "#8b5cf6");
    b.innerHTML = '<span class="em">✨</span>';
    b.onclick = (e) => { e.stopPropagation(); openAiPopup(name, b); };
    if(isSpinner) first.replaceWith(b); else cell.insertBefore(b, cell.firstChild);
  }else if(isSpinner){
    first.remove();
  }
}
let selMode = false;
const picked = new Set();
let selCloser = null;
function updateDelBar(){
  const n = picked.size, bar = $("#delbar"); if(!bar) return;
  $("#delcount").textContent = n ? n + " selected" : "Select files";
  const c = $("#delconfirm");
  // Selected count as a small solid purple badge on Delete,
  // not plain "(n)" text.
  c.innerHTML = n ? 'Delete <span class="tabbadge">' + n + "</span>" : "Delete";
  c.disabled = !n;
}
function selSet(on){
  selMode = on;
  $("#files").classList.toggle("selmode", on);
  const bar = $("#delbar"); if(bar) bar.classList.toggle("show", on);
  if(!on){
    picked.clear();
    document.querySelectorAll("#files .frow.picked").forEach(r => r.classList.remove("picked"));
  }
  updateDelBar();
}
function selOpen(){
  selSet(true);
  selCloser = (self) => { selSet(false); ovClosed(selCloser, self !== false); };
  ovOpened(selCloser);
}
function selExit(){
  if(selCloser){ const c = selCloser; selCloser = null; c(true); }
  else selSet(false);
}
function togglePick(row){
  const name = row.dataset.frow;
  if(picked.has(name)){ picked.delete(name); row.classList.remove("picked"); }
  else { picked.add(name); row.classList.add("picked"); }
  updateDelBar();
}


async function loadFiles(){
  const box = $("#files");
  try {
    const r = await fetch("/api/files"); const files = await r.json();
    const sig = files.map(f => f.name + "|" + f.size).join(";");
    // track brand-new files for AI text scanning (even if list otherwise same)
    let newOnes = false;
    // v2.8.40: a server verdict that just landed for a file that
    // was still spinning (durable no-text, or has-text) patches
    // that row in place below -- no re-render for it either.
    const toPatch = [];
    for(const f of files){
      const k = aiKey(f.name);
      f._aik = k;
      if(f.ai){
        if(pendingAi.has(k)){ pendingAi.delete(k); toPatch.push([f.name, true]); }
        aiReady.add(k);
      }else if(f.ai_known){
        if(pendingAi.has(k)){ pendingAi.delete(k); toPatch.push([f.name, false]); }
      }
      if(!seenFiles.has(k)){
        seenFiles.add(k); newOnes = true;
        if(!f.ai && !f.ai_known && !aiReady.has(k)) pendingAi.add(k);
      }
    }
    if(sig === lastFilesSig && !newOnes){
      // unchanged: skip re-render so video thumbs never flicker.
      // AI scan state NEVER forces one either -- patch any rows
      // whose verdict just landed and return.
      toPatch.forEach(([n, h]) => paintAiCell(n, h));
      return;
    }
    lastFilesSig = sig;
    $("#filecount").textContent = files.length || "";
    $("#mfilecount").textContent = files.length || "";
    const dab = $("#delallbtn"); if(dab){ dab.style.display = files.length ? "" : "none"; paintDeleteState(); }
    if(!files.length){ box.innerHTML = '<p class="empty">Nothing here yet &mdash; beam something over from your phone.</p>'; return; }
    // v2.8.9: hyperlink-like rows on the DESKTOP page only --
    // the bridge is present, so the page is the desktop app.
    // Phone web / APK never get this class (see the CSS).
    box.classList.toggle("desktoplink", hasBridge());
    box.innerHTML = files.map((f,i) =>
      fileRowHtml(f, i) +
      `<span class="fact">` +
      (f.ai || aiReady.has(f._aik) ? `<button data-ai="${i}" title="AI tools" style="--c1:#a78bfa;--c2:#8b5cf6"><span class="em">✨</span></button>`
        : pendingAi.has(f._aik) ? `<span class="aiload" title="Scanning for text…"></span>` : "") +
      `<button data-dl="${i}" data-name="${esc(f.name)}" title="${dlLabel(f)}" style="--c1:#7dd3fc;--c2:#4f46e5">${dlLabel(f) === "Open" ? SVG.open : SVG.dl}</button></span></div>`
    ).join("");
    box.querySelectorAll("[data-dl]").forEach(b =>
      b.onclick = () => { const f = files[+b.dataset.dl];
        // v2.8.24 (2): the row button OPENS the file directly
        // (fileTap: bridge open_file on the desktop, Download
        // then Open elsewhere) -- no preview detour, no
        // reveal-in-folder. Clicking the file NAME / thumbnail
        // still previews in-page. "Show in folder" moved to
        // the file-row right-click menu (see showMenu).
        // v2.8.30 (4): WEB brings back Download -> Open
        // (Essef Nov 6, ~5:24 PM -- the 2.8.25 always-Open
        // icon is reverted for WEB only). The button shows
        // the download arrow + title "Download" until the
        // file is saved on this device (dlLabel: Open only
        // when hasBridge() or isDownloaded(f)); after a
        // completed download it re-renders as Open, and a
        // discarded / failed download never marks it, so it
        // stays Download. The PC app is untouched: dlLabel
        // is always "Open" there (hasBridge), so its direct
        // open_file behaviour and icon are exactly as before.
        fileTap(f, b); });
    box.querySelectorAll("[data-ai]").forEach(b =>
      b.onclick = (e) => { e.stopPropagation(); openAiPopup(files[+b.dataset.ai].name, b); });
    box.querySelectorAll(".frow").forEach(row => {
      if(picked.has(row.dataset.frow)) row.classList.add("picked");
      row.addEventListener("click", e => {
        if(e.target.closest("button")) return;
        if(selMode){ togglePick(row); return; }
        // v2.8.11: clicking a file's NAME, THUMBNAIL or DATE
        // previews it in-page (web + desktop alike); the
        // per-file button OPENS the file directly (fileTap).
        if(e.target.closest(".fname,.thwrap,.ftime")){
          const f = files.find(x => x.name === row.dataset.frow);
          if(f) previewFile(f.name, f.size);
        }
      });
    });
    checkPendingAi();
  } catch(e){
    // v2.8.37 (7): a failed reload must NEVER wipe the file
    // list -- same stuck-wipe as the texts (see loadNotes):
    // lastFilesSig is not reset here, so a wipe followed by a
    // same-signature fetch left an error line on screen
    // forever. Keep the last good list; the next poll retries.
  }
}

// scan pending files for transcribable text; ✨ pops in as soon as text is found
// v2.8.40: a resolved file patches only its own row (paintAiCell)
// -- the old code reset lastFilesSig and re-rendered the WHOLE
// list per file, so every scan resolution re-created every video
// poster and image thumb. Only this address's keys are attempted;
// another address's keys wait untouched until that address is
// current again. Files added mid-round are picked up by the pump
// at the end, not by a re-render.
let _checkingAi = false;
const _aiAttempts = {};
async function checkPendingAi(){
  if(_checkingAi || !pendingHere()) return;
  _checkingAi = true;
  for(const key of [...pendingAi]){
    // re-read the prefix per file: an address switch mid-round
    // must not let this round scan the old address's files
    // against the new folder.
    const prefix = aiPrefix();
    if(key.indexOf(prefix) !== 0) continue;  // another address's scan waits
    const name = key.slice(prefix.length);
    _aiAttempts[key] = (_aiAttempts[key] || 0) + 1;
    if(_aiAttempts[key] > 12){ pendingAi.delete(key); paintAiCell(name, false); continue; }  // give up, drop the spinner
    try{
      const r = await getJSON("/api/aicheck?name=" + encodeURIComponent(name));
      // the user may have switched addresses while this check
      // was in flight: a verdict for the old folder must never
      // patch this folder's row (same file name, different file).
      // Leave the key pending -- it resumes when that address
      // is current again.
      if(key.indexOf(aiPrefix()) !== 0) continue;
      if(r.ok && r.has_text){
        pendingAi.delete(key); aiReady.add(key);
        paintAiCell(name, true);
      }else if(r.ok){
        pendingAi.delete(key);  // no text - drop the spinner
        paintAiCell(name, false);
      }
      // !r.ok: keep pending, retry next round
    }catch(e){ /* keep pending, retry next round */ }
  }
  _checkingAi = false;
  if(pendingHere()) setTimeout(checkPendingAi, 5000);
}

const ACCENTS = [
  ["#22d3ee","#818cf8"], ["#a78bfa","#f472b6"], ["#f472b6","#fb7185"], ["#fbbf24","#fb923c"],
  ["#34d399","#22d3ee"], ["#60a5fa","#a78bfa"], ["#fb7185","#f472b6"], ["#a3e635","#34d399"]
];
function accentFor(id){ let h = 0; const s = String(id);
  for(let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return ACCENTS[h % ACCENTS.length]; }

function strHash(s){ let h = 0; s = String(s);
  for(let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return h; }
let lastNotesSig = null;
async function loadNotes(){
  if(document.querySelector(".editbox,.renamein")) return;  // don't clobber an open editor
  const snbox = $("#snips");
  try {
    const r = await fetch("/api/notes"); const notes = await r.json();
    const sig = notes.map(n => n.id + "|" + (n.title || "") + "|" + (n.starred ? 1 : 0) + "|" + (n.created || 0) + "|" + strHash(n.text || "")).join(";");
    if(sig === lastNotesSig) return;  // unchanged: skip re-render so text selection never drops
    lastNotesSig = sig;
    $("#snipcount").textContent = notes.length || "";
    $("#mnotecount").textContent = notes.length || "";
    const danb = $("#delallnotesbtn"); if(danb) danb.style.display = notes.length ? "" : "none";
    const sfb = $("#starfilter"); if(sfb) sfb.style.display = notes.length ? "" : "none";
    for(const k in NOTES) delete NOTES[k];
    for(const k in NOTEOBJ) delete NOTEOBJ[k];
    notes.forEach(n => { NOTEOBJ[n.id] = n; });
    if(!notes.length){ snbox.innerHTML = '<p class="empty">Nothing shared yet &mdash; send text from the Upload column or your phone.</p>'; paintDeleteState(); return; }
    const shown = starredOnly ? notes.filter(n => n.starred) : notes;
    if(!shown.length){ snbox.innerHTML = '<p class="empty">No starred texts yet &mdash; tap the star on any text to pin it here.</p>'; paintDeleteState(); return; }
    snbox.innerHTML = shown.map(n => {
      NOTES[n.id] = n.text || "";
      const t = n.text || "(empty)";
      const long = t.split("\\n").length > 5 || t.length > 280;
      const ac = accentFor(n.id);
      const isEx = EXPANDED.has(n.id);
      return `<div class="snipcard${isEx ? " expanded" : ""}" data-nid="${esc(n.id)}" style="--nac:${ac[0]};--nac2:${ac[1]}">` +
      `<div class="sniphead"><span class="wic">${SVG.note}</span><span class="who" title="Click to rename">${esc(n.title || n.label || "Shared Text")}</span>` +
      `<span class="ndate">&middot; ${esc(noteTime(n.created))}</span>` +
      `<button class="starbtn${n.starred ? " starred" : ""}" data-star="${esc(n.id)}" title="${n.starred ? "Starred" : "Star this text"}">${SVG.star}</button></div>` +
      `<div class="sniptext">${linkify(esc(t))}</div>` +
      (long ? `<button class="snipmore">${isEx ? "Show less" : "Show more"}</button>` : "") +
      `<div class="nact">` +
      `<button data-edit="${esc(n.id)}" style="--c1:#fbbf24;--c2:#f59e0b" title="Edit">${SVG.edit}</button>` +
      `<button data-copy="${esc(n.id)}" style="--c1:#22d3ee;--c2:#0ea5e9" title="Copy">${SVG.copy}</button>` +
      `<button data-dl="${esc(n.id)}" style="--c1:#277ff0;--c2:#0ea5e9" title="${NOTEDL[n.id] ? "Open" : "Download"}">${NOTEDL[n.id] ? SVG.open : SVG.dl}</button>` +
      `<button data-share="${esc(n.id)}" style="--c1:#a78bfa;--c2:#8b5cf6" title="Share">${SVG.share}</button>` +
      `<button data-del="${esc(n.id)}" style="--c1:#ef4444;--c2:#ef4444" title="Delete">${SVG.del}</button></div></div>`;
    }).join("");
    snbox.querySelectorAll(".snipcard").forEach(card => {
      const nid = card.dataset.nid;
      const more = card.querySelector(".snipmore");
      if(more) more.onclick = () => {
        const ex = card.classList.toggle("expanded");
        if(ex) EXPANDED.add(nid); else EXPANDED.delete(nid);
        more.textContent = ex ? "Show less" : "Show more";
      };
      card.querySelector("[data-edit]").onclick = e => editNote(e.currentTarget.dataset.edit, card);
      card.querySelector("[data-copy]").onclick = e => copyNote(e.currentTarget.dataset.copy);
      card.querySelector("[data-dl]").onclick = e => noteDlTap(e.currentTarget);
      card.querySelector("[data-share]").onclick = e => shareNote(e.currentTarget.dataset.share);
      card.querySelector("[data-del]").onclick = e => delNote(e.currentTarget.dataset.del);
      const whoEl = card.querySelector(".who"); if(whoEl) whoEl.onclick = () => startRename(card, NOTEOBJ[nid]);
      const stb = card.querySelector("[data-star]"); if(stb) stb.onclick = () => toggleStar(nid, stb);
    });
    // v2.7.91: freshly rendered per-note delete buttons must get
    // the grey class immediately, not only on the next full auth
    // check -- a host toggle while notes re-render must paint now.
    paintDeleteState();
  } catch(e){
    // v2.8.37 (7): a failed reload must NEVER wipe the texts.
    // The old code replaced #snips with an error line -- and
    // lastNotesSig was NOT reset, so if the next successful
    // fetch had the same signature (e.g. both addresses have
    // no notes, or the same notes), loadNotes returned early
    // and the wiped message STUCK: texts that had simply
    // failed once mid-switch never came back. Keep the last
    // good list on screen; the next poll retries.
  }
}

const delallbtn = $("#delallbtn");
if(delallbtn) delallbtn.onclick = () => {
  // v2.7.89: guest delete OFF -- the trash icon stays visible but
  // greyed out, and tapping it toasts the exact not-authorized
  // message instead of opening delete-selection mode.
  if(AUTH && !AUTH.host && AUTH.authed && !canDeleteUI()){ toast("No permission to delete files from this device"); return; }
  if(selMode) selExit(); else selOpen();
};
const delcancel = $("#delcancel");
if(delcancel) delcancel.onclick = () => selExit();
const delselall = $("#delselall");
if(delselall) delselall.onclick = () => {
  const rows = [...document.querySelectorAll("#files .frow")];
  const names = rows.map(r => r.dataset.frow);
  if(!names.length) return;
  if(names.every(n => picked.has(n))) names.forEach(n => picked.delete(n));
  else names.forEach(n => picked.add(n));
  rows.forEach(r => r.classList.toggle("picked", picked.has(r.dataset.frow)));
  updateDelBar();
};
const delconfirm = $("#delconfirm");
if(delconfirm) delconfirm.onclick = async () => {
  // v2.7.89 backstop on the client too: a guest whose toggle was
  // turned OFF while selection mode was already open gets the
  // exact not-authorized toast here, not a delete attempt.
  if(AUTH && !AUTH.host && AUTH.authed && !canDeleteUI()){ toast("No permission to delete files from this device"); return; }
  const names = [...picked];
  if(!names.length) return;
  if(!confirm("Delete " + names.length + " file(s) from this PC? This can\'t be undone.")) return;
  delconfirm.disabled = true;
  document.querySelectorAll("#files .frow.picked").forEach(r => collapseEl(r));
  await new Promise(r => setTimeout(r, 300));
  let done = 0;
  for(const name of names){
    try {
      const r = await fetch("/api/delete", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({name})});
      if(r.ok) done++;
    } catch(e){}
  }
  selExit();
  lastFilesSig = null; loadFiles();
  toast(done === names.length ? "Deleted " + done + " file(s)" : "Deleted " + done + " of " + names.length + " file(s)");
};

const starfilter = $("#starfilter");
if(starfilter) starfilter.onclick = () => {
  starredOnly = !starredOnly;
  starfilter.classList.toggle("on", starredOnly);
  // v2.8.39 (6): the toggle state is also exposed to
  // assistive tech (and to tests) via aria-pressed.
  starfilter.setAttribute("aria-pressed", String(starredOnly));
  // v2.8.40 (2): the APK toggle reads "✓ Starred" while ON --
  // the label swaps with the state (the star icon stays).
  const _tl = [...starfilter.childNodes].find(n => n.nodeType === 3);
  if(_tl) _tl.textContent = starredOnly ? " ✓ Starred" : " Starred";
  const sb = $("#snips");
  if(sb){ sb.classList.remove("flip"); void sb.offsetWidth; sb.classList.add("flip");
    setTimeout(() => sb.classList.remove("flip"), 500); }
  lastNotesSig = null; loadNotes();
};

const delallnotesbtn = $("#delallnotesbtn");
if(delallnotesbtn) delallnotesbtn.onclick = async () => {
  if(AUTH && !AUTH.host && AUTH.authed && !canDeleteNotesUI()){ toast("No permission to delete notes from this device"); return; }
  const n = parseInt(($("#snipcount").textContent || "0"), 10) || 0;
  if(!n) return;
  if(!confirm("Delete All " + n + " Shared Text(s)? This Can't Be Undone.")) return;
  try {
    const r = await fetch("/api/notes/delete_all", {method:"POST"});
    if(r.status === 403){ toast("No permission to delete notes from this device"); return; }
    loadNotes(); toast("Deleted " + n + " Shared Text(s)");
  } catch(e){ toast("Couldn't Delete Shared Texts"); }
};

/* ---- Shared Files AI popup: transcribe / translate ---- */
let _aipop = null;
function closeAiPopup(){ if(_aipop){ _aipop.remove(); _aipop = null; } }
document.addEventListener("click", closeAiPopup);
async function getJSON(url){ const r = await fetch(url); return r.json(); }

async function openAiPopup(name, btn){
  closeAiPopup();
  // render instantly with Transcribe; Translate is appended in the
  // background only when the text is foreign - popup never waits
  const pop = document.createElement("div");
  pop.className = "aipop";
  pop.innerHTML = `<button data-act="transcribe"><span class="em">${SVG.transcribe}</span>Transcribe</button>`;
  document.body.appendChild(pop);
  const r = btn.getBoundingClientRect();
  pop.style.top = Math.min(window.innerHeight - 170, r.bottom + 6) + "px";
  pop.style.left = Math.max(8, r.left - 150) + "px";
  _aipop = pop;
  pop.addEventListener("click", e => e.stopPropagation());
  pop.querySelectorAll("[data-act]").forEach(b =>
    b.onclick = () => { closeAiPopup(); aiRun(name, b.dataset.act); });
  getJSON("/api/aifileinfo?name=" + encodeURIComponent(name)).then(info => {
    if(_aipop !== pop) return;  // user already closed it
    if(info && info.lang && info.lang !== "en"){
      const tb = document.createElement("button");
      tb.dataset.act = "translate";
      tb.innerHTML = `<span class="em">${SVG.translate}</span>Translate`;
      tb.onclick = () => { closeAiPopup(); aiRun(name, "translate"); };
      pop.appendChild(tb);
    }
  }).catch(()=>{});
}

// Friendly one-liners for the translation API's machine-readable messages.
function _aiErrMsg(m){
  return {no_pair: "Couldn't get the translation pack - check your internet and try again.",
    no_space: "Not enough free space on the PC for the translation pack (about 110 MB per language). Free some space and try again.",
    rate_limited: "Too many translations at once - wait a minute and try again."}[m] || "Translation failed.";
}

// Long-file translation: POST /api/aitranslate/stream returns NDJSON, one
// JSON object per translated chunk, flushed as each chunk finishes. Each
// chunk is painted into the modal on arrival instead of one blocking call.
// Resolves to a /api/aitranslate-shaped {ok, text, src, message}; throws on
// failure. Throws a `closed`-flagged error when the user closes the modal
// mid-stream so the caller can stay silent.
async function aiTranslateStream(text){
  const fail = m => { const e = new Error(_aiErrMsg(m)); e.isAiErr = true; throw e; };
  const resp = await fetch("/api/aitranslate/stream", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({text})});
  const ctype = resp.headers.get("content-type") || "";
  if(!resp.ok || ctype.indexOf("ndjson") < 0){
    let r = null; try{ r = await resp.json(); }catch(e){}
    fail(r && r.message);
  }
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = "", chunks = [], src = "", total = 0, final = null;
  const paint = () => {
    const ab = document.querySelector("#_aimodal .abody");
    if(!ab) return false;
    const n = Math.min(chunks.filter(Boolean).length + 1, total || 1);
    ab.innerHTML = '<div style="font-size:12.5px;color:var(--muted);margin-bottom:8px">' +
      esc("Translating chunk " + n + " of " + (total || "?") + "…") + "</div>" +
      '<div style="white-space:pre-wrap;word-break:break-word">' +
      esc(chunks.filter(Boolean).join(" ")) + "</div>";
    return true;
  };
  try{
    for(;;){
      let rd;
      try{ rd = await reader.read(); }catch(e){ fail(); }
      if(rd.done) break;
      buf += dec.decode(rd.value, {stream: true});
      let nl;
      while((nl = buf.indexOf("\\n")) >= 0){
        const line = buf.slice(0, nl).trim(); buf = buf.slice(nl + 1);
        if(!line) continue;
        let m = null; try{ m = JSON.parse(line); }catch(e){}
        if(!m) continue;
        if(m.ok === false) fail(m.message);
        if(m.done){ final = m; break; }
        chunks[m.index] = m.text; src = m.src || src; total = m.total || total;
        if(!paint()){
          try{ reader.cancel(); }catch(e){}
          const c = new Error("closed"); c.closed = true; throw c;
        }
      }
      if(final) break;
    }
  }catch(e){ if(e && (e.isAiErr || e.closed)) throw e; fail(); }
  if(!final) fail();
  return final;
}

async function aiRun(name, act){
  const titles = {transcribe: "Transcription", translate: "Translation"};
  showAiModal(titles[act] || "AI", name, AI_LOADING, true);
  try{
    let text = "";
    if(act === "transcribe"){
      const r = await getJSON("/api/aifiletext?name=" + encodeURIComponent(name));
      if(!r.ok) throw new Error(r.message === "no_text" ? "No readable text found in that file." : "Couldn't read that file.");
      text = r.text;
    }else{
      const t = await getJSON("/api/aifiletext?name=" + encodeURIComponent(name));
      if(!t.ok || !t.text) throw new Error("No readable text found in that file.");
      // first use downloads a ~110 MB translation pack - poll for real
      // progress so the modal shows bytes instead of a frozen loader
      const _mb = b => (b / 1048576).toFixed(0) + " MB";
      const _dlpoll = setInterval(async () => {
        try{
          const p = await getJSON("/api/aidl_progress");
          const ks = p && p.downloads ? Object.keys(p.downloads) : [];
          if(!ks.length) return;
          const d = p.downloads[ks[0]];
          const ab = document.querySelector("#_aimodal .abody");
          if(!ab) return;
          const pct = d.total ? Math.round(d.done / d.total * 100) : 0;
          ab.innerHTML = '<div style="padding:20px 6px;text-align:center">' +
            '<div style="font-size:15px;margin-bottom:12px">Downloading translation pack<br><span style="color:var(--muted);font-size:13px">' + esc(d.file || '') + ' &mdash; one-time download, about 110 MB per language</span></div>' +
            '<div style="height:10px;background:var(--card2);border-radius:99px;overflow:hidden">' +
            '<div style="height:100%;width:' + pct + '%;background:linear-gradient(90deg,var(--acc),var(--acc2));border-radius:99px;transition:width .4s"></div></div>' +
            '<div style="margin-top:10px;font-size:13px;color:var(--muted)">' + (d.total ? _mb(d.done) + ' / ' + _mb(d.total) + ' (' + pct + '%)' : _mb(d.done) + ' downloaded&hellip;') + '</div></div>';
        }catch(e){}
      }, 500);
      let r;
      try{
        if(t.text.length > 2000){
          // long file: stream translated chunks into the modal as they
          // arrive instead of one blocking call
          r = await aiTranslateStream(t.text);
        }else{
          const resp = await fetch("/api/aitranslate", {method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({text: t.text})});
          r = await resp.json();
        }
      }finally{ clearInterval(_dlpoll); }
      if(!r.ok) throw new Error(_aiErrMsg(r.message));
      if(r.message === "already_english") throw new Error("That's already English.");
      // mul = multilingual fallback pair, auto/empty = detection failed -
      // show a friendly [auto → en] instead of a cryptic [mul → en] or nothing
      const _srcLabel = (!r.src || r.src === "mul" || r.src === "auto") ? "auto" : r.src;
      text = (r.src && r.src !== "en" ? "[" + _srcLabel + " → en] " : "") + r.text;
    }
    showAiModal(titles[act], name, text);
  }catch(e){ if(e && e.closed) return; showAiModal(titles[act] || "AI", name, "⚠️ " + (e.message || e)); }
}

const AI_LOADING = `<span class="ailoading"><i></i><i></i><i></i></span>`;
function showAiModal(title, name, body, isHtml){
  closeAiModal();
  const w = document.createElement("div");
  w.className = "aimodalwrap"; w.id = "_aimodal";
  w.innerHTML = `<div class="aimodal"><header><span>${esc(title)} — ${esc(name)}</span><span class="ahbtns"><button class="aclose" aria-label="Close" title="Close"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button><button class="acopy">Copy</button></span></header><div class="abody"></div></div>`;
  const ab = w.querySelector(".abody");
  if(isHtml) ab.innerHTML = body; else ab.textContent = body;
  w.querySelector("header button.acopy").onclick = () => {
    navigator.clipboard.writeText(ab.textContent).then(() => toast("Copied"), () => toast("Copy failed"));
  };
  w.querySelector("header button.aclose").onclick = closeAiModal;
  w.addEventListener("click", e => { if(e.target === w) closeAiModal(); });
  document.body.appendChild(w);
}
function closeAiModal(){ const m = $("#_aimodal"); if(m) m.remove(); }

// Translation-pack maintenance: list cached packs and offer to clear them.

const mdlg = $("#mdlg"), mnote = $("#mnote");
// v2.8.34 (3): pop-out on close -- see closeQrPop above:
// add .closing, drop .open after the 160ms pop-out.
// A re-open cancels the pending hide.
let _mdCloseT = null;
function closeMdlg(){
  if(!mdlg || !mdlg.classList.contains("open")) return;
  clearTimeout(_mdCloseT);
  mdlg.classList.add("closing");
  _mdCloseT = setTimeout(() => { mdlg.classList.remove("open", "closing"); }, 160);
}
$("#maddnote").onclick = () => { if(AUTH && !AUTH.host && AUTH.authed && !canAddNotesUI()){ toast("No permission to add notes on this device"); return; } mnote.value=""; clearTimeout(_mdCloseT); mdlg.classList.remove("closing"); mdlg.classList.add("open"); setTimeout(() => mnote.focus(), 60); };
$("#mcancel").onclick = () => closeMdlg();
mdlg.addEventListener("click", e => { if(e.target === mdlg) closeMdlg(); });
$("#msave").onclick = async () => {
  const text = mnote.value.trim();
  if(!text){ toast("Type something first"); return; }
  if(AUTH && !AUTH.host && AUTH.authed && !canAddNotesUI()){ toast("No permission to add notes on this device"); return; }
  try {
    const r = await fetch("/api/snippet", {method:"POST",
      headers:{"Content-Type":"application/json"}, body:JSON.stringify({text})});
    const j = await r.json();
    if(j.ok){ mnote.value=""; closeMdlg(); slideInBoard(); toast("\\u2705 Shared Text Added"); loadNotes(); }
    else toast((r.status === 403 && j.error) ? j.error : "Couldn't save that note");
  } catch(e){ toast("Couldn't save that note"); }
};
const mtabs = document.querySelectorAll(".mtab");
const _TABORDER = ["send", "notes", "files", "ask"];
let _lastTab = null;
function setTab(name){
  // v2.8.24 (7): slide direction follows tab order, so moving
  // right slides in from the right and moving left from the
  // left (--tabdx is read by the tabslidein keyframes).
  const _prevTab = _lastTab || "send";
  document.body.style.setProperty("--tabdx", (_TABORDER.indexOf(name) >= _TABORDER.indexOf(_prevTab) ? 24 : -24) + "px");
  _lastTab = name;
  document.body.dataset.mtab = name;
  const qpp = document.getElementById("qrpop");
  if(qpp) closeQrPop();
  document.querySelectorAll(".board .col").forEach(c =>
    c.classList.toggle("active", c.dataset.col === name));
  mtabs.forEach(t => t.classList.toggle("sel", t.dataset.tab === name));
  try { localStorage.setItem("dropit_tab", name); } catch(e){}
  if(window._tabShown) window._tabShown(name);
}
mtabs.forEach(t => t.onclick = () => setTab(t.dataset.tab));
// v2.8.24 (8): clicking a Save button slides the board in --
// the view that follows the save arrives with the same fast
// slide as the tab changes, instead of appearing instantly.
// Called from the three dialog Save success paths below.
function slideInBoard(){
  const b = document.querySelector(".board"); if(!b) return;
  b.classList.remove("boardslide"); void b.offsetWidth; b.classList.add("boardslide");
}
window.__slideInBoard = slideInBoard;
try { setTab(localStorage.getItem("dropit_tab") || "send"); } catch(e){ setTab("send"); }
// v2.8.18 (2): the Upload tab scrolls ONLY in the two allowed
// cases -- (a) a retry button for failed files is present, or
// (b) the Send Text box is focused (keyboard open). Otherwise
// the Send column clips (see the CSS above) and the tab fits.
// NOTE: failed uploads today only toast ("Upload failed: ...");
// there is no retry button in the app yet, so case (a) is
// implemented for any [data-retry] / .upretry button if one is
// ever added -- today it simply never fires.
function fitSendTab(){
  const retry = document.querySelector("#muploads [data-retry], #uploads [data-retry], #muploads .upretry, #uploads .upretry");
  const kb = document.activeElement === document.querySelector("#msendtext");
  // v2.8.20 (1): a smaller / shorter phone can be TALLER than
  // its column -- the 2.8.18 no-scroll fit only holds on taller
  // screens -- so the Send column must scroll when its content
  // overflows. Otherwise the Share Text card is clipped by the
  // column and the Send Text button ends up under the pill tabs
  // (360x640: the stack is 550px, the column only 366px).
  const colbody = document.querySelector('.col[data-col="send"] .colbody');
  const overflows = !!(colbody && colbody.scrollHeight > colbody.clientHeight + 1);
  document.body.classList.toggle("send-may-scroll", !!(retry || kb || overflows));
}
// v2.8.20 (7): the Share Text box scrolls ONCE when the
// keyboard opens -- the box is scrolled into view a single
// time per focus session (after the keyboard has had a beat to
// open), and typing after that scrolls only INSIDE the box
// (its own scroller + overscroll-behavior:contain in CSS),
// never the page again, so earlier text stays reachable.
// Back (Android back button / gesture) while the box is
// focused closes the keyboard instead of leaving the screen:
// focus pushes ONE history entry, and the popstate handler
// below blurs the box when that entry is consumed -- the
// entry is pushed once per focus session, never stacked, and
// a blur without a back-press removes it again. Same idiom
// as the overlay back handling (ovOpened / ovClosed) above.
// The original focus/blur -> fitSendTab wiring is kept
// verbatim (round34 pins it); the keyboard behaviour below
// is additional listeners, not a replacement.
const _mst = document.querySelector("#msendtext");
if(_mst){ _mst.addEventListener("focus", fitSendTab); _mst.addEventListener("blur", fitSendTab); }
let _mstKbPushed = false;
let _mstKbScrolled = false;
let _mstKbSkipPop = false;
if(_mst){
  _mst.addEventListener("focus", () => {
    _mstKbScrolled = false;
    if(!_mstKbPushed){
      try { history.pushState({dropKb:1}, ""); _mstKbPushed = true; } catch(e){}
    }
    setTimeout(() => {
      if(document.activeElement === _mst && !_mstKbScrolled){
        _mstKbScrolled = true;
        try { _mst.scrollIntoView({block:"nearest"}); } catch(e){}
      }
    }, 350);
  });
  _mst.addEventListener("blur", () => {
    _mstKbScrolled = false;
    if(_mstKbPushed){
      _mstKbPushed = false;
      _mstKbSkipPop = true;
      try { history.back(); } catch(e){ _mstKbSkipPop = false; }
    }
  });
  window.addEventListener("popstate", () => {
    if(_mstKbSkipPop){ _mstKbSkipPop = false; return; }
    if(_mstKbPushed && document.activeElement === _mst){
      // User pressed Back while typing: the pushed entry is
      // consumed, so just close the keyboard (blur) and STAY
      // on the screen -- a second Back then leaves normally.
      _mstKbPushed = false;
      _mstKbScrolled = false;
      try { _mst.blur(); } catch(e){}
    }
  });
  window.addEventListener("resize", fitSendTab);
  if(window.visualViewport){
    try { window.visualViewport.addEventListener("resize", fitSendTab); } catch(e){}
  }
}
// v2.8.20 (1): run the overflow check once at boot, not only
// on the 5s poll -- a short phone must get its Send-column
// scroll from the first paint, not five seconds in.
fitSendTab();

/* v2.7.99 Search sounds: two distinct gentle WebAudio chimes,
   low volume, silent fallback when audio is unavailable.
   Results: a soft ascending pair (E5 -> A5). No results: a
   different soft descending pair (D5 -> G4). Never a file,
   never a download. */
// v2.8.17 (j): a short pop when a file or note is successfully
// sent -- one soft sine blip (950 Hz falling to 420 Hz, ~0.14s),
// low volume, same WebAudio pattern as the Find sounds, with a
// silent fallback when audio is unavailable. Never a file,
// never a download.
function playPopSound(){
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if(!AC) return;
    const ctx = new AC();
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = "sine"; o.connect(g); g.connect(ctx.destination);
    const t0 = ctx.currentTime;
    o.frequency.setValueAtTime(950, t0);
    o.frequency.exponentialRampToValueAtTime(420, t0 + 0.1);
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(0.09, t0 + 0.015);
    g.gain.exponentialRampToValueAtTime(0.001, t0 + 0.14);
    o.start(t0); o.stop(t0 + 0.16);
    setTimeout(() => { try { ctx.close(); } catch(e){} }, 400);
  } catch(e){}
}
function playFindResultsSound(){
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if(!AC) return;
    const ctx = new AC();
    [660, 880].forEach((f, i) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = "sine"; o.connect(g); g.connect(ctx.destination);
      const t0 = ctx.currentTime + i * 0.14;
      o.frequency.setValueAtTime(f, t0);
      g.gain.setValueAtTime(0.0001, t0);
      g.gain.exponentialRampToValueAtTime(0.07, t0 + 0.04);
      g.gain.exponentialRampToValueAtTime(0.001, t0 + 0.32);
      o.start(t0); o.stop(t0 + 0.34);
    });
    setTimeout(() => { try { ctx.close(); } catch(e){} }, 900);
  } catch(e){}
}
function playFindEmptySound(){
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if(!AC) return;
    const ctx = new AC();
    [587, 392].forEach((f, i) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = "sine"; o.connect(g); g.connect(ctx.destination);
      const t0 = ctx.currentTime + i * 0.16;
      o.frequency.setValueAtTime(f, t0);
      g.gain.setValueAtTime(0.0001, t0);
      g.gain.exponentialRampToValueAtTime(0.06, t0 + 0.04);
      g.gain.exponentialRampToValueAtTime(0.001, t0 + 0.36);
      o.start(t0); o.stop(t0 + 0.38);
    });
    setTimeout(() => { try { ctx.close(); } catch(e){} }, 1000);
  } catch(e){}
}
/* Ask Drop — retrieval chat veneer over /api/aisearch. Fixed templates only. */
function AskChat(listId, inputId, sendId){
  const list = document.getElementById(listId),
        input = document.getElementById(inputId),
        sendBtn = document.getElementById(sendId);
  if(!list || !input || !sendBtn) return { greet(){} };
  let greeted = false, busy = false;
  const scroll = () => { list.scrollTop = list.scrollHeight; };
  function addMsg(html, who){
    const d = document.createElement("div");
    d.className = "amsg " + who;
    d.innerHTML = html;
    list.appendChild(d); scroll();
    return d;
  }
  const bot = html => addMsg(html, "bot");
  function greet(){
    if(greeted) return; greeted = true;
    bot("Hi, what can I help you with today?");
    checkComponents();
  }
  async function checkComponents(){
    try {
      const s = await getJSON("/api/aistatus");
      if(!s || s.ok === false) return;
      const missing = s.missing || [];
      if(missing.length){
        bot("Heads up: some AI features are off on your PC (missing: " + missing.map(esc).join(", ") + ").<br>Image reading, photo search and translation need:<br><code>pip install rapidocr-onnxruntime Pillow onnxruntime tokenizers</code><br>Run that on your PC, restart Drop, and everything lights up.");
      }
    } catch(e){}
  }
  async function getJSON(url){
    const r = await fetch(url);
    return r.json();
  }
  function renderResults(r){
    const n = (r.results || []).length;
    if(!n){
      // v2.8.41 (1): on a cold start the index is still
      // building in the background -- say so instead of
      // "couldn't find anything", which reads as a miss.
      if(r.indexing){
        bot("Nothing matches yet &mdash; the PC is still indexing new files. Try again in a moment.");
      } else {
        bot("I couldn't find anything matching that. Try different words &mdash; I match meaning, not just filenames.");
      }
      playFindEmptySound();
      return;
    }
    playFindResultsSound();
    bot((n === 1 ? "Here is the file you requested." : "Here's what I found (" + n + "):") + (r.indexing ? " <span style='opacity:.65'>Still indexing &mdash; more files may match once it finishes.</span>" : ""));
    r.results.forEach(f => {
      const d = document.createElement("div");
      d.className = "ares";
      const isImg = !!f.image;
      d.innerHTML = (isImg
        ? '<img class="athumb" loading="lazy" src="/thumb/' + encodeURIComponent(f.name) + '" alt="" onerror="this.remove()">'
        : '<span class="afic">' + iconFor(f.name) + '</span>') +
        '<span class="afname">' + esc(f.name) + '</span>' +
        '<span class="afsize">' + fmt(f.size) + '</span>' +
        // v2.7.83: no more notepad icon on every picture. The AI
        // (✨) button appears only when the search index actually
        // detected text in the picture (f.has_text from /api/aisearch);
        // pictures without detected text get no AI button at all.
        (isImg && f.has_text ? '<button class="abtn abtn2" type="button" title="AI: read text in image">✨</button>' : '') +
        '<button class="abtn" type="button">Open</button>';
      list.appendChild(d);
      d.querySelectorAll(".abtn").forEach(b => {
        if(b.classList.contains("abtn2")) b.onclick = () => readText(f.name, b);
        else b.onclick = () => openFile(f.name);
      });
    });
    scroll();
  }
  async function readText(name, btn){
    btn.disabled = true; btn.textContent = "\u2026";
    try {
      const r = await getJSON("/api/aiocr?name=" + encodeURIComponent(name));
      if(r.ok && r.text){
        const d = bot("<b>Text in " + esc(name) + ":</b><br>" + esc(r.text).replace(/\\n/g, "<br>"));
        const cb = document.createElement("button");
        cb.className = "abtn"; cb.type = "button"; cb.textContent = "📋 Copy";
        cb.style.marginTop = "8px";
        cb.onclick = () => navigator.clipboard.writeText(r.text).then(() => toast("Copied"), () => toast("Copy failed"));
        d.appendChild(document.createElement("br")); d.appendChild(cb);
        // translate button only for foreign text
        if(r.lang && r.lang !== "en"){
          const tb = document.createElement("button");
          tb.className = "abtn"; tb.type = "button"; tb.textContent = "🌐 English";
          tb.style.marginTop = "8px"; tb.style.marginLeft = "8px";
          tb.onclick = () => translateText(r.text, tb);
          d.appendChild(tb);
        }
        scroll();
      } else if(r.message === "blank"){
        bot("No readable text found in that image.");
      } else if(r.message === "needs_setup"){
        bot("Text reading needs one more package on your PC:<br><code>pip install rapidocr-onnxruntime Pillow</code>");
      } else if(r.message === "error"){
        bot("Reader hit an error: " + esc(r.note || "unknown") + "<br>Send me that text and I'll fix it.");
      } else {
        bot("Couldn't read that image.");
      }
    } catch(e){ bot("Couldn't read that image."); }
    btn.disabled = false; btn.innerHTML = "&#x1F4DD;";
  }
  async function translateText(text, btn){
    btn.disabled = true; btn.textContent = "\u2026";
    try {
      const resp = await fetch("/api/aitranslate", {method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({text: text})});
      const r = await resp.json();
      if(r.ok && r.message === "already_english"){
        bot("That's already English.");
      } else if(r.ok){
        const d = bot("<b>English:</b><br>" + esc(r.text).replace(/\\n/g, "<br>"));
        const cb = document.createElement("button");
        cb.className = "abtn"; cb.type = "button"; cb.textContent = "📋 Copy";
        cb.style.marginTop = "8px";
        cb.onclick = () => navigator.clipboard.writeText(r.text).then(() => toast("Copied"), () => toast("Copy failed"));
        d.appendChild(document.createElement("br")); d.appendChild(cb); scroll();
      } else if(r.message === "no_pair"){
        bot("No offline translation pack for that language yet &mdash; it downloads automatically (about 110 MB) the first time you translate it.");
      } else if(r.message === "no_space"){
        bot("Not enough free space on the PC for the translation pack (about 110 MB per language). Free some space and try again.");
      } else {
        bot("Couldn't translate that right now.");
      }
    } catch(e){ bot("Couldn't translate that right now."); }
    btn.disabled = false; btn.textContent = "🌐 English";
  }
  async function doSearch(q){
    // v2.8.1: Search must ALWAYS terminate. The old code awaited
    // /api/aisearch with no timeout at all, so a stalled backend
    // (index lock held, first model load, slow OCR) left the
    // typing indicator spinning forever and the Send button
    // disabled forever. The server now answers "timeout" within
    // 75s; this 90s abort is the backstop if even that stalls.
    // The typing indicator and busy flag are cleared on EVERY
    // path below -- a search never leaves the UI spinning.
    let r;
    try {
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), 90000);
      try {
        const resp = await fetch("/api/aisearch?q=" + encodeURIComponent(q), {signal: ctl.signal});
        r = await resp.json();
      } finally { clearTimeout(timer); }
    }
    catch(e){ r = { message: (e && e.name === "AbortError") ? "timeout" : "error" }; }
    const t = list.querySelector(".atyping");
    if(t) t.closest(".amsg").remove();
    if(!r || r.message === "error"){
      bot("Something went wrong on the PC side. Try again in a moment.");
    } else if(r.message === "timeout"){
      bot("Search took too long on the PC side -- the search stopped, nothing is still running. Try again in a moment, or try fewer words.");
      playFindEmptySound();
    } else if(r.message === "needs_setup"){
      bot("AI search needs a one-time setup on your PC (about 450 MB). Open a terminal there and run:<br><code>pip install onnxruntime tokenizers numpy pypdf python-docx rapidocr-onnxruntime Pillow langdetect</code><br>Then refresh this page and ask again.");
    } else if(r.message === "no_model"){
      bot("The search model folder is missing from the app folder. Re-download the app zip and try again.");
    } else {
      try { renderResults(r); }
      catch(e){ bot("Something went wrong showing those results. Try again in a moment."); }
    }
    busy = false; sendBtn.disabled = false;
  }
  async function send(){
    const q = input.value.trim();
    if(!q || busy) return;
    input.value = "";
    addMsg(esc(q), "user");
    busy = true; sendBtn.disabled = true;
    addMsg('<span class="atyping"><i></i><i></i><i></i></span>', "bot");
    doSearch(q);
  }
  sendBtn.onclick = send;
  input.addEventListener("keydown", e => { if(e.key === "Enter") send(); });
  return { greet };
}
const askMobile = AskChat("asklist", "asktext", "asksend");
const askDesk = AskChat("asklist2", "asktext2", "asksend2");
window._tabShown = n => { if(n === "ask") askMobile.greet(); };
document.getElementById("askbtn").onclick = () => {
  document.getElementById("askpop").classList.add("open");
  askDesk.greet();
};
document.getElementById("askclose").onclick = () =>
  document.getElementById("askpop").classList.remove("open");
async function loadStatus(){
  // v2.8.33 (1): no session, no status call -- /api/status
  // 401s for an unauthed guest, so the 5s interval's call
  // only spammed a 401 every tick (and, before the wrapper
  // guard above, bounced the login page). The pill only has
  // meaning once authed; the host window and a connected
  // guest are authed by the time the interval first fires.
  if(!(AUTH && AUTH.authed)) return;
  try {
    const r = await fetch("/api/status"); const j = await r.json();
    const n = j.devices || 0;
    const t = $("#statustext"), d = $("#statusdot");
    if(!t || !d) return;
    if(n <= 0){ t.textContent = "No devices connected"; d.classList.add("idle"); }
    else {
      t.textContent = n + (n === 1 ? " Device Connected" : " Devices Connected");
      d.classList.remove("idle");
    }
  } catch(e){}
}
// ---- v2.7.99 Devices dropdown (Send-card pill) ----
// Opens from the pill two ways: HOVERING the arrow (the whole
// pill wrapper's mouseenter -- the arrow sits inside the pill,
// so hovering it opens the window) and CLICKING the Devices
// Connected text (the pill click toggles). Same window both
// ways, animated by the .devdrop CSS transition. Host-only:
// a guest click never opens it and never sees its controls --
// it toasts the host-only message instead. Device rows show
// NAME and MODEL each (display name as-is, model from the
// session's UA hint / device name when it differs); each row
// has its own Disconnect, and Disconnect All sits at the
// BOTTOM, RED. Toasts are exact: "<device name> disconnected"
// for one device, "<N> device(s) disconnected" for all --
// never a generic preceding toast.
let _devdropOpen = false;
function closeDevDrop(){
  _devdropOpen = false;
  const dd = $("#devdrop"); if(dd) dd.classList.remove("open");
}
async function paintDevDrop(){
  const rows = $("#devdroprows"); if(!rows) return;
  try {
    const r = await _origFetch("/api/sessions"); const j = await r.json();
    if(!j.ok){ closeDevDrop(); return; }
    const sess = (() => { const _seen = new Set(); return (j.sessions || []).filter(x => { const k = (String(x.ip || "") + "|" + String(x.display_name || x.device_name || "")).toLowerCase(); if(_seen.has(k)) return false; _seen.add(k); return true; }); })();
    if(!sess.length){ rows.innerHTML = '<p class="devempty">No devices connected</p>'; return; }
    rows.innerHTML = sess.map(s => {
      const name = s.display_name || s.device_name || s.ip || "Device";
      let model = "";
      if(s.ua_hint && s.ua_hint !== name) model = s.ua_hint;
      else if(s.device_name && s.device_name !== name) model = s.device_name;
      return '<div class="devrow"><div class="devmeta"><span class="devname">' + esc(name) + (s.self ? " (this device)" : "") + '</span>' +
        (model ? '<span class="devmodel">' + esc(model) + '</span>' : "") +
        '</div><button class="devdisc" data-sess="' + esc(s.id) + '" data-name="' + esc(name) + '">Disconnect</button></div>';
    }).join("");
    rows.querySelectorAll("[data-sess]").forEach(b => { b.onclick = async (ev) => {
      ev.stopPropagation();
      // v2.8.1 optimistic removal: the row leaves the list
      // IMMEDIATELY on tap (and the pill count drops at once),
      // before the revoke round-trip returns -- no stale
      // few-second window. A failed revoke re-paints the list.
      const rowEl = b.closest(".devrow");
      const pillTxt = $("#statustext");
      if(rowEl) rowEl.remove();
      if(rows && !rows.querySelector(".devrow")) rows.innerHTML = '<p class="devempty">No devices connected</p>';
      if(pillTxt){
        const m = pillTxt.textContent.match(/^(\d+) Device/);
        const n = m ? Math.max(0, parseInt(m[1], 10) - 1) : 0;
        pillTxt.textContent = n <= 0 ? "No devices connected" : n + (n === 1 ? " Device Connected" : " Devices Connected");
        const dot = $("#statusdot"); if(dot && n <= 0) dot.classList.add("idle");
      }
      const jj = await postHostJ("/api/sessions/revoke", {id: b.dataset.sess});
      if(jj.ok){ toast(b.dataset.name + " disconnected"); paintDevDrop(); loadStatus(); }
      else { toast(jj.error || "Could not disconnect"); paintDevDrop(); loadStatus(); }
    }; });
  } catch(e){ closeDevDrop(); }
}
async function openDevDrop(quiet){
  if(!(AUTH && AUTH.host)){
    // Hovering as a guest stays silent (no toast spam); an
    // explicit click still explains why nothing opened.
    if(!quiet) toast("Only the host can change this — change it on the desktop");
    return;
  }
  const dd = $("#devdrop"); if(!dd) return;
  _devdropOpen = true;
  dd.classList.add("open");
  await paintDevDrop();
}
function toggleDevDrop(){
  if(_devdropOpen) closeDevDrop(); else openDevDrop();
}
const _devpill = $("#devpill");
if(_devpill){
  const _pill = $("#statusdiv");
  if(_pill){
    _pill.onclick = () => toggleDevDrop();
    _pill.addEventListener("keydown", e => { if(e.key === "Enter" || e.key === " "){ e.preventDefault(); toggleDevDrop(); } });
  }
  _devpill.addEventListener("mouseenter", () => { if(!_devdropOpen) openDevDrop(true); });
  _devpill.addEventListener("mouseleave", (e) => {
    if(e.relatedTarget && _devpill.contains(e.relatedTarget)) return;
    closeDevDrop();
  });
}
document.addEventListener("click", (e) => {
  if(_devdropOpen && _devpill && !_devpill.contains(e.target)) closeDevDrop();
});
document.addEventListener("keydown", (e) => { if(e.key === "Escape") closeDevDrop(); });
const _devdropall = $("#devdropall");
if(_devdropall) _devdropall.onclick = async () => {
  // v2.8.1 optimistic clear: list + pill empty at once, before
  // the revoke round-trip returns; a failure re-paints.
  const rowsAll = $("#devdroprows");
  if(rowsAll) rowsAll.innerHTML = '<p class="devempty">No devices connected</p>';
  const pillTxtAll = $("#statustext");
  if(pillTxtAll) pillTxtAll.textContent = "No devices connected";
  const dotAll = $("#statusdot"); if(dotAll) dotAll.classList.add("idle");
  const j = await postHostJ("/api/sessions/revoke", {all_guests: true});
  if(j.ok){ toast(j.revoked + " device(s) disconnected"); paintDevDrop(); loadStatus(); }
  else { toast(j.error || "Could not disconnect guests"); paintDevDrop(); loadStatus(); }
};
loadFiles(); loadNotes(); loadStatus();

// ---- sidebar + link window (v2.7.79) ----
const LOCKC = '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>';
const LOCKO = '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.5-2"/></svg>';
function openSidebar(o){
  // v2.8.13: never open the drawer from the login page.
  if(o && document.querySelector("#guestlogin") && document.querySelector("#guestlogin").classList.contains("open")) return;
  $("#sidebar").classList.toggle("open", o);
  $("#scrim").classList.toggle("on", o);
  $("#menubtn").classList.toggle("open", o);
  // v2.7.93: re-check auth when the menu opens, so the host
  // guest-delete toggles are never hidden just because the menu
  // was opened before the boot auth check finished. Guests still
  // never see them (paintSidebar hides them when not host).
  if(o){ paintSidebar(); try { checkAuth().then(() => paintSidebar()); } catch(e){} }
}
function _sepOff(){ return !!(AUTH && AUTH.separate_folders === false); }
function _setChangeLabel(btn, label){
  // Change buttons hold an svg icon + a trailing text node:
  // replace only the text, never the icon.
  if(!btn) return;
  for(const n of btn.childNodes){ if(n.nodeType === 3 && n.nodeValue.trim()){ n.nodeValue = " " + label; return; } }
  btn.appendChild(document.createTextNode(" " + label));
}
function paintSeparateFolders(){
  // v2.8.9 (Essef Nov 4): OFF NEVER disables Change Folder and
  // NEVER renames it -- the 2.8.8 "Change Main Folder" label is
  // reverted (label only). v2.8.12 (Essef Nov 4, 11:14 PM):
  // the MENU button keeps the FULL "Change Folder" label in
  // both states -- the 2.8.11 HTML rename was overwritten back
  // to "Change" here on every paint, which is what his
  // screenshot showed. The Files card stays one-word "Change".
  // v2.8.31: the toggle NO LONGER retargets Change Folder --
  // Change always picks this address's folder, ON or OFF
  // (the old OFF retarget to the Main Folder blocked choosing
  // a folder for an address). The toggle only decides the
  // DEFAULT folder when no per-address folder is set.
  const sep = !_sepOff();
  const sw = $("#swsep"); if(sw) sw.classList.toggle("on", sep);
  const chk = $("#lksepchk"); if(chk) chk.checked = sep;
  const cf = $("#changefolder"); if(cf){ cf.disabled = false; _setChangeLabel(cf, "Change"); cf.setAttribute("data-tip", "Change the save folder for this address"); }
  const lcf = $("#lkchangefolder"); if(lcf){ lcf.disabled = false; _setChangeLabel(lcf, "Change Folder"); lcf.setAttribute("data-tip", "Change the save folder for this address"); }
  const scf = $("#sbchange"); if(scf){ scf.disabled = false; _setChangeLabel(scf, "Change Folder"); scf.setAttribute("data-tip", "Change the Main Folder on this PC"); }
}
async function setSeparateFolders(on){
  if(!(AUTH && AUTH.host)){ toast("Only the host can change this — change it on the desktop"); paintSeparateFolders(); return; }
  const j = await postHostJ("/api/separate_folders", {enabled: !!on});
  if(j.ok){ AUTH.separate_folders = j.separate_folders; await checkAuth(); paintSeparateFolders(); paintAddressAll(); }
  else { toast(j.error || "Could not change that"); paintSeparateFolders(); }
}
function paintSidebar(){
  const st = AUTH || {};
  // v2.8.15 (Essef Nov 5): "Set Up Your Addresses" must not
  // appear on a guest screen at all -- the drawer's host Set Up
  // cards (address setup, separate-folders toggle, Main Folder
  // open/change) are hidden for guests, just like the host
  // sections of the Connect modal. Guests keep Show + Theme.
  // The host sees everything, unchanged.
  ["#sbsetupcard", "#sbsepcard", "#sbfoldercard"].forEach(sel => { const el = $(sel); if(el) el.style.display = st.host ? "" : "none"; });
  // v2.8.39 (1): Disconnect in the menu -- PC web only. The
  // desktop app (bridge) has no session to disconnect from;
  // web host + guest both end the session and return to login.
  const _sdc = $("#sbdisconnect"); if(_sdc) _sdc.style.display = (!hasBridge() && st.authed) ? "" : "none";
  const _sb = $("#sblink"); if(_sb) _sb.innerHTML = st.address_name ? addressDotHtml(st.address_name, st.address_key) : "No address set yet";
  // v2.8.18 (8): "Your address" in the menu is visible to
  // EVERYONE (host + guest) -- a read-only row, never the Set
  // Up controls (those stay host-only above). Guests on the
  // web menu never saw an address before this.
  // v2.8.20 (2): the HOST already sees the address in the
  // "Set Up Your Addresses" card above (#sblink), so the
  // 2.8.18 row duplicated it in the PC menu. The host hides
  // it; guests keep it -- it is their ONLY address row in the
  // web menu (their Set Up cards are hidden above).
  const _sac = $("#sbaddrcard"); if(_sac) _sac.style.display = st.host ? "none" : "";
  const _sa = $("#sbaddr"); if(_sa) _sa.innerHTML = st.address_name ? addressDotHtml(st.address_name, st.address_key) : "No address set yet";
  paintLockBtns();
  $("#sbopen").style.display = "";
  $("#sbchange").style.display = "";
  // v2.7.89: "Lock this device" (self-lock via logout) is retired
  // -- locking is guest-only now, via the switch below. A host
  // logout no longer locks the host out of its own link.
  $("#sblockdev").style.display = "none";
  paintSwitches();
}
function paintLockBtns(){
  const locked = !!(AUTH && AUTH.locked);
  const sb = $("#sblock");
  sb.innerHTML = locked ? LOCKC : LOCKO;
  sb.classList.toggle("locked", locked);
  const cb = $("#linklock");
  if(cb){ cb.innerHTML = locked ? LOCKC : LOCKO; cb.classList.toggle("locked", locked); }
}
// v2.8.11: the QR encodes the CURRENT address, so it must
// refresh on every address change. The <img src="/qr.png">
// never changed, so the browser kept showing the old
// code. A cache-busting query (address key) forces a
// fresh /qr.png (which now also sends no-store) whenever
// paintAddressAll runs, i.e. after every checkAuth /
// address change, on desktop + web + APK web views.
function refreshQr(){
  const v = (AUTH && (AUTH.address_key || AUTH.address_name)) || "";
  if(!v) return;
  const u = "/qr.png?v=" + encodeURIComponent(v);
  document.querySelectorAll(".qr img, .qrmini img").forEach(im => { if(im.getAttribute("src") !== u) im.src = u; });
}
function paintAddressAll(){
  const st = AUTH || {};
  // v2.7.89 Send-tab top box ALWAYS shows connection state:
  // "Link: <exact connected link name>" while connected,
  // "Not connected" when there is no link or this viewer is not
  // signed in (disconnected / locked out). Never blank. The
  // connectbar is the web top box; the mobile Send card has its
  // own state line (mconnstate) below.
  const a = document.querySelector(".connectbar a");
  if(a){ a.innerHTML = (st.authed && st.address_name) ? addressTopHtml(st.address_name, st.address_key) : "Not connected"; if(st.url) a.href = st.url; }
  // v2.8.17 (l): the mobile state line shows ONLY "Connected" /
  // "Not connected" -- the address itself already sits in the
  // box above it (#mpchost), and showing it twice was the
  // duplicate. Connection state still reads off this line (and
  // off the Connect button's .connected arrow).
  const mc = $("#mconnstate"); if(mc) mc.textContent = (st.authed && st.address_name) ? "Connected" : "Not connected";
  // v2.8.14: the mobile Connect arrow is green while connected,
  // muted grey while not -- the APK's paintSendConnectBtn rule.
  const mpcc = $("#mpcconnect"); if(mpcc) mpcc.classList.toggle("connected", !!(st.authed && st.address_name));
  const sb = $("#sblink"); if(sb) sb.innerHTML = st.address_name ? addressDotHtml(st.address_name, st.address_key) : "No address set yet";
  // v2.8.18 (8): keep the menu's "Your address" row in sync too.
  const sa = $("#sbaddr"); if(sa) sa.innerHTML = st.address_name ? addressDotHtml(st.address_name, st.address_key) : "No address set yet";
  // v2.8.39 (1): never clobber an address the user just typed
  // (or is typing) into the card -- the 5s poll used to refill
  // this box from the connected address, so a different address
  // typed here reverted before Connect could be tapped.
  // But a real address SWITCH (host Set Up / link change) must
  // still refill the box: refill whenever the connected
  // address changed since the last paint, or the box is empty.
  // A merely-typed different address (connected address
  // unchanged) is left alone.
  const mp2 = $("#mpchost");
  if(mp2 && document.activeElement !== mp2){
    if(!mp2.value || (st.address_name || "") !== (window.__mpLastAddr || "")) mp2.value = st.address_name || "";
    window.__mpLastAddr = st.address_name || "";
  }
  // v2.8.37 (7): the folder label is ALWAYS refilled, never
  // left showing the previous address's path -- an address
  // with no folder yet reads an em dash, never blank/stale.
  const dl2 = $("#dirnamelabel"); if(dl2) dl2.textContent = st.folder || "—";
  paintLockBtns();
  refreshQr();
}
let showQr = localStorage.getItem("drop_showqr") !== "0";
let showDev = localStorage.getItem("drop_showdev") !== "0";
function applyShowPrefs(){
  // v2.7.87: the QR popup's visibility is class-driven (.open); an
  // inline display style here would permanently block it, so the
  // sidebar switch only hides the QR button (and closes the popup).
  const qp = $("#qrpop"), qm = $("#qrtoggle");
  if(qp && !showQr) closeQrPop();
  if(qm) qm.style.display = showQr ? "" : "none";
  const sd = $("#statusdiv"); if(sd) sd.style.display = showDev ? "" : "none";
  const sw = $("#devpill"); if(sw) sw.style.display = showDev ? "" : "none";
}
function paintSwitches(){
  $("#swqr").classList.toggle("on", showQr);
  $("#swdev").classList.toggle("on", showDev);
}
$("#menubtn").onclick = () => openSidebar(!$("#sidebar").classList.contains("open"));
$("#scrim").onclick = () => openSidebar(false);
// v2.8.37 (8): the menu now covers the top bar (and the menu
// button with it), so Escape closes it too -- the scrim click
// is the other way out. Only when the menu is actually open.
document.addEventListener("keydown", (e) => { if(e.key === "Escape"){ const sb = $("#sidebar"); if(sb && sb.classList.contains("open")) openSidebar(false); } });
$("#sblock").onclick = onLockIcon;
const _ll = $("#linklock"); if(_ll) _ll.onclick = onLockIcon;
// v2.7.90 TOP LINK: clicking the top link NEVER refreshes or
// navigates (the old <a href="__URL__"> reloaded the app and,
// for the desktop window before its bridge token arrived,
// flashed the lock screen). It opens the Set up your addresses
// page (link dialog); a disconnected guest gets its login
// page instead, which is its link page.
const _tl = $("#toplink");
if(_tl) _tl.onclick = e => { e.preventDefault(); if(!(AUTH && AUTH.host) && !(AUTH && AUTH.authed)) showGuestLogin(); else openLinkWin(); };
const _se = $("#sbedit"); if(_se) _se.onclick = () => { openSidebar(false); openLinkWin(); };
// v2.7.96 MENU folder routing: ROOT folder, never the address
// subfolder. The menu must NOT delegate to the Files tab's
// #openfolder / #changefolder buttons (those are address-folder
// buttons). Desktop: the bridge's root methods; other surfaces:
// /api/setrootfolder for Change (host-only, server endpoint),
// and a toast for Open (no OS folder exists on a web surface).
async function openRootFolder(){
  if(hasBridge() && window.pywebview.api.open_root_folder){ try { await window.pywebview.api.open_root_folder(); return; } catch(e){} }
  toast("Open the Main Folder on the desktop PC");
}
async function changeRootFolder(){
  if(hasBridge() && window.pywebview.api.browse_root_directory){
    try {
      const r = await window.pywebview.api.browse_root_directory();
      if(r && r.ok){ await checkAuth(); paintAddressAll(); toast("Main Folder changed"); }
      else if(r && r.error && r.error !== "cancelled"){ toast("Couldn't change the folder: " + r.error); }
    } catch(e){ toast("Couldn't open the folder picker"); }
    return;
  }
  if(!(AUTH && AUTH.host)){ toast("Only the host can change this — change it on the desktop"); return; }
  const path = prompt("Root folder on this PC:", "");
  if(!path) return;
  const j = await postJ("/api/setrootfolder", {folder: path});
  if(j.ok){ await checkAuth(); paintAddressAll(); toast("Main Folder changed"); }
  else toast(j.error || "Couldn't change the folder");
}
$("#sbopen").onclick = () => { openRootFolder(); openSidebar(false); };
// v2.8.39 (1): menu Disconnect (PC web only -- hidden on the
// desktop app by paintSidebar). Ends the session and returns
// to login: a guest lands on the login page, a web host on
// the lock screen. Same doLogout as the mobile Disconnect.
const _sbd = $("#sbdisconnect");
if(_sbd) _sbd.onclick = () => { openSidebar(false); window._userDisconnected = true; doLogout(); toast("Disconnected"); };
$("#sbchange").onclick = () => { changeRootFolder(); openSidebar(false); };
$("#swqr").onclick = () => { showQr = !showQr; localStorage.setItem("drop_showqr", showQr ? "1" : "0"); applyShowPrefs(); paintSwitches(); };
const _swsep = $("#swsep"); if(_swsep) _swsep.onclick = () => { setSeparateFolders(!(AUTH && AUTH.separate_folders === false) ? false : true); };
const _lksep = $("#lksepchk"); if(_lksep) _lksep.addEventListener("change", () => { setSeparateFolders(_lksep.checked); });
$("#swdev").onclick = () => { showDev = !showDev; localStorage.setItem("drop_showdev", showDev ? "1" : "0"); applyShowPrefs(); paintSwitches(); };
$("#themesw2").onclick = () => applyTheme(!document.documentElement.classList.contains("light"));
$("#sblockdev").onclick = async () => { openSidebar(false); await doLogout(); };
// ---- link window (v2.7.87: host screen vs guest connect screen,
// one Save button) ----
// Host: Save redefines the link/password/folder. Guest: Save only
// connects to the host's link (/api/connect); redefinition is
// ---- v2.7.99 Permissions (Set Up Your Addresses) ----
// REPLACES the Devices section (which moved to the Send-card
// dropdown): the host-only Permissions grid for the CURRENT
// address, persisted per address via POST /api/permissions.
// Guests never see this section (openLinkWin hides it); the
// server 403s guest changes in any case. A checkbox change
// posts just that key (the server merges onto the address's
// set) and refreshes the guest grey state immediately.
async function paintPermissions(){
  const sec = $("#lkperms"); if(!sec) return;
  const st = AUTH || {};
  if(!st.host){ sec.style.display = "none"; return; }
  sec.style.display = "";
  try {
    const r = await _origFetch("/api/permissions"); const j = await r.json();
    if(!j.ok || !j.permissions) return;
    AUTH.permissions = j.permissions;
    document.querySelectorAll("#lkpermgrid input[data-perm]").forEach(cb => {
      const k = cb.dataset.perm;
      cb.checked = !!j.permissions[k];
      cb.disabled = false;
      cb.closest(".permchk").classList.remove("disabled");
    });
  } catch(e){}
}
document.querySelectorAll("#lkpermgrid input[data-perm]").forEach(cb => {
  cb.addEventListener("change", async () => {
    if(!(AUTH && AUTH.host)){ cb.checked = !cb.checked; toast("Only the host can change this — change it on the desktop"); return; }
    const body = {}; body[cb.dataset.perm] = cb.checked;
    const j = await postHostJ("/api/permissions", {permissions: body});
    if(j.ok){ if(j.permissions) AUTH.permissions = j.permissions; await checkAuth(); paintDeleteState(); }
    else { cb.checked = !cb.checked; toast(j.error || "Could not change that"); }
  });
});
// v2.7.87: did the user actually type in the password field since
// this screen opened? Untouched + prefilled = KEEP (Save omits the
// password key); touched = SEND the value (empty = remove). The
// prefill fetch below sets .value directly, which fires no input
// event, so it never counts as touched.
let lkPwTouched = false;
// v2.8.38 (2): SAVED-PASSWORD EDIT FLOW, on both password fields
// that ever show a saved password (#lkpw in Set Up / Connect,
// #gloginpw on the login screen). The field shows the saved
// password as dots; clicking INTO it empties it so the user
// types a different password from scratch; clicking OUT with
// nothing typed brings the saved password back (hashed dots);
// clicking out WITH something typed keeps what was typed and
// never brings the saved password back. Empty = open address;
// typed + Save Password checked = saved (hashed) and shown in
// the links lists. State per field: saved (the password the
// field is displaying), shown (field currently displays it),
// keepFocus (the next focus is programmatic -- a reveal or a
// history-row fill -- and must NOT clear the field).
function _mkSavedPwState(onClear, onRestore, onTyped){
  return {saved: "", shown: false, keepFocus: false,
    onClear: onClear, onRestore: onRestore, onTyped: onTyped};
}
const _lkPwSt = _mkSavedPwState(
  () => { lkPwTouched = true; syncLkSavePw(); },
  () => { lkPwTouched = false; syncLkSavePw(); const _e = $("#lkpweye"); if(_e) paintEyeBtn(_e, false); },
  () => { lkPwTouched = true; syncLkSavePw(); });
const _glPwSt = _mkSavedPwState(null, null, null);
function _savedPwFocus(field, st){
  if(!field || !st) return;
  if(st.keepFocus){ st.keepFocus = false; return; }
  if(st.shown && field.value && field.value === st.saved){
    field.value = ""; st.shown = false;
    if(st.onClear) st.onClear();
  }
}
function _savedPwBlur(field, st){
  if(!field || !st) return;
  if(!field.value && st.saved){
    field.value = st.saved; field.type = "password"; st.shown = true;
    if(st.onRestore) st.onRestore();
  } else if(field.value){
    st.shown = false;
    if(st.onTyped) st.onTyped();
  }
}
// v2.8.34 (3): pop-out on close -- add .closing, hide after
// the 160ms pop-out finishes. A re-open cancels the pending
// hide, so the dialog never vanishes under a fresh open.
let _lkCloseT = null;
function closeLinkWin(){
  const w = $("#lkwrap"); if(!w) return;
  if(w.style.display === "none" && !w.classList.contains("closing")) return;
  clearTimeout(_lkCloseT);
  w.classList.add("closing");
  _lkCloseT = setTimeout(() => { w.style.display = "none"; w.classList.remove("closing");
    // v2.8.37 (5): the login page hidden for the Connect modal
    // comes back -- unless the modal's connect succeeded (then
    // the user is authed and belongs on the main page).
    const _gl1 = $("#guestlogin");
    if(_gl1 && _gl1.dataset.lkHidden){ delete _gl1.dataset.lkHidden; if(!(AUTH && AUTH.authed)) _gl1.classList.add("open"); }
  }, 160);
}
// v2.8.37 (1): Set Up Save Password live rule -- the box is
// DISABLED while the password field is empty AND the address
// is open, and ENABLED as soon as any character is typed (the
// same live rule as the Set Password popup, adapted: a LOCKED
// address keeps the box enabled even with an empty field, so
// its stored-but-unretrievable password can still be
// re-saved). An open address with an empty field stays
// disabled (nothing to save); typing a password for a NEW
// address enables it even though the CURRENT address is open
// (the 2.8.36 image-73 bug: the box was computed once from
// the current address and never re-enabled by typing). The
// checked state is left alone -- the guest default (checked)
// and the host sync (checked = a copy is saved) own it.
function syncLkSavePw(){
  const box = $("#lksavepwchk"); const pwf = $("#lkpw"); if(!box || !pwf) return;
  const st = AUTH || {};
  const openAddr = !st.locked && !st.has_password;
  box.disabled = !pwf.value && openAddr;
}
function openLinkWin(){
  // v2.7.93 guard: never throw on a missing window element --
  // a throw here used to make every Set-up click look dead.
  const _lw = $("#lkwrap"); if(!_lw) return;
  clearTimeout(_lkCloseT); _lw.classList.remove("closing");
  _lw.style.display = "flex";
  const st = AUTH || {};
  const host = !!st.host;
  // v2.8.37 (5): a guest opening the Connect modal over the
  // login page would leave TWO live Save Password checkboxes
  // in the page (the login form's #gloginsavechk behind the
  // modal's #lksavepwchk). Hide the login page while the modal
  // is open; closeLinkWin brings it back if still unauthed.
  if(!host){
    const _gl0 = $("#guestlogin");
    if(_gl0 && _gl0.classList.contains("open")){ _gl0.classList.remove("open"); _gl0.dataset.lkHidden = "1"; }
  }
  // v2.7.89 guest link page design: guests get the distinct
  // violet header card + connected-link card; the plain "Your
  // link" heading is replaced by the header card (hidden for
  // guests, shown for the host dialog).
  const lkbox = $("#lkbox"); if(lkbox) lkbox.classList.toggle("guestcard", !host);
  const lkh3 = lkbox ? lkbox.querySelector("h3") : null; if(lkh3) lkh3.style.display = host ? "" : "none";
  const gln0 = $("#guestlinkname"); if(gln0) gln0.innerHTML = (st.authed && st.address_name) ? addressDotHtml(st.address_name, st.address_key) : "Not connected";
  // Main display is the clean user-chosen link name only. No
  // technical address is shown anywhere in this window.
  const _lkn = $("#lkname"); if(_lkn) _lkn.innerHTML = st.address_name ? addressDotHtml(st.address_name, st.address_key) : "No address set yet";
  // Mode split (v2.7.87): HOST gets the full screen -- Current address
  // (read-only), New address, Password, Folder, Open/Change folder,
  // Delete password, devices list. GUEST gets a connect-only
  // screen -- link-to-connect-to input, password entry, single
  // Save. No delete/remove/host-reveal control, no folder change,
  // no link redefinition is shown to a guest at all.
  const show = (id, on) => { const el = $(id); if(el) el.style.display = on ? "" : "none"; };
  show("#guestcardhead", !host); show("#guestlinkcard", !host);
  show("#lkcurlabel", host); show("#lkcurview", host);
  show("#lkfolderlabel", host); show("#lkfolderview", host); show("#lkfolderrow", host);
  // v2.8.15 (Essef Nov 5): the whole host Set Up section stays
  // out of the guest Connect modal -- the split row, the
  // Permissions grid and its label are hidden here too, on top
  // of the CSS !important hard-hide, so no code path can leak
  // them onto a guest screen. A guest sees only address +
  // password + Connect.
  show("#lksplit", host); show("#lkperms", host); show("#lkpermlabel", host);
  show("#lkremovepwbtn", host);
  // v2.8.15: the guest modal's action is a Connect, not a Save.
  const _setBtn = $("#lkset");
  if(_setBtn && _setBtn.lastChild && _setBtn.lastChild.nodeType === 3) _setBtn.lastChild.textContent = host ? " SAVE" : " Connect";
  const addressLabel = $("#lklinklabel");
  // v2.8.16 (Essef Nov 5): the guest label is "Address To
  // Connect" -- the word "to" is removed.
  if(addressLabel) addressLabel.textContent = host ? "New Address" : "Address To Connect";
  const pwLabel = $("#lkpwlabel");
  // v2.7.89: the password is OPTIONAL on both screens, and the
  // guest label must never imply it is required.
  if(pwLabel) pwLabel.textContent = host ? "Password (Optional)" : "Password";
  const inp = $("#lkin");
  // New address starts EMPTY (host): an empty New address leaves
  // the current address unchanged. It is never prefilled with it.
  inp.value = "";
  inp.placeholder = host ? "New Address" : "Address To Connect";
  const pwf = $("#lkpw"); pwf.type = "password";
  pwf.placeholder = host ? "Set A Password (Optional)" : "Password For This Address";
  lkPwTouched = false;
  const err = $("#lkerr"); if(err) err.textContent = "";
  // v2.7.89 HOST-ONLY path: a guest's st.folder is absent from the
  // server, so this stays "-" for guests -- never a host path.
  $("#lkfolder").textContent = host ? (st.folder || "-") : "-";
  const unauth = !st.authed;
  // Guest Save logs in + connects, so guests never need the separate
  // Unlock button; a locked-out host uses it (host Save stays
  // blocked until unlocked). v2.7.89: unauth now also covers the
  // guest lock (not only the password gate).
  $("#lkunlockbtn").style.display = (unauth && host) ? "" : "none";
  // v2.8.12 (Essef Nov 4): the locked/password notice shows ONLY
  // when the address is password-protected AND locked right now.
  // A password set once in the past must not keep the notice
  // showing after the address was unlocked -- the stored password
  // stays (so the host can re-lock without retyping), but an
  // unlocked address shows the open-address notice only.
  // Guests never receive has_password (host-only in /api/authstate),
  // so only an explicit false suppresses the notice on a locked
  // address; undefined (guest) keeps the locked notice. This
  // supersedes the v2.8.7 OR rule (locked OR password stored).
  // v2.8.36 (5): the "Password set for this address." line is
  // gone (Essef Nov 7) -- the locked branch now renders "".
  // The locked warning pill ("Locked address — password
  // required") and the unauth text above stay exactly as
  // they were.
  const _lkNoticeLocked = !!(st.locked && st.has_password !== false);
  $("#lkstate").textContent = unauth
    ? (host ? "This address is locked. Unlock with the current password first, then Save changes the address."
            : "Type the password, then Connect.")
    : "";
  if(host) paintAddressHistory();
  const warn = $("#lkopenwarn"); if(warn) warn.classList.toggle("show", !_lkNoticeLocked);
  const lwarn = $("#lklockedwarn");
  if(lwarn){ lwarn.classList.toggle("show", _lkNoticeLocked);
    const _lt = $("#lklockedtext");
    if(_lt) _lt.textContent = "Locked address — password required"; }
  // v2.7.99: the Devices section is gone from this dialog --
  // devices live in the Send-card dropdown now. This dialog
  // shows the host-only Permissions grid instead.
  paintPermissions(); paintSeparateFolders();
  // Saved-password prefill: HOST ONLY. On the PC the field is
  // filled with the saved password, shown as masked dots
  // (type=password). A guest's field starts blank and is never
  // filled from the host -- the guest types the password.
  // v2.8.38 (2): opening the window clears the edit-flow state
  // with the field; the fetch below re-arms it when it fills.
  pwf.value = ""; _lkPwSt.saved = ""; _lkPwSt.shown = false;
  const _savePwBox = $("#lksavepwchk");
  if(host && (st.has_password || st.locked)){
    _origFetch("/api/linkpassword").then(r => r.json()).then(j => {
      if(j.ok && j.password && !pwf.value && !lkPwTouched){ pwf.value = j.password; _lkPwSt.saved = j.password; _lkPwSt.shown = true; }
      // v2.8.35: the checkbox mirrors whether a password is
      // actually saved for this address.
      if(_savePwBox) _savePwBox.checked = !!(j.ok && j.password);
      // v2.8.37 (1): the prefill may have filled the field --
      // re-run the live disabled rule now (it starts disabled
      // while the field is empty).
      syncLkSavePw();
    }).catch(() => {});
  } else if(_savePwBox){
    // Host with no saved password: unchecked. Guest Connect card:
    // checked by default (remember unless unticked).
    _savePwBox.checked = !host;
  }
  // v2.8.36 (3): an OPEN address has no password to save -- the
  // Save Password checkbox is disabled (greyed out) on the host
  // Set Up dialog and the guest Connect card alike. Open = the
  // gate is not locked AND no password is stored (guests never
  // receive has_password, so undefined reads as "no stored
  // password" and the gate alone decides there). v2.8.37: the
  // live rule (syncLkSavePw) re-evaluates this on every
  // keystroke, so typing a password re-enables the box even
  // when the current address is open (image-73).
  if(_savePwBox){
    const _openAddr = !st.locked && !st.has_password;
    _savePwBox.disabled = !!_openAddr;
    if(_openAddr) _savePwBox.checked = false;
  }
  if(_savePwBox) syncLkSavePw();
  const _eye0 = $("#lkpweye"); if(_eye0) _eye0.innerHTML = eyeSVG(false);
  setTimeout(() => { inp.focus(); }, 60);
}
// v2.8.36 (2): typing in the password field must NOT
// auto-check Save Password -- the user's explicit checkbox
// choice stands (checked = save a retrievable copy,
// unchecked = hash only, still locked).
$("#lkpw").addEventListener("input", () => { lkPwTouched = true; syncLkSavePw(); });
// v2.8.38 (2): the saved-password edit flow -- focus empties a
// field that is showing its saved password, blur restores it
// when nothing was typed (see _savedPwFocus/_savedPwBlur).
// The click listener covers the already-focused field (a row
// fill or an eye reveal focuses it programmatically, so a
// later click into it fires no focus event -- but the spec is
// "clicking into the field empties it").
const _lkpwF38 = $("#lkpw");
if(_lkpwF38){ _lkpwF38.addEventListener("focus", () => _savedPwFocus(_lkpwF38, _lkPwSt)); _lkpwF38.addEventListener("blur", () => _savedPwBlur(_lkpwF38, _lkPwSt)); _lkpwF38.addEventListener("click", () => _savedPwFocus(_lkpwF38, _lkPwSt)); }
const _glpwF38 = $("#gloginpw");
if(_glpwF38){ _glpwF38.addEventListener("focus", () => _savedPwFocus(_glpwF38, _glPwSt)); _glpwF38.addEventListener("blur", () => _savedPwBlur(_glpwF38, _glPwSt)); _glpwF38.addEventListener("click", () => _savedPwFocus(_glpwF38, _glPwSt)); }
// v2.7.92 HOST SAVED-LINKS DROPDOWN (Set up your addresses page).
// Replaces the v2.7.90 rows list: a closed bordered field
// showing the current address, chevron down;
// click opens a floating white list below, chevron flips up;
// click outside or Escape closes it. Rows come from
// /api/linkhistory (names + has_password only -- never a
// password). Selecting a row fills New address + its saved
// password (masked, host-only reveal endpoint) and then runs
// the normal Save path, so it goes through link-name
// validation and toasts "Connected to <link>". The delete
// icon removes the entry from history ONLY (toast says the
// folder and files are still there on this PC) and does NOT
// select that link. Row states: enabled black on white,
// hover light grey, selected purple, selected+hover purple
// on light grey (see .ddopt rules).
// v2.7.92 HOST SAVED-ADDRESSES DROPDOWN (Set up your addresses
// page). The dropdown drops from the current-address field itself
// (chevron inside the field, list floating below it), not from a
// separate history section. Rows come from /api/linkhistory
// (names + has_password only -- never a password). Each row has
// its own eye icon (animated, toggling open / crossed-out and
// hashing / unhashing the password preview) and a delete icon
// identical to the main screens' delete icon (SVG.del). Selecting
// a row fills New address + its saved password (masked,
// host-only reveal endpoint) and then runs the normal Save path,
// so it goes through address-name validation and toasts
// "Connected to <address>". Delete removes the entry from
// history ONLY (toast says the folder and files are still there
// on this PC) and does NOT select that address. Row states:
// enabled black on white, hover light grey, selected purple,
// selected+hover purple on light grey (see .ddopt rules).
async function paintAddressHistory(){
  const list = $("#lkddlist"); if(!list) return;
  try {
    const r = await _origFetch("/api/linkhistory"); const j = await r.json();
    if(!j.ok || !j.entries || !j.entries.length){
      list.innerHTML = '<div class="ddopt ddempty"><span class="ddname">No saved addresses yet.</span></div>';
      return;
    }
    // v2.8.36 (2): history password state -- saved (a
    // retrievable copy exists) shows dots; locked with NO
    // saved copy reads "Locked - No Saved Password"; open
    // with no password reads "No password". The eye button
    // appears ONLY when a copy is saved (hash-only entries
    // have nothing to reveal).
    const currentKey = (AUTH && AUTH.address_key) || addressKeyOf(AUTH && AUTH.address_name);
    list.innerHTML = j.entries.map(e => '<div class="ddopt' + (e.key === currentKey ? ' ddsel' : '') + '" data-key="' + esc(e.key) + '" data-name="' + esc(e.name) + '"><span class="ddname">' + addressDotHtml(e.name, e.key) + '</span><span class="ddpw">' + (e.password_saved ? "••••••" : (e.locked ? "Locked - No Saved Password" : "No password")) + '</span>' +
      (e.password_saved ? '<button class="ddeye" data-eye="' + esc(e.key) + '" title="Show saved password">' + eyeSVG(false) + '</button>' : "") +
      '<button class="dddel" data-delhist="' + esc(e.key) + '" title="Remove from history">' + SVG.del + '</button></div>').join("");
    const chev = $("#lkddchevbtn");
    const close = () => { list.classList.remove("open"); if(chev) chev.textContent = "▾"; };
    list.querySelectorAll(".ddopt").forEach(opt => {
      opt.addEventListener("mouseenter", () => opt.classList.add("ddhover"));
      opt.addEventListener("mouseleave", () => opt.classList.remove("ddhover"));
      opt.onclick = async () => {
        const name = opt.dataset.name, key = opt.dataset.key;
        const nameErr = validateAddressName(name);
        if(nameErr){ shakeAddressField(nameErr); return; }
        $("#lkin").value = name;
        const pwf = $("#lkpw");
        try {
          const rr = await _origFetch("/api/linkpassword?link=" + encodeURIComponent(key));
          const jj = await rr.json();
          if(jj.ok && jj.password){ pwf.value = jj.password; lkPwTouched = false; _lkPwSt.saved = jj.password; _lkPwSt.shown = true; }
          else { _lkPwSt.saved = ""; _lkPwSt.shown = false; }
          // v2.8.35: sync Save Password to the selected address
          // BEFORE the auto-Save below reads it.
          const sc = $("#lksavepwchk"); if(sc) sc.checked = !!(jj.ok && jj.password);
        } catch(e){}
        close();
        $("#lkset").click();
      };
    });
    list.querySelectorAll("[data-eye]").forEach(b => { b.onclick = async (ev) => {
      ev.stopPropagation();
      const row = b.closest(".ddopt");
      const pwSpan = row.querySelector(".ddpw");
      if(pwSpan.dataset.revealed){ pwSpan.textContent = "••••••"; delete pwSpan.dataset.revealed; paintEyeBtn(b, false); return; }
      try {
        const rr = await _origFetch("/api/linkpassword?link=" + encodeURIComponent(b.dataset.eye));
        const jj = await rr.json();
        if(jj.ok && jj.password){ pwSpan.textContent = jj.password; pwSpan.dataset.revealed = "1"; paintEyeBtn(b, true); }
        else toast("Couldn't retrieve the saved password");
      } catch(e){ toast("Couldn't retrieve the saved password"); }
    }; });
    list.querySelectorAll("[data-delhist]").forEach(b => { b.onclick = (ev) => {
      ev.stopPropagation();
      openAddressRemove(b.dataset.delhist, b.closest(".ddopt"));
    }; });
  } catch(e){
    // v2.8.37 (7): a failed history reload keeps the old list
    // on screen instead of blanking the dropdown.
  }
}
// v2.8.11 address-removal prompt: removing an address from
// the dropdown asks FIRST whether its notes and files go too
// -- two separate checkboxes, host-only. Result messages:
// both -> "<address>, notes and files have been deleted.";
// neither -> "Files and notes are still there.";
// files only -> "Files deleted for <address>, the notes are still there.";
// notes only -> "Notes deleted for <address>, the files are still there."
// With separate folders OFF the files live in the shared Main
// Folder, so the files checkbox is disabled (files stay).
let _addrRemKey = "", _addrRemName = "";
function openAddressRemove(key, rowEl){
  if(!(AUTH && AUTH.host)){ toast("Only the host can change this — change it on the desktop"); return; }
  const pop = $("#addrrempop"); if(!pop) return;
  _addrRemKey = key;
  _addrRemName = (rowEl && rowEl.dataset && rowEl.dataset.name) || key;
  const an = $("#addrremaddr"); if(an) an.textContent = _addrRemName;
  const nn = $("#addrremnotes"), ff = $("#addrremfiles"), hint = $("#addrremhint");
  if(nn) nn.checked = false;
  if(ff){ ff.checked = false; ff.disabled = false; const shared = (AUTH && AUTH.separate_folders === false); if(hint) hint.style.display = shared ? "" : "none"; }
  pop.classList.add("open");
}
function closeAddressRemove(){ const pop = $("#addrrempop"); if(pop) pop.classList.remove("open"); }
const _arc = $("#addrremcloseX"); if(_arc) _arc.onclick = closeAddressRemove;
const _arcc = $("#addrremcancel"); if(_arcc) _arcc.onclick = closeAddressRemove;
const _arpop = $("#addrrempop"); if(_arpop) _arpop.addEventListener("mousedown", e => { if(e.target.id === "addrrempop") closeAddressRemove(); });
const _arcf = $("#addrremconfirm"); if(_arcf) _arcf.onclick = async () => {
  const delNotes = !!($("#addrremnotes") && $("#addrremnotes").checked);
  const delFiles = !!($("#addrremfiles") && $("#addrremfiles").checked);
  const jj = await postHostJ("/api/address/remove", {key: _addrRemKey, delete_notes: delNotes, delete_files: delFiles});
  closeAddressRemove();
  if(!(jj && jj.ok)){ toast((jj && jj.error) || "Could not remove that address"); return; }
  const addr = (jj && jj.address) || _addrRemName;
  const nd = !!(jj && jj.notes_deleted), fd = !!(jj && jj.files_deleted);
  if(nd && fd) toast(addr + ", notes and files have been deleted.");
  else if(!nd && !fd) toast("Files and notes are still there.");
  else if(fd) toast("Files deleted for " + addr + ", the notes are still there.");
  else toast("Notes deleted for " + addr + ", the files are still there.");
  // v2.8.35: removal may switch the current address (host
  // only) -- repaint the address displays so the switch shows.
  await checkAuth(); paintAddressAll(); paintAddressHistory(); loadNotes(); loadFiles();
};
const _lkddchev = $("#lkddchevbtn");
if(_lkddchev) _lkddchev.onclick = (ev) => { ev.stopPropagation(); const l = $("#lkddlist"); if(!l) return; const open = l.classList.toggle("open"); _lkddchev.textContent = open ? "▴" : "▾"; };
// v2.8.29 (3): Set Up copy -- the Current Address row's copy
// button copies the FULL WORKING URL (see fullAddressUrl -- the
// QR URL, not the .local form), never the plain address text.
// stopPropagation: the row itself toggles the saved-addresses
// dropdown, and a copy tap must not.
const _lkcp = $("#lkcopy");
if(_lkcp) _lkcp.onclick = async (ev) => {
  if(ev) ev.stopPropagation();
  await ensureConnectUrl();
  const v = fullAddressUrl();
  if(!v){ toast("No address to copy"); return; }
  toast(await copyText(v) ? "Address link copied" : "Couldn't copy address");
};
// v2.7.94: the current-address field itself is the trigger, so a
// click anywhere on it (not on a list row) toggles the list.
const _lkcur = $("#lkcurview");
if(_lkcur) _lkcur.onclick = (ev) => { if(ev.target.closest && ev.target.closest("#lkddlist")) return; const l = $("#lkddlist"); const c = $("#lkddchevbtn"); if(!l) return; const open = l.classList.toggle("open"); if(c) c.textContent = open ? "▴" : "▾"; };
if(!window._lkddDocBound){ window._lkddDocBound = true; document.addEventListener("click", (e) => { const l = document.querySelector("#lkddlist"); const c = document.querySelector("#lkddchevbtn"); if(l && (!e.target.closest || !e.target.closest("#lkcurview"))){ l.classList.remove("open"); if(c) c.textContent = "▾"; } }); }
// v2.7.87: ONE button for the whole link flow, labelled "Save".
// There is no separate Connect, Save Link or Done button in this
// section any more (the dialog closes with the x in its corner).
// HOST: Save redefines the link/password; an empty New address keeps
// the current link, and an untouched prefilled password is KEPT
// (the password key is omitted -- see lkPwTouched). GUEST: Save
// only CONNECTS (login first with the typed password when the link
// is locked, then /api/connect); it never calls /api/setlink,
// /api/setlinkpassword, /api/setlinkfolder, or the reveal endpoint,
// so a guest Save can never change the host's link, password, or
// folder. A different link name from a guest is refused by the
// server (wrong_link), never treated as a rename.
$("#lkset").onclick = async () => {
  const st = AUTH || {};
  const host = !!st.host;
  const cur = st.address_name || "";
  let raw = $("#lkin").value.trim();
  // A pasted desktop link is a connect, not a rename: extract its
  // bare name. Pasting this server's own displayed link means
  // "keep the current link" (host) or "connect to it" (guest) --
  // never a rename, never a silent rewrite of the pasted text.
  const pasted = parsePastedAddress(raw);
  if(pasted){
    if(pasted.toLowerCase() === cur.toLowerCase()) raw = "";
    else raw = pasted;
  }
  // v2.7.89 EMPTY-LINK BLOCK (guest only): an empty guest field
  // must NEVER connect or save a blank link -- Save is blocked
  // here with a clear message, before any connect API call. A
  // pasted current link (normalised to "" above) still counts
  // as entered, so it is restored, not blocked. The HOST keeps
  // the round-4 rule below: empty New address = keep current link
  // (a host Save is not a new connect, it redefines/keeps the
  // host's own link, e.g. changing only the password).
  if(!host && !raw){
    if(pasted){ raw = pasted; }
    else { toast("Enter an address first"); return; }
  }
  let name = raw;
  if(!name){
    if(!cur){
      if(host) shakeAddressField("Type an address name first");
      else toast("Type the address to connect to");
      return;
    }
    name = cur;
  }
  const nameErr = validateAddressName(name);
  if(nameErr){ shakeAddressField(nameErr); return; }
  if(!host){
    const pw = $("#lkpw").value;
    // v2.7.90 password logic: password is optional ONLY for open
    // (passwordless) links. Try the explicit connect FIRST; only
    // when the server says the link is locked do we log in with
    // the typed password and connect again. There is no guest
    // lock any more (retired), so no locked-out branch exists.
    // v2.8.33: refresh the current address first, so the connect
    // never declares a stale one (see refreshAuthName).
    await refreshAuthName();
    showConnPop("connecting");
    let cj = await postJ("/api/connect", {link: name});
    if(cj.ok && cj.authed === false && cj.locked){
      if(!pw){ hideConnPop(); toast("Enter the password first"); return; }
      const lj = await postJ("/api/login", {password: pw});
      if(!lj.ok){ showConnPop("failed"); toast("Incorrect password"); return; }
      justUnlockedAt = Date.now();
      await checkAuth(); paintAddressAll();
      cj = await postJ("/api/connect", {link: name});
    }
    if(cj.ok && cj.authed === false){
      showConnPop("failed");
      toast(cj.locked ? "Enter the password for this address" : "Couldn't connect to this address");
      await checkAuth(); paintAddressAll(); openLinkWin();
      return;
    }
    if(cj.ok){
      window._userDisconnected = false;
      setGuestConnectedAddress(cj.display_address || name);
      bumpAddressUse(cj.display_address || name);
      // v2.8.35: Save password decides whether this device
      // remembers the password for this address.
      const _savePw = !$("#lksavepwchk") || $("#lksavepwchk").checked;
      if(_savePw) saveGuestAddressPw(cj.display_address || name, pw);
      else removeGuestSavedAddressPw(cj.display_address || name);
      showConnPop("connected", cj.display_address || name);
      await checkAuth(); paintAddressAll(); openLinkWin(); slideInBoard();
      lastNotesSig = null; lastFilesSig = null; loadNotes(); loadFiles();
    } else { showConnPop("failed"); toast(cj.error || "Couldn't connect to this address"); }
    return;
  }
  if(st.locked && !st.authed){ toast("Unlock first — tap Unlock with this password"); return; }
  const wasLocked = !!st.locked;
  const pw = $("#lkpw").value;
  // Keep vs remove, explicit: untouched prefilled field -> OMIT the
  // password key (the server keeps it); touched field -> SEND the
  // value (empty = remove, non-empty = set). Never a silent
  // blank-on-save removal, never an ambiguous silent keep.
  // v2.8.36 (2): Save Password decides only whether a
  // RETRIEVABLE copy is kept -- unchecked + a typed password
  // sends the password with save_password:false, so the server
  // stores the hash only and the address STILL LOCKS. Unchecked
  // + empty field still clears (open, no lock). An untouched
  // prefilled field is sent only when unchecked, to drop its
  // saved copy (same password, hash only, lock kept).
  const body = {name};
  const savePwBox = $("#lksavepwchk");
  const savePw = !savePwBox || savePwBox.checked;
  if(lkPwTouched) { body.password = pw; body.save_password = savePw; }
  else if(!savePw && pw) { body.password = pw; body.save_password = false; }
  const j = await postJ("/api/setlink", body);
  if(j.ok){
    // v2.7.90: saving a link is never silent -- it always shows
    // the actual link name it connected to.
    toast(j.message || ("Connected to " + (j.display_address || name)));
    await checkAuth(); paintAddressAll(); openLinkWin(); slideInBoard();
    lastNotesSig = null; lastFilesSig = null; loadNotes(); loadFiles();
  } else if(j.code === "host_only"){ toast(j.error); }
  else if(j.code === "invalid_link_name"){ shakeAddressField(j.error || "That address name is not allowed"); }
  else toast(j.error || "Couldn't set the address");
};
// Password reveal: on the host UI the saved password itself is
// fetched over the authenticated session (never for an
// unauthenticated caller). Saved passwords are stored hashed for
// verification plus locally encrypted for reveal; pure hashing alone
// could not be reversed, and a password saved before this version
// becomes revealable after it is saved once here.
$("#lkpweye").onclick = async () => {
  const pwf = $("#lkpw"); const btn = $("#lkpweye");
  if(pwf.type === "text"){ pwf.type = "password"; paintEyeBtn(btn, false); return; }
  // v2.8.38 (2): revealing is a programmatic focus -- the
  // edit flow must NOT clear the field on it.
  if(pwf.value){ pwf.type = "text"; _lkPwSt.keepFocus = true; pwf.focus(); paintEyeBtn(btn, true); return; }
  // Empty field: only the HOST may reveal the saved password. A
  // guest's field stays blank until the guest types -- the host
  // password is never fetched for a guest (the server 403s
  // /api/linkpassword for guests in any case).
  if(!(AUTH && AUTH.host)){ toast("Type the password first"); return; }
  if(AUTH.has_password === false){ toast("No password set for this address"); return; }
  try {
    const r = await _origFetch("/api/linkpassword");
    const j = await r.json();
    if(j.ok && j.password){ pwf.value = j.password; _lkPwSt.saved = j.password; _lkPwSt.shown = true; pwf.type = "text"; _lkPwSt.keepFocus = true; pwf.focus(); paintEyeBtn(btn, true); }
    else if(j.ok) toast("No password set for this address");
    else if(j.error === "not_retrievable") toast("Save the password once here to enable reveal");
    else toast("Couldn't retrieve the saved password");
  } catch(e){ toast("Couldn't retrieve the saved password"); }
};
$("#lkin").addEventListener("keydown", e => { if(e.key === "Enter") $("#lkset").click(); });
$("#lkunlockbtn").onclick = async () => {
  const pw = $("#lkpw").value;
  if(!pw){ toast("Enter the current password first"); return; }
  const j = await postJ("/api/login", {password: pw});
  if(j.ok){
    window._userDisconnected = false;
    justUnlockedAt = Date.now();
    // v2.8.38 (2): the edit-flow state goes with the field.
    $("#lkpw").value = ""; _lkPwSt.saved = ""; _lkPwSt.shown = false; hideLock();
    await checkAuth(); paintAddressAll(); openLinkWin();
    lastNotesSig = null; lastFilesSig = null; loadNotes(); loadFiles();
    toast("Connected to " + (AUTH.address_name || ""));
  } else toast("Incorrect password");
};
$("#lkremovepwbtn").onclick = async () => {
  // Host only: a guest may not remove the host's password (and the
  // button is hidden on guest screens in any case).
  if(!(AUTH && AUTH.host)){ toast("Only the host can change this — change it on the desktop"); return; }
  if(AUTH.locked && !AUTH.authed){ toast("Unlock first — tap Unlock with this password"); return; }
  // Remove Password visibly empties the field first, then removes it
  // on the server and says so -- never a silent save.
  // v2.8.38 (2): the edit-flow state goes with the field.
  $("#lkpw").value = ""; _lkPwSt.saved = ""; _lkPwSt.shown = false;
  const j = await postJ("/api/setlinkpassword", {password: ""});
  if(j.ok){
    const sc = $("#lksavepwchk"); if(sc) sc.checked = false;
    await checkAuth(); paintAddressAll(); openLinkWin();
    toast("Password removed — Connected to " + (AUTH.address_name || ""));
  } else toast(j.error || "Could not remove the password");
};
$("#lkopenfolder").onclick = () => {
  // Set Up dialog: ADDRESS folder (this address's direct
  // folder), never the root -- the menu is the root route.
  if(hasBridge()){ try { window.pywebview.api.open_folder(); } catch(e){} return; }
  closeLinkWin();
  loadFiles();
  toast("This address's files are listed below");
};
$("#lkchangefolder").onclick = async () => {
  // Set Up dialog: ADDRESS folder (this address's direct
  // folder), never the root -- the menu is the root route.
  // v2.8.31: always the per-address route, ON or OFF -- the
  // old OFF retarget to the Main Folder blocked choosing a
  // folder for an address.
  // Host only (v2.7.86): the desktop bridge path below only exists
  // on the host PC anyway; a guest gets the message, not a prompt.
  if(!(AUTH && AUTH.host)){ toast("Only the host can change this — change it on the desktop"); return; }
  if(hasBridge()){
    try {
      const r = await window.pywebview.api.browse_directory();
      if(r && r.ok){
        const dl = $("#dirnamelabel");
        if(dl) dl.textContent = r.directory;
        await checkAuth(); openLinkWin(); loadFiles();
        toast("Save folder changed");
      } else if(r && r.error && r.error !== "cancelled"){
        toast("Couldn't change the folder: " + r.error);
      }
    } catch(e){ toast("Couldn't open the folder picker"); }
    return;
  }
  const cur = $("#lkfolder").textContent;
  const path = prompt("Folder on this PC for this address:", cur === "-" ? "" : cur);
  if(!path) return;
  const j = await postJ("/api/setlinkfolder", {folder: path});
  if(j.ok){
    await checkAuth(); openLinkWin(); loadFiles();
    toast("Save folder changed");
  } else toast(j.error || "Couldn't change the folder");
};
$("#lkcloseX").onclick = () => { closeLinkWin(); };
// v2.8.9: Permissions info icon -- ONE method only: the hover
// tooltip from its title attribute. The click popup that showed
// the same message is removed; clicking the "i" does nothing.
$("#lkwrap").addEventListener("mousedown", e => { if(e.target.id === "lkwrap") closeLinkWin(); });
// ---- hover popups (v2.7.89, desktop/web only) ----
// Every in-scope button carries data-tip (see the HTML above).
// One shared popup, shown ABOVE the button (or below it when
// there is no room above), centred, never covering the button,
// never cropped off-screen (clamped to the viewport). It changes
// nothing about the click: the button's original handler still
// runs, and no tab/active state is added or toggled here.
const hovertip = document.createElement("div");
hovertip.id = "hovertip"; document.body.appendChild(hovertip);
function showHovertip(el){
  const t = el.getAttribute && el.getAttribute("data-tip");
  if(!t) return;
  hovertip.textContent = t; hovertip.classList.add("show");
  hovertip.style.left = "0px"; hovertip.style.top = "0px";
  const r = el.getBoundingClientRect();
  const w = hovertip.offsetWidth, h = hovertip.offsetHeight;
  let left = r.left + r.width / 2 - w / 2;
  left = Math.max(6, Math.min(left, window.innerWidth - w - 6));
  let top = r.top - h - 8;
  if(top < 6) top = r.bottom + 8;
  hovertip.style.left = left + "px"; hovertip.style.top = top + "px";
}
function hideHovertip(){ hovertip.classList.remove("show"); }
document.addEventListener("mouseover", e => {
  const t = e.target && e.target.closest ? e.target.closest("[data-tip]") : null;
  if(t) showHovertip(t); else hideHovertip();
});
document.addEventListener("mouseout", e => {
  const t = e.target && e.target.closest ? e.target.closest("[data-tip]") : null;
  if(t && !(e.relatedTarget && t.contains(e.relatedTarget))) hideHovertip();
});
document.addEventListener("click", hideHovertip);
window.addEventListener("scroll", hideHovertip, true);
applyShowPrefs();
// v2.7.90 boot: fetch the desktop host token BEFORE the first
// auth check, so the desktop window is recognised as host from
// the very first paint and never flashes the lock screen.
requestHostToken().then(() => checkAuth().then(() => paintAddressAll()));
setInterval(() => { loadFiles(); loadNotes(); loadStatus(); refreshDeleteState(); if(typeof fitSendTab === "function") fitSendTab(); }, 5000);
// The pywebview bridge (desktop app) loads after first paint: once it's ready,
// force one re-render so the host screen flips from the guest connect screen
// as soon as the bridge is ready -- without a reload. (v2.8.25: the file-row
// buttons no longer depend on the bridge -- they always show the Open icon --
// so this re-render is for auth, not for the button icon.)
// v2.8.21 (B): mark the PC desktop app on <html> so its CSS can
// kill horizontal scrolling (see .pcapp). Set at boot when the
// bridge is already there, and again on pywebviewready when it
// appears after first paint; plain browsers / phones never get it.
function markPcApp(){ try{ if(hasBridge()) document.documentElement.classList.add("pcapp"); }catch(e){} }
markPcApp();
// v2.8.33: CUSTOM TITLE BAR (PC app only, Design 4 -- glossy,
// slightly see-through, round logo). The window is frameless, so this bar is the
// only chrome: logo + Drop left, min / max-restore / close
// right. It shows only when the bridge says the window really
// is frameless (html.frameless) -- a framed fallback keeps the
// native bar and this stays hidden. Drag: mousedown on the bar
// (not the buttons) + mousemove moves the window via the
// bridge; double-click toggles maximise, like a normal window.
// MAXIMISE ICON (Essef Nov 6): the button ALWAYS reflects the
// window state -- single square while normal, overlapping
// restore-down squares while maximised (syncTbMaxIcon, run at
// boot, after every toggle, and on resize so an external
// maximise -- Win+Up, snap, taskbar -- flips it too).
async function markFrameless(){
  try{
    if(!hasBridge() || !window.pywebview.api.is_frameless) return;
    const r = await window.pywebview.api.is_frameless();
    if(!(r && r.frameless)) return;
    document.documentElement.classList.add("frameless");
    syncTbMaxIcon();
  }catch(e){}
}
async function syncTbMaxIcon(){
  try{
    const bar = $("#titlebar"); if(!bar) return;
    const api = window.pywebview && window.pywebview.api;
    if(!api || !api.is_maximized) return;
    const m = await api.is_maximized();
    bar.classList.toggle("maxed", !!(m && m.maximized));
    const b = $("#tbmax"); if(b) b.title = (m && m.maximized) ? "Restore Down" : "Maximize";
  }catch(e){}
}
markFrameless();
let _tbResizeT = null;
window.addEventListener("resize", () => {
  if(!document.documentElement.classList.contains("frameless")) return;
  clearTimeout(_tbResizeT);
  _tbResizeT = setTimeout(syncTbMaxIcon, 150);
});
const _tbmin = $("#tbmin");
if(_tbmin) _tbmin.onclick = async () => { try{ await window.pywebview.api.minimize_window(); }catch(e){} };
const _tbmax = $("#tbmax");
if(_tbmax) _tbmax.onclick = async () => {
  try{
    const r = await window.pywebview.api.toggle_maximize_window();
    const bar = $("#titlebar");
    if(bar) bar.classList.toggle("maxed", !!(r && r.maximized));
    _tbmax.title = (r && r.maximized) ? "Restore Down" : "Maximize";
  }catch(e){}
};
const _tbclose = $("#tbclose");
if(_tbclose) _tbclose.onclick = async () => { try{ await window.pywebview.api.close_window(); }catch(e){} };
let _tbdrag = null;
let _tbMoveFlight = null, _tbMoveNext = null;
function _tbMove(x, y){
  // v2.8.41 (4): coalesced window moves. The old code fired
  // one un-awaited move_window per mousemove, so a fast drag
  // queued dozens of stale targets behind the slow pywebview
  // bridge -- the window lagged the cursor, then jumped
  // through old positions after the drag stopped (the
  // "glitching" Essef saw in 2.8.40; the drag code itself is
  // byte-identical to smooth 2.8.38 -- the queue pile-up is
  // what changed, fed by the search/scan CPU storms that
  // starved the bridge, fixed in (1)/(2)). At most one move
  // is ever in flight; each mousemove only records the
  // LATEST target, which is sent as soon as the flight
  // lands. The window can never chase stale positions.
  _tbMoveNext = {x: x, y: y};
  if(_tbMoveFlight) return;
  const send = async () => {
    while(_tbMoveNext){
      const t = _tbMoveNext; _tbMoveNext = null;
      _tbMoveFlight = (async () => {
        try{
          const api = window.pywebview && window.pywebview.api;
          if(api && api.move_window) await api.move_window(t.x, t.y);
        }catch(err){}
      })();
      await _tbMoveFlight;
    }
    _tbMoveFlight = null;
  };
  send();
}
const _tb = $("#titlebar");
if(_tb){
  _tb.addEventListener("mousedown", e => {
    if(e.button !== 0 || (e.target && e.target.closest && e.target.closest(".tb-btn"))) return;
    try{ _tbdrag = { ox: e.screenX - window.screenX, oy: e.screenY - window.screenY, sx: e.screenX, sy: e.screenY, moved:false }; }catch(err){ _tbdrag = null; }
  });
  _tb.addEventListener("dblclick", e => {
    if(e.target && e.target.closest && e.target.closest(".tb-btn")) return;
    try{ const b = $("#tbmax"); if(b) b.click(); }catch(err){}
  });
  document.addEventListener("mousemove", e => {
    if(!_tbdrag) return;
    // v2.8.34 (5): a plain click (or a 1-2px jitter between
    // down and up) never moves the window -- only a real
    // drag past 3px does. Without this the first mousemove
    // after a click re-aimed the window and it visibly
    // jumped. The drag still starts ONLY from the title
    // bar (this listener is armed by its mousedown alone);
    // clicks, holds and text selection anywhere else never
    // arm it, so they can never move the window.
    if(!_tbdrag.moved){
      if(Math.abs(e.screenX - _tbdrag.sx) < 3 && Math.abs(e.screenY - _tbdrag.sy) < 3) return;
      _tbdrag.moved = true;
    }
    _tbMove(e.screenX - _tbdrag.ox, e.screenY - _tbdrag.oy);
  });
  document.addEventListener("mouseup", () => { _tbdrag = null; });
  // v2.8.41 (4): a mouseup outside the window (fast drag off
  // the edge) never reaches the document listener -- without
  // this the next mousemove would keep moving the window.
  window.addEventListener("blur", () => { _tbdrag = null; });
}
let bridgeSeen = hasBridge();
window.addEventListener("pywebviewready", async () => {
  markPcApp();
  markFrameless();
  // v2.7.88: the bridge may appear after the first paint (and
  // after the first checkAuth). Fetch the host token, then
  // re-check auth so the desktop window flips from the guest
  // connect screen to the full host screen as soon as the bridge
  // is ready -- without a reload.
  const got = await requestHostToken();
  if(!bridgeSeen && hasBridge()){ bridgeSeen = true; lastFilesSig = null; loadFiles(); }
  if(got){ await checkAuth(); paintAddressAll(); }
});
// Best effort on load too, in case the bridge is already present.
requestHostToken().then(got => { if(got){ checkAuth().then(() => paintAddressAll()); } });
// ---------- custom right-click menu (desktop only: pywebview shows no native menu;
// phones keep their native long-press menu, so this stays off touch devices) ----------
(function(){
  const ctx = document.createElement("div");
  ctx.id = "ctxmenu"; ctx.style.display = "none";
  document.body.appendChild(ctx);
  const hideCtx = () => { ctx.style.display = "none"; };
  document.addEventListener("click", e => { if(!ctx.contains(e.target)) hideCtx(); });
  document.addEventListener("keydown", e => { if(e.key === "Escape") hideCtx(); });
  window.addEventListener("blur", hideCtx);
  let lastMenuAt = 0;
  const isDesktop = () => {
    try { if(window.matchMedia && matchMedia("(pointer:fine)").matches) return true; } catch(e){}
    try { if(typeof hasBridge === "function" && hasBridge()) return true; } catch(e){}
    return false;
  };
  const editableAt = el => el && el.closest &&
    el.closest("textarea, input:not([type=button]):not([type=submit]):not([type=checkbox]), [contenteditable='true']");
  const selectElText = el => {
    const r = document.createRange(); r.selectNodeContents(el);
    const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
  };
  // Read the clipboard. Desktop app: native bridge (no permission prompt, always
  // accurate). Plain browser: only read when permission is already granted — never
  // cold-prompt on a mere right-click.
  const readClip = async () => {
    try {
      if(typeof hasBridge === "function" && hasBridge()){
        const api = window.pywebview.api;
        if(api && typeof api.get_clipboard === "function"){
          const r = await api.get_clipboard();
          if(r && typeof r.text === "string") return r.text;
        }
      }
    } catch(e){}
    try {
      let granted = false;
      if(navigator.permissions && navigator.permissions.query){
        const st = await navigator.permissions.query({name: "clipboard-read"});
        granted = st.state === "granted";
      } else { granted = true; }
      if(!granted) return "";
      const r = await Promise.race([
        navigator.clipboard.readText(),
        new Promise(res => setTimeout(() => res(""), 800))
      ]);
      return r || "";
    } catch(err){ return ""; }
  };
  const showMenu = async (e) => {
    const ed = editableAt(e.target);
    const sel = (window.getSelection() || "").toString();
    const card = e.target.closest ? e.target.closest(".snipcard") : null;
    const noteTextEl = card ? card.querySelector(".sniptext") : null;
    const modalTextEl = e.target.closest ? e.target.closest(".abody") : null;
    const chatTextEl = e.target.closest ? e.target.closest(".amsg.bot") : null;
    const textEl = noteTextEl || modalTextEl || chatTextEl;
    const frowEl = e.target.closest ? e.target.closest(".frow") : null;
    // v2.8.24 (2): the row Open button opens the file now, so
    // "Show in folder" lives here instead (desktop only).
    if(!ed && !textEl && !(frowEl && typeof hasBridge === "function" && hasBridge())) return false;
    const cx = e.clientX, cy = e.clientY;
    const clipText = await readClip();
    ctx.innerHTML = "";
    const addItem = (label, fn, disabled) => {
      const b = document.createElement("button");
      b.className = "ctxitem" + (disabled ? " off" : "");
      b.textContent = label;
      if(!disabled) b.onclick = () => { hideCtx(); fn(); };
      ctx.appendChild(b);
    };
    if(frowEl && !ed && !textEl){
      addItem("Show in folder", () => revealFile(frowEl.dataset.frow));
    }
    if(ed){
      const edSel = ed.selectionStart !== undefined && ed.selectionStart !== ed.selectionEnd;
      const text = sel || (edSel ? ed.value.slice(ed.selectionStart, ed.selectionEnd) : "");
      addItem("Select all", () => { ed.focus(); ed.select(); });
      addItem("Copy", () => copyText(text), !text);
      // Paste is always shown; greyed out and unclickable when the clipboard is empty.
      addItem("Paste", () => {
        ed.focus();
        const s = ed.selectionStart !== undefined ? ed.selectionStart : ed.value.length;
        const en = ed.selectionEnd !== undefined ? ed.selectionEnd : ed.value.length;
        ed.setRangeText(clipText, s, en, "end");
        ed.dispatchEvent(new Event("input", {bubbles:true}));
      }, !clipText);
    } else if(textEl) {
      // read-only text (notes, AI results): Select all + Copy only, never Paste
      addItem("Select all", () => selectElText(textEl));
      addItem("Copy", () => copyText(sel), !sel);
    }
    const x = Math.min(cx, window.innerWidth - 170);
    const y = Math.min(cy, window.innerHeight - ctx.children.length * 38 - 16);
    ctx.style.left = Math.max(4, x) + "px";
    ctx.style.top = Math.max(4, y) + "px";
    ctx.style.display = "block";
    return true;
  };
  // Primary trigger: the standard contextmenu event.
  document.addEventListener("contextmenu", e => {
    if(!isDesktop()) return;  // touch phones keep their native menu
    if(Date.now() - lastMenuAt < 600) return;  // already shown by the mousedown fallback
    e.preventDefault(); hideCtx();
    lastMenuAt = Date.now();
    showMenu(e);
  });
  // Fallback trigger: some embedded webviews swallow contextmenu, but the
  // right mouse button press itself still fires.
  document.addEventListener("mousedown", e => {
    if(e.button !== 2 || !isDesktop()) return;
    const ed = editableAt(e.target);
    const card = e.target.closest ? e.target.closest(".snipcard") : null;
    const modal = e.target.closest ? e.target.closest(".abody") : null;
    const chat = e.target.closest ? e.target.closest(".amsg.bot") : null;
    const frow = e.target.closest ? e.target.closest(".frow") : null;
    if(!ed && !(card && card.querySelector(".sniptext")) && !modal && !chat && !(frow && typeof hasBridge === "function" && hasBridge())) return;
    e.preventDefault();
    lastMenuAt = Date.now();
    showMenu(e);
  });
})();
</script>

</body>
</html>
"""


def lan_ip() -> str:
    """Best-effort LAN IP without sending any traffic."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def asset_path(name: str):
    """Path to a bundled asset; works frozen (PyInstaller) and from source."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        for cand in (os.path.join(base, "assets", name), os.path.join(base, name)):
            if os.path.isfile(cand):
                return cand
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "assets", name), os.path.join(here, name)):
        if os.path.isfile(cand):
            return cand
    return None


_IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "heic", "svg"}


def _is_image(name: str) -> bool:
    return name.rsplit(".", 1)[-1].lower() in _IMAGE_EXTS if "." in name else False


_THUMB_CACHE = {}


def _thumbnail(path: str):
    """Return (bytes, content_type) for a small preview of an image file.

    v2.7.90 fixes for broken thumbnails: (1) EXIF orientation is
    applied so phone screenshots are not sideways; (2) a truncated
    or otherwise Pillow-unreadable image returns None (the handler
    404s and the UI shows the file icon) instead of serving the
    corrupt original bytes, which browsers render as a broken
    image icon; (3) Pillow-missing is the ONLY fallback-to-original
    case (a valid PNG/JPEG still renders fine without Pillow).
    A format Pillow cannot decode at all (e.g. HEIC with no codec)
    therefore 404s cleanly instead of showing a broken icon."""
    try:
        key = (path, os.path.getmtime(path), os.path.getsize(path))
    except OSError:
        return None
    hit = _THUMB_CACHE.get(key)
    if hit:
        return hit
    data, ctype = None, "image/jpeg"
    try:
        from PIL import Image, ImageFile, ImageOps
        ImageFile.LOAD_TRUNCATED_IMAGES = True
        img = Image.open(path)
        img = ImageOps.exif_transpose(img)
        img.thumbnail((384, 384), Image.LANCZOS)
        if img.mode in ("RGBA", "LA", "PA"):
            bg = Image.new("RGB", img.size, (10, 13, 22))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        else:
            img = img.convert("RGB")
        import io

        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=72)
        data = buf.getvalue()
    except ImportError:
        # No Pillow on this PC: best effort is the original bytes.
        try:
            with open(path, "rb") as f:
                data = f.read()
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        except OSError:
            return None
    except Exception:  # noqa: BLE001 - corrupt/unsupported: no broken icon
        return None
    if data is None:
        return None
    if len(_THUMB_CACHE) > 300:
        _THUMB_CACHE.clear()
    _THUMB_CACHE[key] = (data, ctype)
    return data, ctype


def safe_name(name: str) -> str:
    name = os.path.basename(name).strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return name or "upload"


_DOCX_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_to_html(path: str):
    """Convert a .docx file to simple sanitized HTML using only the stdlib.
    Returns the HTML string, or None if the file can't be read/parsed."""
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml")
        root = ET.fromstring(xml)
    except Exception:
        return None
    W = _DOCX_W
    body = root.find(W + "body")
    if body is None:
        return None

    # Elements whose subtree can carry visible text; recursed in document order.
    # w:del / w:delText (tracked deletions) are skipped so the preview shows final text.
    # Property elements (pPr, rPr, sectPr, ...) carry no visible text and are skipped.
    _SKIP = {W + "del", W + "delText", W + "pPr", W + "rPr", W + "sectPr",
             W + "sdtPr", W + "numPr", W + "tblPr", W + "trPr", W + "tcPr"}

    def runs(el, fmt):
        """Yield (text, fmt) for visible text under el, in document order.
        Recurses through hyperlink / tracked-insertion / content-control /
        textbox wrappers so real-world Word files don't lose their text."""
        for child in el:
            tag = child.tag
            if not isinstance(tag, str) or tag in _SKIP:
                continue
            if tag == W + "t":
                yield (child.text or "", fmt)
            elif tag == W + "tab":
                yield (" ", fmt)
            elif tag == W + "br":
                yield ("\n", fmt)
            elif tag == W + "r":
                rpr = child.find(W + "rPr")
                f = fmt
                if rpr is not None:
                    f = dict(fmt)
                    if rpr.find(W + "b") is not None:
                        f["b"] = True
                    if rpr.find(W + "i") is not None:
                        f["i"] = True
                    if rpr.find(W + "u") is not None:
                        f["u"] = True
                yield from runs(child, f)
            elif tag.startswith(W):
                yield from runs(child, fmt)
            # Other namespaces (drawings, embedded objects): nothing readable.

    def styled(text, fmt):
        t = html.escape(text)
        if fmt.get("b"):
            t = "<b>" + t + "</b>"
        if fmt.get("i"):
            t = "<i>" + t + "</i>"
        if fmt.get("u"):
            t = "<u>" + t + "</u>"
        return t

    def para_html(p):
        parts = []
        for text, fmt in runs(p, {}):
            if text == "\n":
                parts.append("<br>")
            elif text.strip():
                parts.append(styled(text, fmt))
            elif text:
                parts.append(" ")
        return "".join(parts)

    def blocks(el):
        out = []
        for child in el:
            tag = child.tag
            if not isinstance(tag, str):
                continue
            if tag == W + "p":
                ppr = child.find(W + "pPr")
                style, is_list = "", False
                if ppr is not None:
                    ps = ppr.find(W + "pStyle")
                    if ps is not None:
                        style = ps.get(W + "val", "") or ""
                    is_list = ppr.find(W + "numPr") is not None
                inner = para_html(child)
                if not inner.strip():
                    out.append("<p>&nbsp;</p>")
                elif style.startswith("Heading"):
                    digits = "".join(c for c in style if c.isdigit())
                    lvl = max(1, min(6, int(digits) if digits else 1))
                    out.append("<h%d>%s</h%d>" % (lvl, inner, lvl))
                elif is_list:
                    out.append("<p>&bull; " + inner + "</p>")
                else:
                    out.append("<p>" + inner + "</p>")
            elif tag == W + "tbl":
                rows = []
                for tr in child.findall(W + "tr"):
                    cells = []
                    for tc in tr.findall(W + "tc"):
                        txt = " ".join(para_html(p) for p in tc.findall(W + "p"))
                        cells.append("<td>" + txt + "</td>")
                    rows.append("<tr>" + "".join(cells) + "</tr>")
                out.append('<table class="dx">' + "".join(rows) + "</table>")
            elif tag == W + "sdt":
                # Structured document tag (content control): render its content.
                content = child.find(W + "sdtContent")
                if content is not None:
                    out.append(blocks(content))
        return "".join(out)

    return blocks(body)


def _cfb_read_stream(data: bytes, name: str):
    """Read one named stream from an OLE2 Compound Document (.doc).

    Minimal stdlib CFB reader: header + FAT + directory + mini
    stream/miniFAT. Returns the stream bytes, or None if the file
    is not a CFB document or the stream is missing. Streams under
    the 4096-byte mini-stream cutoff live in the mini stream, which
    is why small .doc files need the miniFAT path too.
    """
    try:
        if len(data) < 512 or data[:8] != bytes.fromhex("D0CF11E0A1B11AE1"):
            return None
        sector_size = 1 << struct.unpack_from("<H", data, 30)[0]
        mini_sector_size = 1 << struct.unpack_from("<H", data, 32)[0]
        num_fat_sectors = struct.unpack_from("<I", data, 44)[0]
        first_dir_sector = struct.unpack_from("<I", data, 48)[0]
        mini_cutoff = struct.unpack_from("<I", data, 56)[0]
        first_minifat_sector = struct.unpack_from("<I", data, 60)[0]
        first_difat_sector = struct.unpack_from("<I", data, 68)[0]
        if sector_size < 128 or sector_size > 65536:
            return None
        difat = list(struct.unpack_from("<109I", data, 76))
        # Extra DIFAT sectors (only for very large files).
        s, guard = first_difat_sector, 0
        while s < 0xFFFFFFFA and guard < 64:
            guard += 1
            off = (s + 1) * sector_size
            if off + sector_size > len(data):
                break
            entries = struct.unpack_from(
                "<%dI" % (sector_size // 4 - 1), data, off)
            difat.extend(entries)
            s = struct.unpack_from("<I", data, off + sector_size - 4)[0]
        fat_sectors = [x for x in difat[:num_fat_sectors]
                       if x < 0xFFFFFFFA]
        fat = []
        for fs in fat_sectors:
            off = (fs + 1) * sector_size
            if off + sector_size > len(data):
                return None
            fat.extend(struct.unpack_from(
                "<%dI" % (sector_size // 4), data, off))

        def read_chain(start, size=None):
            out = bytearray()
            s, hops = start, 0
            while 0 <= s < 0xFFFFFFFA and hops < 100000:
                hops += 1
                off = (s + 1) * sector_size
                if off + sector_size > len(data):
                    break
                out += data[off:off + sector_size]
                s = fat[s] if s < len(fat) else 0xFFFFFFFE
            return bytes(out[:size]) if size is not None else bytes(out)

        dirstream = read_chain(first_dir_sector)
        entries = {}
        for i in range(0, len(dirstream) - 127, 128):
            e = dirstream[i:i + 128]
            nlen = struct.unpack_from("<H", e, 64)[0]
            if nlen < 2 or nlen > 64:
                continue
            nm = e[:nlen - 2].decode("utf-16-le", "replace")
            entries[nm] = (e[66],
                           struct.unpack_from("<I", e, 116)[0],
                           struct.unpack_from("<Q", e, 120)[0])
        if name not in entries or "Root Entry" not in entries:
            return None
        otype, start, size = entries[name]
        if otype != 2:
            return None
        if size < mini_cutoff:
            # Mini stream: the root entry's chain, indexed by the miniFAT.
            _, root_start, root_size = entries["Root Entry"]
            ministream = read_chain(root_start, root_size)
            minifat_raw = read_chain(first_minifat_sector)
            if len(minifat_raw) < 4:
                return None
            minifat = struct.unpack_from(
                "<%dI" % (len(minifat_raw) // 4), minifat_raw, 0)
            out = bytearray()
            s, hops = start, 0
            while 0 <= s < 0xFFFFFFFA and hops < 100000:
                hops += 1
                off = s * mini_sector_size
                if off + mini_sector_size > len(ministream):
                    break
                out += ministream[off:off + mini_sector_size]
                s = minifat[s] if s < len(minifat) else 0xFFFFFFFE
            return bytes(out[:size])
        return read_chain(start, size)
    except Exception:  # noqa: BLE001 - malformed .doc: no preview
        return None


def _doc_clean_text(raw: str) -> str:
    """Turn raw .doc main-text characters into clean preview text:
    paragraph marks / cell marks / line breaks become newlines,
    other control characters are dropped, runs of blank lines
    collapse."""
    out = []
    for ch in raw:
        o = ord(ch)
        if ch in "\r\x07\x0b":
            out.append("\n")
        elif o < 32 and ch not in "\t\n":
            continue
        else:
            out.append(ch)
    text = "".join(out)
    lines = [ln.rstrip() for ln in text.split("\n")]
    # Collapse 3+ blank lines to one blank line; drop leading/trailing blanks.
    cleaned, blanks = [], 0
    for ln in lines:
        if not ln.strip():
            blanks += 1
            if blanks <= 1:
                cleaned.append("")
        else:
            blanks = 0
            cleaned.append(ln)
    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()
    return "\n".join(cleaned)


def xlsx_to_html(path: str):
    """Convert the first sheet of a .xlsx file to a simple HTML table,
    using only the stdlib (zipfile + ElementTree), mirroring
    docx_to_html. Shared strings, inline strings and numbers are
    read; the first row renders as a header. Capped at 200 rows x
    26 columns so a huge sheet cannot flood the preview. Returns
    the HTML string, or None if the file can't be read/parsed."""
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            shared = []
            if "xl/sharedStrings.xml" in names:
                sroot = ET.fromstring(z.read("xl/sharedStrings.xml"))
                S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
                for si in sroot.findall(S + "si"):
                    shared.append("".join(
                        (t.text or "") for t in si.iter(S + "t")))
            sheet_name = None
            for cand in ("xl/worksheets/sheet1.xml",):
                if cand in names:
                    sheet_name = cand
                    break
            if sheet_name is None:
                for n in names:
                    if n.startswith("xl/worksheets/") and n.endswith(".xml"):
                        sheet_name = n
                        break
            if sheet_name is None:
                return None
            root = ET.fromstring(z.read(sheet_name))
    except Exception:
        return None
    S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    data = root.find(S + "sheetData")
    if data is None:
        return None
    rows = []
    for row in data.findall(S + "row"):
        if len(rows) >= 200:
            break
        cells = []
        for c in row.findall(S + "c"):
            if len(cells) >= 26:
                break
            t = c.get("t")
            v = c.find(S + "v")
            isv = c.find(S + "is")
            if t == "s" and v is not None and v.text is not None:
                try:
                    text = shared[int(v.text)]
                except (ValueError, IndexError):
                    text = ""
            elif t == "inlineStr" and isv is not None:
                text = "".join((x.text or "") for x in isv.iter(S + "t"))
            elif v is not None:
                text = v.text or ""
            else:
                text = ""
            cells.append(text)
        if cells:
            rows.append(cells)
    if not rows:
        return None
    out = ["<table>"]
    for i, cells in enumerate(rows):
        tag = "th" if i == 0 else "td"
        out.append("<tr>" + "".join(
            "<%s>%s</%s>" % (tag, html.escape(c), tag)
            for c in cells) + "</tr>")
    out.append("</table>")
    return "".join(out)


# --- archive listing (.zip / .rar, v2.8.33 (8)) ------------------------
# LISTING ONLY: file names, sizes and folders -- no decompression,
# no extraction (a later step). Stdlib only, so the zero-setup
# installer stays zero-setup: ZIP via zipfile; RAR via the two
# header parsers below (RAR needs a reader and there is no
# rarfile / unrar / 7z on the machine, so the reader is bundled
# here instead of asking the user to install anything).
# Both parsers read headers only and seek over the compressed
# data, so a huge archive lists without being loaded into memory.
# A corrupt / truncated / header-encrypted archive raises
# ValueError with a human-readable reason; the /api/archive/
# handler turns that into {"ok": false, "error": ...}.

_RAR4_SIG = b"Rar!\x1a\x07\x00"
_RAR5_SIG = b"Rar!\x1a\x07\x01\x00"
_ARCHIVE_MAX_ENTRIES = 10000


def _archive_err(exc):
    msg = (str(exc) or "").splitlines()[0][:120] if str(exc) else ""
    return msg or exc.__class__.__name__


def _rar_decode_name(raw, unicode_flag):
    # RAR4 names are bytes. With the unicode flag the field may
    # hold name + NUL + UTF-16LE name; otherwise it is UTF-8
    # (WinRAR 4+) or an OEM codepage -- cp437 is the best guess.
    if unicode_flag and b"\x00" in raw:
        head, _, tail = raw.partition(b"\x00")
        if tail:
            try:
                return tail.decode("utf-16-le")
            except UnicodeDecodeError:
                pass
        raw = head
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp437", errors="replace")


def _rar4_entries(f, start):
    """List a RAR 4.x archive. f is positioned by seek; start is
    the offset just after the 7-byte signature."""
    entries = []
    f.seek(start)
    seen_main = False
    while True:
        head = f.read(7)
        if len(head) < 7:
            break
        _crc, htype, flags, size = struct.unpack("<HBHH", head)
        if size < 7:
            raise ValueError("corrupt RAR archive (bad block size)")
        long_block = bool(flags & 0x8000)
        add_size = 0
        if long_block:
            raw = f.read(4)
            if len(raw) < 4:
                raise ValueError("truncated RAR archive")
            add_size = struct.unpack("<I", raw)[0]
        body_len = size - 7 - (4 if long_block else 0)
        if body_len < 0:
            raise ValueError("corrupt RAR archive (bad block size)")
        if htype == 0x73:  # main header: always first in a real archive
            seen_main = True
            f.seek(body_len + add_size, 1)
            continue
        if not seen_main:
            raise ValueError(
                "not a readable RAR archive (it may use header encryption)")
        if htype == 0x74:  # file header
            body = f.read(body_len)
            if len(body) < body_len:
                raise ValueError("truncated RAR archive")
            if len(body) < 25:
                raise ValueError("corrupt RAR archive (short file header)")
            pack_size, unp_size = struct.unpack_from("<II", body, 0)
            name_size = struct.unpack_from("<H", body, 19)[0]
            attr = struct.unpack_from("<I", body, 21)[0]
            off = 25
            if flags & 0x0100:  # high pack / unpack sizes present
                if len(body) < off + 8:
                    raise ValueError("corrupt RAR archive (short file header)")
                high_pack, high_unp = struct.unpack_from("<II", body, off)
                pack_size |= high_pack << 32
                unp_size |= high_unp << 32
                off += 8
            if off + name_size > len(body):
                raise ValueError("corrupt RAR archive (short file name)")
            name = _rar_decode_name(body[off:off + name_size],
                                    bool(flags & 0x0200))
            is_dir = bool(attr & 0x10) or name.endswith(("/", "\\"))
            entries.append({"name": name, "size": unp_size,
                            "is_dir": is_dir})
            # Skip the compressed data (ADD_SIZE == pack size here).
            f.seek(add_size if long_block else pack_size, 1)
        else:
            # Comment / subblock / recovery / anything else: skip
            # its header rest plus its data and keep listing.
            f.seek(body_len + add_size, 1)
        if len(entries) >= _ARCHIVE_MAX_ENTRIES:
            break
    if not seen_main:
        raise ValueError("not a readable RAR archive")
    return entries


def _rar5_varint(buf, pos):
    # RAR5 variable-length integer (LEB128), max 10 bytes.
    result = 0
    shift = 0
    for _ in range(10):
        if pos >= len(buf):
            raise ValueError("truncated RAR archive")
        v = buf[pos]
        pos += 1
        result |= (v & 0x7F) << shift
        if not (v & 0x80):
            return result, pos
        shift += 7
    raise ValueError("corrupt RAR archive (bad varint)")


def _rar5_varint_file(f):
    result = 0
    shift = 0
    for _ in range(10):
        b = f.read(1)
        if len(b) != 1:
            raise ValueError("truncated RAR archive")
        v = b[0]
        result |= (v & 0x7F) << shift
        if not (v & 0x80):
            return result
        shift += 7
    raise ValueError("corrupt RAR archive (bad varint)")


def _rar5_entries(f, start):
    """List a RAR 5.x archive. Header layout per the RAR 5.0
    format: CRC32, header size (varint), header type, header
    flags, then the type's fields. The flags varint IS the file
    flags -- there is no second flags field. File header:
    unpacked size, attributes, [mtime if flags&0x02], [data CRC32
    if flags&0x04], compression info, host OS, name length, name,
    extra area size, extra area, [data size if flags&0x01]."""
    entries = []
    f.seek(start)
    seen_main = False
    saw_encryption = False
    while True:
        crc = f.read(4)
        if len(crc) < 4:
            break
        try:
            header_size = _rar5_varint_file(f)
        except ValueError:
            if saw_encryption:
                raise ValueError(
                    "encrypted RAR archive -- file names are encrypted, "
                    "listing unavailable")
            raise
        if header_size < 2 or header_size > (1 << 26):
            raise ValueError("corrupt RAR archive (bad header size)")
        header = f.read(header_size)
        if len(header) < header_size:
            raise ValueError("truncated RAR archive")
        try:
            htype, pos = _rar5_varint(header, 0)
            flags, pos = _rar5_varint(header, pos)
        except ValueError:
            if saw_encryption:
                raise ValueError(
                    "encrypted RAR archive -- file names are encrypted, "
                    "listing unavailable")
            raise
        if htype == 1:  # main header
            seen_main = True
            continue
        if htype == 5:  # end of archive
            break
        if htype == 4:  # encryption header: remember it, keep going
            saw_encryption = True  # -p archives still list; -hp fails below
            continue
        if htype not in (2, 3):  # unknown block: cannot skip its data
            break
        if not seen_main:
            raise ValueError(
                "not a readable RAR archive (it may use header encryption)")
        try:
            unp_size, pos = _rar5_varint(header, pos)
            attr, pos = _rar5_varint(header, pos)
            if flags & 0x02:
                pos += 4  # file modification time
            if flags & 0x04:
                pos += 4  # data CRC32
            _comp, pos = _rar5_varint(header, pos)  # compression info
            _host_os, pos = _rar5_varint(header, pos)
            name_len, pos = _rar5_varint(header, pos)
            if pos + name_len > len(header):
                raise ValueError("corrupt RAR archive (short file name)")
            raw_name = header[pos:pos + name_len]
            pos += name_len
            try:
                name = raw_name.decode("utf-8")
            except UnicodeDecodeError:
                name = raw_name.decode("utf-8", errors="replace")
            _extra_size, pos = _rar5_varint(header, pos)
            data_size = 0
            if flags & 0x01:
                data_size, pos = _rar5_varint(header, pos)
        except ValueError as exc:
            if saw_encryption:
                raise ValueError(
                    "encrypted RAR archive -- file names are encrypted, "
                    "listing unavailable")
            raise
        if htype == 2:  # file header (3 == service header: not listed)
            is_dir = bool(attr & 0x10) or name.endswith(("/", "\\"))
            entries.append({"name": name, "size": unp_size,
                            "is_dir": is_dir})
        f.seek(data_size, 1)
        if len(entries) >= _ARCHIVE_MAX_ENTRIES:
            break
    if not seen_main:
        raise ValueError("not a readable RAR archive")
    return entries


def archive_to_entries(path):
    """List a .zip or .rar archive: [{"name", "size", "is_dir"}].
    Raises ValueError with a human-readable reason for corrupt /
    encrypted / unsupported archives."""
    low = path.lower()
    if low.endswith(".zip"):
        try:
            with zipfile.ZipFile(path) as z:
                infos = z.infolist()
        except Exception as exc:  # noqa: BLE001 - BadZipFile etc.
            raise ValueError("could not read this ZIP file (%s)"
                             % _archive_err(exc))
        entries = []
        for info in infos:
            name = info.filename
            entries.append({"name": name, "size": info.file_size,
                            "is_dir": info.is_dir() or name.endswith("/")})
            if len(entries) >= _ARCHIVE_MAX_ENTRIES:
                break
        return entries
    if low.endswith(".rar"):
        with open(path, "rb") as f:
            # SFX stubs: the signature may sit up to 1 MB in.
            head = f.read(1024 * 1024)
            off5 = head.find(_RAR5_SIG)
            off4 = head.find(_RAR4_SIG)
            if off5 != -1 and (off4 == -1 or off5 <= off4):
                return _rar5_entries(f, off5 + len(_RAR5_SIG))
            if off4 != -1:
                return _rar4_entries(f, off4 + len(_RAR4_SIG))
            raise ValueError(
                "not a RAR archive (signature not found -- it may be corrupt)")
    raise ValueError("only .zip and .rar archives can be listed")


_ARCHIVE_EXTRACT_MAX = 200 * 1024 * 1024  # never extract >200 MB


def archive_extract_entry(path, entry):
    """Extract ONE entry from an archive into a fresh temp dir and
    return the extracted file's path. ZIP only, via stdlib
    zipfile -- RAR has no stdlib decompressor (the bundled
    parsers only LIST headers), so RAR entries raise a clear
    ValueError instead of a crash. The entry must name a real
    non-directory entry of the archive, with no absolute path
    or ".." segment (Zip Slip guard); the extracted path stays
    jailed under the fresh temp dir. The caller owns the temp
    dir (the desktop open-path flow leaves it for the OS temp
    cleaner; the bytes flow deletes it after serving)."""
    low = path.lower()
    if not low.endswith(".zip"):
        if low.endswith(".rar"):
            raise ValueError(
                "RAR entries can't be opened directly -- download "
                "the archive to open this file")
        raise ValueError(
            "only .zip entries can be opened directly -- download "
            "the archive to open this file")
    if not entry or entry.startswith(("/", "\\")) or \
            "\x00" in entry:
        raise ValueError("that file cannot be opened from this archive")
    parts = entry.replace("\\", "/").split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ValueError("that file cannot be opened from this archive")
    try:
        with zipfile.ZipFile(path) as z:
            infos = {info.filename: info for info in z.infolist()}
    except Exception as exc:  # noqa: BLE001 - BadZipFile etc.
        raise ValueError("could not read this ZIP file (%s)"
                         % _archive_err(exc))
    info = infos.get(entry)
    if info is None:
        # ZIPs sometimes store a "./" prefix; match that too.
        alt = "./" + entry
        info = infos.get(alt)
        if info is not None:
            entry = alt
    if info is None or info.is_dir() or entry.endswith("/"):
        raise ValueError("that file is not in this archive")
    if info.file_size > _ARCHIVE_EXTRACT_MAX:
        raise ValueError("that file is too large to open from this archive")
    tmpdir = tempfile.mkdtemp(prefix="drop-extract-")
    target = os.path.join(tmpdir, *parts)
    base = os.path.abspath(tmpdir)
    if os.path.commonpath([base, os.path.abspath(target)]) != base:
        raise ValueError("that file cannot be opened from this archive")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    try:
        with zipfile.ZipFile(path) as z:
            with z.open(info, "r") as src, open(target, "wb") as dst:
                while True:
                    chunk = src.read(65536)
                    if not chunk:
                        break
                    dst.write(chunk)
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        raise ValueError("could not extract this file (%s)"
                         % _archive_err(exc))
    return target


def doc_to_text(path: str):
    """Extract the main text of a legacy Word 97-2003 .doc file
    using only the stdlib (CFB container + FIB + piece table).

    Returns the clean text, or None if the file can't be parsed.
    Clean (non-fast-saved) files store the text as one run at
    fcMin (FIB offset 0x18) of ccpText chars (FIB offset 0x4C);
    fast-saved files (fComplex) need the piece table in the
    1Table stream (fcClx, FibRgFcLcb entry 32, located via the
    csw/cswNew counts so no absolute offset is assumed). A
    UTF-16LE run-scan of the WordDocument stream is the last
    resort for files whose FIB values don't check out.
    """
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    wd = _cfb_read_stream(data, "WordDocument")
    if not wd or len(wd) < 0x60:
        return None
    if struct.unpack_from("<H", wd, 0)[0] not in (0xA5EC, 0xA5DC):
        return None
    f_complex = (wd[10] >> 2) & 1
    fc_min = struct.unpack_from("<I", wd, 0x18)[0]
    ccp_text = struct.unpack_from("<I", wd, 0x4C)[0]

    def _decode_piece(fc, nchars, compressed):
        if compressed:
            if fc + nchars > len(wd):
                return None
            return wd[fc:fc + nchars].decode("latin-1", "replace")
        if fc + nchars * 2 > len(wd):
            return None
        return wd[fc:fc + nchars * 2].decode("utf-16-le", "replace")

    def _looks_like_text(t):
        if not t or not t.strip():
            return False
        printable = sum(1 for ch in t
                        if ch.isprintable() or ch in "\r\n\t\x07\x0b")
        return printable / max(1, len(t)) > 0.85

    text = None
    if f_complex:
        try:
            csw = struct.unpack_from("<H", wd, 0x20)[0]
            rgw_end = 0x22 + csw * 2
            csw_new = struct.unpack_from("<H", wd, rgw_end)[0]
            fclcb_start = rgw_end + 2 + csw_new * 4
            fc_clx, lcb_clx = struct.unpack_from(
                "<II", wd, fclcb_start + 32 * 8)
            tbl = _cfb_read_stream(data, "1Table")
            if tbl and fc_clx and lcb_clx and fc_clx + lcb_clx <= len(tbl):
                clx = tbl[fc_clx:fc_clx + lcb_clx]
                i = 0
                if clx and clx[0] == 0x01:
                    ln = struct.unpack_from("<H", clx, 1)[0]
                    i = 1 + 2 + ln
                if i < len(clx) and clx[i] == 0x02:
                    i += 1
                    rest = len(clx) - i
                    n = (rest - 4) // 12
                    if n > 0:
                        cps = struct.unpack_from("<%dI" % (n + 1), clx, i)
                        pieces = []
                        ok = True
                        for k in range(n):
                            fc_raw = struct.unpack_from(
                                "<I", clx,
                                i + (n + 1) * 4 + k * 8)[0]
                            piece = _decode_piece(
                                fc_raw & 0x3FFFFFFF, cps[k + 1] - cps[k],
                                bool(fc_raw & 0x40000000))
                            if piece is None:
                                ok = False
                                break
                            pieces.append(piece)
                        if ok:
                            text = "".join(pieces)
        except Exception:  # noqa: BLE001 - fall through to single piece
            text = None
    if text is None and 0 < ccp_text <= 1000000 and fc_min < len(wd):
        # Single-piece (clean) file: try UTF-16LE first, then ANSI.
        cand = _decode_piece(fc_min, ccp_text, False)
        if cand is not None and _looks_like_text(cand):
            text = cand
        else:
            cand = _decode_piece(fc_min, ccp_text, True)
            if cand is not None and _looks_like_text(cand):
                text = cand
    if text is None:
        # Last resort: longest printable UTF-16LE run in the stream.
        best, cur = "", ""
        for off in range(0, len(wd) - 1, 2):
            ch = wd[off:off + 2].decode("utf-16-le", "replace")
            if ch.isprintable() or ch in "\r\n\t":
                cur += ch
            else:
                if len(cur) > len(best):
                    best = cur
                cur = ""
        if len(cur) > len(best):
            best = cur
        text = best if len(best.strip()) >= 10 else None
    if text is None:
        return None
    cleaned = _doc_clean_text(text)
    return cleaned if cleaned.strip() else None


def unique_path(directory: str, name: str) -> str:
    base, ext = os.path.splitext(name)
    candidate = os.path.join(directory, name)
    i = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{base} ({i}){ext}")
        i += 1
    return candidate


def parse_multipart(body: bytes, boundary: bytes):
    """Yield (filename, content) for file parts. Binary-safe."""
    files = []
    for part in body.split(b"--" + boundary):
        if part in (b"", b"--\r\n", b"--", b"\r\n"):
            continue
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"--"):
            part = part[:-2]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        head, sep, content = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        m = re.search(r'filename="([^"]*)"', head.decode("latin-1", "replace"))
        if m:
            files.append((safe_name(m.group(1)), content))
    return files


def _qr_connect_url(server) -> str:
    """URL encoded in the QR code: the one a phone browser can
    actually open. v2.8.12: server.url is
    http://<name>.local:<port>/, but .local (mDNS) does not
    resolve in most phone browsers (Android Chrome never
    resolves .local; iOS is flaky), so scanning it gave "this
    site can't be reached" even though the server was up. The
    LAN IP URL is directly reachable on the same WiFi, so the
    QR encodes that instead. The address NAME display is
    untouched (top pill / sidebar still show the name, and
    server.url stays .local for the API/startup print); only
    the encoded QR payload changes."""
    port = server.server_address[1]
    return "http://%s:%d/" % (lan_ip(), port)


def qr_png(url: str) -> bytes:
    """PNG bytes of a QR code for url. Raises if qrcode/Pillow missing."""
    import io

    img = qrcode.make(url, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    server_version = f"Drop/{VERSION}"

    def log_message(self, fmt, *args):  # quieter logs
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # -- helpers ---------------------------------------------------------
    def _send(self, code, body: bytes, ctype="text/html; charset=utf-8", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        items = headers.items() if isinstance(headers, dict) else (headers or [])
        for k, v in items:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode(), "application/json",
                   {"Cache-Control": "no-store"})

    def _send_file(self, path, name, ctype, download=True):
        """Serve a file with Range support (video thumbnails, seeking)."""
        size = os.path.getsize(path)
        start, end, code = 0, size - 1, 200
        rh = self.headers.get("Range")
        if rh:
            m = re.match(r"bytes=(\d*)-(\d*)\s*$", rh)
            if m:
                s, e = m.groups()
                if s:
                    start = int(s)
                    end = int(e) if e else size - 1
                elif e:
                    start = max(0, size - int(e))
                end = min(end, size - 1)
                if 0 <= start <= end < size:
                    code = 206
                else:
                    start, end = 0, size - 1
        length = end - start + 1
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if code == 206:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        if download:
            self.send_header("Content-Disposition", 'attachment; filename="%s"' % name)
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(65536, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    # -- routes ----------------------------------------------------------
    # ---------------------------------------------------------- routes
    def _cfg(self):
        try:
            mt = os.path.getmtime(_config_path())
        except OSError:
            mt = 0
        cache = getattr(self, "_cfg_cache", None)
        if cache is None or cache[0] != mt:
            self._cfg_cache = (mt, _load_config())
        return self._cfg_cache[1]

    def _bridge_host(self):
        """True only when the request carries the server's own
        in-memory desktop host token (X-Drop-Host), delivered to the
        pywebview window solely via its local JS bridge. LAN guests
        have no bridge and therefore no way to obtain it; a wrong or
        missing token is simply not host proof. Compared in constant
        time. Never log or return this token."""
        tok = (self.headers.get("X-Drop-Host") or "").strip()
        expect = getattr(self.server, "host_token", "") or ""
        return bool(tok and expect) and hmac.compare_digest(tok, expect)

    def _is_host(self):
        # Loopback (including the IPv6-mapped loopback form, which
        # the other loopback checks in this file already include but
        # this one did not) OR a valid desktop bridge token. Either
        # alone proves the request comes from this PC's own window;
        # neither is a client-asserted "host" flag, which would be
        # forgeable by any LAN browser.
        return (self.client_address[0] in
                ("127.0.0.1", "::1", "::ffff:127.0.0.1")
                or self._bridge_host())

    # ------------------------------------------------- host / guest
    # (v2.7.86, user decision Nov 1, 2026): the PC running the server
    # is the HOST; every phone/web client over the LAN is a GUEST.
    # Guests may USE the link (send/download files, view files and
    # notes, search, transcribe) and must log in when a password is
    # set, but they may never REDEFINE it: changing the link name,
    # setting/removing the password, changing the link folder,
    # revealing the saved password, or revoking sessions are
    # host-only, enforced here on the server, never by hiding buttons.
    #   * every login token is stamped at issue time with a role:
    #     "host" when issued to the PC itself (localhost, desktop
    #     bridge) and "guest" otherwise. The incoming drop_locked
    #     cookie is deliberately IGNORED here: a successful login
    #     IS the unlock that clears that cookie, so stamping the
    #     new token "guest" just because the browser still sent the
    #     old cookie (v2.7.86 bug) locked the host out of its own
    #     admin forever -- every later login re-sent the cookie
    #     and re-stamped "guest", so setlink / sessions /
    #     linkpassword all 403d while files still worked.
    #     Legacy tokens with no stamp fall back to the request's
    #     origin (localhost + not locked = host, else guest).
    #   * a privileged endpoint additionally requires a host ORIGIN:
    #     the request must come from localhost without the
    #     drop_locked cookie. A host token replayed from a LAN device
    #     is still a guest request; a guest token presented on the PC
    #     itself is still denied by its stamp. Both checks must pass.
    #   * v2.7.88: the desktop pywebview window is ALSO host when it
    #     presents the server's in-memory host token (X-Drop-Host),
    #     obtained only via its local JS bridge (see make_server and
    #     Api.host_token). This covers the window even if its page
    #     was loaded via a LAN IP / .local name instead of loopback.
    #     No API, page, QR code, or config ever reveals that token
    #     to a LAN client, so a guest cannot forge it.
    #   * switching a guest's OWN connection to a different link
    #     (connect-to, /api/connect) is NOT an admin act and stays
    #     open to guests; only redefining the host's link is blocked.
    _HOST_ONLY_MSG = ("Only the host can change this "
                      "- change it on the desktop")

    def _session(self):
        tok = self._token()
        if not tok:
            return None, ""
        cfg = self._cfg()
        sess = (cfg.get("sessions") or {}).get(tok)
        return (sess if isinstance(sess, dict) else None), tok

    def _effective_role(self):
        """'host' / 'guest' / None (unauthenticated for admin)."""
        # v2.7.89 GUEST-ONLY LOCK: the drop_locked cookie is ignored
        # here entirely. A successful login IS the unlock, and a
        # host must never be demoted by a stale cookie. A
        # guest-stamped session stays "guest" even when presented
        # from localhost (that is how a LAN guest is simulated in
        # tests, and how a host token replayed from a phone would
        # behave); a host-stamped session stays "host".
        # v2.7.88: a valid desktop bridge token overrides a stale
        # guest-stamped session. The desktop window may hold a token
        # minted while it was wrongly treated as a guest (the
        # v2.7.87 bug); the bridge token proves the request really
        # comes from the host window, so it, not the old stamp, wins.
        if self._bridge_host():
            return "host"
        sess, _ = self._session()
        if sess is not None:
            role = sess.get("role")
            if role in ("host", "guest"):
                return role
            return "host" if self._is_host() else "guest"
        if self._is_host():
            return "host"
        return None

    def _require_host(self):
        """True when this request is a host admin request. The gate
        already rejected unauthenticated callers; a guest (stamped
        guest, or a non-localhost origin) gets the host-only 403.
        v2.7.89: no drop_locked-cookie check -- the host is never
        blocked by that cookie for its own use/admin."""
        if self._effective_role() != "host":
            return False
        return self._is_host()

    def _can_perm(self, name):
        """One of the six v2.7.99 permissions for the caller.
        Host always; anyone else (guest session, tokenless LAN
        caller) only when the current address's set allows it."""
        if self._is_host() and self._effective_role() != "guest":
            return True
        return bool(_address_permissions(self._cfg()).get(name, False))

    def _can_delete_notes(self):
        """Note deletion permission (v2.7.99: the per-address
        delete_notes permission; host always)."""
        return self._can_perm("delete_notes")

    def _can_delete_files(self):
        """File deletion permission (v2.7.99: the per-address
        delete_files permission; host always)."""
        return self._can_perm("delete_files")

    def _host_only_denied(self):
        self._json({"ok": False, "error": self._HOST_ONLY_MSG,
                    "code": "host_only"}, 403)

    def _clear_guest_sessions(self, cfg):
        """Drop every guest-stamped (or legacy un-stamped) session,
        keep host sessions. Changing the password or the link must
        log guests out; the host stays signed in via its own token
        or the localhost bypass. Returns how many were dropped."""
        sess = dict(cfg.get("sessions") or {})
        kept = {t: s for t, s in sess.items()
                if isinstance(s, dict) and s.get("role") == "host"}
        dropped = len(sess) - len(kept)
        cfg["sessions"] = kept
        # v2.7.92 disconnect-all fix: the device count is IP-based
        # (_seen_ips), so dropping sessions alone left "Devices
        # Connected" up until the 20s TTL expired -- and a
        # disconnected guest's polls re-registered its IP. Clear
        # the seen set here, and _note_seen (below) only counts
        # authed callers, so revoked guests cannot resurrect it.
        with _seen_lock:
            _seen_ips.clear()
        with _session_seen_lock:
            _session_seen.clear()
        return dropped

    def _sessions_list(self):
        # v2.7.90: the HOST is excluded from the device list (and
        # count) -- a host session here used to inflate "Devices
        # connected" and list the PC itself as a device.
        # v2.8.11: only LIVE guest sessions (active within the
        # live window) -- this list and the /api/status count
        # share this one source of truth, so the pill and the
        # dropdown can never disagree, and a stale session ages
        # out of both at the same time.
        cfg = self._cfg()
        _, mine = self._session()
        _live = _live_guest_tokens(cfg)
        out = []
        for tok, s in (cfg.get("sessions") or {}).items():
            if tok not in _live:
                continue
            if not isinstance(s, dict):
                continue
            role = s.get("role")
            if role not in ("host", "guest"):
                role = "guest"
            if role == "host":
                continue
            _ip_str = str(s.get("ip") or "")
            _host_str = _resolve_hostname(_ip_str) if _ip_str else ""
            _disp_name = (_clean_device_name(s.get("device_name") or "")
                          or _host_str
                          or _clean_device_name(s.get("ua_hint") or "")
                          or _ip_str)
            out.append({"id": str(tok)[:12], "_ts_sort": int(s.get("ts") or 0),
                        "role": role,
                        "ip": _ip_str,
                        "device_name": _clean_device_name(
                            s.get("device_name") or ""),
                        "ua_hint": _clean_device_name(
                            s.get("ua_hint") or ""),
                        "hostname": _host_str,
                        "display_name": _disp_name,
                        "link": str(s.get("link") or ""),
                        "address": str(s.get("link") or ""),
                        "ts": int(s.get("ts") or 0),
                        "self": tok == mine})
        out.sort(key=lambda e: e["ts"], reverse=True)
        # v2.8.7: no duplicates after a link change / reconnect.
        # Same device reconnecting mints a new token; keep only
        # the newest session per (ip, display identity).
        _seen_keys = set()
        _deduped = []
        for _e in out:
            _k = (str(_e.get("ip") or "").lower(),
                  str(_e.get("display_name") or "").lower())
            if _k in _seen_keys:
                continue
            _seen_keys.add(_k)
            _deduped.append(_e)
        for _e in _deduped:
            _e.pop("_ts_sort", None)
        return _deduped

    def _token(self):
        t = (self.headers.get("X-Drop-Token") or "").strip()
        if t:
            return t
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "drop_sess":
                return v.strip()
        # v2.7.90 download bearer: set by do_GET from the query
        # string of /dl/, /thumb/ and /api/notes/dl ONLY (see
        # _download_bearer). DownloadManager-style clients cannot
        # send cookies or X-Drop-Token, so a guest's own session
        # token may travel as ?token=<token> on those three paths;
        # it is validated exactly like a header/cookie token
        # (link binding + role) by _profile, and grants nothing
        # beyond what that token already grants.
        return getattr(self, "_query_token", "") or ""

    def _download_bearer(self, query):
        """Extract a session token from a download URL's query
        string (?token= / ?drop_sess= / ?dl_token=). Only called
        for /dl/, /thumb/ and /api/notes/dl; other paths never
        accept a token in the URL."""
        for part in query.split("&"):
            k, _, v = part.partition("=")
            if k in ("token", "drop_sess", "dl_token") and v:
                return urllib.parse.unquote(v)
        return ""

    def _locked_cookie(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "drop_locked" and v.strip() == "1":
                return True
        return False

    def _profile(self):
        # Single collection, always "default". Authed when: a valid
        # session token exists, OR no link password is set, OR the
        # caller is the PC host. v2.7.89 GUEST-ONLY LOCK: the host
        # bypass ignores both the guest lock and the drop_locked
        # cookie -- the host is never locked out of its own link.
        # A guest token is valid only when it is bound to the
        # current link AND (not guest-locked, or stamped with the
        # current lock sequence, i.e. minted by re-authenticating
        # after the lock). Locking clears guest sessions, so the
        # sequence check is belt-and-braces for any pre-lock token
        # that survives. A tokenless guest on a passwordless link
        # is authed only while NOT guest-locked.
        # v2.7.85 link binding: a client that declares its link
        # (X-Drop-Link, sent by the web page and the APK) is denied
        # outright when that link is not the server's CURRENT link --
        # before the token, unlocked-link and host fallbacks.
        if getattr(self, "_prof_cache", None) is not None:
            return self._prof_cache or None
        cfg = self._cfg()
        prof = None
        declared = ((self.headers.get("X-Drop-Address") or
                     self.headers.get("X-Drop-Link") or "").strip())
        if declared and _sanitise_address(declared) != _current_address(cfg):
            _tok0 = self._token()
            _sess0 = (cfg.get("sessions") or {}).get(_tok0)
            _host_proven = self._bridge_host() or (
                isinstance(_sess0, dict)
                and _sess0.get("role") == "host"
                and self._is_host())
            if not _host_proven:
                self._prof_cache = False
                return None
        tok = self._token()
        sess = (cfg.get("sessions") or {}).get(tok)
        if tok and isinstance(sess, dict):
            # A token is bound to the link it was issued for. Tokens
            # issued before v2.7.84 carry no "link" key; they stay
            # valid for the current link until a link change clears
            # all sessions (see /api/setlink).
            if sess.get("link") is None or \
                    sess.get("link") == _current_address(cfg):
                role = sess.get("role")
                if role == "host":
                    prof = "default"
                elif role == "guest":
                    # v2.7.90: guest-lock is retired, so the lock
                    # sequence no longer gates anything. A guest
                    # token is valid when bound to the current
                    # link; the password gate (tokenless callers
                    # below) and link binding are the only gates.
                    prof = "default"
                elif self._is_host():
                    prof = "default"
                elif not _guest_locked(cfg):
                    prof = "default"
            elif sess.get("role") != "guest" and self._is_host():
                # v2.7.86: a stale token must not lock the HOST out
                # of its own PC. A GUEST-stamped stale token is
                # denied even when presented from localhost (that
                # is how LAN guests are simulated in tests); only
                # a host (or legacy un-stamped) token falls back
                # to the host bypass here. A declared stale
                # X-Drop-Link still denies before this point.
                prof = "default"
        elif not _address_locked(cfg):
            # v2.7.90: no password gate on an open link, and no
            # guest-lock gate any more (retired). A caller that
            # DECLARES a stale link was already refused above, so
            # a tokenless caller with no declared link on an open
            # link is a new guest, not a stale one auto-following
            # a link change (the web guest pager additionally
            # refuses to adopt a changed link -- see PAGE).
            if self._is_host():
                prof = "default"
            elif not self._token():
                prof = "default"
            else:
                # A token was presented but matched no session
                # (revoked/disconnected): on an open link the web
                # guest pager treats this as disconnected and
                # shows its login page; the server must not
                # silently re-auth it as a new guest, or a
                # disconnected guest would auto-reconnect.
                # (Tokenless callers take the branch above.)
                prof = None
        elif self._is_host():
            prof = "default"
        self._prof_cache = prof or False
        return prof

    def _dir(self):
        if not self._profile():
            return ""
        d = _address_folder(self._cfg()) or \
            getattr(self.server, "directory", "")
        if d:
            try:
                os.makedirs(d, exist_ok=True)
            except OSError:
                pass
        return d

    def _pid(self):
        return _address_notes_pid(self._cfg())

    def _ai_dir(self):
        return _data_dir()

    def _gate(self):
        if self._profile() is not None:
            return True
        self._json({"ok": False, "need_auth": True}, 401)
        return False

    def do_GET(self):
        path, _, query = self.path.partition("?")
        # v2.7.90: a download bearer in the URL is accepted ONLY
        # on the download paths (see _download_bearer) -- /dl/,
        # /thumb/, /api/notes/dl and /api/archive/ (v2.8.33 (8)).
        if path in ("/api/notes/dl",) or path.startswith(
                ("/dl/", "/thumb/", "/api/archive/")):
            self._query_token = self._download_bearer(query)
        else:
            self._query_token = ""
        # v2.7.92: only authed callers count as devices. Counting
        # every request (even 401s) let a disconnected guest's
        # polls resurrect "Devices Connected" after disconnect-all.
        # (Checked here, AFTER the bearer token is set, so the
        # cached profile the gate reuses stays correct.)
        self._prof_cache = None
        if self._profile() is not None:
            _note_seen(self.client_address[0])
            _note_session_seen(self._session()[1])
        if path not in ("/", "/qr.png", "/manifest.json", "/icon.png",
                        "/logo.png",
                        "/api/authstate", "/api/addressinfo") \
                and not self._gate():
            return
        if path == "/":
            qr_block = (
                '<div class="qr"><img src="/qr.png" alt="QR code">'
                "<div>Scan with your<br>phone camera</div></div>"
                if HAS_QR else ""
            )
            qr_mini = '<img src="/qr.png" alt="QR code">' if HAS_QR else ""
            desktop = getattr(self.server, "desktop", False)
            # A phone browser hitting the desktop app's server still needs the
            # mobile header (Saved button) - the desktop flag is server-global.
            _ua = (self.headers.get("User-Agent") or "").lower()
            _mobile = ("mobi" in _ua or "android" in _ua or "iphone" in _ua or "ipad" in _ua)
            if desktop and not _mobile:
                # Desktop: one button row under the header - Open | Change | Delete all
                file_head = ""
                file_btns = (
                    '<div class="fbtnrow">'
                    # v2.8.39 (8): "+ Add New" on the Files tab --
                    # the Shared Texts button's design, copied
                    # exactly (btn primary + the same plus icon +
                    # "Add New"). Web PC only: the desktop app
                    # hides it (see the html.pcapp rule) and keeps
                    # Open / Change / Delete exactly. On web PC
                    # Open / Change are hidden (2.8.39 (3)), so
                    # the row reads Add New + Delete. It opens the
                    # file picker and uploads, like the Upload
                    # tab's chooser (see #fileaddbtn wiring).
                    '<button class="btn primary" id="fileaddbtn" data-tip="Add files from this PC"><svg viewBox="0 0 24 24" fill="none" stroke="#052e33" stroke-width="2.5" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg> Add New</button>'
                    '<button class="btn openf" id="openfolder" data-tip="Open the save folder on this PC"><svg viewBox="0 0 24 24" fill="#052e33"><path d="M10 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8l-2-2z"/></svg> Open</button>'
                    '<button class="btn changef" id="changefolder" data-tip="Change the save folder for this address"><svg viewBox="0 0 24 24" fill="none" stroke="#ffffff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/></svg> Change</button>'
                    # v2.8.29 (8): the desktop Delete button gets its
                    # trash icon BACK (Essef Nov 6) -- this supersedes
                    # the 2.8.25 text-only revert below. Icon + "Delete"
                    # text, as 2.8.5 had it ("icons before text", Essef
                    # Nov 3): the same trash-2 _SVG_TRASH the mobile
                    # icon-only button uses. Label ("Delete"), colour,
                    # size and position are untouched; Open / Change
                    # keep their icons byte-identical.
                    # (2.8.25 note, kept for history: the trash icon
                    # 2.8.5 added was reverted to text-only -- before
                    # 2.8.5 the button had no icon (v2.7.93 round9:
                    # text only, "Delete files", no trash icon), and
                    # the trash-2 SVG itself never changed.)
                    '<button class="btn dangergrad" id="delallbtn" style="display:none" data-tip="Delete files">' + _SVG_TRASH + ' Delete</button>'
                    "</div>"
                )
            else:
                # Mobile web keeps the stacked Delete all / Saved buttons in the header
                file_head = (
                    '<span style="flex:1"></span><span class="fstack">'
                    '<button class="btn dangergrad iconbtn" id="delallbtn" style="display:none" data-tip="Delete files">' + _SVG_TRASH + '</button>'
                    '<button class="msavedbtn" id="msavedbtn"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> Saved</button>'
                    "</span>"
                )
                file_btns = ""
            _disp = self._cfg().get("address_name") or ""
            # v2.7.89: the served page must never embed the host's
            # save path for a non-host request (an authed guest
            # refreshing the page used to get it here via _dir()).
            # The "they land in" line itself is also stripped for
            # guests, not merely hidden: a guest must not see the
            # host's save-destination line at all, even in source.
            _is_host_req = (self._is_host() and
                            self._effective_role() != "guest")
            _dirname = self._dir() if _is_host_req else ""
            # v2.7.94 top pill: link icon + the address name in
            # its deterministic text colour, no dot, no prefix
            # prefix. The JS copy fallback keeps a plain-text
            # placeholder (__ADDRESSNAME_TEXT__) so copying never
            # copies markup.
            _addr_html = ("Not connected" if not _disp else
                          _SVG_LINK + '<span class="addname" style="color:' +
                          address_text_color(_current_address(self._cfg())) +
                          '">' + html.escape(_disp) + "</span>")
            page = (
                PAGE.replace("__VERSION__", VERSION)
                .replace("__URL__", html.escape(self.server.url))
                .replace("__ADDRESSNAME__", _addr_html)
                .replace("__ADDRESSNAME_TEXT__",
                         html.escape(_disp or "Not connected"))
                .replace("__DIRNAME__", html.escape(_dirname))
                .replace("__QR__", qr_block)
                .replace("__QRMINI__", qr_mini)
                .replace("__FILEHEAD__", file_head)
                .replace("__FILEBTNS__", file_btns)
            )
            # v2.8.39 (7): guest-served pages keep the "or click
            # to browse" line (same .small style as D) and strip
            # ONLY the host-only destination span (#landline-dir
            # -- "they land in:" + the dir name). The old code
            # stripped the whole #landline div, so web guests
            # saw no browse line at all (photo image-78). The
            # host path still never reaches a guest page.
            if not _is_host_req:
                page = re.sub(
                    r'<span id="landline-dir">.*?</span></span>',
                    "", page, count=1, flags=re.S)
            self._send(200, page.encode(), headers={"Cache-Control": "no-store"})
        elif path == "/qr.png":
            try:
                _qr_url = _qr_connect_url(self.server)
                self._send(200, qr_png(_qr_url), "image/png",
                    {"Cache-Control": "no-store"})
            except Exception:  # noqa: BLE001 - qrcode/Pillow not installed
                self._send(404, b"qr unavailable", "text/plain")
        elif path == "/manifest.json":
            self._send(200, json.dumps({
                "name": "Drop",
                "short_name": "Drop",
                "description": "Send files between your phone and PC over WiFi",
                "start_url": "/",
                "display": "standalone",
                "background_color": "#0a0e1a",
                "theme_color": "#0a0e1a",
                "icons": [{"src": "/icon.png", "sizes": "512x512", "type": "image/png"}],
            }).encode(), "application/manifest+json")
        elif path == "/icon.png":
            p = asset_path("icon.png")
            if p:
                with open(p, "rb") as f:
                    self._send(200, f.read(), "image/png")
            else:
                self._send(404, b"no icon", "text/plain")
        elif path == "/logo.png":
            # v2.8.13: Essef's correct Drop logo — blue droplet
            # with WHITE WIFI ARCS above the document (NOT the
            # sparkle version, which was the wrong file in 2.8.12).
            # Byte copy of icon.png, resize-and-fit only.
            # Fallback: icon.png is the SAME artwork, byte for
            # byte — older frozen builds never bundled logo.png
            # (build.bat only added icon.png), so /logo.png 404'd
            # and the web header showed a broken image + alt text.
            # The fallback keeps the logo loading on those builds.
            p = asset_path("logo.png")
            if not p:
                p = asset_path("icon.png")
            if p:
                with open(p, "rb") as f:
                    self._send(200, f.read(), "image/png")
            else:
                self._send(404, b"no logo", "text/plain")
        elif path == "/api/addressinfo":
            # v2.7.92 real-time open-address detection (web login
            # page). Answers, WITHOUT authenticating as the address
            # and WITHOUT leaking any password, whether a typed
            # address is this PC's current address and whether its
            # gate is locked. Unknown / mistyped addresses answer
            # known:false (never a password hint). The locked fact
            # is already public via /api/authstate, so this leaks
            # nothing new; it only scopes it to the typed name.
            cfg = self._cfg()
            want = ""
            for part in query.split("&"):
                k, _, v = part.partition("=")
                if k in ("address", "link", "name"):
                    want = urllib.parse.unquote(v)
            cur = _current_address(cfg)
            if not want or not cur or \
                    _sanitise_address(want) != cur:
                # v2.8.39 (5a): also answer for a KNOWN (history /
                # registry) address, so a guest's address list can
                # show that address's password state -- the
                # current-only answer left every older row stuck at
                # "No Password Saved". Same shape and same no-leak
                # rule as the current-address branch: unknown /
                # mistyped names still answer known:false, and only
                # the locked/open fact is revealed (no password).
                _wk = _sanitise_address(want) if want else ""
                _went = _address_registry(cfg).get(_wk) \
                    if _wk else None
                _whist = [e for e in _address_history(cfg)
                          if e["key"] == _wk] if _wk else []
                if not _wk or (_went is None and not _whist):
                    self._json({"ok": False, "known": False})
                else:
                    self._json({"ok": True, "known": True,
                                "address": (_whist[0]["name"]
                                            if _whist else _wk),
                                "address_key": _wk,
                                "has_password": bool(
                                    isinstance(_went, dict)
                                    and _went.get("pass")),
                                "needs_password":
                                    _entry_locked(cfg, _wk)})
            else:
                self._json({"ok": True, "known": True,
                            "address": cfg.get("address_name") or "",
                            "address_key": cur,
                            # has_password: a password is stored for
                            # this address. needs_password: connecting
                            # currently requires it (the lock gate is
                            # on). An unlocked address with a stored
                            # password needs no password to connect.
                            "has_password": _has_stored_password(cfg),
                            "needs_password": _address_locked(cfg)})
        elif path == "/api/authstate":
            cfg = self._cfg()
            authed = self._profile() is not None
            perms = _address_permissions(cfg)
            out = {"ok": True, "locked": _address_locked(cfg),
                   "guest_locked": False,
                   "guest_delete_allowed": _guest_delete_allowed(cfg),
                   "guest_notes_delete_allowed":
                       _guest_notes_delete_allowed(cfg),
                   "permissions": perms,
                   "can_download_files": (True
                   if self._is_host() and
                   self._effective_role() != "guest"
                   else perms["download_files"]) if authed else False,
                   "can_upload_files": (True
                   if self._is_host() and
                   self._effective_role() != "guest"
                   else perms["upload_files"]) if authed else False,
                   "can_add_notes": (True
                   if self._is_host() and
                   self._effective_role() != "guest"
                   else perms["add_notes"]) if authed else False,
                   "can_star_notes": (True
                   if self._is_host() and
                   self._effective_role() != "guest"
                   else perms["star_notes"]) if authed else False,
                   "can_delete_files": self._can_delete_files()
                   if authed else False,
                   "can_delete_notes": self._can_delete_notes()
                   if authed else False,
                   "separate_folders": _separate_folders_enabled(cfg),
                   "main_folder": _root_folder(cfg),
                   "authed": authed, "host": self._is_host(),
                   # v2.8.0: tokenless open guest -- authed by the
                   # passwordless fallback, but with NO session,
                   # so it appears in Devices only as a bare IP
                   # (seen-IPs) instead of a device name. The web
                   # page uses this flag to call /api/connect
                   # once, which mints a session stamped with
                   # the UA hint (Android model / iPhone / etc),
                   # so open guests show a name like password
                   # guests do. Revoked-token callers are NOT
                   # flagged (their _profile is None), so a
                   # disconnected guest is never silently
                   # re-registered by this path.
                   "sessionless_open": bool(
                       authed and not self._token()
                       and not _address_locked(cfg)
                       and not self._is_host()),
                   "role": self._effective_role(),
                   # kept for older clients; the collection is always
                   # the single default link collection in v2.7.83+
                   "profile": {"id": "default", "name": "Default"},
                   "address_name": cfg.get("address_name") or "",
                   "link_name": cfg.get("address_name") or "",
                   # v2.7.85: display name (as typed) vs folder/mDNS
                   # key (lowercase), plus the server's ACTUAL port
                   # (runtime, never a hard-coded default) so clients
                   # never have to guess it.
                   "address_key": _current_address(cfg),
                   "link_key": _current_address(cfg),
                   "port": self.server.server_address[1],
                   "url": getattr(self.server, "url", ""),
                   # v2.8.29 (3): the URL a phone browser can
                   # actually open -- the SAME http://<LAN IP>:<port>/
                   # the QR code encodes (see _qr_connect_url). The
                   # "url" above stays the .local display form, which
                   # most phone browsers cannot resolve, so copy
                   # buttons must use this one, never "url".
                   "connect_url": _qr_connect_url(self.server)}
            if authed:
                # v2.7.89: the host PC path is HOST-ONLY. A guest
                # must never be told where files land on the host's
                # filesystem, so guests get no "folder" key at all
                # (their screens show no path field or path text).
                # Unauthed callers do not get the PC path either.
                if self._is_host() and \
                        self._effective_role() != "guest":
                    out["folder"] = self._dir()
                out["link_folder"] = bool(_current_address(cfg))
            if self._is_host():
                out["has_password"] = _has_stored_password(cfg)
                # v2.8.36: a retrievable encrypted copy exists for
                # the current address (False for hash-only).
                out["password_saved"] = _password_saved_for(
                    cfg, _current_address(cfg))
                out["root"] = str(cfg.get("directory") or "")
                out["legacy_spaces"] = _legacy_space_count(cfg)
            self._json(out)
        elif path.startswith("/thumb/"):
            name = safe_name(urllib.parse.unquote(path[len("/thumb/"):]))
            path = os.path.join(self._dir(), name)
            if not os.path.isfile(path) or not _is_image(name):
                self._send(404, b"not found", "text/plain")
            else:
                made = _thumbnail(path)
                if made is None:
                    self._send(404, b"unreadable", "text/plain",
                               headers={"Cache-Control": "no-store"})
                else:
                    data, ctype = made
                    self._send(200, data, ctype,
                               headers={"Cache-Control": "no-store"})
        elif path == "/api/linkpassword":
            # v2.7.86 HOST-ONLY reveal: a guest must never get the
            # host's saved password through this endpoint, even when
            # authed (guests reveal only a password they typed
            # themselves, on their own device). The gate above already
            # rejected unauthed callers with 401.
            if not self._require_host():
                self._host_only_denied()
                return
            cfg = self._cfg()
            # v2.7.90: ?link=<key> reveals a SAVED (history) link's
            # password from its registry entry, host only; without
            # it, the current link's password (as before).
            want = ""
            for part in query.split("&"):
                k, _, v = part.partition("=")
                if k in ("link", "address"):
                    want = urllib.parse.unquote(v)
            if want:
                entry = _address_registry(cfg).get(want) or {}
                pw = _decrypt_pw(entry.get("pass_enc") or "")
                if pw is None and not entry.get("pass"):
                    self._json({"ok": False, "error": "not_found"}, 404)
                elif pw is None:
                    self._json({"ok": False,
                                "error": "not_retrievable"})
                else:
                    self._json({"ok": True, "password": pw})
                return
            if not cfg.get("address_pass"):
                self._json({"ok": True, "password": ""})
            else:
                pw = _decrypt_pw(cfg.get("address_pass_enc") or "")
                if pw is None:
                    link = _current_address(cfg)
                    entry = _address_registry(cfg).get(link) or {}
                    pw = _decrypt_pw(entry.get("pass_enc") or "")
                if pw is None:
                    self._json({"ok": False,
                                "error": "not_retrievable"})
                else:
                    self._json({"ok": True, "password": pw})
        elif path == "/api/linkhistory":
            # v2.7.90 HOST-ONLY: saved links. Passwords are NEVER
            # returned here -- only has_password (dots in the UI);
            # the eye reveal fetches one password at a time via
            # /api/linkpassword?link=<key>, host only.
            if not self._require_host():
                self._host_only_denied()
                return
            cfg = self._cfg()
            reg = _address_registry(cfg)
            entries = []
            for e in _address_history(cfg):
                ent = reg.get(e["key"]) or {}
                entries.append({"name": e["name"], "key": e["key"],
                                "has_password": bool(ent.get("pass")),
                                # v2.8.36: "locked" = the gate is
                                # active for this entry;
                                # "password_saved" = a retrievable
                                # encrypted copy exists (hash-only
                                # passwords report False here).
                                "locked": _entry_locked(cfg, e["key"]),
                                "password_saved":
                                    _password_saved_for(cfg, e["key"])})
            self._json({"ok": True, "entries": entries})
        elif path == "/api/files":
            items = []
            names = [n for n in os.listdir(self._dir())
                     if os.path.isfile(os.path.join(self._dir(), n))]
            names.sort(key=lambda n: os.path.getmtime(os.path.join(self._dir(), n)),
                       reverse=True)
            ai_map = {}
            try:
                import dropit_ai
                # v2.8.41: warm the index in the BACKGROUND as
                # soon as the page loads -- a search must never
                # be the thing that builds it (see search_files).
                # Single-flight no-op when already indexed or
                # already building; returns at once.
                dropit_ai._ensure_background_build(
                    self._dir(), self._ai_dir())
                for name in names:
                    # v2.8.40: tri-state AI verdict -- (has_text,
                    # known). "ai" keeps its exact old meaning;
                    # "ai_known" tells the client the verdict is
                    # durable, so a known text-less file never
                    # spins or re-scans on reload / address switch.
                    ai_map[name] = dropit_ai.ai_state(
                        self._dir(), self._ai_dir(), name)
            except Exception:  # noqa: BLE001 - AI optional
                pass
            for name in names:
                fp = os.path.join(self._dir(), name)
                _ai = ai_map.get(name) or (False, False)
                items.append({"name": name,
                              "size": os.path.getsize(fp),
                              "mtime": int(os.path.getmtime(fp)),
                              "ai": bool(_ai[0]),
                              "ai_known": bool(_ai[1])})
            self._json(items)
        elif path == "/api/notes":
            with _notes_lock:
                notes = load_notes(self._pid())
            for n in notes:
                n["label"] = note_label(n.get("text") or "")
            self._json(notes)
        elif path == "/api/status":
            # v2.8.11: count AND names come from the SAME live
            # guest-session list (_sessions_list) -- never from
            # _seen_ips (which counted bare traffic) plus a
            # separately-built name list (which appended bare IPs
            # as names). The pill and the dropdown now agree by
            # construction, on desktop/web and on the APK.
            live = self._sessions_list()
            self._json({"devices": len(live),
                        "device_names": [e.get("display_name", "")
                                         for e in live],
                        "devices_list": [{"display_name": e.get("display_name", ""),
                                          "device_name": e.get("display_name", "")}
                                         for e in live]})
        elif path == "/api/permissions":
            # v2.7.99: the CURRENT address's six permissions, for
            # any authed caller (the do_GET gate above already
            # 401s unauthed callers). Guests read their own
            # address's set so their controls can grey correctly.
            cfg = self._cfg()
            self._json({"ok": True,
                        "address": _current_address(cfg),
                        "permissions": _address_permissions(cfg)})
        elif path == "/api/sessions":
            # v2.7.86 HOST-ONLY device/session list. Full tokens are
            # never returned, only a 12-char id prefix per session.
            if not self._require_host():
                self._host_only_denied()
                return
            self._json({"ok": True, "sessions": self._sessions_list()})
        elif path == "/api/reveal/last":
            # v2.8.20 (9): HOST-ONLY read-back of the last
            # /api/reveal attempt (name / path / argv / ok /
            # error) -- the frozen windowed build has nowhere to
            # print stderr, so a dead "Show in folder" click is
            # diagnosed from this record instead of guessing.
            if not self._require_host():
                self._host_only_denied()
                return
            self._json({"ok": True,
                        "last_reveal": getattr(self.server,
                                               "last_reveal", None)})
        elif path == "/api/aisearch":
            q = ""
            for part in query.split("&"):
                k, _, v = part.partition("=")
                if k == "q":
                    q = urllib.parse.unquote(v)
            try:
                import dropit_ai
                # v2.8.1: bounded search -- a stalled backend must
                # answer "timeout" instead of spinning the Search
                # indicator forever (see search_files_timed).
                self._json(dropit_ai.search_files_timed(
                    self._dir(), self._ai_dir(), q))
            except Exception:  # noqa: BLE001 - AI optional, never break server
                self._json({"ok": False, "results": [], "message": "error"})
        elif path == "/api/aistatus":
            try:
                import dropit_ai
                st = dropit_ai.index_status(self._dir(), self._ai_dir())
                st["ok"] = True
                self._json(st)
            except Exception:  # noqa: BLE001 - AI optional
                self._json({"ok": False})
        elif path == "/api/aicheck":
            # on-demand text check for one file (drives the AI scan spinner)
            name = ""
            for part in query.split("&"):
                k, _, v = part.partition("=")
                if k == "name":
                    name = urllib.parse.unquote(v)
            try:
                import dropit_ai
                fp = os.path.join(self._dir(), name)
                if not os.path.isfile(fp):
                    self._json({"ok": False, "has_text": False})
                else:
                    self._json({"ok": True, "has_text": bool(
                        dropit_ai.file_has_text(
                            self._dir(), self._ai_dir(), name))})
            except Exception:  # noqa: BLE001 - AI optional
                self._json({"ok": False, "has_text": False})
        elif path == "/api/aiocr":
            name = ""
            for part in query.split("&"):
                k, _, v = part.partition("=")
                if k == "name":
                    name = urllib.parse.unquote(v)
            try:
                import dropit_ai
                res = dropit_ai.ocr_image(self._dir(), name,
                                            self._ai_dir())
                # translate button only shows for foreign text
                if res.get("ok") and res.get("text"):
                    try:
                        import dropit_mt
                        res["lang"] = dropit_mt.detect_lang(res["text"])
                    except Exception:  # noqa: BLE001 - AI optional
                        res["lang"] = None
                self._json(res)
            except Exception:  # noqa: BLE001 - AI optional
                self._json({"ok": False, "text": "", "message": "error"})
        elif path == "/api/aifiletext":
            # unified text for any file: OCR for images, extraction for docs
            name = ""
            for part in query.split("&"):
                k, _, v = part.partition("=")
                if k == "name":
                    name = urllib.parse.unquote(v)
            try:
                import dropit_ai
                fp = os.path.join(self._dir(), name)
                if not os.path.isfile(fp):
                    self._json({"ok": False, "text": "",
                                "message": "not_found"})
                else:
                    # full text, paragraph breaks preserved for readability
                    text = dropit_ai.full_text(fp, self._ai_dir())
                    text = re.sub(r"[ \t]+", " ", text)
                    text = re.sub(r"\n{3,}", "\n\n", text).strip()
                    if text:
                        self._json({"ok": True, "text": text,
                                    "message": "ok"})
                    else:
                        self._json({"ok": False, "text": "",
                                    "message": "no_text"})
            except Exception:  # noqa: BLE001 - AI optional
                self._json({"ok": False, "text": "", "message": "error"})
        elif path == "/api/aifileinfo":
            # {has_text, lang} — drives the AI popup (translate grey-out)
            name = ""
            for part in query.split("&"):
                k, _, v = part.partition("=")
                if k == "name":
                    name = urllib.parse.unquote(v)
            try:
                import dropit_ai
                import dropit_mt
                has = dropit_ai.ai_eligible(
                    self._dir(), self._ai_dir(), name)
                lang = None
                if has:
                    fp = os.path.join(self._dir(), name)
                    if os.path.isfile(fp):
                        text = dropit_ai.extract_text(fp)
                        text = re.sub(r"\s+", " ", text).strip()[:2000]
                        if text:
                            lang = dropit_mt.detect_lang(text)
                self._json({"ok": True, "has_text": has, "lang": lang})
            except Exception:  # noqa: BLE001 - AI optional
                self._json({"ok": False, "has_text": False, "lang": None})
        elif path == "/api/notes/dl":
            # v2.7.99: note downloads obey download_files.
            if not self._can_perm("download_files"):
                self._json({"ok": False,
                            "error": _PERM_MESSAGES["download_files"],
                            "code": "download_forbidden"}, 403)
                return
            qs = query
            nid = ""
            for part in qs.split("&"):
                k, _, v = part.partition("=")
                if k == "id":
                    nid = urllib.parse.unquote(v)
            with _notes_lock:
                notes = load_notes(self._pid())
            note = next((n for n in notes if n.get("id") == nid), None)
            if note is None:
                self._send(404, b"not found", "text/plain")
                return
            body = (note["text"] + "\n").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition",
                             'attachment; filename="shared-text-%s.txt"' % nid)
            self.end_headers()
            self.wfile.write(body)
        elif path.startswith("/api/docx/"):
            # v2.8.14: Word preview for BOTH .docx and legacy .doc.
            # .docx renders as HTML (docx_to_html); .doc extracts
            # plain text (doc_to_text, stdlib CFB+FIB) wrapped in
            # <pre> so the preview window shows it cleanly. The
            # route name stays /api/docx/ so the APK and the saved
            # viewer keep working unchanged. Preview is view-only
            # (like PDF/image/text preview): no download_files
            # check here, matching the 2.8.12 preview rule.
            qs = query
            name = ""
            for part in qs.split("&"):
                k, _, v = part.partition("=")
                if k == "name":
                    name = urllib.parse.unquote(v)
            name = safe_name(name)
            low = name.lower()
            if not (low.endswith(".docx") or low.endswith(".doc")):
                self._send(404, b"not found", "text/plain")
                return
            fpath = os.path.join(self._dir(), name)
            if not os.path.isfile(fpath):
                self._send(404, b"not found", "text/plain")
                return
            if low.endswith(".docx"):
                converted = docx_to_html(fpath)
            else:
                text = doc_to_text(fpath)
                converted = ("<pre>" + html.escape(text) + "</pre>"
                             if text else None)
            if not converted:
                self._send(500, b"cannot preview", "text/plain")
                return
            self._send(200, converted.encode("utf-8"), "text/html; charset=utf-8")
        elif path.startswith("/api/xlsx/"):
            # v2.8.22 (8): Excel preview -- the first sheet as an
            # HTML table (xlsx_to_html), same view-only preview
            # rule as /api/docx/ (no download_files check here).
            qs = query
            name = ""
            for part in qs.split("&"):
                k, _, v = part.partition("=")
                if k == "name":
                    name = urllib.parse.unquote(v)
            name = safe_name(name)
            low = name.lower()
            if not low.endswith(".xlsx"):
                self._send(404, b"not found", "text/plain")
                return
            fpath = os.path.join(self._dir(), name)
            if not os.path.isfile(fpath):
                self._send(404, b"not found", "text/plain")
                return
            converted = xlsx_to_html(fpath)
            if not converted:
                self._send(500, b"cannot preview", "text/plain")
                return
            self._send(200, converted.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/archive/extract/":
            # v2.8.34 (4): open ONE file from inside an archive.
            #   GET /api/archive/extract/?file=<archive>&entry=<name>
            #     -> the extracted file's bytes (attachment
            #        download), for web guests -- the web
            #        equivalent of opening it directly.
            #   ...&mode=path -> {"ok": true, "path": <temp path>}
            #     HOST-ONLY: the desktop preview calls this and
            #     hands the path to the bridge open_path, so
            #     Windows opens it in its selected app. A server
            #     path is never handed to a LAN guest.
            # ZIP extracts with stdlib zipfile (see
            # archive_extract_entry); RAR cannot be extracted
            # without an external extractor, so it answers a
            # clear 400 instead of a crash. Extracting a
            # file's CONTENT is a download, so the bytes mode
            # enforces download_files like /dl/ (the listing
            # stays view-only). A guest token may travel as
            # ?token= like /api/archive/ (same bearer rule).
            qs = query
            name = ""
            entry = ""
            mode = ""
            for part in qs.split("&"):
                k, _, v = part.partition("=")
                if k in ("file", "name"):
                    name = urllib.parse.unquote(v)
                elif k == "entry":
                    entry = urllib.parse.unquote(v)
                elif k == "mode":
                    mode = urllib.parse.unquote(v)
            name = safe_name(name)
            low = name.lower()
            if not (low.endswith(".zip") or low.endswith(".rar")):
                self._json({"ok": False,
                            "error": ("only .zip and .rar archives can be "
                                      "opened")}, 400)
                return
            fpath = os.path.join(self._dir(), name)
            if not os.path.isfile(fpath):
                self._json({"ok": False, "error": "not found"}, 404)
                return
            if mode == "path" and not self._require_host():
                self._host_only_denied()
                return
            if mode != "path" and not self._can_perm("download_files"):
                self._json({"ok": False,
                            "error": _PERM_MESSAGES["download_files"],
                            "code": "download_forbidden"}, 403)
                return
            try:
                target = archive_extract_entry(fpath, entry)
            except ValueError as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
                return
            except OSError:
                self._json({"ok": False,
                            "error": "could not read this file"}, 400)
                return
            if mode == "path":
                self._json({"ok": True, "path": target})
                return
            base = os.path.basename(target)
            ctype = (mimetypes.guess_type(base)[0]
                     or "application/octet-stream")
            try:
                self._send_file(target, base, ctype, download=True)
            finally:
                try:
                    os.remove(target)
                    os.rmdir(os.path.dirname(target))
                except OSError:
                    pass
        elif path.startswith("/api/archive/"):
            # v2.8.33 (8): archive LISTING -- what is inside a .zip
            # / .rar (names, sizes, folders), for the web + PC
            # preview and for the APK:
            #   GET /api/archive/?file=<url-encoded file name>
            #   -> {"ok": true, "entries": [{"name": ..., "size": ...,
            #       "is_dir": false}, ...]}
            #   -> {"ok": false, "error": ...} on failure (400 for
            #       a bad extension / corrupt / encrypted archive,
            #       404 for a missing file, 401 when unauthed).
            # View-only preview rule, like /api/docx/ and
            # /api/xlsx/: an authed caller may list even without
            # download_files -- the preview's Download button
            # still enforces it. A guest token may travel as
            # ?token= (same bearer rule as /dl/) or via the
            # X-Drop-Token header / drop_sess cookie, exactly
            # like the other preview endpoints. Listing only:
            # no extraction in this build.
            qs = query
            name = ""
            for part in qs.split("&"):
                k, _, v = part.partition("=")
                if k in ("file", "name"):
                    name = urllib.parse.unquote(v)
            name = safe_name(name)
            low = name.lower()
            if not (low.endswith(".zip") or low.endswith(".rar")):
                self._json({"ok": False,
                            "error": ("only .zip and .rar archives can be "
                                      "listed")}, 400)
                return
            fpath = os.path.join(self._dir(), name)
            if not os.path.isfile(fpath):
                self._json({"ok": False, "error": "not found"}, 404)
                return
            try:
                entries = archive_to_entries(fpath)
            except ValueError as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
                return
            except OSError:
                self._json({"ok": False, "error": "could not read this file"},
                           400)
                return
            self._json({"ok": True, "entries": entries})
        elif path == "/api/mtpacks":
            try:
                import dropit_mt
                packs = dropit_mt.pack_info(self._ai_dir())
                self._json({"ok": True, "packs": packs,
                            "total_bytes": sum(p["bytes"] for p in packs)})
            except Exception:  # noqa: BLE001 - AI optional
                self._json({"ok": False}, 500)
        elif path.startswith("/dl/"):
            # v2.7.99: file downloads obey download_files.
            # v2.8.12: preview (?preview=1) is view-only and
            # stays available WITHOUT download_files -- the
            # preview window streams inline for display, and
            # its Download button greys client-side. The plain
            # download still 403s below.
            _is_preview = "preview=1" in query.split("&")
            if not _is_preview and not self._can_perm("download_files"):
                self._json({"ok": False,
                            "error": _PERM_MESSAGES["download_files"],
                            "code": "download_forbidden"}, 403)
                return
            name = safe_name(urllib.parse.unquote(path[len("/dl/"):]))
            path = os.path.join(self._dir(), name)
            if not os.path.isfile(path):
                self._send(404, b"not found", "text/plain")
                return
            ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
            self._send_file(path, name, ctype, download=not _is_preview)
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        # v2.7.92: see do_GET -- only authed callers count.
        self._prof_cache = None
        if self._profile() is not None:
            _note_seen(self.client_address[0])
            _note_session_seen(self._session()[1])
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length") or 0)
        ctype = self.headers.get("Content-Type") or ""
        self._prof_cache = None
        if path not in ("/api/login", "/api/logout",
                        "/api/connect") and not self._gate():
            return

        if path == "/api/connect":
            # v2.7.86 guest CONNECT-TO: a guest switching its own
            # connection to a link. This changes NOTHING on the host
            # (no link/password/folder change); it only verifies that
            # the named link IS the host's current link, so a clean
            # name like "10-30-99" connects to that link's files and
            # a stale/wrong name is refused instead of silently
            # showing another link's files. Open to guests (no gate).
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                data = {}
            cfg = self._cfg()
            # v2.7.89 IDENTICAL validation on guest connect as on
            # host setlink: dots/forbidden characters are REJECTED
            # with 400 invalid_link_name -- never sanitised into a
            # hyphen form that would silently connect to a
            # different link, and never accepted from a client
            # bypass. Empty is rejected the same way.
            raw_wanted = str(data.get("link") or
                             data.get("address") or "").strip()
            ok_name, name_err = _validate_address_name(raw_wanted)
            if not ok_name:
                self._json({"ok": False, "error": name_err,
                            "code": "invalid_link_name"}, 400)
                return
            wanted = _sanitise_address(raw_wanted)
            cur = _current_address(cfg)
            if wanted != cur:
                self._json({"ok": False,
                            "error": ("That is not this PC's address "
                                      "- check the address on the PC"),
                            "code": "wrong_link",
                            "address_name": cfg.get("address_name") or "",
                            "link_name": cfg.get("address_name") or "",
                            "locked": _address_locked(cfg)}, 409)
            else:
                # v2.8.33 (Essef Nov 6): the "authed" answer here
                # must NOT depend on the X-Drop-Address header.
                # _profile() refuses any declared address that is
                # not the current one -- right for file endpoints,
                # but this endpoint's whole job is verifying that
                # the link named in the BODY is the current one,
                # which was just checked (wanted == cur). A phone
                # page loaded before the PC changed its address
                # still declares the OLD address, so _profile()
                # returned None here even AFTER a successful login
                # had just minted a valid guest token for the new
                # address: Connect answered authed:false and the
                # page showed "Couldn't connect to this address"
                # with the right name and the right password
                # (reproduced live, round48). So authed is computed
                # from the token itself, bound to the current link,
                # plus the same host bypass and tokenless-open
                # fallback _profile() applies -- everything except
                # the declared-header gate, which this endpoint
                # has already superseded by checking the body.
                _ctok = self._token()
                _csess = ((cfg.get("sessions") or {}).get(_ctok)
                          if _ctok else None)
                _ctok_ok = (isinstance(_csess, dict)
                            and (_csess.get("link") is None
                                 or _csess.get("link") == cur))
                _cauthed = bool(_ctok_ok or self._is_host()
                                or (not _address_locked(cfg)
                                    and not _ctok))
                out = {"ok": True, "link": cur, "address": cur,
                       "display_link": cfg.get("address_name") or "",
                       "display_address": cfg.get("address_name") or "",
                       "locked": _address_locked(cfg),
                       "authed": _cauthed}
                if out["authed"]:
                    out["message"] = ("Connected to " +
                                      (cfg.get("address_name") or cur))
                if out["authed"]:
                    # v2.7.89 HOST-ONLY folder: guests connect
                    # without ever learning the host's save folder.
                    if self._is_host() and \
                            self._effective_role() != "guest":
                        out["folder"] = self._dir()
                    # v2.7.87: a connect that leaves no session behind
                    # is invisible to the host's device list -- that
                    # was the "2 Devices Connected but no devices
                    # shown" gap (status counts seen IPs, sessions
                    # only listed login tokens). So an authed
                    # connect WITHOUT a valid token for this link
                    # mints a session token (guest on LAN, host on
                    # the PC), returned in the body and as a cookie,
                    # exactly like a login. A caller that already
                    # holds a valid token reuses it (no duplicates).
                    # Locked + unauthed callers mint nothing.
                    # v2.7.99 ROOT CAUSE FIX: this mint used to sit
                    # inside `if ... self._is_host()`, so a LAN guest
                    # that was already authed (open address, no token
                    # yet -- authed via the passwordless fallback)
                    # never got a session: counted via seen IPs but
                    # invisible in /api/sessions. The mint now runs
                    # for ANY authed caller without a valid token;
                    # the role stamp (host on the PC, guest on LAN)
                    # is what keeps host sessions out of the device
                    # count/list, not the mint gate.
                    tok = self._token()
                    sess = (cfg.get("sessions") or {}).get(tok)
                    valid = isinstance(sess, dict) and (
                        sess.get("link") is None
                        or sess.get("link") == cur)
                    if not valid:
                        newtok = secrets.token_urlsafe(32)
                        sessd = dict(cfg.get("sessions") or {})
                        sessd[newtok] = {
                            "ts": int(time.time()), "link": cur,
                            "role": ("host" if self._is_host()
                                     and self._effective_role() !=
                                     "guest"
                                     else "guest"),
                            "lock_seq": _guest_lock_seq(cfg),
                            "ip": self.client_address[0],
                            **_session_device_fields(self, data)}
                        if len(sessd) > 50:
                            for old_tok, _ in sorted(
                                    sessd.items(),
                                    key=lambda kv: kv[1].get("ts", 0)
                                    )[:len(sessd) - 50]:
                                sessd.pop(old_tok, None)
                        cfg["sessions"] = sessd
                        _save_config(cfg)
                        out["token"] = newtok
                        self._send(200, json.dumps(out).encode(),
                                   "application/json",
                                   headers=[("Set-Cookie",
                                             "drop_sess=" + newtok +
                                             "; Path=/; HttpOnly; "
                                             "SameSite=Lax; "
                                             "Max-Age=31536000")])
                    else:
                        _df = _session_device_fields(self, data)
                        if _df:
                            _upd = dict(cfg.get("sessions") or {})
                            if tok in _upd and isinstance(_upd[tok], dict):
                                _upd[tok].update(_df)
                                cfg["sessions"] = _upd
                                _save_config(cfg)
                        self._json(out)
                elif not out["authed"] and not out["locked"]:
                    # v2.7.90: an EXPLICIT connect to an OPEN link
                    # (the guest typed the link on its login page,
                    # or the host re-saved) mints a fresh session
                    # token for the caller, even when its old token
                    # was revoked by a disconnect. This is NOT
                    # auto-follow: the caller had to name the
                    # current link, and a password link never mints
                    # here (login first, above). Without this, a
                    # disconnected guest on an open link could never
                    # reconnect -- login with no password fails,
                    # and connect returned authed False forever.
                    newtok = secrets.token_urlsafe(32)
                    sessd = dict(cfg.get("sessions") or {})
                    sessd[newtok] = {
                        "ts": int(time.time()), "link": cur,
                        "role": ("host" if self._is_host()
                                 else "guest"),
                        "lock_seq": _guest_lock_seq(cfg),
                        "ip": self.client_address[0],
                        **_session_device_fields(self, data)}
                    if len(sessd) > 50:
                        for old_tok, _ in sorted(
                                sessd.items(),
                                key=lambda kv: kv[1].get("ts", 0)
                                )[:len(sessd) - 50]:
                            sessd.pop(old_tok, None)
                    cfg["sessions"] = sessd
                    _save_config(cfg)
                    out["authed"] = True
                    out["token"] = newtok
                    out["message"] = ("Connected to " +
                                      (cfg.get("address_name") or cur))
                    self._send(200, json.dumps(out).encode(),
                               "application/json",
                               headers=[("Set-Cookie",
                                         "drop_sess=" + newtok +
                                         "; Path=/; HttpOnly; "
                                         "SameSite=Lax; "
                                         "Max-Age=31536000")])
                else:
                    _df2 = _session_device_fields(self, data)
                    if _df2:
                        _tok2 = self._token()
                        _upd2 = dict(cfg.get("sessions") or {})
                        if _tok2 in _upd2 and isinstance(_upd2[_tok2], dict):
                            _upd2[_tok2].update(_df2)
                            cfg["sessions"] = _upd2
                            _save_config(cfg)
                    self._json(out)
        elif path == "/api/login":
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                data = {}
            cfg = self._cfg()
            pw = str(data.get("password") or "")
            ok = False
            if cfg.get("address_pass") and _check_pw(pw, cfg["address_pass"]):
                ok = True
                # Opportunistic upgrade: a password proven correct at
                # login gains its encrypted copy, so the eye icon can
                # reveal even a legacy hash-only password afterwards.
                if not cfg.get("address_pass_enc"):
                    enc = _encrypt_pw(pw)
                    cfg["address_pass_enc"] = enc
                    link0 = _current_address(cfg)
                    if link0:
                        _address_entry(cfg, link0)["pass_enc"] = enc
            elif not cfg.get("address_pass"):
                # Legacy migration: a pre-v2.7.83 profile/space password
                # unlocks once and is adopted as the link password, so
                # an existing password keeps working under the new model.
                for old in _legacy_passwords(cfg):
                    if _check_pw(pw, old):
                        cfg["address_pass"] = old
                        link = _current_address(cfg)
                        if link:
                            _address_entry(cfg, link)["pass"] = old
                        ok = True
                        break
            if not ok:
                self._json({"ok": False, "error": "Wrong password"})
            else:
                tok = secrets.token_urlsafe(32)
                sess = dict(cfg.get("sessions") or {})
                # v2.7.86: stamp the token's role at issue time.
                sess[tok] = {"ts": int(time.time()),
                             "link": _current_address(cfg),
                             "role": ("host" if self._is_host()
                                      else "guest"),
                             "lock_seq": _guest_lock_seq(cfg),
                             "ip": self.client_address[0],
                             **_session_device_fields(self, data)}
                if len(sess) > 50:
                    for old_tok, _ in sorted(sess.items(),
                                             key=lambda kv: kv[1].get("ts", 0))[:len(sess) - 50]:
                        sess.pop(old_tok, None)
                cfg["sessions"] = sess
                _save_config(cfg)
                body = json.dumps({
                    "ok": True, "token": tok,
                    "display_link": cfg.get("address_name") or "",
                    "display_address": cfg.get("address_name") or "",
                    "message": ("Connected to " +
                                (cfg.get("address_name") or ""))}).encode()
                # Login clears drop_locked (set on logout) so the PC
                # host is auto-authed again until it locks explicitly.
                self._send(200, body, "application/json",
                           headers=[("Set-Cookie", "drop_sess=" + tok +
                                     "; Path=/; HttpOnly; SameSite=Lax; Max-Age=31536000"),
                                    ("Set-Cookie", "drop_locked=; Path=/; Max-Age=0")])
        elif path == "/api/logout":
            tok = self._token()
            if tok:
                cfg = self._cfg()
                sess = dict(cfg.get("sessions") or {})
                if tok in sess:
                    del sess[tok]
                    cfg["sessions"] = sess
                    _save_config(cfg)
            self._send(200, json.dumps({"ok": True}).encode(),
                       "application/json",
                       headers=[("Set-Cookie", "drop_sess=; Path=/; Max-Age=0"),
                                ("Set-Cookie", "drop_locked=1; Path=/; Max-Age=31536000")])
        elif path == "/api/setlinkpassword":
            # Set (or, with an empty password, remove) the link password.
            # v2.7.86 HOST-ONLY: a guest may use a password, never set
            # or remove the host's. The password itself is stored
            # hashed (for verification) plus locally encrypted (so the
            # host eye icon can reveal it); it is never stored as bare
            # plaintext -- see _set_address_password.
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                data = {}
            if self._profile() is None:
                self._json({"ok": False, "error": "need_auth"}, 401)
            elif not self._require_host():
                self._host_only_denied()
            else:
                cfg = self._cfg()
                pw = str(data.get("password") or "")
                # v2.8.36: optional save_password (default True,
                # preserves old behaviour for other callers). False
                # + non-empty pw stores the hash only and still
                # locks; empty pw clears and unlocks either way.
                save = data.get("save_password", True)
                save = False if save is False else True
                _set_address_password(cfg, _current_address(cfg), pw,
                                      save=save)
                _address_entry(cfg, _current_address(cfg))["locked"] = bool(pw)
                # A new password must not leave old GUEST sessions
                # connected: every guest re-authenticates with the new
                # password (the PC host stays authed via its own
                # session or the host bypass). This is the ONLY
                # case in v2.7.90 where a previously open-connected
                # guest sees a locked/password page: the link it
                # was on suddenly gained a password.
                self._clear_guest_sessions(cfg)
                _remember_address(cfg, cfg.get("address_name") or "",
                               _current_address(cfg))
                _save_config(cfg)
                self._json({"ok": True, "locked": bool(pw),
                            "display_link": cfg.get("address_name") or "",
                            "display_address": cfg.get("address_name") or "",
                            "message": ("Connected to " +
                                        (cfg.get("address_name") or ""))})
        elif path in ("/api/linkname", "/api/setlink"):
            # v2.7.86 HOST-ONLY again (reversing the v2.7.85 opening):
            # redefining the host's link is a host act. Guests connect
            # to the host's link with /api/connect instead of
            # redefining it here; a guest that calls this gets 403
            # with the host-only message even when authenticated.
            # (The v2.7.85 opening was the dead end in reverse: it let
            # any authed phone rename the PC's link and folder.)
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                data = {}
            if not self._require_host():
                self._host_only_denied()
                return
            raw_name = str(data.get("name") or "").strip()
            ok_name, name_err = _validate_address_name(raw_name)
            if not ok_name:
                self._json({"ok": False, "error": name_err,
                            "code": "invalid_link_name"}, 400)
                return
            name = _sanitise_address(raw_name)
            cfg = self._cfg()
            root = str(cfg.get("directory")
                       or getattr(self.server, "directory", ""))
            old_link = _current_address(cfg)
            had_link = bool(old_link)
            # Password semantics for this one call (v2.7.87, keep
            # vs remove made explicit): an ABSENT password key keeps
            # the link's stored password -- that is what the host
            # web screen sends when Save is pressed with the
            # prefilled saved password untouched. A supplied
            # non-empty password that already matches the current
            # hash is the same keep (no rewrite, no logout). A
            # supplied non-empty password that differs becomes the
            # new password; an explicitly empty password clears it
            # (the host Delete button, or a deliberately cleared
            # field). A brand-new link with no password key gets no
            # password. The APK link screen still always supplies
            # the key, so its empty-field-means-remove behaviour
            # is unchanged there.
            pw_supplied = "password" in data
            pw = str(data.get("password") or "") if pw_supplied else None
            # v2.8.36: optional save_password (default True when
            # absent -- preserves old behaviour for other callers
            # such as the APK). False + non-empty pw stores the
            # hash only (verification) and still locks the gate.
            save_pw = data.get("save_password", True)
            save_pw = False if save_pw is False else True
            entry = _address_entry(cfg, name)
            if old_link == name and not pw_supplied:
                # Re-saving the same link with no password change:
                # nothing moves, nobody is logged out.
                _remember_address(cfg, raw_name, name)
                _save_config(cfg)
                self._json({"ok": True, "url": self.server.url,
                            "link": name, "address": name, "display_link": raw_name, "display_address": raw_name,
                            "folder": _address_folder(cfg),
                            "locked": _address_locked(cfg),
                            "moved": 0, "sessions_cleared": False,
                            "message": "Connected to " + raw_name})
                return
            cur_hash = str(entry.get("pass", "")) \
                if old_link == name else ""
            pw_same_as_current = bool(
                pw_supplied and pw and cur_hash
                and _check_pw(pw, cur_hash))
            if pw_supplied and not pw:
                pw_changed = bool(cur_hash)
            elif pw_supplied:
                pw_changed = not pw_same_as_current
            else:
                pw_changed = False
            name_changed = (name != old_link)
            if pw_supplied and not pw_same_as_current:
                _set_address_password({**cfg, "address_name": raw_name,
                                    "links": _address_registry(cfg)},
                                   name, pw, save=save_pw)
                # _set_address_password mirrored cfg only when the link
                # was already current; for a switch, mirror below.
                entry = _address_registry(cfg)[name]
                # v2.7.92: a supplied password (re)locks the address;
                # an explicitly empty password unlocks it AND clears
                # it (the only clearing path besides the Delete
                # button, which routes here with an empty password).
                entry["locked"] = bool(pw)
            elif pw_supplied and pw_same_as_current and not save_pw:
                # v2.8.36: same password, but the host explicitly
                # unchecked Save Password -- drop the retrievable
                # copy (hash only) while keeping the lock. The
                # password itself is unchanged, so no guest
                # sessions are cleared (pw_changed stays False).
                entry["pass_enc"] = ""
                if name == _current_address(cfg):
                    cfg["address_pass_enc"] = ""
                entry["locked"] = True
            elif name not in _address_registry(cfg) or \
                    "pass" not in _address_registry(cfg)[name]:
                entry["pass"] = ""
                entry["pass_enc"] = ""
            if root:
                cfg["directory"] = root
            new_folder = _address_folder({**cfg, "address_name": raw_name,
                                       "links": _address_registry(cfg)})
            moved = 0
            if root:
                try:
                    os.makedirs(new_folder, exist_ok=True)
                except OSError:
                    pass
                # One-time legacy adoption only: a pre-link shared
                # folder's top-level FILES move into the first link's
                # folder. Switching between links afterwards moves
                # nothing -- each link keeps its own folder.
                if not had_link and not cfg.get("legacy_files_adopted"):
                    try:
                        for fn in os.listdir(root):
                            sp = os.path.join(root, fn)
                            dp = os.path.join(new_folder, fn)
                            if os.path.isfile(sp) \
                                    and not os.path.exists(dp):
                                os.rename(sp, dp)
                                moved += 1
                    except OSError:
                        pass
                    cfg["legacy_files_adopted"] = True
            cfg["address_name"] = raw_name
            cfg["link_folder"] = True
            cfg["address_pass"] = entry.get("pass", "")
            cfg["address_pass_enc"] = entry.get("pass_enc", "")
            # The link IS the connection identity: every old GUEST
            # token dies with the old link (and a host token bound to
            # the old link is refused by _profile's link binding, so
            # it cannot keep serving either). Clients must reconnect
            # through the new link (password prompt if one is set).
            # Old-link clients that declare their link are
            # additionally refused by _profile (see X-Drop-Link), so
            # an unlocked new link does not silently keep serving
            # them either. v2.7.87: guests are cleared ONLY when
            # something actually changed (new name, or a new /
            # removed password) -- a host Save with the prefilled
            # password untouched must NOT disconnect every guest
            # (v2.7.86 cleared unconditionally).
            sessions_cleared = False
            if name_changed or pw_changed:
                self._clear_guest_sessions(cfg)
                sessions_cleared = True
            _adopt_legacy_notes(cfg)
            _remember_address(cfg, raw_name, name)
            _save_config(cfg)
            self.server.address_name = name
            port = self.server.server_address[1]
            self.server.url = "http://%s.local:%d" % (name, port)
            self._json({"ok": True, "url": self.server.url,
                        "link": name, "address": name, "display_link": raw_name, "display_address": raw_name,
                        "folder": _address_folder(cfg),
                        "locked": _address_locked(cfg),
                        "moved": moved,
                        "sessions_cleared": sessions_cleared,
                        "message": "Connected to " + raw_name})
        elif path == "/api/setlinkfolder":
            # Change the save folder for the CURRENT link (v2.7.86
            # HOST-ONLY — the gate above enforced authed, this
            # enforces host). With a link active this sets that
            # link's override and leaves the base root untouched;
            # with no link it moves the base root itself (the old
            # Change-folder behaviour).
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                data = {}
            if not self._require_host():
                self._host_only_denied()
                return
            folder = str(data.get("folder") or "").strip()
            if not folder or not os.path.isabs(folder):
                self._json({"ok": False,
                            "error": "Give a full folder path"})
                return
            try:
                os.makedirs(folder, exist_ok=True)
            except OSError as e:
                self._json({"ok": False, "error": str(e)})
                return
            cfg = self._cfg()
            link = _current_address(cfg)
            # v2.8.31: a per-address folder must be settable
            # regardless of the separate-folders toggle -- the
            # old refusal while OFF blocked Change Folder, and
            # the toggle only decides the default folder, never
            # whether the user may choose one for an address.
            if link:
                _address_entry(cfg, link)["folder"] = folder
            else:
                cfg["directory"] = folder
                self.server.directory = folder
            _save_config(cfg)
            self._json({"ok": True, "folder": _address_folder(cfg)})
        elif path == "/api/setrootfolder":
            # v2.7.96 MENU route (HOST-ONLY): change the ROOT
            # folder only. Per-address folder overrides are left
            # untouched, so an address with an override keeps
            # its own folder; an address without one resolves
            # under the new root (base/<address>/). The Files
            # tab and Set Up dialog never call this -- they use
            # /api/setlinkfolder (address folder) instead.
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                data = {}
            if not self._require_host():
                self._host_only_denied()
                return
            folder = str(data.get("folder") or "").strip()
            if not folder or not os.path.isabs(folder):
                self._json({"ok": False,
                            "error": "Give a full folder path"})
                return
            try:
                os.makedirs(folder, exist_ok=True)
            except OSError as e:
                self._json({"ok": False, "error": str(e)})
                return
            cfg = self._cfg()
            cfg["directory"] = folder
            self.server.directory = folder
            _save_config(cfg)
            self._json({"ok": True, "folder": _root_folder(cfg),
                        "address_folder": _address_folder(cfg)})
        elif path == "/api/separate_folders":
            # v2.8.7: host-only toggle "Create separate folder for
            # each link". ON (default) = per-link subfolders as
            # before. OFF = all links save to the Main Folder, no
            # subfolder creation. v2.8.8: Change Folder is NEVER
            # greyed while OFF. v2.8.31: Change Folder no longer
            # retargets to the Main Folder while OFF -- it always
            # sets the address's own folder (an explicit override
            # wins over the toggle); turning it back ON restores
            # per-link default folders.
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                data = {}
            if not self._require_host():
                self._host_only_denied()
                return
            cfg = self._cfg()
            cfg["separate_folders"] = bool(data.get("enabled", True))
            _save_config(cfg)
            self._json({"ok": True,
                        "separate_folders": _separate_folders_enabled(cfg),
                        "folder": _address_folder(cfg),
                        "main_folder": _root_folder(cfg)})
        elif path == "/api/reveal":
            # v2.8.9 DESKTOP ONLY (host-only): the per-file Open
            # button reveals the file in its folder instead of
            # opening it -- the OS file manager opens with the
            # file selected/highlighted (Windows Explorer
            # /select, macOS Finder -R). Linux has no select
            # verb, so it opens the folder itself. Guests get
            # the host-only denial; a missing file is an error,
            # never a folder open. The name is sanitised and
            # jailed to the current address folder, like open.
            # v2.8.17: Explorer gets the two-item list
            # ["explorer", "/select," + target] -- see
            # Api.reveal_file in app.py: the 2.8.14 verbatim
            # string was the bug (CPython outer-quotes a str
            # arg as one token), and the three-item list was
            # the 2.8.11 bug (space after the comma).
            # v2.8.20 (9): DEVNULL stdio, same as app.py's
            # _spawn() -- the server runs in the same frozen
            # --windowed process, so inheriting its (invalid)
            # std handles fails the spawn the same way. Every
            # attempt is also recorded on server.last_reveal
            # and readable via GET /api/reveal/last.
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                data = {}
            if not self._require_host():
                self._host_only_denied()
                return
            name = safe_name(str(data.get("name") or ""))
            base = os.path.abspath(_address_folder(self._cfg()))
            target = os.path.abspath(os.path.join(base, name))
            rec = {"name": name, "ok": False, "error": "",
                   "path": target, "argv": None}
            self.server.last_reveal = rec
            if not name or not target.startswith(base + os.sep) \
                    or not os.path.isfile(target):
                rec["error"] = "File not found"
                self._json({"ok": False,
                            "error": "File not found"})
                return
            try:
                if sys.platform == "win32":
                    argv = ["explorer", "/select," + target]
                    rec["argv"] = argv
                    subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL,
                                     close_fds=True)
                elif sys.platform == "darwin":
                    argv = ["open", "-R", target]
                    rec["argv"] = argv
                    subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL,
                                     close_fds=True)
                else:
                    argv = ["xdg-open", base]
                    rec["argv"] = argv
                    subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL,
                                     close_fds=True)
            except OSError as e:
                rec["error"] = str(e)
                self._json({"ok": False, "error": str(e)})
                return
            rec["ok"] = True
            self._json({"ok": True})
        elif path == "/api/openlocal":
            # v2.8.40 (5): PC WEB -- open a file FROM PC STORAGE in
            # the PC's default app. The 2.8.39 "real download" was
            # not an open (Essef Nov 7): a download is not an open.
            # A browser page cannot launch a local file itself, but
            # this server RUNS on the PC, so it opens the file the
            # same way the desktop bridge does (Api.open_file in
            # app.py: os.startfile on Windows, open / xdg-open
            # elsewhere). HOST-ONLY, same gate as /api/reveal: the
            # request must come from this PC itself (loopback or
            # bridge token) -- a LAN guest can never make the host
            # PC open a file. The name is sanitised and jailed to
            # the current address folder, like reveal/open. Only
            # for a browser ON the PC (localhost URL or desktop
            # bridge); a PC-web page opened via the LAN address is
            # a guest session, so it falls back to the share sheet
            # (see openSavedFileOS).
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                data = {}
            if not self._require_host():
                self._host_only_denied()
                return
            name = safe_name(str(data.get("name") or ""))
            # Folder resolution MUST match /api/files (see _dir):
            # cfg["directory"] is empty until a Main Folder is
            # picked in the UI, and abspath("") is the process
            # CWD -- resolving against it made openlocal look in
            # the app folder instead of the shared folder on a
            # fresh config (hello.txt "not found" while dropit.py
            # opened). server.directory is the --dir fallback.
            base = os.path.abspath(_address_folder(self._cfg())
                                   or getattr(self.server, "directory", ""))
            target = os.path.abspath(os.path.join(base, name))
            if not name or not target.startswith(base + os.sep) \
                    or not os.path.isfile(target):
                self._json({"ok": False,
                            "error": "File not found"})
                return
            try:
                if sys.platform == "win32":
                    os.startfile(target)  # noqa: S606
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", target],
                                     stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL,
                                     close_fds=True)
                else:
                    subprocess.Popen(["xdg-open", target],
                                     stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL,
                                     close_fds=True)
            except OSError as e:
                self._json({"ok": False, "error": str(e)})
                return
            self._json({"ok": True})
        elif path == "/api/sessions/revoke":
            # v2.7.86 HOST-ONLY: "disconnect this device" ({"id":
            # the 12-char session id from /api/sessions}) or
            # "disconnect all guests" ({"all_guests": true}). The
            # host's own session is never revoked by all_guests.
            # v2.7.90: disconnect ends that guest SESSION ONLY. It
            # never sets any lock state, never bumps a lock
            # sequence, and never blocks reconnection: a
            # disconnected guest reconnects to an unlocked link
            # with no lock screen (explicit /api/connect mints a
            # fresh token) and to a password link via the normal
            # login page.
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                data = {}
            if not self._require_host():
                self._host_only_denied()
                return
            cfg = self._cfg()
            sess = dict(cfg.get("sessions") or {})
            if data.get("all_guests"):
                # v2.7.92 root-cause fix (see _clear_guest_sessions
                # and _profile): revoke-all previously failed
                # outright whenever the host page carried a stale
                # declared-address header (401 from _gate) or was
                # loaded via a LAN address without a bridge token
                # (403 from _require_host), while the sessions list
                # (fetched header-free) still showed the guests --
                # so it LOOKED like disconnect did nothing. The
                # revoke call itself now travels header-free (see
                # postHostJ in PAGE) and host-proven requests bypass
                # the stale-header denial in _profile; and every
                # non-host session is dropped here, on password
                # AND open addresses alike.
                revoked = self._clear_guest_sessions(cfg)
            else:
                sid = str(data.get("id") or "")
                hit = [t for t in sess
                       if sid and len(sid) >= 8 and t.startswith(sid)]
                # v2.8.1: single-device disconnect must drop the
                # device from the Devices count IMMEDIATELY. The
                # pill count is IP-based (_seen_ips, 20s window),
                # so dropping the session alone left the pill
                # (and /api/status) showing the device for up to
                # 20s after Disconnect. Purge exactly the revoked
                # sessions' IPs here (disconnect-all already
                # clears the whole set); a revoked guest that
                # reconnects re-registers via _note_seen, and
                # other devices' IPs are untouched.
                _rev_ips = {str(sess[t].get("ip") or "")
                            for t in hit
                            if isinstance(sess.get(t), dict)}
                for t in hit:
                    sess.pop(t, None)
                    with _session_seen_lock:
                        _session_seen.pop(t, None)
                cfg["sessions"] = sess
                revoked = len(hit)
                _purge_seen_ips(_rev_ips)
            _save_config(cfg)
            self._json({"ok": True, "revoked": revoked,
                        "sessions": self._sessions_list(),
                        "message": ("All guests disconnected" +
                                    ((" \u2014 " + str(revoked) +
                                      " device(s) disconnected")
                                     if data.get("all_guests") else ""))})
        elif path == "/api/addresslock":
            # v2.7.92 HOST-ONLY lock/unlock toggle. Unlocking only
            # flips the gate flag -- the stored password is NEVER
            # cleared here. Locking requires a stored password
            # (first lock, with no password yet, is refused here so
            # the UI shows the password popup instead); re-locking
            # reuses the stored password with no re-entry.
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                data = {}
            if self._profile() is None:
                self._json({"ok": False, "error": "need_auth"}, 401)
            elif not self._require_host():
                self._host_only_denied()
            else:
                cfg = self._cfg()
                want = bool(data.get("locked"))
                cur = _current_address(cfg)
                if want and not _has_stored_password(cfg):
                    self._json({"ok": False, "error": "no_password",
                                "code": "no_password"}, 409)
                    return
                _address_entry(cfg, cur)["locked"] = want
                if want:
                    self._clear_guest_sessions(cfg)
                _save_config(cfg)
                name = cfg.get("address_name") or ""
                self._json({"ok": True, "locked": want,
                            "address": name, "display_address": name,
                            "message": (("Address locked \u2014 " + name)
                                        if want else
                                        ("Address unlocked \u2014 " + name))})
        elif path == "/api/guestlock":
            # v2.7.90 RETIRED: "lock guests out" is gone as a
            # host-initiated action (Nov 1, 2026). The endpoint
            # answers 410 so old clients fail loudly instead of
            # silently believing guests were locked out.
            # Password-gating remains: set a password and guests
            # must log in; remove it and the link is open.
            try:
                self.rfile.read(length)
            except OSError:
                pass
            self._json({"ok": False, "error": "guest lock is removed",
                        "code": "guest_lock_removed"}, 410)
        elif path == "/api/permissions":
            # v2.7.99: set one address's permission set. HOST-ONLY
            # (guests get 403 host_only). Body: {address (optional,
            # default current), permissions: {subset}}. The subset
            # merges onto the address's effective set (seeded from
            # legacy/defaults on first use), so toggling one box
            # never resets the other five. Per-address persisted.
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                data = {}
            if not self._require_host():
                self._host_only_denied()
                return
            cfg = self._cfg()
            raw_addr = str(data.get("address") or "").strip()
            if raw_addr:
                ok_name, _ = _validate_address_name(raw_addr)
                if not ok_name:
                    self._json({"ok": False,
                                "error": "invalid address",
                                "code": "invalid_link_name"}, 400)
                    return
                key = _sanitise_address(raw_addr)
            else:
                key = _current_address(cfg)
            subset = data.get("permissions")
            if not isinstance(subset, dict):
                subset = {}
            merged = _address_permissions(cfg, key)
            for k in _PERM_KEYS:
                if k in subset:
                    merged[k] = bool(subset[k])
            stored = cfg.get("address_permissions")
            if not isinstance(stored, dict):
                stored = {}
                cfg["address_permissions"] = stored
            stored[key] = merged
            _save_config(cfg)
            self._json({"ok": True, "address": key,
                        "permissions": merged})
        elif path == "/api/guestdelete":
            # v2.7.89 guest-delete toggle, HOST-ONLY. Persists in
            # config, takes effect immediately, and does NOT touch
            # sessions (existing guest tokens stay valid for
            # non-delete use; only delete permission changes).
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                data = {}
            if not self._require_host():
                self._host_only_denied()
                return
            cfg = self._cfg()
            cfg["guest_delete_allowed"] = bool(data.get("allowed"))
            _save_config(cfg)
            self._json({"ok": True,
                        "guest_delete_allowed":
                            cfg["guest_delete_allowed"]})
        elif path == "/api/guestnotesdelete":
            # v2.7.90, mirroring /api/guestdelete: host-only,
            # persists, immediate effect, never touches sessions.
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                data = {}
            if not self._require_host():
                self._host_only_denied()
                return
            cfg = self._cfg()
            cfg["guest_notes_delete_allowed"] = bool(data.get("allowed"))
            _save_config(cfg)
            self._json({"ok": True,
                        "guest_notes_delete_allowed":
                            cfg["guest_notes_delete_allowed"]})
        elif path == "/api/address/remove":
            # v2.8.11 HOST-ONLY: remove ONE address from history,
            # optionally deleting its notes and/or files too (two
            # separate checkboxes in the removal prompt). History
            # removal always happens; data deletion only for the
            # boxes ticked. Notes live per address in
            # notes-link-<key>.json. Files live in the address's
            # own folder when separate folders is ON; with it OFF
            # every address shares the Main Folder, so a ticked
            # files box deletes the Main Folder's files (the
            # dialog says they are shared).
            # v2.8.35: removing the CURRENT address also
            # disconnects from it and switches to the previous
            # one (most-recent remaining history entry); guests
            # on the removed address are logged out. Removing
            # the only address leaves no address selected.
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                data = {}
            if not self._require_host():
                self._host_only_denied()
                return
            cfg = self._cfg()
            key = _sanitise_address(str(data.get("key") or
                                        data.get("name") or ""))
            if not key:
                self._json({"ok": False, "error": "No address given"})
                return
            display = key
            for e in _address_history(cfg):
                if isinstance(e, dict) and e.get("key") == key:
                    display = str(e.get("name") or key)
                    break
            cfg["address_history"] = [e for e in _address_history(cfg)
                                      if isinstance(e, dict)
                                      and e.get("key") != key]
            notes_deleted = False
            files_deleted = False
            if data.get("delete_notes"):
                with _notes_lock:
                    p = _notes_path("link-" + key)
                    if os.path.isfile(p):
                        try:
                            os.remove(p)
                            notes_deleted = True
                        except OSError:
                            pass
                    else:
                        notes_deleted = True
            if data.get("delete_files"):
                root = os.path.abspath(_root_folder(cfg))
                entry = _address_registry(cfg).get(key)
                folder = None
                if isinstance(entry, dict) and entry.get("folder"):
                    folder = os.path.abspath(str(entry["folder"]))
                elif root:
                    folder = os.path.join(root, key)
                if _separate_folders_enabled(cfg):
                    if (folder and os.path.isdir(folder)
                            and os.path.abspath(folder) != root):
                        for fn in os.listdir(folder):
                            fp = os.path.join(folder, fn)
                            try:
                                if os.path.isfile(fp) or os.path.islink(fp):
                                    os.remove(fp)
                            except OSError:
                                pass
                        files_deleted = True
                else:
                    # v2.8.35: separate folders OFF -- files are
                    # shared in the Main Folder, so a ticked files
                    # box deletes that folder's top-level files
                    # (same depth as the per-address branch above;
                    # subfolders are left alone).
                    if root and os.path.isdir(root):
                        for fn in os.listdir(root):
                            fp = os.path.join(root, fn)
                            try:
                                if os.path.isfile(fp) or os.path.islink(fp):
                                    os.remove(fp)
                            except OSError:
                                pass
                        files_deleted = True
            # v2.8.35 HOST-ONLY switch: removing the CURRENT
            # address disconnects from it and switches to the
            # previous one (most-recent remaining history entry).
            # Removing the only address leaves no address
            # selected. Guests on the removed address are logged
            # out either way.
            switched_to = ""
            if key and key == _current_address(cfg):
                remaining = _address_history(cfg)
                port = self.server.server_address[1]
                if remaining:
                    prev = remaining[0]
                    prev_key = prev["key"]
                    prev_name = prev["name"]
                    pentry = _address_registry(cfg).get(prev_key) or {}
                    cfg["address_name"] = prev_name
                    cfg["address_pass"] = pentry.get("pass", "")
                    cfg["address_pass_enc"] = pentry.get("pass_enc", "")
                    self.server.address_name = prev_key
                    self.server.url = ("http://%s.local:%d"
                                       % (prev_key, port))
                    switched_to = prev_name
                else:
                    cfg["address_name"] = ""
                    cfg["address_pass"] = ""
                    cfg["address_pass_enc"] = ""
                    self.server.address_name = ""
                    self.server.url = ("http://%s:%d"
                                       % (lan_ip(), port))
                self._clear_guest_sessions(cfg)
            _save_config(cfg)
            self._json({"ok": True, "address": display,
                        "notes_deleted": notes_deleted,
                        "files_deleted": files_deleted,
                        "switched_to": switched_to})
        elif path == "/api/linkhistory/delete":
            # v2.7.90 HOST-ONLY: remove ONE entry from history.
            # History only: the link's folder, files, registry
            # password and folder override are NOT touched.
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                data = {}
            if not self._require_host():
                self._host_only_denied()
                return
            cfg = self._cfg()
            key = _sanitise_address(str(data.get("key") or
                                     data.get("name") or ""))
            cfg["address_history"] = [e for e in _address_history(cfg)
                                   if e["key"] != key]
            _save_config(cfg)
            self._json({"ok": True,
                        "message": ("Removed from history - the "
                                    "folder and files are still "
                                    "there on this PC")})
        elif path == "/api/notes/rename":
            # v2.8.0: renaming is editing -- gated by add_notes,
            # now labelled "Add / Edit Notes" in Set Up.
            if not self._can_perm("add_notes"):
                self._json({"ok": False,
                            "error": _PERM_MESSAGES["add_notes"],
                            "code": "add_note_forbidden"}, 403)
                return
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
                with _notes_lock:
                    ok = rename_note(data.get("id"),
                                     str(data.get("title") or ""), self._pid())
                self._json({"ok": ok})
            except json.JSONDecodeError:
                self._json({"ok": False}, 400)
        elif path == "/api/notes/star":
            # v2.7.99: starring obeys star_notes.
            if not self._can_perm("star_notes"):
                self._json({"ok": False,
                            "error": _PERM_MESSAGES["star_notes"],
                            "code": "star_forbidden"}, 403)
                return
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
                with _notes_lock:
                    ok = star_note(data.get("id"),
                                   bool(data.get("starred")), self._pid())
                self._json({"ok": ok})
            except json.JSONDecodeError:
                self._json({"ok": False}, 400)
        elif path == "/api/upload" and "multipart/form-data" in ctype:
            # v2.7.99: uploads obey upload_files.
            if not self._can_perm("upload_files"):
                self._json({"ok": False,
                            "error": _PERM_MESSAGES["upload_files"],
                            "code": "upload_forbidden"}, 403)
                return
            m = re.search(r"boundary=([^;]+)", ctype)
            if not m or length <= 0:
                self._json({"ok": False, "error": "bad request"}, 400)
                return
            try:
                body = self.rfile.read(length)
            except (OSError, ValueError):
                body = b""
            # v2.8.30 (1): a CANCELLED upload must leave NO file
            # behind (Essef Nov 6, ~5:24 PM). The pill X aborts
            # the XHR, so the socket closes mid-body and read()
            # returns SHORT -- but parse_multipart still yields
            # the truncated part (header + partial content, no
            # closing boundary) and the old code wrote it as a
            # complete file: a broken entry in Shared Files.
            # A complete FormData body ALWAYS ends with the
            # closing "--boundary--" marker, so a body that is
            # short, or lacks that marker, is an aborted upload:
            # write NOTHING, answer 400 if the socket is still
            # alive (it usually is not -- the BrokenPipe is
            # swallowed), and never start the AI index. Only a
            # fully-received body may create files.
            _bnd = m.group(1).encode()
            if (len(body) < length or not body.rstrip(b"\r\n").endswith(
                    b"--" + _bnd + b"--")):
                self.log_message(
                    "discarded incomplete upload (%d of %d bytes)",
                    len(body), length)
                try:
                    self._json({"ok": False, "error": "upload cancelled",
                                "code": "upload_incomplete"}, 400)
                except (OSError, ValueError):
                    pass
                return
            saved = []
            for filename, content in parse_multipart(body, _bnd):
                dest = unique_path(self._dir(), filename)
                with open(dest, "wb") as f:
                    f.write(content)
                saved.append(os.path.basename(dest))
                self.log_message("saved %s (%d bytes)", dest, len(content))
            # index new files in the background so the AI button appears
            # promptly for photos with text (frontend re-polls /api/files)
            try:
                import dropit_ai
                threading.Thread(
                    target=dropit_ai.build_index,
                    args=(self._dir(), self._ai_dir()),
                    daemon=True).start()
            except Exception:  # noqa: BLE001 - AI optional
                pass
            self._json({"ok": True, "saved": saved})
        elif path == "/api/delete":
            # v2.7.89: guest file deletion is gated by the host's
            # "Guests can delete files" toggle (default OFF). Host
            # deletion always works. Notes deletion is a separate
            # endpoint and is NOT gated here (files only).
            if not self._can_delete_files():
                self._json({"ok": False, "error":
                            _PERM_MESSAGES["delete_files"],
                            "code": "guest_delete_forbidden"}, 403)
                return
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
                name = safe_name(data.get("name", ""))
                path = os.path.join(self._dir(), name)
                if os.path.isfile(path):
                    os.remove(path)
                    self._json({"ok": True})
                else:
                    self._json({"ok": False}, 404)
            except (json.JSONDecodeError, OSError):
                self._json({"ok": False}, 400)
        elif path == "/api/delete_all":
            if not self._can_delete_files():
                self._json({"ok": False, "error":
                            _PERM_MESSAGES["delete_files"],
                            "code": "guest_delete_forbidden"}, 403)
                return
            try:
                n = 0
                for name in os.listdir(self._dir()):
                    path = os.path.join(self._dir(), name)
                    if os.path.isfile(path):
                        os.remove(path)
                        n += 1
                self._json({"ok": True, "deleted": n})
            except OSError:
                self._json({"ok": False}, 400)
        elif path == "/api/snippet":
            # v2.7.99: adding a note obeys add_notes.
            if not self._can_perm("add_notes"):
                self._json({"ok": False,
                            "error": _PERM_MESSAGES["add_notes"],
                            "code": "add_note_forbidden"}, 403)
                return
            # Share a text note. Stored in the app's notes.json (app data dir),
            # NOT as a file in the shared folder.
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
                text = data.get("text", "")
                if not isinstance(text, str) or not text.strip():
                    self._json({"ok": False, "error": "empty"}, 400)
                    return
                text = text.strip()
                if len(text) > 100_000:
                    self._json({"ok": False, "error": "too long (100k chars max)"}, 400)
                    return
                with _notes_lock:
                    note = add_note(text, self._pid())
                self.log_message("note %s (%d chars)", note["id"], len(text))
                self._json({"ok": True, "id": note["id"], "name": note["id"]})
            except (json.JSONDecodeError, OSError):
                self._json({"ok": False}, 400)
        elif path == "/api/notes/delete":
            # v2.7.90: gated by "Guests can delete notes" (OFF by
            # default). Host delete always works; file-delete
            # permission does NOT gate notes, and vice versa.
            if not self._can_delete_notes():
                self._json({"ok": False, "error":
                            _PERM_MESSAGES["delete_notes"],
                            "code": "guest_notes_delete_forbidden"}, 403)
                return
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
                nid = data.get("id", "")
                with _notes_lock:
                    ok = delete_note(nid, self._pid()) if isinstance(nid, str) and nid else False
                self._json({"ok": ok}, 200 if ok else 404)
            except (json.JSONDecodeError, OSError):
                self._json({"ok": False}, 400)
        elif path == "/api/notes/delete_all":
            if not self._can_delete_notes():
                self._json({"ok": False, "error":
                            _PERM_MESSAGES["delete_notes"],
                            "code": "guest_notes_delete_forbidden"}, 403)
                return
            try:
                with _notes_lock:
                    n = len(load_notes(self._pid()))
                    save_notes([], self._pid())
                self._json({"ok": True, "deleted": n})
            except OSError:
                self._json({"ok": False}, 400)
        elif path == "/api/notes/edit":
            # v2.8.0: editing is gated by add_notes, like adding.
            if not self._can_perm("add_notes"):
                self._json({"ok": False,
                            "error": _PERM_MESSAGES["add_notes"],
                            "code": "add_note_forbidden"}, 403)
                return
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
                nid = data.get("id", "")
                text = data.get("text", "")
                ok = False
                if isinstance(nid, str) and nid and isinstance(text, str) and text.strip():
                    if len(text) > 100_000:
                        self._json({"ok": False, "error": "too long (100k chars max)"}, 400)
                        return
                    with _notes_lock:
                        ok = edit_note(nid, text, self._pid())
                self._json({"ok": ok}, 200 if ok else 404)
            except (json.JSONDecodeError, OSError):
                self._json({"ok": False}, 400)
        elif path == "/api/aidl_progress":
            try:
                import dropit_mt
                self._json({"ok": True,
                            "downloads": dropit_mt.download_progress()})
            except Exception:  # noqa: BLE001 - AI optional
                self._json({"ok": False}, 500)
        elif path == "/api/mtpacks/clear":
            try:
                import dropit_mt
                cleared = dropit_mt.clear_packs(self._ai_dir())
                self._json({"ok": True, "pairs": cleared["pairs"],
                            "bytes": cleared["bytes"]})
            except Exception:  # noqa: BLE001 - AI optional
                self._json({"ok": False}, 500)
        elif path == "/api/aitranslate":
            if not _ait_allowed(self.client_address[0]):
                self._json({"ok": False, "message": "rate_limited"}, 429)
                return
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
                text = data.get("text", "")
                if not isinstance(text, str) or not text.strip():
                    self._json({"ok": False, "message": "empty"}, 400)
                    return
                if len(text) > 20_000:
                    self._json({"ok": False, "message": "too_long"}, 400)
                    return
                import dropit_mt
                self._json(dropit_mt.translate_to_english(text, self._ai_dir()))
            except (json.JSONDecodeError, OSError):
                self._json({"ok": False, "message": "error"}, 400)
            except Exception:  # noqa: BLE001 - AI optional
                self._json({"ok": False, "message": "error"}, 500)
        elif path == "/api/aitranslate/stream":
            # NDJSON variant of /api/aitranslate: one JSON object per line,
            # flushed as each chunk finishes, so long files render
            # progressively instead of freezing the modal. Same validation
            # and rate limiting as the single-shot endpoint.
            if not _ait_allowed(self.client_address[0]):
                self._json({"ok": False, "message": "rate_limited"}, 429)
                return
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
                text = data.get("text", "")
                if not isinstance(text, str) or not text.strip():
                    self._json({"ok": False, "message": "empty"}, 400)
                    return
                if len(text) > 20_000:
                    self._json({"ok": False, "message": "too_long"}, 400)
                    return
            except (json.JSONDecodeError, OSError):
                self._json({"ok": False, "message": "error"}, 400)
                return
            import dropit_mt
            try:
                stream = dropit_mt.iter_chunk_translations(
                    text.strip(), self._ai_dir())
                first = next(stream, None)
                if first is None or not first.get("ok", True):
                    code = 400 if (first or {}).get("message") in (
                        "empty", "too_long") else 500
                    self._json(first or {"ok": False, "message": "error"},
                               code)
                    return
                self.send_response(200)
                self.send_header("Content-Type",
                                 "application/x-ndjson; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                for msg in (first, *stream):
                    self.wfile.write((json.dumps(msg) + "\n").encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass  # user closed the modal mid-stream
            except Exception:  # noqa: BLE001 - AI optional
                try:
                    self.wfile.write((json.dumps(
                        {"ok": False, "message": "error"}) + "\n").encode())
                    self.wfile.flush()
                except OSError:
                    pass
        else:
            self._send(404, b"not found", "text/plain")


def make_server(port: int, directory: str, desktop: bool = False) -> ThreadingHTTPServer:
    os.makedirs(directory, exist_ok=True)
    migrate_snippets(os.path.abspath(directory))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    # The link is read verbatim from config and NEVER generated or
    # rewritten here: a restart must never auto-change the link. (A
    # v2.7.83 install with no link_name showed the LAN IP as the
    # "link", which changed with DHCP — that is what looked like an
    # auto-change. v2.7.84 shows "No link set yet" instead.)
    _cfg0 = _load_config()
    # v2.7.85: the display name stays exactly as the user typed it
    # (cfg["address_name"] is never rewritten here); only the mDNS/folder
    # key is the sanitised lowercase form. Previously this block
    # rewrote a mixed-case display name back to lowercase on restart.
    _link = _sanitise_address(_cfg0.get("address_name") or "")
    if _link and _adopt_legacy_notes(_cfg0):
        _save_config(_cfg0)
    server.address_name = _link
    # v2.7.88: desktop-app host proof. A random token held ONLY in
    # this server process's memory, handed to the pywebview window
    # only through its local JS bridge (Api.host_token in app.py).
    # It is never written to config, never returned by any API,
    # never put in the page HTML, a URL, a QR code, or a log, and it
    # changes on every server restart. A LAN guest's browser has no
    # pywebview bridge, so it can never obtain this token; a forged
    # "I am the host" claim without it is still a guest. This is
    # what lets the desktop window prove it is the host even when
    # its page was loaded / navigated via a LAN IP or .local name
    # instead of loopback (the v2.7.87 desktop-app bug: the window
    # showed the guest connect-only screen on the PC itself).
    server.host_token = secrets.token_urlsafe(32)
    server.url = (f"http://{_link}.local:{port}" if _link
                  else f"http://{lan_ip()}:{port}")
    threading.Thread(target=_mdns_serve, args=(server,),
                     daemon=True).start()
    server.directory = os.path.abspath(directory)
    server.desktop = desktop
    server.daemon_threads = True
    return server


def _preload_ai(directory):
    """Load the AI search model and build the file index in the background
    at startup, so the Ask tab answers instantly on first use.
    Never breaks startup."""
    try:
        import dropit_ai
        dropit_ai.build_index(directory, _data_dir())
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser(description="Drop - beam files phone <-> PC over WiFi")
    ap.add_argument("--version", action="version", version=f"DropIt {VERSION}")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--dir", default=os.path.join(os.path.expanduser("~"), "DropIt"))
    args = ap.parse_args()

    server = make_server(args.port, args.dir)

    print(f"\n  DropIt {VERSION} running!")
    print(f"  On your phone, open:  {server.url}")
    print(f"  Files land in:        {server.directory}")
    print("  Stop with Ctrl+C\n")
    # Warm up AI search in the background: model loads, index builds.
    threading.Thread(target=_preload_ai, args=(server.directory,),
                     daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBye!")


if __name__ == "__main__":
    main()
