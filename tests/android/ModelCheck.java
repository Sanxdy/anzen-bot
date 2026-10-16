package io.anzenbot.app;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * The transcript logic, run on a plain JVM against the events the server actually emits.
 *
 * Compiled against the app's own Json.java and Model.java (not copies) and run with `java`, so the
 * logic that ships is the logic that is checked. The build machine has no phone attached, and the
 * part of a chat client most likely to be quietly wrong is exactly this: which event becomes which
 * line, and which two events are one line. Kept out of the app tree so it is not dead code in the
 * APK. See tests/test_android.py.
 */
public class ModelCheck {
    static int pass = 0, fail = 0;

    static void ok(String name, boolean cond, Object got) {
        if (cond) { pass++; System.out.println("  PASS " + name); }
        else { fail++; System.out.println("  FAIL " + name + "  got: " + got); }
    }

    static void ok(String name, boolean cond) { ok(name, cond, ""); }

    static Model model() {
        Model m = new Model();
        Map<String, String> roster = new HashMap<>();
        roster.put("producer", "Producer");
        roster.put("writer", "Writer");
        m.roster(roster);
        m.chat("Producer", false);
        return m;
    }

    static Model.Entry last(Model m) { return m.entries().get(m.entries().size() - 1); }

    public static void main(String[] a) {
        json();
        loading();
        turn();
        steps();
        notes();
        words();
        System.out.println("\n" + pass + " passed, " + fail + " failed");
        if (fail > 0) System.exit(1);
    }

    // ---- reading what the server sends -------------------------------------------------------

    static void json() {
        System.out.println("Json");
        Map<String, Object> o = Json.obj("{\"type\":\"plan\",\"agent\":\"producer\",\"n\":3,\"ok\":true,\"x\":null}");
        ok("a field comes back as itself", "plan".equals(Json.str(o.get("type"))), Json.str(o.get("type")));
        ok("a number is a number", Json.num(o.get("n")) == 3, Json.num(o.get("n")));
        ok("a boolean is a boolean", Json.truth(o.get("ok")));
        ok("a null is empty text", Json.str(o.get("x")).isEmpty(), Json.str(o.get("x")));
        ok("an absent field is empty text, not a crash", Json.str(o.get("nope")).isEmpty());

        // The server escapes tool output and command lines into these strings, so escapes matter.
        Map<String, Object> e = Json.obj("{\"text\":\"a \\\"quoted\\\" line\\nsecond\\ttab \\\\ slash\"}");
        ok("an escaped quote survives", Json.str(e.get("text")).contains("\"quoted\""), Json.str(e.get("text")));
        ok("an escaped newline is a newline", Json.str(e.get("text")).contains("\n"), Json.str(e.get("text")));
        ok("an escaped tab is a tab", Json.str(e.get("text")).contains("\t"));
        ok("an escaped backslash is one backslash", Json.str(e.get("text")).contains("\\ slash"));

        Map<String, Object> u = Json.obj("{\"cmd\":\"\\u00e9\\u4e2d\"}");
        ok("a \\u escape is decoded", "\u00e9\u4e2d".equals(Json.str(u.get("cmd"))), Json.str(u.get("cmd")));

        ok("an array parses", ((List<?>) Json.obj("{\"notes\":[\"a\",\"b\"]}").get("notes")).size() == 2);
        ok("an empty object parses", Json.obj("{}") != null && Json.obj("{}").isEmpty());
        ok("an empty array parses", ((List<?>) Json.obj("{\"a\":[]}").get("a")).isEmpty());
        ok("a nested object parses",
           "x".equals(Json.str(((Map<?, ?>) Json.obj("{\"a\":{\"b\":\"x\"}}").get("a")).get("b"))));
        ok("rubbish is not a body", Json.obj("not json at all") == null);
        ok("a half-written body is not a body", Json.obj("{\"a\":") == null);
        ok("nothing is not a body", Json.obj(null) == null);

        ok("a quote in what you type is escaped",
           "\"a\\\"b\"".equals(Json.quote("a\"b")), Json.quote("a\"b"));
        ok("a newline in what you type is escaped",
           "\"a\\nb\"".equals(Json.quote("a\nb")), Json.quote("a\nb"));
        ok("a backslash in what you type is escaped",
           "\"a\\\\b\"".equals(Json.quote("a\\b")), Json.quote("a\\b"));
        ok("what you type round-trips",
           "he said \"hi\"\n\tbye \\ ok".equals(Json.str(Json.obj("{\"t\":" + Json.quote("he said \"hi\"\n\tbye \\ ok") + "}").get("t"))));
    }

