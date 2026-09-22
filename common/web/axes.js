/* The axis gizmo in the corner.
 *
 * Six balls and three lines that turn with the view, so you can always tell
 * which way round the model is — and click one to snap the camera flat onto
 * that axis. The same widget Blender puts in the top right.
 *
 * It is drawn by the same renderer as the viewport, into a small square of
 * the canvas with the depth buffer cleared first. That is cheaper than a
 * second canvas and it can never drift out of step with the main camera,
 * because it is handed that camera's orientation every frame.
 *
 * One honest difference from Blender. gerak's world is **Y up**, like glTF
 * and like Godot, because that is what the files it opens and writes
 * actually contain. Blender is Z up, so its gizmo shows Z at the top where
 * this one shows Y. The letters here name the axes the model really has,
 * rather than the ones Blender would have called them.
 */

import * as THREE from 'three';

const AXES = [
  { key: 'X', dir: new THREE.Vector3(1, 0, 0), colour: '#e2574f', hex: 0xe2574f },
  { key: 'Y', dir: new THREE.Vector3(0, 1, 0), colour: '#9ccb3b', hex: 0x9ccb3b },
  { key: 'Z', dir: new THREE.Vector3(0, 0, 1), colour: '#4a8fd6', hex: 0x4a8fd6 },
];

/** A ball: filled with its letter for a positive axis, a ring for a negative. */
function ballTexture(colour, letter, filled) {
  const size = 128;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const c = canvas.getContext('2d');
  const middle = size / 2;
  const radius = size * 0.40;

  if (filled) {
    c.beginPath();
    c.arc(middle, middle, radius, 0, Math.PI * 2);
    c.fillStyle = colour;
    c.fill();
    c.lineWidth = size * 0.045;
    c.strokeStyle = 'rgba(0,0,0,0.30)';
    c.stroke();

    c.fillStyle = '#ffffff';
    c.font = `600 ${size * 0.46}px ui-sans-serif, -apple-system, system-ui, sans-serif`;
    c.textAlign = 'center';
    c.textBaseline = 'middle';
    c.fillText(letter, middle, middle + size * 0.02);
  } else {
    c.beginPath();
    c.arc(middle, middle, radius * 0.86, 0, Math.PI * 2);
    c.fillStyle = 'rgba(22,24,29,0.55)';
    c.fill();
    c.lineWidth = size * 0.085;
    c.strokeStyle = colour;
    c.stroke();
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  return texture;
}

export class AxisGizmo {
  /**
   * @param {object} opts
   * @param {number} opts.size    the square it is drawn in, in CSS pixels
   * @param {number} opts.margin  how far in from the corner
   */
  constructor({ size = 124, margin = 16 } = {}) {
    this.size = size;
    this.margin = margin;
    this.hovered = null;
    this.onPick = () => {};

    this.scene = new THREE.Scene();
    this.camera = new THREE.OrthographicCamera(-1.45, 1.45, 1.45, -1.45, 0.1, 12);

    this.balls = [];
    const positions = [];
    const colours = [];

    for (const axis of AXES) {
      // The line from the middle out to the positive ball.
      positions.push(0, 0, 0, axis.dir.x, axis.dir.y, axis.dir.z);
      const colour = new THREE.Color(axis.hex);
      colours.push(colour.r, colour.g, colour.b, colour.r, colour.g, colour.b);

      for (const sign of [1, -1]) {
        const filled = sign > 0;
        const material = new THREE.SpriteMaterial({
          map: ballTexture(axis.colour, axis.key, filled),
          transparent: true,
          depthTest: true,
          depthWrite: true,
          sizeAttenuation: false,
        });
        const ball = new THREE.Sprite(material);
        ball.position.copy(axis.dir).multiplyScalar(sign);
        ball.scale.setScalar(filled ? 0.60 : 0.46);
        ball.userData = {
          axis: axis.key,
          sign,
          direction: axis.dir.clone().multiplyScalar(sign),
          base: filled ? 0.60 : 0.46,
          filled,
          colour: axis.colour,
          letter: axis.key,
        };
        this.scene.add(ball);
        this.balls.push(ball);
      }
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.Float32BufferAttribute(colours, 3));
    this.lines = new THREE.LineSegments(
      geometry,
      new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.95 })
    );
    this.scene.add(this.lines);

    this.ray = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this._direction = new THREE.Vector3();
  }

  /** Where the gizmo sits on the canvas, in CSS pixels from the top left. */
  rect(width, height) {
    return {
      left: width - this.size - this.margin,
      top: this.margin,
      size: this.size,
    };
  }

  contains(x, y, width, height) {
    const box = this.rect(width, height);
    return x >= box.left && x <= box.left + box.size
        && y >= box.top && y <= box.top + box.size;
  }

  /** Which ball is under this point, if any. */
  hit(x, y, width, height) {
    if (!this.contains(x, y, width, height)) return null;
    const box = this.rect(width, height);
    this.pointer.x = ((x - box.left) / box.size) * 2 - 1;
    this.pointer.y = -(((y - box.top) / box.size) * 2 - 1);
    this.ray.setFromCamera(this.pointer, this.camera);
    const found = this.ray.intersectObjects(this.balls, false);
    return found.length ? found[0].object : null;
  }

  setHover(ball) {
    if (this.hovered === ball) return;
    this.hovered = ball;
    for (const one of this.balls) {
      const grown = one === ball;
      one.scale.setScalar(one.userData.base * (grown ? 1.28 : 1));
      // A negative ball earns its letter while the cursor is on it, which is
      // how you can tell -X from -Z before you commit to the click.
      const shouldFill = one.userData.filled || grown;
      if (one.userData.shown !== shouldFill) {
        one.userData.shown = shouldFill;
        one.material.map.dispose();
        one.material.map = ballTexture(one.userData.colour, one.userData.letter, shouldFill);
        one.material.needsUpdate = true;
      }
    }
  }

  /**
   * Draw it into the corner of the viewport.
   *
   * The gizmo camera is put at the same angle to the origin as the real
   * camera is to whatever it is orbiting, so the widget turns exactly as the
   * view does.
   */
  render(renderer, camera, target) {
    this._direction.subVectors(camera.position, target);
    if (this._direction.lengthSq() < 1e-12) this._direction.set(0, 0, 1);
    this._direction.normalize().multiplyScalar(6);
    this.camera.position.copy(this._direction);
    this.camera.up.copy(camera.up);
    this.camera.lookAt(0, 0, 0);
    this.camera.updateProjectionMatrix();

    const canvas = renderer.getSize(new THREE.Vector2());
    const box = this.rect(canvas.x, canvas.y);
    // setViewport measures from the bottom of the canvas; the rest of the app
    // thinks in CSS pixels from the top, so the y is flipped here once and
    // nowhere else.
    const bottom = canvas.y - box.top - box.size;

    const wasAutoClear = renderer.autoClear;
    renderer.autoClear = false;
    renderer.setScissorTest(true);
    renderer.setViewport(box.left, bottom, box.size, box.size);
    renderer.setScissor(box.left, bottom, box.size, box.size);
    renderer.clearDepth();
    renderer.render(this.scene, this.camera);
    renderer.setScissorTest(false);
    renderer.setViewport(0, 0, canvas.x, canvas.y);
    renderer.autoClear = wasAutoClear;
  }
}

