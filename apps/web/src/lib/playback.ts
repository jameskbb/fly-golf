import type { ShotRecord } from "@fly-golf/protocol";
import { trajectoryDuration } from "./coords";
import { buildTimeline, type Timeline } from "./swing";

/** The animation timeline of a recorded shot: the same one the 3D fly and ball play. */
export function timelineFor(record: ShotRecord): Timeline {
  return buildTimeline(record.stroke, trajectoryDuration(record.trajectory.points), record.outcome.holed, {
    select: record.mode === "course",
  });
}
