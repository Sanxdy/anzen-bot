#!/usr/bin/env python3
"""Checks for a message's attachments.

The complaint this answers: "the client should support adding attachments — any attachment, like
text, media, doc, zip — right now I cannot add any attachment to the chat." So the claims are: a file
that rides with a message is written where the bot can open it, the bot is told its path, the
transcript keeps it so reopening the chat draws it back, and the server hands it back to the page —
but only from the folder its own chat wrote to.

Pure stdlib, no model, no browser. DATA_DIR and SANDBOX_DIR are redirected before `server` is
imported, so a run can never touch the user's live workspace.

    python3 tests/test_attachments.py
"""
import base64, json, os, socket, sys, tempfile, threading, time, urllib.request, urllib.error

TMP = tempfile.mkdtemp(prefix="anzen-attach-")
os.environ.update(DATA_DIR=TMP, SANDBOX_DIR=os.path.join(TMP, "sandbox"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as S                                                    # noqa: E402
assert S.DATA.startswith(TMP) and S.SANDBOX.startswith(TMP), "test paths must point into tmp"

PASS = FAIL = 0
def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print("  PASS " + name)
    else: FAIL += 1; print("  FAIL " + name + ("  " + str(extra)[:400] if extra else ""))

def data_url(raw, ctype):
    return "data:%s;base64,%s" % (ctype, base64.b64encode(raw).decode())

print("--- a file that came with a message is written where the bot can open it ---")
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
recs = S._save_uploads("room-x", [
    {"name": "shot.png", "type": "image/png", "data": data_url(PNG, "image/png")},
    {"name": "../../escape.zip", "type": "application/zip", "data": data_url(b"PK\x03\x04zip", "application/zip")},
    {"name": "big.bin", "type": "application/octet-stream", "data": data_url(b"x" * (S.MAX_UPLOAD + 1), "")},
    {"name": "broken.txt", "type": "text/plain", "data": "not a data url"},
])
ok("the two usable files are kept, the oversize and the malformed dropped", len(recs) == 2, recs)
ok("each has a path on disk", all(os.path.isfile(r["path"]) for r in recs), recs)
ok("the bytes are the bytes", open(recs[0]["path"], "rb").read() == PNG)
ok("the reader's own name is kept", recs[0]["name"] == "shot.png" and recs[1]["name"] == "escape.zip", recs)
ok("a name that tried to climb out is a file in the chat's folder, not a path",
   os.path.dirname(recs[1]["path"]) == os.path.dirname(recs[0]["path"]), recs[1])
ok("the chat's folder is under the sandbox, not the data dir",
   os.path.realpath(os.path.dirname(recs[0]["path"])).startswith(os.path.realpath(S.SANDBOX) + os.sep))
ok("each has the url the page draws it from", recs[0]["url"].startswith("/api/upload/room-x/"), recs[0])
ok("two files with one name do not overwrite each other", recs[0]["path"] != recs[1]["path"])
again = S._save_uploads("room-x", [recs[0]])          # what a Retry sends back: the record, no payload
ok("a retry keeps the file it was handed",
   len(again) == 1 and os.path.realpath(again[0]["path"]) == os.path.realpath(recs[0]["path"]), again)
ok("...but another chat cannot claim it", S._save_uploads("room-y", [recs[0]]) == [])

print("--- the bot is told the path, and can open it during that turn ---")
note = S._attachments_note(recs)
ok("the note names both files", "shot.png" in note and "escape.zip" in note, note)
ok("...and the path it can actually read", recs[0]["path"] in note, note)
ok("...and says how big each one is", "B)" in note or "KB)" in note, note)
ok("no attachments, no note", S._attachments_note([]) == "" and S._attachments_note(None) == "")
S._WORK.uploads = os.path.dirname(recs[0]["path"])
REPO = os.path.join(TMP, "repo"); os.makedirs(REPO, exist_ok=True)
S.set_work_dir(REPO)                                   # a room with a repo of its own
ok("read_file opens an attachment during the turn",
   S.exec_tool("b", "read_file", {"path": recs[1]["path"]})[0].startswith("PK"), S.exec_tool("b", "read_file", {"path": recs[1]["path"]}))
S._WORK.uploads = None
ok("a later turn in that repo cannot read it",
   S.exec_tool("b", "read_file", {"path": recs[0]["path"]})[0] == "(no such file)")
S._WORK.uploads = os.path.dirname(recs[0]["path"])
ok("looking at an attachment is not a risky command",
   S.is_risky("file " + recs[1]["path"]) is False)
S._WORK.uploads = None
ok("...while a file outside the repo and the turn still is",
   S.is_risky("file /etc/hosts") is True)

print("--- the transcript keeps them, so a reopened chat draws them back ---")
msg = S._user_message("here it is", None, False, None, recs)
ok("the record carries the attachments", msg["attachments"] == recs)
ok("a message with none carries no empty list", "attachments" not in S._user_message("hi", None, False))
S.new_session("attach-room", bot="b")
st = S.load("attach-room"); st["messages"].append(msg); S.save("attach-room", st)
ok("...and they survive the store", S.load("attach-room")["messages"][0]["attachments"][0]["name"] == "shot.png")

print("--- the page gets the file back, and only from its own chat's folder ---")
_s = socket.socket(); _s.bind(("127.0.0.1", 0)); PORT = _s.getsockname()[1]; _s.close()
threading.Thread(target=lambda: S.serve(host="127.0.0.1", port=PORT, warm_browser=False), daemon=True).start()
BASE = "http://127.0.0.1:%d" % PORT
def get(path):
    try:
        r = urllib.request.urlopen(BASE + path, timeout=20)
        return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, b""
for _ in range(80):
    try: urllib.request.urlopen(BASE + "/api/config", timeout=5); break
    except Exception: time.sleep(0.5)
else: raise SystemExit("server never came up")

code, hdr, body = get(recs[0]["url"])
ok("the attachment is served", code == 200 and body == PNG, (code, len(body)))
ok("...as its own type", (hdr.get("Content-Type") or "").startswith("image/png"), hdr.get("Content-Type"))
ok("...and a picture is drawn inline", (hdr.get("Content-Disposition") or "").startswith("inline"), hdr.get("Content-Disposition"))
code, hdr, _ = get(recs[1]["url"])
ok("anything else downloads under its own name",
   code == 200 and (hdr.get("Content-Disposition") or "").startswith("attachment"), hdr.get("Content-Disposition"))
ok("a path out of the folder is not a route", get("/api/upload/room-x/../../settings.json")[0] == 404)
ok("another chat's folder is not readable", get("/api/upload/room-y/" + os.path.basename(recs[0]["path"]))[0] == 404)
hist = json.loads(urllib.request.urlopen(BASE + "/api/history?session=attach-room", timeout=20).read())
ok("history hands the message back with its attachments",
   (hist.get("messages") or [{}])[0].get("attachments", [{}])[0].get("url") == recs[0]["url"], hist)

print("--- a message sent with a file carries it all the way to the turn ---")
# The turn runs for real — only the model is replaced, so what is under test is the wiring from the
# request body to the files on disk and to the transcript.
seen = {}
def fake_stream(model, msgs, tools=None, max_tokens=None, attempts=None):
    seen["msgs"] = msgs
    yield ("done", {"content": "Read it.", "tool_calls": [], "usage": None})
S.chat_stream = fake_stream
req = urllib.request.Request(BASE + "/api/chat", method="POST", headers={"Content-Type": "application/json"},
    data=json.dumps({"session": "attach-room2", "bot": "producer", "text": "read this",
                     "attachments": [{"name": "sent.txt", "type": "text/plain",
                                      "data": "data:text/plain;base64," + base64.b64encode(b"payload").decode()}]}).encode())
urllib.request.urlopen(req, timeout=60).read()
h2 = json.loads(urllib.request.urlopen(BASE + "/api/history?session=attach-room2", timeout=20).read())
rec2 = [m for m in h2.get("messages") or [] if m.get("role") == "user"]
ok("the transcript keeps the file", bool(rec2) and rec2[0]["attachments"][0]["name"] == "sent.txt", rec2)
ok("...which is on disk with the right bytes",
   bool(rec2) and open(rec2[0]["attachments"][0]["path"], "rb").read() == b"payload", rec2)
ok("the bot is told the path it can open",
   bool(rec2) and any(rec2[0]["attachments"][0]["path"] in str(m.get("content")) for m in seen.get("msgs") or []),
   seen.get("msgs"))

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
