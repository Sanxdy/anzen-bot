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
# The sandbox sits beside the data dir, as it does in a real install: `_in_sandbox` refuses anything
# inside the data dir, so a sandbox nested under it would refuse its own attachments.
os.environ.update(DATA_DIR=os.path.join(TMP, "data"), SANDBOX_DIR=os.path.join(TMP, "sandbox"))
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
    # One message, one name, two files: both land in the same millisecond, so a stamped name alone
    # is not unique — the second must not overwrite the first.
    {"name": "dup.txt", "type": "text/plain", "data": data_url(b"one", "text/plain")},
    {"name": "dup.txt", "type": "text/plain", "data": data_url(b"two", "text/plain")},
])
ok("the usable files are kept, the oversize and the malformed dropped", len(recs) == 4, recs)
ok("two files with one name in one message are two files on disk",
   recs[2]["path"] != recs[3]["path"]
   and open(recs[2]["path"], "rb").read() == b"one" and open(recs[3]["path"], "rb").read() == b"two", recs)
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

print("--- a bot sends a file to the chat ---")
# The complaint this answers: "no bot can send any media to the chat". `send_file` copies what the bot
# made into the chat's upload folder and returns the record the page already draws, so a picture, a
# video, a PDF and an archive all take one path — and the copy is what makes it survive a reload.
S.set_work_dir(REPO); S._WORK.uploads = os.path.dirname(recs[0]["path"])
VID = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200
open(os.path.join(REPO, "clip.mp4"), "wb").write(VID)
att, why = S._send_file("clip.mp4")
ok("the file is copied into the chat's upload folder",
   bool(att) and os.path.dirname(att["path"]) == os.path.dirname(recs[0]["path"]) and why == "", (att, why))
ok("...with its bytes", bool(att) and open(att["path"], "rb").read() == VID)
ok("...a video type and a url the page plays it from",
   bool(att) and att["type"] == "video/mp4" and att["url"].startswith("/api/upload/"), att)
ok("...and the original is still where the bot left it", os.path.isfile(os.path.join(REPO, "clip.mp4")))
ok("the reader's name can be changed", S._send_file("clip.mp4", "the take.mp4")[0]["name"] == "the take.mp4")
ok("a path outside the working folder is refused", S._send_file("/etc/hosts")[0] is None)
ok("a file that is not there is refused", S._send_file("nope.bin")[0] is None)
big = os.path.join(REPO, "huge.bin")
with open(big, "wb") as f: f.truncate(S.MAX_UPLOAD + 1)
ok("a file over the message cap is refused", S._send_file("huge.bin")[0] is None)
res, extra = S.exec_tool("b", "send_file", {"path": "clip.mp4"})
ok("the tool returns a `file` event carrying the record",
   bool(extra) and extra[0]["type"] == "file" and extra[0]["att"]["name"] == "clip.mp4", (res, extra))
ok("...and tells the bot what it sent", "clip.mp4" in res, res)
sent = extra[0]["att"] if extra else {}

print("--- the transcript keeps them, so a reopened chat draws them back ---")
msg = S._user_message("here it is", None, False, None, recs)
ok("the record carries the attachments", msg["attachments"] == recs)
ok("a message with none carries no empty list", "attachments" not in S._user_message("hi", None, False))
S.new_session("attach-room", bot="b")
st = S.load("attach-room"); st["messages"].append(msg); S.save("attach-room", st)
ok("...and they survive the store", S.load("attach-room")["messages"][0]["attachments"][0]["name"] == "shot.png")

