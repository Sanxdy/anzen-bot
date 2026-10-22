/* Offline checks for per-chat drafts and the transcript's find bar in app.js — no browser, no DOM lib.

   Two behaviours are pinned. (1) A half-typed message used to follow you into the next chat, where
   Send delivered it to the wrong bot; a draft now stays with its chat, survives a reload, and is
   dropped when the message is sent — and only for that chat. (2) Find marks the hits in place, wraps
   at both ends, and closing puts the transcript's text nodes back exactly as they were, because a
   later markdown re-render reads that text.

   app.js is an ES module that boots the whole UI, so it cannot be imported here; the draft helpers and
   the find functions are read out of the source and run against stubs (a Map for localStorage, and a
   small node tree for the DOM the find walker needs). If an extraction stops matching, these checks
   fail rather than pass on nothing.

   Run: node tests/test_drafts_find.mjs   (exit 0 = all green) */
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../app.js", import.meta.url), "utf8");
const slice = (from, to) => {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0 || b < a) { console.log("FAIL could not find " + from + " in app.js"); process.exit(1); }
  return src.slice(a, b);
};

let pass = 0, fail = 0;
const ok = (name, cond, extra = "") => {
  if (cond) { pass++; console.log("  ok   " + name); }
  else { fail++; console.log("  FAIL " + name + (extra ? "  -> " + extra : "")); }
};

/* =====================================================================
   Drafts — a draft belongs to its chat
   ===================================================================== */
console.log("-- a draft stays with its chat --");
const draftBlock = slice('const DKEY = "anzen.drafts";', "/* ---------------- selection ---------------- */");
const store = new Map();
const ls = { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) };
const input = { value: "" };
let grown = 0;
const $d = sel => (sel === "#input" ? input : null);
const makeD = st => new Function("S", "localStorage", "$", "autoGrow", draftBlock
  + "\nreturn { draftSet, draftsLoad, draftSwap, draftsSave };")
  (st, ls, $d, () => { grown++; });
const S1 = { active: "a", drafts: {} };
const D = makeD(S1);
/* What select does around `draftSwap`: the swap happens against the chat being left, then the chat
   being opened becomes the active one. */
const go = id => { D.draftSwap(id); S1.active = id; };

input.value = "half typed for a";
go("b");
ok("leaving a chat keeps what was typed in it", S1.drafts.a === "half typed for a", JSON.stringify(S1.drafts));
ok("...and the chat opened gets its own (empty) box", input.value === "", JSON.stringify(input.value));
ok("...grown to fit", grown > 0);
input.value = "for b";
go("a");
ok("typing in the next chat stays there", S1.drafts.b === "for b", JSON.stringify(S1.drafts));
ok("...and coming back restores the first chat's text", input.value === "half typed for a", input.value);

console.log("\n-- sending clears only that chat --");
D.draftSet("a", "");
ok("the sent chat has no draft", S1.drafts.a === undefined, JSON.stringify(S1.drafts));
ok("...and the other chat keeps its own", S1.drafts.b === "for b");
D.draftSet("b", "   ");
ok("whitespace is not a draft", S1.drafts.b === undefined, JSON.stringify(S1.drafts));

console.log("\n-- the map is capped --");
const S2 = { active: "x", drafts: {} };
const D2 = makeD(S2);
for (let i = 0; i < 60; i++) D2.draftSet("c" + i, "text " + i);
const keys = Object.keys(S2.drafts);
ok("at most 50 chats are kept", keys.length === 50, String(keys.length));
ok("...the oldest go first", !S2.drafts.c0 && !S2.drafts.c9 && !!S2.drafts.c10, keys.slice(0, 3).join(","));
ok("...the newest is kept", S2.drafts.c59 === "text 59");
D2.draftSet("c59", "edited");
ok("...editing a draft moves it to the newest end", Object.keys(S2.drafts).pop() === "c59",
  Object.keys(S2.drafts).slice(-2).join(","));

