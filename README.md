# Anzen-bot

A self-hosted multi-agent chat workspace you run on your own machine, against your own [OI]-compatible API router.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE) [![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/) [![Platform: macOS | Windows | Linux](https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey.svg)](#desktop-app)

Give a room one goal and a team of bots works on it. A Producer plans and delegates, specialists do the work with real tools — a shell, files, and a headless browser they can see and click — and the Producer reports back. You approve what matters, watch their live screen, and talk to any bot one-to-one. Every bot has its own model, approval level, memory, skills, tools, voice and look. Everything is unlocked: no tiers, no paywall, no subscription.

## Quick start

Requires Python 3.9+. The server is stdlib-only. Playwright is optional and only the browser tool needs it.

```sh
git clone https://github.com/Sanxdy/anzen-bot.git && cd anzen-bot

export ROUTER_URL="http://127.0.0.1:11434/v1"   # any [OI]-compatible endpoint
export ROUTER_KEY="sk-..."                       # optional
export DEFAULT_MODEL="your-model"                # must support tool-calling
export VISION_MODEL="your-vision-model"          # for browser_see, optional
export PORT=8093

python3 server.py
# open http://127.0.0.1:8093
```

`run.sh` does the same with sensible defaults. On first run the server writes `data/config.json` from those environment variables, so edit it afterwards to change the router, key or models. It also writes `data/bots.json` and `data/channels.json`, seeding one room called Company with five bots already on the team: Producer (Chief of Staff), Researcher, Builder, QA and Ops. From then on they are ordinary records — rename them, re-brief them, add your own, or delete them. Optional, for the browser tool:

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install playwright==1.61.0
playwright install chromium            # or reuse existing browsers via PLAYWRIGHT_BROWSERS_PATH
python3 server.py
```

## Features

### Bots and rooms

- Rooms. Each room has its own transcript, member list, shared instructions and responder rule (lead / auto / everyone), so Work, Personal and each project stay apart without cloning your bots. Type `@` in a room's message box and its members drop down with name, role and avatar; the list filters as you type, `↑`/`↓` move the highlight, and Enter, Tab or a click inserts the name the server matches. A mention names only a room's own members, and a `@` in a 1:1 chat is just a character. A bot is told its own current name and its room's current members in every run rather than reading them from its brief, so renaming a bot takes effect at once.
- One repo per room. Set a room's Repo folder and its bots run every shell command and file tool inside that folder only, so several repos never mix. The field is browsable via Browse, or you can type a path. The room header shows the repo in use. A blank folder keeps the room on the shared folder, and a path that does not exist is refused at save time.
- A bot inside a room is its own chat. The sidebar nests each room's bots under it. Talking to a bot from inside a room opens a 1:1 chat scoped to that room, so its shell and file tools run in that room's repo. The same bot in two rooms is two separate conversations (`Webshop → Producer` works in the Webshop repo, `Mobile App → Producer` in the Mobile App repo) with no bleed between them, while staying one bot with one face, one memory and one config. One click opens a room; a double click folds its team shut and another pair opens it again, and the fold is remembered. Bots in no room sit under the Bots section and keep the shared folder.
- Each bot works in its own field and keeps its own log. A room hands a job to a bot, and that bot works in its own folder under the room's repo (`<repo>/<bot>`, created on first use), so two teammates never write over each other. The room is a conversation: it carries what each bot says — the delegation with the task handed over, the acknowledgement, the answer to a steer, the report. The steps are a bot's own: shell commands, file dumps, screenshots and commentary land in that bot's chat inside the room (`<room>/<bot>`, created on first use), live while it works and kept afterwards. A lead hands work only to the members you added; a `delegate` naming anyone else is refused and the room is told why. Every turn a bot runs, direct or delegated, is appended to that bot's work log (`data/logs/<bot>.md`, last 400 lines), readable in **Settings → Memory → Work log**. A turn that fails writes nothing.
- A logo per room. If the room's Repo folder already has a logo (`logo.*`, `brand.*`, `icon.*` or `favicon.*`, at the root or in `public/`, `static/`, `assets/`, `images/`, `build/`, `resources/`), that image is used. Otherwise use **Upload logo** in the room editor (png, jpg, webp, gif or svg, up to 2 MB); **Remove** hands the row back to the repo's logo, and with neither the initials come back. Uploads are checked by their bytes, not the filename, and an svg carrying script is refused.
- Switch chats mid-turn without losing the work. A turn belongs to the chat it was started in, so switching to another room or bot while it runs neither empties the panel nor scatters the running turn's cards into the wrong transcript. The chat you left keeps drawing into its own place and its sidebar row stays lit; the chat you are looking at names the bot that is working in its header. Come back and the plan, the tool cards and the running output are all still there. Each chat runs its own turn.
- Queue a task, or steer the one running. A task sent while one is already running is held in a queue above the composer. Left alone, it runs the moment the turn ends, in the chat you queued it in. **Steer now** hands it to the running turn instead, so the bot changes direction mid-task; a steered task reaches the bot at its next step, after the command it is running now, and is kept in the transcript like any message you type. **×** takes a task back out — nothing was sent, so nothing is undone. The queue is per chat.
- Quote a message, or forward it. Every message has **Reply** and **Forward** buttons (on hover on desktop, always visible in the bubble on touch). Reply quotes the message: the quote waits above the composer, travels with the next task, and is drawn over it in the transcript. The bot is told what you are replying to, because it never sees the transcript. Forward sends a copy to another chat you pick from a list of your rooms and chats; it arrives marked Forwarded and is picked up as a task. Both marks are kept with the message.
- Bots as contacts. Right-click any bot to pin, edit, duplicate, hide or delete it. Add new bots with their own name, title, colour and standing instructions. Each bot gets an animated face of its own in the sidebar.
- Clear chat, a new session without the amnesia. The row menu (**⋯** or right-click) has **Clear chat**. It empties that chat's transcript and keeps the bots' memory: a bot's notes (`data/memory/<bot>.md`) and its work log are not part of a session, so the next chat picks up knowing what the project is about. It is per chat, and the chat's own model pick and approval level survive, so clearing can never quietly loosen a chat you set to Plan only. It asks first, and it is refused while a turn is still running in that chat. **Delete** removes the bot or the room.
- Import a team from BotMRR. **Settings → Bots → Import a team** takes a team copied from [botmrr.io](https://botmrr.io/) and makes every agent its own bot, keeping its distinct name and position (Lea — Producer, Alex — UI, Dima — Dev), its colour, and the shared room with its members and lead. A plain list like `Lea — Producer` works too. Colours off the six-colour palette are mapped to the nearest one.

### Tools

Bots run on real tool-calling, the standard [OI] `tools` API:

- `run_shell`, `read_file`, `write_file`, `list_files` — a command in the shared folder, and file work
- `browser_open`, `browser_read`, `browser_click`, `browser_type`, `browser_press`, `browser_back`, `browser_eval` — drive a real Chromium (`browser_eval` runs one JavaScript expression in the page, for what click and type cannot express)
- `browser_see`, `browser_save` — screenshot the page and look at it with a vision model, and wait for the picture or video a site just produced, download it, show it in the chat
- `generate_image` — draw a picture through the API router. Off by default, because it spends your API tokens; the free web route is the default
- `memory_update`, `delegate` — write a durable note to the bot's memory, and hand a task to a teammate and get their report

The bot editor's Tools section has two modes: **All current tools** (the bot's default set, except that the lead bot starts with `delegate`, `memory_update`, `use_skill` and `finish`, since a coordinator plans rather than runs commands) or **Custom selection**, a tick-list of every tool with a one-line explanation of each. The list is built from the server's own tool table (`/api/config`), so it can never offer a tool the server cannot run, and a connected app adds its tool to the list too. Fewer tools help a small-context model stay on track. The choice is saved with the bot.

### Approvals

A risky shell command surfaces as an inline **Allow / Deny** card before it runs. Commands on a small read-only allowlist (`ls`, `cat`, `grep`, `git status`, …) run straight through, as do file writes and questions.

Choose a level per bot (Bots → Approval level) or per chat (the **Approval** chip in the header).

- **Plan only** — read-only tools only (read a file, list files, open a page, read it, look at it): no shell command, no writing, no image, no delegation, no connected apps. The bot investigates and reports a plan, then stops. The plan arrives with an **Approve plan and run it** button, which switches that chat to full access and runs the plan.
- **Ask for approval** — every tool is available; a shell command that is not a plain read-only one raises a card and the bot waits. File writes, browser actions, image generation, delegation and connected apps run without a card, so today the card covers risky shell commands only.
- **Auto-accept edits** — as Ask today; file writes are not gated yet.
- **Approve routine** — as Ask today.
- **Full access** — no card is ever raised; every tool the bot has (shell, files, browser, image, delegation, connected apps, MCP servers) runs straight away. Every level but Full is gated the same way, so there is no Custom level.

Which level actually runs. A bot has its own level, and a chat may carry one of its own. In a room the room's level is the only level: a room is one team with one rule, so the level set on the room runs for every member, a member's own default is neither used nor shown there, and a level picked from a member's row is written to the room so the two rows cannot disagree. In a 1:1 chat the chat's own level governs if it has one, otherwise the bot's own default. The **Approval** chip always says which of the two is in force: `Approval: Plan only` means the chat has its own level, and `Approval: Full access · bot default` (1:1 only) means it is following the bot. In a 1:1 chat with a level of its own, the menu leads with **Use the bot's own level**, which hands the chat back to the bot's default. A room's menu says **What may run in this room** above the levels. A bot's own Full access is a grant no room or chat may revoke.

### Memory and skills

- Memory. Each bot keeps plain-markdown notes (`data/memory/<bot>.md`), and the first 200 lines load into every turn — chat, rooms and delegations alike. Bots self-learn: after a run that used real tools they reflect once on their own work and append the durable facts, working commands and gotchas they discovered. Turn the per-bot memory switch off to stop both reading and learning. The file is capped at 400 lines, keeping the header and the newest notes. The **Work log** card under it shows that bot's own log, read-only.
- Skills. Reusable capabilities you switch on per bot (Settings → Skills, or the bot editor). Each enabled skill is an index line in the prompt, not a briefing: the bot reads one on demand with `use_skill` when it decides the skill covers the job. The built-ins ship real guidance: **Web browsing** is the recipe for driving a real site in few steps, and **Research** is how to answer a question with sources and evidence.
- Install from a zip. A zip holds one folder per skill, each with a `SKILL.md` whose frontmatter names and describes it, and it may hold several. Uploading scans the zip and installs nothing yet: you get a list of what is inside, each with its description and how many files it brings, all ticked; untick what you do not want and press **Install selected**, or **Install all**. A skill that would land on top of one you already have is marked *replaces installed*. Whatever you install brings its whole folder, bundled scripts and references included. A zip never overwrites a built-in skill, and may be up to 25 MB (any single skill over 200 files or 2 MB is refused). The list has a search box and filters — **Recently installed**, **Installed from zip**, **Built-in**, **On for this bot** — and an installed skill has a **Remove** button that uninstalls it and switches it off everywhere.
- Plugins. MCP servers your bots can use. Add a server by the command that starts it (local, over the stdio transport) or by its URL (remote, over Streamable HTTP, falling back to the older HTTP+SSE transport when the server only speaks that). **Test** connects it now and reports the tools it offers, or why it would not come up; a server that just failed is not retried on every turn. Once connected, every tool a server offers becomes a real tool for every bot, named `mcp__<server>__<tool>` so two servers can both have an `echo` without colliding. Env vars and headers are stored write-only: the panel is told only that they are set, and a save that carries none keeps the ones already stored. **Switch off** keeps a server on the list but stops offering its tools; **Remove** takes it and its connection away.
- Connected apps. Connect an app (GitHub, Slack, Notion, Linear, Gmail, Drive, Calendar, Webhooks) and every bot gains a real tool that calls that app's API — read issues, post messages, search pages, fire webhooks. Credentials are stored write-only, so the UI only ever sees a connected flag. A per-app **Test** button calls the real API, and a refusal comes back as a sentence naming the cause. Each app declares how its credential is sent: GitHub, Slack and Notion take a bearer token; Linear takes a personal API key sent as-is; Gmail, Drive and Calendar use OAuth, because a Google access token dies within the hour. For those three, create an OAuth client of type **Desktop app** in the Google Cloud console and take a refresh token from the [OAuth Playground](https://developers.google.com/oauthplayground) (gear icon → *Use your own OAuth credentials*), then paste the client id, client secret and refresh token; the access token is minted and renewed for you. A refresh token from a consent screen still in Testing mode expires after 7 days.

### Settings

Fourteen sections: **General · AI model · Browser · Phone · Bots · Rooms · Connected apps · Skills · Plugins · Memory · Approvals · Voice · Appearance · Help**.

- Help is the tutorial and the reference, in the app rather than in this file: a jump list over twenty-two sections, from the idea of bot, room and chat through quoting and forwarding, queued tasks and steering, the header chips and the computer button, the approval levels and exactly what each one reaches, the tool catalogue, every settings tab, the sidebar and dock, the keyboard, installing as an app, and phone and tablet. Every list on the page is built from the constant the app itself runs on — `APPROVALS` for the levels, the server's own tool list for the tools, `S.skills` for the skills — so a feature cannot be added and left undescribed. Reachable from the **Help** button above Settings in the sidebar, or the last tab in Settings. The **Approvals** tab renders the same per-level detail from the same definition.
- General holds the app-wide switches: workspace name, reading replies aloud automatically, auto-routing an un-mentioned room message to a fast model, and notification sounds. A chime plays when a turn finishes, fails, stops to ask you something, or is rate-limited, each with its own cue, synthesised in the browser so there is no audio file to ship. The middle of a turn stays silent. Browsers only allow sound after a real interaction; the volume slider previews the cue when you let go, and 0 is the same as off.
- AI model is where a bot's brain runs. The **Connection** card names the [OI]-compatible router every bot talks to (paste your own URL and API key; the key is stored server-side and never shown again). The **Models** card manages the list: **Detect all models from the API key** pulls every model the key can reach, and you can add an id by hand, filter and remove. A long list shows a dozen rows at a time with a **Show all** count. Every model in the list is selectable per bot, from a list you open and filter in place; an id the router does not list can still be typed and chosen. The **Context** card sets the token budget for one request (0 follows the model's own window) and whether a run that outgrows it is compressed rather than failing. **Image generation** lists the image-capable models the key can reach and lets you pick the one bots draw with; video is reported honestly as unavailable when the key has none. Router image drawing is off by default.
- Browser is where the bots browse and the logins they keep. The box offers three ways — own browser (a fresh browser each time, nothing logged in), saved profiles (one browser per account, logins written to disk), or ZenPilot / any browser over CDP (reuses the profiles you are already signed into) — and the line under it describes the one you picked. Below it, one row per account: a name, the sites the bots should use it for, and a **Sign in** button that opens that row's first site in its own window. Log in there, then close that window, which is what writes the login to disk, and the row turns to **Signed in**. That word is read from the site's own sign-in cookie, not from the folder existing, so it never claims a login that did not happen; a site that leaves no readable cookie says so plainly. A row's browser is the folder its logins live in, so two rows cannot share one — a second name pointing at the same folder is marked as that same browser. Only the sites you list for an account ever see its cookies. The **Browser** picker chooses which browser those windows are: **Automatic** uses a Chrome really installed on this Mac, because Google refuses to sign anyone in on the Chromium we ship.
- Phone is the LAN listener the Android app talks to. **Phone & tablet** is off by default, turned on by a switch and guarded by a token, so only a device you have set up can use it; the card shows the address and the token with a button that copies the whole link. **From anywhere** is the relay card beside it: it makes the phone work on cellular or hotel wifi by having this app and the phone both dial out to a relay that joins the two, so nothing is opened on this computer and no router is touched.
- Voice reads bot replies aloud with the browser's built-in voices. No cloud key, nothing sent to a server.
- Appearance offers eleven theme packages, an accent colour, density, font and text size. A theme is a whole look: **Dark** and **Light**, **Liquid Glass** (chrome becomes a blurred translucent pane over a slow iridescent wash, while the transcript stays solid) and its light twin, **AI-Native UI** and its light twin, **Dark Luxe**, **E-Ink / Paper**, **Terminal Hacker** and **Monochrome** and its light twin. Picking a theme adopts its signature accent; the colour field below is where you take it back, and re-picking the theme you are already on leaves your accent alone. The accent previews as you pick and saves with its **Save** button; it tints the primary button, the live dot and your own messages, and its label always gets whichever of black or white reads better. The font picker offers eighteen faces — System, ZCode, Rounded, Avenir, Helvetica, Futura, Optima, Gill Sans, Trebuchet, Wide, Serif, Georgia, Palatino, Didot, Charter, Mono, SF Mono and JetBrains Mono — each one already on your machine, so nothing is downloaded and it works offline; code and tool output keep their monospace face whatever you choose. Text size is a real size in px (12.5 to 18.5), so the whole interface scales together and keeps its proportions; a save from before this change stored a multiplier and is converted to the size it meant on first load.

### Browser

By default each bot drives its own headless Chromium. Point **Browser** at a browser you are already running — ZenPilot, or any Chromium started with `--remote-debugging-port=9222` — and the bots attach over CDP instead of opening a window, reusing the profiles you are already logged into, so there is no extra browser and no login wall.

ZenPilot shows every profile as an Electron `<webview>`, which Playwright cannot see, so for those the server speaks the DevTools Protocol itself (stdlib only) and drives the profile directly. **Which profiles?** takes one or more URL fragments (comma-separated) — list `gemini.google.com, openart.ai` and the bots open each site in the profile logged into it, hopping between them as they go; leave it empty and they use the first profile you have open. One attach reaches every profile ZenPilot holds, so nothing is ever logged in twice.

Give the card the debug port and that is the only number to get right: the bots connect to `http://127.0.0.1:<port>`, and **Launch ZenPilot & connect** opens ZenPilot on that same port, waits for it to answer, and attaches. The endpoint is derived from the port, so the app cannot connect to a port the launch never opened. **Test connection** saves the port and reconnects to a browser that is already running. Opening the app for you is macOS-only; elsewhere start your browser with `--remote-debugging-port=<port>` yourself and press **Test connection**.

**Import profiles** skips the typing: it asks ZenPilot which profiles are open right now, lists each one by the site it is signed into, and lets you tick some or all of them into the pin field. When ZenPilot is not installed the card says so (it looks in `Applications` rather than guessing) and links to where to get it, and if it is installed but not running the status line names the button that fixes it instead of showing a raw connection error.

Free image and video, no API tokens. Sites like Gemini, Google Flow, OpenArt and Dola give you a quota you already have, and the bots spend that instead of your API key — `browser_open` the site, `browser_type` the prompt, `browser_click`, `browser_save`, which waits for the result and drops it into the chat. The paid router route (`generate_image`) stays off by default: it is gated on `media.router_image`, which nothing in the UI writes, so turning it on means setting it to `true` in `data/settings.json`.

### Chat

- A bot's reply is rendered, not dumped. Headings, bold, italic, strikethrough, inline code, fenced code blocks, bullet and numbered lists, blockquotes, rules, links and tables all come out as real elements. Everything is escaped before it is parsed, so a reply containing raw HTML or a `<script>` shows the text and cannot inject markup, and a link that is not `http`, `mailto` or relative is made inert. Your own message is never parsed — a shell command you type arrives exactly as typed.
- Switch the model on the spot. The chip at the top of a chat names the model that will actually answer it: the one you picked for that chat, else the model set on the bot (a room uses its lead's), else the default. Click it for a searchable list of every enabled model; the chat switches at once and the choice is remembered for that chat only. *Each bot's own model* in the same menu clears the override.
- Set the approval on the spot. The **Approval** chip beside it names what the current chat may do without asking, and clicking it lists the levels to pick from, in place, without opening the Bots list. See [Approvals](#approvals) for which level runs.
- A card that waits as long as you do. A turn streams to the browser over one long-lived connection, and a turn can go quiet for a while: a slow model, a long command, or an approval card you have not answered. The stream sends a keepalive every 15 seconds while a turn has nothing to say, so the connection stays open and the card stays answerable however long you leave it. If the connection does drop anyway, the chat says what happened in words rather than echoing the browser: a turn that never reached the server says so and invites a retry, one that died part-way through says the bot may still be working on it, and a failure inside the turn is reported the same way instead of ending as a silent stop.
- Context that never overflows. Every model has a window, so a long run is compressed instead of erroring: the oldest steps are dropped to fit, the system prompt is kept, and the chat says so ("compressed N earlier steps"). The budget follows the model's own known window by default, and **AI model → Context limit** overrides it (0 follows the model). Compression can be switched off there if you would rather the request fail loudly.
- See what filled the window. The **ctx** chip at the top of a chat says how full that chat's context window is (`ctx 76%`), and hovering or clicking it opens the split: the used and total counts, a stacked bar filled to the same fraction, and a row per part with its share — the transcript, the tool schemas the bot was given, the tools from Connected apps, the tools from your MCP servers, the system prompt, the skills it carries, and the memory and team context folded in. The numbers are measured, not guessed: the app measures the prompt in the pieces it composes it from, and the provider's own `prompt_tokens` for that very request is the number at the top, with the rows scaled onto it. The chip warms at 75% and turns red at 90%. It is per chat, survives a reload, and starts over with Clear chat.
- Computer panel. Open a bot's **Computer** to watch its live screen — a screenshot of the real browser — and point it at any page.

### Accessibility

The interface is semantic HTML: `<aside>` for the sidebar and the computer panel, `<nav>` for the rooms and the settings rail, `<main>` holding a `role="log"` transcript and a `<footer>` composer, and a real `role="dialog"` with a `role="tablist"` for Settings. The sidebar fold is a button that reports its state with `aria-expanded` and is remembered across reloads. Every theme's primary button label clears WCAG AA contrast against its accent.

### Faces, mascot and installable app

Every bot has an animated face in the sidebar: a canvas creature whose body shape, ears, eyes and way of idling are picked from the bot's id, so a team looks like a team without anyone configuring it. Twelve species ship — Mochi, Cat, Bunny, Owl, Frog, Ghost, Robot, Alien, Imp, Bean, Blob and Star. The eyes track your cursor, the ears lag behind a hop, and the face wears the bot's colour, one of a six-colour agent palette (purple `#7C5CFF`, blue `#38BDF8`, green `#2EC4A0`, orange `#F29B38`, yellow `#EAB308`, pink `#EC4899`). Open a bot in **Settings → Bots** to pick its species by hand, with a live preview next to the picker.

A canvas mascot lives in the bottom-right dock and wears the face of the bot you are talking to, same species and colour as that bot's sidebar row, so the corner always tells you who is speaking. Open a room and it falls back to the general Mochi, since a room is a whole team with no single face. Click to poke it, hover to see what it is doing, and its eyes follow your cursor. It wears an emotion to match its state: curious while thinking, worried when a turn needs approval, happy when one lands.

Anzen-bot is also a progressive web app. Open it in a browser and use **Install app** (or the browser's own install control) to add it to your desktop or phone home screen; it then runs in its own window, offline-capable for the app shell, with a proper icon. No store, no build step.

## Configuration

The server writes everything under `data/`:

| Path | Holds |
|---|---|
| `data/config.json` | the router URL and key, the default model and the vision model |
| `data/settings.json` | app settings and credentials |
| `data/bots.json` | the bot roster |
| `data/channels.json` | the rooms and their membership |
| `data/memory/<bot>.md` | one bot's notes |
| `data/logs/<bot>.md` | one bot's work log |
| `data/routines.json` | the scheduled routines |
| `data/access_token` | the LAN token the phone app uses, minted once at mode 0600 |

You need a model that supports tool-calling. For `browser_see` you also want a vision model. Both are configured in `data/config.json` (`default_model`, `vision_model`). `vision_model` accepts a comma-separated list, and the first one that answers is used, so one rate-limited model cannot kill the tool.

## Desktop app

`desktop/build.py` packages the app for the machine it runs on, and `.github/workflows/build.yml` runs it on all three, so a tag builds everything at once. It needs PyInstaller (`pip install pyinstaller`) and Node on `PATH`; the first run also downloads Electron's toolchain with `npm install`.

```sh
python3 desktop/build.py              # the app for this OS, plus its disk image or archive
python3 desktop/build.py --no-browser # no bundled Chromium: ~10× smaller, no Computer panel
python3 desktop/build.py --no-dmg     # macOS: the .app without the disk image
```

What lands in `desktop/dist/`:

| OS | app | package |
|---|---|---|
| macOS | `Anzen-bot.app` | `Anzen-bot-<ver>.dmg` — drag to Applications |
| Windows | `Anzen-bot Setup <ver>.exe` | an installer (NSIS) |
| Linux | `Anzen-bot` | `Anzen-bot-<ver>.tar.gz` |

The app is Electron, and the build is two steps. Neither PyInstaller nor electron-builder cross-compiles, so a Windows `.exe` is built on Windows and a Linux build on Linux. PyInstaller freezes the Python side into one console binary, `anzen-backend`. electron-builder then wraps that binary and the web shell into the app, and the shell inside it is the same `index.html` and `app.js` the browser loads, unchanged.

Opening the app does not put it on localhost. There is no port at all: the window is loaded from disk, a `file://` page out of the install directory, and the renderer talks to the Electron main process over IPC. The main process proxies `/api/*` to the Python backend over a Unix socket — a file with a name, not a number to scan for, created mode `0600` inside the user's own application-support directory, so nothing on the machine or the network can dial it. The dev server (`python3 server.py`) is separate and stays open on loopback, on purpose, for development.

The launcher decides only what a packaged app has to decide for itself. Where its data lives: `~/Library/Application Support/Anzen-bot` on macOS, `%APPDATA%\Anzen-bot` on Windows, `~/.local/share/Anzen-bot` on Linux, never inside the bundle, which is read-only once installed and replaced wholesale by an upgrade (`DATA_DIR` overrides it). What window shows it: Electron's own Chromium, so the same engine everywhere and no second browser to ship.

`python3 desktop/anzen_app.py` runs the backend from source; `--sock PATH` gives it the same Unix socket the app uses, `--lan` also serves your wifi, and `--doctor` prints the directories it resolved.

## Phone

`android/` is a native Android client — Java and Android views, no WebView and no page. It talks to the same API the desktop window uses, over the same token, so the phone gets the same bots and the same chats without a browser in the middle.

```sh
python3 android/build_apk.py            # add --install to push it to a plugged-in phone
```

It builds without Gradle — `javac` → `d8` → `aapt2` → `zipalign` → `apksigner`, against the SDK's own build-tools — and signs with the standard debug key (`~/.android/debug.keystore`, generated if it is missing). The APK lands in `android/dist/`, `minSdk 24`. On the phone, paste the address the desktop app shows, or the whole link, which carries the token; the app lifts the token out, keeps both, and signs itself in, so the setup screen appears once.

What the phone draws is the conversation: the list of chats, a chat's saved transcript, and the turn you are in as it arrives — plans, tool calls, approvals with Allow and Deny, screenshots. A `plan`, `tool` or `approval` is machinery the server streams live and never writes down, so a chat opened later is the conversation and nothing else. Sending mid-turn is a steer, so a correction reaches the bot at its next step rather than waiting for the turn to end.

The parts that are not Android — the address parsing, the JSON, the folding of a turn's events into a transcript, and the HTTP and stream transport — are plain Java with no Android in them, and `python3 tests/test_android.py` runs them on this machine, because the machine that builds the APK has no phone attached to catch a wrong guess.

The phone is the one client that cannot use a socket, so turning it on is a deliberate act on the desktop: **Settings → Phone → Phone & tablet → Allow devices on this network**. That opens a separate TCP listener for the phone, reachable on your wifi behind a token (`data/access_token`, minted once at mode 0600) and closed to everything without it; with the switch off the server does not listen on the network at all, and the app's own window keeps working over its socket either way. `--lan` on the command line does the same and cannot be undone from the screen.

That listener is bound to this machine's LAN address, the same address the app hands you to type into the phone, and not to the wildcard, so it is never answered on `127.0.0.1`: even with the switch on, no port on this machine serves the app. If the machine has no LAN address, there is nothing for the phone to reach and the switch reads back as off.

## Development

### Layout

```
anzen-bot/
├── server.py            backend: HTTP + SSE, the agent runtime, tools, scheduler
├── index.html           the chat shell + all styling
├── app.js               UI logic: rooms, bots, settings, computer panel, voice
├── mochi.js             the canvas mascot engine (12 species, emotions, cursor gaze)
├── manifest.webmanifest PWA manifest (installable app)
├── sw.js                service worker (offline app shell)
├── icon-192.png · icon-512.png · icon-maskable-512.png · apple-touch-icon.png
├── run.sh               convenience launcher
├── config.example.json  a sample connection config
├── desktop/             the desktop app: anzen_app.py (the backend launcher), build.py,
│                        and electron/ (the Electron main process that owns the window)
├── android/             the native Android app and its Gradle-free APK builder
├── .github/workflows/   builds the .dmg, the .exe and the Linux archive, and releases a tag
├── tests/               the app gate, the offline suites and the browser suites
└── data/                created at runtime: config, bots, channels, sessions, memory, work logs, installed skills
```

### Tests

The gate is the app, not the browser. `tests/test_desktop_app.py` launches the built bundle, points it at a throwaway data dir and a stub router, and drives it over the app's own Unix socket: no browser, no dev server, no Playwright. It checks that the backend answers the API and nothing else (a request for `/` or `/app.js` is a 404 — those are the shell's, and the shell is Electron's), that the secret store is never served, that the roster and rooms can be created and deleted, and that a real chat turn streams. Then it launches the windowed app and proves the two things that define an app: the window loads the shell off the disk (`file://`) with the API carried over IPC, its chat streams, and the whole process tree opens no TCP listener at all.

```sh
python3 desktop/build.py              # build the app first — the suite tests the artefact
python3 tests/test_desktop_app.py     # the built app: no port, the API over its socket, the window
```

`ANZEN_APP=` aims it at a build elsewhere (`ANZEN_APP=source` runs it from source instead of the bundle) and `ANZEN_SKIP_WINDOW=1` skips the windowed launch (CI, which has no display, sets the latter; Linux needs `xvfb-run`). It asserts the real `data/` is byte-identical afterwards, so a run can never quietly cost you your roster.

Offline suites need no router and no browser:

| Suites | Covers |
|---|---|
| `tests/test_memory.py` · `tests/test_folders.py` | self-learning, skills and team import; per-room repo isolation |
| `tests/test_steer.py` · `tests/test_speed.py` | a mid-turn steer, and the session and settings caches with compaction |
| `tests/test_auth_doors.py` · `tests/test_backend_guards.py` · `tests/test_relay.py` | who may call the API, the tool-arg and connector and relay URL guards, and the phone relay over loopback |
| `tests/test_browser_brief_mode.py` · `tests/test_foreground.py` | the browsing line a bot is told matches the mode set, and the ZenPilot profile switch |
| `tests/test_android.py` | the phone app's non-Android parts, on a JVM |
| `node tests/test_mochi.mjs` · `tests/test_sound.mjs` · `tests/test_clock.mjs` | the mascot engine, the notification cues, and the long-step clock in `app.js` |
| `node tests/test_composer_ime.mjs` · `tests/test_fetch_helpers.mjs` · `tests/test_live_strip.mjs` · `tests/test_transcript_scroll.mjs` · `tests/test_name_colour.mjs` · `tests/test_tablist.mjs` | the composer's Enter-to-send IME guard, the `get()` helper, the room's live strip, following the newest message, transcript name colour, and Settings tab keyboard navigation |
| `node tests/test_service_worker.mjs` · `tests/test_bridge_blob.mjs` | shell caching and offline fallback, and the desktop image bridge blob lifetime |
| `tests/test_model_stall.py` · `node tests/test_notice_row.mjs` | the stall guard and retry policy when a router holds the connection open and sends nothing, and the transcript row dispatch that keeps a stop notice through a redraw |

Browser suites need `pip install playwright==1.61.0 && playwright install chromium`:

```sh
BASE=http://127.0.0.1:8093/ python3 tests/test_app.py   # browser, against a dev server
```

`tests/test_app.py` is the older browser suite. It drives a dev server in headless Chromium and is where the DOM-level checks live — layout, the mascot canvas, theme painting, click flows — that an API-level app test cannot reach: the shell, every settings section, bot and room create-edit-delete, the computer panel, a real multi-bot turn over SSE, mobile layout, team import, room logos, the theme packages, the font and text-size controls, the nested sidebar, Clear chat, switching chats mid-turn, queueing and steering, quoting and forwarding, zip skill installs, the per-bot faces, markdown rendering, the model and approval chips, the context chip and the work-log card, the notification sounds, the Plugins panel driving `tests/mcp_stub.py`, and the Browser card. It is optional and not the gate.

`tests/test_browser_card.py` and `tests/test_own_profiles.py` are the other two suites that need a real browser on the same Playwright install: the first drives the Browser card's account rows against a real server, the second launches a saved profile twice to prove a login survives the close.

## Security

- Shell commands run in a sandbox directory (`data`-sibling `sandbox/`), not your home, and a room with a Repo folder narrows that to the folder you name. The bots' file tools (read, write, list) are confined to it — `..` and absolute paths that escape are refused — but a shell command is not a jail: it starts there, and a `cd` or an absolute path can still leave it. Treat shell access as the real boundary and leave a bot on a low approval level unless you mean it. Risky commands are gated behind the approval card unless a bot is set to Full access.
- API keys are stored in `data/settings.json` (the router key in `data/config.json`) and are write-only to the UI, which only ever sees a configured flag. The static file server never serves the secret store: any path under the data dir answers 404, so a key can never be fetched as a file.
- Reaching the API from your wifi is off until you ask for it, and what it opens is guarded by a token — sent as `X-Anzen-Token` or the `anzen_pair` cookie, compared in constant time, with a same-origin check when a browser sends one. A loopback request is this machine's own page and needs no token. The desktop app does not go through this at all: it reaches the backend over a Unix socket, which nothing but the user running the app can open. The phone's link (`/?t=…`) only hands the cookie to a caller that also sends the token as a header, which a browser cannot do on a navigation.
- No credentials, conversations or memory are ever included in a shared team file.

## Notes and limits

- Bots run on your machine and your router, not a per-account cloud computer. The browser is headless and server-side; it is not desktop-GUI control of your own machine.
- Voice is the browser's own speech synthesis: offline, free, nothing sent to a server. There is no hosted voice option and no cloud key to set.
- The context budget is estimated from the request's size, roughly four characters a token, rather than counted with a real tokeniser, so it errs on the safe side.
- Routines have a working backend and no UI yet. They schedule a bot or a whole room on an interval or a cron expression, live in `data/routines.json`, and are reachable only through `/api/routine` and `/api/routine/delete`: no Settings tab creates or edits one. The scheduler is a background thread that ticks every 30 seconds and hands each due routine its own thread, so a long job never starves the tick.
- The phone half of a packaged macOS build needs the operating system's permission the first time the LAN switch goes on: an unsigned, un-notarized app is refused silently, with the phone timing out and nothing written to any log. The bundle declares `NSLocalNetworkUsageDescription` so macOS does the asking. A build meant for other people should be signed and notarized with a Developer ID. Running from source (`python3 server.py --lan`) is not affected.

## License

MIT. See [LICENSE](LICENSE).
