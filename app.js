/* app.js — Anzen-bot UI. Wires the canvas mascot to the real backend.
   Channels + bots as chats, layered settings, a computer panel, and voice. */
import { attach, detach, speciesFor, SPECIES, OUTFITS, ACCESSORIES } from "./mochi.js";
import { cue, unlock, CUE_FOR } from "./sound.js";

const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const el = (t, c, h) => { const e = document.createElement(t); if (c) e.className = c; if (h != null) e.innerHTML = h; return e; };
/* Make a div/span/li operable from the keyboard: Tab reaches it, Enter or Space fires it.
   Custom controls are built from divs, so without this they would be mouse-only. */
const kbd = (node, fn) => { node.tabIndex = 0; node.setAttribute("role", "button");
  node.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); fn(e); } };
  return node; };
/* Everything that goes into an innerHTML goes through here. The single quote is escaped too: the
   file's own attributes are double-quoted today, so it is not load-bearing yet, but it is the one
   character that turns a double-quoted attribute into a hole if anyone ever writes a single-quoted
   one — and the escape is free. */
const esc = s => (s == null ? "" : String(s)).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
/* The model lists in Settings and in the chat's model menu all match the same way — a case-insensitive
   substring of the id. One definition, so they cannot drift apart. */
const modelHits = q => S.models.filter(m => m.toLowerCase().includes(q.toLowerCase()));
/* Keep Tab inside a modal. Shared by the pick dialogs and Settings — both are `aria-modal`, so a Tab
   that walks out onto the page behind them is a lie. Focus that is already outside comes back in. */
const FOCUSABLE = 'button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
const trapTab = (box, e) => {
  const f = [...box.querySelectorAll(FOCUSABLE)];
  if (!f.length) return;
  const i = f.indexOf(document.activeElement);
  if (i === -1) { e.preventDefault(); (e.shiftKey ? f[f.length - 1] : f[0]).focus(); return; }
  if (e.shiftKey && i === 0) { e.preventDefault(); f[f.length - 1].focus(); }
  else if (!e.shiftKey && i === f.length - 1) { e.preventDefault(); f[0].focus(); }
};
/* The `.sk` rows are checkboxes: they pick a room's members, a bot's skills, its allowed tools and the
   apps in a skill pack. `kbd` made them focusable but announced them as plain buttons, so a screen
   reader could not tell a ticked row from an unticked one. This keeps the div (a row can hold a nested
   Remove button, which a real <button> may not) and gives it checkbox semantics. */
function skBox(html, on, change) {
  const d = el("div", "sk" + (on ? " on" : ""), html);
  d.tabIndex = 0; d.setAttribute("role", "checkbox");
  d.setAttribute("aria-checked", on ? "true" : "false");
  const flip = () => { const nv = !d.classList.contains("on"); d.classList.toggle("on", nv);
                       d.setAttribute("aria-checked", nv ? "true" : "false"); change(nv); };
  d.onclick = flip;
  d.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); flip(); } };
  return d;
}
/* True when a click landed inside one of `sel` — used by the popovers, which stay open for a click on
   themselves or on the chip that owns them and close on any other click. */
const inside = (e, sel) => !!(e && e.target && e.target.closest && e.target.closest(sel));
/* A failed GET comes back null, never a thrown parse error. A 500, an HTML error page or a dropped
   connection is not JSON, and `.json()` on it rejected with a message about an unexpected token —
   which every call site then had to catch and explain. Null is the one shape a caller can test for,
   and a caller that forgets gets a clean `Cannot read properties of null` at its own line rather
   than inside the helper. */
const get = async p => {
  try { const r = await fetch(p); return r.ok ? await r.json() : null; } catch (e) { return null; }
};
const post = (p, b) => fetch(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) });
/* One JSON reply from a POST. A crashed request (500, or an HTML error page) would otherwise surface
   as a bare JSON parse error at the call site, so it comes back in the same {ok:false, error} shape
   the API already uses for its own failures. */
const jpost = async (p, b) => {
  let r; try { r = await post(p, b); } catch (e) { return { ok: false, error: "cannot reach the server" }; }
  try { return await r.json(); } catch (e) { return { ok: false, error: "server error (" + r.status + ")" }; }
};
/* Inline line icons. Emoji never carry meaning on their own — every icon is
   paired with a visible text label. */
const ICON = {
  settings:'<circle cx="12" cy="12" r="3.2"/><path d="M12 2.6v3M12 18.4v3M2.6 12h3M18.4 12h3M5.4 5.4l2.1 2.1M16.5 16.5l2.1 2.1M18.6 5.4l-2.1 2.1M7.5 16.5l-2.1 2.1"/>',
  channels:'<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-5.4A8 8 0 1 1 21 12z"/>',
  bots:'<circle cx="9" cy="8" r="3.2"/><path d="M2.8 20a6.2 6.2 0 0 1 12.4 0"/><path d="M16.5 5.3a3.2 3.2 0 0 1 0 5.4M17.6 14.4A6.2 6.2 0 0 1 21.2 20"/>',
  router:'<rect x="7" y="7" width="10" height="10" rx="2"/><path d="M10 2.6v2.8M14 2.6v2.8M10 18.6v2.8M14 18.6v2.8M2.6 10h2.8M2.6 14h2.8M18.6 10h2.8M18.6 14h2.8"/>',
  models:'<path d="M12 3.4 20.4 8 12 12.6 3.6 8z"/><path d="M3.6 12 12 16.6 20.4 12"/><path d="M3.6 16 12 20.6 20.4 16"/>',
  approvals:'<path d="M12 2.7 4.5 6v6c0 4.5 3.2 7.8 7.5 9.3 4.3-1.5 7.5-4.8 7.5-9.3V6z"/>',
  memory:'<path d="M6 2.8h9l4 4V21H6z"/><path d="M15 2.8V7h4"/><path d="M9 12h7M9 16h5"/>',
  skills:'<path d="M12 3.2 13.6 8.4 18.8 10l-5.2 1.6L12 16.8l-1.6-5.2L5.2 10l5.2-1.6z"/><path d="M18.5 16.4l.7 2.1 2.1.7-2.1.7-.7 2.1-.7-2.1-2.1-.7 2.1-.7z"/>',
  plugins:'<path d="M9 2.8v5M15 2.8v5"/><path d="M6 7.8h12v4.2a6 6 0 0 1-12 0z"/><path d="M12 18v3.2"/>',
  apps:'<rect x="3.2" y="3.2" width="7.6" height="7.6" rx="1.6"/><rect x="13.2" y="3.2" width="7.6" height="7.6" rx="1.6"/><rect x="3.2" y="13.2" width="7.6" height="7.6" rx="1.6"/><rect x="13.2" y="13.2" width="7.6" height="7.6" rx="1.6"/>',
  voice:'<rect x="9" y="2.8" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3.2"/>',
  sound:'<path d="M4 9.4h3.3L12 5.4v13.2L7.3 14.6H4z"/><path d="M15.4 9.2a4.1 4.1 0 0 1 0 5.6"/><path d="M18.1 6.6a7.7 7.7 0 0 1 0 10.8"/>',
  appearance:'<path d="M12 3a9 9 0 1 0 0 18c1.4 0 2-.9 2-1.9 0-1.6 1-2.1 2.4-2.1H18a3 3 0 0 0 3-3A9 9 0 0 0 12 3z"/><circle cx="7.6" cy="11.5" r="1.1"/><circle cx="12" cy="7.6" r="1.1"/><circle cx="16.4" cy="11.5" r="1.1"/>',
  globe:'<circle cx="12" cy="12" r="8.6"/><path d="M3.4 12h17.2"/><path d="M12 3.4c3 3.5 3 13.7 0 17.2c-3-3.5-3-13.7 0-17.2z"/>',
  plus:'<path d="M12 5.5v13M5.5 12h13"/>',
  caret:'<path d="M9 5.5 15.5 12 9 18.5"/>',
  menu:'<path d="M3.5 6.5h17M3.5 12h17M3.5 17.5h17"/>',
  monitor:'<rect x="2.8" y="4.2" width="18.4" height="12.4" rx="2"/><path d="M9 20.4h6M12 16.6v3.8"/>',
  folder:'<path d="M3 7.4a1.6 1.6 0 0 1 1.6-1.6h4.2l2 2.4h7.6A1.6 1.6 0 0 1 20 9.8v8.2a1.6 1.6 0 0 1-1.6 1.6H4.6A1.6 1.6 0 0 1 3 18z"/>',
  file:'<path d="M6.5 2.8h7l4.5 4.5v13.9h-11.5z"/><path d="M13.5 2.8v4.5H18"/>',
  pin:'<path d="M9.2 3.6h5.6l-.9 4.8 3.4 3.4H5.9l3.4-3.4z"/><path d="M12 11.8v8.6"/>',
  edit:'<path d="M4 20.2h4l11-11a2.1 2.1 0 0 0-3-3l-11 11z"/><path d="M14.5 5.2l3 3"/>',
  copy:'<rect x="8.5" y="8.5" width="11.5" height="11.5" rx="2"/><path d="M4 15.5V5.5a2 2 0 0 1 2-2h10"/>',
  hide:'<path d="M2.5 12S6 5.5 12 5.5c1.5 0 2.8.4 4 1M21.5 12S18 18.5 12 18.5c-1.5 0-2.8-.4-4-1"/><path d="M3.2 3.2l17.6 17.6"/>',
  trash:'<path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13"/>',
  clear:'<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-5.4A8 8 0 1 1 21 12z"/><path d="M12 8.6v6.8M8.6 12h6.8"/>',
  warn:'<path d="M12 3.5 21 19.5H3z"/><path d="M12 9.5v4.5M12 17.2v.2"/>',
  speaker:'<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M15.5 9a4 4 0 0 1 0 6"/>',
  check:'<path d="M5 12.5 10 17.5 19.5 7"/>',
  eye:'<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
  help:'<circle cx="12" cy="12" r="9"/><path d="M9.4 9.4a2.7 2.7 0 0 1 5.2.9c0 1.8-2.6 2.3-2.6 4"/><path d="M12 17.4v.2"/>',
  phone:'<rect x="6.5" y="2.6" width="11" height="18.8" rx="2.4"/><path d="M10.4 5.4h3.2M12 18.4v.2"/>',
};
const svg = (n, cls) => `<svg class="${cls || ""}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[n] || ""}</svg>`;
/* Bot/channel avatars: the bot's emoji on its colour, else a coloured monogram.
   The six colours and how they are painted both come from Coucou, so a team here looks like the
   same team there: the hexes are Coucou's own agent palette (its project and fallback colours), and
   a small face is a flat fill of that colour rather than a white-washed gradient. */
const AV = { purple:"#7C5CFF", blue:"#38BDF8", green:"#2EC4A0", orange:"#F29B38", yellow:"#EAB308", pink:"#EC4899" };
const AVK = Object.keys(AV);
const initials = s => { const w = (s || "?").trim().split(/\s+/).filter(Boolean);
  if (!w.length) return "?";
  if (w.length > 1) return (w[0][0] + w[1][0]).toUpperCase();
  const camel = w[0].match(/[A-Z]?[a-z]+|[A-Z]+(?![a-z])/g) || [w[0]];
  return (camel.length > 1 ? camel[0][0] + camel[1][0] : w[0].slice(0, 2)).toUpperCase(); };
const colorFor = s => AVK[((s || "a").charCodeAt(0) + (s || "").length) % AVK.length];
/* The approval levels, in the one place they are written down: the bot editor, the Approvals tab and
   the header chip all read this, so a level cannot mean one thing in one screen and another elsewhere.
   `plan` is the strictest — the bot only investigates and reports a plan, and the chat is switched to
   full access when the user approves it. There is no "custom (config)" level: it configured nothing
   and behaved exactly like `ask`, because the server gates every level but `full` the same way. */
/* Each entry is [value, label, one-line, what-it-actually-does]. The fourth field is the honest
   detail — which tools it reaches and which actions stop to ask — and it is what the Approvals
   tab and the Help tour both render, so the level cannot be described one way in one screen and
   another way elsewhere. `auto` and `approve` say plainly that they behave like `ask` today. */
const APPROVALS = [
  ["plan",    "Plan only",          "Plan first, change nothing, and wait for your go-ahead. Approving runs it with full access.",
   "Read-only tools only: read a file, list files, open a page, read it, look at it. No shell command, no writing, no image, no delegation, no connected apps. The turn ends with a numbered plan and stops. Approving that plan switches this chat to Full access and runs it."],
  ["ask",     "Ask for approval",   "Cards for risky shell commands. Other tools run freely.",
   "Every tool is available. A shell command that is not a plain read-only one — it carries a shell character such as ; & | > or is not on the read-only list — raises an Allow/Deny card and the bot waits. File writes, browser actions, image generation, delegation and connected apps run without a card, so today the card covers risky shell commands only."],
  ["auto",    "Auto-accept edits",  "As Ask today; file writes are not gated yet.",
   "Runs exactly like Ask for now. It is reserved for the day file writes get their own gate; until then, picking it changes nothing about what runs."],
  ["approve", "Approve routine",   "Will approve routine actions on its own. As Ask today; nothing is split out yet.",
   "Runs exactly like Ask for now. It is reserved for a future split between routine and unusual actions; until then, picking it changes nothing about what runs."],
  ["full",    "Full access",        "Commands, edits and computer actions run without asking.",
   "No card is ever raised. Every tool the bot has — shell, files, browser, image, delegation, connected apps and MCP servers — runs straight away. This is the level a plan is approved into."],
];
const approvalLabel = v => (APPROVALS.find(a => a[0] === v) || APPROVALS[1])[1];
/* The chip has room for one word and already says "Approval:", so a level's own first word is not
   always usable — "Approval: Approve" says nothing at all. Each level gets the shortest name that
   still tells it apart; what it actually does is in the Approvals tab and the Help tour. */
const CHIP_WORD = { plan: "Plan", ask: "Ask", auto: "Auto-accept", approve: "Approve routine", full: "Full" };
const approvalChip = v => CHIP_WORD[v] || approvalLabel(v).split(" ")[0];
/* A company's logo, if it has one: an upload, else the logo found in its repo. The server sends a
   version that changes when the file does, so the image is fetched once and cached after that. */
const logoOf = c => c && c.logo ? `<img class="lg" src="/api/logo/${c.id}?v=${c.logo}" alt="">` : "";
const avatar = (name, color, cls, emoji, logo) => logo
  ? `<div class="mc img${cls ? " " + cls : ""}">${logo}</div>`
  /* The colour rides in a custom property as well as `color`, because the light theme has to
     darken it to stay readable on a near-white card and `color-mix(currentColor …)` cannot see
     an element's own colour — it would fall back to the inherited text colour and every
     monogram would come out the same grey. `--mc` is the one place the hue is written. */
  : `<div class="mc ${emoji ? "emo " : ""}${cls || ""}" style="--mc:${AV[color] || AV.blue};color:var(--mc)">${emoji ? esc(emoji) : esc(initials(name))}</div>`;
/* Per-bot animated faces in the sidebar: one small MochiBot canvas per row, filled with the bot's
   colour, all driven by the shared rAF loop.
   Each bot's species (shape, ears, eyes, idle motion) comes from its id, so a team
   of bots looks like a team — unless the bot names one explicitly in its `face`.
   Coucou paints a small bot as a flat fill of its colour — no gradient, no white wash — and that
   is what makes its team read as saturated rather than pastel, so we do the same. */
function sideFace(color) { return { flat: AV[color] || AV.blue }; }
/* What a bot is wearing, and the picture it has for a face: the things that are not its colour or
   its species. Kept in one place so every face the bot appears as — the sidebar row, the editor's
   preview, the dock, the computer panel — is dressed the same, the way `faceOf` keeps them all the
   same species. `avatar` is a version number, not a URL, so a new picture busts the cache. */
const avatarUrl = b => b && b.avatar ? `/api/avatar/${encodeURIComponent(b.id)}?v=${b.avatar}` : "";
const lookOf = b => ({ outfit: (b && b.outfit) || "", accessory: (b && b.accessory) || "", image: avatarUrl(b) });
/* The dock is the one big face, so it keeps Coucou's full grading — a soft body lit from the top —
   and that is also what carries the state: a flat fill has nowhere to put the working / searching
   tint, so a flat dock would stop telling you what the bot is doing. Only the colour changes here. */
const lift = (hex, k) => { const n = parseInt(hex.slice(1), 16);
  return "#" + [n >> 16 & 255, n >> 8 & 255, n & 255]
    .map(v => Math.round(v + (255 - v) * k).toString(16).padStart(2, "0")).join(""); };
function bigFace(color) { const c = AV[color] || AV.blue; return { bodyTop: lift(c, 0.44), bodyBottom: lift(c, 0.08) }; }
const faceOf = b => (b && b.face && SPECIES[b.face]) ? b.face : speciesFor(b && b.id);
function sideSet(id, st) {
  const m = S.sideMochi[id]; if (!m) return;
  if (m._idleTimer) { clearTimeout(m._idleTimer); m._idleTimer = null; }
  m.setState(st);                                     // invalid states fall back to idle inside MochiBot
  if (st === "finished") m._idleTimer = setTimeout(() => { m.setState("idle"); m._idleTimer = null; }, 3200);
}
const cleanBot = t => (t || "")
  .replace(/<<RUN>>[\s\S]*?<\/RUN>>/g, "").replace(/<<REMEMBER>>[\s\S]*?<\/REMEMBER>>/g, "")
  .replace(/<<(?:RUN|REMEMBER)>>[\s\S]*$/g, "").trim();
function dropEmpty() { const e = $("#msgs .empty"); if (e) e.remove(); }
/* Where a card goes. A card that is not part of a running turn lands in the transcript. A card the
   turn streams goes through that turn's own sink, which also remembers it — so when you switch to
   another chat the work is kept rather than destroyed, and switching back puts it on screen again. */
const nearBottom = m => m.scrollHeight - m.scrollTop - m.clientHeight < 80;
/* Whether new output follows the newest message. The reader's own scrolling is the only thing that
   turns it off. It is a flag rather than a measurement taken at the moment of the append, because by
   then the new node is already in the transcript: a message taller than the 80px band would push the
   gap past the threshold and read as "they scrolled up", so a long reply or a tool card would strand
   you at the top of it. */
let pinned = true;
/* A reader who scrolls back is paused, not switched off. Left off it stays off, and that is the whole
   of the reported bug: the transcript keeps growing, so the bottom moves away from anyone trying to
   reach it, and every message after that — yours and the bot's — is drawn below the fold with nothing
   to bring it back. So the pause is timed. It is restarted by each further scroll away from the bottom
   and cancelled by anything that puts the transcript at the bottom, so it only fires once the reader
   has actually stopped reading back.

   What it hands back is the *follow*, not a scroll. Firing used to drag the transcript to the bottom
   as well, and that is the second reported bug: the timer is armed whenever the reader has stopped
   short of the bottom, so reading back pulled them down a few seconds later with nothing having been
   sent — and pulled them down again on every further scroll, which is what made it read as the app
   polling. The trip down belongs to the next message, so this re-arms the follow and leaves the view
   where the reader put it; `stick` is the only thing that moves it, and only a message calls that. */
const RESUME_MS = 4000;
let resumeTimer = 0;
function holdFollow() {
  clearTimeout(resumeTimer);
  resumeTimer = setTimeout(() => { pinned = true; }, RESUME_MS);
}
/* Put the transcript at the bottom without animating the trip there. An animated follow would re-target
   on every append, and — worse for this — the browser fires a scroll event for each step of the
   animation, which lands at a position that still looks like a gap. Read as the reader scrolling away,
   that would switch the follow off in the middle of a stream. An instant write settles where it
   means to, so the "are they at the bottom?" test is honest. */
function toBottom(box) {
  const sb = box.style.scrollBehavior;
  box.style.scrollBehavior = "auto";
  box.scrollTop = box.scrollHeight;
  box.style.scrollBehavior = sb;
  /* A deliberate trip to the newest output — opening a chat, your own message, or the pill — is also a
     decision to follow it again, and it settles the pause rather than leaving a catch-up to fire
     under it later. */
  pinned = true;
  clearTimeout(resumeTimer);
}
/* Follow the stream only when the reader is at the bottom. If they scrolled up to re-read an earlier
   step, a new tool row or a token must not yank them back down — the pill appears instead. */
function stick(m) { if (pinned) toBottom(m); else $("#jump").hidden = false; }
/* Milestones for a screen reader. The transcript is `aria-live="off"` (it repaints every 120ms while
   a bot streams, so a live transcript would re-announce the whole answer dozens of times); this small
   region says only what changed. */
function announce(t) { const n = $("#live"); if (n) n.textContent = t; }
const MSGS = { add: n => { dropEmpty(); $("#msgs").appendChild(n); }, scroll: () => stick($("#msgs")) };
function turnSink(sid) {
  const T = S.turns[sid];
  /* Memoised on the turn state, not rebuilt per event: `addTool` remembers each row it has drawn on
     the sink so the second `tool` event for a call (the one carrying the output) fills that row
     rather than drawing a duplicate. A fresh sink per event meant that map was always empty, so every
     tool call drew twice — once stuck spinning, once finished. */
  return (T.sink = T.sink || {
    add: n => { T.nodes.push(n); if (sid === S.active) $("#msgs").appendChild(n); },
    scroll: () => { if (sid === S.active) MSGS.scroll(); },
    nodes: T.nodes,
    shown: () => sid === S.active });
}
/* A member's chat, while a room turn is running: it gets its own sink, so the work that bot is doing
   draws into its own chat if you are looking at it — and is put back if you switch to it. `T.subs`
   remembers which chats the turn opened, so they can be handed back to their history at the end. */
function subSink(T, sid) {
  if (!S.turns[sid]) { S.turns[sid] = { nodes: [], plan: null, running: true }; (T.subs = T.subs || []).push(sid); }
  return turnSink(sid);
}

/* ---------------- markdown ---------------- */
/* Bots answer in markdown, so a reply is rendered instead of shown raw. The text is escaped
   first and formatting is layered onto the escaped string, so a bot can never inject HTML.
   A link keeps its href only for http/https/mailto — a `javascript:` URL renders as inert text. */
const safeHref = u => (/^(https?:|mailto:|\/|#)/i.test(u) ? u : "#");
/* A sentence puts punctuation after a URL, and the URL does not own it: "see https://x.com." must not
   link the full stop. What is trimmed is handed back to the text rather than dropped, so the sentence
   still reads as it was written. A closing bracket is kept only when it closes one the URL itself
   opened, so a Wikipedia-style `..._(film)` survives while a URL inside a parenthetical does not
   swallow the bracket that ends it. */
function trimUrl(u) {
  let s = u.replace(/[.,;:!?]+$/, "");
  while (s.endsWith(")") && (s.match(/\(/g) || []).length < (s.match(/\)/g) || []).length) s = s.slice(0, -1);
  return s;
}
/* The one thing that writes an anchor, so a markdown link, a bare URL and a card's own link cannot
   drift apart. `href` is the only attribute a click is read from, and it is always filtered. */
const linkHtml = (t, u) => '<a class="lnk" href="' + safeHref(u) + '" target="_blank" rel="noopener noreferrer">' + (t || u) + "</a>";
/* A bare URL, in text that has already been escaped. `&` is allowed only as `&amp;`, so a query string
   survives (`?a=1&amp;b=2`) while a `&quot;` ending a sentence stops the match instead of being eaten. */
const BARE_URL = /(^|[\s(>])(https?:\/\/[^\s&<>"']*(?:&amp;[^\s&<>"']*)*)/g;
/* Autolink one match, keeping whatever trailing punctuation the URL only happened to be next to. */
function linkBare(pre, u) {
  const url = trimUrl(u);
  return pre + linkHtml(null, url) + u.slice(url.length);
}
/* A URL the *reader* typed is still a URL, so it is linked — but nothing else about a person's text is
   reformatted. Their message stays literal: a shell command with an asterisk must not come back italic. */
const linkify = s => esc(s || "").replace(BARE_URL, (m, pre, u) => linkBare(pre, u));
function inlineMd(s) {
  /* Code spans and markdown links are lifted out first: a `*` inside a code span stays literal, and
     the bare-URL pass below cannot match the URL inside a link that already has one. Both come back
     as finished HTML, so the restore is one substitution for either. */
  const held = [];
  const hold = h => "\uE000" + (held.push(h) - 1) + "\uE001";
  s = s.replace(/`([^`]+)`/g, (m, c) => hold("<code>" + c + "</code>"));
  s = s.replace(/\[([^\]]*)\]\(([^)\s]*)\)/g, (m, t, u) => hold(linkHtml(t, u)));
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
       .replace(/~~([^~]+)~~/g, "<del>$1</del>")
       .replace(/(^|[^*\w])\*([^*\n]+)\*/g, "$1<em>$2</em>")
       .replace(/(^|[^_\w])_([^_\n]+)_(?![\w])/g, "$1<em>$2</em>");
  /* A bare URL is what a bot actually writes — the transcripts hold hundreds of them and not one
     markdown link — so without this every URL in a reply is plain text and nothing is clickable. */
  s = s.replace(BARE_URL, (m, pre, u) => pre + hold(linkBare("", u)));
  return s.replace(/\uE000(\d+)\uE001/g, (m, i) => held[+i]);
}
function mdToHtml(text, escaped) {
  const lines = (escaped ? String(text || "") : esc(text || "")).replace(/\r\n?/g, "\n").split("\n");
  const out = []; let i = 0;
  const sep = s => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(s);
  const row = s => { let t = s.trim(); if (t.startsWith("|")) t = t.slice(1); if (t.endsWith("|")) t = t.slice(0, -1);
    return t.split("|").map(c => c.trim()); };
  const bullet = s => /^\s*([-*+]|\d+[.)])\s+/.test(s);
  while (i < lines.length) {
    const line = lines[i];
    const fence = line.match(/^\s*(```|~~~)\s*([\w+-]*)\s*$/);
    if (fence) {                                            // fenced code block
      const body = []; i++;
      while (i < lines.length && !new RegExp("^\\s*" + fence[1] + "\\s*$").test(lines[i])) { body.push(lines[i]); i++; }
      i++;
      out.push('<div class="codeblk"><button class="cbcopy" type="button" title="Copy this code">Copy</button>'
        + "<pre><code>" + body.join("\n") + "</code></pre></div>"); continue;
    }
    if (line.includes("|") && i + 1 < lines.length && sep(lines[i + 1])) {   // table
      const head = row(line); i += 2; const body = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim() !== "") { body.push(row(lines[i])); i++; }
      out.push("<table><thead><tr>" + head.map(c => "<th>" + inlineMd(c) + "</th>").join("") +
        "</tr></thead><tbody>" + body.map(r => "<tr>" + r.map(c => "<td>" + inlineMd(c) + "</td>").join("") + "</tr>").join("") +
        "</tbody></table>"); continue;
    }
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) { const n = h[1].length; out.push("<h" + n + ">" + inlineMd(h[2]) + "</h" + n + ">"); i++; continue; }
    if (/^\s*([-*_])\s*(\1\s*){2,}$/.test(line)) { out.push("<hr>"); i++; continue; }
    if (/^\s*&gt;\s?/.test(line)) {                         // blockquote ("&gt;" — the text is escaped)
      const q = [];
      while (i < lines.length && /^\s*&gt;\s?/.test(lines[i])) { q.push(lines[i].replace(/^\s*&gt;\s?/, "")); i++; }
      out.push("<blockquote>" + mdToHtml(q.join("\n"), true) + "</blockquote>"); continue;
    }
    if (bullet(line)) {                                     // list
      const ordered = /^\s*\d+[.)]\s+/.test(line); const items = [];
      while (i < lines.length && bullet(lines[i])) {
        let it = lines[i].replace(/^\s*(?:[-*+]|\d+[.)])\s+/, ""); i++;
        while (i < lines.length && /^\s+\S/.test(lines[i]) && !bullet(lines[i])) { it += "<br>" + lines[i].trim(); i++; }
        items.push("<li>" + inlineMd(it) + "</li>");
      }
      out.push("<" + (ordered ? "ol" : "ul") + ">" + items.join("") + "</" + (ordered ? "ol" : "ul") + ">"); continue;
    }
    if (line.trim() === "") { i++; continue; }
    const para = [];                                        // paragraph; a single newline is a line break
    while (i < lines.length && lines[i].trim() !== "" && !/^\s*(```|~~~)/.test(lines[i]) && !/^\s*>\s?/.test(lines[i])
           && !/^#{1,6}\s+/.test(lines[i]) && !bullet(lines[i])
           && !(lines[i].includes("|") && i + 1 < lines.length && sep(lines[i + 1]))) { para.push(lines[i]); i++; }
    out.push("<p>" + inlineMd(para.join("<br>")) + "</p>");
  }
  return out.join("");
}

const S = { bots: [], channels: [], models: [], settings: {}, skills: [], routines: [], fontSizes: [],
  active: null, activeIsChannel: false, approval: "ask", approvalSet: false, approvalOwn: null,
  dock: null, pending: {},
  /* `turns` holds what each chat's in-flight turn has drawn so far, keyed by chat — and `running`
     on one of them is that chat's own state, not the app's. Two chats work at once; a turn in one
     never holds up another. Switching chats keeps those nodes instead of destroying them, so the
     work is still on screen when you come back rather than looking lost. `queue` holds the tasks
     typed while *that same* chat's turn was already running, keyed by chat, so one chat's backlog
     never runs in another. */
  turns: {}, queue: {}, ctxSess: null, sideMochi: {}, facePrev: null, compFace: null,
  /* The files panel's own place: the directory being shown, relative to the chat's repo root, the
     root itself (the absolute path a copy needs), the apps the "Open with" submenu offers, and which
     chat the directory belongs to — a path browsed in one repo is not a path in another. */
  filesPath: "", filesRoot: "", filesApps: [], filesFor: null,
  /* The transcript currently on screen, and the chats that have one — both re-read from the server
     rather than kept in the tab, so a chat reopened in another window is the same chat. `chatQuery`
     is the sidebar's search box. */
  messages: [], chats: [], chatQuery: "",
  /* The message you are quoting, waiting for you to send: `{who, text}`. It belongs to the chat it
     was started in, so switching chats drops it rather than carrying a quote into another one. */
  reply: null };

/* ---------------- mascot dock ---------------- */
let dockReal = "idle", tipTimer = null;
const STATES_LABEL = { idle:"idle", working:"working at the desk", thinking:"thinking…", searching:"searching…",
  approval:"needs your approval", question:"asking", finished:"done!", error:"error", sleeping:"sleeping",
  ratelimit:"rate limited", dizzy:"dizzy", bored:"bored" };
/* The header and the dock must never disagree about what a chat is doing, so both read one table. The
   header drops the dock's whimsy — it is a status line beside a bot's name, not a hover tooltip. */
const H_STATE = { ...STATES_LABEL, working: "working", finished: "done" };
const POKE_TIP = ["hehe!", "stop it!", "that tickles", "boop!", "hey!", "again! again!", "ehehe"];
/* A chime for the states worth hearing from another window: a turn that finished, one that failed,
   and one that stopped to ask you something. Which states those are lives in sound.js, next to the
   cues themselves, so the mapping and the sounds cannot drift apart. */
let lastChime = null, lastChimeAt = 0;
function chime(state) {
  const name = CUE_FOR[state]; if (!name) return;                 // working and thinking stay silent
  const s = S.settings.sound || {}; if (s.on === false) return;
  const now = Date.now();
  /* An approval arrives twice — the server's own event, then a status — and both land here. One
     chime per state change, not one per event; a real second approval still gets its own. */
  if (state === lastChime && now - lastChimeAt < 1500) return;
  lastChime = state; lastChimeAt = now;
  cue(name, s.volume == null ? 0.5 : s.volume);
}
/* The first real interaction opens the audio context — see sound.js for why it cannot be sooner. */
const unlockAudio = () => { unlock();
  document.removeEventListener("pointerdown", unlockAudio, true);
  document.removeEventListener("keydown", unlockAudio, true); };
document.addEventListener("pointerdown", unlockAudio, true);
document.addEventListener("keydown", unlockAudio, true);
function setDock(st) {
  /* The one place every state change funnels through, so the screen-reader milestone is said here
     rather than at each call site — and only when the state actually changes, or a turn would
     re-announce "working" on every step. */
  if (dockReal !== st && st !== "idle") announce(STATES_LABEL[st] || st);
  dockReal = st; if (S.dock) S.dock.setState(st); chime(st);
  const tip = $("#dockTip"); if (tip && tip.classList.contains("on")) tip.textContent = STATES_LABEL[st] || st; }
/* The dock wears the face of whoever you are talking to, so the corner always says which
   bot is speaking. A room is a whole company with no single face, so it keeps the general
   Mochi — the plain one. */
function dockFace() {
  if (!S.dock) return;
  const b = S.activeIsChannel ? null : botOf(S.active);
  S.dock.skin(b ? faceOf(b) : "mochi", b ? bigFace(b.color) : null, b ? lookOf(b) : null);
  S.dock.cv.dataset.species = S.dock.species;
  compDress();                                            // the computer panel's placeholder follows too
}
function showTip(txt, holdMs = 0) { const tip = $("#dockTip"); if (!tip) return;
  tip.textContent = txt; tip.classList.add("on"); clearTimeout(tipTimer);
  if (holdMs) tipTimer = setTimeout(() => tip.classList.remove("on"), holdMs); }
function pokeDock() { if (!S.dock) return; S.dock.poke(); showTip(POKE_TIP[Math.floor(Math.random() * POKE_TIP.length)], 900); }
/* The corner mascot is decoration, so it can be put away. It is a local preference, not a setting on
   the server: it is about this screen, and hiding it must not need a round-trip. */
const dockHidden = () => { try { return localStorage.getItem("dock.hidden") === "1"; } catch (e) { return false; } };
function setDockHidden(v) {
  try { localStorage.setItem("dock.hidden", v ? "1" : "0"); } catch (e) {}
  const d = $("#dock"); if (d) d.style.display = v ? "none" : "";
  document.body.classList.toggle("nodock", v);   // lets the composer reclaim the corner the mascot held
  if (v && $("#dockTip")) $("#dockTip").classList.remove("on");
}

/* ---------------- mobile drawer ---------------- */
/* Below 900px the sidebar is an off-canvas drawer, but off-canvas is only a transform — its rows stay
   in the tab order and reachable by a screen reader. `inert` takes the closed drawer out of both; on a
   wide screen it is always in flow, so this only ever applies in the narrow layout. */
const narrowMQ = window.matchMedia("(max-width:900px)");
function syncDrawer() {
  const side = $("#side"); if (!side) return;
  side.inert = narrowMQ.matches && !side.classList.contains("open");
}
function openDrawer() { $("#side").classList.add("open"); $("#backdrop").classList.add("on"); syncDrawer(); }
function closeDrawer() { $("#side").classList.remove("open"); $("#backdrop").classList.remove("on"); syncDrawer(); }
narrowMQ.addEventListener("change", syncDrawer);

/* ---------------- sidebar rail ----------------
   On a wide screen the sidebar folds to a column of faces, handing the transcript back the width
   the names were using. It is a separate control from the mobile drawer: below 900px the
   stylesheet ignores the rail entirely, because a drawer is opened in order to be read. */
function setRail(on) {
  document.body.classList.toggle("rail", on);
  const b = $("#btnRail");
  if (b) { b.setAttribute("aria-expanded", String(!on)); b.title = on ? "Expand the sidebar" : "Collapse the sidebar"; }
  try { localStorage.setItem("nav.rail", on ? "1" : "0"); } catch (e) {}
}
function initRail() {
  const b = $("#btnRail"); if (!b) return;
  b.onclick = () => setRail(!document.body.classList.contains("rail"));
  /* Restored only where it means something, so a fold made on a wide screen does not quietly
     reappear as a broken layout in a narrow one. */
  try { if (localStorage.getItem("nav.rail") === "1" && window.innerWidth > 900) setRail(true); } catch (e) {}
}

/* ---------------- theme ---------------- */
/* Dark ink on a light accent, light ink on a dark one, so the label on the primary button stays
   readable whatever colour the user picks in Appearance. It picks whichever ink actually contrasts
   more rather than testing the accent against a luminance threshold: a mid-tone accent — a red, an
   indigo — sits right on that threshold, and the fixed rule handed those the *worse* ink, which is
   exactly where a button label is hardest to read. */
function readableInk(hex) {
  const m = /^#?([\da-f]{6})$/i.exec(String(hex || "").trim()); if (!m) return "#0B0B10";
  const ch = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  const lum = h => { const x = parseInt(h.slice(1), 16);
    return 0.2126 * ch(x >> 16 & 255) + 0.7152 * ch(x >> 8 & 255) + 0.0722 * ch(x & 255); };
  const on = bg => ink => { const a = Math.max(bg, lum(ink)), b = Math.min(bg, lum(ink)); return (a + 0.05) / (b + 0.05); };
  const contrast = on(lum("#" + m[1]));
  return contrast("#FFFFFF") >= contrast("#0B0B10") ? "#FFFFFF" : "#0B0B10";
}
/* The theme packages. Each id names a token block in index.html; `light` says the block reads on a
   light surface, which is what makes the body carry the `light` class the legibility rules hang
   off. `accent` is the theme's signature colour — picking a theme adopts it, and the colour field
   below is how you keep your own. Every entry here must have a block, and every block must define
   all eighteen tokens; the offline suite checks both. */
const THEMES = [
  ["dark", "Dark", "#7C5CFF", 0],
  ["light", "Light", "#7C5CFF", 1],
  ["glass", "Liquid Glass", "#8AB4FF", 0],
  ["glass-light", "Liquid Glass Light", "#2A62F0", 1],
  ["ainative", "AI-Native UI", "#5457E5", 0],
  ["ainative-light", "AI-Native Light", "#4F46E5", 1],
  ["luxe", "Dark Luxe", "#D4AF37", 0],
  ["eink", "E-Ink / Paper", "#1A1A1A", 1],
  ["terminal", "Terminal Hacker", "#00FF41", 0],
  ["mono", "Monochrome", "#E4E4E7", 0],
  ["mono-light", "Monochrome Light", "#18181B", 1],
];
const themeDef = id => THEMES.find(t => t[0] === id) || THEMES[0];
function applyAppearance(a) {
  a = a || {};
  const th = themeDef(a.theme);
  document.body.dataset.theme = th[0];
  document.body.classList.toggle("light", !!th[3]);
  const acc = a.accent || th[2];
  document.body.style.setProperty("--accent", acc);
  document.body.style.setProperty("--accent-ink", readableInk(acc));
  document.documentElement.style.setProperty("--fs", gridSize(a.font_size) / BASE_PX);
  document.documentElement.style.setProperty("--font", fontStack(a.font));
  /* Density is an attribute, not a variable: compact tightens rules that each carry their own
     padding, so one `body[data-density="compact"]` block beats threading a variable through them
     all. Only set when the caller actually supplied it, so a partial call never resets the choice;
     an absent attribute is comfortable. */
  if ("density" in a) document.body.dataset.density = a.density === "compact" ? "compact" : "comfortable";
  const brand = $(".brand b"); if (brand) brand.textContent = S.settings.company_name || "Anzen-bot";
}
/* The font picker swaps one stack. Every stack is supplied by the system, so a choice works
   offline and nothing is fetched from a font CDN. The first entry must stay identical to the
   --font default in index.html, or the first paint would differ from every later one.
   Each stack carries a generic family (sans-serif / serif / monospace), so a face that is missing
   on another machine degrades to the right kind of type instead of to the browser's default.
   "ZCode" is the interface stack the ZCode editor itself renders in, and "SF Mono" is the face it
   sets code in; both fall back through the generic families in their stack, so neither is ever dead. */
const FONTS = [
  ["system", "System", 'ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,Helvetica,Arial,sans-serif'],
  ["zcode", "ZCode", 'ui-sans-serif,system-ui,sans-serif,"Apple Color Emoji","Segoe UI Emoji","Segoe UI Symbol","Noto Color Emoji"'],
  ["rounded", "Rounded", 'ui-rounded,"SF Pro Rounded","Hiragino Maru Gothic ProN",Quicksand,system-ui,sans-serif'],
  ["avenir", "Avenir", 'Avenir,"Avenir Next",system-ui,sans-serif'],
  ["helvetica", "Helvetica", '"Helvetica Neue",Helvetica,Arial,sans-serif'],
  ["futura", "Futura", 'Futura,"Century Gothic","Trebuchet MS",sans-serif'],
  ["optima", "Optima", 'Optima,Candara,"Segoe UI",sans-serif'],
  ["gill", "Gill Sans", '"Gill Sans","Gill Sans MT",Calibri,sans-serif'],
  ["trebuchet", "Trebuchet", '"Trebuchet MS",Tahoma,sans-serif'],
  ["wide", "Wide", 'Verdana,Tahoma,Geneva,"DejaVu Sans",sans-serif'],
  ["serif", "Serif", 'ui-serif,Georgia,"Iowan Old Style","Times New Roman",serif'],
  ["georgia", "Georgia", 'Georgia,"Times New Roman",serif'],
  ["palatino", "Palatino", 'Palatino,"Palatino Linotype","Book Antiqua",serif'],
  ["didot", "Didot", 'Didot,"Bodoni 72",Bodoni,serif'],
  ["charter", "Charter", 'Charter,"Bitstream Charter",Georgia,serif'],
  ["mono", "Mono", 'ui-monospace,SFMono-Regular,Menlo,Consolas,monospace'],
  ["sfmono", "SF Mono", '"SF Mono",ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace'],
  ["jetbrains", "JetBrains Mono", '"JetBrainsMono Nerd Font","JetBrainsMonoNL Nerd Font",JetBrainsMono,ui-monospace,Menlo,monospace'],
];
const fontStack = id => (FONTS.find(f => f[0] === id) || FONTS[0])[2];
/* The base text size. Must match BASE_FONT_PX in server.py, which owns the grid of sizes the
   panel offers and migrates the old font_scale setting onto it. */
const BASE_PX = 14.5;
/* Snap to the grid the server sent. A hand-edited settings.json would otherwise render at one
   size while the picker showed another, since the picker can only show the options it has. */
const gridSize = px => (S.fontSizes.length ? S.fontSizes.reduce((a, b) => Math.abs(b - px) < Math.abs(a - px) ? b : a) : BASE_PX);

/* ---------------- voice ---------------- */
function speak(text) {
  if (!("speechSynthesis" in window)) return;
  const u = new SpeechSynthesisUtterance((text || "").replace(/[`*#_]/g, "").slice(0, 600));
  const v = (S.settings.voice || {});
  if (v.voice_id) { const m = speechSynthesis.getVoices().find(x => x.name === v.voice_id); if (m) u.voice = m; }
  u.rate = 1.02; speechSynthesis.cancel(); speechSynthesis.speak(u);
}

/* ---------------- boot ---------------- */
async function boot() {
  const cfg = await get("/api/config");
  if (!cfg) {
    $("#msgs").innerHTML = '<div class="empty"><div class="big">Cannot reach the server</div>'
      + '<div class="sub">The app loaded but /api/config did not answer. Make sure server.py is running, then reload.</div></div>';
    splashOff();
    return;
  }
  S.bots = cfg.bots; S.channels = cfg.channels; S.models = cfg.models;
  S.settings = cfg.settings || {}; S.skills = cfg.skills || []; S.routines = cfg.routines || [];
  S.tools = cfg.tools || []; S.connectorTools = cfg.connector_tools || []; S.fontSizes = cfg.font_sizes || [BASE_PX];
  S.teamTemplate = cfg.team_template || "";   // the import panel hands this out; without it a cold start copies nothing
  applyAppearance(S.settings.appearance);
  attach($(".bm"), "finished", { species: speciesFor(S.settings.company_name || "anzen") });
  S.dock = attach($("#dockMochi"), "idle", { species: "mochi" });   // re-skinned per context by dockFace()
  renderNav();
  await refreshPending();
  await loadChats();
  await select(firstChatId());
  watchChats();                        // and from here on, follow what the phone does to these chats
  splashOff();
}
/* The splash covers the gap between the window painting and the first config answer. It goes once
   there is something to look at, and it is removed rather than hidden so it can never eat a click. */
function splashOff() {
  const s = $("#splash"); if (!s) return;
  s.classList.add("gone");
  setTimeout(() => s.remove(), 420);
}

function bot(id) { return S.bots.find(b => b.id === id); }
function chan(id) { return S.channels.find(c => c.id === id); }
/* A chat's id says where it lives: a bare channel id is the room, a bare bot id is a bot with
   no company, and `<channel>/<bot>` is that bot *inside* that company — its own transcript and
   its own repo. The same id is also the sidebar row key, so one string drives everything. */
const scopeOf = id => { const i = (id || "").indexOf("/"); return i < 0 ? null : id.slice(0, i); };
const botIdOf = id => { const i = (id || "").indexOf("/"); return i < 0 ? id : id.slice(i + 1); };
const botOf = id => bot(botIdOf(id));
const chanOf = id => S.activeIsChannel ? chan(id) : (scopeOf(id) ? chan(scopeOf(id)) : null);
/* The channel a chat belongs to: the room itself, or the room a member's nested chat is scoped to.
   Approval is filed per channel, so this is what says whether a chat is inside one at all. */
const roomOf = id => chan(id) || chan(scopeOf(id) || "");
const NAME = id => { const b = botOf(id), c = chan(id); return b ? b.name : (c ? c.name : id); };

/* ---------------- whose name is which colour ----------------
   A stored message records `who` as the bot's display name, not its id, so a name is resolved back
   to a bot to find its colour. A bot keeps the colour of its own avatar and face, so the transcript
   and the sidebar agree. Two members of one room can be given the same colour — nothing in the
   roster requires them to differ — and two names in one room must not read alike, so the later
   member, in the room's own member order, takes the first palette entry nobody before it is using.
   That is read off the member list alone, so it is the same on every redraw, and a bot only ever
   moves off its own colour when it collided. The same bot in two rooms may therefore resolve
   differently, which is what "distinct within one room" means. */
const hueOf = (name, sid) => {
  if (!name) return null;
  const c = chan(sid), used = new Set();
  for (const id of (c && c.members) || []) {
    const b = bot(id); if (!b || b.hidden) continue;
    const k = (used.has(b.color) ? AVK.find(x => !used.has(x)) : b.color) || b.color;
    used.add(k);
    if (b.name === name) return k;
  }
  /* Not in this room's roster: a chat with no room, a bot with no company, or a teammate from
     outside it. Its own colour, which is the one its sidebar row wears. A name that matches no bot
     at all — a bot renamed or deleted after the message was stored — has none. */
  const b = S.bots.find(x => x.name === name);
  return b ? b.color : null;
};
/* A name as it is written in a header. The hue rides in `--mc`, exactly as the avatar's does, so one
   legibility rule in index.html serves both. Without a hue the span is still there — it carries the
   ellipsis the header relies on — and the name reads in the header's own dim. The hue is passed in
   rather than looked up here, so the two places that must never take one (your own name, a room
   label) simply do not call hueOf at all. */
const hueSpan = (name, cls, hue) => {
  const c = [cls, hue ? "hue" : ""].filter(Boolean).join(" ");
  return `<span${c ? ` class="${c}"` : ""}${hue ? ` style="--mc:${AV[hue]}"` : ""}>${esc(name)}</span>`;
};

/* ---------------- sidebar ---------------- */
/* Which companies you folded shut, remembered across reloads. */
const collapsed = () => { try { return new Set(JSON.parse(localStorage.getItem("nav.collapsed") || "[]")); } catch (e) { return new Set(); } };
function setCollapsed(s) { try { localStorage.setItem("nav.collapsed", JSON.stringify([...s])); } catch (e) {} }
/* Folding only hides a team, so the row is toggled in place: a full renderNav() would tear down and
   restart every sidebar face (all their animations), which flickers for a click that changed nothing. */
function foldGroup(cid) {
  const s = collapsed(); s.has(cid) ? s.delete(cid) : s.add(cid); setCollapsed(s);
  const g = document.querySelector('.group[data-group="' + CSS.escape(cid) + '"]');
  if (!g) return renderNav();                             // not on screen yet — fall back to a rebuild
  const shut = s.has(cid);
  g.querySelector(".sub")?.classList.toggle("shut", shut);
  g.querySelector(".caret")?.classList.toggle("open", !shut);
}
/* A whole section folds the same way, keyed by its own name rather than by a company id — a
   separate store, so a company that happens to be called "chats" cannot fold the chat list. The
   list runs to the newest conversation every time a turn ends, and on a short window that pushes
   the rooms and bots off the bottom; folding it hands the sidebar back. */
const shutSecs = () => { try { return new Set(JSON.parse(localStorage.getItem("nav.shut") || "[]")); } catch (e) { return new Set(); } };
function applySecs() {
  const shut = shutSecs().has("chats");
  const lab = $("#chatsLabel"); if (!lab) return;
  lab.parentElement.classList.toggle("shut", shut);
  lab.setAttribute("aria-expanded", String(!shut));
  lab.querySelector(".caret")?.classList.toggle("open", !shut);
}
function foldSec(name) {
  const s = shutSecs(); s.has(name) ? s.delete(name) : s.add(name);
  try { localStorage.setItem("nav.shut", JSON.stringify([...s])); } catch (e) {}
  applySecs();
}
/* ---------------- rearranging the sidebar by hand ----------------
   Hold a row and drag it: the three lists that are a stored array — the rooms, the loose bots, and
   one room's members — can be put in any order, and the drop writes that order to channels.json /
   bots.json. The order is the record's rather than this browser's, so the phone reads what the
   window arranged, and nothing new is stored to say so.

   The browser's own drag-and-drop, not pointer events: the rows are already in the DOM, and the
   ghost, the autoscroll near the edge and the touch long-press all come with it. A row only ever
   drops back into its own list — dragging a bot onto the rooms would be a different act (adding it
   to a room), and this is not the place for it. */
let dragRow = null, dragWas = "";
const dragBox = li => li && li.parentElement;
const dragRows = box => [...box.children].filter(x => x.dataset.drag);
/* The three lists whose order is a stored array, and nothing else: a row dragged out of one of
   them has nowhere to go, so the drag never starts. */
const isList = box => !!box && (box.id === "chans" || box.id === "bots" || box.matches("ul.sub"));
function dragStart(e) {
  const li = e.target.closest ? e.target.closest("[data-drag]") : null;
  if (!isList(dragBox(li))) return;
  dragRow = li; dragWas = dragRows(dragBox(li)).map(x => x.dataset.drag).join(",");
  li.classList.add("dragging");
  e.dataTransfer.effectAllowed = "move";
  /* Firefox starts no drag at all without something on the clipboard, so the payload is the row's
     own id — which is also what a drop into another window would carry. */
  try { e.dataTransfer.setData("text/plain", li.dataset.drag); } catch (err) {}
}
function dragOver(e) {
  if (!dragRow) return;
  const box = dragBox(dragRow);
  /* Only the list the row was picked up from accepts it, and it accepts anywhere inside itself —
     including over a room's members, which are a list of their own. Testing the box rather than the
     element under the pointer is what makes an expanded room a valid place to drop a room. */
  if (!box || !e.target || !box.contains(e.target)) return;
  e.preventDefault(); e.dataTransfer.dropEffect = "move";
  /* The row follows the pointer rather than being drawn by a CSS rule: the gap it leaves is the
     list closing up, which is the answer to "where will this land". Half a row is the midpoint, so
     a drag past the middle of a row means "after it". */
  const after = dragRows(box).find(x => x !== dragRow &&
    e.clientY < x.getBoundingClientRect().top + x.getBoundingClientRect().height / 2);
  after ? box.insertBefore(dragRow, after) : box.appendChild(dragRow);
}
/* The drop itself does nothing: `dragend` is the one commit, so a row let go outside any list —
   which fires no `drop` — is saved exactly like one let go inside it. */
async function dragEnd() {
  if (!dragRow) return;
  const li = dragRow, box = dragBox(li);
  dragRow = null; li.classList.remove("dragging");
  if (!box || !box.contains(li)) return;                     // the list was rebuilt under the drag
  const ids = dragRows(box).map(x => x.dataset.drag);
  if (ids.join(",") === dragWas) return;                     // put back where it was picked up
  const kind = box.id === "chans" ? "channels" : box.id === "bots" ? "bots" : "members";
  const body = { kind, ids };
  if (kind === "members") body.id = box.closest(".group").dataset.group;
  const r = await jpost("/api/nav/order", body);
  if (r.ok === false) { alert(r.error || "Could not save the new order."); return reloadConfig(); }
  /* The rows are already where they were dropped, so the state is patched and nothing re-renders:
     a rebuild here would tear down and restart every face in the sidebar for a list that is
     already right. */
  if (kind === "bots") S.bots = r.bots; else S.channels = r.channels;
  /* Pin still floats a room to the top, so a drag across the pinned boundary is undone at the next
     render. Redrawing now rather than later is what makes the row's landing honest. */
  if (kind === "channels" && S.channels.some(c => c.pinned)) renderNav();
}

/* ---------------- chats (past conversations) ----------------
   The sidebar's other half: every chat that has a transcript, newest first, whichever company it
   belongs to. It is a list of *conversations*, not of bots — the bots below are who you can talk to,
   this is what you already said. Search filters on the name, the title and the last line. */
/* The wall-clock time a message landed, for the transcript's stamp. Minute precision — a chat is read
   for when things happened, not to the second. */
const stampAt = ms => new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
function ago(ts) {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - (ts || 0)));
  if (!ts) return "";
  if (s < 60) return "now";
  if (s < 3600) return Math.floor(s / 60) + "m";
  if (s < 86400) return Math.floor(s / 3600) + "h";
  if (s < 604800) return Math.floor(s / 86400) + "d";
  return Math.floor(s / 604800) + "w";
}
/* The chat to land on when nothing specific was asked for: the first room, else the first chat that
   exists, else the first bot. Nothing at all (a brand-new install with no bots and no rooms) is
   `null` — a hard-coded id here named a bot that may not exist and left the app staring at an
   empty screen under a "null" heading. */
