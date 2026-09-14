/**
 * Headshots for the brain picker, rendered from the real 3D models.
 *
 * One small offscreen WebGL root renders each persona's head and shoulders once, keeps the
 * PNG, and is torn down; the cards show the images. The portrait is therefore always the
 * fly you will see on the course, never a separate drawing of it.
 */
import { useLayoutEffect, useRef, useSyncExternalStore } from "react";
import { createRoot, useThree } from "@react-three/fiber";
import * as THREE from "three";
import { Fly, type FlyRig } from "./Fly";
import { LOOKS, type PersonaId } from "./looks";

const ORDER: PersonaId[] = ["fly", "golfer", "windup"];
// rim light in each brain's tone (the --live / --trained / --mock colours in styles.css)
const RIM: Record<PersonaId, string> = { fly: "#39e08a", golfer: "#c38bff", windup: "#ff8a3d" };
const SIZE = 192; // px; shown at 44-76 CSS px, so sharp at 2x or better

const shots = new Map<PersonaId, string>();
const listeners = new Set<() => void>();
let started = false;

function Capture({
  persona,
  rig,
  onShot,
}: {
  persona: PersonaId;
  rig: React.RefObject<FlyRig | null>;
  onShot: (url: string) => void;
}) {
  const { gl, scene, camera } = useThree();
  useLayoutEffect(() => {
    const frame = LOOKS[persona].portrait;
    const r = rig.current;
    if (r) {
      r.club.visible = false; // a headshot, not an action shot
      r.head.rotation.y = frame.headYaw;
    }
    camera.position.set(...frame.camera);
    camera.lookAt(...frame.target);
    if (camera instanceof THREE.PerspectiveCamera) {
      camera.fov = frame.fov;
      camera.updateProjectionMatrix();
    }
    camera.updateMatrixWorld();
    gl.render(scene, camera);
    onShot(gl.domElement.toDataURL("image/png"));
  }, [gl, scene, camera, persona, rig, onShot]);
  return null;
}

function Sitter({ persona, onShot }: { persona: PersonaId; onShot: (url: string) => void }) {
  const rig = useRef<FlyRig | null>(null);
  return (
    <>
      <hemisphereLight args={["#fff8ec", "#2b3a30", 1.1]} />
      <directionalLight position={[0.6, 1.1, 1.2]} intensity={2.4} />
      <directionalLight position={[-1, 0.5, -0.9]} intensity={3.2} color={RIM[persona]} />
      <Fly rigRef={rig} persona={persona} />
      <Capture persona={persona} rig={rig} onShot={onShot} />
    </>
  );
}

async function renderAll() {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = SIZE;
  const root = createRoot(canvas);
  try {
    await root.configure({
      gl: { alpha: true, antialias: true, preserveDrawingBuffer: true },
      camera: { fov: 30, near: 0.005, far: 5 },
      size: { width: SIZE, height: SIZE, top: 0, left: 0 },
      dpr: 1,
      frameloop: "never",
      events: undefined,
    });
    for (const persona of ORDER) {
      const url = await new Promise<string>((resolve) =>
        root.render(<Sitter persona={persona} onShot={resolve} />),
      );
      shots.set(persona, url);
      listeners.forEach((l) => l());
    }
  } finally {
    root.unmount(); // releases the second WebGL context even if a render failed
  }
}

function subscribe(l: () => void) {
  listeners.add(l);
  if (!started && typeof document !== "undefined") {
    started = true;
    // when the page is idle, so the portraits never hold up the course
    const run = () =>
      void renderAll().catch((e: unknown) => console.warn("Brain headshots could not be rendered:", e));
    if ("requestIdleCallback" in window) window.requestIdleCallback(run, { timeout: 2000 });
    else setTimeout(run, 0);
  }
  return () => listeners.delete(l);
}

/** The persona's headshot as an image URL, or undefined until (or unless) it has been rendered. */
export function usePortrait(persona: PersonaId): string | undefined {
  return useSyncExternalStore(
    subscribe,
    () => shots.get(persona),
    () => undefined,
  );
}
