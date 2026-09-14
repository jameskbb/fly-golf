import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { CoursePayload, SessionState, ShowcaseIndex, ShowcaseRun } from "@fly-golf/protocol";
import { holeOf, holeStarts, scorecardAfter, showcaseState } from "./showcase";
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
