package io.anzenbot.app;

import java.text.DateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * The transcript on the phone: what a turn's events turn into, and what a reopened chat is.
 *
 * Deliberately free of Android, like {@link Targets} and {@link Api}, because this is the part of
 * the native client most likely to be quietly wrong and the build machine has no phone attached to
 * catch it. tests/android/ModelCheck.java runs this on a JVM against the exact events the server
 * emits.
 *
 * A turn arrives as a stream of small events, not as a transcript. The server streams machinery live
 * — plans, tool calls, approvals, the little system notes, the steps a bot is working through — and
 * saves only some of it, so a chat opened later is the conversation plus whatever the server chose to
 * keep: the work a bot did (its tool rows), a room's hand-off, and every note this app wrote about
 * stopping the bot. {@link #apply} folds each event into the entry it belongs to, and {@link #load}
 * reads the saved conversation back. The two must agree: a saved note and a live one are drawn by the
 * same row.
 *
 * The wording of a status, a step or a clock lives here as a static, because the desktop writes it
 * down once and the two clients must not drift: the phone says "needs your approval" for the same
 * reason the computer does.
 */
final class Model {
    static final int USER = 0, BOT = 1, CARD = 2, TOOL = 3, APPROVAL = 4, IMAGE = 5, NOTICE = 6, STEP = 7;

    static final class Entry {
        int kind;
        String id = "";       // a tool's id: its call and its result are one row, not two
        String who = "";      // the bot id behind this entry
        String text = "";     // the body: a message, a card's text, a tool's output, a step log
        String title = "";    // a card's heading, or a tool's one-line summary
        String sub = "";      // a card's kind (plan/sys/final/error) or a tool's name, or a step's phase
        String png = "";      // an image's data URL
        String note = "";     // an image's caption
        String level = "";    // a notice's level: warn or error
        boolean done;         // a tool that has returned; an approval that is answered; a closed step
        boolean allowed;      // an approval's answer
        boolean failed;       // a step that ended because the turn broke
        int steps;            // a step card's phase count
        long ts;              // when this was said, epoch ms; 0 when the server did not say
        long since;           // epoch ms this row started, for its clock; 0 when nothing is running
        boolean open;         // the reader has folded this row open
        int i = -1;           // its place in the saved history, for Edit and Retry; -1 when it has none
        String qWho = "";     // the message this one answers, as its author and its words
        String qText = "";
        boolean fwd;          // this arrived as a forward, and says so

        boolean live() { return since != 0; }
    }

    private final List<Entry> entries = new ArrayList<>();
    private final Map<String, String> names = new HashMap<>();    // bot id -> display name
    private final Map<String, Entry> streaming = new HashMap<>(); // agent -> the reply being typed
    private final Map<String, Entry> tools = new HashMap<>();     // tool id -> its row
    private final Map<String, Entry> steps = new HashMap<>();     // agent -> the step card it is on
    private boolean running;                                      // a turn is in flight
    private boolean room;                                         // the chat on screen is a room
    private String chatName = "";                                 // what that chat is called
    private String state = "idle";                                // the last state the server named
    private String model = "", approval = "";                     // what this chat will answer with, and its gate
    private Map<String, Object> ctx;                              // the last context measurement

    List<Entry> entries() { return entries; }
    boolean running() { return running; }
    String state() { return state; }
    String model() { return model; }
    String approval() { return approval; }
    Map<String, Object> ctx() { return ctx; }

    /** How full this chat's window is, as a whole percent — what the Context chip shows. */
    int ctxPct() {
        if (ctx == null) return 0;
        long used = Json.num(ctx.get("tokens")), limit = Json.num(ctx.get("limit"));
        if (limit <= 0) return 0;
        return (int) Math.min(100, used * 100 / limit);
    }

    /** The bots' names, so a reply is headed with "Producer" and not "producer". */
    void roster(Map<String, String> byId) {
        names.clear();
        if (byId != null) names.putAll(byId);
    }

    String name(String id) {
        if (id == null || id.isEmpty()) return "";
        String n = names.get(id);
        return n == null || n.isEmpty() ? id : n;
    }

    /** Which chat this is: a room names its summary for the room, a direct chat for the bot. */
    void chat(String name, boolean isRoom) {
        chatName = name == null ? "" : name;
        room = isRoom;
    }

    /** What `/api/history` says about the chat itself: the model it answers with, its approval level,
        and how full its window was when it last spoke. Read before the messages, so the chips are
        right the moment the chat opens. */
    void meta(Object modelName, Object approvalLevel, Object ctxRecord) {
        model = Json.str(modelName);
        approval = Json.str(approvalLevel);
        ctx = ctxRecord instanceof Map ? cast(ctxRecord) : null;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> cast(Object o) { return (Map<String, Object>) o; }

    void clear() {
        entries.clear(); streaming.clear(); tools.clear(); steps.clear();
        running = false; state = "idle"; ctx = null; model = ""; approval = "";
    }

    /** The saved conversation: {@code /api/history}'s messages, in the roles the server saves. */
    void load(List<Object> messages) {
        clear();
        if (messages == null) return;
        // The saved index, not a running count: a message with no content is skipped below, and a
        // count would then be one behind, so Edit would truncate to the wrong place.
        for (int i = 0; i < messages.size(); i++) {
            Object o = messages.get(i);
            if (!(o instanceof Map)) continue;
            Map<?, ?> m = (Map<?, ?>) o;
            String role = Json.str(m.get("role")), text = Json.str(m.get("content"));
            // A tool row is the one saved row with no prose of its own: its output is the body and its
            // name is the heading, and the pair is what makes a reopened chat show the work it did.
            if ("tool".equals(role)) {
                Entry t = new Entry();
                t.kind = TOOL; t.who = Json.str(m.get("agent")); t.sub = Json.str(m.get("name"));
                t.title = head(t.sub, m.get("args")); t.text = Json.str(m.get("out")); t.done = true;
                t.ts = seconds(m.get("ts"));
                entries.add(t);
                continue;
            }
            if (text.isEmpty()) continue;
            Entry e = new Entry();
            e.text = text;
            e.ts = seconds(m.get("ts"));
            e.i = i;
            marks(m, e);
            if ("user".equals(role)) {
                e.kind = USER;
            } else if ("notice".equals(role) || "sys".equals(role)) {
                // The app's own account of what happened — a refusal, a denial, a stalled model. It is
                // saved for exactly this: reopening the chat must show the reasons, not only the work.
                e.kind = NOTICE; e.level = "warn";
            } else if ("route".equals(role)) {
                e.kind = CARD; e.sub = "plan"; e.title = ROUTE_LABEL;
            } else {
                e.kind = BOT; e.who = Json.str(m.get("who"));
            }
            entries.add(e);
        }
    }

    private static long seconds(Object o) { return Json.num(o) * 1000; }   // history keeps seconds

    /** A saved message's reply and forward marks. The server writes a reply as {@code quote:{who,text}}
        and a forward as {@code fwd:true}, and both are read here so a reopened chat draws them. */
    private static void marks(Map<?, ?> m, Entry e) {
        e.fwd = Json.truth(m.get("fwd"));
        Object q = m.get("quote");
        if (q instanceof Map) {
            e.qWho = Json.str(((Map<?, ?>) q).get("who"));
            e.qText = Json.str(((Map<?, ?>) q).get("text"));
        }
    }

    /** Your own message, added the moment it is sent so the screen answers the tap at once. */
    int addUser(String text, String qWho, String qText, boolean fwd) {
        Entry e = new Entry();
        e.kind = USER;
        e.text = text;
        e.ts = System.currentTimeMillis();
        e.qWho = qWho == null ? "" : qWho;
        e.qText = qText == null ? "" : qText;
        e.fwd = fwd;
        entries.add(e);
        return entries.size() - 1;
    }

    /**
     * Fold one event from the turn's stream into the transcript.
     *
     * Returns the index of the entry it changed or added, -1 when the event is not something the
     * transcript shows. An entry can also be dropped (a reply that came back empty), which moves
     * every index after it — the caller notices by comparing sizes and rebuilds, rather than this
     * method having to say so.
     */
    int apply(String json) {
        Map<String, Object> ev = Json.obj(json);
        if (ev == null) return -1;
        String type = Json.str(ev.get("type"));
        long now = System.currentTimeMillis();

        if (type.equals("status")) {
            String st = Json.str(ev.get("state"));
            running = !("finished".equals(st) || "idle".equals(st) || st.isEmpty());
            state = st.isEmpty() ? state : st;
            String agent = Json.str(ev.get("agent"));
            // A phase the bot is in gets a step card, and the same phase said again is the same step:
            // the server re-announces it every round-trip, and counting those would make the card read
            // as the network rather than as the work.
            if (stepLabel(st) != null) return step(agent, st, now);
            if (!running) closeSteps(false);
            return -1;
        }
        if (type.equals("done")) { running = false; state = "finished"; closeSteps(false); return -1; }
        if (type.equals("ctx")) { ctx = ev.get("ctx") instanceof Map ? cast(ev.get("ctx")) : null; return -1; }

        if (type.equals("agent_text")) {
            String agent = Json.str(ev.get("agent"));
            String text = Json.str(ev.get("text"));
            Entry e = streaming.get(agent);
            if (Json.truth(ev.get("delta"))) {
                // Tokens arrive one at a time and the row grows with them.
                if (e == null) {
                    e = new Entry(); e.kind = BOT; e.who = agent; e.ts = now;
                    streaming.put(agent, e); entries.add(e);
                }
                e.text += text;
                return entries.indexOf(e);
            }
            // The full text closes the stream, and it replaces what the tokens built rather than
            // being appended to it — the same text, delivered whole.
            streaming.remove(agent);
            if (text.trim().isEmpty()) {
                if (e != null) entries.remove(e);
                return -1;
            }
            if (e == null) { e = new Entry(); e.kind = BOT; e.who = agent; e.ts = now; entries.add(e); }
            e.text = text;
            return entries.indexOf(e);
        }

        if (type.equals("plan")) {
            String kind = Json.str(ev.get("kind"));
            String agent = Json.str(ev.get("agent"));
            String title = kind.equals("route") ? ROUTE_LABEL
                         : agent.isEmpty() ? "Plan" : name(agent) + "'s plan";
            Entry e = new Entry();
            e.kind = CARD; e.sub = "plan"; e.who = agent; e.title = title;
            e.text = Json.str(ev.get("text")); e.ts = now;
            entries.add(e);
            return entries.size() - 1;
        }

        if (type.equals("agent")) {
            if (!"start".equals(Json.str(ev.get("state")))) return -1;
            // A hand-off names what was handed over: a teammate's name with no task under it leaves a
            // room showing a delegation to nothing, which is half of why a room read as silent.
            String who = Json.str(ev.get("name")), task = Json.str(ev.get("task"));
            if (task.length() > 160) task = task.substring(0, 160);
            Entry e = new Entry();
            e.kind = CARD; e.sub = "sys"; e.ts = now;
            e.text = "▸ " + who + " started" + (task.isEmpty() ? "" : ": " + task)
                   + (room ? " — its steps are in " + who + "'s chat" : "");
            entries.add(e);
            return entries.size() - 1;
        }

        if (type.equals("tool")) return tool(ev, now);

        if (type.equals("approval")) {
            Entry e = new Entry();
            e.kind = APPROVAL; e.who = Json.str(ev.get("agent"));
            e.text = Json.str(ev.get("cmd")); e.ts = now;
            entries.add(e);
            return entries.size() - 1;
        }

        if (type.equals("steer")) {
            Entry e = new Entry();
            e.kind = USER; e.text = Json.str(ev.get("text")); e.ts = now;
            marks(ev, e);                        // a steer may itself be a reply, and says so
            entries.add(e);
            return entries.size() - 1;
        }

        if (type.equals("final")) {
            // The server sends the summary with no author on it: in a room it is the room's, and in
            // a direct chat it is the chat's, which is the bot.
            Entry e = new Entry();
            e.kind = CARD; e.sub = "final";
            e.title = room ? "Room · summary" : (chatName.isEmpty() ? "Report" : chatName + " · report");
            e.text = Json.str(ev.get("text")); e.ts = now;
            entries.add(e);
            return entries.size() - 1;
        }

        if (type.equals("error")) {
            closeSteps(true);
            Entry e = new Entry();
            e.kind = CARD; e.sub = "error";
            e.text = "The bot hit an error and stopped: " + Json.str(ev.get("msg")); e.ts = now;
            entries.add(e);
            return entries.size() - 1;
        }

        // This app stopping the bot — a refused command, a denied card, a model that stalled. It goes
        // in the transcript and not only in the step row, because the row is folded and a bot that was
        // refused and then went quiet used to leave the room with nothing to read.
        if (type.equals("notice")) {
            String text = Json.str(ev.get("text"));
            if (text.isEmpty()) return -1;
            if ("error".equals(Json.str(ev.get("level")))) closeSteps(true);
            Entry e = new Entry();
            e.kind = NOTICE; e.text = text; e.level = Json.str(ev.get("level")); e.ts = now;
            entries.add(e);
            return entries.size() - 1;
        }

        if (type.equals("shot") || type.equals("image")) {
            String png = Json.str(ev.get("png"));
            if (png.isEmpty()) return -1;
            Entry e = new Entry();
            e.kind = IMAGE; e.png = png; e.note = Json.str(ev.get("note")); e.ts = now;
            e.sub = type.equals("image") ? "Image" : "Screenshot";
            entries.add(e);
            return entries.size() - 1;
        }

        if (type.equals("learned")) {
            Entry e = new Entry();
            e.kind = CARD; e.sub = "sys";
            e.text = "learned from " + name(Json.str(ev.get("agent"))) + ": " + join(ev.get("notes"), " · ");
            e.ts = now;
            entries.add(e);
            return entries.size() - 1;
        }

        if (type.equals("context")) {
            long dropped = Json.num(ev.get("dropped"));
            Entry e = new Entry();
            e.kind = CARD; e.sub = "sys";
            e.text = "compressed " + dropped + " earlier step" + (dropped == 1 ? "" : "s")
                   + " to fit the model's context window (" + Json.num(ev.get("limit")) + " tokens)";
            e.ts = now;
            entries.add(e);
            return entries.size() - 1;
        }

        if (type.equals("workdir")) {
            String channel = Json.str(ev.get("channel"));
            Entry e = new Entry();
            e.kind = CARD; e.sub = "sys";
            e.text = "working in " + Json.str(ev.get("path")) + (channel.isEmpty() ? "" : " (" + channel + ")");
            e.ts = now;
            entries.add(e);
            return entries.size() - 1;
        }

        return -1;
    }

    /** One tool call. The server sends it twice under the same id — once as it starts, once with the
        result — so the first event makes the row and the second fills it. */
    private int tool(Map<String, Object> ev, long now) {
        String id = Json.str(ev.get("id"));
        Entry e = id.isEmpty() ? null : tools.get(id);
        if (e == null) {
            e = new Entry();
            e.kind = TOOL;
            e.id = id;
            e.who = Json.str(ev.get("agent"));
            e.sub = Json.str(ev.get("name"));
            e.title = head(e.sub, ev.get("args"));
            e.ts = now;
            if (!id.isEmpty()) tools.put(id, e);
            entries.add(e);
        }
        if (ev.get("out") != null) { e.text = Json.str(ev.get("out")); e.done = true; e.since = 0; }
        else e.since = e.since == 0 ? now : e.since;   // a running tool's row carries its own clock
        return entries.indexOf(e);
    }

    /** One bot's step card, in place. The phase is the card's label; the log behind it is the phases
        in order, which is what a reader opens to see what a long turn has been doing. */
    private int step(String agent, String phase, long now) {
        Entry e = steps.get(agent);
        if (e == null) {
            e = new Entry();
            e.kind = STEP; e.who = agent; e.sub = phase; e.steps = 1;
            e.since = now; e.ts = now;
            e.text = "1. " + stepLabel(phase);
            steps.put(agent, e);
            entries.add(e);
            return entries.size() - 1;
        }
        if (phase.equals(e.sub)) return entries.indexOf(e);   // the same phase is not a new step
        e.sub = phase; e.steps++; e.since = now; e.done = false; e.failed = false;
        e.text += "\n" + e.steps + ". " + stepLabel(phase);
        return entries.indexOf(e);
    }

    /** The turn is over: every step card stops its clock and says how it ended. */
    private void closeSteps(boolean failed) {
        for (Entry e : entries) {
            if (e.kind != STEP || e.done) continue;
            e.done = true; e.failed = failed; e.since = 0;
        }
        steps.clear();
    }

    /** The one line that says what a tool is doing, in the same words the web app uses. */
    static String head(String name, Object argsObj) {
        Map<?, ?> a = argsObj instanceof Map ? (Map<?, ?>) argsObj : new HashMap<>();
        String s;
        if (name.equals("run_shell")) s = "$ " + Json.str(a.get("command"));
        else if (name.equals("browser_open")) s = Json.str(a.get("url"));
        else if (name.equals("browser_click") || name.equals("browser_type")) s = Json.str(a.get("selector"));
        else if (name.equals("browser_press")) s = Json.str(a.get("key"));
        else if (name.equals("read_file") || name.equals("write_file") || name.equals("list_files")) s = Json.str(a.get("path"));
        else if (name.equals("memory_update")) s = Json.str(a.get("note"));
        else if (name.equals("browser_see")) s = Json.str(a.get("question"));
        else if (name.equals("generate_image")) s = Json.str(a.get("prompt"));
        else if (name.equals("use_skill")) s = Json.str(a.get("skill")) + (a.get("file") == null ? "" : " · " + Json.str(a.get("file")));
        else if (name.equals("delegate")) s = "→ " + Json.str(a.get("role")) + ": " + Json.str(a.get("task"));
        else s = Json.write(argsObj);
        return s.length() > 200 ? s.substring(0, 200) : s;
    }

    /** A tool's name as a person would say it. Unknown tools keep the name the server sent. */
    static String label(String name) {
        // These three read differently from the generic rules below, and the web app says them this way.
        if (name.equals("browser_see")) return "browser · look";
        if (name.equals("browser_press")) return "browser · key";
        if (name.equals("drive_api")) return "gdrive · api";
        if (name.startsWith("browser_")) return "browser · " + name.substring(8);
        if (name.endsWith("_api")) return name.substring(0, name.length() - 4) + " · api";
        if (name.equals("run_shell")) return "shell";
        if (name.equals("read_file")) return "read file";
        if (name.equals("write_file")) return "write file";
        if (name.equals("list_files")) return "list files";
        if (name.equals("generate_image")) return "draw image";
        if (name.equals("memory_update")) return "memory";
        if (name.equals("use_skill")) return "read skill";
        if (name.equals("webhook_post")) return "webhook · post";
        return name;
    }

    /** How long a turn has been going, in the web app's words: seconds, then minutes and seconds. */
    static String clock(long ms) {
        long s = ms / 1000;
        if (s < 60) return s + "s";
        return (s / 60) + "m " + (s % 60 < 10 ? "0" : "") + (s % 60) + "s";
    }

    // ---- the words, written down once ---------------------------------------------------------

    /** The status a chat is in, as the desktop's header says it. `working` drops the dock's whimsy. */
    static String stateLabel(String st) {
        if (st == null) return "idle";
        if (st.equals("working")) return "working";
        if (st.equals("thinking")) return "thinking…";
        if (st.equals("searching")) return "searching…";
        if (st.equals("approval")) return "needs your approval";
        if (st.equals("question")) return "asking";
        if (st.equals("finished")) return "done";
        if (st.equals("error")) return "error";
        return st;
    }

    /** A phase a bot is in, or null when the state is not a step at all. */
    static String stepLabel(String st) {
        if (st == null) return null;
        if (st.equals("thinking")) return "Thinking…";
        if (st.equals("working")) return "Working…";
        if (st.equals("searching")) return "Searching…";
        if (st.equals("approval")) return "Waiting for your approval…";
        if (st.equals("question")) return "Asking you something…";
        return null;
    }

    /** The same step, said again once it has been going a while: a label that never changes is
        indistinguishable from a bot that has hung. */
    static String stepLong(String st) {
        if (st == null) return null;
        if (st.equals("thinking")) return "Still thinking…";
        if (st.equals("working")) return "Still working…";
        if (st.equals("searching")) return "Still searching…";
        if (st.equals("approval")) return "Still waiting for your approval…";
        if (st.equals("question")) return "Still waiting for your answer…";
        return null;
    }

    /** The label a step card carries: its count and its phase, and the long form past the deadline. */
    static String stepTitle(Entry e, boolean long_) {
        String s = long_ ? stepLong(e.sub) : stepLabel(e.sub);
        return "Step " + Math.max(1, e.steps) + " · " + (s == null ? e.sub : s);
    }

    /** Past this, a running row says it is still going and turns amber. */
    static final long LONG_STEP_MS = 45000;

    static final String ROUTE_LABEL = "Who's on it";

    /** A monogram for a bot with no logo, in the desktop's own rule. */
    static String initials(String s) {
        String[] w = (s == null || s.trim().isEmpty() ? "?" : s.trim()).split("\\s+");
        if (w.length == 0) return "?";
        if (w.length > 1) return ("" + w[0].charAt(0) + w[1].charAt(0)).toUpperCase(Locale.ROOT);
        String one = w[0];
        java.util.regex.Matcher m = java.util.regex.Pattern.compile("[A-Z]?[a-z]+|[A-Z]+(?![a-z])").matcher(one);
        List<String> camel = new ArrayList<>();
        while (m.find()) camel.add(m.group());
        if (camel.size() > 1) return ("" + camel.get(0).charAt(0) + camel.get(1).charAt(0)).toUpperCase(Locale.ROOT);
        return one.substring(0, Math.min(2, one.length())).toUpperCase(Locale.ROOT);
    }

    /** The time a message was said, stamped the way the desktop stamps it. The desktop asks the
        browser for `hour:2-digit, minute:2-digit` in the machine's own locale, so it reads "10:57 PM"
        on en-US and "22:57" where the clock is 24-hour. Locale-following is the behaviour; hardcoding
        either shape is what made the two clients disagree. */
    static String stamp(long ts) {
        if (ts <= 0) return "";
        return DateFormat.getTimeInstance(DateFormat.SHORT, Locale.getDefault()).format(new Date(ts));
    }

    /** How long ago a chat last moved, in the desktop's chat list: now, 5m, 3h, 2d, 1w. */
    static String ago(long ts) {
        if (ts <= 0) return "";
        long s = Math.max(0, System.currentTimeMillis() / 1000 - ts / 1000);
        if (s < 60) return "now";
        if (s < 3600) return (s / 60) + "m";
        if (s < 86400) return (s / 3600) + "h";
        if (s < 604800) return (s / 86400) + "d";
        return (s / 604800) + "w";
    }

    private static String join(Object list, String sep) {
        if (!(list instanceof List)) return "";
        StringBuilder b = new StringBuilder();
        for (Object o : (List<?>) list) {
            if (b.length() > 0) b.append(sep);
            b.append(Json.str(o));
        }
        return b.toString();
    }
}