function firstChatId() {
  if (S.channels && S.channels.length) return S.channels[0].id;
  if (S.chats && S.chats.length) return S.chats[0].id;
  if (S.bots && S.bots.length) return S.bots[0].id;
  return null;
}
async function loadChats() {
  S.chats = ((await get("/api/chats")) || {}).chats || [];   // a failed read empties the rail, never throws
  renderChats();
}
/* ---------------- a chat another device is writing ----------------
   The window and the phone are two clients of one server, and a chat is one transcript on disk — so
   a turn typed on the phone has to show up here, and the other way round. The server pushes a nudge
   down `/api/watch` whenever any client writes a chat; this re-reads that chat over the ordinary
   API. A nudge carries no content, which is the point: a lost one costs a refresh and never a
   message, so the stream is allowed to die and be reopened rather than being treated as precious. */
let watchTimer = null;
async function watchChats() {
  try {
    const r = await fetch("/api/watch");
    if (!r.ok || !r.body) throw new Error("no watch stream");
    const rd = r.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await rd.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, i); buf = buf.slice(i + 2);
        const line = frame.split("\n").find(l => l.startsWith("data:"));
        if (!line) continue;                       // a keepalive comment
        try { await elsewhere(JSON.parse(line.slice(5).trim())); } catch (e) {}
      }
    }
  } catch (e) { /* the server is gone or the stream dropped — the retry below is the whole answer */ }
  clearTimeout(watchTimer);
  watchTimer = setTimeout(watchChats, 2500);
}
async function elsewhere(d) {
  if (!d || !d.session) return;
  /* A running turn's own events arrive many times a second; the sidebar's order and last line do not
     change until the turn saves, so only a transcript nudge is worth re-reading the chat list for. */
  const live = d.type && d.type !== "chat" && d.type !== "gone";
  if (!live) await loadChats();
  if (d.session !== S.active) return;
  if (d.type === "gone") { await select(firstChatId()); return; }
  if (d.turn && S.myTurns && S.myTurns[d.session] === d.turn) return;   // our own turn; its stream drew it
  const T = S.turns[S.active];
  /* A turn running in *this* window owns the transcript: its cards are being drawn into the DOM as
     they arrive, and re-reading the saved copy underneath them would show the same turn twice. That
     turn redraws from the record when it ends, so waiting loses nothing. */
  if (T && !T.watched) return;
  /* The server streams every turn event to every watcher, so a turn another client is running (the
     desktop, while you are on the phone) is drawn here as it happens rather than leaving the chat
     blank until it ends. `done`/`error` is the end of it: hand the chat back to the record. */
  if (d.type === "done" || d.type === "error") { if (T) await endWatched(S.active); return; }
  if (live) {
    const W = T || (S.turns[S.active] = { nodes: [], plan: null, running: true, watched: true });
    drawTurnEvent(S.active, W, d);
    return;
  }
  if (T) return;              // a transcript nudge for a watched turn mid-flight; its `done` hands it back
  await reloadTranscript();   // the redraw lands at the bottom only if you were already following it
}
/* A turn another client ran has ended here: its streamed cards were the live view, so hand the chat
   back to the saved transcript — the record — exactly as the window that ran it does at its own end. */
async function endWatched(sid) {
  const T = S.turns[sid];
  if (T) { T.running = false; stepDone(T, T.failed); }
  delete S.turns[sid];
  workingClear();                        // the turn is over: no live row left for a bot that has finished
  setState(sid, "idle");                 // the turn is over: no dot left lit, no "working" left on the header
  if (sid === S.active) await reloadTranscript();
  loadChats();
  drainQueue(sid);                       // anything typed here while that turn ran goes now that it has
}
function renderChats() {
  const box = $("#chats"); if (!box) return;
  const q = (S.chatQuery || "").trim().toLowerCase();
  /* A chat scoped to a company is still a chat with one bot, so it is named for the bot — the
     company is a quiet qualifier beside it, never in place of it. The qualifier is shown only where
     it is doing a job: a bot with a chat both inside a company and outside one would otherwise give
     two rows the same name. It stays part of the search text either way, so the company still finds
     its chats. */
  const scopeName = id => { const s = scopeOf(id); return s ? ((chan(s) || {}).name || "") : ""; };
  const dupes = {};
  for (const c of S.chats) dupes[c.name] = (dupes[c.name] || 0) + 1;
  const rows = q ? S.chats.filter(c =>
    ((c.name || "") + " " + scopeName(c.id) + " " + (c.title || "") + " " + (c.last || "")).toLowerCase().includes(q)) : S.chats;
  box.innerHTML = "";
  if (!rows.length) {
    box.appendChild(el("li", "chatempty", q ? "No chat matches “" + esc(S.chatQuery) + "”." : "Nothing here yet — say something to a bot and it shows up."));
    return;
  }
  for (const c of rows) {
    const li = el("li", "chat" + (c.id === S.active ? " sel" : ""));
    li.dataset.id = c.id;
    const sc = dupes[c.name] > 1 ? scopeName(c.id) : "";
    li.innerHTML = `<span class="ck">${svg(c.kind === "room" ? "channels" : "bots")}</span>
      <div class="cmin"><div class="cnm">${esc(c.name)}${sc ? `<span class="csc">${esc(sc)}</span>` : ""}</div>
      <div class="clast">${esc(c.last || c.title || "")}</div></div>
      <span class="cts">${esc(ago(c.ts))}</span>`;
    li.onclick = () => { if (c.id !== S.active) select(c.id); };
    kbd(li, li.onclick);
    box.appendChild(li);
  }
}

/* One row for a bot inside a company. Same bot, same face, same config — the row id is what
   makes the chat scoped, so `webshop/producer` and `mobile/producer` are two conversations. */
function subRow(b, scope) {
  const key = scope ? scope + "/" + b.id : b.id;
  const li = el("li", "bot subbot" + (key === S.active ? " sel" : "")); li.dataset.id = key; li.dataset.kind = "bot";
  li.dataset.bot = b.id;                                  // the row's key is scoped; the menu needs the bot id too
  /* Both lists this row appears in are stored arrays — the loose bots, and one room's members — and
     the bare bot id is what orders either one, so one attribute serves the drag for both. */
  li.dataset.drag = b.id; li.draggable = true;
  li.innerHTML = `${avatar(b.name, b.color, "", b.emoji)}
    <div class="min"><div class="nm">${esc(b.name)}${b.pinned ? `<span class="pin">${svg("pin")}</span>` : ""}<i class="dot"></i></div>
    <div class="rl">${esc(b.title || b.role || "")}</div></div><span class="kebab" title="More actions">⋯</span>`;
  /* Already-open chat: clicking its row changes nothing, so it does not re-render and replay the
     smooth scroll over a transcript that is already on screen. */
  li.onclick = e => { if (e.target.closest(".kebab")) return openCtx(e, b.id, "bot", key); if (key !== S.active) select(key); };
  kbd(li, () => { if (key !== S.active) select(key); });
  kbd(li.querySelector(".kebab"), e => openCtx(e, b.id, "bot", key));
  const holder = li.querySelector(".mc");                 // swap the static face for a live one
  const cv = document.createElement("canvas"); cv.className = "sidebot";
  cv.setAttribute("aria-hidden", "true");   // decorative: the row's own name carries the meaning
  cv.dataset.species = faceOf(b);
  holder.replaceWith(cv);
  S.sideMochi[key] = attach(cv, "idle", { size: 46, species: cv.dataset.species, ...sideFace(b.color), ...lookOf(b) });
  return li;
}
function renderNav() {
  for (const m of Object.values(S.sideMochi)) {           // nav rebuilds from scratch — retire old faces
    if (m._idleTimer) clearTimeout(m._idleTimer);
    detach(m);
  }
  S.sideMochi = {};
  const shut = collapsed();
  const cbox = $("#chans"); cbox.innerHTML = "";
  const claimed = new Set();                              // bots that live under some company
  /* A pinned room floats, exactly as a pinned bot does, and the sort is stable so the rest keep the
     order you dragged them into. */
  for (const c of [...S.channels].sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0))) {
    const members = (c.members || []).map(m => bot(m)).filter(b => b && !b.hidden);
    members.forEach(b => claimed.add(b.id));
    const isShut = shut.has(c.id);
    const li = el("li", "bot" + (c.id === S.active ? " sel" : "")); li.dataset.id = c.id; li.dataset.kind = "channel";
    const roster = members.map(b => b.name).join(" · ");
    const repo = (c.folder || "").replace(/\/+$/, "").split("/").pop();   // the row is narrow; the full path is in the header
    li.innerHTML = `<span class="caret${isShut ? "" : " open"}" title="Fold or expand the team" aria-label="Fold or expand the team">${svg("caret")}</span>${avatar(c.name, c.color, "", "", logoOf(c))}
      <div class="min" title="${esc(roster)}"><div class="nm">${esc(c.name)}${c.pinned ? `<span class="pin">${svg("pin")}</span>` : ""}<i class="dot"></i></div>
      <div class="rl"${c.folder ? ` title="repo: ${esc(c.folder)}"` : ""}>${members.length} member${members.length === 1 ? "" : "s"}${repo ? " · " + esc(repo) : ""}</div></div>
      <span class="kebab" title="More actions">⋯</span>`;
    li.onclick = e => {
      if (e.target.closest(".kebab")) return openCtx(e, c.id, "channel");
      if (e.target.closest(".caret")) {                   // the caret folds the company, it does not open it
        return foldGroup(c.id);
      }
      /* Clicking the company you are already in does nothing: re-selecting it would re-render the
         transcript, and since #msgs scrolls smoothly, that replays as a top-to-bottom scroll over a
         chat that never left. */
      if (c.id === S.active) return;
      select(c.id);
    };
    /* One click opens the company. A second click folds the team shut, a third opens it again —
       and because the first click of the pair has already opened the company, double-clicking one
       you were not in both opens it and unfolds the team, which is what "click twice" has to mean.
       The fold is read fresh here rather than taken from the row's own class, so it is the state
       at the moment of the click that flips, not whatever the last render happened to leave. */
    li.ondblclick = e => {
      if (e.target.closest(".kebab") || e.target.closest(".caret")) return;
      foldGroup(c.id);
    };
    kbd(li, () => { if (c.id !== S.active) select(c.id); });
    kbd(li.querySelector(".kebab"), e => openCtx(e, c.id, "channel"));
    kbd(li.querySelector(".caret"), () => foldGroup(c.id));
    /* A room is dragged by its row, and its members come with it — the unit that moves is the whole
       group, so a room keeps its team folded up inside it. */
    const group = el("li", "group"); group.dataset.group = c.id; group.dataset.drag = c.id; group.draggable = true;
    group.appendChild(li);
    const sub = el("ul", "sub" + (isShut ? " shut" : ""));
    for (const b of members) sub.appendChild(subRow(b, c.id));
    group.appendChild(sub);
    cbox.appendChild(group);
  }
  const bbox = $("#bots"); bbox.innerHTML = "";
  const loose = [...S.bots].filter(b => !b.hidden && !claimed.has(b.id))
    .sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0));
  $("#botsLabel").style.display = loose.length ? "" : "none";
  for (const b of loose) bbox.appendChild(subRow(b, null));
  dockFace();                                             // the corner follows the active bot's face
}

/* ---------------- selection ---------------- */
function hSub(st) {
  const c = chanOf(S.active);
  return st + (c && c.folder ? " · repo: " + c.folder : "");
}
/* The header line. The one state that is asking something of you — a card waiting — is picked out in
   colour, so the header and the dock agree and the ask is not easy to miss. */
function setHead(text, attn) {
  const n = $("#hStatus"); n.textContent = text; n.classList.toggle("attn", !!attn);
}
/* What the Approval chip reads, so it can never disagree with what a turn will actually do: a
   channel's own level, or a chat with a bot following a level of its own or the bot's default. */
function chipApproval() {
  $("#chipMem").textContent = "Approval: " + approvalChip(S.approval)
    + ((roomOf(S.active) || S.approvalSet) ? "" : " · bot default");
}
/* What the chip shows and what a turn will actually run, from one /api/history reply. Kept in one
   place because `select` and the post-approval refresh both need it and must not drift apart. */
function applyApproval(h, sid) {
  const room = roomOf(sid);
  S.approvalOwn = room ? null : h.approval_own;
  S.approvalSet = room ? true : !!h.approval;
  S.approval = room ? (h.approval || "ask")
    : (h.approval || h.approval_own || (botOf(sid) || {}).approval || "ask");
  chipApproval();
}
/* A turn belongs to one chat, not to the app: two chats can work at once, so a task typed in one
   never waits on another's turn. `busy` is a chat's own state — the dot, the Stop button and the
   queue all hang off it — and `runningElsewhere` is the chat the header names when this one is idle
   but another is working, so a turn running out of sight is still visible. */
function busy(sid) { const t = S.turns[sid]; return !!(t && t.running); }
function runningElsewhere(sid) {
  return Object.keys(S.turns).find(k => k !== sid && S.turns[k].running) || null;
}
/* The header describes the chat on screen: its own turn's state, or — when a turn is running in a
   chat you are not looking at — which chat that is and whether it is waiting on you. So a turn
   running elsewhere is never invisible. */
function refreshHead() {
  const t = S.turns[S.active], run = busy(S.active), other = runningElsewhere(S.active);
  /* Amber only while the card is on screen for the chat you are looking at; a card waiting in a chat
     you are not looking at is named, not coloured — it is not asking you yet. */
  setHead(run ? hSub(H_STATE[t.asking ? "approval" : "working"])
    : other ? hSub(H_STATE.idle) + " · " + NAME(other) + (S.turns[other].asking ? " " + H_STATE.approval : " is working")
    : hSub(H_STATE.idle),
    run && t.asking);
  $("#hDot").classList.toggle("live", run);
}
async function select(id) {
  if (!id) {                                  // nothing to land on: no rooms, no chats, no bots
    S.active = null; S.activeIsChannel = false;
    $("#hName").textContent = "No chats yet";
    $("#msgs").innerHTML = '<div class="empty"><div class="big">Nothing here yet</div>'
      + '<div class="sub">Add a bot or a room from the sidebar to start a chat.</div></div>';
    return;
  }
  S.active = id; S.activeIsChannel = !!chan(id); closeDrawer();
  /* The strip is the room on screen, so it goes with the room that was: the next room's own events
     build its own rows. */
  workingClear();
  closeModelMenu(); closeMention();
  S.reply = null; renderReply();      // a reply belongs to the chat it was started in
  $$("#bots .bot, #chans .bot").forEach(x => x.classList.toggle("sel", x.dataset.id === id));
  const sb = botOf(id);
  $("#hName").textContent = (sb && sb.emoji ? sb.emoji + "  " : "") + NAME(id);
  setHead(hSub(H_STATE.idle));
  $("#input").placeholder = S.activeIsChannel ? "Message the room… (@mention a bot)" : "Give a task…";
  if (S.dock) S.dock.setState("idle");
  dockFace();
  /* The computer panel is scoped to the chat you are in, so switching chats re-asks now instead of at
     the next 2.5s poll — otherwise the previous chat's screen reads as this one's for a beat. The
     files panel is scoped the same way and more sharply: the directory it is showing need not even
     exist in the repo the new chat works in, so it starts again at that repo's root. */
  if ($("#comp").classList.contains("on")) refreshComp();
  if ($("#files").classList.contains("on")) { filesForChat(); refreshFiles(); }
  const h = await get("/api/history?session=" + encodeURIComponent(id));
  if (!h) return;                               // server unreachable mid-click: leave the panel as it was
  if (id !== S.active) return;                  // a later click already owns the panel; drop this reply
  $("#chipModel").textContent = "Model: " + (h.model || "none");
  applyApproval(h, id);
  renderCtx(h.ctx);
  S.messages = h.messages || [];               // the record the message actions act on
  /* Opening a chat means reading its newest message: wherever you had scrolled back to in the last
     one is not where this one opens. Set here, on the redraw itself, so nothing that happens while
     the history is in flight can leave the new chat opening at the top. */
  pinned = true;
  render(S.messages, h.pending);
  /* A turn may be running here (you switched away and came back) or in another chat. Either way the
     header and the composer say so, so a disabled Send is never a mystery and the running chat is
     never a blank panel. */
  refreshHead();
  if (S.turns[id] && S.turns[id].running) setDock("working");
  renderQueue();                     // this chat's queue, if it has one, belongs on screen too
  renderChats();                     // and the sidebar marks this chat as the one you are in
  syncComposer();                    // Stop belongs to the chat whose turn is running, not to this one
  /* Focus the composer only where a pointer is the input. On a phone this line runs on a tap in the
     drawer (and on a remote `gone` or a sub-chat handback, with no tap at all), so focusing would
     raise the soft keyboard before the user has decided to type. */
  if (matchMedia("(hover: hover)").matches) $("#input").focus();
}

/* ---------------- render ---------------- */
function render(messages, pending) {
  const box = $("#msgs");
  /* The rebuild below throws the transcript away and with it the scroll offset, which resets to the
     top. Keep where the reader was, so a redraw that lands while they are reading back can put them
     exactly where they were instead of at the beginning of the chat. */
  const keep = box.scrollTop;
  box.innerHTML = "";
  MSGS.tools = {};          // the rows just thrown away, so a live tool event cannot fill a detached one
  /* These rows are a redraw of a chat you already had, not messages arriving, so the two things a live
     append does are both wrong for them. They go through this sink rather than through MSGS because
     MSGS.add scrolls, and a scroll reads the transcript's `scrollHeight` — which forces a synchronous
     layout of everything appended so far. Done once per message that is O(n²) over the length of the
     chat, and it was the whole cost of opening a long one. They also carry no entrance animation: a
     transcript that fades itself back in every time you switch to it reads as the app redrawing rather
     than as the message arriving. `render` scrolls once, at the end, where the reader's position is
     decided — rows drawn live, which really are arriving, still get their `pop`. */
  const sink = { add: n => { n.style.animation = "none"; box.appendChild(n); }, scroll: () => {} };
  if (!messages.length && !pending) {
    /* First run: with no model in the list there is nothing a task could run on, so the card says
       exactly that and opens the one screen that fixes it, instead of inviting a task that would fail. */
    if (!S.models.length) {
      const e = el("div", "empty",
        `<div class="big">Connect a model to get started</div>
         <div class="sub">Anzen-bot runs on a hosted model reached over an [OI]-compatible API. Point it at
           your endpoint and key in Settings → AI model, and this chat can take tasks.</div>
         <div class="ex"><button data-act="models">Open AI model settings</button></div>`);
      box.appendChild(e);
      e.querySelector('[data-act="models"]').onclick = () => openSettings("models");
    } else {
    const isChan = S.activeIsChannel, b = botOf(S.active), sc = isChan ? null : chanOf(S.active);
    const ex = isChan
      ? ["Build &amp; test a script", "Write a README", "Scaffold a project"]
      : sc ? ["List the files here", "What is this project?", "Write a README"]
      : ["List the files here", "Create a folder", "Summarise this folder"];
    const e = el("div", "empty",
      `<div class="big">${isChan ? "Your room is ready" : esc(NAME(S.active)) + " is ready"}</div>
       <div class="sub">${isChan ? "Message the room. The lead answers, or @mention a bot. The team plans, builds, tests and reports."
         : sc ? "Talking to " + esc(NAME(S.active)) + " inside " + esc(sc.name)
           + (sc.folder ? ". Its shell and file tools run in " + esc(sc.folder) + "." : ". No repo set, so it works in a shared folder.")
         : esc((b && (b.role || b.title)) || "Give it a task below.")}</div>
       <div class="ex">${ex.map(t => `<button data-t="${t}">${t}</button>`).join("")}</div>`);
    box.appendChild(e);
    /* An example fills the composer so you can edit it before it goes — a suggestion you cannot change
       should not send itself the moment you click it. */
    e.querySelectorAll(".ex button").forEach(btn => btn.onclick = () => {
      const inp = $("#input"); inp.value = btn.dataset.t; inp.focus();
    });
    }
  }
  messages.forEach((m, i) => {
    /* A bot's own chat keeps the work it did on a room's behalf — the commands and what they printed
       — so opening it later shows that log instead of a chat that looks like nothing happened. */
    if (m.role === "tool") addTool(m.agent, m.name, m.args || {}, m.out, sink);
    /* A room's hand-off is saved, not just streamed, so reopening the room still says who was on it —
       the live card is gone the moment the turn ends and the record is redrawn. Drawn here the same
       way drawTurnEvent draws it live, so the two cannot drift apart. */
    else if (m.role === "route") addCard("plan", ROUTE_LABEL, cleanBot(m.content), sink);
    /* A stop this app itself caused — a refused command, a denied card, a model that stalled — is the
       account of what happened, and it is saved for the same reason the hand-off is: the live card is
       drawn while the turn runs and the redraw at the end wipes it, so a chat reopened showed the work
       and none of the reasons. `sys` is the app talking too (a compression note). Both are drawn here
       exactly as drawTurnEvent draws the live card, so a saved note and a live one cannot differ. */
    else if (m.role === "notice" || m.role === "sys") addCard("sys", "", m.content, sink);
    else addMsg(m.role, m.content, m.who, sink, { quote: m.quote, fwd: m.fwd, i, ts: m.ts }, S.active);
  });
  if (pending) addApproval(pending.cmd, pending.agent);
  /* A turn that is still running here has already drawn cards into this chat. Put them back in
     order, so coming back to a running chat shows the work instead of an empty panel. */
  const t = S.turns[S.active];
  if (t) for (const n of t.nodes) box.appendChild(n);
  /* The ticker stops itself the moment no clock is on screen (see `clockTick`). A chat that was
     running while you were looking at another one had its clock nodes detached, so the scan found
     nothing and the ticker died — coming back here must restart it, or the clock shows a stale 0s
     and the turn looks hung. `clockStart` with no node just restarts the ticker; the start time is
     kept on the node, so this resumes the count, it does not reset it. */
  if (!clockTimer && box.querySelector(".telapsed[data-since]")) clockStart();
  /* Where the panel lands is the reader's call, not the redraw's: at the bottom if they were following
     it, otherwise back exactly where they were, with the pill to say there is newer output below. */
  if (pinned) toBottom(box);
  else {
    const sb = box.style.scrollBehavior;
    box.style.scrollBehavior = "auto"; box.scrollTop = keep; box.style.scrollBehavior = sb;
    $("#jump").hidden = false;
  }
}
/* The answer as it is written. Each delta is appended to the bubble the turn already opened for
   that bot and repainted at most every STREAM_MS — not on every token, and not on every frame
   either: re-parsing the whole answer (markdown plus a full subtree rebuild) each frame is O(n²)
   over the length of the message, which is what makes a big report jank as it streams in. A trailing
   paint is scheduled so the last words are not left unpainted while the model pauses. The final
   `agent_text` — the whole message — replaces that bubble and gives it its actions. */
const STREAM_MS = 120;
function streamText(ev, who, to, T, sid) {
  const box = to || MSGS;
  const live = (T.live = T.live || {});
  const key = (ev.to || "") + "\u0000" + (ev.agent || "");
  let d = live[key];
  if (ev.delta) {
    if (!d) {
      d = el("div", "m bot");
      d.appendChild(el("div", "who", hueSpan(who || "", "wn", hueOf(who, sid)) + `<span class="mts">${stampAt(Date.now())}</span>`));
      d.appendChild(el("div", "md"));
      d.dataset.raw = ""; d._box = box;
      live[key] = d; box.add(d);
    }
    d.dataset.raw += ev.text;
    const paint = () => { d._paint = 0; d._painted = performance.now();
      d.querySelector(".md").innerHTML = mdToHtml(d.dataset.raw); d._box.scroll(); };
    const since = performance.now() - (d._painted || 0);
    if (since >= STREAM_MS) paint();
    else if (!d._paint) d._paint = setTimeout(paint, STREAM_MS - since);
    return;
  }
  delete live[key];
  if (!ev.text.trim()) { if (d) d.remove(); return; }
  if (!d) { addMsg("assistant", ev.text, who, to, null, sid); return; }
  if (d._paint) { clearTimeout(d._paint); d._paint = 0; }
  d.dataset.raw = ev.text;
  d.querySelector(".md").innerHTML = mdToHtml(ev.text);
  msgActs(d, who || "", ev.text, "assistant");
  box.scroll();
}
/* What your own messages are labelled with. Set in Settings → General, and "Client" until you name
   yourself, so a transcript never shows a nameless bubble. */
