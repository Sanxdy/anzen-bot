#!/usr/bin/env python3
"""Build the Android app — an APK, with no Gradle anywhere.

Gradle is a large dependency to fetch for a handful of classes, and this machine has the pieces the
SDK actually needs already: `aapt2` to compile resources and link the manifest, `d8` to turn class
files into a dex, `zipalign` and `apksigner` to finish it. So this script drives those four
directly, in the order a build system would, and signs with the standard debug key.

    python3 android/build_apk.py                 # dist/Anzen-bot-1.0.0-debug.apk
    python3 android/build_apk.py --release       # ...-release.apk, unsigned
    python3 android/build_apk.py --install       # build, then adb install -r onto a connected phone

Needs: Android SDK (ANDROID_HOME, or ~/Library/Android/sdk), a JDK 8+ (JAVA_HOME, Android Studio's
bundled JBR, or javac on PATH), and on macOS `sips` to make the launcher icons.
"""
import argparse, glob, os, re, shutil, subprocess, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
APP = os.path.join(HERE, "app")
BUILD = os.path.join(HERE, "build")
DIST = os.path.join(HERE, "dist")
# The launcher icon comes from the same art the desktop app and the web app use.
ICON_SRC = os.path.join(ROOT, "icon-512.png")
DENSITIES = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}


def version():
    """The version lives in server.py, so every build of every platform agrees on it."""
    with open(os.path.join(ROOT, "server.py")) as f:
        return re.search(r'^VERSION\s*=\s*"([^"]+)"', f.read(), re.M).group(1)


def sdk_root():
    for k in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(k) and os.path.isdir(os.environ[k]): return os.environ[k]
    for p in (os.path.expanduser("~/Library/Android/sdk"), os.path.expanduser("~/Android/Sdk"),
              "/usr/lib/android-sdk", "/opt/android-sdk"):
        if os.path.isdir(p): return p
    sys.exit("No Android SDK found. Set ANDROID_HOME to the SDK directory.")


def build_tools(sdk):
    """Newest build-tools that has all four of the programs this script needs."""
    want = ("aapt2", "d8", "zipalign", "apksigner")
    def key(d):
        m = re.match(r"(\d+)\.(\d+)\.(\d+)", os.path.basename(d))
        return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)
    for d in sorted(glob.glob(os.path.join(sdk, "build-tools", "*")), key=key, reverse=True):
        if all(os.path.exists(os.path.join(d, w)) for w in want): return d
    sys.exit("No build-tools with aapt2/d8/zipalign/apksigner in " + sdk)


def platform_jar(sdk):
    def key(d):
        m = re.search(r"android-(\d+)", os.path.basename(d))
        return int(m.group(1)) if m else 0
    for d in sorted(glob.glob(os.path.join(sdk, "platforms", "android-*")), key=key, reverse=True):
        jar = os.path.join(d, "android.jar")
        if os.path.isfile(jar): return jar
    sys.exit("No android.jar under " + os.path.join(sdk, "platforms"))


def javac():
    home = os.environ.get("JAVA_HOME")
    for cand in ([os.path.join(home, "bin", "javac")] if home else []) + [
            "/Applications/Android Studio.app/Contents/jbr/Contents/Home/bin/javac"]:
        if os.path.exists(cand): return cand
    found = shutil.which("javac")
    if found: return found
    sys.exit("No javac found. Set JAVA_HOME, or install Android Studio.")


def use_java(jc):
    """aapt2, d8, apksigner and keytool are launcher scripts that shell out to `java`, so the JDK
    javac came from has to be on PATH for them too — not just JAVA_HOME."""
    home = os.path.dirname(os.path.dirname(os.path.abspath(jc)))
    os.environ["JAVA_HOME"] = home
    os.environ["PATH"] = os.path.join(home, "bin") + os.pathsep + os.environ.get("PATH", "")
    return home


