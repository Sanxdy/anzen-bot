/* Offline checks for the mascot engine (mochi.js) — no browser, no canvas.
   Run: node tests/test_mochi.mjs   (exit 0 = all green) */

/* A 2d context that swallows every call and remembers every property. */
function fakeCtx() {
  const store = {};
  return new Proxy(store, {
    get(t, k) {
      if (k in t) return t[k];
      if (k === "createLinearGradient" || k === "createRadialGradient") return () => ({ addColorStop() {} });
      return () => {};
    },
    set(t, k, v) { t[k] = v; return true; },
  });
}
const fakeCanvas = () => ({ width: 0, height: 0, clientWidth: 160, clientHeight: 160,
  getContext: () => fakeCtx(), getBoundingClientRect: () => ({ left: 0, top: 0, width: 160, height: 160 }) });

globalThis.window = { devicePixelRatio: 2, addEventListener() {} };

const { speciesFor, SPECIES, EMOTIONS, STATES, Ease, MochiBot, eyeFrame, softLimit, OUTFITS, ACCESSORIES, textureFor } = await import("../mochi.js");

let pass = 0, fail = 0;
const ok = (name, cond, extra = "") => {
  if (cond) { pass++; console.log("  ok  " + name); }
  else { fail++; console.log("  FAIL " + name + (extra ? "  -> " + extra : "")); }
};

const mk = (opts = {}) => new MochiBot(fakeCanvas(), opts.state || "idle", opts);
const run = (b, frames = 20, dt = 0.05) => { for (let i = 0; i < frames; i++) { b.tick(dt); b.draw(); } };

console.log("\n-- species --");
ok("speciesFor is deterministic", speciesFor("producer") === speciesFor("producer") && speciesFor("qa") === speciesFor("qa"));
ok("speciesFor always lands on a real species",
   ["producer", "researcher", "builder", "qa", "ops", "", "a", "zzz", "Designer-2"].every(s => SPECIES[speciesFor(s)]));
const team = ["producer", "researcher", "builder", "qa", "ops"].map(speciesFor);
ok("the five default bots look different", new Set(team).size === 5, team.join(","));
ok("at least ten species exist", Object.keys(SPECIES).length >= 10, String(Object.keys(SPECIES).length));
ok("every species names a body, ears, eyes and idle motion",
   Object.values(SPECIES).every(s => s.body && s.ears && s.eyes && s.idle));
ok("unknown species falls back to a derived one", mk({ species: "nope" }).species === speciesFor(undefined));

console.log("\n-- render --");
for (const k of Object.keys(SPECIES)) {
  const b = mk({ species: k });
  let threw = null; try { run(b, 12); } catch (e) { threw = e.message; }
  ok("species " + k + " draws a full cycle", !threw, threw || "");
}

console.log("\n-- states --");
ok("every state names an emotion", Object.values(STATES).every(s => !s.emotion || EMOTIONS[s.emotion]));
for (const st of Object.keys(STATES)) {
  const b = mk({ state: st });
  let threw = null; try { run(b, 10); } catch (e) { threw = e.message; }
  ok("state " + st + " renders", !threw, threw || "");
}
ok("an unknown state falls back to idle", mk({ state: "banana" }).state === "idle");
ok("working reads as focused", mk({ state: "working" }).emotion === "focused");

console.log("\n-- emotions --");
for (const e of Object.keys(EMOTIONS)) {
  const b = mk({ state: "thinking" }); b.setEmotion(e);
  let threw = null; try { run(b, 8); } catch (err) { threw = err.message; }
  ok("emotion " + e + " renders", !threw, threw || "");
}
{
  const b = mk({ state: "thinking" });
  b.setEmotion("happy");
  const before = b.emo.smile;
  run(b, 40);
  ok("a happy bot blends its smile up", b.emo.smile > before + 0.3 && b.emo.smile > 0.7, String(b.emo.smile.toFixed(2)));
  b.setEmotion("angry");
  run(b, 40);
  ok("an angry bot blends its smile down", b.emo.smile < 0, String(b.emo.smile.toFixed(2)));
}

