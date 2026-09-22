/* Runs a test page in a real browser and waits for its answer.
 *
 * Chrome's --dump-dom prints the page the moment it loads, which for anything
 * that reads a file or exports one is far too early. So this opens the page
 * over Chrome's debugging connection instead and waits on window.__done,
 * which the page resolves when it has genuinely finished.
 *
 *   node tests/run-browser.mjs <url>
 */

import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const target = process.argv[2];
// With a second argument, that file's code is run inside the page and its
// return value is the result. Without one, the page reports on itself
// through window.__done.
const scriptFile = process.argv[3];
if (!target) { console.error('usage: run-browser.mjs <url> [script.mjs]'); process.exit(2); }

const port = 9222 + Math.floor(Math.random() * 400);
const profile = mkdtempSync(join(tmpdir(), 'jaring-chrome-'));

const chrome = spawn(CHROME, [
  '--headless=new',
  `--remote-debugging-port=${port}`,
  `--user-data-dir=${profile}`,
  '--no-first-run', '--no-default-browser-check', '--disable-extensions',
  // SwiftShader keeps WebGL working with no display attached.
  '--use-gl=swiftshader', '--enable-unsafe-swiftshader',
  'about:blank',
], { stdio: 'ignore' });

const cleanup = () => {
  try { chrome.kill('SIGKILL'); } catch {}
  try { rmSync(profile, { recursive: true, force: true }); } catch {}
};
process.on('exit', cleanup);

async function waitForChrome() {
  for (let i = 0; i < 100; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/json/version`);
      if (res.ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error('Chrome never opened its debugging port');
}

function cdp(ws) {
  let id = 0;
  const waiting = new Map();
  ws.addEventListener('message', (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && waiting.has(msg.id)) {
      const { ok, no } = waiting.get(msg.id);
      waiting.delete(msg.id);
      msg.error ? no(new Error(msg.error.message)) : ok(msg.result);
    }
  });
  return (method, params = {}) => new Promise((ok, no) => {
    const n = ++id;
    waiting.set(n, { ok, no });
    ws.send(JSON.stringify({ id: n, method, params }));
  });
}

try {
  await waitForChrome();
  const tab = await (await fetch(
    `http://127.0.0.1:${port}/json/new?about:blank`, { method: 'PUT' })).json();

  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((ok, no) => {
    ws.addEventListener('open', ok);
    ws.addEventListener('error', () => no(new Error('could not attach to the tab')));
  });
  const send = cdp(ws);

  await send('Runtime.enable');
  await send('Log.enable');
  await send('Page.enable');
  ws.addEventListener('message', (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.method === 'Log.entryAdded' && msg.params.entry.level === 'error') {
      const e = msg.params.entry;
      console.error('  browser error:', e.text, e.url ? `(${e.url})` : '');
    }
    if (msg.method === 'Runtime.exceptionThrown') {
      const d = msg.params.exceptionDetails;
      console.error('  page threw:', d.exception?.description || d.text,
        d.url ? `(${d.url}:${d.lineNumber})` : '');
    }
    if (msg.method === 'Runtime.consoleAPICalled') {
      console.error('  console.' + msg.params.type + ':',
        msg.params.args.map((a) => a.description || a.value).join(' '));
    }
  });

  // Navigate only once we are listening, then wait for the page to load
  // before asking it anything - evaluating against a blank tab returns
  // undefined and looks like a failure that is really a race.
  const loaded = new Promise((ok) => {
    ws.addEventListener('message', (ev) => {
      if (JSON.parse(ev.data).method === 'Page.loadEventFired') ok();
    });
  });
  await send('Page.navigate', { url: target });
  await loaded;

  const result = await Promise.race([
    send('Runtime.evaluate', {
      // The page's own work starts on load, so give window.__done a moment
      // to exist rather than assuming the module has run yet.
      expression: scriptFile
        ? `(async () => {\n${readFileSync(scriptFile, 'utf8')}\n})()`
        : `(async () => {
        for (let i = 0; i < 200 && !window.__done; i++) {
          await new Promise((r) => setTimeout(r, 50));
        }
        if (!window.__done) throw new Error('the test page never started');
        return await window.__done;
      })()`,
      awaitPromise: true,
      returnByValue: true,
    }),
    new Promise((_, no) => setTimeout(() => no(new Error('timed out after 90s')), 90000)),
  ]);

  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.exception?.description || 'page threw');
  }

  const { failed, text } = result.result.value;
  console.log(text);
  process.exit(failed ? 1 : 0);
} catch (err) {
  console.error('runner failed:', err.message);
  process.exit(1);
}
