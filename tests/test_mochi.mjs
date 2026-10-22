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

/* A video element as far as the engine is concerned: no decoder, so `readyState` is the switch
   between "the preset frame stands in" and "the clip draws", and listeners are fired by hand. */
const videos = [];
const fakeVideo = () => {
  const el = { videoWidth: 512, videoHeight: 512, readyState: 0, paused: true, loop: true,
    muted: false, playsInline: false, preload: "", currentTime: 0, src: "", _l: {},
    addEventListener(t, f) { (this._l[t] || (this._l[t] = [])).push(f); },
    setAttribute() {},
    play() { this.paused = false; return Promise.resolve(); },
    pause() { this.paused = true; },
    fire(t) { for (const f of this._l[t] || []) f({ target: this }); } };
  videos.push(el);
  return el;
};

globalThis.window = { devicePixelRatio: 2, addEventListener() {} };

const { speciesFor, SPECIES, EMOTIONS, STATES, Ease, MochiBot, eyeFrame, softLimit, OUTFITS, ACCESSORIES, textureFor, presetFrame, presetTextureFor, PRESET_FRAMES } = await import("../mochi.js");

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
  ok("a first poke is the jolt", b._pokeFrame === "p1", b._pokeFrame);
  let threw = null; try { run(b, 30); } catch (e) { threw = e.message; }
  ok("the poke animation plays out", !threw, threw || "");

  /* Poke it a few times in a row and it stops being charmed by it. Three visible steps, not one:
     the frame set ships the jolt and the arms-crossed glare, and `e-annoyed` is the step between. */
  const c = mk();
  c.poke(); c.t += 0.6;
  const hearts = c.parts.length;
  c.poke();
  ok("a second poke in a row is irritated", c._pokeFrame === "e-annoyed", c._pokeFrame);
  ok("an irritated poke throws no hearts", c.parts.length === hearts, String(c.parts.length));
  c.t += 0.6; c.poke();
  ok("a third poke in a row is the exasperated frame", c._pokeFrame === "p2", c._pokeFrame);
  ok("an annoyed bot is angry, not excited", c.emotion === "angry", c.emotion);
  c.t += 0.6; c.poke();
  ok("a fourth poke stays at the exasperated frame", c._pokeFrame === "p2", c._pokeFrame);

  const d = mk();
  d.poke(); d.t += 6; d.poke();
  ok("the count lapses, so a poke much later is a jolt again", d._pokeFrame === "p1", d._pokeFrame);
}

