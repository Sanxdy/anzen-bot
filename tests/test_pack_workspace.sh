#!/usr/bin/env bash
# Checks for pack-workspace.sh — the part that was wrong: which data folder it packs.
#
# An install can hold several workspaces. The repo's own `data/` is the five default bots and nothing
# else, while the app writes to the folder it was started with (on macOS, the desktop build keeps it
# under ~/Library/Application Support). An earlier version packed `./data` and reported 7 bots and no
# faces while the real workspace had ten bots, five rooms and thirty-eight faces.
#
# This builds both, then asserts the packer finds and packs the richer one. It runs entirely in a
# throwaway HOME, so nothing on the machine running it is read or written.
#
# Usage:  bash tests/test_pack_workspace.sh     (exit 0 = all green)
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PACK="$ROOT/pack-workspace.sh"
[ -f "$PACK" ] || { echo "FAIL no pack-workspace.sh in $ROOT"; exit 1; }

pass=0; fail=0
ok() { pass=$((pass+1)); printf '  ok   %s\n' "$1"; }
no() { fail=$((fail+1)); printf '  FAIL %s%s\n' "$1" "${2:+  -> $2}"; }

FAKE=$(mktemp -d 2>/dev/null || mktemp -d -t packtest)
trap 'rm -rf "$FAKE"' EXIT

# --- the two workspaces --------------------------------------------------------------------------
mk() {  # mk <root> <bots> <rooms> <faces> <memory> <chats>
  python3 - "$@" <<'PY'
import base64, json, os, sys
root, nb, nr, nf, nm, nc = sys.argv[1], *map(int, sys.argv[2:7])
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 60).decode()
for d in ("memory", "avatars", "faces", "logos", "skills"):
    os.makedirs(os.path.join(root, d), exist_ok=True)
ids = ["bot%d" % i for i in range(nb)]
json.dump([{"id": i, "name": i, "title": "T", "color": "blue", "model": "m",
            "approval": "ask", "instructions": "You are " + i + "."} for i in ids],
          open(os.path.join(root, "bots.json"), "w"))
json.dump([{"id": "room%d" % i, "name": "Room%d" % i, "members": ids[:2], "mode": "lead",
            "lead": ids[0]} for i in range(nr)], open(os.path.join(root, "channels.json"), "w"))
json.dump([], open(os.path.join(root, "routines.json"), "w"))
json.dump([], open(os.path.join(root, "skills.json"), "w"))
json.dump({"company_name": "Anzen", "api_keys": {"elevenlabs": "sk-must-not-travel"}},
          open(os.path.join(root, "settings.json"), "w"))
json.dump({("chat%d" % i): {"title": "c", "messages": [{"role": "user", "text": "hi"}] * 3}
           for i in range(nc)}, open(os.path.join(root, "sessions.json"), "w"))
for i in range(nf):
    open(os.path.join(root, "faces", "f%d.png" % i), "wb").write(base64.b64decode(PNG))
for i in range(nm):
    open(os.path.join(root, "memory", "m%d.md" % i), "w").write("# Notes\n- a note\n")
PY
}

REPO="$FAKE/anzen-bot"
APP="$FAKE/Library/Application Support/anzen-bot/data"
mkdir -p "$REPO"
mk "$REPO/data" 5 1 0 0 1          # the repo's own folder: the defaults, nothing in it
mk "$APP" 10 5 38 10 5             # the workspace in use

# --- it must find both, and pick the one in use ---------------------------------------------------
LIST=$(cd "$REPO" && HOME="$FAKE" bash "$PACK" --list 2>&1)
echo "$LIST" | grep -q "candidate workspaces found: 2" && ok "it finds both workspaces" \
  || no "it should find two workspaces" "$(echo "$LIST" | head -3)"
echo "$LIST" | grep -q "packing this one" && ok "it marks the one it will pack" || no "no choice is marked"
# The line that is marked must be the rich folder, not the repo's. The marker trails the path, so it
# is cut off before comparing.
CHOSEN=$(echo "$LIST" | grep "packing this one" | sed 's/ *<-- packing this one *$//' | grep -o '/.*' | sed 's/ *$//')
case "$CHOSEN" in
  *"Application Support/anzen-bot/data") ok "it picks the workspace in use, not the repo's data/" ;;
  *) no "it picked the wrong folder" "$CHOSEN" ;;
esac
echo "$LIST" | grep -q "Nothing packed" && ok "--list packs nothing" || no "--list must not pack"

# --- a real run: the zip carries the rich workspace, and no credential ----------------------------
RUN=$(cd "$REPO" && HOME="$FAKE" bash "$PACK" 2>&1)
ZIP=$(echo "$RUN" | grep -oE '/[^ ]+\.zip' | head -1)
if [ -n "$ZIP" ] && [ -f "$ZIP" ]; then ok "it writes a zip"; else no "no zip was written" "$RUN"; fi
python3 - "$ZIP" <<'PY'
import json, sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
names = z.namelist()
bots = len(json.loads(z.read("bots.json")))
rooms = len(json.loads(z.read("channels.json")))
faces = sum(1 for n in names if n.startswith("faces/"))
raw = b"".join(z.read(n) for n in names)
bad = []
if bots != 10: bad.append("bots=%d, expected 10" % bots)
if rooms != 5: bad.append("rooms=%d, expected 5" % rooms)
if faces != 38: bad.append("faces=%d, expected 38" % faces)
if b"sk-must-not-travel" in raw: bad.append("A CREDENTIAL TRAVELLED")
if "manifest.json" not in names: bad.append("no manifest.json — it would not import")
if "REPORT.txt" not in names: bad.append("no REPORT.txt")
print("\n".join(bad))
raise SystemExit(1 if bad else 0)
PY
if [ $? -eq 0 ]; then ok "the zip holds the whole workspace, and no credential"
else no "the zip is wrong (see above)"; fi

# --- naming a folder wins over the ranking --------------------------------------------------------
NAMED=$(cd "$REPO" && HOME="$FAKE" bash "$PACK" --list "$REPO/data" 2>&1)
echo "$NAMED" | grep -q "packing this one" && ok "an explicit folder is still ranked" || no "naming a folder broke the run"

echo
echo "$pass ok, $fail failed"
[ "$fail" -eq 0 ] || exit 1
