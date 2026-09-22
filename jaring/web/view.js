/* One viewport, twice — drawn by one renderer.
 *
 * Everything jaring does is a comparison: this many triangles before, this
 * many after. A comparison is only honest if both sides are seen from the same
 * place, so the two halves share a camera. Turn one and the other turns with
 * it, and the difference you see is the mesh, never the angle.
 *
 * Both halves come out of a single WebGL context, split down the middle with a
 * scissor. Two canvases would each hold their own context, and a browser hands
 * out a small number of those before it starts taking them back — which it
 * does silently, leaving one half black. One context also means the two halves
 * cannot drift apart in their colour handling or their pixel ratio, which is
 * exactly the drift that would make a fair comparison unfair.
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/OrbitControls.js';
import { GLTFLoader } from 'three/addons/GLTFLoader.js';
import { Grid } from '/common/grid.js';
import { AxisGizmo, CameraSwing } from '/common/axes.js';

const loader = new GLTFLoader();

/** One of the two halves: its own scene, its own model, its own grid. */
class Half {
  constructor(camera) {
    this.camera = camera;
    this.model = null;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x121419);

    // Light that shows form rather than mood. A normal map is invisible under
    // flat lighting, and seeing that the detail survived is the whole point of
    // the right-hand half.
    const key = new THREE.DirectionalLight(0xffffff, 2.4);
    key.position.set(3, 5, 4);
    const fill = new THREE.DirectionalLight(0x9fb6d8, 0.9);
    fill.position.set(-4, 1.5, -3);
    this.scene.add(key, fill, new THREE.AmbientLight(0xffffff, 0.35));

    this.grid = new Grid();
    this.scene.add(this.grid);
  }

  clear() {
    if (!this.model) return;
    this.scene.remove(this.model);
    this.model.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) [].concat(o.material).forEach((m) => m.dispose());
    });
    this.model = null;
  }

  /**
   * Load a .glb into this half, and measure what arrived.
   *
   * The surface area is what decides the face count, so it is worked out here
   * from the same geometry that is on screen rather than guessed.
   */
  async show(url) {
    const gltf = await loader.loadAsync(url);
    this.clear();
    this.model = gltf.scene;
    this.scene.add(this.model);
    this.model.updateMatrixWorld(true);

    let triangles = 0;
    let area = 0;
    this.model.traverse((node) => {
      if (!node.isMesh || !node.geometry) return;
      const position = node.geometry.attributes.position;
      if (!position) return;
      const index = node.geometry.index;
      triangles += (index ? index.count : position.count) / 3;
      area += surfaceArea(node.geometry, node.matrixWorld);
    });

    const span = this.size();
    this.grid.fitTo(Math.max(span.x, span.y, span.z) || 1);
    return { triangles: Math.round(triangles), area };
  }

  size() {
    if (!this.model) return new THREE.Vector3(1, 1, 1);
    return new THREE.Box3().setFromObject(this.model).getSize(new THREE.Vector3());
  }

  box() {
    return this.model ? new THREE.Box3().setFromObject(this.model) : null;
  }
}

export class Stage {
  constructor(canvas) {
    this.canvas = canvas;

    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.setScissorTest(true);

    this.camera = new THREE.PerspectiveCamera(42, 1, 0.01, 500);
    this.camera.position.set(2.4, 1.8, 3.2);

    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;

    this.left = new Half(this.camera);
    this.right = new Half(this.camera);

    this.gizmo = new AxisGizmo({ size: 104, margin: 14 });
    this.swing = new CameraSwing(this.camera, this.controls);
    this.gizmo.onPick = (direction) => this.swing.start(direction);
    this._watchGizmo();

    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    this.resize();
    this._draw();
  }

  resize() {
    const box = this.canvas.parentElement.getBoundingClientRect();
    this.w = Math.max(2, Math.round(box.width));
    this.h = Math.max(2, Math.round(box.height));
    this.renderer.setSize(this.w, this.h, false);
    // Each half is half as wide as the canvas, so that is the shape the camera
    // has to be told about - not the canvas's.
    this.camera.aspect = (this.w / 2) / this.h;
    this.camera.updateProjectionMatrix();
  }

