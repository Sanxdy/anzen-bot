/* Offline checks for the transcript name colour — no browser, no DOM library.

   A bot's name in the transcript is written in its own colour, so who is talking reads at a glance.
   That name is 10.5px bold, which WCAG counts as small text, so it needs 4.5:1 against whatever it
   sits on — and the six palette colours were drawn for avatars (a fill), not for text. So there are
   two things to prove and this file proves both:

     1. the resolver's rules — a bot keeps its own colour, and two members of one room never share
        one, with the later member shifted off a collision in the room's own order;
     2. the legibility of every resolved colour on every theme, measured, not eyeballed.

   The palette, the theme list, the theme tokens and the mix percentages are all read out of app.js
   and index.html rather than copied here, so a changed palette or a changed token block fails this
   check instead of quietly passing against a stale copy.

   Run: node tests/test_name_colour.mjs   (exit 0 = all green) */
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../app.js", import.meta.url), "utf8");
const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");

let pass = 0, fail = 0;
const ok = (name, cond, extra = "") => {
  if (cond) { pass++; console.log("  ok   " + name); }
  else { fail++; console.log("  FAIL " + name + (extra ? "  -> " + extra : "")); }
};

/* ---------- the palette, as app.js writes it ---------- */
const avSrc = (src.match(/const AV = \{([^}]*)\}/) || [])[1];
if (!avSrc) { console.log("FAIL could not find the AV palette in app.js"); process.exit(1); }
const AV = {};
for (const m of avSrc.matchAll(/([A-Za-z]+)\s*:\s*"(#[0-9A-Fa-f]{6})"/g)) AV[m[1]] = m[2].toUpperCase();
const AVK = Object.keys(AV);
ok("the palette is read out of app.js", AVK.length === 6, AVK.join(","));

