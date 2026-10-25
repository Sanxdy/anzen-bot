#!/usr/bin/env python3
"""Offline checks for the workspace bundle: export, inspect, import, and what must never travel.

No router needed.  Usage:  python3 tests/test_workspace_bundle.py
"""
import os, sys, json, base64, io, zipfile, tempfile
tmp = tempfile.mkdtemp()
os.environ["DATA_DIR"] = tmp                        # nothing may fall back to the real data dir
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as S

# Every store this feature touches, pointed inside tmp. The bundle resolves these at use time on
# purpose, so redirecting them here is what keeps a test from writing into the real workspace.
S.MEMDIR = os.path.join(tmp, "memory")
S.SESS_PATH = os.path.join(tmp, "sessions.json")
S.BOTS_PATH = os.path.join(tmp, "bots.json")
S.CH_PATH = os.path.join(tmp, "channels.json")
S.RT_PATH = os.path.join(tmp, "routines.json")
S.SET_PATH = os.path.join(tmp, "settings.json")
S.CFG_PATH = os.path.join(tmp, "config.json")
S.SKILLS_FILE = os.path.join(tmp, "skills.json")
S.SKILLS_DIR = os.path.join(tmp, "skills")
S.AVATAR_DIR = os.path.join(tmp, "avatars")
S.FACES_DIR = os.path.join(tmp, "faces")
S.FACES_BATCH_PATH = os.path.join(S.FACES_DIR, "batch.json")
S.LOGO_DIR = os.path.join(tmp, "logos")
for d in (S.MEMDIR, S.SKILLS_DIR, S.AVATAR_DIR, S.FACES_DIR, S.LOGO_DIR):
    os.makedirs(d, exist_ok=True)
# The settings cache is keyed on the path, so pointing it at tmp is enough for it to reload.
S._SET = {"path": None, "d": None}
S._SESS = {"path": None, "d": None}

PASS = FAIL = 0
def ok(name, cond):
    global PASS, FAIL
    if cond: PASS += 1; print("  PASS " + name)
    else:    FAIL += 1; print("  FAIL " + name)

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40).decode()

def seed():
    """A workspace with one bot that has everything a bundle is supposed to carry."""
    S.save_bots([{"id": "writer", "name": "Writer", "title": "Copy", "role": "writes",
                  "color": "green", "model": S.DEFAULT_MODEL, "approval": "ask",
                  "instructions": "You write.", "skills": ["notes"], "emoji": "✍️",
                  "outfit": "hoodie", "accessory": "glasses", "face": "cat"}])
    S.save_channels([{"id": "studio", "name": "Studio", "members": ["writer"],
                      "mode": "lead", "lead": "writer", "instructions": "keep it short"}])
    with S._RT_LOCK:
        S.save_routines([{"id": "r1", "session": "writer", "bot": "writer", "prompt": "check the news",
                          "every": 3600, "cron": None, "paused": False, "last": 0}])
    S._save_json(S.SKILLS_FILE, [{"id": "notes", "name": "Notes", "desc": "how to take them",
                                  "body": "write them down"}])
    os.makedirs(os.path.join(S.SKILLS_DIR, "notes", "scripts"), exist_ok=True)
    open(os.path.join(S.SKILLS_DIR, "notes", "SKILL.md"), "w").write("# Notes\n")
    open(os.path.join(S.SKILLS_DIR, "notes", "scripts", "run.py"), "w").write("print(1)\n")
    S.mem_append("writer", "the client likes plain words")
    S._save_image(S.AVATAR_DIR, "writer", "data:image/png;base64," + PNG, "avatar")
    S._save_image(S.FACES_DIR, "writer", "data:image/png;base64," + PNG, "face")
    S._save_image(S.LOGO_DIR, "studio", "data:image/png;base64," + PNG, "logo")
    S.save_settings({**S.load_settings(), "company_name": "Studio One", "user_name": "Paduka",
                     "api_keys": {"elevenlabs": "sk-must-not-travel"},
                     "connectors": [{"id": "gmail", "name": "Gmail", "enabled": True,
                                     "token": "tok-must-not-travel"}]})
    S._write_sessions({"writer": {"bot": "writer", "title": "Writer", "model": None, "pending": None,
                                  "approval": None, "messages": [{"role": "user", "text": "hello"}]}})

