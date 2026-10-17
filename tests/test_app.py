#!/usr/bin/env python3
"""End-to-end checks for Anzen-bot (Playwright, headless Chromium).

Runs against BASE (default the public URL) and exits non-zero on any failure.
Usage:  BASE=https://... .venv/bin/python tests/test_app.py
"""
import os, sys, json, time, socket, re, shutil, http.server, threading
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

BASE = os.environ.get("BASE", "http://127.0.0.1:8092/").rstrip("/") + "/"
# The data root the *server under test* reads. Set ANZEN_DATA_DIR when the suite runs against a
# server started with DATA_DIR=<somewhere else> — otherwise the restore checks below would hand the
# real repo file back while the server kept its own copy, and the comparison would be meaningless.
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DATA = os.environ.get("ANZEN_DATA_DIR", os.path.join(ROOT, "data"))
SANDBOX = os.environ.get("ANZEN_SANDBOX_DIR", os.path.join(ROOT, "sandbox"))
PASS = []; FAIL = []
def check(name, ok, extra=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + (f"  {extra}" if extra and not ok else ""))
def accept_once(d):
    """Answer a dialog. Two `pg.on("dialog", ...)` handlers can be live at once (each `on` adds a
    listener), and the second accept raises 'already handled' — a traceback that buries the run's real
    output. Whichever handler Playwright reaches first answers it; the rest stay quiet."""
    try: d.accept()
    except Exception: pass

class _CDPStub(http.server.BaseHTTPRequestHandler):
    """Stands in for ZenPilot's debug port: one profile (a webview target) and one devtools page,
    which is exactly the shape the real app exposes on /json/list."""
    def do_GET(self):
        body = json.dumps([
            {"id": "w1", "type": "webview", "url": "https://gemini.google.com/app", "title": "Gemini"},
            {"id": "d1", "type": "page", "url": "devtools://devtools/bundled/devtools_app.html", "title": "DevTools"},
        ]).encode() if self.path.startswith("/json/list") else b"{}"
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass

def png1x1():
    """A real one-pixel PNG, so the logo checks upload something a browser can actually decode
    rather than a header the server would take on trust."""
    import zlib, struct
    def chunk(t, d):
        body = t + d
        return struct.pack(">I", len(d)) + body + struct.pack(">I", zlib.crc32(body) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
            + chunk(b"IEND", b""))

def png_blob(n=256, bg=(255, 255, 255), fg=(230, 126, 34)):
    """A plain background with a centred subject — the shape the image model returns for a face.
    A flat single-colour image is the wrong fixture: the engine keys out whatever colour all four
    corners agree on, so a uniform picture would be erased entirely instead of becoming a face."""
    import zlib, struct
    cx = cy = n / 2.0; rad = n * 0.30
    rows = b"".join(b"\x00" + b"".join(bytes(fg if (x - cx) ** 2 + (y - cy) ** 2 <= rad * rad else bg)
                                      for x in range(n)) for y in range(n))
    def chunk(t, d):
        body = t + d
        return struct.pack(">I", len(d)) + body + struct.pack(">I", zlib.crc32(body) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 6))
            + chunk(b"IEND", b""))

def raw_get(url, origin=None, host=None, path_as_is=False, headers=None):
    """One HTTP/1.1 GET over a raw socket, so the request line is sent exactly as written
    (`..` included) and Origin/Host can be forged the way a browser or an attacker would.
    `headers` adds any others — the token a phone presents, say — without the browser's own
    Origin or cookie policy getting in the way."""
    u = urlparse(url); path = u.path + (("?" + u.query) if u.query else "")
    if not path_as_is: path = os.path.normpath(path) or "/"
    req = ("GET " + path + " HTTP/1.1\r\nHost: " + (host or u.netloc) + "\r\n"
           + (("Origin: " + origin + "\r\n") if origin else "")
           + "".join(f"{k}: {v}\r\n" for k, v in (headers or {}).items())
           + "Connection: close\r\n\r\n")
    s = socket.create_connection((u.hostname, u.port or 80), timeout=10)
    try:
        s.sendall(req.encode()); buf = b""
        while True:
            c = s.recv(65536)
            if not c: break
            buf += c
            if len(buf) > 200000: break
    finally:
        s.close()
    head, _, body = buf.partition(b"\r\n\r\n")
    try: code = int(head.split(b" ")[1])
    except Exception: code = 0
    return code, body.decode("utf-8", "replace")

def raw_try(url, **kw):
    """raw_get, but a refused connection comes back as None instead of raising. A port that is not
    listening and a port that answers 403 are both "you cannot come in"; the LAN checks below want
    to tell them apart, so the closed case has to be a value and not a traceback."""
    try: return raw_get(url, **kw)
    except OSError: return None

