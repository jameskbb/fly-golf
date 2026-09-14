/**
 * Procedural, stylized Drosophila golfer built from primitives.
 *
 * Local frame: the fly faces +x (toward the ball), +y is up, and the target
 * line runs along +z. The putter hangs from the grip and swings as a pendulum
 * about the local x axis (+angle = backswing toward -z). Not to scale: a real
 * fruit fly is ~3 mm long; this one is ~25 cm so spectators can see it.
 *
 * `persona` dresses the same rig for each brain (looks.tsx). The default, `fly`, has no
 * overrides: every material below is the baseline fly's own.
 */
import {
  useContext,
  useLayoutEffect,
  useMemo,
  useRef,
  type MutableRefObject,
  type ReactElement,
} from "react";
import * as THREE from "three";
import { LOOKS, LookContext, type Part, type PersonaId } from "./looks";

export type ClubStyle = "putter" | "iron" | "wood";

export interface FlyRig {
  root: THREE.Group;
  body: THREE.Group;
  thorax: THREE.Group;
  head: THREE.Group;
  club: THREE.Group;
  heads: Record<ClubStyle, THREE.Group>;
  wingL: THREE.Group;
  wingR: THREE.Group;
  antennaL: THREE.Group;
  antennaR: THREE.Group;
  brain: THREE.Points;
  windKey: THREE.Group | null; // the tin fly's wind-up key
}

/** Club kind (backend) -> which head the fly holds. */
export function clubStyle(kind: string | undefined | null): ClubStyle {
  if (!kind || kind === "putter") return "putter";
  return kind === "wood" || kind === "driver" || kind === "hybrid" ? "wood" : "iron";
}

/** Metres from the fly origin to the ball (local +x) for each club style. */
export const BALL_OFFSETS: Record<ClubStyle, number> = { putter: 0.14, iron: 0.172, wood: 0.182 };

type V3 = [number, number, number];

const BODY = "#c48a42";
const BODY_DARK = "#7a4a1c";
const LEG = "#5b3a1a";
const EYE = "#b3131c";
const STRIPE = "#3b2410";
const WING = "#e4eef6";

export const BALL_OFFSET = BALL_OFFSETS.putter;
export const GRIP: V3 = [0.1, 0.13, 0];
const HOSEL: V3 = [0.04, -0.108, -0.028];
const HEAD_CENTER: V3 = [0.04, -0.121, -0.028];
// Full clubs: the head reaches the ball further out (the fly stands further away).
const IRON_HOSEL: V3 = [0.07, -0.112, -0.004];
const IRON_HEAD: V3 = [0.074, -0.121, -0.004];
const WOOD_HOSEL: V3 = [0.078, -0.108, -0.004];
const WOOD_HEAD: V3 = [0.084, -0.117, -0.004];

/** The persona's material for `part`, or the baseline material given as the child. */
function Mat({ part, children }: { part?: Part; children: ReactElement }) {
  const look = useContext(LookContext);
  return (part && look?.materials[part]) || children;
}

function Segment({
  a,
  b,
  r = 0.005,
  color = LEG,
  part,
}: {
  a: V3;
  b: V3;
  r?: number;
  color?: string;
  part?: Part;
}) {
  const { position, quaternion, length } = useMemo(() => {
    const va = new THREE.Vector3(...a);
    const vb = new THREE.Vector3(...b);
    const dir = vb.clone().sub(va);
    const len = dir.length();
    const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.normalize());
    return { position: va.add(vb).multiplyScalar(0.5), quaternion: q, length: len };
  }, [a, b]);
  return (
    <mesh position={position} quaternion={quaternion} castShadow>
      <cylinderGeometry args={[r * 0.75, r, length, 7]} />
      <Mat part={part}>
        <meshStandardMaterial color={color} roughness={0.55} />
      </Mat>
    </mesh>
  );
}

interface LegParts {
  upper: Part;
  lower: Part;
  knee: Part;
  foot: Part;
}
const STAND: LegParts = { upper: "thigh", lower: "shin", knee: "knee", foot: "foot" };
const ARM: LegParts = { upper: "arm", lower: "arm", knee: "armKnee", foot: "hand" };

