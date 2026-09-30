/* hantar — to deliver.
 *
 * Four questions: which game, where in it, called what, and what to fix on
 * the way in. The answers to the first three are read out of the project
 * rather than invented — where it already keeps its models, and how those
 * files are already spelled.
 *
 * The exact path it will land at is shown before anything is written. A
 * delivery you cannot see in advance is one you find out about by looking in
 * Finder afterwards.
 */

import { api, modelURL, say, working, escapeHTML, kb, sourceOf } from '/common/tool.js';
import { inside, onReceive } from '/common/bengkel.js';
import { Stage } from '/web/view.js';

const $ = (s) => document.querySelector(s);
const stage = new Stage($('#stage'));

let model = null;
let projects = [];
let result = null;

const project = () => projects.find((p) => p.id === $('#project').value);

/* Both of these are asked for before the projects have arrived — a model
 * dropped on the window the moment it opens gets there first — so both have
 * to answer "not yet" rather than throwing. */
const place = () => {
  const p = project();
  if (!p || !p.places.length) return null;
  const index = parseInt($('#place').value, 10);
  return p.places[Number.isFinite(index) ? index : 0] || p.places[0];
};

// ── the games ───────────────────────────────────────────────────────

async function loadProjects() {
  const answer = await api('/api/projects');
  projects = answer.projects;
  if (!projects.length) {
    $('#subject').textContent = `No game projects found in ${answer.where}`;
    return;
  }
  $('#project').innerHTML = projects.map((p) =>
    `<option value="${escapeHTML(p.id)}">${escapeHTML(p.name)} — ${escapeHTML(p.engineName)}</option>`).join('');
  $('#project').onchange = pickProject;
  pickProject();
}

function pickProject() {
  const p = project();
  if (!p) return;
  $('#engine-about').textContent = p.about;

  $('#place').innerHTML = p.places.map((q, i) => {
    const how = q.count
      ? `${q.count} already there`
      : q.empty ? 'empty, but made for this' : 'would be new';
    return `<option value="${i}">${escapeHTML(q.shown)} — ${how}</option>`;
  }).join('');
  $('#place').onchange = pickPlace;
  pickPlace();
}

function pickPlace() {
  const q = place();
  if (!q) return;
  // Say what the folder is already called, because that is what the name
  // below is about to be made to match.
  $('#place-about').textContent = q.examples.length
    ? `Already in there: ${q.examples.join(', ')}`
    : q.new ? 'This folder does not exist yet; it will be made.'
      : 'Nothing in there yet.';
  landing();
}

// ── where it will land ──────────────────────────────────────────────

let asking = null;
async function landing() {
  const p = project();
  const q = place();
  if (!p || !q) return;

  clearTimeout(asking);
  asking = setTimeout(async () => {
    const name = $('#name').value.trim() || (model ? model.stem : 'model');
    const answer = await api(`/api/landing?name=${encodeURIComponent(name)}`
      + `&style=${q.style}&engine=${p.engine}&into=${encodeURIComponent(q.path)}`);
    $('#landing').textContent = answer.shown
      + (answer.exists ? '  — already there, sending will replace it' : '');
    $('#landing').classList.toggle('is-taken', answer.exists);
  }, 120);
}

// ── the model ───────────────────────────────────────────────────────

async function open(path, name) {
  working(true, 'Opening it', 'Reading the mesh');
  try {
    await stage.show(modelURL(path));
    const file = name || path.split('/').pop();
    model = { path, name: file, stem: file.replace(/\.[^.]+$/, '') };
    $('#empty').hidden = true;
    $('#label').textContent = file;
    if (!$('#name').value.trim()) $('#name').value = model.stem;
    $('#go').disabled = false;
    $('#report').hidden = true;
    result = null;
    landing();
  } catch (err) {
    say(`Could not open that: ${err.message}`, true);
  } finally {
    working(false);
  }
}

// ── sending ─────────────────────────────────────────────────────────

async function send(overwrite = false) {
  const p = project();
  const q = place();
  if (!model || !p || !q) return;

  working(true, `Sending it to ${p.name}`,
    'Standing it on the floor, sizing it, and exporting in the format that '
    + 'engine takes.');
  $('#go').disabled = true;

  try {
    const answer = await api('/api/send', {
      path: model.path,
      into: q.path,
      engine: p.engine,
      style: q.style,
      name: $('#name').value.trim() || model.stem,
      ground: $('#ground').checked,
      height: parseFloat($('#height').value) || 0,
      overwrite,
    });

    if (!answer.ok) {
      // A file already there is a question, not a failure.
      if (answer.exists && confirm(`${answer.problems[0]}\n\nReplace it?`)) {
        working(false);
        return send(true);
      }
      say((answer.problems || ['it did not go'])[0], true);
      return;
    }

    result = answer;
    report(answer, p);
    say(`${answer.name} is in ${p.name}`);
  } catch (err) {
    say(`It failed: ${err.message}`, true);
  } finally {
    working(false);
    $('#go').disabled = false;
  }
}

function report(answer, p) {
  const size = (a) => a.map((n) => n.toFixed(2)).join(' × ') + ' m';
  $('#report').innerHTML = `
    <h3>It is in ${escapeHTML(p.name)}</h3>
    <p><code>${escapeHTML(answer.name)}</code> — ${kb(answer.bytes)}, ${answer.seconds}s.</p>
    ${answer.fixed && answer.fixed.length
      ? `<ul>${answer.fixed.map((f) => `<li>${escapeHTML(f)}</li>`).join('')}</ul>`
      : '<p class="quiet">Nothing needed fixing on the way in.</p>'}
    <p class="quiet">${escapeHTML(size(answer.was))} in, ${escapeHTML(size(answer.now))} out.</p>
    <p class="where">${escapeHTML(answer.shown)}</p>
    <button class="btn btn-small btn-wide" id="reveal">Show me the folder</button>`;
  $('#report').hidden = false;
  $('#reveal').onclick = () => api('/api/reveal', { path: answer.folder });
  landing();
}