console.log("\n-- a poke's feeling wears off --");
{
  /* The poke sets its own emotion, and the idle mood drift that would take it back only runs in
     `idle` — so a bot poked while working stayed excited for the rest of the turn. */
  const b = mk({ state: "working" });
  b.poke();
  ok("a poke overrides the state's feeling", b.emotion === "excited", b.emotion);
  run(b, 40);
  ok("...and the state's feeling comes back when the poke fades", b.emotion === "focused", b.emotion);
  const c = mk({ state: "thinking" });
  c.poke(); c.t += 0.5; c.poke();
  ok("an annoyed poke is angry", c.emotion === "angry", c.emotion);
  run(c, 60);
  ok("...and wears off to the state's feeling", c.emotion === "curious", c.emotion);
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

console.log("\n-- a face is a portrait, not a body --");
{
  /* The picture must never be translated by the idle motion: moving a photograph up and down is a
     bounce, not a breath. Breathing is a slow vertical scale — and it stays under 2%, so it reads as
     a chest rising rather than the head inflating. */
  for (const opts of [{ preset: "woman" }, { preset: "cat", species: "bunny" }]) {
    const b = mk(opts);
    let maxOy = 0, maxOx = 0, minSy = 1, maxSy = 1;
    for (let i = 0; i < 400; i++) {
      b.tick(0.05);
      maxOy = Math.max(maxOy, Math.abs(b.oy)); maxOx = Math.max(maxOx, Math.abs(b.ox));
      minSy = Math.min(minSy, b.sy); maxSy = Math.max(maxSy, b.sy);
    }
    const tag = opts.species ? ` (${opts.species}, a hopping species)` : "";
    ok("a face never translates on its own" + tag, maxOy < 1e-6 && maxOx < 1e-6,
       `oy:${maxOy} ox:${maxOx}`);
    ok("a face breathes gently" + tag, minSy < 0.995 && maxSy > 1.005 && maxSy - minSy < 0.03,
       `sy:${minSy.toFixed(4)}..${maxSy.toFixed(4)}`);
  }
  /* Breathing is one cycle in 4-6 seconds. Faster than that is a pulse. */
  const b = mk({ preset: "woman" });
  let crossings = 0, prev = null;
  for (let i = 0; i < 300; i++) {
    b.tick(0.05);
    const d = b.sy - 1;
    if (prev !== null && Math.sign(d) !== Math.sign(prev) && Math.abs(d) > 1e-4) crossings++;
    prev = d;
  }
  ok("a breath takes 4-6s", crossings >= 4 && crossings <= 7, String(crossings) + " turns in 15s");
  /* `approval` and `finished` bounce and roll a body on purpose. A face must sit still through
     both — its own frame is the beat. The bot starts idle and is moved, because a bot constructed
     already in the state skips the transition and would prove nothing. */
  for (const st of ["approval", "finished"]) {
    const a = mk({ preset: "woman" });
    for (let i = 0; i < 10; i++) a.tick(0.02);         // settle the idle motion first
    a.setState(st);
    let maxOy = 0, maxOx = 0;
    for (let i = 0; i < 200; i++) { a.tick(0.02); maxOy = Math.max(maxOy, Math.abs(a.oy)); maxOx = Math.max(maxOx, Math.abs(a.ox)); }
    ok(`a face does not lunge on ${st}`, maxOy < 1e-6 && maxOx < 1e-6, `oy:${maxOy} ox:${maxOx}`);
  }
  /* A dizzy head wobbles — that is a head movement, not a translated picture. */
  {
    const a = mk({ preset: "woman" });
    a.setState("dizzy");
    let maxTilt = 0;
    for (let i = 0; i < 120; i++) { a.tick(0.02); maxTilt = Math.max(maxTilt, Math.abs(a.tilt)); }
    ok("a dizzy face wobbles its head instead of rolling", maxTilt > 0.05 && Math.abs(a.roll) < 1e-6,
       `tilt:${maxTilt.toFixed(3)} roll:${a.roll}`);
  }
  /* A poke is the one interaction the user starts, and it must not break the portrait rule either:
     the picture recoils by tilting, never by leaving its shoulders. */
  for (const [label, pokes] of [["a jolt", 1], ["an annoyed shake", 3]]) {
    const a = mk({ preset: "woman" });
    let maxOy = 0, maxTilt = 0;
    for (let i = 0; i < pokes; i++) { a.poke(); a.t += 0.5; }
    for (let i = 0; i < 120; i++) { a.tick(0.02); maxOy = Math.max(maxOy, Math.abs(a.oy)); maxTilt = Math.max(maxTilt, Math.abs(a.tilt)); }
    ok(`a poked face ${label} tilts and never leaves the ground`, maxOy < 1e-6 && maxTilt > 0.02,
       `oy:${maxOy} tilt:${maxTilt.toFixed(3)}`);
  }
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
  const recCtx = (log, imgs) => {
    const store = {};
    return new Proxy(store, {
      get(t, k) {
        if (k in t) return t[k];
        if (k === "createLinearGradient") return () => { const g = { addColorStop() {}, grad: "lin" }; return g; };
        if (k === "createRadialGradient") return () => { const g = { addColorStop() {}, grad: "rad" }; return g; };
        if (k === "drawImage") return (cv, x, y, w, h) => {
          log.push("img");
          if (imgs) imgs.push({ a: store.globalAlpha == null ? 1 : store.globalAlpha, x, y, w, h });
        };
        return () => {};
      },
      set(t, k, v) { t[k] = v; if (k === "fillStyle" || k === "strokeStyle") log.push(typeof v === "object" && v ? v.grad : v); return true; },
    });
  };
  const recCanvas = (log, imgs) => ({ width: 0, height: 0, clientWidth: 46, clientHeight: 46,
    getContext: () => recCtx(log, imgs), getBoundingClientRect: () => ({ left: 0, top: 0, width: 46, height: 46 }) });

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
  /* ---- an introduced picture is the bot's face ----
     The user introduces an image, the image model redraws it as a face, and it is drawn where the
     eyes and mouth would be — not as the body with the drawn face on top, which is two faces. The
     picture has to decode before there is a canvas to draw, so a minimal document/Image pair stands
     in for the browser's; without one `textureFor` would stay on its "no canvas" path. */
  ok("no picture means no texture", textureFor("") === null);
  ok("a picture URL is remembered on the bot", mk({ image: "/api/avatar/x?v=1" }).image === "/api/avatar/x?v=1");
  const realDoc = globalThis.document, realImg = globalThis.Image;
  globalThis.Image = class { set src(u) { this.onload && this.onload(); } get width() { return 4; } get height() { return 4; } };
  globalThis.document = { createElement: () => ({ width: 0, height: 0, getContext: () => ({
    drawImage() {}, putImageData() {},
    getImageData: () => ({ data: new Uint8ClampedArray(256 * 256 * 4).fill(255) }),
  }) }) };
  const pic = "/api/avatar/face-test?v=1";
  ok("a picture decodes into a texture", !!(textureFor(pic) || {}).cv);
  /* In the desktop app the page is loaded from disk, so `/api/…` is not an address an <img> can
     reach — the picture has to come through the app's own channel (`window.anzen`). Setting `src`
     straight to the URL is what made every face silently fall back to the plain drawn bot inside
     the app while looking perfect in a browser. */
  const realFetch = globalThis.fetch, realCreate = URL.createObjectURL, realRevoke = URL.revokeObjectURL;
  globalThis.window.anzen = {};
  const fetched = [];
  globalThis.fetch = u => { fetched.push(u); return Promise.resolve({ blob: () => Promise.resolve({}) }); };
  URL.createObjectURL = () => "blob:app-face";
  URL.revokeObjectURL = () => {};
  const appPic = "/api/face/f-app-1.png";
  const appRec = textureFor(appPic);
  await new Promise(r => setTimeout(r, 0));
  ok("inside the app a picture is fetched over its own channel, not set on img.src",
     fetched.includes(appPic), JSON.stringify(fetched));
  ok("...and it decodes from that blob", !!appRec.cv);
  delete globalThis.window.anzen;
  globalThis.fetch = realFetch; URL.createObjectURL = realCreate; URL.revokeObjectURL = realRevoke;
  const INK = "#1A1412";                               // the eyes and mouth are drawn in exactly this
  const withPic = wears({ image: pic, outfit: "scarf", accessory: "crown" });
  ok("a face picture is painted", withPic.includes("img"), JSON.stringify(withPic.slice(0, 10)));
  /* The drawing is the face, not the body: nothing of the engine's own character may show behind it —
     no silhouette, ears, outfit, accessory or drawn eyes. */
  ok("a face picture is drawn alone: no body, ears or drawn face under it",
     !withPic.includes(INK) && !withPic.includes("#EDEDEF") && !withPic.includes("#C4C5CA"),
     JSON.stringify(withPic.slice(0, 10)));
  ok("nothing is dressed on a face picture", !withPic.some(inkish), JSON.stringify(withPic.slice(0, 8)));
  /* A picture fills the box, so the props drawn round a body — thought bubble, magnifier, hand,
     desk — would land on the photo. The desk is the only thing on that path that builds a gradient. */
  const picLog = st => {
    const log = [];
    const b = new MochiBot(recCanvas(log), st, { species: "mochi", size: 160, image: pic });
    b.tick(0.05); b.draw();
    return log;
  };
  ok("a picture gets no scene props over it",
     ["thinking", "searching", "approval", "working"].every(st =>
       !picLog(st).some(v => v === "#EDEDF2" || v === "lin" || v === "rad")),
     JSON.stringify(picLog("thinking").slice(0, 10)));
  ok("a drawn bot still gets its props",
     (() => { const log = [];
       const b = new MochiBot(recCanvas(log), "thinking", { species: "mochi", size: 160 });
       b.tick(0.05); b.draw(); return log.includes("#EDEDF2"); })());
  ok("without a picture the bot still draws its own face", wears({}).includes(INK));
  /* ---- the blink is a second drawing, cross-faded over the first ----
     The engine's `open` channel drives the fade, so a blink lands on the same frame the drawn eyes
     would. A picture with no second drawing simply does not blink — squashing it to fake one read as
     the whole head being pressed. */
  const shutPic = "/api/avatar/face-test-closed?v=1";
  ok("a shut-eye picture URL is remembered on the bot", mk({ imageClosed: shutPic }).imageClosed === shutPic);
  ok("a shut-eye frame decodes into a texture", !!(textureFor(shutPic) || {}).cv);
  const blinkLog = [], blinkImgs = [];
  const bb = new MochiBot(recCanvas(blinkLog, blinkImgs), "idle", { species: "mochi", size: 160,
    image: pic, imageClosed: shutPic });
  bb.open = 1; bb.draw();
  const openFrames = blinkImgs.length;
  bb.open = 0.06; bb.draw();
  ok("a picture with a shut-eye frame cross-fades to it when the eyes close",
     openFrames === 1 && blinkImgs.length === 3 && blinkImgs[2].a > 0.9, JSON.stringify(blinkImgs));
  const plainImgs = [];
  const pb = new MochiBot(recCanvas([], plainImgs), "idle", { species: "mochi", size: 160, image: pic });
  pb.open = 1; pb.draw();
  const tall = plainImgs[0].h;
  pb.open = 0.06; pb.draw();
  ok("a picture with no shut-eye frame is not squashed to fake a blink",
     plainImgs.length === 2 && Math.abs(plainImgs[1].h - tall) < 0.01, JSON.stringify(plainImgs));
  /* ---- the backdrop is keyed from the edge inwards ----
     A cream cat on a white backdrop is still a cat. The key used to remove every pixel close to the
     corner colour, which ate the subject: this photo is a cream disc inside a dark outline on pure
     white, and the disc has to survive while the corner goes. */
  const N = 256, px = new Uint8ClampedArray(N * N * 4);
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
    const i = (y * N + x) * 4, d = Math.hypot(x - 128, y - 128);
    const col = d < 70 ? [245, 239, 228] : d < 76 ? [26, 20, 18] : [255, 255, 255];
    px[i] = col[0]; px[i + 1] = col[1]; px[i + 2] = col[2]; px[i + 3] = 255;
  }
  const alphaAt = (x, y) => px[(y * N + x) * 4 + 3];
  globalThis.document = { createElement: () => ({ width: 0, height: 0, getContext: () => ({
    drawImage() {}, putImageData() {},
    getImageData: () => ({ data: px }),                  // the same buffer the key writes into
  }) }) };
  textureFor("/api/face/cream-cat.png");
  ok("the backdrop around a pale subject is removed", alphaAt(2, 2) === 0 && alphaAt(250, 6) === 0);
  ok("a pale subject inside its own outline survives the key", alphaAt(128, 128) === 255);
  globalThis.document = realDoc; globalThis.Image = realImg;
  ok("skin() re-dresses a live bot",
     (() => { const b = mk({}); b.skin("mochi", null, { outfit: "tie", accessory: "crown", image: "u", imageClosed: "v" });
       return b.outfit === "tie" && b.accessory === "crown" && b.image === "u" && b.imageClosed === "v"; })());
  /* Switching to a room re-skins the dock with no look at all. Anything the last bot was wearing —
     and above all its preset — has to go, or the corner keeps showing a bot you are not talking to. */
  ok("skin() with no look strips the previous bot's face",
     (() => { const b = mk({ preset: "woman", outfit: "tie", accessory: "crown" });
       b.skin("mochi", null, null);
       return b.preset === "" && b.image === "" && b.imageClosed === "" &&
              b.outfit === "" && b.accessory === ""; })());
}

