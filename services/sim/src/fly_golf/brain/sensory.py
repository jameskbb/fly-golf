"""V0 PROXY sensory encoder.

This is an engineered proxy, not a model of fly perception. It converts the
physical golf state into bounded, perceptual-style channels (where is the
target, how far, which way does the ground fall, how fast is the green). It
never computes a solution such as an aim angle or stroke power.

Channel definitions and scales are documented in docs/SENSORY_MAPPING.md.
Changing any constant here requires bumping SENSORY_MAPPING_VERSION.
"""

from __future__ import annotations

import math

from ..golf.env import Observation
from .interfaces import SensoryFrame

SENSORY_MAPPING_VERSION = "proxy-sensory-v0.1"
ENCODER_ID = "proxy-v0"

BEARING_FULL_SCALE_DEG = 45.0
DISTANCE_FULL_SCALE_M = 10.0
SLOPE_FULL_SCALE = 0.03  # 3 % grade
STIMP_MIN, STIMP_SPAN = 6.0, 8.0


def _clip(v: float) -> float:
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


class ProxySensoryEncoder:
    id = ENCODER_ID
    version = SENSORY_MAPPING_VERSION

    def encode(self, obs: Observation) -> SensoryFrame:
        if not isinstance(obs, Observation):
            raise ValueError("ProxySensoryEncoder.encode requires an Observation")
        for name in ("distance_m", "bearing_rel_rad", "slope_along", "slope_cross", "stimp_ft"):
            v = getattr(obs, name)
            if not isinstance(v, int | float) or not math.isfinite(v):
                raise ValueError(f"observation field {name!r} is not finite: {v!r}")
        if obs.distance_m < 0:
            raise ValueError("distance_m must be non-negative")
        bearing_deg = math.degrees(obs.bearing_rel_rad)  # + = target to the fly's left
        channels = {
            "target_left": _clip(bearing_deg / BEARING_FULL_SCALE_DEG),
            "target_right": _clip(-bearing_deg / BEARING_FULL_SCALE_DEG),
            "target_distance": _clip(obs.distance_m / DISTANCE_FULL_SCALE_M),
            "slope_uphill": _clip(obs.slope_along / SLOPE_FULL_SCALE),
            "slope_downhill": _clip(-obs.slope_along / SLOPE_FULL_SCALE),
            # Ground rising to the right of the line means it falls to the left.
            "slope_fall_left": _clip(obs.slope_cross / SLOPE_FULL_SCALE),
            "slope_fall_right": _clip(-obs.slope_cross / SLOPE_FULL_SCALE),
            "green_speed": _clip((obs.stimp_ft - STIMP_MIN) / STIMP_SPAN),
            "ball_at_rest": 1.0 if obs.ball_at_rest else 0.0,
        }
        return SensoryFrame(channels=channels, encoder=self.id, version=self.version)


# ---------------------------------------------------------------------------------------------
# v0.2: the whole course. The nine v0.1 channels are computed exactly as above (the "target" is
# the perceived aiming point, which on the green is the pin); five channels are added.

SENSORY_MAPPING_VERSION_V2 = "proxy-sensory-v0.2"
FAR_FULL_SCALE_M = 250.0  # beyond ~driver distance the long-range cue saturates


class ProxySensoryEncoderV2:
    id = ENCODER_ID
    version = SENSORY_MAPPING_VERSION_V2

    def __init__(self) -> None:
        self._v1 = ProxySensoryEncoder()

    def encode(self, obs: Observation) -> SensoryFrame:
        base = dict(self._v1.encode(obs).channels)
        if not isinstance(obs.water_on_line, int | float) or not math.isfinite(obs.water_on_line):
            raise ValueError("observation field 'water_on_line' is not finite")
        lie = obs.lie
        channels = base | {
            "target_far": _clip(obs.distance_m / FAR_FULL_SCALE_M),
            # "green" covers the fringe too: the ball sits on short, smooth grass either way.
            "lie_green": 1.0 if lie in ("green", "fringe") else 0.0,
            "lie_rough": 1.0 if lie == "rough" else 0.0,
            "lie_sand": 1.0 if lie == "sand" else 0.0,
            "water_on_line": _clip(obs.water_on_line),
        }
        return SensoryFrame(channels=channels, encoder=self.id, version=self.version)
