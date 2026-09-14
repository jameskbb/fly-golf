import { useStore } from "../store";
import { dismissLanding, startRound } from "./controller";

export const REPO_URL = "https://github.com/jameskbb/fly-golf";

/** What a first-time visitor sees: what this is, that it is recorded, and one button to start. */
export function ShowcaseLanding() {
  const view = useStore((s) => s.showcase);
  const error = useStore((s) => s.error);
  if (!view || view.started) return null;
  const run = view.run;
  const mock = run?.shots.filter((s) => s.controller.is_mock).length ?? 0;
  const tag =
    !run || mock === 0
      ? "RECORDED MALECNS RUN"
      : mock === run.shots.length
        ? "RECORDED MOCK RUN"
        : "RECORDED · MIXED BRAINS";
  const holes = run ? new Set(run.shots.map((s) => s.course?.hole_number)).size : 0;
  const recorded = run?.source.created_utc?.slice(0, 10);
  return (
    <div className="overlay landing">
      <div className="overlay-card landing-card">
        <div className="landing-word">FLY GOLF</div>
        <div className="landing-tag">Can a fruit fly break 100?</div>
        <div className="mode-badge recorded big">{tag}</div>
        <p>
          This is an interactive replay of a real Fly Golf experiment. The neural simulation was computed
          beforehand; the 3D replay runs entirely in your browser.
        </p>
        {run && (
          <p className="landing-run">
            <b>{run.title}</b>
            <br />
            {run.description}
            <br />
            <span className="muted small">
              {holes} holes · {run.shots.length} shots
              {recorded ? ` · recorded ${recorded}` : ""} · commit{" "}
              <span className="mono">{run.source.git.commit.slice(0, 7)}</span>
            </span>
          </p>
        )}
        <div className="landing-actions">
          <button className="btn primary big" disabled={!run} onClick={startRound}>
            ▶ PLAY ROUND
          </button>
          <button className="btn" disabled={!run} onClick={dismissLanding}>
            Explore shot by shot
          </button>
        </div>
        {error && <p className="landing-error">{error}</p>}
        <p className="muted small landing-honest">
          <b>Real:</b> the MaleCNS v1.0 wiring diagram (CC BY 4.0). <b>Modelled:</b> the neuron dynamics.{" "}
          <b>Engineered:</b> how golf reaches the senses and how the swing is read out. <b>Trained:</b> an
          optional readout of descending-neuron activity, never the connectome itself. Not a digital copy of a
          fly. <a href={REPO_URL}>Source, method and caveats</a>
        </p>
      </div>
    </div>
  );
}