console.log("\n-- cursor --");
{
  const b = mk();
  run(b, 5);
  const wander = b._targetYaw;
  b.lookAt(1, 0, true);                       // hold the gaze, cursor style
  run(b, 30);
  ok("a held cursor wins over the wandering gaze", b._targetYaw > 0.5 && b._cursorOn, String(b._targetYaw.toFixed(2)));
  b.lookAt(0, 0);                             // release
  run(b, 5);
  ok("releasing the cursor hands the gaze back", !b._cursorOn, String(b._cursorOn));
  ok("the wander target moved off the cursor", Math.abs(b._targetYaw) < 0.5 || wander !== b._targetYaw);
}
{
  /* A bot absorbed in its state must not chase the mouse: working faces the desk, and the
     cursor is only the idle fallback. */
  const b = mk({ state: "working" });
  b.lookAt(1, 1, true);                       // cursor hard to the bottom-right
  run(b, 40);
  ok("a working bot ignores the cursor", Math.abs(b._targetYaw) < 0.2, String(b._targetYaw.toFixed(3)));
  ok("a working bot faces its desk (looks slightly down)", b._targetPitch > 0, String(b._targetPitch.toFixed(3)));
  b.setState("idle");
  run(b, 40);
  ok("back at idle the cursor takes over again", b._targetYaw > 0.5, String(b._targetYaw.toFixed(3)));
  const s = mk({ state: "sleeping" });
  s.lookAt(1, 0, true);
  run(s, 40);
  ok("a sleeping bot ignores the cursor too", Math.abs(s._targetYaw) < 0.05, String(s._targetYaw.toFixed(3)));
  const t = mk({ state: "thinking" });
  t.lookAt(1, 1, true);
  run(t, 40);
  ok("a thinking bot looks up, not at the mouse", t._targetPitch < 0, String(t._targetPitch.toFixed(3)));
}

console.log("\n-- eye projection --");
{
  /* Coucou's eyes live on a cylinder. The port must swing them, foreshorten them and let
     them slip past the horizon — a linear slide would fail every one of these. */
  const rx = 52 * 1.14, ry = 52 * 0.88, sp = 0.36, rest = -0.10;
  const L = eyeFrame(-1, 0, 0, rx, ry, sp, rest);
  const R = eyeFrame(1, 0, 0, rx, ry, sp, rest);
  ok("at rest the eyes sit either side of centre", L.x < 0 && R.x > 0 && Math.abs(L.x + R.x) < 1e-9);
  /* even at rest the eyes are on the curve, so they are already slightly foreshortened */
  ok("at rest the eyes sit on the cylinder, not flat on the face",
     Math.abs(L.fx - Math.cos(sp)) < 1e-9 && L.fx < 1, String(L.fx));

  const turn = eyeFrame(1, 0.62, 0, rx, ry, sp, rest);
  ok("a head turn swings the eyes the same way as the gaze", turn.x > R.x, `${turn.x} vs ${R.x}`);
  ok("the eye nearer the silhouette foreshortens away", turn.fx < 0.9, String(turn.fx));
  ok("the trailing eye stays wider than the leading one",
     eyeFrame(-1, 0.62, 0, rx, ry, sp, rest).fx > turn.fx);

  /* the eye rides a circle of radius rx — that is what a cylinder projection buys */
  const a = 0.62, cp = Math.cos(rest);
  ok("the eye rides the head's circle", Math.abs(turn.x - Math.sin(sp + a) * cp * rx) < 1e-9);
  const half = eyeFrame(1, 0.31, 0, rx, ry, sp, rest);
  ok("foreshortening is cos, not linear", Math.abs(half.fx - Math.cos(sp + 0.31)) < 1e-9, String(half.fx));

  const gone = eyeFrame(1, 1.4, 0, rx, ry, sp, rest);
  ok("an eye past the horizon is culled", !gone.vis);
  ok("an eye on the horizon is culled", !eyeFrame(1, Math.PI / 2 - sp + 0.01, 0, rx, ry, sp, rest).vis);

  /* vertical: cursor below the face (positive pitch) must drop the eyes on screen */
  const down = eyeFrame(1, 0, 0.5, rx, ry, sp, rest);
  ok("looking down drops the eyes", down.y > eyeFrame(1, 0, 0, rx, ry, sp, rest).y, String(down.y));
  ok("a downward look squashes the eyes vertically", down.fy < 1, String(down.fy));
}

