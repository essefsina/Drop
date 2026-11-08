"""v2.8.33 round (Essef Nov 6, voice calls ~8:00-8:09 PM PT) --
web/desktop, local test build only. SEVEN items, nothing else
(video features PARKED by Essef -- do not add them here):

  (1) WEB WILL NOT CONNECT TO THE DESKTOP. Address
      10-0-0-85-8000 (10.0.0.85:8000). Symptom: the connect
      attempt runs a few seconds, then "no devices connected",
      with the desktop app RUNNING. Three root causes, all
      reproduced live in the sandbox on 2.8.32:
        (A) STALE DECLARED-ADDRESS HEADER poisons /api/connect:
            the phone page loaded while the address was oldaddr;
            the PC changed it to 10-0-0-85-8000 (same password);
            without reloading, correct name + correct password
            still failed with "Couldn't connect to this address"
            -- postJ sent X-Drop-Address: oldaddr and the
            server's _profile() refused any declared address !=
            current, even after login minted a valid token.
            Fix: server /api/connect now computes authed from
            the token itself (bound to the current link) + host
            bypass + tokenless-open fallback, ignoring the
            declared-header gate; client refreshAuthName()
            (header-free /api/authstate) runs at the start of
            doGuestLogin, after login before the second connect,
            and before connect in #lkset Save and mpcconnect.
        (B) DOTTED IP / FULL URL REJECTED in the Address field:
            typing 10.0.0.85:8000 or http://10.0.0.85:8000/
            (the exact form the PC's copied link / QR URL
            shows) errored "Dots are not allowed in address
            names" and Connect never fired -- parsePastedAddress
            returned null for any host with a dot, and the
            server 400'd {"link":"10.0.0.85:8000"} as
            invalid_link_name. Fix: parsePastedAddress now
            accepts a dotted host naming THIS server (returns
            AUTH.address_name) and bare IPv4 with/without port
            or scheme; a URL for a DIFFERENT machine navigates
            the browser there (foreignPastedUrl).
        (C) PILL NOT REFRESHED UNTIL THE 5s POLL: the server
            registered the guest at once (devices:1 in 0.00s)
            but the guest's own pill said "No devices connected"
            until the next 5s tick -- doGuestLogin never called
            loadStatus(). Combined with (A), a stale page's
            polls also 401'd, so the pill stuck at 0
            indefinitely -- exactly "tries a few seconds, then
            no devices connected" on a RUNNING desktop. Fix:
            checkAuth() calls loadStatus() once authed.
            (Regression caught by probe48e and fixed in the
            same round: the first cut called loadStatus()
            UNCONDITIONALLY, and /api/status 401s for an
            unauthed guest -- checkAuth -> loadStatus -> 401
            -> wrapper showLock()+checkAuth() spun ~30/sec,
            90 /api/status 401s in 3s, and the Saved view could
            never open. The fix is three-layer: loadStatus()
            only when authed; the 401 wrapper skips its bounce
            while the guest login page is already open; the
            loadStatus() call in checkAuth is authed-only.)
  (2) TITLE BAR -> DESIGN 4 (glossy, round logo, slightly
      see-through). Verified in probe48.py F5 (dark + light,
      bridge stub); CSS assertions live here.
  (3) PREVIEW NOT WORKING ON "SAVED ON THIS DEVICE" (web).
      Four defects, all in the offline Saved path:
        (a) tapping the file NAME did nothing (only thumbnail
            and Open had handlers) -- the name now previews;
        (b) a listed file with no cached blob dead-ended at a
            toast even with the PC reachable -- openBlob's
            re-download fallback is now reached while authed
            (unauthed still gets the honest "no longer stored"
            toast, since re-download needs a session);
        (c) downloadFile's DBCACHE.put was not awaited while
            the ledger wrote synchronously -- ledger/cache
            could diverge on a quick tab close; now awaited;
        (d) closing a saved preview often landed on the login
            form: _savedReturn was consumed by ANY
            showGuestLogin() call, including the 5s poll's 401
            bounce while the viewer was open -- now the flag is
            only consumed once the viewer is closed. (Plus the
            (1)(C) wrapper fix above: unauthed polls no longer
            bounce the Saved view back to the login form at
            all -- it now survives indefinitely.)
  (4) REMOVE THE SCROLLER IN THE MAIN MENU (sidebar), PC app
      only. At the 600px minimum window height the menu
      overflowed by ~12px (scrollH 612 vs clientH 600).
      html.pcapp #sidebar is now overflow-y:hidden with
      tighter vertical spacing (12px padding, 10px card gaps)
      so it fits at 600px with room to spare.
  (5) PREVIEW GOES UNDER THE NEW TITLE BAR (desktop). The
      overlay covered the full viewport at z 1001 under the
      bar's z 1500, so a tall centred preview started ~16px
      from the top and its top edge, red X and scrollbar track
      ran behind the bar (Essef's Nov 6 photo). On
      html.pcapp.frameless the overlay now starts at top:44px
      and every vh-based cap loses the same 44px, for the
      preview AND the saved-file viewer, all types.
  (6) THINNER PICTURE BORDERS (web/desktop). The computed
      borders were already 1px -- the "thick" frame was the
      12px pvbody padding + 1px border (~13px of dark
      surround). Picture/video preview bodies now use 4px
      padding, border still 1px: visible frame ~13px -> ~5px.
      Text/PDF preview padding untouched.
  (7) NO SCROLLERS IN SCREENSHOT/PORTRAIT PICTURE PREVIEW
      (web/desktop). The fit math undercounted chrome by ~2px
      (70px allowance vs 72px real) and .fitpic .pvbody was
      overflow:auto with no CSS backstop (max-width/height
      none), so a 1px horizontal overflow showed scrollbars;
      a cached image could also skip sizing entirely (no
      img.complete check -- the video branch already had the
      readyState guard). Now: .fitpic .pvbody overflow:hidden,
      img clamped max-width:100% / max-height:calc(96vh-180px),
      JS chrome allowance 70->56 wide / 196->180 tall (+44 on
      frameless), and the sizing runs at once for already-
      complete images. The picture is slightly BIGGER in the
      freed space (screenshot 257x572 -> 265x588 at 1280x800).
"""
import ast
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dropit as D  # noqa: E402
from test_link_round2 import server, _raw  # noqa: F401,E402
from test_link_round33 import _Fwd  # noqa: E402
from test_link_round36 import _playwright  # noqa: E402
from test_link_round37 import _make_fixtures  # noqa: E402
from test_link_round44 import desktop_server, _desktop_page  # noqa: E402,F401

