/* Offline checks for the Settings rail's roving-tabindex tablist in app.js — no browser, no DOM lib.

   The rail is a real tablist: every tab names the panel it controls, says whether it is the one
   showing, and exactly one of them is in the tab order — the one on screen — so the rail is a single
   Tab stop rather than fourteen, and the arrows move between sections. app.js is an ES module that
   boots the whole UI, so it cannot be imported here; `renderTabs` is read out of the source and run
   against fake nodes. If the extraction ever stops matching, these checks fail rather than pass on
   nothing.

   Run: node tests/test_tablist.mjs   (exit 0 = all green) */
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../app.js", import.meta.url), "utf8");
const slice = (from, to) => {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0 || b < a) { console.log("FAIL could not find " + from + " in app.js"); process.exit(1); }
  return src.slice(a, b);
};
/* The block under test, and the tab table it reads — both lifted out of app.js, so a changed table
   fails this check instead of quietly passing against a stale copy. */
const block = slice("function renderTabs() {", "\nfunction renderPanel() {");
const tabsSrc = slice("const TABS = [", "\n];") + "\n];";

let pass = 0, fail = 0;
const ok = (name, cond, extra = "") => {
  if (cond) { pass++; console.log("  ok   " + name); }
  else { fail++; console.log("  FAIL " + name + (extra ? "  -> " + extra : "")); }
};

/* ---------- a stand-in for the DOM the rail touches ----------
   An element is its own attributes map, a list of children, and a focus() that records itself as the
   document's active element — which is exactly the state the arrow keys read. */
const document = { activeElement: null, _byId: new Map(), createElement: t => node(t),
  getElementById: id => document._byId.get(id) || null };
function node(tag) {
  const n = {
    tagName: (tag || "div").toUpperCase(), className: "", id: "", tabIndex: 0,
    attrs: {}, children: [], parentElement: null, focused: false, style: {},
    set innerHTML(h) { this.children = []; this._html = h; },
    get innerHTML() { return this._html || ""; },
    appendChild(c) { c.parentElement = this; this.children.push(c); return c; },
    setAttribute(k, v) { this.attrs[k] = String(v); if (k === "id") { this.id = v; document._byId.set(v, this); } },
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    focus() { this.focused = true; document.activeElement = this; },
  };
  return n;
}
const box = node("div");
const $ = sel => (sel === "#setTabs" ? box : null);
const tabsIn = () => box.children.filter(c => c.className.split(" ").includes("mtab"));
const $$ = sel => (sel === "#setTabs .mtab" ? tabsIn() : []);
const el = (t, c, h) => { const e = node(t); if (c) e.className = c; if (h != null) e.innerHTML = h; return e; };
const esc = s => (s == null ? "" : String(s));

/* The app's own `renderTabs`, bound to the fake document and the real tab table. */
const R = new Function("$", "$$", "el", "esc", "svg", "document", "renderPanel", "TABS",
  '"use strict";\nlet curTab = "general";\n' + block
  + "\nreturn { renderTabs, setTab: v => curTab = v, tab: () => curTab };")(
  $, $$, el, esc, () => "<svg></svg>", document, () => {}, new Function(tabsSrc + "\nreturn TABS;")());

console.log("\n-- the rail as a tablist --");
R.renderTabs();
let tabs = tabsIn();
ok("every tab names its role", tabs.length > 0 && tabs.every(t => t.getAttribute("role") === "tab"), String(tabs.length));
ok("every tab says which panel it controls", tabs.every(t => t.getAttribute("aria-controls") === "setPanel"));
ok("aria-selected is true on exactly one tab",
  tabs.filter(t => t.getAttribute("aria-selected") === "true").length === 1,
  tabs.map(t => t.getAttribute("aria-selected")).join(","));
ok("...and it is the current one", tabs.find(t => t.getAttribute("aria-selected") === "true").id === "tab-general");

