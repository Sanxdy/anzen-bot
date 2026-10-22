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
import os, sys, json, tempfile, threading, socket, time, http.client, http.server, collections, queue

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
# The preset tree is app assets beside the shell, so it is redirected the same way: a clip fixture
# must never land in the real `faces/`.
S.PRESET_DIR = os.path.join(_TMP, "presets")
assert all(getattr(S, n).startswith(_TMP) for n in
           ("BOTS_PATH", "CH_PATH", "LOGDIR", "SESS_PATH", "TOKEN_PATH", "LAN_MARK", "PRESET_DIR")), \
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

print("--- the store is private, and a password box is never typed into ---")
# config.json carries the router key and settings.json the connector secrets; a file written before
# this was tightened would still be readable by every account on the machine.
_saved = os.path.join(_TMP, "saved.json")
S._save_json(_saved, {"key": "secret"})
ok("a saved JSON is readable only by its owner", (os.stat(_saved).st_mode & 0o777) == 0o600,
   oct(os.stat(_saved).st_mode & 0o777))
ok("...and holds what was written", json.load(open(_saved)) == {"key": "secret"})

print("--- a bot's file tools cannot reach the store ---")
# A bot whose folder is the app dir (or a parent like `~`) passes the containment test for every
# path inside it, so `read_file` could open settings.json and `write_file` could rewrite it, with no
# card either way. `_in_sandbox` is the one gate all five file tools go through, and it refuses the
# store itself now, by the same rule `_file_path` and `run_shell` already used.
_APP = os.path.realpath(tempfile.mkdtemp(prefix="anzen-app-"))
os.makedirs(os.path.join(_APP, "data"))
open(os.path.join(_APP, "data", "access_token"), "w").write("tok")
_real_data, _real_wd = S.DATA, S.work_dir()
S.DATA = os.path.join(_APP, "data")
S.set_work_dir(_APP)
try:
    ok("a file in the bot's own folder is still reachable",
       S._in_sandbox("notes.md") == os.path.join(_APP, "notes.md"), S._in_sandbox("notes.md"))
    ok("the pairing token is refused", S._in_sandbox("data/access_token") is None)
    ok("settings are refused", S._in_sandbox(os.path.join(_APP, "data", "settings.json")) is None)
    ok("...and a write through the tool itself lands nowhere",
       S.exec_tool("b", "write_file", {"path": "data/settings.json", "content": "{}"})[0] == "(path outside sandbox)")
    # The desktop app's working folder *is* the store, and the rule above refused every write it made:
    # a turn's file never appeared. The store's own files are refused there; anything else is not.
    S.set_work_dir(os.path.join(_APP, "data"))
    ok("a bot whose folder is the app dir can still write an ordinary file",
       S._in_sandbox("notes.md") == os.path.join(_APP, "data", "notes.md"), S._in_sandbox("notes.md"))
    ok("...but not the pairing token", S._in_sandbox("access_token") is None)
    ok("...nor the settings", S._in_sandbox("settings.json") is None)
finally:
    S.DATA = _real_data; S.set_work_dir(_real_wd)

class _FakePage:
    def __init__(self, kind): self.kind = kind; self.filled = []
    def locator(self, sel): return self
    def evaluate(self, js): return self.kind == "password"
    def fill(self, sel, text): self.filled.append(text)
    def wait_for_timeout(self, ms): pass
def typed(kind):
    b = S.Browser.__new__(S.Browser); b.page = _FakePage(kind)
    return b.type("#f", "hunter2"), b.page.filled
msg, filled = typed("password")
ok("a password field is refused and nothing is typed", filled == [] and "password" in msg, (msg, filled))
msg, filled = typed("text")
ok("an ordinary field still types", filled == ["hunter2"], filled)

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

print("--- a first-run secret is minted once, and a lookup never races a delete ---")
_tokpath = os.path.join(S.DATA, "mint-race-token")
_minted = []
_bar = threading.Barrier(8)
def _mint():
    _bar.wait(); _minted.append(S._mint_token(_tokpath))
