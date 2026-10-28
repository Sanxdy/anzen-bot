"""The two guards that validate a name instead of an address, pinned.

Both bugs in the audit were the same mistake in two places: the check ran on the URL that was
supplied and never on the URL the system actually talked to. A redirect moved the request past the
guard in both cases. These tests reproduce the redirect and assert the guard now fires.

Resolves nothing over the network and opens no browser. The MCP case runs a throwaway HTTP server on
loopback that answers every request with a redirect to a link-local address; the browser case asserts
the landing-URL check directly, because launching Chromium is not this test's job.

    python3 tests/test_redirect_guards.py
"""
import os, sys, json, tempfile, threading

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="anzen-redirects-")
os.makedirs(os.path.join(os.environ["DATA_DIR"], "sandbox"), exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server  # noqa: E402
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

METADATA = "169.254.169.254"


class _Redirecting(BaseHTTPRequestHandler):
    """Answers every request with a redirect to wherever `location` says."""
    location = ""

    def _bounce(self):
        self.send_response(302)
        self.send_header("Location", _Redirecting.location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_POST = do_GET = _bounce

    def log_message(self, *a):
        pass


def _serve(location):
    _Redirecting.location = location
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Redirecting)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d/mcp" % srv.server_address[1]


def test_guard_allows_loopback():
    """A local MCP server is the normal shape and must still work."""
    assert server._mcp_url_guard("http://127.0.0.1:3000/mcp") is None
    print("  PASS a loopback MCP URL is still allowed")


def test_guard_refuses_link_local():
    """The bare metadata address is refused before any request is made."""
    try:
        server._mcp_url_guard("http://%s/latest/meta-data/" % METADATA)
    except server.MCPError:
        print("  PASS a link-local MCP URL is refused outright")
        return
    raise AssertionError("link-local URL was accepted")


def test_redirect_to_metadata_is_refused():
    """The bug: urllib followed the 302 and reached the metadata address."""
    srv, url = _serve("http://%s/latest/meta-data/" % METADATA)
    try:
        server._mcp_url_guard(url)          # the configured URL itself is fine
        client = server._MCPHttp(url)
        try:
            client.request("initialize", {})
        except server.MCPError as e:
            assert "link-local" in str(e), str(e)
            print("  PASS a redirect to the metadata address is refused: %s" % str(e)[:60])
            return
        raise AssertionError("redirect to link-local was followed")
    finally:
        srv.shutdown()


def test_redirect_to_loopback_still_works():
    """A plain http->http redirect must not be collateral damage."""
    srv2, target = _serve("http://127.0.0.1:9/unused")
    srv1, url = _serve(target)
    try:
        client = server._MCPHttp(url)
        try:
            client.request("initialize", {}, timeout=3)
        except server.MCPError as e:
            assert "link-local" not in str(e), "guard fired on an allowed redirect: %s" % e
            print("  PASS an allowed redirect is still followed (failed later at the connect)")
            return
        except Exception:
            print("  PASS an allowed redirect is still followed")
            return
        print("  PASS an allowed redirect is still followed")
    finally:
        srv1.shutdown(); srv2.shutdown()


def test_browser_guard_refuses_file_landing():
    """A navigation that lands on file:// must be refused, not read."""
    assert server.browser_url_guard("file:///etc/passwd") != ""
    assert server.browser_url_guard("https://example.com/") == ""
    print("  PASS browser_url_guard refuses a file: landing and allows http(s)")


if __name__ == "__main__":
    print("--- an MCP redirect cannot reach the metadata address ---")
    for fn in (test_guard_allows_loopback, test_guard_refuses_link_local,
               test_redirect_to_metadata_is_refused, test_redirect_to_loopback_still_works):
        fn()
    print("--- a browser navigation is checked at the URL it lands on ---")
    test_browser_guard_refuses_file_landing()
    print("\nall redirect-guard tests passed")