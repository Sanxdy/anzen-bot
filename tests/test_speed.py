#!/usr/bin/env python3
"""Self-checks for the speed / long-turn changes, against a throwaway data dir. No server, no
browser — it imports server.py and pokes the internals it just grew:

  * the in-memory session and settings caches (write-through, copy-on-read)
  * append-only context compaction (`_compact`) vs the old mid-transcript drop
  * the parallel-vs-serial split for one step's tool calls (`_serial_call`)
  * the turn stop flag and its wrap-up wording

Run:  .venv/bin/python tests/test_speed.py
"""
import os, sys, tempfile, json

tmp = tempfile.mkdtemp(prefix="anzen-speed-")
os.environ["DATA_DIR"] = tmp
os.environ["SANDBOX_DIR"] = os.path.join(tmp, "sandbox")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server

PASS = []; FAIL = []
def check(name, ok, extra=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + (f"  {extra}" if extra and not ok else ""))

# --- sessions: a save is visible to the next load without a re-read, and the cache is the truth.
server.SESS_PATH = os.path.join(tmp, "sessions.json")
server._SESS["d"] = None; server._SESS["path"] = None
st = server.load("chat-1"); st["messages"].append({"role": "user", "content": "hi"})
server.save("chat-1", st)
check("session round-trips through the cache", server.load("chat-1")["messages"][-1]["content"] == "hi")
check("session file was written", os.path.isfile(server.SESS_PATH))

# --- settings: save_settings is seen by the next load_settings, which hands out a copy.
server.SET_PATH = os.path.join(tmp, "settings.json")
server._SET["d"] = None; server._SET["path"] = None
s = server.load_settings(); s["appearance"]["theme"] = "light"; server.save_settings(s)
check("settings round-trip through the cache", server.load_settings()["appearance"]["theme"] == "light")
copy = server.load_settings(); copy["appearance"]["theme"] = "dark"
check("load_settings hands out a copy, not the cache",
      server.load_settings()["appearance"]["theme"] == "light")

# --- _compact: trims OLD tool output in place, keeps the newest whole, pins the ask, same length.
def tool(i, n=4000):
    return {"role": "tool", "tool_call_id": "c%d" % i, "name": "run_shell", "content": "x" * n}
msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "the ask"}]
for i in range(12): msgs.append(tool(i))
before = len(msgs)
trimmed = server._compact(msgs, 1000)
check("_compact trims old tool output", trimmed > 0, "trimmed=%r" % trimmed)
check("_compact keeps the message list the same length", len(msgs) == before)
check("_compact pins the ask", msgs[1]["content"] == "the ask")
check("_compact keeps the newest tool results whole", len(msgs[-1]["content"]) == 4000)
check("_compact stubs the oldest", len(msgs[2]["content"]) <= server.TOOL_STUB_CHARS)
check("_compact leaves nothing more to trim at the same budget", server._compact(msgs, 1000) == 0)
check("_compact reports 0 when there is room", server._compact(list(msgs[:4]), 100000) == 0)

# --- _serial_call: delegation, finish, and an unapproved risky shell are serial; plain reads are not.
check("delegate is serial", server._serial_call("delegate", {}, "ask"))
check("finish is serial", server._serial_call("finish", {}, "ask"))
check("risky shell under Ask is serial", server._serial_call("run_shell", {"command": "rm -rf /"}, "ask"))
check("safe shell is parallel-safe", not server._serial_call("run_shell", {"command": "ls"}, "ask"))
check("shell under Full is parallel-safe", not server._serial_call("run_shell", {"command": "rm -rf /"}, "full"))
check("read_file is parallel-safe", not server._serial_call("read_file", {"path": "a"}, "ask"))

# --- _exec_parallel: results come back in the model's order, even out of order in time.
import time as _t
def slow(name, args): _t.sleep(0.05 if name == "b" else 0.0); return ("ran " + name, [])
_real = server.exec_tool
server.exec_tool = lambda bid, name, args: slow(name, args)
calls = [( {"id": "1"}, "a", {}), ({"id": "2"}, "b", {}), ({"id": "3"}, "c", {})]
out = server._exec_parallel("producer", calls)
server.exec_tool = _real
check("_exec_parallel preserves the model's order", [r[0] for r in out] == ["ran a", "ran b", "ran c"])

# --- run_shell's timeout: the caller's number is honoured, a junk value falls back instead of
#     raising, and a huge one is accepted (it is clamped to 600s inside, so it still returns).
out, rc = server.run_shell("sleep 3", 1)
check("run_shell honours a short timeout", rc == 124 and "1s" in out, "out=%r rc=%r" % (out, rc))
out, rc = server.run_shell("echo ok", "not-a-number")
check("run_shell survives a junk timeout", rc == 0 and "ok" in out, "out=%r rc=%r" % (out, rc))
out, rc = server.run_shell("echo ok", 99999)
check("run_shell accepts a large timeout", rc == 0 and "ok" in out, "out=%r rc=%r" % (out, rc))

# --- stop flag + wrap-up wording.
server.STOP.add("chat-1")
check("stop flag reads back", "chat-1" in server.STOP)
server.STOP.discard("chat-1")
check("stop flag clears", "chat-1" not in server.STOP)
check("there is a stop wrap-up note", "stop" in server.STOP_NOTE.lower())
# `_wrap_up` with no finish tool offered and nothing said falls through to a reason line that names
# why the turn ended — the seam the loop uses when it breaks out for stop/time/steps.
check("wrap-up names a user stop", "user stopped" in server._wrap_up("m", [], [], "", "b", why="stop").lower())
check("wrap-up names a time-out", "ran out of time" in server._wrap_up("m", [], [], "", "b", why="time").lower())

