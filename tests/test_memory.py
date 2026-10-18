#!/usr/bin/env python3
"""Offline checks for self-learning, skills and team import.

No router needed — server.chat is stubbed.  Usage:  python3 tests/test_memory.py
"""
import os, sys, tempfile, base64
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as S

tmp = tempfile.mkdtemp()
S.MEMDIR = tmp
S.SESS_PATH = os.path.join(tmp, "sessions.json")   # keep run_agent's sessions out of the real data dir
S.BOTS_PATH = os.path.join(tmp, "bots.json")       # keep build_team's bots out of the real data dir
S.CH_PATH = os.path.join(tmp, "channels.json")
S.AVATAR_DIR = os.path.join(tmp, "avatars")        # an uploaded avatar must not land in the real one
S.LOGO_DIR = os.path.join(tmp, "logos")
# run_agent now works in a per-bot folder and logs the turn, so both need a home inside tmp
S.SANDBOX = os.path.join(tmp, "sandbox"); os.makedirs(S.SANDBOX)
S.LOGDIR = os.path.join(tmp, "logs"); os.makedirs(S.LOGDIR)
assert S.LOGDIR.startswith(tmp) and S.SANDBOX.startswith(tmp), "a bot's field and log must stay in tmp"
PASS = FAIL = 0
def ok(name, cond):
    global PASS, FAIL
    if cond: PASS += 1; print("  PASS " + name)
    else:    FAIL += 1; print("  FAIL " + name)

# --- mem_append creates a header on a fresh file and stamps the note ---
S.mem_append("t1", "python3 is the only interpreter here")
txt = open(S.mem_path("t1"), encoding="utf-8").read()
ok("fresh memory file gets a header", txt.startswith("# Notes"))
ok("note is stamped and kept", "python3 is the only interpreter here" in txt and "[20" in txt)

# --- compaction keeps the header and the freshest notes ---
for i in range(S.MEM_MAX_LINES + 50): S.mem_append("t2", f"note {i}")
lines = open(S.mem_path("t2"), encoding="utf-8").read().splitlines()
ok("memory file stays bounded", len(lines) <= S.MEM_MAX_LINES)
ok("compaction keeps the header", lines[0] == "# Notes")
ok("compaction keeps the newest note", f"note {S.MEM_MAX_LINES + 49}" in lines[-1])

# --- reflect parses lessons, strips bullets, caps at 3, honours NONE ---
def stub(reply):
    S.chat = lambda *a, **k: {"content": reply, "tool_calls": []}
bot = {"id": "b", "model": "m"}
stub("- use python3, not python\n- pytest needs `python3 -m pytest`\n4. keep it small\n- extra")
notes = S.reflect(bot, "task", "report", ["run_shell"])
ok("reflect strips bullets and numbering", notes[:3] == ["use python3, not python", "pytest needs `python3 -m pytest`", "keep it small"])
ok("reflect caps at 3 lessons", len(notes) == 3)

stub("NONE")
ok("reflect returns [] on NONE", S.reflect(bot, "t", "r", ["run_shell"]) == [])
stub("[model error: HTTP 500]")
ok("reflect swallows model errors", S.reflect(bot, "t", "r", ["run_shell"]) == [])
stub("   ")
ok("reflect returns [] on blank reply", S.reflect(bot, "t", "r", ["run_shell"]) == [])

# --- the router sometimes answers with empty content; one retry must recover the lesson ---
calls = {"n": 0}
def flaky(*a, **k):
    calls["n"] += 1
    return {"content": "" if calls["n"] == 1 else "- venv lives at .venv; activate it first", "tool_calls": []}
S.chat = flaky
ok("reflect retries once after an empty reply", S.reflect(bot, "t", "r", ["run_shell"]) == ["venv lives at .venv; activate it first"])
ok("the retry only fires once", calls["n"] == 2)

# --- a bot with memory off never reflects ---
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server.py"), encoding="utf-8").read()
# The gate moved into `_learn`, which is the caller: memory on, and a turn that actually did work
# (fewer than two tools is a greeting or a one-liner, and the round-trip would be a per-turn tax).
ok("reflection is gated on the bot's memory flag",
   'bot.get("memory")' in src and 'len(out.get("used") or []) >= 2' in src)