const userName = () => (S.settings.user_name || "").trim() || "Client";
function addMsg(role, text, who, to, meta, sid) {
  const box = to || MSGS;
  const d = el("div", "m " + (role === "user" ? "user" : "bot"));
  if (meta && meta.quote) d.appendChild(quoteBlock(meta.quote));
  if (meta && meta.fwd) d.appendChild(el("div", "fwd", "↪ Forwarded"));
  /* When it landed. A message redrawn from the transcript carries the server's own stamp; one drawn
     as it is sent is stamped now, which is the same moment to within the round-trip. */
  const when = stampAt(meta && meta.ts ? meta.ts * 1000 : Date.now());
  /* A user message carries no `who` — it is yours — so it wears the name you set, defaulting to
     "Client". Naming it also gives the header line real content: an empty header collapsed to zero
     height, which left the timestamp sitting right on the first line of text. */
  const label = who || (role === "user" ? userName() : "");
  /* Yours is not a bot's name, so it never takes a hue — even if you named yourself after one. The
     guard is the role, not the string: a person and a bot can share a name. */
  const hue = role === "user" ? null : hueOf(label, sid || S.active);
  if (label) d.appendChild(el("div", "who", hueSpan(label, "wn", hue) + `<span class="mts">${when}</span>`));
  else d.appendChild(el("div", "who", `<span class="mts">${when}</span>`));
  /* A bot writes markdown, so its reply is rendered. A person types plain text, which is shown
     exactly as typed — a shell command with an asterisk must not come back italic. Only a URL in it
     is dressed up, because a URL you cannot click is the one thing plain text gets wrong. */
  if (role === "user") d.appendChild(el("span", "", linkify(text)));
  else d.appendChild(el("div", "md", mdToHtml(text || "")));
  if (role !== "user" && text && text.length > 40 && S.settings.voice && S.settings.voice.auto) {
    const sp = el("button", "speak", `${svg("speaker")} Listen`); sp.onclick = () => speak(text); d.appendChild(sp);
  }
  msgActs(d, label, text || "", role, meta && meta.i);
  box.add(d); box.scroll(); return d;
}
/* What you can do with a message once it is there: answer it, pass it on, copy it — and for the two
   ends of a turn, take it back. Edit puts a message of yours in the composer and forgets everything
   after it; Retry forgets a reply and asks the same question again. Both go through the server's
   truncate, so the transcript on disk matches what is on screen. `i` is the message's place in the
   saved history, which a message that arrived during a turn does not have yet — see reloadTranscript. */
function msgActs(d, who, text, role, i) {
  const acts = el("div", "acts");
  const r = el("button", "ab", "Reply");
  r.title = "Quote this message in your reply";
  r.onclick = () => quoteMsg(who, text);
  const f = el("button", "ab", "Forward");
  f.title = "Send a copy of this message to another chat";
  f.onclick = () => forwardMsg(who, text);
  acts.append(r, f);
  const c = el("button", "ab", "Copy");
  c.title = "Copy this message";
  c.onclick = () => copyText(text, c);
  acts.appendChild(c);
  if (i != null && role === "user") {
    const e = el("button", "ab", "Edit");
    e.title = "Put this message back in the composer and drop everything after it";
    e.onclick = () => editMsg(i);
    acts.appendChild(e);
  }
  if (i != null && role !== "user") {
    const t = el("button", "ab", "Retry");
    t.title = "Drop this reply and ask again";
    t.onclick = () => retryMsg(i);
    acts.appendChild(t);
  }
  d.appendChild(acts); return d;
}
/* Copying says so on the button itself: a clipboard write has no other visible effect, and a click
   that appears to do nothing is a click people make twice. It answers with whether the copy landed,
   for the callers that have no button to say it on and report through `showTip` instead. */
async function copyText(text, btn) {
  let ok = true;
  try { await navigator.clipboard.writeText(text || ""); }
  catch (e) {
    /* A page served from disk has no clipboard permission in some builds, so fall back to the one
       copy the platform always allows: a selected textarea and execCommand. */
    const ta = el("textarea"); ta.value = text || ""; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); } catch (_) { ok = false; }
    ta.remove();
  }
  if (!btn) return ok;
  const was = btn.textContent; btn.textContent = "Copied";
  setTimeout(() => { btn.textContent = was; }, 1200);
}
/* Forgetting the tail of a transcript is the server's call, so it is asked first and the answer is
   what is drawn — the two can never disagree about where the chat now ends. */
async function truncateAt(keep) {
  const r = await jpost("/api/history/truncate", { session: S.active, keep });
  if (r.ok === false) { alert(r.error || "Could not change this chat."); return false; }
  S.messages = r.messages || []; return true;
}
async function editMsg(i) {
  if (busy(S.active)) { alert("This chat is working on a turn. Stop it, or wait for it to finish."); return; }
  const m = S.messages[i]; if (!m) return;
  if (!await truncateAt(i)) return;
  pinned = true;                 // the tail just changed: this redraw lands at the newest message
  render(S.messages, null);
  $("#input").value = m.content || "";
  autoGrow($("#input"));
  $("#input").focus(); $("#input").setSelectionRange($("#input").value.length, $("#input").value.length);
}
async function retryMsg(i) {
  if (busy(S.active)) { alert("This chat is working on a turn. Stop it, or wait for it to finish."); return; }
  let u = -1;
  for (let k = i - 1; k >= 0; k--) if (S.messages[k] && S.messages[k].role === "user") { u = k; break; }
  if (u < 0) { alert("There is no message to ask again."); return; }
  const m = S.messages[u];
  const opts = (m.quote || m.fwd) ? { quote: m.quote, fwd: m.fwd } : null;
  if (!await truncateAt(u)) return;
  pinned = true;                 // asking again puts you back at the live end of the chat
  render(S.messages, null);
  await deliver(S.active, m.content || "", opts);
}
/* The quoted message, drawn above the reply that answers it — the same two lines you get when you
   quote someone in any chat app, so the reply is readable on its own. */
function quoteBlock(q) {
  const b = el("div", "quote");
  b.appendChild(el("div", "qw", esc(q.who || "Message")));
  b.appendChild(el("div", "qt", esc((q.text || "").replace(/\s+/g, " ").trim().slice(0, 180))));
  return b;
}
/* What a hand-off card is headed. It answers "who is handling this", which is not a plan — nothing
   has been planned when it is drawn — so it is never headed as one. That mismatch is what made every
   room message open with a PLAN card for a plan nobody had written. */
const ROUTE_LABEL = "Who's on it";
/* `raw` names which of the two strings is already-escaped HTML, and is left off when neither is. A
   card that names a bot needs it: the name carries its own `<span>`, and escaping it again would
   print the markup. It is the header on a plan or a report and the notice line on a hand-off, so the
   two are named rather than merged — the other string stays plain text and is escaped here, and the
   quote the card's actions carry stays words rather than markup. */
function addCard(cls, label, text, to, raw) {
  const box = to || MSGS;
  const d = el("div", "m bot " + cls);
  d.innerHTML = `<div class="who">${raw === "label" ? label : esc(label)}</div>`;
  d.appendChild(el("div", "md", mdToHtml(text || "", raw === "text")));
  const words = raw === "label" ? label.replace(/<[^>]*>/g, "") : label;
  /* A plan and a report are the two cards you would actually want to answer or pass on, so they
     carry the same two actions a message does; a system note is not a message and does not. A
     hand-off is a notice, like the "started" line, so it carries none either. */
  if (cls === "plan" && words !== ROUTE_LABEL) msgActs(d, words, text || "");
  else if (cls === "final") msgActs(d, /^Room · summary$/.test(words) ? "the room" : words.replace(/ · report$/, ""), text || "");
  box.add(d); box.scroll(); return d;
}
/* One tool call, as one line until you open it. The server sends each call twice — once when it
   starts (`out` null) and once with the result — under the same `id`, so the first event makes the
   row and the second fills it rather than drawing a second row for the same command. `to.tools`
   is that per-sink index, so a room's delegated work keeps its own rows in the member's chat. */
const TOOL_LABEL = { run_shell:"shell", browser_open:"browser · open", browser_read:"browser · read",
  browser_click:"browser · click", browser_type:"browser · type", browser_press:"browser · key",
  browser_back:"browser · back", browser_see:"browser · look", browser_eval:"browser · eval", read_file:"read file",
  write_file:"write file", list_files:"list files", generate_image:"draw image", memory_update:"memory",
  use_skill:"read skill", delegate:"delegate",
  gmail_api:"gmail · api", slack_api:"slack · api", github_api:"github · api", notion_api:"notion · api",
  linear_api:"linear · api", drive_api:"gdrive · api", calendar_api:"calendar · api", webhook_post:"webhook · post" };
const TOOL_ICON = { run_shell:"menu", read_file:"eye", write_file:"edit", list_files:"apps",
  generate_image:"apps", memory_update:"memory", use_skill:"skills", delegate:"bots", browser_see:"eye", browser_open:"monitor" };
function toolHead(name, args) {
  if (name === "run_shell") return "$ " + (args.command || "");
  if (name === "browser_open") return args.url || "";
  if (name === "browser_click" || name === "browser_type") return args.selector || "";
  if (name === "browser_press") return args.key || "";
  if (name === "read_file" || name === "write_file" || name === "list_files") return args.path || "";
  if (name === "memory_update") return args.note || "";
  if (name === "browser_see") return args.question || "";
  if (name === "generate_image") return args.prompt || "";
  if (name === "use_skill") return (args.skill || "") + (args.file ? " · " + args.file : "");
  if (name === "delegate") return "→ " + NAME(args.role) + ": " + (args.task || "");
  return JSON.stringify(args).slice(0, 200);
}
/* A write is shown as what changed, not as the whole file: the untouched head and tail are trimmed
   away and only the edited stretch is drawn, deletions first. Enough to see what the bot did to a
   file without reading the file. */
function diffHtml(before, after) {
  const a = String(before == null ? "" : before).replace(/\r\n?/g, "\n").split("\n");
  const b = String(after == null ? "" : after).replace(/\r\n?/g, "\n").split("\n");
  let s = 0; while (s < a.length && s < b.length && a[s] === b[s]) s++;
  let e = 0; while (e < a.length - s && e < b.length - s && a[a.length - 1 - e] === b[b.length - 1 - e]) e++;
  const rows = [];
  for (const l of a.slice(Math.max(0, s - 2), s)) rows.push(`<span class="dl dctx">  ${esc(l)}</span>`);
  const del = a.slice(s, a.length - e), add = b.slice(s, b.length - e);
  for (const l of del) rows.push(`<span class="dl ddel">- ${esc(l)}</span>`);
  for (const l of add) rows.push(`<span class="dl dadd">+ ${esc(l)}</span>`);
  if (!del.length && !add.length) rows.push(`<span class="dl dctx">(no change)</span>`);
  return `<div class="dh">changes</div>` + rows.join("");
}
function addTool(agent, name, args, out, to, id) {
  const box = to || MSGS;
  const map = (box.tools = box.tools || {});
  if (id && map[id]) return fillTool(map[id], name, args, out);
  const label = TOOL_LABEL[name] || name;
  const head = toolHead(name, args);
  const d = el("div", "m bot tool");
  d.innerHTML = `<button class="thead" type="button" aria-expanded="false">
      <span class="tico">${svg(TOOL_ICON[name] || "caret")}</span>
      <span class="tmain"><span class="who">${esc(NAME(agent))} · ${esc(label)}</span><span class="h" title="${esc(head)}">${esc(head)}</span></span>
      <span class="telapsed"></span><span class="tstate"></span><span class="tcaret">${svg("caret")}</span>
    </button><div class="tbody"></div>`;
  const head_ = d.querySelector(".thead");
  head_.onclick = () => { d.classList.toggle("open"); head_.setAttribute("aria-expanded", d.classList.contains("open") ? "true" : "false"); };
  if (id) map[id] = d;
  fillTool(d, name, args, out);
  box.add(d); box.scroll(); return d;
}
/* The result half of a tool row: the output, or — for a write — the diff of the file. Called once
   when the row is made (with no result yet) and again when the result arrives. */
/* Whether the row reads done or failed. run_shell states its outcome exactly — the server prefixes
   `exit N` — so that is read rather than guessed. Every other refusal is a parenthesised note the tool
   wrote ("(no such file)", "(the tool … failed)"), and `(empty)` is the one such note that is a
   result, not a failure. Matching the word "error" anywhere in the output (as this once did) flagged
   honest results like "0 errors". */
function toolFailed(name, out) {
  const s = String(out == null ? "" : out);
  if (name === "run_shell") { const m = s.match(/^exit (\d+)/); return !!m && m[1] !== "0"; }
  return s.startsWith("(") && s !== "(empty)";
}
function fillTool(d, name, args, out) {
  const st = d.querySelector(".tstate"), body = d.querySelector(".tbody");
  if (out == null) { st.innerHTML = `<span class="spin" title="running"></span>`; clockStart(d.querySelector(".telapsed")); return d; }
  clockStop(d.querySelector(".telapsed"));
  body.innerHTML = "";
  const failed = toolFailed(name, out);
  st.className = "tstate " + (failed ? "err" : "ok");
  st.textContent = failed ? "failed" : "done";
  /* A failure the user cannot read is a failure they will re-run. The row is built closed, so open it
     here — the reason is in the body, and a red "failed" chip on a folded row says only that something
     went wrong, not what. */
  if (failed) {
    d.classList.add("open");
    const h = d.querySelector(".thead"); if (h) h.setAttribute("aria-expanded", "true");
  }
  if (name === "write_file" && args.before != null && args.content != null && args.before !== args.content) {
    const df = el("div", "diff"); df.innerHTML = diffHtml(args.before, args.content); body.appendChild(df);
  }
  if (out !== "") {
    const pre = el("pre", "out");
    pre.textContent = out.length > 4000 ? out.slice(0, 4000) + "…" : out;
    body.appendChild(pre);
  }
  return d;
}
function addShot(png, note, title, to) {
  const box = to || MSGS;
  const d = el("div", "m bot shot");
  d.innerHTML = `<div class="who">${esc(title || "Browser · screenshot")}</div>`;
  const im = el("img"); im.src = png; im.alt = title === "Image" ? "generated image" : "page screenshot"; d.appendChild(im);
  if (note) d.appendChild(el("div", "note", (title === "Image" ? "Prompt: " : "Seen: ") + esc(note)));
  box.add(d); box.scroll();
}
function addApproval(cmd, agent, to) {
  const box = to || MSGS;
  const d = el("div", "approval");
  d.innerHTML = `<div class="t">${svg("warn")} ${agent ? esc(NAME(agent)) + " wants" : "Bot wants"} to run a command</div>
    <code>${esc(cmd)}</code>
    <div class="row"><button class="btn allow">Allow</button><button class="btn deny">Deny</button></div>`;
  d.querySelector(".allow").onclick = () => resolveApproval(true, d);
  d.querySelector(".deny").onclick = () => resolveApproval(false, d);
  box.add(d); box.scroll();
  /* The dock only wears "needs your approval" when the card is actually on screen — a card waiting
     in a chat you are not looking at has not asked you anything yet. */
  if (!to || to.shown()) setDock("approval");
}
/* A plan-only turn ends with a plan and nothing done. This is how the plan is accepted: the chat is
   switched to full access, and the bot is told to go — the plan it just wrote is the instruction, so
   it is handed back as the message rather than re-described. `sid` is the chat that made the plan,
   which is not necessarily the one on screen if you switched away while it was working. */
function addPlanApprove(card, sid) {
  const row = el("div", "row"); row.style.marginTop = "10px";
  const go = el("button", "btn pri sm", "Approve plan and run it");
  const note = el("span", "desc", "Switches this chat to full access, then runs the plan.");
  go.onclick = async () => {
    if (sid !== S.active) return select(sid);      // act on the chat that made the plan, never another
    go.disabled = true; go.textContent = "Approving…";
    await post("/api/approval_mode", { session: sid, mode: "full" });
    S.approval = "full"; S.approvalSet = true; chipApproval();
    row.remove();
    $("#input").value = "Approved — go ahead and execute the plan you just made.";
    send();
  };
  row.append(go, note);
  card.appendChild(row);
}

/* ---------------- SSE ---------------- */
/* A dropped connection has no words a person can use: Firefox reports it as the literal string
   "NetworkError when attempting to fetch resource." and Chrome as "Failed to fetch". So that text is
   never shown — the app says what actually happened instead. `started` keeps the two cases of a turn
   apart, because they mean different things: a request that never got a reply never began, while one
   that dropped mid-stream may well still be running on the server. */
const NET_RE = /NetworkError|Failed to fetch|Load failed|Network request failed|net::ERR_/i;
function isOffline(e) {
  const raw = String((e && e.message) || e || "");
  return NET_RE.test(raw) || (e && e.name) === "AbortError" || /aborted/i.test(raw);
}
function humanErr(text) { const e = new Error(text); e.human = true; return e; }
function offlineTurn(started) {
  return humanErr(started
    ? "The connection to the server dropped part-way through this turn. The bot may still be working on it — open this chat again in a moment to see, or send your message again to retry."
    : "Could not reach the server, so this turn never started. It may be restarting — try again in a moment.");
}
async function stream(path, payload, onEvent, T) {
  let res;
  try {
    res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  } catch (e) { throw isOffline(e) ? offlineTurn(false) : e; }
  if (!res.ok) throw humanErr("The server refused this turn (HTTP " + res.status + "). Try again in a moment.");
  if (!res.body) throw humanErr("The server sent a reply this browser cannot read.");
  const rd = res.body.getReader(); const dec = new TextDecoder(); let buf = "";
  /* Stop walks away from the stream. The server notices the dropped connection and ends the turn;
     cancelling the reader is what carries that over both transports — a plain fetch closes the
     socket, and the desktop bridge cancels the IPC request behind the same call. */
  if (T) { T.reader = rd; if (T.stopped) { try { rd.cancel(); } catch (e) {} } }
  while (true) {
    let r; try { r = await rd.read(); } catch (e) { if (T && T.stopped) return; throw isOffline(e) ? offlineTurn(true) : e; }
    const { done, value } = r; if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
      if (chunk.startsWith("data: ")) { try { onEvent(JSON.parse(chunk.slice(6))); } catch (e) {} }
    }
  }
}
/* One place that puts a message into a chat — typed, forwarded, or a reply with a quote attached.
   `opts` carries `quote` and/or `fwd`, which travel with the message to the server and are kept on
   it, so the transcript draws back the same thing you sent. Only a chat whose *own* turn is already
   running holds the message in its queue; a task in another chat goes now, because that other chat's
   turn is not this one's business. */
async function deliver(sid, text, opts) {
  const o = opts || {};
  if (busy(sid)) return queueAdd(sid, text, o);
  /* Sending is the reader asking for the newest message. Whatever they had scrolled back to, their own
     words are the one thing that must not land below the fold — and re-pinning here is also what makes
     the bot's answer to them follow. */
  if (sid === S.active) { pinned = true; addMsg("user", text, null, null, o); }
  const b = chan(sid) ? null : botOf(sid);
  await runChat("/api/chat", { session: sid, bot: b ? b.id : undefined, text, ...o });
}
async function send() {
  const text = $("#input").value.trim(); if (!text) return;
  closeMention();                                        // the picker is for the text just sent
  $("#input").value = ""; $("#input").style.height = "auto";
  const q = S.reply; S.reply = null; renderReply();      // the quote goes with this one message only
  await deliver(S.active, text, q ? { quote: q } : null);
}

/* ---------------- quote and forward ---------------- */
/* A reply carries the message it answers, so the bot — which never sees the transcript — is told
   what "this" points at. A forward is the same text delivered to another chat, where it is drawn
   with a Forwarded mark and picked up like anything else you send there. */
function quoteMsg(who, text) {
  S.reply = { who: who || "", text: text || "" };
  renderReply(); $("#input").focus();
}
function renderReply() {
  const box = $("#reply"); if (!box) return;
  const q = S.reply;
  box.hidden = !q; box.innerHTML = "";
  if (!q) return;
  const body = el("div", "rtext");
  body.appendChild(el("div", "rw", esc(q.who || "Message")));
  body.appendChild(el("div", "rt", esc(q.text)));
  box.appendChild(body);
  const x = el("button", "rx", "×");
  x.title = "Cancel the reply"; x.setAttribute("aria-label", "Cancel the reply");
  x.onclick = () => { S.reply = null; renderReply(); $("#input").focus(); };
  box.appendChild(x);
}
/* Every pick-style dialog is the same shell — a scrim, a titled head with a close X, a body and a
   foot — so the shell, the Escape/scrim-click close, the focus trap and the focus hand-back all live
   in one place instead of three. Returns the modal so the caller can fill the body. */
function openPick({ icon, title, body, foot }) {
  const scrim = el("div", "scrim on");
  const modal = el("div", "modal pick");
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");
  modal.setAttribute("aria-label", title);
  modal.innerHTML = `<div class="mhead"><span class="ico">${svg(icon)}</span><h2>${esc(title)}</h2>
    <button class="x" aria-label="Close">×</button></div>
    <div class="bpick">${body}</div>${foot ? `<div class="bfoot">${foot}</div>` : ""}`;
  scrim.appendChild(modal); document.body.appendChild(scrim); document.body.classList.add("overlay");
  const prev = document.activeElement;
  const close = () => {
    scrim.remove(); document.removeEventListener("keydown", onKey);
    if (!$("#scrim").classList.contains("on")) document.body.classList.remove("overlay");
    if (prev && prev.focus) prev.focus();
  };
  const onKey = e => {
    if (e.key === "Escape") return close();
    if (e.key === "Tab") trapTab(modal, e);
  };
  document.addEventListener("keydown", onKey);
  scrim.onclick = e => { if (e.target === scrim) close(); };
  modal.querySelector(".x").onclick = close;
  (modal.querySelector("button:not(.x), input, [tabindex]") || modal.querySelector(".x")).focus();
  return { modal, close };
}
/* Forwarding is delivering a copy somewhere else: pick the chat, and the message goes there and is
   picked up exactly as if you had sent it — queued if that chat is busy, run if it is not. */
function forwardMsg(who, text) {
  const targets = [];
  for (const c of S.channels) targets.push({ id: c.id, name: c.name, sub: (c.members || []).length + " members", group: "Rooms" });
  for (const b of S.bots) if (!b.hidden) targets.push({ id: b.id, name: b.name, sub: b.title || b.role || "", group: "Chats" });
  const { modal, close } = openPick({
    icon: "caret", title: "Forward to…",
    body: `<div class="fwdprev">${esc((who ? who + ": " : "") + text)}</div><div class="blist" data-a="list"></div>`,
    foot: `<span class="hint">It arrives as your message, and is picked up as a task.</span>`,
  });
  const listEl = modal.querySelector('[data-a="list"]');
  for (const g of ["Rooms", "Chats"]) {
    const rows = targets.filter(t => t.group === g && t.id !== S.active);   // not back into itself
    if (!rows.length) continue;
    listEl.appendChild(el("div", "brow dim", g));
    for (const t of rows) {
      const row = el("div", "brow", `<span class="bico">${svg("caret")}</span><b>${esc(t.name)}</b>` +
        (t.sub ? ` <span class="dim">${esc(t.sub)}</span>` : ""));
      row.onclick = () => { close(); deliver(t.id, text, { fwd: true }); };
      kbd(row, row.onclick);
      listEl.appendChild(row);
    }
  }
}

/* ---------------- who is working, right now ----------------
   A room runs several bots at once, and the only sign of it used to be a hand-off card per member
   that sat unchanged for as long as that member's step took — minutes of a room looking quiet while
   somebody worked. This strip is the live thing instead: one row per bot working in the room on
   screen, updated in place and gone the moment that bot is done. It sits above the box you type in
   rather than in the transcript, because a bot does dozens of things in a turn and a line printed
   per thing would bury the conversation it is working on. Keyed on the bot id, which every event
   carries — a display name can be edited mid-turn, and two members of one room can share one, so a
   row keyed on the name would be a row that loses its bot.
   A room only. In a 1:1 chat the header already names the bot and its state, and a second indicator
   for one fact is one too many. */
const WORKING = new Map();   // bot id -> the row's own parts, so an update is a text change, not a redraw
const workingBox = () => $("#working");

/* What the bot is doing, as one line: the tool it last called, said the way the transcript says it
   (toolHead), and — only while it has called nothing — the first sentence of the last thing it said,
   which is the sentence that says what it is about to do. Nothing here is sliced: the row clips with
   CSS, and a slice under an ellipsis ends the same line twice. */
const firstSentence = t => {
  const s = String(t || "").replace(/\s+/g, " ").trim();   // collapsed first, so a newline cannot end it early
  const m = s.match(/^.*?[.!?](?=\s|$)/);
  return m ? m[0] : s;
};
function workingAct(r) {
  const a = r.tool || firstSentence(r.text);
  r.act.textContent = a ? "— " + a : "";
}
/* The row, built once and then only edited: the clock's start time lives on its own element, so a row
   rebuilt on every event would restart the clock and a long step would never read as long. */
function workingRow(id) {
  let r = WORKING.get(id);
  if (r) return r;
  const box = workingBox(); if (!box) return null;
  const b = bot(id) || {}, name = b.name || NAME(id);
  const row = el("div", "wrow"); row.dataset.agent = id;
  row.innerHTML = `<span class="spin" aria-hidden="true"></span>`
    + hueSpan(name, "wname", hueOf(name, S.active))
    /* Each part carries the separator in front of it, so a bot with no title — or with nothing to show
       yet — leaves no dangling `·` behind: the separator goes when the thing it separates does. */
    + `<span class="wtitle"></span><span class="wact"></span><span class="wphase"></span>`
    + `<span class="wdot" aria-hidden="true">·</span>`
    /* The clock changes every second, and a screen reader walked into this region would be read a new
       number every time it moved — the same reason the transcript is `aria-live="off"`. The phase
       beside it is text, so what a row means never rests on the clock or on the pulse. */
    + `<span class="telapsed" aria-hidden="true"></span>`;
  r = { row, title: row.querySelector(".wtitle"), act: row.querySelector(".wact"),
        phase: row.querySelector(".wphase"), clock: row.querySelector(".telapsed"), tool: "", text: "" };
  r.phase.textContent = "· " + STEP_LABEL.working;      // a bot that has just been handed work is working
  const t = (b.title || "").trim();
  if (t) r.title.textContent = "· " + t;
  box.appendChild(row); box.hidden = false;
  clockStart(r.clock);
  WORKING.set(id, r);
  return r;
}
function workingDrop(id) {
  const r = WORKING.get(id); if (!r) return;
  r.row.remove(); WORKING.delete(id);
  const box = workingBox(); if (box && !WORKING.size) box.hidden = true;
}
/* The strip is the live view, and the transcript's record takes over the moment a turn lands — so
   nothing here outlives one. */
function workingClear() { for (const id of [...WORKING.keys()]) workingDrop(id); }
/* One event, folded onto its bot's row. Called for every event of a turn that has not been stopped. */
function liveEvent(sid, ev) {
  if (sid !== S.active || !chan(sid)) return;          // a room, and the room on screen
  /* The turn itself is over — checked before the bot is looked for, because these two events carry
     no `agent` and the guard below would swallow them, leaving the strip up over a finished turn. */
  if (ev.type === "final" || ev.type === "error") { workingClear(); return; }
  const id = ev.agent || (ev.type === "agent" ? ev.id : null);
  if (!id) return;                                     // a room-level status names no bot to put it on
  if (ev.type === "agent" && ev.state === "done") { workingDrop(id); return; }
  const r = workingRow(id); if (!r) return;
  if (ev.type === "status") { if (STEP_LABEL[ev.state]) r.phase.textContent = "· " + STEP_LABEL[ev.state]; }
  /* The approval phase comes from the `approval` event, which names its bot, and not from the
     `status` beside it, which does not — a member waiting on your decision is the one case where the
     phase matters most, and that status would leave the row reading "Working…" while it waits. */
  else if (ev.type === "approval") r.phase.textContent = "· " + STEP_LABEL.approval;
  else if (ev.type === "tool") { r.tool = toolHead(ev.name, ev.args || {}); workingAct(r); }
  /* A delta appends onto the block in progress and a whole block replaces it, so this holds the last
     thing the bot said rather than a fragment of it. */
  else if (ev.type === "agent_text" && ev.text) { r.text = ev.delta ? r.text + ev.text : ev.text; workingAct(r); }
}

/* ---------------- the queue ---------------- */
/* Steering and queueing are the same list with two outcomes: leave it and the task runs after the
   turn that is already going; steer it and the running turn is handed it now, at its next step,
   so it changes direction mid-task instead of starting a second one. */
let _qid = 0;   // a stable id per queued task, so a row's buttons act on *its* task, not on whatever
                // index that task happens to sit at by the time you click — a shift or a removal
                // between render and click used to make "Steer now" steer the neighbour.
function queueAdd(sid, text, opts) {
  (S.queue[sid] = S.queue[sid] || []).push({ id: ++_qid, text, opts: opts || {} });
  if (sid === S.active) renderQueue();
}
/* Where a steer ends up is the server's call, so the row is cleared by the `steer` event coming
   back rather than by the click: a steer that arrived too late stays queued and simply runs next. */
function steerLanded(sid, text) {
  const q = S.queue[sid]; if (!q) return;
  let i = q.findIndex(x => x.text === text && x.steering);
  if (i < 0) i = q.findIndex(x => x.text === text);
  if (i >= 0) { q.splice(i, 1); if (sid === S.active) renderQueue(); }
}
function renderQueue() {
  const box = $("#queue"); if (!box) return;
  const q = S.queue[S.active] || [];
  box.hidden = !q.length; box.innerHTML = "";
  if (!q.length) return;
  box.appendChild(el("div", "qhead", q.length === 1 ? "1 task queued" : q.length + " tasks queued"));
  q.forEach(it => {
    const row = el("div", "qitem");
    row.appendChild(el("span", "qtext", esc((it.opts && it.opts.fwd ? "↪ " : "") + it.text)));
    /* The row is what the click leaves on screen, so it says what the click did: the turn has it and
       hands it over at its next step. It deliberately does not say the message arrived — that is the
       turn's own `steer` event to claim (see `steerNow`), and the wording must not claim it first. */
    if (it.steering) row.appendChild(el("span", "qnote", `<span class="spin"></span> taken — handing over…`));
    else {
      const s = el("button", "qsteer", "Steer now");
      s.title = "Hand this to the running task now instead of waiting for it to finish";
      s.onclick = () => steerNow(it.id);
      row.appendChild(s);
    }
    const x = el("button", "qx", "×");
    x.title = "Remove from the queue"; x.setAttribute("aria-label", "Remove from the queue");
    x.onclick = () => { const i = q.findIndex(z => z.id === it.id); if (i >= 0) { q.splice(i, 1); renderQueue(); } };
    row.appendChild(x);
    box.appendChild(row);
  });
  box.appendChild(el("div", "qhint", "Runs when the current task finishes."));
}
/* Remove one queued task by its stable id — never by index, which shifts under the row you clicked.
   Says whether it was still there: the caller needs to know that it, and not the turn's own drain,
   was the one that took the task off the queue. */
function queueDrop(sid, id) {
  const q = S.queue[sid]; if (!q) return false;
  const i = q.findIndex(z => z.id === id);
  if (i < 0) return false;
  q.splice(i, 1); if (sid === S.active) renderQueue(); return true;
}
async function steerNow(id) {
  const q = S.queue[S.active] || []; const it = q.find(x => x.id === id); if (!it) return;
  it.steering = true; renderQueue();
  let r = {};
  try { r = await jpost("/api/chat/steer", { session: S.active, text: it.text, ...(it.opts || {}) }); }
  catch (e) { r = {}; }
  /* A steer the turn took is not drawn here: the row stays marked as taken and the turn's own
     `steer` event lands it — the message on screen and the row gone — when the bot actually reaches
     it. Claiming the click as done before then is what made a steer look like it had worked while
     the message was still nowhere: the row went, the message was drawn, and both came back empty. */
  if (r.ok) return;
  it.steering = false;
  if (busy(S.active)) return renderQueue();   // this chat's turn still holds the slot — stay queued
  /* Nothing left to steer: the turn had already written its last word, so send it now — which is
     what steering meant anyway, just without a turn to interrupt. If the row is already gone, the
     turn's own `drainQueue` took it while this request was in flight, and sending it here as well
     would run the same task twice. */
  if (!queueDrop(S.active, id)) return;
  await deliver(S.active, it.text, it.opts);
}
/* The turn that just ended drains its own chat's queue, and only its own: the tasks waiting on *this*
   turn go now, while a task queued in another chat keeps waiting on that chat's own turn. */
function drainQueue(sid) {
  const q = S.queue[sid]; if (!q || !q.length) return;
  const it = q.shift(); if (sid === S.active) renderQueue();
  deliver(sid, it.text, it.opts);
}
async function resolveApproval(allow, node) {
  node.querySelectorAll("button").forEach(b => b.disabled = true);
  node.querySelector(".t").textContent = allow ? "Allowed" : "Denied";
  const b = S.activeIsChannel ? null : botOf(S.active);
  /* A failed answer must not leave the card frozen with both buttons greyed out. Only the approve
     call is retried-safe to re-open — a history read that failed afterwards means the answer did land,
     so the card stays closed and just keeps its wording. */
  try {
    await post("/api/approve", { session: S.active, bot: b ? b.id : undefined, allow });
  } catch (e) {
    node.querySelectorAll("button").forEach(x => x.disabled = false);
    node.querySelector(".t").textContent = "Could not send that answer — try again";
    return;
  }
  if (!allow) setDock("idle");
  /* The answer landed; if the follow-up read failed the card keeps its closed wording, which is
     right — only a failed *answer* re-opens it. */
  const h = await get("/api/history?session=" + encodeURIComponent(S.active));
  if (h) applyApproval(h, S.active);
}
/* One turn, bound to the chat it was started in. Every card it streams goes to that chat's sink,
   never to "whatever is on screen now", so switching chats mid-turn neither scatters the output
   into the wrong transcript nor throws it away: the header, the dock and the composer follow the
   chat you are looking at, and the running chat keeps drawing into its own kept nodes. */
/* One turn event, drawn. A turn's cards are drawn through here whether this window is the one
   running the turn or is watching another client's — the server streams the same events to both —
   so the tool rows and the answer being written look the same on the phone as on the desktop. `T`
   is the chat's turn state; `to` routes a room's delegated work into the member's own chat. */
