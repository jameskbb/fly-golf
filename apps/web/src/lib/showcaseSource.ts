import {
  CoursePayload,
  RunSummary,
  ShowcaseIndex,
  ShowcaseRun,
  type CoursePayload as Course,
  type ShowcaseIndex as Index,
  type ShowcaseRun as Run,
} from "@fly-golf/protocol";
import { assetUrl, type FlyGolfSource, type RunData } from "./source";

/** Recorded runs served as static JSON (apps/web/public/showcase/, written by
 *  `fly-golf export-showcase`). Every file is validated against the shared protocol schemas. */
export class StaticShowcaseSource implements FlyGolfSource {
  readonly mode = "showcase" as const;
  private index?: Promise<Index>;
  private course?: Promise<Course>;
  private runs = new Map<string, Promise<Run>>();

  constructor(private readonly root = "showcase/") {}

  private async fetchJson(path: string): Promise<unknown> {
    const url = assetUrl(`${this.root}${path}`);
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${url}: ${res.status} ${res.statusText}`);
    return res.json();
  }

  getIndex(): Promise<Index> {
    this.index ??= this.fetchJson("index.json").then((d) => ShowcaseIndex.parse(d));
    return this.index;
  }

  getCourse(): Promise<Course> {
    this.course ??= this.getIndex()
      .then((index) => this.fetchJson(index.course))
      .then((d) => CoursePayload.parse(d));
    return this.course;
  }

  getShowcaseRun(id: string): Promise<Run> {
    let run = this.runs.get(id);
    if (!run) {
      run = this.getIndex().then(async (index) => {
        const entry = index.runs.find((r) => r.id === id);
        if (!entry) throw new Error(`No recorded run "${id}" in this showcase.`);
        return ShowcaseRun.parse(await this.fetchJson(entry.file));
      });
      run.catch(() => this.runs.delete(id)); // let a failed fetch be retried
      this.runs.set(id, run);
    }
    return run;
  }

  async getRuns(): Promise<RunSummary[]> {
    const index = await this.getIndex();
    return index.runs.map((r) =>
      RunSummary.parse({
        run_id: r.id,
        created_utc: r.recorded_utc,
        controller: r.controller,
        controllers_used: r.controllers_used,
        shots: r.shots,
        holed: r.holed,
        mode: r.mode,
        experiment_id: null,
      }),
    );
  }

  async getRun(id: string): Promise<RunData> {
    const { shots, ...run } = await this.getShowcaseRun(id);
    return { run, shots };
  }
}

export const showcaseSource = new StaticShowcaseSource();
