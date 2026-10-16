/* Anzen-bot's desktop shell.

   Electron, the same shape as ZCode. The window is loaded **from disk** — a `file://` page out of
   the install directory — and the renderer talks to this main process over **Electron IPC**. This
   process drives the Python backend over a **Unix socket**. No port is opened anywhere, so opening
   the app never puts the workspace on localhost.

   The renderer keeps calling `fetch("/api/…")`: `bridge.js`, a page asset loaded before `app.js`,
   carries those calls into `window.anzen.request`, which lands in the `anzen:request` handler below.
   Replies come back one IPC message per chunk, so the chat's server-sent events still arrive as they
   are written rather than all at once at the end of the turn.
*/
const { app, BrowserWindow, ipcMain, shell } = require('electron');
const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

// ------------------------------------------------------------------ where things live
function dataDir() {
  if (process.env.DATA_DIR) return process.env.DATA_DIR;
  const home = os.homedir();
  const base = process.platform === 'darwin' ? path.join(home, 'Library', 'Application Support')
    : process.platform === 'win32' ? (process.env.APPDATA || path.join(home, 'AppData', 'Roaming'))
      : (process.env.XDG_DATA_HOME || path.join(home, '.local', 'share'));
  return path.join(base, 'Anzen-bot');
}

function appRoot() {
  // Packaged, the shell files are copied into `resources/app`; from source they are the repo root.
  const packaged = path.join(process.resourcesPath || '', 'app');
  if (fs.existsSync(path.join(packaged, 'index.html'))) return packaged;
  return path.resolve(__dirname, '..', '..');
}

function backendCommand(sockPath) {
  // Packaged, the backend is the frozen Python binary beside the shell; from source it is the
  // launcher, run with whatever `python3` is on PATH. PyInstaller leaves a one-file binary on
  // Windows and Linux and a folder beside it on macOS, so both shapes are accepted.
  const exe = process.platform === 'win32' ? 'anzen-backend.exe' : 'anzen-backend';
  let bundled = path.join(process.resourcesPath || '', 'backend', exe);
  if (fs.existsSync(bundled) && fs.statSync(bundled).isDirectory()) bundled = path.join(bundled, exe);
  if (fs.existsSync(bundled)) return { cmd: bundled, args: ['--sock', sockPath] };
  const launcher = path.resolve(__dirname, '..', 'anzen_app.py');
  return { cmd: process.env.ANZEN_PYTHON || 'python3', args: [launcher, '--sock', sockPath] };
}

function socketPath() {
  // A Unix socket address is length-limited, and a data dir can be deep on Windows or Linux, so a
  // long one falls back to the temp dir rather than failing the bind.
  const p = path.join(dataDir(), 'anzen.sock');
  return p.length < 100 ? p : path.join(os.tmpdir(), 'anzen-' + process.pid + '.sock');
}

// ------------------------------------------------------------------ the backend sidecar
let backend = null;
let SOCK = null;