console.log("\n-- the drafts outlive a reload --");
store.clear();
S1.drafts = { a: "still here" };
D.draftsSave();
const S3 = { active: null, drafts: {} };
makeD(S3).draftsLoad();
ok("a saved draft comes back", S3.drafts.a === "still here", JSON.stringify(S3.drafts));
ok("...stored under anzen.drafts", JSON.parse(store.get("anzen.drafts")).a === "still here",
  store.get("anzen.drafts"));
store.set("anzen.drafts", "{not json");
const S4 = { active: null, drafts: { keep: "me" } };
makeD(S4).draftsLoad();
ok("a corrupt store leaves memory alone", S4.drafts.keep === "me", JSON.stringify(S4.drafts));

console.log("\n-- the wiring is in the two functions that need it --");
const selectSrc = slice("async function select(id) {", "/* ---------------- render ---------------- */");
ok("select swaps the composer with the chat", selectSrc.includes("draftSwap(id)"));
const sendSrc = slice("async function send() {", "/* ---------------- attachments ---------------- */");
ok("send clears the draft of the chat it sent in", sendSrc.includes('draftSet(S.active, "")'));

/* =====================================================================
   Find — the DOM it needs, and the transcript it walks
   ===================================================================== */
const findBlock = slice('let findQuery = "", findHits = [], findAt = -1;', "/* The answer as it is written.");

const has = (el, c) => (" " + el.className + " ").split(/\s+/).includes(c);
function textNode(v) {
  return { nodeType: 3, nodeValue: v, parentNode: null,
    splitText(i) {
      const p = this.parentNode, at = p.children.indexOf(this);
      const rest = textNode(this.nodeValue.slice(i));
      this.nodeValue = this.nodeValue.slice(0, i);
      rest.parentNode = p; p.children.splice(at + 1, 0, rest);
      return rest;
    } };
}
function elem(tag, text) {
  const e = { nodeType: 1, tagName: tag.toUpperCase(), className: "", children: [], parentNode: null,
    appendChild(c) {
      if (c.parentNode) c.parentNode.removeChild(c);
      c.parentNode = e; e.children.push(c); return c;
    },
    removeChild(c) { const i = e.children.indexOf(c); if (i >= 0) e.children.splice(i, 1); c.parentNode = null; },
    replaceChild(n, old) {
      const i = e.children.indexOf(old);
      if (i < 0) throw new Error("replaceChild: not a child");
      e.children[i] = n; n.parentNode = e; old.parentNode = null; return old;
    },
    /* Merging adjacent text nodes is the whole point of the unwrap, so it is modelled, not skipped. */
    normalize() {
      const out = [];
      for (const c of e.children) {
        if (c.nodeType === 3 && out.length && out[out.length - 1].nodeType === 3) {
          out[out.length - 1].nodeValue += c.nodeValue; c.parentNode = null;
        } else out.push(c);
      }
      e.children = out;
    },
    querySelectorAll() {
      const out = [], walk = n => {
        for (const c of n.children) if (c.nodeType === 1) {
          if (c.tagName === "MARK" && has(c, "findhit")) out.push(c);
          walk(c);
        }
      };
      walk(e); return out;
    },
    scrollIntoView(o) { e.scrolled = o; },
    get textContent() { return e.children.map(c => (c.nodeType === 3 ? c.nodeValue : c.textContent)).join(""); },
    classList: null };
  e.classList = {
    contains: c => has(e, c),
    toggle(c, on) {
      const now = has(e, c);
      if (on === undefined) on = !now;
      if (on && !now) e.className = (e.className + " " + c).trim();
      if (!on && now) e.className = e.className.split(/\s+/).filter(x => x !== c).join(" ");
    },
  };
  if (text != null) e.appendChild(textNode(text));
  return e;
}
const doc = {
  createElement: t => elem(t),
  createTextNode: v => textNode(v),
  createTreeWalker(root) {
    const list = [], walk = n => { for (const c of n.children) { if (c.nodeType === 3) list.push(c); else walk(c); } };
    walk(root);
    let i = -1;
    return { nextNode: () => (++i < list.length ? list[i] : null) };
  },
};

