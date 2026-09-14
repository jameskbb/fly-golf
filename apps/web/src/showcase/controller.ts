/**
 * Showcase playback: steps through a recorded round with the app's normal playback. For each shot
 * the store gets the session state from just before the shot (lib/showcase.ts) and the recorded
 * ShotRecord is played exactly as a live shot result would be; when the animation ends, the state
 * from just after the shot takes over. One shot at a time: nothing advances on its own. Nothing is
 * simulated: the records are the whole story.
 */
import type { ShowcaseIndex } from "@fly-golf/protocol";
import { holeStarts, showcaseState } from "../lib/showcase";
import { showcaseSource } from "../lib/showcaseSource";
import { useStore, type AppState, type ShowcaseView } from "../store";

let subscribed = false;
let initialised: Promise<void> | undefined;

const st = () => useStore.getState();
const view = () => st().showcase;
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

function setView(patch: Partial<ShowcaseView>, extra: Partial<AppState> = {}) {
  const v = view();
  if (v) st().set({ ...extra, showcase: { ...v, ...patch } });
}

/** Keep the address bar pointing at the shot on screen, so a refresh or a shared link returns to it. */
function syncUrl() {
  const v = view();
  if (!v?.run) return;
  const url = new URL(window.location.href);
  url.searchParams.set("run", v.run.id);
  url.searchParams.set("shot", String(v.cursor + 1));
  window.history.replaceState(null, "", url);
}

function onPlaybackEnded(id: number) {
  const v = view();
  const course = st().course;
  if (!v?.run || !course || v.stage !== "playing" || v.playId !== id) return;
  st().set({ session: showcaseState(v.run, course, v.cursor, "after"), showcase: { ...v, stage: "after" } });
}

/** The recorded round a brain played on its own, if this showcase has one. */
export function runForBrain(index: ShowcaseIndex, brainId: string): string | undefined {
  return index.runs.find((r) => r.controllers_used.length === 1 && r.controllers_used[0] === brainId)?.id;
}

/** Load the showcase index, the course and the featured (or linked) run. Safe to call twice. */
export function initShowcase() {
  if (!subscribed) {
    subscribed = true;
    useStore.subscribe((s, prev) => {
      if (prev.playback && !s.playback) onPlaybackEnded(prev.playback.id);
    });
  }
  initialised ??= (async () => {
    st().set({ showcase: { cursor: 0, stage: "before", started: false } });
    try {
      const [index, course] = await Promise.all([showcaseSource.getIndex(), showcaseSource.getCourse()]);
      st().set({ course });
      setView({ index });
      const params = new URLSearchParams(window.location.search);
      const linked = index.runs.find((r) => r.id === params.get("run"))?.id;
      const id = linked ?? index.featured ?? index.runs[0]?.id;
      if (!id) throw new Error("this showcase has no recorded runs yet");
      const shot = Number(params.get("shot"));
      await loadRun(id, Number.isInteger(shot) && shot > 0 ? shot - 1 : 0);
      if (linked) setView({ started: true }); // a shared link goes straight to its shot
    } catch (e) {
      st().set({ error: `Could not load the recorded showcase: ${errorText(e)}` });
    }
  })();
}

export async function loadRun(id: string, k = 0) {
  try {
    const run = await showcaseSource.getShowcaseRun(id);
    setView({ run }, { error: undefined });
    goTo(Math.min(Math.max(0, k), run.shots.length - 1));
  } catch (e) {
    st().set({ error: `Could not load recorded run "${id}": ${errorText(e)}` });
  }
}

/** Watch another brain: its recorded round starts over from the first tee. */
export async function selectBrain(brainId: string) {
  const v = view();
  const id = v?.index ? runForBrain(v.index, brainId) : undefined;
  if (id && id !== v?.run?.id) await loadRun(id, 0);
}

/** Stand at shot `k`, before it is played. */
export function goTo(k: number) {
  const v = view();
  const course = st().course;
  if (!v?.run || !course || k < 0 || k >= v.run.shots.length) return;
  st().set({
    playback: undefined,
    session: showcaseState(v.run, course, k, "before"),
    history: v.run.shots.slice(0, k),
    showcase: { ...v, cursor: k, stage: "before", playId: undefined },
  });
  syncUrl();
}

/** Play recorded shot `k` from the top. It stops when the ball does. */
export function playShot(k: number) {
  const v = view();
  const course = st().course;
  if (!v?.run || !course || k < 0 || k >= v.run.shots.length) return;
  const shots = v.run.shots;
  st().set({
    playback: undefined,
    session: showcaseState(v.run, course, k, "before"),
    history: shots.slice(0, k + 1),
    showcase: { ...v, cursor: k, stage: "playing", playId: undefined, started: true },
  });
  st().startPlayback(shots[k], false);
  setView({ playId: st().playback?.id });
  syncUrl();
}

/** The main button: play the shot on screen, pause or resume it, then move on when asked. */
export function primaryAction() {
  const v = view();
  if (!v?.run) return;
  const pb = st().playback;
  if (pb) return pb.pausedAt === undefined ? st().pausePlayback() : st().resumePlayback();
  if (v.stage !== "after") return playShot(v.cursor);
  if (v.cursor >= v.run.shots.length - 1) return goTo(0);
  playShot(v.cursor + 1);
}

export const nextShot = () => {
  const v = view();
  if (v?.run && v.cursor < v.run.shots.length - 1) playShot(v.cursor + 1);
};
export const prevShot = () => {
  const v = view();
  if (v?.run && v.cursor > 0) playShot(v.cursor - 1);
};
export const replayShot = () => {
  const v = view();
  if (v?.run) playShot(v.cursor);
};

/** Watch a hole from its first recorded stroke. */
export function watchHole(number: number) {
  const run = view()?.run;
  const k = run ? holeStarts(run.shots).get(number) : undefined;
  if (k !== undefined) playShot(k);
}

/** Jump to `seconds` into the current shot's animation (starting it, paused, if needed). */
export function seek(seconds: number) {
  const v = view();
  if (!v?.run) return;
  const pb = st().playback;
  if (!pb || pb.record !== v.run.shots[v.cursor]) {
    playShot(v.cursor);
    st().pausePlayback();
  }
  st().seekPlayback(seconds);
}

export const openSplash = () => setView({ started: false });
export const closeSplash = () => setView({ started: true });
