/* kulit — the skin.
 *
 * One row per part of the model. Pick a part, give it a colour and say what
 * it is made of. The colour appears on the model as you click it, because
 * choosing a colour by imagining it is not choosing.
 *
 * The material itself is not previewed. Deriving a normal map and a roughness
 * map from a photograph is image work that belongs in Blender, and pretending
 * otherwise with a plausible-looking fake would be worse than being plain
 * about the split: colour now, surface when you press the button.
 */

import { api, modelURL, say, working, escapeHTML, kb, sourceOf } from '/common/tool.js';
import { inside, offerHandOff, note as noteWork, onReceive } from '/common/bengkel.js';
import { Stage } from '/web/view.js';

const $ = (s) => document.querySelector(s);
const stage = new Stage($('#stage'));

let model = null;         // { path, name }
let parts = [];           // [{ name, triangles, colour, surface, scale }]
let chosen = null;        // the part being edited
let surfaces = [];
let palettes = [];
let result = null;

// ── the model ───────────────────────────────────────────────────────

async function open(path, name) {
  working(true, 'Opening it', 'Reading the mesh and its parts');
  try {
    const found = await stage.show(modelURL(path));
    model = { path, name: name || path.split('/').pop() };
    parts = found.map((p) => ({ ...p, surface: 'detail', scale: 1 }));
    chosen = parts.length ? parts[0].name : null;

    $('#empty').hidden = true;
    $('#palette-block').hidden = false;
    $('#go').disabled = !parts.length;
    $('#label').textContent = `${model.name} · ${parts.length} `
      + `${parts.length === 1 ? 'part' : 'parts'}`;
    $('#report').hidden = true;
    $('#send').hidden = true;
    result = null;
    paintParts();
  } catch (err) {
    say(`Could not open that: ${err.message}`, true);
  } finally {
    working(false);
  }
}

// ── the rows ────────────────────────────────────────────────────────

function paintParts() {
  if (!parts.length) {
    $('#parts').innerHTML = '<p class="quiet">That model has no meshes in it.</p>';
    return;
  }

  $('#parts').innerHTML = parts.map((part) => `
    <div class="part ${part.name === chosen ? 'is-on' : ''}" data-name="${escapeHTML(part.name)}">
      <div class="part-head">
        <span class="part-dot" style="background:${part.colour}"></span>
        <span class="part-name" title="${escapeHTML(part.name)}">${escapeHTML(part.name)}</span>
        <span class="part-tris">${part.triangles.toLocaleString()}</span>
      </div>
      <div class="part-row">
        <select data-field="surface">
          ${surfaces.map((s) => `<option value="${s.id}"
            ${s.id === part.surface ? 'selected' : ''}
            ${s.ready ? '' : 'disabled'}>${escapeHTML(s.name)}${s.ready ? '' : ' — no photograph'}</option>`).join('')}
        </select>
      </div>
      <div class="part-row">
        <input type="range" data-field="scale" min="0.25" max="8" step="0.25" value="${part.scale}">
        <span class="n">${part.scale}×</span>
      </div>
    </div>`).join('');

  $('#parts').querySelectorAll('.part').forEach((row) => {
    const part = parts.find((p) => p.name === row.dataset.name);
    row.onclick = (e) => {
      if (e.target.closest('select, input')) return;
      choose(part.name);
    };
    row.querySelector('[data-field="surface"]').onchange = (e) => {
      part.surface = e.target.value;
      choose(part.name);
    };
    row.querySelector('[data-field="scale"]').oninput = (e) => {
      part.scale = parseFloat(e.target.value);
      row.querySelector('.n').textContent = `${part.scale}×`;
    };
  });

  const about = surfaces.find((s) => s.id === (parts.find((p) => p.name === chosen) || {}).surface);
  if (about) $('#subject').textContent = about.about;
}

function choose(name) {
  chosen = name;
  stage.highlight(name);
  paintParts();
}

stage.onPick = (name) => { if (name) choose(name); };

// ── colours ─────────────────────────────────────────────────────────

async function loadPalettes() {
  palettes = (await api('/api/palettes')).palettes;
  if (!palettes.length) {
    $('#palette-block').innerHTML = '<p class="quiet">No palettes found — '
      + "boneka's palettes folder is where they live.</p>";
    return;
  }
  $('#palette').innerHTML = palettes.map((p) =>
    `<option value="${p.slug}">${escapeHTML(p.name)}</option>`).join('');
  $('#palette').onchange = paintSwatches;
  paintSwatches();
}

function paintSwatches() {
  const palette = palettes.find((p) => p.slug === $('#palette').value) || palettes[0];
  $('#swatches').innerHTML = palette.colors.map((c) =>
    `<button class="swatch" style="background:${c}" data-colour="${c}" title="${c}"></button>`).join('');
  $('#swatches').querySelectorAll('.swatch').forEach((button) => {
    button.onclick = () => {
      const part = parts.find((p) => p.name === chosen);
      if (!part) { say('Pick a part first', true); return; }
      part.colour = button.dataset.colour;
      stage.paint(part.name, part.colour);
      paintParts();
    };
  });
}

