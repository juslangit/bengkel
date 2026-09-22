/* The studio screen.
 *
 * It knows nothing about boneka or gerak. It asks bengkel what tools exist
 * and draws a card for each, so a third tool appears here the moment it is
 * added to tools.json — no change to this file.
 */

const list = document.getElementById('tools');

function card(tool) {
  const button = document.createElement('button');
  button.className = 'tool';
  button.style.color = tool.accent;
  button.innerHTML = `
    <div class="tool-top">
      <span class="tool-dot"></span>
      <h3>${escape(tool.name)}</h3>
      <span class="state${tool.live ? ' is-live' : ''}">${tool.live ? 'running' : 'ready'}</span>
    </div>
    <p class="tagline">${escape(tool.tagline)}</p>
    <p class="blurb">${escape(tool.blurb)}</p>`;
  button.onclick = () => window.bengkel.open(tool.id);
  return button;
}

function escape(text) {
  return String(text).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

async function draw() {
  if (!window.bengkel) {
    list.innerHTML = '<p class="waiting">This page is the inside of the bengkel app. '
      + 'Open bengkel to use it.</p>';
    return;
  }
  const tools = await window.bengkel.tools();
  list.innerHTML = '';
  for (const tool of tools) list.append(card(tool));
}

/* ── what you are making ────────────────────────────────────────────
 *
 * A piece appears here when you do something deliberate with it — hand it to
 * the other tool, or save a clip. Not when you merely open something: a list
 * of everything you have ever looked at is not a list of what you are making.
 */

const workSection = document.getElementById('work');
const piecesList = document.getElementById('pieces');

const ACCENTS = { boneka: '#b98cf0', gerak: '#f5a524' };

function when(iso) {
  const then = new Date(iso);
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} minute${mins === 1 ? '' : 's'} ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? 'yesterday' : `${days} days ago`;
}

function pieceRow(piece) {
  const row = document.createElement('div');
  row.className = 'piece' + (piece.exists ? '' : ' is-gone');
  row.innerHTML = `
    <div class="piece-main">
      <div class="piece-name">${escape(piece.name)}</div>
      <p class="piece-what">${piece.exists
        ? escape(piece.last) + ' · ' + when(piece.updated)
        : 'the file has moved or gone'}</p>
    </div>
    <div class="piece-tools">${piece.tools.map((t) =>
      `<span style="color:${ACCENTS[t] || '#8ea0bf'}">${escape(t)}</span>`).join('')}</div>`;

  for (const tool of ['boneka', 'gerak']) {
    const go = document.createElement('button');
    go.className = 'piece-go';
    go.textContent = tool;
    go.disabled = !piece.exists;
    go.title = `Open this in ${tool}`;
    go.onclick = () => window.bengkel.openPiece(piece.id, tool);
    row.append(go);
  }

  const drop = document.createElement('button');
  drop.className = 'piece-drop';
  drop.textContent = '×';
  drop.title = 'Forget this — the files are not touched';
  drop.onclick = async () => { await window.bengkel.forgetPiece(piece.id); draw(); };
  row.append(drop);

  return row;
}

async function drawWork() {
  if (!window.bengkel) return;
  const pieces = await window.bengkel.pieces();
  workSection.hidden = pieces.length === 0;
  piecesList.innerHTML = '';
  for (const piece of pieces) piecesList.append(pieceRow(piece));
}

async function drawAll() { await draw(); await drawWork(); }

// bengkel calls this whenever a tool comes up or a piece changes.
window.refreshStudio = drawAll;
window.refreshTools = drawAll;

drawAll();
