import { playHole } from "../actions";
import { useStore } from "../store";
import { yards } from "../lib/terrain";
import { brainById } from "./brains";

function scoreClass(strokes: number | null, par: number, holed: boolean | null): string {
  if (strokes == null) return "";
  if (holed === false) return "pickup";
  const d = strokes - par;
  return d <= -2 ? "eagle" : d === -1 ? "birdie" : d === 0 ? "par" : d === 1 ? "bogey" : "double";
}

const names = (ids: string[]) => ids.map((id) => brainById(id)?.name ?? id).join(" + ");

/** Broadcast-style scorecard for the front nine. Click a hole number to play it. Each hole shows
 *  which brain(s) played it, so a round with a mid-round switch is visibly mixed. */
export function Scorecard() {
  const session = useStore((s) => s.session);
  const course = useStore((s) => s.course);
  const open = useStore((s) => s.cardOpen);
  const busy = useStore((s) => s.busy);
  const playback = useStore((s) => s.playback);
  if (!open || session?.mode !== "course" || !session.scorecard) return null;
  const card = session.scorecard;
  const current = session.hole_number;
  const totals = session.totals;
  const par = card.reduce((a, c) => a + c.par, 0);
  const lengths = new Map(course?.holes.map((h) => [h.number, h.length_m]) ?? []);
  const water = new Set(course?.holes.filter((h) => h.water.length).map((h) => h.number) ?? []);
  const used = session.controllers_used ?? [];
  const mixed = used.length > 1;
  return (
    <div className="scorecard" aria-label="Scorecard">
      <div className="sc-title">
        FRONT NINE{" "}
        <span className="muted">
          · {used.length ? names(used) : session.controller.label}
          {used.length > 0 &&
            !used.includes(session.controller.id) &&
            ` · next: ${names([session.controller.id])}`}{" "}
          · round {session.round_seed}
        </span>
        {mixed && (
          <span className="tag mixed" title="More than one brain has played this round">
            MIXED BRAINS
          </span>
        )}
      </div>
      <table>
        <thead>
          <tr>
            <th>HOLE</th>
            {card.map((c) => (
              <th key={c.hole}>
                <button
                  className={`hole-btn ${c.hole === current ? "current" : ""}`}
                  disabled={busy || !!playback}
                  title={`Play hole ${c.hole}${water.has(c.hole) ? " (water)" : ""}`}
                  onClick={() => void playHole(c.hole)}
                >
                  {c.hole}
                  {water.has(c.hole) && <span className="drop">●</span>}
                </button>
              </th>
            ))}
            <th>OUT</th>
          </tr>
        </thead>
        <tbody>
          <tr className="muted">
            <td>YDS</td>
            {card.map((c) => (
              <td key={c.hole}>{lengths.has(c.hole) ? Math.round(yards(lengths.get(c.hole)!)) : ""}</td>
            ))}
            <td>{course ? Math.round(yards(course.holes.reduce((a, h) => a + h.length_m, 0))) : ""}</td>
          </tr>
          <tr>
            <td>PAR</td>
            {card.map((c) => (
              <td key={c.hole}>{c.par}</td>
            ))}
            <td>{par}</td>
          </tr>
          <tr className="fly-row">
            <td>FLY</td>
            {card.map((c) => (
              <td key={c.hole}>
                <span className={`score ${scoreClass(c.strokes, c.par, c.holed)}`}>
                  {c.strokes ?? (c.hole === current ? "·" : "")}
                </span>
              </td>
            ))}
            <td>{totals?.holes_played ? totals.strokes : ""}</td>
          </tr>
          <tr className="who-row">
            <td>BRAIN</td>
            {card.map((c) => (
              <td key={c.hole} title={c.controllers?.length ? `Played by ${names(c.controllers)}` : ""}>
                {(c.controllers ?? []).map((id) => (
                  <i key={id} className={`who tone-${brainById(id)?.tone ?? "mock"}`} />
                ))}
              </td>
            ))}
            <td />
          </tr>
        </tbody>
      </table>
      {session.round_complete && totals && (
        <div className="sc-final">
          Round complete: <b>{totals.strokes}</b> ({totals.to_par >= 0 ? "+" : ""}
          {totals.to_par}) — on pace for {totals.strokes * 2} over eighteen.{" "}
          {mixed
            ? `A mixed round (${names(used)}): not a score for any single brain.`
            : totals.strokes * 2 < 100
              ? "The fly would break 100."
              : "Not breaking 100 yet."}
        </div>
      )}
    </div>
  );
}
