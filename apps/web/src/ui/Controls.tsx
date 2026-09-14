import { advance, newHole, replay, selectController, selectMode } from "../actions";
import { useStore } from "../store";
import { BRAINS } from "./brains";
import { Headshot } from "./Headshot";

export function Controls() {
  const session = useStore((s) => s.session);
  const status = useStore((s) => s.status);
  const busy = useStore((s) => s.busy);
  const playback = useStore((s) => s.playback);
  const loading = useStore((s) => s.controllerLoading);
  const history = useStore((s) => s.history);
  const error = useStore((s) => s.error);
  const techOpen = useStore((s) => s.techOpen);
  const runsOpen = useStore((s) => s.runsOpen);
  const cardOpen = useStore((s) => s.cardOpen);
  const modesOpen = useStore((s) => s.modesOpen);
  const set = useStore((s) => s.set);

  const course = (session?.mode ?? "course") === "course";
  const done = session && session.episode_state !== "ready";
  const avail = (id: string) => status?.controllers.find((c) => c.id === id);
  const malecns = avail("malecns");
  const active = session?.controller.id ?? "mock";
  const neural = session?.controller.kind === "malecns";
  const midRound = !!session && (session.strokes > 0 || (session.totals?.holes_played ?? 0) > 0);

  let label = course ? "Hit" : "Putt";
  if (busy) label = neural ? "Brain simulating…" : "Thinking…";
  else if (playback) label = playback.replay ? "Replaying…" : "Watching…";
  else if (done && course)
    label = session?.round_complete
      ? "Round complete · new round →"
      : session?.episode_state === "holed"
        ? "Holed! Next hole →"
        : "Picked up · next hole →";
  else if (done)
    label = session?.episode_state === "holed" ? "Holed! Next hole →" : "Picked up · next hole →";

  return (
    <>
      <div className="controls">
        <div className="controls-row">
          <button
            className="btn primary"
            disabled={busy || !!playback || !session || !!loading}
            onClick={advance}
            title="Space"
          >
            {label}
          </button>
          <button className="btn" disabled={busy || !!loading} onClick={() => void newHole()} title="N">
            {course ? "New round" : "New green"}
          </button>
          <button className="btn" disabled={busy || !history.length} onClick={() => replay()} title="R">
            Replay
          </button>
          <div className="seg" role="radiogroup" aria-label="Mode">
            <button
              className={`seg-btn ${course ? "on mode" : ""}`}
              disabled={busy || !!loading}
              onClick={() => !course && void selectMode("course")}
            >
              Front 9
            </button>
            <button
              className={`seg-btn ${!course ? "on mode" : ""}`}
              disabled={busy || !!loading}
              onClick={() => course && void selectMode("practice")}
            >
              Practice green
            </button>
          </div>
          {course && (
            <button
              className={`btn ghost ${cardOpen ? "on" : ""}`}
              onClick={() => set({ cardOpen: !cardOpen })}
              title="C"
            >
              Card
            </button>
          )}
          <button
            className={`btn ghost ${techOpen ? "on" : ""}`}
            onClick={() => set({ techOpen: !techOpen, runsOpen: false, modesOpen: false })}
          >
            Technical
          </button>
          <button
            className={`btn ghost ${runsOpen ? "on" : ""}`}
            onClick={() => set({ runsOpen: !runsOpen, techOpen: false, modesOpen: false })}
          >
            Runs
          </button>
        </div>
        <div className="brains-head">
          <span className="brains-title">WHO IS SWINGING?</span>
          <span className="brains-note">
            {midRound ? "Switch any time: the next shot uses the new brain." : "Pick the fly's brain."}
          </span>
          <button
            className={`btn ghost small ${modesOpen ? "on" : ""}`}
            onClick={() => set({ modesOpen: !modesOpen, techOpen: false, runsOpen: false })}
            title="M"
          >
            What's the difference?
          </button>
        </div>
        <div className="brains" role="radiogroup" aria-label="Brain">
          {BRAINS.map((b) => {
            const a = avail(b.id);
            const usable = b.id === "mock" || !!a?.available;
            const on = active === b.id;
            return (
              <button
                key={b.id}
                role="radio"
                aria-checked={on}
                className={`brain-card ${b.tone} ${on ? "on" : ""}`}
                disabled={busy || !!loading || !usable}
                title={
                  usable
                    ? `${b.sub} Plays as ${b.persona.name}.`
                    : `Unavailable. Run: ${a?.fix_command ?? "make data"}`
                }
                onClick={() => void selectController(b.id)}
              >
                <Headshot persona={b.persona.id} tone={b.tone} />
                <span className="brain-text">
                  <span className="brain-kicker">{b.kicker}</span>
                  <span className="brain-name">
                    {loading === b.id ? "Loading…" : b.name}
                    {on && <span className="brain-live">● ACTIVE</span>}
                  </span>
                  <span className="brain-sub">
                    {usable ? b.sub : `Unavailable: run ${a?.fix_command ?? "make data"}`}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      </div>
      {malecns && !malecns.available && (
        <div className="hint">
          MaleCNS unavailable — run <code>{malecns.fix_command ?? "make data"}</code> to download and compile
          the connectome.
        </div>
      )}
      {error && (
        <div className="toast" onClick={() => set({ error: undefined })}>
          {error}
        </div>
      )}
    </>
  );
}
