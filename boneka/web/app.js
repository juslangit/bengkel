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
import { RGBELoader } from '/web/vendor/RGBELoader.js';

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

/* A model is assembled the way a modeller assembles one: the body first, then
   the face, then what it is wearing, then what it is carrying. The panel names
   the pass it is on, so the order is something you can watch rather than
   something you have to take on trust. */
const STAGE_NAMES = {
  body: 'Body', face: 'Face', clothing: 'Clothing', armour: 'Armour',
  gear: 'Gear', detail: 'Details', structure: 'Structure',
};
let lastStage = null;

/* ------------------------------------------------------------------ scene */

const canvas = $('view');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.95;

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

/* A real room's worth of light, from a Poly Haven environment map. It lights
   the model from every direction at once, which is what makes a surface read
   as a surface rather than as a shape with a picture on it. The lamps below
   stay, turned right down, only to keep a shadow under the model. */
new RGBELoader().load('/api/hdri?t=' + encodeURIComponent(TOKEN), (hdr) => {
  const pmrem = new THREE.PMREMGenerator(renderer);
  pmrem.compileEquirectangularShader();
  scene.environment = pmrem.fromEquirectangular(hdr).texture;
  scene.environmentIntensity = 1.0;
  hdr.dispose();
  pmrem.dispose();
  key.intensity = 0.85;
  rim.intensity = 0.15;
  hemi.intensity = 0.10;
}, undefined, () => { /* no environment: the lamps carry it, as before */ });

const hemi = new THREE.HemisphereLight(0x9fb6d8, 0x2a2119, 1.35);
scene.add(hemi);
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


/* ---------------------------------------------------------------- palette */
/* A palette is resolved by the server - a built-in mood, something already
   fetched, or anything on Lospec - and Blender is handed the colours, so the
   build itself never touches the network. */

function showSwatches(colors) {
  const box = $('swatches');
  box.innerHTML = '';
  if (!colors || !colors.length) { box.hidden = true; return; }
  for (const c of colors) {
    const s = document.createElement('span');
    s.style.background = c;
    s.title = c;
    box.appendChild(s);
  }
  box.hidden = false;
}

let paletteTimer = null;
async function lookUpPalette() {
  const name = $('palette').value.trim();
  if (!name) {
    showSwatches(null);
    $('palette-note').textContent = 'Everything on the model is built from ' +
      'one palette, shades included.';
    return;
  }
  $('palette-note').textContent = 'looking up ' + name + '\u2026';
  try {
    const res = await fetch('/api/palette?t=' + encodeURIComponent(TOKEN) +
                            '&name=' + encodeURIComponent(name));
    const data = await res.json();
    if (!res.ok) { showSwatches(null); $('palette-note').textContent = data.error; return; }
    showSwatches(data.colors);
    $('palette-note').textContent = data.name + ' \u2014 ' + data.colors.length +
      ' colours, ' + data.source + (data.author ? ', by ' + data.author : '');
  } catch (e) {
    showSwatches(null);
    $('palette-note').textContent = 'could not look that up';
  }
}

$('palette').oninput = () => {
  clearTimeout(paletteTimer);
  paletteTimer = setTimeout(lookUpPalette, 450);
};
$('palette').onkeydown = (e) => {
  if (e.key === 'Enter') { clearTimeout(paletteTimer); lookUpPalette(); }
};
$('palette-clear').onclick = () => {
  $('palette').value = '';
  lookUpPalette();
};


/* ------------------------------------------------ the PC's own generator */
/* An open-weight model on the machine at the academy, reached over Tailscale.
   It does the one thing a recipe cannot: it has seen a million of these, so
   it knows what a thing looks like. What comes back is one lump with no named
   parts, so it goes through the fitted rig rather than the exact one. */

async function checkLocal3d() {
  try {
    const r = await fetch('/api/local3d/health?t=' + encodeURIComponent(TOKEN));
    const d = await r.json();
    if (!d.configured) {
      $('local3d-state').textContent =
        'not set up yet - run tools/hunyuan/install.sh on the PC';
      return;
    }
    if (d.ok === false) {
      $('local3d-state').textContent = 'the PC is not answering (off, or the ' +
        'service is not running)';
      return;
    }
    $('local3d').disabled = false;
    $('local3d-state').textContent = 'the PC is awake' +
      (d.loaded ? ', model loaded' : ', model loads on first use') +
      (d.texture ? ', texture on' : '');
  } catch (e) {
    $('local3d-state').textContent = 'could not ask the server';
  }
}

