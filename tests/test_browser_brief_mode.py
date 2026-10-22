#!/usr/bin/env python3
"""The browsing line a bot is told must match the mode that is actually set.

The failure this answers: the mode was "profiles" (own browser — saved profiles), but the bot was
still told a "Zen Pilot profile" existed, so it spent two minutes launching and probing an app that
was never in play before it gave up and used `browser_open`, which worked. Everything a bot reads
about browsing has to come from the live mode, and in profiles/own mode it must never name Zen Pilot
nor leave the bot free to start or attach to another browser.

Pure functions only — nothing here launches a browser.

Usage:  .venv/bin/python tests/test_browser_brief_mode.py
"""
import os, sys, tempfile

tmp = tempfile.mkdtemp(prefix="anzen-brief-")
os.environ["DATA_DIR"] = tmp
os.environ["SANDBOX_DIR"] = os.path.join(tmp, "sandbox")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as S

assert S.DATA.startswith(tmp) and S.SET_PATH.startswith(tmp), "test paths must point into tmp"

fails = []
def check(name, ok, extra=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra and not ok else ""))
    if not ok: fails.append(name)

def brief(**b):
    s = S.load_settings(); s.setdefault("browser", {}).update(b); S.save_settings(s)
    return S.browser_brief({"browser": b.get("accounts") or []})

own_line = S.BROWSER_OWN_LINE.strip()

# profiles mode — the mode in the bug report. An account named after the app must not make the brief
# name the app: the account name is the user's, the mechanism is this app's own saved-profile browser.
p = brief(mode="profiles", accounts=[{"name": "Zenpilot threads", "sites": "https://www.threads.com/"}])
check("profiles mode names the account and its site", "Zenpilot threads" in p and "threads.com" in p, p)
check("  ...and never calls Zen Pilot the mechanism", "Zen Pilot" not in p, p)
check("  ...and says the app owns the browsers and to probe nothing", own_line in p, p)

# own mode — no accounts at all.
o = brief(mode="own", accounts=[])
check("own mode says no account is set up", "no account is set up" in o, o)
check("  ...and never names Zen Pilot", "Zen Pilot" not in o, o)
check("  ...and carries the same 'the app owns the browsers' line", own_line in o, o)

# The retired mode. A save that still says "cdp" (or "zenpilot") must come back as saved profiles, and
# the fields only that mode used must not survive to confuse anything that reads them.
import json
with open(S.SET_PATH, "w") as f:
    json.dump({"browser": {"mode": "cdp", "port": 9222, "target_url": "https://x.com",
                           "profile": "default", "cdp_url": "http://127.0.0.1:9222",
                           "launch_cmd": "open -a 'Zen Pilot'", "accounts": []}}, f)
mig = S._load_settings_raw()["browser"]
check("a saved cdp mode is moved to saved profiles", mig["mode"] == "profiles", mig)
check("  ...and the fields only it used are retired",
      not [k for k in ("port", "target_url", "profile", "cdp_url", "launch_cmd") if k in mig], mig)

# The two static strings a bot also reads: the tool doc and the browser_open tool description.
check("the tool doc never names Zen Pilot (it rides in every prompt)",
      "Zen Pilot" not in S.TOOL_DOC, S.TOOL_DOC[-200:])
check("the browser_open description never names Zen Pilot",
      "Zen Pilot" not in S.TOOL_SCHEMAS["browser_open"]["function"]["description"])

# ---- a room's own accounts: the binding lives on the room, not in general settings ----
# A room's browser setting is the room's, so a bot working there must be told about the room's
# accounts and never about one it cannot route through.
brief(mode="profiles", accounts=[{"name": "Global X", "sites": "x.com"}])
room = {"id": "promo", "browser": [{"name": "Threads me", "sites": "threads.com"}]}
rb = S.browser_brief(room)
check("a room's brief names the room's account", "Threads me" in rb and "threads.com" in rb, rb)
check("  ...and not the machine-wide one", "Global X" not in rb, rb)
check("  ...and says the chat is the scope", "this chat is set up with accounts" in rb, rb)
check("a chat with no accounts of its own is told it has none",
      "no account is set up for this chat" in S.browser_brief({"browser": []}), S.browser_brief({"browser": []}))
check("  ...and never hears about the machine-wide list", "Global X" not in S.browser_brief({"browser": []}))

empty = S._norm_channels([{"id": "promo", "name": "Promo"}])[0]
check("a room the file left without accounts gets an empty list", empty["browser"] == [], empty)
junk = S._norm_channels([{"id": "promo", "name": "Promo", "browser": [
    {"name": " Zenpilot.pro ", "sites": " x.com "}, {"sites": "y.com"}, "junk"]}])[0]
check("a room's account rows keep only a name and sites, trimmed",
      junk["browser"] == [{"name": "Zenpilot.pro", "sites": "x.com"}], junk["browser"])
check("a record with no accounts routes nothing — it does not borrow the machine-wide list",
      S._own_routes({"browser": []}) == {})
check("a record with accounts routes its own sites",
      S._own_routes(room) == {"threads.com": ["Threads me"]}, S._own_routes(room))
