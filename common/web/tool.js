/* The bits of a tool that are not the tool.
 *
 * Talking to its own server, saying something to the person using it, and
 * showing that something slow is happening. Written once because five tools
 * would otherwise each write them slightly differently.
 */

const TOKEN = window.BENGKEL_TOKEN;

/** Ask this tool's own server for something. */
export async function api(path, body) {
  const url = path.includes('?')
    ? `${path}&t=${encodeURIComponent(TOKEN)}`
    : `${path}?t=${encodeURIComponent(TOKEN)}`;
  const res = await fetch(body ? path : url, {
    method: body ? 'POST' : 'GET',
    headers: { 'X-Bengkel-Token': TOKEN, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const doc = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(doc.error || res.statusText);
  return doc;
}

export const modelURL = (path) =>
  `/api/model?t=${encodeURIComponent(TOKEN)}&path=${encodeURIComponent(path)}`;

let toastTimer = null;

/** Say something, briefly. */
export function say(message, bad = false) {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = message;
  el.classList.toggle('is-bad', bad);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, bad ? 5200 : 2800);
}

/** Show that something slow is happening, and why. */
export function working(on, what = '', why = '') {
  const el = document.getElementById('working');
  if (!el) return;
  el.hidden = !on;
  if (on) {
    el.querySelector('.what').textContent = what;
    el.querySelector('.why').textContent = why;
  }
}

export const kb = (n) =>
  n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.round(n / 1024)} KB`;

export function escapeHTML(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* Where a model came from, in one word — used by every tool that shows a
 * library, so they all group it the same way. */
export function sourceOf(item) {
  const path = item.path || '';
  if (/\/bengkel\/boneka\/sessions\//.test(path)) return 'boneka';
  if (/\/Documents\/bengkel\/([a-z]+)\//.test(path)) {
    return path.match(/\/Documents\/bengkel\/([a-z]+)\//)[1];
  }
  const inProject = path.match(/\/Desktop\/project\/[^/]+\/([^/]+)\//);
  if (inProject && inProject[1] !== 'bengkel') return inProject[1];
  if (/\/Downloads\//.test(path)) return 'Downloads';
  return 'elsewhere';
}
