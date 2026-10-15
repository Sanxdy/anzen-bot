package io.anzenbot.app;

import android.app.Activity;
import android.content.Context;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

/**
 * The Anzen-bot app: a native client for the server running on your computer.
 *
 * Nothing here is a browser. There is no WebView and no page: the conversation is drawn by
 * {@link ChatView} out of Android views, and the only thing that crosses the network is JSON to the
 * desktop app's own API — the same API the desktop window uses, over the same token.
 *
 * What this file owns is the door. The phone is bound to the desktop app: with that app closed there
 * is no server, no chats and no bots, so every launch — and every time the phone comes back to the
 * front, and once in a while while it is being used — the phone asks the computer whether it is
 * there. If it is not, the workspace comes off the screen and is replaced by the reason, and the
 * phone keeps looking on its own, so starting the app on the computer is all it takes to get back
 * in. Nothing is thrown away while that happens: the chat you were in is still in memory behind the
 * message, so it is exactly where you left it when the computer comes back.
 */
public class MainActivity extends Activity {
    private static final String PREFS = "anzen";
    private static final int BG = Pal.BG, FG = Pal.FG, DIM = Pal.DIM, ACCENT = Pal.ACCENT;
    private static final long RETRY_MS = 3000;      // how often a blocked app looks again
    private static final long KEEPALIVE_MS = 10000; // how often a live one checks it still is

    private SharedPreferences prefs;
    private FrameLayout root;
    private ScrollView setup, offline;
    private ChatView chat;
    private EditText urlField, tokenField;
    private TextView status, offlineTitle, offlineMsg, offlineAddr;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private boolean checking = false;    // one probe at a time: a retry must not stack up behind it
    private boolean live = false;        // the desktop app answered, so a probe must not blank the screen

    private final Runnable retry = new Runnable() {
        @Override public void run() { check(); }
    };
    private final Runnable keepAlive = new Runnable() {
        @Override public void run() { check(); }
    };

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        prefs = getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        root = new FrameLayout(this);
        root.setBackgroundColor(BG);
        chat = new ChatView(this);
        setup = buildSetup();
        offline = buildOffline();
        root.addView(chat, new FrameLayout.LayoutParams(-1, -1));
        root.addView(setup, new FrameLayout.LayoutParams(-1, -1));
        root.addView(offline, new FrameLayout.LayoutParams(-1, -1));
        setContentView(root);

