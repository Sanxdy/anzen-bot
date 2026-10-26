/* Offline checks for the ways a turn can end badly in app.js — no browser, no DOM library.

   Three defects, one theme: the client treating "no more bytes" as "the turn finished". A server that
   dies mid-turn closes the socket exactly as a finished turn does, so only the explicit `done` event
   may count as success; a failed turn must not then hand the queue its next task (which would fail
   the same way and take the one after it); and a settings write that the server refused must not be
   reported as saved. app.js boots the whole UI, so it cannot be imported here; each block is read out
   of the source and run against stubs. If an extraction stops matching, these fail rather than pass
   on nothing.

   Run: node tests/test_turn_failures.mjs   (exit 0 = all green) */
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

/* ---------- the stream, run for real ----------
   The app's own `isOffline`/`offlineTurn`/`stream`, closed over a fetch and a reader we control. */
const streamSrc = slice("const NET_RE =", "/* One place that puts a message");
const makeStream = fetchStub =>
  new Function("fetch", streamSrc + "\nreturn stream;")(fetchStub);
const readerOf = chunks => {
  let i = 0;
  return {
    read: async () => i < chunks.length
      ? { done: false, value: new TextEncoder().encode(chunks[i++]) }
      : { done: true, value: undefined },
    cancel() {},
  };
};
const respond = chunks => async () => ({ ok: true, body: { getReader: () => readerOf(chunks) } });
const sse = obj => "data: " + JSON.stringify(obj) + "\n\n";
const settle = p => p.then(v => ({ value: v }), e => ({ error: e }));

console.log("\n-- a clean EOF before the answer is not a finished turn --");
{
  /* Nothing was delivered: no `final`, no `done`. The server died or the socket dropped mid-turn, and
     the turn must say so rather than pass for finished. */
  const stream = makeStream(respond([sse({ type: "status", state: "working" })]));
  const T = {};
  const seen = [];
  const r = await settle(stream("/api/chat", {}, ev => seen.push(ev.type), T));
  ok("the events that did arrive are still drawn", seen.join() === "status");
  ok("the turn fails instead of passing for done", !!r.error && r.error.human === true,
    String(r.error && r.error.message));
  ok("...with the words for a stream that dropped part-way",
    !!r.error && /dropped part-way/.test(r.error.message));
}

console.log("\n-- an answer that arrived is not a failed turn --");
{
  /* The stream can end a beat before its `done`: a refresh, a closed tab, a proxy trimming the tail.
     The answer is on screen, so a red "the turn failed" card under it would be a lie — and it was
     exactly what a delivered turn looked like before `sawFinal` was tracked. */
  const stream = makeStream(respond([sse({ type: "final", text: "hi" })]));
  const r = await settle(stream("/api/chat", {}, () => {}, {}));
  ok("a turn whose answer arrived resolves", !r.error, String(r.error && r.error.message));
}

console.log("\n-- the server's own `done` still finishes it --");
{
  const stream = makeStream(respond([sse({ type: "final", text: "hi" }), sse({ type: "done" })]));
  const r = await settle(stream("/api/chat", {}, () => {}, {}));
  ok("a turn that ends with `done` resolves", !r.error, String(r.error && r.error.message));
}

console.log("\n-- a turn you stopped is not an error --");
{
  const stream = makeStream(respond([]));
  const T = { stopped: true };
  const r = await settle(stream("/api/chat", {}, () => {}, T));
  ok("a stopped turn ending without `done` resolves", !r.error, String(r.error && r.error.message));
}

console.log("\n-- a silent connection is failed, not waited on for ever --");
{
  let fire = null;
  const realSet = globalThis.setTimeout;
  globalThis.setTimeout = fn => { fire = fn; return 1; };
  try {
    let open;
    const reader = { read: () => new Promise(r => { open = r; }), cancel() { open({ done: true }); } };
    const stream = makeStream(async () => ({ ok: true, body: { getReader: () => reader } }));
    const p = settle(stream("/api/chat", {}, () => {}, {}));
    await new Promise(r => realSet(r, 0));      // let it reach its first read
    ok("a watchdog was armed", typeof fire === "function");
    fire();                                     // the silence outlasts it
    const r = await p;
    ok("the dead connection fails the turn", !!r.error && r.error.human === true,
      String(r.error && r.error.message));
  } finally { globalThis.setTimeout = realSet; }
}

/* ---------- a failed turn leaves the queue where it was ----------
   Both drain-on-end paths are read back out of `runChat`'s finally and run with a recording
   `drainQueue`, so what is asserted is the app's own guard, not a copy of it. */
console.log("\n-- a failed turn does not drain the queue --");
const drainTail = slice("    /* Whatever was typed into *this* chat", "\n  }\n}\n/* Redraw the transcript");
const runTail = (T, waiting, drained) =>
  new Function("T", "waiting", "sid", "drainQueue", drainTail)(T, waiting, "chat-a", s => drained.push(s));
{
  const drained = [];
  runTail({ failed: true }, false, drained);
  ok("a failed turn drains nothing", drained.length === 0, JSON.stringify(drained));
  runTail({}, false, drained);
  ok("a good turn drains its own chat", drained.join() === "chat-a", JSON.stringify(drained));
  const waitingDrained = [];
  runTail({}, true, waitingDrained);
  ok("a plan still waiting on your go drains nothing", waitingDrained.length === 0);
}

const subsLoop = slice("    for (const s of (T.subs || [])) {", "    /* Whatever was typed into *this* chat");
const runSubs = (T, drained) => new Function("T", "S", "select", "drainQueue", subsLoop)(
  T, { turns: { "chat-b": {}, "chat-c": {} }, active: "chat-a" }, () => {}, s => drained.push(s));
{
  const drained = [];
  runSubs({ failed: true, subs: ["chat-b", "chat-c"] }, drained);
  ok("a failed room turn drains none of its members' queues", drained.length === 0, JSON.stringify(drained));
  runSubs({ subs: ["chat-b", "chat-c"] }, drained);
  ok("a good room turn still drains them", drained.join() === "chat-b,chat-c", JSON.stringify(drained));
}

/* ---------- the settings write says what the server said ---------- */
console.log("\n-- a refused save is reported, not called saved --");
const saveSrc = slice("const saveSettings = async patch =>", "\n\n/* --- General --- */");
const makeSave = reply => new Function("jpost", "S", "applyAppearance", saveSrc + "\nreturn saveSettings;")(
  async () => reply, { settings: {} }, () => {});
{
  const refused = await makeSave({ ok: false, error: "disk is full" })({ appearance: {} });
  ok("saveSettings hands the refusal back", refused.ok === false && refused.error === "disk is full",
    JSON.stringify(refused));
}

const onClickSrc = slice("  save.onclick = async () => { const r = await saveSettings({ appearance:",
  "\n  row.appendChild(save);");
const runSaveClick = reply => {
  const save = { textContent: "Save" };
  new Function("saveSettings", "save", "cur", "acc", "setTimeout", onClickSrc)(
    async () => reply, save, () => ({}), { value: "#fff" }, () => 1);
  return save;
};
{
  const saved = runSaveClick({ ok: true });
  await saved.onclick();
  ok("a save that landed says Saved", saved.textContent === "Saved", saved.textContent);
  const refused = runSaveClick({ ok: false, error: "disk is full" });
  await refused.onclick();
  ok("a save the server refused says why", refused.textContent === "disk is full", refused.textContent);
}

console.log(`\n${pass} ok, ${fail} failed`);
process.exit(fail ? 1 : 0);
