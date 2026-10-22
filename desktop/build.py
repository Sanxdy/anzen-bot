#!/usr/bin/env python3
"""Package Anzen-bot as a desktop app — for the machine this is run on.

The app is Electron, the same shape as ZCode: the window is loaded **from disk** (a `file://` page
out of the install directory), the renderer talks to the main process over **IPC**, and everything
under `/api/` is proxied to a Python backend over a Unix socket. No port is opened, so opening the
app never puts the workspace on localhost.

That makes the build two steps. First the Python backend is frozen into a plain console binary
(`anzen-backend`) with PyInstaller. Then `electron-builder` wraps that binary and the web shell into
the app. Neither tool cross-compiles, so a Windows `.exe` is built on Windows and a Linux build on
Linux, and `.github/workflows/build.yml` runs this on all three.

    python3 desktop/build.py                # the app for this OS
    python3 desktop/build.py --no-browser   # skip Playwright's Chromium: a much smaller app, but the
                                            # Computer panel reports "browser unavailable"
    python3 desktop/build.py --no-dmg       # skip the macOS disk image

Output lands in desktop/dist/:
    macOS    Anzen-bot.app   Anzen-bot-<ver>.dmg
    Windows  Anzen-bot Setup <ver>.exe
    Linux    Anzen-bot-<ver>.tar.gz
"""
import argparse, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ELECTRON = os.path.join(HERE, "electron")
DIST = os.path.join(HERE, "dist")            # where electron-builder puts the finished app
WORK = os.path.join(HERE, "build")           # PyInstaller's scratch space
BACKEND_DIST = os.path.join(HERE, "dist-backend")   # the frozen backend electron-builder bundles
APP = "Anzen-bot"
BACKEND = "anzen-backend"


def version():
    """The app's own version, from the one place it is written down."""
    for line in open(os.path.join(ROOT, "server.py")):
        if line.startswith("VERSION = "): return line.split("=", 1)[1].strip().strip('"\'')
    return "0.0.0"


def run(cmd, **kw):
    print("   $", " ".join(str(c) for c in cmd))
    kw.setdefault("stdout", subprocess.DEVNULL)
    return subprocess.run(cmd, check=True, **kw)


def stage_browsers():
    """A Chromium for the Computer panel, fetched straight into the bundle. `--only-shell` is the
    headless build the bot actually drives — a fraction of the size of the full browser."""
    d = os.path.join(WORK, "pw-browsers")
    shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    run([sys.executable, "-m", "playwright", "install", "chromium", "--only-shell"],
        env=dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=d))
    return d


def mac_icon():
    """An .icns from the app's own icon, made with the tools macOS already has (no Pillow)."""
    src = os.path.join(ROOT, "icon-512.png")
    if not os.path.exists(src): return None
    out = os.path.join(WORK, APP + ".icns")
    iconset = os.path.join(WORK, APP + ".iconset")
    shutil.rmtree(iconset, ignore_errors=True); os.makedirs(iconset)
    for size in (16, 32, 128, 256, 512):
        png = os.path.join(iconset, "icon_%dx%d.png" % (size, size))
        run(["sips", "-z", str(size), str(size), src, "--out", png])
        # Each rendered size is also the Retina slot of the size below it.
        if size in (32, 256, 512):
            shutil.copyfile(png, os.path.join(iconset, "icon_%dx%d@2x.png" % (size // 2, size // 2)))
    run(["iconutil", "-c", "icns", iconset, "-o", out])
    return out


def backend_args(browsers):
    """The backend as one console binary. Console, not windowed: this process has no window — the
    Electron shell owns that — and it has to be able to write to stderr for the app's log."""
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--console",
            "--name", BACKEND, "--paths", ROOT, "--distpath", BACKEND_DIST, "--workpath", WORK,
            "--specpath", WORK,
            "--exclude-module", "tkinter", "--exclude-module", "test"]
    if browsers:
        args += ["--collect-all", "playwright", "--add-data", browsers + os.pathsep + "pw-browsers"]
    else:
        # server.py imports playwright lazily and degrades to "browser unavailable", so excluding
        # it costs the browser tool and nothing else.
        args += ["--exclude-module", "playwright"]
    if sys.platform == "win32" or sys.platform.startswith("linux"):
        args += ["--onefile"]
    args.append(os.path.join(HERE, "anzen_app.py"))
    return args


def ensure_node_modules():
    if os.path.isdir(os.path.join(ELECTRON, "node_modules", "electron")): return
    print("   installing the Electron toolchain (first run only)")
    run(["npm", "install", "--no-audit", "--no-fund"], cwd=ELECTRON)


def electron_build(ver, icon):
    """Wrap the frozen backend and the web shell into the app. `--publish never` keeps it local: a
    release is a separate, deliberate step."""
    # electron-builder stamps the version it finds in package.json, so the two are put in step before
    # the build and not after it — otherwise the first build after a version bump ships the old one.
    pkg = os.path.join(ELECTRON, "package.json")
    d = json.load(open(pkg))
    if d.get("version") != ver:
        d["version"] = ver
        json.dump(d, open(pkg, "w"), indent=2)
    cmd = ["npx", "electron-builder", "--publish", "never"]
    if sys.platform == "darwin":
        cmd += ["--mac"]
        if icon: cmd += ["-c.mac.icon=" + icon]
    elif sys.platform == "win32":
        cmd += ["--win"]
    else:
        cmd += ["--linux"]
    run(cmd, cwd=ELECTRON)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-browser", action="store_true",
                    help="skip Playwright's Chromium (smaller app; no Computer panel)")
    ap.add_argument("--no-dmg", action="store_true", help="skip the macOS disk image")
    ap.add_argument("--backend-only", action="store_true",
                    help="freeze the Python backend and stop (no Electron packaging)")
    opts = ap.parse_args()
    ver = version()
    shutil.rmtree(WORK, ignore_errors=True); os.makedirs(WORK)
    shutil.rmtree(BACKEND_DIST, ignore_errors=True)
    shutil.rmtree(DIST, ignore_errors=True)      # a stale artefact from an older shape is not a build

    browsers = None
    if not opts.no_browser:
        try:
            import playwright  # noqa: F401
            browsers = stage_browsers()
        except Exception as e:
            print("   ! no Playwright in this build environment (%s)." % e)
            print("     For the Computer panel, install it and rebuild:")
            print("       %s -m pip install playwright && %s -m playwright install chromium --only-shell"
                  % (sys.executable, sys.executable))

    print("==> freezing the backend (%s) for %s" % (BACKEND, sys.platform))
    run(backend_args(browsers))
    if opts.backend_only:
        print("\n==> done\n   %s" % BACKEND_DIST)
        return

    print("==> packaging the app with Electron")
    ensure_node_modules()
    electron_build(ver, mac_icon() if sys.platform == "darwin" else None)

    print("\n==> done")
    for name in sorted(os.listdir(DIST)):
        p = os.path.join(DIST, name)
        if os.path.isdir(p):
            size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(p) for f in fs)
        else:
            size = os.path.getsize(p)
        print("   %-52s %7.1f MB" % (p, size / 1e6))


if __name__ == "__main__":
    main()
