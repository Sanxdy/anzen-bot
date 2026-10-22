#!/usr/bin/env python3
"""Taking the bot's browser from the Computer panel, and handing it back.

A person driving the page outranks the bot: while they hold it, the bot's own browser step waits
rather than being thrown away, so handing it back lets the turn carry on from where it paused — no
new message needed. The panel follows the server's `human` flag, so a reloaded tab or a second device
sees the same state, and a gesture is refused once the browser is handed back.

No router and no Chromium: the browser thread is never started, so what is checked is the state
machine every call goes through.  Usage:  python3 tests/test_computer_takeover.py
"""
import os, sys, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as S

tmp = tempfile.mkdtemp()
# Nothing here may touch the real data dir: importing the server reads its settings.
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
assert S.BOTS_PATH.startswith(tmp) and S.SESS_PATH.startswith(tmp), "test paths must point into tmp"

PASS = FAIL = 0
def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print("  PASS " + name)
    else:    FAIL += 1; print("  FAIL " + name + (("  " + str(extra)) if extra else ""))

B = S.Browser()          # constructed, not started: no thread, no Chromium, no page

ok("a bot may use the browser while nobody is driving", B._gated(False) == "")
ok("the person's own input is never gated", B._gated(True) == "")

ok("taking over succeeds", B.take() == "" and B.human, B.human)
why = B._gated(False)
ok("a queued job is still refused if the take-over lands after it was queued", why != "", why)
ok("the refusal says who has it and not to retry",
   "Computer panel" in why and "do not retry" in why, why)
ok("the person's input still passes the gate", B._gated(True) == "")
ok("the person's input reaches the page check, not the gate",
   B.human_input("click", 0.5, 0.5) == "(no page is open yet)", B.human_input("click", 0.5, 0.5))

pv = json.loads(B.preview())
ok("the panel is told a person is driving", pv.get("human") is True, str(pv))

ok("handing back succeeds", B.give() == "" and B.human == "", B.human)
ok("the bot may use the browser again", B._gated(False) == "")
ok("the panel is told the bot has it", json.loads(B.preview()).get("human") is False)
ok("a gesture after hand-back is refused",
   B.human_input("click", 0.5, 0.5) == "(take the browser first)", B.human_input("click", 0.5, 0.5))
ok("handing back twice is harmless", B.give() == "" and B.human == "")

# --- what a bot's step does while a person drives ------------------------------------------------
# The first version told the bot "do not retry, wait for them", which meant its turn ended there:
# handing the browser back restored control but nothing carried on. Now the step itself waits, so the
# bot resumes where it paused. This is the behaviour a user pressing Hand back expects, and it is
# checked here without Chromium: `_call` is stood in for, so what runs is the waiting.
import threading, time
class Probe(S.Browser):
    def start(self): pass
    def _call(self, fn, timeout=90, **a): self.ran = fn; return "ran " + fn
P = Probe()

P.take()
out = {}
t = threading.Thread(target=lambda: out.setdefault("v", P.call("click", selector="#go")), daemon=True)
t.start(); time.sleep(0.8)
ok("a bot's browser step waits while a person drives", t.is_alive(), str(out))

# The panel must still be able to act during that wait: a bot parked while holding the call lock
# would lock the person out of the page they just took — the one deadlock this feature could have.
panel = {}
pt = threading.Thread(target=lambda: panel.setdefault("v", P.call("human_input", kind="click",
                    _human=True)), daemon=True)
pt.start(); pt.join(5)
ok("the person can still act while a bot's step waits", panel.get("v") == "ran human_input", str(panel))
ok("...and that gesture reached the browser, not a refusal", "(" not in str(panel.get("v")), str(panel))

P.give(); t.join(5)
ok("the step runs the moment the browser is handed back", out.get("v") == "ran click", str(out))
ok("...so the bot carries on by itself, with no new message from the user", not t.is_alive())

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
