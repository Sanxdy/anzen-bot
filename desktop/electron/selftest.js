/* The self-test harness for the desktop shell — never part of the app's own startup.

   Run inside the renderer, from the main process, to answer the questions an outside test cannot:
   did the shell really come off the disk, does `fetch("/api/…")` reach the backend over IPC, and does
   a chat turn stream back one event at a time. `main.js` requires this file only when ANZEN_SELFTEST=1,
   so a shipped app never loads it — the test lives in its own file instead of inside the window code. */
function probe(win) {
  return win.webContents.executeJavaScript(`(async () => {
    const out = { origin: location.origin, protocol: location.protocol,
                  fromDisk: location.protocol === 'file:', viaIpc: !!window.anzen };
    try {
      const c = await (await fetch('/api/config')).json();
      out.config = { ok: true, bots: (c.bots || []).length, hasRoster: Array.isArray(c.roster) };
    } catch (e) { out.config = { ok: false, error: String(e) }; }
    try {
      // A different bot from the one the UI part below opens: a session that already holds a tool
      // result gets a plain answer from the stub, so sharing a session would silently drop the tool
      // row this probe is here to see.
      const res = await fetch('/api/chat', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bot: 'ops', text: 'hello there' }) });
      out.chatStatus = res.status;
      const rd = res.body.getReader(), dec = new TextDecoder();
      let buf = '', n = 0, kinds = [], deltas = 0;
      while (true) {
        const { done, value } = await rd.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf('\\n\\n')) >= 0) {
          const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
          if (chunk.startsWith('data: ')) { n++; try {
            const ev = JSON.parse(chunk.slice(6));
            kinds.push(ev.type);
            if (ev.type === 'agent_text' && ev.delta) deltas++;   // the answer typing itself in
          } catch (e) {} }
        }
      }
      out.chat = { events: n, kinds: kinds.slice(0, 8), deltas, last: kinds[kinds.length - 1] };
    } catch (e) { out.chat = { ok: false, error: String(e) }; }
    // ---- the panel itself ----
    // Not a screenshot: the probe drives the real composer and then reads the real DOM, so what it
    // reports is what a person looking at the window would see. The wait is on the turn actually
    // ending (Stop going away) rather than on a fixed delay, so a slow machine does not read a
    // half-drawn transcript.
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    const q = s => document.querySelector(s), qa = s => [...document.querySelectorAll(s)];
    try {
      // A room routes a member's tool work into that member's own chat, so the transcript on screen
      // would not show a tool row. A chat with one bot is where the work is drawn where you are
      // looking, so the probe opens one before it types — and picks the builder, whose toolset is the
      // full one, so the stub's write_file call is one the bot can actually make.
      const rows = [...document.querySelectorAll('#chans .sub .subbot, #bots .bot')];
      const pick = rows.find(r => /builder/i.test((r.querySelector('.nm') || {}).textContent || '')) || rows[0];
      const want = pick ? ((pick.querySelector('.nm') || {}).textContent || '').trim() : '';
      // Click until the header names that bot: a click that lands while the sidebar is still being
      // rebuilt would leave the room open, and a room routes a member's tool work out of the
      // transcript on screen — which is the very thing this probe is checking for.
      for (let i = 0; pick && i < 3; i++) {
        pick.click(); await sleep(900);
        if (want && ((q('#hName') || {}).textContent || '').includes(want)) break;
      }
      // Whether an element is on screen is a question about computed style, not about the hidden
      // attribute: a rule setting display beats the browser's own rule for [hidden], so an element
      // that says it is hidden can still be one the user is looking at.
      const shown = e => !!e && getComputedStyle(e).display !== 'none';
      const before = qa('#msgs .m').length;
      const ta = q('#input');
      ta.value = 'ui probe turn';
      q('#btnSend').click();
      // Sampled synchronously: the click starts the turn in this same tick, so this reads the
      // composer with a turn in flight. The loop below then waits for that turn to end.
      const stopDuring = shown(q('#btnStop'));
      for (let i = 0; i < 160; i++) {
        await sleep(250);
        const stop = q('#btnStop');
        if (qa('#msgs .m').length > before && stop && stop.hidden) break;
      }
      await sleep(400);
      out.ui = {
        picked: want,                                 // the chat the probe opened, by name
        splash: !!q('#splash'),                       // must be gone once boot() has a config
        chats: qa('#chats .chat').length,             // the sidebar's conversation list
        search: !!q('#chatSearch'),
        stop: !!q('#btnStop'),                        // the control exists…
        stopDuring,                                   // …is shown while a turn runs…
        stopAfter: shown(q('#btnStop')),              // …and gone once there is nothing to stop
        msgs: qa('#msgs .m').length,
        user: qa('#msgs .m.user').length,
        bot: qa('#msgs .m.bot').length,
        acts: qa('#msgs .m .acts .ab').map(b => b.textContent),
        code: qa('#msgs .md pre code').length,
        copier: qa('#msgs .md .cbcopy').length,
        toolRows: qa('#msgs .m.tool .thead').length,
        toolOpen: qa('#msgs .m.tool.open').length,    // collapsed until asked for
        diffLines: qa('#msgs .m.tool .diff .dl').length,
        header: (q('#hName') || {}).textContent || '',
        // The sidebar row for the chat that is open. It must name the bot the header names: a chat
        // with one bot is named for that bot even when the bot sits inside a company.
        chatRow: (q('#chats .chat.sel .cnm') || {}).textContent || '',
        // The chat list is capped and scrolls on its own, so a long history cannot push the channels
        // and bots out of reach. Read as computed style, which is what decides it.
        chatScroll: (() => { const cl = q('#chats'); if (!cl) return null;
          const cs = getComputedStyle(cl);
          return { overflowY: cs.overflowY, maxHeight: cs.maxHeight, capped: cs.maxHeight !== 'none' }; })(),
      };
      // An open chip popover has to sit above the transcript. In the glass themes the header is its
      // own stacking context, so a message bubble — positioned, and later in the tree — paints over
      // the popover unless the header is lifted. This hit-tests the popover where it overlaps a
      // bubble, which is exactly where the covering happens; the point is found rather than assumed,
      // so a transcript that happens not to reach the popover is reported instead of passing blind.
      const chip = q('#chipModel');
      if (chip) {
        // The glass themes are where this went wrong: their header carries a backdrop-filter, which
        // makes it a stacking context that traps the popovers. A fresh install is on Dark, so the
        // theme is switched the way the picker does it — on the body — or there is nothing to see.
        const wasTheme = document.body.dataset.theme;
        document.body.dataset.theme = 'glass'; document.body.classList.remove('light');
        await sleep(200);
        chip.click(); await sleep(250);
        const pop = q('#mmPop');
        if (pop) {
          const pr = pop.getBoundingClientRect();
          const under = qa('#msgs .m').map(m => m.getBoundingClientRect())
            .map(r => ({ left: Math.max(pr.left, r.left), right: Math.min(pr.right, r.right),
                         top: Math.max(pr.top, r.top), bottom: Math.min(pr.bottom, r.bottom) }))
            .find(r => r.right - r.left > 12 && r.bottom - r.top > 12);
          if (under) {
            const hit = document.elementFromPoint((under.left + under.right) / 2, (under.top + under.bottom) / 2);
            out.popover = { overBubble: true, onPopover: !!(hit && pop.contains(hit)),
                            topmost: hit ? (hit.className || hit.tagName) : null };
          } else {
            out.popover = { overBubble: false, onPopover: !!(pop.contains(document.elementFromPoint(
              pr.left + pr.width / 2, pr.top + 20))) };
          }
        } else { out.popover = { opened: false }; }
        chip.click(); await sleep(150);
        document.body.dataset.theme = wasTheme;
      }
      // Opening a chat must land at the bottom, not animate its way down to it. The transcript is
      // clamped for the moment so even a short one overflows and the scroll is observable at all —
      // a transcript with nothing to scroll would prove nothing either way. Samples are taken as the
      // chat is reopened: a position strictly between the top and the bottom means it was still on
      // its way down, which is exactly the travel that should not be happening.
      try {
        const box = q('#msgs');
        const back = q('#chats .chat.sel, #bots .bot.sel, #chans .bot.sel');
        const other = qa('#chats .chat:not(.sel), #bots .bot:not(.sel), #chans .bot:not(.sel)')[0];
        if (box && back && other) {
          const prevMax = box.style.maxHeight;
          box.style.maxHeight = '240px';
          await sleep(150);
          other.click(); await sleep(800);
          const trace = [];
          back.click();
          for (let i = 0; i < 26; i++) {
            trace.push({ top: Math.round(box.scrollTop),
                         bottom: Math.round(box.scrollHeight - box.clientHeight) });
            await sleep(35);
          }
          box.style.maxHeight = prevMax;
          const live = trace.filter(s => s.bottom > 20);      // only where there was something to scroll
          out.scroll = { samples: live.length, seen: live.slice(0, 8),
                         animated: live.filter(s => s.top > 2 && s.top < s.bottom - 2).length };
        } else { out.scroll = { skipped: true, back: !!back, other: !!other }; }
      } catch (e) { out.scroll = { ok: false, error: String(e) }; }
      // A tool row has to keep its own height once the transcript overflows. These rows are flex
      // items in a column, so a row that may shrink will shrink — and .m.tool clips its header with
      // overflow:hidden, which drops the row's automatic minimum size to zero. Without the
      // #msgs>*{flex:0 0 auto} rule every tool row was squeezed down to its 2px border, and a turn
      // that ran a lot of tools drew as a wall of empty lines. The clamp is what makes a short
      // transcript overflow, so there is something to shrink against at all.
      try {
        const box = q('#msgs');
        const rows = qa('#msgs .m.tool');
        if (box && rows.length) {
          const prevMax = box.style.maxHeight;
          box.style.maxHeight = '240px';
          await sleep(150);
          const overflowing = box.scrollHeight > box.clientHeight + 4;
          const hs = rows.slice(0, 6).map(r => Math.round(r.getBoundingClientRect().height));
          const th = rows[0].querySelector('.thead');
          box.style.maxHeight = prevMax;
          out.rows = { overflowing: overflowing, count: rows.length, heights: hs,
                       min: Math.min.apply(null, hs),
                       thead: th ? Math.round(th.getBoundingClientRect().height) : null };
        } else { out.rows = { skipped: true, count: rows.length }; }
      } catch (e) { out.rows = { ok: false, error: String(e) }; }
      // ---- the other device: a write this window did not send ----
      // The window and the phone are two clients of one server and a chat is one transcript on disk,
      // so a turn typed on the phone has to turn up here. This writes to the chat that is open through
      // the ordinary API — a request of its own, which is what the phone's would be — and then reads
      // the real DOM. Nothing in this window sent it, so the only thing that can have put it on screen
      // is the watch stream and the redraw it drives. The write is retried a couple of times because a
      // missed nudge costs a refresh and nothing else — which is the point of the nudge being content
      // free, and exactly why a lost one must not read as a lost message.
      try {
        const sel = q('#chats .chat.sel, #bots .bot.sel, #chans .bot.sel');
        const sid = sel ? sel.dataset.id : '';
        const before = qa('#msgs .m').length;
        let seen = false, attempts = 0, status = 0;
        for (; attempts < 3 && !seen; attempts++) {
          const res = await fetch('/api/chat', { method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bot: sid, text: 'from the other device' }) });
          status = res.status;
          const rd = res.body.getReader();                 // the phone drains the turn the same way
          while (!(await rd.read()).done) {}
          for (let i = 0; i < 24 && !seen; i++) {
            await sleep(250);
            seen = qa('#msgs .m').some(m => /from the other device/.test(m.textContent || ''));
          }
        }
        out.follow = { sid: sid || null, status: status, attempts: attempts,
                       before: before, after: qa('#msgs .m').length, seen: seen };
      } catch (e) { out.follow = { ok: false, error: String(e) }; }
    } catch (e) { out.ui = { ok: false, error: String(e) }; }
    return out;
  })()`);
}

module.exports = { probe };
