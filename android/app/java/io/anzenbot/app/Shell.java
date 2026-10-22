package io.anzenbot.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Build;
import android.view.View;
import android.view.WindowInsets;
import android.webkit.CookieManager;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;

/**
 * The workspace, which is the desktop's own page.
 *
 * This phone draws no UI of its own: the window and the phone load the same `index.html` and run the
 * same `app.js`, so a feature that reaches one reaches both and there is no second implementation to
 * fall out of step. What stays native is the door ({@link MainActivity}) and the four things a page
 * cannot do from inside a WebView: be handed its pairing cookie, open an outside link in the phone's
 * browser, raise the file picker, and answer the hardware back button.
 */
final class Shell extends FrameLayout {
    /** What the wrapper tells the door when the page itself has gone. */
    interface Host {
        /** The page could not be loaded, for a reason worth retrying. */
        void lost(String why);
        /** The server refused the pairing: the token is the one thing the user can fix here. */
        void unpaired(String why);
    }

    static final int PICK_FILE = 4002;

    private final WebView web;
    private final Host host;
    private String base = "", token = "";
    private boolean started = false;
    private ValueCallback<Uri[]> picking;   // the page's own file input, waiting on the picker

    @SuppressLint("SetJavaScriptEnabled")
    Shell(Context c, Host host) {
        super(c);
        this.host = host;
        web = new WebView(c);
        web.setBackgroundColor(Pal.BG);          // no white flash between the door and the page
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);            // the page keeps its own small state there
        s.setTextZoom(100);                      // the app has a size setting of its own; the system's
                                                 // zoom would compound it rather than set it
        web.setWebViewClient(client());
        web.setWebChromeClient(chrome());
        addView(web, new FrameLayout.LayoutParams(-1, -1));
        insets();
    }

    /**
     * The status bar and the keyboard are drawn *over* the app from Android 15, and `adjustResize` no
     * longer shrinks the window — so the page would run under the clock and its composer under the
     * keyboard. The insets become padding on the shell, which shrinks the WebView itself: padding on
     * the WebView would move its content but not its viewport, and the page's toolbar and composer
     * are `position:fixed`, so they would stay where they were. What is left uncovered is painted in
     * the app's own background rather than the page's.
     */
    private void insets() {
        setBackgroundColor(Pal.BG);
        setOnApplyWindowInsetsListener(new View.OnApplyWindowInsetsListener() {
            @Override public WindowInsets onApplyWindowInsets(View v, WindowInsets in) {
                int bottom = in.getSystemWindowInsetBottom();
                if (Build.VERSION.SDK_INT >= 30) bottom = Math.max(bottom, in.getInsets(WindowInsets.Type.ime()).bottom);
                v.setPadding(0, in.getSystemWindowInsetTop(), 0, bottom);
                return in;
            }
        });
    }

    // ---- the page ----------------------------------------------------------------------------

    /**
     * The door opened. The page is the desktop's, so the one thing to arrange is the pairing cookie:
     * the server hands it to a client that proves it holds the token, and this phone already does. Set
     * before the first request, so the token never travels in the URL the page is loaded from — which
     * is the difference between this client and the `/?t=` link a browser needs.
     */
    void start(String url, String tok) {
        // `loadUrl(url + "/")` and the same-origin test below both assume a bare origin; a caller that
        // passes one with a trailing slash would load `//` and send every page to the phone's browser.
        if (url.endsWith("/")) url = url.substring(0, url.length() - 1);
        if (started && url.equals(base) && tok.equals(token)) return;
        base = url; token = tok; started = true;
        CookieManager cm = CookieManager.getInstance();
        cm.setCookie(url, "anzen_pair=" + tok + "; Path=/");
        cm.flush();
        web.loadUrl(url + "/");
    }

    void pause() { web.onPause(); }

    void resume() {
        web.onResume();
        // The roster and the chat on screen may have moved while the phone was away, and a WebView
        // that was paused is not reliably a hidden document, so the page is asked outright.
        web.evaluateJavascript("window.anzenWake && window.anzenWake()", null);
    }

    /** The hardware back button. The page decides: a surface it can dismiss answers true and the app
        stays; false means nothing was open, and the app itself is what closes. */
    void back(final Runnable leave) {
        web.evaluateJavascript("window.anzenBack ? window.anzenBack() : false", new ValueCallback<String>() {
            @Override public void onReceiveValue(String v) { if (!"true".equals(v)) leave.run(); }
        });
    }

    /** The picker came back. A cancelled one is answered with null — a file input left unanswered
        stops every later pick in the page. */
    void filePicked(int result, Intent data) {
        ValueCallback<Uri[]> cb = picking;
        picking = null;
        if (cb == null) return;
        Uri[] uris = null;
        if (result == Activity.RESULT_OK && data != null) {
            // Several files come back in the clip data; a single one in the intent's own data.
            android.content.ClipData clip = data.getClipData();
            if (clip != null) {
                uris = new Uri[clip.getItemCount()];
                for (int i = 0; i < uris.length; i++) uris[i] = clip.getItemAt(i).getUri();
            } else if (data.getData() != null) {
                uris = new Uri[]{data.getData()};
            }
        }
        cb.onReceiveValue(uris);
    }

    // ---- what a page cannot do for itself ------------------------------------------------------

    private WebViewClient client() {
        return new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                Uri u = r.getUrl();
                // `base + "/"`, not `base`: a prefix test let a host that merely starts with the
                // configured one — relay.example.com.evil.tld — load inside the app's own WebView.
                if (!r.isForMainFrame() || u.toString().startsWith(base + "/")) return false;
                open(u);           // anything that is not this server belongs to the phone's browser
                return true;
            }
            @Override public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e) {
                if (!r.isForMainFrame()) return;
                started = false;   // so the next probe that finds the desktop up loads the page again
                host.lost("The page did not load: " + e.getDescription());
            }
            @Override public void onReceivedHttpError(WebView v, WebResourceRequest r, WebResourceResponse res) {
                if (!r.isForMainFrame() || res.getStatusCode() != 403) return;
                started = false;
                host.unpaired("Anzen-bot is running, but this phone is not paired with it — check the "
                            + "access token.");
            }
            @Override public void onPageFinished(WebView v, String url) {
                v.clearHistory();  // back is the hardware button and the page's hook, never a page stack
            }
        };
    }

    private WebChromeClient chrome() {
        return new WebChromeClient() {
            /* Multiple windows are left off, which is what sends a `target="_blank"` link to the page
               itself: `shouldOverrideUrlLoading` then sees it and hands it to the browser. A second
               WebView just to catch the URL would be a window that never shows anything. */
            @Override public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> cb, FileChooserParams p) {
                if (picking != null) picking.onReceiveValue(null);   // a second ask never leaves the first hung
                picking = cb;
                Intent i = new Intent(Intent.ACTION_GET_CONTENT);
                i.addCategory(Intent.CATEGORY_OPENABLE);
                String[] accept = p.getAcceptTypes();
                if (accept != null && accept.length > 1) i.putExtra(Intent.EXTRA_MIME_TYPES, accept);
                i.setType(accept != null && accept.length > 0 && accept[0].contains("/") ? accept[0] : "*/*");
                // The page's input takes several files, so the picker must let you pick several.
                if (p.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE) i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
                try {
                    ((Activity) getContext()).startActivityForResult(
                            Intent.createChooser(i, "Choose a file"), PICK_FILE);
                } catch (Exception e) {
                    picking = null; cb.onReceiveValue(null); return false;   // no picker on this phone
                }
                return true;
            }
        };
    }

    private void open(Uri u) {
        try { getContext().startActivity(new Intent(Intent.ACTION_VIEW, u)); }
        catch (Exception ignored) { }   // no browser, or nothing that claims the scheme
    }

    // ---- the door screens' theme ---------------------------------------------------------------

    /**
     * Wear the theme the phone remembers, before a single view is built.
     *
     * A colour is baked into a drawable the moment the drawable is made, so a theme applied after the
     * screen exists would repaint half of it. The server owns the setting; this is the cache the door
     * screens read, so the next launch starts in the right colours instead of flashing the default.
     */
    static void wear(Context c) {
        SharedPreferences p = c.getSharedPreferences("anzen", Context.MODE_PRIVATE);
        Pal.apply(p.getString("theme", Pal.DEFAULT_THEME), p.getFloat("font_size", 0f),
                  p.getString("density", ""));
    }
}