console.log("\n-- preset frame dissolve --");
{
  /* A preset is stills on a clock, so every swap used to be a cut. While `_fade` runs, the outgoing
     frame is drawn under the incoming one at complementary alpha; once it lands, one draw only. */
  const shot = () => {
    const imgs = [];
    const ctx = {
      a: 1, save() {}, restore() {},
      get globalAlpha() { return this.a; }, set globalAlpha(v) { this.a = v; },
      drawImage(cv) { imgs.push([cv, this.a]); },
    };
    return { ctx, imgs };
  };
  const b = mk({ preset: "cat" });
  const A = { width: 1024, height: 1024 }, B = { width: 1024, height: 1024 };
  b._facePrev = A; b._faceCur = B; b._fade = 0.5;
  let { ctx, imgs } = shot();
  b._facePic(ctx, B);
  ok("a dissolving frame draws the old one under the new",
     imgs.length === 2 && imgs[0][0] === A && imgs[0][1] === 0.5 && imgs[1][0] === B && imgs[1][1] === 0.5,
     JSON.stringify(imgs.map(i => i[1])));
  ({ ctx, imgs } = shot());
  b._fade = 1;
  b._facePic(ctx, B);
  ok("a settled frame draws once", imgs.length === 1 && imgs[0][0] === B);
  /* The fade is timed in seconds, not frames: at 60fps it lands in ~8 ticks, at 10fps in ~2. */
  b._fade = 0;
  for (let i = 0; i < 9; i++) b.tick(1 / 60);
  ok("the dissolve lands in about 0.14s", b._fade === 1, String(b._fade));
}