_ts = [threading.Thread(target=_mint) for _ in range(8)]
[t.start() for t in _ts]; [t.join() for t in _ts]
_on_disk = open(_tokpath).read().strip()
ok("every caller gets the token the file holds", _minted and all(t == _on_disk for t in _minted), _minted)

errs = []
# A tiny switch interval is what makes the delete land between the lookup and the read reliably.
_sw = sys.getswitchinterval(); sys.setswitchinterval(1e-6)
def _lookup():
    try:
        for _ in range(300): S.load("race-id"); S.new_session("race-id", bot="b")
    except Exception as e: errs.append(repr(e))
def _delete():
    for _ in range(300):
        S.new_session("race-id", bot="b"); S.drop_session("race-id")
_r = [threading.Thread(target=_lookup) for _ in range(4)]
[t.start() for t in _r]; _d = threading.Thread(target=_delete); _d.start()
[t.join() for t in _r]; _d.join()
sys.setswitchinterval(_sw)
ok("a read of a chat being deleted never raises", not errs, errs[:3])

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

print("--- no bot reaches another browser's profile, cookies or keychain ---")
# A bot browses with the browser this app launches. It read Arc's profile off disk through
# `run_shell`, so another browser's data is now a refusal of the same kind as the secret store: the
# answer cannot change the outcome, so no card is raised for it. Ordinary work that merely mentions
# cookies or a browser is untouched, or the guard would refuse half of a front-end repo.
for cmd in ("ls ~/Library/Application Support/Arc/User Data/Profile 2",
            'sqlite3 ~/Library/Application\\ Support/Arc/User\\ Data/Profile\\ 2/Cookies "select 1"',
            "cat '/Users/x/Library/Application Support/Google/Chrome/Default/Login Data'",
            "sqlite3 ~/.mozilla/firefox/abc/cookies.sqlite .dump",
            "ls ~/Library/Safari/History.db",
            "security find-internet-password -s premierleague.com"):
    ok("refused: " + cmd[:48], S.shell_refused(cmd) is True)
for cmd in ("grep -rn Cookies app.js", "cat docs/cookies.md", "git log --oneline", "ls -la"):
    ok("allowed: " + cmd, S.shell_refused(cmd) is False)
fb = S.run_shell("ls ~/Library/Application Support/Arc")
ok("run_shell turns the Arc read away", fb[1] == 1 and "another browser" in fb[0], fb)

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

print("--- a lead can hand a task to every teammate, not just the first three ---")
# The lead's brief says "at most once per teammate per turn", and that is the whole rule. A hard cap
# of three on top of it turned a six-bot room into a three-bot room: the three it cut off were told
# "delegation limit reached" and reported nothing, which reads as a team that ignored the job.
S.save_bots([{"id": "lead", "name": "Lead", "model": "m", "instructions": "l", "approval": "full",
              "memory": False, "skills": []}] +
            [{"id": "m%d" % i, "name": "M%d" % i, "model": "m", "instructions": "x",
              "approval": "full", "memory": False, "skills": []} for i in range(1, 7)])
S.save_channels([{"id": "big-room", "name": "Big Room", "lead": "lead", "mode": "lead",
                  "members": ["lead"] + ["m%d" % i for i in range(1, 7)],
                  "instructions": "", "folder": ""}])
BIG = S.load_bots()
def big_stub(model, messages, tools=None, max_tokens=1600):
    """The lead hands out six tasks in one step; each member answers, then the lead lands."""
    if "You are Lead." not in messages[0]["content"]: return {"content": "did it", "tool_calls": []}
    if any(m.get("role") == "tool" for m in messages): return {"content": "landed", "tool_calls": []}
    return {"content": "", "tool_calls": [
        {"id": "t%d" % i, "function": {"name": "delegate",
                                       "arguments": json.dumps({"role": "m%d" % i, "task": "audit it"})}}
        for i in range(1, 7)]}
