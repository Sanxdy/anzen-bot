#!/usr/bin/env python3
"""A tiny MCP server, used only by the tests.

Enough of the protocol to prove the client really speaks it, in all three transports a real server
may use: stdio, Streamable HTTP (replying both as JSON and as an SSE stream) and the older HTTP+SSE
transport. Stdlib only, like the app it is testing.

  python3 mcp_stub.py --stdio
  python3 mcp_stub.py --http PORT [--sse]

`--http` serves Streamable HTTP; `--sse` serves the older HTTP+SSE transport on the same port.
"""
import base64, json, sys, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

TOOLS = [
    {"name": "echo", "description": "Echo the text back.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "add", "description": "Add two numbers.",
     "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                     "required": ["a", "b"]}},
    {"name": "boom", "description": "Always fails.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pic", "description": "Return an image.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "no_schema", "description": "A tool that declares no input schema at all."},
]
PNG = base64.b64encode(b"FAKEPNG-stand-in-for-an-image").decode()


def handle(msg):
    """One JSON-RPC message -> one reply, or None when it is a notification."""
    if not isinstance(msg, dict) or "id" not in msg: return None
    rid, method, p = msg["id"], msg.get("method"), (msg.get("params") or {})
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": p.get("protocolVersion") or "2025-06-18",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "stub-mcp", "version": "1.2.3"}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name, a = p.get("name"), (p.get("arguments") or {})
        if name == "echo":
            return {"jsonrpc": "2.0", "id": rid,
                    "result": {"content": [{"type": "text", "text": "echo: " + str(a.get("text"))}]}}
        if name == "add":
            try: total = int(a.get("a", 0)) + int(a.get("b", 0))
            except (TypeError, ValueError): total = 0
            return {"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": str(total)}]}}
        if name == "boom":
            return {"jsonrpc": "2.0", "id": rid,
                    "result": {"content": [{"type": "text", "text": "it broke"}], "isError": True}}
        if name == "pic":
            return {"jsonrpc": "2.0", "id": rid,
                    "result": {"content": [{"type": "image", "data": PNG, "mimeType": "image/png"}]}}
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "unknown tool " + str(name)}}
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "no such method " + str(method)}}


def stdio():
    """Newline-delimited JSON-RPC on stdin/stdout, which is the local transport."""
    for line in sys.stdin:
        line = line.strip()
        if not line: continue
        try: msg = json.loads(line)
        except ValueError: continue
        reply = handle(msg)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n"); sys.stdout.flush()


class Http(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    streams = []          # the open HTTP+SSE streams, for the legacy transport

    def log_message(self, *a): pass

    def _read(self):
        try: n = int(self.headers.get("Content-Length") or 0)
        except ValueError: n = 0
        try: return json.loads(self.rfile.read(n) or b"{}")
        except ValueError: return {}

    def _send(self, code, body=b"", ctype="application/json", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body: self.wfile.write(body)

    def do_GET(self):
        """The legacy transport's long-lived stream."""
        if not self.sse: return self._send(405, b'{"error":"GET not supported"}')
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.wfile.write(b"event: endpoint\ndata: /messages?sessionId=stub\n\n"); self.wfile.flush()
        q = []
        Http.streams.append(q)
        try:
            while True:
                while q:
                    self.wfile.write(("event: message\ndata: %s\n\n" % q.pop(0)).encode()); self.wfile.flush()
                time.sleep(0.02)
        except Exception:
            pass
        finally:
            if q in Http.streams: Http.streams.remove(q)

    def do_POST(self):
        path = urlparse(self.path).path
        msg = self._read()
        reply = handle(msg)
        if self.sse:
            # The legacy transport: acknowledge, and deliver the reply on the GET stream.
            if path != "/messages": return self._send(404, b'{"error":"no such path"}')
            if reply is not None:
                for q in Http.streams: q.append(json.dumps(reply))
            return self._send(202, b"")
        # Streamable HTTP. A tool call answers as an SSE stream; the handshake answers as plain JSON,
        # so both reply shapes the spec allows are exercised.
        extra = {}
        if (msg or {}).get("method") == "initialize": extra["Mcp-Session-Id"] = "stub-session"
        if reply is None: return self._send(202, b"", extra=extra)
        if (msg or {}).get("method") == "tools/call":
            body = ("event: message\ndata: %s\n\n" % json.dumps(reply)).encode()
            return self._send(200, body, "text/event-stream", extra)
        return self._send(200, json.dumps(reply).encode(), "application/json", extra)


def serve(port, sse):
    Http.sse = sse
    srv = ThreadingHTTPServer(("127.0.0.1", port), Http)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    if "--stdio" in sys.argv: stdio()
    else:
        port = int(sys.argv[sys.argv.index("--http") + 1]) if "--http" in sys.argv else 0
        srv = serve(port, "--sse" in sys.argv)
        print(srv.server_address[1], flush=True)
        threading.Event().wait()
