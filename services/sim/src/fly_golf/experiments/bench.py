"""`fly-golf bench`: closed-loop rounds on the front nine.

The training report scores ONE stroke per held-out situation. What a viewer sees is different:
the fly plays a whole hole, every shot from wherever the last one finished, until it holes out
or picks up at par + 5. This benchmark plays complete front-nine rounds with a controller,
exactly as the app does (same RoundSession, sensing, brain, decoder and physics), and reports
what matters for that: holes finished, strokes, penalty strokes and which club the fly reached
for at each distance.

Rounds are independent and seeded (seed0, seed0 + 1, ...), so a bench is reproducible and two
controllers can be compared on the same rounds. Rounds run in parallel worker processes that
share the compiled graph read-only (fork).
"""

from __future__ import annotations

import multiprocessing as mp
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from ..brain.interfaces import BrainController
from ..brain.mock import MockBrainController
from ..golf.course import COURSE_PAR
from ..provenance import git_info, versions
from .runner import RoundSession

BENCH_VERSION = "front-nine-bench-v1"
DISTANCE_BANDS = ((0.0, 20.0), (20.0, 60.0), (60.0, 120.0), (120.0, 170.0), (170.0, 1e9))

_GRAPH = None  # set in the parent before forking workers
_SPEC: tuple[str, str | None] | None = None
_CTRL: BrainController | None = None


def build_controller(controller_id: str, graph=None, readout_path: str | None = None) -> BrainController:
    if controller_id == "mock":
        return MockBrainController()
    if controller_id == "malecns":
        from ..brain.malecns.controller import MaleCNSController

        return MaleCNSController(graph)
    if controller_id == "malecns-trained":
        from ..brain.trained import TrainedReadoutController, load_readout

        return TrainedReadoutController(graph, load_readout(Path(readout_path)), str(readout_path))
    raise KeyError(f"unknown controller {controller_id!r}")


def _init_worker() -> None:
    global _CTRL
    cid, readout = _SPEC
    _CTRL = build_controller(cid, _GRAPH, readout)


def play_round(seed: int, controller: BrainController | None = None) -> dict:
    """One complete front-nine round (no recording). Returns the card and every shot."""
    controller = controller or _CTRL
    s = RoundSession(controller)
    s.new_round(seed)
    shots = []
    while True:
        hole = s.env.hole
        while not s.env.done:
            rec = s.play_shot()
            o = rec["outcome"]
            shots.append(
                {
                    "hole": hole.number,
                    "start_m": round(o["start_distance_m"], 2),
                    "lie": o["lie_before"],
                    "club": rec["stroke"]["club"]["id"],
                    "power": round(rec["stroke"]["power"], 4),
                    "outcome": o["outcome"],
                    "penalty": o["penalty_strokes"],
                    "final_m": round(o["final_distance_m"], 2),
                }
            )
        if s.round_complete:
            break
        s.next_hole()
    card = [s.scorecard[n] for n in sorted(s.scorecard)]
    return {
        "seed": seed,
        "strokes": sum(c["strokes"] for c in card),
        "card": card,
        "shots": shots,
        "controller": controller.info.to_dict(),
    }


def summarize_rounds(rounds: list[dict]) -> dict:
    if not rounds:
        return {"rounds": 0}
    strokes = np.array([r["strokes"] for r in rounds], dtype=float)
    holes = [c for r in rounds for c in r["card"]]
    shots = [s for r in rounds for s in r["shots"]]
    bands = {}
    for lo, hi in DISTANCE_BANDS:
        band = [s for s in shots if lo <= s["start_m"] < hi]
        if not band:
            continue
        clubs = Counter(s["club"] for s in band)
        name = f"{lo:.0f}-{hi:.0f} m" if hi < 1e8 else f"{lo:.0f}+ m"
        bands[name] = {
            "shots": len(band),
            "top_clubs": [[c, round(100.0 * n / len(band), 1)] for c, n in clubs.most_common(4)],
            "trees_pct": round(100.0 * sum(s["outcome"] == "out_of_bounds" for s in band) / len(band), 1),
            "water_pct": round(100.0 * sum(s["outcome"] == "water" for s in band) / len(band), 1),
        }
    return {
        "rounds": len(rounds),
        "mean_strokes": round(float(strokes.mean()), 2),
        "median_strokes": float(np.median(strokes)),
        "best_round": int(strokes.min()),
        "par": COURSE_PAR,
        "holes": len(holes),
        "holes_holed_pct": round(100.0 * sum(bool(c["holed"]) for c in holes) / len(holes), 1),
        "holes_picked_up": sum(c["holed"] is False for c in holes),
        "shots": len(shots),
        "trees_per_round": round(sum(s["outcome"] == "out_of_bounds" for s in shots) / len(rounds), 2),
        "water_per_round": round(sum(s["outcome"] == "water" for s in shots) / len(rounds), 2),
        "by_distance": bands,
    }


def bench(
    controller_id: str,
    rounds: int = 8,
    seed0: int = 100,
    jobs: int = 1,
    graph=None,
    readout_path: str | None = None,
    log: Callable[[str], None] = print,
) -> dict:
    global _GRAPH, _SPEC
    if rounds < 1:
        raise ValueError("rounds must be at least 1")
    if controller_id != "mock" and graph is None:
        raise ValueError(f"{controller_id} needs the compiled graph")
    _GRAPH, _SPEC = graph, (controller_id, readout_path)
    t0 = time.perf_counter()
    seeds = list(range(seed0, seed0 + rounds))
    out: list[dict] = []
    if jobs <= 1:
        _init_worker()
        for sd in seeds:
            out.append(play_round(sd))
            log(f"  round seed {sd}: {out[-1]['strokes']}  ({time.perf_counter() - t0:.0f} s)")
    else:
        ctx = mp.get_context("fork" if "fork" in mp.get_all_start_methods() else "spawn")
        with ctx.Pool(min(jobs, rounds), initializer=_init_worker) as pool:
            for r in pool.imap_unordered(play_round, seeds):
                out.append(r)
                log(f"  round seed {r['seed']}: {r['strokes']}  ({time.perf_counter() - t0:.0f} s)")
    out.sort(key=lambda r: r["seed"])
    return {
        "bench": BENCH_VERSION,
        "created_utc": datetime.now(UTC).isoformat(),
        "git": git_info(),
        "versions": versions(),
        "controller": out[0]["controller"] if out else {"id": controller_id},
        "readout": readout_path,
        "seeds": seeds,
        "summary": summarize_rounds(out),
        "rounds": [{k: v for k, v in r.items() if k != "controller"} for r in out],
        "wall_s": round(time.perf_counter() - t0, 1),
    }
