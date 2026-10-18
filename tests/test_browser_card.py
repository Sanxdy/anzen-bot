#!/usr/bin/env python3
"""Checks for the Browser card's account rows.

The complaint this answers: you sign in, and the row still says "Sign in" — with no hint that closing
the window is what saves the login, and no way to tell whether it worked. So the claim under test is
that the row says what actually happened and what to do next, and that it notices a sign-in by itself.

Drives the real Settings card in a real browser against a real server, in this process so the
throwaway site can be one the app knows how to judge — the branch a real site like x.com lands in.
The local page plays a real site: it hands out a tracking cookie to everyone, and its sign-in cookie
only on the login page. Nothing here touches the internet.

Usage:  .venv/bin/python tests/test_browser_card.py
"""
import json, os, shutil, sys, tempfile, threading, time, http.server, urllib.request
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# A free port, so this never collides with a running app or another test.
_s = __import__("socket").socket(); _s.bind(("127.0.0.1", 0)); PORT = _s.getsockname()[1]; _s.close()
tmp = tempfile.mkdtemp(prefix="anzen-states-")
os.environ.update(DATA_DIR=tmp, SANDBOX_DIR=os.path.join(tmp, "sandbox"), BROWSER_WARMUP="0")
import server as S

assert S.DATA.startswith(tmp) and S.SET_PATH.startswith(tmp), "test paths must point into tmp"

# The app judges a sign-in by the site's own cookie. 127.0.0.1 is not a site it ships knowledge of,
# so it is taught one here — otherwise this test only ever sees the "cannot be confirmed" branch.
S.AUTH_COOKIES["127.0.0.1"] = ("anzen_login",)
S.AUTH_COOKIES["127.0.0.2"] = ("anzen_login",)

fails, TOTAL = [], [0]
def check(name, ok, extra=""):
    TOTAL[0] += 1
    print(("PASS " if ok else "FAIL ") + name + (("  " + str(extra)[:300]) if not ok else ""))
    if not ok: fails.append(name)

class Page(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        b = b"<h1>local site</h1>"
        cks = ["anon=1; Path=/; Max-Age=86400"]     # what every visitor gets, signed in or not
        if self.path.startswith("/login"):
            cks.append("anzen_login=1; Path=/; Max-Age=86400")   # only the login page hands this out
        self.send_response(200); self.send_header("Content-Type", "text/html")
        for ck in cks: self.send_header("Set-Cookie", ck)        # one header each: a comma inside
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)  # Max-Age voids the cookie
    def log_message(self, *a): pass

site = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)
threading.Thread(target=site.serve_forever, daemon=True).start()
LOGIN = "http://127.0.0.1:%d/login" % site.server_address[1]
SITE = "127.0.0.1:%d" % site.server_address[1]        # the same site, as an account row spells it

threading.Thread(target=lambda: S.serve(host="127.0.0.1", port=PORT, warm_browser=False),
                 daemon=True).start()

def api(path, body=None):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path),
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    return json.loads(urllib.request.urlopen(req, timeout=180).read())