function drawTurnEvent(sid, T, ev) {
  const isChan = !!chan(sid), here = () => sid === S.active;
  /* The live strip is fed from here, on the way in, so it sees every event exactly once and in the
     order it arrived. A turn the user has stopped is not fed: Stop already took its rows down, and a
     step still in flight on the way to landing must not put them back. */
  if (!T.stopped) liveEvent(sid, ev);
  const own = turnSink(sid);
  /* A turn happens inside one company (or none). Events name a bot; the sidebar row that lights
     up is that bot inside that company — so a room turn animates its own members, not the copies
     of the same bot living under another company. */
  const scope = isChan ? sid : scopeOf(sid);
  /* A delegation never leaves the room's own members, so this is the scoped row — the fallback is
     for a bot whose row has not been drawn yet, not for one outside the company. */
  const row = id => { const k = scope ? scope + "/" + id : id; return S.sideMochi[k] ? k : id; };
  /* A room's turn hands each member's *steps* to that member's chat (`to`) — the shell logs and
     screenshots land where you would look for them — while the words each one says stay in the room,
     because that is the conversation the channel exists for. */
  const to = ev.to ? subSink(T, ev.to) : own;
  const who = ev.agent ? NAME(ev.agent) : null;
  if (ev.type === "status") { T.asking = false; setState(sid, ev.state); stepSet(to, T, ev.state);
    if (!isChan) sideSet(sid, ev.state); if (!here()) refreshHead(); }
  /* A plan card is headed with whose plan it is, so "whose is this?" has its answer on the card
     rather than leaving you to guess. A hand-off is headed for what it is instead. */
  else if (ev.type === "plan") { const named = !!(ev.agent && ev.kind !== "route");
    T.plan = addCard("plan",
      named ? hueSpan(NAME(ev.agent), "", hueOf(NAME(ev.agent), sid)) + "'s plan" : (ev.kind === "route" ? ROUTE_LABEL : "Plan"),
      cleanBot(ev.text), to, named ? "label" : undefined); }
  else if (ev.type === "agent" && ev.state === "start") { setState(row(ev.id), "working"); sideSet(row(ev.id), "working");
    if (isChan && here()) { setDock("working"); setHead(hSub(H_STATE.working)); $("#hDot").classList.add("live"); }
    /* A hand-off names what was handed over: a teammate's name with no task under it leaves the room
       showing a delegation to nothing, which is half the reason a room read as silent. The other half
       — that the card then sat unchanged for as long as that teammate's step took — is the live
       strip's job now (see `liveEvent`), which says the phase and the clock for every bot working at
       once rather than one line per card. Its own chat still keeps the steps themselves. */
    if (ev.name) addCard("sys", "", "▸ " + hueSpan(ev.name, "", hueOf(ev.name, sid)) + " started"
      + (ev.task ? ": " + esc(cleanBot(ev.task).slice(0, 160)) : "")
      + (isChan ? " — its steps are in " + esc(ev.name) + "'s chat" : ""), to, "text"); }
  else if (ev.type === "agent" && ev.state === "done") { setState(row(ev.id), "finished"); sideSet(row(ev.id), "finished"); }
  else if (ev.type === "tool") addTool(ev.agent, ev.name, ev.args || {}, ev.out, to, ev.id);
  else if (ev.type === "shot") addShot(ev.png, ev.note, undefined, to);
  else if (ev.type === "image") addShot(ev.png, ev.note, "Image", to);
  else if (ev.type === "agent_text" && ev.text) streamText(ev, who, to, T, sid);
  else if (ev.type === "approval") {
    T.asking = true; addApproval(ev.cmd, ev.agent, to);
    /* The card is on screen, so the header must say what the dock says. A card waiting in a chat you
       are not looking at has not asked you anything yet — that chat is named in the header instead. */
    if (here()) { if (!to || to.shown()) setState(sid, "approval"); }
    else refreshHead();
  }
  /* A steer you sent mid-turn, handed to the bot at its next step. It is drawn where a message
     you type is drawn, because that is what it is — the turn just picks it up sooner. This event is
     the only thing that draws it, on every client alike: the click only marks the row as taken,
     so a steer the turn could not take is never shown as one it did. */
  else if (ev.type === "steer") {
    /* `late` is the turn saying it ended before it could hand this over. It is not a message the bot
       saw, so it is not drawn as one: the row goes back to being an ordinary queued task, and the
       turn's own `drainQueue` runs it next — which is what steering with no turn to interrupt means.
       Drawing it here would put the instruction on screen under a bot that has already stopped. */
    if (ev.late) { const it = (S.queue[sid] || []).find(x => x.text === ev.text && x.steering);
                   if (it) it.steering = false; if (sid === S.active) renderQueue(); }
    else { steerLanded(sid, ev.text); addMsg("user", ev.text, null, to, { quote: ev.quote }); }
  }
  else if (ev.type === "learned") addCard("sys", "", "learned from " + NAME(ev.agent) + ": " + (ev.notes || []).join(" · "), to);
  else if (ev.type === "context") addCard("sys", "", "compressed " + ev.dropped + " earlier step" +
    (ev.dropped === 1 ? "" : "s") + " to fit the model's context window (" + ev.limit + " tokens)", to);
  else if (ev.type === "workdir") addCard("sys", "", "working in " + ev.path + (ev.channel ? " (" + ev.channel + ")" : ""), to);
  else if (ev.type === "ctx") { if (here()) renderCtx(ev.ctx); }
  else if (ev.type === "final") {
    /* The answer usually streams first (agent_text) and then arrives again as the turn's `final`
       report. When both carry the same words, the report is promoted onto the bubble already on
       screen rather than drawn a second time below it. */
    const text = cleanBot(ev.text);
    /* Only a streamed answer bubble carries `data-raw` (see `streamText`), so this picks that bubble
       and not a tool row or the step card, which also carry the `bot` class. */
    const last = [...(to.nodes || [])].reverse().find(n => n.dataset && n.dataset.raw !== undefined);
    const same = text && last && cleanBot(last.dataset.raw).trim() === text.trim();
    /* "Room · summary" is a label, not a name, so it takes no hue; a bot's own report is headed with
       its name and does. */
    const named = !isChan;
    const label = isChan ? "Room · summary" : hueSpan(NAME(sid), "", hueOf(NAME(sid), sid)) + " · report";
    if (same) {
      last.classList.add("final");
      const w = last.querySelector(".who");
      /* Rewrite the label in place, keeping the timestamp span `streamText` put there — replacing the
         whole node dropped it. */
      if (w) {
        const mts = w.querySelector(".mts");
        w.innerHTML = label;
        if (mts) w.appendChild(mts);
      }
    } else addCard("final", label, text, to, named ? "label" : undefined);
  }
  /* The server's own failure — a model call or a tool that threw inside the turn. Without this
     branch the turn just stops with no report and no reason, which reads as a silent hang. */
  else if (ev.type === "error") { T.failed = true; chime("error"); announce("The bot hit an error and stopped.");
    addCard("sys", "", "The bot hit an error and stopped: " + (ev.msg || "no reason given"), to); }
  /* This app stopping the bot — a refused command, a denied card, a tool that threw. It goes in the
     transcript and not only in the step row, because the row is folded and a bot that was refused
     and then went quiet used to leave the room with nothing to read: the refusal *is* the account of
     what happened. Drawn as the same centred note the other app-level lines use. */
  else if (ev.type === "notice" && ev.text) {
    if (ev.level === "error") chime("error");
    announce(ev.text);
    addCard("sys", "", ev.text, to);
  }
}
async function runChat(path, payload) {
  const sid = payload.session;
  const here = () => sid === S.active;
  /* This turn's own id, sent with it and carried back on every event the server mirrors to watchers.
     The server streams a turn to *every* watcher, this window included; the id is how this window
     recognises its own events and ignores them, so its cards are drawn once — by the stream it is
     reading — and never a second time from the watch. Kept after the turn ends, because the tail of
     its events (the report, then `done`) can arrive on the watch a beat later. */
  const turn = payload.turn = "t" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
  (S.myTurns = S.myTurns || {})[sid] = turn;
  S.turns[sid] = { nodes: [], plan: null, running: true };
  const T = S.turns[sid], own = turnSink(sid);
  const mode = S.approval;                       // the approval mode this turn started under
  renderQueue();                                 // the running chat's queued tasks are drawn, not run
  syncComposer();                                // Stop appears for this chat, and only for this chat
  try {
    await stream(path, payload, ev => drawTurnEvent(sid, T, ev), T);
    await refreshPending();
    for (const d of T.nodes.slice())
      if (d.classList && d.classList.contains("bot") && !d.textContent.trim()) { d.remove(); T.nodes.splice(T.nodes.indexOf(d), 1); }
    if (here() && !S.pending[sid]) setDock("idle");
  } catch (e) {
    /* A turn you stopped is not a turn that broke: the stream ending because you walked away is the
       outcome you asked for, so it is said plainly and is not chimed as a failure. */
    if (T.stopped) {
      if (!here()) addCard("sys", "", "Stopped. The bot may have been part-way through a step.", own);
      if (here()) setDock("idle");
    } else {
    /* The turn failed (server down, dropped stream, bad response). Say so in words the user can act
       on and hand the composer back — a stuck Send button would lock the user out until a reload. A
       failure the app recognises is already phrased for a person; anything else is a bug, so its own
       message is kept for whoever has to read it. */
    T.failed = true;
    /* A failure the app recognises is already phrased for a person; anything else is a bug, so the
       user gets a plain sentence and the raw message goes to the console for whoever has to read it. */
    if (!(e && e.human)) console.error("turn failed:", e);
    addCard("sys", "", e && e.human ? e.message
      : "The turn failed. Check that the server is still running, then try again.", own);
    /* A failed turn ends in `idle`, which has no cue of its own, so the failure is announced here
       rather than left silent — "nothing happened" and "it broke" must not sound the same. */
    chime("error"); announce("The turn failed.");
    if (here()) setDock("idle");
    }
  } finally {
    T.running = false;
    /* The turn is over, however it ended — done, stopped, failed — so the strip goes with it, on the
       same beat as the header. The transcript's record is what is left. */
    workingClear();
    stepDone(T, T.failed);
    syncComposer();
    if (!here()) refreshHead();        // the chat on screen no longer needs to name a finished turn
    /* A plan-only turn is not finished until the user says go, so the way to say go is offered only
       now that the turn has actually stopped — a button clicked mid-stream would be a silent no-op. */
    const waiting = !!T.plan && mode === "plan";
    if (waiting) addPlanApprove(T.plan, sid);
    /* Once a turn is done the transcript is the record, so its streamed cards are dropped and a later
       switch back shows the saved history instead of them. Two things the history does not carry are
       kept by their chat, so a turn that ended while you were elsewhere is not a silent blank: a
       failure notice, and a plan still waiting for your go. The final report goes with them — the
       history has it, and keeping the card would show the same report twice. */
    if (!T.failed && !waiting) delete S.turns[sid];
    else if (!here()) for (const n of T.nodes.slice())
      if (n.classList && n.classList.contains("final")) { n.remove(); T.nodes.splice(T.nodes.indexOf(n), 1); }
    if (here()) renderQueue();
    /* The turn's cards were the live view; now that it has stopped they are drawn again from the
       saved transcript, which is also what gives each message its place in the history — the thing
       Edit and Retry act on. A failed turn is not redrawn: its streamed cards carry the error, and
       that is exactly what the transcript does not have. A plan still waiting on your go is not in
       the transcript yet either, so its card stays as it is. */
    if (here() && !waiting && !T.failed) {
      await reloadTranscript();
      if (T.stopped) addCard("sys", "", "Stopped. The bot may have been part-way through a step.");
    }
    loadChats();                       // the sidebar's order and last line follow the new turn
    /* A member's chat drew this turn's work as live cards; its history has it now, so hand it back
       to the record — otherwise the same commands would be drawn twice the next time it is opened. */
    for (const s of (T.subs || [])) {
      if (!S.turns[s]) continue;
      delete S.turns[s];
      if (s === S.active) select(s);
      drainQueue(s);                   // and a task typed into that member's chat goes too
    }
    /* Whatever was typed into *this* chat while its turn ran goes now — unless a plan is still
       waiting on your go, where a second turn would just talk over the decision you have not made.
       Another chat's queue is untouched: it is waiting on its own turn, not on this one. */
    if (!waiting) drainQueue(sid);
  }
}
/* Redraw the transcript from the server. Where the panel lands is the reader's call and `render`
   decides it — a turn ending or a poll is not a reason to drag someone out of the part they were
   reading. */
async function reloadTranscript() {
  /* The record is being redrawn, so the live view is over: whatever the strip was showing is in the
     transcript now, or never happened. */
  workingClear();
  /* A failed read leaves the transcript already on screen, which is a better answer than an empty
     one — so the redraw is skipped rather than blanking the panel. */
  const h = await get("/api/history?session=" + encodeURIComponent(S.active));
  if (h) { S.messages = h.messages || []; render(S.messages, h.pending); }
}
/* Stop is offered for the chat you are looking at and only while *its* turn is running — a turn in
   another chat is not yours to stop from here. Send stays live: typing into a chat whose own turn is
   running queues the message rather than talking over the turn, and typing into any other chat just
   goes. */
function syncComposer() {
  const stop = $("#btnStop"); if (!stop) return;
  stop.hidden = !busy(S.active);
}
async function stopTurn() {
  const sid = S.active; if (!busy(sid)) return;
  const T = S.turns[sid]; if (!T) return;
  T.stopped = true;
  workingClear();      // you asked for the work to stop, so the live rows stop with it (see drawTurnEvent)
  const stop = $("#btnStop"); stop.disabled = true; stop.textContent = "Stopping…";
  // Ask the *server* to land the turn. Cancelling the stream alone only closes the socket — the
  // turn's thread keeps running and its events pile up in a queue nobody reads — so the turn would
  // go on working invisibly. The stream is left open on purpose, so the bot's closing report lands.
  try { await post("/api/stop", { session: sid }); } catch (e) {}
  setTimeout(() => { stop.disabled = false; stop.textContent = "Stop"; }, 800);
}
/* ---------- thinking / steps (see the CSS for what this looks like) ---------- */
const STEP_LABEL = { thinking:"Thinking…", working:"Working…", searching:"Searching…",
  approval:"Waiting for your approval…", question:"Asking you something…" };
/* The same step, said again once it has been going a while. A turn can sit for minutes on one slow
   model call or one long command, and a label that never changes is indistinguishable from a bot
   that has hung — so the card admits the wait rather than leaving you to guess. */
const STEP_LONG = { thinking:"Still thinking…", working:"Still working…", searching:"Still searching…",
  approval:"Still waiting for your approval…", question:"Still waiting for your answer…" };
/* Every running thing carries a clock — the step card, and each tool row while its command runs —
   so a long task never looks like a stopped one. The start time lives on the element, so switching
   chats or redrawing does not restart it, and one interval drives them all. */
const LONG_STEP_MS = 45000;
function clockText(ms) {
  const s = Math.floor(ms / 1000);
  if (s < 60) return s + "s";
  return Math.floor(s / 60) + "m " + String(s % 60).padStart(2, "0") + "s";
}
let clockTimer = null;
function clockStart(node) {
  if (node) node.dataset.since = String(Date.now());
  // The ticker only exists while something is running: a permanently-live 1 Hz whole-document scan is
  // pure idle cost, and it stops itself the moment the last clock goes.
  if (!clockTimer) clockTimer = setInterval(clockTick, 1000);
}
function clockStop(node) { if (node) { delete node.dataset.since; node.textContent = ""; } }
function clockTick() {
  const nodes = $$(".telapsed[data-since]");
  if (!nodes.length) { clearInterval(clockTimer); clockTimer = null; return; }   // nothing left to tick
  const now = Date.now();
  for (const n of nodes) {
    const ms = now - Number(n.dataset.since), long = ms >= LONG_STEP_MS;
    n.textContent = clockText(ms);
    n.classList.toggle("long", long);
    const lab = n.parentElement && n.parentElement.querySelector(".tlabel");
    if (lab && lab.dataset.base) lab.textContent = long ? (lab.dataset.long || lab.dataset.base) : lab.dataset.base;
  }
}
function stepSet(to, T, state) {
  if (!STEP_LABEL[state]) return;                       // idle and the rest are not steps
  if (!T.step) {
    const d = el("div", "m bot think");
    d.innerHTML = `<div class="trow"><span class="tstate"><span class="spin"></span></span>
      <span class="tlabel"></span><span class="telapsed"></span><span class="tcaret">${svg("caret")}</span></div><div class="tbody"></div>`;
    /* The steps log folds open on a click; it must open for a keyboard user too, and say whether it
       is open — the caret is the only other clue, and it is drawn by CSS. */
    d.tabIndex = 0; d.setAttribute("role", "button"); d.setAttribute("aria-expanded", "false");
    d.onclick = () => { const o = d.classList.toggle("open"); d.setAttribute("aria-expanded", o ? "true" : "false"); };
    d.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); d.onclick(); } };
    T.step = d; T.steps = [];
    to.add(d);
  }
  // The same phase, said again (the server re-announces "thinking" every step): keep the clock
  // running and do not count it as another step, so the card reads the phase, not the round-trip.
  if (T.steps[T.steps.length - 1] === state) { to.scroll(); return; }
  T.steps.push(state);
  const lab = T.step.querySelector(".tlabel");
  /* The step number rides on the label so a long turn shows its progress while it runs, not only in
     the "Done — N steps" line at the end. */
  const n = T.steps.length, pre = "Step " + n + " · ";
  lab.dataset.base = pre + STEP_LABEL[state];
  lab.dataset.long = pre + (STEP_LONG[state] || STEP_LABEL[state]);
  lab.textContent = lab.dataset.base;
  clockStart(T.step.querySelector(".telapsed"));        // a new step starts its own clock
  T.step.querySelector(".tbody").textContent =
    T.steps.map((s, i) => (i + 1) + ". " + STEP_LABEL[s]).join("\n");
  to.scroll();
}
function stepDone(T, failed) {
  const d = T.step; if (!d) return;
  clockStop(d.querySelector(".telapsed"));
  const sp = d.querySelector(".spin"); if (sp) sp.remove();
  d.querySelector(".tstate").innerHTML = failed ? svg("warn") : svg("check");
  d.querySelector(".tlabel").textContent = failed ? "Stopped early"
    : "Done — " + (T.steps || []).length + " step" + ((T.steps || []).length === 1 ? "" : "s");
}
function setState(sid, st) {
  if (sid === S.active) { setDock(st);
    setHead(hSub(H_STATE[st] || st), st === "approval");
    $("#hDot").classList.toggle("live", st !== "idle"); }
  /* Escaped, not interpolated raw: a session id is server-made today, but this is a selector, and a
     quote or a bracket in one would either throw or match the wrong row. */
  const li = document.querySelector(`.bot[data-id="${CSS.escape(sid)}"] .dot`);
  if (li) li.style.background = st === "idle" ? "var(--dot)" : "var(--accent)";
}
async function refreshPending() {
  const d = await get("/api/state");
  if (d) S.pending = d;   // a missed poll keeps the last good state rather than blanking the badge
}

/* ---------------- context menu ---------------- */
/* `sess` is the chat a menu item acts on, which is not always the thing the row is: a nested row
   deletes the bot (`id`) but clears *this* conversation (`company/producer`), so the two are kept
   apart. Clearing a channel row acts on the room, where the two are the same. `dir` says a files row
   is a folder: the menu is the same one, but "Open with" has nothing to open and "Open" is the
   descent a plain click already does. */
function openCtx(e, id, kind, sess, dir) {
  e.stopPropagation();
  S.ctxSess = sess || id;
  S.ctxFrom = document.activeElement;   // so Escape can hand focus back to the row that opened it
  const b = bot(id), c = chan(id);
  const items = kind === "bot" ? [
    ["pin", (b && b.pinned ? "Unpin" : "Pin"), "pin"],
    ["edit", "Edit profile", "edit"],
    ["duplicate", "Duplicate", "copy"],
    ["hide", (b && b.hidden ? "Unhide" : "Hide"), "hide"],
    ["sep", "", ""],
    ["clear", "Clear chat", "clear"],
    ["sep", "", ""],
    ["delete", "Delete", "trash"],
  ] : kind === "file" ? [
    /* A files row is its own path, so `id` is the entry relative to the repo root — the one thing
       the server's file routes take — and the absolute path an item copies is `S.filesRoot` + it. */
    ["open", "Open", "file"],
    ["with", "Open with", "caret"],
    ["finder", "Open in Finder", "monitor"],
    ["sep", "", ""],
    ["abs", "Copy absolute path", "copy"],
    ["rel", "Copy relative path", "copy"],
    ["sep", "", ""],
    ["add", "Add to chat", "plus"],
  ] : [
    ["pin", (c && c.pinned ? "Unpin" : "Pin"), "pin"],
    ["edit", "Edit room", "edit"],
    ["sep", "", ""],
    ["clear", "Clear chat", "clear"],
    ["sep", "", ""],
    ["delete", "Delete", "trash"],
  ];
  const menu = $("#ctx"); menu.innerHTML = "";
  for (const [act, label, ico] of items) {
    if (act === "sep") { menu.appendChild(el("div", "sep")); continue; }
    /* "Open with" is the one item that does not act on click: it opens the list of apps beside
       itself. With no app registered it is left out entirely, because a submenu with nothing under
       it is a dead end the user only finds by trying it. */
    if (act === "with") {
      const apps = S.filesApps || [];
      if (!apps.length || dir) continue;
      const it = el("div", "it", `<span class="ico">${svg(ico)}</span><span>${label}</span><span class="fly">${svg("caret")}</span>`);
      it.setAttribute("aria-haspopup", "menu"); it.setAttribute("aria-expanded", "false");
      const fly = el("div", "flyout"); fly.setAttribute("role", "menu"); fly.setAttribute("aria-label", "Open with");
      for (const a of apps) {
        const fi = el("div", "it", `<span>${esc(a.name)}</span>`);
        fi.onclick = () => { closeCtx(); fileOpen(id, a.how);
          if (S.ctxFrom && S.ctxFrom.focus) S.ctxFrom.focus(); };
        kbd(fi, fi.onclick); fi.setAttribute("role", "menuitem");
        fly.appendChild(fi);
      }
      /* The arrows inside the submenu are stopped here rather than left to the parent's walk: the
         parent would otherwise read them as "next item" and step out of the list that is open. */
      fly.onkeydown = ev => {
        if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
          ev.stopPropagation();
          const its = [...fly.querySelectorAll(".it")];
          const i = its.indexOf(document.activeElement);
          const n = ev.key === "ArrowDown" ? (i + 1) % its.length : (i - 1 + its.length) % its.length;
          ev.preventDefault(); its[n].focus(); return;
        }
        if (ev.key === "ArrowLeft" || ev.key === "Escape") { ev.stopPropagation(); hideFly(fly); it.focus(); }
      };
      it.appendChild(fly);
      /* The click is stopped from reaching the document, where the one outside-click handler would
         otherwise read it as "somewhere else" and close the menu the submenu belongs to. */
      it.onclick = ev => { ev.stopPropagation(); if (fly.classList.contains("on")) hideFly(fly); else showFly(fly); };
      kbd(it, it.onclick);
      it.setAttribute("role", "menuitem");
      menu.appendChild(it);
      continue;
    }
    const it = el("div", "it" + (act === "delete" ? " danger" : ""), `<span class="ico">${svg(ico)}</span><span>${label}</span>`);
    it.onclick = () => { closeCtx(); ctxAction(act, id, kind, dir);
      // Hand the caret back to the row that opened the menu: the item that was focused is hidden with
      // the menu, and focus on a hidden element falls to <body>, losing the keyboard user's place.
      if (S.ctxFrom && S.ctxFrom.focus) S.ctxFrom.focus(); };
    kbd(it, it.onclick);
    it.setAttribute("role", "menuitem");   // kbd defaults to "button"; inside a menu it is an item
    menu.appendChild(it);
  }
  menu.classList.add("on");
  const r = menu.getBoundingClientRect();
  /* A pointer gave us the click point; a keyboard activation of the ⋯ kebab gave us nothing (clientX
     and clientY are 0), so fall back to the row that opened the menu and drop it just under that. */
  let x, y;
  if (e && (e.clientX || e.clientY)) { x = e.clientX; y = e.clientY; }
  else { const b = (S.ctxFrom && S.ctxFrom.getBoundingClientRect) ? S.ctxFrom.getBoundingClientRect()
                                                                  : { left: 12, bottom: 12 };
         x = b.left; y = b.bottom + 4; }
  if (x + r.width > innerWidth - 8) x = innerWidth - r.width - 8;
  if (y + r.height > innerHeight - 8) y = innerHeight - r.height - 8;
  menu.style.left = Math.max(8, x) + "px"; menu.style.top = Math.max(8, y) + "px";
  /* A menu opened by keyboard should put the caret inside it, and the arrows should walk the items. */
  menu.onkeydown = ev => {
    /* Right is "into" and left is what walks back out, but only the item that actually owns a
       submenu answers here — the plain menus have no flyout, so this is inert for them. */
    if (ev.key === "ArrowRight") {
      const f = document.activeElement && document.activeElement.querySelector
              ? document.activeElement.querySelector(".flyout") : null;
      if (f) { ev.preventDefault(); showFly(f); }
      return;
    }
    if (ev.key !== "ArrowDown" && ev.key !== "ArrowUp") return;
    /* Direct children only: a submenu's own items carry `.it` too, and a walk that silently stepped
       into one would move the caret into a flyout the user has not opened. */
    const its = [...menu.querySelectorAll(":scope > .it")]; if (!its.length) return;
    const open = menu.querySelector(".flyout.on"); if (open) hideFly(open);
    const i = its.indexOf(document.activeElement);
    const n = ev.key === "ArrowDown" ? (i + 1) % its.length : (i - 1 + its.length) % its.length;
    ev.preventDefault(); its[n].focus();
  };
  const first = menu.querySelector(".it"); if (first) first.focus();
}
/* The submenu hangs off its item and is only shown, never rebuilt. It picks its own side: the menu
   is placed at the click point, which for a row in the files panel is the right edge of the window,
   and a flyout that always opened rightward would hang off the screen there. */
function showFly(f) {
  const it = f.parentElement;
  f.classList.add("on");
  f.classList.toggle("left", it.getBoundingClientRect().right + f.offsetWidth > innerWidth - 8);
  it.setAttribute("aria-expanded", "true");
  const first = f.querySelector(".it"); if (first) first.focus();
}
function hideFly(f) {
  f.classList.remove("on");
  f.parentElement.setAttribute("aria-expanded", "false");
}
function closeCtx() { $("#ctx").classList.remove("on"); }
async function ctxAction(act, id, kind, dir) {
  /* The files menu acts on a path, not on a chat: `id` is the entry relative to the repo root, which
     is exactly what the file routes take. A folder's "Open" is the descent a click on the row already
     does — there is no application to hand a folder to, and Finder is its own item below. */
  if (kind === "file") {
    const rel = id, abs = S.filesRoot ? S.filesRoot + "/" + rel : rel;
    if (act === "open") return dir ? descend(rel) : fileOpen(rel, "open");
    if (act === "finder") return fileOpen(rel, "finder");
    if (act === "rel") return copyPath(rel, "relative path");
    if (act === "abs") return copyPath(abs, "absolute path");
    if (act === "add") return addToChat(rel);
    return;
  }
  if (act === "delete") {
    const gone = kind === "bot" ? "Its chats go with it, in every room."
                                : "The room's transcript and its bots' chats inside it go with it.";
    if (!confirm("Delete " + NAME(id) + "?\n\n" + gone)) return;
    const r = await jpost(kind === "bot" ? "/api/bot/delete" : "/api/channel/delete", { id });
    if (r.ok === false) { alert(r.error || "Could not delete that."); return; }
    await reloadConfig();
    // the active chat may have been inside what we just deleted — a scoped row points at both
    const orphan = kind === "bot" ? S.active === id || (botOf(S.active) || {}).id === id
                                  : S.active === id || scopeOf(S.active) === id;
    if (orphan) select(firstChatId());
    return;
  }
  if (act === "duplicate") {
    const r = await jpost("/api/bot/duplicate", { id });
    if (r.ok === false) { alert(r.error || "Could not duplicate that."); return; }
    await reloadConfig(); return;
  }
  if (act === "clear") {
    const sess = S.ctxSess || id;
    if (!confirm("Start a new chat in " + NAME(sess) + "?\n\nThe transcript is emptied. The bots keep "
               + "their memory and their work logs, so they still know what this project is about.")) return;
    const r = await jpost("/api/clear", { session: sess });
    if (r.ok === false) { alert(r.error || "Could not clear this chat."); return; }
    await refreshPending();                       // a card that was waiting is gone with the transcript
    if (S.active === sess) select(sess);          // re-render the chat, now empty
    return;
  }
  if (act === "pin" || act === "hide") {
    /* A room pins to the top of the sidebar; it has no `hidden` — taking a room out of the sidebar
       would hide its bots' chats with it, and Delete is the honest way to do that. */
    if (kind === "channel") {
      const c = chan(id); if (!c || act === "hide") return;
      const r = await jpost("/api/channel", { channel: { id, pinned: !c.pinned } });
      if (r.ok === false) { alert(r.error || "Could not change that."); return; }
      await reloadConfig(); return;
    }
    const b = bot(id); if (!b) return; const key = act === "pin" ? "pinned" : "hidden";
    const r = await jpost("/api/bot", { bot: { id, [key]: !b[key] } });
    if (r.ok === false) { alert(r.error || "Could not change that."); return; }
    await reloadConfig(); return; }
  if (act === "edit") { openSettings(kind === "bot" ? "bots" : "channels", id); return; }
}
async function reloadConfig() {
  const cfg = await get("/api/config");
  /* A failed reload leaves the last good config in place. Every caller is a "now redraw with the
     server's truth" after a write, and throwing a TypeError into ~20 of them was the wrong answer to
     a blip. */
  if (!cfg) return;
  S.bots = cfg.bots; S.channels = cfg.channels; S.models = cfg.models; S.settings = cfg.settings || {}; S.routines = cfg.routines || [];
  S.tools = cfg.tools || S.tools; S.connectorTools = cfg.connector_tools || []; S.fontSizes = cfg.font_sizes || S.fontSizes;
  S.teamTemplate = cfg.team_template || S.teamTemplate;
  applyAppearance(S.settings.appearance); renderNav(); loadChats();
}

/* ---------------- side panels ---------------- */
/* Both right-hand panels hang under the toolbar, whose height is not a constant: it grows with the
   font scale and changes at the mobile breakpoint. Measured rather than assumed — once per open, and
   again on a resize — so the panel and the bar can never drift apart. */
function panelTop() {
  const bar = document.querySelector(".topbar"); if (!bar) return;
  document.documentElement.style.setProperty("--panel-top", Math.round(bar.getBoundingClientRect().height) + "px");
}

/* ---------------- computer panel ---------------- */
let compTimer = null;
async function openComp() {
  if ($("#files").classList.contains("on")) closeFiles(false);   // one right-hand panel at a time
  const c = $("#comp"); c.classList.add("on"); c.inert = false; document.body.classList.add("overlay");
  panelTop();
  // With no screenshot to show, the frame holds the bot itself rather than a black rectangle: a
  // live face, the same one the dock wears for whoever you are talking to. Built on open and
  // retired on close, like the settings preview, so a hidden panel costs no animation frames.
  if (!S.compFace) S.compFace = attach($("#compFace"), "idle", { size: 210, species: "mochi", ...sideFace("blue") });
  compDress();
  await refreshComp();
  clearInterval(compTimer); compTimer = setInterval(refreshComp, 2500);
}
/* `restoreFocus` is off for a click outside: the user has just pointed somewhere else on purpose, and
   pulling the caret back to the toolbar button would undo what they just did. Every other close — the
   ×, Escape — is a dismissal with nowhere else to land, so the caret goes back to the opener. */
function closeComp(restoreFocus = true) {
  const c = $("#comp"); const wasOpen = c.classList.contains("on");
  c.classList.remove("on"); c.inert = true; document.body.classList.remove("overlay"); clearInterval(compTimer);
  if (S.compFace) { detach(S.compFace); S.compFace = null; }
  if (restoreFocus && wasOpen && $("#btnComp").focus) $("#btnComp").focus();
}
/* The placeholder face follows the active chat, so opening the panel mid-turn shows that bot. */
function compDress() {
  if (!S.compFace) return;
  const b = S.activeIsChannel ? null : botOf(S.active);
  S.compFace.skin(b ? faceOf(b) : "mochi", b ? bigFace(b.color) : null, b ? lookOf(b) : null);
}
async function refreshComp(force) {
  // The panel polls this every 2.5s; a transient error must not throw an unhandled rejection each
  // time and freeze the frame on stale content — say it is offline and try again on the next tick.
  // The chat is named so the server can scope the answer to it: one browser serves every chat, and
  // without this the panel showed whichever chat's bot happened to be driving it.
  let d;
  try { d = await get("/api/computer/preview?sid=" + encodeURIComponent(S.active || "") + (force ? "&force=1" : "")); }
  catch (e) { $("#compFrame").classList.remove("live"); $("#compShot").removeAttribute("src");
              $("#compMeta").textContent = "the computer panel is offline — retrying…"; return; }
  if (!d) { $("#compFrame").classList.remove("live"); $("#compShot").removeAttribute("src");
             $("#compMeta").textContent = "the computer panel is offline — retrying…"; return; }
  const img = $("#compShot"), live = !!d.png;
  $("#compFrame").classList.toggle("live", live);
  if (live) {
    img.src = d.png;
    // `err` alongside a picture is not a failure: it is the note saying this is the profile that is
    // on screen, not the bot's own. Shown, so nobody mistakes one profile for the other.
    $("#compMeta").textContent = (d.title || "(untitled)") + "  ·  " + (d.url || "") + (d.err ? "  —  " + d.err : "");
  } else {
    // No `src` at all, rather than an empty one: an empty src is what made the browser draw a
    // broken-image glyph beside the alt text. The frame is showing the face instead.
    img.removeAttribute("src");
    // The server's own reason is already a sentence — "Alpha is using the computer — not this chat's
    // bot" — so it stands alone; "no screen yet" in front of it only said the same thing twice.
    $("#compMeta").textContent = d.err || "no screen yet — open a page below";
  }
}

/* ---------------- files panel ---------------- */
/* The listing belongs to the chat you are in: a directory browsed in one repo is not a directory in
   another, so the first look at a new chat starts again at its root rather than asking for a path the
   server would refuse with an error about a folder the user never typed. */
function filesForChat() {
  if (S.filesFor === S.active) return;
  S.filesFor = S.active; S.filesPath = "";
}
async function openFiles() {
  if ($("#comp").classList.contains("on")) closeComp(false);   // one right-hand panel at a time
  const f = $("#files");
  filesForChat();
  f.classList.add("on"); f.inert = false; document.body.classList.add("overlay");
  panelTop();
  filesSay("");   // a receipt from a moment ago is not this look's: the panel opens with nothing said
  await refreshFiles();
}
/* `restoreFocus` is off for a click outside, for the same reason as the computer panel's: the user
   has just pointed somewhere else on purpose, and pulling the caret back would undo it. */
function closeFiles(restoreFocus = true) {
  const f = $("#files"); const wasOpen = f.classList.contains("on");
  f.classList.remove("on"); f.inert = true; document.body.classList.remove("overlay");
  if (restoreFocus && wasOpen && $("#btnFiles").focus) $("#btnFiles").focus();
}
/* The directory is re-read from the server rather than remembered in the tab, so a panel reopened
   after a bot wrote a file shows the file. `get` answers null for every failure, so one test covers
   a server that is down and a server that refused; the refusal's own sentence is written for a
   person and is shown as it came. */
async function refreshFiles() {
  const sid = encodeURIComponent(S.active || "");
  const d = await get("/api/files?session=" + sid + "&path=" + encodeURIComponent(S.filesPath || ""));
  const apps = await get("/api/file/apps?session=" + sid);
  if (apps && apps.ok) S.filesApps = apps.apps || [];   // a failed ask keeps the last good list
  if (!d) { renderFilesNote("could not reach the server — press Refresh to try again"); return; }
  if (d.ok === false) { renderFilesNote(d.error || "That folder could not be listed.", true); return; }
  renderFiles(d);
}
/* A failure goes where the answer would have been: it is the answer to the question the panel asked,
   and a banner elsewhere would leave the list looking like an empty folder. */
function renderFilesNote(txt, bad) {
  const box = $("#filesList"); box.innerHTML = "";
  $("#filesRoot").textContent = S.filesRoot || "";
  box.appendChild(el("div", "fnote" + (bad ? " bad" : ""), esc(txt)));
}
/* A folder is the way down and a file is a thing to act on, so the row carries which it is and the
   two click paths never guess from the name. The path is rebuilt from the server's own echo of the
   directory rather than from what was asked for, so the two can never drift apart. */
function renderFiles(d) {
  S.filesRoot = d.root || ""; S.filesPath = d.path || "";
  $("#filesRoot").textContent = S.filesRoot + (S.filesPath ? "/" + S.filesPath : "");
  const box = $("#filesList"); box.innerHTML = "";
  if (S.filesPath) {
    const up = el("div", "frow dir");
    up.dataset.path = S.filesPath.includes("/") ? S.filesPath.slice(0, S.filesPath.lastIndexOf("/")) : "";
    up.dataset.up = "1";   // the way back up, not an entry: it is left out of the right-click menu
    up.innerHTML = `<span class="fico">${svg("folder")}</span><span class="fname">..</span>`;
    up.onclick = () => descend(up.dataset.path);
    kbd(up, up.onclick);
    box.appendChild(up);
  }
  for (const en of (d.entries || [])) {
    const dir = !!en.dir;
    const row = el("div", "frow" + (dir ? " dir" : ""));
    row.dataset.path = S.filesPath ? S.filesPath + "/" + en.name : en.name;
    row.innerHTML = `<span class="fico">${svg(dir ? "folder" : "file")}</span><span class="fname">${esc(en.name)}</span>`
      + (dir ? "" : `<span class="fsize">${esc(fileSize(en.size))}</span>`);
    row.onclick = () => dir ? descend(row.dataset.path) : fileOpen(row.dataset.path, "open");
    kbd(row, row.onclick);
    box.appendChild(row);
  }
  // Entries past the server's cap: said, so a directory that looks complete and is not never is.
  if (d.more > 0) box.appendChild(el("div", "fnote", esc("… and " + d.more + " more")));
}
function descend(p) { S.filesPath = p || ""; refreshFiles(); }
/* Bytes in the unit a person would say out loud. A folder shows no size: the server does not walk one
   to count it, so the column is left to the files rather than filled with a number that means nothing. */
const fileSize = n => n == null ? "" : n < 1024 ? n + " B"
  : n < 1048576 ? (n / 1024).toFixed(1) + " KB" : (n / 1048576).toFixed(1) + " MB";
/* A confirmation is said inside the panel, not on the dock tip: `body.overlay` hides the tip and the
   panel is drawn over where it would have been anyway, so a "Copied path" that landed there would be
   a receipt the user never sees. Held and then cleared, because the panel has no button to say it on. */
let filesSayTimer = null;
function filesSay(txt, bad, holdMs = 1800) {
  const n = $("#filesSay"); if (!n) return;
  clearTimeout(filesSayTimer);
  n.textContent = txt; n.classList.toggle("bad", !!bad);
  filesSayTimer = setTimeout(() => { n.textContent = ""; n.classList.remove("bad"); }, holdMs);
}
/* Every way of opening an entry goes through the one route, so "open", "finder" and "with:<app>"
   differ only in the `how` they send. The server's own sentence is shown when it refuses: it knows
   which app is missing, and "Could not open that" would not. A refusal is held longer than a
   confirmation, because it is a sentence to read and not a two-word receipt. */
async function fileOpen(rel, how) {
  const r = await jpost("/api/file/open", { session: S.active, path: rel, how });
  if (r.ok === false) { filesSay(r.error || "Could not open that.", true, 3200); return; }
  filesSay(how === "finder" ? "Opened in Finder" : "Opened " + rel, false, 1400);
}
/* The panel has no button to say "copied" on, so the note says it — and says the path too when the
   write did not land, since a path the user cannot copy is the one thing they cannot get any other
   way. The fallback for a `file://` origin is the one `copyText` already carries. */
async function copyPath(p, label) {
  const ok = await copyText(p, null);
  filesSay(ok ? "Copied " + label : "Could not copy — " + p, !ok, ok ? 1200 : 3200);
}
/* What tells the bot which file to read: the path in the composer, which its `read_file` tool
   resolves against the same repo root this panel is listing. The caret is placed on the next tick
   rather than now, because the menu hands focus back to the row that opened it the moment this
   returns — and here the caret belongs in the composer, where the task naming the file is typed. */
function addToChat(rel) {
  const ta = $("#input"); const cur = ta.value.trimEnd();
  ta.value = cur ? cur + " " + rel : rel;
  autoGrow(ta);
  setTimeout(() => ta.focus(), 0);
}

/* ---------------- link panel ---------------- */
/* A link opened beside the chat rather than thrown at the system browser, so you can read the page
   the bot is talking about without leaving the conversation.

   In the desktop app the frame is a real embedded browser — a `<webview>`, the same thing ZCode's own
   browser panel is built on. It has to be: the sites these bots cite (Threads, most social and
   news sites) send X-Frame-Options and render as a blank rectangle in an `<iframe>`, which is
   exactly the difference measured before choosing. A plain browser has no `<webview>`, so there the
   frame is an iframe and the header keeps an "Open in browser" for the sites that refuse to be framed. */
let linkHist = [], linkAt = -1, linkReturn = null;
const canWebview = () => typeof window.anzen !== "undefined" && !!window.customElements.get("webview");
/* Built on the first open and reused after, so switching links does not rebuild the browser — but a
   kind change (iframe in the browser, webview in the app) does, because the element is not swappable. */
function linkFrame() {
  const body = $("#linkBody");
  const want = canWebview() ? "webview" : "iframe";
  let f = body.querySelector(".linkframe");
  if (f && f.tagName.toLowerCase() === want) return f;
  if (f) f.remove();
  f = document.createElement(want);
  f.className = "linkframe";
  /* A webview is a browser of its own: a named partition keeps it off the app's own session, and no
     `allowpopups` keeps a link inside the page from spawning a window over the chat. */
  if (want === "webview") f.setAttribute("partition", "persist:links");
  else f.setAttribute("referrerpolicy", "no-referrer");
  body.appendChild(f);
  return f;
}
/* `from` is the anchor that was clicked, so closing the panel hands the caret back to the line you
   were reading rather than to nowhere. */
function openLink(url, from) {
  if ($("#comp").classList.contains("on")) closeComp(false);
  if ($("#files").classList.contains("on")) closeFiles(false);
  if (from) linkReturn = from;
  linkHist = linkHist.slice(0, linkAt + 1); linkHist.push(url); linkAt = linkHist.length - 1;
  showLink();
  const p = $("#link"); p.classList.add("on"); p.inert = false;
  document.body.classList.add("overlay");
  panelTop();
}
function showLink() {
  const url = linkHist[linkAt] || "";
  const f = linkFrame();
  /* Set as an attribute, not the property: a webview navigates on the attribute change, and the same
     write is what an iframe wants too. */
  if (f.getAttribute("src") !== url) f.setAttribute("src", url);
  $("#linkTitle").textContent = url;
  $("#linkTitle").title = url;
  $("#linkOut").href = url;
  const back = $("#linkBack");
  back.disabled = linkAt <= 0;
  /* Only a browser without `<webview>` can meet a page that refuses to be framed, so only there is
     the note worth saying. */
  const note = $("#linkNote");
  note.hidden = canWebview();
  note.textContent = "If this stays blank the site does not allow being embedded — use Open in browser.";
}
function closeLink(restoreFocus = true) {
  const p = $("#link"); const wasOpen = p.classList.contains("on");
  p.classList.remove("on"); p.inert = true;
  document.body.classList.remove("overlay");
  /* The page is released rather than left loaded behind a hidden panel: it would keep playing video
     and running scripts for a panel nobody can see. The history is kept, so reopening a link is
     instant to re-navigate and the Back button still knows where it was. */
  const f = $("#linkBody").querySelector(".linkframe"); if (f) f.remove();
  if (restoreFocus && wasOpen && linkReturn && linkReturn.focus) linkReturn.focus();
  linkReturn = null;
}

