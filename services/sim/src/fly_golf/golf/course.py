"""Fly Golf National: eighteen hand-authored holes (par 72).

The front nine (holes 1-9, parkland) is unchanged since `front-nine-v2`. The back nine, "The
Neuropil Nine" (holes 10-18, dusk), names each hole after a structure of the fly's nervous
system or body and shapes it to echo that structure; see docs/COURSE.md. Training practises on
the front nine only, so the back nine is a held-out course.

Geometry lives in each hole's own frame: metres, the tee at the origin, the hole playing
roughly north (+y). Surfaces are polygons (fairways, bunkers, water) plus a circular, tilted
green. Everything outside the hole's corridor (a band around the routing line, 42 m either side
unless the hole sets its own half-width) is trees, i.e. out of bounds. Tree positions are
generated deterministically for the renderer only; they do not collide with the ball.

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

COURSE_VERSION = "eighteen-v1"  # 18 holes; holes 1-9 are identical to front-nine-v2
COURSE_NAME = "Fly Golf National"

CORRIDOR_HALF_WIDTH_M = 42.0  # default corridor half-width (every front-nine hole); beyond it: trees
GREEN_APRON_M = 26.0  # the corridor also includes a disc this much wider than the green
TEE_RADIUS_M = 5.0
FRINGE_M = 1.5
COLLAR_M = 4.0  # beyond the fringe, the green's rim height blends down to the flat hole over this width
TARGET_REACH_M = 225.0  # the fly looks at the pin once it is this close
TARGET_MIN_AHEAD_M = 60.0  # a routing point closer than this is skipped (never lay up a wedge short of it)
WATER_LINE_STEP_M = 2.0
NINE_THEMES = {"front": "parkland", "back": "dusk"}

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
    corridor_half_width_m: float = CORRIDOR_HALF_WIDTH_M  # beyond this from the routing line: trees

    @property
    def nine(self) -> str:
        """Which nine the hole belongs to: "front" (1-9) or "back" (10-18)."""
        return "front" if self.number <= 9 else "back"

    @property
    def theme(self) -> str:
        """The renderer's look for the hole: parkland on the front nine, dusk on the back."""
        return NINE_THEMES[self.nine]

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
        return _dist_to_polyline(x, y, self.route)[0] <= self.corridor_half_width_m

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
                        off = self.corridor_half_width_m + rng.uniform(4.0, 30.0)
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
            "nine": self.nine,
            "theme": self.theme,
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
                "corridor_half_width_m": self.corridor_half_width_m,
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


def _arc(center: Point, radius: float, a0_deg: float, a1_deg: float, n: int = 16) -> list[Point]:
    """Points along a circular arc, counter-clockwise from a0 to a1 (degrees; 0 = +x, 90 = +y)."""
    cx, cy = center
    out = []
    for k in range(n):
        a = math.radians(a0_deg + (a1_deg - a0_deg) * k / (n - 1))
        out.append((cx + radius * math.cos(a), cy + radius * math.sin(a)))
    return out


def _hex_pots(cx: float, cy: float, spacing: float, radius: float, seed: int, rot_deg: float = 0.0) -> tuple:
    """Seven round pot bunkers packed like ommatidia: one in the middle, six around it."""
    angles = [math.radians(rot_deg + 60.0 * k) for k in range(6)]
    centres = [(cx, cy)] + [(cx + spacing * math.cos(a), cy + spacing * math.sin(a)) for a in angles]
    return tuple(blob(x, y, radius, radius, 0.0, seed=seed + k, wobble=0.06, n=32) for k, (x, y) in enumerate(centres))


def _pews(cx: float, y0: float, n: int, spacing: float, length: float, seed: int, rot_deg: float = 0.0) -> tuple:
    """A row of long, narrow bunkers with strips of grass between them (church pews)."""
    return tuple(
        blob(cx, y0 + spacing * k, length / 2.0, 1.4, rot_deg, seed=seed + k, wobble=0.05, n=40) for k in range(n)
    )


