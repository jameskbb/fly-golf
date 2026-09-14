"""Deterministic putting-green physics.

The backend is authoritative. The browser only renders the trajectory returned
here, so display frame rate can never change an experiment result.

Coordinate frame (backend "world"): metres; +x east, +y north, +z up. Headings
are radians, counter-clockwise from +x. The frontend maps (x, y, z) to three.js
(x, z_up, -y).

Model (documented in docs/PROVENANCE.md, "Physics assumptions"):

* The green is a tilted plane h(x, y) = slope_x * x + slope_y * y (small-angle).
* A rolling solid sphere on an incline accelerates at (5/7) g sin(theta)
  down the fall line (no slip).
* Rolling resistance is a constant deceleration calibrated from the
  stimpmeter: a ball released at 1.83 m/s on a flat green rolls `stimp` feet,
  so decel = v0^2 / (2 * stimp_ft * 0.3048).
* Integration: fixed dt = 1/240 s, semi-implicit Euler. Friction is applied
  as a speed reduction clamped at zero, so it never reverses the ball. A
  ball at rest stays at rest whenever the slope force <= rolling resistance.
* Cup capture is a simplification of Holmes, B. W. (1991), "Putting: How a
  golf ball and hole interact", Am. J. Phys. 59(2): the maximum holing speed
  for a centred ball is taken as 1.63 m/s, falling to zero at the rim as
  sqrt(1 - (offset/R)^2) (our interpolation, not Holmes' full model). A ball
  over the cup that is too fast "lips": it loses speed and is deflected away
  from the cup centre, deterministically.

All arithmetic uses Python floats with a fixed operation order, so identical
inputs give bit-identical trajectories on the same platform.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

PHYSICS_VERSION = "putting-physics-v2"  # v2: lip-out evaluated per cup pass (v1 applied it on entry)

G = 9.80665
BALL_RADIUS_M = 0.021335  # 1.68 in diameter
CUP_RADIUS_M = 0.054  # 4.25 in diameter
STIMP_RELEASE_SPEED = 1.83  # m/s at the bottom of the USGA stimpmeter ramp
FOOT_M = 0.3048
ROLL_FACTOR = 5.0 / 7.0  # solid sphere rolling without slip
DT = 1.0 / 240.0
SAMPLE_EVERY = 4  # trajectory samples at 60 Hz
MAX_TIME_S = 30.0
MAX_CAPTURE_SPEED = 1.63  # m/s, centred ball
LIP_SPEED_RETAIN = 0.7  # fraction of speed kept after a full rim lip
LIP_MAX_DEFLECT_RAD = math.radians(20.0)


class Outcome(StrEnum):
    HOLED = "holed"
    STOPPED = "stopped"  # came to rest on the green
    OFF_GREEN = "off_green"
    TIMEOUT = "timeout"
    NO_CONTACT = "no_contact"  # whiff: strike channel did not fire


@dataclass(frozen=True)
class Green:
    """A planar putting surface."""

    stimp_ft: float = 10.0
    slope_x: float = 0.0  # rise (m) per metre travelled toward +x
    slope_y: float = 0.0
    radius_m: float = 12.0  # playable radius around the green centre
    center: tuple[float, float] = (0.0, 0.0)

    def __post_init__(self) -> None:
        if not (4.0 <= self.stimp_ft <= 16.0):
            raise ValueError("stimp_ft must be within [4, 16]")
        for s in (self.slope_x, self.slope_y):
            if not math.isfinite(s) or abs(s) > 0.2:
                raise ValueError("slope components must be finite and |slope| <= 0.2")
        if self.radius_m <= 0:
            raise ValueError("radius_m must be positive")

    @property
    def rolling_decel(self) -> float:
        return STIMP_RELEASE_SPEED * STIMP_RELEASE_SPEED / (2.0 * self.stimp_ft * FOOT_M)

    @property
    def slope_accel(self) -> tuple[float, float]:
        """Acceleration of a rolling ball due to gravity along the plane."""
        return (-ROLL_FACTOR * G * self.slope_x, -ROLL_FACTOR * G * self.slope_y)

    def height(self, x: float, y: float) -> float:
        return self.slope_x * (x - self.center[0]) + self.slope_y * (y - self.center[1])

    def on_green(self, x: float, y: float) -> bool:
        return math.hypot(x - self.center[0], y - self.center[1]) <= self.radius_m


@dataclass(frozen=True)
class Stroke:
    """Initial ball velocity imparted by the putter."""

    speed_mps: float
    heading_rad: float
    contact: bool = True

    def __post_init__(self) -> None:
        if not math.isfinite(self.speed_mps) or not (0.0 <= self.speed_mps <= 8.0):
            raise ValueError("speed_mps must be finite and within [0, 8]")
        if not math.isfinite(self.heading_rad):
            raise ValueError("heading_rad must be finite")


@dataclass
class RollResult:
    outcome: Outcome
    final_position: tuple[float, float]
    trajectory: list[tuple[float, float, float, float]]  # (t, x, y, z) at 60 Hz + final
    duration_s: float
    closest_approach_m: float
    max_speed_over_cup_mps: float | None
    lip_outs: int
    steps: int
    events: list[dict] = field(default_factory=list)


def _closest_point_on_segment(ax: float, ay: float, bx: float, by: float, px: float, py: float) -> tuple[float, float]:
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    if denom == 0.0:
        return ax, ay
    t = ((px - ax) * dx + (py - ay) * dy) / denom
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return ax + t * dx, ay + t * dy


def capture_speed(offset_m: float) -> float:
    """Maximum speed (m/s) at which a ball passing `offset_m` from the cup centre drops."""
    if offset_m >= CUP_RADIUS_M:
        return 0.0
    return MAX_CAPTURE_SPEED * math.sqrt(1.0 - (offset_m / CUP_RADIUS_M) ** 2)


def simulate_roll(
    green: Green,
    ball: tuple[float, float],
    cup: tuple[float, float],
    stroke: Stroke,
) -> RollResult:
    """Roll the ball from rest under `stroke` until it holes, stops, leaves the green or times out."""
    x, y = float(ball[0]), float(ball[1])
    cx, cy = float(cup[0]), float(cup[1])
    z0 = green.height(x, y) + BALL_RADIUS_M
    trajectory: list[tuple[float, float, float, float]] = [(0.0, x, y, z0)]
    events: list[dict] = []
    closest = math.hypot(x - cx, y - cy)

    if not stroke.contact:
        return RollResult(Outcome.NO_CONTACT, (x, y), trajectory, 0.0, closest, None, 0, 0, events)

    vx = stroke.speed_mps * math.cos(stroke.heading_rad)
    vy = stroke.speed_mps * math.sin(stroke.heading_rad)
    gx, gy = green.slope_accel
    decel = green.rolling_decel
    over_cup = math.hypot(x - cx, y - cy) <= CUP_RADIUS_M
    pass_min_offset = CUP_RADIUS_M
    max_speed_over_cup: float | None = None
    lip_outs = 0
    step = 0
    outcome = Outcome.TIMEOUT
    max_steps = int(round(MAX_TIME_S / DT))

    while step < max_steps:
        step += 1
        # Gravity along the plane, then rolling resistance as a clamped speed reduction.
        vx += gx * DT
        vy += gy * DT
        speed = math.hypot(vx, vy)
        if speed > 0.0:
            reduced = speed - decel * DT
            if reduced <= 0.0:
                vx = vy = 0.0
                speed = 0.0
            else:
                scale = reduced / speed
                vx *= scale
                vy *= scale
                speed = reduced
        nx = x + vx * DT
        ny = y + vy * DT

        # Cup interaction on the swept segment so fast balls cannot tunnel. A pass over the
        # cup is evaluated as a whole: the ball drops as soon as it is slow enough for its
        # current offset; only if it LEAVES the cup disc un-captured does it lip out, with
        # speed loss and deflection set by how centred the whole pass was.
        px, py = _closest_point_on_segment(x, y, nx, ny, cx, cy)
        offset = math.hypot(px - cx, py - cy)
        closest = min(closest, offset)
        if offset <= CUP_RADIUS_M:
            max_speed_over_cup = speed if max_speed_over_cup is None else max(max_speed_over_cup, speed)
            pass_min_offset = offset if not over_cup else min(pass_min_offset, offset)
            over_cup = True
            if speed <= capture_speed(offset):
                x, y = cx, cy
                trajectory.append((step * DT, x, y, green.height(x, y) + BALL_RADIUS_M - 2.0 * BALL_RADIUS_M))
                events.append({"t": step * DT, "type": "holed", "speed": speed, "offset": offset})
                outcome = Outcome.HOLED
                break
        elif over_cup:
            # Left the cup disc without dropping: one rim interaction for this pass.
            rim = pass_min_offset / CUP_RADIUS_M  # 0 = centred pass, 1 = grazed the edge
            retain = LIP_SPEED_RETAIN + (1.0 - LIP_SPEED_RETAIN) * rim
            # Deflect away from the cup: sign of cross product (velocity x to-cup).
            tcx, tcy = cx - x, cy - y
            cross = vx * tcy - vy * tcx
            direction = -1.0 if cross > 0.0 else 1.0
            angle = direction * LIP_MAX_DEFLECT_RAD * (1.0 - rim)
            cos_a, sin_a = math.cos(angle), math.sin(angle)
            vx, vy = (vx * cos_a - vy * sin_a) * retain, (vx * sin_a + vy * cos_a) * retain
            speed *= retain
            nx = x + vx * DT
            ny = y + vy * DT
            lip_outs += 1
            events.append({"t": step * DT, "type": "lip", "speed": speed, "offset": pass_min_offset})
            over_cup = False

        x, y = nx, ny
        if step % SAMPLE_EVERY == 0:
            trajectory.append((step * DT, x, y, green.height(x, y) + BALL_RADIUS_M))

        if not green.on_green(x, y):
            outcome = Outcome.OFF_GREEN
            break
        # At rest. It stays at rest only if gravity cannot overcome rolling resistance.
        if speed == 0.0 and math.hypot(gx, gy) <= decel:
            outcome = Outcome.STOPPED
            break

    t_end = step * DT
    if trajectory[-1][0] != t_end:
        trajectory.append((t_end, x, y, green.height(x, y) + BALL_RADIUS_M))
    return RollResult(
        outcome=outcome,
        final_position=(x, y),
        trajectory=trajectory,
        duration_s=t_end,
        closest_approach_m=closest,
        max_speed_over_cup_mps=max_speed_over_cup,
        lip_outs=lip_outs,
        steps=step,
        events=events,
    )


def rest_is_stable(green: Green) -> bool:
    """True when a stationary ball will not start rolling on this green."""
    gx, gy = green.slope_accel
    return math.hypot(gx, gy) <= green.rolling_decel
