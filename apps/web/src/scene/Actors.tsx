/**
 * Fly + ball + trail (+ golf bag on the course), animated every frame from the store.
 *
 * During playback the fly executes the recorded, decoded stroke and the ball
 * follows the backend-computed trajectory (flight, bounces and roll). On the course the fly
 * first pulls the club it chose out of its bag. Nothing here decides anything about the
 * shot; the browser frame rate only affects how smoothly it is *shown*.
 */
import { useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { Line } from "@react-three/drei";
import * as THREE from "three";
import type { CourseHole, Scenario } from "@fly-golf/protocol";
import { playbackTime, useStore } from "../store";
import { sampleTrajectory } from "../lib/coords";
import { timelineFor } from "../lib/playback";
import { groundFor, heightAt } from "../lib/terrain";
import { easeInOut, lerpAngle, poseAt, type Phase, type Timeline } from "../lib/swing";
import { BALL_OFFSETS, Fly, clubStyle, type ClubStyle, type FlyRig } from "./Fly";
import { BALL_RADIUS } from "./Course";
import { LOOKS, type Look } from "./looks";
import { personaFor } from "../ui/brains";

const TRAIL_MAX = 4096;
const BAG_OFFSET = new THREE.Vector3(-0.13, 0, 0.17); // fly-local: behind and to the side
const tmp = new THREE.Vector3();
const bagTop = new THREE.Vector3();
const grip = new THREE.Vector3();
const camGoal = new THREE.Vector3();
const lookGoal = new THREE.Vector3();

function ClubModel({ style }: { style: ClubStyle }) {
  // A loose club for the bag / the one being pulled out (shaft along +y, head at the bottom).
  return (
    <group>
      <mesh position={[0, 0.07, 0]}>
        <cylinderGeometry args={[0.0022, 0.0022, 0.14, 6]} />
        <meshStandardMaterial
          color={style === "wood" ? "#2a2f35" : "#dfe4e8"}
          metalness={0.6}
          roughness={0.3}
        />
      </mesh>
      <mesh position={[0, 0.145, 0]}>
        <cylinderGeometry args={[0.0045, 0.004, 0.03, 8]} />
        <meshStandardMaterial color="#1b1f22" roughness={0.8} />
      </mesh>
      {style === "wood" ? (
        <mesh position={[0.008, -0.004, 0]} scale={[0.02, 0.011, 0.016]}>
          <sphereGeometry args={[1, 14, 10]} />
          <meshPhysicalMaterial color="#15181c" metalness={0.4} roughness={0.25} clearcoat={0.8} />
        </mesh>
      ) : style === "iron" ? (
        <mesh position={[0.008, -0.004, 0]}>
          <boxGeometry args={[0.026, 0.018, 0.005]} />
          <meshStandardMaterial color="#c9d0d6" metalness={0.9} roughness={0.2} />
        </mesh>
      ) : (
        <mesh position={[0.01, -0.004, 0]}>
          <boxGeometry args={[0.04, 0.012, 0.01]} />
          <meshStandardMaterial color="#b8c0c7" metalness={0.85} roughness={0.25} />
        </mesh>
      )}
    </group>
  );
}

function Bag({ bagRef, colors }: { bagRef: React.RefObject<THREE.Group | null>; colors: Look["bag"] }) {
  const tops: [ClubStyle, number, number][] = [
    ["wood", -0.012, 0.004],
    ["wood", 0.01, -0.006],
    ["iron", 0.0, 0.012],
    ["iron", -0.01, -0.012],
    ["iron", 0.012, 0.008],
    ["putter", 0.004, -0.014],
  ];
  return (
    <group ref={bagRef} visible={false}>
      <group rotation={[0.18, 0, 0.12]}>
        <mesh position={[0, 0.075, 0]} castShadow>
          <cylinderGeometry args={[0.03, 0.026, 0.15, 16]} />
          <meshStandardMaterial color={colors.body} roughness={0.55} />
        </mesh>
        <mesh position={[0, 0.152, 0]}>
          <torusGeometry args={[0.03, 0.004, 8, 20]} />
          <meshStandardMaterial color={colors.rim} roughness={0.6} />
        </mesh>
        <mesh position={[0, 0.03, 0]}>
          <cylinderGeometry args={[0.0305, 0.0305, 0.012, 16]} />
          <meshStandardMaterial color={colors.band} roughness={0.6} />
        </mesh>
        {tops.map(([style, x, z], i) => (
          <group key={i} position={[x, 0.2, z]} rotation={[Math.PI, 0, 0.3 * i]}>
            <ClubModel style={style} />
          </group>
        ))}
      </group>
    </group>
  );
}

export function Actors({ scenario, hole }: { scenario: Scenario; hole: CourseHole | null }) {
  const ground = useMemo(() => groundFor(scenario, hole), [scenario, hole]);
  // the model is the brain that is swinging: the shot being shown, else the session's brain
  // (no fly until that is known, so a mock session never flashes a real fly's body first)
  const persona = useStore((s) => {
    const controller = s.playback?.record.controller ?? s.session?.controller;
    return controller ? personaFor(controller) : null;
  });
  const rig = useRef<FlyRig | null>(null);
  const ball = useRef<THREE.Mesh>(null);
  const aimGroup = useRef<THREE.Group>(null);
  const bag = useRef<THREE.Group>(null);
  const pick = useRef<THREE.Group>(null);
  const pickStyle = useRef<ClubStyle>("iron");
  const splash = useRef<THREE.Mesh>(null);
  const marker = useRef<THREE.Group>(null);
  const flyPos = useRef(new THREE.Vector3(NaN, 0, 0));
  const flyYaw = useRef<number | null>(null);
  const cache = useRef<{ key: string; tl: Timeline } | null>(null);
  const lastPhase = useRef<Phase | "idle">("idle");
  const following = useRef(false);
  const camera = useThree((s) => s.camera);
  const controls = useThree((s) => s.controls) as unknown as {
    target: THREE.Vector3;
    update: () => void;
  } | null;
  const trailGeom = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(3 * TRAIL_MAX), 3));
    g.setDrawRange(0, 0);
    return g;
  }, []);
  const trailKey = useRef("");
  const trailHole = useRef(""); // run/hole the drawn tracer belongs to
  const pickModels = useMemo(
    () => ({
      putter: <ClubModel style="putter" />,
      iron: <ClubModel style="iron" />,
      wood: <ClubModel style="wood" />,
    }),
    [],
  );

  useFrame((state, dt) => {
    const s = useStore.getState();
    const r = rig.current;
    if (!r || !ball.current) return;
    const t = state.clock.elapsedTime;
    const pb = s.playback;
    const course = !!hole;

    let ballWorld: [number, number, number];
    let anchor: number[]; // ball position the fly addresses
    let lineHeading: number;
    let club = Math.sin(t * 1.3) * 0.03; // idle waggle
    let turn = 0;
    let phase: Phase | "idle" = "idle";
    let reaction = 0;
    let holed = false;
    let contact = true;
    let showAim = false;
    let style: ClubStyle | null = course ? null : "putter"; // on the course the club lives in the bag until chosen
    let selectProgress = 1;
    let outcome = "";
    let atEnd = false;
    let finalPos: number[] | null = null;
    let tl: Timeline | null = null;

    if (pb) {
      const rec = pb.record;
      const key = `${rec.run_id}/${rec.shot_id}/${pb.id}`;
      if (cache.current?.key !== key) cache.current = { key, tl: timelineFor(rec) };
      tl = cache.current.tl;
      const pose = poseAt(tl, playbackTime(pb));
      phase = pose.phase;
      anchor = rec.initial_state.ball;
      lineHeading = lerpAngle(rec.stroke.body_heading_rad, rec.stroke.heading_rad, pose.aimProgress);
      club = pose.club;
      turn = pose.turn;
      reaction = pose.reaction;
      holed = rec.outcome.holed;
      contact = rec.stroke.contact;
      outcome = rec.outcome.outcome;
      style = clubStyle(rec.stroke.club?.kind);
      selectProgress = pose.selectProgress;
      showAim = phase === "aim" || phase === "backswing" || phase === "downswing";
      const pts = rec.trajectory.points;
      finalPos = pts[pts.length - 1];
      if (pose.ballTime === null) {
        ballWorld = [anchor[0], anchor[1], heightAt(ground, anchor[0], anchor[1]) + BALL_RADIUS];
      } else {
        ballWorld = sampleTrajectory(pts, pose.ballTime);
        atEnd = pose.ballTime >= tl.rollDuration;
      }
      // trail: rebuild when the record changes, extend as the ball travels
      if (trailKey.current !== key) {
        trailKey.current = key;
        trailHole.current = pb.replay ? "" : `${rec.run_id}/${rec.hole_index}`;
        const arr = trailGeom.attributes.position.array as Float32Array;
        const n = Math.min(pts.length, TRAIL_MAX);
        for (let i = 0; i < n; i++) arr.set([pts[i][1], pts[i][3] + 0.002, -pts[i][2]], i * 3);
        trailGeom.attributes.position.needsUpdate = true;
        trailGeom.computeBoundingSphere();
      }
      let drawn = 0;
      if (pose.ballTime !== null) {
        while (drawn < pts.length && pts[drawn][0] <= pose.ballTime) drawn++;
      }
      trailGeom.setDrawRange(0, Math.min(drawn, TRAIL_MAX));
      if (phase === "done") s.endPlayback();
    } else {
      const sess = s.session;
      anchor = sess?.ball ?? scenario.ball;
      lineHeading =
        (sess?.observation?.body_heading_rad as number | undefined) ?? scenario.address_heading_rad;
      const inCup = Math.hypot(anchor[0] - scenario.cup[0], anchor[1] - scenario.cup[1]) < 0.01;
      ballWorld = [
        anchor[0],
        anchor[1],
        heightAt(ground, anchor[0], anchor[1]) + (inCup ? -0.05 : BALL_RADIUS),
      ];
      // Keep the last tracer on screen while the fly walks to its ball, but not onto a new
      // hole, a new round or the other mode (nor after a replay of some other shot).
      if (trailHole.current !== `${sess?.run_id}/${sess?.hole_index}`) trailGeom.setDrawRange(0, 0);
    }
    if (phase !== lastPhase.current) {
      lastPhase.current = phase;
      s.set({ playPhase: phase });
    }

    // ---- ball (hidden once it is in the cup, under water, or in the trees)
    ball.current.position.set(ballWorld[0], ballWorld[2], -ballWorld[1]);
    const lost = atEnd && (outcome === "water" || outcome === "out_of_bounds");
    ball.current.visible = !lost && ballWorld[2] > heightAt(ground, ballWorld[0], ballWorld[1]) - 0.03;

    // ---- splash where a ball found the water
    if (splash.current) {
      const show = lost && outcome === "water" && finalPos !== null && phase !== "done";
      splash.current.visible = show;
      if (show && finalPos) {
        const k = (t * 1.3) % 1;
        splash.current.position.set(finalPos[1], 0.03, -finalPos[2]);
        splash.current.scale.setScalar(0.3 + 2.2 * k);
        (splash.current.material as THREE.MeshBasicMaterial).opacity = 0.8 * (1 - k);
      }
    }

    // ---- fly placement: stand beside the ball, perpendicular to the line
    const offset = BALL_OFFSETS[style ?? "iron"];
    const yaw = lineHeading + Math.PI / 2;
    const targetX = anchor[0] - offset * Math.cos(yaw);
    const targetY = anchor[1] - offset * Math.sin(yaw);
    const target = tmp.set(targetX, heightAt(ground, targetX, targetY), -targetY);
    if (Number.isNaN(flyPos.current.x) || pb?.replay || flyPos.current.distanceTo(target) > 30)
      flyPos.current.copy(target);
    const moving = flyPos.current.distanceTo(target);
    flyPos.current.lerp(target, 1 - Math.exp(-dt * 3.5));
    if (flyYaw.current === null || pb?.replay) flyYaw.current = yaw;
    flyYaw.current = lerpAngle(flyYaw.current, yaw, 1 - Math.exp(-dt * 6));
    r.root.position.copy(flyPos.current);
    r.root.rotation.y = flyYaw.current;
    const walking = moving > 0.02;
    r.body.position.y = walking ? Math.abs(Math.sin(t * 14)) * 0.012 : 0;
    r.body.rotation.y = turn;

    // ---- club in hand (hidden until it has been pulled out of the bag)
    const inHand = style !== null && selectProgress >= 1;
    r.club.visible = inHand;
    for (const k of ["putter", "iron", "wood"] as const) r.heads[k].visible = style === k;
    r.club.rotation.x = club;

    // ---- the bag and the club being chosen
    if (bag.current) {
      bag.current.visible = course;
      bag.current.position.copy(r.root.localToWorld(bagTop.copy(BAG_OFFSET)));
      bag.current.rotation.y = r.root.rotation.y;
    }
    if (pick.current) {
      const choosing = course && style !== null && selectProgress < 1 && pb !== undefined;
      pick.current.visible = choosing;
      if (choosing && bag.current) {
        if (pickStyle.current !== style) pickStyle.current = style!;
        bag.current.getWorldPosition(bagTop).add(tmp.set(0, 0.2, 0));
        r.club.getWorldPosition(grip);
        // rise out of the bag, then swing across into the fly's front legs
        const p = easeInOut(Math.min(1, Math.max(0, (selectProgress - 0.15) / 0.85)));
        const lift = Math.sin(Math.min(1, selectProgress * 1.4) * Math.PI) * 0.08;
        pick.current.position.lerpVectors(bagTop, grip, p);
        pick.current.position.y += lift;
        pick.current.rotation.set(Math.PI * (1 - p), r.root.rotation.y, 0);
        for (const [i, k] of (["putter", "iron", "wood"] as const).entries())
          (pick.current.children[i] as THREE.Object3D).visible = k === style;
      }
    }

    // ---- reactions
    let wingFlap = 0;
    let headNod = 0;
    let bodyPitch = 0;
    let hop = 0;
    if (phase === "reaction") {
      if (holed) {
        hop = Math.abs(Math.sin(reaction * Math.PI * 5)) * 0.05 * (1 - reaction);
        wingFlap = Math.sin(t * 90) * 0.5 * (1 - reaction * 0.6);
        r.club.rotation.x = -1.3 * Math.min(1, reaction * 4);
      } else if (!contact || outcome === "water" || outcome === "out_of_bounds") {
        headNod = Math.sin(t * 16) * 0.25 * (1 - reaction);
      } else {
        bodyPitch = -0.22 * Math.min(1, reaction * 3);
        headNod = -0.3 * Math.min(1, reaction * 3);
      }
    }
    const thinking = s.busy && !pb;
    if (thinking) wingFlap = Math.sin(t * 40) * 0.08;
    r.body.position.y += hop;
    r.body.rotation.z = bodyPitch;
    r.head.rotation.z = headNod;
    r.wingL.rotation.x = wingFlap;
    r.wingR.rotation.x = -wingFlap;
    const twitch = thinking ? Math.sin(t * 30) * 0.35 : Math.sin(t * 2.1) * 0.08;
    r.antennaL.rotation.z = twitch;
    r.antennaR.rotation.z = -twitch * 0.8;

    // ---- the tin fly's key: ticks over at rest, whirs while its rules run and it swings
    if (r.windKey) r.windKey.rotation.y += dt * (thinking ? 16 : pb && phase !== "done" ? 6 : 1.2);

    // ---- neural sparks above the head: only for the real connectome controllers
    const isMaleCNS = (pb?.record.controller.kind ?? s.session?.controller.kind) === "malecns";
    r.brain.visible = isMaleCNS && (thinking || (pb !== undefined && phase !== "done"));
    if (r.brain.visible) {
      const m = r.brain.material as THREE.PointsMaterial;
      m.opacity = thinking ? 0.5 + 0.5 * Math.abs(Math.sin(t * 9)) : 0.35;
      r.brain.rotation.y = t * 1.5;
    }

    // ---- decoded aim line (longer for full shots)
    if (aimGroup.current) {
      aimGroup.current.visible = showAim;
      aimGroup.current.position.set(anchor[0], heightAt(ground, anchor[0], anchor[1]) + 0.006, -anchor[1]);
      aimGroup.current.rotation.y = lineHeading;
      aimGroup.current.scale.setScalar(style && style !== "putter" ? 8 : 1);
    }

    // ---- where the fly is aiming on the course (a routing point short of the pin)
    if (marker.current) {
      const tg = s.session?.target;
      const show = course && !pb && !!tg && Math.hypot(tg[0] - scenario.cup[0], tg[1] - scenario.cup[1]) > 1;
      marker.current.visible = show;
      if (show && tg) {
        marker.current.position.set(tg[0], 0.02, -tg[1]);
        marker.current.rotation.y = t * 0.6;
      }
    }

    // ---- broadcast follow-cam while a full shot is in the air and rolling out
    const inFlight = !!pb && !!tl?.full && contact && (phase === "follow" || phase === "rolling");
    if (inFlight && controls) {
      following.current = true;
      const dx = ballWorld[0] - anchor[0];
      const dy = ballWorld[1] - anchor[1];
      const d = Math.hypot(dx, dy);
      const ux = d > 1 ? dx / d : Math.cos(lineHeading);
      const uy = d > 1 ? dy / d : Math.sin(lineHeading);
      const hgt = ballWorld[2];
      const back = 10 + hgt * 0.4;
      camGoal.set(
        ballWorld[0] - ux * back + uy * 2.5,
        2.5 + hgt * 0.55,
        -(ballWorld[1] - uy * back - ux * 2.5),
      );
      lookGoal.set(ballWorld[0], hgt * 0.8, -ballWorld[1]);
      const k = 1 - Math.exp(-dt * 2.2);
      camera.position.lerp(camGoal, k);
      controls.target.lerp(lookGoal, k);
      controls.update();
    } else if (following.current && !pb) {
      following.current = false;
    }
  });

  const aimPts = useMemo(() => [new THREE.Vector3(0.03, 0, 0), new THREE.Vector3(2.5, 0, 0)], []);

  return (
    <group>
      {persona && <Fly key={persona} rigRef={rig} persona={persona} />}
      <Bag bagRef={bag} colors={LOOKS[persona ?? "fly"].bag} />
      <group ref={pick} visible={false}>
        {pickModels.putter}
        {pickModels.iron}
        {pickModels.wood}
      </group>
      <mesh ref={ball} castShadow>
        <sphereGeometry args={[BALL_RADIUS, 32, 24]} />
        <meshStandardMaterial color="#fbfbf7" roughness={0.32} />
      </mesh>
      <primitive
        object={useMemo(
          () => new THREE.Line(trailGeom, new THREE.LineBasicMaterial({ color: "#ffb938" })),
          [trailGeom],
        )}
      />
      <mesh ref={splash} rotation={[-Math.PI / 2, 0, 0]} visible={false}>
        <ringGeometry args={[0.35, 0.5, 40]} />
        <meshBasicMaterial color="#e8f6ff" transparent opacity={0.8} depthWrite={false} />
      </mesh>
      <group ref={marker} visible={false}>
        <mesh rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[2.2, 2.7, 48]} />
          <meshBasicMaterial color="#ffe39a" transparent opacity={0.75} depthWrite={false} />
        </mesh>
        <mesh position={[0, 1.5, 0]}>
          <cylinderGeometry args={[0.05, 0.05, 3, 8]} />
          <meshBasicMaterial color="#ffe39a" transparent opacity={0.6} />
        </mesh>
      </group>
      <group ref={aimGroup} visible={false}>
        <Line
          points={aimPts}
          color="#ffe39a"
          lineWidth={2}
          dashed
          dashSize={0.06}
          gapSize={0.04}
          transparent
          opacity={0.85}
        />
      </group>
    </group>
  );
}