def _fan(
    pivot: Point, r0: float, r1: float, a0_deg: float, a1_deg: float, wobble: float = 0.0, seed: int = 0
) -> Polygon:
    """A sector of an annulus around `pivot` (radii r0..r1, angles a0..a1 degrees): a fan, or one
    curved band of it. `wobble` roughens the edges a little (deterministic)."""
    rng = random.Random(f"fan:{seed}:{pivot}:{r0}:{a0_deg}")
    p1, p2 = rng.uniform(0, 2 * math.pi), rng.uniform(0, 2 * math.pi)
    n = max(6, int((a1_deg - a0_deg) * 2))

    def edge(a: float, r: float, ph: float) -> tuple[float, float]:
        w = 0.6 * math.sin(math.radians(a) * 30.0 + ph) + 0.4 * math.sin(math.radians(a) * 70.0 + 2.0 * ph)
        return a, r + wobble * (r1 - r0) * w

    outer = [edge(a, r1, p1) for a in _lin(a0_deg, a1_deg, n)]
    inner = [edge(a, r0, p2) for a in _lin(a1_deg, a0_deg, n)]
    px, py = pivot
    return Polygon(
        tuple((px + r * math.cos(math.radians(a)), py + r * math.sin(math.radians(a))) for a, r in outer + inner)
    )


def _lin(a: float, b: float, n: int) -> list[float]:
    return [a + (b - a) * k / (n - 1) for k in range(n)]


FAN_16: Point = (0.0, -40.0)  # the pivot of hole 16's fan-shaped fairway and its bands of waste sand

