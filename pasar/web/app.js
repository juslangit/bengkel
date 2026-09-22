/* pasar — the market.
 *
 * It knows nothing about Sketchfab, Poly Haven or Texturelabs. It asks its own
 * server what libraries are reachable and draws a chip for each, so a fourth
 * library appears here the moment the server can search it.
 */

import { api, say, working, escapeHTML, kb } from '/common/tool.js';
import { inside, tools as workshopTools, handOver, note as noteWork } from '/common/bengkel.js';

const $ = (s) => document.querySelector(s);
const results = $('#results');

let sources = [];
let showing = 'search';

// ── which libraries are here ────────────────────────────────────────

async function loadSources() {
  const answer = await api('/api/sources');
  sources = answer.sources;
  const where = $('#where');
  where.innerHTML = '<button class="seg-btn is-on" data-where="all">Everything</button>'
    + sources.filter((s) => s.ready).map((s) =>
      `<button class="seg-btn" data-where="${s.id}">${escapeHTML(s.name)}</button>`).join('');
  where.querySelectorAll('.seg-btn').forEach((b) => {
    b.onclick = () => {
      where.querySelectorAll('.seg-btn').forEach((x) => x.classList.toggle('is-on', x === b));
      if ($('#q').value.trim()) search();
    };
  });

  const missing = sources.filter((s) => !s.ready);
  if (missing.length) {
    $('#note').textContent = `${missing.map((s) => s.name).join(' and ')} `
      + `could not be reached — the rest still work.`;
  }
}

const accentOf = (id) => (sources.find((s) => s.id === id) || {}).accent || '#8ea0bf';

// ── searching ───────────────────────────────────────────────────────

async function search() {
  const q = $('#q').value.trim();
  const where = $('#where .is-on').dataset.where;
  showing = 'search';
  paintTabs();

  results.innerHTML = '<p class="empty">Looking…</p>';
  try {
    const found = await api(`/api/search?q=${encodeURIComponent(q)}&where=${where}`);
    draw(found.results, q);
    if (found.problems.length) say(found.problems.join(' · '), true);
  } catch (err) {
    results.innerHTML = `<p class="empty">That search did not work: ${escapeHTML(err.message)}</p>`;
  }
}

function draw(found, q) {
  if (!found.length) {
    results.innerHTML = `<p class="empty">Nothing for “${escapeHTML(q)}”. `
      + `Try a plainer word — “chair” finds more than “office chair with wheels”.</p>`;
    return;
  }
  results.innerHTML = '';
  for (const item of found) results.append(card(item));
}

function card(item) {
  const el = document.createElement('div');
  el.className = 'find';
  const careful = !item.safe;
  el.innerHTML = `
    <div class="find-shot" style="background-image:url('${escapeHTML(item.thumb)}')">
      <span class="where" style="color:${accentOf(item.source)}">${escapeHTML(item.source)}</span>
    </div>
    <div class="find-body">
      <div class="find-title">${escapeHTML(item.title)}</div>
      ${item.by ? `<div class="find-by">by ${escapeHTML(item.by)}</div>` : ''}
      ${item.detail ? `<div class="find-detail">${escapeHTML(item.detail)}</div>` : ''}
      <div class="find-licence${careful ? ' is-careful' : ''}">${escapeHTML(item.licence)}</div>
    </div>`;

  const actions = document.createElement('div');
  actions.className = 'find-actions';
  actions.style.padding = '0 13px 13px';

  const get = document.createElement('button');
  get.className = 'btn btn-primary btn-small';
  get.textContent = 'Bring it home';
  get.onclick = () => fetchIt(item, get);
  actions.append(get);

  if (item.page) {
    const look = document.createElement('a');
    look.className = 'btn btn-small';
    look.textContent = 'Look';
    look.href = item.page;
    look.target = '_blank';
    look.rel = 'noopener';
    look.style.justifyContent = 'center';
    actions.append(look);
  }

  el.append(actions);
  return el;
}

// ── bringing something home ─────────────────────────────────────────

async function fetchIt(item, button) {
  button.disabled = true;
  const was = button.textContent;
  button.textContent = 'Fetching…';
  working(true, `Fetching ${item.title}`,
    item.source === 'sketchfab' ? 'Sketchfab models can be large.' : '');
  try {
    const got = await api('/api/get', item);
    if (!got.ok) throw new Error(got.problem);
    say(`${item.title} is in the workshop — ${got.shown}`);
    await noteWork({ path: got.path, name: item.title, what: `brought it in from ${item.source}` });
    if (got.model) offerNext(got, item);
  } catch (err) {
    say(`Could not fetch it: ${err.message}`, true);
  } finally {
    working(false);
    button.textContent = was;
    button.disabled = false;
  }
}

/* A model that has just arrived has an obvious next step, and the whole point
 * of the workshop is that it is one press away rather than a trip to Finder. */
async function offerNext(got, item) {
  if (!inside) return;
  const here = await workshopTools();
  const next = here.find((t) => t.id === 'gerak');
  if (!next) return;
  say(`${item.title} is in — opening it in gerak.`);
  await handOver('gerak', got.path, item.title);
}

// ── what is already here ────────────────────────────────────────────

async function showMine() {
  showing = 'mine';
  paintTabs();
  results.innerHTML = '<p class="empty">Looking…</p>';
  const { items } = await api('/api/mine');
  if (!items.length) {
    results.innerHTML = '<p class="empty">Nothing brought home yet. '
      + 'Search for something above.</p>';
    return;
  }
  results.innerHTML = '';
  for (const item of items) {
    const el = document.createElement('div');
    el.className = 'find';
    el.innerHTML = `
      <div class="find-body">
        <div class="find-title">${escapeHTML(item.title)}</div>
        <div class="find-by">${escapeHTML(item.source)} · ${kb(item.bytes)}</div>
        <div class="find-detail">${escapeHTML(item.shown)}</div>
      </div>`;
    const actions = document.createElement('div');
    actions.className = 'find-actions';
    actions.style.padding = '0 13px 13px';
    if (item.model && inside) {
      const go = document.createElement('button');
      go.className = 'btn btn-primary btn-small';
      go.textContent = 'Open in gerak';
      go.onclick = () => handOver('gerak', item.path, item.title);
      actions.append(go);
    }
    const show = document.createElement('button');
    show.className = 'btn btn-small';
    show.textContent = 'Show in Finder';
    show.onclick = () => api('/api/reveal', { path: item.path });
    actions.append(show);
    el.append(actions);
    results.append(el);
  }
}

function paintTabs() {
  $('#tab-search').classList.toggle('btn-primary', showing === 'search');
  $('#tab-mine').classList.toggle('btn-primary', showing === 'mine');
}

// ── go ──────────────────────────────────────────────────────────────

$('#go').onclick = search;
$('#q').addEventListener('keydown', (e) => { if (e.key === 'Enter') search(); });
$('#tab-search').onclick = () => { showing = 'search'; paintTabs(); search(); };
$('#tab-mine').onclick = showMine;

window.__toolCommand = (name) => {
  if (name === 'rescan') return search();
  return false;
};

window.pasar = { search, showMine, api, get state() { return { sources, showing }; } };

paintTabs();
loadSources();