# The memory notes go into the prompt on every run — direct chat, a room turn, a delegation alike —
# so the gate is the bot's own flag and never the session's `bot` field (which only a direct chat has).
ok("memory is injected in every run, not just direct chat",
   'if bot.get("memory"):' in src and 'st.get("bot") == bid' not in src.split('if bot.get("memory"):')[1][:200])

# --- skills actually reach the system prompt ---
captured = {}
S.chat = lambda model, messages, tools=None, max_tokens=1600: (captured.update(sys=messages[0]["content"]), {"content": "done", "tool_calls": []})[1]
bots = [{"id": "sk1", "name": "Sk", "instructions": "be a bot", "model": "m", "memory": False,
         "approval": "full", "skills": ["testing", "verification"], "tools_allow": None}]
list(S.run_agent("sk1", "sk1", "go", "", {}, bots, S.load_settings()))
prompt = captured.get("sys", "")
ok("enabled skills are named in the prompt", "Testing" in prompt and "Verification" in prompt)
ok("skill guidance rides along with the name", "checks that actually fail on a bug" in prompt)

bots[0]["skills"] = []
captured.clear()
list(S.run_agent("sk1", "sk1", "go", "", {}, bots, S.load_settings()))
ok("no skills selected means no skills line", "Lean on your skills" not in captured.get("sys", ""))

# --- an installed skill reaches the prompt as an index entry, and its guidance on demand ---
S.SKILLS_DIR = os.path.join(tmp, "skills"); S.SKILLS_FILE = os.path.join(tmp, "skills.json")
import io as _io, zipfile as _zip
_z = _io.BytesIO()
with _zip.ZipFile(_z, "w") as z:
    z.writestr("house-style/SKILL.md", "---\nname: House Style\ndescription: our conventions\n---\n"
                                      "Always use tabs and write the changelog first.\n")
made, errs = S.install_skill_zip(_z.getvalue(), "t.zip")
ok("the zip installed a skill for the prompt test", [m["id"] for m in made] == ["house-style"])
bots[0]["skills"] = ["house-style"]
captured.clear()
list(S.run_agent("sk1", "sk1", "go", "", {}, bots, S.load_settings()))
prompt = captured.get("sys", "")
ok("an installed skill is named in the prompt", "House Style" in prompt)
# The guidance is deliberately not inlined: a prompt carrying every skill's full text is the thing
# that made turns overflow, so the prompt carries the index and the bot reads one on demand. What
# has to be true is that the body is reachable that way, not that it is already in the prompt.
ok("an installed skill's guidance is not inlined into the prompt", "write the changelog first" not in prompt)
ok("...and the bot is told how to read it", "use_skill" in prompt)
_body, _files = S.skill_doc("house-style")
ok("...and reading it on demand gives the guidance itself", "write the changelog first" in _body)

# --- team import: a BotMRR playbook becomes bots + a room ---
FIXTURE = """---
botmrr: 1
id: demo
name: Demo Team
agents:
  - key: lea
    name: Lea
    title: Producer
    description: Owns scope and delivery.
    appearance:
      color: purple
      mascotExpression: focused
    playbooks:
      - planning
  - key: alex
    name: Alex
    title: UI Engineer
    description: Builds the interface.
    appearance:
      color: cyan
rooms:
  - key: demo-room
    name: Demo Room
    members:
      - lea
      - alex
    bulletin: Keep it small.
    defaultResponder:
      kind: agent
      agent: lea
routines: []
"""
t = S.parse_team(FIXTURE)
ok("parses the team name", t["name"] == "Demo Team")
ok("parses every agent", [a["name"] for a in t["agents"]] == ["Lea", "Alex"])
ok("parses titles (the positions)", [a["title"] for a in t["agents"]] == ["Producer", "UI Engineer"])
ok("parses descriptions", t["agents"][0]["description"] == "Owns scope and delivery.")
ok("parses nested appearance colours", [a["color"] for a in t["agents"]] == ["purple", "cyan"])
ok("parses room members", t["rooms"][0]["members"] == ["lea", "alex"])
ok("parses the nested defaultResponder as the lead", t["rooms"][0]["lead"] == "lea")
ok("ignores unrelated sections", len(t["agents"]) == 2 and len(t["rooms"]) == 1)
ok("off-palette colours map onto the app palette", S.IMPORT_COLORS["cyan"] == "blue" and S.IMPORT_COLORS["coral"] == "pink")
ok("role hints drive emoji and skills", S._role_hint("QA and Release Engineer")[0] == "🧪"
   and "testing" in S._role_hint("Backend Engineer")[1])
