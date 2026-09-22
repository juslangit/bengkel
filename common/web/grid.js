/* The floor.
 *
 * A grid made of actual lines has two problems: close up the lines are fat
 * and blocky, and far away they crowd together into a shimmering moiré mess.
 * Blender's floor has neither, because it is not lines at all - it is a
 * single flat surface with a shader that works out, for each pixel, how close
 * that pixel is to a grid line and how wide a line ought to look from here.
 *
 * `fwidth` is what makes that possible: it reports how much a value changes
 * between one pixel and the next, which is exactly "how big is a pixel, in
 * world units, at this spot". Dividing by it gives a line that is always
 * about one pixel wide however close or far the camera is.
 *
 * On top of that there are two grids rather than one - a fine one and a
 * coarser one every tenth line - and the two axis lines through the origin,
 * coloured. In gerak's world Y is up, so the floor is the XZ plane: the red
 * line runs along X and the blue one along Z.
 */

import * as THREE from 'three';

const VERTEX = /* glsl */`
  varying vec3 vWorld;
  void main() {
    vec4 world = modelMatrix * vec4(position, 1.0);
    vWorld = world.xyz;
    gl_Position = projectionMatrix * viewMatrix * world;
  }
`;

const FRAGMENT = /* glsl */`
  precision highp float;

  varying vec3 vWorld;

  uniform vec3  uCamera;
  uniform float uUnit;        // the fine grid spacing, in world units
  uniform float uBlock;       // how many fine squares make a coarse one
  uniform vec3  uThin;
  uniform vec3  uThick;
  uniform vec3  uAxisX;
  uniform vec3  uAxisZ;
  uniform float uNear;        // fully visible up to here
  uniform float uFar;         // gone by here
  uniform float uOpacity;

  /* How much of a grid line is under this pixel, 0 to 1.
   *
   * fract() turns the world position into "how far through the current
   * square am I", and dividing the distance-to-the-nearest-line by fwidth
   * measures it in pixels rather than in metres - which is why the line stays
   * one pixel wide at any zoom instead of thickening as you fly in. */
  float lineCoverage(vec2 coord, float spacing) {
    vec2 square = coord / spacing;
    vec2 distance = abs(fract(square - 0.5) - 0.5) / fwidth(square);
    return 1.0 - min(min(distance.x, distance.y), 1.0);
  }

  /* The same idea for a single line: one axis, through the origin. */
  float axisCoverage(float offset) {
    return 1.0 - min(abs(offset) / (fwidth(offset) * 1.2), 1.0);
  }

  void main() {
    vec2 coord = vWorld.xz;

    // Fade out with distance, so the far grid dissolves rather than turning
    // into a shimmering mess of half-pixel lines.
    float away = distance(uCamera.xz, coord);
    float fade = 1.0 - smoothstep(uNear, uFar, away);
    if (fade <= 0.001) discard;

    float thin  = lineCoverage(coord, uUnit);
    float thick = lineCoverage(coord, uUnit * uBlock);

    vec3  colour = uThin;
    float alpha  = thin * 0.55;
    if (thick > 0.0) {
      colour = mix(colour, uThick, thick);
      alpha  = max(alpha, thick * 0.92);
    }

    // The two lines through the origin, drawn over the grid.
    float alongX = axisCoverage(vWorld.z);   // z = 0, so it runs along X
    float alongZ = axisCoverage(vWorld.x);   // x = 0, so it runs along Z
    if (alongX > 0.0) { colour = uAxisX; alpha = max(alpha, alongX); }
    if (alongZ > 0.0) { colour = uAxisZ; alpha = max(alpha, alongZ); }

    gl_FragColor = vec4(colour, alpha * fade * uOpacity);
  }
`;

export class Grid extends THREE.Mesh {
  constructor() {
    const geometry = new THREE.PlaneGeometry(1, 1);
    geometry.rotateX(-Math.PI / 2);          // lie it down on the XZ plane

    const material = new THREE.ShaderMaterial({
      vertexShader: VERTEX,
      fragmentShader: FRAGMENT,
      transparent: true,
      depthWrite: false,                     // never hide anything behind it
      side: THREE.DoubleSide,                // visible from under the floor
      uniforms: {
        uCamera:  { value: new THREE.Vector3() },
        uUnit:    { value: 0.1 },
        uBlock:   { value: 10 },
        // Brighter than Blender's, because gerak's viewport is much darker
        // than Blender's mid grey and the same values would vanish into it.
        uThin:    { value: new THREE.Color(0x6a7486) },
        uThick:   { value: new THREE.Color(0x98a3b6) },
        uAxisX:   { value: new THREE.Color(0xe2574f) },   // X, red
        uAxisZ:   { value: new THREE.Color(0x4a8fd6) },   // Z, blue
        uNear:    { value: 6 },
        uFar:     { value: 26 },
        uOpacity: { value: 1 },
      },
    });

    super(geometry, material);
    this.frustumCulled = false;
    this.renderOrder = -1;                   // under everything else
    this.scale.setScalar(4000);
  }

  /**
   * Choose a grid spacing that suits the model.
   *
   * A 2 m character and a 12 cm chess piece should both sit on a floor with
   * a sensible number of squares under them, so the spacing is picked as a
   * round number near a tenth of the model's size. Rounding to a power of ten
   * keeps the coarse lines meaningful - they are still every tenth line.
   */
  fitTo(modelSize) {
    const rough = Math.max(modelSize, 0.001) / 10;
    const unit = Math.pow(10, Math.round(Math.log10(rough)));
    this.material.uniforms.uUnit.value = unit;
    this.material.uniforms.uNear.value = modelSize * 5;
    this.material.uniforms.uFar.value = modelSize * 22;
    return unit;
  }

  /**
   * Keep the surface under the camera.
   *
   * The pattern is worked out from world coordinates, so sliding the surface
   * about does not slide the grid with it - it only makes sure there is
   * always surface wherever you are looking. That is what makes it read as
   * infinite rather than as a very large square.
   */
  update(camera) {
    this.position.x = camera.position.x;
    this.position.z = camera.position.z;
    this.material.uniforms.uCamera.value.copy(camera.position);
  }
}
