/**
 * Ground height in backend world coordinates, shared by the course and the practice green.
 *
 * Practice green: one tilted plane (as in V1). Course holes: only the green is tilted; the
 * rest of the hole is flat for physics (docs/COURSE.md). The renderer adds a visual collar
 * around course greens so the tilted green meets the flat ground without a step.
 */
import type { CourseHole, Scenario } from "@fly-golf/protocol";
import { greenHeight, type GreenLike } from "./coords";

export interface Ground {
  green: GreenLike & { radius_m: number };
  hole?: CourseHole | null;
}

export function groundFor(scenario: Scenario, hole?: CourseHole | null): Ground {
  return { green: scenario.green, hole: hole ?? null };
}

/** Width of the collar that blends a course green's rim height down to the flat hole. */
export const collarOuter = (hole: CourseHole) => hole.green.radius_m + hole.fringe_m + (hole.collar_m ?? 4);

export function heightAt(g: Ground, x: number, y: number): number {
  if (!g.hole) return greenHeight(g.green, x, y);
  // Same formula as HoleSpec.height() in the backend (course.py): the ball and the fly stand on
  // the surface the physics uses.
  const { center, radius_m: R } = g.green;
  const dx = x - center[0];
  const dy = y - center[1];
  const d = Math.hypot(dx, dy);
  if (d <= R) return greenHeight(g.green, x, y);
  const outer = collarOuter(g.hole);
  if (d >= outer) return 0;
  const t = (d - R) / (outer - R);
  const s = t * t * (3 - 2 * t);
  return greenHeight(g.green, center[0] + (dx / d) * R, center[1] + (dy / d) * R) * (1 - s);
}

/** Point-in-polygon (ray casting) for [x, y] polygons in world metres. */
export function inPolygon(poly: number[][], x: number, y: number): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export const METRES_PER_YARD = 0.9144;
export const yards = (m: number) => m / METRES_PER_YARD;

/** Broadcast-style distance: yards off the green, feet on it. */
export function distanceLabel(m: number, onGreen: boolean): string {
  if (onGreen || m < 18) return `${(m / 0.3048).toFixed(m < 3 ? 1 : 0)} ft`;
  return `${Math.round(yards(m))} yd`;
}
