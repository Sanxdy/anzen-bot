#!/usr/bin/env python3
"""The link: phone -> relay -> this app, from any network.

Both ends are exercised for real — a relay server on a loopback port, a Link dialled out to it, and a
real backend on a Unix socket behind them — because the point of the thing is exactly the case the
rest of the suite cannot cover: a phone that is not on this wifi. Nothing here opens a port for the
phone to reach, and nothing is tunnelled; the app dials out and the relay meets it halfway.

No router needed.  Usage:  python3 tests/test_relay.py
"""
import http.client, json, os, socket, sys, tempfile, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as S
from relay import anzen_relay as R

tmp = tempfile.mkdtemp()
# Nothing below may touch the real data dir. Same redirects as test_folders, plus the two secrets.
S.SANDBOX = os.path.join(tmp, "sandbox"); os.makedirs(S.SANDBOX)
S.BOTS_PATH = os.path.join(tmp, "bots.json")
S.CH_PATH = os.path.join(tmp, "channels.json")
S.MEMDIR = os.path.join(tmp, "memory"); os.makedirs(S.MEMDIR)
S.SET_PATH = os.path.join(tmp, "settings.json")
S.LOGO_DIR = os.path.join(tmp, "logos")
S.SESS_PATH = os.path.join(tmp, "sessions.json")
S.LOGDIR = os.path.join(tmp, "logs"); os.makedirs(S.LOGDIR)
S.TOKEN_PATH = os.path.join(tmp, "access_token")
S.LAN_MARK = os.path.join(tmp, "lan")
S.LAN = os.path.exists(S.LAN_MARK)                  # the import read the real dir; this suite's is empty
S.RELAY_SECRET_PATH = os.path.join(tmp, "relay_secret")
assert S.BOTS_PATH.startswith(tmp) and S.TOKEN_PATH.startswith(tmp), "test paths must point into tmp"
assert S.RELAY_SECRET_PATH.startswith(tmp), "the relay secret must never be minted into the real data dir"

TOKEN = "token-4a1f"; SECRET = "secret-9c2b"
open(S.TOKEN_PATH, "w").write(TOKEN)
open(S.RELAY_SECRET_PATH, "w").write(SECRET)

PASS = FAIL = 0
def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print("  PASS " + name)
    else:    FAIL += 1; print("  FAIL " + name + (("  " + str(extra)) if extra else ""))

# --- the app, on its own channel; the relay, on a port; the two joined by a Link ---
SOCK = os.path.join(tmp, "anzen.sock")
srv = S.Srv(SOCK, S.H, family=socket.AF_UNIX)
threading.Thread(target=srv.serve_forever, daemon=True).start()

R.RelayHandler.secret = SECRET
relay = R.RelayServer(("127.0.0.1", 0), R.RelayHandler)
RPORT = relay.server_address[1]
threading.Thread(target=relay.serve_forever, daemon=True).start()

STATE = []
lk = R.Link("ws://127.0.0.1:%d/agent" % RPORT, "unix:" + SOCK, SECRET,
            on_state=lambda up, why="": STATE.append(up)).start()
for _ in range(80):
    if R.desktop() is not None: break
    time.sleep(0.05)
ok("the desktop dials out and the relay holds it", R.desktop() is not None)
ok("...and the link reported itself up", STATE and STATE[-1] is True, STATE)


def phone(method, path, headers=None, body=None, host="anzen.example.com", timeout=20):
    """One request as the phone makes it: to the relay, naming the address the phone dialled."""
    c = http.client.HTTPConnection("127.0.0.1", RPORT, timeout=timeout)
    h = {"Host": host}
    h.update(headers or {})
    c.request(method, path, body=body, headers=h)
    return c, c.getresponse()


# --- the door the phone comes through ---
_c, _r = phone("GET", "/healthz"); _r.read()
ok("healthz is not public either — a stranger with no secret is refused", _r.status == 403, _r.status)
_c.close()
_c, _r = phone("GET", "/healthz", {"X-Anzen-Relay": SECRET}); _b = _r.read().decode()
ok("the relay answers for the desktop it is holding", _r.status == 200 and '"desktop": true' in _b, _b)
_c.close()

_c, _r = phone("GET", "/"); _r.read()
ok("the app is not served to a caller with no token", _r.status == 403, _r.status)
_c.close()

