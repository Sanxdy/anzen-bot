#!/usr/bin/env python3
"""App-level checks: drive the *built* Anzen-bot app, not a browser.

The app is Electron. Its window is loaded **from disk** — a `file://` page out of the install
directory — and the renderer talks to the main process over **Electron IPC**, which drives a Python
backend over a Unix socket. So the app opens no TCP port at all. This suite proves that, which is the
property the whole design exists for, and then drives the backend over the same socket to check the
app actually works.

    python3 tests/test_desktop_app.py
    ANZEN_APP=/path/to/Anzen-bot.app python3 tests/test_desktop_app.py
    ANZEN_APP=source python3 tests/test_desktop_app.py     # run from the repo, no packaging

Set ANZEN_SKIP_WINDOW=1 on a machine with no display (CI): the app still starts and is driven over
its socket, but the window checks are skipped.
"""
import hashlib, http.client, http.server, json, os, re, socket, subprocess, sys, tempfile, threading, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
REAL_DATA = os.path.join(ROOT, "data")
SECRET = "sk-appsuite-should-never-surface"
PASS, FAIL, SKIP = [], [], []


def check(name, ok, extra=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + (f"  {extra}" if extra and not ok else ""))


def skip(name, why):
    SKIP.append(name)
    print("  SKIP " + name + "  (" + why + ")")


# ------------------------------------------------------------------ the app
def app_path():
    """What a person double-clicks. `ANZEN_APP` aims it at a build elsewhere, or at `source` to run
    the shell out of the repo; otherwise the packaged app in desktop/dist is used."""
    env = os.environ.get("ANZEN_APP")
    if env == "source":
        return None                       # a sentinel: run `electron .` from desktop/electron
    if env:
        env = os.path.abspath(env)
        return (os.path.join(env, "Contents", "MacOS", "Anzen-bot") if env.endswith(".app") else env)
    dist = os.path.join(ROOT, "desktop", "dist")
    for sub in ("mac", "mac-arm64", "mac-universal", "win-unpacked", "linux-unpacked", ""):
        d = os.path.join(dist, sub) if sub else dist
        mac = os.path.join(d, "Anzen-bot.app", "Contents", "MacOS", "Anzen-bot")
        if os.path.exists(mac): return mac
        for name in ("Anzen-bot.exe", "anzen-bot", "Anzen-bot"):
            p = os.path.join(d, name)
            if os.path.exists(p): return p
    return os.path.join(dist, "Anzen-bot.app", "Contents", "MacOS", "Anzen-bot")


# ------------------------------------------------------------------ a socket HTTP client
class UDS(http.client.HTTPConnection):
    """The app's own channel: a Unix socket, not a port. This is how the test talks to the backend —
    the same way the app's window does, only without going through the window."""
    def __init__(self, path, timeout=30):
        super().__init__("localhost", timeout=timeout); self.sock_path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout); self.sock.connect(self.sock_path)


def raw(sock, path, method="GET", body=None, headers=None, path_as_is=False):
    """One HTTP request over the app's socket."""
    p = path
    if not path_as_is:
        p = os.path.normpath(path) or "/"
    h = {"Host": "127.0.0.1", "Connection": "close"}
    h.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    if body is not None: h["Content-Type"] = "application/json"
    c = UDS(sock)
    try:
        c.request(method, p, body=data, headers=h)
        r = c.getresponse()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read().decode("utf-8", "replace")
    except OSError:
        return 0, {}, ""
    finally:
        c.close()


def jget(sock, path, **kw):
    code, _, body = raw(sock, path, **kw)
    try:
        return code, json.loads(body)
    except Exception:
        return code, None


def events(body):
    """The `data:` lines of an SSE stream, parsed. A comment (the keepalive) is not one."""
    out = []
    for line in body.splitlines():
        if line.startswith("data: "):
            try:
                out.append(json.loads(line[6:]))
            except Exception:
                pass
    return out


