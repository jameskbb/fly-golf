/**
 * One hole of the front nine, rendered from the backend's geometry (the same polygons the
 * physics uses): rough everywhere, fairway strips, bunkers, animated water, a tilted green
 * with a collar, the tee box, and the tree lines that mark out of bounds.
 */
import { useLayoutEffect, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Line } from "@react-three/drei";
import * as THREE from "three";
import type { CourseHole as Hole } from "@fly-golf/protocol";
import { greenHeight } from "../lib/coords";
import { drapedGeometry, drapedOutline, type Bump, type HeightFn } from "../lib/drape";
import { collarOuter, heightAt } from "../lib/terrain";
import { CUP_RADIUS, Flag, stripeTexture } from "./Course";

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

function Water({ polys, ground, bump }: { polys: number[][][]; ground: HeightFn; bump: Bump }) {
  const normals = useMemo(() => {
    const t = waterNormals();
    t.repeat.set(1 / 9, 1 / 9);
    return t;
  }, []);
  const geoms = useMemo(
    () => polys.map((p) => drapedGeometry(p, ground, PAINT_LIFT, bump)),
    [polys, ground, bump],
  );
  const banks = useMemo(
    () => polys.map((p) => drapedOutline(p, ground, PAINT_LIFT + 0.006, bump)),
    [polys, ground, bump],
  );
  useFrame((_, dt) => {
    normals.offset.x += dt * 0.012;
    normals.offset.y += dt * 0.007;
  });
  return (
    <group>
      {geoms.map((g, i) => (
        <mesh key={i} geometry={g} renderOrder={ORDER.water} receiveShadow>
          <meshStandardMaterial
            color="#2b6f86"
            roughness={0.12}
            metalness={0.35}
            normalMap={normals}
            normalScale={new THREE.Vector2(0.55, 0.55)}
            depthWrite={false}
          />
        </mesh>
      ))}
      {banks.map((pts, i) => (
        <Line
          key={i}
          points={pts}
          color="#cfe7df"
          lineWidth={2.2}
          transparent
          opacity={0.8}
          depthWrite={false}
        />
      ))}
    </group>
  );
}

function Trees({ trees, center }: { trees: number[][]; center: [number, number] }) {
  // Hole-edge trees (kind 0 = conifer, 1 = round) plus a far backdrop ring for the horizon.
  const all = useMemo(() => {
    const out = trees.map((t) => [...t]);
    let seed = 29;
    const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    for (let i = 0; i < 150; i++) {
      const a = (i / 150) * Math.PI * 2 + rnd() * 0.05;
      const r = 330 + rnd() * 160;
      out.push([
        center[0] + Math.cos(a) * r,
        center[1] + Math.sin(a) * r,
        14 + rnd() * 16,
        rnd() < 0.5 ? 0 : 1,
      ]);
    }
    return out;
  }, [trees, center]);
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
    conifers.forEach(([x, y, h], i) => {
      m.compose(
        new THREE.Vector3(x, h * 0.25 + h * 0.375, -y),
        q,
        new THREE.Vector3(h * 0.24, h * 0.75, h * 0.24),
      );
      cone.current!.setMatrixAt(i, m);
      cone.current!.setColorAt(i, col.setHSL(0.36 + rnd() * 0.04, 0.42, 0.17 + rnd() * 0.07));
    });
    rounds.forEach(([x, y, h], i) => {
      m.compose(new THREE.Vector3(x, h * 0.62, -y), q, new THREE.Vector3(h * 0.3, h * 0.28, h * 0.3));
      ball.current!.setMatrixAt(i, m);
      ball.current!.setColorAt(i, col.setHSL(0.27 + rnd() * 0.06, 0.45, 0.22 + rnd() * 0.08));
    });
    all.forEach(([x, y, h], i) => {
      m.compose(new THREE.Vector3(x, h * 0.18, -y), q, new THREE.Vector3(0.45, h * 0.36, 0.45));
      trunk.current!.setMatrixAt(i, m);
    });
    for (const r of [cone, ball, trunk]) {
      r.current!.instanceMatrix.needsUpdate = true;
      if (r.current!.instanceColor) r.current!.instanceColor.needsUpdate = true;
    }
  }, [all, conifers, rounds]);

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
        <meshStandardMaterial color="#4a3423" roughness={1} />
      </instancedMesh>
    </group>
  );
}

function Green({ hole, ground }: { hole: Hole; ground: HeightFn }) {
  const g = hole.green;
  const [gx, gy] = g.center;
  const R = g.radius_m;
  const outer = collarOuter(hole); // same collar as the physics (course.py HoleSpec.height)
  const tex = useMemo(() => {
    const t = stripeTexture("#3e8b3a", "#4b9d44");
    t.repeat.set(R / 1.5, R / 1.5);
    return t;
  }, [R]);
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
    const fringeCol = new THREE.Color("#358a37");
    const roughCol = new THREE.Color("#2f6428");
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
  }, [ground, hole.fringe_m, R, outer, gx, gy]);
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

function TeeBox({ hole }: { hole: Hole }) {
  const [tx, ty] = hole.tee;
  const [ax, ay] = hole.route[1];
  const yaw = Math.atan2(ay - ty, ax - tx);
  return (
    <group position={[tx, PAINT_LIFT, -ty]} rotation={[0, yaw, 0]}>
      <mesh rotation={[-Math.PI / 2, 0, 0]} renderOrder={ORDER.tee} receiveShadow>
        <planeGeometry args={[hole.tee_radius_m * 1.6, hole.tee_radius_m * 1.2]} />
        <meshStandardMaterial color="#4fa447" roughness={0.95} depthWrite={false} />
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
  const rough = useMemo(() => {
    const t = stripeTexture("#2f6428", "#336c2b", 2);
    t.repeat.set(1 / 12, 1 / 12); // UVs are world metres
    return t;
  }, []);
  const fairwayTex = useMemo(() => {
    const t = stripeTexture("#4a9a3f", "#56a94a", 2);
    t.repeat.set(1 / 16, 1 / 16);
    t.rotation = Math.PI / 2;
    return t;
  }, []);
  const sandTex = useMemo(() => {
    const t = noiseTexture([222, 205, 158], 26);
    t.repeat.set(1 / 3, 1 / 3);
    return t;
  }, []);
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
          color="#8f7a4c"
          lineWidth={1.5}
          depthWrite={false}
          renderOrder={ORDER.rim}
        />
      ))}
      <Water polys={hole.water} ground={ground} bump={bump} />
      <TeeBox hole={hole} />
      <Green hole={hole} ground={ground} />
      <Trees trees={hole.trees} center={[cx, cy]} />
    </group>
  );
}
