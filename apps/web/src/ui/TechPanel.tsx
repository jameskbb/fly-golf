import { SENSORY_CHANNELS } from "@fly-golf/protocol";
import { IS_SHOWCASE } from "../lib/source";
import { selectLastRecord, useStore } from "../store";
import { Meter, fmt } from "./widgets";

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="kv">
      <span>{k}</span>
      <span>{v}</span>
    </div>
  );
}

export function TechPanel() {
  const open = useStore((s) => s.techOpen);
  const record = useStore(selectLastRecord);
  const session = useStore((s) => s.session);
  const status = useStore((s) => s.status);
  if (!open) return null;
  const ns = record?.neural_summary;
  const download = () => {
    if (!record) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(record, null, 2)], { type: "application/json" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `${record.run_id}-${record.shot_id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="drawer">
      <div className="drawer-head">
        <span>Technical</span>
        <button className="btn ghost small" onClick={() => useStore.getState().set({ techOpen: false })}>
          close
        </button>
      </div>
      <h4>Experiment</h4>
      {IS_SHOWCASE ? (
        <>
          {/* Provenance of the recorded shot itself: there is no backend in the showcase. */}
          <Row k="source" v="recorded showcase (static files)" />
          <Row k="run" v={record?.run_id ?? session?.run_id ?? "—"} />
          <Row k="controller" v={record?.controller.id ?? session?.controller.id ?? "—"} />
          <Row
            k="git"
            v={record ? `${record.git.commit.slice(0, 10)}${record.git.dirty ? " (dirty)" : ""}` : "—"}
          />
          <Row k="protocol" v={record?.versions.protocol ?? "—"} />
          <Row k="MaleCNS data" v="not loaded: every value was recorded" />
        </>
      ) : (
        <>
          <Row k="run" v={session?.run_id ?? "—"} />
          <Row k="controller" v={session?.controller.id ?? "—"} />
          <Row k="git" v={(status?.git as { commit?: string } | undefined)?.commit?.slice(0, 10) ?? "—"} />
          <Row k="protocol" v={status?.protocol_version ?? "—"} />
          <Row k="MaleCNS data" v={status?.malecns.status ?? "—"} />
        </>
      )}
      {record ? (
        <>
          <h4>Shot {record.shot_id}</h4>
          <Row k="hole seed" v={record.seed} />
          <Row k="controller seed" v={record.controller_seed} />
          <Row k="decision window" v={`${record.decision_window_ms} ms`} />
          <Row k="mode" v={record.mode} />
          {record.hole && (
            <Row k="hole" v={`${record.hole.number} · ${record.hole.name} · par ${record.hole.par}`} />
          )}
          {record.initial_state.lie != null && <Row k="lie" v={String(record.initial_state.lie)} />}
          <Row k="body heading" v={`${fmt((record.stroke.body_heading_rad * 180) / Math.PI, 1)}°`} />
          <Row k="start offset" v={`${fmt(record.stroke.start_offset_deg, 2)}°`} />
          {record.stroke.club && (
            <Row
              k="club"
              v={`${record.stroke.club.name} (reach ${fmt(record.stroke.club_reach, 3)}${record.stroke.forced_club ? ", forced" : ""})`}
            />
          )}
          <Row k="ball speed" v={`${fmt(record.stroke.speed_mps, 3)} m/s`} />
          {record.stroke.launch_effective && record.stroke.launch_effective.launch_deg > 0 && (
            <Row
              k="launch"
              v={`${fmt(record.stroke.launch_effective.launch_deg, 1)}° · ${Math.round(record.stroke.launch_effective.backspin_rpm)} rpm back · ${Math.round(record.stroke.launch_effective.sidespin_rpm)} side`}
            />
          )}
          <Row k="contact" v={String(record.stroke.contact)} />
          <Row k="outcome" v={`${record.outcome.outcome} · reward ${fmt(record.reward, 2)}`} />
          <Row
            k="sim / wall"
            v={`${fmt(record.sim_duration_s, 2)} s / ${fmt(record.wall_duration_s, 2)} s`}
          />
          <h4>Versions</h4>
          {Object.entries(record.versions).map(([k, v]) => (
            <Row key={k} k={k} v={String(v)} />
          ))}
          <h4>
            Sensory channels ({record.sensory.encoder}, {record.sensory.version})
          </h4>
          {(SENSORY_CHANNELS as readonly string[])
            .filter((c) => c in record.sensory.channels)
            .map((c) => (
              <Meter key={c} label={c.replace(/_/g, " ")} value={record.sensory.channels[c]} tone="sense" />
            ))}
          {ns && (
            <>
              <h4>Named readouts</h4>
              <table className="pops">
                <thead>
                  <tr>
                    <th>cell</th>
                    <th>side</th>
                    <th>spikes</th>
                    <th>Hz</th>
                  </tr>
                </thead>
                <tbody>
                  {ns.readouts.map((r, i) => (
                    <tr key={i}>
                      <td>{String(r.type)}</td>
                      <td>{String(r.side)}</td>
                      <td>{String(r.spikes)}</td>
                      <td>{String(r.rate_hz)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          <button className="btn small" onClick={download}>
            Download shot record (JSON)
          </button>
        </>
      ) : (
        <p className="muted small">Putt once to inspect the full record.</p>
      )}
    </div>
  );
}
