/**
 * The three fly personas, one per brain.
 *
 * - `fly`: the baseline Drosophila (MaleCNS, untrained). No overrides at all, so it renders
 *   exactly the model in Fly.tsx.
 * - `golfer`: the same fly anatomy (it is the same connectome) dressed as an avid club golfer,
 *   because its readout has practised thousands of shots.
 * - `windup`: a clockwork tin toy. The mock controller has no neurons and runs hand-written
 *   rules, so its body is a machine that does what it was wound up to do.
 *
 * Every persona shares Fly.tsx's rig (joints, club grip, wings, antennae), so the swing,
 * the bag and the reactions animate identically; a look only swaps materials and adds props.
 */
import { createContext, type ReactElement, type ReactNode, type RefObject } from "react";
import * as THREE from "three";

export type PersonaId = "fly" | "golfer" | "windup";

/** Surfaces a look may repaint. Unlisted parts keep the baseline fly's material. */
export type Part =
  | "body"
  | "bodyDark"
  | "stripe"
  | "eye"
  | "wing"
  | "vein"
  | "arista"
  | "thigh" // standing legs, upper segment
  | "shin" // standing legs, lower segment
  | "knee"
  | "foot"
  | "arm" // front legs (they hold the club)
  | "armKnee"
  | "hand";

export interface LookSlots {
  /** Attached to the wind-up key so the rig can turn it (only the tin fly has one). */
  keyRef: RefObject<THREE.Group | null>;
}

type V3 = [number, number, number];

export interface Look {
  materials: Partial<Record<Part, ReactElement>>;
  /** Headshot framing, in fly space: each persona is framed on what makes it that character. */
  portrait: { camera: V3; target: V3; fov: number; headYaw: number };
  thigh: number; // radius multiplier for the standing legs' upper segment (plus-fours)
  foot: number; // radius multiplier for the standing feet (shoes)
  head?: ReactNode; // head-local props
  thorax?: (slots: LookSlots) => ReactNode; // thorax-local props
  abdomen?: ReactNode; // abdomen-local props
  grip?: ReactNode; // body-local props at the club grip
  bag: { body: string; rim: string; band: string };
}

export const LookContext = createContext<Look | null>(null);

// ---------------------------------------------------------------- procedural cloth

const textures = new Map<string, THREE.Texture>();

/** A tiling canvas texture, drawn once per page. */
function cloth(
  key: string,
  size: number,
  repeat: [number, number],
  draw: (g: CanvasRenderingContext2D) => void,
) {
  const k = `${key}:${repeat.join("x")}`;
  let t = textures.get(k);
  if (!t) {
    const c = document.createElement("canvas");
    c.width = c.height = size;
    draw(c.getContext("2d")!);
    t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(...repeat);
    t.anisotropy = 4;
    textures.set(k, t);
  }
  return t;
}

const ARGYLE = { ground: "#3b2160", diamond: "#9b6ddc", deep: "#24123d", line: "#e6c35c" };

function drawArgyle(g: CanvasRenderingContext2D) {
  const s = 128;
  g.fillStyle = ARGYLE.ground;
  g.fillRect(0, 0, s, s);
  const diamond = (cx: number, cy: number, fill: string) => {
    g.fillStyle = fill;
    g.beginPath();
    g.moveTo(cx, cy - s / 2);
    g.lineTo(cx + s / 4, cy);
    g.lineTo(cx, cy + s / 2);
    g.lineTo(cx - s / 4, cy);
    g.closePath();
    g.fill();
  };
  diamond(s / 4, s / 2, ARGYLE.diamond);
  diamond((3 * s) / 4, s / 2, ARGYLE.deep);
  diamond((3 * s) / 4, -s / 2, ARGYLE.diamond);
  diamond((3 * s) / 4, (3 * s) / 2, ARGYLE.diamond);
  diamond(s / 4, -s / 2, ARGYLE.deep);
  diamond(s / 4, (3 * s) / 2, ARGYLE.deep);
  // the thin over-check lines
  g.strokeStyle = ARGYLE.line;
  g.lineWidth = 2;
  g.setLineDash([6, 4]);
  for (const [x0, y0, x1, y1] of [
    [0, 0, s / 2, s],
    [s / 2, 0, s, s],
    [s / 2, 0, 0, s],
    [s, 0, s / 2, s],
  ]) {
    g.beginPath();
    g.moveTo(x0, y0);
    g.lineTo(x1, y1);
    g.stroke();
  }
}

function drawTartan(g: CanvasRenderingContext2D) {
  const s = 64;
  // a light dress tartan, so the cap reads against dark tiles and dark trees alike
  g.fillStyle = "#ece2c8";
  g.fillRect(0, 0, s, s);
  const band = (pos: number, w: number, color: string, alpha: number) => {
    g.globalAlpha = alpha;
    g.fillStyle = color;
    g.fillRect(pos, 0, w, s);
    g.fillRect(0, pos, s, w);
  };
  band(4, 14, "#6d3fb0", 0.55);
  band(34, 10, "#2f6b45", 0.45);
  band(24, 3, "#3b2160", 0.9);
  band(52, 2, "#c0392b", 0.8);
  g.globalAlpha = 1;
}

