/* Offline checks for the transcript's follow-the-newest behaviour in app.js — no browser, no DOM lib.

   Two bugs are pinned here. (1) `stick` used to measure "are they at the bottom?" *after* the new node
   was appended, so a message taller than the 80px band pushed the gap past the threshold and read as
   "the reader scrolled up" — a long reply or a tool card stranded you at the top of it and you had to
   scroll down yourself. (2) `render`/`reloadTranscript` jumped to the bottom unconditionally, so a
   turn ending or a poll dragged you out of the part you were reading a few seconds after you scrolled
   up. The rule now is one flag, turned off only by the reader's own scrolling.

   A third is pinned with them, because it is the one the reader reported: the flag had no way back.
   Once the reader scrolled away nothing turned the follow on again — not their own message, not the
   bot's reply — so a message typed while reading back landed below the fold and stayed there. Scrolling
   away is now a timed pause that hands the follow back on its own, and sending re-pins outright.

   A fourth is pinned with those: that pause used to hand the follow back by scrolling to the bottom
   itself, so a reader who had stopped short of the bottom was pulled down a few seconds later with
   nothing having been sent — and pulled down again on every further scroll, because each scroll re-arms
   the timer. Reading that as the app polling is exactly what it was. The pause now re-arms the follow
   and leaves the view alone; a message is the only thing that moves it.

   app.js is an ES module that boots the whole UI, so it cannot be imported here; the helpers, the
   landing branch at the end of `render`, and the `#msgs` scroll listener are read out of the source
   and run against stand-in nodes. If an extraction ever stops matching, these checks fail rather than
   pass on nothing.

   Run: node tests/test_transcript_scroll.mjs   (exit 0 = all green) */
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

/* ---------- a stand-in for the two nodes the transcript touches ---------- */
function box({ top = 0, height = 400, scroll = 1200 } = {}) {
  return { scrollTop: top, clientHeight: height, scrollHeight: scroll,
    style: { scrollBehavior: "smooth" },
    /* The listener under test is registered here, so keep it: `scrolled()` is what fires it. */
    addEventListener(type, fn) { this._on = fn; } };
}
const pill = { hidden: true };
const $ = sel => (sel === "#msgs" ? $._box : sel === "#jump" ? pill : null);

/* ---------- the blocks under test, lifted out of app.js ---------- */
const helpers = slice("const nearBottom =", "const MSGS =");
const landing = slice("  if (pinned) toBottom(box);", "\n}\n/* The answer as it is written");
const listener = slice('$("#msgs").addEventListener("scroll", () => {', "\n});");

/* Time is faked, because the pause below is timed: the checks have to say *when* the follow comes back,
   not wait four seconds to find out. */
const timers = [];
const setT = (fn, ms) => { const t = { fn, ms }; timers.push(t); return t; };
const clearT = t => { const i = timers.indexOf(t); if (i >= 0) timers.splice(i, 1); };
const fire = () => timers.splice(0, timers.length).forEach(t => t.fn());

const T = new Function("$", "setTimeout", "clearTimeout", [
  helpers,
  "function land(box, keep) {" + landing + "\n}",
  "function wire() {" + listener + "\n});\n}",
  "return { nearBottom, toBottom, stick, land, wire, holdFollow,"
  + " get pinned() { return pinned; }, set pinned(v) { pinned = v; } };",
].join("\n"))($, setT, clearT);

/* Register the real listener on a stand-in box, and fire it on demand. The handler reads
   `$("#msgs")` when it runs, so replacing `$._box` is what the tests below scroll. */
const wired = box();
$._box = wired;
T.wire();
const scrolled = () => wired._on();

/* ---------- "at the bottom" is a band, not a point ---------- */
console.log("-- what counts as the bottom --");
ok("exactly at the bottom is at the bottom", T.nearBottom(box({ top: 800, scroll: 1200, height: 400 })));
ok("a few pixels short still counts", T.nearBottom(box({ top: 760, scroll: 1200, height: 400 })));
ok("scrolled well up does not", !T.nearBottom(box({ top: 400, scroll: 1200, height: 400 })));

/* ---------- the reported bug: a tall new message must not strand you ---------- */
console.log("\n-- a new message follows when you were following --");
T.pinned = true;
let b = box({ top: 800, scroll: 1200, height: 400 });      // sitting at the bottom
b.scrollHeight = 1600;                                     // a 400px reply lands, taller than the band
ok("...the gap now reads as 'scrolled up' to a naive check", !T.nearBottom(b), "the bug this pins");
T.stick(b);
ok("...but the follow still goes to the newest message", b.scrollTop === b.scrollHeight, String(b.scrollTop));
ok("...and it stays pinned", T.pinned === true);

