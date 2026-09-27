import { playHole } from "../actions";
import { holeOf, isMixed } from "../lib/showcase";
import { IS_SHOWCASE } from "../lib/source";
import { watchHole } from "../showcase/controller";
import { useStore } from "../store";
import { yards } from "../lib/terrain";
import { cardNines, cardTotal, roundVerdict, signed, type NineBlock } from "../lib/card";
import { brainById, controllerLabel } from "./brains";

function scoreClass(strokes: number | null, par: number, holed: boolean | null): string {
  if (strokes == null) return "";
  if (holed === false) return "pickup";
  const d = strokes - par;
  return d <= -2 ? "eagle" : d === -1 ? "birdie" : d === 0 ? "par" : d === 1 ? "bogey" : "double";
}

const names = (ids: string[]) => ids.map((id) => brainById(id)?.name ?? id).join(" + ");

interface NineProps {
  block: NineBlock;
  caption?: string; // the nine's name, on an 18-hole card
  total?: ReturnType<typeof cardTotal>; // the TOTAL column, after the last nine of an 18-hole card
  current?: number;
  recordedHoles: Set<number>;
  busy: boolean;
  water: Set<number>;
  yardsOf: (hole: number) => number | undefined;
  seedOf?: (hole: number) => number | undefined;
}

const yd = (n: number | null | undefined) => (n == null ? "" : Math.round(n));

/** One nine of the card: its holes, then its OUT or IN column (and TOTAL after the back nine). */
function NineTable({
  block,
  caption,
  total,
  current,
  recordedHoles,
  busy,
  water,
  yardsOf,
  seedOf,
}: NineProps) {
  const playback = useStore((s) => s.playback);
  const card = block.entries;
  return (
    <div className={`sc-nine nine-${block.id}`}>
      {caption && <div className="sc-nine-name">{caption}</div>}
      <table>
        <thead>
          <tr>
            <th>HOLE</th>
            {card.map((c) => (
              <th key={c.hole}>
                <button
                  className={`hole-btn ${c.hole === current ? "current" : ""}`}
                  disabled={IS_SHOWCASE ? !recordedHoles.has(c.hole) : busy || !!playback}
                  title={`${IS_SHOWCASE ? "Watch" : "Play"} hole ${c.hole}${water.has(c.hole) ? " (water)" : ""}`}
                  onClick={() => void (IS_SHOWCASE ? watchHole(c.hole) : playHole(c.hole))}
                >
                  {c.hole}
                  {water.has(c.hole) && <span className="drop">●</span>}
                </button>
              </th>
            ))}
            <th className="sub">{block.label}</th>
            {total && <th className="sub">TOT</th>}
          </tr>
        </thead>
        <tbody>
          <tr className="muted">
            <td>YDS</td>
            {card.map((c) => (
              <td key={c.hole}>{yd(yardsOf(c.hole))}</td>
            ))}
            <td className="sub">{yd(block.yards)}</td>
            {total && <td className="sub">{yd(total.yards)}</td>}
          </tr>
          <tr>
            <td>PAR</td>
            {card.map((c) => (
              <td key={c.hole}>{c.par}</td>
            ))}
            <td className="sub">{block.par}</td>
            {total && <td className="sub">{total.par}</td>}
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
            <td className="sub">{block.strokes ?? ""}</td>
            {total && <td className="sub">{total.strokes ?? ""}</td>}
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
            <td className="sub" />
            {total && <td className="sub" />}
          </tr>
          {seedOf && (
            <tr className="muted">
              <td title="The recorded round (seed) each hole was drawn from">ROUND</td>
              {card.map((c) => (
                <td key={c.hole}>{seedOf(c.hole) ?? ""}</td>
              ))}
              <td className="sub" />
              {total && <td className="sub" />}
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

/** Broadcast-style scorecard. A nine-hole course (the front nine, as recorded before the back nine
 *  existed) is one row of holes with an OUT column; the 18-hole course is two nines, OUT after the
 *  ninth, IN and TOTAL after the eighteenth, side by side when there is room and stacked when there
 *  is not. Click a hole number to play it. Each hole shows which brain(s) played it, so a round with
 *  a mid-round switch is visibly mixed. */
export function Scorecard() {
  const session = useStore((s) => s.session);
  const course = useStore((s) => s.course);
  const open = useStore((s) => s.cardOpen);
  const busy = useStore((s) => s.busy);
  const recorded = useStore((s) => s.showcase?.run);
  if (!open || session?.mode !== "course" || !session.scorecard) return null;
  const recordedHoles = new Set(recorded?.shots.map(holeOf) ?? []);
  const card = session.scorecard;
  const current = session.hole_number;
  const totals = session.totals;
  const lengths = new Map(course?.holes.map((h) => [h.number, yards(h.length_m)]) ?? []);
  const yardsOf = (hole: number) => lengths.get(hole);
  const water = new Set(course?.holes.filter((h) => h.water.length).map((h) => h.number) ?? []);
  const blocks = cardNines(
    card,
    session.course?.nines ?? course?.nines,
    session.course?.holes ?? course?.holes,
    yardsOf,
  );
  const eighteen = blocks.length > 1;
  const total = cardTotal(blocks);
  const used = session.controllers_used ?? [];
  const mixed = used.length > 1;
  // a showcase mix: which recorded round each hole was drawn from
  const sources = isMixed(recorded) ? recorded.holeSources : undefined;
  const seedOf = sources ? (hole: number) => sources.find((s) => s.hole === hole)?.seed : undefined;
  const roundsUsed = new Set(sources?.map((s) => s.seed)).size;
  const verdict = roundVerdict({
    blocks,
    totals,
    complete: !!session.round_complete,
    mixedBrains: mixed ? names(used) : undefined,
    recordedRounds: sources ? roundsUsed : undefined,
  });
  const title = eighteen
    ? (session.course?.name ?? course?.name ?? "Eighteen holes").toUpperCase()
    : blocks[0].name.toUpperCase();
  return (
    <div className={`scorecard${eighteen ? " eighteen" : ""}`} aria-label="Scorecard">
      <div className="sc-title">
        {title}{" "}
        <span className="muted">
          · {used.length ? names(used) : controllerLabel(session.controller)}
          {used.length > 0 &&
            !used.includes(session.controller.id) &&
            ` · next: ${names([session.controller.id])}`}{" "}
          {sources
            ? `· holes from ${roundsUsed} recorded round${roundsUsed === 1 ? "" : "s"}`
            : `· round ${session.round_seed}`}
        </span>
        {mixed && (
          <span className="tag mixed" title="More than one brain has played this round">
            MIXED BRAINS
          </span>
        )}
      </div>
      <div className="sc-nines">
        {blocks.map((b, i) => (
          <NineTable
            key={b.id}
            block={b}
            caption={eighteen ? b.name : undefined}
            total={eighteen && i === blocks.length - 1 ? total : undefined}
            current={current}
            recordedHoles={recordedHoles}
            busy={busy}
            water={water}
            yardsOf={yardsOf}
            seedOf={seedOf}
          />
        ))}
      </div>
      {verdict && (
        <div className="sc-final">
          {verdict.lead}
          <b>{verdict.score}</b> ({signed(verdict.toPar)}){verdict.rest}
        </div>
      )}
    </div>
  );
}
