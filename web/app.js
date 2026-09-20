/*
 * boneka - the browser half.
 *
 * It keeps one three.js scene open and listens to the server's event stream.
 * While Blender builds, each finished part arrives as its own small .glb and
 * is dropped into the scene with a little pop, which is why the model appears
 * limb by limb. Once there is a rig or an animation, the whole model is
 * swapped in one piece, because the skeleton binds all the parts together.
 */

import * as THREE from 'three';
import { GLTFLoader } from '/web/vendor/GLTFLoader.js';
import { OrbitControls } from '/web/vendor/OrbitControls.js';

const TOKEN = new URLSearchParams(location.search).get('t') || '';
const $ = (id) => document.getElementById(id);
const loader = new GLTFLoader();

const EXAMPLES = [
  'a tall blue knight with a sword and a cape',
  'a chunky red robot with an antenna',
  'a brown dog with a tail',
  'a small white chicken',
  'a blocky green golem',
  'a pine tree',
  'a treasure chest',
  'a wizard with a staff and a hat',
];
const MOVES = ['idle', 'walk', 'run', 'jump', 'wave', 'dance', 'attack',
  'punch', 'kick', 'spin', 'crouch', 'sit', 'die', 'cheer', 'fly', 'sneak'];

/* ------------------------------------------------------------------ scene */

const canvas = $('view');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x15171c);
scene.fog = new THREE.Fog(0x15171c, 14, 46);

const camera = new THREE.PerspectiveCamera(42, 1, 0.05, 260);
camera.position.set(3.0, 2.1, 4.2);

const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.07;
controls.target.set(0, 0.9, 0);
controls.maxPolarAngle = Math.PI * 0.52;

scene.add(new THREE.HemisphereLight(0x9fb6d8, 0x2a2119, 1.35));
const key = new THREE.DirectionalLight(0xfff0d8, 2.5);
key.position.set(4.5, 7.5, 4.0);
key.castShadow = true;
key.shadow.mapSize.set(2048, 2048);
key.shadow.camera.near = 0.5;
key.shadow.camera.far = 40;
key.shadow.camera.left = key.shadow.camera.bottom = -8;
key.shadow.camera.right = key.shadow.camera.top = 8;
key.shadow.bias = -0.0009;
scene.add(key);
const rim = new THREE.DirectionalLight(0x7fa8ff, 1.0);
rim.position.set(-5, 3.5, -4.5);
scene.add(rim);

const floor = new THREE.Mesh(
  new THREE.CircleGeometry(24, 64),
  new THREE.MeshStandardMaterial({ color: 0x1b1e25, roughness: 0.95 }));
floor.rotation.x = -Math.PI / 2;
floor.receiveShadow = true;
scene.add(floor);

const grid = new THREE.GridHelper(24, 24, 0x3d4457, 0x272c38);
grid.material.transparent = true;
grid.material.opacity = 0.75;
grid.position.y = 0.002;
scene.add(grid);

/* three.js is Y-up and so is a .glb, so nothing needs rotating on the way in */
const model = new THREE.Group();
scene.add(model);

let mixer = null;
let action = null;
let skeleton = null;
const pops = [];
const clock = new THREE.Clock();

function resize() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (canvas.width !== w * devicePixelRatio || canvas.height !== h * devicePixelRatio) {
    renderer.setSize(w, h, false);
    camera.aspect = w / Math.max(h, 1);
    camera.updateProjectionMatrix();
  }
}

function tick() {
  requestAnimationFrame(tick);
  const dt = clock.getDelta();
  resize();

  for (let i = pops.length - 1; i >= 0; i--) {
    const p = pops[i];
    p.t += dt / 0.22;
    const k = Math.min(p.t, 1);
    const e = 1 - Math.pow(1 - k, 3);
    const overshoot = 1 + 0.16 * Math.sin(Math.PI * k) * (1 - k);
    p.node.scale.setScalar(e * overshoot);
    p.node.position.y = p.y + (1 - e) * 0.12;
    if (k >= 1) { p.node.scale.setScalar(1); p.node.position.y = p.y; pops.splice(i, 1); }
  }

  if (mixer && action && !paused) {
    mixer.update(dt);
    const d = action.getClip().duration || 1;
    $('scrub').value = Math.round((action.time % d) / d * 1000);
    $('time').textContent = (action.time % d).toFixed(2) + 's';
  }
  controls.update();
  renderer.render(scene, camera);
}
tick();

/* --------------------------------------------------------------- loading */

function clearModel() {
  model.clear();
  pops.length = 0;
  if (mixer) { mixer.stopAllAction(); mixer = null; }
  action = null;
  if (skeleton) { scene.remove(skeleton); skeleton = null; }
  $('playbar').hidden = true;
}

