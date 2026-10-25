#!/usr/bin/env bash
# Confirm the workspace-bundle feature works on THIS machine, without touching the real workspace.
#
#   cd /path/to/anzen-bot && bash verify-bundle.sh
#
# It backs up data/, runs the offline checks, then moves a workspace from one data folder into a
# second empty one — the same thing "export on the laptop, import on the VPS" does, but both halves
# happen here in throwaway folders. Your own bots, chats and memory are only ever read.
set -u
cd "$(dirname "$0")" || exit 1

pass=0; fail=0
say() { printf '%s %s\n' "$1" "$2"; }
ok()  { pass=$((pass+1)); say "PASS" "$1"; }
no()  { fail=$((fail+1)); say "FAIL" "$1"; }

echo "folder: $(pwd)"

# --- 1. is this copy the one with the feature? ---
if [ -f server.py ] && [ -f app.js ]; then
  ok "this is an anzen-bot folder"
else
  no "run me from the anzen-bot folder (no server.py here)"; echo; echo "0 passed, 1 failed"; exit 1
fi
if grep -q '"/api/workspace/export"' server.py && grep -q "function tabBundle" app.js; then
  ok "this copy has the bundle feature (server + UI)"
else
  no "this copy does not have the bundle feature yet — apply the patch first"; echo; echo "$pass passed, $fail failed"; exit 1
fi
if [ -f tests/test_workspace_bundle.py ]; then ok "the checks for it are here"; else no "tests/test_workspace_bundle.py is missing"; fi

# --- 2. back up the real workspace, because the next steps are the only ones that write ---
if [ -d data ]; then
  B="data.before-bundle-$(date +%Y%m%d-%H%M)"
  if cp -R data "$B" 2>/dev/null; then ok "backed up your workspace to $B"; else no "could not back up data/"; fi
else
  say "----" "no data/ folder yet (fresh install) — nothing to back up"
fi

# --- 3. the offline checks ---
echo
echo "-- offline checks: the bundle itself --"
if python3 tests/test_workspace_bundle.py > /tmp/vb-pytest.log 2>&1; then
  ok "test_workspace_bundle.py: $(tail -1 /tmp/vb-pytest.log)"
else
  no "test_workspace_bundle.py failed"; tail -12 /tmp/vb-pytest.log
fi

echo
echo "-- offline checks: the panel --"
if command -v node > /dev/null 2>&1; then
  if [ -f tests/test_bundle_tab.mjs ]; then
    if node tests/test_bundle_tab.mjs > /tmp/vb-nodetest.log 2>&1; then
      ok "test_bundle_tab.mjs: $(tail -1 /tmp/vb-nodetest.log)"
    else
      no "test_bundle_tab.mjs failed"; tail -12 /tmp/vb-nodetest.log
    fi
  else
    no "tests/test_bundle_tab.mjs is missing"
  fi
else
  say "----" "node is not installed — skipping the panel checks (the app itself only needs python)"
fi

# --- 4. move a workspace from one folder into another, the way two machines do ---
echo
echo "-- a real move: one workspace out, a second one in --"
A=$(mktemp -d); C=$(mktemp -d); Z="$(mktemp -d)/bundle.zip"
if python3 - "$A" "$Z" <<'PY'
import os, sys, base64
out, zpath = sys.argv[1], sys.argv[2]
os.environ["DATA_DIR"] = out
sys.path.insert(0, os.getcwd())
import server as S
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40).decode()
S.save_bots([{"id": "probe", "name": "Probe", "title": "Checker", "color": "green",
              "model": S.DEFAULT_MODEL, "approval": "ask", "instructions": "You check things.",
              "skills": ["notes"], "emoji": "\U0001f50d"}])
S.save_channels([{"id": "lab", "name": "Lab", "members": ["probe"], "mode": "lead", "lead": "probe"}])
with S._RT_LOCK:
    S.save_routines([{"id": "r1", "session": "probe", "bot": "probe", "prompt": "check",
                      "every": 3600, "cron": None, "paused": False, "last": 0}])
