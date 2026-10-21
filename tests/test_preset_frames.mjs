/* Offline checks for the preset frame clock (mochi.js) — no browser, no canvas.
   Run: node tests/test_preset_frames.mjs   (exit 0 = all green) */
const { presetFrame, PRESET_FRAMES } = await import("../mochi.js");

let pass = 0, fail = 0;
const ok = (name, cond, extra = "") => {
  if (cond) { pass++; console.log("  ok  " + name); }
  else { fail++; console.log("  FAIL " + name + (extra ? "  -> " + extra : "")); }
};

console.log("\n-- preset frames --");
ok("a preset is 21 frames", PRESET_FRAMES.length === 21, String(PRESET_FRAMES.length));

/* The hard requirement: a working bot's mouth never moves, whatever the emotion channel says. */
{
  let bad = "";
  for (let i = 0; i < 2000; i++) {
    const t = i * 0.01, f = presetFrame("working", t, 1, 1, 0);
    if (!f.startsWith("work-") || !PRESET_FRAMES.includes(f)) { bad = t + ":" + f; break; }
  }
  ok("working only ever shows work frames, even with the mouth open", !bad, bad);
}
ok("working blinks on its 3.7s clock",
   presetFrame("working", 3.7, 0, 1) === "work-closed" &&
   presetFrame("working", 3.69, 0, 1) !== "work-closed");
ok("working smiles for 0.5s in every other 2.3s window",
   presetFrame("working", 4.7, 0, 1) === "work-happy" &&
   presetFrame("working", 1.0, 0, 1) !== "work-happy" &&
   presetFrame("working", 2.4, 0, 1) !== "work-happy");
ok("working alternates its two desk frames every 0.22s",
   presetFrame("working", 1.0, 0, 1) === "work-a" &&
   presetFrame("working", 1.22, 0, 1) === "work-b");

/* Talking: there is no speaking state, so `emo.open` drives the mouth cycle. */
ok("an open mouth cycles m0..m3 every 0.13s",
   ["m0", "m1", "m2", "m3", "m0"].every((f, i) => presetFrame("idle", i * 0.13, 0.5, 1) === f),
   [0, 1, 2, 3, 4].map(i => presetFrame("idle", i * 0.13, 0.5, 1)).join(","));
ok("a shut mouth does not cycle", presetFrame("idle", 0.26, 0.0, 1) === "base");

/* Idle blinks on the engine's own `open` channel. */
ok("idle closes its eyes during a blink", presetFrame("idle", 1, 0, 0.4) === "closed");
ok("idle is base between blinks", presetFrame("idle", 1, 0, 1) === "base");

/* A state's own frame wins over `emo.open`: those states' default emotions open the mouth
   (thinking is "curious"), so the other order would never show the expression. */
{
  const want = { finished: "e-happy", thinking: "g-think", approval: "g-thumb", question: "e-surprised",
                 error: "e-annoyed", ratelimit: "e-annoyed", sleeping: "e-sleepy", bored: "e-bored",
                 dizzy: "e-confused" };
  for (const [st, frame] of Object.entries(want))
    ok(st + " wears " + frame, presetFrame(st, 1, 0.9, 1) === frame, presetFrame(st, 1, 0.9, 1));
}

ok("a first poke shows the jolt frame",
   presetFrame("idle", 1, 0, 1, "p1") === "p1" && presetFrame("idle", 1, 0, 1) !== "p1");
ok("a repeated poke shows the exasperated frame", presetFrame("idle", 1, 0, 1, "p2") === "p2");
ok("a poke reaches a bot at its desk", presetFrame("working", 1, 1, 1, "p1") === "p1");

ok("every state and time lands on a shipped frame", (() => {
  for (const st of ["idle", "working", "thinking", "searching", "approval", "question", "finished",
                    "error", "sleeping", "ratelimit", "dizzy", "bored", "nope"])
    for (let i = 0; i < 400; i++)
      if (!PRESET_FRAMES.includes(presetFrame(st, i * 0.05, (i % 3) * 0.3, i % 2, ["", "p1", "p2"][i % 3])))
        return false;
  return true;
})());

console.log("\n" + pass + " passed, " + fail + " failed\n");
process.exit(fail ? 1 : 0);
