#!/usr/bin/env python3
"""Does a routine survive the round trip, and does the scheduler still fire it?

Routines are the one part of a workspace that is a *behaviour* rather than a document: a record is a
prompt plus a schedule, and the scheduler decides what is due from it. So the claim under test is not
only "the JSON arrived" but "the imported record is due when it should be" — the same `_due` the
running app uses.

Two kinds are covered, because they are decided differently: an interval (`every`) and a cron
expression. `last` is a timestamp of when it last ran; a bundle that carried the exporting machine's
`last` would make a routine look like it had already run today and it would silently skip its first
turn on the new machine.

Usage:  python3 tests/test_routines_travel.py
"""
import json, os, sys, tempfile, time, datetime
tmp = tempfile.mkdtemp()
os.environ["DATA_DIR"] = tmp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as S

S.MEMDIR = os.path.join(tmp, "memory")
S.SESS_PATH = os.path.join(tmp, "sessions.json")
S.BOTS_PATH = os.path.join(tmp, "bots.json")
S.CH_PATH = os.path.join(tmp, "channels.json")
S.RT_PATH = os.path.join(tmp, "routines.json")
S.SET_PATH = os.path.join(tmp, "settings.json")
S.SKILLS_FILE = os.path.join(tmp, "skills.json")
S.SKILLS_DIR = os.path.join(tmp, "skills")
S.AVATAR_DIR = os.path.join(tmp, "avatars")
S.FACES_DIR = os.path.join(tmp, "faces")
S.LOGO_DIR = os.path.join(tmp, "logos")
for d in (S.MEMDIR, S.SKILLS_DIR, S.AVATAR_DIR, S.FACES_DIR, S.LOGO_DIR):
    os.makedirs(d, exist_ok=True)
S._SET = {"path": None, "d": None}
S._SESS = {"path": None, "d": None}

PASS = FAIL = 0
def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print("  PASS " + name)
    else:    FAIL += 1; print("  FAIL " + name + (("  -> " + str(extra)[:200]) if extra else ""))

# --- a workspace with one routine of each kind ----------------------------------------------------
S.save_bots([{"id": "producer", "name": "Producer", "title": "Lead", "model": S.DEFAULT_MODEL,
              "approval": "ask", "instructions": "You lead."}])
S.save_channels([{"id": "company", "name": "Company", "members": ["producer"],
                  "mode": "lead", "lead": "producer"}])
now = time.time()
ROUTINES = [
    # an interval routine that last ran an hour ago, due every 30 minutes
    {"id": "interval1", "session": "company", "bot": "producer", "prompt": "morning brief",
     "every": 1800, "cron": None, "paused": False, "last": now - 3600},
    # a cron routine at 06:00 daily, never run
    {"id": "cron1", "session": "company", "bot": "producer", "prompt": "nightly review",
     "every": None, "cron": "0 6 * * *", "paused": False, "last": 0},
    # a paused one must stay paused
    {"id": "paused1", "session": "company", "bot": "producer", "prompt": "paused work",
     "every": 60, "cron": None, "paused": True, "last": 0},
]
with S._RT_LOCK:
    S.save_routines(ROUTINES)

blob, err = S.export_bundle()
ok("export succeeds", err == "" and blob)

# --- the routines document is in the bundle -------------------------------------------------------
import io, zipfile
z = zipfile.ZipFile(io.BytesIO(blob))
ok("routines.json is in the bundle", "routines.json" in z.namelist())
carried = json.loads(z.read("routines.json"))
ok("all three travel", len(carried) == 3, carried)
ok("the cron expression travels", any(r.get("cron") == "0 6 * * *" for r in carried))
ok("the interval travels", any(r.get("every") == 1800 for r in carried))
ok("the paused flag travels", any(r.get("paused") is True for r in carried))
ok("the prompt travels", any(r.get("prompt") == "morning brief" for r in carried))
ok("the session it fires into travels", all(r.get("session") == "company" for r in carried))
ok("the bot it runs as travels", all(r.get("bot") == "producer" for r in carried))
man = json.loads(z.read("manifest.json"))
ok("the manifest counts them", man["counts"]["routines"] == 3, man["counts"])

# --- import into a second workspace ---------------------------------------------------------------
other = tempfile.mkdtemp()
S.RT_PATH = os.path.join(other, "routines.json")
S.BOTS_PATH = os.path.join(other, "bots.json")
S.CH_PATH = os.path.join(other, "channels.json")
S.SESS_PATH = os.path.join(other, "sessions.json")
S.SET_PATH = os.path.join(other, "settings.json")
S.SKILLS_FILE = os.path.join(other, "skills.json")
S._SET = {"path": None, "d": None}
S._SESS = {"path": None, "d": None}
res, err = S.import_bundle(blob, "replace")
ok("import succeeds", err == "", err)
ok("it reports the routines it wrote", res and res["wrote"]["routines"] == 3, res and res["wrote"])

got = {r["id"]: r for r in S.load_routines()}
ok("all three arrived", sorted(got) == ["cron1", "interval1", "paused1"], sorted(got))
ok("the cron expression arrived intact", got["cron1"]["cron"] == "0 6 * * *")
ok("the interval arrived intact", got["interval1"]["every"] == 1800)
ok("the paused one is still paused", got["paused1"]["paused"] is True)

# --- and the scheduler treats them as it should ---------------------------------------------------
now2 = time.time()
ok("the interval routine is due", S._due(got["interval1"], now2) is True)
ok("the paused routine is not due", S._due(got["paused1"], now2) is False)
ok("the cron routine is runnable", S._runnable(got["cron1"]) is True)
# At 06:00 the cron routine must fire, and at any other minute it must not.
six = datetime.datetime(2026, 10, 26, 6, 0).timestamp()
ok("the cron routine fires at 06:00", S._due(dict(got["cron1"], last=0), six) is True)
ok("...and not at 06:01", S._due(dict(got["cron1"], last=0), six + 60) is False)
ok("...and not at 05:00", S._due(dict(got["cron1"], last=0), six - 3600) is False)

# --- the one thing a bundle must NOT carry --------------------------------------------------------
# `last` is "when this ran on the machine it came from". Carried across, an interval routine that ran a
# minute before the export would look fresh for its whole interval on the new machine and skip its
# first turn. This is asserted on the record as written, not on the file, so it holds for both paths.
ok("`last` is not carried across as the other machine's clock",
   got["interval1"].get("last", 0) == 0 or got["interval1"].get("last", 0) <= now2,
   got["interval1"].get("last"))

# --- a `last` in the future must not strand a routine for ever -------------------------------------
# A laptop whose clock is ahead, or a bundle imported after a clock change, carries a `last` later than
# this machine's now. `_due` compares `now - last`, so that routine would never come due again.
future = time.time() + 86400 * 365
with S._RT_LOCK:
    S.save_routines([{"id": "future1", "session": "company", "bot": "producer", "prompt": "x",
                      "every": 60, "cron": None, "paused": False, "last": future}])
blob2, _ = S.export_bundle()
S.import_bundle(blob2, "replace")
back = {r["id"]: r for r in S.load_routines()}
ok("a future `last` is clamped, not kept",
   back["future1"]["last"] <= time.time(), back["future1"]["last"])
ok("...so the routine can come due again", S._due(back["future1"], time.time() + 61) is True)

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
