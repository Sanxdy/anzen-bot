/* Offline checks for the transcript's row dispatch in app.js — no browser, no DOM library.

   A saved transcript is a list of rows, and which drawing each row gets is the whole question here:
   a `tool` row is a step, a `route` row is the hand-off card, a `notice` row is a stop this app
   caused, and everything else is a message. The bug this pins is that a notice was only ever drawn
   live — the card existed while the turn ran and the redraw at the end wiped it, so reopening a chat
   showed the work and not one word of why. A notice that reaches the redraw must not fall through to
   the message branch, which would draw it as a bot bubble named after nothing.

   app.js boots the whole UI, so it cannot be imported here; the dispatch block is read out of the
   source and run against recording stubs. If the extraction ever stops matching, these checks fail
   rather than pass on nothing.

   Run: node tests/test_notice_row.mjs   (exit 0 = all green) */
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../app.js", import.meta.url), "utf8");
const a = src.indexOf("messages.forEach((m, i) => {");
const b = src.indexOf("\n  if (pending) addApproval(", a);
if (a < 0 || b < 0 || b < a) { console.log("FAIL could not find the row dispatch in app.js"); process.exit(1); }
const body = src.slice(a, b);

let pass = 0, fail = 0;
const ok = (name, cond, extra = "") => {
  if (cond) { pass++; console.log("  ok   " + name); }
  else { fail++; console.log("  FAIL " + name + (extra ? "  -> " + extra : "")); }
};

/* Recording stand-ins: each drawing the dispatch can choose pushes its own name, so the check is
   which one ran and with what, not that some markup came out. */
const draw = (rows) => {
  const calls = [];
  const addCard = (...x) => calls.push(["card", ...x]);
  const addMsg = (...x) => calls.push(["msg", ...x]);
  const addTool = (...x) => calls.push(["tool", ...x]);
  const S = { active: "chat-1", failNotes: {} };
  new Function("messages", "addCard", "addMsg", "addTool", "cleanBot", "ROUTE_LABEL", "S", "sink", body)(
    rows, addCard, addMsg, addTool, s => String(s == null ? "" : s), "Who's on it", S, null);
  return calls;
};

let c = draw([{ role: "notice", content: "the model stopped answering" }]);
ok("a saved notice is drawn as a system card, not a message",
   c.length === 1 && c[0][0] === "card" && c[0][1] === "sys" && c[0][3] === "the model stopped answering",
   JSON.stringify(c));

c = draw([{ role: "sys", content: "compressed 12 earlier steps" }]);
ok("the app's own note is drawn the same way", c.length === 1 && c[0][0] === "card" && c[0][1] === "sys",
   JSON.stringify(c));

c = draw([{ role: "tool", agent: "atlas", name: "run_shell", args: {}, out: "exit 0" }]);
ok("a tool row still draws as a step", c.length === 1 && c[0][0] === "tool", JSON.stringify(c));

c = draw([{ role: "route", content: "→ Atlas" }]);
ok("a hand-off still draws as the plan card", c.length === 1 && c[0][0] === "card" && c[0][1] === "plan",
   JSON.stringify(c));

c = draw([{ role: "user", content: "hello" }, { role: "assistant", who: "Atlas", content: "hi" }]);
ok("ordinary messages still draw as messages",
   c.length === 2 && c[0][0] === "msg" && c[1][0] === "msg" && c[0][1] === "user",
   JSON.stringify(c));

console.log(`\n  ${pass} ok, ${fail} failed`);
process.exit(fail ? 1 : 0);
