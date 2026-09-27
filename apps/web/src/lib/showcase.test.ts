import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { CoursePayload, SessionState, ShowcaseIndex, ShowcaseRun, type ShotRecord } from "@fly-golf/protocol";
import {
  drawHoles,
  holeOf,
  holeStarts,
  holesOfRun,
  isMixed,
  mixRound,
  roundHoles,
  runsForBrain,
  scorecardAfter,
  showcaseState,
} from "./showcase";
import { assetUrl } from "./source";

// The committed showcase that GitHub Pages serves (written by `fly-golf export-showcase`).
const dir = join(dirname(fileURLToPath(import.meta.url)), "../../public/showcase");
const load = (path: string) => JSON.parse(readFileSync(join(dir, path), "utf8"));

describe("assetUrl", () => {
  it("resolves static files under the deployed base path", () => {
    expect(assetUrl("/showcase/index.json", "/fly-golf/")).toBe("/fly-golf/showcase/index.json");
    expect(assetUrl("showcase/index.json", "/fly-golf")).toBe("/fly-golf/showcase/index.json");
    expect(assetUrl("showcase/index.json", "/")).toBe("/showcase/index.json");
  });
});

const index = ShowcaseIndex.parse(load("index.json"));
const course = CoursePayload.parse(load(index.course));

describe("committed showcase", () => {
  it("features one of its runs", () => {
    expect(index.runs.length).toBeGreaterThan(0);
    expect(index.runs.map((r) => r.id)).toContain(index.featured);
  });

  for (const entry of index.runs) {
    describe(entry.id, () => {
      const run = ShowcaseRun.parse(load(entry.file));

      it("matches its index entry and is labelled honestly", () => {
        expect(run.id).toBe(entry.id);
        expect(run.shots.length).toBe(entry.shots);
        expect(entry.is_mock).toBe(run.shots.some((s) => s.controller.is_mock));
        for (const s of run.shots) {
          if (!s.controller.is_mock) expect(s.neural_summary?.neuron_count).toBeGreaterThan(0);
          else expect(s.neural_summary).toBeNull();
        }
      });

      it("rebuilds the scorecard the recorder wrote", () => {
        const card = scorecardAfter(run.shots, course, run.shots.length);
        expect(card.map((c) => [c.hole, c.strokes, c.holed])).toEqual(
          run.round.scorecard.map((c) => [c.hole, c.strokes, c.holed]),
        );
      });

      it("gives a valid session state around every shot", () => {
        run.shots.forEach((shot, k) => {
          const before = SessionState.parse(showcaseState(run, course, k, "before"));
          const after = SessionState.parse(showcaseState(run, course, k, "after"));
          expect(before.strokes).toBe(shot.initial_state.strokes_before);
          expect(before.ball).toEqual(shot.initial_state.ball);
          expect(after.strokes).toBe(shot.score?.hole_strokes);
          expect(after.totals).toMatchObject({
            strokes: shot.score?.strokes,
            to_par: shot.score?.to_par,
            holes_played: shot.score?.holes_played,
          });
          const next = run.shots[k + 1];
          if (next && holeOf(next) === holeOf(shot))
            expect(after.ball).toEqual(showcaseState(run, course, k + 1, "before").ball);
        });
      });

      it("finds the first shot of each hole", () => {
        for (const [hole, i] of holeStarts(run.shots)) {
          expect(holeOf(run.shots[i])).toBe(hole);
          if (i > 0) expect(holeOf(run.shots[i - 1])).not.toBe(hole);
        }
      });
    });
  }
});

