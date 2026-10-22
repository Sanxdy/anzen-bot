/* The app's own transport, and the only file that knows the desktop app is different.

   In a browser this does nothing at all: `window.anzen` exists only inside the desktop app, where the
   page is loaded from disk and a plain `fetch` has no server to reach. There, every `/api/…` call is
   handed to the main process over Electron IPC, and the reply is turned back into a real `Response` —
   body and all, kept a stream so the chat's server-sent events still arrive one at a time rather than
   in one lump at the end of the turn.

   `app.js` is unchanged by any of this: it goes on calling `fetch`. Loaded as a plain script before
   the module, so the shim is in place before `app.js` runs. */
(() => {
  const bridge = window.anzen;
  if (!bridge) return;                       // a browser or the dev server: the ordinary fetch is right

  const API = /^\/api\//;
  const native = window.fetch.bind(window);
  const bytes = b64 => {
    const s = atob(b64), u = new Uint8Array(s.length);
    for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i);
    return u;
  };

  window.fetch = (input, init) => {
    const url = typeof input === 'string' ? input : (input && input.url) || String(input);
    if (!API.test(url)) return native(input, init);        // anything else is not ours to carry

    const spec = {
      url,
      method: (init && init.method) || 'GET',
      headers: (init && init.headers) || {},
      body: (init && init.body) || null,
    };
    let id = null, ctrl = null;
    const body = new ReadableStream({
      start(c) { ctrl = c; },
      cancel() { if (id) bridge.abort(id); },              // the caller walked away: drop the request
    });
    // The status has to be known before a Response can be built, so the head is awaited first and the
    // body keeps filling in behind it.
    const head = new Promise((resolve, reject) => {
      id = bridge.request(spec, {
        head: (status, headers) => resolve({ status, headers }),
        chunk: b64 => ctrl.enqueue(bytes(b64)),
        end: () => ctrl.close(),
        error: message => { const e = new Error(message); try { ctrl.error(e); } catch (_) {} reject(e); },
      });
    });
    return head.then(h => new Response(body, { status: h.status, headers: h.headers }));
  };

  /* A channel's logo is an `<img src="/api/logo/…">`, a sent clip is a `<video>`, a voice note an
     `<audio>` — and none of them is something our shim is asked about: the element fetches it itself,
     which on a page from disk goes nowhere. So any such source is fetched over the same channel and
     swapped to a blob URL. The dataset mark keeps the observer from reacting to its own swap. */
  const swap = node => {
    const src = node.getAttribute('src');
    /* Remember the request URL, not a boolean. A new logo changes the URL on the same element, and
       that is the one time the previous blob must be revoked; the actual blob write is not an API URL
       and therefore cannot loop back through this branch. */
    if (!src || !API.test(src) || node.dataset.anzenSrc === src) return;
    node.dataset.anzenSrc = src;
    fetch(src).then(r => r.blob()).then(b => {
      const url = URL.createObjectURL(b);
      if (node.dataset.anzenSrc !== src) { URL.revokeObjectURL(url); return; }
      const old = node.dataset.anzenBlob;
      node.dataset.anzenBlob = url;
      node.src = url;
      if (old) URL.revokeObjectURL(old);       // nothing else holds the old blob, so it is a leak
    }).catch(() => {
      /* A transient failure must be retryable when the observer sees the same API source again. */
      if (node.dataset.anzenSrc === src) delete node.dataset.anzenSrc;
    });
  };
  const MEDIA = new Set(['IMG', 'VIDEO', 'AUDIO']);
  const SOURCES = 'img[src^="/api/"],video[src^="/api/"],audio[src^="/api/"]';
  const scan = node => {
    if (!node || node.nodeType !== 1) return;
    if (MEDIA.has(node.tagName)) { swap(node); return; }
    // Only walk the subtree when it holds one of these at all: a streamed turn appends text nodes to
    // the transcript constantly, and a selector walk on each one is the hot path this observer lives on.
    if (node.querySelector && node.querySelector('img,video,audio')) node.querySelectorAll(SOURCES).forEach(swap);
  };
  document.querySelectorAll(SOURCES).forEach(swap);
  /* A download is an `<a href="/api/…">`, and the window-open handler would hand that to the OS as a
     `file://` path that does not exist. Fetching it over the channel and clicking a blob link is how
     a file reaches disk from a page loaded off disk. */
  document.addEventListener('click', e => {
    const a = e.target && e.target.closest && e.target.closest('a[href^="/api/"]');
    if (!a) return;
    e.preventDefault(); e.stopPropagation();
    fetch(a.getAttribute('href')).then(r => r.blob()).then(b => {
      const url = URL.createObjectURL(b), t = document.createElement('a');
      t.href = url; t.download = a.getAttribute('download') || ""; t.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);   // the save has started by then
    }).catch(() => {});
  }, true);
  const mo = new MutationObserver(ms => {
    for (const m of ms) {
      if (m.type === 'attributes') swap(m.target);
      else m.addedNodes.forEach(scan);
    }
  });
  // Only the containers that ever hold an `/api/` image, not the whole document: the transcript, the
  // sidebar's chat rows, and the settings panel that draws a logo field. Watching everything meant a
  // scan of every added node for the length of every turn.
  for (const sel of ['#msgs', '#side', '#setPanel']) {
    const root = document.querySelector(sel);
    if (root) mo.observe(root, { subtree: true, childList: true, attributes: true, attributeFilter: ['src'] });
  }
})();
