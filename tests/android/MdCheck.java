package io.anzenbot.app;

import java.util.List;

/**
 * The markdown a bot answers in, checked against the desktop renderer it was ported from.
 *
 * A reply that shows literal asterisks reads as the bot's fault, not the client's, so the parser is
 * the half of the phone's chat view most worth checking here. Md imports nothing from android, so it
 * is compiled and run on a plain JVM against the same text the server sends. See tests/test_android.py.
 */
public class MdCheck {
    static int pass = 0, fail = 0;

    static void ok(String name, boolean cond, Object got) {
        if (cond) { pass++; System.out.println("  PASS " + name); }
        else { fail++; System.out.println("  FAIL " + name + "  got: " + got); }
    }

    static void ok(String name, boolean cond) { ok(name, cond, ""); }

    public static void main(String[] a) {
        inline();
        bareLinks();
        blocks();
        System.out.println("\n" + pass + " passed, " + fail + " failed");
        if (fail > 0) System.exit(1);
    }

    static String kinds(List<Md.Seg> segs) {
        StringBuilder b = new StringBuilder();
        for (Md.Seg s : segs) { if (b.length() > 0) b.append(","); b.append(s.kind); }
        return b.toString();
    }

    static Md.Seg firstLink(List<Md.Seg> segs) {
        for (Md.Seg s : segs) if (s.kind == 5) return s;
        return null;
    }

    static String bkinds(List<Md.Blk> blocks) {
        StringBuilder b = new StringBuilder();
        for (Md.Blk x : blocks) { if (b.length() > 0) b.append(","); b.append(x.kind); }
        return b.toString();
    }

    // ---- one line of a reply ------------------------------------------------------------------

    static void inline() {
        System.out.println("Md.segs — inline");

        List<Md.Seg> b = Md.segs("say **hi** now");
        ok("bold is a span of its own", b.size() == 3 && b.get(1).kind == 1, kinds(b));
        ok("...with the markers gone", "hi".equals(b.get(1).text), b.get(1).text);
        ok("...and the words around it kept",
           "say ".equals(b.get(0).text) && " now".equals(b.get(2).text), kinds(b));

        // The bug report, verbatim: a reply saying **nothing** showed the asterisks.
        List<Md.Seg> nothing = Md.segs("there is **nothing** here");
        ok("**nothing** renders as bold", nothing.size() == 3 && nothing.get(1).kind == 1
           && "nothing".equals(nothing.get(1).text), kinds(nothing));
        boolean star = false;
        for (Md.Seg s : nothing) star = star || s.text.indexOf('*') >= 0;
        ok("...and no literal asterisk is left on the line", !star, nothing.get(0).text);

        List<Md.Seg> em = Md.segs("an *em* word");
        ok("italic is a span of its own", em.size() == 3 && em.get(1).kind == 2 && "em".equals(em.get(1).text), kinds(em));

        List<Md.Seg> strike = Md.segs("~~gone~~");
        ok("strike is a span of its own", strike.size() == 1 && strike.get(0).kind == 3
           && "gone".equals(strike.get(0).text), kinds(strike));

        // The reason code spans are lifted out first: the asterisks are code, not emphasis.
        List<Md.Seg> code = Md.segs("run `a*b*c` now");
        ok("code is lifted out before the asterisks are read", code.size() == 3 && code.get(1).kind == 4
           && "a*b*c".equals(code.get(1).text), kinds(code));

        List<Md.Seg> link = Md.segs("see [docs](https://x.dev)");
        ok("a link keeps its label and its url", link.size() == 2 && link.get(1).kind == 5
           && "docs".equals(link.get(1).text) && "https://x.dev".equals(link.get(1).href), link.get(1).href);

        List<Md.Seg> bad = Md.segs("[x](javascript:alert)");
        ok("a javascript: url is not a url", bad.size() == 1 && "#".equals(bad.get(0).href), bad.get(0).href);
        ok("...but its label is still shown", "x".equals(bad.get(0).text), bad.get(0).text);

        List<Md.Seg> mid = Md.segs("2*3*4");
        ok("an asterisk inside a word is not italic", mid.size() == 1 && mid.get(0).kind == 0, kinds(mid));

        List<Md.Seg> open = Md.segs("a **b");
        ok("an unclosed marker stays literal", open.size() == 1 && "a **b".equals(open.get(0).text), kinds(open));
    }

    // ---- a url a bot just wrote, with no markdown around it -----------------------------------

