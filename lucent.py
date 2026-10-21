"""The Lucent bridge: one Lucent project per room, one Lucent member per bot.

Token-only. Every request carries `Authorization: Bearer <token>`; no cookie is read or
written, no page is opened, and nothing here needs a person in the Lucent UI. Each bot has
its own Lucent account, so a task it files is assigned to it and a comment it writes is
signed by it.

Two directions:
  out  every bot turn — a room message, a delegation, a 1:1 chat, a routine — opens a task
       (in_progress, assigned to the bot, in its room's project) and the bot's report becomes
       a comment that closes it. Lucent is the record of what the team did, not only of what
       was delegated;
  in   a todo task assigned to a bot in Lucent runs a turn in its room, and the reply is
       commented back and the task marked done.

Config is `LUCENT_URL` plus optional `LUCENT_EMAIL`/`LUCENT_PASSWORD` of an existing admin,
or `data/lucent.json`, which this module owns and keeps at 0600. With neither, the bridge
points at `DEFAULT_URL` and Settings asks for the admin password once.
"""
import base64, json, os, queue, re, secrets, threading, time, urllib.error, urllib.request

POLL = 20                 # seconds between pickup sweeps
PROVISION_EVERY = 300     # seconds between member/team/project reconciliation
TIMEOUT = 20
ADMIN_EMAIL = "anzen@bots.anzen.local"
BOT_DOMAIN = "bots.anzen.local"
AVATAR_MAX = 300_000      # Lucent's own cap on a profile picture
DEFAULT_URL = "https://lucent.vortex-freq.web.id"   # Settings may point elsewhere; unset means here
TITLE_MAX = 60            # a board title is a label; the request itself is the description

# Told to a bot in the prompt of a turn the bridge filed a task for. The title and the dates are
# the bot's to fill: only it knows what the job turned out to be and how long it will take.
BRIEF = (
    "\n\nYour turn is a task on the team's Lucent board: it was filed when you started, in this "
    "room's project. Before you call `finish`, tidy it with `lucent_api`: GET "
    "/api/tasks?assignee=me&status=in_progress finds it (the one whose description is the request "
    "you were given), then PATCH /api/tasks/<id> with \"title\" — a summary of at most %d "
    "characters, because the description already holds the full request — \"due_date\" as "
    "YYYY-MM-DD, and \"estimate\" in hours. A task with no due date counts as late." % TITLE_MAX
)

DATA = ""
FACES_DIR = ""; PRESET_DIR = ""; AVATAR_DIR = ""
_BOTS = _CHANNELS = _SAVE_CHANNELS = _SETTINGS = _RUN_TURN = None

_URL = ""
_STATE = None
_READY = threading.Event()
_Q = queue.Queue()
_lock = threading.RLock()
_ERRS = 0                 # failures since boot, so a tick can tell whether it cleared one
_PW_ONCE = ""             # a password typed into Settings: used to mint once, never written
_STARTED = False
_PROV = 0                 # last time members, teams and projects were reconciled
_PICKUP = threading.local()   # set while a turn was started by a Lucent task, so it files no second one

# What a bot may reach through `lucent_api`. Everything Lucent offers a member, and nothing
# that manages the workspace itself: no auth, no members, no teams, no reset.
ALLOW = [
    ("GET", r"^/api/(tasks(\?.*)?|bootstrap|insights(\?.*)?|export\.csv|auth/me|avatars/[A-Za-z0-9-]+)$"),
    ("POST", r"^/api/(tasks|tasks/[^/]+/(subtasks|comments)|projects|events|focus|notifications/read|profile/avatar)$"),
    ("PATCH", r"^/api/(tasks/[^/]+|subtasks/[^/]+|projects/[^/]+|profile|settings)$"),
    ("DELETE", r"^/api/(tasks/[^/]+|subtasks/[^/]+|projects/[^/]+|events/[^/]+)$"),
]


def configure(data, faces, presets, avatars, bots, channels, save_channels, settings, run_turn):
    """Handed the server's own readers rather than importing it: server.py imports this file."""
    global DATA, FACES_DIR, PRESET_DIR, AVATAR_DIR
    global _BOTS, _CHANNELS, _SAVE_CHANNELS, _SETTINGS, _RUN_TURN
    DATA, FACES_DIR, PRESET_DIR, AVATAR_DIR = data, faces, presets, avatars
    _BOTS, _CHANNELS, _SAVE_CHANNELS, _SETTINGS, _RUN_TURN = bots, channels, save_channels, settings, run_turn


