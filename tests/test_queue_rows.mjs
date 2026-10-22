/* Offline checks for the queued-task rows in app.js — no browser, no DOM lib.

   #queue is `role="status" aria-live="polite"`, so a redraw that clears the container and re-adds
   every row reads the whole queue out again on each change. The rows are therefore keyed by task id
   and edited in place; these checks pin down that the existing rows really are kept (not rebuilt),
   that a change touches only the row it belongs to, and that the head/hint stay where they belong.
   app.js is an ES module that boots the whole UI, so it cannot be imported here; `renderQueue` is
   read out of the source and run against fake nodes. If the extraction stops matching, these fail
   rather than pass on nothing.

   Run: node tests/test_queue_rows.mjs   (exit 0 = all green) */
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../app.js", import.meta.url), "utf8");
const slice = (from, to) => {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0 || b < a) { console.log("FAIL could not find " + from + " in app.js"); process.exit(1); }
  return src.slice(a, b);
};
const block = slice("const QROWS = new Map();", "/* Remove one queued task by its stable id");

let pass = 0, fail = 0;
const ok = (name, cond, extra = "") => {
  if (cond) { pass++; console.log("  ok   " + name); }
  else { fail++; console.log("  FAIL " + name + (extra ? "  -> " + extra : "")); }
};

/* A node is its children, its class and its text; removing it detaches it from its parent, which is
   the one thing a reconcile has to get right. */
function node(tag) {
  const n = { tagName: tag, className: "", textContent: "", title: "", children: [], parentNode: null,
    set innerHTML(h) { for (const c of this.children) c.parentNode = null; this.children = []; this._html = h; },
    get innerHTML() { return this._html; },
    appendChild(c) { if (c.parentNode) c.remove(); c.parentNode = this; this.children.push(c); return c; },
    insertBefore(c, ref) { if (c.parentNode) c.remove(); c.parentNode = this;
      const i = this.children.indexOf(ref);
      i < 0 ? this.children.push(c) : this.children.splice(i, 0, c); return c; },
    remove() { const p = this.parentNode; if (p) { const i = p.children.indexOf(this); if (i >= 0) p.children.splice(i, 1); }
      this.parentNode = null; },
    setAttribute(k, v) { this.attrs = { ...this.attrs, [k]: String(v) }; } };
  return n;
}
const box = node("div");
const S = { active: "a", queue: {} };
const $ = sel => (sel === "#queue" ? box : null);
const el = (t, c, h) => { const n = node(t); if (c) n.className = c; if (h != null) n.innerHTML = h; return n; };
const R = new Function("$", "el", "S", "steerNow", '"use strict";\n' + block + "\nreturn renderQueue;")( $, el, S, () => {});

const kinds = () => box.children.map(c => c.className + ":" + c.children.map(k => k.className).join(",")).join(" | ");
const row = id => box.children.find(c => c.className === "qitem" && c.children[0].textContent === id);

console.log("\n-- a fresh queue --");
S.queue.a = [{ id: 1, text: "one", opts: {} }, { id: 2, text: "two", opts: {} }];
R();
ok("head, the rows, then the hint", kinds() === "qhead: | qitem:qtext,qsteer,qx | qitem:qtext,qsteer,qx | qhint:",
  kinds());
const head = box.children[0], one = row("one"), two = row("two"), hint = box.children[3];
ok("the head counts the tasks", head.textContent === "2 tasks queued", head.textContent);

console.log("\n-- a change is an edit, not a rebuild --");
S.queue.a.push({ id: 3, text: "three", opts: {} });
R();
ok("the rows already drawn are the same nodes", box.children[0] === head && box.children[1] === one && box.children[2] === two);
ok("the new row lands before the hint", box.children[3] !== hint && box.children[4] === hint);
ok("the head follows", head.textContent === "3 tasks queued", head.textContent);

S.queue.a[1].steering = true;
R();
ok("a steered row trades its button for a note", two.children.map(k => k.className).join(",") === "qtext,qnote,qx",
  two.children.map(k => k.className).join(","));
ok("...and the row beside it is not touched", one.children.map(k => k.className).join(",") === "qtext,qsteer,qx");
R();
ok("drawing the same state twice changes nothing", two.children.map(k => k.className).join(",") === "qtext,qnote,qx");

console.log("\n-- removal and an empty queue --");
S.queue.a.splice(0, 1);
R();
ok("a dropped task takes only its row", box.children.length === 4 && box.children[1] === two, kinds());
S.queue.a[0].steering = false; R();
ok("un-steering puts the button back", two.children.map(k => k.className).join(",") === "qtext,qsteer,qx",
  two.children.map(k => k.className).join(","));

S.queue.a = [];
R();
ok("an empty queue clears and hides the strip", box.children.length === 0 && box.hidden === true);

S.queue.a = [{ id: 4, text: "again", opts: {} }];
R();
ok("a queue after empty draws cleanly", kinds() === "qhead: | qitem:qtext,qsteer,qx | qhint:" && box.hidden === false, kinds());

console.log("\n-- switching chats --");
S.active = "b"; S.queue.b = [{ id: 5, text: "elsewhere", opts: { fwd: true } }];
R();
ok("another chat's queue replaces the rows", kinds() === "qhead: | qitem:qtext,qsteer,qx | qhint:", kinds());
ok("...with its own text", row("↪ elsewhere") !== undefined);

/* ---------- the queue outlives the tab ---------- */
/* A queued task is drawn as committed work, so a reload must not drop it. `queueSave`/`queueLoad` are
   lifted out and run against a stub storage: the round trip keeps text, opts and attachments, does
   not restore the in-flight `steering` mark, and a write that hits the quota leaves memory alone. */
console.log("\n-- the queue survives a reload --");
const persist = slice('const QKEY = "queue.tasks";', "/* Where a steer ends up");
const store = new Map();
const ls = { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) };
const harness = (queue, storage) => {
  const st = { queue };
  const f = new Function("S", "localStorage",
    "let _qid = 0;\n" + persist + "\nreturn { queueSave, queueLoad, qid: () => _qid };");
  return { st, f: f(st, storage) };
};
const att = { name: "shot.png", type: "image/png", data: "data:image/png;base64,AAAA" };
const first = harness({ a: [{ id: 7, text: "hello", opts: { attachments: [att] }, steering: true }] }, ls);
first.f.queueSave();
const second = harness({}, ls);
second.f.queueLoad();
ok("a saved task comes back in its chat", second.st.queue.a && second.st.queue.a.length === 1,
  JSON.stringify(second.st.queue));
ok("...with its text and attachments", second.st.queue.a[0].text === "hello"
  && second.st.queue.a[0].opts.attachments[0].data === att.data);
ok("...and no half-steered state", second.st.queue.a[0].steering === undefined);
ok("...and the id counter resumes past the restored ids, so a new task cannot take one",
  second.f.qid() === 7, String(second.f.qid()));
const failing = { getItem: () => null, setItem: () => { throw new Error("quota"); } };
const memory = { a: [{ id: 9, text: "still here", opts: {} }] };
ok("a write that hits the quota does not throw", (harness(memory, failing).f.queueSave(), true));
ok("...and leaves the task in memory, where it still runs", memory.a.length === 1 && memory.a[0].text === "still here");

console.log(`\n${pass} ok, ${fail} failed`);
process.exit(fail ? 1 : 0);