    // ---- a chat opened later -----------------------------------------------------------------

    static void loading() {
        System.out.println("\nModel.load — a chat reopened");
        Model m = model();
        List<Object> msgs = new ArrayList<>();
        msgs.add(Json.obj("{\"role\":\"user\",\"content\":\"do the thing\"}"));
        msgs.add(Json.obj("{\"role\":\"assistant\",\"who\":\"producer\",\"content\":\"on it\"}"));
        msgs.add(Json.obj("{\"role\":\"assistant\",\"who\":\"writer\",\"content\":\"\"}"));   // never shown
        m.load(msgs);
        ok("the saved conversation comes back", m.entries().size() == 2, m.entries().size());
        ok("your message is yours", m.entries().get(0).kind == Model.USER);
        ok("...and reads as typed", "do the thing".equals(m.entries().get(0).text));
        ok("the reply is the bot's", m.entries().get(1).kind == Model.BOT);
        ok("...and knows which bot wrote it", "producer".equals(m.entries().get(1).who));
        ok("a bot is named, not numbered", "Producer".equals(m.name("producer")), m.name("producer"));
        ok("an unknown bot keeps its id", "ghost".equals(m.name("ghost")), m.name("ghost"));
        ok("an empty message leaves no blank bubble", m.entries().size() == 2);
        ok("a reopened chat is not mid-turn", !m.running());
        // The index Edit and Retry truncate to is the message's place in the *saved* list, so the
        // skipped empty message above must not shift it.
        ok("your message knows its place in the history", m.entries().get(0).i == 0, m.entries().get(0).i);
        ok("...and the reply knows its own", m.entries().get(1).i == 1, m.entries().get(1).i);

        // A saved reply and a saved forward come back as what they are.
        Model marks = model();
        List<Object> withMarks = new ArrayList<>();
        withMarks.add(Json.obj("{\"role\":\"user\",\"content\":\"what about the docs?\","
            + "\"quote\":{\"who\":\"Producer\",\"text\":\"ship them Friday\"}}"));
        withMarks.add(Json.obj("{\"role\":\"user\",\"content\":\"fyi\",\"fwd\":true}"));
        marks.load(withMarks);
        ok("a saved reply carries who it answers", "Producer".equals(marks.entries().get(0).qWho));
        ok("...and what they said", "ship them Friday".equals(marks.entries().get(0).qText));
        ok("a saved forward says it is one", marks.entries().get(1).fwd);
        ok("an ordinary message is neither", !marks.entries().get(0).fwd && marks.entries().get(1).qWho.isEmpty());
    }

    // ---- a turn, as it streams ----------------------------------------------------------------