console.log("\n-- soft limit --");
{
  ok("inside the band it changes nothing", softLimit(5, -10, 10, 3) === 5);
  ok("it never crosses the limit",
     [...Array(201)].every((_, i) => { const v = -100 + i;
        return softLimit(v, -10, 10, 3) < 10 && softLimit(v, -10, 10, 3) > -10; }));
  ok("it is strictly increasing, so the eye never doubles back",
     [...Array(200)].every((_, i) => softLimit(-100 + i, -10, 10, 3) < softLimit(-99 + i, -10, 10, 3)));
  /* continuous velocity at the knee: no visible stop where the limit starts to bite */
  const eps = 1e-6, before = (softLimit(7 - eps, -10, 10, 3) - softLimit(7 - 2 * eps, -10, 10, 3)) / eps;
  const after = (softLimit(7 + 2 * eps, -10, 10, 3) - softLimit(7 + eps, -10, 10, 3)) / eps;
  ok("velocity is continuous at the knee", Math.abs(before - after) < 1e-4, `${before} vs ${after}`);
}

console.log("\n-- eye / mouth bands --");
{
  /* Whatever the emotion and however far the gaze swings, the eyes must stay clear of the
     mouth and both must stay on the face. This is the bug the user reported. */
  let worst = Infinity, offFace = 0;
  for (const sp of Object.keys(SPECIES)) {
    for (const emo of Object.keys(EMOTIONS)) {
      for (const pitch of [-0.5, -0.25, 0, 0.25, 0.5]) {
        const b = mk({ species: sp });
        b.setEmotion(emo); b.emotion = emo; b.pitch = pitch; b.yaw = 0;
        const R = b.R, rx = R * 1.14, ry = R * 0.88;
        const G = b._faceGeom(R, rx, ry);
        const half = b._eyeHalfH(R);
        for (const sd of [-1, 1]) {
          const F = b.eyeAt(sd, R, rx, ry);
          if (!F.vis) continue;
          worst = Math.min(worst, G.mouthTop - (F.y + half));
          if (F.y - half < -ry * 0.99) offFace++;             // eye poking out the top
        }
        if (G.mouthY + R * 0.34 > ry * 0.95) offFace++;       // mouth off the bottom
      }
    }
  }
  ok("the eyes never reach the mouth, at any emotion or gaze",
     worst > 0, `worst gap ${worst.toFixed(2)}px`);
  ok("the gap stays visible, not a hairline", worst > 1.5, `worst gap ${worst.toFixed(2)}px`);
  ok("both bands stay on the face", offFace === 0, String(offFace));
}

console.log("\n-- poke --");
{
  const b = mk();
  b.poke();
  ok("a poke makes it excited", b.emotion === "excited");
  ok("a poke throws hearts", b.parts.length >= 3, String(b.parts.length));
  let threw = null; try { run(b, 30); } catch (e) { threw = e.message; }
  ok("the poke animation plays out", !threw, threw || "");
}

console.log("\n-- easing --");
ok("out() starts fast and lands exactly", Ease.out(0) === 0 && Ease.out(1) === 1 && Ease.out(0.5) > 0.5);
ok("inOut() is symmetric about the middle", Math.abs(Ease.inOut(0.5) - 0.5) < 1e-9 && Ease.inOut(0) === 0 && Ease.inOut(1) === 1);
ok("back() overshoots past the target then settles", Math.max(...[0.6, 0.7, 0.8, 0.9].map(Ease.back)) > 1 && Math.abs(Ease.back(1) - 1) < 1e-9);
ok("every ease is finite over the unit interval",
   Object.values(Ease).every(f => [...Array(21)].every((_, i) => Number.isFinite(f(i / 20)))));

