/**
 * Showcase playback: steps through a recorded round with the app's normal playback. For each shot
 * the store gets the session state from just before the shot (lib/showcase.ts) and the recorded
 * ShotRecord is played exactly as a live shot result would be; when the animation ends, the state
 * from just after the shot takes over. Nothing is simulated: the records are the whole story.
 */
import { holeOf, holeStarts, showcaseState } from "../lib/showcase";
import { showcaseSource } from "../lib/showcaseSource";
import { useStore, type AppState, type ShowcaseView } from "../store";

const BETWEEN_SHOTS_MS = 1200;
const BETWEEN_HOLES_MS = 2600;

let timer: number | undefined;
let subscribed = false;
let initialised: Promise<void> | undefined;

const st = () => useStore.getState();
const view = () => st().showcase;
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

function clearTimer() {
  if (timer !== undefined) window.clearTimeout(timer);
  timer = undefined;
}

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
  const k = v.cursor;
  const shots = v.run.shots;
  st().set({ session: showcaseState(v.run, course, k, "after"), showcase: { ...v, stage: "after" } });
  if (!v.autoplay) return;
  if (k + 1 >= shots.length) return setView({ autoplay: false });
  const wait = holeOf(shots[k + 1]) !== holeOf(shots[k]) ? BETWEEN_HOLES_MS : BETWEEN_SHOTS_MS;
  timer = window.setTimeout(() => {
    timer = undefined;
    if (view()?.autoplay) playShot(k + 1);
  }, wait);
}

/** Load the showcase index, the course and the featured (or linked) run. Safe to call twice. */
export function initShowcase(): () => void {
  if (!subscribed) {
    subscribed = true;
    useStore.subscribe((s, prev) => {
      if (prev.playback && !s.playback) onPlaybackEnded(prev.playback.id);
    });
  }
  initialised ??= (async () => {
    st().set({ showcase: { cursor: 0, stage: "before", autoplay: false, started: false } });
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
  return clearTimer;
}

export async function loadRun(id: string, k = 0) {
  clearTimer();
  try {
    const run = await showcaseSource.getShowcaseRun(id);
    setView({ run, autoplay: false }, { error: undefined });
    goTo(Math.min(Math.max(0, k), run.shots.length - 1));
  } catch (e) {
    st().set({ error: `Could not load recorded run "${id}": ${errorText(e)}` });
  }
}

/** Stand at shot `k`, before it is played. */
export function goTo(k: number) {
  const v = view();
  const course = st().course;
  if (!v?.run || !course || k < 0 || k >= v.run.shots.length) return;
  clearTimer();
  st().set({
    playback: undefined,
    session: showcaseState(v.run, course, k, "before"),
    history: v.run.shots.slice(0, k),
    showcase: { ...v, cursor: k, stage: "before", playId: undefined },
  });
  syncUrl();
}

/** Play recorded shot `k` from the top. */
export function playShot(k: number) {
  const v = view();
  const course = st().course;
  if (!v?.run || !course || k < 0 || k >= v.run.shots.length) return;
  clearTimer();
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

/** Play / pause. Playing carries on shot after shot until the end of the round. */
export function togglePlay() {
  const v = view();
  if (!v?.run) return;
  const pb = st().playback;
  if ((pb && pb.pausedAt === undefined) || v.autoplay) {
    clearTimer();
    st().pausePlayback();
    setView({ autoplay: false });
    return;
  }
  setView({ autoplay: true, started: true });
  if (pb && pb.pausedAt !== undefined) return st().resumePlayback();
  const last = v.run.shots.length - 1;
  if (v.stage === "after") playShot(v.cursor >= last ? 0 : v.cursor + 1);
  else playShot(v.cursor);
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
    setView({ autoplay: false });
    playShot(v.cursor);
    st().pausePlayback();
  }
  st().seekPlayback(seconds);
}

/** Landing card: watch the whole round from the first tee. */
export function startRound() {
  setView({ autoplay: true, started: true });
  playShot(0);
}

/** Landing card: look around first, then play shots one at a time. */
export function dismissLanding() {
  setView({ started: true });
}
