/* Offline checks for the room's live strip in app.js — no browser, no DOM library.

   The strip says what every bot working in the room is doing, one line each, updated in place. Three
   things about it are logic rather than markup, and they are exactly what the request turns on: what
   a row says a bot is doing, that a bot gets one row rather than one per event, and that the row goes
   when the bot is done. app.js boots the whole UI, so it cannot be imported here; the block is read
   out of the source and run against a few fake nodes. If the extraction ever stops matching, these
   checks fail rather than pass on nothing.

   Run: node tests/test_live_strip.mjs   (exit 0 = all green) */
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../app.js", import.meta.url), "utf8");
const slice = (from, to) => {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0 || b < a) { console.log("FAIL could not find " + from + " in app.js"); process.exit(1); }
  return src.slice(a, b);
};
/* The block under test, and the pieces it leans on — all lifted out of app.js rather than re-written
   here: the hue resolver and its span, the tool line the transcript draws, the phase words. A copy of
   any of them in this file could pass while the app's own said something else. */
const block = slice("const WORKING = new Map();", "/* ---------------- the queue ---------------- */");
const escSrc = slice("const esc = ", "\n/* The model lists in Settings");
const hueOfSrc = slice("const hueOf = (name, sid)", "\nconst hueSpan = ");
const hueSpanSrc = slice("const hueSpan = (name, cls, hue)", "\n\n/* ---------------- sidebar");
const toolHeadSrc = slice("function toolHead(name, args) {", "\n/* A write is shown as what changed");
const stepSrc = slice("const STEP_LABEL = ", "\n/* The same step, said again");
const AV = {};
for (const m of (src.match(/const AV = \{([^}]*)\}/) || [])[1].matchAll(/([A-Za-z]+)\s*:\s*"(#[0-9A-Fa-f]{6})"/g)) AV[m[1]] = m[2].toUpperCase();
const AVK = Object.keys(AV);
const esc = s => (s == null ? "" : String(s)).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let pass = 0, fail = 0;
const ok = (name, cond, extra = "") => {
  if (cond) { pass++; console.log("  ok   " + name); }
  else { fail++; console.log("  FAIL " + name + (extra ? "  -> " + extra : "")); }
};

/* ---------- a stand-in for the DOM the strip touches ----------
   A row's `innerHTML` is a flat run of `<span>`s, which is all the strip ever writes, so the parse is
   a regex rather than a parser. The attributes are kept, because the name's own hue rides in one. */