        if (prefs.getString("url", "").isEmpty()) showSetup("Not set up yet.");
        else check();
    }

    @Override protected void onResume() {
        super.onResume();
        // Coming back to the phone is exactly when the computer may have gone away, so the door is
        // checked again — unless the user is on the setup screen, where there is nothing to check yet.
        if (setup.getVisibility() != View.VISIBLE) check();
    }

    // ---- the door: is the desktop app there? -------------------------------------------------

    /** Ask the computer whether it is there, off the main thread, and open the workspace only if it
        answers. The reply is a sentence to show when it is not, or null when it is. */
    private void check() {
        final String url = prefs.getString("url", ""), token = prefs.getString("token", "");
        if (url.isEmpty()) { showSetup("Not set up yet."); return; }
        if (checking) return;
        checking = true;
        ui.removeCallbacks(retry);
        if (!live) showOffline("Connecting…", "Looking for Anzen-bot on your computer…");
        new Thread(new Runnable() {
            @Override public void run() {
                final String why = Targets.live(url, token);
                ui.post(new Runnable() {
                    @Override public void run() {
                        checking = false;
                        if (isFinishing() || isDestroyed()) return;
                        if (why == null) reachable(url, token);
                        else { showOffline("Anzen-bot is not running", why); ui.postDelayed(retry, RETRY_MS); }
                    }
                });
            }
        }).start();
    }

    /** The app answered. Show the workspace — the same view, so a conversation that was open is
        still open, and a turn that was streaming is still streaming. */
    private void reachable(String url, String token) {
        ui.removeCallbacks(retry);
        live = true;
        offline.setVisibility(View.GONE);
        setup.setVisibility(View.GONE);
        chat.setVisibility(View.VISIBLE);
        chat.start(url, token);
        ui.removeCallbacks(keepAlive);
        ui.postDelayed(keepAlive, KEEPALIVE_MS);   // and keep checking, so quitting it blocks the phone
    }

    // ---- the setup screen --------------------------------------------------------------------

    private ScrollView buildSetup() {
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setGravity(Gravity.CENTER_VERTICAL);
        int p = dp(24);
        col.setPadding(p, dp(40), p, p);

        TextView title = new TextView(this);
        title.setText("Anzen-bot");
        title.setTextColor(FG);
        title.setTextSize(30);
        col.addView(title);

        TextView sub = new TextView(this);
        sub.setText("Your bots, on your own computer. Point this app at the server running there.");
        sub.setTextColor(DIM);
        sub.setTextSize(14);
        sub.setPadding(0, dp(8), 0, dp(24));
        col.addView(sub);

        col.addView(label("Server address"));
        urlField = new EditText(this);
        urlField.setHint("http://192.168.1.10:8093  ·  https://your-relay");
        urlField.setInputType(InputType.TYPE_TEXT_VARIATION_URI | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        style(urlField);
        col.addView(urlField);

        col.addView(label("Access token"));
        tokenField = new EditText(this);
        tokenField.setHint("paste the token from the terminal");
        tokenField.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        style(tokenField);
        col.addView(tokenField);

        Button go = new Button(this);
        go.setText("Connect");
        go.setTextColor(0xFFFFFFFF);
        go.setBackgroundColor(ACCENT);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, dp(50));
        lp.topMargin = dp(22);
        col.addView(go, lp);
        go.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { connect(); }
        });

        status = new TextView(this);
        status.setTextColor(DIM);
        status.setTextSize(13);
        status.setPadding(0, dp(14), 0, 0);
        col.addView(status);

        TextView hint = new TextView(this);
        hint.setText("On the computer, open Anzen-bot and turn on phone access — it prints this address "
                   + "and token. You can paste the whole printed link into the address box above; the "
                   + "token is taken out of it for you. On your own wifi that is all you need.\n\n"
                   + "Away from home, paste the relay address from Settings → Phone → From anywhere "
                   + "instead — the same box, the same token. The computer dials out to that relay, so "
                   + "it works on cellular or hotel wifi without anything being exposed.");
        hint.setTextColor(DIM);
        hint.setTextSize(12);
        hint.setPadding(0, dp(22), 0, 0);
        col.addView(hint);

        ScrollView sc = new ScrollView(this);
        sc.setBackgroundColor(BG);
        sc.addView(col, new ViewGroup.LayoutParams(-1, -2));
        return sc;
    }

    private TextView label(String text) {
        TextView t = new TextView(this);
        t.setText(text);
        t.setTextColor(DIM);
        t.setTextSize(12);
        t.setPadding(dp(2), dp(14), 0, dp(4));
        return t;
    }

    private void style(EditText e) {
        e.setTextColor(FG);
        e.setHintTextColor(Pal.FAINT);
        e.setTextSize(16);
        e.setSingleLine(true);
        e.setPadding(dp(12), dp(12), dp(12), dp(12));
        e.setBackgroundColor(Pal.CARD);
    }

    private void showSetup(String message) {
        ui.removeCallbacks(retry); ui.removeCallbacks(keepAlive);
        live = false;
        setup.setVisibility(View.VISIBLE);
        offline.setVisibility(View.GONE);
        chat.setVisibility(View.GONE);
        status.setText(message == null ? "" : message);
        if (urlField.getText().length() == 0) urlField.setText(prefs.getString("url", ""));
        if (tokenField.getText().length() == 0) tokenField.setText(prefs.getString("token", ""));
    }

    /** Read the two fields, let a pasted link give up its token, keep them, and go through the door:
        paired is not the same as reachable, so the same check that runs on launch runs here. */
    private void connect() {
        String[] target = Targets.split(urlField.getText().toString(), tokenField.getText().toString());
        String url = target[0], token = target[1];
        if (!Targets.reachable(url)) { status.setText("That does not look like an address."); return; }
        if (token.isEmpty()) { status.setText("The access token is needed too."); return; }

        prefs.edit().putString("url", url).putString("token", token).apply();
        status.setText("");
        check();
    }

    // ---- the door, when it is shut -----------------------------------------------------------

    /** The app with nothing behind it. The workspace comes off the screen — that is the whole point
        of the door: there is no offline mode, because there is nothing to be offline *from*. */
    private void showOffline(String title, String message) {
        ui.removeCallbacks(keepAlive);
        live = false;
        offlineTitle.setText(title);
        offlineMsg.setText(message == null ? "" : message);
        String url = prefs.getString("url", "");
        offlineAddr.setText(url.isEmpty() ? "" : "Tried " + url);
        offline.setVisibility(View.VISIBLE);
        setup.setVisibility(View.GONE);
        chat.setVisibility(View.GONE);
    }

    private ScrollView buildOffline() {
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setGravity(Gravity.CENTER_VERTICAL);
        int p = dp(24);
        col.setPadding(p, dp(40), p, p);

        offlineTitle = new TextView(this);
        offlineTitle.setText("Anzen-bot is not running");
        offlineTitle.setTextColor(FG);
        offlineTitle.setTextSize(26);
        col.addView(offlineTitle);

        offlineMsg = new TextView(this);
        offlineMsg.setTextColor(DIM);
        offlineMsg.setTextSize(14);
        offlineMsg.setPadding(0, dp(10), 0, 0);
        col.addView(offlineMsg);

        offlineAddr = new TextView(this);
        offlineAddr.setTextColor(Pal.FAINT);
        offlineAddr.setTextSize(12);
        offlineAddr.setPadding(0, dp(8), 0, 0);
        col.addView(offlineAddr);

        Button again = new Button(this);
        again.setText("Try again");
        again.setTextColor(0xFFFFFFFF);
        again.setBackgroundColor(ACCENT);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, dp(50));
        lp.topMargin = dp(24);
        col.addView(again, lp);
        again.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { check(); }
        });

        Button change = new Button(this);
        change.setText("Change address");
        change.setTextColor(FG);
        change.setBackgroundColor(Pal.CARD);
        LinearLayout.LayoutParams lp2 = new LinearLayout.LayoutParams(-1, dp(46));
        lp2.topMargin = dp(10);
        col.addView(change, lp2);
        change.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { showSetup(""); }
        });

        TextView hint = new TextView(this);
        hint.setText("This app talks to Anzen-bot on your computer — it has nothing to show on its own. "
                   + "Open Anzen-bot there and turn on phone access in Settings; this screen keeps "
                   + "checking by itself, so it will open as soon as the app is running. Nothing here "
                   + "leaves your own network.");
        hint.setTextColor(DIM);
        hint.setTextSize(12);
        hint.setPadding(0, dp(22), 0, 0);
        col.addView(hint);

        ScrollView sc = new ScrollView(this);
        sc.setBackgroundColor(BG);
        sc.addView(col, new ViewGroup.LayoutParams(-1, -2));
        return sc;
    }

    // ---- back ---------------------------------------------------------------------------------

    @Override public void onBackPressed() {
        // Back out of the chat first — a conversation, then the list, then the app itself. From the
        // door there is nowhere to go back to: the workspace behind it is not usable.
        if (chat.getVisibility() == View.VISIBLE && chat.back()) return;
        super.onBackPressed();
    }

    private int dp(int n) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, n, getResources().getDisplayMetrics());
    }
}
