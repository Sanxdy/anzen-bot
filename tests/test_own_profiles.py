#!/usr/bin/env python3
"""Checks for the saved-profile browser ("own browser — saved profiles").

The claim being checked is the whole reason this mode exists: a sign-in done once is still there on
the next run, because the profile lives in a folder on disk. That is checked for real — a page sets a
cookie, the browser is closed, a new one is launched on the same folder, and the cookie must still be
there. Routing and the folder name are checked as pure functions.

Everything that touches a browser goes through `BROWSER.call`, which is how the app does it: the
browser owns its own thread and Playwright refuses to be driven from any other one.

Usage:  .venv/bin/python tests/test_own_profiles.py
"""
import os, sqlite3, subprocess, sys, tempfile, time
from playwright.sync_api import sync_playwright

tmp = tempfile.mkdtemp(prefix="anzen-profiles-")
os.environ["DATA_DIR"] = tmp
os.environ["SANDBOX_DIR"] = os.path.join(tmp, "sandbox")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as S

assert S.DATA.startswith(tmp) and S.SET_PATH.startswith(tmp), "test paths must point into tmp"

PASS = []; FAIL = []
def check(name, ok, extra=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + (f"  {extra}" if extra and not ok else ""))

def set_browser(**kw):
    s = S.load_settings(); s.setdefault("browser", {}).update(kw); S.save_settings(s)

def stop(b):
    """End a browser's thread the way a restart does — the sentinel it drains closes its own
    browsers. `_close_persistent` from this thread would close nothing: the browsers belong to the
    thread that made them."""
    b.q.put(None)
    if b.thread: b.thread.join(30)

def browsers_on(d):
    """The browser processes still running on one profile folder, asked of the OS rather than of
    Playwright — a leaked browser is exactly the thing Playwright cannot tell us about. The folder
    path is unique to this run, so a command line carrying it is a browser of ours and nothing else."""
    out = subprocess.run(["ps", "-Ao", "command"], capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if d in l]

# A test-only probe: quitting a profile's browser is what closing its last window does, and it can
# only be done from the thread that owns it.
def _probe_quit(self, name):
    ent = self._mine()["ctxs"].get(name)
    if ent: ent[0].close()
    return "quit"
S.Browser._probe_quit = _probe_quit


