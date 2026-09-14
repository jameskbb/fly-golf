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
  if (!c) return <div className="badge off">NO SESSION</div>;
  if (c.is_mock) {
    return (
      <div className="badge mock" title="Deterministic test heuristic — not the connectome">
        <span className="badge-title">MOCK CONTROLLER</span>
        <span className="badge-sub">test heuristic · not the connectome</span>
      </div>
    );
  }
  const trained = c.id === "malecns-trained";
  return (
    <div
      className={`badge ${trained ? "trained" : "live"}`}
      title={
        trained
          ? "MaleCNS connectome simulation with a readout trained from practice shots (connectome unchanged)"
          : "Simulated neural dynamics over the reconstructed MaleCNS connectome"
      }
    >
      <span className="dot" />
      <span className="badge-title">{trained ? "MaleCNS · TRAINED READOUT" : "MaleCNS LIVE"}</span>
      <span className="badge-sub">
        {fmtInt(c.neuron_count)} neurons · {fmtInt(c.edge_count)} connections
      </span>
    </div>
  );
}

export function Header() {
  const connection = useStore((s) => s.connection);
  return (
    <header className="hdr">
      <div className="brand">
        <span className="wordmark">FLY GOLF</span>
        <span className="tagline">Can a fruit fly break 100?</span>
      </div>
      <div className="hdr-right">
        <span className={`conn conn-${connection}`} title="WebSocket connection to the simulation backend">
          {connection === "open" ? "backend linked" : connection}
        </span>
        <ControllerBadge />
      </div>
    </header>
  );
}
