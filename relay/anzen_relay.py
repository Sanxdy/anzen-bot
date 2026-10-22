#!/usr/bin/env python3
"""The Anzen link: how the phone reaches the desktop app from any network.

ZCode does this with a relay it hosts — the machine running the agent dials *out* to
`wss://zcode.z.ai/ws`, the phone dials out to the same place, and the two are matched and piped
together. That is the shape copied here, with the relay on a host you own instead of somebody
else's cloud. It is the shape that works behind a home router (neither end needs an inbound port;
both dial out) and the shape that is hard to find (there is no port listening to scan).

Two roles in one file, because they are the two ends of one protocol:

    python3 anzen_relay.py relay --port 7788 --secret <s>          # on the public host
    python3 anzen_relay.py agent --url wss://…/agent --to unix:/…/anzen.sock --secret <s>

The relay holds at most one desktop at a time and forwards every HTTP request it is given to that
desktop, streaming the reply back as it arrives. A chat turn and the watch stream are long-lived
`text/event-stream` responses, so nothing here may buffer a body until it ends: the phone must see
each frame as the backend writes it, or the turn looks frozen.

Nothing here decides who may call the API. The request is replayed against the backend carrying the
Host the phone dialled, so the backend's own token rule is what stands between the internet and an
API that runs shell commands. The secret on this file only keeps a stranger from registering *as*
the desktop.
"""
import argparse, base64, hashlib, http.client, json, os, queue, secrets, signal, socket, ssl, struct, sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_FRAME = 8 << 20          # a body bigger than this is a bug, not a request
CHUNK = 16384
# A request body the relay will carry. It is refused before the read, so an oversized
# `Content-Length` costs one line and not a buffer. Kept under the frame budget above with room for
# the base64 the body is carried in (4/3 its size) and the JSON around it — a body that overran the
# frame cap would be refused by the far end's `recv`, which drops the whole link rather than the one
# request. Anything larger is a zip upload, which belongs on the computer the app runs on.
MAX_BODY_BYTES = 6 << 20
# The link is idle most of the time — a phone that is not being used sends nothing for hours. The
# heartbeat is what keeps it alive, and the read wait has to outlast the heartbeat: with a wait
# shorter than the beat, an idle link is torn down and re-dialled every cycle, so the phone finds the
# relay with nothing behind it for a few seconds in every cycle, and the settings screen calls a link
# that is actually fine down. Three beats still notices a connection that really dropped, promptly.
BEAT_S = 30
IDLE_TIMEOUT = BEAT_S * 3


def ws_key(): return base64.b64encode(os.urandom(16)).decode()
def ws_accept(key):
    return base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()


class WS:
    """One WebSocket connection — either end. Frames are built and parsed here and nowhere else.

    `mask` is the one real difference between the ends: a client must mask what it sends and a
    server must not, so the same code serves the relay and the desktop with one flag between them.
    A ping is answered inside `recv` rather than handed up, because a heartbeat is the transport's
    business and not the protocol's.
    """
    def __init__(self, sock, mask):
        self.s = sock; self.mask = mask; self.buf = b""; self.wlock = threading.Lock()

    def send(self, data, opcode=0x1):
        if isinstance(data, str): data = data.encode()
        with self.wlock:
            h = bytearray([0x80 | opcode]); n = len(data); m = 0x80 if self.mask else 0
            if n < 126: h.append(m | n)
            elif n < 65536: h.append(m | 126); h += struct.pack(">H", n)
            else: h.append(m | 127); h += struct.pack(">Q", n)
            if self.mask:
                k = os.urandom(4); h += k
                data = bytes(b ^ k[i & 3] for i, b in enumerate(data))
            self.s.sendall(bytes(h) + data)

    def ping(self): self.send(b"", 0x9)

    def _take(self, n):
        while len(self.buf) < n:
            d = self.s.recv(65536)
            if not d: raise ConnectionError("closed")
            self.buf += d
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self):
        """The next whole message as text, or None when the peer closed. Fragments are joined."""
        parts = []
        while True:
            b0, b1 = self._take(2)
            fin, op, ln = b0 & 0x80, b0 & 0x0F, b1 & 0x7F
            if ln == 126: ln = struct.unpack(">H", self._take(2))[0]
            elif ln == 127: ln = struct.unpack(">Q", self._take(8))[0]
            if ln > MAX_FRAME: raise ConnectionError("frame too large")
            mk = self._take(4) if b1 & 0x80 else None
            data = self._take(ln)
            if mk: data = bytes(b ^ mk[i & 3] for i, b in enumerate(data))
            if op == 0x9: self.send(data, 0xA); continue        # ping -> pong, and say nothing
            if op == 0xA: continue
            if op == 0x8: return None
            parts.append(data)
            if fin: return b"".join(parts).decode("utf-8", "replace")

    def close(self):
        try: self.send(b"", 0x8)
        except Exception: pass
        try: self.s.close()
        except Exception: pass