function drawTweed(g: CanvasRenderingContext2D) {
  const s = 32;
  g.fillStyle = "#b09366";
  g.fillRect(0, 0, s, s);
  let seed = 11;
  const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  for (let i = 0; i < 220; i++) {
    g.fillStyle = rnd() > 0.5 ? "#8a6f47" : "#d2bb8e";
    g.fillRect(Math.floor(rnd() * s), Math.floor(rnd() * s), 1, 2);
  }
  g.fillStyle = "rgba(90, 60, 110, 0.55)"; // a faint overcheck in the member's purple
  g.fillRect(0, 15, s, 1);
  g.fillRect(15, 0, 1, s);
}

// ---------------------------------------------------------------- golfer

const argyle = (repeat: [number, number]) => cloth("argyle", 128, repeat, drawArgyle);
const tartan = () => cloth("tartan", 64, [3, 3], drawTartan);
const tweed = () => cloth("tweed", 32, [2, 3], drawTweed);

/** A cloth material; the texture is drawn on first render, never at import (tests run in node). */
function Cloth({ kind }: { kind: "tweed" | "sock" }) {
  return <meshStandardMaterial map={kind === "tweed" ? tweed() : argyle([1, 3])} roughness={0.93} />;
}

function Tam() {
  return (
    <group position={[-0.004, 0.027, 0]} rotation={[0, 0, -0.18]}>
      {/* the soft crown, pulled over to one side the way golfers wear it */}
      <mesh position={[-0.002, 0.008, 0.003]} scale={[0.037, 0.012, 0.039]} castShadow>
        <sphereGeometry args={[1, 28, 16]} />
        <meshStandardMaterial map={tartan()} roughness={0.95} />
      </mesh>
      {/* headband */}
      <mesh rotation={[Math.PI / 2, 0, 0]} scale={[1, 1.12, 1]}>
        <torusGeometry args={[0.025, 0.0038, 10, 32]} />
        <meshStandardMaterial color="#2a1745" roughness={0.9} />
      </mesh>
      {/* pom-pom */}
      <mesh position={[-0.004, 0.022, 0.004]} castShadow>
        <sphereGeometry args={[0.0085, 14, 10]} />
        <meshStandardMaterial color="#7a45c4" roughness={1} />
      </mesh>
    </group>
  );
}

function Vest() {
  return (
    <group>
      {/* argyle sweater vest over the thorax */}
      <mesh scale={[0.0535, 0.0455, 0.0465]} castShadow>
        <sphereGeometry args={[1, 32, 20]} />
        <meshStandardMaterial map={argyle([4, 2])} roughness={0.92} />
      </mesh>
      {/* white polo collar where the head meets the vest: a ring around the thorax-to-head
          axis (0.42 rad up from thorax +x), wide enough to clear both surfaces */}
      <group position={[0.044, 0.02, 0]} rotation={[0, Math.PI / 2, 0.42, "ZYX"]}>
        <mesh>
          <torusGeometry args={[0.026, 0.0052, 10, 32]} />
          <meshStandardMaterial color="#f6f4ee" roughness={0.7} />
        </mesh>
        {/* the two collar points, folded down over the vest front */}
        {([1, -1] as const).map((s) => (
          <mesh key={s} position={[0.011 * s, -0.024, 0.004]} rotation={[0.5, 0, 0.45 * s]}>
            <boxGeometry args={[0.014, 0.012, 0.0025]} />
            <meshStandardMaterial color="#f6f4ee" roughness={0.7} />
          </mesh>
        ))}
      </group>
    </group>
  );
}

function Glove() {
  // one white glove on the lead hand, wrapped along the grip (not a ball), with a purple tab
  return (
    <group position={[0.1, 0.134, 0.007]}>
      <mesh castShadow>
        <capsuleGeometry args={[0.0058, 0.014, 4, 10]} />
        <meshStandardMaterial color="#fbfaf6" roughness={0.6} />
      </mesh>
      <mesh position={[-0.003, -0.004, 0.0056]} rotation={[0, 0.3, 0]}>
        <boxGeometry args={[0.0075, 0.006, 0.0016]} />
        <meshStandardMaterial color="#6d3fb0" roughness={0.6} />
      </mesh>
    </group>
  );
}

// ---------------------------------------------------------------- wind-up

// The scene has no environment map, so fully metallic surfaces would render black: keep
// metalness moderate and let the direct lights make the highlights.
const CHROME = <meshStandardMaterial color="#dfe5ea" metalness={0.45} roughness={0.25} />;
const BRASS = <meshStandardMaterial color="#e0b04a" metalness={0.45} roughness={0.3} />;