describe("mixed rounds", () => {
  const runs = new Map(index.runs.map((e) => [e.id, ShowcaseRun.parse(load(e.file))]));
  const holes = course.holes.map((h) => h.number);
  const brains = [
    ...new Set(index.runs.flatMap((r) => (r.controllers_used.length === 1 ? r.controllers_used : []))),
  ];
  const sourceCard = (id: string, hole: number) =>
    runs.get(id)!.round.scorecard.find((c) => c.hole === hole)!;

  it("draws every hole, only from the ids it is given", () => {
    const picks = drawHoles(holes, ["a", "b", "c"], () => 0.999);
    expect([...picks.keys()]).toEqual(holes);
    expect(new Set(picks.values())).toEqual(new Set(["c"]));
    expect(new Set(drawHoles(holes, ["a", "b"], () => 0).values())).toEqual(new Set(["a"]));
    for (const b of brains) for (const r of runsForBrain(index, b)) expect(r.controllers_used).toEqual([b]);
  });

  for (const brain of brains) {
    it(`${brain}: each hole is one recorded hole, unchanged, and the card adds up`, () => {
      const ids = runsForBrain(index, brain).map((r) => r.id);
      const picks = new Map(holes.map((n, i) => [n, ids[i % ids.length]]));
      const mixed = mixRound(runs, picks);
      expect(isMixed(mixed)).toBe(true);
      expect([...holeStarts(mixed.shots).keys()]).toEqual(holes);
      for (const n of holes) {
        const got = mixed.shots.filter((s) => holeOf(s) === n);
        const want = runs.get(picks.get(n)!)!.shots.filter((s) => holeOf(s) === n);
        expect(got.length).toBe(want.length);
        got.forEach((s, i) => expect(s).toBe(want[i])); // the recorded objects themselves
        const card = scorecardAfter(mixed.shots, course, mixed.shots.length).find((c) => c.hole === n)!;
        expect([card.strokes, card.holed]).toEqual([
          sourceCard(picks.get(n)!, n).strokes,
          sourceCard(picks.get(n)!, n).holed,
        ]);
      }
      mixed.shots.forEach((shot, k) => {
        const before = SessionState.parse(showcaseState(mixed, course, k, "before"));
        const after = SessionState.parse(showcaseState(mixed, course, k, "after"));
        expect(before.ball).toEqual(shot.initial_state.ball);
        expect(after.round_seed).toBe(runs.get(picks.get(holeOf(shot))!)!.round.seed);
      });
      const final = showcaseState(mixed, course, mixed.shots.length - 1, "after");
      expect(final.round_complete).toBe(true);
      expect(final.totals?.strokes).toBe(
        holes.reduce((a, n) => a + (sourceCard(picks.get(n)!, n).strokes ?? 0), 0),
      );
    });
  }

  it("refuses a hole its run does not have", () => {
    const [id] = runs.keys();
    expect(() => mixRound(runs, new Map([[99, id]]))).toThrow();
    expect(() => mixRound(runs, new Map([[1, "not-loaded"]]))).toThrow();
  });
});

/**
 * The course growing to 18 holes. Until the showcase is re-recorded the committed data is the front
 * nine only, so these tests build an 18-hole course (the front nine again as holes 10-18, marked
 * back nine / dusk) and 18-hole rounds (one recorded front nine, then another recorded front nine
 * played again as the back nine), and mix them with the old nine-hole rounds.
 */