def main():
    # ---- routing: the settings hold the accounts you made, and a site goes to the one that owns it ----
    set_browser(accounts=[{"name": "X Promo", "sites": "x.com, twitter.com, 127.0.0.1"},
                          {"name": "FB Page", "sites": "facebook.com, localhost"},
                          {"name": "Not Signed In Yet", "sites": ""}],
                mode="profiles", profile="default", headless=True)
    check("accounts parse to host -> account name",
          S._route_pairs() == {"x.com": "X Promo", "twitter.com": "X Promo", "127.0.0.1": "X Promo",
                               "facebook.com": "FB Page", "localhost": "FB Page"},
          str(S._route_pairs()))
    check("a site written as a whole URL still routes",
          S._route_pairs({"accounts": [{"name": "A", "sites": "https://x.com/home"}]}) == {"x.com": "A"})
    check("an account with no name is dropped, not guessed at",
          S._route_pairs({"accounts": [{"name": "", "sites": "x.com"}, {"name": "A", "sites": "y.com"}]})
          == {"y.com": "A"})
    check("a sign-in lands on the account's own first site",
          S.account_site("X Promo") == "https://x.com", S.account_site("X Promo"))
    check("  ...and an account with no site has nowhere to land",
          S.account_site("Not Signed In Yet") == "" and S.account_site("nobody") == "")
    # A row's button belongs to the *row*, not to the account name. Two rows can name the same
    # account — the user's own setup had "Zenpilot.Pro" for x.com and again for threads.com — and the
    # name alone can only ever answer with whichever row was written first, so clicking Open window
    # on the threads row always landed on x.com. The site has to be read off the row that was clicked.
    check("a row's button lands on the first site of that row, as it was written",
          S.first_site("https://x.com/AndikaAndheci") == "https://x.com/AndikaAndheci"
          and S.first_site("https://www.threads.com/") == "https://www.threads.com/",
          "%r %r" % (S.first_site("https://x.com/AndikaAndheci"), S.first_site("https://www.threads.com/")))
    check("  ...a bare host gets https, and the second site of the row is not what it lands on",
          S.first_site("x.com, threads.net") == "https://x.com")
    check("  ...and a site on a port keeps its port — dropping it lands nowhere",
          S.first_site("127.0.0.1:8093") == "https://127.0.0.1:8093", S.first_site("127.0.0.1:8093"))
    check("  ...and a row with no site has nowhere to land, so the name's own site is the fallback",
          S.first_site("") == "" and S.first_site("   ") == "")

    b = S.Browser()
    check("the site's own host routes to its profile",
          b._route("https://x.com/home") == "X Promo")
    check("www and a port do not change the answer",
          b._route("https://www.x.com:443/") == "X Promo")
    check("a subdomain follows its parent domain",
          b._route("https://mobile.x.com/status/1") == "X Promo")
    check("a parent domain does not swallow an unrelated one",
          b._route("https://notx.com/") is None)
    check("a site nobody routed has no profile",
          b._route("https://example.com/") is None)
    check("an empty or scheme-less URL has no profile", b._route("") is None)

    # ---- the folder name is user text, so it must not be able to name a folder elsewhere ----
    base = os.path.abspath(os.path.join(tmp, "browser_profiles"))
    for bad in ("../../etc", "..", "/etc/passwd", "a/../../b", "", "   "):
        d = os.path.abspath(S.own_profile_dir(bad))
        check(f"profile name {bad!r} stays under browser_profiles", d.startswith(base + os.sep), d)
    check("a name with a space and a dot is kept, since folders allow both",
          os.path.basename(S.own_profile_dir("VPS DEV.v2")) == "VPS DEV.v2")

    # ---- which browser we launch: the one thing that decides whether Google will sign you in ----
    # Google turns away the Chromium Playwright ships — "This browser or app may not be secure" — and
    # signs in fine on a real Chrome installed on the machine. So the launch has to (a) be a browser
    # that is really here and (b) not announce itself as automated. (b) is checked live below.
    known = dict((k, p) for k, _, p in S.BROWSER_CHANNELS)
    check("only browsers that are really on disk are offered",
          all(os.path.isdir(known[c["key"]]) for c in S.installed_channels()),
          str(S.installed_channels()))
    check("  ...and every offered browser is one we know how to launch",
          all(c["key"] in known for c in S.installed_channels()))
    have = [c["key"] for c in S.installed_channels()]
    set_browser(channel="auto")
    picked = S.browser_channel()
    check("automatic picks a real local browser when there is one, and admits it when there is not",
          (picked in have) if have else picked == "", "%r vs %r" % (picked, have))
    set_browser(channel="bundled")
    check("asking for the bundled Chromium really means no local browser", S.browser_channel() == "")
    set_browser(channel="not-a-browser-on-this-machine")
    check("a browser this machine does not have is never trusted, it falls back",
          S.browser_channel() in have or S.browser_channel() == "", S.browser_channel())
    set_browser(channel="auto")
    opts = S._launch_opts(True)
    check("the automation switch Playwright adds is removed",
          "--enable-automation" in opts.get("ignore_default_args", []), str(opts))
    check("  ...and the page is told not to report itself as automated",
          "--disable-blink-features=AutomationControlled" in opts["args"], str(opts))
    check("the launch names the chosen browser, and names none when there is none",
          ("channel" in opts) == bool(S.browser_channel()), str(opts))
    # Asking for the sandbox off is what paints "unsupported command-line flag: --no-sandbox" across
    # the sign-in window — a real warning about a real thing, for a flag a desktop never needed.
    # It is only for root (containers), where Chromium refuses to start without it.
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        check("a normal desktop is not asked to run without the sandbox",
              "--no-sandbox" not in opts["args"] and "--disable-dev-shm-usage" not in opts["args"],
              str(opts))

    # ---- the listing names every account you made, and says which have never been opened ----
    lst = S.browser_own_profiles()
    names = {p["name"] for p in lst["profiles"]}
    check("the listing carries every account",
          {"X Promo", "FB Page", "Not Signed In Yet"} <= names, str(sorted(names)))
    check("a profile that was never opened is listed as such",
          all(p["exists"] is False for p in lst["profiles"]), str(lst["profiles"]))
    check("each profile lists the sites routed to it",
          sorted(next(p for p in lst["profiles"] if p["name"] == "X Promo")["hosts"])
          == ["127.0.0.1", "twitter.com", "x.com"])
    check("an account with no sites yet is still listed, so you can sign in before routing it",
          next((p for p in lst["profiles"] if p["name"] == "Not Signed In Yet"), None) is not None)
    check("the listing reports the browser choice and the choices, so the picker can be drawn",
          lst["channel"] == "auto" and [c["key"] for c in lst["channels"]] == have,
          "%r %r" % (lst["channel"], lst["channels"]))

    # ---- a local page that sets a cookie, because that is what a sign-in is ----
    # Planting one through the API would only be testing the API: Chromium keeps those in memory
    # until a real response writes them to the profile folder.
    import http.server, threading
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            b = ("<h1>site</h1><div>%s</div>" % (self.headers.get("Cookie") or "no-cookie")).encode()
            self.send_response(200); self.send_header("Content-Type", "text/html")
            self.send_header("Set-Cookie", "anzen_probe=signed-in; Path=/; Max-Age=86400")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        def log_message(self, *a): pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    site = "http://127.0.0.1:%d/" % srv.server_address[1]
    other = site.replace("127.0.0.1", "localhost")

    b.start()
    first = str(b.call("open", url=site))
    check("the first visit is not signed in yet", "no-cookie" in first, first[:200])
    wd = str(b.call("eval", expression="navigator.webdriver"))
    check("the account's browser does not announce itself as automated — the flag Google reads",
          wd.strip().lower() == "false", wd)
    check("the profile folder was made on disk", os.path.isdir(S.own_profile_dir("X Promo")))
    check("the account shows as open while its browser is up", "X Promo" in b.open_profiles())
    # ...and a different account is a different browser, so it never sees the first one's cookies.
    other_read = str(b.call("open", url=other))
    check("a second account is a separate browser, with its own cookies",
          "no-cookie" in other_read, other_read[:200])
    stop(b)

    # ---- the point: the cookie a page set is still there in the next run ----
    b2 = S.Browser(); b2.start()
    kept = str(b2.call("open", url=site))
    check("the cookie a page set is still there in the next run — the sign-in survives",
          "anzen_probe=signed-in" in kept, kept[:200])

    # ---- the user is told to close the sign-in window when done; that must not brick the account ----
    b2.call("_probe_quit", name="X Promo")             # the user quits that account's browser
    check("a profile the user quit is launched again, not handed back dead",
          "anzen_probe=signed-in" in str(b2.call("open", url=site)))
    stop(b2)

    # ---- Sign in must land on the site, not on a blank window ----
    b3 = S.Browser(); b3.start()
    said = str(b3.call("profile_open", name="X Promo", url=site))
    check("signing in lands on the site, not on a blank window",
          str(b3.call("eval", expression="location.origin")) == site.rstrip("/"), said)
    check("  ...and the note says where it landed", "window is open on" in said, said)
    # This is the window the user signs in in, so it is the one Google looks at. It is opened headed
    # on purpose, and with a local browser chosen it must be that browser rather than the Chromium
    # Playwright ships — whose user agent is what gives it away as a test build.
    if S.browser_channel():
        ua = str(b3.call("eval", expression="navigator.userAgent"))
        check("the sign-in window is the real local browser, not the build Google turns away",
              "HeadlessChrome" not in ua and "Chrome/" in ua, ua)
        check("  ...and it does not announce itself as automated either",
              str(b3.call("eval", expression="navigator.webdriver")).strip().lower() == "false")

    # ---- a restart must really close the old browsers, or the headless switch does nothing ----
    folder = S.own_profile_dir("X Promo")
    check("the account's browser is running before the restart", browsers_on(folder))
    b3.restart()                                       # what the headless checkbox does
    for _ in range(40):
        if not browsers_on(folder): break
        time.sleep(0.25)
    check("a restart closes the browsers the old thread owned, instead of leaking them",
          not browsers_on(folder), browsers_on(folder)[:1])
    check("  ...and the account still works afterwards",
          "anzen_probe=signed-in" in str(b3.call("open", url=site)))
    stop(b3)

    # ---- the bots must be told which sites open signed in, or they never use them ----
    # The accounts live only in Settings, so a bot asked to manage Threads and Facebook cannot find
    # out that an account covers them. This drives a real turn with a stubbed model and reads the
    # system prompt that was actually sent.
    brief = S.browser_brief()
    check("the brief names each account and the sites it covers",
          "X Promo for" in brief and "FB Page for" in brief
          and "x.com" in brief and "facebook.com" in brief, brief)
    check("  ...and a profile that was merely opened is never called signed in",
          "(not signed in yet)" in brief and "(signed in)" not in brief, brief)
    check("  ...and says what to do with everything else",
          "blank throwaway browser" in brief and "search the web" in brief, brief)

    sent = []
    real = S.chat_stream
    def fake_stream(model, messages, tools=None, max_tokens=1600):
        sent.append("".join(m["content"] for m in messages if m.get("role") == "system"))
        yield ("done", {"content": "done", "usage": {},
                        "tool_calls": [{"id": "1", "type": "function",
                                        "function": {"name": "finish", "arguments": '{"summary":"done"}'}}]})
    S.chat_stream = fake_stream
    def turn(n, task="manage my threads and facebook"):
        bots = S.load_bots(); out = {}
        list(S.run_agent("probe-%d" % n, bots[0]["id"], task, "", out, bots, S.load_settings()))
        return sent[-1]
    try:
        sysmsg = turn(1)
        check("the prompt a bot is really sent carries the brief",
              "X Promo for" in sysmsg and "blank throwaway browser" in sysmsg, sysmsg[-600:])
        check("  ...and tells it not to log in by hand",
              "never try to log in or type a password" in sysmsg, sysmsg[-600:])

        # ---- the prompt must follow the settings, or the user edits the list and nothing changes ----
        # Read per turn, so an edit takes effect on the bot's very next step — no restart, nothing to
        # press. A bot working a running turn keeps the prompt it started with, which is the honest
        # limit: the turn in flight was planned against what was true when it began.
        set_browser(accounts=[{"name": "X Promo", "sites": "x.com"},
                              {"name": "Threads Main", "sites": "threads.com"}])
        added = turn(2)
        check("an account added in Settings reaches the very next prompt",
              "Threads Main for" in added and "Threads Main for" not in sysmsg, added[-500:])
        set_browser(accounts=[{"name": "X Promo", "sites": "x.com"}])
        removed = turn(3)
        check("  ...and an account removed stops being mentioned",
              "Threads Main" not in removed and "Threads Main" in added, removed[-500:])
        # Signing in is the other half. Merely opening the window must NOT count as a sign-in — that
        # was the lie this replaced, and the whole reason the row used to say "signed in" the moment
        # anyone pressed Sign in. Until the site's own sign-in cookie is really there, the honest
        # answer is that we cannot confirm it.
        set_browser(accounts=[{"name": "Fresh Acct", "sites": "fresh.example"}])
        before_signin = turn(4)
        os.makedirs(S.own_profile_dir("Fresh Acct"), exist_ok=True)   # the user clicked Sign in
        after_signin = turn(5)
        check("  ...but pressing Sign in is not mistaken for a sign-in",
              "not signed in yet" in before_signin and "(signed in)" not in after_signin,
              after_signin[-500:])
        set_browser(accounts=[], mode="own")
        check("with nothing set up, the prompt says so instead of inventing an account",
              "no account is set up" in turn(6), sent[-1][-400:])
    finally:
        S.chat_stream = real

    # Many accounts must not be able to crowd the prompt: the extras are counted, not listed.
    set_browser(mode="profiles",
                accounts=[{"name": "Acct %02d" % i, "sites": "site%02d.example" % i} for i in range(60)])
    long_brief = S.browser_brief()
    check("a user with many accounts cannot crowd out the prompt",
          len(long_brief) < S.BROWSER_BRIEF_CHARS + 700, len(long_brief))
    check("  ...and the ones that did not fit are counted, not silently dropped",
          "more" in long_brief, long_brief[:200])
    # ---- "signed in" has to be evidence, not "a window was once opened" ----
    # The row used to say "signed in" as soon as the profile folder existed, which happens the moment
    # the window opens — so a user who never logged in was told they had. Every site hands out
    # tracking and consent cookies to a brand-new visitor, so the only thing that proves a login is
    # the cookie the site sets when you actually log in.
    check("a tracking cookie alone is not a sign-in",
          S.signed_in(["x.com"], [(".x.com", "guest_id"), ("x.com", "ct0")]) is False)
    check("the site's own sign-in cookie is",
          S.signed_in(["x.com"], [(".x.com", "guest_id"), (".x.com", "auth_token")]) is True)
    check("a cookie belonging to another site proves nothing",
          S.signed_in(["x.com"], [(".facebook.com", "auth_token")]) is False)
    check("a lookalike domain is not mistaken for the real one",
          S.signed_in(["x.com"], [(".notx.com", "auth_token")]) is False)
    check("a subdomain's cookie counts for the account that owns the domain",
          S.signed_in(["google.com"], [(".accounts.google.com", "SID")]) is True)
    check("a site we cannot judge is unconfirmed, never a claim either way",
          S.signed_in(["example.com"], [("example.com", "whatever")]) is None)
    check("an account with no sites cannot be judged",
          S.signed_in([], [("x.com", "auth_token")]) is None)

    # ---- one folder is one profile, and the listing has to say so ----
    # The settings page matches a row to a profile by the folder that holds its cookies. Two names
    # that reduce to the same folder are therefore one profile — "Anzen" and "anzen" are, on macOS,
    # literally one folder — and the listing must report both names under that single entry. It did
    # not: it reported one entry per *name*, so a second row was handed the first row's saved login
    # and read "Signed in" the moment it was added, before the user had done anything at all.
    def planted(name, hosts, cookie):
        """A profile that is really signed in, as the only thing that proves it: the site's own
        sign-in cookie, in the profile folder's own cookie file."""
        d = S.own_profile_dir(name); os.makedirs(os.path.join(d, "Default"), exist_ok=True)
        con = sqlite3.connect(os.path.join(d, "Default", "Cookies"))
        con.execute("CREATE TABLE IF NOT EXISTS cookies (host_key TEXT, name TEXT, value TEXT)")
        con.execute("INSERT INTO cookies VALUES (?, ?, 'x')", cookie); con.commit(); con.close()
        set_browser(accounts=[{"name": n, "sites": s} for n, s in hosts], mode="profiles")

    planted("Anzen", [("Anzen", "x.com")], (".x.com", "auth_token"))
    one = [p for p in S.browser_own_profiles()["profiles"] if p["id"] == "Anzen"]
    check("a signed-in profile is reported under its folder, with the name that made it",
          len(one) == 1 and one[0]["names"] == ["Anzen"] and one[0]["signed_in"] is True, str(one))
    planted("Anzen", [("Anzen", "x.com"), ("anzen", "x.com")], (".x.com", "auth_token"))
    both = S.browser_own_profiles()["profiles"]
    two = [p for p in both if p["id"].lower() == "anzen"]
    check("a second name landing in the same folder is that same profile, not a second signed-in "
          "account", len(two) == 1 and two[0]["names"] == ["Anzen", "anzen"], str(two))
    check("  ...so a row the server has never heard of is nobody's profile",
          all("Work" not in p["names"] for p in both), str(both))
    check("the folder a name means is decided in exactly one place",
          all(os.path.basename(S.own_profile_dir(n)) == S.profile_id(n)
              for n in ("Anzen", "anzen", "a/b", "  ", "..")))
    check("  ...and a name cannot name a folder outside the profile dir",
          os.path.dirname(S.own_profile_dir("../..")) == os.path.dirname(S.own_profile_dir("x")),
          S.own_profile_dir("../.."))


    # ---- the whole point of the row: it must know you are signed in while you are still looking at
    # the window, and it must stop calling that window open once you close it ----
    class L(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            b = b"<h1>site</h1>"
            self.send_response(200); self.send_header("Content-Type", "text/html")
            self.send_header("Set-Cookie", "auth_token=abc; Path=/; Max-Age=86400"
                             if self.path.startswith("/login") else "anon=1; Path=/; Max-Age=86400")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        def log_message(self, *a): pass
    lsrv = http.server.HTTPServer(("127.0.0.1", 0), L)
    threading.Thread(target=lsrv.serve_forever, daemon=True).start()
    lp = lsrv.server_address[1]
    plain, login = "http://127.0.0.1:%d/" % lp, "http://127.0.0.1:%d/login" % lp

    set_browser(accounts=[{"name": "Truth", "sites": "127.0.0.1"}], mode="profiles", headless=True)
    # The probe site declares what a login looks like on it, so the real code path runs unchanged.
    S.AUTH_COOKIES["127.0.0.1"] = ("auth_token",)
    keep_browser = S.BROWSER
    b4 = S.Browser(); S.BROWSER = b4        # the app has exactly one browser; this is now it
    try:
        def truth():
            return next(x for x in S.browser_own_profiles()["profiles"] if x["name"] == "Truth")
        b4.start()
        t0 = truth()
        check("an account that was never opened is not signed in",
              t0["exists"] is False and t0["signed_in"] is not True, str(t0))
        b4.call("open", url=plain, timeout=180)
        t1 = truth()
        check("a window opened but not logged into is not signed in",
              t1["up"] is True and t1["signed_in"] is False, str(t1))
        b4.call("open", url=login, timeout=180)
        t2 = truth()
        check("SIGNED IN is known while the window is still open — Chrome keeps cookies in memory "
              "until it closes, so this can only come from asking the browser itself",
              t2["up"] is True and t2["signed_in"] is True, str(t2))
        b4.call("_probe_quit", name="Truth")
        t3 = truth()
        check("closing the window keeps the answer, now read from the profile on disk",
              t3["signed_in"] is True, str(t3))
        check("a window the user quit stops counting as open",
              t3["up"] is False, str(t3))
        # And the bot must be told the same truth the user sees.
        check("the brief says signed in once the sign-in is real",
              "(signed in)" in S.browser_brief(), S.browser_brief()[:200])
    finally:
        stop(b4); S.BROWSER = keep_browser; S.AUTH_COOKIES.pop("127.0.0.1", None); lsrv.shutdown()
    check("a site we cannot judge is called unconfirmed in the brief, not signed in",
          "not confirmed" in S.browser_brief() and "(signed in)" not in S.browser_brief(),
          S.browser_brief()[:200])

    srv.shutdown()

    print(f"\n{len(PASS)}/{len(PASS)+len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)

if __name__ == "__main__":
    main()