  /** Put whatever is loaded fully on screen, whatever size it happens to be. */
  frame() {
    const box = this.left.box() || this.right.box();
    if (!box || box.isEmpty()) return;
    const size = box.getSize(new THREE.Vector3());
    const middle = box.getCenter(new THREE.Vector3());
    const reach = Math.max(size.x, size.y, size.z) || 1;

    // Far enough back that the model fits the half, with room to spare.
    const back = (reach / 2) / Math.tan((this.camera.fov * Math.PI) / 360) * 1.8;
    const eye = new THREE.Vector3(0.62, 0.42, 0.86).normalize().multiplyScalar(back);

    this.camera.position.copy(middle).add(eye);
    this.camera.near = Math.max(reach / 800, 0.001);
    this.camera.far = back * 24;
    this.camera.updateProjectionMatrix();
    this.controls.target.copy(middle);
    this.controls.update();
  }

  /* The gizmo is drawn over the corner, so it has to be asked about a pointer
   * before the camera controls get it. A press that travelled more than a few
   * pixels was an orbit, not a click. */
  _watchGizmo() {
    const where = (e) => {
      const r = this.canvas.getBoundingClientRect();
      // The gizmo places itself against the whole canvas, so that is the box
      // its hit test has to be given too.
      return { x: e.clientX - r.left, y: e.clientY - r.top, w: r.width, h: r.height };
    };
    let down = null;

    this.canvas.addEventListener('pointermove', (e) => {
      const at = where(e);
      if (this.gizmo.contains(at.x, at.y, at.w, at.h)) {
        const ball = this.gizmo.hit(at.x, at.y, at.w, at.h);
        this.gizmo.setHover(ball);
        this.canvas.style.cursor = ball ? 'pointer' : '';
      } else if (this.gizmo.hovered) {
        this.gizmo.setHover(null);
        this.canvas.style.cursor = '';
      }
    });
    this.canvas.addEventListener('pointerdown', (e) => { down = { x: e.clientX, y: e.clientY }; });
    this.canvas.addEventListener('pointerup', (e) => {
      if (!down) return;
      const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y);
      down = null;
      if (moved > 4) return;
      const at = where(e);
      const ball = this.gizmo.hit(at.x, at.y, at.w, at.h);
      if (ball) this.gizmo.onPick(ball.userData.direction);
    });
  }

  _draw() {
    requestAnimationFrame(() => this._draw());
    this.controls.update();
    this.swing.update();               // a click on the corner widget, mid-flight

    const half = Math.floor(this.w / 2);
    for (const [index, side] of [this.left, this.right].entries()) {
      const x = index * half;
      // Switched on every frame, not once in the constructor: the gizmo turns
      // it off again when it has finished drawing itself. Left off, the clear
      // at the start of each render covers the whole canvas instead of one
      // half, and the second half wipes out the first - which looks exactly
      // like the left-hand view failing to draw at all.
      this.renderer.setScissorTest(true);
      this.renderer.setViewport(x, 0, half, this.h);
      this.renderer.setScissor(x, 0, half, this.h);
      side.grid.update(this.camera);
      this.renderer.render(side.scene, this.camera);
    }

    // One gizmo for the pair, in the corner of the whole stage: there is only
    // one camera, so a second copy would say the same thing twice.
    this.gizmo.render(this.renderer, this.camera, this.controls.target);
  }
}

/* The area of a mesh, in world space.
 *
 * Every triangle's area is half the length of the cross product of two of its
 * edges. Done in world space, so a model imported at one hundredth scale gets
 * the face count its real size deserves rather than the one its numbers
 * suggest.
 */
const a = new THREE.Vector3();
const b = new THREE.Vector3();
const c = new THREE.Vector3();
const ab = new THREE.Vector3();
const ac = new THREE.Vector3();

function surfaceArea(geometry, matrix) {
  const position = geometry.attributes.position;
  const index = geometry.index;
  const count = index ? index.count : position.count;
  let total = 0;
  for (let i = 0; i < count; i += 3) {
    a.fromBufferAttribute(position, index ? index.getX(i) : i).applyMatrix4(matrix);
    b.fromBufferAttribute(position, index ? index.getX(i + 1) : i + 1).applyMatrix4(matrix);
    c.fromBufferAttribute(position, index ? index.getX(i + 2) : i + 2).applyMatrix4(matrix);
    ab.subVectors(b, a);
    ac.subVectors(c, a);
    total += ab.cross(ac).length() * 0.5;
  }
  return total;
}
