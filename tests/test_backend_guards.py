"""The backend's guards, checked directly — tool arguments, connector and relay URLs, deleted-session
tombstones, `_CTX` under threads, and the routine/connector/relay routes over a real loopback socket.

These are the fixes that keep a tool call from being dispatched with the wrong shape, a connected
app's token from being sent to a private or cleartext address, a deleted chat from being recreated by
a turn that outlived it, and a routine from being stored with a schedule it cannot honour. Each is
non-trivial enough that a silent regression would not be noticed, so they are pinned here rather than
in a throwaway harness.

Pure stdlib, no browser. DATA_DIR is redirected to a temp dir before `server` is imported — and every
path the server writes is re-pointed under it — so a run can never touch the user's live workspace.

    python3 tests/test_backend_guards.py
"""
import os, sys, json, tempfile, threading, socket, http.client, http.server, collections

_TMP = tempfile.mkdtemp(prefix="anzen-guards-")
os.environ["DATA_DIR"] = _TMP
os.makedirs(os.path.join(_TMP, "sandbox"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as S                                                    # noqa: E402

S.SANDBOX = os.path.join(_TMP, "sandbox")
S.BOTS_PATH = os.path.join(_TMP, "bots.json")
S.CH_PATH = os.path.join(_TMP, "channels.json")
S.MEMDIR = os.path.join(_TMP, "memory"); os.makedirs(S.MEMDIR, exist_ok=True)
S.SET_PATH = os.path.join(_TMP, "settings.json")
S.LOGO_DIR = os.path.join(_TMP, "logos")
S.SESS_PATH = os.path.join(_TMP, "sessions.json")
S.LOGDIR = os.path.join(_TMP, "logs"); os.makedirs(S.LOGDIR, exist_ok=True)
S.TOKEN_PATH = os.path.join(_TMP, "access_token")
S.LAN_MARK = os.path.join(_TMP, "lan")
assert all(getattr(S, n).startswith(_TMP) for n in
           ("BOTS_PATH", "CH_PATH", "LOGDIR", "SESS_PATH", "TOKEN_PATH", "LAN_MARK")), \
    "a data path escaped the temp dir"

PASS = FAIL = 0
def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print("  PASS " + name)
    else:    FAIL += 1; print("  FAIL " + name + (("  " + str(extra)) if extra else ""))

print("--- tool argument type validation ---")
schemas = {
    "run_shell": S._fn("run_shell", "run", {"command": {"type": "string"},
                                            "timeout": {"type": "integer"},
                                            "mode": {"type": "string", "enum": ["fast", "safe"]}},
                       ["command"]),
    "list_files": S._fn("list_files", "ls", {"path": {"type": "string"}}, ["path"]),
}
ok("an unknown tool is refused", S._validate_tool_args("nope", {}, schemas) == "unknown tool")
ok("non-object arguments are refused", S._validate_tool_args("list_files", [], schemas) == "arguments must be an object")
ok("a missing required argument is refused",
   S._validate_tool_args("run_shell", {}, schemas) == "missing required argument `command`")
ok("a wrongly typed argument is refused",
   S._validate_tool_args("run_shell", {"command": 1}, schemas) == "argument `command` must be string")
ok("a bool is not an integer",
   S._validate_tool_args("run_shell", {"command": "x", "timeout": True}, schemas)
   == "argument `timeout` must be integer")
ok("a bool is not a number",
   S._schema_type_ok(True, "number") is False and S._schema_type_ok(1, "number") is True)
ok("an out-of-enum value is refused",
   S._validate_tool_args("run_shell", {"command": "x", "mode": "wild"}, schemas)
   == "argument `mode` must be one of: fast, safe")
ok("a valid call passes", S._validate_tool_args("run_shell", {"command": "ls", "timeout": 5, "mode": "fast"}, schemas) == "")
ok("an unsupported schema feature stays permissive",
   S._validate_tool_args("list_files", {"path": "a", "extra": [1, 2]}, schemas) == "")

print("--- connector URL hygiene and credential redaction ---")
ok("a cleartext connector base is refused", bool(S.connector_url_error("http://api.github.com")))
ok("a clean https connector base is accepted", S.connector_url_error("https://api.github.com") == "")
ok("userinfo in a connector base is refused", bool(S.connector_url_error("https://u:p@api.github.com")))
ok("a query in a connector base is refused", bool(S.connector_url_error("https://api.github.com?x=1")))
ok("a fragment in a connector base is refused", bool(S.connector_url_error("https://api.github.com#f")))
ok("a loopback connector base is refused", bool(S.connector_url_error("https://127.0.0.1:8443")))
ok("the cloud metadata address is refused", bool(S.connector_url_error("https://169.254.169.254")))
ok("an empty connector base is refused", bool(S.connector_url_error("")))
ok("a credential-free base reaches the browser unchanged",
   S._public_connector_url("https://github.example.com/api/v3") == "https://github.example.com/api/v3")
ok("a base carrying userinfo never reaches the browser", S._public_connector_url("https://u:p@x.example.com") == "")
ok("a cleartext base never reaches the browser", S._public_connector_url("http://x.example.com") == "")
ent = {"token": "s3cr3t-tok", "client_id": "cid-123", "client_secret": "cs-456"}
red = S._redact_connector_text("headers: Bearer s3cr3t-tok client cid-123 cs-456", ent)
ok("a token echoed by a connector is redacted", "s3cr3t-tok" not in red and "[redacted]" in red, red)
ok("client id and secret are redacted too", "cid-123" not in red and "cs-456" not in red, red)

print("--- HTTPS/WSS relay enforcement ---")
ok("a cleartext ws relay is refused", bool(S.relay_url_error("ws://relay.example")))
ok("a cleartext http relay is refused", bool(S.relay_url_error("http://relay.example")))
ok("an https relay is accepted", S.relay_url_error("https://relay.example.com") == "")
ok("a bare host is taken as https", S.relay_url_error("relay.example.com") == "")
ok("https becomes wss /agent", S.relay_ws_url("https://anzen.example.com") == "wss://anzen.example.com/agent")
ok("an invalid relay url yields no ws url", S.relay_ws_url("ws://x") == "")
ok("set_relay refuses an invalid address", S.set_relay(on=True, url="ws://relay.example") is False)
ok("set_relay refuses cleartext even when switching off with a url", S.set_relay(on=False, url="http://relay.example") is False)
ok("set_relay still accepts switching off with no url", S.set_relay(on=False, url=None) is True)
S.set_relay(on=False, url=None)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relay"))
import anzen_relay as R                                               # noqa: E402
try:
    R.dial("ws://relay.example.com/agent", "s"); raised = None
except ValueError: raised = "ValueError"
except Exception as e: raised = type(e).__name__
ok("the link refuses a remote cleartext dial", raised == "ValueError", raised)
try:
    R.dial("ws://127.0.0.1:9/agent", ""); raised2 = None
except ValueError: raised2 = "ValueError"
except Exception as e: raised2 = type(e).__name__
ok("the link still allows a loopback cleartext dial", raised2 != "ValueError", raised2)

print("--- deleted-session tombstones, epochs and cancellation ---")
S.new_session("t-idle")
ok("a fresh session saves", S.save("t-idle", {"messages": [{"role": "user", "content": "hi"}]}) is True)
S.drop_session("t-idle")
ok("an idle delete leaves no Stop behind", "t-idle" not in S.STOP)
ok("an idle delete removes the chat", "t-idle" not in S._all_sessions())
S.new_session("t-idle")
ok("a later turn on that id is not born stopped", "t-idle" not in S.STOP)
ok("...and its write lands", S.save("t-idle", {"messages": []}) is True)

S.new_session("t-live")
S.STEER["t-live"] = collections.deque()      # stand in for an in-flight turn
S.drop_session("t-live")
ok("an in-flight delete asks the turn to stop", "t-live" in S.STOP)
ok("...and tombstones the id", "t-live" in S._DELETED_SESSIONS)
ok("...and a late write from that turn is refused", S.save("t-live", {"messages": []}) is False)
S.STEER.pop("t-live", None); S.STOP.discard("t-live"); S.STEER_CLOSED.discard("t-live")
S.new_session("t-live")
ok("a fresh turn on the id clears the tombstone", "t-live" not in S._DELETED_SESSIONS)
ok("...and saves again", S.save("t-live", {"messages": []}) is True)

S.new_session("t-ep")
S.STEER["t-ep"] = collections.deque()
S.STEER_CLOSED.discard("t-ep")
_CTXOBJ = S._SESSION_CTX
had = hasattr(_CTXOBJ, "epoch")
_old = _CTXOBJ.epoch if had else None
_CTXOBJ.epoch = S._SESSION_EPOCH.get("t-ep", 0)                # a turn captures its epoch
S.new_session("t-ep")                                         # a new turn bumps it
ok("a stale turn's write after a new session is refused",
   S.save("t-ep", {"messages": [{"role": "user", "content": "old"}]}) is False)
if had: _CTXOBJ.epoch = _old
else: del _CTXOBJ.epoch
S.STEER.pop("t-ep", None)
S.new_session("t-ep")
ok("a current write with no captured epoch still lands", S.save("t-ep", {"messages": []}) is True)

print("--- _CTX synchronization under concurrency ---")
errs = []
def _churn(n):
    try:
        for i in range(400):
            sid = "c%d" % (i % 8)
            S.ctx_set(sid, {"n": n, "i": i})
            S.ctx_get(sid); S.ctx_has(sid); S.ctx_keys()
            if i % 3 == 0: S.ctx_pop(sid)
    except Exception as e:
        errs.append(repr(e))
ts = [threading.Thread(target=_churn, args=(k,)) for k in range(8)]
[t.start() for t in ts]; [t.join() for t in ts]
ok("concurrent ctx access never raises", not errs, errs[:3])
for k in list(S.ctx_keys()): S.ctx_pop(k)

print("--- a command the app will refuse is refused once, and no card is raised for it ---")
# The refusal lives in one place. `shell_refused` decides it, `run_shell` returns it, and the agent
# loop skips the approval card because of it: a card for a command whose answer cannot change the
# outcome is one the user learns to click past, and a bot that keeps reaching for the store used to
# park the turn on it for the rest of the budget — which is what "it just stopped and hung" was.
ok("a read of the secret store is recognised", S.shell_refused("cat " + S.TOKEN_PATH) is True)
ok("the store named by its secret alone is recognised", S.shell_refused("cat access_token") is True)
ok("a Windows-style path into the store is seen through",
   S.shell_refused("type " + S.TOKEN_PATH.replace("/", "\\")) is True)
ok("a relative path into the store that names no secret is left alone",
   S.shell_refused("cat data/bots.json") is False)
ok("an ordinary command is not a refusal", S.shell_refused("ls -la") is False)
ok("a non-string command is not a refusal", S.shell_refused(None) is False)

refused = S.run_shell("cat " + S.TOKEN_PATH)
ok("run_shell turns the read away", isinstance(refused, tuple) and refused[1] == 1, refused)
ok("...with the refusal itself as its text", refused[0] == "(refused: %s)" % S.SECRET_REFUSAL, refused)

print("--- the app stopping the bot is recognised, and the bot's own failure is not ---")
# `exec_tool` hands `run_shell`'s result on prefixed with its own exit code, which is the shape the
# loop actually sees. Each of these is the app refusing rather than the command failing; a plain
# non-zero exit is deliberately not among them, or every `grep` that matched nothing would be
# reported as something the app did.
stop = S._stopped_by_us("exit 1\n(refused: %s)" % S.SECRET_REFUSAL, "Builder")
ok("a refused shell call is recognised through its exit prefix", stop == "Builder — refused: %s." % S.SECRET_REFUSAL, stop)
ok("a blocked browser url is recognised", S._stopped_by_us("(not opened — file:// page)", "Atlas").startswith("Atlas — not opened"))
ok("a tool that threw is recognised", S._stopped_by_us("(the tool raised)", "Atlas").startswith("Atlas — the tool raised"))
ok("a call whose arguments never arrived is recognised",
   S._stopped_by_us("(not run: bad args)", "Atlas").startswith("Atlas — not run: bad args"))
ok("a command's own non-zero exit is not the app stopping it",
   S._stopped_by_us("exit 1\nls: no such file or directory", "Builder") == "")
ok("a clean result is not the app stopping it", S._stopped_by_us("exit 0\nok", "Builder") == "")
ok("no result at all is not a stop", S._stopped_by_us(None, "Builder") == "")

print("--- the landing line names what stopped it, exactly once ---")
# The last line is the one a room actually reads, and a bot that retried the same refused command
# twelve times has one thing to report — a wall of identical sentences reads as noise.
land = S._wrap_up("m", [], [], "", "builder", used=["run_shell"], why="empty", notes=[stop] * 12)
ok("the landing names the tool it ran", "run_shell" in land, land)
ok("...says the app stopped it", "Stopped by the app:" in land, land)
ok("...naming the refusal", "reaches for the app's own secret store" in land, land)
ok("...and repeating it only once",
   land.count("Stopped by the app:") == 1 and land.count("refused:") == 1, land)
ok("...without doubling the full stop", ".." not in land and land.endswith(".)"), land)
plain = S._wrap_up("m", [], [], "", "builder", used=["run_shell"], why="empty")
ok("a landing with nothing to report carries no tail", "Stopped by the app:" not in plain, plain)

print("--- a room delegates to its own members and nobody else ---")
# The roster is every bot you have, not an invitation into a room. `Oracle VPS` held `vps-dev` and
# `producer`, but the lead's `delegate` tool was built from the whole roster, so its lead could hand
# work to `qa` — a bot the user never added — and that work happened off the room's floor. Both the
# enum the model is shown and the check that enforces it come from one list, so they cannot drift.
S.save_bots([
    {"id": "lead", "name": "Lead", "model": "m", "instructions": "l", "approval": "full", "memory": False, "skills": []},
    {"id": "dev",  "name": "Dev",  "model": "m", "instructions": "d", "approval": "full", "memory": False, "skills": []},
    {"id": "qa",   "name": "QA",   "model": "m", "instructions": "q", "approval": "full", "memory": False, "skills": []},
])
S.save_channels([{"id": "vps-room", "name": "VPS Room", "members": ["lead", "dev"], "lead": "lead",
                  "mode": "lead", "instructions": "", "folder": ""}])
RB = S.load_bots()

def delegate_enum(bot_id, peer_ids):
    """The `role` enum the lead would actually be shown, built the way `_agent_loop` builds it."""
    sch = S.tool_schemas(S.bot_by_id(RB, bot_id), [S.bot_by_id(RB, p) for p in peer_ids])
    d = [t for t in sch if t["function"]["name"] == "delegate"]
    return d[0]["function"]["parameters"]["properties"]["role"]["enum"] if d else None

ok("a room's lead is offered only its own members", delegate_enum("lead", ["dev"]) == ["dev"])
ok("...and a bot outside the room is not in the enum at all", "qa" not in json.dumps(delegate_enum("lead", ["dev"])))
ok("a lead with no teammates is not offered the tool", delegate_enum("lead", []) is None)
ok("outside a room the whole roster is still the team",
   sorted(delegate_enum("lead", ["dev", "qa"])) == ["dev", "qa"])
ok("a bot is never offered itself", delegate_enum("lead", ["lead", "dev"]) == ["dev"])

# The enum is a hint the model can ignore — a cached schema, a hand-rolled call, a value the
# provider let through. The run below makes the call the enum forbids, against the real loop.
real_chat = S.chat
script = {"role": "qa"}
handed = []
def stub(model, messages, tools=None, max_tokens=1600):
    """Whichever bot is asking tries the one delegation in `script`, then lands."""
    if "You are Dev." in messages[0]["content"]: return {"content": "dev did it", "tool_calls": []}
    if any(m.get("role") == "tool" for m in messages):
        handed.append(messages[-1].get("content") or "")
        return {"content": "landed", "tool_calls": []}
    return {"content": "", "tool_calls": [{"id": "t1", "function": {
        "name": "delegate", "arguments": json.dumps({"role": script["role"], "task": "audit it"})}}]}
S.chat = stub
out = {}
evs = list(S.run_agent("vps-room", "lead", "ship it", "", out, RB, {}, 0))
S.chat = real_chat

ok("the bot outside the room never starts work",
   not any(e.get("type") == "agent" and e.get("id") == "qa" for e in evs), evs)
ok("...and the call is refused rather than run", any(h.startswith("(not run:") for h in handed), handed)
ok("...the refusal names the role the room does allow",
   any("must be one of: dev" in h for h in handed), handed)
notice = [e for e in evs if e.get("type") == "notice"]
ok("...and the room is told, rather than left with a step row that did nothing", bool(notice), evs)
ok("...naming the call the app turned away", notice and "not run:" in notice[0]["text"], notice)
ok("...and attributing it to the bot that made it", notice and notice[0]["text"].startswith("Lead — "), notice)
ok("the lead carries on and lands its own turn", out.get("text") == "landed", out.get("text"))

# The same room, the same call, naming a member: the delegation is the point of the tool and must
# still work. Without this the check above would pass on a `delegate` that never runs at all.
script["role"] = "dev"; handed.clear()
S.chat = stub
out2 = {}
evs2 = list(S.run_agent("vps-room", "lead", "ship it", "", out2, RB, {}, 0))
S.chat = real_chat
ok("a delegation to a member still runs",
   any(e.get("type") == "agent" and e.get("id") == "dev" and e.get("state") == "start" for e in evs2), evs2)
ok("...and its report reaches the lead", any("dev did it" in h for h in handed), handed)
ok("...with no refusal raised", not any(e.get("type") == "notice" for e in evs2), evs2)
ok("...and the lead still lands its own turn", out2.get("text") == "landed", out2.get("text"))

print("--- a call the app turns away for its shape is reported, not just drawn ---")
# The same silent-stop gap the refusal work closed, one layer earlier: a call whose arguments do not
# match the tool was answered with a folded step row and nothing else, so a bot that kept getting the
# shape wrong went quiet with no account of it anywhere the reader looks.
sch2 = {"run_shell": S._fn("run_shell", "run", {"command": {"type": "string"},
                                               "mode": {"type": "string", "enum": ["fast", "safe"]}},
                           ["command"])}
bad = S._validate_tool_args("run_shell", {"command": "x", "mode": "wild"}, sch2)
ok("an out-of-enum value names the values that were allowed", bad == "argument `mode` must be one of: fast, safe", bad)
long_enum = {"p": S._fn("p", "p", {"k": {"type": "string", "enum": ["v%d" % i for i in range(30)]}}, ["k"])}
msg = S._validate_tool_args("p", {"k": "nope"}, long_enum)
ok("a long enum is capped rather than pasted whole", "(+18 more)" in msg and len(msg) < 140, msg)
ok("the capped message still names the first allowed values", "v0, v1" in msg, msg)
shape = "(not run: %s)" % bad
ok("the app recognises a call refused for its shape", S._stopped_by_us(shape, "Lead") == "Lead — not run: argument `mode` must be one of: fast, safe.", S._stopped_by_us(shape, "Lead"))
trunc = S._stopped_by_us("(not run: the arguments arrived truncated)", "Lead")
ok("...and one whose arguments never arrived", trunc.startswith("Lead — not run: the arguments arrived truncated"), trunc)

print("--- routines, connectors and relay over the real socket (loopback door) ---")
S.save_bots([{"id": "lead", "name": "Lead", "model": "m", "instructions": "l", "approval": "full",
              "memory": False, "skills": []}])
S.save_channels([{"id": "work-room", "name": "Work Room", "members": ["lead"], "lead": "lead",
                  "mode": "lead", "instructions": "", "folder": ""}])
S.save_routines([])
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
S.LAN = False
srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), S.H)
threading.Thread(target=srv.serve_forever, daemon=True).start()

