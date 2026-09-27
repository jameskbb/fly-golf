import { describe, expect, it } from "vitest";
import { benchLabel, benchText, courseModeLabel, courseTag } from "./labels";

describe("courseTag", () => {
  it("practice runs have no course tag", () => {
    expect(courseTag({ mode: "practice" })).toBeNull();
  });
  it("a round recorded on the front nine still says FRONT 9", () => {
    expect(courseTag({ mode: "course" })).toBe("FRONT 9");
    expect(courseTag({ mode: "course", holes_played: 9 })).toBe("FRONT 9");
    const card = Array.from({ length: 9 }, (_, i) => ({ hole: i + 1 }));
    expect(courseTag({ mode: "course", round: { scorecard: card } })).toBe("FRONT 9");
  });
  it("an 18-hole round says 18 HOLES", () => {
    const card = Array.from({ length: 18 }, (_, i) => ({ hole: i + 1 }));
    expect(courseTag({ mode: "course", round: { scorecard: card } })).toBe("18 HOLES");
    expect(courseTag({ mode: "course", holes: [1, 2, 10] })).toBe("18 HOLES");
    expect(courseTag({ mode: "course", holes_played: 18 })).toBe("18 HOLES");
    expect(courseTag({ mode: "course", course_version: "eighteen-v1" })).toBe("18 HOLES");
  });
});

describe("courseModeLabel", () => {
  it("names the course the mode button plays", () => {
    expect(courseModeLabel(18)).toBe("18 holes");
    expect(courseModeLabel(undefined)).toBe("18 holes");
    expect(courseModeLabel(9)).toBe("Front 9");
  });
});

describe("bench labels", () => {
  it("an old bench (no holes field) is the front-nine bench", () => {
    expect(benchLabel({ mean_strokes: 50.5, rounds: 10 })).toBe("Front-nine bench");
    expect(benchLabel({ holes: "1-9" })).toBe("Front-nine bench");
  });
  it("an 18-hole bench, split by nine when reported", () => {
    expect(benchLabel({ holes: "1-18" })).toBe("18-hole bench");
    expect(benchLabel({ holes: "4-6" })).toBe("Bench over holes 4-6");
    expect(
      benchText({
        holes: "1-18",
        mean_strokes: 101.2,
        rounds: 10,
        holes_holed_pct: 91,
        nines: { front: { mean_strokes: 50.1 }, back: { mean_strokes: 51.1 } },
      }),
    ).toBe(
      "18-hole bench: 101.2 strokes per round on average over 10 rounds, 91% of holes holed out. Front nine 50.1, back nine 51.1 (holes it never practised on).",
    );
  });
});
