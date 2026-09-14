"""Course environment: one hole of the front nine is one episode.

The fly plays from the tee until it holes out or reaches par + MAX_OVER_PAR strokes (then it
"picks up", scoring that maximum). Each `step` is one stroke. Rules (docs/COURSE.md):

* A whiff (no contact) counts as a stroke; the ball does not move.
* Water: one penalty stroke; the ball is dropped on the line from the shot's origin, just
  short of where it crossed into the water (a simplified "back on the line" relief).
* Out of bounds (into the trees): one penalty stroke; replay from the previous spot
  (stroke and distance).
"""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass

from .course import HoleSpec
from .env import EpisodeState, Observation, wrap_angle
from .flight import Launch, Outcome, ShotResult, Surface, simulate_shot
from .physics import BALL_RADIUS_M
from .scenario import ADDRESS_JITTER_DEG

COURSE_REWARD_VERSION = "course-reward-v1"
MAX_OVER_PAR = 5
ADDRESS_JITTER_FULL_DEG = 6.0  # off the green the fly stands within +-6 deg of its target line
DROP_BACK_M = 2.0
PUTTING_LIES = (Surface.GREEN, Surface.FRINGE)
# A lofted strike from a bad lie: grass or sand between club and ball costs speed and spin.
# Applied by the environment (the decoder never sees the lie). Putts are unaffected here:
# their roll already feels the surface's rolling resistance.
LIE_SPEED_FACTOR = {"sand": 0.72, "rough": 0.9}
LIE_SPIN_FACTOR = {"sand": 0.5, "rough": 0.55}


def apply_lie(launch: Launch, lie: Surface) -> Launch:
    if launch.launch_deg <= 0.0 or lie.value not in LIE_SPEED_FACTOR:
        return launch
    k = LIE_SPEED_FACTOR[lie.value]
    s = LIE_SPIN_FACTOR[lie.value]
    return Launch(
        launch.speed_mps * k,
        launch.heading_rad,
        launch.launch_deg,
        launch.backspin_rpm * s,
        launch.sidespin_rpm * s,
        launch.contact,
    )


@dataclass(frozen=True)
class CourseShotOutcome:
    outcome: str
    holed: bool
    start_distance_m: float  # to the pin
    final_distance_m: float  # to the pin
    target_distance_m: float  # to the perceived target (routing point or pin)
    long_by_m: float  # + = past the target along the start->target line
    miss_side: str  # left | right | center relative to the start->target line
    lip_outs: int
    closest_approach_m: float
    carry_m: float
    total_m: float
    lie_before: str
    lie_after: str
    penalty_strokes: int
    reward: float
    strokes: int  # strokes on this hole so far, penalties included
    episode_state: str

    def to_dict(self) -> dict:
        return asdict(self)


def course_reward(outcome: Outcome, start_d: float, final_d: float, penalties: int) -> float:
    """Telemetry-only reward (never fed to a controller during play)."""
    if outcome is Outcome.HOLED:
        return 1.0
    if outcome is Outcome.NO_CONTACT:
        return -0.25
    r = (start_d - final_d) / start_d if start_d > 0 else 0.0
    r = max(-1.0, min(1.0, r)) - 0.5 * penalties
    return round(r, 6)


