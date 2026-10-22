/* Offline checks for the service worker (sw.js) — no browser, no real Cache API.

   sw.js is a plain classic script, so it cannot be imported; it is loaded whole against fakes and its
   three listeners are captured. What it has to get right is the shape of the fallback: a failed
   request may only fall back to the shell when it is a navigation — handing index.html to the module
   loader in place of app.js is a syntax error and the app never boots — and a transient 500 must
   never be cached and served as the app afterwards.

   Run: node tests/test_service_worker.mjs   (exit 0 = all green) */
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../sw.js", import.meta.url), "utf8");

let pass = 0, fail = 0;
const ok = (name, cond, extra = "") => {
  if (cond) { pass++; console.log("  ok   " + name); }
  else { fail++; console.log("  FAIL " + name + (extra ? "  -> " + extra : "")); }
};

/* ---------- the fakes sw.js runs against ----------
   `self` records the three listeners; `caches` is a two-line Map with the four methods the worker
   uses; `Response` is only ever asked for `error()`, which is the marker a fallback must not be. */
const listeners = {};
const added = new Set(), put = [];
let skipped = 0, addFails = null;
const store = new Map();
const cache = {
  add: f => { if (f === addFails) return Promise.reject(new Error("404")); added.add(f); return Promise.resolve(); },
  put: (req, res) => { put.push([req, res]); return Promise.resolve(); },
  match: f => Promise.resolve(added.has(f) ? { marker: f } : null),
};
const caches = {
  open: () => Promise.resolve(cache),
  match: req => Promise.resolve(store.get(typeof req === "string" ? req : req.url) || null),
  keys: () => Promise.resolve([]),
  delete: () => Promise.resolve(true),
};
const RESPONSE_ERROR = { marker: "Response.error()" };
const Response = { error: () => RESPONSE_ERROR };
const self = {
  addEventListener: (t, fn) => { listeners[t] = fn; },
  skipWaiting: () => { skipped++; return Promise.resolve(); }, clients: { claim: () => Promise.resolve() },
};
let fetchImpl = async () => { throw new Error("offline"); };
const fetchStub = (...a) => fetchImpl(...a);

new Function("self", "caches", "fetch", "Response", "Request", "URL",
  '"use strict";' + src)(self, caches, fetchStub, Response, {}, URL);

/* The handlers the worker installed. */
const install = listeners.install, activate = listeners.activate, onfetch = listeners.fetch;
if (!install || !activate || !onfetch) { console.log("FAIL sw.js installed no listeners"); process.exit(1); }

const ev = (request) => { const e = { request, responded: null, respondWith(p) { this.responded = p; } }; return e; };
const flush = () => new Promise(r => setImmediate(r));

console.log("\n-- install caches the shell --");
{
  let wait = null; install({ waitUntil: p => { wait = p; } }); await wait;
  ok("the shell is fetched file by file", added.size > 0, String(added.size));
  ok("./bridge.js is in the shell list", added.has("./bridge.js"), [...added].join(","));
  ok("./index.html is in the shell list", added.has("./index.html"));
  ok("./app.js is in the shell list", added.has("./app.js"));
  ok("a complete shell takes over", skipped === 1, String(skipped));
}

console.log("\n-- an incomplete install does not take over --");
{
  added.clear(); addFails = "./sound.js";
  const before = skipped;
  let wait = null; install({ waitUntil: p => { wait = p; } }); await wait;
  ok("one shell file that fails to cache keeps the old worker in charge", skipped === before, String(skipped));
  addFails = null;
}

console.log("\n-- only a real, same-origin 200 is cached --");
{
  put.length = 0;
  const good = { ok: true, type: "basic", clone: () => ({ copy: true }) };
  fetchImpl = async () => good;
  const e = ev({ url: "https://x/app.js", method: "GET", mode: "no-cors" });
  onfetch(e);
  const res = await e.responded; await flush();
  ok("the response is passed straight through", res === good);
  ok("an ok basic response is written to the cache", put.length === 1 && put[0][1].copy === true,
    String(put.length));
}
{
  put.length = 0;
  const bad = { ok: false, type: "basic", status: 500, clone: () => ({ copy: true }) };
  fetchImpl = async () => bad;
  const e = ev({ url: "https://x/app.js", method: "GET", mode: "no-cors" });
  onfetch(e);
  const res = await e.responded; await flush();
  ok("a 500 is returned to the caller, not swallowed", res === bad);
  ok("...and is never cached", put.length === 0, String(put.length));
}
{
  put.length = 0;
  const opaque = { ok: true, type: "opaque", clone: () => ({ copy: true }) };
  fetchImpl = async () => opaque;
  const e = ev({ url: "https://elsewhere/x.js", method: "GET", mode: "no-cors" });
  onfetch(e); await e.responded; await flush();
  ok("a cross-origin (opaque) response is not cached either", put.length === 0, String(put.length));
}

console.log("\n-- network-first: a warm cache never wins over a live network --");
{
  put.length = 0;
  store.clear(); store.set("https://x/app.js", { marker: "stale-app.js" });
  const fresh = { ok: true, type: "basic", clone: () => ({ copy: true }) };
  fetchImpl = async () => fresh;
  const e = ev({ url: "https://x/app.js", method: "GET", mode: "no-cors" });
  onfetch(e);
  const res = await e.responded; await flush();
  ok("the live response is served, not the cached copy", res === fresh, JSON.stringify(res));
  ok("...and the fresh copy replaces the cached one", put.length === 1, String(put.length));
}

console.log("\n-- offline: a navigation falls back to the shell --");
{
  store.clear(); store.set("./index.html", { marker: "index.html" });
  fetchImpl = async () => { throw new Error("offline"); };
  const e = ev({ url: "https://x/anything", method: "GET", mode: "navigate" });
  onfetch(e);
  const res = await e.responded;
  ok("a navigation with nothing cached gets index.html", res === store.get("./index.html"), JSON.stringify(res));
}

console.log("\n-- offline: a subresource does not --");
{
  store.clear(); store.set("./index.html", { marker: "index.html" });   // even with the shell cached
  fetchImpl = async () => { throw new Error("offline"); };
  const e = ev({ url: "https://x/mochi.js", method: "GET", mode: "no-cors" });
  onfetch(e);
  const res = await e.responded;
  ok("a subresource gets Response.error(), never index.html", res === RESPONSE_ERROR, JSON.stringify(res));
}
{
  store.clear(); store.set("https://x/mochi.js", { marker: "cached-mochi" });
  fetchImpl = async () => { throw new Error("offline"); };
  const e = ev({ url: "https://x/mochi.js", method: "GET", mode: "no-cors" });
  onfetch(e);
  const res = await e.responded;
  ok("but a cached subresource is served from the cache", res === store.get("https://x/mochi.js"));
}

console.log("\n-- the API and non-GETs are left alone --");
{
  fetchImpl = async () => { throw new Error("should not be called"); };
  const a = ev({ url: "https://x/api/state", method: "GET", mode: "no-cors" });
  onfetch(a);
  ok("an /api/ GET is not intercepted at all", a.responded === null);
  const p = ev({ url: "https://x/api/state", method: "POST", mode: "no-cors" });
  onfetch(p);
  ok("a non-GET is not intercepted", p.responded === null);
}

console.log(`\n${pass} ok, ${fail} failed`);
process.exit(fail ? 1 : 0);
