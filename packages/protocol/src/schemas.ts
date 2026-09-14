/**
 * Fly Golf wire protocol (mirrors services/sim/src/fly_golf/api/schemas.py).
 *
 * Coordinates: backend world metres, +x east, +y north, +z up; headings in
 * radians counter-clockwise from +x. Render in three.js as (x, z, -y).
 */
import { z } from "zod";

/** v0.1 (putting-only) channel sets: still valid for recorded v0.1 shots. */
export const LEGACY_SENSORY_CHANNELS = [
  "target_left",
  "target_right",
  "target_distance",
  "slope_uphill",
  "slope_downhill",
  "slope_fall_left",
  "slope_fall_right",
  "green_speed",
  "ball_at_rest",
] as const;

/** v0.2: the whole course. */
export const SENSORY_CHANNELS = [
  ...LEGACY_SENSORY_CHANNELS,
  "target_far",
  "lie_green",
  "lie_rough",
  "lie_sand",
  "water_on_line",
] as const;

export const LEGACY_MOTOR_CHANNELS = [
  "aim_left",
  "aim_right",
  "stroke_power",
  "stroke_tempo",
  "face_open",
  "face_closed",
  "strike",
] as const;

/** motor-mapping-v2: + the club the fly reaches for (0 = putter … 1 = driver). */
export const MOTOR_CHANNELS = [...LEGACY_MOTOR_CHANNELS, "club_reach"] as const;

const unit = z.number().min(0).max(1);

/** A channel map whose names match exactly one known channel set. */
function channelMap(sets: readonly (readonly string[])[]) {
  return z.record(z.string(), unit).refine(
    (m) => {
      const keys = Object.keys(m).sort().join(",");
      return sets.some((s) => [...s].sort().join(",") === keys);
    },
    { message: "channel names do not match a known channel set" },
  );
}

export const MessageType = z.enum([
  "hello",
  "error",
  "state",
  "controller_status",
  "shot_phase",
  "shot_result",
]);

export const Envelope = z.object({
  type: MessageType,
  protocol_version: z.number().int(),
  seq: z.number().int().default(0),
  data: z.record(z.string(), z.unknown()).default({}),
});
export type Envelope = z.infer<typeof Envelope>;

export const ServerHello = z.looseObject({
  server: z.literal("fly-golf-sim"),
  server_version: z.string(),
  protocol_version: z.number().int(),
});

export const ClientHello = z.looseObject({
  client: z.string(),
  protocol_version: z.number().int(),
});

export const ErrorData = z.object({
  code: z.enum(["protocol_mismatch", "bad_request", "controller_unavailable", "internal"]),
  message: z.string(),
  server_protocol_version: z.number().int().nullish(),
});

export const ControllerInfo = z.looseObject({
  id: z.string(),
  kind: z.enum(["mock", "malecns"]),
  label: z.string(),
  is_mock: z.boolean(),
  description: z.string().optional(),
  neuron_count: z.number().int().nullish(),
  edge_count: z.number().int().nullish(),
  connectome: z.string().nullish(),
  model: z.string().nullish(),
  config: z.record(z.string(), z.unknown()).optional(),
});
export type ControllerInfo = z.infer<typeof ControllerInfo>;

export const Green = z.looseObject({
  stimp_ft: z.number(),
  slope_x: z.number(),
  slope_y: z.number(),
  radius_m: z.number(),
  center: z.array(z.number()).length(2),
});

export const Scenario = z.looseObject({
  seed: z.number().int(),
  green: Green,
  cup: z.array(z.number()).length(2),
  ball: z.array(z.number()).length(2),
  address_heading_rad: z.number(),
  distance_m: z.number(),
  version: z.string(),
  hole_number: z.number().int().optional(), // course holes only
});
export type Scenario = z.infer<typeof Scenario>;

export const SensoryFrame = z.object({
  channels: channelMap([LEGACY_SENSORY_CHANNELS, SENSORY_CHANNELS]),
  encoder: z.string(),
  version: z.string(),
});

export const MotorCommand = z.object({
  channels: channelMap([LEGACY_MOTOR_CHANNELS, MOTOR_CHANNELS]),
  source: z.string(),
});

const XY = z.array(z.number()).length(2);

export const Club = z.looseObject({
  id: z.string(),
  name: z.string(),
  short: z.string(),
  kind: z.enum(["putter", "wedge", "iron", "hybrid", "wood", "driver"]),
  loft_deg: z.number(),
  ball_speed_mps: z.number(),
  launch_deg: z.number(),
  spin_rpm: z.number(),
  length_m: z.number(),
  nominal: z.looseObject({ carry_m: z.number(), total_m: z.number(), apex_m: z.number() }).nullish(),
});
export type Club = z.infer<typeof Club>;

