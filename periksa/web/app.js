/* periksa — to inspect.
 *
 * Reads the file and says what is worth saying about it. Three levels: what
 * is wrong, what to watch, and what is already fine — the last folded away,
 * because it is reassurance rather than news.
 *
 * Nothing here grades a model. A 400,000 triangle mesh is right for a
 * cinematic and hopeless for a crowd, so every finding says what it found,
 * why it matters and what to do, and leaves the judgement where it belongs.
 */

import { api, modelURL, say, working, escapeHTML, kb, sourceOf } from '/common/tool.js';
import { inside, offerHandOff, onReceive } from '/common/bengkel.js';
import { Stage } from '/web/view.js';

const $ = (s) => document.querySelector(s);
const stage = new Stage($('#stage'));

let model = null;
let role = 'prop';
let roles = [];
let report = null;

// ── what the thing is for ───────────────────────────────────────────

async function loadRoles() {
  roles = (await api('/api/roles')).roles;
  $('#role').innerHTML = roles.map((r) =>
    `<button class="seg-btn ${r.id === role ? 'is-on' : ''}" data-role="${r.id}"
      title="${escapeHTML(r.about)} — about ${r.tris.toLocaleString()} triangles"
      >${escapeHTML(r.name)}</button>`).join('');
  $('#role').querySelectorAll('.seg-btn').forEach((b) => {
    b.onclick = () => {
      role = b.dataset.role;
      $('#role').querySelectorAll('.seg-btn')
        .forEach((x) => x.classList.toggle('is-on', x === b));
      // The budget changed, so what is worth saying changed with it.
      if (model) look(model.path, model.name);
    };
  });
}

// ── looking ─────────────────────────────────────────────────────────

async function look(path, name) {
  working(true, 'Reading it', 'Not opening it — reading the description at the front of the file');
  try {
    const answer = await api(`/api/look?path=${encodeURIComponent(path)}&role=${role}`);
    if (!answer.ok) { say(answer.problem, true); return; }

    model = { path, name: name || answer.name };
    report = answer;

    // Show it too. The findings are about size and where the origin sits, and
    // the only way to believe those is to see it standing on a ruled floor.
    try {
      await stage.show(modelURL(path));
      $('#empty').hidden = true;
    } catch {
      $('#empty').hidden = false;
    }

    $('#label').textContent = `${answer.name} · ${answer.facts.triangles.toLocaleString()} triangles`;
    paint(answer);
    offerHandOff($('#send'), 'gerak', () => path, 'Animate it in gerak');
  } catch (err) {
    say(`Could not read that: ${err.message}`, true);
  } finally {
    working(false);
  }
}

function paint(answer) {
  const { bad, watch } = answer.counts;

  const level = bad ? 'bad' : watch ? 'watch' : 'good';
  const headline = bad
    ? `${bad} thing${bad === 1 ? '' : 's'} to fix first`
    : watch
      ? `${watch} thing${watch === 1 ? '' : 's'} worth a look`
      : 'Nothing standing in its way';
  const under = bad
    ? 'These will cost you an afternoon in the engine if they go in as they are.'
    : watch
      ? 'None of these is wrong. They are the ones that are usually a mistake.'
      : `Fine as a ${(roles.find((r) => r.id === role) || {}).name.toLowerCase()}.`;

  $('#verdict').className = `verdict is-${level}`;
  $('#verdict').innerHTML = `<span class="big">${escapeHTML(headline)}</span>`
    + `<span class="small">${escapeHTML(under)}</span>`;
  $('#verdict').hidden = false;

  const card = (f) => `
    <div class="finding is-${f.level}">
      <div class="what">${escapeHTML(f.what)}</div>
      <p class="why">${escapeHTML(f.why)}</p>
      ${f.todo ? `<p class="todo">${escapeHTML(f.todo)}</p>` : ''}
    </div>`;

  const loud = answer.findings.filter((f) => f.level !== 'good');
  const fine = answer.findings.filter((f) => f.level === 'good');

  $('#findings').innerHTML = loud.map(card).join('')
    + (fine.length ? `
      <details class="fine">
        <summary>${fine.length} thing${fine.length === 1 ? ' that is' : 's that are'} already fine</summary>
        <div class="findings">${fine.map(card).join('')}</div>
      </details>` : '');

  const f = answer.facts;
  const size = f.extent
    ? f.extent.map((n) => n.toFixed(2)).join(' × ') + ' m' : 'unknown';
  const rows = [
    ['Triangles', f.triangles.toLocaleString()],
    ['Size', size],
    ['Meshes', f.meshes],
    ['Materials', f.materials],
    ['Textures', f.images],
    ['Bones', f.bones || '—'],
    ['Clips', f.animations.length || '—'],
    ['On disk', kb(f.bytes)],
    ['Made by', f.generator || 'unknown'],
  ];
  $('#facts').innerHTML = rows.map(([k, v]) =>
    `<dt>${k}</dt><dd>${escapeHTML(String(v))}</dd>`).join('');
  $('#facts').hidden = false;
}

// ── picking a model ─────────────────────────────────────────────────

let libraryItems = [];

async function openSheet() {
  $('#sheet').hidden = false;
  $('#find').value = '';
  $('#find').focus();
  $('#sheet-list').innerHTML = '<p class="quiet" style="padding:14px">Looking…</p>';
  // Only .glb: periksa reads the description at the front of one, and there
  // is no such thing in an .fbx or a .blend.
  libraryItems = (await api('/api/library')).items.filter((i) => i.ext === 'glb');
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
      look(item.path, item.name);
    };
  });
}

// ── wiring ──────────────────────────────────────────────────────────

$('#open').onclick = openSheet;
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
  look(file.path, file.name);
});

onReceive(({ path, name }) => look(path, name));

loadRoles();

// Exposed for the tests, which drive this the way a person would.
window.periksa = {
  look, setRole: (r) => { role = r; },
  state: () => ({ model, role, report, roles: roles.length }),
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
  tool: 'periksa',
  about: 'reads a model\'s size, origin, weight and UVs straight out of the '
       + '.glb and judges them against what the model is for.',
  context: () => {
    const s = window.periksa.state();
    return {
      model: s.model && s.model.name,
      role: s.role,
      roles_available: s.roles,
      findings: s.report && (s.report.findings || []).map((f) => f.what || f),
    };
  },
  snapshot: () => ({ role: window.periksa.state().role }),
  restore: (shot) => {
    window.periksa.setRole(shot.role);
    if ($('#role')) $('#role').value = shot.role;
  },
  actions: {
    setRole: {
      what: 'Say what the model is for, which is what it is judged against',
      args: { role: 'one of the roles listed in roles_available' },
      run: async ({ role }) => {
        window.periksa.setRole(role);
        if ($('#role')) { $('#role').value = role; $('#role').dispatchEvent(new Event('change')); }
        return role;
      },
    },
  },
});
