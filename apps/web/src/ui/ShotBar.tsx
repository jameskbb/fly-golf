import type { ShotRecord } from "@fly-golf/protocol";
import { selectLastRecord, useStore } from "../store";
import { metresToFeet } from "../lib/coords";
import { distanceLabel } from "../lib/terrain";
import { controllerLabel } from "./brains";
import { ClubIcon } from "./ClubIcon";
import { fmt } from "./widgets";

type Out = ShotRecord["outcome"];

export function resultText(o: Out): string {
  if (o.outcome === "holed") return "HOLED";
  if (o.outcome === "no_contact") return "WHIFF";
  if (o.outcome === "off_green") return "OFF THE GREEN";
  if (o.outcome === "water") return "WATER · +1";
  if (o.outcome === "out_of_bounds") return "IN THE TREES · +1";
  const lie = o.lie_after as string | undefined;
  if (lie) return `${distanceLabel(o.final_distance_m, lie === "green" || lie === "fringe")} · ${lie}`;
  const ft = metresToFeet(o.final_distance_m);
  const side = o.miss_side === "center" ? "" : ` ${o.miss_side}`;
  return `${fmt(ft, 1)} ft${side}${o.lip_outs ? " · lipped out" : ""}`;
}

export function scoreName(strokes: number, par: number): string {
  const d = strokes - par;
  if (strokes === 1) return "ACE";
  return (
    (
      { [-3]: "ALBATROSS", [-2]: "EAGLE", [-1]: "BIRDIE", 0: "PAR", 1: "BOGEY", 2: "DOUBLE" } as Record<
        number,
        string
      >
    )[d] ?? `+${d}`
  );
}

const toPar = (n: number) => (n === 0 ? "E" : n > 0 ? `+${n}` : `${n}`);