seed()

# --- export: one zip, the format it claims, and everything in it ---
blob, err = S.export_bundle()
ok("export succeeds", err == "" and blob and blob[:2] == b"PK")
zf = zipfile.ZipFile(io.BytesIO(blob))
names = set(zf.namelist())
for want in ("manifest.json", "bots.json", "channels.json", "routines.json",
             "sessions.json", "settings.json", "skills.json",
             "memory/writer.md", "avatars/writer.png", "faces/writer.png",
             "logos/studio.png", "skills/notes/SKILL.md", "skills/notes/scripts/run.py"):
    ok("bundle holds " + want, want in names)
man = json.loads(zf.read("manifest.json"))
ok("manifest names the format", man["format"] == S.BUNDLE_FORMAT)
ok("manifest counts the bots", man["counts"]["bots"] == 1)

# --- a bundle must never carry a credential or the router ---
raw = b"".join(zf.read(n) for n in names if not n.startswith(("avatars/", "faces/", "logos/")))
ok("no API key travels", b"sk-must-not-travel" not in raw)
ok("no connector token travels", b"tok-must-not-travel" not in raw)
ok("no config.json travels", "config.json" not in names)
ok("no access_token travels", "access_token" not in names)
ok("no relay_secret travels", "relay_secret" not in names)
ok("no browser profiles travel", not any(n.startswith("browser_profiles/") for n in names))
# ...and the settings that describe the workspace do travel
carried = json.loads(zf.read("settings.json"))
ok("company name travels", carried.get("company_name") == "Studio One")
ok("api_keys is not in the bundle at all", "api_keys" not in carried)
ok("connectors are not in the bundle at all", "connectors" not in carried)

# --- inspect says what is inside without writing anything ---
# The roster is not emptied for this check: an empty `bots.json` makes the app fall back to its five
# default bots, which is real behaviour and would hide whether inspect wrote anything. One marker bot
# that the bundle does not contain answers the same question honestly.
S.save_bots([{"id": "marker", "name": "Marker", "title": "T"}])
S.save_channels([{"id": "marker-room", "name": "Marker Room", "members": ["marker"], "mode": "lead", "lead": "marker"}])
S._save_json(S.SKILLS_FILE, [])
info, err = S.bundle_manifest(blob)
ok("inspect reads the bundle", err == "" and info["counts"]["bots"] == 1)
ok("inspect counts the pictures", info["counts"]["avatars"] == 1 and info["counts"]["faces"] == 1)
ok("inspect writes nothing", [b["id"] for b in S.load_bots()] == ["marker"])
ok("inspect touches no rooms", [c["id"] for c in S.load_channels()] == ["marker-room"])

# --- a zip that is not ours is refused, before anything is written ---
notours = io.BytesIO()
with zipfile.ZipFile(notours, "w") as z: z.writestr("hello.txt", "hi")
res, err = S.import_bundle(notours.getvalue())
ok("a zip with no manifest is refused", res is None and "manifest" in err)
wrongver = io.BytesIO()
with zipfile.ZipFile(wrongver, "w") as z:
    z.writestr("manifest.json", json.dumps({"format": S.BUNDLE_FORMAT, "version": 99}))
res, err = S.import_bundle(wrongver.getvalue())
ok("a future version is refused, and named", res is None and "99" in err)
res, err = S.import_bundle(b"not a zip")
ok("a non-zip is refused", res is None and "not a zip" in err)

