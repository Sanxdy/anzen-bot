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
    return S.browser_brief()

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

# cdp mode — unchanged. The Zen Pilot wording is the truth there and must stay.
c = brief(mode="cdp", accounts=[])
check("cdp mode keeps the Zen Pilot wording it always had", "Zen Pilot" in c, c)

# The two static strings a bot also reads: the tool doc and the browser_open tool description.
check("the tool doc never names Zen Pilot (it rides in every prompt)",
      "Zen Pilot" not in S.TOOL_DOC, S.TOOL_DOC[-200:])
check("the browser_open description never names Zen Pilot",
      "Zen Pilot" not in S.TOOL_SCHEMAS["browser_open"]["function"]["description"])

print("FAILED: " + ", ".join(fails) if fails else "all checks passed")
sys.exit(1 if fails else 0)
