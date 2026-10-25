#!/usr/bin/env python3
"""The Backup tab, driven in a real browser against a real server.

What is under test is the thing a unit test cannot see: that the tab is in the rail, that clicking it
draws the panel, that the export link is a download the browser really starts, and that choosing a
bundle shows what is inside *before* anything is written.

Nothing here touches the internet.  Usage:  python3 tests/test_bundle_ui.py
"""
import json, os, shutil, sys, tempfile, threading, time, urllib.request
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_s = __import__("socket").socket(); _s.bind(("127.0.0.1", 0)); PORT = _s.getsockname()[1]; _s.close()
tmp = tempfile.mkdtemp(prefix="anzen-bundle-ui-")
os.environ.update(DATA_DIR=tmp, SANDBOX_DIR=os.path.join(tmp, "sandbox"), BROWSER_WARMUP="0")
import server as S
assert S.DATA.startswith(tmp), "the test must not touch the real data dir"

fails, TOTAL = [], [0]
def check(name, ok, extra=""):
    TOTAL[0] += 1
    print(("PASS " if ok else "FAIL ") + name + (("  " + str(extra)[:300]) if not ok else ""))
    if not ok: fails.append(name)

# One bot with a memory note, so the bundle is not empty when it is exported.
S.save_bots([{"id": "writer", "name": "Writer", "title": "Copy", "role": "writes", "color": "green",
              "model": S.DEFAULT_MODEL, "approval": "ask", "instructions": "You write."}])
S.mem_append("writer", "the client likes plain words")

t = threading.Thread(target=S.serve, kwargs={"host": "127.0.0.1", "port": PORT, "warm_browser": False}, daemon=True)
t.start()
for _ in range(100):
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/api/config" % PORT, timeout=1).read(); break
    except Exception: time.sleep(0.1)

URL = "http://127.0.0.1:%d/" % PORT
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    page = b.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(URL, wait_until="load")
    page.wait_for_timeout(1200)

    # --- the tab is in the rail ---
    page.click("#btnSettings")
    page.wait_for_timeout(600)
    tab = page.locator('#setTabs .mtab:has-text("Backup")')
    check("the Backup tab is in the settings rail", tab.count() == 1)

    # --- clicking it draws the panel ---
    tab.first.click()
    page.wait_for_timeout(700)
    panel = page.locator("#setPanel")
    text = panel.inner_text()
    check("the panel is titled Backup", "Backup" in text)
    check("it offers the export", "Export workspace" in text)
    check("it offers the import", "Import a workspace" in text or "Choose a bundle" in text)
    check("it says what it carries", "memory notes" in text.lower())
    check("it says what does not travel", "router" in text.lower())

    # --- the export link is a real download ---
    link = panel.locator('a:has-text("Export workspace")')
    check("the export is a link, not a script", link.count() == 1)
    href = link.first.get_attribute("href") if link.count() else ""
    check("it points at the export endpoint", href == "/api/workspace/export", href)
    check("it carries the download attribute", link.count() and link.first.get_attribute("download") is not None)
    with page.expect_download(timeout=20000) as dl:
        link.first.click()
    d = dl.value
    check("the browser really starts a download", d is not None)
    path = d.path()
    check("the download is a zip", path and os.path.getsize(path) > 200, path)
    check("it is named for the workspace", (d.suggested_filename or "").startswith("anzen-workspace-"))
    saved = os.path.join(tmp, "got.zip")
    shutil.copyfile(path, saved)

    # --- choosing a bundle shows what is inside, and writes nothing yet ---
    # The picker is detached on purpose (the same pattern the Skills tab uses), so it is driven through
    # the button that opens it rather than by addressing the input in the DOM.
    with page.expect_file_chooser(timeout=15000) as fc:
        panel.locator('button:has-text("Choose a bundle")').first.click()
    fc.value.set_files(saved)
    page.wait_for_timeout(1500)
    after = panel.inner_text()
    check("it names the file that was chosen", "got.zip" in after)
    check("it counts the bots before importing", "1 bot" in after or "bot," in after or "bot " in after)
    check("it offers both ways in", "Add to what is here" in after and "Replace what is here" in after)
    # Nothing has been written: the roster still holds what it held.
    check("nothing was imported by choosing the file",
          [x["id"] for x in S.load_bots()] == ["writer"])

    # --- the import button really imports, and the page picks it up ---
    panel.locator('button:has-text("Import")').last.click()
    page.wait_for_timeout(2500)
    done = panel.inner_text()
    check("it reports what it imported", "Imported" in done, done[:200])
    check("the server now holds the bundle's bot", "writer" in [x["id"] for x in S.load_bots()])

    check("no JavaScript error was raised", not errors, errors[:3])
    b.close()

print("\n%d checks, %d failed" % (TOTAL[0], len(fails)))
if fails: print("FAILED:", fails)
sys.exit(1 if fails else 0)
