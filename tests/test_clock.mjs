/* Offline checks for the long-step clock in app.js — no browser, no DOM library.

   The clock is what stops a slow turn from looking like a hung one: it counts on the step that is
   running and on each command row while it runs, and past a threshold the card says so in words.
   app.js is an ES module that boots the whole UI, so it cannot be imported here; the block is read
   out of the source and run against a few fake nodes. If the extraction ever stops matching, these
   checks fail rather than pass on nothing.

   Run: node tests/test_clock.mjs   (exit 0 = all green) */
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../app.js", import.meta.url), "utf8");
const start = src.indexOf("const LONG_STEP_MS");
/* To the end of the block, not to the first `setInterval(clockTick, …)` — that line sits inside
   `clockStart`, so slicing there left the block truncated mid-expression and unable to parse. */
const end = src.indexOf("\nfunction stepSet(");
if (start < 0 || end < 0 || end < start) { console.log("FAIL could not find the clock block in app.js"); process.exit(1); }
const block = src.slice(start, end);

let pass = 0, fail = 0;
const ok = (name, cond, extra = "") => {
  if (cond) { pass++; console.log("  ok  " + name); }
  else { fail++; console.log("  FAIL " + name + (extra ? "  -> " + extra : "")); }
};

/* A step card: the clock element sits beside the label that gets reworded. A tool row has no label,
   which is the other shape the same tick has to cope with. */
const mkStep = () => {
  const cls = new Set();
  const label = { dataset: { base: "Working…", long: "Still working…" }, textContent: "Working…" };
  const n = { dataset: {}, textContent: "", parentElement: { querySelector: s => (s === ".tlabel" ? label : null) },
              classList: { toggle: (c, on) => { on ? cls.add(c) : cls.delete(c); }, has: c => cls.has(c) } };
  return { n, label, cls };
};
const mkTool = () => {
  const n = { dataset: {}, textContent: "", parentElement: { querySelector: () => null },
              classList: { toggle: () => {}, has: () => false } };
  return { n };
};

let nodes = [];
const clock = new Function("$$", block + "\nreturn {clockText, clockStart, clockStop, clockTick, LONG_STEP_MS};")
  (() => nodes);

console.log("\n-- how a wait is said --");
ok("under a minute counts in seconds", clock.clockText(0) === "0s" && clock.clockText(12500) === "12s");
ok("past a minute it reads minutes and seconds", clock.clockText(65000) === "1m 05s", clock.clockText(65000));
ok("...with the seconds padded, so the width does not jump", clock.clockText(62000) === "1m 02s");
ok("a long one keeps counting up", clock.clockText(3725000) === "62m 05s", clock.clockText(3725000));
ok("the threshold is a real wait, not a blink", clock.LONG_STEP_MS >= 30000);

console.log("\n-- a step that is taking a while --");
const s = mkStep(); nodes = [s.n];
clock.clockStart(s.n);
ok("a started step carries its start time", !!s.n.dataset.since);
s.n.dataset.since = String(Date.now() - 5000); clock.clockTick();
ok("under the threshold it just counts", s.n.textContent === "5s", s.n.textContent);
ok("...and the card still says the plain thing", s.label.textContent === "Working…" && !s.cls.has("long"));
s.n.dataset.since = String(Date.now() - 60000); clock.clockTick();
ok("past the threshold the card admits the wait", s.label.textContent === "Still working…", s.label.textContent);
ok("...and the clock is highlighted and still counting",
   s.cls.has("long") && s.n.textContent === "1m 00s", s.n.textContent);
clock.clockStop(s.n);
ok("a finished step loses its clock", s.n.textContent === "" && !s.n.dataset.since);

console.log("\n-- a command that is taking a while --");
const t = mkTool(); nodes = [t.n];
clock.clockStart(t.n); t.n.dataset.since = String(Date.now() - 90000); clock.clockTick();
ok("a tool row clocks too, with no label to swap", t.n.textContent === "1m 30s", t.n.textContent);
clock.clockStop(t.n);
ok("...and stops when the command returns", t.n.textContent === "");

console.log("\n-- only what is running is ticked --");
nodes = [];
clock.clockTick();
ok("nothing on screen is not an error", true);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