# ------------------------------------------------------------------ the relay
class Stream:
    """One request in flight: the agent's frames land here, the phone's handler drains them."""
    def __init__(self): self.q = queue.Queue()

    def put(self, m): self.q.put(m)

    def get(self, timeout):
        try: return self.q.get(timeout=timeout)
        except queue.Empty: return None


class Desktop:
    """The connected desktop, as the relay sees it."""
    def __init__(self, ws):
        self.ws = ws; self.streams = {}; self.lock = threading.Lock(); self.n = 0

    def open(self):
        with self.lock:
            self.n += 1; sid = self.n; st = Stream(); self.streams[sid] = st
        return sid, st

    def shut(self, sid):
        with self.lock: self.streams.pop(sid, None)

    def pump(self):
        """Read the desktop's frames until it goes away, then wake every stream waiting on it —
        a request with nobody left to answer it must not sit until its timeout."""
        try:
            while True:
                msg = self.ws.recv()
                if msg is None: break
                try: m = json.loads(msg)
                except Exception: continue
                with self.lock: st = self.streams.get(m.get("id"))
                if st: st.put(m)
        except Exception:
            pass
        finally:
            with self.lock: waiting = list(self.streams.values())
            for st in waiting: st.put({"t": "err", "msg": "the desktop went away"})


DESKTOP = None
_dlock = threading.Lock()
# Sockets that stopped being HTTP requests and became the link. `socketserver` half-closes every
# connection when its handler returns, which is right for a request and fatal for this: the desktop
# would see EOF the instant it finished upgrading. These are the ones to leave alone.
UPGRADED = set()


def desktop():
    with _dlock: return DESKTOP


def install(d):
    """Register the desktop that just dialled in. The newest wins: a machine that reconnects
    before the old socket is noticed must not be locked out by its own ghost."""
    global DESKTOP
    with _dlock: old, DESKTOP = DESKTOP, d
    if old is not None:
        try: old.ws.close()
        except Exception: pass


def uninstall(d):
    global DESKTOP
    with _dlock:
        if DESKTOP is d: DESKTOP = None


class RelayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "anzen-relay"
    secret = ""

    def log_message(self, *a): pass

    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers()
        if self.command != "HEAD": self.wfile.write(b)

    def do_GET(self): self._route()
    def do_POST(self): self._route()
    def do_PUT(self): self._route()
    def do_PATCH(self): self._route()
    def do_DELETE(self): self._route()
    def do_HEAD(self): self._route()
    def do_OPTIONS(self): self._route()

    def _route(self):
        if self.path.split("?")[0] == "/agent" and \
                self.headers.get("Upgrade", "").lower() == "websocket":
            return self._register()
        if self.path.split("?")[0] == "/healthz":
            # The liveness probe is the operator's, not the internet's. It answered without a token
            # and named whether a desktop was dialled in, so a stranger who found this address
            # learned that the machine was online. It now takes the same secret the desktop registers
            # with, which is the one value only the two ends hold.
            if self.secret and not secrets.compare_digest(self.headers.get("X-Anzen-Relay") or "", self.secret):
                return self.send_error(403)
            return self._json(200, {"ok": True, "desktop": desktop() is not None})
        d = desktop()
        # Nothing behind the door: the phone is told so, and told it in a way that reads as "the
        # app is not running" rather than as a fault of its own. The body is left unread, so this
        # connection cannot carry another request: HTTP/1.1 keep-alive would parse the leftover
        # body as the next request line and answer that instead — a 501 for a request nobody made.
        if d is None:
            self.close_connection = True
            return self._json(503, {"error": "Anzen-bot is not running on your computer."})
        return self._forward(d)

    def _register(self):
        """The desktop dialling in. The handshake is answered by hand and the socket is then taken
        off this handler — the request ends here, but the connection does not: it becomes the link
        the phone's requests travel down."""
        if self.secret and not secrets.compare_digest(self.headers.get("X-Anzen-Relay") or "", self.secret):
            return self.send_error(403)
        key = self.headers.get("Sec-WebSocket-Key")
        if not key: return self.send_error(400)
        self.wfile.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                          "Connection: Upgrade\r\nSec-WebSocket-Accept: %s\r\n\r\n"
                          % ws_accept(key)).encode())
        self.wfile.flush()
        self.close_connection = True
        UPGRADED.add(self.connection.fileno())
        # A duplicate of the fd: this handler is about to close its own socket, and the link has to
        # outlive it. Nothing was read past the headers (the desktop speaks only once it has the
        # 101), so no bytes are lost by handing the raw socket on.
        sock = socket.socket(fileno=os.dup(self.connection.fileno()))
        # The desktop beats every BEAT_S, so a link that says nothing for IDLE_TIMEOUT is gone —
        # and a read that waits forever cannot tell a quiet link from a half-open one (a slept
        # laptop, a lost route, no FIN). Left waiting, the dead link stays registered and every
        # phone request is forwarded into it and hangs until its own timeout.
        sock.settimeout(IDLE_TIMEOUT)
        d = Desktop(WS(sock, mask=False))
        install(d)
        threading.Thread(target=lambda: (d.pump(), uninstall(d)), daemon=True).start()

    def _forward(self, d):
        try: n = int(self.headers.get("Content-Length") or 0)
        except ValueError: return self._json(400, {"error": "Content-Length is not a number"})
        if n < 0: return self._json(400, {"error": "Content-Length is negative"})
        if n > MAX_BODY_BYTES:
            # Refused before the read: reading it first is the whole cost the cap exists to avoid.
            self.close_connection = True
            return self._json(413, {"error": "that body is larger than %d MB — upload it from the "
                                             "computer the app runs on" % (MAX_BODY_BYTES // 1_000_000)})
        body = self.rfile.read(n) if n else b""
        sid, st = d.open()
        head = None
        try:
            d.ws.send(json.dumps({
                "t": "req", "id": sid, "m": self.command, "p": self.path,
                "h": {k: v for k, v in self.headers.items()},
                "b": base64.b64encode(body).decode()}))
            head = st.get(timeout=120)
            if head is None:
                return self._json(504, {"error": "the desktop did not answer"})
            if head.get("t") == "err":
                return self._json(502, {"error": head.get("msg") or "the desktop failed"})
            self.send_response(int(head.get("s") or 502))
            for k, v in (head.get("h") or {}).items():
                # The reply is re-chunked on the way out, so the backend's framing is dropped and
                # this end's put in its place. Without that a stream arrives as one lump at the end.
                if k.lower() in ("content-length", "transfer-encoding", "connection",
                                 "keep-alive", "date", "server"): continue
                self.send_header(k, v)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            if self.command == "HEAD": return
            while True:
                m = st.get(timeout=300)
                if m is None: break
                t = m.get("t")
                if t == "data":
                    c = base64.b64decode(m.get("b") or "")
                    if c:
                        self.wfile.write(b"%x\r\n" % len(c) + c + b"\r\n"); self.wfile.flush()
                elif t in ("end", "err"):
                    break
            self.wfile.write(b"0\r\n\r\n"); self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            # The phone walked away — a closed tab, a slept phone, a lost wifi. The turn behind it
            # has to be told, or a `/api/watch` stream would sit open on the desktop forever.
            try: d.ws.send(json.dumps({"t": "cancel", "id": sid}))
            except Exception: pass
        finally:
            d.shut(sid)
            self.close_connection = True


class RelayServer(ThreadingHTTPServer):
    daemon_threads = True

    def shutdown_request(self, request):
        """Let go of an upgraded socket without shutting it down.

        `socketserver` ends every request with `shutdown(SHUT_WR)` + `close`, which is exactly right
        for a request and exactly wrong here: the link outlives the request that opened it, and a
        half-close reaches the desktop as EOF. The handler's own fd is still released — the duplicate
        taken at upgrade time is what stays open.
        """
        if request.fileno() in UPGRADED:
            UPGRADED.discard(request.fileno())
            self.close_request(request)
            return
        super().shutdown_request(request)


def run_relay(port, host, secret):
    RelayHandler.secret = secret
    srv = RelayServer((host, port), RelayHandler)
    print("relay listening on %s:%d%s" % (host, port, " (secret required)" if secret else ""),
          file=sys.stderr, flush=True)
    srv.serve_forever()


# ------------------------------------------------------------------ the desktop's end
class UnixConn(http.client.HTTPConnection):
    """The desktop app answers on a Unix socket, not a port — that is the whole reason opening the
    app puts nothing on localhost. The link reaches the backend the same way the window does."""
    def __init__(self, path, timeout=600):
        super().__init__("localhost", timeout=timeout); self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout); self.sock.connect(self.path)


def connect(target):
    if target.startswith("unix:"): return UnixConn(target[5:])
    u = urlparse(target)
    return http.client.HTTPConnection(u.hostname, u.port or 80, timeout=600)


def serve(ws, target, m):
    """Replay one request against the local backend and stream the answer back.

    The Host the phone dialled is kept, and that is load-bearing: the backend decides who may call
    the API by looking at it, and a request that arrived naming the public hostname is treated as
    coming from the network — so it has to carry the token. Sending it as `127.0.0.1` instead would
    hand the whole internet an unauthenticated API that runs shell commands.
    """
    sid = m.get("id")
    try:
        c = connect(target)
        hdrs = {k: v for k, v in (m.get("h") or {}).items()
                if k.lower() not in ("host", "connection", "content-length", "transfer-encoding",
                                     "accept-encoding", "upgrade", "keep-alive")}
        hdrs["Host"] = (m.get("h") or {}).get("Host") or urlparse(target).netloc or "localhost"
        hdrs["Connection"] = "close"
        hdrs["X-Anzen-Door"] = "remote"      # the backend's third door: a browser's, not the app's
        body = base64.b64decode(m.get("b") or "")
        c.request(m.get("m") or "GET", m.get("p") or "/", body=body or None, headers=hdrs)
        r = c.getresponse()
        out = {}
        for k, v in r.getheaders():
            if k.lower() in ("content-length", "transfer-encoding", "connection", "keep-alive"):
                continue
            out[k] = v
        ws.send(json.dumps({"t": "head", "id": sid, "s": r.status, "h": out}))
        while True:
            # `read1`, not `read`: read(16384) waits for 16384 bytes, and a chat turn writes a few
            # bytes every so often — so the whole turn would arrive in one lump at the end of it.
            d = r.read1(CHUNK)
            if not d: break
            ws.send(json.dumps({"t": "data", "id": sid, "b": base64.b64encode(d).decode()}))
        ws.send(json.dumps({"t": "end", "id": sid}))
        c.close()
    except Exception as e:
        try: ws.send(json.dumps({"t": "err", "id": sid, "msg": str(e)}))
        except Exception: pass


def dial(url, secret, timeout=20):
    """Open the link to the relay. Plain `socket` + `ssl`, no client library — the same stdlib-only
    footing as the rest of the backend."""
    u = urlparse(url)
    secure = u.scheme in ("wss", "https")
    # Plain WebSocket/HTTP is only acceptable for loopback test relays. A configured remote relay
    # must be encrypted end-to-end; otherwise the shared relay secret and API traffic are cleartext.
    local = u.hostname in ("127.0.0.1", "::1", "localhost")
    if not secure and not (local and u.scheme in ("ws", "http")):
        raise ValueError("relay connections must use wss/https")
    s = socket.create_connection((u.hostname, u.port or (443 if secure else 80)), timeout=timeout)
    if secure: s = ssl.create_default_context().wrap_socket(s, server_hostname=u.hostname)
    key = ws_key()
    req = ("GET %s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
           "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n" % (u.path or "/agent", u.netloc, key))
    if secret: req += "X-Anzen-Relay: %s\r\n" % secret
    s.sendall((req + "\r\n").encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        d = s.recv(4096)
        if not d: raise ConnectionError("the relay closed during the handshake")
        buf += d
    head, _, rest = buf.partition(b"\r\n\r\n")
    line = head.split(b"\r\n")[0].decode("utf-8", "replace")
    if "101" not in line: raise ConnectionError("the relay refused the link: " + line)
    # The connect wait above is for the handshake. Now that the link is open it must survive being
    # idle, so the socket waits IDLE_TIMEOUT — long enough for the heartbeat's pong to arrive first.
    s.settimeout(IDLE_TIMEOUT)
    ws = WS(s, mask=True); ws.buf = rest
    return ws


class Link:
    """One dial-out to the relay, as the desktop holds it.

    The thread reconnects on its own — a laptop that sleeps, a relay that restarts, hotel wifi that
    drops: the phone should find the link up again without anyone touching the app. `stop` closes the
    socket under the read waiting on it, which is the only way to break that read; and it has to be a
    real stop, because a switch saying the phone cannot reach in has to mean it.
    """
    def __init__(self, url, target, secret, on_state=None, once=False):
        self.url, self.target, self.secret = url, target, secret
        self.on_state, self.once = on_state, once
        self._stop = threading.Event(); self._ws = None
        self._t = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._t.start(); return self

    def stop(self):
        self._stop.set()
        ws, self._ws = self._ws, None
        if ws is not None:
            try: ws.close()
            except Exception: pass

    def _state(self, up, why=""):
        if self.on_state:
            try: self.on_state(up, why)
            except Exception: pass

    def _run(self):
        while not self._stop.is_set():
            try:
                ws = dial(self.url, self.secret)
                if self._stop.is_set():
                    try: ws.close()
                    except Exception: pass
                    return
                self._ws = ws
                print("link up to %s -> %s" % (self.url, self.target), file=sys.stderr, flush=True)
                self._state(True)
                beat = threading.Event()

                def ping():
                    # A heartbeat that fails means the link is gone: close the socket, which is what
                    # breaks the read waiting on it, so the loop above re-dials instead of sitting on a
                    # dead connection until the read wait expires on its own.
                    while not beat.wait(BEAT_S):
                        try: ws.ping()
                        except Exception:
                            try: ws.close()
                            except Exception: pass
                            return
                threading.Thread(target=ping, daemon=True).start()
                try:
                    while True:
                        msg = ws.recv()
                        if msg is None: raise ConnectionError("the relay closed the link")
                        try: m = json.loads(msg)
                        except Exception: continue
                        if m.get("t") == "req":
                            threading.Thread(target=serve, args=(ws, self.target, m),
                                             daemon=True).start()
                        # `req` is the only message the app sends; `cancel` travels the other way.
                finally:
                    beat.set()
            except Exception as e:
                print("link down: %s" % e, file=sys.stderr, flush=True)
                self._state(False, str(e))
            finally:
                self._ws = None
            if self.once: return
            if self._stop.wait(3): return


def run_agent(url, target, secret, once=False):
    """The command line's dial-out: the same Link the app runs, held here until it ends."""
    l = Link(url, target, secret, once=once).start()
    try: l._t.join()
    except KeyboardInterrupt: l.stop()


def main():
    ap = argparse.ArgumentParser(description="the Anzen link: phone <-> relay <-> desktop")
    sub = ap.add_subparsers(dest="role", required=True)
    r = sub.add_parser("relay"); r.add_argument("--port", type=int, default=7788)
    r.add_argument("--host", default="127.0.0.1"); r.add_argument("--secret", default="")
    a = sub.add_parser("agent"); a.add_argument("--url", required=True)
    a.add_argument("--to", required=True); a.add_argument("--secret", default="")
    a.add_argument("--once", action="store_true")
    ns = ap.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    if ns.role == "relay": run_relay(ns.port, ns.host, ns.secret)
    else: run_agent(ns.url, ns.to, ns.secret, ns.once)


if __name__ == "__main__":
    main()
