/**
 * Course-aware labels for recordings and benchmarks. Runs and benches made before the back nine
 * existed covered the front nine only and still say so; anything that played beyond hole 9 is an
 * 18-hole recording.
 */

interface RunLike {
  mode?: string | null;
  holes?: unknown; // hole numbers (showcase index entries)
  holes_played?: unknown;
  round_complete?: unknown;
  course_version?: unknown;
  round?: unknown; // the live backend's run.json round summary (with its scorecard)
}

const numbers = (v: unknown): number[] =>
  Array.isArray(v) ? v.filter((n): n is number => typeof n === "number") : [];

/**
 * "18 HOLES" for a round on the 18-hole course, "FRONT 9" for one recorded on the front nine, and
 * plain "COURSE" while a run says too little to tell (a live run before its first hole is holed
 * out has no scorecard yet).
 */
export function courseTag(run: RunLike): string | null {
  if (run.mode !== "course") return null;
  const round = (run.round ?? {}) as {
    scorecard?: { hole?: unknown }[];
    holes?: unknown;
    course_version?: unknown;
  };
  const card = numbers(Array.isArray(round.scorecard) ? round.scorecard.map((c) => c?.hole) : []);
  const holes = [...numbers(run.holes), ...numbers(round.holes), ...card];
  const version = String(run.course_version ?? round.course_version ?? "");
  const played = typeof run.holes_played === "number" ? run.holes_played : undefined;
  if (holes.some((n) => n > 9) || card.length >= 18 || version.startsWith("eighteen") || (played ?? 0) > 9)
    return "18 HOLES";
  if (
    card.length ||
    version.startsWith("front-nine") ||
    (run.round_complete === true && played !== undefined)
  )
    return "FRONT 9";
  return "COURSE";
}

/** The mode button: "18 holes", or "Front 9" while the course has only its front nine. */
export const courseModeLabel = (holes: number | undefined) =>
  holes !== undefined && holes <= 9 ? "Front 9" : "18 holes";

export interface Bench {
  mean_strokes?: number;
  holes_holed_pct?: number;
  rounds?: number;
  holes?: string; // "1-18" or "1-9"; absent on benches made before the back nine existed
  nines?: { front?: { mean_strokes?: number }; back?: { mean_strokes?: number } };
}

/** What the trained readout's bench covered: "Front-nine bench", "18-hole bench" or the holes. */
export function benchLabel(bench: Bench): string {
  const holes = bench.holes?.replace(/\s+/g, "");
  if (!holes || holes === "1-9") return "Front-nine bench";
  if (holes === "1-18") return "18-hole bench";
  if (holes === "10-18") return "Back-nine bench";
  return `Bench over holes ${holes}`;
}

/** The bench in one sentence, with the two nines split out when the bench reports them. */
export function benchText(bench: Bench): string {
  let text = `${benchLabel(bench)}: ${bench.mean_strokes} strokes per round on average over ${bench.rounds} rounds, ${bench.holes_holed_pct}% of holes holed out.`;
  const front = bench.nines?.front?.mean_strokes;
  const back = bench.nines?.back?.mean_strokes;
  if (front != null && back != null)
    text += ` Front nine ${front}, back nine ${back} (holes it never practised on).`;
  return text;
}
