/**
 * One hole of the course, rendered from the backend's geometry (the same polygons the
 * physics uses): rough everywhere, fairway strips, bunkers, animated water, a tilted green
 * with a collar, the tee box, and the tree lines that mark out of bounds. Colours come from the
 * hole's theme (scene/theme.ts): parkland on the front nine, dusk on the back.
 */
import { useLayoutEffect, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Line } from "@react-three/drei";
import * as THREE from "three";
import type { CourseHole as Hole } from "@fly-golf/protocol";
import { greenHeight } from "../lib/coords";
import { drapedGeometry, drapedOutline, type Bump, type HeightFn } from "../lib/drape";
import { collarOuter, heightAt, inPolygon } from "../lib/terrain";
import { CUP_RADIUS, Flag, stripeTexture } from "./Course";
import { themeFor, type Theme } from "./theme";

/**
 * How the ground is drawn. The base - rough, the green's collar and the green - is one
 * continuous surface at the height the physics uses, and the only ground that writes depth.
 * Fairways, tee, sand, fringe and water are painted over it without writing depth, in the
 * backend's surface priority (course.py HoleSpec.surface: water > green > fringe > sand > tee >
 * fairway > rough): where two overlap, the one the physics sees is the one on top, and no two
 * layers can z-fight however far away the camera is.
 */
const PAINT_LIFT = 0.015;
const ORDER = { base: -10, fairway: -9, tee: -8, sand: -7, rim: -6.5, fringe: -6, green: -5, water: -4 };
/** Segments around the green; the collar's outer edge and the hole cut in the rough share them. */
const RING_SEGMENTS = 128;

function noiseTexture(
  base: [number, number, number],
  amp: number,
  size = 256,
  seed = 3,
): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d")!;
  const img = g.createImageData(size, size);
  let s = seed;
  for (let p = 0; p < img.data.length; p += 4) {
    s = (s * 16807) % 2147483647;
    const n = (s / 2147483647 - 0.5) * amp;
    img.data[p] = base[0] + n;
    img.data[p + 1] = base[1] + n;
    img.data[p + 2] = base[2] + n * 0.7;
    img.data[p + 3] = 255;
  }
  g.putImageData(img, 0, 0);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

/** A quiet tiling ground texture: one base colour, soft blotches of a second colour at low
 *  opacity (the heather in the dusk rough) and a fine grain. No bands, no hard edges. */
function mottleTexture({ base, patch, grain }: { base: string; patch: string; grain: number }) {
  const size = 512;
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d")!;
  g.fillStyle = base;
  g.fillRect(0, 0, size, size);
  let s = 41;
  const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
  const tint = new THREE.Color(patch);
  const rgba = (a: number) =>
    `rgba(${Math.round(tint.r * 255)},${Math.round(tint.g * 255)},${Math.round(tint.b * 255)},${a})`;
  for (let i = 0; i < 70; i++) {
    const x = rnd() * size;
    const y = rnd() * size;
    const r = 20 + rnd() * 60;
    // drawn at each wrap offset so the tile repeats without seams
    for (const ox of [-size, 0, size])
      for (const oy of [-size, 0, size]) {
        const grad = g.createRadialGradient(x + ox, y + oy, 0, x + ox, y + oy, r);
        grad.addColorStop(0, rgba(0.13));
        grad.addColorStop(1, rgba(0));
        g.fillStyle = grad;
        g.fillRect(x + ox - r, y + oy - r, 2 * r, 2 * r);
      }
  }
  const img = g.getImageData(0, 0, size, size);
  for (let p = 0; p < img.data.length; p += 4) {
    const n = (rnd() - 0.5) * grain;
    img.data[p] += n;
    img.data[p + 1] += n;
    img.data[p + 2] += n * 0.7;
  }
  g.putImageData(img, 0, 0);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  return t;
}

