/**
 * Swing timeline: turns a recorded, decoded stroke into animation beats.
 *
 * This is the *embodiment* of decoded motor output, not biomechanics: a real
 * fly does not swing a golf club. Timing comes from the decoded tempo
 * (backswing_s / downswing_s), amplitude from decoded power (and, for full
 * swings, the swing fraction), the line from the decoded start direction, and the
 * ball follows the backend trajectory. On the course the fly first pulls the
 * club it chose (decoded from `club_reach`) out of its bag.
 */

export type Phase =
  "select" | "address" | "aim" | "backswing" | "downswing" | "follow" | "rolling" | "reaction" | "done";

export interface StrokeLike {
  power: number;
  backswing_s: number;
  downswing_s: number;
  contact: boolean;
  swing_fraction?: number;
  club?: { kind: string } | null;
}

export interface TimelineOptions {
  /** Show the club-selection beat (course shots). */
  select?: boolean;
}

export interface Timeline {
  select0: number;
  aim0: number;
  back0: number;
  down0: number;
  impact: number;
  followEnd: number;
  rollEnd: number;
  reaction0: number;
  end: number;
  amplitude: number;
  follow: number;
  full: boolean;
  contact: boolean;
  holed: boolean;
  rollDuration: number;
}

export const SELECT_S = 1.1;
export const ADDRESS_S = 0.6;
export const AIM_S = 0.8;
export const FOLLOW_S = 0.45;
export const FULL_FOLLOW_S = 0.7;
export const REACTION_S = 2.0;

const clamp = (v: number, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));
export const easeInOut = (p: number) => (p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2);
const easeIn = (p: number) => p * p;
const easeOut = (p: number) => 1 - (1 - p) * (1 - p);

export const isFullSwing = (stroke: StrokeLike) => !!stroke.club && stroke.club.kind !== "putter";

export function buildTimeline(
  stroke: StrokeLike,
  rollDuration: number,
  holed: boolean,
  opts: TimelineOptions = {},
): Timeline {
  const full = isFullSwing(stroke);
  const select0 = 0;
  const aim0 = (opts.select ? SELECT_S : 0) + ADDRESS_S;
  const back0 = aim0 + AIM_S;
  const down0 = back0 + Math.max(0.15, stroke.backswing_s);
  const impact = down0 + Math.max(0.08, stroke.downswing_s);
  const followEnd = impact + (full ? FULL_FOLLOW_S : FOLLOW_S);
  const rollEnd = impact + (stroke.contact ? rollDuration : 0);
  const reaction0 = Math.max(followEnd, rollEnd);
  // Putter: a short pendulum (V1). Full swing: the club goes back over the shoulder.
  const amplitude = full
    ? 1.1 + 1.4 * clamp(stroke.swing_fraction ?? stroke.power)
    : 0.18 + 0.85 * clamp(stroke.power);
  return {
    select0,
    aim0,
    back0,
    down0,
    impact,
    followEnd,
    rollEnd,
    reaction0,
    end: reaction0 + REACTION_S,
    amplitude,
    follow: full ? Math.min(2.6, 1.05 * amplitude) : 0.6 * amplitude,
    full,
    contact: stroke.contact,
    holed,
    rollDuration,
  };
}

export interface Pose {
  phase: Phase;
  selectProgress: number; // 0..1 through the club-selection beat (1 once the club is in hand)
  aimProgress: number; // 0 = body heading, 1 = decoded stroke line
  club: number; // pendulum angle (rad); + = back, - = through
  turn: number; // body turn with a full swing (rad, 0 for putts)
  ballTime: number | null; // seconds into the trajectory, null before impact
  reaction: number; // 0..1 progress through the reaction
}

export function poseAt(tl: Timeline, t: number): Pose {
  const selectProgress = tl.aim0 - ADDRESS_S > 0 ? clamp(t / (tl.aim0 - ADDRESS_S)) : 1;
  const aimProgress = easeInOut(clamp((t - tl.aim0) / (tl.back0 - tl.aim0)));
  let club = 0;
  let phase: Phase;
  if (t < tl.aim0 - ADDRESS_S) phase = "select";
  else if (t < tl.aim0) phase = "address";
  else if (t < tl.back0) phase = "aim";
  else if (t < tl.down0) {
    phase = "backswing";
    club = tl.amplitude * easeInOut((t - tl.back0) / (tl.down0 - tl.back0));
  } else if (t < tl.impact) {
    phase = "downswing";
    club = tl.amplitude * (1 - easeIn((t - tl.down0) / (tl.impact - tl.down0)));
  } else if (t < tl.followEnd) {
    phase = "follow";
    club = -tl.follow * easeOut((t - tl.impact) / (tl.followEnd - tl.impact));
  } else {
    club = -tl.follow * (1 - easeInOut(clamp((t - tl.followEnd) / 0.8)));
    phase = t < tl.reaction0 ? "rolling" : t < tl.end ? "reaction" : "done";
  }
  const turn = tl.full ? 0.35 * (club / Math.max(1e-6, tl.amplitude)) : 0;
  const ballTime = tl.contact && t >= tl.impact ? Math.min(t - tl.impact, tl.rollDuration) : null;
  const reaction = clamp((t - tl.reaction0) / REACTION_S);
  return { phase, selectProgress, aimProgress, club, turn, ballTime, reaction };
}

/** Interpolate angles along the shortest arc. */
export function lerpAngle(a: number, b: number, p: number): number {
  let d = (b - a) % (2 * Math.PI);
  if (d > Math.PI) d -= 2 * Math.PI;
  if (d < -Math.PI) d += 2 * Math.PI;
  return a + d * p;
}
