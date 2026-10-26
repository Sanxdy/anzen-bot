"""Each chat gets its own screen: two bots browsing at once must not steal each other's page.

This is the fault behind "Nico is using the computer — not this chat's bot": one shared page meant a
bot in another room took the screen from the chat you were looking at. Here two different bots open
two different sites, then each chat's panel is asked what it sees — and each must see its own.
"""
import json, os, sys, tempfile, threading, time, urllib.request
os.environ["DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, "/opt/anzen-bot")

import server as S
from http.server import ThreadingHTTPServer

PORT = 8099
srv = ThreadingHTTPServer(("127.0.0.1", PORT), S.H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
S.BROWSER.start()
time.sleep(1.0)

B = "http://127.0.0.1:%d" % PORT
def get(p, t=120):
    with urllib.request.urlopen(B + p, timeout=t) as r: return json.loads(r.read())
def post(p, body, t=180):
    req = urllib.request.Request(B + p, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=t) as r: return json.loads(r.read())

PASS = FAIL = 0
def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print("  PASS " + name)
    else:    FAIL += 1; print("  FAIL " + name + (("  -> " + str(extra)[:260]) if extra else ""))

bots = S.load_bots()
ids = [b["id"] for b in bots]
A, Bb = ids[0], ids[1]           # two different bots, so two different chats
ok("there are two bots to test with", len(ids) >= 2, ids[:6])

# --- each chat opens its own page ---
ra = post("/api/computer/open", {"session": A, "url": "https://example.com"})
rb = post("/api/computer/open", {"session": Bb, "url": "https://www.iana.org/help/example-domains"})
ok("chat A opened its page", ra.get("ok"), ra)
ok("chat B opened its page", rb.get("ok"), rb)
time.sleep(3)

# --- each chat's panel must show ITS page, not the other's ---
pa = get("/api/computer/preview?sid=" + A + "&force=1")
pb = get("/api/computer/preview?sid=" + Bb + "&force=1")
print("   A sees: %r" % (pa.get("url") or "")[:70])
print("   B sees: %r" % (pb.get("url") or "")[:70])
ok("chat A sees its own page", "example.com" in (pa.get("url") or "") and "iana" not in (pa.get("url") or ""), pa.get("url"))
ok("chat B sees its own page", "iana.org" in (pb.get("url") or ""), pb.get("url"))
ok("neither panel says another bot is using the computer",
   "is using the computer" not in (pa.get("err") or "") and "is using the computer" not in (pb.get("err") or ""),
   (pa.get("err"), pb.get("err")))
ok("A and B are different pages, not one shared one",
   (pa.get("url") or "a") != (pb.get("url") or "b"))

# --- taking over A must not pause B, and must not need A to be the lead ---
ta = post("/api/computer/take", {"session": A, "on": True})
ok("chat A can take its own screen", ta.get("ok") and ta.get("human"), ta)
pa2 = get("/api/computer/preview?sid=" + A + "&force=1")
pb2 = get("/api/computer/preview?sid=" + Bb + "&force=1")
ok("A reports being driven", pa2.get("human") is True, pa2.get("human"))
ok("B is NOT reported as being driven", pb2.get("human") is False, pb2.get("human"))
post("/api/computer/take", {"session": A, "on": False})

# --- a chat with no page says so plainly, not "someone else is using it" ---
pc = get("/api/computer/preview?sid=" + "analyst")
ok("a chat with no screen says so without naming another bot",
   "is using the computer" not in (pc.get("err") or ""), pc.get("err"))
ok("...and it has no picture", not pc.get("png"))

print("\n%d passed, %d failed" % (PASS, FAIL))
srv.shutdown()
raise SystemExit(1 if FAIL else 0)