ok("a non-BotMRR paste falls through to the model",
   S.parse_team("Lea - Producer\nAlex - UI")["agents"] == [])

made, rooms = S.build_team(FIXTURE)
ok("build_team makes one bot per agent", [b["name"] for b in made] == ["Lea", "Alex"])
ok("build_team gives each bot a title", [b["title"] for b in made] == ["Producer", "UI Engineer"])
ok("build_team wires the room members", rooms and rooms[0]["members"] == ["lea", "alex"])
ok("build_team wires the lead", rooms[0]["lead"] == "lea")
ok("the room bulletin becomes its instructions", rooms[0]["instructions"] == "Keep it small.")
ok("imported bots default to the configured model", all(b["model"] == S.DEFAULT_MODEL for b in made))
ok("imported bots persist", [b["id"] for b in S.load_bots() if b["id"] in ("lea", "alex")] == ["lea", "alex"])
ok("the imported room persists", any(c["id"] == "demo-room" for c in S.load_channels()))
ok("an id collision gets a suffix", S.build_team(FIXTURE)[0][0]["id"] == "lea-2")

# --- team import: the structure we hand out is the structure we accept ---
# The copy button hands out TEAM_TEMPLATE and the endpoint holds a paste to it, so the one thing that
# must never drift is that pair. A template we would ourselves refuse is the bug this catches.
ok("the fixture is a clean playbook", S.team_problems(FIXTURE) == [])
ok("the template we hand out is accepted by our own validator", S.team_problems(S.TEAM_TEMPLATE) == [])
_t = S.parse_team(S.TEAM_TEMPLATE)
ok("...and it is a real playbook, not a stub", len(_t["agents"]) == 2 and len(_t["rooms"]) == 1)
ok("...and it names a chief", _t["chief"] == "lead")
# The real BotMRR shape (botmrr.io/bots/engineering, trimmed) has to pass: this is what users paste.
REAL = """---
botmrr: 1
id: engineering
release: 1.0.0
name: Ship Software Safely
tagline: Turn a product change into a scoped plan.
category: Engineering
author:
  name: OpenMausBot
  url: https://openmausbot.com
agents:
  - key: ada
    name: Ada
    title: Tech Lead
    description: Own technical direction and turn product intent into a plan.
    appearance:
      color: purple
      mascotExpression: focused
    playbooks:
      - architecture-decision
  - key: lin
    name: Lin
    title: Backend Engineer
    description: Own services, data models, APIs, migrations and reliability.
    appearance:
      color: green
chiefOfStaff: ada
rooms:
  - key: engineering-room
    name: Engineering Room
    members:
      - ada
      - lin
    bulletin: Start with the user-visible outcome.
    defaultResponder:
      kind: agent
      agent: ada
routines: []
playbooks:
  - key: architecture-decision
    name: Architecture Decision
    summary: Record a focused technical decision.
---
"""
ok("a real botmrr.io playbook passes unchanged", S.team_problems(REAL) == [])

def _probs(text): return "\n".join(S.team_problems(text))
def _playbook(**over):
    """The template with one line replaced, so each check is about exactly one missing part."""
    t = S.TEAM_TEMPLATE
    for old, new in over.items(): t = t.replace(old, new)
    return t

ok("a paste with no agents is told so",
   "no `agents:`" in _probs(_playbook(**{"agents:\n": ""})))
ok("a paste with no rooms is told so", "no `rooms:`" in _probs(_playbook(**{"rooms:\n": ""})))
ok("an agent missing its title is named",
   "agent 2 (Dima) has no `title`" in _probs(_playbook(**{"    title: Engineer\n": ""})))
