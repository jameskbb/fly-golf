import { useEffect, useState } from "react";
import type { RunSummary, ShotRecord } from "@fly-golf/protocol";
import { api } from "../lib/api";
import { replay } from "../actions";
import { useStore } from "../store";
import { metresToFeet } from "../lib/coords";
import { fmt } from "./widgets";

export function RunsPanel() {
  const open = useStore((s) => s.runsOpen);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [shots, setShots] = useState<ShotRecord[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    api.runs().then(setRuns, (e) => setErr(String(e)));
  }, [open]);

  useEffect(() => {
    if (!selected) return;
    api.run(selected).then(
      (d) => setShots(d.shots),
      (e) => setErr(String(e)),
    );
  }, [selected]);

  if (!open) return null;
  return (
    <div className="drawer">
      <div className="drawer-head">
        <span>Recorded runs</span>
        <button className="btn ghost small" onClick={() => useStore.getState().set({ runsOpen: false })}>
          close
        </button>
      </div>
      {err && <p className="muted small">{err}</p>}
      <ul className="runs">
        {runs.map((r) => (
          <li
            key={r.run_id}
            className={selected === r.run_id ? "on" : ""}
            onClick={() => setSelected(r.run_id)}
          >
            <span
              className={`tag ${r.controller?.id === "malecns-trained" ? "trained" : r.controller?.is_mock === false ? "live" : "mock"}`}
            >
              {r.controller?.id === "malecns-trained"
                ? "TRAINED"
                : r.controller?.is_mock === false
                  ? "MaleCNS"
                  : "MOCK"}
            </span>
            {Array.isArray(r.controllers_used) && r.controllers_used.length > 1 && (
              <span className="tag mixed" title={`Brains: ${r.controllers_used.join(", ")}`}>
                MIXED
              </span>
            )}
            {r.mode === "course" && <span className="tag course">FRONT 9</span>}
            <span className="mono">{r.run_id}</span>
            <span className="muted">
              {r.shots} shots · {r.holed} holed
            </span>
          </li>
        ))}
        {!runs.length && <li className="muted">No runs recorded yet.</li>}
      </ul>
      {selected && (
        <>
          <h4>Shots</h4>
          <ul className="runs">
            {shots.map((s) => (
              <li key={s.shot_id}>
                <span className="mono">{s.shot_id}</span>
                <span className="muted">
                  {s.mode === "course"
                    ? `${s.stroke.club?.short ?? "?"} · ${Math.round(s.outcome.start_distance_m / 0.9144)} yd → ${s.outcome.outcome}`
                    : `${fmt(metresToFeet(s.outcome.start_distance_m), 1)} ft → ${s.outcome.outcome}`}
                </span>
                <button className="btn small" onClick={() => replay(s)}>
                  replay
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
