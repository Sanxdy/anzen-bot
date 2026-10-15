#!/usr/bin/env python3
"""Steering: a task typed into a chat whose turn is already running is handed to that turn at its
next step, and the client is told the truth about whether it was taken.

The bug these checks pin down: the steer endpoint used to answer "the running turn has it" for as
long as the turn was in flight at all — including the stretch after the bot had written its last
word, where there is no step left to hand a steer to. The client believed it, took the task out of
its queue and drew it, and the turn then dropped it on the floor: the message vanished and the bot
never saw it. The endpoint now stops claiming a turn can be steered the moment it is past its last
step, so a steer that cannot land stays in the caller's queue and runs as the next turn instead.

Two more of the same kind, in the turn loop rather than the endpoint: a steer accepted during a step
that turns out to be the run's last is refused (there is no step after it to hand the message to),
and a turn that ends under a steer it had already taken — Stop, the clock, the budget — drains it
and says so instead of popping the deque with the message still in it.

No router needed.  Usage:  python3 tests/test_steer.py
"""
import os, sys, json, time, threading, tempfile, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as S

tmp = tempfile.mkdtemp()
S.SANDBOX = os.path.join(tmp, "sandbox"); os.makedirs(S.SANDBOX)
# Nothing below may touch the real data dir: a turn saves bots, sessions and memories.
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

# --- a stand-in model: one tool call per step, then an answer. `at` is called at the start of the
#     step numbered `n`, which is where a test drops a steer into the turn.
CALLS = []
def make_stream(plan, at=None):
    def fake_stream(model, messages, tools=None, max_tokens=1600):
        CALLS.append([m.get("content", "") for m in messages if m.get("role") == "user"])
        n = len(CALLS)
        yield ("delta", "step%d " % n)
        if at: at(n)
        if n <= plan:
            yield ("done", {"content": "", "tool_calls": [
                {"id": "c%d" % n, "type": "function",
                 "function": {"name": "list_files", "arguments": json.dumps({"path": "."})}}], "usage": {}})
        else:
            yield ("done", {"content": "done: " + messages[-1]["content"][:40], "tool_calls": [], "usage": {}})
    return fake_stream

# --- the turn is driven over the real endpoint on a loopback port, because the contract that broke
#     is the endpoint's answer, not the deque underneath it.
srv = S.Srv(("127.0.0.1", 0), S.H)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

def post(path, body):
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path),
                               data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=60).read())

def run_turn(sid, text, events, done):
    try:
        req = urllib.request.Request("http://127.0.0.1:%d/api/chat" % PORT,
                                     data=json.dumps({"session": sid, "text": text}).encode(),
                                     headers={"Content-Type": "application/json"})
        for raw in urllib.request.urlopen(req, timeout=60):
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("data:"): events.append(json.loads(line[5:]))
    finally:
        done.set()

def transcript(sid):
    return [m.get("content") or "" for m in S.load(sid).get("messages") or []]

def turn(sid, text, plan, at):
    CALLS.clear(); events = []; done = threading.Event()
    S.chat_stream = make_stream(plan, at)
    t = threading.Thread(target=run_turn, args=(sid, text, events, done)); t.start()
    return events, done, t

# --- 1. a steer lands mid-turn: taken, handed over at the next step, kept in the transcript ---
steered = threading.Event(); answer = {}
def at_step_one(n):
    if n != 1: return
    answer["r"] = post("/api/chat/steer", {"session": "producer", "text": "use the other file"})
    steered.set()
events, done, t = turn("producer", "do a long job", 3, at_step_one)
steered.wait(timeout=30); t.join(timeout=60)
ok("mid-turn steer is taken", answer["r"].get("ok") is True, answer["r"])
ok("...and reported as landing in a running turn", answer["r"].get("running") is True, answer["r"])
ok("...and the client is told, so it can draw it",
   any(e.get("type") == "steer" and e.get("text") == "use the other file" for e in events))
ok("...and the bot really read it on its next step",
   any("use the other file" in " ".join(c) for c in CALLS[1:]), CALLS)
ok("...and the transcript keeps it as the thing that turned the bot",
   "use the other file" in transcript("producer"))