def post(path, body):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("POST", path, body=json.dumps(body), headers={"Content-Type": "application/json"})
    r = c.getresponse(); data = r.read(); c.close()
    try: return r.status, json.loads(data or b"{}")
    except Exception: return r.status, {}

st, j = post("/api/routine", {"prompt": "standup", "session": "work-room", "bot": "lead", "every": 60})
ok("a routine naming both a room and a bot is refused", st == 400 and "room routine" in j.get("error", ""), (st, j))
st, j = post("/api/routine", {"prompt": "standup", "session": "work-room", "every": 60})
ok("a room routine with no bot is accepted", st == 200 and j.get("ok"), (st, j))
st, j = post("/api/routine", {"prompt": "x", "session": "ghost-room", "every": 60})
ok("a routine on an unknown session is refused", st == 400, (st, j))
st, j = post("/api/routine", {"prompt": "x", "session": "work-room", "cron": "not a cron"})
ok("a malformed cron is refused", st == 400, (st, j))
st, j = post("/api/routine", {"prompt": "x", "session": "work-room", "every": True})
ok("a bool interval is refused", st == 400, (st, j))
st, j = post("/api/routine", {"prompt": "x", "session": "work-room"})
ok("a routine with no schedule is refused", st == 400, (st, j))
S.save_routines([])

