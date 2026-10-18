#!/usr/bin/env python3
"""The Android app's non-Android logic, checked on a plain JVM.

The app needs a phone to run, so the parts that can be checked here are checked here. Targets (turning
what the user typed into a server address), Json (reading what the server sends, which the theme
cache goes through) and Pal (the palette) are deliberately free of Android, and this compiles the
app's own copies of them — not duplicates — together with the checks and runs them. MainActivity and
Shell are the Android half and are not covered here: they are driven by hand on the emulator, which
is where the layout itself is the thing being checked.

The chat surface itself is not drawn here at all — Shell loads the desktop's own page, so the
transcript, the drawer and the settings panel are the desktop's code, checked by its own tests.

Usage:  python3 tests/test_android.py
"""
import glob, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "android"))
import build_apk  # the same javac lookup the APK build uses

APP = os.path.join(ROOT, "android", "app", "java", "io", "anzenbot", "app")
# Everything in the app that does not import android.* — so it runs here as well as on a phone.
PURE = ["Targets.java", "Json.java", "Pal.java"]
CHECKS = ["TargetsCheck.java"]

jc = build_apk.javac()
out = tempfile.mkdtemp(prefix="anzen-android-")
srcs = [os.path.join(APP, f) for f in PURE] + [os.path.join(ROOT, "tests", "android", c) for c in CHECKS]
r = subprocess.run([jc, "-d", out, *srcs], capture_output=True, text=True)
if r.returncode:
    sys.exit("javac failed:\n" + r.stdout + r.stderr)

java = os.path.join(os.path.dirname(jc), "java")
rc = 0
for check in CHECKS:
    name = check[:-len(".java")]
    print("=== " + name + " ===")
    r = subprocess.run([java, "-cp", out, "io.anzenbot.app." + name], capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    rc = rc or r.returncode
sys.exit(rc)
