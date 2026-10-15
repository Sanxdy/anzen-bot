/* mochi.js — smooth 60fps canvas mascot engine.
   Port of Coucou's BotEngine.swift: continuous tweens/springs, NOT frame swaps.
   One MochiBot per <canvas>; a single rAF loop ticks every bot.

   Three layers, so a bot is a character and not a coloured blob:
     SPECIES  — the body shape, ears/antenna, eye style and idle motion. Each bot gets
                its own, derived from its id, so a team of bots looks like a team.
     EMOTION  — mouths, brows, blush and eye shape, blended smoothly. States set a
                default feeling; an idle bot wanders through its own.
     CURSOR   — every bot's eyes follow the pointer, from wherever it sits on screen.
   Plus the "scene" layer of props per state (desk, thought bubble, magnifier). */

const MC = { INK: "#1A1412" };
const lerp = (a, b, t) => a + (b - a) * t;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
/* Easing curves, ported 1:1 from Coucou's Ease enum. A discrete motion is a list of
   [target, durationMs, ease] keyframes; `back` is the one that overshoots and settles,
   which is most of why their bot reads as animated rather than interpolated. */
export const Ease = {  out:   t => 1 - Math.pow(1 - t, 3),
  inOut: t => t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2,
  back:  t => { const c1 = 1.7, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2); },
  lin:   t => t,
};

/* ---------------- species: one per bot, so faces differ ---------------- */
export const SPECIES = {
  mochi: { label: "Mochi",  body: "squircle", ears: "none",   eyes: "pill",   idle: "bob" },
  cat:   { label: "Cat",    body: "squircle", ears: "cat",    eyes: "pill",   idle: "sway" },
  bunny: { label: "Bunny",  body: "egg",      ears: "bunny",  eyes: "pill",   idle: "hop" },
  owl:   { label: "Owl",    body: "round",    ears: "tufts",  eyes: "bulge",  idle: "sway" },
  frog:  { label: "Frog",   body: "frog",     ears: "none",   eyes: "bulge",  idle: "hop" },
  ghost: { label: "Ghost",  body: "ghost",    ears: "none",   eyes: "pill",   idle: "float" },
  robot: { label: "Robot",  body: "robot",    ears: "none",   eyes: "screen", idle: "jitter", antenna: "stub" },
  alien: { label: "Alien",  body: "dome",     ears: "none",   eyes: "wide",   idle: "float",  antenna: "ball" },
  imp:   { label: "Imp",    body: "squircle", ears: "horns",  eyes: "wide",   idle: "jiggle" },
  bean:  { label: "Bean",   body: "bean",     ears: "none",   eyes: "pill",   idle: "breathe" },
  blob:  { label: "Blob",   body: "blob",     ears: "none",   eyes: "pill",   idle: "wobble" },
  star:  { label: "Star",   body: "star",     ears: "none",   eyes: "pill",   idle: "spin" },
};
const SPECIES_KEYS = Object.keys(SPECIES);
/* A bot's face is stable across reloads: it comes from its id, not from chance.
   The salt is tuned so the five default bots land on five different species. */
export function speciesFor(seed) {
  const s = String(seed == null ? "" : seed);
  let h = (2166136261 ^ 9) >>> 0;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
  h ^= h >>> 15; h = Math.imul(h, 2246822507) >>> 0;
  h ^= h >>> 13; h = Math.imul(h, 3266489909) >>> 0; h ^= h >>> 16;
  return SPECIES_KEYS[(h >>> 0) % SPECIES_KEYS.length];
}
const EYE = {
  pill:   { w: 0.25, h: 0.30, y: -0.16, sp: 0.36 },
  wide:   { w: 0.26, h: 0.32, y: -0.16, sp: 0.37 },
  screen: { w: 0.31, h: 0.11, y: -0.16, sp: 0.30 },
  bulge:  { w: 0.25, h: 0.25, y: -0.62, sp: 0.40 },
};

/* ---------------- emotions: the face a bot is wearing ---------------- */
/* smile -1..1 · open 0..1 (mouth aperture) · brow -1..1 (up is positive) ·
   blush 0..1 · eye 0..1.4 (eye height) · wave 0..1 (mouth squiggle) */
export const EMOTIONS = {
  calm:     { label: "calm",     smile:  0.35, open: 0.00, brow:  0.00, blush: 0.05, eye: 1.00, wave: 0 },
  happy:    { label: "happy",    smile:  0.95, open: 0.32, brow:  0.10, blush: 0.40, eye: 0.62, wave: 0 },
  curious:  { label: "curious",  smile:  0.20, open: 0.55, brow:  0.35, blush: 0.05, eye: 1.18, wave: 0 },
  excited:  { label: "excited",  smile:  1.00, open: 0.45, brow:  0.55, blush: 0.35, eye: 1.30, wave: 0 },
  focused:  { label: "focused",  smile:  0.05, open: 0.00, brow: -0.45, blush: 0.00, eye: 0.86, wave: 0 },
  worried:  { label: "worried",  smile: -0.45, open: 0.00, brow:  0.75, blush: 0.10, eye: 0.92, wave: 0 },
  proud:    { label: "proud",    smile:  0.80, open: 0.10, brow: -0.10, blush: 0.30, eye: 0.62, wave: 0 },
  sleepy:   { label: "sleepy",   smile:  0.10, open: 0.25, brow:  0.10, blush: 0.10, eye: 0.00, wave: 0 },
  confused: { label: "confused", smile: -0.10, open: 0.00, brow:  0.45, blush: 0.05, eye: 1.05, wave: 1 },
  bored:    { label: "bored",    smile: -0.20, open: 0.00, brow:  0.15, blush: 0.00, eye: 0.75, wave: 0 },
  angry:    { label: "angry",    smile: -0.70, open: 0.20, brow: -0.95, blush: 0.15, eye: 0.78, wave: 0 },
};
const EMO_KEYS = ["smile", "open", "brow", "blush", "eye", "wave"];
/* What a bot idly feels when nothing is happening. Picked at random, held a few seconds. */
const IDLE_MOODS = ["calm", "calm", "curious", "happy", "bored", "sleepy"];

/* per-state config — colours, behaviour and the feeling that goes with it */
export const STATES = {
  idle:      { glow: "#C9CFD8", tint: 0,    badge: null,       bob: 1,     emotion: "calm",     label: "idle" },
  working:   { glow: "#3B9EFF", tint: 0.72, badge: "dots",     desk: 1,    emotion: "focused",  label: "working" },
  thinking:  { glow: "#8B5CF6", tint: 0.72, badge: null,       lookUp: 1,  bubble: 1, emotion: "curious", label: "thinking" },
  searching: { glow: "#6366F1", tint: 0.72, badge: null,       scan: 1,    mag: 1,   emotion: "curious", label: "searching" },
  approval:  { glow: "#F5A524", tint: 0.78, badge: "bang",     bounce: 1,  hand: 1,  emotion: "worried", label: "needs approval" },
  question:  { glow: "#22D3EE", tint: 0.75, badge: "question", bubble: 1,            emotion: "curious", label: "asking" },
  finished:  { glow: "#34D399", tint: 0.35, badge: "dot",      stars: 1,             emotion: "happy",   label: "finished" },
  error:     { glow: "#F4505E", tint: 0.78, badge: "dot",      shake: 1,             emotion: "worried", label: "error" },
  sleeping:  { glow: "#94A2B8", tint: 0.32, badge: null,       breathe: 1, zz: 1,     emotion: "sleepy",  label: "sleeping" },
  ratelimit: { glow: "#FB923C", tint: 0.72, badge: "dot",      sweat: 1,             emotion: "worried", label: "rate limited" },
  dizzy:     { glow: "#F472B6", tint: 0.70, badge: null,                             emotion: "confused", label: "dizzy" },
  bored:     { glow: "#C9CFD8", tint: 0.18, badge: null,       breathe: 1,           emotion: "bored",   label: "bored" },
};

