import { CoursePayload, RunSummary, SessionState, ShotRecord, Status } from "@fly-golf/protocol";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      message = body?.detail?.message ?? body?.detail ?? message;
    } catch {
      /* non-JSON error */
    }
    throw new Error(typeof message === "string" ? message : JSON.stringify(message));
  }
  return (await res.json()) as T;
}

const post = (url: string, body?: unknown) =>
  fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export type ControllerId = "mock" | "malecns" | "malecns-trained";
export type Mode = "practice" | "course";

export const api = {
  status: async () => Status.parse(await json(await fetch("/api/status"))),
  course: async () => CoursePayload.parse(await json(await fetch("/api/course"))),
  session: async (controller: ControllerId, mode: Mode, seed?: number) =>
    SessionState.parse(await json(await post("/api/session", { controller, mode, seed }))),
  /** Swap the brain on the live session: the round, hole and ball stay where they are. */
  controller: async (controller: ControllerId) =>
    SessionState.parse(await json(await post("/api/controller", { controller }))),
  reset: async (opts: { seed?: number; hole?: number } = {}) =>
    SessionState.parse(await json(await post("/api/reset", opts))),
  next: async () => SessionState.parse(await json(await post("/api/next"))),
  shot: async () => ShotRecord.parse(await json(await post("/api/shot"))),
  runs: async () => {
    const d = await json<{ runs: unknown[] }>(await fetch("/api/runs"));
    return d.runs.map((r) => RunSummary.parse(r));
  },
  run: async (runId: string) => {
    const d = await json<{ run: Record<string, unknown>; shots: unknown[] }>(
      await fetch(`/api/runs/${encodeURIComponent(runId)}`),
    );
    return { run: d.run, shots: d.shots.map((s) => ShotRecord.parse(s)) };
  },
};