/** A tiling normal map made from smooth value noise: gives the water moving highlights. */
function waterNormals(size = 256): THREE.CanvasTexture {
  const h = new Float32Array(size * size);
  let s = 17;
  const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
  const octaves = [8, 16, 32];
  for (const cells of octaves) {
    const grid = Array.from({ length: cells * cells }, rnd);
    const at = (i: number, j: number) => grid[((j + cells) % cells) * cells + ((i + cells) % cells)];
    for (let y = 0; y < size; y++)
      for (let x = 0; x < size; x++) {
        const fx = (x / size) * cells;
        const fy = (y / size) * cells;
        const i = Math.floor(fx);
        const j = Math.floor(fy);
        const u = fx - i;
        const v = fy - j;
        const a = at(i, j) * (1 - u) + at(i + 1, j) * u;
        const b = at(i, j + 1) * (1 - u) + at(i + 1, j + 1) * u;
        h[y * size + x] += (a * (1 - v) + b * v) / cells;
      }
  }
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d")!;
  const img = g.createImageData(size, size);
  for (let y = 0; y < size; y++)
    for (let x = 0; x < size; x++) {
      const dx = h[y * size + ((x + 1) % size)] - h[y * size + ((x - 1 + size) % size)];
      const dy = h[((y + 1) % size) * size + x] - h[((y - 1 + size) % size) * size + x];
      const n = new THREE.Vector3(-dx * 60, -dy * 60, 1).normalize();
      const p = (y * size + x) * 4;
      img.data[p] = (n.x * 0.5 + 0.5) * 255;
      img.data[p + 1] = (n.y * 0.5 + 0.5) * 255;
      img.data[p + 2] = (n.z * 0.5 + 0.5) * 255;
      img.data[p + 3] = 255;
    }
  g.putImageData(img, 0, 0);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return t;
}

/** An equirectangular sky gradient for the water to reflect (the dusk sunset). */
function skyGradient(r: NonNullable<Theme["water"]["reflect"]>): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = 256;
  c.height = 128;
  const g = c.getContext("2d")!;
  const v = g.createLinearGradient(0, 0, 0, c.height);
  v.addColorStop(0, r.zenith);
  v.addColorStop(0.47, r.horizon);
  v.addColorStop(0.53, r.horizon);
  v.addColorStop(1, r.zenith);
  g.fillStyle = v;
  g.fillRect(0, 0, c.width, c.height);
  // the sun's glow on the horizon, toward the sunset
  const glow = g.createRadialGradient(c.width * 0.6, c.height * 0.5, 0, c.width * 0.6, c.height * 0.5, 60);
  glow.addColorStop(0, r.glow);
  glow.addColorStop(1, "rgba(0,0,0,0)");
  g.fillStyle = glow;
  g.fillRect(0, 0, c.width, c.height);
  const t = new THREE.CanvasTexture(c);
  t.mapping = THREE.EquirectangularReflectionMapping;
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

/**
 * The outline of each water polygon, minus the stretches that run inside another water polygon: an
 * island green's ring can be built from several overlapping pieces of water, and their seams must
 * not show as banks in the middle of the lake. Polygons that overlap nothing keep their outline as
 * one closed line.
 */
function bankSegments(
  polys: number[][][],
  ground: HeightFn,
  bump: Bump,
): { points: THREE.Vector3[]; segments: boolean }[] {
  return polys.map((p, i) => {
    const pts = drapedOutline(p, ground, PAINT_LIFT + 0.006, bump);
    const others = polys.filter((_, j) => j !== i);
    const wet = (v: THREE.Vector3) => others.some((o) => inPolygon(o, v.x, -v.z));
    if (!others.length || !pts.some(wet)) return { points: pts, segments: false };
    const out: THREE.Vector3[] = [];
    for (let k = 0; k + 1 < pts.length; k++) {
      const a = pts[k];
      const b = pts[k + 1];
      if (!wet(a.clone().lerp(b, 0.5))) out.push(a, b);
    }
    return { points: out, segments: true };
  });
}

function Water({
  polys,
  ground,
  bump,
  theme,
}: {
  polys: number[][][];
  ground: HeightFn;
  bump: Bump;
  theme: Theme["water"];
}) {
  const normals = useMemo(() => {
    const t = waterNormals();
    t.repeat.set(1 / 9, 1 / 9);
    return t;
  }, []);
  const envMap = useMemo(() => (theme.reflect ? skyGradient(theme.reflect) : null), [theme.reflect]);
  const geoms = useMemo(
    () => polys.map((p) => drapedGeometry(p, ground, PAINT_LIFT, bump)),
    [polys, ground, bump],
  );
  const banks = useMemo(() => bankSegments(polys, ground, bump), [polys, ground, bump]);
  useFrame((_, dt) => {
    normals.offset.x += dt * 0.012;
    normals.offset.y += dt * 0.007;
  });
  return (
    <group>
      {geoms.map((g, i) => (
        <mesh key={i} geometry={g} renderOrder={ORDER.water} receiveShadow>
          <meshStandardMaterial
            color={theme.color}
            roughness={theme.roughness}
            metalness={theme.metalness}
            normalMap={normals}
            normalScale={new THREE.Vector2(theme.normalScale, theme.normalScale)}
            envMap={envMap}
            envMapIntensity={theme.reflect?.intensity ?? 1}
            depthWrite={false}
          />
        </mesh>
      ))}
      {banks.map((b, i) =>
        b.points.length < 2 ? null : (
          <Line
            key={i}
            points={b.points}
            segments={b.segments || undefined}
            color={theme.bank}
            lineWidth={2.2}
            transparent
            opacity={theme.bankOpacity}
            depthWrite={false}
          />
        ),
      )}
    </group>
  );
}