# The back nine, "The Neuropil Nine": each hole is named after a structure of the fly's nervous
# system or body, and its shape echoes that structure (docs/COURSE.md). It uses only the
# surfaces the front nine uses, plus a per-hole corridor half-width. Seeds follow the front
# nine's numbering (hole 12 uses 121, 122, ...); a cluster of bunkers uses hole * 100 + k.
BACK_NINE: tuple[HoleSpec, ...] = (
    HoleSpec(
        10,
        "Ommatidia",
        4,
        "The compound eye opens the back nine: seven pot bunkers packed in a hexagon, like the facets "
        "of a fly's eye, wait just past the drive. Stay left of the cluster.",
        route=((0.0, 0.0), (-10.0, 232.0), (5.0, 372.0)),
        green=_green((3.0, 375.0), 12.5, 11.0, -0.010, 0.008),
        fairways=(ribbon([(0.0, 40.0), (-6.0, 150.0), (-6.0, 235.0), (0.0, 290.0), (3.0, 350.0)], 20.0, seed=101),),
        bunkers=(
            *_hex_pots(6.0, 262.0, 8.2, 3.3, seed=1001, rot_deg=90.0),
            blob(-19.0, 380.0, 5.0, 7.0, 10.0, seed=102),
            blob(22.0, 388.0, 5.0, 5.5, -20.0, seed=103),
        ),
        trees_seed=10,
    ),
    HoleSpec(
        11,
        "Johnston's Organ",
        3,
        "The fly's ear: a long par three to a big, tilted green. One long curved bunker sweeps across "
        "the front-left like the arista that catches sound; run it in from the right.",
        route=((0.0, 0.0), (-27.0, 199.0)),
        green=_green((-20.0, 193.0), 16.0, 10.5, 0.016, -0.012),
        fairways=(ribbon([(6.0, 120.0), (2.0, 150.0), (-6.0, 172.0)], 12.0, seed=111),),
        bunkers=(
            ribbon(_arc((-20.0, 193.0), 23.0, 172.0, 252.0, 10), 3.8, seed=112, wobble=0.12),
            blob(2.0, 214.0, 5.0, 4.0, 30.0, seed=113),
        ),
        trees_seed=11,
    ),
    HoleSpec(
        12,
        "Halteres",
        5,
        "Named for the fly's balance organs, which beat opposite the wings: a double dogleg that swings "
        "right, then left, with a burn crossing the line of play twice.",
        route=((0.0, 0.0), (6.0, 232.0), (68.0, 392.0), (42.0, 498.0)),
        green=_green((40.0, 501.0), 13.5, 11.0, -0.008, 0.012),
        fairways=(
            ribbon([(0.0, 40.0), (3.0, 150.0), (6.0, 232.0), (14.0, 268.0)], 18.0, seed=121),
            ribbon([(28.0, 318.0), (52.0, 360.0), (68.0, 392.0), (62.0, 425.0)], 17.0, seed=122),
            ribbon([(50.0, 466.0), (44.0, 482.0)], 13.0, seed=123),
        ),
        bunkers=(
            blob(28.0, 240.0, 7.0, 11.0, -10.0, seed=124),
            blob(46.0, 404.0, 6.0, 9.0, 20.0, seed=125),
            blob(58.0, 510.0, 5.0, 7.0, 0.0, seed=126),
            blob(22.0, 508.0, 5.0, 6.0, 20.0, seed=127),
        ),
        water=(
            ribbon(
                [
                    (-70.0, 268.0),
                    (-20.0, 280.0),
                    (20.0, 292.0),
                    (55.0, 300.0),
                    (95.0, 318.0),
                    (118.0, 350.0),
                    (122.0, 395.0),
                    (118.0, 425.0),
                    (95.0, 448.0),
                    (55.0, 455.0),
                    (15.0, 448.0),
                    (-30.0, 452.0),
                ],
                5.5,
                seed=128,
                wobble=0.2,
            ),
        ),
        trees_seed=12,
    ),
    HoleSpec(
        13,
        "Protocerebral Bridge",
        4,
        "A short par four, drivable on paper: a flush driver over a row of church-pew bunkers reaches a "
        "small, fast green with water to its right. The pews echo the protocerebral bridge, a row of "
        "glomeruli spanning the brain's midline. From the tee the fly is shown the lay-up area on the "
        "left, not the pin.",
        route=((0.0, 0.0), (-18.0, 175.0), (14.0, 242.0)),
        green=_green((16.0, 245.0), 10.0, 12.5, -0.012, 0.006),
        fairways=(
            ribbon([(-2.0, 60.0), (-12.0, 130.0), (-18.0, 175.0), (-10.0, 205.0)], 16.0, seed=131),
            ribbon([(6.0, 226.0), (10.0, 232.0)], 8.0, seed=132),
        ),
        bunkers=(
            *_pews(12.0, 180.0, 9, 5.2, 19.0, seed=1301),
            blob(-2.0, 236.0, 4.5, 5.5, 0.0, seed=134),
        ),
        water=(blob(44.0, 240.0, 11.0, 22.0, 10.0, seed=133, wobble=0.12),),
        trees_seed=13,
    ),
    HoleSpec(
        14,
        "Mushroom Body",
        4,
        "The tee sits in a cup of sand like the calyx; a narrow stalk of fairway, the peduncle, runs out "
        "and splits into lobes, one reaching straight up to the green and one turning off to the right.",
        route=((0.0, 0.0), (0.0, 238.0), (-8.0, 388.0)),
        green=_green((-6.0, 391.0), 12.0, 11.5, 0.010, -0.012),
        fairways=(
            ribbon([(0.0, 30.0), (0.0, 120.0), (0.0, 210.0)], 10.0, seed=141, wobble=0.05),
            ribbon([(0.0, 205.0), (-2.0, 260.0), (-6.0, 300.0), (-6.0, 368.0)], 15.0, seed=142),
            ribbon([(6.0, 226.0), (30.0, 252.0)], 11.0, seed=143),
        ),
        bunkers=(
            ribbon(_arc((0.0, 0.0), 16.0, 160.0, 380.0, 14), 3.5, seed=144, wobble=0.1),
            blob(22.0, 286.0, 8.0, 14.0, -30.0, seed=145),
            blob(-24.0, 398.0, 5.0, 8.0, 15.0, seed=146),
            blob(10.0, 404.0, 6.0, 5.0, -20.0, seed=147),
            blob(8.0, 372.0, 4.0, 4.5, 0.0, seed=148),
        ),
        trees_seed=14,
        corridor_half_width_m=46.0,
    ),
    HoleSpec(
        15,
        "Ellipsoid Body",
        3,
        "An island green inside a ring of water, the doughnut of neuropil where the fly keeps its "
        "compass. A thin causeway at the back right is the only way on foot.",
        route=((0.0, 0.0), (2.0, 127.0)),
        green=_green((0.0, 128.0), 12.0, 11.0, 0.006, 0.010),
        fairways=(
            ribbon([(0.0, 62.0), (0.0, 84.0)], 12.0, seed=151),
            blob(0.0, 128.0, 19.0, 19.0, 0.0, seed=152, wobble=0.02),
        ),
        bunkers=(blob(9.5, 115.0, 2.5, 2.5, 0.0, seed=153, wobble=0.05),),
        water=(ribbon(_arc((0.0, 128.0), 27.0, 67.0, 383.0, 24), 7.0, seed=154, wobble=0.04),),
        trees_seed=15,
    ),
    HoleSpec(
        16,
        "Fan-shaped Body",
        4,
        "The widest hole on the course fans out like the fan-shaped body, crossed by bands of waste "
        "sand laid in arcs and broken into columns, as the neuropil is layered and segmented.",
        route=((0.0, 0.0), (3.0, 236.0), (-4.0, 382.0)),
        green=_green((-2.0, 385.0), 17.0, 9.5, 0.006, 0.004),
        fairways=(_fan(FAN_16, 30.0, 380.0, 81.5, 98.5),),
        bunkers=(
            *(
                _fan(FAN_16, 186.0, 197.0, a0, a1, wobble=0.25, seed=1601 + k)
                for k, (a0, a1) in enumerate(((76.0, 81.0), (82.5, 88.0), (89.5, 94.5), (96.0, 100.5), (102.0, 106.0)))
            ),
            *(
                _fan(FAN_16, 316.0, 325.0, a0, a1, wobble=0.25, seed=1611 + k)
                for k, (a0, a1) in enumerate(((81.0, 85.0), (86.5, 89.0), (91.5, 94.5), (96.0, 99.5)))
            ),
            blob(-44.0, 92.0, 11.0, 44.0, 6.0, seed=163, wobble=0.15),
            blob(46.0, 222.0, 10.0, 46.0, -5.0, seed=164, wobble=0.15),
            blob(-28.0, 392.0, 6.0, 8.0, 0.0, seed=165),
            blob(24.0, 378.0, 5.0, 6.0, 0.0, seed=166),
        ),
        trees_seed=16,
        corridor_half_width_m=58.0,
    ),
    HoleSpec(
        17,
        "Giant Fiber",
        5,
        "The giant fibers are the fly's fastest escape pathway: a pair of huge axons running from the "
        "brain straight down to the jump muscles' motor neurons. The longest, straightest hole on the "
        "course, a narrow chute through the trees.",
        route=((0.0, 0.0), (0.0, 240.0), (0.0, 450.0), (2.0, 548.0)),
        green=_green((0.0, 551.0), 11.0, 12.0, -0.006, 0.012),
        fairways=(ribbon([(0.0, 35.0), (0.0, 300.0), (0.0, 527.0)], 13.0, seed=171, wobble=0.05),),
        bunkers=(
            blob(-17.0, 300.0, 5.0, 14.0, 0.0, seed=172),
            blob(17.0, 385.0, 5.0, 14.0, 0.0, seed=173),
            blob(-19.0, 554.0, 4.5, 6.0, 0.0, seed=174),
            blob(18.0, 544.0, 4.5, 5.5, 0.0, seed=175),
        ),
        trees_seed=17,
        corridor_half_width_m=30.0,
    ),
    HoleSpec(
        18,
        "Descending Neurons",
        4,
        "Home, the way the brain's commands leave it: down the descending neurons to the body. A cape "
        "hole around the clubhouse lake; the more of the water you carry, the shorter the way in.",
        route=((0.0, 0.0), (-28.0, 226.0), (-160.0, 335.0)),
        green=_green((-163.0, 338.0), 14.0, 11.5, 0.008, 0.010),
        fairways=(
            ribbon(
                [(0.0, 40.0), (-12.0, 150.0), (-28.0, 226.0), (-70.0, 268.0), (-120.0, 305.0), (-142.0, 322.0)],
                18.0,
                seed=181,
            ),
        ),
        bunkers=(blob(-2.0, 235.0, 7.0, 12.0, 0.0, seed=183), blob(-150.0, 356.0, 6.0, 5.0, 0.0, seed=184)),
        water=(
            blob(-92.0, 178.0, 48.0, 62.0, -40.0, seed=182, wobble=0.14),
            blob(-160.0, 305.0, 22.0, 13.0, 20.0, seed=185, wobble=0.14),
        ),
        trees_seed=18,
    ),
)

COURSE: tuple[HoleSpec, ...] = FRONT_NINE + BACK_NINE
HOLE_BY_NUMBER: dict[int, HoleSpec] = {h.number: h for h in COURSE}
FRONT_PAR = sum(h.par for h in FRONT_NINE)
BACK_PAR = sum(h.par for h in BACK_NINE)
COURSE_PAR = FRONT_PAR + BACK_PAR
NINES: tuple[dict, ...] = (
    {"id": "front", "name": "Front Nine", "holes": [h.number for h in FRONT_NINE], "par": FRONT_PAR},
    {"id": "back", "name": "The Neuropil Nine", "holes": [h.number for h in BACK_NINE], "par": BACK_PAR},
)
# Holes whose geometry is unchanged since an earlier course version: a record of one of these
# holes made under that version still replays against this code bit for bit.
COMPATIBLE_COURSE_VERSIONS: dict[str, frozenset[int]] = {"front-nine-v2": frozenset(range(1, 10))}


def course_summary() -> dict:
    return {
        "name": COURSE_NAME,
        "version": COURSE_VERSION,
        "par": COURSE_PAR,
        "nines": [dict(n) for n in NINES],
        "holes": [h.to_dict(geometry=False) for h in COURSE],
    }
