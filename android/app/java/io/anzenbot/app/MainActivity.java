package io.anzenbot.app;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.res.ColorStateList;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

/**
 * The Anzen-bot app: the desktop's own workspace, on a phone.
 *
 * The chat surface is not rebuilt here — {@link Shell} loads the same page the desktop window loads,
 * so the two cannot drift apart. What this file owns is the door. The phone is bound to the desktop
 * app: with that app closed there is no server, no chats and no bots, so every launch — and every
 * time the phone comes back to the front, and once in a while while it is being used — the phone asks
 * the computer whether it is there. If it is not, the workspace comes off the screen and is replaced
 * by the reason, and the phone keeps looking on its own, so starting the app on the computer is all it
 * takes to get back in.
 */
public class MainActivity extends Activity {
    private static final String PREFS = "anzen";
    private static final long RETRY_MS = 3000;      // how often a blocked app looks again
    private static final long KEEPALIVE_MS = 10000; // how often a live one checks it still is

    private SharedPreferences prefs;
    private FrameLayout root;
    private ScrollView setup, offline;
    private Shell shell;
    private EditText urlField, tokenField;
    private TextView status, offlineTitle, offlineMsg, offlineAddr;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private boolean checking = false;    // one probe at a time: a retry must not stack up behind it
    private boolean live = false;        // the desktop app answered, so a probe must not blank the screen
    private boolean resumed = false;     // the screen is on: a probe's answer is still worth acting on

    private final Runnable retry = new Runnable() {
        @Override public void run() { check(); }
    };
    private final Runnable keepAlive = new Runnable() {
        @Override public void run() { check(); }
    };

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        prefs = getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        // The colours have to be in place before the first view is built: every one of them reads
        // `Pal` once, at construction, and a background painted from a not-yet-loaded palette is a
        // transparent one. The server is the owner of the setting; this only reads the cache of it.
        Shell.wear(this);
        root = new FrameLayout(this);
        root.setBackgroundColor(Pal.BG);
        shell = new Shell(this, new Shell.Host() {
            @Override public void lost(String why) { showOffline("Anzen-bot is not running", why); }
            @Override public void unpaired(String why) { showSetup(why); }
        });
        setup = buildSetup();
        offline = buildOffline();
        root.addView(shell, new FrameLayout.LayoutParams(-1, -1));
        root.addView(setup, new FrameLayout.LayoutParams(-1, -1));
        root.addView(offline, new FrameLayout.LayoutParams(-1, -1));
        setContentView(root);