check("a turn in a room uses the room's accounts",
      S._turn_routes(room, {"browser": [{"name": "Bot acct", "sites": "b.com"}]})
      == {"threads.com": ["Threads me"]})
check("a turn in a bot's own chat uses the bot's accounts",
      S._turn_routes(None, {"browser": [{"name": "Bot acct", "sites": "b.com"}]})
      == {"b.com": ["Bot acct"]})

# The accounts used to be one machine-wide list in Settings → Browser, a tab that is gone. A room
# adopts that list once, or the setup the user already made would exist only as a fallback they cannot
# see or edit from the room. Once is the whole point: re-seeding every record on every boot is what
# made each new room and each new bot inherit the list as if the user had set it up there.
S.save_channels([{"id": "promo", "name": "Promo"},
                 {"id": "mine", "name": "Mine", "browser": [{"name": "Own", "sites": "own.com"}]}])
S.save_bots([{"id": "lead", "name": "Lead"}])
S._migrate_room_browser()
seeded = {c["id"]: c["browser"] for c in S.load_channels()}
check("a room with no accounts adopts the machine-wide list on boot",
      seeded["promo"] == [{"name": "Global X", "sites": "x.com"}], seeded)
check("  ...while a room that set its own keeps them",
      seeded["mine"] == [{"name": "Own", "sites": "own.com"}], seeded)
check("  ...and no bot adopts it, so a bot's own chat starts with nothing",
      S.load_bots()[0]["browser"] == [], S.load_bots()[0]["browser"])
S.save_channels(S.load_channels() + [{"id": "new", "name": "New"}])
S._migrate_room_browser()
check("a room made afterwards starts with no accounts",
      S.channel_by_id(S.load_channels(), "new")["browser"] == [])
chs = S.load_channels()
for c in chs:
    if c["id"] == "promo": c["browser"] = []
S.save_channels(chs)
S._migrate_room_browser()
check("  ...and a list the user emptied later is not refilled on the next boot",
      S.channel_by_id(S.load_channels(), "promo")["browser"] == [])

B = S.BROWSER; rt = S._own_routes(room)
check("the browser routes a room's site through the room's table",
      B._route("https://threads.com/home", rt) == "Threads me")
check("  ...and does not fall back to the machine-wide account for another site",
      B._route("https://x.com/", rt) is None)
check("a caller with no table routes nothing, not the machine-wide account",
      B._route("https://x.com/") is None)

rp = S.browser_own_profiles([{"name": "Threads me", "sites": "threads.com"}])["profiles"]
check("a room's account list shows only the room's accounts",
      [p["name"] for p in rp] == ["Threads me"], [p["name"] for p in rp])
check("  ...and knows the site it covers", rp[0]["hosts"] == ["threads.com"], rp[0]["hosts"])

# The turn's own routing table reaches the browser: a `browser_open` inside a room must carry the
# room's table, or the bot is told about an account it cannot actually reach.
seen = {}
real_call = S.BROWSER.call
S.BROWSER.call = lambda fn, **kw: (seen.update(kw), "(stub)")[1]
S._WORK.routes = rt
S.exec_tool("producer", "browser_open", {"url": "https://threads.com/"})
check("browser_open carries the room's routing table to the browser", seen.get("routes") == rt, seen)
S._WORK.routes = None
seen.clear()
S.exec_tool("producer", "browser_open", {"url": "https://threads.com/"})
check("  ...and a call with no table routes nothing, not the machine-wide list",
      seen.get("routes") is None, seen)
seen.clear()
S.exec_tool("producer", "browser_open", {"url": "https://threads.com/", "account": "Threads me"})
check("  ...and the account a bot names rides with the call",
      seen.get("account") == "Threads me", seen)
S.BROWSER.call = real_call

# The wiring, not just the function: a turn running in a room must actually be handed the room's
# brief. The model call is stubbed, so this is one prompt assembled exactly as a real one is.
bots = [{"id": "lead", "name": "Lead", "model": "m", "instructions": "", "tools": []}]
S.save_channels([{"id": "promo", "name": "Promo", "members": ["lead"], "mode": "lead", "lead": "lead",
                  "instructions": "", "folder": "",
                  "browser": [{"name": "Room acct", "sites": "example.com"}]}])
sent = []
def cap_stream(model, messages, tools=None, max_tokens=None, attempts=None):
    sent.append(messages[0]["content"] if messages[0].get("role") == "system" else
                "\n".join(m.get("content") or "" for m in messages if m.get("role") == "system"))
    yield ("done", {"content": "ok", "tool_calls": []})
real = S.chat_stream; S.chat_stream = cap_stream
try:
    S.new_session("promo", bot="lead")
    list(S.run_agent("promo", "lead", "hi", "", {}, bots, S.load_settings(), 0))
finally:
    S.chat_stream = real
sysmsg = sent[-1] if sent else ""
check("a turn in a room gets that room's accounts in its prompt",
      "Room acct" in sysmsg and "example.com" in sysmsg, sysmsg[-600:])
check("  ...and not the machine-wide account, which it cannot route through",
      "Global X" not in sysmsg, sysmsg[-600:])

print("FAILED: " + ", ".join(fails) if fails else "all checks passed")
sys.exit(1 if fails else 0)
