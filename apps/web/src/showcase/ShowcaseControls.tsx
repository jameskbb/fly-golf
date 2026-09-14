import { useMemo } from "react";
import type { ShotRecord } from "@fly-golf/protocol";
import { timelineFor } from "../lib/playback";
import { holeOf, holeStarts } from "../lib/showcase";
import { useFrameClock } from "../lib/useFrameClock";
import { playbackTime, useStore } from "../store";
import { brainById, controllerLabel } from "../ui/brains";
import { Headshot } from "../ui/Headshot";
import { fmt } from "../ui/widgets";
import { loadRun, nextShot, playShot, prevShot, replayShot, seek, togglePlay, watchHole } from "./controller";

const PHASE_LABEL: Record<string, string> = {
  select: "choosing a club",
  address: "addressing the ball",
  aim: "lining up",
  backswing: "backswing",
  downswing: "downswing",
  follow: "ball in the air",
  rolling: "ball rolling",
  reaction: "reaction",
};

/** Position within the current shot's animation; drag to scrub. */
function Scrubber({ shot, stage }: { shot: ShotRecord; stage: string }) {
  const playback = useStore((s) => s.playback);
  const playPhase = useStore((s) => s.playPhase);
  const mine = playback?.record === shot ? playback : undefined;
  useFrameClock(!!mine && mine.pausedAt === undefined);
  const tl = useMemo(() => timelineFor(shot), [shot]);
  const t = mine ? Math.min(playbackTime(mine), tl.end) : stage === "after" ? tl.end : 0;
  return (
    <div className="scrub">
      <input
        type="range"
        min={0}
        max={tl.end}
        step={0.01}
        value={t}
        aria-label="Position in this shot"
        onChange={(e) => seek(Math.min(Number(e.target.value), tl.end - 0.02))}
      />
      <span className="scrub-time">
        {fmt(t, 1)} / {fmt(tl.end, 1)} s
      </span>
      <span className="scrub-phase">
        {mine?.pausedAt !== undefined ? "paused" : mine ? (PHASE_LABEL[playPhase] ?? "") : ""}
      </span>
    </div>
  );
}

export function ShowcaseControls() {
  const view = useStore((s) => s.showcase);
  const playback = useStore((s) => s.playback);
  const course = useStore((s) => s.course);
  const error = useStore((s) => s.error);
  const techOpen = useStore((s) => s.techOpen);
  const cardOpen = useStore((s) => s.cardOpen);
  const modesOpen = useStore((s) => s.modesOpen);
  const set = useStore((s) => s.set);
  const run = view?.run;
  const starts = useMemo(() => (run ? holeStarts(run.shots) : new Map<number, number>()), [run]);

  if (!view || !run) {
    return error ? (
      <div className="toast">{error}</div>
    ) : (
      <div className="controls showcase-controls">
        <span className="muted">Loading the recorded round…</span>
      </div>
    );
  }

  const shots = run.shots;
  const k = view.cursor;
  const shot = shots[k];
  const hole = holeOf(shot);
  const strokes = shots
    .map((s, i) => ({ s, i }))
    .filter(({ s }) => holeOf(s) === hole && s.hole_index === shot.hole_index);
  const last = shots.length - 1;
  const paused = !!playback && playback.pausedAt !== undefined;
  const running = (!!playback && !paused) || view.autoplay;
  const primary = running
    ? "❚❚ Pause"
    : paused
      ? "▶ Resume"
      : view.stage === "after" && k === last
        ? "↺ Watch again"
        : "▶ Play";
  const brain = brainById(shot.controller.id);
  const runs = view.index?.runs ?? [];
  const holes = course?.holes.map((h) => h.number) ?? [...starts.keys()].sort((a, b) => a - b);

  return (
    <>
      <div className="controls showcase-controls">
        <div className="controls-row">
          <button className="btn primary" onClick={togglePlay} title="Play / pause (Space)">
            {primary}
          </button>
          <button className="btn" disabled={k === 0} onClick={prevShot} title="Previous shot (←)">
            ⏮ Prev
          </button>
          <button className="btn" onClick={replayShot} title="Replay this shot (R)">
            ↺ Replay
          </button>
          <button className="btn" disabled={k >= last} onClick={nextShot} title="Next shot (→)">
            Next ⏭
          </button>
          {runs.length > 1 && (
            <select
              className="run-select"
              value={run.id}
              onChange={(e) => void loadRun(e.target.value)}
              aria-label="Recorded round"
            >
              {runs.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.title}
                </option>
              ))}
            </select>
          )}
          <button
            className={`btn ghost ${cardOpen ? "on" : ""}`}
            onClick={() => set({ cardOpen: !cardOpen })}
            title="C"
          >
            Card
          </button>
          <button
            className={`btn ghost ${techOpen ? "on" : ""}`}
            onClick={() => set({ techOpen: !techOpen, modesOpen: false })}
            title="T"
          >
            Technical
          </button>
          <button
            className={`btn ghost ${modesOpen ? "on" : ""}`}
            onClick={() => set({ modesOpen: !modesOpen, techOpen: false })}
            title="M"
          >
            What&apos;s the difference?
          </button>
        </div>
        <div className="now-playing">
          <span className="now-title">
            Hole {hole} · stroke {shot.stroke_number}
            {shot.stroke.club ? ` · ${shot.stroke.club.name}` : ""}
          </span>
          <span className="muted">
            shot {k + 1} of {shots.length}
          </span>
        </div>
        <Scrubber shot={shot} stage={view.stage} />
        <div className="shot-nav">
          <div className="seg" role="group" aria-label="Hole">
            {holes.map((n) => (
              <button
                key={n}
                className={`seg-btn ${n === hole ? "on mode" : ""}`}
                disabled={!starts.has(n)}
                onClick={() => watchHole(n)}
                title={starts.has(n) ? `Watch hole ${n}` : `Hole ${n} was not played in this run`}
              >
                {n}
              </button>
            ))}
          </div>
          <div className="stroke-chips" role="group" aria-label="Strokes on this hole">
            {strokes.map(({ s, i }) => (
              <button
                key={s.shot_id}
                className={`chip ${i === k ? "on" : ""}`}
                onClick={() => playShot(i)}
                title={`${s.stroke.club?.name ?? "stroke"} · ${s.outcome.outcome.replace(/_/g, " ")}`}
              >
                {s.stroke_number} · {s.stroke.club?.short ?? "?"}
              </button>
            ))}
          </div>
        </div>
        <div className={`recorded-brain ${brain?.tone ?? "mock"}`}>
          {brain && <Headshot persona={brain.persona.id} tone={brain.tone} />}
          <span className="brain-text">
            <span className="brain-name">{controllerLabel(shot.controller)}</span>
            <span className="brain-sub">
              <span className="brain-kicker">
                {brain?.kicker ?? shot.controller.kind.toUpperCase()} · RECORDED
              </span>{" "}
              · round seed {run.round.seed} · commit{" "}
              <span className="mono">{run.source.git.commit.slice(0, 7)}</span>
            </span>
          </span>
        </div>
      </div>
      {error && (
        <div className="toast" onClick={() => set({ error: undefined })}>
          {error}
        </div>
      )}
    </>
  );
}