console.log("\n-- preset textures are sized to the canvas --");
{
  /* The size used to be rounded up to a power of two, so a 210px panel at 2x (420) and a 104px dock
     at 3x (312) both spent a 512 texture — a megabyte a frame, twenty-one frames a character. */
  const u = "/api/preset/sizer/base.webp";
  ok("a 2x 210px panel and a 3x 104px dock get their own textures",
     presetTextureFor(u, 420) !== presetTextureFor(u, 312));
  ok("the same size is decoded once", presetTextureFor(u, 420) === presetTextureFor(u, 420));
  ok("the size is capped, not rounded up", presetTextureFor(u, 512) === presetTextureFor(u, 900));
  ok("a preset frame still names a shipped frame",
     PRESET_FRAMES.includes(presetFrame("finished", 1, 0, 1)), presetFrame("finished", 1, 0, 1));
  /* No decoded frame (no document here) must fall back to the bot's drawn self, not an empty box. */
  const b = mk({ preset: "cat" });
  let threw = null; try { b.tick(0.05); b.draw(); } catch (e) { threw = e.message; }
  ok("a preset with no decoded frame still draws the bot", !threw && b._presetFace() === null, threw || "");
}

console.log("\n-- clips --");
{
  /* Muse's trick: a preset that also ships clips plays them, and keeps its frames wherever the clip
     set has nothing. The DOM here is a stub, so `readyState` is the only readiness signal. */
  const realDoc = globalThis.document, realImg = globalThis.Image;
  globalThis.document = {
    createElement: tag => tag === "video" ? fakeVideo() : { width: 0, height: 0, getContext: () => ({ drawImage() {} }) },
    addEventListener() {},
  };
  globalThis.Image = class { set src(u) { this.onload && this.onload(); } get width() { return 512; } get height() { return 512; } };
  const recCanvas = imgs => ({ width: 0, height: 0, clientWidth: 160, clientHeight: 160,
    getContext: () => new Proxy({}, {
      get(t, k) {
        if (k in t) return t[k];
        if (k === "drawImage") return (cv, x, y, w, h) => imgs.push({ cv, x, y, w, h });
        if (k === "createLinearGradient" || k === "createRadialGradient") return () => ({ addColorStop() {} });
        return () => {};
      },
      set(t, k, v) { t[k] = v; return true; },
    }),
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 160, height: 160 }) });

  /* With no clips the engine is exactly what it was: no video is made, nothing is drawn from one. */
  const made = videos.length;
  const none = mk({ preset: "cat" });
  run(none, 5);
  ok("with no clips the engine makes no video at all",
     videos.length === made && none._clipFace() === null && none._clipEl === null, String(videos.length - made));

  /* Which clip a state wears. */
  const CLIPS = { idle: "/api/clip/x/idle.webm", working: "/api/clip/x/working.webm",
                  celebrate: "/api/clip/x/milestone-confetti.webm" };
  const b = mk({ preset: "cat", clips: CLIPS });
  ok("idle plays the idle clip", b._clipUrl() === CLIPS.idle, b._clipUrl());
  b.setState("working");
  ok("a state with its own clip plays that one", b._clipUrl() === CLIPS.working, b._clipUrl());
  b.setState("bored");
  ok("a resting state with no clip borrows idle", b._clipUrl() === CLIPS.idle, b._clipUrl());
  b.setState("thinking");
  ok("a working state with no clip plays nothing, so its frames stay", b._clipUrl() === "", b._clipUrl());
  b.setState("idle");

  /* Not decoded, the frame stands in; decoded, the clip is the face. */
  b.tick(0.05);
  const vid = b._clipEl;
  ok("a clip that has not decoded is not drawn, but is on its way", !!vid && b._clipFace() === null);
  vid.readyState = 2;
  ok("a decoded clip is the face", b._clipFace() === vid);

  const imgs = [];
  const cb = new MochiBot(recCanvas(imgs), "idle", { preset: "cat", size: 160, clips: CLIPS });
  cb.tick(0.05);
  cb._clipEl.readyState = 2;
  imgs.length = 0;
  cb.draw();
  const frame = imgs.find(i => i.cv === cb._clipEl);
  ok("a clip is drawn in the preset frame's own box",
     !!frame && Math.abs(frame.w - 160 * 0.96) < 1e-9 && Math.abs(frame.h - 160 * 0.96) < 1e-9,
     JSON.stringify(imgs));
  ok("...and drawing does not pause it", cb._clipEl.paused === false);

  /* A clip that cannot load is dead for the session: no retry, no second request, no noise. */
  const dead = mk({ clips: { idle: "/api/clip/x/error.webm" } });
  dead.tick(0.05);
  const before = videos.length;
  dead._clipEl.fire("error");
  dead.tick(0.05); dead.draw(); dead.tick(0.05);
  ok("a clip that fails to load is marked dead", dead._vids.get("/api/clip/x/error.webm").dead === true);
  ok("...and is never requested again", videos.length === before && dead._clipFace() === null,
     videos.length + " vs " + before);

  /* One-shot milestones. */
  const p = mk({ preset: "cat", clips: CLIPS });
  const vids = videos.length;
  p.playOnce("nothing-shipped");
  ok("playOnce with no such clip is a silent no-op",
     p._onceUrl === "" && p._clipEl === null && videos.length === vids, p._onceUrl);
  p.tick(0.05);
  const idleVid = p._clipEl;
  idleVid.readyState = 2;
  p.playOnce("celebrate");
  const onceVid = p._onceEl;
  ok("playOnce plays its clip once", !!onceVid && onceVid !== idleVid && onceVid.loop === false &&
     p._clipUrl() === CLIPS.celebrate, String(onceVid && onceVid.loop));
  ok("...over the state's clip, paused underneath", idleVid.paused === true);
  onceVid.readyState = 2;
  ok("...and the one-shot is what the face draws", p._clipFace() === onceVid);
  onceVid.fire("ended");
  ok("...then hands back to the state", p._onceUrl === "" && p._clipUrl() === CLIPS.idle &&
     onceVid.loop === true && idleVid.paused === false && p._clipFace() === idleVid);

  /* Cost: nothing decodes for a face nobody draws or a tab nobody sees. */
  p._pauseClip();
  ok("a culled face pauses its clip", idleVid.paused === true);
  p.tick(0.05);
  ok("...and the next tick resumes it", idleVid.paused === false);
  p._hidden = true; p._syncClip();
  ok("a hidden tab pauses the clip", idleVid.paused === true);
  p._hidden = false; p._syncClip();
  ok("...and showing the tab again resumes it", idleVid.paused === false);

  /* A re-skin swaps the clip set with the face; a re-skin with none clears it. */
  p.skin("mochi", null, { preset: "cat" });
  ok("a re-skin with no clips clears the set and drops the videos",
     Object.keys(p.clips).length === 0 && p._clipEl === null && p._vids.size === 0 && idleVid.paused === true);
  /* The same set again is not a change: the dock is re-skinned on every redraw, and rebuilding the
     videos there restarted the clip each time the sidebar repainted. */
  p.skin("mochi", null, { preset: "cat" }, CLIPS);
  p.tick(0.05);
  const kept = p._clipEl; kept.readyState = 2; kept.paused = false;
  p.skin("mochi", null, { preset: "cat" }, CLIPS);
  ok("a re-skin with the same clips keeps the video running",
     p._clipEl === kept && kept.paused === false && p._vids.size === 1,
     String(p._clipEl === kept) + " " + kept.paused + " " + p._vids.size);

  globalThis.document = realDoc; globalThis.Image = realImg;
}