# --- the turn's landing. The loop's tail is an if/elif/else — `stopped`, `timed_out`, then the
# step-cap branch. That last one used to be a bare `else`, so a bot that *finished* (which sets
# `done` and breaks out of the step loop) fell straight into it: its answer was replaced by a
# second wrap-up model call and the turn was reported as "max_steps". A normal finish must land on
# its own text, unlabelled, with no extra call.
_bots = server.load_bots()
_bid = _bots[0]["id"]
_calls = {"stream": 0, "chat": 0}

def _fake_stream(model, msgs, tools=None, **k):
    _calls["stream"] += 1
    yield ("done", {"content": "THE ANSWER", "usage": {},
                    "tool_calls": [{"id": "f1", "function": {
                        "name": "finish", "arguments": json.dumps({"summary": "THE ANSWER"})}}]})

def _fake_chat(model, msgs, **k):
    _calls["chat"] += 1
    return {"content": "WRAP-UP", "usage": {},
            "tool_calls": [{"id": "w", "function": {"name": "finish",
                           "arguments": json.dumps({"summary": "WRAP-UP"})}}]}

_real_stream, _real_chat = server.chat_stream, server.chat
server.chat_stream, server.chat = _fake_stream, _fake_chat
_landing = {}
try:
    list(server.run_agent("landing", _bid, "do a thing", "", _landing, _bots, {}, 0))
finally:
    server.chat_stream, server.chat = _real_stream, _real_chat
check("a finished turn keeps its own answer", _landing.get("text") == "THE ANSWER", "text=%r" % _landing.get("text"))
check("a finished turn pays no wrap-up call", _calls["chat"] == 0, "chat calls=%d" % _calls["chat"])
check("a finished turn is not labelled max_steps", _landing.get("stop") is None, "stop=%r" % _landing.get("stop"))

# --- _decide_room: a room with one member is decided without spending a model call on the obvious.
_solo = _bots[0]["id"]
_real_chat2 = server.chat
def _no_chat(*a, **k): raise AssertionError("_decide_room called the model for a one-member room")
server.chat = _no_chat
try:
    check("a one-member room picks without a model call", server._decide_room({"members": [_solo]}, _bots, "hi") == _solo)
finally:
    server.chat = _real_chat2

# --- wait_approval takes the caller's own waiter, so the slot exists before the card is on screen —
# an answer that lands in that gap is otherwise read as a denial (see `/api/approve`).
_ev = server.threading.Event(); server.APPROVAL["waittest"] = {"event": _ev, "allow": True}; _ev.set()
check("wait_approval reads a pre-registered waiter", server.wait_approval("waittest", _ev, max_wait=5) is True)
check("wait_approval pops the slot it was handed", "waittest" not in server.APPROVAL)

# --- the bounded note/log file helpers: one shared append keeps the header + newest, one read is capped.
mp = server.mem_path("tester")
for i in range(server.MEM_MAX_LINES + 20): server.mem_append("tester", "note %d" % i)
lines = open(mp, encoding="utf-8").read().splitlines()
check("mem_append bounds the file", len(lines) <= server.MEM_MAX_LINES, "lines=%d" % len(lines))
check("mem_append keeps the header", lines[0] == "# Notes")
check("mem_append keeps the newest", "note %d" % (server.MEM_MAX_LINES + 19) in lines[-1])
check("mem_read is capped by lines", len(server.mem_read("tester", limit_lines=3).splitlines()) <= 3)
server.log_append("tester", "did a thing")
check("log_append writes the entry", "did a thing" in server.log_read("tester"))
check("log_append keeps the work-log header", open(server.log_path("tester"), encoding="utf-8").readline().strip() == "# Work log")

# --- the turn's clock is opt-in: none unless a machine sets one. A wall-clock cap fires on work that is
# merely slow, and slow is what real browser work is, so the step budget is the bound (see
# DEFAULT_TURN_SECONDS).
check("there is no turn clock by default", server.max_seconds({"context": {}}) == 0)
check("...and the shipped default really is no cap", server.DEFAULT_TURN_SECONDS == 0)
check("max_seconds honours a save", server.max_seconds({"context": {"max_seconds": 30}}) == 30)
check("a nonsense clock reads as no clock, not a broken range",
      server.max_seconds({"context": {"max_seconds": -5}}) == 0
      and server.max_seconds({"context": {"max_seconds": "abc"}}) == 0)

# --- est_tokens: a cheap chars/4 estimate off the fields, not a full re-serialization.
m1 = [{"role": "user", "content": "x" * 400}]
check("est_tokens is about chars/4", 90 <= server.est_tokens(m1) <= 120, server.est_tokens(m1))
check("est_tokens grows with content", server.est_tokens([{"role": "user", "content": "y" * 4000}]) > server.est_tokens(m1))
check("est_tokens counts tool_calls", server.est_tokens(
    [{"role": "assistant", "content": "", "tool_calls": [{"id": "1", "function": {"name": "run_shell", "arguments": "{}"}}]}])
    > server.est_tokens([{"role": "assistant", "content": ""}]))

# --- _mint_token: one definition for the relay secret and the LAN token.
tp = os.path.join(tmp, "tok")
a = server._mint_token(tp)
check("_mint_token mints a token", bool(a) and a == server._mint_token(tp))
check("_mint_token writes it 0600", (os.stat(tp).st_mode & 0o777) == 0o600)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
