#!/usr/bin/env python3
"""Every field of a bot and a room record, removed one at a time, and the app still starts.

The bug this exists for: `boot()` mints a chat for every record and names it `c["name"]`, so one
record in channels.json without a `name` raised KeyError inside boot and the backend would not
start at all. The same was true of a bot with no `name`, and every *other* field a record is read
for was quietly left missing — a `bot["model"]` read inside a turn is a TypeError, not a crash at
boot, so the probe that found this had to look past boot.

So the claim is the invariant, not the one field: **no record the loader hands back is missing any
field the app reads.** If that holds, no unguarded read of one can raise, wherever it is. Checked
for both the loader (a hand-edited or older file) and the create endpoints (the two definitions
drifting apart is how the nameless record got written in the first place).

No router, no browser.  Usage:  .venv/bin/python tests/test_record_fields.py
"""
import os, sys, json, socket, tempfile, threading, http.client, http.server
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as S

tmp = tempfile.mkdtemp(prefix="anzen-fields-")
S.BOTS_PATH = os.path.join(tmp, "bots.json")
S.CH_PATH = os.path.join(tmp, "channels.json")
S.SESS_PATH = os.path.join(tmp, "sessions.json")
S.SET_PATH = os.path.join(tmp, "settings.json")
assert S.BOTS_PATH.startswith(tmp) and S.CH_PATH.startswith(tmp), "test paths must point into tmp"

# Every key either record is read for, in one place. A field added to a record belongs here too —
# that is the whole point: the list is the contract the loader is checked against.
BOT_FIELDS = ["id", "name", "title", "role", "color", "model", "approval", "memory", "voice",
              "instructions", "skills", "tools_allow", "hidden", "pinned", "emoji", "face",
              "outfit", "accessory", "avatar"]
CH_FIELDS = ["id", "name", "members", "mode", "lead", "instructions", "folder", "pinned"]

A_BOT = {"id": "producer", "name": "Producer", "title": "Chief of Staff", "role": "runs the room",
         "color": "purple", "model": "m", "approval": "ask", "memory": True, "voice": "",
         "instructions": "x", "skills": [], "tools_allow": None, "hidden": False, "pinned": False,
         "emoji": "🎬", "face": "", "outfit": "", "accessory": "", "avatar": 0}
A_CH = {"id": "room", "name": "Room", "members": ["producer"], "mode": "lead", "lead": "producer",
        "instructions": "", "folder": "", "pinned": False, "color": ""}

PASS = []; FAIL = []
def check(name, ok, extra=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + (f"  {extra}" if extra and not ok else ""))

def boot_records():
    """The two lines boot() runs over the records — the crash site, called as boot calls them."""
    for b in S.load_bots(): S.new_session(b["id"], bot=b["id"], title=b["name"])
    for c in S.load_channels(): S.new_session(c["id"], bot=None, title=c["name"])

# --- a bot record missing each field -------------------------------------------------------------
print("--- bots: one field removed at a time ---")
for f in BOT_FIELDS:
    rec = dict(A_BOT); rec.pop(f)
    S.save_bots([rec]); S.save_channels([])
    try:
        boot_records()
        got = S.load_bots()[0]
        missing = [k for k in BOT_FIELDS if k not in got]
        # The public projection is what every client draws from; a None in it is a missing field
        # one layer up, where the loader can no longer repair it.
        pub = S.H._bots_public(None, S.load_bots())[0]   # a method only for its name; it reads no self
        blank = [k for k in ("id", "name", "title", "model", "approval") if not pub.get(k)]
        check("a bot with no %s still starts and is whole" % f,
              not missing and not blank, "still-missing=%s blank-public=%s" % (missing, blank))
    except Exception as e:
        check("a bot with no %s still starts and is whole" % f, False,
              "%s: %s" % (type(e).__name__, e))

