import { create } from "zustand";
import type { CourseHole, CoursePayload, SessionState, ShotRecord, Status } from "@fly-golf/protocol";

export type Connection = "connecting" | "open" | "closed" | "mismatch";

export interface Playback {
  record: ShotRecord;
  startedAt: number; // performance.now() ms
  replay: boolean;
}

export interface AppState {
  connection: Connection;
  connectionMessage?: string;
  status?: Status;
  session?: SessionState;
  course?: CoursePayload; // every hole's geometry + the bag (fetched once)
  shotPhase?: string; // backend phase while a shot is being computed
  playPhase: string; // animation beat of the current playback ("idle" when nothing plays)
  busy: boolean;
  controllerLoading?: string;
  error?: string;
  playback?: Playback;
  history: ShotRecord[]; // shots seen this browser session (live, not replays)
  techOpen: boolean;
  runsOpen: boolean;
  cardOpen: boolean;
  modesOpen: boolean;
  set: (patch: Partial<AppState>) => void;
  startPlayback: (record: ShotRecord, replay: boolean) => void;
  endPlayback: () => void;
  addRecord: (record: ShotRecord) => void;
}

export const useStore = create<AppState>((set) => ({
  connection: "connecting",
  playPhase: "idle",
  busy: false,
  history: [],
  techOpen: false,
  runsOpen: false,
  cardOpen: true,
  modesOpen: false,
  set: (patch) => set(patch),
  startPlayback: (record, replay) => set({ playback: { record, startedAt: performance.now(), replay } }),
  endPlayback: () => set({ playback: undefined }),
  addRecord: (record) => set((s) => ({ history: [...s.history, record].slice(-200) })),
}));

/** The shot being played back, else the latest shot of the CURRENT run (a new controller, mode or
 *  round starts with empty panels rather than showing another run's last shot). */
export const selectLastRecord = (s: AppState) => {
  if (s.playback) return s.playback.record;
  for (let i = s.history.length - 1; i >= 0; i--) {
    if (s.history[i].run_id === s.session?.run_id) return s.history[i];
  }
  return undefined;
};

/** The course hole a record (or the live session) is played on, if any. */
export function holeFor(s: AppState, record?: ShotRecord): CourseHole | null {
  const number = record ? record.course?.hole_number : s.session?.hole_number;
  if (record && record.mode !== "course") return null;
  if (!record && s.session?.mode !== "course") return null;
  if (number == null) return null;
  // Prefer the course cache: its objects are stable, so terrain is not rebuilt on every state message.
  const cached = s.course?.holes.find((h) => h.number === number);
  if (cached) return cached;
  return s.session?.hole && s.session.hole.number === number ? s.session.hole : null;
}
