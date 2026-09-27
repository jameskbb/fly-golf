import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { CoursePayload, CourseSummary, SessionState, ShowcaseRunSummary } from "../src";

const here = dirname(fileURLToPath(import.meta.url));
const showcase = join(here, "../../../apps/web/public/showcase");
const load = (path: string) => JSON.parse(readFileSync(join(showcase, path), "utf8"));

/** The committed course: all 18 holes, as the simulator sends it. */
const committed = load("course.json");
const index = load("index.json");

/** The same course in the shape recorded before the back nine existed: the front nine only, no
 *  `nine`, no `theme`, no `nines`. No file of that shape is committed any more, so it is built here. */
function oldFrontNine() {
  const holes = committed.holes.slice(0, 9).map((h: Record<string, unknown>) => {
    const { nine: _nine, theme: _theme, ...rest } = h;
    return rest;
  });
  const { nines: _nines, ...rest } = committed;
  return { ...rest, name: "Fly Golf Front Nine", version: "front-nine-v2", par: 36, holes };
}

describe("committed course", () => {
  it("is the 18-hole course with its two named nines", () => {
    const c = CoursePayload.parse(committed);
    expect(c.version).toBe("eighteen-v1");
    expect(c.par).toBe(72);
    expect(c.holes.map((h) => h.number)).toEqual(Array.from({ length: 18 }, (_, i) => i + 1));
    expect(c.nines?.map((n) => [n.id, n.name, n.holes.length, n.par])).toEqual([
      ["front", "Front Nine", 9, 36],
      ["back", "The Neuropil Nine", 9, 36],
    ]);
    for (const h of c.holes) {
      expect(h.nine).toBe(h.number <= 9 ? "front" : "back");
      expect(h.theme).toBe(h.number <= 9 ? "parkland" : "dusk");
    }
    for (const n of c.nines!)
      expect(n.par).toBe(c.holes.filter((h) => n.holes.includes(h.number)).reduce((a, h) => a + h.par, 0));
  });

  it("really varies the corridor width per hole", () => {
    const widths = CoursePayload.parse(committed).holes.map((h) => h.corridor_half_width_m);
    expect(new Set(widths).size).toBeGreaterThan(1);
  });

  it("carries the nines on the course summary inside session state", () => {
    const summary = CourseSummary.parse({ ...committed, clubs: undefined });
    const run = load(index.runs[0].file);
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
      scorecard: run.round.scorecard,
      totals: { strokes: 0, par_played: 0, to_par: 0, holes_played: 0 },
    });
    expect(state.scorecard).toHaveLength(18);
    expect(state.course?.nines?.[1].name).toBe("The Neuropil Nine");
  });

  it("index entries list their holes and course version", () => {
    for (const raw of index.runs) {
      const entry = ShowcaseRunSummary.parse(raw);
      expect(entry.course_version).toBe("eighteen-v1");
      expect(entry.holes).toHaveLength(entry.holes_played);
    }
  });
});

describe("backward compatibility with records made before the back nine", () => {
  it("an old front-nine course reads as front nine, parkland, with no nines", () => {
    const c = CoursePayload.parse(oldFrontNine());
    expect(c.holes).toHaveLength(9);
    expect(c.nines).toBeUndefined();
    for (const h of c.holes) {
      expect(h.nine).toBe("front");
      expect(h.theme).toBe("parkland");
    }
  });

  it("keeps an unknown theme as data instead of rejecting the course", () => {
    const raw = structuredClone(committed);
    raw.holes[17].theme = "links";
    expect(CoursePayload.parse(raw).holes[17].theme).toBe("links");
  });

  it("rejects an unknown nine", () => {
    const raw = structuredClone(committed);
    raw.holes[17].nine = "middle";
    expect(() => CoursePayload.parse(raw)).toThrow();
  });

  it("an old index entry (no holes, no course version) still reads", () => {
    const { holes: _h, course_version: _v, ...old } = index.runs[0];
    const entry = ShowcaseRunSummary.parse({ ...old, holes_played: 9 });
    expect(entry.holes).toBeUndefined();
    expect(entry.course_version).toBeUndefined();
  });
});