# --- a room record missing each field ------------------------------------------------------------
print("--- rooms: one field removed at a time ---")
for f in CH_FIELDS:
    rec = dict(A_CH); rec.pop(f)
    S.save_bots([dict(A_BOT)]); S.save_channels([rec])
    try:
        boot_records()
        got = S.load_channels()[0]
        missing = [k for k in CH_FIELDS if k not in got]
        pub = S.channels_public(S.load_channels())[0]
        blank = [k for k in ("id", "name") if not pub.get(k)]
        check("a room with no %s still starts and is whole" % f,
              not missing and not blank, "still-missing=%s blank-public=%s" % (missing, blank))
    except Exception as e:
        check("a room with no %s still starts and is whole" % f, False,
              "%s: %s" % (type(e).__name__, e))

# --- the same field, present but null ------------------------------------------------------------------
# `setdefault` fills an *absent* key; a client serialising an unset value writes an explicit null, and
# that is not absent. A room with `"members": null` used to pass the loader and then 500 the next bot
# delete; a bot with `"instructions": null` failed on every turn.
print("--- bots: one field written as null at a time ---")
for f in BOT_FIELDS:
    rec = dict(A_BOT); rec[f] = None
    S.save_bots([rec]); S.save_channels([])
    try:
        boot_records()
        got = S.load_bots()[0]
        unusable = [k for k in BOT_FIELDS if got.get(k) is None and k != "tools_allow"]
        check("a bot with a null %s still starts and is usable" % f, not unusable, "null=%s" % unusable)
    except Exception as e:
        check("a bot with a null %s still starts and is usable" % f, False, "%s: %s" % (type(e).__name__, e))

print("--- rooms: one field written as null at a time ---")
for f in CH_FIELDS:
    rec = dict(A_CH); rec[f] = None
    S.save_bots([dict(A_BOT)]); S.save_channels([rec])
    try:
        boot_records()
        got = S.load_channels()[0]
        unusable = [k for k in CH_FIELDS if got.get(k) is None]
        check("a room with a null %s still starts and is usable" % f, not unusable, "null=%s" % unusable)
    except Exception as e:
        check("a room with a null %s still starts and is usable" % f, False, "%s: %s" % (type(e).__name__, e))

# ...and the field a null actually broke a route with: `bot/delete` iterates the room's members.
S.save_bots([dict(A_BOT), dict(A_BOT, id="qa", name="Qa")])
S.save_channels([dict(A_CH, members=None)])
boot_records()
try:
    chs = S.load_channels(); chs[0]["members"] = [m for m in chs[0]["members"] if m != "qa"]
    S.save_channels(chs)
    check("the bot-delete loop over a room that arrived with null members does not raise",
          S.load_channels()[0]["members"] == [], S.load_channels()[0]["members"])
except Exception as e:
    check("the bot-delete loop over a room that arrived with null members does not raise", False,
          "%s: %s" % (type(e).__name__, e))

# --- a deliberate False, 0 or "" is a value, not a gap ------------------------------------------------
S.save_bots([dict(A_BOT, memory=False, pinned=False, hidden=False, avatar=0, voice="", face="")])
S.save_channels([])
got = S.load_bots()[0]
check("a field the record deliberately set to False, 0 or \"\" is left exactly as written",
      got["memory"] is False and got["pinned"] is False and got["hidden"] is False and
      got["avatar"] == 0 and got["voice"] == "" and got["face"] == "", got)

# --- the literal bug: neither id nor name ---------------------------------------------------------
print("--- the shape that broke it ---")
S.save_bots([dict(A_BOT)]); S.save_channels([{"members": ["producer"], "mode": "lead"}])
try:
    boot_records()
    got = S.load_channels()[0]
    check("a room with neither an id nor a name still starts", True)
    check("...and is handed a name derived from an id it was given",
          bool(got.get("id")) and bool(got.get("name")), got)
except Exception as e:
    check("a room with neither an id nor a name still starts", False, "%s: %s" % (type(e).__name__, e))

S.save_bots([{"title": "Nobody"}])
try:
    boot_records()
    got = S.load_bots()[0]
    check("a bot with neither an id nor a name still starts and keeps the fields it had",
          bool(got.get("id")) and bool(got.get("name")) and got.get("title") == "Nobody", got)
