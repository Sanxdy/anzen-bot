package io.anzenbot.app;

/**
 * What the user typed, turned into a server address — and whether the app behind it is there.
 *
 * Deliberately free of Android so it can be run and checked on a plain JVM (tests/test_android.py):
 * the address and the token are the one part of this app where a wrong guess strands the user, and
 * the machine that builds the APK has no phone attached to catch that.
 */
final class Targets {
    private Targets() { }

    /**
     * Split a typed address and token. A pasted line is usually the whole printed link — the terminal
     * prints `Phone or tablet: http://192.168.1.10:8093/?t=…` — so anything before the URL is dropped
     * and the token is lifted out of the query, rather than asking the user to separate them by hand.
     */
    static String[] split(String raw, String token) {
        raw = raw == null ? "" : raw.trim();
        token = token == null ? "" : token.trim();
        int h = raw.indexOf("http://"), hs = raw.indexOf("https://");
        int cut = h < 0 ? hs : (hs < 0 ? h : Math.min(h, hs));
        if (cut > 0) raw = raw.substring(cut);
        int t = raw.indexOf("?t=");
        if (t >= 0) { token = raw.substring(t + 3).trim(); raw = raw.substring(0, t); }
        int q = raw.indexOf('?');
        if (q >= 0) raw = raw.substring(0, q);
        while (raw.endsWith("/")) raw = raw.substring(0, raw.length() - 1);
        if (!raw.isEmpty() && !raw.startsWith("http://") && !raw.startsWith("https://")) raw = "http://" + raw;
        return new String[]{raw, token};
    }

    /** A scheme, a host and a numeric port, and nothing else, makes an address worth trying; the rest
     *  only fails later, on the network, where the message is less use to the user. */
    static boolean reachable(String url) {
        return url != null && url.matches("^https?://[^/?#\\s:@]+(:\\d{1,5})?(/\\S*)?$");
    }

    /**
     * Is the desktop app there — and if not, what should the phone say about it? Null when it is up.
     *
     * The app is a client for the server running on the computer, so it has nothing to show on its
     * own: with that app closed there is no server, no chats and no bots, and the honest thing is to
     * say so rather than open onto a blank screen. `/api/lan` is the one call that answers without
     * needing the workspace, and it is behind the token, so a 200 also proves this phone is paired.
     * A 403 is worth telling apart from silence: the app is running and the token is wrong.
     *
     * Plain `java.net`, no Android, so the whole thing runs on a JVM and is checked by
     * tests/test_android.py — the machine that builds the APK has no phone attached to catch this.
     */
    static String live(String url, String token) {
        if (url == null || url.isEmpty()) return "Not set up yet.";
        java.net.HttpURLConnection c = null;
        try {
            c = (java.net.HttpURLConnection) new java.net.URL(url + "/api/lan").openConnection();
            c.setConnectTimeout(4000);                 // a phone on the wrong wifi waits, then gives up
            c.setReadTimeout(4000);
            c.setRequestProperty("X-Anzen-Token", token == null ? "" : token);
            c.setRequestProperty("User-Agent", "AnzenBot/1.0");
            int code = c.getResponseCode();
            if (code == 200) {
                return read(c.getInputStream()).contains("\"enabled\"") ? null
                     : "Something answered at " + url + ", but it is not Anzen-bot.";
            }
            if (code == 403) return "Anzen-bot is running, but this phone is not paired with it — "
                                  + "check the access token.";
            // 503 is the relay answering for a desktop that is not dialled in: the address is right
            // and the relay is up, but there is nothing behind it. Same thing to the user.
            if (code == 503) return "Anzen-bot is not running on your computer.";
            return "Anzen-bot answered with an error (" + code + ").";
        } catch (Exception e) {
            return "Anzen-bot is not running on your computer.";   // refused, timed out, or no route
        } finally {
            if (c != null) c.disconnect();
        }
    }

    private static String read(java.io.InputStream in) {
        StringBuilder b = new StringBuilder();
        try (java.io.InputStream i = in) {
            byte[] buf = new byte[4096];
            int n;
            while ((n = i.read(buf)) > 0 && b.length() < 65536) b.append(new String(buf, 0, n, "UTF-8"));
        } catch (Exception ignored) { }
        return b.toString();
    }

    static String encode(String s) {
        StringBuilder b = new StringBuilder();
        for (byte c : s.getBytes(java.nio.charset.StandardCharsets.UTF_8)) {
            char ch = (char) (c & 0xFF);
            if ((ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9')
                    || ch == '-' || ch == '_' || ch == '.' || ch == '~') b.append(ch);
            else b.append(String.format("%%%02X", c & 0xFF));
        }
        return b.toString();
    }
}