console.log("\n-- the silhouette is traced once --");
{
  /* Path2D is not in Node, so the engine runs its fallback tracer here. Stub one to check that the
     cached path is the same silhouette the fallback traces, and that a still body traces it once. */
  const PATH = ["moveTo", "lineTo", "arc", "arcTo", "ellipse", "bezierCurveTo", "quadraticCurveTo", "closePath"];
  const recorder = () => {
    const log = [];
    const ctx = new Proxy({}, {
      get(t, k) {
        if (k in t) return t[k];
        if (PATH.includes(k)) return (...a) => log.push(k);
        if (k === "fill" || k === "clip") return () => log.push("mark");
        if (k === "createLinearGradient" || k === "createRadialGradient") return () => ({ addColorStop() {} });
        return () => {};
      },
      set(t, k, v) { t[k] = v; return true; },
    });
    const cv = { width: 0, height: 0, clientWidth: 160, clientHeight: 160, getContext: () => ctx,
                 getBoundingClientRect: () => ({ left: 0, top: 0, width: 160, height: 160 }) };
    return { log, cv };
  };
  const fallback = recorder();
  new MochiBot(fallback.cv, "idle", { species: "mochi", size: 160 }).draw();
  const oneTrace = fallback.log.slice(0, fallback.log.indexOf("mark"));   // up to the glow's fill
  ok("the fallback traces the silhouette into the context", oneTrace.length > 10, String(oneTrace.length));

  const realPath = globalThis.Path2D, made = [];
  globalThis.Path2D = class { constructor() { this.ops = []; made.push(this); } };
  for (const k of PATH) globalThis.Path2D.prototype[k] = function () { this.ops.push(k); };
  const cached = recorder();
  const b = new MochiBot(cached.cv, "idle", { species: "mochi", size: 160 });
  for (let i = 0; i < 3; i++) b.draw();
  ok("one Path2D is built for a still body's whole life", made.length === 1, String(made.length));
  ok("...carrying exactly the path the fallback traces",
     made[0].ops.join() === oneTrace.join(), made[0].ops.length + " vs " + oneTrace.length);
  /* The eyes and mouth still trace their own paths into the context; the body's squircle is the
     only thing in this draw that uses lineTo, so its absence means the body was never re-traced. */
  ok("...and the context never traces the body again", !cached.log.includes("lineTo"), cached.log.join());
  const blobRec = recorder();
  const blob = new MochiBot(blobRec.cv, "idle", { species: "blob", size: 160 });
  const beforeBlob = made.length;
  blob.draw(); blob.draw();
  ok("the blob's breathing outline is rebuilt, not cached",
     made.length - beforeBlob > 2, String(made.length - beforeBlob));
  globalThis.Path2D = realPath;
  const plain = recorder();
  let threw = null;
  try { new MochiBot(plain.cv, "idle", { species: "mochi", size: 160 }).draw(); } catch (e) { threw = e.message; }
  ok("without Path2D the fallback still draws", !threw, threw || "");
}