# ---------------------------------------------------------------- state
def _path():
    return os.path.join(DATA, "lucent.json")


def _state():
    global _STATE
    if _STATE is None:
        try:
            _STATE = json.load(open(_path()))
        except FileNotFoundError:
            _STATE = {}
        except Exception as e:
            print("lucent: could not read %s (%s); starting over" % (_path(), e), flush=True)
            _STATE = {}
        for k, v in (("url", ""), ("bots", {}), ("projects", {}), ("started", {}), ("open", {}),
                     ("teams", []), ("last_sync", 0), ("last_error", "")):
            _STATE.setdefault(k, v)
    return _STATE


def _save():
    with _lock:
        tmp = _path() + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(_STATE, f, indent=2)
        os.replace(tmp, _path())


def _fail(what):
    global _ERRS
    _ERRS += 1
    print("lucent:", what, flush=True)
    st = _state()
    st["last_error"] = str(what)[:300]
    try:
        _save()
    except Exception:
        pass


def status():
    st = _state()
    return {"url": _URL or st.get("url", ""), "on": bool(_URL),
            "email": (st.get("admin") or {}).get("email", ""),
            "bots": sum(1 for r in st["bots"].values() if r.get("token")),
            "faces": sum(1 for r in st["bots"].values() if r.get("face")),
            "projects": len(st["projects"]), "started": len(st["started"]),
            "last_sync": st.get("last_sync", 0), "last_error": st.get("last_error", "")}


# ---------------------------------------------------------------- http
def _call(method, path, body=None, token=None, timeout=TIMEOUT):
    """One request, as (status, json). Never raises: a Lucent that is down is a log line, not
    a dead turn."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(_URL.rstrip("/") + path, data=data, method=method)
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "AnzenBot/1.0")
    # Lucent's origin guard rejects a write with neither Origin nor Sec-Fetch-Site, and the
    # routes that mint the first token are writes. This header is the honest answer: the
    # bridge is a same-origin client, it just is not a browser.
    req.add_header("Origin", _URL.rstrip("/"))
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)[:200]}


# ---------------------------------------------------------------- accounts
def _admin():
    """The workspace admin this bridge acts as. Minted once and kept; minted again from the
    stored password only if the token stops being accepted (revoked)."""
    st = _state(); a = st.setdefault("admin", {})
    if a.get("token"):
        code, _ = _call("GET", "/api/auth/me", token=a["token"])
        if code == 200:
            return a
    email = (os.environ.get("LUCENT_EMAIL") or a.get("email") or ADMIN_EMAIL).strip().lower()
    pw = os.environ.get("LUCENT_PASSWORD") or a.get("password") or _PW_ONCE or ""
    if not pw:
        # Only the bridge's own account is created here. An admin's account cannot be: its
        # password was never stored, so a rejected token means it has to be typed in again.
        if email != ADMIN_EMAIL:
            _fail("Lucent no longer accepts the token for %s (revoked) — enter the admin password "
                  "in Settings → Lucent again" % email)
            return None
        # No credentials were supplied, so the bridge makes its own account. On an empty
        # workspace this registration is the admin; on an existing one it is a member, and
        # the caller has to supply an admin's email and password instead.
        pw = secrets.token_urlsafe(18)
        code, obj = _call("POST", "/api/auth/register",
                          {"name": "Anzen", "email": email, "password": pw})
        if code not in (201, 409):
            _fail("could not register %s (%s): %s — set LUCENT_EMAIL and LUCENT_PASSWORD"
                  % (email, code, obj.get("error") or ""))
            return None
        a["email"] = email; a["password"] = pw
    code, obj = _call("POST", "/api/auth/token",
                      {"email": email, "password": pw, "name": "anzen-bridge"})
    if code != 201 or not obj.get("token"):
        _fail("could not mint a token for %s (%s): %s" % (email, code, obj.get("error") or ""))
        return None
    a.update(token=obj["token"], user_id=obj.get("user_id", ""), email=email)
    # Only a password the bridge must keep is kept: one it invented, to be able to mint again.
    # An admin's own — from the environment or typed into Settings — is used once and dropped.
    if not os.environ.get("LUCENT_PASSWORD") and not _PW_ONCE:
        a["password"] = pw
    _save()
    return a

def save_config(url, email, password):
    """Settings → Lucent. Connects on the spot: the password is used to mint a token here and
    is not written to disk, so the file never holds an admin's secret."""
    global _URL, _PW_ONCE
    url = (url or DEFAULT_URL).strip().rstrip("/")
    if not re.match(r"^https?://[^\s/]+", url):
        return {"ok": False, "error": "Enter the Lucent address, starting with http:// or https://."}
    st = _state(); a = st.setdefault("admin", {})
    st["url"] = url
    a.pop("token", None)                       # a new address or account means a new token
    if email: a["email"] = email.strip().lower()
    _URL = url
    _save()
    _PW_ONCE = (password or "").strip()
    try:
        got = _admin()
        if got:
            _reconcile()                     # so the answer carries real counts, not zeros
    finally:
        _PW_ONCE = ""
    start()
    if not got:
        return {"ok": False, "error": st.get("last_error") or "could not reach Lucent", **status()}
    return {"ok": True, **status()}


