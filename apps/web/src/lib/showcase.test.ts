import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { CoursePayload, SessionState, ShowcaseIndex, ShowcaseRun } from "@fly-golf/protocol";
import {
  drawHoles,
  holeOf,
  holeStarts,
  isMixed,
  mixRound,
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
