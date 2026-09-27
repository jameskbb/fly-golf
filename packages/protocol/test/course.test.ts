import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { CoursePayload, CourseSummary, SessionState, ShowcaseRunSummary } from "../src";

const here = dirname(fileURLToPath(import.meta.url));
const showcase = join(here, "../../../apps/web/public/showcase");
const load = (path: string) => JSON.parse(readFileSync(join(showcase, path), "utf8"));

/** The committed front-nine course: recorded before holes had `nine` or `theme`. */
const oldCourse = load("course.json");

/** An 18-hole course as the simulator sends it: the front nine plus a back nine. */
function eighteen() {
  const front = oldCourse.holes.map((h: Record<string, unknown>) => ({
    ...h,
    nine: "front",
    theme: "parkland",
  }));
  const back = oldCourse.holes.map((h: Record<string, unknown>, i: number) => ({
    ...h,
    number: 10 + i,
    nine: "back",
    theme: "dusk",
    corridor_half_width_m: 26 + i * 4,
  }));
  return {
    ...oldCourse,
    name: "Fly Golf National",
    version: "eighteen-v1",
    par: 72,
    holes: [...front, ...back],
    nines: [
      { id: "front", name: "Front Nine", holes: [1, 2, 3, 4, 5, 6, 7, 8, 9], par: 36 },
      { id: "back", name: "The Neuropil Nine", holes: [10, 11, 12, 13, 14, 15, 16, 17, 18], par: 36 },
    ],
  };
}

describe("course payload", () => {
  it("reads the old front-nine course: every hole is front nine, parkland; no nines", () => {
    const c = CoursePayload.parse(oldCourse);
    expect(c.holes).toHaveLength(9);
    expect(c.nines).toBeUndefined();
    for (const h of c.holes) {
      expect(h.nine).toBe("front");
      expect(h.theme).toBe("parkland");
    }
  });

  it("reads an 18-hole course with its nines, themes and per-hole corridor widths", () => {
    const c = CoursePayload.parse(eighteen());
    expect(c.holes).toHaveLength(18);
    expect(c.nines?.map((n) => [n.id, n.name, n.holes.length, n.par])).toEqual([
      ["front", "Front Nine", 9, 36],
      ["back", "The Neuropil Nine", 9, 36],
    ]);
    expect(c.holes[9]).toMatchObject({ number: 10, nine: "back", theme: "dusk", corridor_half_width_m: 26 });
    expect(c.holes[0]).toMatchObject({ nine: "front", theme: "parkland" });
  });

  it("keeps an unknown theme as data instead of rejecting the course", () => {
    const raw = eighteen();
    raw.holes[17].theme = "links";
    expect(CoursePayload.parse(raw).holes[17].theme).toBe("links");
  });

  it("rejects an unknown nine", () => {
    const raw = eighteen();
    raw.holes[17].nine = "middle";
    expect(() => CoursePayload.parse(raw)).toThrow();
  });

  it("carries the nines on the course summary inside session state", () => {
    const raw = eighteen();
    const summary = CourseSummary.parse({ ...raw, clubs: undefined });
    expect(summary.nines).toHaveLength(2);
    const run = load(load("index.json").runs[0].file);
    const shot = run.shots[0];
    const state = SessionState.parse({
      mode: "course",
      hole_index: 0,
      scenario: shot.scenario,
      ball: shot.initial_state.ball,
      strokes: 0,
      episode_state: "ready",
      observation: {},
      controller: shot.controller,
      stats: {},
      run_id: null,
      hole_number: 1,
      course: summary,
      scorecard: raw.holes.map((h: { number: number; par: number }) => ({
        hole: h.number,
        par: h.par,
        strokes: null,
        holed: null,
      })),
      totals: { strokes: 0, par_played: 0, to_par: 0, holes_played: 0 },
    });
    expect(state.scorecard).toHaveLength(18);
    expect(state.course?.nines?.[1].name).toBe("The Neuropil Nine");
  });

  it("reads old showcase index entries (no holes, no course version)", () => {
    const entry = ShowcaseRunSummary.parse(load("index.json").runs[0]);
    expect(entry.holes).toBeUndefined();
    expect(ShowcaseRunSummary.parse({ ...entry, holes: [1, 2, 10] }).holes).toEqual([1, 2, 10]);
  });
});
