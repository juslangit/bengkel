/* periksa, driven the way a person drives it.
 *
 * Opens a good model and a broken one and checks that the page says something
 * different about each — which is the only thing a checker has to do.
 */

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const lines = [];
let failed = 0;
const ok = (m) => lines.push(`  ok   ${m}`);
const bad = (m) => { lines.push(`  FAIL ${m}`); failed++; };
const check = (cond, m) => (cond ? ok(m) : bad(m));

const query = new URLSearchParams(location.search);
const MODEL = query.get('model');
const HUGE = query.get('huge');

for (let i = 0; i < 80 && !window.periksa; i++) await wait(250);
if (!window.periksa) return { failed: 1, text: '  FAIL the page never finished loading' };
ok('the page loads and exposes its controls');

for (let i = 0; i < 60 && !document.querySelectorAll('.seg-btn').length; i++) await wait(250);
check(document.querySelectorAll('.seg-btn').length >= 4,
  `the roles arrive from the server (${document.querySelectorAll('.seg-btn').length})`);
check(document.querySelectorAll('canvas').length === 1, 'one renderer, one canvas');

const canvas = document.getElementById('stage');
check(canvas.width > 2 && canvas.height > 2,
  `the canvas has real size (${canvas.width}x${canvas.height})`);

// ── a model that is fine ────────────────────────────────────────────

document.querySelector('.seg-btn[data-role="character"]').click();
await wait(200);
await window.periksa.look(MODEL, 'good.glb');
await wait(900);

let state = window.periksa.state();
check(!!state.report, 'a model is read');
check(state.report.facts.triangles > 0,
  `and its triangles counted (${state.report.facts.triangles.toLocaleString()})`);
check(!document.getElementById('verdict').hidden, 'the one-line answer appears');
check(!document.getElementById('facts').hidden, 'and the plain numbers under it');
check(document.querySelectorAll('.finding').length > 0,
  `with something said about it (${document.querySelectorAll('.finding').length} findings)`);

// The things that are already fine are folded away: reassurance, not news.
check(!!document.querySelector('details.fine'),
  'what is already fine is folded away rather than shouted');
check(document.getElementById('verdict').className.includes('is-watch')
  || document.getElementById('verdict').className.includes('is-good'),
  'a sound model is not reported as broken');

// ── a model that is not ─────────────────────────────────────────────

await window.periksa.look(HUGE, 'huge.glb');
await wait(900);

state = window.periksa.state();
check(state.report.counts.bad > 0,
  `a model exported in centimetres is called out (${state.report.counts.bad} faults)`);
check(document.getElementById('verdict').className.includes('is-bad'),
  'and the one-line answer says so first');
check([...document.querySelectorAll('.finding.is-bad .what')]
  .some((n) => n.textContent.includes('metres across')),
  'in words that name the actual problem');
check([...document.querySelectorAll('.finding.is-bad .todo')].length > 0,
  'and every fault says what to do about it');

// ── changing what it is for changes the answer ──────────────────────

await window.periksa.look(MODEL, 'good.glb');
await wait(700);
const asCharacter = window.periksa.state().report.counts.bad;
document.querySelector('.seg-btn[data-role="background"]').click();
await wait(900);
const asBackground = window.periksa.state().report.counts.bad;

check(asBackground > asCharacter,
  `the same model is judged against what it is for (${asCharacter} as a character, `
  + `${asBackground} as background)`);

return { failed, text: lines.join('\n') };