def _bot_token(rec, email):
    if rec.get("token"):
        code, _ = _call("GET", "/api/auth/me", token=rec["token"])
        if code == 200:
            return rec["token"]
    if not rec.get("password"):
        return ""
    code, obj = _call("POST", "/api/auth/token",
                      {"email": email, "password": rec["password"], "name": "anzen-bot"})
    if code == 201 and obj.get("token"):
        rec["token"] = obj["token"]
        return rec["token"]
    return ""


def _title(b):
    return ((b.get("title") or b.get("role") or "Teammate").strip() or "Teammate")[:40]


def _team(b):
    """A team groups people, so it cannot be the title: one team per title gave eighteen teams
    of one. A bot's work is the room it works in, so that is its team — the first room that
    lists it. `lucent_team` on the bot record overrides it, for a bot that belongs elsewhere."""
    own = str(b.get("lucent_team") or "").strip()
    if own:
        return own[:40]
    for ch in _CHANNELS():
        if b.get("id") in (ch.get("members") or []):
            return ((ch.get("name") or ch.get("id") or "Teammate").strip() or "Teammate")[:40]
    return _title(b)


def _provision(a, boot):
    """Every bot is a Lucent member: its name is its name, its title is its role, and its team
    is the room it works in. A team that does not exist yet is created, which is what makes a
    new room work without anyone opening Lucent."""
    st = _state()
    members = {(m.get("email") or "").lower(): m for m in boot.get("members") or []}
    teams = {(t.get("name") or "").lower() for t in boot.get("teams") or []}
    for b in _BOTS():
        bid = b["id"]; title = _title(b); team = _team(b)
        email = "%s@%s" % (bid, BOT_DOMAIN)
        rec = st["bots"].setdefault(bid, {})
        rec["email"] = email; rec["title"] = title; rec["team"] = team
        if team.lower() not in teams:
            code, obj = _call("POST", "/api/teams", {"name": team}, token=a["token"])
            if code in (201, 409):
                teams.add(team.lower())
                if team not in st["teams"]: st["teams"].append(team)
            else:
                _fail("could not add team %r (%s): %s" % (team, code, obj.get("error") or ""))
        m = members.get(email)
        if m:
            rec["user_id"] = m["id"]
        else:
            code, obj = _call("POST", "/api/members",
                              {"name": b.get("name") or bid, "email": email,
                               "role": title, "team": team}, token=a["token"])
            if code == 201 and obj.get("id"):
                rec["user_id"] = obj["id"]
                rec["password"] = obj.get("temporary_password") or ""
                members[email] = {"id": obj["id"]}
            else:
                _fail("could not add %s (%s): %s" % (bid, code, obj.get("error") or ""))
                continue
        tok = _bot_token(rec, email)
        if not tok:
            _fail("no Lucent token for %s — its account exists but its password is not in this "
                  "state file; delete %s in Lucent's Team page and it will be recreated" % (bid, email))
    _prune_teams(a, boot)
    _save()


