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
  type Extra = { brain?: string; mixedBrains?: string; recordedRounds?: number };
  const verdict = (c: ScorecardEntry[], extra: Extra = {}) => {
    const v = roundVerdict({
      blocks: cardNines(c, c.length > 9 ? NINES : undefined),
      totals: totalsOf(c),
      complete: c.every((e) => e.strokes !== null),
      ...extra,
    });
    return v && verdictText(v);
  };
  const bogeys = (h: number) => PARS[h - 1] + 1; // 90 over 18, 45 over 9
  const doubles = (h: number) => PARS[h - 1] + 2; // 108 over 18, 54 over 9
  const MOCK = { brain: "mock" };
  const WILD = { brain: "malecns" };
  const TRAINED = { brain: "malecns-trained" };

  describe("after 18 holes: the real total, no doubling", () => {
    it("the mock is the reference, never the fly", () => {
      expect(verdict(card(18, 18, bogeys), MOCK)).toBe(
        "Round complete: 90 (+18). The mock controller broke 100. It has no neurons: this is the reference, not the fly.",
      );
      expect(verdict(card(18, 18, doubles), MOCK)).toBe(
        "Round complete: 108 (+36). The mock controller did not break 100. It has no neurons: this is the reference, not the fly.",
      );
    });
    it("the untrained fly", () => {
      expect(verdict(card(18, 18, bogeys), WILD)).toBe(
        "Round complete: 90 (+18). The untrained fly broke 100.",
      );
      expect(verdict(card(18, 18, doubles), WILD)).toBe(
        "Round complete: 108 (+36). The untrained fly did not break 100.",
      );
    });
    it("the trained fly, which never practised on the back nine", () => {
      expect(verdict(card(18, 18, bogeys), TRAINED)).toBe(
        "Round complete: 90 (+18). The trained fly broke 100. The back nine is ground it never practised on.",
      );
      expect(verdict(card(18, 18, doubles), TRAINED)).toBe(
        "Round complete: 108 (+36). The trained fly did not break 100. The back nine is ground it never practised on.",
      );
    });
    it("exactly 100 does not break 100", () => {
      const c = card(18, 18, (h) => (h <= 10 ? 6 : 5));
      expect(totalsOf(c).strokes).toBe(100);
      expect(verdict(c, WILD)).toMatch(/did not break 100\.$/);
    });
    it("an unknown brain is not called the fly", () => {
      expect(verdict(card(18, 18, bogeys))).toBe("Round complete: 90 (+18). This brain broke 100.");
    });
    it("never mentions a pace", () => {
      for (const b of [MOCK, WILD, TRAINED]) expect(verdict(card(18, 18, doubles), b)).not.toMatch(/pace/);
    });
  });

  describe("a nine-hole course keeps the pace over eighteen", () => {
    it("names who is on pace", () => {
      expect(verdict(card(9, 9, bogeys), MOCK)).toBe(
        "Round complete: 45 (+9); on pace for 90 over eighteen. The mock controller would break 100 at this pace. It has no neurons: this is the reference, not the fly.",
      );
      expect(verdict(card(9, 9, bogeys), WILD)).toBe(
        "Round complete: 45 (+9); on pace for 90 over eighteen. The untrained fly would break 100 at this pace.",
      );
      expect(
        verdict(
          card(9, 9, (h) => PARS[h - 1] + 3),
          TRAINED,
        ),
      ).toBe(
        "Round complete: 63 (+27); on pace for 126 over eighteen. The trained fly is not breaking 100 yet.",
      );
    });
  });

  describe("at the turn of an 18-hole round: the OUT score, until a back-nine hole is scored", () => {
    it("names who is out", () => {
      expect(verdict(card(18, 9, bogeys), WILD)).toBe("At the turn: the untrained fly is out in 45 (+9).");
      expect(verdict(card(18, 9, bogeys), MOCK)).toBe(
        "At the turn: the mock controller is out in 45 (+9). It has no neurons: this is the reference, not the fly.",
      );
      expect(verdict(card(18, 9, bogeys), TRAINED)).toBe(
        "At the turn: the trained fly is out in 45 (+9). The back nine ahead is ground it never practised on.",
      );
    });
  });

  describe("through the back nine: the running total and the OUT score", () => {
    it("names who is playing", () => {
      expect(verdict(card(18, 12, bogeys), WILD)).toBe(
        "Through 12: the untrained fly is 60 (+12); out in 45.",
      );
      expect(verdict(card(18, 17, bogeys), MOCK)).toBe(
        "Through 17: the mock controller is 85 (+17); out in 45. It has no neurons: this is the reference, not the fly.",
      );
      expect(verdict(card(18, 14, bogeys), TRAINED)).toBe(
        "Through 14: the trained fly is 70 (+14); out in 45. The back nine is ground it never practised on.",
      );
    });
    it("keeps the mixed caveat", () => {
      expect(verdict(card(18, 10, bogeys), { mixedBrains: "Mock + Trained" })).toBe(
        "Through 10: 50 (+10); out in 45. A mixed round so far (Mock + Trained): not a score for any single brain.",
      );
    });
    it("a showcase mix is the mix, not a round", () => {
      expect(verdict(card(18, 14, bogeys), { ...TRAINED, recordedRounds: 6 })).toBe(
        "Through 14: the mix is 70 (+14); out in 45. The back nine is ground the trained fly never practised on.",
      );
      expect(verdict(card(18, 9, bogeys), { ...MOCK, recordedRounds: 6 })).toBe(
        "At the turn: the mix is out in 45 (+9). The mock controller has no neurons: this is the reference, not the fly.",
      );
    });
  });

  it("nothing to say before the turn", () => {
    expect(verdict(card(18, 5), WILD)).toBeNull();
    expect(verdict(card(9, 5), WILD)).toBeNull();
  });

  it("a mixed round is never one brain's score", () => {
    const mixedBrains = "Mock + Trained";
    expect(verdict(card(18, 18, bogeys), { mixedBrains })).toBe(
      "Round complete: 90 (+18). A mixed round (Mock + Trained): not a score for any single brain.",
    );
    expect(verdict(card(9, 9, bogeys), { mixedBrains })).toBe(
      "Round complete: 45 (+9); on pace for 90 over eighteen. A mixed round (Mock + Trained): not a score for any single brain.",
    );
    expect(verdict(card(18, 9, bogeys), { mixedBrains })).toBe(
      "At the turn: out in 45 (+9). A mixed round so far (Mock + Trained): not a score for any single brain.",
    );
  });

  describe("a showcase mix is a mix of recorded holes, not a round that was played", () => {
    it("says what the mix totals, where it came from, and the brain's caveat", () => {
      expect(verdict(card(18, 18, bogeys), { ...TRAINED, recordedRounds: 6 })).toBe(
        "Round complete: 90 (+18). This mix of recorded holes totals under 100. Eighteen real recorded holes, drawn from 6 recorded rounds of this brain. The back nine is ground the trained fly never practised on.",
      );
      expect(verdict(card(18, 18, doubles), { ...WILD, recordedRounds: 8 })).toBe(
        "Round complete: 108 (+36). This mix of recorded holes totals 100 or more. Eighteen real recorded holes, drawn from 8 recorded rounds of this brain.",
      );
      expect(verdict(card(18, 18, bogeys), { ...MOCK, recordedRounds: 1 })).toBe(
        "Round complete: 90 (+18). This mix of recorded holes totals under 100. Eighteen real recorded holes, drawn from 1 recorded round of this brain. The mock controller has no neurons: this is the reference, not the fly.",
      );
      expect(verdict(card(9, 9, bogeys), { ...WILD, recordedRounds: 3 })).toBe(
        "Round complete: 45 (+9); on pace for 90 over eighteen. This mix of recorded holes is on pace to total under 100. Nine real recorded holes, drawn from 3 recorded rounds of this brain.",
      );
    });
    it("never says a brain broke 100", () => {
      for (const b of [MOCK, WILD, TRAINED])
        for (const c of [card(18, 18, bogeys), card(18, 18, doubles)])
          expect(verdict(c, { ...b, recordedRounds: 4 })).not.toMatch(/break|broke/);
    });
    it("a single recorded run (no mix) keeps the direct verdict", () => {
      expect(verdict(card(18, 18, bogeys), TRAINED)).toMatch(/The trained fly broke 100\./);
    });
  });

  it("never writes an em dash", () => {
    for (const c of [card(18, 18), card(9, 9), card(18, 9)])
      for (const b of [MOCK, WILD, TRAINED, { mixedBrains: "A + B" }])
        expect(verdict(c, { ...b, recordedRounds: 3 })).not.toContain(String.fromCharCode(0x2014));
  });
});
