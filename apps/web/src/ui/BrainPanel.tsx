import { MOTOR_CHANNELS, type Club, type ClubChain } from "@fly-golf/protocol";
import { replayWindowS } from "../lib/brainFiring";
import { IS_SHOWCASE } from "../lib/source";
import { useFrameClock } from "../lib/useFrameClock";
import { playbackTime, selectLastRecord, useStore } from "../store";
import { controllerLabel } from "./brains";
import { ClubIcon } from "./ClubIcon";
import { Meter, Sparkline, Stat, fmt, fmtInt } from "./widgets";

/** Network spikes per 10 ms bin. In the showcase the recorded bins are revealed, slowed down,
 *  while the fly chooses its club and addresses the ball (in step with the Brain firing view);
 *  the values are the recorded ones. */
function SpikeTrace({ values }: { values: number[] }) {
  const playback = useStore((s) => s.playback);
  const animated = IS_SHOWCASE && !!playback && !playback.replay;
  const revealS = playback ? replayWindowS(playback.record) : 1;
  const t = animated && playback ? playbackTime(playback) : revealS;
  useFrameClock(animated && playback?.pausedAt === undefined && t < revealS);
  const progress = animated ? Math.min(1, t / revealS) : undefined;
  return (
    <div className="spark-wrap">
      <span className="spark-caption">
        {progress !== undefined && progress < 1
          ? "replaying the recorded 400 ms of activity, slowed down"
          : "network spikes per 10 ms"}
      </span>
      <Sparkline values={values} progress={progress} />
    </div>
  );
}

const PHASE_TEXT: Record<string, string> = {
  sensing: "Encoding the green into sensory channels…",
  thinking: "Simulating 400 ms of neural activity…",
  swinging: "Decoding motor output…",
  result: "Rolling…",
};

const MOTOR_LABEL: Record<string, string> = {
  aim_left: "aim left",
  aim_right: "aim right",
  stroke_power: "power",
  stroke_tempo: "tempo",
  face_open: "face open",
  face_closed: "face closed",
  strike: "strike",
  club_reach: "club reach",
};

const CHAIN_LABEL: Record<string, string> = {
  fixed: "FIXED READOUT",
  trained: "TRAINED READOUT",
  "mock heuristic": "MOCK HEURISTIC",
};

/** Senses -> (descending-neuron activity ->) readout -> club_reach -> club, for the shot on screen. */
function ClubChainView({ chain, club }: { chain: ClubChain; club?: Club }) {
  const neural = chain.readout !== "mock heuristic";
  let decision = chain.rule ?? "";
  if (chain.readout === "trained" && chain.gate) {
    decision =
      chain.gate === "putter"
        ? `putter gate p(putt) = ${fmt(chain.p_putt ?? 0, 2)} ≥ 0.5 → putter`
        : `putter gate p(putt) = ${fmt(chain.p_putt ?? 0, 2)} < 0.5 → club head ${fmt(chain.club_head_raw ?? 0, 2)}` +
          ` → calibrated ${fmt(chain.club_head_calibrated ?? 0, 2)} → nearest club`;
  } else if (chain.readout === "mock heuristic" && chain.needed_m != null) {
    decision = `${chain.rule} (needs ${fmt(chain.needed_m, 0)} m)`;
  }
  return (
    <section>
      <h3>
        Club choice{" "}
        <span className={`chain-tag chain-${chain.readout.replace(" ", "-")}`}>
          {CHAIN_LABEL[chain.readout] ?? chain.readout}
        </span>
      </h3>
      <ol className="club-chain small">
        <li>
          <span className="chain-step">senses</span> {chain.senses ?? chain.inputs ?? "sensory channels"}
        </li>
        {neural && chain.dn_all_rate_hz != null && (
          <li>
            <span className="chain-step">DN activity</span> all descending neurons{" "}
            {fmt(chain.dn_all_rate_hz, 2)} Hz
          </li>
        )}
        <li>
          <span className="chain-step">readout</span>{" "}
          {chain.senses && chain.inputs ? `reads ${chain.inputs}: ` : ""}
          {decision}
        </li>
        <li>
          <span className="chain-step">club_reach</span> {fmt(chain.club_reach, 3)} → <ClubIcon club={club} />
          <b>{club?.name ?? chain.club}</b>
          {chain.forced_club ? " (practice green: putter only)" : ""}
        </li>
      </ol>
    </section>
  );
}

const TRAINED_CHANNELS = new Set(["aim_left", "aim_right", "stroke_power", "club_reach"]);

