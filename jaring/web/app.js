/* jaring — the net.
 *
 * One question, asked in centimetres: how wide should one square of the new
 * surface be? Everything else follows from that, and the page's job is to make
 * the consequence visible before the minute of Blender rather than after it.
 */

import { api, modelURL, say, working, escapeHTML, kb, sourceOf } from '/common/tool.js';
import { inside, offerHandOff, note as noteWork, onReceive } from '/common/bengkel.js';
import { Stage } from '/web/view.js';

const $ = (s) => document.querySelector(s);

const stage = new Stage($('#stage'));

let model = null;        // { path, name, shown, triangles, area }
let presets = [];
let result = null;

// ── the model on the bench ──────────────────────────────────────────

async function open(path, name) {
  working(true, 'Opening it', 'Reading the mesh and measuring its surface');
  try {
    const measured = await stage.left.show(modelURL(path));
    stage.frame();
    stage.right.clear();
    $('#after-empty').hidden = false;
    $('#count-after').textContent = '—';
    $('#count-after').classList.remove('is-good');
    $('#report').hidden = true;
    result = null;
    $('#send').hidden = true;

    model = {
      path,
      name: name || path.split('/').pop(),
      triangles: measured.triangles,
      area: measured.area,
    };

    $('#count-before').textContent = `${measured.triangles.toLocaleString()} triangles`;
    $('#chosen').innerHTML = `
      <div class="file">${escapeHTML(model.name)}</div>
      <div class="where">${escapeHTML(path.replace(/^\/Users\/[^/]+/, '~'))}</div>
      <div class="facts">${measured.triangles.toLocaleString()} triangles ·
        ${measured.area.toFixed(2)} m² of surface</div>`;
    $('#go').disabled = false;
    estimate();
  } catch (err) {
    say(`Could not open that: ${err.message}`, true);
  } finally {
    working(false);
  }
}

// ── how fine ────────────────────────────────────────────────────────

async function loadPresets() {
  presets = (await api('/api/presets')).presets;
  $('#presets').innerHTML = presets.map((p) => `
    <button class="preset" data-id="${p.id}" title="${escapeHTML(p.about)}">
      <span class="n">${escapeHTML(p.name)}</span>
      <span class="s">${p.quad_cm} cm</span>
    </button>`).join('');

  $('#presets').querySelectorAll('.preset').forEach((button) => {
    button.onclick = () => usePreset(button.dataset.id);
  });
  usePreset('game');
}

function usePreset(id) {
  const preset = presets.find((p) => p.id === id);
  if (!preset) return;
  $('#quad').value = preset.quad_cm;
  $('#texture').value = String(preset.texture);
  $('#lods').value = String(preset.lods);
  paintPreset();
  estimate();
}

/* The preset cards light up when the settings happen to match one, and go dark
 * the moment the slider moves off it — they are a starting point, not a mode. */
function paintPreset() {
  const quad = parseFloat($('#quad').value);
  $('#presets').querySelectorAll('.preset').forEach((button) => {
    const preset = presets.find((p) => p.id === button.dataset.id);
    button.classList.toggle('is-on', preset && Math.abs(preset.quad_cm - quad) < 0.05);
  });
}

/* What that quad size will cost, in faces, for this particular model.
 *
 * The same arithmetic the remesher will do, done here so the number moves
 * while he drags rather than appearing after a minute of Blender.
 */
let estimating = null;
async function estimate() {
  const quad = parseFloat($('#quad').value);
  $('#quad-out').textContent = `${quad.toFixed(1)} cm`;
  paintPreset();

  if (!model) {
    $('#estimate').innerHTML = 'How wide one square of the new surface should '
      + 'be. A 2 cm quad on a person-sized model is about a knuckle.';
    return;
  }

  clearTimeout(estimating);
  estimating = setTimeout(async () => {
    const { faces } = await api(`/api/estimate?area=${model.area}&quad_cm=${quad}`);
    const share = Math.round((faces / Math.max(model.triangles, 1)) * 100);
    $('#estimate').innerHTML =
      `Roughly <b>${faces.toLocaleString()}</b> quads — about `
      + `<b>${share}%</b> of what it is now. `
      + (share > 90
        ? 'That is barely a reduction; try a wider quad.'
        : share < 2
          ? 'That is very coarse — fine for something far away.'
          : 'The exact count will differ a little; Quadriflow decides.');
  }, 90);
}

// ── doing it ────────────────────────────────────────────────────────