function Leg({
  hip,
  knee,
  foot,
  r = 0.0055,
  parts = STAND,
  thigh = 1,
  footScale = 1,
}: {
  hip: V3;
  knee: V3;
  foot: V3;
  r?: number;
  parts?: LegParts;
  thigh?: number;
  footScale?: number;
}) {
  return (
    <group>
      <Segment a={hip} b={knee} r={r * thigh} part={parts.upper} />
      <Segment a={knee} b={foot} r={r * 0.8} part={parts.lower} />
      <mesh position={knee} castShadow>
        <sphereGeometry args={[r * 1.1 * Math.max(1, thigh * 0.86), 8, 6]} />
        <Mat part={parts.knee}>
          <meshStandardMaterial color={LEG} roughness={0.6} />
        </Mat>
      </mesh>
      <mesh position={foot}>
        <sphereGeometry args={[r * 0.9 * footScale, 8, 6]} />
        <Mat part={parts.foot}>
          <meshStandardMaterial color={STRIPE} />
        </Mat>
      </mesh>
    </group>
  );
}

function Wing({ side, wingRef }: { side: 1 | -1; wingRef: MutableRefObject<THREE.Group | null> }) {
  return (
    <group position={[-0.02, 0.034, 0.02 * side]} rotation={[0, 0.42 * side, 0]}>
      <group ref={wingRef}>
        <mesh position={[-0.055, 0, 0]} rotation={[-Math.PI / 2, 0, 0]} scale={[0.062, 0.021, 1]}>
          <circleGeometry args={[1, 36]} />
          <Mat part="wing">
            <meshPhysicalMaterial
              color={WING}
              transparent
              opacity={0.38}
              roughness={0.15}
              iridescence={0.8}
              iridescenceIOR={1.3}
              side={THREE.DoubleSide}
              depthWrite={false}
            />
          </Mat>
        </mesh>
        {/* a couple of veins so the wing reads as a wing */}
        <Segment
          a={[0, 0.0005, 0]}
          b={[-0.11, 0.0005, 0.004 * side]}
          r={0.0009}
          color="#9aa7b0"
          part="vein"
        />
        <Segment a={[0, 0.0005, 0]} b={[-0.1, 0.0005, -0.01 * side]} r={0.0008} color="#9aa7b0" part="vein" />
      </group>
    </group>
  );
}

function Antenna({ side, antRef }: { side: 1 | -1; antRef: MutableRefObject<THREE.Group | null> }) {
  return (
    <group ref={antRef} position={[0.026, 0.016, 0.009 * side]}>
      <Segment a={[0, 0, 0]} b={[0.008, 0.012, 0.004 * side]} r={0.0028} color={BODY_DARK} part="bodyDark" />
      <mesh position={[0.009, 0.014, 0.0045 * side]}>
        <sphereGeometry args={[0.0045, 10, 8]} />
        <Mat part="body">
          <meshStandardMaterial color={BODY} roughness={0.5} />
        </Mat>
      </mesh>
      {/* feathery arista */}
      <Segment
        a={[0.01, 0.016, 0.005 * side]}
        b={[0.03, 0.03, 0.012 * side]}
        r={0.0008}
        color="#4a3016"
        part="arista"
      />
    </group>
  );
}

function BrainSparks({ pointsRef }: { pointsRef: MutableRefObject<THREE.Points | null> }) {
  const geom = useMemo(() => {
    const g = new THREE.BufferGeometry();
    const n = 160;
    const pos = new Float32Array(n * 3);
    let seed = 7;
    const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647) * 2 - 1;
    for (let i = 0; i < n; i++) {
      let x = rnd(),
        y = rnd(),
        z = rnd();
      const l = Math.hypot(x, y, z) || 1;
      const r = 0.012 + 0.018 * Math.abs(rnd());
      x = (x / l) * r;
      y = (y / l) * r * 0.7;
      z = (z / l) * r;
      pos.set([x, y, z], i * 3);
    }
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    return g;
  }, []);
  return (
    <points ref={pointsRef} geometry={geom} position={[0.005, 0.06, 0]} visible={false}>
      <pointsMaterial color="#7cf5c4" size={0.0035} transparent opacity={0.9} depthWrite={false} />
    </points>
  );
}

