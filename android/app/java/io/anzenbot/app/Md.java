package io.anzenbot.app;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * The markdown a bot answers in, parsed into something the phone can draw.
 *
 * A port of the desktop renderer (app.js mdToHtml/inlineMd) with no android.* on the classpath, so
 * the parsing — the half most likely to be quietly wrong, since a reply showing literal asterisks
 * reads as the bot's fault — is checked on a plain JVM by MdCheck. Md parses, ChatView draws.
 */
public final class Md {

  /** Block kinds. */
  public static final int P = 0, H = 1, UL = 2, OL = 3, QUOTE = 4, CODE = 5, HR = 6, TABLE = 7;

  /** One block of the reply. `text` is the block's raw text: for CODE the body without the fence;
      for TABLE the rows joined by "\n" with cells separated by "\t"; for UL/OL the items joined by
      "\n" with the marker stripped; for HR "". `level` is the heading depth 1..6 for H, the start
      number for OL, 0 otherwise. `lang` is the fence's info string for CODE, else "". */
  public static final class Blk {
    public final int kind, level;
    public final String text, lang;

    public Blk(int kind, int level, String text, String lang) {
      this.kind = kind; this.level = level; this.text = text; this.lang = lang;
    }
  }

  /** Inline formatting inside one line. kind: 0 plain, 1 bold, 2 italic, 3 strike, 4 code, 5 link.
      For a link `text` is the label and `href` the URL, already vetted by safeHref. */
  public static final class Seg {
    public final int kind;
    public final String text, href;

    public Seg(int kind, String text, String href) {
      this.kind = kind; this.text = text; this.href = href;
    }
  }

  // ---- the patterns, one per rule in app.js --------------------------------------------------

  private static final Pattern FENCE = Pattern.compile("^\\s*(```|~~~)\\s*([\\w+-]*)\\s*$");
  private static final Pattern FENCE_ANY = Pattern.compile("^\\s*(```|~~~)");
  private static final Pattern SEP = Pattern.compile("^\\s*\\|?\\s*:?-{2,}:?\\s*(\\|\\s*:?-{2,}:?\\s*)*\\|?\\s*$");
  private static final Pattern HEADING = Pattern.compile("^(#{1,6})\\s+(.*)$");
  private static final Pattern HEADING_ANY = Pattern.compile("^#{1,6}\\s+");
  private static final Pattern HR_RULE = Pattern.compile("^\\s*([-*_])\\s*(\\1\\s*){2,}$");
  private static final Pattern QUOTE_MARK = Pattern.compile("^\\s*>\\s?");
  private static final Pattern BULLET = Pattern.compile("^\\s*([-*+]|\\d+[.)])\\s+");
  private static final Pattern BULLET_STRIP = Pattern.compile("^\\s*(?:[-*+]|\\d+[.)])\\s+");
  private static final Pattern ORDERED = Pattern.compile("^\\s*\\d+[.)]\\s+");
  private static final Pattern NUM = Pattern.compile("^\\s*(\\d+)[.)]\\s+");
  private static final Pattern CONT = Pattern.compile("^\\s+\\S");

  private static final Pattern CODE_SPAN = Pattern.compile("`([^`]+)`");
  private static final Pattern BOLD = Pattern.compile("\\*\\*([^*]+)\\*\\*");
  private static final Pattern STRIKE = Pattern.compile("~~([^~]+)~~");
  private static final Pattern ITALIC_STAR = Pattern.compile("(^|[^*\\w])\\*([^*\\n]+)\\*");
  private static final Pattern ITALIC_UND = Pattern.compile("(^|[^_\\w])_([^_\\n]+)_(?![\\w])");
  private static final Pattern LINK = Pattern.compile("\\[([^\\]]*)\\]\\(([^)\\s]*)\\)");
  private static final Pattern SAFE = Pattern.compile("(https?:|mailto:|/|#)", Pattern.CASE_INSENSITIVE);
  /** A bare URL in text that has already been escaped — here, plain text, so `&` is allowed as itself
      and the class only has to stop at whitespace and the characters a URL cannot hold. */
  private static final Pattern BARE_URL = Pattern.compile("(^|[\\s(>])(https?://[^\\s<>\"']*)");
  /** A lifted span sits in the line as \uE000<index>\uE001 until the line is cut into segments. */
  private static final Pattern PH = Pattern.compile("\uE000(\\d+)\uE001");

  // ---- blocks --------------------------------------------------------------------------------