function dressUp(root) {
  root.traverse((o) => {
    if (o.isMesh) {
      o.castShadow = true;
      o.receiveShadow = true;
      if (o.material) o.material.envMapIntensity = 0.8;
    }
  });
}

function addPart(url) {
  loader.load(url, (gltf) => {
    const node = gltf.scene;
    dressUp(node);
    node.scale.setScalar(0.001);
    model.add(node);
    pops.push({ node, t: 0, y: node.position.y });
    frameModel(false);
  }, undefined, (e) => say('could not read that part: ' + e.message));
}

function loadWhole(url, { animated = false } = {}) {
  loader.load(url, (gltf) => {
    clearModel();
    const node = gltf.scene;
    dressUp(node);
    model.add(node);

    node.traverse((o) => {
      if (o.isSkinnedMesh && !skeleton) {
        skeleton = new THREE.SkeletonHelper(node);
        skeleton.visible = bonesVisible;
        scene.add(skeleton);
      }
    });

    if (animated && gltf.animations.length) {
      mixer = new THREE.AnimationMixer(node);
      action = mixer.clipAction(gltf.animations[0]);
      action.setLoop(THREE.LoopRepeat, Infinity);
      action.play();
      paused = false;
      $('play').innerHTML = '&#10074;&#10074;';
      $('playbar').hidden = false;
    }
    frameModel(true);
  }, undefined, (e) => say('could not read that model: ' + e.message));
}

let framedOnce = false;
function frameModel(force) {
  const box = new THREE.Box3().setFromObject(model);
  if (!isFinite(box.min.x) || box.isEmpty()) return;
  const size = box.getSize(new THREE.Vector3());
  const centre = box.getCenter(new THREE.Vector3());
  const reach = Math.max(size.x, size.y, size.z);
  if (reach < 1e-4) return;
  controls.target.lerp(new THREE.Vector3(centre.x, centre.y, centre.z),
    force ? 1 : 0.25);
  if (force || !framedOnce) {
    const dist = reach * 2.15 + 0.6;
    camera.position.set(dist * 0.62, centre.y + reach * 0.42, dist * 0.86);
    framedOnce = true;
  }
  const far = Math.max(60, reach * 14);
  scene.fog.near = reach * 5; scene.fog.far = far;
  camera.far = far; camera.updateProjectionMatrix();
  grid.scale.setScalar(Math.max(1, reach / 2.2));
}


/* --------------------------------------------------------------- reference */

let refFolded = false;

async function showReference(subject) {
  if (!subject) return;
  const box = $('reference'), strip = $('ref-strip');
  $('ref-subject').textContent = subject;
  strip.innerHTML = '';
  $('ref-note').textContent = 'looking\u2026';
  box.hidden = false;
  try {
    const res = await fetch('/api/reference?t=' + encodeURIComponent(TOKEN) +
                            '&q=' + encodeURIComponent(subject));
    const data = await res.json();
    if (!data.images || !data.images.length) {
      $('ref-note').textContent = 'no photographs found for this one';
      return;
    }
    for (const img of data.images) {
      const a = document.createElement('a');
      a.href = img.page || '#';
      a.target = '_blank';
      a.rel = 'noopener';
      a.title = img.title + (img.licence ? ' \u2014 ' + img.licence : '');
      const el = document.createElement('img');
      el.loading = 'lazy';
      el.alt = img.title;
      el.src = '/api/reference/image?t=' + encodeURIComponent(TOKEN) +
               '&u=' + encodeURIComponent(img.thumb);
      a.appendChild(el);
      strip.appendChild(a);
    }
    $('ref-note').textContent = 'Wikimedia Commons \u2014 click one to open it';
  } catch (e) {
    $('ref-note').textContent = 'could not reach Wikimedia (offline?)';
  }
}

$('ref-toggle').onclick = () => {
  refFolded = !refFolded;
  $('reference').classList.toggle('folded', refFolded);
  $('ref-toggle').textContent = refFolded ? 'show' : 'hide';
};

/* ------------------------------------------------------------ server talk */

async function post(path, body) {
  const res = await fetch(path + '?t=' + encodeURIComponent(TOKEN), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Boneka-Token': TOKEN },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || ('server said ' + res.status));
  return data;
}

function send(cmd, extra) { return post('/api/command', { cmd, ...(extra || {}) }); }

let toastTimer = null;
function say(message, good) {
  const t = $('toast');
  t.textContent = message;
  t.classList.toggle('good', !!good);
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, good ? 3500 : 9000);
}

function logLine(text, bad) {
  const log = $('log');
  const line = document.createElement('div');
  if (bad) line.className = 'err';
  line.textContent = text;
  log.appendChild(line);
  while (log.childNodes.length > 300) log.removeChild(log.firstChild);
  log.scrollTop = log.scrollHeight;
}

function setStatus(text, kind) {
  const el = $('status');
  el.textContent = text;
  el.className = 'status ' + kind;
}

