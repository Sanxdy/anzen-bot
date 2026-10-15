package io.anzenbot.app;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Typeface;
import android.os.Handler;
import android.os.Looper;
import android.text.SpannableStringBuilder;
import android.text.Spanned;
import android.text.style.StyleSpan;
import android.text.style.TypefaceSpan;
import android.util.Base64;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.EditorInfo;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * The chat, drawn natively — no WebView, no page, no HTML.
 *
 * Three screens live here: the list of conversations, the bots you can start one with, and one
 * conversation. Everything is a plain Android view built in code, because the whole app is built in
 * code — there is no layout XML in this project and no Gradle to run one through.
 *
 * The turn is the interesting part. `POST /api/chat` answers with a stream of small events, and
 * {@link Model} folds each into the transcript; this class draws whichever entry changed and leaves
 * the rest of the screen alone, so a reply that arrives a token at a time grows in place instead of
 * rebuilding the conversation under your thumb.
 */
final class ChatView extends LinearLayout {
    private static final int LIST = 0, PICK = 1, CHAT = 2;

    private final Model model = new Model();
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final List<View> rows = new ArrayList<>();       // one per entry, so a change redraws one
    private final Map<String, String> botNames = new HashMap<>();

    private String base = "", token = "", sid = "";
    private boolean started;
    private int gen;   // which chat is on screen; a reply that arrives for an older one is dropped

    private long turnStart;          // ms the turn on screen began; 0 when none is running
    private String chatTitle = "";   // the chat's own name, shown under the clock while it runs
    private final Runnable tick = new Runnable() {
        @Override public void run() {
            if (turnStart == 0) return;
            if (chatScreen.getVisibility() == View.VISIBLE) {
                title.setText(chatTitle + " · " + Model.clock(System.currentTimeMillis() - turnStart));
            }
            ui.postDelayed(this, 1000);
        }
    };

    private final FrameLayout body;
    private final ScrollView listScreen, pickScreen;
    private final LinearLayout listCol, pickCol, chatScreen, txCol;
    private final ScrollView txScroll;
    private final TextView title, action, empty;
    private EditText input;
    private Button send;

