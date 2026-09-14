"""MOCK CONTROLLER - deterministic development controller. NOT the scientific result.

Purpose: verify physics, WebSocket streaming, animation, the shot lifecycle and
experiment recording before (and independently of) the connectome.

It uses a hand-written putting heuristic on the proxy sensory channels, plus
seeded "tremor" so shots vary. It has no neurons and reports no neural
statistics. Every record, API payload and UI badge labels it MOCK.
"""

from __future__ import annotations

import math
import random

from ..golf.clubs import BAG, nominal_distances, reach_for
from ..golf.course_env import LIE_SPEED_FACTOR
from ..golf.physics import FOOT_M, ROLL_FACTOR, STIMP_RELEASE_SPEED, G
from .interfaces import (
    ControllerInfo,
    ControllerKind,
    MotorCommand,
    NeuralSummary,
    SensoryFrame,
)
from .motor import FULL_MIN_SWING, MAX_AIM_DEG, MAX_BALL_SPEED_MPS
from .sensory import (
    BEARING_FULL_SCALE_DEG,
    DISTANCE_FULL_SCALE_M,
    FAR_FULL_SCALE_M,
    SLOPE_FULL_SCALE,
    STIMP_MIN,
    STIMP_SPAN,
)

MOCK_VERSION = "mock-heuristic-v2"  # v1 behaviour, unchanged, for v0.1 sensory frames
FULL_SWING_AIM_NOISE_FACTOR = 2.0  # full swings are sprayed more than putts


def _clip(v: float) -> float:
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