/** How far the hole reaches from `center`: its trees and every surface polygon. */
function holeExtent(hole: Hole, center: [number, number]): number {
  const pts = [
    ...hole.trees,
    ...hole.route,
    ...hole.fairways.flat(),
    ...hole.bunkers.flat(),
    ...hole.water.flat(),
  ];
  return pts.reduce((m, p) => Math.max(m, Math.hypot(p[0] - center[0], p[1] - center[1])), 0);
}

/** The backdrop ring starts 330 m out (every front-nine hole fits inside it); a longer or
 *  wider hole pushes it out so the backdrop never stands on the hole. */
const BACKDROP_INNER = 330;
const BACKDROP_CLEARANCE = 15;

function Trees({
  trees,
  center,
  extent,
  theme,
}: {
  trees: number[][];
  center: [number, number];
  extent: number;
  theme: Theme["trees"];
}) {
  // Hole-edge trees (kind 0 = conifer, 1 = round) plus a far backdrop ring for the horizon.
  const inner = Math.max(BACKDROP_INNER, extent + BACKDROP_CLEARANCE);
  const all = useMemo(() => {
    const out = trees.map((t) => [...t]);
    let seed = 29;
    const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    for (let i = 0; i < 150; i++) {
      const a = (i / 150) * Math.PI * 2 + rnd() * 0.05;
      const r = inner + rnd() * 160;
      out.push([
        center[0] + Math.cos(a) * r,
        center[1] + Math.sin(a) * r,
        14 + rnd() * 16,
        rnd() < theme.coniferShare ? 0 : 1,
      ]);
    }
    return out;
  }, [trees, center, inner, theme.coniferShare]);
  const conifers = all.filter((t) => t[3] < 0.5);
  const rounds = all.filter((t) => t[3] >= 0.5);
  const cone = useRef<THREE.InstancedMesh>(null);
  const ball = useRef<THREE.InstancedMesh>(null);
  const trunk = useRef<THREE.InstancedMesh>(null);

  useLayoutEffect(() => {
    const m = new THREE.Matrix4();
    const q = new THREE.Quaternion();
    const col = new THREE.Color();
    let seed = 5;
    const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    // hue first, then lightness: the same draws, in the same order, as before themes existed
    const tint = (t: Theme["trees"]["conifer"]) => {
      const h = t.hue + rnd() * t.hueSpread;
      return col.setHSL(h, t.sat, t.light + rnd() * t.lightSpread);
    };
    conifers.forEach(([x, y, h], i) => {
      m.compose(
        new THREE.Vector3(x, h * 0.25 + h * 0.375, -y),
        q,
        new THREE.Vector3(h * 0.24, h * 0.75, h * 0.24),
      );
      cone.current!.setMatrixAt(i, m);
      cone.current!.setColorAt(i, tint(theme.conifer));
    });
    rounds.forEach(([x, y, h], i) => {
      m.compose(new THREE.Vector3(x, h * 0.62, -y), q, new THREE.Vector3(h * 0.3, h * 0.28, h * 0.3));
      ball.current!.setMatrixAt(i, m);
      ball.current!.setColorAt(i, tint(theme.round));
    });
    all.forEach(([x, y, h], i) => {
      m.compose(new THREE.Vector3(x, h * 0.18, -y), q, new THREE.Vector3(0.45, h * 0.36, 0.45));
      trunk.current!.setMatrixAt(i, m);
    });
    for (const r of [cone, ball, trunk]) {
      r.current!.instanceMatrix.needsUpdate = true;
      if (r.current!.instanceColor) r.current!.instanceColor.needsUpdate = true;
    }
  }, [all, conifers, rounds, theme]);

  return (
    <group>
      <instancedMesh ref={cone} args={[undefined, undefined, conifers.length]} castShadow>
        <coneGeometry args={[1, 1, 8]} />
        <meshStandardMaterial roughness={0.9} flatShading />
      </instancedMesh>
      <instancedMesh ref={ball} args={[undefined, undefined, rounds.length]} castShadow>
        <icosahedronGeometry args={[1, 1]} />
        <meshStandardMaterial roughness={0.9} flatShading />
      </instancedMesh>
      <instancedMesh ref={trunk} args={[undefined, undefined, all.length]} castShadow>
        <cylinderGeometry args={[0.7, 1, 1, 6]} />
        <meshStandardMaterial color={theme.trunk} roughness={1} />
      </instancedMesh>
    </group>
  );
}