def _prune_teams(a, boot):
    """A bot that moves leaves its old team behind, and a team with nobody in it is clutter.
    Only empty ones are removed, and only ones this bridge made: a team named after a bot's
    old title, or one it created. Lucent's own seed teams are never touched."""
    st = _state()
    used = {_team(b).lower() for b in _BOTS()}
    member_teams = {(m.get("team") or "").lower() for m in boot.get("members") or []}
    mine = {t.lower() for t in st.get("teams") or []} | {_title(b).lower() for b in _BOTS()}
    seed = {"product", "design", "engineering", "marketing", "operations"}
    for t in boot.get("teams") or []:
        name = (t.get("name") or "").lower()
        if not name or name in used or name in member_teams or name in seed or name not in mine:
            continue
        code, obj = _call("DELETE", "/api/teams/%s" % t["id"], token=a["token"])
        if code == 200:
            print("lucent: removed the empty team %r" % t["name"], flush=True)
        elif code != 400:                  # 400 = it still has people; not ours to force
            _fail("could not remove the empty team %r (%s): %s" % (t["name"], code, obj.get("error") or ""))


def _face_file(b):
    if b.get("preset"):
        return os.path.join(PRESET_DIR, b["preset"], "base.webp")
    if b.get("genface"):
        return os.path.join(FACES_DIR, b["genface"])
    for ext in (".webp", ".png", ".jpg", ".jpeg"):
        p = os.path.join(AVATAR_DIR, "%s%s" % (b["id"], ext))
        if os.path.isfile(p):
            return p
    return ""