/* ---------------- settings ---------------- */
/* The rail, grouped so fourteen sections stay scannable — a group is a heading you read, not a thing
   you click. The order is the order you meet them: what the app runs on, what is in it, how it
   behaves. This is why there is no "Engines" any more: one tab held the AI endpoint, the browser and
   the phone, and nothing in the word said which of the three a given control belonged to. The AI side
   and the browser are separate sections now, the way ZCode's own settings separate them. */
const TABS = [
  ["general", "General", "settings", "Set up"],
  ["models", "AI model", "models", "Set up"],
  ["browser", "Browser", "monitor", "Set up"],
  ["phone", "Phone", "phone", "Set up"],
  ["bots", "Bots", "bots", "Your workspace"],
  ["channels", "Rooms", "channels", "Your workspace"],
  ["apps", "Connected apps", "apps", "Your workspace"],
  ["skills", "Skills", "skills", "Your workspace"],
  ["plugins", "Plugins", "plugins", "Your workspace"],
  ["memory", "Memory", "memory", "Your workspace"],
  ["approvals", "Approvals", "approvals", "Behaviour"],
  ["voice", "Voice", "voice", "Behaviour"],
  ["appearance", "Appearance", "appearance", "Behaviour"],
  ["help", "Help", "help", ""],
];
let curTab = "general", curEdit = null, settingsReturnFocus = null;
/* The shell behind a dialog, taken out of reach while it is open. The focus trap keeps a Tab inside
   the modal, but a screen reader in browse mode could still walk into the chat underneath, and the
   transcript is not read-only — a stray activation there is a real edit. `inert` removes both at
   once, and the browser lifts focus for us when it goes back on. The dock is named because it is a
   sibling of the shell, not a child of it. */
const BEHIND = ["#side", "#main", "#dock", "#comp", "#files", "#link"];
function behindInert(on) {
  for (const s of BEHIND) { const n = $(s); if (n) n.inert = on; }
  /* Each side panel is an overlay of its own: when the dialog lets go, it goes back to whatever it
     was — inert unless it is actually on screen. Clearing it wholesale would leave a hidden panel's
     controls reachable by keyboard and a screen reader. */
  if (!on) for (const s of ["#comp", "#files", "#link"]) { const n = $(s); n.inert = !n.classList.contains("on"); }
}
function openSettings(tab, id) {
  if ($("#comp").classList.contains("on")) closeComp();
  if ($("#files").classList.contains("on")) closeFiles();   // a dialog owns the screen; the panels yield
  if ($("#link").classList.contains("on")) closeLink();
  curTab = tab || curTab; curEdit = id || null;
  settingsReturnFocus = document.activeElement;
  $("#scrim").classList.add("on"); document.body.classList.add("overlay"); renderTabs(); renderPanel();
  behindInert(true);
  // Land the keyboard inside the dialog instead of on the page behind it.
  const first = $("#setPanel").querySelector("input, select, textarea, button, [tabindex]");
  (first || $("#sClose")).focus();
}
function closeSettings() { $("#scrim").classList.remove("on"); document.body.classList.remove("overlay");
  behindInert(false);
  if (S.facePrev) { detach(S.facePrev); S.facePrev = null; }   // don't keep ticking a hidden preview
  if (settingsReturnFocus && settingsReturnFocus.focus) settingsReturnFocus.focus();
  settingsReturnFocus = null;
}
function renderTabs() {
  const box = $("#setTabs"); box.innerHTML = "";
  /* A real tablist: each tab names the panel it controls and says whether it is the one showing,
     so the rail is navigable and announced as tabs rather than as a row of buttons. A group heading
     is a plain label, not a tab — it is skipped by the keyboard and by the screen reader, which is
     what keeps it from becoming a focusable thing that does nothing. */
  let grp = null;
  for (const [id, label, ico, group] of TABS) {
    if (group && group !== grp) { const g = el("div", "mgrp", esc(group)); g.setAttribute("aria-hidden", "true"); box.appendChild(g); }
    grp = group || grp;
    const t = el("div", "mtab" + (id === curTab ? " on" : ""), `<span class="ico">${svg(ico)}</span><span class="lbl">${label}</span>`);
    /* Focus is put back on the tab after the redraw: activating one rebuilds the rail, and without
       this the keyboard user is dropped onto <body> and has to Tab in from the top again. */
    t.onclick = () => { curTab = id; renderTabs(); renderPanel();
      const n = document.getElementById("tab-" + id); if (n && n.focus) n.focus(); };
    t.id = "tab-" + id;
    t.setAttribute("role", "tab");
    t.setAttribute("aria-selected", id === curTab ? "true" : "false");
    t.setAttribute("aria-controls", "setPanel");
    /* Roving tabindex: exactly one tab is in the tab order — the one showing — so the rail is a single
       Tab stop rather than fourteen, and the arrows move between sections. */
    t.tabIndex = id === curTab ? 0 : -1;
    box.appendChild(t);
  }
  /* The arrows and Home/End move along the rail and take focus with them; Enter or Space opens the
     one they are on. A vertical rail reads with Up/Down, but Left/Right work too, so the habit from a
     horizontal strip is not punished. */
  box.onkeydown = e => {
    const tabs = $$("#setTabs .mtab"), i = tabs.indexOf(document.activeElement);
    const step = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[e.key];
    let to = e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1
      : step ? (i < 0 ? (step > 0 ? 0 : tabs.length - 1) : i + step) : null;
    if (to == null) {
      if ((e.key === "Enter" || e.key === " ") && i >= 0) { e.preventDefault(); tabs[i].onclick(); }
      return;
    }
    e.preventDefault();
    to = (to + tabs.length) % tabs.length;
    tabs.forEach((t, n) => { t.tabIndex = n === to ? 0 : -1; });
    tabs[to].focus();
  };
}
function renderPanel() {
  const p = $("#setPanel"); p.innerHTML = "";
  if (S.facePrev) { detach(S.facePrev); S.facePrev = null; }   // the face preview dies with the panel
  p.setAttribute("aria-labelledby", "tab-" + curTab);
  ({ general: tabGeneral, channels: tabChannels, bots: tabBots, models: tabModels, browser: tabBrowser,
     phone: tabPhone, approvals: tabApprovals, memory: tabMemory, skills: tabSkills, plugins: tabPlugins,
     apps: tabApps, voice: tabVoice, appearance: tabAppearance, help: tabHelp }[curTab] || tabGeneral)(p);
}
function h3(p, title, hint) { p.appendChild(el("h3", "", esc(title))); if (hint) p.appendChild(el("p", "hint", hint)); }
function fld(p, label, node, desc) {
  const f = el("div", "fld"); if (label) f.appendChild(el("label", "", esc(label)));
  f.appendChild(node); if (desc) f.appendChild(el("div", "desc", desc)); p.appendChild(f); return f;
}
function input(p, label, val, on, ph, type) {
  const i = el("input"); i.type = type || "text"; i.value = val == null ? "" : val; if (ph) i.placeholder = ph;
  i.onchange = () => on(i.value); return fld(p, label, i);
}
function selectFld(p, label, val, opts, on, desc) {
  const s = el("select");
  for (const [v, t] of opts) { const o = new Option(t, v); if (v === val) o.selected = true; s.appendChild(o); }
  s.onchange = () => on(s.value); return fld(p, label, s, desc);
}
/* Model picker — a list you open and filter, not a native <datalist>. A datalist only reveals its
   options while you are typing, so after "Detect all models" the field still looked inert; and on a
   router the list is hundreds of ids, which needs a filter and a scroll anyway. The list opens in
   place rather than floating: the settings panel scrolls, and a floating menu would be clipped by it.
   The filter box doubles as the way to use an id the router does not list. */
function modelPicker(p, b) {
  const wrap = el("div", "mpick");
  const field = el("button", "mfield"); field.type = "button";
  field.setAttribute("aria-expanded", "false");
  const label = el("b"), chev = el("span"); chev.innerHTML = svg("caret");
  field.append(label, chev);
  const panel = el("div"); panel.style.display = "none";
  const q = el("input"); q.placeholder = "Filter models…";
  const list = el("div", "mlist scroll");
  const note = el("span", "desc", S.models.length + " models in the list");
  const det = el("button", "btn ghost sm", "Detect all models");
  const shown = () => {
    if (b.model) { label.className = ""; label.textContent = b.model; }
    else { label.className = "ph"; label.textContent = "No model picked"; }
  };
  const draw = () => {
    const cur = b.model || "", text = q.value.trim();
    const hits = modelHits(text);
    list.innerHTML = "";
    for (const m of hits.slice(0, 200)) {
      const r = el("button", "mrow" + (m === cur ? " on" : "")); r.type = "button";
      r.innerHTML = `<b>${esc(m)}</b>`;
      r.onclick = () => { b.model = m; shown(); close(); };
      list.appendChild(r);
    }
    /* An id the router does not list can still be used, so a hand-typed model is not a dead end. */
    if (text && !S.models.some(m => m.toLowerCase() === text.toLowerCase())) {
      const r = el("button", "mrow"); r.type = "button";
      r.innerHTML = `<b>${esc(text)}</b><span>Use this id — the list has no exact match</span>`;
      r.onclick = () => { b.model = text; shown(); close(); };
      list.insertBefore(r, list.firstChild);
    }
    if (!hits.length) list.appendChild(el("div", "mempty", text
      ? "No model matches “" + esc(text) + "”." : "No models in your list yet — detect them below."));
  };
  const open = () => { panel.style.display = ""; field.setAttribute("aria-expanded", "true"); draw(); q.focus(); };
  const close = () => { panel.style.display = "none"; field.setAttribute("aria-expanded", "false"); q.value = ""; };
  field.onclick = () => (panel.style.display === "none" ? open() : close());
  q.oninput = draw;
  q.onkeydown = e => { if (e.key === "Escape") { e.preventDefault(); close(); field.focus(); } };
  det.onclick = async () => {
    det.textContent = "Detecting…"; det.disabled = true;
    const r = await jpost("/api/models/detect", {});
    det.disabled = false; det.textContent = "Detect all models";
    if (r.ok) {
      S.models = r.models; note.textContent = r.count + " models detected from the API key";
      if (panel.style.display !== "none") draw();
    } else note.textContent = "Detection failed: " + (r.error || "unknown");
  };
  const row = el("div", "row"); row.append(det, note);
  panel.append(q, list);
  wrap.append(field, panel, row);
  shown();
  fld(p, "MODEL", wrap, "Pick any model the API key can reach, or type an id.");
}
function toggle(p, title, sub, on, val) {
  const d = el("div", "switch");
  d.innerHTML = `<div class="txt"><b>${esc(title)}</b><span>${esc(sub || "")}</span></div>`;
  /* A real switch: named by the setting it flips and carrying its own on/off state, which the CSS
     class alone could not tell a screen reader. */
  const t = el("button", "tg" + (val ? " on" : ""));
  t.setAttribute("role", "switch"); t.setAttribute("aria-label", title);
  t.setAttribute("aria-checked", val ? "true" : "false");
  t.onclick = () => { const nv = !t.classList.contains("on"); t.classList.toggle("on", nv);
                      t.setAttribute("aria-checked", nv ? "true" : "false"); on(nv); };
  d.appendChild(t); p.appendChild(d); return t;
}
const saveSettings = async patch => { const r = await jpost("/api/settings", { settings: patch }); S.settings = r.settings || S.settings; applyAppearance(S.settings.appearance); };

/* --- General --- */
function tabGeneral(p) {
  h3(p, "General", "App-wide behaviour. Changes apply immediately.");
  /* Two short sections instead of a column of loose rows, so the name is one thing you set and
     the two switches are another. */
  const cg = el("div", "fgroup"); cg.appendChild(el("h4", "", "Workspace"));
  input(cg, "WORKSPACE NAME", S.settings.company_name || "Anzen-bot", v => saveSettings({ company_name: v }), "Anzen-bot");
  /* Your own name labels your messages in every transcript, so saving it redraws the open chat
     rather than waiting for the next reload to show it. */
  input(cg, "YOUR NAME", S.settings.user_name || "Client",
    v => { saveSettings({ user_name: v }).then(reloadTranscript); }, "Client");
  p.appendChild(cg);
  const bg = el("div", "fgroup"); bg.appendChild(el("h4", "", "Behaviour"));
  const curV = () => S.settings.voice || {};
  toggle(bg, "Read replies aloud automatically", "Speak every finished reply with the chosen voice.",
    nv => saveSettings({ voice: { ...curV(), auto: nv } }), curV().auto);
  const curD = () => S.settings.decision || {};
  toggle(bg, "Auto-route room messages", "Let a fast model pick which bot answers an un-mentioned room message.",
    nv => saveSettings({ decision: { ...curD(), enabled: nv, jobs: { ...(curD().jobs || {}), rooms: nv } } }), curD().enabled);
  p.appendChild(bg);
  /* --- Notification sounds --- */
  const curS = () => S.settings.sound || {};
  const sc = el("div", "card");
  sc.innerHTML = `<div class="ct"><span class="ico">${svg("sound")}</span><div><b>Notification sounds</b>
    <div class="sub">A short chime when a turn finishes, fails, or stops to ask you something, so you
    can hear it from another window. Each of the three has its own cue.</div></div></div>`;
  toggle(sc, "Play a chime", "Silent until you click or type once — browsers do not allow sound before that.",
    nv => saveSettings({ sound: { ...curS(), on: nv } }), curS().on !== false);
  const vol = el("input"); vol.type = "range"; vol.min = "0"; vol.max = "1"; vol.step = "0.05";
  vol.value = String(curS().volume == null ? 0.5 : curS().volume);
  vol.oninput = () => { S.settings.sound = { ...curS(), volume: parseFloat(vol.value) }; };   // live while dragging
  /* Releasing the slider plays the cue at the new level, so the control is its own preview and
     there is no separate Test button to explain. */
  vol.onchange = () => { const v = parseFloat(vol.value);
    saveSettings({ sound: { ...curS(), volume: v } }); cue("done", v); };
  fld(sc, "VOLUME", vol, "Drag, then let go — the chime plays at the level you chose. 0 is the same as off.");
  p.appendChild(sc);
}

/* --- Channels --- */
function tabChannels(p) {
  h3(p, "Rooms", "Each room keeps its own transcript, members and responder rule.");
  const box = el("div", "bento"); p.appendChild(box);
  const draw = () => {
    box.innerHTML = "";
    for (const c of S.channels) {
      const d = el("div", "card tcard");
      d.innerHTML = `<div class="ct">${avatar(c.name, c.color, "", "", logoOf(c))}
        <div class="min"><b>${esc(c.name)}</b><div class="sub">${esc(c.mode)}</div></div></div>
        <div class="tc-body">
          <div class="metric"><div class="k">Members</div><div class="v">${(c.members || []).length}</div></div>
          <div class="metric wide"><div class="k">Repo</div><div class="v">${c.folder ? (c.folder_ok ? "" : "missing: ") + esc(c.folder) : "shared folder"}</div></div>
        </div>
        <div class="tc-foot"><button class="btn ghost sm" data-a="edit">Edit</button>
        <button class="btn ghost sm" data-a="del">Delete</button></div>`;
      d.querySelector('[data-a="edit"]').onclick = () => editChannel(c);
      d.querySelector('[data-a="del"]').onclick = async () => { if (confirm("Delete " + c.name + "?")) { await post("/api/channel/delete", { id: c.id }); await reloadConfig(); draw(); } };
      box.appendChild(d);
    }
  };
  draw();
  const add = el("button", "btn pri sm", `${svg("plus")} New room`); add.onclick = () => editChannel(null);
  const row = el("div", "row"); row.style.marginTop = "14px"; row.appendChild(add); p.appendChild(row);
}
/* The repo folder is browsable, not just a path you paste. A modal walks the disk one
   folder at a time — names only, the server never lists file contents — and hands back the
   folder you land on. The text field stays editable, so a pasted path still works. */
function browseFolder(start, onPick) {
  const { modal, close } = openPick({
    icon: "apps", title: "Choose a repo folder",
    body: `<div class="bpath">…</div><div class="blist"></div>`,
    foot: `<button class="btn ghost" data-a="up">Up</button>
    <button class="btn ghost" data-a="home">Home</button><span class="grow"></span>
    <button class="btn pri" data-a="use">Use this folder</button>`,
  });
  const pathEl = modal.querySelector(".bpath"), listEl = modal.querySelector(".blist");
  const upBtn = modal.querySelector('[data-a="up"]');
  let cur = start || "~", parent = "", home = "~";
  const join = (p, d) => (p.endsWith("/") ? p : p + "/") + d;
  async function load(p) {
    listEl.innerHTML = `<div class="brow dim">Reading…</div>`;
    let r; try { r = await get("/api/fs?path=" + encodeURIComponent(p || "")); }
    catch (e) { r = { ok: false, error: "cannot reach the server" }; }
    if (!r || !r.ok) { listEl.innerHTML = `<div class="brow dim">${esc((r && r.error) || "could not read that folder")}</div>`; return; }
    cur = r.path; parent = r.parent; home = r.home || home;
    pathEl.textContent = r.path; pathEl.title = r.path;
    upBtn.disabled = !r.parent;
    listEl.innerHTML = "";
    if (!r.dirs.length) listEl.appendChild(el("div", "brow dim", "(no subfolders here)"));
    for (const d of r.dirs) {
      const row = el("div", "brow", `<span class="bico">${svg("caret")}</span>${esc(d)}`);
      row.onclick = () => load(join(r.path, d));
      kbd(row, row.onclick);
      listEl.appendChild(row);
    }
    if (r.more) listEl.appendChild(el("div", "brow dim", `…and ${r.more} more`));
  }
  upBtn.onclick = () => load(parent);
  modal.querySelector('[data-a="home"]').onclick = () => load(home);
  modal.querySelector('[data-a="use"]').onclick = () => { onPick(cur); close(); };
  load(cur);
}
/* ZenPilot keeps every profile you are signed into open as a <webview>. Rather than type each
   site into the pin field by hand, list what is actually open and let the user tick what to reuse.
   Every path that cannot work says why, in the modal, instead of failing silently. */
async function importProfiles(onPick) {
  const z = await (await fetch("/api/browser/profiles")).json();
  const { modal, close } = openPick({
    icon: "monitor", title: "Import ZenPilot profiles",
    body: `<div class="desc" data-a="lede"></div><div class="blist" data-a="list"></div>`,
    foot: `<button class="btn ghost" data-a="all">Select all</button><span class="grow"></span>
    <button class="btn pri" data-a="use">Import selected</button>`,
  });
  const lede = modal.querySelector('[data-a="lede"]'), listEl = modal.querySelector('[data-a="list"]');
  const all = modal.querySelector('[data-a="all"]'), use = modal.querySelector('[data-a="use"]');
  const dead = html => { lede.innerHTML = html; listEl.remove(); use.remove(); all.remove(); };
  const link = `<a href="${esc(z.get_url || "")}" target="_blank" rel="noopener">Get ZenPilot</a>`;
  if (!z.installed)
    return dead(`ZenPilot is not installed on this machine. ${link}, open a profile and sign in, then press
      “Launch ZenPilot &amp; connect” in the Browser card.`);
  if (!z.up)
    return dead(`ZenPilot is installed, but nothing is answering at <code>${esc(z.cdp_url || "")}</code>.
      Press “Launch ZenPilot &amp; connect” in the Browser card, then import.`);
  const profs = z.profiles || [];
  if (!profs.length)
    return dead(`ZenPilot is running, but no profile window is open. Open a profile in ZenPilot, then import again.`);
  lede.textContent = "Tick the profiles the bots should reuse. Each one pins that site, so a bot works in the window you are already signed into.";
  const picked = new Set(profs.map(p => p.host));
  const draw = () => {
    listEl.innerHTML = "";
    for (const p of profs) {
      const on = picked.has(p.host);
      const row = skBox(`<span class="ck"></span><span><b>${esc(p.host)}</b><span>${esc(p.title)}</span></span>`, on,
        nv => { nv ? picked.add(p.host) : picked.delete(p.host); draw(); });
      listEl.appendChild(row);
    }
    all.textContent = picked.size === profs.length ? "Clear" : "Select all";
  };
  draw();
  all.onclick = () => { const wasAll = picked.size === profs.length; picked.clear();
    if (!wasAll) profs.forEach(p => picked.add(p.host)); draw(); };
  use.onclick = () => {
    if (!picked.size) { lede.textContent = "Pick at least one profile to import."; return; }
    onPick(profs.filter(p => picked.has(p.host)).map(p => p.host).join(", "));
    close();
  };
}
/* The channel's logo: an uploaded image wins, else whatever logo the repo already has, else the
   initials. The upload is keyed by channel id, so a channel has to exist before one can be added. */
function logoField(p, c) {
  const prev = el("div", "lgprev"), said = el("div", "lgsaid"), wrap = el("div", "logofld");
  const msg = el("div", "hint"), row = el("div", "row");
  const file = el("input"); file.type = "file"; file.style.display = "none";
  file.accept = "image/png,image/jpeg,image/webp,image/gif,image/svg+xml";
  const up = el("button", "btn ghost sm", "Upload logo"); up.type = "button";
  const rm = el("button", "btn ghost sm", "Remove"); rm.type = "button";
  let bad = "";
  const draw = () => {
    prev.innerHTML = avatar(c.name, c.color, "", "", logoOf(c));   // the same box the row draws
    up.disabled = rm.disabled = !c.id;                       // no id yet: nothing to attach a logo to
    rm.style.display = c.logo_src === "upload" ? "" : "none";
    // A refusal outranks the status line, or the reason flashes and is replaced by "no logo yet".
    msg.style.color = bad ? "#ff6b6b" : "";
    msg.textContent = bad || (!c.id ? "Save the room, then add its logo."
      : c.logo_src === "upload" ? "Your uploaded logo."
      : c.logo_src === "repo" ? "Using " + c.logo_rel + " from the repo."
      : "No logo yet — the initials stand in.");
  };
  const send = async (url, body, busy) => {
    up.disabled = rm.disabled = true; bad = ""; msg.textContent = busy;
    try {
      const r = await jpost(url, body);
      if (!r.ok) throw new Error(r.error || "that did not work");
      c.logo = r.logo; c.logo_src = r.logo_src; c.logo_rel = r.logo_rel;
      await reloadConfig();                                  // the sidebar row picks the logo up too
    } catch (e) { bad = String(e.message || e); }
    draw();
  };
  up.onclick = () => file.click();
  file.onchange = () => {
    const f = file.files[0]; file.value = ""; if (!f) return;
    bad = f.size > 2e6 ? "That image is larger than 2 MB — try a smaller one." : "";
    if (bad) return draw();
    const rd = new FileReader();
    rd.onload = () => send("/api/logo", { id: c.id, data: rd.result }, "Uploading…");
    rd.onerror = () => { bad = "Could not read that file."; draw(); };
    rd.readAsDataURL(f);
  };
  rm.onclick = () => send("/api/logo/remove", { id: c.id }, "Removing…");
  row.append(up, rm); said.append(row, msg); wrap.append(prev, said);
  fld(p, "LOGO", wrap,
      "Shown on the room's row. Leave it blank to use a logo found in the repo, or the initials.");
  draw();
}

/* The bot's face picture. One control, because it is one thing: introduce an image, the image model
   redraws it as this bot's face, and that face is drawn on the head where the engine's eyes and
   mouth would be. There is no separate "upload it as-is" path — a raw photo would not be a face, and
   two controls for one idea is what made this confusing to use. Stored under the bot's id, so — like
   a channel logo — the bot has to exist before it can have one. */
function avatarField(p, b, redraw) {
  const prev = el("div", "lgprev"), said = el("div", "lgsaid"), wrap = el("div", "logofld");
  const msg = el("div", "hint"), row = el("div", "row");
  const file = el("input"); file.type = "file"; file.style.display = "none";
  file.accept = "image/png,image/jpeg,image/webp";
  const add = el("button", "btn ghost sm", "Introduce an image"); add.type = "button";
  const rm = el("button", "btn ghost sm", "Remove"); rm.type = "button";
  let bad = "";
  const draw = () => {
    const url = avatarUrl(b);
    prev.innerHTML = url ? `<div class="mc img"><img src="${url}" alt=""></div>` : "";
    const has = !!b.id;
    add.disabled = rm.disabled = !has;
    rm.style.display = b.avatar ? "" : "none";
    msg.style.color = bad ? "#ff6b6b" : "";
    msg.textContent = bad || (!has ? "Save the bot, then introduce an image."
      : b.avatar ? "This picture is the bot's face. Its body, outfit, accessory and colour are drawn around it."
      : "No picture — the bot draws its own face.");
  };
  const send = async (url, body, busy) => {
    add.disabled = rm.disabled = true; bad = ""; msg.textContent = busy;
    try {
      const r = await jpost(url, body);
      if (!r.ok) throw new Error(r.error || "that did not work");
      b.avatar = r.avatar || 0;
      await reloadConfig();
      redraw();
    } catch (e) { bad = String(e.message || e); }
    draw();
  };
  add.onclick = () => file.click();
  /* The transform runs image-to-image at the router, so it is 30-60s of real work. The button says
     so while it waits rather than looking hung, and the species and colour already picked are sent
     along so the face it draws sits on the bot it is being drawn for. */
  file.onchange = () => {
    const f = file.files[0]; file.value = ""; if (!f) return;
    if (f.size > 6e6) { bad = "That image is larger than 6 MB — try a smaller one."; return draw(); }
    const rd = new FileReader();
    rd.onload = () => send("/api/avatar/transform",
      { id: b.id, data: rd.result, species: b.face || speciesFor(b.id || b.name), color: b.color },
      "Redrawing your image as this bot's face… this takes up to a minute.");
    rd.onerror = () => { bad = "Could not read that file."; draw(); };
    rd.readAsDataURL(f);
  };
  rm.onclick = () => send("/api/avatar/remove", { id: b.id }, "Removing…");
  row.append(add, rm); said.append(row, msg); wrap.append(prev, said, file);
  fld(p, "FACE PICTURE", wrap,
      "Introduce an image and the image model redraws it as this bot's face, in place of the drawn eyes and mouth — those stay off, so you never get two of them. It keeps blinking, looking around and showing its mood, and the body, outfit, accessory and colour below are drawn around it.");
  draw();
}

function editChannel(c) {
  c = c || { name: "", mode: "lead", members: S.bots.map(b => b.id), lead: (S.bots[0] || {}).id, instructions: "", folder: "" };
  const p = $("#setPanel"); p.innerHTML = "";
  h3(p, c.id ? "Edit room" : "New room", "Members answer by the responder rule.");
  const baseG = el("div", "fgroup"); baseG.appendChild(el("h4", "", "Basics"));
  input(baseG, "NAME", c.name, v => c.name = v, "e.g. Marketing");
  selectFld(baseG, "RESPONDER", c.mode, [["lead", "Lead bot answers"], ["auto", "Auto (a fast model picks)"], ["everyone", "Everyone answers"]], v => c.mode = v);
  selectFld(baseG, "LEAD", c.lead, S.bots.map(b => [b.id, b.name]), v => c.lead = v);
  p.appendChild(baseG);
  const memG = el("div", "fgroup"); memG.appendChild(el("h4", "", "Members"));
  const ml = el("div", "sklist");
  for (const b of S.bots) {
    const on = (c.members || []).includes(b.id);
    const s = skBox(`<span class="ck"></span><span><b>${esc(b.name)}</b><span>${esc(b.title || "")}</span></span>`, on,
      nv => { const set = new Set(c.members || []); nv ? set.add(b.id) : set.delete(b.id); c.members = [...set]; });
    ml.appendChild(s);
  }
  fld(memG, "MEMBERS", ml);
  p.appendChild(memG);
  const repoG = el("div", "fgroup"); repoG.appendChild(el("h4", "", "Repo & notes"));
  input(repoG, "SHARED INSTRUCTIONS", c.instructions, v => c.instructions = v, "optional");
  const fwrap = el("div", "fldrow");
  const fin = el("input"); fin.type = "text"; fin.value = c.folder || "";
  fin.placeholder = "~/code/my-app"; fin.onchange = () => c.folder = fin.value;
  const fbrw = el("button", "btn ghost", "Browse"); fbrw.type = "button";
  fbrw.onclick = () => browseFolder(c.folder || "", p => { fin.value = p; c.folder = p; });
  fwrap.append(fin, fbrw);
  fld(repoG, "REPO FOLDER", fwrap, "one repo per room, e.g. ~/code/my-app. Blank = a shared folder");
  repoG.appendChild(el("div", "hint", "Bots in this room run their shell and file tools inside this folder only, so repos never mix. Leave blank to use a shared folder."));
  p.appendChild(repoG);
  logoField(p, c);   // after the folder, so the logo it finds in that repo is already known
  const err = el("div", "hint"); err.style.color = "#ff6b6b";
  p.appendChild(err);
  const row = el("div", "row"); row.style.marginTop = "6px";
  const save = el("button", "btn pri", "Save");
  save.onclick = async () => {
    const r = await jpost("/api/channel", { channel: c });
    if (!r.ok) { err.textContent = r.error || "could not save"; return; }
    err.textContent = "";
    await reloadConfig(); renderTabs(); renderPanel();
  };
  const back = el("button", "btn ghost", "Back"); back.onclick = () => renderPanel();
  row.append(save, back); p.appendChild(row);
}

/* --- Bots --- */
function tabBots(p) {
  // sub-panels render their own heading, so they must come before the list heading
  if (curEdit === "__import__") return importPanel(p);
  if (curEdit) return botEditor(p, bot(curEdit));
  h3(p, "Bots", "Every bot: its own model, approval level, memory, skills, tools and look.");
  /* One card per bot, on a bento. The head names it, the body carries the facts as labelled
     metrics, the foot carries the verb — so a team of twenty is scanned rather than read. */
  const box = el("div", "bento");
  for (const b of S.bots) {
    const d = el("div", "card tcard");
    const metrics = [["Title", b.title || "—"], ["Model", b.model || "—"],
                     ["Approval", b.approval || "ask"], ["Memory", b.memory === false ? "off" : "on"]]
      .map(([k, v]) => `<div class="metric"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`).join("");
    d.innerHTML = `<div class="ct">${avatar(b.name, b.color, "", b.emoji)}
      <div class="min"><b>${esc(b.name)}</b>${b.pinned ? `<span class="tag">pinned</span>` : ""}${b.hidden ? `<span class="tag">hidden</span>` : ""}
      <div class="sub">${esc(b.role || b.title || "bot")}</div></div></div>
      <div class="tc-body">${metrics}</div>
      <div class="tc-foot"><button class="btn ghost sm" data-a="edit">Edit</button></div>`;
    d.querySelector('[data-a="edit"]').onclick = () => { curEdit = b.id; renderPanel(); };
    box.appendChild(d);
  }
  p.appendChild(box);
  const row = el("div", "row"); row.style.marginTop = "14px";
  const add = el("button", "btn pri sm", `${svg("plus")} New bot`); add.onclick = () => { curEdit = "__new__"; renderPanel(); };
  const imp = el("button", "btn ghost sm", `${svg("bots")} Import a team`); imp.onclick = () => { curEdit = "__import__"; renderPanel(); };
  row.append(add, imp); p.appendChild(row);
}
function importPanel(p) {
  h3(p, "Import a team", "Paste a team from BotMRR (botmrr.io), or just names and positions, and the bots are built for you.");
  const ta = el("textarea"); ta.style.minHeight = "240px";
  ta.placeholder = "On botmrr.io open a team, hit Copy, and paste the whole thing here.\n\nOr just type a list:\nLea: Producer\nAlex: UI\nDima: Dev";
  fld(p, "PASTED TEAM", ta, "A BotMRR playbook builds the bots, their roles and a shared room. A plain list builds the bots.");
  const out = el("div");
  const row = el("div", "row");
  /* The structure is handed out so it can be handed to a model: copy it, describe the team you want
     around it, and paste back what comes out. What comes back is held to the same structure, and
     anything missing is named below the box rather than imported half-built. */
  const tpl = el("button", "btn ghost sm", `${svg("copy")} Copy the structure`);
  tpl.onclick = () => copyText(S.teamTemplate || "", tpl);
  const build = el("button", "btn pri", "Build team");
  const back = el("button", "btn ghost", "Back"); back.onclick = () => { curEdit = null; renderPanel(); };
  build.onclick = async () => {
    if (!ta.value.trim()) return;
    build.disabled = true; build.textContent = "Building…";
    let r = {};
    try { r = await jpost("/api/team/import", { text: ta.value }); }
    catch (e) { r = { ok: false, error: isOffline(e) ? "could not reach the server" : String(e) }; }
    build.disabled = false; build.textContent = "Build team";
    if (!r.ok) {
      const miss = (r.problems || []).map(x => `<li>${esc(x)}</li>`).join("");
      out.innerHTML = `<div class="hint">${esc(r.error || "could not read that")}${miss ? `<ul class="probs">${miss}</ul>` : ""}</div>`;
      return;
    }
    await reloadConfig();
    out.innerHTML = `<div class="card"><div class="ct"><div><b>Added ${r.created.length} bot${r.created.length === 1 ? "" : "s"}</b>
      <div class="sub">${esc(r.created.join(" · "))}${r.room ? ", room: " + esc(r.room) : ""}</div></div></div></div>`;
  };
  row.append(tpl, build, back);
  p.appendChild(row);
  p.appendChild(el("div", "hint", "Send the structure to your AI with the team you want, then paste its answer above."));
  p.appendChild(out);
}
function botEditor(p, b) {
  const isNew = !b;
  b = b || { id: "", name: "", title: "", role: "", color: "blue", model: S.models[0], approval: "ask",
    memory: true, voice: "", instructions: "", skills: [], tools_allow: null, hidden: false, pinned: false,
    emoji: "", face: "", outfit: "", accessory: "", avatar: 0 };
  h3(p, isNew ? "New bot" : "Edit " + b.name, "Give the bot a name, a brain, and what it may do.");
  /* The editor is long, so it reads as five short sections — who the bot is, how it looks, how it
     thinks, what it knows, what it may run — instead of one undivided column of fields. */
  const idG = el("div", "fgroup"); idG.appendChild(el("h4", "", "Identity"));
  input(idG, "NAME", b.name, v => b.name = v, "e.g. Designer");
  input(idG, "EMOJI (optional)", b.emoji || "", v => b.emoji = v.trim(), "a small mark shown before the bot's name in the header and the bot list");
  input(idG, "TITLE", b.title, v => b.title = v, "e.g. Design");
  input(idG, "ROLE (one line)", b.role, v => b.role = v, "short description");
  const cols = el("div", "seg");
  for (const c of ["purple", "blue", "green", "orange", "yellow", "pink"]) {
    const x = el("button", c === b.color ? "on" : "", c); x.onclick = () => { b.color = c; [...cols.children].forEach(n => n.classList.remove("on")); x.classList.add("on"); drawFace(); };
    cols.appendChild(x);
  }
  fld(idG, "COLOR", cols);
  /* FACE — the bot's species: body shape, ears, eyes and idle motion. Blank means
     "derive it from the name", so a fresh team still comes out looking distinct. */
  const faceWrap = el("div", "seg");
  const prev = el("canvas"); prev.width = 84; prev.height = 84;
  prev.setAttribute("aria-hidden", "true");   // decorative preview of the face picked below
  let prevM = null;
  const drawFace = () => {
    if (prevM) detach(prevM);
    prevM = S.facePrev = attach(prev, "idle", { size: 84, species: b.face || speciesFor(b.id || b.name), ...sideFace(b.color), ...lookOf(b) });
  };
  /* One row of choices per axis. `blank` is the honest default for every one of them — no garment,
     and a face derived from the name — so a bot left alone still looks like itself. */
  const picker = (keys, cur, set) => {
    const wrap = el("div", "seg");
    for (const [k, label] of [["", "None"], ...keys]) {
      const x = el("button", cur === k ? "on" : "", label);
      x.onclick = () => {
        set(k);
        [...wrap.children].forEach(n => n.classList.remove("on")); x.classList.add("on");
        drawFace();
      };
      wrap.appendChild(x);
    }
    return wrap;
  };
  const faceBtn = (k, label) => {
    const x = el("button", b.face === k ? "on" : "", label);
    x.onclick = () => {
      b.face = b.face === k ? "" : k;
      [...faceWrap.children].forEach(n => n.classList.remove("on"));
      if (b.face) x.classList.add("on");
      drawFace();
    };
    return x;
  };
  for (const [k, sp] of Object.entries(SPECIES)) faceWrap.appendChild(faceBtn(k, sp.label));
  p.appendChild(idG);
  const lookG = el("div", "fgroup"); lookG.appendChild(el("h4", "", "Look"));
  fld(lookG, "FACE", faceWrap, "Each bot gets its own shape, ears and idle motion. Leave blank to let the name pick one.");
  const fp = fld(lookG, "PREVIEW", prev, "This is the bot as it will look in the sidebar.");
  fp.querySelector("canvas").style.cssText = "width:84px;height:84px;border-radius:18px;background:var(--card2);border:1px solid var(--line)";
  drawFace();
  const outfitWrap = picker(Object.entries(OUTFITS).map(([k, v]) => [k, v.label]), b.outfit || "", v => b.outfit = v);
  fld(lookG, "OUTFIT", outfitWrap, "What it wears on its body. Fixed colours, so a garment stays legible whatever the bot's own colour is.");
  const accWrap = picker(Object.entries(ACCESSORIES).map(([k, v]) => [k, v.label]), b.accessory || "", v => b.accessory = v);
  fld(lookG, "ACCESSORY", accWrap, "What it wears on its head or face. Anchored to the bot's own eye row, so it sits right on every shape.");
  avatarField(lookG, b, drawFace);
  p.appendChild(lookG);
  const brainG = el("div", "fgroup"); brainG.appendChild(el("h4", "", "Brain"));
  modelPicker(brainG, b);
  selectFld(brainG, "APPROVAL LEVEL", b.approval,
    APPROVALS.map(([v, t]) => [v, t]),
    v => b.approval = v, "Plan only = plan first and wait for your go-ahead; Ask = cards for risky shell commands; Auto-accept and Approve routine = as Ask today; Full = runs without asking.");
  toggle(brainG, "Let this bot use memory", "Load its notes into every turn (chat, rooms and delegations), let it write notes, and let it self-learn from its own runs.", nv => b.memory = nv, b.memory);
  const ta = el("textarea"); ta.value = b.instructions || ""; ta.onchange = () => b.instructions = ta.value;
  fld(brainG, "STANDING INSTRUCTIONS", ta, "The bot's system prompt.");
  p.appendChild(brainG);
  const skillG = el("div", "fgroup"); skillG.appendChild(el("h4", "", "Skills"));
  const sk = el("div", "sklist");
  for (const s of S.skills) {
    const on = (b.skills || []).includes(s.id);
    const d = skBox(`<span class="ck"></span><span><b>${esc(s.name)}</b><span>${esc(s.desc)}</span></span>`, on,
      nv => { const set = new Set(b.skills || []); nv ? set.add(s.id) : set.delete(s.id); b.skills = [...set]; });
    sk.appendChild(d);
  }
  fld(skillG, "SKILLS", sk, "Skills shape what the bot is good at.");
  p.appendChild(skillG);
  const toolG = el("div", "fgroup"); toolG.appendChild(el("h4", "", "Tools"));
  /* The tick-list is drawn by a function, not once inline: it is gated on b.tools_allow, and the
     select sets that *after* this section has already been built, so a one-shot draw would leave
     "Custom selection" showing an empty box. The names come from the server (S.tools), so the
     picker can never drift out of step with the tools the server actually offers. */
  const toolBody = el("div");
  const drawTools = () => {
    toolBody.innerHTML = "";
    if (!b.tools_allow) return;
    const known = S.tools || [];
    const names = [...new Set([...known.map(t => t.name), ...(S.connectorTools || []).map(t => t.tool)])];
    const descOf = t => {
      const k = known.find(x => x.name === t); if (k) return k.desc || "";
      const c = (S.connectorTools || []).find(x => x.tool === t); return c ? "From the " + c.name + " connection" : "";
    };
    const tl = el("div", "sklist");
    for (const t of names) {
      const on = b.tools_allow.includes(t);
      const d = skBox(`<span class="ck"></span><span><b>${esc(t)}</b><span>${esc(descOf(t))}</span></span>`, on,
        nv => { const set = new Set(b.tools_allow); nv ? set.add(t) : set.delete(t); b.tools_allow = [...set]; });
      tl.appendChild(d);
    }
    fld(toolBody, "ALLOWED TOOLS", tl, "Tick what this bot may run. A small-context model does better with fewer.");
  };
  selectFld(toolG, "TOOL SELECTION", b.tools_allow ? "custom" : "all",
    [["all", "All current tools"], ["custom", "Custom selection"]],
    v => { b.tools_allow = v === "custom" ? (b.tools_allow || ["run_shell", "read_file", "list_files", "finish"]) : null; drawTools(); },
    "Reduce tools for small-context models.");
  toolG.appendChild(toolBody);
  drawTools();
  p.appendChild(toolG);
  const row = el("div", "row"); row.style.marginTop = "6px";
  const save = el("button", "btn pri", "Save bot");
  save.onclick = async () => {
    if (!b.name.trim()) return alert("Give the bot a name.");
    await post("/api/bot", { bot: b }); curEdit = null; await reloadConfig(); renderPanel();
  };
  const back = el("button", "btn ghost", "Back"); back.onclick = () => { curEdit = null; renderPanel(); };
  row.append(save, back);
  if (!isNew) {
    const del = el("button", "btn deny", "Delete"); del.onclick = async () => { if (confirm("Delete " + b.name + "?")) { await post("/api/bot/delete", { id: b.id }); curEdit = null; await reloadConfig(); renderPanel(); } };
    row.appendChild(del);
  }
  p.appendChild(row);
}

