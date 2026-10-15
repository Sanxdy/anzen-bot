package io.anzenbot.app;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * The phone's one way to talk to the desktop app — plain {@code java.net}, with no Android in it.
 *
 * Kept free of Android for the same reason {@link Targets} is: the machine that builds the APK has
 * no phone attached, so the parts that can be wrong are the parts a JVM can check by itself.
 *
 * Every call carries the token as {@code X-Anzen-Token}, set once when the companion is paired. The
 * app never keeps the cookie that pairing earned: the server reads the header directly, so there is
 * no cookie jar to hold in step with the desktop and nothing to expire. A native client has no
 * business carrying a browser's cookie anyway.
 *
 * Every method here blocks on the network. Callers run them off the main thread.
 */
final class Api {
    private Api() { }

    /** An event as it arrives: {@code json} is one {@code data:} payload, already unwrapped. */
    interface Event { void on(String json); }

    /** A GET, returned as text. Throws with the status and body on anything but 2xx. */
    static String get(String base, String token, String path) throws IOException {
        return body(open("GET", base + path, token, false), null);
    }

    /** A POST, returned as text. {@code json} is the request body, or null for none. */
    static String post(String base, String token, String path, String json) throws IOException {
        return body(open("POST", base + path, token, false), json);
    }

    /**
     * A POST whose reply is an event stream: {@code h.on} runs for each {@code data:} line until the
     * turn ends and the server closes. The {@code : keepalive} comments and blank lines are dropped,
     * so the caller only ever sees real events. There is deliberately no read deadline — a turn is as
     * long as it is, and an approval card can sit unanswered for minutes.
     */
    static void stream(String base, String token, String path, String json, Event h) throws IOException {
        HttpURLConnection c = open("POST", base + path, token, true);
        c.setReadTimeout(0);
        try {
            write(c, json);
            BufferedReader r = new BufferedReader(new InputStreamReader(c.getInputStream(), StandardCharsets.UTF_8));
            String line;
            while ((line = r.readLine()) != null) {
                if (line.startsWith("data:")) h.on(line.substring(5).trim());
            }
        } finally {
            c.disconnect();
        }
    }

    // ---- the plumbing --------------------------------------------------------------------------

    private static HttpURLConnection open(String method, String url, String token, boolean sse) throws IOException {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setRequestMethod(method);
        c.setConnectTimeout(8000);
        c.setReadTimeout(sse ? 0 : 20000);      // a stream has no deadline; a plain call must not hang
        c.setInstanceFollowRedirects(false);
        c.setRequestProperty("X-Anzen-Token", token == null ? "" : token);
        c.setRequestProperty("User-Agent", "AnzenBot/1.0");
        if (sse) c.setRequestProperty("Accept", "text/event-stream");
        return c;
    }

    private static void write(HttpURLConnection c, String json) throws IOException {
        if (json == null) return;
        c.setDoOutput(true);
        c.setRequestProperty("Content-Type", "application/json");
        byte[] out = json.getBytes(StandardCharsets.UTF_8);
        c.setFixedLengthStreamingMode(out.length);
        OutputStream os = c.getOutputStream();
        try { os.write(out); } finally { os.close(); }
    }

    private static String body(HttpURLConnection c, String json) throws IOException {
        try {
            write(c, json);
            int code = c.getResponseCode();
            InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
            String text = read(in);
            if (code >= 400) throw new IOException("HTTP " + code + (text.isEmpty() ? "" : ": " + text));
            return text;
        } finally {
            c.disconnect();
        }
    }

    private static String read(InputStream in) throws IOException {
        if (in == null) return "";
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) > 0) b.write(buf, 0, n);
        return new String(b.toByteArray(), StandardCharsets.UTF_8);
    }
}