st, j = post("/api/connector", {"id": "github", "base_url": "http://api.github.com"})
ok("a cleartext connector base is refused at the route", not j.get("ok") and "https" in j.get("error", ""), (st, j))
st, j = post("/api/connector", {"id": "github", "base_url": "https://u:p@api.github.com"})
ok("a connector base with userinfo is refused at the route", not j.get("ok"), (st, j))
st, j = post("/api/connector", {"id": "github", "base_url": "https://127.0.0.1:9"})
ok("a loopback connector base is refused at the route", not j.get("ok"), (st, j))
st, j = post("/api/connector", {"id": "github", "token": "ghp_TOPSECRET", "base_url": "https://1.1.1.1/api/v3"})
ok("a clean connector base and token are accepted", j.get("ok") is True and j.get("connected") is True, (st, j))
pub = json.dumps(S.settings_public(S.load_settings()))
ok("the saved token never reaches the browser", "ghp_TOPSECRET" not in pub, pub[:200])
ok("the public base url is credential-free", "https://1.1.1.1/api/v3" in pub)

st, j = post("/api/relay", {"on": True, "url": "ws://relay.example"})
ok("a cleartext relay url is refused at the route", not j.get("ok"), (st, j))
st, j = post("/api/relay", {"on": True, "url": "http://127.0.0.1:9"})
ok("a loopback relay url is refused at the route", not j.get("ok"), (st, j))
st, j = post("/api/relay", {"on": True, "url": "https://1.1.1.1"})
ok("a valid relay url is accepted and recorded as wss",
   j.get("ok") is True and S.relay_ws_url(S.load_settings().get("relay", {}).get("url") or "") == "wss://1.1.1.1/agent",
   (st, j, S.load_settings().get("relay")))
st, j = post("/api/relay", {"on": False})
ok("the relay switches off again", j.get("ok") is True, (st, j))
srv.shutdown()

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