    ChatView(Context c) {
        super(c);
        setOrientation(VERTICAL);
        setBackgroundColor(Pal.BG);

        // ---- the top bar: where you are, and the one thing you can do from here ----
        LinearLayout bar = new LinearLayout(c);
        bar.setOrientation(HORIZONTAL);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setBackgroundColor(Pal.CARD);
        bar.setPadding(dp(4), dp(6), dp(10), dp(6));

        TextView back = new TextView(c);
        back.setText("‹");
        back.setTextColor(Pal.FG);
        back.setTextSize(28);
        back.setGravity(Gravity.CENTER);
        back.setPadding(dp(12), 0, dp(12), 0);
        back.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { back(); }
        });
        bar.addView(back, new LayoutParams(-2, -2));

        title = new TextView(c);
        title.setTextColor(Pal.FG);
        title.setTextSize(17);
        title.setSingleLine(true);
        title.setEllipsize(android.text.TextUtils.TruncateAt.END);
        bar.addView(title, new LayoutParams(0, -2, 1f));

        action = new TextView(c);
        action.setTextColor(Pal.ACCENT);
        action.setTextSize(15);
        action.setGravity(Gravity.CENTER);
        action.setPadding(dp(12), dp(6), dp(12), dp(6));
        action.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) {
                if (body.getChildAt(0).getVisibility() == View.VISIBLE) { pick(); }
            }
        });
        bar.addView(action, new LayoutParams(-2, -2));
        addView(bar, new LayoutParams(-1, -2));

        // ---- the three screens ----
        body = new FrameLayout(c);
        addView(body, new LayoutParams(-1, 0, 1f));

        listCol = column(c);
        listScreen = scroll(c, listCol);
        body.addView(listScreen, new FrameLayout.LayoutParams(-1, -1));

        pickCol = column(c);
        pickScreen = scroll(c, pickCol);
        pickScreen.setVisibility(GONE);
        body.addView(pickScreen, new FrameLayout.LayoutParams(-1, -1));

        chatScreen = new LinearLayout(c);
        chatScreen.setOrientation(VERTICAL);
        chatScreen.setVisibility(GONE);
        txCol = column(c);
        txScroll = scroll(c, txCol);
        chatScreen.addView(txScroll, new LayoutParams(-1, 0, 1f));
        chatScreen.addView(composer(c), new LayoutParams(-1, -2));
        body.addView(chatScreen, new FrameLayout.LayoutParams(-1, -1));

        empty = new TextView(c);
        empty.setTextColor(Pal.DIM);
        empty.setTextSize(14);
        empty.setGravity(Gravity.CENTER);
        empty.setPadding(dp(32), dp(60), dp(32), 0);

        showList();
    }

    // ---- what the host calls -----------------------------------------------------------------

    /** The door opened. Load the bots' names and the conversation list, once per address. */
    void start(String url, String tok) {
        if (started && url.equals(base) && tok.equals(token)) return;
        base = url; token = tok; started = true;
        loadRoster();
        loadList();
    }

    /** The hardware back button. True when it was used up here rather than leaving the app. */
    boolean back() {
        if (chatScreen.getVisibility() == View.VISIBLE) { showList(); return true; }
        if (pickScreen.getVisibility() == View.VISIBLE) { showList(); return true; }
        return false;
    }

    // ---- the list ----------------------------------------------------------------------------

    private void showList() {
        stopClock();
        body.getChildAt(0).setVisibility(VISIBLE);
        listScreen.setVisibility(VISIBLE);
        pickScreen.setVisibility(GONE);
        chatScreen.setVisibility(GONE);
        title.setText("Chats");
        action.setText("＋");
        if (started) loadList();   // the chat you just had has moved to the top of the list
    }

    private void loadRoster() {
        new Thread(new Runnable() {
            @Override public void run() {
                try {
                    Map<String, Object> cfg = Json.obj(Api.get(base, token, "/api/config"));
                    final Map<String, String> names = new HashMap<>();
                    names.putAll(names(cfg, "bots"));
                    names.putAll(names(cfg, "channels"));
                    ui.post(new Runnable() {
                        @Override public void run() {
                            botNames.clear(); botNames.putAll(names);
                            model.roster(names);
                        }
                    });
                } catch (IOException ignored) {
                    // A roster is a nicety: the list still works, it just says "producer".
                }
            }
        }).start();
    }

    private static Map<String, String> names(Map<String, Object> cfg, String key) {
        Map<String, String> out = new HashMap<>();
        if (cfg == null || !(cfg.get(key) instanceof List)) return out;
        for (Object o : (List<?>) cfg.get(key)) {
            if (!(o instanceof Map)) continue;
            Map<?, ?> m = (Map<?, ?>) o;
            String id = Json.str(m.get("id")), name = Json.str(m.get("name"));
            if (!id.isEmpty()) out.put(id, name.isEmpty() ? id : name);
        }
        return out;
    }

    private void loadList() {
        new Thread(new Runnable() {
            @Override public void run() {
                try {
                    final Map<String, Object> r = Json.obj(Api.get(base, token, "/api/chats"));
                    ui.post(new Runnable() {
                        @Override public void run() { renderList(r); }
                    });
                } catch (IOException e) {
                    ui.post(new Runnable() {
                        @Override public void run() { note("Could not reach your computer."); }
                    });
                }
            }
        }).start();
    }

    private void renderList(Map<String, Object> r) {
        if (chatScreen.getVisibility() == View.VISIBLE) return;   // a reload must not pull you out
        listCol.removeAllViews();
        List<?> chats = r != null && r.get("chats") instanceof List ? (List<?>) r.get("chats") : Collections.emptyList();
        if (chats.isEmpty()) {
            empty.setText("Nothing here yet.\n\nStart a chat with ＋ — your bots are on the computer.");
            listCol.addView(empty);
            return;
        }
        for (Object o : chats) {
            if (!(o instanceof Map)) continue;
            final Map<?, ?> c = (Map<?, ?>) o;
            final String id = Json.str(c.get("id"));
            LinearLayout row = new LinearLayout(getContext());
            row.setOrientation(VERTICAL);
            row.setBackgroundColor(Pal.CARD);
            row.setPadding(dp(14), dp(12), dp(14), dp(12));

            TextView name = text(Json.str(c.get("name")), Pal.FG, 16);
            row.addView(name);
            TextView last = text(Json.str(c.get("last")), Pal.DIM, 13);
            last.setSingleLine(true);
            last.setEllipsize(android.text.TextUtils.TruncateAt.END);
            last.setPadding(0, dp(3), 0, 0);
            row.addView(last);
            TextView meta = text(Json.str(c.get("kind")) + " · " + Json.num(c.get("count")) + " messages",
                    Pal.FAINT, 11);
            meta.setPadding(0, dp(5), 0, 0);
            row.addView(meta);

            row.setOnClickListener(new OnClickListener() {
                @Override public void onClick(View v) { open(id, Json.str(c.get("name")), "room".equals(Json.str(c.get("kind")))); }
            });
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
            lp.setMargins(dp(10), dp(5), dp(10), dp(5));
            listCol.addView(row, lp);
        }
    }

    // ---- starting a chat ---------------------------------------------------------------------

    private void pick() {
        stopClock();
        body.getChildAt(0).setVisibility(VISIBLE);
        listScreen.setVisibility(GONE);
        chatScreen.setVisibility(GONE);
        pickScreen.setVisibility(VISIBLE);
        title.setText("New chat");
        action.setText("");
        pickCol.removeAllViews();

        if (botNames.isEmpty()) {
            TextView t = text("Still reading your bots…", Pal.DIM, 14);
            t.setPadding(dp(14), dp(20), 0, 0);
            pickCol.addView(t);
            return;
        }
        List<String> ids = new ArrayList<>(botNames.keySet());
        Collections.sort(ids);
        for (final String id : ids) {
            LinearLayout row = new LinearLayout(getContext());
            row.setOrientation(VERTICAL);
            row.setBackgroundColor(Pal.CARD);
            row.setPadding(dp(14), dp(14), dp(14), dp(14));
            row.addView(text(botNames.get(id), Pal.FG, 16));
            row.setOnClickListener(new OnClickListener() {
                @Override public void onClick(View v) { open(id, botNames.get(id), false); }
            });
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
            lp.setMargins(dp(10), dp(5), dp(10), dp(5));
            pickCol.addView(row, lp);
        }
    }

    // ---- one conversation --------------------------------------------------------------------

    private void open(String id, String name, boolean isRoom) {
        sid = id;
        final int g = ++gen;
        model.chat(name, isRoom);
        model.clear();
        rows.clear();
        txCol.removeAllViews();
        chatTitle = name.isEmpty() ? id : name;
        stopClock();
        title.setText(chatTitle);
        action.setText("");
        listScreen.setVisibility(GONE);
        pickScreen.setVisibility(GONE);
        chatScreen.setVisibility(VISIBLE);
        setRunning(false);

        new Thread(new Runnable() {
            @Override public void run() {
                try {
                    final Map<String, Object> h = Json.obj(Api.get(base, token, "/api/history?session=" + Targets.encode(sid)));
                    ui.post(new Runnable() {
                        @Override public void run() { if (g == gen) render(h); }
                    });
                } catch (IOException e) {
                    ui.post(new Runnable() {
                        @Override public void run() { note("Could not open that chat."); }
                    });
                }
            }
        }).start();
    }

    private void render(Map<String, Object> h) {
        model.load(h != null && h.get("messages") instanceof List ? (List<Object>) h.get("messages") : null);
        rebuild();
    }

    private void rebuild() {
        txCol.removeAllViews();
        rows.clear();
        for (Model.Entry e : model.entries()) {
            View v = build(e);
            rows.add(v);
            txCol.addView(v);
        }
        down();
    }

    /** Redraw just the entry that changed. If the transcript changed shape — a reply that came back
        empty is dropped — every index after it moved, so the whole thing is rebuilt instead. */
    private void paint(int i) {
        if (model.entries().size() != rows.size()) { rebuild(); return; }
        if (i < 0 || i >= model.entries().size()) return;
        View v = build(model.entries().get(i));
        if (i < rows.size()) {
            View old = rows.get(i);
            int at = txCol.indexOfChild(old);
            txCol.removeViewAt(at);
            txCol.addView(v, at);
            rows.set(i, v);
        } else {
            rows.add(v);
            txCol.addView(v);
            down();
        }
    }

    private void down() {
        txScroll.post(new Runnable() {
            @Override public void run() { txScroll.fullScroll(View.FOCUS_DOWN); }
        });
    }

    // ---- the composer ------------------------------------------------------------------------

    private View composer(Context c) {
        LinearLayout bar = new LinearLayout(c);
        bar.setOrientation(HORIZONTAL);
        bar.setGravity(Gravity.BOTTOM);
        bar.setBackgroundColor(Pal.CARD);
        bar.setPadding(dp(10), dp(8), dp(10), dp(8));

        input = new EditText(c);
        input.setHint("Message");
        input.setHintTextColor(Pal.FAINT);
        input.setTextColor(Pal.FG);
        input.setTextSize(15);
        input.setBackgroundColor(Pal.BG);
        input.setPadding(dp(12), dp(10), dp(12), dp(10));
        input.setMaxLines(5);
        input.setImeOptions(EditorInfo.IME_ACTION_SEND);
        input.setOnEditorActionListener(new TextView.OnEditorActionListener() {
            @Override public boolean onEditorAction(TextView v, int actionId, android.view.KeyEvent ev) {
                if (actionId == EditorInfo.IME_ACTION_SEND) { send(); return true; }
                return false;
            }
        });
        bar.addView(input, new LayoutParams(0, -2, 1f));

        send = new Button(c);
        send.setText("Send");
        send.setTextColor(0xFFFFFFFF);
        send.setBackgroundColor(Pal.ACCENT);
        send.setOnClickListener(new OnClickListener() {
            @Override public void onClick(View v) { send(); }
        });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-2, -2);
        lp.leftMargin = dp(8);
        bar.addView(send, lp);
        return bar;
    }

    private void setSend(boolean steering) {
        send.setText(steering ? "Steer" : "Send");
        send.setBackgroundColor(steering ? Pal.WARN : Pal.ACCENT);
    }

    /** A turn is under way: put a clock beside the chat's name, so a long job reads as a long job
        rather than a screen that has stopped answering. */
    private void startClock() {
        if (turnStart != 0 || chatScreen.getVisibility() != View.VISIBLE) return;
        turnStart = System.currentTimeMillis();
        ui.post(tick);
    }

    /** The turn is over, or you left the chat: the title goes back to just the name. */
    private void stopClock() {
        if (turnStart == 0) return;
        turnStart = 0;
        ui.removeCallbacks(tick);
        if (chatScreen.getVisibility() == View.VISIBLE) title.setText(chatTitle);
    }

    /** A turn running is two things at once: the button says Send or Steer, and the clock runs. */
    private void setRunning(boolean on) {
        setSend(on);
        if (on) startClock(); else stopClock();
    }

    /** Send what is typed. Mid-turn it is a steer — the bot picks it up at its next step instead of
        waiting for this turn to end, which is the whole point of steering. */
    private void send() {
        final String text = input.getText().toString().trim();
        if (text.isEmpty()) return;
        input.setText("");
        if (model.running()) steer(text);
        else chat(text);
    }

    private void chat(final String text) {
        final String turn = String.valueOf(System.currentTimeMillis());
        // A turn outlives the screen it was started from: you can send a message and walk back to
        // the list while the bot is still working. The stream keeps running, and `g` is what stops
        // its events landing in whatever chat you opened next.
        final String session = sid;
        final int g = gen;
        paint(model.addUser(text));
        setRunning(true);   // the clock starts on the tap, not on the first event to come back
        new Thread(new Runnable() {
            @Override public void run() {
                String body = "{\"session\":" + Json.quote(session) + ",\"text\":" + Json.quote(text)
                            + ",\"turn\":" + Json.quote(turn) + "}";
                try {
                    Api.stream(base, token, "/api/chat", body, new Api.Event() {
                        @Override public void on(final String json) {
                            ui.post(new Runnable() {
                                @Override public void run() { if (g == gen) landed(json); }
                            });
                        }
                    });
                } catch (IOException e) {
                    ui.post(new Runnable() {
                        @Override public void run() {
                            if (g == gen) note("Lost contact with your computer.");
                        }
                    });
                } finally {
                    ui.post(new Runnable() {
                        @Override public void run() { if (g == gen) setRunning(model.running()); }
                    });
                }
            }
        }).start();
    }

    private void steer(final String text) {
        final String session = sid;
        final int g = gen;
        new Thread(new Runnable() {
            @Override public void run() {
                String body = "{\"session\":" + Json.quote(session) + ",\"text\":" + Json.quote(text) + "}";
                try {
                    Map<String, Object> r = Json.obj(Api.post(base, token, "/api/chat/steer", body));
                    // No turn to steer means the turn ended between the tap and the request, and the
                    // message would otherwise be dropped — so it runs as the next turn instead.
                    if (r == null || !Json.truth(r.get("running"))) {
                        ui.post(new Runnable() {
                            @Override public void run() { if (g == gen) chat(text); }
                        });
                    }
                } catch (IOException e) {
                    ui.post(new Runnable() {
                        @Override public void run() {
                            if (g == gen) note("Lost contact with your computer.");
                        }
                    });
                }
            }
        }).start();
    }

    private void landed(String json) {
        int i = model.apply(json);
        if (model.entries().size() != rows.size()) rebuild();
        else if (i >= 0) paint(i);
        setRunning(model.running());
    }

    private void approve(final Model.Entry e, final boolean allow) {
        final int at = model.entries().indexOf(e);
        final String session = sid;
        e.done = true;
        e.allowed = allow;
        if (at >= 0) paint(at);
        new Thread(new Runnable() {
            @Override public void run() {
                try {
                    Api.post(base, token, "/api/approve",
                             "{\"session\":" + Json.quote(session) + ",\"allow\":" + allow + "}");
                } catch (IOException ex) {
                    ui.post(new Runnable() {
                        @Override public void run() { note("Could not answer the request."); }
                    });
                }
            }
        }).start();
    }

    // ---- drawing one entry -------------------------------------------------------------------

    private View build(Model.Entry e) {
        switch (e.kind) {
            case Model.USER: return user(e);
            case Model.BOT: return bot(e);
            case Model.TOOL: return tool(e);
            case Model.APPROVAL: return approval(e);
            case Model.IMAGE: return image(e);
            default: return card(e);
        }
    }

    private View user(Model.Entry e) {
        LinearLayout wrap = new LinearLayout(getContext());
        wrap.setOrientation(VERTICAL);
        wrap.setGravity(Gravity.END);
        wrap.setPadding(dp(40), dp(5), dp(10), dp(5));
        TextView b = new TextView(getContext());
        b.setText(e.text);
        b.setTextColor(Pal.FG);
        b.setTextSize(15);
        b.setBackgroundColor(Pal.USER);
        b.setPadding(dp(12), dp(10), dp(12), dp(10));
        b.setTextIsSelectable(true);
        wrap.addView(b);
        return wrap;
    }

    private View bot(Model.Entry e) {
        LinearLayout wrap = new LinearLayout(getContext());
        wrap.setOrientation(VERTICAL);
        wrap.setPadding(dp(10), dp(5), dp(40), dp(5));
        String who = model.name(e.who);
        if (!who.isEmpty()) {
            TextView h = text(who, Pal.ACCENT, 12);
            h.setPadding(dp(2), 0, 0, dp(4));
            wrap.addView(h);
        }
        View body = prose(e.text, Pal.CARD);
        wrap.addView(body);
        return wrap;
    }

    private View card(Model.Entry e) {
        LinearLayout box = new LinearLayout(getContext());
        box.setOrientation(VERTICAL);
        box.setBackgroundColor(Pal.CARD);
        box.setPadding(dp(12), dp(10), dp(12), dp(10));

        String head = e.title;
        int headColour = Pal.DIM;
        if ("plan".equals(e.sub)) headColour = Pal.ACCENT;
        else if ("final".equals(e.sub)) headColour = Pal.FG;
        else if ("error".equals(e.sub)) headColour = Pal.ERR;
        if (head != null && !head.isEmpty()) {
            TextView h = text(head, headColour, 12);
            h.setPadding(0, 0, 0, dp(5));
            box.addView(h);
        }
        TextView t = new TextView(getContext());
        t.setText(e.text);
        t.setTextColor("error".equals(e.sub) ? Pal.ERR : ("sys".equals(e.sub) ? Pal.DIM : Pal.FG));
        t.setTextSize("sys".equals(e.sub) ? 13 : 14);
        t.setTextIsSelectable(true);
        box.addView(t);

        return inset(box);
    }

    private View tool(Model.Entry e) {
        LinearLayout box = new LinearLayout(getContext());
        box.setOrientation(VERTICAL);
        box.setBackgroundColor(Pal.CARD);
        box.setPadding(dp(12), dp(10), dp(12), dp(10));

        box.addView(text(model.name(e.who) + " · " + Model.label(e.sub), Pal.DIM, 12));
        TextView head = mono(e.title, Pal.FG, 13);
        head.setPadding(0, dp(5), 0, 0);
        head.setTextIsSelectable(true);
        box.addView(head);
        TextView state = text(e.done ? "done" : "running…", e.done ? Pal.FAINT : Pal.WARN, 11);
        state.setPadding(0, dp(5), 0, 0);
        box.addView(state);
        if (e.done && !e.text.isEmpty()) {
            String out = e.text.length() > 1500 ? e.text.substring(0, 1500) + "…" : e.text;
            TextView pre = mono(out, Pal.DIM, 11);
            pre.setPadding(0, dp(6), 0, 0);
            pre.setTextIsSelectable(true);
            box.addView(pre);
        }
        return inset(box);
    }

    private View approval(final Model.Entry e) {
        LinearLayout box = new LinearLayout(getContext());
        box.setOrientation(VERTICAL);
        box.setBackgroundColor(Pal.CARD);
        box.setPadding(dp(12), dp(10), dp(12), dp(10));

        String who = model.name(e.who);
        box.addView(text((who.isEmpty() ? "The bot" : who) + " wants to run a command", Pal.WARN, 13));
        TextView cmd = mono(e.text, Pal.FG, 13);
        cmd.setPadding(0, dp(6), 0, 0);
        cmd.setTextIsSelectable(true);
        box.addView(cmd);

        if (e.done) {
            TextView r = text(e.allowed ? "Allowed" : "Denied", e.allowed ? Pal.ACCENT : Pal.ERR, 13);
            r.setPadding(0, dp(8), 0, 0);
            box.addView(r);
        } else {
            LinearLayout row = new LinearLayout(getContext());
            row.setOrientation(HORIZONTAL);
            row.setPadding(0, dp(10), 0, 0);
            Button allow = new Button(getContext());
            allow.setText("Allow");
            allow.setTextColor(0xFFFFFFFF);
            allow.setBackgroundColor(Pal.ACCENT);
            allow.setOnClickListener(new OnClickListener() {
                @Override public void onClick(View v) { approve(e, true); }
            });
            Button deny = new Button(getContext());
            deny.setText("Deny");
            deny.setTextColor(Pal.FG);
            deny.setBackgroundColor(Pal.LINE);
            LinearLayout.LayoutParams dlp = new LinearLayout.LayoutParams(-2, -2);
            dlp.leftMargin = dp(8);
            deny.setOnClickListener(new OnClickListener() {
                @Override public void onClick(View v) { approve(e, false); }
            });
            row.addView(allow);
            row.addView(deny, dlp);
            box.addView(row);
        }
        return inset(box);
    }

    private View image(Model.Entry e) {
        LinearLayout box = new LinearLayout(getContext());
        box.setOrientation(VERTICAL);
        box.setBackgroundColor(Pal.CARD);
        box.setPadding(dp(12), dp(10), dp(12), dp(10));
        box.addView(text(e.sub, Pal.DIM, 12));
        Bitmap bm = decode(e.png);
        if (bm != null) {
            ImageView iv = new ImageView(getContext());
            iv.setImageBitmap(bm);
            iv.setAdjustViewBounds(true);
            iv.setPadding(0, dp(6), 0, 0);
            box.addView(iv);
        }
        if (!e.note.isEmpty()) {
            TextView n = text(e.note, Pal.FAINT, 12);
            n.setPadding(0, dp(6), 0, 0);
            box.addView(n);
        }
        return inset(box);
    }

    private View inset(View v) {
        LinearLayout wrap = new LinearLayout(getContext());
        wrap.setOrientation(VERTICAL);
        wrap.setPadding(dp(10), dp(5), dp(10), dp(5));
        wrap.addView(v, new LayoutParams(-1, -2));
        return wrap;
    }

    /**
     * A bot writes markdown. A phone cannot render all of it, but two things are worth the code:
     * a fenced block is shown as code rather than as three backticks and a wall of text, and
     * {@code **bold**} and {@code `code`} inside a sentence are shown as themselves.
     */
    private View prose(String text, int bg) {
        LinearLayout col = new LinearLayout(getContext());
        col.setOrientation(VERTICAL);
        col.setBackgroundColor(bg);
        col.setPadding(dp(12), dp(10), dp(12), dp(10));

        int at = 0;
        while (true) {
            int open = text.indexOf("```", at);
            if (open < 0) { col.addView(inline(text.substring(at), Pal.FG, 15)); break; }
            String before = text.substring(at, open).trim();
            if (!before.isEmpty()) col.addView(inline(before, Pal.FG, 15));
            int close = text.indexOf("```", open + 3);
            String code = close < 0 ? text.substring(open + 3) : text.substring(open + 3, close);
            int nl = code.indexOf('\n');
            if (nl >= 0 && !code.substring(0, nl).contains(" ")) code = code.substring(nl + 1);  // drop "java"
            TextView pre = mono(code.trim(), Pal.FG, 12);
            pre.setBackgroundColor(Pal.BG);
            pre.setPadding(dp(10), dp(8), dp(10), dp(8));
            pre.setTextIsSelectable(true);
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
            lp.topMargin = dp(6); lp.bottomMargin = dp(6);
            col.addView(pre, lp);
            if (close < 0) break;
            at = close + 3;
        }
        return col;
    }

    private TextView inline(String text, int colour, float sp) {
        TextView t = new TextView(getContext());
        SpannableStringBuilder b = new SpannableStringBuilder(text);
        span(b, text, "**", new StyleSpan(Typeface.BOLD));
        span(b, text, "`", new TypefaceSpan("monospace"));
        t.setText(b);
        t.setTextColor(colour);
        t.setTextSize(sp);
        t.setTextIsSelectable(true);
        return t;
    }

    /** Mark one pair of delimiters as a span. Unpaired delimiters are left as the literal text the
        writer typed, which is what someone who wrote a lone asterisk meant. */
    private static void span(SpannableStringBuilder b, String text, String mark, Object style) {
        int at = 0;
        while (true) {
            int open = text.indexOf(mark, at);
            if (open < 0) return;
            int close = text.indexOf(mark, open + mark.length());
            if (close < 0) return;
            b.setSpan(style, open, close + mark.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
            at = close + mark.length();
        }
    }

    private static Bitmap decode(String dataUrl) {
        int comma = dataUrl.indexOf(',');
        if (comma < 0) return null;
        try {
            byte[] raw = Base64.decode(dataUrl.substring(comma + 1), Base64.DEFAULT);
            return BitmapFactory.decodeByteArray(raw, 0, raw.length);
        } catch (Exception e) {
            return null;
        }
    }

    // ---- small things ------------------------------------------------------------------------

    private LinearLayout column(Context c) {
        LinearLayout col = new LinearLayout(c);
        col.setOrientation(VERTICAL);
        col.setPadding(0, dp(6), 0, dp(20));
        return col;
    }

    private ScrollView scroll(Context c, View inner) {
        ScrollView s = new ScrollView(c);
        s.setBackgroundColor(Pal.BG);
        s.addView(inner, new ViewGroup.LayoutParams(-1, -2));
        return s;
    }

    private TextView text(String s, int colour, float sp) {
        TextView t = new TextView(getContext());
        t.setText(s == null ? "" : s);
        t.setTextColor(colour);
        t.setTextSize(sp);
        return t;
    }

    private TextView mono(String s, int colour, float sp) {
        TextView t = text(s, colour, sp);
        t.setTypeface(Typeface.MONOSPACE);
        return t;
    }

    private void note(String msg) {
        Toast.makeText(getContext(), msg, Toast.LENGTH_LONG).show();
    }

    private int dp(int n) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, n, getResources().getDisplayMetrics());
    }
}
