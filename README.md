# Anzen-bot

A self-hosted agent workspace you run on your own machine.
Your own team of bots, in a chat app — each with its own model, approval level,
memory, skills, tools, voice and look.

Give a room one goal. The bots work on it: a **Producer** (Chief of Staff) plans
and delegates, specialists do the work with **real tools** — a shell, files, and a
real browser they can see and click — and the Producer reports back. You approve
what matters, watch their live screen, and talk to any bot one-to-one.

Everything is **unlocked** — no tiers, no paywall, no subscription.

---

## What's inside

### A team of bots, as chats
- **Rooms** — each with its own transcript, member list, shared instructions and responder rule (lead / auto / everyone). Keep Work, Personal and each project apart without cloning your bots. Type **`@`** in a room's message box and its members drop down — name, role and avatar — so you can pick one instead of remembering who is in the room; the list filters as you keep typing, `↑`/`↓` move the highlight, and `Enter` (or `Tab`, or a click) inserts the name. The name it inserts is exactly what the server matches, so a picked mention always reaches its bot. A mention names only a room's own members, and a `@` in a 1:1 chat is just a character. A bot is told **its own current name and its room's current members** in every run rather than reading them from its brief, so **renaming a bot takes effect at once** — mention it by the new name and it answers, instead of denying a name its brief no longer matches.
- **One repo per room** — give a room a **Repo folder** and its bots run every shell command and file tool inside that folder only, so several repos never mix or get confused. The field is browsable: hit **Browse** to walk the disk a folder at a time instead of pasting a path (or type one). The room header shows the repo its bots are working in. A blank folder keeps the room on the shared folder, and a path that does not exist is refused at save time instead of silently falling back.
- **A bot inside a room is its own chat** — the sidebar nests each room's bots under it. Talking to a bot from inside a room opens a **1:1 chat scoped to that room**, so that bot's shell and file tools run in *that* room's repo. The same bot in two rooms is two separate conversations — `Webshop → Producer` works in the Webshop repo, `Mobile App → Producer` works in the Mobile App repo, and neither transcript or repo bleeds into the other. It is still the one bot you created: one face, one memory, one config. One click on a room opens it; a **double click folds its team** shut, and another pair opens it again — so a room you were not in both opens *and* unfolds on the double click. The caret on its own does the same fold in one click, and the fold is remembered. Bots in no room sit under the **Bots** section and keep the shared folder.
- **Each bot works in its own field, and keeps its own log** — a room hands a job to a bot; that bot then works **in its own folder** under the room's repo (`<repo>/<bot>`, created on first use), so two teammates never write over each other. The room is a **conversation**, so it carries what each bot *says* — the delegation (with the task it handed over), the acknowledgement, the answer to a steer, the report — and every one of those words is kept in the room's own transcript, so reopening it reads as the discussion rather than as a list of closing reports. The **steps** are a bot's own: the shell commands, file dumps, screenshots and step-by-step commentary land in **that bot's chat inside the room** (`<room>/<bot>`, created on first use), live while it works and kept afterwards — open it and you see what it ran, what that printed, and what it was thinking. A lead hands work **only to the members you added to the room** — the roster is every bot you have, not an invitation into this room, so a `delegate` naming anyone else is refused and the room is told why. Add a bot to the team before expecting it to be asked. Every turn a bot runs — direct chat or a delegation from a room — is appended to that bot's **work log** (`data/logs/<bot>.md`, last 400 lines), readable in Settings → Memory → **Work log**: what it was asked, what it actually did, which folder it worked in, and the report it gave back. A turn that fails writes nothing, so the log never fills with noise.
- **A logo per room** — a room's row shows a logo instead of two letters. It finds one by itself: if the room's **Repo folder** already has a logo (`logo.*`, `brand.*`, `icon.*` or `favicon.*`, at the root or in `public/`, `static/`, `assets/`, `images/`, `build/`, `resources/` …) that image is used — an Electron app's `build/icon.png` counts. Otherwise hit **Upload logo** in the room editor to use your own (png, jpg, webp, gif or svg, up to 2 MB); **Remove** hands the row back to the repo's logo, and with neither the initials come back. Uploads are checked by their bytes, not the filename, and an svg is refused if it carries script.
- **Switch chats mid-turn without losing the work** — a turn belongs to the chat it was started in, so switching to another room or bot while it runs neither empties the panel nor scatters the running turn's cards into the wrong transcript. The chat you left keeps drawing into its own place and its sidebar row stays lit; the chat you are looking at says **"<name> is working"** in the header. Come back and the plan, the tool cards and the running output are all still there. Each chat runs its own turn, so switching away leaves the work running.
- **Queue a task, or steer the one running** — you never have to wait for a turn to finish before typing the next thing. A task sent while one is already running is **held in a queue above the composer**, and the send box stays open. Leave it and it runs by itself the moment the turn ends — in the chat you queued it in, whether or not that chat is on screen. Or hit **Steer now** and the running turn is handed it instead, so the bot changes direction mid-task rather than finishing and starting over; a steered task reaches the bot at its **next step** — after the command it is running now, not in the middle of it — and is kept in the transcript like any message you type. **×** takes a task back out: nothing was sent, so nothing is undone. The queue is per chat, so a task queued in one conversation is never steered into another's turn.
- **Quote a message, or forward it** — every message has two small buttons, **Reply** and **Forward** (on hover on a desktop, always visible inside the bubble on a touch screen). **Reply** quotes that message: the quote waits above the composer, travels with the next task, and is drawn over it in the transcript. The bot is told what you are replying to, because it never sees the transcript — so “make it shorter” points at the message you meant. **Forward** sends a copy of the message to another chat you pick from a list of your rooms and your chats; it arrives there marked **Forwarded** and is picked up as a task, exactly as if you had typed it. Both marks are kept with the message, so reopening a chat draws the quote and the forward mark back where they were.
- **Bots as contacts** — right-click any bot to pin, edit, duplicate, hide or delete it. Add new bots with their own name, title, colour and standing instructions. Each bot gets an animated face of its own in the sidebar.
- **Clear chat — a new session without the amnesia** — the row menu of any bot or room (the **⋯** on the row, or right-click) has **Clear chat**. It empties that chat's transcript, like starting a fresh session, and **keeps the bots' memory**: a bot's notes (`data/memory/<bot>.md`) and its work log are not part of a session, so the next chat picks up knowing what the project is about — you only lose the conversation, never what they learned. It is per chat, so clearing `Webshop → Producer` leaves its chat under Mobile App alone, and the chat's own model pick and approval level survive too, so clearing can never quietly loosen a chat you set to Plan only. It asks first, and it is refused while a turn is still running in that chat — let the turn finish or answer its card, so a reply in flight cannot land in the transcript that replaced it. **Delete** is the other thing entirely: that removes the bot or the room.
- **Import a team from BotMRR** — Settings → Bots → **Import a team**. Paste a team copied from [botmrr.io](https://botmrr.io/) and every agent becomes its own bot, keeping its distinct **name** and **position** (Lea — Producer, Alex — UI, Dima — Dev …), its colour, and the shared **room** with its members and lead. A plain list like `Lea — Producer` works too. Colours off the six-colour palette are mapped to the nearest one.

### Real work, not a text protocol
Bots run on **real tool-calling** (the standard OpenAI `tools` API). Their tools:
- `run_shell` — run a command in a shared folder
- `read_file` / `write_file` / `list_files` — work with files
- `browser_open` / `browser_read` / `browser_click` / `browser_type` / `browser_press` / `browser_back` / `browser_eval` — drive a **real Chromium** (`browser_eval` runs one JavaScript expression in the page, for what click and type cannot express)
- `browser_see` — screenshot the page and **look at it** with a vision model
- `browser_save` — wait for the picture/video a site just produced, download it, show it in the chat
- `generate_image` — draw a picture through the API router. **Off by default**: it spends your API tokens. The default route is free (see below).
- `memory_update` — write a durable note to the bot's memory
- `delegate` — hand a task to a teammate and get their report

**Choosing a bot's tools.** The bot editor's **Tools** section has two modes: **All current tools** (the bot's default set — every tool above, except that the lead bot starts with `delegate`, `memory_update`, `use_skill` and `finish`, since a coordinator plans rather than runs commands) or **Custom selection**, which opens a tick-list of every tool with a one-line explanation of each. The list is built from the server's own tool table (`/api/config`), so it can never offer a tool the server cannot actually run. A connected app adds its tool to the list too. Fewer tools help a small-context model stay on track; the choice is saved with the bot.

### Reading the chat
- **A bot's reply is rendered, not dumped** — headings, **bold**, *italic*, ~~strikethrough~~, `inline code`, fenced code blocks, bullet and numbered lists, blockquotes, rules, links and **tables** all come out as real elements, so a report reads like a report. Everything is escaped before it is parsed, so a reply containing raw HTML or a `<script>` shows the text and cannot inject markup, and a link that is not `http`/`mailto`/relative (`javascript:` and friends) is made inert. Your own message is never parsed — a shell command you type arrives exactly as typed.
- **Switch the model on the spot** — the chip at the top of a chat names the model that will actually answer it: the one you picked for that chat, else the model set on the bot (a room uses its lead's), else the default. Click it for a searchable list of every enabled model and pick one — the chat switches at once, and the choice is remembered for that chat only. *Each bot's own model* in the same menu clears the override.
- **Set the approval on the spot** — the **Approval** chip beside it names what the current chat may do without asking, and clicking it lists the levels to pick from, in place. It does **not** open the Bots list. **In a room, the room's level is the only level**: a room is one team with one rule, so the menu sets the room's level and lists no per-member pickers — a member's own default is neither used nor shown there, and a bot's own level is set where the bot is, in Bots → Approval level. **In a 1:1 chat** the menu offers that bot's levels, and the chip says **which level is in force** — the chat's own, or the bot's default it is following — leading with **Use the bot's own level** when the chat has one of its own, so a level set here once is never a trap.
- **A card that waits as long as you do** — a turn streams to the browser over one long-lived connection, and a turn can go quiet for a while: a slow model, a long command, or an approval card you have not answered yet. An idle connection that long is dropped by the browser or the network in between. The stream sends a keepalive every 15 seconds while a turn has nothing to say, so the connection stays open and the card stays answerable however long you leave it. If the connection does drop anyway, the chat says what happened **in words** rather than echoing the browser: a turn that never reached the server says so and invites a retry, one that died part-way through says the bot may still be working on it, and a failure **inside** the turn — a model or a tool that threw — is reported the same way instead of ending as a silent stop.
- **Context that never overflows** — every model has a window, so a long run is compressed instead of erroring: the oldest steps are dropped to fit, the system prompt is kept, and the chat says so ("compressed N earlier steps …"). The budget follows the model's own known window by default, and **AI model → Context limit** overrides it (0 = follow the model). Compression can be switched off there if you would rather the request fail loudly.
- **See what filled the window** — the **ctx** chip at the top of a chat says how full that chat's context window is (`ctx 76%`), and **hovering it** opens the split: the used and total counts, a stacked bar filled to the same fraction, and a row per part with its share — the transcript, the tool schemas the bot was given, the tools from Connected apps, the tools from your MCP servers, the system prompt, the skills it carries, and the memory and team context folded in. The numbers are **measured, not guessed**: the app measures the prompt in the pieces it actually composes it from, and the provider's own `prompt_tokens` for that very request is the number at the top, with the rows scaled onto it so the shares still add up. A footer gives the chat's **average cache hit rate**, accumulated across its turns. There is an **MCP tools** row because the app really speaks MCP: the tools from the servers you added under Settings → Plugins, alongside the **Connected apps** row and the bot's own tools. The chip warms at 75% and turns red at 90%, so a window about to run out is visible before it bites. It is per chat, survives a reload, and starts over with **Clear chat**. Hovering is the fast path; a click opens it too, for touch and the keyboard.

### Computer panel
Open a bot's **Computer** to watch its live screen (a screenshot of the real
browser), and point it at any page.

### Where the bots browse
By default each bot drives its own headless Chromium. Point **Browser** at a browser you
are already running (ZenPilot, or any Chromium started with `--remote-debugging-port=9222`) and the
bots **attach over CDP instead of opening a window** — they reuse the profiles you are already logged
into, so there is no extra browser and no login wall.

ZenPilot shows every profile as an Electron `<webview>`, which Playwright cannot see, so for those the
server speaks the DevTools Protocol itself (stdlib only) and drives the profile directly. **Which
profiles?** takes one or more URL fragments (comma-separated) — list `gemini.google.com, openart.ai`
and the bots open each site in the profile logged into it, hopping between them as they go; leave it
empty and they use the first profile you have open. One attach reaches every profile ZenPilot holds,
so nothing is ever logged in twice.

Give the card the **debug port** and that is the only number to get right: the bots connect to
`http://127.0.0.1:<port>`, and **Launch ZenPilot & connect** opens ZenPilot on that *same* port
(`open -a "Zen Pilot" --args --remote-debugging-port=<port>`, built from the port rather than stored),
waits for it to answer, and attaches. There is no separate launch command and no separate CDP URL to
keep in step — the endpoint is derived from the port, so the app cannot connect to a port the launch
never opened. **Test connection** saves the port and reconnects to a browser that is already running.
Opening the app for you is macOS-only; elsewhere start your browser with `--remote-debugging-port=<port>`
yourself and press **Test connection**.

**Import profiles** skips the typing: it asks ZenPilot which profiles are open right now, lists each
one by the site it is signed into, and lets you tick some or all of them into the pin field in one
click. When ZenPilot is not installed, the card says so (it looks in `Applications` rather than
guessing) and links to where to get it — and if ZenPilot is installed but not running, the status line
names the button that fixes it instead of showing a raw connection error.

### Free image & video (no API tokens)
Sites like Gemini, Google Flow, OpenArt and Dola give you a quota you already have. The bots spend
that instead of your API key: `browser_open` the site → `browser_type` the prompt → `browser_click`
→ `browser_save`, which waits for the result and drops it into the chat. The paid router route
(`generate_image`) is still there but stays **off by default**: it is gated on `media.router_image`,
which nothing in the UI writes, so turning it on means setting it to `true` in `data/settings.json`.

### Approval cards
A risky shell command surfaces as an inline **Allow / Deny** card before it runs. Commands on a
small read-only allowlist (`ls`, `cat`, `grep`, `git status`, …) run straight through, as do file
writes and questions.
Choose an approval level, per bot (Bots → Approval level) or per chat (the **Approval** chip in the header). Inside a room the room's level is the one that runs; a bot's own level applies only in a chat with that bot on its own.
- **Plan only** — read-only tools only (read a file, list files, open a page, read it, look at it): no shell command, no writing, no image, no delegation, no connected apps. The bot investigates and reports a plan, then stops. The plan arrives with an **Approve plan and run it** button, which switches that chat to full access and runs the plan. The strictest level: nothing happens until you say go.
- **Ask for approval** — every tool is available; a shell command that is not a plain read-only one raises a card and the bot waits. File writes, browser actions, image generation, delegation and connected apps run without a card, so today the card covers risky shell commands only
- **Auto-accept edits** — as Ask today; file writes are not gated yet
- **Approve routine** — as Ask today
- **Full access** — no card is ever raised; every tool the bot has (shell, files, browser, image, delegation, connected apps, MCP servers) runs straight away

Every level but Full is gated the same way, so there is no Custom level.

**Which level actually runs.** A bot has its own level (Bots → Approval level), and a chat may carry a level of its own. **In a room the room's level is the only level** — a room is one team with one rule, so the level set on the room runs for every member, and a member's own default is neither used nor shown there (a level picked from a member's row is written to the room, so the room row and the member row cannot disagree). **In a 1:1 chat** the chat's own level governs if it has one, otherwise the bot's own default. The **Approval** chip always says which of the two is in force, so they can never quietly disagree: **`Approval: Plan only`** means the chat has its own level, and **`Approval: Full access · bot default`** (a 1:1 chat only) means it is following the bot. In a 1:1 chat with a level of its own, the menu leads with **Use the bot's own level**, which hands the chat back to the bot's default. That way back is the point: without it, a level picked on a chat once would be permanent and silent, so a bot set to Full access could keep asking for approval with nothing on screen to say why. A room's menu says **What may run in this room** above the levels, because that level is what runs for every member until it is changed.

### Layered settings (14 sections)
**General · AI model · Browser · Phone · Bots · Rooms · Connected apps · Skills · Plugins ·
Memory · Approvals · Voice · Appearance · Help**
- **Help** — the tutorial and the reference, in the app rather than in this file. A jump list over twenty-two sections: the idea (bot / room / chat), talking to a bot, quoting and forwarding, queued tasks and steering, the header chips and the computer button, **the approval levels and exactly what each one reaches**, the tool catalogue, Bots, Rooms, AI model, Browser, Memory, Skills, Plugins, Connected apps, Voice and sound, Appearance, General, the sidebar and dock, the keyboard, installing as an app, and phone and tablet. Every list on the page is built from the constant the app itself runs on — `APPROVALS` for the levels, the server's own tool list for the tools, `S.skills` for the skills — so a feature cannot be added and left undescribed, and the words cannot drift from the behaviour. Reachable from the **Help** button above Settings in the sidebar, or the last tab in Settings. The **Approvals** tab renders the same per-level detail from the same one definition.
- **General** — the app-wide switches: the workspace name, reading replies aloud automatically, auto-routing an un-mentioned room message to a fast model, and **notification sounds**. A short chime plays when a turn **finishes**, when it **fails**, when it **stops to ask you something** (an approval or a question), or when it is **rate-limited**, so you can hear the bot from another window. Each of the four has its own cue — rising for done, falling for error, a lifted pair for a question, and a short limit cue — and they are **synthesised in the browser**, so there is no audio file to ship, fetch or license. The middle of a turn stays silent on purpose: a chime per state change would be a metronome. Browsers only allow sound after a real interaction, so nothing is audible until you click or type once; the volume slider previews the cue when you let go, and **0** is the same as off.
- **AI model** — where a bot's brain runs. The **Connection** card names the [OI]-compatible router every bot talks to (paste your own URL and API key; the key is stored server-side and never shown again). The **Models** card under it manages the list: hit **Detect all models from the API key** to pull every model the configured key can reach (460 on a full router), add an id by hand, filter, and remove. A long list shows a dozen rows at a time with a **Show all** count, so it stays scannable instead of burying the cards below it. Every model in that list is selectable per bot — the bot editor's MODEL field opens a list you can scroll and filter, in place rather than a floating menu (the settings panel scrolls, so a floating one would be clipped). It is a list you open, **not** a native autocomplete that only reveals its options while you type, which is why **Detect all models** now visibly refills it — the count it reports is the list you are looking at. An id the router does not list can still be typed and chosen, so a hand-entered model is never a dead end. The **Context** card sets the token budget for one request (**0** follows the model's own window) and whether a run that outgrows it is compressed rather than failing, and **Image generation** lists the image-capable models the key can reach and lets you pick the one bots draw with (video is reported honestly as unavailable when the key has none). Router image drawing is **off by default** — the free web route is the default.
- **Browser** — where the bots browse, and the logins they keep. The box offers three ways, and the line under it describes the one you picked rather than all three at once: **own browser** (a fresh browser each time — fast and private, nothing logged in), **saved profiles** (one browser per account, logins written to disk), or **ZenPilot / any browser over CDP** (reuses the profiles you are already signed into — give it the debug port and the button opens ZenPilot on it). Under it, one row per account: a name, the sites the bots should use it for, and a **Sign in** button that opens that row's first site in its own window — the row's own site, not the account's, so two rows sharing a name still each open where they say. Log in once there, then **close that window** — closing is what writes the login to disk — and the row turns to **Signed in**. That word is read from the site's own sign-in cookie, not from the folder existing, so it never claims a login that did not happen; a site that leaves no readable cookie says so plainly instead. A row's browser is the folder its logins live in, so two rows cannot share one: a second name that points at the same folder — the same name again, or one differing only in case — is marked as that same browser instead of being shown the login it did not earn. Only the sites you list for an account ever see its cookies — anything else is read anonymously, in a throwaway browser. **Browser** picks which browser those windows are: **Automatic** uses a Chrome really installed on this Mac, and that matters, because Google refuses to sign anyone in on the Chromium we ship.
- **Phone** — reach this app from the phone in your pocket. **Phone & tablet** is the LAN listener the Android app talks to: off by default (so nothing outside this computer can reach the API), turned on by a switch, and guarded by a token, so only a device you have set up can use it. The card shows the address and the token, with a button that copies the whole link. **From anywhere** is the relay card beside it: it makes the phone work on cellular or hotel wifi by having this app and the phone both dial out to a relay that joins the two, so nothing is opened on this computer and no router is touched.
- **Memory** — each bot keeps plain-markdown notes (`data/memory/<bot>.md`); the first 200 lines load into every turn — chat, rooms and delegations alike. Bots **self-learn**: after a run that used real tools they reflect once on their own work and append the durable facts, working commands and gotchas they discovered, so the next session starts smarter without being told. Turn the per-bot **memory** switch off to stop both reading and learning. The file is capped at 400 lines, keeping the header and the newest notes. Under it, the **Work log** card shows that bot's own log — every turn it ran, direct or delegated, read-only.
- **Skills** — reusable capabilities you switch on per bot (Settings → Skills, or the bot editor). Each enabled skill is an **index line in the prompt, not a briefing**: the bot reads one on demand with `use_skill` when it decides the skill covers the job, which is what keeps a 43-skill shelf from costing more context than the work itself. The built-ins ship real guidance, not just a name: **Web browsing** is the recipe for driving a real site in few steps (go by URL rather than clicking a search box, pull a whole list out with one `browser_eval` instead of many reads, poll inside the eval rather than guessing that an empty read means an empty page), and **Research** is how to answer a question with sources and evidence. **Install from a zip**: a zip holds one folder per skill, each with a `SKILL.md` whose frontmatter names and describes it — and it may hold **several**, so one zip is not one skill. Uploading **scans the zip and installs nothing yet**: you get a list of what is inside, each with its description and how many files it brings, all ticked, and you untick what you don't want and press **Install selected**, or **Install all**. A skill that would land on top of one you already have is marked *replaces installed*. Whatever you install brings its whole folder along — bundled scripts and references included — and its `SKILL.md` guidance is what that bot reads when it reaches for the skill. A zip never overwrites a built-in skill. A zip may be up to **25 MB** (the upload is refused with a message past that, and so is any single skill over 200 files / 2 MB). The list has a **search box** and a filter — **Recently installed**, **Installed from zip**, **Built-in**, **On for this bot** — so a growing collection stays findable, and an installed skill has a **Remove** button that uninstalls it and switches it off everywhere.
- **Plugins** — MCP servers your bots can use, for real. Add a server by **the command that starts it** (a local one, spoken to over a pipe — the stdio transport) or by **its URL** (a remote one, over Streamable HTTP, falling back to the older HTTP+SSE transport when the server only speaks that). **Test** connects it now and reports the tools it offers, or why it would not come up — a server that will not start says why here rather than failing silently inside a turn, and a server that just failed is not retried on every turn. Once connected, every tool a server offers becomes a real tool for every bot, named `mcp__<server>__<tool>` so two servers can both have an `echo` without colliding. Env vars (for a local server) and headers (for a remote one) are stored **write-only**, like every other credential here: the panel is told only that they are set, never their values, and a save that carries none keeps the ones already stored. **Switch off** keeps a server on the list but stops offering its tools; **Remove** takes it and its connection away.
- **Connected apps** — connect an app (GitHub, Slack, Notion, Linear, Gmail, Drive, Calendar, Webhooks) and **every bot gains a real tool** that calls that app's API — read issues, post messages, search pages, fire webhooks. Credentials are stored write-only (the UI only ever sees a connected flag, never a secret); a per-app **Test** button calls the real API to verify, and a refusal comes back as a sentence naming the cause rather than a raw error body. Each app declares how its credential is sent, so nothing is a special case in the request builder: GitHub, Slack and Notion take a bearer token; **Linear** takes a personal API key sent as-is (no `Bearer` prefix); **Gmail, Drive and Calendar** use OAuth, because a Google access token dies within the hour. For those three, create an OAuth client of type **Desktop app** in the Google Cloud console and take a **refresh token** from the [OAuth Playground](https://developers.google.com/oauthplayground) (gear icon → *Use your own OAuth credentials*), then paste the client id, client secret and refresh token. The access token is minted and renewed for you. Note a refresh token from a consent screen still in **Testing** mode expires after 7 days.
- **Voice** — read bot replies aloud with the browser's built-in voices. No cloud key, nothing sent to a server.
- **Appearance** — eleven theme packages, an accent colour, density, **font** and **text size**. A theme is a whole look, not a switch: **Dark** and **Light**, **Liquid Glass** (chrome becomes a blurred translucent pane over a slow iridescent wash; the transcript stays solid so text is never read through a blur) and its light twin, **AI-Native UI** (a neutral base and one accent, with context surfaces marked by the same left rule the approval cards use) and its light twin, **Dark Luxe** (deep graded indigo, metallic gold, panels that float on a long shadow), **E-Ink / Paper** (paper and ink, a serif reading face, no motion, a faint grain), **Terminal Hacker** (phosphor green on black, monospace throughout, a scanline and a phosphor caret) and **Monochrome** (one grey ramp with the accent kept for the live dot, the chat you are in and the primary button) and its light twin. Picking a theme adopts its signature accent; the colour field below is where you take it back, and re-picking the theme you are already on leaves your accent alone. The accent previews as you pick and saves with its **Save** button; it tints the primary button, the live dot and your own messages, and the label on that button always gets whichever of black or white reads better on it. The font picker offers eighteen faces — System, ZCode (the face the ZCode editor itself renders in), Rounded, Avenir, Helvetica, Futura, Optima, Gill Sans, Trebuchet, Wide, Serif, Georgia, Palatino, Didot, Charter, Mono, SF Mono (ZCode's code face) and JetBrains Mono — each one already on your machine, so nothing is downloaded and it works offline, and every stack carries a generic family so a missing face falls back to the right kind of type rather than to the browser's default — code and tool output keep their monospace face whatever you choose. Text size is a real size in px (12.5 to 18.5) rather than a coarse multiplier: every piece of text in the interface is its own designed size times that base, so the whole thing scales together and keeps its proportions. A save from before this change stored a multiplier, and is converted to the size it meant on first load.

### Routines
Schedule a bot (or a whole room) on an **interval** or a **cron** expression.
The scheduler is a background thread that ticks every 30 seconds and hands each due routine its own
thread, so a long job never starves the tick. **The backend is in place but there is no UI for it
yet**: routines live in `data/routines.json`, `/api/routine` and `/api/routine/delete` are the
endpoints, and no Settings tab creates or edits one.

### Bot faces
Every bot has its own animated face in the sidebar — a canvas creature with a
body shape, ears, eyes and a way of idling that are picked from the bot's id, so
a team looks like a team without anyone configuring it. Twelve species ship
(Mochi, Cat, Bunny, Owl, Frog, Ghost, Robot, Alien, Imp, Bean, Blob, Star); the
eyes track your cursor, the ears lag behind a hop, and the face wears the bot's
colour. Open a bot in **Settings → Bots** to pick its species by hand — there is
a live preview next to the picker.

The colour and the grading are both Coucou's, so a team here reads like the same
team there. The six colours are its own agent palette (purple `#7C5CFF`, blue
`#38BDF8`, green `#2EC4A0`, orange `#F29B38`, yellow `#EAB308`, pink `#EC4899`),
and a small face is painted the way Coucou paints a mini bot: **one flat fill of
that colour** — no gradient, no white wash, no highlight. That is what keeps a
46px row saturated instead of pastel. The big dock face is the one exception: it
keeps Coucou's soft body, lit from the top, because the soft body is where the
state lives — the working and searching tints have nowhere to go on a flat fill,
so a flat dock would stop telling you what the bot is doing. The colour is still
the bot's own, only the shading differs.

The motion is a keyframe tween system ported from Coucou: every movement is a
list of `{target, duration, ease}` keys with `out` / `inOut` / `back` curves,
the body and the gaze settle at two different rates, the ears and antenna ride a
damped spring so they ring behind the head, and the eyes are placed on a
projected cylinder — so they swing, foreshorten and slip past the silhouette as
the head turns, instead of sliding across a flat face. The face is split into
two bands, eyes above and mouth below, and the eyes ease into the gap rather
than crossing it — so however far the gaze swings, it never lands in the mouth.

### The mascot
A little canvas mascot lives in the bottom-right dock. It wears the face of the
bot you are talking to — same species, same colour as that bot's sidebar row —
so the corner always tells you who is speaking. Open a room and it falls back to
the general Mochi, since a room is a whole team with no single face. Click to
**poke** it (it hops — the state does not change), hover to see what it is doing,
and its eyes follow your cursor. It wears an emotion to match what it is doing —
curious while thinking, worried when a turn needs approval, happy when one lands.
A bot that is busy looks where its work is, not at your mouse: working stares at
its desk, thinking looks up, sleeping is asleep. The cursor only leads a face that
has nothing better to look at.

### Installable app (PWA)
Anzen-bot is a **progressive web app**. Open it in a browser and use
**Install app** (or the browser's own install control) to add it to your desktop
or phone home screen — it then runs in its own window, offline-capable for the
app shell, with a proper icon. No store, no build step.

---

## Run it

Requires **Python 3.9+**. The server is stdlib-only; the browser tool needs
Playwright (optional — everything else works without it).

```sh
git clone https://github.com/Sanxdy/anzen-bot.git && cd anzen-bot

export ROUTER_URL="http://127.0.0.1:11434/v1"   # any OpenAI-compatible endpoint
export ROUTER_KEY="sk-..."                       # optional
export DEFAULT_MODEL="your-model"                # a model that supports tool-calling
export VISION_MODEL="your-vision-model"          # for browser_see (optional)
export PORT=8093

python3 server.py
# open http://127.0.0.1:8093
```

`run.sh` does the same with sensible defaults. On first run the server writes
`data/config.json` from those env vars — edit it afterwards to change the router,
key or models.

It also writes `data/bots.json` and `data/channels.json`, seeding one room called
**Company** with five bots already on the team — **Producer** (Chief of Staff),
**Researcher**, **Builder**, **QA** and **Ops** — so a fresh install opens on a
working team instead of an empty sidebar. From that point on they are ordinary
records: rename them, re-brief them, add your own, or delete them.

### Optional: the browser tool (computer use)
```sh
python3 -m venv .venv && . .venv/bin/activate
pip install playwright==1.61.0
playwright install chromium            # or reuse existing browsers via PLAYWRIGHT_BROWSERS_PATH
python server.py
```

### Models
You need a model that supports **tool-calling**. For `browser_see` you also want a
**vision** model. Both are configured in `data/config.json` (`default_model`,
`vision_model`). `vision_model` accepts a comma-separated list — the first one that
answers is used, so one rate-limited model can't kill the tool.

---

## Desktop builds

`desktop/build.py` packages the app for the machine it runs on, and `.github/workflows/build.yml`
runs it on all three, so a tag builds everything at once.

```sh
python3 desktop/build.py              # the app for this OS, plus its disk image or archive
python3 desktop/build.py --no-browser # no bundled Chromium: ~10× smaller, no Computer panel
python3 desktop/build.py --no-dmg     # macOS: the .app without the disk image
```

It needs **PyInstaller** (`pip install pyinstaller`) and **Node** on `PATH`; the first run also
downloads Electron's toolchain with `npm install`. What lands in `desktop/dist/`:

| OS | app | package |
|---|---|---|
| macOS | `Anzen-bot.app` | `Anzen-bot-<ver>.dmg` — drag to Applications |
| Windows | `Anzen-bot Setup <ver>.exe` | an installer (NSIS) |
| Linux | `Anzen-bot` | `Anzen-bot-<ver>.tar.gz` |

The app is **Electron**, the same shape as ZCode, and the build is two steps. Neither PyInstaller nor
electron-builder cross-compiles, so a Windows `.exe` is built on Windows and a Linux build on Linux.
**PyInstaller** freezes the Python side into one console binary, `anzen-backend` — console, because
this process has no window of its own and has to be able to write to the log. **electron-builder**
then wraps that binary and the web shell into the app, and the shell inside it is the same
`index.html` and `app.js` the browser loads, unchanged.

**Opening the app does not put it on localhost.** There is no port at all: the window is loaded
**from disk** — a `file://` page out of the install directory — and the renderer talks to the Electron
main process over **IPC**. The main process proxies `/api/*` to the Python backend over a **Unix
socket**. Nothing on the machine or the network can dial that socket — it is a file with a name, not
a number to scan for, and it is created mode `0600` inside the user's own application-support
directory. The dev server (`python3 server.py`) is separate and stays open on loopback, on purpose,
for development.

The launcher decides only what a packaged app has to decide for itself. **Where its data lives** —
`~/Library/Application Support/Anzen-bot` on macOS, `%APPDATA%\Anzen-bot` on Windows,
`~/.local/share/Anzen-bot` on Linux, never inside the bundle, which is read-only once installed and
replaced wholesale by an upgrade (`DATA_DIR` overrides it). **What window shows it** — Electron's own
Chromium, so the same engine everywhere and no second browser to ship.

`python3 desktop/anzen_app.py` runs the backend from source; `--sock PATH` gives it the same Unix
socket the app uses, `--lan` also serves your wifi, and `--doctor` prints the directories it resolved.

### The phone app

`android/` is a native Android client — Java and Android views, no WebView and no page. It talks to
the same API the desktop window uses, over the same token, so the phone gets the same bots and the
same chats without a browser in the middle.

```sh
python3 android/build_apk.py            # add --install to push it to a plugged-in phone
```

It builds without Gradle — `javac` → `d8` → `aapt2` → `zipalign` → `apksigner`, against the SDK's
own build-tools — and signs with the standard debug key (`~/.android/debug.keystore`, generated if
it is missing). The APK lands in `android/dist/`, `minSdk 24`. On the phone, paste the address the
desktop app shows, or the whole link, which carries the token; the app lifts the token out, keeps
both, and signs itself in, so the setup screen appears once.

What the phone draws is the conversation: the list of chats, a chat's saved transcript, and the turn
you are in as it arrives — plans, tool calls, approvals with Allow and Deny, screenshots. A `plan`,
`tool` or `approval` is machinery the server streams live and never writes down, so a chat opened
later is the conversation and nothing else. Sending mid-turn is a steer, so a correction reaches the
bot at its next step rather than waiting for the turn to end.

The parts that are not Android — the address parsing, the JSON, the folding of a turn's events into
a transcript, and the HTTP and stream transport — are plain Java with no Android in them, and
`python3 tests/test_android.py` runs them on this machine, because the machine that builds the APK
has no phone attached to catch a wrong guess.

The phone is the one client that cannot use a socket, so turning it on is a deliberate act on the
desktop: **Settings → Phone → Phone & tablet** → **Allow devices on this network**. That opens a
*separate* TCP listener for the phone — and only then — reachable on your wifi behind a token
(`data/access_token`, minted once at mode 0600) and closed to everything without it; with the switch
off the server does not listen on the network at all, and the app's own window keeps working over its
socket either way. `--lan` on the command line does the same and cannot be undone from the screen.

That listener is bound to this machine's **LAN address** — the same address the app hands you to type
into the phone — and not to the wildcard, so it is never answered on `127.0.0.1`: even with the
switch on, no port on this machine serves the app. If the machine has no LAN address, there is
nothing for the phone to reach and the switch reads back as off.

---

## Layout

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
├── tests/test_app.py    end-to-end checks (Playwright)
├── tests/mcp_stub.py    a real MCP server (stdlib) the suites drive the client against
├── tests/test_desktop_app.py  app-level checks: launches the built app itself, no browser
├── tests/test_memory.py offline checks: self-learning, skills, team import
├── tests/test_folders.py offline checks: per-room repo isolation
├── tests/test_steer.py  offline checks: a mid-turn steer reaches the bot, and one that cannot lands in the caller's queue
└── data/                created at runtime: config, bots, channels, sessions, memory, work logs, installed skills
```

The shell is a two-column CSS grid: the sidebar is a grid **column**, not a flex sibling, so folding it to a rail is one `grid-template-columns` change and the transcript takes the width back on its own. The fold is a real button that reports its state (`aria-expanded`) and is remembered across reloads; below 900px the sidebar becomes a drawer instead and the rail control is hidden, because a drawer is opened in order to be read. The markup is semantic — `<aside>` for the sidebar and the computer panel, `<nav>` for the rooms and the settings rail, `<main>` holding a `<section role="log">` transcript and a `<footer>` composer — and the settings dialog is a real `role="dialog"` with a `role="tablist"`. The lists of cards (Bots, Rooms, the approval levels) are bento grids of tiered cards: the head names it, the body carries the facts as labelled metrics, the foot carries the verb. The long editors group their fields into titled sections — Identity / Look / Brain / Skills / Tools for a bot, Basics / Members / Repo & notes for a room — so no screen is one undivided column of inputs.

---

## Tests

**The gate is the app, not the browser.** `tests/test_desktop_app.py` launches the built bundle —
the thing that actually ships — points it at a throwaway data dir and a stub router, and drives it
over the app's own Unix socket: no browser, no dev server, no Playwright. It checks that the backend
answers the API and *nothing else* (a request for `/` or `/app.js` is a 404 — those are the shell's,
and the shell is Electron's), that the secret store is never served, that the roster and rooms can be
created and deleted, and that a real chat turn streams. Then it launches the windowed app and proves
the two things that define an app: the window loads the shell **off the disk** (`file://`) with the
API carried over **IPC**, its chat streams — and the whole process tree opens **no TCP listener at
all**, so nothing on the machine can reach it. Run it after any change:

```sh
python3 desktop/build.py              # build the app first — the suite tests the artefact
python3 tests/test_desktop_app.py     # the built app: no port, the API over its socket, the window
python tests/test_memory.py           # offline, no router: self-learning, skills, team import
python tests/test_folders.py          # offline, no router: per-room repo isolation
python tests/test_steer.py            # offline, no router: a mid-turn steer
python tests/test_speed.py            # offline, no router: the session/settings caches, and compaction
python tests/test_auth_doors.py       # offline, no router: who may call the API
python tests/test_backend_guards.py   # offline, no router: tool args, connector/relay URLs, tombstones
python tests/test_relay.py            # offline, no router: phone -> relay -> this app, over loopback
python tests/test_browser_brief_mode.py  # offline: the browsing line a bot is told matches the mode set
python tests/test_foreground.py       # offline: the ZenPilot profile switch, against a stand-in DOM
python tests/test_android.py          # offline: the phone app's non-Android parts, on a JVM
node tests/test_mochi.mjs             # offline, no browser: the mascot engine
node tests/test_sound.mjs             # offline, no browser: the notification cues
node tests/test_clock.mjs             # offline, no browser: the long-step clock in app.js
node tests/test_composer_ime.mjs      # offline, no browser: the composer's Enter-to-send IME guard
node tests/test_fetch_helpers.mjs     # offline, no browser: the `get()` helper and its callers
node tests/test_live_strip.mjs        # offline, no browser: the room's live strip in app.js
node tests/test_transcript_scroll.mjs # offline, no browser: following the newest message, and staying put
node tests/test_name_colour.mjs       # offline, no browser: transcript name colour and its contrast
node tests/test_tablist.mjs           # offline, no browser: Settings tab keyboard navigation
node tests/test_service_worker.mjs     # offline, no browser: shell caching and offline fallback
node tests/test_bridge_blob.mjs        # offline, no browser: desktop image bridge blob lifetime
python tests/test_browser_card.py      # browser: connected account rows
python tests/test_own_profiles.py      # browser: saved-profile persistence
```

`ANZEN_APP=` aims it at a build elsewhere (`ANZEN_APP=source` runs it from source instead of the
bundle) and `ANZEN_SKIP_WINDOW=1` skips the windowed launch (CI, which has no display, sets the
latter; Linux needs `xvfb-run`). It asserts the real `data/` is byte-identical afterwards, so a run
can never quietly cost you your roster.

`tests/test_app.py` is the older browser suite: it drives a **dev server** in headless Chromium and
is where the DOM-level checks live — layout, the mascot canvas, theme painting, click flows — that
an API-level app test cannot reach. It is optional now and not the gate; run it against a running
server when you are working on the interface:

```sh
pip install playwright==1.61.0 && playwright install chromium
BASE=http://127.0.0.1:8093/ python tests/test_app.py   # browser, against a dev server
```

`tests/test_browser_card.py` and `tests/test_own_profiles.py` are the other two suites that need a
real browser on the same Playwright install: the first drives the Browser card's account rows against
a real server, the second launches a saved profile twice to prove a login survives the close.

The browser suite checks the shell, every settings section, bot/room create-edit-delete,
the computer panel, a real multi-bot turn over SSE (run in a room the suite builds from bots it
creates, never your own — a turn writes the bot's work log and memory, and the suite takes those
with it, so it leaves nothing behind in your data), mobile layout, team import, the
repo-folder field (including the **Browse** folder picker), room logos (a repo's own logo found
and named, an upload taking over, a renamed file refused, **Remove** falling back), the theme
packages (every one offered in the picker painting surfaces of its own with no token left
undefined and no horizontal overflow, the body named for the theme, only the light-based ones
carrying the light class, the primary button's label clearing WCAG AA on every theme's accent, the
choice and the theme's accent surviving a reload, and re-picking the theme you are already on
leaving your own accent alone), the font and
text-size controls (every size in the interface moving together and keeping its proportions, the
choice surviving a reload, code staying monospace), the nested
sidebar (a room's bots, the fold, the one-click/two-click room row, clicking the room you are
already in changing nothing at all — no re-render and no scroll over a chat that never left — and a
scoped chat showing that room's repo), **Clear chat** (the menu item on a bot and on a room row, the confirm,
the transcript emptied on screen and on the server, and the bot's memory still there afterwards),
**switching chats mid-turn** (a turn driven by a stream the test owns, so the switch happens at an
exact point: the running turn's cards land only in its own chat, the other chat is told who is
working, coming back shows the plan and the tools again, and a turn that fails while you were away
still has its notice when you return),
**queueing a task sent mid-turn** (a task typed while a turn runs is held above the composer rather
than refused, is neither sent nor in the transcript, can be **steered** into the running turn — landing
in that turn's transcript and leaving the queue, without starting a second turn — or left alone to run
by itself the moment the turn ends),
**a room that stays a room transcript** (a real multi-bot turn: the room's transcript carries the
plan, who picked the job up and the report, with no shell or tool card anywhere in it, the room says
where each bot's work went, and its saved history keeps the report and no tool rows — the offline
suite pins the other half, that the command, its output and the bot's own commentary land in that
bot's chat inside the room, and that a bot a lead delegates to from outside the room keeps its work
in its own chat rather than a scoped one with no row),
**quoting and forwarding a message** (a reply carries the message it answers: the quote waits above the
composer, travels with the task, is drawn over the reply and is kept with it so reopening the chat draws
it back; a forward is a copy delivered to another chat through a picker of rooms and chats, arriving
marked *Forwarded* with no quote attached — the offline suite pins the server half, that the bot is
handed the quote inline as the task it is answering, and that a quote which happens to name a teammate
cannot re-route a room),
installing
skills from a **zip** (the picker that scans a multi-skill zip without installing anything, the
tick-to-choose flow, install-all, the search and filter that find them, and a **multi-megabyte** zip
that uploads rather than stalling — the POST body limit is derived from the zip limit so the transport
can never refuse a zip the installer would accept, and an oversized upload is drained and answered
instead of resetting the connection), the per-bot faces (distinct
species, motion, cursor gaze, the face picker, and Coucou's grading — a sidebar face is one flat fill
of exactly the bot's colour, while the big dock face keeps the gradient and so has no single dominant
colour), a bot's markdown reply rendered element by element
(headings, emphasis, inline and fenced code, lists, blockquote, a table, a real link kept and a
`javascript:` link made inert, raw HTML shown as text, and a person's own message left alone), the
model chip (naming the bot's own model rather than a stale default, opening a picker instead of
Settings, switching on the spot, and clearing back to the bot's model), the **approval chip** (in a
room the menu listing only the levels and saying it sets the room, with no per-member pickers and a
member's nested chat showing the room's level rather than the bot's, a level picked from a member's
row landing on the room, and a 1:1 chat naming the bot's default it is following with the menu's way
back handing it to the bot), the context limit card
(prefilled, saved, and a negative refused), the **context chip** (the chip naming how full the window
is and warming then reddening as it fills, the panel opening on hover and closing when the pointer
leaves, a click opening it too for touch and the keyboard, the window and count named, one row per
part with the shares adding up to the whole and the stacked bar filled to the fraction the chip
names, the average cache hit rate shown, 0.0% reported when usage came back with nothing cached but
no cache line at all when no usage came back, and the readout surviving a reload because it is saved
with the chat), the work-log card (read-only, per bot, empty rather
than an error for a bot that has not run yet), the notification sounds (the General card's switch and
volume, a finished turn actually scheduling its cue, the middle of a turn staying silent, the switch
really muting, and the slider previewing on release — with the browser's audio stood in for so an
oscillator being created is what is counted), the **Plugins panel** driving a real MCP server
(`tests/mcp_stub.py`): a server added through the form, Tested and reporting its tools, a server
that will not start showing its reason in its card, Switch off showing it off, Remove taking it
away, and no env value ever reaching the page, and the Browser card (a debug port and nothing else —
no launch-command or CDP-URL field left to drift — the card naming the endpoint the typed port
drives, and saving that port actually moving where the app connects). The offline suites need no router: self-learning,
skills (including that a hostile zip cannot write outside a skill's folder, never shadows a
built-in, that a scan writes nothing at all, and that picking a subset installs exactly that
subset), team import and per-room repo isolation in Python — including `resolve_session`,
the rule that decides which room and which bot a chat id names, what a deleted bot or room
takes with it, and what **Clear chat** does and does not touch (the transcript and a pending card
go; the bot's memory, its work log and the chat's own model and approval stay, and a chat whose turn
is still running is refused), which approval level actually runs (in a room the room's level is
the only level, so a room with none asks for every member and a level set on the room — or from a
member's row — runs for every member, while a 1:1 chat falls back to the bot's own default and a
bot's own **Full access** is a grant no room or chat may revoke), what a **steer** does to a turn that
is already running (the message reaching the bot at its next step rather than after the turn, reported
as its own event and kept in the transcript like a typed one, with the steer inbox alive only as long
as the turn — so a steer arriving after it ends is refused instead of being stranded), a turn that goes
quiet keeping its stream alive (the keepalive written while a card waits, the turn's own event still
arriving after it, and every line the stream sends being either an event or a comment, so the
client's data-only parser never sees one) — plus the logo resolution order
(upload beats repo beats initials), what an upload is allowed to be, the text-size grid and the
conversion of the old multiplier setting onto it, the connector auth schemes (Linear's bare key,
a bearer token, Google's three-part credential and its refresh-token exchange, replayed against a
stubbed token endpoint so no network is touched, and that no credential survives into what the
browser is told), the **MCP client** driven against `tests/mcp_stub.py` — a real MCP server over a real pipe and real sockets, not a stand-in — across all three transports (the stdio handshake and tool list, a Streamable HTTP server with its session id kept and a call answered as an SSE stream, and a legacy HTTP+SSE server whose POST endpoint is learned from the stream and the fallback remembered), the tool namespacing that keeps two servers' `echo` apart and inside the 64-char function-name limit, an image block coming back as a chat event, a server that will not start raising its reason and being remembered rather than retried, and the credentials staying write-only (the panel told the env and header **names** but never a value, and a save carrying none keeping the ones stored), the browser launch being built from the one port (the command opens that port, names
it exactly once, and is an argv rather than a shell string; a nonsense port falls back instead of
building a broken command; and a save from when the port and the command disagreed folds onto the one
port the command actually opened, dropping the retired fields), the dead **engines list** being
retired rather than merely hidden (gone from the shipped defaults, gone from a save that still carries
it, and absent from the whole load-to-serve path, so the tab can never draw an engine switch that does
nothing), the per-bot field each bot works in (one level under the room's repo, created on
use, isolated per bot, and safe against a bot id that tries to climb out), the work log (a delegated
teammate logging its own turn, a direct turn logged as direct, a failed turn logging nothing), which
model actually answers a chat (the chat's pick, else the bot's, else the room lead's, else the
default, including a session saved before this existed), the context budget (each model's window, a
manual override, and the compression that drops the oldest steps instead of overflowing), the context
panel (the rows summing to the provider's own `prompt_tokens` with the shares scaled onto it, an empty
row left out and the panel's own order kept, the cache count read from the usage detail block rather
than the flat field that reads 0, the cache figure averaging across a chat's turns, the fallback to
the app's own estimate when a provider reports no usage at all, a real turn reporting its measurement
and the chat keeping it, and **Clear chat** starting the panel over), and species, emotions,
cursor gaze and the flat-versus-soft colour grading in the mascot engine under Node — plus the notification cues
themselves (the four that exist, the states worth interrupting you for and the deliberate silence of the rest,
and the synth's envelopes under Node, which is where a ramp to exactly zero — the one value Web Audio refuses —
would otherwise go unnoticed) — plus the **Phone & tablet** switch (off by default, nothing to copy while it is
off, and turning it on really opening the door the phone app comes through: the address and token it shows
matching what the API reports, a caller from the LAN refused without a token, refused with a wrong one, accepted
with the token as a header or as a cookie, the one-time link signing the app in only when the token
comes as a header too — which is what keeps a browser pointed at it out — the secret store still 404
over that address, and turning it off closing the door again), and the Android app's own address parsing
compiled and run on a JVM (a pasted link split into address and token, a bare address and an https one, the
token never put in a URL that has none, and prose or a nonsense port refused instead of dialled).

---

## Security notes
- Shell commands run in a **sandbox** directory (`data`-sibling `sandbox/`), not your home.
  A room with a **Repo folder** narrows that to the folder you name. The bots' **file tools**
  (read, write, list) are confined to it — `..` and absolute paths that escape are refused — but a
  shell command is not a jail: it *starts* there, and a `cd` or an absolute path can still leave it,
  so treat shell access as the real boundary and leave a bot on a low approval level unless you mean it.
- Risky commands are gated behind the approval card unless a bot is set to **Full access**.
- API keys are stored in `data/settings.json` (the router key in `data/config.json`) and are **write-only** to the UI (it only ever sees a configured flag).
  The static file server never serves the secret store: any path under the data dir — including the app
  folder's own `data/` when `DATA_DIR` points elsewhere — answers 404, so a key can never be fetched as a file.
- Reaching the API from your **wifi** is off until you ask for it (**Phone & tablet**), and what it opens is
  guarded by a token — sent as `X-Anzen-Token` or the `anzen_pair` cookie, compared in constant time, with a
  same-origin check when a browser sends one. A loopback request is this machine's own page and needs no token,
  so the switch can never lock the dev server out of its own API. The desktop app does not go through this at
  all: it reaches the backend over a Unix socket, which nothing but the user running the app can open. The
  phone's link (`/?t=…`) only hands the cookie to a caller that also sends the token as a header, which a
  browser cannot do on a navigation — so the relay address is the app's door and not a public one.
- No credentials, conversations or memory are ever included in a shared team file.

---

## Notes & limits
- Bots run on **your** machine and router — not a per-account cloud computer.
- The browser is **headless** (server-side); it is not desktop-GUI control of your own machine.
- Voice is the browser's own speech synthesis — offline, free, and nothing sent to a server. There is no hosted voice option and no cloud key to set.
- The context budget is estimated from the request's size (roughly four characters a token) rather than counted with a real tokeniser, so it errs on the safe side — the goal is that a long run degrades instead of erroring.
- The phone half of a **packaged macOS build** needs the operating system's permission the first time the
  LAN switch goes on: an unsigned, un-notarized app is refused silently — the phone times out and nothing is
  written to any log — so the bundle declares `NSLocalNetworkUsageDescription` and macOS does the asking. Say
  yes. A build meant for other people should be signed and notarized with a Developer ID. Running from source
  (`python3 server.py --lan`) is not affected.