PAGE = D.PAGE
SRC = open(os.path.join(os.path.dirname(__file__), "..", "dropit.py"),
           encoding="utf-8").read()

PROOF = "/home/hatch/workspace/dropit-proof-round48"
os.makedirs(PROOF, exist_ok=True)

ADDR = "10-0-0-85-8000"  # Essef's actual address form (LAN IP:port dashed)
PW = "test1234"


def test_version_is_2_8_33():
    assert D.VERSION == "2.8.33"


def test_interpreted_page_valid_js_no_surrogates():
    for n in ast.walk(ast.parse(SRC)):
        if isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "PAGE"
                for t in n.targets):
            page = n.value.value
            break
    else:
        raise AssertionError("PAGE assignment not found")
    assert page == PAGE
    assert not [c for c in page if 0xD800 <= ord(c) <= 0xDFFF]
    page.encode("utf-8")


def test_item1_fix_markers_in_page():
    # (A) token-bound authed + header-free refresh; (B) dotted /
    # foreign-URL paste handling; (C) authed-only pill refresh.
    assert "refreshAuthName" in PAGE
    assert "foreignPastedUrl" in PAGE
    assert "_isThisServerHost" in PAGE
    assert "if(st.authed && typeof loadStatus" in PAGE
    assert "if(!(AUTH && AUTH.authed)) return;" in PAGE


def test_item2_titlebar_design4_in_page():
    assert "rgba(18,23,42,.85)" in PAGE
    assert "backdrop-filter:blur(8px)" in PAGE
    assert "#titlebar .tb-logo { width:22px; height:22px; display:block; border-radius:50%; }" in PAGE


def test_item4_sidebar_no_scroller_rule_in_page():
    assert "html.pcapp #sidebar { overflow-y:hidden;" in PAGE