# ------------------------------------------------------------------ the stub router
class StubRouter(http.server.BaseHTTPRequestHandler):
    """Stands in for the OpenAI endpoint the app talks to. It answers in two steps so a turn really
    uses a tool: the first call asks for a `write_file`, the second — the one that arrives after the
    tool has run — gives the canned reply. That is what makes a tool row, a diff and the model's
    second round trip part of the run rather than something the test asserts about in the abstract."""
    reply = "Hello from the stub router."
    calls = []
    writes = [0]        # every write differs from the one before it, so the second turn shows a diff

    def _send(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/v1/models"):
            return self._send({"data": [{"id": "stub-model"}]})
        self._send({})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b"{}"
        StubRouter.calls.append(self.path)
        try: req = json.loads(body or b"{}")
        except Exception: req = {}
        msgs = req.get("messages") or []
        if any(m.get("role") == "tool" for m in msgs):
            msg = {"role": "assistant", "content": StubRouter.reply}
        else:
            StubRouter.writes[0] += 1
            body_text = "one\ntwo\n%d\n" % StubRouter.writes[0]   # never the same file twice, so every write shows a diff
            msg = {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call_app_suite", "type": "function", "function": {
                    "name": "write_file",
                    "arguments": json.dumps({"path": "app-suite-note.txt",
                                             "content": body_text})}}]}
        usage = {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12}
        if req.get("stream"):
            return self._sse(msg, usage)
        self._send({"id": "c1", "object": "chat.completion",
                    "choices": [{"index": 0, "finish_reason": "stop", "message": msg}],
                    "usage": usage})

    def _sse(self, msg, usage):
        """The same answer, written the way a streaming router writes one: content in pieces, a tool
        call split across chunks with its name first and its arguments after. The app has to read all
        of it the way it reads the real thing, or the live-typing path is never actually exercised."""
        def chunk(delta, finish=None):
            return "data: " + json.dumps({"id": "c1", "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}) + "\n\n"
        out = ""
        if msg.get("tool_calls"):
            tc = msg["tool_calls"][0]
            out += chunk({"role": "assistant", "tool_calls": [
                {"index": 0, "id": tc["id"], "type": "function",
                 "function": {"name": tc["function"]["name"], "arguments": ""}}]})
            args = tc["function"]["arguments"]
            for i in range(0, len(args), 24):                  # the arguments arrive a few bytes at a time
                out += chunk({"tool_calls": [{"index": 0, "function": {"arguments": args[i:i + 24]}}]})
            out += chunk({}, "tool_calls")
        else:
            text = msg.get("content") or ""
            for i in range(0, len(text), 6):                    # a token-ish piece at a time
                out += chunk({"role": "assistant", "content": text[i:i + 6]})
            out += chunk({}, "stop")
        out += "data: " + json.dumps({"id": "c1", "choices": [], "usage": usage}) + "\n\n"
        out += "data: [DONE]\n\n"
        b = out.encode()
        self.send_response(200); self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def log_message(self, *a): pass


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def tree_hash(path):
    """Every file under `path`, by name and content — so 'the app never touched the real data' is a
    fact rather than a hope."""
    h = hashlib.sha1()
    for root, dirs, files in os.walk(path):
        dirs.sort()
        for fn in sorted(files):
            fp = os.path.join(root, fn)
            h.update(os.path.relpath(fp, path).encode())
            with open(fp, "rb") as f:
                h.update(f.read())
    return h.hexdigest()


def tree(root_pid):
    """Every descendant pid of `root_pid`, and each one's command line."""
    ps = subprocess.run(["ps", "-eo", "pid,ppid,command"], capture_output=True, text=True).stdout
    kids, cmds = {}, {}
    for ln in ps.splitlines()[1:]:
        parts = ln.split(None, 2)
        if len(parts) < 3: continue
        kids.setdefault(parts[1], []).append(parts[0]); cmds[parts[0]] = parts[2]
    pids, stack = {str(root_pid)}, [str(root_pid)]
    while stack:
        for k in kids.get(stack.pop(), []):
            if k not in pids:
                pids.add(k); stack.append(k)
    return pids, cmds


def tcp_listeners(pids):
    """The listening TCP sockets belonging to exactly these pids — the app's own, not the machine's."""
    try:
        out = subprocess.run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"],
                             capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return None
    rows = [l for l in out.splitlines()[1:] if l.split()[1] in pids]
    return rows


def app_env(data, stub_url, selftest=False):
    env = dict(os.environ)
    # The app under test gets a port of its own. It shares the default (8093) with a real install,
    # and a real install with the phone switch on is listening there — the test app would then fail
    # to bind, which is a fact about this Mac, not about the app. A free port makes the run
    # independent of whatever else is running here.
    env.update({"DATA_DIR": data, "SANDBOX_DIR": os.path.join(data, "sandbox"),
                "ROUTER_URL": stub_url, "ROUTER_KEY": SECRET, "DEFAULT_MODEL": "stub-model",
                "BROWSER_WARMUP": "0", "PORT": str(free_port())})
    if selftest: env["ANZEN_SELFTEST"] = "1"
    return env


def launch(exe, data, stub_url, log, selftest=False):
    # Its own Electron profile, so the one-shell-at-a-time lock does not make the test app quit
    # whenever the real app happens to be open on this Mac. The socket is under DATA_DIR, not here.
    own = ["--user-data-dir=" + os.path.join(data, "electron")]
    if exe is None:                       # run the shell out of the repo
        cmd, cwd = ["npx", "electron", "."] + own, os.path.join(ROOT, "desktop", "electron")
    else:
        cmd, cwd = [exe] + own, None
    fh = open(log, "wb")
    return subprocess.Popen(cmd, cwd=cwd, env=app_env(data, stub_url, selftest),
                            stdout=fh, stderr=subprocess.STDOUT)


def wait_sock(path, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        if os.path.exists(path):
            c, _, _ = raw(path, "/api/lan")
            if c == 200: return True
        time.sleep(0.3)
    return False


def wait_log(log, needle, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if needle in open(log, "rb").read().decode("utf-8", "replace"): return True
        except OSError:
            pass
        time.sleep(0.4)
    return False


def stop(proc):
    try:
        proc.terminate(); proc.wait(timeout=12)
    except Exception:
        try: proc.kill()
        except Exception: pass


# ------------------------------------------------------------------ the run
def main():
    exe = app_path()
    print("== Anzen-bot app suite ==")
    print("   app: " + (exe if exe else "(from source: desktop/electron)"))
    if exe is not None and not (os.path.exists(exe) and os.access(exe, os.X_OK)):
        check("the app is built", False, exe + " (build it: python3 desktop/build.py)")
        return summary()

    data = tempfile.mkdtemp(prefix="anzen-apptest-")
    before = tree_hash(REAL_DATA)
    stub_port = free_port()
    stub = http.server.ThreadingHTTPServer(("127.0.0.1", stub_port), StubRouter)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    stub_url = "http://127.0.0.1:%d/v1" % stub_port
    proc = None
    try:
        log = os.path.join(data, "app.log")
        sock = os.path.join(data, "anzen.sock")
        selftest = os.environ.get("ANZEN_SKIP_WINDOW") != "1"
        proc = launch(exe, data, stub_url, log, selftest=selftest)

        # ---- 1. it comes up on a socket, not a port ----
        up = wait_sock(sock)
        check("the app starts and opens its own channel", up)
        if not up:
            print("   --- app log ---")
            print("\n".join(open(log, "rb").read().decode("utf-8", "replace").splitlines()[-30:]))
            return summary()

        pids, cmds = tree(proc.pid)
        backends = [p for p, c in cmds.items() if "anzen-backend" in c or "anzen_app.py" in c]
        check("the app runs a backend of its own", bool(backends), str(cmds)[:200])

        # ---- 2. the headline: opening the app opens no port ----
        rows = tcp_listeners(pids)
        if rows is None:
            skip("the app opens no TCP listener", "lsof unavailable")
        else:
            check("the app opens no TCP listener", not rows,
                  "listeners: " + " | ".join(rows))

        # ---- 3. the API works over that socket ----
        c, d = jget(sock, "/api/config")
        ids = [b["id"] for b in (d or {}).get("bots", [])]
        check("the API answers over the app's socket", c == 200 and len(ids) >= 5, str(c))
        check("the router key is write-only — it never comes back to the page",
              SECRET not in json.dumps(d or {}), "the key value leaked into /api/config")
        c, _, body = raw(sock, "/")
        # The backend is API-only on the app's own channel: the shell is the Electron app's, loaded
        # off the disk and checked below by driving the real window. A shell path reaching the socket
        # is therefore a 404, which is the smaller surface, not a failure.
        check("the backend serves the API and nothing else", c == 404, str(c))
        for f in ("app.js", "index.html"):
            c, _, _ = raw(sock, "/" + f)
            check("the backend does not serve the shell (" + f + ")", c == 404, str(c))

        # ---- 4. the secret store is never a file ----
        for p in ("/data/config.json", "/data/settings.json", "/data/access_token",
                  "/../server.py", "/../desktop/anzen_app.py", "/../data/bots.json"):
            c, _, _ = raw(sock, p, path_as_is=True)
            check("hides " + p, c == 404, str(c))

        # ---- 5. the roster and the rooms are the app's own ----
        c, d = jget(sock, "/api/bot", method="POST",
                    body={"bot": {"id": "appsuite-tmp", "name": "App Suite Temp"}})
        check("a bot can be created", c == 200 and d and d.get("ok"), str(d)[:120])
        c, d = jget(sock, "/api/config")
        check("the new bot shows up in the roster",
              any(b["id"] == "appsuite-tmp" for b in (d or {}).get("bots", [])))
        jget(sock, "/api/bot/delete", method="POST", body={"id": "appsuite-tmp"})
        c, d = jget(sock, "/api/config")
        check("the bot is gone after delete",
              not any(b["id"] == "appsuite-tmp" for b in (d or {}).get("bots", [])))
        c, d = jget(sock, "/api/channel", method="POST", body={"channel": {"name": "App Suite Room"}})
        check("a room can be created", c == 200 and d and d.get("ok"), str(d)[:120])
        jget(sock, "/api/channel/delete", method="POST", body={"id": "app-suite-room"})

        # ---- 6. a real turn, end to end ----
        StubRouter.calls.clear()
        c, _, body = raw(sock, "/api/chat", method="POST", body={"bot": "builder", "text": "hello there"})
        evs = events(body); kinds = [e.get("type") for e in evs]
        check("the turn streams as SSE", c == 200 and bool(evs), str(c))
        check("the bot answers through the app", any(e.get("type") == "agent_text"
              and StubRouter.reply in (e.get("text") or "") for e in evs), str(kinds))
        check("the turn ends with done", kinds and kinds[-1] == "done", str(kinds))
        check("the app actually called the model router", bool(StubRouter.calls), str(StubRouter.calls))
        c, d = jget(sock, "/api/history?session=builder")
        msgs = (d or {}).get("messages") or []
        check("the transcript keeps what was sent and what was said",
              any(m.get("content") == "hello there" for m in msgs)
              and any(StubRouter.reply in (m.get("content") or "") for m in msgs),
              json.dumps(msgs)[:200])

        # ---- 7. the LAN switch: the one thing that does open a port, and only when asked ----
        c, d = jget(sock, "/api/lan")
        check("the LAN is off by default", c == 200 and d and d.get("enabled") is False, str(d))
        c, d = jget(sock, "/api/lan", method="POST", body={"on": True})
        check("the switch turns the phone's listener on", c == 200 and d and d.get("ok"), str(d))
        time.sleep(1.2)
        rows = tcp_listeners(pids)
        check("the phone's listener is the only port the app opens",
              rows is None or len(rows) == 1, "listeners: " + " | ".join(rows or []))
        jget(sock, "/api/lan", method="POST", body={"on": False})
        time.sleep(1.6)
        rows = tcp_listeners(pids)
        check("turning the LAN off closes it again", rows is None or not rows,
              "listeners: " + " | ".join(rows or []))
        # The window's own channel must survive that switch.
        c, _ = jget(sock, "/api/config")
        check("the app keeps working while the phone switch is flipped", c == 200, str(c))

        # ---- 8. the window: the shell off the disk, the API over IPC ----
        if not selftest:
            skip("the window loads the shell off the disk", "ANZEN_SKIP_WINDOW=1")
            skip("the API is carried over IPC, not a port", "ANZEN_SKIP_WINDOW=1")
            skip("fetch reaches the API from inside the window", "ANZEN_SKIP_WINDOW=1")
            skip("a chat turn streams inside the window", "ANZEN_SKIP_WINDOW=1")
        else:
            ok = wait_log(log, "selftest ", timeout=120)
            txt = open(log, "rb").read().decode("utf-8", "replace")
            check("the window opens", "window open on file://" in txt, txt[-300:])
            d = {}
            for ln in txt.splitlines():
                if ln.startswith("selftest "):
                    try: d = json.loads(ln[len("selftest "):])
                    except Exception: d = {}
            check("the window loads the shell off the disk",
                  ok and d.get("protocol") == "file:" and d.get("fromDisk") is True,
                  json.dumps(d)[:200])
            check("the API is carried over IPC, not a port",
                  d.get("viaIpc") is True and not (d.get("origin") or "").startswith("http"),
                  json.dumps(d)[:200])
            check("fetch reaches the API from inside the window",
                  (d.get("config") or {}).get("ok") and (d.get("config") or {}).get("bots", 0) >= 5,
                  json.dumps(d.get("config"))[:200])
            ch = d.get("chat") or {}
            check("a chat turn streams inside the window",
                  ch.get("events", 0) > 0 and ch.get("last") == "done", json.dumps(ch)[:200])
            check("the answer arrives as it is written, not all at once",
                  ch.get("deltas", 0) >= 2, json.dumps(ch)[:200])

            # ---- 8b. the panel, read out of the window after driving it ----
            # The probe typed into the real composer and clicked the real Send, then read the real
            # DOM. These are the parts of the chat panel that only exist in the window, so this is
            # the only place they can be checked.
            ui = d.get("ui") or {}
            check("the startup splash is gone once the app has loaded",
                  ui.get("splash") is False, json.dumps(ui)[:200])
            check("the composer and the Stop control are in the window",
                  ui.get("search") is True and ui.get("stop") is True, json.dumps(ui)[:200])
            # Stop is for a turn that is running. `.btn` sets `display`, which outranks the browser's
            # `[hidden]{display:none}`, so the attribute alone left it on screen with nothing to stop —
            # hence computed style, sampled while the turn was in flight and again once it had ended.
            check("Stop is shown while a turn is running",
                  ui.get("stopDuring") is True, json.dumps(ui)[:200])
            check("Stop is gone once nothing is running",
                  ui.get("stopAfter") is False, json.dumps(ui)[:200])
            check("the turn the probe sent is drawn in the transcript",
                  ui.get("user", 0) >= 1 and ui.get("bot", 0) >= 1, json.dumps(ui)[:200])
            check("the sidebar lists the chat the turn happened in",
                  ui.get("chats", 0) >= 1, json.dumps(ui)[:200])
            acts = ui.get("acts") or []
            check("a message carries Copy, Reply and Forward",
                  {"Copy", "Reply", "Forward"}.issubset(set(acts)), json.dumps(acts)[:200])
            check("the probe opened the bot's own chat, not the room",
                  bool(ui.get("picked")) and ui["picked"] in (ui.get("header") or ""), json.dumps(ui)[:300])
            # The sidebar row for the open chat names the bot, as the header above the transcript does
            # — including when that bot sits inside a company, where the row used to name the company.
            check("the chat row in the sidebar names the bot, not a company",
                  bool(ui.get("picked")) and ui["picked"] in (ui.get("chatRow") or ""), json.dumps(ui)[:300])
            # A long chat list scrolls in place instead of pushing the channels and bots off-screen.
            cs = ui.get("chatScroll") or {}
            check("the chat list is capped and scrolls on its own",
                  cs.get("overflowY") == "auto" and cs.get("capped") is True, json.dumps(cs)[:200])
            # The hover pills are laid out even while invisible, so one anchored outward used to give
            # the whole panel a horizontal scrollbar with nothing ever shown outside it.
            check("the transcript has no horizontal scroll",
                  ui.get("hscroll") == 0, json.dumps(ui)[:200])
            check("the tool the turn ran is a row of its own",
                  ui.get("toolRows", 0) >= 1, json.dumps(ui)[:300])
            check("a tool row stays folded until it is asked for",
                  ui.get("toolOpen") == 0, json.dumps(ui)[:300])
            check("the file the tool wrote is drawn as a diff",
                  ui.get("diffLines", 0) >= 1, json.dumps(ui)[:300])
            # A tool row is a flex item in the #msgs column, and .m.tool clips its header with
            # overflow:hidden — which gives the row an automatic minimum size of zero. So a transcript
            # taller than its box used to squeeze every tool row down to its 2px border and the turn
            # drew as a wall of empty lines. Measured while the transcript overflows, because that is
            # the only state in which a row can be squeezed at all.
            rw = d.get("rows") or {}
            check("a tool row keeps its height when the transcript overflows",
                  rw.get("overflowing") is True and rw.get("min", 0) > 20
                  and rw.get("min", 0) >= (rw.get("thead") or 0) - 4, json.dumps(rw)[:300])
            # The glass themes blur the header, which makes it a stacking context; the chip popovers
            # hang off it, so a message bubble painting over an open popover was the whole bug.
            # Hit-tested where the popover and a bubble really do overlap, not at an assumed point.
            pop = d.get("popover") or {}
            check("an open popover sits above the transcript, not under it",
                  pop.get("overBubble") is True and pop.get("onPopover") is True,
                  json.dumps(pop)[:300])
            # Opening a chat lands at the bottom instead of animating its way down to it. `#msgs`
            # scrolls smoothly for a live turn, and that smoothness applied to the redraw as well, so
            # every open eased the transcript down from the top. `samples` proves the transcript was
            # actually scrollable — without that the check would pass on nothing.
            sc = d.get("scroll") or {}
            check("opening a chat lands at the bottom without animating down to it",
                  sc.get("samples", 0) >= 3 and sc.get("animated") == 0,
                  json.dumps(sc)[:400])
            # The window and the phone are two clients of one server, and a chat is one transcript on
            # disk — so a turn typed on one has to turn up on the other, "nothing missing". The probe
            # wrote to the chat that was already open through the ordinary API, which is exactly what
            # the phone's write is, and then read the real DOM. Nothing in the window sent it, so the
            # only thing that can have drawn it is the `/api/watch` nudge and the redraw it drives.
            # (The other direction is the same shell: the phone loads this same app.js off the phone's
            # door, which check 11 below reads.)
            fl = d.get("follow") or {}
            check("a chat written on another device turns up in the window",
                  fl.get("seen") is True, json.dumps(fl)[:300])
            check("...and the window was not the one that wrote it",
                  bool(fl.get("sid")) and fl.get("status") == 200, json.dumps(fl)[:200])

        # ---- 9. the app is told to quit and lets go ----
        stop(proc); proc = None
        time.sleep(0.6)
        check("the socket is cleaned up when the app exits", not os.path.exists(sock), sock)

        # ---- 10. it used the throwaway dir and never the real one ----
        check("the app wrote into the data dir it was given",
              os.path.exists(os.path.join(data, "config.json")))
        check("the real data/ is untouched", tree_hash(REAL_DATA) == before,
              "the app wrote into the repo's own data/")

        # ---- 11. the window's own shell knows the tools the backend offers ----
        # `use_skill` reads a skill on demand, so it turns up in transcripts. A step the shell cannot
        # label draws as a bare tool name and a JSON blob, so the display maps have to carry it. This
        # reads the app.js the window was actually loaded from — `resources/app` in a build, the repo
        # in source mode — not whichever copy happens to be lying around, so a stale bundle fails here.
        shell = os.path.join(ROOT, "app.js") if exe is None else os.path.join(
            os.path.dirname(os.path.dirname(exe)), "Resources", "app", "app.js")
        try:
            js = open(shell, encoding="utf-8", errors="replace").read()
        except OSError:
            js = ""
        check("the shell it loaded labels a use_skill step",
              'use_skill:"read skill"' in js and 'use_skill:"skills"' in js
              and 'args.skill' in js, shell)
        # The phone's door serves this same shell, so the phone follows a chat the desktop writes
        # exactly as the desktop follows one the phone writes. A shell without the subscription would
        # leave the phone showing a transcript that stopped moving the moment the desktop touched it.
        check("the shell it loaded follows a chat another device writes",
              "/api/watch" in js and "watchChats" in js, shell)

        # ---- 12. the shell the phone's door will serve is really there ----
        # The phone's door is the Android companion's way in and the one door that serves a *file*: the
        # window loads the shell off the disk and the app's own socket answers `/` with a 404 on
        # purpose. In a bundle the frozen backend and the web shell are not neighbours — electron-builder
        # keeps the backend under `Resources/backend` and the shell under `Resources/app` — so "the
        # shell is not where the server looked" is the mistake a bundle makes and a source run cannot.
        # It shows up as a 404 on `/` for the phone, which is a companion that cannot open at all.
        # `--doctor` prints the directory the server will serve from, which is the fact the door rests
        # on. (The door itself is not dialled here: macOS drops connections to a listener its firewall
        # has not been told about, and that is about this Mac's firewall list, not about the app.)
        if exe is None:
            doc_cmd = [sys.executable, os.path.join(ROOT, "desktop", "anzen_app.py"), "--doctor"]
        else:
            doc_cmd = [os.path.join(os.path.dirname(os.path.dirname(exe)), "Resources", "backend",
                                    "anzen-backend", "anzen-backend"), "--doctor"]
        try:
            # Pointed at a throwaway data dir: the doctor only reports where the shell is, and a check
            # must not leave a config behind in the real one.
            doc_env = dict(os.environ, DATA_DIR=data, SANDBOX_DIR=os.path.join(data, "sandbox"))
            doc = subprocess.run(doc_cmd, capture_output=True, text=True, timeout=90, env=doc_env).stdout
        except Exception as e:
            doc = "ERR " + str(e)
        line = next((l for l in doc.splitlines() if l.startswith("app shell")), "")
        served = " ".join(line.split()[2:]) if len(line.split()) > 2 else ""
        check("the shell the phone's door will serve is really there",
              bool(served) and os.path.isfile(os.path.join(served, "index.html")), line or doc[:200])
    finally:
        if proc is not None: stop(proc)
        stub.shutdown()
        import shutil
        shutil.rmtree(data, ignore_errors=True)

    return summary()


def summary():
    print("\n== %d passed, %d failed, %d skipped ==" % (len(PASS), len(FAIL), len(SKIP)))
    for f in FAIL:
        print("   FAILED: " + f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
