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

  /* A channel's logo is an `<img src="/api/logo/…">`, and an image element is not something our shim
     is asked about — the browser fetches it itself, which on a page from disk goes nowhere. So any
     such image is fetched over the same channel and swapped to a blob URL. The dataset mark keeps the
     observer from reacting to its own swap. */
  const swap = img => {
    const src = img.getAttribute('src');
    /* Remember the request URL, not a boolean. A new logo changes the URL on the same element, and
       that is the one time the previous blob must be revoked; the actual blob write is not an API URL
       and therefore cannot loop back through this branch. */
    if (!src || !API.test(src) || img.dataset.anzenSrc === src) return;
    img.dataset.anzenSrc = src;
    fetch(src).then(r => r.blob()).then(b => {
      const url = URL.createObjectURL(b);
      if (img.dataset.anzenSrc !== src) { URL.revokeObjectURL(url); return; }
      const old = img.dataset.anzenBlob;
      img.dataset.anzenBlob = url;
      img.src = url;
      if (old) URL.revokeObjectURL(old);       // nothing else holds the old blob, so it is a leak
    }).catch(() => {
      /* A transient failure must be retryable when the observer sees the same API source again. */
      if (img.dataset.anzenSrc === src) delete img.dataset.anzenSrc;
    });
  };
  const scan = node => {
    if (!node || node.nodeType !== 1) return;
    if (node.tagName === 'IMG') { swap(node); return; }
    // Only walk the subtree when it holds an image at all: a streamed turn appends text nodes to the
    // transcript constantly, and a selector walk on each one is the hot path this observer lives on.
    if (node.querySelector && node.querySelector('img')) node.querySelectorAll('img[src^="/api/"]').forEach(swap);
  };
  document.querySelectorAll('img[src^="/api/"]').forEach(swap);
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