# --- import into a workspace that does not have this bot yet ---
# The roster is never truly empty: an empty `bots.json` falls back to the five default bots, so this
# starts from those and checks that the bundle's bot joins them intact rather than expecting it alone.
res, err = S.import_bundle(blob, "merge")
ok("import succeeds", err == "" and res["mode"] == "merge")
bots = {b["id"]: b for b in S.load_bots()}
ok("the bot arrived", "writer" in bots)
ok("the marker bot is still there", "marker" in bots)
b = bots["writer"]
ok("its colour arrived", b["color"] == "green")
ok("its outfit arrived", b["outfit"] == "hoodie" and b["accessory"] == "glasses")
ok("its face arrived", b["face"] == "cat")
ok("its instructions arrived", b["instructions"] == "You write.")
ok("its skills arrived", b["skills"] == ["notes"])
ok("its emoji arrived", b["emoji"] == "✍️")
ok("the room arrived", "studio" in {c["id"] for c in S.load_channels()})
ok("the routine arrived", [r["id"] for r in S.load_routines()] == ["r1"])
ok("the skill record arrived", [s["id"] for s in S.load_installed_skills()] == ["notes"])
ok("the skill's own files arrived",
   os.path.isfile(os.path.join(S.SKILLS_DIR, "notes", "scripts", "run.py")))
ok("the memory arrived", "plain words" in open(S.mem_path("writer")).read())
ok("the avatar arrived", os.path.isfile(os.path.join(S.AVATAR_DIR, "writer.png")))
ok("the face arrived", os.path.isfile(os.path.join(S.FACES_DIR, "writer.png")))
ok("the logo arrived", os.path.isfile(os.path.join(S.LOGO_DIR, "studio.png")))
ok("the chat arrived", "hello" in json.dumps(S._all_sessions()))
ok("the avatar version was re-stamped", {b["id"]: b for b in S.load_bots()}["writer"]["avatar"] > 0)
ok("the company name arrived", S.load_settings().get("company_name") == "Studio One")

# --- import must not wipe the keys the machine already has ---
S.save_settings({**S.load_settings(), "api_keys": {"elevenlabs": "local-key"}})
S.import_bundle(blob, "merge")
ok("a local API key survives an import", S.load_settings()["api_keys"]["elevenlabs"] == "local-key")

# --- merge folds, replace swaps ---
S.save_bots(S.load_bots() + [{"id": "local", "name": "Local", "title": "T"}])
res, err = S.import_bundle(blob, "merge")
ok("merge keeps a bot the bundle does not have",
   {"local", "writer"} <= {b["id"] for b in S.load_bots()})
res, err = S.import_bundle(blob, "replace")
ids = {b["id"] for b in S.load_bots()}
ok("replace drops the one it does not carry", "local" not in ids and "writer" in ids)

# --- path traversal in a member name is refused, not followed ---
evil = io.BytesIO()
with zipfile.ZipFile(evil, "w") as z:
    z.writestr("manifest.json", json.dumps({"format": S.BUNDLE_FORMAT, "version": S.BUNDLE_VERSION}))
    z.writestr("bots.json", json.dumps([{"id": "x", "name": "X", "title": "T"}]))
    z.writestr("memory/../../escaped.md", "pwned")
    z.writestr("avatars/../../escaped.png", PNG)
res, err = S.import_bundle(evil.getvalue())
ok("a traversing member does not escape", not os.path.exists(os.path.join(tmp, "..", "escaped.md")))
ok("it is reported as skipped", res and res["skipped_count"] >= 1)
ok("the rest of that bundle still imports", res and "x" in {b["id"] for b in S.load_bots()})

# --- a bundle over the ceiling is refused with the number, not silently ---
old = S.BUNDLE_MAX_BYTES
S.BUNDLE_MAX_BYTES = 10
blob2, err = S.export_bundle()
ok("an oversized export says so", blob2 is None and "MB" in err)
S.BUNDLE_MAX_BYTES = old

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
