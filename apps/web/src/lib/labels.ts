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

/** A tag for a set of holes: 18 HOLES, FRONT 9, BACK 9, HOLES a-b, or the holes themselves when
 *  they are not a range. */
export function holesTag(holes: number[]): string {
  const set = [...new Set(holes)].sort((x, y) => x - y);
  const run = (lo: number, hi: number) =>
    set.length === hi - lo + 1 && set[0] === lo && set[set.length - 1] === hi;
  if (run(1, 18)) return "18 HOLES";
  if (run(1, 9)) return "FRONT 9";
  if (run(10, 18)) return "BACK 9";
  if (set.length === 1) return `HOLE ${set[0]}`;
  if (run(set[0], set[set.length - 1])) return `HOLES ${set[0]}-${set[set.length - 1]}`;
  return set.length <= 4 ? `HOLES ${set.join(", ")}` : `${set.length} HOLES`;
}

/**
 * The run's holes as a tag (holesTag): from the round's own hole range, else the run's hole list,
 * else its scorecard. A run that lists none falls back to its course version, and to plain
 * "COURSE" while it says too little to tell (a live run before its first hole is holed out has no
 * scorecard yet).
 */
export function courseTag(run: RunLike): string | null {
  if (run.mode !== "course") return null;
  const round = (run.round ?? {}) as {
    scorecard?: { hole?: unknown }[];
    holes?: unknown;
    course_version?: unknown;
  };
  const card = numbers(Array.isArray(round.scorecard) ? round.scorecard.map((c) => c?.hole) : []);
  const listed = [numbers(round.holes), numbers(run.holes), card].find((l) => l.length);
  if (listed) return holesTag(listed);
  const version = String(run.course_version ?? round.course_version ?? "");
  const played = typeof run.holes_played === "number" ? run.holes_played : undefined;
  if (version.startsWith("front-nine") || (run.round_complete === true && played === 9)) return "FRONT 9";
  if (run.round_complete === true && played === 18) return "18 HOLES";
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