try:
    for _ in range(80):
        try: api("/api/config"); break
        except Exception: time.sleep(0.5)
    else: raise SystemExit("server never came up")

    api("/api/settings", {"settings": {"browser": {
        "mode": "profiles", "headless": False,
        "accounts": [{"name": "Fresh", "sites": "127.0.0.2:%d" % site.server_address[1]},
                     {"name": "Local", "sites": "127.0.0.1:%d" % site.server_address[1]},
                     {"name": "Unknown", "sites": "127.0.0.9:%d" % site.server_address[1]},
                     # The user's own shape: two rows, one name, two sites. The name is what picks the
                     # browser, so these two share one — and the site has to come from the row clicked.
                     {"name": "Local", "sites": "localhost:%d" % site.server_address[1]}]}}})
    # The mode is read when the browser attaches, so it has to be restarted for the server to be in
    # profiles mode — the same thing the card's own mode selector does.
    api("/api/browser/restart", {})
    # "Unknown" is a site the app ships no sign-in cookie for, and it has been opened once already —
    # a folder with nothing saved in it. That is the state whose row used to answer "opened", which
    # reads as "it worked"; the folder is what the app looks at, so making it is the whole setup.
    os.makedirs(S.own_profile_dir("Unknown"), exist_ok=True)

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        pg = b.new_page(viewport={"width": 1400, "height": 1000})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto("http://127.0.0.1:%d/" % PORT, wait_until="domcontentloaded")
        pg.wait_for_timeout(1200)
        pg.click("#btnSettings"); pg.click("#tab-browser"); pg.wait_for_timeout(700)
        card = pg.locator(".card", has=pg.locator("b", has_text="Browser")).first
        def row_for(i):
            return pg.locator('input[placeholder="Account name"]').nth(i).locator("xpath=ancestor::div[1]")
        fresh, local, unknown = row_for(0), row_for(1), row_for(2)
        def state(r):
            return (r.locator("span.desc").inner_text(), r.locator("button").first.inner_text().strip(),
                    r.locator("span.desc").get_attribute("title") or "")

        check("the card says what to do after signing in, including closing the window",
              "close the window" in card.inner_text(), card.inner_text()[:400])
        t, btn, why = state(fresh)
        check("an account never opened says so, and the button offers the sign-in",
              t == "Not signed in yet" and btn == "Sign in", "%r / %r" % (t, btn))

        # A site the app ships no sign-in cookie for can never be confirmed either way, and that is
        # the one thing it must say — the row used to answer "opened" for it, which reads as "it worked".
        t, btn, why = state(unknown)
        check("a site the app cannot judge says so instead of guessing",
              t == "Cannot confirm this site's login" and btn == "Sign in", "%r / %r" % (t, btn))
        check("  ...and it does not claim a window is open when none is", "open" not in t.lower(), t)
        check("  ...and still tells the user to close the window when they are done", "close" in why, why)

        local.locator("button").first.click()
        pg.wait_for_timeout(20000)          # the window opens and the site loads
        t, btn, why = state(local)
        check("once the window is open the row says so instead of still offering a sign-in",
              "Window is open" in t and btn == "Open window", "%r / %r" % (t, btn))
        check("the row explains what to do next in its tooltip", "close" in why, why)
        check("the row does NOT claim a sign-in that never happened", "Signed in" not in t, t)
        check("  ...and the account that was not touched is still untouched",
              state(fresh)[0] == "Not signed in yet", state(fresh)[0])

        # Now the user logs in in that window — the one thing no page here can see. It is the app's
        # own browser, so it is driven the way the app drives it: on its thread, through its queue.
        S.BROWSER.call("profile_open", name="Local", url=LOGIN, timeout=180)
        for _ in range(20):                 # the poll ticks every 3s; no click, no refresh
            pg.wait_for_timeout(1000)
            if "Signed in" in state(local)[0]: break
        t, btn, why = state(local)
        check("the card notices the sign-in by itself, with no click and no refresh",
              "Signed in" in t and btn == "Open window", "%r / %r" % (t, btn))
        check("  ...and says the window is still open, because it is",
              "window is open" in t, t)

        # Closing the window is what writes the login to disk. The row must keep saying so, now
        # reading the profile on disk instead of the live browser.
        api("/api/browser/restart", {})
        for _ in range(20):                 # the write to disk is the browser's own, so wait for it
            pg.wait_for_timeout(1000)
            if state(local)[0] == "Signed in": break
        t, btn, why = state(local)
        check("closing the window keeps the sign-in, and the row still says Signed in",
              t == "Signed in" and btn == "Open window", "%r / %r" % (t, btn))
        check("  ...and it no longer claims a window is open", "open" not in t.lower(), t)

        # ---- a row added now must not inherit the login already saved ----
        # The bug the user hit: they added an account and it read "Signed in" before they had done
        # anything. The row was matched to a profile by the name as typed, and the folder is what
        # holds the cookies — so a name that reduces to a folder already on disk ("local" next to
        # "Local", which macOS resolves to the same folder) was handed that profile's saved login.
        pg.locator("button", has_text="Add account").first.click()
        pg.wait_for_timeout(400)
        newname = pg.locator('input[placeholder="Account name"]').nth(4)
        newname.fill("local")
        pg.locator('input[placeholder^="Sites the bots"]').nth(4).fill(SITE)
        newname.press("Tab")                              # blurring is what saves the row
        pg.wait_for_timeout(1500)
        t, btn, why = state(row_for(4))
        check("a row added now does not read Signed in off someone else's browser",
              "Signed in" not in t, t)
        check("  ...it says the two names share one browser, or that it is new",
              "browser" in t or t == "Not signed in yet", t)
        check("  ...and the account that really is signed in still says so",
              state(local)[0] == "Signed in", state(local)[0])
        check("  ...and the untouched account is still untouched",
              state(fresh)[0] == "Not signed in yet", state(fresh)[0])

        # ---- the button on a row opens *that row's* site ----
        # The complaint: clicking Open window on the Threads row always landed on x.com. Both rows
        # were named the same, and the site was read off the account *name*, which can only answer
        # with whichever row came first. Two rows, one name, two sites — each button must use its own.
        t, btn, why = state(row_for(3))
        check("a second row with the same name is named as the same browser, not a second account",
              "browser" in t and "Signed in" not in t, t)
        row_for(3).locator("button").first.click()
        for _ in range(40):
            pg.wait_for_timeout(500)
            if "localhost" in pg.locator("#browserNote").inner_text(): break
        note = pg.locator("#browserNote").inner_text()
        check("the row's own site is what opens, not the first site of the name it shares",
              "https://localhost:%d" % site.server_address[1] in note, note[:300])
        check("  ...and it is not the other row's site",
              "127.0.0.1:%d" % site.server_address[1] not in note, note[:300])
        check("no JavaScript error was raised while doing any of that", not errs, errs)

        # ---- a room's accounts are the room's ----
        # The complaint behind this: every bot in every room saw the whole machine-wide list, so the
        # user had to type an account name into the chat. The list a room's editor draws must be the
        # room's own, and a room with none must still fall back rather than lose its routing.
        api("/api/channel", {"channel": {"id": "promo", "name": "Promo",
                                        "browser": [{"name": "Room acct", "sites": "example.com"}]}})
        room = api("/api/browser/own?room=promo")
        check("a room's account list is the room's own",
              [p["name"] for p in room["profiles"]] == ["Room acct"], room["profiles"])
        check("  ...and it knows the sites that room routes",
              room["profiles"][0]["hosts"] == ["example.com"], room["profiles"][0]["hosts"])
        check("the machine-wide list still answers for a chat outside a room",
              len(api("/api/browser/own")["profiles"]) > 1, api("/api/browser/own")["profiles"])
        check("a room with no accounts still falls back to the machine-wide ones",
              S._room_routes(api("/api/config")["channels"][0]) is None)

        # The room editor itself: the Browser section is there, and its rows belong to the room.
        pg.click("#sClose"); pg.wait_for_timeout(400)
        pg.click("#btnSettings"); pg.click("#tab-channels"); pg.wait_for_timeout(700)
        pg.locator("button", has_text="Edit").first.click(); pg.wait_for_timeout(900)
        panel = pg.locator("#setPanel")
        check("the room editor has a Browser section", "Browser" in panel.inner_text(),
              panel.inner_text()[:600])
        check("  ...and says what an empty list means",
              "machine-wide" in panel.inner_text(), panel.inner_text()[:900])
        check("  ...and no JavaScript error was raised opening it", not errs, errs)
        b.close()
finally:
    try:
        S.BROWSER.q.put(None)
    except Exception: pass
    try:
        S._SRV.shutdown(); S._SRV.server_close()
    except Exception: pass
    site.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)

print("\n%d checks, %d failed" % (TOTAL[0], len(fails)))
sys.exit(1 if fails else 0)
