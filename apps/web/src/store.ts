import { create } from "zustand";
import type {
  CourseHole,
  CoursePayload,
  SessionState,
  ShotRecord,
  ShowcaseIndex,
  ShowcaseRun,
  Status,
} from "@fly-golf/protocol";

export type Connection = "connecting" | "open" | "closed" | "mismatch";

export interface Playback {
  record: ShotRecord;
  id: number; // unique per started playback: replaying the same shot is a new playback
  startedAt: number; // performance.now() ms, shifted on resume and seek
  pausedAt?: number; // performance.now() ms at which the playback was paused
  replay: boolean;
}

/** Seconds into a playback's timeline (frozen while it is paused). */
export const playbackTime = (pb: Playback, now = performance.now()) =>
  ((pb.pausedAt ?? now) - pb.startedAt) / 1000;

/** The static showcase (GitHub Pages): which recorded run is on screen and where we are in it. */
export interface ShowcaseView {
  index?: ShowcaseIndex;
  run?: ShowcaseRun;
  cursor: number; // index into run.shots
  stage: "before" | "playing" | "after"; // relative to the shot at `cursor`
  playId?: number; // the playback started for the shot at `cursor`
  started: boolean; // the splash screen has been dismissed
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
  showcase?: ShowcaseView; // showcase builds only
  techOpen: boolean;
  runsOpen: boolean;
  cardOpen: boolean;
  modesOpen: boolean;
  firingOpen: boolean; // the "Brain firing" view (ui/BrainFiring.tsx)
  set: (patch: Partial<AppState>) => void;
  startPlayback: (record: ShotRecord, replay: boolean) => void;
  endPlayback: () => void;
  pausePlayback: () => void;
  resumePlayback: () => void;
  seekPlayback: (seconds: number) => void;
  addRecord: (record: ShotRecord) => void;
}

let nextPlaybackId = 0;

export const useStore = create<AppState>((set) => ({
  connection: "connecting",
  playPhase: "idle",
  busy: false,
  history: [],
  techOpen: false,
  runsOpen: false,
  cardOpen: true,
  modesOpen: false,
  firingOpen: false,
  set: (patch) => set(patch),
  startPlayback: (record, replay) =>
    set({ playback: { record, replay, id: ++nextPlaybackId, startedAt: performance.now() } }),
  endPlayback: () => set({ playback: undefined }),
  pausePlayback: () =>
    set((s) =>
      s.playback && s.playback.pausedAt === undefined
        ? { playback: { ...s.playback, pausedAt: performance.now() } }
        : {},
    ),
  resumePlayback: () =>
    set((s) => {
      const pb = s.playback;
      if (!pb || pb.pausedAt === undefined) return {};
      return {
        playback: { ...pb, startedAt: pb.startedAt + (performance.now() - pb.pausedAt), pausedAt: undefined },
      };
    }),
  seekPlayback: (seconds) =>
    set((s) => {
      const pb = s.playback;
      if (!pb) return {};
      const now = performance.now();
      return {
        playback: {
          ...pb,
          startedAt: now - Math.max(0, seconds) * 1000,
          pausedAt: pb.pausedAt === undefined ? undefined : now,
        },
      };
    }),
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
