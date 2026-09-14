import { describe, expect, it } from "vitest";
import type { CourseHole } from "@fly-golf/protocol";
import {
  COARSE_CELL_M,
  FINE_CELL_M,
  drapeTriangles,
  drapedGeometry,
  drapedOutline,
  type Bump,
} from "./drape";
import { collarOuter, heightAt } from "./terrain";

// Hole 1's green (course.py): the collar is the only place the ground is not flat.
const green = { center: [2, 330], radius_m: 13, slope_x: 0.008, slope_y: -0.012 };
const hole = { green, fringe_m: 1.5, collar_m: 4 } as unknown as CourseHole;
const ground = (x: number, y: number) => heightAt({ green, hole }, x, y);
const bump: Bump = { center: green.center, radius: collarOuter(hole) };

/** A curving 17 m fairway strip that runs into the green, like course.py's ribbons. */
function ribbon(): number[][] {
  const left: number[][] = [];
  const right: number[][] = [];
  for (let k = 0; k <= 40; k++) {
    const y = 230 + k * 2.6;
    const x = 12 * Math.sin((y - 230) / 40);
    const dx = (12 / 40) * Math.cos((y - 230) / 40);
    const len = Math.hypot(dx, 1);
    left.push([x - (8.5 * 1) / len, y + (8.5 * dx) / len]);
    right.push([x + (8.5 * 1) / len, y - (8.5 * dx) / len]);
  }
  return [...right, ...left.reverse()];
}

/** A kidney-shaped greenside bunker (concave), straddling the collar. */
function kidney(): number[][] {
  const out: number[][] = [];
  for (let k = 0; k < 48; k++) {
    const a = (k / 48) * Math.PI * 2;
    const r = 4 + 1.6 * Math.cos(2 * a);
    out.push([green.center[0] + 15 + r * Math.cos(a) * 1.4, green.center[1] - 3 + r * Math.sin(a)]);
  }
  return out;
}

const area = (p: number[][]) =>
  Math.abs(p.reduce((s, [x, y], i) => s + x * p[(i + 1) % p.length][1] - p[(i + 1) % p.length][0] * y, 0)) /
  2;
const triArea = ([a, b, c]: number[][]) =>
  ((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) / 2;
const key = (p: number[]) => `${p[0].toFixed(6)},${p[1].toFixed(6)}`;

function onBoundary(poly: number[][], p: number[], q: number[]): boolean {
  const mid = [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2];
  return poly.some((a, i) => {
    const b = poly[(i + 1) % poly.length];
    const cr = (b[0] - a[0]) * (mid[1] - a[1]) - (b[1] - a[1]) * (mid[0] - a[0]);
    const dot = (mid[0] - a[0]) * (b[0] - a[0]) + (mid[1] - a[1]) * (b[1] - a[1]);
    const len2 = (b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2;
    return Math.abs(cr) / Math.sqrt(len2) < 1e-6 && dot >= -1e-9 && dot <= len2 + 1e-9;
  });
}

describe("drapeTriangles", () => {
  for (const [name, poly] of [
    ["fairway ribbon", ribbon()],
    ["kidney bunker", kidney()],
  ] as const) {
    it(`covers the ${name} exactly once, facing up`, () => {
      const tris = drapeTriangles(poly, bump);
      const areas = tris.map(triArea);
      expect(Math.min(...areas)).toBeGreaterThan(0);
      const total = areas.reduce((s, a) => s + a, 0);
      expect(Math.abs(total - area(poly)) / area(poly)).toBeLessThan(1e-9);
    });

    it(`has no cracks where the ${name} crosses the collar`, () => {
      const tris = drapeTriangles(poly, bump);
      const edges = new Map<string, [number[], number[], number]>();
      for (const t of tris)
        for (let i = 0; i < 3; i++) {
          const [p, q] = [t[i], t[(i + 1) % 3]];
          const k = [key(p), key(q)].sort().join("|");
          const e = edges.get(k);
          edges.set(k, [p, q, (e?.[2] ?? 0) + 1]);
        }
      // An edge used by one triangle only is either on the polygon's outline or, if it is the
      // side of a coarse cell, on flat ground where a straight edge cannot open a crack.
      for (const [p, q, count] of edges.values()) {
        if (count !== 1 || onBoundary(poly, p, q)) continue;
        expect(ground(p[0], p[1])).toBe(0);
        expect(ground(q[0], q[1])).toBe(0);
        expect(ground((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)).toBe(0);
      }
    });

    it(`follows the ground across the collar for the ${name}`, () => {
      let worst = 0;
      for (const [a, b, c] of drapeTriangles(poly, bump)) {
        const [x, y] = [(a[0] + b[0] + c[0]) / 3, (a[1] + b[1] + c[1]) / 3];
        const flat = (ground(a[0], a[1]) + ground(b[0], b[1]) + ground(c[0], c[1])) / 3;
        worst = Math.max(worst, Math.abs(flat - ground(x, y)));
      }
      expect(worst).toBeLessThan(0.003); // well under the renderer's 15 mm paint lift
    });
  }

  it("keeps flat ground coarse", () => {
    const square = [
      [96, 0],
      [136, 0],
      [136, 40],
      [96, 40],
    ];
    const tris = drapeTriangles(square, bump);
    expect(tris.length).toBe(2 * (40 / COARSE_CELL_M) ** 2);
  });

  it("cuts fine cells only near the green", () => {
    for (const [a, b, c] of drapeTriangles(ribbon(), bump)) {
      const x = (a[0] + b[0] + c[0]) / 3;
      const y = (a[1] + b[1] + c[1]) / 3;
      const span = Math.max(...[a, b, c].flatMap((p) => [Math.abs(p[0] - x), Math.abs(p[1] - y)]));
      if (Math.hypot(x - green.center[0], y - green.center[1]) < bump.radius)
        expect(span).toBeLessThanOrEqual(FINE_CELL_M);
    }
  });
});

describe("drapedGeometry / drapedOutline", () => {
  it("lifts every vertex the same height above the ground", () => {
    const g = drapedGeometry(kidney(), ground, 0.015, bump);
    const p = g.attributes.position;
    for (let i = 0; i < p.count; i++) expect(p.getY(i) - ground(p.getX(i), -p.getZ(i))).toBeCloseTo(0.015, 5);
    expect(g.attributes.uv.count).toBe(p.count);
  });

  it("closes the outline and subdivides it on the collar", () => {
    const poly = kidney();
    const pts = drapedOutline(poly, ground, 0.02, bump);
    expect(pts[0].equals(pts[pts.length - 1])).toBe(true);
    expect(pts.length).toBeGreaterThan(poly.length + 1);
    for (const v of pts) expect(v.y - ground(v.x, -v.z)).toBeCloseTo(0.02, 5);
  });
});