    static void turn() {
        System.out.println("\nModel.apply — one turn");
        Model m = model();

        m.apply("{\"type\":\"status\",\"state\":\"working\"}");
        ok("a turn that started is running", m.running());
        ok("...and the bot's step is a card of its own", last(m).kind == Model.STEP, last(m).kind);

        int i = m.apply("{\"type\":\"plan\",\"agent\":\"producer\",\"text\":\"first I will look\"}");
        ok("a plan is a card", last(m).kind == Model.CARD && "plan".equals(last(m).sub));
        ok("...headed with whose plan it is", "Producer's plan".equals(last(m).title), last(m).title);
        ok("...and returns its own index", i == m.entries().indexOf(last(m)), i);

        m.apply("{\"type\":\"plan\",\"kind\":\"route\",\"text\":\"Writer should take this\"}");
        ok("a hand-off is titled as a hand-off", Model.ROUTE_LABEL.equals(last(m).title), last(m).title);

        m.apply("{\"type\":\"agent\",\"id\":\"writer\",\"name\":\"Writer\",\"state\":\"start\"}");
        ok("a teammate starting is a note", last(m).text.contains("Writer started"), last(m).text);
        int before = m.entries().size();
        m.apply("{\"type\":\"agent\",\"id\":\"writer\",\"name\":\"Writer\",\"state\":\"done\"}");
        ok("...and finishing is not a second one", m.entries().size() == before);

        // A tool arrives twice under one id. It must be one row, filled in, not two.
        before = m.entries().size();
        m.apply("{\"type\":\"tool\",\"id\":\"t1\",\"agent\":\"producer\",\"name\":\"run_shell\",\"args\":{\"command\":\"ls -la\"},\"out\":null}");
        ok("a tool call is one row", m.entries().size() == before + 1, m.entries().size() - before);
        Model.Entry tool = last(m);
        ok("...showing what it is doing", "$ ls -la".equals(tool.title), tool.title);
        ok("...and still running", !tool.done);
        ok("a shell call reads as a shell call", "shell".equals(Model.label("run_shell")));
        ok("an api call reads as an api call", "gmail · api".equals(Model.label("gmail_api")), Model.label("gmail_api"));

        // The clock on a running turn: seconds under a minute, then minutes and seconds.
        ok("a short wait is seconds", "0s".equals(Model.clock(0)), Model.clock(0));
        ok("...counting up", "42s".equals(Model.clock(42000)), Model.clock(42000));
        ok("a minute is minutes and seconds", "1m 05s".equals(Model.clock(65000)), Model.clock(65000));
        ok("...and the seconds are padded", "2m 03s".equals(Model.clock(123000)), Model.clock(123000));

        int again = m.apply("{\"type\":\"tool\",\"id\":\"t1\",\"agent\":\"producer\",\"name\":\"run_shell\",\"args\":{\"command\":\"ls -la\"},\"out\":\"total 0\"}");
        ok("the result fills the same row", m.entries().size() == before + 1, m.entries().size() - before);
        ok("...and points at it", again == m.entries().indexOf(tool), again);
        ok("...and the row is done", tool.done && "total 0".equals(tool.text), tool.text);

        // A reply that streams: tokens build it, then the whole text replaces them.
        m.apply("{\"type\":\"agent_text\",\"agent\":\"producer\",\"text\":\"Hel\",\"delta\":true}");
        m.apply("{\"type\":\"agent_text\",\"agent\":\"producer\",\"text\":\"lo\",\"delta\":true}");
        ok("tokens build one reply", "Hello".equals(last(m).text), last(m).text);
        ok("...and it is a reply, not a card", last(m).kind == Model.BOT);
        int at = m.apply("{\"type\":\"agent_text\",\"agent\":\"producer\",\"text\":\"Hello there\"}");
        ok("the whole text replaces the tokens, not appends", "Hello there".equals(last(m).text), last(m).text);
        ok("...on the same row", at == m.entries().size() - 1, at);

        // A reply that came back empty must leave nothing behind.
        before = m.entries().size();
        m.apply("{\"type\":\"agent_text\",\"agent\":\"writer\",\"text\":\"x\",\"delta\":true}");
        m.apply("{\"type\":\"agent_text\",\"agent\":\"writer\",\"text\":\"   \"}");
        ok("a reply that came back empty is dropped", m.entries().size() == before, m.entries().size() - before);

        m.apply("{\"type\":\"approval\",\"agent\":\"producer\",\"cmd\":\"rm -rf build\"}");
        ok("an approval is its own card", last(m).kind == Model.APPROVAL);
        ok("...with the command on it", "rm -rf build".equals(last(m).text));
        ok("...named for the bot asking", "Producer".equals(m.name(last(m).who)));

        m.apply("{\"type\":\"steer\",\"text\":\"also check the tests\"}");
        ok("a steer you sent reads as your own message", last(m).kind == Model.USER && "also check the tests".equals(last(m).text));

        m.apply("{\"type\":\"final\",\"text\":\"all done\"}");
        ok("a report is a card", last(m).kind == Model.CARD && "final".equals(last(m).sub));
        ok("...titled for the bot in a direct chat", "Producer · report".equals(last(m).title), last(m).title);

        m.apply("{\"type\":\"error\",\"msg\":\"the model call timed out\"}");
        ok("a failure says so instead of stopping silently",
           "error".equals(last(m).sub) && last(m).text.contains("timed out"), last(m).text);

        m.apply("{\"type\":\"learned\",\"agent\":\"writer\",\"notes\":[\"the build is slow\",\"tests are green\"]}");
        ok("what a bot learned is a note",
           last(m).text.equals("learned from Writer: the build is slow · tests are green"), last(m).text);

        m.apply("{\"type\":\"context\",\"dropped\":1,\"limit\":32000}");
        ok("a compression note reads in the singular", last(m).text.contains("1 earlier step to fit"), last(m).text);
        m.apply("{\"type\":\"context\",\"dropped\":4,\"limit\":32000}");
        ok("...and in the plural", last(m).text.contains("4 earlier steps to fit"), last(m).text);

        m.apply("{\"type\":\"workdir\",\"path\":\"/tmp/proj\",\"channel\":\"Studio\"}");
        ok("a work folder note names the folder and the room",
           last(m).text.equals("working in /tmp/proj (Studio)"), last(m).text);

        m.apply("{\"type\":\"shot\",\"png\":\"data:image/png;base64,AAAA\",\"note\":\"a login page\"}");
        ok("a screenshot is an image entry", last(m).kind == Model.IMAGE && last(m).png.startsWith("data:image/png"));
        ok("...with its caption", "a login page".equals(last(m).note));

        // Events the phone does not draw must not become blank rows.
        before = m.entries().size();
        m.apply("{\"type\":\"ctx\",\"ctx\":{\"used\":10}}");
        m.apply("{\"type\":\"something-new\",\"x\":1}");
        m.apply("not json");
        ok("an event with nothing to draw draws nothing", m.entries().size() == before, m.entries().size() - before);

        m.apply("{\"type\":\"done\"}");
        ok("the turn ended", !m.running());

        // A room names its summary for the room, not for whichever member wrote it.
        Model room = model();
        room.chat("Studio", true);
        room.apply("{\"type\":\"final\",\"agent\":\"producer\",\"text\":\"the room's answer\"}");
        ok("a room's report is titled for the room", "Room · summary".equals(last(room).title), last(room).title);

        // Your own message is on screen the moment you send it.
        Model own = model();
        int idx = own.addUser("hello there", "", "", false);
        ok("your message lands immediately", idx == 0 && own.entries().size() == 1);
        ok("...as your own", own.entries().get(0).kind == Model.USER && "hello there".equals(own.entries().get(0).text));
        ok("...with no history index of its own yet", own.entries().get(0).i == -1, own.entries().get(0).i);

        // A reply carries what it answers, and a forward says it is one.
        Model quoted = model();
        quoted.addUser("what about the docs?", "Producer", "ship them Friday", false);
        Model.Entry q = quoted.entries().get(0);
        ok("a reply carries who it answers", "Producer".equals(q.qWho) && "ship them Friday".equals(q.qText),
           q.qWho + "/" + q.qText);
        quoted.addUser("fyi", "", "", true);
        ok("a forward says it is one", quoted.entries().get(1).fwd);

        // A steer may itself be a reply, and the event carries the quote.
        Model steered = model();
        steered.apply("{\"type\":\"steer\",\"text\":\"and the tests?\","
                    + "\"quote\":{\"who\":\"Producer\",\"text\":\"ship Friday\"}}");
        Model.Entry st = last(steered);
        ok("a steered reply keeps its quote",
           st.kind == Model.USER && "Producer".equals(st.qWho) && "ship Friday".equals(st.qText),
           st.qWho + "/" + st.qText);

        // The tool head lines the web app uses, so the two clients say the same thing.
        ok("a delegate names the role and the task",
           "→ writer: write the docs".equals(Model.head("delegate", Json.obj("{\"role\":\"writer\",\"task\":\"write the docs\"}"))),
           Model.head("delegate", Json.obj("{\"role\":\"writer\",\"task\":\"write the docs\"}")));
        ok("an unknown tool falls back to its arguments",
           Model.head("mystery", Json.obj("{\"a\":1}")).contains("a: 1"),
           Model.head("mystery", Json.obj("{\"a\":1}")));
        ok("a long head line is cut to fit",
           Model.head("mystery", Json.obj("{\"a\":" + Json.quote(repeat('x', 400)) + "}")).length() <= 200);
    }