console.log("\n-- body gradients are built once --");
{
  /* Four gradients a frame was the cost of every procedural repaint, for values that never move
     between frames. The key is size + colours + the state's glow, so only a re-skin rebuilds them. */
  let made = 0;
  const ctx = new Proxy({}, {
    get(t, k) {
      if (k in t) return t[k];
      if (k === "createLinearGradient" || k === "createRadialGradient")
        return () => { made++; return { addColorStop() {} }; };
      return () => {};
    },
    set(t, k, v) { t[k] = v; return true; },
  });
  const cv = { width: 0, height: 0, clientWidth: 160, clientHeight: 160,
    getContext: () => ctx, getBoundingClientRect: () => ({ left: 0, top: 0, width: 160, height: 160 }) };
  const b = new MochiBot(cv, "idle", { species: "mochi", size: 160 });
  b.draw();
  const first = made;                      // one build: body, tint, shade, highlight, desk
  for (let i = 0; i < 30; i++) b.draw();
  ok("a repainted body allocates no gradients after its first frame", made === first, first + " then " + made);
  b.setState("working");
  b.draw();
  ok("a state change rebuilds once, for the new glow", made === first * 2, first + " -> " + made);
  b.skin("mochi", { bodyTop: "#111111", bodyBottom: "#222222" }, null);
  b.draw(); b.draw();
  ok("a re-skin rebuilds once, then settles", made === first * 3, first + " -> " + made);
}