async function remesh() {
  if (!model) return;
  const texture = parseInt($('#texture').value, 10);

  working(true, 'Remeshing in Blender',
    'Rebuilding the surface, unwrapping it, and baking the detail into a map. '
    + 'A heavy model takes a few minutes.');
  $('#go').disabled = true;

  try {
    const answer = await api('/api/remesh', {
      path: model.path,
      quad_cm: parseFloat($('#quad').value),
      texture: texture || 1024,
      bake: texture > 0,
      lods: parseInt($('#lods').value, 10),
      symmetry: $('#symmetry').checked,
      sharp: $('#sharp').checked,
    });

    if (!answer.ok) {
      say((answer.problems || ['Blender would not do it'])[0], true);
      return;
    }

    result = answer;
    // No re-framing: the camera stays exactly where it was, which is the only
    // way the two halves are a comparison rather than two pictures.
    await stage.right.show(modelURL(answer.glb));
    $('#after-empty').hidden = true;

    const count = $('#count-after');
    const lighter = answer.saved > 0;
    count.textContent = `${answer.after.toLocaleString()} triangles · `
      + `${Math.abs(answer.saved)}% ${lighter ? 'lighter' : 'heavier'}`;
    count.classList.toggle('is-good', lighter);
    count.classList.toggle('is-careful', !lighter);

    report(answer);
    offerHandOff($('#send'), 'gerak', () => answer.glb, 'Animate it in gerak');
    noteWork(`remeshed ${model.name} to ${answer.after.toLocaleString()} triangles`);
    say(lighter
      ? `Done in ${answer.seconds}s — ${answer.saved}% lighter`
      : `Done in ${answer.seconds}s, but it came out heavier — try a wider quad`,
      !lighter);
  } catch (err) {
    say(`It failed: ${err.message}`, true);
  } finally {
    working(false);
    $('#go').disabled = false;
  }
}

function report(answer) {
  const lods = (answer.lods || []).length > 1
    ? `<dt>Distance versions</dt><dd>${answer.lods.slice(1).map((l) =>
        `LOD${l.level} ${l.tris.toLocaleString()}`).join(', ')}</dd>`
    : '';

  $('#report').innerHTML = `
    <h3>What it did</h3>
    <dl>
      <dt>Triangles</dt><dd>${answer.before.toLocaleString()} → ${answer.after.toLocaleString()}</dd>
      <dt>Remeshed with</dt><dd>${answer.how}</dd>
      <dt>UV islands fill</dt><dd>${answer.coverage}% of the map</dd>
      <dt>Normal map</dt><dd>${answer.normal ? 'baked' : 'none'}</dd>
      ${lods}
      <dt>Took</dt><dd>${answer.seconds}s</dd>
    </dl>
    ${(answer.notes || []).map((n) => `<p class="caution">${escapeHTML(n)}</p>`).join('')}
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
      || i.folder.toLowerCase().includes(want))
    .slice(0, 300);

  if (!shown.length) {
    $('#sheet-list').innerHTML = '<p class="quiet" style="padding:14px">'
      + 'Nothing matches. Anything you bring home with pasar turns up here.</p>';
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

// ── what it has already made ────────────────────────────────────────

async function showMine() {
  $('#sheet').hidden = false;
  $('#find').value = '';
  const { items } = await api('/api/mine');
  libraryItems = items.map((i) => ({ ...i, folder: i.shown, size: i.bytes }));
  paintSheet();
  if (!items.length) {
    $('#sheet-list').innerHTML = '<p class="quiet" style="padding:14px">'
      + 'Nothing yet. Remesh something and it will be here.</p>';
  }
}

// ── wiring ──────────────────────────────────────────────────────────

$('#quad').oninput = estimate;
$('#texture').onchange = paintPreset;
$('#lods').onchange = paintPreset;
$('#go').onclick = remesh;
$('#open').onclick = openSheet;
$('#tab-mine').onclick = showMine;
$('#sheet-close').onclick = () => { $('#sheet').hidden = true; };
$('#find').oninput = paintSheet;
$('#sheet').onclick = (e) => { if (e.target.id === 'sheet') $('#sheet').hidden = true; };

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') $('#sheet').hidden = true;
  if (e.key === 'Enter' && e.metaKey && !$('#go').disabled) remesh();
});

// A model dropped on the window is the fastest way in, and the one people try
// first. The server has to be told it may read that path: it is not in any of
// the folders it scans.
document.addEventListener('dragover', (e) => {
  e.preventDefault();
  $('#drop').hidden = false;
});
document.addEventListener('dragleave', (e) => {
  if (e.relatedTarget === null) $('#drop').hidden = true;
});
document.addEventListener('drop', async (e) => {
  e.preventDefault();
  $('#drop').hidden = true;
  const file = e.dataTransfer.files[0];
  if (!file) return;
  const path = file.path || (window.bengkel && await window.bengkel.droppedPath?.());
  if (!path) { say('Drop it from Finder, or use Open a model', true); return; }
  await api('/api/permit', { path });
  open(path, file.name);
});

// Something handed over from another tool - a model pasar just brought home.
onReceive(({ path, name }) => open(path, name));

loadPresets();
if (inside) $('#subject').textContent = 'Make a heavy model light enough to use';

// Exposed for the tests, which drive this the way a person would.
window.jaring = { open, remesh, estimate, state: () => ({ model, result }) };