/* ---------- the reader's scroll is the only thing that turns it off ---------- */
console.log("\n-- scrolling up turns the follow off, and it stays off --");
$._box = box({ top: 400, scroll: 1200, height: 400 });     // the reader scrolls back
scrolled();
ok("scrolling up unpins", T.pinned === false);
pill.hidden = true; T.stick($._box);
ok("new output does not move the reader", $._box.scrollTop === 400, String($._box.scrollTop));
ok("...and the pill says there is more below", pill.hidden === false);

/* ---------- but only for a few seconds: a pause is not a decision ---------- */
/* The reported bug is that once the follow is off it never comes back: the transcript keeps growing, so
   the bottom moves away from a reader parked short of it, and every later message — theirs and the
   bot's — is drawn below the fold. Scrolling away is a pause, and it is timed. */
console.log("\n-- the pause hands the follow back on its own --");
ok("scrolling away leaves a catch-up pending", timers.length === 1, String(timers.length));
ok("...for a few seconds, not at once", timers[0].ms >= 3000 && timers[0].ms <= 5000, String(timers[0].ms));
$._box = box({ top: 400, scroll: 1600, height: 400 });     // the reader is still where they were
scrolled();
ok("scrolling again restarts it rather than stacking timers", timers.length === 1, String(timers.length));
fire();
/* The other reported bug, and the one this block exists to pin: firing used to drag the transcript to
   the bottom, so a reader parked short of it was pulled off what they were reading a few seconds later
   with nothing having been sent — and pulled off again on every further scroll, which is what made it
   read as the app polling. The follow is what comes back; the trip down is the next message's job. */
ok("when it fires the reader is left exactly where they were", $._box.scrollTop === 400, String($._box.scrollTop));
ok("...with the follow back on, so nothing had to be dragged to get it", T.pinned === true);
ok("...and the pill still says there is newer output below", pill.hidden === false);
ok("...and the next message is what moves them", (T.stick($._box), $._box.scrollTop === 1600), String($._box.scrollTop));
ok("...and no timer left running", timers.length === 0);

/* A timer that only re-arms must not be able to move the view however many times it is armed — the
   reported symptom was it happening *each* time the reader was short of the bottom. */
T.pinned = false; $._box = box({ top: 200, scroll: 1600, height: 400 });
for (let i = 0; i < 3; i++) { scrolled(); fire(); }
ok("a reader who keeps scrolling back is never pulled down by the clock",
   $._box.scrollTop === 200, String($._box.scrollTop));

T.pinned = false; T.holdFollow();
$._box = box({ top: 400, scroll: 1600, height: 400 });
T.toBottom($._box);                                        // the pill, or opening the chat again
ok("a deliberate trip to the bottom cancels the catch-up", timers.length === 0, String(timers.length));

/* ---------- sending is the reader asking for the newest message ---------- */
/* A message you typed is the one thing that must not land below the fold, whatever you had scrolled
   back to. Re-pinning on the way in is also what makes the bot's answer to it follow. */
console.log("\n-- your own message re-pins the transcript --");
const deliverSrc = slice("async function deliver(sid, text, opts) {", "\nasync function send()");
function runDeliver(active, sid) {
  const calls = [];
  const f = new Function("S", "busy", "queueAdd", "addMsg", "chan", "botOf", "runChat",
    "let pinned = false;\n" + deliverSrc + "\nreturn { deliver, pinned: () => pinned };");
  const ret = f({ active }, () => false, () => calls.push("queued"),
    role => calls.push(["add", role]), () => null, () => null, async () => {});
  ret.deliver(sid, "hi", {});        // the body up to its first `await` runs synchronously
  return { calls, pinned: ret.pinned() };
}
const mine = runDeliver("company", "company");
ok("your own message is drawn here", mine.calls.length === 1 && mine.calls[0][1] === "user", JSON.stringify(mine.calls));
ok("...and the transcript is re-pinned for it", mine.pinned === true);
const elsewhere = runDeliver("company", "other-chat");
ok("a message for another chat draws nothing here", elsewhere.calls.length === 0);
ok("...and leaves this transcript alone", elsewhere.pinned === false);

