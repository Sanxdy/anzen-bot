package io.anzenbot.app;

import android.app.AlertDialog;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.res.ColorStateList;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.speech.tts.TextToSpeech;
import android.speech.tts.Voice;
import android.text.Editable;
import android.text.InputType;
import android.text.SpannableStringBuilder;
import android.text.Spanned;
import android.text.TextUtils;
import android.text.TextWatcher;
import android.text.method.LinkMovementMethod;
import android.text.style.ClickableSpan;
import android.text.style.ForegroundColorSpan;
import android.text.style.RelativeSizeSpan;
import android.text.style.StrikethroughSpan;
import android.text.style.StyleSpan;
import android.text.style.TypefaceSpan;
import android.text.style.UnderlineSpan;
import android.util.Base64;
import android.util.TypedValue;
import android.view.ActionMode;
import android.view.Gravity;
import android.view.Menu;
import android.view.MenuItem;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.view.animation.PathInterpolator;
import android.view.inputmethod.EditorInfo;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.HorizontalScrollView;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.PopupMenu;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * The chat, drawn natively — no WebView, no page, no HTML.
 *
 * One conversation fills the screen, and the sidebar the desktop keeps down its left side is a drawer
 * here: the same bots, rooms and past chats, over the conversation instead of beside it, because a
 * phone has no width to give away. Its rows wear the desktop's own grammar — a monogram tile, a
 * status dot, one line of subtitle — so a team looks like the same team on both screens.
 *
 * The turn is the interesting part. `POST /api/chat` answers with a stream of small events, and
 * {@link Model} folds each into the transcript; this class draws whichever entry changed and leaves
 * the rest of the screen alone, so a reply that arrives a token at a time grows in place instead of
 * rebuilding the conversation under your thumb. One clock serves all of it: while a turn is in
 * flight a single 1Hz ticker redraws the rows that are counting and the header beside them, and it
 * stops the moment nothing is running.
 */
final class ChatView extends FrameLayout {
    private static final long RESUME_MS = 4000;   // a reader's scroll-back pauses the follow; it does not end it
    private static final String[] MODES = { "plan", "ask", "auto", "approve" };
    private static final String[] MODE_LABELS = { "Plan only", "Ask for approval", "Auto-accept edits", "Approve routine" };
    // The chip has room for one word and already says "Approval:", so each level gets the shortest
    // name that still tells it apart — "Approval: Approve" would say nothing at all.
    private static final String[] CHIP_WORD = { "Plan", "Ask", "Auto-accept", "Approve routine" };
    private static final String[] HUES = { "purple", "blue", "green", "orange", "yellow", "pink" };
    // A bot's own level, in the desktop's own five (`APPROVALS`, app.js:124). The chat's picker stops
    // at the four a chat can be set to; a bot can be left at the fifth, which is what a plan is
    // approved into. The labels come from `modeLabel`, so there is one spelling of each level.
    private static final String[] LEVELS = { "plan", "ask", "auto", "approve", "full" };

    /** One bot, as the drawer needs it: what to call it, what colour it wears, and its one line. */
    private static final class Bot {
        String name = "", color = "blue", emoji = "", title = "", role = "";
        boolean hidden, pinned;
        /** The uploaded avatar's version. Same shape as a room's logo: it keys the bitmap cache, so a
            new upload re-fetches and a stable one never does, and zero means the row draws the
            monogram. On the desktop the picture is the bot's face, drawn on the head where the drawn
            eyes and mouth would be; this phone has no face engine, so the picture becomes the whole
            of the bot's tile. */
        int avatar;
        /** The record the server sent, so the editor writes the fields it read rather than a shape
            rebuilt here — the endpoint merges what it is given into the bot it already has. */
        Map<String, Object> raw;
        /** The sidebar's one line: what the bot is called by, before the sentence about what it does. */
        String line() { return title.isEmpty() ? role : title; }
        /** The empty card's line, which reads the other way round: the sentence, else the label. */
        String what() { return role.isEmpty() ? title : role; }
    }

    /** One room: its team, the repo it works in, and how many are on it. */
    private static final class Room {
        String name = "", color = "blue", folder = "";
        int members;
        /** A pinned room floats to the top of the drawer, as a pinned bot does — the desktop's own
            rule, and the flag is the server's, so both clients agree on which rooms those are. */
        boolean pinned;
        /** The uploaded logo's version, and the member ids in the order the server lists them. The
            version is what a cached bitmap is keyed on, so a new upload re-fetches and a stable one
            never does. Zero means there is no logo and the row draws the monogram. */
        int logo;
        final List<String> memberIds = new ArrayList<>();
        /** The record the server sent, for the same reason the bot keeps its own. */
        Map<String, Object> raw;
    }

    /**
     * The desktop's pushpin, drawn as a phone-sized stroke (`ICON.pin`, app.js:89): the same two paths
     * on the same 24-unit grid, so a pinned row wears the same mark on both clients. A text glyph was
     * not an option — the pin has no monochrome one, and the emoji would come back coloured and
     * off-theme next to a plain dot.
     */
    private static final class Pin extends View {
        private final Paint ink = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Path path = new Path();
        Pin(Context c, int color) {
            super(c);
            ink.setStyle(Paint.Style.STROKE);
            ink.setStrokeCap(Paint.Cap.ROUND);
            ink.setStrokeJoin(Paint.Join.ROUND);
            ink.setColor(color);
        }
        @Override protected void onDraw(Canvas cv) {
            float u = getWidth() / 24f;
            ink.setStrokeWidth(1.7f * u);
            path.reset();
            path.moveTo(9.2f * u, 3.6f * u);
            path.lineTo(14.8f * u, 3.6f * u);
            path.lineTo(13.9f * u, 8.4f * u);
            path.lineTo(17.3f * u, 11.8f * u);
            path.lineTo(5.9f * u, 11.8f * u);
            path.lineTo(9.3f * u, 8.4f * u);
            path.close();
            cv.drawPath(path, ink);
            cv.drawLine(12f * u, 11.8f * u, 12f * u, 20.4f * u, ink);
        }
    }

    /**
     * A box that scrolls its own content past a ceiling. A shell command can print a thousand lines,
     * and the transcript is not where anyone reads them.
     */
    private static final class Cap extends ScrollView {
        private final int max;
        Cap(Context c, int px) { super(c); max = px; }
        @Override protected void onMeasure(int w, int h) {
            super.onMeasure(w, MeasureSpec.makeMeasureSpec(max, MeasureSpec.AT_MOST));
        }
    }

    /**
     * One bot working in the room on screen. The row is built once and then only edited — its parts
     * are held here so an update is a text change, and the clock's start time lives with the row
     * rather than with the event, so a long step keeps reading as long.
     */
    private static final class WRow {
        final LinearLayout row;
        final TextView name, title, act, phase, clock;
        long since;
        String tool = "", text = "";
        WRow(LinearLayout row, TextView name, TextView title, TextView act, TextView phase, TextView clock) {
            this.row = row; this.name = name; this.title = title;
            this.act = act; this.phase = phase; this.clock = clock;
        }
    }

    /** One task held while this chat's own turn is running. It carries what it will be sent with,
        because a task typed as a reply is still a reply when the queue finally runs it. */
    private static final class QTask {
        final String text;
        final String qWho, qText;
        final boolean fwd;
        boolean steering;
        QTask(String text, String qWho, String qText, boolean fwd, boolean steering) {
            this.text = text; this.qWho = qWho; this.qText = qText; this.fwd = fwd; this.steering = steering;
        }
    }

    private final Model model = new Model();
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final List<View> rows = new ArrayList<>();       // one per entry, so a change redraws one
    private final Map<String, Bot> bots = new LinkedHashMap<>();
    private final Map<String, Room> rooms = new LinkedHashMap<>();
    private final List<Map<String, Object>> chats = new ArrayList<>();
    private final List<String> models = new ArrayList<>();
    // Hues by id *and* by name: a live event names the bot by id, a reopened transcript names it by the
    // name the server saved, and both must come out the same colour.
    private final Map<String, Integer> hues = new LinkedHashMap<>();
    // The chats with a turn in flight. A turn outlives the screen it was started from, so the
    // drawer's dot needs to know about one running in a chat nobody is looking at.
    private final Set<String> turns = new LinkedHashSet<>();
    // The bots working in the room on screen, one row each, keyed by bot id — the desktop's live
    // strip. Keyed by id and not by name: a name can be edited mid-turn, and two members of one room
    // can share one.
    private final Map<String, WRow> working = new LinkedHashMap<>();
    // What a write_file replaced, kept for that row's diff. The pair is in the tool's own args and
    // nowhere else — the transcript keeps a one-line head — so it lives here, keyed by the tool id.
    private final Map<String, String[]> writes = new LinkedHashMap<>();
    // Tasks typed while a chat's turn was already running, held until that turn takes them — keyed by
    // chat, because a task waiting on one chat's turn must not be dropped by looking at another's.
    private final Map<String, List<QTask>> queues = new LinkedHashMap<>();
    // The turn id this app gave each chat's own turn. The watch stream mirrors every turn, this app's
    // included, so the id is what tells its own — already being drawn card for card by the POST stream
    // that started it — from a turn another client is running. A chat id cannot tell them apart: this
    // app may have run a turn in the same chat a moment ago, and skipping by chat would swallow the
    // other client's turn in it, which is the very thing the stream is here to show.
    private final Map<String, String> myTurns = new LinkedHashMap<>();
    // Whether the watch stream should be up. One thread holds `/api/watch` open and re-opens it when
    // it drops; this is what stops it when the phone goes to the background or the view goes away.
    private volatile boolean watching;
    // The live watch connection, held only so `pause` can close it. A reader parked in `readLine`
    // never sees the flag — the server's keepalives keep feeding it — so closing the socket is what
    // actually stops the stream, and the thread ends on the IOException that raises.
    private volatile java.net.HttpURLConnection watchConn;
    // Which watch loop is the current one. A loop that is unwinding when `pause` and `resume` come
    // back to back would otherwise read the flag `resume` just set and carry on beside the new one,
    // leaving two streams open — the recreate-on-a-theme-change path does exactly that.
    private volatile int watchGen;

    private String base = "", token = "", sid = "";
    private boolean started, room, configured;
    private int gen;                  // which chat is on screen; a reply that arrives for an older one is dropped
    private long turnStart;           // ms this chat's turn began; 0 when none is running
    private String chatTitle = "";
    private boolean following = true; // the reader is at the newest output, so output may pull them down
    private final int drawerW;

    // What a reply is answering, held from the moment Reply is tapped until the message is sent. A
    // reply goes with one message only, which is why it is cleared on send and not kept as a mode.
    private String replyWho = "", replyText = "";
    // Room logos, keyed `id:version`, so a new upload re-fetches and a stable one never does.
    private final Map<String, Bitmap> logos = new LinkedHashMap<>();
    // The settings the server last sent, so a switch here writes a patch over what is there rather
    // than over a shape rebuilt from nothing. `appearance` drives the theme and the font size.
    private Map<String, Object> settings = new LinkedHashMap<>();
    // The app's one speech engine, made on the first Listen and shut down with the view. Null until
    // then: a phone that never reads anything aloud never pays for an engine.
    private TextToSpeech tts;
    private boolean ttsReady, ttsFailed;
    // The words waiting on that engine: a phone's speech takes a moment to come up, and the first
    // Listen must not be the one tap that does nothing.
    private String say;
    // The saved conversation as the server sent it. The transcript holds more than this — tool rows
    // and notes live only in the turn — so Edit and Retry index into this, not into the entries, which
    // is exactly what the entry's own `i` points at.
    private List<Object> saved = new ArrayList<>();
    /** The team structure the server hands out, so it can be copied and given to a model. Empty until
        the first roster lands. See `team_template`, server.py:6539. */
    private String teamTemplate = "";

    private final LinearLayout content, navCol, botsCol, roomsCol, chatsCol;
    private LinearLayout chips, inwrap, glow, workCol, queueCol, replyStrip;
    private Cap workCap, queueCap;
    private TextView hName, hStatus, chipModel, chipApproval, chipCtx, send, stop;
    /** The chat's face in the header, filled per chat by {@link #headFace}. */
    private FrameLayout hFace;
    private TextView botsLabel, roomsLabel, chatsLabel;
    // The CHATS heading is the one section that folds, so the label and its caret are a control: the
    // caret turns and the label is what the section's own visibility is set on.
    private TextView chatsCaret;
    private LinearLayout chatsHead;
    private View chatSearch;
    private View hDot, jump, scrim, drawer;
    private EditText search, input;
    private ScrollView txScroll;
    private LinearLayout txCol;
    // The one overlay a sheet is drawn on — a forward picker, the computer, the files, the settings.
    // One at a time, because a phone shows one thing over the chat and the chat stays behind it.
    private View sheet;

    private final Runnable down = new Runnable() {
        @Override public void run() { txScroll.fullScroll(View.FOCUS_DOWN); }
    };
    private final Runnable resume = new Runnable() {
        // The pause hands the *follow* back, not a scroll. Firing used to call `follow()`, which drags
        // the transcript down — so a reader who had stopped short of the bottom was pulled off what
        // they were reading a few seconds later with nothing having been sent, and again on every
        // further scroll, since each one re-arms this. The trip down belongs to the next message; the
        // desktop's `holdFollow` is the same fix.
        @Override public void run() { following = true; }
    };
    /** The one clock: every row that is counting, the bots on the working strip, and the header's
        own, on the same second. */
    private final Runnable tick = new Runnable() {
        @Override public void run() {
            if (turnStart == 0) return;
            for (int i = 0; i < model.entries().size() && i < rows.size(); i++) {
                if (model.entries().get(i).live()) paint(i);
            }
            workClock();
            head();
            ui.postDelayed(this, 1000);
        }
    };