print("--- clearing or deleting a chat takes its files with it ---")
# The UI promises that clearing a chat starts it over, and a deleted bot leaves nothing behind. The
# attachments are files on disk, so the promise only holds if the folder goes with the transcript.
S._save_uploads("gone-room", [{"name": "a.txt", "type": "text/plain", "data": data_url(b"a", "text/plain")}])
S.new_session("gone-room")
ok("the chat's files are on disk", os.path.isdir(S._upload_folder("gone-room")))
S.clear_chat("gone-room")
ok("clearing a chat removes its folder", not os.path.exists(S._upload_folder("gone-room")))
S._save_uploads("dead-room", [{"name": "b.txt", "type": "text/plain", "data": data_url(b"b", "text/plain")}])
S.new_session("dead-room")
S.drop_session("dead-room")
ok("deleting a chat removes its folder", not os.path.exists(S._upload_folder("dead-room")))
# One folder per chat is what makes this safe: a room's copy of a file and the member chat's copy are
# two folders, so deleting the member's chat cannot take the room's copy with it.
S._save_uploads("kept-room", [{"name": "c.txt", "type": "text/plain", "data": data_url(b"c", "text/plain")}])
S._save_uploads("kept-room/sub", [{"name": "d.txt", "type": "text/plain", "data": data_url(b"d", "text/plain")}])
S.new_session("kept-room"); S.new_session("kept-room/sub")
S.drop_session("sub", "bot")
ok("deleting a member's chat leaves the room's own files alone",
   os.path.isdir(S._upload_folder("kept-room")) and not os.path.exists(S._upload_folder("kept-room/sub")))

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
# The browser's own player asks for a byte range before it will play a clip.
_r = urllib.request.Request(BASE + sent["url"], headers={"Range": "bytes=0-3"})
with urllib.request.urlopen(_r, timeout=20) as _resp:
    ok("a byte range is answered with just those bytes",
       _resp.status == 206 and _resp.read() == VID[:4] and _resp.headers.get("Content-Range") == "bytes 0-3/%d" % len(VID),
       (_resp.status, _resp.headers.get("Content-Range")))
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

print("--- a bot that sends a file leaves it in the chat ---")
# The whole path, not just the tool: a real turn, only the model replaced. What is under test is that
# the file the bot sent is a message in the transcript — so it is still there after a reload.
S.set_work_dir(None)
open(os.path.join(S.bot_field_dir("producer"), "report.pdf"), "wb").write(b"%PDF-1.4 fake")
def fake_send(model, msgs, tools=None, max_tokens=None, attempts=None):
    if any(m.get("role") == "tool" for m in msgs):
        yield ("done", {"content": "Sent it.", "tool_calls": [], "usage": None}); return
    yield ("done", {"content": "", "tool_calls": [{"id": "c1", "function": {
        "name": "send_file", "arguments": json.dumps({"path": "report.pdf", "name": "Q3 report.pdf"})}}],
        "usage": None})
S.chat_stream = fake_send
req = urllib.request.Request(BASE + "/api/chat", method="POST", headers={"Content-Type": "application/json"},
    data=json.dumps({"session": "attach-send", "bot": "producer", "text": "send me the report"}).encode())
urllib.request.urlopen(req, timeout=60).read()
h3 = json.loads(urllib.request.urlopen(BASE + "/api/history?session=attach-send", timeout=20).read())
got = [m for m in h3.get("messages") or [] if m.get("attachments")]
ok("the chat keeps the file the bot sent", bool(got) and got[0]["attachments"][0]["name"] == "Q3 report.pdf", h3)
ok("...as a message from the bot", bool(got) and got[0]["role"] == "assistant" and got[0].get("who"), got)
ok("...and the file is on disk in the chat's upload folder",
   bool(got) and os.path.isfile(got[0]["attachments"][0]["path"])
   and os.path.dirname(got[0]["attachments"][0]["path"]) == S._upload_folder("attach-send"), got)

print("--- a file sent in a room lands in the room ---")
# In a room, the steps stay in the member's chat but what a bot *sends* is a message to the room —
# someone asked for it. The member's own chat keeps its copy too, as its record.
room = {"id": "attach-room-r", "name": "Attach", "members": ["producer"], "lead": "producer", "mode": "lead"}
S.new_session("attach-room-r", title="Attach")
def fake_agent(sid, bid, task, ctx, out, bs, settings, images=None):
    out["text"] = "Here it is."
    yield {"type": "agent", "id": bid, "name": "Producer", "state": "start"}
    yield {"type": "file", "agent": bid, "att": sent}
    yield {"type": "agent", "id": bid, "name": "Producer", "state": "done"}
_real = S.run_agent; S.run_agent = fake_agent
list(S._channel_turn("attach-room-r", "send me the clip", room, S.load_bots(), {}, raw="send me the clip", jobs=[]))
S.run_agent = _real
rows = S.load("attach-room-r")["messages"]
ok("the room keeps the file as a message", any(r.get("attachments") for r in rows), rows)
ok("...and the member's own chat keeps its copy",
   any(r.get("attachments") for r in S.load("attach-room-r/producer")["messages"]))

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
