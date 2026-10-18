#!/usr/bin/env python3
"""Anzen-bot — backend.

A self-hosted agent workspace. A roster of bots, each with its own
model, approval level, memory, skills, tools and voice. Real tool-calling
(OpenAI `tools` API), a real browser the bots can see and click, channels,
routines, a computer panel and a full settings surface.

Everything is unlocked: no tiers, no paywall. Stdlib only for the server; the
browser tool needs Playwright (optional).

Run:  python3 server.py
Env:  PORT, HOST, DATA_DIR, SANDBOX_DIR, ROUTER_URL, ROUTER_KEY, DEFAULT_MODEL, VISION_MODEL
"""
import json, os, re, select, signal, socket, socketserver, struct, subprocess, sys, threading, time, base64, queue, shlex, collections, atexit, urllib.request, urllib.error, uuid, datetime, ipaddress, io, shutil, zipfile, secrets, concurrent.futures, sqlite3, random
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode, urljoin

HERE = os.path.dirname(os.path.abspath(__file__))
# The link out to your relay lives beside this file, and it is imported rather than reimplemented:
# both ends of the link speak the same small WebSocket protocol, and a second copy of it would be a
# second thing to keep in step. Guarded, because the app is whole without it — the phone then has no
# door but the LAN one.
if HERE not in sys.path: sys.path.insert(0, HERE)
try: from relay import anzen_relay as link
except Exception: link = None
VERSION = "1.0.0"
DATA = os.environ.get("DATA_DIR", os.path.join(HERE, "data"))
SANDBOX = os.environ.get("SANDBOX_DIR", os.path.join(HERE, "sandbox"))
# The directory the web shell is served out of. From source it is this one. In a bundle it is not:
# electron-builder puts the frozen backend under `Resources/backend/anzen-backend` — so this module's
# `__file__` lands in its `_internal` — and the shell under `Resources/app`, a sibling two levels up.
# Only the phone's TCP door ever serves a file (the desktop window loads the shell off the disk), and
# that door is the Android companion's way in, so a shell that cannot be found is a companion that
# cannot open. That is exactly what a bare `HERE` gave it: a 404 on `/`.
SHELL = HERE
if not os.path.isfile(os.path.join(SHELL, "index.html")):
    _sib = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(sys.executable)))), "app")
    if os.path.isfile(os.path.join(_sib, "index.html")): SHELL = _sib
MEMDIR = os.path.join(DATA, "memory")
os.makedirs(DATA, exist_ok=True); os.makedirs(SANDBOX, exist_ok=True); os.makedirs(MEMDIR, exist_ok=True)

# ---------------------------------------------------------------- where the API answers
# Bound to loopback (the default, and how the desktop app runs) only this machine can reach the
# API, so the origin rule in H._authorized is enough. Bound to the LAN — `--lan`, or HOST=0.0.0.0 —
# the phone app needs to reach it, and then the origin rule cannot be what guards it: every caller
# arrives with a Host that is whatever address it dialled. An unauthenticated LAN API is remote
# shell access for anyone on the wifi, so a LAN bind also demands the token.
def _is_loopback(h):
    try: return ipaddress.ip_address(h).is_loopback
    except ValueError: return h in ("localhost", "")
HOST_ENV = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", 8093))
FORCED = not _is_loopback(HOST_ENV)      # asked for on the command line / in the environment
LAN_MARK = os.path.join(DATA, "lan")     # ...or asked for from the settings screen
# The desktop app does not talk to itself over a port at all. Given a path here it listens on a Unix
# socket instead — the app's own channel, which no browser can be pointed at and nothing on the
# network can reach — so opening the app never puts the workspace on localhost. The phone is the one
# client that cannot use it, so the TCP listener still opens, separately, when the LAN switch is on.
SOCK = os.environ.get("ANZEN_SOCK")
# The link that lets the phone reach this app from any network — the shape ZCode uses. This machine
# dials *out* to a relay, the phone dials out to the same relay, and the relay pipes the two together.
# Nothing here listens for the internet, so there is no port to find and no router to configure: that
# is the difference between this and a tunnel, which exposes this machine rather than meeting it.
RELAY_SECRET_PATH = os.path.join(DATA, "relay_secret")
def _mint_token(path):
    """A shared secret that stands between a door and this app: read if it is there, else minted on
    first use and never rotated on its own — a client that has been set up must keep working."""
    try:
        t = open(path).read().strip()
        if t: return t
    except OSError: pass
    t = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.write(fd, t.encode()); os.close(fd)
    return t
def relay_secret(): return _mint_token(RELAY_SECRET_PATH)
def lan_ip():
    """This machine's address on the local network, for the URL you type into the phone. The
    socket is never connected — this only makes the OS pick the interface that reaches the LAN."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1)); return s.getsockname()[0]
    except OSError: return "127.0.0.1"
    finally: s.close()
def _bind():
    """Where to listen. An explicit HOST or `--lan` wins, because that is an operator's decision;
    otherwise the marker file the settings screen writes decides, and absent that it is loopback.

    The phone's listener is bound to this machine's LAN address and not to the wildcard. The
    wildcard answers on 127.0.0.1 too, and the app's own channel is a Unix socket precisely so that
    no port on this machine serves the workspace. Binding the very address the phone is handed
    keeps the two in step; with no LAN address there is nothing for the phone to reach, so it
    falls back to loopback and the switch reads back as off."""
    if FORCED: return HOST_ENV
    return lan_ip() if os.path.exists(LAN_MARK) else "127.0.0.1"
HOST = _bind()
LAN = not _is_loopback(HOST)
TOKEN_PATH = os.path.join(DATA, "access_token")
def lan_token(): return _mint_token(TOKEN_PATH)

# ---------------------------------------------------------------- connection config
CFG_PATH = os.path.join(DATA, "config.json")
def _read_cfg(path):
    """config.json, or None when it is absent or unreadable.

    A corrupt one used to be a bare `json.load` at import: one bad byte and the app came up with a
    window and no API at all. Now it is moved aside and the config is rebuilt from the environment,
    so the app always starts and the old file is still there to look at."""
    try: return json.load(open(path))
    except FileNotFoundError: return None
    except Exception as e:
        try:
            bad = "%s.corrupt-%s" % (path, time.strftime("%Y%m%d-%H%M%S"))
            os.replace(path, bad); print("could not read %s (%s); kept it as %s" % (path, e, bad), flush=True)
        except Exception: pass
        return None
CFG = _read_cfg(CFG_PATH)
if CFG is None:                         # first run, or a config we could not read: build from env
    CFG = {"router": os.environ.get("ROUTER_URL", "http://127.0.0.1:11434/v1"),
           "key": os.environ.get("ROUTER_KEY", ""),
           "default_model": os.environ.get("DEFAULT_MODEL", "llama3.1"),
           "vision_model": os.environ.get("VISION_MODEL", ""),
           "models": (os.environ.get("MODELS", "").split(",") if os.environ.get("MODELS") else [])}
    json.dump(CFG, open(CFG_PATH, "w"), indent=2)
ROUTER = CFG["router"].rstrip("/"); KEY = CFG.get("key", "")
DEFAULT_MODEL = CFG.get("default_model", "llama3.1")
VISION_MODELS = [m.strip() for m in (CFG.get("vision_model") or DEFAULT_MODEL).split(",") if m.strip()]
# Router image generation: an image-capable chat model returns the picture inline as a data URL.
# OFF by default -- it spends PADUKA's API tokens. The default free route drives a real site in the
# browser (browser_open / browser_type / browser_save) and costs nothing.
#
# The router advertises 8 models with `capabilities.imageOutput`, but only the two below actually
# route -- verified by calling each advertised model: these two answer with a picture, text-to-image
# and image-to-image alike. The six in IMAGE_MODEL_DEAD answer HTTP 400 "route config not found" or
# HTTP 503 "unknown model" however they are called, so a config left on one of them draws nothing.
# Both lists live here so that cannot happen: the fallbacks are always in the list to be tried.
IMAGE_MODEL_FALLBACKS = ["inf/gemini-2.5-flash-image", "inf/cb/gemini-2.5-flash-image"]
IMAGE_MODEL_DEAD = {"inf/gemini-3.0-pro-image", "inf/cb/gemini-3.0-pro-image",
                    "inf/gemini-3.1-flash-image", "inf/cb/gemini-3.1-flash-image",
                    "inf/gemini-2.5-flash-image-microusd", "inf/gemini-image-2"}
def _image_models(cfg_value):
    """What gen_image tries, in order: the configured model(s) that are alive, then the fallbacks.
    Dead ids are dropped from both, so a config left on a dead route still draws."""
    want = [m.strip() for m in (cfg_value or "").split(",") if m.strip()]
    return [m for m in want if m not in IMAGE_MODEL_DEAD] + \
           [m for m in IMAGE_MODEL_FALLBACKS if m not in want]
IMAGE_MODELS = _image_models(CFG.get("image_model"))

_lock = threading.Lock()
OUT_UA = "AnzenBot/1.0"   # WAFs (e.g. Cloudflare 1010) 403 the default Python-urllib signature
def fetch_models(timeout=30):
    """Ask the configured router/API key which models it actually serves."""
    req = urllib.request.Request(ROUTER + "/models", headers={"Authorization": "Bearer " + KEY, "User-Agent": OUT_UA})
    d = json.load(urllib.request.urlopen(req, timeout=timeout))
    items = d.get("data") or d.get("models") or []
    return sorted({(m.get("id") if isinstance(m, dict) else str(m)) for m in items if m})
def save_models(ids):
    """Persist the model list so it survives restarts and shows in every dropdown."""
    CFG["models"] = sorted(set(ids)); _save_json(CFG_PATH, CFG)
    return CFG["models"]
def _load_json(path, default):
    """A JSON file, or `default`.

    A file that is *missing* and a file that will not *parse* are different things: the first is a
    first run, the second is data the caller is about to overwrite with defaults. The second is moved
    aside and reported, so seeding defaults never silently eats the user's roster."""
    try: return json.load(open(path))
    except FileNotFoundError: return default
    except Exception as e:
        try:
            bad = "%s.corrupt-%s" % (path, time.strftime("%Y%m%d-%H%M%S"))
            os.replace(path, bad); print("could not read %s (%s); kept it as %s" % (path, e, bad), flush=True)
        except Exception: pass
        return default
def _save_json(path, obj, indent=2):
    with _lock:
        tmp = path + ".tmp"; json.dump(obj, open(tmp, "w"), indent=indent); os.replace(tmp, path)
def _migrate_image_model():
    """A saved image_model naming a route the router does not serve is the reason the tool drew
    nothing, so move it to a live one and write that back. Runs once at startup: the value is no
    longer dead afterwards, so a second call does nothing -- and a config we cannot write (a
    read-only file, a full disk) is left as it is rather than stopping the app from coming up."""
    if CFG.get("image_model") not in IMAGE_MODEL_DEAD: return
    CFG["image_model"] = IMAGE_MODEL_FALLBACKS[0]
    try: _save_json(CFG_PATH, CFG)
    except Exception as e: print("could not rewrite %s (%s)" % (CFG_PATH, e), flush=True)
_migrate_image_model()
def save_connection(patch):
    """Update the router connection from the AI model tab and re-aim the live globals.
    A blank key means 'keep the saved one' so saving other fields never wipes it."""
    global ROUTER, KEY, DEFAULT_MODEL, VISION_MODELS
    if (patch.get("router") or "").strip(): CFG["router"] = patch["router"].strip()
    if (patch.get("key") or "").strip(): CFG["key"] = patch["key"].strip()
    if (patch.get("default_model") or "").strip(): CFG["default_model"] = patch["default_model"].strip()
    if "vision_model" in patch: CFG["vision_model"] = (patch.get("vision_model") or "").strip()
    _save_json(CFG_PATH, CFG)
    ROUTER = CFG["router"].rstrip("/"); KEY = CFG.get("key", "")
    DEFAULT_MODEL = CFG.get("default_model", "llama3.1")
    VISION_MODELS = [m.strip() for m in (CFG.get("vision_model") or DEFAULT_MODEL).split(",") if m.strip()]
    return {"ok": True, "router": ROUTER, "key_set": bool(KEY),
            "default_model": DEFAULT_MODEL, "vision_model": CFG.get("vision_model", "")}

# ---------------------------------------------------------------- app settings
SET_PATH = os.path.join(DATA, "settings.json")
# The one list of text sizes the UI offers, in px. Every size in index.html is its designed value
# times (chosen / BASE_FONT_PX), so this single base scales the whole interface. Kept here rather
# than in app.js so the Appearance panel and the font_scale migration can never disagree.
BASE_FONT_PX = 14.5
FONT_SIZES = (12.5, 13.5, 14.5, 15.5, 16.5, 17.5, 18.5)
def nearest_size(px):
    return min(FONT_SIZES, key=lambda s: abs(s - px))
DEFAULT_SETTINGS = {
  "connectors": [
    # Google connectors carry three credentials (OAuth client id, secret, refresh token); every
    # other kind carries one token. All are write-only — see settings_public.
    {"id": "gmail",   "name": "Gmail",   "enabled": False, "client_id": "", "client_secret": ""},
    {"id": "slack",   "name": "Slack",   "enabled": False},
    {"id": "github",  "name": "GitHub",  "enabled": False},
    {"id": "notion",  "name": "Notion",  "enabled": False},
    {"id": "linear",  "name": "Linear",  "enabled": False},
    {"id": "gdrive",  "name": "Google Drive", "enabled": False, "client_id": "", "client_secret": ""},
    {"id": "calendar","name": "Google Calendar", "enabled": False, "client_id": "", "client_secret": ""},
    {"id": "webhook", "name": "Webhooks", "enabled": False},
  ],
  "mcp": [],
  "decision": {"enabled": False, "provider": "local", "key": "", "jobs": {"rooms": False, "tools": False, "clicks": False}},
  "voice": {"enabled": False, "provider": "browser", "voice_id": "", "auto": False, "key": ""},
  # The link out to your relay: `url` is where your relay answers (`https://anzen.example.com`), and
  # `on` is whether this app is dialled out to it. The secret is a file, not a setting — see
  # RELAY_SECRET_PATH — so a settings screen that is read back to a browser never carries it.
  "relay": {"on": False, "url": ""},
  # font_size is the px base the whole interface scales from; font is which system stack it uses.
  # (A save from before this may still carry `font_scale` — load_settings converts it once.)
  "appearance": {"theme": "dark", "accent": "#7C5CFF", "density": "comfortable",
                 "font_size": BASE_FONT_PX, "font": "system", "bubbles": "modern"},
  "api_keys": {"composio": "", "boat": "", "elevenlabs": "", "fish": "", "xai": ""},
  # limit is the token budget for one request; 0 means "follow the model's own context window".
  # max_steps is how many model calls one turn may make — see DEFAULT_MAX_STEPS for why it is generous.
  # max_seconds is an optional hard cap on how long a turn may run; 0, the default, is no cap at all
  # (see DEFAULT_TURN_SECONDS). 0 means "use the default" for both.
  # model_retries is how many times one step tries again after an attempt that came back with
  # nothing, and model_stall_seconds how long one attempt may go silent before it counts as one — see
  # DEFAULT_MODEL_RETRIES / DEFAULT_MODEL_STALL_SECONDS / MODEL_FAIL_SECONDS. 0 means "use the
  # default" for both.
  "context": {"limit": 0, "compress": True, "max_steps": 0, "max_seconds": 0,
              "model_retries": 0, "model_stall_seconds": 0},
  # port is the one place the debug endpoint is named; the launch command and the CDP URL are both
  # derived from it, so the app cannot connect to a port the launch never opened.
  # How the bots browse. "own" launches a throwaway browser — fast, but logged out. "cdp" attaches
  # to ZenPilot (or any browser) already running on the debug port. "profiles" launches a browser
  # with a *saved* profile per account: the cookies live in a folder on disk, so you sign in once by
  # hand and every later run is already signed in. `accounts` is the list you make in the UI — a name
  # and the sites it handles — and it is what sends a site to the account that owns it. `headless` is
  # how the *bots'* browsers run; signing in always opens a window, because that is the one thing
  # that cannot be done without one. `channel` is which browser to launch: "auto" prefers a real
  # Chrome-family browser installed on this machine, because Google refuses to sign anyone in on the
  # Chromium Playwright ships — see browser_channel().
  "browser": {"mode": "own", "port": 9222, "target_url": "", "profile": "default",
              "accounts": [], "headless": False, "channel": "auto"},
  "media": {"router_image": False},
  # Notification chimes. The browser synthesises them, so all that is kept is the switch and the
  # level — there is no audio file to ship, fetch or license.
  "sound": {"on": True, "volume": 0.5},
  # How your own messages are labelled in a transcript. A user message has no bot to name it, so it
  # wears this instead; the client falls back to "Client" when it is unset or blank.
  "user_name": "Client",
}
def _load_settings_raw():
    s = _load_json(SET_PATH, None)
    if not s:
        _save_json(SET_PATH, DEFAULT_SETTINGS); return json.loads(json.dumps(DEFAULT_SETTINGS))
    # The text size used to be a bare multiplier (font_scale); it is now a px base (font_size).
    # Convert a save that predates the change, or everyone's "Large" would quietly become "Normal"
    # once the new default lands in it. Checked before the setdefault loop fills font_size in.
    ap = s.get("appearance")
    if isinstance(ap, dict) and "font_size" not in ap:
        ap["font_size"] = nearest_size(BASE_FONT_PX * (ap.get("font_scale") or 1))
    for k, v in DEFAULT_SETTINGS.items():
        if isinstance(v, dict) and isinstance(s.get(k), dict):
            for kk, vv in v.items(): s[k].setdefault(kk, json.loads(json.dumps(vv)))  # new sub-settings appear on upgrade
        else:
            s.setdefault(k, json.loads(json.dumps(v)))
    # `engines` was a decorative list of engine rows with on/off toggles that nothing ever read —
    # every turn goes to the router configured above. Retired rather than left in place, so a stale
    # save cannot keep showing a switch that does nothing. (Same treatment as launch_cmd/cdp_url.)
    s.pop("engines", None)
    conns = s.get("connectors")     # connectors gained token/base_url later — migrate old saves
    if isinstance(conns, list) and conns:
        by = {x.get("id"): x for x in conns}
        for d in DEFAULT_SETTINGS["connectors"]:
            e = by.setdefault(d["id"], json.loads(json.dumps(d)))
            e.setdefault("name", d["name"]); e.setdefault("token", ""); e.setdefault("base_url", "")
            if CONNECTORS.get(d["id"], {}).get("auth") == "google":   # only Google needs the OAuth client
                e.setdefault("client_id", ""); e.setdefault("client_secret", "")
        s["connectors"] = list(by.values())
    # The debug endpoint used to be named twice — a CDP URL and a launch command, each carrying its
    # own port — so the app could connect to one the launch never opened (ECONNREFUSED on a port
    # nothing listened on). The port is now the single source of truth; adopt whichever port those
    # two actually named, then retire them so they can never disagree again.
    br = s.get("browser")
    if isinstance(br, dict):
        for src in (br.get("launch_cmd") or "", br.get("cdp_url") or ""):
            m = re.search(r"remote-debugging-port=(\d{2,5})|:(\d{2,5})(?:\D|$)", src)
            if m:
                p = int(m.group(1) or m.group(2))
                if 1 <= p <= 65535: br["port"] = p
                break
        br.pop("launch_cmd", None); br.pop("cdp_url", None)
    return s

# Settings are read on nearly every request, so the parsed, migrated dict is cached and handed out as
# a copy: a caller that mutates what it read (then saves it through `save_settings`) cannot corrupt
# what the next reader sees. Keyed on the path so a test that redirects SET_PATH starts clean.
_SET = {"path": None, "d": None}
_SET_LOCK = threading.RLock()
def load_settings():
    with _SET_LOCK:
        if _SET["d"] is None or _SET["path"] != SET_PATH:
            _SET["d"] = _load_settings_raw(); _SET["path"] = SET_PATH
            sync_model_policy(_SET["d"])     # the model client reads the retry policy as globals
        return json.loads(json.dumps(_SET["d"]))
def save_settings(s):
    """Write settings through the cache, so the next `load_settings` sees this save and not the file
    it replaced."""
    with _SET_LOCK: _SET["d"] = s; _SET["path"] = SET_PATH
    _save_json(SET_PATH, s)
    sync_model_policy(s)

def _public_connector_url(url):
    """Expose only a credential-free HTTPS base URL to the browser."""
    try: u = urlparse((url or "").strip())
    except ValueError: return ""
    if u.scheme != "https" or not u.hostname or u.username or u.password or u.query or u.fragment:
        return ""
    return url.strip()

def settings_public(s):
    """The shape the browser is allowed to see: connected flags, never tokens or keys."""
    pub = json.loads(json.dumps(s))
    pub["api_keys"] = {k: bool(v) for k, v in s.get("api_keys", {}).items()}   # write-only
    for sec in ("voice", "decision"):                                        # provider keys too
        if isinstance(pub.get(sec), dict) and "key" in pub[sec]:
            pub[sec]["key"] = bool(s[sec].get("key"))
    pub["connectors"] = [{"id": x.get("id"), "name": x.get("name"),
                          "connected": connector_connected(s, x.get("id")),
                          "base_url": _public_connector_url(x.get("base_url", "")),
                          "auth": CONNECTORS.get(x.get("id"), {}).get("auth", "bearer"),
                          # Google needs three credentials. The UI may learn only *whether* each is
                          # set, never what it is — the same write-only rule as the API keys above.
                          "has_client": bool((x.get("client_id") or "").strip()),
                          "has_secret": bool((x.get("client_secret") or "").strip())}
                         for x in s.get("connectors", [])]
    # An MCP server may carry env vars (a local server's token) or request headers (a remote one's
    # key). Those are credentials, so the panel is told which names are set and never their values —
    # the same write-only rule as the API keys above. A save that omits them keeps the stored ones.
    pub["mcp"] = [{"id": m.get("id"), "name": m.get("name"), "kind": m.get("kind"),
                   "target": m.get("target"), "enabled": bool(m.get("enabled", True)),
                   "env_keys": sorted((m.get("env") or {}).keys()),
                   "header_keys": sorted((m.get("headers") or {}).keys())}
                  for m in (s.get("mcp") or []) if isinstance(m, dict)]
    return pub

# ---------------------------------------------------------------- bots
BOTS_PATH = os.path.join(DATA, "bots.json")
# The reply language follows the user, and English is the default. This used to name Indonesian
# first and only, which read as "reply in Indonesian" and primed the model toward it — an English
# question would come back in Indonesian. Stated English-first, with another language only as the
# condition it actually is, so the bot never switches on its own.
LANG = ("Answer in the language of the user's most recent message. English is the default: when they "
        "write in English, answer in English. Use another language only when their message is in that "
        "language — an Indonesian message gets an Indonesian answer, and nothing else does. If a "
        "message mixes languages, answer in English. Never switch language on your own. Code, commands, "
        "filenames and identifiers are ALWAYS in English.")
TOOL_DOC = ("\n\nYou have real tools (function calling). Use them to actually DO the work, then call "
            "`finish` with a short, concrete report of what you did and the real output. Never claim a "
            "result you did not get from a tool. If the message only needs an answer you already know, "
            "just answer it — no tool call and no `finish` are needed. Work in verifiable steps, but do "
            "not spend a step on each probe: `list_files` shows a whole folder and `read_file` reads a "
            "file, in one call each."
            # This used to tell a bot to "chain related commands into a single call" — and the shell
            # gate then read that chain as risky and raised an approval card. Nobody answers a card on
            # a greeting, so the turn sat for the whole 30s deadline, was denied, and spent two more
            # model calls explaining it: `pwd && ls -la && cat *.md` on "hi" was a 42s turn. The two
            # halves now say the same thing.
            "\n\n`run_shell` runs exactly ONE plain read-only command. Chaining (`&&`, `|`, `;`, `>`, "
            "globs) is not read-only, so below Full access it raises an approval card and the turn "
            "waits on it — the slowest thing that can happen to a simple question."
            "\n\nFor anything on a web page, use the browser tools — never drive a browser through "
            "`run_shell`. No `curl` for a page, no hand-written CDP/websocket script, no saved helper "
            "script: those cost a step each and read less than the page really holds. `browser_open` "
            # Where a site opens is decided by the browsing mode, which is read live and spelled out
            # under “Browsing” below — so this points there instead of naming a mechanism. It used to
            # name the Zen Pilot profile outright, which is a lie in saved-profiles mode and sent a
            # bot off to launch Zen Pilot by hand for two minutes before it gave up and used the tool.
            "the site's own URL (which sites open already signed in, and which anonymously, is set out "
            "under “Browsing” below), then do the work "
            "with `browser_eval`, which runs your JavaScript "
            "in the live page. One eval that finds, clicks, fills and submits replaces a step per poke "
            "— read a whole list, scroll, and act in a single call. `browser_read` gives the page text "
            "when you just need to look.")

DEFAULT_BOTS = [
 {"id":"producer","name":"Producer","title":"Chief of Staff","role":"Plans, delegates, coordinates the team",
  "color":"purple","model":DEFAULT_MODEL,"approval":"approve","memory":True,"voice":"",
  "instructions":"You are the team lead. Do NOT do hands-on work yourself. Begin with a short "
  "one-or-two line plan, then DELEGATE each task with `delegate` (at most once per teammate per turn), then "
  "call `finish`.",
  "tools_allow":None,"skills":["planning","delegation","writing"],"hidden":False,"pinned":True},
 {"id":"researcher","name":"Researcher","title":"Research","role":"Reads the sandbox and the web, gathers facts",
  "color":"blue","model":DEFAULT_MODEL,"approval":"ask","memory":True,"voice":"",
  "instructions":"Gather concrete facts with the shell and the real browser "
  "(open, read, click, and browser_see to look at a page). Summarise with evidence; say what you verified vs guessed.",
  "tools_allow":None,"skills":["web","research","summarise"],"hidden":False,"pinned":False},
 {"id":"builder","name":"Builder","title":"Engineering","role":"Writes code and runs commands",
  "color":"green","model":DEFAULT_MODEL,"approval":"auto","memory":True,"voice":"",
  "instructions":"Write and run code in the shared sandbox. Prefer small, tested steps. "
  "Show exact commands and their real output, then report what you built.",
  "tools_allow":None,"skills":["coding","shell","testing"],"hidden":False,"pinned":False},
 {"id":"qa","name":"QA","title":"Quality","role":"Tests the work, finds bugs",
  "color":"orange","model":DEFAULT_MODEL,"approval":"ask","memory":True,"voice":"",
  "instructions":"Independently verify what the team produced: run it, check edge cases, try to "
  "break it, use the browser for web-facing work. Report PASS/FAIL with exact command and real output. Never rubber-stamp.",
  "tools_allow":None,"skills":["testing","verification"],"hidden":False,"pinned":False},
 {"id":"ops","name":"Ops","title":"Operations","role":"Deploys, monitors, keeps the runtime healthy",
  "color":"yellow","model":DEFAULT_MODEL,"approval":"auto","memory":True,"voice":"",
  "instructions":"Handle running services, deployment, monitoring and scheduled jobs. Check "
  "before you change; report real status, never invented status.",
  "tools_allow":None,"skills":["deploy","monitoring"],"hidden":False,"pinned":False},
]
# Each bot's face in the sidebar: one emoji on its colour. Bare id -> emoji; anything
# unknown falls back to the robot. Clients render it, so it lives in data, not in app.js.
BOT_EMOJI = {"producer": "🎩", "researcher": "🔍", "builder": "🛠️", "qa": "🧪", "ops": "⚙️"}
for _b in DEFAULT_BOTS: _b["emoji"] = BOT_EMOJI.get(_b["id"], "🤖")
# The shipped briefs used to name the bot and list its teammates inline. Those names now come live
# from the bot record and its room, so a bot left on the old text is moved to the current one — a
# brief the user edited is not on this list and is left alone.
_STALE_BRIEFS = [
 "You are the Producer and team lead. Do NOT do hands-on work yourself. Begin with a short one-or-two line "
 "plan, then DELEGATE each task with `delegate` (at most once per teammate per turn), then call `finish`. "
 "Teammates: Researcher (web+sandbox), Builder (code), QA (tests), Ops (services).",
 "You are the Researcher. Gather concrete facts with the shell and the real browser (open, read, click, and "
 "browser_see to look at a page). Summarise with evidence; say what you verified vs guessed.",
 "You are the Builder. Write and run code in the shared sandbox. Prefer small, tested steps. Show exact "
 "commands and their real output, then report what you built.",
 "You are QA. Independently verify what the team produced: run it, check edge cases, try to break it, use "
 "the browser for web-facing work. Report PASS/FAIL with exact command and real output. Never rubber-stamp.",
 "You are Ops. Handle running services, deployment, monitoring and scheduled jobs. Check before you change; "
 "report real status, never invented status.",
]
def _slug(s, fallback):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or fallback

def _fill(x, k, v):
    """A field the record left out, or left null.

    `setdefault` only covers the absent case, and a key written as an explicit `null` — which is what
    a client serialising an unset value sends — is not absent. So a room with `"members": null`
    passed the loader and then 500'd on the next bot delete, and a bot with `"instructions": null`
    failed on every turn: present, but nothing a reader could use. Only `None` counts as unfilled, so
    a deliberate `False`, `0` or `""` is left exactly as written."""
    if x.get(k) is None: x[k] = v

def _fill_id_name(x, fallback, taken):
    """An id and a name for a record the file left without them.

    Both are read unguarded all over the app — `boot()` names a chat after the record, the drawer
    prints it, `bot_by_id` matches on the id — so one nameless record in bots.json or channels.json
    used to raise KeyError inside `boot()` and stop the backend from starting at all. The id is
    derived from the name (the same slug rule the create endpoints use) and made unique against the
    ids already claimed, so two rooms called the same cannot end up sharing a chat.

    An id the record supplied is its own and is never the one that yields: it names a session and a
    logo or avatar file on disk, so renaming it would orphan both. `taken` therefore arrives
    pre-seeded with every explicit id in the file, and only a derived id steps aside."""
    own = x.get("id")
    if own:
        taken.add(own)
        x["name"] = x.get("name") or own.replace("-", " ").title()
        return x
    base = _slug(x.get("name"), fallback)
    x["id"] = base
    n = 2
    while x["id"] in taken: x["id"] = "%s-%d" % (base, n); n += 1
    taken.add(x["id"])
    x["name"] = x.get("name") or x["id"].replace("-", " ").title()
    return x

def _norm_bots(b):
    """Every field a bot record is read for, filled in. One definition, shared by the loader, the
    create endpoint and the team importer: those drifting apart is exactly how a record got into the
    file with no `name`, and then stopped the app from booting."""
    known = CFG.get("models") or []
    taken = {x["id"] for x in b if x.get("id")}
    for x in b:
        x.pop("mascot", None)   # avatars are emoji-on-colour now; mascot was the old key
        _fill_id_name(x, "bot", taken)
        _fill(x, "title", "Teammate"); _fill(x, "role", ""); _fill(x, "color", "blue")
        _fill(x, "approval", "ask"); _fill(x, "memory", True); _fill(x, "voice", "")
        _fill(x, "hidden", False); _fill(x, "pinned", False); _fill(x, "skills", [])
        _fill(x, "tools_allow", None)
        _fill(x, "instructions", "You are " + x["name"] + ".")
        _fill(x, "emoji", BOT_EMOJI.get(x["id"], ""))
        _fill(x, "face", "")   # blank = the client derives a species from the id
        # The look the avatar editor edits: an outfit and an accessory the client draws, the
        # version of an uploaded avatar (0 = none, so the drawn face shows), and the generated
        # whole-bot picture from the Bot faces section ("" = none, so the drawn bot shows).
        _fill(x, "outfit", ""); _fill(x, "accessory", ""); _fill(x, "avatar", 0)
        _fill(x, "genface", "")
        # A record with no model, or one the current router does not serve, would 404 on every turn —
        # and `_agent_loop` reads `bot["model"]` unguarded, so a missing one is a TypeError mid-turn.
        _fill(x, "model", DEFAULT_MODEL)
        if known and x["model"] not in known: x["model"] = DEFAULT_MODEL
        if x.get("instructions") in _STALE_BRIEFS:
            d = next((d for d in DEFAULT_BOTS if d["id"] == x.get("id")), None)
            if d: x["instructions"] = d["instructions"]
    return b

def load_bots():
    b = _load_json(BOTS_PATH, None)
    if not b:
        _save_json(BOTS_PATH, DEFAULT_BOTS); return json.loads(json.dumps(DEFAULT_BOTS))
    return _norm_bots(b)
def save_bots(b): _save_json(BOTS_PATH, b)
def bot_by_id(bots, bid): return next((x for x in bots if x.get("id") == bid), None)

# ---------------------------------------------------------------- channels
CH_PATH = os.path.join(DATA, "channels.json")
DEFAULT_CHANNELS = [
  {"id":"company","name":"Company","members":["producer","researcher","builder","qa","ops"],
   "mode":"lead","lead":"producer","instructions":"","folder":""},
]
def _norm_channels(c):
    """Every field a room record is read for, filled in — the same shared definition the create
    endpoint and the team importer use. `members` and `lead` are what the room's own turns iterate,
    so a room the file left without them used to fail later, inside a turn, instead of at boot."""
    taken = {x["id"] for x in c if x.get("id")}
    for x in c:
        _fill_id_name(x, "room", taken)
        _fill(x, "members", [])
        _fill(x, "mode", "lead")
        _fill(x, "lead", (x["members"] or ["producer"])[0])
        _fill(x, "instructions", ""); _fill(x, "folder", ""); _fill(x, "pinned", False)
        # The colour of the room's letter avatar. Both clients default it, so this is only what the
        # row is drawn with before the user picks one — but it is a field they read, so it is filled.
        _fill(x, "color", "")
        # The browser accounts this room's bots use, as rows of {name, sites}. Empty means "the
        # machine-wide list", so a room that never set one keeps behaving exactly as it always did.
        x["browser"] = _norm_accounts(x.get("browser"))
    return c

def _norm_accounts(a):
    """Account rows reduced to the two strings a route is made of, and nothing else. The rows are
    user text that names a profile folder, so a client that echoes one back must not be able to
    store anything under a name the routing then reads."""
    out = []
    for x in a if isinstance(a, list) else []:
        if not isinstance(x, dict): continue
        n = (x.get("name") or "").strip()
        if n: out.append({"name": n, "sites": (x.get("sites") or "").strip()})
    return out

def load_channels():
    c = _load_json(CH_PATH, None)
    if not c:
        _save_json(CH_PATH, DEFAULT_CHANNELS); return json.loads(json.dumps(DEFAULT_CHANNELS))
    return _norm_channels(c)
def save_channels(c): _save_json(CH_PATH, c)
def channel_by_id(chs, cid): return next((x for x in chs if x.get("id") == cid), None)

def reorder(seq, ids, key=lambda x: x.get("id")):
    """Put `seq` in the order `ids` names. Anything the caller did not name keeps its relative
    place, after the ones it did — so a list from a stale client (a row added on the phone since
    that window last read config) can reorder the sidebar without ever dropping a bot."""
    order = {v: i for i, v in enumerate(ids)}
    return sorted(seq, key=lambda x: order.get(key(x), len(order)))

def resolve_session(sid, bot_field, chs, bots):
    """A session id -> (channel, solo bot). One bot can live under several companies, so a chat
    with it is scoped: `<channel>/<bot>` means that bot, inside that company — its own transcript
    and its own repo. A bare channel id is the room; a bare bot id has no company. An id naming a
    company the bot is not in resolves to nothing, so a stale scope never picks up a repo."""
    c = channel_by_id(chs, sid)
    if c: return c, None
    pre, sep, suf = (sid or "").partition("/")
    if sep:
        c = channel_by_id(chs, pre)
        if c and bot_by_id(bots, suf) and suf in (c.get("members") or []): return c, suf
        return None, None
    return None, bot_field or sid

def _computer_scope(sid):
    """(owners, actor) for a chat's Computer panel.

    `owners` is the set of bots whose screen this chat is allowed to show, or None for "do not scope"
    — no chat was named, so there is nothing to compare a screen against. A room's screen belongs to
    any of its members, because the member is who actually browses; the room itself never does.

    `actor` is the one bot a page opened from the panel's own box belongs to: a room's lead, since
    the lead is the member that acts on what you tell the room.

    Scoping is the whole point: one browser serves every chat, so without this the panel showed
    whatever screen another chat's bot had open — you looked at chat B and watched chat A's work."""
    if not sid: return None, ""
    ch, solo = resolve_session(sid, None, load_channels(), load_bots())
    if solo: return {solo}, solo
    if ch:
        mem = set(ch.get("members") or [])
        lead = ch.get("lead") if ch.get("lead") in mem else (sorted(mem)[0] if mem else "")
        return mem, lead
    return set(), ""

def _file_root(sid):
    """(root, label) for a chat's Files panel: the repo that chat works in, or the shared sandbox.

    A chat with no repo is not an error — the sandbox is a real working dir and the panel should
    show it rather than nothing. The label stays the chat's own name even then, so the panel's
    header says which chat you are looking at instead of the folder that happens to back it."""
    try:
        ch, _solo = resolve_session(sid, None, load_channels(), load_bots())
        root = resolve_folder(ch.get("folder")) if ch else None
        return (root or os.path.realpath(SANDBOX)), ((ch.get("name") or ch.get("id")) if ch else "sandbox")
    except Exception:
        return os.path.realpath(SANDBOX), "sandbox"

def _file_path(sid, rel):
    """(absolute path, error) for a path relative to that chat's repo. Never raises."""
    try:
        root, _label = _file_root(sid)
        raw = str(rel or "").strip()
        p = os.path.realpath(os.path.join(root, raw) if raw else root)
        if p != root and not p.startswith(root + os.sep):
            return None, "that path is outside this chat's repo"
        # The store `run_shell` refuses, refused here by the same rule: a typed or symlinked path
        # into it must never become a listing or an "open", whatever the client asks for.
        if names_secrets(p): return None, SECRET_REFUSAL
        return p, ""
    except Exception:
        return None, "that path is outside this chat's repo"

# The editors the "Open with" menu offers on macOS, in the order the menu shows them.
FILE_APPS = (
    ("/Applications/Visual Studio Code.app", "Visual Studio Code"),
    ("/Applications/Cursor.app", "Cursor"),
    ("/Applications/Sublime Text.app", "Sublime Text"),
    ("/Applications/Zed.app", "Zed"),
    ("/System/Applications/TextEdit.app", "TextEdit"),
    ("/System/Applications/Utilities/Terminal.app", "Terminal"),
)
def file_apps():
    """The editors this machine actually has. The menu only lists installed ones, and the
    `with:<name>` action is checked against this same list, so a client can never name an
    arbitrary application for the server to launch."""
    try:
        if sys.platform != "darwin":
            return [{"name": "VS Code", "how": "with:code"}] if shutil.which("code") else []
        home = os.path.expanduser("~")
        found = []
        for path, name in FILE_APPS:
            # The user's own Applications folder holds the same bundles under the same names.
            if (os.path.exists(path)
                    or os.path.exists(os.path.join(home, "Applications", os.path.basename(path)))):
                found.append({"name": name, "how": "with:" + name})
        return found
    except Exception:
        return []

def effective_model(st, ch, solo, bots):
    """The model that will actually answer a chat: the session's own pick if the user set one on
    the fly, else the bot's configured model. A room has no single bot, so it answers as its lead."""
    if st.get("model"): return st["model"]
    bid = solo or (ch.get("lead") if ch else None)
    b = bot_by_id(bots, bid) if bid else None
    return (b or {}).get("model") or DEFAULT_MODEL

def approval_level(chat_level, bot_level, in_channel=False):
    """The level that actually runs for one bot in one chat — the sibling of `effective_model`.

    A channel has exactly one level and it is the channel's. A room is one workspace with one rule,
    so inside it a member's own default is neither consulted nor shown: pick Full access on the room
    and every member runs free, pick Ask and every member asks. That is the whole point — the
    alternative is a room that says one thing on its chip while each member quietly does another.

    A bot's own level means something only in a chat with that bot on its own, where it is the
    fallback when the chat has no level of its own. There **Full access is a grant a chat level may
    not revoke**, because the Bots list shows it and a list that reads "Full access" while the bot
    still stops to ask is exactly the disagreement it looks like."""
    if in_channel: return chat_level or "ask"
    if bot_level == "full": return "full"
    return chat_level or bot_level or "ask"

# ---------------------------------------------------------------- skills catalog
SKILLS = [
 {"id":"planning","name":"Planning","desc":"Break a goal into ordered steps and owners."},
 {"id":"delegation","name":"Delegation","desc":"Hand tasks to the right teammate with clear acceptance."},
 {"id":"writing","name":"Writing","desc":"Clear, concise prose; no filler."},
 {"id":"web","name":"Web browsing","desc":"How to drive a real site in few steps. Read this before a browsing job."},
 {"id":"research","name":"Research","desc":"Gather facts from several sources, cite evidence, and return lists as lists."},
 {"id":"summarise","name":"Summarising","desc":"Condense long material without losing the point."},
 {"id":"coding","name":"Coding","desc":"Write small, tested, readable programs."},
 {"id":"shell","name":"Shell","desc":"Use the shell safely and read real output."},
 {"id":"testing","name":"Testing","desc":"Write and run checks that actually fail on a bug."},
 {"id":"verification","name":"Verification","desc":"Independently reproduce a claim before accepting it."},
 {"id":"deploy","name":"Deployment","desc":"Ship services and verify they are up."},
 {"id":"monitoring","name":"Monitoring","desc":"Watch health and report real status."},
]

# The built-ins above used to be name and description only, so a bot that did the right thing and
# called `use_skill("web")` before a browsing job got "(no extended guidance)" back and improvised —
# which is how a bot asked for posts with 30+ replies spent a whole turn poking at a search box.
# The guidance lives here rather than in a SKILL.md under data/skills because that directory is the
# *user's* shelf (installed skills are unzipped there); these are the shipped ones and they belong
# with the tools they describe. Read on demand, so they cost the prompt nothing.
BUILTIN_BODIES = {
 "web": (
  "Driving a real site is mostly about spending as few steps as possible: every round trip is one, and\n"
  "a turn has a step limit. Three rules, in order.\n\n"
  "1. Go by URL, not by clicking. A search *has* a URL — /search?q=…, /explore/tags/…, ?s=… — and\n"
  "   `browser_open` on it lands you on the results in one step, where a search box costs type, click\n"
  "   and a wait. You do not have to know the pattern in advance: search once by hand, then read\n"
  "   `location.href` with `browser_eval` and reuse that URL from then on.\n\n"
  "2. Extract with one `browser_eval` that returns data. The DOM is the source of truth and a single\n"
  "   call can hand back a whole list:\n"
  "     [...document.querySelectorAll('article')].slice(0,12)\n"
  "       .map(a=>({t:a.innerText.slice(0,400), h:a.querySelector('a')?.href}))\n"
  "   Return JSON you can filter, not prose you have to read back. `browser_read` is for when you\n"
  "   genuinely just want the text; `browser_see` is for layout, not for counting.\n\n"
  "3. Wait inside the eval, never guess. A feed renders after the navigation settles, so poll for what\n"
  "   you need in the same call, on a real deadline:\n"
  "     (async()=>{for(let i=0;i<40;i++){const a=[...document.querySelectorAll('article')];\n"
  "       if(a.length>3)return a.length; await new Promise(r=>setTimeout(r,250))}return 0})()\n"
  "   An empty read means \"not yet\", not \"nothing there\". Re-open the same URL once and re-read;\n"
  "   do not re-open it five times.\n\n"
  "When a click changes nothing, do not click again — the thing you want may be an <a>, a button, or a\n"
  "tab with different words on it. Find it and click it in one eval:\n"
  "  [...document.querySelectorAll('a,button,[role=tab]')].find(e=>e.innerText.trim()==='Top')?.click()\n"
  "Tabs a site offers (Top / Recent / Latest / …) are the difference between what you were asked for\n"
  "and a page of noise: pick the one the task implies, and read something back to prove it changed.\n\n"
  "If the page shows a login wall, stop and say so — the account covering this site is not signed in\n"
  "(the Browsing line in your prompt names the accounts and their state). Never type a password."),
 "research": (
  "Research is a question, several sources, and evidence for each claim.\n\n"
  "- Turn the request into the few things that must be known, and answer those — not the topic.\n"
  "- Go to the source, not to a summary of it. Open the page and quote it.\n"
  "- One `browser_eval` per source that returns the facts as JSON beats ten reads.\n"
  "- Say what you verified and how, and say plainly what you could not find. \"Searched X and Y; the\n"
  "  pages showed only Z\" is a real answer. A plausible-sounding guess is not.\n"
  "- Cite: the URL plus the exact words you are relying on.\n"
  "- When you are asked for a list, return the list — every item, with its numbers — not a paragraph\n"
  "  about having looked."),
}

# ---------------------------------------------------------------- installed skills
# A skill is a folder holding a SKILL.md — YAML frontmatter with `name` and `description`,
# then the guidance body — plus whatever files it bundles. Built-ins above are always
# there; installed ones are unzipped under data/skills/ and indexed in data/skills.json
# with the moment they arrived, which is what the "recently installed" filter sorts on.
SKILLS_DIR = os.path.join(DATA, "skills")
SKILLS_FILE = os.path.join(DATA, "skills.json")
MAX_ZIP_BYTES = 25_000_000     # the upload itself
MAX_SKILL_BYTES = 2_000_000    # one skill's files, uncompressed
MAX_SKILL_FILES = 200
# How big a POST body may be. A zip travels base64-encoded inside JSON, which inflates it by 4/3,
# so the transport limit has to sit above the zip limit rather than below it — otherwise a zip the
# installer would happily accept is refused before it is ever read. Derived, so the two cannot drift.
MAX_BODY_BYTES = MAX_ZIP_BYTES * 4 // 3 + 65536
# An oversized upload is drained before it is refused, so the client finishes sending and reads the
# reply instead of a reset. `Content-Length` is the client's number, though, so the drain is bounded:
# past this the connection is closed rather than read for ever on a header's say-so.
MAX_DRAIN_BYTES = 256_000_000
SKILL_BODY_CHARS = 4000        # how much of a SKILL.md body is kept in the installed index
# How much skill text one system prompt may carry. A skill reaches the prompt as an index — its id,
# name and one-line description — and its guidance is read on demand with the `use_skill` tool. That
# is the whole design: a shelf is a catalogue, not a briefing. Pasting every body in made vps-dev's
# prompt 166 KB against a 32 k-token window, which compressed the history and cut the bot's own
# instructions off it. The cap below is only a guard against a pathological shelf; a realistic one
# (43 skills) comes to about 5 KB.
SKILL_INDEX_CHARS = 24000
SKILL_DOC_CHARS = 12000        # how much of one skill's guidance a single `use_skill` call returns
# The signed-in accounts ride in every prompt, so a user with many of them must not be able to crowd
# out the instructions that matter. This names roughly twenty; the rest are counted, not listed —
# routing is by site, so a bot never has to choose between them.
BROWSER_BRIEF_CHARS = 900
# The one line that must never be missing where this app owns its browsers: there is no other browser
# in play, and a bot's own memory often says there is (notes written back when the mode was "cdp").
# Without it a bot goes looking for an app that will never answer — the live failure was two minutes of
# `pgrep`/`lsof`/launch attempts against a dead debug port before it gave up and used `browser_open`,
# which worked. Short on purpose: it rides in every prompt, so it shares BROWSER_BRIEF_CHARS' budget.
BROWSER_OWN_LINE = (" This app opens and drives those browsers itself: never start, attach to, or "
                    "probe another browser or a debug port.")

def load_installed_skills(): return _load_json(SKILLS_FILE, [])
def all_skills(): return SKILLS + load_installed_skills()
def skills_public():
    """The catalog the settings UI renders: built-ins plus installed, no prompt bodies."""
    return ([dict(s, builtin=True) for s in SKILLS]
            + [dict((k, v) for k, v in s.items() if k != "body") | {"builtin": False}
               for s in load_installed_skills()])
def _skill_slug(s): return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:48]

def _skill_bundled(root):
    """The files a skill bundles, as paths relative to its folder — the tier-3 index `use_skill`
    hands back so a bot that needs more detail knows what there is to read."""
    out = []
    for dirpath, _dirs, names in os.walk(root):
        for n in names:
            rel = os.path.relpath(os.path.join(dirpath, n), root)
            if rel.lower() != "skill.md": out.append(rel)
    return sorted(out)[:80]

def skill_doc(name, file=None):
    """Read one skill on demand: its guidance, or a single file it bundles.

    A skill is a folder under data/skills holding a SKILL.md — the guidance — plus whatever it
    brings along (references/, templates/, scripts/). Only the index travels in the prompt; the
    guidance is read here, once the bot has decided the skill covers the job in front of it, which
    is what keeps a 43-skill shelf from costing more context than the work itself.

    Any skill in the catalog may be read, not just the ones on the calling bot's shelf: it is the
    user's own installed content and this is read-only, and the prompt's index is what actually
    points a bot at the skills meant for its role.
    """
    want = (name or "").strip().lower()
    catalog = all_skills()
    sk = (next((s for s in catalog if s["id"].lower() == want), None)
          or next((s for s in catalog if (s.get("name") or "").lower() == want), None))
    if not sk:
        return ("(no skill called %r — the skills you have are listed in your prompt)" % name), []
    sid, label = sk["id"], sk.get("name") or sk["id"]
    root = os.path.realpath(os.path.join(SKILLS_DIR, sid))
    if file:
        # The path is joined onto the skill's own folder and then re-resolved, so `../../` and an
        # absolute path both land outside it and are refused rather than read.
        p = os.path.realpath(os.path.join(root, file))
        if not (p == root or p.startswith(root + os.sep)) or not os.path.isfile(p):
            return "(no such file in %s: %s)" % (label, file), []
        try:
            with open(p, encoding="utf-8", errors="replace") as f: text = f.read()
        except OSError as e:
            return "(%s: %s)" % (file, e), []
        return text[:SKILL_DOC_CHARS], []
    md = os.path.join(root, "SKILL.md")
    if not os.path.isfile(md):
        # A built-in skill is name, description and — for the ones with a shipped body — the guidance
        # in `BUILTIN_BODIES`. Without that a bot that did the right thing and read its skill first
        # got nothing back, which is worse than no skill at all: it improvises with confidence.
        body = BUILTIN_BODIES.get(sid)
        if body: return body[:SKILL_DOC_CHARS], []
        return ("%s — %s\n\n(no extended guidance; the description is the whole of it)"
                % (label, sk.get("desc") or "")), []
    try:
        with open(md, encoding="utf-8", errors="replace") as f: text = f.read()
    except OSError as e:
        return "(%s: %s)" % (label, e), []
    text = re.sub(r"^\s*---\s*\n.*?\n\s*---\s*\n", "", text, count=1, flags=re.S).strip()  # drop frontmatter
    out = text[:SKILL_DOC_CHARS]
    if len(text) > SKILL_DOC_CHARS:
        out += "\n\n(truncated — %d more characters of guidance)" % (len(text) - SKILL_DOC_CHARS)
    files = _skill_bundled(root)
    if files:
        out += ("\n\n---\nThis skill also bundles these files; read one with "
                "use_skill(skill=%r, file=\"…\"):\n" % sid) + "\n".join("- " + f for f in files)
    return out, []
def _yaml_val(meta, key):
    """One frontmatter value. Handles the folded/literal block scalars real skills use
    (`description: >-` then indented lines) as well as a plain one-line value."""
    m = re.search(r"^" + key + r"\s*:\s*(.*)$", meta, re.M | re.I)
    if not m: return ""
    v = m.group(1).strip()
    if v in (">", ">-", ">+", "|", "|-", "|+"):
        indent, lines = None, []
        for ln in meta[m.end():].splitlines():
            if not ln.strip(): lines.append(""); continue
            cur = len(ln) - len(ln.lstrip())
            if indent is None: indent = cur
            elif cur < indent: break
            lines.append(ln.strip())
        return " ".join(x for x in lines if x).strip()
    return v.strip().strip('"').strip("'")
def _skill_candidates(data):
    """Read a zip into one candidate per SKILL.md — everything needed to show the picker and, if it
    is chosen, to install it. Writes nothing, so a scan can run first and nothing lands until the
    person has seen what the zip holds. Returns (zipfile, candidates, errors); the open archive
    comes back so the caller can read member bytes without unzipping twice."""
    if len(data) > MAX_ZIP_BYTES:
        return None, [], [f"that zip is over {MAX_ZIP_BYTES // 1_000_000} MB"]
    try: zf = zipfile.ZipFile(io.BytesIO(data))
    except Exception as e: return None, [], ["not a readable zip: " + str(e)]
    names = [n.replace("\\", "/") for n in zf.namelist()]
    mds = [n for n in names if n.lower().endswith("skill.md") and not n.endswith("/")]
    if not mds:
        return None, [], ["no SKILL.md in that zip — a skill zip holds one folder per skill, each with a SKILL.md"]
    out, errors = [], []
    taken = {s["id"] for s in SKILLS}       # a zip never shadows a built-in
    for md in mds:
        folder = os.path.dirname(md)
        prefix = (folder + "/") if folder else ""
        try: text = zf.read(md).decode("utf-8", "replace")
        except Exception as e: errors.append(f"{md}: {e}"); continue
        fm = re.match(r"^\s*---\s*\n(.*?)\n\s*---\s*\n?(.*)$", text, re.S)
        meta, body = (fm.group(1), fm.group(2).strip()) if fm else ("", text.strip())
        name = _yaml_val(meta, "name") or os.path.basename(folder) or "Skill"
        desc = _yaml_val(meta, "description")
        base = _skill_slug(name) or _skill_slug(os.path.basename(folder)) or "skill"
        sid, n = base, 1
        while sid in taken:                 # two folders can slug the same, so the ids must differ
            n += 1; sid = base + ("-installed" if n == 2 else "-%d" % n)
        taken.add(sid)
        # A root-level SKILL.md takes the whole archive except the folders of the other skills.
        others = [os.path.dirname(m) for m in mds if os.path.dirname(m) != folder]
        members = [x for x in names if not x.endswith("/") and
                   (x.startswith(prefix) if prefix
                    else not any(os.path.dirname(x) == o or os.path.dirname(x).startswith(o + "/") for o in others))]
        out.append({"id": sid, "name": name, "desc": desc, "body": body, "prefix": prefix, "members": members})
    return zf, out, errors

def scan_skill_zip(data):
    """What a zip holds, for the picker — the same ids install_skill_zip will accept, and nothing
    written. Returns (skills, errors)."""
    _, cands, errors = _skill_candidates(data)
    have = {s["id"] for s in load_installed_skills()}
    return ([{"id": c["id"], "name": c["name"], "desc": c["desc"][:200],
              "files": len(c["members"]), "replaces": c["id"] in have} for c in cands], errors)

def install_skill_zip(data, source="upload.zip", only=None):
    """Install every SKILL.md the zip holds, or just the ones named in `only` (ids from
    scan_skill_zip). Returns (installed, errors).

    Deterministic on purpose: a settings action should not depend on the router being
    up, and frontmatter is exact where a model's reading of a zip is not. A skill's
    whole folder comes along, so bundled scripts and references land with it.
    """
    zf, cands, errors = _skill_candidates(data)
    if zf is None: return [], errors
    want = {c["id"] for c in cands} if only is None else set(only)
    installed = []
    for c in cands:
        if c["id"] not in want: continue
        dest = os.path.join(SKILLS_DIR, c["id"]); written = total = 0
        for n in c["members"]:
            rel = os.path.normpath(n[len(c["prefix"]):] if c["prefix"] else n)
            if os.path.isabs(rel) or rel.startswith(".."):
                errors.append(f"{n}: skipped, it points outside the skill folder"); continue
            p = os.path.realpath(os.path.join(dest, rel))
            if not (p == os.path.realpath(dest) or p.startswith(os.path.realpath(dest) + os.sep)):
                errors.append(f"{n}: skipped, it points outside the skill folder"); continue
            size = zf.getinfo(n).file_size
            if written >= MAX_SKILL_FILES or total + size > MAX_SKILL_BYTES:
                errors.append(f"{c['name']}: stopped at {MAX_SKILL_FILES} files / {MAX_SKILL_BYTES // 1_000_000} MB"); break
            os.makedirs(os.path.dirname(p), exist_ok=True)
            try: open(p, "wb").write(zf.read(n))
            except Exception as e: errors.append(f"{n}: {e}"); continue
            written += 1; total += size
        if not written: errors.append(f"{c['name']}: nothing readable to install"); continue
        installed.append({"id": c["id"], "name": c["name"], "desc": (c["desc"] or "installed from " + source)[:200],
                          "installed_at": datetime.datetime.now().isoformat(timespec="seconds"),
                          "source": source, "files": written, "body": c["body"][:SKILL_BODY_CHARS]})
    if only is not None and not installed and not errors:
        errors.append("nothing in that zip matched the selection — scan it again")
    if installed:
        kept = [s for s in load_installed_skills() if s["id"] not in {i["id"] for i in installed}]
        _save_json(SKILLS_FILE, kept + installed)
    return installed, errors
def remove_skill(sid):
    """Uninstall: drop the record, the folder, and the skill from every bot that had it on."""
    before = load_installed_skills()
    if not any(s["id"] == sid for s in before): return False
    _save_json(SKILLS_FILE, [s for s in before if s["id"] != sid])
    shutil.rmtree(os.path.join(SKILLS_DIR, sid), ignore_errors=True)
    bots = load_bots(); touched = False
    for b in bots:
        if sid in (b.get("skills") or []):
            b["skills"] = [x for x in b["skills"] if x != sid]; touched = True
    if touched: save_bots(bots)
    return True

# ---------------------------------------------------------------- channel logos
# A company's row in the sidebar otherwise shows two letters ("CO", "ER"). A logo is nicer, and
# the repo usually already has one -- so an uploaded image wins, and with nothing uploaded we look
# for the project's own logo. Nothing is copied or cached: the file is read from where it lives, so
# replacing it in the repo shows up on the next request.
LOGO_DIR = os.path.join(DATA, "logos")
MAX_LOGO_BYTES = 2_000_000
LOGO_MIME = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
             "image/gif": ".gif", "image/svg+xml": ".svg"}
LOGO_TYPE = {v: k for k, v in LOGO_MIME.items()}
LOGO_TYPE[".ico"] = "image/x-icon"     # never uploaded, but a repo favicon is a fair logo
# Where a project keeps its logo, most likely first, and what it is usually called. `build` and
# `resources` are the icon folders electron-builder and electron-forge use, which is where an
# Electron app keeps the one image that already stands for the whole project.
REPO_LOGO_DIRS = ("", "public", "static", "assets", "src/assets", "images", "img", "brand",
                  "build", "resources", ".github")
REPO_LOGO_STEMS = ("logo", "brand", "icon", "favicon")
REPO_LOGO_EXTS = (".svg", ".png", ".webp", ".jpg", ".jpeg", ".gif", ".ico")

def _logo_ver(p):
    """A number that changes whenever the image does, so the browser can cache hard and still
    pick up a new logo immediately (it is carried in the URL as ?v=)."""
    try: return int(os.stat(p).st_mtime_ns // 1_000_000)
    except OSError: return 0

def repo_logo(folder):
    """The logo already in a repo, as a path relative to it, or ''. One listdir per candidate
    folder and a fixed preference order, so a project does not have to be renamed to be found."""
    if not folder: return ""
    for d in REPO_LOGO_DIRS:
        base = os.path.join(folder, d) if d else folder
        try: names = os.listdir(base)
        except OSError: continue
        best = None
        for n in names:
            stem, ext = os.path.splitext(n)
            if stem.lower() in REPO_LOGO_STEMS and ext.lower() in REPO_LOGO_EXTS:
                rank = (REPO_LOGO_STEMS.index(stem.lower()), REPO_LOGO_EXTS.index(ext.lower()))
                if best is None or rank < best[0]: best = (rank, n)
        if best: return os.path.join(d, best[1]) if d else best[1]
    return ""

def _logo_id(cid):
    """A channel id is a slug, or it is not a logo id at all. Checked at the one place that turns an
    id into a filename, so no caller -- including one passing an id straight from a request -- can
    hand us a path that reaches outside data/logos."""
    cid = (cid or "").strip().lower()
    return cid if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", cid) else ""

def logo_state(c):
    """The one place that decides a channel's logo, so the sidebar, the editor and the file server
    can never disagree: an uploaded image, else the repo's own, else nothing (the monogram)."""
    cid = _logo_id(c.get("id"))
    for ext in LOGO_MIME.values():
        p = os.path.join(LOGO_DIR, cid + ext)
        if cid and os.path.isfile(p): return {"path": p, "v": _logo_ver(p), "source": "upload", "rel": ""}
    folder = resolve_folder(c.get("folder") or "")
    rel = repo_logo(folder)
    if rel:
        p = os.path.join(folder, rel)
        if os.path.isfile(p): return {"path": p, "v": _logo_ver(p), "source": "repo", "rel": rel}
    return {"path": "", "v": 0, "source": "", "rel": ""}

def _logo_bytes_ok(blob, ext):
    """The MIME type came from the browser, so it is only a hint. Check the bytes really are that
    format -- a renamed file must not become markup served from our own origin."""
    if ext == ".png":  return blob.startswith(b"\x89PNG\r\n\x1a\n")
    if ext == ".jpg":  return blob.startswith(b"\xff\xd8\xff")
    if ext == ".gif":  return blob.startswith((b"GIF87a", b"GIF89a"))
    if ext == ".webp": return blob[:4] == b"RIFF" and blob[8:12] == b"WEBP"
    if ext == ".svg":
        if b"<svg" not in blob[:8192].lower(): return False
        low = blob.lower()
        return not any(t in low for t in (b"<script", b"javascript:", b"<foreignobject", b"onload="))
    return False

def channels_public(chs):
    """Channels for the UI. The logo is described, not embedded: a version to cache-bust with,
    where it came from, and for a repo logo which file -- so the editor can name it."""
    out = []
    for c in chs:
        lg = logo_state(c)
        out.append({**c, "folder_ok": bool(resolve_folder(c.get("folder"))),
                    "logo": lg["v"], "logo_src": lg["source"], "logo_rel": lg["rel"]})
    return out

def _save_image(dirpath, key, data_url, what="logo", cap=None):
    """Decode an uploaded data URL and store it as `<dirpath>/<key>.<ext>`, replacing any older
    extension for that key, so exactly one file decides what a row shows. The MIME type came from
    the browser and is only a hint: the bytes have to really be that format, or a renamed file
    becomes markup served from our own origin. `cap` is for pictures the image model draws, which are
    larger than the 2 MB a logo or an avatar is held to."""
    m = re.match(r"^data:(image/[a-z+.-]+);base64,(.+)$", data_url or "", re.S)
    if not m: return {"ok": False, "error": "that is not an image file"}
    mime, b64 = m.group(1).lower(), m.group(2)
    ext = LOGO_MIME.get(mime)
    if not ext: return {"ok": False, "error": "use a png, jpg, webp, gif or svg"}
    try: blob = base64.b64decode(b64, validate=True)
    except Exception: return {"ok": False, "error": "the image data is corrupt"}
    if not blob: return {"ok": False, "error": "that file is empty"}
    if len(blob) > (cap or MAX_LOGO_BYTES): return {"ok": False, "error": "the image is larger than %d MB" % ((cap or MAX_LOGO_BYTES) // (1 << 20))}
    if not _logo_bytes_ok(blob, ext): return {"ok": False, "error": "that file is not really a " + ext.lstrip(".")}
    try:
        os.makedirs(dirpath, exist_ok=True)
        for old in LOGO_MIME.values():
            if old != ext and os.path.isfile(os.path.join(dirpath, key + old)):
                os.remove(os.path.join(dirpath, key + old))
        tmp = os.path.join(dirpath, key + ext + ".tmp")
        with open(tmp, "wb") as f: f.write(blob)
        os.replace(tmp, os.path.join(dirpath, key + ext))
    except OSError as e:
        return {"ok": False, "error": "could not save the %s: %s" % (what, e)}
    return {"ok": True, "file": key + ext}

def _remove_image(dirpath, key):
    """Delete every extension a key could have been stored under. True if anything was there."""
    gone = False
    for ext in LOGO_MIME.values():
        p = os.path.join(dirpath, key + ext)
        try:
            if os.path.isfile(p): os.remove(p); gone = True
        except OSError: pass
    return gone

def save_logo(cid, data_url):
    """Store an uploaded logo for one channel. Any older upload for that channel is removed first,
    so exactly one file decides what the row shows."""
    cid = _logo_id(cid)
    if not cid: return {"ok": False, "error": "unknown channel"}
    r = _save_image(LOGO_DIR, cid, data_url)
    return {"ok": True} if r.get("ok") else r   # a logo's caller wants ok, not the file name

def remove_logo(cid):
    """Drop the uploaded logo. The repo's own logo (if any) takes over again."""
    cid = _logo_id(cid)
    return _remove_image(LOGO_DIR, cid) if cid else False

# ---------------------------------------------------------------- bot avatars
# A bot's face picture: the user introduces an image, the image model redraws it as the bot's face
# (POST /api/avatar/transform), and the client draws it where the eyes and mouth would be. Stored
# under the bot's id, so -- like a channel logo -- the bot has to exist before it can have one.
# Upload-only: unlike a channel there is no repo to search, and the same 2 MB cap and the same
# magic-byte checks as a logo.
AVATAR_DIR = os.path.join(DATA, "avatars")
def avatar_state(b):
    """A bot's avatar: the stored file and a version that changes whenever it does, or nothing."""
    bid = _logo_id(b.get("id"))
    for ext in LOGO_MIME.values():
        p = os.path.join(AVATAR_DIR, bid + ext)
        if bid and os.path.isfile(p): return {"path": p, "v": _logo_ver(p), "source": "upload"}
    return {"path": "", "v": 0, "source": ""}

def save_avatar(bid, data_url):
    """Store an uploaded avatar for one bot. A bot id is the same slug shape as a channel id, so
    the same check decides whether it can name a file inside data/avatars."""
    bid = _logo_id(bid)
    if not bid: return {"ok": False, "error": "unknown bot"}
    r = _save_image(AVATAR_DIR, bid, data_url, "avatar")
    return {"ok": True} if r.get("ok") else r

def remove_avatar(bid):
    """Drop the uploaded avatar; the client draws the bot's face again."""
    bid = _logo_id(bid)
    return _remove_image(AVATAR_DIR, bid) if bid else False

def avatar_prompt(species, color):
    """What the image model is asked for when turning a photo into a bot's face: the *face* only,
    filling the frame. The bot's body, outfit and accessory are drawn by the engine around it, so a
    body would land underneath them — and a background or an icon frame would land on the head as a
    pasted-in square, which is why the frame is ruled out as firmly as the body."""
    return ("Redraw the subject of the photo as a cute flat-vector mascot FACE, filling the whole "
            "square edge to edge: keep its colours, hair, eyes and distinctive features, drawn as a "
            "friendly cartoon character's face. FACE ONLY — no body, no arms, no hands, no text. NO "
            "background, no frame, no border, no rounded-square icon, no drop shadow: the head itself "
            "reaches all four edges. Species: %s. Colour: %s."
            % (str(species or "as in the photo")[:60], str(color or "as in the photo")[:40]))

# ---------------------------------------------------------------- bot faces
# One source image, and the image model draws a whole mascot for each bot from it — head and body
# together, one distinct character per bot. This is the section's picture, not a per-bot upload: a
# batch is drawn once and every bot takes a different one from it. The engine draws the outfit and
# accessory on top, so the model is asked for a clothing-free body.
# A bot record only carries the filename of the drawing it took, so swapping a bot's face for
# another from the same set is one field, not a new image.
FACES_DIR = os.path.join(DATA, "faces")
FACES_BATCH_PATH = os.path.join(FACES_DIR, "batch.json")
FACE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".webp": "image/webp", ".gif": "image/gif"}
# One batch at a time: the router is slow, and two runs at once would assign bots from both.
FACE_JOB = {"running": False, "done": 0, "total": 0, "error": "", "id": ""}

def faces_batch():
    """The current set: its source picture and the drawings that really exist on disk."""
    st = _load_json(FACES_BATCH_PATH, {}) or {}
    files = [f for f in (st.get("files") or []) if os.path.isfile(os.path.join(FACES_DIR, f))]
    src = st.get("source") or ""
    if src and not os.path.isfile(os.path.join(FACES_DIR, src)): src = ""
    return {"id": st.get("id") or "", "at": st.get("at") or 0, "source": src, "files": files}

def faces_public(bots):
    b = faces_batch()
    return {"id": b["id"], "at": b["at"], "source": b["source"], "files": b["files"],
            "job": dict(FACE_JOB),
            "bots": [{"id": x["id"], "name": x.get("name") or x["id"], "genface": x.get("genface") or "",
                      "avatar": x.get("avatar") or 0}
                     for x in bots]}

def face_prompt(species, color, i, n):
    """A whole mascot: head and body in one drawing, on a plain backdrop the client keys out.

    The animal comes from the photo and nothing else. Naming the bot's engine species here drew a
    cat as an owl — the model obeyed "Species: owl" over the picture it was given. The bot's colour
    is only an accent, for the same reason: recolouring the subject is what made one photo come
    back as several different animals. Clothing and accessories are ruled out because the engine
    draws the bot's own on top, and the backdrop is pure white because that is what the key removes.
    A white subject is allowed now — the key is edge-connected, so it takes the backdrop and not the
    cat sitting on it."""
    accent = str(color or "").strip()[:40]
    return ("Redraw the subject of the photo as a cute flat-vector mascot character: the WHOLE bot, "
            "head and body together, standing upright, centred and filling the square. Keep the "
            "SAME ANIMAL as the photo — never change its species — and keep its own fur or feather "
            "colours, markings, ears, eyes and face. This is character %d of %d, so give it its own "
            "pose or a small prop; the animal itself stays the one in the photo.%s Background: one "
            "flat pure white (#FFFFFF), nothing else — no scenery, no frame, no border, no text, no "
            "shadow. Simple body with no clothing, no hat, no glasses and no accessories: those are "
            "drawn on afterwards."
            % (i + 1, n, (" Only a collar or another small detail may use %s." % accent) if accent else ""))

def set_genface(b, f):
    """Give a bot a face from the set. It also drops an older per-bot picture: picking a face here
    is the newer, deliberate choice, and a picture left over from the bot editor would otherwise
    keep winning in the client — the section would look like it did nothing."""
    b["genface"] = f or ""
    if b["genface"] and b.get("avatar"):
        remove_avatar(b["id"]); b["avatar"] = 0

def _faces_prune(keep=()):
    """Drop drawings no bot can reach any more. `keep` is the set that just landed."""
    if not os.path.isdir(FACES_DIR): return
    for f in os.listdir(FACES_DIR):
        if f.startswith("f-") and f not in keep:
            try: os.remove(os.path.join(FACES_DIR, f))
            except OSError: pass

def _face_worker(batch_id, source_name, source, targets):
    """Draw one mascot per bot, saving and assigning each as it lands: a run that dies halfway still
    leaves the bots it finished with their faces instead of nothing at all."""
    made, err = [], ""
    try:
        for i, (bid, species, color) in enumerate(targets):
            try:
                data_url, used = gen_image(face_prompt(species, color, i, len(targets)),
                                           image=source, timeout=180)
            except Exception as e:
                data_url, used = "", str(e)
            if not data_url:
                err = used or "the image model drew nothing"
            else:
                r = _save_image(FACES_DIR, "f-%s-%d" % (batch_id, i + 1), data_url, "face", cap=8 << 20)
                if not r.get("ok"):
                    err = r.get("error") or err
                else:
                    made.append(r["file"])
                    bots = load_bots()
                    b = bot_by_id(bots, bid)
                    if b: set_genface(b, r["file"]); save_bots(bots)
                    _save_json(FACES_BATCH_PATH, {"id": batch_id, "at": int(time.time()),
                                                  "source": source_name, "files": made})
            FACE_JOB["done"] = i + 1
        # A run that drew nothing must not delete the set that is already there: the bots would be
        # left pointing at files this prune had just removed.
        if made: _faces_prune(made)
    except Exception as e:
        err = str(e)[:200]
    finally:
        if made:
            # A bot whose face was pruned away goes back to its own drawn bot instead of pointing at
            # a file that is not there any more.
            bots = load_bots()
            for b in bots:
                if b.get("genface") and b["genface"] not in made: b["genface"] = ""
            save_bots(bots)
        FACE_JOB["error"] = "" if made else (err or "the image model drew nothing")
        FACE_JOB["running"] = False

# ---------------------------------------------------------------- team import
# BotMRR (botmrr.io) hands you a Markdown playbook: YAML frontmatter with an `agents:`
# list and a `rooms:` list. Paste it and we build the whole team — one bot per agent,
# one room for all of them. Anything that is not a BotMRR playbook falls back to asking
# the model to read the names and positions out of whatever was pasted.
IMPORT_COLORS = {"purple": "purple", "blue": "blue", "green": "green", "orange": "orange",
                 "yellow": "yellow", "pink": "pink", "cyan": "blue", "teal": "green",
                 "coral": "pink", "red": "pink", "grey": "blue", "gray": "blue"}
# First keyword found in the title wins, so order matters: specific roles before generic ones.
IMPORT_ROLES = [
    ("qa", "🧪", "testing verification"), ("quality", "🧪", "testing verification"),
    ("test", "🧪", "testing verification"), ("release", "🚀", "testing verification deploy"),
    ("research", "🔍", "research web summarise"), ("analyst", "📊", "research summarise"),
    ("data", "📊", "research summarise"), ("design", "🎨", "coding"), ("ui", "🎨", "coding"),
    ("frontend", "🎨", "coding"), ("front end", "🎨", "coding"), ("backend", "🛠️", "coding shell testing"),
    ("engineer", "🛠️", "coding shell testing"), ("dev", "🛠️", "coding shell testing"),
    ("ops", "⚙️", "deploy monitoring"), ("deploy", "⚙️", "deploy monitoring"),
    ("growth", "📣", "writing research"), ("market", "📣", "writing research"),
    ("copy", "✍️", "writing"), ("writ", "✍️", "writing"), ("sales", "💼", "writing research"),
    ("support", "💬", "writing"), ("lead", "🎩", "planning delegation writing"),
    ("producer", "🎩", "planning delegation writing"), ("manager", "🎩", "planning delegation writing"),
    ("coordinator", "🎩", "planning delegation writing"),
    ("chief", "🎩", "planning delegation writing"), ("head", "🎩", "planning delegation writing"),
]
IMPORT_PALETTE = ["purple", "blue", "green", "orange", "yellow", "pink"]
def _role_hint(title):
    t = (title or "").lower()
    for kw, emoji, skills in IMPORT_ROLES:
        if kw in t: return emoji, skills.split()
    return "🤖", []
def _scalar(v):
    v = (v or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'": v = v[1:-1]
    return v
def parse_team(text):
    """Read a BotMRR playbook into {name, chief, agents, rooms}. Pure stdlib, no YAML dependency."""
    m = re.search(r"^---[ \t]*\n(.*?)\n---[ \t]*$", text or "", re.S | re.M)
    body = m.group(1) if m else (text or "")
    out = {"name": "", "chief": "", "agents": [], "rooms": []}
    section = rec = sub = None
    for raw in body.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"): continue
        ind = len(raw) - len(raw.lstrip(" ")); s = raw.strip()
        if ind == 0:
            k, _, v = s.partition(":"); k = k.strip()
            if k in ("agents", "rooms", "channels"):
                section = "rooms" if k in ("rooms", "channels") else "agents"; rec = sub = None
            else:
                if k == "name": out["name"] = _scalar(v)
                elif k == "chiefOfStaff": out["chief"] = _scalar(v)
                section = rec = sub = None
            continue
        if section is None: continue
        if s.startswith("- "):
            item = s[2:]; k, _, v = item.partition(":"); k = k.strip(); v = _scalar(v)
            # A record starts at whichever of its own fields comes first. BotMRR writes `key` first,
            # but an entry that opens with `name` is still an agent — reading only `key` here dropped
            # it entirely, which read as "no agents" instead of "this agent has no key".
            if ind <= 4 and k in ("key", "name", "title", "description"):
                rec = {k: v}; sub = None; out[section].append(rec)
            elif rec is not None and sub == "members": rec.setdefault("members", []).append(v or _scalar(item))
            elif rec is not None and sub == "playbooks": rec.setdefault("playbooks", []).append(v or _scalar(item))
            continue
        if rec is None: continue
        k, _, v = s.partition(":"); k = k.strip(); v = _scalar(v)
        if ind <= 4:                                  # a field of the record itself
            if k in ("appearance", "defaultResponder", "playbooks", "members"): sub = k; continue
            sub = None
            if k in ("key", "name", "title", "description", "bulletin", "summary"): rec[k] = v
            continue
        if sub == "appearance" and k == "color": rec["color"] = v
        elif sub == "defaultResponder" and k == "agent": rec["lead"] = v
    return out
# The structure a playbook has to have, and the exact text the copy button hands out. It is a real
# playbook — every field below is one we read — so a paste built from it imports cleanly, and the
# checks run `team_problems` over this same string: the template and the validator cannot drift.
TEAM_TEMPLATE = """---
botmrr: 1
name: Your Team
agents:
  - key: lead
    name: Lea
    title: Producer
    description: What this bot owns, and how it should work. Two or three sentences.
    appearance:
      color: purple
  - key: dev
    name: Dima
    title: Engineer
    description: What this bot owns, and how it should work. Two or three sentences.
    appearance:
      color: green
chiefOfStaff: lead
rooms:
  - key: main-room
    name: Main Room
    members:
      - lead
      - dev
    bulletin: The rules everyone in this room works by. One paragraph.
    defaultResponder:
      kind: agent
      agent: lead
---
"""
def _playbook_shaped(text):
    """True when a paste is claiming to be a playbook rather than the plain list of names the panel
    also takes. A paste with no `agents:` is not a broken playbook — it is the other input, and it
    goes to the model."""
    return bool(re.search(r"^[ \t]*agents[ \t]*:", text or "", re.M)
                or re.search(r"^---", text or "", re.M) or "botmrr:" in (text or ""))
def team_problems(text):
    """Everything a paste is missing, by name, so it can be revised — or [] when it is not a playbook.

    Strict on purpose: an agent or room that exists but is incomplete is reported as such rather than
    being quietly given a default, because the whole point of handing the structure to a model is to
    get a team that is actually filled in."""
    if not _playbook_shaped(text): return []
    t = parse_team(text); out = []
    if not t["agents"]:
        out.append("no `agents:` — add a list with at least one agent")
    keys = {}
    for i, a in enumerate(t["agents"], 1):
        who = (a.get("name") or a.get("key") or "").strip() or ("agent %d" % i)
        for k in ("key", "name", "title", "description"):
            if not (a.get(k) or "").strip(): out.append("agent %d (%s) has no `%s`" % (i, who, k))
        k = (a.get("key") or "").strip().lower()
        if k:
            if k in keys: out.append("two agents share the key `%s`" % k)
            keys[k] = True
    if not t["rooms"]:
        out.append("no `rooms:` — add a list with at least one room")
    for i, r in enumerate(t["rooms"], 1):
        who = (r.get("name") or r.get("key") or "").strip() or ("room %d" % i)
        for k in ("key", "name"):
            if not (r.get(k) or "").strip(): out.append("room %d (%s) has no `%s`" % (i, who, k))
        mem = [m.strip() for m in (r.get("members") or []) if m.strip()]
        if not mem: out.append("room %s has no `members`" % who)
        for m in mem:
            if m.lower() not in keys: out.append("room %s lists member `%s`, but no agent has that key" % (who, m))
        lead = (r.get("lead") or "").strip()
        # Either field can name the room's lead — a playbook that only sets `chiefOfStaff` is complete,
        # since that bot is the one `build_team` puts in charge. Only a room with neither is a problem.
        if not lead and not (t.get("chief") or "").strip():
            out.append("room %s has no `defaultResponder:` `agent:` to lead it" % who)
        elif lead and lead.lower() not in keys:
            out.append("room %s names lead `%s`, but no agent has that key" % (who, lead))
    chief = (t.get("chief") or "").strip()
    if chief and chief.lower() not in keys:
        out.append("`chiefOfStaff` names `%s`, but no agent has that key" % chief)
    return out
IMPORT_SYS = ("Extract the team of AI agents described below into JSON. Reply with ONLY a JSON array, "
              "no prose and no code fence: [{\"name\":\"...\",\"title\":\"...\",\"description\":\"...\"}]. "
              "Use the exact names and positions given; if a description is missing write one short "
              "sentence. At most 12 agents. If there are no agents, reply [].")
def llm_team(text):
    """Fallback for a paste that is not a BotMRR playbook — let the model read it."""
    try: raw = (chat(DEFAULT_MODEL, [{"role": "system", "content": IMPORT_SYS},
                                     {"role": "user", "content": text[:6000]}], max_tokens=1200).get("content") or "").strip()
    except Exception: return []
    i, j = raw.find("["), raw.rfind("]")
    if i < 0 or j < 0: return []
    try: items = json.loads(raw[i:j + 1])
    except Exception: return []
    return [x for x in items if isinstance(x, dict) and (x.get("name") or "").strip()][:12]
def build_team(text):
    """Turn pasted text into bots (and a room). Returns (created_bots, created_rooms)."""
    team = parse_team(text)
    agents = team["agents"] or llm_team(text)
    if not agents: return [], []
    bots = load_bots(); used = {b["id"] for b in bots}; keymap = {}
    made = []
    for i, a in enumerate(agents):
        base = re.sub(r"[^a-z0-9]+", "-", (a.get("key") or a.get("name") or "bot").lower()).strip("-") or "bot"
        bid, n = base, 2
        while bid in used: bid = f"{base}-{n}"; n += 1
        used.add(bid); keymap[(a.get("key") or "").lower()] = bid
        title = (a.get("title") or "Teammate").strip()
        emoji, skills = _role_hint(title)
        name = (a.get("name") or bid.replace("-", " ").title()).strip()
        made.append({"id": bid, "name": name, "title": title, "role": title,
                     "color": IMPORT_COLORS.get((a.get("color") or "").lower()) or IMPORT_PALETTE[i % len(IMPORT_PALETTE)],
                     "model": DEFAULT_MODEL, "approval": "ask", "memory": True, "voice": "",
                     "instructions": (a.get("description") or ("You are " + name + ", " + title + ".")).strip(),
                     "skills": skills, "tools_allow": None, "hidden": False, "pinned": False, "emoji": emoji})
    bots.extend(_norm_bots(made)); save_bots(bots)   # the one shared definition, as for a single bot
    rooms = []
    for r in team["rooms"]:
        rid = re.sub(r"[^a-z0-9]+", "-", (r.get("key") or r.get("name") or "room").lower()).strip("-") or "room"
        members = [keymap[k.lower()] for k in (r.get("members") or []) if k.lower() in keymap] or [b["id"] for b in made]
        # The room's own defaultResponder is the lead; a playbook that only names a `chiefOfStaff`
        # (BotMRR writes both) still gets that bot in charge rather than whoever happened to be first.
        lead = keymap.get((r.get("lead") or "").lower()) or keymap.get((team.get("chief") or "").lower())
        rooms.append({"id": rid, "name": r.get("name") or rid.replace("-", " ").title(), "members": members,
                      "mode": "lead", "lead": lead or members[0], "instructions": (r.get("bulletin") or "").strip(), "folder": ""})
    if rooms:
        chs = load_channels(); have = {c["id"] for c in chs}
        for c in rooms:
            while c["id"] in have: c["id"] += "-2"   # an imported room yields to the one already there
            have.add(c["id"])
        # ...and every field default comes from the one shared definition, so an imported room is
        # whole in the file rather than repaired on every read.
        chs.extend(_norm_channels(rooms))
        save_channels(chs)
    for b in made: new_session(b["id"], bot=b["id"], title=b["name"])
    for c in rooms: new_session(c["id"], bot=None, title=c["name"])
    return made, rooms

# ---------------------------------------------------------------- sessions
SESS_PATH = os.path.join(DATA, "sessions.json")
RUNNING = {}; APPROVAL = {}; STEER = {}
# Deleted chats are tombstoned until an explicit new_session call recreates them. This prevents a
# turn that was already in flight when its bot/room was deleted from saving the session back.
_DELETED_SESSIONS = {}
_SESSION_EPOCH = {}
_SESSION_CTX = threading.local()
# A chat whose turn has passed the point where it can take one more steer. `STEER[sid]` says "a turn is
# in flight"; this says "it is writing its last word, so nothing more can turn it". The two are not the
# same, and the gap between them is where a steer used to be accepted and then quietly dropped.
# Set at each point the turn stops being able to hand one over: the last step of the run (nothing
# follows it), and each exit branch — Stop, the clock, the step budget. `/api/chat/steer` refuses while
# it is set, and a refusal is what makes the caller keep the message and run it as the next turn.
STEER_CLOSED = set()
# A chat the user asked to stop. Cancelling the browser's stream only closes the socket — the turn's
# own thread keeps running and its yields pile up in a queue nobody reads — so Stop used to be a
# no-op that merely hid the card. This is the flag the turn loop actually checks: set by /api/stop,
# cleared when the turn ends, and it also releases a turn parked on an approval card.
STOP = set()
_running_lock = threading.Lock()
def _session_lock(sid):
    """A per-chat lock, created on demand, so one chat runs one turn at a time."""
    with _running_lock:
        return RUNNING.setdefault(sid, threading.RLock())
def _drain_steer(sid):
    """Messages typed into a chat whose turn was already running, in the order they arrived.

    A steer is delivered to the bot at its next step rather than waiting for the turn to end — that
    is the whole difference between steering and queueing. `STEER[sid]` exists only while that
    chat's turn does, so its presence is also how the server knows a turn is in flight to steer.
    Each entry is `{"text", "quote"}` — a steer may be a reply, and then it carries what it answers."""
    d = STEER.get(sid)
    if not d: return []
    out = []
    while d:
        try: m = d.popleft()
        except IndexError: break
        out.append({"text": m, "quote": None} if isinstance(m, str) else m)
    return out
def _apply_steers(sid, messages):
    """Hand the user's mid-turn steers to the bot: each is recorded in the transcript and appended to
    the request the bot is about to see, and each is returned as the event the clients draw.

    Called at every step *and* at each point the turn would otherwise close, because a task typed
    while the bot was writing its last word arrives after the last step has begun: drained only at
    the top of a step, it would sit in the deque until the turn popped it, and the row on the client
    that says "steering…" — cleared by this event — would stay there for good."""
    evs = []
    for m in _drain_steer(sid):
        messages.append({"role": "user", "content": _task_with_quote(m["text"], m.get("quote"))})
        st2 = load(sid); st2["messages"].append(_user_message(m["text"], m.get("quote"), False)); save(sid, st2)
        evs.append({"type": "steer", "text": m["text"], "quote": m.get("quote")})
    return evs
def _release_steers(sid):
    """Steers the turn is ending with no step left to hand them to — Stop, the clock or the step budget
    ended it under them. Each is named as *not* taken, the same answer the endpoint gives a steer that
    arrives too late, so the client keeps it in its own queue and runs it as the next turn.

    Draining these into the transcript instead would draw the message under a turn that is already
    over, with no bot left to answer it: the instruction would sit there looking ignored, which is the
    one reading this must not produce. Popping them silently is what left the row reading "handing
    over…" for good. Either way the message is the user's, so it is handed back rather than spent."""
    return [{"type": "steer", "text": m["text"], "quote": m.get("quote"), "late": True}
            for m in _drain_steer(sid)]
# The whole session store is held in memory and written through, not re-parsed from disk on every
# read. A turn touches it many times per step — exec_tool loads it, every steer loads and saves it,
# every report appends — and a full parse of every chat on each of those calls made a long turn cost
# grow with how many chats exist. One process owns the file (the scheduler thread and the request
# threads all come through here), so this dict is the source of truth and `_save_json`'s atomic
# replace is the only write. Keyed on the path so a test that redirects SESS_PATH starts clean.
_SESS = {"path": None, "d": None}
_SESS_LOCK = threading.RLock()
def _all_sessions():
    with _SESS_LOCK:
        if _SESS["d"] is None or _SESS["path"] != SESS_PATH:
            _SESS["d"] = _load_json(SESS_PATH, {}); _SESS["path"] = SESS_PATH
        return _SESS["d"]
def _sessions_snapshot():
    """A shallow copy of the store for read-only iteration. Writers add and drop chats under
    `_SESS_LOCK` — a room turn creates a member's scoped chat (`<room>/<bot>`) the moment that member
    does work — so a reader that walked the live dict raised "dictionary changed size during
    iteration" and the request died. Readers take the copy; writers still mutate the live dict."""
    with _SESS_LOCK:
        return list((_all_sessions() or {}).items())

def _write_sessions(d, keep_tombstones=False):
    # Compact, not pretty-printed: this store is written several times per turn (the message, every
    # steer, the report), and the indentation doubled the bytes to serialize and fsync each time. It
    # is a data file, not a document anyone reads.
    # Serialized from a copy of each chat rather than from the live object. A session dict is mutated
    # in place all over the app — `save` stamps `ts`, a turn sets `ctx`, the model and approval routes
    # set theirs — and none of those hold `_SESS_LOCK`, so `json.dump` walking the live dict hit
    # "dictionary changed size during iteration" and the save died with it, taking the request with it.
    # `v.copy()` is a single C call, so the GIL is held for its whole length and no other thread can
    # add a key to that chat mid-copy. Only the keys are copied and the values are shared, which is
    # enough: nothing mutates a stored value in place — `ctx` and every message are assigned or
    # appended whole — and a list that grows while `json` walks it does not raise.
    with _SESS_LOCK:
        _SESS["d"] = d; _SESS["path"] = SESS_PATH
        _save_json(SESS_PATH, {k: (v.copy() if isinstance(v, dict) else v) for k, v in d.items()},
                   indent=None)
        if not keep_tombstones:
            for k in list(_DELETED_SESSIONS):
                if k in d: _DELETED_SESSIONS.pop(k, None)

# ---------------------------------------------------------------- who is watching a chat
# The desktop window and the phone are two clients of one server, and a chat is one transcript on
# disk — so a turn typed on the phone has to turn up in the window, and the other way round. Sharing
# the file was never the problem; being *told* was. A client may hold one `/api/watch` stream open,
# and every write to a transcript pushes that chat's id down all of them. What travels is a nudge,
# not the transcript: the client re-reads the chat over the ordinary API, so a lost event costs a
# refresh and never a message, and a slow reader is dropped rather than allowed to stall a turn.
WATCH = set()
_watch_lock = threading.Lock()

def _watching():
    """Open a subscription and hand back its queue. Bounded, because the writer is a running turn
    that must never wait on a phone that has wandered off the wifi."""
    q = queue.Queue(maxsize=64)
    with _watch_lock: WATCH.add(q)
    return q

def _unwatch(q):
    with _watch_lock: WATCH.discard(q)

def _fanout(ev):
    """Push one event to every open watcher. The writer is a running turn, so it never waits: a
    watcher that has fallen behind is dropped (see _watching) rather than allowed to stall the turn."""
    with _watch_lock: subs = list(WATCH)
    for q in subs:
        try: q.put_nowait(ev)
        except queue.Full: pass

def _notify(sid, kind="chat"):
    """Tell every open watcher that one transcript moved."""
    _fanout({"type": kind, "session": sid})

def _broadcast(sid, turn, gen):
    """A turn's own events, mirrored to every watcher as they happen.

    A turn streams its cards (status, plan, tool rows, the answer being written) to the one client
    that POSTed it — so the phone, watching a turn the desktop started, used to sit blank until the
    transcript was saved at the very end. Each event is now also pushed down the watch streams, so a
    watching client draws the same cards live. Every event carries the turn's id: the client running
    the turn ignores the events bearing its own id (its own stream is drawing it), and every other
    client renders them through the same handlers.
    """
    ended = False
    try:
        for ev in gen:
            if ev.get("type") == "done": ended = True
            _fanout(dict(ev, session=sid, turn=turn))
            yield ev
    except Exception as e:
        _fanout({"type": "error", "msg": str(e), "session": sid, "turn": turn}); ended = True
        raise
    finally:
        if not ended: _fanout({"type": "done", "session": sid, "turn": turn})   # never leave a watcher mid-turn

def new_session(sid, bot=None, title=None):
    d = _all_sessions()
    # Adding the key is done under the lock: `_write_sessions` holds it while it serializes the whole
    # store, and a key added mid-dump is the one thing that makes `json.dump` raise "dictionary changed
    # size during iteration" — which aborts whatever turn happened to be saving.
    with _SESS_LOCK:
        _DELETED_SESSIONS.pop(sid, None)
        _SESSION_EPOCH[sid] = _SESSION_EPOCH.get(sid, 0) + 1
        if sid not in d:
            # model stays unset until the user picks one on the fly, so the bot's own model shows through
            d[sid] = {"bot": bot, "title": title or "Chat", "messages": [], "model": None,
                      "pending": None, "approval": None}
            _write_sessions(d)
    return d[sid]
def load(sid):
    d = _all_sessions()
    if sid not in d:
        # A deleted session must not be re-created by a late turn read. The returned object is
        # deliberately ephemeral; save() rejects it while the tombstone is active.
        if sid in _DELETED_SESSIONS:
            return {"bot": None, "title": None, "messages": [], "model": None,
                    "pending": None, "approval": None}
        return new_session(sid, bot=sid)
    s = d[sid]
    s.setdefault("messages", []); s.setdefault("pending", None); s.setdefault("model", None)
    s.setdefault("bot", None); s.setdefault("title", "Chat")
    # A session used to store DEFAULT_MODEL whether or not anyone had chosen it, which pinned every
    # chat to the default and hid the model set on the bot. An unset model now means "the bot's own".
    if s["model"] == DEFAULT_MODEL: s["model"] = None
    return s
def peek(sid):
    """A chat as it is stored, without the side effect of making one.

    `load` creates and persists an empty session for an id it does not know, which is right for a
    POST that names a bot or a room and wrong for a GET: `/api/history?session=<anything>` used to
    mint a chat on disk and in memory for every id a caller cared to invent, so anyone on the LAN
    could grow the store without bound. A read of an unknown chat is the empty chat it is."""
    return (_all_sessions() or {}).get(sid) or {"bot": None, "title": None, "messages": [],
                                                "pending": None, "model": None, "approval": None}
def save(sid, s):
    s["ts"] = time.time()          # when this chat last moved — the chat list's order and its clock
    # Under the lock, with the write: a first save for a new chat adds a key, and `_write_sessions`
    # serializes the whole store while holding the same lock. A late write from a deleted turn is
    # refused, so its final report cannot resurrect a deleted session.
    with _SESS_LOCK:
        epoch = getattr(_SESSION_CTX, "epoch", None)
        if sid in _DELETED_SESSIONS:
            # A fresh direct save is an explicit recreation (the normal turn path calls new_session
            # first). A stale turn has an epoch and is rejected instead of resurrecting the chat.
            if epoch is not None or sid in STEER: return False
            _DELETED_SESSIONS.pop(sid, None); _SESSION_EPOCH[sid] = _SESSION_EPOCH.get(sid, 0) + 1
        if epoch is not None and epoch != _SESSION_EPOCH.get(sid, epoch): return False
        d = _all_sessions(); d[sid] = s; _write_sessions(d)
    _notify(sid)                   # ...and whoever else is looking at this chat hears about it
    return True
def drop_session(sid, scoped=None):
    """A deleted bot or company leaves no orphan conversation behind. A session id is a company's
    room (`<chan>`), a bot's chat inside it (`<chan>/<bot>`), or a bot with no company (`<bot>`).
    `scoped` names the end that is going: "channel" takes the room and the chats inside it, "bot"
    takes that bot's chats in every company; both take the bare id. It is explicit rather than
    inferred because a bot and a company may share a slug, and then only the caller knows which of
    the two a bare id means. Dropping only the bare id is what stranded `<chan>/<bot>` transcripts."""
    # Both maps are copied under the lock: a turn in flight adds keys to `_CTX` and `_all_sessions`,
    # and building the set over the live dict raised "dictionary changed size during iteration" — which
    # turned a delete into a 500 whenever it landed mid-turn.
    with _SESS_LOCK:
        d = _all_sessions()
        keys = set(d) | ctx_keys()
    # `_CTX` is in the union so a chat that was measured but never written to disk is cleaned too.
    dead = [k for k in keys
            if k == sid
            or (scoped != "bot" and k.startswith(sid + "/"))
            or (scoped != "channel" and k.endswith("/" + sid))]
    if dead:
        with _SESS_LOCK:                                   # removing keys is the same size-change hazard
            for k in dead:
                # Tombstone only an active turn: an idle deletion needs no guard, while an in-flight
                # turn may call load/save after this point and must not recreate the deleted chat.
                # A live turn is exactly what `/api/stop` treats as live: `STEER[k]` exists for its
                # whole length, and the held lock covers the instant before that. A leftover `_CTX`
                # measurement is *not* a turn — treating it as one leaked a Stop onto a chat deleted
                # while idle, so the next turn on that id landed before it began.
                lk = RUNNING.get(k)
                held = False
                if lk is not None:
                    held = not lk.acquire(blocking=False)
                    if not held: lk.release()
                active = k in STEER or k in APPROVAL or held
                if active:
                    _DELETED_SESSIONS[k] = time.time()
                    _SESSION_EPOCH[k] = _SESSION_EPOCH.get(k, 0) + 1
                    STOP.add(k); STEER_CLOSED.add(k)
                    waiter = APPROVAL.get(k)
                    if waiter: waiter["event"].set()
                d.pop(k, None); ctx_pop(k)           # a deleted chat leaves no measurement behind
                # ...nor a lock, but only one nothing is holding. A turn runs under this very object
                # for its whole length, and taking it away mid-turn let a chat re-created on the same
                # id — the panel does exactly that when a bot is deleted and added back — get a fresh
                # lock and start a second turn beside the one still going, the two then sharing one
                # APPROVAL waiter and clobbering each other's transcript. A lock a live turn still
                # holds is left where it is: it costs one entry for the life of the process, and a
                # chat re-created on that id finds the same lock, which is the point of keeping it.
                # The instant between a turn being handed the lock and taking it is still open;
                # closing that would mean holding `_running_lock` across the turn's start.
                lk = RUNNING.get(k)
                if lk is not None and not lk.acquire(blocking=False):
                    continue                        # a live turn holds it: it goes when that turn does
                RUNNING.pop(k, None)                # popped while held, so no turn slips in between
                if lk is not None: lk.release()
            _write_sessions(d, keep_tombstones=True)
        # A watcher looking at a chat that has just been deleted is told it is gone, so the other
        # device can leave it rather than sit on a transcript the server would happily re-create.
        for k in dead: _notify(k, "gone")

def clear_chat(sid):
    """Start a new session for one chat: the transcript goes, nothing else does.

    Memory is not part of a session — it lives in `data/memory/<bot>.md` and is read fresh on every
    turn — and neither is a bot's work log, so both survive. That is the whole point: a cleared chat
    is a clean conversation with teammates who still know what the project is about. The chat's own
    model pick and approval level survive too, so clearing can never quietly loosen a chat that was
    set to Plan only. Refused while a turn is still running in this chat, so a turn in flight cannot
    write its reply into the transcript that replaced it."""
    lock = _session_lock(sid)
    if not lock.acquire(blocking=False): return False
    try:
        if sid not in _all_sessions(): return True   # nothing to clear, and no phantom session invented
        st = load(sid); st["messages"] = []; st["pending"] = None; st.pop("ctx", None); save(sid, st)
        ctx_pop(sid)                                 # a new session starts its context panel over too
    finally:
        lock.release()
    return True

def chat_list():
    """Every conversation with something in it, newest first — what the app's chat search reads.
    A row names its chat exactly as the transcript's own header does, so the list and the title above
    the transcript cannot disagree about what a chat is called."""
    bots = load_bots(); chans = load_channels()
    out = []
    for sid, st in _sessions_snapshot():
        msgs = st.get("messages") or []
        if not msgs: continue
        ch, solo = resolve_session(sid, st.get("bot"), chans, bots)
        # `solo` is set for a bot's own chat whether or not it sits inside a company, so the bot is
        # what names the row and only the room itself is named for the company. Reading the channel
        # first is what put the company's name on every direct chat with a bot inside one.
        if solo: name, kind = ((bot_by_id(bots, solo) or {}).get("name") or solo), "bot"
        elif ch is not None: name, kind = ch["name"], "room"
        else: name, kind = sid, "bot"
        last = next(((m.get("content") or "").strip() for m in reversed(msgs) if (m.get("content") or "").strip()), "")
        out.append({"id": sid, "name": name, "kind": kind, "title": st.get("title") or name,
                    "last": last[:160], "count": len(msgs), "ts": st.get("ts") or 0})
    out.sort(key=lambda r: r["ts"], reverse=True)
    return out

def truncate_chat(sid, keep):
    """Drop everything after `keep` messages — how an edited or retried message replaces what came
    after it, rather than piling a second attempt on top of the first. Refused mid-turn for the same
    reason clearing is: the running turn would write its reply into a transcript that moved."""
    lock = _session_lock(sid)
    if not lock.acquire(blocking=False): return False
    try:
        if sid not in _all_sessions(): return True
        st = load(sid); st["messages"] = (st.get("messages") or [])[:max(0, keep)]
        st["pending"] = None; save(sid, st)
    finally:
        lock.release()
    return True

# ---------------------------------------------------------------- memory (per-bot markdown)
def _read_bounded(path, limit_lines=200, limit_bytes=24000):
    if not os.path.isfile(path): return ""
    with open(path, encoding="utf-8", errors="replace") as f:
        txt = f.read(limit_bytes * 4)          # bounded: a runaway file cannot exhaust RAM
    return "\n".join(txt.splitlines()[:limit_lines])[:limit_bytes]

_NOTES_LOCK = threading.Lock()
def _append_bounded(path, line, header, max_lines):
    """Append one entry, then keep the header plus the freshest entries, so the file stays bounded.
    The read-modify-write is under a lock: two turns appending to the same bot's notes at once (a
    bot in two rooms, or `_learn` landing while a turn writes) could otherwise lose one side's line
    at the trim-and-rewrite."""
    with _NOTES_LOCK:
        fresh = not os.path.isfile(path)
        with open(path, "a", encoding="utf-8") as f:
            if fresh: f.write(header)
            f.write("\n" + line.rstrip() + "\n")
        lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
        if len(lines) > max_lines:
            open(path, "w", encoding="utf-8").write("\n".join(lines[:1] + lines[-(max_lines - 1):]) + "\n")

# A bot id becomes a filename. One slug rule for both note files, so a memory note and a work log for
# the same bot can never land under two different names.
def _doc_path(d, bid): return os.path.join(d, re.sub(r"[^a-zA-Z0-9_-]", "_", bid) + ".md")
def mem_path(bid): return _doc_path(MEMDIR, bid)
def mem_read(bid, limit_lines=200, limit_bytes=24000): return _read_bounded(mem_path(bid), limit_lines, limit_bytes)
MEM_MAX_LINES = 400
def mem_append(bid, note):
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    _append_bounded(mem_path(bid), f"- [{stamp}] {note.strip()}", "# Notes\n", MEM_MAX_LINES)
def mem_write(bid, text):
    # The same lock `_append_bounded` holds: a save from the UI must not truncate the file in the
    # middle of a learning note's read-modify-write, which would silently drop that note.
    with _NOTES_LOCK:
        if text and text.strip(): open(mem_path(bid), "w", encoding="utf-8").write(text)
        elif os.path.isfile(mem_path(bid)): os.remove(mem_path(bid))   # clearing notes leaves no empty file

# ---------------------------------------------------------------- per-bot work log
# Every bot keeps a log of the work it actually did — direct or delegated — so the detail stays
# with the bot that produced it and a room's transcript stays a list of reports. Bounded like the
# memory notes: the header and the freshest turns survive.
LOGDIR = os.path.join(DATA, "logs")
os.makedirs(LOGDIR, exist_ok=True)
LOG_MAX_LINES = 400
def log_path(bid): return _doc_path(LOGDIR, bid)
def log_read(bid, limit_lines=200, limit_bytes=24000): return _read_bounded(log_path(bid), limit_lines, limit_bytes)
def log_append(bid, text): _append_bounded(log_path(bid), text, "# Work log\n", LOG_MAX_LINES)
def log_turn(sid, bid, task, out, depth):
    """One turn -> one block. A turn that produced no real report (a router error, a dead end)
    is not work done, so it is not logged."""
    report = (out.get("text") or "").strip()
    if not report or report.startswith("[model error"): return
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    head = "## " + stamp + " · " + (sid or bid) + (" · delegated" if depth else " · direct")
    did = ", ".join(dict.fromkeys(out.get("used") or [])) or "no tools"
    # Why the turn ended, when it did not end cleanly — the question the log is read to answer.
    stop = {"max_steps": "hit the step limit", "empty": "the model returned nothing",
            "stalled": "the model stopped answering mid-step"}.get(out.get("stop") or "")
    log_append(bid, head + "\n- **Task:** " + (task or "").strip().replace("\n", " ")[:400] +
               "\n- **Did:** " + did + "\n- **In:** " + bot_field_dir(bid) +
               ("\n- **Stopped:** " + stop if stop else "") +
               "\n- **Report:** " + report[:2000])

# ---------------------------------------------------------------- self-learning
# After a bot does real work it reflects once on its own run and writes the durable
# lessons to its memory file, so the next session starts smarter without being told.
LEARN_SYS = ("You are the long-term memory of an AI teammate. Below is a task it just completed and the "
             "tools it really used. Extract the durable knowledge this run produced, for its FUTURE self. "
             "Record up to 3 items, one per line, max 140 chars, no bullets: concrete environment facts "
             "(paths, interpreters, versions, what is installed), working commands or recipes that "
             "succeeded, and gotchas, constraints or user preferences revealed. Be specific and reusable. "
             "Only reply NONE if the run taught nothing beyond the task itself. Reply with the lines only.")
def reflect(bot, task, report, used):
    msgs = [{"role": "system", "content": LEARN_SYS},
            {"role": "user", "content": "Task: " + (task or "")[:800]
             + "\n\nTools used: " + ", ".join(used[:20])
             + "\n\nWhat it reported: " + (report or "(nothing)")[:1200]}]
    model = bot.get("model") or DEFAULT_MODEL
    out = ""
    for _ in range(2):                                 # the router occasionally returns empty content — one retry
        try: out = (chat(model, msgs, max_tokens=220).get("content") or "").strip()
        except Exception: return []
        if out and not out.startswith("[model error"): break
    if not out or out.startswith("[model error") or out.upper().startswith("NONE"): return []
    notes = []
    for line in out.splitlines():
        n = re.sub(r"^\s*(?:[-*\u2022]|\d+[.)])\s*", "", line).strip()
        if len(n) > 8 and not n.upper().startswith("NONE"): notes.append(n[:200])
    return notes[:3]

def _learn(bot, bid, task, out):
    """Reflect on a finished turn and keep whatever is durable, returning the notes for the client.
    Called by the turn caller *after* the report has been emitted, so this extra model call is never
    on the critical path of the answer — and only when the turn actually did something, because a
    greeting or a one-line answer has nothing to learn and the round-trip would be a per-turn tax."""
    if not (bot and bot.get("memory") and len(out.get("used") or []) >= 2): return []
    notes = reflect(bot, task, out.get("text", ""), out.get("used") or [])
    for n in notes: mem_append(bid, n)
    return notes

# ---------------------------------------------------------------- shell sandbox
# Each channel can point its bots at one repo folder (`folder` on the channel). The
# thread-local below is what makes that per-turn instead of global: the SSE handler runs a
# whole turn in one thread, so setting it at the start of the turn routes every shell and
# file tool of that turn — including delegations — into the right repo, and nowhere else.
_WORK = threading.local()
def resolve_folder(folder):
    """A channel's folder -> an absolute path that exists, or None. Blank means the shared sandbox."""
    f = (folder or "").strip()
    if not f: return None
    f = os.path.expanduser(f)
    if not os.path.isabs(f): f = os.path.join(SANDBOX, f)
    f = os.path.realpath(f)
    return f if os.path.isdir(f) else None
def work_dir(): return getattr(_WORK, "dir", None) or SANDBOX
def turn_repo():
    """The repo this turn is pinned to — the company's folder, or the sandbox. A bot's own field
    is a subfolder of it, so it stays one however deep a delegation goes."""
    return getattr(_WORK, "base", None) or SANDBOX
def set_work_dir(folder):
    _WORK.base = resolve_folder(folder)     # the repo itself, for bot_field_dir
    _WORK.dir = _WORK.base
def bot_field_dir(bid):
    """A bot's own field: a subfolder of the repo the turn runs in, named after the bot.

    A room's members share the company's repo but never share a folder, so one bot's scratch files
    can never be mistaken for another's, and the room's transcript only ever has to carry reports.
    With no repo set the field lives under the sandbox. Created on demand.
    ponytail: one level deep (`<repo>/<bot>`); give a bot its own absolute `folder` if a team ever
    needs a bot working at a repo root."""
    base = turn_repo()
    p = os.path.join(base, re.sub(r"[^a-zA-Z0-9_-]", "_", bid or "bot") or "bot")
    try: os.makedirs(p, exist_ok=True)
    except OSError: return base
    return p
def list_dirs(path):
    """One folder's subdirectories, for the repo picker. Names only — never file names,
    never contents. A path that does not exist falls back to its nearest existing parent,
    so a half-typed or deleted path still opens somewhere the user can navigate from."""
    raw = (path or "").strip() or "~"
    p = os.path.realpath(os.path.expanduser(raw))
    while not os.path.isdir(p):
        up = os.path.dirname(p.rstrip(os.sep))
        if up == p: break
        p = up
    home = os.path.realpath(os.path.expanduser("~"))
    try:
        with os.scandir(p) as it:
            dirs = [e.name for e in it if e.is_dir(follow_symlinks=True)]
    except OSError as e:
        return {"ok": False, "error": f"cannot read {p}: {e.strerror or e}", "path": p, "dirs": []}
    # Dotfolders last: they are rarely a repo, but hiding them would block ~/.config-style paths.
    dirs.sort(key=lambda n: (n.startswith("."), n.lower()))
    parent = os.path.dirname(p.rstrip(os.sep))
    return {"ok": True, "path": p, "parent": parent if parent != p else "", "home": home,
            "dirs": dirs[:500], "more": max(0, len(dirs) - 500)}
def _in_sandbox(path):
    """A tool path -> an absolute path inside the working dir, or None if it escapes it.

    Absolute paths are honoured, not re-rooted: a path outside the repo is refused rather
    than quietly turning into a file with a strange name inside the repo.
    """
    root = os.path.realpath(work_dir())    # both ends resolved, so a symlinked data dir still matches
    raw = (path or "").strip()
    p = os.path.realpath(raw if os.path.isabs(raw) else os.path.join(root, raw))
    return p if p == root or p.startswith(root + os.sep) else None
def _data_bytes(s):
    """Decode a `data:<type>;base64,<payload>` URL, or None if it is not one."""
    if not isinstance(s, str) or not s.startswith("data:") or "," not in s: return None
    try: return base64.b64decode(s.split(",", 1)[1])
    except Exception: return None
SHELL_OUT_CAP = 6000        # characters of output a bot is shown
SHELL_READ_CAP = 1 << 20    # bytes actually buffered before the rest is dropped
def run_shell(cmd, timeout=45):
    if not isinstance(cmd, str):
        return "(error: run_shell command must be a string)", 1
    if shell_refused(cmd):
        return "(refused: %s)" % SECRET_REFUSAL, 1
    # A bot may ask for longer than the 45s default (an install, a test run). Only the *top* is
    # clamped: a huge number is a lever on the turn's own wall clock, a small one is harmless.
    try: timeout = max(1, min(int(timeout), 600))
    except Exception: timeout = 45
    # `start_new_session` puts the command in its own process group, so the timeout can kill the whole
    # tree and not just the `sh` — a `sleep 1000 &` used to outlive the turn forever. Output is read
    # through a bounded buffer: `yes` or a chatty build inside the window used to be buffered whole
    # (hundreds of MB, up to four at once) before the 6000-char trim was applied.
    try:
        p = subprocess.Popen(cmd, shell=True, cwd=work_dir(), start_new_session=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except Exception as e:
        return f"(error: {e})", 1
    try: pgid = os.getpgid(p.pid)
    except Exception: pgid = None
    buf = bytearray(); fd = p.stdout.fileno(); deadline = time.time() + timeout; rc = None
    while True:
        left = deadline - time.time()
        if left <= 0:                                          # over the clock: kill the whole tree
            rc = 124
            try: os.killpg(pgid, signal.SIGKILL)
            except Exception:
                try: p.kill()
                except Exception: pass
            try: p.wait(timeout=5)
            except Exception: pass
            break
        r, _, _ = select.select([fd], [], [], min(left, 0.25))
        if r:
            chunk = os.read(fd, 65536)
            if not chunk:                                      # the shell and all it started have gone
                rc = p.wait(); break
            room = SHELL_READ_CAP - len(buf)
            if room > 0: buf += chunk[:room]                   # past the cap: drained, not kept
        elif p.poll() is not None:
            # The shell is gone but the pipe is still open — a `&` child holds it. Stop reading and
            # leave it running, which is what a bot that backgrounds a server asked for.
            rc = p.returncode; break
    try: p.stdout.close()
    except Exception: pass
    text = bytes(buf).decode("utf-8", "replace")
    if rc == 124: return f"(timed out after {timeout}s)", 124
    return (text[:SHELL_OUT_CAP] or "(no output)"), rc
# Classification is deliberately stricter than the shell grammar. The command still runs through
# `/bin/sh` for compatibility with Full access, so anything that cannot be proven to be one read-only
# command is risky and therefore gated. In particular, do not turn this back into a prefix regex: a
# prefix lets `find . -delete`, `sort in -o out` and `env sh -c ...` through.
READ_ONLY_COMMANDS = frozenset((
    "ls", "cat", "head", "tail", "wc", "pwd", "echo", "date", "whoami", "id", "uname",
    "df", "free", "uptime", "grep", "rg", "find", "file", "stat", "du", "tree", "sort",
    "uniq", "cut", "tr", "env", "which", "type",
))
GIT_READ_ONLY = frozenset(("status", "log", "diff", "show", "branch"))
SHELL_META = re.compile(r"[;&|`$<>()\n\r*?\[\]{}#]")
_READ_ONLY_ACTIONS = frozenset((
    "-delete", "--delete", "-exec", "--exec", "-execdir", "--execdir", "-ok", "--ok",
    "-okdir", "--okdir", "-fls", "-fprint", "-fprint0", "-fprintf", "--output", "-output",
))
_GIT_WRITE_ACTIONS = frozenset((
    "-d", "-D", "-m", "-M", "-c", "-C", "--delete", "--move", "--copy",
    "--set-upstream", "--set-upstream-to", "--edit-description", "--exec", "--ext-diff",
    "--textconv",
))

def _shell_words(cmd):
    """Return tokens for one conservative shell command, or None when it is not plain text."""
    if not isinstance(cmd, str) or not cmd or "\x00" in cmd or SHELL_META.search(cmd): return None
    try: words = shlex.split(cmd, posix=True)
    except (TypeError, ValueError): return None
    if not words or any(word.startswith("~") for word in words): return None
    return words

def _has_output_option(words):
    """Reject options that make a nominally read-only utility write a named file."""
    for i, word in enumerate(words):
        if word in ("--output", "-output", "--output-file", "-output-file"):
            return True
        if word.startswith(("--output=", "-output=", "--output-file=", "-output-file=")):
            return True
        if word == "-o":
            # `-o FILE` is an output path for sort/uniq/git diff; a trailing -o is invalid anyway.
            if i + 1 < len(words): return True
        if word.startswith("-o") and word != "-o" and not word.startswith("--"):
            return True
    return False

def _names_outside_path(args):
    """True when an argument is an absolute (or `~`-rooted) path that leaves the working directory.

    The read-only allowlist answers "does this command only read?". It must also answer "read what?":
    `cat /etc/hosts` reads, and so does a prompt-injected `cat ~/.ssh/id_rsa` — the bot's own secret
    store is refused outright by `names_secrets`, but nothing else outside the sandbox is. A read-only
    command that reaches outside is not the case this list means, so it takes the approval card. Paths
    *inside* the repo stay frictionless, and a flag (`-C`, `--pretty=…`) is skipped: the path it names
    is the next bare word and is checked there."""
    root = os.path.realpath(work_dir())
    for a in args:
        if a.startswith("-") or not (a.startswith("/") or a.startswith("~")): continue
        p = os.path.realpath(os.path.expanduser(a))
        if p != root and not p.startswith(root + os.sep): return True
    return False

def _safe_command_words(words):
    if not words: return False
    executable = words[0]
    if not executable or executable.startswith("-"): return False
    name = os.path.basename(executable)
    # Do not let a repo-provided `./ls` (or an arbitrary absolute path named `ls`) masquerade as the
    # trusted utility. The shell's PATH lookup is the only executable selection this allowlist permits.
    if executable != name: return False
    args = words[1:]
    if _names_outside_path(args): return False
    if name == "git":
        # Keep git's global options out of this allowlist. A subcommand must be the next word.
        if not args or args[0] not in GIT_READ_ONLY: return False
        subcommand, args = args[0], args[1:]
        if any(a in _GIT_WRITE_ACTIONS or a.startswith(("--exec=", "--ext-diff=", "--textconv=")) for a in args):
            return False
        if subcommand == "branch" and any(a in ("--delete", "--move", "--copy") or a.startswith(("-d", "-D", "-m", "-M", "-c", "-C")) for a in args):
            return False
        return not _has_output_option(args)
    if name not in READ_ONLY_COMMANDS: return False
    if any(a in _READ_ONLY_ACTIONS or a.startswith(("-exec=", "--exec=", "-execdir=", "--execdir=", "--output=", "-output=")) for a in args):
        return False
    if name == "find" and any(a in ("-o", "-or", "-exec", "-execdir", "-delete") for a in args):
        return False
    if name == "env":
        # `env` can replace the environment and launch any executable. Only its harmless listing form,
        # unset flags, and a read-only command are admitted; assignments are rejected conservatively.
        i = 0
        while i < len(args):
            a = args[i]
            if a == "--": i += 1; break
            if a in ("-i", "--ignore-environment"): i += 1; continue
            if a in ("-u", "--unset"):
                if i + 1 >= len(args): return False
                i += 2; continue
            if a.startswith("--unset="): i += 1; continue
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", a): return False
            break
        if i < len(args): return _safe_command_words(args[i:])
        return True
    return not _has_output_option(args)

def _shell_args_error(args):
    if not isinstance(args, dict): return "(error: run_shell arguments must be an object)"
    if not isinstance(args.get("command"), str): return "(error: run_shell command must be a string)"
    return ""

def is_risky(cmd):
    words = _shell_words(cmd)
    return not _safe_command_words(words) if words else True


# The app's own secret store holds the pairing token and the relay secret, and it sits beside the
# sandbox — so `cat <DATA>/access_token` was classified read-only and handed a tool call the whole
# API, no approval card. No bot has a legitimate reason to read any of it, so this is a refusal and
# not a card: it holds whatever the level. A command that names the store by its full path, or by one
# of the two names nothing else uses, is turned away. A relative path into the store that names no
# secret (a plain `data/bots.json`, say) is left alone, which keeps ordinary work in the repo.
SECRET_NAMES = ("access_token", "relay_secret")
SECRET_REFUSAL = "that command reaches for the app's own secret store, which is not yours to read"
def names_secrets(cmd):
    c = cmd.replace("\\", "/")
    # Both forms: the command names the path as written, and on macOS `/tmp` is a symlink to
    # `/private/tmp`, so the resolved form alone would miss a literal path into the store.
    for d in {DATA, os.path.realpath(DATA)}:
        d = (d or "").replace("\\", "/")
        if d and d in c: return True
    return any(w in c for w in SECRET_NAMES)
def shell_refused(cmd):
    """True when `run_shell` will turn this command away whatever the user answers.

    The approval card is a question; a refusal is not one. An absolute path into the store is both
    out of the sandbox (so it reads as risky and would raise a card) and forbidden outright (so the
    answer cannot change the outcome) — and a card that approves nothing is one the user learns to
    click past, while a bot that keeps reaching for the store parks the turn on it for the rest of
    the budget. `run_shell` returns the refusal and the agent loop skips the card, both from here,
    so the two can never disagree about which commands are refused.
    """
    return isinstance(cmd, str) and names_secrets(cmd)

# The other way round the same refusal. The browser tools run JavaScript in a page this process
# controls, and a `file://` page is a page like any other — `browser_open file://<DATA>/access_token`
# and one `browser_eval` handed a bot the pairing token, which the relay then made reachable from the
# phone. The tools are for the web, so a scheme that is not http(s) is refused outright rather than
# filtered, and a URL that resolves into the store or the sandbox's parent is refused even then.
def browser_url_guard(url):
    """Why a browser tool must not open this URL, or "" when it may. A bare host is a web host."""
    s = (url or "").strip()
    m = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*):", s)
    if m and m.group(1).lower() not in ("http", "https"):
        return "a %s: page is not yours to open — the browser tools are for the web" % m.group(1).lower()
    path = urlparse(s if m else "https://" + s).path
    if not path: return ""
    p = os.path.realpath(os.path.expanduser(path))
    for d in {DATA, os.path.realpath(DATA), os.path.dirname(os.path.realpath(SANDBOX))}:
        if d and (p == d or p.startswith(d + os.sep)):
            return "that URL points into this app's own data folder, which is not yours to read"
    return ""

# ---------------------------------------------------------------- browser (computer use)
# ---------------------------------------------------------------- raw CDP (Electron webviews)
# Playwright cannot see <webview> targets, and Electron apps such as ZenPilot show every
# logged-in profile as one. So for those we speak the DevTools Protocol directly: a stdlib
# websocket client, one attach, and the same page-shaped surface the browser tools already use.
class _WS:
    def __init__(self, url, timeout=20):
        assert url.startswith("ws://"), url
        hostport, _, path = url[5:].partition("/")
        host, _, port = hostport.partition(":")
        self.s = socket.create_connection((host, int(port or 80)), timeout=timeout)
        # A refused or half-open handshake must close the socket it opened: the browser panel retries
        # every few seconds, and a leak here was one stranded fd per failed attach.
        try:
            key = base64.b64encode(os.urandom(16)).decode()
            self.s.sendall(("GET /%s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                            "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n"
                            % (path, hostport, key)).encode())
            buf = b""
            while b"\r\n\r\n" not in buf:
                d = self.s.recv(4096)
                if not d: raise ConnectionError("handshake closed")
                buf += d
            head, _, self.buf = buf.partition(b"\r\n\r\n")
            if b"101" not in head.split(b"\r\n")[0]:
                raise ConnectionError("handshake refused: %s" % head[:120].decode("utf-8", "replace"))
        except Exception:
            try: self.s.close()
            except Exception: pass
            raise

    def _take(self, n, deadline=None):
        # A frame only exists once all of it has arrived, and a peer that trickles a byte at a time
        # never lets one arrive. `recv` on its own cannot catch that: the socket timeout is per read,
        # so every trickled byte resets it — the same trap as the model path, and here it pins the one
        # browser thread, which silently turns every later browser call into "(browser timeout)". So
        # the caller's own clock is checked between reads, and a frame that will not complete inside
        # the call's budget ends the call instead of the thread.
        while len(self.buf) < n:
            if deadline is not None and time.time() > deadline:
                raise TimeoutError("no complete frame within the call's budget")
            d = self.s.recv(65536)
            if not d: raise ConnectionError("closed")
            self.buf += d
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _frame(self, op, data):
        hdr = bytearray([0x80 | op]); n = len(data)
        if n < 126: hdr.append(0x80 | n)
        elif n < 65536: hdr.append(0x80 | 126); hdr += struct.pack(">H", n)
        else: hdr.append(0x80 | 127); hdr += struct.pack(">Q", n)
        mask = os.urandom(4); hdr += mask
        self.s.sendall(bytes(hdr) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def send(self, text): self._frame(0x1, text.encode())

    def recv(self, deadline=None):
        parts = []
        while True:
            b0, b1 = self._take(2, deadline)
            fin, op, ln = b0 & 0x80, b0 & 0x0F, b1 & 0x7F
            if ln == 126: ln = struct.unpack(">H", self._take(2, deadline))[0]
            elif ln == 127: ln = struct.unpack(">Q", self._take(8, deadline))[0]
            mk = self._take(4, deadline) if b1 & 0x80 else None
            data = self._take(ln, deadline)
            if mk: data = bytes(b ^ mk[i % 4] for i, b in enumerate(data))
            if op == 0x9: self._frame(0xA, data); continue
            if op == 0xA: continue
            if op == 0x8: raise ConnectionError("closed by peer")
            parts.append(data)
            if fin: return b"".join(parts).decode("utf-8", "replace")

    def close(self):
        try: self._frame(0x8, b"")
        except Exception: pass
        try: self.s.close()
        except Exception: pass


def cdp_targets(endpoint):
    """What a running browser has open, over plain HTTP. Listing targets needs no websocket, so
    this works even when all we want to know is which profiles ZenPilot has."""
    return json.load(urllib.request.urlopen(endpoint.rstrip("/") + "/json/list", timeout=10))

class _CDP:
    """DevTools Protocol client: HTTP for the target list, one websocket for the commands."""

    def __init__(self, endpoint):
        self.ep = endpoint.rstrip("/")
        ver = json.load(urllib.request.urlopen(self.ep + "/json/version", timeout=10))
        self.ws = _WS(ver["webSocketDebuggerUrl"]); self._id = 0

    def targets(self):
        return cdp_targets(self.ep)

    def cmd(self, method, params=None, session=None, timeout=30, sock_timeout=None):
        self._id += 1; mid = self._id
        msg = {"id": mid, "method": method, "params": params or {}}
        if session: msg["sessionId"] = session
        old = None
        if sock_timeout is not None:
            old = self.ws.s.gettimeout(); self.ws.s.settimeout(sock_timeout)
        try:
            self.ws.send(json.dumps(msg))
            end = time.time() + timeout
            while time.time() < end:
                # `end` rides into the read as well, so the clock bounds the frame that is being
                # assembled and not only the gaps between frames (see `_WS._take`).
                m = json.loads(self.ws.recv(deadline=end))
                if m.get("id") == mid:
                    if "error" in m: raise RuntimeError("%s -> %s" % (method, m["error"]))
                    return m.get("result", {})
            raise TimeoutError(method)
        finally:
            if old is not None:
                try: self.ws.s.settimeout(old)
                except Exception: pass

    def attach(self, target_id):
        return self.cmd("Target.attachToTarget", {"targetId": target_id, "flatten": True})["sessionId"]

    def detach(self, session_id):
        """Close a session opened by `attach`. Every attach the browser holds until it is closed, so a
        screenshot that leaves its session open leaks one per call — and the Computer panel polls."""
        try: self.cmd("Target.detachFromTarget", {"sessionId": session_id})
        except Exception: pass

    def close(self): self.ws.close()


class _El:
    def __init__(self, page, selector): self.page = page; self.selector = selector

    def evaluate(self, js):
        if "=>" in js or js.lstrip().startswith(("function", "(")):
            return self.page._ev("(%s)(document.querySelector(%s))" % (js, json.dumps(self.selector)))
        return self.page._ev(js)

class _Count:
    """The one method `Browser.click` needs from a Playwright locator: how many elements match."""
    def __init__(self, page, selector): self.page = page; self.selector = selector

    def count(self):
        return self.page._ev("document.querySelectorAll(%s).length" % json.dumps(self.selector)) or 0


class CDPPage:
    """Playwright-shaped page backed by raw CDP, for targets Playwright will not surface."""

    KEYS = {"Enter": 13, "Tab": 9, "Escape": 27, "Backspace": 8, "ArrowDown": 40, "ArrowUp": 38,
            "ArrowLeft": 37, "ArrowRight": 39, " ": 32}

    def __init__(self, cdp, session):
        self.cdp = cdp; self.sid = session; self.keyboard = self._KB(self)

    class _KB:
        def __init__(self, page): self.page = page
        def press(self, key):
            code = CDPPage.KEYS.get(key, ord(key[0]) if key else 0)
            for typ in ("keyDown", "keyUp"):
                try:
                    self.page.cdp.cmd("Input.dispatchKeyEvent",
                                      {"type": typ, "key": key, "windowsVirtualKeyCode": code,
                                       "text": "\r" if key == "Enter" else (key if len(key) == 1 else "")},
                                      session=self.page.sid)
                except Exception: pass

    def _ev(self, expr, arg=None, timeout=30):
        if "=>" in expr or expr.lstrip().startswith(("function", "async", "(")):
            js = "(%s)" % expr
            if arg is not None: js += "(%s)" % json.dumps(arg)
        else: js = expr
        r = self.cdp.cmd("Runtime.evaluate",
                         {"expression": js, "returnByValue": True, "awaitPromise": True},
                         session=self.sid, timeout=timeout)
        return r.get("result", {}).get("value")

    def evaluate(self, expr, arg=None): return self._ev(expr, arg)

    @property
    def url(self): return self._ev("location.href") or ""

    def title(self): return self._ev("document.title") or ""

    def wait_for_timeout(self, ms): time.sleep(max(0, ms) / 1000.0)

    def goto(self, url, wait_until=None, timeout=45000):
        self.cdp.cmd("Page.navigate", {"url": url}, session=self.sid)
        # `wait_until` is honoured, mapped onto the one signal a CDP page can read: "domcontentloaded"
        # is readyState "interactive", "load" is "complete". "interactive" is also accepted for a
        # "complete" wait, because a page whose sub-resources never finish (a tracker that hangs, an
        # endless long-poll) holds readyState at "interactive" for ever — waiting for "complete" then
        # burned the whole 45s on a page that was ready to read, and the caller settles for the paint.
        want = ("complete",) if wait_until == "load" else ("interactive", "complete")
        end = time.time() + timeout / 1000.0
        while time.time() < end:
            try:
                if self._ev("document.readyState", timeout=8) in want: break
            except Exception: pass
            time.sleep(0.15)
        return self

    def go_back(self, wait_until=None, timeout=30000):
        # The parameters mirror the Playwright page's signature so one call site serves both engines;
        # over CDP the back navigation is followed by a short settle rather than a readiness probe.
        try: self._ev("history.back()")
        except Exception: pass
        time.sleep(1.0)
        return self

    def inner_text(self, selector="body"):
        return self._ev("(s=>{const e=document.querySelector(s)||document.body;return e?e.innerText:''})(%s)"
                        % json.dumps(selector)) or ""

    def wait_for_selector(self, selector, timeout=12000, state="attached"):
        # `state` mirrors the Playwright page's signature so one call site serves both engines; over
        # CDP only presence ("attached") can be probed, which is the state every caller asks for.
        end = time.time() + timeout / 1000.0
        while time.time() < end:
            try:
                if self._ev("!!document.querySelector(%s)" % json.dumps(selector)): return _El(self, selector)
            except Exception: pass
            time.sleep(0.2)
        raise TimeoutError("no element matching %s" % selector)

    def locator(self, selector):
        # Playwright's page has this and `Browser.click` asks it how many elements a selector matches
        # before spending an actionability timeout on nothing; the shape is mirrored here for the same
        # reason `wait_for_selector` is, so one call site serves both engines.
        return _Count(self, selector)

    def click(self, selector, timeout=12000):
        self.wait_for_selector(selector, timeout=timeout).evaluate(
            "e=>{e.scrollIntoView({block:'center'});const r=e.getBoundingClientRect();"
            "const o={bubbles:true,cancelable:true,view:window,clientX:r.left+r.width/2,clientY:r.top+r.height/2};"
            "for(const t of ['pointerdown','mousedown','pointerup','mouseup','click'])"
            "e.dispatchEvent(t.startsWith('pointer')?new PointerEvent(t,o):new MouseEvent(t,o));return 1}")
        return self

    def fill(self, selector, text):
        self.wait_for_selector(selector)
        self._ev("(a)=>{const e=document.querySelector(a.s);if(!e)return '';e.focus();"
                 "const proto=e.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;"
                 "const d=Object.getOwnPropertyDescriptor(proto,'value');"
                 "if(d&&d.set)d.set.call(e,a.v);else e.value=a.v;"
                 "e.dispatchEvent(new Event('input',{bubbles:true}));"
                 "e.dispatchEvent(new Event('change',{bubbles:true}));return e.value}",
                 {"s": selector, "v": text})
        return self

    def screenshot(self, tries=(6, 8)):
        # Two quirks of webview targets: they live on their own surface (ask for the page, not the
        # surface), and the first capture after attaching can wait for a frame. Both attempts are
        # short on purpose. Zen Pilot paints one profile at a time and a <webview> that is not on
        # screen never produces a frame at all — so a long wait here is not patience, it is a panel
        # that hangs. Two quick tries, then say what is actually wrong.
        p = {"format": "png", "fromSurface": False}
        last = None
        for wait in tries:
            try:
                return base64.b64decode(
                    self.cdp.cmd("Page.captureScreenshot", p, session=self.sid, sock_timeout=wait)["data"])
            except Exception as e: last = e
        raise RuntimeError("this profile is not on screen in Zen Pilot — open it there to watch it work")

BROWSER_RETRY_S = 5          # at most how often a browser that failed to attach is retried
NO_PAGE_ERR = ("nothing is open to drive — open a profile in Zen Pilot (or a tab in that browser) "
               "and the screen appears")

def _drivable(url):
    """Whether a page is one the bots may drive. The browser's own chrome — the app shell of an
    Electron app such as Zen Pilot, or devtools — is not one: driving it would navigate away the
    window you are working in. A Zen Pilot profile is a <webview> target and is reached over raw
    CDP before this fallback ever runs, so a profile is still what the bots use."""
    return not (url or "").startswith(("file:", "devtools:", "chrome:", "chrome-extension:"))

def _host(u):
    """The bare site of a URL — no scheme, port, or leading www — so www.threads.com and threads.com
    count as one site. Which site a request needs is what decides which profile it must run in."""
    h = (urlparse(u or "").netloc or "").split(":")[0].lower()
    return h[4:] if h.startswith("www.") else h

def _fg_js(pid, name, svc):
    """The two expressions `Browser._foreground` runs in the Zen Pilot window, as (click, show).

    `click` brings one profile's sidebar row on screen; `show` asks whether it is on screen yet. Zen
    Pilot hides an inactive profile by putting `hidden` on its container, not on the <webview> itself —
    and a <webview> carries no height of its own — so "on screen" is "no ancestor still says
    display:none". A profile in lazy memory mode is not rendered at all, which reads the same way.
    Module level so tests/test_foreground.py runs this exact JS rather than a copy of it."""
    vis = ("const vis=pid=>{const el=[...document.querySelectorAll('webview')]"
           ".find(x=>x.partition==='persist:profile_'+pid);"
           "if(!el)return false;"
           "for(let n=el;n&&n!==document.body;n=n.parentElement){"
           "const c=getComputedStyle(n);if(c.display==='none'||c.visibility==='hidden')return false;}"
           "return true;};")
    click = ("(async()=>{const pid=%d,name=%s,svc=%s;" % (pid, json.dumps(name), json.dumps(svc))
             + vis +
             "if(vis(pid))return 'visible';"
             "const find=()=>[...document.querySelectorAll('button')].find(b=>{const s=b.querySelector('span.truncate');"
             "return s&&s.textContent.trim()===name;});"
             "let b=find();"
             "if(!b){[...document.querySelectorAll('button')].filter(x=>x.getAttribute('aria-expanded')==='false'"
             "&&svc&&x.textContent.includes(svc)).forEach(x=>x.click());"
             "await new Promise(r=>setTimeout(r,250));b=find();}"
             "if(!b)return 'no-row';b.click();return 'clicked';})()")
    return click, "(()=>{%s return vis(%d)})()" % (vis, pid)

class Browser:
    """One browser owned by a dedicated thread. Either we launch it, or we attach over CDP to a
    browser that is already running (ZenPilot), so the bots reuse profiles you are logged into and
    we open no extra window."""
    def __init__(self):
        self.q = queue.Queue(); self.ready = threading.Event()
        self.thread = None; self.ok = False; self.err = ""; self.url = ""; self.title = ""
        self.mode = "own"; self.cdp_url = ""; self.attached = False
        self.engine = ""; self.cdp = None; self.target_id = ""; self.last_try = 0.0
        self._cdp_owner = None                      # the thread whose cdp this is (see _run's sentinel)
        self._shot_id = ""; self._shot_at = 0.0     # the profile the Computer panel last drew
        self.owner = ""                             # the bot whose page is the one on screen (see _computer_scope)
        self._sh = None                             # CDP session on the app window itself
        self._no_profile = False                    # the last open() found no Zen Pilot profile for the site
        self.page = None                            # set by _attach; stays None in profiles mode until a site needs one
        # Everything Playwright hands us belongs to the thread that made it: the sync API refuses to
        # be touched from any other one, and refuses a second driver in the same one. A restart runs
        # the next browser in a new thread while the old one is still winding down, so the driver,
        # the throwaway browser and the saved profiles are all kept per thread and closed by the
        # thread that made them.
        self._thr = {}                              # thread -> {"pp": driver, "hb": browser, "hpage": page, "ctxs": {}}
    def _mine(self):
        """This thread's own Playwright holdings, made on first use."""
        return self._thr.setdefault(threading.current_thread(), {"pp": None, "hb": None, "hctx": None, "hpage": None, "ctxs": {}})
    def start(self):
        if self.thread and self.thread.is_alive(): return
        self.ready.clear(); self.ok = False; self.err = ""; self.attached = False
        self.q = queue.Queue()   # a fresh queue per thread: a restart must not leave two threads reading one
        self.thread = threading.Thread(target=self._run, args=(self.q,), daemon=True); self.thread.start()
        self.ready.wait(90)
    def restart(self):
        self.q.put(None)                      # the old thread drains its own queue and exits on this
        self.thread = None; self.last_try = 0.0
        # A changed profile name, routing table or headless setting has to actually take effect, and
        # those are read when a profile's browser is launched — so the warm ones go. Their cookies are
        # already on disk; the cost is a relaunch, nothing else. The closing happens in the old
        # thread, on the sentinel above: these browsers belong to it and it is the only thread that
        # can touch them.
        self.start()
        return {"ok": self.ok, "mode": self.mode, "attached": self.attached, "err": self.err}
    def _routes(self): return _route_pairs()
    def _route(self, url, routes=None):
        """The profile a site belongs to, or None for a site nobody routed. The exact host wins, then
        each parent domain in turn, so one `x.com=<profile>` line also covers `mobile.x.com`.
        `routes` is the room's own table when the caller has one; the machine-wide list is the
        fallback, and the call comes from the turn's thread with the room already resolved."""
        h = _host_key(url)
        if not h: return None
        r = routes if routes is not None else self._routes(); parts = h.split(".")
        for i in range(len(parts) - 1):
            cand = ".".join(parts[i:])
            if cand in r: return r[cand]
        return None
    def _ensure_ctx(self, name, headless=None):
        """One named profile's browser, launched the first time a site needs it and kept warm after
        that. The profile is a folder under browser_profiles, and that folder is the whole trick: the
        cookies the browser writes there outlive this process, so a sign-in done once is still there
        tomorrow. Several profiles are several browsers at once — each with its own folder — which is
        why picking the right one costs nothing at all."""
        ent = self._mine()["ctxs"].get(name)
        if ent is not None:
            # A browser the user quit is still the one cached under its name, and Settings tells them
            # to close the sign-in window when they are done — so this is the normal end of a
            # sign-in, not an error. `pages` is a local list that stays empty rather than raising, so
            # the browser's own connected flag is the only honest liveness check here.
            if ent[0].browser is None or ent[0].browser.is_connected(): return ent[0]
            self._mine()["ctxs"].pop(name, None)
            try:
                if self.page is not None and self.page.context is ent[0]: self.page = None
            except Exception: pass
        b = load_settings().get("browser") or {}
        hl = bool(b.get("headless", False)) if headless is None else bool(headless)
        d = own_profile_dir(name); os.makedirs(d, exist_ok=True)
        ctx = self._driver().chromium.launch_persistent_context(
            d, viewport={"width": 1280, "height": 820}, **_launch_opts(hl))
        if hl: _no_headless_token(ctx)
        self._mine()["ctxs"][name] = (ctx, hl)
        return ctx
    def _drop_ctx(self, name):
        ent = self._mine()["ctxs"].pop(name, None)
        if ent:
            try: ent[0].close()
            except Exception: pass
    def _close_persistent(self):
        """Close the saved-profile browsers *this* thread made, and stop its driver. Only its own: a
        restart has already started the next thread, and the browsers that one makes are not ours to
        end — which is exactly why this runs on the dying thread rather than on whoever asked."""
        me = self._thr.pop(threading.current_thread(), None)
        if not me: return
        for n in list(me["ctxs"]):
            ent = me["ctxs"].pop(n)
            try: ent[0].close()
            except Exception: pass
        if me["pp"] is not None:
            try: me["pp"].stop()
            except Exception: pass
            me["pp"] = None
    def open_profiles(self):
        """The names whose browsers are genuinely up right now, in any thread — what the Settings list
        reads to say whether an account is open. A window the user quit is still sitting in its slot
        until something asks for it again, so liveness is asked of the browser itself: `pages` is a
        local list that goes empty rather than raising, but `is_connected()` tells the truth."""
        out = set()
        for m in self._thr.values():
            for n, ent in m["ctxs"].items():
                try:
                    if ent[0].browser is None or ent[0].browser.is_connected(): out.add(n)
                except Exception: pass
        return out
    def profile_cookies(self, name):
        """The live cookies of a profile whose window is already open. Chrome holds cookies in memory
        and only writes them out when the window closes, so the file on disk is empty for as long as
        the user is signing in — asking the browser itself is the only way to tell them it worked
        before they close it. Never launches a window: an unopened profile answers "nothing"."""
        ent = self._mine()["ctxs"].get(name)
        if not ent: return []
        try: return [[c.get("domain", ""), c.get("name", "")] for c in ent[0].cookies()]
        except Exception: return []
    def profile_open(self, name, url=""):
        """Bring one profile's window up so you can sign in to it, and leave it as the bot's own
        window. A headless profile has no window to show and signing in is the one thing that cannot
        be done without one, so that profile is reopened visibly here. `url` is where to land: a
        sign-in happens on the site, so opening a blank window makes the user type an address the
        account's own row already names."""
        name = (name or "").strip() or "default"
        why = browser_url_guard(url)
        if why: return "(not opened — %s)" % why
        ent = self._mine()["ctxs"].get(name)
        if ent is not None and ent[1]: self._drop_ctx(name)     # headless: nothing to show
        ctx = self._ensure_ctx(name, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try: page.bring_to_front()
        except Exception: pass
        self.page = page; self.engine = "own"; self.mode = "profiles"
        if url:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                self._settle()
            except Exception as e:
                return "the %s window is open, but %s would not load (%s)" % (name, url, e)
            return ("the %s window is open on %s — sign in there, and close the window when you are "
                    "done. The bots use that same window and the same saved logins." % (name, url))
        return ("the %s window is open. Type the site's address to sign in — or put its site in this "
                "account's row and press Sign in again to land straight on it." % name)
    def _cfg(self):
        b = load_settings().get("browser") or {}
        mode = (b.get("mode") or "own").lower()
        # Attaching over CDP always means a debug port on this machine, so the URL is derived from
        # the one port setting — `browser_port` — so the two can never disagree.
        return mode, ("http://127.0.0.1:%d" % browser_port(b))
    def _targets(self):
        """The 'Which profile?' setting: one or more URL fragments, comma or newline separated."""
        b = load_settings().get("browser") or {}
        return [x.strip() for x in re.split(r"[,\n]", b.get("target_url") or "") if x.strip()]
    def _match_webview(self, wv, url=""):
        """The profile that fits the site: one already showing it, else one matching a pinned
        fragment. None when nothing matches (so a pinned list never yanks the bot off its profile)."""
        host = (urlparse(url).netloc or "").split(":")[0] if url else ""
        if host:
            for t in wv:
                if host in (t.get("url") or ""): return t
        for p in self._targets():
            for t in wv:
                if p in (t.get("url") or ""): return t
        return None
    def _attach_webview(self, url=""):
        """Electron apps (ZenPilot) expose each logged-in profile as a <webview> target. Playwright
        cannot see those; we drive them over raw CDP, so one attach reaches the profiles you are
        already signed into -- no second window, no logging in again. Several profiles can be
        pinned at once, one per site."""
        cdp = None
        try:
            cdp = _CDP(self.cdp_url)
            wv = [t for t in cdp.targets() if t.get("type") == "webview"]
            if not wv: return False
            pick = self._match_webview(wv, url) or wv[0]
            self.cdp = cdp; self._sh = None
            # Who owns this connection. A restart starts a new thread that attaches its own, and the
            # old thread must not close that one on its way out — see the sentinel branch in _run.
            self._cdp_owner = threading.current_thread()
            self.page = CDPPage(cdp, cdp.attach(pick["id"]))
            self.target_id = pick["id"]
            self.url = pick.get("url", ""); self.engine = "webview"; self.attached = True
            cdp = None                        # handed to self.cdp now, so the finally must not close it
            return True
        except Exception as e:
            self.err = "webview: %s" % e
            return False
        finally:
            # A failed attach used to leak its socket: nothing else ever held the connection, and the
            # caller retries on a timer, so a browser that lists targets but refuses to attach leaked
            # one WebSocket per retry.
            if cdp is not None:
                try: cdp.close()
                except Exception: pass
    def _shell_ev(self, js):
        """Run one expression in the app window itself, where electronAPI lives. The window is a
        'page' target whose URL is a file: URL — a profile is a <webview>, so this is the only target
        that is the app and not a site. None when there is no such target or the app is not ZenPilot."""
        if not getattr(self, "cdp", None): return None
        if self._sh is None:
            for t in self.cdp.targets():
                if t.get("type") == "page" and (t.get("url") or "").startswith("file:"):
                    self._sh = self.cdp.attach(t["id"]); break
        if not self._sh: return None
        try:
            r = self.cdp.cmd("Runtime.evaluate",
                             {"expression": js, "returnByValue": True, "awaitPromise": True},
                             session=self._sh, timeout=30)
        except Exception:
            self._sh = None; raise        # a dead session must be re-made, not reused forever
        return r.get("result", {}).get("value")
    def _site_profiles(self):
        """Zen Pilot's own answer to 'which profile is this site?' — every service with its home URL,
        every profile with the service it belongs to, and which profiles are running. What a profile
        is *showing* right now says nothing about what it is for, which is how a Threads request ended
        up being opened in the YouTube profile. `api` says whether the app answered at all: an Electron
        app that is not Zen Pilot has no profile list, while None means the app could not be asked."""
        js = ("(async()=>{const e=window.electronAPI;"
              "if(!e||!e.profiles) return {api:false,p:[],s:[],r:[]};"
              "const p=await e.profiles.getAll(), s=await e.services.getAll(), r=await e.profiles.getRunning();"
              "return {api:true,p:p.map(x=>({id:x.id,name:x.name,service_id:x.service_id})),"
              "s:s.map(x=>({id:x.id,name:x.name,url:x.default_url||''})),r:r}})()")
        try: return self._shell_ev(js)
        except Exception: return None
    def _app_webviews(self):
        """The app window's own list of open profiles: each <webview>'s partition (persist:profile_<id>)
        and the URL it is on. This is the only thing that ties a profile id to a CDP target — the
        order of the target list does not match the order of the profiles."""
        try: return self._shell_ev("[...document.querySelectorAll('webview')].map(w=>({p:w.partition,"
                                   "u:(w.getURL?w.getURL():w.src)||''}))") or []
        except Exception: return []
    def _by_profile(self, pid, wv):
        """The <webview> target for one profile id, found by the URL the app says that profile is on.
        Two profiles on the same URL (two Gmails) are the same site either way, so picking either is
        not the mistake this guards against."""
        for w in self._app_webviews():
            if str(w.get("p") or "") != "persist:profile_%d" % pid: continue
            for t in wv:
                if (t.get("url") or "") == (w.get("u") or ""): return t
        return None
    def _profile_target(self, url):
        """(target, "") for the webview that owns this site, or (None, why). The profile already
        showing the site wins; otherwise Zen Pilot's profile list names the profile that is for this
        site and we ask the app to open it. A site with no profile of its own is refused rather than
        opened in somebody else's profile, which would hand the request the wrong cookies."""
        wv = lambda: [t for t in self.cdp.targets() if t.get("type") == "webview"]
        host = _host(url)
        self._no_profile = False
        if not host: return None, "that URL has no site in it"
        for t in wv():
            if _host(t.get("url")) == host: return t, ""
        m = self._site_profiles()
        if not m:                       # the app could not be asked: refuse, never guess a profile
            return None, ("could not read Zen Pilot's profile list — check that Zen Pilot is running "
                          "and its debug port answers")
        if not m.get("api"):            # an Electron app with no profile list: nothing to protect, so drive what is open
            pick = self._match_webview(wv(), url) or (wv() or [None])[0]
            return (pick, "") if pick else (None, "nothing is open to drive")
        svc = next((s for s in m.get("s") or [] if _host(s.get("url")) == host), None)
        if not svc:
            # The site has no profile of its own. That is the ordinary case for a public page, and it
            # is not a reason to refuse — see `open`, which reads such a site anonymously.
            self._no_profile = True
            have = sorted({_host(t.get("url")) for t in wv() if _host(t.get("url"))})
            return None, ("no Zen Pilot profile is set up for %s — the profiles it has are for %s. "
                          "Add a profile for this site in Zen Pilot, or use a site one already covers."
                          % (host, ", ".join(have) or "nothing yet"))
        ids = [p["id"] for p in m.get("p") or [] if p.get("service_id") == svc["id"]]
        if not ids:
            self._no_profile = True
            return None, ("Zen Pilot's %s has no profile yet — add one there first." % svc["name"])
        for pid in ids:                 # already open, even if it has wandered off its own site
            t = self._by_profile(pid, wv())
            if t: return t, ""
        before = {t["id"] for t in wv()}
        try: self._shell_ev("window.electronAPI.profiles.open(%d)" % ids[0])
        except Exception as e: return None, "could not open the %s profile: %s" % (svc["name"], e)
        end = time.time() + 25
        while time.time() < end:
            new = [t for t in wv() if t["id"] not in before]
            if new: return new[0], ""
            time.sleep(0.5)
        return None, "Zen Pilot did not open its %s profile" % svc["name"]
    def _switch_webview(self, url):
        """Point at the profile that owns the site about to be opened. Returns "" on success, else why
        the site cannot be opened here. Same app, no new window."""
        if not getattr(self, "cdp", None): return "the browser is not attached"
        try: pick, why = self._profile_target(url)
        except Exception as e: return "could not pick a profile: %s" % e
        if not pick: return why
        if pick["id"] != getattr(self, "target_id", ""):
            # Each attach is held by the browser until it is detached, so switching profile without
            # letting the last session go leaked one per cross-site open.
            prev = getattr(self, "page", None)
            if prev: self.cdp.detach(prev.sid)
            self.page = CDPPage(self.cdp, self.cdp.attach(pick["id"]))
            self.target_id = pick["id"]; self.url = pick.get("url", "")
        return self._foreground(pick)
    def _pid_of(self, target):
        """Zen Pilot's profile id for a webview target, or None. The app's own list pairs each
        profile's partition with the URL it is on — the same pairing `_by_profile` reads the other way
        round. Two profiles on one URL are the same site either way, so the first match will do."""
        u = target.get("url") or ""
        for w in self._app_webviews():
            if (w.get("u") or "") != u: continue
            p = str(w.get("p") or "")
            if p.startswith("persist:profile_"):
                try: return int(p.rsplit("_", 1)[1])
                except Exception: return None
        return None
    def _foreground(self, target):
        """Make Zen Pilot actually show the profile behind `target`. It renders one profile at a time
        and a hidden <webview> is 0x0 — it never paints, so a click lands on nothing and a screenshot
        has no frame: the bot drives a profile nobody can see and every action is a no-op that still
        reports success. The app exposes no focus call, so its own sidebar row is the only switch:
        click the row labelled with the profile's name, expanding its service group if collapsed.
        Returns "" once that profile is on screen, else why it would not come on screen."""
        # ponytail: foregrounded at open time only. A turn that switches profiles behind the bot's
        # back (or two profiles of one service) can still leave it clicking a background webview;
        # add the same check to click/type/press if that shows up in a turn.
        pid = self._pid_of(target)
        if pid is None: return ""           # an Electron app with no profile list: nothing to switch
        m = self._site_profiles() or {}
        prof = next((p for p in m.get("p") or [] if p.get("id") == pid), None)
        if not prof: return ""
        svc = next((s.get("name") or "" for s in m.get("s") or [] if s.get("id") == prof.get("service_id")), "")
        name = prof.get("name") or ""
        click, show = _fg_js(pid, name, svc)
        end = time.time() + 8
        while True:
            try: r = self._shell_ev(click)
            except Exception: return ""     # cannot reach the app window: leave the open alone
            if r is None or r == "visible": return ""   # cannot ask, or it is already on screen
            if r == "clicked": break
            if time.time() >= end: return ""            # no row ever appeared: leave the open alone
            time.sleep(0.5)                 # a session that is still starting has no sidebar row yet
        for _ in range(20):
            time.sleep(0.3)
            try: s = self._shell_ev(show)
            except Exception: return ""
            if s is not False: return ""    # True = on screen; None = cannot ask
        return ("Zen Pilot's %s profile is open but will not come on screen, so clicks would land on "
                "nothing — bring that profile up in Zen Pilot and try again." % name)
    def _attach(self):
        """Connect to the configured browser, setting self.ok / self.err. Called once when the thread
        starts and again when a job arrives with no browser yet, so a browser that was not running —
        or that had no profile open — is picked up as soon as it is."""
        # A half-made attempt must not pile up. A browser we launched is ours to close; one we
        # attached to over CDP is somebody else's window, so only our connection to it is dropped.
        try:
            if getattr(self, "browser", None) and not self.attached: self.browser.close()
        except Exception: pass
        self.browser = None
        self.pw = self._driver()    # one driver per thread, shared with the saved profiles
        self.mode, self.cdp_url = self._cfg()
        self.ok = False; self.err = ""; self.attached = False; self.page = None
        try:
            if self.mode == "profiles":
                # Nothing is launched here. A profile's browser comes up the first time a site is
                # routed to it, so a machine that never browses never pays for one — and `self.page`
                # stays None until then, which the call guard reports as "open something first"
                # rather than as a crash. There is no port and no attach: we own these browsers.
                self.engine = "own"; self.attached = False; self.ok = True
            elif self.mode in ("cdp", "zenpilot") and self.cdp_url and self._attach_webview():
                pass
            elif self.mode in ("cdp", "zenpilot") and self.cdp_url:
                self.browser = self.pw.chromium.connect_over_cdp(self.cdp_url, timeout=30000)
                ctx = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()
                # A page you already have open is the point of attaching; the browser's own window is
                # not. (Zen Pilot cannot open a tab for us over CDP either — Target.createTarget is
                # not supported — so when no profile is open there is genuinely nothing to drive.)
                page = next((p for p in ctx.pages if _drivable(p.url)), None)
                if page is None: raise RuntimeError(NO_PAGE_ERR)
                self.page = page; self.attached = True; self.engine = "cdp"
                try: self.url = page.url; self.title = page.title()
                except Exception: pass
            else:
                self.browser = self.pw.chromium.launch(**_launch_opts(True))
                self.page = _plain_ctx(self.browser).new_page()
                self.engine = "own"
            self.ok = True
        except Exception as e: self.err = str(e)
        return self.ok
    def _run(self, q):
        self._attach()
        self.ready.set()
        while True:
            job = q.get()
            if job is None:
                # Close only the connection this thread made. A restart has already started the next
                # thread, and that one may own self.cdp by now — closing it here would break it.
                if self._cdp_owner is threading.current_thread():
                    try:
                        if getattr(self, "cdp", None): self.cdp.close()
                    except Exception: pass
                    self.cdp = None; self._cdp_owner = None
                # The saved profiles are per thread, so this one is always ours to end — on a restart
                # the next thread's browsers live in its own slot and are never touched from here.
                self._close_persistent()
                break
            fn, args, res, ev, owner = job
            # Ownership is recorded here, on the browser's own thread, rather than by the caller: it
            # is the same thread that sets `self.page`, so the two can never disagree about whose
            # screen this is. It is what the Computer panel is scoped by — see `_computer_scope`.
            if owner: self.owner = owner
            # No browser yet: the port had nothing on it, or no profile was open. Try again now —
            # whatever was missing may have appeared since — but not on every poll, so a browser
            # that is simply not running is not re-connected to every couple of seconds.
            if not self.ok and time.time() - self.last_try > BROWSER_RETRY_S:
                self.last_try = time.time(); self._attach()
            if not self.ok:
                res["out"] = "(browser unavailable: " + (self.err or "playwright not installed") + ")"
                ev.set(); continue
            # In profiles mode nothing is launched until a site needs it, so these three can be the
            # first call of a turn with no page behind them yet. Say so in words rather than raising
            # an AttributeError the bot reads as a browser failure.
            if fn not in ("open", "profile_open", "preview", "profile_cookies") and not getattr(self, "page", None):
                res["out"] = "(no page is open yet — call browser_open first)"; ev.set(); continue
            try: res["out"] = getattr(self, fn)(**args)
            except Exception as e: res["out"] = f"(browser error: {e})"
            ev.set()
    def call(self, fn, timeout=90, **args):
        self.start()
        if not (self.thread and self.thread.is_alive()):
            return "(browser unavailable: " + (self.err or "playwright not installed") + ")"
        # `_owner` is the bot this call is on behalf of, and it rides with the job instead of being
        # written from here so the browser thread is the only writer of `self.owner`.
        owner = args.pop("_owner", "")
        res = {}; ev = threading.Event(); self.q.put((fn, args, res, ev, owner))
        if not ev.wait(timeout): return "(browser timeout)"
        return res.get("out", "(no output)")
    def _snap(self):
        try: txt = self.page.inner_text("body")
        except Exception: txt = ""
        try: self.url = self.page.url; self.title = self.page.title()
        except Exception: pass
        return json.dumps({"url": self.page.url, "title": self.page.title(), "text": txt[:3500]})
    def _driver(self):
        """The one Playwright driver this thread runs. The sync API refuses a second one in the same
        thread and refuses to be touched from any other, and both the saved profiles and the throwaway
        browser want one — so it is kept per thread, and whoever asks first makes it."""
        me = self._mine()
        if me["pp"] is None:
            from playwright.sync_api import sync_playwright
            me["pp"] = sync_playwright().start()
        return me["pp"]
    def _headless(self):
        """The throwaway headless browser, launched on first use and kept warm after that. A site with
        no Zen Pilot profile is a public page: it needs no login, so it needs none of your cookies.
        Reading it here is the point — refusing it is what sent the bot off to shell out (curl, a
        hand-rolled CDP script), which is many times slower and sees far less of the page."""
        me = self._mine()
        try:
            if me["hpage"] is None:
                me["hb"] = self._driver().chromium.launch(**_launch_opts(True))
                me["hctx"] = _plain_ctx(me["hb"])
                me["hpage"] = me["hctx"].new_page()
            return me["hpage"]
        except Exception as e:
            me["hb"] = None; me["hctx"] = None; me["hpage"] = None
            self.err = "headless: %s" % e
            return None
    def open(self, url, routes=None):
        # Every browser URL a bot or the panel asks for comes through here, so this is where the
        # secret store is kept out of reach (see browser_url_guard) rather than at each tool call.
        why = browser_url_guard(url)
        if why: return json.dumps({"url": url, "title": "", "text": "(not opened — %s)" % why})
        # A bare host gets https; anything that already names a scheme (http, https, file, data) is
        # left alone — prefixing blindly turned a file: URL into "https://file:...".
        if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", url): url = "https://" + url
        anon = False; note = ""
        if self.engine == "webview":
            why = self._switch_webview(url)   # the profile that is for this site, not whichever is open
            if why:
                # No profile for this site. If that is the only problem, read it anonymously rather
                # than refuse — a public page is the common case, and a refusal is a dead end the bot
                # works around the slow way. A profiled site whose profile would not open is still a
                # refusal: serving it anonymously would quietly drop the login the profile exists for.
                page = self._headless() if self._no_profile else None
                if page is None:
                    return json.dumps({"url": url, "title": "", "text": "(not opened — %s)" % why})
                self.page = page; anon = True
                note = ("read anonymously in a throwaway browser: no Zen Pilot profile covers this "
                        "site, so a page that needs a login shows its login wall here")
        elif self.mode == "profiles":
            # A routed site opens in the account that owns it; anything else is a public page and
            # gets the throwaway browser, because opening a logged-in profile for it would hand it
            # cookies it has no business seeing.
            name = self._route(url, routes)
            if name:
                try:
                    ctx = self._ensure_ctx(name)
                    self.page = ctx.pages[0] if ctx.pages else ctx.new_page()
                except Exception as e:
                    return json.dumps({"url": url, "title": "", "text":
                                       "(not opened — the %s profile would not start: %s)" % (name, e)})
            else:
                page = self._headless()
                if page is None:
                    return json.dumps({"url": url, "title": "", "text":
                                       "(not opened — %s)" % (self.err or "no browser")})
                self.page = page; anon = True
                note = ("read anonymously in a throwaway browser: no account covers %s, so a page that "
                        "needs a login shows its login wall here. If this site should be signed in, tell "
                        "the user to add it to an account's sites in %s." %
                        (_host(url) or url, "this room's Browser section" if routes is not None
                         else "Settings → Browser"))
        self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
        self._settle()
        snap = self._snap()
        if anon:
            d = json.loads(snap); d["note"] = note; snap = json.dumps(d)
        return snap
    def _settle(self, tries=20, step=0.25):
        """Wait for the page to actually paint. `domcontentloaded` fires long before a feed like
        Threads renders, so reading straight after it returns an empty body — the bot reads nothing,
        re-opens, and burns steps. Read the visible text until two reads in a row agree, or give up.
        Two *empty* reads in a row are not agreement: a page mid-navigation is briefly blank, and
        treating that as settled is exactly how a click came back as "nothing happened"."""
        last = -1
        for _ in range(tries):
            try: n = len(self.page.inner_text("body") or "")
            except Exception: n = 0
            if n and n == last: return
            last = n; self.page.wait_for_timeout(int(step * 1000))
    def read(self): return self._snap()
    def eval(self, expression, max_chars=4000):
        """Run one expression in the page and hand back its value. Page JS is the one primitive the
        click/type tools cannot express — counting, listing, scrolling, waiting — and running it here
        reuses the warm CDP session instead of spawning a helper script per poke."""
        v = self.page.evaluate(expression)
        try: s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        except Exception: s = str(v)
        n = int(max_chars)
        # A list cut off mid-JSON is not a shorter answer, it is an unparseable one: the cut says so,
        # so the bot narrows the expression instead of reading a broken value as the real thing.
        return s if len(s) <= n else (s[:n] + "\n…(cut at %d chars — narrow the expression, or ask for "
                                      "more with max_chars)" % n)
    def click(self, selector):
        # A selector that matches nothing used to spend the full 12s actionability timeout and come
        # back as a Playwright wall — which is most of what "the Top tab click returned nothing before
        # time ran out" was. Counting first turns that into an instant answer the bot can act on.
        try: n = self.page.locator(selector).count()
        except Exception: n = 1        # an unparsable selector: let `click` raise it in its own words
        if n == 0:
            return ("(nothing on this page matches %s — use browser_eval to find the element and click "
                    "it in the same call, e.g. [...document.querySelectorAll('a,button')]"
                    ".find(e=>e.innerText.trim()==='Top')?.click())" % selector)
        self.page.click(selector, timeout=12000)
        # A tab or a filter changes the page without navigating, so the fixed sleep this used to do
        # either read the old page or read the new one half-drawn. Waiting for the text to stop
        # changing reads the page the click actually produced. A tighter cap than `open`'s: a tab
        # swaps its content in well under a second, and a page that never stops changing — a feed
        # with a live counter — must not cost seconds on every click.
        self._settle(tries=8)
        return self._snap()
    def type(self, selector, text):
        self.page.fill(selector, text); self.page.wait_for_timeout(200); return f"typed into {selector}"
    def press(self, key):
        self.page.keyboard.press(key); self._settle(tries=8); return self._snap()
    def back(self):
        self.page.go_back(wait_until="domcontentloaded", timeout=30000); return self._snap()
    def shot(self): return self._png(self.page.screenshot())
    def _grab(self, target_id, tries=(4,)):
        """One screenshot from a profile, over a CDP session that is detached again straight away.
        Each `Target.attachToTarget` opens a session the browser holds until it is closed, and the
        Computer panel polls faster than they are reclaimed — so a session left open per poll grew
        without bound (slowness, then attach failures). Detaching here keeps exactly one alive."""
        sid = self.cdp.attach(target_id)
        try: return self._png(CDPPage(self.cdp, sid).screenshot(tries=tries))
        finally: self.cdp.detach(sid)
    def _on_screen(self):
        """The profile Zen Pilot is actually showing, as (target, png), or (None, None).

        Zen Pilot renders one profile at a time and a hidden <webview> never produces a frame, so
        the only honest test of "which one is on screen" is to try to capture each in turn. The one
        that answers is the one you are looking at."""
        for t in self.cdp.targets():
            if t.get("type") != "webview": continue
            try: return t, self._grab(t["id"])
            except Exception: continue
        return None, None
    def _png(self, raw): return "data:image/png;base64," + base64.b64encode(raw).decode()
    def preview(self, force=False):
        """What the Computer panel shows, as JSON.

        The bot's own profile when it is on screen; otherwise the profile that is — so the panel is
        a live screen rather than an empty frame, and the caption says which profile you are looking
        at. This never touches `self.page`, so watching a turn cannot move the bot off its target.

        `force` is the panel's Refresh: it skips the remembered profile below and re-decides from
        scratch, which is the one thing the poll's own call cannot do."""
        if not getattr(self, "page", None):
            return json.dumps({"png": "", "url": "", "title": "", "err":
                               "no page is open yet — ask a bot to browse, or open a profile window below"})
        if self.engine != "webview" or not getattr(self, "cdp", None):
            return json.dumps({"png": self._png(self.page.screenshot()), "url": self.page.url,
                               "title": self.page.title(), "err": ""})
        # Which profile answers is remembered for a few seconds: on a hidden one it costs two
        # timeouts to find out, and the panel polls faster than that, so re-deciding every poll is
        # what would back the browser queue up. The remembered profile is re-captured each time —
        # this is a live screen, only the *choice* is cached.
        now = time.time()
        if not force and self._shot_id and now - self._shot_at < 5:
            t = next((x for x in self.cdp.targets() if x["id"] == self._shot_id), None)
            if t is not None:
                try:
                    png = self._grab(t["id"])
                    self._shot_at = now
                    return json.dumps({"png": png, "url": t.get("url", ""), "title": t.get("title", ""),
                                       "err": "" if t["id"] == self.target_id else self._behind()})
                except Exception: self._shot_id = ""
        try:
            png = self._png(self.page.screenshot(tries=(4,)))
            self._shot_id, self._shot_at = self.target_id, now
            return json.dumps({"png": png, "url": self.page.url, "title": self.page.title(), "err": ""})
        except Exception:
            pass
        t, png = self._on_screen()
        if not png:
            return json.dumps({"png": "", "url": "", "title": "", "err":
                               "no profile is on screen in Zen Pilot — open one there and it appears here"})
        self._shot_id, self._shot_at = t["id"], now
        return json.dumps({"png": png, "url": t.get("url", ""),
                           "title": t.get("title", ""), "err": self._behind()})
    def _behind(self):
        return ("showing the profile that is on screen; the bot's own profile (%s) is in the background"
                % (self.url or "unknown"))
    def save(self, selector="img", wait_ms=60000):
        """Wait for `selector`, then download what it points at (img / video / canvas) as a data URL.
        This is the 'wait for the attachment, then download it' step of the free web route."""
        el = self.page.wait_for_selector(selector, timeout=wait_ms, state="attached")
        if (el.evaluate("e=>e.tagName.toLowerCase()") or "") == "canvas":
            return el.evaluate("e=>e.toDataURL('image/png')")
        url = el.evaluate("e=>e.currentSrc||e.src||e.href||''") or \
              el.evaluate("e=>{const i=e.querySelector&&e.querySelector('img,video,a');return i?(i.currentSrc||i.src||i.href||''):''}")
        if not url: return json.dumps({"error": "element has no image/video source"})
        if url.startswith("data:"): return url
        b64 = self.page.evaluate(
            "async (u)=>{const r=await fetch(u,{credentials:'include'});const a=new Uint8Array(await r.arrayBuffer());"
            "let s='';for(let i=0;i<a.length;i+=8192)s+=String.fromCharCode.apply(null,a.subarray(i,i+8192));"
            "return btoa(s)}", url)
        low = url.split("?")[0].lower()
        mime = ("video/mp4" if low.endswith((".mp4", ".webm")) else
                "image/jpeg" if low.endswith((".jpg", ".jpeg")) else
                "image/webp" if low.endswith(".webp") else "image/png")
        return "data:%s;base64,%s" % (mime, b64)
BROWSER = Browser()
ZENPILOT_GET = "https://anzenpilot.gumroad.com/l/zenpilot"

def browser_hint(err):
    """Playwright's connect failures are a stack trace; say the same thing in a sentence, and keep
    the raw text for the tooltip so nothing is hidden."""
    e = (err or "").lower()
    if not err: return "the browser is still starting"
    if "econnrefused" in e or "connection refused" in e:
        return "nothing is listening on that port yet; press “Launch ZenPilot & connect”"
    if "playwright" in e and "not installed" in e:
        return "the browser engine is not installed on the server; run python3 -m playwright install chromium"
    if "timeout" in e: return "the browser did not answer in time"
    return err.split("\n")[0][:160]

def zenpilot_app(bases=("/Applications", os.path.expanduser("~/Applications"))):
    """The Zen Pilot app bundle if it is on this machine, else ''. A directory listing, not a
    guess: we only tell the user it is missing after actually looking and not finding it."""
    for base in bases:
        try: names = os.listdir(base)
        except OSError: continue
        for n in sorted(names):
            low = n.lower()
            if low.endswith(".app") and "zen" in low and "pilot" in low:
                return os.path.join(base, n)
    return ""

def browser_port(b=None):
    """The one number that says where the debug port is. Everything else — the launch command, the
    CDP URL — is derived from it, so they cannot disagree."""
    b = b if b is not None else (load_settings().get("browser") or {})
    try: port = int(b.get("port") or 9222)
    except Exception: port = 9222
    return port if 1 <= port <= 65535 else 9222

def zenpilot_launch_cmd(port, app=""):
    """The argv that opens ZenPilot with its debug port. It is identical on every machine, so it is
    built from the port instead of being typed into a setting (and an argv, not a shell string, so
    nothing has to be quoted)."""
    return ["open", "-a", app or "Zen Pilot", "--args", "--remote-debugging-port=%d" % int(port)]

def _host_key(x):
    """A bare host or a whole URL, as the host alone. The sites box is typed by hand, so both
    spellings have to work — and `_host` reads a URL's netloc, which a bare host like `x.com` has
    none of."""
    x = (x or "").strip().lower()
    if "://" in x: x = urlparse(x).netloc
    x = x.split("/")[0].split(":")[0]
    return x[4:] if x.startswith("www.") else x

def _route_pairs(b=None):
    """Which account owns which site, as {host: account name}. The settings hold the accounts you
    made in the UI — a name and the sites it handles — and this is the one place that turns them into
    a lookup, so the browser and the settings page can never disagree. A site nobody claims is read
    anonymously: sending it to an account would hand it cookies it has no business seeing."""
    b = b if b is not None else (load_settings().get("browser") or {})
    out = {}
    for a in b.get("accounts") or []:
        if not isinstance(a, dict): continue
        name = (a.get("name") or "").strip()
        if not name: continue                       # an account with no name cannot be routed to
        for s in re.split(r"[,\s]+", a.get("sites") or ""):
            h = _host_key(s)
            if h: out[h] = name
    return out

def _room_routes(ch):
    """The routing table a room's own accounts make, or None when the room defines none — in which
    case the machine-wide list still answers, so a room that never set one behaves as it always has.
    A room with accounts routes only through them: the whole point is that a bot in that room uses
    the account the room names, without being told which one to use."""
    acc = (ch or {}).get("browser") or []
    return _route_pairs({"accounts": acc}) if acc else None

def profile_id(name):
    """The folder basename a profile name reduces to — a profile's *identity*, since the folder is
    what holds the cookies. The name is user text, so it is made safe first: a name of `../..` must
    not be able to name a folder anywhere else on disk. Two names that reduce to the same id are the
    same profile, and every reader of a name goes through here so none of them can disagree."""
    return re.sub(r"[^A-Za-z0-9._ -]", "_", (name or "").strip()).strip(". ") or "default"

def own_profile_dir(name):
    """The folder one named profile keeps its cookies in."""
    return os.path.join(DATA, "browser_profiles", profile_id(name))

# The Chromium-family browsers Playwright can drive, in the order we would rather have them. Only
# these are real installs of a branded browser: Playwright's own Chromium is a "Chrome for Testing"
# build whose user agent says so, and Google refuses to sign anyone in on it ("This browser or app
# may not be secure"). A browser the user already has, launched without Playwright's automation
# switch, signs in normally — which is why the picker offers these and not the bundled one.
BROWSER_CHANNELS = [
    ("chrome", "Google Chrome", "/Applications/Google Chrome.app"),
    ("chrome-beta", "Google Chrome Beta", "/Applications/Google Chrome Beta.app"),
    ("msedge", "Microsoft Edge", "/Applications/Microsoft Edge.app"),
    ("msedge-beta", "Microsoft Edge Beta", "/Applications/Microsoft Edge Beta.app"),
]

def installed_channels():
    """The browsers this machine actually has, as {key, label} — the picker's options, so a choice
    can never name a browser that is not there."""
    return [{"key": k, "label": n} for k, n, app in BROWSER_CHANNELS if os.path.isdir(app)]

def browser_channel():
    """Which browser to launch: the one picked in Settings, or — with "auto" — the first real
    Chrome-family browser installed here, since that is the one that can sign in to Google. Empty
    means nothing local was found and Playwright's own Chromium is all we have."""
    b = load_settings().get("browser") or {}
    have = [e["key"] for e in installed_channels()]
    want = (b.get("channel") or "auto").lower()
    if want == "bundled": return ""          # the explicit "do not use a local browser"
    if want in have: return want
    for k in ("chrome", "msedge"):
        if k in have: return k
    return ""

def _launch_opts(headless, channel=None):
    """How every browser we launch is started, in one place so the throwaway and the saved profiles
    cannot drift apart. The two automation entries are the whole point: Playwright's own
    `--enable-automation` switch is what sets `navigator.webdriver`, and a browser that announces
    itself as automated is exactly what Google's sign-in turns away."""
    o = {"headless": bool(headless),
         "args": ["--disable-blink-features=AutomationControlled"],
         "ignore_default_args": ["--enable-automation"],
         # The sandbox has to be asked for by name, because Playwright turns it off unless it is:
         # the driver pushes `--no-sandbox` whenever `chromiumSandbox !== true`, on every platform.
         # So a desktop that never asked for it had Chrome's process sandbox switched off and
         # "unsupported command-line flag: --no-sandbox. Stability and security will suffer" painted
         # across the top of the sign-in window. That flag is a real security boundary and a real
         # warning, and nothing here needed either. A container running as root is the one place the
         # flag is genuine — Chromium refuses to start there without it — and that is the only case
         # left with the sandbox off.
         "chromium_sandbox": not (hasattr(os, "geteuid") and os.geteuid() == 0)}
    ch = browser_channel() if channel is None else channel
    if ch: o["channel"] = ch
    return o

def _plain_ua(browser):
    """A launched browser's own user agent with the headless token taken out — or "" if it cannot be
    read, in which case the caller sets nothing and gets the default.

    `HeadlessChrome` in the user agent is what a bot check looks for, and it is a lie about what this
    browser is: it is a real, installed Chrome, launched without Playwright's automation switch. The
    token is Playwright's own addition and survives `--headless=new`, so the only way to be rid of it
    is to set the UA — and the *browser's* UA, asked over CDP, is the one string that cannot go stale
    the way a version pinned in the source would. Verified 2026-10-16: with this token, DuckDuckGo
    answered a 305-byte challenge, Brave a 429 and Google "unusual traffic"; with it swapped back to
    `Chrome/`, all three answered the real page from this same machine."""
    try:
        v = browser.new_browser_cdp_session().send("Browser.getVersion")
        return (v.get("userAgent") or "").replace("HeadlessChrome/", "Chrome/")
    except Exception:
        return ""

def _plain_ctx(browser):
    """A context on a browser we launched that does not announce `HeadlessChrome` — see `_plain_ua`
    for why the token matters. A context of our own rather than `browser.new_page()`'s implicit one,
    because the user agent has to be set when the context is made and the implicit one is made before
    the browser can be asked what its own is.

    No locale is set here, deliberately. The language a job needs is carried by the job — the query it
    types and the address it opens — and that is what the engines actually answer in: an Indonesian
    query returned Indonesian results from Google, Brave and DuckDuckGo with this context announcing
    `en-US,en;q=0.9`. A locale set at launch would be one language for every job on the machine, which
    is the pin the request is supposed to decide instead."""
    ua = _plain_ua(browser)
    return browser.new_context(viewport={"width": 1280, "height": 820},
                               **({"user_agent": ua} if ua else {}))

def _no_headless_token(ctx):
    """The same repair for a saved profile, which cannot be made at launch the way the throwaway is.

    A persistent context *is* the browser — it is started with its user agent already set, before
    anything can be asked what that user agent is — so the override goes on the pages instead, and on
    every page after, because a CDP session belongs to one page and a profile opens them one at a time.
    Only asked for when the profile is launched headless: a headed browser never carries the token, and
    this is a CDP round trip per page. Verified 2026-10-16: a headless profile announced
    `HeadlessChrome/155.0.0.0` before this and `Chrome/155.0.0.0` after, across a navigation and a new
    page."""
    ua = _plain_ua(ctx.browser)
    if not ua: return
    def fix(pg):
        try: ctx.new_cdp_session(pg).send("Network.setUserAgentOverride", {"userAgent": ua})
        except Exception: pass
    ctx.on("page", fix)
    for pg in ctx.pages: fix(pg)

def first_site(sites):
    """The address a row's own button lands on: the first site *that row* lists, as it was written —
    https assumed when no scheme was typed, and the port kept, because a site on this machine is
    reached on one. Reading the site off the account name instead would always answer with whichever
    row was written first, which is how a Threads row came to open x.com. Empty when the row names no
    site yet, and then there is nowhere to land."""
    for s in re.split(r"[,\s]+", sites or ""):
        s = (s or "").strip()
        if not s: continue
        u = urlparse(s if "://" in s else "https://" + s)
        if u.netloc: return "%s://%s%s" % (u.scheme, u.netloc, u.path)
    return ""

def account_site(name):
    """The address an account's sign-in lands on, for a caller that has only the name — the first
    site routed to it. Two rows can share a name, so this can only ever be the first of them; the row
    a button was clicked in is the one that knows, and it uses `first_site`. Empty when nothing is
    routed to the name, and then there is nowhere to land."""
    for h, n in _route_pairs().items():
        if n == name: return "https://" + h
    return ""

# The cookie names a site only hands out once you are actually signed in. A site gives a brand-new
# visitor tracking and consent cookies, so "this profile has cookies" would call a window that was
# merely opened "signed in" — which is the exact lie this replaced. The *name* is the evidence.
# ponytail: a short list of the sites this is really used for; add a line when a new site matters.
# A site that is not listed is reported as unconfirmed, never as signed in.
AUTH_COOKIES = {
    "google.com":   ("SID", "HSID", "SSID", "SAPISID", "__Secure-1PSID", "__Secure-3PSID"),
    "youtube.com":  ("SID", "HSID", "SAPISID", "LOGIN_INFO"),
    "x.com":        ("auth_token",),
    "twitter.com":  ("auth_token",),
    "facebook.com": ("c_user",),
    "threads.net":  ("sessionid",),
    "threads.com":  ("sessionid",),
    "instagram.com": ("sessionid",),
    "linkedin.com": ("li_at",),
    "reddit.com":   ("reddit_session",),
    "github.com":   ("user_session",),
    "tiktok.com":   ("sessionid",),
    "pinterest.com": ("_auth",),
    "openai.com":   ("__Secure-next-auth.session-token",),
}

def _bare_host(h):
    """`host_key` in the cookie store may carry the leading dot that means "this domain and below";
    the account's own sites are written without one. Reduced to the same shape so the two compare."""
    return (h or "").strip().lstrip(".").lower()

def _host_matches(a, b):
    a, b = _bare_host(a), _bare_host(b)
    return bool(a) and bool(b) and (a == b or a.endswith("." + b) or b.endswith("." + a))

def _cookie_rows(d):
    """(host, name) for every cookie a profile has on disk. Chrome keeps cookies in memory while it
    runs and writes them out when it closes, so this is the truth about a window that is already
    shut — and simply empty, not wrong, about one still open, which `profile_cookies` covers. Read
    through a read-only handle so a browser holding the file is nobody's problem; any failure is
    "no evidence" rather than an exception the UI would have to handle."""
    p = os.path.join(d, "Default", "Cookies")
    if not os.path.isfile(p): return []
    try:
        con = sqlite3.connect("file:%s?mode=ro&immutable=1" % p, uri=True, timeout=2)
        try: return con.execute("SELECT host_key, name FROM cookies").fetchall()
        finally: con.close()
    except Exception:
        return []

def _live_cookie_rows(name):
    """The cookies of a profile whose window is open right now. The disk file is empty until that
    window closes, so this is the only way to confirm a sign-in while the user is still looking at
    it. Asked of the browser thread, because Playwright belongs to it. None (not []) when the answer
    could not be had — a browser busy with a bot must not read as "this account is not signed in"."""
    try:
        out = BROWSER.call("profile_cookies", timeout=6, name=name)
    except Exception:
        return None
    return out if isinstance(out, list) else None

def signed_in(hosts, rows):
    """Whether one of the account's own sites has left a sign-in cookie. True / False when we know
    how to judge the site, and None when we do not — a guess there would be the same lie in a new
    place, so it is reported as unconfirmed instead."""
    if not hosts: return None
    judgeable = False
    for h in hosts:
        for dom, names in AUTH_COOKIES.items():
            if not _host_matches(h, dom): continue
            judgeable = True
            if any(nm in names and _host_matches(hk, h) for hk, nm in rows): return True
    return False if judgeable else None

def browser_own_profiles(accounts=None):
    """The accounts our own browser keeps, as one entry per *folder* — because the folder is the
    identity. Two account names that reduce to the same folder (the same name typed twice, or one
    differing only in case, which macOS resolves to the same folder) are one profile, and every name
    that lands in it is reported under `names`: without that the settings page matched a row to a
    profile by the name as typed, so a second row could be handed the first row's saved login and
    read "Signed in" the moment it was added. `signed_in` is the honest part: it is True only when a
    cookie the site sets on sign-in is really there, None when the site is not one we know how to
    judge, and False when we looked and found nothing — never merely "the folder exists", which says
    only that a window was once opened.

    `accounts` is a room's own list when the caller has one. The profiles are still the same folders
    on disk — an account is its folder, wherever it was named — so a room's rows read the logins the
    same way the machine-wide list does. Other rooms' folders are not listed: a room shows its own."""
    b = load_settings().get("browser") or {}
    base = os.path.join(DATA, "browser_profiles")
    routes = _route_pairs({"accounts": accounts} if accounts is not None else b)
    try: on_disk = [x for x in os.listdir(base) if os.path.isdir(os.path.join(base, x))]
    except OSError: on_disk = []
    # A folder answers to any case on macOS, so a name spelled differently still means the folder
    # that is really there — report the folder's own spelling, or "Anzen" and "anzen" would come out
    # as two profiles reading one set of cookies.
    real = {x.lower(): x for x in on_disk}
    def canon(n):
        i = profile_id(n)
        return real.get(i.lower(), i)
    # An account with no sites yet is still listed: you sign in to it *before* deciding what it
    # handles, and a row you cannot see is a row you cannot sign in to.
    ids = {}                                  # folder id -> every account name landing in it, in order
    def slot(n):
        return ids.setdefault(canon(n), [])
    for a in (accounts if accounts is not None else (b.get("accounts") or [])):
        if not isinstance(a, dict): continue
        n = (a.get("name") or "").strip()
        if n and n not in slot(n): slot(n).append(n)
    if accounts is None:
        for x in on_disk: ids.setdefault(x, [])
    out = []
    up = BROWSER.open_profiles()
    for i in sorted(ids):
        names = ids[i]
        d = os.path.join(base, i); ex = os.path.isdir(d)
        hosts = sorted(h for h, p in routes.items() if canon(p) == i)
        opened = next((n for n in names if n in up), None)
        si = None
        if not ex:
            si = False      # no folder means no cookies at all, so this is certain, not a guess
        elif opened:
            live = _live_cookie_rows(opened)
            si = None if live is None else signed_in(hosts, live)
        else:
            si = signed_in(hosts, _cookie_rows(d))
        out.append({"id": i, "name": names[0] if names else i, "names": names or [i],
                    "dir": d, "exists": ex, "hosts": hosts, "up": bool(opened), "signed_in": si})
    return {"ok": True, "dir": base, "headless": bool(b.get("headless", False)),
            "channel": (b.get("channel") or "auto"), "channel_in_use": browser_channel(),
            "channels": installed_channels(), "profiles": out}

def browser_brief(ch=None):
    """What a bot cannot find out for itself: which sites open already signed in. The accounts are the
    user's setup and live only in Settings, so without this a bot asked to manage Threads and Facebook
    has no way to know an account covers them — it tries to log in by hand, or reads a login wall as
    "impossible" and stops. Every site not named here opens in a blank throwaway browser, which is the
    honest answer for a search or a public page.

    `ch` is the room the turn runs in. A room with its own accounts is described by those and nothing
    else, because those are the only ones its bots can route through — naming the machine-wide list
    there would tell a bot about an account it cannot use."""
    b = load_settings().get("browser") or {}
    mode = (b.get("mode") or "own").lower()
    if mode in ("cdp", "zenpilot"):
        return ("\n\nBrowsing: a site you are signed into in Zen Pilot opens in its profile, already "
                "logged in; any other site opens anonymously in a blank throwaway browser.")
    room = (ch or {}).get("browser") or []
    rows = browser_own_profiles(room if room else None)["profiles"] if mode == "profiles" else []
    named = [(p["name"], p["hosts"], p["signed_in"]) for p in rows if p["hosts"]]
    if not named:
        return ("\n\nBrowsing: " + ("this room's accounts name no sites yet" if room
                                    else "no account is set up") +
                ", so every site opens in a blank throwaway browser "
                "with no cookies. That is the right way to search the web or read a public page; a "
                "page that needs a login will show its login wall, and no account covers it."
                + BROWSER_OWN_LINE)
    # This rides in every prompt, so a user with many accounts must not be able to crowd out the
    # instructions that matter. Name as many as fit and count the rest — a bot that needs one of the
    # unnamed accounts still finds it, because routing is by site and it never has to pick.
    shown, used = [], 0
    # The state named here is the one we can stand behind: "signed in" only when the site's own
    # sign-in cookie is there, and "sign-in not confirmed" for a site we have no way to judge — so a
    # bot is never told an account is logged in when nobody ever logged in.
    state = {True: "signed in", False: "not signed in yet", None: "sign-in not confirmed"}
    for n, hs, si in named:
        ent = "%s for %s (%s)" % (n, ", ".join(hs), state[si])
        if shown and used + len(ent) > BROWSER_BRIEF_CHARS:
            shown.append("and %d more" % (len(named) - len(shown))); break
        shown.append(ent); used += len(ent)
    return ("\n\nBrowsing: " + ("this room is set up with accounts — " if room
                                else "the user has set up accounts — ") + "; ".join(shown) +
            ". `browser_open` one of those sites and it opens in that account's own browser, already "
            "logged in: never try to log in or type a password yourself. Any other site opens in a "
            "blank throwaway browser with no cookies — that is the right way to search the web or read "
            "a public page." + BROWSER_OWN_LINE)

def open_own_profile(name, sites=None):
    """Open one profile's window so you can sign in to it. The bot drives that same window
    afterwards, so a sign-in done here is a sign-in done for the bot: nothing is logged in twice, and
    the cookies are on disk for the next run. `sites` is the row that was clicked, so the window lands
    on the site that row names rather than on the first site routed to the account."""
    name = (name or "").strip() or "default"
    if not getattr(BROWSER, "ok", False) or BROWSER.mode != "profiles":
        return {"ok": False, "err": "switch the browser to “Own browser — saved profiles” first"}
    try: os.makedirs(own_profile_dir(name), exist_ok=True)
    except OSError as e: return {"ok": False, "err": "could not make the profile folder: %s" % e}
    url = first_site(sites) or account_site(name)
    out = BROWSER.call("profile_open", name=name, url=url, timeout=180)
    return {"ok": not str(out).startswith("("), "out": str(out)[:300]}

def browser_profiles():
    """What ZenPilot actually has open -- one entry per profile you are logged into (a <webview>
    target). Also says plainly whether the app is installed and whether its debug port answers, so
    the UI can tell the user what to do instead of silently using the wrong browser."""
    b = load_settings().get("browser") or {}
    port = browser_port(b)
    url = "http://127.0.0.1:%d" % port
    app = zenpilot_app()
    out = {"ok": True, "installed": bool(app), "app": app, "cdp_url": url, "up": False,
           "profiles": [], "get_url": ZENPILOT_GET, "err": "", "hint": ""}
    try:
        targets = cdp_targets(url)
    except Exception as e:
        out["err"] = str(e) or "no debug port"; out["hint"] = browser_hint(out["err"]); return out
    out["up"] = True
    seen = set()
    for t in targets:
        if t.get("type") != "webview": continue
        host = (urlparse(t.get("url") or "").netloc or "").split(":")[0]
        if not host or host in seen: continue      # one pin per site; a fragment cannot tell two apart
        seen.add(host)
        out["profiles"].append({"host": host, "title": (t.get("title") or "").strip() or host,
                                "url": t.get("url") or ""})
    return out

def launch_browser():
    """Open ZenPilot on the configured debug port, wait for that port to answer, then attach. Only
    the port is a setting: the command is the same everywhere, so it is built from the port rather
    than stored, and the two can no longer name different ports."""
    b = load_settings().get("browser") or {}
    port = browser_port(b)
    url = "http://127.0.0.1:%d" % port
    if sys.platform != "darwin":
        return {"ok": False, "err": "opening the app for you is macOS-only; start your browser with "
                                    "--remote-debugging-port=%d, then press Test connection" % port}
    # `open -a` takes a bundle path as happily as a name, and a path is one we actually found.
    try:
        subprocess.Popen(zenpilot_launch_cmd(port, zenpilot_app()),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception as e:
        return {"ok": False, "err": "could not open ZenPilot: %s" % e}
    for _ in range(60):                       # give it up to a minute to open the port
        try:
            urllib.request.urlopen(url + "/json/version", timeout=2); break
        except Exception: time.sleep(1)
    else:
        return {"ok": False, "err": "ZenPilot did not open a debug port at %s — another copy may "
                                    "already be running without the flag" % url}
    s = load_settings(); s.setdefault("browser", {})
    s["browser"]["mode"] = "cdp"; s["browser"]["port"] = port; save_settings(s)
    r = BROWSER.restart(); r["cdp_url"] = url
    return r

# ---------------------------------------------------------------- model client
# The model path's retry policy, in the two numbers the user sets in Settings → Models → Context.
#
# How long one attempt waits with no *new content* before it gives up. A socket read timeout cannot do
# this job: it is per read, so a router that trickles SSE keepalives (or plain whitespace) resets it
# for as long as it likes and the call never returns — which is a turn that hangs with nothing to show
# for it. Bytes on the wire are not progress; a delta or a tool-call fragment is. This is deliberately
# long, because a model that thinks for a minute before its first token is working, not stalled: the
# clock only ever advances on content, so a model that is still talking is never cut off.
DEFAULT_MODEL_STALL_SECONDS = 120
# How many times one step tries again after an attempt comes back with nothing at all. Retrying that is
# correct and safe — the router dropped the call, and nothing was streamed, so there is no text to
# duplicate — and it is the *only* attempt worth retrying: once a delta has gone out the bot has
# already spoken, and a second attempt would append a second answer to the first (see `chat_stream`).
#
# 11 tries, the count ZCode's own retry loop uses. The user's point is the right one: a bot that keeps
# trying is worth more than a bot that stops and waits to be asked again, because the whole reason it
# runs unattended is that nobody is watching. What made 11 safe to take was not the count but the
# *cost* of an attempt — see MODEL_FAIL_SECONDS, which is what stops a router that has gone quiet from
# turning one step into a half-hour. The setting offers 0-10, so 11 tries is the ceiling either way.
DEFAULT_MODEL_RETRIES = 10
# The wait before the next try: ZCode's schedule exactly — an exponential backoff off a two-second
# base, capped at a minute, jittered. The cap keeps a long run of failures from turning into a long
# silence between them, and the jitter matters because a router that just refused a hundred bots should
# not get all hundred back at the same instant.
MODEL_RETRY_BACKOFF = 2          # seconds before try 2; doubled for each try after that, up to the cap
MODEL_RETRY_BACKOFF_MAX = 60
# The most one step may spend *failing*, across every attempt it makes. This is what makes a high try
# count safe rather than reckless, and it needs no setting of its own because it counts both kinds of
# failure the same way. A router that is refusing calls fails in milliseconds, so all eleven tries and
# their backoff (about six minutes of waiting) fit inside this comfortably; an attempt that went
# *quiet*, on the other hand, burns the whole stall budget before it counts as a failure, so a router
# that has stopped answering reaches this ceiling after three tries and the turn reports instead of
# waiting out an hour of silence. Same policy, same number, and the cheap case — by far the common one
# — is the one that gets all eleven.
MODEL_FAIL_SECONDS = 400
MODEL_RETRIES = DEFAULT_MODEL_RETRIES
MODEL_STALL_SECONDS = DEFAULT_MODEL_STALL_SECONDS
# How many tokens one answer may use. This is a *ceiling*, not a cost — nothing is billed for room
# that goes unused — and a thin ceiling is what makes a step come back with nothing at all: the
# router counts a reasoning model's thinking against this budget, so at the old 1600 a model that
# spent 1600 tokens working out what to do had no room left to say it, and the step arrived as a
# blank that read like a dead router. ZCode sends the model's own maximum for exactly this reason.
# The ceiling is clamped to half the context window so a model with a small window cannot be asked
# for more than it holds.
MAX_OUTPUT_TOKENS = 8192
def model_retries(settings):
    """How many times one step may try again after an attempt that said nothing: the saved number when
    there is one, else the default. 0 means "use the default", like max_steps. The ceiling is the one
    the settings screen offers — this number multiplies a two-minute wait, so a hand-edited file must
    not be able to turn one step into an afternoon."""
    try: n = int((settings.get("context") or {}).get("model_retries") or 0)
    except Exception: n = 0
    return min(n, 10) if n > 0 else DEFAULT_MODEL_RETRIES
def model_stall_seconds(settings):
    """How long one attempt may go with no new content, in seconds: the saved number when there is
    one, else the default. 0 means "use the default"."""
    try: n = int((settings.get("context") or {}).get("model_stall_seconds") or 0)
    except Exception: n = 0
    return min(n, 3600) if n > 0 else DEFAULT_MODEL_STALL_SECONDS
def sync_model_policy(s):
    """Re-aim the two globals the model client reads. `chat` and `chat_stream` are handed a model and
    not the settings dict, so the policy travels the way ROUTER and KEY do: module globals, set from
    the settings when they load and re-aimed whenever they are saved."""
    global MODEL_RETRIES, MODEL_STALL_SECONDS
    MODEL_RETRIES = model_retries(s); MODEL_STALL_SECONDS = model_stall_seconds(s)
def _retry_limit(attempts):
    """How many tries one step may make: the caller's number when it gives one — the wrap-up asks for
    a single attempt — and the saved policy otherwise."""
    return max(1, int(attempts or (MODEL_RETRIES + 1)))
def _retry_wait(attempt):
    """Seconds to wait before try number `attempt` + 1, on ZCode's schedule: an exponential backoff
    off MODEL_RETRY_BACKOFF, capped at MODEL_RETRY_BACKOFF_MAX and jittered to somewhere between half
    the interval and all of it. The jitter is the point of it — a router that just refused a hundred
    bots should not get all hundred back at the same instant — so the wait is a bound, not a promise,
    and the cap holds the *bound*: nothing here ever waits longer than MODEL_RETRY_BACKOFF_MAX."""
    return min(MODEL_RETRY_BACKOFF * (2 ** (attempt - 1)), MODEL_RETRY_BACKOFF_MAX) * (0.5 + 0.5 * random.random())
def output_budget(model, want=None):
    """The ceiling on one answer: what the caller asked for, else MAX_OUTPUT_TOKENS, and never more
    than half the window the model holds. The caller's number wins so a deliberately short call stays
    short, but see MAX_OUTPUT_TOKENS for why the *default* is generous: on a reasoning model a thin
    ceiling is not a short answer, it is no answer."""
    n = int(want) if want else MAX_OUTPUT_TOKENS
    return max(64, min(n, model_context(model) // 2))
# A stall is a fact about one endpoint and one model, and the point of naming them is that the cure is
# not in this app: a router that keeps going quiet will keep going quiet, and the only thing the user
# can do about it is move off it. What marks an outage is a *run* of failures — three blips an hour
# apart are three unrelated transients, and "switch this bot" over them is noise the user is right to
# resent. So the count is of consecutive failures, and any answer resets it.
_stalls = {}                                     # "host|model" -> consecutive failures
def _endpoint_label():
    """The router's host, for naming it in a report. Never the key, and never the full URL — the path
    is the operator's business and the label is read out in a room."""
    try:
        host = urlparse(ROUTER).netloc or ROUTER
    except Exception:
        host = ROUTER
    return host.replace("www.", "")[:80]
def note_stall(model):
    """Record one failure for this endpoint+model and return how many in a row it now is."""
    key = "%s|%s" % (_endpoint_label(), model or "")
    _stalls[key] = _stalls.get(key, 0) + 1
    return _stalls[key]
def note_answer(model):
    """The endpoint answered, so the run is over: the next stall is a fresh one and not the fourth of a
    run, which is what keeps a router that is working most of the time from being reported as a pattern."""
    _stalls.pop("%s|%s" % (_endpoint_label(), model or ""), None)
def _ordinal(n):
    """2 -> "2nd", for a notice that reads as a sentence rather than as a counter."""
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return "%d%s" % (n, suf)
def _elapsed(secs):
    """A wait, in the unit that reads best: seconds under a minute, minutes above it."""
    secs = max(0.0, float(secs or 0))
    return "%ds" % max(1, round(secs)) if secs < 60 else "%dm" % max(1, round(secs / 60.0))
def _model_failure_note(bot, model, msg, reason=""):
    """What the room is told when a step spent every attempt and still ended with nothing.

    A stall, an empty completion and a 5xx are one thing to the reader — the step came back with
    nothing — so one notice covers them and all of them count toward the same run. What the notice
    must never omit is the cost: how many times the router was tried, and how long that took. A
    "the model stopped answering" with neither number is a report the user cannot act on, and it
    reads as though nothing was tried at all."""
    n = note_stall(model)
    where = "%s on %s" % (model or "the model", _endpoint_label())
    tries = int(msg.get("attempts") or 1)
    if msg.get("spoke"):
        note = ("%s's model stopped answering part-way through — %s went quiet for %s mid-answer, and "
                "that step was abandoned. Retrying would have appended a second answer to the first."
                % (bot["name"], where, _elapsed(msg.get("waited"))))
    elif msg.get("stalled"):
        mins = max(1, round(MODEL_STALL_SECONDS / 60.0))
        waited = max(1, round(float(msg.get("waited") or 0) / 60.0))
        note = ("%s's model stopped answering — %s. Tried %d time%s, waiting up to %d minute%s each "
                "(about %d minute%s in total): every attempt went silent."
                % (bot["name"], where, tries, "" if tries == 1 else "s",
                   mins, "" if mins == 1 else "s", waited, "" if waited == 1 else "s"))
    else:
        note = ("%s's model call failed — %s. Tried %d time%s over %s, and every attempt came back the "
                "same way: %s."
                % (bot["name"], where, tries, "" if tries == 1 else "s",
                   _elapsed(msg.get("waited")), reason or "no answer"))
    if n > 1:
        note += (" That is the %s turn in a row it has failed — it is the router, not the task: "
                 "switch this bot to another model or endpoint." % _ordinal(n))
    else:
        note += " Nothing it had already done was lost: retry the task, or give this bot another model."
    return note
def _post(path, body, timeout=None):
    """One non-streaming request, read against a real deadline.

    `urlopen(...).read()` takes each chunk under a fresh socket timeout, so a response that trickles
    bytes holds the call open forever — the same trap as the streamed path, and the fallback `chat`
    runs through here. Reading chunk by chunk against a clock of our own is what makes `timeout` bound
    the whole call rather than each read. One attempt gets the stall budget, streamed or not, so both
    paths to the model are bounded by the same number."""
    timeout = timeout or MODEL_STALL_SECONDS
    req = urllib.request.Request(ROUTER + path, data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json", "User-Agent": OUT_UA})
    deadline = time.time() + timeout
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = []
        while True:
            chunk = r.read1(65536)
            if not chunk: break
            out.append(chunk)
            if time.time() > deadline:
                raise socket.timeout("the router was still sending after %ds" % timeout)
        return b"".join(out).decode("utf-8", "replace")
def _nothing_came(msg):
    """True when a response carried no words, no tool call and no thinking — the router answered with
    nothing at all.

    Thinking counts as an answer here, and that is the whole point of the check. A reasoning model
    puts its work in `reasoning_content` and leaves `content` EMPTY whenever it decides to call a
    tool, so judging by `content` alone calls a working model a dead router. ZCode draws the line in
    the same place: its empty-response test requires the reasoning length to be zero."""
    return (not (msg.get("content") or "").strip() and not msg.get("tool_calls")
            and not (msg.get("reasoning") or "").strip())
def chat(model, messages, tools=None, max_tokens=None, tool_choice="auto", timeout=None, attempts=None):
    """One non-streaming answer. `attempts` caps how many tries this call may make — 1 is what the
    wrap-up asks for; the default follows the settings policy. `max_tokens` is the ceiling on the
    answer; the default is generous on purpose (see MAX_OUTPUT_TOKENS).

    A call that spends every attempt and still comes back with nothing returns the error *and* what it
    cost — `attempts` and `waited` — because a failure report that does not say how many times the
    router was tried, or how long that took, is a report the user cannot act on (see
    `_model_failure_note`)."""
    body = {"model": model, "messages": messages, "max_tokens": output_budget(model, max_tokens),
            "temperature": 0.3}
    if tools: body["tools"] = tools; body["tool_choice"] = tool_choice
    last = ""; tried = []; stalled = False
    tries = _retry_limit(attempts)
    made = 0                           # attempts actually sent: the budget can stop the loop early
    t0 = time.time()
    for attempt in range(1, tries + 1):
        stalled = False                # whatever failed *last* is what this call reports
        if attempt > 1:
            # Give up on retrying before starting another attempt rather than after it: what this
            # bounds is how long the step may keep *trying*, and an attempt already begun is allowed to
            # reach its own end. A router refusing calls fails in milliseconds and spends nothing here,
            # so the whole policy fits; one that has gone quiet has already spent the stall budget on
            # each attempt, and this is what stops it at a few (see MODEL_FAIL_SECONDS).
            if time.time() - t0 >= MODEL_FAIL_SECONDS: break
            time.sleep(_retry_wait(attempt - 1))
        made = attempt
        try:
            # One parser for a completion body, shared with the streamed path's fallback, so a body
            # that is not a completion is reported the same way whichever path reached it — with an
            # excerpt of what the router actually said, not the name of the Python exception it
            # tripped. `raw.index("{")` on a comment-only SSE body raises `ValueError: substring not
            # found`, and that string used to be what the room was told the model had failed with.
            whole = _completion_from(_post("/chat/completions", body, timeout=timeout))
            if whole["content"].startswith("[model error"):
                last = whole["content"].split(": ", 1)[-1].rstrip("]"); continue
            # A 200 with no words, no tool call and no thinking is not an answer — it is the router
            # having nothing to say, which used to end a turn on a blank and vanish from the log.
            # Treat it as a failed attempt so the retry runs, exactly as a 5xx would.
            if _nothing_came(whole):
                last = "empty response from the router"; continue
            return whole
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code} {e.reason}"
            # A 404 usually means the model name is unknown to this router — retry once
            # with the configured default so one bad model cannot kill the whole turn.
            if e.code == 404 and model != DEFAULT_MODEL and DEFAULT_MODEL not in tried:
                tried.append(model); model = DEFAULT_MODEL; body["model"] = DEFAULT_MODEL; continue
        except Exception as e:
            last = str(e)[:200]
            # A timeout is not a special case any more. An attempt that timed out sent nothing, so a
            # retry cannot duplicate an answer nobody has seen, and a router that went quiet once often
            # answers the next try — retrying it is exactly the case this policy is for. It is still
            # named, though: `stalled` lets the turn report it with the same numbers a streamed stall
            # gets, instead of as a bare error string.
            stalled = isinstance(e, (socket.timeout, TimeoutError)) or isinstance(
                getattr(e, "reason", None), (socket.timeout, TimeoutError))
    # `attempts` is how many tries were actually *made*, which is not always the policy's number: the
    # failure budget can stop a step short of it, and a report that claims tries it never made is
    # exactly the kind of number the user cannot act on (see `_model_failure_note`).
    out = {"content": f"[model error: {last}]", "tool_calls": [], "usage": {},
           "attempts": made, "waited": round(time.time() - t0, 1)}
    if stalled: out["stalled"] = True
    return out

def _completion_from(raw):
    """One non-streaming completion body, parsed into the shape `chat` returns. A body that is not a
    completion (an error page, a partial write) comes back as the same visible error string `chat`
    would produce, so the caller sees one failure rather than a parse exception.

    `reasoning` and `finish` ride along because both decide what the caller does next: a reasoning
    model answers with its thinking in `reasoning_content` and an EMPTY `content` whenever it decides
    to call a tool, so content alone cannot tell "the model said nothing" from "the model is working"
    (see `_agent_loop`). `finish` is what says whether the answer was cut off at the ceiling."""
    try:
        raw = raw.split("data: [DONE]")[0].strip()
        obj = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        ch = (obj.get("choices") or [{}])[0]
        m = ch.get("message") or {}
        return {"content": m.get("content") or "", "tool_calls": _tool_calls_of(m),
                "reasoning": m.get("reasoning_content") or m.get("reasoning") or "",
                "finish": ch.get("finish_reason") or "", "usage": obj.get("usage") or {}}
    except Exception:
        # Why it failed to parse is a Python internal ("substring not found") and tells the user
        # nothing; what the router actually said does — an error page, a gateway notice, a partial
        # write. So the excerpt is the report, and it is what the turn quotes in the room.
        head = " ".join((raw or "").split())[:160]
        return {"content": "[model error: the router answered with something that is not a completion"
                           + (": " + head if head else "") + "]", "tool_calls": [], "usage": {},
                "reasoning": "", "finish": ""}
def _tool_calls_of(message):
    """The tool calls in a message, from either field they arrive in.

    `tool_calls` is the current shape. `function_call` is the single-call field it replaced, and some
    gateways still emit it — a call that arrives that way and is read as no call at all is a step the
    bot appears to have skipped, so it is normalised here rather than missed."""
    calls = list(message.get("tool_calls") or [])
    legacy = message.get("function_call")
    if legacy and legacy.get("name"):
        calls.append({"id": "", "type": "function",
                      "function": {"name": legacy.get("name"),
                                   "arguments": legacy.get("arguments") or "{}"}})
    return calls

def chat_stream(model, messages, tools=None, max_tokens=None, attempts=None):
    """One streamed step, with the retry policy applied. `attempts` caps how many tries it may make —
    1 is what the wrap-up asks for; the default follows the settings policy.

    An attempt that goes quiet having said *nothing* is retried, because that is the router dropping the
    call — the user's own case, and the only case a retry cannot spoil: nothing was streamed, so there is
    no text to duplicate. An attempt that had already streamed a delta is never retried: the bot has
    spoken, and a second attempt would append a second answer to the first, so that stall is reported as
    stopping part-way (see `_chat_stream_once`)."""
    tries = _retry_limit(attempts)
    made = 0                           # attempts actually sent: the budget can stop the loop early
    t0 = time.time()
    for attempt in range(1, tries + 1):
        # The same failure budget `chat` keeps: a stream that goes quiet spends the whole stall budget
        # on each attempt, so this is what stops a dead router from being retried eleven times over
        # (see MODEL_FAIL_SECONDS). Cheap failures spend nothing here and get the whole policy.
        if attempt > 1:
            if time.time() - t0 >= MODEL_FAIL_SECONDS: break
            time.sleep(_retry_wait(attempt - 1))
        made = attempt
        spoke = False; msg = None
        for kind, val in _chat_stream_once(model, messages, tools, max_tokens):
            if kind == "delta":
                spoke = True; yield ("delta", val)
            else:
                msg = val
        if not msg.get("stalled") or spoke or attempt >= tries:
            if msg.get("stalled"):
                # The numbers the room is owed: how many tries, and how long that was. Carried on the
                # `done` rather than guessed at the call site, which cannot see either.
                msg["attempts"] = attempt; msg["waited"] = round(time.time() - t0, 1); msg["spoke"] = spoke
            yield ("done", msg); return
    # Only reached when the failure budget stopped the loop before its last try: the step is over with
    # nothing to show, and saying so is the whole point of the budget.
    yield ("done", {"content": "[model error: the router sent nothing new for %ds]"
                               % MODEL_STALL_SECONDS,
                    "tool_calls": [], "usage": {}, "stalled": True,
                    "attempts": made, "waited": round(time.time() - t0, 1), "spoke": False})

def _chat_stream_once(model, messages, tools=None, max_tokens=None):
    """`chat`, read as it is written: yields ("delta", text) for each piece of the answer the moment
    the router produces it, then ("done", {content, tool_calls, usage}) once at the end.

    A router that ignores `stream` and answers with one JSON body, or one that fails outright, falls
    back to the one-shot `chat` — so live typing is an upgrade to a turn, never a new way for it to
    break. The `done` shape is exactly what `chat` returns, which is why the caller cannot tell the
    two paths apart.

    A router that goes quiet is the one case the caller *is* told about: the `done` carries
    `stalled: True`, so the turn can say in the room why the step ended instead of leaving the user
    with a bot that stopped mid-sentence (see MODEL_STALL_SECONDS). Whether to try again after that is
    the caller's call — see `chat_stream`."""
    body = {"model": model, "messages": messages, "max_tokens": output_budget(model, max_tokens),
            "temperature": 0.3, "stream": True, "stream_options": {"include_usage": True}}
    if tools: body["tools"] = tools; body["tool_choice"] = "auto"
    req = urllib.request.Request(ROUTER + "/chat/completions", data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json", "User-Agent": OUT_UA})
    text, calls, usage, seen = [], {}, {}, False
    plain = []                                 # a router that ignored `stream` sends one JSON body
    thinking = []                              # a reasoning model's work, kept to tell "thinking" from "nothing"
    finish = ""                                # `length` here means the answer was cut off at the ceiling
    # The clock that decides whether the model is still there. It moves only when the router says
    # something *new* — a delta, a tool-call fragment — never when it merely keeps the socket warm,
    # which is what a keepalive comment line does. See MODEL_STALL_SECONDS.
    last = time.time(); stalled = False; raw = b""
    try:
        # Chunks, not `for line in r`: a line that never ends (a router dribbling bytes with no
        # newline) would leave the iterator parked inside the socket read, where this clock cannot be
        # read at all. Every chunk that arrives is a chance to ask whether anything new came with it.
        with urllib.request.urlopen(req, timeout=MODEL_STALL_SECONDS) as r:
            while True:
                try:
                    chunk = r.read1(65536)
                except socket.timeout:
                    stalled = True; chunk = b""  # not one byte in the whole budget — the socket is dead
                if chunk:
                    raw += chunk
                    cut = raw.rfind(b"\n") + 1   # decode whole lines only, so a split multibyte char
                else:
                    cut = len(raw)               # the stream is over: what is left is a line all the
                block, raw = raw[:cut], raw[cut:]   # same (a body with no trailing newline), and a
                done_stream = False                 # character split across chunks is still safe
                for line in block.decode("utf-8", "replace").rstrip("\n").split("\n"):
                    line = line.strip()
                    if not line: continue
                    if not line.startswith("data:"):
                        # `plain` is only for a router that ignored `stream:true` and answered with one
                        # JSON body. A line beginning with `:` is an SSE comment — the transport keeping
                        # the socket warm, which is what a silent router sends by the dozen — and
                        # collecting those turned a comment-only stream into a body that is not JSON,
                        # i.e. the user's "the model call failed: substring not found".
                        if not line.startswith(":"): plain.append(line)
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]": done_stream = True; break
                    try: obj = json.loads(payload)
                    except Exception: continue
                    seen = True
                    if obj.get("usage"): usage = obj["usage"]
                    for ch in obj.get("choices") or []:
                        if ch.get("finish_reason"): finish = ch["finish_reason"]
                        d = ch.get("delta") or {}
                        if d.get("content"):
                            text.append(d["content"]); last = time.time()
                            yield ("delta", d["content"])
                        # A reasoning model streams its thinking here and leaves `content` empty. It
                        # is not shown — it is not the bot's answer — but it *is* evidence the model
                        # is alive and working, which is what keeps a working model from being
                        # reported as a dead router (see `_nothing_came`).
                        if d.get("reasoning_content") or d.get("reasoning"):
                            thinking.append(d.get("reasoning_content") or d.get("reasoning")); last = time.time()
                        # Tool calls arrive in pieces too: the name in one chunk, the arguments spread
                        # over the next few, keyed by index so several parallel calls do not interleave.
                        for tc in d.get("tool_calls") or []:
                            last = time.time()
                            slot = calls.setdefault(tc.get("index", 0),
                                {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                            if tc.get("id"): slot["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"): slot["function"]["name"] += fn["name"]
                            if fn.get("arguments"): slot["function"]["arguments"] += fn["arguments"]
                        # The single-call field `tool_calls` replaced; some gateways still stream it,
                        # and a call read as no call at all is a step the bot appears to have skipped.
                        fc = d.get("function_call") or {}
                        if fc.get("name"):
                            last = time.time()
                            slot = calls.setdefault(0, {"id": "", "type": "function",
                                                        "function": {"name": "", "arguments": ""}})
                            slot["function"]["name"] += fc["name"]
                            if fc.get("arguments"): slot["function"]["arguments"] += fc["arguments"]
                if done_stream or not chunk: break
                if time.time() - last > MODEL_STALL_SECONDS: stalled = True; break
    except Exception:
        seen = False                       # nothing usable streamed — the one-shot call is the answer
    if stalled:
        # Reported through the same door as a dead model rather than raised: a raise would escape
        # `run_agent` with `out["text"]` unset, which is the silence this is here to end. The
        # `stalled` key is what lets the turn name the reason in the room. Tool calls are dropped —
        # a stream that stopped mid-answer holds no whole call, and half of one would be dispatched
        # as a tool the model never finished asking for.
        whole = _completion_from("".join(plain)) if plain else None
        if whole and not whole["content"].startswith("[model error"):
            yield ("done", whole); return
        yield ("done", {"content": "[model error: the router sent nothing new for %ds]"
                                   % MODEL_STALL_SECONDS,
                        "tool_calls": [], "usage": usage, "stalled": True})
        return
    if not seen and plain:
        # A router that ignores `stream:true` answered with one JSON body. Parse that body here rather
        # than throwing it away and re-issuing the whole request through `chat` — that cost a second
        # full call per step, so every turn ran about twice as long on such a router.
        whole = _completion_from("".join(plain))
        # ...but only when the body is actually an answer. A completion with nothing in it at all is
        # the router having nothing to say, and returning it here ended the turn on a single request
        # with no retry and no notice — the one failure mode where the user was told neither how many
        # times it had been tried nor why it stopped. It falls through to the one-shot call instead,
        # which retries it and, failing that, reports it.
        if not _nothing_came(whole):
            yield ("done", whole); return
    # A stream that opened but carried no words, no tool call and no thinking is the same nothing as a
    # failed one, so it takes the same route: the one-shot `chat`, which retries and, failing that,
    # returns a visible error instead of an empty answer. A stream that carried *thinking* is not that
    # nothing — the model is a reasoning model that answered without acting, and it is handed back so
    # the turn can nudge it to act rather than calling the router dead.
    if not seen or (not text and not calls and not thinking):
        yield ("done", chat(model, messages, tools=tools, max_tokens=max_tokens)); return
    yield ("done", {"content": "".join(text), "tool_calls": [calls[k] for k in sorted(calls)],
                    "usage": usage, "reasoning": "".join(thinking), "finish": finish})
# ---------------------------------------------------------------- context window
# A model errors out when one request exceeds its context window. Nothing here is a tokeniser —
# it is a chars/4 estimate — but it is enough to keep a long run inside the window: the system
# prompt and the newest steps are kept whole and older tool output is dropped, so a run degrades
# instead of failing.
CTX_FALLBACK = 32000
MODEL_CTX = [("gpt-3.5", 16385), ("gpt-4", 128000), ("o1", 200000), ("o3", 200000), ("o4", 200000),
             ("claude", 200000), ("gemini", 1048576), ("qwen", 131072), ("llama", 131072),
             ("deepseek", 131072), ("mistral", 32768), ("grok", 131072), ("kimi", 131072),
             ("glm", 131072), ("phi", 131072)]
def model_context(model):
    """The window a model is known to have, or a conservative default for one we do not know."""
    m = (model or "").lower()
    for key, n in MODEL_CTX:
        if key in m: return n
    return CTX_FALLBACK
def context_budget(model, limit=0):
    """Tokens one request may use. A manual limit from Settings wins; 0 follows the model."""
    try: limit = int(limit or 0)
    except (TypeError, ValueError): limit = 0
    return limit if limit > 0 else model_context(model)
def est_tokens(messages):
    """A chars/4 estimate of what the request costs. Measured off the fields that actually carry
    bytes rather than `json.dumps(m)`: a full serialization of the whole transcript ran once per
    step (`_compact`) and once per message (`fit_messages`), which is O(n²) string-building across a
    long turn — for a figure that is only ever a rough budget. `content` dominates by orders of
    magnitude, and `len()` on a string is free."""
    total = 0
    for m in messages:
        total += len(m["content"]) if isinstance(m.get("content"), str) else len(str(m.get("content") or ""))
        tc = m.get("tool_calls")
        if tc: total += len(json.dumps(tc))
        total += 40                                   # the per-message keys/role/quotes overhead
    return total // 4

# ---------------------------------------------------------------- context panel
# What filled the window, for the chip in the topbar. The rows are the pieces this app actually
# composes a request from, in the order the panel shows them. Each row is measured with the same
# chars/4 estimate `fit_messages` budgets with,
# so the split and the window agree; the number at the top is the real count the provider reported
# for that very request, and the rows are scaled onto it so the shares still sum to 100%.
CTX_ROWS = ("Messages", "System tools", "Connected apps", "MCP tools", "System prompt", "Skills", "Memory & context")
_CTX = {}   # sid -> the measurement for the turn in flight; seeded from the chat, saved at the end
_CTX_LOCK = threading.RLock()

def ctx_get(sid):
    with _CTX_LOCK: return _CTX.get(sid)

def ctx_set(sid, value):
    with _CTX_LOCK: _CTX[sid] = value

def ctx_pop(sid):
    with _CTX_LOCK: return _CTX.pop(sid, None)

def ctx_keys():
    with _CTX_LOCK: return set(_CTX)

def ctx_has(sid):
    with _CTX_LOCK: return sid in _CTX

def ctx_note(sid, parts, messages, usage, limit, model):
    """Fold one request's real usage into the measurement this chat shows. `hit`/`seen` accumulate,
    so the cache figure is the chat's average rather than the last call's."""
    usage = usage or {}                                      # a provider that reports no usage at all
    # chars/4 on the strings themselves, matching `est_tokens` — the rows and the Messages figure are
    # scaled onto the provider's real count below, so they only need to be proportional. Measuring by
    # `json.dumps` re-serialized the whole transcript on every step, which is the O(n²) `est_tokens`
    # exists to avoid.
    est = {}
    for k, v in parts.items():
        if v: est[k] = est.get(k, 0) + len(v) // 4
    est["Messages"] = est_tokens([m for m in messages if m.get("role") != "system"])
    total_est = sum(est.values())
    real = int(usage.get("prompt_tokens") or 0)
    scale = (real / total_est) if (real and total_est) else 1.0
    det = usage.get("prompt_tokens_details") or {}
    # `cached_tokens` at the top level reads 0 on this router while the detail block has the real
    # number, so the detail block is asked first and the flat field only as a fallback.
    cached = int(det.get("cached_tokens") or usage.get("prompt_cache_hit_tokens") or 0)
    with _CTX_LOCK: rec = _CTX.get(sid) or {"hit": 0, "seen": 0}
    rows = [{"label": k, "tokens": int(round(est[k] * scale))} for k in CTX_ROWS if est.get(k)]
    # Rounding each row on its own can leave the split a token off the total the panel prints beside
    # it. Absorb the drift into the largest row, so the rows always add up to the number shown.
    if rows:
        drift = (real or total_est) - sum(r["tokens"] for r in rows)
        if drift: rows[max(range(len(rows)), key=lambda i: rows[i]["tokens"])]["tokens"] += drift
    rec = {"hit": rec["hit"] + cached, "seen": rec["seen"] + real,
           "tokens": real or total_est, "limit": limit, "model": model, "at": int(time.time()),
           "rows": rows}
    with _CTX_LOCK: _CTX[sid] = rec
    return rec

def fit_messages(messages, budget):
    """Keep a request inside the window by dropping its oldest steps. Returns (messages, dropped).

    The system prompt is trimmed from its end when it alone is over half the window, which is why the
    lines a bot cannot work without sit at its front (see `_agent_loop`). The ask is pinned: a run is
    compressed by dropping steps, never the thing that was asked — a bot that can no longer see the
    question spends its remaining steps rediscovering it, which is how a turn runs out of them."""
    if budget <= 0 or len(messages) < 3: return messages, 0
    head = messages[0]; trimmed = False
    if est_tokens([head]) > budget // 2:                 # an oversized system prompt is trimmed first
        head = {"role": "system", "content": head["content"][: budget * 2]}; trimmed = True
    used = est_tokens([head]); keep = []
    tail = messages[1:]
    ask = next((i for i, m in enumerate(tail) if m.get("role") == "user"), None)
    for i in range(len(tail) - 1, -1, -1):
        if i == ask: continue                            # pinned, and put back in its place below
        m = tail[i]; t = est_tokens([m])
        if keep and used + t > budget * 4 // 5: break    # a fifth of the window is left for the reply
        keep.append(m); used += t
    keep.reverse()
    if ask is not None:
        p = tail[ask]; t = est_tokens([p])
        if used + t <= budget: keep.insert(0, p); used += t
    # The kept messages are a suffix, so the first of them can be a `tool` result whose owning
    # `assistant` (the one carrying the tool_calls) was dropped above it. A router rejects a tool
    # message with no call before it, so a turn would die exactly when compaction kicked in. Drop the
    # orphans: a tool result with no question before it is unreadable to the model anyway.
    while keep and keep[0].get("role") == "tool": keep.pop(0)
    dropped = len(tail) - len(keep)
    # A trimmed system prompt must still be sent trimmed even when the transcript fit: it is over half
    # the window on its own, and returning the original would hand the provider a prompt that alone
    # overflows it — the exact case the trim exists for.
    if not dropped: return ([head] + tail, 0) if trimmed else (messages, 0)
    return ([head, {"role": "system", "content": f"({dropped} earlier step(s) were compressed "
             "to fit this model's context window.)"}] + keep, dropped)

# How much of an old tool result survives compaction, and how many of the newest are kept whole.
TOOL_STUB_CHARS = 600
KEEP_FULL_TOOLS = 6
_TRIM_NOTE = "\n…(trimmed to keep the run inside the model's window)"

def _compact(messages, budget):
    """Free room for the next step by trimming the OLDEST tool outputs in place — same order, same
    length, same ask — and report how many were trimmed (0 when there was room).

    This is what keeps the router's prefix cache warm across a long turn. `fit_messages` frees the
    same room by *deleting* messages from the middle, which changes the prefix on every step and makes
    the provider re-read the whole transcript from scratch each time — the reason a long turn grew
    slower the longer it ran. Stubbing is append-only: an output trimmed once stays trimmed (a stub is
    never longer than TOOL_STUB_CHARS, so it drops out of the candidate set), so from the next step on
    the request is a pure append and the cache holds. `fit_messages` still runs afterwards as the
    backstop for a single step too large to stub away."""
    if budget <= 0: return 0
    idx = [i for i, m in enumerate(messages)
           if m.get("role") == "tool" and len(str(m.get("content") or "")) > TOOL_STUB_CHARS]
    if len(idx) <= KEEP_FULL_TOOLS: return 0
    target = budget * 3 // 5
    size = est_tokens(messages)
    if size <= target: return 0
    trimmed = 0
    for i in idx[:-KEEP_FULL_TOOLS]:
        m = messages[i]; c = str(m.get("content") or "")
        if len(c) <= TOOL_STUB_CHARS: continue
        stub = c[:TOOL_STUB_CHARS - len(_TRIM_NOTE)] + _TRIM_NOTE
        size -= (len(c) - len(stub)) // 4          # only this message's content changed
        m["content"] = stub
        trimmed += 1
        if size <= target: break
    return trimmed

def vision(question, data_url, fallback=""):
    msgs = [{"role": "user", "content": [{"type": "text", "text": question},
            {"type": "image_url", "image_url": {"url": data_url}}]}]
    last = ("(no vision model is configured — set one in Settings → Models, or the bot's own model is "
            "used when it can see)")
    # The configured vision models, then the bot's own model. A bot that is answering at all is running
    # on a model, and most of them can see — so a vision model that is unset or that errors must not be
    # the end of it.
    for m in VISION_MODELS + ([fallback] if fallback and fallback not in VISION_MODELS else []):
        try:
            out = chat(m, msgs, max_tokens=400)["content"].strip()
            if out and not out.startswith("[model error"): return out
            last = out or last
        except Exception as e: last = f"(vision error: {e})"
    return last
def media_models():
    """Which models the router advertises as able to emit images / videos."""
    try:
        req = urllib.request.Request(ROUTER + "/models", headers={"Authorization": "Bearer " + KEY, "User-Agent": OUT_UA})
        items = json.load(urllib.request.urlopen(req, timeout=30)).get("data") or []
    except Exception:
        return {"image": [], "video": []}
    img = [m["id"] for m in items
           if (m.get("capabilities") or {}).get("imageOutput") and m["id"] not in IMAGE_MODEL_DEAD]
    vid = [m["id"] for m in items if (m.get("capabilities") or {}).get("videoOutput")]
    return {"image": sorted(img), "video": sorted(vid)}
def gen_image(prompt, model="", timeout=120, image=""):
    """Draw a picture with an image-capable model. Returns (data_url, model_used) or ("", error).

    `image` is an optional data URL to draw *from* (image-to-image): the same two routes that draw
    from text draw from a photo as well."""
    content = ([{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": image}}]
               if image else prompt)
    msgs = [{"role": "user", "content": content}]
    last = "(no image model configured)"
    for m in ([model] if model else []) + [x for x in IMAGE_MODELS if x != model]:
        try:
            raw = _post("/chat/completions", {"model": m, "messages": msgs, "max_tokens": 400}, timeout=timeout)
            raw = raw.split("data: [DONE]")[0].strip()
            obj = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
            c = obj["choices"][0]["message"].get("content")
            if isinstance(c, list):
                for p in c:
                    if isinstance(p, dict) and p.get("type") == "image_url":
                        return p["image_url"]["url"], m
            last = m + ": model returned no image"
        except Exception as e:
            last = "%s: %s" % (m, str(e)[:120])
            # A provider that hangs on one model will hang on the next, so do not spend the whole
            # budget waiting out every configured model in turn.
            if isinstance(e, (socket.timeout, TimeoutError)) or "timed out" in str(e).lower(): break
    return "", last

# ---------------------------------------------------------------- tools
def _fn(name, desc, props, req):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": req}}}
TOOL_SCHEMAS = {
 "run_shell":  _fn("run_shell","Run a shell command in the shared sandbox and return its output.",
                   {"command":{"type":"string","description":"the shell command"},
                    "timeout":{"type":"integer","description":"seconds to allow before the command is killed; default 45, max 600 — pass a bigger one for an install or a test run"}}, ["command"]),
 "read_file":  _fn("read_file","Read a text file from the sandbox.", {"path":{"type":"string"}}, ["path"]),
 "write_file": _fn("write_file","Write text to a file in the sandbox (overwrites).",
                   {"path":{"type":"string"},"content":{"type":"string"}}, ["path","content"]),
 "list_files": _fn("list_files","List files in a sandbox directory.",
                   {"path":{"type":"string","description":"default '.'"}}, []),
 "generate_image": _fn("generate_image","Draw an image from a text prompt and save it in the sandbox. The picture is shown in the chat.",
                   {"prompt":{"type":"string","description":"what to draw, in English"},
                    "filename":{"type":"string","description":"optional, e.g. hero.png"}}, ["prompt"]),
 "browser_open": _fn("browser_open","Open a URL and return the page's url, title and visible text. Which sites open already signed in, and which open anonymously, is set out under “Browsing” in your instructions — this tool does what that says. Use it for public pages instead of curl.",
                   {"url":{"type":"string"}}, ["url"]),
 "browser_read": _fn("browser_read","Return the current page's url, title and visible text.", {}, []),
 "browser_click": _fn("browser_click","Click an element by CSS selector on the current page.",
                   {"selector":{"type":"string"}}, ["selector"]),
 "browser_type": _fn("browser_type","Type text into an input (CSS selector) on the current page.",
                   {"selector":{"type":"string"},"text":{"type":"string"}}, ["selector","text"]),
 "browser_press": _fn("browser_press","Press a keyboard key, e.g. 'Enter'. Returns the page after.",
                   {"key":{"type":"string"}}, ["key"]),
 "browser_back": _fn("browser_back","Go back one page in the browser history.", {}, []),
 "browser_eval": _fn("browser_eval","Run one JavaScript expression in the page you are driving and get its value back. The escape hatch for what click/type cannot express: read a list, count things, scroll, or wait for a slow page — an async expression works, e.g. (async()=>{await new Promise(r=>setTimeout(r,1500));return document.body.innerText.length})() . One eval does in a single step what would otherwise take many read/click round trips. Return JSON you can filter. A value too long to return is cut, and the cut says so — ask again with a higher max_chars, or return less.",
                   {"expression":{"type":"string","description":"a JS expression; wrap async work as (async()=>{...})()"},
                    "max_chars":{"type":"integer","description":"cap on the returned text, default 4000; raise it to get a long list whole"}}, ["expression"]),
 "browser_see": _fn("browser_see","Screenshot the current page and LOOK at it with vision, answering your question.",
                   {"question":{"type":"string","description":"what to look for"}}, ["question"]),
 "browser_save": _fn("browser_save","Wait for a CSS selector to appear (e.g. the picture a site just made), then download it into the sandbox and show it in the chat.",
                   {"selector":{"type":"string","description":"CSS selector of the image/video, e.g. 'img'"},
                    "filename":{"type":"string","description":"optional, e.g. hero.png"},
                    "wait_seconds":{"type":"integer","description":"how long to wait for it, default 60, max 600"}}, ["selector"]),
 "memory_update": _fn("memory_update","Append a durable note to your long-term memory file.",
                   {"note":{"type":"string"}}, ["note"]),
 "use_skill":  _fn("use_skill","Read one of your skills: its full guidance, or a single file it bundles. Call this before starting a job a skill covers — the prompt carries only the index.",
                   {"skill":{"type":"string","description":"the skill's id or name"},
                    "file":{"type":"string","description":"optional, a bundled file to read instead, e.g. references/api.md"}}, ["skill"]),
 "delegate":   _fn("delegate","Delegate one concrete task to one teammate and get their report back. "
                             "Say in the task exactly what you want back — the items, the numbers, the "
                             "format — because that report is all you get: a teammate asked loosely for "
                             "\"3 posts with 30+ replies\" hands back a paragraph about having looked.",
                   {"role":{"type":"string"},"task":{"type":"string"}}, ["role","task"]),
 "finish":     _fn("finish","Finish your turn with a short, concrete report of what you did.",
                   {"summary":{"type":"string"}}, ["summary"]),
}
ALL_TOOLS = ["run_shell","read_file","write_file","list_files","generate_image","browser_open","browser_read","browser_click",
             "browser_type","browser_press","browser_back","browser_eval","browser_see","browser_save","memory_update","use_skill","delegate","finish"]
DEFAULT_TOOLS = {b["id"]: (ALL_TOOLS if b["id"] != "producer" else ["delegate","memory_update","use_skill","finish"]) for b in DEFAULT_BOTS}

# Plan-only mode: the bot investigates with read-only tools and reports a plan, then stops. Nothing
# that changes the world is offered, so "plan" cannot quietly turn into "do" — the user approves the
# plan first, and the chat is switched to full access only then.
PLAN_TOOLS = {"read_file", "list_files", "use_skill", "browser_open", "browser_read", "browser_see", "finish"}
PLAN_BRIEF = ("\n\n## PLAN MODE\nYou are planning, not doing. You have only read-only tools; inspect what "
              "you need with them. Do NOT try to run commands or change files — those tools are not "
              "available to you now, so such a call would fail. End the turn by calling `finish`, and make "
              "its summary a short, numbered plan: the steps in order, the files you would touch, and how "
              "you would verify the result. The user approves the plan before anything runs.")

def tool_schemas(bot, peers):
    """The tools this bot is offered, given the bots it is allowed to hand work to.

    `peers` is the bot's own team, not the roster — see `_agent_loop`, which is the one place that
    decides it. It is a parameter rather than a lookup so the `delegate` enum below and the check
    that enforces it cannot be built from two different lists."""
    allow = bot.get("tools_allow")
    names = allow if allow else DEFAULT_TOOLS.get(bot["id"], ALL_TOOLS)
    out = []
    for n in names:
        if n not in TOOL_SCHEMAS: continue
        if n == "delegate":
            # Nobody to hand to is no `delegate` tool: a room whose only member is its lead has no
            # teammates, and an enum with nothing in it is a call the model cannot make anyway.
            if not peers: continue
            ids = [b["id"] for b in peers if b["id"] != bot["id"]]
            out.append({"type":"function","function":{"name":"delegate","description":"Delegate one concrete task to one teammate and get their report back. Say in the task exactly what you want back — the items, the numbers, the format — because that report is all you get.",
                "parameters":{"type":"object","properties":{"role":{"type":"string","enum":ids},"task":{"type":"string"}},"required":["role","task"]}}})
        else: out.append(TOOL_SCHEMAS[n])
    return out

# ---------------------------------------------------------------- connected apps
# Each connector stores a token (write-only) in settings.json. While connected it
# contributes a real tool to every bot: a thin authenticated passthrough to that
# app's HTTP API, so a bot can read and act on the real service, not a mock.
# The three Google connectors share one sentence about their credential — kept here so it cannot
# drift between them.
GOOGLE_DESC = ("Google access tokens last about an hour, so this takes a refresh token plus an "
               "OAuth client — the access token is renewed for you.")
CONNECTORS = {
  # `auth` declares how the credential is presented, so a provider that is not a plain bearer
  # token is a one-line difference instead of a special case buried in the request builder:
  #   bearer  Authorization: Bearer <token>
  #   raw     Authorization: <token>          (Linear personal API keys carry no prefix)
  #   google  a refresh token exchanged for a short-lived access token (see google_access_token)
  #   none    no credential (webhooks)
  "gmail":    {"name": "Gmail",           "tool": "gmail_api",    "base": "https://gmail.googleapis.com",
               "auth": "google", "desc": "Read and send mail. " + GOOGLE_DESC,
               "test": {"method": "GET", "path": "/gmail/v1/users/me/profile"}},
  "slack":    {"name": "Slack",           "tool": "slack_api",    "base": "https://slack.com/api",
               "auth": "bearer", "desc": "Post messages, read channels and users via the Web API. A bot token (xoxb) works.",
               "test": {"method": "POST", "path": "/auth.test"}},
  "github":   {"name": "GitHub",          "tool": "github_api",   "base": "https://api.github.com",
               "auth": "bearer", "desc": "Repos, issues, PRs, files, comments — REST v3. A personal access token works; set a custom base for GitHub Enterprise.",
               "test": {"method": "GET", "path": "/user"}},
  "notion":   {"name": "Notion",          "tool": "notion_api",   "base": "https://api.notion.com/v1",
               "auth": "bearer", "extra": {"Notion-Version": "2022-06-28"}, "desc": "Search and read/write pages via the integration API.",
               "test": {"method": "GET", "path": "/users/me"}},
  "linear":   {"name": "Linear",          "tool": "linear_api",   "base": "https://api.linear.app/graphql",
               "auth": "raw", "desc": "Issues, projects and teams via GraphQL (POST the query in body). Paste a personal API key — Linear takes it with no Bearer prefix.",
               "test": {"method": "POST", "path": "/", "body": {"query": "{ viewer { id name } }"}}},
  "gdrive":   {"name": "Google Drive",    "tool": "drive_api",    "base": "https://www.googleapis.com/drive/v3",
               "auth": "google", "desc": "List, read and upload Drive files. " + GOOGLE_DESC,
               "test": {"method": "GET", "path": "/about?fields=user"}},
  "calendar": {"name": "Google Calendar", "tool": "calendar_api", "base": "https://www.googleapis.com/calendar/v3",
               "auth": "google", "desc": "Read and create calendar events. " + GOOGLE_DESC,
               "test": {"method": "GET", "path": "/users/me/calendarList"}},
  "webhook":  {"name": "Webhooks",        "tool": "webhook_post", "base": "",
               "auth": "none", "desc": "POST JSON to any HTTPS URL — Zapier, n8n, IFTTT or your own endpoint. Save a default URL and an optional shared secret (sent as X-Webhook-Secret).",
               "test": {"method": "POST", "path": "/", "body": {"text": "anzen-bot test ping"}}},
}
CONNECTOR_BY_TOOL = {c["tool"]: cid for cid, c in CONNECTORS.items()}

def _connector_entry(settings, cid):
    return next((x for x in (settings.get("connectors") or []) if x.get("id") == cid), None)

# ---------------------------------------------------------------- google oauth
# Google hands out access tokens that die after about an hour, so pasting one — which is what this
# used to ask for — bought you a connector that worked until lunchtime and then failed every call
# with a 401 and no way to fix it. What actually works is a refresh token: a long-lived credential
# you exchange for a fresh access token whenever the old one is close to expiry.
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_SETUP_URL = "https://developers.google.com/oauthplayground"
_TOKEN_CACHE = {}          # connector id -> (access_token, expiry_epoch_seconds, credential fingerprint)
_TOKEN_LOCK = threading.Lock()
_REFRESH_LOCKS = {}        # connector id -> the lock that makes one refresh at a time (see google_access_token)
TOKEN_SKEW = 120           # renew this many seconds before the token actually expires

def google_creds(ent):
    """The three values a Google connector needs, or ('', '', '') if any is missing."""
    e = ent or {}
    return ((e.get("client_id") or "").strip(), (e.get("client_secret") or "").strip(),
            (e.get("token") or "").strip())

def google_access_token(cid, ent):
    """A live access token for a Google connector, refreshed on demand. Returns (token, error)."""
    cid_in, secret, refresh = google_creds(ent)
    if not (cid_in and secret and refresh):
        return "", "this needs an OAuth client id, client secret and refresh token"
    key = (cid_in, refresh)          # a changed credential must not reuse the old token
    with _TOKEN_LOCK:
        hit = _TOKEN_CACHE.get(cid)
        if hit and hit[2] == key and hit[1] > time.time() + TOKEN_SKEW: return hit[0], ""
        rlock = _REFRESH_LOCKS.setdefault(cid, threading.Lock())
    # One refresh per connector at a time. A cold cache with several tool calls in flight (a bot
    # fanning out, a room running members at once) otherwise sent the same refresh N times.
    with rlock:
        with _TOKEN_LOCK:            # a caller that held the lock before us may have just filled it
            hit = _TOKEN_CACHE.get(cid)
            if hit and hit[2] == key and hit[1] > time.time() + TOKEN_SKEW: return hit[0], ""
        return _google_refresh(cid, cid_in, secret, refresh, key)

def _google_refresh(cid, cid_in, secret, refresh, key):
    """The network half of `google_access_token`, run under that connector's refresh lock."""
    form = urlencode({"client_id": cid_in, "client_secret": secret,
                      "refresh_token": refresh, "grant_type": "refresh_token"}).encode()
    req = urllib.request.Request(GOOGLE_TOKEN_URL, data=form,
                                 headers={"Content-Type": "application/x-www-form-urlencoded",
                                          "Accept": "application/json", "User-Agent": OUT_UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read(20000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        # Google answers a bad credential with a JSON body naming the reason; say it in plain words
        # rather than handing the model a raw error.
        try: err = json.loads(e.read(4000).decode("utf-8", "replace")).get("error") or ""
        except Exception: err = ""
        return "", google_refresh_hint(err or ("HTTP %d" % e.code))
    except Exception as e:
        return "", "could not reach Google to refresh the token: %s" % e
    tok = (data.get("access_token") or "").strip()
    if not tok: return "", "Google did not return an access token" + ((": " + str(data.get("error"))) if data.get("error") else "")
    try: ttl = int(data.get("expires_in") or 3600)
    except Exception: ttl = 3600
    with _TOKEN_LOCK:
        _TOKEN_CACHE[cid] = (tok, time.time() + ttl, key)
    return tok, ""

def google_refresh_hint(err):
    """One actionable sentence for the reasons Google actually returns."""
    e = (err or "").lower()
    if "invalid_grant" in e:
        return ("Google rejected the refresh token (invalid_grant). It has expired or been revoked — "
                "make a new one at " + GOOGLE_SETUP_URL + ". Note a token from an OAuth consent screen "
                "still in Testing mode expires after 7 days.")
    if "invalid_client" in e:
        return "Google rejected the client id/secret pair (invalid_client) — check both against the OAuth client you created."
    if "unauthorized_client" in e:
        return "That OAuth client is not allowed to use this grant type (unauthorized_client) — it must be a Desktop or Web client."
    return "Google refused to refresh the token: " + err

def connector_url_error(url):
    """Reject connector base URLs that could carry credentials or cleartext secrets."""
    if not isinstance(url, str) or not url.strip(): return "a connector base URL is required"
    try: u = urlparse(url.strip())
    except ValueError: return "a connector base URL is invalid"
    if u.scheme != "https": return "connector base URLs must use https"
    if u.username or u.password or u.query or u.fragment:
        return "connector base URLs must not contain credentials or query parameters"
    if not u.hostname: return "a connector base URL is invalid"
    return private_host(url) and "a connector base URL must not be a private address" or ""

def connector_connected(settings, cid):
    c = _connector_entry(settings, cid)
    if not c: return False
    scheme = CONNECTORS[cid]["auth"]
    if scheme == "none": return bool((c.get("base_url") or "").strip())
    if scheme == "google": return all(google_creds(c))
    return bool((c.get("token") or "").strip())

def connector_schemas(settings):
    """Tool schemas for every connected app, appended to each bot's toolset."""
    out = []
    for cid, c in CONNECTORS.items():
        if not connector_connected(settings, cid): continue
        if c["tool"] == "webhook_post":
            out.append(_fn("webhook_post", "POST a JSON payload to a webhook URL (Zapier, n8n, IFTTT or your own endpoint).",
                           {"url": {"type": "string", "description": "the webhook HTTPS URL"},
                            "body": {"type": "object", "description": "JSON payload to send"}}, ["url", "body"]))
        else:
            out.append(_fn(c["tool"], "Call the " + c["name"] + " API with the connected token. " + c["desc"] +
                           " path is appended to " + c["base"] + " (query strings allowed).",
                           {"method": {"type": "string", "enum": ["GET", "POST", "PATCH", "PUT", "DELETE"]},
                            "path": {"type": "string", "description": "API path, e.g. /resource/123"},
                            "body": {"type": "object", "description": "JSON body for POST/PATCH/PUT"}}, ["method", "path"]))
    return out

class _ConnectorRedirectRefused(Exception): pass

class _NoConnectorRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise _ConnectorRedirectRefused("redirect refused by connector: %s" % newurl)

_CONN_OPENER = urllib.request.build_opener(_NoConnectorRedirects)

def _conn_http(url, method, headers, payload):
    data = json.dumps(payload).encode() if payload is not None else None
    if data is not None: headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _CONN_OPENER.open(req, timeout=25) as r:
            return r.status, r.read(20000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(4000).decode("utf-8", "replace")
    except _ConnectorRedirectRefused as e:
        return 502, str(e)
    except urllib.error.URLError as e:
        return 0, "request failed: %s" % (e.reason or e)
    except Exception as e:
        return 0, "request failed: %s" % e

def conn_hint(cid, status):
    """A plain sentence for the failures that have an obvious cause, so the bot (and whoever reads
    its log) is told what to do instead of being handed a raw error body."""
    if status in (401, 403):
        scheme = CONNECTORS[cid]["auth"]
        if scheme == "google":
            return ("the credential was refused (HTTP %d) — check the OAuth client id, client secret "
                    "and refresh token in Settings > Connected apps." % status)
        if scheme == "raw":
            return ("the API key was refused (HTTP %d). A Linear personal key is sent as-is, with no "
                    "Bearer prefix — paste the whole key and nothing else." % status)
        return "the token was refused (HTTP %d) — reconnect the app in Settings > Connected apps." % status
    if status == 404: return "the API said that path does not exist (HTTP 404)."
    if status == 429: return "the API is rate-limiting you (HTTP 429) — try again shortly."
    if status >= 500: return "the API is having trouble (HTTP %d) — try again shortly." % status
    return ""

def _redact_connector_text(text, ent):
    for key in ("token", "client_id", "client_secret"):
        secret = (ent.get(key) or "").strip()
        if secret: text = text.replace(secret, "[redacted]")
    return text

def conn_api(cid, args, settings):
    """Authenticated passthrough to one connected app's API."""
    c = CONNECTORS[cid]; ent = _connector_entry(settings, cid) or {}
    method = (args.get("method") or "GET").upper()
    if method not in ("GET", "POST", "PATCH", "PUT", "DELETE"): return "(bad method)"
    base = (ent.get("base_url") or "").strip() or c["base"]
    if ent.get("base_url") and connector_url_error(base): return "(bad connector base url)"
    if not base.startswith("https://"): return "(bad base url)"
    path = (args.get("path") or "").strip() or "/"
    url = base if path == "/" else base.rstrip("/") + (path if path.startswith("/") else "/" + path)
    headers = {"Accept": "application/json", "User-Agent": OUT_UA, **(c.get("extra") or {})}
    scheme = c["auth"]          # how this provider wants the credential presented
    if scheme == "google":
        token, err = google_access_token(cid, ent)
        if err: return "(" + err + ")"
        headers["Authorization"] = "Bearer " + token
    elif scheme == "bearer":
        headers["Authorization"] = "Bearer " + (ent.get("token") or "").strip()
    elif scheme == "raw":
        headers["Authorization"] = (ent.get("token") or "").strip()
    raw = args.get("body") if method not in ("GET", "DELETE") else None
    status, text = _conn_http(url, method, headers, raw if isinstance(raw, dict) else None)
    out = ("HTTP %d\n" % status) + (text[:6000] or "(empty)")
    hint = conn_hint(cid, status)
    return _redact_connector_text(out + ("\n\n(" + hint + ")" if hint else ""), ent)

def private_host(url):
    """Return a refusal reason when *url* has no valid, globally-routable host.

    Caller-supplied URLs are later fetched with urllib, which follows redirects by default. This check
    validates the initial host only; redirect targets remain a residual concern in `_conn_http`.
    """
    if not isinstance(url, str) or not url.strip(): return "invalid URL host"
    try:
        parsed = urlparse(url.strip())
        h = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except (TypeError, ValueError):
        return "invalid URL host"
    if not h: return "invalid URL host"
    if h == "localhost" or h == "local" or h.endswith(".localhost") or h.endswith(".local"):
        return h
    try:
        literal = ipaddress.ip_address(h)
        addresses = [literal]
    except ValueError:
        try:
            infos = socket.getaddrinfo(h, port, type=socket.SOCK_STREAM)
        except (OSError, socket.gaierror, ValueError):
            return h
        addresses = []
        for info in infos:
            try: addresses.append(ipaddress.ip_address(info[4][0]))
            except (ValueError, IndexError): return h
        if not addresses: return h
    # Require every answer to be globally routable. `is_global` alone treats multicast as global on
    # some Python versions, so keep the explicit special-purpose checks too. A mixed DNS answer must
    # not pass merely because one address happens to be public; the client can select the internal one.
    def blocked(address):
        special = isinstance(address, ipaddress.IPv4Address) and address in ipaddress.ip_network("192.0.0.0/24")
        return (special or not address.is_global or address.is_loopback or address.is_private or
                address.is_link_local or address.is_reserved or address.is_unspecified or
                address.is_multicast)
    return h if any(blocked(address) for address in addresses) else ""

def conn_webhook(args, settings):
    ent = _connector_entry(settings, "webhook")
    url = (args.get("url") or "").strip() or ((ent.get("base_url") or "").strip() if ent else "")
    if not url.startswith(("http://", "https://")): return "(a webhook URL is required)"
    h = (urlparse(url).hostname or "").lower()
    local = h in ("localhost", "127.0.0.1", "::1")
    if not url.startswith("https://") and not local:
        return "(webhook URLs must use https — http only for localhost)"
    if private_host(url): return "(webhook host must not be a private address)"
    secret = (ent.get("token") or "").strip() if ent else ""
    headers = {"Accept": "application/json"}
    if secret: headers["X-Webhook-Secret"] = secret
    raw = args.get("body") if isinstance(args.get("body"), dict) else {"text": str(args.get("body") or "")}
    status, text = _conn_http(url, "POST", headers, raw)
    return _redact_connector_text(("HTTP %d\n" % status) + (text[:2000] or "(empty)"), ent)

def conn_missing(cid):
    """What this connector still needs, in the words of its own credential."""
    scheme = CONNECTORS[cid]["auth"]
    if scheme == "google":
        return "not connected — save the OAuth client id, client secret and refresh token first"
    if scheme == "none": return "not connected — save a webhook URL first"
    return "not connected — save a token first"

def _conn_trim(out, n):
    """Shorten a tool result to n chars while keeping the trailing hint, which is the part that
    says what to do about the failure."""
    head, sep, hint = out.partition("\n\n(")
    if len(head) <= n: return out
    return head[:n] + "…" + (sep + hint if sep else "")

def conn_test(cid, settings):
    c = CONNECTORS[cid]
    if not connector_connected(settings, cid): return {"ok": False, "error": conn_missing(cid)}
    if c["tool"] == "webhook_post": out = conn_webhook({}, settings)
    else:
        t = c["test"]
        out = conn_api(cid, {"method": t["method"], "path": t["path"], "body": t.get("body")}, settings)
    return {"ok": out.startswith("HTTP 2"), "out": _conn_trim(out, 400)}

# ---------------------------------------------------------------- MCP (Model Context Protocol)
# Settings > Plugins holds MCP servers, and this is what makes them real: every server a bot is
# allowed to reach contributes its tools to that bot's function-calling toolset, named
# `mcp__<server>__<tool>`, and a call runs against the live server.
#
# The protocol is spoken directly rather than through the official SDK, because the app is
# stdlib-only and no-build and the wire format is small: JSON-RPC 2.0, one `initialize` handshake,
# then `tools/list` and `tools/call`. Both transports real servers use are supported — a local
# command (stdio) and a remote endpoint (Streamable HTTP, falling back to the older HTTP+SSE
# transport, which is still what plenty of deployed servers speak).
MCP_PROTOCOL = "2025-06-18"          # what we offer; whatever the server answers back is accepted
MCP_TIMEOUT = 30                     # a handshake or a listing
MCP_CALL_TIMEOUT = 180               # a tool call: some servers drive a browser or a build
MCP_RETRY_AFTER = 60                 # a server that just failed is not re-spawned on every turn
MCP_MAX_TOOLS = 64                   # a server listing more than this is a directory, not a toolset
MCP_DESC_MAX = 900                   # tool descriptions travel in every request; keep them bounded
MCP_MAX_BODY = 8_000_000
MCP_SID_CAP = 16                     # caps that keep `mcp__<sid>__<tool>` inside the 64-char limit
MCP_TOOL_CAP = 40

class MCPError(Exception):
    """A server that would not come up, or would not answer. The message is shown to the user."""

def _mcp_safe(s, cap):
    """A name as it may appear inside a tool name. Punctuation collapses to `-`, and `_` goes with
    it, so a safe name never contains `__` — which is what lets a tool name be read back into
    (server, tool) by its prefix alone."""
    out = re.sub(r"[^A-Za-z0-9]+", "-", str(s or "")).strip("-")
    return out[:cap] or "x"

def _mcp_arglist(target):
    """A command line as argv, split the way a shell would — so `npx -y pkg /tmp` just works."""
    try: argv = shlex.split(target)
    except ValueError as e: raise MCPError("that command line cannot be read: %s" % e)
    if not argv: raise MCPError("that command line is empty")
    return argv

def _mcp_url_guard(url):
    """Refuse an MCP server URL that points at the cloud metadata service.

    An MCP server over HTTP is usually a local one — `http://127.0.0.1:3000/mcp` is the common
    shape — so loopback and the private ranges stay allowed. A link-local address (169.254.0.0/16,
    fe80::/10) is never an MCP server, and it is where the instance credentials live; a name is
    resolved first so `metadata.google.internal` is caught as well as the bare address."""
    h = (urlparse(url).hostname or "").lower()
    if not h: raise MCPError("that URL names no host")
    try:
        addrs = [ipaddress.ip_address(h)]
    except ValueError:
        try: addrs = [ipaddress.ip_address(a[4][0]) for a in socket.getaddrinfo(h, None)]
        except (socket.gaierror, ValueError): return       # let the connect report its own failure
    if any(a.is_link_local for a in addrs):
        raise MCPError("that address is link-local (the cloud metadata service) — not an MCP server")

def _sse_events(lines):
    """(event, data) pairs from a text/event-stream. One reader serves both a POST that answers with
    SSE and the long-lived GET stream, so both follow exactly the same rules."""
    ev = ""; data = []
    for raw in lines:
        line = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else raw
        line = line.rstrip("\r\n")
        if line == "":
            if data: yield (ev, "\n".join(data))
            ev = ""; data = []
            continue
        if line.startswith(":"): continue                     # a comment, e.g. a keepalive
        field, _, val = line.partition(":")
        if val.startswith(" "): val = val[1:]
        if field == "event": ev = val
        elif field == "data": data.append(val)
    if data: yield (ev, "\n".join(data))

def _mcp_short(b):
    if not b: return ""
    t = (b.decode("utf-8", "replace") if isinstance(b, (bytes, bytearray)) else str(b)).strip()
    return re.sub(r"\s+", " ", t)[:160]

def _mcp_err(e):
    if isinstance(e, dict):
        return "the server refused: %s (code %s)" % (e.get("message") or "no message", e.get("code"))
    return "the server refused: %s" % (e or "no reason given")

def _mcp_schema(s):
    """A tool's `inputSchema` as OpenAI wants it. Servers that omit it get an empty object, which is
    the shape that means 'takes no arguments'."""
    if not isinstance(s, dict) or not s: return {"type": "object", "properties": {}}
    s = json.loads(json.dumps(s))
    s.setdefault("type", "object"); s.setdefault("properties", {})
    return s

class _MCPStdio:
    """A local server: one long-lived child process, newline-delimited JSON-RPC on its stdin/stdout.

    Reads happen on pump threads because a pipe read carries no timeout, and a server that stops
    answering must fail the call rather than wedge the turn that made it. stderr is drained and
    kept, because that is where a server says why it would not start."""

    def __init__(self, argv, env=None):
        e = dict(os.environ); e.update({str(k): str(v) for k, v in (env or {}).items()})
        try:
            self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True, bufsize=1, env=e)
        except (OSError, ValueError) as ex:
            raise MCPError("could not start `%s`: %s" % (argv[0], ex))
        self._q = queue.Queue(); self._err = collections.deque(maxlen=12)
        self._id = 0; self._lock = threading.Lock()
        threading.Thread(target=self._pump, args=(self.p.stdout, None), daemon=True).start()
        threading.Thread(target=self._pump, args=(self.p.stderr, self._err), daemon=True).start()

    def _pump(self, stream, keep):
        try:
            for line in stream:
                line = line.strip()
                if not line: continue
                if keep is None: self._q.put(line)
                else: keep.append(line[:300])
        except Exception: pass

    def alive(self): return self.p.poll() is None

    def why(self):
        if not self.alive(): return "the server exited (code %s)" % self.p.returncode
        return " ".join(self._err) if self._err else "it stopped answering"

    def _write(self, msg):
        try:
            self.p.stdin.write(json.dumps(msg) + "\n"); self.p.stdin.flush()
        except (BrokenPipeError, ValueError, OSError) as e:
            raise MCPError("the server is not accepting input (%s)" % e)

    def notify(self, method, params):
        with self._lock: self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def request(self, method, params, timeout=MCP_TIMEOUT):
        with self._lock:
            self._id += 1; mid = self._id
            self._write({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})
            end = time.time() + timeout
            while True:
                left = end - time.time()
                if left <= 0: raise MCPError("no reply to %s within %ds (%s)" % (method, timeout, self.why()))
                try: raw = self._q.get(timeout=left)
                except queue.Empty: raise MCPError("no reply to %s within %ds (%s)" % (method, timeout, self.why()))
                try: msg = json.loads(raw)
                except ValueError: continue        # a server that logs to stdout; that line is not a reply
                if isinstance(msg, dict) and msg.get("id") == mid: return msg

    def close(self):
        try: self.p.terminate()
        except Exception: pass
        try: self.p.wait(timeout=3)
        except Exception:
            try: self.p.kill()
            except Exception: pass

class _MCPHttp:
    """A remote server.

    Streamable HTTP first, which is what current servers use: POST each JSON-RPC message to the one
    endpoint and take the answer back either as JSON or as a short SSE stream, carrying the session
    id the server handed out at initialize. When the endpoint refuses POST, the older HTTP+SSE
    transport is used instead: GET a stream, POST to the endpoint the stream names, and read the
    replies off the stream on a reader thread."""

    def __init__(self, url, headers=None):
        if not url.startswith(("http://", "https://")): raise MCPError("that is not an http(s) URL")
        self.url = url
        self.headers = {str(k): str(v) for k, v in (headers or {}).items()}
        self.session = ""
        self._id = 0; self._lock = threading.Lock()
        self._legacy = False
        self._q = None; self._stream = None; self._post_url = ""

    def _post(self, url, payload, accept, timeout):
        h = {"Content-Type": "application/json", "Accept": accept, "User-Agent": OUT_UA, **self.headers}
        if self.session: h["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, dict(r.headers), r.read(MCP_MAX_BODY)
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers or {}), e.read(4000)

    def notify(self, method, params):
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        try:
            if self._legacy: self._post(self._post_url, msg, "application/json", MCP_TIMEOUT)
            else: self._post(self.url, msg, "application/json, text/event-stream", MCP_TIMEOUT)
        except Exception: pass          # a notification is best-effort by definition

    def request(self, method, params, timeout=MCP_TIMEOUT):
        with self._lock:
            if self._legacy: return self._legacy_request(method, params, timeout)
            self._id += 1; mid = self._id
            msg = {"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}
            try: status, hdrs, body = self._post(self.url, msg, "application/json, text/event-stream", timeout)
            except Exception as e: raise MCPError("could not reach the server: %s" % e)
            sid = hdrs.get("Mcp-Session-Id") or hdrs.get("mcp-session-id")
            if sid: self.session = sid
            if status in (404, 405, 406, 415):
                self._open_stream()          # not a Streamable HTTP endpoint; try the older transport
                return self._legacy_request(method, params, timeout)
            if status >= 400:
                raise MCPError("the server answered HTTP %d%s" % (status, (": " + _mcp_short(body)) if body else ""))
            reply = _mcp_reply_from(body, hdrs.get("Content-Type", ""), mid)
            if reply is None: raise MCPError("the server sent no reply to %s" % method)
            return reply

    def _open_stream(self):
        """GET the SSE stream, learn where to POST, and read replies on a thread."""
        h = {"Accept": "text/event-stream", "Cache-Control": "no-cache", "User-Agent": OUT_UA, **self.headers}
        try:
            resp = urllib.request.urlopen(urllib.request.Request(self.url, headers=h, method="GET"),
                                          timeout=MCP_TIMEOUT)
        except urllib.error.HTTPError as e:
            raise MCPError("the server refused both POST (HTTP %d) and the SSE stream (HTTP %d)" % (405, e.code))
        except Exception as e:
            raise MCPError("could not open the server's SSE stream: %s" % e)
        self._q = queue.Queue(); ready = threading.Event(); self._stream = resp
        threading.Thread(target=self._read_stream, args=(resp, ready), daemon=True).start()
        if not ready.wait(MCP_TIMEOUT): raise MCPError("the server never said where to POST")
        if not self._post_url: raise MCPError("the server named no POST endpoint")
        self._legacy = True

    def _read_stream(self, resp, ready):
        try:
            for ev, data in _sse_events(resp):
                if ev == "endpoint": self._post_url = urljoin(self.url, data.strip()); ready.set()
                elif data.strip(): self._q.put(data)
        except Exception: pass
        ready.set()

    def _legacy_request(self, method, params, timeout):
        self._id += 1; mid = self._id
        msg = {"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}
        try: status, _h, body = self._post(self._post_url, msg, "application/json", timeout)
        except Exception as e: raise MCPError("could not POST to the server: %s" % e)
        if status >= 400: raise MCPError("the server refused the message (HTTP %d)" % status)
        end = time.time() + timeout
        while True:
            left = end - time.time()
            if left <= 0: raise MCPError("no reply to %s on the SSE stream" % method)
            try: raw = self._q.get(timeout=left)
            except queue.Empty: raise MCPError("no reply to %s on the SSE stream" % method)
            try: m = json.loads(raw)
            except ValueError: continue
            if isinstance(m, dict) and m.get("id") == mid: return m

    def alive(self):
        if not self._legacy: return True
        try: return self._stream is not None and not self._stream.isclosed()
        except Exception: return False

    def why(self): return "the server's SSE stream closed"

    def close(self):
        try:
            if self._stream: self._stream.close()
        except Exception: pass

def _mcp_reply_from(body, ctype, mid):
    """The JSON-RPC message carrying this id, from a body that is either one JSON document (or a
    batch) or an SSE stream carrying several."""
    text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else (body or "")
    msgs = []
    if "text/event-stream" in (ctype or ""):
        for _ev, data in _sse_events(text.splitlines()):
            try: msgs.append(json.loads(data))
            except ValueError: pass
    else:
        try: obj = json.loads(text or "{}")
        except ValueError: raise MCPError("the server sent something that is not JSON: " + _mcp_short(body))
        msgs = obj if isinstance(obj, list) else [obj]
    for m in msgs:
        if isinstance(m, dict) and m.get("id") == mid: return m
    return None

def _mcp_result(res):
    """A `tools/call` result as (text for the model, extra UI events). Images become real images in
    the chat, the same way a generated picture or a screenshot does."""
    parts = []; extras = []
    for c in (res.get("content") or []):
        if not isinstance(c, dict): continue
        kind = c.get("type")
        if kind == "text": parts.append(c.get("text") or "")
        elif kind == "image":
            mt = c.get("mimeType") or "image/png"
            if c.get("data"): extras.append({"type": "image", "png": "data:%s;base64,%s" % (mt, c["data"]),
                                             "note": "from an MCP tool"})
            parts.append("[image returned: %s]" % mt)
        elif kind == "resource":
            r = c.get("resource") or {}
            parts.append(r.get("text") or "[resource: %s]" % (r.get("uri") or ""))
        elif kind == "audio": parts.append("[audio returned]")
        else: parts.append("[%s content]" % kind)
    if res.get("structuredContent") is not None:
        parts.append(json.dumps(res["structuredContent"])[:2000])
    text = "\n".join(p for p in parts if p).strip() or "(the tool returned nothing)"
    if res.get("isError"): text = "(the tool reported an error) " + text
    return text, extras

class MCPClient:
    """One server, connected and initialized. Its tools are listed once and cached, and the
    connection is kept open between turns — re-spawning `npx` for every tool call would be absurd."""

    def __init__(self, entry):
        self.entry = entry
        self.id = entry.get("id")
        self.tools = []          # [{name, description, inputSchema}] as the server listed them
        self.by_safe = {}        # sanitized name -> the server's own name, for reading a call back
        self.info = ""
        target = (entry.get("target") or "").strip()
        if entry.get("kind") == "url" or target.startswith(("http://", "https://")):
            _mcp_url_guard(target)                 # a metadata address is refused before any request
            self.t = _MCPHttp(target, entry.get("headers"))
        else:
            self.t = _MCPStdio(_mcp_arglist(target), entry.get("env"))

    def alive(self): return self.t.alive()
    def why(self): return self.t.why()

    def start(self):
        r = self.t.request("initialize", {"protocolVersion": MCP_PROTOCOL, "capabilities": {},
                                          "clientInfo": {"name": "anzen-bot", "version": "1.0"}})
        if r.get("error"): raise MCPError(_mcp_err(r["error"]))
        info = (r.get("result") or {}).get("serverInfo") or {}
        self.info = " ".join(x for x in (info.get("name"), info.get("version")) if x)
        self.t.notify("notifications/initialized", {})
        self.list_tools()
        return self

    def list_tools(self):
        r = self.t.request("tools/list", {})
        if r.get("error"): raise MCPError(_mcp_err(r["error"]))
        out = []; seen = set()
        for t in (((r.get("result") or {}).get("tools")) or [])[:MCP_MAX_TOOLS]:
            if not isinstance(t, dict): continue
            name = str(t.get("name") or "").strip()
            if not name: continue
            safe = _mcp_safe(name, MCP_TOOL_CAP)
            if safe in seen: continue       # two names that collapse to one cannot both be offered
            seen.add(safe); self.by_safe[safe] = name
            out.append({"name": name, "description": (t.get("description") or "").strip()[:MCP_DESC_MAX],
                        "inputSchema": _mcp_schema(t.get("inputSchema"))})
        self.tools = out
        return out

    def call(self, name, args):
        r = self.t.request("tools/call", {"name": name, "arguments": args if isinstance(args, dict) else {}},
                           timeout=MCP_CALL_TIMEOUT)
        if r.get("error"): raise MCPError(_mcp_err(r["error"]))
        return _mcp_result(r.get("result") or {})

    def close(self):
        try: self.t.close()
        except Exception: pass

_MCP = {}          # server id -> the live client
_MCP_STATUS = {}   # server id -> {ok, tools, info, error, at} — what the panel shows
_MCP_LOCKS = {}
_MCP_REG = threading.Lock()

def mcp_servers(settings):
    """The servers the user switched on and gave a target, in the order they are listed."""
    out = []
    for m in (settings.get("mcp") or []):
        if isinstance(m, dict) and m.get("enabled", True) and (m.get("target") or "").strip(): out.append(m)
    return out

def _mcp_lock(mid):
    with _MCP_REG: return _MCP_LOCKS.setdefault(mid, threading.Lock())

def mcp_status(mid):
    with _MCP_REG: return _MCP_STATUS.get(mid)

def mcp_connect(entry, force=False):
    """The live client for one server, connecting it on first use. Raises MCPError if it will not
    come up; the reason is remembered so the panel can show it rather than hiding the failure."""
    mid = entry.get("id")
    with _mcp_lock(mid):
        c = _MCP.get(mid)
        if c is not None and c.alive() and not force: return c
        if c is not None: c.close()
        try:
            c = MCPClient(entry).start()
        except MCPError as e:
            with _MCP_REG:
                _MCP.pop(mid, None); _MCP_STATUS[mid] = {"ok": False, "tools": 0, "info": "", "error": str(e), "at": time.time()}
            raise
        except Exception as e:
            with _MCP_REG:
                _MCP.pop(mid, None)
                _MCP_STATUS[mid] = {"ok": False, "tools": 0, "info": "", "error": "could not connect: %s" % e, "at": time.time()}
            raise MCPError("could not connect: %s" % e)
        with _MCP_REG:
            _MCP[mid] = c
            _MCP_STATUS[mid] = {"ok": True, "tools": len(c.tools), "info": c.info, "error": "", "at": time.time()}
        return c

def _mcp_ready(entry):
    """Whether to reach for this server this turn. A server that just failed is left alone for a
    while — otherwise a typo in a command would add a spawn timeout to every single message."""
    st = mcp_status(entry.get("id"))
    return not (st and not st.get("ok") and time.time() - st.get("at", 0) < MCP_RETRY_AFTER)

def mcp_schemas(settings):
    """Every enabled server's tools as function-calling schemas, for the turn that is starting.
    Connecting happens here, on the first turn that needs it; after that the client is live and
    this is a lookup."""
    out = []
    for m in mcp_servers(settings):
        if not _mcp_ready(m): continue
        try: c = mcp_connect(m)
        except MCPError: continue
        label = m.get("name") or m.get("id")
        pre = "mcp__" + _mcp_safe(m.get("id"), MCP_SID_CAP) + "__"
        for t in c.tools:
            desc = t["description"] or ("%s, on the %s MCP server" % (t["name"], label))
            out.append({"type": "function", "function": {"name": pre + _mcp_safe(t["name"], MCP_TOOL_CAP),
                        "description": "[MCP · %s] %s" % (label, desc), "parameters": t["inputSchema"]}})
    return out

_MCP_WARM = threading.Event()          # set while a warm pass runs, so it is not started twice
def warm_mcp():
    """Connect every enabled server ahead of the first turn that needs it, so a spawn handshake never
    lands on a turn's critical path — `mcp_schemas` then finds a live client and is a plain lookup.
    Best-effort, idempotent, and never raises: an unreachable server just stays unreachable."""
    if _MCP_WARM.is_set(): return
    def go():
        _MCP_WARM.set()
        try:
            for m in mcp_servers(load_settings()):
                if not _mcp_ready(m): continue
                try: mcp_connect(m)
                except Exception: pass
        finally: _MCP_WARM.clear()
    threading.Thread(target=go, daemon=True).start()

def mcp_exec(name, args):
    """Run one `mcp__<server>__<tool>` call against its live server."""
    settings = load_settings()
    for m in mcp_servers(settings):
        pre = "mcp__" + _mcp_safe(m.get("id"), MCP_SID_CAP) + "__"
        if not name.startswith(pre): continue
        label = m.get("name") or m.get("id"); want = name[len(pre):]
        try: c = mcp_connect(m)
        except MCPError as e: return "(%s is not reachable: %s)" % (label, e), []
        orig = c.by_safe.get(want)
        if not orig: return "(%s has no tool named %s any more — it may have restarted)" % (label, want), []
        try: return c.call(orig, args)
        except MCPError as e: return "(%s: %s)" % (label, e), []
    return "(unknown tool %s)" % name, []

def mcp_forget(mid):
    """Drop a server's connection and its remembered status — after an edit, a disable or a delete,
    so the next turn talks to the server the settings now describe."""
    with _mcp_lock(mid):
        c = _MCP.pop(mid, None)
        if c is not None: c.close()
    with _MCP_REG: _MCP_STATUS.pop(mid, None)

def mcp_shutdown():
    """Let every server go when the app does, so no child process is left running behind it."""
    with _MCP_REG:
        clients = list(_MCP.values()); _MCP.clear()
    for c in clients: c.close()
atexit.register(mcp_shutdown)

def mcp_status_public(settings):
    """What the panel is told about each server: whether it came up and how many tools it offers.
    Never a credential — env vars and headers stay on the server."""
    out = {}
    for m in (settings.get("mcp") or []):
        if not isinstance(m, dict) or not m.get("id"): continue
        st = mcp_status(m["id"]) or {}
        out[m["id"]] = {"checked": bool(st), "ok": bool(st.get("ok")), "tools": st.get("tools", 0),
                        "info": st.get("info", ""), "error": st.get("error", "")}
    return out

def mcp_merge(old, new):
    """Fold a save from the panel onto what is stored. The browser is never given env values or
    header values — they are write-only, like every other credential — so a save that carries none
    must not wipe the ones already there."""
    by = {m.get("id"): m for m in (old or []) if isinstance(m, dict)}
    out = []
    for m in (new or []):
        if not isinstance(m, dict): continue
        prev = by.get(m.get("id")) or {}
        e = dict(m)
        for k in ("env", "headers"):
            if not (isinstance(e.get(k), dict) and e[k]) and isinstance(prev.get(k), dict) and prev[k]:
                e[k] = prev[k]
        out.append(e)
    return out

def mcp_test(entry):
    """Connect one server now, for the panel's Test button. Reports the tools it offers, or why it
    would not come up. A server that has not been saved yet is connected and let go again."""
    mid = entry.get("id"); probe = not mid; key = mid or "_probe"
    try:
        c = mcp_connect(dict(entry, id=key), force=True)
    except MCPError as e:
        if probe: mcp_forget(key)
        return {"ok": False, "error": str(e), "tools": []}
    tools = [t["name"] for t in c.tools][:MCP_MAX_TOOLS]
    info = c.info
    if probe: mcp_forget(key)
    return {"ok": True, "info": info, "tools": tools}

def exec_tool(bid, name, args):
    if name.startswith("mcp__"):
        return mcp_exec(name, args)
    if name in CONNECTOR_BY_TOOL:
        s2 = load_settings(); cid = CONNECTOR_BY_TOOL[name]
        if not connector_connected(s2, cid):
            return f"({cid} is not connected — connect it in Settings > Connected apps)", []
        out = conn_webhook(args, s2) if name == "webhook_post" else conn_api(cid, args, s2)
        return out, []
    if name == "run_shell":
        err = _shell_args_error(args)
        if err: return err, []
        out, rc = run_shell(args["command"], args.get("timeout") or 45); return f"exit {rc}\n{out}", []
    if name == "read_file":
        p = _in_sandbox(args.get("path", ""))
        if not p or not os.path.isfile(p): return "(no such file)", []
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read(12000)[:6000], []
    if name == "write_file":
        p = _in_sandbox(args.get("path", ""))
        if not p: return "(path outside sandbox)", []
        # A path that names a folder — `""` or `"."` resolve to the working directory itself, and any
        # existing folder does too — has no file to write. Say so here: left to `open`, it raises
        # IsADirectoryError and, before the guard in the turn loop, took the whole turn down with it.
        if os.path.isdir(p):
            return "(that is a directory, not a file — give a file name to write, e.g. notes.md)", []
        os.makedirs(os.path.dirname(p), exist_ok=True)
        # What the file held before it is overwritten, so the transcript can show the change as a
        # diff instead of only the new text. Read on the way in, while the old bytes still exist.
        try:
            if os.path.isfile(p): args["before"] = open(p, encoding="utf-8", errors="replace").read()[:20000]
        except OSError: pass
        open(p, "w", encoding="utf-8").write(args.get("content", ""))
        return f"wrote {len(args.get('content',''))} bytes to {args.get('path')}", []
    if name == "list_files":
        p = _in_sandbox(args.get("path", ".") or ".")
        if not p or not os.path.isdir(p): return "(no such directory)", []
        return "\n".join(sorted(os.listdir(p))) or "(empty)", []
    if name == "generate_image":
        prompt = (args.get("prompt") or "").strip()
        if not prompt: return "(no prompt given)", []
        if not (load_settings().get("media") or {}).get("router_image"):
            return ("(router image generation is OFF -- it spends your API tokens. Use the free route: "
                    "browser_open a site, browser_type the prompt, then browser_save the result. Turn the router "
                    "route on in Settings > AI model if you really want it.)"), []
        data_url, used = gen_image(prompt)
        if not data_url: return "(image generation failed: %s)" % used, []
        fn = re.sub(r"[^A-Za-z0-9._-]", "_", (args.get("filename") or "").strip()) or ("image-%d.png" % int(time.time()))
        if not fn.lower().endswith((".png", ".jpg", ".jpeg", ".webp")): fn += ".png"
        p = _in_sandbox(fn)
        if not p: return "(bad filename)", []
        raw = _data_bytes(data_url)
        if raw is None: return "(image generation returned no usable data)", []
        with open(p, "wb") as f: f.write(raw)
        return ("drew %s (%d bytes) with %s" % (fn, os.path.getsize(p), used),
                [{"type": "image", "png": data_url, "note": prompt[:200]}])
    if name.startswith("browser_"):
        # Every browser call a bot makes is made on that bot's behalf, so the screen it leaves behind
        # is attributed to it: one browser serves every chat, and this is what lets the Computer panel
        # answer "is the chat I am looking at the one using the computer?" (see `_computer_scope`).
        # `_owner` rides with the job rather than being written from here, so the browser thread stays
        # the only writer of the attribute it is compared against.
        def bcall(fn, **kw): return BROWSER.call(fn, _owner=bid, **kw)
        if name == "browser_open":   return bcall("open", url=args.get("url", ""),
                                                  routes=getattr(_WORK, "routes", None)), []
        if name == "browser_save":
            sel = args.get("selector") or "img"
            ms = max(5, min(int(args.get("wait_seconds") or 60), 600)) * 1000
            data = bcall("save", timeout=ms // 1000 + 60, selector=sel, wait_ms=ms)
            if not data or data.startswith("(browser"): return data or "(no data)", []
            if data.startswith("{"):
                try: return "(browser_save: %s)" % json.loads(data).get("error", data), []
                except Exception: return data, []
            ext = {"image/jpeg": ".jpg", "image/webp": ".webp", "video/mp4": ".mp4"}.get(data.split(";")[0][5:], ".png")
            fn = re.sub(r"[^A-Za-z0-9._-]", "_", (args.get("filename") or "").strip()) or ("asset-%d%s" % (int(time.time()), ext))
            p = _in_sandbox(fn)
            if not p: return "(bad filename)", []
            raw = _data_bytes(data)
            if raw is None: return "(browser_save returned no usable data)", []
            with open(p, "wb") as f: f.write(raw)
            note = "saved %s (%d bytes) from the page" % (fn, os.path.getsize(p))
            if data.startswith("data:video"): return note + " -- video file, open it from the sandbox", []
            return note, [{"type": "image", "png": data, "note": fn}]
        if name == "browser_read":   return bcall("read"), []
        if name == "browser_click":  return bcall("click", selector=args.get("selector", "")), []
        if name == "browser_type":   return bcall("type", selector=args.get("selector", ""), text=args.get("text", "")), []
        if name == "browser_press":  return bcall("press", key=args.get("key", "Enter")), []
        if name == "browser_back":   return bcall("back"), []
        if name == "browser_eval":   return bcall("eval", expression=args.get("expression", ""),
                                                  max_chars=int(args.get("max_chars") or 4000)), []
        if name == "browser_see":
            png = bcall("shot")
            if not png.startswith("data:"): return png, []
            bot = bot_by_id(load_bots(), bid) or {}
            ans = vision(args.get("question", "Describe this page."), png, fallback=bot.get("model", ""))
            return "vision answer: " + ans, [{"type": "shot", "png": png, "note": ans[:200]}]
    if name == "memory_update":
        note = (args.get("note") or "").strip()[:500]
        if note: mem_append(bid, note)
        return "saved to memory", []
    if name == "use_skill":
        return skill_doc(args.get("skill", ""), args.get("file"))
    return f"(unknown tool {name})", []

def _schema_type_ok(value, typ):
    if typ == "object": return isinstance(value, dict)
    if typ == "array": return isinstance(value, list)
    if typ == "string": return isinstance(value, str)
    if typ == "integer": return isinstance(value, int) and not isinstance(value, bool)
    if typ == "number": return isinstance(value, (int, float)) and not isinstance(value, bool)
    if typ == "boolean": return isinstance(value, bool)
    return True

def _validate_tool_args(name, args, schemas):
    """Fail closed on malformed model tool calls before any side effect runs.

    Providers do not reliably enforce the JSON schema they advertise. Validate the small common
    JSON-schema subset used by built-in, connector, and MCP tools; unsupported schema features stay
    permissive rather than rejecting a valid server-defined argument.
    """
    schema = schemas.get(name)
    if schema is None: return "unknown tool"
    if not isinstance(args, dict): return "arguments must be an object"
    params = schema.get("function", {}).get("parameters") or {}
    typ = params.get("type")
    if typ and not _schema_type_ok(args, typ): return "arguments must be an object"
    props = params.get("properties") or {}
    for key in params.get("required") or []:
        if key not in args: return "missing required argument `%s`" % key
    for key, value in args.items():
        p = props.get(key)
        if not isinstance(p, dict): continue
        pt = p.get("type")
        if pt and not _schema_type_ok(value, pt): return "argument `%s` must be %s" % (key, pt)
        if "enum" in p and value not in p["enum"]:
            # Naming the values is most of the message's worth. "has an invalid value" left the model
            # to guess what it was allowed to pass, and the room is told about every call the app
            # turns away — where "must be one of: dev" reads as an answer and the old text did not.
            # Capped, because a connector's enum can be long and this text travels to both.
            opts = [str(x) for x in p["enum"]]
            shown = ", ".join(opts[:12]) + (" (+%d more)" % (len(opts) - 12) if len(opts) > 12 else "")
            return "argument `%s` must be one of: %s" % (key, shown)
    return ""

def _serial_call(name, args, level):
    """A call that cannot run alongside its siblings in the same step: delegation and finishing change
    the turn's own state (they yield cards and switch the working folder), and a command that needs an
    approval has to put a card up and wait on this thread. One of those makes the whole step serial."""
    if name in ("delegate", "finish"): return True
    if name != "run_shell" or level == "full": return False
    if _shell_args_error(args): return True
    return is_risky(args["command"])

def _stopped_by_us(result, who):
    """The line the room is given when it was this app, and not the command, that stopped the bot.

    Three places answer a call with a parenthesised marker of their own rather than an error the
    command produced: `run_shell` turns away a read of the secret store, the browser guard turns
    away a page that is not on the web, and the loop turns away a call whose arguments never
    arrived. A tool that raised comes back the same shape. Those are the ones the user is told
    about by name — a bot that goes quiet after being refused three times leaves the room with
    nothing to read, and the refusal *is* the account of what happened. A command that merely
    exited non-zero is deliberately not here: that is the bot's own result, the tool row already
    marks it failed and opens on it, and a line for every `grep` that matched nothing would bury
    the ones that matter. `who` names the bot, because a room has several and the centred note
    carries no other attribution.
    """
    s = str(result or "")
    # `run_shell`'s result is prefixed with its own exit code, so the marker is on the line after it.
    m = re.match(r"^exit \d+\n", s)
    if m: s = s[m.end():]
    for mark in ("(refused: ", "(not opened — ", "(the tool ", "(not run: "):
        if s.startswith(mark): return "%s — %s." % (who, s[1:].rstrip(")"))
    return ""

def _exec_parallel(bid, calls):
    """Run one step's tool calls together, each in its own thread, and return their results in the
    order the model asked for them.

    The calls in one step are independent by construction — the model emitted them at once and none
    waits on another — so running them one after another spent N latencies where one would do: three
    files read, or three commands, cost three round-trips of wall-clock. Each worker is handed the
    turn's working folder, because that lives in a thread-local and a fresh thread would otherwise
    fall back to the shared sandbox."""
    wd = work_dir(); base = getattr(_WORK, "base", None)
    def one(call):
        _WORK.dir = wd; _WORK.base = base
        _, name, args = call
        try: return exec_tool(bid, name, args)
        except Exception as e: return ("(the tool %s failed: %s)" % (name, e), [])
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(calls))) as ex:
        return list(ex.map(one, calls))

def wait_approval(sid, ev=None, max_wait=900):
    """Block until the user answers the approval card, or the turn is stopped. Polled rather than a
    single wait so a Stop pressed while the card is up releases the turn instead of leaving it parked
    for the full fifteen minutes. `max_wait` is capped by the caller to the turn's own time budget, so
    a card raised late in a turn cannot park it for another fifteen minutes past that budget.
    `ev` is the waiter the caller already registered before showing the card — see the call site: the
    slot must exist before the card is on screen, or an answer that lands in that gap is read as a
    denial (see `/api/approve`) and the turn then sits on the full deadline for nothing."""
    if ev is None:
        ev = threading.Event(); APPROVAL[sid] = {"event": ev, "allow": False}
    deadline = time.time() + max(1, max_wait)
    while time.time() < deadline:
        if ev.wait(timeout=1) or sid in STOP: break
    return APPROVAL.pop(sid, {}).get("allow", False)

# ---------------------------------------------------------------- agent loop
# How many model calls one turn may make. A step is one call, and one call is often one action — open
# a page, read it, click, read again — so a real browsing job (find something, look at several, act on
# the ones that fit) legitimately wants dozens. 24 was a wall, not a guard: it cut those turns off
# mid-work, which is the one outcome that helps nobody. The cap exists to stop a runaway, so it is set
# well clear of real work and can be raised or lowered per machine in Settings → Models → Context.
# Running out is not fatal either — see `_wrap_up`, which lands the turn on a report of what it did.
DEFAULT_MAX_STEPS = 80
# A turn that runs out of steps with the job unfinished does not die there. Like ZCode's goal
# continuation, it rolls into another round on a fresh budget — the same turn, the same context, a
# nudge the user never sees — so a long job (find something, read several, act on the ones that fit)
# finishes instead of being cut off at the cap. Bounded, so a runaway still lands.
MAX_CONTINUATIONS = 2
# The step cap bounds how many calls a turn makes, and that is the bound the turn is held to. It used
# to carry a wall-clock budget as well — 900s, after which the bot was told to land exactly as if it
# had run out of steps — and that was the wrong thing to enforce. A clock fires on work that is
# *slow*, and slow is what real work is: a page load, a click, a wait for a reply box to appear, a
# model thinking through a long translation. A turn that was still doing exactly what it was asked to
# do got cut off mid-flow for taking a long time, which is the one outcome the step budget exists to
# avoid — and it landed on a report of work that was still going to finish. So there is no default
# clock: the turn runs until its step budget is spent. `max_seconds` is still settable per machine in
# Settings → AI model → Context for anyone who wants a hard cap as well, and 0 — the default — is none.
DEFAULT_TURN_SECONDS = 0
CONTINUE_NOTE = ("You have used all the steps for this round, but the job is not finished. Carry on "
                 "from exactly where you left off — do not repeat what you already did — and call "
                 "`finish` when it is done.")
WRAP_UP = ("You have reached the step limit for this turn. Stop calling tools. Call `finish` now with "
           "a short, concrete report of what you actually found and did — say plainly what is still "
           "unfinished, and do not claim anything you did not get from a tool.")
TIME_UP = ("You have used all the time this turn is allowed. Stop calling tools. Call `finish` now with "
           "a short, concrete report of what you actually found and did — say plainly what is still "
           "unfinished, and do not claim anything you did not get from a tool.")
STOP_NOTE = ("The user asked you to stop. Call `finish` now with a short, concrete report of what you "
             "have done and found so far — say plainly what is still unfinished, and do not claim "
             "anything you did not get from a tool.")
# A step can also come back with thinking but no words and no tool call: a reasoning model that spent
# the whole answer budget on its thinking, so the words — or the call it was about to make — never got
# emitted (`finish_reason` is then usually `length`). That is neither a dead router nor a model with
# nothing to say, so it is not retried from scratch: a fresh attempt would spend the same budget the
# same way. The model is asked to carry straight on instead, which is what ZCode does — up to three
# times, so a model that only ever thinks still lands on a report rather than looping.
OUTPUT_CONTINUE_LIMIT = 3
OUTPUT_CONTINUE_NOTE = ("Your last answer was cut off before it said anything. Carry straight on from "
                        "where it stopped — no apology, no recap of what you were doing — and put the "
                        "work into words, or make the tool call you were about to make.")

def max_steps(settings):
    """How many steps this turn may take: the saved number when there is one, else the default."""
    try:
        n = int((settings.get("context") or {}).get("max_steps") or 0)
    except Exception:
        n = 0
    return n if n > 0 else DEFAULT_MAX_STEPS

def max_seconds(settings):
    """How long this turn may run, in seconds — 0, the default, meaning no wall-clock bound at all.

    The step budget is what bounds a turn; this is only for a machine that wants a hard cap as well.
    See DEFAULT_TURN_SECONDS for why there is no default clock."""
    try:
        n = int((settings.get("context") or {}).get("max_seconds") or 0)
    except Exception:
        n = 0
    return n if n > 0 else DEFAULT_TURN_SECONDS

def _wrap_up(model, messages, tools, said, bid, used=(), budget=0, why="steps", quick=False, notes=()):
    """The turn ran out of room — steps or answers — without finishing. Ask for the report rather
    than discarding the work: one last call, with `finish` the only tool offered, so a bot that has
    been running tools all turn has an obvious way to land. Returns its summary, or the last thing
    it said, or a line built from what it did.

    `quick` skips that call and lands on what the bot already said or did. Stop uses it: a user who
    pressed Stop wants the turn over now, not one more model round-trip before it ends.

    The call it makes is a *single* attempt, whatever the retry policy says, and at most two of them.
    This is the landing call: the turn is out of budget or the model is already known to be dead, so
    the policy's own ~6 minutes of retrying is exactly what must not happen here. The second call is
    for the landing that *worked* and still said nothing — see the loop below.

    Its ceiling is the default one, not a thin one. `MAX_OUTPUT_TOKENS` is generous for the reason
    spelled out there, and it applies here more than anywhere: this is the last call of a turn, and a
    reasoning model that spends its whole ceiling thinking answers with an empty `content` and no
    `finish` call at all. At the old 900 that was the common case on a long turn, which is how a turn
    that had read, run and learned things landed on the bare list of tools it had used.

    `notes` are the times this app stopped the bot (see `_stopped_by_us`). A landing that says only
    "it ran run_shell" reads as a bot that wandered off; the refusal is the answer to "what
    happened?", so it is repeated here — the last line is the one a room actually reads.

    The request is compressed the same way the turn's own calls are. A turn that hit the step limit is
    exactly the long one whose transcript can be over the window, and the uncompressed call would then
    fail — leaving the placeholder instead of the report it was run to get."""
    fin = [t for t in tools if t["function"]["name"] == "finish"]
    if fin and not quick:
        try:
            msgs = fit_messages(messages, budget)[0] if budget else messages
            note = {"time": TIME_UP, "stop": STOP_NOTE}.get(why, WRAP_UP)
            ask = msgs + [{"role": "user", "content": note}]
            # Two calls at most, and each one a single attempt. The second is for the landing that
            # came back as a *success* with nothing in it: a reasoning model that thought and then
            # said nothing is not a failure to `chat` — `_nothing_came` counts thinking as an answer
            # — so the retry policy inside it never fires and one wordless call would be the whole
            # landing. Two `attempts=1` calls is what this costs, not the policy's six minutes, which
            # is the reason it is a loop here and not `attempts=2`. A landing that came back as an
            # error is a different thing and is not asked twice: the model is unreachable, and a
            # second call would only buy another stall budget before the same nothing.
            for _ in range(2):
                msg = chat(model, ask, tools=fin, attempts=1)
                for tc in msg.get("tool_calls") or []:
                    try: args = json.loads(tc["function"]["arguments"] or "{}")
                    except Exception: args = {}
                    if (args.get("summary") or "").strip(): return args["summary"].strip()
                body = (msg.get("content") or "").strip()
                # A router that answers the wrap-up with an error string has reported nothing — fall
                # through to what the bot said and did, rather than handing the error back as the report.
                if body.startswith("[model error"): break
                if body: return body
        except Exception:
            pass
    if said.strip(): return said.strip()
    # Even the report call failed, or the model had nothing to say. Say what it actually did rather
    # than nothing: the tools it ran are the record, and they are worth more than a shrug.
    reason = {"empty": "the model answered with nothing", "stalled": "the model stopped answering mid-step",
              "time": "the turn ran out of time",
              "stop": "the user stopped the turn"}.get(why, "the turn ran out of steps")
    tail = ""
    if notes:
        # One line per distinct problem: a bot that retries the same refused command twelve times has
        # one thing to report, not twelve, and a wall of identical sentences reads as noise.
        uniq = []
        for n in notes:
            if n.rstrip(".") not in [u.rstrip(".") for u in uniq]: uniq.append(n)
        tail = " Stopped by the app: " + "; ".join(u.rstrip(".") for u in uniq) + "."
    if used:
        names = []
        for u in used:
            if u not in names: names.append(u)
        return ("(%s before %s could report. It had run: %s.%s)"
                % (reason, bid or "the bot", ", ".join(names), tail))
    return "(%s before %s could report.%s)" % (reason, bid or "the bot", tail)

def run_agent(sid, bid, task, context, out, bots, settings, depth=0):
    """One bot's turn, run in its own field and written to its own log.

    A room's members share the company's repo but never share a folder, and the detail of what
    each one did lands in that bot's log rather than in the room — which is why a channel stays
    a list of reports.
    """
    prev = getattr(_WORK, "dir", None)
    _WORK.dir = bot_field_dir(bid)
    t0 = time.time()
    try:
        yield from _agent_loop(sid, bid, task, context, out, bots, settings, depth)
    finally:
        # Every exit path — finish, stall, error, wrap-up, exception — is one turn, and this is the
        # only clock that spans all of them: the loop's own `t0` drives the step budget, not this.
        out["took"] = round(time.time() - t0, 1)
        log_turn(sid, bid, task, out, depth)     # still this bot's field, so the log names it
        _WORK.dir = prev

def _agent_loop(sid, bid, task, context, out, bots, settings, depth):
    bot = bot_by_id(bots, bid)
    if not bot:
        # The choke point for every agent run (direct, delegated or in a room): a bot that is no
        # longer in the roster must end the run with a reason, not a TypeError on `bot["model"]`.
        yield {"type": "error", "msg": "that bot is no longer in the roster"}; return
    st = load(sid)
    # The cache figure is the chat's lifetime average, so a measurement saved with the chat seeds the
    # accumulator when this process has not seen the chat yet — a restart, or a chat opened cold.
    if not ctx_has(sid) and st.get("ctx"): ctx_set(sid, st["ctx"])
    # the model picked on the fly (the chip) wins; otherwise the bot's own configured model answers
    model = st.get("model") or bot["model"]
    # Inside a channel the level is the channel's own, read from the room's session rather than from
    # whichever row was clicked: a member's nested chat is the same workspace as the room.
    ch_now, _sc = resolve_session(sid, None, load_channels(), bots)
    level = approval_level(load(ch_now["id"]).get("approval") if ch_now else st.get("approval"),
                           bot.get("approval"), in_channel=bool(ch_now))
    planning = level == "plan"
    # Who this bot may hand work to. Inside a room that is the room's own members and nobody else: the
    # roster is every bot you have, not an invitation into this room, and a lead that reaches past its
    # members puts a name in the channel the user never added — the work then happens off the room's
    # floor. Outside a room there is no floor to keep to, so the roster is the team. This list is the
    # `delegate` tool's own enum, and `_validate_tool_args` fails a call whose `role` is outside it, so
    # the tool the model is shown and the call it is allowed to make cannot disagree.
    peers = [x for x in ([bot_by_id(bots, m) for m in (ch_now.get("members") or [])] if ch_now else bots)
             if x and x["id"] != bot["id"]]
    own_tools = tool_schemas(bot, peers)
    conn_tools = connector_schemas(settings)
    # MCP servers are opt-in per server in Settings > Plugins, so — like Connected apps — their
    # tools are added on top rather than filtered by the bot's own `tools_allow` list. Plan mode
    # still removes them, because PLAN_TOOLS names only read-only built-ins.
    mcp_tools = mcp_schemas(settings)
    tools = own_tools + conn_tools + mcp_tools
    tool_schemas_by_name = {t.get("function", {}).get("name"): t for t in tools}
    if planning:
        # read-only only: in plan mode the bot cannot act, so it cannot act by accident either
        tools = [t for t in tools if t["function"]["name"] in PLAN_TOOLS]
    # The prompt is assembled as (row, text) chunks so the context panel can say what filled the
    # window. Joining the chunks in order rebuilds the exact string this used to concatenate, so the
    # split is measured from the prompt that is actually sent rather than a parallel guess.
    chunks = [("System prompt", bot["instructions"])]
    # Who the bot is, and who it works with, is read live rather than left to whatever the brief
    # happens to say: a brief that names the bot goes stale the moment it is renamed, and then the
    # bot denies its own new name when it is @-mentioned. It is the same `peers` the `delegate` tool
    # is built from — a bot told it works with one team while its tool offers another is how the
    # room came to hand work to somebody it had not added.
    mates = peers
    who = "\n\nYou are " + (bot.get("name") or bid) + "."
    if mates:
        who += (" Your team in this room: " if ch_now else " Your teammates: ") + ", ".join(x["name"] for x in mates) + "."
    chunks.append(("System prompt", who))
    # The operating instructions are placed before the skills on purpose. When a system prompt is too
    # long for the window `fit_messages` cuts it from the end, so whatever sits last is what is lost —
    # and what sits last must never be the working directory, the language rule, or the one line that
    # tells the bot to call `finish`. Those are exactly what a bot cannot work without.
    wd = work_dir()
    chunks.append(("System prompt", ("\n\nYour working directory is " + wd + ". Every shell command and file tool runs there — "
               "do not guess other paths." if wd != SANDBOX else
               "\n\nYour working directory is the shared sandbox: " + SANDBOX + ".") + TOOL_DOC + browser_brief(ch_now) + "\n\n" + LANG))
    if planning: chunks.append(("System prompt", PLAN_BRIEF))
    sk = [s for s in all_skills() if s["id"] in (bot.get("skills") or [])]
    if sk:
        # Only the index travels: the id, the name, and the one line that says what the skill is for.
        # The guidance itself is read on demand with `use_skill`, which is what keeps a 43-skill shelf
        # from costing more context than the job in hand. The ids are shown because the tool is called
        # with one, and a shelf is listed whole or the bot cannot know what it is allowed to reach for.
        lines, used = [], 0
        for s in sk:
            ln = "- " + s["id"] + " — " + s["name"] + ": " + (s.get("desc") or "")
            if used + len(ln) > SKILL_INDEX_CHARS: break
            lines.append(ln); used += len(ln)
        chunks.append(("Skills", "\n\nYour skills. Read one with `use_skill` before you start a job it "
                      "covers — the guidance is not below, only this index:\n" + "\n".join(lines)))
    if bot.get("memory"):
        m = mem_read(bid)
        if m: chunks.append(("Memory & context", "\n\nYour memory notes (yours, kept from past sessions — "
                              "add to them with `memory_update`):\n" + m))
    parts = {}
    for row, t in chunks: parts[row] = parts.get(row, "") + t
    system = "".join(t for _, t in chunks)
    # The tool schemas travel as the API's own `tools` argument and the team context as its own
    # system message, so neither is concatenated into `system` — but both take room in the window,
    # so both are measured as rows rather than left out of the split.
    if own_tools: parts["System tools"] = json.dumps(own_tools)
    if conn_tools: parts["Connected apps"] = json.dumps(conn_tools)
    if mcp_tools: parts["MCP tools"] = json.dumps(mcp_tools)
    if context:
        ctx_text = "\n\nWork already done by the team:\n" + context[-3000:]
        parts["Memory & context"] = parts.get("Memory & context", "") + ctx_text
    messages = [{"role": "system", "content": system}]
    if context: messages.append({"role": "system", "content": "Work already done by the team:\n" + context[-3000:]})
    messages.append({"role": "user", "content": task})
    if bot["id"] != "producer": yield {"type": "status", "state": "working"}
    ctx_cfg = settings.get("context") or {}
    budget = context_budget(model, ctx_cfg.get("limit") or 0)
    compress = ctx_cfg.get("compress", True)
    told = False
    delegated = set(); denied = False; used = []; done = False; said = ""
    # Every time this app stops the bot — a refused command, a denied card, a call that never ran —
    # is remembered here. They are what the user is told about by name: a bot that dies silently
    # after being refused three times leaves the room with nothing to read, and "the turn ran out of
    # steps" is not an account of what happened. See the `notice` events and `_wrap_up`.
    notices = []
    nudges = 0                        # steps re-asked after an answer cut off before it said anything
    steps = max_steps(settings)
    budget_s = max_seconds(settings); t0 = time.time()
    # The turn may run for its step budget plus a bounded number of continuations. At each round
    # boundary the bot is nudged to carry on with a fresh budget — a nudge the user never sees, since
    # the transcript keeps the work and not the machinery — so a job that needs more than one budget's
    # worth of steps finishes rather than dying at the cap.
    total = steps * (1 + MAX_CONTINUATIONS)
    timed_out = False; stopped = False
    for i in range(total):
        # A steer accepted during a step is handed over at the top of the next one, so the last step
        # in the run has nowhere to hand one over: close the window for it, and the caller keeps the
        # message and runs it as the next turn instead of it dying with the deque the turn is about
        # to empty. The exit branches below close the same window for the Stop and for the clock.
        if i + 1 >= total: STEER_CLOSED.add(sid)
        if sid in STOP:                                  # the user pressed Stop: land the turn now
            stopped = True; break
        # A set clock bounds how long the turn may keep *starting* work, not how long any one step may
        # take. A step that has begun runs to its own end: the model call has a stall budget of its own
        # (no new content for MODEL_STALL_SECONDS, which a slow model that is still talking never
        # hits), and retries of its own on top of that — a step that says nothing three times over costs
        # about six minutes, which is the worst case this was sized around (see DEFAULT_MODEL_RETRIES).
        # `run_shell` is allowed the command's own timeout, a browser call its own, and a delegated
        # sub-turn has a budget of its own — so the turn can overrun the clock by one of those, and by
        # the wrap-up call it makes after this to land. That is the design rather than an oversight:
        # cutting a step off in the middle would kill a command or a model mid-answer and lose the work
        # the budget exists to bring home. What this check guarantees is that no *new* step starts past
        # the clock. There is no clock unless a machine set one — see DEFAULT_TURN_SECONDS — so this is
        # normally skipped and the step budget above is the only thing that ends the turn.
        if budget_s and time.time() - t0 > budget_s:
            timed_out = True; break
        if i and i % steps == 0:
            messages.append({"role": "user", "content": CONTINUE_NOTE})
        # The verb for the phase that takes the longest and shows the least: while the model is
        # deciding what to do next it emits nothing, so without this the step card sits frozen on one
        # label for the length of a slow model call and reads as a hang. Emitted every step, cheap,
        # and the client turns it into "Step N · thinking" on the live header. It names the bot because
        # a room runs several of them through one stream: the room shows the phase on the card that
        # says who was handed what, so a teammate on a long step is visibly working rather than absent.
        yield {"type": "status", "state": "thinking", "agent": bid}
        # A steer typed while this turn was already running reaches the bot here — at its next step,
        # not after the turn. It is recorded as a user message, so the transcript keeps it as the
        # thing that turned the bot rather than as something that happened to be typed at it.
        for ev in _apply_steers(sid, messages): yield ev
        msgs = messages
        if compress:
            # Trim old tool output in place first — append-only, so the router's prefix cache stays
            # warm — then fall back to `fit_messages` for a step still too large to stub away.
            trimmed = _compact(messages, budget)
            msgs, dropped = fit_messages(messages, budget)
            if (trimmed or dropped) and not told:
                told = True; yield {"type": "context", "dropped": trimmed or dropped, "limit": budget}
        msg = None
        for kind, val in chat_stream(model, msgs, tools=tools):
            if kind == "delta": yield {"type": "agent_text", "agent": bid, "text": val, "delta": True}
            else: msg = val
        ctx_note(sid, parts, msgs, msg.get("usage"), budget, model)   # measured from the request just sent
        content = (msg["content"] or "").strip()
        # `[model error: …]` is the client's own marker, not the bot speaking — it must not become the
        # last thing the bot is remembered as having said, nor be streamed as if the bot wrote it.
        err = content.startswith("[model error")
        # The endpoint answered, so any run of failures for it is over: the next stall is a fresh one
        # and not the fourth of a run (see note_stall/note_answer).
        if not err and not msg.get("stalled"): note_answer(model)
        # The marker is this app's own words, so it is never streamed or kept as the bot's — but what
        # happened is the one thing the user needs, and it used to be thrown away with the marker: a
        # 429, a wrong model name and a dead router all reached the room as the same "stopped
        # answering". A step that spent every attempt gets the full report — how many tries, and how
        # long — because that is what makes it actionable; a step that failed without being retried
        # gets the bare reason. Both count toward the run that names the endpoint (see
        # `_model_failure_note`), which is why this is one branch and not two.
        if err or msg.get("stalled"):
            reason = content.split(":", 1)[-1].strip().rstrip("]")[:200]
            retried = msg.get("stalled") or int(msg.get("attempts") or 1) > 1
            note = (_model_failure_note(bot, model, msg, reason) if retried
                    else "%s — the model call failed: %s" % (bot["name"], reason))
            if note not in notices:
                notices.append(note); yield {"type": "notice", "level": "warn", "text": note}
        if content and not err: said = content            # the last thing it actually put into words
        tcs = msg["tool_calls"]
        if content and not err and bot["id"] != "producer": yield {"type": "agent_text", "agent": bid, "text": content}
        if not tcs:
            # Thinking but no words and no call: the answer was cut off before it said anything, so the
            # model is asked to carry on rather than the step being written off as a failure. Retrying
            # from scratch would spend the same budget the same way, and reporting it would tell the user
            # the router was dead when it was working. Bounded by OUTPUT_CONTINUE_LIMIT, after which the
            # turn falls through to the report below as it always did.
            # `and not content` is the whole point: a reasoning model sets `reasoning` on EVERY answer,
            # so without it a finished answer was nudged as though it had said nothing — three extra
            # model calls per turn, each re-answering from scratch, and the user waited for the last
            # one. "thanks, that's all" cost four calls and 14s where it needed one and 2.5s.
            if (not err and not msg.get("stalled") and nudges < OUTPUT_CONTINUE_LIMIT
                    and ((msg.get("reasoning") and not content) or msg.get("finish") == "length")):
                nudges += 1
                messages.append({"role": "user", "content": OUTPUT_CONTINUE_NOTE})
                continue
            if content and not err:
                out["text"] = content
            else:
                # Either the model said nothing, or every attempt failed, or the router went quiet — all
                # three are the turn ending with no answer at all, which used to end on a blank and look
                # like the bot had simply quit. Land on what it did instead, and say why. No report call:
                # the model has just failed to answer, and on a stall it is still unreachable, so asking
                # again would only hang for another stall budget before landing on the same reason line.
                out["stop"] = "stalled" if msg.get("stalled") else "empty"
                out["text"] = _wrap_up(model, messages, tools, said, bid, used, budget, why=out["stop"], quick=True, notes=notices)
            # The bot is ready to stop, but a task typed a moment ago still has to reach it: the turn
            # only closes once the user has nothing more to say to it, so a steer that landed while
            # the last word was being written turns the bot instead of dying with the turn. Past this
            # point there is no step left to hand a steer to, so the endpoint stops saying there is —
            # a steer taken now would be written to nobody and dropped when the turn's deque is popped.
            STEER_CLOSED.add(sid)
            tail = _apply_steers(sid, messages)
            if tail:
                STEER_CLOSED.discard(sid)     # it is carrying on after all: steering is open again
                for ev in tail: yield ev
                continue
            done = True; break
        if bot["id"] == "producer" and content and not err and not out.get("plan"):
            # The lead saying what it is about to do, in its own words — the one plan card a turn
            # writes itself. `agent` rides along so the card can be headed with whose plan it is.
            out["plan"] = content; yield {"type": "plan", "agent": bid, "text": content}
        messages.append({"role": "assistant", "content": msg["content"], "tool_calls": tcs})
        # The tools are about to run: name the phase so the card reads "Working…" while a command
        # or a page read is in flight, rather than staying on "Thinking…" through both.
        yield {"type": "status", "state": "working", "agent": bid}
        # Every call in this step, parsed once, so the decision to run them together can be made up
        # front rather than discovered mid-loop.
        calls = []
        for tc in tcs:
            name = tc["function"]["name"]
            try: args = json.loads(tc["function"]["arguments"] or "{}")
            except Exception: args = None
            if not isinstance(args, dict):
                # A stream that stops mid-arguments leaves the JSON truncated, and this used to hand
                # the tool `{}`: `write_file` then wrote an empty file to a path it had never been
                # given and the turn carried on as though it had worked. A call whose arguments cannot
                # be read is not run at all — the model is told, in the turn, and can say what it
                # meant. The reply is as much the point as the refusal: an assistant tool_call with no
                # matching tool message makes the next request invalid, so a skipped call still answers.
                yield {"type": "tool", "id": tc.get("id"), "agent": bid, "name": name, "args": {},
                       "out": "(not run: the arguments arrived truncated)"}
                # A call this app turned away is an app-caused stop like any other, so the room is told
                # rather than left with a step row that quietly did nothing (see `_stopped_by_us`).
                # The notice says what the app did about it, because "the arguments arrived truncated"
                # on its own reads as the end of the turn — it is not: the bot is asked to make the
                # call again, and that second attempt is the retry.
                note = _stopped_by_us("(not run: the arguments arrived truncated — it was asked to make"
                                      " the call again)", bot["name"])
                if note and note not in notices:
                    notices.append(note); yield {"type": "notice", "level": "warn", "text": note}
                messages.append({"role": "tool", "tool_call_id": tc.get("id"), "name": name,
                                 "content": ("(your call to `%s` arrived with truncated arguments and was not run"
                                             " — call it again with the whole argument object.)" % name)})
                continue
            arg_error = _validate_tool_args(name, args, tool_schemas_by_name)
            if arg_error:
                msg = "(not run: %s)" % arg_error
                yield {"type": "tool", "id": tc.get("id"), "agent": bid, "name": name,
                       "args": args, "out": msg}
                # Same again: a call refused for its shape is the app stopping the bot, and it used to
                # be visible only in the folded step row — the one place a reader does not look.
                note = _stopped_by_us(msg, bot["name"])
                if note and note not in notices:
                    notices.append(note); yield {"type": "notice", "level": "warn", "text": note}
                messages.append({"role": "tool", "tool_call_id": tc.get("id"), "name": name,
                                 "content": msg})
                continue
            calls.append((tc, name, args))
        # Independent calls in one step run together — but only when none of them must run here: a
        # delegation, a finish, or a command awaiting approval all yield cards or change the turn's
        # own state, and any one of those makes the whole step serial.
        if len(calls) > 1 and not any(_serial_call(n, a, level) for _, n, a in calls):
            for tc, name, args in calls:
                yield {"type": "tool", "id": tc.get("id"), "agent": bid, "name": name, "args": args, "out": None}
            for (tc, name, args), (result, extra) in zip(calls, _exec_parallel(bid, calls)):
                used.append(name)
                for ev in extra: yield {**ev, "agent": bid}
                yield {"type": "tool", "id": tc.get("id"), "agent": bid, "name": name, "args": args, "out": result[:1800]}
                note = _stopped_by_us(result, bot["name"])
                if note and note not in notices:
                    notices.append(note); yield {"type": "notice", "level": "warn", "text": note}
                messages.append({"role": "tool", "tool_call_id": tc["id"], "name": name, "content": result[:6000]})
        else:
            for ci, (tc, name, args) in enumerate(calls):
                if name == "delegate":
                    sub = args.get("role", ""); subtask = args.get("task", "")
                    sb = bot_by_id(bots, sub)
                    if not sb or sub == bid: result = "(unknown teammate)"
                    elif depth >= 3: result = "(delegation is too deep — call finish now.)"
                    elif sub in delegated: result = f"({sb['name']} already worked on this turn — call finish now.)"
                    elif len(delegated) >= 3: result = "(delegation limit reached — call finish now.)"
                    else:
                        delegated.add(sub)
                        used.append("delegate:" + sub)
                        yield {"type": "agent", "id": sub, "name": sb["name"], "state": "start", "task": subtask}
                        sout = {}
                        yield from run_agent(sid, sub, subtask, context + "\n\nPlan: " + str(task), sout, bots, settings, depth + 1)
                        yield {"type": "agent", "id": sub, "name": sb["name"], "state": "done"}
                        result = sb["name"] + " reported:\n" + (sout.get("text") or "(no report)")
                        rep = (sout.get("text") or "").strip()
                        # What the teammate found is the room's business, not a note passed privately to
                        # the lead: without this the channel showed the delegation and then nothing until
                        # the lead's own summary, so the work in between happened in silence. It is said
                        # as the teammate's own words, which is what `agent_text` is — and only when its
                        # last words were not already those, so a report the bot streamed as it finished
                        # is not said twice. `_channel_turn` records it when this turn *is* the room's;
                        # a chat with one bot inside a company (or outside one) has no such recorder, so
                        # the line is written here — the same transcript the bot's own report lands in.
                        if rep and rep != (sout.get("said") or "").strip():
                            yield {"type": "agent_text", "agent": sub, "text": rep}
                        if not (ch_now and ch_now.get("id") == sid):
                            st2 = load(sid); st2["messages"].append({"role": "assistant", "who": sb["name"], "content": sout.get("text", ""), "ts": time.time()}); save(sid, st2)
                elif name == "finish":
                    # A bot that calls `finish` with nothing to say still has the last thing it said,
                    # and a blank report is the silent stop in another costume — so fall back rather
                    # than hand the room an empty line.
                    out["text"] = args.get("summary", "") or content or said; done = True
                    # `finish` ends the turn, but a steer that lands while it is being written
                    # continues it — and an assistant tool_call with no matching tool reply makes
                    # the next request invalid. So answer this call and any sibling it skipped.
                    for tc2, name2, _ in calls[ci:]:
                        messages.append({"role": "tool", "tool_call_id": tc2["id"], "name": name2,
                                         "content": "(not run: the bot finished)"})
                    break
                else:
                    cmd = args.get("command", "") if name == "run_shell" else ""
                    gate = level not in ("full",)                     # Full access never asks
                    # `not shell_refused(cmd)`: a command this app turns away outright is not a
                    # question, so no card. The answer cannot change the outcome, a card that
                    # approves nothing is one the user learns to click past, and a bot that keeps
                    # reaching for the store would otherwise park the turn on it for the rest of the
                    # budget — which is what a "hung" bot was. The refusal is announced below.
                    if name == "run_shell" and gate and is_risky(cmd) and not shell_refused(cmd):
                        if denied:
                            note = "Refused a second command from %s: one was already denied this turn." % bot["name"]
                            if note not in notices:
                                notices.append(note); yield {"type": "notice", "level": "warn", "text": note}
                            messages.append({"role":"tool","tool_call_id":tc["id"],"name":name,
                              "content":"(blocked: a command was already denied this turn — call finish now.)"})
                            continue
                        # Register the waiter *before* the card is on screen: an answer that lands in
                        # the gap between the yield and the wait would otherwise find no slot and be
                        # read as a denial (see `/api/approve`), stalling the turn on the full deadline.
                        ev = threading.Event(); APPROVAL[sid] = {"event": ev, "allow": False}
                        try:
                            yield {"type": "approval", "agent": bid, "cmd": cmd}
                            yield {"type": "status", "state": "approval"}
                            st2 = load(sid); st2["pending"] = {"cmd": cmd, "agent": bid}; save(sid, st2)
                            # The card gets at least 30s of its own: near the end of a long turn the
                            # remaining budget is ~0, and a one-second deadline is not a question, it is
                            # an auto-deny that flashes a card the user never had a chance to answer.
                            ok = wait_approval(sid, ev, max_wait=max(30, budget_s - (time.time() - t0)))
                        finally:
                            # `wait_approval` pops the slot on the normal path; this covers the one gap
                            # that does not reach it — a save that throws between registering the waiter
                            # and the wait, which would otherwise leave a slot nothing ever pops.
                            APPROVAL.pop(sid, None)
                        st2 = load(sid); st2["pending"] = None; save(sid, st2)
                        if not ok:
                            # Stop releases the card as well, and reading that as a denial told the room
                            # the user had refused a command they were never shown an answer to. They are
                            # two different events and the room is told which one happened.
                            if sid in STOP:
                                note = "%s was stopped while a command waited for your answer." % bot["name"]
                                reply = "(the user stopped the turn while this waited to be approved.)"
                            else:
                                denied = True
                                note = "%s was denied that command and told to stop running them." % bot["name"]
                                reply = ("(user DENIED. Stop running commands — call finish now and explain "
                                         "you were blocked.)")
                            if note not in notices:
                                notices.append(note); yield {"type": "notice", "level": "warn", "text": note}
                            messages.append({"role":"tool","tool_call_id":tc["id"],"name":name,"content":reply})
                            yield {"type": "status", "state": "working"}; continue
                    # The call's own id travels with both events, so the transcript can draw one step
                    # row that fills in when the tool returns — rather than a second row for the call.
                    yield {"type": "tool", "id": tc.get("id"), "agent": bid, "name": name, "args": args, "out": None}
                    # A tool that raises must not take the turn with it. Anything a tool does — a path
                    # that names a folder, a provider that fell over, a browser that died mid-call —
                    # comes back as that tool's own output, so the bot reads it and tries something
                    # else. That is the one thing the raw exception never allowed: it ended the turn.
                    try:
                        result, extra = exec_tool(bid, name, args)
                    except Exception as e:
                        result, extra = "(the tool %s failed: %s)" % (name, e), []
                    used.append(name)
                    note = _stopped_by_us(result, bot["name"])
                    if note and note not in notices:
                        notices.append(note); yield {"type": "notice", "level": "warn", "text": note}
                    for ev in extra: yield {**ev, "agent": bid}   # a screenshot belongs to its bot
                    yield {"type": "tool", "id": tc.get("id"), "agent": bid, "name": name, "args": args, "out": result[:1800]}
                messages.append({"role": "tool", "tool_call_id": tc["id"], "name": name, "content": result[:6000]})
        if done:
            # `finish` ends the turn, so a steer that arrived while the bot was calling it is the same
            # case as the one above: hand it over and keep going rather than close on top of it.
            STEER_CLOSED.add(sid)
            tail = _apply_steers(sid, messages)
            if not tail: break
            STEER_CLOSED.discard(sid)
            for ev in tail: yield ev
            done = False
    if stopped:
        STEER_CLOSED.add(sid)
        out["stop"] = "stop"
        out["text"] = _wrap_up(model, messages, tools, said, bid, used, budget, why="stop", quick=True, notes=notices)
    elif timed_out:
        # Out of wall-clock with work still in hand. Same landing as the step cap: one last call with
        # `finish` the only tool, so the turn reports what it found instead of being cut off silently.
        STEER_CLOSED.add(sid)
        out["stop"] = "time"
        out["text"] = _wrap_up(model, messages, tools, said, bid, used, budget, why="time", notes=notices)
    elif not done:
        # Every round spent with work still in hand — the loop ran out of steps without the bot
        # landing the turn. `done` is the other way out, and it must not come through here: `finish`
        # (or a plain answer with no tool call) has already set `out["text"]`, so running the wrap-up
        # would overwrite the bot's own report with a second model call and label a finished turn
        # "max_steps". Ending here used to mean throwing all of it away and answering
        # "(stopped: too many steps)", which is the one outcome that helps nobody: the bot had
        # already read, run and learned things. Instead it gets one last call with `finish` as the
        # only tool on offer, so the turn lands on a report of what it really found — and if even
        # that fails, on the last thing it managed to say.
        STEER_CLOSED.add(sid)                 # the step budget is spent: no step is left to steer into
        out["stop"] = "max_steps"
        out["text"] = _wrap_up(model, messages, tools, said, bid, used, budget, notes=notices)
    # Whatever is still in the deque here was taken while a step was running and has no step left to be
    # handed to — Stop, the clock or the budget ended the turn under it. It is handed back as *not*
    # taken rather than popped with the deque on the way out: the client's row clears and the message
    # runs as the next turn, instead of a click that said "handing over…" over a turn that is over and
    # a message that reached nobody. It cannot be handed over twice — a drain empties the deque, and
    # the event is what takes the row off the client's queue.
    for ev in _release_steers(sid): yield ev
    # A plan-only turn ends with the plan itself, so the UI can offer to run it. Emitted as the
    # turn's own event (not the lead's mid-turn `plan`) because here the plan IS the whole output.
    if planning and out.get("text"):
        yield {"type": "plan", "agent": bid, "text": out["text"], "mode": "plan"}
    out["used"] = used                       # what this turn touched, for the bot's own work log
    # The last thing it put into words, so a caller handing this bot's report on can tell whether those
    # words already went out as `agent_text` and say them once rather than twice.
    out["said"] = said
    # Self-learning is deferred to the caller, which runs it *after* the report is emitted: the answer
    # is what the user is waiting for, and the notes are a background nicety that must not add a model
    # round-trip to the critical path of every substantive turn. See `_learn`.

# ---------------------------------------------------------------- turns
def _clean_quote(q):
    """A quote arrives from the browser, so only the two fields that mean anything are read off it —
    a who and a text, both strings, both bounded — and an empty quote is no quote at all."""
    if not isinstance(q, dict): return None
    who = str(q.get("who") or "")[:120]
    text = str(q.get("text") or "")[:2000]
    return {"who": who, "text": text} if text.strip() else None

def _user_message(text, quote, fwd, who=None):
    """The transcript's own record of what you sent: the text, plus the quote you attached to it and
    the forward mark, so reopening the chat draws back exactly what you sent rather than a plain
    line. Kept in the same shape a bot's message uses, so nothing else has to know the difference.
    `who` names a message you did not type — a routine's prompt — so it is not drawn as yours."""
    m = {"role": "user", "content": text, "ts": time.time()}
    if who: m["who"] = who
    if quote: m["quote"] = {"who": quote.get("who") or "", "text": (quote.get("text") or "")[:1000]}
    if fwd: m["fwd"] = True
    return m

def _task_with_quote(text, quote):
    """The task as the bot reads it. A reply carries the message it answers, because the bot never
    sees the transcript — without this, "do this" points at nothing."""
    if not quote: return text
    q = (quote.get("text") or "").strip()
    if not q: return text
    who = (quote.get("who") or "").strip()
    return ("Replying to " + (who + ": " if who else "") + '"'
            + (q if len(q) <= 600 else q[:600] + "…") + '"\n\n' + (text or ""))

def _on_it(names):
    """Who a turn is going to, as a sentence rather than a label.

    A room's card answers "who is handling this", which is the question you have while you wait — so
    it is worded as the answer to that question, and the UI heads it "Who's on it". It is not a plan
    and is never called one: nothing has been planned at that point, and a card headed PLAN over a
    routing notice is what made every message look like somebody else's plan."""
    names = [n for n in names if n]
    if not names: return ""
    if len(names) == 1: return names[0] + " is on it."
    return ", ".join(names[:-1]) + " and " + names[-1] + " are on it."

def _run_turn(sid, text, bots, settings, channel=None, solo=None, quote=None, fwd=False, who=None):
    if channel is None and solo is None:
        # A scoped id that resolves to neither a room nor a bot — a member's chat under a room that has
        # since been deleted, or a bot taken out of it. Returning with nothing opened a stream and closed
        # it again: the client's own message blinked out in the redraw and nothing said why, which is the
        # "hung with no explanation" complaint in its smallest form. Say what happened instead.
        yield {"type": "error", "msg": "This chat's room no longer exists — open it again from the sidebar."}
        return
    learn = []                                                # (agent, job) pairs to run off the lock
    # A direct caller starting a fresh turn is an explicit recreation after deletion. An already-running
    # turn never reaches this branch: it owns the lock and its epoch, so its late writes remain refused.
    if sid in _DELETED_SESSIONS and sid not in STEER:
        new_session(sid, bot=solo or ((channel or {}).get("lead") if channel else sid))
    # One turn per chat at a time. Two overlapping turns on the same session would clobber
    # each other's APPROVAL waiter and lose messages in the load -> mutate -> save window.
    with _session_lock(sid):
        prior_epoch = getattr(_SESSION_CTX, "epoch", None)
        _SESSION_CTX.epoch = _SESSION_EPOCH.get(sid, 0)
        STEER[sid] = collections.deque()      # alive for exactly this turn: it is what a steer lands in
        STEER_CLOSED.discard(sid)
        try:
            yield from _run_turn_inner(sid, text, bots, settings, channel, solo, quote, fwd, learn, who)
        finally:
            STEER.pop(sid, None)              # a steer that arrived too late is not stranded here
            STEER_CLOSED.discard(sid)
            STOP.discard(sid)                 # the turn is over: a later Stop is a no-op, not a stale flag
            if prior_epoch is None: del _SESSION_CTX.epoch
            else: _SESSION_CTX.epoch = prior_epoch
    # Self-learning is a separate model call per member, and the report is already on screen — so it
    # runs off the response entirely, in a daemon thread. Yielded here, it kept the turn's stream open
    # (the client only frees the composer when the stream closes), so the user waited on a reflect
    # call per member before they could type again: the exact stall the tool-heavy turns hit hardest.
    # Each note is announced on the watch stream instead, so the card still appears; a job that fails
    # is dropped, because reflection is a bonus and never a fault.
    if learn: threading.Thread(target=_run_learn, args=(sid, learn), daemon=True).start()

def _run_learn(sid, learn):
    for agent, job in learn:
        try: notes = job()
        except Exception: notes = []
        if notes: _fanout({"type": "learned", "agent": agent, "notes": notes, "session": sid})

def _recent_ctx(sid, n=10, cap=600):
    """The last few things said in this chat, as the context a 1:1 turn is handed.

    A 1:1 turn used to be given no context at all, so a bot could not see the message it was
    answering next to: the user had to repeat an instruction the bot had already been given, and every
    repetition was a whole wasted turn of the kind that makes a task feel slow. A room already passes
    this (see `_channel_turn`); a 1:1 chat now does too. The current task is left out — it travels as
    the task itself — and the tool records are skipped, because they are this app's own machinery
    rather than something a model is handed back."""
    msgs = [m for m in load(sid)["messages"] if m.get("role") in ("user", "assistant")][:-1]
    return "\n".join(f"{m.get('who') or m['role']}: {str(m.get('content') or '')[:cap]}" for m in msgs[-n:])

def _run_turn_inner(sid, text, bots, settings, channel=None, solo=None, quote=None, fwd=False, learn=None, who=None):
    set_work_dir(channel.get("folder") if channel else None)   # per-turn: a room's bots work in that room's repo
    # The room's browser accounts ride with the turn, so a `browser_open` inside it routes through
    # this room's list without the bot being told an account name. None = use the machine-wide list.
    _WORK.routes = _room_routes(channel)
    ctx_saved = False        # set once a save has already carried the ctx chip, so `finally` need not repeat it
    try:
        st = load(sid)
        if text: st["messages"].append(_user_message(text, quote, fwd, who)); save(sid, st)
        task = _task_with_quote(text, quote)      # what the bot is handed: the reply, with its quote
        yield {"type": "status", "state": "thinking"}
        wd = work_dir()
        # A 1:1 chat runs in that bot's own field; a room runs in the company's repo, and each
        # member works in its own folder inside it. The card names the folder you would look in.
        if solo: wd = bot_field_dir(solo)
        if wd != SANDBOX:
            yield {"type": "workdir", "path": wd, "channel": channel.get("name", "") if channel else ""}
        if channel and solo is None:
            # Mentions are matched on what you typed, not on the quote: a quoted report that happens
            # to name a teammate is a reference, not an address, and must not re-route the room.
            yield from _channel_turn(sid, task, channel, bots, settings, raw=text, jobs=learn)
        else:
            bot = bot_by_id(bots, solo)
            if not bot:
                # A stale client (or a hand-made id) can name a bot that was deleted; without this the
                # turn died as a TypeError on `bot["name"]` instead of saying what happened.
                yield {"type": "error", "msg": "This chat's bot no longer exists — open a chat from the sidebar."}
                return
            out = {}; seen_plan = False; engaged = []; ran = []
            for ev in run_agent(sid, solo, task, _recent_ctx(sid), out, bots, settings):
                if ev.get("type") == "plan": seen_plan = True
                elif ev.get("type") == "agent" and ev.get("state") == "start": engaged.append(ev.get("name"))
                # A tool call arrives twice — once as it starts, once with its output — and only the
                # second is the record. It is kept in the transcript so the work a turn did is still
                # there when the chat is reopened, rather than being a live-only card that vanishes
                # on the next switch. This chat's transcript is never read back by a model (a 1:1 turn
                # is handed no context), so what lands here cannot change what a bot does next.
                if ev.get("type") == "tool" and ev.get("out") is not None:
                    ran.append({"role": "tool", "agent": ev.get("agent") or solo, "name": ev.get("name"),
                                "args": ev.get("args") or {}, "out": ev.get("out") or ""})
                # A stop this app caused — a refusal, a denial, a stalled model — is the account of what
                # happened, and it was only ever live: the card was drawn while the turn ran and the
                # redraw at the end wiped it, so a chat reopened showed the work and none of the reasons.
                # Kept as a `notice` row, which the redraw draws exactly as the live card drew it.
                if ev.get("type") == "notice" and (ev.get("text") or "").strip():
                    ran.append({"role": "notice", "content": ev["text"], "ts": time.time()})
                yield ev
            # The lead delegated, so say who is doing it. A lead that simply answered has nothing to
            # hand off and gets no card — the old "Plan: answer directly." was a plan of nothing, and
            # it is what put a PLAN card on every single reply.
            if solo == "producer" and not seen_plan and engaged:
                yield {"type": "plan", "kind": "route", "text": _on_it(engaged)}
            final = out.get("text") or ""
            st = load(sid); st["messages"].extend(ran)
            st["messages"].append({"role":"assistant","who": bot_by_id(bots, solo)["name"], "content": final, "ts": time.time(), "took": out.get("took")})
            rec = ctx_get(sid)                           # fold the ctx chip into this same save: one write
            if rec: st["ctx"] = rec; ctx_saved = True     # per turn, not two, on the common 1:1 path
            save(sid, st)
            yield {"type": "final", "text": final}
            # The report is out. The notes are a separate model call, handed back to `_run_turn` to run
            # once this chat's lock is released (see there), rather than before the turn can close.
            learn.append((solo, lambda: _learn(bot_by_id(bots, solo), solo, task, out)))
        rec = ctx_get(sid)
        if rec: yield {"type": "ctx", "ctx": rec}            # the chip updates on the turn that filled it
        yield {"type": "status", "state": "finished"}; yield {"type": "done"}
    except Exception as e:
        # A turn that raised used to leave the user's message with no reply anywhere they could ever see
        # it: the live client got a red card, and the moment the page was reloaded the failure was gone —
        # the transcript kept the question and nothing else. One row says what happened, in the same place
        # and shape as every other stop, so a reload still explains the silence.
        try:
            st = load(sid)
            st["messages"].append({"role": "notice",
                                   "content": "The turn failed: %s" % e, "ts": time.time()})
            save(sid, st)
        except Exception: pass
        raise
    finally:
        rec = ctx_get(sid)
        if rec and not ctx_saved:                            # keep the panel across a reload
            st = load(sid); st["ctx"] = rec; save(sid, st)
        _WORK.dir = None                                     # the next turn in this thread starts clean
        _WORK.base = None

def mentioned_members(text, members, bots):
    """The member ids `text` names with @, in member order. A mention is @name or @id, matched
    without case so a typed @Producer finds the producer, and it must not run into a longer word,
    so @pro does not match @producer. A name may hold spaces (Chief of Staff)."""
    low = text.lower()
    hits = []
    for m in members:
        b = bot_by_id(bots, m)
        if not b:
            continue
        toks = {t.strip().lower() for t in (m, b.get("name") or "")} - {""}
        hit = False
        for tok in toks:
            needle = "@" + tok
            i = low.find(needle)
            while i != -1 and not hit:
                j = i + len(needle)
                if j >= len(low) or not (low[j].isalnum() or low[j] in "_-"):
                    hit = True
                else:
                    i = low.find(needle, i + 1)
        if hit:
            hits.append(m)
    return hits

def _channel_turn(sid, text, channel, bots, settings, raw=None, jobs=None):
    """Channel with a responder mode: lead | auto | everyone. `raw` is what the user typed, without
    any quote attached — the text mentions are matched against. `jobs` collects the members' deferred
    reflection, which `_run_turn` runs once this room's lock is released."""
    members = [b for b in channel["members"] if bot_by_id(bots, b)]
    mode = channel.get("mode", "lead")
    # A lead that was deleted — or a room whose members are all gone — must not name a bot that is not
    # there: `bot_by_id(...)["name"]` on a dead id is a TypeError that surfaced as an error event.
    lead = channel.get("lead")
    if not bot_by_id(bots, lead): lead = members[0] if members else None
    typed = text if raw is None else raw
    targets = []
    if mode == "everyone": targets = members
    elif mode == "auto":
        # A mention is a decision the user already made, so it is spent without a model call — the
        # router only picks when nobody was named. The pick itself is a fast model call, and a room
        # message should not sit through it when the message already says who it is for.
        targets = mentioned_members(typed, members, bots)
        dm = settings.get("decision", {})
        if not targets and dm.get("enabled") and dm.get("jobs", {}).get("rooms"):
            picked = _decide_room(channel, bots, text)
            targets = [picked] if picked else [lead]
        if not targets: targets = [lead]
    else:
        # lead mode: mention wins, else the lead
        targets = mentioned_members(typed, members, bots)
        if not targets: targets = [lead]
    targets = [t for t in targets if bot_by_id(bots, t)]     # a deleted lead or member names nobody
    engaged = []; lead_text = ""; did = []
    # A hand-off, not a plan: who this message is going to. The UI heads it "Who's on it", so a room
    # message never opens with a plan card for a plan nobody wrote. It is kept in the transcript too:
    # the live card is gone the moment the turn ends and the record is redrawn, and "who was on it" is
    # the one thing you want back when you reopen the room.
    route = _on_it(bot_by_id(bots, m)["name"] for m in targets)
    if route:
        st = load(sid)
        st["messages"].append({"role": "route", "who": "Room", "content": route, "ts": time.time()})
        save(sid, st)
    yield {"type": "plan", "kind": "route", "text": route}
    known = {s for s, _ in _sessions_snapshot()}
    def chat_of(bid):
        """A member's work belongs to its chat inside this room, where the sidebar already lists it.
        The fallback is for a bot with no row under this room — a delegation is refused unless the
        bot is a member, so nothing on this path should reach it, but an event naming one must still
        land somewhere you can open rather than on a scoped chat that does not exist."""
        nid = (sid + "/" + bid) if bid in members else bid
        if nid not in known:               # the bot's chat, made on demand
            known.add(nid)
            b = bot_by_id(bots, bid) or {}
            new_session(nid, bot=bid, title=b.get("name") or bid)
        return nid
    # What the room heard, in the order it heard it, written to the room's record one save per member
    # rather than one per line — a turn says a lot, and every save rewrites the whole store.
    room_said = []
    # ...and each thing said, once. A bot's words reach the room from two places: every step that puts
    # something into words (the `agent_text` above), and the closing report at the end. A lead that
    # restates its line on the way to a tool call and then again as its report said one thing, and the
    # room must show it once — so a repeat of the *last* line that speaker said is dropped. Keyed on the
    # last line rather than on `out["said"]` alone, because a model repeating itself across steps
    # slipped past that comparison, and a bot whose steps emit no `agent_text` had its report dropped
    # by it instead — the same words landing twice in one room, and nowhere at all in the other.
    heard = {}
    def room_says(who, text, took=None):
        t = (text or "").strip()
        if t and heard.get(who) != t:
            heard[who] = t
            row = {"role": "assistant", "who": who, "content": text, "ts": time.time()}
            if took is not None: row["took"] = took
            room_said.append(row)
        elif took is not None:
            # The report repeated the line already said, so no new row lands — but that row is this
            # turn's assistant message and the duration still belongs on it.
            for row in reversed(room_said):
                if row.get("who") == who: row["took"] = took; break
    for m in targets:
        yield {"type": "agent", "id": m, "name": bot_by_id(bots, m)["name"], "state": "start"}
        engaged.append(bot_by_id(bots, m)["name"])
        out = {}; work = {}
        # A report is the thing a member most needs to see, and a 200-char cut turned one into a
        # fragment the next member could not act on — so the tail is wider and each line keeps more.
        ctx = "\n".join(f"{x.get('who') or x['role']}: {str(x.get('content') or '')[:600]}"
                        for x in load(sid)["messages"][-10:])
        for ev in run_agent(sid, m, text, ctx, out, bots, settings):
            t = ev.get("type")
            if t == "plan": continue               # we already emitted the plan
            bid = ev.get("agent") or m
            who = (bot_by_id(bots, bid) or {}).get("name") or bid
            # The shell, the files, the screenshots and the running commentary are that bot's own
            # work, so they go to its own chat — where you would look for them — instead of into the
            # room. Every bot that can appear here is a member of this room, so its chat is always the
            # scoped one under this room that the sidebar already lists.
            if t in CHANNEL_DETAIL:
                nid = chat_of(bid)
                _work_note(work, nid, ev, bid, bots)
                yield {**ev, "to": nid}
                continue
            if t == "agent" and ev.get("state") == "start" and ev.get("id") != m:
                # What was handed over, in the room: the delegation is the channel's business, and a
                # teammate's name with no task under it leaves the room showing a hand-off to nothing.
                hand = " ".join((ev.get("task") or "").split())
                room_said.append({"role": "route", "who": "Room",
                                  "content": "→ " + (ev.get("name") or bid) + (": " + hand[:160] if hand else ""),
                                  "ts": time.time()})
            # A bot's words are the room's business: the channel *is* the conversation, and what each
            # one says is what makes it read as one instead of a wall of closing reports. So they are
            # *not* addressed away with `to` — the room draws them, through the one plain yield below.
            # The bot's own chat keeps them too, as its record, so that chat is everything it said and
            # did and not only what it ran.
            if t == "agent_text":
                if (ev.get("text") or "").strip() and not ev.get("delta"):
                    room_says(who, ev["text"])
                _work_note(work, chat_of(bid), ev, bid, bots)
            # A stop this app caused is the account of what happened, and it was only ever live here:
            # the card was drawn while the member ran and the redraw wiped it. Kept in the room's record
            # like the hand-off, so reopening the room still says why a bot went quiet.
            if t == "notice" and (ev.get("text") or "").strip():
                room_said.append({"role": "notice", "content": ev["text"], "ts": time.time()})
            yield ev
        _work_save(work)
        yield {"type": "agent", "id": m, "name": bot_by_id(bots, m)["name"], "state": "done"}
        # The room's own report is what the bot finished with — not the first line of commentary it
        # happened to print on the way there.
        if not lead_text and out.get("text"): lead_text = out["text"]
        # ...and the room heard it already if those are the same words the bot just said: every line it
        # puts into words is in the room's record the moment it says it, so repeating the report here
        # would write the closing line into the transcript twice. When no line of its reached the room
        # (a step that emitted no `agent_text`), the report is the only record of what it said and lands.
        room_says(bot_by_id(bots, m)["name"], out.get("text"), out.get("took"))
        if room_said:
            st = load(sid); st["messages"].extend(room_said); save(sid, st); del room_said[:]
        did.append((m, out))
    if not engaged: yield {"type": "final", "text": "(no member responded)"}
    else: yield {"type": "final", "text": lead_text or ("— " + ", ".join(engaged) + " responded —")}
    # Self-learning is one extra call per member that used tools, and it lands in the member's own
    # chat where its work already lives. It is handed to `_run_turn` to run once this room's lock is
    # released, so a five-member room no longer holds the room for five model calls after the report.
    if jobs is not None:
        for m, mo in did:
            jobs.append((m, _room_learn_job(bots, m, text, mo, (sid + "/" + m) if m in members else m)))

def _room_learn_job(bots, bid, task, out, nid):
    """Reflect on one room member's finished turn, and record the note in that member's chat inside
    the room. Runs off the room's lock (see `_run_turn`); the write to the member's chat takes that
    chat's own lock, so a turn running there directly is not clobbered. Returns nothing to emit: the
    room's transcript stays a list of reports, and the note already shows in the member's own chat."""
    def job():
        notes = _learn(bot_by_id(bots, bid), bid, task, out)
        if notes:
            with _session_lock(nid):
                st = load(nid)
                st["messages"].append({"role": "sys", "content": "learned: " + " · ".join(notes)})
                save(nid, st)
        return []
    return job

# The events that are a bot's own work rather than the room's business. `agent_text` is deliberately
# *not* here: the words a bot puts into a sentence are the conversation the channel exists for — a
# teammate's acknowledgement, its answer to a steer, its report — and hiding them left the channel
# showing the user talking to silence. Only the machinery stays in the bot's own chat.
CHANNEL_DETAIL = {"tool", "shot", "image", "context"}

def _work_note(work, nid, ev, bid, bots):
    """One line of a bot's own work, in the shape its own chat draws. A tool call arrives twice —
    once as it starts and once with its output — and only the second is the record."""
    t = ev.get("type"); name = (bot_by_id(bots, bid) or {}).get("name") or bid
    if t == "tool":
        if ev.get("out") is None: return           # the "running now" card is live-only, not history
        work.setdefault(nid, []).append({"role": "tool", "agent": bid, "name": ev.get("name"),
                                         "args": ev.get("args") or {}, "out": ev.get("out") or ""})
    elif t == "agent_text":
        if ev.get("delta"): return                 # the pieces of a message being typed, not messages
        work.setdefault(nid, []).append({"role": "assistant", "who": name, "content": ev.get("text", "")})
    elif t == "context":
        n = ev.get("dropped", 0)
        work.setdefault(nid, []).append({"role": "sys", "content": "compressed %d earlier step%s to fit the context window"
                                         % (n, "" if n == 1 else "s")})

def _work_save(work):
    """One write per chat, once the bot's run is over — a turn's worth of notes, not one write per
    command. The transcript is the human's record only: a run never reads it back, so what lands
    here cannot change what a bot does next."""
    for nid, notes in work.items():
        # The member's own chat (`<room>/<bot>`) has its own lock, not the room's — a direct turn
        # there runs concurrently, so this load -> extend -> save must take that lock or one side's
        # messages are lost. `_room_learn_job` writes the same chat the same way.
        with _session_lock(nid):
            st = load(nid); st["messages"].extend(notes); save(nid, st)

def _decide_room(channel, bots, text):
    """Decision model: pick the best member in a few hundred ms, fail open to the lead."""
    try:
        cands = [{"id": b["id"], "name": b["name"], "title": b.get("title",""), "desc": b.get("role","")}
                 for b in (bot_by_id(bots, m) for m in channel["members"]) if b]
        if len(cands) == 1: return cands[0]["id"]  # nothing to decide, so no model call to decide it
        if not cands: return None
        prompt = ("Pick the single best responder for this message. Reply with ONLY the id.\n"
                  "Members:\n" + "\n".join(f"- {c['id']}: {c['name']} — {c['title']} — {c['desc']}" for c in cands) +
                  "\n\nMessage: " + text[:500])
        # A short timeout: this is a routing guess, and it must never be the reason a room message sits
        # for minutes before anyone answers. A stalled decision falls open to the lead, as designed.
        ans = chat(DEFAULT_MODEL, [{"role":"user","content":prompt}], max_tokens=20, timeout=6)["content"].strip().lower()
        for c in cands:
            if c["id"] in ans: return c["id"]
    except Exception: pass
    return None

# ---------------------------------------------------------------- routines
RT_PATH = os.path.join(DATA, "routines.json")
def load_routines(): return _load_json(RT_PATH, [])
def save_routines(r): _save_json(RT_PATH, r)
# Every routine change is a read-modify-write of the whole list, and the scheduler does its own to
# bump `last`. Without one lock around the pair, a routine added between the scheduler's read and its
# save was silently dropped — the schedule the user just made simply never ran.
_RT_LOCK = threading.Lock()
# How many routines may be registered, and how many may be running at the same moment. A routine is a
# whole turn — model calls, tools, a browser — and a turn can spend the machine's whole budget, so a
# list of them firing together is the one thing that takes the box down without anyone typing. A
# routine that cannot start now is not marked as run, so the next tick picks it up once a slot frees.
MAX_ROUTINES = 50
MAX_ROUTINES_AT_ONCE = 4
_RT_LIVE = [0]                 # routine turns running, guarded by _RT_LOCK
def _due(r, now):
    if r.get("paused"): return False
    every = r.get("every")
    if every: return now - r.get("last", 0) >= every
    cron = r.get("cron")
    if cron:
        t = datetime.datetime.fromtimestamp(now)
        return _cron_match(cron, t) and (now - r.get("last", 0) >= 60)
    return False
def _cron_match(expr, t):
    try:
        m, h, dom, mon, dow = expr.split()[:5]
        def ok(f, v): return f == "*" or (f.startswith("*/") and v % int(f[2:]) == 0) or ("," in f and v in [int(x) for x in f.split(",")]) or (f.isdigit() and int(f) == v)
        return ok(m, t.minute) and ok(h, t.hour) and ok(dom, t.day) and ok(mon, t.month) and ok(dow, (t.weekday()+1) % 7)
    except Exception: return False

ROUTINE_PROMPT_MAX = 12000
ROUTINE_SESSION_MAX = 256
ROUTINE_BOT_MAX = 128
ROUTINE_CRON_MAX = 100
ROUTINE_EVERY_MAX = 365 * 24 * 60 * 60

def _valid_cron(expr):
    """Validate the five simple cron forms understood by `_cron_match`."""
    if not isinstance(expr, str) or len(expr) > ROUTINE_CRON_MAX: return False
    fields = expr.split()
    if len(fields) != 5: return False
    ranges = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))
    try:
        for field, (lo, hi) in zip(fields, ranges):
            if field == "*": continue
            if field.startswith("*/"):
                if not field[2:].isdigit() or not 0 < int(field[2:]) <= 1000000: return False
                continue
            values = field.split(",")
            if not all(v.isdigit() and lo <= int(v) <= hi for v in values): return False
    except (TypeError, ValueError, OverflowError):
        return False
    return True
def _run_routine(r, bots, settings, chs):
    """One routine's turn, on its own thread. A long job must not starve the tick or the other
    routines — the scheduler's only job is to decide what is due."""
    try:
        sid = r["session"]
        ch, solo = resolve_session(sid, r.get("bot"), chs, bots)
        gen = _broadcast(sid, "", _run_turn(sid, r["prompt"], bots, settings, channel=ch, solo=solo, who="Routine"))
        for _ in gen: pass
    except Exception as e: print("routine %s:" % r.get("id"), e)
    finally:
        with _RT_LOCK: _RT_LIVE[0] -= 1      # the slot goes back however the turn ended

def scheduler():
    while True:
        try:
            now = time.time(); bots = load_bots(); settings = load_settings(); chs = load_channels()
            for r in load_routines():
                if not _due(r, now): continue
                # Mark it run *before* dispatching, so a turn that outlives the tick is not started
                # again on the next one; then hand it to its own thread and go on to the next routine.
                with _RT_LOCK:
                    if _RT_LIVE[0] >= MAX_ROUTINES_AT_ONCE: break    # the rest wait for the next tick
                    rs = load_routines()
                    for x in rs:
                        if x["id"] == r["id"]: x["last"] = now
                    save_routines(rs)
                    _RT_LIVE[0] += 1
                    try: threading.Thread(target=_run_routine, args=(r, bots, settings, chs), daemon=True).start()
                    except Exception:
                        _RT_LIVE[0] -= 1; raise      # a thread that never started must not hold its slot
        except Exception as e: print("scheduler:", e)
        time.sleep(30)

# ---------------------------------------------------------------- HTTP
SSE_KEEPALIVE = 15   # seconds of silence before a keepalive comment; named so a test can shrink it
# How long one write to a stream may take before the stream is abandoned. A client that has stopped
# reading — a phone that slept, a tab closed without the FIN ever reaching us — leaves a full socket
# buffer behind, and `wfile.write` then blocks for ever: the handler thread is pinned, and since the
# turn's own thread only ever queues for it, that turn is stuck too. Same bounded-budget idea as the
# model read in `chat_stream`, and generous for the same reason: the writes here are a few hundred
# bytes against a buffer of tens of kilobytes, so only a reader that has really gone can fill it.
SSE_WRITE_TIMEOUT = 30
def _bound_writes(handler, seconds=SSE_WRITE_TIMEOUT):
    """Cap how long one write on this connection may take. Absent on a stand-in handler."""
    conn = getattr(handler, "connection", None)
    if conn is None: return
    try: conn.settimeout(seconds)
    except OSError: pass
def sse(handler, gen):
    """Stream one turn as SSE. A turn can sit silent for a long time — a slow model, a long tool,
    or worst of all an approval card, which the user may leave unanswered for minutes. A connection
    with nothing on it that long is dropped by the browser or the network in between, and the turn
    then looks failed ("NetworkError") while the server is still working and the card is still
    waiting. So the generator runs in its own thread and a comment line is sent whenever it has been
    quiet; the client ignores anything that is not `data:`, so the keepalive is invisible to it."""
    handler.send_response(200); handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache"); handler.send_header("Connection", "close")
    handler.end_headers(); handler.close_connection = True
    _bound_writes(handler)
    q = queue.Queue(); DONE = object()
    # The turn keeps running to completion even if this connection has gone — that is what makes Stop
    # work, and it is what stops a phone that slept mid-turn from leaving the user's message in the
    # transcript with no answer: the report is written only at the end, so the generator must be
    # drained, not abandoned. `alive` only gates the queue: a reader that has left gets nothing queued
    # for it (the leak a closed tab used to leave behind), while the turn itself runs on.
    alive = threading.Event(); alive.set()
    def pump():
        try:
            for ev in gen:
                if alive.is_set(): q.put(ev)
        except Exception as e:
            if alive.is_set(): q.put({"type": "error", "msg": str(e)})
        finally:
            if alive.is_set(): q.put(DONE)
    threading.Thread(target=pump, daemon=True).start()
    try:
        while True:
            try: ev = q.get(timeout=SSE_KEEPALIVE)
            except queue.Empty:
                handler.wfile.write(b": keepalive\n\n"); handler.wfile.flush(); continue
            # Write everything already queued in one flush. A streamed answer arrives as one event per
            # token, and a flush per token is a syscall per token — draining the queue first keeps the
            # typing just as live (we only ever block when it is empty) while cutting the syscalls.
            batch = [ev]; done = ev is DONE
            while not done:
                try: nxt = q.get_nowait()
                except queue.Empty: break
                batch.append(nxt); done = nxt is DONE
            out = "".join(f"data: {json.dumps(x)}\n\n" for x in batch if x is not DONE)
            if out: handler.wfile.write(out.encode())
            handler.wfile.flush()
            if done: break
    # A write that runs out its budget abandons the stream and nothing else: the pump thread above
    # keeps draining the generator to the end, so the turn still finishes and still writes its
    # transcript, and `_broadcast` still tells every watcher the turn is done. Only the reader that
    # stopped reading is left without the rest of it.
    except (ConnectionResetError, BrokenPipeError, socket.timeout): pass
    except Exception as e:
        try: handler.wfile.write(f"data: {json.dumps({'type':'error','msg':str(e)})}\n\n".encode())
        except Exception: pass
    finally:
        alive.clear()

def watch_stream(handler):
    """Hold one connection open and send a line whenever a transcript moves — the same shape as a
    turn's stream, so a client that can read one can read this, keepalives included. A phone on a
    wifi that reaps idle connections would otherwise lose the stream silently and stop following the
    desktop; the keepalive is what keeps it, and the client reconnects if it is lost anyway."""
    handler.send_response(200); handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache"); handler.send_header("Connection", "close")
    handler.end_headers(); handler.close_connection = True
    _bound_writes(handler)          # a watcher that stopped reading pins its thread the same way
    q = _watching()
    try:
        handler.wfile.write(b": watching\n\n"); handler.wfile.flush()
        while True:
            try: ev = q.get(timeout=SSE_KEEPALIVE)
            except queue.Empty:
                handler.wfile.write(b": keepalive\n\n"); handler.wfile.flush(); continue
            # Drain and flush once, the same way the turn's own stream does: a mirrored turn arrives
            # as one event per token, and a flush per token is a syscall per token on the watch too.
            batch = [ev]
            while True:
                try: batch.append(q.get_nowait())
                except queue.Empty: break
            handler.wfile.write("".join("data: " + json.dumps(x) + "\n\n" for x in batch).encode())
            handler.wfile.flush()
    except (ConnectionResetError, BrokenPipeError, OSError): pass
    finally:
        _unwatch(q)          # a window that closed, or a phone that slept, stops costing anything

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def _req_token(self):
        """The token the caller presents: the header the companion app sends, or the cookie the app
        was handed once it proved it was the app. The cookie is named for what it is — the pairing
        the companion earned — and not for the token, so a browser holding an `anzen_token` cookie
        from before this rule existed is simply not paired and gets nothing."""
        t = (self.headers.get("X-Anzen-Token") or "").strip()
        if t: return t
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "anzen_pair": return v
        return ""
    def _token_ok(self):
        """Does the caller present the pairing token? Compared in constant time, and an absent one
        is never equal to a present one."""
        got = self._req_token()
        return bool(got) and secrets.compare_digest(got, lan_token())
    def _authorized(self):
        """Who may call the API.

        The door is told apart by the socket the request arrived on and the address it came from —
        never by a header. `Host` is attacker-controlled end to end: the relay replays the phone's
        Host verbatim (and substitutes "localhost" when the phone sent none), so a rule that read
        "the Host names loopback" handed the public link — and any client on the wifi — the whole
        API, shell tools and all, for the price of writing 127.0.0.1 in a header.

        The app's own channel is a 0600 Unix socket only this user's processes can open, so a request
        that arrived on it is trusted — except one the link replayed onto it, which carries the door
        header and is judged by the token like any other caller.

        A request on a real socket is this machine's own page only when it came from a loopback peer
        *and* names this machine: a visited site reaches the loopback address over a rebound
        hostname, and its Host names the attacker, so the pair is what refuses it. A DNS-rebinding
        request carries no loopback Host; a page from another site carries a foreign Origin. Both are
        refused. curl and the test suite send no Origin, which is allowed.

        Anything else arrived over the network, where the token takes the place of the address rule
        and a browser must still be same-origin as the address it dialled — a page on another site,
        port or scheme must not drive the API with a cookie it did not earn."""
        srv = getattr(self, "server", None)
        # A handler built without a socket is the test suite's stub. Reading the attribute through
        # `getattr` keeps that buildable; in production every handler has a peer, so the empty string
        # is a test-only value and it lands in the loopback branch, which still demands a loopback Host.
        # Parsed, not `split(":")`: an IPv6 Host is `[::1]:8093`, and splitting on the colon yields
        # `[` — so the `::1` entries in the loopback set were unreachable and an IPv6 loopback
        # browser could never get in.
        host = (urlparse("//" + (self.headers.get("Host") or "")).hostname or "").lower()
        peer = self.client_address[0] if isinstance(getattr(self, "client_address", None), (tuple, list)) else host
        if getattr(srv, "address_family", None) == socket.AF_UNIX:
            # The app's channel, or the link's replay of a phone's request onto it. The replay is a
            # browser and pays the token; it also answers the same-origin rule, because the pairing
            # cookie rides along on a cross-site request whether or not anyone asked it to — the
            # Origin is what stops a page the user never opened from driving the API with it.
            if not self._remote(): return True
            return self._token_ok() and self._same_site()
        if _is_loopback(peer):
            # The local test harness reaches the LAN door through 127.0.0.1 while deliberately
            # naming the address a phone would dial. A valid pairing token is the stronger credential
            # in that case; without it the Host/Origin loopback rule still refuses DNS rebinding.
            if LAN and self._token_ok(): return self._same_site("http")
            if host not in ("127.0.0.1", "localhost", "::1"): return False
            return self._same_site("http")
        if not LAN: return False
        return self._token_ok() and self._same_site("http")
    def _same_site(self, want_scheme=None):
        """True when the browser's Origin names the address it dialled.

        Compared on host, on port when the Host header carries one, and on scheme when the door's own
        scheme is known. A page served from another port or scheme on the same name is a *different*
        origin — `http://127.0.0.1:9999` reaching `http://127.0.0.1:8093` is a page the user never
        opened, and it must not drive the API with a cookie it did not earn. `None` means the header
        was absent (curl, the tests) and passes; a present Origin that names nothing (`Origin: null`,
        from a sandboxed iframe or a `data:` URL) is a browser the user never opened and is refused."""
        origin = self.headers.get("Origin")
        if origin is None: return True
        o = urlparse(origin)
        if not o.hostname: return False
        if want_scheme and o.scheme != want_scheme: return False
        h = urlparse("//" + (self.headers.get("Host") or ""))
        if (o.hostname or "").lower() != (h.hostname or "").lower(): return False
        return h.port is None or h.port == (o.port or (443 if o.scheme == "https" else 80))
    def _remote(self):
        """Was this the link's door — the relay replaying a phone's request onto this app's own
        channel? The door header alone is not enough: a LAN client can send any header it likes, but
        it cannot be on the Unix socket, so the socket is what makes the claim true. A handler built
        without a socket — the test suite does that — is nobody's link."""
        srv = getattr(self, "server", None)
        return (getattr(srv, "address_family", None) == socket.AF_UNIX
                and self.headers.get("X-Anzen-Door") == "remote")
    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def _file(self, rel):
        # Only files in the shell dir, never the secret store, and never outside it.
        #
        # Containment is judged on the path as written, not as resolved: a bundle can keep a shell
        # file in one directory and symlink it in from another, so resolving first would put every
        # one of them "outside" the dir and 404 the whole interface. The secret store, by contrast, is
        # matched on the resolved path, so a symlink cannot be used to reach it.
        root = os.path.normpath(SHELL)
        p = os.path.normpath(os.path.join(root, rel.lstrip("/")))
        if not (p == root or p.startswith(root + os.sep)): self.send_error(404); return
        r = os.path.realpath(p)
        if any(r == s or r.startswith(s + os.sep) for s in
               (os.path.realpath(DATA), os.path.realpath(os.path.join(root, "data")))):
            self.send_error(404); return
        if not os.path.isfile(p): self.send_error(404); return
        # Only the shell's own asset types are served. A whitelist, not a fallback: the source tree is
        # the shell dir in a from-source run, so a catch-all let `GET /server.py` — the backend, its
        # keys handling and all — be read off the LAN door by anyone holding the token.
        ctype = {".html":"text/html",".js":"text/javascript",".css":"text/css",".json":"application/json",
                 ".png":"image/png",".svg":"image/svg+xml",".ico":"image/x-icon",
                 ".webmanifest":"application/manifest+json"}.get(os.path.splitext(p)[1].lower())
        if not ctype: self.send_error(404); return
        b = open(p, "rb").read()
        self.send_response(200); self.send_header("Content-Type", ctype)
        # The shell is behind the token, so no shared cache may keep a copy of any of it. An icon
        # used to go out with no cache header at all, and the CDN in front of the relay cached it and
        # served it to strangers long after the page itself was refused — a small leak, but a leak,
        # and the rule is the same for every file here: nothing on this door is public, so nothing is
        # cacheable by anything but the one client that fetched it.
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def _body(self):
        """The POST body as JSON, or None if it was refused here (the reply is already sent).

        A body over MAX_BODY_BYTES is answered with a real message instead of a truncated read.
        The bytes still in flight are drained first: closing the socket mid-upload resets the
        connection, and a reset reaches the browser as a failed request with no reply at all —
        which is what made an oversized zip look like a hang rather than an error.
        """
        if self.headers.get("Transfer-Encoding"):
            # A chunked body carries no Content-Length, so the read below would take nothing and leave
            # the bytes in the socket, desyncing the next request on a keep-alive connection. Refuse it.
            self._json({"ok": False, "error": "chunked uploads are not supported"}, 411); return None
        try: n = int(self.headers.get("Content-Length", 0) or 0)
        except (TypeError, ValueError): return {}
        if n > MAX_BODY_BYTES:
            left = min(n, MAX_DRAIN_BYTES)
            while left > 0:                                   # let the client finish sending
                chunk = self.rfile.read(min(65536, left))
                if not chunk: break
                left -= len(chunk)
            if n > MAX_DRAIN_BYTES: self.close_connection = True   # too much to drain; just end it
            self._json({"ok": False, "error": "that upload is larger than %d MB"
                        % (MAX_BODY_BYTES // 1_000_000)}, 413)
            return None
        try: return json.loads(self.rfile.read(n) or b"{}")
        except Exception: return {}
    def _sid(self, body): return body.get("session") or body.get("bot") or "producer"
    def _bots_public(self, bots):
        out = [{k: b.get(k) for k in ("id","name","title","role","color","emoji","face","model","approval","memory","voice","hidden","pinned","skills","instructions","tools_allow","outfit","accessory","avatar","genface")} for b in bots]
        # A record written before these keys existed still answers with them, so the client never
        # has to guess whether a missing key means "none" or "this bot is older than the feature".
        for x in out:
            x["outfit"] = x.get("outfit") or ""; x["accessory"] = x.get("accessory") or ""
            x["avatar"] = x.get("avatar") or 0; x["genface"] = x.get("genface") or ""
        return out

    def _fail(self, e):
        """Answer an uncaught handler failure in the same JSON shape as a deliberate one.

        Before this, a handler that raised on a bad body (`{"channel": "x"}` where an object was
        wanted, `{"model": 5}` where a string was) sent no reply at all: the connection dropped, the
        client saw a network error, and the log got a traceback. Now it is a 500 the app can show."""
        self.close_connection = True                  # the request was half-handled; do not reuse it
        try: self._json({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:200])}, 500)
        except Exception: pass                        # the socket is already gone; nothing to say
    def do_GET(self):
        try: self._get_route()
        except Exception as e: self._fail(e)
    def _get_route(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        # The app's own channel is the Unix socket, and there the shell comes off the disk — so this
        # process answers the API and nothing else on it, which is the smaller surface. The phone's
        # TCP listener is a browser and still gets the shell. One handler, two doors, told apart by
        # the kind of address the request arrived on.
        #
        # The relay adds a third: the same Unix socket, but a request the link replayed, carrying the
        # Host the phone dialled. That one is a browser and gets the shell, which is what makes the
        # phone work from any network without a port being opened here.
        remote = self._remote()
        window = self.server.address_family == socket.AF_UNIX and not remote
        # The one-time handover of the token: the companion opens `/?t=…` once and the token becomes
        # a cookie, so every later call — the page's own /api/* fetches, the service worker, a
        # reload — carries it without the URL. This is the only request allowed to arrive without
        # the cookie, because it is where the cookie comes from.
        #
        # It is also the whole difference between the app and a browser, and it is why the token
        # travels in a header here as well as the query. A browser can be pointed at this link, and
        # the token in it is a bearer value: hand it a cookie and it holds the entire app from
        # anywhere, which is what made the relay a public door. A browser cannot set a header on a
        # top-level navigation; the companion can, and does. So the link alone is refused, and only
        # the app — which sends `X-Anzen-Token` — is ever handed the cookie.
        if u.path in ("/", "/index.html") and (LAN or remote) and q.get("t") and not window:
            got = self.headers.get("X-Anzen-Token") or ""
            if (secrets.compare_digest(q["t"][0], lan_token())
                    and secrets.compare_digest(got, lan_token())):
                self.send_response(302)
                # `Secure` only where the cookie is actually travelling over TLS. The desktop door is
                # plain HTTP over a Unix socket and the LAN door is plain HTTP on the wifi, and a
                # browser silently drops a Secure cookie there — which would break pairing on both.
                # A request the link replayed came in over the relay's own https hostname, so that
                # one is the only door where the attribute is both safe and worth having.
                self.send_header("Set-Cookie", "anzen_pair=" + lan_token() +
                                 "; Path=/; HttpOnly; SameSite=Lax; Max-Age=31536000"
                                 + ("; Secure" if remote else ""))
                self.send_header("Location", "/"); self.send_header("Content-Length", "0")
                self.end_headers(); return
            return self.send_error(403)
        if u.path.startswith("/api/") and not self._authorized(): return self.send_error(403)
        if u.path in ("/", "/index.html"):
            if window: return self.send_error(404)
            # The shell is as private as the API it drives. It used to be served to anyone who
            # reached the address, so a stranger on the public link saw the whole app — only the
            # /api/* calls behind it were refused. Nothing about the page is public: the handover
            # above is the one way in, and it hands over the cookie the shell then has to carry.
            if not self._authorized(): return self.send_error(403)
            return self._file("index.html")
        if u.path == "/api/lan": return self._json(lan_state())
        if u.path == "/api/relay": return self._json(relay_state())
        # Who else is looking at these chats. Held open for as long as the client stays, so it sits
        # here among the one-shot endpoints rather than with them in spirit.
        if u.path == "/api/watch": return watch_stream(self)
        if u.path == "/api/config":
            bots = load_bots(); settings = load_settings(); chs = load_channels()
            pub = settings_public(settings)
            return self._json({"bots": self._bots_public(bots), "roster": [b["id"] for b in bots],
                "router": ROUTER, "key_set": bool(KEY),
                "models": CFG.get("models") or [DEFAULT_MODEL], "default_model": DEFAULT_MODEL,
                "vision_model": CFG.get("vision_model", ""), "routines": load_routines(),
                "team_template": TEAM_TEMPLATE,
                "settings": pub, "channels": channels_public(chs),
                "font_sizes": list(FONT_SIZES), "base_font_px": BASE_FONT_PX,
                "skills": skills_public(),
                "tools": [{"name": n, "desc": TOOL_SCHEMAS[n]["function"]["description"]} for n in ALL_TOOLS],
                "connector_tools": [{"id": cid, "tool": c["tool"], "name": c["name"]}
                                    for cid, c in CONNECTORS.items() if connector_connected(settings, cid)],
                # Only what is already known: the page must never wait on spawning a server. The
                # panel's Test button is what connects one, and it fills this in.
                "mcp_status": mcp_status_public(settings)})
        if u.path == "/api/models":
            try:
                ids = fetch_models()
                return self._json({"models": ids, "count": len(ids), "ok": True, "source": "api"})
            except Exception as e:
                return self._json({"models": CFG.get("models") or [DEFAULT_MODEL], "count": 0, "ok": False, "error": str(e)[:160]})
        if u.path == "/api/media/models":
            mm = media_models()
            return self._json({"ok": True, "image": mm["image"], "video": mm["video"],
                               "image_model": IMAGE_MODELS[0] if IMAGE_MODELS else ""})
        if u.path == "/api/fs":
            return self._json(list_dirs(q.get("path", ["~"])[0]))
        if u.path == "/api/history":
            # A GET reads a chat, it does not make one: `peek` answers an unknown id with the empty
            # chat it is, so an invented id leaves nothing behind. `/api/chat` is what creates.
            sid = q.get("session", q.get("bot", ["company"]))[0]; st = peek(sid)
            bots = load_bots(); ch, solo = resolve_session(sid, st.get("bot"), load_channels(), bots)
            # Inside a channel the level is the channel's, and only the channel's: a room and its
            # member chats are one workspace, so the chip shows that one level and there is no
            # per-member fallback to name. A chat with a bot on its own still reports both, so the
            # chip can say whether it is on its own level or following the bot's default.
            in_channel = ch is not None
            own = None
            if not in_channel and solo: own = (bot_by_id(bots, solo) or {}).get("approval") or "ask"
            return self._json({"messages": st.get("messages") or [], "pending": st.get("pending"),
                               "model": effective_model(st, ch, solo, bots),
                               "bot": st.get("bot"), "title": st.get("title"),
                               "approval": (peek(ch["id"]).get("approval") if in_channel
                                            else st.get("approval")),
                               "approval_own": own,
                               "approval_kind": "room" if in_channel else "bot",
                               "ctx": st.get("ctx")})
        if u.path == "/api/state":
            known = [b["id"] for b in load_bots()] + [c["id"] for c in load_channels()]
            # scoped chats (`<channel>/<bot>`) are not bot ids, so carry them explicitly
            scoped = [s for s, _ in _sessions_snapshot() if s not in known and "/" in s]
            return self._json({k: load(k)["pending"] for k in known + scoped})
        if u.path == "/api/chats":
            return self._json({"chats": chat_list()})
        if u.path == "/api/memory":
            bid = q.get("bot", ["producer"])[0]
            return self._json({"bot": bid, "text": open(mem_path(bid), encoding="utf-8", errors="replace").read() if os.path.isfile(mem_path(bid)) else ""})
        if u.path == "/api/bot/log":
            bid = q.get("bot", ["producer"])[0]
            return self._json({"bot": bid, "text": log_read(bid)})
        if u.path == "/api/computer":
            return self._json({"url": BROWSER.url, "title": BROWSER.title, "ok": BROWSER.ok, "err": BROWSER.err,
                               "mode": BROWSER.mode, "attached": BROWSER.attached})
        if u.path == "/api/browser":
            b = load_settings().get("browser") or {}
            port = browser_port(b)
            return self._json({"ok": True, "mode": b.get("mode", "own"),
                               "port": port, "cdp_url": "http://127.0.0.1:%d" % port,
                               "target_url": b.get("target_url", ""), "target_urls": BROWSER._targets(),
                               "profile": b.get("profile", "default"), "accounts": b.get("accounts") or [],
                               "headless": bool(b.get("headless", False)),
                               "channel": b.get("channel") or "auto", "channels": installed_channels(),
                               "engine": BROWSER.engine,
                               "running": BROWSER.ok, "attached": BROWSER.attached, "err": BROWSER.err,
                               "hint": browser_hint(BROWSER.err)})
        if u.path == "/api/browser/profiles":
            return self._json(browser_profiles())
        if u.path == "/api/browser/own":
            # `?room=` scopes the list to a room's own accounts, which is what its editor draws.
            rid = q.get("room", [""])[0]
            if rid:
                ch = channel_by_id(load_channels(), rid)
                if not ch: return self._json({"ok": False, "err": "unknown room"})
                return self._json(browser_own_profiles(ch["browser"]))
            return self._json(browser_own_profiles())
        if u.path.startswith("/api/logo/"):
            # The channel is looked up by id first, so the URL never becomes a path: only a stored
            # channel's own logo can ever be served.
            c = channel_by_id(load_channels(), u.path[len("/api/logo/"):])
            lg = logo_state(c) if c else {"path": ""}
            if not lg["path"]: return self.send_error(404)
            try: blob = open(lg["path"], "rb").read()
            except OSError: return self.send_error(404)
            ctype = LOGO_TYPE.get(os.path.splitext(lg["path"])[1].lower(), "application/octet-stream")
            self.send_response(200); self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(blob)))
            # An uploaded SVG is served from our own origin, so a direct visit must not be able to
            # run anything in it. It is inert inside <img>; this covers the other case.
            self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "private, max-age=300")
            self.end_headers(); self.wfile.write(blob); return
        if u.path == "/api/faces":
            return self._json(faces_public(load_bots()))
        if u.path.startswith("/api/face/"):
            # A generated face is served by its file name, which only this server ever writes, and
            # the name is checked against the shape those names have before it becomes a path.
            name = u.path[len("/api/face/"):]
            if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,60}\.(png|jpg|jpeg|webp|gif)", name):
                return self.send_error(404)
            p = os.path.join(FACES_DIR, name)
            if not os.path.isfile(p): return self.send_error(404)
            try: blob = open(p, "rb").read()
            except OSError: return self.send_error(404)
            self.send_response(200)
            self.send_header("Content-Type", FACE_MIME.get(os.path.splitext(name)[1].lower(), "application/octet-stream"))
            self.send_header("Content-Length", str(len(blob)))
            self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "private, max-age=300")
            self.end_headers(); self.wfile.write(blob); return
        if u.path.startswith("/api/avatar/"):
            # Same shape as the logo route: the bot is looked up by id first, so the URL never
            # becomes a path and only a stored bot's own avatar can ever be served.
            b = bot_by_id(load_bots(), u.path[len("/api/avatar/"):])
            av = avatar_state(b) if b else {"path": ""}
            if not av["path"]: return self.send_error(404)
            try: blob = open(av["path"], "rb").read()
            except OSError: return self.send_error(404)
            ctype = LOGO_TYPE.get(os.path.splitext(av["path"])[1].lower(), "application/octet-stream")
            self.send_response(200); self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(blob)))
            # Same reason as a logo: an uploaded SVG served from our own origin must not be able to
            # run anything if it is visited directly.
            self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "private, max-age=300")
            self.end_headers(); self.wfile.write(blob); return
        if u.path == "/api/computer/preview":
            # Scoped to the chat you are looking at. One browser serves every chat, so a panel that
            # answered with whatever was on screen showed you another chat's work. An empty frame that
            # names whoever *is* using it reads as "not this chat" rather than as a broken panel.
            owners, _ = _computer_scope(q.get("sid", [""])[0])
            if owners is not None and BROWSER.owner not in owners:
                who = bot_by_id(load_bots(), BROWSER.owner) if BROWSER.owner else None
                return self._json({"png": "", "url": "", "title": "",
                                   "err": ("%s is using the computer — not this chat's bot" % who["name"]) if who
                                          else "this chat's bot is not using the computer"})
            # Always through call(), even with no browser: that is what retries the attach, so a
            # profile opened after the panel was first drawn shows up on the next poll by itself.
            d = BROWSER.call("preview", timeout=30, force=q.get("force", [""])[0] in ("1", "true"))
            try: d = json.loads(d)
            except Exception: d = {"png": "", "url": BROWSER.url, "title": BROWSER.title, "err": str(d)}
            return self._json({"png": d.get("png", ""), "url": d.get("url", ""),
                               "title": d.get("title", ""), "err": d.get("err", "")})
        if u.path == "/api/files":
            sid = q.get("session", q.get("bot", [""]))[0]
            root, label = _file_root(sid)
            p, err = _file_path(sid, q.get("path", [""])[0])
            if err: return self._json({"ok": False, "error": err})
            if not os.path.isdir(p): return self._json({"ok": False, "error": "that is a file, not a folder"})
            try:
                with os.scandir(p) as it:
                    ents = []
                    for e in it:
                        # `follow_symlinks=False` throughout: a symlink is listed as the file it
                        # looks like and never followed, so a link pointing out of the repo cannot
                        # make this walk out of it. A broken link still stats, hence the guard.
                        d = e.is_dir(follow_symlinks=False)
                        try: size = 0 if d else e.stat(follow_symlinks=False).st_size
                        except OSError: size = 0
                        ents.append({"name": e.name, "dir": d, "size": size})
            except OSError as e:
                return self._json({"ok": False, "error": "cannot read %s: %s" % (p, e.strerror or e)})
            # Directories first, dot-names last — the order the repo picker uses, so both panels
            # read the same way. Dotfiles are kept: the tree is meant to show the whole repo.
            ents.sort(key=lambda x: (not x["dir"], x["name"].startswith("."), x["name"].lower()))
            more = max(0, len(ents) - 1000)
            rel = "" if p == root else os.path.relpath(p, root).replace(os.sep, "/")
            return self._json({"ok": True, "root": root, "path": rel,
                               "name": label if p == root else os.path.basename(p),
                               "entries": ents[:1000], "more": more})
        if u.path == "/api/file/apps":
            return self._json({"ok": True, "apps": file_apps()})
        if u.path.startswith("/api/"): return self._json({"error": "not found"}, 404)
        if window: return self.send_error(404)      # the app's window reads the shell off the disk
        # ...and every static file the shell pulls in is behind the same token as the page itself.
        if not self._authorized(): return self.send_error(403)
        return self._file(u.path)

    def do_POST(self):
        try: self._post_route()
        except Exception as e: self._fail(e)
    def _post_route(self):
        u = urlparse(self.path)
        if u.path.startswith("/api/") and not self._authorized(): return self.send_error(403)
        body = self._body()
        if body is None: return          # too large; the refusal has already been sent
        if u.path == "/api/chat":
            sid = self._sid(body); text = body.get("text"); bots = load_bots(); settings = load_settings()
            ch, solo = resolve_session(sid, body.get("bot"), load_channels(), bots)
            turn = str(body.get("turn") or "")
            return sse(self, _broadcast(sid, turn, _run_turn(sid, text, bots, settings, channel=ch, solo=solo,
                                       quote=_clean_quote(body.get("quote")), fwd=bool(body.get("fwd")))))
        if u.path == "/api/history/truncate":
            # An edited or retried message replaces everything after it, so the transcript holds one
            # version of the conversation rather than every attempt ever made.
            sid = self._sid(body)
            try: keep = int(body.get("keep", 0) or 0)
            except (TypeError, ValueError): keep = 0     # a stray string is "keep nothing", not a 500
            ok = truncate_chat(sid, keep)
            if not ok: return self._json({"ok": False, "error": "a turn is running in this chat"}, 409)
            return self._json({"ok": True, "messages": load(sid).get("messages") or []})
        if u.path == "/api/chat/steer":
            # Steering is only steering if a turn is there to steer *and* still able to take it:
            # `STEER[sid]` exists for exactly as long as that chat's turn does, and stops counting the
            # moment the turn is past its last step. When either is false the caller is told so and
            # keeps the message in its own queue — where it runs as the next turn instead of vanishing.
            sid = self._sid(body); text = (body.get("text") or "").strip()
            if not text: return self._json({"ok": False, "error": "nothing to steer with"})
            d = STEER.get(sid)
            if d is None or sid in STEER_CLOSED: return self._json({"ok": False, "running": False})
            d.append({"text": text, "quote": _clean_quote(body.get("quote"))})
            return self._json({"ok": True, "running": True})
        if u.path == "/api/stop":
            # Ask this chat's turn to land. The flag is checked at the top of every step and also
            # wakes a turn parked on an approval card, so a Stop always takes effect within a step —
            # on any client, including a phone stopping a turn the desktop started.
            sid = self._sid(body)
            if sid in STEER:                       # `STEER[sid]` exists for exactly as long as the turn
                STOP.add(sid)
                a = APPROVAL.get(sid)              # popped the instant the card is answered, so read once
                if a: a["event"].set()
                return self._json({"ok": True, "stopping": True})
            return self._json({"ok": True, "stopping": False})
        if u.path == "/api/approve":
            sid = self._sid(body); allow = bool(body.get("allow"))
            a = APPROVAL.get(sid)                  # a second answer (a double-click, two devices) must
            if a:                                  # not 500 on an entry the first answer already popped
                a["allow"] = allow; a["event"].set()
                return self._json({"ok": True, "resolved": True})
            st = load(sid)
            if st.get("pending"):
                st["pending"] = None; st["messages"].append({"role":"assistant","content":"(command denied by user)"}); save(sid, st)
            return self._json({"ok": True, "denied": not allow})
        if u.path == "/api/skills/scan":
            data = _data_bytes(body.get("data") or "")
            if not data: return self._json({"ok": False, "error": "send the zip as a data URL in `data`"})
            found, errs = scan_skill_zip(data)
            if not found: return self._json({"ok": False, "error": (errs or ["nothing found in that zip"])[0], "errors": errs})
            return self._json({"ok": True, "found": found, "errors": errs})
        if u.path == "/api/skills/install":
            data = _data_bytes(body.get("data") or "")
            if not data: return self._json({"ok": False, "error": "send the zip as a data URL in `data`"})
            # `ids` picks a subset from a scan; absent means the whole zip, which is what a caller
            # that never scanned (and every older client) expects.
            ids = body.get("ids")
            ids = [str(i) for i in ids] if isinstance(ids, list) else None
            made, errs = install_skill_zip(data, (body.get("name") or "upload.zip")[:120], ids)
            if not made: return self._json({"ok": False, "error": (errs or ["nothing to install"])[0], "errors": errs})
            return self._json({"ok": True, "installed": [{k: v for k, v in s.items() if k != "body"} for s in made],
                               "errors": errs, "skills": skills_public()})
        if u.path == "/api/skills/remove":
            sid = (body.get("id") or "").strip()
            return self._json({"ok": bool(sid) and remove_skill(sid), "skills": skills_public()})
        if u.path == "/api/team/import":
            text = (body.get("text") or "").strip()
            if not text: return self._json({"ok": False, "error": "paste a BotMRR playbook or a list of names first"})
            # A paste built from the structure we hand out is held to that structure: a half-filled
            # playbook is refused with every missing part named, rather than imported as a team of
            # bots called "Teammate" that the user then has to repair one editor at a time.
            problems = team_problems(text)
            if problems:
                return self._json({"ok": False, "problems": problems,
                                   "error": "this playbook is not the structure we accept"})
            made, rooms = build_team(text)
            if not made: return self._json({"ok": False, "error": "could not find any agents in that text"})
            return self._json({"ok": True, "created": [b["name"] + " (" + b["title"] + ")" for b in made],
                               "room": rooms[0]["name"] if rooms else "",
                               "bots": self._bots_public(load_bots()),
                               "channels": load_channels()})
        if u.path == "/api/bot":
            bots = load_bots(); b = dict(body.get("bot") or {})
            bid = b.get("id") or _slug(b.get("name"), "bot")
            b["id"] = bid
            existing = bot_by_id(bots, bid)
            if existing: existing.update(b)
            else:
                b.setdefault("emoji", "🤖")      # a new bot gets a face even if the caller named none
                bots.append(_norm_bots([b])[0])  # ...and every other field, from the one shared list
            save_bots(bots)
            return self._json({"ok": True, "bot": b, "bots": self._bots_public(bots)})
        if u.path == "/api/bot/delete":
            bid = body.get("id"); bots = [b for b in load_bots() if b["id"] != bid]; save_bots(bots)
            chs = load_channels()
            for c in chs:
                c["members"] = [m for m in c["members"] if m != bid]
                # A room left pointing at a lead that no longer exists could never take a message
                # (its turn named a bot that was not there). Hand the lead to a surviving member.
                if c.get("lead") not in c["members"]:
                    c["lead"] = c["members"][0] if c["members"] else None
            save_channels(chs)
            drop_session(bid, "bot")   # a deleted bot leaves no orphan conversation behind
            remove_avatar(bid)         # ...and no orphan avatar file either
            return self._json({"ok": True, "bots": self._bots_public(bots)})
        if u.path == "/api/bot/duplicate":
            bid = body.get("id"); bots = load_bots(); src = bot_by_id(bots, bid)
            if src:
                cp = json.loads(json.dumps(src)); cp["id"] = bid + "-copy"; cp["name"] = src["name"] + " copy"
                bots.append(cp); save_bots(bots)
            return self._json({"ok": True, "bots": self._bots_public(bots)})
        if u.path == "/api/channel":
            chs = load_channels(); c = dict(body.get("channel") or {})
            # These are derived on read, not stored. A client that echoes a channel back (the editor
            # does) would otherwise write them into channels.json as if they were real settings.
            for k in ("logo", "logo_src", "logo_rel", "folder_ok"): c.pop(k, None)
            # The id is a slug and nothing else: it names the session, the row, and now the logo
            # file on disk, so an id from the client must never be able to reach outside data/logos.
            cid = re.sub(r"[^a-z0-9]+", "-",
                         (c.get("id") or c.get("name") or "room").lower()).strip("-")[:48]
            if not cid: return self._json({"ok": False, "error": "a channel needs a name"})
            c["id"] = cid
            # A folder that does not exist would silently fall back to the shared sandbox, which is
            # exactly the mixing this feature exists to prevent — so refuse it up front instead.
            if c.get("folder", "").strip() and not resolve_folder(c["folder"]):
                return self._json({"ok": False, "error": "no folder at " + c["folder"].strip() +
                                   " — check the path (or leave it blank for the shared sandbox)"})
            ex = channel_by_id(chs, cid)
            if ex: ex.update(c)
            else:
                # A room created without a team starts with the whole roster, as it always has.
                c.setdefault("members", [b["id"] for b in load_bots()])
                # ...and `name`, `mode`, `lead` and the rest come from the one shared list, so a
                # create can never again write a record the loader has to repair (or crash on).
                chs.append(_norm_channels([c])[0])
            # One pass over the whole list, so an updated record is shaped by the same rules a loaded
            # one is — the browser rows included, which is where a hand-sent field could otherwise land.
            chs = _norm_channels(chs)
            save_channels(chs)
            return self._json({"ok": True, "channels": chs})
        if u.path == "/api/channel/delete":
            cid = body.get("id"); chs = [c for c in load_channels() if c["id"] != cid]; save_channels(chs)
            drop_session(cid, "channel"); remove_logo(cid)     # a deleted company leaves no logo behind
            return self._json({"ok": True, "channels": chs})
        if u.path == "/api/nav/order":
            # A sidebar rearrangement. The order *is* the array in bots.json / channels.json, so it
            # needs no field of its own and the phone reads the same order as the window.
            ids = [str(i) for i in (body.get("ids") or [])]
            kind = body.get("kind")
            if kind == "members":
                chs = load_channels(); c = channel_by_id(chs, body.get("id") or "")
                if not c: return self._json({"ok": False, "error": "unknown room"})
                c["members"] = reorder(c.get("members") or [], ids, key=lambda m: m)
                save_channels(chs)
                return self._json({"ok": True, "channels": channels_public(chs)})
            if kind == "channels":
                chs = reorder(load_channels(), ids); save_channels(chs)
                return self._json({"ok": True, "channels": channels_public(chs)})
            if kind != "bots": return self._json({"ok": False, "error": "nothing to reorder"})
            bots = reorder(load_bots(), ids); save_bots(bots)
            return self._json({"ok": True, "bots": self._bots_public(bots)})
        if u.path == "/api/logo":
            chs = load_channels(); c = channel_by_id(chs, body.get("id") or "")
            if not c: return self._json({"ok": False, "error": "unknown channel"})
            r = save_logo(c["id"], body.get("data"))
            if r["ok"]:
                lg = logo_state(c)
                r.update({"logo": lg["v"], "logo_src": lg["source"], "logo_rel": lg["rel"]})
            return self._json(r)
        if u.path == "/api/logo/remove":
            chs = load_channels(); c = channel_by_id(chs, body.get("id") or "")
            if not c: return self._json({"ok": False, "error": "unknown channel"})
            remove_logo(c["id"])
            lg = logo_state(c)
            return self._json({"ok": True, "logo": lg["v"], "logo_src": lg["source"],
                               "logo_rel": lg["rel"], "removed": True})
        if u.path == "/api/avatar":
            bots = load_bots(); b = bot_by_id(bots, body.get("id") or "")
            if not b: return self._json({"ok": False, "error": "unknown bot"})
            r = save_avatar(b["id"], body.get("data"))
            if r["ok"]:
                av = avatar_state(b); b["avatar"] = av["v"]; save_bots(bots)
                r.update({"avatar": av["v"], "avatar_src": av["source"]})
            return self._json(r)
        if u.path == "/api/avatar/remove":
            bots = load_bots(); b = bot_by_id(bots, body.get("id") or "")
            if not b: return self._json({"ok": False, "error": "unknown bot"})
            remove_avatar(b["id"]); b["avatar"] = 0; save_bots(bots)
            return self._json({"ok": True, "avatar": 0})
        if u.path == "/api/avatar/transform":
            bots = load_bots(); b = bot_by_id(bots, body.get("id") or "")
            if not b: return self._json({"ok": False, "error": "unknown bot"})
            # An image-to-image call is 30-60s of real work at the router, so the timeout is long on
            # purpose: cutting it short would turn a slow picture into a failure.
            data_url, used = gen_image(avatar_prompt(body.get("species"), body.get("color")),
                                       image=body.get("data") or "", timeout=180)
            if not data_url: return self._json({"ok": False, "error": used})
            r = save_avatar(b["id"], data_url)
            if not r["ok"]: return self._json(r)
            av = avatar_state(b); b["avatar"] = av["v"]; save_bots(bots)
            return self._json({"ok": True, "avatar": av["v"]})
        if u.path == "/api/faces/source":
            r = _save_image(FACES_DIR, "src", body.get("data"), "image", cap=6 << 20)
            if not r.get("ok"): return self._json(r)
            st = faces_batch(); st["source"] = r["file"]
            _save_json(FACES_BATCH_PATH, st)
            return self._json({"ok": True, "source": r["file"]})
        if u.path == "/api/faces/generate":
            if FACE_JOB["running"]: return self._json({"ok": False, "error": "the faces are still being drawn"})
            st = faces_batch()
            if not st["source"]: return self._json({"ok": False, "error": "introduce one image first"})
            bots = load_bots()
            if not bots: return self._json({"ok": False, "error": "there are no bots yet"})
            try: raw = open(os.path.join(FACES_DIR, st["source"]), "rb").read()
            except OSError: return self._json({"ok": False, "error": "the source image is gone"})
            # The species and colour come from the client because it derives a species from the bot
            # id exactly as the engine does; the record's own fields are the fallback.
            spec = {x.get("id"): x for x in (body.get("targets") or []) if isinstance(x, dict)}
            targets = []
            for x in bots:
                t = spec.get(x["id"]) or {}
                targets.append((x["id"], t.get("species") or x.get("face") or "",
                                t.get("color") or x.get("color") or ""))
            batch_id = time.strftime("%Y%m%d-%H%M%S")
            source = "data:%s;base64,%s" % (
                FACE_MIME.get(os.path.splitext(st["source"])[1].lower(), "image/png"),
                base64.b64encode(raw).decode())
            FACE_JOB.update({"running": True, "done": 0, "total": len(targets), "error": "", "id": batch_id})
            threading.Thread(target=_face_worker,
                             args=(batch_id, st["source"], source, targets), daemon=True).start()
            return self._json({"ok": True, "job": dict(FACE_JOB)})
        if u.path == "/api/faces/assign":
            bots = load_bots(); b = bot_by_id(bots, body.get("id") or "")
            if not b: return self._json({"ok": False, "error": "unknown bot"})
            f = (body.get("file") or "").strip()
            if f and f not in faces_batch()["files"]:
                return self._json({"ok": False, "error": "that face is not in the set"})
            set_genface(b, f); save_bots(bots)
            return self._json({"ok": True, "genface": b["genface"]})
        if u.path == "/api/faces/clear":
            bots = load_bots()
            for b in bots: b["genface"] = ""
            save_bots(bots)
            # The introduced image stays: it is what the next set is drawn from, and the panel says so.
            _save_json(FACES_BATCH_PATH, {"source": faces_batch()["source"]})
            _faces_prune()
            return self._json({"ok": True})
        if u.path == "/api/models/detect":
            try:
                ids = fetch_models(); save_models(ids)
                return self._json({"ok": True, "models": CFG["models"], "count": len(ids)})
            except Exception as e:
                return self._json({"ok": False, "models": CFG.get("models") or [DEFAULT_MODEL], "error": str(e)[:160]})
        if u.path == "/api/models/add":
            mid = (body.get("model") or "").strip()
            if not mid: return self._json({"ok": False, "error": "no model id"})
            ids = list(CFG.get("models") or []) + [mid]; save_models(ids)
            return self._json({"ok": True, "models": CFG["models"], "count": len(CFG["models"])})
        if u.path == "/api/models/remove":
            mid = (body.get("model") or "").strip()
            ids = [m for m in (CFG.get("models") or []) if m != mid]
            if not ids: ids = [DEFAULT_MODEL]
            save_models(ids)
            return self._json({"ok": True, "models": CFG["models"], "count": len(CFG["models"])})
        if u.path == "/api/config":
            return self._json(save_connection(body))
        if u.path == "/api/model":
            # An empty model clears the pick, so the chat falls back to the bot's own model.
            sid = self._sid(body); st = load(sid)
            st["model"] = (body.get("model") or "").strip() or None
            save(sid, st)
            bots = load_bots(); ch, solo = resolve_session(sid, st.get("bot"), load_channels(), bots)
            return self._json({"ok": True, "model": effective_model(st, ch, solo, bots)})
        if u.path == "/api/media/model":
            mid = (body.get("model") or "").strip()
            if not mid: return self._json({"ok": False, "error": "no model id"})
            CFG["image_model"] = mid; _save_json(CFG_PATH, CFG)
            # Same builder as startup, so picking a model that turns out not to route leaves the
            # fallbacks in place instead of leaving the tool with nothing to try.
            IMAGE_MODELS[:] = _image_models(mid)
            return self._json({"ok": True, "image_model": mid})
        if u.path == "/api/approval_mode":
            sid = self._sid(body); st = load(sid)
            mode = (body.get("mode") or "").strip()
            # Inside a channel the level lives on the channel, not on whichever row was clicked: a
            # room and its member chats are one workspace with one rule, so setting it from a member
            # sets it for the room. Clearing it puts the channel back to its default of asking.
            ch, _solo = resolve_session(sid, None, load_channels(), load_bots())
            if ch: sid = ch["id"]; st = load(sid)
            st["approval"] = None if mode in ("", "default") else mode
            save(sid, st)
            return self._json({"ok": True, "approval": st["approval"], "session": sid})
        if u.path == "/api/memory":
            bid = body.get("bot")
            if not bid: return self._json({"ok": False, "err": "which bot?"}, 400)   # mem_path slugs the id
            if body.get("text") is not None: mem_write(bid, body["text"])
            return self._json({"ok": True})
        if u.path == "/api/settings":
            s = load_settings(); patch = body.get("settings") or {}
            for k, v in patch.items():
                if k == "connectors": continue   # connector credentials go through /api/connector
                if k == "mcp":
                    # The panel never sees env values or header values, so a save carrying none
                    # keeps the stored ones rather than wiping a working server's credentials.
                    old = s.get("mcp") or []
                    s["mcp"] = mcp_merge(old, v)
                    for m in old:                    # an edit must not keep talking to the old server
                        mcp_forget(m.get("id"))
                    continue
                if isinstance(v, dict) and isinstance(s.get(k), dict): s[k].update(v)
                else: s[k] = v
            save_settings(s)
            return self._json({"ok": True, "settings": settings_public(s)})
        if u.path == "/api/connector":
            cid = body.get("id"); s = load_settings(); ent = _connector_entry(s, cid)
            if not ent: return self._json({"ok": False, "error": "unknown connector"})
            if body.get("disconnect"):
                for k in ("token", "base_url", "client_id", "client_secret"): ent[k] = ""
            else:
                # Every credential field is write-only: blank means "keep what is saved", so the
                # browser never has to round-trip a secret just to leave it alone.
                for k in ("token", "client_id", "client_secret"):
                    v = (body.get(k) or "").strip()
                    if v: ent[k] = v
                if "base_url" in body:
                    # A custom base is how a self-hosted GitHub Enterprise is reached, and it is also
                    # a way to aim this connector's own credential at the metadata service or at
                    # something on the internal network — the tool calls this app makes carry the
                    # token, so a private host is refused here, where the user can see why.
                    base_url = (body.get("base_url") or "").strip()
                    error = connector_url_error(base_url) if base_url else ""
                    if error:
                        return self._json({"ok": False, "error": error})
                    ent["base_url"] = base_url
            _TOKEN_CACHE.pop(cid, None)     # a new or cleared credential must not reuse the cached token
            for x in s.get("connectors", []): x["connected"] = connector_connected(s, x.get("id"))
            # Through the cache, not straight to disk: a bare `_save_json` here left the in-memory copy
            # stale, so the bot's tool list never gained the new connector and the next settings save
            # wrote that stale copy back — silently wiping the credential.
            save_settings(s)
            return self._json({"ok": True, "connected": connector_connected(s, cid),
                               "tools": [c["tool"] for cc, c in CONNECTORS.items() if connector_connected(s, cc)]})
        if u.path == "/api/connector/test":
            s = load_settings(); cid = body.get("id")
            if cid not in CONNECTORS: return self._json({"ok": False, "error": "unknown connector"})
            return self._json(conn_test(cid, s))
        if u.path == "/api/mcp/test":
            # Connect a server now and report its tools, or why it would not come up. The entry may
            # come from the panel unsaved (a Test before Add); otherwise it is the stored one.
            s = load_settings(); entry = body.get("server")
            if not isinstance(entry, dict):
                entry = next((m for m in (s.get("mcp") or [])
                              if isinstance(m, dict) and m.get("id") == body.get("id")), None)
            if not entry: return self._json({"ok": False, "error": "unknown MCP server"})
            if not (entry.get("target") or "").strip(): return self._json({"ok": False, "error": "no command or URL to connect to"})
            return self._json(mcp_test(entry))
        if u.path == "/api/mcp/disconnect":
            # Let go of a server without touching its settings — for a server that was stopped, or
            # after a change to something the entry cannot express (an env var it now needs).
            mcp_forget(body.get("id"))
            return self._json({"ok": True})
        if u.path == "/api/routine":
            if not isinstance(body, dict):
                return self._json({"ok": False, "error": "routine body must be an object"}, 400)
            prompt = body.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                return self._json({"ok": False, "error": "routine prompt must be a non-empty string"}, 400)
            if len(prompt) > ROUTINE_PROMPT_MAX:
                return self._json({"ok": False, "error": "routine prompt is too long (max %d characters)" % ROUTINE_PROMPT_MAX}, 400)
            session = body.get("session")
            if session is not None and not isinstance(session, str):
                return self._json({"ok": False, "error": "routine session must be a string"}, 400)
            if isinstance(session, str) and len(session) > ROUTINE_SESSION_MAX:
                return self._json({"ok": False, "error": "routine session is too long"}, 400)
            bot = body.get("bot")
            if bot is not None and not isinstance(bot, str):
                return self._json({"ok": False, "error": "routine bot must be a string"}, 400)
            if isinstance(bot, str) and len(bot) > ROUTINE_BOT_MAX:
                return self._json({"ok": False, "error": "routine bot is too long"}, 400)
            sid = session or bot or "producer"
            if not isinstance(sid, str) or not sid.strip():
                return self._json({"ok": False, "error": "routine session must not be empty"}, 400)
            if len(sid) > ROUTINE_SESSION_MAX:
                return self._json({"ok": False, "error": "routine session is too long"}, 400)
            try:
                every_raw = body.get("every")
                if every_raw is None or every_raw == "":
                    every = None
                elif isinstance(every_raw, bool):
                    raise ValueError
                elif isinstance(every_raw, int):
                    every = every_raw
                elif isinstance(every_raw, str) and re.fullmatch(r"[0-9]+", every_raw.strip()):
                    every = int(every_raw.strip())
                else:
                    raise ValueError
            except (TypeError, ValueError):
                return self._json({"ok": False, "error": "routine every must be a positive integer in seconds"}, 400)
            if every is not None and not 0 < every <= ROUTINE_EVERY_MAX:
                return self._json({"ok": False, "error": "routine every must be between 1 and %d seconds" % ROUTINE_EVERY_MAX}, 400)
            cron = body.get("cron")
            if cron is not None and not isinstance(cron, str):
                return self._json({"ok": False, "error": "routine cron must be a string"}, 400)
            cron = cron.strip() if isinstance(cron, str) else None
            if cron and not _valid_cron(cron):
                return self._json({"ok": False, "error": "routine cron must have five valid fields"}, 400)
            if every is None and not cron:
                return self._json({"ok": False, "error": "routine needs a positive interval or cron expression"}, 400)
            bots = load_bots(); chs = load_channels()
            if bot and not bot_by_id(bots, bot):
                return self._json({"ok": False, "error": "unknown routine bot"}, 400)
            if session and bot and channel_by_id(chs, session) is not None:
                return self._json({"ok": False, "error": "a room routine cannot also name a bot"}, 400)
            if (channel_by_id(chs, sid) is None and bot_by_id(bots, sid) is None
                    and "/" not in sid):
                return self._json({"ok": False, "error": "unknown routine session"}, 400)
            ch, solo = resolve_session(sid, bot, chs, bots)
            if ch is None and (not solo or not bot_by_id(bots, solo)):
                return self._json({"ok": False, "error": "unknown routine session or bot"}, 400)
            with _RT_LOCK:
                rs = load_routines()
                if len(rs) >= MAX_ROUTINES:
                    return self._json({"ok": False, "error": "that is as many routines as this app keeps (%d)" % MAX_ROUTINES})
                rs.append({"id": str(uuid.uuid4())[:8], "session": sid, "bot": bot,
                           "prompt": prompt, "every": every,
                           "cron": cron or None, "paused": bool(body.get("paused")), "last": 0})
                save_routines(rs)
            return self._json({"ok": True, "routines": rs})
        if u.path == "/api/routine/delete":
            with _RT_LOCK:
                rs = [r for r in load_routines() if r["id"] != body.get("id")]; save_routines(rs)
            return self._json({"ok": True, "routines": rs})
        if u.path == "/api/browser/restart":
            return self._json(BROWSER.restart())
        if u.path == "/api/browser/launch":
            return self._json(launch_browser())
        if u.path == "/api/browser/own/open":
            return self._json(open_own_profile(body.get("name", ""), body.get("sites")))
        if u.path == "/api/computer/open":
            url = (body.get("url") or "").strip()
            if not url: return self._json({"ok": False, "err": "no url"})
            # The panel's box points *this chat's* bot at a page, so the screen that comes back is
            # attributed to the chat you are in — otherwise the panel would open a screen that its own
            # scoping then refuses to show you. It routes like a turn in that room does, too.
            sid = self._sid(body)
            _, actor = _computer_scope(sid)
            ch, _solo = resolve_session(sid, None, load_channels(), load_bots())
            out = BROWSER.call("open", url=url, timeout=60, _owner=actor, routes=_room_routes(ch))
            return self._json({"ok": BROWSER.ok, "out": out[:400]})
        if u.path == "/api/clear":
            sid = self._sid(body)
            if not clear_chat(sid):
                # 409, like the sibling truncate endpoint, so a client can branch on the status rather
                # than parsing the body to tell "busy" apart from "done".
                return self._json({"ok": False, "error": "a turn is still running in this chat — "
                                                        "let it finish or answer its card first"}, 409)
            return self._json({"ok": True, "session": sid})
        if u.path == "/api/lan":
            on = bool(body.get("on"))
            if not set_lan(on):
                return self._json({"ok": False, "error": "LAN access was set on the command line"})
            # The listener switches under this response; the screen reads the state back and waits.
            return self._json(dict({"ok": True}, **lan_state()))
        if u.path == "/api/relay":
            # `on` flips the link, `url` points it somewhere else. Both in one call because the two
            # arrive together: pasting an address and switching on is one gesture in the panel.
            # A private address here is never a relay — this process dials *out* to it, so pointing it
            # at something on the internal network is a way to make the app speak the link's protocol
            # at a host it has no business reaching. Refused by the same rule as a webhook URL.
            relay_url = (body.get("url") or "").strip() if "url" in body else ""
            error = relay_url_error(relay_url) if relay_url else ""
            if error:
                return self._json({"ok": False, "error": error})
            if relay_url and private_host(relay_url):
                return self._json({"ok": False, "error": "the relay address must not be a private address"})
            if not set_relay(on=body.get("on") if "on" in body else None,
                             url=body.get("url") if "url" in body else None):
                return self._json({"ok": False, "error": "the relay address must use HTTPS (the link uses WSS)"})
            return self._json(dict({"ok": True}, **relay_state()))
        if u.path == "/api/file/open":
            p, err = _file_path(self._sid(body), body.get("path"))
            if err: return self._json({"ok": False, "error": err})
            if not os.path.exists(p): return self._json({"ok": False, "error": "no such file"})
            how = str(body.get("how") or "open")
            win = sys.platform == "win32"; mac = sys.platform == "darwin"
            if how == "open":
                # None is the Windows form: the shell's own association has no argv shape.
                cmd = None if win else (["open", p] if mac else ["xdg-open", p])
            elif how == "finder":
                cmd = (["explorer", "/select," + p] if win else
                       ["open", "-R", p] if mac else ["xdg-open", os.path.dirname(p)])
            elif how.startswith("with:") and any(a["name"] == how[5:] for a in file_apps()):
                # The name must be one this server just offered in /api/file/apps, so a client
                # cannot talk the server into launching an application of its own choosing.
                cmd = None if win else (["open", "-a", how[5:], p] if mac else ["xdg-open", p])
            else:
                return self._json({"ok": False, "error": "unknown action"})
            try:
                # Never shell=True, never waited on: these are GUI launches, and waiting would
                # park this handler for as long as the app stays open.
                if cmd is None: os.startfile(p)
                else: subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                return self._json({"ok": False, "error": str(e)})
            return self._json({"ok": True})
        self._json({"error": "not found"}, 404)

def boot(warm_browser=True):
    """Everything that has to happen once before the socket opens: a session for every bot and
    company on the roster, the routine scheduler, and the headless browser warm-up."""
    for b in load_bots(): new_session(b["id"], bot=b["id"], title=b["name"])
    for c in load_channels(): new_session(c["id"], bot=None, title=c["name"])
    threading.Thread(target=scheduler, daemon=True).start()
    warm_mcp()                                    # connect MCP servers now, off the first turn's path
    if warm_browser and os.environ.get("BROWSER_WARMUP", "1") != "0":
        threading.Thread(target=BROWSER.start, daemon=True).start()  # warm up the headless browser in the background

def where():
    """The line the user actually needs: the address to open here, and — on the LAN, where nobody
    could guess it — the address to type into the phone.

    The address, not the link. This goes to the launcher's log, which is a file on disk and a
    console anyone looking over a shoulder can read, and the pairing token in it is the whole
    credential for the API — shell tools and all. So it says a token is needed and where the app
    shows it; the settings screen is where the whole link is copied from."""
    line = (f"Anzen-bot backend on {SOCK}  (sandbox={SANDBOX})" if SOCK
            else f"Anzen-bot backend on http://{HOST}:{PORT}  (sandbox={SANDBOX})")
    if SOCK and not LAN:
        line += "\n  (a Unix socket, not a port: nothing on the network, and no browser, can reach it)"
    if LAN:
        line += (f"\nPhone or tablet: http://{lan_ip()}:{PORT}/  (a token is needed — the Phone &"
                 f" tablet card shows it and copies the whole link; it is also in {TOKEN_PATH})")
    r = load_settings().get("relay") or {}
    if r.get("on") and r.get("url"):
        line += (f"\nPhone or tablet, from anywhere: {r['url'].rstrip('/')}/  (the same token; the"
                 f" relay's own secret is in {RELAY_SECRET_PATH})")
    return line

def lan_state():
    """What the settings screen shows, and what the phone needs typed into it."""
    return {"enabled": LAN, "host": HOST, "port": PORT,
            "url": f"http://{lan_ip()}:{PORT}/", "token": lan_token() if LAN else ""}

def set_lan(on):
    """Turn the LAN listener on or off. The marker file is the decision; the socket follows it, so
    the setting survives a restart and the app never has to be quit to reach a phone."""
    global LAN
    if FORCED: return False                      # a command line asked for this; the screen cannot undo it
    if on: open(LAN_MARK, "w").write("1\n")
    elif os.path.exists(LAN_MARK): os.remove(LAN_MARK)
    if SOCK:
        # The app's own channel is a Unix socket and never moves. Only the phone's TCP listener is
        # opened or closed here, so flipping the switch cannot interrupt the window's own traffic.
        _reconcile_lan()
        return True
    LAN = not _is_loopback(_bind())
    _rebind()
    return True

# ---------------------------------------------------------------- the link out to the relay
# What lets the phone in from any network. The dial-out is a thread in this process, and it replays
# the phone's requests onto this app's own channel — so the relay path needs no port either, and a
# request that arrived that way is told apart from the window's by the door header the link sets.
_relay_lock = threading.Lock()
_LINK = None                      # the running dial-out, or None
LINK_UP = False                   # what it last knew about itself
LINK_NOTE = ""                    # ...and why it is down, for the screen to say

def relay_target():
    """Where the link replays a request: this app's own channel when there is one, else loopback."""
    return ("unix:" + SOCK) if SOCK else ("http://127.0.0.1:%d" % PORT)

def relay_url_error(base):
    """Return why a configured relay address is unsafe, or an empty string when it is valid."""
    u = (base or "").strip()
    if not u: return ""
    if u.lower().startswith(("http://", "ws://")):
        return "the relay address must use HTTPS (the link uses WSS)"
    if u.lower().startswith(("https://", "wss://")):
        return "the relay address must be an HTTPS URL, not a WebSocket URL" if u.lower().startswith("wss://") else ""
    if re.match(r"^[A-Za-z0-9.-]+(?::[0-9]+)?(?:/.*)?$", u): return ""
    return "the relay address must be an HTTPS URL"

def relay_ws_url(base):
    """`https://host` -> `wss://host/agent`. One address to type, and the endpoint follows from it."""
    u = (base or "").strip().rstrip("/")
    if not u or relay_url_error(u): return ""
    if u.startswith("https://"): return "wss://" + u[8:] + "/agent"
    return "wss://" + u + "/agent"

def relay_state():
    """What the settings screen shows. The secret is this app's own, minted here, and it is the one
    thing the relay on your host has to be told — so it is shown, exactly as the phone's token is.
    The token comes along too, because the link the phone is set up with is `?t=…` on the relay
    address: the relay carries the request, but the token is still what the API checks."""
    r = load_settings().get("relay") or {}
    url = (r.get("url") or "").rstrip("/")
    on = bool(r.get("on"))
    return {"on": on, "url": r.get("url") or "", "secret": relay_secret(),
            "up": LINK_UP, "note": LINK_NOTE, "phone": (url + "/") if url else "",
            "token": lan_token() if on else ""}

def _link_state(up, why=""):
    global LINK_UP, LINK_NOTE
    LINK_UP = up; LINK_NOTE = why

def _start_link(base):
    global _LINK
    if link is None: return _link_state(False, "the link is missing from this build")
    ws = relay_ws_url(base)
    if not ws: return _link_state(False, "no relay address yet")
    with _relay_lock:
        if _LINK is not None and _LINK.url == ws: return
        _stop_link_locked()
        _LINK = link.Link(ws, relay_target(), relay_secret(), on_state=_link_state).start()

def _stop_link():
    with _relay_lock: _stop_link_locked()

def _stop_link_locked():
    global _LINK
    if _LINK is not None:
        _LINK.stop(); _LINK = None

def set_relay(on=None, url=None):
    """Turn the link on or off, or point it at a different relay. The setting is what is remembered
    and the dial-out follows it, so the switch survives a restart and a running app is never quit."""
    s = load_settings()
    r = s.setdefault("relay", {"on": False, "url": ""})
    candidate = (url or "").strip() if url is not None else (r.get("url") or "").strip()
    if not (on is False and url is None) and relay_url_error(candidate): return False
    if url is not None: r["url"] = candidate
    if on is not None: r["on"] = bool(on)
    save_settings(s)
    if r["on"] and r["url"]: _start_link(r["url"])
    elif r["on"]: _stop_link(); _link_state(False, "no relay address yet")
    else: _stop_link(); _link_state(False, "the link is off")
    return True

def start_link_from_settings():
    """Called once the listener is up, so a link left on is dialled again on this launch."""
    r = load_settings().get("relay") or {}
    if r.get("on") and r.get("url"): _start_link(r["url"])
    elif r.get("on"): _link_state(False, "no relay address yet")

class Srv(ThreadingHTTPServer):
    """The listener, with two settings that only matter when the LAN switch is flipped.

    HTTP/1.1 keep-alive means a handler thread outlives the request it answered, and a browser holds
    such a connection open for as long as the page is up. `server_close` would normally wait for
    those threads, which would leave the old socket open — and the port taken — for as long as a
    browser tab lives. So the threads are daemonic and closing does not wait for them.

    The wildcard address is also retried: binding 0.0.0.0 can lose a race with the sockets the
    browser just closed on 127.0.0.1, and one lost race must not leave the switch stuck."""
    daemon_threads = True
    block_on_close = False
    def __init__(self, addr, handler, family=socket.AF_INET):
        # `ThreadingHTTPServer` builds an AF_INET socket in its own `__init__`, so the family has to
        # be in place before that runs. A Unix socket is the same server on a different kind of
        # address: the routing, the handlers and the auth rule are all unchanged.
        self.address_family = family
        super().__init__(addr, handler)
    def server_bind(self):
        # `HTTPServer.server_bind` fills `server_name` from a reverse DNS lookup. Nothing here reads
        # it, and in a frozen build that lookup can fail outright — `socket.getfqdn` reaches for the
        # `idna` codec, which PyInstaller need not have bundled, and the raise then leaves the app
        # with a window and no API at all. So the socket is bound directly and the name filled from
        # the address we already have. A failed bind leaves the socket usable, so this is a retry
        # and not a rebuild.
        for attempt in range(12):
            try:
                socketserver.TCPServer.server_bind(self)
                if self.address_family == socket.AF_UNIX:
                    self.server_name, self.server_port = str(self.server_address), 0
                else:
                    self.server_name, self.server_port = self.server_address[:2]
                return
            except OSError:
                if attempt == 11: raise
                time.sleep(0.25)

_SRV = None
_LAN_SRV = None
_RESTART = threading.Event()
def _rebind():
    """Make the listener match the marker without dropping the process: the serve loop below comes
    back round and opens the address the marker now asks for. Called from a request thread, so the
    response to that request is written first and this only nudges the loop — which is also what
    closes the old socket, so the port is free by the time the new address is tried."""
    if _SRV is None: return
    _RESTART.set()
    threading.Thread(target=_SRV.shutdown, daemon=True).start()

def _reconcile_lan():
    """Open or close the phone's TCP listener so it matches the marker, leaving the app's own Unix
    socket alone. The shutdown runs on its own thread and a beat later: the request that asked for
    this came in on one of the two servers, and its reply has to be on the wire before that server
    stops answering."""
    global _LAN_SRV, LAN
    want = not _is_loopback(_bind())
    if want and _LAN_SRV is None:
        try:
            _LAN_SRV = Srv((_bind(), PORT), H)
        except OSError as e:
            print(f"could not listen on {_bind()}:{PORT} ({e}); the phone cannot reach this machine",
                  flush=True)
            LAN = False
            return
        threading.Thread(target=_LAN_SRV.serve_forever, daemon=True).start()
        LAN = True
    elif not want and _LAN_SRV is not None:
        srv, _LAN_SRV = _LAN_SRV, None
        LAN = False
        def close():
            time.sleep(0.4)
            srv.shutdown(); srv.server_close()
        threading.Thread(target=close, daemon=True).start()
    else:
        LAN = want

def serve(host=None, port=None, warm_browser=True):
    """Serve the API until the process ends. The desktop launcher calls this on a thread; running
    `python3 server.py` calls it on the main one. `host` overrides the one the environment chose."""
    global HOST, PORT, LAN, _SRV, HOST_ENV, FORCED
    if host: HOST_ENV = host; FORCED = not _is_loopback(host)
    if port: PORT = int(port)
    boot(warm_browser)
    if SOCK:
        # The app: one channel, a Unix socket, and no TCP listener at all unless the phone switch
        # asks for one. A stale file from a killed process would block the bind, so it goes first.
        if os.path.exists(SOCK):
            try: os.remove(SOCK)
            except OSError: pass
        _SRV = Srv(SOCK, H, family=socket.AF_UNIX)
        try: os.chmod(SOCK, 0o600)          # only the user running the app may open this
        except OSError: pass
        def _unlink(*_):
            # A socket file left behind would be a dead address the next launch has to step over, so
            # the app takes it with it. SIGTERM is how the window closing ends this process, and it
            # does not run atexit handlers, hence the explicit handler.
            try: os.remove(SOCK)
            except OSError: pass
        atexit.register(_unlink)
        for _sig in (signal.SIGTERM, signal.SIGINT):
            try: signal.signal(_sig, lambda *_: sys.exit(0))
            except (ValueError, OSError): pass
        _reconcile_lan()
        start_link_from_settings()          # the listener is up, so a link left on can be dialled
        print(where(), flush=True)
        _SRV.serve_forever()
        _SRV.server_close()
        try: os.remove(SOCK)
        except OSError: pass
        return
    while True:
        HOST = _bind(); LAN = not _is_loopback(HOST)
        try:
            _SRV = Srv((HOST, PORT), H)
        except OSError as e:
            # The LAN address would not open (another process, a firewall). Fall back to loopback and
            # say so, rather than leaving the app dead — the screen reads the live state back.
            print(f"could not listen on {HOST}:{PORT} ({e}); falling back to loopback", flush=True)
            HOST = "127.0.0.1"; LAN = False
            _SRV = Srv((HOST, PORT), H)
        start_link_from_settings()
        print(where(), flush=True)
        _SRV.serve_forever()
        _SRV.server_close()                    # hand the port back before opening the new address
        if not _RESTART.is_set(): return       # a plain shutdown means the process is going away
        _RESTART.clear()

if __name__ == "__main__":
    # `--lan` is the one flag that matters: it is what lets the phone app reach this machine.
    serve(host="0.0.0.0" if "--lan" in sys.argv else None,
          port=os.environ.get("PORT") or 8093)
