#!/usr/bin/env python3
"""Checks for "shuffle a room" — one click gives every bot in a room a preset of its own.

The point of the feature is that nobody has to click through the roster, so the things that matter
are: everyone in the room really changes, nobody shares a face while there are still faces to go
round, a hand-picked face survives unless asked otherwise, and the shuffle never invents a bot.

The whole check runs against a temporary DATA_DIR: the real roster in Application Support is never
touched.

Usage:  python3 tests/test_face_shuffle.py
"""
import os, sys, tempfile

tmp = tempfile.mkdtemp(prefix="anzen-shuffle-")
os.environ["DATA_DIR"] = tmp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as S

assert S.DATA.startswith(tmp) and S.BOTS_PATH.startswith(tmp) and S.CH_PATH.startswith(tmp), \
    "test paths must point into tmp"

PASS = []; FAIL = []
def check(name, ok, extra=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + (f"  {extra}" if extra and not ok else ""))

def room(n, custom=None):
    """A fresh roster of n bots, all members of one room. `custom` is a bot id given a drawn face."""
    bots = [{"id": f"b{i}", "name": f"Bot {i}", "genface": "", "genface_closed": "", "preset": ""}
            for i in range(n)]
    if custom:
        next(b for b in bots if b["id"] == custom)["genface"] = "f-1.png"
    S.save_bots(bots)
    S.save_channels([{"id": "team", "name": "Team", "members": [b["id"] for b in bots]}])
    return "team"

def presets_of(ids):
    bots = {b["id"]: b for b in S.load_bots()}
    return [bots[i].get("preset") or "" for i in ids]

# ---- the roster itself ------------------------------------------------------------------------
counts = {}
for p in S.PRESETS:
    counts[p["species"]] = counts.get(p["species"], 0) + 1
check("35 presets, 15 women / 15 men / 5 cats",
      len(S.PRESETS) == 35 and counts == {"woman": 15, "man": 15, "cat": 5}, str(counts))
check("every preset id is unique and has a label",
      len(S.PRESET_IDS) == len(S.PRESETS) and all(p.get("label") for p in S.PRESETS))

# ---- a room of ten ----------------------------------------------------------------------------
cid = room(10)
r = S.shuffle_room_faces(cid)
ids = [b["id"] for b in S.load_bots()]
got = presets_of(ids)
check("every member got a preset", all(g in S.PRESET_IDS for g in got), str(got))
check("no two members share a preset", len(set(got)) == len(got), str(got))
check("the result counts what it changed", r == {"ok": True, "changed": 10, "kept": 0, "bots": ids}, str(r))

# ---- a hand-picked face survives, until you say otherwise -------------------------------------
cid = room(6, custom="b2")
r = S.shuffle_room_faces(cid, keep=True)
bots = {b["id"]: b for b in S.load_bots()}
check("keep leaves a drawn face alone", bots["b2"]["genface"] == "f-1.png" and r["kept"] == 1, str(r))
check("keep still fills the rest", r["changed"] == 5, str(r))
check("the kept bot's face is not in the deck", bots["b2"]["preset"] == "", bots["b2"].get("preset"))

r = S.shuffle_room_faces(cid, keep=False)
bots = {b["id"]: b for b in S.load_bots()}
check("unticking keep replaces the drawn face", bots["b2"]["preset"] in S.PRESET_IDS
      and bots["b2"]["genface"] == "" and r["changed"] == 6, str(r))

# ---- a picture is a hand-picked face too ------------------------------------------------------
S.save_bots([{"id": "pic", "name": "Pic", "genface": "", "genface_closed": "", "preset": "",
              "avatar": 3, "avatar_closed": 0}])
S.save_channels([{"id": "team", "name": "Team", "members": ["pic"]}])
r = S.shuffle_room_faces("team", keep=True)
check("keep leaves a photo alone", S.load_bots()[0].get("avatar") == 3 and r["kept"] == 1, str(r))

# ---- more members than presets: a second cycle, never a missing face --------------------------
n = len(S.PRESETS) + 5
cid = room(n)
r = S.shuffle_room_faces(cid)
got = presets_of([f"b{i}" for i in range(n)])
check("40 members still all get a preset", all(g in S.PRESET_IDS for g in got))
check("all 35 presets are used before any repeats", len(set(got)) == len(S.PRESETS), str(len(set(got))))
check("no preset is used more than twice", max(got.count(g) for g in set(got)) <= 2)

# ---- refusals ----------------------------------------------------------------------------------
check("unknown room is refused", S.shuffle_room_faces("nope") is None)
S.save_channels([{"id": "empty", "name": "Empty", "members": []}])
check("an empty room is not an error", S.shuffle_room_faces("empty") ==
      {"ok": True, "changed": 0, "kept": 0, "bots": []})
S.save_channels([])
check("no channels at all is refused", S.shuffle_room_faces("team") is None)

# ---- a page asks for every face at once ---------------------------------------------------------
# A roster is a wall of images and a browser opens a connection per image without waiting. The
# stock listen backlog of 5 resets all but five of them, and the page then paints broken pictures,
# so the burst is fired for real over a socket rather than reasoned about.
import threading, urllib.request
from concurrent.futures import ThreadPoolExecutor

srv = S.Srv(("127.0.0.1", 0), S.H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

def fetch(pid):
    try:
        r = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/preset/{pid}/base.webp", timeout=20)
        return r.status, len(r.read())
    except Exception as e:
        return type(e).__name__, str(e)

for rnd in range(3):
    with ThreadPoolExecutor(len(S.PRESET_IDS)) as ex:
        res = list(ex.map(fetch, S.PRESET_IDS))
    bad = [r for r in res if r[0] != 200 or r[1] < 1000]
    check(f"all {len(S.PRESET_IDS)} faces serve at once (round {rnd + 1})", not bad, str(bad[:3]))
srv.shutdown()

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("failed: " + ", ".join(FAIL)); sys.exit(1)