class MockBrainController:
    def __init__(self, aim_noise_deg: float = 1.5, power_noise: float = 0.05):
        self.aim_noise_deg = aim_noise_deg
        self.power_noise = power_noise
        self.info = ControllerInfo(
            id="mock",
            kind=ControllerKind.MOCK,
            label="MOCK CONTROLLER",
            is_mock=True,
            description=(
                "Deterministic hand-written heuristic with seeded noise and a caddie's distance table "
                "(putting and club choice). Development infrastructure only - no neurons, no connectome."
            ),
            model=MOCK_VERSION,
            config={"aim_noise_deg": aim_noise_deg, "power_noise": power_noise},
        )
        self.reset(0)

    def reset(self, seed: int) -> None:
        self._club_trace = None
        self._seed = int(seed)
        self._rng = random.Random(self._seed)
        self._frame: SensoryFrame | None = None
        self._command: MotorCommand | None = None

    def observe(self, frame: SensoryFrame) -> None:
        if not isinstance(frame, SensoryFrame):
            raise ValueError("observe() requires a SensoryFrame")
        self._frame = frame

    def step(self, duration_ms: float) -> NeuralSummary | None:
        if self._frame is None:
            raise RuntimeError("observe() must be called before step()")
        if not math.isfinite(duration_ms) or duration_ms <= 0:
            raise ValueError("duration_ms must be positive")
        if not self._frame.is_legacy:
            self._command = self._course_command(self._frame.channels)
            return None
        c = self._frame.channels
        rng = self._rng

        bearing_deg = (c["target_left"] - c["target_right"]) * BEARING_FULL_SCALE_DEG
        distance = c["target_distance"] * DISTANCE_FULL_SCALE_M
        fall_left = (c["slope_fall_left"] - c["slope_fall_right"]) * SLOPE_FULL_SCALE
        # Ball breaks toward the fall; aim the opposite way, more for longer putts.
        break_comp_deg = -fall_left * distance * 55.0
        aim_deg = bearing_deg + break_comp_deg + rng.gauss(0.0, self.aim_noise_deg)

        stimp = c["green_speed"] * STIMP_SPAN + STIMP_MIN
        decel = STIMP_RELEASE_SPEED**2 / (2.0 * stimp * FOOT_M)
        slope_along = (c["slope_uphill"] - c["slope_downhill"]) * SLOPE_FULL_SCALE
        a_eff = max(0.05, decel + ROLL_FACTOR * G * slope_along)
        roll_target = distance + 0.35  # die ~35 cm past the hole
        speed = math.sqrt(2.0 * a_eff * roll_target) * (1.0 + rng.gauss(0.0, self.power_noise))
        face = rng.gauss(0.0, 0.15)

        self._command = MotorCommand(
            channels={
                "aim_left": _clip(aim_deg / MAX_AIM_DEG),
                "aim_right": _clip(-aim_deg / MAX_AIM_DEG),
                "stroke_power": _clip(speed / MAX_BALL_SPEED_MPS),
                "stroke_tempo": _clip(0.5 + rng.gauss(0.0, 0.04)),
                "face_open": _clip(-face),
                "face_closed": _clip(face),
                "strike": 1.0,
            },
            source=self.info.id,
        )
        return None  # a mock has no neural activity to report

    def motor_output(self) -> MotorCommand:
        if self._command is None:
            raise RuntimeError("step() must be called before motor_output()")
        return self._command

    # ---- mock-heuristic-v2: v0.2 frames (the course) ------------------------------------------
    def _putt_channels(self, c) -> dict[str, float]:
        """The v1 putting heuristic, same draws in the same order."""
        rng = self._rng
        bearing_deg = (c["target_left"] - c["target_right"]) * BEARING_FULL_SCALE_DEG
        distance = c["target_distance"] * DISTANCE_FULL_SCALE_M
        fall_left = (c["slope_fall_left"] - c["slope_fall_right"]) * SLOPE_FULL_SCALE
        aim_deg = bearing_deg - fall_left * distance * 55.0 + rng.gauss(0.0, self.aim_noise_deg)
        stimp = c["green_speed"] * STIMP_SPAN + STIMP_MIN
        decel = STIMP_RELEASE_SPEED**2 / (2.0 * stimp * FOOT_M)
        slope_along = (c["slope_uphill"] - c["slope_downhill"]) * SLOPE_FULL_SCALE
        a_eff = max(0.05, decel + ROLL_FACTOR * G * slope_along)
        speed = math.sqrt(2.0 * a_eff * (distance + 0.35)) * (1.0 + rng.gauss(0.0, self.power_noise))
        face = rng.gauss(0.0, 0.15)
        return {
            "aim_left": _clip(aim_deg / MAX_AIM_DEG),
            "aim_right": _clip(-aim_deg / MAX_AIM_DEG),
            "stroke_power": _clip(speed / MAX_BALL_SPEED_MPS),
            "stroke_tempo": _clip(0.5 + rng.gauss(0.0, 0.04)),
            "face_open": _clip(-face),
            "face_closed": _clip(face),
            "strike": 1.0,
            "club_reach": 0.0,
        }

    def club_trace(self) -> dict | None:
        return getattr(self, "_club_trace", None)

    def _course_command(self, c) -> MotorCommand:
        on_green = c["lie_green"] > 0.5
        near = c["target_distance"] < 1.0
        distance = c["target_distance"] * DISTANCE_FULL_SCALE_M if near else c["target_far"] * FAR_FULL_SCALE_M
        if on_green and distance < 25.0:
            self._club_trace = {
                "readout": "mock heuristic",
                "senses": "on the green, target within 25 m (no neurons)",
                "inputs": "lie",
                "rule": "putter on the green",
                "club_reach": 0.0,
            }
            return MotorCommand(channels=self._putt_channels(c), source=self.info.id)
        rng = self._rng
        # Caddie table: the physics' own nominal totals (carry + roll) for each full club.
        table = nominal_distances()
        need = distance * (1.0 + (0.06 if c["water_on_line"] > 0.0 else 0.0))
        if c["lie_sand"] > 0.5:
            need /= LIE_SPEED_FACTOR["sand"]
        elif c["lie_rough"] > 0.5:
            need /= LIE_SPEED_FACTOR["rough"]
        lofted = [club for club in BAG if not club.is_putter]
        club = next((k for k in lofted if table[k.id]["total_m"] >= need), lofted[-1])
        self._club_trace = {
            "readout": "mock heuristic",
            "senses": "target distance, lie and water from the sensory channels (no neurons)",
            "inputs": "the distance still needed, corrected for lie and water",
            "needed_m": round(need, 2),
            "rule": "caddie table: the shortest club whose nominal total distance covers the need",
            "club_reach": round(reach_for(club), 6),
        }
        ratio = min(1.0, need / table[club.id]["total_m"])
        fraction = ratio ** (1.0 / 1.4)  # partial swings: distance ~ (speed fraction)^1.4 (fit to the physics)
        power = _clip((fraction - FULL_MIN_SWING) / (1.0 - FULL_MIN_SWING)) * (1.0 + rng.gauss(0.0, self.power_noise))
        bearing_deg = (c["target_left"] - c["target_right"]) * BEARING_FULL_SCALE_DEG
        aim_deg = bearing_deg + rng.gauss(0.0, FULL_SWING_AIM_NOISE_FACTOR * self.aim_noise_deg)
        face = rng.gauss(0.0, 0.25)
        return MotorCommand(
            channels={
                "aim_left": _clip(aim_deg / MAX_AIM_DEG),
                "aim_right": _clip(-aim_deg / MAX_AIM_DEG),
                "stroke_power": _clip(power),
                "stroke_tempo": _clip(0.5 + rng.gauss(0.0, 0.04)),
                "face_open": _clip(-face),
                "face_closed": _clip(face),
                "strike": 1.0,
                "club_reach": reach_for(club),
            },
            source=self.info.id,
        )