        if (prefs.getString("url", "").isEmpty()) showSetup("Not set up yet.");
        else check();
    }

    @Override protected void onResume() {
        super.onResume();
        resumed = true;
        if (shell != null) shell.resume();
        // Coming back to the phone is exactly when the computer may have gone away, so the door is
        // checked again — unless the user is on the setup screen, where there is nothing to check yet.
        if (setup.getVisibility() != View.VISIBLE) check();
    }

    @Override protected void onPause() {
        super.onPause();
        resumed = false;
        // The probe goes to sleep with the screen. Left running it is a request every 10 s while the
        // desktop is up — and every 3 s, the retry pace, for as long as the desktop is down, which is
        // the state this phone sits in whenever you quit the app on your computer and pocket it. What
        // it bought was only that the offline screen was already painted on the way back in, and
        // `onResume` runs the same probe the moment you come back anyway. Both timers are cancelled,
        // not just the fast one: the retry is the one that runs hottest.
        ui.removeCallbacks(keepAlive);
        ui.removeCallbacks(retry);
        if (shell != null) shell.pause();
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
                        // The phone left the app while this probe was in flight. Acting on the answer
                        // is the whole of what used to keep the poll alive in the background: this is
                        // where the workspace would come back, where the watch stream would open (with
                        // `pause` already behind it, so nothing would close it), and where the next
                        // probe gets armed — each of which re-arms the one after it. `onResume` asks
                        // the same question again, so nothing is lost by dropping this answer.
                        if (!resumed) return;
                        if (why == null) reachable(url, token);
                        else { showOffline("Anzen-bot is not running", why); ui.postDelayed(retry, RETRY_MS); }
                    }
                });
            }
        }).start();
    }

    /** The app answered. Show the workspace — the same page, so a conversation that was open is still
        open and a turn that was streaming is still streaming. */
    private void reachable(String url, String token) {
        ui.removeCallbacks(retry);
        live = true;
        offline.setVisibility(View.GONE);
        setup.setVisibility(View.GONE);
        shell.setVisibility(View.VISIBLE);
        shell.start(url, token);
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

        col.addView(mark());

        TextView title = text("Anzen-bot", Pal.TXT, 19);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setPadding(0, dp(18), 0, 0);
        col.addView(title);

        TextView sub = text("SELF-HOSTED WORKSPACE", Pal.DIM2, 11);
        sub.setLetterSpacing(0.09f);
        sub.setPadding(0, dp(5), 0, 0);
        col.addView(sub);

        TextView blurb = text("Your bots, on your own computer. Point this app at the server running there.",
                              Pal.DIM, 14);
        blurb.setPadding(0, dp(16), 0, dp(24));
        col.addView(blurb);

        urlField = new EditText(this);
        urlField.setHint("http://192.168.1.10:8093  ·  https://your-relay");
        urlField.setInputType(InputType.TYPE_TEXT_VARIATION_URI | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        urlField.setId(View.generateViewId());
        style(urlField);
        col.addView(label("SERVER ADDRESS", urlField));
        col.addView(urlField);

        tokenField = new EditText(this);
        tokenField.setHint("paste the token from the terminal");
        tokenField.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        tokenField.setId(View.generateViewId());
        style(tokenField);
        col.addView(label("ACCESS TOKEN", tokenField));
        col.addView(tokenField);

        Button go = button("Connect", Pal.ACCENT, Pal.ACCENT_INK);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, dp(44));
        lp.topMargin = dp(22);
        col.addView(go, lp);
        go.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { connect(); }
        });

        status = text("", Pal.DIM, 14);
        status.setPadding(0, dp(14), 0, 0);
        col.addView(status);

        TextView hint = text("On the computer, open Settings → Phone and turn on Allow devices on this "
                   + "network. Then press Copy the link for the phone and paste the whole link into the "
                   + "address box above — the token is taken out of it for you. On your own wifi that is "
                   + "all you need.\n\n"
                   + "The first time that switch goes on, the computer may ask whether Anzen-bot may "
                   + "accept incoming connections; say yes, or the phone cannot get through.\n\n"
                   + "Away from home, fill in From anywhere in that same tab and paste the link it gives "
                   + "you here instead — the same box, the same token. The computer dials out to the "
                   + "relay, so it works on cellular or hotel wifi without anything being exposed.",
                   Pal.DIM2, 12);
        hint.setPadding(0, dp(22), 0, 0);
        col.addView(hint);

        ScrollView sc = new ScrollView(this);
        sc.setBackground(page());
        sc.addView(col, new ViewGroup.LayoutParams(-1, -2));
        return belowStatusBar(sc);
    }

    /** The desktop splash's mark at the size the splash draws it: the accent squircle, and the app's
        three dots inside it. */
    private View mark() {
        View v = new View(this) {
            private final Paint ink = new Paint(Paint.ANTI_ALIAS_FLAG);
            private final float corner = dp(24), step = dp(10), dot = dp(4);

            @Override protected void onDraw(Canvas c) {
                ink.setColor(Pal.ACCENT);
                c.drawRoundRect(0, 0, getWidth(), getHeight(), corner, corner, ink);
                ink.setColor(0xFFFFFFFF);
                float mid = getWidth() / 2f, y = getHeight() / 2f;
                for (int i = -1; i <= 1; i++) c.drawCircle(mid + i * step, y, dot, ink);
            }
        };
        v.setLayoutParams(new LinearLayout.LayoutParams(dp(96), dp(96)));
        return v;
    }

    /** The page a door stands on: the splash's own gradient, black down into the app's background. */
    private GradientDrawable page() {
        return new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM,
                                    new int[]{ 0xFF000000, Pal.BG });
    }

    /** A button as the desktop draws one — a flat fill with rounded corners, no elevation, no
        capitals, and the 44dp floor a thumb needs. The ripple is the fill's own press state. */
    private Button button(String s, int fill, int ink) {
        Button b = new Button(this);
        b.setText(s);
        b.setTextColor(ink);
        b.setTextSize(14);
        b.setTypeface(Typeface.DEFAULT_BOLD);
        b.setAllCaps(false);
        b.setGravity(Gravity.CENTER);
        b.setMinHeight(0);       // the theme's 48dp floor and its press animation are not the desktop's
        b.setMinimumWidth(0);
        b.setStateListAnimator(null);
        b.setBackground(new RippleDrawable(ColorStateList.valueOf(Pal.FOCUS),
                                           shape(fill, dp(11)), shape(fill, dp(11))));
        return b;
    }

    /** A flat fill behind the desktop's 11dp corners: a button, or the box a field is typed into. */
    private GradientDrawable shape(int fill, int radius) {
        GradientDrawable d = new GradientDrawable();
        d.setColor(fill);
        d.setCornerRadius(radius);
        return d;
    }

    /** One line of the door's own voice: colour and size are the whole of its styling. */
    private TextView text(String s, int color, int size) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextColor(color);
        t.setTextSize(size);
        return t;
    }

    private TextView label(String s, View field) {
        TextView t = text(s, Pal.DIM2, 12);
        t.setTypeface(Typeface.DEFAULT_BOLD);
        t.setLetterSpacing(0.07f);
        t.setPadding(dp(2), dp(14), 0, dp(4));
        t.setLabelFor(field.getId());   // so a screen reader names the box, not just its hint
        return t;
    }

    private void style(EditText e) {
        e.setTextColor(Pal.TXT);
        e.setHintTextColor(Pal.DIM2);
        e.setTextSize(15);
        e.setSingleLine(true);
        e.setPadding(dp(12), dp(12), dp(12), dp(12));
        GradientDrawable box = shape(Pal.CARD, dp(11));
        box.setStroke(dp(1), Pal.LINE2);
        e.setBackground(box);
    }

    private void showSetup(String message) {
        ui.removeCallbacks(retry); ui.removeCallbacks(keepAlive);
        live = false;
        setup.setVisibility(View.VISIBLE);
        offline.setVisibility(View.GONE);
        shell.setVisibility(View.GONE);
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
        shell.setVisibility(View.GONE);
    }

    private ScrollView buildOffline() {
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setGravity(Gravity.CENTER_VERTICAL);
        int p = dp(24);
        col.setPadding(p, dp(40), p, p);

        col.addView(mark());

        offlineTitle = text("Anzen-bot is not running", Pal.TXT, 19);
        offlineTitle.setTypeface(Typeface.DEFAULT_BOLD);
        offlineTitle.setPadding(0, dp(18), 0, 0);
        col.addView(offlineTitle);

        offlineMsg = text("", Pal.DIM, 14);
        offlineMsg.setPadding(0, dp(10), 0, 0);
        col.addView(offlineMsg);

        offlineAddr = text("", Pal.DIM2, 12);
        offlineAddr.setPadding(0, dp(8), 0, 0);
        col.addView(offlineAddr);

        Button again = button("Try again", Pal.ACCENT, Pal.ACCENT_INK);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, dp(44));
        lp.topMargin = dp(24);
        col.addView(again, lp);
        again.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { check(); }
        });

        Button change = button("Change address", Pal.CARD, Pal.TXT);
        LinearLayout.LayoutParams lp2 = new LinearLayout.LayoutParams(-1, dp(44));
        lp2.topMargin = dp(10);
        col.addView(change, lp2);
        change.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { showSetup(""); }
        });

        TextView hint = text("This app talks to Anzen-bot on your computer — it has nothing to show on "
                   + "its own. Open Anzen-bot there and turn on phone access in Settings → Phone; this "
                   + "screen keeps checking by itself, so it will open as soon as the app is running. "
                   + "Nothing here leaves your own network.", Pal.DIM2, 12);
        hint.setPadding(0, dp(22), 0, 0);
        col.addView(hint);

        ScrollView sc = new ScrollView(this);
        sc.setBackground(page());
        sc.addView(col, new ViewGroup.LayoutParams(-1, -2));
        return belowStatusBar(sc);
    }

    // ---- back ---------------------------------------------------------------------------------

    @Override public void onBackPressed() {
        // The page closes whatever surface it has open — a dialog, Settings, the drawer — and says so.
        // Only when nothing was open does back mean the app itself. From the door there is nowhere to
        // go back to: the workspace behind it is not usable.
        if (shell.getVisibility() == View.VISIBLE) shell.back(new Runnable() {
            @Override public void run() { leave(); }
        });
        else leave();
    }

    /** The app closes — named rather than calling `super` from inside a callback, so the call site
        says what it is. */
    private void leave() { super.onBackPressed(); }

    /** The one result this app asks another screen for: the file a page's own file input asked for.
        A view has no result of its own, so it is handed on to the shell, which knows what is waiting. */
    @Override protected void onActivityResult(int req, int result, Intent data) {
        super.onActivityResult(req, result, data);
        if (req == Shell.PICK_FILE) shell.filePicked(result, data);
    }

    /** The status bar is drawn over the app, not beside it, from Android 15 — so a screen that began
        at the top of the window would start under the clock. Both door screens are a ScrollView, so
        the inset becomes top padding: the text starts below the clock, the background runs up behind
        it, and on an older Android the inset arrives already spent and nothing moves. */
    private ScrollView belowStatusBar(ScrollView sc) {
        sc.setOnApplyWindowInsetsListener(new View.OnApplyWindowInsetsListener() {
            @Override public WindowInsets onApplyWindowInsets(View v, WindowInsets insets) {
                v.setPadding(0, insets.getSystemWindowInsetTop(), 0, 0);
                return insets;
            }
        });
        return sc;
    }

    private int dp(int n) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, n, getResources().getDisplayMetrics());
    }
}