    ChatView(Context c) {
        super(c);
        setBackgroundColor(Pal.BG);
        drawerW = Math.min(dp(300), getResources().getDisplayMetrics().widthPixels * 86 / 100);

        content = new LinearLayout(c);
        content.setOrientation(LinearLayout.VERTICAL);
        content.addView(header(c), new LayoutParams(-1, -2));
        content.addView(transcript(c), new LinearLayout.LayoutParams(-1, 0, 1f));
        content.addView(composer(c), new LayoutParams(-1, -2));
        addView(content, new LayoutParams(-1, -1));

        scrim = new View(c);
        scrim.setBackgroundColor(0x80000000);
        scrim.setVisibility(GONE);
        scrim.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { closeDrawer(); }
        });
        addView(scrim, new LayoutParams(-1, -1));

        LinearLayout panel = new LinearLayout(c);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setBackgroundColor(Pal.BG2);
        navCol = new LinearLayout(c);
        navCol.setOrientation(LinearLayout.VERTICAL);
        navCol.setPadding(dp(10), 0, dp(10), dp(16));
        chatsLabel = navlabel("CHATS");
        // The CHATS heading folds its own list away. A phone's drawer is short and the list runs to the
        // newest conversation every time a turn ends, which is what pushes the rooms and bots off the
        // bottom — the same reason the desktop added it. The heading carries the whole hit area,
        // because an 11sp uppercase word is a poor target. See `.navlabel.foldable`, index.html:230.
        chatsLabel.setPadding(0, dp(10), 0, dp(6));       // the row carries the side padding instead
        chatsCaret = text("›", Pal.DIM2, 15);
        chatsCaret.setGravity(Gravity.CENTER);
        chatsHead = new LinearLayout(c);
        chatsHead.setOrientation(LinearLayout.HORIZONTAL);
        chatsHead.setGravity(Gravity.CENTER_VERTICAL);
        chatsHead.setPadding(dp(8), 0, dp(8), 0);
        chatsHead.addView(chatsCaret, new LinearLayout.LayoutParams(dp(14), -2));
        chatsHead.addView(chatsLabel);
        chatsHead.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { foldChats(); }
        });
        roomsLabel = navlabel("ROOMS");
        botsLabel = navlabel("BOTS");
        botsCol = new LinearLayout(c);
        botsCol.setOrientation(LinearLayout.VERTICAL);
        roomsCol = new LinearLayout(c);
        roomsCol.setOrientation(LinearLayout.VERTICAL);
        chatsCol = new LinearLayout(c);
        chatsCol.setOrientation(LinearLayout.VERTICAL);
        // The desktop's own order down the sidebar: chats (with the search box inside that section),
        // then the rooms, then the loose bots.
        navCol.addView(chatsHead);
        chatSearch = searchBar(c);
        navCol.addView(chatSearch);
        navCol.addView(chatsCol);
        navCol.addView(roomsLabel);
        navCol.addView(roomsCol);
        navCol.addView(botsLabel);
        navCol.addView(botsCol);
        ScrollView nav = new ScrollView(c);
        nav.addView(navCol, new ViewGroup.LayoutParams(-1, -2));
        panel.addView(nav, new LinearLayout.LayoutParams(-1, 0, 1f));

        // The drawer's own footer, where the desktop keeps Help and Settings. It sits outside the
        // scroll so it is reachable however long the roster grows.
        LinearLayout foot = new LinearLayout(c);
        foot.setOrientation(LinearLayout.HORIZONTAL);
        foot.setPadding(dp(10), dp(10), dp(10), dp(4));
        foot.addView(footBtn("Help", "help"), new LinearLayout.LayoutParams(0, -2, 1f));
        foot.addView(footBtn("Settings", ""), spaced(8));
        panel.addView(foot, new LinearLayout.LayoutParams(-1, -2));

        LinearLayout edge = new LinearLayout(c);
        edge.setOrientation(LinearLayout.HORIZONTAL);
        edge.addView(panel, new LinearLayout.LayoutParams(0, -1, 1f));
        View hairline = new View(c);
        hairline.setBackgroundColor(Pal.LINE);
        edge.addView(hairline, new LayoutParams(dp(1), -1));
        drawer = edge;
        drawer.setVisibility(GONE);
        addView(drawer, new LayoutParams(drawerW + dp(1), -1));
        // The drawer is a full-height panel, so it meets the status bar the same way the header does.
        drawer.setOnApplyWindowInsetsListener(new OnApplyWindowInsetsListener() {
            @Override public WindowInsets onApplyWindowInsets(View v, WindowInsets ins) {
                panel.setPadding(0, ins.getSystemWindowInsetTop(), 0, 0);
                return ins;
            }
        });

        // There is no action bar and, from Android 15, no window that stops at the status bar: the
        // keyboard is drawn over the app too, and nothing else shrinks for it. Taking the bottom inset
        // here shortens the screen by exactly what the keyboard covers, so the composer sits on top of
        // it instead of behind it.
        setOnApplyWindowInsetsListener(new OnApplyWindowInsetsListener() {
            @Override public WindowInsets onApplyWindowInsets(View v, WindowInsets ins) {
                v.setPadding(0, 0, 0, ins.getSystemWindowInsetBottom());
                return ins;
            }
        });

        head();
        rebuild();   // with no chat open yet, this is the empty screen that says so
    }

    // ---- what the host calls -----------------------------------------------------------------

    /** The door opened. Read the roster and the conversation list, once per address. */
    void start(String url, String tok) {
        if (started && url.equals(base) && tok.equals(token)) return;
        base = url; token = tok; started = true;
        loadConfig();
        loadChats();
        watch();
    }

    /** The hardware back button. True when it was used up here rather than leaving the app. Topmost
        surface first, so a sheet over the drawer closes before the drawer does. */
    boolean back() {
        if (sheet != null) { closeSheet(); return true; }
        if (drawer.getVisibility() == VISIBLE) { closeDrawer(); return true; }
        return false;
    }

    // ---- the roster --------------------------------------------------------------------------

    private void loadConfig() {
        new Thread(new Runnable() {
            @Override public void run() {
                try {
                    final Map<String, Object> cfg = Json.obj(Api.get(base, token, "/api/config"));
                    ui.post(new Runnable() {
                        @Override public void run() { roster(cfg); }
                    });
                } catch (IOException ignored) {
                    // A roster is a nicety: the transcript still works, it just says "producer".
                }
            }
        }).start();
    }

    private void roster(Map<String, Object> cfg) {
        bots.clear(); rooms.clear(); models.clear(); hues.clear();
        Map<String, String> names = new LinkedHashMap<>();
        if (cfg != null) {
            // The theme travels with the roster because it is one `/api/config` and one answer: the
            // server owns the setting, so a phone opening after a theme was chosen on the desktop
            // wears it too, and neither client keeps a copy of its own.
            Map<String, Object> s = row(cfg.get("settings"));
            settings = s == null ? new LinkedHashMap<String, Object>() : s;
            appearance(row(settings.get("appearance")));
            teamTemplate = Json.str(cfg.get("team_template"));
            for (Object o : asList(cfg.get("bots"))) {
                Map<String, Object> m = row(o);
                if (m == null) continue;
                String id = Json.str(m.get("id"));
                if (id.isEmpty()) continue;
                Bot b = new Bot();
                b.name = Json.str(m.get("name"));
                b.color = Json.str(m.get("color"));
                b.emoji = Json.str(m.get("emoji"));
                b.title = Json.str(m.get("title"));
                b.role = Json.str(m.get("role"));
                b.hidden = Json.truth(m.get("hidden"));
                b.pinned = Json.truth(m.get("pinned"));
                b.avatar = (int) Json.num(m.get("avatar"));
                b.raw = m;
                bots.put(id, b);
                names.put(id, b.name.isEmpty() ? id : b.name);
                hues.put(id, hue(b.color));
                if (!b.name.isEmpty()) hues.put(b.name, hue(b.color));
            }
            for (Object o : asList(cfg.get("channels"))) {
                Map<String, Object> m = row(o);
                if (m == null) continue;
                String id = Json.str(m.get("id"));
                if (id.isEmpty()) continue;
                Room r = new Room();
                r.name = Json.str(m.get("name"));
                r.color = Json.str(m.get("color"));
                r.folder = Json.str(m.get("folder"));
                r.logo = (int) Json.num(m.get("logo"));
                r.pinned = Json.truth(m.get("pinned"));
                r.raw = m;
                for (Object x : asList(m.get("members"))) {
                    String mid = Json.str(x);
                    Bot b = bots.get(mid);
                    if (b == null || b.hidden) continue;
                    r.members++;
                    r.memberIds.add(mid);   // the drawer nests these under the room
                }
                rooms.put(id, r);
                names.put(id, r.name.isEmpty() ? id : r.name);
                hues.put(id, hue(r.color));
                if (!r.name.isEmpty()) hues.put(r.name, hue(r.color));
            }
            for (Object o : asList(cfg.get("models"))) {
                String mid = Json.str(o);
                if (!mid.isEmpty()) models.add(mid);
            }
            configured = true;
        }
        model.roster(names);
        nav();
        head();
        if (sid.isEmpty()) rebuild();   // the empty card may have just become a different empty card
    }

    /**
     * Wear the theme the phone remembers, before a single view is built.
     *
     * A colour is baked into a drawable the moment the drawable is made, so a theme applied after the
     * screen exists would repaint half of it. This runs first, and {@link #appearance} is what keeps
     * the memory in step with the server — the server owns the setting, this only caches it so the
     * next launch starts in the right colours instead of flashing the default.
     */
    static void wear(Context c) {
        SharedPreferences p = c.getSharedPreferences("anzen", Context.MODE_PRIVATE);
        Pal.apply(p.getString("theme", Pal.DEFAULT_THEME), p.getFloat("font_size", 0f),
                  p.getString("density", ""));
    }

    /**
     * What `/api/config` says the appearance is. The theme, the size and the density travel together
     * in one `appearance` record, so they are read and remembered together.
     *
     * A theme that differs from the one on screen asks the host to rebuild the activity rather than
     * trying to repaint in place — the same answer the desktop gives by redrawing from the body down,
     * and the only one that reaches every drawable. The cache is written first, so the rebuilt screen
     * reads the new theme and does not ask again.
     */
    private void appearance(Map<String, Object> a) {
        String theme = a == null ? "" : Json.str(a.get("theme"));
        if (theme.isEmpty()) theme = Pal.DEFAULT_THEME;
        float size = a == null ? 0f : (float) Json.dbl(a.get("font_size"));
        String density = a == null ? "" : Json.str(a.get("density"));
        SharedPreferences p = getContext().getSharedPreferences("anzen", Context.MODE_PRIVATE);
        boolean changed = !theme.equals(p.getString("theme", Pal.DEFAULT_THEME))
                       || size != p.getFloat("font_size", 0f)
                       || !density.equals(p.getString("density", ""));
        p.edit().putString("theme", theme).putFloat("font_size", size)
                .putString("density", density).apply();
        if (changed) {
            // A sheet is open over this: yanking the activity away mid-edit would drop you out of the
            // settings screen you are standing in, so the new look lands as the sheet closes.
            if (sheet != null) { wearNext = true; return; }
            ((android.app.Activity) getContext()).recreate();
            return;
        }
        Pal.apply(theme, size, density);
    }

    private void loadChats() {
        new Thread(new Runnable() {
            @Override public void run() {
                try {
                    final Map<String, Object> r = Json.obj(Api.get(base, token, "/api/chats"));
                    ui.post(new Runnable() {
                        @Override public void run() { listChats(r); }
                    });
                } catch (IOException ignored) {
                    // The drawer's chat list is a shortcut back into a conversation, not the way in.
                }
            }
        }).start();
    }

    private void listChats(Map<String, Object> r) {
        chats.clear();
        if (r != null) {
            for (Object o : asList(r.get("chats"))) {
                Map<String, Object> c = row(o);
                if (c != null) chats.add(c);
            }
        }
        nav();
        // Nothing open yet: land on the newest chat, which is where the desktop's own boot lands.
        if (sid.isEmpty() && !chats.isEmpty()) {
            Map<String, Object> c = chats.get(0);
            open(Json.str(c.get("id")), Json.str(c.get("name")), "room".equals(Json.str(c.get("kind"))));
        } else if (sid.isEmpty()) {
            rebuild();
        }
    }

    // ---- the drawer --------------------------------------------------------------------------

    private View searchBar(Context c) {
        search = new EditText(c);
        search.setHint("Search chats…");
        search.setHintTextColor(Pal.DIM2);
        search.setTextColor(Pal.TXT);
        search.setTextSize(Pal.fs(13));
        search.setSingleLine(true);
        search.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        search.setBackground(shape(Pal.CARD, Pal.LINE, 1, 11));
        search.setPadding(dp(12), dp(10), dp(12), dp(10));
        search.setMinHeight(dp(40));
        search.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int a, int b, int d) { }
            @Override public void onTextChanged(CharSequence s, int a, int b, int d) { }
            @Override public void afterTextChanged(Editable s) { renderChats(); }
        });
        LinearLayout wrap = new LinearLayout(c);
        wrap.setPadding(dp(12), dp(10), dp(12), dp(6));
        wrap.addView(search, new LayoutParams(-1, -2));
        return wrap;
    }

    /** A button in the drawer's footer: Help, Settings. */
    private TextView footBtn(String label, final String tab) {
        TextView t = bold(text(label, Pal.TXT, 13));
        t.setGravity(Gravity.CENTER);
        t.setPadding(dp(12), dp(11), dp(12), dp(11));
        t.setMinHeight(dp(44));
        t.setBackground(press(shape(Pal.CARD, Pal.LINE, 1, 11)));
        t.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) {
                closeDrawer();
                setTab = tab;
                settingsSheet();
            }
        });
        return t;
    }

    private void openDrawer() {
        if (drawer.getVisibility() == VISIBLE) return;
        drawer.setVisibility(VISIBLE);
        scrim.setVisibility(VISIBLE);
        scrim.setAlpha(0f);
        drawer.setTranslationX(-drawerW);
        slide(0f);
        scrim.animate().alpha(1f).setDuration(260).start();
    }

    private void closeDrawer() {
        if (drawer.getVisibility() != VISIBLE) return;
        slide(-drawerW);
        scrim.animate().alpha(0f).setDuration(260).withEndAction(new Runnable() {
            @Override public void run() { scrim.setVisibility(GONE); }
        }).start();
    }

    /** The desktop's own curve, so the drawer arrives here the way it arrives there. */
    private void slide(float to) {
        drawer.animate().translationX(to).setDuration(260)
              .setInterpolator(new PathInterpolator(0.2f, 0.8f, 0.3f, 1f))
              .withEndAction(new Runnable() {
                  @Override public void run() {
                      if (drawer.getTranslationX() < 0) drawer.setVisibility(GONE);
                  }
              }).start();
    }

    /**
     * The sidebar, in the desktop's own shape: each room with its team nested underneath it, then
     * whatever bots are not on a team. A member bot appears once, under its room — it is not listed
     * again below, which is what `claimed` is for — and the loose bots are pinned-first, so a bot you
     * pinned stays where you put it.
     *
     * The fold is the desktop's `nav.collapsed`, kept here in the app's own preferences: it is a
     * phone's setting about a phone's drawer, and a fold that reset on every launch would be no fold
     * at all. See `renderNav`, app.js:781.
     */
    private void nav() {
        Set<String> claimed = new LinkedHashSet<>();
        roomsCol.removeAllViews();
        // Pinned first, and stable within each half — the desktop's own rule for the rooms
        // (`[...S.channels].sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0))`), so the two
        // clients never disagree about the top of the drawer.
        List<Map.Entry<String, Room>> ordered = new ArrayList<>(rooms.entrySet());
        Collections.sort(ordered, new java.util.Comparator<Map.Entry<String, Room>>() {
            @Override public int compare(Map.Entry<String, Room> a, Map.Entry<String, Room> b) {
                return (b.getValue().pinned ? 1 : 0) - (a.getValue().pinned ? 1 : 0);
            }
        });
        for (Map.Entry<String, Room> e : ordered) {
            String id = e.getKey();
            Room r = e.getValue();
            for (String m : r.memberIds) claimed.add(m);
            boolean shut = folded(id);

            LinearLayout group = new LinearLayout(getContext());
            group.setOrientation(LinearLayout.VERTICAL);
            group.addView(roomRow(id, r, shut));

            LinearLayout sub = new LinearLayout(getContext());
            sub.setOrientation(LinearLayout.VERTICAL);
            // Far enough left that a member reads as *inside* the room and not beside it: the room's
            // own tile starts 30dp in (its caret and its padding), so anything less than that is a
            // list that merely follows one.
            sub.setPadding(dp(30), 0, 0, 0);
            sub.setVisibility(shut ? GONE : VISIBLE);
            for (String m : r.memberIds) {
                Bot b = bots.get(m);
                if (b != null) sub.addView(navRow(m, b.name, b.line(), id, true));
            }
            group.addView(sub);
            roomsCol.addView(group);
        }
        roomsLabel.setVisibility(roomsCol.getChildCount() == 0 ? GONE : VISIBLE);

        botsCol.removeAllViews();
        List<Map.Entry<String, Bot>> loose = new ArrayList<>();
        for (Map.Entry<String, Bot> e : bots.entrySet()) {
            if (!e.getValue().hidden && !claimed.contains(e.getKey())) loose.add(e);
        }
        // Pinned first, and stable within each half: the desktop's own `sort((a,b) => b.pinned - a.pinned)`.
        Collections.sort(loose, new java.util.Comparator<Map.Entry<String, Bot>>() {
            @Override public int compare(Map.Entry<String, Bot> a, Map.Entry<String, Bot> b) {
                return (b.getValue().pinned ? 1 : 0) - (a.getValue().pinned ? 1 : 0);
            }
        });
        for (Map.Entry<String, Bot> e : loose) {
            Bot b = e.getValue();
            botsCol.addView(navRow(e.getKey(), b.name, b.line(), null, false));
        }
        botsLabel.setVisibility(botsCol.getChildCount() == 0 ? GONE : VISIBLE);

        renderChats();
        // The fold is applied here rather than where the rows are built, so a list that changes under
        // it — a turn ending, a search — cannot leave the section half-shut. The search box goes with
        // the list: it is inside the section, as the desktop's own `.chsearch` is.
        boolean shut = chatsShut();
        chatSearch.setVisibility(shut ? GONE : VISIBLE);
        chatsCol.setVisibility(shut ? GONE : VISIBLE);
        chatsCaret.setRotation(shut ? 0 : 90);
        chatsHead.setContentDescription(shut ? "Show your recent chats" : "Hide your recent chats");
        // An empty section takes its heading with it, as the desktop's own does — but a folded one
        // keeps it, because the heading is the only way back to the list.
        chatsHead.setVisibility(chatsCol.getChildCount() == 0 ? GONE : VISIBLE);
    }

    /** Whether the recent-chat list is folded away. Its own store, so a room that happens to be called
        "chats" cannot fold the chat list. See `shutSecs`, app.js:126. */
    private boolean chatsShut() {
        return getContext().getSharedPreferences("anzen", Context.MODE_PRIVATE).getBoolean("chatsShut", false);
    }

    /** Fold the recent-chat list away, or bring it back, and redraw the drawer. */
    private void foldChats() {
        getContext().getSharedPreferences("anzen", Context.MODE_PRIVATE).edit()
                .putBoolean("chatsShut", !chatsShut()).apply();
        nav();
    }

    /** Whether a room's team is folded shut. */
    private boolean folded(String id) {
        return getContext().getSharedPreferences("anzen", Context.MODE_PRIVATE)
                .getStringSet("foldedRooms", Collections.<String>emptySet()).contains(id);
    }

    /** Fold or unfold one room's team, and redraw the drawer. */
    private void fold(String id) {
        SharedPreferences p = getContext().getSharedPreferences("anzen", Context.MODE_PRIVATE);
        Set<String> now = new LinkedHashSet<>(p.getStringSet("foldedRooms", Collections.<String>emptySet()));
        if (!now.remove(id)) now.add(id);
        p.edit().putStringSet("foldedRooms", now).apply();
        nav();
    }

    /**
     * The mark a pinned row wears. It sits between the name and the run dot, which is where the
     * desktop puts it (`app.js:874`), because a row that has floated to the top of the drawer should
     * say why — and with two pins the position alone no longer tells you which rows are the pinned
     * ones.
     */
    private View pinMark() {
        Pin p = new Pin(getContext(), Pal.DIM2);
        p.setContentDescription("Pinned");
        return p;
    }

    /**
     * A room's row: the same row a bot gets, with a caret on its left that folds the team. The caret
     * is its own tap target and consumes the tap, so folding a room never also opens it — on a phone
     * the desktop's double-click on the row is not a gesture anyone would find.
     */
    private View roomRow(final String id, Room r, boolean shut) {
        FrameLayout row = new FrameLayout(getContext());
        row.setBackground(id.equals(sid) ? selected(Pal.CARD2, 13, 12) : press(shape(0, 13)));

        LinearLayout inner = new LinearLayout(getContext());
        inner.setOrientation(LinearLayout.HORIZONTAL);
        inner.setGravity(Gravity.CENTER_VERTICAL);
        inner.setPadding(dp(4), dp(10), dp(11), dp(10));
        inner.setMinimumHeight(dp(56));

        // Only a room with a team gets a caret: one that folds nothing is a tap target that lies.
        if (!r.memberIds.isEmpty()) {
            TextView caret = text("›", Pal.DIM2, 15);
            caret.setGravity(Gravity.CENTER);
            caret.setRotation(shut ? 0 : 90);
            caret.setContentDescription(shut ? "Unfold this room's team" : "Fold this room's team");
            caret.setOnClickListener(new OnClickListener() {
                @Override public void onClick(View v) { fold(id); }
            });
            inner.addView(caret, new LayoutParams(dp(26), dp(46)));
        } else {
            inner.addView(new View(getContext()), new LayoutParams(dp(26), dp(46)));
        }
        inner.addView(tileOrLogo(id, r, FACE_FS, FACE_R), new LayoutParams(dp(46), dp(46)));

        LinearLayout col = new LinearLayout(getContext());
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(dp(12), 0, 0, 0);
        LinearLayout top = new LinearLayout(getContext());
        top.setOrientation(LinearLayout.HORIZONTAL);
        top.setGravity(Gravity.CENTER_VERTICAL);
        TextView n = bold(text(r.name, Pal.TXT, 14));
        n.setSingleLine(true);
        n.setEllipsize(TextUtils.TruncateAt.END);
        top.addView(n, new LinearLayout.LayoutParams(0, -2, 1f));
        if (r.pinned) {
            LinearLayout.LayoutParams plp = new LinearLayout.LayoutParams(dp(12), dp(12));
            plp.leftMargin = dp(7);
            top.addView(pinMark(), plp);
        }
        View dot = new View(getContext());
        dot.setBackground(oval(turns.contains(id) ? Pal.ACCENT : Pal.DOT));
        LinearLayout.LayoutParams dlp = new LinearLayout.LayoutParams(dp(7), dp(7));
        dlp.leftMargin = dp(7);
        top.addView(dot, dlp);
        col.addView(top);
        TextView sub = text(roomLine(r), Pal.DIM, 12);
        sub.setSingleLine(true);
        sub.setEllipsize(TextUtils.TruncateAt.END);
        col.addView(sub);
        inner.addView(col, new LinearLayout.LayoutParams(0, -2, 1f));
        row.addView(inner, new FrameLayout.LayoutParams(-1, -2));

        if (id.equals(sid)) {
            View bar = new View(getContext());
            bar.setBackground(shape(Pal.ACCENT, 3));
            FrameLayout.LayoutParams blp = new FrameLayout.LayoutParams(dp(3), -1, Gravity.LEFT);
            blp.topMargin = dp(12); blp.bottomMargin = dp(12);
            row.addView(bar, blp);
        }
        final String name = r.name;
        row.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { open(id, name, true); }
        });
        row.setOnLongClickListener(new OnLongClickListener() {
            @Override public boolean onLongClick(View v) { rowMenu(v, id, name, "channels", null); return true; }
        });
        return row;
    }

    /** The two boxes a face is drawn in — the drawer's row and the chat header. The mark and the
        corner follow the box, so the header's is the drawer's own tile smaller rather than a second
        design; only the drawer's is spelled out, the header's being 26dp of the same 46. */
    private static final int FACE_FS = 15, FACE_R = 13;
    private static final int FACE_SMALL_FS = 9, FACE_SMALL_R = 7;

    /** A room's face: the logo that was uploaded, or the monogram when there is none — or when what
        was uploaded is an SVG, which this phone has no decoder for. */
    private View tileOrLogo(String id, Room r, int fs, int radius) {
        Bitmap bm = logo(id, r);
        return bm == null ? tile(r.name, r.color, "", fs, radius) : picture(bm, r.color, r.name, radius);
    }

    /** A bot's face: its avatar when it has one, else the monogram — the room's own rule, one kind
        over. On the desktop the picture is the face on the bot's head; this phone has no face engine,
        so the picture is the whole of the bot's tile. See `avatarUrl`, app.js:163. */
    private View tileOrAvatar(String id, int fs, int radius) {
        Bot b = bots.get(id);
        if (b == null) return tile(id, "blue", "", fs, radius);
        Bitmap bm = avatar(id, b);
        return bm == null ? tile(b.name, b.color, b.emoji, fs, radius) : picture(bm, b.color, b.name, radius);
    }

    /** An uploaded picture in the monogram's own box: same size, same radius, same stroke, so a room
        with a logo and a bot with an avatar read as one kind of thing. */
    private View picture(Bitmap bm, String color, String name, int radius) {
        ImageView iv = new ImageView(getContext());
        iv.setImageBitmap(bm);
        iv.setScaleType(ImageView.ScaleType.CENTER_CROP);
        iv.setClipToOutline(true);
        iv.setBackground(shape(Pal.tile(hue(color)), Pal.LINE, 1, radius));
        iv.setContentDescription(name);
        return iv;
    }

    /** A bitmap that would not decode, remembered as a one-pixel one so a bad upload is asked for
        once rather than on every redraw of the drawer. */
    private static final Bitmap EMPTY = Bitmap.createBitmap(1, 1, Bitmap.Config.ALPHA_8);

    /** The room's logo, fetched once per version and kept. A version bump is a new upload, and only
        then is the bytes call made again. */
    private Bitmap logo(final String id, final Room r) {
        return upload("l:" + id, r.logo, "/api/logo/" + Targets.encode(id), id);
    }

    /** A bot's avatar, fetched once per version and kept — `logo`'s own rule. The keys are prefixed by
        kind because a bot and a room may legally share a slug, and a shared key would hand one's
        picture to the other. */
    private Bitmap avatar(final String id, final Bot b) {
        return upload("a:" + id, b.avatar, "/api/avatar/" + Targets.encode(id), id);
    }

    /** One uploaded picture, cached on `kind:id:version` and fetched on a thread when it is not. The
        redraw it posts is the drawer and the header both, because the two draw the same bot. */
    private Bitmap upload(final String who, int version, final String path, final String redrawFor) {
        if (version == 0) return null;
        final String key = who + ":" + version;
        if (logos.containsKey(key)) return logos.get(key) == EMPTY ? null : logos.get(key);
        new Thread(new Runnable() {
            @Override public void run() {
                final byte[] raw = Api.getBytes(base, token, path);
                final Bitmap bm = raw.length == 0 ? null : BitmapFactory.decodeByteArray(raw, 0, raw.length);
                ui.post(new Runnable() {
                    @Override public void run() {
                        logos.put(key, bm == null ? EMPTY : bm);
                        if (bm == null) return;
                        nav();
                        // The header wears the same bot, so it is redrawn too — but only when the chat
                        // on screen is the one the picture arrived for.
                        if (redrawFor.equals(sid)) head();
                    }
                });
            }
        }).start();
        return null;
    }

    private static String roomLine(Room r) {
        String repo = r.folder;
        while (repo.endsWith("/")) repo = repo.substring(0, repo.length() - 1);
        int cut = repo.lastIndexOf('/');
        if (cut >= 0) repo = repo.substring(cut + 1);
        return r.members + (r.members == 1 ? " member" : " members") + (repo.isEmpty() ? "" : " · " + repo);
    }

    /** One row of the drawer: the desktop's bot row, whose id is the chat it opens. */
    private View navRow(final String id, String name, String sub, final String group, boolean nested) {
        FrameLayout row = new FrameLayout(getContext());
        boolean sel = id.equals(sid);
        row.setBackground(sel ? selected(Pal.CARD2, 13, 12) : press(shape(0, 13)));

        LinearLayout inner = new LinearLayout(getContext());
        inner.setOrientation(LinearLayout.HORIZONTAL);
        inner.setGravity(Gravity.CENTER_VERTICAL);
        // A nested member is the same bot, one size down — the desktop's `.bot.subbot`, which
        // tightens the row and drops the name a point rather than drawing a second kind of row.
        inner.setPadding(dp(11), nested ? dp(5) : dp(10), dp(11), nested ? dp(5) : dp(10));
        inner.setMinimumHeight(dp(nested ? 48 : 56));
        inner.addView(tileOrAvatar(id, FACE_FS, FACE_R), new LayoutParams(dp(46), dp(46)));

        LinearLayout col = new LinearLayout(getContext());
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(dp(12), 0, 0, 0);
        LinearLayout top = new LinearLayout(getContext());
        top.setOrientation(LinearLayout.HORIZONTAL);
        top.setGravity(Gravity.CENTER_VERTICAL);
        TextView n = bold(text(name, Pal.TXT, nested ? 13 : 14));
        n.setSingleLine(true);
        n.setEllipsize(TextUtils.TruncateAt.END);
        top.addView(n, new LinearLayout.LayoutParams(0, -2, 1f));
        Bot pinBot = bots.get(id);
        if (pinBot != null && pinBot.pinned) {
            LinearLayout.LayoutParams plp = new LinearLayout.LayoutParams(dp(12), dp(12));
            plp.leftMargin = dp(7);
            top.addView(pinMark(), plp);
        }
        View dot = new View(getContext());
        // Lit for any chat whose turn is running, not only the one on screen: a room works while you
        // are reading somewhere else, and a dot that only ever lights under your thumb hides that.
        dot.setBackground(oval(turns.contains(id) ? Pal.ACCENT : Pal.DOT));
        LinearLayout.LayoutParams dlp = new LinearLayout.LayoutParams(dp(7), dp(7));
        dlp.leftMargin = dp(7);
        top.addView(dot, dlp);
        col.addView(top);
        if (!sub.isEmpty()) {
            TextView r = text(sub, Pal.DIM, 12);
            r.setSingleLine(true);
            r.setEllipsize(TextUtils.TruncateAt.END);
            col.addView(r);
        }
        inner.addView(col, new LinearLayout.LayoutParams(0, -2, 1f));
        row.addView(inner, new FrameLayout.LayoutParams(-1, -2));

        if (sel) {
            View bar = new View(getContext());
            bar.setBackground(shape(Pal.ACCENT, 3));
            FrameLayout.LayoutParams blp = new FrameLayout.LayoutParams(dp(3), -1, Gravity.LEFT);
            blp.topMargin = dp(12); blp.bottomMargin = dp(12);
            row.addView(bar, blp);
        }
        row.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { open(id, name, false); }
        });
        // A phone has no hover, so the desktop's hover-revealed kebab is a press held here: the same
        // menu, on the same rows. The press is consumed, so letting go does not also open the chat.
        final String kind = group != null ? "members" : "bots";
        row.setOnLongClickListener(new OnLongClickListener() {
            @Override public boolean onLongClick(View v) { rowMenu(v, id, name, kind, group); return true; }
        });
        return row;
    }

    private void renderChats() {
        chatsCol.removeAllViews();
        String q = search.getText().toString().trim().toLowerCase(Locale.getDefault());
        // The company is shown beside a chat's name only where it is doing a job: a bot with a chat
        // both inside a room and outside one would otherwise give two rows the same name.
        Map<String, Integer> dupes = new HashMap<>();
        for (Map<String, Object> c : chats) {
            String n = Json.str(c.get("name"));
            Integer was = dupes.get(n);
            dupes.put(n, was == null ? 1 : was + 1);
        }
        int shown = 0;
        for (Map<String, Object> c : chats) {
            String name = Json.str(c.get("name"));
            String last = Json.str(c.get("last"));
            if (last.isEmpty()) last = Json.str(c.get("title"));
            if (!q.isEmpty() && !(name + " " + last).toLowerCase(Locale.getDefault()).contains(q)) continue;
            Integer many = dupes.get(name);
            chatsCol.addView(chatRow(c, name, last, many != null && many > 1 ? scopeName(Json.str(c.get("id"))) : ""));
            shown++;
        }
        if (shown == 0) {
            TextView t = text(q.isEmpty() ? "Nothing here yet — say something to a bot and it shows up."
                                          : "No chat matches “" + search.getText().toString().trim() + "”.",
                              Pal.DIM2, 12);
            t.setPadding(dp(10), dp(8), dp(10), dp(8));
            chatsCol.addView(t);
        }
    }

    /** The room a scoped chat lives in — `studio/builder` reads as "studio" — or "" for a plain one. */
    private String scopeName(String id) {
        int cut = id.lastIndexOf('/');
        Room r = cut < 0 ? null : rooms.get(id.substring(0, cut));
        return r == null || r.name.isEmpty() ? "" : r.name;
    }

    private View chatRow(final Map<String, Object> c, String name, String last, String scope) {
        final String id = Json.str(c.get("id"));
        final boolean isRoom = "room".equals(Json.str(c.get("kind")));
        FrameLayout row = new FrameLayout(getContext());
        boolean sel = id.equals(sid);
        row.setBackground(sel ? selected(Pal.CARD2, 11, 9) : press(shape(0, 11)));

        LinearLayout inner = new LinearLayout(getContext());
        inner.setOrientation(LinearLayout.HORIZONTAL);
        inner.setGravity(Gravity.CENTER_VERTICAL);
        inner.setPadding(dp(9), dp(8), dp(9), dp(8));
        inner.setMinimumHeight(dp(44));

        // The desktop draws a small channel or bot icon here. A phone has no icon set to draw from, so
        // the tile carries the two characters the two kinds are named by everywhere else in the app.
        TextView kind = text(isRoom ? "#" : "@", Pal.DIM, 12);
        kind.setGravity(Gravity.CENTER);
        kind.setBackground(shape(Pal.CARD2, Pal.LINE, 1, 8));
        inner.addView(kind, new LinearLayout.LayoutParams(dp(26), dp(26)));

        LinearLayout col = new LinearLayout(getContext());
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(dp(10), 0, 0, 0);
        TextView n = bold(text(name, Pal.TXT, 13));
        if (!scope.isEmpty()) {
            // The company a scoped chat belongs to, set beside the bot's name rather than in place of
            // it — and only where two chats would otherwise read as the same row.
            SpannableStringBuilder nm = new SpannableStringBuilder(name).append("  ").append(scope);
            nm.setSpan(new ForegroundColorSpan(Pal.DIM2), name.length(), nm.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
            nm.setSpan(new RelativeSizeSpan(0.88f), name.length(), nm.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
            n.setText(nm);
        }
        n.setSingleLine(true);
        n.setEllipsize(TextUtils.TruncateAt.END);
        TextView l = text(last, Pal.DIM, 12);
        l.setSingleLine(true);
        l.setEllipsize(TextUtils.TruncateAt.END);
        col.addView(n);
        col.addView(l);
        inner.addView(col, new LinearLayout.LayoutParams(0, -2, 1f));
        // `/api/chats` stamps in seconds; everything the phone measures in is milliseconds.
        TextView when = text(Model.ago(Json.num(c.get("ts")) * 1000), Pal.DIM2, 11);
        LinearLayout.LayoutParams wlp = new LinearLayout.LayoutParams(-2, -2);
        wlp.leftMargin = dp(8);
        inner.addView(when, wlp);
        row.addView(inner, new FrameLayout.LayoutParams(-1, -2));

        if (sel) {
            View bar = new View(getContext());
            bar.setBackground(shape(Pal.ACCENT, 3));
            FrameLayout.LayoutParams blp = new FrameLayout.LayoutParams(dp(3), -1, Gravity.LEFT);
            blp.topMargin = dp(9); blp.bottomMargin = dp(9);
            row.addView(bar, blp);
        }
        row.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { open(id, name, isRoom); }
        });
        return row;
    }

    // ---- the drawer's own menu ----------------------------------------------------------------

    /**
     * The row menu, on a long press. The desktop reveals its kebab on hover (`openCtx`, app.js:1976);
     * a phone has no hover, so the gesture that opens the same menu is a press held on the row — and
     * the row is the anchor, so the menu opens where the finger already is.
     *
     * A bot row carries the desktop's whole set, a room row the four it has, in its order and with
     * its labels. Pin and Hide are read from the bot's own record rather than fixed: an item reading
     * "Pin" on a pinned bot is a lie about what the tap will do.
     *
     * `kind` and `group` are what a move needs and nothing else does: the three lists whose order is
     * a stored array — the rooms, the loose bots, and one room's members (`group` is that room).
     */
    private void rowMenu(View anchor, final String id, final String name, final String kind, final String group) {
        boolean isRoom = "channels".equals(kind);
        Bot b = isRoom ? null : bots.get(id);
        PopupMenu p = new PopupMenu(getContext(), anchor);
        // The desktop rearranges the sidebar by dragging a row. A phone cannot spare the long press
        // for that — it is the only way to this menu — so the two moves stand in for the drag. They
        // write the same array through the same endpoint, so both clients agree on the order.
        List<String> shown = shownOrder(kind, group);
        int at = shown.indexOf(id);
        if (at > 0) p.getMenu().add(0, 10, 0, "Move up");
        if (at >= 0 && at < shown.size() - 1) p.getMenu().add(0, 11, 1, "Move down");
        if (isRoom) {
            Room r = rooms.get(id);
            p.getMenu().add(0, 1, 2, r != null && r.pinned ? "Unpin" : "Pin");
            p.getMenu().add(0, 2, 3, "Edit room");
            p.getMenu().add(0, 3, 4, "Clear chat");
            p.getMenu().add(0, 4, 5, "Delete");
        } else {
            p.getMenu().add(0, 1, 2, b != null && b.pinned ? "Unpin" : "Pin");
            p.getMenu().add(0, 2, 3, "Edit profile");
            p.getMenu().add(0, 3, 4, "Duplicate");
            p.getMenu().add(0, 4, 5, b != null && b.hidden ? "Unhide" : "Hide");
            p.getMenu().add(0, 5, 6, "Clear chat");
            p.getMenu().add(0, 6, 7, "Delete");
        }
        p.setOnMenuItemClickListener(new PopupMenu.OnMenuItemClickListener() {
            @Override public boolean onMenuItemClick(MenuItem item) {
                switch (item.getItemId()) {
                    case 10: move(kind, group, id, -1); break;
                    case 11: move(kind, group, id, 1); break;
                    case 1: if (isRoom) pinRoom(id); else flag(id, "pinned"); break;
                    case 2: if (isRoom) editRoom(id); else editBot(id); break;
                    case 3: if (isRoom) clear(id, name); else duplicate(id); break;
                    case 4: if (isRoom) delete(id, name, true); else flag(id, "hidden"); break;
                    case 5: clear(id, name); break;      // a bot's own, past its Hide
                    default: delete(id, name, false); break;
                }
                return true;
            }
        });
        p.show();
    }

    /** One reorderable list as the drawer is showing it — which is what "move up" means to the person
        looking at it. A pinned row floats to the top, so this is not the stored order. */
    private List<String> shownOrder(String kind, String group) {
        List<String> ids = new ArrayList<>();
        if ("channels".equals(kind)) {
            List<Map.Entry<String, Room>> ordered = new ArrayList<>(rooms.entrySet());
            Collections.sort(ordered, new java.util.Comparator<Map.Entry<String, Room>>() {
                @Override public int compare(Map.Entry<String, Room> a, Map.Entry<String, Room> b) {
                    return (b.getValue().pinned ? 1 : 0) - (a.getValue().pinned ? 1 : 0);
                }
            });
            for (Map.Entry<String, Room> e : ordered) ids.add(e.getKey());
        } else if ("members".equals(kind)) {
            Room r = rooms.get(group);
            if (r != null) ids.addAll(r.memberIds);
        } else {
            Set<String> claimed = new LinkedHashSet<>();
            for (Room r : rooms.values()) claimed.addAll(r.memberIds);
            List<Map.Entry<String, Bot>> loose = new ArrayList<>();
            for (Map.Entry<String, Bot> e : bots.entrySet()) {
                if (!e.getValue().hidden && !claimed.contains(e.getKey())) loose.add(e);
            }
            Collections.sort(loose, new java.util.Comparator<Map.Entry<String, Bot>>() {
                @Override public int compare(Map.Entry<String, Bot> a, Map.Entry<String, Bot> b) {
                    return (b.getValue().pinned ? 1 : 0) - (a.getValue().pinned ? 1 : 0);
                }
            });
            for (Map.Entry<String, Bot> e : loose) ids.add(e.getKey());
        }
        return ids;
    }

    /** The whole stored array for one list, in the server's own order — what the endpoint is given. */
    private List<String> storedOrder(String kind, String group) {
        List<String> ids = new ArrayList<>();
        if ("members".equals(kind)) {
            Room r = rooms.get(group);
            if (r != null) ids.addAll(r.memberIds);
        } else if ("channels".equals(kind)) {
            ids.addAll(rooms.keySet());
        } else {
            ids.addAll(bots.keySet());
        }
        return ids;
    }

    /**
     * Move one row past its neighbour and save. The neighbour is the one the person can see, so a
     * pinned row above it is the one it trades places with; the two positions are swapped in the
     * stored array rather than the visible order being written back, because the array also holds the
     * hidden bots and the ones a room has claimed, and those must keep their places.
     */
    private void move(String kind, String group, String id, int dir) {
        List<String> shown = shownOrder(kind, group);
        int at = shown.indexOf(id), to = at + dir;
        if (at < 0 || to < 0 || to >= shown.size()) return;
        List<String> ids = storedOrder(kind, group);
        int a = ids.indexOf(id), c = ids.indexOf(shown.get(to));
        if (a < 0 || c < 0) return;
        ids.set(a, shown.get(to));
        ids.set(c, id);
        StringBuilder body = new StringBuilder("{\"kind\":").append(Json.quote(kind))
            .append(",\"ids\":[");
        for (int i = 0; i < ids.size(); i++) {
            if (i > 0) body.append(',');
            body.append(Json.quote(ids.get(i)));
        }
        body.append(']');
        if (group != null) body.append(",\"id\":").append(Json.quote(group));
        body.append('}');
        send("/api/nav/order", body.toString(), "Could not save the new order.", false);
    }

    /** Pin and Hide are one write with two keys: both flip a flag on the bot's own record, and both
        leave the drawer to be read again, because the row that changed is the server's, not this one. */
    private void flag(String id, String key) {
        Bot b = bots.get(id);
        if (b == null) return;
        boolean on = key.equals("pinned") ? !b.pinned : !b.hidden;
        send("/api/bot", "{\"bot\":{\"id\":" + Json.quote(id) + ",\"" + key + "\":" + on + "}}",
             "Could not change that.", false);
    }

    /** A room's pin. A room has no `hidden` — taking it out of the drawer would take its bots'
        chats with it, and Delete is the honest way to do that — so this is the one flag. */
    private void pinRoom(String id) {
        Room r = rooms.get(id);
        if (r == null) return;
        send("/api/channel", "{\"channel\":{\"id\":" + Json.quote(id) + ",\"pinned\":" + !r.pinned + "}}",
             "Could not change that.", false);
    }

    private void duplicate(String id) {
        send("/api/bot/duplicate", "{\"id\":" + Json.quote(id) + "}", "Could not duplicate that.", false);
    }

    /**
     * Delete, confirmed first: the desktop's own two sentences (`ctxAction`, app.js:2118), because
     * what goes is more than the row — a bot takes its chats in every room with it, a room takes its
     * transcript and its members' chats inside it.
     */
    private void delete(final String id, String name, final boolean isRoom) {
        String what = name == null || name.isEmpty() ? id : name;
        new AlertDialog.Builder(getContext())
            .setTitle("Delete " + what + "?")
            .setMessage(isRoom ? "The room's transcript and its bots' chats inside it go with it."
                               : "Its chats go with it, in every room.")
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Delete", new DialogInterface.OnClickListener() {
                @Override public void onClick(DialogInterface d, int which) { doDelete(id, isRoom); }
            }).show();
    }

    private void doDelete(final String id, final boolean isRoom) {
        // The chat on screen can be the row itself or one scoped inside it, and either way it has
        // just gone: the desktop hands the screen to its first chat, and the drawer's own list lands
        // on the newest when nothing is open — so the chat closes here and that list decides next.
        final boolean orphan = id.equals(sid) || id.equals(isRoom ? scopeId() : botId());
        new Thread(new Runnable() {
            @Override public void run() {
                try {
                    Api.post(base, token, isRoom ? "/api/channel/delete" : "/api/bot/delete",
                             "{\"id\":" + Json.quote(id) + "}");
                    ui.post(new Runnable() {
                        @Override public void run() {
                            if (orphan) close();
                            loadConfig();
                            loadChats();
                        }
                    });
                } catch (IOException e) {
                    ui.post(new Runnable() {
                        @Override public void run() { note("Could not delete that."); }
                    });
                }
            }
        }).start();
    }

    /**
     * The chat on screen went with the row that was deleted: there is nothing to look at, so it
     * closes. `gen` is bumped first, because a turn still streaming into that chat must not land in
     * whatever opens next — and what opens next is the drawer's list, read after this.
     */
    private void close() {
        gen++;
        sid = ""; room = false; chatTitle = "";
        model.clear();
        rows.clear();
        txCol.removeAllViews();
        writes.clear();
        renderQueue();
        setRunning(false);
        input.setHint("Give a task…");
        chips();
        head();
        nav();
        rebuild();
    }

    /**
     * A write that ends in a re-read. Every one of these changes a row the server owns, so the drawer
     * is asked for the roster again rather than patched here — which is what the desktop does after
     * each of its own menu items. A refusal arriving as `ok:false` on a 200 is said out loud, as the
     * desktop's `alert(r.error)` says it; a room pointed at a folder that does not exist is the one
     * that matters.
     */
    private void send(final String path, final String body, final String fail, final boolean chats) {
        new Thread(new Runnable() {
            @Override public void run() {
                try {
                    final Map<String, Object> r = Json.obj(Api.post(base, token, path, body));
                    ui.post(new Runnable() {
                        @Override public void run() {
                            if (r != null && !Json.truth(r.get("ok"))) {
                                String why = Json.str(r.get("error"));
                                note(why.isEmpty() ? fail : why);
                                return;
                            }
                            loadConfig();
                            if (chats) loadChats();   // a rename reaches the chats the drawer lists too
                        }
                    });
                } catch (IOException e) {
                    ui.post(new Runnable() {
                        @Override public void run() { note(fail); }
                    });
                }
            }
        }).start();
    }

    // ---- the editors --------------------------------------------------------------------------

    /**
     * The bot's profile, as a dialog: the fields the desktop's own editor writes (`botEditor`,
     * app.js:2827), kept to the identity and the brain. What is left out is what this screen has no
     * honest control for — the face (a canvas the desktop draws), the skills and the tool list
     * (lists the drawer never reads) — and nothing here invents a field the endpoint does not take.
     */
    private void editBot(final String id) {
        final Bot b = bots.get(id);
        if (b == null || b.raw == null) return;
        Map<String, Object> r = b.raw;

        LinearLayout col = form();
        final EditText name = field(col, "Name", Json.str(r.get("name")));
        final EditText emoji = field(col, "Emoji", Json.str(r.get("emoji")));
        final EditText title = field(col, "Title", Json.str(r.get("title")));
        final EditText role = field(col, "Role (one line)", Json.str(r.get("role")));
        final String[] color = { Json.str(r.get("color")) };
        choice(col, "Color", color, HUES, HUES);
        final String[] model = { Json.str(r.get("model")) };
        String[] names = modelNames(model[0]);
        choice(col, "Model", model, names, names);
        final String[] approval = { Json.str(r.get("approval")) };
        String[] levelLabels = new String[LEVELS.length];
        for (int i = 0; i < LEVELS.length; i++) levelLabels[i] = modeLabel(LEVELS[i]);
        choice(col, "Approval level", approval, LEVELS, levelLabels);
        CheckBox memory = new CheckBox(getContext());
        memory.setText("Let this bot use memory");
        memory.setChecked(!Boolean.FALSE.equals(r.get("memory")));
        memory.setTextColor(Pal.TXT);
        memory.setTextSize(Pal.fs(14));
        memory.setButtonTintList(ColorStateList.valueOf(Pal.ACCENT));
        LinearLayout.LayoutParams mlp = new LinearLayout.LayoutParams(-1, -2);
        mlp.topMargin = dp(10);
        col.addView(memory, mlp);
        final EditText instructions = field(col, "Standing instructions", Json.str(r.get("instructions")), true);

        // The picture. The desktop draws a bot from a species, and can turn a photo into its face
        // (`/api/avatar/transform`) — both need the face engine, which this phone has none of, so it
        // offers the picture itself and says where the rest lives. The cache is warm because the
        // drawer drew this very row a moment ago.
        final int version = (int) Json.num(r.get("avatar"));
        LinearLayout faceRow = new LinearLayout(getContext());
        faceRow.setOrientation(LinearLayout.HORIZONTAL);
        faceRow.setGravity(Gravity.CENTER_VERTICAL);
        // The face is always drawn, even on a cold cache — the drawer warms it for every bot it lists,
        // but a hidden bot is not listed, and a blank box beside "Replace picture…" would read as a
        // broken picture rather than as one that has not arrived yet. The monogram is what it falls
        // back to, which is what the row itself falls back to.
        Bitmap thumb = avatar(id, b);
        View face = thumb == null
                ? tile(b.name, b.color, b.emoji, 12, 9)
                : picture(thumb, b.color, b.name, 9);
        faceRow.addView(face, new LinearLayout.LayoutParams(dp(34), dp(34)));
        TextView pickPic = text(version > 0 ? "Replace picture…" : "Choose picture…", Pal.TXT, 13);
        pickPic.setPadding(dp(13), dp(10), dp(13), dp(10));
        pickPic.setBackground(press(shape(0, Pal.LINE2, 1, 9)));
        pickPic.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { pickPicture(id, true); }
        });
        faceRow.addView(pickPic, spaced(10));
        if (version > 0) {
            TextView rm = text("Remove", Pal.DIM, 13);
            rm.setPadding(dp(13), dp(10), dp(13), dp(10));
            rm.setBackground(press(shape(0, 9)));
            rm.setOnClickListener(new OnClickListener() {
                @Override public void onClick(View v) { dropPicture(id, true); }
            });
            faceRow.addView(rm, spaced(8));
        }
        caption(col, "Face picture", faceRow);
        col.addView(faceRow);
        TextView faceHint = text(version > 0
                ? "This picture is the bot's face here. On a computer, introduce one and the image model redraws it as a cute face."
                : "A picture becomes this bot's face here. On a computer, introduce one and the image model redraws it.",
            Pal.DIM2, 12);
        faceHint.setPadding(dp(2), dp(7), dp(2), 0);
        col.addView(faceHint);

        new AlertDialog.Builder(getContext())
            .setTitle("Edit profile")
            .setView(scrolled(col))
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Save", new DialogInterface.OnClickListener() {
                @Override public void onClick(DialogInterface d, int which) {
                    String nm = name.getText().toString().trim();
                    if (nm.isEmpty()) { note("Give the bot a name."); return; }   // the desktop's own refusal
                    String body = "{\"bot\":{\"id\":" + Json.quote(id)
                        + ",\"name\":" + Json.quote(nm)
                        + ",\"emoji\":" + Json.quote(emoji.getText().toString().trim())
                        + ",\"title\":" + Json.quote(title.getText().toString().trim())
                        + ",\"role\":" + Json.quote(role.getText().toString().trim())
                        + ",\"color\":" + Json.quote(color[0])
                        + ",\"model\":" + Json.quote(model[0])
                        + ",\"approval\":" + Json.quote(approval[0])
                        + ",\"memory\":" + memory.isChecked()
                        + ",\"instructions\":" + Json.quote(instructions.getText().toString()) + "}}";
                    send("/api/bot", body, "Could not save the bot.", true);
                }
            }).show();
    }

    /**
     * The room, as a dialog: the fields the desktop's own editor writes (`editChannel`, app.js:2730).
     * The members are the one set among them, and a set is the one thing a dialog of single choices
     * cannot carry; the logo is the one field that opens another screen.
     */
    private void editRoom(final String id) {
        final Room room = rooms.get(id);
        if (room == null || room.raw == null) return;
        Map<String, Object> r = room.raw;

        LinearLayout col = form();
        final EditText name = field(col, "Name", Json.str(r.get("name")));
        final String[] mode = { Json.str(r.get("mode")) };
        choice(col, "Responder", mode, new String[]{ "lead", "auto", "everyone" },
               new String[]{ "Lead bot answers", "Auto (a fast model picks)", "Everyone answers" });

        // Every bot, not only the current members: the desktop's own LEAD list is every bot there is.
        String[] who = bots.keySet().toArray(new String[0]);
        String[] whoNames = new String[who.length];
        for (int i = 0; i < who.length; i++) {
            Bot m = bots.get(who[i]);
            whoNames[i] = m == null || m.name.isEmpty() ? who[i] : m.name;
        }
        final String[] lead = { Json.str(r.get("lead")) };
        choice(col, "Lead", lead, who, whoNames);
        final Set<String> members = new LinkedHashSet<>();
        for (Object o : asList(r.get("members"))) members.add(Json.str(o));
        tick(col, "Members", who, whoNames, members);

        final EditText instructions = field(col, "Shared instructions", Json.str(r.get("instructions")));
        final EditText folder = field(col, "Repo folder", Json.str(r.get("folder")));

        // The logo is the one field the desktop's editor has that this screen could not carry before:
        // the picker here is the phone's own, so the image is chosen where your images are and sent as
        // the data URL the endpoint parses.
        LinearLayout logoRow = new LinearLayout(getContext());
        logoRow.setOrientation(LinearLayout.HORIZONTAL);
        logoRow.setGravity(Gravity.CENTER_VERTICAL);
        TextView pick = text(room.logo > 0 ? "Replace logo…" : "Choose logo…", Pal.TXT, 13);
        pick.setPadding(dp(13), dp(10), dp(13), dp(10));
        pick.setBackground(press(shape(0, Pal.LINE2, 1, 9)));
        pick.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { pickPicture(id, false); }
        });
        logoRow.addView(pick);
        if (room.logo > 0) {
            TextView rm = text("Remove", Pal.DIM, 13);
            rm.setPadding(dp(13), dp(10), dp(13), dp(10));
            rm.setBackground(press(shape(0, 9)));
            rm.setOnClickListener(new OnClickListener() {
                @Override public void onClick(View v) { dropPicture(id, false); }
            });
            logoRow.addView(rm, spaced(8));
        }
        caption(col, "Logo", logoRow);
        col.addView(logoRow);

        new AlertDialog.Builder(getContext())
            .setTitle("Edit room")
            .setView(scrolled(col))
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Save", new DialogInterface.OnClickListener() {
                @Override public void onClick(DialogInterface d, int which) {
                    String body = "{\"channel\":{\"id\":" + Json.quote(id)
                        + ",\"name\":" + Json.quote(name.getText().toString().trim())
                        + ",\"mode\":" + Json.quote(mode[0])
                        + ",\"lead\":" + Json.quote(lead[0])
                        + ",\"members\":" + array(members)
                        + ",\"instructions\":" + Json.quote(instructions.getText().toString())
                        + ",\"folder\":" + Json.quote(folder.getText().toString().trim()) + "}}";
                    send("/api/channel", body, "Could not save the room.", true);
                }
            }).show();
    }

    // ---- a room's logo, and a bot's avatar ------------------------------------------------------

    /** What the host activity's `onActivityResult` is looking at: the row the pick was made for, and
        which of the two pictures it is. One request code covers both, because the endpoint is the only
        difference between them — a second code would be a second copy of everything below. */
    static final int PICK_PICTURE = 4001;
    private String pickFor;
    private boolean pickAvatar;

    /** Ask the phone's own picker for an image. A view has no result of its own, so the host hands
        it back through {@link #picturePicked}. */
    private void pickPicture(String id, boolean avatar) {
        pickFor = id;
        pickAvatar = avatar;
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        i.addCategory(Intent.CATEGORY_OPENABLE);
        i.setType("image/*");
        try {
            ((android.app.Activity) getContext()).startActivityForResult(i, PICK_PICTURE);
        } catch (android.content.ActivityNotFoundException e) {
            pickFor = null;
            note("This phone has no file picker.");
        }
    }

    /** The picker came back. An image is read and sent as the data URL the endpoint parses; a cancel
        does nothing at all. */
    void picturePicked(Intent data) {
        final String id = pickFor;
        final boolean avatar = pickAvatar;
        pickFor = null;
        if (id == null || data == null || data.getData() == null) return;
        final android.net.Uri uri = data.getData();
        final String what = avatar ? "avatar" : "logo";
        new Thread(new Runnable() {
            @Override public void run() {
                final String url = dataUrl(uri);
                if (url == null) {
                    ui.post(new Runnable() {
                        @Override public void run() { note("Could not read that image."); }
                    });
                    return;
                }
                String err = "";
                try {
                    Map<String, Object> r = Json.obj(Api.post(base, token, "/api/" + what,
                            "{\"id\":" + Json.quote(id) + ",\"data\":" + Json.quote(url) + "}"));
                    if (r == null || Boolean.FALSE.equals(r.get("ok"))) err = Json.str(r == null ? "" : r.get("error"));
                } catch (IOException e) {
                    err = avatar ? "Could not save the picture." : "Could not save the logo.";
                }
                final String why = err;
                ui.post(new Runnable() {
                    @Override public void run() {
                        if (!why.isEmpty()) { note(why); return; }
                        // A new upload is a new version, so nothing cached is right any more, and the
                        // row that draws it comes from the roster — so the roster is what is re-read.
                        logos.clear();
                        loadConfig();
                    }
                });
            }
        }).start();
    }

    /** Take a room's logo or a bot's avatar off. The monogram is what the row falls back to. */
    private void dropPicture(final String id, final boolean avatar) {
        new Thread(new Runnable() {
            @Override public void run() {
                try {
                    Api.post(base, token, avatar ? "/api/avatar/remove" : "/api/logo/remove",
                             "{\"id\":" + Json.quote(id) + "}");
                } catch (IOException ignored) {
                    // Nothing to say: the row is redrawn from the roster either way, so a failure
                    // shows as the picture still being there.
                }
                ui.post(new Runnable() {
                    @Override public void run() { logos.clear(); loadConfig(); }
                });
            }
        }).start();
    }

    /** A picked image, wrapped as the data URL the endpoint parses. The MIME type is the picker's
        word for it and only a hint: the server checks the bytes before it keeps them. */
    private String dataUrl(android.net.Uri uri) {
        java.io.InputStream in = null;
        try {
            in = getContext().getContentResolver().openInputStream(uri);
            if (in == null) return null;
            java.io.ByteArrayOutputStream b = new java.io.ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) b.write(buf, 0, n);
            byte[] raw = b.toByteArray();
            if (raw.length == 0 || raw.length > 4 * 1024 * 1024) return null;   // the server's own cap is 2 MB
            String mime = getContext().getContentResolver().getType(uri);
            if (mime == null || !mime.startsWith("image/")) mime = "image/png";
            return "data:" + mime + ";base64," + Base64.encodeToString(raw, Base64.NO_WRAP);
        } catch (IOException e) {
            return null;
        } finally {
            if (in != null) try { in.close(); } catch (IOException ignored) { }
        }
    }

    /** A form too long for one screen. A dialog is not scrollable on its own and clips what does not
        fit — the picture row was the one that pushed the bot's editor over — so the column goes in a
        ScrollView. A short form is unaffected: the scroll only appears when there is more to reach. */
    private View scrolled(View col) {
        ScrollView s = new ScrollView(getContext());
        s.addView(col, new ViewGroup.LayoutParams(-1, -2));
        return s;
    }

    /** The dialog's own column: the desktop stacks its editor's fields down a panel, and so does this. */
    private LinearLayout form() {
        LinearLayout col = new LinearLayout(getContext());
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(dp(20), 0, dp(20), dp(4));
        return col;
    }

    /** A field's caption, in the desktop's own small caps, tied to the control under it so a screen
        reader says what the field is rather than reading a bare value out of the blue. */
    private void caption(LinearLayout col, String label, View control) {
        TextView t = bold(text(label.toUpperCase(Locale.getDefault()), Pal.DIM2, 11));
        t.setLetterSpacing(0.06f);
        t.setPadding(dp(2), dp(13), dp(2), dp(5));
        control.setId(View.generateViewId());
        t.setLabelFor(control.getId());
        col.addView(t);
    }

    /** One text field, with its caption above it, in the order the desktop's editor reads. */
    private EditText field(LinearLayout col, String label, String value, boolean multiline) {
        EditText e = new EditText(getContext());
        e.setText(value);
        e.setTextColor(Pal.TXT);
        e.setTextSize(Pal.fs(14));
        e.setHintTextColor(Pal.DIM2);
        e.setBackground(shape(Pal.CARD, Pal.LINE, 1, 9));
        e.setPadding(dp(11), dp(9), dp(11), dp(9));
        e.setInputType(InputType.TYPE_CLASS_TEXT
                | (multiline ? InputType.TYPE_TEXT_FLAG_MULTI_LINE : 0));
        if (multiline) { e.setMinLines(3); e.setGravity(Gravity.TOP); }
        caption(col, label, e);
        col.addView(e);
        return e;
    }

    private EditText field(LinearLayout col, String label, String value) {
        return field(col, label, value, false);
    }

    /**
     * One field that opens a list: the desktop's `select`, as a dialog a thumb can work. The value
     * lives in the caller's own box, because the form reads it back when Save is pressed, and the row
     * shows the label rather than the value — which is why the two arrays are separate: a level is
     * read as "Plan only" and written as "plan".
     */
    private void choice(LinearLayout col, final String label, final String[] box,
                        final String[] values, final String[] labels) {
        final TextView t = text("", Pal.TXT, 14);
        t.setSingleLine(true);
        t.setEllipsize(TextUtils.TruncateAt.END);
        t.setPadding(dp(11), dp(10), dp(11), dp(10));
        t.setBackground(press(shape(Pal.CARD, Pal.LINE, 1, 9)));
        int sel = at(values, box[0]);
        t.setText(values.length == 0 ? "—" : labels[Math.max(0, sel)]);
        t.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) {
                if (values.length == 0) { note("Nothing to pick from yet."); return; }
                new AlertDialog.Builder(getContext()).setTitle(label)
                    .setSingleChoiceItems(labels, at(values, box[0]), new DialogInterface.OnClickListener() {
                        @Override public void onClick(DialogInterface d, int which) {
                            box[0] = values[which];
                            t.setText(labels[which]);
                            d.dismiss();
                        }
                    }).show();
            }
        });
        caption(col, label, t);
        col.addView(t);
    }

    /** Where a value sits in its own list, or -1 — a choice dialog shows nothing selected then. */
    private static int at(String[] values, String v) {
        for (int i = 0; i < values.length; i++) if (values[i].equals(v)) return i;
        return -1;
    }

    /** The models the router lists, with the bot's own in front when that list has since lost it —
        otherwise the one it wears now would be the one value this form could not show. */
    private String[] modelNames(String cur) {
        List<String> all = new ArrayList<>();
        if (!cur.isEmpty() && !models.contains(cur)) all.add(cur);
        all.addAll(models);
        return all.toArray(new String[0]);
    }

    /** The members tick-list: the one field here that is a set, and the one dialog that can hold a
        set. It stays open while you tick, which is what picking several of something needs. */
    private void tick(LinearLayout col, final String label, final String[] values,
                      final String[] labels, final Set<String> on) {
        final TextView t = text("", Pal.TXT, 14);
        t.setSingleLine(true);
        t.setEllipsize(TextUtils.TruncateAt.END);
        t.setPadding(dp(11), dp(10), dp(11), dp(10));
        t.setBackground(press(shape(Pal.CARD, Pal.LINE, 1, 9)));
        tickText(t, on, values, labels);
        t.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) {
                if (values.length == 0) { note("Nothing to pick from yet."); return; }
                boolean[] checked = new boolean[values.length];
                for (int i = 0; i < values.length; i++) checked[i] = on.contains(values[i]);
                new AlertDialog.Builder(getContext()).setTitle(label)
                    .setMultiChoiceItems(labels, checked, new DialogInterface.OnMultiChoiceClickListener() {
                        @Override public void onClick(DialogInterface d, int which, boolean isChecked) {
                            if (isChecked) on.add(values[which]); else on.remove(values[which]);
                            tickText(t, on, values, labels);
                        }
                    })
                    .setPositiveButton("Done", null).show();
            }
        });
        caption(col, label, t);
        col.addView(t);
    }

    /** What is ticked, read back on the row: a dialog holds the list, so the row holds the answer. */
    private static void tickText(TextView t, Set<String> on, String[] values, String[] labels) {
        StringBuilder b = new StringBuilder();
        for (int i = 0; i < values.length; i++) {
            if (!on.contains(values[i])) continue;
            if (b.length() > 0) b.append(", ");
            b.append(labels[i]);
        }
        t.setText(b.length() == 0 ? "none" : b.toString());
    }

    /** A JSON array of strings, for the one body here that carries a list — a room's members. */
    private static String array(Set<String> items) {
        StringBuilder b = new StringBuilder("[");
        for (String s : items) {
            if (b.length() > 1) b.append(",");
            b.append(Json.quote(s));
        }
        return b.append("]").toString();
    }

    // ---- one conversation --------------------------------------------------------------------

    private void open(String id, String name, boolean isRoom) {
        closeDrawer();
        sid = id;
        room = isRoom;
        final int g = ++gen;
        chatTitle = name == null || name.isEmpty() ? id : name;
        model.chat(chatTitle, isRoom);
        model.clear();          // the previous chat's transcript must not flash under this one's title
        rows.clear();
        txCol.removeAllViews();
        // The strip and the writes belong to the chat they were drawn for: another chat's rows on
        // screen would be reporting work you are not looking at, under a title that is not theirs.
        // The queue does not — a task waiting on another chat's turn keeps waiting on it.
        writes.clear();
        renderQueue();
        setRunning(false);
        input.setHint(isRoom ? "Message the room… (@mention a bot)" : "Give a task…");
        chips();
        head();
        nav();
        follow();
        reload(id);
    }

    /**
     * Re-read one chat's saved transcript and draw it.
     *
     * Used when a chat is opened, and again when a turn another client ran in it ends: the streamed
     * cards were the live view, and the saved record is what the chat goes back to — which is what
     * the window that ran the turn does at its own end. See `reloadTranscript`, app.js:984.
     */
    private void reload(final String id) {
        final int g = gen;
        new Thread(new Runnable() {
            @Override public void run() {
                try {
                    final Map<String, Object> h = Json.obj(Api.get(base, token, "/api/history?session=" + Targets.encode(id)));
                    ui.post(new Runnable() {
                        @Override public void run() {
                            if (g != gen || !id.equals(sid)) return;
                            render(h);
                            // A task this chat queued while its turn ran is still waiting on it, and
                            // nothing else will come along to start it — so it goes now, on top of the
                            // transcript that just landed.
                            drainQueue(id);
                        }
                    });
                } catch (IOException e) {
                    ui.post(new Runnable() {
                        @Override public void run() { if (g == gen) note("Could not open that chat."); }
                    });
                }
            }
        }).start();
    }

    private void render(Map<String, Object> h) {
        saved = h == null ? new ArrayList<Object>() : asList(h.get("messages"));
        model.load(h == null ? null : asList(h.get("messages")));
        if (h != null) {
            String ap = Json.str(h.get("approval"));
            if (ap.isEmpty()) ap = Json.str(h.get("approval_own"));   // the bot's own level, when the chat has none
            // Read after the messages: `load` clears the chips, so a meta set before it would be wiped.
            model.meta(h.get("model"), ap.isEmpty() ? "ask" : ap, h.get("ctx"));
            Map<String, Object> pending = row(h.get("pending"));
            // A card the turn is parked on is not in the saved conversation — it belongs to the turn,
            // not to the transcript — so a chat reopened while it waits would show the work and none
            // of the question. It is drawn from the pending record, as the desktop's redraw draws it.
            if (pending != null) {
                Model.Entry e = new Model.Entry();
                e.kind = Model.APPROVAL;
                e.who = Json.str(pending.get("agent"));
                e.text = Json.str(pending.get("cmd"));
                model.entries().add(e);
            }
        }
        // A reopened chat is the same transcript, so a tool that failed while you were away opens
        // itself here too: the row is built folded, and the reason is in the body.
        for (Model.Entry e : model.entries()) {
            if (e.kind == Model.TOOL && e.done && failed(e.sub, e.text)) e.open = true;
        }
        chips();
        head();
        rebuild();
    }

    private void rebuild() {
        txCol.removeAllViews();
        rows.clear();
        if (model.entries().isEmpty()) {
            txCol.addView(empty(), rowParams());
            stick();
            return;
        }
        for (Model.Entry e : model.entries()) {
            View v = build(e);
            rows.add(v);
            txCol.addView(v, rowParams());
        }
        stick();
    }

    /** Redraw just the entry that changed. If the transcript changed shape — a reply that came back
        empty is dropped — every index after it moved, so the whole thing is rebuilt instead. */
    private void paint(int i) {
        if (model.entries().size() != rows.size()) { rebuild(); return; }
        if (i < 0 || i >= model.entries().size()) return;
        View v = build(model.entries().get(i));
        if (i < rows.size()) {
            View old = rows.get(i);
            int at = txCol.indexOfChild(old);
            txCol.removeViewAt(at);
            txCol.addView(v, at, rowParams());
            rows.set(i, v);
        } else {
            rows.add(v);
            txCol.addView(v, rowParams());
        }
        stick();
    }

    /** The gap belongs to the row, because a row is inserted mid-transcript when an event lands. */
    private LinearLayout.LayoutParams rowParams() {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = dp(16);
        return lp;
    }

    /** New output follows the reader only when the reader is already at the newest of it. */
    private void stick() {
        if (following) follow();
        else jump.setVisibility(VISIBLE);
    }

    private void follow() {
        following = true;
        ui.removeCallbacks(resume);
        jump.setVisibility(GONE);
        txScroll.post(down);
    }

    // ---- the header --------------------------------------------------------------------------

    private View header(Context c) {
        LinearLayout h = new LinearLayout(c);
        h.setOrientation(LinearLayout.VERTICAL);
        h.setBackgroundColor(Pal.BG);
        // There is no action bar and, from Android 15, no window that stops at the status bar: the
        // clock is drawn over the app. The inset goes into this header's own padding rather than into
        // a margin, so its colour runs up behind the clock and its first line starts below it.
        h.setOnApplyWindowInsetsListener(new OnApplyWindowInsetsListener() {
            @Override public WindowInsets onApplyWindowInsets(View v, WindowInsets ins) {
                v.setPadding(0, ins.getSystemWindowInsetTop(), 0, 0);
                return ins;
            }
        });

        LinearLayout bar = new LinearLayout(c);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setPadding(dp(12), dp(8), dp(12), dp(8));
        bar.setMinimumHeight(dp(56));

        TextView menu = text("‹", Pal.TXT, 28);
        menu.setGravity(Gravity.CENTER);
        menu.setContentDescription("Chats and bots");
        menu.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { openDrawer(); }
        });
        bar.addView(menu, new LayoutParams(dp(44), dp(44)));

        hDot = new View(c);
        hDot.setBackground(oval(Pal.DOT));
        LinearLayout.LayoutParams dot = new LinearLayout.LayoutParams(dp(9), dp(9));
        dot.leftMargin = dp(4);
        bar.addView(hDot, dot);

        // The face. The desktop puts the bot's face in the corner mascot (`dockFace`, app.js:410) and
        // a phone has no corner to put one in, so the header is the only thing that answers "who am I
        // talking to". The dot stays beside it: the dot carries run state and the face does not.
        hFace = new FrameLayout(c);
        LinearLayout.LayoutParams flp = new LinearLayout.LayoutParams(dp(26), dp(26));
        flp.leftMargin = dp(9);
        bar.addView(hFace, flp);

        LinearLayout col = new LinearLayout(c);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(dp(10), 0, dp(8), 0);
        hName = bold(text("Anzen-bot", Pal.TXT, 17));
        hName.setSingleLine(true);
        hName.setEllipsize(TextUtils.TruncateAt.END);
        hName.setLetterSpacing(-0.012f);          // the desktop's -0.2px, at 17sp
        hStatus = text("idle", Pal.DIM, 12);
        hStatus.setSingleLine(true);
        hStatus.setEllipsize(TextUtils.TruncateAt.END);
        hStatus.setMaxWidth(getResources().getDisplayMetrics().widthPixels * 38 / 100);
        col.addView(hName);
        col.addView(hStatus);
        bar.addView(col, new LinearLayout.LayoutParams(0, -2, 1f));

        TextView more = text("⋯", Pal.DIM, 24);
        more.setGravity(Gravity.CENTER);
        more.setContentDescription("More");
        more.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { menu(v); }
        });
        bar.addView(more, new LayoutParams(dp(44), dp(44)));
        h.addView(bar, new LayoutParams(-1, -2));

        chips = new LinearLayout(c);
        chips.setOrientation(LinearLayout.HORIZONTAL);
        chips.setGravity(Gravity.CENTER_VERTICAL);
        chips.setPadding(dp(12), 0, dp(12), dp(8));
        chipModel = chip("Model: none", new OnClickListener() {
            @Override public void onClick(View v) { pickModel(); }
        });
        // A model name can be long enough to push the other two chips off the strip, so this one gives
        // up its own tail first — the strip scrolls, but the chip should not have to.
        chipModel.setMaxWidth(dp(230));
        chipModel.setEllipsize(TextUtils.TruncateAt.END);
        chipApproval = chip("Approval: —", new OnClickListener() {
            @Override public void onClick(View v) { pickApproval(); }
        });
        chipCtx = chip("Context: —", new OnClickListener() {
            @Override public void onClick(View v) { showCtx(); }
        });
        chips.addView(chipModel);
        chips.addView(chipApproval, chipSpace());
        chips.addView(chipCtx, chipSpace());
        HorizontalScrollView strip = new HorizontalScrollView(c);
        strip.setHorizontalScrollBarEnabled(false);   // the desktop wraps these; a phone scrolls them instead
        strip.addView(chips, new ViewGroup.LayoutParams(-2, -2));
        h.addView(strip, new LayoutParams(-1, dp(36)));

        View edge = new View(c);
        edge.setBackgroundColor(Pal.LINE);
        h.addView(edge, new LayoutParams(-1, dp(1)));
        return h;
    }

    private TextView chip(String label, OnClickListener tap) {
        TextView t = text(label, Pal.DIM, 12);
        t.setGravity(Gravity.CENTER_VERTICAL);
        t.setSingleLine(true);
        t.setPadding(dp(10), dp(6), dp(10), dp(6));
        t.setMinHeight(dp(36));
        t.setBackground(press(shape(Pal.CARD, Pal.LINE, 1, 999)));
        t.setOnClickListener(tap);
        return t;
    }

    private LinearLayout.LayoutParams chipSpace() {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-2, -2);
        lp.leftMargin = dp(5);
        return lp;
    }

    private void head() {
        Bot b = room ? null : bots.get(botId());
        String emoji = b == null ? "" : b.emoji;
        // Nothing to land on is a state of its own, and a name is how the header says so.
        String name = sid.isEmpty() ? "No chats yet" : chatTitle.isEmpty() ? "Anzen-bot" : chatTitle;
        hName.setText((emoji.isEmpty() ? "" : emoji + "  ") + name);
        // A card on screen is asking something whatever the state says: reopening a chat that is parked
        // on one loads no turn with it, and "idle" beside a waiting card is a plain contradiction.
        boolean asked = pending();
        // The state word alone. The desktop keeps no clock up here — elapsed time belongs to the tool
        // row that is running, and to the working strip beside the composer.
        hStatus.setText(asked ? Model.stateLabel("approval") : Model.stateLabel(model.state()));
        hStatus.setTextColor(asked ? Pal.WARN : Pal.DIM);
        hDot.setBackground(oval(turnStart != 0 ? Pal.ACCENT : Pal.DOT));
        headFace();
    }

    /** The chat's face in the header, drawn on every {@link #head()} because switching chats changes
        who it is: a room wears its logo, a bot its avatar, and either falls back to the monogram. The
        picture arrives on a thread the first time, and the fetch redraws this when it lands. */
    private void headFace() {
        hFace.removeAllViews();
        View face;
        if (room) {
            Room r = rooms.get(sid);
            face = r == null ? tile(chatTitle, "blue", "", FACE_SMALL_FS, FACE_SMALL_R)
                             : tileOrLogo(sid, r, FACE_SMALL_FS, FACE_SMALL_R);
        } else {
            face = tileOrAvatar(botId(), FACE_SMALL_FS, FACE_SMALL_R);
        }
        hFace.addView(face, new FrameLayout.LayoutParams(-1, -1));
    }

    /** Whether a card on screen is waiting for an answer — the one state that is asking something. */
    private boolean pending() {
        for (Model.Entry e : model.entries()) if (e.kind == Model.APPROVAL && !e.done) return true;
        return false;
    }

    /** What your own messages are labelled. Yours is not a bot's name, so it never takes a hue. */
    private String you() {
        String n = Json.str(settings.get("user_name")).trim();
        return n.isEmpty() ? "Client" : n;
    }

    /** The bot behind the chat on screen: a room's id is not a bot, a scoped chat's is the last part. */
    private String botId() {
        int cut = sid.lastIndexOf('/');
        return cut < 0 ? sid : sid.substring(cut + 1);
    }

    /** The room a scoped chat lives in — `studio/builder` reads as `studio` — or "" for a plain one. */
    private String scopeId() {
        int cut = sid.lastIndexOf('/');
        return cut < 0 ? "" : sid.substring(0, cut);
    }

    /** The room a scoped chat lives in — `studio/builder` — or null when the chat is just a bot. */
    private Room scope() {
        String id = scopeId();
        return id.isEmpty() ? null : rooms.get(id);
    }

    private void menu(View anchor) {
        PopupMenu p = new PopupMenu(getContext(), anchor);
        p.getMenu().add("Files");
        p.getMenu().add("Computer");
        p.getMenu().add("Clear this conversation");
        p.setOnMenuItemClickListener(new PopupMenu.OnMenuItemClickListener() {
            @Override public boolean onMenuItemClick(MenuItem item) {
                String s = item.getTitle().toString();
                if ("Files".equals(s)) filesSheet("");
                else if ("Computer".equals(s)) computerSheet();
                else clear();
                return true;
            }
        });
        p.show();
    }

    /* The chat's own folder, as the desktop's side panel shows it. What the desktop does with a file —
       open it on that machine — a phone cannot do, so a tap does the one thing that is useful here:
       the path goes into the composer, where the bot's own read tool resolves it against the same root.
       See the panel's own markup, index.html:1158, and `/api/files`, server.py:6376. */

    private String filesAt = "";
    private TextView filesCrumb;
    private LinearLayout filesList;

    private void filesSheet(String path) {
        LinearLayout card = new LinearLayout(getContext());
        card.setOrientation(LinearLayout.VERTICAL);
        card.setBackground(shape(Pal.BG2, Pal.LINE, 1, 18, 18, 0, 0));
        card.setPadding(dp(16), dp(14), dp(16), dp(16));

        LinearLayout top = new LinearLayout(getContext());
        top.setOrientation(LinearLayout.HORIZONTAL);
        top.setGravity(Gravity.CENTER_VERTICAL);
        top.addView(bold(text("Files", Pal.TXT, 16)), new LinearLayout.LayoutParams(0, -2, 1f));
        TextView again = text("Refresh", Pal.DIM, 13);
        again.setPadding(dp(12), dp(7), dp(12), dp(7));
        again.setBackground(press(shape(0, Pal.LINE2, 1, 999)));
        again.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { files(filesAt); }
        });
        top.addView(again);
        TextView x = text("×", Pal.DIM, 20);
        x.setPadding(dp(10), 0, dp(4), 0);
        x.setContentDescription("Close");
        x.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { closeSheet(); }
        });
        top.addView(x, spaced(8));
        card.addView(top);

        filesCrumb = text("", Pal.DIM2, 12);
        filesCrumb.setSingleLine(true);
        filesCrumb.setEllipsize(TextUtils.TruncateAt.START);   // the tail is where you are
        LinearLayout.LayoutParams clp = new LinearLayout.LayoutParams(-1, -2);
        clp.topMargin = dp(8); clp.bottomMargin = dp(6);
        card.addView(filesCrumb, clp);

        filesList = new LinearLayout(getContext());
        filesList.setOrientation(LinearLayout.VERTICAL);
        Cap sc = new Cap(getContext(), dp(400));
        sc.addView(filesList, new ViewGroup.LayoutParams(-1, -2));
        card.addView(sc, new LinearLayout.LayoutParams(-1, -2));

        openSheet(card);
        files(path);
    }

    private void files(final String path) {
        final int g = gen;
        new Thread(new Runnable() {
            @Override public void run() {
                Map<String, Object> d;
                try {
                    d = Json.obj(Api.get(base, token, "/api/files?session=" + Targets.encode(sid)
                            + "&path=" + Targets.encode(path)));
                } catch (IOException e) {
                    d = null;
                }
                final Map<String, Object> got = d;
                ui.post(new Runnable() {
                    @Override public void run() { if (g == gen) filesFill(got, path); }
                });
            }
        }).start();
    }

    private void filesFill(Map<String, Object> d, String path) {
        if (filesList == null) return;       // the sheet was closed while this was in flight
        filesList.removeAllViews();
        filesAt = path;
        if (d == null || !Json.truth(d.get("ok"))) {
            String why = d == null ? "Could not reach the server." : Json.str(d.get("error"));
            filesCrumb.setText("");
            filesList.addView(text(why.isEmpty() ? "Could not read that folder." : why, Pal.DIM2, 13));
            return;
        }
        String root = Json.str(d.get("root"));
        filesCrumb.setText(path.isEmpty() ? root : root + "/" + path);

        if (!path.isEmpty()) {
            int cut = path.lastIndexOf('/');
            filesRow("..", cut < 0 ? "" : path.substring(0, cut), true, 0);
        }
        for (Object o : asList(d.get("entries"))) {
            Map<String, Object> e = row(o);
            if (e == null) continue;
            String name = Json.str(e.get("name"));
            boolean dir = Json.truth(e.get("dir"));
            filesRow(name, path.isEmpty() ? name : path + "/" + name, dir, Json.num(e.get("size")));
        }
        long more = Json.num(d.get("more"));
        if (more > 0) filesList.addView(text("…" + more + " more", Pal.DIM2, 12));
        if (filesList.getChildCount() == 0) filesList.addView(text("This folder is empty.", Pal.DIM2, 13));
    }

    /** One row of the folder: a folder descends, a file goes into the composer as a path the bot can
        read. A held press offers the two things you might want instead. */
    private void filesRow(String name, final String rel, final boolean dir, long bytes) {
        LinearLayout row = new LinearLayout(getContext());
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setBackground(press(shape(0, 9)));
        row.setPadding(dp(11), dp(10), dp(11), dp(10));
        TextView n = text(dir ? name + "/" : name, dir ? Pal.TXT : Pal.DIM, 13);
        n.setSingleLine(true);
        n.setEllipsize(TextUtils.TruncateAt.END);
        row.addView(n, new LinearLayout.LayoutParams(0, -2, 1f));
        if (!dir && bytes > 0) row.addView(text(size(bytes), Pal.DIM2, 11), spaced(8));
        row.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) {
                if (dir) files(rel); else into(rel);
            }
        });
        row.setOnLongClickListener(new OnLongClickListener() {
            @Override public boolean onLongClick(View v) {
                PopupMenu m = new PopupMenu(getContext(), v);
                m.getMenu().add("Copy path");
                m.getMenu().add("Add to chat");
                m.setOnMenuItemClickListener(new PopupMenu.OnMenuItemClickListener() {
                    @Override public boolean onMenuItemClick(MenuItem it) {
                        if ("Copy path".equals(it.getTitle().toString())) copy(rel); else into(rel);
                        return true;
                    }
                });
                m.show();
                return true;
            }
        });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.bottomMargin = dp(3);
        filesList.addView(row, lp);
    }

    /** A file's path into the composer, where the bot's own read tool resolves it against this chat's
        root — the one thing a phone can do with a path on another machine. */
    private void into(String rel) {
        closeSheet();
        String cur = input.getText().toString().trim();
        String line = cur.isEmpty() ? rel : cur + " " + rel;
        input.setText(line);
        input.setSelection(line.length());
        input.requestFocus();
    }

    /** Bytes in the unit a person would say out loud; the desktop's own three units. */
    private static String size(long n) {
        if (n < 1024) return n + " B";
        if (n < 1048576) return String.format(Locale.getDefault(), "%.1f KB", n / 1024.0);
        return String.format(Locale.getDefault(), "%.1f MB", n / 1048576.0);
    }

    /* The bot's screen, as the desktop's other side panel shows it. The panel polls, because the
       screen is live and nothing pushes it; the poll is one at a time and stops the moment the panel
       does, so a closed panel costs nothing. See `/api/computer/preview`, server.py:6359. */

    private static final long COMP_MS = 2500;
    private ImageView compShot;
    private TextView compMeta;
    private EditText compUrl;
    private boolean compBusy;
    private final Runnable compPoll = new Runnable() {
        @Override public void run() { refreshComp(false); }
    };

    private void computerSheet() {
        LinearLayout card = new LinearLayout(getContext());
        card.setOrientation(LinearLayout.VERTICAL);
        card.setBackground(shape(Pal.BG2, Pal.LINE, 1, 18, 18, 0, 0));
        card.setPadding(dp(16), dp(14), dp(16), dp(18));

        LinearLayout top = new LinearLayout(getContext());
        top.setOrientation(LinearLayout.HORIZONTAL);
        top.setGravity(Gravity.CENTER_VERTICAL);
        top.addView(bold(text("Computer", Pal.TXT, 16)), new LinearLayout.LayoutParams(0, -2, 1f));
        TextView again = text("Refresh", Pal.DIM, 13);
        again.setPadding(dp(12), dp(7), dp(12), dp(7));
        again.setBackground(press(shape(0, Pal.LINE2, 1, 999)));
        again.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { refreshComp(true); }
        });
        top.addView(again);
        TextView x = text("×", Pal.DIM, 20);
        x.setPadding(dp(10), 0, dp(4), 0);
        x.setContentDescription("Close");
        x.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { closeSheet(); }
        });
        top.addView(x, spaced(8));
        card.addView(top);

        compShot = new ImageView(getContext());
        compShot.setScaleType(ImageView.ScaleType.FIT_CENTER);
        compShot.setBackground(shape(Pal.CARD, Pal.LINE, 1, 12));
        compShot.setContentDescription("The bot's screen");
        LinearLayout.LayoutParams flp = new LinearLayout.LayoutParams(-1, dp(200));
        flp.topMargin = dp(12);
        card.addView(compShot, flp);

        compMeta = text("no screen yet — open a page below", Pal.DIM2, 12);
        compMeta.setPadding(0, dp(9), 0, 0);
        card.addView(compMeta);

        compUrl = new EditText(getContext());
        compUrl.setHint("https://example.com");
        compUrl.setHintTextColor(Pal.DIM2);
        compUrl.setTextColor(Pal.TXT);
        compUrl.setTextSize(Pal.fs(14));
        compUrl.setSingleLine(true);
        compUrl.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        compUrl.setBackground(shape(Pal.CARD, Pal.LINE, 1, 9));
        compUrl.setPadding(dp(11), dp(9), dp(11), dp(9));
        LinearLayout urlRow = new LinearLayout(getContext());
        urlRow.setOrientation(LinearLayout.HORIZONTAL);
        urlRow.setGravity(Gravity.CENTER_VERTICAL);
        urlRow.addView(compUrl, new LinearLayout.LayoutParams(0, -2, 1f));
        TextView open = bold(text("Open", Pal.ACCENT_INK, 13));
        open.setGravity(Gravity.CENTER);
        open.setPadding(dp(16), dp(11), dp(16), dp(11));
        open.setBackground(press(shape(Pal.ACCENT, 9)));
        open.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { openUrl(); }
        });
        urlRow.addView(open, spaced(8));
        sField(card, "Point the bot at a page", urlRow,
               "The bot you are chatting with opens the page in its real browser, and the frame above "
               + "becomes its live screen. The panel belongs to the chat you are in.");

        openSheet(card);
        refreshComp(true);
    }

    /** One look at the bot's screen. One at a time, and it re-arms itself only while the panel is
        still there — a closed panel must not keep a poll alive behind it. */
    private void refreshComp(final boolean force) {
        if (compShot == null || compBusy) return;
        compBusy = true;
        new Thread(new Runnable() {
            @Override public void run() {
                Map<String, Object> d;
                try {
                    d = Json.obj(Api.get(base, token, "/api/computer/preview?sid=" + Targets.encode(sid)
                            + (force ? "&force=1" : "")));
                } catch (IOException e) {
                    d = null;
                }
                final Map<String, Object> got = d;
                ui.post(new Runnable() {
                    @Override public void run() {
                        compBusy = false;
                        if (compShot == null) return;      // the panel closed while this was in flight
                        compDress(got);
                        ui.removeCallbacks(compPoll);
                        ui.postDelayed(compPoll, COMP_MS);
                    }
                });
            }
        }).start();
    }

    private void compDress(Map<String, Object> d) {
        if (d == null) {
            compShot.setImageDrawable(null);
            compMeta.setText("the computer panel is offline — retrying…");
            return;
        }
        String png = Json.str(d.get("png"));
        String err = Json.str(d.get("err"));
        if (png.isEmpty()) {
            // No picture at all, rather than an empty one: an empty image draws a broken glyph. The
            // server's reason is already a sentence — "Alpha is using the computer — not this chat's
            // bot" — so it stands alone, as it does on the desktop.
            compShot.setImageDrawable(null);
            compMeta.setText(err.isEmpty() ? "no screen yet — open a page below" : err);
            return;
        }
        Bitmap bm = decode(png);
        if (bm != null) compShot.setImageBitmap(bm);
        String title = Json.str(d.get("title"));
        // `err` beside a picture is a note, not a failure: it says the profile on screen is not the
        // bot's own. Shown, so nobody mistakes one profile for the other.
        compMeta.setText((title.isEmpty() ? "(untitled)" : title) + "  ·  " + Json.str(d.get("url"))
                       + (err.isEmpty() ? "" : "  —  " + err));
    }

    private void openUrl() {
        final String url = compUrl.getText().toString().trim();
        if (url.isEmpty()) return;
        compUrl.setText("");
        if (compMeta != null) compMeta.setText("opening…");
        new Thread(new Runnable() {
            @Override public void run() {
                Map<String, Object> r;
                try {
                    r = Json.obj(Api.post(base, token, "/api/computer/open",
                            "{\"session\":" + Json.quote(sid) + ",\"url\":" + Json.quote(url) + "}"));
                } catch (IOException e) {
                    r = null;
                }
                final Map<String, Object> got = r;
                ui.post(new Runnable() {
                    @Override public void run() {
                        if (compShot == null) return;
                        if (got == null) { note("Could not open that page."); return; }
                        if (!Json.truth(got.get("ok"))) {
                            String out = Json.str(got.get("out"));
                            compMeta.setText(out.isEmpty() ? "could not open that page" : out);
                        }
                        refreshComp(true);   // forced, so the frame that follows is this page
                    }
                });
            }
        }).start();
    }

    private void clear() { clear(sid, chatTitle); }

    /** The desktop's own confirm, word for word (`ctxAction`, app.js:2138). `title` is what the chat
        is called; empty means its id is all there is to name it by. */
    private void clear(final String session, String title) {
        String name = title == null || title.isEmpty() ? session : title;
        new AlertDialog.Builder(getContext())
            .setTitle("Start a new chat in " + name + "?")
            .setMessage("The transcript is emptied. The bots keep their memory and their work logs, so "
                      + "they still know what this project is about.")
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Start new", new DialogInterface.OnClickListener() {
                @Override public void onClick(DialogInterface d, int which) { doClear(session); }
            }).show();
    }

    private void doClear(final String session) {
        new Thread(new Runnable() {
            @Override public void run() {
                try {
                    Api.post(base, token, "/api/clear", "{\"session\":" + Json.quote(session) + "}");
                    ui.post(new Runnable() {
                        @Override public void run() {
                            // The chat on screen is the one that emptied, so it reopens, now empty. One
                            // cleared from the drawer while you are reading another only needs its own
                            // row back: that row's line is the last thing said, and that has just gone.
                            if (session.equals(sid)) open(sid, chatTitle, room);
                            else loadChats();
                        }
                    });
                } catch (IOException e) {
                    ui.post(new Runnable() {
                        @Override public void run() { note("Could not clear this chat."); }
                    });
                }
            }
        }).start();
    }

    // ---- the chips ---------------------------------------------------------------------------

    private void chips() {
        String m = model.model();
        chipModel.setText("Model: " + (m.isEmpty() ? "none" : m));
        chipApproval.setText("Approval: " + chipWord(model.approval()));
        Map<String, Object> ctx = model.ctx();
        int pct = model.ctxPct();
        chipCtx.setText("Context: " + (ctx == null || Json.num(ctx.get("tokens")) == 0 ? "—" : pct + "%"));
        chipCtx.setTextColor(pct >= 90 ? Pal.ERR : pct >= 75 ? Pal.WARN : Pal.DIM);
    }

    /** The level in one word, for a chip that has no room for the sentence. */
    private static String chipWord(String v) {
        if (v == null || v.isEmpty()) return "Ask";
        if (v.equals("full")) return "Full";
        for (int i = 0; i < MODES.length; i++) if (MODES[i].equals(v)) return CHIP_WORD[i];
        return v;
    }

    /** The level spelled out, for the menu that has room to say what each one does. */
    private static String modeLabel(String v) {
        if (v == null || v.isEmpty()) return "Ask for approval";
        if (v.equals("full")) return "Full access";
        for (int i = 0; i < MODES.length; i++) if (MODES[i].equals(v)) return MODE_LABELS[i];
        return v;
    }

    /** The model that will answer this chat, swapped on the spot rather than sent to a settings tab. */
    private void pickModel() {
        // The first row is the desktop's own: clearing the pick puts the chat back on the bot's model.
        final List<String> list = new ArrayList<>();
        list.add("Each bot's own model");
        list.addAll(models);
        new AlertDialog.Builder(getContext())
            .setTitle("Model")
            .setItems(list.toArray(new String[0]), new DialogInterface.OnClickListener() {
                @Override public void onClick(DialogInterface d, int which) {
                    setModel(which == 0 ? "" : list.get(which));
                }
            }).show();
    }

    private void setModel(final String name) {
        final int g = gen;
        new Thread(new Runnable() {
            @Override public void run() {
                try {
                    Map<String, Object> r = Json.obj(Api.post(base, token, "/api/model",
                            "{\"session\":" + Json.quote(sid) + ",\"model\":" + Json.quote(name) + "}"));
                    final String effective = r == null ? name : Json.str(r.get("model"));
                    ui.post(new Runnable() {
                        @Override public void run() {
                            if (g != gen) return;
                            model.meta(effective, model.approval(), model.ctx());
                            chips();
                        }
                    });
                } catch (IOException e) {
                    ui.post(new Runnable() {
                        @Override public void run() { note("Could not switch the model."); }
                    });
                }
            }
        }).start();
    }

    /** What this chat may do without asking. The four the desktop offers, in its own words. */
    private void pickApproval() {
        new AlertDialog.Builder(getContext())
            .setTitle("Approval")
            .setItems(MODE_LABELS, new DialogInterface.OnClickListener() {
                @Override public void onClick(DialogInterface d, int which) { setApproval(MODES[which]); }
            }).show();
    }

    private void setApproval(final String mode) {
        final int g = gen;
        new Thread(new Runnable() {
            @Override public void run() {
                try {
                    Map<String, Object> r = Json.obj(Api.post(base, token, "/api/approval_mode",
                            "{\"session\":" + Json.quote(sid) + ",\"mode\":" + Json.quote(mode) + "}"));
                    final String effective = r == null ? mode : Json.str(r.get("approval"));
                    ui.post(new Runnable() {
                        @Override public void run() {
                            if (g != gen) return;
                            model.meta(model.model(), effective.isEmpty() ? mode : effective, model.ctx());
                            chips();
                        }
                    });
                } catch (IOException e) {
                    ui.post(new Runnable() {
                        @Override public void run() { note("Could not change the approval level."); }
                    });
                }
            }
        }).start();
    }

    /** What filled this chat's window — the desktop's hover popover, as a dialog a thumb can open. */
    private void showCtx() {
        Map<String, Object> c = model.ctx();
        if (c == null || Json.num(c.get("tokens")) == 0) {
            note("Nothing sent in this chat yet. The window fills as you talk.");
            return;
        }
        StringBuilder b = new StringBuilder();
        b.append(fmtTok(Json.num(c.get("tokens")))).append(" / ").append(fmtTok(Json.num(c.get("limit"))))
         .append(" (").append(model.ctxPct()).append("%)");
        for (Object o : asList(c.get("rows"))) {
            Map<String, Object> r = row(o);
            if (r == null) continue;
            b.append("\n").append(Json.str(r.get("label"))).append("  ").append(fmtTok(Json.num(r.get("tokens"))));
        }
        new AlertDialog.Builder(getContext())
            .setTitle("Context window")
            .setMessage(b.toString())
            .setPositiveButton("Close", null)
            .show();
    }

    private static String fmtTok(long n) {
        if (n <= 0) return "0";
        if (n < 1000) return String.valueOf(n);
        return String.format(Locale.getDefault(), "%.1fK", n / 1000.0);
    }

    // ---- the transcript ----------------------------------------------------------------------

    private View transcript(Context c) {
        FrameLayout body = new FrameLayout(c);
        txCol = new LinearLayout(c);
        txCol.setOrientation(LinearLayout.VERTICAL);
        // The transcript's own top padding is the rest of the first row's gap: every row carries its
        // gap as a margin, so the first one must not be 16dp lower than the desktop's 18dp inset.
        txCol.setPadding(dp(14), dp(2), dp(14), dp(132));
        txScroll = new ScrollView(c);
        txScroll.setBackgroundColor(Pal.BG);
        txScroll.setClipToPadding(false);
        txScroll.addView(txCol, new ViewGroup.LayoutParams(-1, -2));
        txScroll.setOnScrollChangeListener(new View.OnScrollChangeListener() {
            @Override public void onScrollChange(View v, int x, int y, int ox, int oy) {
                if (!txScroll.canScrollVertically(1)) {     // back at the newest output
                    if (!following) follow();
                    return;
                }
                following = false;
                jump.setVisibility(VISIBLE);
                ui.removeCallbacks(resume);
                // Read back as long as you like: the follow re-arms after this, and the view stays
                // where you put it — only a message moves it. See `resume`.
                ui.postDelayed(resume, RESUME_MS);
            }
        });
        body.addView(txScroll, new FrameLayout.LayoutParams(-1, -1));

        jump = bold(text("↓ New output", Pal.TXT, 12));
        jump.setPadding(dp(13), dp(6), dp(13), dp(6));
        jump.setBackground(press(shape(Pal.CARD2, Pal.LINE2, 1, 999)));
        jump.setVisibility(GONE);
        jump.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { follow(); }
        });
        FrameLayout.LayoutParams jlp = new FrameLayout.LayoutParams(-2, -2, Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL);
        jlp.bottomMargin = dp(112);
        body.addView(jump, jlp);
        return body;
    }

    private View build(Model.Entry e) {
        switch (e.kind) {
            case Model.USER: return user(e);
            case Model.BOT: return bot(e);
            case Model.CARD: return card(e);
            case Model.TOOL: return tool(e);
            case Model.APPROVAL: return approval(e);
            case Model.IMAGE: return shot(e);
            case Model.NOTICE: return centred(e.text, "error".equals(e.level) ? Pal.ERR : Pal.DIM2);
            default: return step(e);
        }
    }

    private View user(Model.Entry e) {
        LinearLayout box = bubble(Pal.USER_BG, Pal.USER_LINE, 14, 14, 6, 14);
        box.addView(head(you(), Pal.DIM, e.ts));
        quoteBlock(box, e);
        // Typed text stays literal — no markdown — but a URL in it is tappable, which is the one thing
        // plain text gets wrong. `literal` is the whole of the difference from `spans`, and the
        // movement method is the same trade `para` makes: the link answers a tap and the long-press
        // selection goes with it, which is why the message menu carries Copy.
        TextView t = text("", Pal.TXT, 15);
        t.setText(literal(e.text));
        t.setMovementMethod(LinkMovementMethod.getInstance());
        airy(t, 15, 1.62f);
        box.addView(t);
        acts(box, e, you(), e.text);
        return end(box);
    }

    private View bot(Model.Entry e) {
        LinearLayout box = bubble(Pal.CARD, Pal.LINE, 14, 14, 14, 6);
        // A bot the roster no longer knows — renamed or deleted after the message was saved — has no
        // hue, and the desktop reads its name in the header's own dim rather than inventing one.
        int h = hueOf(e.who);
        box.addView(head(model.name(e.who), h == 0 ? Pal.DIM : Pal.lift(h), e.ts));
        quoteBlock(box, e);
        box.addView(prose(e.text));
        listen(box, e);
        acts(box, e, model.name(e.who), e.text);
        return start(box);
    }

    private View card(Model.Entry e) {
        if ("sys".equals(e.sub)) return centred(e.text, Pal.DIM2);
        int who = Pal.DIM;
        if ("plan".equals(e.sub)) who = Pal.PLAN_WHO;
        else if ("final".equals(e.sub)) who = Pal.FINAL_WHO;
        else if ("error".equals(e.sub)) who = Pal.ERR;
        LinearLayout box = bubble(Pal.CARD2, Pal.LINE2, 14, 14, 14, 14);
        box.addView(head(e.title, who, e.ts));
        if ("error".equals(e.sub)) {
            TextView t = text(e.text, Pal.ERR, 15);
            t.setTextIsSelectable(true);
            airy(t, 15, 1.62f);
            box.addView(t);
        } else {
            box.addView(prose(e.text));
        }
        // A plan and a report are the two cards you would actually want to answer or pass on, so they
        // carry the same actions a message does; a hand-off is a notice and carries none. That is the
        // desktop's own rule (`addCard`, app.js:1166).
        if ("plan".equals(e.sub) || "final".equals(e.sub)) acts(box, e, e.title, e.text);
        return start(box);
    }

    private View tool(final Model.Entry e) {
        boolean live = e.live();
        boolean long_ = live && System.currentTimeMillis() - e.since >= Model.LONG_STEP_MS;
        boolean bad = e.done && failed(e.sub, e.text);

        LinearLayout box = new LinearLayout(getContext());
        box.setOrientation(LinearLayout.VERTICAL);
        box.setBackground(shape(Pal.BG2, Pal.LINE, 1, 13, 13, 6, 13));

        LinearLayout head = new LinearLayout(getContext());
        head.setOrientation(LinearLayout.VERTICAL);
        head.setPadding(dp(13), dp(9), dp(13), dp(9));
        head.setMinimumHeight(dp(40));

        LinearLayout top = new LinearLayout(getContext());
        top.setOrientation(LinearLayout.HORIZONTAL);
        top.setGravity(Gravity.CENTER_VERTICAL);
        String agent = model.name(e.who);
        if (agent.isEmpty()) agent = "Bot";
        // `who · label` in one span, the way the desktop's row reads, and the head beside it — the
        // label never gives way, the head is the part that clips.
        SpannableStringBuilder line = new SpannableStringBuilder();
        line.append("● ").append(agent).append(" · ").append(Model.label(e.sub));
        line.setSpan(new ForegroundColorSpan(Pal.TOOL_WHO), 0, line.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        line.setSpan(new StyleSpan(Typeface.BOLD), 0, line.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        TextView who = new TextView(getContext());
        who.setText(line);
        who.setTextSize(Pal.fs(12));
        who.setSingleLine(true);
        who.setEllipsize(TextUtils.TruncateAt.END);
        who.setMaxWidth(getResources().getDisplayMetrics().widthPixels * 58 / 100);
        top.addView(who);

        TextView what = mono(e.title, Pal.TOOL_HEAD, 13);
        what.setSingleLine(true);
        what.setEllipsize(TextUtils.TruncateAt.END);
        LinearLayout.LayoutParams hlp = new LinearLayout.LayoutParams(0, -2, 1f);
        hlp.leftMargin = dp(8);
        top.addView(what, hlp);

        if (live) {
            top.addView(spinner());
            top.addView(text(Model.clock(System.currentTimeMillis() - e.since), long_ ? Pal.WARN : Pal.DIM2, 11), spaced(6));
        } else {
            top.addView(text(bad ? "failed" : "done", bad ? Pal.ERR : Pal.OK, 11), spaced(6));
        }
        TextView caret = text("›", Pal.DIM2, 13);
        caret.setRotation(e.open ? 90 : 0);
        top.addView(caret, spaced(9));
        head.addView(top);
        head.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { e.open = !e.open; paint(model.entries().indexOf(e)); }
        });
        box.addView(head, new LayoutParams(-1, -2));

        if (e.open) {
            View edge = new View(getContext());
            edge.setBackgroundColor(Pal.LINE);
            box.addView(edge, new LayoutParams(-1, dp(1)));
            LinearLayout body = new LinearLayout(getContext());
            body.setOrientation(LinearLayout.VERTICAL);
            body.setPadding(dp(13), dp(9), dp(13), dp(12));
            // The head in the header clips; the whole of it is here, where a thumb can read it.
            TextView full = mono(e.title, Pal.TOOL_HEAD, 13);
            full.setTextIsSelectable(true);
            body.addView(full);
            String[] w = e.done ? writes.get(e.id) : null;   // the desktop draws it with the result, not before
            if (w != null) {
                LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
                lp.topMargin = dp(9);
                body.addView(diff(w[0], w[1]), lp);
            }
            if (e.done && !e.text.isEmpty()) {
                String out = e.text.length() > 1500 ? e.text.substring(0, 1500) + "…" : e.text;
                TextView pre = mono(out, Pal.TOOL_OUT, 12);
                pre.setTextIsSelectable(true);
                airy(pre, 12, 1.5f);
                pre.setBackground(shape(Pal.BG, Pal.LINE, 1, 9));
                pre.setPadding(dp(10), dp(8), dp(10), dp(8));
                Cap cap = new Cap(getContext(), dp(280));
                cap.addView(pre, new ViewGroup.LayoutParams(-1, -2));
                LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
                lp.topMargin = dp(9);
                body.addView(cap, lp);
            }
            box.addView(body, new LayoutParams(-1, -2));
        }
        return wide(box);
    }

    /**
     * A write shown as what changed rather than as the whole file: the untouched head and tail are
     * trimmed away and only the edited stretch is drawn, deletions first. Enough to see what the bot
     * did to a file without reading the file. See `diffHtml`, app.js:1211.
     */
    private View diff(String before, String after) {
        String[] a = before.replace("\r\n", "\n").replace("\r", "\n").split("\n", -1);
        String[] b = after.replace("\r\n", "\n").replace("\r", "\n").split("\n", -1);
        int s = 0;
        while (s < a.length && s < b.length && a[s].equals(b[s])) s++;
        int e = 0;
        while (e < a.length - s && e < b.length - s && a[a.length - 1 - e].equals(b[b.length - 1 - e])) e++;
        LinearLayout box = new LinearLayout(getContext());
        box.setOrientation(LinearLayout.VERTICAL);
        box.setBackground(shape(Pal.BG, Pal.LINE, 1, 9));
        TextView h = text("changes", Pal.DIM2, 11);
        h.setAllCaps(true);
        h.setLetterSpacing(0.04f);
        h.setPadding(dp(10), dp(4), dp(10), dp(4));
        box.addView(h);
        int at = box.getChildCount();
        for (int i = Math.max(0, s - 2); i < s; i++) box.addView(dline("  " + a[i], Pal.DIM2));
        for (int i = s; i < a.length - e; i++) box.addView(dline("- " + a[i], Pal.ERR));
        for (int i = s; i < b.length - e; i++) box.addView(dline("+ " + b[i], Pal.OK));
        if (box.getChildCount() == at) box.addView(dline("(no change)", Pal.DIM2));
        Cap cap = new Cap(getContext(), dp(340));
        cap.addView(box, new ViewGroup.LayoutParams(-1, -2));
        return cap;
    }

    private TextView dline(String s, int ink) {
        TextView t = mono(s, ink, 12);
        t.setTextIsSelectable(true);
        t.setPadding(dp(10), dp(1), dp(10), dp(1));
        return t;
    }

    private View step(final Model.Entry e) {
        boolean live = e.live();
        boolean long_ = live && System.currentTimeMillis() - e.since >= Model.LONG_STEP_MS;
        GradientDrawable dashed = shape(0, 14);
        dashed.setStroke(dp(1), Pal.LINE2, dp(4), dp(4));     // dashed: a step is not a message

        LinearLayout box = new LinearLayout(getContext());
        box.setOrientation(LinearLayout.VERTICAL);
        box.setBackground(dashed);
        box.setPadding(dp(13), dp(8), dp(13), dp(8));

        LinearLayout top = new LinearLayout(getContext());
        top.setOrientation(LinearLayout.HORIZONTAL);
        top.setGravity(Gravity.CENTER_VERTICAL);
        if (live) {
            top.addView(spinner());
        } else {
            top.addView(text(e.failed ? "!" : "✓", e.failed ? Pal.ERR : Pal.OK, 13));
        }
        String label = live ? Model.stepTitle(e, long_)
                            : e.failed ? "Stopped early"
                                       : "Done — " + e.steps + (e.steps == 1 ? " step" : " steps");
        TextView l = text(label, long_ ? Pal.WARN : Pal.DIM, 13);
        l.setSingleLine(true);
        l.setEllipsize(TextUtils.TruncateAt.END);
        LinearLayout.LayoutParams llp = new LinearLayout.LayoutParams(0, -2, 1f);
        llp.leftMargin = dp(9);
        top.addView(l, llp);
        if (live) top.addView(text(Model.clock(System.currentTimeMillis() - e.since), long_ ? Pal.WARN : Pal.DIM2, 11), spaced(6));
        TextView caret = text("›", Pal.DIM2, 12);
        caret.setRotation(e.open ? 90 : 0);
        top.addView(caret, spaced(9));
        box.addView(top, new LayoutParams(-1, -2));

        if (e.open) {
            TextView log = mono(e.text, Pal.DIM, 13);
            log.setTextIsSelectable(true);
            airy(log, 13, 1.6f);
            log.setPadding(0, dp(8), 0, 0);
            box.addView(log);
        }
        box.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { e.open = !e.open; paint(model.entries().indexOf(e)); }
        });
        return start(box);
    }

    private View approval(final Model.Entry e) {
        String who = model.name(e.who);
        LinearLayout row = new LinearLayout(getContext());
        row.setOrientation(LinearLayout.HORIZONTAL);
        View bar = new View(getContext());
        bar.setBackground(shape(Pal.WARN, 3));
        row.addView(bar, new LinearLayout.LayoutParams(dp(3), -1));

        LinearLayout box = new LinearLayout(getContext());
        box.setOrientation(LinearLayout.VERTICAL);
        box.setBackground(shape(Pal.CARD, Pal.LINE2, 1, 14));
        box.setPadding(dp(15), dp(14), dp(15), dp(14));
        String title = e.done ? (e.allowed ? "Allowed" : "Denied")
                              : (who.isEmpty() ? "Bot wants" : who + " wants") + " to run a command";
        box.addView(bold(text(title, Pal.WARN, 13)));

        TextView cmd = mono(e.text, Pal.APPR_CMD, 13);
        cmd.setTextIsSelectable(true);
        airy(cmd, 13, 1.5f);
        cmd.setBackground(shape(Pal.BG, Pal.LINE, 1, 9));
        cmd.setPadding(dp(11), dp(9), dp(11), dp(9));
        LinearLayout.LayoutParams clp = new LinearLayout.LayoutParams(-1, -2);
        clp.topMargin = dp(9);
        box.addView(cmd, clp);

        LinearLayout buttons = new LinearLayout(getContext());
        buttons.setOrientation(LinearLayout.HORIZONTAL);
        buttons.setPadding(0, dp(10), 0, 0);
        TextView allow = pill("Allow", Pal.OK, Pal.ALLOW_INK);
        TextView deny = pill("Deny", Pal.HOV, Pal.TXT);
        allow.setEnabled(!e.done);
        deny.setEnabled(!e.done);
        if (e.done) { allow.setAlpha(0.5f); deny.setAlpha(0.5f); }
        allow.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { approve(e, true); }
        });
        deny.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { approve(e, false); }
        });
        buttons.addView(allow);
        buttons.addView(deny, spaced(9));
        box.addView(buttons);
        row.addView(box, new LinearLayout.LayoutParams(0, -2, 1f));
        return wide(row);
    }

    private View shot(Model.Entry e) {
        LinearLayout box = bubble(Pal.BG2, Pal.LINE, 13, 13, 6, 13);
        box.addView(head(e.sub, Pal.SHOT_WHO, e.ts));
        Bitmap bm = decode(e.png);
        if (bm != null) {
            ImageView iv = new ImageView(getContext());
            iv.setImageBitmap(bm);
            iv.setAdjustViewBounds(true);
            iv.setClipToOutline(true);                     // the corners come from the background's outline
            iv.setBackground(shape(0, Pal.LINE, 1, 9));
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
            lp.topMargin = dp(2);
            box.addView(iv, lp);
        }
        if (!e.note.isEmpty()) {
            TextView n = text(("Image".equals(e.sub) ? "Prompt: " : "Seen: ") + e.note, Pal.DIM, 13);
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
            lp.topMargin = dp(7);
            box.addView(n, lp);
        }
        return wide(box);
    }

    /** The desktop's empty transcript, in its four cases, with examples that fill the box and wait. */
    private View empty() {
        LinearLayout col = new LinearLayout(getContext());
        col.setOrientation(LinearLayout.VERTICAL);
        col.setGravity(Gravity.CENTER_HORIZONTAL);
        col.setPadding(dp(20), dp(20), dp(20), dp(20));

        String big, sub;
        final List<String> examples = new ArrayList<>();
        boolean noModel = configured && models.isEmpty();
        if (noModel) {
            big = "Connect a model to get started";
            sub = "Anzen-bot runs on a hosted model reached over an [OI]-compatible API. Point it at your "
                + "endpoint and key in Settings → AI model, and this chat can take tasks.";
        } else if (sid.isEmpty()) {
            big = "Nothing here yet";
            sub = "Add a bot or a room from the sidebar to start a chat.";
        } else if (room) {
            big = "Your room is ready";
            sub = "Message the room. The lead answers, or @mention a bot. The team plans, builds, tests and reports.";
            examples.add("Build & test a script");
            examples.add("Write a README");
            examples.add("Scaffold a project");
        } else if (scope() != null) {
            Room r = scope();
            big = chatTitle + " is ready";
            sub = "Talking to " + chatTitle + " inside " + r.name
                + (r.folder.isEmpty() ? ". No repo set, so it works in a shared folder."
                                      : ". Its shell and file tools run in " + r.folder + ".");
            examples.add("List the files here");
            examples.add("What is this project?");
            examples.add("Write a README");
        } else {
            Bot b = bots.get(botId());
            big = chatTitle + " is ready";
            sub = b != null && !b.what().isEmpty() ? b.what() : "Give it a task below.";
            examples.add("List the files here");
            examples.add("Create a folder");
            examples.add("Summarise this folder");
        }

        TextView title = bold(text(big, Pal.TXT, 20));
        title.setGravity(Gravity.CENTER);
        col.addView(title);
        TextView line = text(sub, Pal.DIM, 14);
        line.setGravity(Gravity.CENTER);
        line.setPadding(0, dp(6), 0, 0);
        col.addView(line);

        if (noModel) {
            col.addView(example("Open AI model settings", null));
        }
        for (String t : examples) col.addView(example(t, t));
        return col;
    }

    /**
     * One suggested task. It fills the composer rather than sending: a suggestion you cannot change
     * should not go the moment you touch it. The one exception is the model card's button, which has
     * no task to offer — the phone has no model settings screen, so it opens the same picker the
     * Model chip does, which is the one place a model is chosen here.
     */
    private View example(String label, final String fill) {
        TextView b = bold(text(label, Pal.TXT, 13));
        b.setPadding(dp(16), dp(11), dp(16), dp(11));
        b.setBackground(press(shape(Pal.CARD, Pal.LINE2, 1, 999)));
        b.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) {
                if (fill == null) { pickModel(); return; }
                input.setText(fill);
                input.setSelection(fill.length());
                input.requestFocus();
            }
        });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-2, -2);
        lp.topMargin = dp(16);
        LinearLayout wrap = new LinearLayout(getContext());
        wrap.setGravity(Gravity.CENTER_HORIZONTAL);
        wrap.addView(b, lp);
        return wrap;
    }

    private View centred(String s, int colour) {
        LinearLayout w = new LinearLayout(getContext());
        w.setGravity(Gravity.CENTER);
        TextView t = text(s, colour, 12);
        t.setGravity(Gravity.CENTER);
        w.addView(t);
        return w;
    }

    // ---- the composer ------------------------------------------------------------------------

    private View composer(Context c) {
        LinearLayout bar = new LinearLayout(c);
        bar.setOrientation(LinearLayout.VERTICAL);
        bar.setBackgroundColor(Pal.BG);
        View edge = new View(c);
        edge.setBackgroundColor(Pal.LINE);
        bar.addView(edge, new LayoutParams(-1, dp(1)));

        LinearLayout pad = new LinearLayout(c);
        pad.setOrientation(LinearLayout.VERTICAL);
        pad.setPadding(dp(9), dp(7), dp(9), dp(11));   // 10/12/14 minus the 3dp the focus ring reserves

        glow = new LinearLayout(c);
        glow.setOrientation(LinearLayout.VERTICAL);
        glow.setPadding(dp(3), dp(3), dp(3), dp(3));

        // The two live lists sit above the box you type in, not in the transcript: a bot does dozens of
        // things in a turn and a line printed per thing would bury the conversation it is working on.
        // Both are capped, because three rows should not eat a phone screen's worth of conversation.
        workCol = new LinearLayout(c);
        workCol.setOrientation(LinearLayout.VERTICAL);
        workCap = new Cap(c, dp(132));
        workCap.addView(workCol, new ViewGroup.LayoutParams(-1, -2));
        workCap.setVisibility(GONE);
        LinearLayout.LayoutParams wlp = new LinearLayout.LayoutParams(-1, -2);
        wlp.bottomMargin = dp(8);
        pad.addView(workCap, wlp);

        queueCol = new LinearLayout(c);
        queueCol.setOrientation(LinearLayout.VERTICAL);
        queueCap = new Cap(c, dp(132));
        queueCap.addView(queueCol, new ViewGroup.LayoutParams(-1, -2));
        queueCap.setVisibility(GONE);
        LinearLayout.LayoutParams qlp = new LinearLayout.LayoutParams(-1, -2);
        qlp.bottomMargin = dp(8);
        pad.addView(queueCap, qlp);

        inwrap = new LinearLayout(c);
        inwrap.setOrientation(LinearLayout.HORIZONTAL);
        inwrap.setGravity(Gravity.BOTTOM);
        inwrap.setBackground(shape(Pal.CARD, Pal.LINE2, 1, 14));
        inwrap.setPadding(dp(14), dp(8), dp(8), dp(8));

        // What you are answering, above the box you are answering in. It is built once and filled by
        // `renderReply`, because it is empty most of the time and a view that is always there keeps
        // the input from jumping when a reply is picked up or dropped.
        replyStrip = new LinearLayout(c);
        replyStrip.setOrientation(LinearLayout.HORIZONTAL);
        replyStrip.setGravity(Gravity.CENTER_VERTICAL);
        replyStrip.setBackground(shape(Pal.CARD2, Pal.LINE2, 1, 11));
        replyStrip.setPadding(dp(12), dp(8), dp(6), dp(8));
        replyStrip.setVisibility(GONE);
        LinearLayout.LayoutParams rlp = new LinearLayout.LayoutParams(-1, -2);
        rlp.bottomMargin = dp(8);
        pad.addView(replyStrip, rlp);

        input = new EditText(c);
        input.setHint("Give a task…");
        input.setHintTextColor(Pal.DIM2);
        input.setTextColor(Pal.TXT);
        input.setTextSize(Pal.fs(15));
        input.setBackground(null);
        input.setMaxLines(5);
        input.setImeOptions(EditorInfo.IME_ACTION_SEND);
        input.setOnEditorActionListener(new TextView.OnEditorActionListener() {
            @Override public boolean onEditorAction(TextView v, int actionId, android.view.KeyEvent ev) {
                if (actionId == EditorInfo.IME_ACTION_SEND) { send(); return true; }
                return false;
            }
        });
        input.setOnFocusChangeListener(new OnFocusChangeListener() {
            @Override public void onFocusChange(View v, boolean has) {
                glow.setBackground(has ? shape(Pal.FOCUS, 17) : null);
                inwrap.setBackground(shape(Pal.CARD, has ? Pal.ACCENT : Pal.LINE2, 1, 14));
            }
        });
        inwrap.addView(input, new LinearLayout.LayoutParams(0, -2, 1f));

        stop = pill("Stop", Pal.ERR, Pal.STOP_INK);
        stop.setVisibility(GONE);
        stop.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { halt(); }
        });
        send = pill("Send", Pal.ACCENT, Pal.ACCENT_INK);
        send.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { send(); }
        });
        inwrap.addView(stop, spaced(8));
        inwrap.addView(send, spaced(8));

        glow.addView(inwrap, new LayoutParams(-1, -2));
        pad.addView(glow, new LayoutParams(-1, -2));
        bar.addView(pad, new LayoutParams(-1, -2));
        return bar;
    }

    private TextView pill(String label, int fill, int ink) {
        TextView t = bold(text(label, ink, 14));
        t.setGravity(Gravity.CENTER);
        t.setPadding(dp(15), dp(10), dp(15), dp(10));
        t.setMinHeight(dp(44));
        t.setMinWidth(dp(44));
        t.setBackground(press(shape(fill, 11)));
        return t;
    }

    /** A turn running is the clock, the Stop button, and Send becoming Steer. */
    private void setRunning(boolean on) {
        if (on) startClock(); else stopClock();
        send.setText(on ? "Steer" : "Send");
        send.setBackground(press(shape(on ? Pal.WARN : Pal.ACCENT, 11)));
        stop.setVisibility(on ? VISIBLE : GONE);
        // The working strip is the live view; the transcript's own record takes over the moment the
        // turn lands, so nothing on the strip outlives the turn it was reporting.
        if (!on) workClear();
    }

    private void startClock() {
        if (turnStart != 0) return;
        turnStart = System.currentTimeMillis();
        head();
        ui.post(tick);
    }

    /** The turn is over: nothing is counting, so the ticker stops with it. */
    private void stopClock() {
        if (turnStart == 0) return;
        turnStart = 0;
        ui.removeCallbacks(tick);
        head();
    }

    /** Send what is typed. Mid-turn it is a steer — the bot picks it up at its next step instead of
        waiting for this turn to end, which is the whole point of steering. */
    private void send() {
        final String text = input.getText().toString().trim();
        if (text.isEmpty()) return;
        input.setText("");
        // The quote goes with this one message only, as it does on the desktop (`send`, app.js:1378):
        // an answer that kept quoting the last one would answer the wrong thing the second time.
        String qWho = replyWho, qText = replyText;
        replyWho = ""; replyText = "";
        renderReply();
        if (model.running()) steer(text, qWho, qText, false);
        else chat(text, qWho, qText, false);
    }

    private void chat(final String text) { chat(text, "", "", false); }

    private void chat(final String text, final String qWho, final String qText, final boolean fwd) {
        final String turn = String.valueOf(System.currentTimeMillis());
        // A turn outlives the screen it was started from: you can send a message and walk back to the
        // drawer while the bot is still working. The stream keeps running, and `g` is what stops its
        // events landing in whatever chat you opened next.
        final String session = sid;
        final int g = gen;
        paint(model.addUser(text, qWho, qText, fwd));
        follow();
        setRunning(true);   // the clock starts on the tap, not on the first event to come back
        turns.add(session);
        // Kept, not cleared at the turn's end: the watch stream can deliver the tail of this turn a
        // beat after the POST stream closed, and a stale entry here is only ever compared for equality.
        myTurns.put(session, turn);
        nav();              // this chat's dot lights now, even before you look at the drawer
        new Thread(new Runnable() {
            @Override public void run() {
                String body = "{\"session\":" + Json.quote(session) + ",\"text\":" + Json.quote(text)
                            + ",\"turn\":" + Json.quote(turn) + quote(qWho, qText, fwd) + "}";
                try {
                    Api.stream(base, token, "/api/chat", body, new Api.Event() {
                        @Override public void on(final String json) {
                            ui.post(new Runnable() {
                                @Override public void run() { if (g == gen) landed(json); }
                            });
                        }
                    });
                } catch (IOException e) {
                    ui.post(new Runnable() {
                        @Override public void run() {
                            if (g == gen) note("Lost contact with your computer.");
                        }
                    });
                } finally {
                    ui.post(new Runnable() {
                        @Override public void run() {
                            // The turn is over for its own chat whatever is on screen now, so the dot
                            // goes dark here rather than when that chat is next looked at.
                            if (turns.remove(session)) nav();
                            if (g == gen) setRunning(model.running());
                            // And whatever was typed into that chat while its turn ran goes now —
                            // unless a card is still waiting on your go, where a second turn would
                            // talk over the decision you have not made.
                            if (!(g == gen && pending())) drainQueue(session);
                        }
                    });
                }
            }
        }).start();
    }

    /**
     * Hand the running turn one more thing. The row it makes is the phone's queue: the task is held
     * on screen from the tap until the turn's own `steer` event lands it — a click that claimed the
     * hand-over before the bot reached it would show a message that had gone nowhere.
     */
    private void steer(final String text) { steer(text, "", "", false); }

    private void steer(final String text, String qWho, String qText, boolean fwd) {
        final QTask it = new QTask(text, qWho, qText, fwd, true);
        queue().add(it);
        renderQueue();
        steer(it);
    }

    private void steer(final QTask it) {
        final String session = sid;
        final int g = gen;
        new Thread(new Runnable() {
            @Override public void run() {
                String body = "{\"session\":" + Json.quote(session) + ",\"text\":" + Json.quote(it.text)
                            + quote(it.qWho, it.qText, it.fwd) + "}";
                boolean took = false;
                try {
                    Map<String, Object> r = Json.obj(Api.post(base, token, "/api/chat/steer", body));
                    took = r != null && Json.truth(r.get("running"));
                } catch (IOException e) {
                    // The row stays: nothing was sent, and the turn's own end will drain it.
                }
                final boolean taken = took;
                ui.post(new Runnable() {
                    @Override public void run() {
                        // A steer the turn took is not landed here: the row stays marked as taken and
                        // the turn's own `steer` event clears it when the bot actually reaches it.
                        if (taken) return;
                        it.steering = false;
                        // This chat's turn still holds the slot — the refusal was the server being a
                        // step ahead of us — so the task simply stays queued.
                        if (g == gen && model.running()) { renderQueue(); return; }
                        // Nothing left to steer: the turn had already written its last word. Run it
                        // now, which is what steering meant anyway. If the turn's own drain took it
                        // first this returns false, and running it here would run the same task twice.
                        if (!queueDrop(session, it)) return;
                        if (g == gen) chat(it.text, it.qWho, it.qText, it.fwd);
                    }
                });
            }
        }).start();
    }

    /** Stop this chat's turn. It lands within a step, and it also wakes a bot parked on a card. */
    private void halt() {
        stop.setText("Stopping…");
        stop.setEnabled(false);
        ui.postDelayed(new Runnable() {
            @Override public void run() {
                stop.setText("Stop");
                stop.setEnabled(true);
            }
        }, 800);
        new Thread(new Runnable() {
            @Override public void run() {
                try {
                    Api.post(base, token, "/api/stop", "{\"session\":" + Json.quote(sid) + "}");
                } catch (IOException e) {
                    ui.post(new Runnable() {
                        @Override public void run() { note("Could not reach your computer."); }
                    });
                }
            }
        }).start();
    }

    private void landed(String json) {
        // Folded twice, on purpose: the transcript takes the entry, the strip takes the live phase.
        Map<String, Object> ev = Json.obj(json);
        live(ev);
        int i = model.apply(json);
        // A steer the turn ended without handing over is not a message the bot saw, and the transcript
        // must not carry it as one — the row that shows it is back to being an ordinary queued task.
        // `Model.apply` draws the event either way, so the entry it just made is taken back here.
        if (i >= 0 && late(ev)) {
            model.entries().remove(i);
            i = -1;
        }
        if (i >= 0 && i < model.entries().size()) {
            Model.Entry e = model.entries().get(i);
            // A failure the reader cannot see is a failure they will re-run: the row is built folded,
            // so a tool that just failed opens itself and shows what it printed.
            if (e.kind == Model.TOOL && e.done && failed(e.sub, e.text)) e.open = true;
        }
        if (model.entries().size() != rows.size()) rebuild();
        else if (i >= 0) paint(i);
        setRunning(model.running());
    }

    private static boolean late(Map<String, Object> ev) {
        return ev != null && "steer".equals(Json.str(ev.get("type"))) && Json.truth(ev.get("late"));
    }

    // ---- the other client's turn ---------------------------------------------------------------

    /**
     * Hold the watch stream open, and re-open it whenever it drops.
     *
     * The window and the phone are two clients of one server, and a chat is one transcript on disk —
     * so a turn started on the desktop has to be visible here, and the other way round. The server
     * pushes every turn event, and a nudge for every transcript write, down this one stream. A nudge
     * carries no content, which is the point: a lost one costs a re-read and never a message, so the
     * stream is allowed to die and be re-opened rather than being treated as precious. See
     * `watchChats`, app.js:735.
     *
     * ponytail: one thread per open stream, and the reconnect sleep is what paces it. The flag alone
     * would not stop a reader parked in `readLine`, which is why `watchConn` is closed as well.
     */
    private void watch() {
        if (watching || base.isEmpty()) return;
        watching = true;
        final int g = ++watchGen;
        new Thread(new Runnable() {
            @Override public void run() {
                while (watching && g == watchGen) {
                    try {
                        Api.watch(base, token, "/api/watch", new Api.Event() {
                            @Override public void on(final String json) {
                                ui.post(new Runnable() {
                                    @Override public void run() { if (watching && g == watchGen) mirror(json); }
                                });
                            }
                        }, new Api.Open() {
                            @Override public void on(java.net.HttpURLConnection c) { if (g == watchGen) watchConn = c; }
                        });
                    } catch (IOException e) {
                        // The server is gone, or the socket was reaped — or `pause` closed it under
                        // this read. The sleep and retry below are the whole answer to the first two.
                    } finally {
                        if (g == watchGen) watchConn = null;
                    }
                    if (!watching || g != watchGen) return;
                    try { Thread.sleep(2500); } catch (InterruptedException e) { return; }
                }
            }
        }).start();
    }

    /**
     * One event off the watch stream: a chat moved, or a turn another client is running said
     * something.
     *
     * This is the phone's half of "the two clients are one server" — `elsewhere`, app.js:757. A turn's
     * events carry its session and its turn id, and the turn id is how this app recognises its own:
     * that turn's POST stream is drawing it already, and drawing the mirrored copy too would double
     * every card. Everything else is another client's work, and the phone shows it the way the window
     * that ran it does — the dot, the header's state, the room's working strip, and the cards
     * themselves, because `landed` is the same fold the POST stream goes through.
     */
    private void mirror(String json) {
        Map<String, Object> d = Json.obj(json);
        if (d == null) return;
        String session = Json.str(d.get("session"));
        if (session.isEmpty()) return;
        String turn = Json.str(d.get("turn"));
        if (!turn.isEmpty() && turn.equals(myTurns.get(session))) return;   // our own turn; its stream drew it

        String type = Json.str(d.get("type"));
        if ("gone".equals(type)) {
            // The chat was deleted, here or on the desktop. If it is the one on screen there is
            // nothing left to show, so the list is re-read and lands on the newest chat instead.
            if (session.equals(sid)) sid = "";
            loadChats();
            return;
        }
        // A nudge is a transcript write and carries nothing of it; a turn's own events come many times
        // a second and cannot change the list's order or its last line until the turn saves.
        boolean live = !type.isEmpty() && !"chat".equals(type);
        if (!live) {
            loadChats();
            // The transcript moved with no turn in flight, so the saved record is the only view of it.
            // This app's own turn draws its chat already, and re-reading under it would show the same
            // turn twice — the record is not written until it ends.
            if (session.equals(sid) && !turns.contains(session)) reload(session);
            return;
        }

        // A turn another client is running. Its dot lights whether or not you are looking at it, which
        // is what `turns` already means for this app's own turns — a chat works while you are elsewhere.
        if (turns.add(session)) nav();
        boolean here = session.equals(sid);
        if (here) {
            landed(json);
            // A mirrored turn is working whatever its first event happened to be. `landed` has just
            // settled the header from `model.running()`, and an event that is not itself a state — a
            // tool call, a line of text — would leave the phone reading "idle" until the next one. The
            // clock is started after it for that reason, not before.
            if (!type.equals("done") && !type.equals("error")) setRunning(true);
        }
        if (!type.equals("done") && !type.equals("error")) return;

        // The turn is over. Its streamed cards were the live view, so the chat goes back to the saved
        // record — exactly what the window that ran it does at its own end.
        turns.remove(session);
        nav();
        if (here) reload(session);
        loadChats();
        // Anything typed into that chat while its turn ran goes now that it has finished.
        drainQueue(session);
    }

    // ---- who is working, right now ------------------------------------------------------------

    /**
     * One event, folded onto the room's working strip on its way into the transcript.
     *
     * A room runs several bots at once, and without this the only sign of it is a hand-off card per
     * member that sits unchanged for as long as that member's step takes — minutes of a room looking
     * quiet while somebody works. The strip is the live thing instead: one row per bot working in the
     * room on screen, updated in place, gone the moment that bot is done. A room only: in a 1:1 chat
     * the header already names the bot and its state, and a second indicator for one fact is one too
     * many. See `liveEvent`, app.js:1525.
     */
    private void live(Map<String, Object> ev) {
        if (ev == null) return;
        String type = Json.str(ev.get("type"));
        if (type.equals("tool") && "write_file".equals(Json.str(ev.get("name")))) write(ev);
        if (type.equals("steer")) {
            // `late` is the turn saying it ended before it could hand this over. It is not a message
            // the bot saw, so the row goes back to being an ordinary queued task and this chat's next
            // turn runs it — which is what steering with no turn to interrupt means.
            if (Json.truth(ev.get("late"))) steerLate(Json.str(ev.get("text")));
            else queueLanded(Json.str(ev.get("text")));
        }
        if (!room) return;
        // The turn itself is over — checked before the bot is looked for, because these two events
        // carry no agent and the guard below would swallow them, leaving the strip up over a turn
        // that has finished.
        if (type.equals("final") || type.equals("error")) { workClear(); return; }
        String id = Json.str(ev.get("agent"));
        if (id.isEmpty() && type.equals("agent")) id = Json.str(ev.get("id"));
        if (id.isEmpty()) return;                        // a room-level status names no bot to put it on
        if (type.equals("agent") && "done".equals(Json.str(ev.get("state")))) { workDrop(id); return; }
        WRow r = workRow(id);
        if (r == null) return;
        if (type.equals("status")) {
            String p = Model.stepLabel(Json.str(ev.get("state")));
            if (p != null) r.phase.setText("· " + p);
        } else if (type.equals("approval")) {
            // The approval phase comes from the `approval` event, which names its bot, and not from
            // the `status` beside it, which does not: a member waiting on your decision is the one
            // case where the phase matters most, and that status would leave the row reading
            // "Working…" while it waits.
            r.phase.setText("· " + Model.stepLabel("approval"));
        } else if (type.equals("tool")) {
            r.tool = Model.head(Json.str(ev.get("name")), ev.get("args"));
            workAct(r);
        } else if (type.equals("agent_text") && !Json.str(ev.get("text")).isEmpty()) {
            String t = Json.str(ev.get("text"));
            // A delta appends onto the block in progress and a whole block replaces it, so this holds
            // the last thing the bot said rather than a fragment of it.
            r.text = Json.truth(ev.get("delta")) ? r.text + t : t;
            workAct(r);
        }
    }

    /** What the bot is doing, as one line: the tool it last called, said the way the transcript says
        it, and — only while it has called nothing — the first sentence of the last thing it said. */
    private static void workAct(WRow r) {
        String a = r.tool.isEmpty() ? firstSentence(r.text) : r.tool;
        r.act.setText(a.isEmpty() ? "" : "— " + a);
    }

    private static String firstSentence(String t) {
        String s = t == null ? "" : t.replaceAll("\\s+", " ").trim();   // collapsed first, so a newline cannot end it early
        java.util.regex.Matcher m = java.util.regex.Pattern.compile("^.*?[.!?](?=\\s|$)").matcher(s);
        return m.find() ? m.group() : s;
    }

    /** One bot's row, built once and then only edited: its clock starts here, not on every event. */
    private WRow workRow(String id) {
        WRow r = working.get(id);
        if (r != null) return r;
        Bot b = bots.get(id);
        String name = b == null || b.name.isEmpty() ? model.name(id) : b.name;
        LinearLayout row = new LinearLayout(getContext());
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setBackground(selected(Pal.CARD, 10, 0));
        row.setPadding(dp(11), dp(6), dp(11), dp(6));
        int h = hueOf(id);
        // ponytail: the desktop pulses this name; the spinner, the phase word and the clock already
        // keep the row visibly live, so the phone's name holds its full-strength colour instead.
        TextView nm = bold(text(name, h == 0 ? Pal.DIM : Pal.lift(h), 12));
        nm.setSingleLine(true);
        nm.setEllipsize(TextUtils.TruncateAt.END);
        // Each part carries the separator in front of it, so a bot with no title — or with nothing to
        // show yet — leaves no dangling `·` behind.
        TextView title = text("", Pal.DIM, 12);
        title.setSingleLine(true);
        title.setEllipsize(TextUtils.TruncateAt.END);
        TextView act = text("", Pal.DIM2, 12);
        act.setSingleLine(true);
        act.setEllipsize(TextUtils.TruncateAt.END);
        // A bot that has just been handed work is working, whatever it has said yet.
        TextView phase = text("· " + Model.stepLabel("working"), Pal.DIM2, 12);
        TextView clock = text("", Pal.DIM2, 11);
        row.addView(spinner(0));
        row.addView(nm);
        row.addView(title, spaced(7));
        row.addView(act, new LinearLayout.LayoutParams(0, -2, 1f));
        row.addView(phase, spaced(7));
        row.addView(text("·", Pal.DIM2, 12), spaced(7));   // the dot between the phase and its clock
        row.addView(clock, spaced(7));
        String t = b == null ? "" : b.title.trim();
        if (!t.isEmpty()) title.setText("· " + t);
        r = new WRow(row, nm, title, act, phase, clock);
        r.since = System.currentTimeMillis();
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.bottomMargin = dp(5);
        workCol.addView(row, lp);
        workCap.setVisibility(VISIBLE);
        working.put(id, r);
        workClock();
        return r;
    }

    private void workDrop(String id) {
        WRow r = working.remove(id);
        if (r == null) return;
        workCol.removeView(r.row);
        if (working.isEmpty()) workCap.setVisibility(GONE);
    }

    private void workClear() {
        for (String id : new ArrayList<>(working.keySet())) workDrop(id);
    }

    /** The strip's own clock, on the same second as everything else that is counting. */
    private void workClock() {
        long now = System.currentTimeMillis();
        for (WRow r : working.values()) {
            long ms = now - r.since;
            r.clock.setText(Model.clock(ms));
            r.clock.setTextColor(ms >= Model.LONG_STEP_MS ? Pal.WARN : Pal.DIM2);
        }
    }

    /** A write's before and after, kept for that row's diff: the pair is in the tool's own args and
        nowhere else, so it is held here rather than in the transcript. */
    private void write(Map<String, Object> ev) {
        String id = Json.str(ev.get("id"));
        Map<String, Object> args = row(ev.get("args"));
        if (id.isEmpty() || args == null) return;
        Object before = args.get("before"), content = args.get("content");
        if (before == null || content == null || before.equals(content)) return;
        writes.put(id, new String[]{ Json.str(before), Json.str(content) });
    }

    // ---- the queue ----------------------------------------------------------------------------

    /**
     * The tasks this chat is holding. Above the box you type in: the message the composer's Steer
     * pill handed to the running turn, held until that turn's own `steer` event lands it — a click
     * that claimed the hand-over first would show a message the bot had not reached. See `renderQueue`,
     * app.js:1564.
     */
    private void renderQueue() {
        if (queueCol == null) return;
        List<QTask> q = queue();
        queueCol.removeAllViews();
        if (q.isEmpty()) { queueCap.setVisibility(GONE); return; }
        queueCap.setVisibility(VISIBLE);
        TextView head = text(q.size() == 1 ? "1 task queued" : q.size() + " tasks queued", Pal.DIM, 11);
        head.setAllCaps(true);
        head.setLetterSpacing(0.04f);
        LinearLayout.LayoutParams hlp = new LinearLayout.LayoutParams(-2, -2);
        hlp.bottomMargin = dp(6);
        queueCol.addView(head, hlp);
        for (final QTask it : q) {
            LinearLayout row = new LinearLayout(getContext());
            row.setOrientation(LinearLayout.HORIZONTAL);
            row.setGravity(Gravity.CENTER_VERTICAL);
            row.setBackground(selected(Pal.CARD, 10, 0));
            row.setPadding(dp(11), dp(7), dp(9), dp(7));
            TextView t = text(it.text, Pal.TXT, 13);
            t.setSingleLine(true);
            t.setEllipsize(TextUtils.TruncateAt.END);
            row.addView(t, new LinearLayout.LayoutParams(0, -2, 1f));
            if (it.steering) {
                // The row says what the click did — the turn has it and hands it over at its next
                // step — and deliberately not that the message arrived: that is the turn's own
                // `steer` event to claim.
                LinearLayout note = new LinearLayout(getContext());
                note.setOrientation(LinearLayout.HORIZONTAL);
                note.setGravity(Gravity.CENTER_VERTICAL);
                note.addView(spinner(0));
                note.addView(text("taken — handing over…", Pal.DIM, 11), spaced(6));
                row.addView(note, spaced(9));
            } else {
                TextView now = text("Steer now", Pal.TXT, 12);
                now.setPadding(dp(11), dp(4), dp(11), dp(4));
                now.setBackground(press(shape(0, Pal.LINE2, 1, 999)));
                now.setOnClickListener(new OnClickListener() {
                    @Override public void onClick(View v) { it.steering = true; renderQueue(); steer(it); }
                });
                row.addView(now, spaced(9));
            }
            TextView x = text("×", Pal.DIM, 16);
            x.setPadding(dp(9), dp(5), dp(9), dp(5));
            x.setBackground(press(shape(0, 7)));
            x.setContentDescription("Remove from the queue");
            x.setOnClickListener(new OnClickListener() {
                @Override public void onClick(View v) { queueDrop(sid, it); renderQueue(); }
            });
            row.addView(x, spaced(9));
            LinearLayout.LayoutParams rlp = new LinearLayout.LayoutParams(-1, -2);
            rlp.bottomMargin = dp(6);
            queueCol.addView(row, rlp);
        }
        queueCol.addView(text("Runs when the current task finishes.", Pal.DIM2, 11));
    }

    /** This chat's queued tasks, made on first use — a chat that never queued one holds no list. */
    private List<QTask> queue(String session) {
        List<QTask> q = queues.get(session);
        if (q == null) { q = new ArrayList<>(); queues.put(session, q); }
        return q;
    }

    private List<QTask> queue() { return queue(sid); }

    /** Take one task off a chat's queue by the task itself, and say whether it was still there: the
        caller needs to know that it, and not the turn's own drain, was the one that took it. */
    private boolean queueDrop(String session, QTask it) {
        return queue(session).remove(it);
    }

    /** A steer the turn took: the row goes when the event says so, never when the click did. The row
        already marked as taken goes first — two queued copies of one message are two tasks. */
    private void queueLanded(String text) {
        List<QTask> q = queue();
        int at = -1;
        for (int i = 0; i < q.size(); i++) {
            if (!q.get(i).text.equals(text)) continue;
            if (q.get(i).steering) { at = i; break; }
            if (at < 0) at = i;
        }
        if (at >= 0) { q.remove(at); renderQueue(); }
    }

    /** A steer the turn ended without reaching: the row stays, back to being an ordinary queued task. */
    private void steerLate(String text) {
        for (QTask it : queue()) {
            if (it.steering && it.text.equals(text)) { it.steering = false; renderQueue(); return; }
        }
    }

    /**
     * The turn that just ended takes the first task waiting on it. Only the chat on screen can start
     * one — the transcript is the only one this class holds — so a task queued in another chat keeps
     * waiting there, and `open` drains it when that chat is next looked at.
     */
    private void drainQueue(String session) {
        if (!session.equals(sid) || turns.contains(session)) return;
        List<QTask> q = queue(session);
        if (q.isEmpty()) return;
        QTask it = q.remove(0);
        renderQueue();
        chat(it.text, it.qWho, it.qText, it.fwd);
    }

    // ---- quote, forward, and what a message lets you do ---------------------------------------

    /** The desktop's own refusal, word for word, so the two clients say the same thing. */
    private static final String WORKING = "This chat is working on a turn. Stop it, or wait for it to finish.";

    /** The `quote`/`fwd` a message carries to the server. The server keeps both on the message, so a
        reopened chat draws the same reply and the same forward mark it was sent with. */
    private static String quote(String who, String text, boolean fwd) {
        StringBuilder b = new StringBuilder();
        if (!who.isEmpty() || !text.isEmpty())
            b.append(",\"quote\":{\"who\":").append(Json.quote(who))
             .append(",\"text\":").append(Json.quote(text)).append("}");
        if (fwd) b.append(",\"fwd\":true");
        return b.toString();
    }

    /** The message this one answers, drawn above it — the same two lines any chat app gives you, so
        the reply reads on its own. The desktop's own block is `quoteBlock`, app.js:1154. */
    private void quoteBlock(LinearLayout box, Model.Entry e) {
        if (!e.qWho.isEmpty() || !e.qText.isEmpty()) {
            LinearLayout row = new LinearLayout(getContext());
            row.setOrientation(LinearLayout.HORIZONTAL);
            View bar = new View(getContext());
            bar.setBackgroundColor(Pal.LINE2);
            row.addView(bar, new LinearLayout.LayoutParams(dp(3), -1));
            LinearLayout col = new LinearLayout(getContext());
            col.setOrientation(LinearLayout.VERTICAL);
            col.setPadding(dp(9), 0, 0, 0);
            TextView w = text(e.qWho.isEmpty() ? "Message" : e.qWho, Pal.DIM, 11);
            w.setSingleLine(true);
            w.setEllipsize(TextUtils.TruncateAt.END);
            col.addView(w);
            TextView t = text(one(e.qText), Pal.DIM2, 12);
            t.setMaxLines(2);
            t.setEllipsize(TextUtils.TruncateAt.END);
            col.addView(t);
            row.addView(col, new LinearLayout.LayoutParams(0, -2, 1f));
            LinearLayout.LayoutParams rlp = new LinearLayout.LayoutParams(-1, -2);
            rlp.bottomMargin = dp(8);
            box.addView(row, rlp);
        }
        if (e.fwd) {
            TextView f = text("↪ Forwarded", Pal.DIM2, 11);
            f.setPadding(0, 0, 0, dp(5));
            box.addView(f);
        }
    }

    /** One line's worth of a message: the whitespace of a pasted block squeezed out, and the tail
        dropped. A quote is a reminder of what was said, not a second copy of it. */
    private static String one(String s) {
        String t = (s == null ? "" : s).replaceAll("\\s+", " ").trim();
        return t.length() > 180 ? t.substring(0, 180) : t;
    }

    /** What you are answering, above the box you answer in — or nothing at all. */
    private void renderReply() {
        if (replyStrip == null) return;
        replyStrip.removeAllViews();
        boolean on = !replyWho.isEmpty() || !replyText.isEmpty();
        replyStrip.setVisibility(on ? VISIBLE : GONE);
        if (!on) return;
        LinearLayout col = new LinearLayout(getContext());
        col.setOrientation(LinearLayout.VERTICAL);
        TextView w = text(replyWho.isEmpty() ? "Message" : replyWho, Pal.DIM, 11);
        w.setSingleLine(true);
        w.setEllipsize(TextUtils.TruncateAt.END);
        col.addView(w);
        TextView t = text(replyText, Pal.DIM2, 12);
        t.setSingleLine(true);
        t.setEllipsize(TextUtils.TruncateAt.END);
        col.addView(t);
        replyStrip.addView(col, new LinearLayout.LayoutParams(0, -2, 1f));
        TextView x = text("×", Pal.DIM, 18);
        x.setPadding(dp(12), dp(4), dp(12), dp(4));
        x.setBackground(press(shape(0, 8)));
        x.setContentDescription("Cancel the reply");
        x.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) {
                replyWho = ""; replyText = ""; renderReply(); input.requestFocus();
            }
        });
        replyStrip.addView(x, spaced(6));
    }

    /**
     * What you can do with a message once it is there. The desktop reveals these on hover; a phone
     * has no hover, so they are a press held on the message — the same actions, reached the way a
     * phone reaches things. See `msgActs`, app.js:1078.
     */
    private void acts(LinearLayout box, final Model.Entry e, final String who, final String text) {
        OnLongClickListener l = new OnLongClickListener() {
            @Override public boolean onLongClick(View v) { msgMenu(v, e, who, text); return true; }
        };
        arm(box, l, e, who, text);
    }

    /** Put the long-press on the bubble and on everything in it that would otherwise eat it. A
        selectable block keeps the phone's own long-press — that is how you copy part of a paragraph —
        so the message's actions ride on the bar that long-press opens rather than replacing it. */
    private void arm(View v, OnLongClickListener l, Model.Entry e, String who, String text) {
        if (v instanceof TextView && ((TextView) v).isTextSelectable()) {
            pick((TextView) v, e, who, text);
            return;
        }
        v.setOnLongClickListener(l);
        if (v instanceof ViewGroup) {
            ViewGroup g = (ViewGroup) v;
            for (int i = 0; i < g.getChildCount(); i++) arm(g.getChildAt(i), l, e, who, text);
        }
    }

    /** Long-pressing selected text opens Android's own Copy/Share/Select all bar, which knows nothing
        of a message — and your own bubbles are selectable, so on those it is the *only* bar a finger
        can reach. Its callback is where Reply and the rest go, so one long-press carries both the
        desktop's right-click menu and the phone's partial copy. Copy is not added: the bar's own is
        the better one, because it copies the part you picked. */
    private void pick(TextView t, final Model.Entry e, final String who, final String text) {
        t.setCustomSelectionActionModeCallback(new ActionMode.Callback() {
            @Override public boolean onCreateActionMode(ActionMode m, Menu menu) {
                menu.add("Reply");
                menu.add("Forward");
                for (String s : recall(e)) menu.add(s);
                return true;
            }
            @Override public boolean onPrepareActionMode(ActionMode m, Menu menu) { return false; }
            @Override public boolean onActionItemClicked(ActionMode m, MenuItem it) {
                act(it.getTitle().toString(), e, who, text);
                m.finish();
                return true;
            }
            @Override public void onDestroyActionMode(ActionMode m) { }
        });
    }

    /** The two actions that change a message already in the history instead of making a new one.
        Only a message the server has saved can be changed: one that arrived during a turn has no
        place in the history yet, which is what `i` says. See `reloadTranscript`, app.js:984. */
    private static List<String> recall(Model.Entry e) {
        if (e.i < 0) return Collections.emptyList();
        return Collections.singletonList(e.kind == Model.USER ? "Edit" : "Retry");
    }

    private void msgMenu(View anchor, final Model.Entry e, final String who, final String text) {
        PopupMenu m = new PopupMenu(getContext(), anchor);
        m.getMenu().add("Reply");
        m.getMenu().add("Forward");
        m.getMenu().add("Copy");
        for (String s : recall(e)) m.getMenu().add(s);
        m.setOnMenuItemClickListener(new PopupMenu.OnMenuItemClickListener() {
            @Override public boolean onMenuItemClick(MenuItem it) {
                act(it.getTitle().toString(), e, who, text);
                return true;
            }
        });
        m.show();
    }

    /** One message's actions, wherever they were asked for from — the popup menu or the selection bar. */
    private void act(String s, Model.Entry e, String who, String text) {
        if ("Reply".equals(s)) {
            replyWho = who; replyText = text; renderReply(); input.requestFocus();
        } else if ("Forward".equals(s)) forwardSheet(who, text);
        else if ("Copy".equals(s)) copy(text);
        else if ("Edit".equals(s)) editMsg(e.i, text);
        else if ("Retry".equals(s)) retryMsg(e.i);
    }

    private void copy(String text) {
        ClipboardManager cm = (ClipboardManager) getContext().getSystemService(Context.CLIPBOARD_SERVICE);
        if (cm != null) cm.setPrimaryClip(ClipData.newPlainText("message", text == null ? "" : text));
        note("Copied");
    }

    /**
     * Forgetting the tail of a transcript is the server's call, so it is asked first and its answer
     * is what gets drawn — the two can never disagree about where the chat now ends. Null means it
     * refused, and the reason has already been said.
     */
    private Map<String, Object> truncateAt(int keep) {
        try {
            Map<String, Object> r = Json.obj(Api.post(base, token, "/api/history/truncate",
                    "{\"session\":" + Json.quote(sid) + ",\"keep\":" + keep + "}"));
            if (r != null && !Boolean.FALSE.equals(r.get("ok"))) return r;
            String err = r == null ? "" : Json.str(r.get("error"));
            note(err.isEmpty() ? "Could not change this chat." : err);
        } catch (IOException e) {
            note("Could not change this chat.");
        }
        return null;
    }

    /** Take a message of yours back: it goes in the composer and everything after it is forgotten. */
    private void editMsg(final int keep, final String text) {
        if (turns.contains(sid)) { note(WORKING); return; }
        new Thread(new Runnable() {
            @Override public void run() {
                final Map<String, Object> r = truncateAt(keep);
                if (r == null) return;
                ui.post(new Runnable() {
                    @Override public void run() {
                        render(r);
                        input.setText(text);
                        input.setSelection(input.getText().length());
                        input.requestFocus();
                    }
                });
            }
        }).start();
    }

    /** Drop a reply and ask the same question again, quote and forward mark and all. */
    private void retryMsg(final int keep) {
        if (turns.contains(sid)) { note(WORKING); return; }
        int u = -1;
        for (int k = keep - 1; k >= 0; k--) {
            Map<String, Object> m = row(saved.get(k));
            if (m != null && "user".equals(Json.str(m.get("role")))) { u = k; break; }
        }
        if (u < 0) { note("There is no message to ask again."); return; }
        final int at = u;
        new Thread(new Runnable() {
            @Override public void run() {
                Map<String, Object> m = row(saved.get(at));
                final String text = Json.str(m.get("content"));
                Map<String, Object> q = row(m.get("quote"));
                final String qWho = q == null ? "" : Json.str(q.get("who"));
                final String qText = q == null ? "" : Json.str(q.get("text"));
                final boolean fwd = Json.truth(m.get("fwd"));
                final Map<String, Object> r = truncateAt(at);
                if (r == null) return;
                ui.post(new Runnable() {
                    @Override public void run() { render(r); deliver(sid, text, qWho, qText, fwd); }
                });
            }
        }).start();
    }

    /** Forwarding is delivering a copy somewhere else: pick the chat, and the message goes there and
        is picked up exactly as if you had sent it there. See `forwardMsg`, app.js:1437. */
    private void forwardSheet(final String who, final String text) {
        LinearLayout card = new LinearLayout(getContext());
        card.setOrientation(LinearLayout.VERTICAL);
        card.setBackground(shape(Pal.BG2, Pal.LINE, 1, 18, 18, 0, 0));
        card.setPadding(dp(16), dp(14), dp(16), dp(20));

        LinearLayout top = new LinearLayout(getContext());
        top.setOrientation(LinearLayout.HORIZONTAL);
        top.setGravity(Gravity.CENTER_VERTICAL);
        top.addView(bold(text("Forward to…", Pal.TXT, 16)), new LinearLayout.LayoutParams(0, -2, 1f));
        TextView x = text("×", Pal.DIM, 20);
        x.setPadding(dp(10), 0, dp(4), 0);
        x.setContentDescription("Close");
        x.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { closeSheet(); }
        });
        top.addView(x);
        card.addView(top);

        TextView prev = text((who.isEmpty() ? "" : who + ": ") + one(text), Pal.DIM, 12);
        prev.setMaxLines(2);
        prev.setEllipsize(TextUtils.TruncateAt.END);
        prev.setBackground(shape(Pal.CARD, 10));
        prev.setPadding(dp(11), dp(9), dp(11), dp(9));
        LinearLayout.LayoutParams plp = new LinearLayout.LayoutParams(-1, -2);
        plp.topMargin = dp(12); plp.bottomMargin = dp(4);
        card.addView(prev, plp);

        Cap sc = new Cap(getContext(), dp(360));
        LinearLayout list = new LinearLayout(getContext());
        list.setOrientation(LinearLayout.VERTICAL);
        list.setPadding(0, dp(6), 0, 0);
        int n = 0;
        for (Map.Entry<String, Room> e : rooms.entrySet()) {
            if (e.getKey().equals(sid)) continue;    // not back into itself, as the desktop's picker is not
            fwdRow(list, e.getKey(), e.getValue().name, e.getValue().members + " members", text);
            n++;
        }
        for (Map.Entry<String, Bot> e : bots.entrySet()) {
            Bot b = e.getValue();
            if (b.hidden || e.getKey().equals(sid)) continue;
            fwdRow(list, e.getKey(), b.name, b.line(), text);
            n++;
        }
        if (n == 0) list.addView(text("There is nowhere else to send it.", Pal.DIM2, 13));
        sc.addView(list, new ViewGroup.LayoutParams(-1, -2));
        card.addView(sc, new LinearLayout.LayoutParams(-1, -2));

        TextView hint = text("It arrives as your message, and is picked up as a task.", Pal.DIM2, 11);
        LinearLayout.LayoutParams hlp = new LinearLayout.LayoutParams(-1, -2);
        hlp.topMargin = dp(10);
        card.addView(hint, hlp);
        openSheet(card);
    }

    private void fwdRow(LinearLayout list, final String id, String name, String sub, final String text) {
        LinearLayout row = new LinearLayout(getContext());
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setBackground(press(shape(0, 11)));
        row.setPadding(dp(12), dp(11), dp(12), dp(11));
        row.addView(text(name, Pal.TXT, 14), new LinearLayout.LayoutParams(0, -2, 1f));
        if (sub != null && !sub.isEmpty()) row.addView(text(sub, Pal.DIM2, 12), spaced(8));
        row.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { closeSheet(); deliver(id, text, "", "", true); }
        });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.bottomMargin = dp(4);
        list.addView(row, lp);
    }

    /**
     * One place that puts a message into a chat — typed, forwarded, or a reply with a quote on it.
     * Only a chat whose *own* turn is already running holds the message in its queue; a task for
     * another chat goes now, because that other chat's turn is not this one's business. See
     * `deliver`, app.js:1366.
     */
    private void deliver(final String session, final String text, final String qWho,
                         final String qText, final boolean fwd) {
        if (turns.contains(session)) {
            queue(session).add(new QTask(text, qWho, qText, fwd, false));
            if (session.equals(sid)) renderQueue();
            return;
        }
        if (session.equals(sid)) { following = true; chat(text, qWho, qText, fwd); return; }
        // Another chat: it runs there, and its transcript is not this one's, so nothing is drawn here
        // — the drawer's dot is what says it landed. Only the end of it matters to this screen.
        turns.add(session);
        nav();
        new Thread(new Runnable() {
            @Override public void run() {
                String body = "{\"session\":" + Json.quote(session) + ",\"text\":" + Json.quote(text)
                            + quote(qWho, qText, fwd) + "}";
                try {
                    Api.stream(base, token, "/api/chat", body, new Api.Event() {
                        @Override public void on(String json) { }
                    });
                } catch (IOException ignored) {
                    // A forward that could not be delivered is not drawn anywhere: the dot going dark
                    // is the whole of what this screen knows about that chat.
                } finally {
                    ui.post(new Runnable() {
                        @Override public void run() { if (turns.remove(session)) nav(); }
                    });
                }
            }
        }).start();
    }

    /** The one overlay a sheet is drawn on: a scrim over the whole screen and a card rising from the
        bottom. It is built per sheet and torn down on close, so nothing here holds a stale list. */
    private void openSheet(View card) {
        closeSheet();
        FrameLayout layer = new FrameLayout(getContext());
        layer.setBackgroundColor(0x99000000);
        layer.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { closeSheet(); }
        });
        card.setClickable(true);       // so a tap on the card is not also a tap on the scrim
        layer.addView(card, new FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM));
        sheet = layer;
        addView(layer, new LayoutParams(-1, -1));
        card.setTranslationY(dp(28));
        card.setAlpha(0f);
        card.animate().translationY(0).alpha(1f).setDuration(200).start();
    }

    private void closeSheet() {
        if (sheet == null) return;
        final View gone = sheet;
        sheet = null;
        compShot = null; compMeta = null; compUrl = null;
        ui.removeCallbacks(compPoll);      // a closed panel must not keep asking
        setTab = "";                       // the settings sheet opens at its rail next time
        gone.animate().alpha(0f).setDuration(140).withEndAction(new Runnable() {
            @Override public void run() { removeView(gone); }
        }).start();
        if (wearNext) {                    // a theme picked in the settings sheet, landing now
            wearNext = false;
            ((android.app.Activity) getContext()).recreate();
        }
    }

    /** Bring the speech engine up without saying anything, so a voice list is a real list. */
    private void warmVoice() {
        if (tts == null) speak("");
    }

    /** The phone is going to the background: nothing that polls should keep polling — and the watch
        stream, the longest-lived of them all, goes with the rest. The flag alone would not stop it, so
        the socket is closed too; it is re-opened on the way back in, which is also when what it missed
        is re-read. */
    void pause() {
        watching = false;
        watchGen++;
        java.net.HttpURLConnection c = watchConn;
        watchConn = null;
        if (c != null) c.disconnect();
        ui.removeCallbacks(compPoll);
    }

    /** Back in front of it. The screen panel, if it is still open, picks its poll back up, and the
        watch stream is re-opened. */
    void resume() {
        watch();
        if (compShot != null) refreshComp(true);
        // Whatever moved while the phone was away moved unwatched, so the two things that stream would
        // have kept current are re-read: the chat list, and the chat on screen — unless this app's own
        // turn is drawing it, where a re-read would show that turn twice.
        if (base.isEmpty()) return;
        loadChats();
        if (!sid.isEmpty() && !turns.contains(sid)) reload(sid);
    }

    // ---- reading a message aloud ---------------------------------------------------------------

    /** A "Listen" pill under a bot's reply, where the desktop puts one: only when reading aloud is
        switched on, and only for something long enough to be worth hearing. */
    private void listen(LinearLayout box, Model.Entry e) {
        Map<String, Object> v = row(settings.get("voice"));
        if (v == null || !Json.truth(v.get("auto"))) return;
        if (e.text == null || e.text.length() <= 40) return;
        final String said = e.text;
        TextView b = text("🔊 Listen", Pal.DIM, 12);
        b.setPadding(dp(11), dp(6), dp(11), dp(6));
        b.setBackground(press(shape(0, Pal.LINE2, 1, 999)));
        b.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { speak(said); }
        });
        // The pill hugs its words, so it goes in a row that spans the bubble instead of into the
        // bubble itself. A vertical LinearLayout with children that are not all MATCH_PARENT takes its
        // width from the ones that are not, counting the rest as nothing
        // (`LinearLayout.measureVertical`: `maxWidth = alternativeMaxWidth`), so one wrap_content
        // child shrinks the whole bubble to that child's width and the paragraph and the header are
        // then stretched into it — the header's name gets a few characters and ellipsises. Keeping
        // every child of a bubble MATCH_PARENT keeps the bubble the width of its content.
        LinearLayout row = new LinearLayout(getContext());
        row.addView(b, new LinearLayout.LayoutParams(-2, -2));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = dp(8);
        box.addView(row, lp);
    }

    /**
     * Read a message aloud. The engine is built on the first Listen and kept, because a phone's
     * speech takes a moment to come up and the second tap should not wait for it again. The words
     * wait in `say` until it is ready, so the first tap is not the one that does nothing.
     */
    void speak(String text) {
        String plain = (text == null ? "" : text).replaceAll("[`*#_]", "");
        final String said = plain.length() > 600 ? plain.substring(0, 600) : plain;
        if (tts != null) {
            if (ttsReady) { pickVoice(); tts.speak(said, TextToSpeech.QUEUE_FLUSH, null, "anzen"); }
            else say = said;
            return;
        }
        say = said;
        tts = new TextToSpeech(getContext(), new TextToSpeech.OnInitListener() {
            @Override public void onInit(int status) {
                if (status != TextToSpeech.SUCCESS) {
                    ttsFailed = true;
                    note("This phone has no voice to read with.");
                    return;
                }
                ttsReady = true;
                pickVoice();
                tts.setSpeechRate(1.02f);
                if (say != null) { tts.speak(say, TextToSpeech.QUEUE_FLUSH, null, "anzen"); say = null; }
            }
        });
    }

    /**
     * Point the engine at the chosen voice. The desktop names a browser voice — "Samantha" — and a
     * phone's engine has its own list, so the setting is only a hint: when it names none of this
     * engine's voices the phone reads in the language it is set to, which is the honest answer.
     *
     * Run on every utterance, not once at start-up: an engine's list is empty for the first moment
     * after it comes up, so resolving at init alone would drop the choice for the whole session.
     */
    private void pickVoice() {
        Map<String, Object> v = row(settings.get("voice"));
        String want = v == null ? "" : Json.str(v.get("voice_id"));
        Voice have = null;
        try { for (Voice voice : tts.getVoices()) if (want.equals(voice.getName())) { have = voice; break; } }
        catch (Exception ignored) { }
        if (have != null) tts.setVoice(have);
        else if (tts.getVoice() == null) tts.setLanguage(Locale.getDefault());
    }

    /** The speech engine belongs to this view, so it is closed when the view is. */
    void shutdown() {
        watching = false;
        watchGen++;
        java.net.HttpURLConnection c = watchConn;
        watchConn = null;
        if (c != null) c.disconnect();
        if (tts == null) return;
        tts.stop();
        tts.shutdown();
        tts = null;
        ttsReady = false;
        say = null;
    }

    // ---- settings ----------------------------------------------------------------------------

    /** The rail's sections, in the desktop's own order and groups (`TABS`, app.js:2350). */
    private static final String[][] SET_TABS = {
        { "general", "General", "Set up" },
        { "models", "AI model", "Set up" },
        { "browser", "Browser", "Set up" },
        { "phone", "Phone", "Set up" },
        { "bots", "Bots", "Your workspace" },
        { "channels", "Rooms", "Your workspace" },
        { "apps", "Connected apps", "Your workspace" },
        { "skills", "Skills", "Your workspace" },
        { "plugins", "Plugins", "Your workspace" },
        { "memory", "Memory", "Your workspace" },
        { "approvals", "Approvals", "Behaviour" },
        { "voice", "Voice", "Behaviour" },
        { "appearance", "Appearance", "Behaviour" },
        { "help", "Help", "" },
    };

    /** Which section is open, or "" for the rail itself. */
    private String setTab = "";
    /** An appearance change made here, waiting for the sheet to close before the screen is rebuilt:
        a theme applied mid-edit would take the editor away with it. */
    private boolean wearNext;

    /** What a control does with the value the user gave it. */
    private interface Sink { void set(String v); }

    private void settingsSheet() {
        if (setTab.isEmpty()) rail();
        else panel(setTab);
    }

    private void rail() {
        LinearLayout card = sheetCard("Settings", null);
        String group = "";
        for (String[] t : SET_TABS) {
            if (!t[2].equals(group)) {
                group = t[2];
                if (!group.isEmpty()) card.addView(sGroup(group));
            }
            final String id = t[0];
            card.addView(sRow(t[1], new OnClickListener() {
                @Override public void onClick(View v) { setTab = id; settingsSheet(); }
            }));
        }
        openSheet(card);
    }

    private void panel(String id) {
        String title = id;
        for (String[] t : SET_TABS) if (t[0].equals(id)) title = t[1];
        LinearLayout card = sheetCard(title, "");
        LinearLayout col = new LinearLayout(getContext());
        col.setOrientation(LinearLayout.VERTICAL);
        if ("general".equals(id)) generalTab(col);
        else if ("appearance".equals(id)) appearanceTab(col);
        else if ("voice".equals(id)) voiceTab(col);
        else if ("phone".equals(id)) phoneTab(col);
        else if ("models".equals(id)) modelsTab(col);
        else if ("channels".equals(id)) roomsTab(col);
        else if ("help".equals(id)) helpTab(col);
        else elsewhere(col, id);
        Cap sc = new Cap(getContext(), dp(430));
        sc.addView(col, new ViewGroup.LayoutParams(-1, -2));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = dp(12);
        card.addView(sc, lp);
        openSheet(card);
    }

    /**
     * A section this phone does not host. The desktop's settings screen is a panel fourteen sections
     * wide; on a phone most of those jobs are already done where the thing is — the chips under the
     * header, the drawer's own editors, the Files and Computer sheets — and saying where is more use
     * than a second, worse copy of them.
     */
    /**
     * The AI model tab. Which model answers is the chips under the header — a model is a choice about
     * the chat you are in, not about the workspace — so the top of this panel says where they are. The
     * rest is the desktop's own Context card (`tabModels`, app.js:3351): the part of the model
     * settings that has no chip, because it is about how much a turn may spend before it must report.
     */
    private void modelsTab(LinearLayout col) {
        elsewhere(col, "models");
        col.addView(sGroup("Context"));
        Map<String, Object> cx = row(settings.get("context"));
        sNumber(col, "Context limit (tokens)", cxNum(cx, "limit"), "0", null, new Sink() {
            @Override public void set(String v) { saveContext("limit", v, 0); }
        });
        sNumber(col, "Max steps per turn", cxNum(cx, "max_steps"), "0",
                "0 uses the default (80). A step is one action — open a page, read it, click — so a "
                + "browsing job needs many; raise it if a bot is still being cut off mid-work.",
                new Sink() {
            @Override public void set(String v) { saveContext("max_steps", v, 0); }
        });
        sNumber(col, "Max seconds per turn", cxNum(cx, "max_seconds"), "0",
                "0 — the default — is no cap: the turn runs until it has spent its step budget, so a "
                + "slow but real job is never cut off for taking a long time. Set a number only if you "
                + "want a runaway stopped by the clock too. The cap is checked between steps, so a "
                + "command already running is allowed to finish.",
                new Sink() {
            @Override public void set(String v) { saveContext("max_seconds", v, 0); }
        });
        sNumber(col, "Retries if the model goes quiet", cxNum(cx, "model_retries"), "0",
                "0 uses the default (10), so eleven tries in total. A call that fails fast gets all of "
                + "them; a model that has gone silent spends the full wait on each try, so it gets "
                + "about three before the app stops and reports.",
                new Sink() {
            @Override public void set(String v) { saveContext("model_retries", v, 10); }
        });
    }

    /** One `context` setting. A field left blank or filled with rubbish reads as 0, which is the
        server's own "use the default" for every one of them. */
    private void saveContext(String key, String v, int max) {
        int n = 0;
        try { n = Integer.parseInt(v.trim()); } catch (NumberFormatException ignored) { }
        n = Math.max(0, max > 0 ? Math.min(max, n) : n);
        save("{\"context\":{\"" + key + "\":" + n + "}}");
    }

    private static String cxNum(Map<String, Object> m, String key) {
        return String.valueOf(m == null ? 0 : (int) Json.num(m.get(key)));
    }

    /**
     * The Rooms tab: where the rooms are, and the one thing the drawer cannot do — build a whole team
     * from a paste. The structure is handed out so it can be handed to a model: copy it, describe the
     * team you want around it, and paste the answer back. See `importPanel`, app.js:3095.
     */
    private void roomsTab(LinearLayout col) {
        elsewhere(col, "channels");
        col.addView(sGroup("New team"));

        final EditText ta = new EditText(getContext());
        ta.setHint("On botmrr.io open a team, hit Copy, and paste the whole thing here.\n\n"
                 + "Or just type a list:\nLea: Producer\nAlex: UI\nDima: Dev");
        ta.setHintTextColor(Pal.DIM2);
        ta.setTextColor(Pal.TXT);
        ta.setTextSize(Pal.fs(14));
        ta.setGravity(Gravity.TOP);
        ta.setMinLines(6);
        ta.setBackground(shape(Pal.CARD, Pal.LINE, 1, 9));
        ta.setPadding(dp(11), dp(9), dp(11), dp(9));
        caption(col, "Pasted team", ta);
        col.addView(ta);

        LinearLayout row = new LinearLayout(getContext());
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setPadding(0, dp(12), 0, 0);
        TextView tpl = text("Copy the structure", Pal.TXT, 13);
        tpl.setPadding(dp(13), dp(10), dp(13), dp(10));
        tpl.setBackground(press(shape(0, Pal.LINE2, 1, 9)));
        tpl.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { copy(teamTemplate); }
        });
        row.addView(tpl);
        final TextView build = text("Build team", Pal.TXT, 13);
        build.setPadding(dp(13), dp(10), dp(13), dp(10));
        build.setBackground(press(shape(0, Pal.LINE2, 1, 9)));
        row.addView(build, spaced(8));
        col.addView(row);

        // The desktop's own sentence under these two buttons (`importPanel`, app.js:3120): "Copy the
        // structure" is only useful if you know what to do with it.
        TextView howto = text("Send the structure to your AI with the team you want, then paste its "
                            + "answer above.", Pal.DIM2, 12);
        howto.setPadding(dp(2), dp(12), dp(2), 0);
        col.addView(howto);

        final TextView out = text("", Pal.DIM, 13);
        out.setPadding(dp(2), dp(12), dp(2), 0);
        col.addView(out);

        build.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) {
                final String text = ta.getText().toString().trim();
                if (text.isEmpty()) return;
                build.setEnabled(false);
                out.setTextColor(Pal.DIM);
                out.setText("Building…");
                new Thread(new Runnable() {
                    @Override public void run() {
                        String err = "";
                        List<String> created = new ArrayList<>();
                        String room = "", problems = "";
                        try {
                            Map<String, Object> r = Json.obj(Api.post(base, token, "/api/team/import",
                                    "{\"text\":" + Json.quote(text) + "}"));
                            if (r == null || !Json.truth(r.get("ok"))) {
                                err = Json.str(r == null ? "" : r.get("error"));
                                if (err.isEmpty()) err = "Could not read that.";
                                // What the paste was missing, named one per line — a half-built team is
                                // worse than a refusal, so nothing is created until all of it reads.
                                for (Object o : asList(r == null ? null : r.get("problems"))) {
                                    problems += "\n· " + Json.str(o);
                                }
                            } else {
                                for (Object o : asList(r.get("created"))) created.add(Json.str(o));
                                room = Json.str(r.get("room"));
                            }
                        } catch (IOException e) {
                            err = "Could not reach the server.";
                        }
                        final String e2 = err, p2 = problems, room2 = room;
                        final List<String> made = created;
                        ui.post(new Runnable() {
                            @Override public void run() {
                                build.setEnabled(true);
                                if (!e2.isEmpty()) {
                                    out.setTextColor(Pal.WARN);
                                    out.setText(e2 + p2);
                                    return;
                                }
                                out.setTextColor(Pal.DIM);
                                out.setText("Added " + made.size() + (made.size() == 1 ? " bot" : " bots")
                                           + (room2.isEmpty() ? "" : ", room: " + room2)
                                           + (made.isEmpty() ? "" : "\n" + TextUtils.join(" · ", made)));
                                ta.setText("");
                                loadConfig();
                            }
                        });
                    }
                }).start();
            }
        });
    }

    private void elsewhere(LinearLayout col, String id) {
        String where;
        if ("models".equals(id) || "approvals".equals(id))
            where = "The chips under the header: tap Model or Approval to change it for the chat you "
                  + "are in. A bot's own level is on the bot, in the drawer.";
        else if ("bots".equals(id) || "channels".equals(id))
            where = "The drawer: hold a bot or a room for its editor — name, colour, model, members, "
                  + "logo and the rest.";
        else if ("browser".equals(id))
            where = "The bot's browser is on your computer, where it can be signed in. Open the "
                  + "Computer sheet from the header menu to watch it work, or point it at a page.";
        else if ("apps".equals(id))
            where = "Connect an app on your computer; the bots use it from there, and this phone uses "
                  + "it through them.";
        else if ("skills".equals(id) || "plugins".equals(id) || "memory".equals(id))
            where = "Set up on your computer. A bot's skills, plugins and memory are loaded by the "
                  + "server, and this phone gets all of it without knowing how it works.";
        else where = "Open Anzen-bot on your computer to change this.";
        TextView t = text(where, Pal.DIM, 14);
        t.setPadding(dp(2), dp(12), dp(2), dp(4));
        col.addView(t);
    }

    // ---- the pieces a settings screen is made of ----------------------------------------------

    /** The sheet's own card, with its heading: a back chevron when this is a section, and a close. */
    private LinearLayout sheetCard(String title, final String back) {
        LinearLayout card = new LinearLayout(getContext());
        card.setOrientation(LinearLayout.VERTICAL);
        card.setBackground(shape(Pal.BG2, Pal.LINE, 1, 18, 18, 0, 0));
        card.setPadding(dp(16), dp(14), dp(16), dp(18));
        LinearLayout top = new LinearLayout(getContext());
        top.setOrientation(LinearLayout.HORIZONTAL);
        top.setGravity(Gravity.CENTER_VERTICAL);
        if (back != null) {
            TextView b = text("‹", Pal.TXT, 22);
            b.setPadding(dp(6), 0, dp(14), 0);
            b.setContentDescription("Back to the settings list");
            b.setOnClickListener(new OnClickListener() {
                @Override public void onClick(View v) { setTab = ""; settingsSheet(); }
            });
            top.addView(b);
        }
        top.addView(bold(text(title, Pal.TXT, 16)), new LinearLayout.LayoutParams(0, -2, 1f));
        TextView x = text("×", Pal.DIM, 20);
        x.setPadding(dp(10), 0, dp(4), 0);
        x.setContentDescription("Close");
        x.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { closeSheet(); }
        });
        top.addView(x);
        card.addView(top);
        return card;
    }

    private TextView sGroup(String label) {
        TextView t = bold(text(label.toUpperCase(Locale.getDefault()), Pal.DIM2, 11));
        t.setLetterSpacing(0.06f);
        t.setPadding(dp(2), dp(16), dp(2), dp(6));
        return t;
    }

    private View sRow(String label, OnClickListener tap) {
        LinearLayout row = new LinearLayout(getContext());
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setBackground(press(shape(0, 11)));
        row.setPadding(dp(13), dp(14), dp(13), dp(14));
        row.addView(text(label, Pal.TXT, 15), new LinearLayout.LayoutParams(0, -2, 1f));
        row.addView(text("›", Pal.DIM2, 15));
        row.setOnClickListener(tap);
        return row;
    }

    /** A caption, its control, and the sentence explaining it — the desktop's own `fld`. */
    private void sField(LinearLayout col, String label, View control, String desc) {
        caption(col, label, control);
        col.addView(control);
        if (desc != null && !desc.isEmpty()) {
            TextView d = text(desc, Pal.DIM2, 11);
            d.setPadding(dp(2), dp(5), dp(2), 0);
            col.addView(d);
        }
    }

    /** A text setting. It saves when you leave the field: a name typed and then tapped away from is
        not a name anyone meant to throw away. */
    private void sInput(LinearLayout col, String label, String value, String hint, final Sink sink) {
        sInput(col, label, value, hint, null, sink, InputType.TYPE_CLASS_TEXT);
    }

    /** A number: the same field with the keyboard a number needs, and a sentence under it saying what
        the number is for. */
    private void sNumber(LinearLayout col, String label, String value, String hint, String desc,
                         final Sink sink) {
        sInput(col, label, value, hint, desc, sink, InputType.TYPE_CLASS_NUMBER);
    }

    /** The one text field. What varies between settings is only the keyboard and the sentence. */
    private void sInput(LinearLayout col, String label, String value, String hint, String desc,
                        final Sink sink, int type) {
        EditText e = new EditText(getContext());
        e.setText(value);
        e.setHint(hint);
        e.setHintTextColor(Pal.DIM2);
        e.setTextColor(Pal.TXT);
        e.setTextSize(Pal.fs(14));
        e.setSingleLine(true);
        e.setInputType(type);
        e.setBackground(shape(Pal.CARD, Pal.LINE, 1, 9));
        e.setPadding(dp(11), dp(9), dp(11), dp(9));
        e.setImeOptions(EditorInfo.IME_ACTION_DONE);
        e.setOnEditorActionListener(new TextView.OnEditorActionListener() {
            @Override public boolean onEditorAction(TextView v, int action, android.view.KeyEvent ev) {
                if (action != EditorInfo.IME_ACTION_DONE) return false;
                v.clearFocus();
                return true;
            }
        });
        e.setOnFocusChangeListener(new OnFocusChangeListener() {
            @Override public void onFocusChange(View v, boolean has) {
                if (!has) sink.set(((EditText) v).getText().toString().trim());
            }
        });
        sField(col, label, e, desc);
    }

    /** A switch, drawn as the desktop draws one: a small pill that says which way it is, so it wears
        the theme rather than the platform's own accent. */
    private void sSwitch(LinearLayout col, String title, String sub, boolean on, final Sink sink) {
        LinearLayout row = new LinearLayout(getContext());
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(dp(2), dp(10), dp(2), dp(10));
        LinearLayout txt = new LinearLayout(getContext());
        txt.setOrientation(LinearLayout.VERTICAL);
        txt.addView(text(title, Pal.TXT, 14));
        if (sub != null && !sub.isEmpty()) txt.addView(text(sub, Pal.DIM2, 12));
        row.addView(txt, new LinearLayout.LayoutParams(0, -2, 1f));
        final TextView tg = text(on ? "On" : "Off", on ? Pal.ACCENT_INK : Pal.DIM, 12);
        tg.setGravity(Gravity.CENTER);
        tg.setPadding(dp(14), dp(7), dp(14), dp(7));
        tg.setMinWidth(dp(58));
        tg.setBackground(press(shape(on ? Pal.ACCENT : 0, on ? Pal.ACCENT : Pal.LINE2, 1, 999)));
        tg.setContentDescription(title);
        tg.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) {
                boolean now = !"On".equals(tg.getText().toString());
                tg.setText(now ? "On" : "Off");
                tg.setTextColor(now ? Pal.ACCENT_INK : Pal.DIM);
                tg.setBackground(press(shape(now ? Pal.ACCENT : 0, now ? Pal.ACCENT : Pal.LINE2, 1, 999)));
                sink.set(now ? "true" : "false");
            }
        });
        row.addView(tg, spaced(10));
        col.addView(row);
    }

    /** One of a list: a row that opens the choices. */
    private void sSelect(LinearLayout col, String label, String value, final String[] values,
                         String[] labels, final Sink sink, String desc) {
        final String[] labs = labels;
        final TextView shown = text("", Pal.TXT, 14);
        for (int i = 0; i < values.length; i++) if (values[i].equals(value)) shown.setText(labs[i]);
        if (shown.getText().length() == 0 && labs.length > 0) shown.setText(labs[0]);
        shown.setPadding(dp(12), dp(11), dp(12), dp(11));
        shown.setBackground(press(shape(Pal.CARD, Pal.LINE, 1, 9)));
        shown.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) {
                new AlertDialog.Builder(getContext())
                    .setItems(labs, new DialogInterface.OnClickListener() {
                        @Override public void onClick(DialogInterface d, int which) {
                            shown.setText(labs[which]);
                            sink.set(values[which]);
                        }
                    })
                    .setNegativeButton("Cancel", null)
                    .show();
            }
        });
        sField(col, label, shown, desc);
    }

    /** Write a setting. The server merges a patch into what it already has, so a section set from
        here never drops the fields this screen does not know about. */
    private void save(final String patch) {
        new Thread(new Runnable() {
            @Override public void run() {
                try {
                    Api.post(base, token, "/api/settings", "{\"settings\":" + patch + "}");
                } catch (IOException e) {
                    ui.post(new Runnable() {
                        @Override public void run() { note("Could not save that setting."); }
                    });
                    return;
                }
                ui.post(new Runnable() {
                    @Override public void run() { loadConfig(); }
                });
            }
        }).start();
    }

    private void saveAppearance(String key, String jsonValue) {
        save("{\"appearance\":{\"" + key + "\":" + jsonValue + "}}");
    }

    private void saveVoice(String jsonValue) {
        save("{\"voice\":" + jsonValue + "}");
    }

    private Map<String, Object> voice() {
        Map<String, Object> v = row(settings.get("voice"));
        return v == null ? new LinkedHashMap<String, Object>() : v;
    }

    // ---- the sections this phone sets ---------------------------------------------------------

    private void generalTab(LinearLayout col) {
        col.addView(sGroup("Workspace"));
        sInput(col, "Workspace name", Json.str(settings.get("company_name")), "Anzen-bot", new Sink() {
            @Override public void set(String v) { save("{\"company_name\":" + Json.quote(v) + "}"); }
        });
        sInput(col, "Your name", Json.str(settings.get("user_name")), "Client", new Sink() {
            @Override public void set(String v) { save("{\"user_name\":" + Json.quote(v) + "}"); }
        });
        col.addView(sGroup("Behaviour"));
        sSwitch(col, "Read replies aloud automatically",
                "Speak every finished reply with the chosen voice.",
                Json.truth(voice().get("auto")), new Sink() {
            @Override public void set(String v) { saveVoice("{\"auto\":" + v + ",\"enabled\":" + v + "}"); }
        });
        Map<String, Object> dec = row(settings.get("decision"));
        sSwitch(col, "Auto-route room messages",
                "Let a fast model pick which bot answers an un-mentioned room message.",
                dec != null && Json.truth(dec.get("enabled")), new Sink() {
            @Override public void set(String v) {
                save("{\"decision\":{\"enabled\":" + v + ",\"jobs\":{\"rooms\":" + v + "}}}");
            }
        });
    }

    private void appearanceTab(LinearLayout col) {
        Map<String, Object> a = row(settings.get("appearance"));
        String theme = a == null ? "" : Json.str(a.get("theme"));
        if (theme.isEmpty()) theme = Pal.DEFAULT_THEME;
        String[] ids = new String[Pal.THEMES.length], names = new String[Pal.THEMES.length];
        for (int i = 0; i < Pal.THEMES.length; i++) { ids[i] = Pal.THEMES[i][0]; names[i] = Pal.THEMES[i][1]; }
        sSelect(col, "Theme", theme, ids, names, new Sink() {
            @Override public void set(String v) { saveAppearance("theme", Json.quote(v)); }
        }, "A whole look — surfaces and type. The theme is the one the desktop app is wearing, so the two "
         + "match. The blurred-glass themes are left out: a window can blur what is behind it, a view "
         + "cannot.");

        float px = a == null ? 0 : (float) Json.dbl(a.get("font_size"));
        if (px <= 0) px = Pal.BASE_PX;
        String[] sizes = new String[Pal.SIZES.length], sl = new String[Pal.SIZES.length];
        for (int i = 0; i < Pal.SIZES.length; i++) {
            sizes[i] = String.valueOf(Pal.SIZES[i]);
            sl[i] = Pal.SIZES[i] + " px";
        }
        sSelect(col, "Font size", String.valueOf(px), sizes, sl, new Sink() {
            @Override public void set(String v) { saveAppearance("font_size", v); }
        }, "The base text size. Everything else is this times its own designed value, so the whole app "
         + "grows with it.");

        String density = a == null ? "" : Json.str(a.get("density"));
        if (density.isEmpty()) density = "comfortable";
        sSelect(col, "Density", density, new String[]{ "comfortable", "compact" },
                new String[]{ "Comfortable", "Compact" }, new Sink() {
            @Override public void set(String v) { saveAppearance("density", Json.quote(v)); }
        }, null);
    }

    private void voiceTab(LinearLayout col) {
        warmVoice();     // so the list below is a real list by the time it is tapped
        sSwitch(col, "Read replies aloud", "Show a Listen button on longer bot replies.",
                Json.truth(voice().get("auto")), new Sink() {
            @Override public void set(String v) { saveVoice("{\"auto\":" + v + ",\"enabled\":" + v + "}"); }
        });
        final TextView row = text(voiceLabel(), Pal.TXT, 14);
        row.setPadding(dp(12), dp(11), dp(12), dp(11));
        row.setBackground(press(shape(Pal.CARD, Pal.LINE, 1, 9)));
        row.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) {
                final Map<String, String> pick = voiceChoices();
                final List<String> labels = new ArrayList<>(pick.keySet());
                new AlertDialog.Builder(getContext())
                    .setItems(labels.toArray(new String[0]), new DialogInterface.OnClickListener() {
                        @Override public void onClick(DialogInterface d, int which) {
                            String label = labels.get(which);
                            saveVoice("{\"voice_id\":" + Json.quote(pick.get(label)) + "}");
                            row.setText(label);
                        }
                    })
                    .setNegativeButton("Cancel", null)
                    .show();
            }
        });
        sField(col, "Voice", row, "A phone has its own voices, not the browser's — the name saved on the "
                                 + "desktop will usually not be here, and the phone then reads in the "
                                 + "language it is set to.");

        TextView test = text("🔊 Test voice", Pal.TXT, 13);
        test.setGravity(Gravity.CENTER);
        test.setPadding(dp(13), dp(11), dp(13), dp(11));
        test.setBackground(press(shape(Pal.CARD, Pal.LINE, 1, 9)));
        test.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) {
                speak("Hello! I am a bot in your Anzen-bot team. Everything is unlocked.");
            }
        });
        sField(col, "Test", test, null);
    }

    /** The name saved in `voice_id`, or the honest answer that this phone is using its own. */
    private String voiceLabel() {
        String id = Json.str(voice().get("voice_id"));
        if (id.isEmpty()) return "System default";
        for (Map.Entry<String, String> e : voiceChoices().entrySet()) {
            if (id.equals(e.getValue())) return e.getKey();
        }
        return "System default (the saved voice is not on this phone)";
    }

    /** This phone's own voices, the default first, as label -> the engine's own id. The label leads
        with the language because an engine's name for a voice is an id like `en-us-x-sfg-local`,
        which says nothing to the person choosing one; where two voices share a language the id is
        still there to tell them apart. */
    private Map<String, String> voiceChoices() {
        Map<String, String> out = new LinkedHashMap<>();
        out.put("System default", "");
        if (tts != null) {
            List<Voice> vs = new ArrayList<>();
            try { vs.addAll(tts.getVoices()); }
            catch (Exception ignored) { }     // a half-built engine has no voices to offer yet
            Collections.sort(vs, new java.util.Comparator<Voice>() {
                @Override public int compare(Voice a, Voice b) {
                    int c = lang(a).compareTo(lang(b));
                    return c != 0 ? c : a.getName().compareTo(b.getName());
                }
            });
            for (Voice v : vs) {
                String label = lang(v);
                if (out.containsKey(label)) label = label + " — " + v.getName();
                out.put(label, v.getName());
            }
        }
        return out;
    }

    /** The language a voice speaks, as a person would name it. */
    private static String lang(Voice v) {
        Locale l = v.getLocale();
        if (l == null) return v.getName();
        String s = l.getDisplayLanguage(Locale.getDefault());
        String c = l.getDisplayCountry(Locale.getDefault());
        return c.isEmpty() ? s : s + " (" + c + ")";
    }

    private void phoneTab(final LinearLayout col) {
        col.addView(sGroup("This phone"));
        TextView at = text(base, Pal.DIM, 13);
        at.setTextIsSelectable(true);
        sField(col, "Connected to", at, "The address this phone reaches Anzen-bot at.");
        col.addView(sGroup("Reach it from another device"));
        final LinearLayout box = new LinearLayout(getContext());
        box.setOrientation(LinearLayout.VERTICAL);
        col.addView(box);
        new Thread(new Runnable() {
            @Override public void run() {
                Map<String, Object> d;
                try { d = Json.obj(Api.get(base, token, "/api/lan")); } catch (IOException e) { d = null; }
                final Map<String, Object> got = d;
                ui.post(new Runnable() {
                    @Override public void run() { lanFill(box, got); }
                });
            }
        }).start();
    }

    private void lanFill(LinearLayout box, Map<String, Object> d) {
        box.removeAllViews();
        if (d == null) { box.addView(text("Could not read the phone settings.", Pal.DIM2, 13)); return; }
        final boolean on = Json.truth(d.get("enabled"));
        sSwitch(box, "Phone access", "Let a device on your own network open this app.", on, new Sink() {
            @Override public void set(String v) { setLan(box, "true".equals(v)); }
        });
        if (!on) {
            box.addView(text("Turn it on for an address to type into another phone.", Pal.DIM2, 12));
            return;
        }
        TextView u = text(Json.str(d.get("url")), Pal.TXT, 14);
        u.setTextIsSelectable(true);
        sField(box, "Address", u, null);
        TextView t = text(Json.str(d.get("token")), Pal.DIM, 12);
        t.setTextIsSelectable(true);
        sField(box, "Token", t, "Type both into Anzen-bot on the other device.");
    }

    private void setLan(final LinearLayout box, final boolean on) {
        new Thread(new Runnable() {
            @Override public void run() {
                Map<String, Object> d;
                try { d = Json.obj(Api.post(base, token, "/api/lan", "{\"on\":" + on + "}")); }
                catch (IOException e) { d = null; }
                final Map<String, Object> got = d;
                ui.post(new Runnable() {
                    @Override public void run() {
                        if (got == null) { note("Could not change that."); return; }
                        // The listener switches under this response, so the state is read back rather
                        // than assumed: the address is only real once something is listening on it.
                        lanFill(box, got);
                    }
                });
            }
        }).start();
    }

    /** What the phone needs to know, which is not the desktop's tour: how to talk to a bot, what a
        room is, and the gestures a touch screen has instead of hover and a keyboard. */
    private void helpTab(LinearLayout col) {
        String[][] secs = {
            { "The idea", "Anzen-bot is a chat app you host yourself. You give a team of bots a goal in "
              + "plain words, and they answer, use real tools, and hand back a report. Nothing here is "
              + "a mock: a bot runs a shell, reads and writes files, drives a real browser, and calls "
              + "the apps you connect. It all runs on your computer; this phone is a window onto it." },
            { "Bots, rooms, chats", "A bot is one teammate, with its own model, memory, colour and face. "
              + "A room is a team with its own transcript and its own repo folder. A chat is a "
              + "transcript — every bot and every room keeps its own, so the same bot in two rooms is "
              + "two separate conversations." },
            { "Talking to one", "Type at the bottom and press Send. In a room, name a teammate with @ "
              + "to aim a message at one bot. You can walk away to another chat while a turn runs: it "
              + "keeps drawing into its own transcript, and its dot stays lit in the drawer." },
            { "What a message can do", "Hold a message for Reply, Forward, Copy — and Edit or Retry on "
              + "one that has already been saved. Reply carries what you are answering to the bot, "
              + "which never sees the transcript. Forward sends a copy to another chat, where it is "
              + "picked up as a task. Edit puts your message back in the box and drops everything "
              + "after it; Retry drops a reply and asks the same question again." },
            { "Files and Computer", "The header menu opens both. Files lists the repo this chat works "
              + "in — tap a file to put its path in the box, where the bot can read it. Computer shows "
              + "the bot's screen, scoped to this chat: a chat whose bot is not using the computer "
              + "shows nothing rather than another chat's work." },
            { "Where the work is", "The strip above the box is what the bots are doing right now, and "
              + "the queue under it is what you sent while they were busy. A card with Allow and Deny "
              + "is the bot asking before it does something the chat's approval level does not cover." },
        };
        for (String[] s : secs) {
            TextView h = bold(text(s[0], Pal.TXT, 14));
            h.setPadding(dp(2), dp(16), dp(2), dp(5));
            col.addView(h);
            TextView b = text(s[1], Pal.DIM, 13);
            airy(b, 13, 1.55f);
            col.addView(b);
        }
    }

    private void approve(final Model.Entry e, final boolean allow) {
        final int at = model.entries().indexOf(e);
        final String session = sid;
        e.done = true;
        e.allowed = allow;
        if (at >= 0) paint(at);
        new Thread(new Runnable() {
            @Override public void run() {
                try {
                    Api.post(base, token, "/api/approve",
                             "{\"session\":" + Json.quote(session) + ",\"allow\":" + allow + "}");
                } catch (IOException ex) {
                    ui.post(new Runnable() {
                        @Override public void run() { note("Could not answer the request."); }
                    });
                }
            }
        }).start();
    }

    // ---- drawing -----------------------------------------------------------------------------

    private View head(String label, int colour, long ts) {
        LinearLayout h = new LinearLayout(getContext());
        h.setOrientation(LinearLayout.HORIZONTAL);
        h.setGravity(Gravity.BOTTOM);
        h.setPadding(0, 0, 0, dp(4));
        TextView n = bold(text(label.toUpperCase(Locale.getDefault()), colour, 11));
        n.setLetterSpacing(0.045f);                    // the desktop's 0.5px, at 11sp
        n.setSingleLine(true);
        n.setEllipsize(TextUtils.TruncateAt.END);
        h.addView(n, new LinearLayout.LayoutParams(0, -2, 1f));
        // The desktop stamps a message the server gave no time for with the moment it draws it
        // (`stampAt(meta && meta.ts ? meta.ts * 1000 : Date.now())`), so a row is never left without
        // one. Only an older record lacks a `ts`; a message said live always has one.
        String when = Model.stamp(ts > 0 ? ts : System.currentTimeMillis());
        if (!when.isEmpty()) {
            TextView t = text(when, Pal.MTS, 11);
            t.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));   // the stylesheet's 500
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-2, -2);
            lp.leftMargin = dp(10);
            h.addView(t, lp);
        }
        return h;
    }

    private LinearLayout bubble(int fill, int stroke, int tl, int tr, int br, int bl) {
        LinearLayout box = new LinearLayout(getContext());
        box.setOrientation(LinearLayout.VERTICAL);
        box.setBackground(shape(fill, stroke, 1, tl, tr, br, bl));
        box.setPadding(dp(15), dp(11), dp(15), dp(11));
        return box;
    }

    /** The desktop caps a bubble at a share of the transcript's width; here that is room kept clear. */
    private View start(View v) {
        LinearLayout w = new LinearLayout(getContext());
        w.setOrientation(LinearLayout.VERTICAL);
        w.setPadding(0, 0, slack(6), 0);
        w.addView(v, new LinearLayout.LayoutParams(-2, -2));
        return w;
    }

    private View end(View v) {
        LinearLayout w = new LinearLayout(getContext());
        w.setOrientation(LinearLayout.VERTICAL);
        w.setGravity(Gravity.END);
        w.setPadding(slack(6), 0, 0, 0);
        w.addView(v, new LinearLayout.LayoutParams(-2, -2));
        return w;
    }

    /** A row that wants the width it is given — a tool's output, a command, a screenshot. */
    private View wide(View v) {
        LinearLayout w = new LinearLayout(getContext());
        w.setOrientation(LinearLayout.VERTICAL);
        w.setPadding(0, 0, slack(3), 0);
        w.addView(v, new LinearLayout.LayoutParams(-1, -2));
        return w;
    }

    private int slack(int pct) {
        return (getResources().getDisplayMetrics().widthPixels - dp(28)) * pct / 100;
    }

    /**
     * A bot writes markdown, so a reply is rendered rather than shown raw. The cutting is done by
     * {@link Md} — the desktop's own parser, checked on a plain JVM — and this only draws what it
     * returns: a heading as a heading, a fence as code, a table as a table. See `mdToHtml`, app.js:259.
     */
    private View prose(String text) {
        LinearLayout col = new LinearLayout(getContext());
        col.setOrientation(LinearLayout.VERTICAL);
        List<Md.Blk> blocks = Md.blocks(text);
        for (int i = 0; i < blocks.size(); i++) {
            View v = block(blocks.get(i));
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
            // `.md p{margin:0 0 9px}` with `>*:last-child{margin-bottom:0}`: the bubble's own padding
            // is the space under the last block, so the block's does not double it.
            lp.bottomMargin = i == blocks.size() - 1 ? 0 : dp(9);
            col.addView(v, lp);
        }
        return col;
    }

    private View block(Md.Blk b) {
        switch (b.kind) {
            case Md.CODE: return code(b.text);
            case Md.H: {
                // `.md h1..h3` at 17/15.5/14px, and h4-h6 at the body size, which is 13px there.
                float sp = b.level == 1 ? 17 : b.level == 2 ? 15.5f : b.level == 3 ? 14 : 13;
                TextView t = bold(text("", Pal.TXT, sp));
                t.setText(spans(b.text));
                t.setTextIsSelectable(true);
                airy(t, sp, 1.3f);
                return t;
            }
            case Md.UL:
            case Md.OL: return list(b);
            case Md.QUOTE: return quote(b.text);
            case Md.TABLE: return table(b.text);
            case Md.HR: {
                View rule = new View(getContext());
                rule.setBackgroundColor(Pal.LINE);
                rule.setMinimumHeight(dp(1));
                return rule;
            }
            default: return para(b.text);
        }
    }

    /** A paragraph: a single newline in the source is a line break, which is what `\n` already is. */
    private View para(String text) {
        TextView t = new TextView(getContext());
        t.setTextColor(Pal.TXT);   // prose takes the desktop's `--txt`; unset, it inherits the OEM theme
        t.setText(spans(text));
        t.setTextSize(Pal.fs(15));
        // The link spans only answer a tap under this method, and it takes the long-press selection
        // with it — which is why the blocks worth copying (code, a table) stay selectable instead.
        t.setMovementMethod(LinkMovementMethod.getInstance());
        airy(t, 15, 1.62f);
        return t;
    }

    private View list(Md.Blk b) {
        LinearLayout col = new LinearLayout(getContext());
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(dp(2), 0, 0, 0);
        String[] items = b.text.split("\n", -1);
        int n = b.kind == Md.OL ? b.level : 0;
        for (int i = 0; i < items.length; i++) {
            if (items[i].isEmpty()) continue;
            LinearLayout row = new LinearLayout(getContext());
            row.setOrientation(LinearLayout.HORIZONTAL);
            row.addView(text(b.kind == Md.OL ? (n + i) + ". " : "• ", Pal.TXT, 15));
            TextView t = new TextView(getContext());
            t.setTextColor(Pal.TXT);   // as `para`: the item's prose, not the OEM theme's default
            t.setText(spans(items[i]));
            t.setTextSize(Pal.fs(15));
            airy(t, 15, 1.62f);
            row.addView(t, new LinearLayout.LayoutParams(0, -2, 1f));
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
            lp.bottomMargin = dp(3);                          // `.md li{margin:3px 0}`
            col.addView(row, lp);
        }
        return col;
    }

    /** Quoted text, behind the desktop's own bar. Its lines are parsed again, so a quote holding a
        list or a fence reads the way it does inside the quote on the desktop. */
    private View quote(String text) {
        LinearLayout row = new LinearLayout(getContext());
        row.setOrientation(LinearLayout.HORIZONTAL);
        View bar = new View(getContext());
        bar.setBackgroundColor(Pal.LINE2);
        row.addView(bar, new LinearLayout.LayoutParams(dp(3), -1));
        View body = prose(text);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, -2, 1f);
        lp.leftMargin = dp(11);
        row.addView(body, lp);
        return row;
    }

    /**
     * A table as the phone can draw one: monospace, columns padded to a common width, so the cells
     * line up. There is no horizontal scroll here, so a cell too wide for the bubble wraps — a
     * squeezed table is worse than a wrapped one.
     */
    private View table(String text) {
        String[] rows = text.split("\n", -1);
        List<String[]> cells = new ArrayList<>();
        int cols = 0;
        for (String r : rows) {
            String[] c = r.split("\t", -1);
            cells.add(c);
            cols = Math.max(cols, c.length);
        }
        int[] wide = new int[cols];
        for (String[] c : cells) for (int i = 0; i < c.length; i++) wide[i] = Math.max(wide[i], c[i].length());
        LinearLayout col = new LinearLayout(getContext());
        col.setOrientation(LinearLayout.VERTICAL);
        col.setBackground(shape(Pal.BG, Pal.LINE, 1, 9));
        col.setPadding(dp(10), dp(8), dp(10), dp(8));
        for (int r = 0; r < cells.size(); r++) {
            String[] c = cells.get(r);
            StringBuilder s = new StringBuilder();
            for (int i = 0; i < cols; i++) {
                String cell = i < c.length ? c[i] : "";
                s.append(cell);
                if (i < cols - 1) for (int p = cell.length(); p < wide[i] + 2; p++) s.append(' ');
            }
            TextView t = mono(s.toString(), Pal.TXT, 12);
            t.setTextIsSelectable(true);
            if (r == 0) {                                     // `.md th{background:var(--bg2);font-weight:700}`
                bold(t);
                t.setBackgroundColor(Pal.BG2);
                t.setPadding(dp(4), dp(2), dp(4), dp(2));
            }
            col.addView(t);
        }
        return col;
    }

    /** A fenced block: the code, and the button that copies it. The button floats over the block's
        top-right corner as it does on the desktop, and says so on itself when it lands. */
    private View code(final String body) {
        FrameLayout frame = new FrameLayout(getContext());
        frame.setBackground(shape(Pal.BG, Pal.LINE, 1, 9));
        TextView pre = mono(body, Pal.TXT, 12);
        pre.setTextIsSelectable(true);
        airy(pre, 12, 1.55f);
        pre.setPadding(dp(11), dp(9), dp(11), dp(9));
        Cap cap = new Cap(getContext(), dp(340));
        cap.addView(pre, new ViewGroup.LayoutParams(-1, -2));
        frame.addView(cap, new FrameLayout.LayoutParams(-1, -2));

        final TextView copy = text("Copy", Pal.DIM, 11);
        copy.setPadding(dp(9), dp(3), dp(9), dp(3));
        copy.setBackground(press(shape(Pal.CARD2, Pal.LINE2, 1, 7)));
        copy.setContentDescription("Copy this code");
        copy.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) {
                ClipboardManager cb = (ClipboardManager) getContext().getSystemService(Context.CLIPBOARD_SERVICE);
                cb.setPrimaryClip(ClipData.newPlainText("code", body));
                copy.setText("Copied");                       // a click that appears to do nothing gets made twice
                copy.postDelayed(new Runnable() {
                    @Override public void run() { copy.setText("Copy"); }
                }, 1200);
            }
        });
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(-2, -2, Gravity.END | Gravity.TOP);
        lp.topMargin = dp(6);
        lp.rightMargin = dp(6);
        frame.addView(copy, lp);
        return frame;
    }

    /** One line of markdown, drawn: the block's own text with its inline formatting on top of it. */
    private CharSequence spans(String text) {
        SpannableStringBuilder out = new SpannableStringBuilder();
        String[] lines = text.split("\n", -1);
        for (int i = 0; i < lines.length; i++) {
            if (i > 0) out.append('\n');
            for (Md.Seg s : Md.segs(lines[i])) {
                int at = out.length();
                out.append(s.text);
                int end = out.length();
                if (s.kind == 1) out.setSpan(new StyleSpan(Typeface.BOLD), at, end, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
                else if (s.kind == 2) out.setSpan(new StyleSpan(Typeface.ITALIC), at, end, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
                else if (s.kind == 3) out.setSpan(new StrikethroughSpan(), at, end, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
                else if (s.kind == 4) {
                    // `.md code` reads as prose, so it takes the accent walked to a legible lightness.
                    out.setSpan(new TypefaceSpan("monospace"), at, end, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
                    out.setSpan(new ForegroundColorSpan(Pal.ACCENT_TXT), at, end, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
                } else if (s.kind == 5) {
                    out.setSpan(link(s.href), at, end, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
                }
            }
        }
        return out;
    }

    /** A person's own message, drawn: nothing formatted, only its URLs made tappable. */
    private CharSequence literal(String text) {
        SpannableStringBuilder out = new SpannableStringBuilder();
        String[] lines = (text == null ? "" : text).split("\n", -1);
        for (int i = 0; i < lines.length; i++) {
            if (i > 0) out.append('\n');
            for (Md.Seg s : Md.literal(lines[i])) {
                int at = out.length();
                out.append(s.text);
                if (s.kind == 5) out.setSpan(link(s.href), at, out.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
            }
        }
        return out;
    }

    /** A link, opened by the phone's own browser. `Md` has already vetted the href, so an unusable
        one arrives as "#" and is drawn as the prose it is. */
    private ClickableSpan link(final String href) {
        return new ClickableSpan() {
            @Override public void onClick(View v) {
                if (href == null || href.isEmpty() || href.equals("#")) return;
                try {
                    getContext().startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(href)));
                } catch (Exception e) {
                    // A phone with nothing that opens links would otherwise do nothing at all on a tap,
                    // which reads as a dead link rather than as a missing browser.
                    note("Nothing on this phone opens links.");
                }
            }
            @Override public void updateDrawState(android.text.TextPaint p) {
                p.setColor(Pal.ACCENT_TXT);
                p.setUnderlineText(true);
            }
        };
    }

    /** Whether a tool's output reads as a failure. `run_shell` states its outcome exactly — the server
        prefixes `exit N` — and every other refusal is a parenthesised note the tool wrote, of which
        `(empty)` is a result rather than a failure. */
    private static boolean failed(String name, String out) {
        if (name.equals("run_shell")) {
            java.util.regex.Matcher m = java.util.regex.Pattern.compile("^exit (\\d+)").matcher(out);
            return m.find() && !m.group(1).equals("0");
        }
        return out.startsWith("(") && !out.equals("(empty)");
    }

    private static Bitmap decode(String dataUrl) {
        int comma = dataUrl.indexOf(',');
        if (comma < 0) return null;
        try {
            byte[] raw = Base64.decode(dataUrl.substring(comma + 1), Base64.DEFAULT);
            return BitmapFactory.decodeByteArray(raw, 0, raw.length);
        } catch (Exception e) {
            return null;
        }
    }

    // ---- small things ------------------------------------------------------------------------

    /** The desktop's line-height, as Android wants it: a TextView's own line box is already about
        1.17 of the font, so the difference is added as leading. */
    private void airy(TextView t, float sp, float lh) {
        t.setLineSpacing((lh - 1.17f) * Pal.fs(sp) * getResources().getDisplayMetrics().scaledDensity, 1f);
    }

    private TextView navlabel(String s) {
        TextView t = bold(text(s, Pal.DIM2, 11));
        t.setAllCaps(true);
        t.setLetterSpacing(0.09f);
        t.setPadding(dp(8), dp(10), dp(8), dp(6));
        return t;
    }

    /** The desktop's monogram tile: the bot's own hue under a lift of the same hue. */
    private TextView tile(String name, String color, String emoji, int fs, int radius) {
        int hue = hue(color);
        TextView t = bold(text(emoji.isEmpty() ? Model.initials(name) : emoji, Pal.lift(hue), fs));
        t.setGravity(Gravity.CENTER);
        t.setBackground(shape(Pal.tile(hue), Pal.LINE, 1, radius));
        return t;
    }

    private static int hue(String color) {
        for (int i = 0; i < HUES.length; i++) if (HUES[i].equals(color)) return Pal.AV[i];
        return Pal.AV[1];
    }

    /** The hue a name wears, or 0 for a name no bot in the roster answers to. */
    private int hueOf(String who) {
        Integer h = hues.get(who);
        return h == null ? 0 : h;
    }

    private TextView text(String s, int colour, float sp) {
        TextView t = new TextView(getContext());
        t.setText(s == null ? "" : s);
        t.setTextColor(colour);
        t.setTextSize(Pal.fs(sp));      // every size here is a designed one, scaled by the size setting
        if (Pal.serif()) t.setTypeface(Typeface.SERIF);
        else if (Pal.mono()) t.setTypeface(Typeface.MONOSPACE);
        return t;
    }

    private TextView mono(String s, int colour, float sp) {
        TextView t = text(s, colour, sp);
        t.setTypeface(Typeface.MONOSPACE);
        return t;
    }

    /** Bold, in whatever family the theme is reading in — and never over a code block's monospace,
        which a table's header row would otherwise lose to the heading it is. */
    private TextView bold(TextView t) {
        Typeface was = t.getTypeface();
        boolean mono = was != null && was.equals(Typeface.MONOSPACE);
        t.setTypeface(Typeface.create(mono ? Typeface.MONOSPACE
                                          : Pal.serif() ? Typeface.SERIF : Typeface.DEFAULT,
                                      Typeface.BOLD));
        return t;
    }

    /** A flat fill behind the desktop's corners: a bubble, a chip, a row, a box. */
    private GradientDrawable shape(int fill, int radius) {
        GradientDrawable d = new GradientDrawable();
        d.setColor(fill);
        d.setCornerRadius(dp(radius));
        return d;
    }

    private GradientDrawable shape(int fill, int stroke, int width, int radius) {
        GradientDrawable d = shape(fill, radius);
        if (width > 0) d.setStroke(dp(width), stroke);
        return d;
    }

    private GradientDrawable shape(int fill, int stroke, int width, int tl, int tr, int br, int bl) {
        GradientDrawable d = new GradientDrawable();
        d.setColor(fill);
        d.setCornerRadii(new float[]{ dp(tl), dp(tl), dp(tr), dp(tr), dp(br), dp(br), dp(bl), dp(bl) });
        d.setStroke(dp(width), stroke);
        return d;
    }

    private GradientDrawable oval(int colour) {
        GradientDrawable d = new GradientDrawable();
        d.setShape(GradientDrawable.OVAL);
        d.setColor(colour);
        return d;
    }

    /** The platform's own press state — the desktop's hover fill, as a finger gets it. */
    private Drawable press(Drawable d) {
        return new RippleDrawable(ColorStateList.valueOf(Pal.FOCUS), d, null);
    }

    /** A row you are in: the desktop's card, with the accent bar on its own left edge. */
    private Drawable selected(int fill, int radius, int barInset) {
        GradientDrawable card = shape(fill, Pal.LINE2, 1, radius);
        android.graphics.drawable.LayerDrawable l = new android.graphics.drawable.LayerDrawable(
                new Drawable[]{ shape(Pal.ACCENT, 3), card });
        l.setLayerGravity(0, Gravity.LEFT);
        l.setLayerWidth(0, dp(3));
        l.setLayerInset(0, 0, dp(barInset), 0, dp(barInset));
        return l;
    }

    /** The desktop spins a ring while a tool or a step runs; this is the platform's own. */
    private ProgressBar spinner() {
        return spinner(6);
    }

    /** The same ring leading a row rather than following text: no gap to open. */
    private ProgressBar spinner(int left) {
        ProgressBar p = new ProgressBar(getContext(), null, android.R.attr.progressBarStyleSmall);
        p.setIndeterminateTintList(ColorStateList.valueOf(Pal.ACCENT));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(dp(12), dp(12));
        lp.leftMargin = dp(left);
        p.setLayoutParams(lp);
        return p;
    }

    private LinearLayout.LayoutParams spaced(int left) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-2, -2);
        lp.leftMargin = dp(left);
        return lp;
    }

    /** A JSON array as the reader's own list type, so what comes back needs no cast at each use. */
    @SuppressWarnings("unchecked")
    private static List<Object> asList(Object o) {
        return o instanceof List ? (List<Object>) o : Collections.emptyList();
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> row(Object o) {
        return o instanceof Map ? (Map<String, Object>) o : null;
    }

    /** Say something in passing. A notice is raised from whichever thread found the problem — often a
        background one — and a Toast built off the main looper throws, so it hops here. */
    private void note(final String msg) {
        if (Looper.myLooper() == Looper.getMainLooper()) {
            Toast.makeText(getContext(), msg, Toast.LENGTH_LONG).show();
            return;
        }
        ui.post(new Runnable() {
            @Override public void run() { Toast.makeText(getContext(), msg, Toast.LENGTH_LONG).show(); }
        });
    }

    private int dp(int n) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, n, getResources().getDisplayMetrics());
    }
}
