/**
 * Draping flat course polygons (fairways, bunkers, water) onto the ground.
 *
 * The hole is flat except inside the green's collar, where the tilted green rises out of (or dips
 * into) the ground (lib/terrain.ts). A polygon triangulated only at its own vertices crosses that
 * bump with long flat triangles that sink into it or float above it, so each polygon is cut along
 * a grid first: COARSE_CELL_M cells on flat ground, FINE_CELL_M cells wherever a coarse cell
 * touches the bump. Coarse and fine cells only meet outside the bump, where the ground is exactly
 * flat, so the mesh has no cracks.
 */
import * as THREE from "three";

export type HeightFn = (x: number, y: number) => number;

/** Disc outside which the ground is flat: the green plus its collar. */
export interface Bump {
  center: number[];
  radius: number;
}

export const COARSE_CELL_M = 8;
export const FINE_CELL_M = 0.5;

type Pt = [number, number];

/** Sutherland-Hodgman against one axis-aligned half-plane. */
function clipHalf(poly: Pt[], axis: 0 | 1, v: number, keepGreater: boolean): Pt[] {
  const out: Pt[] = [];
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i];
    const b = poly[(i + 1) % poly.length];
    const ina = keepGreater ? a[axis] >= v : a[axis] <= v;
    const inb = keepGreater ? b[axis] >= v : b[axis] <= v;
    if (ina) out.push(a);
    if (ina !== inb) {
      const t = (v - a[axis]) / (b[axis] - a[axis]);
      out.push(axis === 0 ? [v, a[1] + (b[1] - a[1]) * t] : [a[0] + (b[0] - a[0]) * t, v]);
    }
  }
  return out;
}

function clipRect(poly: Pt[], x0: number, y0: number, x1: number, y1: number): Pt[] {
  let p = clipHalf(poly, 0, x0, true);
  if (p.length) p = clipHalf(p, 0, x1, false);
  if (p.length) p = clipHalf(p, 1, y0, true);
  if (p.length) p = clipHalf(p, 1, y1, false);
  return p;
}

const cross = (a: Pt, b: Pt, c: Pt) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);

/** Triangulate one clipped piece; triangles counter-clockwise in world (x, y), i.e. facing up. */
function triangulate(piece: Pt[], out: Pt[][]) {
  const pts: Pt[] = [];
  for (const p of piece) {
    const q = pts[pts.length - 1];
    if (!q || Math.abs(q[0] - p[0]) > 1e-9 || Math.abs(q[1] - p[1]) > 1e-9) pts.push(p);
  }
  while (
    pts.length > 1 &&
    Math.abs(pts[0][0] - pts[pts.length - 1][0]) < 1e-9 &&
    Math.abs(pts[0][1] - pts[pts.length - 1][1]) < 1e-9
  )
    pts.pop();
  if (pts.length < 3) return;
  const idx = THREE.ShapeUtils.triangulateShape(
    pts.map(([x, y]) => new THREE.Vector2(x, y)),
    [],
  );
  for (const [i, j, k] of idx) {
    const a = cross(pts[i], pts[j], pts[k]);
    if (Math.abs(a) < 1e-10) continue;
    out.push(a > 0 ? [pts[i], pts[j], pts[k]] : [pts[i], pts[k], pts[j]]);
  }
}

function touchesBump(bump: Bump | null, x0: number, y0: number, x1: number, y1: number): boolean {
  if (!bump) return false;
  const [cx, cy] = bump.center;
  const dx = Math.max(x0 - cx, 0, cx - x1);
  const dy = Math.max(y0 - cy, 0, cy - y1);
  return Math.hypot(dx, dy) < bump.radius;
}

/** Triangles in world (x, y) covering `poly`, fine wherever the ground bends. */
export function drapeTriangles(poly: number[][], bump: Bump | null): Pt[][] {
  const src = poly.map(([x, y]) => [x, y] as Pt);
  const xs = src.map((p) => p[0]);
  const ys = src.map((p) => p[1]);
  const C = COARSE_CELL_M;
  const F = FINE_CELL_M;
  const tris: Pt[][] = [];
  for (let i = Math.floor(Math.min(...xs) / C); i * C < Math.max(...xs); i++) {
    for (let j = Math.floor(Math.min(...ys) / C); j * C < Math.max(...ys); j++) {
      const [x0, y0, x1, y1] = [i * C, j * C, (i + 1) * C, (j + 1) * C];
      const piece = clipRect(src, x0, y0, x1, y1);
      if (piece.length < 3) continue;
      if (!touchesBump(bump, x0, y0, x1, y1)) {
        triangulate(piece, tris);
        continue;
      }
      const n = Math.round(C / F);
      for (let a = 0; a < n; a++)
        for (let b = 0; b < n; b++) {
          const sub = clipRect(piece, x0 + a * F, y0 + b * F, x0 + (a + 1) * F, y0 + (b + 1) * F);
          if (sub.length >= 3) triangulate(sub, tris);
        }
    }
  }
  return tris;
}

/** Up-facing unit normal of the ground at (x, y), in three.js axes (x, up, -y). */
function groundNormal(ground: HeightFn, x: number, y: number, out: THREE.Vector3): THREE.Vector3 {
  const e = 0.05;
  const hx = (ground(x + e, y) - ground(x - e, y)) / (2 * e);
  const hy = (ground(x, y + e) - ground(x, y - e)) / (2 * e);
  return out.set(-hx, 1, hy).normalize();
}

/** `poly` as a mesh lying `lift` metres above the ground, with world-metre UVs. */
export function drapedGeometry(
  poly: number[][],
  ground: HeightFn,
  lift: number,
  bump: Bump | null,
): THREE.BufferGeometry {
  const tris = drapeTriangles(poly, bump);
  const pos = new Float32Array(tris.length * 9);
  const nor = new Float32Array(tris.length * 9);
  const uv = new Float32Array(tris.length * 6);
  const n = new THREE.Vector3();
  let v = 0;
  for (const tri of tris)
    for (const [x, y] of tri) {
      pos.set([x, ground(x, y) + lift, -y], v * 3);
      groundNormal(ground, x, y, n);
      nor.set([n.x, n.y, n.z], v * 3);
      uv.set([x, y], v * 2);
      v++;
    }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setAttribute("normal", new THREE.BufferAttribute(nor, 3));
  g.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
  return g;
}

/** Closed outline of `poly` `lift` metres above the ground, subdivided where the ground bends. */
export function drapedOutline(
  poly: number[][],
  ground: HeightFn,
  lift: number,
  bump: Bump | null,
): THREE.Vector3[] {
  const out: THREE.Vector3[] = [];
  for (let i = 0; i < poly.length; i++) {
    const [ax, ay] = poly[i];
    const [bx, by] = poly[(i + 1) % poly.length];
    const near = touchesBump(bump, Math.min(ax, bx), Math.min(ay, by), Math.max(ax, bx), Math.max(ay, by));
    const steps = near ? Math.max(1, Math.ceil(Math.hypot(bx - ax, by - ay) / FINE_CELL_M)) : 1;
    for (let k = 0; k < steps; k++) {
      const x = ax + ((bx - ax) * k) / steps;
      const y = ay + ((by - ay) * k) / steps;
      out.push(new THREE.Vector3(x, ground(x, y) + lift, -y));
    }
  }
  out.push(out[0].clone());
  return out;
}