export const Launch = z.looseObject({
  speed_mps: z.number(),
  heading_rad: z.number(),
  launch_deg: z.number(),
  backspin_rpm: z.number(),
  sidespin_rpm: z.number(),
  contact: z.boolean(),
});

export const HoleSummary = z.looseObject({
  number: z.number().int(),
  name: z.string(),
  par: z.number().int(),
  description: z.string(),
  length_m: z.number(),
  tee: XY,
  cup: XY,
  has_water: z.boolean(),
});

export const CourseHole = HoleSummary.extend({
  route: z.array(XY),
  green: Green,
  fairways: z.array(z.array(XY)),
  bunkers: z.array(z.array(XY)),
  water: z.array(z.array(XY)),
  corridor_half_width_m: z.number(),
  green_apron_m: z.number(),
  fringe_m: z.number(),
  tee_radius_m: z.number(),
  collar_m: z.number().optional(),
  trees: z.array(z.array(z.number()).length(4)),
});
export type CourseHole = z.infer<typeof CourseHole>;

export const CourseSummary = z.looseObject({
  name: z.string(),
  version: z.string(),
  par: z.number().int(),
  holes: z.array(HoleSummary),
});

export const CoursePayload = z.looseObject({
  name: z.string(),
  version: z.string(),
  par: z.number().int(),
  holes: z.array(CourseHole),
  clubs: z.array(Club),
});
export type CoursePayload = z.infer<typeof CoursePayload>;

export const ScorecardEntry = z.object({
  hole: z.number().int(),
  par: z.number().int(),
  strokes: z.number().int().nullable(),
  holed: z.boolean().nullable(),
  // ids of every controller that played a stroke on this hole (a brain can be swapped mid-round)
  controllers: z.array(z.string()).optional(),
});
export type ScorecardEntry = z.infer<typeof ScorecardEntry>;

export const PopulationStat = z.looseObject({
  role: z.enum(["sensory", "motor"]),
  neurons: z.number().int(),
  spikes: z.number().int(),
  rate_hz: z.number(),
});

export const NeuralSummary = z.looseObject({
  sim_ms: z.number(),
  wall_s: z.number(),
  total_spikes: z.number().int(),
  active_neurons: z.number().int(),
  neuron_count: z.number().int(),
  mean_rate_hz: z.number(),
  bins: z.array(z.object({ t_ms: z.number(), spikes: z.number().int() })),
  populations: z.record(z.string(), PopulationStat),
  readouts: z.array(z.record(z.string(), z.unknown())).default([]),
});
export type NeuralSummary = z.infer<typeof NeuralSummary>;

export const Stroke = z.looseObject({
  speed_mps: z.number(),
  heading_rad: z.number(),
  contact: z.boolean(),
  aim_deg: z.number(),
  face_deg: z.number(),
  start_offset_deg: z.number(),
  power: z.number(),
  tempo: z.number(),
  backswing_s: z.number(),
  downswing_s: z.number(),
  body_heading_rad: z.number(),
  // motor-mapping-v2 (absent on v1 records: the club was always the putter)
  club: Club.optional(),
  club_reach: z.number().optional(),
  forced_club: z.boolean().optional(),
  swing_fraction: z.number().optional(),
  launch: Launch.optional(),
  launch_effective: Launch.optional(),
});
export type Stroke = z.infer<typeof Stroke>;

export const Outcome = z.looseObject({
  outcome: z.enum(["holed", "stopped", "off_green", "timeout", "no_contact", "water", "out_of_bounds"]),
  holed: z.boolean(),
  start_distance_m: z.number(),
  final_distance_m: z.number(),
  long_by_m: z.number(),
  miss_side: z.enum(["left", "right", "center"]),
  lip_outs: z.number().int(),
  reward: z.number(),
  strokes: z.number().int(),
  episode_state: z.enum(["ready", "holed", "picked_up"]),
});

/** How the club was chosen: senses -> (neural activity ->) readout -> club_reach -> club. */
export const ClubChain = z.looseObject({
  readout: z.string(), // "fixed" | "trained" | "mock heuristic"
  senses: z.string().optional(), // what reached the brain (or the heuristic)
  inputs: z.string().optional(), // what the readout reads
  rule: z.string().optional(),
  dn_all_rate_hz: z.number().optional(),
  p_putt: z.number().nullable().optional(),
  gate: z.string().nullable().optional(),
  club_head_raw: z.number().nullable().optional(),
  club_head_calibrated: z.number().nullable().optional(),
  needed_m: z.number().optional(),
  club_reach: z.number(),
  club: z.string(),
  forced_club: z.boolean(),
});
export type ClubChain = z.infer<typeof ClubChain>;