ok("an agent missing its description is named",
   "has no `description`" in _probs(_playbook(**{"    description: What this bot owns, and how it should work. Two or three sentences.\n    appearance:\n      color: purple\n": ""})))
ok("an agent that opens with name instead of key is still seen, and reported",
   "agent 1 (Lea) has no `key`" in _probs(_playbook(**{"  - key: lead\n": "  - name: Lea\n"})))
ok("two agents sharing a key is named", "share the key `lead`" in _probs(_playbook(**{"  - key: dev\n": "  - key: lead\n"})))
ok("a room member that is not an agent is named",
   "lists member `ghost`, but no agent has that key" in _probs(_playbook(**{"      - dev\n": "      - ghost\n"})))
ok("a lead that is not an agent is named",
   "names lead `ghost`, but no agent has that key" in _probs(_playbook(**{"      agent: lead\n": "      agent: ghost\n"})))
ok("a room with no members is named", "has no `members`" in _probs(_playbook(**{"    members:\n      - lead\n      - dev\n": ""})))
ok("a room with no lead at all is named",
   "no `defaultResponder:` `agent:`" in _probs(_playbook(**{
       "chiefOfStaff: lead\n": "",
       "    defaultResponder:\n      kind: agent\n      agent: lead\n": ""})))
ok("a chiefOfStaff that is not an agent is named",
   "`chiefOfStaff` names `ghost`" in _probs(_playbook(**{"chiefOfStaff: lead": "chiefOfStaff: ghost"})))
ok("a plain list is not treated as a broken playbook", S.team_problems("Lea: Producer\nAlex: UI\nDima: Dev") == [])
_bare = _probs(_playbook(**{"agents:\n": "", "rooms:\n": ""}))
ok("an empty playbook names every part it is missing, not just the first",
   "no `agents:`" in _bare and "no `rooms:`" in _bare and "`chiefOfStaff` names `lead`" in _bare)

# --- team import: chiefOfStaff leads when the room names no responder ---
NOLEAD = REAL.replace("    defaultResponder:\n      kind: agent\n      agent: ada\n", "")
ok("a room that names only a chiefOfStaff is still complete", S.team_problems(NOLEAD) == [])
_made, _rooms = S.build_team(NOLEAD)
ok("...and chiefOfStaff becomes the room's lead", _rooms[0]["lead"] == "ada")

# --- image models: a config left on a dead route must still leave something to draw with ---
ok("a dead configured image route still leaves a live model to try",
   S._image_models("inf/cb/gemini-3.1-flash-image")[:1] == S.IMAGE_MODEL_FALLBACKS[:1])
ok("a live configured image route is tried before the fallbacks",
   S._image_models("inf/gemini-2.5-flash-image")[0] == "inf/gemini-2.5-flash-image")
ok("a configured route that is not a fallback is kept too",
   S._image_models("some-other-image-model")[0] == "some-other-image-model")
ok("the live image list carries a live model", bool(set(S.IMAGE_MODELS) & set(S.IMAGE_MODEL_FALLBACKS)))
ok("the live image list carries no dead model", not set(S.IMAGE_MODELS) & S.IMAGE_MODEL_DEAD)
ok("the settings picker cannot offer a dead image route", 'm["id"] not in IMAGE_MODEL_DEAD' in src)

# --- avatars: the logo decode/validate/store path, reused, plus the bot keys behind it ---
def _data(mime, blob): return "data:%s;base64,%s" % (mime, base64.b64encode(blob).decode())
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 32
GIF = b"GIF89a" + b"y" * 32

ok("_save_image refuses what is not a data URL", not S._save_image(S.AVATAR_DIR, "t1", "hello")["ok"])
ok("_save_image refuses a MIME we do not serve", not S._save_image(S.AVATAR_DIR, "t1", _data("image/tiff", PNG))["ok"])
ok("_save_image refuses a data URL with no payload", not S._save_image(S.AVATAR_DIR, "t1", "data:image/png;base64,")["ok"])
ok("...and the empty-blob guard is still there for a payload that decodes to nothing", "that file is empty" in src)
ok("_save_image refuses bytes that are not the type they claim",
   not S._save_image(S.AVATAR_DIR, "t1", _data("image/png", GIF))["ok"])
