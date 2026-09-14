"""Deterministic full-course ball physics: flight, bounce and roll over mixed surfaces.

Backend-authoritative like `physics.py` (which is left untouched for the practice green and
for replaying older records). Same world frame: metres, +x east, +y north, +z up, headings
counter-clockwise from +x.

Model (documented in docs/COURSE.md, "Physics assumptions"):

* Flight: point-mass ball with quadratic drag and Magnus lift,
  F = 0.5 rho A v^2 (C_D, C_L), C_D = 0.25 + 0.18 S, C_L = 0.38 (1 - exp(-S / 0.12)),
  S = r omega / v (spin factor). Spin decays exponentially (tau = 25 s). Backspin lifts;
  sidespin (+ = counter-clockwise seen from above) curves the ball left. No wind.
  These are round-number fits in the range reported for golf balls (e.g. Bearman & Harvey
  1976; Smits & Smith 1994), tuned so the bag produces typical carries. Not a CFD model.
* Landing: when the ball reaches the ground it bounces with a surface restitution; the
  horizontal speed keeps a surface fraction, reduced further by backspin (so wedges check
  and drivers release). Bouncing ends when the rebound is below 1 m/s; then it rolls.
* Roll: identical in form to the putting model (constant rolling deceleration, clamped;
  gravity along the tilted plane on the green only; the rest of the course is flat for
  physics). Rolling deceleration depends on the surface; on the green it is the stimpmeter
  value. Cup capture and lip-outs reuse the putting rule (Holmes 1991 simplification).
* A ball that lands on the flag's cup disc drops (a dunk). Water ends the shot where the
  ball enters it; leaving the corridor ends it in the trees (out of bounds).
* Integration: fixed dt = 1/240 s, semi-implicit Euler, samples at 60 Hz. Python floats in a
  fixed operation order, so identical inputs reproduce bit-identical trajectories.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from .physics import (
    BALL_RADIUS_M,
    CUP_RADIUS_M,
    DT,
    LIP_MAX_DEFLECT_RAD,
    LIP_SPEED_RETAIN,
    SAMPLE_EVERY,
    G,
    Green,
    _closest_point_on_segment,
    capture_speed,
)

COURSE_PHYSICS_VERSION = "course-physics-v2"  # v2: green collar height; closest approach on the ground only

RHO = 1.2  # kg/m^3, air at ~20 C
BALL_MASS_KG = 0.04593
BALL_AREA_M2 = math.pi * BALL_RADIUS_M * BALL_RADIUS_M
AERO_K = 0.5 * RHO * BALL_AREA_M2 / BALL_MASS_KG  # acceleration per (C * v^2)
CD0, CD_SPIN = 0.25, 0.18
CL_MAX, CL_SCALE = 0.38, 0.12
SPIN_DECAY_TAU_S = 25.0
RPM_TO_RADS = 2.0 * math.pi / 60.0
MAX_FLIGHT_S = 15.0
MAX_ROLL_S = 30.0
MIN_BOUNCE_VZ = 1.0  # m/s; below this the ball stops bouncing and rolls
SPIN_CHECK_PER_KRPM = 0.09  # fraction of horizontal speed removed per 1000 rpm of backspin at landing
SPIN_RETAIN_BOUNCE = 0.45
SURFACE_RECHECK_M = 0.15  # re-query the surface after moving this far (cheap point-in-polygon cache)


class Surface(StrEnum):
    TEE = "tee"
    FAIRWAY = "fairway"
    FRINGE = "fringe"
    GREEN = "green"
    ROUGH = "rough"
    SAND = "sand"
    WATER = "water"
    OOB = "oob"


@dataclass(frozen=True)
class SurfaceParams:
    roll_decel: float  # m/s^2 (green: from the stimpmeter instead)
    restitution: float  # vertical rebound fraction
    retain: float  # horizontal speed kept through a bounce (before spin)


SURFACE_PARAMS: dict[Surface, SurfaceParams] = {
    Surface.TEE: SurfaceParams(1.25, 0.32, 0.62),
    Surface.FAIRWAY: SurfaceParams(1.25, 0.32, 0.62),
    Surface.FRINGE: SurfaceParams(1.1, 0.28, 0.58),
    Surface.GREEN: SurfaceParams(0.0, 0.26, 0.58),
    Surface.ROUGH: SurfaceParams(3.4, 0.16, 0.40),
    Surface.SAND: SurfaceParams(9.0, 0.03, 0.08),
}


class Outcome(StrEnum):
    HOLED = "holed"
    STOPPED = "stopped"
    WATER = "water"
    OUT_OF_BOUNDS = "out_of_bounds"
    TIMEOUT = "timeout"
    NO_CONTACT = "no_contact"


class Terrain(Protocol):
    green: Green
    cup: tuple[float, float]

    def surface(self, x: float, y: float) -> Surface: ...

    def height(self, x: float, y: float) -> float: ...


class FlatTerrain:
    """Endless flat fairway with a far-away green: used for the nominal club distances and tests."""

    def __init__(self, surface: Surface = Surface.FAIRWAY):
        self._surface = surface
        self.green = Green(stimp_ft=10.0, radius_m=10.0, center=(0.0, 10_000.0))
        self.cup = (0.0, 10_000.0)

    def surface(self, x: float, y: float) -> Surface:
        return Surface.GREEN if self.green.on_green(x, y) else self._surface

    def height(self, x: float, y: float) -> float:
        return self.green.height(x, y) if self.green.on_green(x, y) else 0.0


@dataclass(frozen=True)
class Launch:
    """Ball state leaving the clubface."""

    speed_mps: float
    heading_rad: float
    launch_deg: float
    backspin_rpm: float
    sidespin_rpm: float  # + = curves left (counter-clockwise seen from above)
    contact: bool = True

    def __post_init__(self) -> None:
        for name in ("speed_mps", "heading_rad", "launch_deg", "backspin_rpm", "sidespin_rpm"):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        if not (0.0 <= self.speed_mps <= 90.0):
            raise ValueError("speed_mps must be within [0, 90]")
        if not (0.0 <= self.launch_deg <= 70.0):
            raise ValueError("launch_deg must be within [0, 70]")
        if not (0.0 <= self.backspin_rpm <= 15000.0) or abs(self.sidespin_rpm) > 6000.0:
            raise ValueError("spin out of range")

    def to_dict(self) -> dict:
        return {
            "speed_mps": self.speed_mps,
            "heading_rad": self.heading_rad,
            "launch_deg": self.launch_deg,
            "backspin_rpm": self.backspin_rpm,
            "sidespin_rpm": self.sidespin_rpm,
            "contact": self.contact,
        }


@dataclass
class ShotResult:
    outcome: Outcome
    final_position: tuple[float, float]
    final_surface: Surface
    trajectory: list[tuple[float, float, float, float]]  # (t, x, y, z) at 60 Hz + final
    duration_s: float
    carry_m: float  # horizontal distance to the first landing (0 for a putt)
    apex_m: float  # max height above the launch point
    closest_approach_m: float
    lip_outs: int
    hazard_entry: tuple[float, float] | None  # where the ball entered water / left the corridor
    events: list[dict] = field(default_factory=list)


def lift_drag(speed: float, omega: float) -> tuple[float, float]:
    """(C_L, C_D) for a ball moving at `speed` m/s spinning at `omega` rad/s."""
    s = BALL_RADIUS_M * omega / speed if speed > 0.0 else 0.0
    return CL_MAX * (1.0 - math.exp(-s / CL_SCALE)), CD0 + CD_SPIN * s


def simulate_shot(terrain: Terrain, ball: tuple[float, float], launch: Launch) -> ShotResult:
    """Fly (if lofted), bounce and roll the ball until it holes, rests, or reaches a hazard."""
    x, y = float(ball[0]), float(ball[1])
    z = terrain.height(x, y) + BALL_RADIUS_M
    z0 = z
    cx, cy = float(terrain.cup[0]), float(terrain.cup[1])
    trajectory: list[tuple[float, float, float, float]] = [(0.0, x, y, z)]
    events: list[dict] = []
    closest = math.hypot(x - cx, y - cy)
    start_surface = terrain.surface(x, y)
    if not launch.contact:
        return ShotResult(
            Outcome.NO_CONTACT, (x, y), start_surface, trajectory, 0.0, 0.0, 0.0, closest, 0, None, events
        )

    ch, sh = math.cos(launch.heading_rad), math.sin(launch.heading_rad)
    cl, sl = math.cos(math.radians(launch.launch_deg)), math.sin(math.radians(launch.launch_deg))
    vx, vy, vz = launch.speed_mps * cl * ch, launch.speed_mps * cl * sh, launch.speed_mps * sl
    # Spin vector: backspin about the horizontal axis pointing to the RIGHT of travel
    # (so that omega x v lifts), sidespin about +z.
    wb = launch.backspin_rpm * RPM_TO_RADS
    ws = launch.sidespin_rpm * RPM_TO_RADS
    wx, wy, wz = wb * sh, -wb * ch, ws
    step = 0
    t_limit = int(round(MAX_FLIGHT_S / DT))
    carry = 0.0
    apex = 0.0
    landed = False
    decay = math.exp(-DT / SPIN_DECAY_TAU_S)
    airborne = launch.launch_deg > 0.0 and vz > 0.0

    # ---------------- flight + bounces
    while airborne and step < t_limit:
        step += 1
        speed = math.sqrt(vx * vx + vy * vy + vz * vz)
        omega = math.sqrt(wx * wx + wy * wy + wz * wz)
        c_l, c_d = lift_drag(speed, omega)
        ax = ay = 0.0
        az = -G
        if speed > 0.0:
            kd = AERO_K * c_d * speed
            ax -= kd * vx
            ay -= kd * vy
            az -= kd * vz
            if omega > 0.0:
                # Magnus direction: (omega x v) / |omega x v|
                mx = wy * vz - wz * vy
                my = wz * vx - wx * vz
                mz = wx * vy - wy * vx
                mn = math.sqrt(mx * mx + my * my + mz * mz)
                if mn > 0.0:
                    kl = AERO_K * c_l * speed * speed / mn
                    ax += kl * mx
                    ay += kl * my
                    az += kl * mz
        vx += ax * DT
        vy += ay * DT
        vz += az * DT
        wx *= decay
        wy *= decay
        wz *= decay
        nx, ny, nz = x + vx * DT, y + vy * DT, z + vz * DT
        ground = terrain.height(nx, ny) + BALL_RADIUS_M
        if nz - z0 > apex:
            apex = nz - z0
        if nz <= ground:
            # Contact with the ground this step.
            x, y, z = nx, ny, ground
            surf = terrain.surface(x, y)
            if not landed:
                landed = True
                carry = math.hypot(x - ball[0], y - ball[1])
                events.append({"t": step * DT, "type": "land", "x": x, "y": y, "surface": surf.value})
            if surf is Surface.WATER or surf is Surface.OOB:
                trajectory.append((step * DT, x, y, z))
                outcome = Outcome.WATER if surf is Surface.WATER else Outcome.OUT_OF_BOUNDS
                events.append({"t": step * DT, "type": surf.value})
                return ShotResult(outcome, (x, y), surf, trajectory, step * DT, carry, apex, closest, 0, (x, y), events)
            offset = math.hypot(x - cx, y - cy)
            closest = min(closest, offset)
            if offset <= CUP_RADIUS_M:
                trajectory.append((step * DT, cx, cy, terrain.height(cx, cy) - BALL_RADIUS_M))
                events.append({"t": step * DT, "type": "holed", "dunk": True, "speed": speed, "offset": offset})
                return ShotResult(
                    Outcome.HOLED, (cx, cy), Surface.GREEN, trajectory, step * DT, carry, apex, 0.0, 0, None, events
                )
            params = SURFACE_PARAMS[surf]
            back_krpm = abs(wx * sh - wy * ch) / RPM_TO_RADS / 1000.0
            check = max(0.0, 1.0 - SPIN_CHECK_PER_KRPM * back_krpm)
            h_keep = params.retain * check
            vx *= h_keep
            vy *= h_keep
            vz = -vz * params.restitution
            wx *= SPIN_RETAIN_BOUNCE
            wy *= SPIN_RETAIN_BOUNCE
            wz *= SPIN_RETAIN_BOUNCE
            events.append({"t": step * DT, "type": "bounce", "surface": surf.value, "vz": vz})
            if vz < MIN_BOUNCE_VZ:
                airborne = False
        else:
            x, y, z = nx, ny, nz  # airborne: passing over the cup is not an approach
        if step % SAMPLE_EVERY == 0:
            trajectory.append((step * DT, x, y, z))
    if airborne:  # pathological launch: never came down within MAX_FLIGHT_S
        trajectory.append((step * DT, x, y, z))
        return ShotResult(
            Outcome.TIMEOUT, (x, y), terrain.surface(x, y), trajectory, step * DT, carry, apex, closest, 0, None, events
        )
    if launch.launch_deg <= 0.0:
        # A putt (or any unlofted strike) starts rolling at once.
        vx, vy = launch.speed_mps * ch, launch.speed_mps * sh

    # ---------------- roll
    green = terrain.green
    gx, gy = green.slope_accel
    green_decel = green.rolling_decel
    surf = terrain.surface(x, y)
    last_check = (x, y)
    over_cup = math.hypot(x - cx, y - cy) <= CUP_RADIUS_M
    pass_min_offset = CUP_RADIUS_M
    lip_outs = 0
    roll_limit = step + int(round(MAX_ROLL_S / DT))
    outcome = Outcome.TIMEOUT
    while step < roll_limit:
        step += 1
        on_green = surf is Surface.GREEN
        if on_green:
            vx += gx * DT
            vy += gy * DT
            decel = green_decel
        else:
            decel = SURFACE_PARAMS[surf].roll_decel
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

        if on_green and (abs(nx - cx) < 1.0 and abs(ny - cy) < 1.0):
            # Cup interaction on the swept segment (same rule as physics.simulate_roll).
            px, py = _closest_point_on_segment(x, y, nx, ny, cx, cy)
            offset = math.hypot(px - cx, py - cy)
            closest = min(closest, offset)
            if offset <= CUP_RADIUS_M:
                pass_min_offset = offset if not over_cup else min(pass_min_offset, offset)
                over_cup = True
                if speed <= capture_speed(offset):
                    x, y = cx, cy
                    trajectory.append((step * DT, x, y, terrain.height(x, y) - BALL_RADIUS_M))
                    events.append({"t": step * DT, "type": "holed", "speed": speed, "offset": offset})
                    outcome = Outcome.HOLED
                    break
            elif over_cup:
                rim = pass_min_offset / CUP_RADIUS_M
                retain = LIP_SPEED_RETAIN + (1.0 - LIP_SPEED_RETAIN) * rim
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
        else:
            closest = min(closest, math.hypot(nx - cx, ny - cy))

        x, y = nx, ny
        if abs(x - last_check[0]) + abs(y - last_check[1]) >= SURFACE_RECHECK_M or speed == 0.0:
            surf = terrain.surface(x, y)
            last_check = (x, y)
        if step % SAMPLE_EVERY == 0:
            trajectory.append((step * DT, x, y, terrain.height(x, y) + BALL_RADIUS_M))
        if surf is Surface.WATER or surf is Surface.OOB:
            outcome = Outcome.WATER if surf is Surface.WATER else Outcome.OUT_OF_BOUNDS
            events.append({"t": step * DT, "type": surf.value})
            t_end = step * DT
            if trajectory[-1][0] != t_end:
                trajectory.append((t_end, x, y, terrain.height(x, y) + BALL_RADIUS_M))
            return ShotResult(outcome, (x, y), surf, trajectory, t_end, carry, apex, closest, lip_outs, (x, y), events)
        if speed == 0.0 and (surf is not Surface.GREEN or math.hypot(gx, gy) <= green_decel):
            outcome = Outcome.STOPPED
            break

    t_end = step * DT
    if trajectory[-1][0] != t_end:
        trajectory.append((t_end, x, y, terrain.height(x, y) + BALL_RADIUS_M))
    final_surface = Surface.GREEN if outcome is Outcome.HOLED else terrain.surface(x, y)
    return ShotResult(outcome, (x, y), final_surface, trajectory, t_end, carry, apex, closest, lip_outs, None, events)
