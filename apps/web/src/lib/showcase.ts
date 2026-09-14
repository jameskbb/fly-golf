/**
 * Showcase bookkeeping: the session state the live backend would have sent around each recorded
 * shot, rebuilt from the shot records themselves (ball, lie, strokes, scorecard and totals). It
 * never decides anything about a shot: every value comes from a record. showcase.test.ts checks
 * the rebuilt scorecard against the one the recorder wrote.
 */
import type {
  CoursePayload,
  ScorecardEntry,
  SessionState,
  ShotRecord,
  ShowcaseIndex,
  ShowcaseRun,
  ShowcaseRunSummary,
} from "@fly-golf/protocol";

export type Stage = "before" | "after";

export const holeOf = (shot: ShotRecord): number =>
  shot.course?.hole_number ?? shot.hole?.number ?? shot.scenario.hole_number ?? 0;

/** Where one hole of a mixed round was recorded. */
export interface HoleSource {
  hole: number;
  run: string; // showcase run id
  seed: number; // that round's seed
  commit: string; // the commit it was simulated at
}

/** A round assembled from real recorded holes (`mixRound`). */
export type MixedRun = ShowcaseRun & { holeSources: HoleSource[] };

export const isMixed = (run: ShowcaseRun | undefined): run is MixedRun =>
  !!run && Array.isArray((run as Partial<MixedRun>).holeSources);

/** The complete rounds a brain played on its own in this showcase. */
export function runsForBrain(index: ShowcaseIndex, brainId: string): ShowcaseRunSummary[] {
  return index.runs.filter((r) => r.controllers_used.length === 1 && r.controllers_used[0] === brainId);
}

/** For every hole, one of the run ids, at random. */
export function drawHoles(
  holes: number[],
  ids: string[],
  random: () => number = Math.random,
): Map<number, string> {
  return new Map(holes.map((n) => [n, ids[Math.floor(random() * ids.length) % ids.length]]));
}

/**
 * A round made of real recorded holes: hole n is every recorded stroke of hole n, unchanged, from
 * the run `picks.get(n)`. The runs are complete rounds by the same brain on the same course and
 * every hole starts from its tee, so each hole stands on its own; the scorecard and totals are
 * rebuilt from the shots exactly as for a single recorded run. Nothing in a shot is altered.
 */
export function mixRound(runs: Map<string, ShowcaseRun>, picks: Map<number, string>): MixedRun {
  const holeSources: HoleSource[] = [];
  const shots: ShotRecord[] = [];
  for (const [hole, id] of picks) {
    const run = runs.get(id);
    if (!run) throw new Error(`recorded run "${id}" is not loaded`);
    const strokes = run.shots.filter((s) => holeOf(s) === hole);
    if (!strokes.length) throw new Error(`recorded run "${id}" has no strokes on hole ${hole}`);
    shots.push(...strokes);
    holeSources.push({ hole, run: id, seed: run.round.seed, commit: run.source.git.commit });
  }
  if (!holeSources.length) throw new Error("a mixed round needs at least one hole");
  return { ...runs.get(holeSources[0].run)!, shots, holeSources };
}

/** Index of the first recorded shot on each hole, in the order the holes were played. */
export function holeStarts(shots: ShotRecord[]): Map<number, number> {
  const out = new Map<number, number>();
  shots.forEach((s, i) => {
    if (!out.has(holeOf(s))) out.set(holeOf(s), i);
  });
  return out;
}

/** The scorecard once the first `count` shots have been played. */
export function scorecardAfter(shots: ShotRecord[], course: CoursePayload, count: number): ScorecardEntry[] {
  const card = course.holes.map((h) => ({
    hole: h.number,
    par: h.par,
    strokes: null as number | null,
    holed: null as boolean | null,
    controllers: [] as string[],
  }));
  const byHole = new Map(card.map((c) => [c.hole, c]));
  for (const shot of shots.slice(0, count)) {
    const entry = byHole.get(holeOf(shot));
    if (!entry) continue;
    if (!entry.controllers.includes(shot.controller.id)) entry.controllers.push(shot.controller.id);
    if (shot.outcome.episode_state !== "ready") {
      entry.strokes = shot.score?.hole_strokes ?? shot.initial_state.strokes_before + 1;
      entry.holed = shot.outcome.holed;
    }
  }
  return card;
}

function totalsOf(card: ScorecardEntry[]) {
  const played = card.filter((c) => c.strokes !== null);
  const strokes = played.reduce((a, c) => a + (c.strokes ?? 0), 0);
  const par = played.reduce((a, c) => a + c.par, 0);
  return { strokes, par_played: par, to_par: strokes - par, holes_played: played.length };
}

function controllersUsed(card: ScorecardEntry[]): string[] {
  const out: string[] = [];
  for (const c of card) for (const id of c.controllers ?? []) if (!out.includes(id)) out.push(id);
  return out;
}

const finalXY = (shot: ShotRecord): number[] => {
  const pts = shot.trajectory.points;
  const last = pts[pts.length - 1];
  return last ? [last[1], last[2]] : shot.initial_state.ball;
};

/** The session state just before (`before`) or just after (`after`) recorded shot `k`. */
export function showcaseState(
  run: ShowcaseRun,
  course: CoursePayload,
  k: number,
  stage: Stage,
): SessionState {
  const shots = run.shots;
  const shot = shots[k];
  const number = holeOf(shot);
  const next = shots[k + 1];
  const continues =
    stage === "after" && !!next && holeOf(next) === number && next.hole_index === shot.hole_index;
  const card = scorecardAfter(shots, course, stage === "after" ? k + 1 : k);

  let ball = shot.initial_state.ball;
  let lie = shot.initial_state.lie as string | undefined;
  let target = (shot.initial_state.target as number[] | null | undefined) ?? undefined;
  let strokes = shot.initial_state.strokes_before;
  let episode: SessionState["episode_state"] = "ready";
  let observation = (shot.initial_state.observation as Record<string, unknown> | undefined) ?? {
    body_heading_rad: shot.stroke.body_heading_rad,
  };
  if (stage === "after") {
    strokes = shot.score?.hole_strokes ?? shot.initial_state.strokes_before + 1;
    episode = shot.outcome.episode_state;
    if (continues) {
      // the ball as the next stroke found it (after any penalty drop)
      ball = next.initial_state.ball;
      lie = next.initial_state.lie as string | undefined;
      target = (next.initial_state.target as number[] | null | undefined) ?? undefined;
      observation = (next.initial_state.observation as Record<string, unknown> | undefined) ?? {
        body_heading_rad: next.stroke.body_heading_rad,
      };
    } else {
      ball = shot.outcome.holed ? shot.scenario.cup : finalXY(shot);
      lie = (shot.outcome.lie_after as string | undefined) ?? lie;
      observation = { body_heading_rad: shot.stroke.heading_rad };
    }
  }

  return {
    mode: "course",
    hole_index: shot.hole_index,
    hole_number: number,
    hole: course.holes.find((h) => h.number === number) ?? null,
    course: { name: course.name, version: course.version, par: course.par, holes: course.holes },
    scenario: shot.scenario,
    ball,
    lie,
    target,
    strokes,
    episode_state: episode,
    observation,
    controller: shot.controller,
    stats: {},
    run_id: shot.run_id,
    round_seed: isMixed(run)
      ? (run.holeSources.find((h) => h.hole === number)?.seed ?? run.round.seed)
      : run.round.seed,
    scorecard: card,
    totals: totalsOf(card),
    round_complete: card.every((c) => c.strokes !== null),
    controllers_used: controllersUsed(card),
  };
}
