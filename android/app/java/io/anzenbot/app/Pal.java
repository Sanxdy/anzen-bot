package io.anzenbot.app;

/**
 * The companion's colours — the desktop shell's own tokens, so the phone and the computer read as
 * one product rather than a phone app bolted onto a computer one.
 *
 * These are the names the CSS uses (`index.html`, `:root, body[data-theme=…]`), and the values are
 * its values verbatim. Anything the stylesheet computes with `color-mix()` is computed here, with
 * the mix written beside it, because the phone has no `color-mix`.
 *
 * The desktop ships eleven themes; the phone ships the seven it can be honest about. {@link #apply}
 * swaps the token set, and {@link #FS} scales every size, so one call repaints the whole app. The
 * four themes left out are left out on purpose: Liquid Glass and Liquid Glass Light are a translucent
 * pane over an iridescent wash with a backdrop blur, and `RenderEffect` (API 31) blurs a view's own
 * content, not what is behind it — the flat fallback would be a plainer theme wearing the name.
 * Monochrome is honest only once the avatars go grey with it.
 */
final class Pal {
    private Pal() { }

    // ---- the tokens, one set per theme ------------------------------------------------------
    static int BG, BG2, CARD, CARD2, LINE, LINE2, TXT, DIM, DIM2,
               ACCENT, ACCENT_INK, ACCENT_TXT, OK, WARN, ERR, HOV, DOT;

    // ---- what the stylesheet mixes, mixed here ----------------------------------------------
    static int USER_BG, USER_LINE, MTS, FOCUS;

    // ---- the fixed label colours, straight from the stylesheet ------------------------------
    static final int PLAN_WHO  = 0xFFB9A6FF; // .m.plan .who
    static final int FINAL_WHO = 0xFF7FE3B6; // .m.final .who
    static final int TOOL_WHO  = 0xFF8FBEFF; // .m.tool .who
    static final int TOOL_HEAD = 0xFFD3D7E2; // .m.tool .h
    static final int TOOL_OUT  = 0xFFC3D0DE; // .m.tool pre.out
    static final int SHOT_WHO  = 0xFFFFB4D1; // .m.shot .who
    static final int APPR_CMD  = 0xFFE8D9B0; // .approval code
    static final int STOP_INK  = 0xFF2A0206; // .btn.stop
    static final int ALLOW_INK = 0xFF04261A; // .btn.allow

    /** The avatar palette (`AV` in app.js): the flat fills a bot's monogram tile is tinted with. */
    static final int[] AV = { 0xFF7C5CFF, 0xFF38BDF8, 0xFF2EC4A0, 0xFFF29B38, 0xFFEAB308, 0xFFEC4899 };

    /** The one theme this client opens with when nothing has been chosen. */
    static final String DEFAULT_THEME = "dark";

    /** Every theme the phone can be honest about: id, label, and whether it reads on a light
        surface. The desktop's own list (`THEMES`, app.js:443) with the four it cannot honour cut. */
    static final String[][] THEMES = {
        { "dark",           "Dark",            "0" },
        { "light",          "Light",           "1" },
        { "ainative",       "AI-Native UI",    "0" },
        { "ainative-light", "AI-Native Light", "1" },
        { "luxe",           "Dark Luxe",       "0" },
        { "eink",           "E-Ink / Paper",   "1" },
        { "terminal",       "Terminal Hacker", "0" },
    };

    /** The desktop's font grid (`FONT_SIZES`/`BASE_FONT_PX`, server.py:184) and the picker that
        snaps a chosen size to it. `--fs` in the stylesheet is this ratio. */
    static final float BASE_PX = 14.5f;
    static final float[] SIZES = { 12.5f, 13.5f, 14.5f, 15.5f, 16.5f, 17.5f, 18.5f };

    /** Every font size in the app is its designed value times this. */
    static float FS = 1f;

    /** A size as this theme and this font-size setting want it. */
    static float fs(float sp) { return sp * FS; }

    /** The size a chosen value snaps to, then divided by the base — the desktop's `gridSize`. */
    static float ratio(Object chosen) {
        float px = (float) Json.dbl(chosen);
        if (px <= 0) return 1f;
        float best = SIZES[0];
        for (float s : SIZES) if (Math.abs(s - px) < Math.abs(best - px)) best = s;
        return best / BASE_PX;
    }

