package io.anzenbot.app;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Just enough JSON to read what the server sends and write what it expects.
 *
 * The server's own module is the only thing this app ever parses, so this is a reader for that shape
 * and not a general-purpose one: objects, arrays, strings, numbers, booleans and null, and nothing
 * else. {@code org.json} would do the reading but lives on Android and not on a JVM, and this is
 * deliberately a JVM class — see {@link Model} for why.
 *
 * A malformed body parses to null rather than throwing: the caller's question is always "what did
 * the server say", and a body it cannot read is the same answer as no body at all.
 */
final class Json {
    private final String s;
    private int i;

    private Json(String s) { this.s = s; }

    static Object parse(String text) {
        Json p = new Json(text == null ? "" : text);
        try {
            p.ws();
            return p.value();
        } catch (RuntimeException e) {
            return null;
        }
    }

    @SuppressWarnings("unchecked")
    static Map<String, Object> obj(String text) {
        Object v = parse(text);
        return v instanceof Map ? (Map<String, Object>) v : null;
    }

    static String str(Object o) {
        if (o == null) return "";
        return o instanceof String ? (String) o : String.valueOf(o);
    }

    static long num(Object o) { return o instanceof Number ? ((Number) o).longValue() : 0; }

    /** The same, keeping the fraction. A font size is 14.5 and a whole number would snap it to the
        wrong step on the desktop's own grid. */
    static double dbl(Object o) { return o instanceof Number ? ((Number) o).doubleValue() : 0; }

    static boolean truth(Object o) { return Boolean.TRUE.equals(o); }

    /** A JSON string literal for a value being sent, escaped so a quote or a newline in what the
        user typed cannot break out of it. */
    static String quote(String s) {
        if (s == null) return "null";
        StringBuilder b = new StringBuilder(s.length() + 2).append('"');
        for (int k = 0; k < s.length(); k++) {
            char c = s.charAt(k);
            if (c == '"' || c == '\\') b.append('\\').append(c);
            else if (c == '\n') b.append("\\n");
            else if (c == '\r') b.append("\\r");
            else if (c == '\t') b.append("\\t");
            else if (c < 0x20) b.append(String.format("\\u%04x", (int) c));
            else b.append(c);
        }
        return b.append('"').toString();
    }

    /** A value written back out — used to show a tool's arguments when no nicer line is known. */
    static String write(Object v) {
        if (v == null) return "null";
        if (v instanceof String) return quote((String) v);
        if (v instanceof Map) {
            StringBuilder b = new StringBuilder("{");
            for (Map.Entry<?, ?> e : ((Map<?, ?>) v).entrySet()) {
                if (b.length() > 1) b.append(", ");
                b.append(e.getKey()).append(": ").append(write(e.getValue()));
            }
            return b.append('}').toString();
        }
        if (v instanceof List) {
            StringBuilder b = new StringBuilder("[");
            for (Object o : (List<?>) v) {
                if (b.length() > 1) b.append(", ");
                b.append(write(o));
            }
            return b.append(']').toString();
        }
        return String.valueOf(v);
    }

    // ---- the reader --------------------------------------------------------------------------

    private void ws() { while (i < s.length() && Character.isWhitespace(s.charAt(i))) i++; }

    private Object value() {
        ws();
        if (i >= s.length()) throw new IllegalStateException("eof");
        char c = s.charAt(i);
        if (c == '{') return object();
        if (c == '[') return array();
        if (c == '"') return string();
        if (s.startsWith("true", i)) { i += 4; return Boolean.TRUE; }
        if (s.startsWith("false", i)) { i += 5; return Boolean.FALSE; }
        if (s.startsWith("null", i)) { i += 4; return null; }
        return number();
    }

    private Map<String, Object> object() {
        Map<String, Object> m = new LinkedHashMap<>();
        i++;
        ws();
        if (i < s.length() && s.charAt(i) == '}') { i++; return m; }
        while (true) {
            ws();
            String k = string();
            ws();
            if (s.charAt(i++) != ':') throw new IllegalStateException("expected :");
            m.put(k, value());
            ws();
            char c = s.charAt(i++);
            if (c == '}') return m;
            if (c != ',') throw new IllegalStateException("expected ,");
        }
    }

    private List<Object> array() {
        List<Object> a = new ArrayList<>();
        i++;
        ws();
        if (i < s.length() && s.charAt(i) == ']') { i++; return a; }
        while (true) {
            a.add(value());
            ws();
            char c = s.charAt(i++);
            if (c == ']') return a;
            if (c != ',') throw new IllegalStateException("expected ,");
        }
    }

    private String string() {
        if (s.charAt(i) != '"') throw new IllegalStateException("expected string");
        i++;
        StringBuilder b = new StringBuilder();
        while (true) {
            char c = s.charAt(i++);
            if (c == '"') return b.toString();
            if (c != '\\') { b.append(c); continue; }
            char e = s.charAt(i++);
            if (e == 'n') b.append('\n');
            else if (e == 't') b.append('\t');
            else if (e == 'r') b.append('\r');
            else if (e == 'b') b.append('\b');
            else if (e == 'f') b.append('\f');
            else if (e == 'u') { b.append((char) Integer.parseInt(s.substring(i, i + 4), 16)); i += 4; }
            else b.append(e);
        }
    }

    private Double number() {
        int start = i;
        while (i < s.length() && "+-0123456789.eE".indexOf(s.charAt(i)) >= 0) i++;
        return Double.valueOf(s.substring(start, i));
    }
}
