/* Offline checks for the notification chimes (sound.js) — no browser, no real audio.
   Run: node tests/test_sound.mjs   (exit 0 = all green) */

let pass = 0, fail = 0;
const ok = (name, cond, extra = "") => {
  if (cond) { pass++; console.log("  ok  " + name); }
  else { fail++; console.log("  FAIL " + name + (extra ? "  -> " + extra : "")); }
};

/* A fresh copy of the module per scenario. `ac` and `dead` are module state — the context is
   opened once and kept — so a scenario that needs its own cannot share one with the others.
   Node gives a distinct instance per query string on the specifier. */
let seq = 0;
const load = () => import("../sound.js?v=" + (++seq));

/* A Web Audio stand-in that records what a cue actually schedules. `new C()` on a function that
   returns an object yields that object, so the stub needs no prototype. */
function studio(state = "running") {
  const rec = { notes: [], resumed: 0, state, currentTime: 10 };
  rec.ctx = {
    get state() { return rec.state; },
    get currentTime() { return rec.currentTime; },
    destination: { name: "destination" },
    resume() { rec.resumed++; rec.state = "running"; return Promise.resolve(); },
    createOscillator() {
      const o = { type: null, freq: null, startAt: null, stopAt: null, gn: null,
        frequency: { setValueAtTime(v) { o.freq = v; } },
        connect(n) { o.gn = n; return n; },
        start(t) { o.startAt = t; rec.notes.push(o); },
        stop(t) { o.stopAt = t; } };
      return o;
    },
    createGain() {
      const g = { env: [], to: null,
        connect(n) { g.to = n; return n; },
        gain: { setValueAtTime(v, t) { g.env.push(["set", v, t]); },
                exponentialRampToValueAtTime(v, t) { g.env.push(["ramp", v, t]); } } };
      return g;
    },
  };
  return rec;
}
const peaks = o => o.gn.env.filter(([k]) => k === "ramp").map(([, v]) => v);
const peakOf = o => Math.max(...peaks(o));

const { CUES, CUE_FOR } = await import("../sound.js");

console.log("\n-- the cue table --");
{
  const names = Object.keys(CUES);
  ok("there is a cue for each kind of interruption", names.length >= 3, names.join(","));
  ok("every cue is a contour of at least two notes", names.every(n => CUES[n].length >= 2),
     JSON.stringify(names.map(n => [n, CUES[n].length])));
  const wellFormed = ([f, at, dur, g, type]) =>
    typeof f === "number" && f > 20 && f < 20000 && at >= 0 && dur > 0 && g > 0 && g <= 1 &&
    ["sine", "triangle", "square", "sawtooth"].includes(type);
  ok("every note names a real frequency, timing, gain and waveform",
     names.every(n => CUES[n].every(wellFormed)), JSON.stringify(CUES));
  ok("the notes of a cue are in time order",
     names.every(n => CUES[n].every((x, i) => i === 0 || x[1] >= CUES[n][i - 1][1])));
  /* Two cues that rose the same way would be told apart only by pitch, which is exactly the
     thing a notification must not depend on. */
  const contour = n => CUES[n].map(([f]) => Math.round(f)).join(">");
  ok("no two cues share a contour", new Set(names.map(contour)).size === names.length,
     names.map(n => n + ":" + contour(n)).join("  "));
  ok("no cue is longer than half a second",
     names.every(n => Math.max(...CUES[n].map(x => x[1] + x[2])) <= 0.5),
     JSON.stringify(names.map(n => [n, Math.max(...CUES[n].map(x => x[1] + x[2]))])));
}

console.log("\n-- which states are worth a sound --");
{
  ok("a finished turn chimes", CUE_FOR.finished === "done", String(CUE_FOR.finished));
  ok("a failed turn chimes, with its own cue", CUE_FOR.error === "error", String(CUE_FOR.error));
  ok("needing approval chimes", CUE_FOR.approval === "ask", String(CUE_FOR.approval));
  ok("being asked something chimes", CUE_FOR.question === "ask", String(CUE_FOR.question));
  ok("being rate limited chimes", CUE_FOR.ratelimit === "limit", String(CUE_FOR.ratelimit));
  ok("every mapped state has a cue behind it", Object.values(CUE_FOR).every(c => CUES[c]),
     JSON.stringify(CUE_FOR));
  /* The middle of a turn must stay silent, or a long run becomes a metronome. */
  const quiet = ["idle", "working", "thinking", "searching", "sleeping", "dizzy", "bored"];
  ok("the middle of a turn is silent", quiet.every(s => !CUE_FOR[s]),
     JSON.stringify(quiet.filter(s => CUE_FOR[s])));
  ok("done, error and ask are three different sounds",
     new Set([CUE_FOR.finished, CUE_FOR.error, CUE_FOR.approval]).size === 3);
}