def test_item5_preview_below_bar_rules_in_page():
    assert "html.pcapp.frameless .previewpop { top:44px; }" in PAGE
    assert "html.pcapp.frameless .viewer { top:44px; }" in PAGE
    assert "calc(96vh - 224px)" in PAGE


def test_item6_thin_frame_rules_in_page():
    assert (".previewpop.fitpic .previewbox .pvbody { overflow:hidden;"
            in PAGE)
    assert "max-height:calc(96vh - 180px)" in PAGE


# --- live guest helpers (real server + non-loopback guest) --------

def _guest_browser(pw, fwd_port):
    browser = pw.chromium.launch(args=["--no-proxy-server"])
    ctx = browser.new_context(viewport={"width": 390, "height": 844},
                              is_mobile=True, has_touch=True)
    pg = ctx.new_page()
    pg.goto("http://127.0.0.3:%d/" % fwd_port)
    pg.wait_for_function(
        "() => { const e = document.querySelector('#guestlogin');"
        " return e && e.classList.contains('open'); }", timeout=10000)
    pg.wait_for_timeout(400)
    return browser, ctx, pg


def _connect(pg, link_text, pw_text=PW):
    pg.fill("#gloginlink", link_text)
    pg.fill("#gloginpw", pw_text)
    pg.click("#gloginbtn")
    pg.wait_for_function(
        "() => { const e = document.querySelector('#guestlogin');"
        " return e && !e.classList.contains('open'); }", timeout=15000)


def _pill(pg):
    return pg.evaluate("() => document.querySelector('#statustext')"
                       ".textContent")


def _wait_pill(pg, expected="1 Device Connected", timeout=3000):
    # The pill refresh is async (checkAuth -> loadStatus fetch), so
    # wait for it -- but bound it well under the old 5s poll: the
    # point of the fix is that it flips PROMPTLY after Connect.
    pg.wait_for_function(
        "() => { const e = document.querySelector('#statustext');"
        " return e && e.textContent === '%s'; }" % expected,
        timeout=timeout)
    return _pill(pg)


def _linkdir_with_fixtures(client, base):
    client.j("POST", "/api/setlink", {"name": ADDR, "password": PW})
    linkdir = os.path.join(str(base), ADDR)
    os.makedirs(linkdir, exist_ok=True)
    _make_fixtures(linkdir)
    from PIL import Image
    Image.new("RGB", (1080, 2400), (20, 90, 160)).save(
        os.path.join(linkdir, "screenshot.png"))
    Image.new("RGB", (800, 1200), (160, 40, 40)).save(
        os.path.join(linkdir, "portrait.png"))
    return linkdir


def test_item1_dotted_ip_connect_succeeds(server):
    client, base, proc, port, home = server
    _linkdir_with_fixtures(client, base)
    fwd = _Fwd(port)
    pw = _playwright()
    try:
        browser, ctx, pg = _guest_browser(pw, fwd.port)
        # (B) the dotted form the PC's copied link / QR URL shows.
        _connect(pg, "10.0.0.85:8000")
        assert _wait_pill(pg) == "1 Device Connected", _pill(pg)
        pg.screenshot(path=os.path.join(PROOF, "r48_t_dotted_ip_main.png"))
        print("ITEM1-DOTTED: connect ok, pill '1 Device Connected' at once")
        browser.close()
    finally:
        pw.stop()


def test_item1_full_url_connect_succeeds(server):
    client, base, proc, port, home = server
    _linkdir_with_fixtures(client, base)
    fwd = _Fwd(port)
    pw = _playwright()
    try:
        browser, ctx, pg = _guest_browser(pw, fwd.port)
        _connect(pg, "http://10.0.0.85:8000/")
        assert _wait_pill(pg) == "1 Device Connected", _pill(pg)
        print("ITEM1-URL: http://10.0.0.85:8000/ connect ok, pill at once")
        browser.close()
    finally:
        pw.stop()


def test_item1_stale_page_connect_succeeds(server):
    # (A) page loaded while the address was oldaddr; the PC then
    # changes it to 10-0-0-85-8000 (same password). Without a
    # reload, the correct new name + password must connect.
    client, base, proc, port, home = server
    client.j("POST", "/api/setlink", {"name": "oldaddr", "password": PW})
    fwd = _Fwd(port)
    pw = _playwright()
    try:
        browser, ctx, pg = _guest_browser(pw, fwd.port)
        client.j("POST", "/api/setlink", {"name": ADDR, "password": PW})
        _connect(pg, ADDR)
        assert _wait_pill(pg) == "1 Device Connected", _pill(pg)
        print("ITEM1-STALE: stale page connects after PC address change")
        browser.close()
    finally:
        pw.stop()


