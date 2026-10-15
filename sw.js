/* Service worker — makes Anzen-bot installable and its shell work offline.
   Never caches the API or the SSE stream; only the static app shell.

   Strategy: NETWORK-FIRST for the shell, cache only as an offline fallback.
   Cache-first here would serve a stale index.html/app.js forever after an
   update — the app would look unchanged until the user manually cleared it. */
const CACHE = "anzen-v4";   // bump this whenever a file in SHELL changes: activate() drops every other
                            // cache, and a stale shell list is what an offline launch would keep serving.
                            // (Online, the fetch handler below is network-first, so a new file is picked
                            // up on the next load either way — this is about the offline copy.)
const SHELL = ["./", "./index.html", "./app.js", "./mochi.js", "./sound.js", "./bridge.js", "./manifest.webmanifest",
               "./icon-192.png", "./icon-512.png", "./icon-maskable-512.png", "./apple-touch-icon.png"];

self.addEventListener("install", e => {
  // allSettled, not addAll: one icon that 404s must not fail the whole install, or skipWaiting never
  // runs and the update sits waiting behind the old worker.
  e.waitUntil(caches.open(CACHE).then(c => Promise.allSettled(SHELL.map(f => c.add(f)))).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.startsWith("/api/")) return;   // live data: never cache
  e.respondWith(
    fetch(e.request).then(res => {
      // Only a real, same-origin 200 is worth keeping: a transient 500 would otherwise be cached and
      // served as the app long after the server recovered.
      if (res.ok && res.type === "basic") {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy)).catch(() => {});
      }
      return res;
    }).catch(async () => {
      const hit = await caches.match(e.request);
      if (hit) return hit;
      // Offline and nothing cached: only a navigation may fall back to the shell. Handing index.html
      // to the module loader in place of app.js is not a fallback — it is a syntax error, and the app
      // never boots.
      if (e.request.mode === "navigate") {
        const shell = await caches.match("./index.html");
        if (shell) return shell;
      }
      return Response.error();
    })
  );
});