/* ------------------------------------------------------------------ state */

const state = { ready: false, built: false, rigged: false, busy: false,
                total: 0, name: '' };

function refreshButtons() {
  const free = state.ready && !state.busy;
  $('build').disabled = !free;
  $('meshy').disabled = !free;
  $('rig').disabled = !free || !state.built;
  $('animate').disabled = !free || !state.rigged;
  $('anim-prompt').disabled = !state.rigged;
  $('use-clip').disabled = !free || !state.rigged;
  document.querySelectorAll('.export').forEach((b) => { b.disabled = !free || !state.built; });
  $('rig-hint').textContent = state.rigged
    ? 'Bones are in. You can re-rig any time.'
    : (state.built ? 'One press. It knows where every joint is.'
                   : 'Build something first.');
  $('anim-hint').textContent = state.rigged
    ? 'Try "walk slowly", "big jump", "fast dance".'
    : 'Rig it first.';
}

/* ------------------------------------------------------------------ events */

function connect() {
  const src = new EventSource('/api/events?t=' + encodeURIComponent(TOKEN));
  src.onmessage = (msg) => handle(JSON.parse(msg.data));
  src.onerror = () => setStatus('lost the server - is it still running?', 'bad');
}

function handle(ev) {
  switch (ev.event) {
    case 'ready':
      state.ready = true;
      setStatus('Blender ' + ev.blender + ' ready', 'ready');
      logLine('Blender ' + ev.blender + ' ready');
      refreshButtons();
      break;

    case 'plan':
      clearModel();
      framedOnce = false;
      state.total = ev.total;
      state.built = false;
      state.rigged = false;
      $('progress').hidden = false;
      $('bar-fill').style.width = '0%';
      $('progress-label').textContent = 'planning ' + ev.total + ' parts…';
      $('r-name').textContent = ev.plan.name;
      $('r-bones').textContent = '—';
      logLine('plan: ' + ev.plan.archetype + ', ' + ev.total + ' parts');
      showReference(ev.plan.subject);
      break;

    case 'step': {
      const done = ev.i + 1;
      $('bar-fill').style.width = (done / ev.total * 100) + '%';
      $('progress-label').textContent = done + ' / ' + ev.total + '  —  ' + ev.label;
      addPart('/session/' + ev.file);
      break;
    }

    case 'sculpting':
      if (ev.stage === 'start') {
        $('progress-label').textContent =
          'sculpting \u2014 fusing the parts into one form\u2026';
        logLine('sculpting: voxel remesh, colour group by colour group');
      } else if (ev.stage === 'group') {
        $('progress-label').textContent =
          'sculpting \u2014 ' + (ev.i + 1) + ' / ' + ev.total;
      }
      break;

    case 'built':
      state.built = true;
      state.name = ev.name;
      $('progress-label').textContent = 'built — ' + ev.parts + ' parts';
      $('r-name').textContent = ev.name;
      $('r-parts').textContent = ev.parts + ' parts';
      $('r-tris').textContent = ev.triangles.toLocaleString() + ' triangles';
      $('r-height').textContent = ev.height + ' m tall';
      logLine('built ' + ev.name + ' (' + ev.triangles + ' triangles' +
              (ev.sculpted ? ', sculpted' : '') + ')');
      // the sculpt pass rebuilt the geometry, so swap the streamed parts for
      // the finished thing rather than leaving the loose pieces on screen
      loadWhole('/session/' + ev.file);
      say(ev.sculpted
        ? 'Built and sculpted. Press Auto-Rig when you like it.'
        : 'Built. Press Auto-Rig when you like it.', true);
      break;

    case 'rigged':
      state.rigged = true;
      $('r-bones').textContent = ev.count + ' bones';
      loadWhole('/session/' + ev.file);
      logLine('rigged: ' + ev.count + ' bones (' +
              (ev.exact ? 'exact, from the recipe' : 'fitted to the mesh') + ')');
      say(ev.exact
        ? 'Rigged with ' + ev.count + ' bones, placed exactly.'
        : 'Rigged with ' + ev.count + ' bones, fitted to the shape.', true);
      break;

    case 'animated':
      loadWhole('/session/' + ev.file, { animated: ev.frames > 1 });
      logLine('animation: ' + ev.move + ', ' + ev.frames + ' frames at ' + ev.fps + ' fps');
      if (ev.frames > 1) say(ev.move + ' — ' + ev.frames + ' frames', true);
      break;

    case 'exported':
      logLine('exported ' + ev.file);
      say('Saved ' + ev.file.split('/').pop() + ' in the session folder', true);
      break;

    case 'meshy':
      setStatus('Meshy: ' + ev.stage + (ev.progress ? ' ' + ev.progress + '%' : ''), 'busy');
      $('meshy-state').textContent = 'Meshy: ' + ev.stage;
      logLine('meshy ' + ev.stage);
      break;

    case 'error':
      setStatus(ev.message, 'bad');
      say(ev.message);
      logLine('error: ' + ev.message, true);
      if (ev.detail) logLine(ev.detail, true);
      state.busy = false;
      refreshButtons();
      break;

    case 'idle':
      state.busy = false;
      setStatus('ready', 'ready');
      refreshButtons();
      break;

    case 'stopped':
      state.ready = false;
      setStatus(ev.message, 'bad');
      refreshButtons();
      break;
  }
}

