/* Offline check for the Backup panel in app.js — no browser, no DOM lib, same extraction trick as
   tests/test_tablist.mjs.

   `tabBundle` is the whole feature's face: an export that is one link, and an import that reads a
   bundle and shows what is inside before it writes anything. app.js boots the whole UI as an ES
   module, so the function is read out of the source and run against fake nodes. If the extraction
   ever stops matching, these checks fail rather than pass on nothing.

   Run: node tests/test_bundle_tab.mjs   (exit 0 = all green) */
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

/* ---------- just enough DOM for el() and the panel's own tree ---------- */
const created = [];   // every node el() made, attached or not — a hidden file input is never appended
class Node {
  constructor(tag) {
    this.tag = tag; this.children = []; this.className = ""; this.style = {}; this.attrs = {};
    this.textContent = ""; this._html = ""; this.type = ""; this.href = ""; this.disabled = false;
    this.files = [];
  }
  set innerHTML(v) { this._html = v; this.children = []; }
  get innerHTML() { return this._html; }
  appendChild(n) { this.children.push(n); return n; }
  append(...ns) { for (const n of ns) this.children.push(n); }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener() {}
  click() {}
  get all() { return this.children.flatMap(c => [c, ...(c.all || [])]); }
  find(pred) { return this.all.find(pred); }
  findAll(pred) { return this.all.filter(pred); }
}
global.document = { createElement: t => { const n = new Node(t); created.push(n); return n; } };
global.FileReader = class { readAsDataURL() { this.result = "data:application/zip;base64,AA=="; this.onload(); } };
global.fetch = async () => ({ json: async () => ({ ok: true }) });

/* The helpers `tabBundle` leans on, in their simplest honest form. `svg` returns a marker so a card
   that forgot its icon is visible; `esc` is the real escaping rule. */
const realPost = slice("const post = (p, b) => fetch(", "\n/* One JSON reply from a POST.");
const realJpost = slice("const jpost = async (p, b) => {", "\n/* Inline line icons.");
const stubs = realPost + realJpost + `
const el = (t, c, h) => { const e = document.createElement(t); if (c) e.className = c; if (h != null) e.innerHTML = h; return e; };
const esc = s => (s == null ? "" : String(s)).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const svg = n => "[icon:" + n + "]";
const h3 = (p, t) => p.appendChild(el("h3", "", esc(t)));
const isOffline = () => false;
const reloadConfig = async () => {};
const draw = () => {};
const S = {};
`;
const block = slice("function tabBundle(p) {", "\nfunction tabPlugins(p) {");
const factory = new Function(stubs + block + "\nreturn tabBundle;");
const tabBundle = factory();

/* ---------- the tab is registered, in the right group ---------- */
const tabsSrc = slice("const TABS = [", "\n];") + "\n];";
const tabRows = [...tabsSrc.matchAll(/\["([a-z]+)", "([^"]+)", "([a-z]+)", "([^"]*)"\]/g)]
  .map(m => ({ id: m[1], label: m[2], icon: m[3], group: m[4] }));
const bundleRow = tabRows.find(t => t.id === "bundle");
ok("a Backup tab exists", !!bundleRow);
ok("it is called Backup", bundleRow && bundleRow.label === "Backup");
ok("it sits in Your workspace", bundleRow && bundleRow.group === "Your workspace");
ok("it is next to Rooms", tabRows.findIndex(t => t.id === "bundle") === tabRows.findIndex(t => t.id === "channels") + 1);
ok("its icon exists", bundleRow && src.includes("  " + bundleRow.icon + ":"));
ok("the panel is dispatched from the tab id", src.includes("bundle: tabBundle,"));

/* ---------- the panel builds, and offers the two halves ---------- */
const panel = new Node("div");
tabBundle(panel);
const link = panel.find(n => n.tag === "a");
ok("the panel draws an export link", !!link);
ok("it points at the export endpoint", link && link.href === "/api/workspace/export");
ok("it is a download, not a navigation", link && "download" in link.attrs);
const file = created.find(n => n.type === "file");
ok("it offers a file picker for import", !!file);
ok("the picker only takes zips", file && String(file.accept).includes("zip"));
const buttons = panel.findAll(n => n.tag === "button");
const label = n => n.textContent + " " + n.innerHTML;
ok("it has a button to open the picker", buttons.some(b => /Choose a bundle/.test(label(b))));
ok("nothing is shown as imported before anything happens",
   !panel.find(n => /Imported/.test(n.textContent)));

/* ---------- what it says it carries, and what it says it does not ---------- */
const words = panel.all.map(n => n.textContent + " " + n.innerHTML).join(" ");
ok("it names memory as carried", /memory notes/.test(words));
ok("it names avatars and faces as carried", /avatars/.test(words) && /faces/.test(words));
ok("it names skills as carried", /skills/.test(words));
ok("it names routines as carried", /routines/.test(words));
ok("it says the router key does not travel", /router address and its key/.test(words));
ok("it says browser profiles do not travel", /browser profiles/.test(words));

/* ---------- reading a bundle shows what is inside before writing ---------- */
const reads = [];
global.fetch = async (url, opts) => {
  reads.push({ url, body: JSON.parse(opts.body) });
  return { json: async () => ({ ok: true, at: "2026-10-25T12:00:00",
    counts: { bots: 7, channels: 2, sessions: 11, routines: 3, skills: 1, skill_files: 4,
              memory: 5, avatars: 2, faces: 6, logos: 1 } }) };
};
const picker = created.find(n => n.type === "file");
picker.files = [{ name: "workspace.zip" }];
await picker.onchange();
ok("choosing a file asks the server to read it, not to import it",
   reads.length === 1 && reads[0].url === "/api/workspace/inspect");
ok("the whole file is sent as a data URL", reads[0].body.data.startsWith("data:application/zip;base64,"));
const after = panel.all.map(n => n.textContent + " " + n.innerHTML).join(" ");
ok("the counts are shown before anything is written", /7 bots/.test(after) && /11 chats/.test(after));
ok("the pictures are counted together", /9 pictures/.test(after));   // 2 avatars + 6 faces + 1 logo
ok("both ways in are offered", /Add to what is here/.test(after) && /Replace what is here/.test(after));
ok("nothing was imported yet", !reads.some(r => r.url === "/api/workspace/import"));

console.log("\n" + pass + " ok, " + fail + " failed");
process.exit(fail ? 1 : 0);