// ── picking a model ─────────────────────────────────────────────────

let libraryItems = [];

async function openSheet() {
  $('#sheet').hidden = false;
  $('#find').value = '';
  $('#find').focus();
  $('#sheet-list').innerHTML = '<p class="quiet" style="padding:14px">Looking…</p>';
  libraryItems = (await api('/api/library')).items;
  paintSheet();
}

function paintSheet() {
  const want = $('#find').value.trim().toLowerCase();
  const shown = libraryItems
    .filter((i) => !want || i.name.toLowerCase().includes(want)
      || (i.folder || '').toLowerCase().includes(want))
    .slice(0, 300);
  if (!shown.length) {
    $('#sheet-list').innerHTML = '<p class="quiet" style="padding:14px">Nothing matches.</p>';
    return;
  }
  $('#sheet-list').innerHTML = shown.map((item, index) => `
    <button class="pick" data-index="${index}">
      <span class="n">${escapeHTML(item.name)}</span>
      <span class="w">${escapeHTML(sourceOf(item))}</span>
      <span class="t">${kb(item.size)}</span>
    </button>`).join('');
  $('#sheet-list').querySelectorAll('.pick').forEach((button) => {
    button.onclick = () => {
      const item = shown[parseInt(button.dataset.index, 10)];
      $('#sheet').hidden = true;
      open(item.path, item.name);
    };
  });
}

// ── wiring ──────────────────────────────────────────────────────────

$('#go').onclick = () => send(false);
$('#open').onclick = openSheet;
$('#name').oninput = landing;
$('#sheet-close').onclick = () => { $('#sheet').hidden = true; };
$('#find').oninput = paintSheet;
$('#sheet').onclick = (e) => { if (e.target.id === 'sheet') $('#sheet').hidden = true; };
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') $('#sheet').hidden = true;
});

document.addEventListener('dragover', (e) => { e.preventDefault(); $('#drop').hidden = false; });
document.addEventListener('dragleave', (e) => { if (e.relatedTarget === null) $('#drop').hidden = true; });
document.addEventListener('drop', async (e) => {
  e.preventDefault();
  $('#drop').hidden = true;
  const file = e.dataTransfer.files[0];
  if (!file || !file.path) { say('Drop it from Finder, or use Open a model', true); return; }
  await api('/api/permit', { path: file.path });
  open(file.path, file.name);
});

onReceive(({ path, name }) => open(path, name));

loadProjects();

// Exposed for the tests, which drive this the way a person would.
window.hantar = {
  open, send, stage,
  setProject: (id) => { $('#project').value = id; pickProject(); },
  setName: (n) => { $('#name').value = n; landing(); },
  state: () => ({ model, result, projects: projects.length,
                  project: $('#project').value, place: place(),
                  landing: $('#landing').textContent }),
};


/* ── what the assistant may do here ──────────────────────────────────
 *
 * bengkel injects a floating assistant into every tool it hosts. It cannot
 * write code or touch anything on its own: it may only call the actions
 * listed here, which are the things this tool already does. That is what
 * makes them undoable — `snapshot` photographs everything an action could
 * change, and `restore` puts it back.
 *
 * `risky: true` means it reaches outside the tool, and bengkel always asks
 * before running one however sure the assistant is.
 *
 * None of this happens when the tool is run on its own.
 */
if (window.bengkel && window.bengkel.assist) window.bengkel.assist({
  tool: 'hantar',
  about: 'puts a finished model into one of the game projects, under that '
       + 'project\'s own naming, standing on the floor, in the right format.',
  context: () => {
    const s = window.hantar.state();
    return {
      model: s.model && s.model.name,
      project: s.project,
      projects_available: s.projects,
      name: $('#name') ? $('#name').value : '',
      landing: s.landing,
      sent: !!s.result,
    };
  },
  snapshot: () => ({
    project: $('#project') ? $('#project').value : '',
    name: $('#name') ? $('#name').value : '',
    height: $('#height') ? $('#height').value : null,
    ground: $('#ground') ? $('#ground').checked : null,
  }),
  restore: (shot) => {
    if ($('#project') && shot.project) window.hantar.setProject(shot.project);
    if ($('#name')) window.hantar.setName(shot.name);
    if ($('#height') && shot.height !== null) {
      $('#height').value = shot.height;
      $('#height').dispatchEvent(new Event('input'));
    }
    if ($('#ground') && shot.ground !== null) {
      $('#ground').checked = shot.ground;
      $('#ground').dispatchEvent(new Event('change'));
    }
  },
  actions: {
    chooseProject: {
      what: 'Pick which game project the model is going to',
      args: { project: 'the id of a project from projects_available' },
      run: async ({ project }) => { window.hantar.setProject(project); return project; },
    },
    setName: {
      what: 'Set the name the model will have inside the game',
      args: { name: 'the file name, without an extension' },
      run: async ({ name }) => { window.hantar.setName(name); return name; },
    },
    setHeight: {
      what: 'Set how tall the model should be in the game, in metres',
      args: { metres: 'a number' },
      run: async ({ metres }) => {
        const el = $('#height');
        if (!el) throw new Error('no height box on this page');
        el.value = String(metres);
        el.dispatchEvent(new Event('input'));
        return `${el.value} m`;
      },
    },
    ship: {
      what: 'Copy the model into the chosen game project',
      args: {},
      risky: true,
      warn: 'This writes the model into a game project\'s own folder.',
      run: async () => { await window.hantar.send(); return 'sent'; },
    },
  },
});