function node(cls) {
  const n = {
    className: cls || "", dataset: {}, hidden: false, children: [], parentElement: null, removed: false,
    textContent: "", attrs: "",
    set innerHTML(h) {
      this.children = [];
      for (const m of h.matchAll(/<span([^>]*)>([^<]*)<\/span>/g)) {
        const c = node((m[1].match(/class="([^"]*)"/) || [])[1] || "");
        c.attrs = m[1]; c.textContent = m[2]; c.parentElement = this;
        this.children.push(c);
      }
    },
    appendChild(c) { c.parentElement = this; this.children.push(c); return c; },
    querySelector(sel) {
      const k = sel.replace(/^\./, "");
      return this.children.find(c => c.className.split(" ").includes(k)) || null;
    },
    remove() { this.removed = true; if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(x => x !== this); },
  };
  return n;
}

/* ---------- the roster the strip reads ---------- */
const bots = [
  { id: "atlas", name: "Atlas", title: "Chief Marketing Strategist", color: "purple" },
  { id: "scout", name: "Scout", title: "Research", color: "blue" },
  { id: "plain", name: "Plain", title: "", color: "green" },      // a bot with no title at all
];
const channels = [{ id: "growth", name: "Growth", members: ["atlas", "scout", "plain"] }];
const S = { bots, channels, active: "growth" };
const bot = id => bots.find(b => b.id === id);
const NAME = id => (bot(id) || {}).name || id;
const chan = id => channels.find(c => c.id === id);
/* `hueOf`/`hueSpan`/`toolHead`/`STEP_LABEL` are the app's own, bound to this roster. */
const hueOf = new Function("bot", "chan", "S", "AVK", `"use strict";${hueOfSrc};return hueOf;`)(bot, chan, S, AVK);
const hueSpan = new Function("esc", "AV", `"use strict";${hueSpanSrc};return hueSpan;`)(esc, AV);
const toolHead = new Function("NAME", `"use strict";${toolHeadSrc};return toolHead;`)(NAME);
const STEP_LABEL = new Function(`"use strict";${stepSrc};return STEP_LABEL;`)();
let box = node("working");
const clocked = new Map();
/* The lifted sources are the app's own, so they bring `esc`, `hueOf`, `hueSpan`, `toolHead` and
   `STEP_LABEL` with them — only the names they do *not* define are handed in as parameters. */
const live = new Function("el", "$", "bot", "NAME", "chan", "S", "AV", "AVK", "clockStart",
  [escSrc, hueOfSrc, hueSpanSrc, toolHeadSrc, stepSrc, block].join("\n")
  + "\nreturn {WORKING, liveEvent, workingRow, workingDrop, workingClear, workingPaint, firstSentence};")(
  (t, c) => node(c), sel => (sel === "#working" ? box : null), bot, NAME, chan, S, AV, AVK,
  n => clocked.set(n, (clocked.get(n) || 0) + 1));

const rowOf = id => live.WORKING.get("growth\u0000" + id);

console.log("\n-- one line, said the way the transcript says it --");
live.liveEvent("growth", { type: "agent", id: "atlas", name: "Atlas", state: "start" });
ok("a bot handed work gets a row", box.children.length === 1 && !!rowOf("atlas"), String(box.children.length));
ok("the strip is no longer hidden", box.hidden === false);
ok("its name is the bot's own, in the bot's own hue",
  rowOf("atlas").row.children[1].className === "wname hue"
  && rowOf("atlas").row.children[1].attrs.includes("--mc:" + AV.purple),
  rowOf("atlas").row.children[1].attrs);
ok("its title rides along", rowOf("atlas").title.textContent === "· Chief Marketing Strategist", rowOf("atlas").title.textContent);
live.liveEvent("growth", { type: "agent", id: "plain", name: "Plain", state: "start" });
ok("a bot with no title leaves no dangling separator", rowOf("plain").title.textContent === "", JSON.stringify(rowOf("plain").title.textContent));
ok("a bot that has just been handed work is working", rowOf("atlas").phase.textContent === "· Working…", rowOf("atlas").phase.textContent);
ok("and has nothing to show yet", rowOf("atlas").act.textContent === "", rowOf("atlas").act.textContent);

console.log("\n-- what it says the bot is doing --");
live.liveEvent("growth", { type: "tool", agent: "atlas", name: "run_shell", args: { command: "npm run build" } });
ok("the tool it just called, said as a tool line", rowOf("atlas").act.textContent === "— $ npm run build", rowOf("atlas").act.textContent);
live.liveEvent("growth", { type: "agent_text", agent: "atlas", text: "I will open Threads now.", delta: true });
ok("a tool outranks the words the bot is saying", rowOf("atlas").act.textContent === "— $ npm run build", rowOf("atlas").act.textContent);
live.liveEvent("growth", { type: "agent_text", agent: "plain", text: "First I will look around. Then I will report.", delta: false });
ok("with no tool yet, its first sentence stands in",
  rowOf("plain").act.textContent === "— First I will look around.", rowOf("plain").act.textContent);
live.liveEvent("growth", { type: "agent", id: "scout", name: "Scout", state: "start" });
ok("a bot with nothing to show shows nothing", rowOf("scout").act.textContent === "", rowOf("scout").act.textContent);
live.liveEvent("growth", { type: "status", agent: "scout", state: "thinking" });
ok("the phase is the app's own word for the phase", rowOf("scout").phase.textContent === "· Thinking…", rowOf("scout").phase.textContent);
live.liveEvent("growth", { type: "approval", agent: "scout", cmd: "rm -rf /tmp/x" });
ok("a bot waiting on you says so, off the event that names it",
  rowOf("scout").phase.textContent === "· " + STEP_LABEL.approval, rowOf("scout").phase.textContent);

console.log("\n-- one row per bot, whatever the bot does --");
const before = box.children.length, rowEl = rowOf("atlas").row;
for (const ev of [
  { type: "tool", agent: "atlas", name: "browser_open", args: { url: "https://threads.com" } },
  { type: "status", agent: "atlas", state: "working" },
  { type: "tool", agent: "atlas", name: "read_file", args: { path: "app.js" } },
  { type: "agent_text", agent: "atlas", text: "Done.", delta: true },
]) live.liveEvent("growth", ev);
ok("four more events for one bot are still one row",
  box.children.length === before && rowOf("atlas").row === rowEl, `${before} -> ${box.children.length}`);
ok("...and the row is the latest thing it did", rowOf("atlas").act.textContent === "— app.js", rowOf("atlas").act.textContent);
ok("the row was edited, never rebuilt — the clock's start time survives",
  clocked.get(rowOf("atlas").clock) === 1, String(clocked.get(rowOf("atlas").clock)));

console.log("\n-- and gone when that bot is done --");
live.liveEvent("growth", { type: "agent", id: "atlas", name: "Atlas", state: "done" });
ok("its row goes", !rowOf("atlas") && rowEl.removed);
ok("...and the others stay", !!rowOf("plain") && !!rowOf("scout"));
live.liveEvent("growth", { type: "final", text: "— everyone responded —" });
ok("a finished turn leaves no row behind", box.children.length === 0 && box.hidden === true,
  `${box.children.length} rows, hidden=${box.hidden}`);

console.log("\n-- a room, and only the room on screen --");
live.liveEvent("growth", { type: "agent", id: "atlas", name: "Atlas", state: "start" });
ok("a new turn brings its rows back", box.children.length === 1 && box.hidden === false, String(box.children.length));
S.active = "atlas";                                    // a 1:1 chat: its header already says this
live.liveEvent("atlas", { type: "tool", agent: "atlas", name: "run_shell", args: { command: "ls" } });
ok("a 1:1 chat has no strip", box.children.length === 1 && rowOf("atlas").act.textContent === "", rowOf("atlas").act.textContent);
S.active = "growth"; live.workingPaint();
live.liveEvent("growth", { type: "tool", agent: "atlas", name: "run_shell", args: { command: "ls" } });
ok("...and the room draws its own again", rowOf("atlas").act.textContent === "— $ ls", rowOf("atlas").act.textContent);
/* The bug this pins: a row only existed for the room on screen, so switching away and back lost it,
   and a bot in a long silent step had nothing left to say it was still working. */
S.active = "atlas";
live.liveEvent("growth", { type: "tool", agent: "atlas", name: "run_shell", args: { command: "pwd" } });
ok("work in a room you are not looking at is still recorded", rowOf("atlas").act.textContent === "— $ pwd", rowOf("atlas").act.textContent);
ok("...but is not shown under the chat you are in", rowOf("atlas").row.hidden === true && box.hidden === true);
S.active = "growth"; live.workingPaint();
ok("coming back shows what the bot is still doing, with no event needed",
  rowOf("atlas").row.hidden === false && box.hidden === false && rowOf("atlas").act.textContent === "— $ pwd");
live.workingClear("other");
ok("another room's turn ending leaves this room's rows alone", !!rowOf("atlas") && box.hidden === false);
live.liveEvent("growth", { type: "status", state: "working" });     // a room-level status names no bot
ok("a status that names no bot is put on no row", box.children.length === 1, String(box.children.length));

console.log("\n-- the pieces the row is built from --");
ok("the first sentence stops at the first full stop",
  live.firstSentence("First I will look. Then I will report.") === "First I will look.");
ok("a newline does not end a sentence early",
  live.firstSentence("First I will\nlook around. Then report.") === "First I will look around.");
ok("no full stop at all means the whole thing", live.firstSentence("checking the repo") === "checking the repo");
ok("and nothing means nothing", live.firstSentence("") === "" && live.firstSentence(null) === "");
ok("the tool line is the transcript's own",
  toolHead("delegate", { role: "scout", task: "read the docs" }) === "→ Scout: read the docs");
live.workingClear("growth");
ok("clearing leaves nothing at all", live.WORKING.size === 0 && box.children.length === 0 && box.hidden === true);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