describe("18 holes", () => {
  const BACK = 9;
  const runs = index.runs.map((e) => ShowcaseRun.parse(load(e.file)));
  const course18 = CoursePayload.parse({
    ...course,
    name: "Fly Golf National",
    version: "eighteen-v1",
    par: course.par * 2,
    holes: [
      ...course.holes,
      ...course.holes.map((h) => ({ ...h, number: h.number + BACK, nine: "back", theme: "dusk" })),
    ],
    nines: [
      { id: "front", name: "Front Nine", holes: course.holes.map((h) => h.number), par: course.par },
      {
        id: "back",
        name: "The Neuropil Nine",
        holes: course.holes.map((h) => h.number + BACK),
        par: course.par,
      },
    ],
  });
  const asBack = (shot: ShotRecord): ShotRecord => ({
    ...shot,
    hole_index: shot.hole_index + BACK,
    scenario: { ...shot.scenario, hole_number: holeOf(shot) + BACK },
    hole: shot.hole && { ...shot.hole, number: shot.hole.number + BACK },
    course: shot.course && {
      ...shot.course,
      version: "eighteen-v1",
      hole_number: shot.course.hole_number + BACK,
    },
  });
  /** An 18-hole round: `front`'s nine, then `back`'s nine played as holes 10-18. */
  const eighteen = (id: string, front: ShowcaseRun, back: ShowcaseRun): ShowcaseRun => ({
    ...front,
    id,
    course_version: "eighteen-v1",
    shots: [...front.shots, ...back.shots.map(asBack)],
    round: {
      ...front.round,
      scorecard: [
        ...front.round.scorecard,
        ...back.round.scorecard.map((c) => ({ ...c, hole: c.hole + BACK })),
      ],
    },
  });
  const trained = runs.filter(
    (r) => r.controllers_used.length === 1 && r.controllers_used[0] === "malecns-trained",
  );
  const [a, b, c] = trained;
  const full1 = eighteen("trained-eighteen-1", a, b);
  const full2 = eighteen("trained-eighteen-2", b, c);
  const pool = new Map([full1, full2, a, b, c].map((r) => [r.id, r]));
  const holes18 = course18.holes.map((h) => h.number);

  it("parses: every back-nine hole is dusk and the nines are named", () => {
    expect(course18.holes).toHaveLength(18);
    expect(course18.holes.filter((h) => h.theme === "dusk").map((h) => h.number)).toEqual(
      holes18.slice(BACK),
    );
    expect(course18.nines?.[1].name).toBe("The Neuropil Nine");
  });

  it("knows which holes a run has", () => {
    expect(holesOfRun(a)).toEqual(holes18.slice(0, BACK));
    expect(holesOfRun(full1)).toEqual(holes18);
  });

  it("draws a back-nine hole only from a round that played it", () => {
    const has = (id: string, hole: number) => holesOfRun(pool.get(id)!).includes(hole);
    for (const r of [0, 0.3, 0.6, 0.999]) {
      const picks = drawHoles(holes18, [...pool.keys()], () => r, has);
      expect([...picks.keys()]).toEqual(holes18);
      for (const [hole, id] of picks) expect(has(id, hole)).toBe(true);
    }
    // with only front-nine rounds, the back nine is not drawn at all
    const frontOnly = drawHoles(holes18, [a.id, b.id], () => 0.5, has);
    expect([...frontOnly.keys()]).toEqual(holes18.slice(0, BACK));
  });

  it("an 18-hole mix of old and new rounds: 18 real holes, the card adds up, the round completes", () => {
    const has = (id: string, hole: number) => holesOfRun(pool.get(id)!).includes(hole);
    let r = 0;
    const picks = drawHoles(holes18, [...pool.keys()], () => (r = (r + 0.37) % 1), has);
    const mixed = mixRound(pool, picks);
    expect(new Set(mixed.holeSources.map((s) => s.run)).size).toBeGreaterThan(1);
    expect(mixed.round.scorecard.map((e) => e.hole)).toEqual(holes18);
    expect([...holeStarts(mixed.shots).keys()]).toEqual(holes18);
    const final = SessionState.parse(showcaseState(mixed, course18, mixed.shots.length - 1, "after"));
    expect(final.scorecard).toHaveLength(18);
    expect(final.round_complete).toBe(true);
    expect(final.course?.nines).toHaveLength(2);
    const want = holes18.reduce(
      (sum, n) => sum + (pool.get(picks.get(n)!)!.round.scorecard.find((e) => e.hole === n)?.strokes ?? 0),
      0,
    );
    expect(final.totals?.strokes).toBe(want);
    expect(mixed.round.strokes).toBe(want);
    const turn = holeStarts(mixed.shots).get(10)!;
    const atTurn = showcaseState(mixed, course18, turn, "before");
    expect(atTurn.scorecard?.filter((e) => e.strokes !== null).map((e) => e.hole)).toEqual(
      holes18.slice(0, BACK),
    );
    expect(atTurn.round_complete).toBe(false);
  });

  it("an old front-nine round shown with the 18-hole course is still a nine-hole round", () => {
    const last = showcaseState(a, course18, a.shots.length - 1, "after");
    expect(last.scorecard?.map((e) => e.hole)).toEqual(holes18.slice(0, BACK));
    expect(last.round_complete).toBe(true);
    // a mix drawn only from front-nine rounds, likewise
    const mixed = mixRound(
      pool,
      drawHoles(
        holes18,
        [a.id, b.id],
        () => 0.2,
        (id, h) => holesOfRun(pool.get(id)!).includes(h),
      ),
    );
    expect(showcaseState(mixed, course18, 0, "before").scorecard).toHaveLength(BACK);
  });

  it("a single recorded 18-hole run replays exactly (deep links)", () => {
    const card = scorecardAfter(full1.shots, course18, full1.shots.length, roundHoles(full1, course18));
    expect(card.map((e) => [e.hole, e.strokes, e.holed])).toEqual(
      full1.round.scorecard.map((e) => [e.hole, e.strokes, e.holed]),
    );
    const k = full1.shots.findIndex((s) => holeOf(s) === 12);
    const before = SessionState.parse(showcaseState(full1, course18, k, "before"));
    expect(before.hole_number).toBe(12);
    expect(before.hole?.theme).toBe("dusk");
    expect(before.ball).toEqual(full1.shots[k].initial_state.ball);
  });
});
