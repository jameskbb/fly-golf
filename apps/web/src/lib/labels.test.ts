import { describe, expect, it } from "vitest";
import { benchLabel, benchText, courseModeLabel, courseTag, holesTag } from "./labels";

describe("courseTag", () => {
  const card = (from: number, to: number) =>
    Array.from({ length: to - from + 1 }, (_, i) => ({ hole: from + i }));
  it("practice runs have no course tag", () => {
    expect(courseTag({ mode: "practice" })).toBeNull();
  });
  it("tags by the round's holes", () => {
    expect(courseTag({ mode: "course", round: { scorecard: card(1, 18) } })).toBe("18 HOLES");
    expect(courseTag({ mode: "course", round: { scorecard: card(1, 9) } })).toBe("FRONT 9");
    expect(courseTag({ mode: "course", round: { scorecard: card(10, 18) } })).toBe("BACK 9");
    expect(courseTag({ mode: "course", round: { holes: [10, 11, 12, 13, 14, 15, 16, 17, 18] } })).toBe(
      "BACK 9",
    );
    expect(courseTag({ mode: "course", holes: [1, 2, 3, 4, 5] })).toBe("HOLES 1-5");
    expect(courseTag({ mode: "course", holes: [12] })).toBe("HOLE 12");
  });
  it("prefers the round's own range to the holes played so far", () => {
    expect(
      courseTag({ mode: "course", holes: [10, 11], round: { holes: card(10, 18).map((c) => c.hole) } }),
    ).toBe("BACK 9");
  });
  it("without a hole list: the course version, a complete round's size, else COURSE", () => {
    expect(courseTag({ mode: "course", course_version: "front-nine-v2" })).toBe("FRONT 9");
    expect(courseTag({ mode: "course", holes_played: 9, round_complete: true })).toBe("FRONT 9");
    expect(courseTag({ mode: "course", holes_played: 18, round_complete: true })).toBe("18 HOLES");
    expect(courseTag({ mode: "course" })).toBe("COURSE");
    expect(courseTag({ mode: "course", round: null, holes_played: 3 })).toBe("COURSE");
  });
});

describe("holesTag", () => {
  it("names whole nines, the full round and other ranges", () => {
    expect(holesTag(card18())).toBe("18 HOLES");
    expect(holesTag([3, 1, 2, 4, 5, 6, 7, 8, 9])).toBe("FRONT 9");
    expect(holesTag([1, 3, 8])).toBe("HOLES 1, 3, 8");
    expect(holesTag([1, 3, 5, 7, 9])).toBe("5 HOLES");
  });
});
const card18 = () => Array.from({ length: 18 }, (_, i) => i + 1);

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