console.log("\n-- keyframe tweens --");
{
  /* tick() blends the species' own idle motion into every channel, so a tween's exact
     keyframe values are only observable at the tween layer. Drive it directly here. */
  const b = mk();
  b.anim("tilt", [[0.5, 200, Ease.out]]);
  ok("a tween locks its channel", b.locks.has("tilt"));
  b.t = 0.2; b._stepTweens();
  ok("the tween reaches its target", b.tilt === 0.5, String(b.tilt));
  ok("the tween releases its channel when done", !b.locks.has("tilt"));
}
{
  const b = mk();
  b.anim("tilt", [[0.5, 200, Ease.out]]);
  const seen = [];
  for (let i = 0; i < 30; i++) { b.tick(0.02); seen.push(b.tilt); }
  ok("a locked channel is not overridden by idle motion mid-flight",
     seen[1] > 0 && Math.abs(seen[0]) < Math.abs(seen[1]), JSON.stringify(seen.slice(0, 3)));
}
{
  const b = mk();
  b.anim("oy", [[1, 100, Ease.lin], [0, 100, Ease.lin]]);
  b.t = 0.1; b._stepTweens();
  ok("a multi-key tween walks through its keyframes", Math.abs(b.oy - 1) < 1e-9, String(b.oy));
  b.t = 0.2; b._stepTweens();
  ok("a multi-key tween ends on its last key", b.oy === 0, String(b.oy));
}
{
  let fired = 0;
  const b = mk();
  b.anim("oy", [[1, 50, Ease.lin]], () => fired++);
  b.t = 0.05; b._stepTweens();
  ok("a tween's completion callback fires exactly once", fired === 1, String(fired));
  b.t = 0.1; b._stepTweens();
  ok("the completion callback does not re-fire", fired === 1, String(fired));
}

console.log("\n-- squash, blink, roll --");
{
  const b = mk();
  b.squash();
  let minSy = 1, maxSy = 1;
  for (let i = 0; i < 40; i++) { b.tick(0.016); minSy = Math.min(minSy, b.sy); maxSy = Math.max(maxSy, b.sy); }
  ok("squash compresses below 1", minSy < 0.85, String(minSy.toFixed(3)));
  ok("squash stretches past 1 on the way back", maxSy > 1.02, String(maxSy.toFixed(3)));
  ok("squash returns to the species' idle baseline", Math.abs(b.sy - 1) < 0.06, String(b.sy.toFixed(4)));
}
{
  /* exact keyframes again, read off the tween layer without idle motion mixed in */
  const b = mk();
  b.squash();
  b.t = 0.07; b._stepTweens();
  const sy1 = b.sy, sx1 = b.sx;
  b.t = 0.20; b._stepTweens();
  const sy2 = b.sy;
  b.t = 0.37; b._stepTweens();
  ok("squash compresses to 0.78", Math.abs(sy1 - 0.78) < 1e-9, String(sy1));
  ok("squash overshoots to 1.10", Math.abs(sy2 - 1.10) < 1e-9, String(sy2));
  ok("squash settles exactly on 1", b.sy === 1, String(b.sy));
  ok("squash and stretch stay in step", sx1 > 1 && sy1 < 1 && b.sx === 1, `sy:${sy1} sx:${sx1}`);
}
{
  const b = mk();
  b.blink();
  let minOpen = 1;
  for (let i = 0; i < 30; i++) { b.tick(0.016); minOpen = Math.min(minOpen, b.open); }
  ok("a blink actually closes the eyes", minOpen < 0.1, String(minOpen.toFixed(3)));
  ok("the eyes open again", Math.abs(b.open - 1) < 1e-6, String(b.open));
  ok("a blink is over inside 0.25s", b.locks.size === 0);
}
{
  const b = mk();
  b.setState("finished");
  let maxRoll = 0;
  for (let i = 0; i < 80; i++) { b.tick(0.02); maxRoll = Math.max(maxRoll, Math.abs(b.roll)); }
  ok("finished does a full barrel roll", maxRoll > Math.PI * 1.9, String(maxRoll.toFixed(2)));
  ok("the roll unwinds back to upright", Math.abs(b.roll) < 1e-6, String(b.roll));
}
{
  const b = mk();
  b.setState("dizzy");
  let maxRoll = 0;
  for (let i = 0; i < 90; i++) { b.tick(0.02); maxRoll = Math.max(maxRoll, Math.abs(b.roll)); }
  ok("dizzy rolls twice as far", maxRoll > Math.PI * 3.9, String(maxRoll.toFixed(2)));
}

