"""Practice situations: where the fly stands for each practice shot.

Four kinds, all generated deterministically from a seed:

* ``putt``  — a practice-green scenario (1–6 m putts, the V1 putting experiment's generator);
* ``green`` — a putt on one of the front-nine greens (1–14 m);
* ``full``  — a tee shot or a shot from somewhere along a hole (fairway, rough, sand);
* ``short`` — a chip or pitch from 3–70 m around a green (v2: the shots that need wedges).

Each situation is split into train or test by its index, so held-out evaluation never sees
a situation the readout was fitted on.
"""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass

from ..golf.course import FRONT_NINE, HOLE_BY_NUMBER, HoleSpec
from ..golf.course_env import ADDRESS_JITTER_FULL_DEG, CourseEnvironment
from ..golf.env import PuttingEnvironment
from ..golf.flight import Surface
from ..golf.scenario import ADDRESS_JITTER_DEG, generate_scenario

SITUATIONS_VERSION = "practice-situations-v2"  # v2 = v1 + short-game situations
SHORT_MIN_M = 3.0
SHORT_MAX_M = 70.0
PRACTICE_SEED_BASE = 500_000  # practice-green scenario seeds used for training (play uses random seeds)
TEST_EVERY = 10
TEST_SLOTS = (1, 4, 7)  # indices i with i % 10 in these slots are held out (30 %)


@dataclass(frozen=True)
class Situation:
    sid: str
    index: int
    kind: str  # putt | green | short | full
    seed: int
    hole: int | None = None
    ball: tuple[float, float] | None = None
    jitter_deg: float = 0.0

    @property
    def is_test(self) -> bool:
        return self.index % TEST_EVERY in TEST_SLOTS

    def build(self) -> PuttingEnvironment | CourseEnvironment:
        if self.kind == "putt":
            return PuttingEnvironment(generate_scenario(self.seed))
        env = CourseEnvironment(HOLE_BY_NUMBER[self.hole], self.seed)
        env.place(self.ball, self.jitter_deg)
        return env

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ball"] = list(self.ball) if self.ball else None
        return d

    @staticmethod
    def from_dict(d: dict) -> Situation:
        return Situation(
            sid=d["sid"],
            index=int(d["index"]),
            kind=d["kind"],
            seed=int(d["seed"]),
            hole=d.get("hole"),
            ball=tuple(d["ball"]) if d.get("ball") else None,
            jitter_deg=float(d.get("jitter_deg", 0.0)),
        )


def _route_point(hole: HoleSpec, s: float) -> tuple[float, float, float, float]:
    """(x, y, ux, uy): the point at arc length s along the routing line and its direction."""
    for (ax, ay), (bx, by) in zip(hole.route, hole.route[1:], strict=False):
        seg = math.hypot(bx - ax, by - ay)
        if s <= seg:
            ux, uy = (bx - ax) / seg, (by - ay) / seg
            return ax + ux * s, ay + uy * s, ux, uy
        s -= seg
    (ax, ay), (bx, by) = hole.route[-2], hole.route[-1]
    seg = math.hypot(bx - ax, by - ay)
    return bx, by, (bx - ax) / seg, (by - ay) / seg


def generate_situations(
    n_putt: int = 120, n_green: int = 120, n_full: int = 200, seed: int = 0, n_short: int = 0
) -> list[Situation]:
    """Putts, course-green putts and full shots in the v1 layout, then (v2) `n_short` chips and
    pitches from 3-70 m, drawn from a separate stream so the v1 part is unchanged."""
    rng = random.Random(f"practice-situations-v1:{seed}")
    out: list[Situation] = []

    def add(kind: str, seed_: int, hole: int | None = None, ball=None, jitter: float = 0.0) -> None:
        i = len(out)
        out.append(Situation(f"{kind}-{i:04d}", i, kind, seed_, hole, ball, round(jitter, 6)))

    for i in range(n_putt):
        add("putt", PRACTICE_SEED_BASE + seed * 10_000 + i)
    for i in range(n_green):
        hole = FRONT_NINE[i % len(FRONT_NINE)]
        cx, cy = hole.cup
        while True:
            d = rng.uniform(1.0, 14.0)
            a = rng.uniform(0.0, 2.0 * math.pi)
            ball = (round(cx + d * math.cos(a), 4), round(cy + d * math.sin(a), 4))
            if hole.surface(*ball) is Surface.GREEN:
                break
        add("green", i, hole.number, ball, rng.uniform(-ADDRESS_JITTER_DEG, ADDRESS_JITTER_DEG))
    for i in range(n_full):
        hole = FRONT_NINE[i % len(FRONT_NINE)]
        if i % 5 == 2:  # offset so tee shots fall in both the train and the held-out slots
            ball = hole.tee
        else:
            while True:
                s = rng.uniform(40.0, max(60.0, hole.length_m - 18.0))
                x, y, ux, uy = _route_point(hole, s)
                off = rng.uniform(-28.0, 28.0)
                ball = (round(x - uy * off, 4), round(y + ux * off, 4))
                if hole.surface(*ball) not in (Surface.WATER, Surface.OOB, Surface.GREEN, Surface.FRINGE):
                    break
        add("full", 1_000 + i, hole.number, ball, rng.uniform(-ADDRESS_JITTER_FULL_DEG, ADDRESS_JITTER_FULL_DEG))
    short_rng = random.Random(f"{SITUATIONS_VERSION}:short:{seed}")
    for i in range(n_short):
        # Around the green: anywhere in play 3-70 m from the pin that is not the green itself
        # (the fringe is included; from there the fly practises with the putter).
        hole = FRONT_NINE[i % len(FRONT_NINE)]
        cx, cy = hole.cup
        while True:
            d = short_rng.uniform(SHORT_MIN_M, SHORT_MAX_M)
            a = short_rng.uniform(0.0, 2.0 * math.pi)
            ball = (round(cx + d * math.cos(a), 4), round(cy + d * math.sin(a), 4))
            if hole.surface(*ball) not in (Surface.WATER, Surface.OOB, Surface.GREEN):
                break
        jitter = short_rng.uniform(-ADDRESS_JITTER_FULL_DEG, ADDRESS_JITTER_FULL_DEG)
        add("short", 2_000 + i, hole.number, ball, jitter)
    return out
