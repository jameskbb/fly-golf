import { SessionState, ShotPhase, ShotRecord } from "@fly-golf/protocol";
import { api, type ControllerId, type Mode } from "./lib/api";
import { connectSimulation } from "./lib/ws";
import { useStore } from "./store";

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

export async function refreshStatus() {
  try {
    const status = await api.status();
    useStore.getState().set({ status, session: status.session ?? useStore.getState().session });
  } catch (e) {
    useStore.getState().set({ error: `Backend unreachable: ${errorText(e)}` });
  }
}

export async function loadCourse() {
  if (useStore.getState().course) return;
  try {
    useStore.getState().set({ course: await api.course() });
  } catch (e) {
    useStore.getState().set({ error: `Could not load the course: ${errorText(e)}` });
  }
}

function handleShotResult(record: ShotRecord) {
  const s = useStore.getState();
  if (s.history.some((h) => h.shot_id === record.shot_id && h.run_id === record.run_id)) return;
  s.addRecord(record);
  s.startPlayback(record, false);
}

export function startLiveConnection(): () => void {
  const { set } = useStore.getState();
  return connectSimulation({
    onReady: () => {
      set({ connection: "open", connectionMessage: undefined });
      void refreshStatus();
      void loadCourse();
    },
    onClosed: () => {
      if (useStore.getState().connection !== "mismatch") set({ connection: "closed" });
    },
    onMismatch: (message) => set({ connection: "mismatch", connectionMessage: message }),
    onMessage: (msg) => {
      if (msg.type === "state") {
        const parsed = SessionState.safeParse(msg.data);
        if (parsed.success) set({ session: parsed.data });
      } else if (msg.type === "shot_phase") {
        const p = ShotPhase.safeParse(msg.data);
        if (p.success) set({ shotPhase: p.data.phase });
      } else if (msg.type === "shot_result") {
        const r = ShotRecord.safeParse(msg.data);
        if (r.success) handleShotResult(r.data);
      } else if (msg.type === "controller_status") {
        void refreshStatus();
      }
    },
  });
}

/** Play one stroke (putt on the practice green, any club on the course). */
export async function shot() {
  const s = useStore.getState();
  if (s.busy || s.playback || !s.session || s.session.episode_state !== "ready") return;
  s.set({ busy: true, error: undefined, shotPhase: "sensing" });
  try {
    handleShotResult(await api.shot());
  } catch (e) {
    useStore.getState().set({ error: errorText(e) });
  } finally {
    useStore.getState().set({ busy: false, shotPhase: undefined });
  }
}

async function sessionCall(call: () => Promise<SessionState>) {
  const s = useStore.getState();
  if (s.busy) return;
  s.set({ error: undefined, playback: undefined });
  try {
    useStore.getState().set({ session: await call() });
  } catch (e) {
    useStore.getState().set({ error: errorText(e) });
  }
}

/** Practice: a new random green. Course: a new round from hole 1. */
export const newHole = (seed?: number) => sessionCall(() => api.reset({ seed }));
/** Course: the next hole (a new round after the ninth). */
export const nextHole = () => sessionCall(() => api.next());
/** Course: play (or replay) a chosen hole of the current round. */
export const playHole = (hole: number) => sessionCall(() => api.reset({ hole }));

/** The main button: hit, or move on once the hole is finished. */
export function advance() {
  const s = useStore.getState().session;
  if (!s) return;
  if (s.episode_state === "ready") return void shot();
  return void (s.mode === "course" ? nextHole() : newHole());
}

async function startSession(id: ControllerId, mode: Mode) {
  const s = useStore.getState();
  if (s.busy || s.controllerLoading) return;
  s.set({ controllerLoading: id, error: undefined, playback: undefined });
  try {
    const session = await api.session(id, mode);
    useStore.getState().set({ session });
  } catch (e) {
    useStore.getState().set({ error: errorText(e) });
  } finally {
    useStore.getState().set({ controllerLoading: undefined });
    await refreshStatus();
  }
}

/** Change the brain. With a session in progress this happens in place, mid-round: the next
 *  shot is played by the new controller and the scorecard records who played each hole. */
export async function selectController(id: ControllerId) {
  const s = useStore.getState();
  if (!s.session) return startSession(id, "course");
  if (s.busy || s.controllerLoading || s.session.controller.id === id) return;
  s.set({ controllerLoading: id, error: undefined });
  try {
    const session = await api.controller(id);
    useStore.getState().set({ session });
  } catch (e) {
    useStore.getState().set({ error: errorText(e) });
  } finally {
    useStore.getState().set({ controllerLoading: undefined });
    await refreshStatus();
  }
}

export function selectMode(mode: Mode) {
  const id = (useStore.getState().session?.controller.id ?? "mock") as ControllerId;
  return startSession(id, mode);
}

export function replay(record?: ShotRecord) {
  const s = useStore.getState();
  const r = record ?? s.history[s.history.length - 1];
  if (!r || s.busy) return;
  s.startPlayback(r, true);
}
