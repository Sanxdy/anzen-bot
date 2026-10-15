package io.anzenbot.app;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * The transcript on the phone: what a turn's events turn into, and what a reopened chat is.
 *
 * Deliberately free of Android, like {@link Targets} and {@link Api}, because this is the part of
 * the native client most likely to be quietly wrong and the build machine has no phone attached to
 * catch it. tests/android/ModelCheck.java runs this on a JVM against the exact events the server
 * emits.
 *
 * A turn arrives as a stream of small events, not as a transcript. `plan`, `tool`, `approval` and the
 * little `sys` notes are machinery: the server streams them live and never writes them down, so a
 * chat opened later is the conversation — your messages and the bot's replies — and nothing else.
 * {@link #apply} folds each event into the entry it belongs to, and {@link #load} reads the saved
 * conversation back.
 */
final class Model {
    static final int USER = 0, BOT = 1, CARD = 2, TOOL = 3, APPROVAL = 4, IMAGE = 5;

    static final class Entry {
        int kind;
        String id = "";       // a tool's id: its call and its result are one row, not two
        String who = "";      // the bot id behind this entry
        String text = "";     // the body: a message, a card's text, a tool's output
        String title = "";    // a card's heading, or a tool's one-line summary
        String sub = "";      // a card's kind (plan/sys/final/error) or a tool's name
        String png = "";      // an image's data URL
        String note = "";     // an image's caption
        boolean done;         // a tool that has returned; an approval that is answered
        boolean allowed;      // an approval's answer
    }

    private final List<Entry> entries = new ArrayList<>();
    private final Map<String, String> names = new HashMap<>();    // bot id -> display name
    private final Map<String, Entry> streaming = new HashMap<>(); // agent -> the reply being typed
    private final Map<String, Entry> tools = new HashMap<>();     // tool id -> its row
    private boolean running;                                      // a turn is in flight
    private boolean room;                                         // the chat on screen is a room
    private String chatName = "";                                 // what that chat is called

    List<Entry> entries() { return entries; }
    boolean running() { return running; }

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

    void clear() {
        entries.clear(); streaming.clear(); tools.clear();
        running = false;
    }

    /** The saved conversation: {@code /api/history}'s messages. */
    void load(List<Object> messages) {
        clear();
        if (messages == null) return;
        for (Object o : messages) {
            if (!(o instanceof Map)) continue;
            Map<?, ?> m = (Map<?, ?>) o;
            String text = Json.str(m.get("content"));
            if (text.isEmpty()) continue;
            Entry e = new Entry();
            if ("user".equals(Json.str(m.get("role")))) {
                e.kind = USER;
            } else {
                e.kind = BOT;
                e.who = Json.str(m.get("who"));
            }
            e.text = text;
            entries.add(e);
        }
    }

    /** Your own message, added the moment it is sent so the screen answers the tap at once. */
    int addUser(String text) {
        Entry e = new Entry();
        e.kind = USER;
        e.text = text;
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

        if (type.equals("status")) { running = !"finished".equals(Json.str(ev.get("state"))); return -1; }
        if (type.equals("done")) { running = false; return -1; }
        if (type.equals("ctx")) return -1;                 // the context chip: no chip on the phone

        if (type.equals("agent_text")) {
            String agent = Json.str(ev.get("agent"));
            String text = Json.str(ev.get("text"));
            Entry e = streaming.get(agent);
            if (Json.truth(ev.get("delta"))) {
                // Tokens arrive one at a time and the row grows with them.
                if (e == null) {
                    e = new Entry(); e.kind = BOT; e.who = agent;
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
            if (e == null) { e = new Entry(); e.kind = BOT; e.who = agent; entries.add(e); }
            e.text = text;
            return entries.indexOf(e);
        }

        if (type.equals("plan")) {
            String kind = Json.str(ev.get("kind"));
            String agent = Json.str(ev.get("agent"));
            String title = kind.equals("route") ? "Handing off"
                         : agent.isEmpty() ? "Plan" : name(agent) + "'s plan";
            Entry e = new Entry();
            e.kind = CARD; e.sub = "plan"; e.who = agent; e.title = title; e.text = Json.str(ev.get("text"));
            entries.add(e);
            return entries.size() - 1;
        }

        if (type.equals("agent")) {
            if (!"start".equals(Json.str(ev.get("state")))) return -1;
            Entry e = new Entry();
            e.kind = CARD; e.sub = "sys"; e.text = "▸ " + Json.str(ev.get("name")) + " started";
            entries.add(e);
            return entries.size() - 1;
        }

        if (type.equals("tool")) return tool(ev);

        if (type.equals("approval")) {
            Entry e = new Entry();
            e.kind = APPROVAL; e.who = Json.str(ev.get("agent")); e.text = Json.str(ev.get("cmd"));
            entries.add(e);
            return entries.size() - 1;
        }

        if (type.equals("steer")) {
            Entry e = new Entry();
            e.kind = USER; e.text = Json.str(ev.get("text"));
            entries.add(e);
            return entries.size() - 1;
        }

        if (type.equals("final")) {
            // The server sends the summary with no author on it: in a room it is the room's, and in
            // a direct chat it is the chat's, which is the bot.
            Entry e = new Entry();
            e.kind = CARD; e.sub = "final";
            e.title = room ? "Room · summary" : (chatName.isEmpty() ? "Report" : chatName + " · report");
            e.text = Json.str(ev.get("text"));
            entries.add(e);
            return entries.size() - 1;
        }

        if (type.equals("error")) {
            Entry e = new Entry();
            e.kind = CARD; e.sub = "error";
            e.text = "The bot hit an error and stopped: " + Json.str(ev.get("msg"));
            entries.add(e);
            return entries.size() - 1;
        }

        if (type.equals("shot") || type.equals("image")) {
            String png = Json.str(ev.get("png"));
            if (png.isEmpty()) return -1;
            Entry e = new Entry();
            e.kind = IMAGE; e.png = png; e.note = Json.str(ev.get("note"));
            e.sub = type.equals("image") ? "Image" : "Screenshot";
            entries.add(e);
            return entries.size() - 1;
        }

        if (type.equals("learned")) {
            Entry e = new Entry();
            e.kind = CARD; e.sub = "sys";
            e.text = "learned from " + name(Json.str(ev.get("agent"))) + ": " + join(ev.get("notes"), " · ");
            entries.add(e);
            return entries.size() - 1;
        }

        if (type.equals("context")) {
            long dropped = Json.num(ev.get("dropped"));
            Entry e = new Entry();
            e.kind = CARD; e.sub = "sys";
            e.text = "compressed " + dropped + " earlier step" + (dropped == 1 ? "" : "s")
                   + " to fit the model's context window (" + Json.num(ev.get("limit")) + " tokens)";
            entries.add(e);
            return entries.size() - 1;
        }

        if (type.equals("workdir")) {
            String channel = Json.str(ev.get("channel"));
            Entry e = new Entry();
            e.kind = CARD; e.sub = "sys";
            e.text = "working in " + Json.str(ev.get("path")) + (channel.isEmpty() ? "" : " (" + channel + ")");
            entries.add(e);
            return entries.size() - 1;
        }

        return -1;
    }

    /** One tool call. The server sends it twice under the same id — once as it starts, once with the
        result — so the first event makes the row and the second fills it. */
    private int tool(Map<String, Object> ev) {
        String id = Json.str(ev.get("id"));
        Entry e = id.isEmpty() ? null : tools.get(id);
        if (e == null) {
            e = new Entry();
            e.kind = TOOL;
            e.id = id;
            e.who = Json.str(ev.get("agent"));
            e.sub = Json.str(ev.get("name"));
            e.title = head(e.sub, ev.get("args"));
            if (!id.isEmpty()) tools.put(id, e);
            entries.add(e);
        }
        if (ev.get("out") != null) { e.text = Json.str(ev.get("out")); e.done = true; }
        return entries.indexOf(e);
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
