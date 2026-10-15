"""Who may call the API — the door rule, checked directly.

The rule used to read the `Host` header to decide "this is loopback", and `Host` is attacker-
controlled end to end: the relay replays the phone's Host verbatim and substitutes "localhost"
when there is none, so a request on the public link could name 127.0.0.1 and reach the whole API —
shell tools included — with no token. These cases pin the door to the socket and the peer address
instead, and pin every legitimate path so the fix cannot close one of them.

Pure stdlib, no browser: it builds a stand-in handler and calls the real `H._authorized`.
DATA_DIR is redirected to a temp dir before `server` is imported, so nothing here can touch the
user's live workspace.

    python3 tests/test_auth_doors.py
"""
import os, sys, socket, types, tempfile

_TMP = tempfile.mkdtemp(prefix="anzen-authdoors-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("HOST", "127.0.0.1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server                                                    # noqa: E402

TOKEN = server.lan_token()
UNIX, INET = socket.AF_UNIX, socket.AF_INET


class _Stub:
    def __init__(self, headers, peer, family, remote=False):
        self.headers = headers
        self.client_address = (peer, 4321) if peer is not None else ""
        self.server = types.SimpleNamespace(address_family=family)
        self._is_remote = remote
    def _remote(self): return self._is_remote
    def _req_token(self): return (self.headers.get("X-Anzen-Token") or "").strip()


_Stub._authorized = server.H._authorized
_Stub._token_ok = server.H._token_ok
_Stub._same_site = server.H._same_site

# (name, headers, peer, socket family, is_relay_replay, LAN switch, expected)
CASES = [
    # --- the app's own channel: a 0600 Unix socket, trusted ---
    ("desktop app on the unix socket",     {"Host": "127.0.0.1"}, "", UNIX, False, False, True),
    # --- the relay's door: replayed onto that socket, so it pays the token ---
    ("relay replay with token",            {"Host": "anzen.example.com", "X-Anzen-Token": TOKEN}, "", UNIX, True, False, True),
    ("relay replay without token",         {"Host": "anzen.example.com"}, "", UNIX, True, False, False),
    ("relay replay spoofing loopback host", {"Host": "127.0.0.1"}, "", UNIX, True, False, False),
    ("relay replay spoofing localhost",    {"Host": "localhost"}, "", UNIX, True, False, False),
    ("relay replay with no Host at all",   {}, "", UNIX, True, False, False),
    # --- the LAN door: anyone on the wifi reaches it, so the token is the credential ---
    ("LAN off: the port is not even open", {"Host": "192.168.1.20", "X-Anzen-Token": TOKEN}, "192.168.1.5", INET, False, False, False),
    ("LAN on: a LAN peer without the token", {"Host": "192.168.1.20"}, "192.168.1.5", INET, False, True, False),
    ("LAN on: a LAN peer with the token",  {"Host": "192.168.1.20", "X-Anzen-Token": TOKEN}, "192.168.1.5", INET, False, True, True),
    ("LAN on: a LAN peer cannot forge a cookie into a pass", {"Host": "192.168.1.20"}, "192.168.1.5", INET, False, True, False),
    ("LAN on: a cross-origin LAN caller is refused", {"Host": "192.168.1.20", "X-Anzen-Token": TOKEN, "Origin": "https://evil.example"}, "192.168.1.5", INET, False, True, False),
    ("LAN on: a same-origin LAN caller is allowed", {"Host": "192.168.1.20", "X-Anzen-Token": TOKEN, "Origin": "http://192.168.1.20"}, "192.168.1.5", INET, False, True, True),
    # --- a loopback peer: this machine's own page, judged by Host + Origin ---
    ("loopback browser, plain",            {"Host": "127.0.0.1"}, "127.0.0.1", INET, False, False, True),
    ("loopback browser naming a port",     {"Host": "127.0.0.1:8093"}, "127.0.0.1", INET, False, False, True),
    ("loopback with an IPv6 Host",         {"Host": "[::1]:8093"}, "::1", INET, False, False, True),
    ("loopback peer, rebinding Host",      {"Host": "evil.example"}, "127.0.0.1", INET, False, False, False),
    ("loopback peer, cross-site Origin",   {"Host": "127.0.0.1", "Origin": "https://evil.example"}, "127.0.0.1", INET, False, False, False),
    ("loopback peer, Origin: null",        {"Host": "127.0.0.1", "Origin": "null"}, "127.0.0.1", INET, False, False, False),
    ("loopback peer, same-origin",         {"Host": "127.0.0.1", "Origin": "http://127.0.0.1:8093"}, "127.0.0.1", INET, False, False, True),
    # --- same name, different origin: another port or scheme on this host is a page the user never opened ---
    ("loopback peer, same host other port", {"Host": "127.0.0.1:8093", "Origin": "http://127.0.0.1:9999"}, "127.0.0.1", INET, False, False, False),
    ("loopback peer, same host other scheme", {"Host": "127.0.0.1:8093", "Origin": "https://127.0.0.1:8093"}, "127.0.0.1", INET, False, False, False),
    ("LAN on: same host, other port is refused", {"Host": "192.168.1.20:8093", "X-Anzen-Token": TOKEN, "Origin": "http://192.168.1.20:9999"}, "192.168.1.5", INET, False, True, False),
]


def main():
    bad = 0
    for name, headers, peer, family, remote, lan, want in CASES:
        server.LAN = lan
        got = _Stub(dict(headers), peer, family, remote)._authorized()
        ok = got == want
        bad += not ok
        print(("ok   " if ok else "FAIL ") + name + "  -> " + str(got))
    print("\n%d/%d passed" % (len(CASES) - bad, len(CASES)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
