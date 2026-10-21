#!/usr/bin/env python3
"""The Lucent bridge, against a fake Lucent.

Token-only and off the turn path, so this drives the module's own functions directly: one
fake HTTP server records every request, and the checks read that record rather than trusting
the module's own state.

Run: python3 tests/test_lucent.py
"""
import json, os, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  ok   " if ok else "  FAIL ") + name + ("" if ok else "  <- " + str(detail)[:300]))


# ---------------------------------------------------------------- the fake
class Fake:
    requests = []
    bootstrap = {"members": [], "teams": [], "projects": []}
    todo = []                 # what GET /api/tasks answers
    fail_tasks = False
    n = 0

    @classmethod
    def record(cls, method, path, body, auth):
        cls.requests.append({"method": method, "path": path, "body": body, "auth": auth})

    @classmethod
    def count(cls, method, prefix):
        return sum(1 for r in cls.requests if r["method"] == method and r["path"].startswith(prefix))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, obj=None):
        body = json.dumps(obj).encode() if obj is not None else b""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try: return json.loads(raw) if raw else None
        except Exception: return None

    def _auth(self):
        return self.headers.get("Authorization")

    def do_GET(self):
        p = urlparse(self.path); Fake.record("GET", self.path, None, self._auth())
        if p.path == "/api/auth/me": return self._send(200, {"user": {"id": "u-admin"}})
        if p.path == "/api/bootstrap": return self._send(200, Fake.bootstrap)
        if p.path == "/api/tasks":
            who = (parse_qs(p.query).get("assignee") or [""])[0]
            return self._send(200, {"tasks": [t for t in Fake.todo if t["assignee_id"] == who]})
        return self._send(404, {"error": "no such route"})

    def do_POST(self):
        p = urlparse(self.path); b = self._body(); Fake.record("POST", p.path, b, self._auth())
        if p.path == "/api/auth/register": return self._send(201, {"ok": True})
        if p.path == "/api/auth/token":
            return self._send(201, {"token": "tok-" + (b or {}).get("email", "x"),
                                    "user_id": "u-admin", "expires_at": "2099-01-01"})
        if p.path == "/api/teams": return self._send(201, {"id": "team-" + b["name"], "name": b["name"]})
        if p.path == "/api/members":
            return self._send(201, {"id": "u-" + b["email"].split("@")[0], "temporary_password": "temp-pw"})
        if p.path == "/api/projects": return self._send(201, {"id": "p-" + b["name"].lower()})
        if p.path == "/api/profile/avatar": return self._send(201, {"ok": True})
        if p.path == "/api/tasks":
            if Fake.fail_tasks: return self._send(500, {"error": "boom"})
            Fake.n += 1
            return self._send(201, {"id": "t-%d" % Fake.n})
        if p.path.endswith("/comments"): return self._send(201, {"id": "c-1"})
        return self._send(404, {"error": "no such route"})

    def do_PATCH(self):
        p = urlparse(self.path); b = self._body(); Fake.record("PATCH", p.path, b, self._auth())
        if p.path == "/api/profile": return self._send(200, {"ok": True})
        if p.path.startswith("/api/tasks/"): return self._send(200, {"ok": True})
        return self._send(404, {"error": "no such route"})

    def do_DELETE(self):
        p = urlparse(self.path); Fake.record("DELETE", p.path, None, self._auth())
        return self._send(200, {"ok": True})


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d" % srv.server_address[1]

    data = tempfile.mkdtemp()
    faces = os.path.join(data, "faces"); os.makedirs(faces)
    presets = os.path.join(data, "presets"); os.makedirs(os.path.join(presets, "cat"))
    avatars = os.path.join(data, "avatars"); os.makedirs(avatars)
    # a picture with WebP's magic bytes; the fake does not look at it
    open(os.path.join(presets, "cat", "base.webp"), "wb").write(b"RIFF\x00\x00\x00\x00WEBP" + b"x" * 200)

    bots = [
        {"id": "producer", "name": "Producer", "title": "Chief of Staff", "preset": ""},
        {"id": "builder", "name": "Builder", "title": "Engineering", "preset": "cat"},
        {"id": "loner", "name": "Loner", "title": "Odd Jobs", "preset": ""},
        {"id": "guest", "name": "Guest", "title": "Engineer", "preset": "", "lucent_team": "Platform"},
    ]
    chans = [{"id": "company", "name": "Company", "members": ["producer", "builder"]}]

    def save_channels(c):
        chans[:] = c

    turns = []
    during = []               # whether the pickup flag was set while the turn ran

    def run_turn(sid, text, bs, settings, channel=None, solo=None, who=None):
        turns.append({"sid": sid, "text": text, "solo": solo, "who": who})
        during.append(getattr(lucent._PICKUP, "on", False))
        lucent.on_work("company", solo or "x", "this must not become a second task")
        yield {"type": "status", "state": "thinking"}
        yield {"type": "final", "text": "Built it. Tests pass."}

    os.environ["LUCENT_URL"] = url
    os.environ["LUCENT_EMAIL"] = "anzen@bots.anzen.local"
    os.environ["LUCENT_PASSWORD"] = "pw"
    import lucent
    lucent.POLL = 1
    lucent.configure(data, faces, presets, avatars, lambda: bots, lambda: chans, save_channels,
                     lambda: {}, run_turn)
    lucent._URL = url

    # --- no cookie is ever read or written ------------------------------------------------
    check("no request carries a Cookie header",
          not any("Cookie" in r["path"] for r in Fake.requests))

    # --- accounts -------------------------------------------------------------------------
    a = lucent._admin()
    check("admin token minted from credentials", a and a.get("token"), a)
    boot = lucent._bootstrap(a)
    check("bootstrap read", boot is not None)
    lucent._provision(a, boot)

    st = lucent._state()
    check("a member was created per bot", len(st["bots"]) == 4, st["bots"])
    check("member id recorded", st["bots"]["builder"].get("user_id") == "u-builder", st["bots"]["builder"])
    check("bot token recorded", st["bots"]["builder"].get("token"), st["bots"]["builder"])
    # A team groups people. The title is one per bot, so it cannot be the team: bots in a room
    # share that room's team, and only a bot in no room falls back to its title.
    check("bots in a room share one team", lucent._team(bots[0]) == lucent._team(bots[1]) == "Company",
          [lucent._team(b) for b in bots])
    check("a bot in no room keeps its title", lucent._team(bots[2]) == "Odd Jobs")
    check("lucent_team overrides the room", lucent._team(bots[3]) == "Platform")
    check("one team per room, not per bot", Fake.count("POST", "/api/teams") == 3,
          [r["body"] for r in Fake.requests if r["path"] == "/api/teams"])
    check("the member carries the room's team",
          [r["body"] for r in Fake.requests if r["path"] == "/api/members"
           and r["body"]["email"] == "builder@bots.anzen.local"][0]["team"] == "Company")

    # A bot that moved out of a title-team leaves it empty behind; an empty team nobody is in
    # is clutter, so it goes. A team with people in it, or Lucent's own, is left alone.
    Fake.bootstrap["teams"] = [{"id": "t-old", "name": "Chief of Staff"},
                               {"id": "t-seed", "name": "Engineering"},
                               {"id": "t-full", "name": "Odd Jobs"}]
    Fake.bootstrap["members"] = [{"id": "u-x", "email": "x@y.z", "team": "Odd Jobs"}]
    Fake.requests.clear()
    lucent._prune_teams(a, Fake.bootstrap)
    gone = [r["path"] for r in Fake.requests if r["method"] == "DELETE"]
    check("an empty team the bridge made is removed", gone == ["/api/teams/t-old"], gone)
    check("a team with people in it stays", "/api/teams/t-full" not in gone, gone)
    check("Lucent's own team stays", "/api/teams/t-seed" not in gone, gone)
    Fake.bootstrap["teams"] = []; Fake.bootstrap["members"] = []
    check("every call is a Bearer call",
          all((r["auth"] or "").startswith("Bearer ") for r in Fake.requests if r["path"] != "/api/auth/token"))

    # --- profile and face -----------------------------------------------------------------
    lucent._sync_profiles()
    patches = [r for r in Fake.requests if r["method"] == "PATCH" and r["path"] == "/api/profile"
               and r["body"]["email"] == "builder@bots.anzen.local"]
    check("profile carries name, role and team", patches and patches[0]["body"]["team"] == "Company",
          patches[:1])
    check("the face was uploaded once", Fake.count("POST", "/api/profile/avatar") == 1, Fake.requests)
    before = Fake.count("POST", "/api/profile/avatar")
    lucent._sync_profiles()
    check("an unchanged face is not uploaded again", Fake.count("POST", "/api/profile/avatar") == before)

    # --- projects -------------------------------------------------------------------------
    lucent._sync_projects(a, boot)
    check("one project per room", st["projects"].get("company") == "p-company", st["projects"])
    check("the room records its project", chans[0].get("lucent_project") == "p-company", chans[0])

    # --- a bot turn becomes a task, the report closes it -----------------------------------
    long = ("Write the parser for the invoice feed. Then test it against the March export and "
            "post the numbers to the finance room before Friday.")
    lucent.on_work("company", "builder", long)
    lucent._handle(lucent._Q.get_nowait())
    created = [r for r in Fake.requests if r["method"] == "POST" and r["path"] == "/api/tasks"]
    check("the delegation filed one task", len(created) == 1, created)
    check("the task is in the room's project and running",
          created and created[0]["body"]["project_id"] == "p-company"
          and created[0]["body"]["status"] == "in_progress", created[:1])
    check("filed with the delegate's own token",
          created and created[0]["auth"] == "Bearer tok-builder@bots.anzen.local", created[:1])
    check("the title is a short summary of the request",
          created and created[0]["body"]["title"] == "Write the parser for the invoice feed", created[:1])
    check("...and the description keeps the request whole",
          created and created[0]["body"]["description"] == long, created[:1])

    # A title is a label, never a paragraph: cut at a word boundary, capped at TITLE_MAX, and
    # something rather than nothing when the request has no words at all.
    check("a long title is cut at a word",
          len(lucent._short("alpha " * 30)) <= lucent.TITLE_MAX
          and lucent._short("alpha " * 30).endswith("alpha"), lucent._short("alpha " * 30))
    check("a title with no spaces is cut hard", lucent._short("x" * 200) == "x" * lucent.TITLE_MAX)
    check("an empty title still labels something", lucent._short("   ") == "Task")
    check("a summary is the first sentence", lucent._summary("Do the thing. Then more.") == "Do the thing")
    check("a one-sentence request is summarised whole", lucent._summary("short job") == "short job")

    # The board brief rides in the bot's prompt — except on a turn that already is a task.
    check("the prompt carries the board rules", "%d" % lucent.TITLE_MAX in lucent.brief()
          and "due_date" in lucent.brief(), lucent.brief())
    lucent._PICKUP.on = True
    check("a picked-up task is not told to file one", lucent.brief() == "")
    lucent._PICKUP.on = False

    lucent.on_report("company", "builder", "Done, tests pass.")
    lucent._handle(lucent._Q.get_nowait())
    check("the report became a comment", Fake.count("POST", "/api/tasks/t-1/comments") == 1, Fake.requests)
    check("the task was closed",
          any(r["method"] == "PATCH" and r["path"] == "/api/tasks/t-1"
              and r["body"].get("status") == "done" for r in Fake.requests))

    # A chat with one bot outside any room is work too, so it is a task — with no project,
    # because there is no room to map one from.
    Fake.requests.clear()
    lucent.on_work("chat", "loner", "answer the phone")
    lucent._handle(lucent._Q.get_nowait())
    created = [r for r in Fake.requests if r["method"] == "POST" and r["path"] == "/api/tasks"]
    check("a 1:1 chat files a task as well", len(created) == 1, created)
    check("...with no project when the bot is in no room",
          created and "project_id" not in created[0]["body"], created[:1])

    # --- a task created in Lucent runs a turn ---------------------------------------------
    Fake.todo = [{"id": "h-1", "title": "Rename the files", "description": "by date",
                  "assignee_id": "u-builder", "created_by": "u-maya"}]
    lucent._pickup()
    check("one turn ran for the task", len(turns) == 1, turns)
    check("the turn ran as the bot in its room", turns and turns[0]["sid"] == "company/builder"
          and turns[0]["solo"] == "builder", turns[:1])
    check("a task-started turn does not file a second task",
          during == [True] and lucent._Q.empty(), (during, lucent._Q.qsize()))
    check("the turn's report was commented back",
          Fake.count("POST", "/api/tasks/h-1/comments") == 1, Fake.requests)
    check("the picked-up task was closed",
          any(r["method"] == "PATCH" and r["path"] == "/api/tasks/h-1"
              and r["body"].get("status") == "done" for r in Fake.requests))
    lucent._pickup()
    check("a second sweep does not run it again", len(turns) == 1, turns)

    # --- its own task is not picked up ----------------------------------------------------
    Fake.todo = [{"id": "h-2", "title": "mine", "description": "", "assignee_id": "u-builder",
                  "created_by": "u-builder"}]
    lucent._pickup()
    check("a task the bot filed itself is not picked up", len(turns) == 1, turns)

    # --- failures are recorded, not raised ------------------------------------------------
    Fake.fail_tasks = True
    lucent.on_work("company", "builder", "this one fails")
    try:
        lucent._handle(lucent._Q.get_nowait())
        raised = False
    except Exception:
        raised = True
    check("a Lucent 500 does not raise", not raised)
    check("...and lands in last_error", "boom" in lucent.status()["last_error"], lucent.status())
    Fake.fail_tasks = False

    # --- the bot's tool -------------------------------------------------------------------
    Fake.requests.clear()
    out = lucent.api_tool("builder", "GET", "tasks?assignee=me", None)
    check("a member route is called", Fake.count("GET", "/api/tasks") == 1 and "tasks" in out, out)
    Fake.requests.clear()
    out = lucent.api_tool("builder", "POST", "/api/members", {"name": "x"})
    check("workspace management is refused", Fake.requests == [] and "not open" in out, out)
    out = lucent.api_tool("builder", "GET", "/api/reset", None)
    check("reset is refused", "not open" in out, out)
    # A bot that writes its whole request into a title has it cut here, so the board stays a
    # list of labels whatever the model sends.
    Fake.requests.clear()
    lucent.api_tool("builder", "POST", "/api/tasks", {"title": "y" * 200, "description": "the request"})
    posted = [r for r in Fake.requests if r["path"] == "/api/tasks" and r["method"] == "POST"]
    check("a title written by the bot is clamped too",
          posted and len(posted[0]["body"]["title"]) <= lucent.TITLE_MAX
          and posted[0]["body"]["description"] == "the request", posted[:1])

    # --- the fixed workspace --------------------------------------------------------------
    # With no address anywhere, bot work still has somewhere to go: the team's own Lucent.
    os.environ.pop("LUCENT_URL", None)
    st["url"] = ""
    lucent._STARTED = True                        # set the address without spawning the threads
    lucent.start()
    check("with no address configured the bridge uses the fixed workspace",
          lucent._URL == lucent.DEFAULT_URL == "https://lucent.vortex-freq.web.id", lucent._URL)
    lucent._URL = url; lucent._STARTED = False
    st["url"] = url; lucent._save()

    # --- Settings → Lucent ----------------------------------------------------------------
    # The desktop app has no environment to read, so the tab posts the admin login. It must
    # connect on the spot and leave no password behind.
    lucent.start = lambda: True                  # the threads are the ticker's job, not this test's
    bad = lucent.save_config("lucent.example.com", "a@b.c", "pw")
    check("a URL without a scheme is refused", not bad["ok"] and "http" in bad["error"], bad)
    os.environ.pop("LUCENT_EMAIL", None); os.environ.pop("LUCENT_PASSWORD", None)
    Fake.requests.clear()
    ok = lucent.save_config(url, "sandy@example.com", "secret-pw")
    check("the settings form connects at once", ok["ok"] and ok["on"], ok)
    check("...as the admin it was given",
          [r for r in Fake.requests if r["path"] == "/api/auth/token"][0]["body"]["email"] == "sandy@example.com",
          Fake.requests)
    check("...and the password is not written to disk",
          "password" not in lucent._state()["admin"] and "secret-pw" not in open(lucent._path()).read(),
          lucent._state()["admin"])
    check("...but the token is", bool(lucent._state()["admin"].get("token")))

    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
