package io.anzenbot.app;

/**
 * The address-and-token parsing, run on a plain JVM.
 *
 * Compiled against the app's own Targets.java (not a copy) and run with `java`, so the logic that
 * actually ships is the logic that is checked. Kept out of the app tree so it is not dead code in
 * the APK. See tests/test_android.py.
 */
public class TargetsCheck {
    static int pass = 0, fail = 0;

    static void ok(String name, boolean cond, Object got) {
        if (cond) { pass++; System.out.println("  PASS " + name); }
        else { fail++; System.out.println("  FAIL " + name + "  " + got); }
    }

    static void ok(String name, boolean cond) { ok(name, cond, ""); }

    public static void main(String[] a) {
        // The whole printed line from the terminal is the thing people copy, prefix and all.
        String[] p = Targets.split("Phone or tablet: http://192.168.1.20:8093/?t=TOK3n", "");
        ok("the whole printed line gives up its address", p[0].equals("http://192.168.1.20:8093"), p[0]);
        ok("...and its token", p[1].equals("TOK3n"), p[1]);
        ok("that address is worth trying", Targets.reachable(p[0]), p[0]);

        // A bare address is what most people type.
        p = Targets.split("192.168.1.20:8093", "TOK");
        ok("a bare address gets a scheme", p[0].equals("http://192.168.1.20:8093"), p[0]);
        ok("a bare address keeps the token typed beside it", p[1].equals("TOK"), p[1]);
        ok("localhost works the same way", Targets.split("localhost:8093/", "T")[0].equals("http://localhost:8093"),
           Targets.split("localhost:8093/", "T")[0]);
        ok("an https address is left alone",
           Targets.split("https://anzen.local:8443", "")[0].equals("https://anzen.local:8443"));
        ok("the token typed in the second box wins over nothing in the first",
           Targets.split("http://h:8093", "SEP")[1].equals("SEP"));

        // Nonsense must be refused before anything is pointed at it.
        ok("an empty box is not an address", !Targets.reachable(Targets.split("", "")[0]));
        ok("whitespace is not an address", !Targets.reachable(Targets.split("   ", "")[0]));
        ok("prose is not an address", !Targets.reachable(Targets.split("hello world", "")[0]));
        ok("a scheme with no host is not an address", !Targets.reachable("http://"), "http://");
        ok("a port that is not a number is caught here, not on the network",
           !Targets.reachable("http://h:abc"), "http://h:abc");
        ok("a real port is fine", Targets.reachable("http://h:8093"), "http://h:8093");
        ok("a portless host is fine", Targets.reachable("http://h"), "http://h");

        // The token goes into a query, so it is percent-encoded rather than trusted.
        ok("a plain token is unchanged", Targets.encode("abc-123_X").equals("abc-123_X"));
        ok("a token with a slash or space is encoded",
           Targets.encode("a/b c").equals("a%2Fb%20c"), Targets.encode("a/b c"));

        // ---- the door: is the desktop app there? ------------------------------------------
        // A real HTTP server on the loopback, because the question the app asks on every launch is
        // answered by the network, not by string handling. `live()` returns a sentence to show when
        // the desktop app is not there, and null when it is.
        try {
            com.sun.net.httpserver.HttpServer srv = server();
            ok("a desktop app that answers is live", Targets.live(base(srv), "TOK") == null,
               Targets.live(base(srv), "TOK"));
            ok("...and it was asked for the token, which is what the desktop app checks",
               seenToken.length() > 0, seenToken);
            ok("...on the door the app answers before the workspace is needed",
               seenPath.equals("/api/lan"), seenPath);
            ok("a desktop app that refuses this phone is not live, and says why",
               Targets.live(base(srv), "WRONG").contains("not paired"),
               Targets.live(base(srv), "WRONG"));
            ok("a reply that is not Anzen-bot at all is not live",
               Targets.live(base(srv), "NOTAPP").contains("not Anzen-bot"),
               Targets.live(base(srv), "NOTAPP"));
            ok("an error from the app is reported as one",
               Targets.live(base(srv), "BOOM").contains("(500)"),
               Targets.live(base(srv), "BOOM"));
            srv.stop(0);
        } catch (Exception e) { ok("the door checks ran", false, e); }

        ok("nothing listening is not live, and says the app is not running",
           Targets.live(baseClosed(), "TOK").contains("not running"),
           Targets.live(baseClosed(), "TOK"));
        ok("an unpaired phone has nothing to check", Targets.live("", "TOK").contains("Not set up"),
           Targets.live("", "TOK"));

        System.out.println("\n" + pass + " passed, " + fail + " failed");
        System.exit(fail == 0 ? 0 : 1);
    }

    // ---- the little server the door is checked against --------------------------------------

    private static volatile String seenToken = "", seenPath = "";

    private static String base(com.sun.net.httpserver.HttpServer srv) {
        return "http://127.0.0.1:" + srv.getAddress().getPort();
    }

    /** A port with nothing on it: what the phone finds when the desktop app is closed. */
    private static String baseClosed() {
        try {
            java.net.ServerSocket s = new java.net.ServerSocket(0);
            int p = s.getLocalPort(); s.close();
            return "http://127.0.0.1:" + p;
        } catch (Exception e) { return "http://127.0.0.1:1"; }
    }

    /** Stands in for the desktop app's door: `/api/lan`, behind the token, answered by the token. */
    private static com.sun.net.httpserver.HttpServer server() throws Exception {
        com.sun.net.httpserver.HttpServer srv =
            com.sun.net.httpserver.HttpServer.create(new java.net.InetSocketAddress("127.0.0.1", 0), 0);
        srv.createContext("/api/lan", new com.sun.net.httpserver.HttpHandler() {
            public void handle(com.sun.net.httpserver.HttpExchange x) throws java.io.IOException {
                seenPath = x.getRequestURI().getPath();
                seenToken = x.getRequestHeaders().getFirst("X-Anzen-Token");
                String tok = seenToken == null ? "" : seenToken;
                String body; int code;
                if ("WRONG".equals(tok)) { code = 403; body = "forbidden"; }
                else if ("BOOM".equals(tok)) { code = 500; body = "boom"; }
                else if ("NOTAPP".equals(tok)) { code = 200; body = "{\"hello\":1}"; }
                else { code = 200; body = "{\"enabled\":true,\"host\":\"192.168.1.20\",\"port\":8093}"; }
                byte[] b = body.getBytes("UTF-8");
                x.sendResponseHeaders(code, b.length);
                x.getResponseBody().write(b); x.close();
            }
        });
        srv.start();
        return srv;
    }
}
