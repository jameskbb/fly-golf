"""Motor decoding (channels -> putter stroke) and motor targets.

The decoder is the fly's *embodiment*: a fixed, documented transform shared by
every controller. It does not look at the cup or the green; it only uses the
motor channels plus the body heading at address (where the fly is facing).
Constants are documented in docs/MOTOR_MAPPING.md; bump MOTOR_MAPPING_VERSION
when changing them.

Motor targets decouple "what stroke was commanded" from "who executes it":
`SimulationMotorTarget` drives the physics; `HardwareMotorTarget` is the
reserved interface for a future robotic putter.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Protocol

from ..golf.clubs import Club, club_from_reach
from ..golf.env import Observation, PuttingEnvironment, ShotOutcome
from ..golf.flight import Launch
from ..golf.physics import RollResult, Stroke
from .interfaces import MotorCommand

MOTOR_MAPPING_VERSION = "motor-mapping-v1"

MAX_AIM_DEG = 25.0  # full aim_left/right swing relative to body heading
MAX_FACE_DEG = 4.0  # full face open/closed
FACE_START_FACTOR = 0.85  # fraction of face angle that sets start direction (putting rule of thumb)
MAX_BALL_SPEED_MPS = 4.2  # stroke_power = 1.0
TEMPO_IDEAL = 0.5
TEMPO_SPEED_PENALTY = 0.12  # max fractional ball-speed loss at extreme tempo
STRIKE_THRESHOLD = 0.5  # strike channel must reach this to make contact
BACKSWING_BASE_S = 0.35
BACKSWING_TEMPO_SPAN_S = 0.5


@dataclass(frozen=True)
class DecodedStroke:
    stroke: Stroke
    aim_deg: float  # + = left of body heading
    face_deg: float  # + = closed (starts ball left)
    start_offset_deg: float  # total start direction offset from body heading, + = left
    power: float
    tempo: float
    smash: float
    contact: bool
    backswing_s: float
    downswing_s: float
    version: str = MOTOR_MAPPING_VERSION

    def to_dict(self) -> dict:
        d = asdict(self)
        d["stroke"] = {
            "speed_mps": self.stroke.speed_mps,
            "heading_rad": self.stroke.heading_rad,
            "contact": self.stroke.contact,
        }
        return d


class MotorDecoder:
    version = MOTOR_MAPPING_VERSION

    def decode(self, cmd: MotorCommand, body_heading_rad: float) -> DecodedStroke:
        if not isinstance(cmd, MotorCommand):
            raise ValueError("MotorDecoder.decode requires a MotorCommand")
        if not math.isfinite(body_heading_rad):
            raise ValueError("body heading must be finite")
        c = cmd.channels
        aim = (c["aim_left"] - c["aim_right"]) * MAX_AIM_DEG
        face = (c["face_closed"] - c["face_open"]) * MAX_FACE_DEG
        start_offset = aim + FACE_START_FACTOR * face
        tempo = c["stroke_tempo"]
        smash = 1.0 - TEMPO_SPEED_PENALTY * min(1.0, abs(tempo - TEMPO_IDEAL) / 0.5)
        power = c["stroke_power"]
        contact = c["strike"] >= STRIKE_THRESHOLD
        speed = power * MAX_BALL_SPEED_MPS * smash if contact else 0.0
        heading = body_heading_rad + math.radians(start_offset)
        return DecodedStroke(
            stroke=Stroke(speed_mps=round(speed, 12), heading_rad=heading, contact=contact),
            aim_deg=aim,
            face_deg=face,
            start_offset_deg=start_offset,
            power=power,
            tempo=tempo,
            smash=smash,
            contact=contact,
            backswing_s=BACKSWING_BASE_S + BACKSWING_TEMPO_SPAN_S * (1.0 - tempo),
            downswing_s=0.18 + 0.12 * (1.0 - tempo),
        )


class MotorTarget(Protocol):
    id: str

    def execute(self, decoded: DecodedStroke) -> tuple[RollResult, ShotOutcome]: ...


class SimulationMotorTarget:
    """Executes strokes in the deterministic backend physics."""

    id = "simulation"

    def __init__(self, env: PuttingEnvironment):
        self.env = env

    def execute(self, decoded: DecodedStroke) -> tuple[RollResult, ShotOutcome]:
        return self.env.step(decoded.stroke)


class HardwareMotorTarget:
    """Reserved for a future robotic putter (not implemented in V1).

    A hardware target would receive the same `DecodedStroke` (start direction,
    ball speed, tempo, contact) and must report the measured result back as a
    `RollResult`-compatible trajectory so experiments stay comparable.
    """

    id = "hardware"

    def execute(self, decoded: DecodedStroke) -> tuple[RollResult, ShotOutcome]:
        raise NotImplementedError("Hardware motor targets are future work; see docs/MOTOR_MAPPING.md")


def body_heading(obs: Observation) -> float:
    return obs.body_heading_rad


# ---------------------------------------------------------------------------------------------
# motor-mapping-v2: the full bag. The putter stroke is exactly motor-mapping-v1; the new
# `club_reach` channel picks the club, and lofted clubs produce a flight launch.

MOTOR_MAPPING_VERSION_V2 = "motor-mapping-v2"
FULL_FACE_START_FACTOR = 0.75  # with a full swing the face sets less of the start line than with a putter
SIDESPIN_RPM_PER_FACE_DEG = 120.0  # face closed (+) relative to the path -> draw/hook spin (curves left)
FULL_MIN_SWING = 0.3  # ball-speed fraction of a full swing at stroke_power = 0 (a short pitch)


@dataclass(frozen=True)
class DecodedSwing:
    club: Club
    launch: Launch
    aim_deg: float
    face_deg: float
    start_offset_deg: float
    power: float
    swing_fraction: float  # fraction of the club's full ball speed (1.0 for the putter's v1 scale)
    tempo: float
    smash: float
    contact: bool
    club_reach: float
    forced_club: bool  # True when the environment allows only one club (practice green: putter)
    backswing_s: float
    downswing_s: float
    version: str = MOTOR_MAPPING_VERSION_V2

    @property
    def stroke(self) -> Stroke:
        """The putting-physics stroke (practice green). Only meaningful for the putter."""
        return Stroke(
            speed_mps=round(self.launch.speed_mps, 12), heading_rad=self.launch.heading_rad, contact=self.contact
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["club"] = self.club.to_dict()
        d["launch"] = self.launch.to_dict()
        return d


class MotorDecoderV2:
    """Channels + body heading -> club and ball launch. Never sees the cup, the lie or the green."""

    version = MOTOR_MAPPING_VERSION_V2

    def decode(self, cmd: MotorCommand, body_heading_rad: float, forced_club: Club | None = None) -> DecodedSwing:
        if not isinstance(cmd, MotorCommand):
            raise ValueError("MotorDecoderV2.decode requires a MotorCommand")
        if "club_reach" not in cmd.channels:
            raise ValueError("motor-mapping-v2 needs the club_reach channel (got a v1 command)")
        if not math.isfinite(body_heading_rad):
            raise ValueError("body heading must be finite")
        c = cmd.channels
        club = forced_club or club_from_reach(c["club_reach"])
        aim = (c["aim_left"] - c["aim_right"]) * MAX_AIM_DEG
        face = (c["face_closed"] - c["face_open"]) * MAX_FACE_DEG
        tempo = c["stroke_tempo"]
        smash = 1.0 - TEMPO_SPEED_PENALTY * min(1.0, abs(tempo - TEMPO_IDEAL) / 0.5)
        power = c["stroke_power"]
        contact = c["strike"] >= STRIKE_THRESHOLD
        if club.is_putter:
            start_offset = aim + FACE_START_FACTOR * face
            fraction = power
            speed = power * MAX_BALL_SPEED_MPS * smash if contact else 0.0
            launch_deg = backspin = sidespin = 0.0
            backswing = BACKSWING_BASE_S + BACKSWING_TEMPO_SPAN_S * (1.0 - tempo)
            downswing = 0.18 + 0.12 * (1.0 - tempo)
        else:
            start_offset = aim + FULL_FACE_START_FACTOR * face
            fraction = FULL_MIN_SWING + (1.0 - FULL_MIN_SWING) * power
            speed = club.ball_speed_mps * fraction * smash if contact else 0.0
            launch_deg = club.launch_deg
            backspin = club.spin_rpm * fraction
            sidespin = SIDESPIN_RPM_PER_FACE_DEG * face
            backswing = 0.55 + 0.45 * (1.0 - tempo)
            downswing = 0.2 + 0.1 * (1.0 - tempo)
        heading = body_heading_rad + math.radians(start_offset)
        return DecodedSwing(
            club=club,
            launch=Launch(speed, heading, launch_deg, backspin, sidespin, contact),
            aim_deg=aim,
            face_deg=face,
            start_offset_deg=start_offset,
            power=power,
            swing_fraction=fraction,
            tempo=tempo,
            smash=smash,
            contact=contact,
            club_reach=c["club_reach"],
            forced_club=forced_club is not None,
            backswing_s=backswing,
            downswing_s=downswing,
        )