console.log("\n-- the synth --");
{
  const rec = studio();
  globalThis.AudioContext = function () { return rec.ctx; };
  const s = await load();

  ok("nothing is scheduled before the first gesture",
     s.cue("done", 0.5) === false && rec.notes.length === 0);
  ok("unlock() opens the context", s.unlock() === rec.ctx);
  ok("unlock() is idempotent, so it never stacks contexts", s.unlock() === rec.ctx);

  rec.notes.length = 0;
  ok("a cue plays once the context is open", s.cue("done", 0.5) === true);
  ok("a cue schedules exactly the notes of that cue", rec.notes.length === CUES.done.length,
     rec.notes.length + " vs " + CUES.done.length);
  ok("the notes play at the cue's frequencies, in order",
     JSON.stringify(rec.notes.map(o => o.freq)) === JSON.stringify(CUES.done.map(n => n[0])),
     JSON.stringify(rec.notes.map(o => o.freq)));
  ok("each note rides its own gain envelope, wired to the output",
     rec.notes.every(o => o.gn && o.gn.env.length === 3 && o.gn.to === rec.ctx.destination));
  /* An exponential ramp to exactly 0 is invalid in Web Audio and throws — the tail must stop
     just short of silence. This is the one bug that would make the chime fail silently. */
  ok("no envelope step touches zero",
     rec.notes.every(o => o.gn.env.every(([, v]) => v > 0)),
     JSON.stringify(rec.notes.flatMap(o => o.gn.env)));
  ok("the envelope rises then falls", rec.notes.every(o => {
    const v = peaks(o); return v.length === 2 && v[0] > v[1];
  }), JSON.stringify(rec.notes.map(peaks)));
  ok("every note is stopped, so nothing is left running",
     rec.notes.every(o => o.stopAt > o.startAt), JSON.stringify(rec.notes.map(o => [o.startAt, o.stopAt])));

  rec.notes.length = 0;
  s.cue("done", 1.0);
  const loud = peakOf(rec.notes[0]);
  rec.notes.length = 0;
  s.cue("done", 0.25);
  const soft = peakOf(rec.notes[0]);
  ok("the volume scales the peak", loud > soft && soft > 0, loud + " vs " + soft);
  ok("even at full volume the peak stays below clipping", loud <= 1, String(loud));

  rec.notes.length = 0;
  ok("volume 0 is silence, not a quiet chime", s.cue("done", 0) === false && rec.notes.length === 0);
  ok("an unknown cue is a no-op, not a throw",
     s.cue("banana", 0.5) === false && rec.notes.length === 0);
}

console.log("\n-- when audio is unavailable --");
{
  const rec = studio("suspended");
  globalThis.AudioContext = function () { return rec.ctx; };
  const s = await load();
  s.unlock();
  ok("a suspended context is resumed", rec.resumed >= 1, String(rec.resumed));
}
{
  const rec = studio();
  rec.ctx.createOscillator = () => { throw new Error("blocked by policy"); };
  globalThis.AudioContext = function () { return rec.ctx; };
  const s = await load();
  s.unlock();
  ok("a failing synth is swallowed, never thrown at the caller", s.cue("done", 0.5) === false);
}
{
  delete globalThis.AudioContext;
  delete globalThis.webkitAudioContext;
  const s = await load();
  ok("a browser with no Web Audio at all is a no-op, not a throw",
     s.unlock() === null && s.cue("done", 0.5) === false);
}
{
  globalThis.AudioContext = function () { throw new Error("no device"); };
  const s = await load();
  ok("a context that refuses to open is a no-op, not a throw",
     s.unlock() === null && s.cue("done", 0.5) === false);
}

console.log("\n" + pass + " passed, " + fail + " failed\n");
process.exit(fail ? 1 : 0);