function WindKey({ keyRef }: { keyRef: RefObject<THREE.Group | null> }) {
  // sticks out of the top of the thorax (thorax-local +y points up and back)
  return (
    <group position={[-0.006, 0.04, 0]}>
      <group ref={keyRef}>
        <mesh position={[0, 0.011, 0]}>
          <cylinderGeometry args={[0.0028, 0.0028, 0.022, 10]} />
          {BRASS}
        </mesh>
        <mesh position={[0, 0.021, 0]}>
          <boxGeometry args={[0.009, 0.004, 0.004]} />
          {BRASS}
        </mesh>
        {([1, -1] as const).map((s) => (
          <mesh key={s} position={[0.011 * s, 0.028, 0]} castShadow>
            <torusGeometry args={[0.0085, 0.0026, 10, 24]} />
            {BRASS}
          </mesh>
        ))}
      </group>
    </group>
  );
}

function TinSeam() {
  // the pressed seam where two tin halves were crimped together, with rivets
  const rivets = [0.5, 1.1, 1.7, 2.3, 2.9].map((a) => [0, Math.cos(a) * 0.0435, Math.sin(a) * 0.0445]);
  return (
    <group>
      <mesh rotation={[0, Math.PI / 2, 0]} scale={[1.02, 0.975, 1]}>
        <torusGeometry args={[0.0438, 0.0016, 8, 40]} />
        {CHROME}
      </mesh>
      {rivets.map((p, i) => (
        <mesh key={i} position={p as [number, number, number]}>
          <sphereGeometry args={[0.0026, 8, 6]} />
          {CHROME}
        </mesh>
      ))}
      {rivets.map((p, i) => (
        <mesh key={`b${i}`} position={[p[0], p[1], -p[2]]}>
          <sphereGeometry args={[0.0026, 8, 6]} />
          {CHROME}
        </mesh>
      ))}
    </group>
  );
}

function LampBezels() {
  // chrome rims around the lamp eyes
  return (
    <>
      {([1, -1] as const).map((s) => (
        <mesh key={s} position={[0.006, 0.003, 0.0305 * s]} scale={[1, 1.18, 1]}>
          <torusGeometry args={[0.0205, 0.0026, 10, 32]} />
          {CHROME}
        </mesh>
      ))}
    </>
  );
}

function TinTail() {
  // a stamped tin tail cap at the tip of the abdomen
  return (
    <mesh position={[-0.064, 0, 0]} rotation={[0, 0, Math.PI / 2]}>
      <cylinderGeometry args={[0.012, 0.018, 0.01, 18]} />
      {CHROME}
    </mesh>
  );
}

// ---------------------------------------------------------------- the three looks

export const LOOKS: Record<PersonaId, Look> = {
  fly: {
    // the eyes are the character: face-on and a touch above
    portrait: { camera: [0.28, 0.235, 0.12], target: [0.026, 0.19, 0.002], fov: 25, headYaw: -0.22 },
    materials: {},
    thigh: 1,
    foot: 1,
    bag: { body: "#b2261e", rim: "#1c1c1c", band: "#f4f1ea" },
  },
  golfer: {
    // higher and wider, so the tam and the argyle vest both fill the tile
    portrait: { camera: [0.25, 0.265, 0.15], target: [0.018, 0.178, 0.002], fov: 30, headYaw: -0.22 },
    materials: {
      thigh: <Cloth kind="tweed" />,
      shin: <Cloth kind="sock" />,
      knee: <Cloth kind="tweed" />,
      foot: <meshStandardMaterial color="#f5f2ea" roughness={0.35} />,
    },
    thigh: 1.55,
    foot: 2,
    head: <Tam />,
    thorax: () => <Vest />,
    grip: <Glove />,
    bag: { body: "#5e3a1c", rim: "#e6c35c", band: "#6d3fb0" },
  },
  windup: {
    // in profile, so the key in its back is silhouetted beside a lamp eye
    portrait: { camera: [0.03, 0.2, 0.3], target: [0.0, 0.172, 0.0], fov: 31, headYaw: 0 },
    materials: {
      body: <meshPhysicalMaterial color="#e2542a" metalness={0.55} roughness={0.28} clearcoat={1} />,
      bodyDark: <meshStandardMaterial color="#22314d" metalness={0.6} roughness={0.35} />,
      stripe: <meshPhysicalMaterial color="#f2dfa4" metalness={0.4} roughness={0.3} clearcoat={1} />,
      eye: (
        <meshStandardMaterial color="#ffcf6b" emissive="#ff9a1f" emissiveIntensity={1.4} roughness={0.2} />
      ),
      wing: <meshStandardMaterial color="#e3e8ec" metalness={0.4} roughness={0.3} side={THREE.DoubleSide} />,
      vein: <meshStandardMaterial color="#e2542a" metalness={0.5} roughness={0.4} />,
      arista: CHROME,
      thigh: CHROME,
      shin: CHROME,
      knee: BRASS,
      foot: BRASS,
      arm: CHROME,
      armKnee: BRASS,
      hand: BRASS,
    },
    thigh: 0.8,
    foot: 1.6,
    head: <LampBezels />,
    thorax: ({ keyRef }) => (
      <>
        <TinSeam />
        <WindKey keyRef={keyRef} />
      </>
    ),
    abdomen: <TinTail />,
    bag: { body: "#c9d0d6", rim: "#22314d", band: "#e2542a" },
  },
};
