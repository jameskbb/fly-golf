/**
 * The scorecard's arithmetic and its one-line verdict, kept out of the component so they can be
 * tested: which nines the card has, OUT / IN / TOTAL, and what the round's score means.
 *
 * Everything is derived from the scorecard entries the backend (or a recorded run) supplies. A
 * course recorded before the back nine existed has no `nines`: it is one front nine and renders
 * exactly as it always has.
 */
import type { CourseNine, ScorecardEntry } from "@fly-golf/protocol";

/** One block of the card: a nine and its subtotal column. */
export interface NineBlock {
  id: string; // "front" | "back" (or whatever the course calls it)
  name: string; // "Front Nine", "The Neuropil Nine"
  label: string; // the subtotal column: OUT for the front nine, IN for the back
  entries: ScorecardEntry[];
  par: number;
  yards: number | null; // null when a hole's length is unknown
  strokes: number | null; // strokes over the holes played so far, null if none played
  played: number;
  complete: boolean;
}

interface HoleLike {
  number: number;
  nine?: string;
}

const FRONT: Pick<CourseNine, "id" | "name"> = { id: "front", name: "Front Nine" };
const BACK: Pick<CourseNine, "id" | "name"> = { id: "back", name: "Back Nine" };

const subtotalLabel = (id: string, index: number, count: number) =>
  id === "front" ? "OUT" : id === "back" ? "IN" : count === 1 ? "OUT" : index === 0 ? "OUT" : "IN";

/**
 * The nines of a card. `nines` comes from the course (payload or session summary); without it the
 * holes' own `nine` field groups them, and without that the whole card is one front nine. Nines
 * with no entry on this card are left out (an old nine-hole run shown on the 18-hole course is a
 * front nine only); an entry no nine claims joins the last block.
 */
export function cardNines(
  card: ScorecardEntry[],
  nines?: CourseNine[] | null,
  holes?: HoleLike[] | null,
  yardsOf?: (hole: number) => number | undefined,
): NineBlock[] {
  let groups: { id: string; name: string; holes: Set<number> }[];
  if (nines?.length) {
    groups = nines.map((n) => ({ id: n.id, name: n.name, holes: new Set(n.holes) }));
  } else if (holes?.some((h) => h.nine === "back")) {
    groups = [FRONT, BACK].map((n) => ({
      ...n,
      holes: new Set(holes.filter((h) => (h.nine ?? "front") === n.id).map((h) => h.number)),
    }));
  } else {
    groups = [{ ...FRONT, holes: new Set(card.map((c) => c.hole)) }];
  }
  const buckets = groups.map((g) => ({ ...g, entries: [] as ScorecardEntry[] }));
  for (const entry of card) {
    const home = buckets.find((b) => b.holes.has(entry.hole)) ?? buckets[buckets.length - 1];
    home.entries.push(entry);
  }
  const used = buckets.filter((b) => b.entries.length);
  return used.map((b, i) => {
    const played = b.entries.filter((e) => e.strokes !== null);
    const lengths = b.entries.map((e) => yardsOf?.(e.hole));
    return {
      id: b.id,
      name: b.name,
      label: subtotalLabel(b.id, i, used.length),
      entries: b.entries,
      par: b.entries.reduce((a, e) => a + e.par, 0),
      yards: lengths.every((y) => y !== undefined) ? lengths.reduce((a, y) => a + (y ?? 0), 0) : null,
      strokes: played.length ? played.reduce((a, e) => a + (e.strokes ?? 0), 0) : null,
      played: played.length,
      complete: played.length === b.entries.length,
    };
  });
}

/** Every hole on the card: OUT + IN. */
export function cardTotal(blocks: NineBlock[]) {
  const played = blocks.reduce((a, b) => a + b.played, 0);
  const yards = blocks.every((b) => b.yards !== null) ? blocks.reduce((a, b) => a + (b.yards ?? 0), 0) : null;
  return {
    holes: blocks.reduce((a, b) => a + b.entries.length, 0),
    par: blocks.reduce((a, b) => a + b.par, 0),
    yards,
    strokes: played ? blocks.reduce((a, b) => a + (b.strokes ?? 0), 0) : null,
    played,
  };
}

/** The verdict line under the card, as "<lead><score> (<to par>)<rest>". The score is set bold. */
export interface Verdict {
  lead: string;
  score: number;
  toPar: number;
  rest: string;
}

export interface VerdictInput {
  blocks: NineBlock[];
  totals?: { strokes: number; to_par: number } | null;
  complete: boolean; // every hole on the card has been played
  mixedBrains?: string; // names of the brains, when more than one played this round
  recordedRounds?: number; // a showcase mix: how many recorded rounds its holes came from
}

export const signed = (n: number) => `${n >= 0 ? "+" : ""}${n}`;

const roundsWord = (n: number) => `${n} recorded round${n === 1 ? "" : "s"}`;

/**
 * What the round's score says, or nothing yet.
 *
 * A full 18: the real total, and whether the fly broke 100. A nine-hole course: its total and the
 * pace over eighteen (the only way to talk about 100 there). At the turn of an 18-hole round, the
 * OUT score. A round more than one brain played is never passed off as one brain's score.
 */
export function roundVerdict({
  blocks,
  totals,
  complete,
  mixedBrains,
  recordedRounds,
}: VerdictInput): Verdict | null {
  const holes = blocks.reduce((a, b) => a + b.entries.length, 0);
  const mixed = mixedBrains ? ` A mixed round (${mixedBrains}): not a score for any single brain.` : "";
  if (complete && totals) {
    const eighteen = holes >= 18;
    let rest: string;
    if (eighteen) {
      rest = "." + (mixed || (totals.strokes < 100 ? " The fly broke 100." : " The fly did not break 100."));
    } else {
      const pace = totals.strokes * 2;
      rest =
        `; on pace for ${pace} over eighteen.` +
        (mixed || (pace < 100 ? " The fly would break 100." : " Not breaking 100 yet."));
    }
    if (recordedRounds)
      rest += ` ${eighteen ? "Eighteen" : "Nine"} real recorded holes, drawn from ${roundsWord(recordedRounds)} of this brain.`;
    return { lead: "Round complete: ", score: totals.strokes, toPar: totals.to_par, rest };
  }
  const front = blocks[0];
  if (holes >= 18 && blocks.length > 1 && front.complete && front.strokes !== null) {
    return {
      lead: "At the turn: out in ",
      score: front.strokes,
      toPar: front.strokes - front.par,
      rest: "." + mixed.replace("A mixed round", "A mixed round so far"),
    };
  }
  return null;
}

export const verdictText = (v: Verdict) => `${v.lead}${v.score} (${signed(v.toPar)})${v.rest}`;
