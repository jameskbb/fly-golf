"""Putting environment: authoritative episode state, observations and reward.

One *episode* is one hole: the fly putts from the scenario's ball position
until it holes out or reaches MAX_STROKES (then it "picks up"). Each call to
`step` is one stroke.
"""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass
from enum import StrEnum

from .physics import BALL_RADIUS_M, Outcome, RollResult, Stroke, simulate_roll
from .scenario import ADDRESS_JITTER_DEG, Scenario

REWARD_VERSION = "putting-reward-v1"
MAX_STROKES = 6
LONG_PENALTY_THRESHOLD_M = 1.0


class EpisodeState(StrEnum):
    READY = "ready"  # ball at rest, awaiting a stroke
    HOLED = "holed"
    PICKED_UP = "picked_up"  # max strokes reached without holing


def wrap_angle(a: float) -> float:
    """Wrap to (-pi, pi]."""
    a = math.fmod(a + math.pi, 2.0 * math.pi)
    if a <= 0.0:
        a += 2.0 * math.pi
    return a - math.pi


@dataclass(frozen=True)
class Observation:
    """True physical state available to the sensory encoder (never to the decoder)."""

    ball: tuple[float, float]
    cup: tuple[float, float]
    distance_m: float
    bearing_world_rad: float  # direction ball -> cup
    body_heading_rad: float  # direction the fly faces at address
    bearing_rel_rad: float  # cup direction relative to body; + = to the fly's LEFT (CCW)
    slope_along: float  # rise per metre along the ball->cup line (+ = uphill putt)
    slope_cross: float  # rise per metre toward the RIGHT of the ball->cup line
    stimp_ft: float
    ball_at_rest: bool
    strokes: int
    # Course fields (defaults describe the practice green: the target is the pin, ball on the green).
    target: tuple[float, float] | None = None  # perceived aiming point; None = the cup
    target_is_pin: bool = True
    lie: str = "green"
    water_on_line: float = 0.0  # fraction of the ball->target line over water
    distance_to_pin_m: float | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ball"] = list(self.ball)
        d["cup"] = list(self.cup)
        d["target"] = list(self.target) if self.target is not None else list(self.cup)
        if d["distance_to_pin_m"] is None:
            d["distance_to_pin_m"] = self.distance_m
        return d


@dataclass(frozen=True)
class ShotOutcome:
    outcome: str
    holed: bool
    start_distance_m: float
    final_distance_m: float
    long_by_m: float  # + = past the hole along the original line, - = short
    miss_side: str  # "left" | "right" | "center" relative to the line, from the golfer's view
    lip_outs: int
    closest_approach_m: float
    reward: float
    strokes: int
    episode_state: str

    def to_dict(self) -> dict:
        return asdict(self)


def shot_reward(outcome: Outcome, start_d: float, final_d: float, long_by: float) -> float:
    """Documented reward (docs/PROVENANCE.md). Used for telemetry and future experiments only.

    It is never fed back to any controller in V1.
    """
    if outcome is Outcome.HOLED:
        return 1.0
    if outcome is Outcome.NO_CONTACT:
        return -0.25
    improvement = (start_d - final_d) / start_d if start_d > 0 else 0.0
    r = max(-1.0, min(1.0, improvement))
    if outcome is Outcome.OFF_GREEN:
        r -= 0.5
    if long_by > LONG_PENALTY_THRESHOLD_M:
        r -= 0.25
    return round(r, 6)


class PuttingEnvironment:
    def __init__(self, scenario: Scenario):
        self.reset(scenario)

    def reset(self, scenario: Scenario) -> Observation:
        self.scenario = scenario
        self.ball = scenario.ball
        self.strokes = 0
        self.state = EpisodeState.READY
        self.body_heading = scenario.address_heading_rad
        self.last_roll: RollResult | None = None
        return self.observe()

    def _address_heading(self) -> float:
        """Body heading when the fly addresses the ball for the next stroke.

        First stroke: the scenario's heading. Later strokes: the fly re-addresses
        toward the cup with seeded jitter, so aim is still required.
        """
        if self.strokes == 0:
            return self.scenario.address_heading_rad
        # String seed: a stream independent of the controller seed (hole_seed * 1000 + stroke).
        rng = random.Random(f"address-jitter:{self.scenario.seed}:{self.strokes}")
        to_cup = math.atan2(self.scenario.cup[1] - self.ball[1], self.scenario.cup[0] - self.ball[0])
        return to_cup + math.radians(rng.uniform(-ADDRESS_JITTER_DEG, ADDRESS_JITTER_DEG))

    def observe(self) -> Observation:
        bx, by = self.ball
        cx, cy = self.scenario.cup
        dx, dy = cx - bx, cy - by
        distance = math.hypot(dx, dy)
        bearing = math.atan2(dy, dx)
        ux, uy = (dx / distance, dy / distance) if distance > 0 else (1.0, 0.0)
        g = self.scenario.green
        slope_along = g.slope_x * ux + g.slope_y * uy
        # Right of the line = heading rotated clockwise by 90 deg: (uy, -ux).
        slope_cross = g.slope_x * uy + g.slope_y * (-ux)
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
        )

    @property
    def done(self) -> bool:
        return self.state is not EpisodeState.READY

    def step(self, stroke: Stroke) -> tuple[RollResult, ShotOutcome]:
        if self.done:
            raise RuntimeError(f"episode is finished ({self.state}); reset first")
        start = self.ball
        cup = self.scenario.cup
        start_d = math.hypot(cup[0] - start[0], cup[1] - start[1])
        roll = simulate_roll(self.scenario.green, start, cup, stroke)
        self.strokes += 1
        self.last_roll = roll

        fx, fy = roll.final_position
        if roll.outcome is Outcome.OFF_GREEN:
            # Ball returns to where it left the green (simple drop rule, documented).
            pass
        self.ball = (fx, fy)
        final_d = math.hypot(cup[0] - fx, cup[1] - fy)
        ux, uy = ((cup[0] - start[0]) / start_d, (cup[1] - start[1]) / start_d) if start_d else (1.0, 0.0)
        along = (fx - start[0]) * ux + (fy - start[1]) * uy
        long_by = along - start_d
        # Golfer's view looking down the line: cross > 0 means the ball finished LEFT.
        cross = ux * (fy - start[1]) - uy * (fx - start[0])
        if roll.outcome is Outcome.HOLED or abs(cross) < BALL_RADIUS_M:
            side = "center"
        else:
            side = "left" if cross > 0 else "right"

        if roll.outcome is Outcome.HOLED:
            self.state = EpisodeState.HOLED
        elif self.strokes >= MAX_STROKES:
            self.state = EpisodeState.PICKED_UP
        else:
            self.state = EpisodeState.READY
            self.body_heading = self._address_heading()

        outcome = ShotOutcome(
            outcome=roll.outcome.value,
            holed=roll.outcome is Outcome.HOLED,
            start_distance_m=start_d,
            final_distance_m=0.0 if roll.outcome is Outcome.HOLED else final_d,
            long_by_m=long_by,
            miss_side=side,
            lip_outs=roll.lip_outs,
            closest_approach_m=roll.closest_approach_m,
            reward=shot_reward(roll.outcome, start_d, final_d, long_by),
            strokes=self.strokes,
            episode_state=self.state.value,
        )
        return roll, outcome
