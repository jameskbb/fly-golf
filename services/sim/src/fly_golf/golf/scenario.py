"""Seeded putting-scenario generator.

`random.Random` (Mersenne Twister) is specified by the Python language and is
reproducible across platforms for a given seed, which is why it is used here
rather than a NumPy generator whose stream could change between versions.
"""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass

from .physics import Green, rest_is_stable

SCENARIO_VERSION = "putting-scenario-v2"  # v2: re-address jitter stream decoupled from controller seed

MIN_DISTANCE_M = 1.0  # ~3 ft
MAX_DISTANCE_M = 6.0  # ~20 ft
MIN_STIMP = 8.0
MAX_STIMP = 12.0
MAX_SLOPE = 0.025  # 2.5 % grade
ADDRESS_JITTER_DEG = 10.0


@dataclass(frozen=True)
class Scenario:
    seed: int
    green: Green
    cup: tuple[float, float]
    ball: tuple[float, float]
    address_heading_rad: float
    """Direction the fly's body faces at address. Deliberately not the exact
    line to the cup: the golfer stands roughly facing the hole and must aim."""
    version: str = SCENARIO_VERSION

    @property
    def distance_m(self) -> float:
        return math.hypot(self.cup[0] - self.ball[0], self.cup[1] - self.ball[1])

    def to_dict(self) -> dict:
        d = asdict(self)
        d["green"]["center"] = list(self.green.center)
        d["cup"] = list(self.cup)
        d["ball"] = list(self.ball)
        d["distance_m"] = self.distance_m
        d["green"]["rolling_decel"] = self.green.rolling_decel
        return d

    @staticmethod
    def from_dict(d: dict) -> Scenario:
        g = d["green"]
        green = Green(
            stimp_ft=g["stimp_ft"],
            slope_x=g["slope_x"],
            slope_y=g["slope_y"],
            radius_m=g["radius_m"],
            center=tuple(g["center"]),
        )
        return Scenario(
            seed=int(d["seed"]),
            green=green,
            cup=tuple(d["cup"]),
            ball=tuple(d["ball"]),
            address_heading_rad=float(d["address_heading_rad"]),
            version=d.get("version", SCENARIO_VERSION),
        )


def generate_scenario(seed: int) -> Scenario:
    if not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    rng = random.Random(seed)
    stimp = rng.uniform(MIN_STIMP, MAX_STIMP)
    slope_mag = rng.uniform(0.0, MAX_SLOPE)
    slope_dir = rng.uniform(0.0, 2.0 * math.pi)
    green = Green(
        stimp_ft=round(stimp, 3),
        slope_x=round(slope_mag * math.cos(slope_dir), 6),
        slope_y=round(slope_mag * math.sin(slope_dir), 6),
    )
    if not rest_is_stable(green):  # guaranteed by MAX_SLOPE, asserted for safety
        raise RuntimeError("generated green cannot hold a ball at rest")
    distance = rng.uniform(MIN_DISTANCE_M, MAX_DISTANCE_M)
    placement = rng.uniform(0.0, 2.0 * math.pi)
    cup = (0.0, 0.0)
    ball = (round(distance * math.cos(placement), 6), round(distance * math.sin(placement), 6))
    to_cup = math.atan2(cup[1] - ball[1], cup[0] - ball[0])
    jitter = math.radians(rng.uniform(-ADDRESS_JITTER_DEG, ADDRESS_JITTER_DEG))
    return Scenario(
        seed=seed,
        green=green,
        cup=cup,
        ball=ball,
        address_heading_rad=round(to_cup + jitter, 9),
    )
