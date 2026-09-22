/* jaring, driven the way a person drives it.
 *
 * Opens a real model off the disk, checks that the page measured it the same
 * way Blender will, moves the slider, and reads back what it says the result
 * will cost. It stops short of the remesh itself: that is minutes of Blender
 * and it has its own test.
 */

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const lines = [];
let failed = 0;
const ok = (m) => lines.push(`  ok   ${m}`);
const bad = (m) => { lines.push(`  FAIL ${m}`); failed++; };
const check = (cond, m) => (cond ? ok(m) : bad(m));

const MODEL = new URLSearchParams(location.search).get('model');

for (let i = 0; i < 80 && !window.jaring; i++) await wait(250);
if (!window.jaring) {
  return { failed: 1, text: '  FAIL the page never finished loading' };
}
ok('the page loads and exposes its controls');

// the presets come from the server, so they prove the server is answering
for (let i = 0; i < 60 && !document.querySelectorAll('.preset').length; i++) await wait(250);
const presets = [...document.querySelectorAll('.preset')].map((b) => b.querySelector('.n').textContent);
check(presets.length === 3, `three presets arrive from the server (${presets.join(', ')})`);
check(document.querySelector('.preset.is-on')?.dataset.id === 'game',
  'and Game is chosen to begin with');

// one canvas, not two: a second WebGL context is a context the browser may
// silently take back, leaving half the comparison black
check(document.querySelectorAll('canvas').length === 1,
  'both halves are drawn by one renderer');

const canvas = document.getElementById('stage');
check(canvas.width > 2 && canvas.height > 2,
  `the canvas has real size (${canvas.width}x${canvas.height})`);

// ── opening a model ─────────────────────────────────────────────────

await window.jaring.open(MODEL, MODEL.split('/').pop());
await wait(500);

const state = window.jaring.state();
check(!!state.model, 'a model off the disk opens');
check(state.model && state.model.triangles > 0,
  `and its triangles are counted (${state.model?.triangles?.toLocaleString()})`);
check(state.model && state.model.area > 0,
  `and its surface area measured (${state.model?.area?.toFixed(2)} m²)`);
check(!document.getElementById('go').disabled, 'Remesh it becomes pressable');
check(document.getElementById('count-before').textContent.includes('triangles'),
  'the Before label says how heavy it is');

// ── the estimate ────────────────────────────────────────────────────

/* The number on screen has to be the number Blender will use. If the page
 * estimates from one area and the remesher works from another, he chooses a
 * setting on screen and gets something else, which is the one thing a preview
 * must never do. */
async function estimateAt(cm) {
  const slider = document.getElementById('quad');
  slider.value = String(cm);
  slider.dispatchEvent(new Event('input'));
  await wait(400);
  const text = document.getElementById('estimate').textContent;
  const match = text.match(/([\d,]+)<?\/?b?>? ?quads|Roughly ([\d,]+)/);
  const found = text.match(/([\d,]+)/);
  return found ? parseInt(found[1].replace(/,/g, ''), 10) : 0;
}

const fine = await estimateAt(1);
const coarse = await estimateAt(8);
check(fine > 0 && coarse > 0, `the estimate answers at both ends (${fine} and ${coarse})`);
check(fine > coarse, 'a finer quad means more faces, not fewer');

// The formula itself: faces = area / side², the same one in the worker.
const area = state.model.area;
const expected = Math.max(20, Math.min(Math.floor(area / (0.08 * 0.08)), 500000));
check(Math.abs(coarse - expected) <= 1,
  `and it is the same arithmetic the remesher uses (${coarse} vs ${expected})`);

// ── the right half stays empty until there is something in it ───────

check(!document.getElementById('after-empty').hidden,
  'the After half says it is empty until something is remeshed');
check(document.getElementById('send').hidden,
  'and there is nothing to send on yet');

return { failed, text: lines.join('\n') };