/* --- AI model --- */
function tabModels(p) {
  h3(p, "AI model", "The endpoint every bot talks to, and the models it can reach.");
  /* --- Connection: the router URL + API key every bot talks to --- */
  const cc = el("div", "card");
  cc.innerHTML = `<div class="ct"><span class="ico">${svg("router")}</span><div><b>Connection</b>
    <div class="sub">The OpenAI-compatible endpoint every bot talks to. Paste your own router URL and API key here.</div></div></div>`;
  const cUrl = el("input"); cUrl.placeholder = "https://openrouter.ai/api/v1 · https://api.openai.com/v1 · http://127.0.0.1:11434/v1";
  const cKey = el("input"); cKey.type = "password"; cKey.style.marginTop = "8px";
  const cDm = el("input"); cDm.placeholder = "Default model id (must support tool-calling)"; cDm.style.marginTop = "8px";
  const cVm = el("input"); cVm.placeholder = "Vision model for browser_see (optional, comma-separated)"; cVm.style.marginTop = "8px";
  const cNote = el("div", "desc", "Loading current connection…"); cNote.style.marginTop = "8px";
  const cRow = el("div", "row"); cRow.style.marginTop = "10px";
  const cSave = el("button", "btn pri sm", "Save connection");
  const cTest = el("button", "btn ghost sm", "Test connection"); cTest.style.marginLeft = "8px";
  cRow.append(cSave, cTest);
  cc.append(cUrl, cKey, cDm, cVm, cNote, cRow);
  p.appendChild(cc);
  const keyHint = set => set ? "••••••••  saved. Leave blank to keep it" : "sk-…  your API key (stored server-side, never shown again)";
  (async () => {
    const c = await get("/api/config"); if (!c) return;   // a failed read leaves the card's last values
    cUrl.value = c.router || ""; cDm.value = c.default_model || ""; cVm.value = c.vision_model || "";
    cKey.placeholder = keyHint(c.key_set);
    cNote.textContent = "Now talking to " + (c.router || "none") + (c.key_set ? " with a saved API key." : " without an API key.");
  })();
  cSave.onclick = async () => {
    cNote.textContent = "Saving…";
    const body = { router: cUrl.value.trim(), default_model: cDm.value.trim(), vision_model: cVm.value.trim() };
    if (cKey.value.trim()) body.key = cKey.value.trim();
    const r = await jpost("/api/config", body);
    if (r.ok) {
      cKey.value = ""; cKey.placeholder = keyHint(r.key_set);
      cNote.textContent = "Saved. Now talking to " + r.router + (r.key_set ? " (key stored)." : " (no key).");
    } else cNote.textContent = "Could not save: " + (r.error || "unknown");
  };
  cTest.onclick = async () => {
    cNote.textContent = "Testing the router…";
    const r = await jpost("/api/models/detect", {});
    if (r.ok) { S.models = r.models; cNote.textContent = "Works: " + r.count + " models reachable with this connection."; renderPanel(); }
    else cNote.textContent = "Failed: " + (r.error || "unknown") + ". Check the URL and key.";
  };
  /* --- Models: what the API key can reach (first, so it is never below the fold) --- */
  const mc = el("div", "card");
  mc.innerHTML = `<div class="ct"><span class="ico">${svg("models")}</span><div><b>Models</b>
    <div class="sub">${S.models.length} available · any bot can use any of them</div></div></div>`;
  const det = el("button", "btn pri sm", "Detect all models");
  det.onclick = async () => {
    det.textContent = "Detecting…"; det.disabled = true;
    const r = await jpost("/api/models/detect", {});
    det.disabled = false; det.textContent = "Detect all models";
    if (r.ok) S.models = r.models; else alert("Detection failed: " + (r.error || "unknown"));
    renderPanel();
  };
  mc.appendChild(det);
  const ai = el("input"); ai.placeholder = "Add a model id by hand, e.g. cmc/Qwen/Qwen3.7-Max";
  ai.setAttribute("aria-label", "Model id to add");
  const ab = el("button", "btn ghost sm", "Add model");
  ab.onclick = async () => {
    const v = ai.value.trim(); if (!v) return;
    const r = await jpost("/api/models/add", { model: v });
    if (r.ok) S.models = r.models; renderPanel();
  };
  const arow = el("div", "row"); arow.style.marginTop = "10px"; arow.append(ai, ab);
  mc.appendChild(arow);
  const q = el("input"); q.placeholder = "Filter models…"; q.style.marginTop = "10px";
  q.setAttribute("aria-label", "Filter models");
  const list = el("div", "sklist scroll"); list.style.marginTop = "8px";
  /* A router can hand back several hundred models, and printing every one of them buries the Context
     and Image cards under a wall of names nobody scrolls. A dozen is enough to see the list is real
     and to remove something by name; the filter is how you reach the rest, and "Show all" is there for
     when you really do want to read the whole thing. */
  const LIST_CAP = 12;
  let showAll = false;
  const draw = () => {
    list.innerHTML = "";
    const hits = modelHits(q.value);
    const shown = showAll ? hits : hits.slice(0, LIST_CAP);
    for (const m of shown) {
      const d = el("div", "sk on");
      d.innerHTML = `<span class="ck"></span><span><b>${esc(m)}</b></span>`;
      const x = el("button", "btn ghost sm", "Remove");
      x.onclick = async e => { e.stopPropagation();
        const r = await jpost("/api/models/remove", { model: m });
        if (r.ok) S.models = r.models; renderPanel(); };
      d.appendChild(x); list.appendChild(d);
    }
    if (!hits.length) list.innerHTML = `<div class="desc">No model matches “${esc(q.value)}”.</div>`;
    else if (hits.length > shown.length) {
      const more = el("button", "btn ghost sm", "Show all " + hits.length);
      more.style.marginTop = "6px";
      more.onclick = () => { showAll = true; draw(); };
      list.appendChild(more);
    }
  };
  q.oninput = () => { showAll = false; draw(); }; draw();
  mc.append(q, list);
  p.appendChild(mc);
  /* --- Context: how much of a model's window one request may use --- */
  const xc = el("div", "card");
  xc.innerHTML = `<div class="ct"><span class="ico">${svg("models")}</span><div><b>Context</b>
    <div class="sub">Every model has a maximum context window. When a long run fills it, the oldest
    steps are dropped so the model answers instead of erroring.</div></div></div>`;
  const ccfg = () => S.settings.context || {};
  const cx = el("input"); cx.type = "number"; cx.min = "0"; cx.step = "1000"; cx.value = String(ccfg().limit || 0);
  cx.onchange = () => saveSettings({ context: { ...ccfg(), limit: Math.max(0, parseInt(cx.value || "0", 10) || 0) } });
  fld(xc, "CONTEXT LIMIT (TOKENS)", cx, "0 follows the model's own window. Set a number to cap a request yourself — handy when a model's real window is smaller than its name suggests.");
  const ms = el("input"); ms.type = "number"; ms.min = "0"; ms.step = "5"; ms.value = String(ccfg().max_steps || 0);
  ms.onchange = () => saveSettings({ context: { ...ccfg(), max_steps: Math.max(0, parseInt(ms.value || "0", 10) || 0) } });
  fld(xc, "MAX STEPS PER TURN", ms, "How many model calls one turn may make before it must report. 0 uses the default (80). A step is one action — open a page, read it, click — so a browsing job needs many; raise it if a bot is still being cut off mid-work.");
  const mt = el("input"); mt.type = "number"; mt.min = "0"; mt.step = "60"; mt.value = String(ccfg().max_seconds || 0);
  mt.onchange = () => saveSettings({ context: { ...ccfg(), max_seconds: Math.max(0, parseInt(mt.value || "0", 10) || 0) } });
  fld(xc, "MAX SECONDS PER TURN", mt, "An optional hard cap on how long one turn may keep working, in seconds. 0 — the default — is no cap: the turn runs until it has spent its step budget, so a slow but real job is never cut off for taking a long time. Set a number only if you want a runaway stopped by the clock as well. The cap is checked between steps, so a command or a model answer already running is allowed to finish.");
  const rt = el("input"); rt.type = "number"; rt.min = "0"; rt.max = "10"; rt.step = "1"; rt.value = String(ccfg().model_retries || 0);
  rt.onchange = () => saveSettings({ context: { ...ccfg(), model_retries: Math.min(10, Math.max(0, parseInt(rt.value || "0", 10) || 0)) } });
  fld(xc, "RETRIES IF THE MODEL GOES QUIET", rt, "How many times to try again when a model call says nothing at all. 0 uses the default (10), so eleven tries in total. A call that fails fast — a refusal, a dropped connection — gets all of them; a model that has gone silent spends the full wait on each try, so it gets about three before the app stops and reports. Raise it on a connection that keeps dropping mid-answer.");
  const stl = el("input"); stl.type = "number"; stl.min = "0"; stl.max = "3600"; stl.step = "10"; stl.value = String(ccfg().model_stall_seconds || 0);
  stl.onchange = () => saveSettings({ context: { ...ccfg(), model_stall_seconds: Math.min(3600, Math.max(0, parseInt(stl.value || "0", 10) || 0)) } });
  fld(xc, "WAIT BEFORE RETRYING", stl, "How long to wait, in seconds, for the model to say something before giving up on that try and starting another. 0 uses the default (120). Raise it for a slow model that thinks for a long time before it answers.");
  toggle(xc, "Compress when it runs out", "Drop the oldest tool output so a long turn still gets an answer.",
    v => saveSettings({ context: { ...ccfg(), compress: v } }), ccfg().compress !== false);
  p.appendChild(xc);
  /* --- Media: which model draws pictures --- */
  const mdc = el("div", "card");
  mdc.innerHTML = `<div class="ct"><span class="ico">${svg("models")}</span><div><b>Image generation</b>
    <div class="sub">Which model draws pictures when a bot uses the draw-image tool.</div></div></div>`;
  const sel = el("select"); sel.style.marginTop = "10px";
  const note = el("div", "desc", "Checking which models can draw…");
  mdc.append(sel, note);
  p.appendChild(mdc);
  (async () => {
    const r = await (await fetch("/api/media/models")).json();
    const imgs = r.image || [];
    if (!imgs.length) { note.textContent = "No image-capable model found on this API key."; sel.remove(); return; }
    sel.innerHTML = "";
    for (const m of imgs) { const o = el("option", "", esc(m)); o.value = m; sel.appendChild(o); }
    sel.value = r.image_model || imgs[0];
    note.textContent = imgs.length + " image-capable model" + (imgs.length === 1 ? "" : "s") +
      " on this API key. Video: " + ((r.video || []).length ? (r.video.length + " available") : "none available on this API key");
    sel.onchange = async () => {
      const rr = await jpost("/api/media/model", { model: sel.value });
      note.textContent = rr.ok ? ("Saved. Bots now draw with " + sel.value) : ("Could not save: " + (rr.error || "unknown"));
    };
  })();
}
/* --- Browser: which browser the bots drive --- */
function tabBrowser(p) {
  h3(p, "Browser", "Which browser the bots drive, and the logins it keeps for you.");
  /* --- Browser: which browser the bots drive --- */
  const brc = el("div", "card");
  brc.innerHTML = `<div class="ct"><span class="ico">${svg("monitor")}</span><div><b>Browser</b>
    <div class="sub">Where the bots browse. Pick one of the three ways below; the line under the box says what the one you picked does.</div></div></div>`;
  const bmode = el("select"); bmode.style.marginTop = "10px";
  for (const [v, t] of [["own", "Own browser (a fresh browser each time — no logins)"],
                        ["profiles", "Own browser — saved profiles (sign in once, logins kept)"],
                        ["cdp", "ZenPilot / any browser over CDP"]]) {
    const o = el("option", "", esc(t)); o.value = v; bmode.appendChild(o);
  }
  /* The explanation follows the choice instead of covering all three at once. Three modes described in
     one paragraph is how a settings screen turns into something nobody reads. */
  const bmodehint = el("div", "desc");
  bmodehint.style.cssText = "margin-top:4px;max-width:640px";
  const setModeHint = () => {
    bmodehint.textContent = {
      own: "A fresh browser every time. Fast and private, but nothing is logged in — right for searching "
         + "the web and reading public pages.",
      profiles: "One browser per account, with its logins saved to disk. Add an account below, press Sign in, "
              + "log in once in the window that opens, then close the window — closing is what saves the login.",
      cdp: "Reuses the profiles already open in ZenPilot, over its debug port below.",
    }[bmode.value] || "";
  };
  /* Which browser we actually launch. This exists because of a hard wall: Google will not sign
     anyone in on the Chromium Playwright ships ("This browser or app may not be secure"), but it
     signs in fine on a real Chrome installed on this machine. So the choice is offered, and the
     options are only the browsers that are really here. */
  const bchan = el("select"); bchan.style.marginTop = "8px";
  const bchanhint = el("div", "desc");
  bchanhint.style.cssText = "margin-top:4px;max-width:640px";
  const bport = el("input"); bport.type = "number"; bport.min = "1"; bport.max = "65535";
  bport.style.marginTop = "8px"; bport.style.width = "100%"; bport.placeholder = "9222";
  const bphint = el("div", "desc");
  const btarget = el("input"); btarget.style.marginTop = "8px"; btarget.style.width = "100%";
  btarget.placeholder = "Profiles to keep on screen, comma-separated — e.g. gemini.google.com, openart.ai";
  btarget.title = "Each site opens in its own profile anyway; this only decides which ones ZenPilot keeps on screen. Empty means the first one opened.";
  /* One row per account, and the row *is* the whole feature: a name, the sites it handles, and the
     window you sign in in. There is no separate syntax to learn — the box you type in is the box
     that routes. */
  const bacc = el("div"); bacc.style.marginTop = "10px";
  const baccrows = el("div");
  const baddacc = el("button", "btn ghost sm", "Add account"); baddacc.style.marginTop = "6px";
  bacc.append(baccrows, baddacc);
  const bhl = el("label", "desc");
  bhl.style.cssText = "display:flex;gap:8px;align-items:flex-start;margin-top:10px";
  const bhlcb = el("input"); bhlcb.type = "checkbox"; bhlcb.style.marginTop = "2px";
  bhl.append(bhlcb, document.createTextNode(
    "Run the bots' browsers without a window (headless). Signing in always opens a window."));
  const bnote = el("div", "desc", "Checking…"); bnote.id = "browserNote";
  const btest = el("button", "btn ghost sm", "Test connection");
  const blaunch = el("button", "btn pri sm", "Launch ZenPilot & connect");
  const bimp = el("button", "btn ghost sm", "Import profiles");
  const brow = el("div", "row"); brow.style.marginTop = "10px"; brow.append(btest, blaunch, bimp);
  const bzp = el("div", "zpwarn"); bzp.style.display = "none";
  brc.append(bmode, bmodehint, bchan, bchanhint, bport, bphint, btarget, brow, bacc, bhl, bzp, bnote); p.appendChild(brc);
  let zp = null;                       // the last /api/browser/profiles answer, for the banner + modal
  let accounts = [];                   // the accounts list, kept locally so a row can be edited live
  let rows = [];                       // {name, info, btn} per drawn row, so a refresh can repaint it
  let drawTimer = null;                // the poll that watches for a sign-in landing in the other window
  let drawBusy = false;                // one refresh in flight at a time, so a slow one cannot stack
  let quiet = 0;                       // ticks since the last window closed, so a slow write still lands
  // One number, used for both the launch and the connect, so the two can never disagree.
  const portOf = () => { const n = parseInt(bport.value || "", 10); return (n >= 1 && n <= 65535) ? n : 9222; };
  const endpoint = () => "http://127.0.0.1:" + portOf();
  const setPortHint = () => { bphint.textContent = "DEBUG PORT — the bots connect to " + endpoint() +
    ", and “Launch ZenPilot & connect” opens it on the same port."; };
  (async () => {
    const r = await (await fetch("/api/browser")).json();
    bmode.value = ["cdp", "profiles"].includes(r.mode) ? r.mode : "own";
    bport.value = String(r.port || 9222);
    btarget.value = r.target_url || "";
    bhlcb.checked = !!r.headless;
    accounts = (r.accounts || []).map(a => ({ name: a.name || "", sites: a.sites || "" }));
    /* Only browsers that are really installed are offered, plus "automatic" and the one we ship.
       A choice that names a browser this machine does not have would be a lie in a dropdown. */
    const chans = r.channels || [];
    const chLabel = k => k === "bundled" ? "Playwright's Chromium"
      : (chans.find(c => c.key === k) || {}).label || (chans[0] ? chans[0].label : "Playwright's Chromium");
    for (const [v, t] of [["auto", "Automatic — " + (chans.length ? chans[0].label : "Playwright's Chromium")],
                          ...chans.map(c => [c.key, c.label]),
                          ["bundled", "Playwright's Chromium (fast, but Google blocks its sign-in)"]]) {
      const o = el("option", "", esc(t)); o.value = v; bchan.appendChild(o);
    }
    bchan.value = ["auto", "bundled", ...chans.map(c => c.key)].includes(r.channel) ? r.channel : "auto";
    const setChanHint = () => {
      const bundled = bchan.value === "bundled" || (bchan.value === "auto" && !chans.length);
      bchanhint.textContent = bundled
        ? "Playwright's own Chromium — fast, but Google refuses to sign in on it (“This browser or app "
          + "may not be secure”). Pick a real browser above if you need Google or Facebook logins."
        : "Sign-ins open in " + chLabel(bchan.value) + " — a browser actually installed on this Mac, which "
          + "is why Google will sign in here. Each account keeps its own logins in its own folder.";
    };
    const prof = () => bmode.value === "profiles";
    const show = () => {
      const cdp = bmode.value === "cdp", pr = prof();
      setModeHint();
      for (const e of [bchan, bchanhint]) e.style.display = cdp ? "none" : "";
      for (const e of [bport, bphint, btarget, brow]) e.style.display = cdp ? "" : "none";
      for (const e of [bacc, bhl]) e.style.display = pr ? "" : "none";
      bzp.style.display = (cdp && zp && !zp.installed) ? "" : "none";
      if (pr) drawAccounts();
      else { clearTimeout(drawTimer); drawTimer = null; }   // the sign-in poll belongs to this card only
    };
    /* One plain sentence in the card; the raw error stays on hover so nothing is hidden. Called
       again once the disk check lands, so a missing ZenPilot overrides the connect hint instead of
       the two lines contradicting each other. */
    /* One plain sentence in the card; the raw error stays on hover so nothing is hidden. Saved
       profiles have nothing connected — each account's browser opens on demand — so saying
       "connected" there would be a small lie the user has to work around. */
    const say = o => o.mode === "profiles" ? "Ready — an account's browser opens the first time a bot visits one of its sites."
                                           : ("Connected" + (o.attached ? " to an existing browser." : " with our own browser."));
    const setNote = () => {
      if (zp && !zp.installed && bmode.value === "cdp") { bnote.textContent = "ZenPilot is not installed — see below."; bnote.title = ""; }
      else if (r.running) { bnote.textContent = say(r); bnote.title = ""; }
      else { bnote.textContent = "Not running — " + (r.hint || r.err || "starting…"); bnote.title = r.err || ""; }
    };
    show(); setNote(); setPortHint(); setChanHint();
    const why = o => {
      bnote.textContent = o.ok ? say(o) : ("Could not connect — " + (o.hint || o.err || "unknown"));
      bnote.title = o.ok ? "" : (o.err || "");
    };
    /* The mode is what the running browser was built as, so changing it has to be saved *and*
       restarted — otherwise the card shows one mode while the bots are still driving the old one,
       and a Sign in lands on a browser that is not a saved profile at all. */
    bmode.onchange = async () => { show(); await save(); why(await jpost("/api/browser/restart", {})); };
    /* The browser is picked when a window is launched, so an open one is still the old build —
       saving and restarting drops it rather than leaving two browsers disagreeing. */
    bchan.onchange = async () => { setChanHint(); await save(); why(await jpost("/api/browser/restart", {})); };
    bport.oninput = setPortHint;                                 // the hint follows what you type
    bport.onchange = () => { bport.value = String(portOf()); setPortHint(); };
    const save = () => post("/api/settings", { settings: { browser: {
      mode: bmode.value, port: portOf(), target_url: btarget.value.trim(),
      accounts: accounts.filter(a => a.name).map(a => ({ name: a.name, sites: a.sites })),
      headless: bhlcb.checked, channel: bchan.value } } });
    /* Accounts are read fresh on every open, so a saved row takes effect on the bot's next step —
       no restart. Headless is read when a profile's browser is launched, so that one restarts. */
    bhlcb.onchange = async () => { await save(); why(await jpost("/api/browser/restart", {})); };
    /* The list. A row is a name, the sites it handles, and the window you sign in in — so there is
       no second place to write the routing, and no syntax to get wrong. */
    /* What a row can honestly say, and what its button will do. "Signed in" is not "the folder
       exists" — that only means a window was once opened — so it comes from the server, which looks
       for the cookie the site sets when you really log in. Until then the row says what to do next
       rather than guessing at what happened. Three things can be true: nothing was ever opened, a
       login is saved, or a login is pending — and for the last of those, whether the window is still
       up is the only other thing the user needs, because closing it is what saves the login. Whether
       the app can *confirm* that site's login changes the explanation, not the instruction. */
    const view = pf => !pf || !pf.exists
      ? { btn: "Sign in", txt: "Not signed in yet",
          why: "Press Sign in to open this account's first site in its own window." }
      : pf.signed_in === true
        ? { btn: "Open window", txt: pf.up ? "Signed in — window is open" : "Signed in",
            why: "This account's logins are saved. The bots reuse this browser." }
        : pf.up
          ? { btn: "Open window", txt: "Window is open — sign in, then close it",
              why: pf.signed_in === null
                ? "This site leaves no sign-in cookie the app can read, so it will never confirm the login. Log in there and close the window — closing is what saves it."
                : "The login is written to disk when the window closes; the row then says Signed in." }
          : pf.signed_in === null
            ? { btn: "Sign in", txt: "Cannot confirm this site's login",
                why: "The app has no way to tell whether this site logged you in. Press Sign in, log in there, then close the window — closing is what saves the login." }
            : { btn: "Sign in again", txt: "Opened, but no sign-in was saved",
                why: "A window was opened but the site left no login behind. Press Sign in and log in again." };
    /* A profile's identity is the folder its cookies live in, and the server reports every account
       name that lands in the same one. Two rows sharing a folder share one browser, so the second
       must not be shown the first one's login — it is named as a duplicate instead. Matching on the
       folder is also what stops a row from claiming a login it never earned: a name nothing on disk
       answers to has no profile to inherit a state from, so it reads "Not signed in yet". */
    const statesOf = o => {
      const st = {}, owner = new Map();
      for (const pf of o.profiles || [])
        for (const n of (pf.names || [pf.name])) { st[n] = pf; owner.set(n, pf.id); }
      return { st, owner };
    };
    const clash = (other, same) => same
      ? { btn: "Sign in", txt: "Both rows are one browser",
          why: "Both rows are named “" + other + "”, and the name is what picks the browser — so they "
             + "share one, with one set of logins. Put both sites in one row, or rename one of them." }
      : { btn: "Sign in", txt: "Same browser as “" + other + "”",
          why: "The name is what picks the browser, and this name means the same browser as “" + other
             + "” — so this row cannot keep its own logins. Put both sites in one row, or give this "
             + "row a different name." };
    async function drawAccounts() {
      clearTimeout(drawTimer); drawTimer = null; quiet = 0;
      let o = {};
      try { o = await (await fetch("/api/browser/own")).json(); } catch (e) {}
      const { st, owner } = statesOf(o);
      const taken = new Map();     // folder id -> the first row that claimed it, so a second can say so
      baccrows.innerHTML = ""; rows = [];
      const h = el("div", "desc", "Accounts — one browser each, with its own saved logins. Name it, list the " +
        "sites the bots should use it for, then press Sign in: log in once in the window that opens, then " +
        "close the window — closing is what saves the login, and the row turns to Signed in. A site you do " +
        "not list is read anonymously, so your logins are never handed to a site that is not yours.");
      h.style.cssText = "margin-bottom:8px;max-width:640px";
      baccrows.appendChild(h);
      if (!accounts.length) {
        baccrows.appendChild(el("div", "desc", "No accounts yet — “Add account”, then “Sign in”."));
      }
      accounts.forEach((a, i) => {
        const row = el("div");
        row.style.cssText = "display:flex;gap:8px;align-items:center;margin-bottom:6px;flex-wrap:wrap";
        const nm = el("input"); nm.value = a.name; nm.placeholder = "Account name";
        nm.style.cssText = "width:140px";
        nm.title = "Renaming starts a fresh browser — the old name's saved logins stay in the old folder.";
        const sites = el("input"); sites.value = a.sites;
        sites.placeholder = "Sites the bots should use this account for — e.g. x.com";
        sites.title = "The bots use this account for these sites. Sign in opens the first one. A site you do not list here is read anonymously.";
        sites.style.cssText = "flex:1;min-width:220px";
        const si = el("button", "btn ghost sm", "Sign in");
        /* The same multiplication sign the panels' close buttons carry, not the U+2715 dingbat: this
           is the one glyph in app.js outside the SVG icon set, and the dingbat is what the "no emoji
           glyphs in the served script" check catches — a screen reader reads it aloud as "x". */
        const rm = el("button", "btn ghost sm", "\u00D7");
        rm.title = "Remove this row. Its saved logins stay on disk under the old name.";
        const info = el("span", "desc");
        /* Its own line under the row's controls. Inline, a long state ("Both rows are one browser")
           wrapped to the *next* row's line and read as that row's — the state has to belong to the
           row it is about, and a fixed place is what makes that true for every wording. */
        info.style.cssText = "flex:1 1 100%;margin:-2px 0 4px";
        /* Which profile this row is, as the folder: the server's id when it knows the name, else the
           name itself — so a row nothing answers to stays unclaimed and reads as brand new. */
        const key = owner.get(a.name) || a.name;
        const dup = taken.get(key) || "";
        if (key && !taken.has(key)) taken.set(key, a.name);
        rows.push({ name: a.name, dup, info, btn: si });
        const paint = pf => { const v = dup ? clash(dup, dup === a.name) : view(pf);
          si.textContent = v.btn; info.textContent = v.txt; info.title = v.why; };
        paint(st[a.name]);
        const commit = () => { a.name = nm.value.trim(); a.sites = sites.value.trim(); save(); drawAccounts(); };
        nm.onchange = commit; sites.onchange = commit;
        si.onclick = async () => {
          si.textContent = "Opening…"; si.disabled = true;
          /* The row's own sites go with it: two rows can name the same account, and then the account
             name alone cannot say which site this button was for — it would always answer with the
             first row's site. The row that was clicked is the one that knows. */
          const res = await jpost("/api/browser/own/open", { name: a.name || "default", sites: a.sites });
          si.disabled = false;
          bnote.textContent = res.ok ? (res.out || "opened") : ("Could not open — " + (res.err || "unknown"));
          bnote.title = res.ok ? "" : (res.err || "");
          drawAccounts();
        };
        rm.onclick = () => { accounts.splice(i, 1); save(); drawAccounts(); };
        row.append(nm, sites, si, rm, info); baccrows.appendChild(row);
      });
      if ((o.profiles || []).some(p => p.up)) drawTimer = setTimeout(refreshStates, 3000);
    }
    /* A sign-in happens in the other window, so nothing here would ever notice it. While an account's
       window is open, keep the states fresh — the row turns to Signed in on its own the moment the
       login lands, instead of leaving the user to guess whether it worked. Only the text is repainted,
       never the rows, so this cannot steal focus from someone typing a name or a site. Closing the last
       window does not stop it straight away: the browser writes its cookies out as it goes, and a
       tick that lands first would freeze the row on "sign in, then close it" for good. A few quiet
       ticks give that write time to land. */
    async function refreshStates() {
      if (bmode.value !== "profiles") return;             // left the card; the poll stops with it
      if (drawBusy) return; drawBusy = true;
      let o = {};
      try { o = await (await fetch("/api/browser/own")).json(); } catch (e) {}
      finally { drawBusy = false; }
      const { st } = statesOf(o);
      for (const r of rows) {
        const v = r.dup ? clash(r.dup, r.dup === r.name) : view(st[r.name]);
        r.info.textContent = v.txt; r.info.title = v.why;
        if (!r.btn.disabled) r.btn.textContent = v.btn;
      }
      if ((o.profiles || []).some(p => p.up)) { quiet = 0; drawTimer = setTimeout(refreshStates, 3000); }
      else if (++quiet < 3) drawTimer = setTimeout(refreshStates, 3000);
    }
    baddacc.onclick = async () => {
      accounts.push({ name: "", sites: "" }); await drawAccounts();
      baccrows.lastElementChild?.querySelector("input")?.focus();
    };
    btest.onclick = async () => {
      bnote.textContent = "Testing…"; bnote.title = "";
      await save();
      why(await jpost("/api/browser/restart", {}));
    };
    blaunch.onclick = async () => {
      bnote.textContent = "Launching ZenPilot…"; bnote.title = "";
      await save();
      why(await jpost("/api/browser/launch", {}));
    };
    bimp.onclick = () => importProfiles(hosts => {
      btarget.value = hosts;
      save();
      const n = hosts.split(",").length;
      bnote.textContent = "Imported " + n + " profile" + (n === 1 ? "" : "s") + ". The bots reuse them from now on.";
    });
    /* The warning is drawn from a real look at the disk, and it names the fix + where to get it. */
    try {
      zp = await (await fetch("/api/browser/profiles")).json();
      bzp.innerHTML = `<span class="zi">${svg("warn")}</span><div><b>ZenPilot is not installed on this machine.</b>
        <div class="zsub">Looked in Applications and did not find it. Get ZenPilot, open a profile and sign in,
        then press “Launch ZenPilot &amp; connect” — the bots reuse those logins, so nothing is logged in twice.</div>
        <a class="btn ghost sm" data-a="zp-get" href="${esc(zp.get_url || "")}" target="_blank" rel="noopener">Get ZenPilot</a></div>`;
      show(); setNote();
    } catch (e) { /* the profiles check is a nicety; never break the card over it */ }
  })();
}
/* --- Phone & tablet: the LAN listener the Android app talks to --- */
function tabPhone(p) {
  h3(p, "Phone", "Reach this app from your phone — on your wifi, or from anywhere.");
  /* --- Phone & tablet: the LAN listener the Android app talks to --- */
  const pc = el("div", "card");
  pc.innerHTML = `<div class="ct"><span class="ico">${svg("phone")}</span><div><b>Phone &amp; tablet</b>
    <div class="sub">Let the Anzen-bot app on your wifi reach this machine. Off by default, and while it
    is off nothing outside this computer can talk to the API at all. Turning it on is what the phone
    needs; it is guarded by a token, so only a device you have set up can use it.</div></div></div>`;
  const pNote = el("div", "desc", "Checking…");
  const pBox = el("div"); pBox.style.display = "none"; pBox.style.marginTop = "10px";
  const pUrl = el("input"); pUrl.readOnly = true;
  const pTok = el("input"); pTok.readOnly = true; pTok.style.marginTop = "8px";
  const pRow = el("div", "row"); pRow.style.marginTop = "10px";
  const pCopy = el("button", "btn ghost sm", "Copy the link for the phone");
  pRow.appendChild(pCopy);
  const pSteps = el("div", "desc", "In the Android app, paste that address into “Server address” and the "
    + "token into “Access token” — or paste the whole link into the address box, which takes the token out "
    + "for you. Both stay on your own network.");
  pSteps.style.marginTop = "8px";
  const pPerm = el("div", "desc", "The first time you turn this on, macOS or Windows may ask whether the app "
    + "may accept incoming connections — say yes, or the phone cannot get through. Nothing on the network can "
    + "use the API without the token either way.");
  pPerm.style.marginTop = "8px";
  pBox.append(pUrl, pTok, pRow, pSteps, pPerm);
  let pToggle = null;
  const drawLan = st => {
    if (pToggle) pToggle.classList.toggle("on", !!st.enabled);
    pBox.style.display = st.enabled ? "" : "none";
    if (st.enabled) { pUrl.value = st.url; pTok.value = st.token; }
    pNote.textContent = st.enabled
      ? "Reachable on this network. Only a device holding the token can use it."
      : "Only this computer can reach the API.";
  };
  /* The listener moves address when the switch flips, and for that moment there is nothing to answer on
     the old one — so the state is read back with a few tries rather than once. */
  const readLan = async () => {
    for (let i = 0; i < 20; i++) {
      try { return await (await fetch("/api/lan")).json(); }
      catch (e) { await new Promise(r => setTimeout(r, 250)); }
    }
  };
  pToggle = toggle(pc, "Allow devices on this network",
    "The phone app needs this on. It opens the API to your wifi behind a token — leave it off if you do not use a phone.",
    async v => {
      pNote.textContent = "Switching…";
      const r = await jpost("/api/lan", { on: v });
      if (!r.ok) { pNote.textContent = "Could not change it: " + (r.error || "unknown"); return; }
      drawLan(await readLan() || r);
    }, false);
  pc.append(pNote, pBox);
  p.appendChild(pc);
  pCopy.onclick = async () => {
    const text = pUrl.value + "?t=" + pTok.value;
    try { await navigator.clipboard.writeText(text); pCopy.textContent = "Copied"; }
    catch (e) { pUrl.select(); pCopy.textContent = "Select and copy"; }
    setTimeout(() => { pCopy.textContent = "Copy the link for the phone"; }, 1600);
  };
  (async () => { const st = await readLan(); if (st) drawLan(st); else pNote.textContent = ""; })();

  /* --- From anywhere: the link out to a relay, so your wifi is not the only way in --- */
  const rc = el("div", "card");
  rc.innerHTML = `<div class="ct"><span class="ico">${svg("globe")}</span><div><b>From anywhere</b>
    <div class="sub">The switch above only reaches the phone on your own wifi. With a relay the phone
    works on any network — cellular, a hotel, a café — because this app and the phone both dial out to
    the relay and it joins the two together. Nothing is opened on this computer and no router is
    touched, which is the same way ZCode reaches its app.</div></div></div>`;
  const rNote = el("div", "desc", "Checking…");
  const rBox = el("div"); rBox.style.marginTop = "10px";
  const rUrlLbl = el("div", "desc", "Where your relay answers. It is also the address the phone is given.");
  const rUrl = el("input"); rUrl.placeholder = "https://anzen.example.com";
  rUrl.style.marginTop = "6px";
  const rSecLbl = el("div", "desc", "Start the relay with this secret — it is what stops a stranger "
    + "registering as this computer. On the host: <code>anzen_relay.py relay --port 7788 --secret …</code>");
  rSecLbl.style.marginTop = "10px";
  const rSec = el("input"); rSec.readOnly = true; rSec.style.marginTop = "6px";
  const rPhoneLbl = el("div", "desc", "What the phone is set up with — the address above, signed in once.");
  rPhoneLbl.style.marginTop = "10px";
  const rPhone = el("input"); rPhone.readOnly = true; rPhone.style.marginTop = "6px";
  const rRow = el("div", "row"); rRow.style.marginTop = "10px";
  const rCopySec = el("button", "btn ghost sm", "Copy the secret");
  const rCopyPhone = el("button", "btn ghost sm", "Copy the link for the phone");
  rRow.append(rCopySec, rCopyPhone);
  rBox.append(rUrlLbl, rUrl, rSecLbl, rSec, rPhoneLbl, rPhone, rRow);
  let rToggle = null;
  const drawRelay = st => {
    if (rToggle) rToggle.classList.toggle("on", !!st.on);
    if (document.activeElement !== rUrl) rUrl.value = st.url || "";
    rSec.value = st.secret || "";
    rPhone.value = st.phone && st.token ? st.phone + "?t=" + st.token : "";
    rNote.textContent = !st.on
      ? "Off — the phone can only reach this app on your own wifi."
      : (st.up ? "Connected. The phone can reach this app from any network."
               : "Not connected" + (st.note ? " — " + st.note : "."));
  };
  rToggle = toggle(rc, "Reach this app from anywhere",
    "The phone then works on any network, not just your wifi. This app dials out to the relay you name "
    + "below; nothing is opened on this machine.",
    async v => {
      rNote.textContent = "Switching…";
      drawRelay(await jpost("/api/relay", { on: v, url: rUrl.value.trim() }));
    }, false);
  rUrl.onchange = async () => { drawRelay(await jpost("/api/relay", { url: rUrl.value.trim() })); };
  rc.append(rNote, rBox);
  p.appendChild(rc);
  rCopySec.onclick = () => copyText(rSec.value, rCopySec);
  rCopyPhone.onclick = () => copyText(rPhone.value, rCopyPhone);
  (async () => {
    try { drawRelay(await (await fetch("/api/relay")).json()); }
    catch (e) { rNote.textContent = ""; }
  })();
}
/* --- Approvals --- */
function tabApprovals(p) {
  h3(p, "Approvals", "What a bot may do without asking. Set a room's level from the Approval chip in the header, or a bot's own in Bots → Approval level. The Help tab explains the whole flow.");
  const box = el("div", "bento"); p.appendChild(box);
  for (const [v, t, s, detail] of APPROVALS) { const d = el("div", "card");
    d.innerHTML = `<div class="ct"><div><b>${esc(t)}</b><div class="sub">${esc(s)}</div></div></div>`
      + `<div class="desc" style="margin-top:8px;line-height:1.6">${esc(detail)}</div>`;
    box.appendChild(d); }
}
/* --- Help --- */
/* The tour, and the reference. Every list below is built from the constant the app itself runs on
   — APPROVALS for the levels, S.tools for the tool catalogue, S.skills for the skills — so a
   feature cannot be added and left undescribed, and these words cannot drift from the behaviour.
   Only the "why" is written by hand. */