except Exception as e:
    check("a bot with neither an id nor a name still starts and keeps the fields it had", False,
          "%s: %s" % (type(e).__name__, e))

# --- two records that would collide once named ----------------------------------------------------
S.save_bots([dict(A_BOT)])
S.save_channels([{"name": "Standup", "members": ["producer"]}, {"name": "Standup", "members": ["producer"]}])
try:
    boot_records()
    ids = [c["id"] for c in S.load_channels()]
    check("two rooms with the same name get two chats, not one", len(set(ids)) == 2, ids)
except Exception as e:
    check("two rooms with the same name get two chats, not one", False, "%s: %s" % (type(e).__name__, e))

# --- an id the record supplied is never the one that is renamed -----------------------------------
# It names a session and a logo file on disk, so renaming it orphans both. A record with no id of its
# own is the one that yields.
S.save_bots([dict(A_BOT)])
S.save_channels([{"name": "Standup", "members": ["producer"]},
                 {"id": "standup", "name": "Weekly", "members": ["producer"]}])
try:
    boot_records()
    ids = [c["id"] for c in S.load_channels()]
    check("a room that named its own id keeps it, and the one without an id yields",
          ids == ["standup-2", "standup"], ids)
except Exception as e:
    check("a room that named its own id keeps it, and the one without an id yields", False,
          "%s: %s" % (type(e).__name__, e))

# --- the third writer: the team importer ------------------------------------------------------------
print("--- the team importer writes whole records ---")
S.save_bots([]); S.save_channels([])          # an empty file is re-seeded with the default roster
made, rooms = S.build_team(S.TEAM_TEMPLATE)
check("the shipped template imports", bool(made), made)
check("...and every bot it made is whole in the file",
      not [k for b in S.load_bots() for k in BOT_FIELDS if k not in b],
      [k for b in S.load_bots() for k in BOT_FIELDS if k not in b])
check("...and every room it made is whole in the file",
      bool(rooms) and not [k for c in S.load_channels() for k in CH_FIELDS if k not in c],
      [k for c in S.load_channels() for k in CH_FIELDS if k not in c])
boot_records()   # what the importer's own two new_session loops do, over what it wrote

# --- the create endpoints: what they write is already whole ---------------------------------------
print("--- the create endpoints write whole records ---")
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

S.save_bots([dict(A_BOT)]); S.save_channels([])
st, j = post("/api/bot", {"bot": {"name": "Researcher"}})
check("creating a bot from a name alone is accepted", j.get("ok") is True, (st, j))
on_disk = S._load_json(S.BOTS_PATH, [])
made = S.bot_by_id(on_disk, "researcher")
check("...and the file already holds every field, so no read can miss one",
      made is not None and not [k for k in BOT_FIELDS if k not in made],
      [k for k in BOT_FIELDS if not made or k not in made])
check("...and it landed in the same file the loader reads",
      S.bot_by_id(S.load_bots(), "researcher") is not None)

st, j = post("/api/channel", {"channel": {"name": "Design Standup"}})
check("creating a room from a name alone is accepted", j.get("ok") is True, (st, j))
made = S.channel_by_id(S._load_json(S.CH_PATH, []), "design-standup")
check("...and the file already holds every field",
      made is not None and not [k for k in CH_FIELDS if k not in made],
      [k for k in CH_FIELDS if not made or k not in made])

# --- and the loader's repair reaches the router's own model list ----------------------------------
print("--- a model the router does not serve ---")
S.save_bots([dict(A_BOT, model="a-model-that-is-gone")])
S.CFG["models"] = ["the-only-model"]
try:
    got = S.load_bots()[0]
    check("a model the router no longer serves is replaced, not left to 404 every turn",
          got["model"] == S.DEFAULT_MODEL, got.get("model"))
except Exception as e:
    check("a model the router no longer serves is replaced, not left to 404 every turn", False,
          "%s: %s" % (type(e).__name__, e))

srv.shutdown()
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