export function Fly({
  rigRef,
  persona = "fly",
}: {
  rigRef: MutableRefObject<FlyRig | null>;
  persona?: PersonaId;
}) {
  const look = LOOKS[persona];
  const root = useRef<THREE.Group>(null);
  const body = useRef<THREE.Group>(null);
  const thorax = useRef<THREE.Group>(null);
  const head = useRef<THREE.Group>(null);
  const club = useRef<THREE.Group>(null);
  const putterHead = useRef<THREE.Group>(null);
  const ironHead = useRef<THREE.Group>(null);
  const woodHead = useRef<THREE.Group>(null);
  const wingL = useRef<THREE.Group | null>(null);
  const wingR = useRef<THREE.Group | null>(null);
  const antennaL = useRef<THREE.Group | null>(null);
  const antennaR = useRef<THREE.Group | null>(null);
  const brain = useRef<THREE.Points | null>(null);
  const windKey = useRef<THREE.Group | null>(null);

  useLayoutEffect(() => {
    rigRef.current = {
      root: root.current!,
      body: body.current!,
      thorax: thorax.current!,
      head: head.current!,
      club: club.current!,
      heads: { putter: putterHead.current!, iron: ironHead.current!, wood: woodHead.current! },
      wingL: wingL.current!,
      wingR: wingR.current!,
      antennaL: antennaL.current!,
      antennaR: antennaR.current!,
      brain: brain.current!,
      windKey: windKey.current,
    };
    return () => {
      rigRef.current = null;
    };
  }, [rigRef]);

  const stripes = [-0.012, -0.03, -0.047];

  return (
    <LookContext.Provider value={look}>
      <group ref={root}>
        <group ref={body}>
          {/* mid + hind legs stand on the green */}
          {([1, -1] as const).map((s) => (
            <group key={s}>
              <Leg
                hip={[-0.03, 0.1, 0.022 * s]}
                knee={[-0.062, 0.128, 0.08 * s]}
                foot={[-0.085, 0.0, 0.1 * s]}
                thigh={look.thigh}
                footScale={look.foot}
              />
              <Leg
                hip={[0.0, 0.103, 0.026 * s]}
                knee={[0.012, 0.122, 0.092 * s]}
                foot={[0.032, 0.0, 0.112 * s]}
                thigh={look.thigh}
                footScale={look.foot}
              />
              {/* front legs grip the putter */}
              <Leg
                hip={[0.03, 0.128, 0.022 * s]}
                knee={[0.07, 0.112, 0.045 * s]}
                foot={[GRIP[0], GRIP[1], 0.008 * s]}
                r={0.005}
                parts={ARM}
              />
            </group>
          ))}
          {look.grip}

          {/* thorax, reared up so the fly can hold a club */}
          <group ref={thorax} position={[0, 0.12, 0]} rotation={[0, 0, 0.55]}>
            <mesh scale={[0.05, 0.042, 0.043]} castShadow>
              <sphereGeometry args={[1, 28, 18]} />
              <Mat part="body">
                <meshStandardMaterial color={BODY} roughness={0.42} />
              </Mat>
            </mesh>
            {/* scutellum */}
            <mesh position={[-0.03, 0.026, 0]} scale={[0.018, 0.01, 0.02]}>
              <sphereGeometry args={[1, 14, 10]} />
              <Mat part="bodyDark">
                <meshStandardMaterial color={BODY_DARK} roughness={0.5} />
              </Mat>
            </mesh>
            <Wing side={1} wingRef={wingL} />
            <Wing side={-1} wingRef={wingR} />
            {look.thorax?.({ keyRef: windKey })}

            {/* abdomen with the classic dark tergite bands */}
            <group position={[-0.07, -0.018, 0]} rotation={[0, 0, -0.35]}>
              <mesh scale={[0.066, 0.046, 0.047]} castShadow>
                <sphereGeometry args={[1, 28, 18]} />
                <Mat part="body">
                  <meshStandardMaterial color={BODY} roughness={0.45} />
                </Mat>
              </mesh>
              {stripes.map((x) => {
                const r = 0.047 * Math.sqrt(Math.max(0, 1 - (x / 0.066) ** 2)) + 0.0012;
                return (
                  <mesh
                    key={x}
                    position={[x, 0, 0]}
                    rotation={[0, 0, Math.PI / 2]}
                    scale={[r, 0.007, r * 0.98]}
                  >
                    <cylinderGeometry args={[1, 1, 1, 28, 1, true]} />
                    <Mat part="stripe">
                      <meshStandardMaterial color={STRIPE} roughness={0.6} side={THREE.DoubleSide} />
                    </Mat>
                  </mesh>
                );
              })}
              {look.abdomen}
            </group>

            {/* head with big red compound eyes */}
            <group ref={head} position={[0.062, 0.028, 0]}>
              <mesh scale={[0.028, 0.03, 0.034]} castShadow>
                <sphereGeometry args={[1, 24, 16]} />
                <Mat part="body">
                  <meshStandardMaterial color={BODY} roughness={0.45} />
                </Mat>
              </mesh>
              {([1, -1] as const).map((s) => (
                <mesh key={s} position={[0.006, 0.003, 0.022 * s]} scale={[0.022, 0.026, 0.015]} castShadow>
                  <sphereGeometry args={[1, 24, 16]} />
                  <Mat part="eye">
                    <meshPhysicalMaterial
                      color={EYE}
                      roughness={0.28}
                      clearcoat={0.6}
                      clearcoatRoughness={0.3}
                    />
                  </Mat>
                </mesh>
              ))}
              <Antenna side={1} antRef={antennaL} />
              <Antenna side={-1} antRef={antennaR} />
              {/* proboscis */}
              <Segment
                a={[0.012, -0.02, 0]}
                b={[0.02, -0.036, 0]}
                r={0.0035}
                color={BODY_DARK}
                part="bodyDark"
              />
              {look.head}
              <BrainSparks pointsRef={brain} />
            </group>
          </group>

          {/* the club: a pendulum about the grip; one of three heads is shown */}
          <group ref={club} position={GRIP}>
            <mesh position={[0, 0.012, 0]}>
              <cylinderGeometry args={[0.0048, 0.0042, 0.04, 10]} />
              <meshStandardMaterial color="#1b1f22" roughness={0.8} />
            </mesh>
            <group ref={putterHead}>
              <Segment a={[0, 0.02, 0]} b={HOSEL} r={0.0026} color="#d7dde2" />
              <mesh position={HEAD_CENTER} castShadow>
                <boxGeometry args={[0.05, 0.016, 0.012]} />
                <meshStandardMaterial color="#b8c0c7" metalness={0.85} roughness={0.25} />
              </mesh>
            </group>
            <group ref={ironHead} visible={false}>
              <Segment a={[0, 0.02, 0]} b={IRON_HOSEL} r={0.0022} color="#dfe4e8" />
              <mesh position={IRON_HEAD} rotation={[0.35, 0, 0]} castShadow>
                <boxGeometry args={[0.03, 0.02, 0.005]} />
                <meshStandardMaterial color="#c9d0d6" metalness={0.9} roughness={0.2} />
              </mesh>
            </group>
            <group ref={woodHead} visible={false}>
              <Segment a={[0, 0.02, 0]} b={WOOD_HOSEL} r={0.0024} color="#2a2f35" />
              <mesh position={WOOD_HEAD} scale={[0.022, 0.012, 0.018]} castShadow>
                <sphereGeometry args={[1, 20, 14]} />
                <meshPhysicalMaterial color="#15181c" metalness={0.4} roughness={0.25} clearcoat={0.8} />
              </mesh>
            </group>
          </group>
        </group>
      </group>
    </LookContext.Provider>
  );
}