// ── dressing it ─────────────────────────────────────────────────────

async function dress() {
  if (!model || !parts.length) return;
  working(true, 'Dressing it in Blender',
    'Deriving a detail, normal and roughness map from each photograph, then '
    + 'building the materials and exporting.');
  $('#go').disabled = true;

  try {
    const answer = await api('/api/dress', {
      path: model.path,
      parts: parts.map((p) => ({
        name: p.name, colour: p.colour, surface: p.surface, scale: p.scale,
      })),
    });

    if (!answer.ok) {
      say((answer.problems || ['Blender would not do it'])[0], true);
      return;
    }

    result = answer;
    await stage.show(modelURL(answer.glb));
    stage.highlight(null);
    report(answer);
    offerHandOff($('#send'), 'gerak', () => answer.glb, 'Animate it in gerak');
    noteWork(`dressed ${model.name}`);
    say(`Dressed in ${answer.seconds}s`);
  } catch (err) {
    say(`It failed: ${err.message}`, true);
  } finally {
    working(false);
    $('#go').disabled = false;
  }
}

function report(answer) {
  const used = [...new Set(answer.dressed.map((d) => d.surface))];
  $('#report').innerHTML = `
    <h3>What it did</h3>
    <p>${answer.dressed.length} ${answer.dressed.length === 1 ? 'part' : 'parts'}
       dressed in ${escapeHTML(used.join(', '))} — ${kb(answer.bytes)}, ${answer.seconds}s.</p>
    ${(answer.notes || []).map((n) => `<p class="caution">${escapeHTML(n)}</p>`).join('')}
    <p class="licence"><b>The maps in this file come from Texturelabs.</b>
      Using it inside a finished game is fine. Handing someone the
      <code>.glb</code> is not, and it must not go into a public repository.
      The full wording is in <code>WHAT-IS-IN-IT.md</code> beside it.</p>
    <p class="where">${escapeHTML(answer.shown)}</p>
    <button class="btn btn-small btn-wide" id="reveal">Show me the folder</button>`;
  $('#report').hidden = false;
  $('#reveal').onclick = () => api('/api/reveal', { path: answer.folder });
}

// ── picking a model ─────────────────────────────────────────────────

let libraryItems = [];

async function openSheet() {
  $('#sheet').hidden = false;
  $('#find').value = '';
  $('#find').focus();
  $('#sheet-list').innerHTML = '<p class="quiet" style="padding:14px">Looking…</p>';
  libraryItems = await api('/api/library');
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

async function showMine() {
  $('#sheet').hidden = false;
  $('#find').value = '';
  const { items } = await api('/api/mine');
  libraryItems = items.map((i) => ({ ...i, folder: i.shown, size: i.bytes }));
  paintSheet();
  if (!items.length) {
    $('#sheet-list').innerHTML = '<p class="quiet" style="padding:14px">'
      + 'Nothing yet. Dress something and it will be here.</p>';
  }
}

// ── wiring ──────────────────────────────────────────────────────────

$('#go').onclick = dress;
$('#open').onclick = openSheet;
$('#tab-mine').onclick = showMine;
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

(async () => {
  const answer = await api('/api/surfaces');
  surfaces = answer.surfaces;
  if (!answer.any) {
    say('No texture photographs found — everything will come out flat colour', true);
  }
  await loadPalettes();
  paintParts();
})();

// Exposed for the tests, which drive this the way a person would.
window.kulit = {
  open, dress, choose,
  state: () => ({ model, parts, chosen, result, surfaces: surfaces.length }),
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
  tool: 'kulit',
  about: 'gives a model a colour and a material per part, with detail, normal '
       + 'and roughness maps derived from one photograph.',
  context: () => {
    const s = window.kulit.state();
    return {
      model: s.model && s.model.name,
      parts: (s.parts || []).map((p) => ({ name: p.name, colour: p.colour,
                                           surface: p.surface })),
      chosen: s.chosen,
      surfaces_available: s.surfaces,
      done: !!s.result,
    };
  },
  snapshot: () => ({ chosen: window.kulit.state().chosen }),
  restore: (shot) => { if (shot.chosen) window.kulit.choose(shot.chosen); },
  actions: {
    choosePart: {
      what: 'Pick which part of the model to work on',
      args: { part: 'the name of the part, as listed in parts' },
      run: async ({ part }) => { window.kulit.choose(part); return part; },
    },
    dress: {
      what: 'Apply the colours and materials to the model. Writes files',
      args: {},
      risky: true,
      warn: 'This bakes the textures and writes a new model to disk.',
      run: async () => { await window.kulit.dress(); return 'done'; },
    },
  },
});