def main():
    with sync_playwright() as p:
        br = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = br.new_context(viewport={"width": 1360, "height": 900})
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: errors.append("console:" + m.text) if m.type == "error" else None)
        # Every response that was not a success, with its URL: a console "404 (Not Found)" names no
        # resource, and a failed check has to say *what* failed. Reported alongside the JS errors.
        badresp = []
        pg.on("response", lambda r: badresp.append("%d %s" % (r.status, r.url)) if r.status >= 400 else None)

        def js_errs():
            """Console errors that are the app misbehaving. app.js reports a dropped turn stream with
            `console.error("turn failed:")` on purpose — and this suite reloads the page mid-turn,
            because a reload is how reopening a chat is tested. That abort is the test's, not a defect
            in the code path under test; a real error in it arrives as a `pageerror` or its own line."""
            return [e for e in errors if "turn failed:" not in e]

        pg.goto(BASE, wait_until="load"); pg.wait_for_timeout(1200)

        # ---- 0. clean test artifacts from previous runs (idempotent) ----
        def sweep():
            cfg = pg.evaluate("async()=>await (await fetch('/api/config')).json()")
            for b in cfg["bots"]:
                if b["id"].startswith(("designer", "e2e-")):
                    pg.evaluate("async(id)=>{await fetch('/api/bot/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})})}", b["id"])
            for c in cfg["channels"]:
                if c["id"].startswith("e2e-") or c["name"] == "Marketing":
                    pg.evaluate("async(id)=>{await fetch('/api/channel/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})})}", c["id"])
        sweep()
        pg.reload(wait_until="load"); pg.wait_for_timeout(1000)

        # ---- 1. shell ----
        check("page loads with title", "Anzen-bot" in pg.title())
        check("no JS errors on boot", not errors, str(errors[:3]))

        # ---- 2. sidebar: channels, each with its bots nested underneath ----
        chans = pg.eval_on_selector_all("#chans > li.group > .bot .nm", "els=>els.map(e=>e.innerText.trim())")
        nested = pg.eval_on_selector_all("#chans .sub .subbot", "els=>els.map(e=>e.dataset.id)")
        check("channels rendered", len(chans) >= 1, str(chans))
        check("company channel is first", chans and "Company" in chans[0], str(chans))
        check("the company nests its members", all(nested[i] == "company/" + b for i, b in enumerate(
            ["producer", "researcher", "builder", "qa", "ops"])), str(nested))
        check("a nested row is a scoped chat id, not a bare bot id",
              all("/" in n for n in nested), str(nested))
        check("the 5 default bots are all reachable in the sidebar",
              all(n in nested for n in ["company/producer", "company/researcher", "company/builder",
                                        "company/qa", "company/ops"]), str(nested))
        # The rows are keyed by bot *id*, but show the bot's *name* — which the user can rename, so
        # read the names from config rather than pinning them here.
        cfg0 = pg.evaluate("async()=>await (await fetch('/api/config')).json()")
        name_of = {b["id"]: b["name"] for b in cfg0["bots"]}
        check("every nested row is labelled with its bot name",
              pg.eval_on_selector_all('#chans .sub .subbot[data-id^="company/"] .nm',
                "els=>els.map(e=>e.innerText.trim().split('\\n')[0])") ==
              [name_of.get(i, i) for i in ["producer", "researcher", "builder", "qa", "ops"]],
              str(pg.eval_on_selector_all('#chans .sub .subbot[data-id^="company/"] .nm',
                "els=>els.map(e=>e.innerText.trim())")))
        check("no bot is listed outside a company when every bot is in one",
              pg.eval_on_selector_all("#bots .subbot", "els=>els.length") == 0,
              str(pg.eval_on_selector_all("#bots .subbot", "els=>els.map(e=>e.dataset.id)")))

        # ---- 2b. the caret folds a company; the choice survives a reload ----
        pg.eval_on_selector("#chans > li.group > .bot .caret", "e=>e.click()"); pg.wait_for_timeout(250)
        check("folding a company hides its bots", not pg.is_visible("#chans .sub .subbot"))
        pg.reload(wait_until="load"); pg.wait_for_timeout(900)
        check("the fold survives a reload", not pg.is_visible("#chans .sub .subbot"))
        pg.eval_on_selector("#chans > li.group > .bot .caret", "e=>e.click()"); pg.wait_for_timeout(250)
        check("unfolding brings the bots back", pg.is_visible("#chans .sub .subbot"))

        # ---- 2b3. one click on a company opens it; two clicks fold its team ----
        # The row itself is the control now: one click opens the company (the caret still folds on
        # its own), and a double click folds the team shut — or opens it, if it was folded. The
        # second case is the one that matters: a pair of clicks on a company you were not in has to
        # open it *and* unfold it, so the two clicks are never a no-op.
        COMP = '#chans > li.group:has(> .bot[data-id="company"]) > .bot'
        # Start from a chat that is not this company, so the single click below has to open it. On
        # boot the first company is already the open chat, and a click on the chat you are in is
        # deliberately a no-op — so without this the check below would pass on a click that did
        # nothing at all.
        pg.click('#chans .sub .subbot[data-id="company/producer"]'); pg.wait_for_timeout(400)
        check("the company is not the open chat before the click",
              not pg.eval_on_selector(COMP, "e=>e.classList.contains('sel')"),
              pg.evaluate("()=>{const e=document.querySelector('#chans .bot.sel');return e?e.dataset.id:null}"))
        pg.click(COMP); pg.wait_for_timeout(450)
        check("one click on a company opens it",
              pg.eval_on_selector(COMP, "e=>e.classList.contains('sel')"),
              pg.eval_on_selector(COMP, "e=>e.className"))
        check("one click leaves the team unfolded", pg.is_visible("#chans .sub .subbot"))
        pg.dblclick(COMP); pg.wait_for_timeout(450)
        check("two clicks fold the team", not pg.is_visible("#chans .sub .subbot"))
        check("two clicks leave the company open",
              pg.eval_on_selector(COMP, "e=>e.classList.contains('sel')"),
              pg.eval_on_selector(COMP, "e=>e.className"))
        # Fold it while the company is *not* the open chat, then double-click: it must do both.
        # The team is shut from the double click above, so open it again before reaching for a nested
        # row — a folded team's rows are hidden, and a hidden row cannot be clicked.
        pg.eval_on_selector(COMP + " .caret", "e=>e.click()"); pg.wait_for_timeout(300)
        pg.click('#chans .sub .subbot[data-id="company/producer"]'); pg.wait_for_timeout(400)
        pg.eval_on_selector(COMP + " .caret", "e=>e.click()"); pg.wait_for_timeout(300)
        check("the team is folded before the pair of clicks", not pg.is_visible("#chans .sub .subbot"))
        pg.dblclick(COMP); pg.wait_for_timeout(450)
        check("two clicks on a folded company open it and unfold the team",
              pg.eval_on_selector(COMP, "e=>e.classList.contains('sel')")
              and pg.is_visible("#chans .sub .subbot"),
              pg.eval_on_selector(COMP, "e=>e.className"))

        # ---- 2b4. Clear chat is a new session: the transcript goes, the memory stays ----
        # The one destructive action that must not touch memory, so this drives the real menu and
        # then reads both sides back from the server: transcript empty, memory intact.
        pg.evaluate("""async()=>{
          // a bot's model is rewritten to the default unless the router is known to serve it
          await fetch('/api/models/add',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({model:'e2e/quick-model'})});
          await fetch('/api/bot',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({bot:{id:'e2e-clear',name:'E2E Clear',title:'Teammate',role:'',
              color:'blue',model:'e2e/quick-model'}})});
          await fetch('/api/memory',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({bot:'e2e-clear',text:'# Notes\\n\\n- the project is a video tool\\n'})});
          await fetch('/api/approval_mode',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({session:'e2e-clear',mode:'plan'})});}""")
        clear_stub = ("".join("data: " + json.dumps(ev) + "\n\n" for ev in [
            {"type": "agent_text", "agent": "E2E Clear", "text": "I built the thing."},
            {"type": "final", "text": "I built the thing."}]))
        pg.route("**/api/chat", lambda route: route.fulfill(
            status=200, content_type="text/event-stream", body=clear_stub))
        pg.reload(wait_until="load"); pg.wait_for_timeout(900)
        pg.evaluate("""()=>{const r=document.querySelector('#bots .subbot[data-id="e2e-clear"]');if(r)r.click()}""")
        pg.wait_for_timeout(400)
        # A finished turn is redrawn from the saved history, not left as the streamed cards — that is
        # what gives each message its Edit/Retry index. The /api/chat stub never reaches the server, so
        # the history has to be stubbed too: otherwise the redraw is truthfully empty and there is
        # nothing to clear. The stub goes in only now, so the transcript was empty before the send.
        pg.fill("#input", "build the thing")
        hist_stub = json.dumps({"model": "e2e/quick-model", "messages": [
            {"role": "user", "text": "build the thing", "ts": time.time()},
            {"role": "assistant", "text": "I built the thing.", "ts": time.time()}]})
        pg.route("**/api/history*", lambda route: route.fulfill(
            status=200, content_type="application/json", body=hist_stub))
        pg.eval_on_selector("#btnSend", "e=>e.click()")
        pg.wait_for_timeout(900)
        pg.unroute("**/api/chat"); pg.unroute("**/api/history*")
        check("the chat has a transcript to clear",
              pg.eval_on_selector_all("#msgs .m", "e=>e.length") >= 2,
              str(pg.eval_on_selector_all("#msgs .m", "e=>e.length")))
        # the menu item is on the row, beside Delete, and is offered for a bot chat
        pg.eval_on_selector('#bots .subbot[data-id="e2e-clear"] .kebab', "e=>e.click()")
        pg.wait_for_timeout(250)
        menu_items = pg.eval_on_selector_all("#ctx .it", "els=>els.map(e=>e.innerText.trim())")
        check("the row menu offers Clear chat", "Clear chat" in menu_items, str(menu_items))
        # clicking it asks first, then clears
        def accept_dialog(d): d.accept()
        pg.on("dialog", accept_dialog)
        pg.evaluate("""()=>{const it=[...document.querySelectorAll('#ctx .it')]
          .find(x=>x.innerText.trim()==='Clear chat');it.click()}""")
        pg.wait_for_timeout(900)
        pg.remove_listener("dialog", accept_dialog)
        check("clearing empties the transcript on screen",
              pg.eval_on_selector_all("#msgs .m", "e=>e.length") == 0,
              str(pg.eval_on_selector_all("#msgs .m", "e=>e.length")))
        chist = pg.evaluate("async()=>await (await fetch('/api/history?session=e2e-clear')).json()")
        check("the cleared chat has no messages left on the server",
              chist["messages"] == [], str(chist["messages"])[:200])
        mem = pg.evaluate("async()=>await (await fetch('/api/memory?bot=e2e-clear')).json()")
        check("the bot still remembers, so the next chat knows what this is about",
              "the project is a video tool" in mem["text"], str(mem)[:200])
        check("the chat keeps its own model pick and approval level",
              chist["model"] == "e2e/quick-model" and chist["approval"] == "plan",
              f'{chist["model"]} / {chist["approval"]}')
        # a channel row offers the same item, and it acts on the room
        pg.evaluate("""()=>{const r=document.querySelector('#chans > li.group > .bot[data-id="company"] .kebab');
          if(r)r.click()}""")
        pg.wait_for_timeout(250)
        check("a channel row offers Clear chat too",
              "Clear chat" in pg.eval_on_selector_all("#ctx .it", "els=>els.map(e=>e.innerText.trim())"),
              str(pg.eval_on_selector_all("#ctx .it", "els=>els.map(e=>e.innerText.trim())")))
        pg.evaluate("()=>document.body.click()"); pg.wait_for_timeout(200)   # any click closes the menu
        check("a click elsewhere closes the menu", pg.eval_on_selector_all("#ctx.on", "e=>e.length") == 0)
        # leave nothing behind: the bot, its transcript, the memory file this test wrote, the model
        pg.evaluate("""async()=>{
          await fetch('/api/bot/delete',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({id:'e2e-clear'})});
          await fetch('/api/memory',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({bot:'e2e-clear',text:''})});
          await fetch('/api/models/remove',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({model:'e2e/quick-model'})});}""")
        pg.reload(wait_until="load"); pg.wait_for_timeout(800)

        # ---- 2b2. the custom controls are reachable and operable from the keyboard ----
        check("a sidebar row is keyboard focusable",
              pg.eval_on_selector('#chans .sub .subbot', "e=>e.tabIndex") == 0)
        pg.eval_on_selector_all("#chans .sub .subbot", "els=>{const b=els.find(x=>x.dataset.id==='company/qa');b.focus()}")
        pg.keyboard.press("Enter"); pg.wait_for_timeout(500)
        check("Enter on a focused row opens that chat",
              "QA" in pg.eval_on_selector("#hName", "e=>e.innerText"),
              pg.eval_on_selector("#hName", "e=>e.innerText"))
        pg.eval_on_selector_all("#chans .sub .subbot", "els=>{const b=els.find(x=>x.dataset.id==='company/producer');b.click()}")
        pg.wait_for_timeout(400)

        # ---- 2c. clicking a nested row opens that bot's chat *inside* that company ----
        hist = []
        pg.on("request", lambda r: hist.append(r.url) if "/api/history" in r.url else None)
        # Move off the nested row first: the keyboard check above already opened it, and clicking the
        # chat you are already in is deliberately a no-op — so without this the click below would ask
        # for nothing and the check would pass on a request that never had to happen.
        pg.click(COMP); pg.wait_for_timeout(500)
        hist.clear()
        pg.eval_on_selector_all("#chans .sub .subbot", "els=>{const b=els.find(x=>x.dataset.id==='company/producer');b.click()}")
        pg.wait_for_timeout(600)
        check("a nested row opens a scoped chat",
              any("session=company%2Fproducer" in u or "session=company/producer" in u for u in hist), str(hist[-2:]))
        check("the header names the bot", name_of.get("producer", "producer") in pg.eval_on_selector("#hName", "e=>e.textContent"))
        check("the header does not claim the room", "Room" not in pg.eval_on_selector("#hName", "e=>e.textContent"))
        check("the nested row is highlighted", pg.eval_on_selector("#chans .sub .subbot.sel", "e=>e.dataset.id") == "company/producer")

        # ---- 2d. clicking the chat you are already in does nothing ----
        # The transcript scrolls smoothly, so a needless re-render replays as a visible top-to-bottom
        # scroll over a chat that never left. Re-clicking the open row must neither re-fetch the
        # history nor move the transcript, and must leave what is on screen untouched.
        pg.click(COMP); pg.wait_for_timeout(400)                    # open the company
        # Opening a chat scrolls the transcript to the bottom *smoothly*, so wait for that animation to
        # finish before measuring. Otherwise it lands inside the measurement window and reads as the app
        # moving the transcript on a click that did nothing.
        prev = -1
        for _ in range(30):
            cur = pg.evaluate("()=>document.querySelector('#msgs').scrollTop")
            if cur == prev: break
            prev = cur; pg.wait_for_timeout(100)
        before = pg.evaluate("""()=>{const m=document.querySelector('#msgs');
          // Pin the transcript to instant scrolling while it is measured, so nothing this block does can
          // animate. Restored at the end of the block.
          m.style.scrollBehavior='auto';
          for(let i=0;i<40;i++){const d=document.createElement('div');d.className='m bot';d.textContent='filler '+i;m.appendChild(d);}
          m.scrollTop=0; return m.scrollTop;}""")
        hist.clear()
        pg.click(COMP); pg.wait_for_timeout(500)                    # click the same, already-open row
        after = pg.evaluate("()=>document.querySelector('#msgs').scrollTop")
        check("re-clicking the open channel fires no history request",
              not any("/api/history" in u for u in hist), str(hist[-2:]))
        check("re-clicking the open channel does not scroll the transcript", after == before, f"{before}->{after}")
        check("re-clicking the open channel does not re-render it",
              pg.evaluate("()=>document.querySelector('#msgs').textContent.includes('filler 39')"))
        pg.evaluate("()=>{document.querySelector('#msgs').style.scrollBehavior=''}")

        # ---- 3. dock mascot + poke ----
        check("dock mascot canvas present", pg.eval_on_selector("#dockMochi", "e=>e.tagName") == "CANVAS")
        st0 = pg.eval_on_selector("#hStatus", "e=>e.textContent")
        pg.eval_on_selector("#dock", "e=>e.click()"); pg.wait_for_timeout(400)
        st1 = pg.eval_on_selector("#hStatus", "e=>e.textContent")
        check("dock poke does not change the state", st0 == st1, f"{st0}->{st1}")

        # ---- 4. settings: 14 tabs, each renders ----
        pg.eval_on_selector("#btnSettings", "e=>e.click()"); pg.wait_for_timeout(500)
        tabs = pg.eval_on_selector_all("#setTabs .mtab .lbl", "els=>els.map(e=>e.textContent)")
        check("settings has 14 tabs", len(tabs) == 14, str(tabs))
        check("settings tabs cover the full surface",
              all(t in tabs for t in ["General","AI model","Browser","Phone","Bots","Rooms",
                                      "Connected apps","Skills","Plugins","Memory","Approvals",
                                      "Voice","Appearance","Help"]), str(tabs))
        err0 = len(errors)
        for i in range(len(tabs)):
            pg.eval_on_selector_all("#setTabs .mtab", f"els=>els[{i}].click()"); pg.wait_for_timeout(180)
        check("every settings tab renders with no JS error", len(errors) == err0, str(errors[err0:]))

        # ---- 4a. Help documents every feature, and the approval levels in full ----
        pg.eval_on_selector_all("#setTabs .mtab", f"els=>els[{tabs.index('Help')}].click()"); pg.wait_for_timeout(300)
        htxt = pg.eval_on_selector("#setPanel", "e=>e.innerText")
        check("Help explains every settings area",
              all(w in htxt for w in ["Bots","Rooms","AI model","Browser","Phone","Approvals",
                                      "Memory","Skills","Plugins","Connected apps","Voice",
                                      "Appearance","General"]), htxt[:200])
        # each level, its value, and its honest access detail are rendered from the one list
        lvls = pg.evaluate("""()=>[...document.querySelectorAll('#setPanel .help .lvl')].map(d=>({
              name:(d.querySelector('.hd b')||{}).textContent||'',
              tag:(d.querySelector('.tag')||{}).textContent||'',
              acc:((d.querySelector('.acc')||{}).textContent||'').length}))""")
        check("Help lists all five approval levels",
              [l["name"] for l in lvls] == ["Plan only","Ask for approval","Auto-accept edits","Approve routine","Full access"], str(lvls))
        check("every approval level carries a real access description",
              len(lvls) == 5 and all(l["acc"] > 40 for l in lvls), str([l["acc"] for l in lvls]))
        check("Help states that only risky shell commands are gated today",
              "risky shell commands" in htxt, htxt[:0])
        check("Help covers the plan-approve flow", "Approve plan and run it" in htxt)
        check("Help carries no emoji",
              len(pg.evaluate("()=>{const r=document.querySelector('#setPanel').innerText.match(/[\\u{1F000}-\\u{1FAFF}\\u{2600}-\\u{27BF}\\u{FE0F}]/gu);return r||[]}")) == 0)
        # the sidebar Help button opens the same tab
        pg.eval_on_selector("#sClose", "e=>e.click()"); pg.wait_for_timeout(300)
        pg.eval_on_selector("#btnHelp", "e=>e.click()"); pg.wait_for_timeout(400)
        check("the sidebar Help button opens the Help tab",
              pg.eval_on_selector("#tab-help", "e=>e.getAttribute('aria-selected')") == "true")
        # leave the panel open on the Help tab, which is where the tab sweep left it

        # ---- 4b. labels are plain text and always visible (an icon alone is not a label) ----
        vis = pg.eval_on_selector_all("#setTabs .mtab .lbl",
              "els=>els.map(e=>({t:e.textContent.trim(),w:Math.round(e.getBoundingClientRect().width),h:Math.round(e.getBoundingClientRect().height)}))")
        check("every settings tab shows a visible text label", all(v["t"] and v["w"] > 0 and v["h"] > 0 for v in vis), str(vis))
        emo = pg.evaluate("()=>{const r=document.querySelector('#setTabs').innerText.match(/[\\u{1F000}-\\u{1FAFF}\\u{2600}-\\u{27BF}\\u{FE0F}]/gu);return r||[]}")
        check("settings rail carries no emoji", len(emo) == 0, str(emo))
        pg.set_viewport_size({"width": 390, "height": 844}); pg.wait_for_timeout(500)
        vis2 = pg.eval_on_selector_all("#setTabs .mtab .lbl",
               "els=>els.map(e=>({t:e.textContent.trim(),w:Math.round(e.getBoundingClientRect().width)}))")
        check("labels stay visible on mobile", all(v["t"] and v["w"] > 0 for v in vis2), str(vis2))
        pg.set_viewport_size({"width": 1360, "height": 900}); pg.wait_for_timeout(400)
        # ---- 4c. the rail is grouped, and every section is reachable without guessing ----
        # Fourteen sections in one flat column is a list you have to read top to bottom; the group
        # headings break it into what the app runs on, what is in it, and how it behaves. A heading is
        # a label, not a thing you click, so it must not take a tab stop — and the rail must not hide
        # its own last entries below the fold at the size the dialog actually opens at.
        grps = pg.eval_on_selector_all("#setTabs .mgrp", "els=>els.map(e=>e.textContent.trim())")
        check("the rail is grouped", grps == ["Set up", "Your workspace", "Behaviour"], str(grps))
        check("a group heading is a label, not a control",
              pg.eval_on_selector_all("#setTabs .mgrp",
                "els=>els.every(e=>e.getAttribute('aria-hidden')==='true'&&e.tabIndex<0&&e.tagName!=='BUTTON')"))
        check("the rail is announced as a tablist of tabs",
              pg.evaluate("""()=>{const r=document.querySelector('#setTabs');
                const t=[...r.querySelectorAll('.mtab')];
                return r.getAttribute('role')==='tablist'&&t.every(x=>x.getAttribute('role')==='tab'
                  && x.getAttribute('aria-controls')==='setPanel'
                  && x.getAttribute('aria-selected')===(x.classList.contains('on')?'true':'false'))}"""))
        fit = pg.evaluate("""()=>{const r=document.querySelector('#setTabs');
          const last=r.querySelector('.mtab:last-of-type').getBoundingClientRect();
          return {below:Math.round(last.bottom-r.getBoundingClientRect().bottom), h:Math.round(last.height)}}""")
        check("the last section is on screen without scrolling the rail",
              fit["h"] > 0 and fit["below"] <= 0, str(fit))

        # ---- 5. create a bot ----
        pg.eval_on_selector("#tab-bots", "e=>e.click()"); pg.wait_for_timeout(250)  # Bots
        pg.eval_on_selector("#setPanel .btn.pri", "e=>e.click()"); pg.wait_for_timeout(300)          # New bot
        pg.eval_on_selector_all("#setPanel input", "els=>{els[0].value='Designer';els[0].dispatchEvent(new Event('change'));els[1].value='Design';els[1].dispatchEvent(new Event('change'));}")
        pg.eval_on_selector("#setPanel .btn.pri", "e=>e.click()"); pg.wait_for_timeout(1000)         # Save bot
        pg.eval_on_selector("#sClose", "e=>e.click()"); pg.wait_for_timeout(400)
        bots2 = pg.eval_on_selector_all("#bots .subbot .nm", "els=>els.map(e=>e.innerText.trim())")
        check("a new bot with no company appears in the sidebar", any("Designer" in b for b in bots2), str(bots2))
        check("the no-company group is shown when it has bots",
              pg.is_visible("#botsLabel") and pg.is_visible("#bots .subbot"))
        check("a new bot is not silently dropped into a company",
              pg.eval_on_selector_all("#chans .sub .subbot", "els=>els.map(e=>e.dataset.id).includes('company/designer')") is False)

        # ---- 6. bot context menu (pin / duplicate / delete) ----
        pg.eval_on_selector_all("#bots .subbot", "els=>{const b=els.find(x=>x.dataset.id==='designer'); b.querySelector('.kebab').click();}")
        pg.wait_for_timeout(300)
        check("context menu opens on kebab", pg.eval_on_selector("#ctx", "e=>e.classList.contains('on')"))
        pg.eval_on_selector_all("#ctx .it", "els=>{const it=els.find(x=>x.textContent.includes('Duplicate')); it.click();}")
        pg.wait_for_timeout(900)
        bots3 = pg.eval_on_selector_all("#bots .subbot .nm", "els=>els.map(e=>e.innerText.trim())")
        check("duplicate creates a copy", any("copy" in b for b in bots3), str(bots3))

        # ---- 7. create a channel ----
        pg.eval_on_selector("#addChannel", "e=>e.click()"); pg.wait_for_timeout(400)
        pg.eval_on_selector_all("#setPanel input", "els=>{els[0].value='Marketing';els[0].dispatchEvent(new Event('change'));}")
        pg.eval_on_selector("#setPanel .btn.pri", "e=>e.click()"); pg.wait_for_timeout(900)
        pg.eval_on_selector("#sClose", "e=>e.click()"); pg.wait_for_timeout(300)
        chans2 = pg.eval_on_selector_all("#chans > li.group > .bot .nm", "els=>els.map(e=>e.innerText.trim())")
        check("new channel appears in the sidebar", any("Marketing" in c for c in chans2), str(chans2))

        # ---- 8. appearance themes ----
        # The suite must hand the user's own appearance back, so snapshot it before touching it —
        # and restore it here rather than later, or every section after this would be measuring a
        # theme the suite chose.
        appear8 = pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.settings.appearance}")
        pg.eval_on_selector("#btnSettings", "e=>e.click()"); pg.wait_for_timeout(400)
        pg.eval_on_selector("#tab-appearance", "e=>e.click()"); pg.wait_for_timeout(300)  # Appearance
        opts = pg.eval_on_selector_all("#themeSel option", "els=>els.map(e=>e.value)")
        check("the theme picker offers the whole set of packages",
              all(t in opts for t in ["dark", "light", "glass", "ainative", "luxe", "eink", "terminal", "mono"]),
              str(opts))
        pick_theme = "v=>{const s=document.querySelector('#themeSel');s.value=v;s.dispatchEvent(new Event('change'))}"
        seen = {}
        for tid in ["dark", "light", "glass", "ainative", "luxe", "eink", "terminal", "mono"]:
            pg.evaluate(pick_theme, tid); pg.wait_for_timeout(320)
            seen[tid] = pg.evaluate("()=>{const s=getComputedStyle(document.body);return [s.getPropertyValue('--bg2').trim(),document.body.dataset.theme,document.body.classList.contains('light')]}")
        check("every theme package paints surfaces of its own", len({v[0] for v in seen.values()}) >= 6, str(seen))
        check("each theme is named on the body, and only the light ones carry the light class",
              all(v[1] == k for k, v in seen.items()) and seen["light"][2] and not seen["dark"][2], str(seen))
        check("no theme overflows the page",
              pg.evaluate("()=>document.documentElement.scrollWidth <= window.innerWidth + 2"))
        # a theme is a saved choice, not a preview: it survives a reload, and it brings its accent
        pg.evaluate(pick_theme, "luxe"); pg.wait_for_timeout(500)
        check("picking a theme is saved",
              pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.settings.appearance.theme}") == "luxe")
        check("a theme adopts its signature accent",
              pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.settings.appearance.accent}") == "#D4AF37")
        pg.reload(wait_until="load"); pg.wait_for_timeout(1200)
        check("the theme survives a reload", pg.evaluate("()=>document.body.dataset.theme") == "luxe")
        pg.eval_on_selector("#btnSettings", "e=>e.click()"); pg.wait_for_timeout(400)
        pg.eval_on_selector("#tab-appearance", "e=>e.click()"); pg.wait_for_timeout(300)
        pg.evaluate("async(a)=>{await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({settings:{appearance:a}})})}", appear8)
        pg.reload(wait_until="load"); pg.wait_for_timeout(1200)
        pg.eval_on_selector("#btnSettings", "e=>e.click()"); pg.wait_for_timeout(400)
        pg.eval_on_selector("#tab-appearance", "e=>e.click()"); pg.wait_for_timeout(300)
        check("the suite hands the user's own appearance back",
              pg.evaluate("()=>document.body.dataset.theme") == (appear8.get("theme") or "dark"),
              str(appear8.get("theme")))

        # ---- 8b. font and text size ----
        # the suite must hand the user's own appearance back, so snapshot it before touching it
        app_before = pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.settings.appearance}")
        labels = pg.eval_on_selector_all("#setPanel label", "els=>els.map(e=>e.innerText)")
        check("appearance offers a font", "FONT" in labels, str(labels))
        check("appearance offers a text size", "FONT SIZE" in labels, str(labels))
        fsel = pg.eval_on_selector_all("#setPanel select", "els=>els.map(s=>({l:(s.closest('.fld').querySelector('label')||{}).innerText,v:s.value,o:[...s.options].map(x=>x.text)}))")
        fsel = {x["l"]: x for x in fsel}
        check("the font picker offers several faces", len(fsel["FONT"]["o"]) >= 4, str(fsel["FONT"]))
        check("the font picker opens on the saved face",
              fsel["FONT"]["v"] == app_before.get("font", "system"), str(fsel["FONT"]))
        check("the size picker offers a range of sizes", len(fsel["FONT SIZE"]["o"]) >= 5, str(fsel["FONT SIZE"]))
        # the saved size is the user's, so read it rather than assuming the default
        check("the size picker opens on the saved size",
              fsel["FONT SIZE"]["v"] == str(app_before.get("font_size")), str(fsel["FONT SIZE"]))

        # changing the size must actually resize text, not just store a number
        probe = """()=>{const px=s=>{const e=document.querySelector(s);return e?+getComputedStyle(e).fontSize.replace('px',''):null};
          return {body:px('body'),msg:px('#msgs .m'),name:px('#chans .bot .nm'),brand:px('.brand b')}}"""
        # the size under test comes from the picker itself, not a hardcoded number: the user's own
        # saved size may already be the floor, and then "smaller than what is saved" has no answer
        pick = "v=>{const s=[...document.querySelectorAll('#setPanel select')].find(x=>(x.closest('.fld').querySelector('label')||{}).innerText==='FONT SIZE');s.value=v;s.dispatchEvent(new Event('change'))}"
        sizes = pg.evaluate("()=>{const s=[...document.querySelectorAll('#setPanel select')].find(x=>(x.closest('.fld').querySelector('label')||{}).innerText==='FONT SIZE');return [...s.options].map(o=>parseFloat(o.value))}")
        lo, hi = min(sizes), max(sizes)
        pg.evaluate(pick, str(lo)); pg.wait_for_timeout(900)
        at_small = pg.evaluate(probe)
        pg.evaluate(pick, str(hi)); pg.wait_for_timeout(900)
        at_big = pg.evaluate(probe)
        check("raising the size grows the base text", at_big["body"] > at_small["body"], f"{at_small['body']} -> {at_big['body']}")
        check("raising the size grows the text around it, not just the base",
              at_big["name"] > at_small["name"] and at_big["brand"] > at_small["brand"],
              f"{at_small['name']}/{at_small['brand']} -> {at_big['name']}/{at_big['brand']}")
        check("the whole interface scales together, keeping the design's proportions",
              abs(at_big["brand"] / at_big["body"] - at_small["brand"] / at_small["body"]) < 0.02,
              f"{at_small['brand']/at_small['body']:.3f} vs {at_big['brand']/at_big['body']:.3f}")
        pg.evaluate(pick, str(lo)); pg.wait_for_timeout(900)
        check("lowering the size shrinks it again", at_small["body"] < at_big["body"], f"{at_big['body']} -> {at_small['body']}")
        check("the size survives a reload",
              pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.settings.appearance.font_size}") == lo)
        pg.reload(wait_until="load"); pg.wait_for_timeout(1200)
        check("the reloaded page is drawn at the saved size", pg.evaluate(probe)["body"] == lo)
        check("no horizontal overflow at the smallest size",
              pg.evaluate("()=>document.documentElement.scrollWidth <= window.innerWidth + 2"))
        pg.eval_on_selector("#btnSettings", "e=>e.click()"); pg.wait_for_timeout(400)
        pg.eval_on_selector_all("#setTabs .mtab", f"els=>els[{tabs.index('Appearance')}].click()"); pg.wait_for_timeout(300)

        # the font picker swaps the typeface, and the choice sticks
        fpick = "v=>{const s=[...document.querySelectorAll('#setPanel select')].find(x=>(x.closest('.fld').querySelector('label')||{}).innerText==='FONT');s.value=v;s.dispatchEvent(new Event('change'))}"
        bodyface = "()=>getComputedStyle(document.body).fontFamily"
        before_face = pg.evaluate(bodyface)
        pg.evaluate(fpick, "serif"); pg.wait_for_timeout(900)
        serif = pg.evaluate(bodyface)
        check("picking a font changes the typeface", "serif" in serif.lower() and serif != before_face, serif)
        check("the whole interface takes the chosen face, not just one panel",
              "serif" in pg.eval_on_selector("#chans .bot .nm", "e=>getComputedStyle(e).fontFamily").lower())
        # a tool call is code, so it keeps its own monospace face whatever the setting says
        check("a code block keeps its monospace face",
              "mono" in pg.evaluate("()=>{const s=document.createElement('div');s.className='m tool';"
                                    "document.querySelector('#msgs').appendChild(s);"
                                    "const f=getComputedStyle(s).fontFamily;s.remove();return f}").lower())
        pg.reload(wait_until="load"); pg.wait_for_timeout(1200)
        check("the font survives a reload",
              pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.settings.appearance.font}") == "serif")
        check("the reloaded page uses the saved font", "serif" in pg.evaluate(bodyface).lower())
        # hand the user's own appearance back
        pg.evaluate("async(a)=>{await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({settings:{appearance:a}})})}", app_before)
        pg.reload(wait_until="load"); pg.wait_for_timeout(1000)
        back = pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.settings.appearance}")
        check("the appearance the suite borrowed is handed back",
              back.get("font") == app_before.get("font") and back.get("font_size") == app_before.get("font_size"),
              f"{app_before} -> {back}")
        # the reload above closed the panel the next section expects to be open
        pg.eval_on_selector("#btnSettings", "e=>e.click()"); pg.wait_for_timeout(400)

        # ---- 9. memory panel saves ----
        # capture producer's real notes first: this test writes to the selected bot's file
        mem_before = pg.evaluate("async()=>{const d=await (await fetch('/api/memory?bot=producer')).json();return d.text}")
        pg.eval_on_selector("#tab-memory", "e=>e.click()"); pg.wait_for_timeout(300)  # Memory
        marker = "# Notes\n- e2e marker " + str(int(time.time() * 1000))
        pg.eval_on_selector("#setPanel textarea", f"e=>{{e.value={json.dumps(marker)};e.dispatchEvent(new Event('change'))}}")
        pg.eval_on_selector("#setPanel .btn.pri", "e=>e.click()"); pg.wait_for_timeout(600)
        check("memory save button responds", "Saved" in pg.eval_on_selector("#setPanel .btn.pri", "e=>e.textContent"))
        saved_mem = pg.evaluate("async()=>{const d=await (await fetch('/api/memory?bot=producer')).json();return d.text}")
        check("memory save round-trips to the file", "e2e marker" in saved_mem)
        pg.evaluate("async(t)=>{await fetch('/api/memory',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({bot:'producer',text:t})})}", mem_before)
        restored = pg.evaluate("async()=>{const d=await (await fetch('/api/memory?bot=producer')).json();return d.text}")
        check("memory test restores the bot's real notes", restored == mem_before)
        check("memory panel explains self-learning", "lessons" in pg.eval_on_selector("#setPanel", "e=>e.innerText"))
        check("chat renders the learned event",
              pg.evaluate("async()=>{const t=await (await fetch('app.js',{cache:'no-store'})).text();return t.includes('\"learned\"')}"))

        # ---- 9b. skills tab toggles a real checkbox and persists ----
        pg.eval_on_selector("#tab-skills", "e=>e.click()"); pg.wait_for_timeout(300)  # Skills
        pg.select_option("#setPanel select", "qa"); pg.wait_for_timeout(250)
        on_before = pg.eval_on_selector_all("#setPanel .sk.on b", "els=>els.map(e=>e.textContent)")
        pg.eval_on_selector("#setPanel .sk", "e=>e.click()"); pg.wait_for_timeout(200)
        on_after = pg.eval_on_selector_all("#setPanel .sk.on b", "els=>els.map(e=>e.textContent)")
        check("skills checkbox toggles on click", on_before != on_after, f"{on_before}->{on_after}")
        pg.eval_on_selector("#setPanel .btn.pri", "e=>e.click()"); pg.wait_for_timeout(600)
        qa_skills = pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return (c.bots.find(b=>b.id==='qa')||{}).skills}")
        check("skills toggle persists to the bot", len(qa_skills) == len(on_after), str(qa_skills))
        # restore qa's original skills
        pg.evaluate("async(s)=>{await fetch('/api/bot',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({bot:{id:'qa',skills:s}})})}", ["testing", "verification"])

        # ---- 9b2. install a skill from a zip, then find it with the filter ----
        import base64, io as _io, zipfile as _zip
        _zbuf = _io.BytesIO()
        with _zip.ZipFile(_zbuf, "w") as z:
            z.writestr("pdf-tools/SKILL.md", "---\nname: PDF Toolkit\ndescription: Extract text and tables from PDFs.\n---\n\nUse pdftotext.\n")
            z.writestr("pdf-tools/scripts/merge.py", "print('merge')\n")
            z.writestr("sheet-wrangler/SKILL.md", "---\nname: Sheet Wrangler\ndescription: Read and write xlsx and csv.\n---\n\nPrefer csv.\n")
        _zb64 = base64.b64encode(_zbuf.getvalue()).decode()
        check("skills tab offers a zip install", "Install from zip" in pg.eval_on_selector("#setPanel", "e=>e.innerText"))
        check("skills tab offers a filter", pg.eval_on_selector_all("#setPanel select", "e=>e.length") >= 2)
        _upload = """async (b64) => {
          const bin = atob(b64), arr = new Uint8Array(bin.length);
          for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
          const dt = new DataTransfer(); dt.items.add(new File([arr], 'skills.zip', { type: 'application/zip' }));
          const inp = document.querySelector('#setPanel input[type=file]');
          inp.files = dt.files; inp.dispatchEvent(new Event('change'));
        }"""
        _installed = ("async()=>{const c=await (await fetch('/api/config')).json();"
                      "return c.skills.filter(s=>s.installed_at).map(s=>s.id).sort()}")
        pg.evaluate(_upload, _zb64); pg.wait_for_timeout(1200)
        # Uploading scans the zip and commits nothing: the picker lists what is inside and waits.
        check("uploading a zip installs nothing on its own", pg.evaluate(_installed) == [], str(pg.evaluate(_installed)))
        check("the picker opens on the uploaded zip", pg.eval_on_selector("#setPanel .zpick", "e=>e.offsetParent !== null"))
        picked = pg.eval_on_selector_all("#setPanel .zpick .sk", "els=>els.map(e=>e.querySelector('b').textContent)")
        check("the picker names every skill the zip holds", sorted(picked) == ["PDF Toolkit", "Sheet Wrangler"], str(picked))
        check("the picker says how many the zip holds",
              "holds 2 skills" in pg.eval_on_selector("#setPanel .zpick .desc", "e=>e.innerText"),
              pg.eval_on_selector("#setPanel .zpick .desc", "e=>e.innerText"))
        check("every skill starts ticked, so 'all' is the default",
              pg.eval_on_selector_all("#setPanel .zpick .sk", "els=>els.every(e=>e.classList.contains('on'))"))
        check("the picker offers install-all, install-selected and cancel",
              pg.eval_on_selector_all("#setPanel .zpick .btn", "els=>els.length") == 3)
        # Untick one and install the rest: only the ticked ones may land.
        pg.evaluate("""()=>{const d=[...document.querySelectorAll('#setPanel .zpick .sk')]
          .find(e=>e.querySelector('b').textContent==='PDF Toolkit'); d.click()}""")
        pg.wait_for_timeout(200)
        check("unticking one updates the count",
              "Install selected (1)" in pg.eval_on_selector_all("#setPanel .zpick .btn", "els=>els[0].textContent"),
              pg.eval_on_selector_all("#setPanel .zpick .btn", "els=>els[0].textContent"))
        pg.eval_on_selector("#setPanel .zpick .btn", "e=>e.click()"); pg.wait_for_timeout(1500)
        after_pick = pg.evaluate(_installed)
        check("install-selected installs only what was ticked", after_pick == ["sheet-wrangler"], str(after_pick))
        check("the picker closes once it has installed", not pg.eval_on_selector("#setPanel .zpick", "e=>e.offsetParent !== null"))
        # Upload again and take the lot.
        pg.evaluate(_upload, _zb64); pg.wait_for_timeout(1200)
        check("a re-upload flags the skill it would replace",
              "replaces installed" in pg.eval_on_selector("#setPanel .zpick", "e=>e.innerText"),
              pg.eval_on_selector("#setPanel .zpick", "e=>e.innerText"))
        pg.evaluate("""()=>{const b=[...document.querySelectorAll('#setPanel .zpick .btn')].find(x=>x.textContent.startsWith('Install all'));b.click()}""")
        pg.wait_for_timeout(1500)
        check("the zip installs every skill it holds",
              pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.skills.filter(s=>s.installed_at).map(s=>s.id).sort().join(',')}")
              == "pdf-toolkit,sheet-wrangler",
              pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.skills.filter(s=>s.installed_at).map(s=>s.id)}"))
        check("an installed skill is marked in the list",
              pg.eval_on_selector_all("#setPanel .sk", "els=>els.some(e=>e.innerText.includes('installed'))"))
        check("the install reports what it did", "Installed 2" in pg.eval_on_selector("#setPanel .desc", "e=>e.innerText"),
              pg.eval_on_selector("#setPanel .desc", "e=>e.innerText"))
        # the search box narrows the list
        all_names = pg.eval_on_selector_all("#setPanel .sk b", "els=>els.map(e=>e.textContent)")
        pg.fill("#setPanel .fldrow input[type=text]", "pdf"); pg.wait_for_timeout(300)
        hit = pg.eval_on_selector_all("#setPanel .sk b", "els=>els.map(e=>e.textContent)")
        check("search narrows the skill list", 0 < len(hit) < len(all_names) and any("PDF" in h for h in hit), str(hit))
        pg.fill("#setPanel .fldrow input[type=text]", "zzz-nothing"); pg.wait_for_timeout(300)
        check("search with no match says so", "No skills match" in pg.eval_on_selector("#setPanel", "e=>e.innerText"))
        pg.fill("#setPanel .fldrow input[type=text]", ""); pg.wait_for_timeout(300)
        # the "recently installed" filter leads with what just arrived
        pg.evaluate("""()=>{const s=[...document.querySelectorAll('#setPanel select')].find(x=>[...x.options].some(o=>o.text==='Recently installed'));
          s.value='recent'; s.dispatchEvent(new Event('change'));}""")
        pg.wait_for_timeout(300)
        recent = pg.eval_on_selector_all("#setPanel .sk b", "els=>els.map(e=>e.textContent)")
        check("recently installed leads with the new skills",
              recent and all(any(k in r for k in ("PDF", "Sheet")) for r in recent), str(recent))
        pg.evaluate("""()=>{const s=[...document.querySelectorAll('#setPanel select')].find(x=>[...x.options].some(o=>o.text==='Built-in'));
          s.value='builtin'; s.dispatchEvent(new Event('change'));}""")
        pg.wait_for_timeout(300)
        check("the built-in filter hides installed skills",
              not pg.eval_on_selector_all("#setPanel .sk", "els=>els.some(e=>e.innerText.includes('installed'))"))
        # remove takes it back out
        pg.evaluate("""()=>{const s=[...document.querySelectorAll('#setPanel select')].find(x=>[...x.options].some(o=>o.text==='Recently installed'));
          s.value='recent'; s.dispatchEvent(new Event('change'));}""")
        pg.wait_for_timeout(300)
        pg.on("dialog", accept_once)
        first = pg.eval_on_selector("#setPanel .sk b", "e=>e.textContent")
        pg.eval_on_selector("#setPanel .sk .btn", "e=>e.click()"); pg.wait_for_timeout(1200)
        left = pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.skills.filter(s=>s.installed_at).map(s=>s.name)}")
        check("removing an installed skill takes that one out of the catalog",
              len(left) == 1 and first not in left, f"removed {first}, left {left}")
        check("the removed skill's folder is gone on disk",
              not os.path.isdir(os.path.join(DATA, "skills",
                                             re.sub(r"[^a-z0-9]+", "-", first.lower()).strip("-"))))
        # and the second one too, so the suite leaves no installed skills behind
        pg.eval_on_selector("#setPanel .sk .btn", "e=>e.click()"); pg.wait_for_timeout(1200)
        check("the suite leaves no installed skills behind",
              pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.skills.filter(s=>s.installed_at).length}") == 0)

        # ---- 9b3. a zip bigger than the POST body cap uploads instead of hanging ----
        # The body cap used to sit below the zip cap, so a multi-megabyte zip was cut off mid-read
        # and the socket reset; the browser then saw a failed request with no reply and the button
        # sat on "Reading…" for ever. A real zip of a few megabytes must go through, and a request
        # that does fail must put the button back with a message.
        import os as _os
        _big = _io.BytesIO()
        with _zip.ZipFile(_big, "w", _zip.ZIP_DEFLATED) as z:
            z.writestr("big-skill/SKILL.md",
                       "---\nname: Big Skill\ndescription: A skill whose zip is larger than one megabyte.\n---\n\nBig.\n")
            z.writestr("big-skill/data/blob.bin", _os.urandom(2_000_000))
        _bb64 = base64.b64encode(_big.getvalue()).decode()
        pg.evaluate(_upload, _bb64)
        try:
            pg.wait_for_selector("#setPanel .zpick .sk", timeout=20000, state="attached")
            _opened = True
        except Exception:
            _opened = False
        check("a multi-megabyte zip finishes uploading and opens the picker", _opened)
        check("the upload button is restored, not left reading for ever",
              pg.eval_on_selector("#setPanel .btn.ghost.sm", "e=>e.textContent").strip() == "Install from zip",
              pg.eval_on_selector("#setPanel .btn.ghost.sm", "e=>e.textContent"))
        check("the picker names the skill inside the large zip",
              pg.eval_on_selector_all("#setPanel .zpick .sk b", "els=>els.map(e=>e.textContent)") == ["Big Skill"])
        pg.eval_on_selector("#setPanel .zpick .btn.pri", "e=>e.click()"); pg.wait_for_timeout(2500)
        check("the large zip installs",
              pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.skills.filter(s=>s.installed_at).map(s=>s.id)}") == ["big-skill"])
        pg.on("dialog", accept_once)
        pg.evaluate("""()=>{const s=[...document.querySelectorAll('#setPanel select')].find(x=>[...x.options].some(o=>o.text==='Recently installed'));
          s.value='recent'; s.dispatchEvent(new Event('change'));}""")
        pg.wait_for_timeout(300)
        pg.eval_on_selector("#setPanel .sk .btn", "e=>e.click()"); pg.wait_for_timeout(1200)
        check("the large-zip probe is removed again, leaving the catalog as it was",
              pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.skills.filter(s=>s.installed_at).length}") == 0)
        # A request that fails outright must not strand the button — stub fetch to reject once.
        pg.evaluate("""()=>{window.__pf = window.fetch;
          window.fetch = (u, o) => String(u).includes('/api/skills/scan')
            ? Promise.reject(new TypeError('Failed to fetch')) : window.__pf(u, o);}""")
        pg.evaluate(_upload, _bb64); pg.wait_for_timeout(1500)
        check("a failed upload restores the button instead of hanging",
              pg.eval_on_selector("#setPanel .btn.ghost.sm", "e=>e.textContent").strip() == "Install from zip",
              pg.eval_on_selector("#setPanel .btn.ghost.sm", "e=>e.textContent"))
        check("and the panel says the upload failed",
              "Could not upload" in pg.eval_on_selector("#setPanel .desc", "e=>e.innerText"),
              pg.eval_on_selector("#setPanel .desc", "e=>e.innerText")[:120])
        pg.evaluate("()=>{window.fetch = window.__pf}")

        # ---- 9c. appearance: the accent previews, saves, and survives a later change ----
        appear_before = pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.settings.appearance}")
        pg.eval_on_selector_all("#setTabs .mtab", f"els=>els[{tabs.index('Appearance')}].click()"); pg.wait_for_timeout(300)
        # The accent is written on `body` (applyAppearance), and a `body[data-theme]` block carries the
        # theme's own --accent, so <html>'s copy is the :root default and never moves. Read the element
        # the app writes to, which is also the one every painted surface inherits from.
        acc = lambda: pg.evaluate("()=>getComputedStyle(document.body).getPropertyValue('--accent').trim()")
        check("accent field has a Save button", any("Save" in t for t in pg.eval_on_selector_all("#setPanel .btn.pri", "els=>els.map(e=>e.textContent)")))
        pg.eval_on_selector("#setPanel input[type=color]", "e=>{e.value='#ff0000';e.dispatchEvent(new Event('input',{bubbles:true}))}")
        pg.wait_for_timeout(300)
        check("accent previews live before saving", acc() == "#ff0000", acc())
        pg.eval_on_selector("#setPanel .btn.pri", "e=>e.click()"); pg.wait_for_timeout(700)
        check("accent save confirms", "Saved" in pg.eval_on_selector("#setPanel .btn.pri", "e=>e.textContent"))
        saved_acc = pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.settings.appearance.accent}")
        check("accent persists to settings", saved_acc == "#ff0000", str(saved_acc))
        pg.eval_on_selector_all("#setPanel select", "els=>{const s=els[els.length-1];s.value='0.9';s.dispatchEvent(new Event('change',{bubbles:true}))}")
        pg.wait_for_timeout(700)
        after_acc = pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.settings.appearance.accent}")
        check("accent survives a later settings change (no silent revert)", after_acc == "#ff0000", str(after_acc))
        # restore the real appearance
        pg.evaluate("async(a)=>{await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({settings:{appearance:a}})})}", appear_before)

        # ---- 10. AI model + phone + connected apps + plugins + voice render controls ----
        # By id, not by index: the rail gained groups and lost "Engines" (one tab that held the AI
        # endpoint, the browser and the phone, with nothing in the word to say which control was
        # whose), so a positional click would now land on the wrong panel.
        pg.eval_on_selector("#tab-models", "e=>e.click()"); pg.wait_for_timeout(200)
        mod = pg.eval_on_selector("#setPanel", "e=>e.innerText")
        check("the AI model tab carries the connection and model controls",
              "Connection" in mod and "Models" in mod and "Context" in mod, mod[:200])
        # The dead engine rows (9router / Ollama / claude / codex / custom) with their on/off toggles
        # used to sit at the bottom of the old Engines tab. Nothing ever read them — every turn goes to
        # the configured router — so they are gone rather than left as switches that do nothing. The
        # three real switches are now where their subject is: the Context card's compression here, and
        # the two that open the app to the phone on the Phone tab.
        check("the dead engine list is gone",
              not any(n in mod for n in ["9router", "Ollama", "Codex CLI", "Custom CLI"]), mod[:300])
        check("the AI model tab's only switch is the Context compression",
              pg.eval_on_selector_all("#setPanel .switch", "els=>els.map(e=>e.innerText.replace(/\\s+/g,' '))")
              == ["Compress when it runs out Drop the oldest tool output so a long turn still gets an answer."],
              str(pg.eval_on_selector_all("#setPanel .switch", "els=>els.map(e=>e.innerText)")))
        pg.eval_on_selector("#tab-phone", "e=>e.click()"); pg.wait_for_timeout(200)
        check("the Phone tab carries the LAN switch and the relay switch, and nothing else",
              pg.eval_on_selector_all("#setPanel .switch", "els=>els.map(e=>e.innerText.replace(/\\s+/g,' '))")
              == ["Allow devices on this network The phone app needs this on. It opens the API to your wifi behind a token — leave it off if you do not use a phone.",
                  "Reach this app from anywhere The phone then works on any network, not just your wifi. This app dials out to the relay you name below; nothing is opened on this machine."],
              str(pg.eval_on_selector_all("#setPanel .switch", "els=>els.map(e=>e.innerText)")))
        # The rail is a real tablist with a roving tabindex: exactly one tab — the one showing — is in
        # the tab order, so the rail is a single Tab stop and the arrows move between sections. This
        # used to assert every tab was tabbable, which is the pre-roving shape;
        # tests/test_tablist.mjs holds the same invariant against renderTabs directly.
        check("a settings tab is keyboard focusable",
              pg.evaluate("""()=>{const t=[...document.querySelectorAll('#setTabs .mtab')];
                const on=t.filter(e=>e.tabIndex===0);
                return t.length>0 && on.length===1 && on[0].getAttribute('aria-selected')==='true';}"""))
        pg.eval_on_selector("#tab-apps", "e=>e.click()"); pg.wait_for_timeout(200)  # Connected apps
        check("connected apps grid present", pg.eval_on_selector_all("#setPanel .card", "e=>e.length") >= 6)
        # The contract the panel is built on: each app declares how its credential is sent.
        conns = pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.settings.connectors}")
        by_id = {c["id"]: c for c in conns}
        check("each connector declares its auth scheme",
              by_id["linear"]["auth"] == "raw" and by_id["gmail"]["auth"] == "google"
              and by_id["github"]["auth"] == "bearer", str([(c["id"], c["auth"]) for c in conns]))
        check("no connector credential reaches the browser",
              not any(k in json.dumps(conns) for k in ('"token"', '"client_secret"')), json.dumps(conns)[:200])
        # A Google card asks for the durable credential and says where to get it; a token card does not.
        def card(name):
            return pg.evaluate("""(n)=>{const c=[...document.querySelectorAll('#setPanel .card')]
              .find(x=>x.querySelector('b') && x.querySelector('b').innerText===n);
              if(!c) return null; const a=c.querySelector('a');
              return {inputs:c.querySelectorAll('input').length, href:(a&&a.href)||'', text:c.innerText}}""", name)
        g = card("Gmail")
        check("the Gmail card asks for a client id, secret and refresh token", g and g["inputs"] == 4, str(g))
        check("the Gmail card links to where a refresh token comes from",
              g and "oauthplayground" in g["href"], str(g))
        check("the Gmail card warns about the 7-day Testing expiry", g and "7 days" in g["text"], str(g))
        check("a token-only app asks for one credential, not four", card("Linear")["inputs"] == 2, str(card("Linear")))
        # A credential round-trips write-only: saved, reported as a flag, never echoed back. The real
        # credential is snapshotted first and handed back through the API, so the suite cannot leave a
        # fake token behind — and, because the server keeps settings in memory, a bare file write would
        # not be enough: the cached copy would still hold the fake one.
        SETF = os.path.join(DATA, "settings.json")
        snap = json.load(open(SETF))
        gm = next((x for x in snap["connectors"] if x["id"] == "gmail"), {})
        was = all((gm.get(k) or "").strip() for k in ("client_id", "client_secret", "token"))
        try:
            r = pg.evaluate("""async()=>{const r=await (await fetch('/api/connector',{method:'POST',
              headers:{'Content-Type':'application/json'},body:JSON.stringify({id:'gmail',
              client_id:'e2e-client',client_secret:'e2e-secret',token:'e2e-refresh'})})).json();
              const c=await (await fetch('/api/config')).json();
              return {r:r, gmail:c.settings.connectors.find(x=>x.id==='gmail'),
                      raw:JSON.stringify(c.settings.connectors)}}""")
            check("saving a Google credential connects the app", r["r"]["connected"] and r["gmail"]["connected"], str(r["r"]))
            check("the panel learns the client is set, but never sees the secret",
                  r["gmail"]["has_client"] and r["gmail"]["has_secret"]
                  and not any(s in r["raw"] for s in ("e2e-client", "e2e-secret", "e2e-refresh")), r["raw"][:200])
            check("connecting a Google app adds its tool for bots", "gmail_api" in r["r"]["tools"], str(r["r"]["tools"]))
        finally:
            # Hand the real state back through the API (which also refreshes the server's cache):
            # restore the snapshot's credential, or disconnect when there was none to begin with.
            pg.evaluate("""async(v)=>{await fetch('/api/connector',{method:'POST',
              headers:{'Content-Type':'application/json'},
              body:JSON.stringify(v || {id:'gmail',disconnect:true})})}""",
              ({"id": "gmail", "client_id": gm.get("client_id", ""),
                "client_secret": gm.get("client_secret", ""), "token": gm.get("token", "")} if was else None))
        back = pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.settings.connectors.find(x=>x.id==='gmail').connected}")
        check("the test hands the real connector state back", back == was, str(back))
        pg.eval_on_selector("#tab-plugins", "e=>e.click()"); pg.wait_for_timeout(200)  # Plugins
        check("plugins add-server field present", pg.eval_on_selector_all("#setPanel input", "e=>e.length") >= 2)

        # ---- 10b. Plugins: a real MCP server reaches a bot ----
        # The panel is what connects a server and says what it found, so this drives the real controls
        # against tests/mcp_stub.py — a real MCP server over a real pipe, not a stand-in for one. The
        # settings file is snapshotted and handed back, so the suite leaves no plugin behind.
        MCP_SET = os.path.join(DATA, "settings.json")
        mcp_snap = json.load(open(MCP_SET))
        mcp_stub = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_stub.py")
        mcp_target = "%s %s --stdio" % (sys.executable, mcp_stub)
        mcp_card = "()=>{const c=[...document.querySelectorAll('#setPanel .card')].find(x=>x.innerText.includes('%s'));return c?c.innerText:''}"
        def mcp_add(name, target, env=""):
            pg.evaluate("""(a)=>{
              const ins=[...document.querySelectorAll('#setPanel input')];
              ins[0].value=a.name; ins[1].value=a.target;
              document.querySelectorAll('#setPanel textarea')[0].value=a.env;
            }""", {"name": name, "target": target, "env": env})
            pg.evaluate("()=>{[...document.querySelectorAll('#setPanel button')].find(b=>b.innerText.includes('Add server')).click()}")
            pg.wait_for_timeout(1100)
        def mcp_press(name, label):
            pg.evaluate("""(a)=>{const c=[...document.querySelectorAll('#setPanel .card')].find(x=>x.innerText.includes(a.n));
              [...c.querySelectorAll('button')].find(b=>b.innerText.includes(a.l)).click()}""", {"n": name, "l": label})
            pg.wait_for_timeout(1200)
        try:
            check("the plugins panel no longer says MCP is unwired",
                  "does not speak MCP" not in pg.eval_on_selector("#setPanel", "e=>e.innerText"))
            # add the server through the form, with an env var, the way a real local server is added
            mcp_add("E2E Stub", mcp_target, "STUB_TOKEN=e2e-secret-value")
            added = pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return (c.settings.mcp||[]).map(m=>m.id)}")
            check("the panel adds an MCP server", added == ["e2e-stub"], str(added))
            check("a server that is not tested yet says so", "not tested yet" in pg.evaluate(mcp_card % "E2E Stub"))
            # the credential is stored, and never handed back to the browser
            creds = pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return JSON.stringify(c.settings.mcp[0])}")
            check("the panel is told the env var is set", "STUB_TOKEN" in creds and "env_keys" in creds, creds[:200])
            check("the env value never reaches the browser", "e2e-secret-value" not in creds, creds[:200])
            # Test really connects the server and reports what it found
            mcp_press("E2E Stub", "Test")
            good = pg.evaluate(mcp_card % "E2E Stub")
            check("Test connects the server and the card names its tools",
                  "5 tools" in good and "stub-mcp" in good, good[:200])
            check("a connected server reads as on",
                  pg.eval_on_selector("#setPanel .card .tag", "e=>e.innerText.trim()") == "on")
            probe = pg.evaluate("async()=>await (await fetch('/api/mcp/test',{method:'POST',"
                                "headers:{'Content-Type':'application/json'},body:JSON.stringify({id:'e2e-stub'})})).json()")
            check("the server's own tool list comes back over the API",
                  probe.get("ok") and "echo" in probe.get("tools", []) and "add" in probe.get("tools", []), str(probe))
            # a server that will not start says why, in the panel, instead of failing inside a turn
            mcp_add("E2E Bad", "/nonexistent/mcp-server-xyz")
            mcp_press("E2E Bad", "Test")
            bad = pg.evaluate(mcp_card % "E2E Bad")
            check("a server that will not start says why in the panel",
                  "did not connect" in bad and "could not start" in bad, bad[:200])
            # Switch off keeps the entry but stops offering its tools
            mcp_press("E2E Stub", "Switch off")
            check("switching a server off shows it off", "switched off" in pg.evaluate(mcp_card % "E2E Stub"))
            # Remove takes it away, and takes its connection with it
            mcp_press("E2E Stub", "Remove")
            mcp_press("E2E Bad", "Remove")
            left = pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return (c.settings.mcp||[]).map(m=>m.id)}")
            check("removing a server takes it off the list", left == [], str(left))
        finally:
            for i in ("e2e-stub", "e2e-bad"):
                pg.evaluate("async(id)=>{await fetch('/api/mcp/disconnect',{method:'POST',"
                            "headers:{'Content-Type':'application/json'},body:JSON.stringify({id})})}", i)
            json.dump(mcp_snap, open(MCP_SET, "w"), indent=2)
        handed = pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return (c.settings.mcp||[]).length}")
        check("the test hands the real plugin list back", handed == len(mcp_snap.get("mcp") or []), str(handed))
        pg.eval_on_selector("#tab-voice", "e=>e.click()"); pg.wait_for_timeout(200)  # Voice
        check("voice tab offers a voice + test",
              pg.eval_on_selector_all("#setPanel select", "e=>e.length") >= 1
              and pg.eval_on_selector_all("#setPanel button", "e=>e.length") >= 1)
        check("voice tab makes no cloud-provider claim",
              "cloud" not in pg.eval_on_selector("#setPanel", "e=>e.innerText").lower())
        pg.eval_on_selector("#sClose", "e=>e.click()"); pg.wait_for_timeout(300)

        # ---- 11. computer panel ----
        pg.eval_on_selector("#btnComp", "e=>e.click()"); pg.wait_for_timeout(600)
        check("computer panel opens", pg.eval_on_selector("#comp", "e=>e.classList.contains('on')"))
        check("computer panel has a live frame + url box", pg.eval_on_selector("#compShot", "e=>e.tagName") == "IMG" and pg.eval_on_selector("#compUrl", "e=>e.tagName") == "INPUT")
        pg.eval_on_selector("#compClose", "e=>e.click()"); pg.wait_for_timeout(300)
        check("computer panel closes", not pg.eval_on_selector("#comp", "e=>e.classList.contains('on')"))

        # ---- 11b. PWA / installable app ----
        man = pg.evaluate("async()=>{const r=await fetch('manifest.webmanifest');return {ct:r.headers.get('content-type'),body:await r.json()}}")
        check("manifest served as manifest+json", "manifest" in (man["ct"] or ""), man["ct"])
        check("manifest has name + standalone + icons",
              man["body"].get("name") and man["body"].get("display") == "standalone" and len(man["body"].get("icons", [])) >= 3,
              str(man["body"].get("display")))
        ico = pg.evaluate("async()=>{const r=await fetch('icon-512.png');return {ct:r.headers.get('content-type'),n:(await r.blob()).size}}")
        check("app icon is a real PNG", "image/png" in (ico["ct"] or "") and ico["n"] > 1000, str(ico))
        sw = pg.evaluate("async()=>{const r=await navigator.serviceWorker.getRegistration();return !!(r&&(r.active||r.installing||r.waiting))}")
        check("service worker registers (installable)", sw)

        # ---- 11c. the secret store is not served, and the API is same-origin only ----
        # Raw HTTP, not page fetch: the browser normalises `..` and forbids a custom Origin,
        # so a raw socket is the only way to send a traversal and a foreign Origin for real.
        for path in ["/data/settings.json", "/data/config.json", "/data/sessions.json", "/../server.py"]:
            code, body = raw_get(BASE + path.lstrip("/"), path_as_is=True)
            check("the secret store is not served: " + path, code == 404, str(code))
            if code == 200: check("  ...and no secret came back: " + path, "router" not in body[:400] and "token" not in body[:400])
        code, _ = raw_get(BASE + "api/config", origin="https://evil.example")
        check("a cross-site API call is refused", code == 403, str(code))
        code, _ = raw_get(BASE + "api/config", host="evil.example")
        check("a rebound Host is refused", code == 403, str(code))

        # ---- 11c. no stale shell: updates must reach the user ----
        hdr = pg.evaluate("async()=>{const r=await fetch('index.html',{cache:'no-store'});return {cc:r.headers.get('cache-control')||'',js:await (await fetch('app.js',{cache:'no-store'})).text()}}")
        check("html is served no-cache (no stale shell)", "no-cache" in hdr["cc"] or "no-store" in hdr["cc"], hdr["cc"])
        check("served app.js is the icon build (svg icons present)", "svg(" in hdr["js"])
        bad = pg.evaluate("async()=>{const t=await (await fetch('app.js',{cache:'no-store'})).text();return (t.match(/[\\u{1F000}-\\u{1FAFF}\\u{2600}-\\u{27BF}\\u{FE0F}]/gu)||[]).slice(0,8)}")
        check("served app.js carries no emoji glyphs", len(bad) == 0, str(bad))
        swsrc = pg.evaluate("async()=>await (await fetch('sw.js',{cache:'no-store'})).text()")
        # The network call is made first and the cache is only read in its failure path, so a cached
        # shell can never pin an update. Matched by order rather than by the catch's exact text: the
        # catch became `async` when it grew the navigation fallback (tests/test_service_worker.mjs
        # holds the fallback's shape, and its own warm-cache check holds network-first).
        check("service worker is network-first (won't pin a stale shell)",
              "fetch(e.request).then(res" in swsrc and "caches.match" in swsrc
              and swsrc.index("fetch(e.request)") < swsrc.index("caches.match"))

        # ---- 11d. models: detect every model the API key can reach ----
        # This one is real, and the endpoint saves what it finds into config.json — so the file is
        # kept here and written back at the end. Without that the suite quietly replaces the user's
        # own saved model list with whatever the router happens to be serving today.
        CFGP = os.path.join(DATA, "config.json")
        cfg_before = open(CFGP).read()
        mdet = pg.evaluate("async()=>await (await fetch('/api/models/detect',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).json()")
        check("detect models from the API key returns a real list", bool(mdet.get("ok")) and mdet.get("count", 0) > 5, str(mdet)[:150])
        cfgm = pg.evaluate("async()=>await (await fetch('/api/config')).json()")
        check("detected models persist in config", len(cfgm.get("models", [])) == mdet.get("count"), str(len(cfgm.get("models", []))))
        pg.eval_on_selector("#btnSettings", "e=>e.click()"); pg.wait_for_timeout(400)
        pg.eval_on_selector("#tab-models", "e=>e.click()"); pg.wait_for_timeout(400)   # AI model
        check("AI model offers 'Detect all models from the API key'",
              pg.evaluate("()=>[...document.querySelectorAll('#setPanel .btn')].some(b=>/Detect all models/.test(b.textContent))"))
        # The raw call above proved the endpoint; this is the UI's own path — the button the user
        # actually clicks — and it is what refreshes the client's model list. Calling the endpoint
        # directly leaves that list untouched, so the panel would still be drawing the one model it
        # loaded at start-up, and every list check below would be measuring the bypass, not the app.
        pg.evaluate("()=>[...document.querySelectorAll('#setPanel .btn')]"
                    ".find(b=>/^Detect all models$/.test(b.textContent.trim())).click()")
        # The detect is a live round-trip to the router — several hundred ids over a link that can take
        # a second or more. Reading the panel before it lands measures the list from *before* the click
        # against a count from after it, and the mismatch reads as a broken cap. Wait for the button to
        # come back, then take the count from the panel itself: that is the same list the cap counts, so
        # the comparison is the app's own consistency rather than the router's mood.
        pg.wait_for_function("()=>{const b=[...document.querySelectorAll('#setPanel .btn')]"
                             ".find(x=>x.textContent.trim()==='Detect all models');return !!b&&!b.disabled}",
                             timeout=60000)
        subline = pg.evaluate("""()=>{const c=[...document.querySelectorAll('#setPanel .card')]
            .find(x=>/^Models/.test((x.querySelector('.ct b')||{}).textContent||''));
            return c?(c.querySelector('.sub')||{}).textContent:''}""")
        mcount = int((re.search(r"(\d+) available", subline) or re.match(r"(\d+)", subline or "0")).group(1))
        check("model list renders with remove buttons",
              pg.eval_on_selector_all("#setPanel .sklist.scroll .sk .btn", "e=>e.length") > 5)
        # A router can hand back several hundred ids. Rendering every one of them pushed the Context
        # and Image cards off the panel — a settings screen nobody scrolls to the end of — so the list
        # shows a dozen and offers the rest behind a count.
        shown = pg.eval_on_selector_all("#setPanel .sklist.scroll .sk", "e=>e.length")
        check("a long model list is capped, not dumped", shown == min(12, mcount), "%d rows of %d" % (shown, mcount))
        if mcount > 12:
            capt = pg.evaluate("()=>{const b=[...document.querySelectorAll('#setPanel .sklist button')]"
                               ".find(x=>/^Show all/.test(x.textContent));return b?b.textContent.trim():''}")
            check("the cap says how many are behind it", capt == "Show all %d" % mcount,
                  "%r vs 'Show all %d'" % (capt, mcount))
            pg.evaluate("()=>[...document.querySelectorAll('#setPanel .sklist button')]"
                        ".find(x=>/^Show all/.test(x.textContent)).click()")
            pg.wait_for_timeout(400)
            revealed = pg.eval_on_selector_all("#setPanel .sklist.scroll .sk", "e=>e.length")
            check("Show all reveals the whole list", revealed == mcount, "%d of %d" % (revealed, mcount))
        # The media card fills its picker from /api/media/models, which is a round-trip to the router
        # and takes anywhere from one to eight seconds — so this waits for the options to appear rather
        # than for a guessed number of milliseconds, which only passes when the router happens to be
        # quick. The deadline is generous and the check below still reports an empty picker as a failure.
        mdeadline = time.time() + 60
        while time.time() < mdeadline:
            pg.wait_for_timeout(400)
            if pg.eval_on_selector_all("#setPanel select option", "e=>e.length"): break
        check("AI model has an 'Image generation' card",
              pg.evaluate("()=>[...document.querySelectorAll('#setPanel .card .ct b')].some(b=>/Image generation/.test(b.textContent))"))
        check("image model picker is filled from the API key",
              pg.eval_on_selector_all("#setPanel select option", "e=>e.length") > 0,
              pg.evaluate("()=>[...document.querySelectorAll('#setPanel .card')].map(c=>(c.querySelector('.ct b')||{}).textContent+': '+(c.querySelector('.desc')||{}).textContent).join(' | ')")[:200])
        # The browser is its own tab now, so the card checks below run there rather than here.
        pg.eval_on_selector("#tab-browser", "e=>e.click()"); pg.wait_for_timeout(400)
        check("the Browser tab has a Browser card",
              pg.evaluate("()=>[...document.querySelectorAll('#setPanel .card .ct b')].some(b=>/^Browser$/.test(b.textContent.trim()))"))
        check("browser card offers ZenPilot over CDP",
              pg.eval_on_selector_all("#setPanel select", "els=>els.some(s=>[...s.options].some(o=>/CDP/.test(o.textContent)))"))
        check("browser card asks for a debug port, and only a port",
              pg.evaluate("()=>{const i=[...document.querySelectorAll('#setPanel input')].find(x=>x.type==='number'&&x.max==='65535');"
                          "return !!i&&i.placeholder==='9222'&&!document.querySelector('#setPanel input[placeholder*=\"--remote-debugging-port\"]')}"))
        check("the port field says which endpoint it drives",
              pg.evaluate("()=>[...document.querySelectorAll('#setPanel .desc')].some(d=>/DEBUG PORT/.test(d.textContent)&&/127\\.0\\.0\\.1/.test(d.textContent))"))
        check("browser card can launch ZenPilot from the port",
              pg.evaluate("()=>[...document.querySelectorAll('#setPanel .btn')].some(b=>/Launch ZenPilot/.test(b.textContent))"))
        check("browser card can pin which profile to use",
              pg.eval_on_selector_all("#setPanel input", "els=>els.some(i=>/Profiles to keep/.test(i.placeholder||''))"))
        pg.eval_on_selector("#tab-bots", "e=>e.click()"); pg.wait_for_timeout(400)   # Bots
        pg.eval_on_selector_all("#setPanel [data-a='edit']", "els=>els[0].click()"); pg.wait_for_timeout(400)
        # ---- 11d. the bot editor's model picker ----
        # It must be a list you open, not a native <datalist>: a datalist only shows its options
        # while you are typing, so "Detect all models" looked like it had done nothing.
        check("the model field is not a native datalist",
              pg.evaluate("()=>!document.querySelector('#setPanel .mpick datalist')"))
        check("the model field opens on click",
              pg.evaluate("()=>{const f=document.querySelector('#setPanel .mfield');return !!f && f.getAttribute('aria-expanded')==='false'}"))
        pg.eval_on_selector("#setPanel .mfield", "e=>e.click()"); pg.wait_for_timeout(300)
        opened = pg.evaluate("""()=>({exp:document.querySelector('#setPanel .mfield').getAttribute('aria-expanded'),
          rows:document.querySelectorAll('#setPanel .mlist .mrow').length,
          focus:document.activeElement && document.activeElement.placeholder})""")
        check("opening it lists the models and puts the cursor in the filter",
              opened["exp"] == "true" and opened["rows"] > 5 and opened["focus"] == "Filter models…", str(opened))
        pg.fill("#setPanel .mpick input", "qwen"); pg.wait_for_timeout(300)
        filt = pg.evaluate("()=>[...document.querySelectorAll('#setPanel .mlist .mrow b')].map(e=>e.textContent)")
        check("typing filters the model list", 0 < len(filt) < opened["rows"], str(filt[:4]))
        check("the filter matches anywhere in the id, not just the start",
              all("qwen" in m.lower() for m in filt), str(filt[:4]))
        pg.evaluate("()=>document.querySelector('#setPanel .mlist .mrow').click()"); pg.wait_for_timeout(250)
        picked = pg.evaluate("()=>({label:document.querySelector('#setPanel .mfield b').textContent,"
                             "exp:document.querySelector('#setPanel .mfield').getAttribute('aria-expanded')})")
        check("picking a model names it in the field", picked["label"] == filt[0], str(picked) + " vs " + filt[0])
        check("picking a model closes the list", picked["exp"] == "false")
        # an id the router does not list is still usable, so a hand-typed model is not a dead end
        pg.eval_on_selector("#setPanel .mfield", "e=>e.click()"); pg.wait_for_timeout(250)
        pg.fill("#setPanel .mpick input", "e2e/custom-model-not-in-list"); pg.wait_for_timeout(300)
        check("a typed id the list does not hold is offered",
              "e2e/custom-model-not-in-list" in pg.evaluate("()=>{const r=document.querySelector('#setPanel .mlist .mrow');return r?r.textContent:''}"))
        pg.evaluate("()=>document.querySelector('#setPanel .mlist .mrow').click()"); pg.wait_for_timeout(250)
        check("the typed id can be chosen",
              pg.evaluate("()=>document.querySelector('#setPanel .mfield b').textContent") == "e2e/custom-model-not-in-list")
        # Detect is stubbed, so the check proves the wiring without spending a call or rewriting
        # the user's saved model list (the real endpoint saves what it finds into config.json). The
        # stub is a *superset* of the real list, so the picker is left holding a truthful list (the
        # page's S.models is module-scoped, so a test cannot put the real list back afterwards).
        base = pg.evaluate("async()=>((await (await fetch('/api/models')).json()).models)||[]")
        stub = {"ok": True, "count": len(base) + 3,
                "models": ["e2e/alpha", "e2e/beta", "e2e/gamma"] + base}
        pg.route("**/api/models/detect", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(stub)))
        pg.eval_on_selector("#setPanel .mfield", "e=>e.click()"); pg.wait_for_timeout(200)
        pg.evaluate("()=>{const b=[...document.querySelectorAll('#setPanel button')].find(x=>/detect all models/i.test(x.textContent));b.click()}")
        for _ in range(20):
            pg.wait_for_timeout(250)
            if "Detecting" not in pg.evaluate("()=>{const b=[...document.querySelectorAll('#setPanel button')].find(x=>/detect/i.test(x.textContent));return b?b.textContent:''}"):
                break
        det = pg.evaluate("""()=>({note:[...document.querySelectorAll('#setPanel .mpick .desc')].map(e=>e.textContent).join(' | '),
          btn:(()=>{const b=[...document.querySelectorAll('#setPanel button')].find(x=>/detect/i.test(x.textContent));return b?b.textContent:''})(),
          rows:[...document.querySelectorAll('#setPanel .mlist .mrow b')].map(e=>e.textContent)})""")
        check("Detect finishes and reports how many it found",
              f"{stub['count']} models detected from the API key" in det["note"], str(det["note"])[:120])
        check("Detect is not left spinning", "Detecting" not in det["btn"], str(det["btn"]))
        check("the detected models appear in the open list",
              det["rows"][:3] == stub["models"][:3], str(det["rows"][:4]))
        pg.unroute("**/api/models/detect")

        # ---- 11d2. the bot editor's Tools section ----
        # The tick-list is gated on b.tools_allow, which the select sets *after* this section has
        # been drawn, so drawing it once left "Custom selection" showing an empty box. The list is
        # also fed by the server (/api/config "tools"), so it can never offer a tool the server
        # cannot actually run.
        tools_cfg = pg.evaluate("async()=>(await (await fetch('/api/config')).json()).tools")
        check("the server tells the editor which tools exist",
              isinstance(tools_cfg, list) and len(tools_cfg) > 5
              and all(t.get("name") and t.get("desc") for t in tools_cfg), str(tools_cfg)[:120])
        def set_tool_mode(v):
            pg.evaluate("""(v)=>{const f=[...document.querySelectorAll('#setPanel .fld')]
              .find(x=>x.querySelector('label')&&x.querySelector('label').textContent==='TOOL SELECTION');
              const s=f.querySelector('select');s.value=v;s.dispatchEvent(new Event('change'))}""", v)
            pg.wait_for_timeout(250)
        def tool_rows():
            return pg.evaluate("""()=>{const f=[...document.querySelectorAll('#setPanel .fld')]
              .find(x=>x.querySelector('label')&&x.querySelector('label').textContent==='ALLOWED TOOLS');
              return f?[...f.querySelectorAll('.sk')].map(e=>({name:e.querySelector('b').textContent,
                desc:(e.querySelector('span span')||{}).textContent||'',on:e.classList.contains('on')})):null}""")
        opts = pg.evaluate("""()=>{const f=[...document.querySelectorAll('#setPanel .fld')]
          .find(x=>x.querySelector('label')&&x.querySelector('label').textContent==='TOOL SELECTION');
          return f?[...f.querySelector('select').options].map(o=>o.textContent):null}""")
        check("the editor offers both a default set and a custom selection",
              opts == ["All current tools", "Custom selection"], str(opts))
        set_tool_mode("all")
        check("'All current tools' shows no tick-list", tool_rows() is None, str(tool_rows()))
        set_tool_mode("custom")
        rows = tool_rows()
        check("switching to Custom shows the tools to tick (the reported bug)",
              rows is not None and len(rows) >= len(tools_cfg), str(rows)[:160])
        names = [r["name"] for r in (rows or [])]
        check("the offered tools begin with exactly the server's own tools",
              names[:len(tools_cfg)] == [t["name"] for t in tools_cfg], str(names))
        check("every tool row explains what that tool does",
              all(r["desc"] for r in (rows or [])), str([r["name"] for r in (rows or []) if not r["desc"]]))
        check("a fresh custom selection starts with a small working set",
              0 < sum(r["on"] for r in (rows or [])) < len(rows or []),
              str([r["name"] for r in (rows or []) if r["on"]]))
        pg.evaluate("""()=>{const f=[...document.querySelectorAll('#setPanel .fld')]
          .find(x=>x.querySelector('label')&&x.querySelector('label').textContent==='ALLOWED TOOLS');
          f.querySelector('.sk').click()}""")
        pg.wait_for_timeout(200)
        after = tool_rows()
        check("ticking a tool flips it", after is not None and after[0]["on"] != rows[0]["on"],
              str(after[0]) + " vs " + str(rows[0]))
        # the choice must survive a save, so prove the round trip on a throwaway bot (the editor's
        # working copy is not saved here, so the user's own bots are never touched).
        rt = {"id": "e2e-tools", "name": "E2E Tools", "tools_allow": ["read_file", "finish"]}
        pg.evaluate("async(b)=>{await fetch('/api/bot',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({bot:b})})}", rt)
        got = pg.evaluate("async()=>((await (await fetch('/api/config')).json()).bots||[]).find(b=>b.id==='e2e-tools')")
        check("a bot's chosen tools are saved and handed back",
              bool(got) and got.get("tools_allow") == ["read_file", "finish"], str(got))
        pg.evaluate("async()=>{await fetch('/api/bot/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:'e2e-tools'})})}")

        pg.eval_on_selector_all("#setPanel .btn", "els=>{const b=els.find(x=>/^Back$/.test(x.textContent.trim()));if(b)b.click()}")
        pg.wait_for_timeout(200)
        pg.eval_on_selector("#sClose", "e=>e.click()"); pg.wait_for_timeout(300)

        # ---- 11e. the media endpoints answer honestly (the free browser route is the default) ----
        med = pg.evaluate("async()=>await (await fetch('/api/media/models')).json()")
        check("API key exposes image-capable models", bool(med.get("ok")) and len(med.get("image", [])) > 0, str(med)[:160])
        check("media endpoint names the model used to draw", bool(med.get("image_model")), str(med.get("image_model")))
        check("media endpoint reports video availability honestly", "video" in med, str(med.get("video"))[:80])
        bad_img = pg.evaluate("async()=>await (await fetch('/api/media/model',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:''})})).json()")
        check("media endpoint rejects an empty model", not bad_img.get("ok"))

        # ---- 11f. the bots can reuse a browser you already run (ZenPilot), over CDP ----
        binfo = pg.evaluate("async()=>await (await fetch('/api/browser')).json()")
        check("browser endpoint reports a mode", bool(binfo.get("ok")) and binfo.get("mode") in ("own", "cdp"), str(binfo)[:160])
        check("browser endpoint reports running + attached", "running" in binfo and "attached" in binfo, str(binfo)[:120])
        check("browser endpoint reports the port and the endpoint derived from it",
              binfo.get("port") and binfo.get("cdp_url") == "http://127.0.0.1:%s" % binfo["port"],
              str(binfo)[:150])
        check("the retired launch command is gone, not left to disagree with the port",
              "launch_cmd" not in binfo, str(list(binfo.keys())))
        check("browser endpoint carries the profile filter",
              "target_url" in binfo and "target_urls" in binfo, str(binfo)[:150])

        # The regression this guards: the port and the launch command each named a port, so the app
        # could connect to one nothing was listening on. The port is now the only thing to set, and
        # the endpoint the app connects to has to follow it.
        pg.eval_on_selector("#btnSettings", "e=>e.click()"); pg.wait_for_timeout(400)
        pg.eval_on_selector("#tab-browser", "e=>e.click()"); pg.wait_for_timeout(700)   # Browser
        pg.evaluate("()=>{const i=[...document.querySelectorAll('#setPanel input')].find(x=>x.type==='number'&&x.max==='65535');"
                    "i.value='9333';i.dispatchEvent(new Event('input'));i.dispatchEvent(new Event('change'))}")
        hint = pg.evaluate("()=>[...document.querySelectorAll('#setPanel .desc')].map(d=>d.textContent).join(' ')")
        check("the card names the endpoint the typed port drives", "127.0.0.1:9333" in hint, hint[:170])
        # Scope to the Browser card: the Connection card's own "Test connection" comes first in the
        # panel, and clicking that would test the router instead of moving the browser endpoint.
        pg.evaluate("""()=>{const c=[...document.querySelectorAll('#setPanel .card')]
          .find(x=>x.querySelector('input[type=number][max="65535"]'));
          [...c.querySelectorAll('.btn')].find(b=>/Test connection/.test(b.textContent)).click()}""")
        pg.wait_for_timeout(1500)
        moved = pg.evaluate("async()=>await (await fetch('/api/browser')).json()")
        check("saving the port moves the endpoint the app connects to",
              moved.get("port") == 9333 and moved.get("cdp_url") == "http://127.0.0.1:9333", str(moved)[:160])
        # put the port back where it was found, and reconnect there, so nothing is left borrowed
        pg.evaluate("async(b)=>await (await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},"
                    "body:JSON.stringify({settings:{browser:b}})})).json()",
                    {"mode": binfo.get("mode", "own"), "port": binfo.get("port", 9222)})
        pg.evaluate("""()=>{const c=[...document.querySelectorAll('#setPanel .card')]
          .find(x=>x.querySelector('input[type=number][max="65535"]'));
          [...c.querySelectorAll('.btn')].find(b=>/Test connection/.test(b.textContent)).click()}""")
        pg.wait_for_timeout(1200)
        pg.eval_on_selector("#sClose", "e=>e.click()"); pg.wait_for_timeout(250)

        # ---- 11g. import the ZenPilot profiles that are actually open, instead of typing them ----
        zinfo = pg.evaluate("async()=>await (await fetch('/api/browser/profiles')).json()")
        check("profiles endpoint says whether ZenPilot is installed",
              zinfo.get("ok") is True and isinstance(zinfo.get("installed"), bool), str(zinfo)[:160])
        check("profiles endpoint carries the page that sells ZenPilot",
              zinfo.get("get_url") == "https://anzenpilot.gumroad.com/l/zenpilot", str(zinfo.get("get_url")))
        check("profiles endpoint answers with a list and an up flag, never a guess",
              isinstance(zinfo.get("profiles"), list) and isinstance(zinfo.get("up"), bool), str(zinfo)[:160])

        stub = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _CDPStub)
        threading.Thread(target=stub.serve_forever, daemon=True).start()
        sport = stub.server_address[1]
        # The stub port goes into the real settings for the length of this block, so the restore
        # has to happen even if a check below blows up -- otherwise the user's browser config is
        # left pointing at a port that stopped listening when this test ended.
        try:
            pg.evaluate("async(p)=>await (await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},"
                        "body:JSON.stringify({settings:{browser:{mode:'cdp',port:Number(p)}}})})).json()",
                        str(sport))
            live = pg.evaluate("async()=>await (await fetch('/api/browser/profiles')).json()")
            check("a running ZenPilot's profiles are listed by host",
                  live.get("up") is True and [x.get("host") for x in live.get("profiles", [])] == ["gemini.google.com"],
                  str(live)[:200])
            check("the devtools page target is not mistaken for a profile",
                  all("devtools" not in (x.get("host") or "") for x in live.get("profiles", [])), str(live.get("profiles"))[:160])

            pg.eval_on_selector("#btnSettings", "e=>e.click()"); pg.wait_for_timeout(400)
            pg.eval_on_selector("#tab-browser", "e=>e.click()"); pg.wait_for_timeout(600)   # Browser
            check("the browser card offers to import ZenPilot profiles",
                  pg.evaluate("()=>[...document.querySelectorAll('#setPanel .btn')].some(b=>/Import profiles/.test(b.textContent))"))
            glink = pg.evaluate("()=>{const a=document.querySelector('#setPanel [data-a=\"zp-get\"]');return a?a.getAttribute('href'):''}")
            check("the card links to where ZenPilot can be got",
                  glink == "https://anzenpilot.gumroad.com/l/zenpilot", str(glink))
            check("no 'not installed' warning when ZenPilot is actually here",
                  pg.evaluate("()=>getComputedStyle(document.querySelector('#setPanel .zpwarn')).display") == "none")
            pg.evaluate("()=>[...document.querySelectorAll('#setPanel .btn')].find(b=>/Import profiles/.test(b.textContent)).click()")
            pg.wait_for_timeout(700)
            rows = pg.eval_on_selector_all(".modal.pick .blist .sk b", "els=>els.map(e=>e.textContent)")
            check("the import picker lists the profiles ZenPilot has open", rows == ["gemini.google.com"], str(rows))
            pg.evaluate("()=>[...document.querySelectorAll('.modal.pick .bfoot .btn')].find(b=>/Import selected/.test(b.textContent)).click()")
            pg.wait_for_timeout(700)
            check("importing closes the picker", pg.evaluate("()=>!document.querySelector('.modal.pick')"))
            pin = pg.evaluate("async()=>(await (await fetch('/api/browser')).json()).target_url")
            check("importing pins the chosen profile for the bots", pin == "gemini.google.com", str(pin))
            shown = pg.evaluate("()=>{const i=[...document.querySelectorAll('#setPanel input')].find(x=>/Profiles to keep/.test(x.placeholder||''));return i?i.value:''}")
            check("the pin field shows what was imported", shown == "gemini.google.com", str(shown))
        finally:
            pg.evaluate("async(b)=>await (await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},"
                        "body:JSON.stringify({settings:{browser:b}})})).json()",
                        {"mode": binfo.get("mode", "own"), "port": binfo.get("port", 9222),
                         "target_url": binfo.get("target_url", "")})
            stub.shutdown()
        back = pg.evaluate("async()=>(await (await fetch('/api/browser')).json())")
        check("the browser settings the test borrowed are handed back",
              back.get("cdp_url") == binfo.get("cdp_url") and back.get("port") == binfo.get("port"), str(back)[:160])
        pg.eval_on_selector("#sClose", "e=>e.click()"); pg.wait_for_timeout(250)

        # ---- 11h. ZenPilot missing: a warning the user can act on, not a silent wrong browser ----
        pg.route("**/api/browser/profiles", lambda r: r.fulfill(status=200, content_type="application/json",
            body=json.dumps({"ok": True, "installed": False, "app": "", "cdp_url": "http://127.0.0.1:9222",
                             "up": False, "profiles": [], "get_url": "https://anzenpilot.gumroad.com/l/zenpilot",
                             "err": "refused", "hint": "nothing is listening on that port yet"})))
        # The warning is about the CDP route: in "own" mode ZenPilot is irrelevant, so the card hides
        # it. Put the server in cdp mode for this block, and hand the mode back at the end.
        pg.evaluate("async()=>await (await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},"
                    "body:JSON.stringify({settings:{browser:{mode:'cdp',port:9222}}})})).json()")
        pg.eval_on_selector("#btnSettings", "e=>e.click()"); pg.wait_for_timeout(400)
        pg.eval_on_selector("#tab-browser", "e=>e.click()"); pg.wait_for_timeout(900)   # Browser
        warn = pg.evaluate("()=>{const w=document.querySelector('#setPanel .zpwarn');return w?{d:getComputedStyle(w).display,t:w.innerText}:null}")
        check("a missing ZenPilot raises a warning on the card", bool(warn) and warn["d"] != "none", str(warn))
        check("the warning says ZenPilot is not installed and how to get it",
              "not installed" in warn["t"] and "anzenpilot.gumroad.com/l/zenpilot" not in warn["t"], str(warn["t"])[:120])
        check("the warning carries a Get ZenPilot button that opens the shop page",
              pg.evaluate("()=>{const a=document.querySelector('#setPanel [data-a=\"zp-get\"]');"
                          "return a&&a.getAttribute('href')==='https://anzenpilot.gumroad.com/l/zenpilot'"
                          "&&a.getAttribute('target')==='_blank'}"))
        check("the status line points at the warning instead of a raw connect error",
              "not installed" in pg.evaluate("()=>document.querySelector('#setPanel .card .desc:last-of-type').textContent").lower()
              or "not installed" in pg.evaluate("()=>[...document.querySelectorAll('#setPanel .desc')].map(e=>e.textContent).join(' ')").lower(),
              pg.evaluate("()=>[...document.querySelectorAll('#setPanel .desc')].map(e=>e.textContent).join(' | ')")[:160])
        pg.evaluate("()=>[...document.querySelectorAll('#setPanel .btn')].find(b=>/Import profiles/.test(b.textContent)).click()")
        pg.wait_for_timeout(700)
        dead = pg.evaluate("()=>{const m=document.querySelector('.modal.pick');return m?{t:m.innerText,rows:m.querySelectorAll('.blist .sk').length,use:!!m.querySelector('[data-a=\"use\"]')}:null}")
        check("importing without ZenPilot explains why and offers no dead picker",
              bool(dead) and dead["rows"] == 0 and not dead["use"] and "not installed" in dead["t"], str(dead)[:180])
        check("the dead end still links to the shop page",
              pg.evaluate("()=>{const a=document.querySelector('.modal.pick a');return a?a.getAttribute('href'):''}") == "https://anzenpilot.gumroad.com/l/zenpilot")
        pg.evaluate("()=>document.querySelector('.modal.pick .x').click()"); pg.wait_for_timeout(200)
        pg.eval_on_selector("#sClose", "e=>e.click()"); pg.wait_for_timeout(200)
        pg.unroute("**/api/browser/profiles")
        pg.evaluate("async(b)=>await (await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},"
                    "body:JSON.stringify({settings:{browser:b}})})).json()",
                    {"mode": binfo.get("mode", "own"), "port": binfo.get("port", 9222)})

        # ---- 11i. Phone & tablet: the switch really opens the door the Android app comes through ----
        # The card is the whole setup path for the phone — no terminal, no flag — so it is checked
        # the way a user would use it: flip the switch, read the address and token off the card, and
        # confirm the API answered a caller on the LAN address differently before and after.
        pg.eval_on_selector("#btnSettings", "e=>e.click()"); pg.wait_for_timeout(400)
        pg.eval_on_selector("#tab-phone", "e=>e.click()"); pg.wait_for_timeout(700)   # Phone
        lan_card = pg.evaluate("""()=>{const c=[...document.querySelectorAll('#setPanel .card')]
          .find(x=>/Phone & tablet/.test(x.textContent));
          const i=c.querySelector('input');
          return c?{on:!!c.querySelector('.switch .tg.on'),note:c.querySelector('.desc').innerText,
                    shown:!!i&&i.getBoundingClientRect().height>0}:null}""")
        check("the Phone & tablet card is on the Phone tab", bool(lan_card), str(lan_card))
        check("it starts off, and says the API is closed", lan_card["on"] is False, str(lan_card))
        check("...with nothing to copy while it is off", lan_card["shown"] is False, str(lan_card))
        check("the API agrees it is closed",
              pg.evaluate("async()=>(await (await fetch('/api/lan')).json()).enabled") is False)
        # The phone's door is a TCP port on this machine's own LAN address — never on loopback, which
        # the app deliberately leaves shut so nothing on localhost serves it. So these calls connect
        # to the address the server reports and forge the Host the phone would send. While the switch
        # is off that port is not listening at all, which is a stronger shut door than a 403.
        lan_url = pg.evaluate("async()=>(await (await fetch('/api/lan')).json()).url")
        lan_host = "192.168.1.20:%d" % urlparse(BASE).port
        check("a caller on the LAN address is refused while it is off",
              raw_try(lan_url + "api/config", host=lan_host) is None, str(lan_url))
        pg.evaluate("""()=>{const c=[...document.querySelectorAll('#setPanel .card')]
          .find(x=>/Phone & tablet/.test(x.textContent)); c.querySelector('.switch .tg').click()}""")
        pg.wait_for_timeout(2500)
        on = pg.evaluate("""()=>{const c=[...document.querySelectorAll('#setPanel .card')]
          .find(x=>/Phone & tablet/.test(x.textContent));
          const i=[...c.querySelectorAll('input')];
          return {on:!!c.querySelector('.switch .tg.on'),note:c.querySelector('.desc').innerText,
                  url:i[0].value,token:i[1].value}}""")
        check("flipping the switch turns it on and says so", on["on"] is True, str(on)[:160])
        check("...and the card hands over an address and a token for the phone",
              on["url"].startswith("http://") and len(on["token"]) >= 32, str(on)[:160])
        # The listener has moved off loopback, so the page can no longer reach the API — every check
        # from here to the switch-off reads through the LAN address instead.
        _st, _body = raw_get(lan_url + "api/lan", host=lan_host, headers={"X-Anzen-Token": on["token"]})
        st = json.loads(_body) if _st == 200 else {}
        check("...and the API it wrote agrees", st.get("enabled") is True, str(st))
        check("the token on the card is the one the server minted", st.get("token") == on["token"])
        check("a caller on the LAN address with no token is still refused",
              raw_get(lan_url + "api/config", host=lan_host)[0] == 403)
        check("...but the token the card showed lets it in",
              raw_get(lan_url + "api/config", host=lan_host, headers={"X-Anzen-Token": on["token"]})[0] == 200)
        check("...and a wrong token does not",
              raw_get(lan_url + "api/config", host=lan_host, headers={"X-Anzen-Token": "nope"})[0] == 403)
        code, _ = raw_get(lan_url + "?t=" + on["token"], host=lan_host)
        check("the phone's link on its own — what a browser can send — is refused", code == 403, str(code))
        code, _ = raw_get(lan_url + "?t=" + on["token"], host=lan_host,
                          headers={"X-Anzen-Token": on["token"]})
        check("...and hands the device a cookie once the app proves itself with the header",
              code == 302, str(code))
        check("...and a wrong one is refused",
              raw_get(lan_url + "?t=wrong", host=lan_host, headers={"X-Anzen-Token": "wrong"})[0] == 403)
        check("the secret store is not served to a phone that got in either",
              raw_get(lan_url + "data/config.json", host=lan_host,
                      headers={"X-Anzen-Token": on["token"]})[0] == 404)
        check("loopback stays shut while the LAN is open — the window uses its own channel",
              raw_try(BASE + "api/config", host="127.0.0.1:%d" % urlparse(BASE).port) is None)
        pg.evaluate("""()=>{const c=[...document.querySelectorAll('#setPanel .card')]
          .find(x=>/Phone & tablet/.test(x.textContent)); c.querySelector('.switch .tg').click()}""")
        pg.wait_for_timeout(2500)
        off = pg.evaluate("""()=>{const c=[...document.querySelectorAll('#setPanel .card')]
          .find(x=>/Phone & tablet/.test(x.textContent));
          return {on:!!c.querySelector('.switch .tg.on'),note:c.querySelector('.desc').innerText}}""")
        check("flipping it back closes the door again", off["on"] is False, str(off))
        check("...and the API says so",
              pg.evaluate("async()=>(await (await fetch('/api/lan')).json()).enabled") is False)
        check("a token is no longer handed out while it is off",
              pg.evaluate("async()=>(await (await fetch('/api/lan')).json()).token") == "")
        check("...and the door really is shut, not just reported shut",
              raw_try(lan_url + "api/config", host=lan_host,
                      headers={"X-Anzen-Token": on["token"]}) is None)
        pg.eval_on_selector("#sClose", "e=>e.click()"); pg.wait_for_timeout(250)

        # ---- 11b. @mention picker ----
        # A room's members are what @ can name, so the list comes from the channel that is open.
        first_room = pg.evaluate("async()=>{const cfg=await (await fetch('/api/config')).json();"
                                 "return cfg.channels.length?cfg.channels[0].id:null}")
        room_members = pg.evaluate("async(id)=>{const cfg=await (await fetch('/api/config')).json();"
                                   "const room=cfg.channels.find(x=>x.id===id);return room?room.members:[]}", first_room)
        pg.evaluate("(id)=>[...document.querySelectorAll('#chans > li.group > .bot')].find(e=>e.dataset.id===id).click()", first_room)
        pg.wait_for_timeout(500)
        pg.fill("#input", "@"); pg.wait_for_timeout(300)
        pop = pg.evaluate("()=>{const p=document.querySelector('#mentionPop');"
                          "return {hidden:p.hidden,n:p.querySelectorAll('.mi').length}}")
        check("typing @ opens the member list", not pop["hidden"] and pop["n"] > 0, str(pop))
        check("the list holds every member of the room", pop["n"] == len(room_members), str(pop) + " vs " + str(room_members))
        pg.fill("#input", "@a"); pg.wait_for_timeout(300)
        filt = pg.evaluate("()=>[...document.querySelectorAll('#mentionPop .mi b')].map(e=>e.textContent)")
        check("typing after @ filters the list", len(filt) < pop["n"] and len(filt) >= 1, str(filt))
        # Enter picks the highlighted member instead of sending the message
        pg.eval_on_selector("#input", "e=>{e.focus();e.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))}")
        pg.wait_for_timeout(250)
        after = pg.evaluate("()=>({v:document.querySelector('#input').value,"
                            "hidden:document.querySelector('#mentionPop').hidden})")
        check("Enter inserts the mention rather than sending it", after["v"].startswith("@") and len(after["v"]) > 2, str(after))
        check("the mention is the bot's name", filt and after["v"].strip().rstrip() == "@" + filt[0], str(after) + " vs " + str(filt))
        check("the list closes once a mention is picked", after["hidden"])
        # the inserted token must be what the server matches
        pg.fill("#input", "@"); pg.wait_for_timeout(250)
        pg.eval_on_selector("#input", "e=>{e.focus();e.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))}")
        pg.wait_for_timeout(200)
        check("Escape closes the list", pg.evaluate("()=>document.querySelector('#mentionPop').hidden"))
        # a 1:1 chat has nobody to name, so @ stays a plain character
        pg.eval_on_selector_all("#chans .sub .bot", "els=>els[0].click()"); pg.wait_for_timeout(400)
        pg.fill("#input", "@"); pg.wait_for_timeout(250)
        check("a 1:1 chat does not open the member list",
              pg.evaluate("()=>document.querySelector('#mentionPop').hidden"))
        pg.fill("#input", "")

        # ---- 12. real room turn (SSE) ----
        # Run the turn in a room the suite owns, built from bots the suite owns, never the user's
        # own: a real turn writes the messages into the room's transcript, but it also writes the
        # bot's work log (data/logs/<bot>.md) and its memory notes — and running it on the user's
        # bots left test text in their real files. These bots and this room are created here and
        # deleted, with their on-disk artifacts, at cleanup. The model is copied from the user's
        # first bot so the live router is known to serve it.
        turn_room = pg.evaluate("""async()=>{
          const c=await (await fetch('/api/config')).json();
          const model=(c.bots[0]||{}).model;
          const mk=async(id,name)=>{await fetch('/api/bot',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({bot:{id,name,title:'Teammate',role:'',color:'blue',model}})});return id;};
          const a=await mk('e2e-turn-a','E2E Turn Lead'), b=await mk('e2e-turn-b','E2E Turn Mate');
          const r=await (await fetch('/api/channel',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({channel:{name:'E2E Turn Room',members:[a,b],lead:a,mode:'lead'}})}));
          const j=await r.json(); return j.channels.find(x=>x.name==='E2E Turn Room').id;
        }""")
        pg.reload(wait_until="load"); pg.wait_for_timeout(900)
        pg.evaluate("(id)=>[...document.querySelectorAll('#chans > li.group > .bot')].find(e=>e.dataset.id===id).click()", turn_room)
        pg.wait_for_timeout(500)
        # The plan card and the "its work is in" line are the *live* view of a room turn: the room's
        # saved transcript is its reports, so the redraw that lands the moment the turn stops replaces
        # them. Watch the panel as it is drawn instead of reading it afterwards — afterwards there is
        # only ever the report, which is the split working, not a missing card. The stream is tee'd so
        # the test knows when the turn is really over: the composer's Send is never disabled mid-turn,
        # so waiting on it would wait out the whole deadline and then check a panel already redrawn.
        pg.evaluate("""()=>{window.__seen=[]; window.__work=false; window.__chatDone=false;
          const rec=()=>{document.querySelectorAll('#msgs .m').forEach(n=>{
            const k=n.className; if(!window.__seen.includes(k)) window.__seen.push(k);
            if(!window.__work && (n.textContent||'').includes('its steps are in')) window.__work=true;});};
          new MutationObserver(rec).observe(document.querySelector('#msgs'),
            {childList:true,subtree:true,attributes:true,attributeFilter:['class']}); rec();
          const pf=window.fetch.bind(window);
          window.fetch=(u,o)=>{ if(!/[/]api[/]chat([?]|$)/.test(String(u))) return pf(u,o);
            return pf(u,o).then(res=>{ const [a,b]=res.body.tee();
              (async()=>{try{const rd=b.getReader(); for(;;){const{done}=await rd.read(); if(done)break;}}catch(e){}
                finally{window.__chatDone=true;}})();
              return new Response(a,{status:res.status,headers:res.headers});});};}""")
        pg.fill("#input", "In one short line, say hello and name the team.")
        pg.eval_on_selector("#btnSend", "e=>e.click()")
        deadline = time.time() + 180
        while time.time() < deadline:
            pg.wait_for_timeout(300)
            if pg.evaluate("()=>window.__chatDone"): break
        pg.wait_for_timeout(800)                    # let the post-turn redraw land
        seen = pg.evaluate("()=>window.__seen.join(',')")
        check("room turn produced a plan card", "plan" in seen, seen)
        check("room turn produced a final report", "final" in seen, seen)
        # The room is the company channel: it carries the delegation, what each bot says, and the
        # report — the shell logs belong to each member's own chat. That split is the point of a room.
        room_text = pg.evaluate("()=>document.querySelector('#msgs').textContent")
        check("the room's transcript carries no shell log",
              "tool" not in seen and "run_shell" not in room_text, seen + " | " + room_text[:200])
        # ...and the bot's words are *not* split away with them: a channel that keeps only the reports
        # reads as the user talking to nobody, which is what this room was. Read from the observer's log
        # of what was on screen *during* the turn, not the DOM after it: the redraw at the end replaces
        # the live view with the record, and a row redrawn from the record carries no `data-raw`, so
        # asking the DOM afterwards measures the redraw instead of the room. A plain `m bot` row — no
        # tool, plan, sys or final — is the bot talking, which is the thing that must be there.
        check("the room draws what the bot said, not only its closing report",
              pg.evaluate("()=>window.__seen.includes('m bot')"), seen)
        check("the room says where each bot's steps went", pg.evaluate("()=>!!window.__work"))
        check("the room's saved history keeps the report and no tool rows",
              pg.evaluate("""async(r)=>{const h=await (await fetch('/api/history?session='+encodeURIComponent(r))).json();
                return (h.messages||[]).some(m=>m.role==='assistant') && !(h.messages||[]).some(m=>m.role==='tool');}""", turn_room))
        # The hand-off is the one live card you want back when you reopen the room, so it is kept in
        # the record — without this the reload redraws the reports and loses who was on it.
        check("the room's hand-off is in the record, so it survives a reload",
              pg.evaluate("""async(r)=>{const h=await (await fetch('/api/history?session='+encodeURIComponent(r))).json();
                return (h.messages||[]).some(m=>m.role==='route' && /on it\\.$/.test(m.content||''));}""", turn_room))
        check("send button re-enabled after the turn", not pg.eval_on_selector("#btnSend", "e=>e.disabled"))
        check("card labels are single-line",
              all(h <= 20 for h in pg.eval_on_selector_all("#msgs .m .who", "els=>els.map(e=>Math.round(e.getBoundingClientRect().height))")))
        check("no JS errors after a full turn", not errors, str(errors[:3]))
        # the turn wrote only into the suite's own room, so the user's transcript is untouched
        check("the turn left every other room alone",
              pg.evaluate("""async(r)=>{
                const c=await (await fetch('/api/config')).json();
                const ids=c.channels.map(x=>x.id).concat(c.bots.map(b=>b.id)).filter(x=>x!==r);
                for(const id of ids){
                  const h=await (await fetch('/api/history?session='+encodeURIComponent(id))).json();
                  if((h.messages||[]).some(m=>String(m.content||'').includes('say hello and name the team'))) return false;
                }
                return true;
              }""", turn_room))
        pg.evaluate("async(id)=>{await fetch('/api/channel/delete',{method:'POST',"
                    "headers:{'Content-Type':'application/json'},body:JSON.stringify({id})})}", turn_room)

        # ---- 12b. switching chats mid-turn keeps the work, and keeps it out of the other chat ----
        # A turn's cards used to be written to whatever the transcript showed at that moment, so
        # switching to another chat mid-turn emptied the panel, scattered the running turn's output
        # into the wrong chat, and left nothing to come back to. The turn is driven from here rather
        # than by a model, so the mid-turn switch happens at an exact point instead of a guessed one.
        sw_rooms = pg.evaluate("""async()=>{
          const c=await (await fetch('/api/config')).json();
          const ids=c.bots.slice(0,2).map(b=>b.id);
          const mk=async(name)=>{
            const r=await (await fetch('/api/channel',{method:'POST',headers:{'Content-Type':'application/json'},
              body:JSON.stringify({channel:{name,members:ids,lead:ids[0],mode:'lead'}})}));
            return (await r.json()).channels.find(x=>x.name===name).id;
          };
          return {a:await mk('E2E Switch A'), b:await mk('E2E Switch B'), bot:ids[0],
                  name:c.bots.find(b=>b.id===ids[0]).name};
        }""")
        pg.reload(wait_until="load"); pg.wait_for_timeout(900)
        click_room = "(id)=>[...document.querySelectorAll('#chans > li.group > .bot')].find(e=>e.dataset.id===id).click()"
        pg.evaluate(click_room, sw_rooms["a"]); pg.wait_for_timeout(400)
        # A stream this test owns: /api/chat resolves to a body the test pushes events into.
        pg.evaluate("""()=>{window.__pf=window.fetch; window.__turn=null;
          window.fetch=(u,o)=>{
            if(!/[/]api[/]chat([?]|$)/.test(String(u))) return window.__pf(u,o);
            let ctrl; const body=new ReadableStream({start(c){ctrl=c;}});
            const enc=new TextEncoder();
            window.__turn={send:ev=>ctrl.enqueue(enc.encode('data: '+JSON.stringify(ev)+'\\n\\n')), end:()=>ctrl.close()};
            return Promise.resolve(new Response(body,{status:200,headers:{'Content-Type':'text/event-stream'}}));
          };}""")
        pg.fill("#input", "switch-probe task")
        pg.eval_on_selector("#btnSend", "e=>e.click()"); pg.wait_for_timeout(400)
        pg.evaluate("(ev)=>window.__turn.send(ev)", {"type": "plan", "text": "Plan: switch-probe plan."})
        pg.evaluate("(ev)=>window.__turn.send(ev)",
                    {"type": "agent", "id": sw_rooms["bot"], "name": sw_rooms["name"], "state": "start"})
        pg.evaluate("(ev)=>window.__turn.send(ev)",
                    {"type": "tool", "agent": sw_rooms["bot"], "name": "run_shell",
                     "args": {"command": "echo switch-probe"}, "out": "switch-probe"})
        pg.wait_for_timeout(300)
        check("a turn's cards stream into the chat that started it",
              pg.evaluate("()=>[...document.querySelectorAll('#msgs > .m')].some(e=>e.textContent.includes('switch-probe plan'))")
              and pg.evaluate("()=>[...document.querySelectorAll('#msgs > .m')].some(e=>e.className.includes('tool'))"))
        check("the composer stays open while its turn runs, so a task can be queued",
              not pg.eval_on_selector("#btnSend", "e=>e.disabled"))
        # Switch to a different chat while that turn is still streaming.
        pg.evaluate(click_room, sw_rooms["b"]); pg.wait_for_timeout(600)
        check("switching chats does not scatter the running turn into the new chat",
              not pg.evaluate("()=>document.querySelector('#msgs').textContent.includes('switch-probe')"))
        check("the chat you switched to says the other one is working",
              "is working" in pg.eval_on_selector("#hStatus", "e=>e.textContent"),
              pg.eval_on_selector("#hStatus", "e=>e.textContent"))
        check("the composer is open in a chat whose turn is not the running one",
              not pg.eval_on_selector("#btnSend", "e=>e.disabled"))
        check("the running chat's sidebar row still shows it working",
              pg.evaluate("(k)=>{const d=document.querySelector('.bot[data-id=\"'+k+'\"] .dot');"
                          "return !!d && d.style.background !== '';}", sw_rooms["a"] + "/" + sw_rooms["bot"]))
        # Events that arrive while the user is elsewhere must still land in the turn's own chat.
        pg.evaluate("(ev)=>window.__turn.send(ev)",
                    {"type": "tool", "agent": sw_rooms["bot"], "name": "run_shell",
                     "args": {"command": "echo later-probe"}, "out": "later-probe"})
        pg.wait_for_timeout(300)
        check("output produced while you are away stays out of the chat on screen",
              not pg.evaluate("()=>document.querySelector('#msgs').textContent.includes('later-probe')"))
        # A turn that stops to ask you something must say so in the chat you are actually looking at.
        pg.evaluate("(ev)=>window.__turn.send(ev)",
                    {"type": "approval", "cmd": "echo needs-your-go", "agent": sw_rooms["bot"]})
        pg.wait_for_timeout(300)
        check("a turn waiting on you says so, in the chat you are looking at",
              "needs your approval" in pg.eval_on_selector("#hStatus", "e=>e.textContent"),
              pg.eval_on_selector("#hStatus", "e=>e.textContent"))
        pg.evaluate("(ev)=>window.__turn.send(ev)", {"type": "status", "state": "working"})
        pg.wait_for_timeout(300)
        check("and goes back to working once the turn moves on",
              "is working" in pg.eval_on_selector("#hStatus", "e=>e.textContent"),
              pg.eval_on_selector("#hStatus", "e=>e.textContent"))
        # Coming back must show the work, not an empty panel.
        pg.evaluate(click_room, sw_rooms["a"]); pg.wait_for_timeout(600)
        back = pg.evaluate("()=>document.querySelector('#msgs').textContent")
        check("coming back shows the plan again", "switch-probe plan" in back)
        check("coming back shows the tool the turn ran", "switch-probe" in back and "later-probe" in back)
        check("the header of a running chat reads as working",
              "working" in pg.eval_on_selector("#hStatus", "e=>e.textContent"),
              pg.eval_on_selector("#hStatus", "e=>e.textContent"))
        pg.evaluate("(ev)=>window.__turn.send(ev)", {"type": "final", "text": "switch-probe report."})
        pg.wait_for_timeout(300)
        # Read the report card before `end()`: once the turn stops, the transcript is redrawn from the
        # saved history, and this stubbed turn left no server-side record to draw back — so the card
        # would be truthfully gone. What is being checked is *where* it landed: this chat, not the other.
        check("the turn finishes in the chat it belongs to",
              pg.evaluate("()=>[...document.querySelectorAll('#msgs > .m')].some(e=>e.className.includes('final'))"))
        pg.evaluate("()=>window.__turn.end()"); pg.wait_for_timeout(800)
        check("send is handed back when the turn ends",
              not pg.eval_on_selector("#btnSend", "e=>e.disabled"))
        check("no JS errors while switching mid-turn", not errors, str(errors[:3]))
        pg.evaluate("()=>{window.fetch=window.__pf}")
        # A turn that fails while you are in another chat must still leave its notice behind, and
        # must not leave it in the chat you were looking at.
        pg.evaluate("""()=>{window.__pf2=window.fetch; window.__failNext=true;
          window.fetch=(u,o)=>/[/]api[/]chat([?]|$)/.test(String(u)) && window.__failNext
            ? Promise.reject(new TypeError('Failed to fetch')) : window.__pf2(u,o);}""")
        pg.evaluate(click_room, sw_rooms["a"]); pg.wait_for_timeout(400)
        pg.fill("#input", "switch-fail task"); pg.eval_on_selector("#btnSend", "e=>e.click()")
        pg.wait_for_timeout(700)
        check("a failed turn says so in its own chat",
              pg.evaluate("()=>document.querySelector('#msgs').textContent.includes('Could not reach the server')"))
        check("the browser's own wording is not shown for a failed turn",
              pg.evaluate("()=>!document.querySelector('#msgs').textContent.includes('Failed to fetch')"))
        pg.evaluate(click_room, sw_rooms["b"]); pg.wait_for_timeout(500)
        check("a failure in another chat does not appear in this one",
              not pg.evaluate("()=>document.querySelector('#msgs').textContent.includes('Could not reach the server')"))
        check("send is handed back after a failure", not pg.eval_on_selector("#btnSend", "e=>e.disabled"))
        pg.evaluate(click_room, sw_rooms["a"]); pg.wait_for_timeout(500)
        check("coming back to a chat that failed still shows the notice",
              pg.evaluate("()=>document.querySelector('#msgs').textContent.includes('Could not reach the server')"))
        check("no JS errors after a mid-turn switch and a failure", not errors, str(errors[:3]))
        pg.evaluate("()=>{window.fetch=window.__pf2}")
        # A stream that dies after the turn had begun is a different thing from one that never
        # started: the bot may still be working, and the notice must say so rather than show the
        # browser's own "NetworkError when attempting to fetch resource.".
        pg.evaluate("""()=>{window.__pf3=window.fetch; window.__turn=null;
          window.fetch=(u,o)=>{
            if(!/[/]api[/]chat([?]|$)/.test(String(u))) return window.__pf3(u,o);
            let ctrl; const body=new ReadableStream({start(c){ctrl=c;}});
            const enc=new TextEncoder();
            window.__turn={send:ev=>ctrl.enqueue(enc.encode('data: '+JSON.stringify(ev)+'\\n\\n')),
                           fail:e=>ctrl.error(e), end:()=>ctrl.close()};
            return Promise.resolve(new Response(body,{status:200,headers:{'Content-Type':'text/event-stream'}}));
          };}""")
        pg.fill("#input", "drop-probe task"); pg.eval_on_selector("#btnSend", "e=>e.click()"); pg.wait_for_timeout(400)
        pg.evaluate("(ev)=>window.__turn.send(ev)", {"type": "status", "state": "working"})
        pg.evaluate("()=>window.__turn.fail(new TypeError('NetworkError when attempting to fetch resource.'))")
        pg.wait_for_timeout(700)
        drop = pg.evaluate("()=>document.querySelector('#msgs').textContent")
        check("a turn that drops mid-stream says the bot may still be working", "may still be working" in drop)
        check("the browser's network wording is never shown", "NetworkError" not in drop)
        check("send is handed back after a dropped stream", not pg.eval_on_selector("#btnSend", "e=>e.disabled"))
        # The server's own failure inside a turn arrives as an `error` event; it must be reported
        # rather than silently ending the turn with no report and no reason.
        pg.fill("#input", "server-error task"); pg.eval_on_selector("#btnSend", "e=>e.click()"); pg.wait_for_timeout(400)
        pg.evaluate("(ev)=>window.__turn.send(ev)", {"type": "error", "msg": "the model refused the request"})
        pg.evaluate("()=>window.__turn.end()"); pg.wait_for_timeout(700)
        se = pg.evaluate("()=>document.querySelector('#msgs').textContent")
        check("a server-side error inside a turn is reported", "the model refused the request" in se)
        check("a server-side error does not end as a silent hang", "hit an error" in se)

        # ---- 12c. a task sent mid-turn is queued, and can be steered in ----
        # Sending while a turn was running used to be refused outright (the composer was disabled).
        # A task now waits above the composer instead: leave it and it runs when the turn ends, or
        # steer it and the running turn is handed it at its next step. Driven from here, so the queue
        # is checked at an exact moment rather than a guessed one.
        pg.evaluate("""()=>{window.__pf4=window.fetch; window.__turns=[]; window.__sent=[];
          window.fetch=(u,o)=>{
            const s=String(u);
            if(s.includes('/api/chat/steer')) return Promise.resolve(new Response(
              JSON.stringify({ok:true,running:true}),{status:200,headers:{'Content-Type':'application/json'}}));
            if(!/[/]api[/]chat([?]|$)/.test(s)) return window.__pf4(u,o);
            window.__sent.push(JSON.parse(o.body).text);
            let ctrl; const body=new ReadableStream({start(c){ctrl=c;}});
            const enc=new TextEncoder();
            window.__turns.push({send:ev=>ctrl.enqueue(enc.encode('data: '+JSON.stringify(ev)+'\\n\\n')), end:()=>ctrl.close()});
            return Promise.resolve(new Response(body,{status:200,headers:{'Content-Type':'text/event-stream'}}));
          };}""")
        pg.fill("#input", "queue-probe one"); pg.eval_on_selector("#btnSend", "e=>e.click()")
        pg.wait_for_timeout(300)
        check("the first task starts a turn", pg.evaluate("()=>window.__turns.length===1"))
        # The turn is running, so a second task has nowhere to go but the queue.
        pg.fill("#input", "queue-probe two"); pg.eval_on_selector("#btnSend", "e=>e.click()")
        pg.wait_for_timeout(300)
        check("a task sent mid-turn is queued above the composer",
              pg.eval_on_selector("#queue", "e=>!e.hidden && e.textContent.includes('queue-probe two')"))
        check("the queued task has not been sent", pg.evaluate("()=>window.__turns.length===1"))
        check("the queued task is not in the transcript yet",
              not pg.evaluate("()=>document.querySelector('#msgs').textContent.includes('queue-probe two')"))
        check("the composer stays open for the next task",
              not pg.eval_on_selector("#btnSend", "e=>e.disabled"))
        # Steering: the running turn is handed the task, so it lands in that turn's transcript.
        pg.eval_on_selector("#queue .qsteer", "e=>e.click()"); pg.wait_for_timeout(300)
        pg.evaluate("(ev)=>window.__turns[0].send(ev)", {"type": "steer", "text": "queue-probe two"})
        pg.wait_for_timeout(300)
        check("steering hands the task to the turn that is already running",
              pg.evaluate("()=>document.querySelector('#msgs').textContent.includes('queue-probe two')"))
        check("the steered task leaves the queue once the turn has it",
              pg.eval_on_selector("#queue", "e=>e.hidden"))
        check("steering starts no second turn", pg.evaluate("()=>window.__turns.length===1"))
        # A task left alone must run by itself when the turn it was queued behind finishes.
        pg.fill("#input", "queue-probe three"); pg.eval_on_selector("#btnSend", "e=>e.click()")
        pg.wait_for_timeout(250)
        check("a task left in the queue waits its turn", pg.evaluate("()=>window.__turns.length===1"))
        pg.evaluate("(ev)=>window.__turns[0].send(ev)", {"type": "final", "text": "queue-probe report."})
        pg.evaluate("()=>window.__turns[0].end()"); pg.wait_for_timeout(700)
        check("the queued task runs by itself when the turn ends",
              pg.evaluate("()=>window.__turns.length===2 && window.__sent[1]==='queue-probe three'"),
              pg.evaluate("()=>JSON.stringify(window.__sent)"))
        check("and it is drawn in the transcript as your own message",
              pg.evaluate("()=>document.querySelector('#msgs').textContent.includes('queue-probe three')"))
        check("the queue is empty once it has run", pg.eval_on_selector("#queue", "e=>e.hidden"))
        pg.evaluate("()=>window.__turns[1].end()"); pg.wait_for_timeout(400)
        check("no JS errors across queueing and steering", not errors, str(errors[:3]))
        pg.evaluate("()=>{window.fetch=window.__pf3}")
        pg.evaluate("""async(ids)=>{for(const id of ids) await fetch('/api/channel/delete',{method:'POST',
          headers:{'Content-Type':'application/json'},body:JSON.stringify({id})});}""", [sw_rooms["a"], sw_rooms["b"]])

        # ---- 12d. quote a message, or forward it to another chat ----
        # A reply carries the message it answers, so the bot — which never sees the transcript — is
        # told what "this" points at; a forward is the same text delivered somewhere else, marked as
        # forwarded. Both marks belong to the message, so reopening the chat draws them back. Driven
        # from here, so the quote is checked at an exact moment rather than a guessed one.
        qf = pg.evaluate("""async()=>{
          const c=await (await fetch('/api/config')).json();
          const model=(c.bots[0]||{}).model;
          const mk=async(id,name)=>{await fetch('/api/bot',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({bot:{id,name,title:'Teammate',role:'',color:'blue',model}})});return id;};
          return {src:await mk('e2e-quote','E2E Quote'), dst:await mk('e2e-fwd','E2E Fwd')};
        }""")
        pg.reload(wait_until="load"); pg.wait_for_timeout(900)
        pg.evaluate("""()=>{window.__pfq=window.fetch; window.__bodies=[]; window.__turns=[]; window.__live=false;
          window.fetch=(u,o)=>{
            const s=String(u);
            if(!/[/]api[/]chat([?]|$)/.test(s)) return window.__pfq(u,o);
            try{ window.__bodies.push(JSON.parse(o.body)); }catch(e){ window.__bodies.push({}); }
            if(window.__live) return window.__pfq(u,o);           // a real turn, so the server keeps it
            let ctrl; const body=new ReadableStream({start(c){ctrl=c;}});
            const enc=new TextEncoder();
            window.__turns.push({send:ev=>ctrl.enqueue(enc.encode('data: '+JSON.stringify(ev)+'\\n\\n')), end:()=>ctrl.close()});
            return Promise.resolve(new Response(body,{status:200,headers:{'Content-Type':'text/event-stream'}}));
          };}""")
        pg.evaluate("(id)=>[...document.querySelectorAll('#bots .bot')].find(e=>e.dataset.id===id).click()", qf["src"])
        pg.wait_for_timeout(400)
        pg.fill("#input", "quote-probe original"); pg.eval_on_selector("#btnSend", "e=>e.click()")
        pg.wait_for_timeout(300)
        check("the original task is drawn as your own message",
              pg.evaluate("()=>document.querySelector('#msgs').textContent.includes('quote-probe original')"))
        # Reply: the quoted message waits above the composer, then travels with the next task.
        pg.evaluate("""()=>{const m=[...document.querySelectorAll('#msgs > .m')].find(e=>e.textContent.includes('quote-probe original'));
          m.querySelector('.acts .ab').click();}""")
        pg.wait_for_timeout(200)
        check("replying shows the quoted message above the composer",
              pg.eval_on_selector("#reply", "e=>!e.hidden && e.textContent.includes('quote-probe original')"))
        pg.evaluate("(ev)=>window.__turns[0].send(ev)", {"type": "final", "text": "quote-probe report."})
        pg.evaluate("()=>window.__turns[0].end()"); pg.wait_for_timeout(600)
        # The reply is a real turn, so the server's own record — and a real reopen — is what is checked.
        pg.evaluate("()=>{window.__live=true}")
        pg.fill("#input", "quote-probe answer"); pg.eval_on_selector("#btnSend", "e=>e.click()")
        # The stubbed turn has just ended, so this is a direct send; if it were still winding down the
        # task would drain from the queue instead. Either way a second real request goes out.
        bdeadline = time.time() + 30
        while time.time() < bdeadline and pg.evaluate("()=>window.__bodies.length") < 2:
            pg.wait_for_timeout(400)
        check("the reply carries the message it answers",
              pg.evaluate("()=>{const b=window.__bodies[1]||{};return !!b.quote && String(b.quote.text).includes('quote-probe original');}"),
              pg.evaluate("()=>JSON.stringify(window.__bodies[1]||{})"))
        check("the quote is drawn above the reply in the transcript",
              pg.evaluate("""()=>{const m=[...document.querySelectorAll('#msgs > .m')].find(e=>e.textContent.includes('quote-probe answer'));
                return !!m.querySelector('.quote') && m.querySelector('.quote').textContent.includes('quote-probe original');}"""))
        check("the composer's quote clears once it has been sent", pg.eval_on_selector("#reply", "e=>e.hidden"))
        qdeadline = time.time() + 60
        while time.time() < qdeadline:
            pg.wait_for_timeout(800)
            if pg.evaluate("""async(s)=>{const h=await (await fetch('/api/history?session='+encodeURIComponent(s))).json();
                return (h.messages||[]).some(m=>m.role==='user' && m.quote && String(m.quote.text).includes('quote-probe original'));}""", qf["src"]):
                break
        check("a quote is kept with the message, so reopening draws it back",
              pg.evaluate("""async(s)=>{const h=await (await fetch('/api/history?session='+encodeURIComponent(s))).json();
                return (h.messages||[]).some(m=>m.role==='user' && m.quote && String(m.quote.text).includes('quote-probe original'));}""", qf["src"]))
        # A real reload is the reopening: the mark has to come back from the server, not from the DOM.
        # It also ends the turn on the client, so the forward below is delivered rather than queued.
        pg.reload(wait_until="load"); pg.wait_for_timeout(900)
        pg.evaluate("(id)=>[...document.querySelectorAll('#bots .bot')].find(e=>e.dataset.id===id).click()", qf["src"])
        pg.wait_for_timeout(600)
        check("reopening the chat draws the quote back",
              pg.evaluate("""()=>{const q=document.querySelector('#msgs .m .quote');
                return !!q && q.textContent.includes('quote-probe original');}"""))
        # Forward: pick another chat, and the message is delivered there marked as forwarded. The reply
        # is the message forwarded — it is a real one, and it is the one carrying a quote, so the copy
        # landing with no quote is the thing being checked.
        pg.evaluate("""()=>{const m=[...document.querySelectorAll('#msgs > .m')].find(e=>e.textContent.includes('quote-probe answer'));
          m.querySelectorAll('.acts .ab')[1].click();}""")
        pg.wait_for_timeout(300)
        check("forwarding opens a picker that lists rooms and chats",
              pg.eval_on_selector(".pick", "e=>/Forward to/.test(e.textContent)")
              and pg.evaluate("()=>[...document.querySelectorAll('.pick .brow.dim')].some(r=>r.textContent.trim()==='Chats')"))
        pg.evaluate("""()=>{const r=[...document.querySelectorAll('.pick .blist .brow')].find(x=>x.textContent.includes('E2E Fwd'));
          r.click();}""")
        fdeadline = time.time() + 90
        while time.time() < fdeadline:
            pg.wait_for_timeout(800)
            if pg.evaluate("""async(s)=>{const h=await (await fetch('/api/history?session='+encodeURIComponent(s))).json();
                return (h.messages||[]).some(m=>m.role==='user' && m.fwd);}""", qf["dst"]):
                break
        check("the forward is delivered to the chat you picked",
              pg.evaluate("""async(s)=>{const h=await (await fetch('/api/history?session='+encodeURIComponent(s))).json();
                return (h.messages||[]).some(m=>m.role==='user' && m.fwd && String(m.content).includes('quote-probe answer'));}""", qf["dst"]))
        check("the forward arrives as a plain copy, with no quote attached",
              pg.evaluate("""async(s)=>{const h=await (await fetch('/api/history?session='+encodeURIComponent(s))).json();
                const m=(h.messages||[]).find(x=>x.fwd);return !!m && !m.quote;}""", qf["dst"]))
        check("no JS errors across quoting and forwarding", not js_errs(), str(js_errs()[:3]) + " | " + str(badresp[:3]))

        # ---- 13. mobile ----
        mp = ctx.new_page()
        mp.set_viewport_size({"width": 390, "height": 844})
        mp.goto(BASE, wait_until="load"); mp.wait_for_timeout(900)
        ov = mp.evaluate("()=>({sw:document.documentElement.scrollWidth, iw:window.innerWidth})")
        check("no horizontal overflow on mobile", ov["sw"] <= ov["iw"] + 2, str(ov))
        mp.eval_on_selector("#btnMenu", "e=>e.click()"); mp.wait_for_timeout(400)
        check("mobile drawer opens", mp.eval_on_selector("#side", "e=>e.classList.contains('open')"))
        # settings on mobile
        mp.eval_on_selector("#btnSettings", "e=>e.click()"); mp.wait_for_timeout(400)
        check("settings opens full-screen on mobile", mp.eval_on_selector("#scrim", "e=>e.classList.contains('on')"))
        mov = mp.evaluate("()=>({sw:document.documentElement.scrollWidth, iw:window.innerWidth})")
        check("settings has no horizontal overflow on mobile", mov["sw"] <= mov["iw"] + 2, str(mov))
        mp.screenshot(path="shots/mobile-settings.png")

        # ---- 14. import a team from BotMRR: paste a playbook, get named bots + a room ----
        pg.eval_on_selector("#btnSettings", "e=>e.click()"); pg.wait_for_timeout(400)
        pg.eval_on_selector_all("#setTabs .mtab", f"els=>els[{tabs.index('Bots')}].click()"); pg.wait_for_timeout(300)
        check("Bots tab offers 'Import a team'",
              pg.evaluate("()=>[...document.querySelectorAll('#setPanel .btn')].some(b=>/Import a team/.test(b.textContent))"))
        pg.eval_on_selector_all("#setPanel .btn", "els=>{const b=els.find(x=>/Import a team/.test(x.textContent));b.click()}")
        pg.wait_for_timeout(300)
        check("import panel shows a single heading", pg.eval_on_selector_all("#setPanel h3", "e=>e.length") == 1)
        check("import panel explains the paste", "botmrr.io" in pg.eval_on_selector("#setPanel textarea", "e=>e.placeholder"))
        # The button must hand out the structure the server accepts — so the copied text is what we
        # assert on, not that a button exists. It is read from a stubbed clipboard because the real
        # one is permission-gated in headless Chromium and would silently copy nothing.
        check("import panel offers 'Copy the structure'",
              pg.evaluate("()=>[...document.querySelectorAll('#setPanel .btn')].some(b=>/Copy the structure/.test(b.textContent))"))
        pg.evaluate("()=>{window.__copied=null;navigator.clipboard.writeText=async t=>{window.__copied=t}}")
        pg.eval_on_selector_all("#setPanel .btn", "els=>els.find(x=>/Copy the structure/.test(x.textContent)).click()")
        pg.wait_for_timeout(250)
        copied = pg.evaluate("()=>window.__copied")
        check("the copy button hands over a playbook", bool(copied) and copied.startswith("---\nbotmrr: 1"), repr((copied or "")[:24]))
        check("what it copies is the server's own template",
              copied == pg.evaluate("async()=>(await (await fetch('/api/config')).json()).team_template"))
        check("the button confirms the copy",
              "Copied" in pg.eval_on_selector_all("#setPanel .btn", "els=>els.find(x=>/Copy|Copied/.test(x.textContent)).textContent"))
        # A playbook we refuse must name every missing part, so it can be revised.
        bad = ("---\nbotmrr: 1\nagents:\n  - key: e2e-lead\n    name: Lea\n    title: Producer\n    description: Runs it.\n"
               "  - key: e2e-dev\n    name: Dima\n    title: Engineer\nrooms:\n  - key: e2e-bad\n    name: Bad\n"
               "    members:\n      - e2e-lead\n      - ghost\n    defaultResponder:\n      agent: ghost\n---\n")
        pg.eval_on_selector("#setPanel textarea", f"e=>{{e.value={json.dumps(bad)};e.dispatchEvent(new Event('input'))}}")
        pg.eval_on_selector("#setPanel .btn.pri", "e=>e.click()"); pg.wait_for_timeout(1200)
        probs = pg.eval_on_selector_all("#setPanel ul.probs li", "els=>els.map(e=>e.textContent)")
        check("a playbook missing parts is refused", "not the structure we accept" in pg.eval_on_selector("#setPanel", "e=>e.innerText"))
        check("the refusal names the missing field", any("Dima" in p and "description" in p for p in probs), str(probs))
        check("the refusal names the unknown member", any("ghost" in p and "member" in p for p in probs), str(probs))
        check("the refusal names the unknown lead", any("ghost" in p and "lead" in p for p in probs), str(probs))
        check("a refused playbook builds no bots",
              not any(b["id"] == "e2e-dev" for b in pg.evaluate("async()=>(await (await fetch('/api/config')).json()).bots")))
        playbook = ("---\nbotmrr: 1\nagents:\n"
                    "  - key: e2e-lea\n    name: Lea\n    title: Producer\n    description: Runs the show.\n"
                    "    appearance:\n      color: purple\n"
                    "  - key: e2e-alex\n    name: Alex\n    title: UI Engineer\n    description: Designs the screens.\n"
                    "    appearance:\n      color: orange\n"
                    "rooms:\n  - key: e2e-room\n    name: Import Room\n    bulletin: Ship it.\n"
                    "    members:\n      - e2e-lea\n      - e2e-alex\n"
                    "    defaultResponder:\n      agent: e2e-lea\n---\n")
        pg.eval_on_selector("#setPanel textarea", f"e=>{{e.value={json.dumps(playbook)};e.dispatchEvent(new Event('input'))}}")
        pg.eval_on_selector("#setPanel .btn.pri", "e=>e.click()"); pg.wait_for_timeout(1600)
        check("import reports the added bots", "Added 2 bots" in pg.eval_on_selector("#setPanel", "e=>e.innerText"))
        cfgimp = pg.evaluate("async()=>await (await fetch('/api/config')).json()")
        lea = next((b for b in cfgimp["bots"] if b["id"] == "e2e-lea"), {})
        alex = next((b for b in cfgimp["bots"] if b["id"] == "e2e-alex"), {})
        check("imported bots keep distinct names", lea.get("name") == "Lea" and alex.get("name") == "Alex", f"{lea.get('name')}/{alex.get('name')}")
        check("imported bots keep distinct titles", lea.get("title") == "Producer" and alex.get("title") == "UI Engineer", f"{lea.get('title')}/{alex.get('title')}")
        check("imported bot colors come from the playbook", lea.get("color") == "purple" and alex.get("color") == "orange", f"{lea.get('color')}/{alex.get('color')}")
        room = next((c for c in cfgimp["channels"] if c["id"] == "e2e-room"), {})
        check("import built the room with both members", sorted(room.get("members", [])) == ["e2e-alex", "e2e-lea"], str(room.get("members")))
        check("import took the room lead from defaultResponder", room.get("lead") == "e2e-lea", str(room.get("lead")))
        check("imported room carries the bulletin", "Ship it." in (room.get("instructions") or ""), str(room.get("instructions")))
        pg.eval_on_selector("#sClose", "e=>e.click()"); pg.wait_for_timeout(400)
        sb = pg.eval_on_selector_all("#chans .sub .subbot .nm, #bots .subbot .nm", "els=>els.map(e=>e.innerText.trim())")
        sc = pg.eval_on_selector_all("#chans > li.group > .bot .nm", "els=>els.map(e=>e.innerText.trim())")
        check("imported bots appear in the sidebar", any("Lea" in b for b in sb) and any("Alex" in b for b in sb), str(sb))
        check("imported room appears in the sidebar", any("Import Room" in c for c in sc), str(sc))

        # ---- 15. a channel can be pinned to one repo, so repos never mix ----
        pg.eval_on_selector("#btnSettings", "e=>e.click()"); pg.wait_for_timeout(400)
        pg.eval_on_selector_all("#setTabs .mtab", f"els=>els[{tabs.index('Rooms')}].click()"); pg.wait_for_timeout(300)
        pg.eval_on_selector("#addChannel", "e=>e.click()"); pg.wait_for_timeout(400)
        check("channel editor offers a repo folder",
              "REPO FOLDER" in pg.eval_on_selector("#setPanel", "e=>e.innerText"))
        check("channel editor explains the isolation",
              "never mix" in pg.eval_on_selector("#setPanel", "e=>e.innerText"))
        # inputs: 0 NAME · 1 SHARED INSTRUCTIONS · 2 REPO FOLDER
        setinp = "els=>{els[0].value='E2E Repo Room';els[0].dispatchEvent(new Event('change'));els[2].value='/tmp/e2e-not-a-real-repo-xyz';els[2].dispatchEvent(new Event('change'))}"
        pg.eval_on_selector_all("#setPanel input", setinp)
        pg.eval_on_selector("#setPanel .btn.pri", "e=>e.click()"); pg.wait_for_timeout(900)
        check("a missing repo folder is refused with a reason",
              "no folder at" in pg.eval_on_selector("#setPanel", "e=>e.innerText"))
        check("the bad folder was not saved",
              pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return !c.channels.some(x=>x.name==='E2E Repo Room')}"))
        # point it at a real folder and it saves
        pg.eval_on_selector_all("#setPanel input", "els=>{els[2].value='/tmp';els[2].dispatchEvent(new Event('change'))}")
        pg.eval_on_selector("#setPanel .btn.pri", "e=>e.click()"); pg.wait_for_timeout(900)
        roomf = pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.channels.find(x=>x.name==='E2E Repo Room')||null}")
        check("a real folder saves to the channel", bool(roomf) and roomf.get("folder") == "/tmp", str(roomf)[:120])
        check("the saved folder is reported as valid", bool(roomf) and roomf.get("folder_ok") is True)

        # a second room with no folder, so the "no repo label" checks below own the state they
        # assert on -- the real Company channel is the user's and may well be pinned to a repo
        pg.eval_on_selector("#addChannel", "e=>e.click()"); pg.wait_for_timeout(400)
        pg.eval_on_selector_all("#setPanel input",
            "els=>{els[0].value='E2E No Repo Room';els[0].dispatchEvent(new Event('change'))}")
        pg.eval_on_selector("#setPanel .btn.pri", "e=>e.click()"); pg.wait_for_timeout(900)
        norepo = pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.channels.find(x=>x.name==='E2E No Repo Room')||null}")
        check("a room with no folder saves with an empty folder", bool(norepo) and not norepo.get("folder"), str(norepo)[:120])

        # ---- 15b. the repo folder is browsable, not just a path you paste ----
        pickroot = "/tmp/e2e-pick"
        os.makedirs(os.path.join(pickroot, "parent", "child"), exist_ok=True)
        # saving closed the editor, so reopen the room's editor from the channel list
        pg.evaluate("()=>{const d=[...document.querySelectorAll('#setPanel .card')].find(x=>x.innerText.includes('E2E Repo Room'));d.querySelector('[data-a=\"edit\"]').click()}")
        pg.wait_for_timeout(500)
        check("channel editor offers a Browse button",
              pg.eval_on_selector_all("#setPanel .fldrow .btn", "els=>els.some(b=>b.innerText.includes('Browse'))"))
        pg.eval_on_selector_all("#setPanel input",
              f"els=>{{els[2].value={pickroot!r};els[2].dispatchEvent(new Event('change'))}}")
        pg.eval_on_selector("#setPanel .fldrow .btn", "e=>e.click()"); pg.wait_for_timeout(700)
        check("Browse opens a folder picker", pg.eval_on_selector_all(".modal.pick", "e=>e.length") == 1)
        check("the picker shows the folder's subfolders, not files",
              pg.evaluate("()=>{const t=document.querySelector('.blist').innerText;return t.includes('parent')&&!t.includes('.txt')}"),
              pg.eval_on_selector(".blist", "e=>e.innerText")[:120])
        check("the picker names the folder it is looking at",
              pickroot.split("/")[-1] in pg.eval_on_selector(".bpath", "e=>e.textContent"))
        # walk into parent/, then pick it
        pg.evaluate("()=>{const r=[...document.querySelectorAll('.blist .brow')].find(x=>x.innerText.trim()==='parent');r.click()}")
        pg.wait_for_timeout(700)
        check("clicking a subfolder walks into it",
              pg.eval_on_selector(".bpath", "e=>e.textContent").rstrip("/").endswith("/parent"),
              pg.eval_on_selector(".bpath", "e=>e.textContent"))
        pg.eval_on_selector('.modal.pick [data-a="use"]', "e=>e.click()"); pg.wait_for_timeout(500)
        check("the picker closes once a folder is chosen", pg.eval_on_selector_all(".modal.pick", "e=>e.length") == 0)
        check("the chosen folder lands in the field",
              pg.eval_on_selector_all("#setPanel input", "els=>els[2].value").rstrip("/").endswith("/parent"),
              pg.eval_on_selector_all("#setPanel input", "els=>els[2].value"))
        pg.eval_on_selector("#setPanel .btn.pri", "e=>e.click()"); pg.wait_for_timeout(900)
        picked = pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();const r=c.channels.find(x=>x.name==='E2E Repo Room');return r?{ok:r.folder_ok,f:r.folder}:null}")
        check("the picked folder saves and validates",
              bool(picked) and picked.get("ok") is True and picked.get("f", "").endswith("/parent"), str(picked))
        # put it back on /tmp so the header check below stays true (saving closed the editor again)
        pg.evaluate("()=>{const d=[...document.querySelectorAll('#setPanel .card')].find(x=>x.innerText.includes('E2E Repo Room'));d.querySelector('[data-a=\"edit\"]').click()}")
        pg.wait_for_timeout(500)
        pg.eval_on_selector_all("#setPanel input", "els=>{els[2].value='/tmp';els[2].dispatchEvent(new Event('change'))}")
        pg.eval_on_selector("#setPanel .btn.pri", "e=>e.click()"); pg.wait_for_timeout(800)
        pg.eval_on_selector("#sClose", "e=>e.click()"); pg.wait_for_timeout(300)
        # the room shows its repo in the header, so you always know where its bots work
        pg.reload(wait_until="load"); pg.wait_for_timeout(1000)
        pg.eval_on_selector_all("#chans > li.group > .bot", "els=>{const b=els.find(x=>x.innerText.includes('E2E Repo Room'));if(b)b.click()}")
        pg.wait_for_timeout(700)
        check("the room header names the repo", "/tmp" in pg.eval_on_selector("#hStatus", "e=>e.textContent"),
              pg.eval_on_selector("#hStatus", "e=>e.textContent"))
        pg.eval_on_selector_all("#chans > li.group > .bot", "els=>{const b=els.find(x=>x.innerText.includes('E2E No Repo Room'));if(b)b.click()}")
        pg.wait_for_timeout(600)
        check("a room with no folder shows no repo label", "repo:" not in pg.eval_on_selector("#hStatus", "e=>e.textContent"),
              pg.eval_on_selector("#hStatus", "e=>e.textContent"))
        # the point of the nesting: talking to a bot *inside* a company puts it in that company's
        # repo. E2E No Repo Room has no folder; E2E Repo Room is /tmp — same bot, two answers.
        rid = roomf.get("id")
        pg.eval_on_selector_all("#chans .sub .subbot",
            f"els=>{{const b=els.find(x=>x.dataset.id==='{rid}/producer');if(b)b.click()}}")
        pg.wait_for_timeout(700)
        check("a bot nested in a company chat shows that company's repo",
              "/tmp" in pg.eval_on_selector("#hStatus", "e=>e.textContent"),
              pg.eval_on_selector("#hStatus", "e=>e.textContent"))
        check("the scoped chat says which company it is in",
              "E2E Repo Room" in pg.eval_on_selector("#msgs", "e=>e.innerText"),
              pg.eval_on_selector("#msgs", "e=>e.innerText")[:160])
        pg.eval_on_selector_all("#chans .sub .subbot",
            "els=>{const b=els.find(x=>x.dataset.id==='e2e-no-repo-room/producer');if(b)b.click()}")
        pg.wait_for_timeout(600)
        check("the same bot under a company with no repo shows no repo",
              "repo:" not in pg.eval_on_selector("#hStatus", "e=>e.textContent"),
              pg.eval_on_selector("#hStatus", "e=>e.textContent"))
        # the user's case exactly: one bot, several companies — a separate chat in each
        prod = pg.eval_on_selector_all("#chans .sub .subbot",
            "els=>els.map(e=>e.dataset.id).filter(x=>x.endsWith('/producer'))")
        check("the same bot sits under each company as its own chat",
              len(prod) >= 2 and len(set(prod)) == len(prod), str(prod))

        # ---- 15c. a company shows its logo, not just its initials ----
        logorepo = "/tmp/e2e-logo-repo"
        os.makedirs(logorepo, exist_ok=True)
        with open(os.path.join(logorepo, "logo.svg"), "w") as fh:
            fh.write("<svg xmlns='http://www.w3.org/2000/svg' width='32' height='32'>"
                     "<rect width='32' height='32' fill='#7C5CFF'/></svg>")
        pg.eval_on_selector("#btnSettings", "e=>e.click()"); pg.wait_for_timeout(400)
        pg.eval_on_selector_all("#setTabs .mtab", f"els=>els[{tabs.index('Rooms')}].click()"); pg.wait_for_timeout(300)
        pg.eval_on_selector("#addChannel", "e=>e.click()"); pg.wait_for_timeout(400)
        pg.eval_on_selector_all("#setPanel input",
            f"els=>{{els[0].value='E2E Logo Room';els[0].dispatchEvent(new Event('change'));"
            f"els[2].value={logorepo!r};els[2].dispatchEvent(new Event('change'))}}")
        pg.eval_on_selector("#setPanel .btn.pri", "e=>e.click()"); pg.wait_for_timeout(900)
        # the logo is keyed by channel id, so the editor offers it once the channel exists
        pg.evaluate("()=>{const d=[...document.querySelectorAll('#setPanel .card')]"
                    ".find(x=>x.innerText.includes('E2E Logo Room'));d.querySelector('[data-a=\"edit\"]').click()}")
        pg.wait_for_timeout(500)
        check("the channel editor offers a logo",
              "LOGO" in pg.eval_on_selector("#setPanel", "e=>e.innerText"))
        check("a logo already in the repo is found and named",
              "logo.svg" in pg.eval_on_selector("#setPanel .lgsaid", "e=>e.innerText"),
              pg.eval_on_selector("#setPanel .lgsaid", "e=>e.innerText"))
        check("the repo logo is previewed in the editor",
              pg.eval_on_selector_all("#setPanel .lgprev img", "els=>els.length") == 1)
        # the preview has to be the same small box the row draws, not the image at its natural size
        box = pg.eval_on_selector("#setPanel .lgprev .mc.img",
            "e=>{const r=e.getBoundingClientRect();return {w:Math.round(r.width),h:Math.round(r.height)}}")
        check("the logo preview is the row's size, not the image's natural size",
              box["w"] == 46 and box["h"] == 46, str(box))
        check("no Remove button while the logo is only the repo's",
              pg.eval_on_selector_all("#setPanel .logofld button",
                  "els=>els.filter(b=>b.innerText.trim()==='Remove'&&b.offsetParent!==null).length") == 0)

        def row_img(cid):
            return pg.eval_on_selector_all("#chans > li.group > .bot",
                f"els=>{{const r=els.find(x=>x.dataset.id==='{cid}');const i=r&&r.querySelector('.mc.img img');return i?i.getAttribute('src'):''}}")
        pg.eval_on_selector("#sClose", "e=>e.click()"); pg.wait_for_timeout(400)
        check("the sidebar row shows the repo logo instead of the initials",
              row_img("e2e-logo-room").startswith("/api/logo/e2e-logo-room?"), row_img("e2e-logo-room"))
        check("a company with no logo still shows its initials",
              pg.evaluate("()=>{const r=[...document.querySelectorAll('#chans > li.group > .bot')]"
                          ".find(x=>x.innerText.includes('E2E No Repo Room'));"
                          "return r.querySelector('.mc').innerText.trim()}") == "EN",
              pg.evaluate("()=>{const r=[...document.querySelectorAll('#chans > li.group > .bot')]"
                          ".find(x=>x.innerText.includes('E2E No Repo Room'));"
                          "return r.querySelector('.mc').innerText.trim()}"))

        # uploading our own logo replaces it
        pg.eval_on_selector("#btnSettings", "e=>e.click()"); pg.wait_for_timeout(400)
        pg.eval_on_selector_all("#setTabs .mtab", f"els=>els[{tabs.index('Rooms')}].click()"); pg.wait_for_timeout(300)
        pg.evaluate("()=>{const d=[...document.querySelectorAll('#setPanel .card')]"
                    ".find(x=>x.innerText.includes('E2E Logo Room'));d.querySelector('[data-a=\"edit\"]').click()}")
        pg.wait_for_timeout(500)
        with pg.expect_file_chooser() as fc:
            pg.eval_on_selector("#setPanel .logofld button", "e=>e.click()")
        fc.value.set_files({"name": "brand.png", "mimeType": "image/png", "buffer": png1x1()})
        pg.wait_for_timeout(1200)
        check("the upload is reported as ours, not the repo's",
              "uploaded logo" in pg.eval_on_selector("#setPanel .lgsaid", "e=>e.innerText"),
              pg.eval_on_selector("#setPanel .lgsaid", "e=>e.innerText"))
        check("the Remove button appears once we own the logo",
              pg.eval_on_selector_all("#setPanel .logofld button",
                  "els=>els.some(b=>b.innerText.trim()==='Remove'&&b.offsetParent!==null)"))
        got = pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();"
                          "const x=c.channels.find(y=>y.id==='e2e-logo-room');"
                          "const r=await fetch('/api/logo/e2e-logo-room?v='+x.logo);"
                          "return {src:x.logo_src,rel:x.logo_rel,ct:r.headers.get('content-type'),"
                          "ns:r.headers.get('x-content-type-options'),len:(await r.arrayBuffer()).byteLength}}")
        check("the upload takes over from the repo logo", got["src"] == "upload" and got["rel"] == "", str(got))
        check("the stored logo is served as an image, sniffing disabled",
              got["ct"] == "image/png" and got["ns"] == "nosniff", str(got))
        check("the bytes served are the ones we uploaded", got["len"] == len(png1x1()), str(got))

        # a file that only claims to be a png is refused, and the repo logo stays in charge
        with pg.expect_file_chooser() as fc2:
            pg.eval_on_selector("#setPanel .logofld button", "e=>e.click()")
        fc2.value.set_files({"name": "sneaky.png", "mimeType": "image/png", "buffer": b"<html>not an image</html>"})
        pg.wait_for_timeout(900)
        check("a renamed file is refused with a reason, not stored",
              "not really a png" in pg.eval_on_selector("#setPanel .lgsaid", "e=>e.innerText"),
              pg.eval_on_selector("#setPanel .lgsaid", "e=>e.innerText"))
        check("the refused upload did not displace the good one",
              pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();"
                          "return c.channels.find(y=>y.id==='e2e-logo-room').logo_src}") == "upload")

        # removing our logo hands the row back to the repo's
        pg.evaluate("()=>{const b=[...document.querySelectorAll('#setPanel .logofld button')]"
                    ".find(x=>x.innerText.trim()==='Remove');b.click()}")
        pg.wait_for_timeout(1200)
        check("removing our logo falls back to the repo's",
              "logo.svg" in pg.eval_on_selector("#setPanel .lgsaid", "e=>e.innerText"),
              pg.eval_on_selector("#setPanel .lgsaid", "e=>e.innerText"))
        back = pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();"
                           "const x=c.channels.find(y=>y.id==='e2e-logo-room');"
                           "const r=await fetch('/api/logo/e2e-logo-room?v='+x.logo);"
                           "return {src:x.logo_src,rel:x.logo_rel,ct:r.headers.get('content-type')}}")
        check("the repo logo is served again, as an svg",
              back["src"] == "repo" and back["rel"] == "logo.svg" and back["ct"] == "image/svg+xml", str(back))
        pg.eval_on_selector("#sClose", "e=>e.click()"); pg.wait_for_timeout(400)
        check("the sidebar falls back to the repo logo too",
              row_img("e2e-logo-room").startswith("/api/logo/e2e-logo-room?"), row_img("e2e-logo-room"))

        # the logo endpoint is a lookup, never a path
        n0 = len(errors)
        code = pg.evaluate("async()=>{const r=await fetch('/api/logo/no-such-channel');return r.status}")
        check("an unknown channel has no logo to serve", code == 404, str(code))
        # That 404 is the point of the check, and Chromium logs every failed load as a console error —
        # so the line this probe just added is dropped here rather than blamed on the app at the end of
        # the run. Only lines added since `n0` are considered, so nothing earlier is discarded.
        errors[:] = errors[:n0] + [e for e in errors[n0:] if "Failed to load resource" not in e]
        badresp[:] = [b for b in badresp if "no-such-channel" not in b]
        code2 = raw_get(BASE + "api/logo/..%2f..%2fetc%2fpasswd", path_as_is=True)[0]
        check("a traversing logo id is not a path", code2 == 404, str(code2))
        nologo = pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();"
                             "return c.channels.find(y=>y.id==='e2e-no-repo-room').logo_src}")
        check("a company with nothing to show reports no logo at all", nologo == "", str(nologo))

        # ---- 16. every bot gets its own face: shape, motion, and eyes that track the cursor ----
        ROWS = "#chans .sub .subbot, #bots .subbot"          # every bot row, wherever it is nested
        faces = pg.evaluate("""()=>[...document.querySelectorAll('#chans .sub .subbot, #bots .subbot')].map(li=>({
            id: li.dataset.id,
            sp: (li.querySelector('canvas.sidebot')||{dataset:{}}).dataset.species || null }))""")
        check("every sidebar bot draws a live face", len(faces) > 0 and all(f["sp"] for f in faces), str(faces[:4]))
        defaults = {f["id"].split("/").pop(): f["sp"] for f in faces
                    if f["id"].split("/").pop() in ("producer","researcher","builder","qa","ops")}
        check("the five default bots each look different",
              len(defaults) == 5 and len(set(defaults.values())) == 5, str(defaults))
        anim = pg.evaluate("""async()=>{const cv=document.querySelector('#chans .sub .subbot canvas.sidebot, #bots .subbot canvas.sidebot');
            const a=cv.toDataURL(); await new Promise(r=>setTimeout(r,400)); return a!==cv.toDataURL();}""")
        check("the faces are animated, not stiff", anim)
        # Coucou's colour grading: a small face is ONE flat fill of the bot's colour, so the single
        # most common opaque pixel is exactly that colour and covers a big share of the face. The
        # gradient body it replaced had no colour that dominated — that is the pastel wash.
        COUCOU = {"purple":"7c5cff","blue":"38bdf8","green":"2ec4a0","orange":"f29b38","yellow":"eab308","pink":"ec4899"}
        grade = pg.evaluate("""async()=>{
            const mixCv=(cv)=>{ if(!cv) return null;
              const d=cv.getContext('2d').getImageData(0,0,cv.width,cv.height).data;
              const tally={}; let n=0;
              for(let i=0;i<d.length;i+=4){ if(d[i+3]<200) continue;
                const k=[d[i],d[i+1],d[i+2]].join(','); tally[k]=(tally[k]||0)+1; n++; }
              let top='',max=0; for(const k in tally) if(tally[k]>max){max=tally[k];top=k;}
              return { top, frac: n?max/n:0 }; };
            const li=document.querySelector('#chans .sub .subbot, #bots .subbot');
            const cfg=await (await fetch('/api/config')).json();
            const b=cfg.bots.find(x=>x.id===li.dataset.id.split('/').pop());
            return { face: mixCv(li.querySelector('canvas.sidebot')),
                     dock: mixCv(document.querySelector('#dockMochi')), color: b&&b.color };
        }""")
        want = COUCOU.get(grade["color"])
        exp = ",".join(str(int(want[i:i+2], 16)) for i in (0, 2, 4)) if want else ""
        check("a sidebar face is one flat fill of the bot's colour (Coucou grading)",
              bool(want) and grade["face"]["top"] == exp,
              "%s vs %s (bot=%s)" % (grade["face"]["top"], exp, grade["color"]))
        check("a flat face is dominated by that one colour",
              grade["face"]["frac"] > 0.35, str(grade["face"]))
        check("the big dock face keeps its gradient, so it has no single dominant colour",
              grade["dock"]["frac"] < grade["face"]["frac"] - 0.1,
              "dock=%s face=%s" % (grade["dock"]["frac"], grade["face"]["frac"]))
        # Coucou's palette is made for fills on a dark surface, so a monogram drawn in it is too
        # light on the light theme's near-white card. Two things must hold, and the second is the
        # one a naive fix gets wrong: the text must read on the light card, AND the hue must
        # survive. `color-mix(currentColor …)` looks right but reads the *inherited* colour on the
        # `color` property, so every monogram comes out the same grey — measure real pixels.
        mono = pg.evaluate("""()=>{
            const rel=c=>{const f=v=>{v/=255;return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4)};
              return 0.2126*f(c[0])+0.7152*f(c[1])+0.0722*f(c[2]);};
            const px=s=>s.startsWith('color(') ? s.match(/[\\d.]+/g).slice(0,3).map(v=>Math.round(+v*255))
                                              : s.match(/\\d+/g).slice(0,3).map(Number);
            const cr=(a,b)=>{const L=[rel(a),rel(b)].sort((x,y)=>y-x);return (L[0]+0.05)/(L[1]+0.05);};
            /* two monograms of different hues, built the way the app builds them */
            const d=document.createElement('div');
            d.innerHTML=['#7C5CFF','#EAB308','#38BDF8'].map((v,i)=>
              `<div class="mc" style="--mc:${v};color:var(--mc)">${i}</div>`).join('');
            document.querySelector('#side').appendChild(d);
            const read=()=>[...d.children].map(e=>{const cs=getComputedStyle(e);
              return { c:cs.color, ratio:+cr(px(cs.color), px(cs.backgroundColor)).toFixed(2) };});
            /* the theme is named by data-theme now, and the light class is derived from it, so the
               test sets the theme the way the app does and puts back whatever the user had. */
            const was=document.body.dataset.theme, wasL=document.body.classList.contains('light');
            const set=t=>{document.body.dataset.theme=t;document.body.classList.toggle('light',t==='light')};
            set('dark');  const dark=read();
            set('light'); const light=read();
            document.body.dataset.theme=was; document.body.classList.toggle('light',wasL); d.remove();
            return { dark, light }; }""")
        check("a monogram is legible on the light theme's near-white card",
              all(m["ratio"] >= 4.5 for m in mono["light"]), str(mono["light"]))
        # The dark rule is a `color-mix(... 78%,#fff)` lift, so its computed value serializes as
        # `color(srgb …)`, not `rgb(…)`. What must hold is that each monogram keeps its own colour
        # instead of collapsing to one shared grey; the percentage and the contrast it buys are
        # measured in tests/test_name_colour.mjs.
        check("and the dark theme keeps each monogram its own colour, not one shared grey",
              all(m["c"].startswith(("rgb(", "color(")) for m in mono["dark"])
              and len({m["c"] for m in mono["dark"]}) == 3, str(mono["dark"]))
        check("the light theme darkens the hue instead of greying every monogram alike",
              len({m["c"] for m in mono["light"]}) == 3, str(mono["light"]))
        # drive the real engine on a real canvas: hold the gaze left, then right, and read the ink
        gaze = pg.evaluate("""async()=>{
            const m = await import('./mochi.js');
            const cv = document.createElement('canvas');
            const b = new m.MochiBot(cv, 'idle', { size: 160, species: 'mochi' });
            const ink = () => { const g = cv.getContext('2d');
              const d = g.getImageData(0,0,cv.width,cv.height).data; let sx=0,n=0;
              for (let y=0;y<cv.height;y++) for (let x=0;x<cv.width;x++){ const i=(y*cv.width+x)*4;
                if (d[i+3]>40 && (d[i]+d[i+1]+d[i+2])/3<90){ sx+=x; n++; } }
              return n ? sx/n : -1; };
            const hold = nx => { b._actAt=999; b._act=null; b.lookAt(nx,0,true);
              for (let i=0;i<30;i++) b.tick(0.05); b.draw(); return ink(); };
            return { L: hold(-1), R: hold(1) }; }""")
        check("the eyes follow the cursor left and right",
              gaze["L"] > 0 and gaze["R"] > gaze["L"] + 2, str(gaze))
        # the face picker in the bot editor
        pg.eval_on_selector("#btnSettings", "e=>e.click()"); pg.wait_for_timeout(400)
        pg.eval_on_selector_all("#setTabs .mtab", f"els=>els[{tabs.index('Bots')}].click()"); pg.wait_for_timeout(300)
        errf = len(errors)
        pg.eval_on_selector("#setPanel .btn.pri", "e=>e.click()"); pg.wait_for_timeout(400)   # New bot
        check("the bot editor opens with no JS error", len(errors) == errf, str(errors[errf:]))
        check("the bot editor offers a face", "FACE" in pg.eval_on_selector("#setPanel", "e=>e.innerText"))
        labels = pg.eval_on_selector_all("#setPanel .seg button", "els=>els.map(e=>e.textContent.trim())")
        check("the face picker lists real species",
              all(x in labels for x in ["Cat", "Owl", "Ghost", "Robot", "Blob"]), str(labels))
        pg.eval_on_selector_all("#setPanel input", "els=>{els[0].value='E2E Face';els[0].dispatchEvent(new Event('change'))}")
        pg.eval_on_selector_all("#setPanel .seg button", "els=>{const b=els.find(x=>x.textContent.trim()==='Ghost');if(b)b.click()}")
        pg.wait_for_timeout(250)
        pg.eval_on_selector("#setPanel .btn.pri", "e=>e.click()"); pg.wait_for_timeout(900)   # Save bot
        saved = pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();const b=c.bots.find(x=>x.name==='E2E Face');return b?b.face:null}")
        check("the chosen face is saved on the bot", saved == "ghost", str(saved))
        pg.eval_on_selector("#sClose", "e=>e.click()"); pg.wait_for_timeout(600)
        drawn = pg.evaluate("""()=>{const li=[...document.querySelectorAll('#chans .sub .subbot, #bots .subbot')].find(x=>x.innerText.includes('E2E Face'));
            const cv=li&&li.querySelector('canvas.sidebot'); return cv ? cv.dataset.species : null;}""")
        check("the sidebar draws the chosen face", drawn == "ghost", str(drawn))
        # the corner mascot wears the face of whoever you are talking to, so it always says
        # which bot is speaking; a room has no single bot, so it keeps the general Mochi
        pairs = pg.evaluate("""()=>[...document.querySelectorAll('#chans .sub .subbot, #bots .subbot')].map(li=>({
            id: li.dataset.id,
            sp: (li.querySelector('canvas.sidebot')||{dataset:{}}).dataset.species || null }))""")
        mism = []
        for f in pairs[:5]:
            pg.eval_on_selector_all("#chans .sub .subbot, #bots .subbot", f"els=>{{const b=els.find(x=>x.dataset.id==='{f['id']}');if(b)b.click()}}")
            pg.wait_for_timeout(220)
            d = pg.eval_on_selector("#dockMochi", "e=>e.dataset.species")
            if d != f["sp"]:
                mism.append((f["id"], d, f["sp"]))
        check("the dock mascot wears the active bot's face", not mism, str(mism))
        pg.eval_on_selector_all("#chans > li.group > .bot", "els=>{const b=els.find(x=>x.innerText.includes('Company'));if(b)b.click()}")
        pg.wait_for_timeout(300)
        check("a room falls back to the general Mochi face",
              pg.eval_on_selector("#dockMochi", "e=>e.dataset.species") == "mochi",
              pg.eval_on_selector("#dockMochi", "e=>e.dataset.species"))

        # ---- 16b. a bot's look: outfit, accessory and a face picture ----
        # The wardrobe axes live in the Look group and are drawn by mochi.js, so these checks are
        # about the *editor* wiring: the pickers exist and repaint the preview, the choice is saved on
        # the bot, and a picture introduced once becomes the face the sidebar draws. The engine itself
        # (every garment on every species, and the picture standing in for the drawn eyes and mouth)
        # is covered by tests/test_mochi.mjs.
        pg.eval_on_selector("#btnSettings", "e=>e.click()"); pg.wait_for_timeout(400)
        pg.eval_on_selector_all("#setTabs .mtab", f"els=>els[{tabs.index('Bots')}].click()"); pg.wait_for_timeout(300)
        pg.eval_on_selector("#setPanel .btn.pri", "e=>e.click()"); pg.wait_for_timeout(400)   # New bot
        looktxt = pg.eval_on_selector("#setPanel", "e=>e.innerText")
        check("the bot editor offers a look: outfit, accessory and a face picture",
              all(k in looktxt for k in ["OUTFIT", "ACCESSORY", "FACE PICTURE"]))
        segs = pg.evaluate("""()=>{const g=[...document.querySelectorAll('#setPanel .fgroup')]
            .find(e=>e.querySelector('h4') && e.querySelector('h4').textContent==='Look');
            return g ? [...g.querySelectorAll('.seg')].map(s=>[...s.children].map(c=>c.textContent.trim())) : [];}""")
        check("the Look group has face, outfit and accessory pickers", len(segs) == 3, str(segs))
        check("the outfit picker lists the garments and a None",
              len(segs) == 3 and all(k in segs[1] for k in ["None", "Scarf", "Tie", "Collar", "Apron", "Mantle", "Bow tie"]), str(segs[1:2]))
        check("the accessory picker lists the accessories and a None",
              len(segs) == 3 and all(k in segs[2] for k in ["None", "Glasses", "Hat", "Crown"]), str(segs[2:3]))
        pg.eval_on_selector_all("#setPanel input", "els=>{els[0].value='E2E Look';els[0].dispatchEvent(new Event('change'))}")
        prev_png = "()=>{const g=[...document.querySelectorAll('#setPanel .fgroup')].find(e=>e.querySelector('h4')&&e.querySelector('h4').textContent==='Look');const cv=g&&g.querySelector('canvas');return cv?cv.toDataURL():'';}"
        bare = pg.evaluate(prev_png)
        check("the Look group has its own preview canvas", bool(bare), str(len(bare)))
        pg.eval_on_selector_all("#setPanel .seg button", "els=>{const b=els.find(x=>x.textContent.trim()==='Scarf');if(b)b.click()}")
        pg.wait_for_timeout(350)
        dressed = pg.evaluate(prev_png)
        check("picking an outfit repaints the preview", dressed and dressed != bare)
        pg.eval_on_selector_all("#setPanel .seg button", "els=>{const b=els.find(x=>x.textContent.trim()==='Crown');if(b)b.click()}")
        pg.wait_for_timeout(350)
        check("picking an accessory repaints it again",
              pg.evaluate(prev_png) not in (bare, dressed))
        # One control, and it does the whole job: introduce an image → the image model redraws it as
        # this bot's face. There is no second "upload it as-is" button — two controls for one idea is
        # the confusion this replaces — so the count is the check.
        face_fld = pg.locator("#setPanel .fld", has_text="FACE PICTURE")
        ctrls = face_fld.locator("button:visible").all_inner_texts()
        check("the face picture is one control, not two", ctrls == ["Introduce an image"], str(ctrls))
        check("the old two-button split is gone",
              not pg.evaluate("()=>[...document.querySelectorAll('#setPanel button')]"
                              ".some(b=>/Upload a picture|Transform a photo|Transform this photo/.test(b.textContent))"))
        # What that control sends. The transform is 30-60s of real work at the router, so the call is
        # answered here rather than waited out — the payload is what is being checked: the picture,
        # and the species and colour the face is being drawn for.
        pg.evaluate("""()=>{window.__av=null; const pf=window.fetch.bind(window);
          window.fetch=(u,o)=>{const s=String(u);
            if(!/[/]api[/]avatar[/]transform/.test(s)) return pf(u,o);
            try{ window.__av=JSON.parse(o.body); }catch(e){ window.__av={}; }
            return Promise.resolve(new Response(JSON.stringify({ok:true,avatar:0}),
              {status:200,headers:{'Content-Type':'application/json'}}));};}""")
        face_fld.locator("input[type=file]").set_input_files(
            files=[{"name": "face.png", "mimeType": "image/png", "buffer": png_blob(64)}])
        pg.wait_for_timeout(900)
        payload = pg.evaluate("()=>window.__av") or {}
        check("introducing an image sends it to the transform, for this bot's species and colour",
              str(payload.get("data", "")).startswith("data:image/png;base64,")
              and payload.get("species") and payload.get("color"), str(payload)[:160])
        pg.eval_on_selector("#setPanel .btn.pri", "e=>e.click()"); pg.wait_for_timeout(1000)   # Save bot
        lookbot = next((b for b in pg.evaluate("async()=>(await (await fetch('/api/config')).json()).bots")
                        if b["name"] == "E2E Look"), {})
        check("the outfit and accessory are saved on the bot",
              lookbot.get("outfit") == "scarf" and lookbot.get("accessory") == "crown", str(lookbot)[:120])
        # ...and a picture in place is served and drawn. Stored through POST /api/avatar, which is the
        # phone's own path to the same slot (the desktop's is the transform above). The fixture is a
        # plain background with a centred subject — a flat single-colour image would be keyed out
        # entirely, which is the point of the keying.
        av = pg.evaluate("""async(id)=>{
            const png = %s;
            const r = await fetch('/api/avatar',{method:'POST',headers:{'Content-Type':'application/json'},
              body: JSON.stringify({id, data: 'data:image/png;base64,'+png})});
            return (await r.json()).avatar || 0; }""" % json.dumps(__import__("base64").b64encode(png_blob()).decode()), lookbot.get("id"))
        check("a picture is accepted as the bot's face", bool(av), str(av))
        check("the picture is served back as an image",
              pg.evaluate("async(id)=>{const r=await fetch('/api/avatar/'+id);return [r.status, r.headers.get('content-type')]}", lookbot.get("id")) == [200, "image/png"])
        pg.reload(wait_until="load"); pg.wait_for_timeout(1200)
        drawn_av = pg.evaluate("""()=>{const li=[...document.querySelectorAll('#chans .sub .subbot, #bots .subbot')]
            .find(x=>x.innerText.includes('E2E Look'));const cv=li&&li.querySelector('canvas.sidebot');
            return cv?cv.toDataURL():'';}""")
        check("the sidebar draws the picture on the bot", bool(drawn_av), str(len(drawn_av)))
        check("no JS error from the look editor", not js_errs(), str(js_errs()[:3]) + " | " + str(badresp[:3]))

        # ---- 17. a bot's markdown reply is rendered, not shown raw ----
        # The reply is stubbed so the checks are about the renderer, not about what a model happens
        # to write. It goes through the real SSE path, so the whole client chain is exercised.
        md = ("## Findings\n\n**bold** and *italic* and `code`.\n\n"
              "| Bot | Model |\n| --- | --- |\n| Producer | qwen |\n| Builder | llama |\n\n"
              "- one\n- two\n\n1. first\n2. second\n\n> quoted <tag>\n\n```py\nprint(1)\n```\n\n"
              "[docs](https://example.com) and [bad](javascript:alert(1))\n\n"
              "<script>alert(1)</script> and <b>raw html</b>\n")
        # A finished turn is redrawn from the saved history, so the two stubs have to agree: /api/chat
        # records what it was sent, and /api/history hands that same transcript back. Without the
        # history stub the redraw is truthfully empty and there is nothing on screen to check.
        md_msgs = []
        def md_chat(route):
            try: sent = json.loads(route.request.post_data or "{}").get("text", "")
            except Exception: sent = ""
            if sent: md_msgs.append({"role": "user", "content": sent, "ts": time.time()})
            md_msgs.append({"role": "assistant", "who": "Producer", "content": md, "ts": time.time()})
            body = "".join("data: " + json.dumps(ev) + "\n\n" for ev in [
                {"type": "agent_text", "agent": "producer", "text": md}, {"type": "final", "text": "done"}])
            route.fulfill(status=200, content_type="text/event-stream", body=body)
        def md_hist(route):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"model": "e2e/quick-model", "messages": md_msgs}))
        pg.route("**/api/chat", md_chat); pg.route("**/api/history*", md_hist)
        pg.fill("#input", "render this")
        pg.eval_on_selector("#btnSend", "e=>e.click()"); pg.wait_for_timeout(900)
        # the reply rides in its own bubble; the `final` event adds a report card after it, and the
        # transcript still holds earlier chats, so read the newest bubble that carries the heading
        LAST = "[...document.querySelectorAll('#msgs .md')].filter(m=>m.querySelector('h2')).pop()"
        check("a heading renders as a heading",
              pg.evaluate(f"()=>{{const m={LAST}||document.createElement('div');return [...m.querySelectorAll('h2')].map(x=>x.textContent)}}") == ["Findings"])
        check("bold and italic render as elements",
              pg.evaluate(f"()=>{{const m={LAST}||document.createElement('div');return !!m.querySelector('strong')&&!!m.querySelector('em')}}"))
        check("inline code renders as code",
              pg.evaluate(f"()=>{{const c={LAST}||document.createElement('div');const k=c.querySelector('code');return !!k&&k.textContent==='code'}}"))
        tbl = pg.evaluate(f"()=>{{const t={LAST}||document.createElement('div');const q=t.querySelector('table');if(!q)return null;"
                          "return {head:[...q.querySelectorAll('th')].map(e=>e.textContent),"
                          "rows:[...q.querySelectorAll('tbody tr')].map(r=>[...r.children].map(c=>c.textContent))}}")
        check("a table renders with its header and rows",
              bool(tbl) and tbl["head"] == ["Bot", "Model"] and tbl["rows"] == [["Producer", "qwen"], ["Builder", "llama"]],
              str(tbl)[:200])
        check("a bullet list renders as list items",
              pg.evaluate(f"()=>{{const m={LAST}||document.createElement('div');return [...m.querySelectorAll('ul li')].map(x=>x.textContent)}}") == ["one", "two"])
        check("a numbered list renders as ol/li",
              pg.evaluate(f"()=>{{const m={LAST}||document.createElement('div');return [...m.querySelectorAll('ol li')].map(x=>x.textContent)}}") == ["first", "second"])
        check("a blockquote renders, and its text is escaped exactly once",
              pg.evaluate(f"()=>({LAST})?.querySelector('blockquote')?.textContent") == "quoted <tag>",
              str(pg.evaluate(f"()=>({LAST})?.querySelector('blockquote')?.textContent")))
        check("a fenced block renders as pre>code",
              pg.evaluate(f"()=>({LAST})?.querySelector('pre code')?.textContent") == "print(1)")
        check("a link keeps a real href",
              pg.evaluate(f"()=>({LAST})?.querySelector('a')?.getAttribute('href')") == "https://example.com")
        check("a javascript: link is made inert",
              pg.evaluate(f"()=>[...(({LAST})?.querySelectorAll('a')||[])].map(x=>x.getAttribute('href'))").count("#") == 1)
        check("raw html in a reply is shown as text, never parsed",
              pg.evaluate(f"()=>({LAST})?.querySelectorAll('b, script').length") == 0
              and "<b>raw html</b>" in (pg.evaluate(f"()=>({LAST})?.innerText") or ""),
              (pg.evaluate(f"()=>({LAST})?.innerText") or "")[:120])
        # a person's own text is not markdown: a shell command must survive as typed
        pg.fill("#input", "*not italic* and `not code`")
        pg.eval_on_selector("#btnSend", "e=>e.click()"); pg.wait_for_timeout(500)
        check("a person's own message is shown exactly as typed, not rendered",
              pg.evaluate("()=>{const m=[...document.querySelectorAll('#msgs .m.user')].pop();"
                          "return m.textContent.includes('*not italic*')&&!m.querySelector('.md,em,code')}"))
        pg.unroute("**/api/chat"); pg.unroute("**/api/history*")

        # ---- 18. the model chip names the real model, and switches it on the spot ----
        pg.evaluate("""async()=>{for(const m of ['e2e/quick-model','e2e/other-model'])
            await fetch('/api/models/add',{method:'POST',headers:{'Content-Type':'application/json'},
              body:JSON.stringify({model:m})});
            await fetch('/api/bot',{method:'POST',headers:{'Content-Type':'application/json'},
              body:JSON.stringify({bot:{id:'e2e-quick',name:'E2E Quick',model:'e2e/quick-model',
                title:'Teammate',role:'',color:'blue'}})});}""")
        pg.reload(wait_until="load"); pg.wait_for_timeout(900)
        pg.evaluate("()=>{const b=document.querySelector('#bots .subbot[data-id=\"e2e-quick\"]');if(b)b.click()}")
        pg.wait_for_timeout(700)
        check("the chip shows the bot's own model, not a stale default",
              pg.eval_on_selector("#chipModel", "e=>e.textContent.trim()") == "Model: e2e/quick-model",
              pg.eval_on_selector("#chipModel", "e=>e.textContent"))
        pg.eval_on_selector("#chipModel", "e=>e.click()"); pg.wait_for_timeout(300)
        check("clicking the chip opens a model menu instead of Settings",
              pg.eval_on_selector_all("#mmPop", "e=>e.length") == 1
              and not pg.eval_on_selector("#scrim", "e=>e.classList.contains('on')"))
        check("the menu lists the models in your list",
              pg.evaluate("()=>[...document.querySelectorAll('#mmPop .mrow b')].some(b=>b.textContent==='e2e/quick-model')"))
        check("the menu marks the model that is in use",
              pg.evaluate("()=>{const r=[...document.querySelectorAll('#mmPop .mrow')].find(x=>x.classList.contains('on'));"
                          "return r?r.textContent.trim():''}") == "e2e/quick-model",
              pg.evaluate("()=>[...document.querySelectorAll('#mmPop .mrow.on')].map(x=>x.textContent)"))
        pg.evaluate("()=>{const r=[...document.querySelectorAll('#mmPop .mrow')]"
                    ".find(x=>x.querySelector('b')&&x.querySelector('b').textContent==='e2e/other-model');r.click()}")
        pg.wait_for_timeout(600)
        check("picking a model changes the chip at once",
              pg.eval_on_selector("#chipModel", "e=>e.textContent.trim()") == "Model: e2e/other-model",
              pg.eval_on_selector("#chipModel", "e=>e.textContent"))
        check("the switch sticks to the chat",
              pg.evaluate("async()=>{const h=await (await fetch('/api/history?session=e2e-quick')).json();return h.model}") == "e2e/other-model")
        pg.eval_on_selector("#chipModel", "e=>e.click()"); pg.wait_for_timeout(300)
        pg.evaluate("()=>{const r=[...document.querySelectorAll('#mmPop .mrow')].find(x=>/own model/.test(x.textContent));r.click()}")
        pg.wait_for_timeout(600)
        check("clearing the pick goes back to the bot's own model",
              pg.eval_on_selector("#chipModel", "e=>e.textContent.trim()") == "Model: e2e/quick-model",
              pg.eval_on_selector("#chipModel", "e=>e.textContent"))
        check("the menu closes once a model is picked", pg.eval_on_selector_all("#mmPop", "e=>e.length") == 0)

        # ---- 18b. the Approval chip is a switch scoped to the chat, not a door to the Bots list ----
        # It used to open Settings → Bots (every bot you own). It must instead offer the levels in
        # place: only the levels in a 1:1 chat, and in a room only that room's own members.
        levels_shown = pg.evaluate("""()=>{const c=document.querySelector('#chipMem');c.click();
          return [...document.querySelectorAll('#apPop .mrow b')].map(b=>b.textContent)}""")
        pg.wait_for_timeout(250)
        check("clicking the Approval chip opens a menu, not Settings",
              pg.eval_on_selector_all("#apPop", "e=>e.length") == 1
              and not pg.eval_on_selector("#scrim", "e=>e.classList.contains('on')"),
              str(levels_shown))
        check("the menu lists the approval levels",
              levels_shown == ["Plan only", "Ask for approval", "Auto-accept edits", "Approve routine", "Full access"],
              str(levels_shown))
        check("there is no 'Custom (config)' level left to pick",
              not any("custom" in (t or "").lower() for t in levels_shown), str(levels_shown))
        check("a 1:1 chat shows no member list",
              pg.eval_on_selector_all("#apPop .aprow", "e=>e.length") == 0)
        # pick a level and prove it lands on this chat only
        pg.evaluate("""()=>{const r=[...document.querySelectorAll('#apPop .mrow')]
          .find(x=>x.querySelector('b')&&x.querySelector('b').textContent==='Plan only');r.click()}""")
        pg.wait_for_timeout(600)
        check("picking a level closes the menu and names it on the chip",
              pg.eval_on_selector_all("#apPop", "e=>e.length") == 0
              and pg.eval_on_selector("#chipMem", "e=>e.textContent") == "Approval: Plan",
              pg.eval_on_selector("#chipMem", "e=>e.textContent"))
        check("the level sticks to the chat it was set on",
              pg.evaluate("async()=>{const h=await (await fetch('/api/history?session=e2e-quick')).json();return h.approval}") == "plan")
        # a room shows exactly its own members — never every bot
        pg.evaluate("""async()=>{
          await fetch('/api/bot',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({bot:{id:'e2e-quick2',name:'E2E Quick Two',model:'e2e/quick-model',
              title:'Teammate',role:'',color:'green'}})});
          await fetch('/api/channel',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({channel:{name:'E2E Approval Room',members:['e2e-quick','e2e-quick2'],lead:'e2e-quick'}})});}""")
        pg.reload(wait_until="load"); pg.wait_for_timeout(900)
        pg.evaluate("""()=>{const r=[...document.querySelectorAll('#chans .bot')]
          .find(x=>x.dataset.id==='e2e-approval-room');if(r)r.click()}""")
        pg.wait_for_timeout(700)
        room = pg.evaluate("""()=>{document.querySelector('#chipMem').click();
          const pop=document.querySelector('#apPop');
          return {levels:pop.querySelectorAll('.mrow').length,
                  pickers:pop.querySelectorAll('.aprow select').length,
                  head:(pop.querySelector('.aphead')||{}).textContent||""}}""")
        pg.wait_for_timeout(200)
        check("in a room the menu still lists the levels", room["levels"] == 5, str(room))
        check("the room's menu says it is setting the room",
              "this room" in room["head"], str(room["head"]))
        check("a room shows no per-member level pickers", room["pickers"] == 0, str(room))
        pg.evaluate("()=>document.querySelector('#chipMem').click()"); pg.wait_for_timeout(150)

        # ---- 18c. a channel has one level, and the chip names it ----
        # A room used to fall back to each member's own default and to list a picker per member, so
        # the chip read "each member's own" while every member ran at whatever its own row said — and
        # a level picked on the room never reached a member's nested chat, which is a different
        # session. The room's level is now the only level inside a channel.
        check("a room with no level of its own says it is on Ask",
              pg.eval_on_selector("#chipMem", "e=>e.textContent") == "Approval: Ask",
              pg.eval_on_selector("#chipMem", "e=>e.textContent"))
        # set the room's level, then check the chip names it
        pg.evaluate("""()=>{const c=document.querySelector('#chipMem');c.click();
          const r=[...document.querySelectorAll('#apPop .mrow')]
            .find(x=>x.querySelector('b')&&x.querySelector('b').textContent==='Plan only');r.click()}""")
        pg.wait_for_timeout(600)
        check("picking a level on the room names it on the chip",
              pg.eval_on_selector("#chipMem", "e=>e.textContent") == "Approval: Plan",
              pg.eval_on_selector("#chipMem", "e=>e.textContent"))
        check("the level is stored on the room itself",
              pg.evaluate("async()=>{const h=await (await fetch('/api/history?session=e2e-approval-room')).json();return h.approval}") == "plan")
        check("history tells the client this chat is a channel",
              pg.evaluate("async()=>{const h=await (await fetch('/api/history?session=e2e-approval-room')).json();return h.approval_kind}") == "room")
        check("a channel reports no per-member fallback to show",
              pg.evaluate("async()=>{const h=await (await fetch('/api/history?session=e2e-approval-room')).json();return h.approval_own}") is None)
        # a member's nested chat is the same workspace: it shows the room's level, and a level picked
        # from that row is written to the room, so the room row and the member row cannot disagree
        pg.evaluate("""()=>{const b=document.querySelector('#chans .sub .subbot[data-id="e2e-approval-room/e2e-quick"]');if(b)b.click()}""")
        pg.wait_for_timeout(700)
        check("a member's nested chat shows the room's level, not the bot's",
              pg.eval_on_selector("#chipMem", "e=>e.textContent") == "Approval: Plan",
              pg.eval_on_selector("#chipMem", "e=>e.textContent"))
        check("and reports itself as a channel too",
              pg.evaluate("async()=>{const h=await (await fetch('/api/history?session=e2e-approval-room%2Fe2e-quick')).json();return h.approval_kind}") == "room")
        pg.evaluate("""()=>{document.querySelector('#chipMem').click();
          [...document.querySelectorAll('#apPop .mrow')]
            .find(x=>x.querySelector('b')&&x.querySelector('b').textContent==='Full access').click()}""")
        pg.wait_for_timeout(600)
        check("a level picked from a member's row lands on the room",
              pg.evaluate("async()=>{const h=await (await fetch('/api/history?session=e2e-approval-room')).json();return h.approval}") == "full")
        check("and the member's row shows it too",
              pg.eval_on_selector("#chipMem", "e=>e.textContent") == "Approval: Full",
              pg.eval_on_selector("#chipMem", "e=>e.textContent"))
        # A 1:1 chat follows its bot's own level — the case the channel rule must not break. e2e-quick
        # picked a level on itself back in 18b, so clear that first, then put the bot on Full access.
        pg.evaluate("""async()=>{
          await fetch('/api/approval_mode',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({session:'e2e-quick',mode:''})});
          await fetch('/api/bot',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({bot:{id:'e2e-quick',approval:'full'}})})}""")
        # clean up the throwaway room + bot (the sweep also covers leftovers on the next run)
        pg.evaluate("""async()=>{
          await fetch('/api/channel/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:'e2e-approval-room'})});
          await fetch('/api/bot/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:'e2e-quick2'})});}""")
        pg.reload(wait_until="load"); pg.wait_for_timeout(900)
        pg.evaluate("""()=>{const b=document.querySelector('#bots .subbot[data-id="e2e-quick"]');if(b)b.click()}""")
        pg.wait_for_timeout(700)
        check("outside a channel a chat follows its bot's own level",
              pg.eval_on_selector("#chipMem", "e=>e.textContent") == "Approval: Full · bot default",
              pg.eval_on_selector("#chipMem", "e=>e.textContent"))
        check("history reports the bot's own level as the fallback",
              pg.evaluate("async()=>{const h=await (await fetch('/api/history?session=e2e-quick')).json();return h.approval_own}") == "full")
        check("and reports this chat is not a channel",
              pg.evaluate("async()=>{const h=await (await fetch('/api/history?session=e2e-quick')).json();return h.approval_kind}") == "bot")
        # set a level on the chat, then hand it back — the 1:1 way out that only a 1:1 chat needs
        pg.evaluate("""()=>{document.querySelector('#chipMem').click();
          [...document.querySelectorAll('#apPop .mrow')]
            .find(x=>x.querySelector('b')&&x.querySelector('b').textContent==='Plan only').click()}""")
        pg.wait_for_timeout(600)
        check("a level set on a 1:1 chat is shown as its own",
              pg.eval_on_selector("#chipMem", "e=>e.textContent") == "Approval: Plan",
              pg.eval_on_selector("#chipMem", "e=>e.textContent"))
        pg.evaluate("""()=>{document.querySelector('#chipMem').click();
          [...document.querySelectorAll('#apPop .mrow')]
            .find(x=>x.textContent.includes("own level")).click()}""")
        pg.wait_for_timeout(600)
        check("handing the chat back to its bot shows the bot's own level",
              pg.eval_on_selector("#chipMem", "e=>e.textContent") == "Approval: Full · bot default",
              pg.eval_on_selector("#chipMem", "e=>e.textContent"))
        check("and the chat really carries no level of its own now",
              pg.evaluate("async()=>{const h=await (await fetch('/api/history?session=e2e-quick')).json();return h.approval}") is None)
        pg.reload(wait_until="load"); pg.wait_for_timeout(800)

        # ---- 19. the context window is settable, and compression is on by default ----
        SETF2 = os.path.join(DATA, "settings.json")
        snap2 = json.load(open(SETF2))
        try:
            pg.eval_on_selector("#btnSettings", "e=>e.click()"); pg.wait_for_timeout(400)
            pg.eval_on_selector("#tab-models", "e=>e.click()"); pg.wait_for_timeout(300)
            eng = pg.eval_on_selector("#setPanel", "e=>e.innerText")
            check("AI model offers a context limit", "CONTEXT LIMIT" in eng)
            check("AI model explains that 0 follows the model", "follows the model" in eng)
            check("AI model offers compression", "Compress when it runs out" in eng)
            check("the limit is prefilled with what is saved",
                  pg.eval_on_selector("#setPanel input[type=number]", "e=>e.value") == str(snap2["context"]["limit"]),
                  pg.eval_on_selector("#setPanel input[type=number]", "e=>e.value"))
            pg.evaluate("()=>{const i=document.querySelector('#setPanel input[type=number]');i.value='9000';i.dispatchEvent(new Event('change'))}")
            pg.wait_for_timeout(700)
            check("a context limit saves",
                  pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.settings.context.limit}") == 9000)
            check("a negative limit is refused, not stored", pg.evaluate("""async()=>{
                const i=document.querySelector('#setPanel input[type=number]');i.value='-5';i.dispatchEvent(new Event('change'));
                await new Promise(r=>setTimeout(r,500));
                const c=await (await fetch('/api/config')).json();return c.settings.context.limit}""") == 0)
        finally:
            json.dump(snap2, open(SETF2, "w"), indent=2)
        check("the test hands the real context setting back",
              pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.settings.context.limit}")
              == snap2["context"]["limit"])

        # ---- 19b. the context chip: how full the window is, and what filled it on hover ----
        # The server measures each request as it goes out and sends a `ctx` payload back with the turn
        # that produced it, so the chip is a readout of a real request rather than a running guess.
        # The turn is stood in for here, so this checks the wiring and the arithmetic, not the router.
        ctx_turn = {"evs": []}
        pg.route("**/api/chat", lambda r: r.fulfill(status=200, content_type="text/event-stream",
            body="".join("data: " + json.dumps(e) + "\n\n" for e in ctx_turn["evs"])))
        try:
            pg.eval_on_selector("#sClose", "e=>e.click()"); pg.wait_for_timeout(300)
            ctx_turn["evs"] = [{"type": "status", "state": "working"},
                {"type": "ctx", "ctx": {"tokens": 152200, "limit": 200000, "model": "m", "hit": 891, "seen": 1000,
                    "rows": [{"label": "Messages", "tokens": 137900}, {"label": "System tools", "tokens": 8371},
                             {"label": "Connected apps", "tokens": 4718}, {"label": "System prompt", "tokens": 609},
                             {"label": "Skills", "tokens": 609}, {"label": "Memory & context", "tokens": 152}]}},
                {"type": "status", "state": "finished"}, {"type": "done"}]
            pg.fill("#input", "count the context"); pg.eval_on_selector("#btnSend", "e=>e.click()")
            pg.wait_for_timeout(900)
            check("the chip says how full the window is",
                  pg.eval_on_selector("#chipCtx", "e=>e.textContent").strip() == "Context: 76%",
                  pg.eval_on_selector("#chipCtx", "e=>e.textContent"))
            check("a window with room left is not flagged", "hot" not in pg.eval_on_selector("#chipCtx", "e=>e.className"))
            pg.hover("#chipCtx"); pg.wait_for_timeout(400)
            pop = pg.evaluate("""()=>{const p=document.querySelector('#ctxpop'); if(!p) return null;
                const rows=[...p.querySelectorAll('.ctxrow')].map(r=>[r.querySelector('.lbl').textContent,
                    +r.querySelector('.pct').textContent.replace('%','')]);
                return { vis:getComputedStyle(p).display!=='none', rows,
                    head:(p.querySelector('.ctxhead b')||{}).textContent||'',
                    foot:(p.querySelector('.ctxfoot')||{}).textContent||'',
                    fill:(p.querySelector('.ctxfill')||{}).style.width||'',
                    segs:p.querySelectorAll('.ctxfill i').length }; }""")
            check("hovering the chip opens the panel", bool(pop and pop["vis"]), str(pop))
            check("the panel names the window and the count",
                  pop and pop["head"] == "152.2K / 200.0K (76.1%)", str(pop and pop["head"]))
            check("the panel lists every part that took room", pop and len(pop["rows"]) == 6, str(pop and pop["rows"]))
            check("the parts are shares of what was used, so they add up to the whole",
                  pop and abs(sum(r[1] for r in pop["rows"]) - 100) < 0.5,
                  str(pop and sum(r[1] for r in pop["rows"])))
            check("the transcript is the biggest share, as the split says",
                  pop and pop["rows"][0][0] == "Messages" and pop["rows"][0][1] > 90, str(pop and pop["rows"][0]))
            check("the stacked bar is filled to the same fraction the chip names",
                  pop and pop["fill"].startswith("76"), str(pop and pop["fill"]))
            check("the bar carries one segment per part", pop and pop["segs"] == 6, str(pop and pop["segs"]))
            check("the panel reports the average cache hit rate",
                  pop and "Average cache hit rate 89.1%" in pop["foot"], str(pop and pop["foot"]))
            # a window about to run out is flagged before it bites, and the cache figure tells
            # "reported usage, nothing cached" (0.0%) apart from "no usage reported" (no line at all,
            # which is honest, rather than a rate invented out of an absent number)
            ctx_turn["evs"] = [{"type": "ctx", "ctx": {"tokens": 190000, "limit": 200000, "model": "m",
                    "hit": 0, "seen": 190000, "rows": [{"label": "Messages", "tokens": 190000}]}}, {"type": "done"}]
            pg.fill("#input", "fill it up"); pg.eval_on_selector("#btnSend", "e=>e.click()")
            pg.wait_for_timeout(900)
            check("a nearly full window is flagged, not just reported",
                  "hot" in pg.eval_on_selector("#chipCtx", "e=>e.className"),
                  pg.eval_on_selector("#chipCtx", "e=>e.className"))
            pg.hover("#chipCtx"); pg.wait_for_timeout(350)
            check("a chat that cached nothing reports 0.0%, not a blank",
                  "Average cache hit rate 0.0%" in pg.eval_on_selector("#ctxpop", "e=>e.innerText"),
                  pg.eval_on_selector("#ctxpop", "e=>e.innerText"))
            ctx_turn["evs"] = [{"type": "ctx", "ctx": {"tokens": 900, "limit": 200000, "model": "m",
                    "hit": 0, "seen": 0, "rows": [{"label": "Messages", "tokens": 900}]}}, {"type": "done"}]
            pg.fill("#input", "no usage"); pg.eval_on_selector("#btnSend", "e=>e.click()")
            pg.wait_for_timeout(900)
            pg.hover("#chipCtx"); pg.wait_for_timeout(350)
            check("a provider that reported no usage shows no cache line rather than a fake rate",
                  "cache hit rate" not in pg.eval_on_selector("#ctxpop", "e=>e.innerText"),
                  pg.eval_on_selector("#ctxpop", "e=>e.innerText"))
        finally:
            pg.unroute("**/api/chat")
        # The measurement is saved with the chat, so opening it again shows the window it left behind.
        # A real sidebar click drives the real `select()`, which reads /api/history — only the answer
        # is stood in for, so the path from the payload to the chip is the one that ships.
        pg.route("**/api/history*", lambda r: r.fulfill(status=200, content_type="application/json",
            body=json.dumps({"messages": [], "pending": None, "model": "m", "bot": None, "title": "t",
                "approval": "ask", "ctx": {"tokens": 50000, "limit": 100000, "model": "m", "hit": 30,
                    "seen": 100, "rows": [{"label": "Messages", "tokens": 50000}]}})))
        try:
            pg.evaluate("()=>document.querySelector('#bots .subbot, #chans .sub .subbot').click()")
            pg.wait_for_timeout(800)
            check("a chat opened again shows the window it left behind",
                  pg.eval_on_selector("#chipCtx", "e=>e.textContent").strip() == "Context: 50%",
                  pg.eval_on_selector("#chipCtx", "e=>e.textContent"))
            pg.hover("#chipCtx"); pg.wait_for_timeout(350)
            check("and the panel it left behind too",
                  "50.0K / 100.0K (50.0%)" in pg.eval_on_selector("#ctxpop", "e=>e.innerText"),
                  pg.eval_on_selector("#ctxpop", "e=>e.innerText"))
        finally:
            pg.unroute("**/api/history*")

        # ---- 20. every bot keeps its own work log, in its own folder ----
        pg.route("**/api/bot/log*", lambda r: r.fulfill(status=200, content_type="application/json",
            body=json.dumps({"bot": "producer", "text": "# Work log\n\n## 2026-01-01 09:00 · company · direct\n- **Did:** run_shell\n- **In:** /tmp/repo/producer\n"})))
        pg.eval_on_selector_all("#setTabs .mtab", f"els=>els[{tabs.index('Memory')}].click()"); pg.wait_for_timeout(500)
        memtxt = pg.eval_on_selector("#setPanel", "e=>e.innerText")
        check("Memory shows a work log", "Work log" in memtxt)
        check("the work log says it is the bot's own", "in its own folder" in memtxt)
        check("the work log is shown read-only, per bot",
              pg.eval_on_selector_all("#setPanel textarea", "e=>e.length") >= 2
              and pg.eval_on_selector_all("#setPanel textarea", "e=>e[0].readOnly !== true")
              and pg.eval_on_selector_all("#setPanel textarea", "e=>e[e.length-1].readOnly === true"))
        check("the log's turns reach the panel",
              "run_shell" in pg.eval_on_selector_all("#setPanel textarea", "e=>e[e.length-1].value"))
        pg.unroute("**/api/bot/log*")
        # the real endpoint answers for a bot that has never run, instead of looking broken
        empty = pg.evaluate("async()=>{const d=await (await fetch('/api/bot/log?bot=e2e-quick')).json();return d.text}")
        check("a bot with no turns yet gets an empty log, not an error", empty == "", str(empty)[:80])
        pg.eval_on_selector("#sClose", "e=>e.click()"); pg.wait_for_timeout(300)
        pg.evaluate("""async()=>{for(const m of ['e2e/quick-model','e2e/other-model'])
            await fetch('/api/models/remove',{method:'POST',headers:{'Content-Type':'application/json'},
              body:JSON.stringify({model:m})})}""")

        # ---- 21. notification sounds: synthesised cues, wired to the turn's outcome ----
        # Nothing is fetched — the chime is drawn with Web Audio — so the only honest way to see the
        # wiring is to stand in for the browser's audio: a recording AudioContext turns "an oscillator
        # was created" into a number. It has to be installed before the page loads, because sound.js
        # opens the context once, on the first real gesture, and keeps it for the life of the page.
        pg.add_init_script("""(function(){
            window.__osc = 0;
            window.AudioContext = class {
              constructor(){ this.state = 'running'; this.currentTime = 0; this.destination = {}; }
              resume(){ this.state = 'running'; }
              createOscillator(){ window.__osc++;
                return { type:'', frequency:{ setValueAtTime(){} }, connect(n){ return n; }, start(){}, stop(){} }; }
              createGain(){ return { gain:{ setValueAtTime(){}, exponentialRampToValueAtTime(){} }, connect(n){ return n; } }; }
            };
          })()""")
        pg.reload(wait_until="load"); pg.wait_for_timeout(900)
        pg.keyboard.press("Shift"); pg.wait_for_timeout(150)   # a real gesture opens the audio context
        # a turn needs a session, and the outcome of that turn is what the dock reads
        pg.evaluate("()=>{const b=document.querySelector('#bots .subbot, #chans .sub .subbot'); if(b) b.click()}")
        pg.wait_for_timeout(400)

        # the switch lives in General, beside the other app-wide behaviour
        saved_snd = pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.settings.sound}")
        check("the server ships a sound setting", isinstance(saved_snd, dict)
              and isinstance(saved_snd.get("on"), bool) and isinstance(saved_snd.get("volume"), (int, float)),
              str(saved_snd))
        pg.eval_on_selector("#btnSettings", "e=>e.click()"); pg.wait_for_timeout(400)
        pg.eval_on_selector_all("#setTabs .mtab", f"els=>els[{tabs.index('General')}].click()"); pg.wait_for_timeout(300)
        check("General offers notification sounds", "Notification sounds" in pg.eval_on_selector("#setPanel", "e=>e.innerText"))
        scard = pg.evaluate("""()=>{
            const sw=[...document.querySelectorAll('#setPanel .switch')].find(s=>/Play a chime/.test(s.innerText));
            const f=[...document.querySelectorAll('#setPanel .fld')].find(x=>(x.querySelector('label')||{}).innerText==='VOLUME');
            const r=f&&f.querySelector('input[type=range]');
            return { tog: !!sw, on: sw?sw.querySelector('.tg').classList.contains('on'):null, vol: r?+r.value:null }; }""")
        check("the sound switch matches what is saved", scard["tog"] and scard["on"] == saved_snd["on"], str(scard))
        check("the volume slider opens on the saved level", scard["vol"] == saved_snd["volume"], str(scard))

        SND = os.path.join(DATA, "settings.json")
        raw_snd = open(SND).read()          # byte-for-byte, so the test's own mute is fully undone
        turn = {"evs": []}
        def snd_chat(route):
            route.fulfill(status=200, content_type="text/event-stream",
                          body="".join("data: " + json.dumps(e) + "\n\n" for e in turn["evs"]))
        pg.route("**/api/chat", snd_chat)
        try:
            # a turn that finishes lands the dock on `finished`, which is worth a chime
            turn["evs"] = [{"type": "status", "state": "working"},
                           {"type": "agent_text", "agent": "producer", "text": "ok"},
                           {"type": "status", "state": "finished"}, {"type": "done"}]
            pg.eval_on_selector("#sClose", "e=>e.click()"); pg.wait_for_timeout(300)
            pg.evaluate("()=>{window.__osc=0}")
            pg.fill("#input", "say something"); pg.eval_on_selector("#btnSend", "e=>e.click()")
            pg.wait_for_timeout(900)
            check("a finished turn plays a chime", pg.evaluate("()=>window.__osc") >= 2,
                  "oscillators=%s" % pg.evaluate("()=>window.__osc"))

            # the middle of a turn is silent on purpose — a chime per state would be a metronome
            turn["evs"] = [{"type": "status", "state": "working"}, {"type": "status", "state": "thinking"},
                           {"type": "status", "state": "searching"},
                           {"type": "agent_text", "agent": "producer", "text": "ok"}, {"type": "done"}]
            pg.evaluate("()=>{window.__osc=0}")
            pg.fill("#input", "still working"); pg.eval_on_selector("#btnSend", "e=>e.click()")
            pg.wait_for_timeout(900)
            check("the middle of a turn stays silent", pg.evaluate("()=>window.__osc") == 0,
                  "oscillators=%s" % pg.evaluate("()=>window.__osc"))

            # and the switch really is a mute, not decoration
            pg.eval_on_selector("#btnSettings", "e=>e.click()"); pg.wait_for_timeout(400)
            pg.eval_on_selector_all("#setTabs .mtab", f"els=>els[{tabs.index('General')}].click()"); pg.wait_for_timeout(300)
            pg.evaluate("""()=>{const sw=[...document.querySelectorAll('#setPanel .switch')].find(s=>/Play a chime/.test(s.innerText));
                sw.querySelector('.tg').click();}""")
            pg.wait_for_timeout(500)
            check("the switch turns off", pg.evaluate("""()=>[...document.querySelectorAll('#setPanel .switch')]
                .find(s=>/Play a chime/.test(s.innerText)).querySelector('.tg').classList.contains('on')""") is False)
            pg.eval_on_selector("#sClose", "e=>e.click()"); pg.wait_for_timeout(300)
            turn["evs"] = [{"type": "status", "state": "working"}, {"type": "status", "state": "finished"},
                           {"type": "done"}]
            pg.evaluate("()=>{window.__osc=0}")
            pg.fill("#input", "quiet please"); pg.eval_on_selector("#btnSend", "e=>e.click()")
            pg.wait_for_timeout(900)
            check("muting the chime makes a finished turn silent", pg.evaluate("()=>window.__osc") == 0,
                  "oscillators=%s" % pg.evaluate("()=>window.__osc"))

            # releasing the slider plays the cue at the level chosen, so the control previews itself
            pg.eval_on_selector("#btnSettings", "e=>e.click()"); pg.wait_for_timeout(400)
            pg.eval_on_selector_all("#setTabs .mtab", f"els=>els[{tabs.index('General')}].click()"); pg.wait_for_timeout(300)
            pg.evaluate("""()=>{const f=[...document.querySelectorAll('#setPanel .fld')].find(x=>(x.querySelector('label')||{}).innerText==='VOLUME');
                const r=f.querySelector('input[type=range]'); r.value='0.7';
                r.dispatchEvent(new Event('input')); r.dispatchEvent(new Event('change'));}""")
            pg.wait_for_timeout(500)
            check("releasing the volume slider previews the chime", pg.evaluate("()=>window.__osc") >= 2,
                  "oscillators=%s" % pg.evaluate("()=>window.__osc"))
        finally:
            pg.unroute("**/api/chat")
            open(SND, "w").write(raw_snd)
            # A bare file write is invisible to the server's settings cache, so the restore above does
            # not reach /api/config. Hand the real value back through the same API the UI uses too.
            pg.evaluate("""async(s)=>{await fetch('/api/settings',{method:'POST',
                headers:{'Content-Type':'application/json'},body:JSON.stringify({settings:{sound:s}})})}""",
                json.loads(raw_snd)["sound"])
        handed = pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.settings.sound}")
        check("the test hands the real sound settings back",
              handed.get("on") == saved_snd["on"] and handed.get("volume") == saved_snd["volume"], str(handed))

        # ---- cleanup: the suite must leave no trace ----
        cfg = pg.evaluate("async()=>await (await fetch('/api/config')).json()")
        for b in cfg["bots"]:
            if b["id"].startswith(("designer", "e2e-")):
                pg.evaluate("async(id)=>{await fetch('/api/bot/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})})}", b["id"])
        for c in cfg["channels"]:
            if c["id"].startswith("e2e-") or c["name"] == "Marketing":
                pg.evaluate("async(id)=>{await fetch('/api/channel/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})})}", c["id"])
        left_bots = pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.bots.filter(b=>b.id.startsWith('designer')||b.id.startsWith('e2e-')).length}")
        left_chans = pg.evaluate("async()=>{const c=await (await fetch('/api/config')).json();return c.channels.filter(x=>x.name==='Marketing'||x.id.startsWith('e2e-')).length}")
        check("suite cleans up its own bots", left_bots == 0)
        check("suite cleans up its own channels", left_chans == 0)
        # Detect-all rewrote the saved model list, so the config file goes back exactly as it was.
        open(CFGP, "w").write(cfg_before)
        check("the test hands the real model list back", open(CFGP).read() == cfg_before)
        # Deleting a bot drops its session but leaves its on-disk artifacts — its work log, its memory
        # file and its sandbox field. A bot the suite created must take those with it, or the suite
        # leaves test text in files a later real run reads.
        for b in cfg["bots"]:
            if not b["id"].startswith(("designer", "e2e-")): continue
            slug = re.sub(r"[^a-zA-Z0-9_-]", "_", b["id"])
            for rel in (("logs", slug + ".md"), ("memory", slug + ".md")):
                try: os.remove(os.path.join(DATA, *rel))
                except OSError: pass
            shutil.rmtree(os.path.join(SANDBOX, slug), ignore_errors=True)
        # A deleted bot or company must take its transcript with it — including the scoped
        # `<company>/<bot>` chats, which used to be left stranded on disk.
        sess_path = os.path.join(DATA, "sessions.json")
        try: left_sess = [k for k in json.load(open(sess_path)) if "e2e" in k.split("/")]
        except Exception: left_sess = []
        check("suite cleans up its own chats", left_sess == [], str(left_sess))
        memp = os.path.join(DATA, "memory")
        try: left_mem = [f for f in os.listdir(memp) if f.startswith(("e2e-", "designer"))]
        except Exception: left_mem = []
        check("suite leaves no bot memory files behind", left_mem == [], str(left_mem))
        logp = os.path.join(DATA, "logs")
        try: left_log = [f for f in os.listdir(logp) if f.startswith(("e2e-", "designer"))]
        except Exception: left_log = []
        check("suite leaves no bot work logs behind", left_log == [], str(left_log))
        sbx = SANDBOX
        try: left_sbx = [f for f in os.listdir(sbx) if f.startswith(("e2e-", "designer"))]
        except Exception: left_sbx = []
        check("suite leaves no bot sandbox fields behind", left_sbx == [], str(left_sbx))
        # The repo-picker fixtures live at fixed /tmp paths the suite picked; they are its own
        # scratch, so they go too.
        for d in ("/tmp/e2e-pick", "/tmp/e2e-logo-repo"):
            shutil.rmtree(d, ignore_errors=True)

        br.close()

    print(f"\n{len(PASS)}/{len(PASS)+len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)

if __name__ == "__main__":
    os.makedirs("shots", exist_ok=True)
    main()
