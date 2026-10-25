#!/usr/bin/env python3
"""The lead is pushed to use its team, and a teammate can be asked twice.

Delegation used to be a sentence in the lead's brief and nothing more, so a lead could
answer the whole request itself; and a teammate could be delegated to once per turn, so
build → QA finds a bug → build the fix could not happen. Both are checked here against a
scripted model — no router.

No router needed.  Usage:  python3 tests/test_delegation_lead.py
"""
import os, sys, tempfile, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as S

tmp = tempfile.mkdtemp()
S.SANDBOX = os.path.join(tmp, "sandbox"); os.makedirs(S.SANDBOX)
S.BOTS_PATH = os.path.join(tmp, "bots.json")
S.CH_PATH = os.path.join(tmp, "channels.json")
S.MEMDIR = os.path.join(tmp, "memory"); os.makedirs(S.MEMDIR)
S.SET_PATH = os.path.join(tmp, "settings.json")
S.SESS_PATH = os.path.join(tmp, "sessions.json")
S.LOGDIR = os.path.join(tmp, "logs"); os.makedirs(S.LOGDIR)
S.TOKEN_PATH = os.path.join(tmp, "access_token")
S.LAN_MARK = os.path.join(tmp, "lan")
assert S.BOTS_PATH.startswith(tmp) and S.CH_PATH.startswith(tmp), "test paths must point into tmp"
assert S.SESS_PATH.startswith(tmp) and S.LOGDIR.startswith(tmp), "a turn's writes must stay in tmp"

PASS = FAIL = 0
def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print("  PASS " + name)
    else:    FAIL += 1; print("  FAIL " + name + (("  " + str(extra)) if extra else ""))

BOTS = [
 {"id": "producer", "name": "Producer", "model": "m", "instructions": "lead the team",
  "approval": "full", "memory": False, "skills": []},
 {"id": "builder", "name": "Builder", "model": "m", "instructions": "build the thing",
  "approval": "full", "memory": False, "skills": []},
]
S.save_bots(BOTS)
S.save_channels([{"id": "room", "name": "Room", "members": ["producer", "builder"],
                  "lead": "producer", "folder": ""},
                 {"id": "solo", "name": "Solo", "members": ["producer"],
                  "lead": "producer", "folder": ""}])

def finish(text="done"):
    return {"content": "", "tool_calls": [{"id": "f", "function": {
        "name": "finish", "arguments": json.dumps({"summary": text})}}]}

def hand(role, task):
    return {"content": "", "tool_calls": [{"id": "d", "function": {
        "name": "delegate", "arguments": json.dumps({"role": role, "task": task})}}]}

def run(sid, bid, task, script):
    """One turn, with `script(step, messages, tools)` answering each model call. The messages
    every call saw are kept, because the refusal is only visible there."""
    seen = []
    def chat(model, messages, tools=None, max_tokens=1600):
        seen.append({"messages": [dict(x) for x in messages], "tools": tools or []})
        return script(len(seen), messages, tools or [])
    S.chat = chat
    out = {}
    list(S.run_agent(sid, bid, task, "", out, BOTS, {}, 0))
    return out, seen

def tool_texts(seen, n):
    return [m.get("content") or "" for m in seen[n]["messages"] if m.get("role") == "tool"]

def offered(seen, n, name):
    return any(t.get("function", {}).get("name") == name for t in seen[n]["tools"])

# --- a lead that finishes without using its team is asked once, in words ---
out, seen = run("room", "producer", "Do the thing", lambda n, m, t: finish("all done"))
ok("the lead's first finish with no delegation does not end the turn", len(seen) == 2, len(seen))
ok("...it is refused in words that name the team", any("have not handed anything to your team" in x
   for x in tool_texts(seen, 1)), tool_texts(seen, 1))
ok("...and the second finish goes through, so a one-line answer is still possible",
   out.get("text") == "all done", out.get("text"))
ok("the lead is offered `delegate` in a room with a teammate", offered(seen, 0, "delegate"))

# --- a lead that delegates is not interrupted ---
def delegating(n, m, t):
    if m[-1].get("content") == "build it": return {"content": "built it", "tool_calls": []}
    return hand("builder", "build it") if n == 1 else finish("built")
out, seen = run("room", "producer", "Do the thing", delegating)
ok("a lead that delegates gets no refusal at all", len(seen) == 3, len(seen))
ok("...and its report is what the room gets", out.get("text") == "built", out.get("text"))

# --- the same teammate can be asked again: build, then the fix ---
lead_steps = []
def twice(n, m, t):
    last = m[-1]
    if last.get("role") == "user" and last.get("content") in ("build it", "fix it"):
        return {"content": "built it" if last["content"] == "build it" else "fixed it", "tool_calls": []}
    lead_steps.append(1)
    return (hand("builder", "build it") if len(lead_steps) == 1 else
            hand("builder", "fix it") if len(lead_steps) == 2 else finish("fixed"))
out, seen = run("room", "producer", "Do the thing", twice)
ok("a teammate can be delegated to a second time in one turn", len(seen) == 5, len(seen))
ok("...the second hand-off is not refused", not any("already worked on this turn" in x
   for x in tool_texts(seen, 2)), tool_texts(seen, 2))
ok("...and the lead reads both reports", any("built it" in x for x in tool_texts(seen, 2))
   and any("fixed it" in x for x in tool_texts(seen, 4)), tool_texts(seen, 4))

# --- a member is not the lead, and a room with no teammates has no team ---
out, seen = run("room", "builder", "Do the thing", lambda n, m, t: finish("mine"))
ok("a member answering its own chat finishes without being pushed", len(seen) == 1, len(seen))
out, seen = run("solo", "producer", "Do the thing", lambda n, m, t: finish("alone"))
ok("a lead whose room has no other members is not pushed either", len(seen) == 1, len(seen))
ok("...and is not offered a `delegate` tool with nobody in it", not offered(seen, 0, "delegate"))

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