_c, _r = phone("GET", "/", {"Cookie": "anzen_pair=" + TOKEN}); _b = _r.read()
ok("...and is served once the token is presented", _r.status == 200 and b"<html" in _b.lower(),
   "%s %d bytes" % (_r.status, len(_b)))
_c.close()

_c, _r = phone("GET", "/api/lan"); _r.read()
ok("the API through the relay is behind the token", _r.status == 403, _r.status)
_c.close()

_c, _r = phone("GET", "/api/lan", {"X-Anzen-Token": TOKEN}); _b = _r.read().decode()
ok("...and opens with it", _r.status == 200 and '"enabled"' in _b, "%s %s" % (_r.status, _b[:120]))
ok("...answering from an app whose LAN switch is off", '"enabled": false' in _b, _b[:160])
_c.close()

# The Host the phone dialled has to survive the trip, or the API would treat the relay's traffic as
# its own machine's. The same-origin rule is what shows it did: a page on the relay's own address is
# allowed, a page anywhere else is not.
_c, _r = phone("GET", "/api/lan", {"X-Anzen-Token": TOKEN, "Origin": "https://anzen.example.com"}); _r.read()
ok("a browser on the relay's address is same-origin and allowed", _r.status == 200, _r.status)
_c.close()
_c, _r = phone("GET", "/api/lan", {"X-Anzen-Token": TOKEN, "Origin": "https://evil.example.net"}); _r.read()
ok("...and another site's page is refused, which it could not be if the Host were loopback",
   _r.status == 403, _r.status)
_c.close()

_c, _r = phone("GET", "/api/lan", {"Cookie": "anzen_pair=" + TOKEN}); _b = _r.read().decode()
ok("the cookie the app sets works through the relay too", _r.status == 200, _r.status)
_c.close()

# The handover: `/?t=…` with the token as a header hands the app its cookie, and the link on its
# own — all a browser can send — is refused. That last part is the whole point of the relay being
# the companion's door and not a public one.
_c, _r = phone("GET", "/?t=" + TOKEN); _r.read()
ok("the link on its own, which is what a browser can send, is refused through the relay",
   _r.status == 403, _r.status)
_c.close()
_c, _r = phone("GET", "/?t=" + TOKEN, {"X-Anzen-Token": TOKEN}); _h = dict(_r.getheaders()); _r.read()
ok("the one-time link signs the app in through the relay once it proves itself",
   _r.status == 302 and "anzen_pair=" + TOKEN in (_h.get("Set-Cookie") or ""), "%s %s" % (_r.status, _h))
_c.close()
_c, _r = phone("GET", "/?t=wrong", {"X-Anzen-Token": "wrong"}); _r.read()
ok("a wrong token on that link is refused", _r.status == 403, _r.status)
_c.close()

# A stream has to arrive as it is written, not as one lump when it ends: a chat turn and the watch
# stream are both long-lived, and a buffered relay would make every turn look frozen.
_c, _r = phone("GET", "/api/watch", {"X-Anzen-Token": TOKEN})
first = _r.readline().decode().strip()
ok("a streamed reply comes back through the relay as it is written", first == ": watching", first)
_c.close()

# --- nothing about the window's own door changed ---
def unix(method, path, headers=None):
    c = http.client.HTTPConnection("localhost", timeout=20)
    c.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); c.sock.connect(SOCK)
    c.request(method, path, headers=headers or {})
    return c, c.getresponse()

_c, _r = unix("GET", "/api/lan"); _b = _r.read().decode()
ok("the window's own channel still needs no token", _r.status == 200 and '"enabled"' in _b, _r.status)
_c.close()
_c, _r = unix("GET", "/"); _r.read()
ok("...and still gets no shell on it", _r.status == 404, _r.status)
_c.close()

# The door header alone must not open anything: it is the Unix socket that makes the claim true, and
# a LAN client can send any header it likes.
S.LAN = False
lan = S.Srv(("127.0.0.1", 0), S.H)
LPORT = lan.server_address[1]
threading.Thread(target=lan.serve_forever, daemon=True).start()
c = http.client.HTTPConnection("127.0.0.1", LPORT, timeout=20)
c.request("GET", "/api/lan", headers={"Host": "192.168.1.20:%d" % LPORT, "X-Anzen-Door": "remote"})
r = c.getresponse(); r.read()
ok("a forged door header on the network opens nothing", r.status == 403, r.status)
c.close()
lan.shutdown(); lan.server_close()