/**
 * Swing a camera round to look straight down an axis.
 *
 * It keeps its distance from what it is looking at and only changes where it
 * stands, so clicking an axis frames the same thing from a new side rather
 * than jumping somewhere else entirely.
 */
export class CameraSwing {
  constructor(camera, orbit) {
    this.camera = camera;
    this.orbit = orbit;
    this.from = new THREE.Vector3();
    this.to = new THREE.Vector3();
    this.upFrom = new THREE.Vector3();
    this.upTo = new THREE.Vector3();
    this.started = 0;
    this.length = 380;
    this.running = false;
  }

  to_(direction) { return direction; }

  start(direction) {
    const distance = this.camera.position.distanceTo(this.orbit.target) || 1;
    this.from.copy(this.camera.position);
    this.to.copy(this.orbit.target)
      .add(direction.clone().normalize().multiplyScalar(distance));

    this.upFrom.copy(this.camera.up);
    // Looking straight down Y, "up" cannot also be Y, so borrow Z.
    this.upTo.set(0, 1, 0);
    if (Math.abs(direction.y) > 0.999) this.upTo.set(0, 0, direction.y > 0 ? -1 : 1);

    this.started = performance.now();
    this.running = true;
  }

  /** @returns true while it is still moving. */
  update() {
    if (!this.running) return false;
    const t = Math.min(1, (performance.now() - this.started) / this.length);
    const eased = t * t * (3 - 2 * t);
    this.camera.position.lerpVectors(this.from, this.to, eased);
    this.camera.up.lerpVectors(this.upFrom, this.upTo, eased).normalize();
    this.camera.lookAt(this.orbit.target);
    if (t >= 1) this.running = false;
    return true;
  }
}
