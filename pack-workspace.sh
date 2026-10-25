#!/usr/bin/env bash
# Pack this machine's anzen-bot workspace into ONE zip you can send for checking.
#
#   bash pack-workspace.sh              # finds the workspace itself, packs the richest one
#   bash pack-workspace.sh --list       # only show the candidates, pack nothing
#   bash pack-workspace.sh /path/data   # a folder you name yourself
#   bash pack-workspace.sh --no-chats   # leave the conversations out
#
# It does NOT assume ./data is the workspace. An install can have several data folders — the repo's
# own (default bots, nothing in it), the one the app actually writes, and one the desktop build keeps
# under ~/Library/Application Support. Packing the wrong one is what made an earlier version report
# 7 bots and no faces while the real workspace had far more, so every candidate is now found and
# scored by what it really contains, and the richest is packed.
#
# Nothing here writes to the workspace: files are read, copied into a temp folder, and zipped.
# Credentials are cut out on the way. The zip is flat with a manifest.json at its root, so it is
# also a bundle: Settings -> Backup -> Import accepts it directly on another machine.
#
# Works on macOS (bash 3.2) and Linux. Run: bash pack-workspace.sh
set -u

WITH_CHATS=1
LIST_ONLY=0
DATA_ARG=""
for a in "$@"; do
  case "$a" in
    --no-chats) WITH_CHATS=0 ;;
    --list) LIST_ONLY=1 ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) DATA_ARG="$a" ;;
  esac
done

if ! command -v python3 > /dev/null 2>&1; then
  echo "python3 is not on PATH. It is what this app runs on, so start the shell the app uses"
  echo "(or install Python 3) and run me again."
  exit 1
fi

HERE=$(cd "$(dirname "$0")" && pwd)

