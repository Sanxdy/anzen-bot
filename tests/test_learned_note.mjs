/* A "learned" note arrives after its turn's own `done`, so it has no turn state to be drawn in. The
   watch path used to create one for any live event and only `done`/`error` ever removed it — a chat
   that received a note stayed "running" for ever and queued every later message. Run: node
   tests/test_learned_note.mjs */
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../app.js", import.meta.url), "utf8");
const start = src.indexOf("async function elsewhere(d) {");
const end = src.indexOf("\n}", start);
const body = src.slice(start, end + 2);

let pass = 0, fail = 0;
const ok = (name, cond, extra = "") => {
  if (cond) { pass++; console.log("  ok  " + name); }
  else { fail++; console.log("  FAIL " + name + (extra ? "  -> " + extra : "")); }
};

function harness() {
  const S = { active: "chat-a", turns: {}, myTurns: {} };
  const calls = { drew: [], ended: [], reloaded: 0, chats: 0, composed: 0 };
  const elsewhere = new Function(
    "d", "S", "loadChats", "select", "firstChatId", "drawTurnEvent", "endWatched", "reloadTranscript",
    "syncComposer",
    body + "\nreturn elsewhere;")(
    undefined, S,
    async () => { calls.chats++; }, async () => {}, () => "first",
    (sid, T, d) => calls.drew.push([sid, d.type, T]),
    async sid => calls.ended.push(sid),
    async () => { calls.reloaded++; },
    () => { calls.composed++; });
  return { S, calls, elsewhere };
}

console.log("\n-- a learned note is not a turn --");
{
  const { S, calls, elsewhere } = harness();
  await elsewhere({ type: "learned", session: "chat-a", agent: "qa", notes: ["x"] });
  ok("the note still reaches the transcript", calls.drew.length === 1 && calls.drew[0][1] === "learned");
  ok("...through a sink that is not a running turn", !calls.drew[0][2].running);
  ok("...and nothing is left in S.turns", !S.turns["chat-a"], JSON.stringify(S.turns));
}

console.log("\n-- another client's turn is still watched --");
{
  const { S, calls, elsewhere } = harness();
  await elsewhere({ type: "tool", session: "chat-a", turn: 7, name: "read_file" });
  ok("a live event still creates a watched turn", !!S.turns["chat-a"] && S.turns["chat-a"].running === true);
  ok("...and is drawn", calls.drew.length === 1);
  ok("...and the composer is re-synced, so Stop is offered for a turn this window did not start",
     calls.composed > 0);
  await elsewhere({ type: "done", session: "chat-a", turn: 7 });
  ok("...and its done hands the chat back", calls.ended[0] === "chat-a", JSON.stringify(calls.ended));
}

console.log("\n" + pass + " passed, " + fail + " failed\n");
process.exit(fail ? 1 : 0);