def run(*cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit("failed: " + " ".join(cmd) + "\n" + (r.stdout or "") + (r.stderr or ""))
    return r.stdout


def resize(src, dst, px):
    """One square PNG. `sips` is macOS-only, so a Linux runner uses ImageMagick instead."""
    if shutil.which("sips"): run("sips", "-z", str(px), str(px), src, "--out", dst)
    elif shutil.which("convert"): run("convert", src, "-resize", "%dx%d" % (px, px), dst)
    elif shutil.which("magick"): run("magick", src, "-resize", "%dx%d" % (px, px), dst)
    else: sys.exit("Need sips (macOS) or ImageMagick to make the launcher icons.")


def icons():
    """Downscale the shared icon into the five launcher densities."""
    out = os.path.join(BUILD, "res")
    shutil.rmtree(out, ignore_errors=True)
    for name, px in DENSITIES.items():
        d = os.path.join(out, "mipmap-" + name)
        os.makedirs(d)
        resize(ICON_SRC, os.path.join(d, "ic_launcher.png"), px)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", action="store_true", help="build an unsigned release APK")
    ap.add_argument("--install", action="store_true", help="adb install the result")
    args = ap.parse_args()

    sdk = sdk_root(); bt = build_tools(sdk); jar = platform_jar(sdk); jc = javac()
    use_java(jc)
    v = version()
    print("sdk          " + sdk)
    print("build-tools  " + os.path.basename(bt))
    print("javac        " + jc)

    shutil.rmtree(BUILD, ignore_errors=True); os.makedirs(os.path.join(BUILD, "classes"))
    os.makedirs(DIST, exist_ok=True)

    # 1. Java -> class files. Java 8 bytecode keeps d8's desugaring simple and the APK small.
    sources = glob.glob(os.path.join(APP, "java", "**", "*.java"), recursive=True)
    run(jc, "-source", "8", "-target", "8", "-nowarn", "-Xlint:-options",
        "-bootclasspath", jar, "-d", os.path.join(BUILD, "classes"), *sources)

    # 2. class files -> classes.dex
    classes = glob.glob(os.path.join(BUILD, "classes", "**", "*.class"), recursive=True)
    os.makedirs(os.path.join(BUILD, "dex"))
    run(os.path.join(bt, "d8"), "--lib", jar, "--min-api", "24",
        "--output", os.path.join(BUILD, "dex"), *classes)

    # 3. resources -> .flat, then manifest + resources -> an APK with no dex in it yet
    res = icons()
    run(os.path.join(bt, "aapt2"), "compile", "--dir", res, "-o", os.path.join(BUILD, "res.zip"))
    base = os.path.join(BUILD, "base.apk")
    run(os.path.join(bt, "aapt2"), "link", "-o", base, "-I", jar,
        "--manifest", os.path.join(APP, "AndroidManifest.xml"),
        "--min-sdk-version", "24", "--target-sdk-version", "35",
        "--version-code", "1", "--version-name", v,
        "--auto-add-overlay", "-R", os.path.join(BUILD, "res.zip"))

    # 4. slip the dex in beside the resources — the APK is just a zip
    with zipfile.ZipFile(base, "a") as z:
        z.write(os.path.join(BUILD, "dex", "classes.dex"), "classes.dex")

    # 5. align, then sign
    aligned = os.path.join(BUILD, "aligned.apk")
    run(os.path.join(bt, "zipalign"), "-f", "4", base, aligned)

    if args.release:
        out = os.path.join(DIST, "Anzen-bot-%s-release.apk" % v)
        shutil.copyfile(aligned, out)
        print("\n" + out + "   (unsigned — sign it with your own key before shipping)")
    else:
        ks = os.path.expanduser("~/.android/debug.keystore")
        if not os.path.exists(ks):
            os.makedirs(os.path.dirname(ks), exist_ok=True)
            run(shutil.which("keytool") or jc.replace("javac", "keytool"), "-genkeypair",
                "-keystore", ks, "-storepass", "android", "-keypass", "android",
                "-alias", "androiddebugkey", "-keyalg", "RSA", "-keysize", "2048",
                "-validity", "10000", "-dname", "CN=Android Debug,O=Android,C=US")
        out = os.path.join(DIST, "Anzen-bot-%s-debug.apk" % v)
        run(os.path.join(bt, "apksigner"), "sign", "--ks", ks, "--ks-pass", "pass:android",
            "--key-pass", "pass:android", "--ks-key-alias", "androiddebugkey", "--out", out, aligned)
        run(os.path.join(bt, "apksigner"), "verify", "--print-certs", out)
        print("\n" + out)

    if args.install:
        adb = shutil.which("adb") or os.path.join(sdk, "platform-tools", "adb")
        run(adb, "install", "-r", out)
        print("installed — open “Anzen-bot” on the phone and enter the address and token")


if __name__ == "__main__":
    main()
