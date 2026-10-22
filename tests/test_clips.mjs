/* Offline checks for the clip lookup in app.js — no browser.

   A preset's clips are asked for once, not once per redraw: `dockFace` runs on every navigation
   repaint, and a fetch there would put a request on every keystroke in a sidebar name. What is pinned
   is that the request happens once per preset, that a preset with no clips is remembered as having
   none, that a failure is not retried in a loop, and that a reply which lands after the chat changed
   only reaches a face still wearing that preset.

   Run: node tests/test_clips.mjs   (exit 0 = all green) */
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../app.js", import.meta.url), "utf8");
const a = src.indexOf("const NO_CLIPS = Object.freeze({});");
const b = src.indexOf("/* A row's face outlives the list it sits in.");
if (a < 0 || b < a) { console.log("FAIL could not find the clip lookup in app.js"); process.exit(1); }
const block = src.slice(a, b);

let pass = 0, fail = 0;
const ok = (name, cond, extra = "") => {
  if (cond) { pass++; console.log("  ok   " + name); }
  else { fail++; console.log("  FAIL " + name + (extra ? "  -> " + extra : "")); }
};

const make = (reply, S = { dock: null, compFace: null }) => {
  const asked = [];
  const get = p => { asked.push(p); return reply(p); };
  const lookOf = b => ({ preset: (b && b.preset) || "", image: (b && b.image) || "" });
  const api = new Function("get", "S", "lookOf", block + "\nreturn { clipsFor, clipKeyFor };")
    (get, S, lookOf);
  return { ...api, asked, S };
};
const settle = () => new Promise(r => setTimeout(r, 0));

console.log("-- a preset's clips are asked for once --");
{
  const { clipsFor, asked } = make(async () => ({ ok: true, clips: { idle: "/api/clip/cat/idle.webm" } }));
  const first = clipsFor("cat");
  ok("the first call answers with nothing while the list is in flight", Object.keys(first).length === 0);
  ok("...and asks the server once", asked.length === 1 && asked[0] === "/api/clips/cat", asked.join());
  clipsFor("cat"); clipsFor("cat");
  ok("a redraw does not ask again", asked.length === 1, asked.length + " requests");
  await settle();
  const now = clipsFor("cat");
  ok("once the list lands it is what the face gets", now.idle === "/api/clip/cat/idle.webm", JSON.stringify(now));
  ok("...without a second request", asked.length === 1);
}

console.log("\n-- a preset with no clips, and one that could not be asked --");
{
  const { clipsFor, asked } = make(async () => ({ ok: true, clips: {} }));
  clipsFor("plain"); await settle();
  ok("a preset with no clips is remembered as having none",
     Object.keys(clipsFor("plain")).length === 0 && asked.length === 1);
  const dead = make(async () => null);
  dead.clipsFor("gone"); await settle();
  dead.clipsFor("gone"); dead.clipsFor("gone");
  ok("a failed lookup is not retried on every redraw", dead.asked.length === 1, dead.asked.length + " requests");
  ok("...and it leaves the face on its frames", Object.keys(dead.clipsFor("gone")).length === 0);
}

console.log("\n-- a late answer goes to a face that still wears it --");
{
  let release;
  const { clipsFor, S } = make(() => new Promise(r => { release = r; }));
  const dock = { preset: "cat", clips: {}, _clipKey: "cat" };
  const panel = { preset: "dog", clips: {}, _clipKey: "dog" };
  S.dock = dock; S.compFace = panel;
  clipsFor("cat");
  await settle(); release({ ok: true, clips: { idle: "/api/clip/cat/idle.webm" } });
  await settle();
  ok("the face still wearing that preset takes the clips", dock.clips.idle === "/api/clip/cat/idle.webm",
     JSON.stringify(dock.clips));
  ok("...and one wearing another preset is left alone", Object.keys(panel.clips).length === 0);
}

console.log("\n-- which set a face plays --");
{
  const { clipKeyFor } = make(async () => null);
  ok("a preset plays its own clips", clipKeyFor({ preset: "cat" }) === "cat");
  ok("the drawn mascot plays the shared set", clipKeyFor({ preset: "" }) === "mochi");
  ok("...and so does a room, which has no bot at all", clipKeyFor(null) === "mochi");
  ok("a bot with a picture of its own keeps it", clipKeyFor({ preset: "", image: "/api/avatar/x?v=1" }) === "");
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