const box = elem("section");
const p1 = elem("div", "The cat sat.");
const p2 = elem("div", "The CAT ran.");
const p3 = elem("div", "concatenate");
box.appendChild(p1); box.appendChild(p2); box.appendChild(p3);
const count = { textContent: "" };
const bar = { hidden: true };
const findInput = { value: "", focused: 0, selected: 0, focus() { this.focused++; }, select() { this.selected++; } };
const composer = { focused: 0, focus() { this.focused++; } };
const $f = sel => sel === "#msgs" ? box : sel === "#findCount" ? count : sel === "#findbar" ? bar
  : sel === "#findInput" ? findInput : sel === "#input" ? composer : null;
const F = new Function("$", "document", "NodeFilter", findBlock
  + "\nreturn { findRun, findStep, findOpen, findClose, findUnmark,"
  + " get hits() { return findHits; }, get at() { return findAt; }, get query() { return findQuery; } };")
  ($f, doc, { SHOW_TEXT: 4 });

const texts = () => box.querySelectorAll().map(m => m.children[0].nodeValue).join(",");

console.log("\n-- hits are counted, case-insensitively --");
F.findRun("cat", 0);
ok("three hits in the transcript", F.hits.length === 3, String(F.hits.length));
ok("...the counter says which one is current", count.textContent === "1 of 3", count.textContent);
ok("...the current one is marked", has(F.hits[0], "cur") && !has(F.hits[1], "cur"));
ok("...and scrolled to", F.hits[0].scrolled && F.hits[0].scrolled.block === "center",
  JSON.stringify(F.hits[0].scrolled));
ok("...wrapping only the matched text", texts() === "cat,CAT,cat", texts());
F.findRun("zzz", 0);
ok("a query with no hits says so", count.textContent === "No matches" && F.hits.length === 0, count.textContent);
F.findRun("", 0);
ok("an empty query clears the counter", count.textContent === "" && F.hits.length === 0, count.textContent);

console.log("\n-- Enter and Shift+Enter wrap --");
F.findRun("cat", 0);
F.findStep(1);
ok("next moves to the second", count.textContent === "2 of 3", count.textContent);
F.findStep(1);
F.findStep(1);
ok("...and past the last goes back to the first", count.textContent === "1 of 3", count.textContent);
F.findStep(-1);
ok("previous from the first wraps to the last", count.textContent === "3 of 3", count.textContent);
ok("...and the mark follows", has(F.hits[2], "cur") && !has(F.hits[0], "cur"));

console.log("\n-- a redraw re-runs the same query at the same hit --");
F.findRun("cat", F.at);
ok("re-running keeps the match you were on", count.textContent === "3 of 3", count.textContent);
ok("...with the marks put back", F.hits.length === 3);
ok("render re-runs an open find", slice("function render(messages, pending) {",
  "/* ---------------- find in the open transcript").includes("findRun(findQuery, findAt)"));

console.log("\n-- closing leaves the transcript exactly as it was --");
bar.hidden = false;                    // the bar is open whenever a find is running
F.findClose();
ok("no marks are left", box.querySelectorAll().length === 0);
ok("...the text reads as before", p1.children[0].nodeValue === "The cat sat."
  && p2.children[0].nodeValue === "The CAT ran." && p3.children[0].nodeValue === "concatenate",
  [p1.children[0].nodeValue, p2.children[0].nodeValue, p3.children[0].nodeValue].join("|"));
ok("...one text node per element again, so a re-render sees one string",
  p1.children.length === 1 && p2.children.length === 1 && p3.children.length === 1);
ok("...the bar is hidden and empty", bar.hidden && count.textContent === "" && F.query === "");
ok("...and the composer has the caret back", composer.focused === 1, String(composer.focused));
F.findRun("cat", 0);
F.findClose(false);
ok("a chat switch closes it without taking the focus", composer.focused === 1 && bar.hidden);

console.log("\n-- opening the bar --");
bar.hidden = true;
F.findOpen();
ok("it shows and focuses the input", bar.hidden === false && findInput.focused === 1);
ok("...selecting whatever is in it", findInput.selected === 1);

console.log(`\n${pass} ok, ${fail} failed`);
process.exit(fail ? 1 : 0);
