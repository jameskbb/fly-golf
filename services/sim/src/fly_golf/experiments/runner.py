"""Sessions (practice green and the front nine), run recording and replay.

Loop per stroke:
    Observation -> ProxySensoryEncoderV2 -> BrainController.observe/step/motor_output
    -> MotorDecoderV2 (club + launch) -> environment physics -> outcome -> record

Every controller is reset with a per-stroke seed (hole_seed * 1000 + stroke) before each
stroke, so every shot is independently reproducible from its record. Records written by
earlier versions (putting-v1, v0.1 channels) still replay: physics.py is unchanged and the
controllers keep their v0.1 behaviour for v0.1 frames.
"""

from __future__ import annotations

import json
import math
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from ..brain.interfaces import BrainController, MotorCommand, SensoryFrame
from ..brain.motor import DecodedSwing, MotorDecoderV2
from ..brain.sensory import ProxySensoryEncoderV2
from ..golf.clubs import PUTTER
from ..golf.course import COURSE_PAR, COURSE_VERSION, FRONT_NINE, HOLE_BY_NUMBER, course_summary
from ..golf.course_env import CourseEnvironment
from ..golf.env import PuttingEnvironment
from ..golf.flight import COURSE_PHYSICS_VERSION, Launch, simulate_shot
from ..golf.physics import PHYSICS_VERSION, Stroke, simulate_roll
from ..golf.scenario import Scenario, generate_scenario
from ..provenance import git_info, versions

RECORD_SCHEMA_VERSION = 2
EXPERIMENT_ID = "putting-v2"  # practice green, v0.2 sensing, putter only
COURSE_EXPERIMENT_ID = "course-v1"
DECISION_WINDOW_MS = 400.0
Notify = Callable[[str, dict], None]


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]


def controller_seed(hole_seed: int, stroke_index: int) -> int:
    return hole_seed * 1000 + stroke_index


def hole_seed(round_seed: int, hole_number: int, attempt: int = 0) -> int:
    """Seed for one attempt at one hole of a round (address jitter + controller seeds).

    Replaying a hole from the scorecard is a new attempt with a new seed, not a rerun."""
    return round_seed * 10 + hole_number + attempt * 10_000_000


class RunRecorder:
    """Append-only JSONL recorder: runs/<run_id>/run.json + shots.jsonl (+ traces/)."""

    def __init__(self, runs_dir: Path, run_id: str | None = None, metadata: dict | None = None):
        self.runs_dir = Path(runs_dir)
        self.run_id = run_id or new_run_id()
        self.dir = self.runs_dir / self.run_id
        self.shots_path = self.dir / "shots.jsonl"
        self._extra = metadata or {}
        self.metadata: dict | None = None  # written lazily: no directory for runs without shots

    def _ensure_created(self) -> None:
        if self.metadata is not None:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        self.metadata = {
            "record_type": "run",
            "schema_version": RECORD_SCHEMA_VERSION,
            "experiment_id": EXPERIMENT_ID,
            "run_id": self.run_id,
            "created_utc": datetime.now(UTC).isoformat(),
            "git": git_info(),
            "versions": versions(),
            "shots": 0,
            "holed": 0,
            **self._extra,
        }
        self._write_meta()

    def _write_meta(self) -> None:
        tmp = self.dir / "run.json.partial"
        tmp.write_text(json.dumps(self.metadata, indent=2) + "\n")
        tmp.replace(self.dir / "run.json")

    def append(self, record: dict) -> None:
        self._ensure_created()
        with self.shots_path.open("a") as fh:
            fh.write(json.dumps(record, separators=(",", ":")) + "\n")
        self.metadata["shots"] += 1
        self.metadata["holed"] += int(bool(record["outcome"]["holed"]))
        self.metadata["updated_utc"] = datetime.now(UTC).isoformat()
        self._write_meta()

    def update(self, **fields) -> None:
        """Merge summary fields (e.g. a round's scorecard) into run.json once it exists."""
        if self.metadata is None:
            return
        self.metadata.update(fields)
        self._write_meta()

    def write_trace(self, shot_id: str, trace: dict) -> str:
        self._ensure_created()
        tdir = self.dir / "traces"
        tdir.mkdir(exist_ok=True)
        path = tdir / f"{shot_id}.json"
        path.write_text(json.dumps(trace, separators=(",", ":")))
        return str(path.relative_to(self.runs_dir))