# --- the relay's own rules ---
try:
    R.dial("ws://127.0.0.1:%d/agent" % RPORT, "not-the-secret"); refused = False
except Exception: refused = True
ok("a stranger with the wrong secret is refused at the handshake", refused)
ok("...leaving the real desktop in place", R.desktop() is not None)

# The relay's own health, and what it says when nothing is behind it.
_c, _r = phone("GET", "/healthz", {"X-Anzen-Relay": SECRET}); _b = _r.read().decode()
ok("healthz reports the desktop while it is dialled in", '"desktop": true' in _b, _b)
_c.close()
lk.stop()
for _ in range(80):
    if R.desktop() is None: break
    time.sleep(0.05)
_c, _r = phone("GET", "/api/lan", {"X-Anzen-Token": TOKEN}); _b = _r.read().decode()
ok("with the app closed the phone is told so, not left waiting", _r.status == 503, _r.status)
ok("...in words that name the real cause", "not running" in _b, _b)
_c.close()

# --- the settings surface the panel drives ---
ok("the relay is off and unaddressed on a fresh save", S.relay_state()["on"] is False, S.relay_state())
ok("the relay secret is this app's own, read from its file", S.relay_state()["secret"] == SECRET)
os.remove(S.RELAY_SECRET_PATH)
ok("...and minted on first use when there is none", len(S.relay_secret()) > 20)
ok("...and then kept, so a relay already set up keeps working", S.relay_secret() == S.relay_secret())
open(S.RELAY_SECRET_PATH, "w").write(SECRET)      # back to the one the relay below was started with
ok("https://host becomes wss://host/agent", S.relay_ws_url("https://anzen.example.com") == "wss://anzen.example.com/agent")
ok("a bare host is taken as https", S.relay_ws_url("anzen.example.com") == "wss://anzen.example.com/agent")
S.set_relay(on=True, url="https://anzen.example.com")
st = S.relay_state()
ok("switching it on records where the relay answers", st["on"] is True and st["url"] == "https://anzen.example.com")
ok("...and hands the phone a link, token and all", st["phone"] == "https://anzen.example.com/" and st["token"] == TOKEN, st)
S.set_relay(on=False)
ok("switching it off stops the dial-out", S.relay_state()["on"] is False and S._LINK is None)

# --- a link that is idle must not be torn down ---
# The link is quiet most of the time — a phone that is not being used sends nothing for hours — so the
# heartbeat is what keeps it open, and the read wait has to outlast the beat. A wait shorter than the
# beat makes an idle link time out and re-dial every cycle: for a few seconds in every cycle the relay
# is up with nothing behind it, and the phone is told the app is not running when it is. This is
# measured rather than assumed, so it would have caught the 20s-wait/30s-beat version.
ok("the read wait outlasts the heartbeat", R.IDLE_TIMEOUT > R.BEAT_S, "%ss vs %ss" % (R.IDLE_TIMEOUT, R.BEAT_S))

def idle_link(beat, wait, secs):
    """Hold a fresh link open doing nothing, and report the up/down it saw. The two timings are
    squeezed so the test runs in seconds instead of minutes; only their order matters."""
    keep = (R.BEAT_S, R.IDLE_TIMEOUT)
    R.BEAT_S, R.IDLE_TIMEOUT = beat, wait
    seen = []
    l2 = R.Link("ws://127.0.0.1:%d/agent" % RPORT, "unix:" + SOCK, SECRET,
                on_state=lambda up, why="": seen.append(up)).start()
    try:
        for _ in range(80):
            if seen: break
            time.sleep(0.05)
        time.sleep(secs)
    finally:
        l2.stop(); R.BEAT_S, R.IDLE_TIMEOUT = keep
    return seen

held = idle_link(beat=0.25, wait=0.75, secs=1.5)          # six beats, nothing sent
ok("an idle link is kept up across many beats", held and held[-1] is True and False not in held, held)
flapped = idle_link(beat=0.75, wait=0.25, secs=1.5)       # the old shape: the wait cuts in before the beat
ok("...and it drops when the wait is shorter than the beat, so the check bites", False in flapped, flapped)

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