    // ---- the step card: what a bot is doing, and for how long ---------------------------------

    static void steps() {
        System.out.println("\nModel.apply — the step card");
        Model m = model();
        m.apply("{\"type\":\"status\",\"state\":\"thinking\",\"agent\":\"producer\"}");
        Model.Entry s = last(m);
        ok("a phase is a step card", s.kind == Model.STEP, s.kind);
        ok("...naming the phase", "thinking".equals(s.sub), s.sub);
        ok("...with its clock running", s.live(), s.since);
        ok("...headed with the count and the phase", "Step 1 · Thinking…".equals(Model.stepTitle(s, false)),
           Model.stepTitle(s, false));

        m.apply("{\"type\":\"status\",\"state\":\"thinking\",\"agent\":\"producer\"}");
        ok("the same phase said again is not a second step", m.entries().size() == 1 && s.steps == 1, s.steps);

        m.apply("{\"type\":\"status\",\"state\":\"working\",\"agent\":\"producer\"}");
        ok("a new phase counts up", s.steps == 2, s.steps);
        ok("...and is the card's label", "Step 2 · Working…".equals(Model.stepTitle(s, false)),
           Model.stepTitle(s, false));
        ok("...and the log keeps every phase", s.text.equals("1. Thinking…\n2. Working…"), s.text);
        ok("...on the same row, not a new one", m.entries().size() == 1, m.entries().size());

        ok("past the deadline the label admits the wait",
           "Step 2 · Still working…".equals(Model.stepTitle(s, true)), Model.stepTitle(s, true));

        // Two bots in a room work at once, so each gets its own card rather than one that flips.
        m.apply("{\"type\":\"status\",\"state\":\"working\",\"agent\":\"writer\"}");
        ok("another bot's step is its own card", m.entries().size() == 2, m.entries().size());
        ok("...named for that bot", "writer".equals(last(m).who), last(m).who);

        m.apply("{\"type\":\"done\"}");
        ok("the turn ending closes every step", s.done && last(m).done);
        ok("...and stops their clocks", !s.live() && !last(m).live());
        ok("...and the chat is no longer running", !m.running());
    }

