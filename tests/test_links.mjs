/* Offline checks for links in a transcript — no browser, no DOM library.

   A bot writes URLs bare. Every transcript on this machine holds hundreds of them and not one
   markdown link, so before this nothing in a reply was clickable: the text said
   `https://www.threads.com/@zenpilot.2026/post/...` and there was no way to open it.

   Two things are pinned here. (1) The autolinker's edges, which are where a naive `https?://\S+`
   goes wrong: the full stop that ends a sentence is not part of the URL, a bracket the URL opened
   is, a query string survives escaping, a URL already inside a markdown link or a code span is left
   alone, and `javascript:` is never a link. (2) The click route — the transcript's links open the
   side panel rather than navigating the window away, which for a `file://` shell would replace the
   whole app.

   `inlineMd` lives in app.js, an ES module that boots the whole UI and cannot be imported here, so
   the block is read out of the source and run against the real `esc`. If the extraction ever stops
   matching, these checks fail rather than pass on nothing.

   Run: node tests/test_links.mjs   (exit 0 = all green) */
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../app.js", import.meta.url), "utf8");
const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");

let pass = 0, fail = 0;
const ok = (name, cond, extra = "") => {
  if (cond) { pass++; console.log("  ok   " + name); }
  else { fail++; console.log("  FAIL " + name + (extra ? "  -> " + extra : "")); }
};

const slice = (from, to) => {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0 || b < a) { console.log("FAIL could not find " + from + " in app.js"); process.exit(1); }
  return src.slice(a, b);
};
const escSrc = src.match(/^const esc = .*$/m);
if (!escSrc) { console.log("FAIL could not find esc in app.js"); process.exit(1); }
const mdSrc = slice("const safeHref =", "function mdToHtml(");

const L = new Function(escSrc[0] + "\n" + mdSrc + "\nreturn { inlineMd, linkify, trimUrl, safeHref, BARE_URL, esc };")();
const md = raw => L.inlineMd(L.esc(raw));   // what mdToHtml hands inlineMd: text escaped first

/* ---------- a bare URL is linked at all ---------- */
const one = md("see https://example.com/a/b for the report");
ok("a bare URL becomes an anchor", /<a class="lnk" href="https:\/\/example\.com\/a\/b"/.test(one), one);
ok("...and the words around it survive", one.startsWith("see ") && one.endsWith(" for the report"), one);
ok("...and the anchor opens safely", /target="_blank"/.test(one) && /rel="noopener noreferrer"/.test(one), one);

/* ---------- the punctuation a sentence puts after a URL is not the URL ---------- */
const dot = md("Read https://example.com/x.");
ok("a full stop ending the sentence is not linked", dot.includes('href="https://example.com/x"'), dot);
ok("...and the full stop is still shown", /<\/a>\.$/.test(dot), dot);
ok("a comma is not linked", md("a https://x.com/p, b").includes('href="https://x.com/p"'));
ok("a closing bracket after a bare URL is not linked", md("(see https://x.com/p)").includes('href="https://x.com/p"'));
ok("...but a bracket the URL opened is kept",
   md("https://en.wikipedia.org/wiki/Heat_(1995_film)").includes('href="https://en.wikipedia.org/wiki/Heat_(1995_film)"'));
ok("a query string survives the escape pass", md("https://x.com/?a=1&b=2").includes('href="https://x.com/?a=1&amp;b=2"'),
   md("https://x.com/?a=1&b=2"));

/* ---------- a URL that is already something else stays that something else ---------- */
const code = md("run `curl https://x.com/p` now");
ok("a URL inside a code span is not a link", !/<a /.test(code) && code.includes("<code>curl https://x.com/p</code>"), code);
const mlink = md("[the docs](https://x.com/p)");
ok("a markdown link is not double-linked", (mlink.match(/<a /g) || []).length === 1, mlink);
ok("...and keeps its own text", mlink.includes(">the docs</a>"), mlink);
ok("a URL inside bold is still linked", md("**https://x.com/p**").includes('href="https://x.com/p"'));
ok("two URLs on one line both link", (md("https://a.com/1 and https://b.com/2").match(/<a /g) || []).length === 2);
ok("a URL glued to a word is not linked", !/<a /.test(md("xhttps://y.com")), md("xhttps://y.com"));

/* ---------- schemes ---------- */
ok("javascript: is never an href", !/href="javascript:/i.test(md("[x](javascript:alert(1))")));
ok("...and renders as an inert anchor", md("[x](javascript:alert(1))").includes('href="#"'));
ok("mailto: survives in a markdown link", md("[mail](mailto:a@b.com)").includes('href="mailto:a@b.com"'));
ok("a bare mailto: is not autolinked", !/<a /.test(md("write to mailto:a@b.com")));

/* ---------- a person's own text ---------- */
const mine = L.linkify("curl https://x.com/a *not italic* https://y.com/b");
ok("a URL the reader typed is linked", (mine.match(/<a /g) || []).length === 2, mine);
ok("...and the rest of their text stays literal", mine.includes("*not italic*") && !/<em>/.test(mine), mine);
ok("...and their text is still escaped", L.linkify("<script>x</script>").includes("&lt;script&gt;"), L.linkify("<script>x</script>"));

/* ---------- the panel the links open into ---------- */
ok("the link panel is in the shell", /<aside id="link" class="sidepanel"/.test(html));
ok("...with a back button, an external escape and a close",
   /id="linkBack"/.test(html) && /id="linkOut"/.test(html) && /id="linkClose"/.test(html));
ok("...and a body the frame is built into", /id="linkBody"/.test(html));
ok("the panel starts out of reach", /<aside id="link" class="sidepanel" aria-label="Link panel" inert>/.test(html));
ok("the transcript delegates clicks on its links",
   /\$\("#msgs"\)\.addEventListener\("click"/.test(src) && /closest\("#msgs a\[href\]"\)/.test(src));
ok("a modified click is left to the browser", /e\.metaKey \|\| e\.ctrlKey \|\| e\.shiftKey \|\| e\.altKey/.test(src));
ok("Escape closes the link panel", /\$\("#link"\)\.classList\.contains\("on"\)\) \{ closeLink\(\)/.test(src));
ok("a press outside closes it too", /inside\(e, "#comp, #files, #link, #btnComp, #btnFiles, #ctx"\)/.test(src));
ok("a link press does not close and reopen the panel",
   /e\.target\.closest\("#msgs a\[href\]"\)\) return;/.test(src));
const main = readFileSync(new URL("../desktop/electron/main.js", import.meta.url), "utf8");
ok("the desktop shell enables the embedded browser", /webviewTag: true/.test(main));
ok("...and trims every webview to http(s) with no Node",
   /will-attach-webview/.test(main) && /delete prefs\.preload/.test(main)
   && /prefs\.nodeIntegration = false/.test(main)
   && /test\(params\.src \|\| ['"]{2}\)\) e\.preventDefault\(\)/.test(main));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
