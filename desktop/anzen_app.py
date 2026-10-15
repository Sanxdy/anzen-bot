#!/usr/bin/env python3
"""Anzen-bot's desktop backend.

The backend is the very same `server.py` the browser version runs. This file decides only where a
packaged app keeps its data and how the Electron shell reaches it. The shell starts this with
`--sock`, so the app's own channel is a Unix socket: no port is opened, and opening the app never
puts the workspace on localhost.

    python3 desktop/anzen_app.py --sock PATH   # the app's own channel, as the shell starts it
    python3 desktop/anzen_app.py               # just the backend, on loopback, for working on it
    python3 desktop/anzen_app.py --lan         # also reachable by the Android app on your wifi
"""
import os, sys


def app_data_dir():
    """Where a desktop app is allowed to keep its data. Never inside the bundle: that is read-only
    once installed, and an upgrade replaces it wholesale — a roster living there would be gone."""
    if os.environ.get("DATA_DIR"): return os.environ["DATA_DIR"]
    home = os.path.expanduser("~")
    if sys.platform == "darwin": base = os.path.join(home, "Library", "Application Support")
    elif os.name == "nt": base = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
    else: base = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    return os.path.join(base, "Anzen-bot")


def bundled_browser_dir():
    """Playwright's browsers, when the app was built with them. Pointing playwright at the copy
    inside the bundle is the difference between a working Computer panel and 'browser unavailable':
    left to itself it looks in the user's own cache, which on a fresh machine is empty."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(base, "pw-browsers")
    return d if os.path.isdir(d) else None


def main():
    argv = sys.argv[1:]
    lan = "--lan" in argv
    # `--sock PATH`, or ANZEN_SOCK in the environment (which is how the Electron shell starts this),
    # makes this process the backend only: it answers on a Unix socket and opens no port. The window
    # is Electron's, and it talks to this process over the socket.
    if "--sock" in argv:
        i = argv.index("--sock")
        if i + 1 < len(argv): os.environ["ANZEN_SOCK"] = argv[i + 1]
    sock = os.environ.get("ANZEN_SOCK")

    os.environ.setdefault("DATA_DIR", app_data_dir())
    os.environ.setdefault("SANDBOX_DIR", os.path.join(os.environ["DATA_DIR"], "sandbox"))
    pw = bundled_browser_dir()
    if pw: os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", pw)
    # From source the server is next door; in a bundle it is a module beside this one.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    import server
    if "--doctor" in argv:
        # What the packaged app actually resolved, for when something looks missing. A bundle is
        # opaque from the outside, and "which directory did it think it was in" is the first
        # question every packaging problem comes down to.
        print("data dir    ", os.environ["DATA_DIR"])
        print("sandbox     ", os.environ["SANDBOX_DIR"])
        print("app dir     ", server.HERE)
        print("app shell   ", server.SHELL if os.path.isfile(os.path.join(server.SHELL, "index.html"))
              else "MISSING — the phone's door would 404 on /")
        print("browser dir ", pw or "(not bundled)")
        print("frozen      ", bool(getattr(sys, "_MEIPASS", None)))
        print("channel     ", sock or "(a TCP port)")
        return
    # The backend, and nothing more. The shell owns the window and reaches this process over the
    # socket; started by hand without one it is simply the server — on loopback, or on your wifi
    # with `--lan` — which is also what the Phone & tablet switch in the UI toggles.
    server.serve(host="0.0.0.0" if lan else None)


if __name__ == "__main__":
    main()