def _download_file(pg, name):
    pg.evaluate(
        """(n) => { const r=[...document.querySelectorAll('.frow')]
          .find(x=>x.dataset.frow===n);
          const b=r.querySelector('[data-dl]')||r.querySelector('.fact button');
          if(b) b.click(); }""", name)
    pg.wait_for_timeout(900)
    if pg.evaluate("() => document.querySelector('#cfdlg')"
                   ".classList.contains('open')"):
        pg.click("#cfyes")
        pg.wait_for_timeout(1000)


def _open_saved_view(pg):
    pg.evaluate("async()=>{await fetch('/api/logout',{method:'POST'})}")
    pg.reload()
    pg.wait_for_function(
        "() => { const e = document.querySelector('#guestlogin');"
        " return e && e.classList.contains('open'); }", timeout=10000)
    pg.wait_for_timeout(600)
    pg.click("#gsavedbtn")
    pg.wait_for_timeout(600)


def _viewer_state(pg):
    return pg.evaluate(
        """() => ({open: document.querySelector('#viewer')
                     .classList.contains('open'),
                   title: (document.querySelector('#vtitle')||{})
                     .textContent || '',
                   hasImg: !!document.querySelector('#vcontent img'),
                   hasPre: !!document.querySelector('#vcontent pre'),
                   hasIframe: !!document.querySelector('#vcontent iframe'),
                   hasVideo: !!document.querySelector('#vcontent video')})""")


def _saved_open(pg):
    return pg.evaluate(
        "() => document.querySelector('#gsavedview')"
        ".classList.contains('open')")


def test_item3_saved_preview_after_reload(server):
    client, base, proc, port, home = server
    _linkdir_with_fixtures(client, base)
    fwd = _Fwd(port)
    pw = _playwright()
    try:
        browser, ctx, pg = _guest_browser(pw, fwd.port)
        _connect(pg, ADDR)
        pg.click('.mtab[data-tab="files"]')
        pg.wait_for_timeout(800)
        for name in ("pic.png", "notes.txt", "doc.pdf"):
            _download_file(pg, name)
        saved = pg.evaluate("() => JSON.parse(localStorage.getItem"
                            "('dropit_dl')||'{}')")
        assert set(saved) >= {"pic.png", "notes.txt", "doc.pdf"}, saved
        _open_saved_view(pg)
        assert _saved_open(pg) is True
        for name, key in (("pic.png", "hasImg"), ("notes.txt", "hasPre"),
                          ("doc.pdf", "hasIframe")):
            pg.evaluate(
                """(n) => { const b=[...document.querySelectorAll(
                  '[data-open-saved]')].find(x=>x.getAttribute(
                  'data-open-saved')===n); if(b) b.click(); }""", name)
            pg.wait_for_timeout(1200)
            st = _viewer_state(pg)
            assert st["open"] is True, (name, st)
            assert st["title"] == name, (name, st)
            assert st[key] is True, (name, st)
            pg.evaluate("()=>{const c=document.querySelector('#vclose');"
                        " if(c) c.click();}")
            pg.wait_for_timeout(900)
            assert _saved_open(pg) is True, (name, "close must return "
                                              "to the Saved view")
        pg.screenshot(path=os.path.join(PROOF, "r48_t_saved_preview.png"))
        print("ITEM3-RELOAD: pic/txt/pdf preview after reload; close "
              "returns to Saved view")
        browser.close()
    finally:
        pw.stop()


def test_item3_saved_name_tap_opens_preview(server):
    client, base, proc, port, home = server
    _linkdir_with_fixtures(client, base)
    fwd = _Fwd(port)
    pw = _playwright()
    try:
        browser, ctx, pg = _guest_browser(pw, fwd.port)
        _connect(pg, ADDR)
        pg.click('.mtab[data-tab="files"]')
        pg.wait_for_timeout(800)
        _download_file(pg, "pic.png")
        _open_saved_view(pg)
        assert _saved_open(pg) is True
        pg.evaluate(
            """() => { const w=document.querySelector(
              '[data-savedname="pic.png"]'); if(w) w.click(); }""")
        pg.wait_for_timeout(1200)
        st = _viewer_state(pg)
        assert st["open"] is True, st
        assert st["hasImg"] is True, st
        print("ITEM3-NAME-TAP: tapping the Saved file name opens preview")
        browser.close()
    finally:
        pw.stop()


