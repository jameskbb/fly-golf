import { describe, expect, it } from "vitest";
import type { CourseNine, ScorecardEntry } from "@fly-golf/protocol";
import { cardNines, cardTotal, roundVerdict, verdictText } from "./card";

const NINES: CourseNine[] = [
  { id: "front", name: "Front Nine", holes: [1, 2, 3, 4, 5, 6, 7, 8, 9], par: 36 },
  { id: "back", name: "The Neuropil Nine", holes: [10, 11, 12, 13, 14, 15, 16, 17, 18], par: 36 },
];
const PARS = [4, 4, 3, 5, 4, 3, 4, 5, 4, 4, 5, 3, 4, 4, 3, 5, 4, 4];

/** A card whose first `played` holes were played in `strokes(hole)`. */
function card(holes: number, played: number, strokes: (hole: number) => number = (h) => PARS[h - 1] + 1) {
  return Array.from({ length: holes }, (_, i): ScorecardEntry => ({
    hole: i + 1,
    par: PARS[i],
    strokes: i < played ? strokes(i + 1) : null,
    holed: i < played ? true : null,
  }));
}
const totalsOf = (c: ScorecardEntry[]) => {
  const played = c.filter((e) => e.strokes !== null);
  const strokes = played.reduce((a, e) => a + (e.strokes ?? 0), 0);
  return { strokes, to_par: strokes - played.reduce((a, e) => a + e.par, 0) };
};

describe("cardNines", () => {
  it("an old nine-hole card is one front nine with an OUT column", () => {
    const blocks = cardNines(card(9, 9), undefined, undefined, () => 100);
    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({ id: "front", name: "Front Nine", label: "OUT", par: 36, yards: 900 });
    expect(blocks[0].strokes).toBe(45);
  });

  it("18 holes: OUT, IN and TOTAL add up from the card", () => {
    const c = card(18, 13, (h) => h); // hole n took n strokes
    const blocks = cardNines(c, NINES, undefined, (h) => h * 10);
    expect(blocks.map((b) => [b.label, b.name, b.entries.length, b.par])).toEqual([
      ["OUT", "Front Nine", 9, 36],
      ["IN", "The Neuropil Nine", 9, 36],
    ]);
    expect(blocks[0]).toMatchObject({ strokes: 45, played: 9, complete: true, yards: 450 });
    expect(blocks[1]).toMatchObject({ strokes: 10 + 11 + 12 + 13, played: 4, complete: false, yards: 1260 });
    expect(cardTotal(blocks)).toEqual({ holes: 18, par: 72, yards: 1710, strokes: 91, played: 13 });
  });

  it("groups by the holes' own nine when the course has no nines list", () => {
    const holes = Array.from({ length: 18 }, (_, i) => ({ number: i + 1, nine: i < 9 ? "front" : "back" }));
    const blocks = cardNines(card(18, 0), null, holes);
    expect(blocks.map((b) => [b.id, b.label, b.entries.length, b.strokes])).toEqual([
      ["front", "OUT", 9, null],
      ["back", "IN", 9, null],
    ]);
  });

  it("leaves out a nine the card does not have, and has no yards if a length is unknown", () => {
    const blocks = cardNines(card(9, 2), NINES, undefined, (h) => (h === 3 ? undefined : 100));
    expect(blocks.map((b) => b.id)).toEqual(["front"]);
    expect(blocks[0].yards).toBeNull();
    expect(cardTotal(blocks).yards).toBeNull();
  });
});

describe("roundVerdict", () => {
  const verdict = (c: ScorecardEntry[], extra: { mixedBrains?: string; recordedRounds?: number } = {}) => {
    const v = roundVerdict({
      blocks: cardNines(c, c.length > 9 ? NINES : undefined),
      totals: totalsOf(c),
      complete: c.every((e) => e.strokes !== null),
      ...extra,
    });
    return v && verdictText(v);
  };

  it("after 18: the real total, broke 100", () => {
    expect(verdict(card(18, 18, (h) => PARS[h - 1] + 1))).toBe(
      "Round complete: 90 (+18). The fly broke 100.",
    );
  });

  it("after 18: did not break 100, with no doubling", () => {
    const text = verdict(card(18, 18, (h) => PARS[h - 1] + 2))!;
    expect(text).toBe("Round complete: 108 (+36). The fly did not break 100.");
    expect(text).not.toMatch(/pace/);
  });

  it("exactly 100 does not break 100", () => {
    const c = card(18, 18, (h) => (h <= 10 ? 6 : 5));
    expect(totalsOf(c).strokes).toBe(100);
    expect(verdict(c)).toMatch(/did not break 100\.$/);
  });

  it("a nine-hole course keeps the pace over eighteen", () => {
    expect(verdict(card(9, 9, (h) => PARS[h - 1] + 1))).toBe(
      "Round complete: 45 (+9); on pace for 90 over eighteen. The fly would break 100.",
    );
    expect(verdict(card(9, 9, (h) => PARS[h - 1] + 3))).toBe(
      "Round complete: 63 (+27); on pace for 126 over eighteen. Not breaking 100 yet.",
    );
  });

  it("at the turn of an 18-hole round: the OUT score", () => {
    expect(verdict(card(18, 9, (h) => PARS[h - 1] + 1))).toBe("At the turn: out in 45 (+9).");
    expect(verdict(card(18, 12, (h) => PARS[h - 1] + 1))).toBe("At the turn: out in 45 (+9).");
  });

  it("nothing to say before the turn", () => {
    expect(verdict(card(18, 5))).toBeNull();
    expect(verdict(card(9, 5))).toBeNull();
  });

  it("a mixed round is never one brain's score", () => {
    expect(verdict(card(18, 18), { mixedBrains: "Mock + Trained" })).toBe(
      "Round complete: 90 (+18). A mixed round (Mock + Trained): not a score for any single brain.",
    );
    expect(verdict(card(9, 9), { mixedBrains: "Mock + Trained" })).toBe(
      "Round complete: 45 (+9); on pace for 90 over eighteen. A mixed round (Mock + Trained): not a score for any single brain.",
    );
    expect(verdict(card(18, 9), { mixedBrains: "Mock + Trained" })).toBe(
      "At the turn: out in 45 (+9). A mixed round so far (Mock + Trained): not a score for any single brain.",
    );
  });

  it("a showcase mix says where its holes came from", () => {
    expect(verdict(card(18, 18), { recordedRounds: 7 })).toBe(
      "Round complete: 90 (+18). The fly broke 100. Eighteen real recorded holes, drawn from 7 recorded rounds of this brain.",
    );
    expect(verdict(card(9, 9), { recordedRounds: 1 })).toMatch(
      /Nine real recorded holes, drawn from 1 recorded round of this brain\.$/,
    );
  });

  it("never writes an em dash", () => {
    for (const c of [card(18, 18), card(9, 9), card(18, 9)])
      expect(verdict(c, { mixedBrains: "A + B", recordedRounds: 3 })).not.toContain(
        String.fromCharCode(0x2014),
      );
  });
});