  /** Cuts a reply into blocks. See mdToHtml, app.js:259. */
  public static List<Blk> blocks(String text) {
    List<Blk> out = new ArrayList<>();
    String[] lines = (text == null ? "" : text).replace("\r\n", "\n").replace("\r", "\n").split("\n", -1);
    int i = 0;
    while (i < lines.length) {
      String line = lines[i];
      Matcher f = FENCE.matcher(line);
      if (f.matches()) {                                            // fenced code block
        Pattern close = Pattern.compile("^\\s*" + Pattern.quote(f.group(1)) + "\\s*$");
        List<String> body = new ArrayList<>();
        i++;
        while (i < lines.length && !close.matcher(lines[i]).matches()) { body.add(lines[i]); i++; }
        i++;                                                        // the closing fence, or off the end
        out.add(new Blk(CODE, 0, join("\n", body), f.group(2)));
        continue;
      }
      if (line.indexOf('|') >= 0 && i + 1 < lines.length && SEP.matcher(lines[i + 1]).matches()) {
        List<String> rows = new ArrayList<>();                      // table: header, then body rows
        rows.add(join("\t", row(line)));
        i += 2;
        while (i < lines.length && lines[i].indexOf('|') >= 0 && !lines[i].trim().isEmpty()) {
          rows.add(join("\t", row(lines[i]))); i++;
        }
        out.add(new Blk(TABLE, 0, join("\n", rows), ""));
        continue;
      }
      Matcher h = HEADING.matcher(line);
      if (h.matches()) { out.add(new Blk(H, h.group(1).length(), h.group(2), "")); i++; continue; }
      if (HR_RULE.matcher(line).matches()) { out.add(new Blk(HR, 0, "", "")); i++; continue; }
      if (QUOTE_MARK.matcher(line).lookingAt()) {                   // consecutive quotes are one block
        List<String> q = new ArrayList<>();
        while (i < lines.length && QUOTE_MARK.matcher(lines[i]).lookingAt()) {
          q.add(QUOTE_MARK.matcher(lines[i]).replaceFirst("")); i++;
        }
        out.add(new Blk(QUOTE, 0, join("\n", q), ""));
        continue;
      }
      if (BULLET.matcher(line).lookingAt()) {                       // consecutive bullets are one list
        boolean ordered = ORDERED.matcher(line).lookingAt();
        List<String> items = new ArrayList<>();
        int level = ordered ? num(line) : 0;
        while (i < lines.length && BULLET.matcher(lines[i]).lookingAt()) {
          String it = BULLET_STRIP.matcher(lines[i]).replaceFirst(""); i++;
          while (i < lines.length && CONT.matcher(lines[i]).lookingAt() && !BULLET.matcher(lines[i]).lookingAt()) {
            it += " " + lines[i].trim(); i++;                       // a wrapped line belongs to its item
          }
          items.add(it);
        }
        out.add(new Blk(ordered ? OL : UL, level, join("\n", items), ""));
        continue;
      }
      if (line.trim().isEmpty()) { i++; continue; }
      List<String> para = new ArrayList<>();                        // paragraph; a newline is a line break
      while (i < lines.length && !lines[i].trim().isEmpty()
          && !FENCE_ANY.matcher(lines[i]).lookingAt() && !QUOTE_MARK.matcher(lines[i]).lookingAt()
          && !HEADING_ANY.matcher(lines[i]).lookingAt() && !BULLET.matcher(lines[i]).lookingAt()
          && !(lines[i].indexOf('|') >= 0 && i + 1 < lines.length && SEP.matcher(lines[i + 1]).matches())) {
        para.add(lines[i]); i++;
      }
      out.add(new Blk(P, 0, join("\n", para), ""));
    }
    return out;
  }

  /** One table row's cells: one leading and one trailing `|` dropped, each cell trimmed. */
  private static List<String> row(String s) {
    String t = s.trim();
    if (t.startsWith("|")) t = t.substring(1);
    if (t.endsWith("|")) t = t.substring(0, t.length() - 1);
    List<String> cells = new ArrayList<>();
    for (String c : t.split("\\|", -1)) cells.add(c.trim());
    return cells;
  }

  private static int num(String line) {
    Matcher m = NUM.matcher(line);
    return m.lookingAt() ? Integer.parseInt(m.group(1)) : 0;
  }

  // ---- inline --------------------------------------------------------------------------------

  /** Cuts one line into formatted spans. See inlineMd, app.js:248. */
  public static List<Seg> segs(String line) {
    List<Seg> lifted = new ArrayList<>();
    String s = line == null ? "" : line;
    s = lift(s, CODE_SPAN, lifted, 4);      // code spans first, so a `*` inside one stays literal
    s = lift(s, BOLD, lifted, 1);
    s = lift(s, STRIKE, lifted, 3);
    s = lift(s, ITALIC_STAR, lifted, 2);
    s = lift(s, ITALIC_UND, lifted, 2);
    s = links(s, lifted);
    s = bareLinks(s, lifted);
    return scan(s, lifted);
  }