/* ---------- the themes, as app.js writes them: [id, isLight] ---------- */
const THEMES = [];
const thSrc = (src.match(/const THEMES = \[([\s\S]*?)\n\];/) || [])[1] || "";
for (const m of thSrc.matchAll(/\[\s*"([\w-]+)"\s*,\s*"[^"]*"\s*,\s*"#[0-9A-Fa-f]+"\s*,\s*([01])\s*\]/g)) {
  THEMES.push({ id: m[1], light: +m[2] === 1 });
}
ok("all eleven themes are read out of app.js", THEMES.length === 11, String(THEMES.length));

/* ---------- every `selector{body}` block in index.html, in order ---------- */
const blocks = [...html.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(m => [m[1], m[2]]);
const tok = (body, name) => {
  const m = body.match(new RegExp("--" + name + ":\\s*(#[0-9A-Fa-f]{6})"));
  return m ? m[1].toUpperCase() : null;
};
/* A theme's token block is the first block that names it and carries `--card` — a theme may add
   character rules of its own further down, and those carry no tokens. */
const tokens = {};
for (const t of THEMES) {
  const b = blocks.find(([sel, body]) => sel.includes(`data-theme="${t.id}"`) && body.includes("--card:"));
  tokens[t.id] = b ? { card: tok(b[1], "card"), card2: tok(b[1], "card2"), bg: tok(b[1], "bg"),
    dim2: tok(b[1], "dim2") } : null;
}
const missing = THEMES.filter(t => !tokens[t.id] || !tokens[t.id].card || !tokens[t.id].card2 || !tokens[t.id].bg).map(t => t.id);
ok("every theme has a token block with --card, --card2 and --bg", missing.length === 0, missing.join(","));

/* ---------- the legibility rules, as index.html writes them ---------- */
const pct = (re, what) => { const m = html.match(re); return m ? +m[1] : (fail++, console.log("  FAIL " + what), null); };
const LIGHT_PCT = pct(/body\.light \.m \.hue\{color:color-mix\(in srgb,var\(--mc\) (\d+)%,#000\)/, "the light-theme name rule");
const DARK_PCT = pct(/body:not\(\.light\) \.m \.hue\{color:color-mix\(in srgb,var\(--mc\) (\d+)%,#fff\)/, "the dark-theme name rule");
ok("the name takes its hue from --mc", html.includes(".m .hue{color:var(--mc)}"));
ok("the name is wired to the resolver",
  src.includes("const hueOf = (name, sid)") && src.includes("const hueSpan = (name, cls, hue)"));
/* The two exemptions are read off the rules, not assumed: a theme named in the mono rule has no hue
   at all, a theme named in the glass rule has one everywhere but in a notice. */
const noHue = new Set(), noHueInNotice = new Set();
for (const m of html.matchAll(/body\[data-theme="([\w-]+)"\] \.m(\.sys)? \.hue/g)) (m[2] ? noHueInNotice : noHue).add(m[1]);

/* ---------- WCAG relative luminance and contrast ---------- */
const ch = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
const lum = h => { const x = parseInt(h.slice(1), 16);
  return 0.2126 * ch(x >> 16 & 255) + 0.7152 * ch(x >> 8 & 255) + 0.0722 * ch(x & 255); };
const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
/* `color-mix(in srgb, A p%, B)` is a lerp of the gamma-encoded components, rounded to 8 bits — the
   same arithmetic the browser does, so the ratio below is the one the pixel actually gets. */
const mix = (from, p, to) => {
  const a = parseInt(from.slice(1), 16), b = parseInt(to.slice(1), 16);
  return "#" + [16, 8, 0].map(s =>
    Math.round((a >> s & 255) * (p / 100) + (b >> s & 255) * (1 - p / 100)).toString(16).padStart(2, "0")).join("");
};
/* The colour a name is actually painted in on a theme: the dark rule lifts toward white, the light
   one darkens, and a theme in the mono rule never gets here. */
const inkFor = (hue, theme) => noHue.has(theme.id) ? null
  : mix(AV[hue], theme.light ? LIGHT_PCT : DARK_PCT, theme.light ? "#000000" : "#FFFFFF");

/* ---------- 1. the resolver's rules ----------
   `hueOf` is lifted out of app.js and run against a fake roster: this is the rule the request turns
   on — two members of one room must not read alike — so it is tested, not just read. */
const fnSrc = src.slice(src.indexOf("const hueOf = "), src.indexOf("\nconst hueSpan = "));
if (!fnSrc.includes("used.has")) { console.log("FAIL could not find the collision rule in app.js"); process.exit(1); }
const bots = [
  { id: "atlas", name: "Atlas", color: "purple" },
  { id: "scout", name: "Scout", color: "blue" },
  { id: "nova", name: "Nova", color: "pink" },
  { id: "echo", name: "Echo", color: "green" },
  { id: "pixel", name: "Pixel", color: "orange" },
  { id: "vps", name: "VPS DEV", color: "orange" },      // the real roster's collision
  { id: "loner", name: "Loner", color: "orange" },      // in the roster, not in the room
  { id: "ghost", name: "Ghost", color: "pink", hidden: true },
];
const chans = [{ id: "growth-room", name: "Social Growth Room",
  members: ["atlas", "scout", "nova", "echo", "pixel", "vps"] }];
const hueOf = new Function("bot", "chan", "S", "AVK",
  `"use strict";${fnSrc};return hueOf;`)(
  id => bots.find(b => b.id === id), id => chans.find(c => c.id === id), { bots }, AVK);

ok("a bot keeps its own colour", hueOf("Atlas", "growth-room") === "purple" && hueOf("Nova", "growth-room") === "pink");
ok("two members with one colour do not both keep it",
  hueOf("Pixel", "growth-room") === "orange" && hueOf("VPS DEV", "growth-room") !== "orange",
  "Pixel=" + hueOf("Pixel", "growth-room") + " VPS DEV=" + hueOf("VPS DEV", "growth-room"));
ok("the later member takes the first entry nobody before it is using",
  hueOf("VPS DEV", "growth-room") === "yellow", String(hueOf("VPS DEV", "growth-room")));
const hues = chans[0].members.map(id => hueOf(bots.find(b => b.id === id).name, "growth-room"));
ok("every name in the room is distinct", new Set(hues).size === hues.length, hues.join(","));
ok("the room is stable across redraws",
  hues.join(",") === chans[0].members.map(id => hueOf(bots.find(b => b.id === id).name, "growth-room")).join(","));
ok("a hidden bot is not in the room's order", hueOf("Ghost", "growth-room") === "pink");
ok("a bot outside the room keeps its own colour", hueOf("Loner", "growth-room") === "orange");
ok("a chat with no room keeps the bot's own colour", hueOf("VPS DEV", "chat-1") === "orange");
ok("a name that matches no bot has no colour", hueOf("Someone Else", "growth-room") === null);
ok("an empty name has no colour", hueOf("", "growth-room") === null && hueOf(null, "growth-room") === null);

/* ---------- 3. the hand-off notice, where the name goes in as markup ----------
   `addCard(..., "text")` hands mdToHtml a pre-escaped string, which is the one new risk in the
   wiring: the markdown pass must leave the name's own span alone rather than escape it into
   visible text. `esc` and the markdown block are lifted out of app.js and run here for real. */
const escEnd = src.indexOf("\n", src.indexOf("const esc = "));
const mdSrc = src.slice(src.indexOf("const esc = "), escEnd) + "\n"
  + src.slice(src.indexOf("const safeHref = "), src.indexOf("\nconst S = {"));
const mdToHtml = new Function(`${mdSrc};return mdToHtml;`)();
const notice = mdToHtml(`▸ <span class="hue" style="--mc:#7C5CFF">Atlas</span> started: fix &amp; ship — its steps are in Atlas's chat`, true);
ok("a hand-off notice keeps the name's span", notice.includes('<span class="hue" style="--mc:#7C5CFF">Atlas</span>'));
ok("a hand-off notice does not print the span as text", !notice.includes("&lt;span"));
ok("a hand-off notice still escapes what it quotes", notice.includes("fix &amp; ship"));

/* ---------- 2. the contrast, for every theme and every colour ---------- */
console.log("");
console.log("  contrast of a resolved name (10.5px bold -> 4.5:1) against its theme's message surfaces");
console.log("  surfaces: bubble --card, plan/report card --card2, notice --bg");
console.log("");
const worst = { r: Infinity, at: "" };
for (const t of THEMES) {
  const s = tokens[t.id];
  if (!s) continue;
  const cells = [], exempt = [];
  for (const k of AVK) {
    const ink = inkFor(k, t);
    if (!ink) { exempt.push(k); continue; }
    const r = Math.min(ratio(ink, s.card), ratio(ink, s.card2), ratio(ink, s.bg));
    if (r < worst.r) { worst.r = r; worst.at = t.id + "/" + k; }
    cells.push(`${k} ${r.toFixed(2)}${r >= 4.5 ? "" : " <<< UNDER 4.5"}`);
  }
  const mark = exempt.length ? `EXEMPT (no hue: ${exempt.join(",")})` : "PASS";
  console.log("  " + t.id.padEnd(15) + cells.join("  ") + (exempt.length ? "" : "") + "   " + mark);
  if (!exempt.length) ok(`every colour clears 4.5:1 on ${t.id}`, cells.every(c => !c.includes("UNDER")));
}
console.log("");
ok("the tightest ratio anywhere is at least 4.5:1", worst.r >= 4.5, `${worst.at} at ${worst.r.toFixed(2)}:1`);
console.log(`  the tightest ratio is ${worst.r.toFixed(2)}:1 (${worst.at})`);

/* The exemptions, asserted rather than skipped: each one is named, and the rule that makes it is
   proved to be the rule that is written down. */
console.log("");
ok("mono and mono-light are the themes with no hue by design", noHue.has("mono") && noHue.has("mono-light"),
  [...noHue].join(","));
ok("their names keep --dim, the colour they have always had",
  /body\[data-theme="mono"\] \.m \.hue,body\[data-theme="mono-light"\] \.m \.hue\{color:var\(--dim\) !important\}/.test(html));
ok("only the two glass themes exempt a name in a notice", noHueInNotice.has("glass") && noHueInNotice.has("glass-light")
  && noHueInNotice.size === 2, [...noHueInNotice].join(","));
ok("that notice keeps --dim2, the colour it has always had", html.includes("body[data-theme=\"glass\"] .m.sys .hue"));

/* The glass themes read the transcript through a translucent pane over an animated wash, so a name in
   a notice reads over something that moves. Those rows get a plate of their own base — see the rule in
   index.html — but the plate is 88% opaque, so the wash still reaches the words; this is measured at
   the worst place the wash can put them: a bloom centre, the lightest a dark theme's base gets and the
   darkest a light one's. A name in a bubble is unaffected — bubbles are solid, and the table above is
   what holds for them. */
const over = (fg, a, bg) => { const f = parseInt(fg.slice(1), 16), b = parseInt(bg.slice(1), 16);
  return "#" + [16, 8, 0].map(s => Math.round((f >> s & 255) * a + (b >> s & 255) * (1 - a)).toString(16).padStart(2, "0")).join(""); };
const washCase = (id, accent) => {
  const s = tokens[id];
  const msgs = over(s.bg, 0.46, over(accent, 0.85, s.bg));   // #msgs, over the strongest bloom
  /* What the name is painted in here is `--dim2`, not `--dim` — the rule that keeps a name in a notice
     off the hue names that token, and a check reading the other one under-reports the ratio. */
  const dim2 = s.dim2;
  const rows = AVK.map(k => `${k} ${ratio(mix(AV[k], THEMES.find(t => t.id === id).light ? LIGHT_PCT : DARK_PCT,
    THEMES.find(t => t.id === id).light ? "#000000" : "#FFFFFF"), msgs).toFixed(2)}`);
  console.log(`  ${id}: notice background over the strongest bloom is ${msgs}`);
  console.log(`    coloured name would be: ${rows.join("  ")}`);
  console.log(`    the --dim2 it keeps instead: ${dim2} -> ${ratio(dim2, msgs).toFixed(2)}:1 (the same rule already measured it below 4.5 there)`);
  return { msgs, dimRatio: ratio(dim2, msgs) };
};
console.log("");
const wg = washCase("glass", "#8AB4FF");
const wgl = washCase("glass-light", "#2A62F0");
ok("the glass exemption is a real limitation, not a tidy-up", wg.dimRatio < 4.5 && wgl.dimRatio < 4.5,
  `${wg.dimRatio.toFixed(2)} / ${wgl.dimRatio.toFixed(2)}`);
console.log("  the exemption is stated, not silent: a name in a notice keeps its dim on these two themes only,");
console.log("  and every coloured name in a bubble on them is in the table above and clears 4.5:1.");

/* ---------- 4. the live strip above the composer ----------
   A name in the strip is the same name, so it takes the same `--mc` and the same two measured
   percentages. Those percentages are the one thing that can silently drift — they are written a
   second time, for a selector that is not a `.m` — so they are read back here and held to the
   transcript's. The strip's surface is the row's own solid `--card`, which is what lets every theme
   be measured here instead of exempted: a row is not a notice with no background of its own. */
console.log("");
const stripPct = (re, what) => { const m = html.match(re); return m ? +m[1] : (fail++, console.log("  FAIL " + what), null); };
const S_LIGHT_PCT = stripPct(/body\.light \.working \.hue\{color:color-mix\(in srgb,var\(--mc\) (\d+)%,#000\)/, "the strip's light-theme name rule");
const S_DARK_PCT = stripPct(/body:not\(\.light\) \.working \.hue\{color:color-mix\(in srgb,var\(--mc\) (\d+)%,#fff\)/, "the strip's dark-theme name rule");
ok("the strip's name mixes at the transcript's own percentages",
  S_LIGHT_PCT === LIGHT_PCT && S_DARK_PCT === DARK_PCT, `${S_LIGHT_PCT}/${S_DARK_PCT} vs ${LIGHT_PCT}/${DARK_PCT}`);
ok("the strip's name takes its hue from --mc too", html.includes(".working .hue{color:var(--mc)}"));
const stripNoHue = new Set();
for (const m of html.matchAll(/body\[data-theme="([\w-]+)"\] \.working \.hue/g)) stripNoHue.add(m[1]);
ok("the strip goes grey on exactly the two themes the transcript does",
  stripNoHue.size === 2 && stripNoHue.has("mono") && stripNoHue.has("mono-light"), [...stripNoHue].join(","));
/* The strip is exempted nowhere, and that is only safe because of the row's own surface: if a glass
   theme were ever added to a strip rule, a name there would have no background left to measure. */
ok("no theme exempts a name in the strip", !/data-theme="glass[^"]*"\] \.working/.test(html));

console.log("  contrast of a strip name (12px bold -> 4.5:1) against the row's own --card");
const stripWorst = { r: Infinity, at: "" };
for (const t of THEMES) {
  const s = tokens[t.id];
  if (!s) continue;
  if (stripNoHue.has(t.id)) { console.log("  " + t.id.padEnd(15) + "keeps --dim (no hue by design)"); continue; }
  const cells = [];
  for (const k of AVK) {
    const ink = mix(AV[k], t.light ? S_LIGHT_PCT : S_DARK_PCT, t.light ? "#000000" : "#FFFFFF");
    const r = ratio(ink, s.card);
    if (r < stripWorst.r) { stripWorst.r = r; stripWorst.at = t.id + "/" + k; }
    cells.push(`${k} ${r.toFixed(2)}${r >= 4.5 ? "" : " <<< UNDER 4.5"}`);
  }
  console.log("  " + t.id.padEnd(15) + cells.join("  "));
  ok(`every strip name clears 4.5:1 on ${t.id}`, cells.every(c => !c.includes("UNDER")));
}
ok("the tightest strip ratio is at least 4.5:1", stripWorst.r >= 4.5, `${stripWorst.at} at ${stripWorst.r.toFixed(2)}:1`);
console.log(`  the tightest strip ratio is ${stripWorst.r.toFixed(2)}:1 (${stripWorst.at}) — the same full-strength ink, on a surface of its own`);

/* ---------- 5. the pulse ----------
   What pulses is a halo behind the glyphs, never the glyphs' own paint, so the ratios above are the
   ratios *while* it pulses. That is the choice, and the floor printed below is why: an opacity pulse
   would have to stay above it to hold 4.5:1 anywhere, and a name that may only dim by a tenth is not
   a name anybody can see flashing. */
const alphaFloor = (hue, t) => {
  const ink = inkFor(hue, t); if (!ink) return null;
  let lo = 0, hi = 1;
  for (let i = 0; i < 40; i++) { const mid = (lo + hi) / 2; (ratio(over(ink, mid, tokens[t.id].card), tokens[t.id].card) >= 4.5 ? hi = mid : lo = mid); }
  return hi;
};
let floorMax = 0, floorAt = "";
for (const t of THEMES) for (const k of AVK) {
  const f = alphaFloor(k, t);
  if (f != null && f > floorMax) { floorMax = f; floorAt = t.id + "/" + k; }
}
console.log("");
ok("a dimmed name would have to stay so bright that no flash is left in it", floorMax > 0.85, floorMax.toFixed(4));
console.log(`  an opacity pulse could dim a name no further than ${floorMax.toFixed(3)} (${floorAt}) and still clear 4.5:1`);
console.log(`  -> a dip of ${(100 - floorMax * 100).toFixed(1)}%, which is why the pulse moves a halo and leaves the paint alone`);

ok("the pulse animates a text-shadow, and nothing that carries the text's own paint",
  /@keyframes livepulse\{from\{text-shadow:[^}]*\}\s*to\{text-shadow:[^}]*currentColor/.test(html)
  && !/\.working \.wname\{[^}]*opacity/.test(html));
const pulse = html.match(/\.working \.wname\{[^}]*animation:livepulse ([\d.]+)s/);
ok("the pulse breathes no faster than once a second", !!pulse && +pulse[1] >= 1, pulse ? pulse[1] + "s" : "no animation found");
ok("reduced motion turns the pulse off, leaving the clock and the phase word to say the row is live",
  /@media \(prefers-reduced-motion:reduce\)\{\.working \.wname\{animation:none\}\}/.test(html));

/* ---------- 6. the monogram ----------
   The avatar's monogram is the same hue as the name, so it is the same two rules that keep it legible
   — and it needs its own table, because the surface under it is not the same one: the monogram paints
   the hue on the avatar's own `--card2`, not on the bubble's `--card`. The two percentages are read
   back out of index.html and held to the transcript's, exactly as the strip's are, so a rule that
   drifts shows up in all three places. Monochrome greyscales the monogram with `filter:grayscale(1)`,
   which is the luminance matrix — a grey of the same relative luminance — so the ratio measured on
   the colour is the ratio the grey pixel gets, and no theme is exempt from this table. */
console.log("");
const mcLightPct = pct(/body\.light \.mc:not\(\.img\)\{color:color-mix\(in srgb,var\(--mc\) (\d+)%,#000\)/, "the monogram's light-theme rule");
const mcDarkPct = pct(/body:not\(\.light\) \.mc:not\(\.img\)\{color:color-mix\(in srgb,var\(--mc\) (\d+)%,#fff\)/, "the monogram's dark-theme rule");
ok("the monogram mixes at the transcript's own percentages",
  mcLightPct === LIGHT_PCT && mcDarkPct === DARK_PCT, `${mcLightPct}/${mcDarkPct} vs ${LIGHT_PCT}/${DARK_PCT}`);
ok("the monogram takes its hue from --mc, and only for the drawn monogram",
  /body\.light \.mc:not\(\.img\)\{/.test(html) && /body:not\(\.light\) \.mc:not\(\.img\)\{/.test(html));
console.log("  contrast of a monogram (15px bold -> 4.5:1) against the avatar's own --card2");
const mcWorst = { r: Infinity, at: "" };
for (const t of THEMES) {
  const s = tokens[t.id];
  if (!s) continue;
  const cells = [];
  for (const k of AVK) {
    const ink = mix(AV[k], t.light ? mcLightPct : mcDarkPct, t.light ? "#000000" : "#FFFFFF");
    const r = ratio(ink, s.card2);
    if (r < mcWorst.r) { mcWorst.r = r; mcWorst.at = t.id + "/" + k; }
    cells.push(`${k} ${r.toFixed(2)}${r >= 4.5 ? "" : " <<< UNDER 4.5"}`);
  }
  console.log("  " + t.id.padEnd(15) + cells.join("  "));
  ok(`every monogram clears 4.5:1 on ${t.id}`, cells.every(c => !c.includes("UNDER")));
}
ok("the tightest monogram ratio is at least 4.5:1", mcWorst.r >= 4.5, `${mcWorst.at} at ${mcWorst.r.toFixed(2)}:1`);
console.log(`  the tightest monogram ratio is ${mcWorst.r.toFixed(2)}:1 (${mcWorst.at})`);

console.log("");
console.log(`${pass} ok, ${fail} failed`);
process.exit(fail ? 1 : 0);
