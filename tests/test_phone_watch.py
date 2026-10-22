#!/usr/bin/env python3
"""The phone's view of work that is already happening.

The companion is the same page as the desktop, so it should show the same thing — but the live
strip and Stop are built from turn events, and a client only receives events while it is watching
the chat those events are for. Two gaps followed from that:

  * a turn started on the desktop while the phone watched the room drew its rows but never offered
    Stop, because the composer was only re-synced by a turn this window started;
  * a turn already running when the phone opened the room — launched mid-turn, switched to from
    another chat, or woken after its screen was off — showed nothing at all: the transcript has no
    row for a turn that has not been saved yet, and the watch stream only carries what happens next.

`/api/history` now carries the running turn's state, and the page adopts it on open and on wake.

Run:  .venv/bin/python tests/test_phone_watch.py     (exit 0 = all green)
"""
import os, sys, json, time, threading, tempfile, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as S

tmp = tempfile.mkdtemp()
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
assert S.SESS_PATH.startswith(tmp), "test paths must point into tmp"

json.dump([{"id": "atlas", "name": "Atlas", "title": "Lead", "model": "m", "color": "purple"},
           {"id": "scout", "name": "Scout", "title": "Research", "model": "m", "color": "blue"}],
          open(S.BOTS_PATH, "w"))
json.dump([{"id": "growth", "name": "Growth", "members": ["atlas", "scout"], "lead": "atlas",
            "mode": "everyone"}], open(S.CH_PATH, "w"))
json.dump({}, open(S.SESS_PATH, "w"))

PASS = FAIL = 0
def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print("  PASS " + name)
    else:    FAIL += 1; print("  FAIL " + name + (("  " + str(extra)) if extra else ""))

# A room member that takes a few seconds and reports where it is at every step, so the strip has
# something to show and the checks have a window to look in. No model, no shell.
def slow_member(sid, bid, task, context, out, bots, settings, depth=0, images=None):
    yield {"type": "status", "state": "working", "agent": bid}
    yield {"type": "tool", "agent": bid, "name": "run_shell", "args": {"cmd": "sleep 1"}, "id": "t1"}
    yield {"type": "agent_text", "agent": bid, "text": "starting", "delta": True}
    time.sleep(5)
    yield {"type": "agent_text", "agent": bid, "text": " report from " + bid}
    out["text"] = "report from " + bid
S.run_agent = slow_member
S.reflect = lambda *a, **k: []
S.lucent = None

srv = S.Srv(("127.0.0.1", 0), S.H)
BASE = "http://127.0.0.1:%d/" % srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

def start_turn():
    req = urllib.request.Request(BASE + "api/chat",
                                 data=json.dumps({"session": "growth", "text": "hi", "turn": "T1"}).encode(),
                                 headers={"Content-Type": "application/json"})
    for _ in urllib.request.urlopen(req, timeout=60): pass

from playwright.sync_api import sync_playwright

def wait_for(pg, expr, ms=8000):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        if pg.evaluate(expr): return True
        pg.wait_for_timeout(100)
    return False

ROWS = "()=>document.querySelectorAll('#working .wrow').length"
STOP_HIDDEN = "()=>document.getElementById('btnStop').hidden"

with sync_playwright() as p:
    br = p.chromium.launch()
    errs = []
    def phone():
        pg = br.new_page(viewport={"width": 390, "height": 844})      # a phone
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(BASE, wait_until="load")
        pg.wait_for_timeout(1200)
        return pg

    # --- 1. watching a turn the desktop started: the strip is drawn *and* Stop is offered ---
    pg = phone()
    pg.eval_on_selector('#chans .bot[data-id="growth"]', "e=>e.click()")
    pg.wait_for_timeout(700)
    th = threading.Thread(target=start_turn); th.start()
    ok("a turn started elsewhere draws a row in the room's strip",
       wait_for(pg, ROWS + ">=1"), pg.evaluate(ROWS))
    ok("...and Stop is offered for it, though this window did not start it",
       pg.evaluate(STOP_HIDDEN) is False)

    # --- 2. a phone that was not there when it started: opening the room mid-turn shows the work ---
    pg2 = phone()
    pg2.eval_on_selector('#chans .bot[data-id="growth"]', "e=>e.click()")
    pg2.wait_for_timeout(900)
    ok("the turn is still running for the next check", th.is_alive())
    ok("a phone opened mid-turn draws the strip too", pg2.evaluate(ROWS) >= 1, pg2.evaluate(ROWS))
    ok("...and Stop with it", pg2.evaluate(STOP_HIDDEN) is False)
    row = pg2.evaluate("()=>document.querySelector('#working .wrow')?.innerText||''")
    ok("...naming the bot and what it is doing", "Atlas" in row and "Working" in row, row)
    ok("...and the step card the desktop is showing",
       pg2.evaluate("()=>!!document.querySelector('#msgs .m.bot.think')"))

    th.join(timeout=60)
    pg.wait_for_timeout(1500); pg2.wait_for_timeout(1500)
    for who, page in (("the watching phone", pg), ("the one that joined late", pg2)):
        ok("when the turn ends %s loses the strip" % who, page.evaluate(ROWS) == 0, page.evaluate(ROWS))
        ok("...and Stop with it", page.evaluate(STOP_HIDDEN) is True)
    ok("no JS errors on the way", not errs, errs[:3])
    br.close()

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.stdout.flush()
os._exit(0 if FAIL == 0 else 1)