def _sync_profiles():
    """Name, role and team on every bot's Lucent account, and its face as the profile
    picture. Both are only sent when they changed, so a steady tick is a no-op."""
    st = _state()
    for b in _BOTS():
        rec = st["bots"].get(b["id"]) or {}
        tok = rec.get("token")
        if not tok:
            continue
        title = _title(b); team = _team(b)
        want = "%s|%s|%s" % (b.get("name") or b["id"], title, team)
        if rec.get("profile") != want:
            code, obj = _call("PATCH", "/api/profile",
                              {"name": b.get("name") or b["id"], "email": rec.get("email", ""),
                               "role": title, "team": team}, token=tok)
            if code == 200:
                rec["profile"] = want
            else:
                _fail("profile for %s (%s): %s" % (b["id"], code, obj.get("error") or ""))
        path = _face_file(b)
        fp = path or ""
        if not path or rec.get("face") == fp:
            continue
        ext = os.path.splitext(path)[1].lower()
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp"}.get(ext)
        if not mime:
            continue
        try:
            raw = open(path, "rb").read()
        except OSError as e:
            _fail("could not read the face for %s (%s)" % (b["id"], e))
            continue
        if len(raw) > AVATAR_MAX:
            _fail("the face for %s is %d KB, over Lucent's 300 KB cap" % (b["id"], len(raw) // 1000))
            rec["face"] = fp          # do not retry a picture that cannot be sent
            continue
        code, obj = _call("POST", "/api/profile/avatar",
                          {"data_url": "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode())},
                          token=tok)
        if code == 201:
            rec["face"] = fp
        else:
            _fail("avatar for %s (%s): %s" % (b["id"], code, obj.get("error") or ""))
    _save()


def _sync_projects(a, boot):
    """One Lucent project per room, matched by name, and the id written onto the room so the
    mapping survives a restart. Rooms keep unknown keys, so anzen needs no schema change."""
    st = _state()
    known = {p.get("id") for p in boot.get("projects") or []}
    by_name = {(p.get("name") or "").lower(): p.get("id") for p in boot.get("projects") or []}
    chs = _CHANNELS(); changed = False
    for ch in chs:
        pid = st["projects"].get(ch["id"])
        if pid not in known:
            pid = by_name.get((ch.get("name") or "").lower())
        if not pid:
            code, obj = _call("POST", "/api/projects",
                              {"name": ch.get("name") or ch["id"],
                               "description": "anzen-bot room %s" % ch["id"],
                               "status": "active", "lead_id": a.get("user_id") or None},
                              token=a["token"])
            if code == 201:
                pid = obj.get("id")
            else:
                _fail("could not add project %r (%s): %s" % (ch.get("name"), code, obj.get("error") or ""))
        if pid:
            st["projects"][ch["id"]] = pid
            if ch.get("lucent_project") != pid:
                ch["lucent_project"] = pid; changed = True
    if changed:
        _SAVE_CHANNELS(chs)
    _save()


# ---------------------------------------------------------------- out of a room
def _short(text):
    """A title is a label on a board, not the request: one line, at most TITLE_MAX, cut at a word
    so it never ends mid-word. The full request lives in the description."""
    s = " ".join((text or "").split())
    if len(s) > TITLE_MAX:
        cut = s[:TITLE_MAX]
        s = cut[:cut.rfind(" ")] if " " in cut else cut
    return s.rstrip(" ,.;:-") or "Task"


def _summary(text):
    """The first sentence of a request, short enough to be its title."""
    line = " ".join((text or "").split())
    for sep in (". ", "? ", "! ", "; "):
        i = line.find(sep)
        if 0 < i <= TITLE_MAX:
            return _short(line[:i])
    return _short(line)


def brief():
    """The board instructions for a bot's prompt — empty for a turn that already is a task, so a
    picked-up task is not described as one the bot has just filed."""
    if not _URL or getattr(_PICKUP, "on", False):
        return ""
    return BRIEF


def on_work(room, bot, text):
    """A bot is starting work. Every turn is a task on the board — a delegation, a message to a
    room, a chat with one bot, a routine — because that is what makes Lucent the record of what
    the team did. Queued, never sent from the turn's own thread: the turn must not wait on it."""
    if _URL and bot and (text or "").strip() and not getattr(_PICKUP, "on", False):
        _Q.put({"kind": "work", "room": room or "chat", "bot": bot, "task": text})


def on_report(room, bot, text):
    if _URL and bot and (text or "").strip():
        _Q.put({"kind": "report", "room": room or "chat", "bot": bot, "text": text})


def _handle(item):
    st = _state(); rec = st["bots"].get(item["bot"]) or {}
    tok = rec.get("token")
    if not tok:
        return
    key = "%s/%s" % (item["room"], item["bot"])
    if item["kind"] == "work":
        tid = st["open"].get(key)
        if tid:
            # The last turn on this key never reported — a crash or a model error — so its task is
            # still open. The new work goes in as a comment rather than orphaning it: a task left
            # in_progress for good is a lie on the board.
            code, _ = _call("POST", "/api/tasks/%s/comments" % tid,
                            {"body": item["task"][:2000]}, token=tok)
            if code < 400:
                return
            st["open"].pop(key, None)          # the task is gone from Lucent; file a fresh one
        body = {"title": _summary(item["task"]),
                "description": item["task"][:2000], "status": "in_progress"}
        pid = st["projects"].get(item["room"])
        if pid:
            body["project_id"] = pid
        code, obj = _call("POST", "/api/tasks", body, token=tok)
        if code == 201 and obj.get("id"):
            st["open"][key] = obj["id"]
            _save()
        else:
            _fail("could not file %s (%s): %s" % (item["bot"], code, obj.get("error") or ""))
        return
    tid = st["open"].pop(key, "")
    if not tid:
        return
    _call("POST", "/api/tasks/%s/comments" % tid, {"body": item["text"][:2000]}, token=tok)
    _call("PATCH", "/api/tasks/%s" % tid, {"status": "done"}, token=tok)
    _save()


def _worker():
    _READY.wait(120)                  # the first delegation may arrive before provisioning
    while True:
        try:
            _handle(_Q.get())
        except Exception as e:
            _fail("queue: %s" % e)


# ---------------------------------------------------------------- into a room
def _pickup():
    """A todo task assigned to a bot is a request to work. It runs in the room that owns the
    project, and its reply is the comment. Tasks the bridge itself filed are skipped: they are
    the mirror of work already running."""
    st = _state()
    now = time.time()
    for tid, at in list(st["started"].items()):
        if now - at > 7 * 86400:
            st["started"].pop(tid, None)
    rooms = {c["id"]: c for c in _CHANNELS()}
    for room, pid in list(st["projects"].items()):
        ch = rooms.get(room)
        if not ch:
            continue
        for bid in ch.get("members") or []:
            rec = st["bots"].get(bid) or {}
            tok, uid = rec.get("token"), rec.get("user_id")
            if not tok or not uid:
                continue
            code, obj = _call("GET", "/api/tasks?assignee=%s&status=todo&project_id=%s&limit=20"
                              % (uid, pid), token=tok)
            if code != 200:
                continue
            for t in obj.get("tasks") or []:
                if t.get("created_by") == uid or t["id"] in st["started"]:
                    continue
                st["started"][t["id"]] = now
                _save()
                _run_task(ch, bid, t, tok)


def _run_task(ch, bid, task, tok):
    _call("PATCH", "/api/tasks/%s" % task["id"], {"status": "in_progress"}, token=tok)
    text = ("Lucent task %s: %s\n\n%s\n\nDo the work, then reply with a short report. "
            "It is posted back to the task." % (task["id"], task.get("title") or "",
                                                task.get("description") or ""))
    final = ""
    _PICKUP.on = True                # this turn *is* a task already; filing another would double it
    try:
        for ev in _RUN_TURN("%s/%s" % (ch["id"], bid), text, _BOTS(), _SETTINGS(),
                            channel=ch, solo=bid, who="Lucent"):
            if ev.get("type") == "final":
                final = ev.get("text") or final
            elif ev.get("type") == "error":
                final = final or ("error: " + (ev.get("msg") or ""))
    except Exception as e:
        final = "error: %s" % e
    finally:
        _PICKUP.on = False
    if final:
        _call("POST", "/api/tasks/%s/comments" % task["id"], {"body": final[:2000]}, token=tok)
    _call("PATCH", "/api/tasks/%s" % task["id"], {"status": "done"}, token=tok)


# ---------------------------------------------------------------- the bot's own tool
def api_tool(bid, method, path, body):
    """`lucent_api` for one bot: the same routes a member has in the Lucent UI, called with
    that bot's own token so the board shows who did what."""
    st = _state(); rec = st["bots"].get(bid) or {}
    tok = rec.get("token")
    if not tok:
        return "(Lucent is not connected for this bot yet — the bridge is still setting it up)"
    method = (method or "GET").upper()
    p = (path or "").strip()
    if not p.startswith("/api/"):
        p = "/api/" + p.lstrip("/")
    if not any(m == method and re.match(rx, p) for m, rx in ALLOW):
        return "(that Lucent route is not open to bots: %s %s)" % (method, p)
    # A bot cannot put its whole request in a title: the board is a list of labels, so a long one
    # is cut here rather than left to fill the page. The description is where the detail belongs.
    if isinstance(body, dict) and isinstance(body.get("title"), str):
        body = {**body, "title": _short(body["title"])}
    code, obj = _call(method, p, body, token=tok)
    out = json.dumps(obj, ensure_ascii=False)[:6000]
    return out if code < 400 else "HTTP %d %s" % (code, out)


# ---------------------------------------------------------------- lifecycle
def start():
    global _URL, _STARTED
    st = _state()
    _URL = (os.environ.get("LUCENT_URL") or st.get("url") or DEFAULT_URL).strip().rstrip("/")
    st["url"] = _URL
    try:
        _save()
    except Exception as e:
        _fail("could not save %s (%s)" % (_path(), e))
        return False
    if _STARTED:
        return True                        # Settings may point at a new address; the threads stay
    _STARTED = True
    threading.Thread(target=_ticker, daemon=True).start()
    threading.Thread(target=_worker, daemon=True).start()
    print("lucent: bridge on, %s" % _URL, flush=True)
    return True


def _reconcile():
    """Members, teams, projects and profiles: the half of a tick that is safe to run inside a
    request. Pickup is not — it runs a whole turn — so it stays in the ticker."""
    global _PROV
    before = _ERRS
    a = _admin()
    if not a:
        return None
    now = time.time()
    if now - _PROV > PROVISION_EVERY:
        boot = _bootstrap(a)
        if boot:
            _provision(a, boot)
            _sync_projects(a, boot)
            _PROV = now
            _READY.set()
    _sync_profiles()
    st = _state()
    st["last_sync"] = time.time()
    if _ERRS == before:
        st["last_error"] = ""
    _save()
    return a


def _ticker():
    while True:
        try:
            if _reconcile():
                _pickup()
        except Exception as e:
            _fail("tick: %s" % e)
        time.sleep(POLL)


def _bootstrap(a):
    code, obj = _call("GET", "/api/bootstrap", token=a["token"])
    if code != 200:
        _fail("bootstrap (%s): %s" % (code, obj.get("error") or ""))
        return None
    return obj
