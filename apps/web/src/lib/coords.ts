/**
 * Backend world frame: metres, +x east, +y north, +z up, headings CCW from +x.
 * three.js frame: +y up. Mapping: (x, y, z)_world -> (x, z, -y)_three.
 * A heading h becomes a rotation of h about the three.js +y axis.
 */
export type Vec3 = [number, number, number];

export interface GreenLike {
  slope_x: number;
  slope_y: number;
  center: number[];
}

export function greenHeight(g: GreenLike, x: number, y: number): number {
  return g.slope_x * (x - g.center[0]) + g.slope_y * (y - g.center[1]);
}

export function toThree(x: number, y: number, z = 0): Vec3 {
  return [x, z, -y];
}

/** Unit direction in three.js coordinates for a world heading. */
export function headingDir3(h: number): Vec3 {
  return [Math.cos(h), 0, -Math.sin(h)];
}

export function trajectoryDuration(points: number[][]): number {
  return points.length ? points[points.length - 1][0] : 0;
}

/** Linear interpolation of a (t, x, y, z) trajectory at time t (clamped). Returns world [x, y, z]. */
export function sampleTrajectory(points: number[][], t: number): Vec3 {
  if (points.length === 0) return [0, 0, 0];
  if (t <= points[0][0]) return [points[0][1], points[0][2], points[0][3]];
  const last = points[points.length - 1];
  if (t >= last[0]) return [last[1], last[2], last[3]];
  let lo = 0;
  let hi = points.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (points[mid][0] <= t) lo = mid;
    else hi = mid;
  }
  const a = points[lo];
  const b = points[hi];
  const f = (t - a[0]) / (b[0] - a[0] || 1);
  return [a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f, a[3] + (b[3] - a[3]) * f];
}

export function metresToFeet(m: number): number {
  return m / 0.3048;
}