/* ---------------- body shapes (each traces a path at the origin) ---------------- */
const SHAPES = {
  squircle(ctx, rx, ry) {
    const exp = 2 / 2.7, n = 64;
    ctx.beginPath();
    for (let i = 0; i <= n; i++) {
      const a = i / n * Math.PI * 2, ca = Math.cos(a), sa = Math.sin(a);
      const x = rx * (ca >= 0 ? Math.pow(ca, exp) : -Math.pow(-ca, exp));
      const y = ry * (sa >= 0 ? Math.pow(sa, exp) : -Math.pow(-sa, exp));
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }
    ctx.closePath();
  },
  round(ctx, rx, ry) { ctx.beginPath(); ctx.ellipse(0, 0, rx, ry, 0, 0, 7); ctx.closePath(); },
  frog(ctx, rx, ry) { ctx.beginPath(); ctx.ellipse(0, ry * 0.14, rx * 1.06, ry * 0.88, 0, 0, 7); ctx.closePath(); },
  egg(ctx, rx, ry) {
    ctx.beginPath(); ctx.moveTo(0, -ry);
    ctx.bezierCurveTo(rx * 0.74, -ry * 0.86, rx, -ry * 0.20, rx, ry * 0.18);
    ctx.bezierCurveTo(rx, ry * 0.82, rx * 0.58, ry, 0, ry);
    ctx.bezierCurveTo(-rx * 0.58, ry, -rx, ry * 0.82, -rx, ry * 0.18);
    ctx.bezierCurveTo(-rx, -ry * 0.20, -rx * 0.74, -ry * 0.86, 0, -ry);
    ctx.closePath();
  },
  dome(ctx, rx, ry) {
    ctx.beginPath(); ctx.moveTo(-rx, ry * 0.30);
    ctx.bezierCurveTo(-rx * 1.04, -ry * 1.12, rx * 1.04, -ry * 1.12, rx, ry * 0.30);
    ctx.bezierCurveTo(rx * 0.84, ry * 1.02, -rx * 0.84, ry * 1.02, -rx, ry * 0.30);
    ctx.closePath();
  },
  robot(ctx, rx, ry) { ctx.beginPath(); rr(ctx, -rx, -ry, rx * 2, ry * 2, Math.min(rx, ry) * 0.32); ctx.closePath(); },
  ghost(ctx, rx, ry) {
    const top = -ry * 0.52, bot = ry * 0.96;
    ctx.beginPath(); ctx.moveTo(-rx, bot); ctx.lineTo(-rx, top);
    ctx.arc(0, top, rx, Math.PI, 0);
    ctx.lineTo(rx, bot);
    const w = rx * 2 / 3;
    for (let i = 0; i < 3; i++) {
      const x0 = rx - i * w;
      ctx.quadraticCurveTo(x0 - w / 2, bot - ry * 0.36, x0 - w, bot);
    }
    ctx.closePath();
  },
  bean(ctx, rx, ry) {
    ctx.beginPath(); ctx.moveTo(0, -ry * 0.95);
    ctx.bezierCurveTo(rx * 1.06, -ry * 0.90, rx * 1.02, ry * 0.52, rx * 0.30, ry * 0.95);
    ctx.bezierCurveTo(-rx * 0.42, ry * 1.06, -rx * 1.02, ry * 0.48, -rx * 0.96, -ry * 0.30);
    ctx.bezierCurveTo(-rx * 0.92, -ry * 0.94, -rx * 0.50, -ry * 1.00, 0, -ry * 0.95);
    ctx.closePath();
  },
  star(ctx, rx, ry) {
    /* A five-point star covers well under half the ellipse it inscribes, so at the same rx/ry
       it reads as much smaller and lighter than the round species. Bulge the inner radius and
       swell the outline so its silhouette carries the same weight as the rest of the team. */
    const g = 1.08, ix = rx * g, iy = ry * g, pts = [];
    for (let i = 0; i < 10; i++) {
      const a = i * Math.PI / 5 - Math.PI / 2, r = i % 2 ? 0.60 : 1;
      pts.push([Math.cos(a) * ix * r, Math.sin(a) * iy * r]);
    }
    poly(ctx, pts, Math.min(ix, iy) * 0.17);
  },
  /* the blob breathes its outline — the least stiff body of the lot */
  blob(ctx, rx, ry, t) {
    const n = 48;
    ctx.beginPath();
    for (let i = 0; i <= n; i++) {
      const a = i / n * Math.PI * 2;
      const wob = 1 + 0.055 * Math.sin(a * 3 + t * 1.5) + 0.035 * Math.sin(a * 5 - t * 2.1);
      const x = Math.cos(a) * rx * wob, y = Math.sin(a) * ry * wob;
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }
    ctx.closePath();
  },
};

/* ---------------- cursor: every face follows the pointer ---------------- */
const POINTER = { x: 0, y: 0, on: false };
/* A rect is read once and reused until something that actually moves a face invalidates it (scroll,
   resize, attach). Reading it per pointermove forced a layout on every event. */
function invalidateRects() { for (const b of bots) b._rect = null; }
function applyPointer() {
  if (!POINTER.on) return;
  for (const b of bots) {
    const r = b._rect || (b._rect = b.cv.getBoundingClientRect());
    if (!r.width || !r.height) continue;
    /* divide by at least 160px so a small sidebar face tracks subtly instead of pinning */
    const span = Math.max(r.width, r.height, 160) * 0.9;
    b.lookAt((POINTER.x - (r.left + r.width / 2)) / span,
             (POINTER.y - (r.top + r.height / 2)) / span, true);
  }
}
function releasePointer() {
  POINTER.on = false;
  for (const b of bots) b.lookAt(0, 0, false);
}