export function ShotBar() {
  const session = useStore((s) => s.session);
  const record = useStore(selectLastRecord);
  const playPhase = useStore((s) => s.playPhase);
  const playback = useStore((s) => s.playback);
  const reveal = !playback || playPhase === "reaction" || playPhase === "done";
  const chosen = playback && playPhase !== "select" ? playback.record : !playback ? record : undefined;

  // During a replay every cell describes the replayed shot's hole, not the live one.
  const replayRec = playback?.replay ? playback.record : undefined;
  const course = replayRec ? replayRec.mode === "course" : session?.mode === "course";
  const sc = replayRec ? replayRec.scenario : session?.scenario;
  const ballPos = replayRec ? replayRec.initial_state.ball : session?.ball;
  const toCup = sc && ballPos ? Math.hypot(ballPos[0] - sc.cup[0], ballPos[1] - sc.cup[1]) : 0;
  const stats = session?.stats ?? {};
  const aim = record?.stroke.start_offset_deg ?? 0;

  if (course) {
    const holeInfo =
      replayRec?.hole ??
      (session?.hole
        ? { number: session.hole.number, name: session.hole.name, par: session.hole.par }
        : undefined);
    const lie = (replayRec ? (replayRec.initial_state.lie as string) : session?.lie) ?? "tee";
    const onGreen = lie === "green" || lie === "fringe";
    const totals = session?.totals;
    const inCup = !replayRec && session?.episode_state === "holed";
    return (
      <div className="shotbar">
        <div className="cell hole">
          <span className="k">HOLE {holeInfo?.number ?? "—"}</span>
          <span className="v">PAR {holeInfo?.par ?? "—"}</span>
          <span className="s">{holeInfo?.name ?? ""}</span>
        </div>
        <div className="cell">
          <span className="k">TO PIN</span>
          <span className="v">{inCup ? "IN" : distanceLabel(toCup, onGreen)}</span>
          <span className="s">lie · {inCup ? "cup" : lie}</span>
        </div>
        <div className="cell club">
          <span className="k">CLUB</span>
          <span className="v">
            {chosen?.stroke.club ? (
              <>
                <ClubIcon club={chosen.stroke.club} />
                {chosen.stroke.club.name}
              </>
            ) : playback ? (
              "choosing…"
            ) : (
              "—"
            )}
          </span>
          <span className="s">
            {chosen?.stroke.club_reach != null
              ? `club_reach ${fmt(chosen.stroke.club_reach, 2)}`
              : "picked by the fly"}
          </span>
        </div>
        <div className="cell">
          <span className="k">AIM</span>
          <span className="v">{record ? `${fmt(Math.abs(aim), 1)}° ${aim >= 0 ? "L" : "R"}` : "—"}</span>
          <span className="s">off body line</span>
        </div>
        <div className="cell">
          <span className="k">SWING</span>
          <span className="v">
            {record ? `${Math.round((record.stroke.swing_fraction ?? record.stroke.power) * 100)}%` : "—"}
          </span>
          <span className="s">{record ? `${fmt(record.stroke.speed_mps, 1)} m/s ball` : ""}</span>
        </div>
        <div
          className={`cell result ${reveal && record?.outcome.holed ? "holed" : ""} ${reveal && record && ["water", "out_of_bounds"].includes(record.outcome.outcome) ? "penalty" : ""}`}
        >
          <span className="k">RESULT {record && playback?.replay ? "· REPLAY" : ""}</span>
          <span className="v">{record ? (reveal ? resultText(record.outcome) : "…") : "—"}</span>
          <span className="s">
            {record ? `${controllerLabel(record.controller)} · ${record.shot_id}` : ""}
          </span>
        </div>
        <div className="cell">
          <span className="k">STROKES</span>
          <span className="v">{session?.strokes ?? 0}</span>
          <span className="s">
            {session?.episode_state === "picked_up"
              ? "picked up"
              : session?.episode_state === "holed" && holeInfo
                ? scoreName(session.strokes, holeInfo.par)
                : "this hole"}
          </span>
        </div>
        <div className="cell">
          <span className="k">SCORE</span>
          <span className="v">{totals ? toPar(totals.to_par) : "—"}</span>
          <span className="s">{totals ? `${totals.strokes} thru ${totals.holes_played}` : ""}</span>
        </div>
      </div>
    );
  }

  const slope = sc ? Math.hypot(sc.green.slope_x, sc.green.slope_y) * 100 : 0;
  const holeNo = replayRec ? replayRec.hole_index + 1 : session ? session.hole_index + 1 : null;
  const avg = stats.holes_completed ? (stats.strokes ?? 0) / Math.max(1, stats.holes) : null;
  return (
    <div className="shotbar">
      <div className="cell hole">
        <span className="k">GREEN</span>
        <span className="v">{holeNo ?? "—"}</span>
        <span className="s">seed {sc?.seed ?? "—"}</span>
      </div>
      <div className="cell">
        <span className="k">TO CUP</span>
        <span className="v">
          {!replayRec && session?.episode_state === "holed" ? "IN" : `${fmt(metresToFeet(toCup), 1)} ft`}
        </span>
        <span className="s">{fmt(toCup, 2)} m</span>
      </div>
      <div className="cell">
        <span className="k">SPEED</span>
        <span className="v">{fmt(sc?.green.stimp_ft, 1)}</span>
        <span className="s">stimp · slope {fmt(slope, 1)}%</span>
      </div>
      <div className="cell">
        <span className="k">AIM</span>
        <span className="v">{record ? `${fmt(Math.abs(aim), 1)}° ${aim >= 0 ? "L" : "R"}` : "—"}</span>
        <span className="s">off body line</span>
      </div>
      <div className="cell">
        <span className="k">POWER</span>
        <span className="v">{record ? `${Math.round(record.stroke.power * 100)}%` : "—"}</span>
        <span className="s">{record ? `${fmt(record.stroke.speed_mps, 2)} m/s` : ""}</span>
      </div>
      <div className={`cell result ${reveal && record?.outcome.holed ? "holed" : ""}`}>
        <span className="k">RESULT {record && playback?.replay ? "· REPLAY" : ""}</span>
        <span className="v">{record ? (reveal ? resultText(record.outcome) : "…") : "—"}</span>
        <span className="s">{record ? `${controllerLabel(record.controller)} · ${record.shot_id}` : ""}</span>
      </div>
      <div className="cell">
        <span className="k">STROKES</span>
        <span className="v">{session?.strokes ?? 0}</span>
        <span className="s">{session?.episode_state === "picked_up" ? "picked up" : "this green"}</span>
      </div>
      <div className="cell">
        <span className="k">CARD</span>
        <span className="v">
          {stats.holed ?? 0}/{stats.holes_completed ?? 0}
        </span>
        <span className="s">holed · {avg ? `${fmt(avg, 1)} putts/green` : "none finished"}</span>
      </div>
    </div>
  );
}