    // ---- the notes this app writes about stopping a bot ---------------------------------------

    static void notes() {
        System.out.println("\nModel.apply — notices, and the context chip");
        Model m = model();
        int before = m.entries().size();
        m.apply("{\"type\":\"notice\",\"level\":\"warn\",\"text\":\"Producer was denied that command.\"}");
        ok("a notice is a row of its own", m.entries().size() == before + 1);
        ok("...with what happened on it", last(m).text.contains("denied"), last(m).text);
        ok("...and its level kept", "warn".equals(last(m).level), last(m).level);
        ok("...so a turn that stopped says why", last(m).kind == Model.NOTICE);

        m.apply("{\"type\":\"notice\",\"level\":\"warn\",\"text\":\"\"}");
        ok("an empty notice leaves no blank row", m.entries().size() == before + 1, m.entries().size() - before);

        ok("no measurement means an empty chip", m.ctxPct() == 0, m.ctxPct());
        m.apply("{\"type\":\"ctx\",\"ctx\":{\"tokens\":8000,\"limit\":32000,\"rows\":[{\"label\":\"Messages\",\"tokens\":8000}]}}");
        ok("the chip reads the turn's own measurement", m.ctxPct() == 25, m.ctxPct());
        ok("...and keeps the breakdown behind it", m.ctx() != null && m.ctx().get("rows") != null);
        m.apply("{\"type\":\"done\"}");
        ok("...without becoming a row", m.entries().size() == before + 1, m.entries().size() - before);

        // What /api/history says about the chat itself — the three chips, before a turn is run.
        Model h = model();
        h.meta("gpt-5", "ask", Json.obj("{\"tokens\":1000,\"limit\":4000}"));
        ok("the chat's model is known on open", "gpt-5".equals(h.model()), h.model());
        ok("...and its approval level", "ask".equals(h.approval()), h.approval());
        ok("...and how full its window is", h.ctxPct() == 25, h.ctxPct());
        h.clear();
        ok("opening another chat forgets the last one's chips", h.model().isEmpty() && h.ctxPct() == 0);
    }

    // ---- the saved conversation, and the words -------------------------------------------------