console.log("\n-- waiting on a teammate --");
{
  ok("the waiting state exists and says so",
     !!STATES.waiting && /teammate/.test(STATES.waiting.label), STATES.waiting && STATES.waiting.label);
  const b = mk();
  b.setState("waiting", true);
  const yaw = [];
  for (let i = 0; i < 60; i++) { b.tick(0.1); yaw.push(b._targetYaw); }
  /* Six seconds at 0.75 rad/s is most of one full sweep, so both sides have to be reached. */
  ok("waiting looks left and right", Math.max(...yaw) > 0.3 && Math.min(...yaw) < -0.3,
     Math.min(...yaw).toFixed(2) + ".." + Math.max(...yaw).toFixed(2));
  ok("...level, not up like thinking", Math.abs(b._targetPitch) < 0.1, String(b._targetPitch));
  /* A preset head is a picture: the gaze moves nothing, so waiting would look exactly like idle.
     The sweep is 0.9 rad/s, so a full period takes 7s — nine seconds covers both sides. */
  const p = mk({ preset: "cat" }); p.setState("waiting", true);
  const tilt = [];
  for (let i = 0; i < 90; i++) { p.tick(0.1); tilt.push(p.tilt); }
  ok("a preset waiting tilts its head instead", Math.max(...tilt) > 0.02 && Math.min(...tilt) < -0.02,
     Math.min(...tilt).toFixed(3) + ".." + Math.max(...tilt).toFixed(3));
  const idle = mk({ preset: "cat" }); const still = [];
  for (let i = 0; i < 40; i++) { idle.tick(0.1); still.push(Math.abs(idle.tilt)); }
  ok("...and an idle preset does not", Math.max(...still) < 0.005, String(Math.max(...still)));
}

