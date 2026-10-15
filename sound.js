/* sound.js — notification chimes, synthesised in the browser.
   There is no audio file to ship, fetch or license: a cue is a short contour of two notes drawn
   with an oscillator and a gain envelope. What makes it read as a notification rather than a beep
   is the envelope — a ~12ms attack into a long exponential tail — and the two-note shape, which
   carries meaning (rising = good, falling = bad) that a single flat tone cannot. */

/* Equal-tempered frequencies, named so the cue table below reads as music. */
const NOTE = { E4: 329.63, A4: 440.00, D5: 587.33, E5: 659.25, A5: 880.00, B5: 987.77, C6: 1046.50 };

/* Each cue is [frequency, start offset (s), duration (s), relative gain, waveform].
   The four are distinct in contour and register, so they are told apart without being learned:
   done rises a fifth, ask rises a little and higher (question intonation), error falls, limit sits
   flat on one note. */
export const CUES = {
  done:  [[NOTE.E5, 0, 0.15, 1.00, "sine"],     [NOTE.B5, 0.10, 0.32, 0.80, "sine"]],
  ask:   [[NOTE.A5, 0, 0.09, 0.90, "sine"],     [NOTE.C6, 0.08, 0.20, 0.70, "sine"]],
  error: [[NOTE.A4, 0, 0.16, 1.00, "triangle"], [NOTE.E4, 0.13, 0.36, 0.85, "triangle"]],
  limit: [[NOTE.D5, 0, 0.08, 0.85, "triangle"], [NOTE.D5, 0.14, 0.08, 0.65, "triangle"]],
};

/* Which of the dock's states is worth interrupting someone for. The middle of a turn is not —
   working and thinking would be a metronome — so every other state maps to nothing, on purpose. */
export const CUE_FOR = {
  finished: "done", error: "error", approval: "ask", question: "ask", ratelimit: "limit",
};

let ac = null, dead = false;

/* Browsers only allow audio to start from a user gesture, so the context is opened on the first
   real click or keypress and reused for the life of the page. Creating it any earlier leaves it
   suspended, which is both silent and a console warning on every page load. */
export function unlock() {
  if (dead) return null;
  try {
    if (!ac) {
      const C = globalThis.AudioContext || globalThis.webkitAudioContext;
      if (!C) { dead = true; return null; }
      ac = new C();
    }
    if (ac.state === "suspended") ac.resume();
    return ac;
  } catch (e) { dead = true; return null; }   // no sound is never a reason to break the interface
}

export function cue(name, volume = 0.5) {
  const notes = CUES[name];
  if (!notes || !(volume > 0) || !ac) return false;   // before the first gesture there is no context
  if (ac.state === "suspended") ac.resume();
  try {
    const t0 = ac.currentTime + 0.01;
    for (const [f, at, dur, gain, type] of notes) {
      const o = ac.createOscillator(), g = ac.createGain();
      o.type = type; o.frequency.setValueAtTime(f, t0 + at);
      /* Silence, up to the peak, then an exponential tail. Neither ramp may touch exactly zero,
         so both ends sit a hair above it. A flat envelope is what makes a chime sound like an alarm. */
      g.gain.setValueAtTime(0.0001, t0 + at);
      g.gain.exponentialRampToValueAtTime(Math.max(0.0002, gain * volume * 0.35), t0 + at + 0.012);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + at + dur);
      o.connect(g).connect(ac.destination);
      o.start(t0 + at); o.stop(t0 + at + dur + 0.03);
    }
    return true;
  } catch (e) { return false; }
}
