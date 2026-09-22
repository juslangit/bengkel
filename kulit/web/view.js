/* One model on a turntable, with its parts pickable.
 *
 * Simpler than jaring's split view, because kulit is not a comparison: there
 * is one model and you are changing it. What matters is that a colour clicked
 * here appears on the model immediately, so the choosing is done by looking
 * rather than by imagining.
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/OrbitControls.js';
import { GLTFLoader } from 'three/addons/GLTFLoader.js';
import { Grid } from '/common/grid.js';
import { AxisGizmo, CameraSwing } from '/common/axes.js';

const loader = new GLTFLoader();

export class Stage {
  constructor(canvas) {
    this.canvas = canvas;
    this.model = null;
    this.parts = new Map();          // name → mesh
    this.onPick = () => {};

    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x121419);

    this.camera = new THREE.PerspectiveCamera(42, 1, 0.01, 500);
    this.camera.position.set(2.4, 1.8, 3.2);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;

    const key = new THREE.DirectionalLight(0xffffff, 2.2);
    key.position.set(3, 5, 4);
    const fill = new THREE.DirectionalLight(0x9fb6d8, 0.85);
    fill.position.set(-4, 1.5, -3);
    const rim = new THREE.DirectionalLight(0xffe0c0, 0.7);
    rim.position.set(0, 2, -5);
    this.scene.add(key, fill, rim, new THREE.AmbientLight(0xffffff, 0.35));

    this.grid = new Grid();
    this.scene.add(this.grid);

    this.gizmo = new AxisGizmo({ size: 104, margin: 14 });
    this.swing = new CameraSwing(this.camera, this.controls);
    this.gizmo.onPick = (d) => this.swing.start(d);

    this.ray = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this._watch();

    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    this.resize();
    this._draw();
  }

  resize() {
    const box = this.canvas.parentElement.getBoundingClientRect();
    this.w = Math.max(2, Math.round(box.width));
    this.h = Math.max(2, Math.round(box.height));
    this.renderer.setSize(this.w, this.h, false);
    this.camera.aspect = this.w / this.h;
    this.camera.updateProjectionMatrix();
  }

  clear() {
    if (!this.model) return;
    this.scene.remove(this.model);
    this.model.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) [].concat(o.material).forEach((m) => m.dispose());
    });
    this.model = null;
    this.parts.clear();
  }

  /**
   * Load a model, and report its parts.
   *
   * The part list is the point: it is what the controls are built from, and
   * the names have to be the ones Blender will see, or a colour chosen here
   * lands on nothing there.
   */
  async show(url) {
    const gltf = await loader.loadAsync(url);
    this.clear();
    this.model = gltf.scene;
    this.scene.add(this.model);
    this.model.updateMatrixWorld(true);

    const parts = [];
    this.model.traverse((node) => {
      if (!node.isMesh || !node.geometry) return;
      this.parts.set(node.name, node);
      // Its own material, so painting one part does not paint its twin.
      node.material = node.material.clone();
      const index = node.geometry.index;
      const position = node.geometry.attributes.position;
      parts.push({
        name: node.name,
        triangles: Math.round((index ? index.count : position.count) / 3),
        colour: '#' + node.material.color.getHexString(),
      });
    });

    this.frame();
    return parts;
  }

  /** Paint one part, now, so the choice is made by looking. */
  paint(name, colour) {
    const mesh = this.parts.get(name);
    if (!mesh) return;
    mesh.material.color.set(colour);
    // A downloaded model usually carries its own texture, and a colour set
    // underneath one is a colour you cannot see.
    mesh.material.map = null;
    mesh.material.needsUpdate = true;
  }

  /** Dim everything except one part, so you can see which it is. */
  highlight(name) {
    for (const [key, mesh] of this.parts) {
      mesh.material.opacity = !name || key === name ? 1 : 0.22;
      mesh.material.transparent = !!name && key !== name;
      mesh.material.needsUpdate = true;
    }
  }

  frame() {
    if (!this.model) return;
    const box = new THREE.Box3().setFromObject(this.model);
    if (box.isEmpty()) return;
    const size = box.getSize(new THREE.Vector3());
    const middle = box.getCenter(new THREE.Vector3());
    const reach = Math.max(size.x, size.y, size.z) || 1;
    const back = (reach / 2) / Math.tan((this.camera.fov * Math.PI) / 360) * 1.7;

    this.camera.position.copy(middle)
      .add(new THREE.Vector3(0.62, 0.42, 0.86).normalize().multiplyScalar(back));
    this.camera.near = Math.max(reach / 800, 0.001);
    this.camera.far = back * 24;
    this.camera.updateProjectionMatrix();
    this.controls.target.copy(middle);
    this.controls.update();
    this.grid.fitTo(reach);
  }

  _watch() {
    const where = (e) => {
      const r = this.canvas.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top, w: r.width, h: r.height };
    };
    let down = null;

    this.canvas.addEventListener('pointermove', (e) => {
      const at = where(e);
      if (this.gizmo.contains(at.x, at.y, at.w, at.h)) {
        const ball = this.gizmo.hit(at.x, at.y, at.w, at.h);
        this.gizmo.setHover(ball);
        this.canvas.style.cursor = ball ? 'pointer' : '';
        return;
      }
      if (this.gizmo.hovered) this.gizmo.setHover(null);
      this.canvas.style.cursor = this._under(e) ? 'pointer' : '';
    });

    this.canvas.addEventListener('pointerdown', (e) => { down = { x: e.clientX, y: e.clientY }; });
    this.canvas.addEventListener('pointerup', (e) => {
      if (!down) return;
      const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y);
      down = null;
      if (moved > 4) return;

      const at = where(e);
      if (this.gizmo.contains(at.x, at.y, at.w, at.h)) {
        const ball = this.gizmo.hit(at.x, at.y, at.w, at.h);
        if (ball) this.gizmo.onPick(ball.userData.direction);
        return;
      }
      // Clicking a part on the model selects its row, which is the way round
      // people reach for when the part names are Mesh_0 and Mesh_1.
      const mesh = this._under(e);
      this.onPick(mesh ? mesh.name : null);
    });
  }

  _under(e) {
    if (!this.model) return null;
    const r = this.canvas.getBoundingClientRect();
    this.pointer.x = ((e.clientX - r.left) / r.width) * 2 - 1;
    this.pointer.y = -(((e.clientY - r.top) / r.height) * 2 - 1);
    this.ray.setFromCamera(this.pointer, this.camera);
    const hit = this.ray.intersectObject(this.model, true)
      .find((h) => h.object.isMesh);
    return hit ? hit.object : null;
  }

  _draw() {
    requestAnimationFrame(() => this._draw());
    this.controls.update();
    this.swing.update();
    this.grid.update(this.camera);
    this.renderer.render(this.scene, this.camera);
    this.gizmo.render(this.renderer, this.camera, this.controls.target);
  }
}