# --- every place a workspace could be --------------------------------------------------------------
# Not a guess: each of these is somewhere an anzen-bot data folder really ends up. The list is
# gathered, then scored by contents, because a folder that exists is not a folder that is in use.
CANDS=$(mktemp 2>/dev/null || mktemp -t anzenc)
trap 'rm -f "$CANDS"' EXIT
add() {
  [ -n "${1:-}" ] && [ -d "$1" ] && [ -f "$1/bots.json" ] && printf '%s\n' "$(cd "$1" 2>/dev/null && pwd)" >> "$CANDS"
}
add "$DATA_ARG"
add "${DATA_DIR:-}"
add "$PWD/data"
add "$HERE/data"
add "$HERE/../data"
add "$HOME/anzen-bot/data"
add "$HOME/.anzen-bot"
add "$HOME/.anzen-bot/data"
for base in "$HOME/Library/Application Support" "$HOME/.local/share" "$HOME/.config"; do
  [ -d "$base" ] || continue
  for d in "$base"/*anzen* "$base"/*Anzen*; do
    [ -d "$d" ] || continue
    add "$d"; add "$d/data"
  done
done
# A bounded sweep, in case the app was started from somewhere unexpected. Depth 4 and the usual heavy
# folders pruned, so this stays quick on a home directory with node_modules in it.
if [ -z "$DATA_ARG" ]; then
  for p in $(find "$HOME" -maxdepth 4 -name bots.json \
               -not -path "*/node_modules/*" -not -path "*/.git/*" \
               -not -path "*/Library/Caches/*" -not -path "*/Trash/*" 2>/dev/null); do
    add "$(dirname "$p")"
  done
fi
sort -u "$CANDS" -o "$CANDS" 2>/dev/null || true

if [ ! -s "$CANDS" ]; then
  echo "No anzen-bot workspace found on this machine."
  echo "Searched: $PWD/data, $HERE/data, ~/anzen-bot/data, ~/.anzen-bot,"
  echo "          ~/Library/Application Support/*anzen*, and $HOME to depth 4."
  echo "If you know where it is, name it:  bash pack-workspace.sh /path/to/data"
  exit 1
fi

# --- score them, and pick the one that is really in use --------------------------------------------
CHOSEN=$(python3 - "$CANDS" "$LIST_ONLY" <<'PY'
import json, os, sys

def jload(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d

def files(d):
    n = 0
    for _, _, fs in os.walk(d):
        n += len(fs)
    return n

rows = []
for path in [l.strip() for l in open(sys.argv[1], encoding="utf-8") if l.strip()]:
    bots = jload(os.path.join(path, "bots.json"), [])
    rooms = jload(os.path.join(path, "channels.json"), [])
    sess = jload(os.path.join(path, "sessions.json"), {})
    msgs = sum(len((s or {}).get("messages") or []) for s in sess.values() if isinstance(s, dict))
    faces = files(os.path.join(path, "faces")) if os.path.isdir(os.path.join(path, "faces")) else 0
    avatars = files(os.path.join(path, "avatars")) if os.path.isdir(os.path.join(path, "avatars")) else 0
    mem = len([f for f in os.listdir(os.path.join(path, "memory"))
               if f.endswith(".md")]) if os.path.isdir(os.path.join(path, "memory")) else 0
    skills = jload(os.path.join(path, "skills.json"), [])
    # Weighted by what a workspace *is*: bots and rooms first, then the work that cannot be recreated —
    # faces, avatars and memory notes — then conversations. A folder holding only the default five bots
    # and no faces scores low on purpose, which is exactly the mistake this replaces.
    score = (len(bots) * 10 + len(rooms) * 8 + faces * 3 + avatars * 3 + mem * 2
             + len(skills) * 4 + msgs)
    rows.append({"path": path, "bots": len(bots), "rooms": len(rooms), "faces": faces,
                 "avatars": avatars, "mem": mem, "skills": len(skills),
                 "chats": len(sess), "msgs": msgs, "score": score})

rows.sort(key=lambda r: -r["score"])
print("candidate workspaces found: %d" % len(rows), file=sys.stderr)
print("  %-5s %-6s %-6s %-6s %-5s %-7s %-6s %-6s  %s" % (
    "bots", "rooms", "faces", "avatar", "mem", "skills", "chats", "msgs", "path"), file=sys.stderr)
for i, r in enumerate(rows):
    print("  %-5d %-6d %-6d %-6d %-5d %-7d %-6d %-6d  %s%s" % (
        r["bots"], r["rooms"], r["faces"], r["avatars"], r["mem"], r["skills"],
        r["chats"], r["msgs"], r["path"], "   <-- packing this one" if i == 0 else ""), file=sys.stderr)
if len(rows) > 1:
    print("\nIf that is the wrong folder, name the right one:  bash pack-workspace.sh '<path>'",
          file=sys.stderr)
print(rows[0]["path"])
PY
)

if [ -z "$CHOSEN" ]; then echo "Could not read any workspace."; exit 1; fi
if [ "$LIST_ONLY" = "1" ]; then
  echo
  echo "Nothing packed (--list)."
  exit 0
fi

DATA=$CHOSEN
echo
echo "workspace: $DATA"

# --- a working copy, so the zip can be built without touching the original ------------------------
WORK=$(mktemp -d 2>/dev/null || mktemp -d -t anzenpack)
OUT="$HOME/Desktop"
[ -d "$OUT" ] || OUT="$HOME"
STAMP=$(date +%Y%m%d-%H%M)
NAME="anzen-workspace-$STAMP"
mkdir -p "$WORK"
trap 'rm -rf "$WORK"; rm -f "$CANDS"' EXIT

# --- what travels: the workspace ------------------------------------------------------------------
for f in bots.json channels.json routines.json skills.json settings.json; do
  [ -f "$DATA/$f" ] && cp "$DATA/$f" "$WORK/$f"
done
[ "$WITH_CHATS" = "1" ] && [ -f "$DATA/sessions.json" ] && cp "$DATA/sessions.json" "$WORK/sessions.json"
for d in memory avatars faces logos skills; do
  [ -d "$DATA/$d" ] && cp -R "$DATA/$d" "$WORK/$d"
done

# --- what never travels: this machine, and its secrets --------------------------------------------
SKIPPED=""
for f in config.json access_token relay_secret lucent.json; do
  [ -f "$DATA/$f" ] && SKIPPED="$SKIPPED $f"
done
for d in lan browser_profiles logs; do
  [ -d "$DATA/$d" ] && SKIPPED="$SKIPPED $d/"
done

if [ -f "$WORK/settings.json" ]; then
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
fi

# --- a report and a manifest ----------------------------------------------------------------------
python3 - "$DATA" "$WORK" "$SKIPPED" "$WITH_CHATS" <<'PY'
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
    lines.append("   - %-16s %-20s %-8s %s" % (
        b.get("id", "?"), (b.get("name") or "")[:20], b.get("color", "?"),
        "face=" + (b.get("face") or b.get("genface") or "-")))
lines += [
    "rooms     %d" % len(rooms),
]
for c in rooms:
    lines.append("   - %-16s %-20s %d member(s)" % (c.get("id", "?"), (c.get("name") or "")[:20],
                                                    len(c.get("members") or [])))
lines += [
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
# Anchored so it cannot match inside a word: the earlier version flagged "task-library" and
# "task-workspaces" as if they were keys.
if grep -rIlE '(^|[^A-Za-z0-9_-])(sk-[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|AIza[A-Za-z0-9_-]{30,})' \
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