def test_item3_saved_view_survives_poll(server):
    # (1)(C) wrapper fix: unauthed 5s polls must not bounce the
    # Saved view back to the login form.
    client, base, proc, port, home = server
    _linkdir_with_fixtures(client, base)
    fwd = _Fwd(port)
    pw = _playwright()
    try:
        browser, ctx, pg = _guest_browser(pw, fwd.port)
        _connect(pg, ADDR)
        pg.click('.mtab[data-tab="files"]')
        pg.wait_for_timeout(800)
        _download_file(pg, "pic.png")
        _open_saved_view(pg)
        assert _saved_open(pg) is True
        pg.wait_for_timeout(7000)
        assert _saved_open(pg) is True, "Saved view bounced to login form"
        n401 = pg.evaluate(
            "() => (window.__n401===undefined)?0:window.__n401")
        print("ITEM3-SURVIVES: Saved view still open after 7s of polls")
        browser.close()
    finally:
        pw.stop()


def test_item3_missing_blob_redownloads_when_authed(server):
    # (3)(b): a listed file whose blob is gone re-downloads
    # through openBlob while connected; unauthed it still gets
    # the honest "no longer stored" toast.
    client, base, proc, port, home = server
    _linkdir_with_fixtures(client, base)
    fwd = _Fwd(port)
    pw = _playwright()
    try:
        browser, ctx, pg = _guest_browser(pw, fwd.port)
        _connect(pg, ADDR)
        pg.click('.mtab[data-tab="files"]')
        pg.wait_for_timeout(800)
        _download_file(pg, "pic.png")
        pg.evaluate("async()=>{ delete MEMBLOBS['pic.png'];"
                    " await DBCACHE.del('pic.png'); }")
        pg.wait_for_timeout(500)
        # openSavedFile -> openBlob -> downloadFile prompts the
        # Save confirm; answer it (do not await the call, it
        # blocks on the dialog).
        pg.evaluate("()=>{ openSavedFile('pic.png'); }")
        pg.wait_for_timeout(700)
        if pg.evaluate("() => document.querySelector('#cfdlg')"
                       ".classList.contains('open')"):
            pg.click("#cfyes")
        pg.wait_for_timeout(1500)
        st = _viewer_state(pg)
        assert st["open"] is True, st
        assert st["hasImg"] is True, st
        print("ITEM3-REDOWNLOAD: missing blob re-downloaded while authed")
        browser.close()
    finally:
        pw.stop()


def _preview_geom(pg):
    return pg.evaluate(
        """() => { const pop=document.querySelector('.previewpop');
          const box=pop.querySelector('.previewbox');
          const body=pop.querySelector('.pvbody');
          const br=box.getBoundingClientRect();
          const bd=body.getBoundingClientRect();
          const img=body.querySelector('img');
          const ir=img?img.getBoundingClientRect():null;
          return {open: pop.classList.contains('open'),
                  cls: pop.className,
                  boxTop: Math.round(br.top),
                  boxBottom: Math.round(br.bottom),
                  bodyTop: Math.round(bd.top),
                  scrollW: body.scrollWidth, clientW: body.clientWidth,
                  scrollH: body.scrollHeight, clientH: body.clientHeight,
                  overflow: getComputedStyle(body).overflowX + '/' +
                    getComputedStyle(body).overflowY,
                  img: ir ? {w: Math.round(ir.width),
                             h: Math.round(ir.height)} : null}; }""")


