/* Offline checks for the `get()` helper and its callers in app.js — no browser, no DOM library.

   `get()` used to hand a failed request's body straight to `.json()`, so a 500, an HTML error page
   or a dropped connection rejected with a message about an unexpected token, and every call site had
   to catch and explain it. It now returns null on any failure — the one shape a caller can test for.
   app.js is an ES module that boots the whole UI, so it cannot be imported here; the helper is read
   out of the source and run against a stubbed `globalThis.fetch`, and the callers it now feeds are
   held to the null-safe shape by reading their own lines back out of the source.

   Run: node tests/test_fetch_helpers.mjs   (exit 0 = all green) */
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../app.js", import.meta.url), "utf8");
const slice = (from, to) => {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0 || b < a) { console.log("FAIL could not find " + from + " in app.js"); process.exit(1); }
  return src.slice(a, b);
};

let pass = 0, fail = 0;
const ok = (name, cond, extra = "") => {
  if (cond) { pass++; console.log("  ok   " + name); }
  else { fail++; console.log("  FAIL " + name + (extra ? "  -> " + extra : "")); }
};

/* ---------- the helper itself, run for real ----------
   The app's own `get`, closed over a fetch we control. Each scenario swaps globalThis.fetch and calls
   it once; what comes back is what every call site would get. */
const getSrc = slice("const get = async p =>", "\nconst post = ");
const get = new Function(getSrc + "\nreturn get;")();
const fetchWith = stub => { globalThis.fetch = stub; };

console.log("\n-- a good reply is the JSON body --");
fetchWith(async () => ({ ok: true, json: async () => ({ text: "notes" }) }));
ok("an ok response resolves to its parsed body",
  JSON.stringify(await get("/api/x")) === JSON.stringify({ text: "notes" }));

console.log("\n-- a failure is null, never a throw --");
fetchWith(async () => ({ ok: false, status: 500 }));
ok("a 500 is null", (await get("/api/x")) === null);
fetchWith(async () => ({ ok: false, status: 404, json: async () => { throw new Error("no"); } }));
ok("a 404 is null too, without reaching .json()", (await get("/api/x")) === null);
fetchWith(async () => { throw new Error("connection dropped"); });
ok("a rejected fetch is null", (await get("/api/x")) === null);
/* The case the docstring names by hand: an ok status whose body is an HTML error page. `.json()`
   rejects, and the helper swallows it rather than letting the SyntaxError escape to the caller. */
fetchWith(async () => ({ ok: true, json: async () => { throw new SyntaxError("Unexpected token <"); } }));
ok("an ok response whose body is not JSON is null", (await get("/api/x")) === null);
delete globalThis.fetch;

/* ---------- the callers, held to the null-safe shape ----------
   The two loader lines sit inside closures that build a whole settings panel, so re-implementing the
   loader here would test a copy rather than the app. They are read back out of the sliced function
   instead: the assertion is that the app's own line guards the reply, which is exactly the change.
   `reloadConfig`, which is a plain function, is both read and run. */
console.log("\n-- the memory and log loaders guard the reply --");
const tabMemory = slice("function tabMemory(p) {", "\n/* --- Skills --- */");
ok("the memory loader reads (d || {}).text",
  /await get\("\/api\/memory[\s\S]*?\(d \|\| \{\}\)\.text/.test(tabMemory),
  (tabMemory.match(/await get\("\/api\/memory[^\n]*/) || [""])[0]);
ok("the work-log loader reads (d || {}).text",
  /await get\("\/api\/bot\/log[\s\S]*?\(d \|\| \{\}\)\.text/.test(tabMemory),
  (tabMemory.match(/await get\("\/api\/bot\/log[^\n]*/) || [""])[0]);

console.log("\n-- reloadConfig returns early on a null config --");
const rcSrc = slice("async function reloadConfig() {", "\n\n/* ---------------- computer panel");
ok("the early return is written down", /const cfg = await get\(\"\/api\/config\"\);\s*[\s\S]*?if \(!cfg\) return;/.test(rcSrc));
/* Run it, too: with get() giving null, nothing downstream may be touched. That is the whole point of
   the early return — a failed reload leaves the last good config in place rather than blanking it. */
const touched = { applied: 0, nav: 0, chats: 0 };
const S = { bots: ["keep"], channels: ["keep"], settings: {} };
const reloadConfig = new Function("get", "S", "applyAppearance", "renderNav", "loadChats",
  '"use strict";' + rcSrc + "\nreturn reloadConfig;")(
  async () => null, S,
  () => { touched.applied++; }, () => { touched.nav++; }, () => { touched.chats++; });
await reloadConfig();
ok("a null config leaves S untouched", S.bots[0] === "keep" && S.channels[0] === "keep");
ok("...and redraws nothing", touched.applied === 0 && touched.nav === 0 && touched.chats === 0,
  JSON.stringify(touched));

console.log(`\n${pass} ok, ${fail} failed`);
process.exit(fail ? 1 : 0);
