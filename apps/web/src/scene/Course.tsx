import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import type { Scenario } from "@fly-golf/protocol";
import { greenHeight } from "../lib/coords";

export const BALL_RADIUS = 0.021335;
export const CUP_RADIUS = 0.054;

export function stripeTexture(dark: string, light: string, bands = 8): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = c.height = 512;
  const g = c.getContext("2d")!;
  const w = c.width / bands;
  for (let i = 0; i < bands; i++) {
    g.fillStyle = i % 2 ? dark : light;
    g.fillRect(i * w, 0, w, c.height);
  }
  // fine grain so the surface does not look like plastic
  const img = g.getImageData(0, 0, c.width, c.height);
  let seed = 11;
  for (let p = 0; p < img.data.length; p += 4) {
    seed = (seed * 16807) % 2147483647;
    const n = (seed / 2147483647 - 0.5) * 18;
    img.data[p] += n;
    img.data[p + 1] += n;
    img.data[p + 2] += n * 0.5;
  }
  g.putImageData(img, 0, 0);
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
}

function tilt(geom: THREE.BufferGeometry, scenario: Scenario, lift = 0) {
  const pos = geom.attributes.position as THREE.BufferAttribute;
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i);
    const z = pos.getZ(i);
    pos.setY(i, greenHeight(scenario.green, x, -z) + lift);
  }
  pos.needsUpdate = true;
  geom.computeVertexNormals();
  return geom;
}

export function Flag({ x, y, z }: { x: number; y: number; z: number }) {
  const cloth = useRef<THREE.Mesh>(null);
  const geom = useMemo(() => new THREE.PlaneGeometry(0.5, 0.32, 14, 4).translate(0.25, 0, 0), []);
  const base = useMemo(() => Float32Array.from(geom.attributes.position.array), [geom]);
  useFrame(({ clock }) => {
    const p = geom.attributes.position as THREE.BufferAttribute;
    const t = clock.elapsedTime;
    for (let i = 0; i < p.count; i++) {
      const bx = base[i * 3];
      p.setZ(i, Math.sin(t * 3.2 + bx * 9) * 0.035 * (bx / 0.5));
    }
    p.needsUpdate = true;
  });
  return (
    <group position={[x, y, z]}>
      <mesh position={[0, 1.065, 0]} castShadow>
        <cylinderGeometry args={[0.006, 0.006, 2.13, 10]} />
        <meshStandardMaterial color="#f4f1ea" roughness={0.4} />
      </mesh>
      <mesh ref={cloth} geometry={geom} position={[0.006, 1.95, 0]} castShadow>
        <meshStandardMaterial color="#ffc21a" roughness={0.7} side={THREE.DoubleSide} />
      </mesh>
    </group>
  );
}

function Trees() {
  const mesh = useRef<THREE.InstancedMesh>(null);
  const count = 70;
  useMemo(() => {
    requestAnimationFrame(() => {
      if (!mesh.current) return;
      const m = new THREE.Matrix4();
      let seed = 5;
      const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
      for (let i = 0; i < count; i++) {
        const a = (i / count) * Math.PI * 2 + rnd() * 0.08;
        const r = 38 + rnd() * 40;
        const s = 3 + rnd() * 5;
        m.compose(
          new THREE.Vector3(Math.cos(a) * r, s * 1.1, Math.sin(a) * r),
          new THREE.Quaternion(),
          new THREE.Vector3(s * 0.55, s * 2.2, s * 0.55),
        );
        mesh.current.setMatrixAt(i, m);
      }
      mesh.current.instanceMatrix.needsUpdate = true;
    });
  }, []);
  return (
    <instancedMesh ref={mesh} args={[undefined, undefined, count]} castShadow>
      <coneGeometry args={[1, 1, 7]} />
      <meshStandardMaterial color="#1f4a2a" roughness={0.9} flatShading />
    </instancedMesh>
  );
}

export function Course({ scenario }: { scenario: Scenario }) {
  const R = scenario.green.radius_m;
  const greenTex = useMemo(() => {
    const t = stripeTexture("#3e8b3a", "#4b9d44");
    t.repeat.set(R / 1.5, R / 1.5);
    return t;
  }, [R]);
  const roughTex = useMemo(() => {
    const t = stripeTexture("#2f6428", "#336c2b", 2);
    t.repeat.set(40, 40);
    return t;
  }, []);
  const green = useMemo(
    () => tilt(new THREE.CircleGeometry(R, 160).rotateX(-Math.PI / 2), scenario),
    [R, scenario],
  );
  const fringe = useMemo(
    () => tilt(new THREE.RingGeometry(R, R + 1.3, 160, 2).rotateX(-Math.PI / 2), scenario, -0.004),
    [R, scenario],
  );
  const [cx, cy] = scenario.cup;
  const cupY = greenHeight(scenario.green, cx, cy);

  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.06, 0]} receiveShadow>
        <planeGeometry args={[400, 400]} />
        <meshStandardMaterial map={roughTex} roughness={1} />
      </mesh>
      <mesh geometry={fringe} receiveShadow>
        <meshStandardMaterial color="#2f7a31" roughness={1} />
      </mesh>
      <mesh geometry={green} receiveShadow>
        <meshStandardMaterial map={greenTex} roughness={0.92} />
      </mesh>
      {/* cup */}
      <mesh position={[cx, cupY + 0.0015, -cy]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[CUP_RADIUS, 40]} />
        <meshBasicMaterial color="#050505" />
      </mesh>
      <mesh position={[cx, cupY + 0.0017, -cy]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[CUP_RADIUS - 0.004, CUP_RADIUS, 40]} />
        <meshStandardMaterial color="#e9e9e4" />
      </mesh>
      <Flag x={cx} y={cupY} z={-cy} />
      <Trees />
    </group>
  );
}