S.chat = big_stub
big_out = {}
big_evs = list(S.run_agent("big-room", "lead", "ship it", "", big_out, BIG, {}, 0))
S.chat = real_chat
started = [e["id"] for e in big_evs if e.get("type") == "agent" and e.get("state") == "start"]
ok("every member of a six-bot team is handed its task", started == ["m%d" % i for i in range(1, 7)], started)
ok("...and none is refused for a limit", not any("delegation limit" in json.dumps(e) for e in big_evs), big_evs)
ok("...so the lead still lands its own turn", big_out.get("text") == "landed", big_out.get("text"))

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
# The app's own server class, not the stock one: its accept queue is wide enough for the concurrent
# bursts below (the stock backlog of 5 resets a few of eight simultaneous connects at random).
srv = S.Srv(("127.0.0.1", port), S.H)
threading.Thread(target=srv.serve_forever, daemon=True).start()

def post(path, body):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("POST", path, body=json.dumps(body), headers={"Content-Type": "application/json"})
    r = c.getresponse(); data = r.read(); c.close()
    try: return r.status, json.loads(data or b"{}")
    except Exception: return r.status, {}

def post_short(path, raw, length):
    """POST a body the client never finishes — a phone that lost wifi mid-upload. The socket is
    half-closed so the server's read hits EOF short of the Content-Length it was promised."""
    s = socket.create_connection(("127.0.0.1", port), timeout=10)
    s.sendall(("POST %s HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
               "Content-Length: %d\r\n\r\n" % (path, length)).encode() + raw)
    s.shutdown(socket.SHUT_WR)
    data = b""
    while True:
        chunk = s.recv(4096)
        if not chunk: break
        data += chunk
    s.close()
    return int(data.split(b" ")[1])