def test_item7_picture_preview_no_scrollers_web(server):
    client, base, proc, port, home = server
    _linkdir_with_fixtures(client, base)
    fwd = _Fwd(port)
    pw = _playwright()
    try:
        browser, ctx, pg = _guest_browser(pw, fwd.port)
        _connect(pg, ADDR)
        pg.click('.mtab[data-tab="files"]')
        pg.wait_for_timeout(800)
        for name, min_w, min_h in (("screenshot.png", 280, 580),
                                   ("portrait.png", 310, 470)):
            pg.evaluate(
                """(n) => { const r=[...document.querySelectorAll('.frow')]
                  .find(x=>x.dataset.frow===n);
                  const f=r.querySelector('.fname'); if(f) f.click(); }""",
                name)
            pg.wait_for_timeout(1200)
            g = _preview_geom(pg)
            assert g["open"] is True, (name, g)
            assert g["scrollW"] == g["clientW"], (name, g)
            assert g["scrollH"] == g["clientH"], (name, g)
            assert g["overflow"] == "hidden/hidden", (name, g)
            assert g["img"]["w"] >= min_w and g["img"]["h"] >= min_h, \
                (name, g)
            # Whole picture inside the window.
            assert g["boxBottom"] <= 844, (name, g)
            pg.evaluate("()=>{const b=document.querySelector"
                        "('.previewpop .pvclose'); if(b) b.click();}")
            pg.wait_for_timeout(600)
        pg.screenshot(path=os.path.join(PROOF, "r48_t_pic_noscroll.png"))
        print("ITEM7-WEB: screenshot+portrait fit, no scrollers, bigger "
              "than pre-fix 257x572")
        browser.close()
    finally:
        pw.stop()


def test_item6_picture_frame_thinner_web(server):
    client, base, proc, port, home = server
    _linkdir_with_fixtures(client, base)
    fwd = _Fwd(port)
    pw = _playwright()
    try:
        browser, ctx, pg = _guest_browser(pw, fwd.port)
        _connect(pg, ADDR)
        pg.click('.mtab[data-tab="files"]')
        pg.wait_for_timeout(800)
        pg.evaluate(
            """() => { const r=[...document.querySelectorAll('.frow')]
              .find(x=>x.dataset.frow==='pic.png');
              const f=r.querySelector('.fname'); if(f) f.click(); }""")
        pg.wait_for_timeout(1200)
        frame = pg.evaluate(
            """() => { const b=document.querySelector(
              '.previewpop.fitpic .previewbox .pvbody');
              const cs=getComputedStyle(b);
              return {paddingTop: cs.paddingTop,
                      borderTopWidth: cs.borderTopWidth}; }""")
        # Was 12px padding + 1px border (~13px frame); now 4px + 1px.
        assert frame["paddingTop"] == "4px", frame
        assert frame["borderTopWidth"] == "1px", frame
        print("ITEM6: picture frame padding 12px -> 4px, border stays 1px")
        browser.close()
    finally:
        pw.stop()


# --- desktop (PC app stub) checks ---------------------------------
# The page only adds html.pcapp / html.frameless when the pywebview
# bridge is present (markPcApp, from the bridge's is_frameless).
# A plain browser page never gets those classes, so desktop tests
# install the same bridge stub probe48.py used before loading.
BRIDGE_STUB = """
window.__bridgeCalls = [];
window.pywebview = { api: {
  open_file: async (n) => { return true; },
  host_token: async () => "",
  is_frameless: async () => ({ok:true, frameless:true}),
  is_maximized: async () => ({ok:true, maximized:false}),
  minimize_window: async () => { window.__bridgeCalls.push('min'); return {ok:true}; },
  toggle_maximize_window: async () => { window.__bridgeCalls.push('max'); return {ok:true, maximized:true}; },
  close_window: async () => { window.__bridgeCalls.push('close'); return {ok:true}; },
  move_window: async (x,y) => { window.__bridgeCalls.push('move'); return {ok:true}; },
} };
"""


def _desktop_page_stub(pw, port, exe, width=1280, height=800):
    browser = pw.chromium.launch(
        executable_path=exe, args=["--no-proxy-server"])
    # NOTE: the stub MUST be installed on the context (not the
    # page): pg.add_init_script did not take in probe48h
    # (hasBridge False), while ctx.add_init_script works.
    ctx = browser.new_context(viewport={"width": width, "height": height})
    ctx.add_init_script(BRIDGE_STUB)
    pg = ctx.new_page()
    pg.goto("http://127.0.0.1:%d/" % port)
    pg.wait_for_timeout(1800)
    return browser, pg