def list_runs(runs_dir: Path) -> list[dict]:
    runs_dir = Path(runs_dir)
    if not runs_dir.exists():
        return []
    out = []
    for d in sorted((p for p in runs_dir.iterdir() if (p / "run.json").exists()), reverse=True):
        meta = json.loads((d / "run.json").read_text())
        if "shots" in meta:  # counts maintained by RunRecorder.append: no need to parse every shot
            n_shots, n_holed = int(meta["shots"]), int(meta.get("holed", 0))
        else:  # records written before counts existed
            shots = load_shots(d / "shots.jsonl")
            n_shots, n_holed = len(shots), sum(1 for s in shots if s["outcome"]["holed"])
        if n_shots == 0:
            continue
        out.append(
            {
                "run_id": meta["run_id"],
                "created_utc": meta.get("created_utc"),
                "controller": meta.get("controller"),
                "experiment_id": meta.get("experiment_id"),
                "mode": meta.get("mode", "practice"),
                "shots": n_shots,
                "holed": n_holed,
                "round": meta.get("round"),
                "controllers_used": meta.get("controllers_used"),
                "git_commit": meta.get("git", {}).get("commit"),
                "git_dirty": meta.get("git", {}).get("dirty"),
            }
        )
    return out


def load_shots(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_run(runs_dir: Path, run_id: str) -> dict | None:
    if "/" in run_id or "\\" in run_id or run_id.startswith("."):
        return None
    d = Path(runs_dir) / run_id
    if not (d / "run.json").exists():
        return None
    return {"run": json.loads((d / "run.json").read_text()), "shots": load_shots(d / "shots.jsonl")}


def is_course_record(record: dict) -> bool:
    return record.get("mode") == "course"


def replay_physics(record: dict) -> dict:
    """Re-simulate a recorded shot from its recorded start state and launch; compare trajectories."""
    ball = tuple(record["initial_state"]["ball"])
    if is_course_record(record):
        course = record["course"]
        hole = HOLE_BY_NUMBER[course["hole_number"]]
        launch = Launch(**record["stroke"]["launch_effective"])
        roll = simulate_shot(hole, ball, launch)
        recorded_physics = record.get("versions", {}).get("course_physics")
        current_physics = COURSE_PHYSICS_VERSION
        extra = {"course_version_recorded": course.get("version"), "course_version_current": COURSE_VERSION}
    else:
        scenario = Scenario.from_dict(record["scenario"])
        s = record["stroke"]
        stroke = Stroke(speed_mps=s["speed_mps"], heading_rad=s["heading_rad"], contact=s["contact"])
        roll = simulate_roll(scenario.green, ball, scenario.cup, stroke)
        recorded_physics = record.get("versions", {}).get("physics")
        current_physics = PHYSICS_VERSION
        extra = {}
    replayed = [list(p) for p in roll.trajectory]
    recorded = record["trajectory"]["points"]
    identical = replayed == recorded
    max_diff = 0.0
    if not identical and len(replayed) == len(recorded):
        max_diff = max(
            abs(a - b) for pa, pb in zip(replayed, recorded, strict=True) for a, b in zip(pa, pb, strict=True)
        )
    return {
        "identical": identical,
        "physics_version_recorded": recorded_physics,
        "physics_version_current": current_physics,
        "same_physics_version": recorded_physics == current_physics,
        "points_recorded": len(recorded),
        "points_replayed": len(replayed),
        "max_abs_diff": max_diff if not identical else 0.0,
        "outcome": roll.outcome.value,
        "trajectory": replayed,
        **extra,
    }


def replay_controller(record: dict, controller: BrainController) -> dict:
    """Re-run the controller on the recorded sensory frame; check the motor output reproduces."""
    frame = SensoryFrame(
        channels=record["sensory"]["channels"],
        encoder=record["sensory"]["encoder"],
        version=record["sensory"]["version"],
    )
    controller.reset(record["controller_seed"])
    controller.observe(frame)
    controller.step(record["decision_window_ms"])
    cmd = controller.motor_output()
    return {"identical": dict(cmd.channels) == record["motor"]["channels"], "motor": dict(cmd.channels)}


def _stroke_fields(decoded: DecodedSwing, speed_mps: float, body_heading: float, effective: Launch) -> dict:
    return {
        "speed_mps": speed_mps,
        "heading_rad": decoded.launch.heading_rad,
        "contact": decoded.contact,
        "aim_deg": decoded.aim_deg,
        "face_deg": decoded.face_deg,
        "start_offset_deg": decoded.start_offset_deg,
        "power": decoded.power,
        "swing_fraction": decoded.swing_fraction,
        "tempo": decoded.tempo,
        "smash": decoded.smash,
        "backswing_s": decoded.backswing_s,
        "downswing_s": decoded.downswing_s,
        "body_heading_rad": body_heading,
        "club": decoded.club.to_dict(),
        "club_reach": decoded.club_reach,
        "forced_club": decoded.forced_club,
        "launch": decoded.launch.to_dict(),
        "launch_effective": effective.to_dict(),
        "motor_mapping_version": decoded.version,
    }


class _Session:
    """What both sessions share: encoding, the controller call, decoding and recording."""

    mode = "practice"
    experiment_id = EXPERIMENT_ID

    def __init__(
        self,
        controller: BrainController,
        recorder: RunRecorder | None = None,
        decision_window_ms: float = DECISION_WINDOW_MS,
        detailed_traces: bool = False,
    ):
        self.controller = controller
        self.recorder = recorder
        self.encoder = ProxySensoryEncoderV2()
        self.decoder = MotorDecoderV2()
        self.decision_window_ms = decision_window_ms
        self.detailed_traces = detailed_traces
        self.hole_index = -1
        self.last_record: dict | None = None
        self.run_controllers: list[str] = []  # every controller that has played a stroke in this run

    def set_controller(self, controller: BrainController) -> None:
        """Swap the brain mid-session (mid-round, mid-hole). The environment is untouched; every
        later stroke records the new controller, and each hole / the run notes who played."""
        self.controller = controller

    def _decide(self, obs, cseed: int, notify: Notify, forced_club=None):
        frame = self.encoder.encode(obs)
        notify("sensing", {"sensory": frame.to_dict()})
        self.controller.reset(cseed)
        self.controller.observe(frame)
        notify("thinking", {"decision_window_ms": self.decision_window_ms})
        summary = self.controller.step(self.decision_window_ms)
        cmd: MotorCommand = self.controller.motor_output()
        decoded = self.decoder.decode(cmd, obs.body_heading_rad, forced_club=forced_club)
        notify("swinging", {"motor": cmd.to_dict(), "club": decoded.club.to_dict(), "stroke": decoded.to_dict()})
        return frame, summary, cmd, decoded

    def _record(
        self,
        shot_id: str,
        stroke_number: int,
        cseed: int,
        obs,
        frame,
        summary,
        cmd,
        stroke: dict,
        roll,
        outcome,
        wall: float,
        extra: dict,
    ) -> dict:
        info = self.controller.info
        record = {
            "record_type": "shot",
            "schema_version": RECORD_SCHEMA_VERSION,
            "experiment_id": self.experiment_id,
            "mode": self.mode,
            "run_id": self.recorder.run_id if self.recorder else None,
            "shot_id": shot_id,
            "hole_index": self.hole_index,
            "stroke_number": stroke_number,
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "git": git_info(),
            "versions": versions(),
            "controller_seed": cseed,
            "controller": info.to_dict(),
            "decision_window_ms": self.decision_window_ms,
            **extra,
            "sensory": frame.to_dict(),
            "neural_summary": summary.to_dict() if summary else None,
            "motor": cmd.to_dict(),
            "stroke": stroke,
            "trajectory": {"sample_hz": 60, "points": [list(p) for p in roll.trajectory], "events": roll.events},
            "outcome": outcome.to_dict(),
            "reward": outcome.reward,
            "sim_duration_s": roll.duration_s,
            "wall_duration_s": round(wall, 4),
            "trace_file": None,
        }
        # How the club was chosen: senses -> (neural activity ->) readout -> club_reach -> club.
        trace = self.controller.club_trace() if hasattr(self.controller, "club_trace") else None
        if trace is not None and isinstance(stroke.get("club"), dict):
            record["club_chain"] = trace | {
                "club": stroke["club"]["id"],
                "forced_club": bool(stroke.get("forced_club")),
            }
        record["initial_state"]["observation"] = obs.to_dict()
        if self.detailed_traces and hasattr(self.controller, "last_trace") and self.recorder:
            trace = self.controller.last_trace()
            if trace:
                record["trace_file"] = self.recorder.write_trace(shot_id, trace)
        if info.id not in self.run_controllers:
            self.run_controllers.append(info.id)
        if self.recorder:
            self.recorder.append(record)
            if self.recorder.metadata.get("controllers_used") != self.run_controllers:
                self.recorder.update(controllers_used=list(self.run_controllers))
        self.last_record = record
        return record


class PuttingSession(_Session):
    """The practice green: seeded putts, putter only (the environment hands the fly a putter)."""

    mode = "practice"
    experiment_id = EXPERIMENT_ID

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.env: PuttingEnvironment | None = None
        self.stats = {"holes": 0, "holes_completed": 0, "holed": 0, "strokes": 0, "shots": 0}

    def new_hole(self, seed: int) -> dict:
        scenario = generate_scenario(seed)
        self.env = PuttingEnvironment(scenario)
        self.hole_index += 1
        self.stats["holes"] += 1
        self.last_record = None
        return self.state()

    def state(self) -> dict:
        if self.env is None:
            return {
                "mode": self.mode,
                "hole": None,
                "controller": self.controller.info.to_dict(),
                "stats": dict(self.stats),
            }
        obs = self.env.observe()
        return {
            "mode": self.mode,
            "hole_index": self.hole_index,
            "scenario": self.env.scenario.to_dict(),
            "ball": list(self.env.ball),
            "strokes": self.env.strokes,
            "episode_state": self.env.state.value,
            "observation": obs.to_dict(),
            "controller": self.controller.info.to_dict(),
            "stats": dict(self.stats),
            "run_id": self.recorder.run_id if self.recorder else None,
            "controllers_used": list(self.run_controllers),
        }

    def play_shot(self, on_phase: Notify | None = None) -> dict:
        if self.env is None:
            raise RuntimeError("call new_hole() first")
        if self.env.done:
            raise RuntimeError("hole finished; start a new hole")
        env = self.env
        notify = on_phase or (lambda _phase, _data: None)
        wall0 = time.perf_counter()
        initial_ball = list(env.ball)
        strokes_before = env.strokes
        obs = env.observe()
        cseed = controller_seed(env.scenario.seed, strokes_before)
        frame, summary, cmd, decoded = self._decide(obs, cseed, notify, forced_club=PUTTER)
        stroke = decoded.stroke
        roll, outcome = env.step(stroke)
        wall = time.perf_counter() - wall0

        self.stats["shots"] += 1
        self.stats["strokes"] += 1
        if outcome.holed:
            self.stats["holed"] += 1
        if env.done:
            self.stats["holes_completed"] += 1
        shot_id = f"h{self.hole_index:03d}-s{strokes_before + 1:02d}"
        effective = Launch(stroke.speed_mps, stroke.heading_rad, 0.0, 0.0, 0.0, stroke.contact)
        record = self._record(
            shot_id,
            strokes_before + 1,
            cseed,
            obs,
            frame,
            summary,
            cmd,
            _stroke_fields(decoded, stroke.speed_mps, obs.body_heading_rad, effective),
            roll,
            outcome,
            wall,
            {
                "seed": env.scenario.seed,
                "scenario": env.scenario.to_dict(),
                "initial_state": {"ball": initial_ball, "strokes_before": strokes_before},
            },
        )
        notify("result", {"shot_id": shot_id})
        return record


class RoundSession(_Session):
    """A round on the front nine. The fly picks every club itself (motor channel club_reach)."""

    mode = "course"
    experiment_id = COURSE_EXPERIMENT_ID

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.env: CourseEnvironment | None = None
        self.round_seed = 0
        self.hole_number = 0
        self.scorecard: dict[int, dict] = {}
        self.attempts: dict[int, int] = {}
        self.rounds: list[dict] = []  # summaries of earlier rounds in this run
        self.stats = {"holes": 0, "holes_completed": 0, "holed": 0, "strokes": 0, "shots": 0, "penalties": 0}

    # ---- round flow ----------------------------------------------------------------------------
    def _round_summary(self) -> dict:
        return {
            "seed": self.round_seed,
            "complete": self.round_complete,
            "controllers_used": self._round_controllers(),
            "scorecard": [self.scorecard[n] for n in sorted(self.scorecard)],
            **self._totals(),
        }

    def new_round(self, round_seed: int, start_hole: int = 1) -> dict:
        if not isinstance(round_seed, int) or round_seed < 0:
            raise ValueError("round seed must be a non-negative integer")
        if any(c["strokes"] is not None for c in self.scorecard.values()):
            self.rounds.append(self._round_summary())
        self.round_seed = round_seed
        self.attempts = {}
        self.scorecard = {
            h.number: {"hole": h.number, "par": h.par, "strokes": None, "holed": None, "controllers": []}
            for h in FRONT_NINE
        }
        return self.start_hole(start_hole)

    def start_hole(self, number: int) -> dict:
        if number not in HOLE_BY_NUMBER:
            raise ValueError(f"no hole {number} on the front nine")
        self.hole_number = number
        attempt = self.attempts.get(number, -1) + 1
        self.attempts[number] = attempt
        self.env = CourseEnvironment(HOLE_BY_NUMBER[number], hole_seed(self.round_seed, number, attempt))
        self.hole_index += 1
        self.stats["holes"] += 1
        self.last_record = None
        self.scorecard[number] = {
            "hole": number,
            "par": HOLE_BY_NUMBER[number].par,
            "strokes": None,
            "holed": None,
            "controllers": [],
        }
        return self.state()

    @property
    def round_complete(self) -> bool:
        return bool(self.scorecard) and all(c["strokes"] is not None for c in self.scorecard.values())

    def _round_controllers(self) -> list[str]:
        """Every controller that played a stroke on the current scorecard, in hole order."""
        out: list[str] = []
        for n in sorted(self.scorecard):
            for cid in self.scorecard[n].get("controllers", []):
                if cid not in out:
                    out.append(cid)
        return out

    def next_hole(self) -> dict:
        """Advance after a finished hole: the next unplayed hole, or a new round after the ninth."""
        if self.env is not None and not self.env.done:
            raise RuntimeError("finish the current hole first")
        if self.round_complete:
            return self.new_round(self.round_seed + 1)
        later = [n for n in sorted(self.scorecard) if n > self.hole_number and self.scorecard[n]["strokes"] is None]
        pending = later or [n for n in sorted(self.scorecard) if self.scorecard[n]["strokes"] is None]
        return self.start_hole(pending[0])

    def _totals(self) -> dict:
        played = [c for c in self.scorecard.values() if c["strokes"] is not None]
        strokes = sum(c["strokes"] for c in played)
        par = sum(c["par"] for c in played)
        return {"strokes": strokes, "par_played": par, "to_par": strokes - par, "holes_played": len(played)}

    def state(self) -> dict:
        if self.env is None:
            return {
                "mode": self.mode,
                "hole": None,
                "controller": self.controller.info.to_dict(),
                "stats": dict(self.stats),
            }
        env = self.env
        obs = env.observe()
        hole = env.hole
        return {
            "mode": self.mode,
            "hole_index": self.hole_index,
            "hole_number": hole.number,
            "hole": hole.to_dict(),
            "course": course_summary(),
            "scenario": self._scenario(),
            "ball": list(env.ball),
            "lie": env.lie.value,
            "target": list(env.target()),
            "strokes": env.strokes,
            "episode_state": env.state.value,
            "observation": obs.to_dict(),
            "controller": self.controller.info.to_dict(),
            "stats": dict(self.stats),
            "run_id": self.recorder.run_id if self.recorder else None,
            "round_seed": self.round_seed,
            "scorecard": [self.scorecard[n] for n in sorted(self.scorecard)],
            "totals": self._totals(),
            "round_complete": self.round_complete,
            "controllers_used": self._round_controllers(),
        }

    def _scenario(self) -> dict:
        """The hole in the practice-green scenario shape (green, cup, seed) plus its number."""
        env = self.env
        g = env.hole.green
        return {
            "seed": env.seed,
            "green": {
                "stimp_ft": g.stimp_ft,
                "slope_x": g.slope_x,
                "slope_y": g.slope_y,
                "radius_m": g.radius_m,
                "center": list(g.center),
                "rolling_decel": g.rolling_decel,
            },
            "cup": list(env.hole.cup),
            "ball": list(env.hole.tee),
            "address_heading_rad": env.initial_heading,
            "distance_m": env.hole.length_m,
            "version": COURSE_VERSION,
            "hole_number": env.hole.number,
        }

    def play_shot(self, on_phase: Notify | None = None) -> dict:
        if self.env is None:
            raise RuntimeError("call new_round() first")
        if self.env.done:
            raise RuntimeError("hole finished; go to the next hole")
        env = self.env
        notify = on_phase or (lambda _phase, _data: None)
        wall0 = time.perf_counter()
        initial_ball = list(env.ball)
        strokes_before = env.strokes
        lie_before = env.lie.value
        obs = env.observe()
        cseed = controller_seed(env.seed, strokes_before)
        frame, summary, cmd, decoded = self._decide(obs, cseed, notify)
        result, outcome = env.step(decoded.launch)
        # Credit the brain with the hole only once its stroke has actually been played.
        who = self.scorecard[env.hole.number].setdefault("controllers", [])
        if self.controller.info.id not in who:
            who.append(self.controller.info.id)
        wall = time.perf_counter() - wall0

        self.stats["shots"] += 1
        self.stats["strokes"] += env.strokes - strokes_before  # respects the pick-up cap
        self.stats["penalties"] += outcome.penalty_strokes
        if outcome.holed:
            self.stats["holed"] += 1
        if env.done:
            self.stats["holes_completed"] += 1
            self.scorecard[env.hole.number] = {
                "hole": env.hole.number,
                "par": env.hole.par,
                "strokes": env.strokes,
                "holed": outcome.holed,
                "controllers": who,
            }
        attempt = self.attempts.get(env.hole.number, 0)
        retry = f"a{attempt}" if attempt else ""
        shot_id = f"r{self.round_seed}-h{env.hole.number}{retry}-s{strokes_before + 1:02d}"
        hole = env.hole
        record = self._record(
            shot_id,
            strokes_before + 1,
            cseed,
            obs,
            frame,
            summary,
            cmd,
            _stroke_fields(decoded, decoded.launch.speed_mps, obs.body_heading_rad, env.last_launch),
            result,
            outcome,
            wall,
            {
                "seed": env.seed,
                "scenario": self._scenario(),
                "course": {
                    "version": COURSE_VERSION,
                    "hole_number": hole.number,
                    "round_seed": self.round_seed,
                    "attempt": attempt,
                    "par": COURSE_PAR,
                },
                "hole": {"number": hole.number, "name": hole.name, "par": hole.par},
                "initial_state": {
                    "ball": initial_ball,
                    "strokes_before": strokes_before,
                    "lie": lie_before,
                    "target": list(obs.target) if obs.target else None,
                },
                "score": {"hole_strokes": env.strokes, **self._totals()},
            },
        )
        if self.recorder and env.done:
            current = self._round_summary()
            self.recorder.update(round=current, rounds=[*self.rounds, current])
        notify("result", {"shot_id": shot_id})
        return record


def summarize(record: dict) -> str:
    o = record["outcome"]
    s = record["stroke"]
    label = record["controller"]["label"]
    if is_course_record(record):
        club = s["club"]["short"]
        d_yd = o["start_distance_m"] / 0.9144
        if o["holed"]:
            res = "HOLED"
        elif o["outcome"] in ("water", "out_of_bounds"):
            res = f"{o['outcome'].upper()} (+{o['penalty_strokes']})"
        else:
            res = f"{o['lie_after']}, {o['final_distance_m'] / 0.9144:.0f} yd to go"
        return (
            f"[{label}] {record['shot_id']} {d_yd:5.0f} yd {o['lie_before']:>7s} {club:>3s}: "
            f"{o['total_m'] / 0.9144:4.0f} yd -> {res}"
        )
    ft = o["start_distance_m"] / 0.3048
    res = "HOLED" if o["holed"] else f"{o['outcome']} {o['final_distance_m']:.2f} m left ({o['miss_side']})"
    return (
        f"[{label}] {record['shot_id']} {ft:4.1f} ft putt: "
        f"aim {s['aim_deg']:+5.1f} deg, speed {s['speed_mps']:.2f} m/s -> {res}, reward {record['reward']:+.2f}"
        + ("" if math.isfinite(record["reward"]) else " (!)")
    )
