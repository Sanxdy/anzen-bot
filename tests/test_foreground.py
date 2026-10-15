#!/usr/bin/env python3
"""Checks for the ZenPilot profile switch the browser tool performs before it drives a site.

`Browser._foreground` exists because ZenPilot renders one profile at a time: a background profile's
<webview> is display:none, so it never paints — a click lands on nothing and a screenshot has no
frame, yet every action still reports success. The switch is "click the sidebar row named after the
profile", and the only thing worth checking is that the JS does exactly that against a DOM shaped
like ZenPilot's. The DOM below is a stand-in: the sidebar rows and the hidden/visible containers,
with a click handler that mimics React's onSwitchProfile.

Usage:  .venv/bin/python tests/test_foreground.py
"""
import os, sys, json, tempfile
from playwright.sync_api import sync_playwright

tmp = tempfile.mkdtemp(prefix="anzen-fg-")
os.environ["DATA_DIR"] = tmp
os.environ["SANDBOX_DIR"] = os.path.join(tmp, "sandbox")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as S

assert S.DATA.startswith(tmp) and S.SESS_PATH.startswith(tmp), "test paths must point into tmp"

PASS = []; FAIL = []
def check(name, ok, extra=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + (f"  {extra}" if extra and not ok else ""))

# Two profiles of one service (so the sidebar groups them and the group can be collapsed) plus one
# ungrouped. Only profile 1 starts on screen.
HTML = """
<style>.hidden{display:none}</style>
<div id="app">
  <div class="w-56">
    <button aria-expanded="false" id="grp">&#9662; <span>Threads</span> <span>2</span></button>
    <div id="grpbody"></div>
    <div><button id="row-fb"><span class="font-medium truncate">FB Page</span></button></div>
  </div>
  <div id="c1" class="relative z-20 flex flex-col"><webview partition="persist:profile_1"></webview></div>
  <div id="c2" class="hidden"><webview partition="persist:profile_2"></webview></div>
  <div id="c3" class="hidden"><webview partition="persist:profile_3"></webview></div>
</div>
<script>
// Electron's <webview> reflects `partition` as a property; a plain unknown element does not, so the
// stand-in adds it. This is the same property _app_webviews() reads in the real app.
document.querySelectorAll('webview').forEach(w => Object.defineProperty(w, 'partition',
  { value: w.getAttribute('partition') }));
const c = {1: document.getElementById('c1'), 2: document.getElementById('c2'), 3: document.getElementById('c3')};
function activate(pid) {
  for (const k of [1, 2, 3]) c[k].className = k === pid ? 'relative z-20 flex flex-col' : 'hidden';
}
// A collapsed group renders no rows at all (`{!isCollapsed && group.profiles.map(...)}`), so the
// stand-in must not merely hide them — a hidden button is still findable and still clickable.
const ROWS = '<div><button id="row-th"><span class="font-medium truncate">Threads Main</span></button></div>'
           + '<div><button id="row-x"><span class="font-medium truncate">X Promo</span></button></div>';
function setRows(open) {
  document.getElementById('grpbody').innerHTML = open ? ROWS : '';
  document.getElementById('grp').setAttribute('aria-expanded', open ? 'true' : 'false');
  if (open) {
    document.getElementById('row-th').onclick = () => activate(1);
    document.getElementById('row-x').onclick  = () => activate(2);
  }
}
document.getElementById('grp').onclick = () =>
  setRows(document.getElementById('grpbody').innerHTML === '');
setRows(false);
document.getElementById('row-fb').onclick = () => activate(3);
</script>
"""

def main():
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        pg = br.new_page(viewport={"width": 900, "height": 700})
        pg.set_content(HTML)

        def click(pid, name, svc): return pg.evaluate(S._fg_js(pid, name, svc)[0])
        def show(pid): return pg.evaluate(S._fg_js(pid, name="", svc="")[1])

        check("a profile already on screen is left where it is",
              click(1, "Threads Main", "Threads") == "visible")
        check("nothing was switched by that call", show(1) and not show(2))

        # The bot asks for a profile whose service group is collapsed: the group must open first.
        check("a background profile is brought on screen, expanding its collapsed group",
              click(2, "X Promo", "Threads") == "clicked")
        check("  ...and it is the one on screen now", show(2) and not show(1))
        check("  ...and its sidebar group is open", pg.evaluate("()=>document.getElementById('grp').getAttribute('aria-expanded')==='true'"))

        check("a second call is a no-op, not another click",
              click(2, "X Promo", "Threads") == "visible")

        # An ungrouped profile: no group to expand, the row is there from the start.
        check("an ungrouped profile switches too", click(3, "FB Page", "Facebook") == "clicked")
        check("  ...and it is on screen", show(3))

        check("a name no row carries reports no-row, so the caller leaves the open alone",
              click(1, "Ghost", "Threads") == "no-row")

        # Lazy memory mode: an inactive profile is not in the DOM at all.
        pg.set_content(HTML)
        pg.evaluate("()=>document.getElementById('c2').remove()")
        check("a profile that is not rendered reads as not on screen", show(2) is False)

        br.close()

    print(f"\n{len(PASS)}/{len(PASS)+len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)

if __name__ == "__main__":
    main()