console.log("\n-- a redraw while you are reading back keeps your place --");
T.pinned = false;                                          // the reader has scrolled back
$._box = box({ top: 400, scroll: 1600, height: 400 });
T.land($._box, 400);
ok("the redraw restores the exact position", $._box.scrollTop === 400, String($._box.scrollTop));
ok("...without animating the trip there", $._box.style.scrollBehavior === "smooth", $._box.style.scrollBehavior);
ok("...and the pill is shown", pill.hidden === false);

console.log("\n-- a redraw while you are following lands at the newest message --");
T.pinned = true;
$._box = box({ top: 800, scroll: 1600, height: 400 });
T.land($._box, 800);
ok("the redraw goes to the bottom", $._box.scrollTop === 1600, String($._box.scrollTop));
ok("...and stays pinned", T.pinned === true);

/* ---------- getting back to the bottom resumes the follow ---------- */
console.log("\n-- the way back to following --");
T.pinned = false; pill.hidden = false;
$._box = box({ top: 0, scroll: 1600, height: 400 });
T.toBottom($._box);
ok("the pill's jump goes to the bottom", $._box.scrollTop === 1600, String($._box.scrollTop));
ok("...and re-pins the transcript", T.pinned === true);

T.pinned = false;
$._box = box({ top: 1200, scroll: 1600, height: 400 });    // the reader scrolls back down themselves
scrolled();
ok("scrolling back to the bottom re-pins", T.pinned === true);
ok("...and clears the pill", pill.hidden === true);

/* ---------- the follow write must not animate ---------- */
console.log("\n-- an animated follow would misread itself --");
T.pinned = true;
$._box = box({ top: 0, scroll: 1600, height: 400 });
$._box.style.scrollBehavior = "smooth";
T.toBottom($._box);
ok("the write is instant, so it lands where it means to", $._box.scrollTop === 1600);
ok("...and the reader's own smooth scrolling is put back", $._box.style.scrollBehavior === "smooth");

/* ---------- opening a chat must not rebuild it one forced layout at a time ---------- */
/* Every row the rebuild appends used to go through MSGS.add, which scrolls — and a scroll reads the
   transcript's scrollHeight, forcing a synchronous layout of everything appended so far. Once per
   message that is O(n²) over the length of the chat: opening a 616-message chat measured 330 ms, of
   which a CPU profile put 102 ms inside toBottom alone. The rebuild now appends through a sink that
   neither scrolls nor animates, and scrolls once at the end — where the landing branch above runs. */
console.log("\n-- the rebuild appends without a forced layout per row --");
const sinkSrc = slice("const sink = { add:", ";\n  if (!messages.length");
const target = { kids: [], appendChild(n) { this.kids.push(n); } };
const sink = new Function("box", sinkSrc + "\nreturn sink;")(target);
const row = { style: {} };
sink.add(row);
ok("the sink appends the row", target.kids[0] === row);
ok("...with no entrance animation, so a redraw does not re-fade the chat", row.style.animation === "none");
ok("...and scrolls nothing, so no layout is forced", sink.scroll() === undefined);

const loop = slice("messages.forEach((m, i) => {", "  if (pending) addApproval");
ok("tool rows go through the sink", loop.includes("addTool(m.agent, m.name, m.args || {}, m.out, sink)"));
ok("hand-off cards go through the sink", loop.includes('addCard("plan", ROUTE_LABEL, cleanBot(m.content), sink)'));
ok("messages go through the sink", loop.includes("addMsg(m.role, m.content, m.who, sink,"));