    /**
     * Wear one theme. The token table is the desktop's own block for that id, verbatim; the four
     * mixes are computed from it, because the stylesheet asks `color-mix()` for them and the phone
     * has no `color-mix`. An unknown id falls back to the default rather than to no colours at all.
     */
    static void apply(String theme, Object fontSize, String density) {
        String t = theme == null ? "" : theme;
        THEME = t.isEmpty() ? DEFAULT_THEME : t;
        LIGHT = false;
        for (String[] th : THEMES) if (th[0].equals(t)) LIGHT = th[2].equals("1");
        if (t.equals("light")) {
            set(0xFFF6F6F9, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFF1F1F5, 0xFFE4E4EA, 0xFFD5D5DE,
                0xFF14141C, 0xFF5A5A6A, 0xFF6B6B78, 0xFF7C5CFF, 0xFF0B0B10, 0xFF5B3AE0,
                0xFF0E7C52, 0xFF8A5A00, 0xFFC0263A, 0xFFECECF2, 0xFF7A7A88);
        } else if (t.equals("ainative")) {
            set(0xFF0B0D12, 0xFF12151C, 0xFF161A23, 0xFF1E2330, 0xFF272C38, 0xFF39404F,
                0xFFEDEFF4, 0xFFA0A7B8, 0xFF8A91A3, 0xFF5457E5, 0xFFFFFFFF, 0xFF9BA0F5,
                0xFF34D399, 0xFFFBBF24, 0xFFF87171, 0xFF1B202A, 0xFF6B7280);
        } else if (t.equals("ainative-light")) {
            set(0xFFF7F8FA, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFF1F2F6, 0xFFE3E5EB, 0xFFCFD3DD,
                0xFF111827, 0xFF5A6273, 0xFF686F7D, 0xFF4F46E5, 0xFFFFFFFF, 0xFF4338CA,
                0xFF047857, 0xFF8A5A00, 0xFFC0263A, 0xFFEDEFF4, 0xFF7A8194);
        } else if (t.equals("luxe")) {
            set(0xFF0F0F23, 0xFF15152E, 0xFF1A1A3E, 0xFF22224A, 0xFF2E2E55, 0xFF3D3D6B,
                0xFFF0EDE4, 0xFFA9A3C4, 0xFF8F89AD, 0xFFD4AF37, 0xFF0B0B10, 0xFFE8CE7A,
                0xFF5FD3A6, 0xFFE8C766, 0xFFFF6B7A, 0xFF232349, 0xFF8E88AC);
        } else if (t.equals("eink")) {
            set(0xFFFDFBF7, 0xFFF7F4ED, 0xFFFFFFFF, 0xFFF1EDE4, 0xFFE0DDD5, 0xFFC9C4B8,
                0xFF1A1A1A, 0xFF4A4A4A, 0xFF6A665E, 0xFF1A1A1A, 0xFFFFFFFF, 0xFF1A1A1A,
                0xFF1F5C3A, 0xFF7A5A10, 0xFF8C2A2A, 0xFFEFEBE1, 0xFF6A665E);
        } else if (t.equals("terminal")) {
            set(0xFF050806, 0xFF0A120C, 0xFF0C1610, 0xFF102016, 0xFF1C3A24, 0xFF2C5A38,
                0xFFC8FFD0, 0xFF6FBF83, 0xFF57996A, 0xFF00FF41, 0xFF0B0B10, 0xFF4DFF7A,
                0xFF00FF41, 0xFFFFD24A, 0xFFFF5D6C, 0xFF122418, 0xFF3E7A50);
        } else {
            set(0xFF08080C, 0xFF0E0E14, 0xFF14141C, 0xFF1B1B25, 0xFF26262F, 0xFF33333F,
                0xFFF2F2F7, 0xFF9C9CAD, 0xFF84848F, 0xFF7C5CFF, 0xFF0B0B10, 0xFFA48BFF,
                0xFF38D39F, 0xFFF5B23D, 0xFFFF5D6C, 0xFF1C1C26, 0xFF5E5E6B);
        }
        FS = ratio(fontSize);
        // Density is a value the app reads where it lays out, not a colour: the desktop makes it an
        // attribute (`body[data-density=compact]`) so one block can tighten rules that each carry
        // their own padding. Here it is the same one knob, read by `density()`.
        COMPACT = "compact".equals(density);
    }

    /** The desktop's `body[data-density="compact"]`: the same layout, less air. */
    static boolean COMPACT;

    private static void set(int bg, int bg2, int card, int card2, int line, int line2,
                            int txt, int dim, int dim2, int accent, int accentInk, int accentTxt,
                            int ok, int warn, int err, int hov, int dot) {
        BG = bg; BG2 = bg2; CARD = card; CARD2 = card2; LINE = line; LINE2 = line2;
        TXT = txt; DIM = dim; DIM2 = dim2; ACCENT = accent; ACCENT_INK = accentInk; ACCENT_TXT = accentTxt;
        OK = ok; WARN = warn; ERR = err; HOV = hov; DOT = dot;
        USER_BG   = mix(ACCENT, CARD, 15);   // color-mix(in srgb, accent 15%, card)
        USER_LINE = mix(ACCENT, LINE, 34);   // color-mix(in srgb, accent 34%, line)
        MTS       = mix(DIM, CARD, 82);      // color-mix(in srgb, dim 82%, card) — a timestamp
        FOCUS     = (ACCENT & 0x00FFFFFF) | 0x38000000;   // color-mix(in srgb, accent 22%, transparent)
    }

    /** `color-mix(in srgb, a p%, b)` — `a` at `p` per cent over `b`, channel by channel. */
    private static int mix(int a, int b, int p) {
        int out = 0xFF000000;
        for (int shift : new int[]{ 16, 8, 0 }) {
            int av = (a >> shift) & 0xFF, bv = (b >> shift) & 0xFF;
            out |= (bv + (av - bv) * p / 100) << shift;
        }
        return out;
    }

    /** A palette entry, lifted for a dark background: {@code color-mix(hue 78%, #fff)}. On a light
        theme the lift is the opposite — the hue walked *down* to stay legible on white. */
    static int lift(int hue) {
        return LIGHT ? mix(hue, 0xFF000000, 62) : mix(hue, 0xFFFFFFFF, 78);
    }

    /** One avatar fill at 18% over this theme's card — the tinted tile a monogram sits on. */
    static int tile(int hue) {
        return mix(hue, CARD, 18);
    }

    /** Whether the theme on is one that reads on a light surface (`THEMES[i][2]`). */
    static boolean LIGHT;

    /** The theme on, so the two that also change the typeface can say so. */
    static String THEME = DEFAULT_THEME;

    /** E-Ink reads as paper and Terminal as a console: `body[data-theme=eink] :is(#msgs,#input,.md)`
        asks for a serif and `[data-theme=terminal]` for the mono family, and both reach the whole
        transcript rather than one block of it. */
    static boolean serif() { return "eink".equals(THEME); }
    static boolean mono() { return "terminal".equals(THEME); }
}
