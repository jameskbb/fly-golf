/**
 * Showcase playback: steps through a recorded round with the app's normal playback. For each shot
 * the store gets the session state from just before the shot (lib/showcase.ts) and the recorded
 * ShotRecord is played exactly as a live shot result would be; when the animation ends, the state
 * from just after the shot takes over. One shot at a time: nothing advances on its own. Nothing is
 * simulated: the records are the whole story.
 *
 * A brain's round is a mix of its recorded rounds: each hole is drawn at random from every round
 * that brain recorded (lib/showcase.ts `mixRound`), so every visit shows different holes. A link
 * to one recorded run (?run=<id>&shot=<n>) still plays that run exactly as it was recorded.
 */
import type { ShowcaseRun } from "@fly-golf/protocol";
import { drawHoles, holeStarts, isMixed, mixRound, runsForBrain, showcaseState } from "../lib/showcase";
import { showcaseSource } from "../lib/showcaseSource";
import { useStore, type AppState, type ShowcaseView } from "../store";

let subscribed = false;
let initialised: Promise<void> | undefined;

const st = () => useStore.getState();
const view = () => st().showcase;
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));
const brainOf = (run: ShowcaseRun) => run.shots[0].controller.id;

function setView(patch: Partial<ShowcaseView>, extra: Partial<AppState> = {}) {
  const v = view();
  if (v) st().set({ ...extra, showcase: { ...v, ...patch } });
}

/** Keep the address bar pointing at what is on screen. A single recorded run keeps its shot, so a
 *  refresh or a shared link returns to it; a mixed round keeps only the brain, since every visit
 *  draws a new mix. */
function syncUrl() {
  const v = view();
  if (!v?.run) return;
  const url = new URL(window.location.href);
  if (isMixed(v.run)) {
    url.searchParams.delete("run");
    url.searchParams.delete("shot");
    url.searchParams.set("brain", brainOf(v.run));
  } else {
    url.searchParams.delete("brain");
    url.searchParams.set("run", v.run.id);
    url.searchParams.set("shot", String(v.cursor + 1));
  }
  window.history.replaceState(null, "", url);
}

function onPlaybackEnded(id: number) {
  const v = view();
  const course = st().course;
  if (!v?.run || !course || v.stage !== "playing" || v.playId !== id) return;
  st().set({ session: showcaseState(v.run, course, v.cursor, "after"), showcase: { ...v, stage: "after" } });
}

/** Load the showcase index and the course, then a linked run or a mix for the featured brain.
 *  Safe to call twice. */
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
      if (linked) {
        const shot = Number(params.get("shot"));
        await loadRun(linked, Number.isInteger(shot) && shot > 0 ? shot - 1 : 0);
        setView({ started: true }); // a shared link goes straight to its shot
        return;
      }
      const featured = index.runs.find((r) => r.id === index.featured) ?? index.runs[0];
      if (!featured) throw new Error("this showcase has no recorded runs yet");
      const asked = params.get("brain");
      await selectBrain(asked && runsForBrain(index, asked).length ? asked : featured.controllers_used[0]);
    } catch (e) {
      st().set({ error: `Could not load the recorded showcase: ${errorText(e)}` });
    }
  })();
}

/** Play one recorded run exactly as it was recorded, from shot `k`. */
export async function loadRun(id: string, k = 0) {
  try {
    const run = await showcaseSource.getShowcaseRun(id);
    setView({ run }, { error: undefined });
    goTo(Math.min(Math.max(0, k), run.shots.length - 1));
  } catch (e) {
    st().set({ error: `Could not load recorded run "${id}": ${errorText(e)}` });
  }
}

/** Watch a brain: a new mix of its recorded holes, from the first tee. Only the rounds the draw
 *  picked are fetched. */
export async function selectBrain(brainId: string) {
  const v = view();
  const course = st().course;
  if (!v?.index || !course) return;
  const ids = runsForBrain(v.index, brainId).map((r) => r.id);
  if (!ids.length) return;
  const picks = drawHoles(
    course.holes.map((h) => h.number),
    ids,
  );
  try {
    const loaded = await Promise.all(
      [...new Set(picks.values())].map((id) => showcaseSource.getShowcaseRun(id)),
    );
    setView({ run: mixRound(new Map(loaded.map((r) => [r.id, r])), picks) }, { error: undefined });
    goTo(0);
  } catch (e) {
    st().set({ error: `Could not load the recorded rounds: ${errorText(e)}` });
  }
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

/** The main button: play the shot on screen, pause or resume it, then move on when asked. At the
 *  end of a mixed round it draws a new mix; a single recorded run starts over. */
export function primaryAction() {
  const v = view();
  if (!v?.run) return;
  const pb = st().playback;
  if (pb) return pb.pausedAt === undefined ? st().pausePlayback() : st().resumePlayback();
  if (v.stage !== "after") return playShot(v.cursor);
  if (v.cursor >= v.run.shots.length - 1) return isMixed(v.run) ? void selectBrain(brainOf(v.run)) : goTo(0);
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