/* The live path is the one that must keep both: a message arriving really is arriving. */
const live = slice("const MSGS = {", "\n");
ok("a live append still follows the newest message", /scroll: *\(\) *=> *stick\(/.test(live));
ok("...and still drops the empty card", /dropEmpty\(\)/.test(live));

/* ---------- the app stopping the bot has to reach the transcript ---------- */
/* A refused command used to leave the room with nothing to read: the step row is folded, and a bot
   that was refused and then went quiet simply stopped. The `notice` event is that account, drawn as
   the same centred note the other app-level lines use. The branch is run rather than only read,
   because what it draws and what it says are the two things the report depends on. */
console.log("\n-- a notice from the app lands in the transcript --");
const noticeBranch = slice('  else if (ev.type === "notice" && ev.text) {', "\n}");
ok("the notice branch is the only one that claims a notice",
   (src.match(/ev\.type === "notice"/g) || []).length === 1);
function runNotice(ev, onScreen = true) {
  const calls = { card: [], chime: [], said: [], fail: [] };
  const to = { tag: "this turn's sink" };
  new Function("ev", "to", "chime", "announce", "addCard", "isLimit", "here", "failDock",
               "if (false) {} " + noticeBranch)(
    ev, to, l => calls.chime.push(l), t => calls.said.push(t),
    (cls, head, text, sink) => calls.card.push([cls, head, text, sink]),
    s => /429|rate.?limit/i.test(String(s || "")), () => onScreen, r => calls.fail.push(r));
  return { calls, to };
}
const warn = runNotice({ type: "notice", level: "warn", text: "Builder — refused: the secret store." });
ok("a notice is drawn in the transcript", warn.calls.card.length === 1, JSON.stringify(warn.calls.card));
ok("...as the app-level centred note", warn.calls.card[0][0] === "sys" && warn.calls.card[0][1] === "");
ok("...saying what the app did, in its own words", warn.calls.card[0][2] === "Builder — refused: the secret store.");
ok("...into the sink the turn was writing to, so a member's note lands in that member's chat",
   warn.calls.card[0][3] === warn.to);
ok("...and read out for a screen reader", warn.calls.said[0] === "Builder — refused: the secret store.");
ok("a warning does not chime", warn.calls.chime.length === 0);
ok("an error-level notice chimes", runNotice({ type: "notice", level: "error", text: "boom" }).calls.chime[0] === "error");
ok("a rate-limit notice also turns the corner orange",
   runNotice({ type: "notice", level: "warn", text: "429 rate limited" }).calls.fail.length === 1);
ok("...but only for the chat on screen",
   runNotice({ type: "notice", level: "warn", text: "429 rate limited" }, false).calls.fail.length === 0);
ok("a notice with no text draws nothing", runNotice({ type: "notice" }).calls.card.length === 0);

/* The live strip folds a turn onto its bot's row; a notice carries no phase, so it must pass through
   without being mistaken for one — a refused command must not leave a row reading "Working…". */
const liveSrc = slice("function liveEvent(sid, ev) {", "\n/* ---------------- the queue");
ok("the live strip folds only the events it knows", !/notice/.test(liveSrc));
ok("...and clears on the two that end a turn", /ev\.type === "final" \|\| ev\.type === "error"/.test(liveSrc));

/* ---------- a history read must answer for the chat it was asked about ---------- */
/* `reloadTranscript` is called by the end of a turn, by a wake-up and by the watch stream. The read
   is async, and a chat switch can land inside it: the answer then painted the chat you left into the
   chat you opened, and left `S.messages` holding the wrong record for the next render. */
console.log("\n-- a read that lands after a chat switch is dropped --");
const reloadSrc = slice("async function reloadTranscript() {", "\n/* Stop is offered");
function runReload() {
  const S = { active: "room" };
  const drawn = [], adopted = [];
  let answer;
  const fn = new Function("S", "get", "render", "adoptLive", `"use strict";${reloadSrc}\nreturn reloadTranscript;`)(
    S, () => new Promise(res => { answer = res; }), (m, p) => drawn.push([m, p]),
    (sid, live) => adopted.push([sid, live]));
  return { S, drawn, adopted, start: fn, answer: (...a) => answer(...a) };
}
const stale = runReload();
const staleRun = stale.start();
stale.S.active = "other";                                   // the user switches chats mid-read
stale.answer({ messages: [{ role: "user", content: "from the room" }], pending: null });
await staleRun;
ok("the answer is not painted into the chat you opened", stale.drawn.length === 0, JSON.stringify(stale.drawn));
ok("...and does not overwrite the record", stale.S.messages === undefined, JSON.stringify(stale.S.messages));

const fresh = runReload();
const freshRun = fresh.start();
fresh.answer({ messages: [{ role: "user", content: "still here" }], pending: null, live: { turn: "t1" } });
await freshRun;
ok("a read that still belongs to the chat on screen is drawn",
   fresh.drawn.length === 1 && fresh.S.messages.length === 1, JSON.stringify(fresh.drawn));
ok("...and a turn that is still running comes with it, so the strip and Stop can be drawn",
   fresh.adopted.length === 1 && fresh.adopted[0][0] === "room" && fresh.adopted[0][1].turn === "t1",
   JSON.stringify(fresh.adopted));

console.log(`\n${pass} ok, ${fail} failed`);
process.exit(fail ? 1 : 0);