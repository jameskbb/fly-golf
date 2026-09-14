import { useStore } from "../store";
import { BRAINS } from "./brains";
import { Headshot } from "./Headshot";

interface ReadoutMeta {
  id?: string | null;
  method?: string | null;
  format?: string | null;
  git_commit?: string | null;
  test_metrics?: Record<string, { holed_pct?: number; median_leave_m?: number; penalty_pct?: number }> | null;
  bench?: { mean_strokes?: number; holes_holed_pct?: number; rounds?: number } | null;
  situations?: { train?: number; test?: number } | null;
}

const DETAIL: Record<string, { what: string[]; honest: string }> = {
  mock: {
    what: [
      "A few lines of hand-written golf logic: it reads the distance, slope and lie and looks up a club, like a caddie table.",
      "No neurons, no connectome. It exists to test the course, the physics and the renderer.",
    ],
    honest: "Never presented as the fly's brain. Every mock shot is labelled MOCK.",
  },
  malecns: {
    what: [
      "The reconstructed MaleCNS v1.0 connectome (166,700 neurons, 25.6M connections) runs as a spiking network for 400 ms per shot.",
      "The scene is injected into sensory neurons; the stroke is read from descending neurons with FIXED rules written before any shot was seen.",
    ],
    honest:
      "Untrained: it tends to blast putts and reach for the same mid iron everywhere. That is a real result.",
  },
  "malecns-trained": {
    what: [
      "Exactly the same connectome simulation and the same sensory input. Nothing inside the brain is changed.",
      "Only the READOUT is learned: linear weights that turn descending-neuron firing into a putter-or-swing decision, a club, an aim and a power.",
      "The weights come from practice: the fly tried thousands of shots in the simulator and kept what worked (see below).",
    ],
    honest:
      "Every number that reaches the body still comes from simulated neural activity, never from the golf state.",
  },
};

const STEPS: [string, string][] = [
  [
    "Practice spots",
    "Seeded situations: putts on the practice green and the course greens, chips and pitches around the greens, and full shots from tees, fairways, rough and sand. 30 % are held out and never trained on.",
  ],
  [
    "Neural response",
    "At each spot the scene is fed to the connectome and 400 ms of spiking is simulated, exactly as in play. The firing rate of every descending-neuron type (~480) is recorded.",
  ],
  [
    "Trial and error",
    "In the physics simulator the fly tries every club, swing length and aim from that spot. Each club is judged robustly (a shot that only works if perfect, with the trees a hair away, scores badly) and the shortest club that does about as well as the best is kept.",
  ],
  [
    "Fit the readout",
    "From the neural firing alone: a putter-or-swing gate, a club head and aim/power heads, each a linear layer chosen by cross-validation.",
  ],
  [
    "Calibrate by practice",
    "The fly then plays its own readout's strokes on the training spots and tunes how the club and power are decoded (a club too long flies into the trees; one too short just leaves another shot).",
  ],
  [
    "Test honestly",
    "Held-out shots, full front-nine rounds (fly-golf bench), a no-brain baseline fitted the same way on the raw senses, and a shuffled-wiring control.",
  ],
];

export function ModesPanel() {
  const open = useStore((s) => s.modesOpen);
  const session = useStore((s) => s.session);
  if (!open) return null;
  const active = session?.controller.id;
  const readout = (session?.controller.config as { readout?: ReadoutMeta } | undefined)?.readout;
  return (
    <div className="drawer modes-panel" aria-label="The three brains explained">
      <div className="drawer-head">
        <span>Mock vs MaleCNS vs Trained</span>
        <button className="btn ghost small" onClick={() => useStore.getState().set({ modesOpen: false })}>
          close
        </button>
      </div>
      <p className="muted small">
        You can switch brains at any moment, even in the middle of a hole. The next shot is played by the new
        brain, and the scorecard marks which brain played each hole, so a mixed round is never passed off as
        one brain's score.
      </p>
      {BRAINS.map((b) => (
        <section key={b.id} className={`mode-block ${b.tone} ${active === b.id ? "on" : ""}`}>
          <div className="mode-head">
            <span className={`tag ${b.tone}`}>{b.name.toUpperCase()}</span>
            <span className="brain-kicker">{b.kicker}</span>
            {active === b.id && <span className="brain-live">● ACTIVE</span>}
          </div>
          <div className="mode-body">
            <Headshot persona={b.persona.id} tone={b.tone} size="lg" />
            <div>
              <p className="mode-look">
                <b>Plays as {b.persona.name}.</b> {b.persona.look}
              </p>
              <ul>
                {DETAIL[b.id].what.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            </div>
          </div>
          <p className="mode-honest">{DETAIL[b.id].honest}</p>
        </section>
      ))}
      <h4>How the trained readout was trained</h4>
      <ol className="train-steps">
        {STEPS.map(([title, text]) => (
          <li key={title}>
            <b>{title}.</b> {text}
          </li>
        ))}
      </ol>
      {active === "malecns-trained" && readout && (
        <div className="card trained small">
          <strong>Installed readout</strong> {readout.id ?? "?"} · {readout.method ?? "?"} · trained at{" "}
          <span className="mono">{readout.git_commit?.slice(0, 7) ?? "?"}</span>
          {readout.situations?.train != null && (
            <div>
              Practised on {readout.situations.train + (readout.situations.test ?? 0)} situations (
              {readout.situations.test ?? 0} held out, never trained on).
            </div>
          )}
          {readout.bench?.mean_strokes != null && (
            <div>
              Front-nine bench: {readout.bench.mean_strokes} strokes per round on average over{" "}
              {readout.bench.rounds} rounds, {readout.bench.holes_holed_pct}% of holes holed out.
            </div>
          )}
        </div>
      )}
      <p className="muted small">
        The full method, every number and the controls are in <span className="mono">docs/TRAINING.md</span>.
      </p>
    </div>
  );
}
