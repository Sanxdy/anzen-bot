/* Offline checks for the blob swap in bridge.js — no browser, no real object URLs.

   In the desktop app a channel logo is an `<img src="/api/logo/…">`, which an image element fetches
   itself — and on a page loaded from disk that goes nowhere. bridge.js fetches such images over its
   own channel and swaps the element to a blob URL. A re-swap replaces the source, so the previous
   blob URL is revoked rather than leaked. bridge.js is an IIFE that returns early in a browser, so it
   is loaded whole against fakes that stand in for the desktop app, and the swap is driven through the
   observer bridge.js itself installs. If the extraction ever stops matching, these checks fail rather
   than pass on nothing.

   Run: node tests/test_bridge_blob.mjs   (exit 0 = all green) */
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../bridge.js", import.meta.url), "utf8");

let pass = 0, fail = 0;
const ok = (name, cond, extra = "") => {
  if (cond) { pass++; console.log("  ok   " + name); }
  else { fail++; console.log("  FAIL " + name + (extra ? "  -> " + extra : "")); }
};

/* ---------- the fakes bridge.js runs against ----------
   `window.anzen` must exist or the file returns at line 13, which is the whole point of it. The
   MutationObserver captures the callback and the observe() calls — the swap is driven through them,
   so the swap under test is the one bridge.js wired, not a copy of it. */
let moCallback = null;
const observed = [];
class MutationObserver { constructor(fn) { moCallback = fn; } observe(root, opts) { observed.push({ root, opts }); } }

const containers = { "#msgs": { id: "#msgs" }, "#side": { id: "#side" }, "#setPanel": { id: "#setPanel" } };
const documentElement = { id: "documentElement" };
const document = {
  documentElement,
  querySelector: sel => containers[sel] || null,
  querySelectorAll: () => [],
};

let created = 0, revoked = [];
const URLstub = { createObjectURL: () => "blob:" + (++created), revokeObjectURL: u => revoked.push(u) };
let fetchImpl = async () => ({ blob: async () => ({ bytes: true }) });
const fetchParam = (...a) => fetchImpl(...a);
const window = { anzen: { request: () => 1, abort: () => {} }, fetch: fetchParam };

new Function("window", "document", "MutationObserver", "fetch", "URL", "ReadableStream", "Response", "Request", "atob",
  '"use strict";' + src)(window, document, MutationObserver, fetchParam, URLstub,
  class {}, function () {}, function () {}, () => "");

if (!moCallback) { console.log("FAIL bridge.js installed no MutationObserver"); process.exit(1); }
const flush = () => new Promise(r => setImmediate(r));

/* A stand-in for a logo `<img>`: its src is readable both as a property and through getAttribute,
   which is the two ways the code touches it. */
const mkImg = src => ({
  dataset: {}, _src: src,
  get src() { return this._src; }, set src(v) { this._src = v; },
  getAttribute(k) { return k === "src" ? this._src : null; },
});
/* What the observer does when the app changes an element's src. */
const fireSrcChange = img => moCallback([{ type: "attributes", target: img }]);

console.log("\n-- the observer watches the three containers, not the whole document --");
ok("three containers are observed", observed.length === 3, String(observed.length));
const roots = observed.map(o => o.root.id);
ok("...and they are #msgs, #side and #setPanel",
  roots.join(",") === "#msgs,#side,#setPanel", roots.join(","));
ok("the document root is not one of them", !roots.includes("documentElement"));
ok("...so a scan does not run on every node of every turn",
  observed.every(o => o.opts.subtree && o.opts.childList && o.opts.attributes));
ok("...and only the src attribute wakes it", observed.every(o => String(o.opts.attributeFilter) === "src"));

console.log("\n-- the first swap makes one blob URL and keeps it --");
created = 0; revoked = [];
const img = mkImg("/api/logo/growth?v=1");
fireSrcChange(img); await flush();
ok("a blob URL is created", created === 1, String(created));
ok("...and becomes the element's source", img.src === "blob:1", img.src);
ok("...and is remembered on the element", img.dataset.anzenBlob === "blob:1", String(img.dataset.anzenBlob));
ok("...and nothing is revoked yet", revoked.length === 0, JSON.stringify(revoked));
ok("the element remembers the source so the observer ignores its own write", img.dataset.anzenSrc === "/api/logo/growth?v=1");

console.log("\n-- an src that is not ours is left alone --");
created = 0; revoked = [];
const cdn = mkImg("https://cdn.example.com/x.png");
fireSrcChange(cdn); await flush();
ok("a non-API image is never fetched or swapped", created === 0 && cdn.src === "https://cdn.example.com/x.png");

console.log("\n-- a re-swap revokes the previous URL, and only it --");
/* The mark exists so the observer ignores the swap's own src write. A genuine re-swap (a new logo,
   a new avatar) therefore clears it and writes the new source — that is the path the revoke is on. */
created = 0; revoked = [];
const logo = mkImg("/api/logo/growth?v=1");
fireSrcChange(logo); await flush();                       // first swap -> blob:1
delete logo.dataset.anzenSrc;                             // the element is re-marked for the new source
logo._src = "/api/logo/growth?v=2";
fireSrcChange(logo); await flush();                       // second swap -> blob:2
ok("the second swap makes a new blob URL", created === 2, String(created));
ok("...and the element now points at it", logo.src === "blob:2", logo.src);
ok("exactly one revoke happened", revoked.length === 1, JSON.stringify(revoked));
ok("...and it was the first URL, not the second", revoked[0] === "blob:1", JSON.stringify(revoked));
ok("...so the live URL is not the one revoked", !revoked.includes(logo.src));

console.log("\n-- the mark stops the observer from looping on its own write --");
created = 0; revoked = [];
const loop = mkImg("/api/logo/growth?v=1");
fireSrcChange(loop); await flush();                       // -> blob:1
fireSrcChange(loop); await flush();                       // the observer firing on that same write
ok("a second pass without a new source is a no-op", created === 1, String(created));
ok("...and revokes nothing", revoked.length === 0, JSON.stringify(revoked));

console.log(`\n${pass} ok, ${fail} failed`);
process.exit(fail ? 1 : 0);