def test_item2_titlebar_design4_desktop(desktop_server):
    client, base, port, srv, exe = desktop_server
    client.j("POST", "/api/setlink", {"name": ADDR})
    pw = _playwright()
    try:
        browser, pg = _desktop_page_stub(pw, port, exe, 1280, 800)
        tb = pg.evaluate(
            """() => { const e=document.querySelector('#titlebar');
              const cs=getComputedStyle(e);
              const logo=document.querySelector('.tb-logo');
              return {h: e.getBoundingClientRect().height,
                      bg: cs.backgroundColor,
                      backdrop: cs.backdropFilter,
                      logoRadius: getComputedStyle(logo).borderRadius,
                      htmlCls: document.documentElement.className}; }""")
        assert tb["h"] == 44, tb
        assert tb["bg"] == "rgba(18, 23, 42, 0.85)", tb
        assert tb["backdrop"] == "blur(8px)", tb
        assert tb["logoRadius"] == "50%", tb
        assert "pcapp" in tb["htmlCls"] and "frameless" in tb["htmlCls"], tb
        pg.click("#tbmax")
        pg.wait_for_timeout(400)
        calls = pg.evaluate("() => window.__bridgeCalls")
        assert "max" in calls, calls
        pg.screenshot(path=os.path.join(PROOF, "r48_t_titlebar_dark.png"))
        pg.evaluate("()=>document.documentElement.classList.add('light')")
        pg.wait_for_timeout(300)
        light = pg.evaluate(
            "() => getComputedStyle(document.querySelector('#titlebar'))"
            ".backgroundColor")
        assert light == "rgba(255, 255, 255, 0.85)", light
        pg.screenshot(path=os.path.join(PROOF, "r48_t_titlebar_light.png"))
        print("ITEM2: Design 4 dark+light, round logo, blur bar")
        browser.close()
    finally:
        pw.stop()


def test_item4_sidebar_no_scroller_at_600(desktop_server):
    client, base, port, srv, exe = desktop_server
    client.j("POST", "/api/setlink", {"name": ADDR})
    pw = _playwright()
    try:
        for h in (800, 600):
            browser, pg = _desktop_page_stub(pw, port, exe, 1280, h)
            sb = pg.evaluate(
                """() => { const s=document.querySelector('#sidebar');
                  const cs=getComputedStyle(s);
                  let bottom=0;
                  s.querySelectorAll('*').forEach(el=>{
                    const r=el.getBoundingClientRect();
                    if(r.bottom>bottom) bottom=r.bottom; });
                  return {overflowY: cs.overflowY,
                          clientH: s.clientHeight,
                          contentBottom: Math.round(bottom)}; }""")
            assert sb["overflowY"] == "hidden", (h, sb)
            assert sb["contentBottom"] <= sb["clientH"], (h, sb)
            print("ITEM4 h=%d: sidebar fits, no scroller %s" % (h, sb))
            browser.close()
    finally:
        pw.stop()


def test_item5_preview_below_titlebar_desktop(desktop_server):
    client, base, port, srv, exe = desktop_server
    linkdir = os.path.join(str(base), ADDR)
    os.makedirs(linkdir, exist_ok=True)
    _make_fixtures(linkdir)
    client.j("POST", "/api/setlink", {"name": ADDR})
    pw = _playwright()
    try:
        browser, pg = _desktop_page_stub(pw, port, exe, 1280, 800)
        pg.wait_for_timeout(1000)
        for name in ("notes.txt", "pic.png"):
            pg.evaluate("(n)=>previewFile(n)", name)
            pg.wait_for_timeout(1200)
            g = _preview_geom(pg)
            assert g["open"] is True, (name, g)
            # Title bar is 44px: box top AND scroll-area top below it.
            assert g["boxTop"] >= 44, (name, g)
            assert g["bodyTop"] >= 44, (name, g)
            assert g["boxBottom"] <= 800, (name, g)
            pg.screenshot(path=os.path.join(
                PROOF, "r48_t_pc_preview_%s.png" % name.split(".")[0]))
            pg.evaluate("()=>{const b=document.querySelector"
                        "('.previewpop .pvclose'); if(b) b.click();}")
            pg.wait_for_timeout(600)
        print("ITEM5: text+pic preview fully below the 44px title bar")
        browser.close()
    finally:
        pw.stop()