console.log("\n-- response speed --");
{
  /* The complaint that started this: the old engine converged in ~0.24s, which reads as
     laggy. Coucou's rates settle in ~0.14-0.17s. Both channels must beat the old number. */
  const b = mk();
  b.lookAt(1, 1, true);
  let frames = 0, yawDone = -1, syDone = -1;
  b.squash();
  for (let i = 0; i < 200 && (yawDone < 0 || syDone < 0); i++) {
    b.tick(0.016); frames++;
    if (yawDone < 0 && Math.abs(b.yaw - 0.62) < 0.62 * 0.1) yawDone = frames * 0.016;
    if (syDone < 0 && Math.abs(b.sy - 1) < 0.1 * 0.1 && i > 20) syDone = frames * 0.016;
  }
  ok("the gaze reaches 90% of target within 0.42s", yawDone > 0 && yawDone < 0.42, String(yawDone));
  ok("the body settles from a squash within 0.45s", syDone > 0 && syDone < 0.45, String(syDone));
}

console.log("\n-- accessory spring --");
{
  const b = mk({ species: "cat" });
  b.anim("yaw", [[0.6, 200, Ease.out]]);
  let minDx = 0, maxDx = 0, crossings = 0, prev = 0;
  for (let i = 0; i < 90; i++) {
    b.tick(0.016);
    minDx = Math.min(minDx, b._physDx); maxDx = Math.max(maxDx, b._physDx);
    if (prev !== 0 && Math.sign(b._physDx) !== Math.sign(prev) && Math.abs(b._physDx) > 1e-4) crossings++;
    prev = b._physDx;
  }
  ok("a head turn drags the ears", Math.abs(minDx) > 0.02 || Math.abs(maxDx) > 0.02, String(maxDx.toFixed(4)));
  ok("the ears ring past neutral before settling", crossings >= 1, String(crossings));
  ok("the spring comes to rest", Math.abs(b._physDx) < 0.02, String(b._physDx.toFixed(4)));
}

console.log("\n-- idle life --");
{
  /* A quiet face is never a still image: it blinks on a timer, and now and then it fidgets.
     Pinned to mochi, whose idle only bobs — a jiggle/wobble species oscillates sy on every
     frame and would swamp the counters with its own idle motion rather than real fidgets. */
  const b = mk({ species: "mochi" });
  let blinks = 0;
  for (let i = 0; i < 1300; i++) { b.tick(0.016); if (b.open < 0.5) blinks++; }
  ok("an idle bot blinks on its own", blinks > 0, String(blinks));

  /* The fidget pick is random, so drive the tilt / squash / hop branches directly: a ~20s
     window that happens to draw blink twice is a legitimate miss, not a bug. */
  const rand = Math.random, saw = { tilt: 0, squash: 0, hop: 0 }, f = mk({ species: "mochi" });
  for (const r of [0.40, 0.65, 0.95]) {
    f._behaveAt = 1e9;                                   // keep tick from picking its own
    Math.random = () => r; f._idleBehavior(); Math.random = rand;
    for (let i = 0; i < 80; i++) {
      f.tick(0.016);
      if (Math.abs(f.tilt) > 0.02) saw.tilt++;
      if (f.sy < 0.97 || f.sy > 1.03) saw.squash++;
      if (f.oy < -4) saw.hop++;
    }
  }
  ok("an idle bot fidgets (tilt / squash / hop)",
     saw.tilt > 0 && saw.squash > 0 && saw.hop > 0, JSON.stringify(saw));
  ok("the fidgets are occasional, not constant",
     saw.tilt + saw.squash + saw.hop < 3 * 80 * 0.5, String(saw.tilt + saw.squash + saw.hop));
}