console.log("\n-- roving tabindex --");
ok("exactly one tab is in the tab order",
  tabs.filter(t => t.tabIndex === 0).length === 1, tabs.map(t => t.tabIndex).join(","));
ok("...and it is the current one", tabs.find(t => t.tabIndex === 0).id === "tab-general");
ok("every other tab is out of the order", tabs.filter(t => t.id !== "tab-general").every(t => t.tabIndex === -1));

console.log("\n-- the current tab moves --");
R.setTab("memory"); R.renderTabs();
tabs = tabsIn();
ok("the new tab is the one in the order", tabs.find(t => t.tabIndex === 0).id === "tab-memory");
ok("the old tab has left it", tabs.find(t => t.id === "tab-general").tabIndex === -1);
ok("still exactly one in the order", tabs.filter(t => t.tabIndex === 0).length === 1);

console.log("\n-- the arrows move along the rail --");
const key = k => ({ key: k, prevented: false, preventDefault() { this.prevented = true; } });
const idx = id => tabsIn().findIndex(t => t.id === id);
const focusId = () => (document.activeElement && document.activeElement.id) || null;
const press = k => { const e = key(k); box.onkeydown(e); return e; };

document.activeElement = tabs[0];                       // on the first tab, as opening settings leaves it
press("ArrowDown");
ok("ArrowDown moves to the next tab", focusId() === tabs[1].id, focusId());
ok("...and the roving tabindex follows", tabsIn().find(t => t.tabIndex === 0).id === focusId());
ok("...with exactly one still in the order", tabsIn().filter(t => t.tabIndex === 0).length === 1);
press("ArrowUp");
ok("ArrowUp moves back", focusId() === tabs[0].id, focusId());

press("End");
ok("End jumps to the last tab", focusId() === tabs[tabs.length - 1].id, focusId());
press("Home");
ok("Home jumps to the first", focusId() === tabs[0].id, focusId());

console.log("\n-- it wraps at both ends --");
press("ArrowUp");                                        // from the first, upward wraps to the last
ok("ArrowUp off the top wraps to the last tab", focusId() === tabs[tabs.length - 1].id, focusId());
press("ArrowDown");                                      // from the last, downward wraps to the first
ok("ArrowDown off the bottom wraps to the first", focusId() === tabs[0].id, focusId());
ok("the wrap leaves one tab in the order", tabsIn().filter(t => t.tabIndex === 0).length === 1);

console.log("\n-- the group headings are not tabs --");
const heads = box.children.filter(c => c.className.split(" ").includes("mgrp"));
ok("the group headings are drawn", heads.length >= 3, String(heads.length));
ok("...and are hidden from the keyboard and the reader",
  heads.every(h => h.getAttribute("aria-hidden") === "true" && h.getAttribute("role") === null));
ok("...so they are never one of the tabs", heads.every(h => !tabsIn().includes(h)));

console.log("\n-- the dialog's inertness, and the computer panel's own state --");
const behindBlock = slice("const BEHIND = [", "\nfunction openSettings");
const overlays = {};
const behind$ = sel => (overlays[sel] ||= (() => {
  const n = node("div");
  n.classList = { _s: new Set(), contains(c) { return this._s.has(c); } };
  return n;
})());
const body = ['"use strict";', behindBlock, "return { behindInert, BEHIND };"].join("\n");
const B = new Function("$", body)(behind$);
B.behindInert(true);
ok("opening the dialog takes the whole shell out of reach",
  B.BEHIND.every(s => overlays[s].inert === true));
B.behindInert(false);
ok("closing it hands the shell back", overlays["#side"].inert === false);
ok("...but a computer panel that was closed stays inert", overlays["#comp"].inert === true);
overlays["#comp"].classList._s.add("on");
B.behindInert(true); B.behindInert(false);
ok("...and one that is on screen is reachable again", overlays["#comp"].inert === false);

console.log(`\n${pass} ok, ${fail} failed`);
process.exit(fail ? 1 : 0);
