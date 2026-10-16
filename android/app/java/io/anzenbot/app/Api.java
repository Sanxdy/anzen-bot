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

    /** A stream's connection, handed over the moment it is open, so the caller can close it. */
    interface Open { void on(HttpURLConnection c); }

    /** A GET, returned as text. Throws with the status and body on anything but 2xx. */
    static String get(String base, String token, String path) throws IOException {
        return body(open("GET", base + path, token, false), null);
    }

    /** A POST, returned as text. {@code json} is the request body, or null for none. */
    static String post(String base, String token, String path, String json) throws IOException {
        return body(open("POST", base + path, token, false), json);
    }

    /**
     * A GET whose reply is bytes, not text — a room's logo.
     *
     * The logo lives behind the same token gate as everything else, so an {@code ImageView} pointed
     * at the URL would be refused: the header is what the server reads, and a plain image load cannot
     * carry one. Empty on any failure, which the caller draws as the monogram instead.
     */
    static byte[] getBytes(String base, String token, String path) {
        HttpURLConnection c = null;
        try {
            c = open("GET", base + path, token, false);
            if (c.getResponseCode() >= 400) return new byte[0];
            ByteArrayOutputStream b = new ByteArrayOutputStream();
            InputStream in = c.getInputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) b.write(buf, 0, n);
            return b.toByteArray();
        } catch (IOException e) {
            return new byte[0];
        } finally {
            if (c != null) c.disconnect();
        }
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

    /**
     * A GET whose reply is an event stream: {@code h.on} runs for each {@code data:} line until the
     * server closes or the socket goes quiet.
     *
     * Unlike a turn's own stream this one is expected to end: the watch is held open and re-opened
     * when it drops, so it carries a read deadline. The server's {@code : keepalive} comment arrives
     * every 15 s, well inside it, so a healthy stream never times out and a socket the wifi reaped
     * always does — which is what turns a dead stream into a reconnect instead of a thread stuck in
     * a read that will never return.
     *
     * {@code opened} is handed the live connection so the caller can close it. A reader parked in
     * {@code readLine} cannot be told to stop — the keepalives keep it fed, so it never notices — and
     * closing the socket from another thread is what makes that read throw and the loop end.
     */
    static void watch(String base, String token, String path, Event h, Open opened) throws IOException {
        HttpURLConnection c = open("GET", base + path, token, true);
        c.setReadTimeout(40000);
        if (opened != null) opened.on(c);
        try {
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
