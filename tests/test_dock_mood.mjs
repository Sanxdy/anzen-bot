/* Offline checks for the dock's mood rules in app.js — no browser, no DOM library.

   Three things about the corner are logic rather than drawing, and each answers a way it used to
   read wrong: a turn steps working → thinking → working several times a second, so the face is now
   held for a second; a failed turn used to end in the same `idle` a finished one does, so it now
   wears its own face for a few seconds; and a dock nobody touched held one neutral face forever, so
   it now goes to sleep. app.js boots the whole UI and cannot be imported, so the block is read out
   of the source and run against stubs — the clock and the timers are injected, so nothing here waits
   a real second or five minutes.

   Run: node tests/test_dock_mood.mjs   (exit 0 = all green) */
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../app.js", import.meta.url), "utf8");
const cut = (from, to) => {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0 || b < a) { console.log("FAIL could not find " + from + " in app.js"); process.exit(1); }
  return src.slice(a, b);
};
/* The pieces the dock's rules lean on, lifted out of app.js rather than re-written here: the state
   it holds, the constants, the label table it announces from, and the rules themselves. `chime` and
   `announce` are stubs — what is under test is when a state is shown, not what it sounds like. */
const block = cut('let dockReal = "idle"', "\nconst STATES_LABEL")
  + cut("const STATES_LABEL = {", "\nconst H_STATE")
  + cut("function setDock(st) {", "function dockFace()");

let pass = 0, fail = 0;
const ok = (name, cond, extra = "") => {
  if (cond) { pass++; console.log("  ok  " + name); }
  else { fail++; console.log("  FAIL " + name + (extra ? "  -> " + extra : "")); }
};

let clock = 0, tid = 0, interval = null;
const timers = new Map();
const setT = (fn, ms) => { const id = ++tid; timers.set(id, { fn, at: clock + ms }); return id; };
const clearT = id => timers.delete(id);
const advance = ms => {
  clock += ms;
  /* In time order, like a real event loop: the queue-firing timer and the failure's hand-back can
     both be due inside one jump, and whichever was set first is not necessarily the earlier one. */
  for (const [id, t] of [...timers].sort((a, b) => a[1].at - b[1].at)) {
    if (t.at <= clock) { timers.delete(id); t.fn(); }
  }
};
const shown = [], chimed = [], said = [];
const handlers = {};
const S = { dock: { setState: s => shown.push(s) } };
const api = new Function("announce", "chime", "S", "$", "performance", "setTimeout", "clearTimeout",
  "setInterval", "document", block +
  "\nreturn { setDock, failDock, dockWake, tick: () => sleepTimer && null, state: () => dockReal };")(
  s => said.push(s), s => chimed.push(s), S, () => null, { now: () => clock }, setT, clearT,
  (fn) => { interval = fn; return 1; },
  { addEventListener: (ev, fn) => { handlers[ev] = fn; } });
const { setDock, failDock, dockWake: wake, state } = api;

console.log("\n-- a mood holds for a second --");
setDock("working");
ok("the first state shows at once", state() === "working" && shown.length === 1, shown.join(","));
setDock("thinking");
ok("a state that arrives 100ms later waits", state() === "working" && shown.length === 1, shown.join(","));
ok("...without chiming or announcing yet", chimed.length === 1 && said.length === 1,
   chimed.join(",") + " / " + said.join(","));
advance(899);
ok("...still waiting just short of a second", state() === "working", state());
advance(101);
ok("...and shows when the second is up", state() === "thinking", state());
ok("...announced once, when it was shown", said.length === 2 && said[1] === "thinking…", said.join(","));

console.log("\n-- a flapping turn lands on the last mood --");
shown.length = 0; said.length = 0;
advance(2000); setDock("working");
advance(100); setDock("thinking"); advance(100); setDock("searching"); advance(100); setDock("working");
advance(1000);
ok("the newest held state wins, not a queue of all of them",
   shown[shown.length - 1] === "working" && shown.filter(s => s === "thinking").length === 0, shown.join(","));

console.log("\n-- a repeat of the shown mood cancels what was queued --");
shown.length = 0;
advance(2000); setDock("working"); advance(100); setDock("thinking");
advance(100); setDock("working");               // the model answered: the thinking is over
advance(1500);
ok("the bot stays at its desk, and the stale mood never lands", state() === "working", shown.join(","));

console.log("\n-- an interruption skips the wait --");
shown.length = 0;
advance(2000); setDock("working"); advance(50); setDock("approval");
ok("an approval is on screen immediately", state() === "approval", state());
ok("...and the state it interrupted is not replayed later", (advance(1500), state() === "approval"), state());
/* The turn's own `finally` sets idle the moment the stream ends, so a finish that queued would be
   replaced before it was ever drawn — and the confetti with it. */
shown.length = 0;
advance(2000); setDock("working"); advance(100); setDock("finished"); setDock("idle");
ok("a finish shows at once, not after the idle that follows it", state() === "finished", state());
advance(1000);
ok("...and hands over to idle a second later", state() === "idle", state());

console.log("\n-- a failure wears a face of its own --");
shown.length = 0;
advance(2000); setDock("working"); failDock("The server refused this turn (HTTP 500).");
ok("a failed turn is not shown as idle", state() === "error", state());
advance(3100);
ok("...it stays up for about three seconds", state() === "error", state());
advance(200);
ok("...then goes back to idle", state() === "idle", state());
/* A rate limit clears on its own, so it gets the softer face rather than the red one. */
failDock("The API is rate-limiting you (HTTP 429) — try again shortly.");
ok("a rate limit gets the sweating face, not the error one", state() === "ratelimit", state());
advance(3300);
ok("...and clears the same way", state() === "idle", state());
/* A second failure restarts the clock; the first one's timer must not cut the second short. */
failDock("boom"); advance(2000); failDock("boom again");
advance(1500);
ok("a second failure is not cut short by the first one's timer", state() === "error", state());
advance(2000);
ok("...and both clear once the last one has had its time", state() === "idle", state());
/* A turn that started while the failure face was up must not be knocked back to idle by its timer. */
failDock("boom"); setDock("working"); advance(4000);
ok("a turn started after a failure is left alone", state() === "working", state());

console.log("\n-- an untouched dock goes to sleep --");
advance(2000); setDock("idle");
advance(60 * 1000); interval();
ok("a minute of quiet does not put it to sleep", state() === "idle", state());
advance(5 * 60 * 1000); interval();
ok("five minutes of quiet does", state() === "sleeping", state());
wake();
ok("any interaction wakes it", state() === "idle", state());
advance(5 * 60 * 1000 + 1000); interval();
ok("...and it dozes off again after another five", state() === "sleeping", state());
setDock("working");
advance(10 * 60 * 1000); interval();
ok("a dock that is working never sleeps", state() === "working", state());
/* The listeners are the wake path, so they have to be the real ones. */
ok("pointer, key and wheel all wake it", ["pointerdown", "keydown", "wheel"].every(e => typeof handlers[e] === "function"),
   Object.keys(handlers).join(","));

console.log("\n" + pass + " passed, " + fail + " failed\n");
process.exit(fail ? 1 : 0);
