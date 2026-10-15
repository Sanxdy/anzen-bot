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
    }

    // ---- a turn, as it streams ----------------------------------------------------------------

    static void turn() {
        System.out.println("\nModel.apply — one turn");
        Model m = model();

        m.apply("{\"type\":\"status\",\"state\":\"working\"}");
        ok("a turn that started is running", m.running());

        int i = m.apply("{\"type\":\"plan\",\"agent\":\"producer\",\"text\":\"first I will look\"}");
        ok("a plan is a card", last(m).kind == Model.CARD && "plan".equals(last(m).sub));
        ok("...headed with whose plan it is", "Producer's plan".equals(last(m).title), last(m).title);
        ok("...and returns its own index", i == 0, i);

        m.apply("{\"type\":\"plan\",\"kind\":\"route\",\"text\":\"Writer should take this\"}");
        ok("a hand-off is not titled like a plan", "Handing off".equals(last(m).title), last(m).title);

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
        int idx = own.addUser("hello there");
        ok("your message lands immediately", idx == 0 && own.entries().size() == 1);
        ok("...as your own", own.entries().get(0).kind == Model.USER && "hello there".equals(own.entries().get(0).text));

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

    static String repeat(char c, int n) {
        char[] out = new char[n];
        Arrays.fill(out, c);
        return new String(out);
    }
}