function tabHelp(p) {
  h3(p, "Help", "What every part of Anzen-bot does, and what each setting changes. Read straight through for the tour, or jump to a section.");
  const wrap = el("div", "help"); p.appendChild(wrap);
  const SEC = [];                                   // the jump list, filled as sections are added
  const sec = (id, title) => { const s = el("section", "hsec"); s.id = "help-" + id;
    s.appendChild(el("h4", "", esc(title))); wrap.appendChild(s); SEC.push([id, title]); return s; };
  const para = (s, html, dim) => s.appendChild(el("p", dim ? "dim" : "", html));
  const list = (s, items, ordered) => { const l = el(ordered ? "ol" : "ul");
    for (const it of items) l.appendChild(el("li", "", it)); s.appendChild(l); return l; };
  /* A feature row: an icon, a name, and what it does. `desc` is HTML, so callers escape text. */
  const feat = (s, ico, name, desc) => { const d = el("div", "feat");
    d.innerHTML = `<span class="ico">${svg(ico)}</span><div><b>${esc(name)}</b><div class="d">${desc}</div></div>`;
    s.appendChild(d); return d; };

  /* ---- the idea ---- */
  let s = sec("idea", "The idea");
  para(s, "Anzen-bot is a chat app you host yourself. You give a team of bots a goal in plain words, and they answer, use real tools, and hand back a report. Nothing here is a mock: a bot runs a shell, reads and writes files, drives a real browser, and calls the apps you connect.");
  para(s, "Three things make up the app:");
  list(s, [
    "<b>A bot</b> — one teammate. It has its own model, approval level, memory, skills, tools, colour and face.",
    "<b>A room</b> — a team of bots with its own transcript, its own repo folder and its own rule for who answers.",
    "<b>A chat</b> — a transcript. Every bot and every room keeps its own; the same bot in two rooms is two separate conversations.",
  ]);
  para(s, "Everything runs on your machine. Your API key and every app token are stored server-side and never shown again.", "dim");

  /* ---- talking to a bot ---- */
  s = sec("talking", "Talking to a bot");
  list(s, [
    "Type in the box at the bottom and press <kbd>Enter</kbd> to send. <kbd>Shift</kbd>+<kbd>Enter</kbd> adds a new line.",
    "In a room, type <code>@</code> to name a teammate — the list is that room's members — so a message can be aimed at one bot.",
    "You can switch to another chat while a turn is running: the running turn keeps drawing into its own transcript, and the header, the dock and the send box follow the chat you are looking at.",
    "A turn ends with a report from each bot that worked. A delegation shows as “▸ Name started” and its report lands back in the parent bot's turn.",
  ]);
  para(s, "Who answers in a room is the room's <b>Responder</b> rule (see Rooms): the lead bot, an auto-picked bot, or everyone.", "dim");
  para(s, "A turn that fails says so in the transcript in plain words: whether the server could not be reached and the turn never started, or the connection dropped part-way through and the bot may still be working, or the bot hit an error of its own. The browser's own wording for a dropped connection is never shown.", "dim");

  /* ---- quote and forward ---- */
  s = sec("quote", "Quoting and forwarding");
  para(s, "Every message carries two small buttons — <b>Reply</b> and <b>Forward</b> — on hover on a desktop, and always visible inside the bubble on a touch screen.");
  list(s, [
    "<b>Reply</b> quotes that message. The quote waits above the composer until you send, then travels with your task and is drawn over it in the transcript. The bot is told what you are replying to, because it never sees the transcript — so “make it shorter” points at the message you meant. Sending clears the quote; <b>×</b> cancels it.",
    "<b>Forward</b> sends a copy of the message to another chat: a picker lists your rooms and your chats, and the copy arrives there marked <i>Forwarded</i> and is picked up as a task, exactly as if you had typed it.",
  ]);
  para(s, "Both marks are kept with the message, so reopening a chat draws the quote and the forward mark back where they were.", "dim");

  /* ---- queue and steering ---- */
  s = sec("queue", "Queued tasks and steering");
  para(s, "Chats work independently: each chat runs its own turn, and a task in one never waits on another. You never have to wait for a turn to finish before typing the next thing — a task sent into a chat whose <i>own</i> turn is already running is <b>held in a queue</b> above the composer, and the send box stays open.");
  list(s, [
    "<b>Leave it alone</b> and it runs by itself the moment that chat's running turn ends — in the chat you queued it in, whether or not that chat is on screen.",
    "<b>Steer now</b> hands it to the turn that is already running instead, so the bot changes direction mid-task rather than finishing and starting over. The task is delivered at the bot's next step — after the command it is running now, not in the middle of it.",
    "<b>×</b> takes it out of the queue. Nothing was sent, so nothing is undone.",
  ]);
  para(s, "A steered task is kept in the transcript like any message you type, so the record shows what turned the bot. Queueing and steering are per chat: a task queued in one chat never waits on, or steers into, another chat's turn.", "dim");

  /* ---- header chips ---- */
  s = sec("header", "The chips in the header");
  feat(s, "models", "Model chip", "The model that answers <i>this</i> chat. Click it to switch — the list filters as you type, and “Each bot's own model” clears your pick so the bot's configured model answers again. Changing it here never touches Settings.");
  feat(s, "approvals", "Approval chip", "What this chat may do without asking. Click it to change the level on the spot. In a room the chip names the room's one level, and picking a level there sets it for the whole room — every member runs at it.");
  feat(s, "models", "Context chip", "How full this chat's context window is. Hover or click it for the breakdown: which pieces of the prompt — system prompt, memory, skills, transcript, tool output — took which share, plus the average cache hit rate.");
  feat(s, "monitor", "Computer button", "Opens the Computer panel: a live screenshot of the bot's real headless browser, plus a box to point it at a page. Refresh keeps it current.");

  /* ---- approvals ---- */
  s = sec("approvals", "Approvals — what each level lets a bot do");
  para(s, "An approval level answers one question: <b>which of a bot's actions stop and wait for you, and which just run?</b> These are the levels, and exactly what each one reaches:");
  for (const [v, t, one, detail] of APPROVALS) {
    const d = el("div", "lvl");
    d.innerHTML = `<div class="hd"><b>${esc(t)}</b><span class="tag">${esc(v)}</span></div>`
      + `<div class="one">${esc(one)}</div><div class="acc">${esc(detail)}</div>`;
    s.appendChild(d);
  }
  para(s, "Where the level comes from");
  list(s, [
    "In a room, <b>the room's level is the only level</b>. A room is one team with one rule, so picking a level on the room sets what every member does — a member's own default is neither used nor shown there. Set a bot's own level where the bot is, in Bots → Edit.",
    "In a chat with one bot, <b>the chat's own level governs</b>. Set it from the Approval chip in the header.",
    "If that chat has no level of its own, <b>the bot's own default</b> applies (Bots → Edit → Approval level).",
    "<b>Full access is a grant made on the bot itself.</b> In a one-to-one chat, no chat level can quietly take it away — so the Bots list and the chat never disagree.",
    "A fresh bot starts at <b>Ask for approval</b>, and so does a room with no level of its own.",
  ], true);
  para(s, "The approval card");
  para(s, "When a level does stop to ask, a card appears in the chat with the exact command and <b>Allow</b> / <b>Deny</b> buttons. The bot waits — the dock wears “needs your approval” and the header says so. <b>Allow</b> runs that one command and the turn continues. <b>Deny</b> tells the bot it was blocked and that it may not run another command this turn; it finishes and explains. A card left unanswered waits up to 15 minutes.");
  para(s, "Only <b>risky shell commands</b> raise a card today. A command is safe when it is one plain read-only command — <code>ls</code>, <code>cat</code>, <code>git status</code>, <code>find</code> and the like — with no shell characters (<code>; &amp; | &gt; $ `</code>). Anything else asks. So <b>Plan only</b> and <b>Full access</b> are the two levels that really change what runs; Ask, Auto-accept and Approve routine behave the same way for now.", "dim");
  para(s, "Plan only → approve → run");
  para(s, "A plan-only turn can only look, never touch. It ends by writing a numbered plan and stopping. The plan card has one button, <b>Approve plan and run it</b>: it switches this chat to Full access and hands the plan back as the instruction, so the bot executes exactly what it proposed. Ignore the card and nothing runs.");

  /* ---- tools ---- */
  s = sec("tools", "The tools a bot can use");
  para(s, "These are the built-in tools. A bot has them all by default; in Bots → Edit → Tools you can hand it a smaller set, which helps a small-context model stay on task.");
  for (const t of (S.tools || [])) feat(s, "settings", t.name, esc(t.desc || ""));
  if ((S.connectorTools || []).length) {
    para(s, "From your connected apps:", "dim");
    for (const c of S.connectorTools) feat(s, "apps", c.tool, "Call " + esc(c.name) + " — see Connected apps below.");
  }
  para(s, "Every MCP server you add under Plugins contributes its own tools too, named after the server (for example <code>filesystem__read</code>).", "dim");

  /* ---- bots ---- */
  s = sec("bots", "Bots");
  para(s, "Bots → Edit is where a bot is defined. The editor has five parts:");
  list(s, [
    "<b>Identity</b> — name, optional emoji, title, a one-line role, and the colour that paints its avatar.",
    "<b>Look</b> — the face shape: each bot gets its own shape, ears and idle motion, and the preview shows exactly how it will sit in the sidebar.",
    "<b>Outfit and accessory</b> — what it wears: a scarf, a tie, a hat, glasses. The outfit is clipped to its body; the accessory is anchored to its own eye row, so both sit right on every shape.",
    "<b>Face picture</b> — introduce an image and the image model redraws it as this bot's face, in place of the drawn eyes and mouth. It keeps blinking, looking around and showing its mood, and the body, outfit, accessory and colour are drawn around it.",
    "<b>Brain</b> — the model, the approval level, a switch for memory, and the standing instructions (the bot's system prompt).",
    "<b>Skills</b> — tick the skills this bot should lean on.",
    "<b>Tools</b> — all current tools, or a custom selection.",
  ]);
  para(s, "The Bots list shows one card per bot with its title, model, approval and memory, so a team of twenty is scanned rather than read. <b>New bot</b> adds one; <b>Import a team</b> builds a whole roster from a BotMRR playbook, or just a pasted list of names and positions.");
  para(s, "Right-click a bot in the sidebar (or use its ⋯) for pin, hide, duplicate, clear chat and delete. Pin floats it to the top; hide takes it out of the sidebar without deleting it. A room's own menu carries pin too — and no hide, since hiding a room would take its bots' chats with it; Delete is the honest way to do that.");

  /* ---- channels ---- */
  s = sec("channels", "Rooms");
  para(s, "Settings → Rooms creates one, and Edit sets:");
  list(s, [
    "<b>Responder</b> — who answers an un-mentioned message: <i>Lead bot answers</i>, <i>Auto</i> (a fast model picks the right bot), or <i>Everyone answers</i>.",
    "<b>Lead</b> — the bot that answers when the rule is “Lead bot”, and the face of the room in the header.",
    "<b>Members</b> — which bots are in the room.",
    "<b>Shared instructions</b> — extra guidance every member gets.",
    "<b>Repo folder</b> — the one repo the room's bots work in. Browse to it, or paste a path. Blank means a shared folder.",
    "<b>Logo</b> — upload one, or let it use a logo found in the repo, or fall back to the initials.",
  ]);
  para(s, "A bot runs its shell and file tools inside the room's repo only, so two repos never mix. A room is a <i>conversation</i>: what each bot <i>says</i> — the delegation and the task handed over, the acknowledgement, the answer to a steer, the report — stays in the room's transcript, so the channel reads as the discussion and not as you talking to silence. The <i>steps</i> are a bot's own: the shell commands, file dumps, screenshots and running commentary land in that bot's chat inside the room (<b><i>room</i>/<i>bot</i></b> in the sidebar, made the first time it works there): open it to watch the commands it runs and what they print, live while it works and kept afterwards. A lead hands work only to the members you added to the room — a bot outside it is refused and the room is told — so add a bot to the team before expecting it to be asked. The same detail is also written to each bot's own work log (see Memory).");
  para(s, "Right-click a room for Edit, Clear chat and Delete. The caret folds the team shut; double-clicking the row toggles it too.", "dim");

  /* ---- the AI side ---- */
  s = sec("models", "AI model");
  feat(s, "router", "Connection", "The [OI]-compatible endpoint every bot talks to: paste your router URL, API key, a default model, and optionally a vision model for browser_see. The key is stored server-side and never shown again. “Test connection” checks the router, and “Detect all models” pulls the model list.");
  feat(s, "models", "Models", "Every model the API key can reach. Detect them all, add one by hand, or remove ones you do not want. Any bot can use any model in this list.");
  feat(s, "models", "Context", "Every model has a maximum context window. Set a <b>context limit</b> to cap a request yourself (0 follows the model's own window), and leave <b>Compress when it runs out</b> on so a long turn drops its oldest steps and still answers instead of erroring.");
  feat(s, "models", "Image generation", "Which model draws pictures when a bot uses the draw-image tool. Image-capable models are listed automatically.");

  /* ---- the browser ---- */
  s = sec("browser", "Browser");
  feat(s, "monitor", "Browser", "Where the bots browse. <i>Own browser</i> runs a fresh browser each time — fast, but logged out. <i>Own browser — saved profiles</i> keeps one browser per account with its logins saved to disk: add an account, type the sites it should be used for, then click <b>Sign in</b> — it opens the first of those sites in that account's own window, and you log in once there and then <b>close the window</b> (closing is what saves the login). Every later run is already signed in, and only the sites you listed ever see that account's cookies; anything else is read anonymously. <b>Browser</b> is which browser those windows are: <i>Automatic</i> uses a Chrome really installed on this Mac, and that matters — Google refuses to sign anyone in on the Chromium we ship (“This browser or app may not be secure”), but signs in normally on a real Chrome, so leave it on Automatic unless you have a reason not to. <i>ZenPilot / any browser over CDP</i> reuses the profiles you are already signed into — give it the debug port and the button launches ZenPilot on the same port. <b>Import profiles</b> lists the profiles open in ZenPilot so you can tick the ones to reuse.");

  /* ---- memory ---- */
  s = sec("memory", "Memory");
  para(s, "Each bot keeps plain markdown notes, and they load into every turn so it starts each session knowing what this project is about.");
  list(s, [
    "<b>memory.md</b> — editable here. Only the first 200 lines load each turn; the bot also appends its own lessons after it uses tools.",
    "<b>Work log</b> — what the bot actually did, turn by turn, in its own folder. Newest turns are at the bottom, and the file is bounded so the oldest roll off.",
    "<b>Self-learning</b> — after real work the bot reflects once on its own run and writes a few durable lessons (paths, working commands, gotchas) back to its memory, so the next session is smarter without being told.",
  ]);
  para(s, "Turn memory off on a bot in Bots → Edit if you want it stateless.", "dim");

  /* ---- skills ---- */
  s = sec("skills", "Skills");
  para(s, "A skill is a reusable capability you switch on per bot. Switching one on puts an <i>index line</i> in that bot's prompt, not the whole briefing — the bot reads the guidance with <code>use_skill</code> when it decides the skill covers the job. The built-ins ship real guidance, not just a name (Web browsing is the recipe for driving a site in few steps; Research is how to answer with sources and evidence):");
  for (const sk of (S.skills || []).filter(x => x.builtin !== false))
    feat(s, "skills", sk.name, esc(sk.desc || ""));
  para(s, "You can also install skills from a zip: a skill is a folder with a <code>SKILL.md</code> inside, and one zip may hold several — you choose which to install after uploading. Filter the list by name, or by <i>recently installed</i>, <i>built-in</i> and <i>on for this bot</i>. An installed skill can be removed again.");

  /* ---- plugins ---- */
  s = sec("plugins", "Plugins — MCP servers");
  para(s, "A plugin is a real <b>MCP server</b>. Add one by the command that starts it (a local server, spoken to over a pipe) or by its URL (a remote one); the tools it offers become your bots' tools, named after the server so two servers can both have an <code>echo</code>. Environment values and headers are stored but never shown again, like every other credential. <b>Test</b> connects it and reports the tool count, or the reason it would not come up. Switch a server off without removing it.");
  para(s, "MCP tools are added on top of a bot's own tools, for every bot — they are not filtered by a bot's tool selection.", "dim");

  /* ---- connected apps ---- */
  s = sec("apps", "Connected apps");
  para(s, "Connect an app once and every bot gains a real tool that calls its API. Most take a token you paste; the Google ones (Gmail, Drive, Calendar) take an OAuth client id, client secret and a refresh token, because a Google access token dies within the hour and a pasted one would work only until lunchtime. <b>Test</b> makes a real call. <b>Disconnect</b> revokes it.");
  para(s, "The apps: Gmail, Slack, GitHub, Notion, Linear, Google Drive, Google Calendar, and Webhooks (POST JSON to any HTTPS URL — Zapier, n8n, IFTTT or your own endpoint, with an optional shared secret).");

  /* ---- voice and sound ---- */
  s = sec("voice", "Voice and sound");
  feat(s, "voice", "Read replies aloud", "Show a listen button on longer replies, or read every finished reply automatically (General). Pick one of the voices your browser already has — nothing is sent to a server. Test it here.");
  feat(s, "sound", "Notification sounds", "A short chime when a turn finishes, fails, or stops to ask you something, so you can hear it from another window. Each of the three has its own cue; drag the volume slider and let go to hear it at the level you chose. Sound stays silent until you click or type once — browsers do not allow it before that.");

  /* ---- appearance ---- */
  s = sec("appearance", "Appearance");
  list(s, [
    "<b>Theme</b> — a whole look: surfaces, accent and type. Picking one adopts its signature accent; the colour field below takes it back.",
    "<b>Accent</b> — the one colour that marks the primary action, the chat you are in, and the live dot. It previews live; click Save to keep it.",
    "<b>Density</b> — comfortable or compact spacing.",
    "<b>Font</b> — the typeface for the whole interface. Each one ships with your system, so nothing is downloaded.",
    "<b>Font size</b> — the base text size. Everything else is this times its own designed value, so the whole interface grows with it.",
  ]);

  /* ---- general ---- */
  s = sec("general", "General");
  list(s, [
    "<b>Workspace name</b> — shown in the sidebar.",
    "<b>Your name</b> — how your own messages are labelled in every transcript; defaults to “Client”.",
    "<b>Read replies aloud automatically</b> — speak every finished reply with the chosen voice.",
    "<b>Auto-route room messages</b> — let a fast model pick which bot answers an un-mentioned room message.",
    "<b>Notification sounds</b> — the chime switch and volume (see Voice and sound).",
  ]);

  /* ---- sidebar and dock ---- */
  s = sec("chrome", "The sidebar and the dock");
  para(s, "The sidebar lists your chats, your rooms and your loose bots. Click a row to open its chat, click the caret to fold a team, and right-click (or the ⋯) for pin, hide, duplicate, clear and delete. The rail button collapses the sidebar to a strip of faces.");
  para(s, "Click the <b>CHATS</b> heading to fold the recent-chat list away and give the rooms and bots the room — the heading stays as the control that brings it back, and the choice is remembered.");
  para(s, "To put the sidebar in your own order, <b>hold a row and drag it</b>: a room (its team comes with it), a loose bot, or a bot inside a room. The order you drop into is saved on the server, so the phone shows what the window arranged. <b>Pin</b> from a room's menu floats it to the top, above everything else, and unpinning puts it back where you left it.");
  para(s, "The corner face is the dock: it wears the face of whoever you are talking to and shows what it is doing — idle, working at the desk, thinking, searching, needs your approval, done, error. Poke it for fun. The header dot goes live while a turn is running.");

  /* ---- keyboard ---- */
  s = sec("keys", "Keyboard and gestures");
  const krow = (k, d) => s.appendChild(el("div", "kbdrow", `<span>${k}</span><span>${d}</span>`));
  krow("<kbd>Enter</kbd>", "Send the message");
  krow("<kbd>Shift</kbd>+<kbd>Enter</kbd>", "New line");
  krow("<kbd>@</kbd> in a room", "Open the teammate list; <kbd>↑</kbd>/<kbd>↓</kbd> to choose, <kbd>Enter</kbd> to insert");
  krow("<kbd>Esc</kbd>", "Close a dialog, menu or the settings panel");
  krow("<kbd>Tab</kbd>", "Reach every control, including the ones built from cards and rows");

  /* ---- install ---- */
  s = sec("install", "Install as an app");
  para(s, "Anzen-bot is a progressive web app. When your browser offers it, an <b>Install app</b> button appears above Settings in the sidebar — install it and it opens in its own window like a native app, offline shell included.");

  s = sec("phone", "Phone and tablet");
  para(s, "There are desktop builds — a <b>.dmg</b> on macOS, an <b>.exe</b> on Windows, a binary on Linux — and an Android app, all in the project's <b>desktop/</b> and <b>android/</b> folders. The desktop build runs the same server on your own machine and shows it in the operating system's own window; nothing is sent anywhere.");
  list(s, [
    "To use the phone, open <b>Settings → Phone</b> and turn on <b>Allow devices on this network</b>. That opens the API to your wifi, so it is off until you ask for it.",
    "Then press <b>Copy the link for the phone</b> and paste it into the Android app's address box. The link carries a token; the app lifts it out, keeps it, and signs itself in.",
    "The first time the switch goes on, the operating system may ask whether the app may accept incoming connections. On macOS an unsigned build is refused silently if you do not say yes — the phone then just times out — so allow it when it asks.",
    "The token is the only thing standing between your wifi and an API that can run commands, so it is minted once and never shown to anyone who has not already got in. It lives in the app's data folder as <b>access_token</b>. Turning the switch off closes the door again.",
    "That switch only reaches the phone on your own wifi. To use it anywhere, run the relay that ships in <b>relay/anzen_relay.py</b> on a machine with a public address, then fill in the <b>From anywhere</b> card in that same tab. This app and the phone both dial out to the relay and it joins the two, so nothing here is exposed and no router is touched — the same way ZCode reaches its app.",
  ]);
  para(s, "A device that was set up once keeps working: the token does not rotate on its own, and the app remembers the address.", "dim");

  /* the jump list, built last so it names every section that exists */
  const toc = el("div", "toc");
  for (const [id, title] of SEC) {
    const a = el("button", "", esc(title)); a.type = "button";
    a.onclick = () => { const n = document.getElementById("help-" + id); if (n) n.scrollIntoView({ block: "start", behavior: "smooth" }); };
    toc.appendChild(a);
  }
  wrap.insertBefore(toc, wrap.firstChild);
}
/* --- Memory --- */
function tabMemory(p) {
  h3(p, "Memory", "Each bot keeps plain markdown notes that load into its turns, and it writes its own lessons after real work.");
  const sel = el("select");
  for (const b of S.bots) { const o = new Option(b.name, b.id); if (b.id === curEdit) o.selected = true; sel.appendChild(o); }
  const ta = el("textarea"); ta.style.minHeight = "220px";
  const load = async () => { const d = await get("/api/memory?bot=" + encodeURIComponent(sel.value)); ta.value = (d || {}).text || ""; };
  fld(p, "BOT", sel);
  fld(p, "MEMORY.MD", ta, "Only the first 200 lines load each turn. The bot appends its own lessons here after using tools.");
  const row = el("div", "row");
  const save = el("button", "btn pri", "Save"); save.onclick = async () => { await post("/api/memory", { bot: sel.value, text: ta.value }); save.textContent = "Saved"; setTimeout(() => save.textContent = "Save", 1200); };
  row.appendChild(save); p.appendChild(row);
  load();

  /* Every bot keeps its own log of the work it did — direct or delegated — in its own folder.
     The room only ever gets the report, so this is where the detail lives. */
  const lc = el("div", "card");
  lc.innerHTML = `<div class="ct"><span class="ico">${svg("memory")}</span><div><b>Work log</b>
    <div class="sub">What this bot actually did, turn by turn, in its own folder. A room's transcript keeps what it said; this is everything it ran.</div></div></div>`;
  const lsel = el("select");
  for (const b of S.bots) lsel.appendChild(new Option(b.name, b.id));
  lsel.value = sel.value;
  const lta = el("textarea"); lta.readOnly = true; lta.style.minHeight = "200px";
  const lload = async () => {
    const d = await get("/api/bot/log?bot=" + encodeURIComponent(lsel.value));
    lta.value = (d || {}).text || "(nothing logged yet — this bot has not finished a turn)";
  };
  lsel.onchange = lload;
  fld(lc, "BOT", lsel);
  fld(lc, "LOG", lta, "Newest turns are at the bottom. The file is bounded, so the oldest turns roll off.");
  p.appendChild(lc); lload();
  sel.onchange = () => { load(); lsel.value = sel.value; lload(); };
}
/* --- Skills --- */
function tabSkills(p) {
  h3(p, "Skills", "Reusable capabilities you switch on per bot. Switching one on adds an index line to the prompt; the bot reads the guidance with use_skill when the job calls for it.");
  const sel = el("select");
  for (const b of S.bots) { const o = new Option(b.name, b.id); if (b.id === curEdit) o.selected = true; sel.appendChild(o); }

  /* Install from a zip. One zip holds one folder per skill and may hold several, so the upload is
     scanned first and nothing is written until you have seen what is inside: untick what you do not
     want, or take the lot. */
  const zfile = el("input"); zfile.type = "file"; zfile.accept = ".zip,application/zip"; zfile.style.display = "none";
  const zbtn = el("button", "btn ghost sm", "Install from zip");
  const znote = el("div", "desc", "A skill is a folder with a SKILL.md inside it. A zip can hold several of them — you choose which to install after uploading.");
  const zpick = el("div", "zpick"); zpick.style.display = "none";
  const hidePick = () => { zpick.style.display = "none"; zpick.innerHTML = ""; };   // no stale entries left behind
  zbtn.onclick = () => zfile.click();
  zfile.onchange = async () => {
    const f = zfile.files[0]; if (!f) return;
    zbtn.disabled = true; zbtn.textContent = "Reading…"; znote.textContent = ""; hidePick();
    /* The button comes back in `finally`, whatever happens: a request that fails — a big zip the
       server refuses, a dropped connection — used to leave it reading for ever with no message,
       because the rejected await escaped and the label was never restored. */
    try {
      const data = await new Promise((res, rej) => {
        const fr = new FileReader();
        fr.onload = () => res(fr.result);
        fr.onerror = () => rej(new Error("could not read that file"));
        fr.readAsDataURL(f);
      });
      const r = await jpost("/api/skills/scan", { name: f.name, data });
      if (!r.ok) { znote.textContent = "Could not upload that zip: " + (r.error || "the server could not read it"); return; }
      showPick(f.name, data, r.found);
    } catch (e) {
      znote.textContent = "Could not upload that zip: " + (isOffline(e) ? "the connection to the server dropped." : (e && e.message ? e.message : e));
    } finally {
      zbtn.disabled = false; zbtn.textContent = "Install from zip"; zfile.value = "";
    }
  };
  const showPick = (name, data, found) => {
    const picked = new Set(found.map(s => s.id));
    const head = el("div", "desc", `<b>${esc(name)}</b> holds ${found.length} skill${found.length === 1 ? "" : "s"}. Untick any you do not want.`);
    const row = el("div", "row"); row.style.marginTop = "10px";
    const some = el("button", "btn pri sm", ""); some.type = "button";
    const all = el("button", "btn ghost sm", "Install all " + found.length); all.type = "button";
    const cancel = el("button", "btn ghost sm", "Cancel"); cancel.type = "button";
    const counts = () => { some.textContent = "Install selected (" + picked.size + ")"; some.disabled = picked.size === 0; };
    const go = async ids => {
      some.disabled = all.disabled = true;
      let r;
      try { r = await jpost("/api/skills/install", { name, data, ids }); }
      catch (e) {                                              // same trap as the upload: never strand the panel
        some.disabled = all.disabled = false;
        znote.textContent = "Could not install that zip: " + (isOffline(e) ? "the connection to the server dropped." : (e && e.message ? e.message : e));
        return;
      }
      hidePick();
      if (!r.ok) { znote.textContent = "Could not install that zip: " + (r.error || "the server refused it"); return; }
      S.skills = r.skills; draw();
      znote.textContent = "Installed " + r.installed.length + ": " + r.installed.map(s => s.name).join(", ")
        + (r.errors.length ? "  (" + r.errors.length + " skipped: " + r.errors[0] + ")" : "");
    };
    all.onclick = () => go(found.map(s => s.id));
    some.onclick = () => go([...picked]);
    cancel.onclick = () => { hidePick(); znote.textContent = "Nothing installed."; };
    zpick.innerHTML = ""; zpick.style.display = ""; zpick.append(head);
    for (const s of found) {
      const d = skBox(`<span class="ck"></span><span><span class="hd"><b>${esc(s.name)}</b>`
        + (s.replaces ? `<i class="tag">replaces installed</i>` : "")
        + `</span><span>${esc(s.desc || "no description in its SKILL.md")}</span>`
        + `<span class="n">${s.files} file${s.files === 1 ? "" : "s"}</span></span>`, true,
        nv => { nv ? picked.add(s.id) : picked.delete(s.id); counts(); });
      zpick.appendChild(d);
    }
    counts(); row.append(some, all, cancel); zpick.appendChild(row);
  };

  /* Filter: with a zip install you quickly accumulate skills, so you need to find one. */
  const q = el("input"); q.type = "text"; q.placeholder = "Search skills by name or description…";
  const filt = el("select");
  for (const [v, t] of [["all", "All skills"], ["recent", "Recently installed"], ["installed", "Installed from zip"],
                        ["builtin", "Built-in"], ["on", "On for this bot"]]) filt.appendChild(new Option(t, v));
  const frow = el("div", "fldrow"); frow.style.marginBottom = "10px"; frow.append(q, filt);
  filt.style.flex = "0 0 170px";

  const box = el("div", "sklist scroll");
  const draw = () => {
    box.innerHTML = "";
    const b = bot(sel.value) || {}, on = id => (b.skills || []).includes(id);
    const needle = q.value.trim().toLowerCase();
    let list = S.skills.slice();
    if (filt.value === "recent") list = list.filter(s => s.installed_at)
      .sort((x, y) => (y.installed_at || "").localeCompare(x.installed_at || ""));
    else if (filt.value === "installed") list = list.filter(s => s.installed_at);
    else if (filt.value === "builtin") list = list.filter(s => s.builtin);
    else if (filt.value === "on") list = list.filter(s => on(s.id));
    if (needle) list = list.filter(s => (s.name + " " + s.desc).toLowerCase().includes(needle));
    if (!list.length) { box.appendChild(el("div", "hint", "No skills match.")); return; }
    for (const s of list) {
      const d = skBox(`<span class="ck"></span><span><span class="hd"><b>${esc(s.name)}</b>${s.installed_at ? `<i class="tag">installed</i>` : ""}</span><span>${esc(s.desc)}</span></span>`, on(s.id),
        nv => { const set = new Set(b.skills || []); nv ? set.add(s.id) : set.delete(s.id); b.skills = [...set]; });
      if (s.installed_at) {                                  // an installed skill can be taken back out
        const rm = el("button", "btn ghost sm", "Remove"); rm.type = "button"; rm.title = "Uninstall " + s.name;
        rm.onclick = async e => {
          e.stopPropagation(); if (!confirm("Uninstall " + s.name + "?")) return;
          const r = await jpost("/api/skills/remove", { id: s.id });
          if (r.ok) { S.skills = r.skills; znote.textContent = "Uninstalled " + s.name; draw(); }
        };
        d.appendChild(rm);
      }
      box.appendChild(d);
    }
  };
  sel.onchange = draw; q.oninput = draw; filt.onchange = draw;
  const zrow = el("div", "row"); zrow.style.marginBottom = "14px"; zrow.append(zfile, zbtn, znote);
  znote.style.alignSelf = "center";
  p.appendChild(zrow); p.appendChild(zpick);
  fld(p, "BOT", sel);
  fld(p, "SKILLS", box, "Click a skill to switch it on or off for this bot.");
  p.insertBefore(frow, box.parentNode);
  const row = el("div", "row");
  const save = el("button", "btn pri", "Save");
  save.onclick = async () => { await post("/api/bot", { bot: bot(sel.value) }); save.textContent = "Saved"; setTimeout(() => save.textContent = "Save", 1200); };
  row.appendChild(save); p.appendChild(row);
  draw();
}
/* --- Plugins --- */
/* MCP servers, for real. A server is a command (a local one, spoken to over a pipe) or a URL (a
   remote one); whichever it is, the tools it offers are handed to every bot, named after the server
   so two servers can both have an `echo`. The panel is what connects one and says what it found, so
   a server that will not come up says why here rather than failing silently inside a turn. */
