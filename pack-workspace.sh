#!/usr/bin/env bash
# Pack this machine's anzen-bot workspace into ONE zip you can send for checking.
#
#   cd /path/to/anzen-bot && bash pack-workspace.sh
#   bash pack-workspace.sh --no-chats          # leave the conversations out
#   bash pack-workspace.sh /path/to/other/data # a data folder somewhere else
#
# The app does not have to be running. Nothing here writes to your workspace: files are only read,
# copied into a temporary folder, and zipped. Credentials are dropped on the way in, so what leaves
# this machine is the workspace and not your keys.
#
# The zip is flat, with a manifest.json at its root, so it is also a valid bundle: Settings -> Backup
# -> Import accepts it directly on another machine.
#
# Works on macOS (bash 3.2) and Linux. Run: bash pack-workspace.sh
set -u

WITH_CHATS=1
DATA_ARG=""
for a in "$@"; do
  case "$a" in
    --no-chats) WITH_CHATS=0 ;;
    -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) DATA_ARG="$a" ;;
  esac
done

# --- find the data folder -------------------------------------------------------------------------
HERE=$(cd "$(dirname "$0")" && pwd)
DATA=""
for c in "$DATA_ARG" "$HERE/data" "$HERE/../data" "$PWD/data"; do
  if [ -n "$c" ] && [ -d "$c" ] && [ -f "$c/bots.json" ]; then DATA=$(cd "$c" && pwd); break; fi
done
if [ -z "$DATA" ]; then
  echo "Could not find the workspace."
  echo "Looked for data/bots.json in: $HERE, $HERE/.., $PWD"
  echo "Pass the folder yourself:  bash pack-workspace.sh /path/to/anzen-bot/data"
  exit 1
fi
echo "workspace: $DATA"

# The app is Python, so this is always here — but say it plainly rather than failing halfway.
if ! command -v python3 > /dev/null 2>&1; then
  echo "python3 is not on PATH. It is what this app runs on, so start the shell the app uses"
  echo "(or install Python 3) and run me again."
  exit 1
fi

# --- a working copy, so the zip can be built without touching the original ------------------------
WORK=$(mktemp -d 2>/dev/null || mktemp -d -t anzenpack)
OUT="$HOME/Desktop"
[ -d "$OUT" ] || OUT="$HOME"
STAMP=$(date +%Y%m%d-%H%M)
NAME="anzen-workspace-$STAMP"
mkdir -p "$WORK"
trap 'rm -rf "$WORK"' EXIT

# --- what travels: the workspace ------------------------------------------------------------------
for f in bots.json channels.json routines.json skills.json settings.json; do
  [ -f "$DATA/$f" ] && cp "$DATA/$f" "$WORK/$f"
done
[ "$WITH_CHATS" = "1" ] && [ -f "$DATA/sessions.json" ] && cp "$DATA/sessions.json" "$WORK/sessions.json"
for d in memory avatars faces logos skills; do
  [ -d "$DATA/$d" ] && cp -R "$DATA/$d" "$WORK/$d"
done

# --- what never travels: this machine, and its secrets --------------------------------------------
# config.json holds the router address and its key; the token and the relay secret identify this
# install; browser profiles are full of logged-in cookies; logs are noise. None of it is copied.
SKIPPED=""
for f in config.json access_token relay_secret lucent.json; do
  [ -f "$DATA/$f" ] && SKIPPED="$SKIPPED $f"
done
for d in lan browser_profiles logs; do
  [ -d "$DATA/$d" ] && SKIPPED="$SKIPPED $d/"
done

# settings.json is the one file that mixes the two, so the credential sections are cut out of the
# copy. If python3 is missing the file is dropped rather than sent with a key still inside it.
if [ -f "$WORK/settings.json" ]; then
  if command -v python3 > /dev/null 2>&1; then
    python3 - "$WORK/settings.json" <<'PY' || rm -f "$WORK/settings.json"
import json, sys
p = sys.argv[1]
d = json.load(open(p, encoding="utf-8"))
for k in ("api_keys", "connectors", "mcp", "relay"):
    d.pop(k, None)
for sec in ("voice", "decision"):
    if isinstance(d.get(sec), dict):
        d[sec].pop("key", None)
json.dump(d, open(p, "w", encoding="utf-8"), indent=2)
PY
  else
    rm -f "$WORK/settings.json"
    SKIPPED="$SKIPPED settings.json(no python3 to scrub it)"
  fi
fi

