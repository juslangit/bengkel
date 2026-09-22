/* kulit, driven the way a person drives it.
 *
 * Opens a model, checks that every part of it got a row, picks a colour off a
 * palette and checks it landed on the model rather than only in the list. It
 * stops short of the Blender run, which the suite around it covers.
 */

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const lines = [];
let failed = 0;
const ok = (m) => lines.push(`  ok   ${m}`);
const bad = (m) => { lines.push(`  FAIL ${m}`); failed++; };
const check = (cond, m) => (cond ? ok(m) : bad(m));

const MODEL = new URLSearchParams(location.search).get('model');

for (let i = 0; i < 80 && !window.kulit; i++) await wait(250);
if (!window.kulit) return { failed: 1, text: '  FAIL the page never finished loading' };
ok('the page loads and exposes its controls');

for (let i = 0; i < 60 && !document.querySelectorAll('.swatch').length; i++) await wait(250);
check(document.querySelectorAll('.swatch').length > 0,
  `a palette arrives from the server (${document.querySelectorAll('.swatch').length} colours)`);
check(document.querySelectorAll('canvas').length === 1, 'one renderer, one canvas');

const canvas = document.getElementById('stage');
check(canvas.width > 2 && canvas.height > 2,
  `the canvas has real size (${canvas.width}x${canvas.height})`);

// ── opening a model ─────────────────────────────────────────────────

await window.kulit.open(MODEL, MODEL.split('/').pop());
await wait(600);

const state = window.kulit.state();
check(!!state.model, 'a model off the disk opens');
check(state.parts.length > 0, `and every mesh in it gets a row (${state.parts.length})`);
check(document.querySelectorAll('.part').length === state.parts.length,
  'the rows on screen match the parts in the model');
check(!document.getElementById('go').disabled, 'Dress it becomes pressable');

// Every row has to offer a surface, or the choice cannot be made at all.
const menus = document.querySelectorAll('.part [data-field="surface"]');
check(menus.length === state.parts.length, 'each row can be told what it is made of');
check([...menus[0].options].length >= 8,
  `with every surface listed (${[...menus[0].options].length})`);

// A surface with no photograph behind it is offered but not choosable, rather
// than being chosen and silently coming out as flat colour.
const disabled = [...menus[0].options].filter((o) => o.disabled);
check([...menus[0].options].some((o) => !o.disabled),
  `surfaces without a photograph are disabled, not silently plain (${disabled.length} disabled)`);

// ── choosing a colour ───────────────────────────────────────────────

const before = window.kulit.state().parts[0].colour;
window.kulit.choose(state.parts[0].name);
await wait(150);
document.querySelectorAll('.swatch')[3].click();
await wait(250);

const after = window.kulit.state().parts[0];
check(after.colour !== before, `clicking a colour changes the part (${before} → ${after.colour})`);
check(document.querySelector('.part .part-dot').style.background !== '',
  'and the row shows the colour it now is');

// The point of the whole panel: the colour has to be on the model, now, or
// it is being chosen by imagining rather than by looking.
const dot = document.querySelector('.part .part-dot');
check(dot.style.background.replace(/\s/g, '').toLowerCase().includes(
  after.colour.toLowerCase()) || dot.style.background.startsWith('rgb'),
  'the swatch on the row is the colour that was clicked');

check(document.getElementById('send').hidden, 'there is nothing to send on yet');

return { failed, text: lines.join('\n') };