console.log("\n-- a finish throws confetti --");
{
  const b = mk();
  b.setState("finished");
  const burst = b.parts.filter(p => p.b);
  ok("a finish throws a burst", burst.length >= 20, String(burst.length));
  ok("...in every direction, not one cone",
     new Set(burst.map(p => Math.sign(p.vx))).size === 2 && burst.some(p => p.vy > 0) && burst.some(p => p.vy < 0));
  for (let i = 0; i < 20; i++) b.tick(0.05);
  ok("...and it is gone inside a second", b.parts.filter(p => p.b).length === 0,
     String(b.parts.filter(p => p.b).length));
  /* A preset head fills its box and carries its own expression, so idle sparkles would land on its
     face. A burst is thrown outward from the head, so that one is drawn. */
  const counter = () => { let n = 0; const ctx = new Proxy({}, {
    get: (t, k) => k === "save" ? () => n++ : () => {}, set: () => true }); return { ctx, n: () => n }; };
  const p = mk({ preset: "cat" });
  p.parts = [{ k: "star", x: 0, y: 0, vy: 0, a: 1, s: 1 }];
  let c = counter(); p._parts(c.ctx, 0, 0);
  ok("a preset draws no idle sparkles over its face", c.n() === 0, String(c.n()));
  p.parts.push({ k: "star", b: 1, x: 0, y: 0, vx: 1, vy: 0, a: 1, s: 1 });
  c = counter(); p._parts(c.ctx, 0, 0);
  ok("...but the finish's burst is drawn round it", c.n() === 1, String(c.n()));
  /* The sidebar holds `finished` for 3.2s, so a second turn can finish inside that window and
     re-assert the same state. That is a second piece of news: another burst, another roll. */
  const again = mk();
  again.setState("finished");
  for (let i = 0; i < 20; i++) again.tick(0.05);         // the first burst has aged out
  const before = again.parts.filter(q => q.b).length;
  again.setState("finished");
  ok("a finish re-asserted inside the hold throws a second burst",
     before === 0 && again.parts.filter(q => q.b).length >= 20,
     before + " -> " + again.parts.filter(q => q.b).length);
  ok("...and rolls again", again.locks.has("roll"), [...again.locks].join(","));
}

console.log("\n-- reduced motion --");
{
  /* `ti` is frozen at 0 under reduced motion, and the blink window `ti % 3.7 < 0.22` is open at 0 —
     so a second copy of the module, imported with the query the media query answers, is what proves
     a working preset does not wear the blink frame for the whole turn. */
  globalThis.matchMedia = () => ({ matches: true });
  globalThis.document = { addEventListener() {}, createElement: () => fakeVideo() };
  const { presetFrame: reducedFrame, MochiBot: ReducedBot } = await import("../mochi.js?reduced");
  ok("a working preset is not stuck mid-blink when motion is reduced",
     reducedFrame("working", 0, 0, 1) !== "work-closed", reducedFrame("working", 0, 0, 1));
  ok("...and an ordinary one still blinks", presetFrame("working", 0, 0, 1) === "work-closed");
  /* A clip is motion, so reduced motion never plays one: not the state's, not a milestone. */
  const rv = videos.length;
  const rb = new ReducedBot(fakeCanvas(), "idle",
    { clips: { idle: "/api/clip/x/idle.webm", celebrate: "/api/clip/x/milestone-confetti.webm" } });
  rb.playOnce("celebrate");
  rb.tick(0.05);
  ok("reduced motion plays no clip at all",
     rb._onceUrl === "" && rb._clipEl === null && rb._clipFace() === null && videos.length === rv,
     rb._clipUrl());
  delete globalThis.matchMedia; delete globalThis.document;
}

console.log("\n" + pass + " passed, " + fail + " failed\n");
process.exit(fail ? 1 : 0);
