"""The Fly Golf front nine: nine hand-authored holes (par 36).

Geometry lives in each hole's own frame: metres, the tee at the origin, the hole playing
roughly north (+y). Surfaces are polygons (fairways, bunkers, water) plus a circular, tilted
green. Everything outside the hole's corridor (a band around the routing line) is trees, i.e.
out of bounds. Tree positions are generated deterministically for the renderer only; they do
not collide with the ball.

The hole also defines its ROUTING: the sequence of aiming points a player follows (tee →
landing areas → pin). The "target" the fly perceives is the pin once it is within
TARGET_REACH_M, else the next routing point at least TARGET_MIN_AHEAD_M away. This is part of
the environment (like yardage markers and a
caddie pointing down the fairway), not a controller decision; see docs/COURSE.md.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from functools import cached_property

from .flight import Surface
from .physics import Green

COURSE_VERSION = "front-nine-v2"  # v2: routing skips near points; green collar height
COURSE_NAME = "Fly Golf National · Front Nine"

CORRIDOR_HALF_WIDTH_M = 42.0  # beyond this distance from the routing line: trees (out of bounds)
GREEN_APRON_M = 26.0  # the corridor also includes a disc this much wider than the green
TEE_RADIUS_M = 5.0
FRINGE_M = 1.5
COLLAR_M = 4.0  # beyond the fringe, the green's rim height blends down to the flat hole over this width
TARGET_REACH_M = 225.0  # the fly looks at the pin once it is this close
TARGET_MIN_AHEAD_M = 60.0  # a routing point closer than this is skipped (never lay up a wedge short of it)
WATER_LINE_STEP_M = 2.0

Point = tuple[float, float]


@dataclass(frozen=True)
class Polygon:
    points: tuple[Point, ...]

    @cached_property
    def bbox(self) -> tuple[float, float, float, float]:
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return min(xs), min(ys), max(xs), max(ys)

    def contains(self, x: float, y: float) -> bool:
        x0, y0, x1, y1 = self.bbox
        if x < x0 or x > x1 or y < y0 or y > y1:
            return False
        inside = False
        pts = self.points
        j = len(pts) - 1
        for i in range(len(pts)):
            xi, yi = pts[i]
            xj, yj = pts[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
        return inside

    def to_list(self) -> list[list[float]]:
        return [[round(x, 3), round(y, 3)] for x, y in self.points]


def blob(
    cx: float, cy: float, rx: float, ry: float, rot_deg: float = 0.0, seed: int = 0, wobble: float = 0.1, n: int = 56
) -> Polygon:
    """An organic ellipse (bunkers, ponds): deterministic low-frequency wobble on the radius."""
    rng = random.Random(f"blob:{seed}:{cx}:{cy}")
    p1, p2, p3 = (rng.uniform(0, 2 * math.pi) for _ in range(3))
    rot = math.radians(rot_deg)
    cr, sr = math.cos(rot), math.sin(rot)
    pts = []
    for k in range(n):
        a = 2 * math.pi * k / n
        w = 1.0 + wobble * (0.55 * math.sin(2 * a + p1) + 0.3 * math.sin(3 * a + p2) + 0.15 * math.sin(5 * a + p3))
        ex, ey = rx * w * math.cos(a), ry * w * math.sin(a)
        pts.append((cx + ex * cr - ey * sr, cy + ex * sr + ey * cr))
    return Polygon(tuple(pts))


def _catmull_rom(points: list[Point], sub: int = 10) -> list[Point]:
    if len(points) < 3:
        (ax, ay), (bx, by) = points
        return [(ax + (bx - ax) * i / sub, ay + (by - ay) * i / sub) for i in range(sub + 1)]
    pts = [points[0], *points, points[-1]]
    out: list[Point] = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        for s in range(sub):
            t = s / sub
            t2, t3 = t * t, t * t * t
            out.append(
                tuple(
                    0.5
                    * (
                        2 * p1[k]
                        + (-p0[k] + p2[k]) * t
                        + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2
                        + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3
                    )
                    for k in range(2)
                )
            )
    out.append(points[-1])
    return out


def ribbon(
    centerline: list[Point], half_width: float, cap_segments: int = 8, seed: int = 0, wobble: float = 0.08
) -> Polygon:
    """A smooth strip around a centreline with rounded ends (fairways, creeks)."""
    c = _catmull_rom(centerline)
    rng = random.Random(f"ribbon:{seed}:{centerline[0]}")
    ph = rng.uniform(0, 2 * math.pi)
    left: list[Point] = []
    right: list[Point] = []
    for i, (x, y) in enumerate(c):
        ax, ay = c[max(0, i - 1)]
        bx, by = c[min(len(c) - 1, i + 1)]
        dx, dy = bx - ax, by - ay
        d = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / d, dx / d
        w = half_width * (1.0 + wobble * math.sin(i * 0.37 + ph))
        left.append((x + nx * w, y + ny * w))
        right.append((x - nx * w, y - ny * w))

    def cap(center: Point, a: Point, sign: float) -> list[Point]:
        ang0 = math.atan2(a[1] - center[1], a[0] - center[0])
        r = math.hypot(a[0] - center[0], a[1] - center[1])
        return [
            (
                center[0] + r * math.cos(ang0 + sign * math.pi * k / cap_segments),
                center[1] + r * math.sin(ang0 + sign * math.pi * k / cap_segments),
            )
            for k in range(1, cap_segments)
        ]

    # left side forward, round the far end, right side back, round the near end
    far = cap(c[-1], left[-1], -1.0)
    near = cap(c[0], right[0], -1.0)
    return Polygon(tuple(left + far + right[::-1] + near))


def _dist_to_polyline(x: float, y: float, line: tuple[Point, ...]) -> tuple[float, float]:
    """(distance, arc length of the closest point) from (x, y) to a polyline."""
    best_d, best_s, s0 = math.inf, 0.0, 0.0
    for (ax, ay), (bx, by) in zip(line, line[1:], strict=False):
        dx, dy = bx - ax, by - ay
        seg = math.hypot(dx, dy)
        t = 0.0 if seg == 0.0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (seg * seg)))
        px, py = ax + t * dx, ay + t * dy
        d = math.hypot(x - px, y - py)
        if d < best_d:
            best_d, best_s = d, s0 + t * seg
        s0 += seg
    return best_d, best_s


@dataclass(frozen=True)
class HoleSpec:
    number: int
    name: str
    par: int
    description: str
    route: tuple[Point, ...]  # tee, aiming points..., cup
    green: Green
    fairways: tuple[Polygon, ...] = ()
    bunkers: tuple[Polygon, ...] = ()
    water: tuple[Polygon, ...] = ()
    trees_seed: int = 0
    extra_fields: dict = field(default_factory=dict)

    # ---- Terrain protocol (flight.py) ----------------------------------------------------
    @property
    def cup(self) -> Point:
        return self.route[-1]

    @property
    def tee(self) -> Point:
        return self.route[0]

    def in_corridor(self, x: float, y: float) -> bool:
        if math.hypot(x - self.green.center[0], y - self.green.center[1]) <= self.green.radius_m + GREEN_APRON_M:
            return True
        return _dist_to_polyline(x, y, self.route)[0] <= CORRIDOR_HALF_WIDTH_M

    def surface(self, x: float, y: float) -> Surface:
        for w in self.water:
            if w.contains(x, y):
                return Surface.WATER
        if not self.in_corridor(x, y):
            return Surface.OOB
        dg = math.hypot(x - self.green.center[0], y - self.green.center[1])
        if dg <= self.green.radius_m:
            return Surface.GREEN
        if dg <= self.green.radius_m + FRINGE_M:
            return Surface.FRINGE
        for b in self.bunkers:
            if b.contains(x, y):
                return Surface.SAND
        if math.hypot(x - self.tee[0], y - self.tee[1]) <= TEE_RADIUS_M:
            return Surface.TEE
        for f in self.fairways:
            if f.contains(x, y):
                return Surface.FAIRWAY
        return Surface.ROUGH

    def height(self, x: float, y: float) -> float:
        """Ground height: the tilted green, a collar that blends its rim down to the flat hole.

        Rolling physics feels gravity on the green only; the collar exists so the ball's height
        (and the renderer, which uses the same formula) never steps at the rim (docs/COURSE.md).
        """
        g = self.green
        dx, dy = x - g.center[0], y - g.center[1]
        d = math.hypot(dx, dy)
        if d <= g.radius_m:
            return g.height(x, y)
        outer = g.radius_m + FRINGE_M + COLLAR_M
        if d >= outer:
            return 0.0
        t = (d - g.radius_m) / (outer - g.radius_m)
        s = t * t * (3.0 - 2.0 * t)
        rim = g.height(g.center[0] + dx / d * g.radius_m, g.center[1] + dy / d * g.radius_m)
        return rim * (1.0 - s)

    # ---- routing -------------------------------------------------------------------------
    @cached_property
    def _route_s(self) -> list[float]:
        s = [0.0]
        for (ax, ay), (bx, by) in zip(self.route, self.route[1:], strict=False):
            s.append(s[-1] + math.hypot(bx - ax, by - ay))
        return s

    @property
    def length_m(self) -> float:
        return self._route_s[-1]

    def target_for(self, ball: Point) -> Point:
        """The aiming point the fly perceives from `ball` (see module docstring).

        The pin once it is within TARGET_REACH_M; otherwise the next routing point ahead of the
        ball that is at least TARGET_MIN_AHEAD_M away (a landing area a wedge away is skipped).
        """
        cx, cy = self.cup
        if math.hypot(cx - ball[0], cy - ball[1]) <= TARGET_REACH_M:
            return self.cup
        _, s_ball = _dist_to_polyline(ball[0], ball[1], self.route)
        for p, s in zip(self.route[1:-1], self._route_s[1:-1], strict=True):
            if s > s_ball and math.hypot(p[0] - ball[0], p[1] - ball[1]) >= TARGET_MIN_AHEAD_M:
                return p
        return self.cup

    def water_on_line(self, a: Point, b: Point) -> float:
        """Fraction of the straight line a -> b that passes over water (0 if none)."""
        if not self.water:
            return 0.0
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(2, min(160, int(d / WATER_LINE_STEP_M)))
        wet = 0
        for k in range(1, n + 1):
            t = k / n
            x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            if any(w.contains(x, y) for w in self.water):
                wet += 1
        return wet / n

    # ---- rendering data ------------------------------------------------------------------
    @cached_property
    def trees(self) -> list[list[float]]:
        """Decorative tree positions just outside the corridor: [x, y, height_m, kind]."""
        rng = random.Random(f"trees:{self.number}:{self.trees_seed}")
        out: list[list[float]] = []
        pts = list(self.route)
        # sample along the route on both sides, plus behind the green and the tee
        for (ax, ay), (bx, by) in zip(pts, pts[1:], strict=False):
            seg = math.hypot(bx - ax, by - ay)
            ux, uy = (bx - ax) / seg, (by - ay) / seg
            nx, ny = -uy, ux
            k = 0.0
            while k < seg:
                for side in (-1.0, 1.0):
                    for _row in range(2):
                        off = CORRIDOR_HALF_WIDTH_M + rng.uniform(4.0, 30.0)
                        along = k + rng.uniform(-4.0, 4.0)
                        x = ax + ux * along + nx * off * side
                        y = ay + uy * along + ny * off * side
                        if self.in_corridor(x, y) or any(w.contains(x, y) for w in self.water):
                            continue
                        out.append(
                            [round(x, 2), round(y, 2), round(rng.uniform(9.0, 19.0), 2), float(rng.random() < 0.55)]
                        )
                k += rng.uniform(6.0, 10.0)
        gx, gy = self.green.center
        for k in range(40):
            a = 2 * math.pi * k / 40
            r = self.green.radius_m + GREEN_APRON_M + rng.uniform(4.0, 26.0)
            x, y = gx + r * math.cos(a), gy + r * math.sin(a)
            if not self.in_corridor(x, y) and not any(w.contains(x, y) for w in self.water):
                out.append([round(x, 2), round(y, 2), round(rng.uniform(10.0, 20.0), 2), float(rng.random() < 0.5)])
        for k in range(18):
            a = math.pi + math.pi * (k / 17.0)  # behind the tee (south)
            r = rng.uniform(22.0, 48.0)
            x, y = self.tee[0] + r * math.cos(a), self.tee[1] + r * math.sin(a) * 0.8
            out.append([round(x, 2), round(y, 2), round(rng.uniform(9.0, 18.0), 2), float(rng.random() < 0.5)])
        return out

    def to_dict(self, geometry: bool = True) -> dict:
        d = {
            "number": self.number,
            "name": self.name,
            "par": self.par,
            "description": self.description,
            "length_m": round(self.length_m, 2),
            "tee": list(self.tee),
            "cup": list(self.cup),
            "has_water": bool(self.water),
        }
        if geometry:
            d |= {
                "route": [list(p) for p in self.route],
                "green": {
                    "stimp_ft": self.green.stimp_ft,
                    "slope_x": self.green.slope_x,
                    "slope_y": self.green.slope_y,
                    "radius_m": self.green.radius_m,
                    "center": list(self.green.center),
                },
                "fairways": [f.to_list() for f in self.fairways],
                "bunkers": [b.to_list() for b in self.bunkers],
                "water": [w.to_list() for w in self.water],
                "corridor_half_width_m": CORRIDOR_HALF_WIDTH_M,
                "green_apron_m": GREEN_APRON_M,
                "fringe_m": FRINGE_M,
                "tee_radius_m": TEE_RADIUS_M,
                "collar_m": COLLAR_M,
                "trees": self.trees,
            }
        return d


def _green(center: Point, radius: float, stimp: float, sx: float, sy: float) -> Green:
    return Green(stimp_ft=stimp, slope_x=sx, slope_y=sy, radius_m=radius, center=center)


FRONT_NINE: tuple[HoleSpec, ...] = (
    HoleSpec(
        1,
        "First Flight",
        4,
        "A gentle opener. Fairway bunkers pinch the landing area; the green is guarded left and right.",
        route=((0.0, 0.0), (0.0, 232.0), (5.0, 333.0)),
        green=_green((2.0, 330.0), 13.0, 10.0, 0.008, -0.012),
        fairways=(ribbon([(0.0, 40.0), (0.0, 170.0), (1.0, 250.0), (2.0, 305.0)], 17.0, seed=1),),
        bunkers=(
            blob(-21.0, 214.0, 7.0, 13.0, 8.0, seed=11),
            blob(22.0, 250.0, 6.0, 12.0, -10.0, seed=12),
            blob(-16.0, 324.0, 5.0, 8.0, 20.0, seed=13),
            blob(17.0, 338.0, 5.5, 7.5, -25.0, seed=14),
        ),
        trees_seed=1,
    ),
    HoleSpec(
        2,
        "The Dogleg",
        4,
        "Doglegs hard left around a corner bunker. Cut too much off and the trees wait.",
        route=((0.0, 0.0), (0.0, 238.0), (-82.0, 350.0)),
        green=_green((-80.0, 348.0), 12.0, 10.5, -0.010, 0.006),
        fairways=(ribbon([(0.0, 50.0), (0.0, 200.0), (-8.0, 250.0), (-38.0, 292.0), (-66.0, 330.0)], 16.0, seed=2),),
        bunkers=(
            blob(-24.0, 238.0, 8.0, 12.0, 30.0, seed=21),
            blob(23.0, 262.0, 6.0, 11.0, -15.0, seed=22),
            blob(-65.0, 360.0, 6.0, 5.0, 10.0, seed=23),
            blob(-95.0, 338.0, 5.0, 7.0, 0.0, seed=24),
        ),
        trees_seed=2,
    ),
    HoleSpec(
        3,
        "Pond Hop",
        3,
        "All carry over the pond to a green that tilts back toward the water.",
        route=((0.0, 0.0), (6.0, 150.0)),
        green=_green((5.0, 152.0), 14.0, 10.0, 0.0, 0.010),
        fairways=(ribbon([(3.0, 124.0), (4.0, 134.0)], 14.0, seed=3),),
        bunkers=(blob(19.0, 167.0, 6.0, 5.0, 15.0, seed=31), blob(-12.0, 169.0, 6.5, 4.5, -10.0, seed=32)),
        water=(blob(2.0, 84.0, 33.0, 34.0, 12.0, seed=33, wobble=0.14),),
        trees_seed=3,
    ),
    HoleSpec(
        4,
        "Long Haul",
        5,
        "The long par five. A creek crosses the fairway just past driving distance: lay up or carry it.",
        route=((0.0, 0.0), (8.0, 240.0), (-5.0, 392.0), (-3.0, 477.0)),
        green=_green((0.0, 474.0), 13.0, 11.0, 0.012, 0.006),
        fairways=(
            ribbon([(0.0, 40.0), (6.0, 150.0), (8.0, 278.0)], 18.0, seed=41),
            ribbon([(4.0, 320.0), (-5.0, 392.0), (0.0, 452.0)], 16.0, seed=42),
        ),
        bunkers=(
            blob(-23.0, 250.0, 7.0, 12.0, 5.0, seed=43),
            blob(28.0, 410.0, 7.0, 10.0, -12.0, seed=44),
            blob(16.0, 473.0, 5.0, 7.0, 0.0, seed=45),
            blob(-15.0, 482.0, 5.0, 6.0, 30.0, seed=46),
        ),
        water=(
            ribbon(
                [(-80.0, 294.0), (-35.0, 305.0), (0.0, 298.0), (32.0, 308.0), (80.0, 300.0)], 6.5, seed=47, wobble=0.2
            ),
        ),
        trees_seed=4,
    ),
    HoleSpec(
        5,
        "Lakeside",
        4,
        "A lake runs the whole left side and the green leans toward it. Bail out right.",
        route=((0.0, 0.0), (6.0, 230.0), (-2.0, 347.0)),
        green=_green((0.0, 345.0), 12.0, 10.5, 0.010, 0.0),
        fairways=(ribbon([(3.0, 40.0), (6.0, 200.0), (4.0, 322.0)], 17.0, seed=5),),
        bunkers=(blob(28.0, 232.0, 7.0, 11.0, 0.0, seed=51), blob(15.0, 355.0, 5.0, 6.0, -20.0, seed=52)),
        water=(blob(-64.0, 196.0, 32.0, 138.0, 4.0, seed=53, wobble=0.12),),
        trees_seed=5,
    ),
    HoleSpec(
        6,
        "Little Sting",
        3,
        "Short, but the green is ringed by four bunkers. Precision over power.",
        route=((0.0, 0.0), (-3.0, 125.0)),
        green=_green((0.0, 127.0), 11.0, 11.5, 0.015, -0.008),
        fairways=(ribbon([(0.0, 62.0), (0.0, 108.0)], 13.0, seed=6),),
        bunkers=(
            blob(-15.0, 118.0, 4.5, 6.0, 10.0, seed=61),
            blob(15.0, 122.0, 4.5, 6.5, -10.0, seed=62),
            blob(-9.0, 142.0, 6.0, 4.0, 5.0, seed=63),
            blob(12.0, 139.0, 5.5, 4.0, -15.0, seed=64),
        ),
        trees_seed=6,
    ),
    HoleSpec(
        7,
        "Wingspan",
        4,
        "A long dogleg right. The inside corner bunker rewards a brave line.",
        route=((0.0, 0.0), (0.0, 245.0), (80.0, 362.0)),
        green=_green((82.0, 361.0), 12.5, 10.0, -0.008, -0.010),
        fairways=(ribbon([(0.0, 50.0), (0.0, 210.0), (15.0, 265.0), (50.0, 318.0), (72.0, 346.0)], 16.0, seed=7),),
        bunkers=(
            blob(-21.0, 255.0, 7.0, 11.0, 0.0, seed=71),
            blob(27.0, 228.0, 7.0, 10.0, 25.0, seed=72),
            blob(96.0, 352.0, 5.0, 7.0, 0.0, seed=73),
            blob(68.0, 375.0, 6.0, 5.0, 0.0, seed=74),
        ),
        trees_seed=7,
    ),
    HoleSpec(
        8,
        "Marsh Run",
        5,
        "A three-shotter past a marsh pond, finishing at a green with water short and right.",
        route=((0.0, 0.0), (-6.0, 250.0), (4.0, 420.0), (-2.0, 505.0)),
        green=_green((-4.0, 508.0), 13.0, 10.5, 0.010, 0.010),
        fairways=(ribbon([(0.0, 40.0), (-6.0, 160.0), (-5.0, 300.0), (2.0, 420.0), (-2.0, 482.0)], 17.0, seed=8),),
        bunkers=(
            blob(19.0, 265.0, 7.0, 11.0, 0.0, seed=81),
            blob(-25.0, 420.0, 6.5, 10.0, 10.0, seed=82),
            blob(-21.0, 515.0, 5.0, 6.0, 0.0, seed=83),
        ),
        water=(
            blob(24.0, 468.0, 24.0, 20.0, -20.0, seed=84, wobble=0.15),
            blob(-38.0, 335.0, 16.0, 30.0, 8.0, seed=85, wobble=0.15),
        ),
        trees_seed=8,
    ),
    HoleSpec(
        9,
        "Home Stretch",
        4,
        "A cross bunker splits the fairway on the way home to a big, fast green.",
        route=((0.0, 0.0), (-4.0, 240.0), (3.0, 362.0)),
        green=_green((2.0, 364.0), 14.0, 11.0, -0.006, 0.014),
        fairways=(ribbon([(0.0, 40.0), (-4.0, 200.0), (0.0, 300.0), (2.0, 338.0)], 18.0, seed=9),),
        bunkers=(
            blob(0.0, 290.0, 21.0, 5.0, 3.0, seed=91, wobble=0.18),
            blob(19.0, 358.0, 5.0, 7.0, 0.0, seed=92),
            blob(-17.0, 367.0, 5.5, 6.0, 0.0, seed=93),
        ),
        trees_seed=9,
    ),
)

HOLE_BY_NUMBER: dict[int, HoleSpec] = {h.number: h for h in FRONT_NINE}
COURSE_PAR = sum(h.par for h in FRONT_NINE)


def course_summary() -> dict:
    return {
        "name": COURSE_NAME,
        "version": COURSE_VERSION,
        "par": COURSE_PAR,
        "holes": [h.to_dict(geometry=False) for h in FRONT_NINE],
    }