/* ---------------------------------------------------------------- controls */

function busy(label) {
  state.busy = true;
  setStatus(label, 'busy');
  refreshButtons();
}

$('build').onclick = async () => {
  const prompt = $('prompt').value.trim() || $('prompt').placeholder;
  busy('building…');
  try { await send('build', { prompt }); }
  catch (e) { say(e.message); state.busy = false; refreshButtons(); }
};

$('rig').onclick = async () => {
  busy('fitting the skeleton…');
  try { await send('rig'); }
  catch (e) { say(e.message); state.busy = false; refreshButtons(); }
};

async function animate(prompt) {
  busy('keyframing…');
  try { await send('animate', { prompt }); }
  catch (e) { say(e.message); state.busy = false; refreshButtons(); }
}

$('animate').onclick = () => animate($('anim-prompt').value.trim() || 'idle');
$('anim-prompt').onkeydown = (e) => {
  if (e.key === 'Enter' && !$('animate').disabled) $('animate').click();
};
$('prompt').onkeydown = (e) => {
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) $('build').click();
};

$('use-clip').onclick = async () => {
  const file = $('clips').value;
  if (!file) return;
  busy('borrowing that motion…');
  try { await send('clip', { path: file }); }
  catch (e) { say(e.message); state.busy = false; refreshButtons(); }
};

document.querySelectorAll('.export').forEach((b) => {
  b.onclick = async () => {
    busy('writing the file…');
    try { await send('export', { format: b.dataset.format }); }
    catch (e) { say(e.message); state.busy = false; refreshButtons(); }
  };
});

$('meshy').onclick = async () => {
  const prompt = $('prompt').value.trim() || $('prompt').placeholder;
  const ok = confirm(
    'Send this to Meshy?\n\n"' + prompt + '"\n\n' +
    'A preview model costs about 5 Meshy credits and takes one to three ' +
    'minutes. Credits are real money, so boneka only ever does this when ' +
    'you say yes here.');
  if (!ok) return;
  busy('Meshy is generating…');
  try { await post('/api/meshy', { prompt, confirm: true }); }
  catch (e) { say(e.message); state.busy = false; refreshButtons(); }
};

/* playback */
let paused = false;
let bonesVisible = false;

$('play').onclick = () => {
  paused = !paused;
  $('play').innerHTML = paused ? '&#9654;' : '&#10074;&#10074;';
};
$('scrub').oninput = () => {
  if (!action) return;
  const d = action.getClip().duration || 1;
  action.time = ($('scrub').value / 1000) * d;
  mixer.update(0);
  $('time').textContent = action.time.toFixed(2) + 's';
};
$('speed').oninput = () => {
  if (mixer) mixer.timeScale = $('speed').value / 100;
};
$('toggle-bones').onclick = () => {
  bonesVisible = !bonesVisible;
  if (skeleton) skeleton.visible = bonesVisible;
};
$('toggle-grid').onclick = () => { grid.visible = !grid.visible; };
$('log-toggle').onclick = () => $('log').classList.toggle('open');

/* chips */
for (const text of EXAMPLES) {
  const b = document.createElement('button');
  b.className = 'chip'; b.textContent = text;
  b.onclick = () => { $('prompt').value = text; $('build').click(); };
  $('examples').appendChild(b);
}
for (const move of MOVES) {
  const b = document.createElement('button');
  b.className = 'chip'; b.textContent = move;
  b.onclick = () => { $('anim-prompt').value = move; if (state.rigged) animate(move); };
  $('moves').appendChild(b);
}

/* start */
(async () => {
  try {
    const hello = await (await fetch('/api/hello?t=' + encodeURIComponent(TOKEN))).json();
    if (hello.ready) { state.ready = true; setStatus('Blender ready', 'ready'); }
    if (hello.clips && hello.clips.length) {
      $('clips-row').hidden = false;
      for (const c of hello.clips) {
        const o = document.createElement('option');
        o.value = c; o.textContent = c;
        $('clips').appendChild(o);
      }
    }
    if (!hello.meshy) {
      $('meshy').disabled = true;
      $('meshy-state').textContent = 'No Meshy key in ~/.claude/.env';
    }
  } catch (e) { setStatus('cannot reach the server', 'bad'); }
  refreshButtons();
  connect();
})();