function Green({ hole, ground, theme }: { hole: Hole; ground: HeightFn; theme: Theme["ground"] }) {
  const g = hole.green;
  const [gx, gy] = g.center;
  const R = g.radius_m;
  const outer = collarOuter(hole); // same collar as the physics (course.py HoleSpec.height)
  const tex = useMemo(() => {
    const t = stripeTexture(theme.green[0], theme.green[1]);
    t.repeat.set(R / 1.5, R / 1.5);
    return t;
  }, [R, theme.green]);
  const surface = useMemo(() => {
    const geom = new THREE.CircleGeometry(R, RING_SEGMENTS).rotateX(-Math.PI / 2);
    const p = geom.attributes.position as THREE.BufferAttribute;
    for (let i = 0; i < p.count; i++) {
      const x = p.getX(i) + gx;
      const y = -p.getZ(i) + gy;
      p.setXYZ(i, x, greenHeight(g, x, y) + 0.004, -y);
    }
    geom.computeVertexNormals();
    return geom;
  }, [g, R, gx, gy]);
  // The collar (base) blends the green's rim down to the flat hole; the fringe is painted on
  // its inner edge. Both fade fringe -> rough outward.
  const [collar, fringe] = useMemo(() => {
    const fringeCol = new THREE.Color(theme.fringe);
    const roughCol = new THREE.Color(theme.collarRough);
    const c = new THREE.Color();
    const ring = (inner: number, outerR: number, rings: number, lift: number) => {
      const geom = new THREE.RingGeometry(inner, outerR, RING_SEGMENTS, rings).rotateX(-Math.PI / 2);
      const p = geom.attributes.position as THREE.BufferAttribute;
      const colors = new Float32Array(p.count * 3);
      for (let i = 0; i < p.count; i++) {
        const lx = p.getX(i);
        const ly = -p.getZ(i);
        const t = Math.min(1, Math.max(0, (Math.hypot(lx, ly) - R) / (outer - R)));
        p.setXYZ(i, gx + lx, ground(gx + lx, gy + ly) + lift, -(gy + ly));
        c.copy(fringeCol).lerp(roughCol, Math.min(1, t * 1.6));
        colors.set([c.r, c.g, c.b], i * 3);
      }
      geom.setAttribute("color", new THREE.BufferAttribute(colors, 3));
      geom.computeVertexNormals();
      return geom;
    };
    return [ring(R - 0.05, outer, 24, 0), ring(R, R + hole.fringe_m, 6, PAINT_LIFT)];
  }, [ground, hole.fringe_m, R, outer, gx, gy, theme.fringe, theme.collarRough]);
  const [cx, cy] = hole.cup;
  const cupY = greenHeight(g, cx, cy);
  return (
    <group>
      <mesh geometry={collar} renderOrder={ORDER.base} receiveShadow>
        <meshStandardMaterial vertexColors roughness={1} />
      </mesh>
      <mesh geometry={fringe} renderOrder={ORDER.fringe} receiveShadow>
        <meshStandardMaterial vertexColors roughness={1} depthWrite={false} />
      </mesh>
      <mesh geometry={surface} renderOrder={ORDER.green} receiveShadow>
        <meshStandardMaterial map={tex} roughness={0.92} />
      </mesh>
      <mesh position={[cx, cupY + 0.0055, -cy]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[CUP_RADIUS, 40]} />
        <meshBasicMaterial color="#050505" />
      </mesh>
      <mesh position={[cx, cupY + 0.0057, -cy]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[CUP_RADIUS - 0.004, CUP_RADIUS, 40]} />
        <meshStandardMaterial color="#e9e9e4" />
      </mesh>
      <Flag x={cx} y={cupY} z={-cy} />
    </group>
  );
}

function TeeBox({ hole, color }: { hole: Hole; color: string }) {
  const [tx, ty] = hole.tee;
  const [ax, ay] = hole.route[1];
  const yaw = Math.atan2(ay - ty, ax - tx);
  return (
    <group position={[tx, PAINT_LIFT, -ty]} rotation={[0, yaw, 0]}>
      <mesh rotation={[-Math.PI / 2, 0, 0]} renderOrder={ORDER.tee} receiveShadow>
        <planeGeometry args={[hole.tee_radius_m * 1.6, hole.tee_radius_m * 1.2]} />
        <meshStandardMaterial color={color} roughness={0.95} depthWrite={false} />
      </mesh>
      {[1, -1].map((s) => (
        <mesh key={s} position={[1.4, 0.05, 2.1 * s]} castShadow>
          <sphereGeometry args={[0.07, 12, 10]} />
          <meshStandardMaterial color="#f2f2ee" roughness={0.4} />
        </mesh>
      ))}
    </group>
  );
}