    static void bareLinks() {
        System.out.println("\nMd.segs — a bare url");

        // The transcripts hold hundreds of bare urls and not one markdown link, so this pass decides
        // whether anything a bot writes is tappable at all.
        List<Md.Seg> b = Md.segs("see https://x.dev now");
        Md.Seg l = firstLink(b);
        ok("a bare url becomes a link", b.size() == 3 && l != null && "https://x.dev".equals(l.href),
           l == null ? "no link" : l.href);
        ok("...with the words around it kept",
           "see ".equals(b.get(0).text) && " now".equals(b.get(2).text), kinds(b));

        // "see https://x.dev." must not link the full stop — and must not drop it either.
        List<Md.Seg> dot = Md.segs("see https://x.dev.");
        Md.Seg dl = firstLink(dot);
        ok("a sentence's full stop is not part of the url", dl != null && "https://x.dev".equals(dl.href),
           dl == null ? "no link" : dl.href);
        ok("...and is still shown", dot.get(dot.size() - 1).text.endsWith("."),
           dot.get(dot.size() - 1).text);

        // A bracket the url opened itself is its own; a bracket that merely followed it is not.
        List<Md.Seg> wiki = Md.segs("https://en.wikipedia.org/wiki/X_(film)");
        Md.Seg wl = firstLink(wiki);
        ok("a bracket the url opened stays in it",
           wl != null && "https://en.wikipedia.org/wiki/X_(film)".equals(wl.href),
           wl == null ? "no link" : wl.href);

        List<Md.Seg> paren = Md.segs("(see https://x.dev)");
        Md.Seg pl = firstLink(paren);
        ok("a bracket that merely ends the sentence is not swallowed",
           pl != null && "https://x.dev".equals(pl.href), pl == null ? "no link" : pl.href);

        // Lifted first, so the url inside it is code, not a link.
        List<Md.Seg> code = Md.segs("run `https://x.dev`");
        ok("a url inside a code span stays code", code.size() == 2 && code.get(1).kind == 4
           && firstLink(code) == null, kinds(code));

        // A markdown link was lifted before this pass, so it cannot be linked a second time.
        List<Md.Seg> md = Md.segs("[docs](https://x.dev)");
        ok("a markdown link is not linked twice", md.size() == 1 && md.get(0).kind == 5
           && "docs".equals(md.get(0).text), kinds(md));

        // A person's own text: no markdown at all, but a url they typed is still a url.
        List<Md.Seg> me = Md.literal("run *this* at https://x.dev");
        Md.Seg ml = firstLink(me);
        ok("a typed url is linked", ml != null && "https://x.dev".equals(ml.href),
           ml == null ? "no link" : ml.href);
        ok("...and the asterisks are left alone", me.get(0).text.indexOf('*') >= 0, me.get(0).text);

        List<Md.Seg> plain = Md.literal("a * b");
        ok("text with no url is one plain span", plain.size() == 1 && plain.get(0).kind == 0, kinds(plain));

        List<Md.Seg> js = Md.literal("javascript:alert(1)");
        ok("a non-http scheme is not linked", firstLink(js) == null, kinds(js));
    }

    // ---- a reply, block by block --------------------------------------------------------------

    static void blocks() {
        System.out.println("\nMd.blocks — block");

        List<Md.Blk> p = Md.blocks("just words");
        ok("a line of prose is one paragraph", p.size() == 1 && p.get(0).kind == Md.P
           && "just words".equals(p.get(0).text), bkinds(p));

        List<Md.Blk> nl = Md.blocks("line one\nline two");
        ok("a single newline survives inside the paragraph", nl.size() == 1
           && "line one\nline two".equals(nl.get(0).text), bkinds(nl));

        List<Md.Blk> two = Md.blocks("first\n\nsecond");
        ok("a blank line ends a paragraph", two.size() == 2 && two.get(0).kind == Md.P
           && two.get(1).kind == Md.P, bkinds(two));

        List<Md.Blk> h = Md.blocks("### Three");
        ok("a heading is a heading", h.size() == 1 && h.get(0).kind == Md.H, bkinds(h));
        ok("...at its own depth", h.get(0).level == 3, h.get(0).level);
        ok("...with the hashes gone", "Three".equals(h.get(0).text), h.get(0).text);

        List<Md.Blk> fence = Md.blocks("```python\nprint(1)\n```");
        ok("a fence is a code block", fence.size() == 1 && fence.get(0).kind == Md.CODE, bkinds(fence));
        ok("...named by its info string", "python".equals(fence.get(0).lang), fence.get(0).lang);
        ok("...holding the body without the fence", "print(1)".equals(fence.get(0).text), fence.get(0).text);

        List<Md.Blk> unterminated = Md.blocks("```\nstill code");
        ok("an unterminated fence runs to the end", unterminated.size() == 1
           && unterminated.get(0).kind == Md.CODE && "still code".equals(unterminated.get(0).text),
           bkinds(unterminated));

        List<Md.Blk> ul = Md.blocks("- a\n- b\n- c");
        ok("three bullets are one list", ul.size() == 1 && ul.get(0).kind == Md.UL, bkinds(ul));
        ok("...a line per item", "a\nb\nc".equals(ul.get(0).text), ul.get(0).text);
        ok("...with no start number", ul.get(0).level == 0, ul.get(0).level);

        List<Md.Blk> ol = Md.blocks("3. three\n4. four");
        ok("a numbered list is an ordered list", ol.size() == 1 && ol.get(0).kind == Md.OL, bkinds(ol));
        ok("...that remembers where it started", ol.get(0).level == 3, ol.get(0).level);
        ok("...with the numbers stripped", "three\nfour".equals(ol.get(0).text), ol.get(0).text);

        List<Md.Blk> q = Md.blocks("> first\n> second");
        ok("two quoted lines are one quote", q.size() == 1 && q.get(0).kind == Md.QUOTE, bkinds(q));
        ok("...with the markers gone", "first\nsecond".equals(q.get(0).text), q.get(0).text);

        List<Md.Blk> t = Md.blocks("| h1 | h2 |\n|---|---|\n| a | b |\n| c | d |");
        ok("a header and its separator are a table", t.size() == 1 && t.get(0).kind == Md.TABLE, bkinds(t));
        ok("...header first, then a row per line", "h1\th2\na\tb\nc\td".equals(t.get(0).text), t.get(0).text);

        List<Md.Blk> hr = Md.blocks("---");
        ok("a rule is a rule", hr.size() == 1 && hr.get(0).kind == Md.HR, bkinds(hr));
    }
}