ok("_save_image refuses a blob over the 2 MB cap",
   not S._save_image(S.AVATAR_DIR, "t1", _data("image/png", PNG + b"\x00" * S.MAX_LOGO_BYTES))["ok"])
ok("_save_image stores nothing when it refuses", not os.path.isdir(S.AVATAR_DIR))

ok("save_avatar stores a picture and reports it as an upload",
   S.save_avatar("av1", _data("image/png", PNG))["ok"])
_av = S.avatar_state({"id": "av1"})
ok("...and the bot's avatar reads back as an upload with a version",
   _av["source"] == "upload" and _av["v"] > 0)
ok("remove_avatar takes the bot back to its drawn face",
   S.remove_avatar("av1") and S.avatar_state({"id": "av1"})["source"] == "")
ok("...with the version back to none", S.avatar_state({"id": "av1"})["v"] == 0)

S.save_avatar("av2", _data("image/png", PNG)); S.save_avatar("av2", _data("image/gif", GIF))
ok("a second upload in another format replaces the first, so exactly one file decides",
   sorted(f for f in os.listdir(S.AVATAR_DIR) if f.startswith("av2.")) == ["av2.gif"])
ok("an id that is not a slug names no avatar file", not S.save_avatar("../../etc", _data("image/png", PNG))["ok"])

# The channel editor depends on these exact strings, so the refactor that shares the code with
# avatars must not have reworded a single one of them.
ok("save_logo still refuses an unknown channel", S.save_logo("", "x")["error"] == "unknown channel")
ok("save_logo still refuses a non-image", S.save_logo("lg1", "hello")["error"] == "that is not an image file")
ok("save_logo still lists the formats it takes",
   S.save_logo("lg1", _data("image/tiff", PNG))["error"] == "use a png, jpg, webp, gif or svg")
ok("save_logo still refuses bytes that are not the type they claim",
   S.save_logo("lg1", _data("image/png", GIF))["error"] == "that file is not really a png")
ok("save_logo still returns exactly {ok: True} on success", S.save_logo("lg1", _data("image/png", PNG)) == {"ok": True})

# --- a bot record written before outfit/accessory/avatar existed still answers with them ---
_pub = S.H._bots_public(None, [{"id": "old", "name": "Old"}])[0]
ok("a bot from before the avatar keys still reports an outfit", _pub["outfit"] == "")
ok("...an accessory", _pub["accessory"] == "")
ok("...and no avatar version", _pub["avatar"] == 0)
ok("a bot with an outfit keeps it", S.H._bots_public(None, [{"id": "n", "outfit": "hoodie"}])[0]["outfit"] == "hoodie")

# --- Bot faces: the photo decides the animal, and a chosen face beats an older picture ---
# The prompt used to name the bot's engine species ("Species: owl"), and the model obeyed it over
# the photo: a cat came back as an owl. The species is still passed in (the caller has it) but it
# must not reach the prompt.
_p = S.face_prompt("owl", "purple", 0, 3)
ok("the face prompt does not name the bot's species", "owl" not in _p and "Species:" not in _p)
ok("the face prompt keeps the animal in the photo", "SAME ANIMAL" in _p and "never change its species" in _p)
ok("the bot's colour is only an accent, not a recolour", "Only a collar" in _p and "purple" in _p)
ok("...and a run with no colour says nothing about one", "Only a collar" not in S.face_prompt("", "", 0, 1))

S.save_avatar("fb1", _data("image/png", PNG))
_b = {"id": "fb1", "genface": "", "avatar": 7}
S.set_genface(_b, "f-1-1.png")
ok("a face from the set lands on the bot", _b["genface"] == "f-1-1.png")
ok("...and it drops an older per-bot picture that would have outranked it", _b["avatar"] == 0)
ok("...including the stored file, so nothing is left behind",
   not os.path.isfile(os.path.join(S.AVATAR_DIR, "fb1.png")))
S.set_genface(_b, "")
ok("clearing a face puts the bot back on its drawn bot", _b["genface"] == "")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