export class MochiBot {
  constructor(canvas, state = "idle", opts = {}) {
    this.cv = canvas; this.ctx = canvas.getContext("2d");
    this.dpr = Math.min(window.devicePixelRatio || 1, 3);
    this.size = opts.size || canvas.clientWidth || 160;
    // Coucou paints a small bot as one flat fill of its colour; a big mascot gets the soft body.
    this.flat = opts.flat || null;
    this.bodyTop = opts.bodyTop || opts.flat || "#EDEDEF";
    this.bodyBottom = opts.bodyBottom || opts.flat || "#C4C5CA";
    this.species = SPECIES[opts.species] ? opts.species : speciesFor(opts.seed);
    this.sp = SPECIES[this.species];
    this.cv.width = this.size * this.dpr; this.cv.height = this.size * this.dpr;
    this.R = this.size * 0.326;                      // body radius; the unit every offset is quoted in
    this.yaw = 0; this.pitch = 0; this.tilt = 0; this.roll = 0; this.open = 1;
    this.sx = 1; this.sy = 1; this.oy = 0; this.ox = 0;
    this.tint = 0; this.badgeS = 0; this.glowA = 0; this.scanX = -1;
    this.es = 1;                                     // eye-scale channel: the "surprised pop"
    this.parts = []; this.t = 0; this.ti = 0;   // `ti` is the idle clock: `t`, unless reduced motion
    this._blinkAt = 1.5 + Math.random() * 2;
    this._lookAt = 2 + Math.random() * 3; this._look = { yaw: 0, pitch: 0 };
    this._cursor = null; this._cursorOn = false;
    /* accessory spring (ears, antenna): stiffness 60, damping 9 — same as Coucou's hat spring */
    this._prevYaw = 0; this._prevOy = 0;
    this._physDx = 0; this._physDy = 0; this._physVx = 0; this._physVy = 0;
    this._moodAt = 3 + Math.random() * 4; this._mood = "calm";
    this._behaveAt = 5 + Math.random() * 6;
    this.tw = {}; this.locks = new Set();            // keyframe tweens, keyed by property
    this.emo = {}; for (const k of EMO_KEYS) this.emo[k] = EMOTIONS.calm[k];
    this.setState(state, true);
  }
  /* ---- keyframe tweens (the Coucou anim() API) ---- */
  anim(key, keys, onDone) {
    this.tw[key] = { keys, i: 0, from: this._get(key), start: this.t * 1000, done: onDone || null };
    this.locks.add(key);
  }
  _get(key) {
    switch (key) {
      case "yaw": return this.yaw;       case "pitch": return this.pitch;
      case "roll": return this.roll;     case "tilt": return this.tilt;
      case "open": return this.open;     case "sx": return this.sx;
      case "sy": return this.sy;         case "oy": return this.oy;
      case "ox": return this.ox;         case "es": return this.es;
      default: return 0;
    }
  }
  _set(key, v) {
    switch (key) {
      case "yaw": this.yaw = v; break;       case "pitch": this.pitch = v; break;
      case "roll": this.roll = v; break;     case "tilt": this.tilt = v; break;
      case "open": this.open = v; break;     case "sx": this.sx = v; break;
      case "sy": this.sy = v; break;         case "oy": this.oy = v; break;
      case "ox": this.ox = v; break;         case "es": this.es = v; break;
      default: break;
    }
  }
  _stepTweens() {
    const now = this.t * 1000;
    for (const key of Object.keys(this.tw)) {
      const tw = this.tw[key], k = tw.keys[tw.i];
      const p = clamp((now - tw.start) / k[1], 0, 1);
      this._set(key, tw.from + (k[0] - tw.from) * k[2](p));
      if (p < 1) continue;
      tw.from = k[0]; tw.i++; tw.start = now;
      if (tw.i >= tw.keys.length) { delete this.tw[key]; this.locks.delete(key); if (tw.done) tw.done(); }
    }
  }
  /* Eyes shut and open: 70ms in, 130ms out. Crisp, not a triangle wave. */
  blink() {
    if (this.locks.has("open")) return;
    this.anim("open", [[0.06, 70, Ease.inOut], [1, 130, Ease.out]]);
  }
  /* Squash & stretch on landing — the single biggest "this thing is alive" tell. */
  squash() {
    this._physVy += 0.6;
    this.anim("sy", [[0.78, 70, Ease.out], [1.10, 130, Ease.out], [1, 170, Ease.inOut]]);
    this.anim("sx", [[1.16, 70, Ease.out], [0.95, 130, Ease.out], [1, 170, Ease.inOut]]);
  }
  doRoll(turns, ms) {
    this.roll = 0;
    this.anim("roll", [[Math.PI * 2 * turns, ms, Ease.inOut]], () => { this.roll = 0; this.squash(); });
  }
  /* A fidget for a bot with nothing to do, so a quiet face is never a still image. */
  _idleBehavior() {
    if (this.state !== "idle" && this.state !== "bored") return;
    if (this.locks.has("oy") || this.locks.has("yaw") || this.locks.has("tilt")) return;
    const R = this.R, r = Math.random();
    if (this.state === "bored") {
      if (r < 0.4) this.blink();
      else this.anim("yaw", [[0.40, 420, Ease.inOut], [-0.40, 700, Ease.inOut], [0, 460, Ease.inOut]]);
    } else if (r < 0.28) this.blink();
    else if (r < 0.54) this.anim("tilt", [[0.11, 260, Ease.out], [0.11, 520, Ease.lin], [0, 300, Ease.inOut]]);
    else if (r < 0.8) this.squash();
    else this.anim("oy", [[-0.16 * R, 150, Ease.out], [0.02 * R, 180, Ease.inOut], [0, 220, Ease.back]]);
  }
  setState(s, instant = false) {
    const prev = this.state;
    if (!STATES[s]) s = "idle";
    this.state = s; this.cfg = STATES[s];
    if (this.cfg.emotion) this.setEmotion(this.cfg.emotion);
    if (instant) { this.tint = this.cfg.tint; this.glowA = this.cfg.tint > 0 ? 1 : 0.5; return; }
    if (prev === s) return;
    const R = this.R;
    if ((prev === "sleeping" || prev === "bored") && s !== "sleeping" && s !== "bored")
      this.anim("sy", [[1.12, 500, Ease.inOut], [1, 500, Ease.inOut]]);   // stretch on waking
    switch (s) {
      case "finished": this.doRoll(1, 950); break;
      case "error": this.anim("ox", [[0.08 * R, 50, Ease.out], [-0.08 * R, 70, Ease.inOut],
                                     [0.05 * R, 70, Ease.inOut], [0, 90, Ease.out]]); break;
      case "approval": this.anim("oy", [[-0.2 * R, 150, Ease.out], [0, 300, Ease.back]]); break;
      case "dizzy": this.doRoll(2, 1300); break;
      case "question": this.blink();
        this.anim("es", [[1.25, 120, Ease.out], [1, 500, Ease.inOut]]); break;
      default: if (prev !== "idle" || s !== "idle") this.blink();
    }
  }
  /* Re-skin a live bot: same canvas, same motion mid-flight, a different species and colour.
     Pass no colours to fall back to the plain Mochi body. */
  skin(species, colors) {
    if (SPECIES[species]) { this.species = species; this.sp = SPECIES[species]; }
    this.flat = (colors && colors.flat) || null;
    this.bodyTop = (colors && colors.bodyTop) || (colors && colors.flat) || "#EDEDEF";
    this.bodyBottom = (colors && colors.bodyBottom) || (colors && colors.flat) || "#C4C5CA";
  }
  /* The feeling on top of the state. Idle bots drift through their own moods. */
  setEmotion(e) {
    if (!EMOTIONS[e]) return;
    this.emotion = e;
    this._mood = e; this._moodAt = 3 + Math.random() * 5;
  }
  poke() {
    this.squash();
    this.anim("oy", [[-0.34 * this.R, 120, Ease.out], [0.03 * this.R, 200, Ease.inOut], [0, 170, Ease.back]]);
    this.anim("yaw", [[(Math.random() < 0.5 ? -1 : 1) * 0.34, 130, Ease.out], [0, 320, Ease.inOut]]);
    this.setEmotion("excited");
    this.anim("es", [[1.18, 110, Ease.out], [1, 380, Ease.inOut]]);
    for (let i = 0; i < 3; i++)
      this.parts.push({ k: "heart", x: (Math.random() * 2 - 1) * 18, y: -14, vy: -26 - Math.random() * 16,
                        vx: (Math.random() * 2 - 1) * 10, a: 1, s: 0.6 + Math.random() * 0.5 });
  }
  /* look toward a normalised point (-1..1). cursor=true holds it there until released. */
  lookAt(nx, ny, cursor = false) {
    /* same gain as Coucou: yaw 0.62, pitch 0.50 of the normalised pointer */
    const yaw = clamp(nx, -1, 1) * 0.62, pitch = clamp(ny, -1, 1) * 0.5;
    if (cursor) { this._cursor = { yaw, pitch }; this._cursorOn = true; }
    else if (this._cursorOn) { this._cursorOn = false; this._lookAt = 1.2; }
    else { this._look = { yaw, pitch }; this._lookAt = 1.4; }
  }
  tick(dt) {
    this.t += dt;
    const ti = this.ti = REDUCED ? 0 : this.t;   // the idle clock: frozen, so nothing drifts, while `t` runs on
    const c = this.cfg, sp = this.sp, R = this.R;
    /* Two smoothing rates, straight from Coucou: the body settles in ~0.14s and the gaze
       in ~0.17s, so the eyes trail the body by a hair. One shared rate — which is what
       this did before — converged in ~0.24s and read as laggy rather than fluid. */
    const kLook = 1 - Math.pow(0.0025, dt);
    const kGen  = 1 - Math.pow(0.0008, dt);
    this._stepTweens();
    /* --- where to look: a bot absorbed in its state looks there and ignores the mouse —
       working faces its desk, thinking looks up, sleeping is asleep. The cursor is the
       idle fallback, not an override. */
    if (c.zz) { this._targetYaw = 0; this._targetPitch = 0.05; }
    else if (c.lookUp) { this._targetYaw = 0; this._targetPitch = -0.45; }
    else if (c.desk) { this._targetYaw = Math.sin(ti * 0.7) * 0.12; this._targetPitch = 0.12; }
    else if (REDUCED) { this._targetYaw = 0; this._targetPitch = 0; }   // no cursor-following
    else if (this._cursorOn && this._cursor) { this._targetYaw = this._cursor.yaw; this._targetPitch = this._cursor.pitch; }
    else {
      this._lookAt -= dt;
      if (this._lookAt <= 0) { this._lookAt = 2 + Math.random() * 3.5;
        this._look = { yaw: (Math.random() * 2 - 1) * 0.5, pitch: (Math.random() * 2 - 1) * 0.3 }; }
      this._targetYaw = this._look.yaw; this._targetPitch = this._look.pitch;
    }
    /* --- idle moods: a calm bot quietly changes how it feels --- */
    this._moodAt -= dt;
    if (this._moodAt <= 0 && this.state === "idle" && !REDUCED) {
      this._moodAt = 3 + Math.random() * 5;
      const pick = IDLE_MOODS[Math.floor(Math.random() * IDLE_MOODS.length)];
      if (pick !== this._mood) { this._mood = pick; this.emotion = pick; }
    }
    /* --- a fidget every few seconds, so a quiet face is never a still image --- */
    this._behaveAt -= dt;
    if (this._behaveAt <= 0) { this._behaveAt = 5 + Math.random() * 6; if (!REDUCED) this._idleBehavior(); }
    /* --- gaze --- */
    if (!this.locks.has("yaw"))   this.yaw   += (this._targetYaw   - this.yaw)   * kLook;
    if (!this.locks.has("pitch")) this.pitch += (this._targetPitch - this.pitch) * kLook;
    if (!this.locks.has("tilt"))  this.tilt  += ((c.shake ? Math.sin(ti * 34) * 0.06 : 0) - this.tilt) * kGen;
    /* --- the species' own idle motion, in body-radius units so it scales with the face --- */
    let oyT = 0, syT = 1, sxT = 1, oxT = 0;
    switch (sp.idle) {
      case "hop":     oyT = -Math.abs(Math.sin(ti * 2.6)) * R * 0.135; syT = 1 - Math.abs(Math.sin(ti * 2.6)) * 0.06; break;
      case "sway":    oxT = Math.sin(ti * 1.3) * R * 0.062; oyT = Math.sin(ti * 1.3) * R * 0.027; break;
      case "float":   oyT = Math.sin(ti * 1.05) * R * 0.096; break;
      case "jitter":  oxT = Math.sin(ti * 9) * R * 0.017; oyT = Math.sin(ti * 7.3) * R * 0.013; break;
      case "jiggle":  syT = 1 + Math.sin(ti * 4.4) * 0.045; sxT = 1 - Math.sin(ti * 4.4) * 0.035; break;
      case "wobble":  syT = 1 + Math.sin(ti * 2.1) * 0.055; sxT = 1 - Math.sin(ti * 2.1) * 0.045; break;
      case "breathe": syT = 1 + Math.sin(ti * 1.6) * 0.035; break;
      case "spin":    oyT = Math.sin(ti * 1.7) * R * 0.058; break;
      default:        oyT = Math.sin(ti * 1.5) * R * 0.042; break;                 // bob
    }
    if (c.bounce) oyT += -Math.abs(Math.sin(ti * 5.2)) * R * 0.172;
    else if (c.bob) oyT += Math.sin(ti * 1.5) * R * 0.027;
    else if (c.desk) oyT += Math.sin(ti * 2.2) * R * 0.023;
    if (c.breathe) syT += Math.sin(ti * 1.8) * 0.022;
    if (!this.locks.has("oy")) this.oy += (oyT - this.oy) * kGen;
    if (!this.locks.has("sy")) this.sy += (syT - this.sy) * kGen;
    if (!this.locks.has("sx")) this.sx += (sxT - this.sx) * kGen;
    if (!this.locks.has("ox")) this.ox += (oxT + (c.shake ? Math.sin(ti * 40) * R * 0.042 : 0) - this.ox) * kGen;
    if (!this.locks.has("es")) this.es += (1 - this.es) * kGen;
    /* --- accessory spring: ears and antenna lag and ring behind the body --- */
    const yawVel = (this.yaw - this._prevYaw) / Math.max(dt, 1e-3);
    const oyVel  = (this.oy  - this._prevOy)  / Math.max(dt, 1e-3) / R;    // in R units, like Coucou
    this._prevYaw = this.yaw; this._prevOy = this.oy;
    const tDx = clamp(-yawVel * 0.35 - this.tilt * 2, -1, 1);
    const tDy = clamp(oyVel * 0.50, -1, 1);
    const stiff = 60, damp = 9;
    this._physVx += (stiff * (tDx - this._physDx) - damp * this._physVx) * dt;
    this._physVy += (stiff * (tDy - this._physDy) - damp * this._physVy) * dt;
    this._physDx += this._physVx * dt;
    this._physDy += this._physVy * dt;
    /* --- colour, glow, badge, scan, emotion --- */
    this.tint += (c.tint - this.tint) * kGen;
    this.glowA += ((c.tint > 0 ? 1 : 0.5) - this.glowA) * kGen;
    this.badgeS += ((c.badge ? 1 : 0) - this.badgeS) * kGen;
    if (c.scan && !REDUCED) { this.scanX += dt * 0.9; if (this.scanX > 1.2) this.scanX = -1.2; }
    else this.scanX += (-1.2 - this.scanX) * kGen;   // a sweeping line is motion: park it off-screen
    const tgt = EMOTIONS[this.emotion] || EMOTIONS.calm;
    const kEmo = 1 - Math.pow(0.01, dt);                 // a feeling lands in ~0.2s, not ~2s
    for (const key of EMO_KEYS) this.emo[key] += (tgt[key] - this.emo[key]) * kEmo;
    /* --- blink on a timer --- */
    this._blinkAt -= dt;
    if (this._blinkAt <= 0) {
      if (this.state !== "sleeping" && this.state !== "dizzy") {
        this.blink();
        this._blinkAt = Math.random() < 0.22 ? 0.23 : 2.2 + Math.random() * 3.2;   // an occasional double blink
      } else this._blinkAt = 2.2 + Math.random() * 3.2;
    }
    this._particles(dt);
  }
  _particles(dt) {
    const c = this.cfg, e = this.emo;
    if (c.sweat && Math.random() < dt * 1.6) this.parts.push({ k: "drop", x: 40, y: -24, vy: 14, a: 1, s: 1 });
    if (c.stars && Math.random() < dt * 2.2) this.parts.push({ k: "star", x: (Math.random() * 2 - 1) * 40, y: -30 - Math.random() * 12, vy: -6, a: 1, s: 0.5 + Math.random() * 0.6 });
    if (e.smile > 0.75 && Math.random() < dt * 0.7) this.parts.push({ k: "spark", x: (Math.random() * 2 - 1) * 46, y: -22 - Math.random() * 14, vy: -8, a: 1, s: 0.4 + Math.random() * 0.5 });
    for (const p of this.parts) { p.y += p.vy * dt; if (p.vx) p.x += p.vx * dt;
      p.a -= dt * (p.k === "star" || p.k === "spark" ? 1.4 : p.k === "heart" ? 0.55 : 0.7); }
    this.parts = this.parts.filter(p => p.a > 0);
  }
  _shape(ctx, rx, ry) { SHAPES[this.sp.body](ctx, rx, ry, this.ti); }
  draw() {
    const ctx = this.ctx, S = this.size, d = this.dpr, R = S * 0.326;
    const rx = R * 1.14, ry = R * 0.88, cx = S / 2, cy = S / 2 + R * 0.06;
    ctx.setTransform(d, 0, 0, d, 0, 0);
    ctx.clearRect(0, 0, S, S);
    /* The body is quoted in rx/ry but the scene props are placed against the un-inset rx/ry, so
       this inset only shrinks the face against its own accessories. Keep it close to 1: the
       silhouette then fills its box instead of floating in it. */
    const k = 0.92;
    ctx.save(); ctx.translate(S / 2 * (1 - k), S / 2 * (1 - k)); ctx.scale(k, k);
    ctx.save();
    ctx.translate(cx + this.ox, cy + this.oy);
    if (this.tilt || this.roll) ctx.rotate(this.tilt + this.roll);
    ctx.scale(this.sx * (1 + (1 - this.sy) * 0.62), this.sy);

    if (this.sp.antenna) this._antenna(ctx, R, rx, ry);
    if (this.sp.ears !== "none") this._ears(ctx, R, rx, ry);

    if (this.glowA > 0.02) {
      ctx.save(); ctx.shadowColor = this.cfg.glow;
      ctx.shadowBlur = R * 0.9 * this.glowA; ctx.globalAlpha = 0.5 * this.glowA;
      this._shape(ctx, rx, ry); ctx.fillStyle = this.cfg.glow; ctx.fill(); ctx.restore();
    }
    if (this.flat) {
      /* Coucou's small-bot body: one flat fill, and none of the gradient, tint, shadow rim or
         highlight a big mascot gets. Those are what wash the colour out at 46px — and a state
         tint would also hide the bot's colour, which is the only thing the row is saying. The
         glow behind it still rides the state, so the row lights up without losing its colour. */
      this._shape(ctx, rx, ry); ctx.fillStyle = this.flat; ctx.fill();
    } else {
      const g = ctx.createLinearGradient(rx * 0.7, -ry * 0.85, -rx * 0.8, ry * 0.9);
      g.addColorStop(0, this.bodyTop); g.addColorStop(1, this.bodyBottom);
      this._shape(ctx, rx, ry); ctx.fillStyle = g; ctx.fill();
      if (this.tint > 0.01) {
        const tg = ctx.createLinearGradient(0, ry, 0, -ry);
        tg.addColorStop(0, hexA(this.cfg.glow, 0.72 * this.tint)); tg.addColorStop(1, hexA(this.cfg.glow, 0));
        this._shape(ctx, rx, ry); ctx.fillStyle = tg; ctx.fill();
      }
      const sg = ctx.createRadialGradient(0, 0, R * 0.15, 0, 0, R * 1.25);
      sg.addColorStop(0, "rgba(0,0,0,0)"); sg.addColorStop(0.6, "rgba(0,0,0,0)"); sg.addColorStop(1, "rgba(0,0,0,0.2)");
      this._shape(ctx, rx, ry); ctx.fillStyle = sg; ctx.fill();
      const hg = ctx.createRadialGradient(rx * 0.34, -ry * 0.46, 0, rx * 0.34, -ry * 0.46, R * 0.42);
      hg.addColorStop(0, "rgba(255,255,255,0.55)"); hg.addColorStop(1, "rgba(255,255,255,0)");
      this._shape(ctx, rx, ry); ctx.fillStyle = hg; ctx.fill();
    }
    const ba = clamp((0.28 + 0.5 * this.tint) * 0.7 + this.emo.blush * 0.8, 0, 0.9);
    if (ba > 0.02) for (const sd of [-1, 1]) {
      ctx.save(); ctx.globalAlpha = ba; ctx.fillStyle = "#FF8FB1";
      ctx.beginPath(); ctx.ellipse(sd * rx * 0.55 + this.yaw * rx * 0.35, ry * 0.2, rx * 0.30, ry * 0.20, 0, 0, 7); ctx.fill(); ctx.restore();
    }
    if (this.cfg.scan) {
      ctx.save(); this._shape(ctx, rx, ry); ctx.clip();
      const sx = this.scanX * rx;
      const lg = ctx.createLinearGradient(sx - 10, 0, sx + 10, 0);
      lg.addColorStop(0, "rgba(255,255,255,0)"); lg.addColorStop(0.5, "rgba(255,255,255,0.5)"); lg.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = lg; ctx.fillRect(sx - 10, -ry, 20, ry * 2); ctx.restore();
    }
    this._eyes(ctx, R, rx, ry);
    this._mouth(ctx, R, rx, ry);
    ctx.restore();

    this._props(ctx, cx + this.ox, cy + this.oy, R, rx, ry);
    if (this.badgeS > 0.02) this._badge(ctx, cx + this.ox, cy + this.oy, R);
    this._parts(ctx, cx + this.ox, cy + this.oy);
    ctx.restore();
  }
  _ears(ctx, R, rx, ry) {
    /* The spring's lag, not a smoothed derivative: ears swing back when the head turns
       and lift when the body drops, and they ring past the target before settling. */
    const a = this._physDx * 0.9, dy = -this._physDy * R * 0.10, kind = this.sp.ears;
    ctx.save();
    if (kind === "cat") {
      for (const sd of [-1, 1]) {
        ctx.save(); ctx.translate(sd * rx * 0.56, -ry * 0.80 + dy); ctx.rotate(sd * (0.10 + a));
        ctx.beginPath(); ctx.moveTo(-R * 0.20, R * 0.14); ctx.lineTo(R * 0.02, -R * 0.42); ctx.lineTo(R * 0.24, R * 0.12);
        ctx.closePath(); ctx.fillStyle = this.bodyBottom; ctx.fill();
        ctx.beginPath(); ctx.moveTo(-R * 0.10, R * 0.10); ctx.lineTo(R * 0.02, -R * 0.26); ctx.lineTo(R * 0.14, R * 0.09);
        ctx.closePath(); ctx.fillStyle = "rgba(255,150,175,0.75)"; ctx.fill(); ctx.restore();
      }
    } else if (kind === "bunny") {
      for (const sd of [-1, 1]) {
        ctx.save(); ctx.translate(sd * rx * 0.34, -ry * 0.78 + dy); ctx.rotate(sd * (0.16 + a * 1.6));
        ctx.beginPath(); ctx.ellipse(0, -R * 0.42, R * 0.13, R * 0.46, 0, 0, 7);
        ctx.fillStyle = this.bodyBottom; ctx.fill();
        ctx.beginPath(); ctx.ellipse(0, -R * 0.42, R * 0.06, R * 0.32, 0, 0, 7);
        ctx.fillStyle = "rgba(255,150,175,0.7)"; ctx.fill(); ctx.restore();
      }
    } else if (kind === "horns") {
      /* Drawn under the body, so the tip has to clear the silhouette or it vanishes
         and the imp reads as a plain mochi. Origin high, tip past -1.2R. */
      for (const sd of [-1, 1]) {
        ctx.save(); ctx.translate(sd * rx * 0.46, -ry * 0.82 + dy); ctx.rotate(sd * (0.30 + a * 1.4));
        ctx.beginPath(); ctx.moveTo(-R * 0.15, R * 0.14);
        ctx.quadraticCurveTo(-R * 0.10, -R * 0.40, sd * R * 0.30, -R * 0.60);
        ctx.quadraticCurveTo(R * 0.06, -R * 0.24, R * 0.15, R * 0.14);
        ctx.closePath(); ctx.fillStyle = "#C99A63"; ctx.fill(); ctx.restore();
      }
    } else if (kind === "tufts") {
      for (const sd of [-1, 1]) {
        ctx.save(); ctx.translate(sd * rx * 0.62, -ry * 0.66 + dy); ctx.rotate(sd * (0.35 + a));
        ctx.beginPath(); ctx.moveTo(-R * 0.16, R * 0.10); ctx.lineTo(0, -R * 0.34); ctx.lineTo(R * 0.16, R * 0.10);
        ctx.closePath(); ctx.fillStyle = this.bodyBottom; ctx.fill(); ctx.restore();
      }
    }
    ctx.restore();
  }
  _antenna(ctx, R, rx, ry) {
    const a = this._physDx * 1.5, ball = this.sp.antenna === "ball";
    ctx.save(); ctx.translate(this._physDx * R * 0.14, -ry * 0.86 - this._physDy * R * 0.08); ctx.rotate(a);
    ctx.strokeStyle = this.bodyBottom; ctx.lineWidth = R * 0.075; ctx.lineCap = "round";
    ctx.beginPath(); ctx.moveTo(0, 0); ctx.quadraticCurveTo(R * 0.06, -R * 0.26, 0, -R * 0.42); ctx.stroke();
    ctx.beginPath(); ctx.arc(0, -R * 0.46, R * (ball ? 0.15 : 0.09), 0, 7);
    ctx.fillStyle = ball ? this.cfg.glow : this.bodyBottom; ctx.fill();
    ctx.restore();
  }
  /* The face is two bands: eyes above, mouth below, and this is the only place the split is
     defined. However far the gaze swings, the eyes are held clear of the mouth, and both stay
     inside the head — a face whose eyes land on its mouth stops reading as a face. */
  _eyeHalfH(R) {
    const st = EYE[this.sp.eyes] || EYE.pill, e = this.emo, es = this.es;
    if (this.sp.eyes === "screen") return R * 0.22;                    // the visor is a fixed box
    const h = R * st.h * clamp(e.eye, 0, 1.4) * es, w = R * st.w * es;
    if (this.sp.eyes === "wide")  return Math.max(h * 1.12, w * 0.30) / 2;
    return Math.max(h, w * 0.32) / 2;
  }
  _faceGeom(R, rx, ry) {
    const half = this._eyeHalfH(R);
    const mouthY = ry * 0.56;                                          // mouth centre
    const mouthTop = mouthY - R * Math.max(0.17, 0.10 + 0.24 * clamp(this.emo.open, 0, 1));
    /* knee: how far short of the limit the eye may ease, so the approach stays smooth */
    const eyeMinY = -ry * 0.66, eyeMaxY = mouthTop - R * 0.09 - half;
    return { mouthY, mouthTop, eyeMinY, eyeMaxY,
             knee: Math.max(R * 0.12, (eyeMaxY - eyeMinY) * 0.14) };
  }
  /* Where an eye actually lands, after the cylinder projection and the band limit. Both the
     renderer and the tests go through here, so the guarantee lives in one place. */
  eyeAt(sd, R, rx, ry) {
    const st = EYE[this.sp.eyes] || EYE.pill;
    const F = eyeFrame(sd, this.yaw, this.pitch, rx, ry, st.sp, st.y);
    if (F.vis && this.sp.eyes !== "bulge") {
      const G = this._faceGeom(R, rx, ry);
      F.y = softLimit(F.y, G.eyeMinY, G.eyeMaxY, G.knee);
    }
    return F;
  }
  _eyes(ctx, R, rx, ry) {
    const st = EYE[this.sp.eyes] || EYE.pill, ink = MC.INK, e = this.emo;
    const es = this.es;                                      // surprise pop: eyes widen for a beat
    const w = R * st.w * es, h = R * st.h * clamp(e.eye, 0, 1.4) * es;
    const bulge = this.sp.eyes === "bulge";
    if (!bulge) { ctx.save(); this._shape(ctx, rx, ry); ctx.clip(); }
    for (const sd of [-1, 1]) {
      const F = this.eyeAt(sd, R, rx, ry);
      if (!F.vis) continue;
      ctx.save(); ctx.translate(F.x, F.y); ctx.scale(F.fx, F.fy);
      if (this.sp.eyes === "screen") {                       // a robot visor, lit by the state colour
        const vw = R * 0.98, vh = R * 0.44;
        ctx.beginPath(); rr(ctx, -vw / 2, -vh / 2, vw, vh, vh * 0.32);
        ctx.fillStyle = "#15161C"; ctx.fill();
        const ow = vw * 0.30, oh = Math.max(vh * 0.30, vh * 0.62 * clamp(this.open * e.eye, 0, 1));
        for (const s2 of [-1, 1]) {
          ctx.beginPath(); rr(ctx, s2 * vw * 0.22 - ow / 2, -oh / 2, ow, oh, oh * 0.3);
          ctx.fillStyle = this.cfg.glow; ctx.fill();
        }
      } else if (bulge) {                                    // eyes that sit on top of the head
        const r = R * st.w * (0.92 + e.eye * 0.20);
        ctx.beginPath(); ctx.arc(0, 0, r, 0, 7); ctx.fillStyle = this.bodyTop; ctx.fill();
        ctx.lineWidth = R * 0.035; ctx.strokeStyle = "rgba(0,0,0,0.16)"; ctx.stroke();
        const ph = Math.max(r * 0.55, r * clamp(this.open * e.eye, 0, 1.1));
        ctx.beginPath(); ctx.ellipse(this.yaw * r * 0.5, this.pitch * r * 0.5, r * 0.42, ph * 0.55, 0, 0, 7);
        ctx.fillStyle = ink; ctx.fill();
      } else {
        const o = this.open;
        switch (this.sp.eyes) {
          case "wide": {
            const hh = Math.max(h * 1.12 * o, w * 0.30);
            ctx.beginPath(); rr(ctx, -w * 0.58, -hh / 2, w * 1.16, hh, Math.min(w * 1.16, hh) / 2);
            ctx.fillStyle = ink; ctx.fill(); break;
          }
          default: {
            const hh = Math.max(h * o, w * 0.32);
            ctx.beginPath(); rr(ctx, -w / 2, -hh / 2, w, hh, Math.min(w, hh) / 2);
            ctx.fillStyle = ink; ctx.fill(); break;
          }
        }
      }
      ctx.restore();
    }
    if (!bulge) ctx.restore();
    /* brows: the strongest emotion signal, drawn over the eyes */
    if (Math.abs(e.brow) > 0.06) {
      ctx.save(); if (!bulge) { this._shape(ctx, rx, ry); ctx.clip(); }
      ctx.strokeStyle = ink; ctx.lineWidth = R * 0.055; ctx.lineCap = "round";
      for (const sd of [-1, 1]) {
        const F = this.eyeAt(sd, R, rx, ry);
        if (!F.vis) continue;
        /* the brow rides the same band as the eye, so it never drifts off the forehead */
        ctx.save(); ctx.translate(F.x, F.y - R * st.h * 0.92); ctx.scale(F.fx, F.fy);
        ctx.rotate(-e.brow * 0.5 * sd);
        ctx.beginPath(); ctx.moveTo(-w * 0.5, 0); ctx.lineTo(w * 0.5, 0); ctx.stroke(); ctx.restore();
      }
      ctx.restore();
    }
  }
  _mouth(ctx, R, rx, ry) {
    const e = this.emo;
    if (e.eye < 0.12 && this.sp.eyes !== "screen") return;   // asleep: no mouth to speak of
    const mw = R * 0.40, my = this._faceGeom(R, rx, ry).mouthY;   // shares the eye/mouth split
    ctx.save(); this._shape(ctx, rx, ry); ctx.clip();
    ctx.strokeStyle = MC.INK; ctx.lineWidth = R * 0.055; ctx.lineCap = "round"; ctx.lineJoin = "round";
    if (e.open > 0.12) {
      const ow = mw * (0.42 + 0.55 * clamp(e.smile, -0.4, 1)), oh = R * (0.10 + 0.24 * e.open);
      ctx.beginPath(); ctx.ellipse(0, my, ow, oh, 0, 0, 7);
      ctx.fillStyle = MC.INK; ctx.fill();
      ctx.save(); ctx.beginPath(); ctx.ellipse(0, my + oh * 0.42, ow * 0.52, oh * 0.38, 0, 0, 7);
      ctx.fillStyle = "#FF7EA0"; ctx.fill(); ctx.restore();
    } else {
      ctx.beginPath();
      if (e.wave > 0.5) {
        ctx.moveTo(-mw / 2, my);
        ctx.quadraticCurveTo(-mw / 4, my - R * 0.10, 0, my);
        ctx.quadraticCurveTo(mw / 4, my + R * 0.10, mw / 2, my);
      } else {
        const lift = e.smile * R * 0.13;
        ctx.moveTo(-mw / 2, my - lift);
        ctx.quadraticCurveTo(0, my + e.smile * R * 0.34, mw / 2, my - lift);
      }
      ctx.stroke();
    }
    ctx.restore();
  }
  /* ---------- scene props ---------- */
  _props(ctx, cx, cy, R, rx, ry) {
    const c = this.cfg;
    ctx.save(); ctx.translate(cx, cy);
    if (c.bubble) this._bubble(ctx, R, rx, ry);
    if (c.mag)    this._mag(ctx, R, rx, ry);
    if (c.hand)   this._hand(ctx, R, rx, ry);
    if (c.zz)     this._zz(ctx, R, rx, ry);
    if (c.desk)   this._desk(ctx, R, rx, ry);
    ctx.restore();
  }
  _bubble(ctx, R, rx, ry) {
    const t = this.ti, cw = R * 0.60;
    ctx.save(); ctx.translate(rx * 0.60, -ry * 0.96);
    ctx.fillStyle = "#EDEDF2";
    ctx.beginPath(); ctx.arc(-rx * 0.30, ry * 0.62, R * 0.085, 0, 7); ctx.fill();
    ctx.beginPath(); ctx.arc(-rx * 0.12, ry * 0.34, R * 0.125, 0, 7); ctx.fill();
    ctx.beginPath();
    ctx.arc(-cw * 0.52, 0, cw * 0.52, 0, 7); ctx.arc(0, -cw * 0.24, cw * 0.62, 0, 7);
    ctx.arc(cw * 0.52, 0, cw * 0.52, 0, 7); ctx.arc(0, cw * 0.20, cw * 0.56, 0, 7);
    ctx.fill();
    ctx.fillStyle = "#6B6B78";
    for (let i = 0; i < 3; i++) {
      ctx.globalAlpha = 0.35 + 0.65 * (0.5 + 0.5 * Math.sin(t * 5 - i * 1.2));
      ctx.beginPath(); ctx.arc(-cw * 0.36 + i * cw * 0.36, -cw * 0.02, R * 0.075, 0, 7); ctx.fill();
    }
    ctx.restore();
  }
  _mag(ctx, R, rx, ry) {
    const t = this.ti;
    ctx.save(); ctx.translate(rx * 0.86, ry * 0.30); ctx.rotate(0.5 + Math.sin(t * 2) * 0.06);
    ctx.beginPath(); ctx.arc(0, 0, R * 0.30, 0, 7);
    ctx.fillStyle = "rgba(140,190,255,0.35)"; ctx.fill();
    ctx.lineWidth = R * 0.075; ctx.strokeStyle = "#2B2B33"; ctx.stroke();
    ctx.beginPath(); ctx.arc(-R * 0.10, -R * 0.10, R * 0.085, 0, 7); ctx.fillStyle = "rgba(255,255,255,0.7)"; ctx.fill();
    ctx.beginPath(); ctx.moveTo(R * 0.21, R * 0.21); ctx.lineTo(R * 0.52, R * 0.52);
    ctx.lineWidth = R * 0.11; ctx.lineCap = "round"; ctx.strokeStyle = "#2B2B33"; ctx.stroke();
    ctx.restore();
  }
  _hand(ctx, R, rx, ry) {
    const t = this.ti, hx = rx * 0.92, hy = -ry * 0.55 + Math.sin(t * 6) * R * 0.06;
    ctx.save();
    ctx.strokeStyle = "#2B2B33"; ctx.lineWidth = R * 0.13; ctx.lineCap = "round";
    ctx.beginPath(); ctx.moveTo(rx * 0.68, ry * 0.06); ctx.quadraticCurveTo(hx, -ry * 0.15, hx, hy); ctx.stroke();
    ctx.translate(hx, hy);
    ctx.fillStyle = "#2B2B33";
    ctx.beginPath(); rr(ctx, -R * 0.16, -R * 0.05, R * 0.32, R * 0.34, R * 0.10); ctx.fill();
    for (let i = 0; i < 4; i++) {
      ctx.beginPath(); rr(ctx, -R * 0.15 + i * R * 0.085, -R * 0.28, R * 0.065, R * 0.30, R * 0.03); ctx.fill();
    }
    ctx.beginPath(); rr(ctx, -R * 0.28, -R * 0.02, R * 0.13, R * 0.20, R * 0.06); ctx.fill();
    ctx.restore();
  }
  _zz(ctx, R, rx, ry) {
    const t = this.ti;
    for (let i = 0; i < 3; i++) {
      const ph = (t * 0.55 + i / 3) % 1;
      ctx.save();
      ctx.globalAlpha = Math.sin(ph * Math.PI) * 0.9;
      ctx.fillStyle = "#B9C2D0";
      ctx.font = `800 ${(12 + ph * 9) * (R / 49)}px ui-sans-serif,sans-serif`;
      ctx.textAlign = "center";
      ctx.translate(rx * 0.70 + ph * R * 0.35, -ry * 0.55 - ph * R * 0.9);
      ctx.rotate(Math.sin(ph * 6) * 0.12);
      ctx.fillText("Z", 0, 0);
      ctx.restore();
    }
  }
  _desk(ctx, R, rx, ry) {
    const t = this.ti;
    const dw = rx * 2.15, dh = R * 0.28, dy = ry * 0.84;
    const g = ctx.createLinearGradient(0, dy, 0, dy + dh);
    g.addColorStop(0, "#43434F"); g.addColorStop(1, "#2A2A34");
    ctx.beginPath(); rrect(ctx, -dw / 2, dy, dw, dh, R * 0.09); ctx.fillStyle = g; ctx.fill();
    ctx.beginPath(); rrect(ctx, -dw / 2, dy, dw, R * 0.055, R * 0.03); ctx.fillStyle = "rgba(255,255,255,0.09)"; ctx.fill();
    const lw = R * 0.70, lh = R * 0.46, ly = dy - R * 0.02;
    ctx.beginPath(); rrect(ctx, -lw / 2, ly - lh, lw, lh * 0.92, R * 0.08); ctx.fillStyle = "#1C1C24"; ctx.fill();
    ctx.beginPath(); rrect(ctx, -lw / 2 + R * 0.055, ly - lh + R * 0.065, lw - R * 0.11, lh * 0.92 - R * 0.13, R * 0.045);
    ctx.fillStyle = hexA(this.cfg.glow, 0.85); ctx.fill();
    ctx.fillStyle = "rgba(255,255,255,0.78)";
    for (let i = 0; i < 3; i++) {
      const w = (0.30 + 0.5 * ((Math.sin(t * 3 + i * 1.7) + 1) / 2)) * (lw - R * 0.20);
      ctx.beginPath(); rrect(ctx, -lw / 2 + R * 0.11, ly - lh + R * 0.15 + i * R * 0.10, w, R * 0.042, R * 0.02); ctx.fill();
    }
    ctx.beginPath(); rrect(ctx, -lw * 0.60, ly - R * 0.015, lw * 1.20, R * 0.095, R * 0.035); ctx.fillStyle = "#33333D"; ctx.fill();
    ctx.fillStyle = "#2B2B33";
    for (const sd of [-1, 1]) {
      const yy = ly - R * 0.07 + Math.sin(t * 9 + (sd > 0 ? 0 : Math.PI)) * R * 0.028;
      ctx.beginPath(); ctx.arc(sd * lw * 0.44, yy, R * 0.10, 0, 7); ctx.fill();
    }
  }
  _badge(ctx, cx, cy, R) {
    const kind = this.cfg.badge, col = this.cfg.glow, s = this.badgeS;
    ctx.save(); ctx.translate(cx - R * 0.72, cy - R * 0.72); ctx.scale(s, s); ctx.fillStyle = col;
    const now = this.ti;
    if (kind === "dots") for (let i = 0; i < 3; i++) {
      ctx.globalAlpha = 0.35 + 0.65 * (0.5 + 0.5 * Math.sin(now * 5.7 - i * 1.1));
      ctx.beginPath(); ctx.arc(i * 9 - 9, 0, 3.4, 0, 7); ctx.fill();
    } else if (kind === "bang") {
      ctx.globalAlpha = 1; const sc = 1 + Math.sin(now * 6) * 0.14;
      ctx.save(); ctx.scale(sc, sc);
      ctx.beginPath(); rr(ctx, -2.6, -11, 5.2, 14, 2.6); ctx.fill();
      ctx.beginPath(); ctx.arc(0, 7.5, 3.2, 0, 7); ctx.fill(); ctx.restore();
    } else if (kind === "question") {
      ctx.globalAlpha = 0.55 + 0.45 * (0.5 + 0.5 * Math.sin(now * 4.8));
      ctx.font = "800 20px -apple-system,sans-serif"; ctx.textAlign = "center"; ctx.fillText("?", 0, 7);
    } else if (kind === "dot") {
      ctx.globalAlpha = 1; ctx.beginPath(); ctx.arc(0, 0, 3.6 + Math.sin(now * 4.5) * 1.1, 0, 7); ctx.fill();
    }
    ctx.restore();
  }
  _parts(ctx, cx, cy) {
    for (const p of this.parts) {
      ctx.save(); ctx.globalAlpha = clamp(p.a, 0, 1); ctx.translate(cx + p.x, cy + p.y);
      if (p.k === "star") { ctx.fillStyle = "#F7B32B"; star(ctx, 7 * p.s); }
      else if (p.k === "spark") { ctx.fillStyle = "#FFF0B8"; star(ctx, 5 * p.s); }
      else if (p.k === "heart") { ctx.fillStyle = "#FF6B93"; heart(ctx, 8 * p.s); }
      else if (p.k === "drop") { ctx.fillStyle = "#8FD3FF"; ctx.beginPath(); ctx.moveTo(0, -5); ctx.quadraticCurveTo(5, 3, 0, 7); ctx.quadraticCurveTo(-5, 3, 0, -5); ctx.fill(); }
      else { ctx.fillStyle = "#B9C2D0"; ctx.font = `800 ${16 * p.s}px sans-serif`; ctx.textAlign = "center"; ctx.fillText("Z", 0, 0); }
      ctx.restore();
    }
  }
}

