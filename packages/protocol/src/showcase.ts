/**
 * Static showcase format (mirrors services/sim/src/fly_golf/experiments/showcase.py).
 *
 * A showcase is a set of previously recorded Fly Golf runs, exported by
 * `fly-golf export-showcase` into apps/web/public/showcase/, that the web app replays without the
 * backend (GitHub Pages). Every shot is a recorded ShotRecord: nothing in a showcase is computed
 * in the browser.
 *
 *   index.json         ShowcaseIndex: the available runs
 *   course.json        CoursePayload: the course geometry and the bag, shared by every run
 *   runs/<id>.json     ShowcaseRun: one exported round
 */
import { z } from "zod";
import { ControllerInfo, ScorecardEntry, ShotRecord } from "./schemas";

export const SHOWCASE_FORMAT = "fly-golf-showcase";
export const SHOWCASE_VERSION = 1;

const Slug = z.string().regex(/^[a-z0-9][a-z0-9-]{0,63}$/);

export const ShowcaseRunSummary = z.looseObject({
  id: Slug,
  title: z.string(),
  description: z.string(),
  file: z.string(), // relative to index.json
  controller: ControllerInfo, // the brain that played; label "MIXED BRAINS" if more than one did
  controllers_used: z.array(z.string()),
  is_mock: z.boolean(), // true if ANY shot came from the mock controller
  mode: z.literal("course"),
  shots: z.number().int(),
  holed: z.number().int(), // holes finished in the cup
  holes_played: z.number().int(),
  strokes: z.number().int(),
  to_par: z.number().int(),
  round_complete: z.boolean(),
  round_seed: z.number().int(),
  source_run_id: z.string(),
  recorded_utc: z.string().nullish(),
  git_commit: z.string(),
});
export type ShowcaseRunSummary = z.infer<typeof ShowcaseRunSummary>;

export const ShowcaseIndex = z.object({
  format: z.literal(SHOWCASE_FORMAT),
  version: z.literal(SHOWCASE_VERSION),
  course: z.string(), // relative to index.json
  featured: z.string().nullish(),
  runs: z.array(ShowcaseRunSummary),
});
export type ShowcaseIndex = z.infer<typeof ShowcaseIndex>;

export const ShowcaseRound = z.looseObject({
  seed: z.number().int(),
  complete: z.boolean(),
  scorecard: z.array(ScorecardEntry),
  strokes: z.number().int(),
  par_played: z.number().int(),
  to_par: z.number().int(),
  holes_played: z.number().int(),
  controllers_used: z.array(z.string()),
});

export const ShowcaseRun = z.looseObject({
  format: z.literal(SHOWCASE_FORMAT),
  version: z.literal(SHOWCASE_VERSION),
  id: Slug,
  title: z.string(),
  description: z.string(),
  source: z.looseObject({
    run_id: z.string(),
    experiment_id: z.string().nullish(),
    created_utc: z.string().nullish(),
    git: z.looseObject({ commit: z.string(), dirty: z.boolean().nullable() }),
    versions: z.record(z.string(), z.union([z.string(), z.number()])),
  }),
  controller: ControllerInfo,
  controllers_used: z.array(z.string()),
  course_version: z.string(),
  round: ShowcaseRound,
  export: z.looseObject({ exporter: z.string(), exported_utc: z.string(), notes: z.array(z.string()) }),
  shots: z.array(ShotRecord).min(1),
});
export type ShowcaseRun = z.infer<typeof ShowcaseRun>;
