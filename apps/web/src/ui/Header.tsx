import { IS_SHOWCASE } from "../lib/source";
import { useStore } from "../store";
import { fmtInt } from "./widgets";

function ControllerBadge() {
  const session = useStore((s) => s.session);
  const status = useStore((s) => s.status);
  const loading = useStore((s) => s.controllerLoading);
  if ((loading && loading !== "mock") || status?.malecns.status === "loading") {
    return (
      <div className="badge loading" title="Loading the compiled MaleCNS graph into memory">
        <span className="badge-title">LOADING MaleCNS…</span>
        <span className="badge-sub">166,700 neurons · 25.6M connections</span>
      </div>
    );
  }
  const c = session?.controller;
  if (!c) return <div className="badge off">{IS_SHOWCASE ? "LOADING RUN…" : "NO SESSION"}</div>;
  if (c.is_mock) {
    return (
      <div className="badge mock" title="Deterministic test heuristic — not the connectome">
        <span className="badge-title">MOCK CONTROLLER</span>
        <span className="badge-sub">test heuristic · not the connectome</span>
      </div>
    );
  }
  const trained = c.id === "malecns-trained";
  const recorded = IS_SHOWCASE ? " (recorded run: the simulation was computed beforehand)" : "";
  return (
    <div
      className={`badge ${trained ? "trained" : "live"}`}
      title={
        (trained
          ? "MaleCNS connectome simulation with a readout trained from practice shots (connectome unchanged)"
          : "Simulated neural dynamics over the reconstructed MaleCNS connectome") + recorded
      }
    >
      <span className="dot" />
      <span className="badge-title">
        {trained ? "MaleCNS · TRAINED READOUT" : IS_SHOWCASE ? "MaleCNS · RECORDED" : "MaleCNS LIVE"}
      </span>
      <span className="badge-sub">
        {fmtInt(c.neuron_count)} neurons · {fmtInt(c.edge_count)} connections
      </span>
    </div>
  );
}

/** What kind of data is on screen. "LIVE" appears only while the simulation backend is connected. */
function ModeBadge() {
  const connection = useStore((s) => s.connection);
  const run = useStore((s) => s.showcase?.run);
  if (IS_SHOWCASE) {
    const mock = run?.shots.filter((s) => s.controller.is_mock).length ?? 0;
    const text =
      !run || mock === 0
        ? "RECORDED MALECNS RUN"
        : mock === run.shots.length
          ? "RECORDED MOCK RUN"
          : "RECORDED · MIXED BRAINS";
    return (
      <span
        className="mode-badge recorded"
        title="An interactive replay of shots recorded earlier. No simulation runs in this page."
      >
        {text}
      </span>
    );
  }
  return (
    <span className={`conn conn-${connection}`} title="WebSocket connection to the simulation backend">
      {connection === "open" ? "LIVE SIMULATION" : `backend ${connection}`}
    </span>
  );
}

export function Header() {
  return (
    <header className="hdr">
      <div className="brand">
        <span className="wordmark">FLY GOLF</span>
        <span className="tagline">Can a fruit fly break 100?</span>
      </div>
      <div className="hdr-right">
        <ModeBadge />
        <ControllerBadge />
      </div>
    </header>
  );
}
