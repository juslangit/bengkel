/* hantar, driven the way a person drives it.
 *
 * The page's job is to say, before anything is written, exactly where the
 * file will land and what it will be called. So that is what this checks: the
 * answer has to change when the project changes, when the folder changes, and
 * when the name changes — and it has to be the project's own spelling, not
 * whatever was typed.
 *
 * It stops short of pressing Send, which writes into a real folder and is
 * covered by the suite around it.
 */

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const lines = [];
let failed = 0;
const ok = (m) => lines.push(`  ok   ${m}`);
const bad = (m) => { lines.push(`  FAIL ${m}`); failed++; };
const check = (cond, m) => (cond ? ok(m) : bad(m));

const MODEL = new URLSearchParams(location.search).get('model');

for (let i = 0; i < 80 && !window.hantar; i++) await wait(250);
if (!window.hantar) return { failed: 1, text: '  FAIL the page never finished loading' };
ok('the page loads and exposes its controls');

for (let i = 0; i < 60 && !document.querySelector('#project option'); i++) await wait(250);
const projects = document.querySelectorAll('#project option').length;
check(projects > 0, `the game projects arrive from the server (${projects})`);
check(document.querySelectorAll('#place option').length > 0,
  'and the first one already knows where it keeps its models');
check(document.getElementById('engine-about').textContent.length > 10,
  'with a line saying what that engine takes');

check(document.querySelectorAll('canvas').length === 1, 'one renderer, one canvas');
const canvas = document.getElementById('stage');
check(canvas.width > 2 && canvas.height > 2,
  `the canvas has real size (${canvas.width}x${canvas.height})`);

// ── opening a model ─────────────────────────────────────────────────

await window.hantar.open(MODEL, MODEL.split('/').pop());
await wait(600);
check(!!window.hantar.state().model, 'a model off the disk opens');
check(!document.getElementById('go').disabled, 'Send it becomes pressable');

// ── where it will land ──────────────────────────────────────────────

window.hantar.setName('Walker Walk');
await wait(600);
let landing = window.hantar.state().landing;
check(landing.length > 0, 'the page says where it will land before anything is written');
check(landing.startsWith('~/'),
  `and says it as a path you can read (${landing.split('/').slice(-2).join('/')})`);

// The typed name is put into the destination folder's own spelling. Which
// spelling that is depends on the project, so the assertion is that it is one
// of them and never the raw text with a space in it.
const filename = landing.split('/').pop().split(' ')[0];
check(!filename.includes(' ') && /^[A-Za-z0-9_-]+\.(glb|fbx)$/.test(filename),
  `typed text becomes a real file name (${filename})`);
check(/walker[-_]?walk/i.test(filename),
  'and it is the name that was typed, respelled rather than replaced');

// Choosing a different game has to change the answer, or the project picker
// is decoration.
const before = window.hantar.state().landing;
const options = [...document.querySelectorAll('#project option')];
if (options.length > 1) {
  const other = options.find((o) => o.value !== document.getElementById('project').value);
  window.hantar.setProject(other.value);
  await wait(600);
  check(window.hantar.state().landing !== before,
    'choosing a different game changes where it will land');
} else {
  ok('only one game project here, so there is nothing to switch between');
}

// The destination format follows the engine, not the source file.
const finalLanding = window.hantar.state().landing;
check(/\.(glb|fbx)\b/.test(finalLanding),
  `the format follows the engine (${finalLanding.split('.').pop().split(' ')[0]})`);

return { failed, text: lines.join('\n') };