def get(path, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", path, headers=headers or {})
    r = c.getresponse(); data = r.read(); hdrs = dict(r.getheaders()); c.close()
    return r.status, data, hdrs

print("--- a body that did not arrive whole is refused, not read as empty ---")
# A body cut short by a dropped connection used to parse to `{}` and be accepted: `/api/chat` then
# answered 200 and died mid-turn on a missing `text`, and the attachments were dropped in silence.
ok("a truncated POST body is a 400, not an empty request",
   post_short("/api/chat", b'{"session": "work-room", "text": "hi"', 200) == 400)
ok("a JSON null body is a 400, not a 500", post("/api/chat", None)[0] == 400)
st, j = post("/api/chat", {"session": "work-room"})
ok("a chat with no text and no attachments is a 400", st == 400 and not j.get("ok"), (st, j))

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

# A hand-edited record without a prompt can never run. It used to be dispatched, fail on the missing
# key, and be marked run anyway — so it never ran again and nothing ever reached a client.
S.save_routines([{"id": "no-prompt", "session": "work-room", "every": 1}])
ok("a routine with no prompt is never due", S._due(S.load_routines()[0], time.time()) is False)
_real_turn0, ran = S._run_turn, []
S._run_turn = lambda *a, **k: ran.append(a) or iter(())
S._RT_LIVE[0] += 1
try:
    S._run_routine({"id": "no-prompt", "session": "work-room", "every": 1},
                   S.load_bots(), S.load_settings(), S.load_channels())
finally:
    S._run_turn = _real_turn0
ok("...and dispatching it starts no turn", not ran, ran)
S.save_routines([])

# A routine's prompt is stored as a user message so it can drive a turn, but it is not the user's:
# with no `who` every transcript drew it under the user's own name ("Client" by default).
_real_turn, seen = S._run_turn, {}
def _fake_turn(sid, text, bots, settings, **kw):
    seen.update(kw, sid=sid, text=text); return iter(())
S._run_turn = _fake_turn
S._RT_LIVE[0] += 1
try:
    S._run_routine({"id": "r1", "session": "work-room", "prompt": "standup"},
                   S.load_bots(), S.load_settings(), S.load_channels())
finally:
    S._run_turn = _real_turn
ok("a routine's turn is marked as the routine's, not the user's", seen.get("who") == "Routine", seen)
ok("...and a message you typed still carries no who", "who" not in S._user_message("hi", None, False))

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

# The shape check alone lets `..` through, so a request no client normalised is what proves the
# containment rule is the one that answers.
_c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
_c.request("GET", "/api/upload/../bots.json")
_r = _c.getresponse(); _r.read(); _c.close()
ok("an upload path that climbs out of its folder is not served", _r.status == 404, _r.status)

def make_bot(i): post("/api/bot", {"bot": {"name": "Race %d" % i, "model": "m"}})
ts = [threading.Thread(target=make_bot, args=(i,)) for i in range(8)]
[t.start() for t in ts]; [t.join() for t in ts]
names = {b["name"] for b in S.load_bots()}
ok("concurrent bot saves do not lose one another",
   all("Race %d" % i in names for i in range(8)), sorted(names))

def patch_setting(i): post("/api/settings", {"settings": {"probe_%d" % i: i}})
ts = [threading.Thread(target=patch_setting, args=(i,)) for i in range(6)]
[t.start() for t in ts]; [t.join() for t in ts]
st_now = S.load_settings()
ok("concurrent settings saves do not lose one another",
   all(st_now.get("probe_%d" % i) == i for i in range(6)), st_now)

print("--- a second answer to one card never writes a denial ---")
# Two answers to one card — a double-click, or the desktop and the phone — are the normal case. The
# first wakes the turn, which pops the waiter; the second then lands on the transcript's `pending`.
# It used to append "(command denied by user)" whatever the answer was, so an allowed command that
# really ran was recorded as refused.
S.new_session("approve-chat", bot="lead")
def answer(allow):
    st = S.load("approve-chat"); st["pending"] = {"cmd": "ls"}; S.save("approve-chat", st)
    return post("/api/approve", {"session": "approve-chat", "allow": allow})[1]
def said(sid):
    return [m.get("content") or "" for m in S.load(sid).get("messages") or []]
j = answer(True)
ok("a stale card answered Allow is resolved, not denied",
   j.get("ok") is True and j.get("resolved") is True, j)
ok("...and no denial is written", not any("command denied" in m for m in said("approve-chat")), said("approve-chat"))
ok("...and the card is gone", S.load("approve-chat").get("pending") is None)
answer(False)
ok("a stale card answered Deny still says the command was denied",
   any("command denied by user" in m for m in said("approve-chat")), said("approve-chat"))

print("--- a watcher that fell behind still learns the turn ended ---")
# One `agent_text` per token overflows the 64-slot queue on a slow phone. Losing the tail of that
# stream used to lose `done` with it, and the client kept the chat `running: true` for ever.
q = S._watching()
try:
    for i in range(64): S._fanout({"type": "agent_text", "text": str(i)})
    S._fanout({"type": "done"})
    got = []
    while True:
        try: got.append(q.get_nowait())
        except queue.Empty: break
    ok("a full queue still carries the turn's end", bool(got) and got[-1].get("type") == "done", got[-2:])
    ok("...by dropping the oldest delta, not the newest", len(got) == 64 and got[0].get("text") == "1", got[:2])
finally:
    S._unwatch(q)

q = S._watching()
try:
    S._fanout({"type": "done"})
    for i in range(63): S._fanout({"type": "agent_text", "text": str(i)})
    S._fanout({"type": "agent_text", "text": "late"})
    got = []
    while True:
        try: got.append(q.get_nowait())
        except queue.Empty: break
    ok("a later delta never pushes a queued end out", any(e.get("type") == "done" for e in got) and len(got) <= 64,
       len(got))
finally:
    S._unwatch(q)

print("--- a duplicated bot does not inherit the source's browser logins ---")
# Saved profiles are keyed by account name on this machine, not by bot: copied, the duplicate would
# inherit a login the user never granted it, and both bots would drive one profile. Its picture is a
# file named by the source's id, so the reference goes too rather than point at a URL that 404s.
post("/api/bot", {"bot": {"name": "Copy Me", "model": "m", "avatar": 3,
                          "browser": [{"name": "fpl", "sites": "fantasy.premierleague.com"}]}})
st, j = post("/api/bot/duplicate", {"id": "copy-me"})
cp = S.bot_by_id(S.load_bots(), "copy-me-copy")
ok("the copy is made", st == 200 and cp is not None, (st, j))
ok("...without the source's browser accounts", cp is not None and cp.get("browser") == [], cp)
ok("...and without a picture file it does not have",
   cp is not None and cp.get("avatar") == 0 and cp.get("avatar_closed") == 0, cp)
ok("...while the source keeps both", S.bot_by_id(S.load_bots(), "copy-me").get("browser") != [])

print("--- one face batch at a time, even for two clicks ---")
# Both requests used to pass a bare `if FACE_JOB["running"]` before either set it, so both batches
# ran: double the image spend and two writers on bots.json. The flag is now claimed under a lock
# before the loading, so a second request while the first is in flight is turned away.
os.makedirs(S.FACES_DIR, exist_ok=True)
open(os.path.join(S.FACES_DIR, "src.png"), "wb").write(b"\x89PNG\r\n\x1a\n")
S._save_json(S.FACES_BATCH_PATH, {"source": "src.png"})
_park = threading.Event(); _real_worker = S._face_worker
S._face_worker = lambda *a: _park.wait(10)
try:
    st, j = post("/api/faces/generate", {})
    ok("the first request starts a batch", j.get("ok") is True and j.get("job", {}).get("running") is True, (st, j))
    st2, j2 = post("/api/faces/generate", {})
    ok("...and a second one while it runs is refused", j2.get("ok") is False and "still being drawn" in j2.get("error", ""), (st2, j2))
finally:
    S.FACE_JOB["running"] = False; _park.set(); S._face_worker = _real_worker

print("--- preset clips: listed from disk, served whole or in one range, never off-path ---")
# Clips are optional app assets beside the preset frames, so the folder is empty in a fresh
# checkout: every check below builds its own fixture under the redirected PRESET_DIR. The bytes
# are not a real WebM — these routes move bytes and never parse the container.
CLIP = bytes(range(256)) * 4
_cd = os.path.join(S.PRESET_DIR, "cat", "clips")
os.makedirs(_cd, exist_ok=True)
open(os.path.join(_cd, "idle.webm"), "wb").write(CLIP)
open(os.path.join(_cd, "celebrate.mp4"), "wb").write(CLIP[:16])
open(os.path.join(_cd, "notes.txt"), "wb").write(b"not a clip")

st, body, _ = get("/api/clips/cat")
j = json.loads(body or b"{}")
ok("the listing names only the clips that exist",
   st == 200 and j == {"ok": True, "clips": {"celebrate": "/api/clip/cat/celebrate.mp4",
                                             "idle": "/api/clip/cat/idle.webm"}}, (st, j))
st, body, _ = get("/api/clips/cat-grey")
ok("a preset with no clips folder answers an empty map, not an error",
   st == 200 and json.loads(body or b"{}").get("clips") == {}, (st, body))
ok("an unknown preset id is a 404", get("/api/clips/nope")[0] == 404)
ok("...on the clip route too", get("/api/clip/nope/idle.webm")[0] == 404)
# The drawn mascot — every room, and every bot without a preset — has a shared clip set of its own.
ok("the drawn mascot can have clips: an empty map until one exists",
   get("/api/clips/mochi")[0] == 200 and
   json.loads(get("/api/clips/mochi")[1] or b"{}").get("clips") == {})
_md = os.path.join(S.PRESET_DIR, "mochi", "clips")
os.makedirs(_md, exist_ok=True)
open(os.path.join(_md, "idle.webm"), "wb").write(CLIP)
st, body, h = get("/api/clip/mochi/idle.webm")
ok("...and one of its clips is served like a preset's",
   st == 200 and body == CLIP and h.get("Content-Type") == "video/webm", (st, len(body or b"")))
ok("a missing clip is a 404", get("/api/clip/cat/sleeping.webm")[0] == 404)
ok("a file in the clips folder that is not a clip is not served", get("/api/clip/cat/notes.txt")[0] == 404)
ok("a traversal that climbs out of the folder is refused", get("/api/clip/cat/../../server.py")[0] == 404)
ok("...and the encoded form is refused too", get("/api/clip/cat/..%2F..%2Fserver.py")[0] == 404)

st, body, h = get("/api/clip/cat/idle.webm")
ok("a full request answers 200 with every byte",
   st == 200 and body == CLIP and h.get("Content-Length") == str(len(CLIP)), (st, len(body)))
ok("...typed as video/webm", h.get("Content-Type") == "video/webm", h.get("Content-Type"))
ok("...private, sandboxed and sniff-proof",
   h.get("Cache-Control") == "private, max-age=3600"
   and h.get("Content-Security-Policy") == "default-src 'none'; sandbox"
   and h.get("X-Content-Type-Options") == "nosniff", h)
st, body, h = get("/api/clip/cat/celebrate.mp4")
ok("an mp4 clip is typed as video/mp4", h.get("Content-Type") == "video/mp4", h.get("Content-Type"))

st, body, h = get("/api/clip/cat/idle.webm", {"Range": "bytes=10-19"})
ok("a range request answers 206 with just those bytes",
   st == 206 and body == CLIP[10:20] and h.get("Content-Range") == "bytes 10-19/%d" % len(CLIP)
   and h.get("Content-Length") == "10" and h.get("Content-Type") == "video/webm", (st, len(body), h))
st, body, h = get("/api/clip/cat/idle.webm", {"Range": "bytes=9999-"})
ok("an unsatisfiable range answers 416 with the size",
   st == 416 and h.get("Content-Range") == "bytes */%d" % len(CLIP), (st, h.get("Content-Range")))
st, body, h = get("/api/clip/cat/idle.webm", {"Range": "bytes=abc"})
ok("a malformed range answers 416 too", st == 416, st)
srv.shutdown()

print("--- a failed write never reaches the cache, and a card waits for a person ---")
before = S.load_settings()
bad = json.loads(json.dumps(before)); bad["probe_write"] = "never"
real_save = S._save_json
def _boom(*a, **k): raise OSError("disk full")
S._save_json = _boom
try:
    try: S.save_settings(bad); raised = False
    except OSError: raised = True
finally: S._save_json = real_save
ok("a settings write that fails is not published to the cache", raised and S.load_settings() == before)
ok("an approval card has a budget of its own, in minutes", S.APPROVAL_WAIT >= 300, S.APPROVAL_WAIT)
ok("the handler drops a connection that goes silent", 0 < S.H.timeout <= 120, S.H.timeout)

print("--- a save keeps its own temp file, and a read is bounded by one clock ---")
import base64 as _b64
PNGD = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
logo_url = "data:image/png;base64," + _b64.b64encode(PNGD).decode()
ldir = os.path.join(_TMP, "race-logos")
saved = []
ts = [threading.Thread(target=lambda: saved.append(S._save_image(ldir, "same", logo_url))) for _ in range(8)]
[t.start() for t in ts]; [t.join() for t in ts]
ok("every concurrent save of one picture succeeds", all(r.get("ok") for r in saved), saved[:3])
ok("...and no half-written temp file is left behind",
   not [f for f in os.listdir(ldir) if f.endswith(".tmp")], os.listdir(ldir))
ok("...and the stored picture is the one that was sent",
   open(os.path.join(ldir, "same.png"), "rb").read() == PNGD)
# A failed write must not take the old logo with it: the older format goes only once the new file
# is in place.
real_mk = S.tempfile.mkstemp
S.tempfile.mkstemp = lambda **kw: (_ for _ in ()).throw(OSError("disk full"))
try:
    failed = S._save_image(ldir, "same", "data:image/gif;base64,"
                           + _b64.b64encode(b"GIF89a" + b"\x00" * 32).decode())
finally: S.tempfile.mkstemp = real_mk
ok("a save that fails leaves the logo that was there",
   failed.get("ok") is False and open(os.path.join(ldir, "same.png"), "rb").read() == PNGD, failed)

class _Trickle:
    n = 0
    def read1(self, n):
        self.n += 1; time.sleep(0.05); return b"x" if self.n < 100 else b""
try: S._read_deadline(_Trickle(), 0.02); raised = False
except socket.timeout: raised = True
ok("a response that trickles is cut at the deadline, not per read", raised)

class _NoHandshake:
    closed = False
    def request(self, *a, **k): raise S.MCPError("no handshake")
    def notify(self, *a, **k): pass
    def close(self): self.closed = True
mc = S.MCPClient.__new__(S.MCPClient); mc.t = _NoHandshake(); mc.info = ""; mc.tools = []; mc.by_safe = {}
try: mc.start()
except S.MCPError: pass
ok("a failed MCP handshake closes the process it spawned", mc.t.closed)

print("--- a turn's duration rides on the assistant row, never on a typed message ---")
# The clock spans the whole turn — model steps and tool calls — and only `run_agent`'s `finally`
# sees every way it can end. A turn that dies on a stall or an exception still took that long, so
# the value must be set before the log write and on the path out, not on the happy branch alone.
real_stream = S.chat_stream
def quick_stream(model, messages, tools=None, max_tokens=None, attempts=None):
    yield ("done", {"content": "done already", "tool_calls": []})
S.chat_stream = quick_stream
S.new_session("took-chat", bot="lead")
out = {}
try:
    list(S.run_agent("took-chat", "lead", "do it", "", out, RB, {}, 0))
finally:
    S.chat_stream = real_stream
ok("a finished turn records a numeric duration",
   isinstance(out.get("took"), (int, float)) and not isinstance(out.get("took"), bool) and out["took"] >= 0, out)
ok("...rounded to a tenth of a second", out.get("took") == round(out.get("took"), 1), out.get("took"))
ok("a message the user typed carries no duration", "took" not in S._user_message("hi", None, False))

print("--- a restart clears an approval card no turn is waiting on ---")
# The card's waiter is an in-memory Event; after a restart there is none, so the stored `pending`
# draws an Allow/Deny for a command that will never run and leaves the dock asking for an answer.
S.new_session("stale-card", bot="lead")
_st = S.load("stale-card"); _st["pending"] = {"cmd": "rm -rf x", "agent": "lead"}; S.save("stale-card", _st)
S.new_session("live-card", bot="lead")
_lt = S.load("live-card"); _lt["pending"] = {"cmd": "ls", "agent": "lead"}; S.save("live-card", _lt)
S.APPROVAL["live-card"] = {"event": threading.Event(), "allow": False}
_keep = (S.warm_mcp, S.scheduler, S.lucent)
S.warm_mcp = lambda: None; S.scheduler = lambda: None; S.lucent = None
try: S.boot(warm_browser=False)
finally:
    S.warm_mcp, S.scheduler, S.lucent = _keep; S.APPROVAL.pop("live-card", None)
ok("boot clears a card left by a turn that is gone", S.load("stale-card").get("pending") is None,
   S.load("stale-card").get("pending"))
ok("...and leaves a card whose turn is still waiting",
   S.load("live-card").get("pending") == {"cmd": "ls", "agent": "lead"}, S.load("live-card").get("pending"))

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
