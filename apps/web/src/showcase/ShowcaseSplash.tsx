import { useStore } from "../store";
import { BRAINS, brainById } from "../ui/brains";
import { Headshot } from "../ui/Headshot";
import { recordedHoles, runsForBrain } from "../lib/showcase";
import { closeSplash, selectBrain } from "./controller";

const WORDS: Record<number, string> = { 9: "nine", 18: "eighteen" };
const numberWord = (n: number) => (n ? (WORDS[n] ?? String(n)) : "");

export const REPO_URL = "https://github.com/jameskbb/fly-golf";

const CLONE = `git clone ${REPO_URL}
cd fly-golf
make setup
make data   # ~1.1 GB download, then compiles
make dev    # http://localhost:5173`;

/** First screen of the web demo: what is on this page (recordings), how to run the real thing,
 *  and which brain to watch. Reopened from "About this demo". */
export function ShowcaseSplash() {
  const view = useStore((s) => s.showcase);
  const error = useStore((s) => s.error);
  if (!view || view.started) return null;
  const index = view.index;
  const current = view.run?.shots[0]?.controller.id;
  const watching = brainById(current);
  // what the recorded rounds contain, never the course's hole count: the page can only show holes
  // that were recorded
  const recorded = index ? recordedHoles(index, current) : [];
  const holeCount = numberWord(recorded.length);
  const backNine = recorded.some((n) => n > 9);

  return (
    <div className="overlay splash" role="dialog" aria-modal="true" aria-labelledby="splash-title">
      <div className="splash-card">
        <header>
          <div className="splash-word">FLY GOLF</div>
          <h2 id="splash-title">Can a fruit fly break 100?</h2>
          <p className="splash-lede">
            A simulated fruit-fly brain, running on the real wiring diagram of a male fly&apos;s nervous
            system, plays {holeCount ? `${holeCount} holes of golf` : "golf"}.{" "}
            <strong>This page shows pre-generated plays.</strong> Every shot was simulated before the page was
            built, and your browser only replays the recordings.
            {backNine &&
              " The trained fly practised only on the front nine, so the back nine, played at dusk, is ground it has never seen."}
          </p>
        </header>

        <h3 id="splash-pick">Pick a brain to watch</h3>
        <div className="splash-brains" role="radiogroup" aria-labelledby="splash-pick">
          {BRAINS.map((b) => {
            const available = !!index && runsForBrain(index, b.id).length > 0;
            const on = current === b.id;
            return (
              <button
                key={b.id}
                role="radio"
                aria-checked={on}
                className={`brain-card ${b.tone} ${on ? "on" : ""}`}
                disabled={!available}
                title={available ? undefined : "No recorded round for this brain yet"}
                onClick={() => void selectBrain(b.id)}
              >
                <Headshot persona={b.persona.id} tone={b.tone} size="lg" />
                <span className="brain-text">
                  <span className="brain-kicker">{b.kicker}</span>
                  <span className="brain-name">{b.name}</span>
                  <span className="brain-sub">{b.sub}</span>
                </span>
              </button>
            );
          })}
        </div>

        <div className="splash-compare">
          <section>
            <h3>On this page</h3>
            <p>
              Recorded rounds, one shot at a time. Each brain recorded several complete rounds, and every hole
              you watch is drawn at random from all of them, so each visit shows different holes; the page
              says which round each hole came from. Play a shot, pause it, scrub through the swing, jump to
              any hole and orbit the camera. The spikes, active neurons and motor outputs are the values
              recorded for each shot. Nothing is simulated here, so it loads in seconds.
            </p>
          </section>
          <section>
            <h3>Run it in real time</h3>
            <p>
              To watch the brain play new shots as they are computed, clone the repository and run it on your
              own computer. It downloads the full MaleCNS connectome and simulates all 166,700 neurons for
              every shot, so it needs more than 1 GB of disk (about 1.5 GB with the compiled graph) and a few
              GB of memory.
            </p>
            <pre className="splash-code">
              <code>{CLONE}</code>
            </pre>
          </section>
        </div>

        <footer className="splash-foot">
          <button className="btn primary big" disabled={!view.run} onClick={closeSplash}>
            {watching ? `Watch ${watching.persona.name}` : "Watch the round"}
          </button>
          <a href={REPO_URL}>Method, results and caveats on GitHub</a>
        </footer>
        {view.notice && (
          <p className="splash-notice" role="status">
            {view.notice}
          </p>
        )}
        {error && <p className="splash-error">{error}</p>}
        <p className="splash-honest">
          The wiring is real (MaleCNS v1.0, CC BY 4.0). The neuron dynamics are a model, and the senses and
          the swing are engineered by hand. The trained brain learns only a readout outside the connectome. On
          the front nine a readout fitted to a shuffled-wiring connectome plays better than one fitted to the
          real wiring, and a readout of the raw senses with no brain beats both; neither control has been run
          on the back nine. This is not a digital copy of a fly.
        </p>
      </div>
    </div>
  );
}