# --- a report and a manifest, so the zip explains itself and can be imported ----------------------
python3 - "$DATA" "$WORK" "$SKIPPED" "$WITH_CHATS" <<'PY' 2>/dev/null || true
import json, os, sys, platform, datetime
data, stage, skipped, chats = sys.argv[1], sys.argv[2], sys.argv[3].strip(), sys.argv[4]
def jload(p, d):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return d
def count(label):
    p = os.path.join(stage, label)
    if not os.path.isdir(p): return 0
    return sum(len(fs) for _, _, fs in os.walk(p))
bots = jload(os.path.join(stage, "bots.json"), [])
rooms = jload(os.path.join(stage, "channels.json"), [])
routines = jload(os.path.join(stage, "routines.json"), [])
skills = jload(os.path.join(stage, "skills.json"), [])
chatmap = jload(os.path.join(stage, "sessions.json"), {}) if chats == "1" else {}
lines = [
    "anzen-bot workspace pack",
    "made      " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    "machine   " + platform.platform(),
    "python    " + platform.python_version(),
    "source    " + data,
    "",
    "bots      %d" % len(bots),
]
for b in bots:
    lines.append("   - %-14s %-22s %-10s %s" % (
        b.get("id", "?"), (b.get("name") or "")[:22], b.get("color", "?"),
        "face=" + (b.get("face") or b.get("genface") or "-")))
lines += [
    "rooms     %d" % len(rooms),
    "routines  %d" % len(routines),
    "skills    %d (%d files)" % (len(skills), count("skills")),
    "chats     %d" % len(chatmap),
    "memory    %d file(s)" % count("memory"),
    "avatars   %d file(s)" % count("avatars"),
    "faces     %d file(s)" % count("faces"),
    "logos     %d file(s)" % count("logos"),
    "",
    "left behind on purpose:" + (skipped or " nothing"),
]
open(os.path.join(stage, "REPORT.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
# The manifest is what makes this zip a bundle the app itself will import, not just a folder of files.
json.dump({"format": "anzen-workspace", "version": 1,
           "at": datetime.datetime.now().isoformat(timespec="seconds"),
           "counts": {"bots": len(bots), "channels": len(rooms), "routines": len(routines),
                      "skills": len(skills), "sessions": len(chatmap),
                      "memory": count("memory"), "avatars": count("avatars"),
                      "faces": count("faces"), "logos": count("logos"),
                      "skill_files": count("skills")}},
          open(os.path.join(stage, "manifest.json"), "w", encoding="utf-8"), indent=2)
print("\n".join(lines))
PY

# --- a quick check that no secret slipped through -------------------------------------------------
if grep -rIl -E 'sk-[A-Za-z0-9]{12,}|xox[baprs]-|ghp_[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{30,}' \
     "$WORK" > /tmp/anzenpack-secret.txt 2>/dev/null; then
  if [ -s /tmp/anzenpack-secret.txt ]; then
    echo
    echo "STOPPED: something that looks like a key is in the pack:"
    sed 's/^/   /' /tmp/anzenpack-secret.txt
    echo "Nothing was zipped. Send me that list and I will say what to remove."
    rm -f /tmp/anzenpack-secret.txt
    exit 1
  fi
fi
rm -f /tmp/anzenpack-secret.txt

# --- zip -----------------------------------------------------------------------------------------
# Python does the zipping, not the `zip` command: macOS ships it, plenty of Linux boxes do not, and a
# packer that fails on a missing binary is worse than one with no dependency at all.
ZIP="$OUT/$NAME.zip"
if ! python3 - "$WORK" "$ZIP" <<'PY'
import os, sys, zipfile
work, out = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for dirpath, _dirs, files in os.walk(work):
        for f in sorted(files):
            p = os.path.join(dirpath, f)
            z.write(p, os.path.relpath(p, work).replace(os.sep, "/"))
print("zipped")
PY
then echo "zip failed"; exit 1; fi
SIZE=$(wc -c < "$ZIP" | tr -d ' ')
[ "$SIZE" -gt 45000000 ] && echo "NOTE: this is over 45 MB, which Telegram will refuse. Use --no-chats, or send it another way."

echo
echo "ready:  $ZIP"
echo "size:   $((SIZE / 1024)) KB"
if command -v shasum > /dev/null 2>&1; then
  echo "sha256: $(shasum -a 256 "$ZIP" | cut -d' ' -f1)"
elif command -v sha256sum > /dev/null 2>&1; then
  echo "sha256: $(sha256sum "$ZIP" | cut -d' ' -f1)"
fi
echo
echo "Send that file. Nothing in it is a key or a login."
echo "It is also a bundle: on another machine, Settings -> Backup -> Import accepts it as it is."