class CourseEnvironment:
    def __init__(self, hole: HoleSpec, seed: int):
        self.reset(hole, seed)

    def reset(self, hole: HoleSpec, seed: int) -> Observation:
        if not isinstance(seed, int) or seed < 0:
            raise ValueError("seed must be a non-negative integer")
        self.hole = hole
        self.seed = seed
        self.ball: tuple[float, float] = hole.tee
        self.strokes = 0
        self.penalties = 0
        self.state = EpisodeState.READY
        self.lie = Surface.TEE
        self.last_result: ShotResult | None = None
        self.last_launch: Launch | None = None
        self.body_heading = self._address_heading()
        self.initial_heading = self.body_heading
        return self.observe()

    def place(self, ball: tuple[float, float], jitter_deg: float) -> Observation:
        """Put the ball somewhere on the hole (practice / training situations, not play).

        The fly addresses it facing its target, rotated by `jitter_deg`.
        """
        self.ball = (float(ball[0]), float(ball[1]))
        self.lie = self.hole.surface(*self.ball)
        if self.lie in (Surface.WATER, Surface.OOB):
            raise ValueError("cannot place the ball in water or out of bounds")
        tx, ty = self.target()
        self.body_heading = math.atan2(ty - self.ball[1], tx - self.ball[0]) + math.radians(jitter_deg)
        return self.observe()

    @property
    def max_strokes(self) -> int:
        return self.hole.par + MAX_OVER_PAR

    @property
    def done(self) -> bool:
        return self.state is not EpisodeState.READY

    @property
    def on_putting_surface(self) -> bool:
        return self.lie in PUTTING_LIES

    def target(self) -> tuple[float, float]:
        return self.hole.target_for(self.ball)

    def _address_heading(self) -> float:
        """Where the fly's body faces at address: toward its target with seeded jitter."""
        tx, ty = self.target()
        to_target = math.atan2(ty - self.ball[1], tx - self.ball[0])
        jitter = ADDRESS_JITTER_DEG if self.on_putting_surface else ADDRESS_JITTER_FULL_DEG
        rng = random.Random(f"course-address:{self.hole.number}:{self.seed}:{self.strokes}")
        return to_target + math.radians(rng.uniform(-jitter, jitter))

    def observe(self) -> Observation:
        bx, by = self.ball
        tx, ty = self.target()
        dx, dy = tx - bx, ty - by
        distance = math.hypot(dx, dy)
        bearing = math.atan2(dy, dx)
        ux, uy = (dx / distance, dy / distance) if distance > 0 else (1.0, 0.0)
        g = self.hole.green
        if self.lie is Surface.GREEN:  # the fringe is flat for physics, so it reports no slope
            slope_along = g.slope_x * ux + g.slope_y * uy
            slope_cross = g.slope_x * uy + g.slope_y * (-ux)
        else:
            slope_along = slope_cross = 0.0  # the fairway is flat for physics
        cx, cy = self.hole.cup
        return Observation(
            ball=(bx, by),
            cup=(cx, cy),
            distance_m=distance,
            bearing_world_rad=bearing,
            body_heading_rad=self.body_heading,
            bearing_rel_rad=wrap_angle(bearing - self.body_heading),
            slope_along=slope_along,
            slope_cross=slope_cross,
            stimp_ft=g.stimp_ft,
            ball_at_rest=True,
            strokes=self.strokes,
            target=(tx, ty),
            target_is_pin=(tx, ty) == (cx, cy),
            lie=self.lie.value,
            water_on_line=self.hole.water_on_line((bx, by), (tx, ty)),
            distance_to_pin_m=math.hypot(cx - bx, cy - by),
        )

    def _water_drop(self, start: tuple[float, float], entry: tuple[float, float]) -> tuple[float, float]:
        """Walk back from the entry point toward the shot's origin until dry land, then DROP_BACK_M more."""
        ex, ey = entry
        d = math.hypot(ex - start[0], ey - start[1])
        if d <= 0.0:
            return start
        ux, uy = (start[0] - ex) / d, (start[1] - ey) / d
        s = 0.0
        while s < d:
            x, y = ex + ux * s, ey + uy * s
            if self.hole.surface(x, y) not in (Surface.WATER, Surface.OOB):
                back = min(d, s + DROP_BACK_M)
                px, py = ex + ux * back, ey + uy * back
                if self.hole.surface(px, py) in (Surface.WATER, Surface.OOB):
                    return (x, y)
                return (px, py)
            s += 0.5
        return start

    def step(self, launch: Launch) -> tuple[ShotResult, CourseShotOutcome]:
        if self.done:
            raise RuntimeError(f"episode is finished ({self.state}); reset first")
        start = self.ball
        lie_before = self.lie
        cx, cy = self.hole.cup
        tx, ty = self.target()
        start_d = math.hypot(cx - start[0], cy - start[1])
        target_d = math.hypot(tx - start[0], ty - start[1])
        launch = apply_lie(launch, lie_before)
        self.last_launch = launch
        result = simulate_shot(self.hole, start, launch)
        self.strokes += 1
        self.last_result = result
        penalties = 0
        if result.outcome is Outcome.WATER:
            penalties = 1
            self.ball = self._water_drop(start, result.hazard_entry or result.final_position)
        elif result.outcome is Outcome.OUT_OF_BOUNDS:
            penalties = 1
            self.ball = start
        else:
            self.ball = result.final_position
        self.strokes += penalties
        self.penalties += penalties
        self.lie = Surface.GREEN if result.outcome is Outcome.HOLED else self.hole.surface(*self.ball)

        fx, fy = result.final_position
        final_d = 0.0 if result.outcome is Outcome.HOLED else math.hypot(cx - fx, cy - fy)
        ux, uy = ((tx - start[0]) / target_d, (ty - start[1]) / target_d) if target_d else (1.0, 0.0)
        along = (fx - start[0]) * ux + (fy - start[1]) * uy
        cross = ux * (fy - start[1]) - uy * (fx - start[0])
        if result.outcome is Outcome.HOLED or abs(cross) < BALL_RADIUS_M:
            side = "center"
        else:
            side = "left" if cross > 0 else "right"

        if result.outcome is Outcome.HOLED:
            self.state = EpisodeState.HOLED
        elif self.strokes >= self.max_strokes:
            self.state = EpisodeState.PICKED_UP
            self.strokes = self.max_strokes
        else:
            self.state = EpisodeState.READY
            self.body_heading = self._address_heading()

        outcome = CourseShotOutcome(
            outcome=result.outcome.value,
            holed=result.outcome is Outcome.HOLED,
            start_distance_m=start_d,
            final_distance_m=final_d,
            target_distance_m=target_d,
            long_by_m=along - target_d,
            miss_side=side,
            lip_outs=result.lip_outs,
            closest_approach_m=result.closest_approach_m,
            carry_m=result.carry_m,
            total_m=math.hypot(fx - start[0], fy - start[1]),
            lie_before=lie_before.value,
            lie_after=self.lie.value,
            penalty_strokes=penalties,
            reward=course_reward(result.outcome, start_d, final_d, penalties),
            strokes=self.strokes,
            episode_state=self.state.value,
        )
        return result, outcome