/* ---- small helpers ---- */
function rr(ctx, x, y, w, h, r) {
  r = Math.min(r, w / 2, h / 2);
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}
function rrect(ctx, x, y, w, h, r) { ctx.beginPath(); rr(ctx, x, y, w, h, r); }
function poly(ctx, pts, r) {
  const n = pts.length;
  ctx.beginPath();
  for (let i = 0; i < n; i++) {
    const p0 = pts[(i - 1 + n) % n], p1 = pts[i], p2 = pts[(i + 1) % n];
    const v1x = p1[0] - p0[0], v1y = p1[1] - p0[1], v2x = p2[0] - p1[0], v2y = p2[1] - p1[1];
    const l1 = Math.hypot(v1x, v1y) || 1, l2 = Math.hypot(v2x, v2y) || 1;
    const c1 = Math.min(r, l1 / 2), c2 = Math.min(r, l2 / 2);
    const ax = p1[0] - v1x / l1 * c1, ay = p1[1] - v1y / l1 * c1;
    const bx = p1[0] + v2x / l2 * c2, by = p1[1] + v2y / l2 * c2;
    i ? ctx.lineTo(ax, ay) : ctx.moveTo(ax, ay);
    ctx.quadraticCurveTo(p1[0], p1[1], bx, by);
  }
  ctx.closePath();
}
function star(ctx, r) {
  ctx.beginPath();
  for (let i = 0; i < 10; i++) {
    const a = Math.PI / 5 * i - Math.PI / 2, r2 = i % 2 ? r * 0.44 : r;
    const x = Math.cos(a) * r2, y = Math.sin(a) * r2;
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  }
  ctx.closePath(); ctx.fill();
}
function heart(ctx, r) {
  ctx.beginPath();
  ctx.moveTo(0, r * 0.72);
  ctx.bezierCurveTo(-r * 1.35, -r * 0.25, -r * 0.5, -r * 1.05, 0, -r * 0.35);
  ctx.bezierCurveTo(r * 0.5, -r * 1.05, r * 1.35, -r * 0.25, 0, r * 0.72);
  ctx.closePath(); ctx.fill();
}
/* The eyes ride a shorter vertical arc than the full pitch: a face whose eyes travel the whole
   height ends up with them in the mouth. 0.45 keeps the gaze legible and the gap honest. */
