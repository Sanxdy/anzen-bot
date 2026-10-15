#!/usr/bin/env python3
"""Offline checks for self-learning, skills and team import.

No router needed — server.chat is stubbed.  Usage:  python3 tests/test_memory.py
"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as S

tmp = tempfile.mkdtemp()
S.MEMDIR = tmp
S.SESS_PATH = os.path.join(tmp, "sessions.json")   # keep run_agent's sessions out of the real data dir
S.BOTS_PATH = os.path.join(tmp, "bots.json")       # keep build_team's bots out of the real data dir
S.CH_PATH = os.path.join(tmp, "channels.json")
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

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