# --- 2. a steer that lands while the bot is writing its last word still turns it: the turn reopens
#        rather than closing on top of the task it was just handed. ---
steered2 = threading.Event(); answer2 = {}
def at_step_two(n):
    if n != 2: return
    answer2["r"] = post("/api/chat/steer", {"session": "producer", "text": "turn once more"})
    steered2.set()
events2, done2, t2 = turn("producer", "start", 2, at_step_two)
steered2.wait(timeout=30); t2.join(timeout=60)
ok("a steer at the close point is taken", answer2["r"].get("ok") is True, answer2["r"])
ok("...and the turn reopens for it instead of closing over it",
   any("turn once more" in " ".join(c) for c in CALLS), CALLS)

# --- 3. a steer past the last step is refused, not swallowed: the turn has nothing left to hand it
#        to, so the caller keeps it and runs it as the next turn. This is the bug. ---
in_reflect = threading.Event(); answer3 = {}
def slow_reflect(*a, **k):
    in_reflect.set(); time.sleep(3.0); return []
S.reflect = slow_reflect
events3, done3, t3 = turn("producer", "finish up", 1, None)
in_reflect.wait(timeout=30)
answer3["r"] = post("/api/chat/steer", {"session": "producer", "text": "too late for this turn"})
t3.join(timeout=60)
ok("a steer past the last step is refused", answer3["r"].get("ok") is False, answer3["r"])
ok("...and it is not drawn as though the turn took it",
   not any(e.get("type") == "steer" for e in events3))
ok("...and it is not left in the transcript as a message the bot answered",
   "too late for this turn" not in transcript("producer"))

# --- 4. once the turn has ended there is nothing to steer into either, and the answer says so ---
ok("a steer with no turn running is refused",
   post("/api/chat/steer", {"session": "producer", "text": "nobody home"}).get("ok") is False)
ok("...and the closed flag does not outlive the turn",
   "producer" not in S.STEER_CLOSED and "producer" not in S.STEER)

# --- 5. a turn that ends under a steer it had already taken still accounts for it. Stop, the clock
#        and the step budget all end the turn at a point the steer was accepted past — it has no step
#        left to be handed to, so it is drained and the client is told, and the message is in the
#        record, rather than dying with the deque the turn pops on its way out. ---
S.reflect = lambda *a, **k: []                      # reflection is not what this is about
steered5 = threading.Event(); answer5 = {}
def at_step_two(n):
    if n != 2: return
    answer5["r"] = post("/api/chat/steer", {"session": "producer", "text": "stop but keep this"})
    S.STOP.add("producer")                          # the loop sees this at the top of the next step
    steered5.set()
events5, done5, t5 = turn("producer", "do a long job", 4, at_step_two)
steered5.wait(timeout=30); t5.join(timeout=60)
ok("a steer taken before a Stop was reported as taken", answer5["r"].get("ok") is True, answer5["r"])
ok("...and the turn hands it back as not taken rather than dropping it",
   any(e.get("type") == "steer" and e.get("text") == "stop but keep this" and e.get("late") for e in events5), events5)
ok("...so the client runs it as the next turn, not as a message the bot never answered",
   "stop but keep this" not in transcript("producer"))

# --- 6. a steer typed while the turn is on its last step is refused, not taken: the step after it is
#        where a steer would be handed over, and there is no step after it. The caller keeps the
#        message and runs it as the next turn, which is the whole difference from it dying here. ---
real_steps = S.max_steps
S.max_steps = lambda s: 1                           # one step a round, MAX_CONTINUATIONS rounds: three
steered6 = threading.Event(); answer6 = {}
def at_last_step(n):
    if n != 3: return
    answer6["r"] = post("/api/chat/steer", {"session": "producer", "text": "no step left for this"})
    steered6.set()
S.chat = lambda *a, **k: {"content": "wrapped up", "tool_calls": [], "usage": {}}   # the wrap-up call
events6, done6, t6 = turn("producer", "keep going", 99, at_last_step)
steered6.wait(timeout=30); t6.join(timeout=60)
S.max_steps = real_steps
ok("a steer on the turn's last step is refused", answer6["r"].get("ok") is False, answer6["r"])
ok("...and it is not drawn as though the turn took it",
   not any(e.get("type") == "steer" for e in events6), events6)
ok("...and it is not written into the record as a message the bot answered",
   "no step left for this" not in transcript("producer"))

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
