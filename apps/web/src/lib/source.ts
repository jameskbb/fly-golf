import type { CoursePayload, RunSummary, ShotRecord } from "@fly-golf/protocol";

/**
 * Where the app's data comes from.
 *
 * - `live` (default): the local app, driven by the FastAPI + WebSocket backend that runs the
 *   simulation.
 * - `showcase`: the static build for GitHub Pages. It replays runs recorded beforehand, from JSON
 *   files next to the page. There is no backend and nothing is simulated in the browser.
 *
 * The mode is fixed at build time (`vite --mode showcase`, or VITE_FLY_GOLF_MODE=showcase), never
 * guessed from the hostname.
 */
export type SourceMode = "live" | "showcase";

export const SOURCE_MODE: SourceMode =
  import.meta.env.VITE_FLY_GOLF_MODE === "showcase" ? "showcase" : "live";
export const IS_SHOWCASE = SOURCE_MODE === "showcase";

/** A static asset URL under the deployed base path (e.g. /fly-golf/ on GitHub Pages). */
export function assetUrl(path: string, base: string = import.meta.env.BASE_URL): string {
  return `${base.endsWith("/") ? base : `${base}/`}${path.replace(/^\/+/, "")}`;
}

export interface RunData {
  run: Record<string, unknown>;
  shots: ShotRecord[];
}

/** Recorded data, whichever way it arrives. Rendering and playback never depend on the origin;
 *  session control (hit, reset, switch brains) exists only live, on `api` in ./api.ts. */
export interface FlyGolfSource {
  readonly mode: SourceMode;
  getCourse(): Promise<CoursePayload>;
  getRuns(): Promise<RunSummary[]>;
  getRun(id: string): Promise<RunData>;
}