const EYE_PITCH = 0.45;
/* Coucou places the eyes on a cylinder and projects them. That is why its gaze reads as a
   head turning rather than a sticker sliding: the eyes swing, foreshorten (fx/fy), and slip
   past the horizon (vis) as they go. A linear slide keeps them full-width and glued on.
   `p` is the rest pitch, measured downward-positive like the rest of this engine (Coucou's
   eyeP is the negation of it). */
export function eyeFrame(sd, yaw, pitch, rx, ry, sp, p) {
  const ey = sd * sp + yaw, ep = p + pitch * EYE_PITCH, cp = Math.cos(ep);
  return {
    x: Math.sin(ey) * cp * rx, y: Math.sin(ep) * ry,
    fx: Math.max(0.18, Math.cos(ey)), fy: Math.max(0.18, cp),
    vis: Math.cos(ey) * cp > 0.04,
  };
}
/* A limit the value can approach but never cross, with no sudden stop: identity inside the
   band, then a rational ease that flattens into the limit with a continuous velocity at the
   knee. It is strictly monotonic — a hard clamp would freeze the eye mid-gaze and read as a
   stuck face, and an exponential ease would turn it back on itself. */
export function softLimit(v, lo, hi, knee) {
  if (v > hi - knee) { const u = (v - (hi - knee)) / knee; return hi - knee / (1 + u); }
  if (v < lo + knee) { const u = (lo + knee - v) / knee; return lo + knee / (1 + u); }
  return v;
}
function hexA(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

/* ---- one global loop drives every bot (single rAF, smooth) ---- */
/* `prefers-reduced-motion` is honoured here as well as in the CSS: the faces are drawn on a canvas,
   so the media query in index.html cannot reach them. `tick` freezes only the *continuous* idle
   motion (bob, breathe, sway, the sweeping scan, the cursor gaze, the random fidgets); a state
   change still lands, because a face that never updated would be a worse lie than a short tween. */
const REDUCED = typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;
const bots = new Set();
let last = performance.now(), running = false;
function loop(now) {
  const dt = Math.min((now - last) / 1000, 0.05); last = now;
  for (const b of bots) { b.tick(dt); b.draw(); }
  /* With no faces attached — mascot hidden, or the last chat closed — the loop stands down instead of
     spinning a rAF forever; `attach` starts it again. */
  if (!bots.size) { running = false; return; }
  requestAnimationFrame(loop);
}
/* The cursor drives every face, so the listener lives here, not in the app. */
if (typeof window !== "undefined") {
  window.addEventListener("pointermove", e => { POINTER.x = e.clientX; POINTER.y = e.clientY; POINTER.on = true; applyPointer(); }, { passive: true });
  window.addEventListener("scroll", () => { invalidateRects(); applyPointer(); }, { passive: true });
  window.addEventListener("resize", () => { invalidateRects(); applyPointer(); });
  window.addEventListener("pointerleave", releasePointer);
  window.addEventListener("blur", releasePointer);
}
export function attach(canvas, state, opts) {
  const b = new MochiBot(canvas, state, opts);
  bots.add(b);
  if (!running) { running = true; last = performance.now(); requestAnimationFrame(loop); }
  return b;
}
export function detach(b) { bots.delete(b); }