    static void words() {
        System.out.println("\nModel.load — what a reopened chat keeps");
        Model m = model();
        List<Object> msgs = new ArrayList<>();
        msgs.add(Json.obj("{\"role\":\"user\",\"content\":\"do the thing\",\"ts\":1700000000}"));
        msgs.add(Json.obj("{\"role\":\"assistant\",\"who\":\"Producer\",\"content\":\"on it\",\"ts\":1700000060}"));
        // The work a bot did is saved, so reopening shows the commands and what they printed.
        msgs.add(Json.obj("{\"role\":\"tool\",\"agent\":\"producer\",\"name\":\"run_shell\","
                        + "\"args\":{\"command\":\"ls -la\"},\"out\":\"total 0\",\"ts\":1700000120}"));
        msgs.add(Json.obj("{\"role\":\"route\",\"who\":\"Room\",\"content\":\"Writer should take this\"}"));
        // A stop this app caused is the account of what happened, and it is saved for the same reason.
        msgs.add(Json.obj("{\"role\":\"notice\",\"content\":\"Producer was denied that command.\"}"));
        m.load(msgs);
        ok("the saved conversation comes back", m.entries().size() == 5, m.entries().size());
        ok("a message keeps when it was said", m.entries().get(0).ts == 1700000000000L, m.entries().get(0).ts);
        ok("the work a bot did is kept", m.entries().get(2).kind == Model.TOOL, m.entries().get(2).kind);
        ok("...with its command line", "$ ls -la".equals(m.entries().get(2).title), m.entries().get(2).title);
        ok("...and its output", "total 0".equals(m.entries().get(2).text), m.entries().get(2).text);
        ok("...already finished, not left running", m.entries().get(2).done && !m.entries().get(2).live());
        ok("a hand-off is kept as a hand-off", Model.ROUTE_LABEL.equals(m.entries().get(3).title));
        ok("a stop note is kept as a note", m.entries().get(4).kind == Model.NOTICE);
        ok("a reopened chat is not mid-turn", !m.running());

        System.out.println("\nModel — the words the two clients share");
        ok("a live turn says it is working", "working".equals(Model.stateLabel("working")), Model.stateLabel("working"));
        ok("...not that it is at the desk", !Model.stateLabel("working").contains("desk"));
        ok("a finished turn says done", "done".equals(Model.stateLabel("finished")), Model.stateLabel("finished"));
        ok("a waiting turn says what it waits for",
           "needs your approval".equals(Model.stateLabel("approval")), Model.stateLabel("approval"));
        ok("an idle chat says idle", "idle".equals(Model.stateLabel("idle")), Model.stateLabel("idle"));
        ok("idle is not a step", Model.stepLabel("idle") == null);
        ok("a step is named in the desktop's words", "Working…".equals(Model.stepLabel("working")));
        ok("a monogram takes the first letters", "PS".equals(Model.initials("Producer Smith")), Model.initials("Producer Smith"));
        ok("...splitting a camel-case name", "ZW".equals(Model.initials("ZenWriter")), Model.initials("ZenWriter"));
        ok("...and two letters of a short one", "PR".equals(Model.initials("Producer")), Model.initials("Producer"));
        ok("no name still gets a monogram", "?".equals(Model.initials("")));
        /* Locale-following on purpose: en-US stamps "10:57 PM" and a 24-hour locale "22:57", which is
           what the desktop's own `toLocaleTimeString` does. So the check is the shape, not the digits. */
        String stamped = Model.stamp(1700000000000L);
        ok("a time is stamped", stamped.indexOf(':') > 0 && stamped.length() >= 5, stamped);
        ok("nothing said has no stamp", Model.stamp(0).isEmpty());
        ok("a chat that just moved says now", "now".equals(Model.ago(System.currentTimeMillis())), Model.ago(System.currentTimeMillis()));
        ok("...and an old one in weeks", "2w".equals(Model.ago((System.currentTimeMillis() / 1000 - 1209600) * 1000)), Model.ago((System.currentTimeMillis() / 1000 - 1209600) * 1000));
    }

    static String repeat(char c, int n) {
        char[] out = new char[n];
        Arrays.fill(out, c);
        return new String(out);
    }
}