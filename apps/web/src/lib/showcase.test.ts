import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { CoursePayload, SessionState, ShowcaseIndex, ShowcaseRun } from "@fly-golf/protocol";
import {
  drawHoles,
  holeOf,
  holeStarts,
  holesOfRun,
  recordedHoles,
  resolveRunLink,
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

      it("is a complete 18-hole round whose card adds up", () => {
        const holes = course.holes.map((h) => h.number);
        expect(entry.course_version).toBe("eighteen-v1");
        expect(entry.holes).toEqual(holes);
        expect(holesOfRun(run)).toEqual(holes);
        expect(run.round.scorecard.map((e) => e.hole)).toEqual(holes);
        expect(run.round.complete).toBe(true);
        const strokes = run.round.scorecard.reduce((a, e) => a + (e.strokes ?? 0), 0);
        expect(run.round.strokes).toBe(strokes);
        expect(entry.strokes).toBe(strokes);
        expect(entry.to_par).toBe(strokes - course.par);
      });

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
 * 18 holes, and the rounds recorded before the back nine existed. The committed showcase is all
 * 18-hole rounds; old front-nine rounds (no longer committed) are rebuilt here in their old shape
 * from the front nine of committed rounds: holes 1-9 only, a nine-hole card, no hole list.
 */
describe("18 holes", () => {
  const BACK = 9;
  const course18 = course;
  const trained = index.runs
    .filter((r) => r.controllers_used.length === 1 && r.controllers_used[0] === "malecns-trained")
    .map((e) => ShowcaseRun.parse(load(e.file)));
  /** A committed round cut back to the shape of a round recorded on the front-nine course. */
  const asOld = (run: ShowcaseRun): ShowcaseRun => {
    const round = { ...run.round };
    delete round.holes;
    return {
      ...run,
      id: run.id.replace("eighteen", "front-nine"),
      course_version: "front-nine-v2",
      shots: run.shots.filter((s) => holeOf(s) <= BACK),
      round: { ...round, scorecard: run.round.scorecard.filter((c) => c.hole <= BACK) },
    };
  };
  const [full1, full2] = trained;
  const [a, b, c] = trained.slice(2, 5).map(asOld);
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

  it("a round over holes 10-18 only is a nine-hole round that completes on its range", () => {
    const back = full1.shots.filter((s) => holeOf(s) > BACK);
    const range = holes18.slice(BACK);
    const run: ShowcaseRun = {
      ...full1,
      shots: back,
      round: { ...full1.round, holes: range, scorecard: full1.round.scorecard },
    };
    expect(roundHoles(run, course18)).toEqual(range);
    const last = showcaseState(run, course18, back.length - 1, "after");
    expect(last.scorecard?.map((e) => e.hole)).toEqual(range);
    expect(last.round_complete).toBe(true);
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

describe("recordedHoles", () => {
  it("the committed rounds recorded all 18 holes, for every brain", () => {
    expect(recordedHoles(index)).toEqual(course.holes.map((h) => h.number));
    for (const b of ["mock", "malecns", "malecns-trained"]) expect(recordedHoles(index, b)).toHaveLength(18);
  });
  it("never claims more holes than the index lists", () => {
    const [entry] = index.runs;
    const nine = { ...index, runs: [{ ...entry, holes: [1, 2, 3, 4, 5, 6, 7, 8, 9], holes_played: 9 }] };
    expect(recordedHoles(nine)).toHaveLength(9);
    const old = { ...index, runs: [{ ...entry, holes: undefined, holes_played: 9 }] };
    expect(recordedHoles(old)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9]);
  });
});

describe("resolveRunLink", () => {
  it("a run in the index plays as is", () => {
    expect(resolveRunLink(index, "trained-eighteen-s07")).toEqual({ id: "trained-eighteen-s07" });
    expect(resolveRunLink(index, null)).toEqual({});
  });
  it("an old front-nine link opens its re-recorded 18-hole round, with a note", () => {
    for (const brain of ["trained", "untrained", "mock"]) {
      const link = resolveRunLink(index, `${brain}-front-nine-s07`);
      expect(link.id).toBe(`${brain}-eighteen-s07`);
      expect(link.notice).toMatch(/re-recorded as an 18-hole round/);
    }
  });
  it("any other unknown run is reported, not ignored", () => {
    for (const id of ["trained-front-nine-s99", "no-such-run"]) {
      const link = resolveRunLink(index, id);
      expect(link.id).toBeUndefined();
      expect(link.notice).toMatch(/is not available in this showcase/);
    }
  });
  it("the alias keeps shot numbers: holes 1-9 open on the same hole and stroke", () => {
    // the old round's shot 14 was hole 3, stroke 1 (Pond Hop's tee shot); so is the new round's
    const run = ShowcaseRun.parse(load("runs/trained-eighteen-s07.json"));
    expect([holeOf(run.shots[13]), run.shots[13].stroke_number]).toEqual([3, 1]);
  });
});
