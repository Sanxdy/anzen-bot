/* The one bridge between the page and the main process.

   `contextIsolation` is on, so this file runs in its own world: the page never sees `ipcRenderer` or
   anything else from Node — only the two functions handed over below. Each request is given an id,
   and the main process answers with a head, then a chunk per piece of the reply, then an end (or an
   error instead). `bridge.js` turns that back into a real `Response` for `app.js`. */
const { contextBridge, ipcRenderer } = require('electron');

const handlers = new Map();     // id -> { head, chunk, end, error }
// Seeded per page load: main.js keeps its in-flight map across a reload, so restarting at 1 would let
// the new page's first request receive the old turn's still-streaming chunks.
let nextId = 1 + Math.floor(Math.random() * 1e9);

ipcRenderer.on('anzen:head', (_e, m) => { const h = handlers.get(m.id); if (h) h.head(m.status, m.headers); });
ipcRenderer.on('anzen:chunk', (_e, m) => { const h = handlers.get(m.id); if (h) h.chunk(m.b64); });
ipcRenderer.on('anzen:end', (_e, m) => { const h = handlers.get(m.id); handlers.delete(m.id); if (h) h.end(); });
ipcRenderer.on('anzen:error', (_e, m) => { const h = handlers.get(m.id); handlers.delete(m.id); if (h) h.error(m.message); });

contextBridge.exposeInMainWorld('anzen', {
  request(spec, h) {
    const id = nextId++;
    handlers.set(id, h);
    ipcRenderer.send('anzen:request', { id, spec });
    return id;
  },
  abort(id) {
    handlers.delete(id);
    ipcRenderer.send('anzen:abort', id);
  },
});