export function CourseHole({ hole }: { hole: Hole }) {
  const theme = themeFor(hole);
  const colors = theme.ground;
  const rough = useMemo(() => {
    if (colors.roughMottle) {
      const t = mottleTexture(colors.roughMottle);
      t.repeat.set(1 / 40, 1 / 40); // one tile of patches per 40 m
      return t;
    }
    const t = stripeTexture(colors.rough[0], colors.rough[1], 2);
    t.repeat.set(1 / 12, 1 / 12); // UVs are world metres
    return t;
  }, [colors.rough, colors.roughMottle]);
  const fairwayTex = useMemo(() => {
    const t = stripeTexture(colors.fairway[0], colors.fairway[1], 2);
    t.repeat.set(1 / 16, 1 / 16);
    t.rotation = Math.PI / 2;
    return t;
  }, [colors.fairway]);
  const sandTex = useMemo(() => {
    const t = noiseTexture(colors.sand, 26);
    t.repeat.set(1 / 3, 1 / 3);
    return t;
  }, [colors.sand]);
  // Surfaces are draped on the same ground the physics uses (the green collar included).
  const ground = useMemo<HeightFn>(() => {
    const g = { green: hole.green, hole };
    return (x, y) => heightAt(g, x, y);
  }, [hole]);
  const bump = useMemo<Bump>(() => ({ center: hole.green.center, radius: collarOuter(hole) }), [hole]);
  const fairways = useMemo(
    () => hole.fairways.map((p) => drapedGeometry(p, ground, PAINT_LIFT, bump)),
    [hole, ground, bump],
  );
  const bunkers = useMemo(
    () => hole.bunkers.map((p) => drapedGeometry(p, ground, PAINT_LIFT, bump)),
    [hole, ground, bump],
  );
  const bunkerRims = useMemo(
    () => hole.bunkers.map((p) => drapedOutline(p, ground, PAINT_LIFT + 0.004, bump)),
    [hole, ground, bump],
  );
  const cx = (hole.tee[0] + hole.cup[0]) / 2;
  const cy = (hole.tee[1] + hole.cup[1]) / 2;
  const center = useMemo<[number, number]>(() => [cx, cy], [cx, cy]);
  const extent = useMemo(() => holeExtent(hole, center), [hole, center]);
  const roughGeom = useMemo(() => {
    // Flat rough everywhere except the disc the green and its collar fill exactly.
    const H = 1500;
    const s = new THREE.Shape([
      new THREE.Vector2(cx - H, cy - H),
      new THREE.Vector2(cx + H, cy - H),
      new THREE.Vector2(cx + H, cy + H),
      new THREE.Vector2(cx - H, cy + H),
    ]);
    const [gx, gy] = hole.green.center;
    const r = collarOuter(hole);
    s.holes.push(
      new THREE.Path(
        Array.from({ length: RING_SEGMENTS }, (_, k) => {
          const a = (k / RING_SEGMENTS) * (Math.PI * 2);
          return new THREE.Vector2(gx + r * Math.cos(a), gy + r * Math.sin(a));
        }),
      ),
    );
    return new THREE.ShapeGeometry(s).rotateX(-Math.PI / 2);
  }, [hole, cx, cy]);
  return (
    <group>
      <mesh geometry={roughGeom} renderOrder={ORDER.base} receiveShadow>
        <meshStandardMaterial map={rough} roughness={1} />
      </mesh>
      {fairways.map((g, i) => (
        <mesh key={i} geometry={g} renderOrder={ORDER.fairway} receiveShadow>
          <meshStandardMaterial map={fairwayTex} roughness={0.95} depthWrite={false} />
        </mesh>
      ))}
      {bunkers.map((g, i) => (
        <mesh key={i} geometry={g} renderOrder={ORDER.sand} receiveShadow>
          <meshStandardMaterial map={sandTex} roughness={1} depthWrite={false} />
        </mesh>
      ))}
      {bunkerRims.map((pts, i) => (
        <Line
          key={i}
          points={pts}
          color={colors.rim}
          lineWidth={1.5}
          depthWrite={false}
          renderOrder={ORDER.rim}
        />
      ))}
      <Water polys={hole.water} ground={ground} bump={bump} theme={theme.water} />
      <TeeBox hole={hole} color={colors.tee} />
      <Green hole={hole} ground={ground} theme={colors} />
      <Trees trees={hole.trees} center={center} extent={extent} theme={theme.trees} />
    </group>
  );
}
