package io.anzenbot.app;

/**
 * The companion's colours — the same dark the desktop shell wears, so the phone and the computer
 * read as one product rather than a phone app bolted onto a computer one.
 */
final class Pal {
    private Pal() { }

    static final int BG     = 0xFF0E1116;   // the page behind everything
    static final int CARD   = 0xFF171C24;   // a raised surface: a row, a tool card, the composer
    static final int LINE   = 0xFF232A36;   // hairlines and card edges
    static final int FG     = 0xFFE6EAF2;   // body text
    static final int DIM    = 0xFF8A93A6;   // labels, meta, the last thing said
    static final int FAINT  = 0xFF5A6478;   // the least important line on a screen
    static final int ACCENT = 0xFF5B8DEF;   // the live dot, the primary button, your own messages
    static final int USER   = 0xFF1B2740;   // your own bubble, a step off the accent
    static final int WARN   = 0xFFE0A34A;   // an approval, a refusal worth reading
    static final int ERR    = 0xFFE06C6C;   // a turn that failed
}
