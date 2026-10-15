/* Offline checks for the composer's Enter-to-send IME guard — no browser, no DOM library.

   An IME (Japanese, Chinese, Korean) uses Enter to accept the candidate it is offering, and that
   Enter reaches the composer's keydown handler like any other key. Without a guard the message goes
   out mid-word: the turn starts with the composition still open, and the rest of the word lands in
   an empty composer. app.js is an ES module that boots the whole UI, so it cannot be imported here;
   the handler is read out of the source and installed on a fake node whose addEventListener records
   it. If the extraction ever stops matching, these checks fail rather than pass on nothing.

   Run: node tests/test_composer_ime.mjs   (exit 0 = all green) */
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../app.js", import.meta.url), "utf8");
const slice = (from, to) => {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0 || b < a) { console.log("FAIL could not find " + from + " in app.js"); process.exit(1); }
  return src.slice(a, b);
};
/* The handler under test, and the mention popover's own keys that live inside it — the same block. */
const block = slice('$("#input").addEventListener("keydown"', '$("#input").addEventListener("input"');

let pass = 0, fail = 0;
const ok = (name, cond, extra = "") => {
  if (cond) { pass++; console.log("  ok   " + name); }
  else { fail++; console.log("  FAIL " + name + (extra ? "  -> " + extra : "")); }
};

/* A fake composer node: its addEventListener hands the keydown handler back to us, which is the only
   thing the app does with it at this point. */
let handler = null;
const input = { addEventListener: (type, fn) => { if (type === "keydown") handler = fn; } };
const $ = sel => (sel === "#input" ? input : null);

/* The popover state and the four things the handler reaches for when the list is open. Each records
   that it was called, so "did not fire" is an assertion and not a silence. */
const MP = { open: false, items: [{}, {}, {}], idx: 0, at: 0 };
const called = { renderMention: 0, insertMention: 0, closeMention: 0, send: 0 };
const renderMention = () => { called.renderMention++; };
const insertMention = () => { called.insertMention++; };
const closeMention = () => { called.closeMention++; };
const send = () => { called.send++; };

/* The app's own handler, installed on the fake node. `MP` and the four callbacks are handed in as
   parameters because the lifted source is the app's own and does not define them. */
new Function("$", "MP", "renderMention", "insertMention", "closeMention", "send",
  '"use strict";' + block)(($), MP, renderMention, insertMention, closeMention, send);
if (!handler) { console.log("FAIL the keydown handler was never installed"); process.exit(1); }

/* A keyboard event as the handler sees it: only the fields the block reads, plus preventDefault. */
const ev = (key, opts = {}) => ({
  key, shiftKey: false, isComposing: false, keyCode: 0, prevented: false,
  preventDefault() { this.prevented = true; }, ...opts,
});
const reset = () => { called.send = 0; called.insertMention = 0; called.renderMention = 0; called.closeMention = 0; };

console.log("\n-- a plain Enter sends --");
reset();
const plain = ev("Enter");
handler(plain);
ok("Enter with no composition sends the message", called.send === 1, "send=" + called.send);
ok("...and the newline is suppressed", plain.prevented === true, "prevented=" + plain.prevented);

console.log("\n-- a composition's Enter does not --");
reset();
handler(ev("Enter", { isComposing: true }));
ok("Enter with isComposing sends nothing", called.send === 0, "send=" + called.send);
reset();
handler(ev("Enter", { keyCode: 229 }));
ok("Enter with the legacy keyCode 229 sends nothing", called.send === 0, "send=" + called.send);
reset();
handler(ev("Enter", { isComposing: true, keyCode: 229 }));
ok("both flags at once still send nothing", called.send === 0, "send=" + called.send);

console.log("\n-- Shift+Enter never sends --");
reset();
handler(ev("Enter", { shiftKey: true }));
ok("Shift+Enter is a newline, not a send", called.send === 0, "send=" + called.send);

console.log("\n-- the mention popover's own Enter --");
reset();
MP.open = true;
handler(ev("Enter"));
ok("with the list open, Enter takes the highlighted mention", called.insertMention === 1 && called.send === 0,
  "insert=" + called.insertMention + " send=" + called.send);
reset();
handler(ev("Enter", { isComposing: true }));
ok("but an Enter that is accepting an IME candidate does not", called.insertMention === 0, "insert=" + called.insertMention);
reset();
handler(ev("Enter", { keyCode: 229 }));
ok("...nor does the legacy 229 one", called.insertMention === 0, "insert=" + called.insertMention);
reset();
MP.open = false;

console.log("\n-- the guard is the first thing the handler does --");
reset();
handler(ev("ArrowDown", { isComposing: true }));
ok("a composing arrow key does not move the highlight", called.renderMention === 0, "render=" + called.renderMention);
MP.open = true; reset();
handler(ev("ArrowDown", { isComposing: true }));
ok("...even with the list open", called.renderMention === 0, "render=" + called.renderMention);
MP.open = false;

console.log(`\n${pass} ok, ${fail} failed`);
process.exit(fail ? 1 : 0);