console.log("\n-- colour grading --");
{
  /* Coucou paints a small bot as one flat fill of its colour; only the big mascot gets the
     gradient body, state tint, shadow rim and white highlight. `flat` is how a sidebar face
     asks for the small-bot treatment, so record every fill and gradient and check both. */
  const recCtx = (log) => {
    const store = {};
    return new Proxy(store, {
      get(t, k) {
        if (k in t) return t[k];
        if (k === "createLinearGradient") return () => { const g = { addColorStop() {}, grad: "lin" }; return g; };
        if (k === "createRadialGradient") return () => { const g = { addColorStop() {}, grad: "rad" }; return g; };
        return () => {};
      },
      set(t, k, v) { t[k] = v; if (k === "fillStyle" || k === "strokeStyle") log.push(typeof v === "object" && v ? v.grad : v); return true; },
    });
  };
  const recCanvas = (log) => ({ width: 0, height: 0, clientWidth: 46, clientHeight: 46,
    getContext: () => recCtx(log), getBoundingClientRect: () => ({ left: 0, top: 0, width: 46, height: 46 }) });

  const FLAT = "#7C5CFF";
  const flatLog = [];
  const fb = new MochiBot(recCanvas(flatLog), "idle", { species: "mochi", size: 46, flat: FLAT });
  for (let i = 0; i < 3; i++) { fb.tick(0.05); fb.draw(); }
  ok("a flat face fills its body with exactly its colour", flatLog.includes(FLAT), JSON.stringify(flatLog.slice(0, 6)));
  ok("a flat face draws no gradient at all (Coucou's mini-bot body)",
     flatLog.every(v => v !== "lin" && v !== "rad"), JSON.stringify(flatLog.slice(0, 8)));
  ok("a flat colour also backs the parts that used the body shades",
     fb.bodyTop === FLAT && fb.bodyBottom === FLAT, fb.bodyTop + "/" + fb.bodyBottom);

  const softLog = [];
  const sb = new MochiBot(recCanvas(softLog), "idle", { species: "mochi", size: 160 });
  for (let i = 0; i < 3; i++) { sb.tick(0.05); sb.draw(); }
  ok("a big mascot keeps its gradient body", softLog.includes("lin") && softLog.includes("rad"),
     JSON.stringify(softLog.slice(0, 8)));

  /* skin() is how a face is recoloured after the fact (Settings → Bots changes a colour live). */
  const rb = mk({ species: "mochi" });
  rb.skin("mochi", { flat: FLAT });
  ok("skin() takes a flat colour", rb.flat === FLAT, String(rb.flat));
  rb.skin("mochi", { bodyTop: "#111", bodyBottom: "#222" });
  ok("skin() without a flat colour clears the flat fill", rb.flat === null && rb.bodyTop === "#111",
     rb.flat + "/" + rb.bodyTop);

  /* No cheek blush. The pink was drawn over the body for every emotion and every state tint, so
     the only way to be sure it is gone is to look at what actually got filled — a leftover
     `blush` key would otherwise come back as a NaN alpha that silently draws nothing. */
  const cheekLog = [];
  const cb = new MochiBot(recCanvas(cheekLog), "idle", { species: "mochi", size: 160 });
  for (const st of Object.keys(STATES)) { cb.setState(st); for (const emo of Object.keys(EMOTIONS)) {
    cb.setEmotion(emo); cb.tint = 1; cb.draw(); } }
  ok("no cheek blush is painted, at any emotion or state",
     !cheekLog.some(v => typeof v === "string" && /^#FF8FB1$/i.test(v)), JSON.stringify(cheekLog.filter(v => v).slice(0, 8)));

  /* ---- what the bot is wearing ---- */
  /* Every garment has to actually put something on the canvas, and a key this build does not know
     has to be ignored rather than drawn as a half-garment or thrown on. The ink is excluded from
     the "did it paint" count because the eyes and mouth are always drawn in it. */
  const inkish = v => typeof v === "string" && v.startsWith("#") && v !== "#1A1412";
  const wears = (opts) => {
    const log = [];
    const b = new MochiBot(recCanvas(log), "idle", { species: "mochi", size: 160, ...opts });
    b.tick(0.05); b.draw();
    return log;
  };
  ok("there are garments to choose from",
     Object.keys(OUTFITS).length >= 4 && Object.keys(ACCESSORIES).length >= 6,
     Object.keys(OUTFITS).length + "/" + Object.keys(ACCESSORIES).length);
  for (const k of Object.keys(OUTFITS))
    ok("outfit " + k + " paints something", wears({ outfit: k }).some(inkish));
  for (const k of Object.keys(ACCESSORIES))
    ok("accessory " + k + " paints something", wears({ accessory: k }).some(inkish));
  ok("an outfit this build does not know is ignored, not drawn",
     mk({ outfit: "tutu" }).outfit === "" &&
     wears({ outfit: "tutu" }).join() === wears({}).join());
  ok("an accessory this build does not know is ignored, not drawn",
     mk({ accessory: "monocle" }).accessory === "" &&
     wears({ accessory: "monocle" }).join() === wears({}).join());
  /* The eye row is not the same height on every species — a frog's eyes sit on top of its head — so
     the glasses are anchored to it rather than to a fixed y. Two species whose eyes differ in height
     must therefore put the frames at different heights; a fixed offset would put them both in the
     same place and land the frog's lenses on its mouth. */
  const ringY = sp => {
    const log = [];
    const ctx = new Proxy({}, {
      get(t, k) {
        if (k in t) return t[k];
        if (k === "arc") return (x, y) => log.push(y);
        if (k === "createLinearGradient" || k === "createRadialGradient") return () => ({ addColorStop() {} });
        return () => {};
      },
      set(t, k, v) { t[k] = v; return true; },
    });
    const cv = { width: 0, height: 0, clientWidth: 160, clientHeight: 160, getContext: () => ctx,
                 getBoundingClientRect: () => ({ left: 0, top: 0, width: 160, height: 160 }) };
    const b = new MochiBot(cv, "idle", { species: sp, size: 160, accessory: "glasses" });
    b.tick(0.05); b.draw();
    return log.length ? Math.min(...log) : 0;      // the topmost arc is the frame's
  };
  ok("glasses sit on the species' own eye row, not at a fixed height",
     ringY("frog") < ringY("mochi") - 5, ringY("frog") + " vs " + ringY("mochi"));
  ok("every species can wear an outfit and an accessory and still show its face",
     Object.keys(SPECIES).every(sp => wears({ species: sp, outfit: "scarf", accessory: "beanie" }).includes("#1A1412")));
  /* ---- an uploaded avatar becomes the body ---- */
  ok("no avatar URL means no texture", textureFor("") === null);
  ok("an avatar URL is remembered on the bot", mk({ image: "/api/avatar/x?v=1" }).image === "/api/avatar/x?v=1");
  ok("skin() re-dresses a live bot",
     (() => { const b = mk({}); b.skin("mochi", null, { outfit: "tie", accessory: "crown", image: "u" });
       return b.outfit === "tie" && b.accessory === "crown" && b.image === "u"; })());
  ok("skin() with no look keeps what the bot is wearing",
     (() => { const b = mk({ outfit: "tie", accessory: "crown" }); b.skin("cat", { flat: FLAT });
       return b.outfit === "tie" && b.accessory === "crown"; })());
}

console.log("\n" + pass + " passed, " + fail + " failed\n");
process.exit(fail ? 1 : 0);
