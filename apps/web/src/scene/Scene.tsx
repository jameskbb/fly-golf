import { useEffect, useMemo, useRef } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { OrbitControls, Sky } from "@react-three/drei";
import type { CourseHole as Hole, Scenario } from "@fly-golf/protocol";
import * as THREE from "three";
import { holeFor, useStore } from "../store";
import { groundFor, heightAt } from "../lib/terrain";
import { Course } from "./Course";
import { CourseHole } from "./CourseHole";
import { Actors } from "./Actors";

const PUTTING_LIES = new Set(["green", "fringe"]);

/**
 * Frame each new ball position like a broadcast: low behind the ball looking down the line
 * on the green; behind the golfer looking down the fairway for full shots.
 */
function CameraRig({ scenario, hole, viewKey }: { scenario: Scenario; hole: Hole | null; viewKey: string }) {
  const camera = useThree((s) => s.camera);
  const controls = useThree((s) => s.controls) as unknown as {
    target: THREE.Vector3;
    update: () => void;
  } | null;
  useEffect(() => {
    const st = useStore.getState();
    const pb = st.playback;
    const ball = pb?.record.initial_state.ball ?? st.session?.ball ?? scenario.ball;
    const recTarget = pb?.record.initial_state.target as number[] | null | undefined;
    const aim = recTarget ?? (!pb ? st.session?.target : undefined) ?? scenario.cup;
    const lie = (pb?.record.initial_state.lie as string | undefined) ?? (!pb ? st.session?.lie : undefined);
    const ground = groundFor(scenario, hole);
    const [bx, by] = ball;
    const [cx, cy] = aim;
    const dist = Math.hypot(cx - bx, cy - by);
    const d = Math.max(0.5, dist);
    // Ball in (or on) the cup: no line to look along, so keep the fly's facing instead of
    // collapsing into a straight-down view.
    const heading =
      dist > 0.05
        ? Math.atan2(cy - by, cx - bx)
        : ((pb ? pb.record.stroke.heading_rad : (st.session?.observation?.body_heading_rad as number)) ??
          scenario.address_heading_rad);
    const ux = Math.cos(heading);
    const uy = Math.sin(heading);
    const h = heightAt(ground, bx, by);
    const putting = !hole || (lie !== undefined && PUTTING_LIES.has(lie));
    let tx: number;
    let ty: number;
    let th: number;
    if (putting) {
      const back = 1.6 + Math.min(d, 20) * 0.28;
      camera.position.set(
        bx - ux * back - uy * 0.55,
        h + 0.75 + Math.min(d, 20) * 0.12,
        -(by - uy * back + ux * 0.55),
      );
      tx = bx + ux * Math.min(d, 20) * 0.42;
      ty = by + uy * Math.min(d, 20) * 0.42;
      th = heightAt(ground, tx, ty);
    } else {
      // Behind the golfer, a little to the left of the line and low, looking a few metres past
      // the ball: the fly, its bag and the ball sit in the lower half, the hole in the upper half.
      camera.position.set(bx - ux * 1.5 - uy * 0.6, h + 0.55, -(by - uy * 1.5 + ux * 0.6));
      const look = Math.min(d, 4);
      tx = bx + ux * look;
      ty = by + uy * look;
      th = h;
    }
    if (controls) {
      controls.target.set(tx, th, -ty);
      controls.update();
    } else camera.lookAt(tx, th, -ty);
    // Re-frame only when the view changes (new ball position, hole, replay), not on every state
    // message that happens to carry a fresh scenario object.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewKey, camera, controls, hole]);
  return null;
}

/** Keep the sun's shadow frustum centred on the fly wherever it is on the hole. */
function SunRig({ course }: { course: boolean }) {
  const light = useRef<THREE.DirectionalLight>(null);
  const target = useMemo(() => new THREE.Object3D(), []);
  useEffect(() => {
    if (light.current) light.current.target = target;
  }, [target]);
  useFrame(() => {
    const st = useStore.getState();
    const b = st.playback?.record.initial_state.ball ?? st.session?.ball;
    const [x, y] = b ?? [0, 0];
    target.position.set(x, 0, -y);
    target.updateMatrixWorld();
    light.current?.position.set(x + 6, 10, -y + 4);
  });
  return (
    <>
      <primitive object={target} />
      <directionalLight
        ref={light}
        position={[6, 10, 4]}
        intensity={course ? 2.6 : 2.4}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-8}
        shadow-camera-right={8}
        shadow-camera-top={8}
        shadow-camera-bottom={-8}
        shadow-bias={-0.0004}
      />
    </>
  );
}

export function Scene() {
  const session = useStore((s) => s.session);
  const playback = useStore((s) => s.playback);
  const hole = useStore((s) => holeFor(s, s.playback?.replay ? s.playback.record : undefined));
  const scenario = playback?.replay ? playback.record.scenario : session?.scenario;
  const course = !!hole;
  // Re-frame on a new hole, after the fly walks to its next ball, and on replays -
  // but not when a live stroke starts (keeps the spectator's camera during the swing).
  const shownStrokes =
    playback && !playback.replay ? playback.record.initial_state.strokes_before : session?.strokes;
  const viewKey = playback?.replay
    ? `replay-${playback.record.shot_id}-${playback.startedAt}`
    : `live-${session?.run_id}-${session?.hole_index}-${shownStrokes}`;

  return (
    <Canvas
      shadows="percentage"
      dpr={[1, 2]}
      // near/far span 400 000:1 (a fly's-eye close-up to the horizon trees); a logarithmic depth
      // buffer keeps millimetre ground layers apart hundreds of metres away, e.g. under the
      // follow-cam while the ball is in the air.
      gl={{ logarithmicDepthBuffer: true }}
      camera={{ fov: 40, near: 0.01, far: 4000, position: [-3, 1.5, 2] }}
    >
      <color attach="background" args={["#a9c9e6"]} />
      <fog attach="fog" args={course ? ["#c3d8ea", 160, 1100] : ["#bcd5ea", 35, 160]} />
      <Sky sunPosition={[60, 40, 30]} turbidity={5} rayleigh={1.1} mieCoefficient={0.004} distance={3500} />
      <hemisphereLight args={["#dcecff", "#35552c", 0.75]} />
      <SunRig course={course} />
      {scenario && (
        <>
          {hole ? <CourseHole hole={hole} /> : <Course scenario={scenario} />}
          <Actors scenario={scenario} hole={hole} />
          <CameraRig scenario={scenario} hole={hole} viewKey={viewKey} />
        </>
      )}
      <OrbitControls
        makeDefault
        maxPolarAngle={Math.PI / 2 - 0.04}
        minDistance={0.25}
        maxDistance={course ? 600 : 45}
        enableDamping
      />
    </Canvas>
  );
}