$('local3d').onclick = async () => {
  const file = $('local3d-file').files[0];
  if (!file) { say('Pick a photo first'); return; }
  const data = await new Promise((done) => {
    const fr = new FileReader();
    fr.onload = () => done(fr.result);
    fr.readAsDataURL(file);
  });
  busy('the PC is generating\u2026');
  logLine('sent ' + file.name + ' to the PC');
  try {
    await post('/api/local3d', {
      image: data,
      name: file.name.replace(/\.[^.]+$/, '').replace(/[^a-z0-9]+/gi, '_'),
      texture: $('local3d-texture').checked,
    });
  } catch (e) { say(e.message); state.busy = false; refreshButtons(); }
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
      lastStage = null;
      $('progress-label').textContent = ev.total + ' parts: ' +
        (ev.stages || []).map((s) => STAGE_NAMES[s] || s).join(' → ');
      $('r-name').textContent = ev.plan.name;
      $('r-bones').textContent = '—';
      logLine('plan: ' + ev.plan.archetype + ', ' + ev.total + ' parts');
      showReference(ev.plan.subject);
      if (ev.plan.palette && ev.plan.palette.length) {
        showSwatches(ev.plan.palette);
        if (ev.plan.palette_name) {
          $('palette-note').textContent = ev.plan.palette_name +
            ' \u2014 named in the prompt';
        }
      }
      break;

    case 'step': {
      const done = ev.i + 1;
      $('bar-fill').style.width = (done / ev.total * 100) + '%';
      $('progress-label').innerHTML =
        '<b>' + (STAGE_NAMES[ev.stage] || ev.stage) + '</b> · ' + ev.label +
        '<span class="count">' + done + ' / ' + ev.total + '</span>';
      if (ev.stage !== lastStage) {
        logLine('— ' + (STAGE_NAMES[ev.stage] || ev.stage));
        lastStage = ev.stage;
      }
      logLine('   ' + ev.label);
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
      // A .glb asked for by the "Animate it in gerak" button is not announced
      // as a save - it goes straight next door.
      if (handingOver && ev.file.toLowerCase().endsWith('.glb')) {
        const going = handingOver;
        handingOver = null;
        sendToGerak(ev.file, going);
      } else {
        say('Saved ' + ev.file.split('/').pop() + ' in the session folder', true);
      }
      break;

    case 'local3d':
      if (ev.stage === 'sending') {
        setStatus('the PC is generating - a minute or two', 'busy');
        logLine('the PC is generating');
      } else if (ev.stage === 'fetching') {
        setStatus('fetching the mesh from the PC', 'busy');
        logLine('generated in ' + ev.seconds + 's, fetching');
      } else if (ev.stage === 'done') {
        logLine('got ' + ev.file + (ev.textured ? ', textured' : ', untextured'));
        say('Came back from the PC. Press Auto-Rig \u2014 it will fit a ' +
            'skeleton, since this one has no named parts.', true);
      }
      break;

    case 'designing':
      // boneka has no recipe for this, so Claude is designing one
      if (ev.stage === 'reference') {
        setStatus('no recipe for "' + ev.subject + '" — looking it up', 'busy');
        logLine('no built-in recipe for ' + ev.subject + ': asking Claude to design one');
      } else if (ev.stage === 'thinking') {
        setStatus('Claude is designing a ' + ev.subject + ' — a minute or two', 'busy');
        logLine('Claude is designing it, from ' + ev.references + ' reference photo' +
                (ev.references === 1 ? '' : 's'));
      } else if (ev.stage === 'fixing') {
        logLine('its recipe needed a fix (' + ev.message + '), asking again');
      } else if (ev.stage === 'done') {
        logLine('Claude designed ' + ev.parts + ' parts in ' + ev.seconds + 's; building');
      }
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
  const palette = $('palette').value.trim();
  busy('building…');
  try { await send('build', palette ? { prompt, palette } : { prompt }); }
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
    const pal = await (await fetch('/api/palettes?t=' +
                       encodeURIComponent(TOKEN))).json();
    for (const mood of (pal.moods || []).concat(pal.cached || [])) {
      const b = document.createElement('button');
      b.className = 'chip'; b.textContent = mood;
      b.onclick = () => { $('palette').value = mood; lookUpPalette(); };
      $('moods').appendChild(b);
    }
    if (!hello.meshy) {
      $('meshy').disabled = true;
      $('meshy-state').textContent = 'No Meshy key in ~/.claude/.env';
    }
  } catch (e) { setStatus('cannot reach the server', 'bad'); }
  refreshButtons();
  connect();
  checkLocal3d();
})();


