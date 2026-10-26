"""Does `human_input`'s click actually reach the page? Test the method directly, on a real https page.

Everything above the method looks correct — the route answers ok, `human_on` passes — so the doubt is
the click itself. This page records the coordinates of any click in its title, and it is served over
https from a local server so the URL guard allows it.
"""
import json, os, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
os.environ["DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, "/opt/anzen-bot")
import server as S

HTML = """<!doctype html><html><body style="margin:0">
<div style="position:fixed;inset:0;background:#eef">
  <a id="go" href="javascript:void(0)" style="position:absolute;left:40%;top:40%;width:20%;height:20%;
     display:block;background:#08f;color:#fff;font-size:20px">GO</a>
</div>
<script>
document.addEventListener('click', e => {
  document.title = 'clicked ' + Math.round(e.clientX) + ',' + Math.round(e.clientY) +
                   ' on ' + (e.target.id || e.target.tagName);
}, true);
</script></body></html>"""

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = HTML if self.path == "/" else "<html><title>landed</title><body>landed</body></html>"
        b = body.encode()
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass

srv = ThreadingHTTPServer(("127.0.0.1", 8123), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()

S.BROWSER.start(); time.sleep(1)

PASS = FAIL = 0
def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print("  PASS " + name)
    else:    FAIL += 1; print("  FAIL " + name + (("  -> " + str(extra)[:220]) if extra else ""))

out = S.BROWSER.call("open", url="http://127.0.0.1:8123/", timeout=60, _owner="tester")
print("open:", str(out)[:110])
ok("the test page opened", "127.0.0.1:8123" in str(out), out)

S.BROWSER.call("take", timeout=10, _owner="tester", _human=True)
ok("take succeeded", S.BROWSER.human_on("tester"), S.BROWSER.humans)

geo = S.BROWSER.call("eval", timeout=30, _owner="tester", _human=True,
                     expression="JSON.stringify({w:innerWidth,h:innerHeight})")
print("page viewport:", geo)

r = S.BROWSER.call("human_input", timeout=30, _owner="tester", _human=True,
                   kind="click", fx=0.5, fy=0.5)
print("click result:", repr(r))
time.sleep(1.5)
title = S.BROWSER.call("eval", timeout=30, _owner="tester", _human=True, expression="document.title")
print("title after click:", title)
ok("the click reached the page", "clicked" in str(title), title)
ok("it landed on the link", "on go" in str(title).lower(), title)
# now point the same link at a real page and click again: this time the navigation is the evidence
S.BROWSER.call("eval", timeout=30, _owner="tester", _human=True,
               expression="document.getElementById('go').href='/landed'")
S.BROWSER.call("human_input", timeout=30, _owner="tester", _human=True, kind="click", fx=0.5, fy=0.5)
time.sleep(1.5)

url_now = S.BROWSER.call("eval", timeout=30, _owner="tester", _human=True, expression="location.href")
print("url after click:", url_now)
url_now = S.BROWSER.call("eval", timeout=30, _owner="tester", _human=True, expression="location.href")
print("url after the second click:", url_now)
ok("the link navigated", "landed" in str(url_now), url_now)

print("\n%d passed, %d failed" % (PASS, FAIL))
srv.shutdown()
sys.exit(1 if FAIL else 0)
