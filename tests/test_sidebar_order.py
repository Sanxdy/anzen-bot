#!/usr/bin/env python3
"""Sidebar arrangement: the stored order of the rooms, the loose bots and one room's members, and
the pin that floats a room to the top.

The claim being checked is that the order the user drags into is the *record's*, not one browser's:
the sidebar's order is the array in bots.json / channels.json, so it is written there and the phone
reads what the window arranged. And that a rearrangement can never lose a row — a list from a client
that has not seen a bot added since (the phone, a stale tab) reorders what it knows and leaves the
rest in place, at the end.

No router, no browser.  Usage:  .venv/bin/python tests/test_sidebar_order.py
"""
import os, sys, json, socket, tempfile, threading, http.client, http.server
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as S

tmp = tempfile.mkdtemp(prefix="anzen-order-")
S.BOTS_PATH = os.path.join(tmp, "bots.json")
S.CH_PATH = os.path.join(tmp, "channels.json")
S.SESS_PATH = os.path.join(tmp, "sessions.json")
S.SET_PATH = os.path.join(tmp, "settings.json")
assert S.BOTS_PATH.startswith(tmp) and S.CH_PATH.startswith(tmp), "test paths must point into tmp"

PASS = []; FAIL = []
def check(name, ok, extra=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + (f"  {extra}" if extra and not ok else ""))

# --- the helper: named ids in the order given, anything unnamed after them, untouched -----------
def ids_of(seq): return [x["id"] for x in seq]
def named(*ids): return [{"id": i} for i in ids]

check("reorder puts the named ids in the order given",
      ids_of(S.reorder(named("a", "b", "c"), ["c", "a", "b"])) == ["c", "a", "b"])
check("reorder keeps an unnamed row rather than dropping it",
      ids_of(S.reorder(named("a", "b", "c"), ["c", "a"])) == ["c", "a", "b"])
check("...and puts it after the named ones, in its own order",
      ids_of(S.reorder(named("a", "b", "c", "d"), ["d", "b"])) == ["d", "b", "a", "c"])
check("an id that names nothing is ignored rather than invented",
      ids_of(S.reorder(named("a", "b"), ["b", "ghost", "a"])) == ["b", "a"])
check("an empty list is a no-op, not an empty sidebar",
      ids_of(S.reorder(named("a", "b"), [])) == ["a", "b"])
check("members are plain strings, not objects",
      S.reorder(["producer", "qa", "ops"], ["ops", "producer"], key=lambda m: m) == ["ops", "producer", "qa"])

# --- over a real socket: the route writes the order to the file the sidebar reads ----------------
S.save_bots([{"id": i, "name": i.title(), "model": "m", "instructions": "x", "approval": "ask",
              "memory": False, "skills": []} for i in ("alpha", "beta", "gamma")])
S.save_channels([{"id": "room-a", "name": "A", "members": ["alpha", "beta"], "lead": "alpha",
                  "mode": "lead", "instructions": "", "folder": ""},
                 {"id": "room-b", "name": "B", "members": ["gamma"], "lead": "gamma",
                  "mode": "lead", "instructions": "", "folder": ""}])
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

st, j = post("/api/nav/order", {"kind": "bots", "ids": ["gamma", "alpha", "beta"]})
check("reordering the bots is accepted", j.get("ok") is True, (st, j))
check("...and the reply carries the new order",
      [b["id"] for b in j.get("bots", [])] == ["gamma", "alpha", "beta"], j.get("bots"))
check("...and the file on disk is what the sidebar will read",
      [b["id"] for b in S.load_bots()] == ["gamma", "alpha", "beta"], ids_of(S.load_bots()))

st, j = post("/api/nav/order", {"kind": "bots", "ids": ["beta", "alpha"]})
check("a list from a client that has not seen every bot loses none of them",
      [b["id"] for b in S.load_bots()] == ["beta", "alpha", "gamma"], ids_of(S.load_bots()))

st, j = post("/api/nav/order", {"kind": "channels", "ids": ["room-b", "room-a"]})
check("reordering the rooms is accepted", j.get("ok") is True, (st, j))
check("...and lands in channels.json",
      [c["id"] for c in S.load_channels()] == ["room-b", "room-a"], ids_of(S.load_channels()))

st, j = post("/api/nav/order", {"kind": "members", "id": "room-a", "ids": ["beta", "alpha"]})
check("reordering one room's members is accepted", j.get("ok") is True, (st, j))
check("...and only that room's member list moved",
      S.channel_by_id(S.load_channels(), "room-a")["members"] == ["beta", "alpha"],
      S.channel_by_id(S.load_channels(), "room-a")["members"])
check("...and the other room is untouched",
      S.channel_by_id(S.load_channels(), "room-b")["members"] == ["gamma"])
check("...and the bot list is untouched",
      [b["id"] for b in S.load_bots()] == ["beta", "alpha", "gamma"], ids_of(S.load_bots()))

st, j = post("/api/nav/order", {"kind": "members", "id": "ghost", "ids": ["alpha"]})
check("members of a room that does not exist are refused", j.get("ok") is False, (st, j))
st, j = post("/api/nav/order", {"ids": ["alpha"]})
check("a reorder that names no list is refused", j.get("ok") is False, (st, j))
st, j = post("/api/nav/order", {"kind": "rooms", "ids": ["alpha"]})
check("a misspelled kind is refused rather than silently taken as bots",
      j.get("ok") is False, (st, j))

# --- pin: a room floats in the sidebar, and the hand-made order survives the unpin ----------------
st, j = post("/api/channel", {"channel": {"id": "room-a", "pinned": True}})
check("a room pins through the ordinary channel write", j.get("ok") is True, (st, j))
check("...and config hands the flag back to the sidebar",
      [c["pinned"] for c in j["channels"] if c["id"] == "room-a"] == [True],
      [c.get("pinned") for c in j["channels"]])
check("...and pinning is a flag, not a move: the stored order is the one you dragged",
      [c["id"] for c in S.load_channels()] == ["room-b", "room-a"], ids_of(S.load_channels()))
check("...and the room's own settings survive the pin",
      S.channel_by_id(S.load_channels(), "room-a")["members"] == ["beta", "alpha"],
      S.channel_by_id(S.load_channels(), "room-a"))
st, j = post("/api/channel", {"channel": {"id": "room-a", "pinned": False}})
check("unpinning restores the room to the order it was dragged into",
      S.channel_by_id(S.load_channels(), "room-a")["pinned"] is False and
      [c["id"] for c in S.load_channels()] == ["room-b", "room-a"], ids_of(S.load_channels()))

# --- the client's own half, read from the source it ships ---------------------------------------
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.js")).read()
check("the sidebar floats a pinned room to the top, as it already did for a pinned bot",
      "for (const c of [...S.channels].sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0)))" in src)
check("a room row carries the pin glyph", 'c.pinned ? `<span class="pin">' in src)
check("the rooms menu offers pin", '["pin", (c && c.pinned ? "Unpin" : "Pin"), "pin"]' in src)
check("the chats section folds, and remembers it", 'localStorage.setItem("nav.shut"' in src)
check("a row is dropped back into its own list only", "box.contains(e.target)" in src)
check("the order is saved on dragend, so a row let go outside a list is still saved",
      'navwrap.addEventListener("dragend", dragEnd)' in src)

srv.shutdown()
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