/* ── next door ───────────────────────────────────────────────────────
 *
 * When boneka is running inside bengkel there is another tool beside it, and
 * a model that has just been rigged has an obvious next step. So: export a
 * .glb the way the export buttons do, and when it lands, ask bengkel to open
 * it in gerak.
 *
 * Outside bengkel `window.bengkel` does not exist, the button never appears,
 * and nothing about boneka changes. That is the whole of the coupling.
 */

let handingOver = null;

function sendToGerak(file, what) {
  if (!window.bengkel) return;
  window.bengkel.handOver('gerak', file, what || '');
  say('Sent to gerak — click a joint and start posing', true);
}

if (window.bengkel) {
  $('handover-row').hidden = false;

  const button = $('to-gerak');
  button.onclick = async () => {
    if (!state.built) return;
    button.disabled = true;
    const was = button.textContent;
    button.textContent = 'Exporting…';
    handingOver = state.name || '';
    try {
      await send('export', { format: 'glb' });
    } catch (err) {
      handingOver = null;
      say('Could not export: ' + err.message, false);
    } finally {
      button.textContent = was;
      button.disabled = false;
    }
  };

  /* Whatever turns the export buttons on should turn this one on too, so
   * wrap the one function that decides. Giving it the `export` class instead
   * would have hooked it to the export click handler, which expects a format
   * in its dataset and would have exported nothing. */
  const buttonsWere = refreshButtons;
  refreshButtons = function (...args) {
    buttonsWere.apply(this, args);
    button.disabled = !state.ready || state.busy || !state.built;
    button.title = state.rigged
      ? 'Export a .glb and open it in gerak'
      : 'It has no skeleton yet — gerak can give it one, or press Auto-Rig first';
  };
  refreshButtons();

  // A model handed back from gerak.
  window.bengkel.onReceive((payload) => {
    if (!payload || !payload.path) return;
    say('gerak sent back ' + payload.path.split('/').pop()
      + ' — open it from the session folder', true);
    logLine('received from gerak: ' + payload.path);
  });
}


/* ── what the assistant may do here ──────────────────────────────────
 *
 * bengkel injects a floating assistant into every tool it hosts. It cannot
 * write code or touch anything on its own: it may only call the actions
 * listed here, which are things this tool already does. `snapshot` and
 * `restore` are what make them undoable, and `risky: true` marks the ones
 * that reach outside the tool, which bengkel always asks about first.
 *
 * None of this happens when the tool is run on its own.
 */
if (window.bengkel && window.bengkel.assist) window.bengkel.assist({
  tool: 'boneka',
  about: 'makes a character from a written description, in Blender, on this '
       + 'Mac. Building takes a while and shows its progress as it goes.',
  context: () => ({
    prompt: $('prompt') ? $('prompt').value : '',
    animation_prompt: $('anim-prompt') ? $('anim-prompt').value : '',
    busy: $('build') ? $('build').disabled : null,
    last_line: $('log') ? ($('log').lastElementChild || {}).textContent || '' : '',
  }),
  snapshot: () => ({
    prompt: $('prompt') ? $('prompt').value : '',
    anim: $('anim-prompt') ? $('anim-prompt').value : '',
  }),
  restore: (shot) => {
    if ($('prompt')) $('prompt').value = shot.prompt;
    if ($('anim-prompt')) $('anim-prompt').value = shot.anim;
  },
  actions: {
    describe: {
      what: 'Write the description of the character to be built, without '
          + 'building it yet',
      args: { prompt: 'what the character should be' },
      run: async ({ prompt }) => {
        if (!$('prompt')) throw new Error('no description box on this page');
        $('prompt').value = prompt || '';
        return prompt;
      },
    },
    build: {
      what: 'Build the character that is described. Takes a while and writes files',
      args: {},
      risky: true,
      warn: 'This runs Blender and builds a whole character, which takes a '
          + 'few minutes and writes files to disk.',
      run: async () => {
        if (!$('build') || $('build').disabled) throw new Error('it is busy already');
        $('build').click();
        return 'started — watch the log';
      },
    },
    animate: {
      what: 'Give the character an animation, described in words',
      args: { prompt: 'the movement, e.g. "a slow walk"' },
      risky: true,
      warn: 'This builds an animation onto the character and writes files.',
      run: async ({ prompt }) => {
        if ($('anim-prompt')) $('anim-prompt').value = prompt || '';
        if (!$('animate')) throw new Error('no animate button on this page');
        $('animate').click();
        return 'started';
      },
    },
  },
});
