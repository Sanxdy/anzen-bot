#!/usr/bin/env python3
"""The model path's stall guard, against a real loopback socket — no router, no tokens spent.

A router that holds the socket open and sends nothing but keepalives used to hang a turn forever. The
`timeout=` handed to urlopen is per read, not a deadline on the call, so every keepalive comment line
reset it and `chat_stream` never came back; the turn's own budgets did not help, because the step clock
is only read at the top of a step, and the turn writes its report only at the end. The result was a bot
that went silent for eighteen minutes with nothing to show for it.

So the stubs here are the routers that hang a turn and the routers that are merely slow, and the checks
say which of the two is abandoned, which is left to finish, and what the room is told when one is.

The second half is the retry policy that grew out of that eighteen-minute turn: an attempt that said
nothing at all is tried again (up to the policy — see DEFAULT_MODEL_RETRIES), an attempt that had already
streamed a delta never is, and the notice that reaches the room carries the tries and the time they cost
rather than a count of unrelated blips inside an hour.

Pure stdlib. DATA_DIR is redirected to a temp dir before `server` is imported — the same isolation the
guard suite uses — so a run can never touch the user's live workspace.

    python3 tests/test_model_stall.py
"""
import os, sys, time, json, socket, tempfile, threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

_TMP = tempfile.mkdtemp(prefix="anzen-stall-")
os.environ["DATA_DIR"] = _TMP
os.environ["SANDBOX_DIR"] = os.path.join(_TMP, "sandbox")
os.makedirs(os.path.join(_TMP, "sandbox"), exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as S                                                    # noqa: E402

assert S.DATA.startswith(_TMP), "DATA_DIR was not redirected: %r" % S.DATA
for _n in ("SESS_PATH", "BOTS_PATH", "SET_PATH", "LOGDIR"):
    assert getattr(S, _n).startswith(_TMP), "%s escaped the temp dir: %r" % (_n, getattr(S, _n))

PASS = FAIL = 0
def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print("  PASS " + name)
    else:    FAIL += 1; print("  FAIL " + name + (("  " + str(extra)) if extra else ""))

# --- a stub router, one mode per router this has to survive.
MODE = "trickle"
HITS = {}                                # requests served, per mode: the fallback is a second call
class Router(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def do_POST(self):
        HITS[MODE] = HITS.get(MODE, 0) + 1
        try: self.rfile.read(int(self.headers.get("Content-Length") or 0))
        except Exception: pass
        try: self._route()
        except Exception: pass          # the client abandoned us: there is nothing left to answer
    def _head(self, chunked):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        # Real routers frame an SSE stream both ways, so the guard is exercised against both.
        self.send_header("Transfer-Encoding" if chunked else "Connection",
                         "chunked" if chunked else "close")
        self.end_headers()
    def _send(self, data, chunked):
        if chunked: data = b"%x\r\n%s\r\n" % (len(data), data)
        self.wfile.write(data); self.wfile.flush()
    def _delta(self, text, chunked):
        self._send(('data: {"choices":[{"delta":{"content":%s}}]}\n\n' % json.dumps(text)).encode(),
                   chunked)
    def _route(self):
        if MODE == "trickle":
            # The shape that hung the turn: a warm socket, keepalive lines, no content, no [DONE].
            self._head(True)
            for _ in range(40):                     # 8s of it, then the stub gives up
                self._send(b": keepalive\n\n", True); time.sleep(0.2)
        elif MODE == "keepalive_then_answer":
            # The same keepalives, with real content every 0.9s: a model that is slow, not gone.
            self._head(True)
            for i in range(3):
                for _ in range(3):
                    self._send(b": keepalive\n\n", True); time.sleep(0.3)
                self._delta("part%d " % i, True)    # 0.9s, 1.8s, 2.7s — past the stall budget, in
            self._send(b"data: [DONE]\n\n", True)   # total, but never that long without content
            self.wfile.write(b"0\r\n\r\n"); self.wfile.flush()
        elif MODE == "think_then_answer":
            # A model thinking before its first token: no bytes at all for a while, then an answer.
            self._head(False)
            time.sleep(0.6)
            self._delta("hello ", False); time.sleep(0.6); self._delta("world", False)
            self._send(b"data: [DONE]\n\n", False)
            self.close_connection = True
        elif MODE == "plain_body":
            # A router that ignored `stream:true` and answered with one JSON body — with no trailing
            # newline, so the answer only exists as the tail of a line that never ended.
            body = json.dumps({"choices": [{"message": {"content": "plain answer"}}]}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body); self.wfile.flush()
        elif MODE == "body_then_trickle":
            # The same one-shot body, and then a socket that is never closed and never stops talking.
            # The answer is already in hand, so the stall must not throw it away.
            body = (json.dumps({"choices": [{"message": {"content": "whole answer"}}]}) + "\n").encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Connection", "close"); self.end_headers()
            self.wfile.write(body); self.wfile.flush()
            for _ in range(100):
                self._send(b" ", False); time.sleep(0.1)
        elif MODE == "trickling_body":
            # A one-shot answer that never ends: a byte every 0.1s, no Content-Length, no close.
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Connection", "close"); self.end_headers()
            for _ in range(100):
                self._send(b" ", False); time.sleep(0.1)
        elif MODE == "comments_only":
            # A stream that carried nothing but keepalive comments and then ended. The comments are
            # the transport keeping the socket warm, not the model's answer, so this is "nothing
            # came" — but the line collector took every non-`data:` line for a one-shot body, so the
            # comments were parsed as JSON, and the failure the room was shown was the Python
            # exception that raised: "substring not found".
            self._head(True)
            for _ in range(4):
                self._send(b": keepalive\n\n", True); time.sleep(0.02)
            self.wfile.write(b"0\r\n\r\n"); self.wfile.flush()
        elif MODE == "not_a_completion":
            # A 200 that is not a completion at all: an error page behind the router.
            body = b"<html><body>502 Bad Gateway</body></html>"
            self.send_response(200); self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body); self.wfile.flush()
        elif MODE == "truncated_args":
            # A tool call whose arguments stop arriving mid-JSON — the app refuses to run a call it
            # cannot read, and that refusal is a `notice`. It is the cheapest deterministic app-caused
            # stop, which makes it the right probe for whether a notice survives the reload.
            self._head(False)
            if HITS[MODE] == 1:
                frag = ('data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
                        '"function":{"name":"run_shell","arguments":"{\\"command\\": \\"ls "}}]}}]}\n\n')
                self._send(frag.encode(), False)
            else:
                self._delta("done", False)
            self._send(b"data: [DONE]\n\n", False)
            self.close_connection = True
        elif MODE == "stall_once_then_answer":
            # The shape the user hit, and the one a retry is for: nothing at all on the first try, a
            # normal answer on the second. Silent for the whole stall budget, then keepalives, because
            # a router that dropped the call does not hang up either.
            self._head(True)
            if HITS[MODE] == 1:
                for _ in range(40):
                    self._send(b": keepalive\n\n", True); time.sleep(0.2)
            else:
                self._delta("second try", True)
                self._send(b"data: [DONE]\n\n", True)
                self.wfile.write(b"0\r\n\r\n"); self.wfile.flush()
        elif MODE == "delta_then_trickle":
            # Half an answer, then silence. The bot has already spoken, so this stall must be reported
            # rather than retried: a second attempt would append a second answer to the first.
            self._head(True)
            self._delta("half an answer", True)
            for _ in range(40):
                self._send(b": keepalive\n\n", True); time.sleep(0.2)

_srv = ThreadingHTTPServer(("127.0.0.1", 0), Router)
_srv.daemon_threads = True
threading.Thread(target=_srv.serve_forever, daemon=True).start()
S.ROUTER = "http://127.0.0.1:%d" % _srv.server_address[1]
S.KEY = "stub-key"

STALL = 1.0                                   # a one-second budget, so the checks run in seconds

# The retry policy lives in settings and reaches the model client as module globals, so the suite sets it
# through the same door the settings screen uses — which is also the check that the sync works. One second
# of silence per attempt is the fast, deterministic stall the checks below were written against, and the
# suite pins the attempt count on the global directly: a saved 0 means "use the built-in default", so
# "one try" is not something a setting can say.
def policy(stall=STALL, retries=1):
    s = S.load_settings(); s.setdefault("context", {})
    s["context"]["model_stall_seconds"] = stall; s["context"]["model_retries"] = retries
    S.save_settings(s)

ok("the built-in policy is three tries of two minutes each",
   S.DEFAULT_MODEL_RETRIES == 2 and S.DEFAULT_MODEL_STALL_SECONDS == 120,
   (S.DEFAULT_MODEL_RETRIES, S.DEFAULT_MODEL_STALL_SECONDS))
policy(77, 4)
ok("a saved policy re-aims the globals the model client reads",
   S.MODEL_RETRIES == 4 and S.MODEL_STALL_SECONDS == 77, (S.MODEL_RETRIES, S.MODEL_STALL_SECONDS))
policy(0, 0)
ok("0 in a save means the built-in default, not zero",
   S.MODEL_RETRIES == S.DEFAULT_MODEL_RETRIES and S.MODEL_STALL_SECONDS == S.DEFAULT_MODEL_STALL_SECONDS,
   (S.MODEL_RETRIES, S.MODEL_STALL_SECONDS))
policy()
S.MODEL_RETRIES = 0                              # one try, as the checks below were written
ok("the suite's own budget is one second a try, and one try",
   S.MODEL_STALL_SECONDS == STALL and S.MODEL_RETRIES == 0, (S.MODEL_STALL_SECONDS, S.MODEL_RETRIES))

def run(mode, stall=STALL, attempts=None):
    """One `chat_stream` against the stub, timed. Returns (events, elapsed). `attempts` caps the tries
    for this call alone; None follows the policy (one try, as the suite saved it)."""
    global MODE
    MODE = mode; S.MODEL_STALL_SECONDS = stall
    t0 = time.time()
    events = list(S.chat_stream("stub", [{"role": "user", "content": "hi"}], attempts=attempts))
    return events, time.time() - t0

def done_of(events): return [v for k, v in events if k == "done"][-1]
def text_of(events): return "".join(v for k, v in events if k == "delta")

print("--- a router that only keeps the socket warm is abandoned ---")
ev, took = run("trickle")
ok("the call returns instead of hanging", took < 2.5 * STALL, "took %.1fs" % took)
ok("it is reported as a stalled model", done_of(ev).get("stalled") is True, done_of(ev))
ok("it carries the model-error marker the turn lands on",
   done_of(ev)["content"].startswith("[model error"), done_of(ev)["content"][:80])
ok("no half-formed tool call is handed to the turn", done_of(ev)["tool_calls"] == [])

print("--- a model that is merely slow is left to finish ---")
ev, took = run("think_then_answer")
ok("a model silent before its first token is not cut off", text_of(ev) == "hello world", text_of(ev))
ok("it is not reported as stalled", not done_of(ev).get("stalled"), done_of(ev))
ok("it ends on its own answer", done_of(ev)["content"] == "hello world", done_of(ev)["content"][:80])

print("--- content is progress; keepalives are not ---")
ev, took = run("keepalive_then_answer")
ok("a turn that outlives the budget on content still finishes", text_of(ev) == "part0 part1 part2 ",
   text_of(ev))
ok("it is not reported as stalled", not done_of(ev).get("stalled"), done_of(ev))
ok("it really did run longer than the stall budget", took > STALL, "took %.1fs" % took)

print("--- a router that ignores `stream` is still read as an answer ---")
HITS.clear(); ev, took = run("plain_body")
ok("one JSON body, with no trailing newline, is the answer",
   done_of(ev)["content"] == "plain answer", done_of(ev)["content"][:80])
ok("it is not reported as stalled", not done_of(ev).get("stalled"), done_of(ev))
ok("...and costs no second call to get it", HITS.get("plain_body") == 1, "requests=%r" % HITS)
HITS.clear(); ev, took = run("body_then_trickle")
ok("an answer already in hand survives a socket that never closes",
   done_of(ev)["content"] == "whole answer", done_of(ev)["content"][:80])
ok("...and is not thrown away as a stall", not done_of(ev).get("stalled"), done_of(ev))
ok("...and still costs no second call", HITS.get("body_then_trickle") == 1, "requests=%r" % HITS)

print("--- a stream that carried only keepalives is nothing, not an answer ---")
HITS.clear(); ev, took = run("comments_only", attempts=1)
ok("a comment-only stream is never quoted back as the reason the model failed",
   "substring not found" not in done_of(ev)["content"], done_of(ev)["content"][:120])
ok("...and the room is told something it can act on instead",
   "not a completion" in done_of(ev)["content"] or done_of(ev).get("stalled") is True,
   done_of(ev)["content"][:120])
ok("...and the one-shot fallback is tried, since nothing was streamed",
   HITS.get("comments_only", 0) > 1, "requests=%r" % HITS)

print("--- a body that is not a completion is named, not parsed ---")
MODE = "not_a_completion"; S.MODEL_STALL_SECONDS = STALL
msg = S.chat("stub", [{"role": "user", "content": "hi"}], attempts=1)
ok("an error page is not reported as a Python exception",
   "substring not found" not in msg["content"], msg["content"][:120])
ok("...it quotes what the router actually said, which is the part that can be acted on",
   "502 Bad Gateway" in msg["content"], msg["content"][:140])

print("--- the non-streaming fallback has a deadline too ---")
MODE = "trickling_body"; S.MODEL_STALL_SECONDS = STALL
t0 = time.time(); msg = S.chat("stub", [{"role": "user", "content": "hi"}], timeout=STALL)
took = time.time() - t0
ok("a body that trickles forever is cut off", took < 2.5 * STALL, "took %.1fs" % took)
ok("and comes back as the same visible error", msg["content"].startswith("[model error"), msg["content"])
ok("...and is named as a stall, so the turn can report it with the same numbers",
   msg.get("stalled") is True, msg)

print("--- the turn it was hanging lands a report and says why ---")
bots = S.load_bots(); bid = bots[0]["id"]
MODE = "trickle"; S.MODEL_STALL_SECONDS = STALL
out = {}
t0 = time.time()
events = list(S.run_agent("stall-chat", bid, "do a thing", "", out, bots, {}, 0))
took = time.time() - t0
notices = [e for e in events if e.get("type") == "notice"]
ok("the turn ends quickly rather than hanging", took < 3 * STALL, "took %.1fs" % took)
ok("the turn lands a report", bool((out.get("text") or "").strip()), "text=%r" % out.get("text"))
ok("the report says the model stopped answering",
   "stopped answering" in (out.get("text") or ""), "text=%r" % out.get("text"))
ok("the turn is labelled stalled, not just empty", out.get("stop") == "stalled", "stop=%r" % out.get("stop"))
ok("the room is told, in a notice, why the step was abandoned — and which endpoint did it",
   any("stopped answering" in n["text"] and S._endpoint_label() in n["text"] for n in notices),
   "notices=%r" % [n["text"][:70] for n in notices])

print("--- a stop the app caused is written to the transcript, not only streamed ---")
# The notice machinery exists so the user is told what happened, but it lived only on the stream: the
# card was drawn while the turn ran and the redraw at the end wiped it, so reopening the chat showed the
# work and not one word of why. These checks pin the row into the transcript, on both write paths.
MODE = "truncated_args"; HITS.clear(); S.MODEL_STALL_SECONDS = STALL
sid = "notice-chat"
S.new_session(sid, bot=bid, title="notice")
events = list(S._run_turn_inner(sid, "run the thing", bots, {}, solo=bid, learn=[]))
rows = S.load(sid)["messages"]
notes = [m for m in rows if m.get("role") == "notice"]
ok("the 1:1 turn streams the notice", any(e.get("type") == "notice" for e in events))
ok("and it is saved to the transcript", len(notes) >= 1, rows[-3:])
ok("the saved row says what the app refused",
   bool(notes) and "truncated" in notes[0]["content"], notes[:1])
ok("the turn still lands its answer", (S.load(sid)["messages"][-1].get("content") or "") == "done",
   S.load(sid)["messages"][-1])

MODE = "truncated_args"; HITS.clear()
room = {"id": "notice-room", "name": "Room", "members": [bid], "lead": bid, "mode": "lead"}
S.new_session("notice-room", title="Room")
room_events = list(S._channel_turn("notice-room", "run the thing", room, bots, {}, raw="run the thing"))
room_rows = S.load("notice-room")["messages"]
room_notes = [m for m in room_rows if m.get("role") == "notice"]
ok("the room streams the notice too", any(e.get("type") == "notice" for e in room_events))
ok("and the room keeps it after a redraw", len(room_notes) >= 1, room_rows[-3:])

print("--- a chat whose room is gone says so instead of going quiet ---")
# The smallest silent stop: a scoped id that resolves to nothing opened a stream and closed it, so the
# user's own message blinked out in the redraw and no reason was given for the empty panel.
ghost = list(S._run_turn("ghost-room/atlas", "hello", bots, {}, channel=None, solo=None))
ok("an unresolvable scoped chat reports the problem", any(e.get("type") == "error" for e in ghost), ghost)
ok("and the message says what to do",
   any("no longer exists" in (e.get("msg") or "") for e in ghost), ghost)

print("--- a stall names the culprit, and calls out a run of them ---")
# A stall is not this app's doing, so the one thing the report must carry is *which* endpoint and model
# went quiet, and whether it is a habit — that is what turns "it hung again" into a decision. What counts
# as a habit is a *run*: failures that follow one another with no answer between them. Unrelated blips an
# hour apart are three transients, and telling the user to move off a router that is working is noise.
_keep_router = S.ROUTER
S.ROUTER = "https://router.example.com/v1"
ok("the endpoint label is the host — no key, no path",
   S._endpoint_label() == "router.example.com", S._endpoint_label())
S.ROUTER = _keep_router

S.MODEL_RETRIES = 0                              # one try: this section is about the report, not the retry
MODE = "trickle"; S.MODEL_STALL_SECONDS = STALL; S._stalls.clear()
stub_host = S._endpoint_label()
first = list(S.run_agent("stall-1", bid, "go", "", {}, bots, {}, 0))
n1 = [e["text"] for e in first if e.get("type") == "notice" and "stopped answering" in e["text"]]
ok("the notice names the endpoint that went quiet",
   bool(n1) and stub_host in n1[0], n1[:1])
ok("...and the model", bool(n1) and (bots[0].get("model") or "") in n1[0], n1[:1])
ok("a first stall reads as a one-off, with the tries and the wait it cost",
   bool(n1) and "Tried 1 time" in n1[0] and "in total" in n1[0] and "in a row" not in n1[0], n1[:1])
ok("...and a plain retry suggestion, not a verdict on the router",
   bool(n1) and "another model" in n1[0] and "it is the router, not the task" not in n1[0], n1[:1])
second = list(S.run_agent("stall-2", bid, "go", "", {}, bots, {}, 0))
n2 = [e["text"] for e in second if e.get("type") == "notice" and "stopped answering" in e["text"]]
ok("a repeat from the same endpoint is reported as a run, not as a fresh surprise",
   bool(n2) and "2nd turn in a row it has failed" in n2[0], n2[:1])
ok("...and tells the user what to do about it",
   bool(n2) and "switch this bot" in n2[0], n2[:1])

print("--- the run is consecutive, and any answer ends it ---")
S._stalls.clear()
ok("note_stall counts a run of failures", S.note_stall("m") == 1 and S.note_stall("m") == 2, S._stalls)
S.note_answer("m")
ok("note_answer resets the run", S.note_stall("m") == 1, S._stalls)
ok("the run is per endpoint+model, so a different one starts fresh",
   S.note_stall("some-other-model") == 1, S._stalls)
S._stalls.clear()
MODE = "trickle"; S.MODEL_RETRIES = 0
list(S.run_agent("streak-1", bid, "go", "", {}, bots, {}, 0))          # a failure: the run is at one
MODE = "think_then_answer"
answered = {}
list(S.run_agent("streak-ok", bid, "go", "", answered, bots, {}, 0))   # an answer ends it
ok("a turn that gets an answer resets the endpoint's run", not S._stalls, S._stalls)
ok("...and the turn really did answer", answered.get("text") == "hello world", answered.get("text"))
MODE = "trickle"
after = list(S.run_agent("streak-2", bid, "go", "", {}, bots, {}, 0))
n3 = [e["text"] for e in after if e.get("type") == "notice" and "stopped answering" in e["text"]]
ok("so the next stall is a fresh one-off, not the second of a run",
   bool(n3) and "in a row" not in n3[0] and "Tried 1 time" in n3[0], n3[:1])
S._stalls.clear()

print("--- a stall with nothing streamed is retried, and the turn succeeds ---")
# The case the user hit: the router sent nothing at all, and then worked. On the old code the first stall
# ended the step — which is what the first check below pins, with the retry turned off — so the second one
# is the check the policy exists to turn green.
S.MODEL_RETRIES = 0
MODE = "stall_once_then_answer"; HITS.clear()
once = {}
list(S.run_agent("stall-once", bid, "do a thing", "", once, bots, {}, 0))
ok("with the retry off, the same stub ends the step",
   once.get("stop") == "stalled" and once.get("text") != "second try",
   (once.get("stop"), once.get("text")))
S.MODEL_RETRIES = 2                              # the default policy: three tries
MODE = "stall_once_then_answer"; HITS.clear()
retried = {}
events = list(S.run_agent("stall-retry", bid, "do a thing", "", retried, bots, {}, 0))
ok("the stub really was asked a second time",
   HITS.get("stall_once_then_answer") == 2, "requests=%r" % HITS)
ok("the turn succeeds on the retry", retried.get("text") == "second try", "text=%r" % retried.get("text"))
ok("...and is not labelled stalled", retried.get("stop") is None, "stop=%r" % retried.get("stop"))
ok("...and the room is not told the model stopped answering",
   not any(e.get("type") == "notice" and "stopped answering" in e["text"] for e in events),
   [e["text"][:60] for e in events if e.get("type") == "notice"])

print("--- a stall after the bot has spoken is never retried ---")
# The one thing a retry must not do: append a second answer to a first one the client has already seen.
MODE = "delta_then_trickle"; HITS.clear()
ev, took = run("delta_then_trickle")
ok("the half-answer that was streamed reaches the client", text_of(ev) == "half an answer", text_of(ev))
ok("it is reported as stalled", done_of(ev).get("stalled") is True, done_of(ev))
ok("...as stopping part-way, not as a router that said nothing",
   done_of(ev).get("spoke") is True and done_of(ev).get("attempts") == 1, done_of(ev))
ok("...and it costs no second attempt", HITS.get("delta_then_trickle") == 1, "requests=%r" % HITS)
MODE = "delta_then_trickle"; HITS.clear()
part = list(S.run_agent("stall-part", bid, "go", "", {}, bots, {}, 0))
pn = [e["text"] for e in part if e.get("type") == "notice" and "stopped answering" in e["text"]]
ok("a turn that stalled part-way is reported as stopping part-way",
   bool(pn) and "part-way" in pn[0], pn[:1])

print("--- the notice carries the numbers the user asked for ---")
S.MODEL_RETRIES = 2
MODE = "trickle"; HITS.clear()
ev, took = run("trickle", stall=0.5)
ok("every attempt really was made", HITS.get("trickle") == 3, "requests=%r" % HITS)
ok("...and the report says how many tries", done_of(ev).get("attempts") == 3, done_of(ev))
ok("...and how long they waited", done_of(ev).get("waited", 0) >= 1.5, done_of(ev))
MODE = "trickle"; HITS.clear()
three = list(S.run_agent("stall-three", bid, "go", "", {}, bots, {}, 0))
n3 = [e["text"] for e in three if e.get("type") == "notice" and "stopped answering" in e["text"]]
ok("the notice says how many tries it made and what they cost",
   bool(n3) and "Tried 3 times" in n3[0] and "in total" in n3[0], n3[:1])
ok("...and names the run of failures rather than a count in a window",
   bool(n3) and "in a row it has failed" in n3[0] and "last hour" not in n3[0], n3[:1])

print("--- the landing call is a single attempt ---")
# `_wrap_up` runs when the turn is already out of budget or the model is known dead: retrying there would
# add the policy's own six minutes to a turn that has given up.
S.MODEL_RETRIES = 2
_calls = {"n": 0}
_real_post = S._post
def _dead_post(path, body, timeout=None):
    _calls["n"] += 1; raise socket.timeout("no answer")
S._post = _dead_post
try:
    land = S._wrap_up("m", [{"role": "user", "content": "x"}],
                      [{"type": "function", "function": {"name": "finish", "parameters": {}}}],
                      "", "builder", used=["run_shell"])
finally:
    S._post = _real_post
ok("the wrap-up asks the model exactly once, whatever the policy says",
   _calls["n"] == 1, "posts=%d" % _calls["n"])
ok("...and still lands on what the bot actually did", "run_shell" in land, land)
S.MODEL_RETRIES = 0
S._stalls.clear()

print("--- the CDP reader is bounded too: a trickled frame cannot pin the browser thread ---")
# The same trap one file over. The browser thread is single, so a peer that trickles a frame pins it and
# every later browser call silently becomes "(browser timeout)". The turn itself is bounded by
# `Browser.call`, but the thread is not — this is what bounds the frame.
import threading as _th
_ws_srv = socket.socket(); _ws_srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
_ws_srv.bind(("127.0.0.1", 0)); _ws_srv.listen(1)
_ws_port = _ws_srv.getsockname()[1]
def _trickler():
    c, _ = _ws_srv.accept()
    try:
        buf = b""
        while b"\r\n\r\n" not in buf:                 # the upgrade request
            d = c.recv(4096)
            if not d: return
            buf += d
        c.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n\r\n")
        c.sendall(bytes([0x81, 100]))                 # fin+text, unmasked, payload length 100
        for _ in range(30):                           # trickle 30 of the 100 bytes, then hang up: the
            c.sendall(b"x"); time.sleep(0.2)          # frame never completes, which is what used to
        c.close()                                     # block — forever, on the old per-read timeout
    except Exception:
        pass
_th.Thread(target=_trickler, daemon=True).start()
ws = S._WS("ws://127.0.0.1:%d/devtools/page/1" % _ws_port, timeout=5)
t0 = time.time()
try:
    ws.recv(deadline=time.time() + STALL); raised = None
except Exception as e:
    raised = e
took = time.time() - t0
ok("a frame that never completes ends the call instead of the thread",
   raised is not None and took < 2.5 * STALL, "raised=%r took=%.1fs" % (raised, took))
ok("...and it is a timeout, which the caller already treats as a dead browser",
   isinstance(raised, (TimeoutError, socket.timeout)), raised)
try: ws.close()
except Exception: pass

print()
print("  %d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