export const ShotRecord = z.looseObject({
  record_type: z.literal("shot"),
  schema_version: z.number().int(),
  experiment_id: z.string(),
  run_id: z.string().nullable(),
  shot_id: z.string(),
  hole_index: z.number().int(),
  stroke_number: z.number().int(),
  timestamp_utc: z.string(),
  git: z.object({ commit: z.string(), dirty: z.boolean().nullable() }),
  versions: z.record(z.string(), z.union([z.string(), z.number()])),
  seed: z.number().int(),
  controller_seed: z.number().int(),
  controller: ControllerInfo,
  decision_window_ms: z.number(),
  scenario: Scenario,
  initial_state: z.looseObject({ ball: z.array(z.number()).length(2), strokes_before: z.number().int() }),
  sensory: SensoryFrame,
  neural_summary: NeuralSummary.nullable(),
  motor: MotorCommand,
  stroke: Stroke,
  club_chain: ClubChain.optional(), // absent on records made before the telemetry existed
  trajectory: z.object({
    sample_hz: z.number(),
    points: z.array(z.array(z.number()).length(4)),
    events: z.array(z.record(z.string(), z.unknown())).default([]),
  }),
  outcome: Outcome,
  reward: z.number(),
  sim_duration_s: z.number(),
  wall_duration_s: z.number(),
  mode: z.enum(["practice", "course"]).default("practice"),
  hole: z.looseObject({ number: z.number().int(), name: z.string(), par: z.number().int() }).optional(),
  course: z
    .looseObject({ version: z.string(), hole_number: z.number().int(), round_seed: z.number().int() })
    .optional(),
  score: z.looseObject({ hole_strokes: z.number().int(), strokes: z.number().int(), to_par: z.number().int() }).optional(),
});
export type ShotRecord = z.infer<typeof ShotRecord>;

export const SessionState = z.looseObject({
  mode: z.enum(["practice", "course"]).default("practice"),
  hole_index: z.number().int(),
  scenario: Scenario,
  ball: z.array(z.number()).length(2),
  strokes: z.number().int(),
  episode_state: z.enum(["ready", "holed", "picked_up"]),
  observation: z.record(z.string(), z.unknown()),
  controller: ControllerInfo,
  stats: z.record(z.string(), z.number()),
  run_id: z.string().nullable(),
  // course mode
  hole_number: z.number().int().optional(),
  hole: CourseHole.nullish(),
  course: CourseSummary.optional(),
  lie: z.string().optional(),
  target: XY.optional(),
  round_seed: z.number().int().optional(),
  scorecard: z.array(ScorecardEntry).optional(),
  totals: z
    .looseObject({ strokes: z.number().int(), par_played: z.number().int(), to_par: z.number().int(), holes_played: z.number().int() })
    .optional(),
  round_complete: z.boolean().optional(),
  // ids of every controller that has played a stroke this round / on this green
  controllers_used: z.array(z.string()).optional(),
});
export type SessionState = z.infer<typeof SessionState>;

export const ShotPhase = z.looseObject({
  phase: z.enum(["sensing", "thinking", "swinging", "result"]),
  club: Club.optional(),
});

export const ControllerAvailability = z.looseObject({
  id: z.string(),
  kind: z.enum(["mock", "malecns"]),
  label: z.string(),
  is_mock: z.boolean(),
  available: z.boolean(),
  status: z.string(),
  neuron_count: z.number().int().nullish(),
  fix_command: z.string().nullish(),
});

export const Status = z.looseObject({
  protocol_version: z.number().int(),
  server_version: z.string(),
  controllers: z.array(ControllerAvailability),
  active_controller: z.string(),
  mode: z.enum(["practice", "course"]).optional(),
  malecns: z.looseObject({
    status: z.enum(["unavailable", "ready", "loading", "loaded", "error"]),
    neurons: z.number().int().nullish(),
    edges: z.number().int().nullish(),
    fix_command: z.string().nullish(),
    error: z.string().nullish(),
  }),
  busy: z.boolean(),
  session: SessionState.nullable(),
});
export type Status = z.infer<typeof Status>;

export const RunSummary = z.looseObject({
  run_id: z.string(),
  created_utc: z.string().nullish(),
  controller: ControllerInfo.nullish(),
  shots: z.number().int(),
  holed: z.number().int(),
  mode: z.string().nullish(),
  experiment_id: z.string().nullish(),
});
export type RunSummary = z.infer<typeof RunSummary>;