function tabPlugins(p) {
  h3(p, "Plugins", "MCP servers your bots can use. Add a server by the command that starts it (a local one) or its URL (a remote one) — the tools it offers become your bots' tools, named after the server. Env values and headers are stored but never shown again, like every other credential here.");
  const box = el("div"); p.appendChild(box);
  let status = {};
  const line = s => String(s == null ? "" : s).split("\n").map(x => x.trim()).filter(Boolean);
  const kv = (s, sep) => { const o = {}; for (const l of line(s)) { const i = l.indexOf(sep); if (i > 0) o[l.slice(0, i).trim()] = l.slice(i + sep.length).trim(); } return o; };
  const draw = async () => {
    const c = await get("/api/config"); if (!c) return;   // a failed read keeps the last drawn status
    status = c.mcp_status || {};
    box.innerHTML = "";
    const servers = S.settings.mcp || [];
    if (!servers.length) box.appendChild(el("p", "desc", "No MCP server yet. A local one starts with a command like <code>npx -y @modelcontextprotocol/server-filesystem /tmp</code>; a remote one is its https URL."));
    for (const m of servers) {
      const st = status[m.id] || {};
      const d = el("div", "card");
      const nEnv = (m.env_keys || []).length, nHdr = (m.header_keys || []).length;
      const detail = !m.enabled ? "switched off"
        : !st.checked ? "not tested yet — press Test"
        : st.ok ? st.tools + (st.tools === 1 ? " tool" : " tools") + (st.info ? " · " + st.info : "")
        : "did not connect";
      const creds = (nEnv || nHdr) ? " · " + nEnv + " env, " + nHdr + " header set" : "";
      const state = (m.enabled && st.ok) ? "ok" : "off";
      d.innerHTML = `<div class="ct"><span class="ico">${svg("plugins")}</span><div><b>${esc(m.name)}</b>
        <div class="sub">${esc(m.kind)} · ${esc(m.target || "")}</div>
        <div class="sub">${esc(detail + creds)}</div></div>
        <div class="rt"><span class="tag ${state}">${state === "ok" ? "on" : "off"}</span></div></div>`;
      if (st.checked && !st.ok && st.error) d.appendChild(el("div", "desc", esc(st.error)));
      const row = el("div", "row");
      const test = el("button", "btn ghost sm", "Test");
      test.onclick = async () => {
        test.textContent = "Connecting…";
        // The answer is remembered on the server, so re-drawing reads it back: the card then shows
        // the tool count, or the reason it would not come up.
        await post("/api/mcp/test", { id: m.id });
        await draw();
      };
      const on = el("button", "btn ghost sm", m.enabled ? "Switch off" : "Switch on");
      on.onclick = async () => { await saveSettings({ mcp: servers.map(x => x.id === m.id ? { ...x, enabled: !m.enabled } : x) }); await draw(); };
      const del = el("button", "btn ghost sm", "Remove");
      del.onclick = async () => { await saveSettings({ mcp: servers.filter(x => x.id !== m.id) }); await draw(); };
      row.append(test, on, del); d.appendChild(row);
      box.appendChild(d);
    }
    const name = el("input"); name.placeholder = "server name, e.g. Filesystem";
    const target = el("input"); target.placeholder = "command, e.g. npx -y @modelcontextprotocol/server-filesystem /tmp — or an https URL";
    const env = el("textarea"); env.style.minHeight = "60px"; env.placeholder = "one KEY=value per line (optional; for a local server)";
    const hdr = el("textarea"); hdr.style.minHeight = "60px"; hdr.placeholder = "one Name: value per line (optional; for a remote server)";
    const f = el("div", "fld"); f.appendChild(el("label", "", "ADD SERVER"));
    f.append(name, target);
    const add = el("button", "btn pri sm", `${svg("plus")} Add server`);
    const entry = () => ({
      id: name.value.toLowerCase().replace(/\W+/g, "-").replace(/^-+|-+$/g, "").slice(0, 24),
      name: name.value.trim(), kind: /^https?:/i.test(target.value.trim()) ? "url" : "stdio",
      target: target.value.trim(), enabled: true,
      ...(Object.keys(kv(env.value, "=")).length ? { env: kv(env.value, "=") } : {}),
      ...(Object.keys(kv(hdr.value, ":")).length ? { headers: kv(hdr.value, ":") } : {}),
    });
    const probe = el("button", "btn ghost sm", "Test");
    const out = el("div", "desc");
    const runTest = async () => {
      if (!target.value.trim()) { out.textContent = "A command or a URL is needed first."; return; }
      probe.textContent = "Connecting…";
      const r = await jpost("/api/mcp/test", { server: entry() });
      probe.textContent = "Test";
      out.textContent = r.ok
        ? "Connected. " + r.tools.length + " tool" + (r.tools.length === 1 ? "" : "s") + (r.tools.length ? ": " + r.tools.slice(0, 10).join(", ") + (r.tools.length > 10 ? "…" : "") : "")
        : "Did not connect: " + (r.error || "no reason given");
    };
    probe.onclick = runTest;
    add.onclick = async () => {
      const e = entry();
      if (!e.name || !e.target || !e.id) { out.textContent = "A name and a command or URL are needed."; return; }
      if ((S.settings.mcp || []).some(x => x.id === e.id)) { out.textContent = "A server with that name already exists."; return; }
      await saveSettings({ mcp: [...(S.settings.mcp || []), e] }); await draw();
    };
    const arow = el("div", "row"); arow.append(probe, add);
    f.appendChild(env); f.appendChild(hdr); f.appendChild(arow); f.appendChild(out);
    box.appendChild(f);
  };
  draw().catch(() => {});   // a failed config read must not surface as an unhandled rejection
}
/* --- Connected apps --- */
function tabApps(p) {
  h3(p, "Connected apps", "Connect an app once and every bot gains a real tool that calls its API — a token for most, an OAuth refresh token for the Google ones.");
  const wrap = el("div"); p.appendChild(wrap);
  const draw = async () => {
    const c = await get("/api/config"); if (!c) return;   // a failed read keeps the cards already drawn
    S.connectorTools = c.connector_tools || [];
    wrap.innerHTML = "";
    const grid = el("div", "grid2"); wrap.appendChild(grid);
    for (const conn of (c.settings.connectors || [])) {
      const d = el("div", "card");
      d.innerHTML = `<div class="ct">${avatar(conn.name, colorFor(conn.name), "sm")}
        <div><b>${esc(conn.name)}</b><div class="sub">${conn.connected ? "connected. Bots can call it now" : "not connected"}</div></div>
        <div class="rt"><span class="tag ${conn.connected ? "ok" : "off"}">${conn.connected ? "on" : "off"}</span></div></div>`;
      const note = el("div", "desc", " ");
      if (conn.id === "webhook") {
        const url = el("input"); url.placeholder = "Default webhook URL (optional; tools can pass any https URL)";
        const sec = el("input"); sec.type = "password"; sec.style.marginTop = "8px";
        sec.placeholder = conn.connected ? "••••••••  secret saved. Leave blank to keep" : "Optional shared secret (sent as X-Webhook-Secret)";
        if (conn.base_url) url.value = conn.base_url;
        const row = el("div", "row"); row.style.marginTop = "10px";
        const save = el("button", "btn pri sm", conn.connected ? "Save" : "Connect");
        const test = el("button", "btn ghost sm", "Test"); test.style.marginLeft = "8px";
        const disc = el("button", "btn ghost sm", "Disconnect"); disc.style.marginLeft = "8px";
        save.onclick = async () => {
          const body = { id: conn.id, base_url: url.value.trim() };
          if (sec.value.trim()) body.token = sec.value.trim();
          const r = await jpost("/api/connector", body);
          note.textContent = r.ok ? (r.connected ? "Connected. webhook_post is live for all bots." : "Saved (no URL/secret yet).") : ("Could not save: " + (r.error || "unknown"));
          await reloadConfig(); renderPanel();
        };
        test.onclick = async () => { note.textContent = "Sending a test ping…";
          const r = await jpost("/api/connector/test", { id: conn.id });
          note.textContent = r.ok ? "Delivered: " + r.out.replace(/\n/g, " ") : "Failed: " + (r.out || r.error || "no response").replace(/\n/g, " "); };
        disc.onclick = async () => { await post("/api/connector", { id: conn.id, disconnect: true }); await reloadConfig(); renderPanel(); };
        if (!conn.connected) disc.style.display = "none";
        row.append(save, test, disc);
        d.append(url, sec, row, note);
      } else if (conn.auth === "google") {
        // A Google access token dies within the hour, so pasting one buys a connector that works
        // until lunchtime. This asks for the durable credential instead: a refresh token plus the
        // OAuth client that mints fresh access tokens from it.
        const cid = el("input");
        cid.placeholder = conn.has_client ? "••••••••  client id saved. Leave blank to keep it" : "OAuth client id";
        const csec = el("input"); csec.type = "password"; csec.style.marginTop = "8px";
        csec.placeholder = conn.has_secret ? "••••••••  client secret saved. Leave blank to keep it" : "OAuth client secret";
        const tok = el("input"); tok.type = "password"; tok.style.marginTop = "8px";
        tok.placeholder = conn.connected ? "••••••••  refresh token saved. Leave blank to keep it" : "Refresh token";
        const base = el("input"); base.style.marginTop = "8px"; base.placeholder = "API base URL (optional; default shown)";
        if (conn.base_url) base.value = conn.base_url;
        const how = el("div", "desc",
          'Create an OAuth client of type <b>Desktop app</b> in the Google Cloud console, then get a ' +
          'refresh token from the <a href="https://developers.google.com/oauthplayground" target="_blank" ' +
          'rel="noopener">OAuth Playground</a> (gear icon → tick "Use your own OAuth credentials"). ' +
          'A refresh token from a consent screen still in Testing mode expires after 7 days.');
        how.style.marginTop = "8px";
        const row = el("div", "row"); row.style.marginTop = "10px";
        const save = el("button", "btn pri sm", conn.connected ? "Save" : "Connect");
        const test = el("button", "btn ghost sm", "Test"); test.style.marginLeft = "8px";
        const disc = el("button", "btn ghost sm", "Disconnect"); disc.style.marginLeft = "8px";
        save.onclick = async () => {
          const body = { id: conn.id, base_url: base.value.trim() };
          if (cid.value.trim()) body.client_id = cid.value.trim();
          if (csec.value.trim()) body.client_secret = csec.value.trim();
          if (tok.value.trim()) body.token = tok.value.trim();
          const r = await jpost("/api/connector", body);
          note.textContent = r.ok ? (r.connected ? "Connected: " + (r.tools.find(t => TOOL_LABEL[t]) || conn.name.toLowerCase()) + " is live for all bots." : "Saved, but still not connected. It needs the client id, client secret and refresh token.") : ("Could not save: " + (r.error || "unknown"));
          await reloadConfig(); renderPanel();
        };
        test.onclick = async () => { note.textContent = "Exchanging the refresh token, then calling the real API…";
          const r = await jpost("/api/connector/test", { id: conn.id });
          note.textContent = r.ok ? "Works: " + r.out.replace(/\n/g, " ").slice(0, 200) : "Failed: " + (r.out || r.error || "no response").replace(/\n/g, " ").slice(0, 200); };
        disc.onclick = async () => { await post("/api/connector", { id: conn.id, disconnect: true }); await reloadConfig(); renderPanel(); };
        if (!conn.connected) disc.style.display = "none";
        row.append(save, test, disc);
        d.append(cid, csec, tok, base, row, how, note);
      } else {
        const tok = el("input"); tok.type = "password";
        tok.placeholder = conn.connected ? "••••••••  saved. Leave blank to keep it" : "Paste your " + conn.name + " token";
        const base = el("input"); base.style.marginTop = "8px"; base.placeholder = "API base URL (optional; default shown)";
        if (conn.base_url) base.value = conn.base_url;
        const row = el("div", "row"); row.style.marginTop = "10px";
        const save = el("button", "btn pri sm", conn.connected ? "Save" : "Connect");
        const test = el("button", "btn ghost sm", "Test"); test.style.marginLeft = "8px";
        const disc = el("button", "btn ghost sm", "Disconnect"); disc.style.marginLeft = "8px";
        save.onclick = async () => {
          const body = { id: conn.id, base_url: base.value.trim() };
          if (tok.value.trim()) body.token = tok.value.trim();
          const r = await jpost("/api/connector", body);
          note.textContent = r.ok ? (r.connected ? "Connected: " + (r.tools.find(t => TOOL_LABEL[t]) || conn.name.toLowerCase()) + " is live for all bots." : "Saved, but still not connected. A token is required.") : ("Could not save: " + (r.error || "unknown"));
          await reloadConfig(); renderPanel();
        };
        test.onclick = async () => { note.textContent = "Calling the real API…";
          const r = await jpost("/api/connector/test", { id: conn.id });
          note.textContent = r.ok ? "Works: " + r.out.replace(/\n/g, " ").slice(0, 160) : "Failed: " + (r.out || r.error || "no response").replace(/\n/g, " ").slice(0, 160); };
        disc.onclick = async () => { await post("/api/connector", { id: conn.id, disconnect: true }); await reloadConfig(); renderPanel(); };
        if (!conn.connected) disc.style.display = "none";
        row.append(save, test, disc);
        d.append(tok, base, row, note);
      }
      const tool = TOOL_LABEL[conn.id === "webhook" ? "webhook_post" : conn.id + "_api"];
      if (tool && conn.connected) d.appendChild(el("div", "desc", "Tool for bots: <code>" + tool + "</code>"));
      grid.appendChild(d);
    }
  };
  draw().catch(() => {});   // a failed config read must not surface as an unhandled rejection
}
/* --- Voice --- */
function tabVoice(p) {
  h3(p, "Voice", "Read bot replies aloud, using the browser's built-in voices.");
  const cur = () => S.settings.voice || {};   // read fresh: a captured copy goes stale after each save
  toggle(p, "Read replies aloud", "Show a listen button on longer bot replies.", nv => saveSettings({ voice: { ...cur(), auto: nv, enabled: nv } }), cur().auto);
  const vs = el("select");
  const fill = () => {
    const keep = vs.value || cur().voice_id || "";
    vs.innerHTML = ""; vs.appendChild(new Option("Default voice", ""));
    for (const voice of (window.speechSynthesis ? speechSynthesis.getVoices() : [])) vs.appendChild(new Option(voice.name, voice.name));
    vs.value = keep;
  };
  fill();
  /* Chrome fills the voice list asynchronously: the first read can come back empty and the real list
     arrives on this event, so repopulate then instead of leaving the dropdown blank until reopen. */
  if (window.speechSynthesis) speechSynthesis.onvoiceschanged = fill;
  vs.onchange = () => saveSettings({ voice: { ...cur(), voice_id: vs.value } });
  fld(p, "VOICE", vs, "Pick one of the voices your browser already has. Nothing is sent to a server.");
  const test = el("button", "btn ghost sm", `${svg("speaker")} Test voice`); test.onclick = () => speak("Hello! I am a bot in your Anzen-bot team. Everything is unlocked.");
  p.appendChild(test);
}
/* --- Appearance --- */
function tabAppearance(p) {
  h3(p, "Appearance", "Theme, accent, font and density.");
  const cur = () => S.settings.appearance || {};   // read fresh: a captured copy goes stale after each save
  /* A theme package is a whole look, so it is a list rather than a switch. Picking one adopts its
     signature accent — otherwise the theme's palette would never be seen behind the accent you
     happened to have — and the colour field below is where you take it back. Re-picking the theme
     you are already on leaves your accent alone, so a stray click cannot undo a colour you chose. */
  const thsel = el("select"); thsel.id = "themeSel";
  for (const t of THEMES) thsel.appendChild(new Option(t[1], t[0]));
  thsel.value = themeDef(cur().theme)[0];
  thsel.onchange = () => {
    const v = thsel.value, a = { ...cur(), theme: v };
    if (v !== cur().theme) a.accent = themeDef(v)[2];
    saveSettings({ appearance: a });
  };
  fld(p, "THEME", thsel, "A whole look — surfaces, accent and type. The colour below overrides the theme's own accent.");
  const acc = el("input"); acc.type = "color"; acc.value = cur().accent || "#7C5CFF";
  acc.style.height = "44px"; acc.style.padding = "4px";
  acc.oninput = () => applyAppearance({ ...cur(), accent: acc.value });   // preview live
  const row = el("div", "row");
  const save = el("button", "btn pri", "Save");
  save.onclick = async () => { await saveSettings({ appearance: { ...cur(), accent: acc.value } });
    save.textContent = "Saved"; setTimeout(() => save.textContent = "Save", 1400); };
  row.appendChild(save);
  const wrap = el("div"); wrap.appendChild(acc); wrap.appendChild(row);
  fld(p, "ACCENT", wrap, "Pick a colour. It previews live. Click Save to keep it.");
  selectFld(p, "DENSITY", cur().density || "comfortable", [["comfortable", "Comfortable"], ["compact", "Compact"]],
    v => saveSettings({ appearance: { ...cur(), density: v } }));
  selectFld(p, "FONT", cur().font || "system", FONTS.map(f => [f[0], f[1]]),
    v => saveSettings({ appearance: { ...cur(), font: v } }),
    "The typeface for the whole interface. Each one ships with your system, so nothing is downloaded.");
  selectFld(p, "FONT SIZE", String(cur().font_size || BASE_PX), S.fontSizes.map(s => [String(s), s + " px"]),
    v => saveSettings({ appearance: { ...cur(), font_size: parseFloat(v) } }),
    "The base text size. Everything else is this times its own designed value, so the whole interface grows with it.");
  toggle(p, "Corner mascot", "The animated face in the bottom-right corner. Hiding it keeps its state, so it comes back where you left it.", v => setDockHidden(!v), !dockHidden());
}

/* ---------------- input ---------------- */
$("#btnMenu").onclick = openDrawer;
syncDrawer();     // a narrow screen starts with the drawer closed, so take it out of the tab order
$("#backdrop").onclick = closeDrawer;
$("#btnSend").onclick = send;
$("#btnStop").onclick = stopTurn;
$("#btnSettings").onclick = () => openSettings("general");
$("#btnHelp").onclick = () => openSettings("help");
kbd($("#btnHelp"), $("#btnHelp").onclick);
initRail();
/* ---------------- the chats section, and dragging the sidebar into shape ---------------- */
/* The label folds the section; the + beside it still opens a new chat, so a click that landed on
   the add button is left to it. */
const foldChats = e => { if (!e.target.closest(".add")) foldSec("chats"); };
$("#chatsLabel").onclick = foldChats;
kbd($("#chatsLabel"), foldChats);
applySecs();
/* Delegated on the wrapper, which is never rebuilt: the rows are, on every renderNav. */
const navwrap = $("#navwrap");
navwrap.addEventListener("dragstart", dragStart);
navwrap.addEventListener("dragover", dragOver);
navwrap.addEventListener("dragend", dragEnd);
/* Without this the browser refuses the drop and the row snaps back on the release. */
navwrap.addEventListener("drop", e => { if (dragRow) e.preventDefault(); });
/* ---------------- chat list ---------------- */
/* Search is local: the list is already in memory and is at most a few dozen rows, so filtering it is
   a string compare rather than a round trip per keystroke. */
$("#chatSearch").addEventListener("input", e => { S.chatQuery = e.target.value; renderChats(); });
/* A chat here is a conversation with one bot or one room, so "new chat" is the same act as the row
   menu's "Clear chat": the transcript goes, the bot keeps its memory. It is the one button, in the
   one place, so the two can never mean different things. */
$("#btnNewChat").onclick = () => {
  if (!S.active) return;
  S.ctxSess = S.active;
  ctxAction("clear", S.activeIsChannel ? S.active : botIdOf(S.active), S.activeIsChannel ? "channel" : "bot");
};
kbd($("#btnNewChat"), $("#btnNewChat").onclick);
/* One listener for every code block's Copy button, because the blocks are rebuilt on every render
   and per-block handlers would be thrown away with them. */
document.addEventListener("click", e => {
  const b = e.target.closest && e.target.closest(".md .cbcopy"); if (!b) return;
  const code = b.parentElement.querySelector("code");
  copyText(code ? code.textContent : "", b);
});
/* The model chip names the model that will actually answer this chat and swaps it on the spot,
   so changing models never means a trip through Settings. */
function closeModelMenu(e) {
  if (inside(e, "#mmPop, #chipModel")) return;
  const m = $("#mmPop"); if (m) m.remove();
  $("#chipModel").setAttribute("aria-expanded", "false");
  document.removeEventListener("click", closeModelMenu, true);
}
async function pickModel(m) {
  closeModelMenu();
  const r = await jpost("/api/model", { session: S.active, model: m });
  if (r.ok === false) { alert(r.error || "Could not change the model."); return; }
  $("#chipModel").textContent = "Model: " + (r.model || "none");
}
/* The chip reads "Model: <name>"; the menu needs the bare name to match it against the list, so one
   place knows the prefix and the chip's label and the menu's "in use" mark cannot drift apart. */
const chipModelName = () => $("#chipModel").textContent.replace(/^Model:\s*/, "").trim();
function modelMenu() {
  if ($("#mmPop")) return closeModelMenu();
  const chip = $("#chipModel");
  const pop = el("div", "mpop"); pop.id = "mmPop";
  /* The chip advertises `aria-haspopup="dialog"`, so this has to *be* one — a plain div under a
     chip that promises a menu is a lie a screen reader repeats. Same shape as `#ctxpop`. */
  pop.setAttribute("role", "dialog"); pop.setAttribute("aria-label", "Choose a model");
  const q = el("input"); q.placeholder = "Filter models…";
  const list = el("div", "mlist");
  const draw = () => {
    list.innerHTML = "";
    const cur = chipModelName();
    const hits = modelHits(q.value);
    const shown = hits.slice(0, 200);
    // a long list is cut off at 200, which can hide the model that is answering right now
    if (hits.includes(cur) && !shown.includes(cur)) shown.unshift(cur);
    for (const m of shown) {
      const b = el("button", "mrow" + (cur === m ? " on" : ""));
      b.innerHTML = `<b>${esc(m)}</b>`;
      b.onclick = () => pickModel(m);
      list.appendChild(b);
    }
    if (!hits.length) list.innerHTML = `<div class="mempty">${S.models.length
      ? "No model matches “" + esc(q.value) + "”." : "No models in your list yet — add them in Settings, AI model."}</div>`;
  };
  q.oninput = draw; draw();
  const own = el("button", "mrow", `<b>Each bot's own model</b><span>Clear this chat's pick</span>`);
  own.onclick = () => pickModel("");
  pop.append(q, list, own);
  chip.parentNode.appendChild(pop);
  chip.setAttribute("aria-expanded", "true");
  setTimeout(() => document.addEventListener("click", closeModelMenu, true), 0);
  q.focus();
}
$("#chipModel").onclick = modelMenu;
/* The Approval chip is a switch, like the model chip: it names what the current chat may do and
   changes it on the spot, so setting an approval never means a trip through the whole Bots list —
   which is what it used to open. A room also lists *its own* members and no others, because a room
   is the only place a per-bot default is worth setting from inside the chat. */
function closeApprovalMenu(e) {
  if (inside(e, "#apPop, #chipMem")) return;
  const m = $("#apPop"); if (m) m.remove();
  $("#chipMem").setAttribute("aria-expanded", "false");
  document.removeEventListener("click", closeApprovalMenu, true);
}
async function pickApproval(mode) {
  closeApprovalMenu();
  /* `jpost`, not `post`: a 500 or a dead server resolves the bare fetch without throwing, so the chip
     would report a level the server never accepted. Only move the chip once the server has confirmed. */
  const r = await jpost("/api/approval_mode", { session: S.active, mode });
  if (r.ok === false) { alert(r.error || "Could not change the approval level."); return; }
  /* The server files a channel's level on the channel itself, so a level picked from a member's row
     sets the room. Clearing it puts the channel back to its default of asking. */
  if (roomOf(S.active)) { S.approvalSet = true; S.approval = mode || "ask"; }
  else { S.approvalSet = !!mode; S.approval = mode || S.approvalOwn || "ask"; }
  chipApproval();
}
function approvalMenu() {
  if ($("#apPop")) return closeApprovalMenu();
  const chip = $("#chipMem");
  const room = roomOf(S.active);
  const pop = el("div", "mpop"); pop.id = "apPop";
  /* Matches the chip's `aria-haspopup="dialog"` — see the note in `modelMenu`. */
  pop.setAttribute("role", "dialog"); pop.setAttribute("aria-label", "Choose an approval level");
  if (room) {
    /* A channel has one level for the whole room, so the menu sets that and nothing else: no
       per-member pickers, because a member's own default is not what runs in a room. A bot's own
       level is set where the bot is, in Bots → Edit. */
    pop.appendChild(el("div", "aphead", "What may run in this room"));
  } else if (S.approvalSet) {
    /* The way back to the bot's own default, offered only when this chat is on its own level, so it
       is never a no-op. */
    const back = el("button", "mrow");
    back.innerHTML = `<b>Use ${esc(NAME(S.active))}'s own level</b><span>Follow the bot's own default (${esc(approvalLabel(S.approvalOwn || "ask"))}).</span>`;
    back.onclick = () => pickApproval("");
    pop.appendChild(back);
    pop.appendChild(el("div", "aphead", "Or set a level for this chat"));
  } else {
    pop.appendChild(el("div", "aphead", "What " + esc(NAME(S.active)) + " may do"));
  }
  for (const [v, t, d] of APPROVALS) {
    const b = el("button", "mrow" + (v === S.approval ? " on" : ""));
    b.innerHTML = `<b>${esc(t)}</b><span>${esc(d)}</span>`;
    b.onclick = () => pickApproval(v);
    pop.appendChild(b);
  }
  chip.parentNode.appendChild(pop);
  chip.setAttribute("aria-expanded", "true");
  setTimeout(() => document.addEventListener("click", closeApprovalMenu, true), 0);
  /* A dialog the keyboard cannot enter is a dialog a keyboard user cannot use. Move focus to the
     current level, so Tab and Enter work from inside the menu rather than on the chip behind it. */
  const on = pop.querySelector(".mrow.on") || pop.querySelector(".mrow");
  if (on) on.focus();
}
$("#chipMem").onclick = approvalMenu;
/* The context chip: how full this chat's window is, and on hover what filled it. The server measures
   each request as it goes out and sends a `ctx` payload back, so every number here is the provider's
   own count for a request that really happened — the rows are the pieces this app composes a prompt
   from, scaled onto that count so the shares still add up to the whole. */
const CTX_HUES = ["var(--accent)", "#4C8DF6", "#22B8A0", "#E0A82E", "#B06CF0", "#9AA3B2"];
const fmtTok = n => !n ? "0" : n >= 1000 ? (n / 1000).toFixed(1) + "K" : String(n);
function renderCtx(c) {
  const chip = $("#chipCtx"), pop = $("#ctxpop"); if (!chip || !pop) return;
  const used = (c && c.tokens) || 0, lim = (c && c.limit) || 0;
  const pct = lim ? used / lim * 100 : 0;
  chip.textContent = used ? "Context: " + Math.round(pct) + "%" : "Context: —";
  chip.classList.toggle("warm", pct >= 75 && pct < 90);
  chip.classList.toggle("hot", pct >= 90);
  pop.innerHTML = "";
  if (!used) {
    pop.append(el("div", "ctxhead", "<span>Context window</span>"),
               el("div", "mempty", "Nothing sent in this chat yet. The window fills as you talk."));
    return;
  }
  const rows = (c.rows || []).filter(r => r.tokens > 0);
  const sum = rows.reduce((a, r) => a + r.tokens, 0) || 1;
  const head = el("div", "ctxhead");
  head.innerHTML = `<span>Context window</span><b>${fmtTok(used)} / ${fmtTok(lim)} (${pct.toFixed(1)}%)</b>`;
  const bar = el("div", "ctxbar"), fill = el("div", "ctxfill");
  fill.style.width = Math.min(100, pct).toFixed(1) + "%";
  const list = el("div", "ctxrows");
  rows.forEach((r, i) => {
    const share = r.tokens / sum * 100, hue = CTX_HUES[i % CTX_HUES.length];
    const seg = el("i"); seg.style.flexGrow = String(share); seg.style.background = hue;
    seg.title = `${r.label} — ${fmtTok(r.tokens)} tokens (${share.toFixed(1)}%)`;
    fill.appendChild(seg);
    const row = el("div", "ctxrow");
    row.title = fmtTok(r.tokens) + " tokens";
    row.innerHTML = `<span class="dot" style="background:${hue}"></span><span class="lbl">${esc(r.label)}</span>` +
      `<span class="pct">${share.toFixed(1)}%</span>`;
    list.appendChild(row);
  });
  bar.appendChild(fill);
  pop.append(head, bar, list);
  if (c.seen) pop.appendChild(el("div", "ctxfoot", "Average cache hit rate " + (c.hit / c.seen * 100).toFixed(1) + "%"));
}
/* Hover is the CSS above; a click opens it too, so it works on touch and from the keyboard. */
function closeCtxPop(e) {
  if (inside(e, ".ctxwrap")) return;
  const w = $(".ctxwrap"); if (w) w.classList.remove("open");
  $("#chipCtx").setAttribute("aria-expanded", "false");
  document.removeEventListener("click", closeCtxPop, true);
}
$("#chipCtx").onclick = () => {
  const w = $("#chipCtx").parentNode;
  if (w.classList.contains("open")) return closeCtxPop();
  w.classList.add("open");
  $("#chipCtx").setAttribute("aria-expanded", "true");
  setTimeout(() => document.addEventListener("click", closeCtxPop, true), 0);
};
// Installable app: show an Install button when the browser offers the prompt.
let deferredPrompt = null;
window.addEventListener("beforeinstallprompt", e => { e.preventDefault(); deferredPrompt = e; $("#btnInstall").style.display = "inline-flex"; });
$("#btnInstall").onclick = async () => { if (!deferredPrompt) return; deferredPrompt.prompt(); await deferredPrompt.userChoice; deferredPrompt = null; $("#btnInstall").style.display = "none"; };
window.addEventListener("appinstalled", () => { $("#btnInstall").style.display = "none"; });
$("#sClose").onclick = closeSettings;
$("#scrim").onclick = e => { if (e.target === $("#scrim")) closeSettings(); };
// The "new output" pill: shown when a live turn writes while you are reading back, gone the moment
// you are at the bottom again (whether by clicking it or scrolling there yourself).
$("#jump").onclick = () => { toBottom($("#msgs")); $("#jump").hidden = true; };
/* Your own scrolling is what decides whether the transcript follows new output. Landing at the bottom
   — by scrolling there or by the pill — turns following back on; scrolling up turns it off for as long
   as you keep scrolling, and a few seconds of it is a pause, not a decision: the follow comes back on
   its own, and the view stays where you left it, because only a message moves it. It has to come back,
   because the bottom keeps moving down as the transcript grows, so a reader parked a little short of
   it is one the app would otherwise never follow again. */
$("#msgs").addEventListener("scroll", () => {
  pinned = nearBottom($("#msgs"));
  if (pinned) { clearTimeout(resumeTimer); $("#jump").hidden = true; }
  else holdFollow();
});
// Escape closes Settings — but a dialog stacked above it (folder picker, forward, import) owns its
// own Escape and its own Tab ring, so it must not also tear down the panel underneath.
document.addEventListener("keydown", e => {
  if (!$("#scrim").classList.contains("on")) return;
  if (document.querySelector(".modal.pick")) return;
  if (e.key === "Escape") return closeSettings();
  if (e.key === "Tab") trapTab($("#scrim .modal"), e);
});
$("#addBot").onclick = () => openSettings("bots", "__new__");
$("#addChannel").onclick = () => { openSettings("channels"); editChannel(null); };
kbd($("#addBot"), $("#addBot").onclick);
kbd($("#addChannel"), $("#addChannel").onclick);
$("#btnComp").onclick = openComp;
$("#compClose").onclick = closeComp;
/* The panel already polls, so a silent click on Refresh looked like it did nothing at all. Hold the
   word long enough to be read — a capture takes a few hundred ms, which flickers past otherwise —
   and ask for a forced one, which re-decides which profile is on screen instead of reusing the poll's. */
$("#compRefresh").onclick = async e => {
  const b = e.currentTarget, label = b.textContent;
  b.disabled = true; b.textContent = "Refreshing…";
  const t0 = performance.now();
  await refreshComp(true);
  setTimeout(() => { b.disabled = false; b.textContent = label; }, Math.max(0, 450 - (performance.now() - t0)));
};
$("#compOpen").onclick = async () => { const u = $("#compUrl").value.trim(); if (!u) return;
  await post("/api/computer/open", { url: u, session: S.active }); await refreshComp(true);
};
$("#btnFiles").onclick = openFiles;
$("#filesClose").onclick = closeFiles;
$("#linkClose").onclick = closeLink;
/* Back walks the links you followed from inside the panel. A frame is not a history stack we can ask,
   so the panel keeps its own — which is also what lets the button know when there is nothing behind. */
$("#linkBack").onclick = () => { if (linkAt > 0) { linkAt--; showLink(); } };
/* Same reasoning as the computer panel's: the list only changes when the user asks it to, so a click
   with no visible result reads as broken. Hold the word long enough to be read. */
$("#filesRefresh").onclick = async e => {
  const b = e.currentTarget, label = b.textContent;
  b.disabled = true; b.textContent = "Refreshing…";
  const t0 = performance.now();
  await refreshFiles();
  setTimeout(() => { b.disabled = false; b.textContent = label; }, Math.max(0, 450 - (performance.now() - t0)));
};
/* The panel is a side overlay, not a dialog, so it has no scrim to catch a click — this stands in for
   one: press anywhere but the panel itself (the chat field, the sidebar, a message) and it closes.
   `pointerdown` rather than `click` so it lands before the press does its own work, and the button
   that opens a panel is left out, so pressing that again does not close and reopen in one go. `#ctx`
   is left out too: a menu opened from a row in the panel is not "somewhere else", and closing the
   panel on the way to a menu item would take the row the item hands focus back to with it. */
document.addEventListener("pointerdown", e => {
  if (inside(e, "#comp, #files, #link, #btnComp, #btnFiles, #ctx")) return;
  /* A link in the transcript is the panel's own opener, not "somewhere else": closing on the press and
     reopening on the click would slide the panel out and back in again on every link you follow. */
  if (e.target.closest && e.target.closest("#msgs a[href]")) return;
  if ($("#comp").classList.contains("on")) { closeComp(false); return; }
  if ($("#files").classList.contains("on")) closeFiles(false);
  if ($("#link").classList.contains("on")) closeLink(false);
});
/* A link in the transcript opens beside the chat instead of taking the window with it. Delegated onto
   the transcript rather than bound per anchor: the transcript is rebuilt on every redraw and repainted
   every 120ms while a bot streams, so a handler bound to an anchor is thrown away mid-turn. A modified
   click (⌘/Ctrl, ⇧, middle) is left to the browser — that is the reader asking for their own browser. */
$("#msgs").addEventListener("click", e => {
  const a = e.target.closest ? e.target.closest("#msgs a[href]") : null;
  if (!a) return;
  const href = a.getAttribute("href") || "";
  if (!/^https?:/i.test(href)) return;         // mailto:, an in-page #anchor, or a filtered-out scheme
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
  e.preventDefault();
  openLink(href, a);
});
/* The poke affordance is a real <button>, so Enter and Space come for free — no `kbd` shim. */
$("#dockPoke").onclick = pokeDock;
$("#dock").addEventListener("pointerenter", () => showTip(STATES_LABEL[dockReal] || dockReal));
$("#dock").addEventListener("pointerleave", () => $("#dockTip").classList.remove("on"));
/* The × is a sibling of the poke button, so its clicks never reach the poke at all. */
$("#dockHide").onclick = () => setDockHidden(true);
setDockHidden(dockHidden());                              // honour the saved choice on load
/* ---------------- @mention picker ----------------
   In a room, @ names a teammate. The list is that room's members, and the token inserted is the
   bot's NAME, which is what the server matches a mention against (a typed @Producer finds the
   producer). Outside a room there is nobody to name, so @ does nothing. */
const MP = { open: false, items: [], idx: 0, at: 0 };
const mentionMembers = () => {
  if (!S.activeIsChannel) return [];
  const c = chan(S.active);
  return c ? (c.members || []).map(bot).filter(b => b && !b.hidden) : [];
};
/* The mention being typed: the @ and what follows it up to the caret. Only a @ that starts a word
   counts, so an email address in the text never opens the list, and a newline ends it. */
function mentionQuery() {
  const ta = $("#input"), pos = ta.selectionStart;
  if (pos == null) return null;
  const before = ta.value.slice(0, pos);
  const at = before.lastIndexOf("@");
  if (at < 0 || (at > 0 && !/\s/.test(before[at - 1]))) return null;
  const q = before.slice(at + 1);
  if (/\n/.test(q)) return null;
  return { at, q };
}
function closeMention() { MP.open = false; const p = $("#mentionPop"); if (p) p.hidden = true;
  const ta = $("#input"); if (ta) { ta.setAttribute("aria-expanded", "false"); ta.removeAttribute("aria-activedescendant"); } }
function renderMention() {
  const pop = $("#mentionPop"); if (!pop) return;
  const mq = mentionQuery();
  if (!mq) return closeMention();
  const q = mq.q.toLowerCase();
  /* Filter on the name and the id — the two things a mention can be written as — not the title,
     so "@a" does not surface everyone whose job description happens to contain an "a". */
  const hits = mentionMembers().filter(b => ((b.name || "") + " " + b.id).toLowerCase().includes(q));
  if (!hits.length) return closeMention();
  MP.open = true; MP.items = hits; MP.at = mq.at;
  if (MP.idx >= hits.length) MP.idx = 0;
  pop.innerHTML = hits.map((b, i) =>
    `<div class="mi${i === MP.idx ? " on" : ""}" role="option" id="mp-i-${i}" data-i="${i}">
       <span class="av" style="background:${esc(b.color || "#7C5CFF")}">${esc((b.name || "?").trim()[0].toUpperCase())}</span>
       <span><b>${esc(b.name)}</b><div class="sub">${esc(b.title || b.role || "bot")}</div></span></div>`).join("");
  pop.hidden = false;
  /* Tell assistive tech the composer owns the open list, and which option is the highlighted one. */
  const ta = $("#input");
  if (ta) { ta.setAttribute("aria-expanded", "true"); ta.setAttribute("aria-activedescendant", "mp-i-" + MP.idx); }
  pop.querySelectorAll(".mi").forEach(el => el.onclick = () => insertMention(+el.dataset.i));
  const on = pop.querySelector(".mi.on"); if (on) on.scrollIntoView({ block: "nearest" });
}
function insertMention(i) {
  const b = MP.items[i]; if (!b) return;
  const ta = $("#input"), pos = ta.selectionStart;
  const token = "@" + b.name + " ";
  ta.value = ta.value.slice(0, MP.at) + token + ta.value.slice(pos);
  const c = MP.at + token.length;
  ta.setSelectionRange(c, c); ta.focus();
  autoGrow(ta);
  closeMention();
}
/* The composer grows with what you type, capped at a fixed height and also at a share of the viewport:
   a 140px box is fine on a desktop and most of the screen on a phone. One definition, so the two
   places that grow it cannot cap at different heights. */
const COMPOSER_MAX = 140;
const autoGrow = ta => { ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight, COMPOSER_MAX, Math.round(window.innerHeight * 0.4)) + "px"; };
$("#mentionPop").onmousedown = e => e.preventDefault();   // keep the caret where it was
$("#input").addEventListener("keydown", e => {
  /* An IME (Japanese, Chinese, Korean) uses Enter to accept the candidate it is offering, and that
     Enter arrives here like any other. Acting on it would send mid-word: the message goes out with the
     composition still open and the rest of the word lands in an empty composer. `isComposing` is the
     standard flag; 229 is the legacy keyCode some IMEs still send instead of it. */
  if (e.isComposing || e.keyCode === 229) return;
  if (MP.open) {
    if (e.key === "ArrowDown") { e.preventDefault(); MP.idx = (MP.idx + 1) % MP.items.length; return renderMention(); }
    if (e.key === "ArrowUp") { e.preventDefault(); MP.idx = (MP.idx - 1 + MP.items.length) % MP.items.length; return renderMention(); }
    if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); return insertMention(MP.idx); }
    if (e.key === "Escape") { e.preventDefault(); return closeMention(); }
  }
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});
$("#input").addEventListener("input", e => { autoGrow(e.target); renderMention(); });
/* The picker follows the caret: when the composer loses focus the list has nothing to point at, so it
   goes away. Clicking an option keeps focus (its mousedown is prevented), so this never fires there. */
$("#input").addEventListener("blur", closeMention);
document.addEventListener("click", closeCtx);
/* A resize moves the toolbar's height, so the panels' offset is re-measured alongside the menu that
   the resize invalidates anyway. */
window.addEventListener("resize", () => { closeCtx(); panelTop(); });
/* Right-clicking a row opens the same menu as its ⋯ kebab. Help documents this, so it has to work:
   a right-click that fell through to the browser's own menu was a dead end. Delegated from the two
   static containers, so the rows themselves stay free of it. */
for (const sel of ["#chans", "#bots"]) $(sel).addEventListener("contextmenu", e => {
  const row = e.target.closest("li.bot"); if (!row) return;
  e.preventDefault();
  openCtx(e, row.dataset.bot || row.dataset.id, row.dataset.kind || "channel", row.dataset.id);
});
/* Every row opens the same menu, folders included: the paths and Finder are as useful on a folder as
   on a file, and "Open" descends, which is what a click on the row already does. The `..` row is left
   out — it is the way back up, not an entry, and the parent's own path is one click away. */
$("#filesList").addEventListener("contextmenu", e => {
  const row = e.target.closest(".frow"); if (!row || row.dataset.up) return;
  e.preventDefault();
  openCtx(e, row.dataset.path, "file", S.active, row.classList.contains("dir"));
});
/* Escape dismisses whatever transient surface is open and hands focus back to the control that
   opened it. A dialog owns Escape itself (it has its own trap), so this stands down while one is up —
   Settings via its scrim, and a picker stacked over it via `.pick`. It must be `.pick` and not
   `.modal`: the Settings dialog is static markup that is in the document from the first paint, so
   matching `.modal` stood this handler down for good and Escape dismissed nothing at all. */
document.addEventListener("keydown", e => {
  if (e.key !== "Escape" || $("#scrim").classList.contains("on") || document.querySelector(".modal.pick")) return;
  /* The menu first, before the panels: it is drawn over them, and a files menu is opened from a row
     *inside* the files panel — so with the panels checked first, Escape on a menu item dismissed the
     panel underneath and left the menu floating over nothing. Topmost surface first is the rule. */
  if ($("#ctx").classList.contains("on")) {
    closeCtx();
    if (S.ctxFrom && S.ctxFrom.focus) S.ctxFrom.focus();
    return;
  }
  if ($("#comp").classList.contains("on")) { closeComp(); return $("#btnComp").focus(); }
  if ($("#files").classList.contains("on")) { closeFiles(); return $("#btnFiles").focus(); }
  /* The link panel is the one side panel with no toolbar button behind it — it opens from a link in
     the transcript — so there is no opener to hand focus back to; `closeLink` returns it to the line
     that was clicked instead. */
  if ($("#link").classList.contains("on")) { closeLink(); return; }
  if ($("#side").classList.contains("open")) { closeDrawer(); return $("#btnMenu").focus(); }
  if ($("#mmPop")) { closeModelMenu(); return $("#chipModel").focus(); }
  if ($("#apPop")) { closeApprovalMenu(); return $("#chipMem").focus(); }
  if ($(".ctxwrap.open")) { closeCtxPop(); return $("#chipCtx").focus(); }
});

/* A boot that throws after config answered (a stale session id, a server restart mid-load, one 500)
   used to leave the splash up for good: `splashOff` is the last line of `boot`, so a rejection skipped
   it and the fixed overlay — removed by nothing else — swallowed every click. Whatever went wrong, the
   app is shown and the failure is in the console. */
boot().catch(e => { console.error("boot failed:", e); splashOff(); });