S._save_json(S.SKILLS_FILE, [{"id": "notes", "name": "Notes", "desc": "d", "body": "b"}])
os.makedirs(os.path.join(S.SKILLS_DIR, "notes"), exist_ok=True)
open(os.path.join(S.SKILLS_DIR, "notes", "SKILL.md"), "w").write("# Notes\n")
S.mem_append("probe", "a note that has to travel")
S._save_image(S.AVATAR_DIR, "probe", "data:image/png;base64," + PNG, "avatar")
S._save_image(S.FACES_DIR, "probe", "data:image/png;base64," + PNG, "face")
S._save_image(S.LOGO_DIR, "lab", "data:image/png;base64," + PNG, "logo")
S.save_settings({**S.load_settings(), "company_name": "Probe Works", "user_name": "Tester",
                 "api_keys": {"elevenlabs": "sk-must-not-travel"}})
S._write_sessions({"probe": {"bot": "probe", "title": "Probe", "model": None, "pending": None,
                             "approval": None, "messages": [{"role": "user", "text": "hello"}]}})
blob, err = S.export_bundle()
if err: print("export refused:", err); raise SystemExit(1)
open(zpath, "wb").write(blob)
print("exported %d bytes" % len(blob))
PY
then ok "exported a workspace to a file"
else no "the export failed"; fi

if python3 - "$C" "$Z" <<'PY'
import os, sys, json
into, zpath = sys.argv[1], sys.argv[2]
os.environ["DATA_DIR"] = into
sys.path.insert(0, os.getcwd())
import server as S
blob = open(zpath, "rb").read()
info, err = S.bundle_manifest(blob)
if err: print("inspect refused:", err); raise SystemExit(1)
res, err = S.import_bundle(blob, "replace")
if err: print("import refused:", err); raise SystemExit(1)
problems = []
bots = {b["id"]: b for b in S.load_bots()}
if "probe" not in bots: problems.append("the bot did not arrive")
else:
    b = bots["probe"]
    if b["color"] != "green": problems.append("the colour did not arrive")
    if b["instructions"] != "You check things.": problems.append("the instructions did not arrive")
    if b["emoji"] != "\U0001f50d": problems.append("the emoji did not arrive")
    if b["avatar"] <= 0: problems.append("the avatar was not re-stamped")
if "lab" not in {c["id"] for c in S.load_channels()}: problems.append("the room did not arrive")
if [r["id"] for r in S.load_routines()] != ["r1"]: problems.append("the routine did not arrive")
if "travel" not in open(S.mem_path("probe")).read(): problems.append("the memory did not arrive")
if not os.path.isfile(os.path.join(S.AVATAR_DIR, "probe.png")): problems.append("the avatar file did not arrive")
if not os.path.isfile(os.path.join(S.FACES_DIR, "probe.png")): problems.append("the face file did not arrive")
if not os.path.isfile(os.path.join(S.LOGO_DIR, "lab.png")): problems.append("the logo file did not arrive")
if not os.path.isfile(os.path.join(S.SKILLS_DIR, "notes", "SKILL.md")): problems.append("the skill's files did not arrive")
if "hello" not in json.dumps(S._all_sessions()): problems.append("the chat did not arrive")
if S.load_settings().get("company_name") != "Probe Works": problems.append("the company name did not arrive")
if S.load_settings().get("api_keys", {}).get("elevenlabs") == "sk-must-not-travel":
    problems.append("A CREDENTIAL TRAVELLED IN THE BUNDLE")
if problems:
    print("\n".join(problems)); raise SystemExit(1)
print("imported: bots %d, rooms %d, routines %d, files %d"
      % (res["wrote"]["bots"], res["wrote"]["channels"], res["wrote"]["routines"], res["wrote"]["files"]))
PY
then ok "the workspace arrived whole in a second folder"
else no "the move lost something — see above"; fi

rm -rf "$A" "$C" "$Z"

echo
if [ "$fail" -eq 0 ]; then
  echo "$pass passed, 0 failed — the feature works on this machine."
  echo
  echo "Now look at it yourself: start the app, Settings -> Backup, and press Export workspace."
  echo "Your workspace is backed up at data.before-bundle-* — delete it once you are happy."
else
  echo "$pass passed, $fail failed — do not import anything on this machine yet."
fi
exit $([ "$fail" -eq 0 ] && echo 0 || echo 1)