function startBackend(sock) {
  const { cmd, args } = backendCommand(sock);
  backend = spawn(cmd, args, {
    env: { ...process.env, ANZEN_SOCK: sock, DATA_DIR: dataDir() },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  backend.stdout.on('data', d => process.stdout.write('[backend] ' + d));
  backend.stderr.on('data', d => process.stderr.write('[backend] ' + d));
  backend.on('exit', (code, sig) => {
    console.error(`[backend] exited code=${code} signal=${sig}`);
    backend = null;
  });
  return backend;
}

// The socket file appearing means the backend bound it; one probe then proves it is answering, so
// the window never opens onto a connection the backend is not yet ready to take.
function waitForBackend(sock, tries = 240) {
  return new Promise((resolve, reject) => {
    let n = 0;
    const tick = () => {
      if (backend === null) return reject(new Error('the backend exited before it was ready'));
      if (++n > tries) return reject(new Error('the backend did not come up in time'));
      const req = http.request({ socketPath: sock, path: '/api/lan', method: 'GET', timeout: 500 },
        res => { res.resume(); resolve(); });
      req.on('error', () => setTimeout(tick, 250));
      req.on('timeout', () => { req.destroy(); setTimeout(tick, 250); });
      req.end();
    };
    tick();
  });
}

// ------------------------------------------------------------------ the IPC channel
// Everything the renderer asks for arrives here, one message per request. The path is the only thing
// the renderer is trusted with, and only under `/api/` — the shell itself is read from disk, so
// nothing else needs a door into the backend. Replies stream back chunk by chunk.
const inflight = new Map();

// A backend that takes a request and then never answers — no head, or a stream that stalls — would
// leave the renderer's promise pending for good, so an idle timer settles it. Generous on purpose: a
// turn can think a while before its first byte, and the backend's own per-read socket timeout is 240s,
// so this only fires when the backend has genuinely stopped talking. Reset on every chunk.
const IDLE_MS = 300000;

function answer(id, sender, spec) {
  const url = String((spec && spec.url) || '');
  const say = (channel, payload) => { if (!sender.isDestroyed()) sender.send(channel, payload); };
  if (!url.startsWith('/api/')) return say('anzen:error', { id, message: 'refused: ' + url });
  const headers = { ...((spec && spec.headers) || {}), host: '127.0.0.1' };  // loopback for the auth rule
  delete headers['content-length'];   // let Node set it from the body it is given
  let done = false, idle = null;
  const finish = (channel, payload) => {
    if (done) return;                 // end, error and the idle timer all race; the first one wins
    done = true;
    clearTimeout(idle);
    inflight.delete(id);
    say(channel, payload);
  };
  const req = http.request({ socketPath: SOCK, path: url, method: (spec && spec.method) || 'GET', headers }, res => {
    const h = {};
    for (const [k, v] of Object.entries(res.headers)) if (v !== undefined) h[k] = Array.isArray(v) ? v.join(', ') : v;
    say('anzen:head', { id, status: res.statusCode, headers: h });
    idle.refresh();                   // the head arrived: push the deadline out to the next chunk
    // Base64 rather than a typed array: it survives the isolated-world boundary unchanged, and a
    // chunk is small enough that the encoding is not what anyone is waiting on.
    res.on('data', b => { idle.refresh(); say('anzen:chunk', { id, b64: b.toString('base64') }); });
    res.on('end', () => finish('anzen:end', { id }));
    res.on('error', e => finish('anzen:error', { id, message: e.message }));
  });
  inflight.set(id, req);
  idle = setTimeout(() => {
    if (!inflight.has(id)) return;    // the caller aborted: nothing left to settle
    finish('anzen:error', { id, message: 'the backend stopped answering' });
    req.destroy();
  }, IDLE_MS);
  req.on('error', e => finish('anzen:error', { id, message: e.message }));
  req.end((spec && spec.body) || undefined);
}

ipcMain.on('anzen:request', (e, { id, spec }) => answer(id, e.sender, spec));
ipcMain.on('anzen:abort', (_e, id) => {
  const req = inflight.get(id);
  if (req) { req.destroy(); inflight.delete(id); }
});

// ------------------------------------------------------------------ the window
// The window's own self-test — did the shell come off the disk, does `fetch` reach the backend, does
// a turn stream back one event at a time — lives in `selftest.js` and is required only when
// ANZEN_SELFTEST=1, so the shipped window code carries none of it.

function openWindow() {
  const file = path.join(appRoot(), 'index.html');
  const win = new BrowserWindow({
    width: 1280, height: 860, minWidth: 380, minHeight: 600,
    backgroundColor: '#0e0e14',
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true, nodeIntegration: false, sandbox: true,
      // The link panel's frame is a real embedded browser (`<webview>`), which is what lets a page
      // that refuses to be framed — X-Frame-Options, so most social and news sites — still render
      // beside the chat. Electron leaves it off by default, so it has to be asked for.
      webviewTag: true,
    },
  });
  /* A webview is remote content being attached to our own window, so it is trimmed to exactly what
     the link panel needs: no preload of ours, no Node, and nothing but http(s) as a source. A page
     the transcript linked to can therefore never reach this process or the app's own page. */
  win.webContents.on('will-attach-webview', (e, prefs, params) => {
    delete prefs.preload;
    prefs.nodeIntegration = false;
    prefs.contextIsolation = true;
    if (!/^https?:/i.test(params.src || '')) e.preventDefault();
  });
  win.loadFile(file);            // the shell comes off the disk, not off a server
  win.webContents.once('did-finish-load', async () => {
    // The one line that says the window really came up, for the app-level test to read: a frozen
    // app cannot be asked from the outside whether its window opened, so it says so itself.
    console.log('window open on file://' + file);
    if (process.env.ANZEN_SELFTEST === '1') {
      const { probe } = require('./selftest');
      console.log('selftest ' + JSON.stringify(await probe(win)));
    }
  });
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: 'deny' }; });
  return win;
}

// ------------------------------------------------------------------ run
app.whenReady().then(async () => {
  SOCK = socketPath();
  try { fs.rmSync(SOCK, { force: true }); } catch { /* nothing to clear */ }
  startBackend(SOCK);
  try {
    await waitForBackend(SOCK);
  } catch (e) {
    console.error('the backend did not start: ' + e.message);
  }
  openWindow();
});

app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) openWindow(); });
app.on('before-quit', () => {
  // The window closing is what ends the app, and the backend goes with it rather than lingering as
  // an orphan holding the socket.
  if (backend) { backend.kill('SIGTERM'); backend = null; }
});