  /** A person's own message: no markdown at all — a shell command with an asterisk must not come back
      italic — but a URL they typed is still a URL, and a URL you cannot tap is the one thing plain
      text gets wrong. See `linkify`, app.js:275. */
  public static List<Seg> literal(String line) {
    List<Seg> lifted = new ArrayList<>();
    return scan(bareLinks(line == null ? "" : line, lifted), lifted);
  }

  /** Every match becomes a lifted span; a pattern with a leading group keeps that group literal. */
  private static String lift(String s, Pattern p, List<Seg> lifted, int kind) {
    Matcher m = p.matcher(s);
    StringBuffer sb = new StringBuffer();
    while (m.find()) {
      String head = m.groupCount() > 1 ? m.group(1) : "";
      lifted.add(new Seg(kind, m.group(m.groupCount()), ""));
      m.appendReplacement(sb, Matcher.quoteReplacement(head + ph(lifted.size() - 1)));
    }
    m.appendTail(sb);
    return sb.toString();
  }

  private static String links(String s, List<Seg> lifted) {
    Matcher m = LINK.matcher(s);
    StringBuffer sb = new StringBuffer();
    while (m.find()) {
      String label = m.group(1), url = m.group(2);
      lifted.add(new Seg(5, label.isEmpty() ? url : label, safeHref(url)));
      m.appendReplacement(sb, Matcher.quoteReplacement(ph(lifted.size() - 1)));
    }
    m.appendTail(sb);
    return sb.toString();
  }

  private static String safeHref(String u) { return SAFE.matcher(u).lookingAt() ? u : "#"; }

  /** Link bare http(s) URLs without swallowing sentence punctuation. Markdown links were lifted first,
      so this cannot make a second link inside one that already has a label and href. */
  private static String bareLinks(String s, List<Seg> lifted) {
    Matcher m = BARE_URL.matcher(s);
    StringBuffer sb = new StringBuffer();
    while (m.find()) {
      String raw = m.group(2), url = raw.replaceFirst("[.,;:!?]+$", "");
      while (url.endsWith(")") && count(url, ')') > count(url, '(')) url = url.substring(0, url.length() - 1);
      lifted.add(new Seg(5, url, safeHref(url)));
      m.appendReplacement(sb, Matcher.quoteReplacement(m.group(1) + ph(lifted.size() - 1) + raw.substring(url.length())));
    }
    m.appendTail(sb);
    return sb.toString();
  }

  private static int count(String s, char c) {
    int n = 0; for (int i = 0; i < s.length(); i++) if (s.charAt(i) == c) n++; return n;
  }

  /** Cuts the line at each lifted span, coalescing the plain text between them into one span. */
  private static List<Seg> scan(String s, List<Seg> lifted) {
    List<Seg> out = new ArrayList<>();
    Matcher m = PH.matcher(s);
    int at = 0;
    while (m.find()) {
      if (m.start() > at) out.add(new Seg(0, s.substring(at, m.start()), ""));
      Seg g = lifted.get(Integer.parseInt(m.group(1)));
      out.add(new Seg(g.kind, resolve(g.text, lifted), g.href));
      at = m.end();
    }
    if (at < s.length()) out.add(new Seg(0, s.substring(at), ""));
    return out;
  }

  // ponytail: Seg is flat, so a span nested inside another (`**bold \`code\`**`) keeps the outer
  // styling and drops the inner one. Nest when a renderer actually needs it.
  private static String resolve(String text, List<Seg> lifted) {
    if (text.indexOf('\uE000') < 0) return text;
    Matcher m = PH.matcher(text);
    StringBuffer sb = new StringBuffer();
    while (m.find()) {
      m.appendReplacement(sb, Matcher.quoteReplacement(resolve(lifted.get(Integer.parseInt(m.group(1))).text, lifted)));
    }
    m.appendTail(sb);
    return sb.toString();
  }

  private static String ph(int i) { return "\uE000" + i + "\uE001"; }

  /** String.join is API 26; this app runs on 24. Same reason Model.java has its own. */
  private static String join(String sep, List<String> parts) {
    StringBuilder b = new StringBuilder();
    for (int i = 0; i < parts.size(); i++) {
      if (i > 0) b.append(sep);
      b.append(parts.get(i));
    }
    return b.toString();
  }
}
