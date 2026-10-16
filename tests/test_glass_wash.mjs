/* Offline checks for where the glass themes put their wash — no browser, no DOM library.

   The wash is a full-viewport animated gradient sitting under the whole app. It used to be
   `body::before`. On a pseudo-element Chromium does not composite it, so every animation frame
   re-committed the entire document: on a 1597-row transcript that measured 800ms of commit per
   2.5s arriving in ~200ms stalls, and scrolling dropped 8.6% of frames. Moved to a real element the
   same gradient and the same keyframes composite, commit falls to ~40ms, and scrolling is clean —
   the two are indistinguishable on screen, so nothing here can be caught by looking.

   What is pinned is the structure the fix depends on: the wash is a real element, fixed, animated
   only on the two glass themes; and the glass `::before` rule is gone rather than merely unused.
   Run: node tests/test_glass_wash.mjs   (exit 0 = all green) */
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
let pass = 0, fail = 0;
const ok = (name, cond, extra = "") => {
  if (cond) { pass++; console.log("  ok   " + name); }
  else { fail++; console.log("  FAIL " + name + (extra ? "  -> " + extra : "")); }
};
const blocks = [...html.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(m => [m[1].trim(), m[2]]);
const rule = sel => { const b = blocks.find(([s]) => s.split(",").map(x => x.trim()).includes(sel)); return b && b[1]; };

const wash = rule("#wash");
ok("index.html has an #wash rule", !!wash);
ok("#wash is a real, fixed, full-viewport layer", !!wash && /position:\s*fixed/.test(wash) && /inset:\s*0/.test(wash));

const shown = rule('body[data-theme="glass"] #wash');
ok("the wash is shown and animated on the glass themes", !!shown && /animation:\s*wash\b/.test(shown), shown);
ok("the wash carries the gradient", !!shown && /radial-gradient/.test(shown));

const light = rule('body[data-theme="glass-light"] #wash');
ok("glass-light shows it too", !!light && /animation:\s*wash\b/.test(light));

/* The defect itself: an animated full-viewport background on a pseudo-element of the grid body. */
const pseudo = blocks.filter(([s, b]) => /::before|::after/.test(s) && /animation:\s*wash/.test(b)).map(([s]) => s);
ok("no pseudo-element carries the wash animation", pseudo.length === 0, pseudo.join(" | "));

ok("the wash element is in the document", /<div id="wash"/.test(html));
ok("the wash is hidden until a glass theme asks for it", !!rule("#wash") && /display:\s*none/.test(rule("#wash")));
ok("@keyframes wash still defines the movement", /@keyframes wash\{[^}]*translate3d/.test(html));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