export function BrainPanel() {
  const session = useStore((s) => s.session);
  const busy = useStore((s) => s.busy);
  const shotPhase = useStore((s) => s.shotPhase);
  const playPhase = useStore((s) => s.playPhase);
  const playback = useStore((s) => s.playback);
  const record = useStore(selectLastRecord);
  // Attribute what is on screen to the controller that PRODUCED the shot being shown
  // (a replayed MaleCNS shot stays MaleCNS even if the live session is the mock).
  const controller = record?.controller ?? session?.controller;
  const isMock = controller?.is_mock ?? true;
  const trained = controller?.id === "malecns-trained";
  const readout = (
    controller?.config as
      | {
          readout?: {
            id?: string;
            test_metrics?: Record<string, { holed_pct: number; median_leave_m: number }>;
          };
        }
      | undefined
  )?.readout;
  const ns = record?.neural_summary ?? null;
  const pops = ns ? Object.entries(ns.populations) : [];
  const motorChannels = record
    ? (MOTOR_CHANNELS as readonly string[]).filter((c) => c in record.motor.channels)
    : [];

  let statusText = IS_SHOWCASE
    ? "Recorded run — this brain was simulated beforehand"
    : "Idle — waiting for a shot";
  if (busy) statusText = PHASE_TEXT[shotPhase ?? "thinking"] ?? "Working…";
  else if (playback?.replay) statusText = `Replaying ${playback.record.shot_id} (${playback.record.run_id})`;
  else if (playPhase !== "idle" && playPhase !== "done")
    statusText = IS_SHOWCASE
      ? `Replaying the recorded stroke · ${playPhase}`
      : `Executing stroke · ${playPhase}`;

  return (
    <aside className="brain">
      <div className="panel-title">
        BRAIN <span className="panel-title-sub">{controller ? controllerLabel(controller) : "—"}</span>
      </div>

      {isMock ? (
        <div className="card warn">
          <strong>MOCK CONTROLLER</strong>
          <p>
            A hand-written heuristic with seeded noise and a caddie&apos;s distance table for picking clubs.
            It has <b>no neurons</b> and is used only to test physics, animation and recording. Switch to
            MaleCNS for the connectome.
          </p>
        </div>
      ) : (
        <div className={`card ${trained ? "trained" : "live"}`}>
          <strong>{controller?.connectome ?? "MaleCNS v1.0"}</strong>
          <p>
            Simulated LIF dynamics over <b>{fmtInt(controller?.neuron_count)}</b> neurons and{" "}
            <b>{fmtInt(controller?.edge_count)}</b> connections of the reconstructed male fly CNS.
          </p>
          {controller?.model && (
            <p className="small">
              Neural engine <code>{controller.model}</code>
              {controller.model !== "fly-golf-lif-v1"
                ? " (legacy engine, kept for older readouts and replays)"
                : ""}
            </p>
          )}
          {trained && (
            <p>
              <b>TRAINED READOUT:</b> aim, power and club are read out of descending-neuron activity by linear
              weights fitted from practice shots. The connectome itself is unchanged.
              {readout?.test_metrics?.putt && (
                <>
                  {" "}
                  Held-out practice putts: <b>{readout.test_metrics.putt.holed_pct}%</b> holed, median leave{" "}
                  {readout.test_metrics.putt.median_leave_m} m.
                </>
              )}
            </p>
          )}
        </div>
      )}

      <div className={`status-line ${busy ? "pulse" : ""}`}>{statusText}</div>

      <section>
        <h3>
          {playback?.replay ? "Replayed decision" : IS_SHOWCASE ? "Recorded decision" : "Last decision"}
        </h3>
        {ns ? (
          <>
            <div className="stats">
              <Stat label="spikes" value={fmtInt(ns.total_spikes)} />
              <Stat
                label="active neurons"
                value={fmtInt(ns.active_neurons)}
                sub={`of ${fmtInt(ns.neuron_count)}`}
              />
              <Stat label="mean rate" value={`${fmt(ns.mean_rate_hz, 2)} Hz`} />
              <Stat
                label="neural / wall"
                value={`${fmt(ns.sim_ms, 0)} ms`}
                sub={`${fmt(ns.wall_s, 2)} s compute`}
              />
            </div>
            <SpikeTrace values={ns.bins.map((b) => b.spikes)} />
            <table className="pops">
              <thead>
                <tr>
                  <th>population</th>
                  <th>role</th>
                  <th>n</th>
                  <th>Hz</th>
                </tr>
              </thead>
              <tbody>
                {pops.map(([name, p]) => (
                  <tr key={name} className={`role-${p.role}`}>
                    <td>{name}</td>
                    <td>{p.role === "sensory" ? "in" : "out"}</td>
                    <td>{fmtInt(p.neurons)}</td>
                    <td>{fmt(p.rate_hz, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : (
          <p className="muted small">
            {record ? "No neural activity: this shot came from the mock controller." : "No shot yet."}
          </p>
        )}
      </section>

      <section>
        <h3>Motor output</h3>
        {record ? (
          <>
            {motorChannels.map((c) => (
              <Meter
                key={c}
                label={MOTOR_LABEL[c] + (trained && TRAINED_CHANNELS.has(c) ? " ·T" : "")}
                value={record.motor.channels[c]}
                tone={isMock ? "mock" : trained && TRAINED_CHANNELS.has(c) ? "trained" : "live"}
              />
            ))}
            {record.stroke.club && !record.club_chain && (
              <p className="small club-note">
                club_reach {record.motor.channels.club_reach?.toFixed(2)} →{" "}
                <ClubIcon club={record.stroke.club} />
                <b>{record.stroke.club.name}</b>
                {record.stroke.forced_club ? " (practice green: putter only)" : ""}
              </p>
            )}
          </>
        ) : (
          <p className="muted small">Channels appear after the first shot.</p>
        )}
      </section>

      {record?.club_chain && <ClubChainView chain={record.club_chain} club={record.stroke.club} />}

      <footer className="honesty">
        Real anatomical wiring (MaleCNS v1.0, CC BY 4.0). Neuron dynamics, sensory and motor mappings are
        engineered models — not a digital copy of a fly.
        {IS_SHOWCASE &&
          " Every value here was recorded when the shot was simulated; this page only replays it."}
      </footer>
    </aside>
  );
}
